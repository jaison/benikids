"""Coleções do itch.io: gênero, override, preservação e o tile do Windows. Sem rede."""
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

REPOSITORIO = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(REPOSITORIO / "src"))

import application_launcher  # noqa: E402
import itch_sync  # noqa: E402

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
            self.assertTrue(tile["visible"])
            self.assertEqual(tile["category"], "jogos")
            self.assertLessEqual(len(tile["emoji"]), 32)
            self.assertTrue(tile["emoji"].startswith("img:covers/"))
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
            ["itch-little-chef-prototype", "paint"],
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
        self.assertEqual(antes, depois)
        self.assertEqual(novo["profiles"][0]["tiles"], cfg["profiles"][0]["tiles"])
        self.assertIn("mantendo como está", log)
        self.assertNotIn("config.json atualizado", log)
        self.assertFalse((self.dir / "cache.json").exists())

    def test_pagina_inesperada_nao_apaga_os_jogos(self):
        def baixar(url, binario=False, tentativas=4):
            return "<html>acesso negado</html>"

        tile = {"id": "itch-dog-wash", "label": "Dog Wash", "emoji": "🎮",
                "cmd": ["navegador-jogos", "x"], "visible": True, "category": "jogos"}
        cfg = {"profiles": [{"id": "ela", "name": "Perfil", "gender": "menina", "tiles": [tile]}]}
        novo, log, antes, depois = self.rodar(cfg, baixar=baixar)
        self.assertEqual(antes, depois)
        self.assertEqual(novo["profiles"][0]["tiles"], [tile])
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
        self.assertTrue(acao["url"].startswith("http://127.0.0.1:38431/jogo.html#w=960&h=540&u="))
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
        self.assertIn("special:external-browser:", seren["cmd"][0])
        self.assertNotIn("navegador-jogos", dog["cmd"])
        self.assertNotIn("navegador-jogos", unity["cmd"])

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


if __name__ == "__main__":
    unittest.main()
