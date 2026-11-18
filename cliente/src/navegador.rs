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
//! a vigia devolvendo o foco ao menu. Linux: wmctrl (below, skip_taskbar, skip_pager; o
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
    /// Começo: o menu fica por cima.
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
    // Em QUALQUER fim (PIN aceito, cancelado, timer, navegador que morreu, erro,
    // até pânico) o menu deixa de ficar por cima. No roteiro 17 a tela "Acabou o
    // tempo!" do timer_watchdog ficou sem teclado depois deste caminho.
    let mut menu_solto = false;
    let r = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| laco(s, estado, &mut menu_solto, pausa)));
    if !menu_solto {
        s.soltar_menu();
    }
    match r {
        Ok(veio) => {
            if veio {
                apareceu.store(true, Ordering::SeqCst);
            }
            veio
        }
        Err(e) => std::panic::resume_unwind(e),
    }
}

fn laco<J: Janelas>(
    s: &mut J,
    estado: &AtomicU8,
    menu_solto: &mut bool,
    pausa: &dyn Fn(Instant) -> Duration,
) -> bool {
    let desde = Instant::now();
    s.segurar_menu();
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
            *menu_solto = true;
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
    use std::collections::{HashMap, HashSet};
    use std::sync::{Arc, Mutex};
    use std::time::Instant;

    use windows_sys::Win32::Foundation::{HWND, LPARAM};
    use windows_sys::Win32::System::Com::{CLSCTX_INPROC_SERVER, COINIT_APARTMENTTHREADED, CoCreateInstance, CoInitializeEx};
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        EnumWindows, GWL_EXSTYLE, GetClassNameW, GetForegroundWindow, GetWindowLongPtrW, GetWindowThreadProcessId, HWND_BOTTOM,
        HWND_NOTOPMOST, HWND_TOP, HWND_TOPMOST, IsWindow, IsWindowVisible, SWP_ASYNCWINDOWPOS, SWP_FRAMECHANGED, SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOSIZE, SetWindowLongPtrW,
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
    /// ITaskbarList2 (com MarkFullscreenWindow), ou ITaskbarList se não houver.
    struct Barra(*mut *const [usize; 9], bool);

    const CLSID_TASKBAR_LIST: GUID = GUID::from_u128(0x56fdf344_fd6d_11d0_958a_006097c9a090);
    const IID_ITASKBAR_LIST: GUID = GUID::from_u128(0x56fdf342_fd6d_11d0_958a_006097c9a090);
    const IID_ITASKBAR_LIST2: GUID = GUID::from_u128(0x602d4995_b13a_429b_a66e_1935e44f4317);
    type Metodo = unsafe extern "system" fn(*mut core::ffi::c_void, HWND) -> i32;
    type Marcar = unsafe extern "system" fn(*mut core::ffi::c_void, HWND, i32) -> i32;
    type HrInit = unsafe extern "system" fn(*mut core::ffi::c_void) -> i32;
    type Release = unsafe extern "system" fn(*mut core::ffi::c_void) -> u32;

    impl Barra {
        fn nova() -> Option<Self> {
            unsafe {
                CoInitializeEx(std::ptr::null(), COINIT_APARTMENTTHREADED as u32);
                let mut barra = None;
                for (iid, v2) in [(&IID_ITASKBAR_LIST2, true), (&IID_ITASKBAR_LIST, false)] {
                    let mut p: *mut core::ffi::c_void = std::ptr::null_mut();
                    let hr = CoCreateInstance(&CLSID_TASKBAR_LIST, std::ptr::null_mut(), CLSCTX_INPROC_SERVER, iid, &mut p);
                    if hr >= 0 && !p.is_null() {
                        barra = Some(Barra(p as *mut *const [usize; 9], v2));
                        break;
                    }
                }
                let barra = barra?;
                let p = barra.0 as *mut core::ffi::c_void;
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
        /// Diz à barra de tarefas que a janela é de tela cheia (fica por baixo dela).
        fn tela_cheia(&self, h: HWND) {
            if self.1 {
                unsafe {
                    let f: Marcar = std::mem::transmute(self.vtable(8)); // MarkFullscreenWindow
                    f(self.0 as *mut core::ffi::c_void, h, 1);
                }
            }
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
        /// pids do navegador vistos na última volta
        pids_vistos: Vec<u32>,
        /// quando o navegador pegou o foco (para medir até ele largar)
        perdeu_foco_em: Option<Instant>,
        /// quando o menu foi posto por cima (o pedido é assíncrono)
        segurou_em: Option<Instant>,
        /// janelas com a troca de estilo em andamento (numa thread à parte)
        em_andamento: Arc<Mutex<HashSet<isize>>>,
    }

    impl Sistema {
        pub fn novo(pid: u32, job: Option<Arc<Job>>) -> Self {
            Self {
                pid,
                job,
                barra: None,
                estilos: HashMap::new(),
                avisou_topmost: false,
                pids_vistos: Vec::new(),
                perdeu_foco_em: None,
                segurou_em: None,
                em_andamento: Arc::new(Mutex::new(HashSet::new())),
            }
        }

        /// Se o navegador está com o foco, devolve ao menu (de novo a cada volta,
        /// enquanto ele insistir) e mede no log quanto tempo levou. Roteiro 18: o
        /// foco ficava 410–668 ms no Edge, porque a vigia travava em chamadas
        /// síncronas às janelas do Edge (ocupado abrindo) e do menu (inativo);
        /// agora elas são assíncronas ou feitas numa thread à parte.
        fn checar_foco(&mut self) {
            let frente = unsafe { GetForegroundWindow() };
            let mut pid = 0u32;
            unsafe { GetWindowThreadProcessId(frente, &mut pid) };
            if pid != 0 && self.pids_vistos.contains(&pid) {
                if self.perdeu_foco_em.is_none() {
                    self.perdeu_foco_em = Some(Instant::now());
                    // a classe e a visibilidade dizem que janela era (a do quiosque,
                    // ou uma auxiliar invisível do Chromium)
                    let mut classe = [0u16; 64];
                    let n = unsafe { GetClassNameW(frente, classe.as_mut_ptr(), classe.len() as i32) };
                    let classe = String::from_utf16_lossy(&classe[..n.max(0) as usize]);
                    let visivel = unsafe { IsWindowVisible(frente) } != 0;
                    log::info!(
                        "o navegador pegou o foco (janela {classe}, visível: {visivel}, pid {pid}); devolvendo ao menu"
                    );
                }
                crate::menu::trazer_para_frente();
            } else if let Some(t) = self.perdeu_foco_em.take() {
                // N = quanto tempo uma janela do navegador ficou como a da frente
                let com = if frente == crate::menu::janela_do_menu() { "o menu" } else { "outra janela" };
                log::info!("o navegador largou o foco em {} ms (agora com {com})", t.elapsed().as_millis());
            }
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
            // assíncrono: a vigia não espera o menu (inativo, desenha a cada 500 ms)
            unsafe { SetWindowPos(h, onde, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS) };
        }
    }

    fn estilo(h: HWND) -> isize {
        unsafe { GetWindowLongPtrW(h, GWL_EXSTYLE) }
    }

    impl super::Janelas for Sistema {
        type Id = isize;

        fn listar(&mut self) -> Vec<isize> {
            self.pids_vistos = self.pids();
            let mut busca = Busca { pids: self.pids_vistos.clone(), achadas: Vec::new() };
            unsafe { EnumWindows(Some(visiveis), &mut busca as *mut Busca as LPARAM) };
            busca.achadas.into_iter().map(|h| h as isize).collect()
        }

        fn vivo(&mut self) -> bool {
            !self.pids().is_empty()
        }

        // Sem LockSetForegroundWindow: a trava vale para todos os programas e só
        // sai se quem destrava estiver na frente. No roteiro 17 a tela "Acabou o
        // tempo!" (outro processo) ficou sem teclado. Se o navegador pegar o foco,
        // `manter_menu` devolve ao menu em até 10 ms.
        fn segurar_menu(&mut self) {
            self.menu_por_cima(true);
            self.segurou_em = Some(Instant::now());
            let menu = crate::menu::janela_do_menu();
            log::info!("menu por cima (exstyle {:#x})", estilo(menu));
        }

        fn manter_menu(&mut self, guardadas: &[isize]) {
            self.checar_foco();
            let menu = crate::menu::janela_do_menu();
            if menu.is_null() {
                return;
            }
            // O pedido de "por cima" é assíncrono: logo depois de segurar_menu o
            // estilo ainda não mudou. Era isso o aviso a cada abertura no roteiro 19.
            let assentou = self.segurou_em.is_some_and(|t| t.elapsed().as_millis() > 500);
            if assentou && estilo(menu) & WS_EX_TOPMOST as isize == 0 {
                if !self.avisou_topmost {
                    log::info!("o menu não está \"sempre por cima\"; pondo de novo");
                    self.avisou_topmost = true;
                }
                self.menu_por_cima(true);
            }
            // o Chromium pode refazer o estilo da janela (ex.: ao entrar no quiosque)
            for j in guardadas {
                let ocupada = self.em_andamento.lock().map(|e| e.contains(j)).unwrap_or(true);
                if !ocupada && estilo(*j as HWND) & WS_EX_TOOLWINDOW as isize == 0 {
                    log::info!("o navegador voltou ao Alt+Tab; guardando de novo");
                    self.guardar(*j);
                }
            }
        }

        fn soltar_menu(&mut self) {
            self.menu_por_cima(false);
            log::info!("menu deixou de ficar por cima");
        }

        fn guardar(&mut self, j: isize) {
            // o foco primeiro: a janela que acabou de nascer costuma pegá-lo
            self.checar_foco();
            let h = j as HWND;
            let antes = estilo(h);
            self.estilos.entry(j).or_insert(antes); // o original, para devolver
            let novo = (antes | WS_EX_TOOLWINDOW as isize) & !(WS_EX_APPWINDOW as isize | WS_EX_TOPMOST as isize);
            // Trocar o estilo de uma janela de outro processo espera a thread dela
            // (o Edge, ocupado abrindo): numa thread à parte, a vigia segue olhando o foco.
            if let Ok(mut e) = self.em_andamento.lock() {
                e.insert(j);
            }
            let em_andamento = self.em_andamento.clone();
            let _ = std::thread::Builder::new().name("guardar-janela".into()).spawn(move || {
                let h = j as HWND;
                unsafe {
                    SetWindowLongPtrW(h, GWL_EXSTYLE, novo);
                    if antes & WS_EX_TOPMOST as isize != 0 {
                        SetWindowPos(h, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
                    }
                    SetWindowPos(h, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED);
                }
                if let Ok(mut e) = em_andamento.lock() {
                    e.remove(&j);
                }
            });
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
                // o Edge entrou no quiosque enquanto guardado; sem isto a barra de
                // tarefas ficava por cima da área dos pais (roteiro 17)
                b.tela_cheia(h);
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
        quebrar_em: Option<usize>,
        estado: &'a AtomicU8,
        log: RefCell<Vec<String>>,
    }

    impl Janelas for Falso<'_> {
        type Id = u32;
        fn listar(&mut self) -> Vec<u32> {
            self.volta += 1;
            if Some(self.volta) == self.quebrar_em {
                panic!("erro de teste");
            }
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
        let mut f = Falso { volta: 0, nascer, liberar_em, fechar_em, roubar_foco_em: roubar, quebrar_em: None, estado: &estado, log: RefCell::new(vec![]) };
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
    fn erro_no_meio_tambem_solta_o_menu() {
        // roteiro 17: a tela "Acabou o tempo!" ficou sem teclado; o menu tem de
        // sair do "por cima" em qualquer fim, até num pânico
        let estado = AtomicU8::new(ESPERANDO);
        let apareceu = AtomicBool::new(false);
        let mut f = Falso {
            volta: 0,
            nascer: Some(1),
            liberar_em: None,
            fechar_em: None,
            roubar_foco_em: None,
            quebrar_em: Some(3),
            estado: &estado,
            log: RefCell::new(vec![]),
        };
        let r = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            vigiar(&mut f, &estado, &apareceu, &|_| Duration::from_millis(0))
        }));
        assert!(r.is_err());
        assert_eq!(f.log.into_inner(), ["segurar", "guardar 7", "soltar"]);
    }

    #[test]
    fn soltar_o_menu_acontece_uma_vez_so() {
        for (nascer, liberar, fechar) in [(Some(2), Some(5), None), (Some(5), Some(1), None), (Some(2), None, Some(4))] {
            let (_, log) = rodar(nascer, liberar, fechar, None);
            assert_eq!(log.iter().filter(|l| *l == "soltar").count(), 1, "{log:?}");
        }
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
