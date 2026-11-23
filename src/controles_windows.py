"""Leitura de controles no Windows, sem dependências novas.

Dois caminhos, os dois por ctypes:

- XInput (xinput1_4 / xinput1_3): controles de Xbox. O SDL desses já vem
  pronto no próprio SDL, então eles NÃO entram no SDL_GAMECONTROLLERCONFIG
  (a ordem dos eixos Y do XInput não é a que o SDL mostra). Servem para o
  menu e para o Start+Select.
- HID (hid.dll + setupapi), aberto com FILE_SHARE_READ|WRITE para o jogo
  continuar lendo o mesmo controle: DragonRise e os genéricos. O caminho
  "IG_" é o Xbox visto de novo pelo HID; esses ficam só no XInput.

Os botões viram os mesmos tokens do Linux ("k:288", "a:17:-1"). O índice
segue a ordem em que o HID (e o SDL em modo HIDAPI) numera: botão 0 =
0x120, eixo 0 = ABS_X, chapéu = ABS_HAT0X/Y. A parte de hardware fica neste
arquivo; os testes usam as funções puras (hat, transições, dispositivo
sintético) e injetam listar/ler/esperar em rodar().
"""

import ctypes
import os
import re
import time
from ctypes import wintypes

# Largura fixa do Windows (no Mac o c_ulong tem 8 bytes e estragaria o layout).
_U32 = ctypes.c_uint32
_I32 = ctypes.c_int32
_U16 = ctypes.c_uint16
_I16 = ctypes.c_int16
_U8 = ctypes.c_uint8

# Mesmos códigos do evdev, para o mapeamento da área dos pais valer igual.
BTN_JOYSTICK = 0x120
ABS_HAT0X = 0x10
ABS_HAT0Y = 0x11
USAGE_PAGE_DESKTOP = 0x01
USAGE_JOYSTICK = 0x04
USAGE_GAMEPAD = 0x05
USAGE_MULTIAXIS = 0x08
USAGE_HAT = 0x39
USOS_EIXO = (0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38)

# XInput, na ordem dos botões do SDL (o direcional é chapéu, não botão).
XINPUT_BOTOES = (
    0x1000, 0x2000, 0x4000, 0x8000,  # A B X Y
    0x0100, 0x0200,                  # LB RB
    0x0020, 0x0010,                  # Back Start
    0x0040, 0x0080,                  # LS RS
)
XINPUT_CIMA, XINPUT_BAIXO, XINPUT_ESQUERDA, XINPUT_DIREITA = 0x0001, 0x0002, 0x0004, 0x0008

# Hat HID: 0 = norte, no sentido horário, até 7. Fora disso (8, 15, nulo) é o centro.
_HAT = {0: (0, -1), 1: (1, -1), 2: (1, 0), 3: (1, 1), 4: (0, 1), 5: (-1, 1), 6: (-1, 0), 7: (-1, -1)}

_VK = {"Up": 0x26, "Down": 0x28, "Left": 0x25, "Right": 0x27, "Return": 0x0D, "Escape": 0x1B}
_VK_ESTENDIDA = {0x25, 0x26, 0x27, 0x28}
_KEYUP = 0x0002
_EXTENDED = 0x0001


def eixos_do_hat(valor):
    """Valor cru do chapéu HID → (x, y) em -1, 0 ou 1. Y negativo é para cima."""
    try:
        valor = int(valor)
    except (TypeError, ValueError):
        return (0, 0)
    return _HAT.get(valor, (0, 0))


def token_gatilho(codigo, valor, estado, limite=150):
    """Gatilho do XInput: 0 é solto, não o lado negativo do eixo.

    O _token do Linux trata o meio da faixa como centro. Num gatilho isso
    dispararia sozinho com o dedo fora. Aqui só conta puxar além do limite,
    uma vez, até soltar."""
    try:
        valor = int(valor)
    except (TypeError, ValueError):
        return None
    if valor >= limite and estado.get(codigo) != 1:
        estado[codigo] = 1
        return f"a:{codigo}:1"
    if valor < limite // 3:
        estado[codigo] = 0
    return None


def transicoes_botoes(antes, agora):
    """Códigos que mudaram: (codigo, 1 apertou / 0 soltou), apertos primeiro."""
    return [(c, 1) for c in sorted(agora - antes)] + [(c, 0) for c in sorted(antes - agora)]


