"""Sites special: chegam uma vez ao Windows já instalado e não voltam se apagados."""

import json
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

import sites_windows as sites  # noqa: E402
from config_validation import validate_stored_config  # noqa: E402


def tile(ident, cmd="special:external-browser:https://exemplo.org/"):
    return {"id": ident, "label": ident, "emoji": "🌐", "cmd": [cmd],
            "visible": True, "category": "educativo"}


def config(tiles, **extra):
    cfg = {"configVersion": 2, "activeProfileId": "a", "profiles": [
        {"id": "a", "name": "Ana", "tiles": list(tiles)},
        {"id": "b", "name": "Bia", "tiles": []},
    ]}
    cfg.update(extra)
    return cfg


class SitesWindowsTest(unittest.TestCase):
    def test_arquivo_embarcado_bate_com_o_linux(self):
        linux = sites.extrair_dos_arquivos()
        self.assertEqual(sites.carregar(), linux)
        self.assertTrue(linux)
        self.assertEqual([t["id"] for t in linux], list(dict.fromkeys(t["id"] for t in linux)))
        for tile_site in linux:
            self.assertTrue(sites.e_site(tile_site))

    def test_base_e_subconjunto_do_que_ja_esta_no_pacote(self):
        # Não compare com igualdade: um site novo fica só no tiles.json, fora da tupla,
        # e é isso que faz o Windows já instalado recebê-lo uma vez.
        ids = {t["id"] for t in sites.carregar()}
        self.assertTrue(set(sites.SITES_JA_ENTREGUES) <= ids)

    def test_site_novo_chega_uma_vez_e_apagado_nao_volta(self):
        antigo = tile("antigo")
        novo = tile("novo")
        lista = [antigo, novo]
        cfg, mudou = sites.sincronizar(config([antigo]), lista, ja_entregues=("antigo",))
        self.assertTrue(mudou)
        self.assertEqual([t["id"] for t in cfg["profiles"][0]["tiles"]], ["antigo", "novo"])
        self.assertEqual([t["id"] for t in cfg["profiles"][1]["tiles"]], ["novo"])
        self.assertEqual(cfg["sitesSeen"], ["antigo", "novo"])
        validate_stored_config(cfg, existing_pin_hash="", allow_pin_hash=True)
        de_novo, mudou = sites.sincronizar(cfg, lista, ja_entregues=("antigo",))
        self.assertFalse(mudou)
        self.assertIs(de_novo, cfg)
        cfg["profiles"][0]["tiles"] = [antigo]
        cfg["profiles"][1]["tiles"] = []
        parado, mudou = sites.sincronizar(cfg, lista, ja_entregues=("antigo",))
        self.assertFalse(mudou)
        self.assertEqual(parado["profiles"][1]["tiles"], [])

    def test_site_apagado_antes_desta_funcao_nao_volta(self):
        antigo = tile("antigo")
        cfg, mudou = sites.sincronizar(config([]), [antigo], ja_entregues=("antigo",))
        self.assertTrue(mudou)  # grava sitesSeen, sem recolocar o tile
        self.assertEqual(cfg["profiles"][0]["tiles"], [])
        self.assertEqual(cfg["sitesSeen"], ["antigo"])

    def test_app_do_linux_nao_entra(self):
        app = {"id": "neverball", "label": "Bola", "emoji": "🔵", "cmd": ["neverball"],
               "visible": True, "category": "jogos"}
        cfg, mudou = sites.sincronizar(config([]), [app, tile("novo")], ja_entregues=())
        self.assertEqual([t["id"] for t in cfg["profiles"][0]["tiles"]], ["novo"])
        self.assertNotIn("neverball", cfg["sitesSeen"])

    def test_migracao_de_site_entra_na_lista(self):
        extraidos = sites.extrair(
            {"profiles": [{"tiles": [tile("ja")]}]},
            {"migracoes": [{"operacoes": [
                {"op": "adicionar_tile", "tile": tile("vindo-da-migracao")},
                {"op": "adicionar_tile", "tile": {"id": "app", "cmd": ["neverball"]}},
            ]}]},
        )
        self.assertEqual([t["id"] for t in extraidos], ["ja", "vindo-da-migracao"])

    def test_css_da_extensao_repete_o_do_firefox(self):
        firefox = (RAIZ / "beni" / "firefox" / "userContent.css").read_text()
        copia = (RAIZ / "src" / "firefox" / "userContent.css").read_text()
        self.assertEqual(firefox, copia)
        extensao = RAIZ / "src" / "edge" / "sites-limpos"
        manifesto = json.loads((extensao / "manifest.json").read_text())
        self.assertEqual(manifesto["manifest_version"], 3)
        juntos = "\n".join((extensao / nome).read_text() for nome in (
            "escolagames.css", "colorir.css", "autodraw.css"))
        for seletor in (
            'a[href*="/jogos-divertidos"]',
            '[data-hideable-key="jogos-em-ingles"]',
            "header, .oxy-header-wrapper, footer",
            "#main-menu > ul > li:nth-child(3)",
            "#aix-link",
        ):
            self.assertIn(seletor, firefox)
            self.assertIn(seletor, juntos)


if __name__ == "__main__":
    unittest.main()
