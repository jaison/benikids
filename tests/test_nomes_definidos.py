"""Nenhum nome indefinido nos .py do Benikids (roteiro 29: overlay.py chamava log_windows,
que tinha sumido numa refatoração; o NameError só aparecia no Windows, dentro de um
caminho que nenhum teste rodava). O CI instala o pyflakes; sem ele, o teste é pulado."""
import subprocess
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

try:
    import pyflakes  # noqa: F401
except ImportError:
    pyflakes = None


@unittest.skipIf(pyflakes is None, "sem pyflakes (o CI instala)")
class NomesDefinidosTests(unittest.TestCase):
    def test_no_undefined_names_in_src_and_scripts(self):
        saida = subprocess.run([sys.executable, "-m", "pyflakes", str(RAIZ / "src"), str(RAIZ / "scripts")],
                               capture_output=True, text=True).stdout
        indefinidos = [linha for linha in saida.splitlines() if "undefined name" in linha]
        self.assertEqual(indefinidos, [])


if __name__ == "__main__":
    unittest.main()
