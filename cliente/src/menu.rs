//! A tela da criança: escolha (Aprender / Passatempo / Jogar), grade de ícones,
//! medidores de tempo, relógio, timer, avisos e PIN. Porta de src/frontend para gpui.
//! A área dos pais (e sites embutidos / biblioteca de mídia) abre no navegador.

use std::collections::HashMap;
use std::path::PathBuf;
use std::process::Child;
use std::time::{Duration, Instant};

use gpui::{
    AnimationExt as _, AnyElement, App, BoxShadow, ClickEvent, Context, FocusHandle, FontWeight, KeyDownEvent,
    ObjectFit, SharedString, StyledImage as _, Window, div, img, linear_color_stop, linear_gradient,
    point, prelude::*, px,
};
use serde_json::{Value, json};

use crate::api::{Api, codificar};
use crate::dados::{self, Faixa, Tile};
use crate::icones::icone;
use crate::sons::{self, Som};
use crate::tema::{self, Enfeite, Fundo, Tema, hsla, hsla_a, sombras};

// ---------------------------------------------------------------- opções

#[derive(Clone)]
pub struct Opcoes {
    pub porta: u16,
    pub app_root: PathBuf,
    pub web_cmd: String,
    pub web_familia: String, // "firefox" | "chromium"
    pub web_perfil: PathBuf,
    pub demo: bool,
}

// ---------------------------------------------------------------- estado

#[derive(Clone, PartialEq)]
enum AcaoPin {
    Sair,
    Desligar,
    Perfil(String),
}

#[derive(Clone, PartialEq)]
enum Janela {
    /// Mensagem amigável (limite de uso). Some sozinha em 15 s.
    Mensagem { titulo: String, corpo: String, geracao: u64 },
    /// Fora do horário (perfil) ou app bloqueado no horário.
    Bloqueio { perfil: bool, foco: usize },
    /// "Faltam 5 minutos!" (6 s).
    AvisoTimer { texto: String, geracao: u64 },
    /// Timer acabou: PIN + mais tempo.
    TimerEsgotado { pin: String, erro: String, foco: usize },
    /// PIN dos pais para sair / desligar / trocar de perfil.
    Pin { pin: String, erro: String, acao: AcaoPin },
    /// Escolher o perfil (criança).
    Perfis { foco: usize },
}

struct Inicio {
    emoji: String,
    texto: String,
    sucesso: bool,
    geracao: u64,
}

pub struct Menu {
    o: Opcoes,
    api: Api,
    focus: FocusHandle,
    // dados da API
    cfg: Value,
    uso: Value,
    timer: Value,
    disp: Value,
    features: Value,
    erro_inicio: bool,
    atualizacao: bool,
    // navegação
    modo: Option<String>,
    modo_perfil: String,
    pagina: usize,
    foco: usize,
    foco_visivel: bool,
    // janelas por cima
    janela: Option<Janela>,
    inicio: Option<Inicio>,
    geracao: u64,
    aviso_timer_mostrado: bool,
    ultimo_expiry: f64,
    ultimos: HashMap<String, String>,
    // navegador (pais, sites embutidos, mídia)
    web: Option<(Child, u64)>,
    // diversos
    ativa: bool,
    sujo: bool, // mudou algo com a janela inativa (redesenha ao voltar)
    bateria: Option<(u32, bool)>,
    fala: u64,
    celebracao: Option<u64>,
    pub iniciado: Instant,
}

const ARQ_ESTADO: &str = "menu-estado.json";

impl Menu {
    pub fn new(o: Opcoes, focus: FocusHandle) -> Self {
        let api = if o.demo { Api::demo() } else { Api::new(o.porta) };
        let ultimos = std::fs::read(estado_dir().join(ARQ_ESTADO))
            .ok()
            .and_then(|b| serde_json::from_slice::<HashMap<String, String>>(&b).ok())
            .unwrap_or_default();
        Self {
            o,
            api,
            focus,
            cfg: Value::Null,
            uso: Value::Null,
            timer: Value::Null,
            disp: json!({"profileAllowed": true, "blockedTileIds": []}),
            features: Value::Null,
            erro_inicio: false,
            atualizacao: false,
            modo: None,
            modo_perfil: String::new(),
            pagina: 0,
            foco: 0,
            foco_visivel: true,
            janela: None,
            inicio: None,
            geracao: 0,
            aviso_timer_mostrado: false,
            ultimo_expiry: 0.,
            ultimos,
            web: None,
            ativa: true,
            sujo: false,
            bateria: ler_bateria(),
            fala: 0,
            celebracao: None,
            iniciado: Instant::now(),
        }
    }

    // ------------------------------------------------------------ tarefas

