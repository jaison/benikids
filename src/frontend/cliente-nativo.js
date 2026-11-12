// Integração com o menu nativo (beni-menu). Só age quando a aba foi aberta por ele
// (cliente.html marca sessionStorage.beniCliente):
//  - /index.html?pais=1 → abre direto a área dos pais (com o PIN, se houver); ao
//    sair dela (Voltar, Esc ou PIN cancelado) avisa o servidor e o menu nativo
//    fecha o navegador;
//  - /index.html sem ?pais=1 (ex.: "voltar" de um site embutido ou da biblioteca
//    de mídia) → avisa na hora, porque a tela da criança é a do menu nativo.
(function () {
  'use strict';
  let doCliente = false;
  try { doCliente = sessionStorage.getItem('beniCliente') === '1'; } catch (e) {}
  if (!doCliente) return;
  document.documentElement.classList.add('beni-cliente');
  let avisou = false;
  function voltarAoMenu() {
    if (avisou) return;
    avisou = true;
    document.body.style.visibility = 'hidden';
    fetch('/api/cliente/voltar', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      .catch(function () {});
  }
  const pais = new URLSearchParams(location.search).get('pais') === '1';
  if (!pais) { voltarAoMenu(); return; }

  // Some com a tela da criança desta aba: só a área dos pais interessa aqui.
  const estilo = document.createElement('style');
  estilo.textContent = 'html.beni-cliente #kids, html.beni-cliente .cornerbar, html.beni-cliente #clockBadge,'
    + ' html.beni-cliente #batteryBadge, html.beni-cliente #timerBadge, html.beni-cliente .nav { visibility:hidden !important; }';
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

  function abrirPais() {
    if (typeof cfg === 'undefined' || !cfg) { setTimeout(abrirPais, 100); return; }
    if (typeof openAdmin === 'function') openAdmin();
  }
  const inicio = typeof bootstrapLauncher === 'function' ? bootstrapLauncher() : null;
  if (inicio && typeof inicio.then === 'function') inicio.then(abrirPais, abrirPais); else abrirPais();
  void fecharAdminOriginal;
})();
