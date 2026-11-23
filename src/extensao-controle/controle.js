// Beni Launcher: troca navigator.getGamepads() por uma versão que entrega cada
// controle USB no formato "standard" da Gamepad API (0 = ✕/de baixo, 1 = ◯,
// 2 = □, 3 = △, 4/5 = L1/R1, 6/7 = L2/R2, 8 = Select, 9 = Start, 12–15 =
// direcional, eixos 0–3 = analógicos), usando o mapeamento da área dos pais
// (window.__beniControles, gerado em mapa.js).
//
// - Controle que o Chromium não conhece (mapping ""): monta tudo a partir da
//   numeração crua (botões e eixos na ordem do kernel; o direcional "hat" chega
//   como dois eixos).
// - Controle que o Chromium já chama de "standard": o direcional e os
//   analógicos já vêm certos, mas os botões 0–11 seguem a numeração crua;
//   então só os botões são reordenados.
(function () {
  "use strict";
  const MAPAS = window.__beniControles || {};
  const original = Navigator.prototype.getGamepads;
  if (typeof original !== "function" || !Object.keys(MAPAS).length) return;
  const ORDEM = ["a", "b", "x", "y", "l1", "r1", "l2", "r2", "select", "start", "l3", "r3",
                 "up", "down", "left", "right"];

  function chave(id) {
    const texto = id || "";
    const m = /Vendor:\s*([0-9a-f]{4})\s+Product:\s*([0-9a-f]{4})/i.exec(texto);
    if (m) return (m[1] + ":" + m[2]).toLowerCase();
    // Edge no Windows às vezes manda o id no formato do HID (VID_0079&PID_0006).
    const w = /VID_([0-9a-f]{4})&PID_([0-9a-f]{4})/i.exec(texto);
    return w ? (w[1] + ":" + w[2]).toLowerCase() : null;
  }
  function botao(valor) {
    const v = Math.max(0, Math.min(1, valor || 0));
    return Object.freeze({ pressed: v > 0.5, touched: v > 0.5, value: v });
  }
  function ler(pad, alvo) {
    // alvo: ["b", indice] | ["e", indice, sinal]
    if (!alvo) return 0;
    if (alvo[0] === "b") { const b = pad.buttons[alvo[1]]; return b ? b.value || (b.pressed ? 1 : 0) : 0; }
    const v = pad.axes[alvo[1]] || 0;
    return v * alvo[2] > 0.5 ? 1 : 0;
  }
  function eixo(pad, alvo) {
    if (!alvo) return 0;
    const v = pad.axes[alvo[0]] || 0;
    return alvo[1] < 0 ? -v : v;
  }
  function ehUnity() {
    return typeof window.createUnityInstance === "function" || typeof window.UnityLoader === "object";
  }
  function converter(pad) {
    // No Windows, mapping "standard" já é a ordem da Gamepad API (o WGI do
    // Edge arruma sozinho). Reordenar de novo trocaria os botões. O Linux não
    // define __beniPlataforma, então o comportamento de lá não muda.
    if (window.__beniPlataforma === "windows" && pad.mapping === "standard") return pad;
    const mapa = MAPAS[chave(pad.id)];
    if (!mapa) return pad;
    const padrao = pad.mapping === "standard";
    const botoes = [];
    for (let i = 0; i < 17; i++) {
      const nome = ORDEM[i];
      const alvo = mapa.botoes[nome];
      if (padrao && (i >= 12 || !alvo || alvo[0] !== "b")) {
        botoes.push(pad.buttons[i] || botao(0));      // o Chromium já acertou
      } else {
        botoes.push(botao(ler(pad, alvo)));
      }
    }
    const eixos = padrao ? Array.from(pad.axes).slice(0, 4)
      : ["lx", "ly", "rx", "ry"].map(n => eixo(pad, mapa.eixos[n]));
    while (eixos.length < 4) eixos.push(0);
    // Unity com o Input Manager antigo: "Horizontal"/"Vertical" do joystick só
    // olham o analógico. Com o analógico parado, o direcional move os eixos 0/1.
    if (ehUnity() && Math.abs(eixos[0]) < 0.2 && Math.abs(eixos[1]) < 0.2) {
      eixos[0] = botoes[15].value - botoes[14].value;
      eixos[1] = botoes[13].value - botoes[12].value;
    }
    return Object.freeze({
      id: pad.id, index: pad.index, connected: pad.connected, timestamp: pad.timestamp,
      mapping: "standard", axes: Object.freeze(eixos), buttons: Object.freeze(botoes),
      vibrationActuator: pad.vibrationActuator || null, hapticActuators: pad.hapticActuators || [],
    });
  }
  const novo = function getGamepads() {
    const lista = original.call(this);
    return Array.from(lista, p => (p ? converter(p) : null));
  };
  Object.defineProperty(novo, "toString", { value: () => "function getGamepads() { [native code] }" });
  Navigator.prototype.getGamepads = novo;
  const embrulhar = tipo => window.addEventListener(tipo, e => {
    if (e.gamepad) { try { Object.defineProperty(e, "gamepad", { value: converter(e.gamepad) }); } catch (_) {} }
  }, true);
  embrulhar("gamepadconnected");
  embrulhar("gamepaddisconnected");
})();
