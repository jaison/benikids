"""Roteiro 31: o travamento não chegou à telemetria. Os vigias e as exceções não tratadas
dos processos do Windows mandam, no máximo 1 por assinatura por dia, sem dado pessoal."""
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import telemetria  # noqa: E402


class PorDiaTests(unittest.TestCase):
    def setUp(self):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.fila = os.path.join(pasta.name, "fila.jsonl")
        self.marcas = os.path.join(pasta.name, "marcas.json")

    def itens(self):
        with open(self.fila, encoding="utf-8") as f:
            return [json.loads(linha) for linha in f]

    def test_one_per_signature_per_day(self):
        for _ in range(5):
            telemetria.relatar_problema("overlay.travou", "x", "overlay.travou:tuxpaint", fila=self.fila,
                                        por_dia=True, marcas=self.marcas)
        telemetria.relatar_problema("app.travou", "x", "app.travou:tuxpaint", fila=self.fila,
                                    por_dia=True, marcas=self.marcas)
        self.assertEqual([i["assinatura"] for i in self.itens()],
                         ["overlay.travou:tuxpaint", "app.travou:tuxpaint"])

    def test_next_day_sends_again_and_old_marks_are_dropped(self):
        self.assertFalse(telemetria.ja_relatado_hoje("a", self.marcas, hoje="2026-11-18"))
        self.assertTrue(telemetria.ja_relatado_hoje("a", self.marcas, hoje="2026-11-18"))
        self.assertFalse(telemetria.ja_relatado_hoje("b", self.marcas, hoje="2026-11-19"))
        self.assertFalse(telemetria.ja_relatado_hoje("a", self.marcas, hoje="2026-11-19"))
        with open(self.marcas, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"a": "2026-11-19", "b": "2026-11-19"})

    def test_exception_signature_and_clean_traceback(self):
        casa = os.path.expanduser("~")
        try:
            raise ValueError(f"falhou em {casa}\\Benikids\\x.py")
        except ValueError:
            tipo, valor, tb = sys.exc_info()
        telemetria.relatar_excecao("overlay", tipo, valor, tb, fila=self.fila, marcas=self.marcas)
        telemetria.relatar_excecao("overlay", tipo, valor, tb, fila=self.fila, marcas=self.marcas)
        itens = self.itens()
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0]["assinatura"], "excecao:overlay:ValueError")
        self.assertNotIn(casa, itens[0]["detalhe"])
        self.assertIn("ValueError", itens[0]["detalhe"])

    def test_hooks_only_on_windows_and_they_chain(self):
        self.assertFalse(telemetria.instalar_excepthook("x", sistema_nt=False))
        antes_sys, antes_thread = sys.excepthook, threading.excepthook
        vistos = []
        try:
            sys.excepthook = lambda *a: vistos.append("sys")
            threading.excepthook = lambda a: vistos.append("thread")
            relatados = []
            original = telemetria.relatar_excecao
            telemetria.relatar_excecao = lambda processo, tipo, *_: relatados.append((processo, tipo.__name__))
            try:
                self.assertTrue(telemetria.instalar_excepthook("servidor", sistema_nt=True))
                sys.excepthook(KeyError, KeyError("k"), None)
                t = threading.Thread(target=lambda: 1 / 0)
                t.start()
                t.join()
            finally:
                telemetria.relatar_excecao = original
        finally:
            sys.excepthook, threading.excepthook = antes_sys, antes_thread
        self.assertEqual(relatados, [("servidor", "KeyError"), ("servidor", "ZeroDivisionError")])
        self.assertEqual(vistos, ["sys", "thread"])


if __name__ == "__main__":
    unittest.main()
