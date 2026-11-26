import hashlib
import http.client
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import urllib.error
import zipfile
from unittest import mock

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
        self.assertTrue(texto.startswith("Às ") or texto.startswith("Em "))
        self.assertIn("não deu para verificar (sem internet?)", texto)
        self.assertNotEqual(texto, "Não deu para verificar (sem internet?).")
        self.assertEqual(tipo, "error")
        self.assertNotIn("versão mais nova", texto)
        # 3 h depois a frase ainda é a hora daquela tentativa, não a de agora
        hora = time.strftime("%H:%M", time.localtime(1000))
        self.assertIn(hora, texto)
        tarde, _tipo = aw.mensagem_para_os_pais(self.app, self.base, agora=1000 + 3 * 3600)
        self.assertIn(hora, tarde)
        self.assertNotIn(time.strftime("%H:%M", time.localtime(1000 + 3 * 3600)), tarde)
        self.assertIn("não deu para verificar (sem internet?)", tarde)

        self.pedidos.clear()
        self.assertIsNone(aw.verificar(self.app, self.base, abrir, agora=1030, forcar=True))
        self.assertEqual(self.pedidos, [])
        # a procura automática não espera 6 h quando a última nem chegou ao GitHub
        self.assertIsNone(aw.verificar(self.app, self.base, abrir, agora=1000 + 10 * 60))
        self.assertEqual(self.pedidos, [])
        with self.assertRaises(aw.FalhaDeRede):
            aw.verificar(self.app, self.base, abrir, agora=1000 + aw.REPETIR_SEM_REDE)
        self.assertTrue(self.pedidos)

    def test_a_click_inside_the_minute_does_not_pretend_it_checked_again(self):
        abrir = self.servidor(release("1.0.4"), pacote_zip("1.0.4"))
        self.assertIsNone(aw.verificar(self.app, self.base, abrir, agora=1000, forcar=True))
        antes = aw._estado(self.base).get("tentado_em")

        def sem_rede(url, timeout=30):
            self.pedidos.append(url)
            raise urllib.error.URLError("offline")

        self.pedidos = []
        self.assertIsNone(aw.verificar(self.app, self.base, sem_rede, agora=1030, forcar=True))
        self.assertEqual(self.pedidos, [])
        self.assertTrue(aw.procura_nao_rodou(self.base, antes))
        texto, tipo = aw.mensagem_para_os_pais(
            self.app, self.base, agora=1030, resultado_antigo=True)
        self.assertEqual(texto, "Você tem a versão mais nova (1.0.4). Verificado há poucos segundos.")
        self.assertEqual(tipo, "success")
        self.assertNotIn("Verificado agora", texto)
        # a tela aberta, sem um clique novo, ainda pode dizer que foi agora
        fresco, _tipo = aw.mensagem_para_os_pais(self.app, self.base, agora=1000)
        self.assertIn("Verificado agora", fresco)

    def test_a_later_check_clears_the_offline_sentence(self):
        def sem_rede(url, timeout=30):
            raise urllib.error.URLError("offline")

        with self.assertRaises(aw.FalhaDeRede):
            aw.verificar(self.app, self.base, sem_rede, agora=1000, forcar=True)
        abrir = self.servidor(release("1.0.4"), pacote_zip("1.0.4"))
        self.assertIsNone(aw.verificar(self.app, self.base, abrir, agora=1000 + aw.REPETIR_SEM_REDE))
        texto, tipo = aw.mensagem_para_os_pais(self.app, self.base, agora=1000 + aw.REPETIR_SEM_REDE)
        self.assertNotIn("sem internet", texto)
        self.assertIn("versão mais nova", texto)
        self.assertEqual(tipo, "success")
        self.assertFalse(aw._estado(self.base).get("sem_rede"))

    def test_the_launcher_wakes_often_enough_to_clear_an_offline_sentence(self):
        caminho = os.path.join(os.path.dirname(__file__), "..", "src", "beni_windows.py")
        with open(caminho, encoding="utf-8") as arquivo:
            texto = arquivo.read()
        trecho = texto[texto.index("def procurar_atualizacao_depois"):texto.index("def limpar_queda")]
        self.assertIn("REPETIR_SEM_REDE", trecho)
        self.assertIn("time.sleep(pausa)", trecho)
        self.assertNotIn("INTERVALO", trecho)
        self.assertIn("a rede voltou", trecho)

    def test_a_check_that_breaks_midway_is_not_the_newest_version(self):
        def abrir_zip(erro):
            def abrir(url, timeout=30):
                self.pedidos.append(url)
                if url == "https://exemplo/zip":
                    raise erro
                return io.BytesIO(self.respostas[url])
            return abrir

        for erro in (ConnectionResetError("reset"), http.client.IncompleteRead(b"pedaco")):
            with self.subTest(erro=type(erro).__name__):
                shutil.rmtree(self.base, ignore_errors=True)
                aw.verificar(self.app, self.base, self.servidor(release("1.0.4"), pacote_zip("1.0.4")), agora=1000)
                self.publicar("1.0.5")
                self.pedidos.clear()
                with self.assertRaises(aw.FalhaDeRede):
                    aw.verificar(self.app, self.base, abrir_zip(erro), agora=1000 + 120, forcar=True)
                texto, tipo = aw.mensagem_para_os_pais(self.app, self.base, agora=1000 + 120)
                self.assertNotIn("versão mais nova", texto)
                self.assertIn("sem internet", texto)
                self.assertEqual(tipo, "error")
                estado = aw._estado(self.base)
                self.assertTrue(estado.get("sem_rede"))
                self.assertGreater(float(estado["tentado_em"]), float(estado["verificado_em"]))
                self.pedidos.clear()
                self.assertIsNone(aw.verificar(self.app, self.base, abrir_zip(erro), agora=1000 + 120 + 10 * 60))
                self.assertEqual(self.pedidos, [])

    def test_disk_full_during_download_is_not_the_newest_version(self):
        abrir = self.servidor(release("1.0.4"), pacote_zip("1.0.4"))
        aw.verificar(self.app, self.base, abrir, agora=1000)
        self.publicar("1.0.5")
        real_open = open

        def open_sem_disco(path, mode="r", *args, **kwargs):
            if os.path.basename(str(path)) == aw.ASSET and "w" in str(mode):
                raise OSError(28, "No space left on device")
            return real_open(path, mode, *args, **kwargs)

        with mock.patch("builtins.open", open_sem_disco):
            with self.assertRaises(OSError):
                aw.verificar(self.app, self.base, abrir, agora=1000 + 120, forcar=True)
        texto, tipo = aw.mensagem_para_os_pais(self.app, self.base, agora=1000 + 120)
        self.assertNotIn("versão mais nova", texto)
        self.assertIn("Não deu para baixar", texto)
        self.assertEqual(tipo, "error")
        self.pedidos.clear()
        self.assertIsNone(aw.verificar(self.app, self.base, abrir, agora=1000 + 120 + 10 * 60))
        self.assertEqual(self.pedidos, [])
        with mock.patch("builtins.open", open_sem_disco):
            with self.assertRaises(OSError):
                aw.verificar(self.app, self.base, abrir, agora=1000 + 120 + aw.REPETIR_SEM_REDE)
        self.assertTrue(self.pedidos)

    def test_attempt_newer_than_the_last_success_does_not_claim_up_to_date(self):
        aw._gravar_estado(self.base, verificado_em=1000, tentado_em=1000 + 120,
                          sem_rede=False, erro_download=None)
        texto, tipo = aw.mensagem_para_os_pais(self.app, self.base, agora=1000 + 120)
        self.assertNotIn("versão mais nova", texto)
        self.assertEqual(tipo, "error")

    def test_a_ready_version_that_already_failed_does_not_promise_to_install(self):
        abrir = self.servidor(release("1.0.5"), pacote_zip("1.0.5"))
        aw.verificar(self.app, self.base, abrir, agora=1000)
        aw.marcar_falha("1.0.5", self.base)
        texto, tipo = aw.mensagem_para_os_pais(self.app, self.base, agora=1000)
        self.assertEqual(texto, "A versão 1.0.5 não conseguiu instalar.")
        self.assertNotIn("vai ser instalada", texto)
        self.assertEqual(tipo, "error")
        self.publicar("1.0.6")
        self.assertEqual(aw.verificar(self.app, self.base, abrir, agora=1000 + 120, forcar=True), "1.0.6")
        aw.marcar_falha("1.0.5", self.base)
        texto, _tipo = aw.mensagem_para_os_pais(self.app, self.base, agora=1000 + 120)
        self.assertIn("Versão 1.0.6 baixada", texto)
        self.assertIn("vai ser instalada", texto)
        self.assertIn("A versão 1.0.5 não conseguiu instalar.", texto)

    def test_a_check_older_than_the_interval_does_not_claim_the_newest_version(self):
        abrir = self.servidor(release("1.0.4"), pacote_zip("1.0.4"))
        aw.verificar(self.app, self.base, abrir, agora=1000)
        texto, tipo = aw.mensagem_para_os_pais(self.app, self.base, agora=1000 + aw.INTERVALO)
        self.assertNotIn("versão mais nova", texto)
        self.assertIn("Toque em Ver atualizações", texto)
        self.assertEqual(tipo, "empty")
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
