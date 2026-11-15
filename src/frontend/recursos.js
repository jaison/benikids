// Guarda os arquivos da página (CSS/JS) que não carregaram. Carregado antes de
// tudo no index.html. Com um deles faltando, a tela sai sem a marca ou para de
// funcionar; na aba aberta pelo menu nativo, frontend/cliente-nativo.js recarrega.
window.beniRecursosFalhos = [];
window.addEventListener('error', function (e) {
  var t = e.target;
  if (t && (t.tagName === 'SCRIPT' || t.tagName === 'LINK')) {
    window.beniRecursosFalhos.push(String(t.src || t.href || '').replace(/^https?:\/\/[^/]+/, ''));
  }
}, true);
