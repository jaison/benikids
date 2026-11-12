//! Temas da tela da criança, traduzidos de src/frontend/styles.css e cozy-temas.css.
//! Só o que a tela da criança usa: fundo, título, cartões, foco e botões pequenos.

use gpui::{BoxShadow, Hsla, point, px, rgb, rgba};

#[derive(Clone, Copy, PartialEq)]
pub enum Fundo {
    /// Gradiente vertical (bg1 → bg2).
    Cores,
    /// Imagem em /themes (cobre a tela) sobre a cor bg1.
    Imagem(&'static str),
}

#[derive(Clone, Copy, PartialEq)]
pub enum Enfeite {
    Nenhum,
    /// Floco de neve no canto (Reino do Gelo).
    Floco,
    /// Coroa em cima (Castelo Encantado).
    Coroa,
    /// Telhadinho em cima (Casinha Mágica).
    Telhado,
    /// Pinos de bloco de montar em cima.
    Pinos,
}

#[derive(Clone, Copy)]
pub struct Sombra {
    pub x: f32,
    pub y: f32,
    pub blur: f32,
    pub spread: f32,
    pub cor: u32, // 0xRRGGBBAA
}

const fn s(x: f32, y: f32, blur: f32, spread: f32, cor: u32) -> Sombra {
    Sombra { x, y, blur, spread, cor }
}

#[derive(Clone, Copy)]
pub struct Tema {
    pub id: &'static str,
    pub fundo: Fundo,
    pub bg1: u32,
    pub bg2: u32,
    pub texto: u32,
    pub botao: u32, // --btn (foco padrão, estrela)
    pub fonte: Option<&'static str>,
    pub fonte_peso: Option<u16>,
    pub maiusculas: bool,
    // título
    pub titulo_cor: u32,
    pub titulo_sombras: &'static [(f32, f32, u32)],
    pub titulo_fundo: Option<u32>, // 0xRRGGBBAA (pílula atrás do título)
    #[allow(dead_code)] // o CSS gira o título 2°; o gpui não gira texto
    pub titulo_inclinado: bool,
    // cartões
    pub cartao_cores: &'static [u32], // fundo (0xRRGGBBAA), alterna pela posição
    pub cartao_cores_escuras: &'static [u32], // "base" 3D (blocos/casinha); vazio = sem
    pub cartao_gradiente: Option<(u32, u32)>, // sobrepõe cartao_cores (0xRRGGBBAA)
    pub cartao_texto: u32,
    pub cartao_borda: f32,
    pub cartao_borda_cor: u32,
    pub cartao_raio: f32,
    pub cartao_sombras: &'static [Sombra],
    pub cartao_sombras_par: &'static [Sombra], // vazio = iguais
    pub enfeite: Enfeite,
    pub enfeite_cor: u32,
    #[allow(dead_code)] // pontinhos de gibi (heroi): ainda não desenhados
    pub pontilhado: bool,
    // foco
    pub foco_cor: u32,
    pub foco_largura: f32,
    pub foco_distancia: f32,
    pub foco_tracejado: bool,
    // botões pequenos / relógio
    pub peq_fundo: u32, // 0xRRGGBBAA
    pub peq_texto: u32,
    pub peq_borda: f32,
    pub peq_borda_cor: u32,
    pub peq_raio: f32,
    pub peq_sombras: &'static [Sombra],
    pub tamanho_emoji_grande: f32,
}

pub fn hsla(cor: u32) -> Hsla {
    rgb(cor).into()
}
pub fn hsla_a(cor: u32) -> Hsla {
    rgba(cor).into()
}

pub fn sombras(lista: &[Sombra]) -> Vec<BoxShadow> {
    lista
        .iter()
        .map(|s| BoxShadow {
            color: rgba(s.cor).into(),
            offset: point(px(s.x), px(s.y)),
            blur_radius: px(s.blur),
            spread_radius: px(s.spread),
            inset: false,
        })
        .collect()
}

const SOMBRA_PADRAO: &[Sombra] = &[s(0., 14., 40., 0., 0x7d235430)];
const SOMBRA_LILA: &[Sombra] = &[s(0., 14., 40., 0., 0x45216a2e)];
const SOMBRA_AZUL: &[Sombra] = &[s(0., 14., 40., 0., 0x1f46702e)];
const SOMBRA_VERDE: &[Sombra] = &[s(0., 14., 40., 0., 0x24563a26)];

const BASE: Tema = Tema {
    id: "rosa",
    fundo: Fundo::Cores,
    bg1: 0xffd6e8,
    bg2: 0xffeef6,
    texto: 0x5f2148,
    botao: 0xe85a9c,
    fonte: None,
    fonte_peso: None,
    maiusculas: false,
    titulo_cor: 0x5f2148,
    titulo_sombras: &[],
    titulo_fundo: None,
    titulo_inclinado: false,
    cartao_cores: &[0xffffffeb],
    cartao_cores_escuras: &[],
    cartao_gradiente: None,
    cartao_texto: 0x5f2148,
    cartao_borda: 0.,
    cartao_borda_cor: 0,
    cartao_raio: 32.,
    cartao_sombras: SOMBRA_PADRAO,
    cartao_sombras_par: &[],
    enfeite: Enfeite::Nenhum,
    enfeite_cor: 0,
    pontilhado: false,
    foco_cor: 0xe85a9c,
    foco_largura: 4.,
    foco_distancia: 4.,
    foco_tracejado: false,
    peq_fundo: 0xfff7fbff,
    peq_texto: 0x5f2148,
    peq_borda: 0.,
    peq_borda_cor: 0,
    peq_raio: 18.,
    peq_sombras: SOMBRA_PADRAO,
    tamanho_emoji_grande: 64.,
};

/// Tema de cores (sem imagem): só muda a paleta.
const fn cores(id: &'static str, bg1: u32, bg2: u32, texto: u32, botao: u32, peq: u32, sombra: u32) -> Tema {
    let sombras: &'static [Sombra] = match sombra {
        0x45216a30 => SOMBRA_LILA,
        0x1f467030 => SOMBRA_AZUL,
        0x24563a26 => SOMBRA_VERDE,
        _ => SOMBRA_PADRAO,
    };
    Tema {
        id, bg1, bg2, texto, botao, titulo_cor: texto, cartao_texto: texto, foco_cor: botao,
        peq_fundo: (peq << 8) | 0xff, peq_texto: texto, cartao_sombras: sombras, peq_sombras: sombras,
        ..BASE
    }
}

