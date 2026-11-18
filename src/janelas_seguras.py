"""Mexer em janela de OUTRO processo sem ficar preso a ela (Windows; roteiro 31).

No PC de teste, o Tux Paint e a pílula travaram juntos (os dois "Não respondendo", sem
CPU): a pílula fazia AttachThreadInput com a janela da frente e depois ShowWindow,
BringWindowToTop e SetForegroundWindow enquanto o Tux Paint ainda criava a janela.
Com as filas de entrada ligadas, um esperava o outro, e o menu (ligado à mesma fila)
parou de pintar e de receber toques até a pílula ser morta.

Regras daqui para a frente:
- nada de AttachThreadInput;
- janela travada (IsHungAppWindow) não é tocada;
- só chamadas assíncronas (ShowWindowAsync, SetWindowPos com SWP_ASYNCWINDOWPOS);
- o que não tem versão assíncrona (SetWindowLongPtr num estilo, que manda
  WM_STYLECHANGING ao app) só depois de o app responder a um SendMessageTimeout curto,
  e numa thread de trabalho (Trabalhador), nunca na thread do Tk.

Este módulo não usa ctypes: a lógica é testável fora do Windows. O plataforma_windows
entrega as chamadas de verdade.
"""

import threading
import time

SW_SHOW = 5
SW_RESTORE = 9


def trazer(api, h):
    """Põe a janela h no primeiro plano sem ligar filas de entrada.

    api: travada(h), frente(), iconica(h), visivel(h), mostrar(h, sw) (assíncrono),
    primeiro_plano(h) -> bool (SetForegroundWindow) e segurar_alt(bool).

    Devolve "ja" (já estava na frente), "direto", "alt", "travada" ou "falhou".
    - "travada": o app não processa mensagens; não mexe (tenta de novo depois).
    - "direto": o Windows deixou trocar o primeiro plano.
    - "alt": o Windows só deixou com a tecla Alt apertada (o "truque do Alt": um
      processo que está mandando entrada pode trocar o primeiro plano). É entrada
      sintética, que só entra na fila de quem está na frente: ninguém espera ninguém.
    """
    if not h:
        return "falhou"
    if api.travada(h):
        return "travada"
    if api.frente() == h:
        return "ja"
    if api.iconica(h):
        api.mostrar(h, SW_RESTORE)
    elif not api.visivel(h):
        api.mostrar(h, SW_SHOW)
    if api.primeiro_plano(h):
        return "direto"
    api.segurar_alt(True)
    try:
        ok = api.primeiro_plano(h)
    finally:
        api.segurar_alt(False)
    return "alt" if ok else "falhou"


def pode_mexer(api, h, ms=300):
    """Antes de uma chamada que espera o app (SetWindowLongPtr): ele não está travado e
    respondeu a um WM_NULL em até `ms` (SendMessageTimeout com SMTO_ABORTIFHUNG)."""
    return bool(h) and not api.travada(h) and api.responde(h, ms)


class Trabalhador:
    """Uma thread que faz as chamadas que podem demorar; quem pede nunca espera.

    Uma tarefa por vez: enquanto uma está rodando (ou presa numa janela travada), os
    pedidos novos são recusados (pedir devolve False) e a pílula segue viva. O erro de
    uma tarefa vai para ao_erro e não para a thread."""

    def __init__(self, nome="trabalho", ao_erro=None, relogio=time.monotonic, iniciar=True):
        self.nome = nome
        self.ao_erro = ao_erro
        self.relogio = relogio
        self._cond = threading.Condition()
        self._pendente = None
        self._atual = None  # (chave, começou em)
        self._thread = None
        if iniciar:
            self._thread = threading.Thread(target=self._rodar, name=nome, daemon=True)
            self._thread.start()

    def pedir(self, chave, funcao, *args):
        with self._cond:
            if self._atual is not None or self._pendente is not None:
                return False
            self._pendente = (chave, funcao, args)
            self._cond.notify()
        return True

    def preso(self):
        """(chave, segundos) da tarefa em andamento, ou None."""
        with self._cond:
            if self._atual is None:
                return None
            chave, desde = self._atual
            return chave, self.relogio() - desde

    def rodar_uma(self, espera=None):
        """Roda a tarefa pendente (a thread faz isso sozinha; os testes chamam direto)."""
        with self._cond:
            if self._pendente is None and espera is not None:
                self._cond.wait(espera)
            if self._pendente is None:
                return False
            chave, funcao, args = self._pendente
            self._pendente = None
            self._atual = (chave, self.relogio())
        try:
            funcao(*args)
        except Exception as erro:  # noqa: BLE001 — uma tarefa ruim não para as próximas
            if self.ao_erro:
                try:
                    self.ao_erro(chave, erro)
                except Exception:  # noqa: BLE001
                    pass
        finally:
            with self._cond:
                self._atual = None
        return True

    def _rodar(self):
        while True:
            self.rodar_uma(espera=1.0)


def rodar_com_limite(funcao, segundos, *args):
    """Roda numa thread e espera no máximo `segundos` (ao fechar a pílula: dar a frente ao
    menu sem arriscar ficar preso). Devolve o resultado, ou None se não terminou."""
    resultado = []

    def alvo():
        try:
            resultado.append(funcao(*args))
        except Exception:  # noqa: BLE001
            resultado.append(None)

    t = threading.Thread(target=alvo, daemon=True)
    t.start()
    t.join(segundos)
    return resultado[0] if resultado else None
