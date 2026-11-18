// Telemetria anônima do Benikids (veja docs/PRIVACY.md).
// POST /v1/ping com um JSON pequeno; grava uma linha por instalação no D1.
// Não grava IP nem cabeçalhos; campos fora da lista são ignorados.

const CAMPOS = {
  versao: 32, plataforma: 16, sistema: 80, cpu: 120, gpu: 160,
  menu: 16, tela: 16, idioma: 16,
};
const ID = /^[0-9a-f]{32}$/;

function texto(valor, max) {
  if (typeof valor !== "string") return null;
  const limpo = valor.replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, max);
  return limpo || null;
}

const HEX32 = /^[0-9a-f]{32}$/;
const DIA = /^\d{4}-\d{2}-\d{2}$/;

async function json(request) {
  if (Number(request.headers.get("content-length") || 0) > 65536) return null;
  try {
    return await request.json();
  } catch {
    return null;
  }
}

async function ping(corpo, env) {
  if (!corpo || typeof corpo.id !== "string" || !ID.test(corpo.id)) return 400;
  const v = {};
  for (const [campo, max] of Object.entries(CAMPOS)) v[campo] = texto(corpo[campo], max);
  const ram = Number.isFinite(corpo.ram_gb) ? Math.max(0, Math.min(4096, Math.round(corpo.ram_gb))) : null;
  const hoje = new Date().toISOString().slice(0, 10);
  await env.DB.prepare(
    `INSERT INTO instalacoes (id, primeira, ultima, envios, versao, plataforma, sistema, cpu, ram_gb, gpu, menu, tela, idioma)
     VALUES (?1, ?2, ?2, 1, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)
     ON CONFLICT(id) DO UPDATE SET
       ultima = ?2, envios = envios + 1, versao = ?3, plataforma = ?4, sistema = ?5, cpu = ?6,
       ram_gb = ?7, gpu = ?8, menu = ?9, tela = ?10, idioma = ?11`
  ).bind(corpo.id, hoje, v.versao, v.plataforma, v.sistema, v.cpu, ram, v.gpu, v.menu, v.tela, v.idioma).run();
  return 204;
}

function minutos(valor) {
  return Number.isFinite(valor) ? Math.max(0, Math.min(1440, Math.round(valor))) : 0;
}

async function uso(corpo, env) {
  if (!corpo || !Array.isArray(corpo.dias) || corpo.dias.length > 400) return 400;
  const comandos = [];
  for (const d of corpo.dias) {
    if (!d || !HEX32.test(d.crianca || "") || !DIA.test(d.dia || "")) continue;
    const categorias = {};
    for (const [k, m] of Object.entries(d.categorias || {}).slice(0, 20)) categorias[texto(k, 30) || "?"] = minutos(m);
    comandos.push(env.DB.prepare(
      `INSERT OR REPLACE INTO uso (crianca, dia, faixa, genero, minutos, categorias) VALUES (?1, ?2, ?3, ?4, ?5, ?6)`
    ).bind(d.crianca, d.dia, texto(d.faixa, 8), ["menino", "menina"].includes(d.genero) ? d.genero : null,
           minutos(d.minutos), JSON.stringify(categorias)));
    for (const a of (Array.isArray(d.apps) ? d.apps : []).slice(0, 100)) {
      const app = texto(a && a.app, 80);
      if (!app) continue;
      comandos.push(env.DB.prepare(
        `INSERT OR REPLACE INTO uso_apps (crianca, dia, app, nome, categoria, minutos) VALUES (?1, ?2, ?3, ?4, ?5, ?6)`
      ).bind(d.crianca, d.dia, app, texto(a.nome, 60), texto(a.categoria, 30), minutos(a.minutos)));
    }
  }
  if (comandos.length) await env.DB.batch(comandos);
  return 204;
}

