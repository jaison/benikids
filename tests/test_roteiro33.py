"""Roteiro 33: Tux Paint com OpenGL e --nolockfile, app que caiu com o código na
telemetria, aviso do app travado no menu, fila de problemas sem perder nada, pid-file que
o Windows está lendo, Pingus só maximizado."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

import catalogo_windows  # noqa: E402
import process_state  # noqa: E402
import process_supervisor  # noqa: E402
import telemetria  # noqa: E402


class CatalogoTests(unittest.TestCase):
    def test_tux_paint_uses_opengl_and_no_lockfile(self):
        item = catalogo_windows.por_id("tuxpaint")
        self.assertEqual(item["args"], ["--windowsize", "{tela}", "--nolockfile"])
        self.assertEqual(catalogo_windows.ambiente(["catalogo:tuxpaint"]), {"SDL_RENDER_DRIVER": "opengl"})
        self.assertEqual(catalogo_windows.ambiente(["catalogo:gcompris"]),
                         {"LANG": "pt_BR", "LC_ALL": "pt_BR", "LANGUAGE": "pt_BR"})
        self.assertEqual(catalogo_windows.ambiente(["tuxpaint"]), {})  # fora do catálogo
        self.assertEqual(catalogo_windows.ambiente([]), {})

    def test_bad_env_entries_are_dropped(self):
        with mock.patch.object(catalogo_windows, "por_id",
                               return_value={"env": {"A": "1", "B=C": "x", "D": ["x"], "": "y"}}):
            self.assertEqual(catalogo_windows.ambiente(["catalogo:x"]), {"A": "1"})

    def test_linux_wrapper_has_no_lockfile_too(self):
        self.assertIn("--nolockfile", (RAIZ / "beni" / "bin" / "tuxpaint").read_text(encoding="utf-8"))

    def test_pingus_stays_maximized_without_borderless(self):
        item = catalogo_windows.por_id("pingus")
        self.assertTrue(item["maximizar"])
        self.assertIs(item["sem_moldura"], False)
        codigo = (RAIZ / "src" / "overlay.py").read_text(encoding="utf-8")
        self.assertIn("if sem_moldura_no_inicio(tile_id):", codigo)

    def test_catalog_lines_were_not_reformatted(self):
        linhas = (RAIZ / "src" / "catalogo" / "windows.json").read_text(encoding="utf-8").splitlines()
        self.assertTrue(any(linha.lstrip().startswith('{"id": "tuxpaint"') for linha in linhas))
        json.loads("\n".join(linhas))


class CodigoDeSaidaTests(unittest.TestCase):
    def test_ntstatus_crash_is_shown_in_hex_and_kept_as_exit_code(self):
        self.assertEqual(process_supervisor.codigo_legivel(3221225477), "0xC0000005")
        self.assertEqual(process_supervisor.codigo_legivel(1), "1")
        self.assertEqual(process_supervisor.codigo_de_saida(3221225477), -1073741819)
        self.assertEqual(process_supervisor.codigo_de_saida(-1073741819) & 0xFFFFFFFF, 0xC0000005)
        self.assertEqual(process_supervisor.codigo_de_saida(0), 0)
        self.assertEqual(process_supervisor.codigo_de_saida(None), 0)

    def test_server_names_a_crash_app_caiu(self):
        import server

        self.assertEqual(server.como_o_app_saiu(3221225477), ("app.caiu", "0xC0000005"))
        self.assertEqual(server.como_o_app_saiu(-1073741819), ("app.caiu", "0xC0000005"))
        self.assertEqual(server.como_o_app_saiu(1), ("app.fechou_sozinho", "1"))
        self.assertEqual(server.como_o_app_saiu(None), ("app.fechou_sozinho", "?"))


class AvisoDoAppTravadoTests(unittest.TestCase):
    def test_warning_rides_on_usage_status_for_2_minutes(self):
        import server

        self.assertIsNone(server.aviso_app_travado(agora=0.0) if not server._app_travado_aviso["seq"] else None)
        server.avisar_app_travado("tuxpaint", agora=1000.0)
        aviso = server.aviso_app_travado(agora=1010.0)
        self.assertEqual(aviso["tileId"], "tuxpaint")
        seq = aviso["seq"]
        server.avisar_app_travado("kapman", agora=1020.0)
        self.assertEqual(server.aviso_app_travado(agora=1030.0)["seq"], seq + 1)
        self.assertIsNone(server.aviso_app_travado(agora=1020.0 + server.APP_TRAVADO_AVISO_S + 1))

    def test_both_menus_show_it(self):
        js = (RAIZ / "src" / "frontend" / "usage-limits.js").read_text(encoding="utf-8")
        self.assertIn("showUsageMessage('😕 O jogo travou','O jogo travou e foi fechado.')", js)
        self.assertIn("maybeShowAppTravado(data);", js)
        rs = (RAIZ / "cliente" / "src" / "menu.rs").read_text(encoding="utf-8")
        self.assertIn('"O jogo travou e foi fechado."', rs)


class FilaTests(unittest.TestCase):
    def setUp(self):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.pasta = pasta.name
        self.fila = os.path.join(pasta.name, "fila.jsonl")
        self.marcas = os.path.join(pasta.name, "marcas.json")

    def test_day_mark_only_after_the_queue_was_written(self):
        with mock.patch("builtins.open", side_effect=OSError("disco cheio")):
            self.assertFalse(telemetria.relatar_problema("app.travou", "x", "app.travou:t", fila=self.fila,
                                                         por_dia=True, marcas=self.marcas))
        self.assertFalse(os.path.exists(self.marcas))  # não marcou: a próxima tentativa vale
        self.assertTrue(telemetria.relatar_problema("app.travou", "x", "app.travou:t", fila=self.fila,
                                                    por_dia=True, marcas=self.marcas))
        self.assertFalse(telemetria.relatar_problema("app.travou", "x", "app.travou:t", fila=self.fila,
                                                     por_dia=True, marcas=self.marcas))

    def test_items_added_while_sending_are_not_lost(self):
        telemetria.relatar_problema("a", "1", fila=self.fila)
        original = open

        def abrir(caminho, *args, **kwargs):
            # outro processo acrescenta bem no meio do envio
            if str(caminho).endswith(".enviando") and not getattr(abrir, "feito", False):
                abrir.feito = True
                telemetria.relatar_problema("b", "2", fila=self.fila)
            return original(caminho, *args, **kwargs)

        with mock.patch("builtins.open", abrir):
            primeiro = telemetria.tirar_da_fila(self.fila)
        self.assertEqual([i["etapa"] for i in primeiro], ["a"])
        self.assertEqual([i["etapa"] for i in telemetria.tirar_da_fila(self.fila)], ["b"])

    def test_leftover_sending_file_is_read_first(self):
        with open(self.fila + ".enviando", "w", encoding="utf-8") as f:
            f.write(json.dumps({"etapa": "velho"}) + "\n")
        self.assertEqual(telemetria.tirar_da_fila(self.fila), [{"etapa": "velho"}])

    def test_exception_goes_to_the_log_with_traceback(self):
        linhas = []
        try:
            raise PermissionError("[WinError 32] em uso: overlay.pid")
        except PermissionError:
            tipo, valor, tb = sys.exc_info()
        for _ in range(2):
            telemetria.relatar_excecao("overlay", tipo, valor, tb, fila=self.fila, marcas=self.marcas,
                                       log=linhas.append)
        self.assertEqual(len(linhas), 2)  # no log sempre; na telemetria 1 por dia
        self.assertTrue(linhas[0].startswith("overlay: exceção não tratada PermissionError: [WinError 32]"))
        self.assertIn("Traceback", linhas[0])
        with open(self.fila, encoding="utf-8") as f:
            self.assertEqual(len(f.readlines()), 1)

    def test_log_never_raises(self):
        telemetria.log_windows("x", arquivo=os.path.join(self.pasta, "nao", "existe", "log"))
        telemetria.log_windows(object(), arquivo=self.pasta)  # é uma pasta


class PidFileTests(unittest.TestCase):
    """O PermissionError do overlay (D1, problema 27): WinError 32 no os.unlink do
    overlay.pid ao sair, porque o servidor o lia naquele instante."""

    def test_unlink_retries_while_another_process_reads(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "overlay.pid")
            Path(caminho).write_text("{}", encoding="utf-8")
            real = os.unlink
            tentativas = []

            def unlink(p):
                tentativas.append(p)
                if len(tentativas) < 3:
                    raise PermissionError(32, "em uso")
                real(p)

            with mock.patch.object(process_state.os, "unlink", unlink), \
                    mock.patch.object(process_state.time, "sleep"):
                self.assertTrue(process_state.remove_process_record(caminho))
            self.assertEqual(len(tentativas), 3)
            self.assertFalse(os.path.exists(caminho))

    def test_unlink_that_never_works_does_not_raise(self):
        with mock.patch.object(process_state.os, "unlink", side_effect=PermissionError(32, "em uso")), \
                mock.patch.object(process_state.time, "sleep"):
            self.assertFalse(process_state.remove_process_record("/x/overlay.pid"))

    def test_replace_retries_too(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "r.json")
            real = os.replace
            vezes = []

            def replace(a, b):
                vezes.append(1)
                if len(vezes) == 1:
                    raise PermissionError(5, "negado")
                real(a, b)

            with mock.patch.object(process_state.os, "replace", replace), \
                    mock.patch.object(process_state.time, "sleep"):
                process_state._atomic_write(caminho, {"a": 1})
            self.assertEqual(json.loads(Path(caminho).read_text(encoding="utf-8")), {"a": 1})


if __name__ == "__main__":
    unittest.main()
