"""Catálogo de apps do Windows (src/catalogo/windows.json).

Cada item é um app livre curado para crianças, instalado pelo winget e ligado por
padrão (os pais desligam na área dos pais). O tile guarda só "catalogo:<id>"; o
caminho do .exe é procurado na hora de abrir, porque muda com a versão e com o
tipo de instalação (por usuário ou para todos).
"""

import glob
import json
import os
import sys

ARQUIVO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalogo", "windows.json")
PREFIXO = "catalogo:"


def _ler(arquivo):
    try:
        with open(arquivo, encoding="utf-8") as f:
            dados = json.load(f)
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def carregar(arquivo=ARQUIVO):
    return [item for item in _ler(arquivo).get("apps", []) if isinstance(item, dict) and item.get("id")]


def nucleos_retroarch(arquivo=ARQUIVO):
    """Pacote estável dos núcleos do RetroArch: url, sha256, snes, ps1 e o extrator."""
    info = _ler(arquivo).get("retroarch_nucleos")
    return info if isinstance(info, dict) else {}


def raizes():
    vistas = []
    for nome, padrao in (
        ("ProgramFiles", r"C:\Program Files"),
        ("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ("LOCALAPPDATA", ""),
    ):
        raiz = os.environ.get(nome, padrao)
        if raiz and raiz not in vistas:
            vistas.append(raiz)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        vistas.append(os.path.join(local, "Programs"))
    return vistas


def localizar(item, bases=None, registro=None):
    """Caminho do .exe do app, ou None.

    Primeiro pelos padrões glob do catálogo (relativos às pastas de programas); se
    nenhum casar, pelo "Programas instalados" do Windows (chaves Uninstall), que
    sabe a pasta mesmo quando o instalador muda o nome dela entre versões.
    """
    for padrao in item.get("exe", []):
        for base in bases if bases is not None else raizes():
            achados = sorted(glob.glob(os.path.join(base, padrao), recursive=True), reverse=True)
            for caminho in achados:
                if os.path.isfile(caminho):
                    return caminho
    if item.get("registro"):
        entradas = registro if registro is not None else programas_instalados()
        return pelo_registro(item, entradas)
    return None


def nomes_do_exe(item):
    return {os.path.basename(p).lower() for p in item.get("exe", []) if "*" not in os.path.basename(p)}


def pelo_registro(item, entradas):
    """entradas: [(DisplayName, InstallLocation, DisplayIcon)]. Acha o exe do app nelas."""
    nome = item["registro"].lower()
    exes = nomes_do_exe(item)
    for exibido, pasta, icone in entradas:
        if nome not in (exibido or "").lower():
            continue
        icone = (icone or "").split(",")[0].strip().strip('"')
        if icone.lower().endswith(".exe") and os.path.basename(icone).lower() in exes and os.path.isfile(icone):
            return icone
        if pasta and os.path.isdir(pasta):
            for raiz, _pastas, arquivos in os.walk(pasta):
                if raiz[len(pasta):].count(os.sep) > 3:
                    continue
                for arquivo in arquivos:
                    if arquivo.lower() in exes:
                        return os.path.join(raiz, arquivo)
    return None


def programas_instalados():
    """[(DisplayName, InstallLocation, DisplayIcon)] de HKLM/HKCU ...\\Uninstall (só Windows)."""
    try:
        import winreg
    except ImportError:
        return []
    caminhos = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    entradas = []
    for raiz, caminho in caminhos:
        try:
            chave = winreg.OpenKey(raiz, caminho)
        except OSError:
            continue
        with chave:
            i = 0
            while True:
                try:
                    nome = winreg.EnumKey(chave, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(chave, nome) as sub:
                        def valor(campo):
                            try:
                                return str(winreg.QueryValueEx(sub, campo)[0])
                            except OSError:
                                return ""
                        entradas.append((valor("DisplayName"), valor("InstallLocation"), valor("DisplayIcon")))
                except OSError:
                    continue
    return entradas


def por_id(item_id, catalogo=None):
    for item in catalogo if catalogo is not None else carregar():
        if item["id"] == item_id:
            return item
    return None


def comando(cmd, catalogo=None, bases=None):
    """["catalogo:gcompris"] → [caminho do exe, *args]; None se não está instalado."""
    if not cmd or not isinstance(cmd[0], str) or not cmd[0].startswith(PREFIXO):
        return cmd
    item = por_id(cmd[0][len(PREFIXO):], catalogo)
    if not item:
        return None
    exe = localizar(item, bases)
    if not exe:
        return None
    argv = [exe]
    for arg in item.get("args", []):
        preenchido = preencher(arg, item)
        if preenchido:
            argv.append(preenchido)
    gravar_config_inicial(item, exe)
    if "LANGUAGE" in (item.get("env") or {}):
        garantir_idioma_kde()
    preparar = item.get("preparar")
    if preparar == "xmoto":
        preparar_xmoto()
    elif preparar == "scratch":
        preparar_scratch()
    elif preparar == "luanti":
        preparar_luanti(exe)
    elif preparar == "supertuxkart":
        preparar_supertuxkart(tamanho_da_tela())
    elif preparar == "pista":
        preparar_pista()
    elif preparar == "cozy":
        import cozy_jogos

        cozy_jogos.preparar_pastas(item["id"])
        return [sys.executable, os.path.abspath(cozy_jogos.__file__), item["id"], exe]
    return argv


# ---------------------------------------------------------------- Luanti
# Mesmo ajuste do beni/bin/luanti no Linux: sem o aviso "Uma nova versão está
# disponível" (com o botão "Visitar site", que abriria o navegador fora do Benikids),
# em português e em tela cheia. Só grava a chave que falta: o que os pais mudarem no
# próprio jogo fica. Valor vazio, como o printf do Linux: sem endereço, sem consulta.
# As chaves de beni/emuladores/luanti-minetest.conf (notebook fraco), mais o aviso
# de versão nova desligado. garantir_chaves só grava a que ainda não existe.
LUANTI_CONFIG = (
    ("update_information_url", ""),
    ("fullscreen", "true"),
    ("language", "pt_BR"),
    ("viewing_range", "40"),
    ("smooth_lighting", "false"),
    ("enable_shaders", "false"),
    ("enable_clouds", "false"),
    ("enable_3d_clouds", "false"),
    ("enable_particles", "false"),
    ("enable_waving_leaves", "false"),
    ("enable_waving_plants", "false"),
    ("enable_waving_water", "false"),
    ("enable_minimap", "false"),
    ("fps_max", "30"),
    ("fps_max_unfocused", "10"),
    ("client_mapblock_limit", "3000"),
    ("mip_map", "false"),
    ("anisotropic_filter", "false"),
    ("bilinear_filter", "false"),
    ("trilinear_filter", "false"),
    ("antialiasing", "none"),
    ("undersampling", "2"),
    ("menu_last_game", "mineclonia"),
)


def garantir_chaves(texto, pares):
    """Texto de um .conf (chave = valor) com as chaves que faltavam no fim."""
    import re

    faltam = [(chave, valor) for chave, valor in pares
              if not re.search(r"^[ \t]*" + re.escape(chave) + r"[ \t]*=", texto, re.MULTILINE)]
    if not faltam:
        return texto
    if texto and not texto.endswith("\n"):
        texto += "\n"
    return texto + "".join(f"{chave} = {valor}\n" for chave, valor in faltam)


def confs_luanti(exe, appdata=None, pacotes=None):
    """Onde o Luanti do winget lê o minetest.conf.

    O LuantiTeam.Luanti do winget é o .zip portátil (RUN_IN_PLACE): os dados e o
    minetest.conf ficam na pasta acima de bin\\luanti.exe, ao lado da pasta builtin.
    O atalho de WinGet\\Links aponta para lá. Numa instalação comum (instalador, sem
    builtin ao lado), o Luanti usa %APPDATA%\\Luanti."""
    caminhos, vistos = [], set()
    if pacotes is None:
        # o atalho de Links nem sempre é um link de verdade: procura a pasta do pacote
        local = os.environ.get("LOCALAPPDATA")
        pacotes = sorted(glob.glob(os.path.join(local, "Microsoft", "WinGet", "Packages", "LuantiTeam.Luanti*",
                                                "**", "bin", "luanti.exe"), recursive=True)) if local else []
    for candidato in (exe, os.path.realpath(exe) if exe else None, *pacotes):
        if not candidato:
            continue
        raiz = os.path.dirname(os.path.dirname(os.path.abspath(candidato)))
        if os.path.isdir(os.path.join(raiz, "builtin")):
            conf = os.path.join(raiz, "minetest.conf")
            chave = os.path.normcase(os.path.realpath(conf))
            if chave not in vistos:
                vistos.add(chave)
                caminhos.append(conf)
    if not caminhos:
        appdata = appdata if appdata is not None else os.environ.get("APPDATA")
        if appdata:
            caminhos.append(os.path.join(appdata, "Luanti", "minetest.conf"))
    return caminhos


def preparar_luanti(exe, appdata=None, pacotes=None):
    gravados = []
    for conf in confs_luanti(exe, appdata, pacotes):
        try:
            texto = ""
            if os.path.isfile(conf):
                with open(conf, encoding="utf-8", errors="surrogateescape", newline="") as f:
                    texto = f.read()
            novo = garantir_chaves(texto, LUANTI_CONFIG)
            if novo != texto:
                os.makedirs(os.path.dirname(conf), exist_ok=True)
                with open(conf, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
                    f.write(novo)
            gravados.append(conf)
        except OSError:
            continue
    return gravados


# ---------------------------------------------------------------- SuperTuxKart
# Como o beni/bin/supertuxkart no Linux: sempre na resolução atual da tela (se o jogo
# troca a resolução, a tela pode ficar apagada ao fechar), e aqui também em tela cheia.
# O catálogo passa --fullscreen --screensize={tela}, que valem já na primeira vez.
# Antes de CADA abertura (o jogo só grava o config.xml quando sai direito; fechar
# pela pílula não grava):
# - sem a pergunta de internet: <enable_internet value="2" /> (0 = não perguntou,
#   1 = permitido, 2 = não permitido). Sem config.xml, um mínimo com essa chave e a
#   versão 8 (UserConfig::m_current_config_version do jogo; o resto fica no padrão
#   e o jogo completa o arquivo quando sair);
# - sem a tela "Criar usuário", que vem com o nome do usuário do Windows (dado
#   pessoal) no campo: sem players.xml, um com o jogador "Benikids" como atual. O
#   jogo cria o que falta nele (modo história, conquistas, ícone) — conferido no
#   PlayerManager/PlayerProfile do código do SuperTuxKart. Um players.xml que já
#   existe fica como está.
STK_CONFIG_VERSAO = 8
STK_CONFIG_MINIMO = ('<?xml version="1.0"?>\n<stkconfig version="%d" >\n'
                     '    <enable_internet value="2" />\n</stkconfig>\n') % STK_CONFIG_VERSAO
STK_PLAYERS_MINIMO = (
    '<?xml version="1.0"?>\n<players version="1" >\n    <current player="Benikids"/>\n'
    '    <player name="Benikids" guest="false" use-frequency="1" icon-filename="" unique-id="1"'
    ' saved-session="false" saved-user="0" saved-token="" last-online-name=""'
    ' last-was-online="false" remember-password="false" default-kart-color="0">\n'
    '    </player>\n</players>\n'
)


def pasta_supertuxkart(appdata=None):
    appdata = appdata if appdata is not None else os.environ.get("APPDATA")
    if not appdata:
        return None
    return os.path.join(appdata, "supertuxkart", "config-0.10")


def config_supertuxkart(appdata=None):
    pasta = pasta_supertuxkart(appdata)
    return os.path.join(pasta, "config.xml") if pasta else None


def ajustar_config_stk(texto, largura=None, altura=None):
    """config.xml do SuperTuxKart em tela cheia, na resolução dada e sem internet (só
    mexe no que já existe, mais o enable_internet: o resto do arquivo fica igual)."""
    import re

    if largura and altura:
        texto = re.sub(r'(\b(?:real_|prev_real_)?width=")\d+(")', rf"\g<1>{largura}\g<2>", texto)
        texto = re.sub(r'(\b(?:real_|prev_real_)?height=")\d+(")', rf"\g<1>{altura}\g<2>", texto)
    texto = re.sub(r'(\bfullscreen=")(?:true|false)(")', r"\g<1>true\g<2>", texto)
    if re.search(r"<enable_internet\b", texto):
        return re.sub(r'(<enable_internet\s+value=")[^"]*(")', r"\g<1>2\g<2>", texto)
    if "</stkconfig>" in texto:
        return texto.replace("</stkconfig>", '    <enable_internet value="2" />\n</stkconfig>', 1)
    return texto


def _gravar_se_mudou(arquivo, texto, novo):
    if novo == texto:
        return False
    os.makedirs(os.path.dirname(arquivo), exist_ok=True)
    with open(arquivo, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
        f.write(novo)
    return True


def preparar_supertuxkart(tela, pasta=None):
    """Devolve o que gravou: subconjunto de {"config.xml", "players.xml"}."""
    pasta = pasta or pasta_supertuxkart()
    if not pasta:
        return set()
    gravados = set()
    largura = altura = None
    try:
        largura, altura = (int(v) for v in (tela or "").split("x"))
    except ValueError:
        pass
    config = os.path.join(pasta, "config.xml")
    try:
        if os.path.isfile(config):
            with open(config, encoding="utf-8", errors="surrogateescape", newline="") as f:
                texto = f.read()
            if _gravar_se_mudou(config, texto, ajustar_config_stk(texto, largura, altura)):
                gravados.add("config.xml")
        elif _gravar_se_mudou(config, "", STK_CONFIG_MINIMO):
            gravados.add("config.xml")
    except OSError:
        pass
    players = os.path.join(pasta, "players.xml")
    try:
        if not os.path.exists(players) and _gravar_se_mudou(players, "", STK_PLAYERS_MINIMO):
            gravados.add("players.xml")
    except OSError:
        pass
    return gravados


# Mesmo ajuste do beni/bin/xmoto no Linux: português, sem o aviso de "versão em
# desenvolvimento", sem internet e sem o contador de quadros (F7 → F13).
XMOTO_CONFIG = (
    ("NotifyAtInit", "false"), ("Language", "pt_BR"), ("WebConfAtInit", "false"),
    ("WebHighscores", "false"), ("CheckHighscoresAtStartup", "false"),
    ("CheckNewLevelsAtStartup", "false"), ("ShowInGameWorldRecord", "false"),
    ("EnableJoysticks", "true"), ("KeySwitchFPS", "K:1073741928:0"),
)


def bancos_xmoto():
    """Onde o X-Moto guarda o xm.db no Windows (varia com a versão do jogo)."""
    candidatos = []
    for variavel, sub in (("APPDATA", "xmoto"), ("LOCALAPPDATA", "xmoto"),
                          ("USERPROFILE", os.path.join(".local", "share", "xmoto")),
                          ("USERPROFILE", ".xmoto")):
        raiz = os.environ.get(variavel)
        if raiz:
            candidatos.append(os.path.join(raiz, sub, "xm.db"))
    return candidatos


def preparar_xmoto(bancos=None, perfil="Benikids"):
    """Deixa o perfil "Benikids" pronto no xm.db que já existe. O banco só nasce na
    primeira vez que o jogo abre; daí em diante a criança cai direto no menu."""
    import sqlite3
    import time

    preparados = []
    for caminho in bancos if bancos is not None else bancos_xmoto():
        if not os.path.isfile(caminho):
            continue
        try:
            db = sqlite3.connect(caminho, timeout=2)
            try:
                site = db.execute("SELECT value FROM xm_parameters WHERE param='siteKey'").fetchone()
                if site and not db.execute("SELECT 1 FROM stats_profiles WHERE id_profile=?", (perfil,)).fetchone():
                    db.execute("INSERT INTO stats_profiles VALUES (?, ?, 0, ?)",
                               (site[0], perfil, time.strftime("%Y-%m-%d %H:%M:%S")))
                for nome in ("", perfil):
                    for chave, valor in XMOTO_CONFIG:
                        db.execute("INSERT OR REPLACE INTO profiles_configs VALUES (?, ?, ?)", (nome, chave, valor))
                db.commit()
                preparados.append(caminho)
            finally:
                db.close()
        except sqlite3.Error:
            continue
    return preparados


def texto_kdeglobals(texto):
    """kdeglobals com Language=pt_BR se essa chave ainda não existe.

    O Qt no Windows nem sempre lê LANG. O KDE lê [Locale] Language neste arquivo
    (%LOCALAPPDATA%\\kdeglobals e %APPDATA%\\kdeglobals). O que os pais mudarem fica.
    """
    import re

    if re.search(r"(?mi)^[ \t]*Language[ \t]*=", texto or ""):
        return texto
    if re.search(r"(?mi)^\[Locale\][ \t]*$", texto or ""):
        return re.sub(r"(?mi)^\[Locale\][ \t]*$", "[Locale]\nLanguage=pt_BR", texto, count=1)
    if texto and not texto.endswith("\n"):
        texto += "\n"
    return (texto or "") + "[Locale]\nLanguage=pt_BR\n"


def garantir_idioma_kde(arquivos=None):
    """Grava Language=pt_BR nos kdeglobals que ainda não escolhem idioma."""
    if arquivos is None:
        arquivos = []
        for variavel in ("LOCALAPPDATA", "APPDATA"):
            raiz = os.environ.get(variavel)
            if raiz:
                arquivos.append(os.path.join(raiz, "kdeglobals"))
    gravados = []
    for caminho in arquivos:
        try:
            texto = ""
            if os.path.isfile(caminho):
                with open(caminho, encoding="utf-8", errors="surrogateescape", newline="") as f:
                    texto = f.read()
            novo = texto_kdeglobals(texto)
            if novo != texto:
                os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
                with open(caminho, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
                    f.write(novo)
            gravados.append(caminho)
        except OSError:
            continue
    return gravados


def preparar_pista(destino=None, origem=None):
    """Copia Pista Turbo.sb3 para Imagens/Scratch se a criança ainda não tem a sua.

    Igual ao Linux (beni/bin/pista-turbo): a cópia que ela editar não é sobrescrita.
    Devolve o caminho do .sb3, ou "" se a original não está no pacote."""
    import shutil

    origem = origem or os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratch", "Pista Turbo.sb3")
    if destino is None:
        try:
            import politicas_edge

            imagens = politicas_edge.pasta_imagens()
        except OSError:
            imagens = ""
        if not imagens:
            return ""
        destino = os.path.join(imagens, "Scratch", "Pista Turbo.sb3")
    if os.path.isfile(destino):
        return destino
    if not os.path.isfile(origem):
        return ""
    try:
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        shutil.copyfile(origem, destino)
    except OSError:
        return ""
    return destino


def preparar_scratch(arquivo=None):
    """Scratch 3 sem a pergunta "ajudar a melhorar o Scratch?": a resposta fica em
    %APPDATA%\\Scratch\\telemetry.json ("optIn"); enquanto falta, o diálogo aparece.
    Grava "optIn": false (não envia nada) só se ninguém respondeu ainda, mantendo o resto."""
    import json

    if arquivo is None:
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return False
        arquivo = os.path.join(appdata, "Scratch", "telemetry.json")
    dados = {}
    if os.path.isfile(arquivo):
        try:
            with open(arquivo, encoding="utf-8") as f:
                dados = json.load(f)
        except (OSError, ValueError):
            return False
        if not isinstance(dados, dict) or "optIn" in dados:
            return False
    dados["optIn"] = False
    try:
        os.makedirs(os.path.dirname(arquivo), exist_ok=True)
        with open(arquivo, "w", encoding="utf-8") as f:
            json.dump(dados, f)
    except OSError:
        return False
    return True


def pasta_no_path(cmd, resolvido):
    """Pasta do exe para pôr no PATH do app, quando o catálogo pede ("path_do_exe": o
    Quatro em Linha só acha o kfourinlineproc.exe pelo PATH). Senão, ""."""
    item = por_id(cmd[0][len(PREFIXO):]) if cmd and cmd[0].startswith(PREFIXO) else None
    if not item or not item.get("path_do_exe") or not resolvido:
        return ""
    return os.path.dirname(resolvido[0])


def ambiente(cmd):
    """Variáveis de ambiente só deste app ("env" no catálogo), ou {}. Roteiro 33: o Tux
    Paint com SDL_RENDER_DRIVER=opengl, porque o Direct3D 9 do driver NVIDIA (GPU híbrida)
    travava no splash ou caía (0xC0000005 em nvd3dumx.dll). Só textos simples."""
    item = por_id(cmd[0][len(PREFIXO):]) if cmd and cmd[0].startswith(PREFIXO) else None
    env = item.get("env") if item else None
    if not isinstance(env, dict):
        return {}
    return {str(k): str(v) for k, v in env.items()
            if isinstance(k, str) and k and "=" not in k and isinstance(v, (str, int))}


def gravar_config_inicial(item, exe=None):
    """Config pronta na pasta de dados do app, se ainda não existe (ex.: SuperTux sem a
    pergunta "conectar à Internet?": o ✕ fecha o jogo à força e ele nunca grava a resposta).

    Com "junto_do_exe", o arquivo fica relativo à pasta do .exe (ex.: Tux Racer, que lê
    config\\options.txt ao lado do programa; a pasta dá escrita a todos os usuários)."""
    inicial = item.get("config_inicial")
    if not isinstance(inicial, dict) or not inicial.get("arquivo"):
        return
    if inicial.get("junto_do_exe"):
        if not exe:
            return
        caminho = os.path.join(os.path.dirname(exe), *inicial["arquivo"].split("/"))
    else:
        caminho = os.path.join(pasta_de_dados_ascii(item), inicial["arquivo"])
    if os.path.exists(caminho):
        return
    try:
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(inicial.get("texto", ""))
    except OSError:
        pass


def pasta_de_dados_ascii(item, usuario=None, raiz=None):
    """Pasta de dados do app num caminho só com letras ASCII.

    O SuperTux 0.7 não abre quando o caminho do usuário tem acento (ex.:
    C:\\Users\\Ângela): ele não consegue criar a pasta em %APPDATA%. Aqui fica em
    %ProgramData%\\Benikids\\dados\\<usuário sem acento>\\<app>, que qualquer usuário cria.
    """
    import unicodedata

    usuario = usuario or os.environ.get("USERNAME") or "crianca"
    limpo = unicodedata.normalize("NFKD", usuario).encode("ascii", "ignore").decode()
    limpo = "".join(c if c.isalnum() or c in "-_." else "_" for c in limpo).strip("._") or "crianca"
    raiz = raiz or os.environ.get("ProgramData", r"C:\ProgramData")
    pasta = os.path.join(raiz, "Benikids", "dados", limpo, item["id"])
    try:
        os.makedirs(pasta, exist_ok=True)
    except OSError:
        pass
    return pasta


def tamanho_da_tela():
    """"LARGURAxALTURA" da tela principal (em pixels reais), ou None fora do Windows."""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        try:
            user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass
        largura, altura = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    except (AttributeError, OSError, ImportError):
        return None
    return f"{largura}x{altura}" if largura > 0 and altura > 0 else None


def preencher(arg, item):
    if "{dados_ascii}" in arg:
        arg = arg.replace("{dados_ascii}", pasta_de_dados_ascii(item))
    if "{tela}" in arg:
        arg = arg.replace("{tela}", tamanho_da_tela() or "1280x720")
    if "{pista}" in arg:
        arg = arg.replace("{pista}", preparar_pista())
    return arg


def tiles(catalogo=None):
    """Tiles do catálogo para a configuração inicial (todos visíveis)."""
    resultado = []
    for item in catalogo if catalogo is not None else carregar():
        if item.get("tile") is False:  # ex.: VLC, usado pelo "Filmes e música"
            continue
        tile = {
            "id": item["id"],
            "label": item["label"],
            "emoji": item.get("emoji", "🎮"),
            "cmd": [PREFIXO + item["id"]],
            "visible": True,
            "category": item.get("category", "jogos"),
        }
        if item.get("gamepad"):
            tile["gamepad"] = True
        resultado.append(tile)
    return resultado


# Uma vez no catalogSeen: o GCompris saiu de Aprender (educativo) para Passatempo.
# Não é um id de app. O padrão de catalogSeen aceita letras, números e hífen.
MARCA_GCOMPRIS = "migracao-gcompris-passatempo"


def _migrar_gcompris(tile, categoria):
    """Move o GCompris que ainda está em Aprender. Não mexe em mais nenhum tile.

    A categoria de um tile que já existe é dos pais (usage-limits.js). Esta função
    só existe para a mudança antiga do catálogo, e o chamador só a usa enquanto
    a marca não está em catalogSeen. Outra categoria — ou a volta para Aprender
    depois da marca — fica como os pais deixaram.
    """
    if not isinstance(tile, dict):
        return False
    if tile.get("id") != "gcompris" or tile.get("cmd") != [PREFIXO + "gcompris"]:
        return False
    if tile.get("category") != "educativo" or categoria == "educativo":
        return False
    tile["category"] = categoria
    return True


def sincronizar_tiles(stored, catalogo=None):
    """Põe nos perfis os apps do catálogo que este computador ainda não viu.

    "catalogSeen" guarda os ids já oferecidos: um app novo no catálogo entra uma vez em
    cada perfil (ligado, como todo o catálogo); um app que os pais removeram não volta.
    Um app que saiu do catálogo (ex.: Neverputt, que fecha sozinho no Windows) sai dos
    perfis, para não sobrar um botão que não abre.
    A marca do GCompris entra junto: a categoria dele muda uma vez, e a de um tile
    que já existe não é mais escrita.
    Devolve (config, mudou).
    """
    import copy

    catalogo = catalogo if catalogo is not None else carregar()
    novos = tiles(catalogo)
    vistos = set(stored.get("catalogSeen") or [])
    ids_catalogo = [t["id"] for t in novos]
    existem = {item["id"] for item in catalogo}

    def fora_do_catalogo(tile):
        cmd = tile.get("cmd") if isinstance(tile, dict) else None
        return (isinstance(cmd, list) and len(cmd) == 1 and isinstance(cmd[0], str)
                and cmd[0].startswith(PREFIXO) and cmd[0][len(PREFIXO):] not in existem)

    orfaos = any(fora_do_catalogo(t) for p in stored.get("profiles", [])
                 for t in p.get("tiles", []))
    ja_migrou = MARCA_GCOMPRIS in vistos
    if vistos >= set(ids_catalogo) and not orfaos and ja_migrou:
        return stored, False
    resultado = copy.deepcopy(stored)
    categoria_gcompris = next(
        (t.get("category", "passatempo") for t in novos if t["id"] == "gcompris"),
        "passatempo",
    )
    for perfil in resultado.get("profiles", []):
        if "tiles" in perfil:
            perfil["tiles"] = [t for t in perfil["tiles"] if not fora_do_catalogo(t)]
            if not ja_migrou:
                for tile in perfil["tiles"]:
                    _migrar_gcompris(tile, categoria_gcompris)
        existentes = {t.get("id") for t in perfil.get("tiles", []) if isinstance(t, dict)}
        for tile in novos:
            if tile["id"] not in vistos and tile["id"] not in existentes:
                perfil.setdefault("tiles", []).append(copy.deepcopy(tile))
    resultado["catalogSeen"] = sorted(vistos | set(ids_catalogo) | {MARCA_GCOMPRIS})
    return resultado, True
