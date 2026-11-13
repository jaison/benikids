"""Controles (gamepads USB) do Beni Launcher.

Lê os controles direto do kernel (/dev/input/eventN, sem dependências), guarda o
mapeamento feito pelos pais na área dos pais e, a partir dele, gera:

  - navegação do menu: direcional = setas, ✕ = Enter, ◯ = Esc (só quando a
    janela do menu está na frente e nenhum app está aberto);
  - SDL_GAMECONTROLLERCONFIG para os jogos SDL (SuperTux, SuperTuxKart...);
  - perfil de autoconfig do RetroArch (Super Nintendo);
  - ~/.pcsxr/plugins/dfinput.cfg (PlayStation).

O mapeamento é guardado pelos códigos do kernel (ex.: "k:289" = botão
BTN_THUMB, "a:17:-1" = eixo ABS_HAT0Y para o lado negativo), que não mudam de
um programa para outro. Os índices que cada programa usa (SDL, RetroArch udev e
DFInput numeram os botões e eixos do mesmo jeito) são calculados a partir das
capacidades do dispositivo.
"""

import copy
try:
    import fcntl  # Linux (evdev); no Windows os controles ainda não são lidos
except ImportError:
    fcntl = None
import json
import os
import re
import select
import shutil
import struct
import subprocess
import threading
import time

PROC_DEVICES = "/proc/bus/input/devices"
SYS_INPUT = "/sys/class/input"
DEV_INPUT = "/dev/input"

EV_KEY = 0x01
EV_ABS = 0x03
BTN_MISC = 0x100
BTN_JOYSTICK = 0x120
KEY_MAX = 0x2FF
ABS_HAT0X = 0x10
ABS_HAT3Y = 0x17
ABS_MISC = 0x28
EVENT_FORMAT = "llHHi"
EVENT_SIZE = struct.calcsize(EVENT_FORMAT)

# Botões lógicos, na ordem do assistente. Nomes de face no layout do SDL:
# a = de baixo (✕), b = da direita (◯), x = da esquerda (□), y = de cima (△).
BOTOES = (
    ("up", "Direcional para CIMA", True),
    ("down", "Direcional para BAIXO", True),
    ("left", "Direcional para a ESQUERDA", True),
    ("right", "Direcional para a DIREITA", True),
    ("a", "Botão de BAIXO (✕) — confirmar", True),
    ("b", "Botão da DIREITA (◯) — voltar", True),
    ("x", "Botão da ESQUERDA (□)", True),
    ("y", "Botão de CIMA (△)", True),
    ("l1", "Gatilho L1 (ombro esquerdo)", False),
    ("r1", "Gatilho R1 (ombro direito)", False),
    ("l2", "Gatilho L2 (de baixo, esquerdo)", False),
    ("r2", "Gatilho R2 (de baixo, direito)", False),
    ("select", "SELECT", False),
    ("start", "START", False),
    ("lx", "Analógico ESQUERDO: empurre para a DIREITA", False),
    ("ly", "Analógico ESQUERDO: empurre para BAIXO", False),
    ("rx", "Analógico DIREITO: empurre para a DIREITA", False),
    ("ry", "Analógico DIREITO: empurre para BAIXO", False),
)
NOMES_BOTOES = tuple(nome for nome, _, _ in BOTOES)
OBRIGATORIOS = tuple(nome for nome, _, obrigatorio in BOTOES if obrigatorio)
EIXOS_ANALOGICOS = ("lx", "ly", "rx", "ry")
TOKEN = re.compile(r"^(?:k:(\d{1,4})|a:(\d{1,3}):(-1|1))$")
CHAVE_CONTROLE = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{4}$")

# Saída de emergência: Start + Select seguros por este tempo fecham o app aberto
SEGURAR_PARA_SAIR_S = 2.0

TECLAS_MENU = {"up": "Up", "down": "Down", "left": "Left", "right": "Right",
               "a": "Return", "start": "Return", "b": "Escape"}


# ------------------------------------------------------------------ dispositivos

def _bits(texto):
    """Bitmap de /sys/.../capabilities/* (palavras hex, a mais significativa primeiro)."""
    valor = 0
    palavras = texto.split()
    largura = 64 if struct.calcsize("l") == 8 else 32
    for palavra in palavras:
        valor = (valor << largura) | int(palavra, 16)
    return valor


