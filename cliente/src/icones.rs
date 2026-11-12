//! Ícones de traço do menu (os mesmos de src/frontend/icons.js). O gpui desenha SVG
//! de arquivo com cor própria, então cada ícone vira um arquivo por cor no cache.

use std::path::PathBuf;

const ICONES: &[(&str, &[&str])] = &[
    ("nav-left", &["M15 18l-6-6 6-6"]),
    ("nav-right", &["M9 6l6 6-6 6"]),
    ("back", &["M19 12H5", "M11 18l-6-6 6-6"]),
    ("system", &["M4 7h10", "M18 7h2", "M14 4v6", "M4 17h2", "M10 17h10", "M6 14v6"]),
    ("power", &["M12 2v9", "M6.3 5.8a8 8 0 1 0 11.4 0"]),
    ("exit", &["M10 4H5v16h5", "M14 8l4 4-4 4", "M9 12h9"]),
    ("timer", &["M12 7v5l3 2", "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18", "M9 1h6"]),
    ("close", &["M6 6l12 12", "M18 6L6 18"]),
    ("lock", &["M6 10h12v10H6z", "M8 10V7a4 4 0 0 1 8 0v3", "M12 14v2"]),
    ("battery", &["M3 7h16v10H3z", "M21 10v4"]),
    ("charging", &["M13 2L7 13h5l-1 9 6-12h-5z"]),
    ("battery-low", &["M3 7h16v10H3z", "M21 10v4", "M6 10v4"]),
    ("sunrise", &["M4 18h16", "M6 14a6 6 0 0 1 12 0", "M12 3v3", "M4.9 6.9L7 9", "M19.1 6.9L17 9"]),
    ("sun", &["M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8", "M12 2v2", "M12 20v2", "M4.9 4.9l1.4 1.4", "M17.7 17.7l1.4 1.4", "M2 12h2", "M20 12h2", "M4.9 19.1l1.4-1.4", "M17.7 6.3l1.4-1.4"]),
    ("sunset", &["M4 18h16", "M6 14a6 6 0 0 1 12 0", "M12 3v3", "M4.9 6.9L7 9", "M19.1 6.9L17 9", "M9 21h6"]),
    ("moon", &["M20 15.5A8 8 0 0 1 8.5 4 8.5 8.5 0 1 0 20 15.5"]),
    ("star", &["M12 3l2.7 5.5 6.1.9-4.4 4.3 1 6.1-5.4-2.9-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"]),
];

/// Caminho do SVG do ícone `nome` na cor `cor` (0xRRGGBB); cria na primeira vez.
pub fn icone(nome: &str, cor: u32) -> PathBuf {
    let dir = diretorio();
    let caminho = dir.join(format!("{nome}-{cor:06x}.svg"));
    if !caminho.exists() {
        let tracos = ICONES.iter().find(|(n, _)| *n == nome).map(|(_, t)| *t).unwrap_or(&[]);
        let mut svg = format!(
            "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' width='48' height='48' fill='none' stroke='#{cor:06x}' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>"
        );
        for d in tracos {
            svg.push_str(&format!("<path d='{d}'/>"));
        }
        svg.push_str("</svg>");
        let _ = std::fs::create_dir_all(&dir);
        let temporario = caminho.with_extension("tmp");
        if std::fs::write(&temporario, svg).is_ok() {
            let _ = std::fs::rename(&temporario, &caminho);
        }
    }
    caminho
}

fn diretorio() -> PathBuf {
    let base = std::env::var_os("XDG_CACHE_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".cache")))
        .unwrap_or_else(std::env::temp_dir);
    base.join("cozy-kids-launcher").join("menu-icones")
}
