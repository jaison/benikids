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

use std::process::{Child, Command};

pub struct Navegador {
    filho: Child,
    #[cfg(windows)]
    job: Option<job::Job>,
}

impl Navegador {
    pub fn abrir(cmd: &mut Command) -> std::io::Result<Self> {
        let filho = cmd.spawn()?;
        #[cfg(windows)]
        let job = job::Job::novo_com(&filho);
        #[cfg(windows)]
        if job.is_none() {
            log::warn!("navegador fora de um job: só o processo {} será fechado", filho.id());
        }
        Ok(Self {
            filho,
            #[cfg(windows)]
            job,
        })
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
mod job {
    use std::os::windows::io::AsRawHandle;
    use std::process::Child;

    use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
        JOBOBJECT_BASIC_ACCOUNTING_INFORMATION, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JobObjectBasicAccountingInformation, JobObjectExtendedLimitInformation, QueryInformationJobObject,
        SetInformationJobObject, TerminateJobObject,
    };

    pub struct Job(HANDLE);

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
