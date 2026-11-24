"""Lógica do controle no Windows, sem hardware.

A leitura de verdade (XInput/HID) não roda no CI. Aqui ficam o mapeamento que
vira tecla, o Start+Select com o tempo, a pausa quando não há controle, o
texto do SDL e a extensão do Edge.
"""

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import application_launcher  # noqa: E402
import catalogo_windows  # noqa: E402
import controles  # noqa: E402
import controles_windows  # noqa: E402

MAPA = {
    "up": "a:17:-1", "down": "a:17:1", "left": "a:16:-1", "right": "a:16:1",
    "a": "k:290", "b": "k:289", "x": "k:291", "y": "k:288",
    "l1": "k:294", "r1": "k:295", "l2": "k:292", "r2": "k:293",
    "select": "k:296", "start": "k:297",
    "lx": "a:0:1", "ly": "a:1:1", "rx": "a:5:1", "ry": "a:2:-1",
}


class PausaTests(unittest.TestCase):
    def test_sem_controle_a_espera_e_de_segundos(self):
        self.assertGreaterEqual(controles.pausa_da_leitura(0), 2.0)
        self.assertLess(controles.pausa_da_leitura(1), 0.2)

    def test_volta_sem_controle_nao_gira(self):
        with tempfile.TemporaryDirectory() as home:
            servico = controles.Controles(os.devnull, home)
            esperas = []

            def esperar(segundos):
                esperas.append(segundos)
                servico.parar.set()

            controles_windows.rodar(servico, listar=lambda: [], ler=lambda _s: None, esperar=esperar)
            self.assertEqual(esperas, [controles.PAUSA_SEM_CONTROLE_S])

    def test_com_controle_le_em_vez_de_dormir_dois_segundos(self):
        disp = controles_windows.dispositivo_de_layout(0x0079, 0x0006, "DragonRise", 12, 6, True)
        with tempfile.TemporaryDirectory() as home:
            servico = controles.Controles(os.devnull, home)
            lidas = []

            def ler(alvo):
                lidas.append(len(alvo.abertos))
                alvo.parar.set()

            controles_windows.rodar(servico, listar=lambda: [disp], ler=ler, esperar=lambda _s: None)
            self.assertEqual(lidas, [1])

    def test_listar_fora_do_windows_nao_abre_dll(self):
        self.assertEqual(controles_windows.listar_dispositivos(), [])


