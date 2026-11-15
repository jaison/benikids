// Integração com o menu nativo (beni-menu). Só age quando a aba foi aberta por ele
// (cliente.html marca sessionStorage.beniCliente):
//  - /index.html?pais=1 → abre direto a área dos pais (com o PIN, se houver); ao
//    sair dela (Voltar, Esc ou PIN cancelado) avisa o servidor e o menu nativo
//    fecha o navegador;
//  - /index.html sem ?pais=1 (ex.: "voltar" de um site embutido ou da biblioteca
//    de mídia) → avisa na hora, porque a tela da criança é a do menu nativo.
// Os avisos de tempo ("Faltam 5 minutos", "Acabou o tempo!") são do menu nativo:
// nesta aba eles ficariam por cima do PIN e da área dos pais (z-index maior),
// com o tema da criança, e os pais não conseguiriam entrar.
(function () {
  'use strict';
  let doCliente = false;
  try { doCliente = sessionStorage.getItem('beniCliente') === '1'; } catch (e) {}
  if (!doCliente) return;
  document.documentElement.classList.add('beni-cliente');
  let avisou = false;
  const pais = new URLSearchParams(location.search).get('pais') === '1';
  let reabrir = null;
  function voltarAoMenu() {
    if (avisou) return;
    avisou = true;
    document.body.style.visibility = 'hidden';
    fetch('/api/cliente/voltar', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      .catch(function () {});
    // O menu nativo fecha o navegador em menos de 1 s. Se a janela continuar aberta
    // (aviso perdido, navegador que não fechou), a tela não pode ficar só com o
    // fundo: mostra de novo o PIN para os pais tentarem outra vez.
    if (pais) {
      clearTimeout(reabrir);
      reabrir = setTimeout(function () {
        avisou = false;
        document.body.style.visibility = '';
        abrirPais();
      }, 5000);
    }
  }
  if (!pais) { voltarAoMenu(); return; }

  // Some com a tela da criança desta aba: só a área dos pais interessa aqui.
  const estilo = document.createElement('style');
  estilo.textContent = 'html.beni-cliente #kids, html.beni-cliente .cornerbar, html.beni-cliente #clockBadge,'
    + ' html.beni-cliente #batteryBadge, html.beni-cliente #timerBadge, html.beni-cliente .nav { visibility:hidden !important; }'
    + ' html.beni-cliente #timerBlock, html.beni-cliente #timerWarning, html.beni-cliente #usageMessage { display:none !important; }';
  document.head.appendChild(estilo);

  const fecharAdminOriginal = window.closeAdmin;
  window.closeAdmin = function () { voltarAoMenu(); };
  const cancelarPinOriginal = window.cancelPin;
  window.cancelPin = function () {
    const adminAberto = !document.getElementById('admin').classList.contains('hidden');
    if (typeof cancelarPinOriginal === 'function') cancelarPinOriginal();
    if (!adminAberto) voltarAoMenu();
  };
  // Esc na tela (sem PIN aberto e fora da área dos pais) também volta.
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    const adminAberto = !document.getElementById('admin').classList.contains('hidden');
    const pinAberto = !document.getElementById('pin').classList.contains('hidden');
    if (!adminAberto && !pinAberto) { e.preventDefault(); e.stopImmediatePropagation(); voltarAoMenu(); }
  }, true);

  // ---------- A aba nunca fica só com o fundo ----------
  // No Windows, ao reabrir a área dos pais logo depois de voltar, a página às vezes
  // ficava só com o fundo (ou com o PIN no tema da criança) até o F5. Um arquivo da
  // página que não carrega (CSS ou JS) basta: sem o marca.css o PIN sai com o tema;
  // sem um script, o desenho da tela quebra e o bootstrap apagava o cfg. O aviso de
  // erro com "tentar de novo" fica na tela da criança, que esta aba esconde.
  // Um vigia, a cada segundo:
  //  - arquivo da página que não carregou: recarrega (até 3 vezes por aba);
  //  - sem configuração: tenta de novo; 6 s depois da PRIMEIRA falha (ou 3 falhas
  //    seguidas) recarrega a página, como o F5; depois de 2 s mostra "Abrindo…";
  //  - PIN aceito sem configuração: abre o painel quando ela voltar;
  //  - com configuração e nada na tela: pede o PIN de novo.
  // Cada recuperação vira o evento "cliente.recuperado" no diagnóstico, com o erro.
  const MAX_RECARGAS = 3;
  let carregou = false;      // o carregamento completo terminou (com ou sem erro)
  let carregando = false;
  let recarregando = false;
  let semCfgDesde = Date.now();
  let falhasSeguidas = 0;
  let entrarDepois = false;
  let vazioDesde = 0;
  const temCfg = function () { return typeof cfg !== 'undefined' && !!cfg; };
  const ultimoErro = function () {
    return typeof launcherLoadError !== 'undefined' ? launcherLoadError : null;
  };
  // Mensagem e começo da pilha do erro, sem textos entre aspas (podem ter dados
  // da configuração, como nomes) nem o endereço do servidor.
  function textoDoErro(e) {
    if (!e) return '';
    const msg = e && e.message ? e.message : String(e);
    const pilha = e && e.stack ? String(e.stack).split('\n').slice(1, 4).join(' ') : '';
    return (msg + (pilha ? ' @ ' + pilha : ''))
      .replace(/"[^"]*"|'[^']*'|`[^`]*`/g, '"…"')
      .replace(/https?:\/\/[^/\s)]+/g, '')
      .replace(/\s+/g, ' ')
      .slice(0, 300);
  }
  const registros = {};
  function registrar(etapa, erro) {
    registros[etapa] = (registros[etapa] || 0) + 1;
    if (registros[etapa] > 5) return; // servidor com problema: não enche o diagnóstico
    const dados = { etapa: etapa };
    if (erro) dados.erro = textoDoErro(erro);
    fetch('/api/cliente/evento', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(dados) }).catch(function () {});
  }
  function recargasFeitas() {
    try { return Number(sessionStorage.getItem('beniRecargas')) || 0; } catch (e) { return MAX_RECARGAS; }
  }
  // Recarrega a página (o mesmo que o F5), no máximo MAX_RECARGAS vezes por aba.
  function recarregar(etapa, erro) {
    if (recarregando) return true;
    const n = recargasFeitas();
    if (n >= MAX_RECARGAS) return false;
    try { sessionStorage.setItem('beniRecargas', String(n + 1)); } catch (e) { return false; }
    recarregando = true;
    registrar(etapa, erro);
    setTimeout(function () { location.reload(); }, 200);
    return true;
  }
  function aberto(id) {
    const el = document.getElementById(id);
    return !!el && !el.classList.contains('hidden');
  }
  function algoNaTela() {
    const els = document.querySelectorAll('#admin, .pinoverlay, .install-overlay, #availabilityBlock');
    for (let i = 0; i < els.length; i++) {
      if (!els[i].classList.contains('hidden') && els[i].getClientRects().length > 0) return true;
    }
    return false;
  }

  // PIN aceito enquanto a configuração ainda não voltou: o painel abre depois.
  const entrarOriginal = window.enterAdmin;
  window.enterAdmin = function () {
    if (!temCfg()) { entrarDepois = true; return; }
    entrarDepois = false;
    try {
      const r = entrarOriginal.apply(this, arguments);
      try { sessionStorage.removeItem('beniRecargas'); } catch (e) {}
      return r;
    } catch (e) { registrar('painel', e); }
  };

  // Com PIN, pede o PIN assim que a configuração chega, sem esperar o resto do
  // carregamento (apps, recomendações, cronômetro). Sem PIN, a área dos pais abre
  // direto e espera tudo carregar.
  function abrirPais() {
    if (avisou || recarregando || !temCfg()) return;
    if (!cfg.pinConfigured && !carregou) return;
    if (aberto('admin') || aberto('pin')) return;
    if (entrarDepois) { window.enterAdmin(); return; } // o PIN já foi aceito
    if (typeof openAdmin === 'function') openAdmin();
  }
  // Uma carga por vez (bootstrapLauncher também devolve a carga em andamento).
  function carregar() {
    if (carregando || recarregando || typeof bootstrapLauncher !== 'function') return;
    carregando = true;
    const fim = function () {
      carregando = false;
      carregou = true;
      const erro = ultimoErro();
      if (!temCfg()) {
        falhasSeguidas++;
        registrar('config', erro);
      } else if (erro && erro.etapa === 'render') {
        registrar('render', erro);
      }
      abrirPais();
    };
    Promise.resolve(bootstrapLauncher()).then(fim, fim);
  }

  // Mensagem enquanto a configuração não chega (em vez da tela vazia).
  const espera = document.createElement('div');
  espera.className = 'cliente-espera';
  espera.setAttribute('role', 'status');
  espera.hidden = true;
  espera.innerHTML = '<p>Abrindo a área dos pais…</p><div class="cliente-espera-botoes">'
    + '<button type="button" class="smallbtn save">Tentar de novo</button>'
    + '<button type="button" class="smallbtn">Voltar ao menu</button></div>';
  const botoes = espera.querySelectorAll('button');
  botoes[0].addEventListener('click', function () { location.reload(); });
  botoes[1].addEventListener('click', voltarAoMenu);
  document.body.appendChild(espera);
  estilo.textContent += ' .cliente-espera { position:fixed; left:50%; top:50%; transform:translate(-50%,-50%); z-index:300;'
    + ' background:#fff; color:#1e3e64; border-radius:24px; padding:24px 32px; text-align:center;'
    + ' box-shadow:0 18px 48px rgba(30,62,100,.28); font:600 1.2rem system-ui,sans-serif; }'
    + ' .cliente-espera[hidden] { display:none; } .cliente-espera p { margin:0 0 16px; }'
    + ' .cliente-espera-botoes { display:flex; gap:12px; justify-content:center; flex-wrap:wrap; }';

  // frontend/recursos.js anota os arquivos que falharam; se nem ele carregou, conta como falha.
  function recursosFalhos() {
    return Array.isArray(window.beniRecursosFalhos) ? window.beniRecursosFalhos : ['/frontend/recursos.js'];
  }

  function vigiar() {
    if (avisou || recarregando) { vazioDesde = 0; espera.hidden = true; return; }
    const falhos = recursosFalhos();
    if (falhos.length && recarregar('recurso', new Error('arquivo não carregou: ' + falhos.join(' ')))) {
      espera.hidden = true;
      return;
    }
    if (!temCfg()) {
      espera.hidden = Date.now() - semCfgDesde < 2000;
      if (Date.now() - semCfgDesde > 6000 || falhasSeguidas >= 3) {
        if (recarregar('config', ultimoErro())) { espera.hidden = true; return; }
      }
      carregar();
      return;
    }
    semCfgDesde = Date.now();
    falhasSeguidas = 0;
    espera.hidden = true;
    if (entrarDepois) { registrar('painel'); window.enterAdmin(); return; }
    if (algoNaTela() || (!cfg.pinConfigured && !carregou)) { vazioDesde = 0; return; }
    // nada na tela: espera mais um segundo (transições) e pede o PIN de novo
    if (!vazioDesde) { vazioDesde = Date.now(); return; }
    vazioDesde = 0;
    registrar('pin');
    abrirPais();
  }

  // Um arquivo da página que já falhou: recarrega antes de qualquer coisa.
  if (recursosFalhos().length && recarregar('recurso', new Error('arquivo não carregou: ' + recursosFalhos().join(' ')))) {
    return;
  }
  carregar();
  (function primeiro() {
    if (avisou || recarregando) return;
    if (temCfg()) { abrirPais(); return; }
    if (Date.now() - semCfgDesde < 3000) setTimeout(primeiro, 100);
  })();
  setInterval(vigiar, 1000);
  void fecharAdminOriginal;
})();
