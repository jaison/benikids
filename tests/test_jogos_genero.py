"""Jogos por gênero e a tradução dos jogos de navegador para o Windows."""
import importlib.machinery
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(RAIZ / "src"))

import application_launcher  # noqa: E402
import jogos_genero  # noqa: E402


def carregar(nome, caminho):
    loader = importlib.machinery.SourceFileLoader(nome, str(caminho))
    spec = importlib.util.spec_from_loader(nome, loader)
    modulo = importlib.util.module_from_spec(spec)
    loader.exec_module(modulo)
    return modulo


migrar = carregar("migrar_jogos", RAIZ / "beni/ferramentas/migrar-config.py")
config_padrao = carregar("config_padrao_jogos", RAIZ / "scripts/windows/config-padrao.py")


class JogosPorGeneroTest(unittest.TestCase):
    def test_menina_recebe_os_quatro_e_menino_nao(self):
        menina = {"id": "ela", "gender": "menina", "tiles": [{"id": "paint", "cmd": ["tuxpaint"]}]}
        menino = {"id": "ele", "gender": "menino", "tiles": [{"id": "paint", "cmd": ["tuxpaint"]}]}
        self.assertEqual(jogos_genero.aplicar_perfil(menina, "linux"), 4)
        self.assertEqual(jogos_genero.aplicar_perfil(menino, "linux"), 0)
        self.assertEqual(
            [t["id"] for t in menina["tiles"] if t["id"] != "paint"],
            ["bea-dollmaker", "bea-kitty", "bea-darling", "bea-missy"],
        )
        for tile in menina["tiles"]:
            if tile["id"].startswith("bea-"):
                self.assertTrue(tile["visible"])
                self.assertEqual(tile["category"], "jogos")
                self.assertEqual(tile["cmd"][0], "navegador-jogos")
                self.assertIn("cozy-jogo.html#", tile["cmd"][1])
        self.assertEqual([t["id"] for t in menino["tiles"]], ["paint"])
        vistos = set(menina["tilesSeen"])
        self.assertTrue({"bea-dollmaker", "bea-kitty", "bea-darling", "bea-missy"} <= vistos)
        cmds = {t["id"]: t["cmd"][1] for t in menina["tiles"] if t["id"].startswith("bea-")}
        self.assertIn("pad=20", cmds["bea-darling"])
        self.assertIn("pad=20", cmds["bea-missy"])
        self.assertNotIn("pad=", cmds["bea-dollmaker"])
        self.assertNotIn("pad=", cmds["bea-kitty"])

    def test_folga_entra_no_comando_que_ja_existe(self):
        perfil = {
            "id": "ela", "gender": "menina",
            "tiles": [{
                "id": "bea-darling", "label": "Nome dos pais", "emoji": "💄",
                "cmd": ["navegador-jogos",
                        "file:///tmp/cozy-jogo.html#w=1366&h=768&u=https%3A%2F%2Fhtml-classic.itch.zone%2Fhtml%2F1%2Findex.html"],
                "visible": False, "category": "passatempo",
            }],
        }
        self.assertEqual(jogos_genero.aplicar_perfil(perfil, "linux"), 3)
        darling = next(t for t in perfil["tiles"] if t["id"] == "bea-darling")
        self.assertIn("pad=20", darling["cmd"][1])
        self.assertFalse(darling["visible"])
        self.assertEqual(darling["label"], "Nome dos pais")
        self.assertEqual(darling["category"], "passatempo")
        self.assertEqual(perfil["tiles"][0]["id"], "bea-darling")

    def test_jogo_apagado_nao_volta(self):
        perfil = {
            "id": "ela", "gender": "menina", "tilesSeen": ["bea-darling"],
            "tiles": [{"id": "paint", "cmd": ["tuxpaint"]}],
        }
        self.assertEqual(jogos_genero.aplicar_perfil(perfil, "linux"), 3)
        ids = [t["id"] for t in perfil["tiles"]]
        self.assertNotIn("bea-darling", ids)
        self.assertIn("bea-missy", ids)
        self.assertEqual(jogos_genero.aplicar_perfil(perfil, "linux"), 0)
        self.assertNotIn("bea-darling", [t["id"] for t in perfil["tiles"]])

    def test_perfil_sem_gender_nao_muda(self):
        perfil = {"id": "sem", "tiles": [{"id": "paint", "visible": True}]}
        antes = json.dumps(perfil)
        self.assertEqual(jogos_genero.aplicar_perfil(perfil, "linux"), 0)
        self.assertEqual(jogos_genero.aplicar_perfil(perfil, "windows"), 0)
        self.assertEqual(json.dumps(perfil), antes)

    def test_migracao_preserva_o_tile_oculto(self):
        oculto = {
            "id": "bea-dollmaker", "label": "Nome dos pais", "emoji": "🧸",
            "cmd": ["navegador-jogos", "file://escolha-dos-pais"],
            "visible": False, "category": "passatempo",
        }
        cfg = {"profiles": [
            {"id": "ela", "gender": "menina", "tiles": [dict(oculto)]},
            {"id": "ele", "gender": "menino", "tiles": [{"id": "paint"}]},
            {"id": "sem", "tiles": [{"id": "paint"}]},
        ]}
        op = {"op": "adicionar_por_genero", "perfis": "todos"}
        self.assertEqual(migrar.apply_op(cfg, op), 3)
        self.assertEqual(migrar.apply_op(cfg, op), 0)
        tiles = cfg["profiles"][0]["tiles"]
        self.assertEqual(tiles[0], oculto)
        self.assertEqual(
            [t["id"] for t in tiles],
            ["bea-dollmaker", "bea-kitty", "bea-darling", "bea-missy"],
        )
        self.assertEqual(cfg["profiles"][1]["tiles"], [{"id": "paint"}])
        self.assertEqual(cfg["profiles"][2]["tiles"], [{"id": "paint"}])

    def test_windows_abre_na_moldura_como_a_colecao(self):
        perfil = {"id": "ela", "gender": "menina", "tiles": []}
        jogos_genero.aplicar_perfil(perfil, "windows", porta=38431)
        boneca = perfil["tiles"][0]
        self.assertEqual(boneca["id"], "bea-dollmaker")
        self.assertTrue(boneca["cmd"][0].startswith(
            "special:external-browser:benikids-jogo:#w=960&h=540&u="
        ))
        acao = application_launcher.resolve_tile_action(boneca)
        self.assertEqual(acao["type"], "web")
        self.assertEqual(acao["mode"], "external")
        with tempfile.TemporaryDirectory() as cache:
            comando = application_launcher.external_browser_command(
                "msedge.exe", acao["url"], cache, profile_id="ela",
            )
        self.assertEqual(comando[-2:], ["--kiosk", "--app=" + acao["url"]])

    def test_menino_nao_herda_os_jogos_do_modelo(self):
        modelo = {"gender": "menina", "tiles": []}
        jogos_genero.aplicar_perfil(modelo, "linux")
        menino = json.loads(json.dumps(modelo))
        menino["gender"] = "menino"
        jogos_genero.retirar_de_outros_generos(menino)
        jogos_genero.aplicar_perfil(menino, "linux")
        self.assertEqual(menino["tiles"], [])

    def test_trocar_genero_tira_bea_visivel_e_respeita_oculto_e_apagado(self):
        perfil = {
            "id": "ela",
            "gender": "menino",
            "tilesSeen": ["bea-dollmaker", "bea-kitty", "bea-darling", "bea-missy"],
            "tiles": [
                {"id": "paint", "visible": True, "label": "Desenhar"},
                {"id": "bea-dollmaker", "visible": True, "label": "Boneca"},
                {"id": "bea-kitty", "visible": False, "label": "Escondido"},
            ],
        }
        jogos_genero.trocar_genero(perfil, "linux")
        ids = [t["id"] for t in perfil["tiles"]]
        self.assertEqual(ids, ["paint", "bea-kitty"])
        self.assertFalse(perfil["tiles"][1]["visible"])
        self.assertEqual(perfil["tiles"][1]["label"], "Escondido")
        self.assertNotIn("bea-dollmaker", perfil["tilesSeen"])
        self.assertIn("bea-darling", perfil["tilesSeen"])
        self.assertIn("bea-missy", perfil["tilesSeen"])

        perfil["gender"] = "menina"
        jogos_genero.trocar_genero(perfil, "linux")
        por_id = {t["id"]: t for t in perfil["tiles"]}
        self.assertTrue(por_id["bea-dollmaker"]["visible"])
        self.assertFalse(por_id["bea-kitty"]["visible"])
        self.assertEqual(por_id["bea-kitty"]["label"], "Escondido")
        self.assertNotIn("bea-darling", por_id)
        self.assertNotIn("bea-missy", por_id)
        self.assertEqual(perfil["tiles"][0]["id"], "paint")

    def test_trocar_para_menina_no_windows_abre_na_moldura(self):
        perfil = {"id": "ele", "gender": "menina", "tiles": [{"id": "paint", "visible": True}]}
        jogos_genero.trocar_genero(perfil, "windows")
        boneca = next(t for t in perfil["tiles"] if t["id"] == "bea-dollmaker")
        self.assertTrue(boneca["cmd"][0].startswith(
            "special:external-browser:benikids-jogo:#"
        ))


