//! O navegador que o menu abre para as páginas web (área dos pais, sites, mídia).
//!
//! No Windows o Chrome/Edge é uma árvore de processos, e o processo que o menu
//! criou nem sempre é o que segura a janela: se outro msedge.exe com o mesmo
//! perfil ainda está de pé, o novo só repassa o endereço para ele e sai na hora
//! (e numa atualização o navegador se reabre como outro processo). Matar só o
//! processo criado, ou achar que o navegador fechou porque ele saiu, deixava uma
//! janela viva e sem dono: a próxima "área dos pais" caía nela, só com o fundo.
//! Por isso, no Windows, tudo o que nasce dessa abertura entra num Job Object:
//! "está aberto" = ainda há processo no job; fechar = encerrar o job inteiro.
//! O navegador dos pais (fora do Benikids) nunca está no job e não é tocado.
//!
//! Área dos pais com PIN no menu: o navegador abre ATRÁS do menu enquanto o
//! adulto digita (a partida do Edge leva ~1,5 s num notebook de 2012) e vem para
//! a frente com o PIN certo (`liberar`). Uma thread vigia as janelas desta
//! abertura (`vigiar`, igual nos dois sistemas):
//! - esperando o PIN: o menu fica "sempre por cima" e com o foco; cada janela
//!   do navegador que nasce é guardada atrás dele, fora do Alt+Tab e da barra
//!   de tarefas. NÃO é escondida: o Chromium escondido (SW_HIDE) para de
//!   desenhar e volta todo branco;
//! - PIN aceito: a janela guardada volta ao normal e vem para a frente; se ela
//!   ainda não nasceu, vem para a frente quando nascer;
//! - desistiram: o menu deixa de ficar por cima e o navegador é fechado.
//! Windows: estilo WS_EX_TOOLWINDOW (fora do Alt+Tab) + ITaskbarList (barra) +
//! LockSetForegroundWindow. Linux: wmctrl (below, skip_taskbar, skip_pager; o
//! menu "above") + xdotool para o foco.

use std::process::{Child, Command};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU8, Ordering};
use std::time::{Duration, Instant};

pub struct Navegador {
    filho: Child,
    #[cfg(windows)]
    job: Option<Arc<job::Job>>,
    vigia: Option<Vigia>,
}

// Estados da vigia de uma abertura "atrás do menu".
const ESPERANDO: u8 = 0; // PIN ainda na tela: janelas guardadas atrás do menu
const LIBERADO: u8 = 1; // PIN aceito: a janela (já aberta ou a que nascer) vem para a frente
const FECHANDO: u8 = 2; // desistiram: só desfaz o "menu por cima"

/// A thread que cuida das janelas desta abertura (ver o topo do arquivo).
struct Vigia {
    estado: Arc<AtomicU8>,
    apareceu: Arc<AtomicBool>,
}

impl Drop for Vigia {
    fn drop(&mut self) {
        // a thread desfaz o "menu por cima" e a trava de foco sozinha
        let _ = self.estado.compare_exchange(ESPERANDO, FECHANDO, Ordering::SeqCst, Ordering::SeqCst);
        let _ = self.estado.compare_exchange(LIBERADO, FECHANDO, Ordering::SeqCst, Ordering::SeqCst);
    }
}

/// O que a vigia precisa do sistema de janelas. `Id` identifica uma janela do
/// navegador desta abertura.
pub(crate) trait Janelas {
    type Id: Copy + PartialEq + std::fmt::Debug;
    /// Janelas visíveis do navegador desta abertura.
    fn listar(&mut self) -> Vec<Self::Id>;
    /// O navegador ainda tem processo?
    fn vivo(&mut self) -> bool;
    /// Começo: o menu fica por cima e os outros não tomam o foco.
    fn segurar_menu(&mut self);
    /// Enquanto espera: confere se o menu continua por cima e com o foco.
    fn manter_menu(&mut self, guardadas: &[Self::Id]);
    /// Fim da espera: o menu deixa de ficar por cima.
    fn soltar_menu(&mut self);
    /// Guarda a janela atrás do menu, fora do Alt+Tab e da barra de tarefas
    /// (sem esconder: o Chromium escondido para de desenhar e volta branco).
    fn guardar(&mut self, j: Self::Id);
    /// Desfaz o `guardar`.
    fn devolver(&mut self, j: Self::Id);
    /// Traz para a frente, com o foco.
    fn frente(&mut self, j: Self::Id);
}

