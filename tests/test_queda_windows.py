"""Queda do iniciador no Windows (roteiro 24): o que sobrou da sessão anterior é
reconhecido pelo caminho da instalação e encerrado na abertura seguinte."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import queda_windows as queda  # noqa: E402

APP = os.path.join(os.sep, "Beni", "app")
CACHE = os.path.join(os.sep, "Users", "ana", ".cache", "cozy-kids-launcher")
PY = os.path.join(os.sep, "Beni", "python", "pythonw.exe")


def proc(pid, exe, argv=(), sessao=1):
    return {"pid": pid, "exe": exe, "argv": list(argv) or [exe], "sessao": sessao}


class RestosTests(unittest.TestCase):
    def test_orphans_of_this_installation_are_found_menu_first(self):
        lista = [
            proc(10, PY, [PY, os.path.join(APP, "server.py")]),
            proc(11, PY, [PY, os.path.join(APP, "timer_watchdog.py"), "--port", "38431"]),
            proc(12, os.path.join(APP, "beni-menu.exe"), [os.path.join(APP, "beni-menu.exe"), "--porta", "1"]),
            proc(13, PY, [PY, os.path.join(APP, "overlay.py"), "x"]),
            proc(14, PY, [PY, os.path.join(APP, "process_supervisor.py")]),
            proc(15, "msedge.exe", ["msedge.exe", "--user-data-dir=" + os.path.join(CACHE, "menu-chromium-profile"),
                                    "--kiosk", "http://127.0.0.1"]),
            proc(16, "firefox.exe", ["firefox.exe", "--profile", os.path.join(CACHE, "menu-firefox-profile")]),
        ]
        self.assertEqual(queda.restos(lista, APP, CACHE, meu_pid=1, minha_sessao=1),
                         [12, 10, 11, 13, 14, 15, 16])

    def test_other_programs_users_and_this_process_are_left_alone(self):
        lista = [
            proc(1, PY, [PY, os.path.join(APP, "beni_windows.py")]),        # este iniciador
            proc(20, PY, [PY, os.path.join(APP, "instalar_apps.py")]),      # instalação pedida pelos pais
            proc(21, "msedge.exe", ["msedge.exe", "https://exemplo.org"]),  # o Edge do adulto
            proc(22, "beni-menu.exe", ["beni-menu.exe"]),                   # mesmo nome, outro lugar
            proc(23, PY, [PY, os.path.join(os.sep, "outro", "server.py")]),
            proc(24, os.path.join(APP, "beni-menu.exe"), sessao=2),         # outro usuário logado
            proc(25, "msedge.exe", ["msedge.exe", "--user-data-dir=" + os.path.join(CACHE, "site-profile")]),
        ]
        self.assertEqual(queda.restos(lista, APP, CACHE, meu_pid=1, minha_sessao=1), [])

    def test_crash_is_detected_by_the_session_or_taskbar_file(self):
        with tempfile.TemporaryDirectory() as pasta:
            sessao = os.path.join(pasta, "sessao.json")
            barra = os.path.join(pasta, "barra-escondida.json")
            self.assertFalse(queda.caiu_antes(sessao, (barra,)))
            queda.marcar_sessao(sessao, 123)
            self.assertTrue(queda.caiu_antes(sessao, (barra,)))
            queda.fim_da_sessao(sessao)
            queda.fim_da_sessao(sessao)  # de novo (finally + atexit)
            self.assertFalse(queda.caiu_antes(sessao, (barra,)))
            Path(barra).write_text("{}")
            self.assertTrue(queda.caiu_antes(sessao, (barra,)))


class ForaDoJobTests(unittest.TestCase):
    def test_breakaway_is_asked_and_falls_back_when_refused(self):
        with mock.patch.object(queda.subprocess, "Popen") as popen:
            queda.popen_fora_do_job(["x"], creationflags=0x08000000, cwd="c")
        popen.assert_called_once_with(["x"], creationflags=0x08000000 | queda.CREATE_BREAKAWAY_FROM_JOB, cwd="c")
        with mock.patch.object(queda.subprocess, "Popen", side_effect=[OSError(5, "negado"), "ok"]) as popen:
            self.assertEqual(queda.popen_fora_do_job(["x"]), "ok")
        self.assertEqual(popen.call_args_list[1], mock.call(["x"], creationflags=0))


class IniciadorTests(unittest.TestCase):
    def test_launcher_cleans_up_before_the_update_and_jails_its_children(self):
        codigo = Path(__file__).resolve().parents[1].joinpath("src", "beni_windows.py").read_text(encoding="utf-8")
        main = codigo[codigo.index("def main():"):]
        ordem = [main.index(t) for t in ("instancia_unica(", "limpar_queda()", "win.prender_a_sessao()",
                                         "marcar_sessao(", "atualizacao_pendente()", "trava.ligar()",
                                         "subir_servidor()")]
        self.assertEqual(ordem, sorted(ordem))
        fim = main[main.index("    finally:\n        encerrar_tudo"):]
        self.assertIn("queda_windows.fim_da_sessao(SESSAO)", fim)

    def test_things_that_must_outlive_the_session_break_away_from_the_job(self):
        raiz = Path(__file__).resolve().parents[1] / "src"
        self.assertIn("popen_fora_do_job(argv", (raiz / "atualizar_windows.py").read_text(encoding="utf-8"))
        servidor = (raiz / "server.py").read_text(encoding="utf-8")
        trecho = servidor[servidor.index('"api/catalogo/instalar"'):][:900]
        self.assertIn("popen_fora_do_job(", trecho)


if __name__ == "__main__":
    unittest.main()
