"""Menu nativo (cliente/, beni-menu) e as otimizações feitas junto com ele.

- servidor: /api/cliente/estado e /api/cliente/voltar (o navegador aberto pelo
  menu nativo avisa quando voltaria para o menu), cache da configuração e
  recomendações sem procurar programas no PATH a cada requisição;
- páginas web: cliente.html e frontend/cliente-nativo.js;
- controles: o controles.json não é relido a cada evento de analógico;
- script de início: checagem de processo em bash puro (process_alive_rapido)
  igual à do process_state.py, e o menu nativo com volta para o navegador;
- atualizador: baixa e confere o binário anexado à Release.
"""
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import controles  # noqa: E402
import test_server  # noqa: E402
from test_atualizador import atualizar  # noqa: E402

server_module = test_server.server_module
LAUNCHER = ROOT / "beni" / "bin" / "cozy-kids-launcher"


class ClienteNativoServidorTests(unittest.TestCase):
    setUp = test_server.ServerApiTests.setUp
    tearDown = test_server.ServerApiTests.tearDown
    request = test_server.ServerApiTests.request

    def test_voltar_ao_menu_incrementa_o_contador(self):
        status, antes, _ = self.request("/api/cliente/estado")
        self.assertEqual(status, 200)
        status, depois, _ = self.request("/api/cliente/voltar", method="POST", body={})
        self.assertEqual(status, 200)
        self.assertEqual(depois["voltar"], antes["voltar"] + 1)
        _, agora, _ = self.request("/api/cliente/estado")
        self.assertEqual(agora["voltar"], antes["voltar"] + 1)

    def test_voltar_recusa_outro_site(self):
        _, antes, _ = self.request("/api/cliente/estado")
        status, _, _ = self.request(
            "/api/cliente/voltar", method="POST", body={}, origin="https://exemplo.com"
        )
        self.assertEqual(status, 403)
        _, depois, _ = self.request("/api/cliente/estado")
        self.assertEqual(depois["voltar"], antes["voltar"])

    def test_config_em_cache_mas_relida_quando_muda(self):
        primeira = server_module.load_cfg()
        primeira["title"] = "mexido por quem chamou"
        self.assertNotEqual(server_module.load_cfg()["title"], "mexido por quem chamou")
        with mock.patch.object(server_module, "validate_stored_config",
                               side_effect=AssertionError("não devia revalidar")):
            server_module.load_cfg()
            server_module.load_stored_cfg()
        config = test_server.base_config()
        config["title"] = "Título novo"
        server_module.save_cfg(config)
        self.assertEqual(server_module.load_cfg()["title"], "Título novo")
        _, publica, _ = self.request("/api/config")
        self.assertEqual(publica["title"], "Título novo")

    def test_config_carregada_nao_procura_programas(self):
        Path(server_module.RECOMMENDATIONS_FILE).write_text(json.dumps([
            {"id": "x", "label": "X", "cmd": ["programa-x"], "alt_cmds": ["outro-x"]},
        ]), encoding="utf-8")
        with mock.patch.object(server_module.shutil, "which",
                               side_effect=AssertionError("não devia procurar")):
            server_module.save_cfg(test_server.base_config())
            server_module.load_stored_cfg()
            recs = server_module.load_recommendations(check_installed=False)
        self.assertEqual(recs[0]["cmd"], ["programa-x"])
        with mock.patch.object(server_module.shutil, "which", return_value=None) as which:
            self.assertFalse(server_module.load_recommendations()[0]["installed"])
        self.assertTrue(which.called)


