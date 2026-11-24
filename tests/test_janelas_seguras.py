"""Roteiro 31: a pílula travou junto com o Tux Paint (e o menu parou de pintar) por causa
do AttachThreadInput e de chamadas síncronas a uma janela de outro app."""
import re
import sys
import threading
import time
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

import janelas_seguras as js  # noqa: E402


class Falso:
    def __init__(self, travada=False, frente=0, iconica=False, visivel=True, direto=True, com_alt=True):
        self.chamadas = []
        self._travada, self._frente, self._iconica, self._visivel = travada, frente, iconica, visivel
        self.direto, self.com_alt, self.alt = direto, com_alt, False

    def travada(self, h):
        return self._travada

    def responde(self, h, ms):
        self.chamadas.append(("responde", ms))
        return True

    def frente(self):
        return self._frente

    def iconica(self, h):
        return self._iconica

    def visivel(self, h):
        return self._visivel

    def mostrar(self, h, sw):
        self.chamadas.append(("mostrar", sw))

    def primeiro_plano(self, h):
        self.chamadas.append(("primeiro_plano", self.alt))
        return self.com_alt if self.alt else self.direto

    def segurar_alt(self, apertar):
        self.alt = apertar
        self.chamadas.append(("alt", apertar))


class TrazerTests(unittest.TestCase):
    def test_hung_window_is_not_touched(self):
        f = Falso(travada=True)
        self.assertEqual(js.trazer(f, 0x10), "travada")
        self.assertEqual(f.chamadas, [])

    def test_already_in_front(self):
        f = Falso(frente=0x10)
        self.assertEqual(js.trazer(f, 0x10), "ja")
        self.assertEqual(f.chamadas, [])

    def test_direct_then_alt_trick_and_alt_is_always_released(self):
        f = Falso(direto=True)
        self.assertEqual(js.trazer(f, 0x10), "direto")
        self.assertNotIn(("alt", True), f.chamadas)
        f = Falso(direto=False)
        self.assertEqual(js.trazer(f, 0x10), "alt")
        self.assertEqual(f.chamadas[-3:], [("alt", True), ("primeiro_plano", True), ("alt", False)])
        f = Falso(direto=False, com_alt=False)
        self.assertEqual(js.trazer(f, 0x10), "falhou")
        self.assertEqual(f.chamadas[-1], ("alt", False))

    def test_minimized_window_is_restored_asynchronously(self):
        f = Falso(iconica=True)
        js.trazer(f, 0x10)
        self.assertIn(("mostrar", js.SW_RESTORE), f.chamadas)
        f = Falso()
        js.trazer(f, 0x10)
        self.assertFalse([c for c in f.chamadas if c[0] == "mostrar"])  # visível: nem mexe

    def test_style_changes_wait_for_a_short_ping_first(self):
        self.assertTrue(js.pode_mexer(Falso(), 0x10, 300))
        self.assertFalse(js.pode_mexer(Falso(travada=True), 0x10))
        self.assertFalse(js.pode_mexer(Falso(), 0))


class DePeTests(unittest.TestCase):
    """Roteiro 32: o Tux Paint travava no splash só quando aberto pelo Benikids. Nada na
    janela de outro app antes de ela estar de pé."""

    def montar(self):
        self.agora = [0.0]
        self.f = Falso()
        self.f.ocioso = lambda h: self.ocioso
        self.ocioso = True
        self.respostas = []
        self.f.responde = lambda h, ms: self.respostas.pop(0) if self.respostas else True
        return js.DePe(relogio=lambda: self.agora[0])

    def test_needs_2_s_of_answers_in_a_row(self):
        d = self.montar()
        for self.agora[0] in (0.0, 0.5, 1.0, 1.5):
            self.assertFalse(d.pronta(self.f, 0x10))
        self.agora[0] = 2.0
        self.assertTrue(d.pronta(self.f, 0x10))
        self.assertTrue(d.firme(0x10))
        self.respostas = [False]
        self.assertTrue(d.pronta(self.f, 0x10))  # de pé uma vez, fica

    def test_a_missed_answer_starts_the_count_again(self):
        d = self.montar()
        d.pronta(self.f, 0x10)
        self.agora[0] = 1.5
        self.respostas = [False]
        self.assertFalse(d.pronta(self.f, 0x10))
        self.agora[0] = 3.0
        self.assertFalse(d.pronta(self.f, 0x10))  # recomeçou em 3,0
        self.agora[0] = 5.0
        self.assertTrue(d.pronta(self.f, 0x10))

    def test_waits_for_input_idle_and_never_touches_a_hung_window(self):
        d = self.montar()
        self.ocioso = False
        d.pronta(self.f, 0x10)
        self.agora[0] = 10.0
        self.assertFalse(d.pronta(self.f, 0x10))
        self.ocioso = True
        self.assertTrue(d.pronta(self.f, 0x10))
        self.f._travada = True
        self.assertFalse(d.pronta(self.f, 0x10))  # travada: nunca, nem de pé
        self.assertFalse(d.pronta(self.f, 0))


