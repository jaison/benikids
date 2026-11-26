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

    def test_tux_paint_screen_sized_window_is_left_as_it_is(self):
        """Roteiro 32: o Tux Paint com --windowsize 2560x1080 fica (-3,-26,2563,1083), com
        o título para fora. A regra do roteiro 31 que o deixava sem moldura saiu (o SDL
        desfazia, e é a 1ª suspeita do travamento no splash)."""
        t = overlay.TelaCheia()
        for _ in range(5):
            self.assertIsNone(t.passo("tux", False, (-3, -26, 2563, 1083), TRABALHO, MONITOR, False))
        self.assertFalse(hasattr(overlay, "moldura_para_fora"))
        # sem moldura e do tamanho do monitor (STK, o menu): nada
        self.assertIsNone(overlay.TelaCheia().passo("stk", False, MONITOR, TRABALHO, MONITOR, True))

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


class DePeFalso:
    """Janela de pé (responde e o processo está ocioso)."""

    def __init__(self, responde=True):
        self._responde = responde

    def travada(self, _h):
        return False

    def responde(self, _h, _ms):
        return self._responde

    def ocioso(self, _h):
        return True


class EsticarAppTests(unittest.TestCase):
    """Roda o esticar_app de verdade (com um Windows de mentira) e confere o log: no
    roteiro 29 ele chamava log_windows, que não existia, e o NameError matava a volta."""

    def rodar(self, voltas):
        import tempfile

        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        falso = mock.Mock()
        falso.janelas_de.return_value = ["kapman"]
        estado = {"zoom": True, "ret": (-8, -8, 2568, 1048), "sem": False}
        falso.esta_maximizada.side_effect = lambda _h: estado["zoom"]
        falso.retangulo.side_effect = lambda _h: estado["ret"]
        falso.areas_do_monitor.return_value = (TRABALHO, MONITOR)
        falso.sem_moldura.side_effect = lambda _h: estado["sem"]
        falso.travada.side_effect = lambda _h: estado.get("travada", False)

        def aplicar(_h, monitor):
            estado.update(zoom=False, ret=monitor, sem=True)
            return 0x16CF0000

        falso.tela_cheia_sem_moldura.side_effect = aplicar
        falso.JANELAS = DePeFalso()
        o = overlay.AppOverlay.__new__(overlay.AppOverlay)
        o.closing, o.erros_logados = False, set()
        o.de_pe = overlay.janelas_seguras.DePe(segundos=0)
        o.trabalho = overlay.janelas_seguras.Trabalhador(iniciar=False, ao_erro=o.erro_no_trabalho)
        agendados = []
        o.root = mock.Mock()
        o.root.after.side_effect = lambda _ms, f: agendados.append(f)
        with mock.patch.object(overlay, "win", falso, create=True), \
                mock.patch.object(overlay, "CACHE_DIR", pasta.name), \
                mock.patch.object(overlay, "owned_process", return_value={"pid": 10}):
            o.esticar_app(overlay.TelaCheia(limite=2))
            o.trabalho.rodar_uma()  # a volta roda na thread de trabalho, não na do Tk
            for passo in voltas:
                passo(estado)
                agendados.pop(0)()
                o.trabalho.rodar_uma()
            log = Path(pasta.name, "beni-windows.log").read_text(encoding="utf-8")
        return falso, log, agendados

    def test_first_time_logs_and_keeps_going(self):
        falso, log, agendados = self.rodar([lambda _e: None])
        falso.tela_cheia_sem_moldura.assert_called_once_with("kapman", MONITOR)
        self.assertIn("overlay: app em tela cheia sem moldura", log)
        # roteiro 32: a ação é logada ANTES, com milissegundos
        linhas = log.splitlines()
        antes = [i for i, linha in enumerate(linhas) if "vou tirar a moldura (hwnd kapman)" in linha]
        self.assertTrue(antes and antes[0] < [i for i, linha in enumerate(linhas) if "sem moldura" in linha][-1])
        self.assertRegex(linhas[0], r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} overlay: ")
        self.assertEqual(len(agendados), 1)  # a volta seguinte continua marcada
        self.assertNotIn("erro", log)

    def test_app_that_undoes_it_is_redone_then_given_back(self):
        def desfaz(estado):
            estado.update(zoom=True, ret=(-8, -8, 2568, 1048), sem=False)

        falso, log, _ = self.rodar([desfaz, desfaz])
        self.assertIn("refeita", log)
        self.assertIn("devolvida a janela como era", log)
        self.assertIn("vou devolver a moldura (hwnd kapman)", log)
        falso.devolver_moldura.assert_called_once_with("kapman", 0x16CF0000, (-8, -8, 2568, 1048))

    def test_hung_app_is_not_touched_and_the_turn_does_not_count(self):
        def trava(estado):
            estado.update(zoom=True, ret=(-8, -8, 2568, 1048), sem=False, travada=True)

        falso, log, _ = self.rodar([trava, trava, trava])
        falso.tela_cheia_sem_moldura.assert_called_once()  # só a 1ª, antes de travar
        falso.devolver_moldura.assert_not_called()
        self.assertNotIn("refeita", log)

    def test_app_that_does_not_answer_the_ping_is_left_for_the_next_turn(self):
        def nao_responde(_h, _monitor):
            return None

        import tempfile

        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        falso = mock.Mock()
        falso.janelas_de.return_value = ["kapman"]
        falso.travada.return_value = False
        falso.esta_maximizada.return_value = True
        falso.retangulo.return_value = (-8, -8, 2568, 1048)
        falso.JANELAS = DePeFalso()
        falso.areas_do_monitor.return_value = (TRABALHO, MONITOR)
        falso.sem_moldura.return_value = False
        falso.tela_cheia_sem_moldura.side_effect = nao_responde
        o = overlay.AppOverlay.__new__(overlay.AppOverlay)
        o.erros_logados = set()
        o.de_pe = overlay.janelas_seguras.DePe(segundos=0)
        t = overlay.TelaCheia()
        with mock.patch.object(overlay, "win", falso, create=True), \
                mock.patch.object(overlay, "CACHE_DIR", pasta.name), \
                mock.patch.object(overlay, "owned_process", return_value={"pid": 10}):
            o.passo_da_tela_cheia(t, {})
        self.assertEqual(t.feitas, {})  # tenta de novo como se fosse a 1ª vez
        self.assertIn("não tirei a moldura (hwnd kapman): o app não respondeu",
                      Path(pasta.name, "beni-windows.log").read_text(encoding="utf-8"))

    def test_window_that_just_appeared_is_not_touched_for_2_s(self):
        """Roteiro 32: nada na janela antes de ela estar de pé (2 s respondendo)."""
        import tempfile

        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        agora = [0.0]
        falso = mock.Mock()
        falso.janelas_de.return_value = ["kapman"]
        falso.travada.return_value = False
        falso.esta_maximizada.return_value = True
        falso.retangulo.return_value = (-8, -8, 2568, 1048)
        falso.areas_do_monitor.return_value = (TRABALHO, MONITOR)
        falso.sem_moldura.return_value = False
        falso.tela_cheia_sem_moldura.return_value = 0x16CF0000
        falso.JANELAS = DePeFalso()
        o = overlay.AppOverlay.__new__(overlay.AppOverlay)
        o.erros_logados = set()
        o.de_pe = overlay.janelas_seguras.DePe(relogio=lambda: agora[0])
        t = overlay.TelaCheia()
        with mock.patch.object(overlay, "win", falso, create=True), \
                mock.patch.object(overlay, "CACHE_DIR", pasta.name), \
                mock.patch.object(overlay, "owned_process", return_value={"pid": 10}):
            for agora[0] in (0.0, 1.0, 1.9):
                o.passo_da_tela_cheia(t, {})
            falso.retangulo.assert_not_called()
            falso.tela_cheia_sem_moldura.assert_not_called()
            agora[0] = 2.0
            o.passo_da_tela_cheia(t, {})
        falso.tela_cheia_sem_moldura.assert_called_once()

    def test_an_unexpected_error_is_logged_once_and_the_loop_survives(self):
        def quebra(_estado):
            overlay.win.retangulo.side_effect = NameError("x")

        _falso, log, agendados = self.rodar([quebra, lambda _e: None])
        self.assertEqual(log.count("overlay: erro na tela cheia: NameError: x"), 1)
        self.assertEqual(len(agendados), 1)


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

    def test_paused_learning_asks_to_move(self):
        uso = {"restante": 28 * 60, "limite": 30 * 60, "emoji": "📚", "pausado": True}
        timer = {"restante": 40 * 60, "expirado": False, "aviso": False}
        self.assertEqual(overlay.rotulo_da_pilula(uso, timer, "cor"), ("⏸ mexa para contar", "cor"))
        fim = {"restante": 0, "expirado": True, "aviso": False}
        self.assertEqual(overlay.rotulo_da_pilula(uso, fim, "cor")[0], "⏰ Acabou!")


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
        self.assertIn("acao = estado.passo(de_pe, frente in pids)", codigo)
        self.assertNotIn("frente == os.getpid()", codigo)


