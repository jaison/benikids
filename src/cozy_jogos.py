#!/usr/bin/env python3
"""Lista de Super Nintendo e PlayStation no Windows (o cozy-jogos do Linux).

Abre os jogos de %USERPROFILE%\\Jogos\\SNES ou \\PS1 com capa, se houver uma
imagem com o mesmo nome. O RetroArch sobe sem menu, em tela cheia sem trocar
a resolução, e o Esc sai. Não há ROM nem BIOS neste repositório: a lista mostra
o que estiver na pasta. A BIOS do PlayStation, se a família tiver uma cópia,
fica em Jogos\\PS1\\BIOS (senão o núcleo usa a BIOS simulada).

Uso: cozy_jogos.py snes|ps1 <caminho do retroarch.exe>
"""

import hashlib
import hmac
import io
import os
import queue
import re
import sys
import threading
import time

JOGOS_NOME = "Jogos"
CFG_NOME = os.path.join("Benikids", "cozy-jogos")
# pcsx_rearmed é o núcleo leve (o mesmo tipo de máquina do Linux: Celeron e
# Intel HD). O swanstation é mais fiel e mais pesado. Os dois vêm do pacote
# estável gravado no catálogo, com sha256 — a pasta stable não publica o zip
# de cada núcleo, só o RetroArch_cores.7z.
TETO_PACOTE = 300 * 1024 * 1024
TETO_EXTRATOR = 2 * 1024 * 1024

SISTEMAS = {
    "snes": {
        "titulo": "Super Nintendo",
        "pasta": "SNES",
        "exts": (".sfc", ".smc", ".swc", ".fig", ".bs", ".zip"),
        "cor": "#7b5cd6",
    },
    "ps1": {
        "titulo": "PlayStation",
        "pasta": "PS1",
        "exts": (".cue", ".iso", ".img", ".mdf", ".pbp", ".bin"),
        "cor": "#2f7fd8",
    },
}
IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")

LEIA_ME = """\
JOGOS DE SUPER NINTENDO E PLAYSTATION (Benikids)
================================================

Onde colocar os jogos (use as suas cópias):
  Super Nintendo:  Jogos\\SNES   (arquivos .sfc, .smc ou .zip)
  PlayStation:     Jogos\\PS1    (de preferência .cue + .bin; também .iso, .pbp)

Capas (opcional): uma imagem com o MESMO nome do jogo, na mesma pasta.
  Exemplo: "Super Mario World.sfc" e "Super Mario World.png"

BIOS do PlayStation (opcional): o arquivo em Jogos\\PS1\\BIOS, com um destes
nomes: scph1001.bin, scph5501.bin, scph7001.bin ou scph5502.bin.
Sem BIOS, o emulador usa uma BIOS simulada: vários jogos funcionam, alguns não.

Para sair do jogo: tecla Esc, ou Start+Select no controle.
Saves: Jogos\\.saves
"""


def pasta_jogos(home=None):
    home = home or os.environ.get("USERPROFILE") or os.path.expanduser("~")
    return os.path.join(home, JOGOS_NOME)


def pasta_config(appdata=None):
    appdata = appdata if appdata is not None else os.environ.get("APPDATA")
    if not appdata:
        appdata = os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    return os.path.join(appdata, CFG_NOME)


def nome_bonito(caminho):
    nome = os.path.splitext(os.path.basename(caminho))[0]
    nome = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", nome)
    nome = nome.replace("_", " ").strip()
    return nome or os.path.basename(caminho)


