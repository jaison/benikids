"""Timer da sessão acabou com um app aberto: o app fecha (Linux teimoso e
Windows, em que o primeiro sinal já é TerminateProcess) e a janela de bloqueio
fica na frente do que ainda estiver mapeado."""

import importlib
import json
import signal
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import process_state
import timer_fim


def carregar():
    """O python3 do Mac (Homebrew) pode vir sem Tk. O overlay e a vigia são
    carregados com um tkinter de mentira, como os outros testes."""
    tk = types.ModuleType("tkinter")
    fonte = types.ModuleType("tkinter.font")
    tk.font = fonte
    tk.Canvas = type("Canvas", (), {})
    tk.TclError = type("TclError", (Exception,), {})
    with mock.patch.dict(sys.modules, {"tkinter": tk, "tkinter.font": fonte}):
        for nome in ("overlay", "marca_tk", "timer_watchdog"):
            sys.modules.pop(nome, None)
        return importlib.import_module("overlay"), importlib.import_module("timer_watchdog")


overlay, timer_watchdog = carregar()


class ConstantesTest(unittest.TestCase):
    def test_o_mesmo_registro_que_o_x_do_overlay(self):
        self.assertEqual(timer_fim.TILE_PROCESS_PIDFILE, overlay.TILE_PROCESS_PIDFILE)
        self.assertEqual(timer_fim.TILE_PROCESS_MARKER, overlay.TILE_PROCESS_MARKER)


class OrdemDasJanelasTest(unittest.TestCase):
    def test_navegador_atras_do_app_sobe_e_o_app_sai_do_alt_tab(self):
        menu, pingus = 0x10, 0x20
        # pilha de baixo para cima: o Pingus está na frente do navegador
        passos = timer_fim.passos_da_ordem([menu, pingus], menu, [pingus])
        self.assertEqual(
            passos,
            [
                ("skip_taskbar", pingus),
                ("below", pingus),
                ("above", menu),
                ("ativar", menu),
            ],
        )

    def test_navegador_ja_na_frente_nao_rouba_o_foco_do_pin(self):
        menu, pingus = 0x10, 0x20
        passos = timer_fim.passos_da_ordem([pingus, menu], menu, [pingus])
        self.assertEqual(passos, [("skip_taskbar", pingus), ("below", pingus)])

    def test_vigia_fora_da_pilha_so_abaixa_o_app(self):
        # a janela override-redirect da vigia não entra no _NET_CLIENT_LIST_STACKING
        pingus = 0x20
        passos = timer_fim.passos_da_ordem([0x10, pingus], 0x99, [pingus])
        self.assertEqual(passos, [("skip_taskbar", pingus), ("below", pingus)])

    def test_sem_app_nao_deixa_o_menu_above(self):
        self.assertEqual(timer_fim.passos_da_ordem([0x10], 0x10, []), [])

    def test_aplica_no_wmctrl_e_reconhecer_o_menu(self):
        comandos = []
        timer_fim.aplicar_passos([("skip_taskbar", 32), ("ativar", 16)], comandos.append)
        self.assertEqual(comandos[0][:4], ["wmctrl", "-i", "-r", "0x20"])
        self.assertIn("skip_taskbar", comandos[0][-1])
        self.assertEqual(comandos[1], ["wmctrl", "-i", "-a", "0x10"])
        linhas = ["0x000a  0 host Beni", "0x0003  0 host Cozy Kids Launcher"]
        self.assertEqual(timer_fim.janela_do_menu(linhas), 0xA)
        self.assertEqual(
            timer_fim.pilha_do_texto("_NET_CLIENT_LIST_STACKING(WINDOW): window id # 0x1, 0x20"),
            [1, 0x20],
        )


class AppSimulado:
    """Processo de mentira. `teimoso` ignora SIGTERM (o Pingus); no Windows o
    primeiro os.kill já é TerminateProcess e o processo morre ali."""

    def __init__(self, teimoso):
        self.teimoso = teimoso
        self.vivo = True
        self.sinais = []

    def stat(self, _pid):
        if not self.vivo:
            return None
        return ("R", 100)

    def kill(self, _pid, sig):
        self.sinais.append(sig)
        if not self.teimoso or sig == signal.SIGKILL:
            self.vivo = False


