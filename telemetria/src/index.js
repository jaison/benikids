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

  // limpeza diária
  async scheduled(_evento, env) {
    await env.DB.batch([
      env.DB.prepare(`DELETE FROM uso WHERE dia < date('now', '-12 months')`),
      env.DB.prepare(`DELETE FROM uso_apps WHERE dia < date('now', '-12 months')`),
      env.DB.prepare(`DELETE FROM problemas WHERE recebido < date('now', '-6 months')`),
    ]);
  },
};
