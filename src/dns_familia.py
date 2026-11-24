"""DNS com filtro para crianças no Windows (CleanBrowsing Family).

Os mesmos IPs do Linux (beni/sistema/dns-familia-resolved.conf): bloqueia sites
adultos, proxies e VPNs e força a Busca Segura. Vale para o computador, não para
a sessão — Sair dos pais e não há desinstalador que desfaça isto.

Quem liga e desliga é um PowerShell elevado (a mesma senha do UAC). Na
instalação isso entra no lote que já pede a senha (instalar_apps.py). Depois,
Pais → Sistema → "Filtro de internet".

Placa que aparecer mais tarde (Wi-Fi novo): a instalação cria a tarefa
"Benikids DNS Familia", que roda como SYSTEM (sem UAC) na subida do Windows e
quando uma rede conecta (evento 10000 do NetworkProfile). Ela só age se o
registro DnsFamilia estiver em 1. Desligar põe 0: a tarefa continua, mas não
mexe no DNS, e as placas ativas voltam para o DNS automático.

Se o IPv6 da placa não aceitar o CleanBrowsing, a tarefa tira os servidores
DNS do IPv6 (não deixa o do roteador). As consultas seguem pelo IPv4 filtrado.

O Chrome (e o Chromium) instalado ganha DnsOverHttpsMode=off no mesmo lote:
senão o "DNS seguro" dele ignora o DNS do Windows. Não usamos NRPT (uma regra
para todo nome): ela também pega impressora, VPN e nome da rede de casa. O Edge
já tem a mesma política em politicas_edge.py. Outro navegador (o Firefox, por
exemplo) ainda pode furar com o DNS seguro dele.
"""

import os
import sys

IPV4 = ("185.228.168.168", "185.228.169.168")
IPV6 = ("2a0d:2a00:1::", "2a0d:2a00:2::")
TAREFA = "Benikids DNS Familia"
PASTA = r"C:\ProgramData\Benikids"
SCRIPT = PASTA + r"\dns-familia.ps1"
# SIDs, não os nomes: no Windows em português o grupo é "Administradores".
# SYSTEM e Administradores com controle total; Usuários só leitura. A herança
# do ProgramData daria escrita a quem usa o computador, e a tarefa é SYSTEM.
_SID_SYSTEM = "S-1-5-18"
_SID_ADMINS = "S-1-5-32-544"
_SID_USUARIOS = "S-1-5-32-545"
# O Chrome lê isto mesmo fora de domínio. O Chromium usa a outra chave.
CHAVES_DOH = (
    r"HKLM:\SOFTWARE\Policies\Google\Chrome",
    r"HKLM:\SOFTWARE\Policies\Chromium",
)
LOG = PASTA + r"\dns-familia.log"
CHAVE = r"HKLM:\SOFTWARE\Benikids"
CHAVE_WINREG = r"SOFTWARE\Benikids"
VALOR = "DnsFamilia"

# Consulta do evento "rede conectou" (Microsoft-Windows-NetworkProfile 10000).
_CONSULTA_REDE = (
    "<QueryList><Query Id='0' Path='Microsoft-Windows-NetworkProfile/Operational'>"
    "<Select Path='Microsoft-Windows-NetworkProfile/Operational'>"
    "*[System[(EventID=10000)]]</Select></Query></QueryList>"
)


def _ps(texto):
    return "'" + str(texto).replace("'", "''") + "'"


def _lista_ps(itens):
    return "@(" + ", ".join(_ps(i) for i in itens) + ")"


