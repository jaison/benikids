"""Navegação de topo de cada tile: domínios, regras e o caso do PhET."""

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

import navegacao_sites as nav  # noqa: E402
from application_launcher import (  # noqa: E402
    CHROMIUM_RECURSOS_DESLIGADOS,
    external_browser_command,
    flags_do_chromium,
)

PREFIXO = "special:external-browser:"
PHET = "http://127.0.0.1:38431/sites/phet.html"
SIM = "https://phet.colorado.edu/sims/html/balancing-act/latest/balancing-act_pt_BR.html"


def urls_dos_tiles():
    tiles = json.loads((RAIZ / "src" / "sites" / "tiles.json").read_text())["tiles"]
    saida = []
    for tile in tiles:
        cmd = tile["cmd"][0]
        if cmd.startswith(PREFIXO):
            saida.append((tile["id"], cmd[len(PREFIXO):]))
    return saida


class LimitesTest(unittest.TestCase):
    def test_cada_tile_abre_e_nao_sai_do_dominio(self):
        self.assertGreaterEqual(len(urls_dos_tiles()), 15)
        for ident, url in urls_dos_tiles():
            limites = nav.limites_da_url(url)
            self.assertTrue(nav.permite(url, limites), ident)
            self.assertFalse(nav.permite("https://www.pinterest.com/pin/create/button/", limites), ident)
            self.assertFalse(nav.permite("https://www.givecampus.com/schools/x/donations/new", limites), ident)
            if "127.0.0.1" not in url:
                self.assertFalse(nav.permite("http://127.0.0.1:38431/index.html", limites), ident)
            self.assertNotIn(" ", nav.regex_host("kiddogames.fun"))

    def test_kiddo_fica_no_site_e_o_compartilhar_nao(self):
        url = "https://kiddogames.fun/"
        limites = nav.limites_da_url(url)
        self.assertEqual(limites["resumo"], "kiddogames.fun")
        self.assertTrue(nav.permite("https://kiddogames.fun/jogo/1", limites))
        self.assertTrue(nav.permite("https://play.kiddogames.fun/a", limites))
        for fora in (
            "https://www.pinterest.com/pin/create/button/?url=https://kiddogames.fun/",
            "https://twitter.com/intent/tweet?text=oi",
            "https://www.facebook.com/sharer/sharer.php?u=https://kiddogames.fun/",
            "https://x.com/intent/post",
            "https://kiddogames.fun.evil.com/",
            "https://evilkiddogames.fun/",
            "https://fonts.googleapis.com/css?family=A",
        ):
            self.assertFalse(nav.permite(fora, limites), fora)

    def test_phet_so_a_simulacao(self):
        limites = nav.limites_da_url(PHET)
        self.assertIn("sims/html", limites["resumo"])
        self.assertTrue(nav.permite(PHET, limites))
        self.assertTrue(nav.permite(SIM, limites))
        self.assertTrue(nav.permite("https://phet.colorado.edu/sims/html/friction/latest/friction_pt_BR.html", limites))
        self.assertTrue(nav.permite("http://phet.colorado.edu/sims/html/friction/latest/friction_all.html?locale=pt_BR", limites))
        for bloqueado in (
            "https://phet.colorado.edu/pt_BR/simulations/filter?subjects=physics&levels=elementary-school&type=html",
            "https://phet.colorado.edu/",
            "https://phet.colorado.edu/pt_BR/sign-in",
            "https://phet.colorado.edu/donate",
            "https://phet.colorado.edu/en/studio",
            "https://phet.colorado.edu/pt_BR/simulations/balancing-act",
            "https://www.givecampus.com/schools/UniversityofColoradoFoundation/donations/new",
            "http://127.0.0.1:38431/index.html",
            "http://127.0.0.1:38431/sites/outro.html",
            "https://phet.colorado.edu.evil.com/sims/html/friction/",
        ):
            self.assertFalse(nav.permite(bloqueado, limites), bloqueado)

    def test_paginas_que_o_linux_ja_bloqueia_continuam_bloqueadas(self):
        escola = nav.limites_da_url("https://www.escolagames.com.br/")
        self.assertTrue(nav.permite("https://www.escolagames.com.br/jogos/estoura-balao", escola))
        self.assertFalse(nav.permite("https://www.escolagames.com.br/jogos-divertidos", escola))
        self.assertFalse(nav.permite("https://escolagames.com.br/diversao/voo-natalino", escola))
        self.assertFalse(nav.permite("https://www.bestschoolgames.com/", escola))
        colorir = nav.limites_da_url("https://colorir-online.com/")
        self.assertTrue(nav.permite("https://colorir-online.com/desenhos", colorir))
        self.assertFalse(nav.permite("https://colorir-online.com/apps", colorir))
        self.assertFalse(nav.permite("https://www.colorir-online.com/quem-somos", colorir))
        code = nav.limites_da_url("https://studio.code.org/courses?lang=pt-BR")
        self.assertTrue(nav.permite("https://studio.code.org/courses?lang=pt-BR", code))
        self.assertTrue(nav.permite("https://code.org/students", code))
        self.assertFalse(nav.permite("https://code.org/donate", code))
        self.assertFalse(nav.permite("https://donate.code.org/", code))
        self.assertFalse(nav.permite("https://code.org/en-US/donate", code))

    def test_music_lab_nao_abre_outro_experimento_nem_o_atalho(self):
        url = "https://musiclab.chromeexperiments.com/?lang=pt-BR"
        limites = nav.limites_da_url(url)
        self.assertTrue(nav.permite(url, limites))
        self.assertTrue(nav.permite("https://musiclab.chromeexperiments.com/Song-Maker/", limites))
        self.assertFalse(nav.permite("https://g.co/songmaker", limites))
        self.assertFalse(nav.permite("https://chromeexperiments.com/", limites))
        self.assertFalse(nav.permite("https://other.chromeexperiments.com/x", limites))

    def test_com_br_nao_encurta_demais(self):
        self.assertEqual(nav.registravel("www.escolagames.com.br"), "escolagames.com.br")
        self.assertEqual(nav.registravel("pt.khanacademy.org"), "khanacademy.org")
        limites = nav.limites_da_url("https://pt.khanacademy.org/")
        self.assertTrue(nav.permite("https://pt.khanacademy.org/login", limites))
        self.assertTrue(nav.permite("https://www.khanacademy.org/computing", limites))


