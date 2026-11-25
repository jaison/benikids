import assert from "node:assert/strict";
import test from "node:test";

import { escolherParaAbrir, issues } from "../src/index.js";

function banco(opcoes = {}) {
  const problemas = [];
  const issuesMap = new Map(opcoes.issues || []);
  const fila = new Map();
  let ate = opcoes.ate || 0;
  let insertsQueFalham = opcoes.insertsQueFalham || 0;
  const sqls = [];

  function agrupar(desde) {
    const grupos = new Map();
    for (const p of problemas) {
      if (p.assinatura == null) continue;
      const entra = p.n > desde || fila.has(p.assinatura) || !issuesMap.has(p.assinatura);
      if (!entra) continue;
      const g = grupos.get(p.assinatura) || {
        assinatura: p.assinatura, etapa: p.etapa, vezes: 0, ids: new Set(), ultimo: 0,
        desde: p.recebido, versoes: new Set(), plataformas: new Set(), sistemas: new Set(),
      };
      g.vezes += 1;
      g.ids.add(p.id);
      g.ultimo = Math.max(g.ultimo, p.n);
      if (p.recebido < g.desde) g.desde = p.recebido;
      if (p.versao) g.versoes.add(p.versao);
      if (p.plataforma) g.plataformas.add(p.plataforma);
      if (p.sistema) g.sistemas.add(p.sistema);
      if (!g.etapa) g.etapa = p.etapa;
      grupos.set(p.assinatura, g);
    }
    return [...grupos.values()]
      .map((g) => ({
        assinatura: g.assinatura,
        etapa: g.etapa,
        vezes: g.vezes,
        instalacoes: g.ids.size,
        ultimo: g.ultimo,
        desde: g.desde,
        versoes: [...g.versoes].join(","),
        plataformas: [...g.plataformas].join(","),
        sistemas: [...g.sistemas].join(","),
      }))
      .sort((a, b) => b.vezes - a.vezes);
  }

  function exec(sql, args, modo) {
    sqls.push(sql);
    if (sql.startsWith("CREATE TABLE")) return modo === "all" ? [] : null;
    if (sql.includes("FROM problemas")) return agrupar(args[0]);
    if (sql.startsWith("DELETE FROM issues_fila")) {
      fila.clear();
      return null;
    }
    if (sql.startsWith("INSERT INTO issues_fila")) {
      fila.set(args[0], args[1]);
      return null;
    }
    if (sql.startsWith("INSERT INTO issues_estado")) {
      ate = args[0];
      return null;
    }
    if (sql.startsWith("INSERT INTO issues (")) {
      if (insertsQueFalham > 0) {
        insertsQueFalham -= 1;
        throw new Error("d1");
      }
      issuesMap.set(args[0], args[1]);
      return null;
    }
    if (sql.includes("FROM issues_fila")) return [...fila.entries()].map(([assinatura, numero]) => ({ assinatura, numero }));
    if (sql.includes("FROM issues_estado")) return ate ? { ate_n: ate } : null;
    if (sql.includes("FROM issues")) return [...issuesMap.entries()].map(([chave, numero]) => ({ chave, numero }));
    throw new Error("SQL inesperado: " + sql);
  }

  function stmt(sql, args) {
    return {
      first: async () => {
        const r = exec(sql, args, "first");
        return Array.isArray(r) ? r[0] || null : r;
      },
      all: async () => ({ results: exec(sql, args, "all") || [] }),
      run: async () => exec(sql, args, "run"),
    };
  }

  return {
    problemas,
    fila,
    issues: issuesMap,
    sqls,
    get ate() {
      return ate;
    },
    prepare(sql) {
      return { ...stmt(sql, []), bind: (...args) => stmt(sql, args) };
    },
    async batch(comandos) {
      for (const c of comandos) await c.run();
    },
  };
}

function ocorrencia(assinatura, n, vezes = 1) {
  const linhas = [];
  for (let i = 0; i < vezes; i++) {
    linhas.push({
      n, assinatura, etapa: "instalar", id: "ab".repeat(16), recebido: "2026-11-01",
      versao: "1.0.8", plataforma: "linux", sistema: "Linux Mint 22",
    });
  }
  return linhas;
}

