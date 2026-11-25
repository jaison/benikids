"""Coleções do itch.io: gênero, override, preservação e o tile do Windows. Sem rede."""
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

REPOSITORIO = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(REPOSITORIO / "src"))

import application_launcher  # noqa: E402
import itch_sync  # noqa: E402
import jogos_genero  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "itch"
PAGINAS = {
    itch_sync.COLECAO_BEA: "colecao.html",
    itch_sync.COLECAO_BENI: "colecao-beni.html",
    "https://demo.itch.io/dog-wash": "jogo.html",
    "https://demo.itch.io/little-chef-prototype": "jogo.html",
    "https://demo.itch.io/somente-download": "jogo-sem-navegador.html",
    "https://demo.itch.io/mingle": "jogo.html",
    "https://demo.itch.io/pikwip": "jogo.html",
    "https://demo.itch.io/fossil-quest": "jogo.html",
    "https://demo.itch.io/serenitrove": "jogo-unity.html",
    "https://html-classic.itch.zone/html/1001/index.html": "embed.html",
    "https://html-classic.itch.zone/html/2002/index.html": "unity-index.html",
}


def baixar_paginas(paginas):
    def baixar(url, binario=False, tentativas=4):
        if binario:
            if "img.itch.zone" not in url:
                raise urllib.error.URLError(url)
            return b"\x89PNG\r\n\x1a\n"
        nome = paginas.get(url)
        if not nome:
            raise urllib.error.URLError(url)
        return (FIX / nome).read_text(encoding="utf-8")

    return baixar


def ids_itch(perfil):
    return [t["id"] for t in perfil["tiles"] if str(t.get("id", "")).startswith("itch-")]


class ItchSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def rodar(self, cfg, colecoes=None, plataforma="linux", paginas=None, baixar=None):
        cfg_path = self.dir / "config.json"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        antes = cfg_path.read_bytes()
        if colecoes is not None:
            (self.dir / "colecoes.json").write_text(json.dumps(colecoes), encoding="utf-8")
        caminhos = itch_sync.Caminhos(
            config=str(cfg_path),
            colecoes=str(self.dir / "colecoes.json"),
            cache=str(self.dir / "cache.json"),
            capas=str(self.dir / "covers"),
            log=str(self.dir / "itch-sync.log"),
            trava=str(self.dir / "lock"),
            moldura=str(self.dir / "cozy-jogo.html"),
            porta=38431,
        )
        self.caminhos = caminhos
        if baixar is None:
            baixar = baixar_paginas(PAGINAS if paginas is None else paginas)
        itch_sync.sincronizar(caminhos, baixar=baixar, plataforma=plataforma, usar_trava=False)
        novo = json.loads(cfg_path.read_text(encoding="utf-8"))
        log = ""
        if caminhos.log and Path(caminhos.log).exists():
            log = Path(caminhos.log).read_text(encoding="utf-8")
        return novo, log, antes, cfg_path.read_bytes()

    def test_menina_recebe_a_bea_e_menino_a_beni(self):
        cfg = {"profiles": [
            {"id": "ela", "name": "Perfil", "gender": "menina", "tiles": []},
            {"id": "ele", "name": "Perfil", "gender": "menino", "tiles": []},
        ]}
        novo, log, _, _ = self.rodar(cfg)
        ela, ele = novo["profiles"]
        self.assertEqual(ids_itch(ela), ["itch-dog-wash", "itch-little-chef-prototype"])
        self.assertEqual(
            ids_itch(ele),
            ["itch-mingle", "itch-pikwip", "itch-fossil-quest", "itch-serenitrove"],
        )
        for tile in ela["tiles"]:
            if not str(tile["id"]).startswith("itch-"):
                continue
            self.assertTrue(tile["visible"])
            self.assertEqual(tile["category"], "jogos")
            self.assertLessEqual(len(tile["emoji"]), 32)
            self.assertTrue(tile["emoji"].startswith("img:covers/"))
        self.assertEqual(
            [t["id"] for t in ela["tiles"] if t["id"] in jogos_genero.ids("menina")],
            jogos_genero.ids("menina"),
        )
        self.assertTrue(all(
            t["visible"] and t["category"] == "jogos"
            for t in ela["tiles"] if t["id"] in jogos_genero.ids("menina")
        ))
        self.assertFalse(any(t["id"] in jogos_genero.ids("menina") for t in ele["tiles"]))
        self.assertTrue((self.dir / "covers" / "dog-wash.png").is_file())
        self.assertIn("ela: 2 jogo(s) de navegador na coleção (gênero menina)", log)
        self.assertIn("ele: 4 jogo(s) de navegador na coleção (gênero menino)", log)
        self.assertNotIn("itch-somente-download", ids_itch(ela))
        self.assertIn("Somente Download: sem versão de navegador, ignorado", log)
        chef = next(t for t in ela["tiles"] if t["id"] == "itch-little-chef-prototype")
        self.assertEqual(chef["cmd"][0], "navegador-jogos")
        self.assertIn("file://", chef["cmd"][1])
        self.assertIn("cozy-jogo.html#w=960&h=540&u=", chef["cmd"][1])

    def test_json_manda_sobre_o_genero_e_sobre_a_falta_dele(self):
        cfg = {"profiles": [
            {"id": "default", "name": "Perfil", "gender": "menina", "tiles": []},
            {"id": "outro", "name": "Perfil", "tiles": []},
        ]}
        novo, log, _, _ = self.rodar(
            cfg, colecoes={"default": itch_sync.COLECAO_BENI, "outro": itch_sync.COLECAO_BEA},
        )
        self.assertEqual(
            ids_itch(novo["profiles"][0]),
            ["itch-mingle", "itch-pikwip", "itch-fossil-quest", "itch-serenitrove"],
        )
        self.assertEqual(ids_itch(novo["profiles"][1]), ["itch-dog-wash", "itch-little-chef-prototype"])
        self.assertIn("default: 4 jogo(s) de navegador na coleção (itch-colecoes.json)", log)
        self.assertNotIn("default: sem gênero", log)

    def test_perfil_sem_genero_nao_recebe_colecao(self):
        antigo = {
            "id": "itch-dog-wash",
            "label": "Fica",
            "emoji": "🎮",
            "cmd": ["navegador-jogos", "file://antigo"],
            "visible": True,
            "category": "jogos",
        }
        paint = {"id": "paint", "label": "Desenhar", "emoji": "🎨", "cmd": ["tuxpaint"], "visible": True}
        cfg = {"profiles": [
            {"id": "sem", "name": "Perfil", "tiles": [antigo, paint]},
            {"id": "ela", "name": "Perfil", "gender": "menina", "tiles": []},
        ]}
        novo, log, _, _ = self.rodar(cfg)
        self.assertEqual(novo["profiles"][0]["tiles"], [antigo, paint])
        self.assertFalse(any(t["id"] in jogos_genero.ids("menina") for t in novo["profiles"][0]["tiles"]))
        self.assertIn("sem: sem gênero, nenhuma coleção", log)
        self.assertIn("itch-dog-wash", ids_itch(novo["profiles"][1]))

    def test_preserva_o_que_os_pais_mudaram_e_jogo_novo_entra_ligado(self):
        cfg = {"profiles": [{
            "id": "ela",
            "name": "Perfil",
            "gender": "menina",
            "tiles": [{
                "id": "itch-dog-wash",
                "label": "Banho do cachorro",
                "emoji": "🎮",
                "cmd": ["navegador-jogos", "file://antigo"],
                "visible": False,
                "category": "passatempo",
                "gamepad": True,
            }],
        }]}
        novo, _, _, _ = self.rodar(cfg)
        dog = next(t for t in novo["profiles"][0]["tiles"] if t["id"] == "itch-dog-wash")
        chef = next(t for t in novo["profiles"][0]["tiles"] if t["id"] == "itch-little-chef-prototype")
        self.assertFalse(dog["visible"])
        self.assertEqual(dog["category"], "passatempo")
        self.assertEqual(dog["label"], "Banho do cachorro")
        self.assertTrue(dog["gamepad"])
        self.assertTrue(chef["visible"])
        self.assertEqual(chef["category"], "jogos")
        self.assertEqual(chef["label"], "Little Chef: Prototype")

    def test_jogo_removido_da_colecao_some(self):
        paginas = dict(PAGINAS)
        paginas[itch_sync.COLECAO_BEA] = "colecao-sem-dog-wash.html"
        cfg = {"profiles": [{
            "id": "ela",
            "name": "Perfil",
            "gender": "menina",
            "tiles": [
                {"id": "itch-dog-wash", "label": "Dog Wash", "emoji": "🎮",
                 "cmd": ["navegador-jogos", "x"], "visible": True, "category": "jogos"},
                {"id": "itch-little-chef-prototype", "label": "Little Chef: Prototype", "emoji": "🎮",
                 "cmd": ["navegador-jogos", "x"], "visible": True, "category": "jogos"},
                {"id": "paint", "label": "Desenhar", "emoji": "🎨", "cmd": ["tuxpaint"], "visible": True},
            ],
        }]}
        novo, _, _, _ = self.rodar(cfg, paginas=paginas)
        self.assertEqual(
            [t["id"] for t in novo["profiles"][0]["tiles"]],
            ["itch-little-chef-prototype", "paint", *jogos_genero.ids("menina")],
        )

    def test_sem_internet_nada_muda(self):
        def baixar(url, binario=False, tentativas=4):
            raise urllib.error.URLError("sem rede")

        cfg = {"profiles": [{
            "id": "ela", "name": "Perfil", "gender": "menina",
            "tiles": [{"id": "paint", "label": "Desenhar", "emoji": "🎨",
                       "cmd": ["tuxpaint"], "visible": True}],
        }]}
        novo, log, antes, depois = self.rodar(cfg, baixar=baixar)
        # a coleção não entra sem rede; os jogos por gênero não dependem dela
        self.assertNotEqual(antes, depois)
        self.assertEqual(novo["profiles"][0]["tiles"][0], cfg["profiles"][0]["tiles"][0])
        self.assertEqual(
            [t["id"] for t in novo["profiles"][0]["tiles"][1:]],
            jogos_genero.ids("menina"),
        )
        self.assertFalse(any(str(t["id"]).startswith("itch-") for t in novo["profiles"][0]["tiles"]))
        self.assertIn("mantendo como está", log)
        self.assertIn("jogo(s) por gênero acrescentado(s)", log)
        self.assertIn("config.json atualizado", log)
        self.assertFalse((self.dir / "cache.json").exists())

    def test_pagina_inesperada_nao_apaga_os_jogos(self):
        def baixar(url, binario=False, tentativas=4):
            return "<html>acesso negado</html>"

        tile = {"id": "itch-dog-wash", "label": "Dog Wash", "emoji": "🎮",
                "cmd": ["navegador-jogos", "x"], "visible": True, "category": "jogos"}
        cfg = {"profiles": [{"id": "ela", "name": "Perfil", "gender": "menina", "tiles": [tile]}]}
        novo, log, _, _ = self.rodar(cfg, baixar=baixar)
        self.assertEqual(novo["profiles"][0]["tiles"][0], tile)
        self.assertEqual(
            [t["id"] for t in novo["profiles"][0]["tiles"][1:]],
            jogos_genero.ids("menina"),
        )
        self.assertIn("formato inesperado", log)

    def test_tile_do_windows_abre_no_edge_como_os_sites(self):
        cfg = {"profiles": [{"id": "ela", "name": "Perfil", "gender": "menina", "tiles": []}]}
        novo, _, _, _ = self.rodar(cfg, plataforma="windows")
        tiles = {t["id"]: t for t in novo["profiles"][0]["tiles"]}
        dog = tiles["itch-dog-wash"]
        self.assertEqual(dog["category"], "jogos")
        self.assertTrue(dog["visible"])
        acao = application_launcher.resolve_tile_action(dog)
        self.assertEqual(acao["type"], "web")
        self.assertEqual(acao["mode"], "external")
        self.assertTrue(dog["cmd"][0].startswith("special:external-browser:benikids-jogo:#w=960&h=540&u="))
        self.assertTrue(acao["url"].startswith("file:///"))
        self.assertIn("/jogo.html#w=960&h=540&u=", acao["url"])
        self.assertNotIn("127.0.0.1", acao["url"])
        self.assertLessEqual(len(dog["cmd"][0]), 2048)
        comando = application_launcher.external_browser_command(
            "msedge.exe", acao["url"], str(self.dir / "edge"), profile_id="ela",
        )
        self.assertEqual(comando[-2:], ["--kiosk", "--app=" + acao["url"]])
        unity = tiles["itch-little-chef-prototype"]
        # os dois jogos de exemplo usam a mesma página; a faixa do Unity é a do beni
        beni = {"profiles": [{"id": "ele", "name": "Perfil", "gender": "menino", "tiles": []}]}
        # segunda sincronização no mesmo diretório: o cache já tem os jogos da bea
        novo_b, _, _, _ = self.rodar(beni, plataforma="windows")
        seren = next(t for t in novo_b["profiles"][0]["tiles"] if t["id"] == "itch-serenitrove")
        url = application_launcher.resolve_tile_action(seren)["url"]
        self.assertIn("/jogo.html#w=960&h=540&fh=578&u=", url)
        self.assertTrue(url.startswith("file:///"))
        self.assertTrue(seren["cmd"][0].startswith("special:external-browser:benikids-jogo:#"))
        self.assertNotIn("navegador-jogos", dog["cmd"])
        self.assertNotIn("navegador-jogos", unity["cmd"])
        boneca = tiles["bea-dollmaker"]
        self.assertTrue(boneca["cmd"][0].startswith(
            "special:external-browser:benikids-jogo:#w=960&h=540&u="
        ))
        self.assertNotIn("bea-dollmaker", [t["id"] for t in novo_b["profiles"][0]["tiles"]])

    def test_moldura_codifica_acento_e_converte_o_comando_velho(self):
        frag = "w=960&h=540&u=https%3A%2F%2Fhtml-classic.itch.zone%2Fhtml%2F1%2Findex.html"
        caminho = (
            "C:/Users/Lívia Kids/Benikids/jogo.html"
            if os.name == "nt"
            else "/home/Lívia Kids/Benikids/jogo.html"
        )
        token = ["special:external-browser:benikids-jogo:#" + frag]
        with mock.patch.object(itch_sync, "caminho_da_moldura", return_value=caminho):
            info = {
                "embed": "https://html-classic.itch.zone/html/1/index.html",
                "w": 960, "h": 540,
            }
            self.assertEqual(
                itch_sync.comando_do_jogo(info, "windows", self.caminhos_minimos()),
                token,
            )
            uri = application_launcher.resolve_tile_action({"cmd": token})["url"]
            self.assertEqual(uri, Path(caminho).as_uri() + "#" + frag)
            self.assertTrue(uri.startswith("file:///"))
            self.assertIn("L%C3%ADvia%20Kids", uri)
            self.assertNotIn("Lívia", uri)
            self.assertNotIn(" ", uri.split("#", 1)[0])
            velho = ["special:external-browser:http://127.0.0.1:38431/jogo.html#" + frag]
            self.assertEqual(
                application_launcher.resolve_tile_action({"cmd": velho})["url"],
                uri,
            )
        linux = itch_sync.comando_do_jogo(
            info, "linux", self.caminhos_minimos(),
        )
        self.assertEqual(linux[0], "navegador-jogos")
        self.assertIn("file://", linux[1])
        self.assertIn("cozy-jogo.html#", linux[1])
        self.assertNotIn("benikids-jogo", linux[1])
        self.assertEqual(itch_sync.converter_comando_gravado(velho), token)
        self.assertIsNone(itch_sync.converter_comando_gravado(linux))
        self.assertIsNone(itch_sync.converter_comando_gravado(
            ["special:external-browser:http://127.0.0.1:38431/sites/phet.html"]
        ))
        self.assertEqual(
            application_launcher.resolve_tile_action(
                {"cmd": ["special:external-browser:http://127.0.0.1:38431/sites/phet.html"]}
            )["url"],
            "http://127.0.0.1:38431/sites/phet.html",
        )

    def caminhos_minimos(self):
        return itch_sync.Caminhos(
            config="", colecoes="", cache="", capas="", log="", trava="",
            moldura=str(self.dir / "cozy-jogo.html"), porta=38431,
        )

    def test_comando_velho_converte_mesmo_sem_rede(self):
        frag = "w=960&h=540&u=https%3A%2F%2Fhtml-classic.itch.zone%2Fhtml%2F1%2Findex.html"
        velho = ["special:external-browser:http://127.0.0.1:49152/jogo.html#" + frag]
        cfg = {"profiles": [{"id": "ela", "name": "Perfil", "gender": "menina", "tiles": [
            {"id": "itch-dog-wash", "label": "Nome dos pais", "emoji": "🎮",
             "cmd": velho, "visible": False, "category": "passatempo"},
            {"id": "bea-dollmaker", "label": "Boneca", "emoji": "🧸",
             "cmd": list(velho), "visible": True, "category": "jogos"},
            {"id": "phet", "label": "Ciências", "emoji": "🔬",
             "cmd": ["special:external-browser:http://127.0.0.1:38431/sites/phet.html"],
             "visible": True, "category": "educativo"},
        ]}]}

        def baixar(url, binario=False, tentativas=4):
            raise urllib.error.URLError("sem rede")

        novo, log, _, _ = self.rodar(cfg, baixar=baixar, plataforma="windows")
        tiles = {t["id"]: t for t in novo["profiles"][0]["tiles"]}
        token = ["special:external-browser:benikids-jogo:#" + frag]
        self.assertEqual(tiles["itch-dog-wash"]["cmd"], token)
        self.assertFalse(tiles["itch-dog-wash"]["visible"])
        self.assertEqual(tiles["itch-dog-wash"]["category"], "passatempo")
        self.assertEqual(tiles["itch-dog-wash"]["label"], "Nome dos pais")
        self.assertEqual(tiles["bea-dollmaker"]["cmd"], token)
        self.assertEqual(
            tiles["phet"]["cmd"],
            ["special:external-browser:http://127.0.0.1:38431/sites/phet.html"],
        )
        self.assertIn("comando(s) antigo(s) de jogo convertido(s) para a moldura local", log)

    def test_rele_o_config_depois_do_download(self):
        cfg = {"profiles": [{
            "id": "ela", "name": "Perfil", "gender": "menina", "timerMinutes": 40,
            "tiles": [{"id": "paint", "label": "Velho", "emoji": "🎨",
                       "cmd": ["tuxpaint"], "visible": True}],
        }]}

        def baixar(url, binario=False, tentativas=4):
            if not binario and url == itch_sync.COLECAO_BEA and not getattr(baixar, "feito", False):
                baixar.feito = True
                atual = json.loads((self.dir / "config.json").read_text(encoding="utf-8"))
                atual["pinHash"] = "hash-dos-pais"
                atual["profiles"][0]["timerMinutes"] = 15
                atual["profiles"][0]["tiles"] = [
                    {"id": "paint", "label": "Novo desenho", "emoji": "🎨",
                     "cmd": ["tuxpaint"], "visible": True},
                    {"id": "itch-dog-wash", "label": "Banho", "emoji": "🎮",
                     "cmd": ["navegador-jogos", "x"], "visible": False, "category": "passatempo"},
                ]
                (self.dir / "config.json").write_text(json.dumps(atual), encoding="utf-8")
            return baixar_paginas(PAGINAS)(url, binario=binario, tentativas=tentativas)

        novo, log, _, _ = self.rodar(cfg, baixar=baixar)
        perfil = novo["profiles"][0]
        ids = [t["id"] for t in perfil["tiles"]]
        self.assertEqual(novo["pinHash"], "hash-dos-pais")
        self.assertEqual(perfil["timerMinutes"], 15)
        self.assertEqual(perfil["tiles"][0]["label"], "Novo desenho")
        self.assertLess(ids.index("paint"), ids.index("itch-dog-wash"))
        dog = next(t for t in perfil["tiles"] if t["id"] == "itch-dog-wash")
        self.assertFalse(dog["visible"])
        self.assertEqual(dog["label"], "Banho")
        self.assertEqual(dog["category"], "passatempo")
        self.assertIn("itch-little-chef-prototype", ids)
        self.assertIn("config.json atualizado", log)

    def test_tile_apagado_nao_volta_e_a_ordem_fica(self):
        cfg = {"profiles": [{
            "id": "ela", "name": "Perfil", "gender": "menina",
            "tilesSeen": ["itch-dog-wash", "bea-dollmaker"],
            "tiles": [
                {"id": "paint", "label": "Desenhar", "emoji": "🎨",
                 "cmd": ["tuxpaint"], "visible": True},
                {"id": "itch-little-chef-prototype", "label": "Cozinha", "emoji": "🎮",
                 "cmd": ["navegador-jogos", "x"], "visible": True, "category": "passatempo"},
            ],
        }]}
        novo, _, _, _ = self.rodar(cfg)
        ids = [t["id"] for t in novo["profiles"][0]["tiles"]]
        self.assertNotIn("itch-dog-wash", ids)
        self.assertNotIn("bea-dollmaker", ids)
        self.assertEqual(ids[0], "paint")
        self.assertEqual(ids[1], "itch-little-chef-prototype")
        chef = novo["profiles"][0]["tiles"][1]
        self.assertEqual(chef["label"], "Cozinha")
        self.assertEqual(chef["category"], "passatempo")
        self.assertIn("itch-dog-wash", novo["profiles"][0]["tilesSeen"])
        self.assertIn("bea-kitty", ids)

    def test_id_com_autor_so_quando_o_nome_colide(self):
        embed_b = "https://html-classic.itch.zone/html/2/index.html"
        brutos = [
            {"link": "https://ana.itch.io/platformer",
             "info": {"embed": "https://html-classic.itch.zone/html/1/index.html"}},
            {"link": "https://bia.itch.io/platformer", "info": {"embed": embed_b}},
        ]
        self.assertEqual(
            itch_sync.ids_da_colecao(brutos, []),
            ["itch-platformer", "itch-bia-platformer"],
        )
        frag = "w=1&h=1&u=" + urllib.parse.quote(embed_b, safe="")
        tiles = [{"id": "itch-platformer", "cmd": ["navegador-jogos", "file:///tmp/cozy-jogo.html#" + frag]}]
        self.assertEqual(
            itch_sync.ids_da_colecao(brutos, tiles),
            ["itch-ana-platformer", "itch-platformer"],
        )
        self.assertEqual(
            itch_sync.ids_da_colecao(
                [{"link": "https://demo.itch.io/dog-wash", "info": {"embed": embed_b}}],
                [{"id": "itch-dog-wash", "cmd": ["navegador-jogos", "x"]}],
            ),
            ["itch-dog-wash"],
        )
        self.assertEqual(len(set(itch_sync.ids_da_colecao(brutos, tiles))), 2)

    def test_nao_grava_config_com_id_duplicado(self):
        cfg = {"profiles": [{
            "id": "ela", "name": "Perfil", "gender": "menina", "tiles": [],
        }]}

        def mesclar(tiles_atuais, tiles_colecao, vistos=None):
            tile = {
                "id": "itch-igual", "label": "Igual", "emoji": "🎮",
                "cmd": ["navegador-jogos", "x"], "visible": True, "category": "jogos",
            }
            return [dict(tile), dict(tile)]

        with mock.patch.object(itch_sync, "mesclar_tiles", mesclar):
            novo, log, antes, depois = self.rodar(cfg)
        self.assertEqual(antes, depois)
        self.assertIn("id de tile repetido", log)
        self.assertEqual(novo["profiles"][0]["tiles"], [])

    def test_moldura_so_aceita_https_no_itch_zone(self):
        self.assertTrue(itch_sync.embed_permitido(
            "https://html-classic.itch.zone/html/5076665/itch_1/index.html"))
        self.assertTrue(itch_sync.embed_permitido("https://html.itch.zone/html/1/index.html"))
        self.assertTrue(itch_sync.embed_permitido("https://assets.itch.zone/html/1/index.html"))
        self.assertFalse(itch_sync.embed_permitido("http://html.itch.zone/html/1/index.html"))
        self.assertFalse(itch_sync.embed_permitido("https://evil.com/jogo"))
        self.assertFalse(itch_sync.embed_permitido("https://html.itch.zone.evil.com/jogo"))
        self.assertFalse(itch_sync.embed_permitido("https://itch.zone/jogo"))
        self.assertFalse(itch_sync.embed_permitido("javascript:alert(1)"))
        frag_ok = "w=10&h=10&u=" + urllib.parse.quote(
            "https://html.itch.zone/html/1/index.html", safe="")
        frag_http = "w=10&h=10&u=" + urllib.parse.quote(
            "http://html.itch.zone/html/1/index.html", safe="")
        self.assertTrue(itch_sync._fragmento_valido(frag_ok))
        self.assertFalse(itch_sync._fragmento_valido(frag_http))
        self.assertIsNone(itch_sync.fragmento_da_moldura("benikids-jogo:#" + frag_http))
        moldura = (REPOSITORIO / "src" / "jogo.html").read_text(encoding="utf-8")
        self.assertEqual(
            moldura,
            (REPOSITORIO / "beni" / "chromium" / "cozy-jogo.html").read_text(encoding="utf-8"),
        )
        self.assertIn("enderecoPermitido", moldura)
        self.assertIn("scrolling=\"no\"", moldura)
        self.assertIn("overflow:hidden", moldura)
        sandbox = moldura.split('sandbox="', 1)[1].split('"', 1)[0]
        self.assertNotIn("allow-top-navigation", sandbox)
        self.assertNotIn("allow-popups", sandbox)
        self.assertNotIn("allow-downloads", sandbox)
        self.assertIn("pad=", moldura)

    def test_file_uri_codifica_o_caminho_no_linux(self):
        info = {
            "embed": "https://html-classic.itch.zone/html/1/index.html",
            "w": 960, "h": 540,
        }
        caminho = "/home/Lívia Kids/cozy-jogo.html"
        caminhos = self.caminhos_minimos()
        caminhos.moldura = caminho
        cmd = itch_sync.comando_do_jogo(info, "linux", caminhos)
        base, frag = cmd[1].split("#", 1)
        self.assertEqual(base, Path(caminho).as_uri())
        self.assertNotIn(" ", base)
        self.assertNotIn("Lívia", base)
        self.assertTrue(itch_sync._fragmento_valido(frag))
        antigo = ["navegador-jogos", "file:///home/Lívia Kids/cozy-jogo.html#" + frag]
        self.assertEqual(
            itch_sync.atualizar_uri_da_moldura(antigo, caminho),
            cmd,
        )

    def test_segunda_sincronizacao_nao_regrava(self):
        cfg = {"profiles": [{"id": "ela", "name": "Perfil", "gender": "menina", "tiles": []}]}
        self.rodar(cfg)
        _, log, _, _ = self.rodar(json.loads((self.dir / "config.json").read_text(encoding="utf-8")))
        self.assertIn("nada mudou", log)

    def test_agenda_dois_minutos_depois_e_a_cada_trinta(self):
        esperas = []
        chamadas = []

        def esperar(segundos):
            esperas.append(segundos)
            if len(esperas) >= 3:
                raise StopIteration

        with self.assertRaises(StopIteration):
            itch_sync.loop(lambda: chamadas.append(1), esperar)
        self.assertEqual(esperas, [120, 1800, 1800])
        self.assertEqual(chamadas, [1, 1])

    def test_429_espera_e_tenta_de_novo(self):
        chamadas = {"n": 0}

        class Corpo:
            def read(self):
                return b"ok"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def urlopen(req, timeout=25):
            chamadas["n"] += 1
            if chamadas["n"] == 1:
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
            return Corpo()

        esperas = []
        with mock.patch.object(itch_sync.urllib.request, "urlopen", urlopen), \
                mock.patch.object(itch_sync, "dormir", lambda segundos: esperas.append(segundos)):
            texto = itch_sync.baixar_rede("https://itch.io/c/1/exemplo")
        self.assertEqual(texto, "ok")
        self.assertEqual(esperas, [10, itch_sync.PAUSA])
        self.assertEqual(itch_sync.PAUSA, 2.5)

    def test_moldura_e_capa_do_menu_nativo(self):
        linux = (REPOSITORIO / "beni" / "chromium" / "cozy-jogo.html").read_text(encoding="utf-8")
        windows = (REPOSITORIO / "src" / "jogo.html").read_text(encoding="utf-8")
        self.assertEqual(linux, windows)
        menu = (REPOSITORIO / "cliente" / "src" / "menu.rs").read_text(encoding="utf-8")
        self.assertIn('emoji.strip_prefix("img:")', menu)
        self.assertIn('app_root.join("themes")', menu)
        servidor = (REPOSITORIO / "src" / "server.py").read_text(encoding="utf-8")
        self.assertIn("itch_sync.iniciar()", servidor)

    def _caminhos(self):
        return itch_sync.Caminhos(
            config=str(self.dir / "config.json"),
            colecoes=str(self.dir / "colecoes.json"),
            cache=str(self.dir / "cache.json"),
            capas=str(self.dir / "covers"),
            log=str(self.dir / "itch-sync.log"),
            trava=str(self.dir / "lock"),
            moldura=str(self.dir / "cozy-jogo.html"),
            porta=38431,
        )

    def test_trava_ocupada_desiste_sem_esperar(self):
        cfg_path = self.dir / "config.json"
        cfg_path.write_text(json.dumps({
            "profiles": [{"id": "ele", "name": "Perfil", "gender": "menino", "tiles": []}],
        }), encoding="utf-8")
        caminhos = self._caminhos()
        Path(caminhos.trava).write_text("99999", encoding="utf-8")

        def nao_dorme(_segundos):
            raise AssertionError("não devia esperar a trava")

        with mock.patch.object(itch_sync, "dormir", nao_dorme):
            codigo = itch_sync.sincronizar(
                caminhos, baixar=baixar_paginas(PAGINAS), plataforma="linux",
            )
        self.assertEqual(codigo, 0)
        log = Path(caminhos.log).read_text(encoding="utf-8")
        self.assertIn("outra sincronização em andamento\n", log)
        self.assertNotIn("esperando para tentar de novo", log)
        self.assertEqual(ids_itch(json.loads(cfg_path.read_text(encoding="utf-8"))["profiles"][0]), [])

    def test_sync_do_perfil_novo_espera_a_trava_e_tenta_de_novo(self):
        cfg_path = self.dir / "config.json"
        cfg_path.write_text(json.dumps({
            "profiles": [{"id": "ele", "name": "Perfil", "gender": "menino", "tiles": []}],
        }), encoding="utf-8")
        caminhos = self._caminhos()
        trava = Path(caminhos.trava)
        trava.write_text("99999", encoding="utf-8")

        def solta(_segundos):
            if trava.exists():
                trava.unlink()

        with mock.patch.object(itch_sync, "dormir", solta):
            codigo = itch_sync.sincronizar(
                caminhos, baixar=baixar_paginas(PAGINAS), plataforma="linux",
                esperar_trava=True, prazo_trava=5,
            )
        self.assertEqual(codigo, 0)
        log = Path(caminhos.log).read_text(encoding="utf-8")
        self.assertIn("esperando para tentar de novo", log)
        perfil = json.loads(cfg_path.read_text(encoding="utf-8"))["profiles"][0]
        self.assertEqual(
            ids_itch(perfil),
            ["itch-mingle", "itch-pikwip", "itch-fossil-quest", "itch-serenitrove"],
        )
        self.assertFalse(trava.exists())


if __name__ == "__main__":
    unittest.main()