def script_da_tarefa():
    """PowerShell que a tarefa agendada roda como SYSTEM. Idempotente.

    Não faz nada se o filtro estiver desligado (registro 0 ou ausente).
    """
    return "\n".join([
        "$ErrorActionPreference = 'Continue'",
        "function Benikids-DnsLog($m) {",
        f"  if (-not (Test-Path {_ps(PASTA)})) {{ New-Item -ItemType Directory -Path {_ps(PASTA)} | Out-Null }}",
        "  $linha = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' dns-familia: ' + $m",
        f"  Add-Content -LiteralPath {_ps(LOG)} -Value $linha -Encoding UTF8",
        "}",
        "$ligado = 0",
        "try {",
        f"  $ligado = [int](Get-ItemProperty -Path {_ps(CHAVE)} -Name {_ps(VALOR)} -ErrorAction Stop).{VALOR}",
        "} catch { $ligado = 0 }",
        "if ($ligado -ne 1) { exit 0 }",
        f"$v4 = {_lista_ps(IPV4)}",
        f"$v6 = {_lista_ps(IPV6)}",
        "$placas = @(Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object { $_.Status -eq 'Up' })",
        "if ($placas.Count -eq 0) { Benikids-DnsLog 'nenhuma placa ativa'; exit 0 }",
        "foreach ($placa in $placas) {",
        "  $i = $placa.ifIndex",
        "  $nome = [string]$placa.Name",
        "  $atual4 = @()",
        "  try {",
        "    $atual4 = @(Get-DnsClientServerAddress -InterfaceIndex $i -AddressFamily IPv4 -ErrorAction SilentlyContinue |",
        "      Select-Object -ExpandProperty ServerAddresses)",
        "  } catch { }",
        "  $tem4 = ((@($atual4) | Where-Object { $_ }) -join ',')",
        "  if ($tem4 -ne ($v4 -join ',')) {",
        "    try {",
        "      Set-DnsClientServerAddress -InterfaceIndex $i -ServerAddresses $v4 -ErrorAction Stop",
        "      Benikids-DnsLog ('placa ' + $nome + ' ipv4=' + ($v4 -join ','))",
        "    } catch { Benikids-DnsLog ('placa ' + $nome + ' ipv4 erro: ' + $_.Exception.Message) }",
        "  }",
        "  $atual6 = @()",
        "  try {",
        "    $atual6 = @(Get-DnsClientServerAddress -InterfaceIndex $i -AddressFamily IPv6 -ErrorAction SilentlyContinue |",
        "      Select-Object -ExpandProperty ServerAddresses)",
        "  } catch { }",
        "  $tem6 = ((@($atual6) | Where-Object { $_ }) -join ',')",
        "  if ($tem6 -ne ($v6 -join ',')) {",
        "    $ok6 = $false",
        "    try {",
        "      Set-DnsClientServerAddress -InterfaceIndex $i -AddressFamily IPv6 -ServerAddresses $v6 -ErrorAction Stop",
        "      Benikids-DnsLog ('placa ' + $nome + ' ipv6=' + ($v6 -join ','))",
        "      $ok6 = $true",
        "    } catch {",
        "      Benikids-DnsLog ('placa ' + $nome + ' ipv6 sem cleanbrowsing: ' + $_.Exception.Message)",
        "    }",
        # Sem o CleanBrowsing, esvaziar. ResetServerAddresses devolveria o DNS
        # do roteador, e o IPv6 furaria o filtro. netsh com address=none deixa
        # a família sem servidor (as consultas ficam no IPv4, que é o nosso).
        "    if (-not $ok6 -and $tem6 -ne '') {",
        "      $limpo = $false",
        "      $saida = & netsh interface ipv6 set dnsservers name=\"$nome\" source=static address=none validate=no 2>&1",
        "      if ($LASTEXITCODE -eq 0) { $limpo = $true }",
        "      else { Benikids-DnsLog ('placa ' + $nome + ' ipv6 netsh: ' + (($saida | Out-String).Trim())) }",
        "      if ($limpo) { Benikids-DnsLog ('placa ' + $nome + ' ipv6 sem servidor (o do roteador nao vale)') }",
        "      else { Benikids-DnsLog ('placa ' + $nome + ' ipv6 continua com o dns anterior') }",
        "    } elseif (-not $ok6) {",
        "      Benikids-DnsLog ('placa ' + $nome + ' ipv6 sem servidor (o do roteador nao vale)')",
        "    }",
        "  }",
        "}",
        "exit 0",
    ])


def _linhas_log(mensagem):
    return (
        f"Add-Content -LiteralPath {_ps(LOG)} -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + "
        f"{_ps(' dns-familia: ' + mensagem)}) -Encoding UTF8"
    )


def _linhas_chave():
    """Cria a chave se faltar. New-Item -Force numa chave que existe a esvaziaria."""
    return f"if (-not (Test-Path {_ps(CHAVE)})) {{ New-Item -Path {_ps(CHAVE)} | Out-Null }}"


def linhas_acl_do_script():
    """ACL do .ps1, no mesmo lote elevado que o grava.

    Sem herança: o ProgramData deixa Usuários criarem arquivo. Quem troca este
    script é executado como SYSTEM na próxima rede. Usuários ficam só com leitura.
    """
    grants = " ".join(
        f"'*{sid}:({direito})'"
        for sid, direito in ((_SID_SYSTEM, "F"), (_SID_ADMINS, "F"), (_SID_USUARIOS, "R"))
    )
    return [
        "icacls " + _ps(SCRIPT) + " /inheritance:r /grant:r " + grants + " | Out-Null",
        "if ($LASTEXITCODE -ne 0) { throw 'acl do dns-familia.ps1 falhou' }",
    ]


def _argumento_da_tarefa():
    """O -File vai entre aspas: o caminho não pode partir no agendador."""
    return '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + SCRIPT + '"'


def linhas_doh_navegador(ligado):
    """Chrome e Chromium: desliga o DoH próprio, ou devolve quando o filtro sai.

    Não apaga a chave inteira: pode ter outra política. O Edge fica em
    politicas_edge.py (DnsOverHttpsMode=off) e não volta quando o filtro sai.
    """
    linhas = []
    for chave in CHAVES_DOH:
        if ligado:
            linhas.append(
                f"if (-not (Test-Path {_ps(chave)})) {{ New-Item -Path {_ps(chave)} -Force | Out-Null }}"
            )
            linhas.append(
                f"New-ItemProperty -Path {_ps(chave)} -Name 'DnsOverHttpsMode' -Value 'off' "
                "-PropertyType String -Force | Out-Null"
            )
        else:
            linhas.append(
                f"Remove-ItemProperty -Path {_ps(chave)} -Name 'DnsOverHttpsMode' "
                "-ErrorAction SilentlyContinue"
            )
    return linhas