def _ler(caminho):
    try:
        with open(caminho, encoding="utf-8") as arquivo:
            return arquivo.read().strip()
    except OSError:
        return ""


def listar_dispositivos(proc_devices=PROC_DEVICES, sys_input=SYS_INPUT):
    """Controles conectados (os que o kernel expõe como joystick, jsN)."""
    try:
        with open(proc_devices, encoding="utf-8", errors="replace") as arquivo:
            blocos = arquivo.read().split("\n\n")
    except OSError:
        return []
    achados = []
    for bloco in blocos:
        info = {}
        for linha in bloco.splitlines():
            if linha.startswith("I:"):
                for par in linha[2:].split():
                    if "=" in par:
                        chave, valor = par.split("=", 1)
                        info[chave.lower()] = valor.lower()
            elif linha.startswith("N: Name="):
                info["nome"] = linha[len("N: Name="):].strip().strip('"')
            elif linha.startswith("H: Handlers="):
                info["handlers"] = linha[len("H: Handlers="):].split()
        handlers = info.get("handlers", [])
        evento = next((h for h in handlers if re.fullmatch(r"event\d+", h)), None)
        js = next((h for h in handlers if re.fullmatch(r"js\d+", h)), None)
        if not evento or not js:
            continue
        caps = os.path.join(sys_input, evento, "device", "capabilities")
        teclas = _bits(_ler(os.path.join(caps, "key")) or "0")
        eixos = _bits(_ler(os.path.join(caps, "abs")) or "0")
        achados.append({
            "evento": evento,
            "js": js,
            "nome": info.get("nome", "Controle"),
            "bus": info.get("bus", "0003"),
            "vendor": info.get("vendor", "0000"),
            "product": info.get("product", "0000"),
            "version": info.get("version", "0000"),
            "chave": f"{info.get('vendor', '0000')}:{info.get('product', '0000')}",
            "teclas": teclas,
            "eixos": eixos,
        })
    achados.sort(key=lambda d: int(d["evento"][5:]))
    return achados


def botoes_em_ordem(teclas):
    """Códigos de botão na ordem de índice do SDL / RetroArch udev / joydev."""
    codigos = [c for c in range(BTN_JOYSTICK, KEY_MAX) if teclas >> c & 1]
    codigos += [c for c in range(0, BTN_JOYSTICK) if teclas >> c & 1]
    return codigos


def eixos_em_ordem(eixos):
    """Códigos de eixo (sem os direcionais "hat") na ordem de índice do SDL."""
    return [c for c in range(ABS_MISC) if eixos >> c & 1 and not ABS_HAT0X <= c <= ABS_HAT3Y]


def hats_em_ordem(eixos):
    """Número do hat (0, 1...) de cada par ABS_HATnX/ABS_HATnY presente."""
    pares = []
    for base in range(ABS_HAT0X, ABS_HAT3Y + 1, 2):
        if eixos >> base & 1 or eixos >> (base + 1) & 1:
            pares.append(base)
    return pares


def sdl_guid(dispositivo):
    """GUID do SDL2 (sem o CRC do nome, que o SDL aceita como curinga)."""
    def le16(hexa):
        valor = int(hexa, 16)
        return f"{valor & 0xFF:02x}{valor >> 8 & 0xFF:02x}"
    return (le16(dispositivo["bus"]) + "0000" + le16(dispositivo["vendor"]) + "0000"
            + le16(dispositivo["product"]) + "0000" + le16(dispositivo["version"]) + "0000")


# --------------------------------------------------------------- tokens → índices

def token_valido(token):
    return isinstance(token, str) and TOKEN.match(token) is not None


def _parse(token):
    m = TOKEN.match(token)
    if m.group(1) is not None:
        return ("k", int(m.group(1)), 0)
    return ("a", int(m.group(2)), int(m.group(3)))