    /// Roda `f` numa thread de fundo (HTTP) e aplica o resultado na tela.
    fn tarefa<R: Send + 'static>(
        &self,
        cx: &mut Context<Self>,
        f: impl FnOnce(Api) -> R + Send + 'static,
        depois: impl FnOnce(&mut Self, R, &mut Context<Self>) + 'static,
    ) {
        let api = self.api.clone();
        cx.spawn(async move |this, cx| {
            let r = cx.background_executor().spawn(async move { f(api) }).await;
            let _ = this.update(cx, |m, cx| depois(m, r, cx));
        })
        .detach();
    }

    /// Começa os ciclos de atualização (uso 5 s, timer/horários 10 s, config 60 s).
    pub fn iniciar(&mut self, cx: &mut Context<Self>) {
        self.carregar_config(cx);
        self.atualizar_uso(cx);
        self.atualizar_timer(cx);
        self.atualizar_disp(cx);
        self.tarefa(cx, |api| api.get_json("/api/features"), |m, r, cx| {
            if let Some(v) = r {
                m.features = v;
                cx.notify();
            }
        });
        self.tarefa(
            cx,
            |api| api.get_json("/api/update/status"),
            |m, r, cx| {
                m.atualizacao = r.is_some_and(|v| dados::verdade(&v, "updateAvailable"));
                cx.notify();
            },
        );
        ciclo(cx, Duration::from_secs(5), |m, cx| m.atualizar_uso(cx));
        // se o uso não chegar, a escolha aparece mesmo assim depois de 4 s
        cx.spawn(async move |this, cx| {
            cx.background_executor().timer(Duration::from_millis(4100)).await;
            let _ = this.update(cx, |_, cx| cx.notify());
        })
        .detach();
        ciclo(cx, Duration::from_secs(10), |m, cx| {
            m.atualizar_timer(cx);
            m.atualizar_disp(cx);
        });
        ciclo(cx, Duration::from_secs(60), |m, cx| {
            if m.web.is_none() {
                m.carregar_config(cx);
            }
            let b = ler_bateria();
            if b != m.bateria {
                m.bateria = b;
                m.redesenhar(cx);
            }
        });
        // relógio: redesenha quando o minuto vira
        let mut minuto = agora_local().1;
        ciclo(cx, Duration::from_secs(5), move |menu, cx| {
            let m = agora_local().1;
            if m != minuto {
                minuto = m;
                menu.redesenhar(cx);
            }
        });
    }

    fn carregar_config(&mut self, cx: &mut Context<Self>) {
        self.tarefa(cx, |api| api.get_json("/api/config"), |m, r, cx| match r {
            Some(v) if v.get("tiles").is_some_and(Value::is_array) => {
                let primeira = m.cfg.is_null();
                if v != m.cfg {
                    m.cfg = v;
                    m.sincronizar_perfil();
                    m.corrigir_pagina();
                    m.redesenhar(cx);
                }
                m.erro_inicio = false;
                if primeira {
                    log::info!("menu: configuração carregada em {:?}", m.iniciado.elapsed());
                }
                if !dados::verdade(&m.cfg, "setupCompleted") && m.cfg.get("setupCompleted").is_some() {
                    // primeira vez: crianças e PIN dos pais (configurar.html, no navegador).
                    // Enquanto não terminar, reabre (abrir_web ignora se já está aberto).
                    m.abrir_web("/configurar.html", cx);
                }
            }
            _ => {
                if m.cfg.is_null() {
                    m.erro_inicio = true;
                    m.redesenhar(cx);
                    // o servidor pode estar subindo: tenta de novo
                    cx.spawn(async move |this, cx| {
                        cx.background_executor().timer(Duration::from_secs(2)).await;
                        let _ = this.update(cx, |m, cx| m.carregar_config(cx));
                    })
                    .detach();
                }
            }
        });
    }

    fn atualizar_uso(&mut self, cx: &mut Context<Self>) {
        self.tarefa(cx, |api| api.get_json("/api/usage/status"), |m, r, cx| {
            let Some(v) = r else { return };
            if v == m.uso {
                return;
            }
            let bloqueados_antes = m.uso.get("blockedTileIds").cloned();
            m.uso = v;
            if m.uso.get("blockedTileIds").cloned() != bloqueados_antes {
                m.atualizar_disp(cx);
            }
            // a categoria da lista acabou: volta para a escolha
            if let Some(modo) = m.modo.clone() {
                if dados::tempo(&m.uso, &modo).esgotada || dados::opcao(&m.uso, &modo).is_none() {
                    m.modo = None;
                    m.pagina = 0;
                    m.foco = 0;
                }
            }
            m.corrigir_pagina();
            m.talvez_mostrar_expiracao();
            m.redesenhar(cx);
        });
    }

    fn atualizar_timer(&mut self, cx: &mut Context<Self>) {
        self.tarefa(cx, |api| api.get_json("/api/timer/status"), |m, r, cx| {
            let Some(v) = r else { return };
            let ativo = dados::verdade(&v, "active");
            let esgotado = dados::verdade(&v, "expired");
            let aviso = dados::verdade(&v, "warning");
            if ativo && esgotado {
                if !matches!(m.janela, Some(Janela::TimerEsgotado { .. })) {
                    m.janela = Some(Janela::TimerEsgotado { pin: String::new(), erro: String::new(), foco: 0 });
                }
            } else if ativo && aviso && !m.aviso_timer_mostrado {
                m.aviso_timer_mostrado = true;
                let restante = dados::numero(&v, "remainingSeconds").unwrap_or(0.);
                m.mostrar_aviso_timer(dados::minutos_usados(restante), cx);
            } else if !ativo {
                m.aviso_timer_mostrado = false;
                if matches!(m.janela, Some(Janela::TimerEsgotado { .. } | Janela::AvisoTimer { .. })) {
                    m.janela = None;
                }
            }
            if v != m.timer {
                m.timer = v;
                m.redesenhar(cx);
            }
        });
    }

    fn atualizar_disp(&mut self, cx: &mut Context<Self>) {
        self.tarefa(cx, |api| api.get_json("/api/availability/status"), |m, r, cx| {
            let Some(v) = r else { return };
            if !v.get("profileAllowed").is_some_and(Value::is_boolean) {
                return;
            }
            let permitido = dados::verdade(&v, "profileAllowed");
            if !permitido && m.web.is_none() {
                if !matches!(m.janela, Some(Janela::Bloqueio { perfil: true, .. })) {
                    m.janela = Some(Janela::Bloqueio { perfil: true, foco: 0 });
                }
            } else if permitido && matches!(m.janela, Some(Janela::Bloqueio { perfil: true, .. })) {
                m.janela = None;
            }
            if v != m.disp {
                m.disp = v;
                m.redesenhar(cx);
            }
        });
    }

    fn talvez_mostrar_expiracao(&mut self) {
        let Some(exp) = self.uso.get("lastExpiry") else { return };
        let Some(em) = dados::numero(exp, "at") else { return };
        if em <= self.ultimo_expiry {
            return;
        }
        let agora = dados::numero(&self.uso, "now").unwrap_or(em);
        if agora - em > 180. {
            return;
        }
        self.ultimo_expiry = em;
        let motivo = if dados::texto(exp, "limitedBy") == "total" { "daily_limit" } else { "category_limit" };
        let (t, c) = dados::textos_limite(&self.uso, motivo, &dados::texto(exp, "category"));
        self.mostrar_mensagem(t, c);
    }

    // ------------------------------------------------------------ dados derivados

    fn tema(&self) -> Tema {
        let mut t = tema::tema(&dados::texto(&self.cfg, "theme"));
        if t.id == "custom" {
            if let Some(c) = self.cfg.get("customColors") {
                let cor = |k: &str| c.get(k).and_then(Value::as_str).and_then(cor_hex);
                if let Some(v) = cor("bg1") { t.bg1 = v; }
                if let Some(v) = cor("bg2") { t.bg2 = v; }
                if let Some(v) = cor("text") { t.texto = v; t.titulo_cor = v; t.cartao_texto = v; t.peq_texto = v; }
                if let Some(v) = cor("btn") { t.botao = v; t.foco_cor = v; }
                if let Some(v) = cor("card") { t.cartao_cores = cor_de_cartao((v << 8) | 0xff); }
                if let Some(v) = cor("smallbtnBg") { t.peq_fundo = (v << 8) | 0xff; }
            }
        }
        t
    }

    fn perfil_id(&self) -> String {
        let id = dados::texto(&self.cfg, "activeProfileId");
        if id.is_empty() { "default".into() } else { id }
    }

    fn sincronizar_perfil(&mut self) {
        let p = self.perfil_id();
        if p != self.modo_perfil {
            self.modo_perfil = p;
            self.modo = None;
            self.pagina = 0;
            self.foco = 0;
        }
    }

    fn escolha_habilitada(&self) -> bool {
        self.cfg.get("choiceScreenEnabled").and_then(Value::as_bool) != Some(false)
    }

    fn na_escolha(&self) -> bool {
        self.escolha_habilitada() && self.modo.is_none()
    }

    fn por_pagina(&self) -> usize {
        if self.klein() { 9 } else { 4 }
    }

    fn colunas(&self) -> usize {
        if self.klein() { 3 } else { 2 }
    }

    fn klein(&self) -> bool {
        dados::texto(&self.cfg, "layoutMode") == "klein"
    }

    fn tiles(&self) -> Vec<Tile> {
        let todos = dados::tiles_visiveis(&self.cfg);
        match (&self.modo, self.escolha_habilitada()) {
            (Some(modo), true) => todos.into_iter().filter(|t| dados::tile_na_lista(modo, &self.uso, t)).collect(),
            _ => todos,
        }
    }

    fn paginas(&self) -> usize {
        self.tiles().len().div_ceil(self.por_pagina()).max(1)
    }

    fn tiles_da_pagina(&self) -> Vec<Tile> {
        let n = self.por_pagina();
        self.tiles().into_iter().skip(self.pagina * n).take(n).collect()
    }

    fn corrigir_pagina(&mut self) {
        let p = self.paginas();
        if self.pagina >= p {
            self.pagina = p - 1;
        }
        let n = if self.na_escolha() { dados::opcoes(&self.uso).len() } else { self.tiles_da_pagina().len() };
        if self.foco >= n.max(1) {
            self.foco = 0;
        }
    }

    fn bloqueados(&self) -> Vec<String> {
        self.disp
            .get("blockedTileIds")
            .and_then(Value::as_array)
            .map(|a| a.iter().filter_map(|v| v.as_str().map(str::to_string)).collect())
            .unwrap_or_default()
    }

    fn motivo_limite(&self, tile_id: &str) -> String {
        for fonte in [self.disp.get("limitBlocked"), self.uso.get("blockedReasons")] {
            if let Some(m) = fonte.and_then(|v| v.get(tile_id)).and_then(Value::as_str) {
                return m.to_string();
            }
        }
        String::new()
    }

    fn pin_configurado(&self) -> bool {
        dados::verdade(&self.cfg, "pinConfigured")
    }

    // ------------------------------------------------------------ ações

    fn som(&self, som: Som) {
        if dados::verdade(&self.cfg, "soundFeedbackEnabled") {
            sons::tocar(som);
        }
    }

    /// Estrelinhas depois de abrir um app (opção "comemoração" do perfil).
    fn celebrar(&mut self, cx: &mut Context<Self>) {
        if !dados::verdade(&self.cfg, "celebrationEnabled") || dados::verdade(&self.cfg, "accessibilityReducedMotion") {
            return;
        }
        self.geracao += 1;
        let g = self.geracao;
        self.celebracao = Some(g);
        cx.spawn(async move |this, cx| {
            cx.background_executor().timer(Duration::from_millis(950)).await;
            let _ = this.update(cx, |m, cx| {
                if m.celebracao == Some(g) {
                    m.celebracao = None;
                    cx.notify();
                }
            });
        })
        .detach();
    }

    fn mostrar_mensagem(&mut self, titulo: String, corpo: String) {
        self.geracao += 1;
        self.janela = Some(Janela::Mensagem { titulo, corpo, geracao: self.geracao });
    }

    fn agendar_fechar_mensagem(&mut self, cx: &mut Context<Self>) {
        if let Some(Janela::Mensagem { geracao, .. }) = &self.janela {
            let g = *geracao;
            cx.spawn(async move |this, cx| {
                cx.background_executor().timer(Duration::from_secs(15)).await;
                let _ = this.update(cx, |m, cx| {
                    if matches!(&m.janela, Some(Janela::Mensagem { geracao, .. }) if *geracao == g) {
                        m.janela = None;
                        cx.notify();
                    }
                });
            })
            .detach();
        }
    }

    fn mostrar_aviso_timer(&mut self, minutos: i64, cx: &mut Context<Self>) {
        if matches!(self.janela, Some(_)) {
            return;
        }
        self.geracao += 1;
        let g = self.geracao;
        let texto = if minutos <= 1 { "Falta 1 minuto.".to_string() } else { format!("Faltam {minutos} minutos.") };
        self.janela = Some(Janela::AvisoTimer { texto, geracao: g });
        cx.spawn(async move |this, cx| {
            cx.background_executor().timer(Duration::from_secs(6)).await;
            let _ = this.update(cx, |m, cx| {
                if matches!(&m.janela, Some(Janela::AvisoTimer { geracao, .. }) if *geracao == g) {
                    m.janela = None;
                    cx.notify();
                }
            });
        })
        .detach();
    }

    fn mostrar_bloqueio(&mut self, motivo: &str, tile_id: &str, cx: &mut Context<Self>) {
        if motivo == "category_limit" || motivo == "daily_limit" {
            let cat = dados::categoria_do_tile(
                &self.uso,
                &Tile { id: tile_id.into(), label: String::new(), emoji: String::new(), gamepad: false, categoria: String::new(), biblioteca: false },
            );
            let (t, c) = dados::textos_limite(&self.uso, motivo, &cat);
            self.mostrar_mensagem(t, c);
            self.agendar_fechar_mensagem(cx);
            return;
        }
        self.janela = Some(Janela::Bloqueio { perfil: motivo != "app_schedule", foco: 0 });
    }

    fn entrar(&mut self, id: &str, cx: &mut Context<Self>) {
        let t = dados::tempo(&self.uso, id);
        if t.esgotada {
            self.som(Som::Bloqueado);
            let motivo = if dados::verdade(&self.uso, "totalExhausted") { "daily_limit" } else { "category_limit" };
            let (ti, c) = dados::textos_limite(&self.uso, motivo, id);
            self.mostrar_mensagem(ti, c);
            self.agendar_fechar_mensagem(cx);
            return;
        }
        self.modo = Some(id.to_string());
        self.pagina = 0;
        self.foco = 0;
        self.foco_visivel = true;
        self.som(Som::Navegar);
    }

    fn voltar_escolha(&mut self) {
        let Some(modo) = self.modo.take() else { return };
        self.som(Som::Navegar);
        self.pagina = 0;
        self.foco = dados::opcoes(&self.uso).iter().position(|o| o.id == modo).unwrap_or(0);
        self.foco_visivel = true;
    }

    fn mudar_pagina(&mut self, dir: i32) {
        if self.na_escolha() {
            return;
        }
        let nova = (self.pagina as i32 + dir).clamp(0, self.paginas() as i32 - 1) as usize;
        if nova != self.pagina {
            self.pagina = nova;
            self.foco = 0;
            self.som(Som::Navegar);
        }
    }

    fn mover(&mut self, dir: &str, cx: &mut Context<Self>) {
        if !self.foco_visivel {
            // a primeira seta só mostra o foco
            self.foco_visivel = true;
            return;
        }
        let escolha = self.na_escolha();
        let n = if escolha { dados::opcoes(&self.uso).len() } else { self.tiles_da_pagina().len() };
        if n == 0 {
            return;
        }
        let cols = if escolha { n } else { self.colunas() };
        let linha = self.foco / cols;
        match dir {
            "right" => {
                if (self.foco + 1) % cols != 0 && self.foco + 1 < n {
                    self.foco += 1;
                } else if !escolha && self.pagina + 1 < self.paginas() {
                    self.mudar_pagina(1);
                    self.foco = (linha * cols).min(self.tiles_da_pagina().len().saturating_sub(1));
                }
            }
            "left" => {
                if self.foco % cols != 0 {
                    self.foco -= 1;
                } else if !escolha && self.pagina > 0 {
                    self.mudar_pagina(-1);
                    self.foco = (linha * cols + cols - 1).min(self.tiles_da_pagina().len().saturating_sub(1));
                }
            }
            "down" => {
                if self.foco + cols < n {
                    self.foco += cols;
                }
            }
            "up" => {
                if self.foco >= cols {
                    self.foco -= cols;
                }
            }
            _ => {}
        }
        self.falar_foco(cx);
    }

    fn falar_foco(&mut self, cx: &mut Context<Self>) {
        if self.na_escolha()
            || !dados::verdade(&self.cfg, "speechFeedbackEnabled")
            || !dados::verdade(&self.features, "speechFeedbackAvailable")
        {
            return;
        }
        let Some(tile) = self.tiles_da_pagina().get(self.foco).cloned() else { return };
        self.fala += 1;
        let g = self.fala;
        let api = self.api.clone();
        cx.spawn(async move |this, cx| {
            cx.background_executor().timer(Duration::from_millis(450)).await;
            let ainda = this.update(cx, |m, _| m.fala == g).unwrap_or(false);
            if ainda {
                cx.background_executor()
                    .spawn(async move { api.post("/api/feedback/speak", Some(&json!({"tileId": tile.id}))) })
                    .await
                    .ok();
            }
        })
        .detach();
    }

    fn acionar(&mut self, cx: &mut Context<Self>) {
        if self.na_escolha() {
            if let Some(o) = dados::opcoes(&self.uso).get(self.foco).copied() {
                self.entrar(o.id, cx);
            }
            return;
        }
        if let Some(t) = self.tiles_da_pagina().get(self.foco).cloned() {
            self.lancar(t, cx);
        }
    }

    fn lancar(&mut self, tile: Tile, cx: &mut Context<Self>) {
        if self.bloqueados().contains(&tile.id) {
            let mut motivo = self.motivo_limite(&tile.id);
            if motivo.is_empty() {
                motivo = if dados::verdade(&self.disp, "profileAllowed") { "app_schedule".into() } else { "profile_schedule".into() };
            }
            self.som(Som::Bloqueado);
            self.mostrar_bloqueio(&motivo, &tile.id, cx);
            return;
        }
        self.som(Som::Abrir);
        if tile.biblioteca {
            self.lembrar(&tile.id);
            self.abrir_web(&format!("/media.html?tile={}", codificar(&tile.id)), cx);
            return;
        }
        self.geracao += 1;
        let g = self.geracao;
        let emoji = tile.emoji.clone();
        self.inicio = Some(Inicio {
            emoji: emoji.clone(),
            texto: format!("Abrindo {}...", tile.label),
            sucesso: false,
            geracao: g,
        });
        self.esconder_inicio_depois(g, Duration::from_millis(1500), cx);
        let id = tile.id.clone();
        self.tarefa(
            cx,
            move |api| api.post(&format!("/launch/{}", codificar(&id)), None),
            move |m, r, cx| {
                match r {
                    Ok(r) if r.status == 403 => {
                        m.inicio = None;
                        let motivo = r.json().map(|v| dados::texto(&v, "reason")).unwrap_or_default();
                        let motivo = if motivo.is_empty() { "profile_schedule".to_string() } else { motivo };
                        m.mostrar_bloqueio(&motivo, &tile.id, cx);
                        m.atualizar_disp(cx);
                    }
                    Ok(r) if (300..400).contains(&r.status) => {
                        m.inicio = None;
                        m.lembrar(&tile.id);
                        if let Some(destino) = r.cabecalho("Location").map(str::to_string) {
                            m.abrir_web(&destino, cx);
                        }
                    }
                    Ok(r) if r.ok() => {
                        m.lembrar(&tile.id);
                        if m.inicio.as_ref().is_some_and(|i| i.geracao == g) {
                            m.inicio = Some(Inicio {
                                emoji: "✨".into(),
                                texto: format!("{} está pronto", tile.label),
                                sucesso: true,
                                geracao: g,
                            });
                            m.esconder_inicio_depois(g, Duration::from_millis(900), cx);
                            m.som(Som::Sucesso);
                            m.celebrar(cx);
                        }
                        m.atualizar_uso(cx);
                    }
                    Ok(r) => {
                        log::warn!("abrir {}: o servidor respondeu {}", tile.id, r.status);
                        m.inicio = None;
                        let faltando = r.json().is_some_and(|v| dados::texto(&v, "status") == "missing");
                        let (titulo, texto) = if faltando {
                            ("Ainda não instalado", "Peça para a mamãe ou o papai instalar este app.")
                        } else {
                            ("Não deu para abrir", "Tente de novo daqui a pouco.")
                        };
                        m.mostrar_mensagem(format!("{} {}", tile.emoji, titulo), texto.into());
                        m.agendar_fechar_mensagem(cx);
                    }
                    Err(e) => {
                        log::warn!("abrir {}: {e}", tile.id);
                        m.inicio = None;
                    }
                }
                cx.notify();
            },
        );
    }

    fn esconder_inicio_depois(&self, g: u64, quanto: Duration, cx: &mut Context<Self>) {
        cx.spawn(async move |this, cx| {
            cx.background_executor().timer(quanto).await;
            let _ = this.update(cx, |m, cx| {
                if m.inicio.as_ref().is_some_and(|i| i.geracao == g) {
                    m.inicio = None;
                    cx.notify();
                }
            });
        })
        .detach();
    }

    fn lembrar(&mut self, tile_id: &str) {
        self.ultimos.insert(self.perfil_id(), tile_id.to_string());
        let dir = estado_dir();
        let _ = std::fs::create_dir_all(&dir);
        if let Ok(texto) = serde_json::to_vec(&self.ultimos) {
            let tmp = dir.join(format!("{ARQ_ESTADO}.tmp"));
            if std::fs::write(&tmp, texto).is_ok() {
                let _ = std::fs::rename(tmp, dir.join(ARQ_ESTADO));
            }
        }
    }

    /// Abre uma página do servidor no navegador (área dos pais, site embutido,
    /// biblioteca de mídia). Quando a página volta para o menu, o navegador fecha.
    pub fn abrir_web(&mut self, caminho: &str, cx: &mut Context<Self>) {
        if self.o.demo {
            self.inicio = None;
            self.mostrar_mensagem(
                "Modo demonstração".into(),
                "Aqui a área dos pais (e as páginas web) abririam no navegador.".into(),
            );
            self.agendar_fechar_mensagem(cx);
            return;
        }
        if let Some((filho, _)) = self.web.as_mut() {
            if matches!(filho.try_wait(), Ok(None)) {
                return; // já tem um aberto
            }
        }
        let url = format!("{}/cliente.html?ir={}", self.api.base(), codificar(caminho));
        let mut cmd = std::process::Command::new(&self.o.web_cmd);
        if self.o.web_familia == "chromium" {
            cmd.arg(format!("--user-data-dir={}", self.o.web_perfil.display()))
                .args(["--no-first-run", "--password-store=basic", "--kiosk", &url]);
        } else {
            cmd.arg("--no-remote")
                .arg("--profile")
                .arg(&self.o.web_perfil)
                .args(["--new-window", "--kiosk", &url]);
        }
        cmd.stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .env_remove("GPUI_RECUSAR_SOFTWARE");
        // base do contador "voltar" antes de abrir
        let base = self
            .api
            .get_json("/api/cliente/estado")
            .and_then(|v| dados::numero(&v, "voltar"))
            .unwrap_or(0.) as u64;
        match cmd.spawn() {
            Ok(filho) => {
                log::info!("navegador aberto para {caminho} (pid {})", filho.id());
                self.web = Some((filho, base));
                self.inicio = None;
                ciclo_ate(cx, Duration::from_millis(800), |m, cx| m.vigiar_web(cx));
            }
            Err(e) => log::error!("não deu para abrir o navegador ({}): {e}", self.o.web_cmd),
        }
    }

    /// Chamado a cada 0,8 s enquanto o navegador está aberto. Devolve false quando acabou.
    fn vigiar_web(&mut self, cx: &mut Context<Self>) -> bool {
        let Some((filho, base)) = self.web.as_mut() else { return false };
        match filho.try_wait() {
            Ok(None) => {
                let base = *base;
                let pid = filho.id();
                self.tarefa(
                    cx,
                    |api| api.get_json("/api/cliente/estado").and_then(|v| dados::numero(&v, "voltar")),
                    move |m, r, _| {
                        if r.is_some_and(|n| n as u64 > base) {
                            log::info!("a página pediu para voltar ao menu; fechando o navegador");
                            fechar_processo(m.web.as_mut().map(|(c, _)| c), pid);
                        }
                    },
                );
                true
            }
            _ => {
                self.web = None;
                self.api.esquecer_sessao();
                self.carregar_config(cx);
                self.atualizar_uso(cx);
                self.atualizar_disp(cx);
                self.atualizar_timer(cx);
                trazer_para_frente();
                cx.notify();
                false
            }
        }
    }

    fn pedir_pin(&mut self, acao: AcaoPin, cx: &mut Context<Self>) {
        if self.pin_configurado() {
            self.janela = Some(Janela::Pin { pin: String::new(), erro: String::new(), acao });
        } else {
            self.executar(acao, cx);
        }
    }

    fn conferir_pin(&mut self, cx: &mut Context<Self>) {
        let Some(Janela::Pin { pin, acao, .. }) = self.janela.clone() else { return };
        self.tarefa(
            cx,
            move |api| api.post("/api/verify-pin", Some(&json!({"pin": pin}))),
            move |m, r, cx| {
                let valido = r.as_ref().ok().and_then(|r| r.json()).is_some_and(|v| dados::verdade(&v, "valid"));
                if valido {
                    m.janela = None;
                    m.executar(acao, cx);
                } else if let Some(Janela::Pin { pin, erro, .. }) = m.janela.as_mut() {
                    pin.clear();
                    *erro = if r.as_ref().is_ok_and(|r| r.status == 429) {
                        "Muitas tentativas. Espere um pouco.".into()
                    } else {
                        "PIN incorreto".into()
                    };
                }
                cx.notify();
            },
        );
    }

    fn executar(&mut self, acao: AcaoPin, cx: &mut Context<Self>) {
        match acao {
            AcaoPin::Sair => self.tarefa(cx, |api| api.post("/exit-kids", None), |m, _, _| m.api.esquecer_sessao()),
            AcaoPin::Desligar => self.tarefa(cx, |api| api.post("/shutdown", None), |m, _, _| m.api.esquecer_sessao()),
            AcaoPin::Perfil(id) => self.tarefa(
                cx,
                move |api| api.post("/api/profiles/select", Some(&json!({"profileId": id}))),
                |m, r, cx| {
                    m.api.esquecer_sessao();
                    if let Some(cfg) = r.ok().and_then(|r| r.json()).and_then(|v| v.get("config").cloned()) {
                        if cfg.get("tiles").is_some() {
                            m.cfg = cfg;
                        }
                    }
                    m.janela = None;
                    m.aviso_timer_mostrado = false;
                    m.sincronizar_perfil();
                    m.carregar_config(cx);
                    m.atualizar_uso(cx);
                    m.atualizar_disp(cx);
                    m.atualizar_timer(cx);
                    cx.notify();
                },
            ),
        }
    }

    fn estender_timer(&mut self, minutos: u32, cx: &mut Context<Self>) {
        let Some(Janela::TimerEsgotado { pin, .. }) = self.janela.clone() else { return };
        self.tarefa(
            cx,
            move |api| api.post("/api/timer/extend", Some(&json!({"pin": pin, "minutes": minutos}))),
            |m, r, cx| {
                let valido = r.ok().and_then(|r| r.json()).is_some_and(|v| dados::verdade(&v, "valid"));
                if valido {
                    m.janela = None;
                    m.aviso_timer_mostrado = false;
                    m.atualizar_timer(cx);
                } else if let Some(Janela::TimerEsgotado { pin, erro, .. }) = m.janela.as_mut() {
                    pin.clear();
                    *erro = "PIN incorreto".into();
                }
                cx.notify();
            },
        );
    }

    fn abrir_pais(&mut self, cx: &mut Context<Self>) {
        self.abrir_web("/index.html?pais=1", cx);
    }

    // ------------------------------------------------------------ teclado

    fn tecla(&mut self, ev: &KeyDownEvent, cx: &mut Context<Self>) {
        let k = ev.keystroke.key.as_str();
        let digito = ev
            .keystroke
            .key_char
            .as_deref()
            .filter(|c| c.len() == 1 && c.as_bytes()[0].is_ascii_digit())
            .or_else(|| (k.len() == 1 && k.as_bytes()[0].is_ascii_digit()).then_some(k))
            .map(str::to_string);
        if self.inicio.is_some() {
            return;
        }
        if let Some(j) = self.janela.clone() {
            self.tecla_janela(j, k, digito, cx);
            cx.notify();
            return;
        }
        if self.cfg.is_null() {
            return;
        }
        match k {
            "left" | "right" | "up" | "down" => self.mover(k, cx),
            "enter" | "space" | "kp_enter" => {
                if !self.foco_visivel {
                    self.foco_visivel = true;
                } else {
                    self.acionar(cx);
                }
            }
            "escape" => {
                if self.modo.is_some() && self.escolha_habilitada() {
                    self.voltar_escolha();
                } else {
                    self.pedir_pin(AcaoPin::Sair, cx);
                }
            }
            "pageup" => self.mudar_pagina(-1),
            "pagedown" => self.mudar_pagina(1),
            _ => return,
        }
        cx.notify();
    }

    fn tecla_janela(&mut self, j: Janela, k: &str, digito: Option<String>, cx: &mut Context<Self>) {
        match j {
            Janela::Mensagem { .. } | Janela::AvisoTimer { .. } => {
                if matches!(k, "enter" | "escape" | "space") {
                    self.janela = None;
                    self.foco_visivel = true;
                }
            }
            Janela::Bloqueio { perfil, foco } => {
                if !perfil {
                    if matches!(k, "enter" | "escape" | "space") {
                        self.janela = None;
                    }
                    return;
                }
                match k {
                    "left" | "right" => self.janela = Some(Janela::Bloqueio { perfil, foco: 1 - foco.min(1) }),
                    "enter" | "space" => {
                        if foco == 0 {
                            self.abrir_pais(cx);
                        } else {
                            self.pedir_pin(AcaoPin::Sair, cx);
                        }
                    }
                    _ => {}
                }
            }
            Janela::TimerEsgotado { mut pin, erro, foco } => {
                if let Some(d) = digito {
                    if pin.len() < 8 {
                        pin.push_str(&d);
                    }
                    self.janela = Some(Janela::TimerEsgotado { pin, erro: String::new(), foco });
                    return;
                }
                match k {
                    "backspace" => {
                        pin.pop();
                        self.janela = Some(Janela::TimerEsgotado { pin, erro, foco });
                    }
                    "left" => self.janela = Some(Janela::TimerEsgotado { pin, erro, foco: foco.saturating_sub(1) }),
                    "right" => self.janela = Some(Janela::TimerEsgotado { pin, erro, foco: (foco + 1).min(3) }),
                    "enter" | "kp_enter" => {
                        if foco == 3 {
                            self.pedir_pin(AcaoPin::Sair, cx);
                        } else {
                            self.estender_timer([15, 30, 60][foco], cx);
                        }
                    }
                    _ => {}
                }
            }
            Janela::Pin { mut pin, erro, acao } => {
                if let Some(d) = digito {
                    if pin.len() < 8 {
                        pin.push_str(&d);
                    }
                    self.janela = Some(Janela::Pin { pin, erro: String::new(), acao });
                    return;
                }
                match k {
                    "backspace" => {
                        pin.pop();
                        self.janela = Some(Janela::Pin { pin, erro, acao });
                    }
                    "escape" => self.fechar_pin(),
                    "enter" | "kp_enter" => self.conferir_pin(cx),
                    _ => {}
                }
            }
            Janela::Perfis { foco } => {
                let n = self.perfis().len();
                match k {
                    "left" | "up" => self.janela = Some(Janela::Perfis { foco: foco.saturating_sub(1) }),
                    "right" | "down" => self.janela = Some(Janela::Perfis { foco: (foco + 1).min(n.saturating_sub(1)) }),
                    "escape" => self.janela = None,
                    "enter" | "space" => self.escolher_perfil(foco, cx),
                    _ => {}
                }
            }
        }
    }

    fn fechar_pin(&mut self) {
        // se o PIN veio do bloqueio de horário, volta para ele
        self.janela = None;
        if !dados::verdade(&self.disp, "profileAllowed") {
            self.janela = Some(Janela::Bloqueio { perfil: true, foco: 0 });
        } else if dados::verdade(&self.timer, "active") && dados::verdade(&self.timer, "expired") {
            self.janela = Some(Janela::TimerEsgotado { pin: String::new(), erro: String::new(), foco: 0 });
        }
    }

    fn perfis(&self) -> Vec<(String, String, String)> {
        self.cfg
            .get("profiles")
            .and_then(Value::as_array)
            .map(|a| {
                a.iter()
                    .map(|p| (dados::texto(p, "id"), dados::texto(p, "name"), dados::texto(p, "avatar")))
                    .collect()
            })
            .unwrap_or_default()
    }

    fn escolher_perfil(&mut self, i: usize, cx: &mut Context<Self>) {
        let Some((id, _, _)) = self.perfis().get(i).cloned() else { return };
        if id == self.perfil_id() {
            self.janela = None;
            return;
        }
        self.janela = None;
        self.pedir_pin(AcaoPin::Perfil(id), cx);
    }

    // ------------------------------------------------------------ desenho

    fn esc(&self, window: &Window) -> f32 {
        let v = window.viewport_size();
        let e = (f32::from(v.width) / 1366.).min(f32::from(v.height) / 768.);
        e.clamp(0.55, 2.5)
    }
}

