import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import marca_tk  # noqa: E402


class FonteTituloTests(unittest.TestCase):
    def carregar(self, familias):
        fonte = types.SimpleNamespace(families=lambda raiz: familias)
        tk = types.ModuleType("tkinter")
        tk.font = fonte
        with mock.patch.dict(sys.modules, {"tkinter": tk, "tkinter.font": fonte}), \
             mock.patch.object(marca_tk, "_carregada", None), \
             mock.patch.object(marca_tk, "_registrar_fonte", return_value=True):
            return marca_tk.fonte_titulo(object()), marca_tk.titulo(20)

    def test_linux_lists_fredoka_by_its_first_name(self):
        # fc-scan: "Fredoka,Fredoka SemiBold"; o Tk lista só "Fredoka"
        self.assertEqual(self.carregar(("Ubuntu", "Fredoka")), ("Fredoka", ("Fredoka", 20)))

    def test_windows_lists_the_semibold_family(self):
        self.assertEqual(self.carregar(("Segoe UI", "Fredoka SemiBold")),
                         ("Fredoka SemiBold", ("Fredoka SemiBold", 20)))

    def test_without_fredoka_falls_back_to_bold_system_font(self):
        familia, fonte = self.carregar(("Ubuntu",))
        self.assertEqual(familia, marca_tk.FONTE_CORPO)
        self.assertEqual(fonte, (marca_tk.FONTE_CORPO, 20, "bold"))


if __name__ == "__main__":
    unittest.main()