def _resolver(dispositivo, token):
    """("botao", i) | ("hat", h, mascara) | ("eixo", i, sinal) | None."""
    if not token_valido(token):
        return None
    tipo, codigo, sinal = _parse(token)
    if tipo == "k":
        ordem = botoes_em_ordem(dispositivo["teclas"])
        return ("botao", ordem.index(codigo)) if codigo in ordem else None
    if ABS_HAT0X <= codigo <= ABS_HAT3Y:
        base = codigo - (codigo - ABS_HAT0X) % 2
        hats = hats_em_ordem(dispositivo["eixos"])
        if base not in hats:
            return None
        vertical = codigo != base
        mascara = (4 if sinal > 0 else 1) if vertical else (2 if sinal > 0 else 8)
        return ("hat", hats.index(base), mascara)
    ordem = eixos_em_ordem(dispositivo["eixos"])
    return ("eixo", ordem.index(codigo), sinal) if codigo in ordem else None


def _hat_nome(mascara):
    return {1: "up", 2: "right", 4: "down", 8: "left"}[mascara]


# ------------------------------------------------------------------- geradores

SDL_NOMES = {"a": "a", "b": "b", "x": "x", "y": "y", "l1": "leftshoulder",
             "r1": "rightshoulder", "l2": "lefttrigger", "r2": "righttrigger",
             "select": "back", "start": "start", "up": "dpup", "down": "dpdown",
             "left": "dpleft", "right": "dpright", "lx": "leftx", "ly": "lefty",
             "rx": "rightx", "ry": "righty"}


def linha_sdl(dispositivo, mapa):
    partes = [sdl_guid(dispositivo), re.sub(r"[,\s]+", " ", dispositivo["nome"]).strip() or "Controle"]
    for nome in NOMES_BOTOES:
        alvo = _resolver(dispositivo, mapa.get(nome, ""))
        if alvo is None:
            continue
        if alvo[0] == "botao":
            valor = f"b{alvo[1]}"
        elif alvo[0] == "hat":
            valor = f"h{alvo[1]}.{alvo[2]}"
        elif nome in EIXOS_ANALOGICOS:
            valor = f"a{alvo[1]}" + ("~" if alvo[2] < 0 else "")
        else:
            valor = ("+" if alvo[2] > 0 else "-") + f"a{alvo[1]}"
        partes.append(f"{SDL_NOMES[nome]}:{valor}")
    partes.append("platform:Linux")
    return ",".join(partes) + ","


# RetroArch (layout do SNES): b = de baixo, a = da direita, y = da esquerda, x = de cima.
RETROARCH_NOMES = {"a": "b", "b": "a", "x": "y", "y": "x", "l1": "l", "r1": "r",
                   "l2": "l2", "r2": "r2", "select": "select", "start": "start",
                   "up": "up", "down": "down", "left": "left", "right": "right"}
RETROARCH_ANALOGICOS = {"lx": "l_x", "ly": "l_y", "rx": "r_x", "ry": "r_y"}


def perfil_retroarch(dispositivo, mapa):
    linhas = [
        "# Gerado pelo Beni Launcher (área dos pais → Controles). Não edite à mão.",
        'input_driver = "udev"',
        f'input_device = "{dispositivo["nome"]}"',
        f'input_vendor_id = "{int(dispositivo["vendor"], 16)}"',
        f'input_product_id = "{int(dispositivo["product"], 16)}"',
    ]
    for nome, ra in RETROARCH_NOMES.items():
        alvo = _resolver(dispositivo, mapa.get(nome, ""))
        if alvo is None:
            continue
        if alvo[0] == "botao":
            linhas.append(f'input_{ra}_btn = "{alvo[1]}"')
        elif alvo[0] == "hat":
            linhas.append(f'input_{ra}_btn = "h{alvo[1]}{_hat_nome(alvo[2])}"')
        else:
            linhas.append(f'input_{ra}_axis = "{"+" if alvo[2] > 0 else "-"}{alvo[1]}"')
    for nome, ra in RETROARCH_ANALOGICOS.items():
        alvo = _resolver(dispositivo, mapa.get(nome, ""))
        if alvo is None or alvo[0] != "eixo":
            continue
        mais, menos = ("+", "-") if alvo[2] > 0 else ("-", "+")
        linhas.append(f'input_{ra}_plus_axis = "{mais}{alvo[1]}"')
        linhas.append(f'input_{ra}_minus_axis = "{menos}{alvo[1]}"')
    return "\n".join(linhas) + "\n"