class CliqueNoBotaoTests(unittest.TestCase):
    X = (20, 1017, 72, 1069)

    def test_press_and_release_on_the_button_over_the_pill(self):
        c = js.CliqueNoBotao()
        self.assertFalse(c.passo(True, (46, 1037), self.X, True))
        self.assertFalse(c.passo(True, (46, 1037), self.X, True))
        self.assertTrue(c.passo(False, (46, 1037), self.X, True))
        self.assertFalse(c.passo(False, (46, 1037), self.X, True))

    def test_not_a_click_on_the_x(self):
        c = js.CliqueNoBotao()
        c.passo(True, (500, 500), self.X, True)
        self.assertFalse(c.passo(False, (46, 1037), self.X, True))  # começou fora
        c.passo(True, (46, 1037), self.X, True)
        self.assertFalse(c.passo(False, (300, 1037), self.X, True))  # arrastou para fora
        c.passo(True, (46, 1037), self.X, False)
        self.assertFalse(c.passo(False, (46, 1037), self.X, False))  # outra janela por cima
        c.passo(True, (46, 1037), None, True)
        self.assertFalse(c.passo(False, (46, 1037), None, True))  # ✕ ainda sem posição


class TrabalhadorTests(unittest.TestCase):
    def test_a_stuck_call_never_blocks_whoever_asked(self):
        solta = threading.Event()
        erros = []
        t = js.Trabalhador("teste", ao_erro=lambda c, e: erros.append((c, e)))
        comeco = time.monotonic()
        self.assertTrue(t.pedir("trazer o app", solta.wait, 30))  # "preso" numa janela travada
        for _ in range(100):
            if t.preso():
                break
            time.sleep(0.01)
        self.assertLess(time.monotonic() - comeco, 2)
        self.assertEqual(t.preso()[0], "trazer o app")
        self.assertFalse(t.pedir("tela cheia", lambda: None))  # recusado: a pílula segue
        solta.set()
        for _ in range(100):
            if not t.preso():
                break
            time.sleep(0.01)
        self.assertTrue(t.pedir("tela cheia", lambda: None))
        self.assertEqual(erros, [])

    def test_errors_go_to_the_callback_and_the_next_task_runs(self):
        erros = []
        t = js.Trabalhador(ao_erro=lambda c, e: erros.append((c, type(e).__name__)), iniciar=False)
        t.pedir("tela cheia", lambda: 1 / 0)
        t.rodar_uma()
        feito = []
        t.pedir("trazer", feito.append, 1)
        t.rodar_uma()
        self.assertEqual(erros, [("tela cheia", "ZeroDivisionError")])
        self.assertEqual(feito, [1])

    def test_time_limited_call(self):
        comeco = time.monotonic()
        self.assertIsNone(js.rodar_com_limite(time.sleep, 0.2, 5))
        self.assertLess(time.monotonic() - comeco, 1)
        self.assertEqual(js.rodar_com_limite(lambda x: x * 2, 1, 21), 42)


class SemChamadaQuePrendeTests(unittest.TestCase):
    """Nenhum código do Benikids volta a ligar filas de entrada nem a chamar a versão
    síncrona do ShowWindow/BringWindowToTop (a regra do roteiro 31)."""

    ARQUIVOS = ["src/plataforma_windows.py", "src/overlay.py", "src/quiosque_edge.py", "src/trava_windows.py",
                "src/timer_watchdog.py", "src/beni_windows.py", "src/vigia_da_pilula.py",
                "cliente/src/menu.rs", "cliente/src/navegador.rs"]

    def test_no_attach_thread_input_or_synchronous_show(self):
        for nome in self.ARQUIVOS:
            codigo = (RAIZ / nome).read_text(encoding="utf-8")
            with self.subTest(nome):
                self.assertNotRegex(codigo, r"\bAttachThreadInput\(")
                self.assertNotRegex(codigo, r"\bShowWindow\(")
                self.assertNotRegex(codigo, r"\bBringWindowToTop\(")

    def test_overlay_only_touches_other_apps_from_the_worker(self):
        codigo = (RAIZ / "src" / "overlay.py").read_text(encoding="utf-8")
        self.assertNotRegex(codigo, r"win\.ativar_processo\(")
        self.assertEqual(len(re.findall(r"win\.trazer_para_frente\(", codigo)), 1)  # só no trazer_app (na thread de trabalho)
        self.assertEqual(len(re.findall(r"win\.maximizar\(", codigo)), 1)  # só no passo_maximizar (idem)
        self.assertIn("janelas_seguras.rodar_com_limite(win.ativar_processo, 1.0", codigo)
        self.assertIn('self.pedir_janela("tela cheia", self.passo_da_tela_cheia', codigo)
        self.assertIn('self.pedir_janela("voltar", self.voltar_no_app', codigo)
        self.assertIn('self.pedir_janela("maximizar", self.passo_maximizar', codigo)
        self.assertIn('self.pedir_janela("quiosque", self.passo_do_quiosque', codigo)
        self.assertNotRegex(codigo, r"\bSendMessageW\(")


if __name__ == "__main__":
    unittest.main()
