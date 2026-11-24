"""Tecla Windows e barra de tarefas presas enquanto o Benikids roda (src/trava_windows.py).

A parte do Windows (gancho de teclado, ShowWindow, SystemParametersInfo) só roda lá;
aqui ficam a decisão de cada tecla e o caminho de esconder e devolver a barra, com
um Windows de mentira."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import trava_windows as trava  # noqa: E402

class WindowsDeMentira:
    """Um Explorer de mentira que anota toda chamada: o Benikids só pode esconder e mostrar
    as barras, nunca mexer em preferência do usuário."""

    def __init__(self, barras=("principal",)):
        self.visiveis = {b: True for b in barras}
        self.chamadas = []

    def barras(self):
        return list(self.visiveis)

    def visivel(self, janela):
        return self.visiveis[janela]

    def esconder(self, janela):
        self.chamadas.append(("esconder", janela))
        self.visiveis[janela] = False

    def mostrar(self, janela):
        self.chamadas.append(("mostrar", janela))
        self.visiveis[janela] = True


class TeclasTests(unittest.TestCase):
    def test_windows_keys_never_reach_the_system(self):
        self.assertTrue(trava.engolir_tecla(trava.VK_LWIN))
        self.assertTrue(trava.engolir_tecla(trava.VK_RWIN))
        # com modificadores também (Ctrl+Win+D, Shift+Win+S...)
        self.assertTrue(trava.engolir_tecla(trava.VK_LWIN, ctrl=True, shift=True, alt=True))

    def test_ctrl_esc_opens_start_and_is_swallowed(self):
        self.assertTrue(trava.engolir_tecla(trava.VK_ESCAPE, ctrl=True))

    def test_escape_alone_alt_tab_and_task_manager_pass(self):
        self.assertFalse(trava.engolir_tecla(trava.VK_ESCAPE))  # Esc fecha o PIN, sai de jogos
        self.assertFalse(trava.engolir_tecla(trava.VK_ESCAPE, ctrl=True, shift=True))  # Gerenciador
        self.assertFalse(trava.engolir_tecla(0x09, alt=True))  # Alt+Tab leva ao menu
        self.assertFalse(trava.engolir_tecla(0x41))


class BarraTests(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.arquivo = os.path.join(self.pasta.name, "barra-escondida.json")

    def test_hides_every_taskbar_and_brings_them_back(self):
        win = WindowsDeMentira(barras=("principal", "segunda tela"))
        barra = trava.Barra(win, self.arquivo)
        barra.esconder()
        self.assertEqual(win.visiveis, {"principal": False, "segunda tela": False})
        self.assertTrue(os.path.exists(self.arquivo))
        barra.restaurar()
        self.assertEqual(win.visiveis, {"principal": True, "segunda tela": True})
        self.assertFalse(os.path.exists(self.arquivo))
        barra.restaurar()  # o atexit repete: não faz nada
        self.assertEqual(len(win.chamadas), 4)

    def test_no_user_preference_is_ever_touched(self):
        # roteiro 27: o "ocultar automaticamente" foi abandonado; só esconder e mostrar
        win = WindowsDeMentira()
        barra = trava.Barra(win, self.arquivo)
        barra.esconder()
        win.visiveis = {"nova": True}
        barra.explorer_voltou()
        barra.manter()
        barra.restaurar()
        self.assertEqual({c[0] for c in win.chamadas}, {"esconder", "mostrar"})
        codigo = Path(trava.__file__).read_text(encoding="utf-8").split('"""', 2)[2]  # sem a docstring
        for proibido in ("SHAppBarMessage", "ABM_SETSTATE", "StuckRects", "SPI_SETWORKAREA",
                         "SystemParametersInfo", "winreg"):
            self.assertNotIn(proibido, codigo)

    def test_taskbar_of_a_restarted_explorer_is_hidden_again(self):
        log = []
        win = WindowsDeMentira()
        barra = trava.Barra(win, self.arquivo, log.append)
        barra.esconder()
        self.assertFalse(barra.manter())
        win.visiveis = {"nova": True}
        self.assertTrue(barra.manter())
        self.assertEqual(win.visiveis, {"nova": False})
        self.assertIn("barra: Explorer voltou; escondida de novo", log)
        self.assertFalse(barra.manter())
        win.visiveis["nova"] = True  # o Explorer mostra a mesma barra de novo ao subir
        barra.explorer_voltou()
        self.assertEqual(win.visiveis, {"nova": False})

    def test_second_screen_at_start_is_not_taken_for_a_new_explorer(self):
        log = []
        trava.Barra(WindowsDeMentira(barras=("principal", "segunda")), self.arquivo, log.append).esconder()
        self.assertNotIn("barra: Explorer voltou; escondida de novo", log)

    def test_marker_left_by_a_crash_is_noticed_and_any_old_content_is_fine(self):
        for conteudo in ('{"estado": 3}', "{quebrado", '{"escondida": true}'):
            Path(self.arquivo).write_text(conteudo)
            log = []
            win = WindowsDeMentira()
            win.visiveis["principal"] = False  # a queda deixou a barra escondida
            barra = trava.Barra(win, self.arquivo, log.append)
            barra.esconder()
            self.assertTrue(any("não mostrou a barra" in linha for linha in log), conteudo)
            barra.restaurar()
            self.assertEqual(win.visiveis, {"principal": True})
            self.assertFalse(os.path.exists(self.arquivo))

    def test_crash_marker_is_quiet_when_the_explorer_already_brought_the_bar_back(self):
        Path(self.arquivo).write_text('{"escondida": true}')
        log = []
        win = WindowsDeMentira()  # Explorer reiniciado depois da queda: barra visível
        trava.Barra(win, self.arquivo, log.append).esconder()
        self.assertFalse(any("não mostrou a barra" in linha for linha in log))

    def test_window_events_that_mean_a_taskbar_is_showing(self):
        for ev in (trava.EVENT_OBJECT_CREATE, trava.EVENT_OBJECT_SHOW):
            for classe in trava.CLASSES_DA_BARRA:
                self.assertTrue(trava.evento_da_barra(ev, 0, 0, classe))
        self.assertFalse(trava.evento_da_barra(0x8001, 0, 0, "Shell_TrayWnd"))  # DESTROY
        self.assertFalse(trava.evento_da_barra(trava.EVENT_OBJECT_SHOW, -4, 0, "Shell_TrayWnd"))  # cursor, menu...
        self.assertFalse(trava.evento_da_barra(trava.EVENT_OBJECT_SHOW, 0, 3, "Shell_TrayWnd"))  # um botão dela
        self.assertFalse(trava.evento_da_barra(trava.EVENT_OBJECT_SHOW, 0, 0, "Qt662QWindowIcon"))

    def test_nothing_to_restore_when_it_never_hid(self):
        win = WindowsDeMentira()
        trava.Barra(win, self.arquivo).restaurar()
        self.assertEqual(win.chamadas, [])

    def test_lock_is_off_outside_windows(self):
        t = trava.Trava(self.arquivo)
        if os.name != "nt":
            t.ligar()
            self.assertEqual(t.threads, {})
        t.desligar()