function githubOk(chamadas, falhar) {
  let numero = 100;
  return async (_env, metodo, caminho) => {
    chamadas.push({ metodo, caminho });
    if (falhar && falhar(metodo, caminho, chamadas.length)) throw new Error(`GitHub ${metodo} ${caminho}: 500`);
    if (metodo === "POST" && caminho === "/issues") return { number: ++numero };
    return {};
  };
}

test("a vaga da fila fica com a espera mais antiga quando há assinatura nova", () => {
  const chaves = escolherParaAbrir([
    { k: "nova1", vezes: 100, ultimo: 10, esperando: false },
    { k: "nova2", vezes: 90, ultimo: 11, esperando: false },
    { k: "nova3", vezes: 80, ultimo: 12, esperando: false },
    { k: "nova4", vezes: 70, ultimo: 13, esperando: false },
    { k: "nova5", vezes: 60, ultimo: 14, esperando: false },
    { k: "rara", vezes: 1, ultimo: 1, esperando: true },
    { k: "sobra", vezes: 50, ultimo: 20, esperando: true },
  ]).map((g) => g.k);
  assert.deepEqual(chaves, ["nova1", "nova2", "nova3", "nova4", "rara"]);
});

test("sem espera abre as que mais aconteceram", () => {
  const chaves = escolherParaAbrir([
    { k: "a", vezes: 1, esperando: false },
    { k: "b", vezes: 9, esperando: false },
    { k: "c", vezes: 3, esperando: false },
  ], 2).map((g) => g.k);
  assert.deepEqual(chaves, ["b", "c"]);
});

test("o cursor não passa da assinatura que ficou acima do teto", async () => {
  const db = banco();
  db.problemas.push(...ocorrencia("a", 1, 6), ...ocorrencia("b", 2, 5), ...ocorrencia("c", 3, 4));
  db.problemas.push(...ocorrencia("d", 4, 3), ...ocorrencia("e", 5, 2), ...ocorrencia("f", 1000, 1));
  const chamadas = [];
  const r1 = await issues({ GITHUB_TOKEN: "t", DB: db }, githubOk(chamadas));
  assert.equal(r1.novas, 5);
  assert.equal(r1.adiadas, 1);
  assert.equal(db.ate, 5);
  assert.equal(db.fila.has("f"), true);
  assert.equal(db.issues.has("f"), false);

  const r2 = await issues({ GITHUB_TOKEN: "t", DB: db }, githubOk(chamadas));
  assert.equal(r2.novas, 1);
  assert.equal(db.issues.has("f"), true);
  assert.equal(db.fila.size, 0);
  assert.equal(db.ate, 1000);
});

test("no dia seguinte a espera antiga ganha vaga na frente de várias novas", async () => {
  const db = banco();
  for (let i = 1; i <= 5; i++) db.problemas.push(...ocorrencia("c" + i, i, 10 - i));
  db.problemas.push(...ocorrencia("instalar_app:kbruch:x", 1000, 1));
  await issues({ GITHUB_TOKEN: "t", DB: db }, githubOk([]));
  assert.equal(db.issues.has("instalar_app:kbruch:x"), false);
  assert.equal(db.ate < 1000, true);
  db.problemas.push(...ocorrencia("n1", 10, 50), ...ocorrencia("n2", 11, 40), ...ocorrencia("n3", 12, 30));
  db.problemas.push(...ocorrencia("n4", 13, 20), ...ocorrencia("n5", 14, 15));
  await issues({ GITHUB_TOKEN: "t", DB: db }, githubOk([]));
  assert.equal(db.issues.has("instalar_app:kbruch:x"), true);
  const abertasNovas = ["n1", "n2", "n3", "n4", "n5"].filter((k) => db.issues.has(k));
  assert.equal(abertasNovas.length, 4);
});

test("assinatura que o cursor já passou e não tem Issue ainda é aberta", async () => {
  const db = banco({ ate: 50 });
  db.problemas.push(...ocorrencia("instalar_app:minuet:y", 10, 1));
  const r = await issues({ GITHUB_TOKEN: "t", DB: db }, githubOk([]));
  assert.equal(r.novas, 1);
  assert.equal(db.issues.has("instalar_app:minuet:y"), true);
  assert.equal(db.ate, 50);
});