def dispositivo_de_layout(vendor, product, nome, n_botoes, n_eixos, tem_hat, tipo="hid", evento="hid0"):
    """Dispositivo no formato do controles.py, sem falar com o hardware.

    Os bits seguem a ordem do SDL no Windows: botão i = 0x120+i, eixo i = i,
    chapéu em 0x10/0x11. "driver" entra no GUID ('h' ou 'x')."""
    teclas = 0
    for i in range(max(0, int(n_botoes))):
        teclas |= 1 << (BTN_JOYSTICK + i)
    eixos = 0
    for i in range(max(0, int(n_eixos))):
        if i < ABS_HAT0X:
            eixos |= 1 << i
    if tem_hat:
        eixos |= (1 << ABS_HAT0X) | (1 << ABS_HAT0Y)
    vendor = int(vendor)
    product = int(product)
    return {
        "evento": evento,
        "js": "js0",
        "nome": nome or "Controle",
        "bus": "0003",
        "vendor": f"{vendor:04x}",
        "product": f"{product:04x}",
        "version": "0000",
        "chave": f"{vendor:04x}:{product:04x}",
        "teclas": teclas,
        "eixos": eixos,
        "plataforma": "Windows",
        "driver": "x" if tipo == "xinput" else "h",
        "tipo": tipo,
    }


def enviar_tecla(tecla):
    """Seta, Enter ou Esc na janela da frente (o menu nativo e o menu web)."""
    vk = _VK.get(tecla)
    if vk is None or os.name != "nt":
        return
    user32 = _user32()
    flags = _EXTENDED if vk in _VK_ESTENDIDA else 0
    user32.keybd_event(vk, 0, flags, 0)
    user32.keybd_event(vk, 0, flags | _KEYUP, 0)


def rodar(servico, listar=None, ler=None, esperar=None):
    """Thread do Windows. Sem controle, `esperar` recebe 2 s (não gira)."""
    import controles

    listar = listar or listar_dispositivos
    ler = ler or ler_dispositivos
    esperar = esperar or servico.parar.wait
    proxima = 0.0
    avisou_vazio = False
    while not servico.parar.is_set():
        agora = time.monotonic()
        if agora >= proxima:
            try:
                atuais = listar()
            except Exception:  # noqa: BLE001 — um HID esquisito não mata a thread
                atuais = []
            mudou = _trocar(servico, atuais)
            if mudou:
                if atuais:
                    avisou_vazio = False
                    for d in atuais:
                        n_botoes = bin(d.get("teclas") or 0).count("1")
                        controles.log_controle(
                            f"controles: lendo {d['nome'].strip() or 'controle'} "
                            f"({d['chave']}, {d.get('tipo') or '?'}, {n_botoes} botões)")
                elif not avisou_vazio:
                    avisou_vazio = True
                    controles.log_controle("controles: nenhum controle; nova procura a cada 2 s")
            proxima = agora + controles.PAUSA_SEM_CONTROLE_S
        if not servico.abertos:
            esperar(controles.pausa_da_leitura(0))
            proxima = 0.0
            continue
        try:
            ler(servico)
        except Exception:  # noqa: BLE001
            proxima = 0.0
            esperar(controles.pausa_da_leitura(0))
            continue
        servico._verificar_saida(time.monotonic())


def _trocar(servico, atuais):
    """Atualiza a lista. Devolve True se conectou ou desconectou algum."""
    import controles

    chaves = [d["evento"] for d in atuais]
    with servico.trava:
        antes = [d["evento"] for d in servico.dispositivos]
        servico.dispositivos = list(atuais)
        abertos = {}
        for d in atuais:
            anterior = servico.abertos.get(d["evento"])
            estado = anterior[3] if anterior else {}
            faixas = d.get("faixas") or (anterior[2] if anterior else {})
            abertos[d["evento"]] = (None, d, faixas, estado)
        servico.abertos = abertos
        for evento in list(servico.segurados):
            if evento not in abertos:
                servico.segurados.pop(evento, None)
    if chaves == antes:
        return False
    try:
        servico.aplicar(atuais)
    except OSError:
        pass
    return True


def _aplicar_eixo(servico, dispositivo, faixas, estado, codigo, valor):
    token = servico._token(3, codigo, valor, faixas, estado)  # EV_ABS = 3
    if token:
        servico._acionado(dispositivo, token)


