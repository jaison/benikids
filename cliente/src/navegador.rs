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
//! Área dos pais com PIN no menu: o navegador abre ESCONDIDO enquanto o adulto
//! digita (a partida do Edge leva ~1,5 s num notebook de 2012) e só aparece com
//! o PIN certo (`revelar`). Uma thread vigia as janelas desta abertura:
//! - Windows: esconde (SW_HIDE) toda janela visível dos processos do job assim
//!   que ela surge — janela escondida não entra no Alt+Tab nem na barra de
//!   tarefas; o menu fica "sempre por cima" e trava o SetForegroundWindow dos
//!   outros processos (LockSetForegroundWindow) para o navegador não roubar o
//!   foco; se roubar mesmo assim, o menu pega de volta;
//! - Linux (X11): tira a janela do mapa (xdotool windowunmap), o que também a
//!   tira do Alt+Tab, e devolve o foco ao menu.
//! Ao revelar, as janelas voltam, o navegador vai para a frente e o menu deixa
//! de ficar por cima. Ao fechar, tudo é desfeito do mesmo jeito.

use std::process::{Child, Command};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

pub struct Navegador {
    filho: Child,
    #[cfg(windows)]
    job: Option<Arc<job::Job>>,
    escondido: Option<Escondedor>,
}

/// A thread que mantém as janelas escondidas (ver o topo do arquivo).
struct Escondedor {
    ativo: Arc<AtomicBool>,
    revelar: Arc<AtomicBool>,
}

impl Escondedor {
    fn parar(&self, revelar: bool) {
        self.revelar.store(revelar, Ordering::SeqCst);
        self.ativo.store(false, Ordering::SeqCst);
    }
}

impl Drop for Escondedor {
    fn drop(&mut self) {
        // a thread desfaz o "sempre por cima" e a trava de foco sozinha
        self.ativo.store(false, Ordering::SeqCst);
    }
}