class RegrasEManifestoTest(unittest.TestCase):
    def test_regras_so_main_frame_e_prioridade(self):
        limites = nav.limites_da_url(PHET)
        regras = nav.regras_dnr(limites)
        ids = [r["id"] for r in regras]
        self.assertEqual(ids, list(range(1, len(regras) + 1)))
        self.assertEqual(regras[0]["priority"], 1)
        self.assertEqual(regras[0]["action"]["redirect"]["extensionPath"], "/ficou.html")
        self.assertEqual(regras[0]["condition"]["regexFilter"], r"^https?://")
        self.assertEqual(regras[0]["condition"]["resourceTypes"], ["main_frame"])
        allows = [r for r in regras if r["action"]["type"] == "allow"]
        self.assertTrue(allows)
        self.assertTrue(all(r["priority"] > regras[0]["priority"] for r in allows))
        self.assertTrue(all(r["condition"]["resourceTypes"] == ["main_frame"] for r in regras))
        self.assertNotIn("sub_frame", json.dumps(regras))
        juntos = " ".join(r["condition"].get("regexFilter", "") for r in allows)
        self.assertIn("/sims/html/", juntos)
        self.assertNotIn("givecampus", juntos)

    def test_manifesto_gerado_e_valido_e_a_guarda_leva_as_regras(self):
        origem = json.loads((RAIZ / "src" / "edge" / "sites-limpos" / "manifest.json").read_text())
        self.assertEqual(origem["manifest_version"], 3)
        self.assertNotIn("declarative_net_request", origem)
        with tempfile.TemporaryDirectory() as tmp:
            destino = nav.preparar_extensao(os.path.join(tmp, "extensao-sites"), PHET)
            manifesto = json.loads(Path(destino, "manifest.json").read_text())
            regras = json.loads(Path(destino, "regras.json").read_text())
            guarda = Path(destino, "guarda.js").read_text()
            ficou = Path(destino, "ficou.html").read_text()
            ficou_js = Path(destino, "ficou.js").read_text()
        self.assertEqual(manifesto["manifest_version"], 3)
        self.assertEqual(manifesto["permissions"], ["declarativeNetRequest"])
        self.assertEqual(manifesto["host_permissions"], ["<all_urls>"])
        recurso = manifesto["declarative_net_request"]["rule_resources"]
        self.assertEqual(recurso, [{"id": "limites", "enabled": True, "path": "regras.json"}])
        partes = manifesto["version"].split(".")
        self.assertEqual(len(partes), 3)
        self.assertTrue(all(p.isdigit() and 0 <= int(p) <= 65535 for p in partes))
        scripts = [s for s in manifesto["content_scripts"] if s.get("js") == ["guarda.js"]]
        self.assertEqual(len(scripts), 1)
        self.assertEqual(scripts[0]["world"], "MAIN")
        self.assertEqual(scripts[0]["run_at"], "document_start")
        self.assertTrue(scripts[0]["all_frames"])
        self.assertEqual(regras, nav.regras_dnr(nav.limites_da_url(PHET)))
        self.assertIn(json.dumps(nav.PHET_SIM), guarda)
        self.assertIn("window.open", guarda)
        self.assertIn("Esse link não abre", ficou)
        self.assertIn("ficou.js", ficou)
        self.assertNotIn("<script>location", ficou)
        self.assertEqual(ficou_js, nav.js_ficou(PHET))
        self.assertEqual(
            manifesto["web_accessible_resources"],
            [{"resources": ["ficou.html", "ficou.js"], "matches": ["<all_urls>"]}],
        )
        self.assertNotIn("chrome-extension", regras[0]["condition"]["regexFilter"])
        for rx in nav.limites_da_url(PHET)["permitir"]:
            re.compile(rx)
            self.assertIn(json.dumps(rx), guarda)

    def test_comando_do_edge_carrega_a_copia_e_o_firefox_nao(self):
        with tempfile.TemporaryDirectory() as tmp:
            comando = external_browser_command("msedge.exe", "https://kiddogames.fun/", tmp)
            firefox = external_browser_command("firefox", "https://kiddogames.fun/", tmp)
            carga = [a for a in comando if a.startswith("--load-extension=")]
            self.assertEqual(len(carga), 1)
            pasta = carga[0].split("=", 1)[1]
            self.assertTrue(pasta.endswith(os.path.join("extensao-sites")))
            self.assertTrue((Path(pasta) / "regras.json").is_file())
            self.assertIn("--kiosk", comando)
            self.assertEqual(firefox[-2:], ["--kiosk", "https://kiddogames.fun/"])
            self.assertFalse(any("load-extension" in a or "declarative" in a for a in firefox))

    def test_uma_flag_junta_a_pasta_do_controle(self):
        with tempfile.TemporaryDirectory() as tmp:
            extra = os.path.join(tmp, "cozy-controle")
            os.makedirs(extra)
            por_lista = external_browser_command(
                "msedge.exe", "https://kiddogames.fun/", tmp, extensoes=[extra])
            por_uma = external_browser_command(
                "msedge.exe", "https://kiddogames.fun/", tmp, extensao=extra)
            for atual in (por_lista, por_uma):
                carga = [a for a in atual if a.startswith("--load-extension=")]
                self.assertEqual(len(carga), 1)
                pastas = carga[0].split("=", 1)[1].split(",")
                self.assertEqual(pastas[1:], [extra])
                self.assertTrue(pastas[0].endswith(os.path.join("extensao-sites")))
                flags = [a for a in atual if a.startswith("--disable-features=")]
                self.assertEqual(flags, [f"--disable-features={CHROMIUM_RECURSOS_DESLIGADOS}"])
                self.assertIn("--lang=pt-BR", atual)
            self.assertEqual(
                flags_do_chromium(),
                [f"--disable-features={CHROMIUM_RECURSOS_DESLIGADOS}"],
            )
            codigo = (RAIZ / "src" / "application_launcher.py").read_text(encoding="utf-8")
            self.assertEqual(codigo.count("--load-extension="), 1)
            self.assertEqual(codigo.count("--disable-features="), 1)
            iniciador = (RAIZ / "src" / "beni_windows.py").read_text(encoding="utf-8")
            self.assertIn("flags_do_chromium()", iniciador)
            self.assertNotIn("--disable-features=", iniciador)
            self.assertNotIn("--load-extension=", iniciador)


