//! Regras da tela da criança portadas de src/frontend (escolha.js, usage-limits.js,
//! launcher-ui.js). Funções puras sobre o JSON da API, para dar para testar.

use serde_json::Value;

#[derive(Clone, Debug, PartialEq)]
pub struct Tile {
    pub id: String,
    pub label: String,
    pub emoji: String,
    pub gamepad: bool,
    pub categoria: String,
    pub biblioteca: bool, // special:filme-musik → página de mídia
}

pub fn texto(v: &Value, chave: &str) -> String {
    v.get(chave).and_then(Value::as_str).unwrap_or("").to_string()
}

pub fn numero(v: &Value, chave: &str) -> Option<f64> {
    v.get(chave).and_then(Value::as_f64)
}

pub fn verdade(v: &Value, chave: &str) -> bool {
    v.get(chave).and_then(Value::as_bool).unwrap_or(false)
}

pub fn tiles_visiveis(cfg: &Value) -> Vec<Tile> {
    let Some(lista) = cfg.get("tiles").and_then(Value::as_array) else { return vec![] };
    lista
        .iter()
        .filter(|t| t.get("visible").and_then(Value::as_bool).unwrap_or(true))
        .filter_map(|t| {
            let id = t.get("id")?.as_str()?.to_string();
            let cmd = t.get("cmd").and_then(Value::as_array);
            let biblioteca = cmd.is_some_and(|c| c.len() == 1 && c[0].as_str() == Some("special:filme-musik"));
            Some(Tile {
                id,
                label: texto(t, "label"),
                emoji: texto(t, "emoji"),
                gamepad: t.get("gamepad").and_then(Value::as_bool) == Some(true),
                categoria: texto(t, "category"),
                biblioteca,
            })
        })
        .collect()
}

// ---------------- Escolha (Aprender / Passatempo / Jogar) ----------------

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Opcao {
    pub id: &'static str,
    pub titulo: &'static str,
    pub emoji: &'static str,
    pub lista: &'static str,
}

pub const OPCOES: [Opcao; 3] = [
    Opcao { id: "educativo", titulo: "Aprender", emoji: "📚", lista: "Aprender" },
    Opcao { id: "passatempo", titulo: "Passatempo", emoji: "🎨", lista: "Passatempo" },
    Opcao { id: "jogos", titulo: "Jogar", emoji: "🎮", lista: "Jogar" },
];

pub fn tem_passatempo(uso: &Value) -> bool {
    if uso.is_null() {
        return false;
    }
    let nas_categorias = uso
        .get("categories")
        .and_then(Value::as_array)
        .is_some_and(|c| c.iter().any(|c| c.get("id").and_then(Value::as_str) == Some("passatempo")));
    nas_categorias
        || uso
            .get("tileCategories")
            .and_then(Value::as_object)
            .is_some_and(|m| m.values().any(|v| v.as_str() == Some("passatempo")))
}

pub fn opcoes(uso: &Value) -> Vec<Opcao> {
    let p = tem_passatempo(uso);
    OPCOES.iter().copied().filter(|o| o.id != "passatempo" || p).collect()
}

pub fn opcao(uso: &Value, id: &str) -> Option<Opcao> {
    opcoes(uso).into_iter().find(|o| o.id == id)
}

pub fn categoria_do_tile(uso: &Value, tile: &Tile) -> String {
    if let Some(m) = uso.get("tileCategories").and_then(Value::as_object) {
        if let Some(v) = m.get(&tile.id) {
            return v.as_str().unwrap_or("").to_string();
        }
    }
    tile.categoria.clone()
}

/// "Aprender" = educativo; "Passatempo" = passatempo; "Jogar" = todo o resto.
pub fn tile_na_lista(modo: &str, uso: &Value, tile: &Tile) -> bool {
    let c = categoria_do_tile(uso, tile);
    if modo == "educativo" || modo == "passatempo" {
        return c == modo;
    }
    let proprias: &[&str] = if tem_passatempo(uso) { &["educativo", "passatempo"] } else { &["educativo"] };
    !proprias.contains(&c.as_str())
}

pub fn categoria<'a>(uso: &'a Value, id: &str) -> Option<&'a Value> {
    uso.get("categories")?
        .as_array()?
        .iter()
        .find(|c| c.get("id").and_then(Value::as_str) == Some(id))
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Tempo {
    pub com_tempo: bool,
    pub esgotada: bool,
    pub restante: f64,
    pub limite: f64,
    pub escala: Option<f64>,
}

pub fn regra_aprendizado(uso: &Value) -> Option<&Value> {
    if !verdade(uso, "enabled") {
        return None;
    }
    let r = uso.get("learningRule")?;
    verdade(r, "enabled").then_some(r)
}