async function problema(corpo, env) {
  if (!corpo || typeof corpo.id !== "string" || !ID.test(corpo.id)) return 400;
  const hoje = new Date().toISOString().slice(0, 10);
  // no máximo 50 problemas por instalação por dia
  const conta = await env.DB.prepare(
    `SELECT COUNT(*) AS n FROM problemas WHERE id = ?1 AND recebido = ?2`
  ).bind(corpo.id, hoje).first();
  if (conta && conta.n >= 50) return 429;
  await env.DB.prepare(
    `INSERT INTO problemas (recebido, id, versao, plataforma, sistema, etapa, assinatura, detalhe)
     VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)`
  ).bind(hoje, corpo.id, texto(corpo.versao, 32), texto(corpo.plataforma, 16), texto(corpo.sistema, 80),
         texto(corpo.etapa, 60), texto(corpo.assinatura, 120),
         typeof corpo.detalhe === "string" ? corpo.detalhe.slice(-4000) : null).run();
  return 204;
}

async function apagar(corpo, env) {
  if (!corpo || typeof corpo.id !== "string" || !ID.test(corpo.id)) return 400;
  const criancas = (Array.isArray(corpo.criancas) ? corpo.criancas : []).filter((c) => HEX32.test(c)).slice(0, 20);
  const comandos = [
    env.DB.prepare(`DELETE FROM instalacoes WHERE id = ?1`).bind(corpo.id),
    env.DB.prepare(`DELETE FROM problemas WHERE id = ?1`).bind(corpo.id),
  ];
  for (const c of criancas) {
    comandos.push(env.DB.prepare(`DELETE FROM uso WHERE crianca = ?1`).bind(c));
    comandos.push(env.DB.prepare(`DELETE FROM uso_apps WHERE crianca = ?1`).bind(c));
  }
  await env.DB.batch(comandos);
  return 204;
}

// ---------- Problemas → Issues no GitHub ----------
// Uma vez por dia: cada assinatura nova vira uma Issue (no máximo NOVAS_POR_DIA); uma
// assinatura que já tem Issue ganha um comentário com as ocorrências do dia (e é reaberta,
// se estava fechada). O repositório é público, então a Issue nunca leva o detalhe (fim de log) nem o id da instalação.
const NOVAS_POR_DIA = 5;
const REPO = "jaison/benikids";

function chave(assinatura) {
  return String(assinatura || "").replace(/[^A-Za-z0-9_.:-]+/g, "_").slice(0, 90);
}

function lista(valores) {
  const itens = [...new Set(String(valores || "").split("\u001f").map((v) => chave(v).replace(/_/g, " ").trim()).filter(Boolean))];
  return itens.length ? itens.slice(0, 8).map((v) => "`" + v + "`").join(", ") : "—";
}

async function github(env, metodo, caminho, corpo) {
  const resposta = await fetch(`${env.GITHUB_API || "https://api.github.com"}/repos/${env.GITHUB_REPO || REPO}${caminho}`, {
    method: metodo,
    headers: {
      authorization: `Bearer ${env.GITHUB_TOKEN}`,
      accept: "application/vnd.github+json",
      "user-agent": "benikids-telemetria",
      "content-type": "application/json",
    },
    body: JSON.stringify(corpo),
  });
  if (!resposta.ok) throw new Error(`GitHub ${metodo} ${caminho}: ${resposta.status}`);
  return resposta.json();
}