class NavegadorJogosWindowsTest(unittest.TestCase):
    def test_site_abre_direto_e_moldura_vai_para_jogo_html(self):
        self.assertEqual(
            jogos_genero.traduzir_navegador_jogos(
                ["navegador-jogos", "https://boom.rabisco.net/"]
            ),
            ["special:external-browser:https://boom.rabisco.net/"],
        )
        frag = "w=960&h=540&u=https%3A%2F%2Fhtml-classic.itch.zone%2Fhtml%2F1%2Findex.html"
        self.assertEqual(
            jogos_genero.traduzir_navegador_jogos(
                ["navegador-jogos", "file:///tmp/cozy-jogo.html#" + frag]
            ),
            ["special:external-browser:benikids-jogo:#" + frag],
        )
        self.assertIsNone(jogos_genero.traduzir_navegador_jogos(["tuxpaint"]))

    def test_config_padrao_copia_visibilidade_do_linux(self):
        with tempfile.TemporaryDirectory() as tmp:
            saida = str(Path(tmp) / "config.json")
            config_padrao.main(saida)
            cfg = json.loads(Path(saida).read_text(encoding="utf-8"))
        perfil = cfg["profiles"][0]
        tiles = {t["id"]: t for t in perfil["tiles"]}
        self.assertNotIn("bea-dollmaker", tiles)
        visiveis = ("rb-boom", "rb-fight", "rb-guerra", "rb-ultimo", "rb-eldoria", "rb-fliperama")
        ocultos = ("rb-arena", "rb-corrida", "rb-ovo")
        for jogo in visiveis:
            self.assertTrue(tiles[jogo]["visible"], jogo)
            self.assertEqual(tiles[jogo]["category"], "jogos")
            self.assertEqual(
                tiles[jogo]["cmd"],
                ["special:external-browser:https://%s/" % {
                    "rb-boom": "boom.rabisco.net",
                    "rb-fight": "fight.rabisco.net",
                    "rb-guerra": "guerra.rabisco.net",
                    "rb-ultimo": "ultimo.rabisco.net",
                    "rb-eldoria": "eldoria.rabisco.net",
                    "rb-fliperama": "fliperama.rabisco.net",
                }[jogo]],
            )
        for jogo in ocultos:
            self.assertFalse(tiles[jogo]["visible"], jogo)
            self.assertEqual(tiles[jogo]["category"], "jogos")
            self.assertTrue(tiles[jogo]["cmd"][0].startswith("special:external-browser:https://"))


if __name__ == "__main__":
    unittest.main()