#[cfg_attr(not(any(windows, target_os = "linux")), allow(dead_code))]
/// Intervalo da vigia: curto no começo (a janela nasce em ~1–2 s), depois mais leve.
fn intervalo(desde: Instant) -> Duration {
    let inicio = if cfg!(windows) { Duration::from_millis(10) } else { Duration::from_millis(80) };
    if desde.elapsed() < Duration::from_secs(10) { inicio } else { Duration::from_millis(300) }
}

/// Quanto tempo, depois do PIN aceito, a vigia ainda espera a janela nascer.
const ESPERA_JANELA: Duration = Duration::from_secs(30);

#[cfg_attr(not(any(windows, target_os = "linux", test)), allow(dead_code))]
/// O laço da vigia, igual nos dois sistemas. Devolve se alguma janela veio para a frente.
pub(crate) fn vigiar<J: Janelas>(
    s: &mut J,
    estado: &AtomicU8,
    apareceu: &AtomicBool,
    pausa: &dyn Fn(Instant) -> Duration,
) -> bool {
    let desde = Instant::now();
    s.segurar_menu();
    let mut menu_solto = false;
    let mut guardadas: Vec<J::Id> = Vec::new();
    let mut liberado_em: Option<Instant> = None;
    let veio = 'vigia: loop {
        let agora = estado.load(Ordering::SeqCst);
        if agora == FECHANDO {
            break false;
        }
        if agora == LIBERADO && liberado_em.is_none() {
            liberado_em = Some(Instant::now());
            s.soltar_menu();
            menu_solto = true;
            for j in &guardadas {
                s.devolver(*j);
            }
            if let Some(j) = guardadas.first() {
                s.frente(*j);
                log::info!("navegador na frente ({} janela(s) guardada(s), {:?})", guardadas.len(), desde.elapsed());
                break true;
            }
            log::info!("PIN aceito antes de o navegador ter janela; ela vem para a frente quando nascer");
        }
        let vistas = s.listar();
        for j in vistas {
            if guardadas.contains(&j) {
                continue;
            }
            if liberado_em.is_some() {
                s.frente(j);
                log::info!("navegador na frente ao nascer ({:?} depois do clique)", desde.elapsed());
                break 'vigia true;
            }
            s.guardar(j);
            guardadas.push(j);
            log::info!("navegador guardado atrás do menu ({:?})", desde.elapsed());
        }
        if liberado_em.is_none() {
            s.manter_menu(&guardadas);
        } else if liberado_em.is_some_and(|t| t.elapsed() > ESPERA_JANELA) {
            log::warn!("o navegador não abriu janela depois do PIN");
            break false;
        }
        if desde.elapsed() > Duration::from_secs(3) && !s.vivo() {
            break false; // o navegador já fechou
        }
        std::thread::sleep(pausa(desde));
    };
    if !menu_solto {
        s.soltar_menu();
    }
    if veio {
        apareceu.store(true, Ordering::SeqCst);
    }
    veio
}

impl Navegador {
    pub fn abrir(cmd: &mut Command) -> std::io::Result<Self> {
        let filho = cmd.spawn()?;
        #[cfg(windows)]
        let job = job::Job::novo_com(&filho).map(Arc::new);
        #[cfg(windows)]
        if job.is_none() {
            log::warn!("navegador fora de um job: só o processo {} será fechado", filho.id());
        }
        Ok(Self {
            filho,
            #[cfg(windows)]
            job,
            vigia: None,
        })
    }

    /// Abre o navegador atrás do menu (só vem para a frente com `liberar`).
    pub fn abrir_atras(cmd: &mut Command) -> std::io::Result<Self> {
        let mut nav = Self::abrir(cmd)?;
        let estado = Arc::new(AtomicU8::new(ESPERANDO));
        let apareceu = Arc::new(AtomicBool::new(false));
        let (e, a) = (estado.clone(), apareceu.clone());
        let pid = nav.filho.id();
        #[cfg(windows)]
        let job = nav.job.clone();
        let criou = std::thread::Builder::new().name("vigia-navegador".into()).spawn(move || {
            #[cfg(windows)]
            vigiar(&mut plataforma::Sistema::novo(pid, job), &e, &a, &intervalo);
            #[cfg(target_os = "linux")]
            vigiar(&mut plataforma::Sistema::novo(pid), &e, &a, &intervalo);
            #[cfg(not(any(windows, target_os = "linux")))]
            let _ = (pid, e, a);
        });
        match criou {
            Ok(_) => nav.vigia = Some(Vigia { estado, apareceu }),
            Err(e) => log::warn!("não deu para vigiar o navegador: {e}"),
        }
        Ok(nav)
    }