def _aplicar_botoes(servico, dispositivo, evento, antes, agora):
    apertados = servico.segurados.setdefault(evento, set())
    for codigo, valor in transicoes_botoes(antes, agora):
        if valor:
            apertados.add(codigo)
            servico._acionado(dispositivo, f"k:{codigo}")
        else:
            apertados.discard(codigo)


# ----------------------------------------------------------------- hardware

_dlls = {}


def _dll(nome):
    if nome not in _dlls:
        _dlls[nome] = ctypes.WinDLL(nome, use_last_error=True)
    return _dlls[nome]


def _user32():
    dll = _dll("user32")
    dll.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
    return dll


def _kernel32():
    dll = _dll("kernel32")
    dll.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    dll.CreateFileW.restype = wintypes.HANDLE
    dll.ReadFile.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
    ]
    dll.ReadFile.restype = wintypes.BOOL
    dll.GetOverlappedResult.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL,
    ]
    dll.CloseHandle.argtypes = [wintypes.HANDLE]
    dll.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    dll.CreateEventW.restype = wintypes.HANDLE
    dll.WaitForMultipleObjects.argtypes = [
        wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL, wintypes.DWORD,
    ]
    dll.WaitForMultipleObjects.restype = wintypes.DWORD
    dll.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    dll.ResetEvent.argtypes = [wintypes.HANDLE]
    dll.ResetEvent.restype = wintypes.BOOL
    return dll


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


class _HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Size", _U32), ("VendorID", _U16),
                ("ProductID", _U16), ("VersionNumber", _U16)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", _U16), ("UsagePage", _U16),
        ("InputReportByteLength", _U16),
        ("OutputReportByteLength", _U16),
        ("FeatureReportByteLength", _U16),
        ("Reserved", _U16 * 17),
        ("NumberLinkCollectionNodes", _U16),
        ("NumberInputButtonCaps", _U16),
        ("NumberInputValueCaps", _U16),
        ("NumberInputDataIndices", _U16),
        ("NumberOutputButtonCaps", _U16),
        ("NumberOutputValueCaps", _U16),
        ("NumberOutputDataIndices", _U16),
        ("NumberFeatureButtonCaps", _U16),
        ("NumberFeatureValueCaps", _U16),
        ("NumberFeatureDataIndices", _U16),
    ]


class _Faixa(ctypes.Structure):
    _fields_ = [
        ("UsageMin", _U16), ("UsageMax", _U16),
        ("StringMin", _U16), ("StringMax", _U16),
        ("DesignatorMin", _U16), ("DesignatorMax", _U16),
        ("DataIndexMin", _U16), ("DataIndexMax", _U16),
    ]


class _UmUso(ctypes.Structure):
    _fields_ = [
        ("Usage", _U16), ("Reserved1", _U16),
        ("StringIndex", _U16), ("Reserved2", _U16),
        ("DesignatorIndex", _U16), ("Reserved3", _U16),
        ("DataIndex", _U16), ("Reserved4", _U16),
    ]


class _Uniao(ctypes.Union):
    _fields_ = [("Range", _Faixa), ("NotRange", _UmUso)]


class HIDP_BUTTON_CAPS(ctypes.Structure):
    _fields_ = [
        ("UsagePage", _U16),
        ("ReportID", _U8),
        ("IsAlias", _U8),
        ("BitField", _U16),
        ("LinkCollection", _U16),
        ("LinkUsage", _U16),
        ("LinkUsagePage", _U16),
        ("IsRange", _U8),
        ("IsStringRange", _U8),
        ("IsDesignatorRange", _U8),
        ("IsAbsolute", _U8),
        ("Reserved", _U32 * 10),
        ("U", _Uniao),
    ]


class HIDP_VALUE_CAPS(ctypes.Structure):
    _fields_ = [
        ("UsagePage", _U16),
        ("ReportID", _U8),
        ("IsAlias", _U8),
        ("BitField", _U16),
        ("LinkCollection", _U16),
        ("LinkUsage", _U16),
        ("LinkUsagePage", _U16),
        ("IsRange", _U8),
        ("IsStringRange", _U8),
        ("IsDesignatorRange", _U8),
        ("IsAbsolute", _U8),
        ("HasNull", _U8),
        ("Reserved", _U8),
        ("BitSize", _U16),
        ("ReportCount", _U16),
        ("Reserved2", _U16 * 5),
        ("UnitsExp", _U32),
        ("Units", _U32),
        ("LogicalMin", _I32),
        ("LogicalMax", _I32),
        ("PhysicalMin", _I32),
        ("PhysicalMax", _I32),
        ("U", _Uniao),
    ]