// ---------------------------------------------------------------- desenho

struct Pincel {
    e: f32, // escala da tela (1366×768 = 1)
    texto_grande: f32,
    t: Tema,
}

impl Pincel {
    fn z(&self, v: f32) -> gpui::Pixels {
        px(v * self.e)
    }
    fn f(&self, v: f32) -> gpui::Pixels {
        px(v * self.e * self.texto_grande)
    }
    fn fonte<E: Styled>(&self, el: E) -> E {
        let el = el.font_family(SharedString::from(self.t.fonte.unwrap_or(tema::FONTE_PADRAO)));
        match (self.t.fonte, self.t.fonte_peso) {
            (_, Some(p)) => el.font_weight(FontWeight(p as f32)),
            (Some(_), None) => el.font_weight(FontWeight(400.)),
            (None, None) => el.font_weight(FontWeight(700.)),
        }
    }
    fn caixa(&self, s: &str) -> String {
        if self.t.maiusculas { s.to_uppercase() } else { s.to_string() }
    }
    fn sombras(&self, lista: &[tema::Sombra]) -> Vec<BoxShadow> {
        sombras(lista)
            .into_iter()
            .rev() // no CSS a primeira sombra fica por cima; no gpui, a última
            .map(|mut s| {
                s.offset = point(s.offset.x * self.e, s.offset.y * self.e);
                s.blur_radius = s.blur_radius * self.e;
                s.spread_radius = s.spread_radius * self.e;
                s
            })
            .collect()
    }