    /// PIN aceito: a janela (já aberta ou a que ainda vai nascer) vem para a frente.
    pub fn liberar(&mut self) {
        if let Some(v) = &self.vigia {
            let _ = v.estado.compare_exchange(ESPERANDO, LIBERADO, Ordering::SeqCst, Ordering::SeqCst);
        }
    }

    /// Ainda esperando o PIN (aberto com `abrir_atras` e não liberado)?
    pub fn esperando_pin(&self) -> bool {
        self.vigia.as_ref().is_some_and(|v| v.estado.load(Ordering::SeqCst) == ESPERANDO)
    }

    /// Liberado e ainda sem janela na frente (o menu mostra "Abrindo…").
    pub fn chegando(&self) -> bool {
        self.vigia.as_ref().is_some_and(|v| {
            v.estado.load(Ordering::SeqCst) == LIBERADO && !v.apareceu.load(Ordering::SeqCst)
        })
    }

    /// Traz para a frente um navegador já aberto (ex.: "Pais" clicado de novo).
    pub fn trazer_para_frente(&self) {
        let pid = self.filho.id();
        #[cfg(windows)]
        let job = self.job.clone();
        let _ = std::thread::Builder::new().name("frente-navegador".into()).spawn(move || {
            #[cfg(windows)]
            let mut s = plataforma::Sistema::novo(pid, job);
            #[cfg(target_os = "linux")]
            let mut s = plataforma::Sistema::novo(pid);
            #[cfg(any(windows, target_os = "linux"))]
            if let Some(j) = s.listar().first() {
                s.frente(*j);
            }
            #[cfg(not(any(windows, target_os = "linux")))]
            let _ = pid;
        });
    }

    pub fn id(&self) -> u32 {
        self.filho.id()
    }

    /// Ainda tem janela do navegador desta abertura?
    pub fn aberto(&mut self) -> bool {
        let filho_vivo = matches!(self.filho.try_wait(), Ok(None));
        #[cfg(windows)]
        if let Some(job) = &self.job {
            let n = job.processos();
            if !filho_vivo && n > 0 {
                log::info!("o processo {} saiu, mas o navegador segue com {n} processo(s)", self.filho.id());
            }
            return n > 0;
        }
        filho_vivo
    }

    /// Fecha o navegador desta abertura (TERM no Linux, para ele salvar o perfil;
    /// no Windows, a árvore inteira).
    pub fn fechar(&mut self) {
        self.vigia = None; // a thread desfaz o "menu por cima"
        #[cfg(unix)]
        {
            let pid = self.filho.id().to_string();
            let _ = Command::new("kill").args(["-TERM", &pid]).status();
        }
        #[cfg(windows)]
        if let Some(job) = &self.job {
            job.encerrar();
            return;
        }
        #[cfg(not(unix))]
        {
            let _ = self.filho.kill();
        }
    }
}

#[cfg(windows)]
mod plataforma {
    use std::collections::HashMap;
    use std::sync::Arc;