def listar_jogos(sistema, raiz_jogos):
    info = SISTEMAS[sistema]
    pasta = os.path.join(raiz_jogos, info["pasta"])
    arquivos = []
    for raiz, dirs, nomes in os.walk(pasta):
        dirs[:] = [d for d in dirs if d.upper() != "BIOS" and not d.startswith(".")]
        for n in nomes:
            if n.lower().endswith(info["exts"]):
                arquivos.append(os.path.join(raiz, n))
    if sistema == "ps1":
        usados = set()
        for f in arquivos:
            if f.lower().endswith(".cue"):
                try:
                    with open(f, "r", errors="ignore") as h:
                        for linha in h:
                            m = re.match(r'\s*FILE\s+"?(.+?)"?\s+\S+\s*$', linha, re.I)
                            if m:
                                usados.add(os.path.normcase(os.path.normpath(
                                    os.path.join(os.path.dirname(f), m.group(1)))))
                except OSError:
                    pass
        arquivos = [f for f in arquivos
                    if not (f.lower().endswith(".bin")
                            and os.path.normcase(os.path.normpath(f)) in usados)]
    jogos = [(nome_bonito(f), f) for f in arquivos]
    jogos.sort(key=lambda j: j[0].lower())
    return jogos


def achar_capa(rom):
    base = os.path.splitext(rom)[0]
    pasta = os.path.dirname(rom)
    nome = os.path.basename(base)
    candidatos = [base + e for e in IMG_EXTS]
    for sub in ("capas", "Capas"):
        candidatos += [os.path.join(pasta, sub, nome + e) for e in IMG_EXTS]
    for c in candidatos:
        if os.path.isfile(c):
            return c
    return None


def log_nucleo(texto, arquivo=None):
    """Uma linha no beni-windows.log. O hash que não confere fica registrado aqui."""
    caminho = arquivo or os.path.join(
        os.path.expanduser("~"), ".cache", "cozy-kids-launcher", "beni-windows.log")
    try:
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        with open(caminho, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + texto + "\n")
    except OSError:
        pass


def info_nucleos():
    import catalogo_windows

    return catalogo_windows.nucleos_retroarch()


def _sha256(caminho):
    soma = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            soma.update(bloco)
    return soma.hexdigest()


