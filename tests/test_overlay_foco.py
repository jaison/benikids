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