    /// Botão pequeno (smallbtn) com o visual do tema.
    fn pequeno(&self, id: impl Into<gpui::ElementId>) -> gpui::Stateful<gpui::Div> {
        let t = &self.t;
        let d = div()
            .id(id)
            .flex()
            .items_center()
            .justify_center()
            .gap(self.z(8.))
            .h(self.z(54.))
            .min_w(self.z(110.))
            .px(self.z(18.))
            .rounded(self.z(t.peq_raio.min(27.)))
            .bg(hsla_a(t.peq_fundo))
            .text_color(hsla(t.peq_texto))
            .text_size(self.f(if t.fonte == Some("Bangers") { 17. } else { 16. }))
            .shadow(self.sombras(t.peq_sombras))
            .cursor_pointer()
            .when(t.peq_borda > 0., |d| d.border(self.z(t.peq_borda)).border_color(hsla(t.peq_borda_cor)));
        self.fonte(d)
    }

    fn icone(&self, nome: &str, cor: u32, tamanho: f32) -> AnyElement {
        img(icone(nome, cor)).w(self.z(tamanho)).h(self.z(tamanho)).flex_none().into_any_element()
    }

    /// Texto com "sombra de texto" (cópias deslocadas por baixo).
    fn texto_com_sombra(&self, texto: String, tamanho: f32, cor: u32, sombras: &[(f32, f32, u32)]) -> AnyElement {
        let base = || self.fonte(div().whitespace_nowrap().text_size(self.f(tamanho)).line_height(self.f(tamanho * 1.15)));
        let mut d = div().relative();
        for (dx, dy, c) in sombras {
            d = d.child(base().absolute().left(self.z(*dx)).top(self.z(*dy)).text_color(hsla(*c)).child(texto.clone()));
        }
        d.child(base().relative().text_color(hsla(cor)).child(texto)).into_any_element()
    }
}

impl Render for Menu {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let t = self.tema();
        let grande = dados::verdade(&self.cfg, "accessibilityLargeText");
        let p = Pincel { e: self.esc(window), texto_grande: if grande { 1.125 } else { 1. }, t };
        let mut raiz = div()
            .id("menu")
            .font(gpui::Font {
                family: SharedString::from(tema::FONTE_PADRAO),
                features: Default::default(),
                fallbacks: Some(gpui::FontFallbacks::from_fonts(vec![tema::FONTE_EMOJI.to_string()])),
                weight: FontWeight(400.),
                style: gpui::FontStyle::Normal,
            })
            .track_focus(&self.focus)
            .on_key_down(cx.listener(|this, ev: &KeyDownEvent, _, cx| this.tecla(ev, cx)))
            .size_full()
            .relative()
            .overflow_hidden()
            .child(self.fundo(&p));
        if self.cfg.is_null() {
            let msg = if self.erro_inicio { "Abrindo o menu… (esperando o servidor)" } else { "Abrindo o menu…" };
            return raiz.child(
                div().absolute().inset_0().flex().items_center().justify_center().child(
                    p.texto_com_sombra(msg.into(), 34., p.t.titulo_cor, p.t.titulo_sombras),
                ),
            );
        }
        raiz = raiz.child(self.conteudo(&p, cx));
        raiz = raiz.child(self.setas(&p, cx));
        raiz = raiz.child(self.cantos(&p, cx));
        raiz = raiz.child(self.selos(&p));
        if let Some(j) = self.janela.clone() {
            raiz = raiz.child(self.janela_el(&p, j, cx));
        }
        if let Some(i) = &self.inicio {
            raiz = raiz.child(self.inicio_el(&p, i));
        }
        if let Some(g) = self.celebracao {
            let v = window.viewport_size();
            raiz = raiz.child(celebracao_el(g, f32::from(v.width), f32::from(v.height)));
        }
        raiz
    }
}

