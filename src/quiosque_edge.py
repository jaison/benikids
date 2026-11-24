"""Janelas a mais do Edge/Chrome em quiosque (special:external-browser).

O --kiosk só vale para a primeira janela. Um window.open, o Ctrl+N, o
Inspecionar, o "Abrir link em nova janela", o diálogo de arquivo (#32770,
Import/Export, Ctrl+O, Ctrl+S), o de impressão e o menu de contexto nascem
como outra janela de nível superior da mesma árvore. A criança sai do quiosque
por elas, e o overlay não pode passar a tratar essa janela como o app.

Este módulo não usa ctypes: a decisão é testável fora do Windows. Quem fecha
de verdade é o plataforma_windows, com PostMessage (não espera o outro app,
sem AttachThreadInput), na thread de trabalho do overlay.
"""

WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
IDCANCEL = 2

# O Edge hospeda a janela de digitação. Fechar isso tira o teclado do jogo
# (o nome da boneca, um campo do site). O resto da árvore, visível e de nível
# superior, não é o quiosque.
CLASSES_INTOCADAS = frozenset({
    "IME",
    "MSCTFIME UI",
    "CiceroUIWndFrame",
})


def titulo_curto(titulo, limite=40):
    """Uma linha curta para o log, sem quebra e sem o título inteiro da página."""
    texto = " ".join(str(titulo or "").split())
    if not texto:
        return "(sem título)"
    if len(texto) <= limite:
        return texto
    return texto[: limite - 1] + "…"


def mensagens_para_fechar(classe):
    """O que postar, sem esperar. O diálogo do sistema (#32770, Abrir/Salvar/
    Imprimir) recebe IDCANCEL e WM_CLOSE; as outras janelas, só WM_CLOSE."""
    if classe == "#32770":
        return [(WM_COMMAND, IDCANCEL), (WM_CLOSE, 0)]
    return [(WM_CLOSE, 0)]


def _navegador(janela):
    """Janela de chrome do Edge/Chrome, sem dono (não é diálogo pendurado)."""
    return (str(janela.get("classe") or "").startswith("Chrome_WidgetWin")
            and not janela.get("dono"))


def _maior(navegadores):
    """A da quiosque quando várias aparecem juntas: a maior. Empate fica com a
    mais ao fundo (a lista vem com a da frente primeiro; a de trás nasceu antes)."""
    escolhida = max(
        enumerate(navegadores),
        key=lambda par: (par[1].get("area") or 0, par[0]),
    )
    return escolhida[1]["hwnd"]


def analisar(principal, janelas):
    """principal: hwnd já travado do quiosque, ou None.

    janelas: hwnd, classe, titulo, dono, area, visivel (faltou visivel = está).
    Ordem Z, a da frente primeiro.

    Devolve (principal, fechar, edge).
    - edge False: não há janela Chrome_WidgetWin (Firefox, ou o Edge ainda não
      mostrou a dele). Não fecha nada; o overlay segue com as janelas sem dono.
    - Com a do quiosque ainda na lista: ela fica, e toda outra janela visível
      (segunda janela do navegador, #32770, menu) entra em fechar. A de digitar
      (CLASSES_INTOCADAS) não.
    - Se o hwnd travado sumiu e sobrou outra janela de navegador: não adota
      nenhuma. Fecha todas. O hwnd antigo continua travado para a próxima volta
      não eleger a que sobrou.
    - Se o hwnd sumiu e não há outra de navegador: espera (pode ser um pisca).
      Diálogo que tenha ficado ainda fecha.
    """
    vivas = [j for j in janelas if j.get("visivel", True)]
    navegadores = [j for j in vivas if _navegador(j)]
    hwnds = {j["hwnd"] for j in navegadores}
    edge = principal is not None or bool(navegadores)
    if not edge:
        return None, [], False
    if principal is None:
        principal = navegadores[0]["hwnd"] if len(navegadores) == 1 else _maior(navegadores)
    fechar = []
    quiosque_na_lista = principal in hwnds
    if quiosque_na_lista or not navegadores:
        for janela in vivas:
            if janela["hwnd"] == principal:
                continue
            if janela.get("classe") in CLASSES_INTOCADAS:
                continue
            fechar.append(janela)
    else:
        # a do quiosque não está e há outras de navegador: fecha todas
        for janela in vivas:
            if janela.get("classe") in CLASSES_INTOCADAS:
                continue
            fechar.append(janela)
    return principal, fechar, True


class Estado:
    """Lembra o hwnd do quiosque entre as voltas do overlay."""

    def __init__(self):
        self.principal = None
        self.edge = False

    def observar(self, janelas):
        """Atualiza o hwnd travado. Devolve as janelas a fechar nesta volta."""
        self.principal, fechar, self.edge = analisar(self.principal, janelas)
        return fechar

    def para_cuidar(self, janelas):
        """Quais hwnds o overlay pode maximizar, esticar ou trazer para a frente.

        No Edge, só a do quiosque (ou nenhuma, se ela não está na lista: a
        segunda não é adotada). Sem janela Chrome, as sem dono, como antes.
        """
        self.observar(janelas)
        if not self.edge:
            return [j["hwnd"] for j in janelas if j.get("visivel", True) and not j.get("dono")]
        if any(j.get("hwnd") == self.principal for j in janelas):
            return [self.principal]
        return []
