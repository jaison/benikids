"""O scripts/install.sh copia os .py um a um. Se o servidor, a pílula ou o timer
importam um módulo de src/ e ele fica de fora dessa lista, o Linux não abre
(na 1.0.7 faltaram itch_sync e navegacao_sites).

O teste lê a árvore sintática. Não executa o código.
"""
import ast
import re
import unittest
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[1]
SRC = RAIZ / "src"
INSTALL_SH = RAIZ / "scripts" / "install.sh"

# Importados no topo ou sem um "if os.name == 'nt'" visível, mas só existem
# no Windows. O install.sh do Linux não precisa copiá-los.
# janelas_seguras entra aqui, e o overlay também cria um Trabalhador dele no
# Linux. O install.sh copia o arquivo mesmo assim. Tirar essa linha não falha
# este teste; a instalação de mentira do CI falha no "import overlay".
MODULOS_SO_WINDOWS = frozenset({
    "sites_windows",
    "janelas_seguras",
    "vigia_da_pilula",
    "plataforma_windows",
})

# Scripts que o install.sh coloca na instalação e que o Linux realmente abre
# (ou que o servidor importa no topo). O fechamento transitivo sai daqui e de
# todo .py que o próprio install.sh copia.
PONTOS_DE_ENTRADA = (
    "server",
    "overlay",
    "timer_watchdog",
    "application_launcher",
    "process_supervisor",
    "media_session",
)

_COPIA_PY = re.compile(r"\$SRC_DIR/([A-Za-z_][A-Za-z0-9_]*)\.py")


def modulos_copiados(texto):
    """Nomes (sem .py) que o install.sh copia de src/ para a instalação."""
    return set(_COPIA_PY.findall(texto))


def _texto(no):
    if isinstance(no, ast.Constant) and isinstance(no.value, str):
        return no.value
    return None


def _e_os_name(no):
    return (
        isinstance(no, ast.Attribute)
        and no.attr == "name"
        and isinstance(no.value, ast.Name)
        and no.value.id == "os"
    )


def _e_sys_platform(no):
    return (
        isinstance(no, ast.Attribute)
        and no.attr == "platform"
        and isinstance(no.value, ast.Name)
        and no.value.id == "sys"
    )


def classificar_teste(no, flags):
    """'so_windows' se o teste só é verdadeiro no Windows, 'so_linux' se só
    fora dele, ou None quando não dá para saber."""
    if isinstance(no, ast.Name) and no.id in flags:
        return "so_windows"
    if isinstance(no, ast.UnaryOp) and isinstance(no.op, ast.Not):
        interno = classificar_teste(no.operand, flags)
        return {"so_windows": "so_linux", "so_linux": "so_windows"}.get(interno)
    if isinstance(no, ast.BoolOp) and isinstance(no.op, ast.And):
        partes = [classificar_teste(parte, flags) for parte in no.values]
        if "so_linux" in partes:
            return None
        if "so_windows" in partes:
            return "so_windows"
        return None
    if isinstance(no, ast.BoolOp) and isinstance(no.op, ast.Or):
        partes = [classificar_teste(parte, flags) for parte in no.values]
        if partes and all(parte == "so_windows" for parte in partes):
            return "so_windows"
        if partes and all(parte == "so_linux" for parte in partes):
            return "so_linux"
        return None
    if isinstance(no, ast.Call):
        func = no.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "startswith"
            and _e_sys_platform(func.value)
            and len(no.args) == 1
        ):
            prefixo = _texto(no.args[0]) or ""
            if prefixo.startswith("win"):
                return "so_windows"
            if prefixo.startswith("linux"):
                return "so_linux"
        return None
    if not isinstance(no, ast.Compare) or len(no.ops) != 1 or len(no.comparators) != 1:
        return None
    op = no.ops[0]
    esquerda, direita = no.left, no.comparators[0]
    valor = _texto(direita)
    if isinstance(op, ast.Eq):
        if _e_os_name(esquerda) and valor == "nt":
            return "so_windows"
        if _e_os_name(esquerda) and valor == "posix":
            return "so_linux"
        if _e_sys_platform(esquerda) and valor == "win32":
            return "so_windows"
        if _e_sys_platform(esquerda) and valor == "linux":
            return "so_linux"
    if isinstance(op, ast.NotEq):
        if _e_os_name(esquerda) and valor == "nt":
            return "so_linux"
        if _e_os_name(esquerda) and valor == "posix":
            return "so_windows"
        if _e_sys_platform(esquerda) and valor == "win32":
            return "so_linux"
    return None