class FecharQuandoExpiraTest(unittest.TestCase):
    def _expira(self, teimoso):
        app = AppSimulado(teimoso)
        agora = [0.0]

        def dormir(segundos):
            agora[0] += segundos

        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "tile-process.pid"
            caminho.write_text(
                json.dumps({
                    "recordVersion": 1,
                    "pid": 4242,
                    "startTime": 100,
                    "role": "tile-process",
                    "marker": "process_supervisor.py",
                }),
                encoding="utf-8",
            )
            with mock.patch.object(timer_fim, "TILE_PROCESS_PIDFILE", str(caminho)), \
                    mock.patch.object(timer_fim, "TILE_PROCESS_MARKER", "process_supervisor.py"), \
                    mock.patch.object(process_state, "_process_stat", app.stat), \
                    mock.patch.object(process_state, "process_command", lambda _pid: ["process_supervisor.py"]), \
                    mock.patch.object(process_state.os, "kill", app.kill), \
                    mock.patch.object(process_state.time, "monotonic", lambda: agora[0]), \
                    mock.patch.object(process_state.time, "sleep", dormir):
                fechou = timer_fim.tratar_expiracao(
                    {"active": True, "expired": True, "remainingSeconds": 0},
                    timeout=0.2,
                )
                # timer ainda correndo, ou sem estar expirado: não mexe no processo
                self.assertFalse(timer_fim.tratar_expiracao({"active": True, "expired": False}))
                self.assertFalse(timer_fim.tratar_expiracao({"active": False, "expired": True}))
        return fechou, app

    def test_linux_app_teimoso_recebe_sigterm_e_depois_sigkill(self):
        fechou, app = self._expira(teimoso=True)
        self.assertTrue(fechou)
        self.assertEqual(app.sinais, [signal.SIGTERM, signal.SIGKILL])
        self.assertFalse(app.vivo)

    def test_windows_o_primeiro_sinal_ja_encerra(self):
        # no Windows os.kill(SIGTERM) é TerminateProcess; o Job Object leva a árvore
        fechou, app = self._expira(teimoso=False)
        self.assertTrue(fechou)
        self.assertEqual(app.sinais, [signal.SIGTERM])
        self.assertFalse(app.vivo)