    use windows_sys::Win32::Foundation::{HWND, LPARAM};
    use windows_sys::Win32::System::Com::{CLSCTX_INPROC_SERVER, COINIT_APARTMENTTHREADED, CoCreateInstance, CoInitializeEx};
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        EnumWindows, GWL_EXSTYLE, GetForegroundWindow, GetWindowLongPtrW, GetWindowThreadProcessId, HWND_BOTTOM,
        HWND_NOTOPMOST, HWND_TOP, HWND_TOPMOST, IsWindow, IsWindowVisible, LSFW_LOCK, LSFW_UNLOCK,
        LockSetForegroundWindow, SWP_FRAMECHANGED, SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOSIZE, SetWindowLongPtrW,
        SetWindowPos, WS_EX_APPWINDOW, WS_EX_TOOLWINDOW, WS_EX_TOPMOST,
    };
    use windows_sys::core::GUID;

    use super::job::Job;

    struct Busca {
        pids: Vec<u32>,
        achadas: Vec<HWND>,
    }

    unsafe extern "system" fn visiveis(h: HWND, dados: LPARAM) -> i32 {
        unsafe {
            let busca = &mut *(dados as *mut Busca);
            let mut pid = 0u32;
            GetWindowThreadProcessId(h, &mut pid);
            if busca.pids.contains(&pid) && IsWindowVisible(h) != 0 {
                busca.achadas.push(h);
            }
        }
        1
    }

    /// ITaskbarList (shobjidl.h), pela tabela de funções: tira e põe o botão da
    /// janela na barra de tarefas sem esconder a janela.
    struct Barra(*mut *const [usize; 8]);

    const CLSID_TASKBAR_LIST: GUID = GUID::from_u128(0x56fdf344_fd6d_11d0_958a_006097c9a090);
    const IID_ITASKBAR_LIST: GUID = GUID::from_u128(0x56fdf342_fd6d_11d0_958a_006097c9a090);
    type Metodo = unsafe extern "system" fn(*mut core::ffi::c_void, HWND) -> i32;
    type HrInit = unsafe extern "system" fn(*mut core::ffi::c_void) -> i32;
    type Release = unsafe extern "system" fn(*mut core::ffi::c_void) -> u32;

    impl Barra {
        fn nova() -> Option<Self> {
            unsafe {
                CoInitializeEx(std::ptr::null(), COINIT_APARTMENTTHREADED as u32);
                let mut p: *mut core::ffi::c_void = std::ptr::null_mut();
                let hr = CoCreateInstance(
                    &CLSID_TASKBAR_LIST,
                    std::ptr::null_mut(),
                    CLSCTX_INPROC_SERVER,
                    &IID_ITASKBAR_LIST,
                    &mut p,
                );
                if hr < 0 || p.is_null() {
                    return None;
                }
                let barra = Barra(p as *mut *const [usize; 8]);
                let init: HrInit = std::mem::transmute(barra.vtable(3));
                init(p);
                Some(barra)
            }
        }
        unsafe fn vtable(&self, i: usize) -> usize {
            unsafe { (**self.0)[i] }
        }
        fn chamar(&self, i: usize, h: HWND) {
            unsafe {
                let f: Metodo = std::mem::transmute(self.vtable(i));
                f(self.0 as *mut core::ffi::c_void, h);
            }
        }
        fn tirar(&self, h: HWND) {
            self.chamar(5, h); // DeleteTab
        }
        fn por(&self, h: HWND) {
            self.chamar(4, h); // AddTab
        }
    }

    impl Drop for Barra {
        fn drop(&mut self) {
            unsafe {
                let f: Release = std::mem::transmute(self.vtable(2));
                f(self.0 as *mut core::ffi::c_void);
            }
        }
    }

    pub struct Sistema {
        pid: u32,
        job: Option<Arc<Job>>,
        barra: Option<Barra>,
        estilos: HashMap<isize, isize>,
        avisou_topmost: bool,
    }

    impl Sistema {
        pub fn novo(pid: u32, job: Option<Arc<Job>>) -> Self {
            Self { pid, job, barra: None, estilos: HashMap::new(), avisou_topmost: false }
        }

        fn pids(&self) -> Vec<u32> {
            match &self.job {
                Some(j) => j.pids(),
                None => vec![self.pid],
            }
        }

        fn menu_por_cima(&self, sim: bool) {
            let h = crate::menu::janela_do_menu();
            if h.is_null() {
                log::warn!("janela do menu não encontrada para ficar por cima");
                return;
            }
            let onde = if sim { HWND_TOPMOST } else { HWND_NOTOPMOST };
            unsafe { SetWindowPos(h, onde, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE) };
        }
    }

    fn estilo(h: HWND) -> isize {
        unsafe { GetWindowLongPtrW(h, GWL_EXSTYLE) }
    }

    impl super::Janelas for Sistema {
        type Id = isize;

        fn listar(&mut self) -> Vec<isize> {
            let mut busca = Busca { pids: self.pids(), achadas: Vec::new() };
            unsafe { EnumWindows(Some(visiveis), &mut busca as *mut Busca as LPARAM) };
            busca.achadas.into_iter().map(|h| h as isize).collect()
        }

        fn vivo(&mut self) -> bool {
            !self.pids().is_empty()
        }

        fn segurar_menu(&mut self) {
            unsafe { LockSetForegroundWindow(LSFW_LOCK) };
            self.menu_por_cima(true);
            let menu = crate::menu::janela_do_menu();
            log::info!("menu por cima (exstyle {:#x})", estilo(menu));
        }

        fn manter_menu(&mut self, guardadas: &[isize]) {
            let menu = crate::menu::janela_do_menu();
            if menu.is_null() {
                return;
            }
            if estilo(menu) & WS_EX_TOPMOST as isize == 0 {
                if !self.avisou_topmost {
                    log::warn!("o menu perdeu o \"sempre por cima\"; pondo de novo");
                    self.avisou_topmost = true;
                }
                self.menu_por_cima(true);
            }
            // o Chromium pode refazer o estilo da janela (ex.: ao entrar no quiosque)
            for j in guardadas {
                if estilo(*j as HWND) & WS_EX_TOOLWINDOW as isize == 0 {
                    log::info!("o navegador voltou ao Alt+Tab; guardando de novo");
                    self.guardar(*j);
                }
            }
            let frente = unsafe { GetForegroundWindow() } as isize;
            if guardadas.contains(&frente) {
                log::info!("o navegador pegou o foco; devolvendo ao menu");
                crate::menu::trazer_para_frente();
            }
        }

        fn soltar_menu(&mut self) {
            unsafe { LockSetForegroundWindow(LSFW_UNLOCK) };
            self.menu_por_cima(false);
        }

        fn guardar(&mut self, j: isize) {
            let h = j as HWND;
            let antes = estilo(h);
            self.estilos.entry(j).or_insert(antes); // o original, para devolver
            let novo = (antes | WS_EX_TOOLWINDOW as isize) & !(WS_EX_APPWINDOW as isize | WS_EX_TOPMOST as isize);
            unsafe {
                SetWindowLongPtrW(h, GWL_EXSTYLE, novo);
                if antes & WS_EX_TOPMOST as isize != 0 {
                    SetWindowPos(h, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
                }
                SetWindowPos(h, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED);
            }
            if self.barra.is_none() {
                self.barra = Barra::nova();
            }
            if let Some(b) = &self.barra {
                b.tirar(h);
            }
        }

        fn devolver(&mut self, j: isize) {
            let h = j as HWND;
            if unsafe { IsWindow(h) } == 0 {
                return;
            }
            if let Some(antes) = self.estilos.remove(&j) {
                unsafe {
                    SetWindowLongPtrW(h, GWL_EXSTYLE, antes & !(WS_EX_TOPMOST as isize));
                    SetWindowPos(h, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED);
                }
            }
            if let Some(b) = &self.barra {
                b.por(h);
            }
        }

        fn frente(&mut self, j: isize) {
            crate::menu::trazer_janela_para_frente(j as HWND);
        }
    }
}

