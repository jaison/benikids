import json
import sys
import unittest
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

import config_store
import config_validation
import jogos_genero
import profile_config


def legacy_config():
    return {
        "configVersion": 1,
        "language": "en",
        "pinHash": "",
        "title": "Hello Kiddo",
        "theme": "rosa",
        "layoutMode": "gross",
        "currentPage": 0,
        "timerMinutes": 30,
        "timerWarningMinutes": 5,
        "tiles": [{
            "id": "paint",
            "label": "Paint",
            "emoji": "🎨",
            "cmd": ["tuxpaint"],
            "visible": True,
        }],
    }


class ProfileConfigTests(unittest.TestCase):
    def test_schema_one_becomes_a_complete_default_profile(self):
        stored, migrated = config_store.migrate_config(legacy_config())

        self.assertTrue(migrated)
        self.assertEqual(stored["configVersion"], 2)
        self.assertEqual(stored["activeProfileId"], "default")
        self.assertEqual(stored["profiles"][0]["title"], "Hello Kiddo")
        self.assertEqual(stored["profiles"][0]["tiles"][0]["id"], "paint")
        self.assertNotIn("tiles", stored)

    def test_active_projection_preserves_the_existing_runtime_contract(self):
        stored = config_validation.validate_stored_config(legacy_config())
        runtime = profile_config.active_config(stored)

        self.assertEqual(runtime["title"], "Hello Kiddo")
        self.assertEqual(runtime["tiles"][0]["cmd"], ["tuxpaint"])
        self.assertEqual(
            runtime["profiles"],
            [{"id": "default", "name": "Kiddo", "avatar": "🌈"}],
        )

    def test_profiles_keep_tiles_themes_favorites_and_limits_independent(self):
        stored = config_validation.validate_stored_config(legacy_config())
        stored, second_id = profile_config.add_profile(
            stored,
            "Alex",
            "🚀",
            profile_id="alex",
            gender="menino",
        )
        stored = config_validation.validate_stored_config(stored)
        stored = profile_config.select_profile(stored, second_id)
        alex = profile_config.active_config(stored)
        alex["theme"] = "blau"
        alex["themeMotionEnabled"] = True
        alex["themeTimeOfDayEnabled"] = True
        alex["soundFeedbackEnabled"] = True
        alex["speechFeedbackEnabled"] = True
        alex["celebrationEnabled"] = True
        alex["accessibilityLargeText"] = True
        alex["accessibilityHighContrast"] = True
        alex["accessibilityReducedMotion"] = True
        alex["accessibilityKeyboardFocus"] = True
        alex["tiles"][0]["label"] = "Alex Paint"
        alex["favorites"] = ["paint"]
        alex["appLimits"] = {"paint": 20}
        alex["weeklySchedule"] = {
            "enabled": True,
            "days": {"monday": [{"start": "08:00", "end": "18:00"}]},
        }
        alex["appAvailability"] = {
            "paint": {
                "enabled": True,
                "days": {"monday": [{"start": "09:00", "end": "12:00"}]},
            },
        }
        stored = profile_config.merge_active_config(stored, alex)
        stored = config_validation.validate_stored_config(stored)

        default = profile_config.active_config(
            profile_config.select_profile(stored, "default")
        )
        alex = profile_config.active_config(stored)
        self.assertEqual(default["theme"], "rosa")
        self.assertEqual(default["tiles"][0]["label"], "Paint")
        self.assertEqual(default["favorites"], [])
        self.assertEqual(alex["theme"], "blau")
        self.assertNotIn("themeMotionEnabled", default)
        self.assertNotIn("soundFeedbackEnabled", default)
        self.assertNotIn("celebrationEnabled", default)
        self.assertNotIn("accessibilityLargeText", default)
        self.assertTrue(alex["themeMotionEnabled"])
        self.assertTrue(alex["themeTimeOfDayEnabled"])
        self.assertTrue(alex["soundFeedbackEnabled"])
        self.assertTrue(alex["speechFeedbackEnabled"])
        self.assertTrue(alex["celebrationEnabled"])
        self.assertTrue(alex["accessibilityLargeText"])
        self.assertTrue(alex["accessibilityHighContrast"])
        self.assertTrue(alex["accessibilityReducedMotion"])
        self.assertTrue(alex["accessibilityKeyboardFocus"])
        self.assertEqual(alex["favorites"], ["paint"])
        self.assertEqual(alex["appLimits"], {"paint": 20})
        self.assertTrue(alex["weeklySchedule"]["enabled"])
        self.assertIn("paint", alex["appAvailability"])

    def test_active_and_last_profile_deletion_is_rejected(self):
        stored = config_validation.validate_stored_config(legacy_config())
        with self.assertRaisesRegex(ValueError, "active profile"):
            profile_config.remove_profile(stored, "default")

        stored, _ = profile_config.add_profile(
            stored,
            "Alex",
            profile_id="alex",
            gender="menino",
        )
        stored = profile_config.remove_profile(stored, "alex")
        self.assertEqual(len(stored["profiles"]), 1)

    def test_profile_collections_and_limits_are_bounded(self):
        stored = config_validation.validate_stored_config(legacy_config())
        stored["profiles"][0]["favorites"] = ["bad id"]
        with self.assertRaisesRegex(ValueError, "favorites"):
            config_validation.validate_stored_config(stored)

        stored = config_validation.validate_stored_config(legacy_config())
        stored["profiles"][0]["appLimits"] = {"paint": 181}
        with self.assertRaisesRegex(ValueError, "appLimits.paint"):
            config_validation.validate_stored_config(stored)

        stored = config_validation.validate_stored_config(legacy_config())
        stored["tiles"] = []
        with self.assertRaisesRegex(ValueError, "inside profiles"):
            config_validation.validate_stored_config(stored)