def linhas_ligar():
    """Linhas do PowerShell elevado: grava o script, a tarefa e liga o filtro."""
    return [
        f"New-Item -ItemType Directory -Force -Path {_ps(PASTA)} | Out-Null",
        "@'\n" + script_da_tarefa() + "\n'@ | Set-Content -LiteralPath " + _ps(SCRIPT) + " -Encoding UTF8",
        *linhas_acl_do_script(),
        f"$acao = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument {_ps(_argumento_da_tarefa())}",
        "$subida = New-ScheduledTaskTrigger -AtStartup",
        "$gatilhos = @($subida)",
        "try {",
        "  $classe = Get-CimClass -ClassName MSFT_TaskEventTrigger -Namespace Root/Microsoft/Windows/TaskScheduler",
        "  $rede = New-CimInstance -CimClass $classe -ClientOnly",
        f"  $rede.Subscription = {_ps(_CONSULTA_REDE)}",
        "  $rede.Enabled = $true",
        "  $gatilhos += $rede",
        "} catch {",
        "  " + _linhas_log("gatilho de rede indisponivel") ,
        "}",
        "$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest",
        "$ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-StartWhenAvailable -MultipleInstances IgnoreNew",
        f"Register-ScheduledTask -TaskName {_ps(TAREFA)} -Action $acao -Trigger $gatilhos "
        "-Principal $principal -Settings $ajustes -Force | Out-Null",
        _linhas_log("tarefa agendada (placa nova nao pede senha)"),
        _linhas_chave(),
        f"New-ItemProperty -Path {_ps(CHAVE)} -Name {_ps(VALOR)} -Value 1 -PropertyType DWord -Force | Out-Null",
        *linhas_doh_navegador(True),
        _linhas_log("doh do chrome desligado"),
        f"& {_ps(SCRIPT)}",
        _linhas_log("filtro ligado"),
    ]


def linhas_desligar():
    """Linhas do PowerShell elevado: desliga o filtro e devolve o DNS automático.

    A tarefa fica (sem UAC na próxima vez que ligar). Com o registro em 0 ela
    não reaplica o DNS.
    """
    return [
        f"Stop-ScheduledTask -TaskName {_ps(TAREFA)} -ErrorAction SilentlyContinue",
        _linhas_chave(),
        f"New-ItemProperty -Path {_ps(CHAVE)} -Name {_ps(VALOR)} -Value 0 -PropertyType DWord -Force | Out-Null",
        *linhas_doh_navegador(False),
        "Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object { $_.Status -eq 'Up' } | ForEach-Object {",
        "  Set-DnsClientServerAddress -InterfaceIndex $_.ifIndex -ResetServerAddresses -ErrorAction SilentlyContinue",
        "}",
        _linhas_log("filtro desligado (dns automatico)"),
    ]


def _valor_do_registro(winreg):
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, CHAVE_WINREG) as chave:
            return winreg.QueryValueEx(chave, VALOR)[0]
    except OSError:
        return None


def ler(winreg=None):
    """Estado do filtro. Ler o HKLM não precisa de administrador.

    Fora do Windows: desligado e ainda não configurado.
    """
    if winreg is None:
        if os.name != "nt":
            return {"ligado": False, "configurado": False}
        import winreg  # noqa: PLC0415 — só existe no Windows
    valor = _valor_do_registro(winreg)
    if valor is None:
        return {"ligado": False, "configurado": False}
    return {"ligado": int(valor) == 1, "configurado": True}


def falta(winreg=None):
    """True se o filtro ainda não foi configurado (o lote com UAC liga).

    0 é escolha dos pais: uma reinstalação não liga de novo. Fora do Windows: False.
    """
    if winreg is None and os.name != "nt":
        return False
    return not ler(winreg)["configurado"]


def aplicar(ligado):
    """Pede o UAC e liga ou desliga. Devolve True se o PowerShell terminou."""
    if os.name != "nt":
        return False
    import politicas_edge  # noqa: PLC0415 — o pedido de UAC mora lá

    linhas = linhas_ligar() if ligado else linhas_desligar()
    return politicas_edge.rodar_como_admin(linhas)


def main(args):
    if os.name != "nt" or not args or args[0] not in ("ligar", "desligar", "estado"):
        print("uso (Windows): dns_familia.py ligar | desligar | estado")
        return 2
    if args[0] == "estado":
        print("ligado" if ler()["ligado"] else "desligado")
        return 0
    ok = aplicar(args[0] == "ligar")
    print("pronto" if ok else "não terminou (senha cancelada ou erro)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