class ClienteNativoWebTests(unittest.TestCase):
    def test_index_carrega_o_script_do_menu_nativo_por_ultimo(self):
        html = (ROOT / "src" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<script defer src="/frontend/cliente-nativo.js"></script>', html)
        self.assertGreater(html.index("cliente-nativo.js"), html.index("runtime-controls.js"))

    def test_cliente_html_so_aceita_caminho_local(self):
        html = (ROOT / "src" / "cliente.html").read_text(encoding="utf-8")
        self.assertIn("ir.charAt(0) !== '/'", html)
        self.assertIn("ir.charAt(1) === '/'", html)
        self.assertIn("sessionStorage.setItem('beniCliente', '1')", html)
        self.assertIn("location.replace(ir)", html)

    def test_script_so_age_em_aba_aberta_pelo_menu_nativo(self):
        js = (ROOT / "src" / "frontend" / "cliente-nativo.js").read_text(encoding="utf-8")
        self.assertIn("sessionStorage.getItem('beniCliente') === '1'", js)
        self.assertIn("if (!doCliente) return;", js)
        self.assertIn("/api/cliente/voltar", js)

    def test_instalador_leva_o_binario_quando_existe(self):
        texto = (ROOT / "instalar.sh").read_text(encoding="utf-8")
        self.assertIn('"$REPO/cliente/bin/beni-menu"', texto)
        self.assertIn('"$APP_ROOT/beni-menu"', texto)


class ControlesCacheTests(unittest.TestCase):
    def test_le_de_novo_so_quando_o_arquivo_muda_e_devolve_copia(self):
        with tempfile.TemporaryDirectory() as tmp:
            arquivo = os.path.join(tmp, "controles.json")
            Path(arquivo).write_text(json.dumps({"controles": {"a": {"nome": "A"}}}), encoding="utf-8")
            dados = controles.carregar(arquivo)
            dados["controles"]["a"]["nome"] = "mexido"
            self.assertEqual(controles.carregar(arquivo)["controles"]["a"]["nome"], "A")
            with mock.patch("builtins.open", side_effect=AssertionError("não devia abrir")):
                controles.carregar(arquivo)
            novo = os.path.join(tmp, "novo.json")
            Path(novo).write_text(json.dumps({"controles": {}, "navegarMenu": False}), encoding="utf-8")
            os.replace(novo, arquivo)
            self.assertFalse(controles.carregar(arquivo)["navegarMenu"])

    def test_start_select_nao_le_o_arquivo_sem_dois_botoes_apertados(self):
        servico = controles.Controles(os.devnull, tempfile.gettempdir(), ao_sair=lambda: None)
        servico.segurados = {"event10": {288}}
        with mock.patch.object(controles, "carregar", side_effect=AssertionError("não devia ler")):
            servico._verificar_saida(time.monotonic())


@unittest.skipUnless(sys.platform.startswith("linux"), "usa /proc")
class ProcessoRapidoTests(unittest.TestCase):
    """process_alive_rapido (bash) tem que concordar com process_state.py."""

    def setUp(self):
        texto = LAUNCHER.read_text(encoding="utf-8")
        inicio = texto.index("process_alive_rapido() {")
        fim = texto.index("\n}\n", inicio) + 3
        self.funcao = texto[inicio:fim]
        self.tmp = tempfile.TemporaryDirectory()
        self.filho = subprocess.Popen(["sleep", "30"])
        with open(f"/proc/{self.filho.pid}/stat", encoding="utf-8") as stat:
            self.inicio = int(stat.read().rsplit(")", 1)[1].split()[19])

    def tearDown(self):
        self.filho.kill()
        self.filho.wait()
        self.tmp.cleanup()

    def registro(self, **campos):
        dados = {"recordVersion": 1, "pid": self.filho.pid, "startTime": self.inicio, "role": "browser"}
        dados.update(campos)
        caminho = os.path.join(self.tmp.name, "r.pid")
        Path(caminho).write_text(json.dumps(dados, separators=(",", ":")) + "\n", encoding="utf-8")
        return caminho

    def rapido(self, caminho, papel="browser"):
        script = (
            "process_alive() { python3 " + str(ROOT / "src" / "process_state.py")
            + ' alive "$1" "$2" >/dev/null 2>&1; }\n' + self.funcao
            + f'\nprocess_alive_rapido "{caminho}" "{papel}"'
        )
        return subprocess.run(["bash", "-c", script], capture_output=True, timeout=10).returncode

    def python(self, caminho, papel="browser"):
        return subprocess.run(
            [sys.executable, str(ROOT / "src" / "process_state.py"), "alive", caminho, papel],
            capture_output=True, timeout=10,
        ).returncode

    def test_concorda_com_o_python(self):
        casos = [
            (self.registro(), "browser"),
            (self.registro(), "server"),
            (self.registro(startTime=1), "browser"),
            (self.registro(marker="sleep"), "browser"),
            (self.registro(marker="/nao/e/este"), "browser"),
            (self.registro(recordVersion=2), "browser"),
            (self.registro(pid=999999999), "browser"),
            (os.path.join(self.tmp.name, "nao-existe.pid"), "browser"),
        ]
        for caminho, papel in casos:
            conteudo = Path(caminho).read_text(encoding="utf-8") if os.path.exists(caminho) else "(sem arquivo)"
            with self.subTest(registro=conteudo, papel=papel):
                self.assertEqual(self.rapido(caminho, papel), self.python(caminho, papel))

    def test_sem_mensagens_de_erro(self):
        caminho = os.path.join(self.tmp.name, "nao-existe.pid")
        script = self.funcao + f'\nprocess_alive_rapido "{caminho}" browser'
        resultado = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=10)
        self.assertEqual(resultado.returncode, 1)
        self.assertEqual(resultado.stderr, "")


