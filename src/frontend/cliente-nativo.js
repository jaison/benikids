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
  // ficava só com o fundo até o F5. Se o /api/config falha ou trava uma vez, o
  // bootstrap desiste (cfg = null) e o aviso de erro com "tentar de novo" vai para
  // a tela da criança, que esta aba esconde; o abrirPais esperava o cfg para
  // sempre. Agora um vigia, a cada segundo:
  //  - sem configuração: carrega de novo (e recarrega a página se travou);
  //  - PIN aceito sem configuração: abre o painel quando ela voltar;
  //  - com configuração e nada na tela (nem PIN, nem painel, nem janela): pede o
  //    PIN de novo (sem PIN, abre o painel).
  // Cada recuperação vira o evento "cliente.recuperado" no diagnóstico.
  let carregou = false;      // o carregamento completo terminou (com ou sem erro)
  let carregando = false;
  let cargaDesde = Date.now();
  let entrarDepois = false;
  let vazioDesde = 0;
  const temCfg = function () { return typeof cfg !== 'undefined' && !!cfg; };
  const registros = {};
  function registrar(etapa) {
    registros[etapa] = (registros[etapa] || 0) + 1;
    if (registros[etapa] > 5) return; // servidor com problema: não enche o diagnóstico
    fetch('/api/cliente/evento', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ etapa: etapa }) }).catch(function () {});
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
    try { return entrarOriginal.apply(this, arguments); } catch (e) { registrar('painel'); }
  };

  // Com PIN, pede o PIN assim que a configuração chega, sem esperar o resto do
  // carregamento (apps, recomendações, cronômetro). Sem PIN, a área dos pais abre
  // direto e espera tudo carregar.
  function abrirPais() {
    if (avisou || !temCfg()) return;
    if (!cfg.pinConfigured && !carregou) return;
    if (aberto('admin') || aberto('pin')) return;
    if (entrarDepois) { window.enterAdmin(); return; } // o PIN já foi aceito
    if (typeof openAdmin === 'function') openAdmin();
  }
  function carregar() {
    if (carregando || typeof bootstrapLauncher !== 'function') return;
    carregando = true;
    cargaDesde = Date.now();
    const fim = function () { carregando = false; carregou = true; abrirPais(); };
    Promise.resolve(bootstrapLauncher()).then(fim, fim);
  }

  // Mensagem enquanto a configuração não chega (em vez da tela vazia).
  const espera = document.createElement('div');
  espera.className = 'cliente-espera';
  espera.setAttribute('role', 'status');
  espera.hidden = true;
  espera.innerHTML = '<p>Abrindo a área dos pais…</p><button type="button" class="smallbtn">Voltar ao menu</button>';
  espera.querySelector('button').addEventListener('click', voltarAoMenu);
  document.body.appendChild(espera);
  estilo.textContent += ' .cliente-espera { position:fixed; left:50%; top:50%; transform:translate(-50%,-50%); z-index:300;'
    + ' background:#fff; color:#1e3e64; border-radius:24px; padding:24px 32px; text-align:center;'
    + ' box-shadow:0 18px 48px rgba(30,62,100,.28); font:600 1.2rem system-ui,sans-serif; }'
    + ' .cliente-espera[hidden] { display:none; } .cliente-espera p { margin:0 0 16px; }';

  function vigiar() {
    if (avisou) { vazioDesde = 0; espera.hidden = true; return; }
    if (!temCfg()) {
      espera.hidden = Date.now() - cargaDesde < 2000;
      if (!carregando) { registrar('config'); carregar(); return; }
      // o carregamento travou (o fetch não volta): recarrega a página, como o F5
      if (Date.now() - cargaDesde > 6000) { registrar('config'); location.reload(); }
      return;
    }
    espera.hidden = true;
    if (entrarDepois) { registrar('painel'); window.enterAdmin(); return; }
    if (algoNaTela() || (!cfg.pinConfigured && !carregou)) { vazioDesde = 0; return; }
    // nada na tela: espera mais um segundo (transições) e pede o PIN de novo
    if (!vazioDesde) { vazioDesde = Date.now(); return; }
    vazioDesde = 0;
    registrar('pin');
    abrirPais();
  }

  carregar();
  (function primeiro() {
    if (avisou) return;
    if (temCfg()) { abrirPais(); return; }
    if (Date.now() - cargaDesde < 3000) setTimeout(primeiro, 100);
  })();
  setInterval(vigiar, 1000);
  void fecharAdminOriginal;
})();
