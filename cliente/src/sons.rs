//! Sons de retorno (opção "sons" do perfil): os mesmos tons sintetizados de
//! src/frontend/feedback-runtime.js (seno com glissando e envelope curto). Os WAV
//! são gerados uma vez no cache e tocados com paplay/pw-play/aplay em segundo plano.

use std::path::PathBuf;
use std::process::{Command, Stdio};

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Som {
    Navegar,
    Abrir,
    Sucesso,
    Bloqueado,
}

impl Som {
    fn tom(self) -> (f32, f32, f32, &'static str) {
        // (frequência inicial, final, duração em s, nome do arquivo)
        match self {
            Som::Navegar => (440., 494., 0.055, "navegar"),
            Som::Abrir => (523., 659., 0.10, "abrir"),
            Som::Sucesso => (659., 880., 0.16, "sucesso"),
            Som::Bloqueado => (262., 196., 0.14, "bloqueado"),
        }
    }
}

const TAXA: u32 = 44_100;

/// Amostras de 16 bits: seno com frequência em rampa exponencial e ganho que sobe
/// em 12 ms e desce exponencialmente (como o Web Audio do menu web).
pub fn sintetizar(f0: f32, f1: f32, duracao: f32) -> Vec<i16> {
    let n = ((duracao + 0.01) * TAXA as f32) as usize;
    let mut fase = 0f32;
    let mut saida = Vec::with_capacity(n);
    let (g_min, g_max) = (0.0001f32, 0.035f32 * 4.0); // um pouco mais alto que o web (alto-falante de notebook)
    for i in 0..n {
        let t = i as f32 / TAXA as f32;
        let k = (t / duracao).min(1.);
        let f = f0 * (f1 / f0).powf(k);
        fase += std::f32::consts::TAU * f / TAXA as f32;
        let ganho = if t < 0.012 {
            g_min * (g_max / g_min).powf(t / 0.012)
        } else if t < duracao {
            g_max * (g_min / g_max).powf((t - 0.012) / (duracao - 0.012))
        } else {
            0.
        };
        saida.push((fase.sin() * ganho * i16::MAX as f32) as i16);
    }
    saida
}

pub fn wav(amostras: &[i16]) -> Vec<u8> {
    let dados = (amostras.len() * 2) as u32;
    let mut b = Vec::with_capacity(44 + dados as usize);
    b.extend_from_slice(b"RIFF");
    b.extend_from_slice(&(36 + dados).to_le_bytes());
    b.extend_from_slice(b"WAVEfmt ");
    b.extend_from_slice(&16u32.to_le_bytes());
    b.extend_from_slice(&1u16.to_le_bytes()); // PCM
    b.extend_from_slice(&1u16.to_le_bytes()); // mono
    b.extend_from_slice(&TAXA.to_le_bytes());
    b.extend_from_slice(&(TAXA * 2).to_le_bytes());
    b.extend_from_slice(&2u16.to_le_bytes());
    b.extend_from_slice(&16u16.to_le_bytes());
    b.extend_from_slice(b"data");
    b.extend_from_slice(&dados.to_le_bytes());
    for a in amostras {
        b.extend_from_slice(&a.to_le_bytes());
    }
    b
}

fn arquivo(som: Som) -> Option<PathBuf> {
    let (f0, f1, d, nome) = som.tom();
    let dir = std::env::var_os("HOME")
        .map(PathBuf::from)?
        .join(".cache/cozy-kids-launcher/menu-sons");
    let caminho = dir.join(format!("{nome}-v1.wav"));
    if !caminho.exists() {
        std::fs::create_dir_all(&dir).ok()?;
        let tmp = caminho.with_extension("tmp");
        std::fs::write(&tmp, wav(&sintetizar(f0, f1, d))).ok()?;
        std::fs::rename(&tmp, &caminho).ok()?;
    }
    Some(caminho)
}

/// Toca o som sem bloquear (um processo curto do player do sistema).
pub fn tocar(som: Som) {
    std::thread::spawn(move || {
        let Some(caminho) = arquivo(som) else { return };
        for player in ["paplay", "pw-play", "aplay"] {
            let mut cmd = Command::new(player);
            if player == "aplay" {
                cmd.arg("-q");
            }
            let ok = cmd
                .arg(&caminho)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status()
                .is_ok_and(|s| s.success());
            if ok {
                return;
            }
        }
    });
}

#[cfg(test)]
mod testes {
    use super::*;

    #[test]
    fn wav_tem_cabecalho_e_tamanho_certos() {
        let a = sintetizar(440., 494., 0.055);
        assert_eq!(a.len(), ((0.065) * TAXA as f32) as usize);
        let w = wav(&a);
        assert_eq!(&w[0..4], b"RIFF");
        assert_eq!(&w[8..16], b"WAVEfmt ");
        assert_eq!(w.len(), 44 + a.len() * 2);
        // termina em silêncio
        assert!(a.last().unwrap().abs() < 50);
    }
}