# DFInput (PCSX): Nome=Tecla,TipoJoy,Valor. TipoJoy: 0 nada, 1 eixo, 2 hat, 3 botão.
DFINPUT_ORDEM = ("Select", "L3", "R3", "Analog", "Start", "Up", "Right", "Down", "Left",
                 "L2", "R2", "L1", "R1", "Triangle", "Circle", "Cross", "Square",
                 "LeftAnalogXP", "LeftAnalogXM", "LeftAnalogYP", "LeftAnalogYM",
                 "RightAnalogXP", "RightAnalogXM", "RightAnalogYP", "RightAnalogYM")
DFINPUT_NOMES = {"Select": "select", "Start": "start", "Up": "up", "Right": "right",
                 "Down": "down", "Left": "left", "L2": "l2", "R2": "r2", "L1": "l1",
                 "R1": "r1", "Triangle": "y", "Circle": "b", "Cross": "a", "Square": "x"}
# teclado do jogador 1 (padrão do DFInput; X keysyms)
DFINPUT_TECLADO = {"Select": 99, "Start": 118, "Up": 65362, "Right": 65363, "Down": 65364,
                   "Left": 65361, "L2": 101, "R2": 116, "L1": 119, "R1": 114,
                   "Triangle": 100, "Circle": 120, "Cross": 122, "Square": 115, "Analog": 98}
# joystick sem mapeamento: o padrão do próprio DFInput
DFINPUT_PADRAO = {"Select": (3, 8), "Start": (3, 9), "Up": (1, -2), "Right": (1, 1),
                  "Down": (1, 2), "Left": (1, -1), "L2": (3, 4), "R2": (3, 5),
                  "L1": (3, 6), "R1": (3, 7), "Triangle": (3, 0), "Circle": (3, 1),
                  "Cross": (3, 2), "Square": (3, 3)}


def _dfinput_joy(dispositivo, mapa, nome_df):
    if mapa is None:
        return DFINPUT_PADRAO.get(nome_df, (0, 0))
    nome = DFINPUT_NOMES.get(nome_df)
    alvo = _resolver(dispositivo, mapa.get(nome, "")) if nome else None
    if alvo is None:
        return (0, 0)
    if alvo[0] == "botao":
        return (3, alvo[1])
    if alvo[0] == "hat":
        return (2, (alvo[1] << 8) | alvo[2])
    return (1, (alvo[1] + 1) * alvo[2])


def config_dfinput(jogadores):
    """jogadores: até 2 tuplas (indice_sdl, dispositivo, mapa_ou_None)."""
    linhas = ["[CONFIG]", "Threaded=1", "HideCursor=0", "PreventScrSaver=0", ""]
    for numero in range(2):
        jogador = jogadores[numero] if numero < len(jogadores) else None
        indice, dispositivo, mapa = jogador if jogador else (numero, None, None)
        linhas += [f"[PAD{numero + 1}]", f"DevNum={indice}", "Type=4",
                   "VisualVibration=0", "PhysicalVibration=0"]
        for nome_df in DFINPUT_ORDEM:
            tecla = DFINPUT_TECLADO.get(nome_df, 0) if numero == 0 else 0
            tipo, valor = _dfinput_joy(dispositivo, mapa, nome_df)
            linhas.append(f"{nome_df}={tecla},{tipo},{valor}")
        linhas.append("")
    linhas += ["[EMU]", "EmuDev=0"]
    for nome in ("EMU_SAVESTATE", "EMU_LOADSTATE", "EMU_INCREMENTSTATE",
                 "EMU_FASTFORWARDS", "EMU_SCREENSHOT", "EMU_ESCAPE"):
        linhas.append(f"{nome}=0,0,0")
    return "\n".join(linhas) + "\n"


# Chromium (jogos de navegador): numeração crua do joydev. Botões na mesma ordem do
# SDL; eixos = todos os ABS em ordem de código, inclusive os do direcional "hat".
ABS_MAX = 0x3F


