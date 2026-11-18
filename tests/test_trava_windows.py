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

NORMAL = trava.ABS_ALWAYSONTOP  # barra comum, sempre visível


# StuckRects3 "Settings" de um Windows 10 de verdade (barra embaixo, 2560x1080, fixa):
# 48 bytes; os 4 primeiros são o tamanho (0x30) e o byte 8 tem as opções (0x02 fixa,
# 0x03 com "ocultar automaticamente").
STUCKRECTS_FIXA = bytes.fromhex(
    "30000000feffffff0200000003000000"
    "3e000000280000000000000010040000"
    "000a0000380400006000000001000000")


def stuckrects(autohide):
    return trava.com_autohide_no_registro(STUCKRECTS_FIXA, autohide)


class WindowsDeMentira:
    """Um Explorer de mentira. O registro (StuckRects3) só muda quando o Explorer grava a
    cópia dele: `contaminado` imita o Explorer reiniciado do roteiro 26, que gravou o
    "ocultar automaticamente" do Benikids quando a barra foi devolvida."""

    def __init__(self, barras=("principal",), estado=NORMAL, registro="igual", idade=3600.0):
        self.visiveis = {b: True for b in barras}
        self.bits = estado
        self.chamadas = []
        if registro == "igual":
            registro = stuckrects(bool((estado or 0) & trava.ABS_AUTOHIDE))
        self.reg = registro
        self.idade = idade
        self.contaminado = False
        self.reiniciado = 0

    def registro(self):
        return self.reg

    def gravar_registro(self, dados):
        self.chamadas.append(("registro", dados[8]))
        self.reg = dados

    def idade_do_explorer(self):
        return self.idade

    def reiniciar_explorer(self):
        self.reiniciado += 1
        self.contaminado = False

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
        if self.contaminado and self.reg:
            self.reg = stuckrects(True)  # o Explorer grava a cópia errada

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
        dormir = mock.patch.object(trava.time, "sleep")
        dormir.start()
        self.addCleanup(dormir.stop)
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

    def test_new_explorer_is_hidden_again_and_autohide_comes_back_by_itself(self):
        # roteiro 25: o Explorer novo volta com a barra fixa (ABM_GETSTATE 0); a
        # conferência periódica precisa esconder e religar mesmo sem o TaskbarCreated
        log = []
        win = WindowsDeMentira()
        barra = trava.Barra(win, self.arquivo, log.append)
        barra.esconder()
        self.assertFalse(barra.manter())  # nada mudou
        win.visiveis = {"nova": True}
        win.bits = None  # o Explorer novo ainda não responde
        self.assertTrue(barra.manter())
        self.assertEqual(win.visiveis, {"nova": False})
        self.assertIn("barra: Explorer voltou; escondida de novo", log)
        self.assertTrue(barra.religar)
        win.bits = NORMAL  # respondeu, com o "ocultar automaticamente" desligado
        self.assertFalse(barra.manter())
        self.assertEqual(win.bits, NORMAL | trava.ABS_AUTOHIDE)
        self.assertFalse(barra.religar)
        chamadas = len(win.chamadas)
        barra.manter()
        self.assertEqual(len(win.chamadas), chamadas)  # e não fica mexendo à toa
        barra.restaurar()
        self.assertEqual(win.bits, NORMAL)

    def test_taskbar_created_turns_autohide_back_on_right_away(self):
        win = WindowsDeMentira()
        barra = trava.Barra(win, self.arquivo)
        barra.esconder()
        win.visiveis, win.bits = {"nova": True}, NORMAL
        barra.explorer_voltou()
        self.assertEqual(win.visiveis, {"nova": False})
        self.assertEqual(win.bits, NORMAL | trava.ABS_AUTOHIDE)

    def test_second_screen_at_start_is_not_taken_for_a_new_explorer(self):
        log = []
        barra = trava.Barra(WindowsDeMentira(barras=("principal", "segunda")), self.arquivo, log.append)
        barra.esconder()
        self.assertNotIn("barra: Explorer voltou; escondida de novo", log)

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


