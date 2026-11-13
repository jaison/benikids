import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import catalogo_windows  # noqa: E402
from config_validation import validate_stored_config  # noqa: E402


class CatalogoWindowsTests(unittest.TestCase):
    def test_catalog_items_are_complete_and_unique(self):
        itens = catalogo_windows.carregar()
        self.assertGreaterEqual(len(itens), 10)
        ids = [i["id"] for i in itens]
        self.assertEqual(len(ids), len(set(ids)))
        for item in itens:
            self.assertRegex(item["id"], r"^[a-z0-9-]+$")
            self.assertTrue(item.get("winget"), item["id"])
            self.assertIn(item.get("escopo", ""), ("", "user", "machine"), item["id"])
            self.assertTrue(item.get("exe"), item["id"])
            if item.get("escopo") == "machine":
                self.assertIn(item.get("instalador"), ("msi", "wix", "nullsoft", "inno"), item["id"])

    def test_tiles_are_valid_config_and_all_visible(self):
        tiles = catalogo_windows.tiles()
        self.assertTrue(all(t["visible"] for t in tiles))
        self.assertNotIn("vlc", [t["id"] for t in tiles])
        config = {
            "configVersion": 2,
            "activeProfileId": "default",
            "profiles": [{"id": "default", "name": "Ana", "tiles": tiles}],
        }
        validate_stored_config(config, existing_pin_hash="", allow_pin_hash=True)

    def test_command_resolves_installed_exe_and_reports_missing(self):
        with tempfile.TemporaryDirectory() as raiz:
            exe = Path(raiz, "SuperTux 0.7", "bin", "supertux2.exe")
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"")
            self.assertEqual(
                catalogo_windows.comando(["catalogo:supertux"], bases=[raiz]),
                [str(exe), "--fullscreen"],
            )
            self.assertIsNone(catalogo_windows.comando(["catalogo:gcompris"], bases=[raiz]))
            self.assertIsNone(catalogo_windows.comando(["catalogo:nao-existe"], bases=[raiz]))
            self.assertEqual(catalogo_windows.comando(["tuxpaint"], bases=[raiz]), ["tuxpaint"])


if __name__ == "__main__":
    unittest.main()
