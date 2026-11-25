"""DNS CleanBrowsing no Windows: o script elevado, sem tocar na rede."""

import sys
import unittest
from pathlib import Path
from unittest import mock

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
        self.assertIn("dns-familia: doh do chrome desligado", texto)
        chamada = "& " + dns._ps(dns.SCRIPT) + " -Marca "
        self.assertIn(chamada, texto)
        self.assertNotIn("dns-familia: filtro ligado", texto)
        self.assertIn(r"HKLM:\SOFTWARE\Policies\Google\Chrome", texto)
        self.assertIn(r"HKLM:\SOFTWARE\Policies\Chromium", texto)
        self.assertIn("-Name 'DnsOverHttpsMode' -Value 'off'", texto)
        self.assertLess(texto.index("doh do chrome desligado"), texto.index(chamada))
        self.assertIn("if (-not (Test-Path 'HKLM:\\SOFTWARE\\Benikids'))", texto)
        self.assertNotIn("New-Item -Path 'HKLM:\\SOFTWARE\\Benikids' -Force", texto)
        self.assertNotIn("Unregister-ScheduledTask", texto)
        self.assertIn('-File "C:\\ProgramData\\Benikids\\dns-familia.ps1"', texto)
        self.assertIn("icacls 'C:\\ProgramData\\Benikids\\dns-familia.ps1' /inheritance:r", texto)
        self.assertIn("'*S-1-5-18:(F)'", texto)
        self.assertIn("'*S-1-5-32-544:(F)'", texto)
        self.assertIn("'*S-1-5-32-545:(R)'", texto)
        gravacao = "Set-Content -LiteralPath " + dns._ps(dns.SCRIPT)
        trava = "icacls " + dns._ps(dns.SCRIPT) + " /inheritance:r"
        self.assertLess(texto.index(gravacao), texto.index(trava))
        self.assertLess(texto.index(trava), texto.index("Register-ScheduledTask"))
        self.assertIn("throw 'acl do dns-familia.ps1 falhou'", texto)

    def test_desligar_devolve_o_dns_de_antes_e_deixa_a_tarefa(self):
        texto = "\n".join(dns.linhas_desligar())
        self.assertIn("-Value 0 -PropertyType DWord", texto)
        self.assertIn("-ResetServerAddresses", texto)
        self.assertIn("return 'restaurado'", texto)
        self.assertIn("return 'automatico'", texto)
        self.assertIn("desligado anterior ilegivel", texto)
        self.assertIn("Benikids-DnsLog $resumo", texto)
        self.assertIn(dns.ANTERIOR, texto)
        self.assertLess(texto.index("-Value 0"), texto.index("$resto = Benikids-RestaurarPendentes"))
        self.assertLess(texto.index("-Value 0"), texto.rindex("-ResetServerAddresses"))
        self.assertLess(texto.index("Benikids-DnsLog $resumo"), texto.index("nao atualizou o script"))
        executado = texto.split("@'", 1)[0] + texto.split("\n'@", 1)[-1]
        self.assertNotIn("185.228.168.168", executado)
        self.assertNotIn("2a0d:2a00:1::", executado)
        self.assertNotIn("dns-familia: filtro desligado (dns automatico)", texto)
        self.assertIn("Remove-ItemProperty -Path 'HKLM:\\SOFTWARE\\Policies\\Google\\Chrome' -Name 'DnsOverHttpsMode'", texto)
        self.assertIn("Remove-ItemProperty -Path 'HKLM:\\SOFTWARE\\Policies\\Chromium' -Name 'DnsOverHttpsMode'", texto)
        self.assertNotIn("-Value 'off'", texto)
        self.assertNotIn("Unregister-ScheduledTask", texto)
        self.assertNotIn("exit-kids", texto)
        self.assertNotIn("Exception.Message", texto)

    def test_ipv6_sem_cleanbrowsing_fica_sem_servidor(self):
        texto = dns.script_da_tarefa()
        self.assertNotIn("ipv6 ignorado", texto)
        # o reset automático devolveria o DNS do roteador; ao pôr o filtro, não
        aplicar = texto[texto.index("-ServerAddresses $v4"):]
        self.assertNotIn("-ResetServerAddresses", aplicar)
        self.assertIn("address=none", texto)
        self.assertIn("ipv6 sem cleanbrowsing", texto)
        self.assertIn("ipv6 sem servidor (o do roteador nao vale)", texto)
        self.assertIn("ipv6 continua com o dns anterior", texto)
        # só esvazia se não conseguiu pôr o CleanBrowsing, e não quando já está vazio à toa
        self.assertLess(texto.index("ipv6 sem cleanbrowsing"), texto.index("address=none"))
        self.assertLess(texto.index("$ok6 = $false"), texto.index("address=none"))

    def test_tarefa_restaura_se_sobrou_json_e_nao_poe_o_filtro(self):
        texto = dns.script_da_tarefa()
        bloco = texto[texto.index("if ($ligado -ne 1)"):texto.index("-ServerAddresses $v4")]
        self.assertIn("$resto = Benikids-RestaurarPendentes", bloco)
        self.assertIn("Test-Path -LiteralPath $Anterior", bloco)
        self.assertIn("exit 0", bloco)
        self.assertIn("(uma rede nao voltou)", bloco)
        self.assertNotIn("-ServerAddresses $v4", bloco)
        self.assertIn("if ($r4 -eq 'erro' -or $r6 -eq 'erro') { $ficam[$guid] = $item }", texto)
        self.assertIn("if (-not $vistos.ContainsKey($guid)) { $ficam[$guid] = $map[$guid] }", texto)

    def test_leitura(self):
        self.assertEqual(dns.ler(WinregFalso(None)), {"ligado": False, "configurado": False})
        self.assertTrue(dns.falta(WinregFalso(None)))
        self.assertEqual(dns.ler(WinregFalso(1)), {"ligado": True, "configurado": True})
        self.assertFalse(dns.falta(WinregFalso(1)))
        # 0 é escolha dos pais: a reinstalação não liga de novo
        self.assertEqual(dns.ler(WinregFalso(0)), {"ligado": False, "configurado": True})
        self.assertFalse(dns.falta(WinregFalso(0)))

    def test_guarda_o_dns_antes_de_trocar_e_so_mexe_no_ipv6_se_houver(self):
        texto = dns.script_da_tarefa()
        self.assertIn("param([string]$Marca)", texto)
        self.assertIn(dns.ANTERIOR, texto)
        self.assertIn("NameServer", texto)
        self.assertIn("$modo = 'dhcp'", texto)
        self.assertIn("$modo = 'manual'", texto)
        self.assertIn("$r6 = 'sem-ipv6'", texto)
        self.assertIn("fe80:*", texto)
        for ip in dns.IPV6_PLACEHOLDER:
            self.assertIn(ip, texto)
        self.assertNotIn("2a0d:2a00:1::1", texto)
        self.assertNotIn("Exception.Message", texto)
        self.assertNotIn("\n'@", texto)
        gravar = texto.index("Benikids-GravarAnterior $map")
        ipv4 = texto.index("Set-DnsClientServerAddress -InterfaceIndex $i -AddressFamily IPv4")
        ipv6 = texto.index("Set-DnsClientServerAddress -InterfaceIndex $i -AddressFamily IPv6")
        self.assertLess(gravar, ipv4)
        self.assertLess(texto.index("$r6 = 'sem-ipv6'"), ipv6)
        self.assertLess(ipv4, ipv6)
        self.assertLess(texto.index("if ($ligado -ne 1)"), texto.index("if (-not (Benikids-Ligado))"))
        self.assertLess(texto.index("\n  exit 0\n"), texto.index("-ServerAddresses $v4"))
        self.assertIn("if (-not $parou -and ($Marca -or $mudou))", texto)

    def test_linha_de_log_nao_leva_ip_nem_resultado_velho(self):
        self.assertEqual(
            dns.linha_de_log(True, "ligado Wi-Fi ipv4=ok ipv6=sem-ipv6", True),
            "dns-familia: ligado Wi-Fi ipv4=ok ipv6=sem-ipv6",
        )
        self.assertEqual(
            dns.linha_de_log(False, "desligado Ethernet ipv4=restaurado", True),
            "dns-familia: desligado Ethernet ipv4=restaurado",
        )
        self.assertNotIn("1.1.1.1", dns.linha_de_log(True, "ligado Wi-Fi ipv4=ok 1.1.1.1", True))
        self.assertNotIn("2a0d:2a00:1::", dns.linha_de_log(False, "desligado Wi-Fi 2a0d:2a00:1::", True))
        self.assertNotIn("\n", dns.linha_de_log(True, "ligado\nWi-Fi ipv4=ok", True))
        self.assertEqual(dns.linha_de_log(True, "", True), "dns-familia: ligado")
        self.assertIn("não terminou", dns.linha_de_log(False, "desligado Wi-Fi ipv4=ok", False))
        self.assertNotIn("Wi-Fi", dns.linha_de_log(False, "desligado Wi-Fi ipv4=ok", False))

    def test_aplicar_grava_uma_linha_e_ignora_resultado_de_outra_vez(self):
        with mock.patch.object(dns.os, "name", "nt"), \
             mock.patch.object(dns.secrets, "token_hex", return_value="abc12345"), \
             mock.patch("politicas_edge.rodar_como_admin", return_value=True), \
             mock.patch("telemetria.log_windows") as log, \
             mock.patch.object(dns, "_ler_resumo", return_value="abc12345 ligado Wi-Fi ipv4=ok ipv6=sem-ipv6"):
            self.assertEqual(dns.aplicar(True), (True, "ligado Wi-Fi ipv4=ok ipv6=sem-ipv6"))
        log.assert_called_once_with("dns-familia: ligado Wi-Fi ipv4=ok ipv6=sem-ipv6")

        with mock.patch.object(dns.os, "name", "nt"), \
             mock.patch.object(dns.secrets, "token_hex", return_value="abc12345"), \
             mock.patch("politicas_edge.rodar_como_admin", return_value=True), \
             mock.patch("telemetria.log_windows") as log, \
             mock.patch.object(dns, "_ler_resumo", return_value="deadbeef desligado Ethernet ipv4=automatico"):
            self.assertEqual(dns.aplicar(False), (True, ""))
        log.assert_called_once_with("dns-familia: desligado")

        with mock.patch.object(dns.os, "name", "nt"), \
             mock.patch.object(dns.secrets, "token_hex", return_value="abc12345"), \
             mock.patch("politicas_edge.rodar_como_admin", return_value=False), \
             mock.patch("telemetria.log_windows") as log, \
             mock.patch.object(dns, "_ler_resumo", return_value="abc12345 ligado Wi-Fi ipv4=ok"):
            self.assertEqual(dns.aplicar(True), (False, ""))
        self.assertIn("não terminou", log.call_args[0][0])
        self.assertNotIn("Wi-Fi", log.call_args[0][0])

    def test_fora_do_windows_nao_pede_nada(self):
        with mock.patch.object(dns.os, "name", "posix"):
            self.assertFalse(dns.falta())
            self.assertEqual(dns.ler(), {"ligado": False, "configurado": False})
            self.assertEqual(dns.aplicar(True), (False, ""))


    def test_nao_troca_o_dns_se_nao_gravou_o_anterior(self):
        texto = dns.script_da_tarefa()
        self.assertIn("$Anterior + '.tmp'", texto)
        self.assertIn("Move-Item -LiteralPath $tmp -Destination $Anterior -Force -ErrorAction Stop", texto)
        self.assertIn("return $false", texto)
        self.assertLess(texto.index("acl do arquivo de dns falhou"), texto.index("return $false"))
        gravar = texto.index("if (-not (Benikids-GravarAnterior $map))")
        self.assertLess(texto.index("if (-not $podeGuardar)"), gravar)
        self.assertLess(texto.index("continue", gravar), texto.index("-ServerAddresses $v4"))
        self.assertIn("ipv4=erro ipv6=sem-ipv6", texto)

    def test_aviso_e_log_quando_alguma_placa_fica_em_erro(self):
        resumo = "desligado Ethernet ipv4=erro ipv6=restaurado (uma rede nao voltou)"
        linha = dns.linha_de_log(False, resumo, True)
        self.assertIn("nao voltou", linha)
        self.assertIn("ipv4=erro", linha)
        self.assertIn("não voltou", dns.aviso_para_os_pais(False, resumo))
        self.assertIn("guardar", dns.aviso_para_os_pais(True, "ligado Wi-Fi ipv4=erro ipv6=sem-ipv6"))
        self.assertEqual(
            dns.aviso_para_os_pais(False, "desligado Ethernet ipv4=restaurado ipv6=automatico"),
            "",
        )
        tela = (Path(__file__).resolve().parent.parent / "src" / "frontend" / "launcher-ui.js").read_text()
        self.assertIn("data.aviso", tela)

    def test_atualizacao_troca_o_script_sem_ligar_o_filtro(self):
        texto = "\n".join(dns.linhas_atualizar_script())
        self.assertIn("Set-Content -LiteralPath " + dns._ps(dns.SCRIPT), texto)
        self.assertIn("Register-ScheduledTask", texto)
        self.assertNotIn("-Value 1", texto)
        self.assertNotIn("-Value 0", texto)
        self.assertNotIn("-Marca", texto)
        self.assertIn("& " + dns._ps(dns.SCRIPT), texto)
        self.assertTrue(dns.precisa_atualizar_script(conteudo="script velho"))
        self.assertFalse(dns.precisa_atualizar_script(conteudo=dns.script_da_tarefa()))
        self.assertFalse(dns.precisa_atualizar_script(
            conteudo=dns.script_da_tarefa().replace("\n", "\r\n") + "\r\n",
        ))


if __name__ == "__main__":
    unittest.main()
