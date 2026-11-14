import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import atualizar_windows as aw  # noqa: E402


def pacote_zip(versao, extra=None):
    dados = io.BytesIO()
    with zipfile.ZipFile(dados, "w") as z:
        z.writestr("Beni/instalar_windows.py", "")
        z.writestr("Beni/python/pythonw.exe", "MZ")
        z.writestr("Beni/app/server.py", "")
        z.writestr("Beni/app/version", versao)
        for nome, conteudo in (extra or {}).items():
            z.writestr(nome, conteudo)
    return dados.getvalue()


def release(versao, **mais):
    r = {"tag_name": "v" + versao, "draft": False, "prerelease": False, "assets": [
        {"name": aw.ASSET, "browser_download_url": "https://exemplo/zip"},
        {"name": aw.ASSET + ".sha256", "browser_download_url": "https://exemplo/sha"},
    ]}
    r.update(mais)
    return r


class AtualizarWindowsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = os.path.join(self.tmp.name, "app")
        self.base = os.path.join(self.tmp.name, "atualizacao")
        os.makedirs(self.app)
        with open(os.path.join(self.app, "version"), "w") as f:
            f.write("1.0.4")

    def servidor(self, rel, zip_bytes, soma=None):
        soma = soma or hashlib.sha256(zip_bytes).hexdigest()
        respostas = {
            "https://api.github.com/repos/jaison/benikids/releases/latest": json.dumps(rel).encode(),
            "https://exemplo/zip": zip_bytes,
            "https://exemplo/sha": f"{soma}  {aw.ASSET}\n".encode(),
        }
        self.pedidos = []

        def abrir(url, timeout=30):
            self.pedidos.append(url)
            return io.BytesIO(respostas[url])

        return abrir

    def test_only_newer_published_releases_with_the_package_count(self):
        self.assertIsNotNone(aw.release_nova(release("1.0.5"), "1.0.4"))
        self.assertIsNone(aw.release_nova(release("1.0.4"), "1.0.4"))
        self.assertIsNone(aw.release_nova(release("1.0.3"), "1.0.4"))
        self.assertIsNone(aw.release_nova(release("1.0.5", prerelease=True), "1.0.4"))
        self.assertIsNone(aw.release_nova(release("1.0.5", assets=[]), "1.0.4"))
        self.assertIsNone(aw.release_nova(release("1.0.5", tag_name="nightly"), "1.0.4"))

    def test_new_version_is_downloaded_checked_and_installed_on_next_start(self):
        abrir = self.servidor(release("1.0.5"), pacote_zip("1.0.5"))
        self.assertEqual(aw.verificar(self.app, self.base, abrir, agora=1000), "1.0.5")
        versao, raiz = aw.pendente(self.app, self.base)
        self.assertEqual(versao, "1.0.5")
        self.assertTrue(os.path.isfile(os.path.join(raiz, "instalar_windows.py")))
        # no mesmo dia não pergunta de novo ao GitHub
        self.pedidos.clear()
        self.assertIsNone(aw.verificar(self.app, self.base, abrir, agora=2000))
        self.assertEqual(self.pedidos, [])
        # depois de instalada, a pasta baixada é apagada
        with open(os.path.join(self.app, "version"), "w") as f:
            f.write("1.0.5")
        self.assertIsNone(aw.pendente(self.app, self.base))
        self.assertFalse(os.path.exists(os.path.join(self.base, "pronta")))

    def test_wrong_checksum_is_rejected(self):
        abrir = self.servidor(release("1.0.5"), pacote_zip("1.0.5"), soma="0" * 64)
        with self.assertRaises(RuntimeError):
            aw.verificar(self.app, self.base, abrir, agora=1000)
        self.assertIsNone(aw.pendente(self.app, self.base))

    def test_package_version_must_match_the_tag(self):
        abrir = self.servidor(release("1.0.5"), pacote_zip("1.0.6"))
        with self.assertRaises(RuntimeError):
            aw.verificar(self.app, self.base, abrir, agora=1000)
        self.assertIsNone(aw.pendente(self.app, self.base))

    def test_zip_cannot_write_outside_its_folder(self):
        abrir = self.servidor(release("1.0.5"), pacote_zip("1.0.5", {"../../fora.txt": "x"}))
        with self.assertRaises(RuntimeError):
            aw.verificar(self.app, self.base, abrir, agora=1000)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "fora.txt")))

    def test_a_version_that_failed_is_not_retried_every_login(self):
        abrir = self.servidor(release("1.0.5"), pacote_zip("1.0.5"))
        aw.verificar(self.app, self.base, abrir, agora=1000)
        aw.marcar_falha("1.0.5", self.base)
        self.assertIsNone(aw.pendente(self.app, self.base))


if __name__ == "__main__":
    unittest.main()
