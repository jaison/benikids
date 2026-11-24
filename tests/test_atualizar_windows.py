import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
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
        self.respostas = respostas

        def abrir(url, timeout=30):
            self.pedidos.append(url)
            dado = self.respostas[url]
            if isinstance(dado, Exception):
                raise dado
            return io.BytesIO(dado)

        return abrir

    def publicar(self, versao):
        dados = pacote_zip(versao)
        self.respostas["https://api.github.com/repos/jaison/benikids/releases/latest"] = json.dumps(
            release(versao)).encode()
        self.respostas["https://exemplo/zip"] = dados
        self.respostas["https://exemplo/sha"] = f"{hashlib.sha256(dados).hexdigest()}  {aw.ASSET}\n".encode()

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

    def test_parents_see_the_downloaded_version_and_failures(self):
        vazio = aw.estado_para_os_pais(self.app, self.base)
        self.assertIsNone(vazio["baixada"])
        self.assertIsNone(vazio["ultimaVerificacao"])
        self.assertIsNone(vazio["erro"])
        self.assertIn("Ainda não procurei", vazio["texto"])
        self.assertNotIn("versão mais nova", vazio["texto"])
        abrir = self.servidor(release("1.0.5"), pacote_zip("1.0.5"))
        aw.verificar(self.app, self.base, abrir, agora=1000)
        estado = aw.estado_para_os_pais(self.app, self.base)
        self.assertEqual(estado["baixada"], "1.0.5")
        self.assertTrue(estado["ultimaVerificacao"])
        self.assertIsNone(estado["erro"])
        self.assertIn("Versão 1.0.5 baixada", estado["texto"])
        self.assertIn("parado no menu", estado["texto"])
        aw.marcar_falha("1.0.5", self.base)
        self.assertIn("1.0.5", aw.estado_para_os_pais(self.app, self.base)["erro"])

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

    def test_force_ignores_the_interval_and_the_minute_limit_holds(self):
        abrir = self.servidor(release("1.0.4"), pacote_zip("1.0.4"))
        self.assertIsNone(aw.verificar(self.app, self.base, abrir, agora=1000))
        self.assertEqual(len(self.pedidos), 1)

        self.publicar("1.0.5")
        self.pedidos.clear()
        # dentro das 6 h a procura automática não fala com o GitHub
        self.assertIsNone(aw.verificar(self.app, self.base, abrir, agora=2000))
        self.assertEqual(self.pedidos, [])
        # o botão ignora as 6 h e baixa
        self.assertEqual(aw.verificar(self.app, self.base, abrir, agora=2000, forcar=True), "1.0.5")
        self.assertTrue(self.pedidos)

        self.publicar("1.0.6")
        self.pedidos.clear()
        # menos de um minuto: nem o botão pergunta de novo
        self.assertIsNone(aw.verificar(self.app, self.base, abrir, agora=2030, forcar=True))
        self.assertEqual(self.pedidos, [])
        self.assertEqual(aw.verificar(self.app, self.base, abrir, agora=2000 + 61, forcar=True), "1.0.6")
        self.assertTrue(self.pedidos)

    def test_each_state_has_an_honest_sentence(self):
        texto, tipo = aw.mensagem_para_os_pais(self.app, self.base, agora=1000)
        self.assertIn("Ainda não procurei", texto)
        self.assertNotIn("versão mais nova", texto)
        self.assertEqual(tipo, "empty")

        abrir = self.servidor(release("1.0.4"), pacote_zip("1.0.4"))
        self.assertIsNone(aw.verificar(self.app, self.base, abrir, agora=1000, forcar=True))
        texto, tipo = aw.mensagem_para_os_pais(self.app, self.base, agora=1000)
        self.assertEqual(texto, "Você tem a versão mais nova (1.0.4). Verificado agora.")
        self.assertEqual(tipo, "success")
        texto, _tipo = aw.mensagem_para_os_pais(self.app, self.base, agora=1000 + 180)
        self.assertTrue(texto.startswith("Você tem a versão mais nova (1.0.4). Verificado às "))
        self.assertNotIn("Em dia", texto)

        self.publicar("1.0.5")
        self.assertEqual(aw.verificar(self.app, self.base, abrir, agora=1000 + 180, forcar=True), "1.0.5")
        texto, tipo = aw.mensagem_para_os_pais(self.app, self.base, agora=1000 + 180)
        self.assertEqual(
            texto,
            "Versão 1.0.5 baixada; vai ser instalada quando o computador ficar parado no menu.",
        )
        self.assertEqual(tipo, "success")

        texto, tipo = aw.mensagem_para_os_pais(self.app, self.base, agora=1000 + 180 + aw.INTERVALO)
        # a versão baixada continua valendo, mesmo se a procura já é antiga
        self.assertIn("Versão 1.0.5 baixada", texto)

    def test_offline_is_not_reported_as_up_to_date_and_retries_sooner(self):
        def abrir(url, timeout=30):
            self.pedidos.append(url)
            raise urllib.error.URLError("offline")

        self.pedidos = []
        with self.assertRaises(aw.FalhaDeRede):
            aw.verificar(self.app, self.base, abrir, agora=1000, forcar=True)
        texto, tipo = aw.mensagem_para_os_pais(self.app, self.base, agora=1000)
        self.assertEqual(texto, "Não deu para verificar (sem internet?).")
        self.assertEqual(tipo, "error")
        self.assertNotIn("versão mais nova", texto)

        self.pedidos.clear()
        self.assertIsNone(aw.verificar(self.app, self.base, abrir, agora=1030, forcar=True))
        self.assertEqual(self.pedidos, [])
        # a procura automática não espera 6 h quando a última nem chegou ao GitHub
        self.assertIsNone(aw.verificar(self.app, self.base, abrir, agora=1000 + 10 * 60))
        self.assertEqual(self.pedidos, [])
        with self.assertRaises(aw.FalhaDeRede):
            aw.verificar(self.app, self.base, abrir, agora=1000 + aw.REPETIR_SEM_REDE)
        self.assertTrue(self.pedidos)

    def test_a_check_older_than_the_interval_does_not_claim_the_newest_version(self):
        abrir = self.servidor(release("1.0.4"), pacote_zip("1.0.4"))
        aw.verificar(self.app, self.base, abrir, agora=1000)
        texto, tipo = aw.mensagem_para_os_pais(self.app, self.base, agora=1000 + aw.INTERVALO)
        self.assertNotIn("versão mais nova", texto)
        self.assertIn("Toque em Ver atualizações", texto)
        self.assertEqual(tipo, "empty")


class HoraDeAtualizarTests(unittest.TestCase):
    def test_installs_only_when_ready_idle_and_no_app_open(self):
        pronta = ("1.0.6", "/pacote")
        vinte = aw.OCIOSO_PARA_ATUALIZAR
        self.assertTrue(aw.hora_de_atualizar(pronta, None, vinte))
        self.assertFalse(aw.hora_de_atualizar(None, None, vinte * 10))      # nada baixado
        self.assertFalse(aw.hora_de_atualizar(pronta, {"pid": 1}, vinte))   # criança num app
        self.assertFalse(aw.hora_de_atualizar(pronta, None, vinte - 1))     # alguém mexeu há pouco


if __name__ == "__main__":
    unittest.main()