def _mapa_de_pais(arvore):
    pais = {}
    for pai in ast.walk(arvore):
        for filho in ast.iter_child_nodes(pai):
            pais[id(filho)] = pai
    return pais


def _flags_windows(arvore):
    """Nomes do módulo que guardam os.name == 'nt', como WINDOWS no overlay."""
    flags = set()
    for stmt in arvore.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and stmt.targets[0].__class__ is ast.Name:
            alvos, valor = stmt.targets, stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
            alvos, valor = [stmt.target], stmt.value
        else:
            continue
        if classificar_teste(valor, flags) == "so_windows":
            flags.add(alvos[0].id)
    return flags


def _lista_do_pai(pai, filho):
    if pai is None:
        return None
    for campo in ("body", "orelse", "finalbody"):
        lista = getattr(pai, campo, None)
        if isinstance(lista, list) and filho in lista:
            return lista
    return None


def _sempre_sai(stmts):
    """Todo caminho do bloco termina em return ou raise."""
    if not stmts:
        return False
    ultimo = stmts[-1]
    if isinstance(ultimo, (ast.Return, ast.Raise)):
        return True
    if isinstance(ultimo, ast.If):
        return _sempre_sai(ultimo.body) and _sempre_sai(ultimo.orelse)
    return False


def _sai_se_nao_for_windows(stmt, flags):
    """if os.name != 'nt': return  → o que vem depois só roda no Windows."""
    return (
        isinstance(stmt, ast.If)
        and classificar_teste(stmt.test, flags) == "so_linux"
        and _sempre_sai(stmt.body)
    )


def _guardado_por_if(no, pais, flags):
    atual = no
    while atual is not None:
        pai = pais.get(id(atual))
        if isinstance(pai, ast.If):
            tipo = classificar_teste(pai.test, flags)
            if tipo == "so_windows" and atual in pai.body:
                return True
            if tipo == "so_linux" and atual in pai.orelse:
                return True
        if isinstance(pai, ast.IfExp):
            tipo = classificar_teste(pai.test, flags)
            if tipo == "so_windows" and atual is pai.body:
                return True
            if tipo == "so_linux" and atual is pai.orelse:
                return True
        atual = pai
    return False


def _guardado_por_saida_antes(no, pais, flags):
    atual = no
    while atual is not None:
        pai = pais.get(id(atual))
        lista = _lista_do_pai(pai, atual)
        if lista is not None:
            for anterior in lista[:lista.index(atual)]:
                if _sai_se_nao_for_windows(anterior, flags):
                    return True
        atual = pai
    return False


def _dentro_de(no, recipiente, pais):
    atual = no
    while atual is not None:
        if atual is recipiente:
            return True
        atual = pais.get(id(atual))
    return False


def _funcoes_so_windows(arvore, pais, flags):
    """Função cujo único uso está sob um guarda de Windows (ou dentro de outra
    função assim). O import lá dentro não roda no Linux."""
    funcoes = [
        no for no in ast.walk(arvore)
        if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    por_nome = {}
    for func in funcoes:
        por_nome.setdefault(func.name, []).append(func)
    unicas = {nome: grupo[0] for nome, grupo in por_nome.items() if len(grupo) == 1}
    usos = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Name) and isinstance(no.ctx, ast.Load) and no.id in unicas:
            if not _dentro_de(no, unicas[no.id], pais):
                usos.append(no)
    so_windows = set()

    def uso_e_de_windows(no):
        if _guardado_por_if(no, pais, flags) or _guardado_por_saida_antes(no, pais, flags):
            return True
        atual = pais.get(id(no))
        while atual is not None:
            if isinstance(atual, (ast.FunctionDef, ast.AsyncFunctionDef)) and id(atual) in so_windows:
                return True
            atual = pais.get(id(atual))
        return False

    mudou = True
    while mudou:
        mudou = False
        for nome, func in unicas.items():
            if id(func) in so_windows:
                continue
            chamadas = [uso for uso in usos if uso.id == nome]
            if chamadas and all(uso_e_de_windows(uso) for uso in chamadas):
                so_windows.add(id(func))
                mudou = True
    return so_windows