class TrazerSemTravarTests(unittest.TestCase):
    """Roteiro 31: a pílula travou junto com o Tux Paint ao trazê-lo para a frente."""

    def montar(self, travada):
        falso = mock.Mock()
        falso.arvore.return_value = [10, 11]
        falso.janelas_de.return_value = [0x77]
        falso.travada.return_value = travada
        falso.pid_da_janela_ativa.return_value = 999  # o menu na frente
        o = overlay.AppOverlay.__new__(overlay.AppOverlay)
        o.erros_logados = set()
        o.trabalho = mock.Mock()
        o.trabalho.pedir.return_value = True
        o.root = mock.Mock()
        o.de_pe = overlay.janelas_seguras.DePe()
        return falso, o

    def test_hung_app_is_not_brought_and_the_turn_does_not_count(self):
        falso, o = self.montar(travada=True)
        estado = overlay.PrimeiraJanela()
        with mock.patch.object(overlay, "win", falso, create=True), \
                mock.patch.object(overlay, "log_windows") as log, \
                mock.patch.object(overlay, "owned_process", return_value={"pid": 10}):
            o.trazer_app_quando_abrir(estado)
            o.trazer_app_quando_abrir(estado)
        self.assertEqual(estado.voltas, 0)
        o.trabalho.pedir.assert_not_called()
        falso.ativar_processo.assert_not_called()
        log.assert_called_once_with("overlay: o app não responde; espero para trazê-lo para a frente")
        o.root.after.assert_called()  # continua olhando

    def test_bringing_the_app_goes_to_the_worker_thread(self):
        falso, o = self.montar(travada=False)
        o.de_pe._firmes.add(0x77)  # já de pé
        with mock.patch.object(overlay, "win", falso, create=True), \
                mock.patch.object(overlay, "owned_process", return_value={"pid": 10}):
            o.trazer_app_quando_abrir(overlay.PrimeiraJanela())
        o.trabalho.pedir.assert_called_once_with("trazer o app", o.trazer_app, 10)
        falso.trazer_para_frente.assert_not_called()  # nunca na thread do Tk

    def test_window_not_standing_yet_is_only_checked_on_the_worker(self):
        """Roteiro 32: a janela acabou de aparecer: a thread de trabalho só confere se
        ela está de pé (ping); trazer, só depois."""
        falso, o = self.montar(travada=False)
        estado = overlay.PrimeiraJanela()
        with mock.patch.object(overlay, "win", falso, create=True), \
                mock.patch.object(overlay, "owned_process", return_value={"pid": 10}):
            o.trazer_app_quando_abrir(estado)
        o.trabalho.pedir.assert_called_once_with("ver se está de pé", o.de_pe.pronta, falso.JANELAS, 0x77)
        self.assertEqual(estado.trazidas, 0)

    def test_trazer_app_checks_again_and_logs_before_acting(self):
        import tempfile

        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        falso, o = self.montar(travada=False)
        falso.JANELAS = DePeFalso(responde=False)
        falso.ULTIMO_JEITO = ["direto"]
        with mock.patch.object(overlay, "win", falso, create=True), \
                mock.patch.object(overlay, "CACHE_DIR", pasta.name):
            o.trazer_app(10)
            falso.trazer_para_frente.assert_not_called()
            o.de_pe._firmes.add(0x77)
            o.trazer_app(10)
        falso.trazer_para_frente.assert_called_once_with(0x77)
        log = Path(pasta.name, "beni-windows.log").read_text(encoding="utf-8")
        self.assertIn("ainda não está de pé", log)
        self.assertLess(log.index("vou trazer o app (hwnd 0x77)"), log.index("trazer o app (hwnd 0x77): direto"))

    def test_stuck_worker_is_logged_once_and_the_pill_goes_on(self):
        o = overlay.AppOverlay.__new__(overlay.AppOverlay)
        o.erros_logados = set()
        o.trabalho = mock.Mock()
        o.trabalho.pedir.return_value = False
        o.trabalho.preso.return_value = ("trazer o app", 8.0)
        with mock.patch.object(overlay, "log_windows") as log:
            self.assertFalse(o.pedir_janela("tela cheia", print))
            self.assertFalse(o.pedir_janela("tela cheia", print))
        log.assert_called_once_with(
            "overlay: trazer o app preso há mais de 5 s numa janela de outro app; a pílula segue")


