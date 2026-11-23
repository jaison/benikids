"""DNS CleanBrowsing no Windows: o script elevado, sem tocar na rede."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import dns_familia as dns  # noqa: E402


class WinregFalso:
    HKEY_LOCAL_MACHINE = "HKLM"

    def __init__(self, valor):
        self.valor = valor

    def OpenKey(self, raiz, caminho):  # noqa: N802
        assert raiz == "HKLM"
        if self.valor is None or caminho != dns.CHAVE_WINREG:
            raise FileNotFoundError(caminho)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def QueryValueEx(self, chave, nome):  # noqa: N802
        if nome != dns.VALOR or self.valor is None:
            raise FileNotFoundError(nome)
        return self.valor, 4


class DnsFamiliaTest(unittest.TestCase):
    def test_ips_sao_os_do_linux(self):
        texto = (Path(__file__).resolve().parent.parent / "beni" / "sistema"
                 / "dns-familia-resolved.conf").read_text()
        for ip in dns.IPV4 + dns.IPV6:
            self.assertIn(ip, texto)
        script = dns.script_da_tarefa()
        for ip in dns.IPV4 + dns.IPV6:
            self.assertIn(ip, script)

    def test_ligar_cria_tarefa_sem_uac_depois_e_nao_apaga_chave_existente(self):
        texto = "\n".join(dns.linhas_ligar())
        self.assertIn("Register-ScheduledTask -TaskName 'Benikids DNS Familia'", texto)
        self.assertIn("-UserId 'SYSTEM'", texto)
        self.assertIn("EventID=10000", texto)
        self.assertIn("-AtStartup", texto)
        self.assertIn("-Value 1 -PropertyType DWord", texto)
        self.assertIn("dns-familia: tarefa agendada (placa nova nao pede senha)", texto)
        self.assertIn("dns-familia: filtro ligado", texto)
        self.assertIn("if (-not (Test-Path 'HKLM:\\SOFTWARE\\Benikids'))", texto)
        self.assertNotIn("New-Item -Path 'HKLM:\\SOFTWARE\\Benikids' -Force", texto)
        self.assertNotIn("Unregister-ScheduledTask", texto)

    def test_desligar_devolve_o_dns_automatico_e_deixa_a_tarefa(self):
        texto = "\n".join(dns.linhas_desligar())
        self.assertIn("-Value 0 -PropertyType DWord", texto)
        self.assertIn("-ResetServerAddresses", texto)
        self.assertIn("dns-familia: filtro desligado (dns automatico)", texto)
        self.assertNotIn("Unregister-ScheduledTask", texto)
        self.assertNotIn("exit-kids", texto)
        self.assertNotIn("185.228.168.168", texto)

    def test_tarefa_so_age_com_o_filtro_ligado(self):
        texto = dns.script_da_tarefa()
        self.assertIn("if ($ligado -ne 1) { exit 0 }", texto)
        self.assertLess(texto.index("if ($ligado -ne 1)"), texto.index("Set-DnsClientServerAddress"))

    def test_leitura(self):
        self.assertEqual(dns.ler(WinregFalso(None)), {"ligado": False, "configurado": False})
        self.assertTrue(dns.falta(WinregFalso(None)))
        self.assertEqual(dns.ler(WinregFalso(1)), {"ligado": True, "configurado": True})
        self.assertFalse(dns.falta(WinregFalso(1)))
        # 0 é escolha dos pais: a reinstalação não liga de novo
        self.assertEqual(dns.ler(WinregFalso(0)), {"ligado": False, "configurado": True})
        self.assertFalse(dns.falta(WinregFalso(0)))

    def test_fora_do_windows_nao_pede_nada(self):
        with unittest.mock.patch.object(dns.os, "name", "posix"):
            self.assertFalse(dns.falta())
            self.assertEqual(dns.ler(), {"ligado": False, "configurado": False})
            self.assertFalse(dns.aplicar(True))


if __name__ == "__main__":
    unittest.main()