impl Menu {
    fn fundo(&self, p: &Pincel) -> AnyElement {
        let t = &p.t;
        let base = div().absolute().inset_0().bg(linear_gradient(
            180.,
            linear_color_stop(hsla(t.bg1), 0.),
            linear_color_stop(hsla(t.bg2), 1.),
        ));
        let Fundo::Imagem(arq) = t.fundo else { return base.into_any_element() };
        let mut caminho = self.o.app_root.join("themes").join(arq);
        if arq.ends_with(".svg") {
            // largura estável (a janela começa menor antes de ir para tela cheia)
            let largura = ((1366. * p.e.max(1.)) / 100.).ceil() as u32 * 100;
            caminho = fundo_rasterizado(&caminho, largura);
        }
        let movimento = dados::verdade(&self.cfg, "themeMotionEnabled")
            && !dados::verdade(&self.cfg, "accessibilityReducedMotion")
            && arq.ends_with(".jpg")
            && self.ativa;
        if movimento {
            // o mundo "respira" devagar (worldThemeDrift), só com a janela ativa
            let foto = img(caminho).absolute().top(px(0.)).left(px(0.)).size_full().object_fit(ObjectFit::Cover);
            return base
                .child(
                    div().absolute().inset_0().child(foto.with_animation(
                        "deriva",
                        gpui::Animation::new(Duration::from_secs(30)).repeat(),
                        |f, k| {
                            let s = (k * std::f32::consts::TAU).sin();
                            f.left(px(12. * s)).top(px(-7. * s))
                        },
                    )),
                )
                .into_any_element();
        }
        base.child(img(caminho).absolute().inset_0().size_full().object_fit(ObjectFit::Cover)).into_any_element()
    }

    fn titulo(&self, p: &Pincel) -> AnyElement {
        let t = &p.t;
        let mut texto = dados::texto(&self.cfg, "title");
        if texto.is_empty() {
            texto = "Hello Kiddo 🌈".into();
        }
        let tamanho = if t.fonte.is_some() { 64. } else { 54. };
        let el = p.texto_com_sombra(p.caixa(&texto), tamanho, t.titulo_cor, t.titulo_sombras);
        match t.titulo_fundo {
            Some(f) if t.fundo != Fundo::Cores => div()
                .px(p.z(26.))
                .py(p.z(2.))
                .rounded(p.z(18.))
                .bg(hsla_a(f))
                .child(el)
                .into_any_element(),
            _ => el,
        }
    }

    fn conteudo(&self, p: &Pincel, cx: &mut Context<Self>) -> AnyElement {
        let escolha = self.na_escolha();
        // título (+ "Voltar" e a categoria quando está na lista filtrada)
        let mut topo = div()
            .relative()
            .w(p.z(1180.))
            .h(p.z(112.))
            .mb(p.z(22.))
            .flex()
            .items_end()
            .justify_center()
            .child(self.titulo(p));
        if let (Some(modo), true) = (&self.modo, self.escolha_habilitada()) {
            topo = topo.child(
                p.pequeno("voltar")
                    .absolute()
                    .left(px(0.))
                    .bottom(p.z(6.))
                    .h(p.z(64.))
                    .px(p.z(26.))
                    .text_size(p.f(23.))
                    .child(p.icone("back", p.t.peq_texto, 26.))
                    .child("Voltar")
                    .on_click(cx.listener(|m, _: &ClickEvent, _, cx| {
                        m.voltar_escolha();
                        cx.notify();
                    })),
            );
            if let Some(o) = dados::opcao(&self.uso, modo) {
                topo = topo.child(self.chip(p, o));
            }
        }
        let corpo = if escolha && self.uso.is_null() && self.iniciado.elapsed() < Duration::from_secs(4) {
            // sem o uso ainda não se sabe se tem Passatempo: espera (evita a tela "pular")
            div().h(p.z(420.)).into_any_element()
        } else if escolha {
            self.escolha_el(p, cx)
        } else {
            self.grade(p, cx)
        };
        div()
            .absolute()
            .top(px(0.))
            .left(px(0.))
            .right(px(0.))
            .bottom(p.z(90.))
            .flex()
            .flex_col()
            .items_center()
            .justify_center()
            .child(topo)
            .child(corpo)
            .into_any_element()
    }

    fn chip(&self, p: &Pincel, o: dados::Opcao) -> AnyElement {
        let tempo = dados::tempo(&self.uso, o.id);
        let texto = dados::texto_tempo(&tempo);
        let mut corpo = div()
            .flex()
            .flex_col()
            .gap(p.z(5.))
            .min_w(p.z(120.))
            .child(p.fonte(div()).text_size(p.f(19.)).child(p.caixa(o.lista)));
        if tempo.com_tempo && !tempo.esgotada {
            corpo = corpo.child(self.barra(p, &tempo, p.z(120.)));
        }
        let mut chip = p
            .pequeno("chip")
            .absolute()
            .right(px(0.))
            .bottom(p.z(6.))
            .h(p.z(64.))
            .px(p.z(20.))
            .gap(p.z(12.))
            .cursor_default()
            .child(div().text_size(p.f(34.)).child(if tempo.esgotada { "🔒" } else { o.emoji }))
            .child(corpo);
        if !texto.is_empty() {
            chip = chip.child(
                div()
                    .text_size(p.f(17.))
                    .child(if tempo.esgotada { "acabou".to_string() } else { texto }),
            );
        }
        chip.into_any_element()
    }

    fn barra(&self, p: &Pincel, t: &dados::Tempo, largura: gpui::Pixels) -> AnyElement {
        let fr = dados::fracao_barra(t);
        let faixa = if t.esgotada { Faixa::Acabou } else { dados::faixa(Some(t.restante), t.limite) };
        div()
            .w(largura)
            .h(p.z(16.))
            .rounded(p.z(10.))
            .bg(hsla(p.t.cartao_texto).opacity(0.16))
            .border(p.z(2.))
            .border_color(hsla(p.t.cartao_texto).opacity(0.22))
            .overflow_hidden()
            .child(div().h_full().w(gpui::relative(fr)).rounded(p.z(10.)).bg(hsla(faixa.cor())))
            .into_any_element()
    }

    /// Cartão (tile) com o visual do tema. `indice` = posição na grade (cores alternadas).
    fn cartao(&self, p: &Pincel, indice: usize, largura: f32, altura: f32) -> gpui::Div {
        let t = &p.t;
        let cor = t.cartao_cores[indice % t.cartao_cores.len()];
        let mut sombras_lista = if !t.cartao_sombras_par.is_empty() && indice % 2 == 1 {
            p.sombras(t.cartao_sombras_par)
        } else {
            p.sombras(t.cartao_sombras)
        };
        if !t.cartao_cores_escuras.is_empty() {
            let escura = t.cartao_cores_escuras[indice % t.cartao_cores_escuras.len()];
            let (inset, dy) = if t.enfeite == Enfeite::Pinos { (true, -10.) } else { (false, 8.) };
            sombras_lista.insert(
                0,
                BoxShadow {
                    color: hsla(escura),
                    offset: point(px(0.), p.z(dy)),
                    blur_radius: px(0.),
                    spread_radius: px(0.),
                    inset,
                },
            );
        }
        let mut d = div()
            .relative()
            .w(p.z(largura))
            .h(p.z(altura))
            .rounded(p.z(t.cartao_raio))
            .shadow(sombras_lista)
            .text_color(hsla(t.cartao_texto))
            .flex()
            .flex_col()
            .items_center()
            .justify_center();
        d = match t.cartao_gradiente {
            Some((a, b)) => d.bg(linear_gradient(160., linear_color_stop(hsla_a(a), 0.), linear_color_stop(hsla_a(b), 1.))),
            None => d.bg(hsla_a(cor)),
        };
        if t.cartao_borda > 0. {
            d = d.border(p.z(t.cartao_borda)).border_color(hsla(t.cartao_borda_cor));
        }
        match t.enfeite {
            Enfeite::Floco => {
                d = d.child(
                    div().absolute().top(p.z(8.)).right(p.z(18.)).text_size(p.f(26.)).text_color(hsla(t.enfeite_cor)).child("❄"),
                )
            }
            Enfeite::Coroa => {
                d = d.child(
                    div().absolute().top(p.z(-24.)).left(px(0.)).right(px(0.)).flex().justify_center().text_size(p.f(30.)).child("👑"),
                )
            }
            Enfeite::Pinos => {
                let mut pinos = div().absolute().top(p.z(-16.)).left(p.z(largura * 0.08)).right(p.z(largura * 0.08)).flex().justify_around();
                for _ in 0..4 {
                    pinos = pinos.child(div().w(p.z(largura * 0.12)).h(p.z(16.)).rounded_t(p.z(8.)).bg(hsla_a(cor)));
                }
                d = d.child(pinos);
            }
            Enfeite::Telhado | Enfeite::Nenhum => {}
        }
        d
    }

    /// Contorno de foco (outline) em volta de um cartão.
    fn foco_el(&self, p: &Pincel) -> AnyElement {
        let t = &p.t;
        let fora = t.foco_distancia + t.foco_largura;
        div()
            .absolute()
            .top(p.z(-fora))
            .left(p.z(-fora))
            .right(p.z(-fora))
            .bottom(p.z(-fora))
            .rounded(p.z(t.cartao_raio + fora))
            .border(p.z(t.foco_largura))
            .border_color(hsla(t.foco_cor))
            .when(t.foco_tracejado, |d| d.border_dashed())
            .into_any_element()
    }

    fn visual(&self, p: &Pincel, emoji: &str, tamanho: f32, largura: f32, altura: f32) -> AnyElement {
        if let Some(rel) = emoji.strip_prefix("img:") {
            if !rel.contains("..") {
                let caminho = self.o.app_root.join("themes").join(rel);
                return img(caminho)
                    .h(p.z(altura * 0.58))
                    .max_w(p.z(largura * 0.86))
                    .rounded(p.z(12.))
                    .object_fit(ObjectFit::Contain)
                    .into_any_element();
            }
        }
        let e = if emoji.is_empty() { "⭐" } else { emoji };
        div().text_size(p.f(tamanho)).line_height(p.f(tamanho * 1.15)).child(e.to_string()).into_any_element()
    }