class _XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", _U16),
        ("bLeftTrigger", _U8),
        ("bRightTrigger", _U8),
        ("sThumbLX", _I16),
        ("sThumbLY", _I16),
        ("sThumbRX", _I16),
        ("sThumbRY", _I16),
    ]


class _XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", _U32), ("Gamepad", _XINPUT_GAMEPAD)]


class _OVERLAPPED(ctypes.Structure):
    # Igual ao OVERLAPPED do Windows 64 bits: 32 bytes.
    _fields_ = [
        ("Internal", ctypes.c_uint64),
        ("InternalHigh", ctypes.c_uint64),
        ("Offset", _U32),
        ("OffsetHigh", _U32),
        ("hEvent", ctypes.c_void_p),
    ]


class _SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", _GUID),
                ("Flags", wintypes.DWORD), ("Reserved", ctypes.c_void_p)]


_INVALID = wintypes.HANDLE(-1).value
_HIDP_OK = 0x00110000
_GENERIC_READ = 0x80000000
_SHARE = 0x1 | 0x2  # leitura e escrita: o jogo abre o mesmo HID
_OPEN_EXISTING = 3
_OVERLAPPED_FLAG = 0x40000000
_DIGCF = 0x12  # PRESENT | DEVICEINTERFACE
_ERROR_IO_PENDING = 997
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258
_XINPUT_OK = 0

# Leituras HID em andamento (evento do dispositivo → estado). Não vai para o json.
_hid_abertos = {}


def _hid():
    dll = _dll("hid")
    dll.HidD_GetHidGuid.argtypes = [ctypes.POINTER(_GUID)]
    dll.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(_HIDD_ATTRIBUTES)]
    dll.HidD_GetAttributes.restype = wintypes.BOOL
    dll.HidD_GetProductString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_ulong]
    dll.HidD_GetProductString.restype = wintypes.BOOL
    dll.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
    dll.HidD_GetPreparsedData.restype = wintypes.BOOL
    dll.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
    dll.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
    dll.HidP_GetCaps.restype = ctypes.c_long
    dll.HidP_GetButtonCaps.argtypes = [
        ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_ushort), ctypes.c_void_p,
    ]
    dll.HidP_GetButtonCaps.restype = ctypes.c_long
    dll.HidP_GetValueCaps.argtypes = [
        ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_ushort), ctypes.c_void_p,
    ]
    dll.HidP_GetValueCaps.restype = ctypes.c_long
    dll.HidP_GetUsages.argtypes = [
        ctypes.c_int, ctypes.c_ushort, ctypes.c_ushort, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong,
    ]
    dll.HidP_GetUsages.restype = ctypes.c_long
    dll.HidP_GetUsageValue.argtypes = [
        ctypes.c_int, ctypes.c_ushort, ctypes.c_ushort, ctypes.c_ushort,
        ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong,
    ]
    dll.HidP_GetUsageValue.restype = ctypes.c_long
    return dll


def _setup():
    dll = _dll("setupapi")
    dll.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(_GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
    dll.SetupDiGetClassDevsW.restype = wintypes.HANDLE
    dll.SetupDiEnumDeviceInterfaces.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(_GUID), wintypes.DWORD,
        ctypes.POINTER(_SP_DEVICE_INTERFACE_DATA),
    ]
    dll.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
    dll.SetupDiGetDeviceInterfaceDetailW.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_SP_DEVICE_INTERFACE_DATA),
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
    ]
    dll.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
    dll.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
    return dll


def _xinput():
    if "xinput" in _dlls:
        return _dlls["xinput"]
    for nome in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
        try:
            dll = ctypes.WinDLL(nome, use_last_error=True)
        except OSError:
            continue
        dll.XInputGetState.argtypes = [wintypes.DWORD, ctypes.POINTER(_XINPUT_STATE)]
        dll.XInputGetState.restype = wintypes.DWORD
        _dlls["xinput"] = dll
        return dll
    _dlls["xinput"] = None
    return None


def _abrir(caminho):
    h = _kernel32().CreateFileW(caminho, _GENERIC_READ, _SHARE, None, _OPEN_EXISTING, _OVERLAPPED_FLAG, None)
    if not h or h == _INVALID:
        return None
    return h