class ListaPhETTest(unittest.TestCase):
    def test_lista_so_tem_simulacao_e_a_pagina_nao_abre_o_site(self):
        dados = json.loads((RAIZ / "src" / "sites" / "phet-sims.json").read_text())
        pagina = (RAIZ / "src" / "sites" / "phet.html").read_text()
        self.assertNotIn("simulations/filter", pagina)
        self.assertIn("/sims/html/", pagina)
        self.assertEqual(dados["nivel"], "elementary-school")
        limites = nav.limites_da_url(PHET)
        vistos = set()
        for tema, itens in dados["temas"].items():
            self.assertIn(tema, ("physics", "math-and-statistics", "chemistry", "earth-and-space", "biology"))
            self.assertTrue(itens, tema)
            for item in itens:
                self.assertTrue(item["url"].startswith("https://phet.colorado.edu/sims/html/"), item["url"])
                self.assertNotIn("/simulations/", item["url"])
                self.assertNotIn("donate", item["url"])
                self.assertTrue(nav.permite(item["url"], limites), item["url"])
                vistos.add(item["sim"])
        self.assertIn("balancing-act", vistos)
        self.assertNotIn("acid-base-solutions", vistos)
        self.assertNotIn("band-structure", vistos)


if __name__ == "__main__":
    unittest.main()