#[cfg(target_os = "linux")]
mod plataforma {
    use std::process::{Command, Stdio};

    fn rodar(prog: &str, args: &[&str]) -> Option<String> {
        let saida = Command::new(prog).args(args).stdin(Stdio::null()).stderr(Stdio::null()).output().ok()?;
        Some(String::from_utf8_lossy(&saida.stdout).into_owned())
    }

    fn janelas_do_pid(pid: &str, so_visiveis: bool) -> Vec<u64> {
        let mut args = vec!["search"];
        if so_visiveis {
            args.push("--onlyvisible");
        }
        args.extend(["--pid", pid]);
        rodar("xdotool", &args)
            .unwrap_or_default()
            .split_whitespace()
            .filter_map(|w| w.parse().ok())
            .collect()
    }

    fn estados(w: u64, acao: &str, quais: &str) {
        let id = format!("{w:#x}");
        rodar("wmctrl", &["-i", "-r", &id, "-b", &format!("{acao},{quais}")]);
    }

    /// Com o xdotool e o wmctrl (já usados pelo Benikids): a janela do Firefox
    /// fica mapeada, abaixo das outras e fora da barra/pager e do Alt+Tab do
    /// xfwm4; o menu fica "acima" e recupera o foco se o Firefox pegar.
    pub struct Sistema {
        pid: String,
        menu: Option<u64>,
    }