def _fechar(h):
    if h and h != _INVALID:
        _kernel32().CloseHandle(h)


def _nome_produto(h):
    buf = ctypes.create_unicode_buffer(126)
    if not _hid().HidD_GetProductString(h, buf, ctypes.sizeof(buf)):
        return ""
    return buf.value.strip()


def _caminhos_hid():
    hid, setup, k32 = _hid(), _setup(), _kernel32()
    guid = _GUID()
    hid.HidD_GetHidGuid(ctypes.byref(guid))
    lista = setup.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, _DIGCF)
    if not lista or lista == _INVALID:
        return []
    caminhos = []
    try:
        indice = 0
        while indice < 64:
            data = _SP_DEVICE_INTERFACE_DATA()
            data.cbSize = ctypes.sizeof(data)
            if not setup.SetupDiEnumDeviceInterfaces(lista, None, ctypes.byref(guid), indice, ctypes.byref(data)):
                break
            indice += 1
            preciso = wintypes.DWORD(0)
            setup.SetupDiGetDeviceInterfaceDetailW(lista, ctypes.byref(data), None, 0, ctypes.byref(preciso), None)
            if not preciso.value:
                continue
            buf = ctypes.create_string_buffer(preciso.value)
            # cbSize é 8 no 64 bits e 6 no 32 (o cabeçalho, sem o caminho)
            ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0] = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            if not setup.SetupDiGetDeviceInterfaceDetailW(
                lista, ctypes.byref(data), buf, preciso, ctypes.byref(preciso), None,
            ):
                continue
            caminho = ctypes.wstring_at(ctypes.addressof(buf) + ctypes.sizeof(wintypes.DWORD))
            if caminho:
                caminhos.append(caminho)
    finally:
        setup.SetupDiDestroyDeviceInfoList(lista)
    return caminhos


def _usos_de_caps(caps):
    if caps.IsRange:
        return [(caps.UsagePage, u) for u in range(caps.U.Range.UsageMin, caps.U.Range.UsageMax + 1)]
    return [(caps.UsagePage, caps.U.NotRange.Usage)]


def _descrever_hid(caminho):
    """None se não for joystick/gamepad, ou o dict do dispositivo (handle fechado)."""
    if "IG_" in caminho.upper():
        return None  # o Xbox entra pelo XInput
    h = _abrir(caminho)
    if not h:
        return None
    preparsed = ctypes.c_void_p()
    try:
        hid = _hid()
        attrs = _HIDD_ATTRIBUTES()
        attrs.Size = ctypes.sizeof(attrs)
        if not hid.HidD_GetAttributes(h, ctypes.byref(attrs)):
            return None
        if not hid.HidD_GetPreparsedData(h, ctypes.byref(preparsed)):
            return None
        caps = HIDP_CAPS()
        if hid.HidP_GetCaps(preparsed, ctypes.byref(caps)) != _HIDP_OK:
            return None
        if caps.UsagePage != USAGE_PAGE_DESKTOP or caps.Usage not in (
            USAGE_JOYSTICK, USAGE_GAMEPAD, USAGE_MULTIAXIS,
        ):
            return None
        n_botoes = max(1, caps.NumberInputButtonCaps)
        botoes_caps = (HIDP_BUTTON_CAPS * n_botoes)()
        n = ctypes.c_ushort(n_botoes)
        botoes = []
        if caps.NumberInputButtonCaps and hid.HidP_GetButtonCaps(
            0, ctypes.cast(botoes_caps, ctypes.c_void_p), ctypes.byref(n), preparsed,
        ) == _HIDP_OK:
            for i in range(min(n.value, n_botoes)):
                botoes.extend(_usos_de_caps(botoes_caps[i]))
        n_val = max(1, caps.NumberInputValueCaps)
        val_caps = (HIDP_VALUE_CAPS * n_val)()
        n = ctypes.c_ushort(n_val)
        eixos = []
        hat = None
        if caps.NumberInputValueCaps and hid.HidP_GetValueCaps(
            0, ctypes.cast(val_caps, ctypes.c_void_p), ctypes.byref(n), preparsed,
        ) == _HIDP_OK:
            for i in range(min(n.value, n_val)):
                item = val_caps[i]
                for pagina, uso in _usos_de_caps(item):
                    if pagina != USAGE_PAGE_DESKTOP:
                        continue
                    if uso == USAGE_HAT and hat is None:
                        hat = {"pagina": pagina, "uso": uso, "min": item.LogicalMin, "max": item.LogicalMax}
                    elif uso in USOS_EIXO:
                        eixos.append({
                            "pagina": pagina, "uso": uso,
                            "min": item.LogicalMin, "max": item.LogicalMax,
                        })
        if not botoes and not eixos and hat is None:
            return None
        nome = _nome_produto(h) or "Controle"
        faixas = {}
        for i, eixo in enumerate(eixos):
            if i >= ABS_HAT0X:
                break
            faixas[i] = (eixo["min"], eixo["max"])
        if hat is not None:
            faixas[ABS_HAT0X] = (-1, 1)
            faixas[ABS_HAT0Y] = (-1, 1)
        disp = dispositivo_de_layout(
            attrs.VendorID, attrs.ProductID, nome, len(botoes), len(eixos), hat is not None,
            tipo="hid", evento="hid",
        )
        disp["faixas"] = faixas
        disp["_caminho"] = caminho
        disp["_botoes"] = botoes[:32]
        disp["_eixos"] = eixos[:8]
        disp["_hat"] = hat
        disp["_tamanho"] = caps.InputReportByteLength or 0
        return disp
    finally:
        if preparsed:
            _hid().HidD_FreePreparsedData(preparsed)
        _fechar(h)