class MapeamentoTests(unittest.TestCase):
    def test_gatilho_solto_nao_dispara(self):
        estado = {}
        self.assertIsNone(controles_windows.token_gatilho(4, 0, estado))
        self.assertIsNone(controles_windows.token_gatilho(4, 40, estado))
        self.assertEqual(controles_windows.token_gatilho(4, 255, estado), "a:4:1")
        self.assertIsNone(controles_windows.token_gatilho(4, 255, estado))
        self.assertIsNone(controles_windows.token_gatilho(4, 0, estado))
        self.assertEqual(controles_windows.token_gatilho(4, 200, estado), "a:4:1")

    def test_hat_hid_casa_com_o_eixo_do_linux(self):
        self.assertEqual(controles_windows.eixos_do_hat(0), (0, -1))   # cima
        self.assertEqual(controles_windows.eixos_do_hat(2), (1, 0))    # direita
        self.assertEqual(controles_windows.eixos_do_hat(4), (0, 1))    # baixo
        self.assertEqual(controles_windows.eixos_do_hat(6), (-1, 0))   # esquerda
        self.assertEqual(controles_windows.eixos_do_hat(8), (0, 0))    # neutro
        self.assertEqual(controles_windows.eixos_do_hat(None), (0, 0))

    def test_transicao_so_no_aperto(self):
        self.assertEqual(controles_windows.transicoes_botoes(set(), {296, 297}),
                         [(296, 1), (297, 1)])
        self.assertEqual(controles_windows.transicoes_botoes({297}, {297}), [])
        self.assertEqual(controles_windows.transicoes_botoes({296, 297}, {297}), [(296, 0)])

    def test_mapeamento_vira_tecla_do_menu(self):
        disp = controles_windows.dispositivo_de_layout(0x0079, 0x0006, "DragonRise", 12, 6, True)
        with tempfile.TemporaryDirectory() as home:
            arquivo = os.path.join(home, "controles.json")
            servico = controles.Controles(arquivo, home, pode_navegar=lambda: True)
            teclas = []
            with mock.patch.object(controles, "enviar_tecla", teclas.append):
                servico.salvar("0079:0006", "DragonRise", MAPA)
                servico._acionado(disp, "k:290")
                servico._acionado(disp, "k:289")
                servico._acionado(disp, "a:17:-1")
            self.assertEqual(teclas, ["Return", "Escape", "Up"])

    def test_start_select_com_as_transicoes_dispara_uma_vez_aos_dois_segundos(self):
        disp = controles_windows.dispositivo_de_layout(0x0079, 0x0006, "DragonRise", 12, 6, True)
        with tempfile.TemporaryDirectory() as home:
            arquivo = os.path.join(home, "controles.json")
            fechou = []
            servico = controles.Controles(arquivo, home, ao_sair=lambda: fechou.append(True))
            servico.salvar("0079:0006", "DragonRise", MAPA)
            servico.abertos = {"hid0": (None, disp, {}, {})}
            apertados = set()
            for codigo, valor in controles_windows.transicoes_botoes(set(), {296, 297}):
                if valor:
                    apertados.add(codigo)
            servico.segurados = {"hid0": apertados}
            servico._verificar_saida(10.0)
            servico._verificar_saida(11.9)
            self.assertEqual(fechou, [])
            servico._verificar_saida(12.0)
            servico._verificar_saida(15.0)
            self.assertEqual(fechou, [True])

    def test_linha_sdl_do_generico_e_windows_e_o_xbox_fica_de_fora(self):
        hid = controles_windows.dispositivo_de_layout(
            0x0079, 0x0006, "DragonRise Inc. Generic USB Joystick", 12, 6, True)
        xbox = controles_windows.dispositivo_de_layout(
            0x045E, 0x02A1, "Controle Xbox", 10, 6, True, tipo="xinput", evento="xinput0")
        self.assertEqual(controles.sdl_guid(hid), "03000000790000000600000000006800")
        self.assertEqual(hid["driver"], "h")
        self.assertIn("platform:Windows", controles.linha_sdl(hid, MAPA))
        self.assertIn("a:b2", controles.linha_sdl(hid, MAPA).split(","))
        self.assertIn("dpup:h0.1", controles.linha_sdl(hid, MAPA).split(","))
        with tempfile.TemporaryDirectory() as home:
            arquivo = os.path.join(home, "controles.json")
            dados = {"navegarMenu": True, "controles": {
                "0079:0006": {"nome": "D", "mapa": MAPA},
                "045e:02a1": {"nome": "X", "mapa": MAPA},
            }}
            with open(arquivo, "w", encoding="utf-8") as f:
                json.dump(dados, f)
            antes = os.environ.get("SDL_GAMECONTROLLERCONFIG")
            self.addCleanup(lambda: os.environ.__setitem__("SDL_GAMECONTROLLERCONFIG", antes)
                            if antes is not None else os.environ.pop("SDL_GAMECONTROLLERCONFIG", None))
            controles.Controles(arquivo, home).aplicar([hid, xbox])
            texto = os.environ["SDL_GAMECONTROLLERCONFIG"]
            self.assertIn("03000000790000000600000000006800", texto)
            self.assertNotIn("045e", texto.lower())
            self.assertIn("platform:Windows", texto)

    def test_structs_hid_tem_o_tamanho_do_windows(self):
        # Conferido contra o SDK: se mudar, a leitura do DragonRise lê lixo.
        self.assertEqual(ctypes.sizeof(controles_windows.HIDP_CAPS), 64)
        self.assertEqual(ctypes.sizeof(controles_windows.HIDP_BUTTON_CAPS), 72)
        self.assertEqual(ctypes.sizeof(controles_windows.HIDP_VALUE_CAPS), 72)
        self.assertEqual(ctypes.sizeof(controles_windows._XINPUT_STATE), 16)
        self.assertEqual(ctypes.sizeof(controles_windows._OVERLAPPED), 32)


