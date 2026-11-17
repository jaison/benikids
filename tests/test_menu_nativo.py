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

    def test_evento_de_recuperacao_so_aceita_etapas_conhecidas(self):
        with mock.patch.object(server_module, "log_runtime_event", return_value=True) as log:
            status, corpo, _ = self.request("/api/cliente/evento", method="POST", body={"etapa": "config"})
            self.assertEqual((status, corpo["status"]), (200, "ok"))
            log.assert_called_once_with("cliente.recuperado", level="warning", etapa="config")
            status, corpo, _ = self.request("/api/cliente/evento", method="POST", body={"etapa": "render", "erro": "x is not defined"})
            self.assertEqual(status, 200)
            log.assert_called_with("cliente.recuperado", level="warning", etapa="render", erro="x is not defined")
            log.reset_mock()
            status, corpo, _ = self.request("/api/cliente/evento", method="POST", body={"etapa": 5})
            self.assertEqual((status, corpo["status"]), (200, "ignored"))
            log.assert_not_called()

    def test_fila_de_conexoes_aguenta_a_abertura_da_pagina(self):
        # a página pede ~30 arquivos de uma vez; com a fila padrão (5) o Windows recusa
        self.assertGreaterEqual(server_module.Servidor.request_queue_size, 64)

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

    def test_windows_nao_procura_comandos_de_linux_no_path(self):
        Path(server_module.RECOMMENDATIONS_FILE).write_text(json.dumps([
            {"id": "x", "label": "X", "cmd": ["programa-x"]},
            {"id": "n", "label": "N", "cmd": ["navegador"], "category": "browser"},
        ]), encoding="utf-8")
        with mock.patch.object(server_module.os, "name", "nt"), \
                mock.patch.object(server_module.shutil, "which",
                                  side_effect=AssertionError("não devia procurar")):
            recs = server_module.load_recommendations()
        self.assertEqual([r["installed"] for r in recs], [False, True])


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

    def test_cliente_html_guarda_a_espera_do_pin_do_menu(self):
        html = (ROOT / "src" / "cliente.html").read_text(encoding="utf-8")
        # o id vem depois do "#" (não vai ao servidor) e só com caracteres seguros
        self.assertIn("/^#espera=([A-Za-z0-9_-]{16,64})$/.exec(location.hash)", html)
        self.assertIn("sessionStorage.setItem('beniEspera', espera[1])", html)
        self.assertIn("sessionStorage.removeItem('beniEspera')", html)
        # segue sem o "#": location.replace(ir) usa só o caminho
        self.assertLess(html.index("beniEspera"), html.index("location.replace(ir)"))

    def test_pagina_escondida_espera_o_pin_do_menu_sem_abrir_a_area_dos_pais(self):
        js = (ROOT / "src" / "frontend" / "cliente-nativo.js").read_text(encoding="utf-8")
        self.assertIn("postJson('/api/pais/espera', { espera: esperaId })", js)
        self.assertIn("postJson('/api/pais/entrar', { token: res.d.token })", js)
        # antes do PIN não abre a área dos pais (nem o PIN da página)
        self.assertIn("if (avisou || recarregando || aguardandoMenu || !temCfg()) return;", js)
        self.assertIn("if (aguardandoMenu) { vazioDesde = 0; return; }", js)
        # coberta com o fundo da marca, por cima de tudo
        self.assertIn("capa.className = 'cliente-capa';", js)
        self.assertIn(".cliente-capa { position:fixed; inset:0; z-index:2147483647;", js)
        # cookie trocado: abre o painel direto; falhou: cai no PIN da página
        self.assertIn("if (r.ok) entrarDepois = true;", js)
        self.assertIn("esqueceEspera(); // espera desconhecida: PIN da página", js)

    def test_script_so_age_em_aba_aberta_pelo_menu_nativo(self):
        js = (ROOT / "src" / "frontend" / "cliente-nativo.js").read_text(encoding="utf-8")
        self.assertIn("sessionStorage.getItem('beniCliente') === '1'", js)
        self.assertIn("if (!doCliente) return;", js)
        self.assertIn("/api/cliente/voltar", js)

    def test_avisos_de_tempo_nao_cobrem_o_pin_na_aba_do_menu_nativo(self):
        # Com o tempo esgotado, o "Acabou o tempo!" da página (z-index 250) cobria o
        # PIN e a área dos pais, com o tema da criança; o aviso é do menu nativo.
        js = (ROOT / "src" / "frontend" / "cliente-nativo.js").read_text(encoding="utf-8")
        self.assertIn("html.beni-cliente #timerBlock, html.beni-cliente #timerWarning, html.beni-cliente #usageMessage { display:none !important; }", js)

    def test_pin_aparece_sem_esperar_o_carregamento_e_tela_nao_fica_vazia(self):
        js = (ROOT / "src" / "frontend" / "cliente-nativo.js").read_text(encoding="utf-8")
        # pede o PIN logo que a configuração chega (sem PIN, espera carregar tudo)
        self.assertIn("if (!cfg.pinConfigured && !carregou) return;", js)
        # se o navegador não fechar depois de "voltar", a página aparece de novo
        self.assertIn("document.body.style.visibility = '';", js)
        self.assertIn("}, 5000);", js)

    def test_vigia_recupera_a_tela_vazia(self):
        # Windows, pacotes 10.2/10.3: um arquivo da página ou o /api/config falhando na
        # abertura deixava a aba só com o fundo (ou o PIN no tema) até o F5.
        js = (ROOT / "src" / "frontend" / "cliente-nativo.js").read_text(encoding="utf-8")
        self.assertIn("setInterval(vigiar, 1000);", js)
        # o tempo conta desde a PRIMEIRA falha: carregar() não reinicia o relógio
        self.assertNotIn("cargaDesde = Date.now()", js)
        self.assertIn("if (Date.now() - semCfgDesde > 6000 || falhasSeguidas >= 3) {", js)
        self.assertIn("espera.hidden = Date.now() - semCfgDesde < 2000;", js)
        # recarrega como o F5, no máximo 3 vezes por aba
        self.assertIn("const MAX_RECARGAS = 3;", js)
        self.assertIn("location.reload();", js)
        # arquivo da página que não carregou (capturado no index.html)
        self.assertIn("recarregar('recurso'", js)
        # PIN aceito antes da configuração voltar: o painel abre depois
        self.assertIn("if (!temCfg()) { entrarDepois = true; return; }", js)
        self.assertIn("registrar('pin');", js)
        # o erro real vai para o diagnóstico, sem textos entre aspas
        self.assertIn("dados.erro = textoDoErro(erro);", js)
        self.assertIn("Abrindo a área dos pais…", js)

    def test_index_guarda_os_arquivos_que_nao_carregaram_antes_de_tudo(self):
        html = (ROOT / "src" / "index.html").read_text(encoding="utf-8")
        captura = html.index('<script src="/frontend/recursos.js"></script>')
        self.assertLess(captura, html.index('<link rel="stylesheet"'))
        js = (ROOT / "src" / "frontend" / "recursos.js").read_text(encoding="utf-8")
        self.assertIn("window.beniRecursosFalhos = [];", js)
        self.assertIn("window.addEventListener('error', function (e) {", js)
        self.assertIn("recursos.js marca.css", (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8"))

    def test_erro_ao_desenhar_nao_apaga_a_configuracao(self):
        js = (ROOT / "src" / "frontend" / "launcher-ui.js").read_text(encoding="utf-8")
        self.assertIn("erro.etapa='render';", js)
        self.assertIn("if(!cfg||!e||e.etapa!=='render'){", js)
        # uma carga por vez
        self.assertIn("if(bootstrapPromise) return bootstrapPromise;", js)

    def test_pin_fica_acima_do_aviso_de_tempo_esgotado(self):
        import re
        css = (ROOT / "src" / "frontend" / "styles.css").read_text(encoding="utf-8")
        timer = int(re.search(r"\.timeroverlay \{[^}]*z-index:(\d+)", css).group(1))
        pin = int(re.search(r"#pin\.pinoverlay \{ z-index:(\d+)", css).group(1))
        self.assertGreater(pin, timer)

    def test_pin_nao_e_campo_de_senha(self):
        # type=password fazia o Edge oferecer "Salvar senha" com o PIN dos pais
        for nome, ids in (("index.html", ("pinInput", "timerBlockPin", "cfgPin", "cfgPinConfirm")),
                          ("configurar.html", ("pin", "pin2")), ("browser.html", ("timerBlockPin",))):
            html = (ROOT / "src" / nome).read_text(encoding="utf-8")
            for i in ids:
                self.assertIn(f'<input id="{i}" type="text" class="campo-pin" inputmode="numeric" autocomplete="off"', html, (nome, i))
            self.assertNotIn('type="password"', html, nome)
        css = (ROOT / "src" / "frontend" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".campo-pin{-webkit-text-security:disc}", css)

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