#[cfg_attr(not(any(windows, target_os = "linux")), allow(dead_code))]
/// Intervalo da vigia: curto no começo (a janela nasce em ~1–2 s), depois mais leve.
fn intervalo(desde: Instant) -> Duration {
    let inicio = if cfg!(windows) { Duration::from_millis(10) } else { Duration::from_millis(80) };
    if desde.elapsed() < Duration::from_secs(10) { inicio } else { Duration::from_millis(300) }
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
            escondido: None,
        })
    }

    /// Abre o navegador escondido atrás do menu (só aparece com `revelar`).
    pub fn abrir_escondido(cmd: &mut Command) -> std::io::Result<Self> {
        let mut nav = Self::abrir(cmd)?;
        let ativo = Arc::new(AtomicBool::new(true));
        let revelar = Arc::new(AtomicBool::new(false));
        let (a, r) = (ativo.clone(), revelar.clone());
        let pid = nav.filho.id();
        #[cfg(windows)]
        let job = nav.job.clone();
        let criou = std::thread::Builder::new().name("esconder-navegador".into()).spawn(move || {
            #[cfg(windows)]
            plataforma::vigiar(pid, job, a, r);
            #[cfg(target_os = "linux")]
            plataforma::vigiar(pid, a, r);
            #[cfg(not(any(windows, target_os = "linux")))]
            let _ = (pid, a, r);
        });
        match criou {
            Ok(_) => nav.escondido = Some(Escondedor { ativo, revelar }),
            Err(e) => log::warn!("não deu para esconder o navegador: {e}"),
        }
        Ok(nav)
    }

    /// Mostra o navegador aberto com `abrir_escondido` e passa o foco para ele.
    pub fn revelar(&mut self) {
        if let Some(e) = self.escondido.take() {
            e.parar(true);
        }
    }

    pub fn escondido(&self) -> bool {
        self.escondido.is_some()
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
        if let Some(e) = self.escondido.take() {
            e.parar(false);
        }
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
    use std::sync::Arc;
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::time::Instant;

    use windows_sys::Win32::Foundation::{HWND, LPARAM};
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        EnumWindows, GetForegroundWindow, GetWindowThreadProcessId, HWND_NOTOPMOST, HWND_TOPMOST, IsWindow,
        IsWindowVisible, LSFW_LOCK, LSFW_UNLOCK, LockSetForegroundWindow, SW_HIDE, SW_SHOW, SWP_NOACTIVATE,
        SWP_NOMOVE, SWP_NOSIZE, SetWindowPos, ShowWindow,
    };

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

    fn janelas_visiveis(pids: Vec<u32>) -> Vec<HWND> {
        let mut busca = Busca { pids, achadas: Vec::new() };
        unsafe { EnumWindows(Some(visiveis), &mut busca as *mut Busca as LPARAM) };
        busca.achadas
    }

    fn menu_por_cima(sim: bool) {
        let h = crate::menu::janela_do_menu();
        if h.is_null() {
            return;
        }
        let onde = if sim { HWND_TOPMOST } else { HWND_NOTOPMOST };
        unsafe { SetWindowPos(h, onde, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE) };
    }

    /// Roda numa thread própria: as chamadas que mexem na janela do menu mandam
    /// mensagens para ela, e de dentro do update do gpui isso quebraria
    /// ("RefCell already borrowed").
    pub fn vigiar(pid: u32, job: Option<Arc<Job>>, ativo: Arc<AtomicBool>, revelar: Arc<AtomicBool>) {
        let desde = Instant::now();
        unsafe { LockSetForegroundWindow(LSFW_LOCK) };
        menu_por_cima(true);
        let mut escondidas: Vec<isize> = Vec::new();
        while ativo.load(Ordering::SeqCst) {
            let pids = match &job {
                Some(j) => j.pids(),
                None => vec![pid],
            };
            if pids.is_empty() && desde.elapsed().as_secs() > 2 {
                break; // o navegador já fechou
            }
            let novas = janelas_visiveis(pids);
            for h in &novas {
                unsafe { ShowWindow(*h, SW_HIDE) };
                if !escondidas.contains(&(*h as isize)) {
                    escondidas.push(*h as isize);
                }
            }
            if !novas.is_empty() {
                log::info!("navegador escondido atrás do menu ({} janela(s), {:?})", novas.len(), desde.elapsed());
                let menu = crate::menu::janela_do_menu();
                if !menu.is_null() && unsafe { GetForegroundWindow() } != menu {
                    crate::menu::trazer_para_frente();
                }
            }
            std::thread::sleep(super::intervalo(desde));
        }
        unsafe { LockSetForegroundWindow(LSFW_UNLOCK) };
        if revelar.load(Ordering::SeqCst) {
            let vivas: Vec<HWND> =
                escondidas.iter().map(|h| *h as HWND).filter(|h| unsafe { IsWindow(*h) } != 0).collect();
            for h in &vivas {
                unsafe { ShowWindow(*h, SW_SHOW) };
            }
            if let Some(h) = vivas.first() {
                crate::menu::trazer_janela_para_frente(*h);
            }
            log::info!("navegador revelado ({} janela(s))", vivas.len());
        }
        menu_por_cima(false);
    }
}

#[cfg(target_os = "linux")]
mod plataforma {
    use std::process::{Command, Stdio};
    use std::sync::Arc;
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::time::Instant;

    fn xdotool(args: &[&str]) -> Option<String> {
        let saida = Command::new("xdotool").args(args).stdin(Stdio::null()).stderr(Stdio::null()).output().ok()?;
        Some(String::from_utf8_lossy(&saida.stdout).into_owned())
    }

    /// Mesma ideia do Windows, com o xdotool (já usado pelo menu): a janela do
    /// Firefox sai do mapa assim que aparece e o foco volta ao menu.
    pub fn vigiar(pid: u32, ativo: Arc<AtomicBool>, revelar: Arc<AtomicBool>) {
        let desde = Instant::now();
        let pid = pid.to_string();
        let mut escondidas: Vec<String> = Vec::new();
        while ativo.load(Ordering::SeqCst) {
            let achadas = xdotool(&["search", "--onlyvisible", "--pid", &pid]).unwrap_or_default();
            let novas: Vec<&str> = achadas.split_whitespace().collect();
            for w in &novas {
                xdotool(&["windowunmap", w]);
                if !escondidas.iter().any(|e| e == w) {
                    escondidas.push(w.to_string());
                }
            }
            if !novas.is_empty() {
                log::info!("navegador escondido atrás do menu ({} janela(s), {:?})", novas.len(), desde.elapsed());
                crate::menu::trazer_para_frente();
            }
            std::thread::sleep(super::intervalo(desde));
        }
        if revelar.load(Ordering::SeqCst) {
            for w in &escondidas {
                xdotool(&["windowmap", w]);
            }
            if let Some(w) = escondidas.last() {
                xdotool(&["windowactivate", w]);
            }
            log::info!("navegador revelado ({} janela(s))", escondidas.len());
        }
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
