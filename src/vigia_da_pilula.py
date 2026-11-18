"""Vigia da pílula e do app aberto (Windows; roda numa thread do servidor). Roteiro 31.

No PC de teste, a pílula (overlay.py) travou junto com o Tux Paint: a criança ficou sem
✕ e sem sair. A cada 1 s, enquanto um app do menu está aberto, o vigia confere:

- a pílula: se o processo morreu (por 3 s, com o app ainda aberto) ou se a janela dela
  não responde por mais de 6 s, encerra o overlay e abre de novo com os mesmos
  argumentos ("overlay: pílula travada; reaberta"). No máximo 3 vezes por app aberto.
- o app: se a janela dele fica "Não respondendo" (IsHungAppWindow) por mais de 15 s
  seguidos, loga "app: <tile> não responde há N s" e manda para a telemetria. Não fecha
  sozinho: a criança fecha pelo ✕ (o ✕ encerra a árvore do app pelo Job Object).
  Enquanto ele não responde, o tempo de uso não conta.

Telemetria (no máximo 1 por assinatura por dia, sem dado pessoal): "overlay.travou:<tile>",
"overlay.caiu:<tile>" e "app.travou:<tile>".
"""

import os
import time

PILULA_TRAVADA_S = 6.0
PILULA_MORTA_S = 3.0
APP_TRAVADO_S = 15.0
REABERTURAS = 3
LOG = os.path.join(os.path.expanduser("~"), ".cache", "cozy-kids-launcher", "beni-windows.log")


def log_windows(texto, arquivo=None):
    try:
        with open(arquivo or LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + texto + "\n")
    except OSError:
        pass


class VigiaDaPilula:
    """A decisão, sem Windows: cada passo recebe o que foi medido e devolve as ações.

    Ações: ("reabrir", motivo, vez), ("desistir", motivo), ("app_parou",),
    ("app_voltou", segundos parado), ("app_travado", segundos)."""

    def __init__(self, travada_s=PILULA_TRAVADA_S, morta_s=PILULA_MORTA_S,
                 app_s=APP_TRAVADO_S, reaberturas=REABERTURAS):
        self.travada_s = travada_s
        self.morta_s = morta_s
        self.app_s = app_s
        self.reaberturas = reaberturas
        self._novo(None)

    def _novo(self, sessao):
        self.sessao = sessao
        self.vezes = 0
        self.desistiu = False
        self.travada_desde = None
        self.morta_desde = None
        self.app_desde = None
        self.app_avisado = False

    def passo(self, agora, sessao, app_vivo, pilula_viva, pilula_travada, app_travado):
        acoes = []
        if not app_vivo or sessao != self.sessao:
            if self.app_desde is not None:
                acoes.append(("app_voltou", agora - self.app_desde))
            self._novo(sessao if app_vivo else None)
            if not app_vivo:
                return acoes

        # o app
        if app_travado:
            if self.app_desde is None:
                self.app_desde = agora
                acoes.append(("app_parou",))
            elif not self.app_avisado and agora - self.app_desde >= self.app_s:
                self.app_avisado = True
                acoes.append(("app_travado", agora - self.app_desde))
        elif self.app_desde is not None:
            acoes.append(("app_voltou", agora - self.app_desde))
            self.app_desde = None
            self.app_avisado = False

        # a pílula
        motivo = None
        if not pilula_viva:
            self.travada_desde = None
            self.morta_desde = self.morta_desde if self.morta_desde is not None else agora
            if agora - self.morta_desde >= self.morta_s:
                motivo = "caiu"
        else:
            self.morta_desde = None
            if pilula_travada:
                self.travada_desde = self.travada_desde if self.travada_desde is not None else agora
                if agora - self.travada_desde >= self.travada_s:
                    motivo = "travou"
            else:
                self.travada_desde = None
        if motivo:
            self.travada_desde = self.morta_desde = None
            if self.vezes < self.reaberturas:
                self.vezes += 1
                acoes.append(("reabrir", motivo, self.vezes))
            elif not self.desistiu:
                self.desistiu = True
                acoes.append(("desistir", motivo))
        return acoes