test("quem já tem Issue só ganha comentário e não gasta a cota", async () => {
  const db = banco();
  db.issues.set("app.travou:tuxpaint", 7);
  db.problemas.push(...ocorrencia("app.travou:tuxpaint", 3, 2));
  for (const nome of ["a", "b", "c", "d", "e"]) db.problemas.push(...ocorrencia(nome, 4, 1));
  const chamadas = [];
  const r = await issues({ GITHUB_TOKEN: "t", DB: db }, githubOk(chamadas));
  assert.equal(r.novas, 5);
  assert.equal(r.comentadas, 1);
  assert.equal(chamadas.some((c) => c.metodo === "POST" && c.caminho === "/issues/7/comments"), true);
  assert.equal(chamadas.some((c) => c.metodo === "PATCH" && c.caminho === "/issues/7"), true);
  assert.equal(db.ate, 4);
});

test("falha do GitHub não avança o cursor e a próxima rodada tenta de novo", async () => {
  const db = banco();
  db.problemas.push(...ocorrencia("instalar_app:kbruch:x", 8, 1));
  const chamadas = [];
  let falhas = 1;
  const r1 = await issues({ GITHUB_TOKEN: "t", DB: db }, githubOk(chamadas, () => falhas-- > 0));
  assert.equal(r1.novas, 0);
  assert.equal(db.ate, 0);
  assert.equal(db.fila.has("instalar_app:kbruch:x"), true);
  const r2 = await issues({ GITHUB_TOKEN: "t", DB: db }, githubOk(chamadas));
  assert.equal(r2.novas, 1);
  assert.equal(db.ate, 8);
  assert.equal(db.issues.has("instalar_app:kbruch:x"), true);
});

test("se o banco não gravar o número, a rodada seguinte não abre outra Issue", async () => {
  const db = banco({ insertsQueFalham: 1 });
  db.problemas.push(...ocorrencia("instalar_app:kbruch:x", 4, 1));
  const chamadas = [];
  const chamar = githubOk(chamadas);
  await issues({ GITHUB_TOKEN: "t", DB: db }, chamar);
  assert.equal(db.issues.size, 0);
  assert.equal(db.fila.get("instalar_app:kbruch:x") > 0, true);
  await issues({ GITHUB_TOKEN: "t", DB: db }, chamar);
  assert.equal(db.issues.size, 1);
  assert.equal(chamadas.filter((c) => c.caminho === "/issues").length, 1);
});

test("comentário que falha fica na fila mesmo com o cursor à frente", async () => {
  const db = banco();
  db.issues.set("app.travou:tuxpaint", 7);
  db.problemas.push(...ocorrencia("app.travou:tuxpaint", 3, 1), ...ocorrencia("outra", 9, 1));
  const chamadas = [];
  await issues({ GITHUB_TOKEN: "t", DB: db }, githubOk(chamadas, (metodo, caminho) => caminho.includes("/comments")));
  assert.equal(db.fila.has("app.travou:tuxpaint"), true);
  assert.ok(db.ate < 3 || db.fila.has("app.travou:tuxpaint"));
  const antes = chamadas.length;
  await issues({ GITHUB_TOKEN: "t", DB: db }, githubOk(chamadas));
  assert.equal(chamadas.slice(antes).some((c) => c.caminho === "/issues/7/comments"), true);
  assert.equal(db.fila.has("app.travou:tuxpaint"), false);
});

test("sem token o cursor não anda", async () => {
  const db = banco({ ate: 4 });
  db.prepare = () => {
    throw new Error("não devia consultar o banco");
  };
  const r = await issues({ GITHUB_TOKEN: "", DB: db }, githubOk([]));
  assert.deepEqual(r, { novas: 0, comentadas: 0 });
});

test("muitas assinaturas novas acabam todas com Issue", async () => {
  const db = banco();
  for (let i = 0; i < 12; i++) db.problemas.push(...ocorrencia("s" + i, i + 1, 12 - i));
  for (let i = 0; i < 4; i++) await issues({ GITHUB_TOKEN: "t", DB: db }, githubOk([]));
  assert.equal(db.issues.size, 12);
  assert.equal(db.fila.size, 0);
  assert.equal(db.ate, 12);
});
