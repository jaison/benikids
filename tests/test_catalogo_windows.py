import os
import sys
import tempfile
import unittest
from unittest import mock
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
            self.assertTrue(item.get("winget") or item.get("baixar", {}).get("url", "").startswith("https://") or item.get("pagina", "").startswith("https://"), item["id"])
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
            with mock.patch.dict(os.environ, {"ProgramData": raiz, "USERNAME": "Ângela"}), \
                 mock.patch.object(catalogo_windows, "tamanho_da_tela", return_value="2560x1080"):
                cmd = catalogo_windows.comando(["catalogo:supertux"], bases=[raiz])
            # o SuperTux não abre com acento no caminho do usuário: pasta de dados só ASCII
            dados = os.path.join(raiz, "Benikids", "dados", "Angela", "supertux")
            self.assertEqual(cmd, [str(exe), "--fullscreen", "--geometry", "2560x1080", "--userdir", dados])
            self.assertTrue(os.path.isdir(dados))
            self.assertIsNone(catalogo_windows.comando(["catalogo:gcompris"], bases=[raiz]))
            self.assertIsNone(catalogo_windows.comando(["catalogo:nao-existe"], bases=[raiz]))
            self.assertEqual(catalogo_windows.comando(["tuxpaint"], bases=[raiz]), ["tuxpaint"])


class CatalogoWindowsExtrasTests(unittest.TestCase):
    def test_finds_the_exe_through_installed_programs_when_globs_miss(self):
        with tempfile.TemporaryDirectory() as raiz:
            exe = Path(raiz, "Extreme TuxRacer", "ExtremeTuxRacer.exe")
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"")
            item = {"id": "etr", "registro": "Tux Racer", "exe": ["Outro*/ExtremeTuxRacer.exe"]}
            entradas = [("Firefox", "", ""), ("Extreme Tux Racer 0.8.4", str(exe.parent) + os.sep, "")]
            self.assertEqual(catalogo_windows.localizar(item, bases=[], registro=entradas), str(exe))
            self.assertIsNone(catalogo_windows.localizar(item, bases=[], registro=[("Firefox", raiz, "")]))

    def test_real_paths_reported_by_the_windows_test_match_the_catalog(self):
        with tempfile.TemporaryDirectory() as raiz:
            for relativo in ("GCompris-Qt/bin/GCompris.exe", "Extreme TuxRacer/ExtremeTuxRacer.exe"):
                Path(raiz, relativo).parent.mkdir(parents=True)
                Path(raiz, relativo).write_bytes(b"")
            for item_id in ("gcompris", "extremetuxracer"):
                item = catalogo_windows.por_id(item_id)
                self.assertTrue(catalogo_windows.localizar(item, bases=[raiz], registro=[]), item_id)

    def test_initial_config_is_written_once(self):
        with tempfile.TemporaryDirectory() as raiz:
            item = {"id": "supertux", "config_inicial": {"arquivo": "config", "texto": "(disable_network #t)"}}
            with mock.patch.dict(os.environ, {"ProgramData": raiz, "USERNAME": "Ângela"}):
                catalogo_windows.gravar_config_inicial(item)
                caminho = Path(raiz, "Benikids", "dados", "Angela", "supertux", "config")
                self.assertEqual(caminho.read_text(), "(disable_network #t)")
                caminho.write_text("do jogo")
                catalogo_windows.gravar_config_inicial(item)
                self.assertEqual(caminho.read_text(), "do jogo")  # não sobrescreve


class SincronizarCatalogoTests(unittest.TestCase):
    CATALOGO = [
        {"id": "gcompris", "label": "GCompris", "emoji": "🧩"},
        {"id": "kapman", "label": "Come-Come", "emoji": "🟡", "category": "jogos"},
        {"id": "vlc", "label": "VLC", "tile": False},
    ]

    def config(self, **extra):
        cfg = {"configVersion": 2, "activeProfileId": "a", "profiles": [
            {"id": "a", "name": "Ana", "tiles": [{"id": "gcompris", "label": "GCompris", "cmd": ["catalogo:gcompris"]}]},
            {"id": "b", "name": "Bia", "tiles": []},
        ]}
        cfg.update(extra)
        return cfg

    def test_new_catalog_apps_reach_existing_profiles_once(self):
        cfg, mudou = catalogo_windows.sincronizar_tiles(self.config(), self.CATALOGO)
        self.assertTrue(mudou)
        self.assertEqual([t["id"] for t in cfg["profiles"][0]["tiles"]], ["gcompris", "kapman"])
        self.assertEqual([t["id"] for t in cfg["profiles"][1]["tiles"]], ["gcompris", "kapman"])
        self.assertEqual(cfg["catalogSeen"], ["gcompris", "kapman"])
        validate_stored_config(cfg, existing_pin_hash="", allow_pin_hash=True)
        _, mudou = catalogo_windows.sincronizar_tiles(cfg, self.CATALOGO)
        self.assertFalse(mudou)

    def test_apps_removed_by_parents_do_not_come_back(self):
        cfg = self.config(catalogSeen=["gcompris", "kapman"])
        novo, mudou = catalogo_windows.sincronizar_tiles(cfg, self.CATALOGO)
        self.assertFalse(mudou)
        self.assertEqual(novo["profiles"][1]["tiles"], [])

    def test_apps_that_left_the_catalog_leave_the_profiles(self):
        cfg = self.config(catalogSeen=["gcompris", "kapman", "neverputt"])
        cfg["profiles"][0]["tiles"] += [
            {"id": "neverputt", "label": "Minigolfe", "cmd": ["catalogo:neverputt"]},
            {"id": "site", "label": "Site", "cmd": ["https://exemplo.org"]},
        ]
        novo, mudou = catalogo_windows.sincronizar_tiles(cfg, self.CATALOGO)
        self.assertTrue(mudou)
        self.assertEqual([t["id"] for t in novo["profiles"][0]["tiles"]], ["gcompris", "site"])
        _, mudou = catalogo_windows.sincronizar_tiles(novo, self.CATALOGO)
        self.assertFalse(mudou)