def _identidades_xinput(caminhos):
    """slot IG_XX → (vendor, product, nome), lido do caminho HID do Xbox."""
    achados = {}
    for caminho in caminhos:
        m = re.search(r"VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4}).*IG_(\d+)", caminho, re.I)
        if not m:
            continue
        slot = int(m.group(3))
        if slot in achados:
            continue
        nome = "Controle Xbox"
        h = _abrir(caminho)
        if h:
            nome = _nome_produto(h) or nome
            _fechar(h)
        achados[slot] = (int(m.group(1), 16), int(m.group(2), 16), nome)
    return achados


def _listar_xinput(identidades):
    dll = _xinput()
    if dll is None:
        return []
    achados = []
    for usuario in range(4):
        estado = _XINPUT_STATE()
        if dll.XInputGetState(usuario, ctypes.byref(estado)) != _XINPUT_OK:
            continue
        vendor, product, nome = identidades.get(usuario, (0x045E, 0x02A1, "Controle Xbox"))
        disp = dispositivo_de_layout(
            vendor, product, nome, 10, 6, True, tipo="xinput", evento=f"xinput{usuario}",
        )
        disp["faixas"] = {0: (-32768, 32767), 1: (-32768, 32767), 2: (-32768, 32767),
                          3: (-32768, 32767), 4: (0, 255), 5: (0, 255),
                          ABS_HAT0X: (-1, 1), ABS_HAT0Y: (-1, 1)}
        disp["_xinput"] = usuario
        achados.append(disp)
    return achados


# Caminhos HID da última procura. Sem controle novo, não reabre o dispositivo
# (reabrir a cada 2 s atrapalharia o jogo que está lendo o mesmo HID).
_cache_hid = {"caminhos": None, "hid": [], "identidades": {}}


def listar_dispositivos():
    """Controles agora: Xbox pelo XInput e genéricos pelo HID. Lista vazia se não há nenhum."""
    if os.name != "nt":
        return []
    try:
        caminhos = _caminhos_hid()
    except Exception:  # noqa: BLE001
        caminhos = []
    if caminhos != _cache_hid["caminhos"]:
        try:
            hid = [d for d in (_descrever_hid(c) for c in caminhos) if d]
        except Exception:  # noqa: BLE001
            hid = []
        hid.sort(key=lambda d: d.get("_caminho", ""))
        for i, d in enumerate(hid):
            d["evento"] = f"hid{i}"
            d["js"] = f"js{i}"
        try:
            identidades = _identidades_xinput(caminhos)
        except Exception:  # noqa: BLE001
            identidades = {}
        _cache_hid["caminhos"] = list(caminhos)
        _cache_hid["hid"] = hid
        _cache_hid["identidades"] = identidades
    try:
        xinput = _listar_xinput(_cache_hid["identidades"])
    except Exception:  # noqa: BLE001
        xinput = []
    return list(_cache_hid["hid"]) + xinput