    fn escolha_el(&self, p: &Pincel, cx: &mut Context<Self>) -> AnyElement {
        let opcoes = dados::opcoes(&self.uso);
        let n = opcoes.len();
        let (largura_total, gap) = if n == 3 { (1240., 32.) } else { (1000., 48.) };
        let largura = (largura_total - gap * (n as f32 - 1.)) / n as f32;
        let altura = 360.;
        let pergunta = p.texto_com_sombra(
            p.caixa("O que você quer fazer?"),
            43.,
            p.t.titulo_cor,
            p.t.titulo_sombras,
        );
        // com dica em algum cartão, todos reservam o espaço dela (títulos alinhados)
        let alguma_regra = opcoes.iter().any(|o| !dados::texto_regra(&self.uso, o.id).is_empty());
        let mut linha = div().flex().gap(p.z(gap));
        for (i, o) in opcoes.iter().enumerate() {
            let tempo = dados::tempo(&self.uso, o.id);
            let regra = dados::texto_regra(&self.uso, o.id);
            let texto = dados::texto_tempo(&tempo);
            let emoji = div()
                .relative()
                .text_size(p.f(if n == 3 { 99. } else { 120. }))
                .line_height(p.f(if n == 3 { 110. } else { 132. }))
                .child(o.emoji)
                .when(tempo.esgotada, |d| {
                    d.child(div().absolute().right(p.z(-30.)).bottom(p.z(-8.)).text_size(p.f(52.)).child("🔒"))
                });
            let mut c = self
                .cartao(p, i, largura, altura)
                .gap(p.z(10.))
                .px(p.z(18.))
                .child(emoji)
                .child(p.fonte(div()).text_size(p.f(if n == 3 { 45. } else { 54. })).line_height(p.f(50.)).child(p.caixa(o.titulo)));
            if tempo.com_tempo || tempo.esgotada {
                let mut bloco = div().flex().flex_col().items_center().gap(p.z(8.)).w(p.z((largura * 0.86).min(320.)));
                if tempo.com_tempo && !tempo.esgotada {
                    bloco = bloco.child(self.barra(p, &tempo, p.z((largura * 0.86).min(320.))));
                }
                bloco = bloco.child(p.fonte(div()).text_size(p.f(25.)).child(p.caixa(&texto)));
                c = c.child(bloco);
            }
            if alguma_regra {
                c = c.child(
                    div()
                        .h(p.f(42.))
                        .font_family(SharedString::from(tema::FONTE_PADRAO))
                        .font_weight(FontWeight(700.))
                        .text_size(p.f(15.))
                        .line_height(p.f(20.))
                        .text_center()
                        .child(regra),
                );
            }
            let id = o.id;
            let mut celula = div()
                .id(("escolha", i))
                .relative()
                .cursor_pointer()
                .when(tempo.esgotada, |d| d.opacity(0.78))
                .child(c)
                .on_click(cx.listener(move |m, _: &ClickEvent, _, cx| {
                    m.foco = i;
                    m.entrar(id, cx);
                    cx.notify();
                }));
            if self.foco == i && self.foco_visivel && self.janela.is_none() {
                celula = celula.child(self.foco_el(p));
            }
            linha = linha.child(celula);
        }
        div()
            .flex()
            .flex_col()
            .items_center()
            .gap(p.z(18.))
            .child(pergunta)
            .child(linha)
            .into_any_element()
    }

    fn grade(&self, p: &Pincel, cx: &mut Context<Self>) -> AnyElement {
        let tiles = self.tiles_da_pagina();
        if tiles.is_empty() {
            return div()
                .flex()
                .flex_col()
                .items_center()
                .gap(p.z(12.))
                .px(p.z(40.))
                .py(p.z(30.))
                .rounded(p.z(24.))
                .bg(hsla_a(0xffffffe6))
                .text_color(hsla(p.t.texto))
                .child(div().text_size(p.f(80.)).child("🤔"))
                .child(p.fonte(div()).text_size(p.f(24.)).child("Peça para a mamãe ou o papai adicionar apps!"))
                .into_any_element();
        }
        let klein = self.klein();
        let cols = self.colunas();
        let (gap, altura) = if klein { (26., 140.) } else { (26., 190.) };
        let largura = (1180. - gap * (cols as f32 - 1.)) / cols as f32;
        let emoji_tam = if klein { 42. } else { p.t.tamanho_emoji_grande };
        let rotulo = match (klein, p.t.fonte) {
            (true, _) => 21.6,
            (false, Some("Bangers")) => 38.,
            (false, Some("Fredoka")) => 36.,
            (false, _) => 32.,
        };
        let bloqueados = self.bloqueados();
        let ultimo = self.ultimos.get(&self.perfil_id()).cloned().unwrap_or_default();
        // folga de alguns px: com a escala (ex.: 2560×1080 → 1,406) o arredondamento
        // da largura dos cartões passava de 1180 e a 3ª coluna quebrava de linha
        let mut grade = div().flex().flex_wrap().gap(p.z(gap)).w(p.z(1180.) + px(6.));
        for i in 0..self.por_pagina() {
            let Some(tile) = tiles.get(i) else {
                grade = grade.child(div().w(p.z(largura)).h(p.z(altura)));
                continue;
            };
            let bloqueado = bloqueados.contains(&tile.id);
            let mut c = self
                .cartao(p, i, largura, altura)
                .gap(p.z(if klein { 6. } else { 14. }))
                .px(p.z(12.))
                .child(self.visual(p, &tile.emoji, emoji_tam, largura, altura))
                .child(
                    p.fonte(div())
                        .text_size(p.f(rotulo))
                        .line_height(p.f(rotulo * 1.1))
                        .max_w(p.z(largura - 24.))
                        .px(p.z(6.)) // folga para letras inclinadas (Bangers) não serem cortadas
                        .whitespace_nowrap()
                        .text_ellipsis()
                        .overflow_hidden()
                        .child(p.caixa(&tile.label)),
                );
            if tile.gamepad {
                c = c.child(div().absolute().bottom(p.z(8.)).right(p.z(12.)).text_size(p.f(22.)).child("🎮"));
            }
            if tile.id == ultimo {
                c = c.child(div().absolute().top(p.z(8.)).right(p.z(8.)).child(p.icone("star", p.t.botao, 22.)));
            }
            if bloqueado {
                c = c.child(div().absolute().top(p.z(10.)).right(p.z(12.)).text_size(p.f(20.)).child("🔒"));
            }
            let tile_c = tile.clone();
            let mut celula = div()
                .id(("tile", i))
                .relative()
                .cursor_pointer()
                .when(bloqueado, |d| d.opacity(0.62))
                .child(c)
                .on_click(cx.listener(move |m, _: &ClickEvent, _, cx| {
                    m.foco = i;
                    m.lancar(tile_c.clone(), cx);
                    cx.notify();
                }));
            if self.foco == i && self.foco_visivel && self.janela.is_none() {
                celula = celula.child(self.foco_el(p));
            }
            grade = grade.child(celula);
        }
        grade.into_any_element()
    }

    /// Setas de página nas laterais da tela (só na lista de ícones).
    fn setas(&self, p: &Pincel, cx: &mut Context<Self>) -> AnyElement {
        let mut camada = div().absolute().inset_0();
        if self.na_escolha() || self.cfg.is_null() {
            return camada.into_any_element();
        }
        let seta = |id: &'static str, icone_nome: &'static str, dir: i32| {
            p.pequeno(id)
                .absolute()
                .top(gpui::relative(0.5))
                .mt(p.z(-60.))
                .min_w(p.z(56.))
                .w(p.z(56.))
                .h(p.z(120.))
                .px(px(0.))
                .rounded(p.z(16.))
                .child(p.icone(icone_nome, p.t.peq_texto, 36.))
                .on_click(cx.listener(move |m, _: &ClickEvent, _, cx| {
                    m.mudar_pagina(dir);
                    cx.notify();
                }))
        };
        if self.pagina > 0 {
            camada = camada.child(seta("seta-esq", "nav-left", -1).left(p.z(14.)));
        }
        if self.pagina + 1 < self.paginas() {
            camada = camada.child(seta("seta-dir", "nav-right", 1).right(p.z(14.)));
        }
        camada.into_any_element()
    }

    fn cantos(&self, p: &Pincel, cx: &mut Context<Self>) -> AnyElement {
        let t = &p.t;
        let mut esquerda = div().flex().gap(p.z(12.));
        if dados::verdade(&self.features, "shutdownAvailable") {
            let rotulo = dados::texto(&self.cfg, "shutdownLabel");
            esquerda = esquerda.child(
                p.pequeno("desligar")
                    .child(p.icone("power", t.peq_texto, 20.))
                    .child(p.caixa(if rotulo.is_empty() { "Desligar" } else { &rotulo }))
                    .on_click(cx.listener(|m, _: &ClickEvent, _, cx| {
                        m.pedir_pin(AcaoPin::Desligar, cx);
                        cx.notify();
                    })),
            );
        }
        let perfil = self.perfis().into_iter().find(|(id, _, _)| *id == self.perfil_id());
        let (nome, avatar) = perfil.map(|(_, n, a)| (n, a)).unwrap_or_else(|| (dados::texto(&self.cfg, "name"), dados::texto(&self.cfg, "avatar")));
        esquerda = esquerda.child(
            p.pequeno("perfil")
                .child(div().text_size(p.f(22.)).child(if avatar.is_empty() { "👤".to_string() } else { avatar }))
                .child(p.caixa(&nome))
                .on_click(cx.listener(|m, _: &ClickEvent, _, cx| {
                    let i = m.perfis().iter().position(|(id, _, _)| *id == m.perfil_id()).unwrap_or(0);
                    m.janela = Some(Janela::Perfis { foco: i });
                    cx.notify();
                })),
        );
        let sair = dados::texto(&self.cfg, "exitLabel");
        let pais = dados::texto(&self.cfg, "parentLabel");
        let mut botao_pais = p
            .pequeno("pais")
            .relative()
            .child(p.icone("system", t.peq_texto, 20.))
            .child(p.caixa(if pais.is_empty() { "Pais" } else { &pais }))
            .on_click(cx.listener(|m, _: &ClickEvent, _, cx| {
                m.abrir_pais(cx);
                cx.notify();
            }));
        if self.atualizacao {
            botao_pais = botao_pais.child(
                div()
                    .absolute()
                    .top(p.z(-6.))
                    .right(p.z(-6.))
                    .w(p.z(22.))
                    .h(p.z(22.))
                    .rounded_full()
                    .bg(hsla(0xe53935))
                    .text_color(hsla(0xffffff))
                    .text_size(p.f(13.))
                    .flex()
                    .items_center()
                    .justify_center()
                    .child("1"),
            );
        }
        let direita = div()
            .flex()
            .gap(p.z(12.))
            .child(
                p.pequeno("sair")
                    .child(p.icone("exit", t.peq_texto, 20.))
                    .child(p.caixa(if sair.is_empty() { "Sair" } else { &sair }))
                    .on_click(cx.listener(|m, _: &ClickEvent, _, cx| {
                        m.pedir_pin(AcaoPin::Sair, cx);
                        cx.notify();
                    })),
            )
            .child(botao_pais);
        let mut meio = div().flex().gap(p.z(12.));
        if !self.na_escolha() {
            for (i, item) in dados::medidores(&self.uso).into_iter().enumerate() {
                meio = meio.child(self.medidor(p, i, item));
            }
        }
        div()
            .absolute()
            .left(p.z(20.))
            .right(p.z(20.))
            .bottom(p.z(18.))
            .flex()
            .justify_between()
            .items_end()
            .child(esquerda)
            .child(meio)
            .child(direita)
            .into_any_element()
    }

