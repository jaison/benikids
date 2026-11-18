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


class TelaCheiaTests(unittest.TestCase):
    """Roteiro 28: esticar a janela maximizada não segurava (o app a devolvia em menos de
    100 ms). A janela maximizada do app vira tela cheia sem moldura."""

    def test_windows10_maximized_window_is_recognized(self):
        self.assertTrue(overlay.maximizada_na_area((-8, -8, 2568, 1048), TRABALHO, MONITOR))  # Kapman, KBlocks
        self.assertTrue(overlay.maximizada_na_area((0, 0, 2560, 1040), TRABALHO, MONITOR))  # sem moldura
        self.assertTrue(overlay.maximizada_na_area((52, -8, 2568, 1088), (60, 0, 2560, 1080), MONITOR))  # barra à esquerda
        mon2, trab2 = (2560, 0, 4480, 1080), (2560, 0, 4480, 1040)
        self.assertTrue(overlay.maximizada_na_area((2552, -8, 4488, 1048), trab2, mon2))  # segundo monitor

    def test_small_fullscreen_or_odd_windows_are_not(self):
        self.assertFalse(overlay.maximizada_na_area((600, 200, 1400, 800), TRABALHO, MONITOR))  # Klavaro, Quinze
        self.assertFalse(overlay.maximizada_na_area(MONITOR, TRABALHO, MONITOR))  # STK em tela cheia, o menu
        self.assertFalse(overlay.maximizada_na_area((-8, -8, 2568, 1088), MONITOR, MONITOR))  # sem faixa
        self.assertFalse(overlay.maximizada_na_area((-30, -30, 2590, 1070), TRABALHO, MONITOR))
        self.assertFalse(overlay.maximizada_na_area((0, 0, 2000, 1040), TRABALHO, MONITOR))

    def test_maximized_app_becomes_borderless_fullscreen_once(self):
        t = overlay.TelaCheia()
        self.assertEqual(t.passo("kapman", True, (-8, -8, 2568, 1048), TRABALHO, MONITOR, False), "tela_cheia")
        # depois: sem moldura, no tamanho do monitor (e já não está maximizada)
        for _ in range(5):
            self.assertIsNone(t.passo("kapman", False, MONITOR, TRABALHO, MONITOR, True))

    def test_window_that_is_not_maximized_is_left_alone(self):
        t = overlay.TelaCheia()
        self.assertIsNone(t.passo("quinze", False, (600, 200, 1400, 800), TRABALHO, MONITOR, False))
        self.assertIsNone(t.passo("klavaro", True, (600, 200, 1400, 800), TRABALHO, MONITOR, False))
        self.assertIsNone(t.passo("stk", False, MONITOR, TRABALHO, MONITOR, True))

    def test_app_that_undoes_it_gets_it_again_then_its_window_back(self):
        t = overlay.TelaCheia(limite=3)
        maximizada = (-8, -8, 2568, 1048)
        self.assertEqual(t.passo("pencil", True, maximizada, TRABALHO, MONITOR, False), "tela_cheia")
        self.assertEqual(t.passo("pencil", True, maximizada, TRABALHO, MONITOR, False), "tela_cheia")  # 1ª
        self.assertEqual(t.passo("pencil", False, MONITOR, TRABALHO, MONITOR, False), "tela_cheia")  # moldura voltou
        self.assertEqual(t.passo("pencil", True, maximizada, TRABALHO, MONITOR, False), "desistir")
        self.assertIsNone(t.passo("pencil", True, maximizada, TRABALHO, MONITOR, False))  # fica como o app quer
        self.assertEqual(t.passo("outra", True, maximizada, TRABALHO, MONITOR, False), "tela_cheia")


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
        # roteiro 28: a pílula na frente NÃO é o app na frente (ela nem pega mais o foco)
        self.assertIn("estado.passo(bool(pids) and bool(win.janelas_de(pids)), frente in pids)", codigo)
        self.assertNotIn("frente == os.getpid()", codigo)


class PilulaSemFocoTests(unittest.TestCase):
    def test_every_overlay_window_is_made_non_activating_on_windows(self):
        janela = mock.Mock()
        janela.wm_frame.return_value = "0x1234"
        falso = mock.Mock()
        with mock.patch.object(overlay, "WINDOWS", True), mock.patch.object(overlay, "win", falso, create=True):
            overlay.configure_overlay_window(janela)
        falso.nao_ativavel.assert_called_once_with(0x1234)
        janela.focus_force.assert_not_called()

    def test_nothing_changes_outside_windows(self):
        janela = mock.Mock()
        with mock.patch.object(overlay, "WINDOWS", False):
            overlay.configure_overlay_window(janela)
        janela.wm_frame.assert_not_called()


if __name__ == "__main__":
    unittest.main()