def hash_confere(caminho, esperado):
    if not isinstance(esperado, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", esperado):
        return False
    try:
        return hmac.compare_digest(_sha256(caminho), esperado.lower())
    except OSError:
        return False


def nucleo_de(sistema, info):
    """(arquivo.dll, sha256) do catálogo, ou ("", "") se faltar ou o nome for caminho."""
    item = info.get(sistema) if isinstance(info, dict) else None
    if not isinstance(item, dict):
        return "", ""
    nome, sha = item.get("arquivo") or "", item.get("sha256") or ""
    if not isinstance(nome, str) or not nome or "/" in nome or "\\" in nome or nome.startswith("."):
        return "", ""
    return nome, sha


def baixar_conferindo(url, destino, sha256, abrir, teto, rotulo, log):
    """Grava `destino` só se o sha256 bater. Devolve False e apaga o parcial se não bater."""
    if not isinstance(url, str) or not url.startswith("https://"):
        log(f"núcleo do RetroArch: sem endereço ({rotulo}); não instalei")
        return False
    if os.path.isfile(destino) and hash_confere(destino, sha256):
        return True
    abrir = abrir or _abrir_url
    temporario = destino + ".baixando"
    soma = hashlib.sha256()
    tamanho = 0
    try:
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        with abrir(url) as resposta, open(temporario, "wb") as f:
            while True:
                bloco = resposta.read(1024 * 1024)
                if not bloco:
                    break
                tamanho += len(bloco)
                if tamanho > teto:
                    raise ValueError("grande")
                soma.update(bloco)
                f.write(bloco)
        if not re.fullmatch(r"[0-9a-fA-F]{64}", sha256 or "") or not hmac.compare_digest(
                soma.hexdigest(), sha256.lower()):
            log(f"núcleo do RetroArch: hash não confere ({rotulo}); não instalei")
            return False
        os.replace(temporario, destino)
        return True
    except (OSError, ValueError) as erro:
        log(f"núcleo do RetroArch: não deu para baixar {rotulo} ({erro.__class__.__name__})")
        return False
    finally:
        if os.path.isfile(temporario):
            try:
                os.remove(temporario)
            except OSError:
                pass


def extrair_com_7zr(pacote, pasta_saida, nomes, extrator):
    """Tira só os .dll pedidos. O 7zr já foi conferido pelo hash."""
    import subprocess

    os.makedirs(pasta_saida, exist_ok=True)
    # -r: no pacote estável a DLL fica em RetroArch-Win64/cores/, e o "e" tira a pasta.
    argv = [extrator, "e", "-y", "-r", "-bso0", "-bsp0", "-o" + pasta_saida, pacote, *nomes]
    kwargs = {"capture_output": True, "timeout": 900}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000
    try:
        proc = subprocess.run(argv, **kwargs)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _limpar_pasta(caminho):
    import shutil

    shutil.rmtree(caminho, ignore_errors=True)


def baixar_core(sistema, pasta, abrir=None, extrair=None, log=None, info=None):
    """Grava a DLL se o sha256 do pacote e o da DLL baterem. Senão não instala e loga."""
    log = log or log_nucleo
    info = info_nucleos() if info is None else info
    nome, sha_dll = nucleo_de(sistema, info)
    if not nome:
        log("núcleo do RetroArch: o catálogo não tem este núcleo; não instalei")
        return ""
    try:
        os.makedirs(pasta, exist_ok=True)
    except OSError:
        return ""
    destino = os.path.join(pasta, nome)
    if os.path.isfile(destino) and hash_confere(destino, sha_dll):
        return destino
    if os.path.isfile(destino):
        try:
            os.remove(destino)
        except OSError:
            return ""
    url, sha_pacote = info.get("url"), info.get("sha256")
    pacote = os.path.join(pasta, "RetroArch_cores.7z")
    if not baixar_conferindo(url, pacote, sha_pacote, abrir, TETO_PACOTE, "pacote", log):
        return ""
    extrator_info = info.get("extrator") if isinstance(info.get("extrator"), dict) else {}
    extrator = os.path.join(pasta, extrator_info.get("arquivo") or "7zr.exe")
    if not baixar_conferindo(
            extrator_info.get("url"), extrator, extrator_info.get("sha256"),
            abrir, TETO_EXTRATOR, "extrator", log):
        return ""
    pedidos = []
    for sis in ("snes", "ps1"):
        nome_sis, sha_sis = nucleo_de(sis, info)
        if nome_sis and sha_sis:
            pedidos.append((nome_sis, sha_sis))
    if not pedidos:
        return ""
    saida = os.path.join(pasta, ".extraidos")
    _limpar_pasta(saida)
    try:
        os.makedirs(saida, exist_ok=True)
    except OSError:
        return ""
    try:
        ok = (extrair or extrair_com_7zr)(pacote, saida, [n for n, _ in pedidos], extrator)
    except (OSError, ValueError):
        ok = False
    if not ok:
        log("núcleo do RetroArch: não deu para extrair o pacote; não instalei")
        _limpar_pasta(saida)
        return ""
    for nome_sis, sha_sis in pedidos:
        origem = os.path.join(saida, nome_sis)
        final = os.path.join(pasta, nome_sis)
        if not hash_confere(origem, sha_sis):
            log(f"núcleo do RetroArch: hash não confere ({nome_sis}); não instalei")
            try:
                os.remove(origem)
            except OSError:
                pass
            continue
        try:
            os.replace(origem, final)
        except OSError:
            log(f"núcleo do RetroArch: não deu para gravar {nome_sis}; não instalei")
    _limpar_pasta(saida)
    # O .7z só sai do disco quando as duas DLLs conferiram. Se uma não bater,
    # ele fica para a próxima tentativa não baixar 220 MB de novo.
    if all(hash_confere(os.path.join(pasta, n), s) for n, s in pedidos):
        try:
            os.remove(pacote)
        except OSError:
            pass
    if hash_confere(destino, sha_dll):
        log(f"núcleo do RetroArch: instalei {nome} ({info.get('versao') or 'estável'})")
        return destino
    return ""


def _abrir_url(url):
    import urllib.request

    return urllib.request.urlopen(url, timeout=120)


def _aspas(caminho):
    return '"' + caminho.replace("\\", "/") + '"'


def texto_retroarch(sistema, raiz_jogos, cfg_dir):
    """retroarch.cfg do Linux, com áudio e controle do Windows e sem menu.

    O vídeo fica em gl, como beni/emuladores/retroarch.cfg. No RetroArch 1.22.2,
    se o d3d11 não cria o vídeo, o programa grava gl na cfg, mostra um erro e sai
    (video_driver_force_fallback): não segue na mesma abertura. Esta cfg é
    reescrita toda vez que a lista abre, então o gl gravado se perderia e um
    Intel HD antigo (sem DirectX 11) cairia nesse erro sempre.
    """
    saves = os.path.join(raiz_jogos, ".saves", sistema)
    sistema_bios = os.path.join(raiz_jogos, "PS1", "BIOS")
    autoconfig = os.path.join(cfg_dir, "autoconfig")
    return f"""config_save_on_exit = "false"
video_driver = "gl"
video_fullscreen = "true"
video_windowed_fullscreen = "true"
video_fullscreen_x = "0"
video_fullscreen_y = "0"
video_vsync = "true"
video_threaded = "true"
video_smooth = "false"
video_scale_integer = "false"
aspect_ratio_index = "0"
video_shader_enable = "false"
video_font_enable = "false"
video_disable_composition = "false"
suspend_screensaver_enable = "true"
pause_nonactive = "false"
audio_driver = "wasapi"
audio_enable = "true"
audio_latency = "96"
audio_sync = "true"
audio_resampler = "nearest"
audio_resampler_quality = "1"
menu_driver = "rgui"
kiosk_mode_enable = "true"
input_menu_toggle = "nul"
input_menu_toggle_btn = "nul"
input_menu_toggle_gamepad_combo = "0"
menu_show_online_updater = "false"
menu_show_core_updater = "false"
rgui_show_start_screen = "false"
notification_show_autoconfig = "false"
notification_show_remap_load = "false"
notification_show_config_override_load = "false"
notification_show_save_state = "false"
notification_show_fast_forward = "false"
menu_enable_widgets = "false"
quit_press_twice = "false"
input_exit_emulator = "escape"
input_quit_gamepad_combo = "4"
input_grab_mouse_toggle = "nul"
input_auto_mouse_grab = "false"
input_auto_game_focus = "0"
input_game_focus_toggle = "nul"
input_toggle_fullscreen = "nul"
input_pause_toggle = "nul"
input_frame_advance = "nul"
input_hold_fast_forward = "nul"
input_toggle_fast_forward = "nul"
input_hold_slowmotion = "nul"
input_toggle_slowmotion = "nul"
input_rewind = "nul"
input_reset = "nul"
input_shader_next = "nul"
input_shader_prev = "nul"
input_shader_toggle = "nul"
input_save_state = "nul"
input_load_state = "nul"
input_screenshot = "nul"
input_desktop_menu_toggle = "nul"
input_close_content = "nul"
input_driver = "dinput"
input_player1_up = "up"
input_player1_down = "down"
input_player1_left = "left"
input_player1_right = "right"
input_player1_a = "x"
input_player1_b = "z"
input_player1_x = "s"
input_player1_y = "a"
input_player1_l = "q"
input_player1_r = "w"
input_player1_start = "enter"
input_player1_select = "rshift"
joypad_driver = "xinput"
input_autodetect_enable = "true"
joypad_autoconfig_dir = {_aspas(autoconfig)}
input_player1_joypad_index = "0"
input_player1_analog_dpad_mode = "1"
input_player1_b_btn = "0"
input_player1_a_btn = "1"
input_player1_y_btn = "2"
input_player1_x_btn = "3"
input_player1_l_btn = "4"
input_player1_r_btn = "5"
input_player1_select_btn = "6"
input_player1_start_btn = "7"
input_player1_up_btn = "h0up"
input_player1_down_btn = "h0down"
input_player1_left_btn = "h0left"
input_player1_right_btn = "h0right"
savefile_directory = {_aspas(saves)}
savestate_directory = {_aspas(saves)}
sort_savefiles_enable = "false"
autosave_interval = "20"
savestate_auto_save = "false"
savestate_auto_load = "false"
rewind_enable = "false"
run_ahead_enabled = "false"
system_directory = {_aspas(sistema_bios)}
log_verbosity = "false"
"""


def garantir_opcao(texto, chave, valor):
    if re.search(r'(?m)^[ \t]*' + re.escape(chave) + r'[ \t]*=', texto or ""):
        return texto
    if texto and not texto.endswith("\n"):
        texto += "\n"
    return (texto or "") + f'{chave} = "{valor}"\n'


def preparar_pastas(sistema, home=None, appdata=None):
    """Pastas de ROM, o texto para os pais e a cfg. Sem baixar nada (não trava o clique)."""
    if sistema not in SISTEMAS:
        return ""
    raiz = pasta_jogos(home)
    cfg_dir = pasta_config(appdata)
    try:
        os.makedirs(os.path.join(raiz, "SNES"), exist_ok=True)
        os.makedirs(os.path.join(raiz, "PS1", "BIOS"), exist_ok=True)
        os.makedirs(os.path.join(raiz, ".saves", sistema), exist_ok=True)
        os.makedirs(os.path.join(cfg_dir, "autoconfig"), exist_ok=True)
        leia = os.path.join(raiz, "LEIA-ME.txt")
        if not os.path.exists(leia):
            with open(leia, "w", encoding="utf-8") as f:
                f.write(LEIA_ME)
        cfg = os.path.join(cfg_dir, "retroarch.cfg")
        with open(cfg, "w", encoding="utf-8", newline="\n") as f:
            f.write(texto_retroarch(sistema, raiz, cfg_dir))
        opcoes = os.path.join(cfg_dir, "retroarch-core-options.cfg")
        atual = ""
        if os.path.isfile(opcoes):
            with open(opcoes, encoding="utf-8", errors="surrogateescape") as f:
                atual = f.read()
        novo = garantir_opcao(atual, "pcsx_rearmed_bios", "auto")
        if novo != atual:
            with open(opcoes, "w", encoding="utf-8", newline="\n") as f:
                f.write(novo)
    except OSError:
        return ""
    return cfg_dir


def preparar(sistema, retroarch, home=None, appdata=None, abrir=None):
    """Pastas e a cfg, e o núcleo se ainda não está na máquina. Devolve a DLL ou ""."""
    cfg_dir = preparar_pastas(sistema, home, appdata)
    if not cfg_dir or not retroarch:
        return ""
    return baixar_core(sistema, os.path.join(cfg_dir, "cores"), abrir)


def _capa_tk(tk, caminho):
    if not caminho:
        return None
    try:
        from PIL import Image
        import base64
        img = Image.open(caminho)
        img.thumbnail((266, 220))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG")
        return tk.PhotoImage(data=base64.b64encode(buf.getvalue()))
    except Exception:
        try:
            return tk.PhotoImage(file=caminho)
        except Exception:
            return None


def comando_jogo(sistema, rom, retroarch, cfg, core):
    if sistema not in SISTEMAS or not retroarch or not cfg or not core or not os.path.isfile(core):
        return None
    return [retroarch, "-f", "-c", cfg, "-L", core, rom]


class Controles(threading.Thread):
    """XInput: direcional ou analógico esquerdo, e o botão A confirma."""

    def __init__(self, fila):
        super().__init__(daemon=True)
        self.fila = fila
        self.ativo = True

    def run(self):
        try:
            import ctypes
            from ctypes import wintypes
            xinput = ctypes.WinDLL("xinput1_4")
        except (OSError, AttributeError):
            try:
                import ctypes
                from ctypes import wintypes
                xinput = ctypes.WinDLL("xinput1_3")
            except (OSError, AttributeError):
                return

        class Pad(ctypes.Structure):
            _fields_ = [("wButtons", wintypes.WORD), ("bLeftTrigger", ctypes.c_ubyte),
                        ("bRightTrigger", ctypes.c_ubyte), ("sThumbLX", ctypes.c_short),
                        ("sThumbLY", ctypes.c_short), ("sThumbRX", ctypes.c_short),
                        ("sThumbRY", ctypes.c_short)]

        class State(ctypes.Structure):
            _fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", Pad)]

        antes = (0, 0, False)
        while self.ativo:
            estado = State()
            if xinput.XInputGetState(0, ctypes.byref(estado)) != 0:
                threading.Event().wait(1)
                antes = (0, 0, False)
                continue
            botao = estado.Gamepad.wButtons
            horizontal = vertical = 0
            if botao & 0x0004 or estado.Gamepad.sThumbLX < -16000:
                horizontal = -1
            elif botao & 0x0008 or estado.Gamepad.sThumbLX > 16000:
                horizontal = 1
            if botao & 0x0001 or estado.Gamepad.sThumbLY > 16000:
                vertical = -1
            elif botao & 0x0002 or estado.Gamepad.sThumbLY < -16000:
                vertical = 1
            agora = (horizontal, vertical, bool(botao & 0x1000))
            if self.ativo and agora[0] and agora[0] != antes[0]:
                self.fila.put("dir" if agora[0] > 0 else "esq")
            if self.ativo and agora[1] and agora[1] != antes[1]:
                self.fila.put("cima" if agora[1] < 0 else "baixo")
            if self.ativo and agora[2] and not antes[2]:
                self.fila.put("ok")
            antes = agora
            threading.Event().wait(0.08)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    sistema = (argv[0] if argv else "snes").lower()
    retroarch = argv[1] if len(argv) > 1 else ""
    if sistema not in SISTEMAS:
        print("uso: cozy_jogos.py snes|ps1 retroarch.exe", file=sys.stderr)
        return 2
    preparar_pastas(sistema)
    import tkinter as tk

    raiz = pasta_jogos()
    cfg_dir = pasta_config()
    info_n = info_nucleos()
    nome_core, sha_core = nucleo_de(sistema, info_n)
    pasta_cores = os.path.join(cfg_dir, "cores")
    ja_esta = bool(nome_core) and hash_confere(os.path.join(pasta_cores, nome_core), sha_core)
    # O pacote dos núcleos tem ~220 MB. A lista abre na hora e o download segue
    # atrás; o jogo só começa quando a DLL conferida está na pasta.
    aviso = ["" if ja_esta else "Baixando o emulador de jogos…"]

    def quando_baixar():
        caminho = baixar_core(sistema, pasta_cores, info=info_n)
        aviso[0] = "" if caminho else "Não consegui preparar o emulador. Tente de novo com internet."

    if retroarch and not ja_esta:
        threading.Thread(target=quando_baixar, daemon=True).start()
    info = SISTEMAS[sistema]
    jogos = listar_jogos(sistema, raiz)
    fonte = "Segoe UI" if os.name == "nt" else "DejaVu Sans"

    root = tk.Tk(className="cozy-jogos")
    root.title("Jogos - " + info["titulo"])
    root.configure(bg="#1b1f3b")
    root.attributes("-fullscreen", True)
    largura, altura = root.winfo_screenwidth(), root.winfo_screenheight()
    canvas = tk.Canvas(root, bg="#1b1f3b", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    fila = queue.Queue()
    controles = Controles(fila)
    if os.name == "nt":
        controles.start()
    sel = [0]
    proc = [None]
    capas = []

    def desenhar():
        nonlocal capas
        canvas.delete("all")
        capas = []
        canvas.create_text(largura // 2, 52, text=info["titulo"], fill="white",
                           font=(fonte, 34, "bold"))
        if not jogos:
            pasta = os.path.join(raiz, info["pasta"])
            canvas.create_text(largura // 2, altura // 2 - 20, text="Ainda não tem jogos aqui.",
                               fill="white", font=(fonte, 30, "bold"))
            canvas.create_text(largura // 2, altura // 2 + 40,
                               text=f"Peça para um adulto colocar os jogos na pasta {pasta}",
                               fill="#c8cdf5", font=(fonte, 18))
            return
        cols, card_w, card_h, gap, topo = 4, 290, 300, 26, 120
        total = cols * card_w + (cols - 1) * gap
        x0 = (largura - total) // 2
        for i, (nome, rom) in enumerate(jogos):
            lin, col = divmod(i, cols)
            x = x0 + col * (card_w + gap)
            y = topo + lin * (card_h + gap)
            tag = f"j{i}"
            canvas.create_rectangle(x, y, x + card_w, y + card_h, fill="#2a3060",
                                    outline="#2a3060", width=6, tags=(tag, f"borda{i}"))
            img = _capa_tk(tk, achar_capa(rom))
            if img is not None:
                capas.append(img)
                canvas.create_image(x + card_w // 2, y + 122, image=img, tags=tag)
            else:
                canvas.create_rectangle(x + 12, y + 12, x + card_w - 12, y + 232,
                                        fill=info["cor"], outline="", tags=tag)
            canvas.create_text(x + card_w // 2, y + card_h - 34, text=nome, fill="white",
                               width=card_w - 16, justify="center", font=(fonte, 14, "bold"), tags=tag)
            canvas.tag_bind(tag, "<Enter>", lambda e, k=i: selecionar(k))
            canvas.tag_bind(tag, "<Button-1>", lambda e, k=i: jogar(k))
        selecionar(sel[0])

    def selecionar(k):
        if not jogos:
            return
        k = max(0, min(len(jogos) - 1, k))
        canvas.itemconfigure(f"borda{sel[0]}", outline="#2a3060")
        sel[0] = k
        canvas.itemconfigure(f"borda{k}", outline="#ffd34d")

    def acao(a):
        if proc[0] is not None or not jogos:
            return
        if a == "esq":
            selecionar(sel[0] - 1)
        elif a == "dir":
            selecionar(sel[0] + 1)
        elif a == "cima":
            selecionar(sel[0] - 4)
        elif a == "baixo":
            selecionar(sel[0] + 4)
        elif a == "ok":
            jogar(sel[0])

    def jogar(k):
        import subprocess
        if proc[0] is not None:
            return
        selecionar(k)
        core = os.path.join(pasta_cores, nome_core) if nome_core else ""
        cfg = os.path.join(cfg_dir, "retroarch.cfg")
        cmd = comando_jogo(sistema, jogos[k][1], retroarch, cfg, core)
        if not cmd:
            canvas.create_text(largura // 2, altura - 36,
                               text="O emulador ainda não está pronto. Tente de novo com internet.",
                               fill="#ffd34d", font=(fonte, 16))
            return
        try:
            proc[0] = subprocess.Popen(cmd)
        except OSError:
            proc[0] = None
            return
        controles.ativo = False
        root.after(800, root.withdraw)
        root.after(1000, esperar)

    def esperar():
        if proc[0] is not None and proc[0].poll() is None:
            root.after(500, esperar)
            return
        proc[0] = None
        while not fila.empty():
            fila.get_nowait()
        root.deiconify()
        root.attributes("-fullscreen", True)
        root.after(400, lambda: setattr(controles, "ativo", True))

    def ler_fila():
        try:
            while True:
                acao(fila.get_nowait())
        except queue.Empty:
            pass
        root.after(80, ler_fila)

    for tecla, nome in (("<Left>", "esq"), ("<Right>", "dir"), ("<Up>", "cima"),
                        ("<Down>", "baixo"), ("<Return>", "ok"), ("<space>", "ok")):
        root.bind(tecla, lambda e, a=nome: acao(a))
    def pulsar_aviso():
        if aviso[0]:
            if canvas.find_withtag("aviso"):
                canvas.itemconfigure("aviso", text=aviso[0])
            else:
                canvas.create_text(largura // 2, altura - 36, text=aviso[0],
                                   fill="#ffd34d", font=(fonte, 16), tags="aviso")
        else:
            canvas.delete("aviso")
        root.after(400, pulsar_aviso)

    desenhar()
    root.after(100, ler_fila)
    root.after(400, pulsar_aviso)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