class FocoTests(unittest.TestCase):
    def test_focus_stuck_on_the_desktop_goes_back_to_the_last_window(self):
        # roteiro 24: depois do Explorer reiniciar, o foco ficava no Progman atrás do menu
        foco = trava.Foco()
        existe = lambda _j: True  # noqa: E731
        self.assertIsNone(foco.passo("menu", "Zed::Window", existe))
        self.assertIsNone(foco.passo("desk", "Progman", existe))  # espera uma volta
        self.assertEqual(foco.passo("desk", "Progman", existe), "menu")

    def test_taskbar_and_workerw_count_as_outside(self):
        for classe in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd", "WorkerW"):
            foco = trava.Foco()
            foco.passo("app", "SDL_app", lambda _j: True)
            foco.passo("x", classe, lambda _j: True)
            self.assertEqual(foco.passo("x", classe, lambda _j: True), "app", classe)

    def test_quick_switch_and_closed_windows_are_left_alone(self):
        foco = trava.Foco()
        foco.passo("app", "SDL_app", lambda _j: True)
        self.assertIsNone(foco.passo("desk", "Progman", lambda _j: True))
        self.assertIsNone(foco.passo("menu", "Zed::Window", lambda _j: True))  # foi só de passagem
        self.assertIsNone(foco.passo("desk", "Progman", lambda _j: True))
        # a última janela fechou: não há para onde devolver
        self.assertIsNone(foco.passo("desk", "Progman", lambda _j: False))
        # nada na frente (troca em andamento) não conta
        foco2 = trava.Foco()
        foco2.passo("app", "SDL_app", lambda _j: True)
        self.assertIsNone(foco2.passo(None, "", lambda _j: True))
        self.assertIsNone(foco2.passo(None, "", lambda _j: True))


    def test_right_after_explorer_restarts_no_window_in_front_also_counts(self):
        foco = trava.Foco()
        foco.passo("menu", "Zed::Window", lambda _j: True)
        self.assertIsNone(foco.passo(None, "", lambda _j: True, vazio_conta=True))
        self.assertEqual(foco.passo(None, "", lambda _j: True, vazio_conta=True), "menu")


