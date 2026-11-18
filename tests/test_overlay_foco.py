"""overlay: o app que demora a abrir vem para a frente quando a janela dele aparece
(roteiro 24: o SuperTuxKart nasceu atrás do menu na 1ª vez; só a pílula aparecia)."""
import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def carregar():
    tk = types.ModuleType("tkinter")
    fonte = types.ModuleType("tkinter.font")
    tk.font = fonte
    tk.Canvas = type("Canvas", (), {})
    tk.TclError = type("TclError", (Exception,), {})
    with mock.patch.dict(sys.modules, {"tkinter": tk, "tkinter.font": fonte}):
        for nome in ("overlay", "marca_tk"):
            sys.modules.pop(nome, None)
        return importlib.import_module("overlay")


overlay = carregar()


MONITOR = (0, 0, 2560, 1080)
TRABALHO = (0, 0, 2560, 1040)  # a barra escondida continua reservando 40 px embaixo


class EsticarTests(unittest.TestCase):
    """Roteiro 27: sem o "ocultar automaticamente", os apps maximizados param 40 px acima do
    fim da tela; o overlay estica a janela maximizada até o monitor."""

    def test_windows10_maximized_window_keeps_its_8px_frame_overhang(self):
        # Kapman/KBlocks maximizados no Windows 10: 8 px além da área em cada lado
        self.assertEqual(overlay.retangulo_esticado((-8, -8, 2568, 1048), TRABALHO, MONITOR),
                         (-8, -8, 2568, 1088))

    def test_frameless_maximized_window_goes_edge_to_edge(self):
        self.assertEqual(overlay.retangulo_esticado((0, 0, 2560, 1040), TRABALHO, MONITOR), MONITOR)

    def test_taskbar_on_the_left_or_top_is_handled_the_same_way(self):
        self.assertEqual(overlay.retangulo_esticado((52, -8, 2568, 1088), (60, 0, 2560, 1080), MONITOR),
                         (-8, -8, 2568, 1088))
        self.assertEqual(overlay.retangulo_esticado((-8, 32, 2568, 1088), (0, 40, 2560, 1080), MONITOR),
                         (-8, -8, 2568, 1088))

    def test_second_monitor_uses_its_own_rectangles(self):
        mon2, trab2 = (2560, 0, 4480, 1080), (2560, 0, 4480, 1040)
        self.assertEqual(overlay.retangulo_esticado((2552, -8, 4488, 1048), trab2, mon2), (2552, -8, 4488, 1088))

    def test_already_stretched_fullscreen_or_no_strip_is_left_alone(self):
        self.assertIsNone(overlay.retangulo_esticado((-8, -8, 2568, 1088), TRABALHO, MONITOR))  # já esticada
        self.assertIsNone(overlay.retangulo_esticado(MONITOR, TRABALHO, MONITOR))  # STK, menu: tela cheia
        self.assertIsNone(overlay.retangulo_esticado((-8, -8, 2568, 1088), MONITOR, MONITOR))  # sem faixa

    def test_a_window_that_is_not_maximized_to_the_work_area_is_not_touched(self):
        # Klavaro/Quinze em janela; ou um app "maximizado" num tamanho próprio
        self.assertIsNone(overlay.retangulo_esticado((600, 200, 1400, 800), TRABALHO, MONITOR))
        self.assertIsNone(overlay.retangulo_esticado((-30, -30, 2590, 1070), TRABALHO, MONITOR))
        self.assertIsNone(overlay.retangulo_esticado((0, 0, 2000, 1040), TRABALHO, MONITOR))

    def test_an_app_that_keeps_shrinking_back_is_given_up_on(self):
        e = overlay.Esticador(limite=3)
        maximizada = (-8, -8, 2568, 1048)
        for _ in range(3):
            self.assertIsNotNone(e.passo("kapman", maximizada, TRABALHO, MONITOR))
        self.assertTrue(e.desistiu("kapman"))
        self.assertIsNone(e.passo("kapman", maximizada, TRABALHO, MONITOR))
        self.assertIsNotNone(e.passo("outra", maximizada, TRABALHO, MONITOR))  # cada janela conta à parte
        self.assertIsNone(e.passo("ok", (-8, -8, 2568, 1088), TRABALHO, MONITOR))
        self.assertNotIn("ok", e.vezes)


class PilulaTests(unittest.TestCase):
    # roteiro 26: a pílula mostrava "28 min" do limite de Aprender com o timer em 3 min
    def test_shows_whatever_ends_first(self):
        uso = {"restante": 28 * 60, "limite": 30 * 60, "emoji": "📚"}
        timer = {"restante": 3 * 60, "expirado": False, "aviso": False}
        self.assertEqual(overlay.rotulo_da_pilula(uso, timer, "cor")[0], "⏱️ 3 min")
        timer["restante"] = 40 * 60
        self.assertEqual(overlay.rotulo_da_pilula(uso, timer, "cor")[0], "📚 28 min")
        self.assertEqual(overlay.rotulo_da_pilula(None, timer, "cor"), ("⏱️ 40 min", "cor"))
        self.assertEqual(overlay.rotulo_da_pilula(uso, None, "cor")[0], "📚 28 min")
        self.assertEqual(overlay.rotulo_da_pilula(None, None, "cor"), ("", None))

    def test_timer_warning_and_end(self):
        aviso = {"restante": 4 * 60 + 10, "expirado": False, "aviso": True}
        self.assertEqual(overlay.rotulo_da_pilula(None, aviso, "cor"), ("⏱️ 5 min", overlay.TIMER_COR_AVISO))
        fim = {"restante": 0, "expirado": True, "aviso": False}
        uso = {"restante": 600, "limite": 1800, "emoji": "🎮"}
        self.assertEqual(overlay.rotulo_da_pilula(uso, fim, "cor"), ("⏰ Acabou!", overlay.TIMER_COR_FIM))


class PrimeiraJanelaTests(unittest.TestCase):
    def test_waits_for_the_window_then_brings_it_once(self):
        p = overlay.PrimeiraJanela()
        self.assertEqual([p.passo(False, False) for _ in range(6)], ["esperar"] * 6)  # compilando shaders
        self.assertEqual(p.passo(True, False), "trazer")
        self.assertEqual(p.passo(True, True), "esperar")
        self.assertEqual(p.passo(True, True), "esperar")
        self.assertEqual(p.passo(True, True), "fim")

    def test_app_already_in_front_is_left_alone(self):
        p = overlay.PrimeiraJanela()
        self.assertEqual([p.passo(True, True) for _ in range(3)], ["esperar", "esperar", "fim"])
        self.assertEqual(p.trazidas, 0)

    def test_gives_up_after_a_few_tries_and_at_the_limit(self):
        p = overlay.PrimeiraJanela(tentativas=2)
        self.assertEqual([p.passo(True, False) for _ in range(3)], ["trazer", "trazer", "fim"])
        p = overlay.PrimeiraJanela(limite=3)
        self.assertEqual([p.passo(False, False) for _ in range(4)], ["esperar"] * 3 + ["fim"])

    def test_overlay_starts_it_on_windows(self):
        codigo = (Path(__file__).resolve().parent.parent / "src" / "overlay.py").read_text(encoding="utf-8")
        self.assertIn("self.trazer_app_quando_abrir(PrimeiraJanela())", codigo)
        # a pílula na frente (a criança arrastando) também conta como "app na frente"
        self.assertIn("frente in pids or frente == os.getpid()", codigo)


if __name__ == "__main__":
    unittest.main()