/// Tema de mundo (foto de fundo, cartões brancos translúcidos).
const fn mundo(id: &'static str, img: &'static str, bg1: u32, texto: u32, botao: u32, peq: u32) -> Tema {
    Tema {
        id, fundo: Fundo::Imagem(img), bg1, bg2: bg1, texto, botao, titulo_cor: texto,
        cartao_texto: texto, foco_cor: botao, peq_fundo: (peq << 8) | 0xff, peq_texto: texto,
        titulo_fundo: Some(0xffffffd9),
        ..BASE
    }
}

pub static TEMAS: &[Tema] = &[
    cores("rosa", 0xffd6e8, 0xffeef6, 0x5f2148, 0xe85a9c, 0xfff7fb, 0),
    cores("lila", 0xe3d6ff, 0xf4eeff, 0x45216a, 0x9b59b6, 0xfaf5ff, 0x45216a30),
    cores("blau", 0xd7ebff, 0xeef7ff, 0x1f4670, 0x3498db, 0xf0f8ff, 0x1f467030),
    cores("gruen", 0xd9f7df, 0xeffcf1, 0x24563a, 0x27ae60, 0xf0fff4, 0x24563a26),
    cores("regenbogen", 0xffd6e8, 0xd7ebff, 0x5f2148, 0xe85a9c, 0xfff7fb, 0),
    cores("custom", 0xffd6e8, 0xffeef6, 0x5f2148, 0xe85a9c, 0xfff7fb, 0),
    Tema { cartao_borda: 2., cartao_borda_cor: 0x81c784, cartao_raio: 28., ..mundo("wald", "forrest.jpg", 0xc8e6c9, 0x1b5e20, 0x43a047, 0xf1f8e9) },
    Tema { cartao_raio: 20., ..mundo("weltraum", "space.jpg", 0xd1c4e9, 0x311b92, 0x7e57c2, 0xf3e5f5) },
    Tema { cartao_raio: 28., ..mundo("ocean", "ocean.jpg", 0xb3e5fc, 0x01579b, 0x0288d1, 0xe0f7fa) },
    Tema { cartao_borda: 3., cartao_borda_cor: 0x689f38, cartao_raio: 24., ..mundo("dinosaurier", "dinosaur.jpg", 0xdcedc8, 0x33691e, 0x689f38, 0xf9fbe7) },
    Tema { cartao_borda: 3., cartao_borda_cor: 0xff9800, cartao_raio: 12., ..mundo("baustelle", "construction-site.jpg", 0xffecb3, 0xe65100, 0xff9800, 0xfff3e0) },
    Tema { cartao_raio: 40., ..mundo("prinzessin", "princess.jpg", 0xf8bbd0, 0x880e4f, 0xec407a, 0xfff0f5) },
    Tema { cartao_borda: 2., cartao_borda_cor: 0xe57373, cartao_raio: 28., ..mundo("bauernhof", "farm.jpg", 0xffcdd2, 0xb71c1c, 0xe53935, 0xfff5f5) },
    Tema { cartao_raio: 36., ..mundo("katzen", "cats.jpg", 0xffe0b2, 0xe65100, 0xfb8c00, 0xfff8e1) },
    Tema { cartao_raio: 36., ..mundo("hunde", "dogs.jpg", 0xd7ccc8, 0x4e342e, 0x8d6e63, 0xfafafa) },
    // ---------- Herói Aranha: quadrinhos ----------
    Tema {
        id: "heroi", fundo: Fundo::Imagem("heroi.svg"), bg1: 0x0b1a4a, bg2: 0x14205e,
        texto: 0x0b1f4b, botao: 0xc8102e, fonte: Some("Bangers"), maiusculas: true,
        titulo_cor: 0xffffff, titulo_sombras: &[(3., 3., 0xc8102e), (6., 6., 0x0a0a0a)],
        titulo_fundo: None, titulo_inclinado: true,
        cartao_cores: &[0xffffffff], cartao_gradiente: Some((0xffffffff, 0xeef3ffff)), cartao_texto: 0x0b1f4b,
        cartao_borda: 4., cartao_borda_cor: 0x0a0a0a, cartao_raio: 6.,
        cartao_sombras: &[s(8., 8., 0., 0., 0xc8102eff), s(8., 8., 0., 4., 0x0a0a0aff)],
        cartao_sombras_par: &[s(8., 8., 0., 0., 0x1d3c8fff), s(8., 8., 0., 4., 0x0a0a0aff)],
        pontilhado: true,
        foco_cor: 0xffd34d, foco_largura: 5., foco_distancia: 6.,
        peq_fundo: 0xffffffff, peq_texto: 0x0b1f4b, peq_borda: 3., peq_borda_cor: 0x0a0a0a, peq_raio: 18.,
        peq_sombras: &[s(4., 4., 0., 0., 0xc8102eff)],
        ..BASE
    },
    // ---------- Blocos de Montar ----------
    Tema {
        id: "blocos", fundo: Fundo::Imagem("blocos.svg"), bg1: 0x2e9e48, bg2: 0x2e9e48,
        texto: 0x222222, botao: 0xf9c80e, fonte: Some("Bungee"),
        titulo_cor: 0xf9c80e, titulo_sombras: &[(0., 6., 0x222222)], titulo_fundo: Some(0x0000002e),
        cartao_cores: &[0xd42a2fff, 0x1565c0ff, 0xf9c80eff, 0xff7a00ff],
        cartao_cores_escuras: &[0x8e1418, 0x0b3a75, 0xb58900, 0xb04f00],
        cartao_texto: 0xffffff, cartao_raio: 8.,
        cartao_sombras: &[s(0., 10., 0., 0., 0x00000040)],
        enfeite: Enfeite::Pinos,
        foco_cor: 0xffffff, foco_largura: 5., foco_distancia: 5.,
        peq_fundo: 0xf9c80eff, peq_texto: 0x222222, peq_raio: 8.,
        peq_sombras: &[s(0., 5., 0., 0., 0x00000040)],
        ..BASE
    },
    // ---------- Dojo Ninja ----------
    Tema {
        id: "ninja", fundo: Fundo::Imagem("ninja.svg"), bg1: 0x03140f, bg2: 0x0b3326,
        texto: 0xf4c542, botao: 0xe53935, fonte: Some("Shojumaru"),
        titulo_cor: 0xf4c542, titulo_sombras: &[(0., 5., 0x000000), (2., 2., 0x1a1200), (-2., -2., 0x1a1200)],
        cartao_cores: &[0x0e3d2beb], cartao_gradiente: Some((0x0e3d2beb, 0x03140feb)), cartao_texto: 0xf4c542,
        cartao_borda: 2., cartao_borda_cor: 0xb8860b, cartao_raio: 4.,
        cartao_sombras: &[s(0., 14., 34., 0., 0x0000008c)],
        foco_cor: 0xe53935, foco_largura: 3., foco_distancia: 6.,
        peq_fundo: 0x061812e6, peq_texto: 0xf4c542, peq_borda: 2., peq_borda_cor: 0xb8860b,
        peq_sombras: &[s(0., 0., 0., 2., 0xb8860bff)],
        ..BASE
    },
    // ---------- Reino do Gelo ----------
    Tema {
        id: "gelo", fundo: Fundo::Imagem("gelo.svg"), bg1: 0x1b2a6b, bg2: 0x9fb8ff,
        texto: 0x1f3a8a, botao: 0x3d7bff, fonte: Some("Fredoka"), fonte_peso: Some(600),
        titulo_cor: 0xffffff, titulo_sombras: &[(0., 4., 0x3d5bd1)],
        cartao_cores: &[0xfffffff2], cartao_gradiente: Some((0xfffffff2, 0xbed6ffe0)), cartao_texto: 0x1f3a8a,
        cartao_borda: 3., cartao_borda_cor: 0xffffff, cartao_raio: 32.,
        cartao_sombras: &[s(0., 0., 0., 4., 0x9fd8ff8c), s(0., 14., 30., 0., 0x1f3a8a59)],
        enfeite: Enfeite::Floco, enfeite_cor: 0x7fb8ff,
        foco_cor: 0xffffff, foco_largura: 5., foco_distancia: 6.,
        peq_fundo: 0xffffffe6, peq_texto: 0x1f3a8a, peq_borda: 3., peq_borda_cor: 0xffffff,
        peq_sombras: &[s(0., 0., 14., 0., 0x9fd8ffcc)],
        tamanho_emoji_grande: 74.,
        ..BASE
    },
    // ---------- Casinha Mágica ----------
    Tema {
        id: "casinha", fundo: Fundo::Imagem("casinha.svg"), bg1: 0xffd1ec, bg2: 0xe9d5ff,
        texto: 0x7a1f5c, botao: 0xff6fae, fonte: Some("Fredoka"), fonte_peso: Some(600),
        titulo_cor: 0xff4f9a, titulo_sombras: &[(0., 5., 0xffffff)], titulo_fundo: Some(0xffffffbf),
        cartao_cores: &[0xffc6e2ff, 0xdccdffff, 0xbff3e3ff, 0xfff0b8ff],
        cartao_cores_escuras: &[0xff6fae, 0x9b7bff, 0x3fc79f, 0xf2b72e],
        cartao_texto: 0x5a1748, cartao_borda: 6., cartao_borda_cor: 0xffffff, cartao_raio: 26.,
        cartao_sombras: &[s(0., 14., 26., 0., 0x7a1f5c38)],
        enfeite: Enfeite::Telhado,
        foco_cor: 0xff4f9a, foco_largura: 5., foco_distancia: 6., foco_tracejado: true,
        peq_fundo: 0xffffffff, peq_texto: 0x7a1f5c, peq_borda: 4., peq_borda_cor: 0xffb3d9, peq_raio: 999.,
        peq_sombras: &[s(0., 8., 0., 0., 0x7a1f5c2e)],
        tamanho_emoji_grande: 74.,
        ..BASE
    },
    // ---------- Castelo Encantado ----------
    Tema {
        id: "castelo", fundo: Fundo::Imagem("castelo.svg"), bg1: 0xffb3d1, bg2: 0xfff0d6,
        texto: 0x6b2a7a, botao: 0xc77dff, fonte: Some("Fredoka"), fonte_peso: Some(600),
        titulo_cor: 0x8e44d6, titulo_sombras: &[(0., 3., 0xffffff)],
        cartao_cores: &[0xfffdf8ff], cartao_gradiente: Some((0xfffdf8ff, 0xffeef7ff)), cartao_texto: 0x6b2a7a,
        cartao_borda: 4., cartao_borda_cor: 0xf4c542, cartao_raio: 30.,
        cartao_sombras: &[s(0., 0., 0., 6., 0xffffffff), s(0., 0., 0., 9., 0xf9b6d6ff), s(0., 14., 30., 0., 0x8e44d647)],
        enfeite: Enfeite::Coroa,
        foco_cor: 0xc77dff, foco_largura: 5., foco_distancia: 10.,
        peq_fundo: 0xfffaf3ff, peq_texto: 0x6b2a7a, peq_borda: 3., peq_borda_cor: 0xf4c542,
        peq_sombras: &[s(0., 0., 0., 3., 0xf4c542ff), s(0., 12., 28., 0., 0x8e44d640)],
        tamanho_emoji_grande: 74.,
        ..BASE
    },
];

pub fn tema(id: &str) -> Tema {
    TEMAS.iter().find(|t| t.id == id).copied().unwrap_or(TEMAS[0])
}

/// Fontes que o menu registra (ficam em themes/fonts).
pub const FONTES: &[&str] = &[
    "Bangers-Regular.ttf",
    "Bungee-Regular.ttf",
    "Shojumaru-Regular.ttf",
    "Fredoka-SemiBold.ttf", // instância estática (o gpui não aplica o eixo de peso)
];

/// Fonte do texto "normal" quando o tema não define uma.
pub const FONTE_PADRAO: &str = "Noto Sans";

/// Emojis coloridos (sem isto o gpui pode cair numa fonte de símbolos monocromática).
pub const FONTE_EMOJI: &str = "Noto Color Emoji";
