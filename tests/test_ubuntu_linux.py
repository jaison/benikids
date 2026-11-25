"""Ubuntu e derivados: Firefox snap, limite no perfil, idioma e jogos."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

import application_launcher  # noqa: E402
import navegacao_sites as nav  # noqa: E402
import site_logins  # noqa: E402
from application_launcher import external_browser_command, external_firefox_profile  # noqa: E402

BIN = RAIZ / "beni" / "bin"


class FirefoxSnapTest(unittest.TestCase):
    def test_script_do_ubuntu_e_snap_e_o_deb_nao(self):
        self.assertTrue(application_launcher.conteudo_indica_firefox_snap(
            "/snap/bin/firefox", ""))
        self.assertTrue(application_launcher.conteudo_indica_firefox_snap(
            "/usr/bin/firefox", 'exec /snap/bin/firefox "$@"\n'))
        self.assertTrue(application_launcher.conteudo_indica_firefox_snap(
            "/usr/bin/firefox", 'os.execvp("snap", ["snap", "run", "firefox"])\n'))
        self.assertFalse(application_launcher.conteudo_indica_firefox_snap(
            "/usr/lib/firefox/firefox", ""))
        self.assertFalse(application_launcher.conteudo_indica_firefox_snap(
            "/usr/bin/firefox-esr", "exec /usr/lib/firefox-esr/firefox-esr"))

    def test_perfil_do_snap_fica_onde_ele_le_e_nao_mexe_no_deb(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = os.path.join(tmp, "cache")
            os.makedirs(cache)
            deb = external_firefox_profile(cache, "default", snap=False)
            self.assertEqual(deb, os.path.join(cache, "external-firefox-profile"))
            with mock.patch.object(application_launcher, "_home_do_usuario", return_value=tmp):
                snap = external_firefox_profile(cache, "child-1", snap=True)
            self.assertIn(
                os.path.join("snap", "firefox", "common", "cozy-kids-launcher"),
                snap,
            )
            self.assertTrue(snap.endswith("external-firefox-profile-child-1"))
            self.assertFalse(snap.startswith(cache))

    def test_comando_do_snap_nao_reusa_o_firefox_da_familia(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(application_launcher, "_home_do_usuario", return_value=tmp), \
                    mock.patch.object(application_launcher, "firefox_e_snap", return_value=True), \
                    mock.patch.object(application_launcher, "sessao_linux", return_value=True):
                comando = external_browser_command("firefox", "https://kiddogames.fun/", tmp)
            self.assertIn("--no-remote", comando)
            self.assertIn("--new-instance", comando)
            self.assertIn("--marionette", comando)
            self.assertEqual(comando[-2:], ["--kiosk", "https://kiddogames.fun/"])
            perfil = comando[comando.index("--profile") + 1]
            self.assertIn(os.path.join("snap", "firefox", "common"), perfil)
            manifesto = json.loads(
                Path(perfil, nav.PASTA_LIMITE_NO_PERFIL, "manifest.json").read_text()
            )
            self.assertEqual(
                manifesto["browser_specific_settings"]["gecko"]["id"],
                nav.ID_EXTENSAO_FIREFOX,
            )
            self.assertIn("declarativeNetRequest", manifesto["permissions"])
            prefs = Path(perfil, "user.js").read_text()
            self.assertIn('user_pref("marionette.port", 28290);', prefs)

    def test_politica_global_nao_bloqueia_a_internet_da_familia(self):
        politica = json.loads((RAIZ / "beni" / "firefox" / "policies.json").read_text())
        bloqueios = politica["policies"]["WebsiteFilter"]["Block"]
        self.assertNotIn("<all_urls>", json.dumps(bloqueios))
        texto = (RAIZ / "beni" / "sistema" / "instalar-sistema.sh").read_text()
        self.assertIn("Não use WebsiteFilter Block <all_urls>", texto)

    def test_extensao_temporaria_nao_pede_assinatura(self):
        pedido = site_logins.pedido_extensao_temporaria("/tmp/benikids-sites-limpos")
        self.assertTrue(pedido["temporary"])
        self.assertTrue(pedido["path"].endswith("benikids-sites-limpos"))


class IdiomaEJogosTest(unittest.TestCase):
    def test_reconhece_o_locale_pt_br(self):
        self.assertTrue(application_launcher.tem_locale_pt_br("C\npt_BR.utf8\n"))
        self.assertTrue(application_launcher.tem_locale_pt_br("pt_BR.UTF-8\n"))
        self.assertFalse(application_launcher.tem_locale_pt_br("C\nen_US.utf8\npt_PT.utf8\n"))

    def test_atalhos_forcam_pt_br_se_existir(self):
        locale = (BIN / "cozy-locale").read_text()
        self.assertIn("LANG=pt_BR.UTF-8", locale)
        self.assertIn("LC_ALL=pt_BR.UTF-8", locale)
        for nome in ("supertux", "klotski", "gcompris", "cozy-kids-launcher"):
            self.assertIn("cozy-locale", (BIN / nome).read_text(), nome)
        sistema = (RAIZ / "beni" / "sistema" / "instalar-sistema.sh").read_text()
        self.assertIn("language-pack-pt", sistema)
        self.assertIn("pt_BR.UTF-8", sistema)

    def test_supertux_e_klotski_detectam_o_binario(self):
        supertux = (BIN / "supertux").read_text()
        self.assertIn("/usr/games/supertux2 /usr/games/supertux", supertux)
        klotski = (BIN / "klotski").read_text()
        self.assertIn("gnome-klotski", klotski)
        self.assertIn("org.gnome.Klotski", klotski)
        self.assertIn('ID" = "linuxmint"', klotski)
        self.assertIn("GLYCIN_DISABLE_SANDBOX", klotski)
        self.assertIn("GSK_RENDERER", klotski)
        apt = (RAIZ / "beni" / "sistema" / "pacotes-apt.txt").read_text()
        self.assertIn("gnome-klotski", apt)
        self.assertIn("\nsupertux\n", apt)

    def test_wayland_avisa_para_usar_o_xorg(self):
        texto = (RAIZ / "instalar.sh").read_text()
        self.assertIn("Ubuntu on Xorg", texto)
        self.assertIn('XDG_SESSION_TYPE:-}" == "wayland"', texto)
        tecnico = (RAIZ / "docs" / "benikids-tecnico.md").read_text()
        self.assertIn("wmctrl", tecnico)
        self.assertIn("Wayland", tecnico)


if __name__ == "__main__":
    unittest.main()