class ConfigsAntesDeAbrirTests(unittest.TestCase):
    def test_tux_racer_gets_fullscreen_portuguese_options_next_to_the_exe(self):
        with tempfile.TemporaryDirectory() as raiz:
            exe = os.path.join(raiz, "Extreme TuxRacer", "ExtremeTuxRacer.exe")
            item = {"id": "extremetuxracer", "config_inicial": {
                "arquivo": "config/options.txt", "junto_do_exe": True,
                "texto": "[fullscreen] 1\n[language] pt_PT\n"}}
            catalogo_windows.gravar_config_inicial(item, exe)
            caminho = Path(raiz, "Extreme TuxRacer", "config", "options.txt")
            self.assertEqual(caminho.read_text(encoding="utf-8"), "[fullscreen] 1\n[language] pt_PT\n")
            caminho.write_text("[language] EN_en\n", encoding="utf-8")
            catalogo_windows.gravar_config_inicial(item, exe)
            self.assertEqual(caminho.read_text(encoding="utf-8"), "[language] EN_en\n")  # não sobrescreve
            catalogo_windows.gravar_config_inicial(item, None)  # sem exe, nada a fazer

    def test_scratch_answers_the_telemetry_question_with_no_once(self):
        import json
        with tempfile.TemporaryDirectory() as raiz:
            arquivo = os.path.join(raiz, "Scratch", "telemetry.json")
            os.makedirs(os.path.dirname(arquivo))
            with open(arquivo, "w", encoding="utf-8") as f:
                json.dump({"clientID": "abc", "packetQueue": [1, 2]}, f)
            self.assertTrue(catalogo_windows.preparar_scratch(arquivo))
            with open(arquivo, encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"clientID": "abc", "packetQueue": [1, 2], "optIn": False})
            with open(arquivo, "w", encoding="utf-8") as f:
                json.dump({"optIn": True}, f)
            self.assertFalse(catalogo_windows.preparar_scratch(arquivo))  # os pais já responderam
            novo = os.path.join(raiz, "outro", "Scratch", "telemetry.json")
            self.assertTrue(catalogo_windows.preparar_scratch(novo))
            with open(novo, encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"optIn": False})

    def test_enigma_goes_fullscreen_once(self):
        with tempfile.TemporaryDirectory() as raiz:
            arquivo = os.path.join(raiz, "Enigma", ".enigmarc.xml")
            marca = os.path.join(raiz, "dados", "tela-cheia-ligada")
            self.assertTrue(catalogo_windows.preparar_enigma(arquivo, marca))
            self.assertIn('key="FullScreen" value="1"', Path(arquivo).read_text(encoding="utf-8"))
            Path(arquivo).write_text('<preferences><properties>\n<property key="FullScreen" value="0"/>\n'
                                     '<property key="VideoMode" value="0"/></properties></preferences>', encoding="utf-8")
            self.assertFalse(catalogo_windows.preparar_enigma(arquivo, marca))  # os pais desligaram
            os.remove(marca)
            self.assertTrue(catalogo_windows.preparar_enigma(arquivo, marca))  # arquivo do jogo, com 0
            texto = Path(arquivo).read_text(encoding="utf-8")
            self.assertIn('key="FullScreen" value="1"', texto)
            self.assertIn('key="VideoMode" value="0"', texto)


class PrepararXmotoTests(unittest.TestCase):
    def banco(self, pasta):
        import sqlite3
        caminho = os.path.join(pasta, "xm.db")
        db = sqlite3.connect(caminho)
        db.execute("CREATE TABLE xm_parameters(param, value)")
        db.execute("INSERT INTO xm_parameters VALUES ('siteKey', 'abc')")
        db.execute("CREATE TABLE stats_profiles(sitekey, id_profile, nbStarts, since)")
        db.execute("CREATE TABLE profiles_configs(id_profile, key, value, PRIMARY KEY(id_profile, key))")
        db.execute("INSERT INTO profiles_configs VALUES ('', 'Language', 'en_US')")
        db.commit()
        db.close()
        return caminho

    def test_existing_database_gets_the_benikids_profile_in_portuguese(self):
        import sqlite3
        import tempfile
        with tempfile.TemporaryDirectory() as pasta:
            caminho = self.banco(pasta)
            faltando = os.path.join(pasta, "nao", "xm.db")
            self.assertEqual(catalogo_windows.preparar_xmoto([faltando, caminho]), [caminho])
            catalogo_windows.preparar_xmoto([caminho])  # de novo: não duplica o perfil
            db = sqlite3.connect(caminho)
            self.assertEqual(db.execute("SELECT count(*) FROM stats_profiles WHERE id_profile='Benikids'").fetchone()[0], 1)
            cfg = dict(db.execute("SELECT key, value FROM profiles_configs WHERE id_profile=''").fetchall())
            db.close()
            self.assertEqual(cfg["Language"], "pt_BR")
            self.assertEqual(cfg["NotifyAtInit"], "false")

    def test_broken_database_is_ignored(self):
        import tempfile
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "xm.db")
            with open(caminho, "w") as f:
                f.write("isto não é sqlite")
            self.assertEqual(catalogo_windows.preparar_xmoto([caminho]), [])


if __name__ == "__main__":
    unittest.main()
