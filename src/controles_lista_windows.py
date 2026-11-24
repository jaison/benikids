"""Controles USB genéricos para a lista de ROMs (Windows), sem dependência nova.

O XInput não vê um DragonRise. Aqui o HID (hid.dll + setupapi) entrega chapéu,
eixos e os primeiros botões, no formato (horizontal, vertical, confirmar) que
a lista já usa. O caminho "IG_" é o Xbox visto de novo pelo HID; esse fica no
XInput de cozy_jogos.

É a mesma ideia de src/controles_windows.py no ramo win/controle, só o pedaço
da lista: sem mapeamento de botão da área dos pais e sem SDL. Quando aquele
módulo chegar a este ramo e tiver estados_para_lista(), cozy_jogos passa a
chamá-la e este arquivo deixa de ser lido. Não é um merge daquele ramo.

Fora do Windows, estados() devolve lista vazia. A parte de ctypes só roda lá.
"""

import ctypes
import os
import time
from ctypes import wintypes

_U32 = ctypes.c_uint32
_I32 = ctypes.c_int32
_U16 = ctypes.c_uint16
_U8 = ctypes.c_uint8

USAGE_PAGE_DESKTOP = 0x01
USAGE_JOYSTICK = 0x04
USAGE_GAMEPAD = 0x05
USAGE_MULTIAXIS = 0x08
USAGE_HAT = 0x39
USOS_EIXO = (0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38)

_GENERIC_READ = 0x80000000
_SHARE = 0x1 | 0x2  # o jogo, se abrir o mesmo HID, continua lendo
_OPEN_EXISTING = 3
_OVERLAPPED = 0x40000000
_DIGCF = 0x12  # PRESENT | DEVICEINTERFACE
_HIDP_OK = 0x00110000
_IO_PENDING = 997
_WAIT_OBJECT_0 = 0
_INVALID = ctypes.c_void_p(-1).value

# caminho → dispositivo aberto. Só a thread da lista mexe.
_abertos = {}
_proxima_lista = 0.0


def caminho_de_xbox(caminho):
    """O HID do Xbox (IG_) não entra aqui: o XInput já lê esse controle."""
    return "IG_" in (caminho or "").upper()


def fechar():
    """Solta os HID. A lista chama isto quando o jogo fica com o controle."""
    global _proxima_lista
    for caminho in list(_abertos):
        _fechar_um(caminho)
    _proxima_lista = 0.0


def estados():
    """Um (horizontal, vertical, confirmar) por gamepad HID conectado."""
    global _proxima_lista
    if os.name != "nt":
        return []
    agora = time.monotonic()
    if agora >= _proxima_lista:
        _proxima_lista = agora + 2.0
        try:
            caminhos = [c for c in _caminhos_hid() if c and not caminho_de_xbox(c)]
        except Exception:  # noqa: BLE001 — um HID esquisito não para a lista
            caminhos = []
        atuais = set(caminhos)
        for caminho in list(_abertos):
            if caminho not in atuais:
                _fechar_um(caminho)
        for caminho in caminhos:
            if caminho not in _abertos:
                try:
                    aberto = _abrir_joystick(caminho)
                except OSError:
                    aberto = None
                if aberto:
                    _abertos[caminho] = aberto
    saida = []
    for caminho, aberto in list(_abertos.items()):
        try:
            if _ler_relatorio(aberto):
                movimento = _movimento(aberto)
                if movimento is not None:
                    aberto["ultimo"] = movimento
        except Exception:  # noqa: BLE001 — este controle sai; os outros ficam
            _fechar_um(caminho)
            continue
        if aberto.get("ultimo") is not None:
            saida.append(aberto["ultimo"])
    return saida


# ----------------------------------------------------------------- hid.dll

_dlls = {}


def _dll(nome):
    if nome not in _dlls:
        _dlls[nome] = ctypes.WinDLL(nome, use_last_error=True)
    return _dlls[nome]


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", _U32), ("Data2", _U16), ("Data3", _U16), ("Data4", _U8 * 8)]


class _HIDP_CAPS(ctypes.Structure):
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


class _BUTTON_CAPS(ctypes.Structure):
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


class _VALUE_CAPS(ctypes.Structure):
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


class _OVERLAPPED_IO(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_uint64),
        ("InternalHigh", ctypes.c_uint64),
        ("Offset", _U32),
        ("OffsetHigh", _U32),
        ("hEvent", ctypes.c_void_p),
    ]


class _INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", _GUID),
                ("Flags", wintypes.DWORD), ("Reserved", ctypes.c_void_p)]


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
    dll.GetOverlappedResult.restype = wintypes.BOOL
    dll.CloseHandle.argtypes = [wintypes.HANDLE]
    dll.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    dll.CreateEventW.restype = wintypes.HANDLE
    dll.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    dll.WaitForSingleObject.restype = wintypes.DWORD
    dll.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    dll.CancelIoEx.restype = wintypes.BOOL
    dll.ResetEvent.argtypes = [wintypes.HANDLE]
    dll.ResetEvent.restype = wintypes.BOOL
    return dll


