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
        self.assertEqual(cfg["catalogSeen"], ["gcompris", "kapman", "migracao-gcompris-passatempo"])
        validate_stored_config(cfg, existing_pin_hash="", allow_pin_hash=True)
        _, mudou = catalogo_windows.sincronizar_tiles(cfg, self.CATALOGO)
        self.assertFalse(mudou)

    def test_apps_removed_by_parents_do_not_come_back(self):
        cfg = self.config(catalogSeen=["gcompris", "kapman", catalogo_windows.MARCA_GCOMPRIS])
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

    def test_existing_gcompris_moves_to_the_linux_category(self):
        catalogo = [
            {"id": "gcompris", "label": "GCompris", "emoji": "🧩", "category": "passatempo"},
        ]
        cfg = self.config(catalogSeen=["gcompris"])
        cfg["profiles"][0]["tiles"][0]["category"] = "educativo"
        novo, mudou = catalogo_windows.sincronizar_tiles(cfg, catalogo)
        self.assertTrue(mudou)
        self.assertEqual(novo["profiles"][0]["tiles"][0]["category"], "passatempo")
        self.assertIn(catalogo_windows.MARCA_GCOMPRIS, novo["catalogSeen"])
        _, mudou = catalogo_windows.sincronizar_tiles(novo, catalogo)
        self.assertFalse(mudou)
        # os pais devolvem para Aprender: a subida do servidor não desfaz
        novo["profiles"][0]["tiles"][0]["category"] = "educativo"
        de_novo, mudou = catalogo_windows.sincronizar_tiles(novo, catalogo)
        self.assertFalse(mudou)
        self.assertEqual(de_novo["profiles"][0]["tiles"][0]["category"], "educativo")

    def test_parent_category_survives_and_is_not_rewritten_for_other_tiles(self):
        catalogo = [
            {"id": "gcompris", "label": "GCompris", "emoji": "🧩", "category": "passatempo"},
            {"id": "kapman", "label": "Come-Come", "emoji": "🟡", "category": "jogos"},
        ]
        cfg = self.config(catalogSeen=["gcompris"])
        cfg["profiles"][0]["tiles"][0]["category"] = "jogos"
        cfg["profiles"][0]["tiles"].append(
            {"id": "kapman", "label": "Come-Come", "cmd": ["catalogo:kapman"], "category": "educativo"},
        )
        novo, mudou = catalogo_windows.sincronizar_tiles(cfg, catalogo)
        self.assertTrue(mudou)  # só a marca; a categoria que os pais escolheram fica
        self.assertEqual(novo["profiles"][0]["tiles"][0]["category"], "jogos")
        self.assertEqual(novo["profiles"][0]["tiles"][1]["category"], "educativo")
        _, mudou = catalogo_windows.sincronizar_tiles(novo, catalogo)
        self.assertFalse(mudou)
        self.assertEqual(novo["profiles"][0]["tiles"][0]["category"], "jogos")
        self.assertEqual(novo["profiles"][0]["tiles"][1]["category"], "educativo")


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

    def test_kfourinline_gets_its_folder_in_the_path(self):
        exe = os.path.join("C:", "kfourinline", "bin", "kfourinline.exe")
        self.assertEqual(catalogo_windows.pasta_no_path(["catalogo:kfourinline"], [exe]), os.path.dirname(exe))
        self.assertEqual(catalogo_windows.pasta_no_path(["catalogo:gcompris"], ["x/GCompris.exe"]), "")
        self.assertEqual(catalogo_windows.pasta_no_path(["tuxpaint"], ["tuxpaint"]), "")


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