def mapa_navegador(dispositivo, mapa):
    """Tabela lida por beni/chromium/controle/controle.js para montar o controle padrão."""
    botoes_ordem = botoes_em_ordem(dispositivo["teclas"])
    eixos_ordem = [c for c in range(ABS_MAX + 1) if dispositivo["eixos"] >> c & 1]
    botoes, eixos = {}, {}
    for nome in NOMES_BOTOES:
        token = mapa.get(nome, "")
        if not token_valido(token):
            continue
        tipo, codigo, sinal = _parse(token)
        if tipo == "k":
            if codigo in botoes_ordem:
                botoes[nome] = ["b", botoes_ordem.index(codigo)]
        elif codigo in eixos_ordem:
            if nome in EIXOS_ANALOGICOS:
                eixos[nome] = [eixos_ordem.index(codigo), sinal]
            else:
                botoes[nome] = ["e", eixos_ordem.index(codigo), sinal]
    return {"botoes": botoes, "eixos": eixos}


def script_navegador(dispositivos, mapas):
    tabela = {}
    for dispositivo in dispositivos:
        mapa = (mapas.get(dispositivo["chave"]) or {}).get("mapa")
        if mapa and dispositivo["chave"] not in tabela:
            tabela[dispositivo["chave"]] = mapa_navegador(dispositivo, mapa)
    return ("// Gerado pelo Beni Launcher (área dos pais → Controles). Não edite à mão.\n"
            "window.__beniControles = " + json.dumps(tabela, sort_keys=True) + ";\n")


# --------------------------------------------------------------- armazenamento

_cache_carregar = {}
_trava_cache = threading.Lock()