pub fn regra_reduzida<'a>(uso: &'a Value, cat_id: &str) -> Option<&'a Value> {
    let r = regra_aprendizado(uso)?;
    let cat = categoria(uso, cat_id)?;
    (verdade(r, "active") && verdade(cat, "learningReduced")).then_some(r)
}

pub fn tempo(uso: &Value, id: &str) -> Tempo {
    let vazio = Tempo::default();
    if !verdade(uso, "enabled") {
        return vazio;
    }
    let total_limite = numero(uso, "totalMinutes").map(|m| m * 60.);
    let Some(cat) = categoria(uso, id) else {
        let Some(limite) = total_limite else { return vazio };
        return Tempo {
            com_tempo: true,
            esgotada: verdade(uso, "totalExhausted"),
            restante: numero(uso, "totalRemainingSeconds").unwrap_or(0.),
            limite,
            escala: None,
        };
    };
    let esgotada = verdade(cat, "exhausted") || verdade(uso, "totalExhausted");
    let Some(disponivel) = numero(cat, "availableSeconds") else {
        return Tempo { esgotada, ..vazio };
    };
    let limite = numero(cat, "minutes").map(|m| m * 60.).or(total_limite);
    let escala = regra_reduzida(uso, id).and_then(|r| numero(r, "baseMinutes")).map(|m| m * 60.);
    let limite = match limite {
        Some(l) if l > 0. => l,
        _ if disponivel > 0. => disponivel,
        _ => 1.,
    };
    Tempo { com_tempo: true, esgotada, restante: disponivel, limite, escala }
}

pub fn minutos(segundos: f64) -> i64 {
    (segundos.max(0.) / 60.).ceil() as i64
}

pub fn minutos_usados(segundos: f64) -> i64 {
    (segundos.max(0.) / 60.).floor() as i64
}

pub fn texto_tempo(t: &Tempo) -> String {
    if t.esgotada {
        return "Amanhã tem mais!".into();
    }
    if !t.com_tempo {
        return String::new();
    }
    let m = minutos(t.restante);
    if m <= 1 { "falta 1 min".into() } else { format!("faltam {m} min") }
}

pub fn texto_regra(uso: &Value, id: &str) -> String {
    if regra_aprendizado(uso).is_none() {
        return String::new();
    }
    if let Some(r) = regra_reduzida(uso, id) {
        return texto_regra_crianca(r);
    }
    if id == "educativo" {
        return texto_meta_aprender(uso);
    }
    String::new()
}

pub fn texto_regra_crianca(r: &Value) -> String {
    format!("Hoje {} min — ontem faltou aprender 📚", numero(r, "minutes").unwrap_or(0.) as i64)
}