class XTests(unittest.TestCase):
    """Roteiro 32: com o Tux Paint travado, 6 cliques no ✕ não fecharam nada e o log não
    dizia nada."""

    def montar(self):
        import tempfile

        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.log = Path(pasta.name, "beni-windows.log")
        for alvo, valor in (("WINDOWS", True), ("CACHE_DIR", pasta.name)):
            p = mock.patch.object(overlay, alvo, valor)
            p.start()
            self.addCleanup(p.stop)
        o = overlay.AppOverlay.__new__(overlay.AppOverlay)
        o.tile_id = "tuxpaint"
        o.retangulo_do_x = (20, 1017, 72, 1069)
        return o

    def test_close_logs_first_and_kills_the_supervisor_once(self):
        o = self.montar()
        o.root = mock.Mock()
        with mock.patch.object(overlay, "terminate_owned_process", return_value=True) as termina, \
                mock.patch.object(overlay, "focus_launcher"), \
                self.assertRaises(SystemExit):
            o.on_close("✕")
        termina.assert_called_once_with(overlay.TILE_PROCESS_PIDFILE, "tile-process", overlay.TILE_PROCESS_MARKER)
        linhas = self.log.read_text(encoding="utf-8").splitlines()
        self.assertTrue(linhas[0].endswith("overlay: ✕ tocado"))
        self.assertIn("supervisor do app encerrado", linhas[1])
        with mock.patch.object(overlay, "terminate_owned_process") as termina:
            self.assertFalse(o.fechar_app("de novo"))  # uma vez só
        termina.assert_not_called()

    def test_x_watcher_closes_the_app_when_tk_never_gets_the_click(self):
        o = self.montar()
        eu = overlay.os.getpid()
        estados = iter([(False, (46, 1037), eu), (True, (46, 1037), eu), (False, (46, 1037), eu)])
        falso = mock.Mock()
        falso.estado_do_mouse.side_effect = lambda: next(estados, (False, (46, 1037), eu))
        relogio = [0.0]

        def dormir(seg):
            relogio[0] += seg

        with mock.patch.object(overlay, "win", falso, create=True), \
                mock.patch.object(overlay.time, "sleep", dormir), \
                mock.patch.object(overlay.time, "monotonic", lambda: relogio[0]), \
                mock.patch.object(overlay, "terminate_owned_process", return_value=True) as termina, \
                mock.patch.object(overlay, "focus_launcher"), \
                mock.patch.object(overlay, "remove_process_record"), \
                mock.patch.object(overlay.telemetria, "relatar_problema") as relata, \
                mock.patch.object(overlay.os, "_exit", side_effect=SystemExit) as sair, \
                self.assertRaises(SystemExit):
            o.vigiar_o_x()
        termina.assert_called_once()
        sair.assert_called_once_with(0)
        self.assertEqual(relata.call_args[0][2], "overlay.x_sem_tk:tuxpaint")
        log = self.log.read_text(encoding="utf-8")
        self.assertIn("vigia do ✕: clique no ✕", log)
        self.assertIn("o clique no ✕ não chegou ao Tk (o Tk rodou há", log)

    def test_x_watcher_steps_aside_when_tk_handles_the_click(self):
        o = self.montar()
        eu = overlay.os.getpid()
        estados = iter([(True, (46, 1037), eu), (False, (46, 1037), eu)])
        falso = mock.Mock()
        falso.estado_do_mouse.side_effect = lambda: next(estados, (False, (46, 1037), eu))

        def dormir(_seg):
            if falso.estado_do_mouse.call_count >= 2:
                o.fechando = True  # o on_close do Tk começou

        with mock.patch.object(overlay, "win", falso, create=True), \
                mock.patch.object(overlay.time, "sleep", dormir), \
                mock.patch.object(overlay, "terminate_owned_process") as termina, \
                mock.patch.object(overlay.os, "_exit") as sair:
            o.vigiar_o_x()
        termina.assert_not_called()
        sair.assert_not_called()

    def test_close_button_logs_every_press_and_release(self):
        codigo = (Path(__file__).resolve().parent.parent / "src" / "overlay.py").read_text(encoding="utf-8")
        self.assertIn('self.bind("<ButtonPress-1>", self._log_aperto, add="+")', codigo)
        self.assertIn('log_windows(f"overlay: botão {self.nome} solto', codigo)
        self.assertIn('command=lambda: self.on_close("✕"))', codigo)
        self.assertIn('threading.Thread(target=self.vigiar_o_x, name="vigia-do-x", daemon=True).start()', codigo)