class AmbienteEEdgeTests(unittest.TestCase):
    def test_ambiente_do_app_ganha_o_mapeamento_salvo(self):
        with mock.patch.dict(os.environ, {"SDL_GAMECONTROLLERCONFIG": "linha-do-controle"}):
            junto = catalogo_windows.com_controle({"SDL_RENDER_DRIVER": "opengl"})
            self.assertEqual(junto["SDL_GAMECONTROLLERCONFIG"], "linha-do-controle")
            self.assertEqual(junto["SDL_RENDER_DRIVER"], "opengl")
            # o catálogo, se um dia trouxer a variável, não é substituído
            self.assertEqual(
                catalogo_windows.com_controle({"SDL_GAMECONTROLLERCONFIG": "do-catalogo"})
                ["SDL_GAMECONTROLLERCONFIG"],
                "do-catalogo",
            )
        ambiente = dict(os.environ)
        ambiente.pop("SDL_GAMECONTROLLERCONFIG", None)
        with mock.patch.dict(os.environ, ambiente, clear=True):
            self.assertEqual(catalogo_windows.com_controle({"A": "1"}), {"A": "1"})

    def test_edge_carrega_a_extensao_num_unico_disable_features(self):
        with tempfile.TemporaryDirectory() as tmp:
            comando = application_launcher.external_browser_command(
                "msedge.exe", "https://x.org/", tmp, extensao=os.path.join(tmp, "cozy-controle"))
        self.assertIn(f"--load-extension={os.path.join(tmp, 'cozy-controle')}", comando)
        flags = [a for a in comando if a.startswith("--disable-features")]
        self.assertEqual(flags, ["--disable-features=Translate,DisableLoadExtensionCommandLineSwitch"])

    def test_script_do_windows_marca_a_plataforma_e_o_linux_nao(self):
        texto = controles.script_navegador([], {}, plataforma="windows")
        self.assertIn('window.__beniPlataforma = "windows";', texto)
        linux = controles.script_navegador([], {}, plataforma="")
        self.assertNotIn("__beniPlataforma", linux)
        raiz = os.path.join(os.path.dirname(__file__), "..")
        caminho = os.path.join(raiz, "beni", "chromium", "controle", "controle.js")
        windows = os.path.join(raiz, "src", "extensao-controle", "controle.js")
        with open(caminho, encoding="utf-8") as arquivo:
            js = arquivo.read()
        with open(windows, encoding="utf-8") as arquivo:
            self.assertEqual(arquivo.read(), js)
        self.assertIn("ehXInput", js)
        self.assertIn('__beniPlataforma === "windows"', js)
        self.assertNotIn('mapping === "standard") return pad', js)
        self.assertIn("VID_", js)

    def test_generico_standard_no_windows_usa_o_mapa_e_o_xinput_nao(self):
        # O Linux não define __beniPlataforma: o XInput com mapa ainda é reordenado lá.
        arquivo = os.path.join(os.path.dirname(__file__), "..", "src", "extensao-controle", "controle.js")
        programa = r"""
const fs = require("fs");
const vm = require("vm");
const arquivo = process.argv[1];
const mapas = {
  "0079:0006": { botoes: { a: ["b", 2] }, eixos: {} },
  "045e:028e": { botoes: { a: ["b", 1] }, eixos: {} },
};
function pad(id, mapping, apertado) {
  const buttons = [];
  for (let i = 0; i < 17; i++) {
    const on = i === apertado;
    buttons.push({ pressed: on, touched: on, value: on ? 1 : 0 });
  }
  return { id, index: 0, connected: true, timestamp: 1, mapping, axes: [0, 0, 0, 0], buttons };
}
function carregar(plataforma) {
  const g = {
    window: { __beniControles: mapas, addEventListener() {} },
    console,
  };
  if (plataforma) g.window.__beniPlataforma = plataforma;
  function Navigator() {}
  Navigator.prototype.getGamepads = function () { return g._pads; };
  g.Navigator = Navigator;
  vm.runInNewContext(fs.readFileSync(arquivo, "utf8"), g, { filename: arquivo });
  return function (p) { g._pads = [p]; return new Navigator().getGamepads()[0]; };
}
function apertado(saida) {
  return saida.buttons.findIndex(b => b.pressed);
}
const win = carregar("windows");
const linux = carregar("");
const generico = "USB Gamepad (Vendor: 0079 Product: 0006)";
const xbox = "Xbox 360 Controller (XInput STANDARD GAMEPAD Vendor: 045e Product: 028e)";
const semMapa = "USB Gamepad (Vendor: 0810 Product: 0001)";
const casos = [
  ["win-generico-standard", apertado(win(pad(generico, "standard", 2))), 0],
  ["win-xinput-standard", apertado(win(pad(xbox, "standard", 1))), 1],
  ["win-sem-mapa", apertado(win(pad(semMapa, "standard", 2))), 2],
  ["win-generico-cru", apertado(win(pad(generico, "", 2))), 0],
  ["linux-generico-standard", apertado(linux(pad(generico, "standard", 2))), 0],
  ["linux-xinput-standard", apertado(linux(pad(xbox, "standard", 1))), 0],
];
const erros = casos.filter(c => c[1] !== c[2]).map(c => c[0] + " veio " + c[1] + " esperava " + c[2]);
if (erros.length) { console.error(erros.join("\n")); process.exit(1); }
console.log("ok");
"""
        proc = subprocess.run(
            ["node", "-e", programa, arquivo], capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)


if __name__ == "__main__":
    unittest.main()