class ThreadsTests(unittest.TestCase):
    def test_thread_timer_reads_the_real_msg_field(self):
        # pacote 22: msg.hwnd não existe no wintypes.MSG (é hWnd); o AttributeError no
        # primeiro WM_TIMER matava a thread da barra sem deixar rastro
        from ctypes import wintypes

        msg = wintypes.MSG()
        msg.message = trava.WM_TIMER
        self.assertTrue(trava.timer_da_thread(msg))
        msg.hWnd = 1234
        self.assertFalse(trava.timer_da_thread(msg))
        msg.hWnd, msg.message = None, 0x0100
        self.assertFalse(trava.timer_da_thread(msg))
        codigo = Path(trava.__file__).read_text(encoding="utf-8")
        self.assertNotIn("msg.hwnd", codigo)

    def test_a_thread_that_dies_leaves_its_reason_in_the_log(self):
        import threading

        log = []
        t = trava.Trava("x", log.append)
        t.threads["barra"] = [None, 0]
        pronta = threading.Event()

        def quebra(_pronta):
            raise AttributeError("hwnd")

        t._rodar("barra", quebra, pronta)
        self.assertTrue(pronta.is_set())
        self.assertTrue(any("a thread caiu: AttributeError: hwnd" in linha for linha in log))
        self.assertIn("trava (barra): parou", log)

    def test_the_same_error_is_logged_once(self):
        log = []
        erro_de = trava.LogDeErro(log.append)
        for _ in range(3):
            erro_de("barra", OSError(5, "negado"))
        erro_de("foco", OSError(5, "negado"))
        self.assertEqual(len(log), 2)


class IniciadorTests(unittest.TestCase):
    def test_launcher_turns_the_lock_on_and_always_off(self):
        codigo = Path(__file__).resolve().parents[1].joinpath("src", "beni_windows.py").read_text(encoding="utf-8")
        self.assertIn("atexit.register(trava.desligar)", codigo)
        fim = codigo[codigo.index("    finally:\n        encerrar_tudo"):]
        self.assertIn("trava.desligar()", fim)
        # só a instância que fica: a segunda só traz o menu para a frente
        self.assertGreater(codigo.index("trava.ligar()"), codigo.index("instancia_unica("))


if __name__ == "__main__":
    unittest.main()
