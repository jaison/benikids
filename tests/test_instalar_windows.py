"""A instalação por cima apaga arquivo que saiu da versão e deixa dado do usuário."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "windows"))

import atualizar_windows as aw  # noqa: E402
import instalar_windows as inst  # noqa: E402


def escrever(pasta, relativo, conteudo="x"):
    caminho = os.path.join(pasta, *relativo.split("/"))
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(conteudo)
    return caminho


def ler(caminho):
    with open(caminho, encoding="utf-8") as f:
        return f.read()


class CopiarPacoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pacote = os.path.join(self.tmp.name, "pacote")
        self.destino = os.path.join(self.tmp.name, "instalado")
        self.app = os.path.join(self.pacote, "app")
        os.makedirs(os.path.join(self.pacote, "python"))
        escrever(self.pacote, "python/pythonw.exe", "MZ")
        escrever(self.app, "server.py", "novo")
        escrever(self.app, "version", "1.0.9")
        aw.gravar_manifesto(self.app)
        self.logs = []

    def test_upgrade_removes_orphans_and_keeps_covers_and_python(self):
        escrever(self.destino, "server.py", "velho")
        escrever(self.destino, "timer_fim.py", "orfao")
        escrever(self.destino, "__pycache__/timer_fim.cpython-313.pyc")
        escrever(self.destino, "themes/covers/capa.jpg", "capa")
        escrever(self.destino, "python/Lib/sobra.py", "fica")
        escrever(self.destino, "python/__pycache__/sobra.pyc")
        with open(os.path.join(self.destino, aw.MANIFESTO), "w", encoding="utf-8") as f:
            f.write("server.py\ntimer_fim.py\nthemes/covers/capa.jpg\n")
        fora = escrever(self.tmp.name, "segredo.txt", "nao")

        inst.copiar_pacote(self.pacote, self.destino, log=self.logs.append)

        self.assertEqual(ler(os.path.join(self.destino, "server.py")), "novo")
        self.assertFalse(os.path.exists(os.path.join(self.destino, "timer_fim.py")))
        self.assertFalse(os.path.exists(os.path.join(self.destino, "__pycache__")))
        self.assertEqual(ler(os.path.join(self.destino, "themes", "covers", "capa.jpg")), "capa")
        self.assertEqual(ler(os.path.join(self.destino, "python", "Lib", "sobra.py")), "fica")
        self.assertTrue(os.path.isfile(os.path.join(self.destino, "python", "__pycache__", "sobra.pyc")))
        self.assertEqual(ler(os.path.join(self.destino, "version")), "1.0.9")
        self.assertEqual(ler(fora), "nao")
        self.assertTrue(any("timer_fim.py" in linha for linha in self.logs))
        self.assertTrue(any("sem lista" not in linha and "__pycache__" in linha for linha in self.logs))
        instalado = aw.ler_manifesto(self.destino)
        self.assertIn("server.py", instalado)
        self.assertNotIn("timer_fim.py", instalado)

    def test_old_install_without_a_list_keeps_the_py_and_drops_pycache(self):
        escrever(self.destino, "timer_fim.py", "orfao")
        escrever(self.destino, "__pycache__/timer_fim.cpython-313.pyc")
        escrever(self.destino, "themes/covers/capa.jpg", "capa")

        inst.copiar_pacote(self.pacote, self.destino, log=self.logs.append)

        self.assertTrue(os.path.isfile(os.path.join(self.destino, "timer_fim.py")))
        self.assertFalse(os.path.exists(os.path.join(self.destino, "__pycache__")))
        self.assertTrue(os.path.isfile(os.path.join(self.destino, "themes", "covers", "capa.jpg")))
        self.assertTrue(any("sem lista da versão anterior" in linha for linha in self.logs))

    def test_plain_copy_keeps_files_that_exist_only_at_the_destination(self):
        origem = os.path.join(self.tmp.name, "origem")
        escrever(origem, "server.py", "novo")
        escrever(self.destino, "server.py", "velho")
        escrever(self.destino, "themes/covers/capa.jpg", "capa")
        inst.copiar_arvore(origem, self.destino)
        self.assertEqual(ler(os.path.join(self.destino, "server.py")), "novo")
        self.assertEqual(ler(os.path.join(self.destino, "themes", "covers", "capa.jpg")), "capa")


if __name__ == "__main__":
    unittest.main()
