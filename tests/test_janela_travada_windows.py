"""Roteiro 34: provar no Windows de verdade (runner do CI) que o vigia fecha um app
travado. No PC de teste não dá para provocar: suspender o processo deixa a thread
"esperando entrada" dentro do GetMessage, e o IsHungAppWindow nunca vira True.

O ajudante (tests/ajudantes/janela_travada.py) cria uma janela Win32, bombeia ~1 s e
dorme na thread dela sem bombear. O teste manda entrada (PostMessage), espera o
IsHungAppWindow e roda o VigiaDaPilula + VigiaWindows de verdade sobre a árvore do
ajudante, com os tempos encurtados. Só roda no Windows."""
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

AJUDANTE = RAIZ / "tests" / "ajudantes" / "janela_travada.py"
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0200, 0x0201, 0x0202


class UsoFalso:
    def __init__(self):
        self.pausas = 0
        self.retomadas = 0

    def pausar(self):
        self.pausas += 1

    def retomar(self):
        self.retomadas += 1
        return 0.0

    def parado_agora(self):
        return 0.0


@unittest.skipUnless(os.name == "nt", "precisa de janelas Win32 de verdade")
class JanelaTravadaTests(unittest.TestCase):
    def setUp(self):
        import ctypes

        import plataforma_windows
        import telemetria
        import vigia_da_pilula

        self.win, self.telemetria, self.vp = plataforma_windows, telemetria, vigia_da_pilula
        self.user32 = ctypes.WinDLL("user32")
        self.user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.fila = os.path.join(pasta.name, "problemas-pendentes.jsonl")
        self.marcas = os.path.join(pasta.name, "problemas-do-dia.json")

    def abrir_ajudante(self, dorme):
        proc = subprocess.Popen([sys.executable, str(AJUDANTE), str(dorme)], stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: (proc.poll() is None and proc.kill(), proc.wait(5)))
        linha = proc.stdout.readline().strip()
        self.assertTrue(linha.startswith("pronto "), linha)
        self.comeco_do_sono = time.monotonic()
        return proc, int(linha.split()[1])

    def cutucar(self, h):
        # entrada na fila da janela (o Windows só "vê" o travamento com algo para ler)
        self.user32.PostMessageW(h, WM_MOUSEMOVE, 0, (50 << 16) | 50)
        self.user32.PostMessageW(h, WM_LBUTTONDOWN, 1, (50 << 16) | 50)
        self.user32.PostMessageW(h, WM_LBUTTONUP, 0, (50 << 16) | 50)

    def montar_vigia(self, proc, app_s, fechar_s):
        teste = self

        class Launcher:
            lock = threading.Lock()
            ultimo_overlay = {"mode": "local", "url": "", "tile_id": "teste-travado"}
            chamadas = []

            def stop_existing_overlay(self):
                self.chamadas.append("parar a pílula")

            def stop_active_tile(self):
                # o mesmo que o servidor faz com o supervisor: TerminateProcess
                self.chamadas.append("fechar o app")
                ok = teste.win.terminar(proc.pid)
                proc.wait(5)
                return ok

        self.launcher = Launcher()
        self.linhas = []
        self.fechados = []
        self.uso = UsoFalso()
        app = {"pid": proc.pid, "startTime": 1}
        pilula = {"pid": os.getpid()}  # viva e sem janelas: nunca "travada"

        def relatar(etapa, detalhe, assinatura):
            self.telemetria.relatar_problema(etapa, detalhe, assinatura, fila=self.fila, por_dia=True,
                                             marcas=self.marcas)

        return self.vp.VigiaWindows(
            self.win, lambda: self.launcher, lambda: (app if proc.poll() is None else None, pilula),
            uso=self.uso, relatar=relatar, log=self.linhas.append,
            vigia=self.vp.VigiaDaPilula(app_s=app_s, fechar_s=fechar_s), ao_fechar=self.fechados.append)

    def itens_da_fila(self):
        import json

        if not os.path.exists(self.fila):
            return []
        with open(self.fila, encoding="utf-8") as f:
            return [json.loads(linha) for linha in f]

    def test_hung_window_is_detected_and_closed_by_the_watcher(self):
        proc, h = self.abrir_ajudante(dorme=120)
        v = self.montar_vigia(proc, app_s=1.0, fechar_s=4.0)
        travou_em = None
        limite = time.monotonic() + 40
        while proc.poll() is None and time.monotonic() < limite:
            self.cutucar(h)
            if travou_em is None and self.win.travada(h):
                travou_em = time.monotonic() - self.comeco_do_sono
                print(f"\n  IsHungAppWindow True {travou_em:.1f} s depois de a janela parar de bombear")
            v.volta()
            time.sleep(0.25)
        fechou_em = time.monotonic() - self.comeco_do_sono
        print(f"  app fechado pelo vigia {fechou_em:.1f} s depois de a janela parar de bombear")
        print("  log: " + " | ".join(self.linhas))
        self.assertIsNotNone(travou_em, "o IsHungAppWindow nunca virou True neste Windows")
        self.assertLessEqual(travou_em, 6.0)
        self.assertIsNotNone(proc.poll(), "o vigia não encerrou o app travado")
        self.assertEqual(self.launcher.chamadas, ["parar a pílula", "fechar o app"])
        self.assertTrue(any(linha.startswith("app: teste-travado travado há 4 s; fechado") for linha in self.linhas),
                        self.linhas)
        self.assertEqual(self.fechados, ["teste-travado"])
        self.assertEqual(self.uso.pausas, 1)
        v.volta()  # o app já não existe: o tempo volta a contar (sem o travado)
        self.assertEqual(self.uso.retomadas, 1)
        itens = self.itens_da_fila()
        self.assertEqual([i["assinatura"] for i in itens], ["app.travou:teste-travado"])
        self.assertIn("fechado=True", itens[0]["detalhe"])

    def test_window_that_comes_back_before_the_limit_is_not_closed(self):
        # dorme 9 s: "Não respondendo" de ~5 s a ~9 s (uns 4 s), abaixo do limite de 8 s
        proc, h = self.abrir_ajudante(dorme=9)
        v = self.montar_vigia(proc, app_s=1.0, fechar_s=8.0)
        viu_travada = False
        limite = time.monotonic() + 16
        while time.monotonic() < limite:
            self.cutucar(h)
            viu_travada = viu_travada or self.win.travada(h)
            v.volta()
            time.sleep(0.25)
        print("\n  log: " + " | ".join(self.linhas))
        self.assertTrue(viu_travada, "o IsHungAppWindow nunca virou True neste Windows")
        self.assertIsNone(proc.poll(), "o vigia fechou um app que voltou a responder")
        self.assertEqual(self.launcher.chamadas, [])
        self.assertTrue(any("voltou a responder" in linha for linha in self.linhas), self.linhas)
        itens = self.itens_da_fila()
        self.assertEqual([i["assinatura"] for i in itens], ["app.travou:teste-travado"])
        self.assertIn("fechado=False", itens[0]["detalhe"])


if __name__ == "__main__":
    unittest.main()
