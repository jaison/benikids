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

TELA = [0, 0, 2560, 1080]
COM_BARRA = [0, 0, 2560, 1040]


class WindowsDeMentira:
    def __init__(self, barras=("principal",), area=COM_BARRA):
        self.visiveis = {b: True for b in barras}
        self.area = list(area)
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

    def area_de_trabalho(self):
        return list(self.area)

    def definir_area(self, area):
        self.chamadas.append(("area", list(area)))
        self.area = list(area)

    def tela(self):
        return list(TELA)


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

    def test_hides_every_taskbar_and_gives_apps_the_whole_screen(self):
        win = WindowsDeMentira(barras=("principal", "segunda tela"))
        barra = trava.Barra(win, self.arquivo)
        barra.esconder()
        self.assertEqual(win.visiveis, {"principal": False, "segunda tela": False})
        self.assertEqual(win.area, TELA)
        self.assertEqual(json.loads(Path(self.arquivo).read_text())["area"], COM_BARRA)

    def test_exit_brings_back_the_taskbar_and_the_original_work_area(self):
        win = WindowsDeMentira()
        barra = trava.Barra(win, self.arquivo)
        barra.esconder()
        barra.restaurar()
        self.assertEqual(win.visiveis, {"principal": True})
        self.assertEqual(win.area, COM_BARRA)
        self.assertFalse(os.path.exists(self.arquivo))
        # de novo (finally + atexit): não faz nada
        chamadas = len(win.chamadas)
        barra.restaurar()
        self.assertEqual(len(win.chamadas), chamadas)

    def test_taskbar_that_comes_back_is_hidden_again(self):
        win = WindowsDeMentira()
        barra = trava.Barra(win, self.arquivo)
        barra.esconder()
        # Explorer reiniciado: barra nova, visível, e a área de trabalho recalculada
        win.visiveis = {"nova": True}
        win.area = list(COM_BARRA)
        barra.vigiar()
        self.assertEqual(win.visiveis, {"nova": False})
        self.assertEqual(win.area, TELA)

    def test_after_a_crash_the_next_start_restores_the_saved_area(self):
        Path(self.arquivo).write_text(json.dumps({"area": COM_BARRA}))
        win = WindowsDeMentira(area=TELA)  # o anterior caiu e deixou a tela inteira
        barra = trava.Barra(win, self.arquivo)
        barra.esconder()
        barra.restaurar()
        self.assertEqual(win.area, COM_BARRA)
        self.assertEqual(win.visiveis, {"principal": True})

    def test_broken_saved_file_falls_back_to_the_current_area(self):
        Path(self.arquivo).write_text("{quebrado")
        win = WindowsDeMentira()
        barra = trava.Barra(win, self.arquivo)
        barra.esconder()
        barra.restaurar()
        self.assertEqual(win.area, COM_BARRA)

    def test_nothing_to_restore_when_it_never_hid(self):
        win = WindowsDeMentira()
        trava.Barra(win, self.arquivo).restaurar()
        self.assertEqual(win.chamadas, [])

    def test_lock_is_off_outside_windows(self):
        t = trava.Trava(self.arquivo)
        if os.name != "nt":
            t.ligar()
            self.assertIsNone(t.thread)
        t.desligar()


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