class NovoPerfilPorGeneroTests(unittest.TestCase):
    def ativa_menina(self):
        stored = config_validation.validate_stored_config(legacy_config())
        perfil = stored["profiles"][0]
        perfil["gender"] = "menina"
        perfil["timerMinutes"] = 5
        perfil["categoryLimits"] = {
            "enabled": True,
            "totalMinutes": 15,
            "categories": {"jogos": {"minutes": 10}},
        }
        perfil["tiles"] = [
            {
                "id": "bea-dollmaker", "label": "Boneca", "emoji": "🧸",
                "cmd": ["navegador-jogos", "file:///tmp/x"],
                "visible": True, "category": "jogos",
            },
            {
                "id": "so-desta", "label": "Só desta", "emoji": "⭐",
                "cmd": ["echo", "oi"], "visible": True, "category": "jogos",
            },
        ]
        return config_validation.validate_stored_config(stored)

    def novo(self, gender, plataforma):
        stored, profile_id = profile_config.add_profile(
            self.ativa_menina(),
            "Novo",
            gender=gender,
            plataforma=plataforma,
            profile_id="novo",
        )
        stored = config_validation.validate_stored_config(stored)
        perfil = next(p for p in stored["profiles"] if p["id"] == profile_id)
        self.assertEqual(stored["profiles"][0]["timerMinutes"], 5)
        self.assertEqual(stored["profiles"][0]["gender"], "menina")
        return perfil

    def test_menino_nao_copia_a_menina_ativa(self):
        for plataforma in ("linux", "windows"):
            perfil = self.novo("menino", plataforma)
            ids = [t["id"] for t in perfil["tiles"]]
            self.assertEqual(perfil["gender"], "menino", plataforma)
            self.assertFalse(any(i.startswith("bea-") for i in ids), plataforma)
            self.assertNotIn("so-desta", ids)
            self.assertEqual(perfil["timerMinutes"], 30)
            self.assertEqual(perfil["categoryLimits"]["totalMinutes"], 60)
            arena = next(t for t in perfil["tiles"] if t["id"] == "rb-arena")
            self.assertFalse(arena["visible"])

    def test_menina_recebe_os_jogos_bea_do_padrao(self):
        for plataforma in ("linux", "windows"):
            perfil = self.novo("menina", plataforma)
            ids = [t["id"] for t in perfil["tiles"]]
            for jogo in jogos_genero.ids("menina"):
                self.assertIn(jogo, ids, plataforma)
            self.assertNotIn("so-desta", ids)
            boneca = next(t for t in perfil["tiles"] if t["id"] == "bea-dollmaker")
            self.assertTrue(boneca["visible"])
            if plataforma == "windows":
                self.assertTrue(boneca["cmd"][0].startswith(
                    "special:external-browser:benikids-jogo:#"
                ))
                self.assertTrue(any(t["id"] == "ktuberling" for t in perfil["tiles"]))
                self.assertFalse(any(t["id"] == "games" for t in perfil["tiles"]))
            else:
                self.assertEqual(boneca["cmd"][0], "navegador-jogos")
                self.assertTrue(any(t["id"] == "games" for t in perfil["tiles"]))
                self.assertFalse(any(
                    isinstance(t.get("cmd"), list) and t["cmd"]
                    and str(t["cmd"][0]).startswith("catalogo:")
                    for t in perfil["tiles"]
                ))

    def test_menino_no_windows_tem_os_mesmos_tiles_do_config_padrao(self):
        import importlib.machinery
        import importlib.util
        import tempfile
        from pathlib import Path

        caminho = Path(__file__).resolve().parents[1] / "scripts/windows/config-padrao.py"
        loader = importlib.machinery.SourceFileLoader("config_padrao_perfil", str(caminho))
        spec = importlib.util.spec_from_loader("config_padrao_perfil", loader)
        modulo = importlib.util.module_from_spec(spec)
        loader.exec_module(modulo)
        with tempfile.TemporaryDirectory() as tmp:
            saida = str(Path(tmp) / "config.json")
            modulo.main(saida)
            padrao = json.loads(Path(saida).read_text(encoding="utf-8"))
        perfil = self.novo("menino", "windows")
        self.assertEqual(
            [t["id"] for t in perfil["tiles"]],
            [t["id"] for t in padrao["profiles"][0]["tiles"]],
        )

    def test_sem_genero_nao_cria(self):
        stored = config_validation.validate_stored_config(legacy_config())
        with self.assertRaisesRegex(ValueError, "menino ou menina"):
            profile_config.add_profile(stored, "Novo", gender="")


if __name__ == "__main__":
    unittest.main()
