/* Segura a janela do site: outro domínio não abre, nem em janela nova.
   BENI_REGEXES e BENI_BLOQUEIOS são trocados ao abrir o tile (navegacao_sites.py).
   Roda no mundo da página, antes dos scripts dela. O declarativeNetRequest
   cobre o que este arquivo não alcançar (refresh, redirect). */
(() => {
  var BENI_REGEXES = [];
  var BENI_BLOQUEIOS = [];

  var permitir = BENI_REGEXES.map(function (s) { return new RegExp(s); });
  var bloquear = BENI_BLOQUEIOS.map(function (s) { return new RegExp(s); });

  function permitido(href) {
    var i;
    for (i = 0; i < bloquear.length; i++) if (bloquear[i].test(href)) return false;
    for (i = 0; i < permitir.length; i++) if (permitir[i].test(href)) return true;
    return false;
  }

  function httpUrl(valor) {
    try {
      var u = new URL(valor, location.href);
      if (u.protocol !== "http:" && u.protocol !== "https:") return null;
      return u.href;
    } catch (e) {
      return null;
    }
  }

  function linkDoEvento(e) {
    var caminho = e.composedPath ? e.composedPath() : [e.target];
    var i, no;
    for (i = 0; i < caminho.length; i++) {
      no = caminho[i];
      if (no && no.tagName && String(no.tagName).toLowerCase() === "a") return no;
    }
    return null;
  }

  function noClique(e) {
    var a = linkDoEvento(e);
    if (!a) return;
    var bruto = a.getAttribute("href") || "";
    var resolvido = httpUrl(a.href || bruto);
    if (!resolvido) {
      if (bruto && !/^javascript:/i.test(bruto)) {
        e.preventDefault();
        e.stopImmediatePropagation();
      }
      return;
    }
    var alvo = (a.getAttribute("target") || "").toLowerCase();
    var nova = alvo && alvo !== "_self" && alvo !== "_top" && alvo !== "_parent";
    var modificado = e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1;
    if (!permitido(resolvido) || nova || modificado) {
      e.preventDefault();
      e.stopImmediatePropagation();
      if (permitido(resolvido)) location.assign(resolvido);
    }
  }

  window.addEventListener("click", noClique, true);
  window.addEventListener("auxclick", noClique, true);

  window.addEventListener("submit", function (e) {
    var f = e.target;
    if (!f || !f.action) return;
    var resolvido = httpUrl(f.action);
    if (!resolvido || !permitido(resolvido)) {
      e.preventDefault();
      e.stopImmediatePropagation();
    }
  }, true);

  window.open = function (url) {
    if (url == null || url === "" || url === "about:blank") return null;
    var resolvido = httpUrl(url);
    if (resolvido && permitido(resolvido)) location.assign(resolvido);
    return null;
  };

  try {
    if (navigator.share) navigator.share = function () { return Promise.resolve(); };
  } catch (e) {}

  try {
    ["assign", "replace"].forEach(function (nome) {
      var original = Location.prototype[nome];
      if (typeof original !== "function") return;
      Location.prototype[nome] = function (url) {
        var resolvido = httpUrl(url);
        if (resolvido && !permitido(resolvido)) return;
        if (!resolvido && url) return;
        return original.apply(this, arguments);
      };
    });
    var desc = Object.getOwnPropertyDescriptor(Location.prototype, "href");
    if (desc && desc.set && desc.get) {
      Object.defineProperty(Location.prototype, "href", {
        configurable: true,
        enumerable: desc.enumerable,
        get: desc.get,
        set: function (valor) {
          var resolvido = httpUrl(valor);
          if (resolvido && !permitido(resolvido)) return;
          if (!resolvido && valor) return;
          return desc.set.call(this, valor);
        },
      });
    }
  } catch (e) {}
})();