class PilulaSemFocoTests(unittest.TestCase):
    """Roteiro 29: a pílula continuava ativável (exstyle 0x80008). O Tk recria a janela de
    fora quando o -alpha muda o WS_EX_LAYERED, e o estilo ficava na janela antiga."""

    def setUp(self):
        import tempfile

        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.log = Path(pasta.name, "beni-windows.log")
        for alvo, valor in (("WINDOWS", True), ("CACHE_DIR", pasta.name), ("_SEM_ATIVAR", {})):
            p = mock.patch.object(overlay, alvo, valor)
            p.start()
            self.addCleanup(p.stop)
        self.falso = mock.Mock()
        self.falso.raiz_da_janela.return_value = 0x1234
        self.falso.nao_ativavel.return_value = 0x08080088  # NOACTIVATE|TOPMOST|LAYERED|TOOLWINDOW
        p = mock.patch.object(overlay, "win", self.falso, create=True)
        p.start()
        self.addCleanup(p.stop)

    def test_every_overlay_window_is_made_non_activating_on_the_real_toplevel(self):
        janela = mock.Mock()
        janela.winfo_id.return_value = 0x99  # a janela de dentro; a de fora é a raiz (GA_ROOT)
        overlay.configure_overlay_window(janela)
        self.falso.raiz_da_janela.assert_called_with(0x99)
        self.falso.nao_ativavel.assert_called_with(0x1234)
        janela.attributes.assert_any_call("-toolwindow", True)
        janela.focus_force.assert_not_called()
        janela.lift.assert_not_called()  # o lift do Tk pode ativar
        self.assertIn("overlay: pílula sem ativar (hwnd 0x1234, exstyle 0x8080088)", self.log.read_text(encoding="utf-8"))

    def test_logged_once_per_window_and_again_when_tk_recreates_it(self):
        janela = mock.Mock()
        for _ in range(3):
            overlay.sem_ativar(janela, "pílula")
        self.falso.raiz_da_janela.return_value = 0x5678  # o -alpha recriou a janela
        overlay.sem_ativar(janela, "pílula")
        self.assertEqual(self.falso.nao_ativavel.call_count, 4)  # confere toda vez
        linhas = self.log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(linhas), 2)
        self.assertIn("0x5678", linhas[1])

    def test_style_that_did_not_stick_is_flagged_in_the_log(self):
        self.falso.nao_ativavel.return_value = 0x80008  # o que o claude-win mediu
        overlay.sem_ativar(mock.Mock(), "contagem")
        self.assertIn("o estilo NÃO ficou", self.log.read_text(encoding="utf-8"))

    def test_hover_never_reaches_full_opacity_on_windows(self):
        codigo = (Path(__file__).resolve().parent.parent / "src" / "overlay.py").read_text(encoding="utf-8")
        self.assertIn("PILL_ALPHA_HOVER = 0.99 if WINDOWS else 1.0", codigo)

    def test_nothing_changes_outside_windows(self):
        janela = mock.Mock()
        with mock.patch.object(overlay, "WINDOWS", False):
            overlay.configure_overlay_window(janela)
        janela.winfo_id.assert_not_called()
        janela.lift.assert_called_once()