pub fn texto_meta_aprender(uso: &Value) -> String {
    let Some(t) = regra_aprendizado(uso).and_then(|r| r.get("today")) else { return String::new() };
    let meta = numero(t, "goalSeconds").unwrap_or(0.);
    if meta <= 0. {
        return String::new();
    }
    if verdade(t, "met") {
        return "Meta de hoje cumprida! ⭐".into();
    }
    format!(
        "Aprenda mais {} min e amanhã o tempo de jogar fica completo ⭐",
        minutos(meta - numero(t, "learnedSeconds").unwrap_or(0.))
    )
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Faixa {
    Ok,
    Atencao,
    Pouco,
    Acabou,
}

impl Faixa {
    pub fn cor(self) -> u32 {
        match self {
            Faixa::Ok => 0x43a047,
            Faixa::Atencao => 0xf9a825,
            Faixa::Pouco | Faixa::Acabou => 0xe53935,
        }
    }
}

pub fn faixa(disponivel: Option<f64>, limite: f64) -> Faixa {
    let Some(d) = disponivel else { return Faixa::Ok };
    if d <= 0. {
        return Faixa::Acabou;
    }
    if d <= 60. {
        return Faixa::Pouco;
    }
    if limite > 0. {
        let f = d / limite;
        if f <= 0.2 {
            return Faixa::Pouco;
        }
        if f <= 0.5 {
            return Faixa::Atencao;
        }
    }
    Faixa::Ok
}

/// Fração da barrinha da escolha (cheia = muito tempo).
pub fn fracao_barra(t: &Tempo) -> f32 {
    if t.esgotada {
        return 0.;
    }
    let base = t.escala.unwrap_or(t.limite).max(1.);
    (t.restante / base).clamp(0., 1.) as f32
}

// ---------------- Medidores do rodapé ----------------

#[derive(Clone, Debug, PartialEq)]
pub struct Medidor {
    pub emoji: String,
    pub nome: String,
    pub usado: f64,
    pub limite: f64,
    pub disponivel: Option<f64>,
    pub esgotado: bool,
    pub nota: String,
}

pub fn medidores(uso: &Value) -> Vec<Medidor> {
    if !verdade(uso, "enabled") {
        return vec![];
    }
    struct Grupo {
        pool: String,
        nomes: Vec<String>,
        emojis: String,
        minutos: Option<f64>,
        usado: f64,
        disponivel: Option<f64>,
        esgotado: bool,
        reduzido: bool,
    }
    let mut grupos: Vec<Grupo> = vec![];
    for c in uso.get("categories").and_then(Value::as_array).into_iter().flatten() {
        let id = texto(c, "id");
        let pool = c.get("pool").and_then(Value::as_str).map(str::to_string).unwrap_or_else(|| id.clone());
        let reduzido = regra_reduzida(uso, &id).is_some();
        let pos = grupos.iter().position(|g| g.pool == pool);
        let g = match pos {
            Some(i) => &mut grupos[i],
            None => {
                grupos.push(Grupo {
                    pool: pool.clone(),
                    nomes: vec![],
                    emojis: String::new(),
                    minutos: numero(c, "minutes"),
                    usado: 0.,
                    disponivel: numero(c, "availableSeconds"),
                    esgotado: verdade(c, "exhausted"),
                    reduzido: false,
                });
                grupos.last_mut().unwrap()
            }
        };
        g.nomes.push(texto(c, "label"));
        g.emojis.push_str(&texto(c, "emoji"));
        g.usado = match numero(c, "poolUsedSeconds") {
            Some(p) => p,
            None => g.usado + numero(c, "usedSeconds").unwrap_or(0.),
        };
        g.reduzido |= reduzido;
    }
    let mut itens = vec![];
    let mut soma = 0f64;
    for g in &grupos {
        soma += g.minutos.unwrap_or(f64::INFINITY);
        let Some(min) = g.minutos else { continue };
        itens.push(Medidor {
            emoji: g.emojis.clone(),
            nome: g.nomes.join(" + "),
            usado: g.usado,
            limite: min * 60.,
            disponivel: g.disponivel,
            esgotado: g.esgotado,
            nota: if g.reduzido { "ontem faltou aprender 📚".into() } else { String::new() },
        });
    }
    if let Some(total) = numero(uso, "totalMinutes") {
        if total < soma || itens.is_empty() {
            itens.push(Medidor {
                emoji: "⏳".into(),
                nome: "Hoje".into(),
                usado: numero(uso, "totalUsedSeconds").unwrap_or(0.),
                limite: total * 60.,
                disponivel: numero(uso, "totalRemainingSeconds"),
                esgotado: verdade(uso, "totalExhausted"),
                nota: String::new(),
            });
        }
    }
    itens
}

// ---------------- Mensagens de limite ----------------

fn alternativas(uso: &Value, excluir: &str) -> String {
    if verdade(uso, "totalExhausted") {
        return String::new();
    }
    let proprio = categoria(uso, excluir);
    let pool_proprio = proprio
        .and_then(|c| c.get("pool").and_then(Value::as_str))
        .unwrap_or(excluir)
        .to_string();
    let opcoes: Vec<String> = uso
        .get("categories")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter(|c| {
            let id = texto(c, "id");
            let pool = c.get("pool").and_then(Value::as_str).map(str::to_string).unwrap_or_else(|| id.clone());
            let disp = numero(c, "availableSeconds");
            id != excluir && pool != pool_proprio && !verdade(c, "exhausted") && disp.is_none_or(|d| d > 0.)
        })
        .map(|c| {
            let mut s = format!("{} {}", texto(c, "label"), texto(c, "emoji"));
            if let Some(d) = numero(c, "availableSeconds") {
                s.push_str(&format!(" ({} min)", minutos(d)));
            }
            s
        })
        .collect();
    if opcoes.is_empty() {
        return String::new();
    }
    format!("Você ainda pode brincar de {}.", opcoes.join(" ou "))
}

/// (título, texto) da mensagem amigável de limite (usageLimitTexts).
pub fn textos_limite(uso: &Value, motivo: &str, cat_id: &str) -> (String, String) {
    let cat = categoria(uso, cat_id);
    if motivo == "daily_limit" || verdade(uso, "totalExhausted") || cat.is_none() {
        return (
            "O tempo de hoje acabou!".into(),
            "Que tal brincar longe da tela? Amanhã tem mais! 😊".into(),
        );
    }
    let cat = cat.unwrap();
    let outra = alternativas(uso, cat_id);
    let dica = match regra_aprendizado(uso) {
        Some(r)
            if cat.get("pool") == r.get("category")
                && r.get("today").is_some_and(|t| !verdade(t, "met") && numero(t, "goalSeconds").unwrap_or(0.) > 0.) =>
        {
            " Aprendendo um pouquinho hoje, amanhã tem mais tempo de jogar! 📚"
        }
        _ => "",
    };
    (
        format!("O tempo de {} acabou por hoje!", texto(cat, "label")),
        format!("{}{}", if outra.is_empty() { "Amanhã tem mais! 😊".to_string() } else { outra }, dica),
    )
}

#[cfg(test)]
mod testes {
    use super::*;
    use serde_json::json;

    fn uso() -> Value {
        json!({
            "enabled": true, "totalMinutes": 60, "totalUsedSeconds": 59, "totalRemainingSeconds": 3540,
            "totalExhausted": false,
            "categories": [
                {"id":"jogos","label":"Jogos","emoji":"🎮","minutes":15,"pool":"jogos","baseMinutes":30,
                 "learningReduced":true,"usedSeconds":59,"poolUsedSeconds":59,"availableSeconds":840,"exhausted":false},
                {"id":"educativo","label":"Aprender","emoji":"📚","minutes":30,"pool":"educativo",
                 "usedSeconds":0,"poolUsedSeconds":0,"availableSeconds":1800,"exhausted":false},
                {"id":"passatempo","label":"Passatempo","emoji":"🎨","minutes":15,"pool":"jogos","baseMinutes":30,
                 "learningReduced":true,"usedSeconds":0,"poolUsedSeconds":59,"availableSeconds":840,"exhausted":false}
            ],
            "tileCategories": {"a":"jogos","b":"passatempo","c":"educativo"},
            "learningRule": {"enabled":true,"active":true,"category":"jogos","baseMinutes":30,"minutes":15,
                             "today":{"goalSeconds":900,"learnedSeconds":0,"met":false}}
        })
    }

    fn tile(id: &str) -> Tile {
        Tile { id: id.into(), label: id.into(), emoji: "x".into(), gamepad: false, categoria: String::new(), biblioteca: false }
    }

    #[test]
    fn opcoes_com_passatempo() {
        assert_eq!(opcoes(&uso()).len(), 3);
        assert_eq!(opcoes(&json!({"enabled":false})).len(), 2);
    }

    #[test]
    fn filtra_tiles_por_modo() {
        let u = uso();
        assert!(tile_na_lista("jogos", &u, &tile("a")));
        assert!(!tile_na_lista("jogos", &u, &tile("b")));
        assert!(tile_na_lista("passatempo", &u, &tile("b")));
        assert!(tile_na_lista("educativo", &u, &tile("c")));
        // sem categoria conhecida → Jogar
        assert!(tile_na_lista("jogos", &u, &tile("z")));
    }

    #[test]
    fn tempo_e_textos() {
        let u = uso();
        let t = tempo(&u, "jogos");
        assert!(t.com_tempo && !t.esgotada);
        assert_eq!(texto_tempo(&t), "faltam 14 min");
        assert_eq!(t.escala, Some(1800.));
        assert!((fracao_barra(&t) - 840. / 1800.).abs() < 1e-6);
        assert_eq!(texto_regra(&u, "jogos"), "Hoje 15 min — ontem faltou aprender 📚");
        assert!(texto_regra(&u, "educativo").starts_with("Aprenda mais 15 min"));
        assert_eq!(faixa(Some(840.), 900.), Faixa::Ok);
        assert_eq!(faixa(Some(300.), 900.), Faixa::Atencao);
        assert_eq!(faixa(Some(50.), 900.), Faixa::Pouco);
    }

    #[test]
    fn medidores_agrupam_pool() {
        let m = medidores(&uso());
        assert_eq!(m.len(), 2); // Jogos+Passatempo, Aprender (60 ≥ 15+30 → sem "Hoje")
        assert_eq!(m[0].nome, "Jogos + Passatempo");
        assert_eq!(m[0].emoji, "🎮🎨");
        assert_eq!(m[0].usado, 59.);
        assert_eq!(m[0].nota, "ontem faltou aprender 📚");
    }

    #[test]
    fn mensagem_de_limite() {
        let (t, c) = textos_limite(&uso(), "category_limit", "jogos");
        assert_eq!(t, "O tempo de Jogos acabou por hoje!");
        assert!(c.starts_with("Você ainda pode brincar de Aprender 📚 (30 min)."));
        assert!(c.ends_with("📚"));
        let (t, _) = textos_limite(&uso(), "daily_limit", "jogos");
        assert_eq!(t, "O tempo de hoje acabou!");
    }
}
