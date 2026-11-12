import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import controles  # noqa: E402

LISTAR = controles.listar_dispositivos

# Os dois controles do notebook do Beni, como o kernel mostra
PROC = """I: Bus=0003 Vendor=413c Product=8505 Version=0111
N: Name="Dell Universal Receiver"
H: Handlers=sysrq kbd event5 leds

I: Bus=0003 Vendor=0079 Product=0006 Version=0110
N: Name="DragonRise Inc.   Generic   USB  Joystick  "
H: Handlers=event10 js0

I: Bus=0003 Vendor=0810 Product=0001 Version=0110
N: Name=" USB Gamepad          "
H: Handlers=event11 js1
"""
CAPS = {"event10": ("fff00000000 0 0 0 0", "3002f"),
        "event11": ("fff00000000 0 0 0 0", "30027")}

MAPA = {
    "up": "a:17:-1", "down": "a:17:1", "left": "a:16:-1", "right": "a:16:1",
    "a": "k:290", "b": "k:289", "x": "k:291", "y": "k:288",
    "l1": "k:294", "r1": "k:295", "l2": "k:292", "r2": "k:293",
    "select": "k:296", "start": "k:297",
    "lx": "a:0:1", "ly": "a:1:1", "rx": "a:5:1", "ry": "a:2:-1",
}


class FakeInput:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.proc = root / "devices"
        self.proc.write_text(PROC, encoding="utf-8")
        self.sys = root / "sys"
        for evento, (key, abs_) in CAPS.items():
            caps = self.sys / evento / "device" / "capabilities"
            caps.mkdir(parents=True)
            (caps / "key").write_text(key + "\n", encoding="utf-8")
            (caps / "abs").write_text(abs_ + "\n", encoding="utf-8")
        self.home = root / "home"
        self.home.mkdir()

    def dispositivos(self):
        return LISTAR(str(self.proc), str(self.sys))


class DispositivosTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeInput()
        self.addCleanup(self.fake.tmp.cleanup)

    def test_so_joysticks_entram_na_lista_em_ordem_de_evento(self):
        lista = self.fake.dispositivos()
        self.assertEqual([d["chave"] for d in lista], ["0079:0006", "0810:0001"])
        self.assertEqual(lista[0]["js"], "js0")

    def test_indices_seguem_a_ordem_do_sdl(self):
        dragon = self.fake.dispositivos()[0]
        self.assertEqual(controles.botoes_em_ordem(dragon["teclas"]), list(range(0x120, 0x12C)))
        # X, Y, Z, RX, RZ (o hat 0 não conta como eixo)
        self.assertEqual(controles.eixos_em_ordem(dragon["eixos"]), [0, 1, 2, 3, 5])
        self.assertEqual(controles.hats_em_ordem(dragon["eixos"]), [0x10])

    def test_guid_do_sdl_bate_com_a_base_do_sdl(self):
        dragon, usb = self.fake.dispositivos()
        self.assertEqual(controles.sdl_guid(dragon), "03000000790000000600000010010000")
        self.assertEqual(controles.sdl_guid(usb), "03000000100800000100000010010000")


class GeradoresTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeInput()
        self.addCleanup(self.fake.tmp.cleanup)
        self.dragon = self.fake.dispositivos()[0]

    def test_linha_sdl(self):
        linha = controles.linha_sdl(self.dragon, MAPA)
        partes = linha.split(",")
        self.assertEqual(partes[0], "03000000790000000600000010010000")
        self.assertEqual(partes[1], "DragonRise Inc. Generic USB Joystick")
        for esperado in ("a:b2", "b:b1", "x:b3", "y:b0", "leftshoulder:b6", "lefttrigger:b4",
                         "back:b8", "start:b9", "dpup:h0.1", "dpdown:h0.4", "dpleft:h0.8",
                         "dpright:h0.2", "leftx:a0", "lefty:a1", "rightx:a4", "righty:a2~"):
            self.assertIn(esperado, partes)
        self.assertTrue(linha.endswith("platform:Linux,"))

    def test_perfil_retroarch_usa_layout_do_snes(self):
        perfil = controles.perfil_retroarch(self.dragon, MAPA)
        self.assertIn('input_vendor_id = "121"', perfil)
        self.assertIn('input_product_id = "6"', perfil)
        self.assertIn('input_b_btn = "2"', perfil)   # ✕ (de baixo) = B do SNES
        self.assertIn('input_a_btn = "1"', perfil)   # ◯ (da direita) = A do SNES
        self.assertIn('input_up_btn = "h0up"', perfil)
        self.assertIn('input_l_x_plus_axis = "+0"', perfil)
        self.assertIn('input_r_y_plus_axis = "-2"', perfil)

    def test_direcional_por_eixo(self):
        mapa = dict(MAPA, up="a:1:-1", down="a:1:1", left="a:0:-1", right="a:0:1")
        self.assertIn("dpup:-a1", controles.linha_sdl(self.dragon, mapa).split(","))
        self.assertIn('input_left_axis = "-0"', controles.perfil_retroarch(self.dragon, mapa))
        cfg = controles.config_dfinput([(0, self.dragon, mapa)])
        self.assertIn("Up=65362,1,-2", cfg)
        self.assertIn("Right=65363,1,1", cfg)

    def test_dfinput(self):
        usb = self.fake.dispositivos()[1]
        cfg = controles.config_dfinput([(0, self.dragon, MAPA), (1, usb, None)])
        pad1, pad2 = cfg.split("[PAD2]")
        self.assertIn("DevNum=0", pad1)
        self.assertIn("Type=4", pad1)
        self.assertIn("Cross=122,3,2", pad1)
        self.assertIn("Circle=120,3,1", pad1)
        self.assertIn("Up=65362,2,1", pad1)        # hat 0, para cima
        self.assertIn("Left=65361,2,8", pad1)
        self.assertIn("Analog=98,0,0", pad1)
        # controle sem mapeamento: padrão do próprio DFInput, sem teclado
        self.assertIn("DevNum=1", pad2)
        self.assertIn("Cross=0,3,2", pad2)
        self.assertIn("Up=0,1,-2", pad2)
        self.assertIn("[EMU]", pad2)


class NavegadorTests(unittest.TestCase):
    """Numeração do Chromium medida nos dois controles reais (página de teste)."""

    def setUp(self):
        self.fake = FakeInput()
        self.addCleanup(self.fake.tmp.cleanup)
        self.dragon, self.usb = self.fake.dispositivos()

    def test_controle_desconhecido_pelo_chromium(self):
        # USB Gamepad: hat = eixos 4/5; Z = eixo 2; RZ = eixo 3
        mapa = dict(MAPA, rx="a:5:1", ry="a:2:1")
        tabela = controles.mapa_navegador(self.usb, mapa)
        self.assertEqual(tabela["botoes"]["up"], ["e", 5, -1])
        self.assertEqual(tabela["botoes"]["left"], ["e", 4, -1])
        self.assertEqual(tabela["botoes"]["a"], ["b", 2])
        self.assertEqual(tabela["botoes"]["y"], ["b", 0])
        self.assertEqual(tabela["eixos"]["rx"], [3, 1])
        self.assertEqual(tabela["eixos"]["ry"], [2, 1])

    def test_dragonrise_inclui_rx_na_contagem_de_eixos(self):
        tabela = controles.mapa_navegador(self.dragon, MAPA)
        self.assertEqual(tabela["botoes"]["up"], ["e", 6, -1])   # X Y Z RX RZ HAT0X HAT0Y
        self.assertEqual(tabela["eixos"]["rx"], [4, 1])

    def test_script_so_tem_controles_configurados(self):
        texto = controles.script_navegador([self.dragon, self.usb], {"0810:0001": {"mapa": MAPA}})
        self.assertTrue(texto.startswith("// Gerado pelo Beni Launcher"))
        tabela = json.loads(texto.split("window.__beniControles = ", 1)[1].rstrip(";\n"))
        self.assertEqual(list(tabela), ["0810:0001"])


class ServicoTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeInput()
        self.addCleanup(self.fake.tmp.cleanup)
        self.arquivo = self.fake.home / ".config" / "cozy-kids-launcher" / "controles.json"
        self.servico = controles.Controles(str(self.arquivo), str(self.fake.home))
        patcher = mock.patch.object(controles, "listar_dispositivos", self.fake.dispositivos)
        patcher.start()
        self.addCleanup(patcher.stop)
        antes = os.environ.get("SDL_GAMECONTROLLERCONFIG")
        self.addCleanup(lambda: os.environ.__setitem__("SDL_GAMECONTROLLERCONFIG", antes)
                        if antes is not None else os.environ.pop("SDL_GAMECONTROLLERCONFIG", None))

    def test_salvar_gera_configs_dos_jogos(self):
        self.servico.salvar("0079:0006", "DragonRise", MAPA)
        dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
        self.assertEqual(dados["controles"]["0079:0006"]["mapa"]["a"], "k:290")
        self.assertIn("03000000790000000600000010010000", os.environ["SDL_GAMECONTROLLERCONFIG"])
        perfil = self.fake.home / ".config" / "cozy-jogos" / "autoconfig" / "beni-0079-0006.cfg"
        self.assertTrue(perfil.is_file())
        dfinput = (self.fake.home / ".pcsxr" / "plugins" / "dfinput.cfg").read_text(encoding="utf-8")
        self.assertIn("Cross=122,3,2", dfinput)
        # a extensão do Chromium não está instalada neste HOME: não cria a pasta
        self.assertFalse((self.fake.home / ".var").exists())
        extensao = self.fake.home / ".var" / "app" / "org.chromium.Chromium" / "cozy-controle"
        extensao.mkdir(parents=True)
        self.servico.aplicar()
        self.assertIn('"0079:0006"', (extensao / "mapa.js").read_text(encoding="utf-8"))

        self.servico.esquecer("0079:0006")
        self.assertFalse(perfil.exists())
        self.assertNotIn("SDL_GAMECONTROLLERCONFIG", os.environ)

    def test_sem_mapeamento_nao_sobrescreve_dfinput_feito_a_mao(self):
        dfinput = self.fake.home / ".pcsxr" / "plugins" / "dfinput.cfg"
        dfinput.parent.mkdir(parents=True)
        dfinput.write_text("feito à mão", encoding="utf-8")
        self.servico.aplicar()
        self.assertEqual(dfinput.read_text(encoding="utf-8"), "feito à mão")

    def test_mapa_invalido_e_recusado(self):
        with self.assertRaises(ValueError):
            self.servico.salvar("0079:0006", "x", dict(MAPA, a="rm -rf"))
        with self.assertRaises(ValueError):
            self.servico.salvar("0079:0006", "x", {"up": "a:17:-1"})  # faltam botões
        with self.assertRaises(ValueError):
            self.servico.salvar("../../x", "x", MAPA)
        with self.assertRaises(ValueError):
            self.servico.salvar("0079:0006", "x", dict(MAPA, turbo="k:300"))

    def test_estado_lista_jogadores(self):
        self.servico.salvar("0810:0001", "USB", MAPA)
        estado = self.servico.estado()
        self.assertTrue(estado["navegarMenu"])
        self.assertEqual([(d["jogador"], d["chave"], bool(d["mapa"])) for d in estado["dispositivos"]],
                         [(1, "0079:0006", False), (2, "0810:0001", True)])
        self.assertEqual(estado["botoes"][0]["id"], "up")

    def test_captura_e_navegacao(self):
        dragon = self.fake.dispositivos()[0]
        teclas = []
        self.servico.pode_navegar = lambda: True
        with mock.patch.object(controles, "enviar_tecla", teclas.append):
            # sem mapeamento: só o direcional
            self.servico._acionado(dragon, "a:17:1")
            self.servico._acionado(dragon, "k:290")
            self.assertEqual(teclas, ["Down"])
            self.servico.salvar("0079:0006", "DragonRise", MAPA)
            self.servico._acionado(dragon, "k:290")
            self.servico._acionado(dragon, "k:289")
            self.assertEqual(teclas, ["Down", "Return", "Escape"])
            # durante a captura o controle não mexe no menu
            self.servico.captura_ate = float("inf")
            self.servico._acionado(dragon, "k:291")
            self.assertEqual(teclas, ["Down", "Return", "Escape"])
            captura = self.servico.ultima_captura(0)
            self.assertEqual((captura["evento"], captura["token"]), ("event10", "k:291"))
            self.assertIsNone(self.servico.ultima_captura(captura["seq"]))
            self.servico.parar_captura()
            # navegação desligada pelos pais
            self.servico.definir_navegacao(False)
            self.servico._acionado(dragon, "k:290")
            self.assertEqual(teclas, ["Down", "Return", "Escape"])
            # menu atrás de um app
            self.servico.definir_navegacao(True)
            self.servico.pode_navegar = lambda: False
            self.servico._acionado(dragon, "k:290")
            self.assertEqual(teclas, ["Down", "Return", "Escape"])

    def test_start_e_select_seguros_fecham_o_app_uma_vez(self):
        dragon = self.fake.dispositivos()[0]
        fechou = []
        self.servico.ao_sair = lambda: fechou.append(True)
        self.servico.salvar("0079:0006", "DragonRise", MAPA)   # select k:296, start k:297
        self.servico.abertos = {"event10": (None, dragon, {}, {})}
        self.servico.segurados = {"event10": {296, 297}}
        self.servico._verificar_saida(100.0)
        self.servico._verificar_saida(101.9)
        self.assertEqual(fechou, [])                 # ainda não deu 2 s
        self.servico._verificar_saida(102.0)
        self.servico._verificar_saida(105.0)
        self.assertEqual(fechou, [True])             # uma vez só enquanto segura
        self.servico.segurados = {"event10": {297}}  # soltou o Select
        self.servico._verificar_saida(106.0)
        self.servico.segurados = {"event10": {296, 297}}
        self.servico._verificar_saida(107.0)
        self.servico._verificar_saida(109.5)
        self.assertEqual(fechou, [True, True])
        # só Start, ou durante o assistente: nada
        self.servico.segurados = {"event10": {297}}
        self.servico._verificar_saida(120.0)
        self.servico._verificar_saida(125.0)
        self.servico.segurados = {"event10": {296, 297}}
        self.servico.captura_ate = float("inf")
        self.servico._verificar_saida(130.0)
        self.servico._verificar_saida(135.0)
        self.assertEqual(len(fechou), 2)

    def test_token_de_eixo_so_dispara_ao_cruzar_o_limite(self):
        estado = {}
        faixas = {0: (0, 255)}
        token = controles.Controles._token
        self.assertIsNone(token(3, 0, 128, faixas, estado))
        self.assertEqual(token(3, 0, 255, faixas, estado), "a:0:1")
        self.assertIsNone(token(3, 0, 250, faixas, estado))   # segurando
        self.assertIsNone(token(3, 0, 130, faixas, estado))   # voltou ao centro
        self.assertEqual(token(3, 0, 0, faixas, estado), "a:0:-1")
        self.assertEqual(token(1, 290, 1, faixas, estado), "k:290")
        self.assertIsNone(token(1, 290, 0, faixas, estado))   # soltou


if __name__ == "__main__":
    unittest.main()