def _import_so_no_windows(no, pais, flags, funcoes):
    if _guardado_por_if(no, pais, flags) or _guardado_por_saida_antes(no, pais, flags):
        return True
    atual = pais.get(id(no))
    while atual is not None:
        if isinstance(atual, (ast.FunctionDef, ast.AsyncFunctionDef)) and id(atual) in funcoes:
            return True
        atual = pais.get(id(atual))
    return False


def _nomes_do_import(no):
    if isinstance(no, ast.Import):
        return [alias.name.split(".", 1)[0] for alias in no.names]
    if isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
        return [no.module.split(".", 1)[0]]
    return []


def imports_locais_sem_guarda(caminho):
    """(módulo, linha) de cada import local que o Linux executa."""
    arvore = ast.parse(caminho.read_text(encoding="utf-8"), filename=str(caminho))
    pais = _mapa_de_pais(arvore)
    flags = _flags_windows(arvore)
    funcoes = _funcoes_so_windows(arvore, pais, flags)
    achados = []
    for no in ast.walk(arvore):
        if not isinstance(no, (ast.Import, ast.ImportFrom)):
            continue
        if _import_so_no_windows(no, pais, flags, funcoes):
            continue
        for nome in _nomes_do_import(no):
            achados.append((nome, no.lineno))
    return achados


def modulos_exigidos(copiados):
    """Módulos de src/ que os pontos de entrada importam no Linux, inclusive
    os que só aparecem no meio da cadeia. Devolve (conjunto, origem)."""
    locais = {caminho.stem for caminho in SRC.glob("*.py")}
    fila = set(copiados) & locais
    vistos = set()
    exigidos = set()
    origem = {}
    while fila:
        nome = fila.pop()
        if nome in vistos:
            continue
        vistos.add(nome)
        for importado, linha in imports_locais_sem_guarda(SRC / f"{nome}.py"):
            if importado not in locais or importado in MODULOS_SO_WINDOWS:
                continue
            exigidos.add(importado)
            origem.setdefault(importado, []).append(f"{nome}.py:{linha}")
            fila.add(importado)
    return exigidos, origem


class InstaladorLinuxTests(unittest.TestCase):
    def test_pontos_de_entrada_estao_no_install_sh(self):
        copiados = modulos_copiados(INSTALL_SH.read_text(encoding="utf-8"))
        faltam = [nome for nome in PONTOS_DE_ENTRADA if nome not in copiados]
        self.assertEqual(faltam, [])

    def test_modulos_importados_no_linux_estao_no_install_sh(self):
        copiados = modulos_copiados(INSTALL_SH.read_text(encoding="utf-8"))
        exigidos, origem = modulos_exigidos(copiados)
        faltam = sorted(exigidos - copiados)
        detalhe = ", ".join(
            f"{nome} (importado em {', '.join(origem[nome])})" for nome in faltam
        )
        self.assertEqual(
            faltam,
            [],
            f"o install.sh não copia módulo que o Linux importa: {detalhe}",
        )

    def test_tirar_itch_sync_do_install_sh_falha(self):
        # A 1.0.7 quebrou assim: o arquivo existia em src/, o servidor importava,
        # e a lista do install.sh não tinha a linha.
        copiados = modulos_copiados(INSTALL_SH.read_text(encoding="utf-8")) - {"itch_sync"}
        exigidos, origem = modulos_exigidos(copiados | {"server", "application_launcher"})
        self.assertIn("itch_sync", exigidos)
        self.assertNotIn("itch_sync", copiados)
        self.assertIn("itch_sync", exigidos - copiados)
        self.assertTrue(
            any(lugar.startswith("application_launcher.py:") for lugar in origem["itch_sync"]),
            origem["itch_sync"],
        )

    def test_modulos_so_de_windows_nao_sao_exigidos(self):
        copiados = modulos_copiados(INSTALL_SH.read_text(encoding="utf-8"))
        exigidos, _origem = modulos_exigidos(copiados)
        vazou = sorted(MODULOS_SO_WINDOWS & exigidos)
        self.assertEqual(vazou, [])


if __name__ == "__main__":
    unittest.main()