def _hid():
    dll = _dll("hid")
    dll.HidD_GetHidGuid.argtypes = [ctypes.POINTER(_GUID)]
    dll.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(_HIDD_ATTRIBUTES)]
    dll.HidD_GetAttributes.restype = wintypes.BOOL
    dll.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
    dll.HidD_GetPreparsedData.restype = wintypes.BOOL
    dll.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
    dll.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(_HIDP_CAPS)]
    dll.HidP_GetCaps.restype = ctypes.c_long
    dll.HidP_GetButtonCaps.argtypes = [
        ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(_U16), ctypes.c_void_p,
    ]
    dll.HidP_GetButtonCaps.restype = ctypes.c_long
    dll.HidP_GetValueCaps.argtypes = [
        ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(_U16), ctypes.c_void_p,
    ]
    dll.HidP_GetValueCaps.restype = ctypes.c_long
    dll.HidP_GetUsages.argtypes = [
        ctypes.c_int, _U16, _U16, ctypes.c_void_p,
        ctypes.POINTER(_U32), ctypes.c_void_p, ctypes.c_void_p, _U32,
    ]
    dll.HidP_GetUsages.restype = ctypes.c_long
    dll.HidP_GetUsageValue.argtypes = [
        ctypes.c_int, _U16, _U16, _U16,
        ctypes.POINTER(_U32), ctypes.c_void_p, ctypes.c_void_p, _U32,
    ]
    dll.HidP_GetUsageValue.restype = ctypes.c_long
    return dll


def _setup():
    dll = _dll("setupapi")
    dll.SetupDiGetClassDevsW.argtypes = [
        ctypes.POINTER(_GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD,
    ]
    dll.SetupDiGetClassDevsW.restype = wintypes.HANDLE
    dll.SetupDiEnumDeviceInterfaces.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(_GUID), wintypes.DWORD,
        ctypes.POINTER(_INTERFACE_DATA),
    ]
    dll.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
    dll.SetupDiGetDeviceInterfaceDetailW.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_INTERFACE_DATA),
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
    ]
    dll.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
    dll.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
    return dll


def _abrir_arquivo(caminho):
    h = _kernel32().CreateFileW(
        caminho, _GENERIC_READ, _SHARE, None, _OPEN_EXISTING, _OVERLAPPED, None)
    if not h or h == _INVALID:
        return None
    return h


def _fechar_handle(h):
    if h and h != _INVALID:
        _kernel32().CloseHandle(h)


def _usos(caps):
    if caps.IsRange:
        return [(caps.UsagePage, uso) for uso in range(caps.U.Range.UsageMin, caps.U.Range.UsageMax + 1)]
    return [(caps.UsagePage, caps.U.NotRange.Usage)]


def _caminhos_hid():
    hid, setup = _hid(), _setup()
    guid = _GUID()
    hid.HidD_GetHidGuid(ctypes.byref(guid))
    lista = setup.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, _DIGCF)
    if not lista or lista == _INVALID:
        return []
    caminhos = []
    try:
        for indice in range(32):
            data = _INTERFACE_DATA()
            data.cbSize = ctypes.sizeof(data)
            if not setup.SetupDiEnumDeviceInterfaces(lista, None, ctypes.byref(guid), indice, ctypes.byref(data)):
                break
            preciso = wintypes.DWORD(0)
            setup.SetupDiGetDeviceInterfaceDetailW(lista, ctypes.byref(data), None, 0, ctypes.byref(preciso), None)
            if not preciso.value:
                continue
            buf = ctypes.create_string_buffer(preciso.value)
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


def _abrir_joystick(caminho):
    """None se não for joystick/gamepad. O handle fica aberto para a leitura."""
    h = _abrir_arquivo(caminho)
    if not h:
        return None
    preparsed = ctypes.c_void_p()
    evento = None
    try:
        hid = _hid()
        if not hid.HidD_GetPreparsedData(h, ctypes.byref(preparsed)):
            return None
        caps = _HIDP_CAPS()
        if hid.HidP_GetCaps(preparsed, ctypes.byref(caps)) != _HIDP_OK:
            return None
        if caps.UsagePage != USAGE_PAGE_DESKTOP or caps.Usage not in (
            USAGE_JOYSTICK, USAGE_GAMEPAD, USAGE_MULTIAXIS,
        ):
            return None
        botoes = _botoes(hid, preparsed, caps)
        eixos, hat = _eixos_e_hat(hid, preparsed, caps)
        if not botoes and not eixos and hat is None:
            return None
        evento = _kernel32().CreateEventW(None, True, False, None)
        if not evento:
            return None
        tamanho = caps.InputReportByteLength or 0
        if tamanho <= 0:
            return None
        aberto = {
            "handle": h, "preparsed": preparsed, "evento": evento,
            "buf": ctypes.create_string_buffer(tamanho), "tamanho": tamanho,
            "ov": _OVERLAPPED_IO(hEvent=evento), "botoes": botoes[:8],
            "eixos": eixos[:2], "hat": hat, "ultimo": None,
        }
        h = preparsed = evento = None
        return aberto
    finally:
        if preparsed:
            _hid().HidD_FreePreparsedData(preparsed)
        _fechar_handle(evento)
        _fechar_handle(h)


