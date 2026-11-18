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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import trava_windows as trava  # noqa: E402

NORMAL = trava.ABS_ALWAYSONTOP  # barra comum, sempre visível


class WindowsDeMentira:
    def __init__(self, barras=("principal",), estado=NORMAL):
        self.visiveis = {b: True for b in barras}
        self.bits = estado
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

    def estado(self):
        return self.bits

    def definir_estado(self, bits):
        self.chamadas.append(("estado", bits))
        self.bits = bits


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
        self.arquivo = os.path.join(self.pasta.name, "barra-escondida.json")

    def tearDown(self):
        self.pasta.cleanup()

    def test_hides_every_taskbar_and_turns_on_autohide(self):
        # roteiro 24: gravar a área de trabalho não segurava (o Explorer a reescrevia);
        # com "ocultar automaticamente" é o próprio Explorer que dá a tela toda aos apps
        win = WindowsDeMentira(barras=("principal", "segunda tela"))
        barra = trava.Barra(win, self.arquivo)
        barra.esconder()
        self.assertEqual(win.visiveis, {"principal": False, "segunda tela": False})
        self.assertEqual(win.bits, NORMAL | trava.ABS_AUTOHIDE)
        self.assertEqual(json.loads(Path(self.arquivo).read_text())["estado"], NORMAL)

    def test_exit_brings_back_the_taskbar_and_the_users_setting(self):
        win = WindowsDeMentira()
        barra = trava.Barra(win, self.arquivo)
        barra.esconder()
        barra.restaurar()
        self.assertEqual(win.visiveis, {"principal": True})
        self.assertEqual(win.bits, NORMAL)
        self.assertFalse(os.path.exists(self.arquivo))
        # de novo (finally + atexit): não faz nada
        chamadas = len(win.chamadas)
        barra.restaurar()
        self.assertEqual(len(win.chamadas), chamadas)

    def test_user_who_already_hid_the_taskbar_keeps_it_that_way(self):
        win = WindowsDeMentira(estado=trava.ABS_AUTOHIDE)
        barra = trava.Barra(win, self.arquivo)
        barra.esconder()
        self.assertNotIn(("estado", trava.ABS_AUTOHIDE), win.chamadas[:1])
        barra.restaurar()
        self.assertEqual(win.bits, trava.ABS_AUTOHIDE)

    def test_taskbar_that_comes_back_is_hidden_again(self):
        win = WindowsDeMentira()
        barra = trava.Barra(win, self.arquivo)
        barra.esconder()
        # Explorer reiniciado: barra nova, visível
        win.visiveis = {"nova": True}
        self.assertTrue(barra.vigiar())
        self.assertEqual(win.visiveis, {"nova": False})
        self.assertFalse(barra.vigiar())
        # e se ele voltou sem o "ocultar automaticamente", liga de novo
        win.bits = NORMAL
        barra.ocultar_automaticamente()
        self.assertEqual(win.bits, NORMAL | trava.ABS_AUTOHIDE)

    def test_after_a_crash_the_next_start_restores_the_saved_setting(self):
        Path(self.arquivo).write_text(json.dumps({"estado": NORMAL}))
        win = WindowsDeMentira(estado=NORMAL | trava.ABS_AUTOHIDE)  # o anterior caiu com ele ligado
        barra = trava.Barra(win, self.arquivo)
        barra.esconder()
        barra.restaurar()
        self.assertEqual(win.bits, NORMAL)
        self.assertEqual(win.visiveis, {"principal": True})

    def test_broken_or_old_saved_file_falls_back_to_the_current_setting(self):
        for conteudo in ("{quebrado", json.dumps({"area": [0, 0, 2560, 1040]}), json.dumps({"estado": True})):
            Path(self.arquivo).write_text(conteudo)
            win = WindowsDeMentira()
            barra = trava.Barra(win, self.arquivo)
            barra.esconder()
            barra.restaurar()
            self.assertEqual(win.bits, NORMAL, conteudo)

    def test_explorer_missing_at_start_is_saved_when_it_arrives(self):
        win = WindowsDeMentira(barras=())
        win.bits = None
        barra = trava.Barra(win, self.arquivo)
        barra.esconder()
        self.assertFalse(os.path.exists(self.arquivo))
        win.bits = NORMAL  # TaskbarCreated
        win.visiveis = {"nova": True}
        barra.vigiar()
        barra.ocultar_automaticamente()
        self.assertEqual(win.bits, NORMAL | trava.ABS_AUTOHIDE)
        self.assertEqual(json.loads(Path(self.arquivo).read_text())["estado"], NORMAL)
        barra.restaurar()
        self.assertEqual(win.bits, NORMAL)

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