class PrepararLuantiTests(unittest.TestCase):
    def portatil(self, raiz):
        exe = Path(raiz) / "luanti-5.18.0-win64" / "bin" / "luanti.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        (exe.parent.parent / "builtin").mkdir()
        return exe

    def test_portable_winget_build_gets_the_missing_keys_next_to_builtin(self):
        with tempfile.TemporaryDirectory() as raiz:
            exe = self.portatil(raiz)
            gravados = catalogo_windows.preparar_luanti(str(exe), appdata=raiz, pacotes=[])
            conf = exe.parent.parent / "minetest.conf"
            self.assertEqual(gravados, [str(conf)])
            self.assertEqual(conf.read_text(encoding="utf-8"),
                             "".join(f"{k} = {v}\n" for k, v in catalogo_windows.LUANTI_CONFIG))
            self.assertFalse((Path(raiz) / "Luanti").exists())

    def test_keys_the_parents_changed_are_kept(self):
        with tempfile.TemporaryDirectory() as raiz:
            exe = self.portatil(raiz)
            conf = exe.parent.parent / "minetest.conf"
            conf.write_text("fullscreen = false\r\nname = Bia", encoding="utf-8")
            catalogo_windows.preparar_luanti(str(exe), appdata=raiz, pacotes=[])
            faltam = "".join(f"{k} = {v}\n" for k, v in catalogo_windows.LUANTI_CONFIG if k != "fullscreen")
            self.assertEqual(conf.read_bytes().decode("utf-8"),
                             "fullscreen = false\r\nname = Bia\n" + faltam)
            antes = conf.read_text(encoding="utf-8")
            catalogo_windows.preparar_luanti(str(exe), appdata=raiz, pacotes=[])
            self.assertEqual(conf.read_text(encoding="utf-8"), antes)

    def test_links_shortcut_falls_back_to_the_package_folder(self):
        with tempfile.TemporaryDirectory() as raiz:
            exe = self.portatil(raiz)
            atalho = Path(raiz) / "Links" / "luanti.exe"
            atalho.parent.mkdir()
            atalho.write_text("")  # cópia, não link: o caminho real não leva ao jogo
            confs = catalogo_windows.confs_luanti(str(atalho), appdata=raiz, pacotes=[str(exe)])
            self.assertEqual(confs, [str(exe.parent.parent / "minetest.conf")])

    def test_installed_build_uses_appdata(self):
        with tempfile.TemporaryDirectory() as raiz:
            exe = Path(raiz) / "Programs" / "Luanti" / "bin" / "luanti.exe"
            self.assertEqual(catalogo_windows.confs_luanti(str(exe), appdata=raiz, pacotes=[]),
                             [os.path.join(raiz, "Luanti", "minetest.conf")])

    def test_catalog_asks_for_the_luanti_preparation(self):
        self.assertEqual(catalogo_windows.por_id("luanti")["preparar"], "luanti")

    def test_lightweight_keys_match_the_linux_conf(self):
        texto = Path(__file__).resolve().parents[1].joinpath(
            "beni", "emuladores", "luanti-minetest.conf").read_text(encoding="utf-8")
        chaves = {}
        for linha in texto.splitlines():
            if not linha.strip() or linha.strip().startswith("#") or "=" not in linha:
                continue
            chave, _, valor = linha.partition("=")
            chaves[chave.strip()] = valor.strip()
        atual = dict(catalogo_windows.LUANTI_CONFIG)
        for chave, valor in chaves.items():
            self.assertEqual(atual[chave], valor, chave)
        self.assertEqual(atual["update_information_url"], "")


