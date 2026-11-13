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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/v1/ping") return new Response("Benikids\n", { status: 404 });
    if (request.method !== "POST") return new Response(null, { status: 405 });
    if (Number(request.headers.get("content-length") || 0) > 4096) return new Response(null, { status: 413 });

    let corpo;
    try {
      corpo = await request.json();
    } catch {
      return new Response(null, { status: 400 });
    }
    if (!corpo || typeof corpo.id !== "string" || !ID.test(corpo.id)) return new Response(null, { status: 400 });

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

    return new Response(null, { status: 204 });
  },
};