def _garantir_leitura(disp):
    """Abre o HID (compartilhado) e deixa uma leitura pendente. None no XInput."""
    if disp.get("tipo") != "hid":
        return None
    evento = disp["evento"]
    aberto = _hid_abertos.get(evento)
    if aberto and aberto.get("caminho") == disp.get("_caminho"):
        return aberto
    _soltar(evento)
    h = _abrir(disp.get("_caminho", ""))
    if not h or not disp.get("_tamanho"):
        _fechar(h)
        return None
    preparsed = ctypes.c_void_p()
    if not _hid().HidD_GetPreparsedData(h, ctypes.byref(preparsed)):
        _fechar(h)
        return None
    ev = _kernel32().CreateEventW(None, True, False, None)
    if not ev:
        _hid().HidD_FreePreparsedData(preparsed)
        _fechar(h)
        return None
    aberto = {
        "caminho": disp["_caminho"], "handle": h, "preparsed": preparsed,
        "evento_win": ev, "overlapped": _OVERLAPPED(hEvent=ev),
        "buf": ctypes.create_string_buffer(disp["_tamanho"]),
        "tamanho": disp["_tamanho"], "pendente": False, "botoes": set(),
    }
    _hid_abertos[evento] = aberto
    return aberto


def _soltar(evento):
    aberto = _hid_abertos.pop(evento, None)
    if not aberto:
        return
    k32 = _kernel32()
    try:
        k32.CancelIoEx(aberto["handle"], ctypes.byref(aberto["overlapped"]))
    except Exception:  # noqa: BLE001
        pass
    _hid().HidD_FreePreparsedData(aberto["preparsed"])
    _fechar(aberto["handle"])
    _fechar(aberto["evento_win"])


def _pedir_relatorio(aberto):
    """'pendente', 'pronto' (já veio) ou 'erro'."""
    if aberto["pendente"]:
        return "pendente"
    k32 = _kernel32()
    k32.ResetEvent(aberto["evento_win"])
    lidos = wintypes.DWORD(0)
    ok = k32.ReadFile(aberto["handle"], aberto["buf"], aberto["tamanho"], ctypes.byref(lidos),
                      ctypes.byref(aberto["overlapped"]))
    if ok:
        return "pronto"
    if ctypes.get_last_error() == _ERROR_IO_PENDING:
        aberto["pendente"] = True
        return "pendente"
    return "erro"


def _relatorio_pronto(aberto):
    """True com relatório, False se ainda não (não deve ocorrer), None se o HID caiu."""
    if not aberto["pendente"]:
        return False
    lidos = wintypes.DWORD(0)
    ok = _kernel32().GetOverlappedResult(
        aberto["handle"], ctypes.byref(aberto["overlapped"]), ctypes.byref(lidos), False)
    aberto["pendente"] = False
    if not ok:
        return None
    return lidos.value > 0


def _ler_hid(servico, disp, aberto):
    hid = _hid()
    buf = aberto["buf"]
    tamanho = aberto["tamanho"]
    preparsed = aberto["preparsed"]
    pagina_botoes = {}
    for pagina, uso in disp.get("_botoes") or []:
        pagina_botoes.setdefault(pagina, set()).add(uso)
    apertados = set()
    for pagina, esperados in pagina_botoes.items():
        lista = (ctypes.c_ushort * 64)()
        n = ctypes.c_ulong(64)
        if hid.HidP_GetUsages(0, pagina, 0, ctypes.cast(lista, ctypes.c_void_p), ctypes.byref(n),
                              preparsed, buf, tamanho) != _HIDP_OK:
            continue
        presentes = {lista[i] for i in range(min(n.value, 64))}
        for i, (pag, uso) in enumerate(disp["_botoes"]):
            if pag == pagina and uso in presentes and uso in esperados:
                apertados.add(BTN_JOYSTICK + i)
    antes = aberto["botoes"]
    _fd, dispositivo, faixas, estado = servico.abertos.get(disp["evento"], (None, disp, {}, {}))
    _aplicar_botoes(servico, dispositivo, disp["evento"], antes, apertados)
    aberto["botoes"] = apertados
    for i, eixo in enumerate(disp.get("_eixos") or []):
        if i >= ABS_HAT0X:
            break
        valor = ctypes.c_ulong(0)
        if hid.HidP_GetUsageValue(0, eixo["pagina"], 0, eixo["uso"], ctypes.byref(valor),
                                  preparsed, buf, tamanho) == _HIDP_OK:
            _aplicar_eixo(servico, dispositivo, faixas, estado, i, valor.value)
    hat = disp.get("_hat")
    if hat:
        valor = ctypes.c_ulong(0)
        bruto = None
        if hid.HidP_GetUsageValue(0, hat["pagina"], 0, hat["uso"], ctypes.byref(valor),
                                  preparsed, buf, tamanho) == _HIDP_OK:
            bruto = valor.value
        x, y = eixos_do_hat(bruto)
        _aplicar_eixo(servico, dispositivo, faixas, estado, ABS_HAT0X, x)
        _aplicar_eixo(servico, dispositivo, faixas, estado, ABS_HAT0Y, y)