def _ler_json(caminho):
    """Lê o JSON só quando o arquivo muda (a thread dos controles consulta muito)."""
    try:
        info = os.stat(caminho)
    except OSError:
        return {}
    chave = (info.st_mtime_ns, info.st_size, info.st_ino)
    with _trava_cache:
        guardado = _cache_carregar.get(caminho)
        if guardado and guardado[0] == chave:
            return copy.deepcopy(guardado[1])
    try:
        with open(caminho, encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
    except (OSError, ValueError):
        return {}
    with _trava_cache:
        _cache_carregar[caminho] = (chave, dados)
    return copy.deepcopy(dados)


def carregar(caminho):
    dados = _ler_json(caminho)
    if not isinstance(dados, dict):
        dados = {}
    controles = dados.get("controles")
    dados["controles"] = controles if isinstance(controles, dict) else {}
    dados["navegarMenu"] = dados.get("navegarMenu") is not False
    return dados


def _gravar(caminho, texto):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    temporario = caminho + ".tmp"
    with open(temporario, "w", encoding="utf-8") as arquivo:
        arquivo.write(texto)
    os.replace(temporario, caminho)


def validar_mapa(mapa):
    if not isinstance(mapa, dict):
        raise ValueError("mapping must be an object")
    limpo = {}
    for nome, token in mapa.items():
        if nome not in NOMES_BOTOES:
            raise ValueError(f"unknown button {nome!r}")
        if token in (None, ""):
            continue
        if not token_valido(token):
            raise ValueError(f"invalid input {token!r}")
        limpo[nome] = token
    faltando = [nome for nome in OBRIGATORIOS if nome not in limpo]
    if faltando:
        raise ValueError("missing buttons: " + ", ".join(faltando))
    return limpo


# ------------------------------------------------------------------- serviço

def _eviocgabs(codigo):
    # _IOR('E', 0x40 + codigo, struct input_absinfo) — 6 inteiros de 32 bits
    return (2 << 30) | (24 << 16) | (ord("E") << 8) | (0x40 + codigo)


class Controles:
    """Lê os controles numa thread; serve a captura e a navegação do menu."""

    def __init__(self, arquivo, casa=None, pode_navegar=None, ao_mudar_dispositivos=None,
                 ao_sair=None):
        self.arquivo = arquivo
        self.casa = casa or os.path.expanduser("~")
        self.pode_navegar = pode_navegar or (lambda: False)
        self.trava = threading.Lock()
        self.dispositivos = []
        self.abertos = {}        # evento -> (fd, dispositivo, faixas, estado)
        self.captura_ate = 0.0
        self.captura = None      # {"chave", "evento", "token", "seq"}
        self.seq = 0
        self.thread = None
        self.parar = threading.Event()
        self.ao_mudar_dispositivos = ao_mudar_dispositivos
        # ao_sair(): fecha o app aberto (Start + Select seguros); chamado 1 vez por aperto
        self.ao_sair = ao_sair
        self.segurados = {}       # evento -> códigos de botão apertados agora
        self.combo_desde = {}     # evento -> monotonic em que Start+Select começaram
        self.combo_disparado = set()

    # -- configuração gerada

    def caminhos(self):
        return {
            "retroarch": os.path.join(self.casa, ".config", "cozy-jogos", "autoconfig"),
            "dfinput": os.path.join(self.casa, ".pcsxr", "plugins", "dfinput.cfg"),
            # extensão do Chromium dos jogos (instalada pelo instalar.sh)
            "navegador": os.path.join(self.casa, ".var", "app", "org.chromium.Chromium",
                                      "cozy-controle", "mapa.js"),
        }

    def aplicar(self, dispositivos=None, forcar=False):
        """Gera as configs dos jogos e atualiza SDL_GAMECONTROLLERCONFIG.

        Sem nenhum controle configurado, não mexe num dfinput.cfg que já exista
        (pode ter sido feito à mão no PCSX)."""
        dados = carregar(self.arquivo)
        if dispositivos is None:
            dispositivos = listar_dispositivos()
        mapas = dados["controles"]
        linhas_sdl = []
        vistos = set()
        for dispositivo in dispositivos:
            mapa = (mapas.get(dispositivo["chave"]) or {}).get("mapa")
            if mapa and dispositivo["chave"] not in vistos:
                vistos.add(dispositivo["chave"])
                linhas_sdl.append(linha_sdl(dispositivo, mapa))
        if linhas_sdl:
            os.environ["SDL_GAMECONTROLLERCONFIG"] = "\n".join(linhas_sdl)
        else:
            os.environ.pop("SDL_GAMECONTROLLERCONFIG", None)
        caminhos = self.caminhos()
        pasta_ra = caminhos["retroarch"]
        os.makedirs(pasta_ra, exist_ok=True)
        desejados = {}
        for dispositivo in dispositivos:
            mapa = (mapas.get(dispositivo["chave"]) or {}).get("mapa")
            if mapa:
                nome = "beni-" + dispositivo["chave"].replace(":", "-") + ".cfg"
                desejados[nome] = perfil_retroarch(dispositivo, mapa)
        for nome in os.listdir(pasta_ra):
            if nome.startswith("beni-") and nome not in desejados:
                os.remove(os.path.join(pasta_ra, nome))
        for nome, texto in desejados.items():
            _gravar(os.path.join(pasta_ra, nome), texto)
        jogadores = [(indice, d, (mapas.get(d["chave"]) or {}).get("mapa"))
                     for indice, d in enumerate(dispositivos)][:2]
        if mapas or forcar or not os.path.exists(caminhos["dfinput"]):
            _gravar(caminhos["dfinput"], config_dfinput(jogadores))
        if os.path.isdir(os.path.dirname(caminhos["navegador"])):
            _gravar(caminhos["navegador"], script_navegador(dispositivos, mapas))

    def salvar(self, chave, nome, mapa):
        if not CHAVE_CONTROLE.match(chave or ""):
            raise ValueError("invalid controller id")
        mapa = validar_mapa(mapa)
        with self.trava:
            dados = carregar(self.arquivo)
            dados["controles"][chave] = {"nome": str(nome or "Controle")[:120], "mapa": mapa}
            _gravar(self.arquivo, json.dumps(dados, ensure_ascii=False, indent=2))
        self.aplicar()

    def esquecer(self, chave):
        with self.trava:
            dados = carregar(self.arquivo)
            dados["controles"].pop(chave, None)
            _gravar(self.arquivo, json.dumps(dados, ensure_ascii=False, indent=2))
        self.aplicar(forcar=True)

    def definir_navegacao(self, ligada):
        with self.trava:
            dados = carregar(self.arquivo)
            dados["navegarMenu"] = bool(ligada)
            _gravar(self.arquivo, json.dumps(dados, ensure_ascii=False, indent=2))

    def estado(self):
        dados = carregar(self.arquivo)
        with self.trava:
            dispositivos = list(self.dispositivos) if self.thread else listar_dispositivos()
        lista = []
        for jogador, d in enumerate(dispositivos, start=1):
            salvo = dados["controles"].get(d["chave"]) or {}
            lista.append({"chave": d["chave"], "nome": d["nome"], "evento": d["evento"],
                          "jogador": jogador, "mapa": salvo.get("mapa") or None})
        return {"navegarMenu": dados["navegarMenu"], "dispositivos": lista,
                "botoes": [{"id": n, "texto": t, "obrigatorio": o} for n, t, o in BOTOES]}

    # -- captura (assistente da área dos pais)

    def iniciar_captura(self, segundos=60):
        with self.trava:
            self.captura_ate = time.monotonic() + segundos
            self.captura = None
        self.garantir_thread()

    def ultima_captura(self, depois_de=0):
        with self.trava:
            if self.captura_ate:
                self.captura_ate = max(self.captura_ate, time.monotonic() + 30)
            if self.captura and self.captura["seq"] > depois_de:
                return dict(self.captura)
            return None

    def parar_captura(self):
        with self.trava:
            self.captura_ate = 0.0
            self.captura = None

    def capturando(self):
        return self.captura_ate > time.monotonic()

    # -- leitura

    def garantir_thread(self):
        if self.thread is None or not self.thread.is_alive():
            self.parar.clear()
            self.thread = threading.Thread(target=self._loop, name="controles", daemon=True)
            self.thread.start()

    def encerrar(self):
        self.parar.set()

    def _sincronizar(self):
        atuais = listar_dispositivos()
        mudou = [d["evento"] for d in atuais] != [d["evento"] for d in self.dispositivos]
        for evento in list(self.abertos):
            if evento not in {d["evento"] for d in atuais}:
                os.close(self.abertos.pop(evento)[0])
        for d in atuais:
            if d["evento"] in self.abertos:
                continue
            try:
                fd = os.open(os.path.join(DEV_INPUT, d["evento"]), os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            faixas = {}
            for codigo in range(ABS_MISC):
                if d["eixos"] >> codigo & 1:
                    try:
                        buf = fcntl.ioctl(fd, _eviocgabs(codigo), bytes(24))
                        _valor, minimo, maximo = struct.unpack("6i", buf)[:3]
                        faixas[codigo] = (minimo, maximo)
                    except OSError:
                        pass
            self.abertos[d["evento"]] = (fd, d, faixas, {})
        with self.trava:
            self.dispositivos = atuais
        if mudou:
            try:
                self.aplicar(atuais)
            except OSError:
                pass

    def _loop(self):
        proxima_busca = 0.0
        util_ate = 0.0  # até quando houve evento útil (botão/direcional) recente
        while not self.parar.is_set():
            agora = time.monotonic()
            if agora >= proxima_busca:
                self._sincronizar()
                proxima_busca = agora + 2
            fds = {v[0]: k for k, v in self.abertos.items()}
            if not fds:
                self.parar.wait(2)
                continue
            try:
                prontos, _, _ = select.select(list(fds), [], [], 0.25)
            except (OSError, ValueError):
                proxima_busca = 0
                continue
            for fd in prontos:
                evento = fds[fd]
                try:
                    dados = os.read(fd, EVENT_SIZE * 64)
                except OSError:
                    os.close(fd)
                    self.abertos.pop(evento, None)
                    continue
                _fd, dispositivo, faixas, estado = self.abertos.get(evento, (fd, None, {}, {}))
                for i in range(0, len(dados) - EVENT_SIZE + 1, EVENT_SIZE):
                    _s, _us, tipo, codigo, valor = struct.unpack(EVENT_FORMAT, dados[i:i + EVENT_SIZE])
                    if tipo == EV_KEY and valor in (0, 1):
                        apertados = self.segurados.setdefault(evento, set())
                        (apertados.add if valor else apertados.discard)(codigo)
                        util_ate = time.monotonic() + 3
                    token = self._token(tipo, codigo, valor, faixas, estado)
                    if token:
                        util_ate = time.monotonic() + 3
                        self._acionado(dispositivo, token)
            agora = time.monotonic()
            self._verificar_saida(agora)
            if prontos and agora > util_ate:
                # Só ruído (ex.: eixo solto de controle barato mandando dezenas de
                # eventos por segundo): junta os eventos em vez de acordar a cada um.
                self.parar.wait(0.1)

    def _verificar_saida(self, agora, dados=None):
        """Start + Select seguros por SEGURAR_PARA_SAIR_S fecham o app aberto."""
        if self.ao_sair is None or self.capturando():
            return
        if not any(len(apertados) >= 2 for apertados in self.segurados.values()):
            # ninguém segurando dois botões: não há Start + Select em andamento
            # (evita ler o controles.json a cada evento dos analógicos)
            self.combo_desde.clear()
            self.combo_disparado.clear()
            return
        dados = dados or carregar(self.arquivo)
        for evento, (_fd, dispositivo, _f, _e) in list(self.abertos.items()):
            mapa = (dados["controles"].get(dispositivo["chave"]) or {}).get("mapa") or {}
            alvos = [mapa.get("start", ""), mapa.get("select", "")]
            if not all(t.startswith("k:") for t in alvos):
                continue
            apertados = self.segurados.get(evento, set())
            if all(int(t[2:]) in apertados for t in alvos):
                inicio = self.combo_desde.setdefault(evento, agora)
                if agora - inicio >= SEGURAR_PARA_SAIR_S and evento not in self.combo_disparado:
                    self.combo_disparado.add(evento)
                    try:
                        self.ao_sair()
                    except Exception:  # noqa: BLE001
                        pass
            else:
                self.combo_desde.pop(evento, None)
                self.combo_disparado.discard(evento)

    @staticmethod
    def _token(tipo, codigo, valor, faixas, estado):
        if tipo == EV_KEY and valor == 1:
            return f"k:{codigo}"
        if tipo != EV_ABS:
            return None
        minimo, maximo = faixas.get(codigo, (-1, 1))
        centro = (minimo + maximo) / 2
        meia = max((maximo - minimo) / 2, 1)
        posicao = (valor - centro) / meia
        lado = 1 if posicao > 0.6 else (-1 if posicao < -0.6 else 0)
        if abs(posicao) < 0.3:
            estado[codigo] = 0
            return None
        if lado and estado.get(codigo, 0) != lado:
            estado[codigo] = lado
            return f"a:{codigo}:{lado}"
        return None

    def _acionado(self, dispositivo, token):
        if dispositivo is None:
            return
        with self.trava:
            if self.captura_ate > time.monotonic():
                self.seq += 1
                self.captura = {"chave": dispositivo["chave"], "evento": dispositivo["evento"],
                                "nome": dispositivo["nome"], "token": token, "seq": self.seq}
                return
        dados = carregar(self.arquivo)
        if not dados["navegarMenu"]:
            return
        mapa = (dados["controles"].get(dispositivo["chave"]) or {}).get("mapa") or mapa_basico(dispositivo)
        acao = next((nome for nome, t in mapa.items() if t == token and nome in TECLAS_MENU), None)
        if acao and self.pode_navegar():
            enviar_tecla(TECLAS_MENU[acao])


def mapa_basico(dispositivo):
    """Sem mapeamento salvo: só o direcional (hat ou eixos X/Y); os botões variam demais."""
    mapa = {}
    if dispositivo["eixos"] >> ABS_HAT0X & 1:
        mapa.update(up="a:17:-1", down="a:17:1", left="a:16:-1", right="a:16:1")
    else:
        mapa.update(up="a:1:-1", down="a:1:1", left="a:0:-1", right="a:0:1")
    return mapa


def enviar_tecla(tecla):
    if not shutil.which("xdotool"):
        return
    try:
        subprocess.run(["xdotool", "key", "--clearmodifiers", tecla], timeout=3,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def janela_ativa_pid():
    if not shutil.which("xdotool"):
        return None
    try:
        saida = subprocess.run(["xdotool", "getactivewindow", "getwindowpid"], timeout=3,
                               stdin=subprocess.DEVNULL, capture_output=True, text=True)
        return int(saida.stdout.strip()) if saida.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