    impl Sistema {
        pub fn novo(pid: u32) -> Self {
            Self { pid: pid.to_string(), menu: None }
        }
    }

    impl super::Janelas for Sistema {
        type Id = u64;

        fn listar(&mut self) -> Vec<u64> {
            janelas_do_pid(&self.pid, true)
        }

        fn vivo(&mut self) -> bool {
            std::path::Path::new(&format!("/proc/{}", self.pid)).exists()
        }

        fn segurar_menu(&mut self) {
            self.menu = janelas_do_pid(&std::process::id().to_string(), true).first().copied();
            if let Some(m) = self.menu {
                estados(m, "add", "above");
            }
        }

        fn manter_menu(&mut self, guardadas: &[u64]) {
            let ativa = rodar("xdotool", &["getactivewindow"]).and_then(|s| s.trim().parse::<u64>().ok());
            if ativa.is_some_and(|a| guardadas.contains(&a)) {
                log::info!("o navegador pegou o foco; devolvendo ao menu");
                crate::menu::trazer_para_frente();
            }
        }

        fn soltar_menu(&mut self) {
            if let Some(m) = self.menu {
                estados(m, "remove", "above");
            }
        }

        fn guardar(&mut self, j: u64) {
            estados(j, "add", "skip_taskbar,skip_pager");
            estados(j, "add", "below");
            crate::menu::trazer_para_frente();
        }

        fn devolver(&mut self, j: u64) {
            estados(j, "remove", "below");
            estados(j, "remove", "skip_taskbar,skip_pager");
        }

        fn frente(&mut self, j: u64) {
            rodar("xdotool", &["windowactivate", &j.to_string()]);
        }
    }
}

#[cfg(test)]
mod testes {
    use super::*;
    use std::cell::RefCell;

    /// Sistema de janelas de mentira: `nascer` diz em que volta do laço a janela
    /// aparece; `liberar_em` muda o estado para LIBERADO nessa volta.
    struct Falso<'a> {
        volta: usize,
        nascer: Option<usize>,
        liberar_em: Option<usize>,
        fechar_em: Option<usize>,
        roubar_foco_em: Option<usize>,
        estado: &'a AtomicU8,
        log: RefCell<Vec<String>>,
    }

    impl Janelas for Falso<'_> {
        type Id = u32;
        fn listar(&mut self) -> Vec<u32> {
            self.volta += 1;
            if Some(self.volta) == self.liberar_em {
                self.estado.store(LIBERADO, Ordering::SeqCst);
            }
            if Some(self.volta) == self.fechar_em {
                self.estado.store(FECHANDO, Ordering::SeqCst);
            }
            if self.nascer.is_some_and(|n| self.volta >= n) { vec![7] } else { vec![] }
        }
        fn vivo(&mut self) -> bool {
            true
        }
        fn segurar_menu(&mut self) {
            self.log.borrow_mut().push("segurar".into());
        }
        fn manter_menu(&mut self, g: &[u32]) {
            if Some(self.volta) == self.roubar_foco_em && !g.is_empty() {
                self.log.borrow_mut().push("foco-de-volta".into());
            }
        }
        fn soltar_menu(&mut self) {
            self.log.borrow_mut().push("soltar".into());
        }
        fn guardar(&mut self, j: u32) {
            self.log.borrow_mut().push(format!("guardar {j}"));
        }
        fn devolver(&mut self, j: u32) {
            self.log.borrow_mut().push(format!("devolver {j}"));
        }
        fn frente(&mut self, j: u32) {
            self.log.borrow_mut().push(format!("frente {j}"));
        }
    }

    fn rodar(nascer: Option<usize>, liberar_em: Option<usize>, fechar_em: Option<usize>, roubar: Option<usize>) -> (bool, Vec<String>) {
        let estado = AtomicU8::new(ESPERANDO);
        let apareceu = AtomicBool::new(false);
        let mut f = Falso { volta: 0, nascer, liberar_em, fechar_em, roubar_foco_em: roubar, estado: &estado, log: RefCell::new(vec![]) };
        let veio = vigiar(&mut f, &estado, &apareceu, &|_| Duration::from_millis(0));
        assert_eq!(veio, apareceu.load(Ordering::SeqCst));
        (veio, f.log.into_inner())
    }

    #[test]
    fn pin_antes_da_janela_nascer_traz_a_janela_quando_ela_nasce() {
        // defeito A do pacote 13: PIN 269 ms depois do clique, janela aos 1091 ms
        let (veio, log) = rodar(Some(5), Some(1), None, None);
        assert!(veio);
        assert_eq!(log, ["segurar", "soltar", "frente 7"]);
    }

    #[test]
    fn pin_com_a_janela_ja_guardada_devolve_e_traz_para_a_frente() {
        let (veio, log) = rodar(Some(2), Some(6), None, Some(3));
        assert!(veio);
        assert_eq!(log, ["segurar", "guardar 7", "foco-de-volta", "soltar", "devolver 7", "frente 7"]);
    }

    #[test]
    fn desistir_so_solta_o_menu() {
        let (veio, log) = rodar(Some(2), None, Some(4), None);
        assert!(!veio);
        assert_eq!(log, ["segurar", "guardar 7", "soltar"]);
    }

    #[test]
    fn nunca_esconde_a_janela() {
        // o Chromium escondido (SW_HIDE) voltava todo branco: só guardar/devolver
        let (_, log) = rodar(Some(1), Some(3), None, None);
        assert!(log.iter().all(|l| !l.contains("esconder")));
        assert_eq!(log.iter().filter(|l| l.starts_with("guardar")).count(), 1);
    }
}