    fn medidor(&self, p: &Pincel, i: usize, item: dados::Medidor) -> AnyElement {
        let faixa = if item.esgotado { Faixa::Acabou } else { dados::faixa(item.disponivel, item.limite) };
        let usado = (dados::minutos_usados(item.usado) as f64).min(item.limite / 60.) as i64;
        let limite = (item.limite / 60.).round() as i64;
        let fr = if item.limite > 0. { (item.usado / item.limite).clamp(0., 1.) as f32 } else { 1. };
        let fr = if item.esgotado { 1. } else { fr };
        let mut texto = div().flex().flex_col().gap(p.z(4.)).min_w(p.z(96.)).child(
            div().text_size(p.f(15.)).line_height(p.f(16.)).child(item.nome.clone()),
        );
        texto = texto.child(
            div()
                .w_full()
                .h(p.z(8.))
                .rounded(p.z(6.))
                .bg(hsla(p.t.peq_texto).opacity(0.18))
                .overflow_hidden()
                .child(div().h_full().w(gpui::relative(fr)).bg(hsla(faixa.cor()))),
        );
        if !item.nota.is_empty() {
            texto = texto.child(div().text_size(p.f(12.)).child(item.nota.clone()));
        }
        let vermelho = matches!(faixa, Faixa::Pouco | Faixa::Acabou);
        p.pequeno(("medidor", i))
            .cursor_default()
            .gap(p.z(10.))
            .child(div().text_size(p.f(25.)).child(if item.esgotado { "🔒".to_string() } else { item.emoji.clone() }))
            .child(texto)
            .child(
                div()
                    .text_size(p.f(16.))
                    .when(vermelho, |d| d.text_color(hsla(0xd32f2f)))
                    .child(if item.esgotado { "acabou".to_string() } else { format!("{usado}/{limite} min") }),
            )
            .into_any_element()
    }

    /// Relógio, bateria e timer (canto de cima).
    fn selos(&self, p: &Pincel) -> AnyElement {
        let t = &p.t;
        let selo = |id: &'static str| {
            p.pequeno(id).h(p.z(40.)).min_w(px(0.)).px(p.z(14.)).rounded(p.z(16.)).cursor_default()
        };
        let (h, m) = agora_local();
        let icone_hora = match h {
            5..=10 => "sunrise",
            11..=16 => "sun",
            17..=20 => "sunset",
            _ => "moon",
        };
        let mut linha = div().absolute().top(p.z(18.)).right(p.z(18.)).flex().gap(p.z(10.));
        if dados::verdade(&self.timer, "active") {
            let esgotado = dados::verdade(&self.timer, "expired");
            let aviso = dados::verdade(&self.timer, "warning");
            let resto = dados::minutos_usados(dados::numero(&self.timer, "remainingSeconds").unwrap_or(0.));
            let (fundo, cor) = if esgotado {
                (0xffebeeff, 0xcc0000)
            } else if aviso {
                (0xfff3e0ff, 0xe65100)
            } else {
                (t.peq_fundo, t.peq_texto)
            };
            linha = linha.child(
                selo("timer")
                    .bg(hsla_a(fundo))
                    .text_color(hsla(cor))
                    .child(p.icone("timer", cor, 18.))
                    .child(if esgotado { "Acabou o tempo!".to_string() } else { format!("{resto} min") }),
            );
        }
        if let Some((pct, carregando)) = self.bateria {
            let nome = if carregando { "charging" } else if pct <= 20 { "battery-low" } else { "battery" };
            linha = linha.child(selo("bateria").child(p.icone(nome, t.peq_texto, 18.)).child(format!("{pct}%")));
        }
        linha = linha.child(selo("relogio").child(p.icone(icone_hora, t.peq_texto, 18.)).child(format!("{h}:{m:02}")));
        linha.into_any_element()
    }

    fn caixa_janela(&self, p: &Pincel) -> gpui::Div {
        div()
            .flex()
            .flex_col()
            .items_center()
            .gap(p.z(12.))
            .max_w(p.z(640.))
            .px(p.z(40.))
            .py(p.z(32.))
            .rounded(p.z(24.))
            .bg(hsla(0xffffff))
            .text_color(hsla(0x333333))
            .shadow(p.sombras(&[tema::Sombra { x: 0., y: 14., blur: 40., spread: 0., cor: 0x00000040 }]))
            .font_family(SharedString::from(tema::FONTE_PADRAO))
    }

    fn botao_janela(&self, p: &Pincel, id: &'static str, texto: String, focado: bool) -> gpui::Stateful<gpui::Div> {
        div()
            .id(id)
            .flex()
            .items_center()
            .justify_center()
            .h(p.z(54.))
            .min_w(p.z(110.))
            .px(p.z(18.))
            .rounded(p.z(18.))
            .bg(hsla(0xf3f3f6))
            .text_size(p.f(18.))
            .font_weight(FontWeight(700.))
            .cursor_pointer()
            .border(p.z(4.))
            .border_color(if focado { hsla(p.t.botao) } else { hsla_a(0x00000000) })
            .child(texto)
    }

    fn janela_el(&self, p: &Pincel, j: Janela, cx: &mut Context<Self>) -> AnyElement {
        let titulo = |texto: String| div().text_size(p.f(28.)).font_weight(FontWeight(800.)).text_center().child(texto);
        let corpo = |texto: String| div().text_size(p.f(18.)).text_center().child(texto);
        let caixa = match j {
            Janela::Mensagem { titulo: t, corpo: c, .. } => self
                .caixa_janela(p)
                .child(div().text_size(p.f(48.)).child("⏰"))
                .child(titulo(t))
                .child(corpo(c))
                .child(self.botao_janela(p, "ok", "OK 👍".into(), true).on_click(cx.listener(|m, _: &ClickEvent, _, cx| {
                    m.janela = None;
                    cx.notify();
                }))),
            Janela::AvisoTimer { texto, .. } => self
                .caixa_janela(p)
                .child(p.icone("timer", 0xe65100, 48.))
                .child(titulo("Faltam 5 minutos!".into()))
                .child(corpo(texto)),
            Janela::Bloqueio { perfil, foco } => {
                let mut c = self
                    .caixa_janela(p)
                    .child(div().text_size(p.f(48.)).child("🌙"))
                    .child(titulo("Hora de dar uma pausa".into()))
                    .child(corpo(if perfil {
                        "Agora não é horário de usar apps. Se precisar mudar, peça para a mamãe ou o papai.".into()
                    } else {
                        "Este app não está liberado agora.".into()
                    }));
                if perfil {
                    c = c.child(
                        div()
                            .flex()
                            .gap(p.z(12.))
                            .child(self.botao_janela(p, "bl-pais", "Área dos pais".into(), foco == 0).on_click(cx.listener(
                                |m, _: &ClickEvent, _, cx| {
                                    m.abrir_pais(cx);
                                    cx.notify();
                                },
                            )))
                            .child(self.botao_janela(p, "bl-sair", "Sair".into(), foco == 1).on_click(cx.listener(
                                |m, _: &ClickEvent, _, cx| {
                                    m.pedir_pin(AcaoPin::Sair, cx);
                                    cx.notify();
                                },
                            ))),
                    );
                } else {
                    c = c.child(self.botao_janela(p, "bl-fechar", "Fechar".into(), true).on_click(cx.listener(
                        |m, _: &ClickEvent, _, cx| {
                            m.janela = None;
                            cx.notify();
                        },
                    )));
                }
                c
            }
            Janela::TimerEsgotado { pin, erro, foco } => {
                let mut botoes = div().flex().gap(p.z(12.));
                for (i, min) in [15u32, 30, 60].into_iter().enumerate() {
                    botoes = botoes.child(
                        self.botao_janela(p, ["t15", "t30", "t60"][i], format!("+{min}"), foco == i).on_click(cx.listener(
                            move |m, _: &ClickEvent, _, cx| {
                                m.estender_timer(min, cx);
                                cx.notify();
                            },
                        )),
                    );
                }
                self.caixa_janela(p)
                    .child(p.icone("timer", 0xcc0000, 48.))
                    .child(titulo("Acabou o tempo!".into()))
                    .child(corpo("Peça para a mamãe ou o papai para continuar brincando.".into()))
                    .child(self.campo_pin(p, &pin))
                    .child(div().text_color(hsla(0xd32f2f)).text_size(p.f(16.)).child(erro))
                    .child(botoes)
                    .child(self.botao_janela(p, "t-sair", "Sair".into(), foco == 3).on_click(cx.listener(
                        |m, _: &ClickEvent, _, cx| {
                            m.pedir_pin(AcaoPin::Sair, cx);
                            cx.notify();
                        },
                    )))
            }
            Janela::Pin { pin, erro, .. } => self
                .caixa_janela(p)
                .child(p.icone("lock", 0x333333, 44.))
                .child(titulo("Digite o PIN".into()))
                .child(self.campo_pin(p, &pin))
                .child(div().text_color(hsla(0xd32f2f)).text_size(p.f(16.)).child(erro))
                .child(
                    div()
                        .flex()
                        .gap(p.z(12.))
                        .child(self.botao_janela(p, "pin-ok", "OK".into(), true).on_click(cx.listener(
                            |m, _: &ClickEvent, _, cx| {
                                m.conferir_pin(cx);
                                cx.notify();
                            },
                        )))
                        .child(self.botao_janela(p, "pin-cancelar", "Cancelar".into(), false).on_click(cx.listener(
                            |m, _: &ClickEvent, _, cx| {
                                m.fechar_pin();
                                cx.notify();
                            },
                        ))),
                ),
            Janela::Perfis { foco } => {
                let mut linha = div().flex().gap(p.z(16.));
                for (i, (id, nome, avatar)) in self.perfis().into_iter().enumerate() {
                    let ativo = id == self.perfil_id();
                    linha = linha.child(
                        div()
                            .id(("perfil-op", i))
                            .flex()
                            .flex_col()
                            .items_center()
                            .gap(p.z(6.))
                            .w(p.z(150.))
                            .py(p.z(16.))
                            .rounded(p.z(20.))
                            .bg(hsla(if ativo { 0xf0f4ff } else { 0xf6f6f8 }))
                            .border(p.z(4.))
                            .border_color(if foco == i { hsla(p.t.botao) } else { hsla_a(0x00000000) })
                            .cursor_pointer()
                            .child(div().text_size(p.f(52.)).child(if avatar.is_empty() { "👤".into() } else { avatar }))
                            .child(div().text_size(p.f(20.)).font_weight(FontWeight(800.)).child(nome))
                            .on_click(cx.listener(move |m, _: &ClickEvent, _, cx| {
                                m.escolher_perfil(i, cx);
                                cx.notify();
                            })),
                    );
                }
                self.caixa_janela(p)
                    .max_w(p.z(900.))
                    .child(titulo("Quem vai brincar?".into()))
                    .child(linha)
                    .child(self.botao_janela(p, "perfis-fechar", "Fechar".into(), false).on_click(cx.listener(
                        |m, _: &ClickEvent, _, cx| {
                            m.janela = None;
                            cx.notify();
                        },
                    )))
            }
        };
        div()
            .id("fundo-janela")
            .occlude() // cliques não passam para os ícones de trás
            .absolute()
            .inset_0()
            .bg(hsla_a(0x00000066))
            .flex()
            .items_center()
            .justify_center()
            .child(caixa)
            .into_any_element()
    }

    fn campo_pin(&self, p: &Pincel, pin: &str) -> AnyElement {
        let pontos: String = pin.chars().map(|_| '●').collect();
        div()
            .w(p.z(260.))
            .h(p.z(56.))
            .rounded(p.z(14.))
            .border(p.z(3.))
            .border_color(hsla(p.t.botao))
            .bg(hsla(0xffffff))
            .flex()
            .items_center()
            .justify_center()
            .text_size(p.f(26.))
            .text_color(hsla(0x333333))
            .child(if pontos.is_empty() { " ".to_string() } else { pontos })
            .into_any_element()
    }

    fn inicio_el(&self, p: &Pincel, i: &Inicio) -> AnyElement {
        let visual = self.visual(p, &i.emoji, 64., 300., 160.);
        let caixa = div()
            .flex()
            .flex_col()
            .items_center()
            .gap(p.z(12.))
            .px(p.z(48.))
            .py(p.z(40.))
            .rounded(p.z(28.))
            .bg(hsla(0xffffff))
            .shadow(p.sombras(&[tema::Sombra {
                x: 0.,
                y: 14.,
                blur: 46.,
                spread: 0.,
                cor: if i.sucesso { 0x27ae603d } else { 0x00000033 },
            }]))
            .child(visual)
            .child(
                p.fonte(div())
                    .text_size(p.f(26.))
                    .text_color(hsla(p.t.cartao_texto))
                    .child(p.caixa(&i.texto)),
            );
        div()
            .id("fundo-inicio")
            .occlude()
            .absolute()
            .inset_0()
            .bg(hsla_a(0x00000059))
            .flex()
            .items_center()
            .justify_center()
            .child(caixa)
            .into_any_element()
    }

    /// Atrás de um jogo a janela não está visível: só marca para redesenhar
    /// quando voltar para a frente (economiza CPU enquanto a criança joga).
    fn redesenhar(&mut self, cx: &mut Context<Self>) {
        if self.ativa || self.web.is_some() {
            cx.notify();
        } else {
            self.sujo = true;
        }
    }

    pub fn janela_ativada(&mut self, ativa: bool, cx: &mut Context<Self>) {
        if ativa == self.ativa {
            return;
        }
        self.ativa = ativa;
        self.sujo = false;
        if ativa {
            self.atualizar_uso(cx);
            self.atualizar_disp(cx);
            self.atualizar_timer(cx);
        }
        cx.notify();
    }
}

