//! beni-menu: o menu das crianças do Beni Launcher, nativo (gpui-fast).
//!
//! Fala com o servidor Python local (o mesmo do menu web) e só desenha a tela da
//! criança; a área dos pais continua no navegador. Feito para notebooks antigos:
//! abre em menos de 1 s e gasta ~1/4 da memória do Firefox.
//!
//! Uso: beni-menu [--porta 38431] [--app-root DIR] [--web-cmd firefox]
//!                [--web-familia firefox|chromium] [--web-perfil DIR] [--demo]
//!
//! Sai com código 75 quando não há GPU utilizável (só renderização por CPU):
//! quem chamou (cozy-kids-launcher) volta para o menu no navegador.

// No Windows, sem janela de console atrás do menu.
#![cfg_attr(windows, windows_subsystem = "windows")]

mod api;
mod dados;
mod demo;
mod icones;
mod menu;
mod sons;
mod tema;

use std::borrow::Cow;
use std::path::PathBuf;
use std::time::{Duration, Instant};

use gpui::{App, Bounds, WindowBounds, WindowOptions, prelude::*, px, size};
use gpui_platform::application;

use menu::{Menu, Opcoes};

pub const SEM_GPU: i32 = 75;

fn opcoes() -> Opcoes {
    let casa = PathBuf::from(std::env::var_os("HOME").unwrap_or_default());
    let mut o = Opcoes {
        porta: std::env::var("COZY_KIDS_PORT").ok().and_then(|p| p.parse().ok()).unwrap_or(38431),
        app_root: casa.join(".local/share/cozy-kids-launcher"),
        web_cmd: "firefox".into(),
        web_familia: "firefox".into(),
        web_perfil: casa.join(".cache/cozy-kids-launcher/firefox-profile"),
        demo: false,
    };
    let mut a = std::env::args().skip(1);
    while let Some(x) = a.next() {
        let mut valor = || a.next().unwrap_or_default();
        match x.as_str() {
            "--porta" => o.porta = valor().parse().unwrap_or(o.porta),
            "--app-root" => o.app_root = valor().into(),
            "--web-cmd" => o.web_cmd = valor(),
            "--web-familia" => o.web_familia = valor(),
            "--web-perfil" => o.web_perfil = valor().into(),
            "--demo" => o.demo = true,
            "--versao" | "--version" => {
                println!("beni-menu {}", env!("CARGO_PKG_VERSION"));
                std::process::exit(0);
            }
            outro => eprintln!("beni-menu: opção desconhecida {outro}"),
        }
    }
    o
}

fn main() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("beni_menu=info,warn")).init();
    let mut o = opcoes();
    // Sem servidor (ex.: testar no Windows): modo demonstração. Também quando o
    // executável se chama "*demo*" (dá para abrir com dois cliques).
    let nome = std::env::current_exe().ok().and_then(|p| p.file_name().map(|n| n.to_string_lossy().to_lowercase()));
    if nome.is_some_and(|n| n.contains("demo")) {
        o.demo = true;
    }
    if o.demo {
        o.app_root = demo::preparar_arquivos();
    }
    let t0 = Instant::now();
    // Sem GPU de verdade (ex.: sessão sem acesso ao /dev/dri) o menu nativo ficaria
    // pesado: recusa o llvmpipe e deixa o script voltar para o navegador.
    if std::env::var_os("GPUI_RECUSAR_SOFTWARE").is_none() {
        // SAFETY: ainda não há outras threads.
        unsafe { std::env::set_var("GPUI_RECUSAR_SOFTWARE", "1") };
    }
    application().run(move |cx: &mut App| {
        for f in tema::FONTES {
            match std::fs::read(o.app_root.join("themes/fonts").join(f)) {
                Ok(b) => {
                    if let Err(e) = cx.text_system().add_fonts(vec![Cow::Owned(b)]) {
                        log::warn!("fonte {f}: {e}");
                    }
                }
                Err(e) => log::warn!("fonte {f}: {e}"),
            }
        }
        let bounds = Bounds::centered(None, size(px(1366.0), px(768.0)), cx);
        let opcoes_janela = WindowOptions {
            window_bounds: Some(WindowBounds::Fullscreen(bounds)),
            titlebar: None,
            app_id: Some("beni-menu".into()),
            // atrás de um jogo, o menu quase não desenha
            inactive_frame_interval: Some(Duration::from_millis(500)),
            ..Default::default()
        };
        let o2 = o.clone();
        let janela = cx.open_window(opcoes_janela, move |window, cx| {
            window.set_window_title("Beni");
            cx.new(|cx| {
                let focus = cx.focus_handle();
                window.focus(&focus, cx);
                let mut m = Menu::new(o2, focus);
                m.iniciado = t0;
                m.iniciar(cx);
                cx.observe_window_activation(window, |m: &mut Menu, window, cx| {
                    m.janela_ativada(window.is_window_active(), cx);
                })
                .detach();
                // o xfwm4 ignora o pedido de tela cheia feito na criação da janela
                cx.spawn_in(window, async |_, cx| {
                    for espera in [300u64, 1200] {
                        cx.background_executor().timer(Duration::from_millis(espera)).await;
                        let _ = cx.update(|window, _| {
                            if !window.is_fullscreen() {
                                window.toggle_fullscreen();
                            }
                            // aberto por um processo de fundo, o Windows não dá o foco sozinho
                            #[cfg(windows)]
                            {
                                window.activate_window();
                                menu::trazer_para_frente();
                            }
                        });
                    }
                })
                .detach();
                m
            })
        });
        match janela {
            Ok(_) => {
                log::info!("menu: janela aberta em {:?}", t0.elapsed());
                cx.activate(true);
            }
            Err(e) => {
                log::error!("menu: não deu para abrir a janela ({e:#}); voltando para o navegador");
                std::process::exit(SEM_GPU);
            }
        }
    });
}