class PrepararSuperTuxKartTests(unittest.TestCase):
    CONFIG = ('<?xml version="1.0"?>\n<stkconfig version="8" >\n    <Video\n'
              '        fullscreen="false"\n        prev_fullscreen="false"\n'
              '        width="1040"\n        height="807"\n        real_width="1040"\n'
              '        real_height="807"\n        prev_real_width="1024"\n        prev_real_height="768"\n'
              '        max_texture_size="512"\n    />\n    <enable_internet value="0" />\n\n</stkconfig>\n')

    def test_existing_config_goes_fullscreen_offline_at_the_current_resolution(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "config.xml"
            arquivo.write_text(self.CONFIG, encoding="utf-8")
            (Path(pasta) / "players.xml").write_text("<players/>", encoding="utf-8")
            self.assertEqual(catalogo_windows.preparar_supertuxkart("2560x1080", pasta), {"config.xml"})
            texto = arquivo.read_text(encoding="utf-8")
            for chave, valor in (("fullscreen", "true"), ("width", "2560"), ("height", "1080"),
                                 ("real_width", "2560"), ("real_height", "1080"),
                                 ("prev_real_width", "2560"), ("prev_real_height", "1080")):
                self.assertIn(f'\n        {chave}="{valor}"', texto)
            self.assertIn('<enable_internet value="2" />', texto)
            self.assertNotIn('value="0"', texto)
            self.assertIn('prev_fullscreen="false"', texto)
            self.assertIn('max_texture_size="512"', texto)
            # de novo, antes da próxima abertura: nada muda
            self.assertEqual(catalogo_windows.preparar_supertuxkart("2560x1080", pasta), set())
            self.assertEqual((Path(pasta) / "players.xml").read_text(encoding="utf-8"), "<players/>")

    def test_config_without_the_internet_key_gets_it(self):
        texto = catalogo_windows.ajustar_config_stk('<stkconfig version="8" >\n</stkconfig>\n')
        self.assertEqual(texto, '<stkconfig version="8" >\n    <enable_internet value="2" />\n</stkconfig>\n')

    def test_first_run_gets_minimal_files_the_game_accepts(self):
        import xml.etree.ElementTree as ET

        with tempfile.TemporaryDirectory() as raiz:
            pasta = os.path.join(raiz, "supertuxkart", "config-0.10")
            self.assertEqual(catalogo_windows.preparar_supertuxkart("1366x768", pasta), {"config.xml", "players.xml"})
            config = ET.parse(os.path.join(pasta, "config.xml")).getroot()
            self.assertEqual(config.tag, "stkconfig")
            self.assertEqual(config.get("version"), "8")  # menor que isso o jogo descarta
            self.assertEqual(config.find("enable_internet").get("value"), "2")
            players = ET.parse(os.path.join(pasta, "players.xml")).getroot()
            self.assertEqual(players.tag, "players")
            self.assertEqual(players.find("current").get("player"), "Benikids")
            jogador = players.find("player")
            self.assertEqual(jogador.get("name"), "Benikids")
            self.assertEqual(jogador.get("guest"), "false")
            # sem ícone: o jogo copia o de um kart (PlayerProfile::addIcon)
            self.assertEqual(jogador.get("icon-filename"), "")

    def test_command_line_and_preparation_are_in_the_catalog(self):
        item = catalogo_windows.por_id("supertuxkart")
        self.assertEqual(item["args"], ["--fullscreen", "--screensize={tela}"])
        self.assertEqual(item["preparar"], "supertuxkart")
        with mock.patch.object(catalogo_windows, "tamanho_da_tela", return_value="1366x768"):
            self.assertEqual(catalogo_windows.preencher("--screensize={tela}", item), "--screensize=1366x768")

    def test_files_live_in_appdata(self):
        self.assertEqual(catalogo_windows.config_supertuxkart(appdata="A"),
                         os.path.join("A", "supertuxkart", "config-0.10", "config.xml"))


class AjustesDosAppsTests(unittest.TestCase):
    def test_gcompris_matches_the_linux_wrapper(self):
        item = catalogo_windows.por_id("gcompris")
        self.assertEqual(item["category"], "passatempo")
        self.assertEqual(item["args"], ["-f", "--difficulty", "3-6", "--locale", "pt_BR"])
        self.assertEqual(item["env"]["LANGUAGE"], "pt_BR")

    def test_stellarium_starts_fullscreen(self):
        self.assertEqual(catalogo_windows.por_id("stellarium")["args"], ["--full-screen", "yes"])

    def test_tux_racer_keeps_pt_pt_because_the_game_has_no_pt_br(self):
        texto = catalogo_windows.por_id("extremetuxracer")["config_inicial"]["texto"]
        self.assertIn("[language] pt_PT", texto)
        self.assertNotIn("pt_BR", texto)

    def test_kdeglobals_gains_portuguese_without_replacing_a_choice(self):
        self.assertEqual(catalogo_windows.texto_kdeglobals(""), "[Locale]\nLanguage=pt_BR\n")
        self.assertEqual(catalogo_windows.texto_kdeglobals("[Locale]\nCountry=BR\n"),
                         "[Locale]\nLanguage=pt_BR\nCountry=BR\n")
        escolhido = "[Locale]\nLanguage=en_US\n"
        self.assertEqual(catalogo_windows.texto_kdeglobals(escolhido), escolhido)
        with tempfile.TemporaryDirectory() as raiz:
            caminho = os.path.join(raiz, "kdeglobals")
            catalogo_windows.garantir_idioma_kde([caminho])
            self.assertEqual(Path(caminho).read_text(encoding="utf-8"), "[Locale]\nLanguage=pt_BR\n")
            Path(caminho).write_text("Language=de\n", encoding="utf-8")
            catalogo_windows.garantir_idioma_kde([caminho])
            self.assertEqual(Path(caminho).read_text(encoding="utf-8"), "Language=de\n")

    def test_pista_turbo_copies_the_project_once(self):
        with tempfile.TemporaryDirectory() as raiz:
            origem = os.path.join(raiz, "Pista Turbo.sb3")
            destino = os.path.join(raiz, "Scratch", "Pista Turbo.sb3")
            with open(origem, "wb") as f:
                f.write(b"PK pista")
            self.assertEqual(catalogo_windows.preparar_pista(destino, origem), destino)
            self.assertEqual(Path(destino).read_bytes(), b"PK pista")
            with open(destino, "wb") as f:
                f.write(b"da crianca")
            catalogo_windows.preparar_pista(destino, origem)
            self.assertEqual(Path(destino).read_bytes(), b"da crianca")

    def test_scratch_tile_is_turbowarp_and_pista_opens_the_sb3(self):
        scratch = catalogo_windows.por_id("scratch")
        pista = catalogo_windows.por_id("pista-turbo")
        self.assertEqual(scratch["winget"], "GarboMuffin.TurboWarp")
        self.assertEqual(pista["winget"], scratch["winget"])
        self.assertEqual(pista["category"], "educativo")
        self.assertEqual(pista["args"], ["{pista}"])
        with tempfile.TemporaryDirectory() as raiz:
            exe = Path(raiz, "TurboWarp", "TurboWarp.exe")
            exe.parent.mkdir()
            exe.write_bytes(b"")
            destino = os.path.join(raiz, "Scratch", "Pista Turbo.sb3")
            with mock.patch.object(catalogo_windows, "preparar_pista", return_value=destino):
                cmd = catalogo_windows.comando(["catalogo:pista-turbo"], bases=[raiz])
            self.assertEqual(cmd, [str(exe), destino])

    def test_snes_opens_the_game_list(self):
        with tempfile.TemporaryDirectory() as raiz:
            exe = Path(raiz, "RetroArch", "retroarch.exe")
            exe.parent.mkdir()
            exe.write_bytes(b"MZ")
            with mock.patch("cozy_jogos.baixar_core", return_value=os.path.join(raiz, "core.dll")), \
                    mock.patch("cozy_jogos.pasta_jogos", return_value=os.path.join(raiz, "Jogos")), \
                    mock.patch("cozy_jogos.pasta_config", return_value=os.path.join(raiz, "cfg")):
                cmd = catalogo_windows.comando(["catalogo:snes"], bases=[raiz])
            self.assertEqual(cmd[0], sys.executable)
            self.assertTrue(cmd[1].endswith("cozy_jogos.py"))
            self.assertEqual(cmd[2:], ["snes", str(exe)])
            cfg = Path(raiz, "cfg", "retroarch.cfg").read_text(encoding="utf-8")
            self.assertIn('video_driver = "gl"', cfg)
            self.assertIn('audio_driver = "wasapi"', cfg)
            self.assertIn('joypad_driver = "sdl2"', cfg)
            self.assertNotIn("joypad_autoconfig_dir", cfg)
            self.assertIn('kiosk_mode_enable = "true"', cfg)
            self.assertIn('input_exit_emulator = "escape"', cfg)
            self.assertIn('menu_show_online_updater = "false"', cfg)
            self.assertTrue((Path(raiz, "Jogos") / "LEIA-ME.txt").is_file())
            self.assertIn("SNES", (Path(raiz, "Jogos") / "LEIA-ME.txt").read_text(encoding="utf-8"))
            item = catalogo_windows.por_id("ps1")
            self.assertEqual(item["winget"], "Libretro.RetroArch")
            self.assertIs(item["sem_moldura"], False)
            nucleos = catalogo_windows.nucleos_retroarch()
            self.assertEqual(catalogo_windows.por_id("snes")["versao"], nucleos["versao"])
            self.assertEqual(item["versao"], nucleos["versao"])
            self.assertTrue(nucleos["url"].startswith(
                "https://buildbot.libretro.com/stable/" + nucleos["versao"] + "/"))
            for chave in ("sha256",):
                self.assertEqual(len(nucleos[chave]), 64)
            for sis in ("snes", "ps1"):
                self.assertEqual(len(nucleos[sis]["sha256"]), 64)
                self.assertTrue(nucleos[sis]["arquivo"].endswith("_libretro.dll"))
            self.assertEqual(len(nucleos["extrator"]["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