class LauncherMenuNativoTests(unittest.TestCase):
    def test_script_usa_o_menu_nativo_e_volta_para_o_navegador(self):
        texto = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn('MENU_NATIVO="$APP_ROOT/beni-menu"', texto)
        self.assertIn('[[ "$NATIVO_STATUS" == "75" ]]', texto)
        self.assertIn("USAR_NATIVO=0", texto)
        self.assertIn('while process_alive_rapido "$BROWSER_PIDFILE" browser; do', texto)
        subprocess.run(["bash", "-n", str(LAUNCHER)], check=True)


class AtualizadorMenuNativoTests(unittest.TestCase):
    def release(self, binario, sha):
        return {"assets": [
            {"name": "beni-menu-linux-x86_64", "browser_download_url": "https://x/bin"},
            {"name": "beni-menu-linux-x86_64.sha256", "browser_download_url": "https://x/sha"},
        ], "_bin": binario, "_sha": sha}

    def baixar(self, release, destino):
        def fetch(url, timeout=30):
            return io.BytesIO(release["_bin"] if url.endswith("/bin") else release["_sha"])
        with mock.patch.object(atualizar, "fetch", side_effect=fetch), \
                mock.patch.object(atualizar, "log"):
            return atualizar.download_native_menu(release, destino)

    def test_baixa_e_confere_o_sha256(self):
        binario = b"\x7fELF binario de teste"
        sha = (hashlib.sha256(binario).hexdigest() + "  beni-menu-linux-x86_64\n").encode()
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(self.baixar(self.release(binario, sha), tmp))
            alvo = Path(tmp) / "beni-menu"
            self.assertEqual(alvo.read_bytes(), binario)
            self.assertTrue(os.access(alvo, os.X_OK))

    def test_recusa_sha256_errado(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(self.baixar(self.release(b"abc", b"0" * 64 + b"\n"), tmp))
            self.assertFalse((Path(tmp) / "beni-menu").exists())

    def test_release_sem_binario_segue(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(atualizar, "log"):
            self.assertFalse(atualizar.download_native_menu({"assets": []}, tmp))

    def test_espera_o_binario_so_em_release_recente(self):
        import datetime
        agora = datetime.datetime.now(datetime.timezone.utc)
        recente = {"published_at": (agora - datetime.timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        antiga = {"published_at": (agora - datetime.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        self.assertTrue(atualizar.release_is_fresh(recente))
        self.assertFalse(atualizar.release_is_fresh(antiga))
        self.assertFalse(atualizar.release_is_fresh({}))


if __name__ == "__main__":
    unittest.main()