def _ler_xinput(servico, disp, anterior):
    dll = _xinput()
    if dll is None:
        return anterior
    estado = _XINPUT_STATE()
    if dll.XInputGetState(int(disp["_xinput"]), ctypes.byref(estado)) != _XINPUT_OK:
        return anterior
    if anterior and anterior[0] == estado.dwPacketNumber:
        return anterior
    pad = estado.Gamepad
    agora = {BTN_JOYSTICK + i for i, mascara in enumerate(XINPUT_BOTOES) if pad.wButtons & mascara}
    _fd, dispositivo, faixas, eixo_estado = servico.abertos.get(disp["evento"], (None, disp, {}, {}))
    _aplicar_botoes(servico, dispositivo, disp["evento"], anterior[1] if anterior else set(), agora)
    for codigo, valor in ((0, pad.sThumbLX), (1, pad.sThumbLY), (2, pad.sThumbRX), (3, pad.sThumbRY)):
        _aplicar_eixo(servico, dispositivo, faixas, eixo_estado, codigo, int(valor))
    for codigo, valor in ((4, pad.bLeftTrigger), (5, pad.bRightTrigger)):
        token = token_gatilho(codigo, int(valor), eixo_estado)
        if token:
            servico._acionado(dispositivo, token)
    x = (1 if pad.wButtons & XINPUT_DIREITA else 0) - (1 if pad.wButtons & XINPUT_ESQUERDA else 0)
    y = (1 if pad.wButtons & XINPUT_BAIXO else 0) - (1 if pad.wButtons & XINPUT_CIMA else 0)
    _aplicar_eixo(servico, dispositivo, faixas, eixo_estado, ABS_HAT0X, x)
    _aplicar_eixo(servico, dispositivo, faixas, eixo_estado, ABS_HAT0Y, y)
    return (estado.dwPacketNumber, agora)


_xinput_cache = {}


def ler_dispositivos(servico):
    """Uma fatia de leitura. Bloqueia até ~50 ms (não gira no processador)."""
    import controles

    vivos = set()
    esperas = []
    for _fd, disp, _f, _e in list(servico.abertos.values()):
        vivos.add(disp["evento"])
        if disp.get("tipo") == "xinput":
            _xinput_cache[disp["evento"]] = _ler_xinput(servico, disp, _xinput_cache.get(disp["evento"]))
            continue
        aberto = _garantir_leitura(disp)
        if not aberto:
            continue
        pedido = _pedir_relatorio(aberto)
        if pedido == "erro":
            _soltar(disp["evento"])
            continue
        if pedido == "pronto":
            try:
                _ler_hid(servico, disp, aberto)
            except Exception:  # noqa: BLE001
                _soltar(disp["evento"])
            continue
        esperas.append((disp, aberto))
    for evento in list(_hid_abertos):
        if evento not in vivos:
            _soltar(evento)
    for evento in list(_xinput_cache):
        if evento not in vivos:
            _xinput_cache.pop(evento, None)
    if not esperas:
        servico.parar.wait(controles.PAUSA_COM_CONTROLE_S)
        return
    handles = (wintypes.HANDLE * len(esperas))(*(a["evento_win"] for _d, a in esperas))
    codigo = _kernel32().WaitForMultipleObjects(len(esperas), handles, False, int(controles.PAUSA_COM_CONTROLE_S * 1000))
    if codigo == _WAIT_TIMEOUT or codigo < _WAIT_OBJECT_0 or codigo >= _WAIT_OBJECT_0 + len(esperas):
        return
    disp, aberto = esperas[codigo - _WAIT_OBJECT_0]
    pronto = _relatorio_pronto(aberto)
    if pronto is None:
        _soltar(disp["evento"])
        return
    if pronto:
        try:
            _ler_hid(servico, disp, aberto)
        except Exception:  # noqa: BLE001
            _soltar(disp["evento"])
