"""Roteiro 31: pílula travada é reaberta (até 3 vezes); app travado é logado, vai para a
telemetria e não conta tempo."""
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import vigia_da_pilula as vp  # noqa: E402
from application_launcher import ApplicationLauncher, PortaoDeAbertura  # noqa: E402
from usage_limits import UsageTracker  # noqa: E402

S = (100, 1)  # sessão: pid e hora de criação do supervisor


class DecisaoTests(unittest.TestCase):
    def test_pill_hung_more_than_6_s_is_reopened_at_most_3_times(self):
        v = vp.VigiaDaPilula()
        acoes = []
        for t in range(0, 60):
            acoes += v.passo(float(t), S, True, True, True, False)
        reaberturas = [a for a in acoes if a[0] == "reabrir"]
        self.assertEqual([a[2] for a in reaberturas], [1, 2, 3])
        self.assertEqual(reaberturas[0][1], "travou")
        self.assertEqual([a for a in acoes if a[0] == "desistir"], [("desistir", "travou")])

    def test_short_hiccup_is_not_a_hang(self):
        v = vp.VigiaDaPilula()
        acoes = []
        for t in range(0, 30):
            acoes += v.passo(float(t), S, True, True, t % 6 < 5, False)  # 5 s travada, 1 s viva
        self.assertEqual(acoes, [])

    def test_pill_that_died_with_the_app_open_is_reopened(self):
        v = vp.VigiaDaPilula()
        self.assertEqual(v.passo(0.0, S, True, False, False, False), [])
        self.assertEqual(v.passo(2.0, S, True, False, False, False), [])
        self.assertEqual(v.passo(3.0, S, True, False, False, False), [("reabrir", "caiu", 1)])

    def test_closing_the_app_with_the_x_is_not_a_crash(self):
        v = vp.VigiaDaPilula()
        v.passo(0.0, S, True, False, False, False)  # a pílula saiu primeiro (✕)
        self.assertEqual(v.passo(1.0, None, False, False, False, False), [])  # o app foi junto
        self.assertEqual(v.passo(5.0, None, False, False, False, False), [])

    def test_a_new_app_resets_the_count(self):
        v = vp.VigiaDaPilula(reaberturas=1)
        for t in range(0, 20):
            v.passo(float(t), S, True, True, True, False)
        acoes = []
        for t in range(20, 30):
            acoes += v.passo(float(t), (200, 5), True, True, True, False)
        self.assertEqual([a[0] for a in acoes], ["reabrir"])

    def test_hung_app_pauses_usage_reports_once_after_15_s_and_resumes(self):
        v = vp.VigiaDaPilula()
        acoes = []
        for t in range(0, 40):
            acoes += v.passo(float(t), S, True, True, False, True)
        acoes += v.passo(40.0, S, True, True, False, False)
        self.assertEqual(acoes[0], ("app_parou",))
        self.assertEqual([a for a in acoes if a[0] == "app_travado"], [("app_travado", 15.0)])
        self.assertEqual(acoes[-1], ("app_voltou", 40.0))


class LauncherFalso:
    def __init__(self):
        self.lock = threading.Lock()
        self.ultimo_overlay = {"mode": "local", "url": "", "tile_id": "tuxpaint"}
        self.chamadas = []

    def stop_existing_overlay(self):
        self.chamadas.append("parar")

    def start_overlay(self, mode, url="", tile_id=""):
        self.chamadas.append(("abrir", mode, url, tile_id))
        return True


