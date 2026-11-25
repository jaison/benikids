//! Modo demonstração (`beni-menu --demo`): o menu abre sozinho, sem o servidor,
//! com dois perfis de exemplo (Herói Aranha e Reino do Gelo). Serve para testar
//! em outra máquina (ex.: Windows) só com o executável. Abrir apps não faz nada;
//! Sair e Esc na tela inicial fecham o programa.

use std::path::{Path, PathBuf};

use serde_json::{Value, json};

const DADOS: &str = include_str!("demo.json");

/// Fontes e fundos dos temas embutidos no executável.
const ARQUIVOS: &[(&str, &[u8])] = &[
    ("fonts/Bangers-Regular.ttf", include_bytes!("../../themes/fonts/Bangers-Regular.ttf")),
    ("fonts/Bungee-Regular.ttf", include_bytes!("../../themes/fonts/Bungee-Regular.ttf")),
    ("fonts/Shojumaru-Regular.ttf", include_bytes!("../../themes/fonts/Shojumaru-Regular.ttf")),
    ("fonts/Fredoka-SemiBold.ttf", include_bytes!("../../themes/fonts/Fredoka-SemiBold.ttf")),
    ("heroi.svg", include_bytes!("../../themes/heroi.svg")),
    ("gelo.svg", include_bytes!("../../themes/gelo.svg")),
    ("blocos.svg", include_bytes!("../../themes/blocos.svg")),
    ("ninja.svg", include_bytes!("../../themes/ninja.svg")),
    ("casinha.svg", include_bytes!("../../themes/casinha.svg")),
    ("castelo.svg", include_bytes!("../../themes/castelo.svg")),
];

/// Grava os temas numa pasta temporária e devolve a "raiz do app" para o menu.
pub fn preparar_arquivos() -> PathBuf {
    let raiz = std::env::temp_dir().join("beni-menu-demo");
    for (rel, bytes) in ARQUIVOS {
        let destino = raiz.join("themes").join(rel);
        if std::fs::metadata(&destino).map(|m| m.len() as usize) .ok() != Some(bytes.len()) {
            if let Some(dir) = destino.parent() {
                let _ = std::fs::create_dir_all(dir);
            }
            let _ = std::fs::write(&destino, bytes);
        }
    }
    raiz
}

pub struct Demo {
    perfis: Value,
    uso: Value,
    ativo: String,
}

impl Demo {
    pub fn new() -> Self {
        let dados: Value = serde_json::from_str(DADOS).expect("demo.json válido");
        Self { perfis: dados["perfis"].clone(), uso: dados["uso"].clone(), ativo: "default".into() }
    }

    fn config(&self) -> Value {
        self.perfis[&self.ativo].clone()
    }

    pub fn responder(&mut self, metodo: &str, caminho: &str, corpo: &Value) -> (u16, Option<Value>) {
        let rota = caminho.split('?').next().unwrap_or("");
        match (metodo, rota) {
            ("GET", "/api/config") => (200, Some(self.config())),
            ("GET", "/api/usage/status") => (200, Some(self.uso.clone())),
            ("GET", "/api/timer/status") => (
                200,
                Some(json!({"active": false, "expired": false, "warning": false, "remainingSeconds": 0})),
            ),
            ("GET", "/api/availability/status") => {
                (200, Some(json!({"profileAllowed": true, "blockedTileIds": [], "limitBlocked": {}})))
            }
            ("GET", "/api/features") => (200, Some(json!({"shutdownAvailable": false, "speechFeedbackAvailable": false}))),
            ("GET", "/api/update/status") => (200, Some(json!({"updateAvailable": false}))),
            ("GET", "/api/cliente/estado") => (200, Some(json!({"voltar": 0}))),
            ("POST", "/api/timer/tela") => (200, Some(json!({"status": "ok"}))),
            ("POST", r) if r.starts_with("/launch/") => (204, None),
            ("POST", "/api/verify-pin") => (200, Some(json!({"valid": true}))),
            ("POST", "/api/profiles/select") => {
                if let Some(id) = corpo.get("profileId").and_then(Value::as_str) {
                    if self.perfis.get(id).is_some() {
                        self.ativo = id.to_string();
                    }
                }
                (200, Some(json!({"status": "ok", "config": self.config()})))
            }
            ("POST", "/exit-kids" | "/shutdown") => {
                log::info!("demonstração: saindo");
                std::process::exit(0)
            }
            _ => (404, None),
        }
    }
}

#[allow(dead_code)]
fn _caminho(_: &Path) {}

#[cfg(test)]
mod testes {
    use super::*;

    #[test]
    fn dados_de_exemplo_tem_dois_perfis_e_trocam() {
        let mut d = Demo::new();
        let (s, c) = d.responder("GET", "/api/config", &Value::Null);
        assert_eq!(s, 200);
        assert!(c.unwrap()["tiles"].as_array().unwrap().len() > 10);
        let (_, r) = d.responder("POST", "/api/profiles/select", &json!({"profileId": "child-2501513b5fcb"}));
        assert_eq!(r.unwrap()["config"]["theme"], "gelo");
        assert_eq!(d.responder("POST", "/launch/x", &Value::Null).0, 204);
    }
}