class QuiosqueNaoAdotaTests(unittest.TestCase):
    """A segunda janela do Edge não vira o app. A bolha de download não fecha."""

    def test_esticar_trazer_e_o_vigia_ficam_com_a_do_quiosque(self):
        import tempfile

        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        popup = {"hwnd": "popup", "classe": "Chrome_WidgetWin_1", "titulo": "Powered by Ren'Py",
                 "dono": False, "area": 800 * 600, "visivel": True}
        bolha = {"hwnd": "bolha", "classe": "Chrome_WidgetWin_1", "titulo": "",
                 "dono": True, "area": 400 * 200, "visivel": True}
        quiosque = {"hwnd": "quiosque", "classe": "Chrome_WidgetWin_1", "titulo": "Jogo",
                    "dono": False, "area": 1920 * 1080, "visivel": True}
        falso = mock.Mock()
        falso.descrever_janelas.return_value = [popup, bolha, quiosque]
        falso.arvore.return_value = [10]
        falso.travada.return_value = False
        falso.esta_maximizada.return_value = True
        falso.retangulo.return_value = (-8, -8, 2568, 1048)
        falso.areas_do_monitor.return_value = (TRABALHO, MONITOR)
        falso.sem_moldura.return_value = False
        falso.tela_cheia_sem_moldura.return_value = 1
        falso.JANELAS = DePeFalso()
        falso.ULTIMO_JEITO = ["direto"]
        o = overlay.AppOverlay.__new__(overlay.AppOverlay)
        o.closing = False
        o.erros_logados = set()
        o.quiosque = overlay.quiosque_edge.Estado()
        o.quiosque_logados = set()
        o.de_pe = overlay.janelas_seguras.DePe(segundos=0)
        with mock.patch.object(overlay, "win", falso, create=True), \
                mock.patch.object(overlay, "CACHE_DIR", pasta.name), \
                mock.patch.object(overlay, "owned_process", return_value={"pid": 10}):
            o.passo_da_tela_cheia(overlay.TelaCheia(), {})
            o.trazer_app(10)
            o.passo_do_quiosque()
            o.passo_do_quiosque()
            log = Path(pasta.name, "beni-windows.log").read_text(encoding="utf-8")
        falso.tela_cheia_sem_moldura.assert_called_once()
        self.assertEqual(falso.tela_cheia_sem_moldura.call_args[0][0], "quiosque")
        falso.trazer_para_frente.assert_called_once_with("quiosque")
        self.assertEqual(
            [c.args for c in falso.fechar_extra.call_args_list],
            [("popup", "Chrome_WidgetWin_1"), ("popup", "Chrome_WidgetWin_1")],
        )
        self.assertEqual(
            log.count("quiosque: fechei janela extra do Edge (Chrome_WidgetWin_1, Powered by Ren'Py)"),
            1,
        )
        self.assertEqual(
            log.count("quiosque: deixei a bolha de download do Edge (Chrome_WidgetWin_1, (sem título))"),
            1,
        )
        self.assertNotIn("hwnd popup", log)
        self.assertNotIn("hwnd bolha", log)


if __name__ == "__main__":
    unittest.main()