// ---------------------------------------------------------------- comemoração

/// Explosão de 8 estrelas (celebration-runtime.js): saem do centro, crescem e somem.
fn celebracao_el(geracao: u64, largura: f32, altura: f32) -> AnyElement {
    // (x em % da largura, y em % da altura, atraso em ms, escala final)
    const PONTOS: [(f32, f32, f32, f32); 8] = [
        (-0.22, -0.18, 0., 1.05),
        (-0.10, -0.27, 35., 0.8),
        (0.07, -0.25, 70., 1.15),
        (0.21, -0.14, 20., 0.9),
        (0.24, 0.07, 85., 1.05),
        (0.11, 0.21, 45., 0.82),
        (-0.08, 0.23, 95., 1.1),
        (-0.23, 0.09, 55., 0.88),
    ];
    let mut camada = div().absolute().inset_0();
    for (i, (x, y, atraso, escala)) in PONTOS.into_iter().enumerate() {
        let total = 780. + atraso;
        let estrela = div()
            .absolute()
            .text_color(hsla(0xffd447))
            .child("★")
            .with_animation(
                ("estrela", (geracao as usize) * 8 + i),
                gpui::Animation::new(Duration::from_millis(total as u64)),
                move |d, t| {
                    let local = ((t * total - atraso) / 780.).clamp(0., 1.);
                    let k = 1. - (1. - local).powi(3); // ease-out
                    let tam = 42. * (0.45 + (escala - 0.45) * k);
                    let opacidade = if local < 0.18 { local / 0.18 } else { 1. - (local - 0.18) / 0.82 };
                    d.left(px(largura / 2. + x * largura * k - tam / 2.))
                        .top(px(altura / 2. + y * altura * k - tam / 2.))
                        .text_size(px(tam))
                        .opacity(opacidade.clamp(0., 1.))
                },
            );
        camada = camada.child(estrela);
    }
    camada.into_any_element()
}

// ---------------------------------------------------------------- utilidades

/// Repete `f` a cada `intervalo` enquanto o menu existir.
fn ciclo(cx: &mut Context<Menu>, intervalo: Duration, mut f: impl FnMut(&mut Menu, &mut Context<Menu>) + 'static) {
    cx.spawn(async move |this, cx| loop {
        cx.background_executor().timer(intervalo).await;
        if this.update(cx, |m, cx| f(m, cx)).is_err() {
            break;
        }
    })
    .detach();
}

/// Repete `f` até ela devolver false.
fn ciclo_ate(cx: &mut Context<Menu>, intervalo: Duration, mut f: impl FnMut(&mut Menu, &mut Context<Menu>) -> bool + 'static) {
    cx.spawn(async move |this, cx| loop {
        cx.background_executor().timer(intervalo).await;
        match this.update(cx, |m, cx| f(m, cx)) {
            Ok(true) => {}
            _ => break,
        }
    })
    .detach();
}

/// Fundo SVG já convertido em PNG (no cache), se existir; senão devolve o SVG e
/// converte em segundo plano com o rsvg-convert (quando instalado) para a próxima
/// vez. O gpui rasteriza o SVG a cada início (~1 s num Celeron); o PNG abre logo.
fn fundo_rasterizado(svg: &std::path::Path, largura: u32) -> PathBuf {
    use std::sync::Mutex;
    static PEDIDOS: Mutex<Vec<PathBuf>> = Mutex::new(Vec::new());
    let Ok(info) = std::fs::metadata(svg) else { return svg.to_path_buf() };
    let marca = info
        .modified()
        .ok()
        .and_then(|m| m.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let nome = svg.file_stem().and_then(|n| n.to_str()).unwrap_or("fundo");
    let png = estado_dir().join("menu-fundos").join(format!("{nome}-{largura}-{marca}-{}.png", info.len()));
    if png.exists() {
        return png;
    }
    let mut pedidos = PEDIDOS.lock().unwrap();
    if !pedidos.contains(&png) {
        pedidos.push(png.clone());
        let (svg, destino) = (svg.to_path_buf(), png);
        std::thread::spawn(move || {
            let Some(dir) = destino.parent() else { return };
            if std::fs::create_dir_all(dir).is_err() {
                return;
            }
            let tmp = destino.with_extension("tmp");
            let ok = std::process::Command::new("rsvg-convert")
                .args(["--width", &largura.to_string(), "--keep-aspect-ratio", "--format", "png", "--output"])
                .arg(&tmp)
                .arg(&svg)
                .stdin(std::process::Stdio::null())
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .status()
                .is_ok_and(|s| s.success());
            if ok {
                let _ = std::fs::rename(&tmp, &destino);
            } else {
                let _ = std::fs::remove_file(&tmp);
            }
        });
    }
    svg.to_path_buf()
}

/// Lista estática de uma cor de cartão (tema "Cores próprias"). Guarda as que já
/// apareceram para não criar uma nova a cada redesenho.
fn cor_de_cartao(cor: u32) -> &'static [u32] {
    use std::sync::Mutex;
    static CORES: Mutex<Vec<&'static [u32]>> = Mutex::new(Vec::new());
    let mut cores = CORES.lock().unwrap();
    if let Some(c) = cores.iter().find(|c| c[0] == cor) {
        return c;
    }
    let nova: &'static [u32] = Box::leak(Box::new([cor]));
    cores.push(nova);
    nova
}

fn estado_dir() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(std::env::temp_dir)
        .join(".cache")
        .join("cozy-kids-launcher")
}

fn cor_hex(s: &str) -> Option<u32> {
    let h = s.trim().strip_prefix('#')?;
    match h.len() {
        6 => u32::from_str_radix(h, 16).ok(),
        3 => {
            let v = u32::from_str_radix(h, 16).ok()?;
            let (r, g, b) = ((v >> 8) & 0xf, (v >> 4) & 0xf, v & 0xf);
            Some((r * 17) << 16 | (g * 17) << 8 | (b * 17))
        }
        _ => None,
    }
}

/// Hora e minuto locais.
pub fn agora_local() -> (u32, u32) {
    use chrono::Timelike;
    let agora = chrono::Local::now();
    (agora.hour(), agora.minute())
}

fn ler_bateria() -> Option<(u32, bool)> {
    let dir = std::fs::read_dir("/sys/class/power_supply").ok()?;
    for e in dir.flatten() {
        let p = e.path();
        let tipo = std::fs::read_to_string(p.join("type")).unwrap_or_default();
        if tipo.trim() != "Battery" {
            continue;
        }
        let pct: u32 = std::fs::read_to_string(p.join("capacity")).ok()?.trim().parse().ok()?;
        let status = std::fs::read_to_string(p.join("status")).unwrap_or_default();
        return Some((pct.min(100), status.trim() == "Charging"));
    }
    None
}

/// Fecha o navegador aberto pelo menu (TERM no Linux, para ele salvar o perfil).
fn fechar_processo(filho: Option<&mut Child>, pid: u32) {
    #[cfg(unix)]
    {
        let _ = filho;
        let _ = std::process::Command::new("kill").args(["-TERM", &pid.to_string()]).status();
    }
    #[cfg(not(unix))]
    {
        let _ = pid;
        if let Some(c) = filho {
            let _ = c.kill();
        }
    }
}

/// Traz a janela do menu para a frente (depois que o navegador fecha).
#[cfg(windows)]
pub(crate) fn trazer_para_frente() {
    // O Windows não deixa um processo de fundo roubar o foco: anexar a entrada à
    // janela que está na frente libera o SetForegroundWindow.
    use windows_sys::Win32::Foundation::{HWND, LPARAM};
    use windows_sys::Win32::System::Threading::{AttachThreadInput, GetCurrentThreadId};
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        BringWindowToTop, EnumWindows, GetForegroundWindow, GetWindowThreadProcessId, IsWindowVisible,
        SetForegroundWindow, ShowWindow, SW_SHOW,
    };
    unsafe extern "system" fn achar(h: HWND, alvo: LPARAM) -> i32 {
        unsafe {
            let mut pid = 0u32;
            GetWindowThreadProcessId(h, &mut pid);
            if pid == std::process::id() && IsWindowVisible(h) != 0 {
                *(alvo as *mut HWND) = h;
                return 0;
            }
        }
        1
    }
    unsafe {
        let mut h: HWND = std::ptr::null_mut();
        EnumWindows(Some(achar), &mut h as *mut HWND as LPARAM);
        if h.is_null() || GetForegroundWindow() == h {
            return;
        }
        let frente = GetWindowThreadProcessId(GetForegroundWindow(), std::ptr::null_mut());
        let eu = GetCurrentThreadId();
        let ligou = frente != 0 && frente != eu && AttachThreadInput(eu, frente, 1) != 0;
        ShowWindow(h, SW_SHOW);
        BringWindowToTop(h);
        SetForegroundWindow(h);
        if ligou {
            AttachThreadInput(eu, frente, 0);
        }
    }
}

#[cfg(not(any(unix, windows)))]
pub(crate) fn trazer_para_frente() {}

#[cfg(unix)]
pub(crate) fn trazer_para_frente() {
    let pid = std::process::id().to_string();
    std::thread::spawn(move || {
        let _ = std::process::Command::new("xdotool")
            .args(["search", "--pid", &pid, "windowactivate"])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status();
    });
}

#[allow(dead_code)]
fn _usa(_: &App) {}