class OverlayFechaTest(unittest.TestCase):
    def novo(self):
        o = overlay.AppOverlay.__new__(overlay.AppOverlay)
        o.tile_id = "pingus"
        o.fechando = False
        o.timer_pilula = None
        o.uso_pilula = None
        o.usage_label = None
        o.root = mock.Mock()
        o.set_timer_text = mock.Mock()
        return o

    def test_poll_com_timer_expirado_fecha_o_app(self):
        o = self.novo()
        o.on_close = mock.Mock()

        def api(caminho, data=None):
            if "availability" in caminho:
                return {"profileAllowed": True, "blockedTileIds": []}
            return {"active": True, "expired": True, "remainingSeconds": 0, "warning": False}

        with mock.patch.object(overlay, "api", api):
            o.poll_timer()
        o.on_close.assert_called_once_with("acabou o timer")

    def test_relogio_local_no_zero_confirma_no_servidor_antes_de_fechar(self):
        o = self.novo()
        o.on_close = mock.Mock()
        o.timer_pilula = {"fim": overlay.time.monotonic() - 1, "expirado": False, "aviso": False}
        with mock.patch.object(overlay, "api", return_value={
            "active": True, "expired": True, "remainingSeconds": 0, "warning": False,
        }):
            o.atualizar_pilula()
        o.on_close.assert_called_once_with("acabou o timer")

    def test_relogio_local_no_zero_nao_fecha_se_o_servidor_ainda_tem_tempo(self):
        o = self.novo()
        o.on_close = mock.Mock()
        o.timer_pilula = {"fim": overlay.time.monotonic() - 1, "expirado": False, "aviso": False}
        with mock.patch.object(overlay, "api", return_value={
            "active": True, "expired": False, "remainingSeconds": 30, "warning": False,
        }):
            o.atualizar_pilula()
        o.on_close.assert_not_called()
        self.assertGreater(o.timer_pilula["fim"], overlay.time.monotonic())
        self.assertFalse(o.timer_pilula["expirado"])

    def test_linux_poe_o_bloqueio_na_frente_e_depois_fecha(self):
        o = self.novo()
        o.root.destroy = mock.Mock()
        ordem = []
        with mock.patch.object(overlay, "WINDOWS", False), \
                mock.patch.object(timer_fim, "por_o_bloqueio_na_frente", side_effect=lambda *a, **k: ordem.append("cobre")), \
                mock.patch.object(overlay, "terminate_owned_process", side_effect=lambda *a, **k: ordem.append("fecha") or True), \
                mock.patch.object(overlay, "focus_launcher", side_effect=lambda *a, **k: ordem.append("menu")), \
                self.assertRaises(SystemExit):
            o.on_close("acabou o timer")
        self.assertEqual(ordem, ["cobre", "fecha", "menu"])
        # a contagem da categoria continua sem esse passo
        ordem.clear()
        o.fechando = False
        with mock.patch.object(overlay, "WINDOWS", False), \
                mock.patch.object(timer_fim, "por_o_bloqueio_na_frente", side_effect=lambda *a, **k: ordem.append("cobre")), \
                mock.patch.object(overlay, "terminate_owned_process", return_value=True), \
                mock.patch.object(overlay, "focus_launcher"), \
                self.assertRaises(SystemExit):
            o.on_close("acabou o tempo")
        self.assertEqual(ordem, [])

    def test_windows_loga_e_encerra_o_supervisor(self):
        o = self.novo()
        o.root.destroy = mock.Mock()
        with tempfile.TemporaryDirectory() as pasta:
            with mock.patch.object(overlay, "WINDOWS", True), \
                    mock.patch.object(overlay, "CACHE_DIR", pasta), \
                    mock.patch.object(timer_fim, "por_o_bloqueio_na_frente") as cobre, \
                    mock.patch.object(overlay, "terminate_owned_process", return_value=True) as termina, \
                    mock.patch.object(overlay, "focus_launcher"), \
                    self.assertRaises(SystemExit):
                o.on_close("acabou o timer")
            cobre.assert_not_called()
            termina.assert_called_once_with(
                overlay.TILE_PROCESS_PIDFILE, "tile-process", overlay.TILE_PROCESS_MARKER,
            )
            log = Path(pasta, "beni-windows.log").read_text(encoding="utf-8")
        self.assertIn("overlay: fechando (acabou o timer)", log)
        self.assertIn("overlay: supervisor do app encerrado", log)


class VigiaFechaTest(unittest.TestCase):
    def test_a_vigia_chama_o_mesmo_fechar_e_nao_empilha(self):
        app = timer_watchdog.WatchdogApp.__new__(timer_watchdog.WatchdogApp)
        app._fechar_app = timer_watchdog.threading.Lock()
        app.status = {"active": True, "expired": True}
        with mock.patch.object(timer_fim, "tratar_expiracao", return_value=True) as tratar:
            app._fechar_app_do_timer()
        tratar.assert_called_once_with(app.status)
        app._fechar_app.acquire()
        with mock.patch.object(timer_fim, "tratar_expiracao") as tratar:
            app._fechar_app_do_timer()
        tratar.assert_not_called()

    def test_log_no_windows_quando_encerra(self):
        with tempfile.TemporaryDirectory() as pasta:
            with mock.patch.object(timer_watchdog, "CACHE_DIR", pasta), \
                    mock.patch.object(timer_watchdog.os, "name", "nt"):
                timer_watchdog._log_windows("vigia: o timer acabou; o app foi encerrado")
            texto = Path(pasta, "beni-windows.log").read_text(encoding="utf-8")
        self.assertIn("vigia: o timer acabou; o app foi encerrado", texto)


if __name__ == "__main__":
    unittest.main()