export async function issues(env, chamar = github) {
  if (!env.GITHUB_TOKEN) return { novas: 0, comentadas: 0 };
  const estado = await env.DB.prepare(`SELECT ate_n FROM issues_estado WHERE um = 1`).first();
  const desde = estado ? estado.ate_n : 0;
  const { results: brutas } = await env.DB.prepare(
    `SELECT p.assinatura AS assinatura, MIN(p.etapa) AS etapa, COUNT(*) AS vezes,
            COUNT(DISTINCT p.id) AS instalacoes, MAX(p.n) AS ultimo, MIN(p.recebido) AS desde,
            GROUP_CONCAT(DISTINCT p.versao) AS versoes, GROUP_CONCAT(DISTINCT p.plataforma) AS plataformas,
            GROUP_CONCAT(DISTINCT p.sistema) AS sistemas
       FROM problemas p
      WHERE p.assinatura IS NOT NULL
        AND p.n > ?1
      GROUP BY p.assinatura
      ORDER BY vezes DESC`
  ).bind(desde).all();
  // assinaturas que ficam iguais depois de limpas contam juntas
  const separar = (v) => String(v || "").split(",").join("\u001f");
  const porChave = new Map();
  let ate = desde;
  for (const l of brutas || []) {
    ate = Math.max(ate, l.ultimo);
    const k = chave(l.assinatura);
    if (!k) continue;
    const g = porChave.get(k) || { k, etapa: l.etapa, vezes: 0, instalacoes: 0, desde: l.desde, versoes: [], plataformas: [], sistemas: [] };
    g.vezes += l.vezes;
    g.instalacoes += l.instalacoes;
    if (l.desde < g.desde) g.desde = l.desde;
    g.versoes.push(separar(l.versoes));
    g.plataformas.push(separar(l.plataformas));
    g.sistemas.push(separar(l.sistemas));
    porChave.set(k, g);
  }
  const linhas = [...porChave.values()].sort((a, b) => b.vezes - a.vezes).slice(0, 30);
  let novas = 0, comentadas = 0;
  for (const l of linhas) {
    const k = l.k;
    const resumo =
      `- **Ocorrências:** ${l.vezes} em ${l.instalacoes} instalação(ões), desde ${l.desde}\n` +
      `- **Versões:** ${lista(l.versoes.join("\u001f"))}\n` +
      `- **Plataformas:** ${lista(l.plataformas.join("\u001f"))}\n` +
      `- **Sistemas:** ${lista(l.sistemas.join("\u001f"))}`;
    const existente = await env.DB.prepare(`SELECT numero FROM issues WHERE chave = ?1`).bind(k).first();
    if (!existente && novas >= NOVAS_POR_DIA) {
      l.adiada = true;
      continue;
    }
    try {
      if (existente) {
        await chamar(env, "POST", `/issues/${existente.numero}/comments`, { body: `Novas ocorrências:\n\n${resumo}` });
        // Uma Issue fechada que volta a acontecer é reaberta: só o comentário passava
        // despercebido (ex.: fechada por ter sido algo de um dia, e o problema volta).
        await chamar(env, "PATCH", `/issues/${existente.numero}`, { state: "open" });
        comentadas++;
        continue;
      }
      const issue = await chamar(env, "POST", "/issues", {
        title: `Problema relatado: ${k}`,
        labels: ["telemetria"],
        body:
          `Aberta pela telemetria do Benikids (relatórios de problema, com o consentimento dos pais).\n\n` +
          `- **Assinatura:** \`${k}\`\n- **Etapa:** \`${chave(l.etapa) || "—"}\`\n${resumo}\n\n` +
          `O fim do log fica só no banco da telemetria (tabela \`problemas\`, assinatura acima), por privacidade.`,
      });
      await env.DB.prepare(`INSERT INTO issues (chave, numero) VALUES (?1, ?2)`).bind(k, issue.number).run();
      novas++;
    } catch (erro) {
      console.log("issue", k, erro && erro.message); // uma falha não segura as outras
    }
  }
  // As que passaram do limite de novas por dia (proteção contra envios falsos) ganham Issue
  // quando voltarem a acontecer; continuam no banco de qualquer jeito.
  await env.DB.prepare(`INSERT INTO issues_estado (um, ate_n) VALUES (1, ?1) ON CONFLICT(um) DO UPDATE SET ate_n = ?1`).bind(ate).run();
  return { novas, comentadas, adiadas: linhas.filter((l) => l.adiada).length };
}

const ROTAS = { "/v1/ping": ping, "/v1/uso": uso, "/v1/problema": problema, "/v1/apagar": apagar };

export default {
  async fetch(request, env) {
    const rota = ROTAS[new URL(request.url).pathname];
    if (!rota) return new Response("Benikids\n", { status: 404 });
    if (request.method !== "POST") return new Response(null, { status: 405 });
    const corpo = await json(request);
    if (corpo === null) return new Response(null, { status: 400 });
    return new Response(null, { status: await rota(corpo, env) });
  },

  // limpeza diária e Issues dos problemas novos
  async scheduled(_evento, env) {
    try {
      await issues(env);
    } catch (erro) {
      console.log("issues:", erro && erro.message);
    }
    await env.DB.batch([
      env.DB.prepare(`DELETE FROM uso WHERE dia < date('now', '-12 months')`),
      env.DB.prepare(`DELETE FROM uso_apps WHERE dia < date('now', '-12 months')`),
      env.DB.prepare(`DELETE FROM problemas WHERE recebido < date('now', '-6 months')`),
    ]);
  },
};
