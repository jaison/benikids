import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import atualizar_windows as aw  # noqa: E402


def pacote_zip(versao, extra=None, manifesto=True):
    arquivos = {
        "Beni/instalar_windows.py": "",
        "Beni/python/pythonw.exe": "MZ",
        "Beni/app/server.py": "",
        "Beni/app/version": versao,
    }
    arquivos.update(extra or {})
    if manifesto:
        prefixo = "Beni/app/"
        linhas = sorted(
            nome[len(prefixo):]
            for nome in arquivos
            if nome.startswith(prefixo) and nome[len(prefixo):] != aw.MANIFESTO and ".." not in nome.split("/")
        )
        arquivos[prefixo + aw.MANIFESTO] = "".join(linha + "\n" for linha in linhas)
    dados = io.BytesIO()
    with zipfile.ZipFile(dados, "w") as z:
        for nome, conteudo in arquivos.items():
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

    def test_parents_see_the_downloaded_version_and_failures(self):
        vazio = aw.estado_para_os_pais(self.app, self.base)
        self.assertEqual(vazio, {"baixada": None, "ultimaVerificacao": None, "erro": None})
        abrir = self.servidor(release("1.0.5"), pacote_zip("1.0.5"))
        aw.verificar(self.app, self.base, abrir, agora=1000)
        estado = aw.estado_para_os_pais(self.app, self.base)
        self.assertEqual(estado["baixada"], "1.0.5")
        self.assertTrue(estado["ultimaVerificacao"])
        self.assertIsNone(estado["erro"])
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

    def test_package_without_the_file_list_is_rejected(self):
        abrir = self.servidor(release("1.0.5"), pacote_zip("1.0.5", manifesto=False))
        with self.assertRaises(RuntimeError):
            aw.verificar(self.app, self.base, abrir, agora=1000)
        self.assertIsNone(aw.pendente(self.app, self.base))



def escrever(pasta, relativo, conteudo="x"):
    caminho = os.path.join(pasta, *relativo.split("/"))
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(conteudo)
    return caminho


def lista(pasta, linhas):
    with open(os.path.join(pasta, aw.MANIFESTO), "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")


class LimpaArquivosVelhosTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.destino = os.path.join(self.tmp.name, "app")
        self.novo = os.path.join(self.tmp.name, "pacote")
        self.fora = os.path.join(self.tmp.name, "fora")
        os.makedirs(self.destino)
        os.makedirs(self.novo)
        os.makedirs(self.fora)
        self.logs = []

    def limpar(self, anterior=None):
        if anterior is None:
            anterior = aw.ler_manifesto(self.destino)
        return aw.limpar_arquivos_velhos(self.destino, self.novo, anterior=anterior, log=self.logs.append)

    def test_removes_files_that_left_the_version_and_old_pycache(self):
        escrever(self.destino, "server.py", "velho")
        escrever(self.destino, "timer_fim.py", "orfao")
        escrever(self.destino, "__pycache__/timer_fim.cpython-313.pyc")
        escrever(self.destino, "frontend/__pycache__/menu.cpython-313.pyc")
        escrever(self.novo, "server.py", "novo")
        lista(self.destino, ["server.py", "timer_fim.py"])
        lista(self.novo, ["server.py"])
        self.assertEqual(self.limpar(), ["timer_fim.py"])
        self.assertFalse(os.path.exists(os.path.join(self.destino, "timer_fim.py")))
        self.assertFalse(os.path.exists(os.path.join(self.destino, "__pycache__")))
        self.assertFalse(os.path.exists(os.path.join(self.destino, "frontend", "__pycache__")))
        self.assertTrue(os.path.isfile(os.path.join(self.destino, "server.py")))
        self.assertTrue(any("timer_fim.py" in linha for linha in self.logs))
        self.assertTrue(any("__pycache__" in linha for linha in self.logs))

    def test_without_a_previous_list_only_pycache_goes(self):
        escrever(self.destino, "timer_fim.py", "orfao")
        escrever(self.destino, "__pycache__/timer_fim.cpython-313.pyc")
        escrever(self.destino, "themes/covers/capa.jpg", "capa")
        escrever(self.novo, "server.py", "novo")
        lista(self.novo, ["server.py"])
        self.assertEqual(self.limpar(), [])
        self.assertTrue(os.path.isfile(os.path.join(self.destino, "timer_fim.py")))
        self.assertTrue(os.path.isfile(os.path.join(self.destino, "themes", "covers", "capa.jpg")))
        self.assertFalse(os.path.exists(os.path.join(self.destino, "__pycache__")))
        self.assertTrue(any("sem lista da versão anterior" in linha for linha in self.logs))

    def test_keeps_user_data_even_if_an_old_list_names_it(self):
        escrever(self.destino, "themes/covers/capa.jpg", "capa")
        escrever(self.destino, "themes/covers/__pycache__/x.pyc")
        escrever(self.destino, "python/Lib/velho.py", "py")
        escrever(self.destino, "python/__pycache__/velho.pyc")
        escrever(self.destino, "config.json", "{}")
        escrever(self.destino, "beni-windows.log", "log")
        escrever(self.fora, "segredo.txt", "nao")
        escrever(self.novo, "server.py")
        lista(self.destino, [
            "themes/covers/capa.jpg",
            "python/Lib/velho.py",
            "config.json",
            "beni-windows.log",
            "../fora/segredo.txt",
            "C:/Windows/notepad.exe",
        ])
        lista(self.novo, ["server.py"])
        self.assertEqual(self.limpar(), [])
        for relativo in ("themes/covers/capa.jpg", "themes/covers/__pycache__/x.pyc",
                         "python/Lib/velho.py", "python/__pycache__/velho.pyc",
                         "config.json", "beni-windows.log"):
            self.assertTrue(os.path.exists(os.path.join(self.destino, *relativo.split("/"))), relativo)
        with open(os.path.join(self.fora, "segredo.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "nao")

    def test_a_package_without_a_list_does_not_delete_app_files(self):
        escrever(self.destino, "timer_fim.py")
        lista(self.destino, ["timer_fim.py", "server.py"])
        escrever(self.novo, "server.py")
        self.assertEqual(self.limpar(), [])
        self.assertTrue(os.path.isfile(os.path.join(self.destino, "timer_fim.py")))
        self.assertTrue(any("não trouxe a lista" in linha for linha in self.logs))

    def test_locked_file_is_skipped_and_the_others_go(self):
        escrever(self.destino, "timer_fim.py")
        escrever(self.destino, "outro_velho.py")
        lista(self.destino, ["timer_fim.py", "outro_velho.py"])
        lista(self.novo, ["server.py"])
        real = os.remove

        def remove(caminho):
            if caminho.endswith("timer_fim.py"):
                raise OSError("em uso")
            real(caminho)

        with mock.patch("atualizar_windows.os.remove", side_effect=remove):
            apagados = self.limpar()
        self.assertEqual(apagados, ["outro_velho.py"])
        self.assertTrue(os.path.isfile(os.path.join(self.destino, "timer_fim.py")))
        self.assertTrue(any("não consegui apagar timer_fim.py" in linha for linha in self.logs))

    def test_a_locked_file_stays_on_the_list_for_the_next_install(self):
        # a cópia já gravou a lista nova, sem o arquivo que não saiu
        escrever(self.destino, "timer_fim.py")
        lista(self.destino, ["server.py"])
        lista(self.novo, ["server.py"])
        real = os.remove

        def remove(caminho):
            if caminho.endswith("timer_fim.py"):
                raise OSError("em uso")
            real(caminho)

        with mock.patch("atualizar_windows.os.remove", side_effect=remove):
            self.limpar(anterior={"server.py", "timer_fim.py"})
        self.assertIn("timer_fim.py", aw.ler_manifesto(self.destino))
        self.assertTrue(any("próxima instalação" in linha for linha in self.logs))

    def test_does_not_remove_a_directory_or_a_symlink(self):
        os.makedirs(os.path.join(self.destino, "pasta_velha"))
        alvo = escrever(self.destino, "server.py", "fica")
        os.symlink(alvo, os.path.join(self.destino, "atalho.py"))
        lista(self.destino, ["pasta_velha", "atalho.py"])
        lista(self.novo, ["server.py"])
        self.assertEqual(self.limpar(), [])
        self.assertTrue(os.path.isdir(os.path.join(self.destino, "pasta_velha")))
        self.assertTrue(os.path.islink(os.path.join(self.destino, "atalho.py")))

    def test_case_only_rename_is_kept(self):
        escrever(self.destino, "Timer_Fim.py")
        lista(self.destino, ["Timer_Fim.py"])
        lista(self.novo, ["timer_fim.py"])
        self.assertEqual(self.limpar(), [])
        self.assertTrue(os.path.isfile(os.path.join(self.destino, "Timer_Fim.py")))

    def test_manifest_lists_app_files_and_skips_user_data(self):
        escrever(self.novo, "server.py")
        escrever(self.novo, "frontend/menu.js")
        escrever(self.novo, "__pycache__/server.cpython-313.pyc")
        escrever(self.novo, "themes/covers/capa.jpg")
        escrever(self.novo, "python/pythonw.exe")
        escrever(self.novo, "notas.log")
        os.symlink(os.path.join(self.novo, "server.py"), os.path.join(self.novo, "link.py"))
        arquivos = aw.gravar_manifesto(self.novo)
        self.assertEqual(arquivos, ["frontend/menu.js", "server.py"])
        with open(os.path.join(self.novo, aw.MANIFESTO), encoding="utf-8") as f:
            texto = f.read()
        self.assertEqual(texto, "frontend/menu.js\nserver.py\n")
        self.assertIsNone(aw._normalizar_relativo("../fora.txt"))
        self.assertEqual(aw.ler_manifesto(self.novo), {"frontend/menu.js", "server.py"})
        self.assertIsNone(aw.ler_manifesto(self.destino))


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