class VigiaWindows:
    """Mede no Windows e executa as ações. Tudo com limite de tempo: o vigia nunca
    fica preso a uma janela (IsHungAppWindow e SendMessageTimeout de 500 ms)."""

    def __init__(self, win, launcher, registros, uso=None, relatar=None, log=log_windows,
                 relogio=time.monotonic, vigia=None):
        self.win = win
        self.launcher = launcher  # () -> ApplicationLauncher
        self.registros = registros  # () -> (registro do app, registro do overlay)
        self.uso = uso  # UsageTracker (pausar/retomar)
        self.relatar = relatar
        self.log = log
        self.relogio = relogio
        self.vigia = vigia or VigiaDaPilula()
        self.descontado = 0.0

    def _pilula_travada(self, pid):
        for h in self.win.janelas_de([pid])[:1]:
            return self.win.travada(h) or not self.win.responde(h, 500)
        return False

    def _app_travado(self, pid):
        return any(self.win.travada(h) for h in self.win.janelas_de(self.win.arvore(pid)))

    def volta(self):
        app, pilula = self.registros()
        args = getattr(self.launcher(), "ultimo_overlay", None) or {}
        tile = args.get("tile_id") or "?"
        app_vivo = bool(app)
        sessao = (app["pid"], app.get("startTime")) if app else None
        pilula_viva = bool(pilula)
        travada = pilula_viva and self._pilula_travada(pilula["pid"])
        app_travado = app_vivo and self._app_travado(app["pid"])
        for acao in self.vigia.passo(self.relogio(), sessao, app_vivo, pilula_viva, travada, app_travado):
            self.executar(acao, tile, args)

    def executar(self, acao, tile, args):
        tipo = acao[0]
        if tipo == "app_parou":
            if self.uso is not None:
                self.uso.pausar()
            self.log(f"app: {tile} não responde (IsHungAppWindow); o tempo de uso não conta")
        elif tipo == "app_voltou":
            segundos = self.uso.retomar() if self.uso is not None else acao[1]
            self.descontado += segundos
            self.log(f"app: {tile} voltou a responder ou fechou; {int(segundos)} s não contados")
        elif tipo == "app_travado":
            self.log(f"app: {tile} não responde há {int(acao[1])} s")
            if self.relatar:
                self.relatar("app.travou", f"tile={tile} sem responder há {int(acao[1])} s", f"app.travou:{tile}")
        elif tipo == "reabrir":
            motivo, vez = acao[1], acao[2]
            reaberta = self.reabrir(args)
            parado = self.uso.parado_agora() if self.uso is not None else 0
            self.log(f"overlay: pílula {'travada' if motivo == 'travou' else 'caiu'}; "
                     f"{'reaberta' if reaberta else 'NÃO deu para reabrir'} ({tile}, {vez}ª vez; "
                     f"{int(self.descontado + parado)} s de app travado não contados até agora)")
            if self.relatar:
                self.relatar("overlay." + motivo, f"tile={tile} vez={vez} reaberta={reaberta}",
                             f"overlay.{motivo}:{tile}")
        elif tipo == "desistir":
            self.log(f"overlay: a pílula do {tile} {acao[1]} {REABERTURAS} vezes; não reabro mais")

    def reabrir(self, args):
        if not args:
            return False
        launcher = self.launcher()
        with launcher.lock:
            app, _ = self.registros()
            if not app or (app["pid"], app.get("startTime")) != self.vigia.sessao:
                return False  # outro app foi aberto nesse meio-tempo
            launcher.stop_existing_overlay()
            return bool(launcher.start_overlay(args.get("mode", "local"), url=args.get("url", ""),
                                               tile_id=args.get("tile_id", "")))

    def rodar(self, parar, intervalo=1.0):
        erros = set()
        while not parar.wait(intervalo):
            try:
                self.volta()
            except Exception as erro:  # noqa: BLE001 — o vigia não pode parar
                texto = f"vigia da pílula: {type(erro).__name__}: {erro}"
                if texto not in erros:
                    erros.add(texto)
                    self.log(texto)