def _botoes(hid, preparsed, caps):
    n_caps = caps.NumberInputButtonCaps
    if not n_caps:
        return []
    vetor = (_BUTTON_CAPS * n_caps)()
    n = _U16(n_caps)
    if hid.HidP_GetButtonCaps(0, ctypes.cast(vetor, ctypes.c_void_p), ctypes.byref(n), preparsed) != _HIDP_OK:
        return []
    usos = []
    for i in range(min(int(n.value), n_caps)):
        usos.extend(_usos(vetor[i]))
    return usos


def _eixos_e_hat(hid, preparsed, caps):
    n_caps = caps.NumberInputValueCaps
    if not n_caps:
        return [], None
    vetor = (_VALUE_CAPS * n_caps)()
    n = _U16(n_caps)
    if hid.HidP_GetValueCaps(0, ctypes.cast(vetor, ctypes.c_void_p), ctypes.byref(n), preparsed) != _HIDP_OK:
        return [], None
    eixos, hat = [], None
    for i in range(min(int(n.value), n_caps)):
        item = vetor[i]
        for pagina, uso in _usos(item):
            if pagina != USAGE_PAGE_DESKTOP:
                continue
            if uso == USAGE_HAT and hat is None:
                hat = (pagina, uso)
            elif uso in USOS_EIXO:
                eixos.append((pagina, uso, int(item.LogicalMin), int(item.LogicalMax)))
    return eixos, hat


def _fechar_um(caminho):
    aberto = _abertos.pop(caminho, None)
    if not aberto:
        return
    k32 = _kernel32()
    try:
        k32.CancelIoEx(aberto["handle"], ctypes.byref(aberto["ov"]))
    except OSError:
        pass
    _hid().HidD_FreePreparsedData(aberto["preparsed"])
    _fechar_handle(aberto["handle"])
    _fechar_handle(aberto["evento"])


def _ler_relatorio(aberto):
    """True se chegou um relatório novo. Espera no máximo 15 ms."""
    k32 = _kernel32()
    k32.ResetEvent(aberto["evento"])
    lidos = wintypes.DWORD(0)
    ok = k32.ReadFile(
        aberto["handle"], aberto["buf"], aberto["tamanho"], ctypes.byref(lidos), ctypes.byref(aberto["ov"]))
    if not ok and ctypes.get_last_error() == _IO_PENDING:
        if k32.WaitForSingleObject(aberto["evento"], 15) != _WAIT_OBJECT_0:
            k32.CancelIoEx(aberto["handle"], ctypes.byref(aberto["ov"]))
            k32.GetOverlappedResult(aberto["handle"], ctypes.byref(aberto["ov"]), ctypes.byref(lidos), True)
            return False
        ok = k32.GetOverlappedResult(aberto["handle"], ctypes.byref(aberto["ov"]), ctypes.byref(lidos), False)
    return bool(ok and lidos.value)


def _uso_valor(hid, aberto, pagina, uso):
    valor = _U32(0)
    if hid.HidP_GetUsageValue(
        0, pagina, 0, uso, ctypes.byref(valor), aberto["preparsed"], aberto["buf"], aberto["tamanho"],
    ) != _HIDP_OK:
        return None
    return int(valor.value)


def _movimento(aberto):
    from cozy_jogos import eixos_do_hat, movimento_de_hid

    hid = _hid()
    mascara = 0
    paginas = {}
    for pagina, uso in aberto["botoes"]:
        paginas.setdefault(pagina, set()).add(uso)
    presentes = {}
    for pagina in paginas:
        lista = (_U16 * 32)()
        n = _U32(32)
        if hid.HidP_GetUsages(
            0, pagina, 0, ctypes.cast(lista, ctypes.c_void_p), ctypes.byref(n),
            aberto["preparsed"], aberto["buf"], aberto["tamanho"],
        ) != _HIDP_OK:
            continue
        presentes[pagina] = {int(lista[i]) for i in range(min(int(n.value), 32))}
    for i, (pagina, uso) in enumerate(aberto["botoes"]):
        if uso in presentes.get(pagina, ()):
            mascara |= 1 << i
    hat = None
    if aberto["hat"] is not None:
        bruto = _uso_valor(hid, aberto, *aberto["hat"])
        if bruto is not None and eixos_do_hat(bruto) != (0, 0):
            hat = bruto
        elif bruto is not None:
            hat = None  # centro: os eixos ainda podem valer
    x = y = None
    faixa_x, faixa_y = (0, 255), (0, 255)
    if aberto["eixos"]:
        pagina, uso, minimo, maximo = aberto["eixos"][0]
        x = _uso_valor(hid, aberto, pagina, uso)
        faixa_x = (minimo, maximo)
    if len(aberto["eixos"]) > 1:
        pagina, uso, minimo, maximo = aberto["eixos"][1]
        y = _uso_valor(hid, aberto, pagina, uso)
        faixa_y = (minimo, maximo)
    return movimento_de_hid(hat, x, y, mascara, faixa_x, faixa_y)
