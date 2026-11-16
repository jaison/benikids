"""Políticas do Edge (uBlock Origin Lite e páginas bloqueadas), sem tocar no registro."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RAIZ_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ_REPO / "src"))

import instalar_apps  # noqa: E402
import politicas_edge as pe  # noqa: E402

FORCELIST = r"SOFTWARE\Policies\Microsoft\Edge\ExtensionInstallForcelist"
BLOCKLIST = r"SOFTWARE\Policies\Microsoft\Edge\URLBlocklist"
UBOL = rf"SOFTWARE\Policies\Microsoft\Edge\3rdparty\extensions\{pe.UBOL_ID}\policy"


class WinregFalso:
    """Só o que politicas_edge.faltam() usa do winreg, sobre um dicionário."""

    HKEY_LOCAL_MACHINE = "HKLM"

    def __init__(self, chaves):
        self.chaves = {k.lower(): v for k, v in chaves.items()}

    class _Chave:
        def __init__(self, valores):
            self.valores = list(valores.items())

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def OpenKey(self, raiz, caminho):  # noqa: N802 — mesmo nome do winreg
        assert raiz == "HKLM"
        if caminho.lower() not in self.chaves:
            raise FileNotFoundError(caminho)
        return self._Chave(self.chaves[caminho.lower()])

    def EnumValue(self, chave, i):  # noqa: N802
        if i >= len(chave.valores):
            raise OSError("fim")
        nome, valor = chave.valores[i]
        return nome, valor, 1

    def QueryValueEx(self, chave, nome):  # noqa: N802
        for n, v in chave.valores:
            if n == nome:
                return v, 1
        raise FileNotFoundError(nome)


def registro_completo(**extra):
    chaves = {
        FORCELIST: {"1": "outra;https://x", "2": pe.UBOL_FORCELIST},
        BLOCKLIST: {str(i + 1): url for i, url in enumerate(("exemplo.com",) + pe.URLS_BLOQUEADAS)},
        UBOL: {"defaultFiltering": "optimal", "disableFirstRunPage": 1},
    }
    chaves.update(extra)
    return chaves


class PoliticasTest(unittest.TestCase):
    def test_paginas_bloqueadas_iguais_as_do_firefox_no_linux(self):
        firefox = json.loads((RAIZ_REPO / "beni" / "firefox" / "policies.json").read_text())
        convertidas = {pe.url_do_firefox(p) for p in firefox["policies"]["WebsiteFilter"]["Block"]}
        self.assertEqual(convertidas, set(pe.URLS_BLOQUEADAS))
        self.assertEqual(len(pe.URLS_BLOQUEADAS), len(set(pe.URLS_BLOQUEADAS)))

    def test_conversao_do_padrao_do_firefox(self):
        self.assertEqual(pe.url_do_firefox("*://www.escolagames.com.br/diversao/*"), "escolagames.com.br/diversao/")
        self.assertEqual(pe.url_do_firefox("*://bestschoolgames.com/*"), "bestschoolgames.com")
        self.assertEqual(pe.url_do_firefox("*://colorir-online.com/apps*"), "colorir-online.com/apps")

    def test_script_aplicar(self):
        texto = "\n".join(pe.script_aplicar(sem_filtro=False))
        self.assertIn(
            r"Benikids-Por 'HKLM:\SOFTWARE\Policies\Microsoft\Edge\ExtensionInstallForcelist' "
            "@('cimighlppcgcoapaliogpjjdehbnofhn;https://edge.microsoft.com/extensionwebstorebase/v1/crx') "
            "'cimighlppcgcoapaliogpjjdehbnofhn;'",
            texto,
        )
        self.assertIn(r"Benikids-Por 'HKLM:\SOFTWARE\Policies\Microsoft\Edge\URLBlocklist' @('escolagames", texto)
        chave = rf"'HKLM:\SOFTWARE\Policies\Microsoft\Edge\3rdparty\extensions\{pe.UBOL_ID}\policy'"
        self.assertIn(f"-Path {chave} -Name 'defaultFiltering' -Value 'optimal' -PropertyType String", texto)
        self.assertIn(f"-Path {chave} -Name 'disableFirstRunPage' -Value 1 -PropertyType DWord", texto)
        # sem o "Escola Games sem filtro", a lista some se tiver ficado de antes
        self.assertIn(r"policy\noFiltering' -Recurse", texto)
        self.assertNotIn("escolagames.com.br')", texto.split("URLBlocklist")[0])
        # nada de apagar a chave inteira do Edge ou recriar chaves que já existem
        self.assertNotIn(r"Remove-Item -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Edge'", texto)
        self.assertIn("if (-not (Test-Path $k)) { New-Item -Path $k -Force", texto)
        self.assertEqual(texto.count("New-Item "), 1)

    def test_escola_games_sem_filtro_fica_pronto(self):
        texto = "\n".join(pe.script_aplicar(sem_filtro=True))
        self.assertIn(r"policy\noFiltering' @('escolagames.com.br')", texto)
        self.assertNotIn(r"noFiltering' -Recurse", texto)
        self.assertFalse(pe.ESCOLA_GAMES_SEM_FILTRO)  # o claude-win confirma antes de ligar

    def test_desfazer_tira_so_o_nosso(self):
        texto = "\n".join(pe.script_desfazer())
        self.assertIn(r"Benikids-Tirar 'HKLM:\SOFTWARE\Policies\Microsoft\Edge\ExtensionInstallForcelist'", texto)
        self.assertIn(r"Benikids-Tirar 'HKLM:\SOFTWARE\Policies\Microsoft\Edge\URLBlocklist'", texto)
        self.assertIn(rf"Remove-Item -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Edge\3rdparty\extensions\{pe.UBOL_ID}'",
                      texto)
        removidos = [l for l in texto.splitlines() if l.startswith("Remove-Item")]
        self.assertEqual(len(removidos), 1)
        # a chave da lista só some se ficou vazia e sem subchaves
        self.assertIn("$outros.Count -eq 0 -and $chave.SubKeyCount -eq 0", texto)

    def test_listas_sao_renumeradas_sem_buracos(self):
        # o Edge para de ler a lista no primeiro número que falta
        funcoes = pe.script_aplicar()[0]
        self.assertIn("Remove-ItemProperty -Path $k -Name $n", funcoes)
        self.assertIn('$i = 1', funcoes)
        self.assertIn("Sort-Object { [int]$_ }", funcoes)

    def test_faltam(self):
        self.assertFalse(pe.faltam(sem_filtro=False, winreg=WinregFalso(registro_completo())))
        self.assertTrue(pe.faltam(sem_filtro=False, winreg=WinregFalso({})))
        sem_ubol = registro_completo(**{FORCELIST: {"1": "outra;https://x"}})
        self.assertTrue(pe.faltam(sem_filtro=False, winreg=WinregFalso(sem_ubol)))
        # um buraco na numeração esconde o uBOL do Edge
        buraco = registro_completo(**{FORCELIST: {"1": "outra;https://x", "3": pe.UBOL_FORCELIST}})
        self.assertTrue(pe.faltam(sem_filtro=False, winreg=WinregFalso(buraco)))
        falta_url = registro_completo(**{BLOCKLIST: {"1": pe.URLS_BLOQUEADAS[0]}})
        self.assertTrue(pe.faltam(sem_filtro=False, winreg=WinregFalso(falta_url)))
        outra_config = registro_completo(**{UBOL: {"defaultFiltering": "basic", "disableFirstRunPage": 1}})
        self.assertTrue(pe.faltam(sem_filtro=False, winreg=WinregFalso(outra_config)))
        # Escola Games sem filtro: a lista tem de bater nos dois sentidos
        self.assertTrue(pe.faltam(sem_filtro=True, winreg=WinregFalso(registro_completo())))
        com_lista = registro_completo(**{UBOL + r"\noFiltering": {"1": "escolagames.com.br"}})
        self.assertFalse(pe.faltam(sem_filtro=True, winreg=WinregFalso(com_lista)))
        self.assertTrue(pe.faltam(sem_filtro=False, winreg=WinregFalso(com_lista)))

    def test_fora_do_windows_nao_pede_nada(self):
        with mock.patch.object(pe.os, "name", "posix"):
            self.assertFalse(pe.faltam())


class LoteComSenhaTest(unittest.TestCase):
    def test_politicas_entram_no_lote_so_quando_faltam(self):
        with tempfile.TemporaryDirectory() as pasta:
            sem, _ = instalar_apps.script_admin([], pasta)
            com, resultados = instalar_apps.script_admin([], pasta, politicas=True)
        self.assertNotIn("Benikids-Por", sem)
        self.assertIn("function Benikids-Por", com)
        self.assertIn("ExtensionInstallForcelist", com)
        self.assertIn("'edge-politicas|' + $c", com)
        # um erro nas políticas não para o lote dos apps
        self.assertIn("catch { $c = 'erro: '", com)
        self.assertIn("finally { $ErrorActionPreference = 'Continue' }", com)
        self.assertTrue(com.rstrip().endswith("'fim|0'"))
        self.assertIn(resultados, com)

    def test_trabalhar_pede_senha_so_para_as_politicas(self):
        avisos = instalar_apps.queue.Queue()
        with mock.patch.object(instalar_apps.politicas_edge, "faltam", return_value=True), \
                mock.patch.object(instalar_apps, "pedem_senha", return_value=set()), \
                mock.patch.object(instalar_apps, "instalar_como_admin", return_value={"edge-politicas": "0", "fim": "0"}) \
                as admin, tempfile.TemporaryDirectory() as pasta:
            instalar_apps.trabalhar([], avisos, pasta=pasta)
        self.assertEqual(admin.call_args.kwargs["politicas"], True)
        estados = []
        while not avisos.empty():
            estados.append(avisos.get_nowait())
        self.assertIn((None, "admin", "politicas"), estados)
        self.assertNotIn((None, "sem_senha", ""), estados)
        self.assertEqual(estados[-1], (None, "fim", ""))

    def test_trabalhar_sem_nada_faltando_nao_pede_senha(self):
        avisos = instalar_apps.queue.Queue()
        with mock.patch.object(instalar_apps.politicas_edge, "faltam", return_value=False), \
                mock.patch.object(instalar_apps, "pedem_senha", return_value=set()), \
                mock.patch.object(instalar_apps, "instalar_como_admin") as admin, \
                tempfile.TemporaryDirectory() as pasta:
            instalar_apps.trabalhar([], avisos, pasta=pasta)
        admin.assert_not_called()


if __name__ == "__main__":
    unittest.main()