class VigiaWindowsTests(unittest.TestCase):
    def montar(self, pilula_viva=True, pilula_travada=True, app_travado=False):
        self.agora = [0.0]
        self.linhas, self.relatos = [], []
        win = mock.Mock()
        win.janelas_de.side_effect = lambda pids: [0xAA] if pids == [7] else [0xBB]
        win.arvore.return_value = [100, 101]
        self.estado = {"pilula": pilula_travada, "app": app_travado}
        win.travada.side_effect = lambda h: self.estado["pilula"] if h == 0xAA else self.estado["app"]
        win.responde.return_value = True
        self.launcher = LauncherFalso()
        app = {"pid": 100, "startTime": 1}
        pilula = {"pid": 7} if pilula_viva else None
        self.uso = mock.Mock()
        self.uso.retomar.return_value = 412.0
        self.uso.parado_agora.return_value = 30.0
        return vp.VigiaWindows(win, lambda: self.launcher, lambda: (app, pilula), uso=self.uso,
                               relatar=lambda *a: self.relatos.append(a), log=self.linhas.append,
                               relogio=lambda: self.agora[0])

    def rodar(self, v, segundos):
        for _ in range(segundos):
            v.volta()
            self.agora[0] += 1

    def test_hung_pill_is_killed_and_reopened_with_the_same_arguments(self):
        v = self.montar()
        self.rodar(v, 8)
        self.assertEqual(self.launcher.chamadas, ["parar", ("abrir", "local", "", "tuxpaint")])
        self.assertTrue(any(linha.startswith("overlay: pílula travada; reaberta (tuxpaint, 1ª vez")
                            for linha in self.linhas), self.linhas)
        self.assertEqual(self.relatos[0][2], "overlay.travou:tuxpaint")

    def test_dead_pill_is_reported_as_caiu(self):
        v = self.montar(pilula_viva=False)
        self.rodar(v, 4)
        self.assertEqual(self.relatos[0][2], "overlay.caiu:tuxpaint")

    def test_hung_app_is_logged_reported_and_its_time_not_counted(self):
        v = self.montar(pilula_travada=False, app_travado=True)
        self.rodar(v, 17)
        self.uso.pausar.assert_called_once()
        self.assertIn("app: tuxpaint não responde há 15 s", self.linhas)
        self.assertEqual(self.relatos, [("app.travou", "tile=tuxpaint sem responder há 15 s", "app.travou:tuxpaint")])
        self.estado["app"] = False
        self.rodar(v, 1)
        self.assertIn("app: tuxpaint voltou a responder ou fechou; 412 s não contados", self.linhas)
        self.assertEqual(self.launcher.chamadas, [])  # o app NÃO é fechado sozinho


class TempoParadoTests(unittest.TestCase):
    def test_paused_time_is_not_counted_and_is_reported(self):
        agora = [1000.0]
        with tempfile.TemporaryDirectory() as pasta:
            u = UsageTracker(Path(pasta, "uso.json"), lambda: {}, lambda: True, lambda: None,
                             clock=lambda: agora[0])
            u.set_active("p", "tuxpaint", "passatempo")
            for _ in range(10):
                agora[0] += 1
                u.tick()
            u.pausar()
            for _ in range(8):
                agora[0] += 1
                u.tick()
            self.assertEqual(u.parado_agora(), 8)
            self.assertEqual(u.retomar(), 8)
            agora[0] += 1
            u.tick()
            entrada = u.usage["profiles"]["p"]
            self.assertEqual(entrada["totalSeconds"], 11)
            self.assertEqual(entrada["categories"]["passatempo"], 11)


class PortaoTests(unittest.TestCase):
    """Roteiro 31: o menu destravou e mandou ~32 toques represados; o servidor abriu o
    Kiddo Games ~32 vezes, uma a cada ~2,5 s."""

    def test_one_launch_at_a_time_with_3_s_of_slack(self):
        agora = [0.0]
        p = PortaoDeAbertura(relogio=lambda: agora[0])
        self.assertTrue(p.entrar())
        self.assertFalse(p.entrar())  # o pedido seguinte chega enquanto o 1º abre
        p.abriu_app()
        agora[0] = 2.5
        p.sair()
        agora[0] = 4.0
        self.assertFalse(p.entrar())  # 1,5 s depois de abrir: represado
        agora[0] = 5.6
        self.assertTrue(p.entrar())
        p.sair()  # não abriu nada (bloqueado): sem folga
        self.assertTrue(p.entrar())

    def test_server_uses_the_gate_and_the_overlay_args_are_kept(self):
        codigo = (Path(__file__).resolve().parent.parent / "src" / "server.py").read_text(encoding="utf-8")
        self.assertIn("if not PORTAO_DE_ABERTURA.entrar():", codigo)
        self.assertIn("PORTAO_DE_ABERTURA.sair()", codigo)
        self.assertIn("PORTAO_DE_ABERTURA.abriu_app()", codigo)
        launcher = ApplicationLauncher("t.pid", "o.pid", "sup.py", "/nao/existe/overlay.py")
        self.assertFalse(launcher.start_overlay("local", tile_id="x"))  # sem o script não abre
        self.assertIn("ultimo_overlay = None", (Path(__file__).resolve().parent.parent / "src" /
                                                 "application_launcher.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
