//! Embute o ícone da marca (src/beni.ico, o mesmo do atalho) no beni-menu.exe.
//! O gpui no Windows usa o recurso nº 1 como ícone da janela (LoadImageW(1)),
//! então isto vale para o Explorer, a barra de tarefas e o Alt+Tab.
//! Fora do Windows não faz nada (o ícone da janela no X11 vai em main.rs).

use std::{env, fs, path::PathBuf};

fn main() {
    let raiz = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let ico = raiz.join("../src/beni.ico");
    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-changed={}", ico.display());
    if env::var("CARGO_CFG_TARGET_OS").as_deref() != Ok("windows") {
        return;
    }
    let ico = ico.canonicalize().expect("src/beni.ico não encontrado");
    // caminho absoluto no .rc (o rc.exe resolve relativos pela pasta atual)
    let caminho = ico.to_str().unwrap().trim_start_matches(r"\\?\").replace('\\', "\\\\");
    let rc = PathBuf::from(env::var("OUT_DIR").unwrap()).join("beni-menu.rc");
    fs::write(&rc, format!("1 ICON \"{caminho}\"\n")).unwrap();
    embed_resource::compile(&rc, embed_resource::NONE)
        .manifest_required()
        .unwrap();
}