#[cfg(windows)]
mod job {
    use std::os::windows::io::AsRawHandle;
    use std::process::Child;

    use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
        JOBOBJECT_BASIC_ACCOUNTING_INFORMATION, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JobObjectBasicAccountingInformation, JobObjectBasicProcessIdList, JobObjectExtendedLimitInformation,
        QueryInformationJobObject, SetInformationJobObject, TerminateJobObject,
    };

    pub struct Job(HANDLE);

    // O handle do job é usado também pela thread que esconde as janelas.
    unsafe impl Send for Job {}
    unsafe impl Sync for Job {}

    impl Job {
        /// Cria o job e põe o navegador nele. Os processos que ele abrir depois
        /// (abas, GPU, o próprio navegador reaberto) entram junto.
        pub fn novo_com(filho: &Child) -> Option<Self> {
            unsafe {
                let h = CreateJobObjectW(std::ptr::null(), std::ptr::null());
                if h.is_null() {
                    return None;
                }
                let job = Job(h);
                // se o menu cair, o navegador vai junto (o Windows fecha o job)
                let mut limite: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
                limite.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                SetInformationJobObject(
                    h,
                    JobObjectExtendedLimitInformation,
                    &limite as *const _ as *const core::ffi::c_void,
                    std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                );
                if AssignProcessToJobObject(h, filho.as_raw_handle() as HANDLE) == 0 {
                    return None;
                }
                Some(job)
            }
        }

        pub fn processos(&self) -> u32 {
            unsafe {
                let mut info: JOBOBJECT_BASIC_ACCOUNTING_INFORMATION = std::mem::zeroed();
                let ok = QueryInformationJobObject(
                    self.0,
                    JobObjectBasicAccountingInformation,
                    &mut info as *mut _ as *mut core::ffi::c_void,
                    std::mem::size_of::<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>() as u32,
                    std::ptr::null_mut(),
                );
                if ok == 0 { 0 } else { info.ActiveProcesses }
            }
        }

        /// Processos que estão no job agora.
        pub fn pids(&self) -> Vec<u32> {
            #[repr(C)]
            struct Lista {
                atribuidos: u32,
                na_lista: u32,
                ids: [usize; 256],
            }
            unsafe {
                let mut lista: Lista = std::mem::zeroed();
                let ok = QueryInformationJobObject(
                    self.0,
                    JobObjectBasicProcessIdList,
                    &mut lista as *mut _ as *mut core::ffi::c_void,
                    std::mem::size_of::<Lista>() as u32,
                    std::ptr::null_mut(),
                );
                if ok == 0 {
                    return Vec::new();
                }
                let n = (lista.na_lista as usize).min(lista.ids.len());
                lista.ids[..n].iter().map(|p| *p as u32).collect()
            }
        }

        pub fn encerrar(&self) {
            unsafe {
                TerminateJobObject(self.0, 1);
            }
        }
    }

    impl Drop for Job {
        fn drop(&mut self) {
            unsafe {
                CloseHandle(self.0);
            }
        }
    }
}