class PreferenciaGravadaTests(unittest.TestCase):
    """Roteiro 26: depois de um Explorer reiniciado com o Benikids aberto, o Sair deixava o
    StuckRects3 com 0x03 (ocultar automaticamente) no lugar do 0x02 do usuário."""

    def setUp(self):
        dormir = mock.patch.object(trava.time, "sleep")
        dormir.start()
        self.addCleanup(dormir.stop)
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.arquivo = os.path.join(self.pasta.name, "barra-escondida.json")

    def test_only_bit_one_of_byte_eight_changes(self):
        self.assertIs(trava.autohide_no_registro(STUCKRECTS_FIXA), False)
        ligado = trava.com_autohide_no_registro(STUCKRECTS_FIXA, True)
        self.assertEqual(ligado[8], 0x03)
        self.assertEqual(ligado[:8] + ligado[9:], STUCKRECTS_FIXA[:8] + STUCKRECTS_FIXA[9:])
        self.assertIs(trava.autohide_no_registro(ligado), True)
        self.assertEqual(trava.com_autohide_no_registro(ligado, False), STUCKRECTS_FIXA)
        self.assertEqual(trava.com_autohide_no_registro(STUCKRECTS_FIXA, False), STUCKRECTS_FIXA)

    def test_unknown_format_is_never_read_or_written(self):
        for dados in (None, b"", STUCKRECTS_FIXA[:40], b"\x28" + STUCKRECTS_FIXA[1:], "texto"):
            self.assertIsNone(trava.autohide_no_registro(dados))
        win = WindowsDeMentira(registro=STUCKRECTS_FIXA[:40])
        barra = trava.Barra(win, self.arquivo)
        barra.esconder()
        barra.restaurar()
        self.assertNotIn("registro", [c[0] for c in win.chamadas])
        self.assertEqual(win.bits, NORMAL)

    def test_the_saved_preference_wins_over_a_leftover_autohide(self):
        # o "ocultar automaticamente" de agora sobrou de um Benikids; o gravado é fixa
        log = []
        win = WindowsDeMentira(estado=NORMAL | trava.ABS_AUTOHIDE, registro=stuckrects(False))
        barra = trava.Barra(win, self.arquivo, log.append)
        barra.esconder()
        self.assertEqual(barra.original, NORMAL)
        self.assertTrue(any("vale a gravada" in linha for linha in log))
        barra.restaurar()
        self.assertEqual(win.bits, NORMAL)
        self.assertEqual(win.reg, stuckrects(False))

    def test_a_user_who_chose_autohide_keeps_it(self):
        win = WindowsDeMentira(estado=NORMAL | trava.ABS_AUTOHIDE)
        barra = trava.Barra(win, self.arquivo)
        barra.esconder()
        barra.restaurar()
        self.assertEqual(win.bits, NORMAL | trava.ABS_AUTOHIDE)
        self.assertEqual(win.reg, stuckrects(True))
        self.assertEqual(win.reiniciado, 0)

    def test_autohide_waits_for_a_young_explorer(self):
        log = []
        win = WindowsDeMentira(idade=3.0)  # Benikids abriu junto com o Windows
        barra = trava.Barra(win, self.arquivo, log.append)
        barra.esconder()
        self.assertEqual(win.visiveis, {"principal": False})  # a barra some já
        self.assertEqual(win.bits, NORMAL)  # o autohide espera
        self.assertTrue(any("espera" in linha for linha in log))
        win.idade = 11.9
        barra.manter()
        self.assertEqual(win.bits, NORMAL)
        win.idade = 12.5
        barra.manter()
        self.assertEqual(win.bits, NORMAL | trava.ABS_AUTOHIDE)

    def test_restarted_explorer_gets_autohide_only_after_it_settles(self):
        win = WindowsDeMentira()
        barra = trava.Barra(win, self.arquivo)
        barra.esconder()
        win.visiveis, win.bits, win.idade = {"nova": True}, NORMAL, 1.3
        barra.explorer_voltou()
        barra.manter()
        self.assertEqual(win.visiveis, {"nova": False})
        self.assertEqual(win.bits, NORMAL)
        win.idade = 13.0
        barra.manter()
        self.assertEqual(win.bits, NORMAL | trava.ABS_AUTOHIDE)

    def test_exit_fixes_the_registry_and_restarts_explorer_when_it_saved_our_autohide(self):
        log = []
        win = WindowsDeMentira()
        barra = trava.Barra(win, self.arquivo, log.append)
        barra.esconder()
        win.contaminado = True  # o Explorer gravaria o autohide do Benikids
        barra.restaurar()
        self.assertEqual(win.bits, NORMAL)
        self.assertEqual(win.reg, STUCKRECTS_FIXA)
        self.assertEqual(win.reiniciado, 1)
        self.assertTrue(any("preferência devolvida no registro" in linha for linha in log))

    def test_clean_exit_does_not_touch_the_registry_or_explorer(self):
        win = WindowsDeMentira()
        barra = trava.Barra(win, self.arquivo)
        barra.esconder()
        barra.restaurar()
        self.assertNotIn("registro", [c[0] for c in win.chamadas])
        self.assertEqual(win.reiniciado, 0)
        self.assertEqual(win.reg, STUCKRECTS_FIXA)


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
