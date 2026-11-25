"""DNS com filtro para crianças no Windows (CleanBrowsing Family).

Os mesmos IPs do Linux (beni/sistema/dns-familia-resolved.conf): bloqueia sites
adultos, proxies e VPNs e força a Busca Segura. Vale para o computador, não para
a sessão — Sair dos pais e não há desinstalador que desfaça isto.

Quem liga e desliga é um PowerShell elevado (a mesma senha do UAC). Na
instalação isso entra no lote que já pede a senha (instalar_apps.py). Depois,
Pais → Sistema → "Filtro de internet".

Ao ligar, o DNS de cada placa (IPv4 e IPv6, automático ou manual) vai para
dns-familia-anterior.json, com a mesma ACL do script, antes de trocar. Ao
desligar, cada placa volta exatamente ao que estava. Placa sem esse registro
(filtro antigo, ou placa que não estava na hora) volta ao DNS automático.

Placa que aparecer mais tarde (Wi-Fi novo, outro adaptador): a tarefa
"Benikids DNS Familia" roda como SYSTEM (sem UAC) na subida do Windows e
quando uma rede conecta (evento 10000 do NetworkProfile). O mesmo script
guarda o DNS daquela placa e aplica o filtro. Com o registro em 1 ela
aplica o filtro. Com o registro em 0 ela não põe o filtro: se ainda houver
dns-familia-anterior.json (a volta falhou, ou a placa não estava na hora),
restaura essas placas e apaga o GUID que voltou.

O DNS de uma placa só muda depois que o JSON foi gravado e a ACL fechou.
Se a gravação falhar, a placa fica como está.

IPv6 da família, na documentação do CleanBrowsing: 2a0d:2a00:1:: e
2a0d:2a00:2::. O endereço com ::1 é o filtro Adulto (não bloqueia proxy):
não serve aqui. O IPv6 só entra na placa que tem IPv6 de verdade (um endereço
que não é link-local, ou um DNS IPv6 que não seja o fec0:0:0:ffff de
mentira do Windows). Placa sem isso fica como está. Se o CleanBrowsing não
pegar no IPv6, a placa fica sem servidor DNS IPv6; o IPv4 filtrado continua.
Uma falha no IPv6 não desfaz o IPv4 nem deixa o PC sem DNS.

O Chrome (e o Chromium) instalado ganha DnsOverHttpsMode=off no mesmo lote:
senão o "DNS seguro" dele ignora o DNS do Windows. Não usamos NRPT (uma regra
para todo nome): ela também pega impressora, VPN e nome da rede de casa. O Edge
já tem a mesma política em politicas_edge.py. Outro navegador (o Firefox, por
exemplo) ainda pode furar com o DNS seguro dele.
"""

import os
import re
import secrets
import sys

IPV4 = ("185.228.168.168", "185.228.169.168")
# Family, não Adult (::1). Conferido em cleanbrowsing.org/filters.
IPV6 = ("2a0d:2a00:1::", "2a0d:2a00:2::")
# DNS IPv6 que o Windows mostra quando a rede não deu DNS IPv6.
IPV6_PLACEHOLDER = ("fec0:0:0:ffff::1", "fec0:0:0:ffff::2", "fec0:0:0:ffff::3")
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
ANTERIOR = PASTA + r"\dns-familia-anterior.json"
PLACAS = PASTA + r"\dns-familia-placas.txt"
RESULTADO = PASTA + r"\dns-familia-resultado.txt"
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


_RE_IP = re.compile(
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b|(?:[0-9a-fA-F]{0,4}:){2,}[0-9a-fA-F:]*"
)


def _marca(marca):
    """Hex só: entra no PowerShell entre aspas e não leva nada da pessoa."""
    if isinstance(marca, str) and re.fullmatch(r"[0-9a-f]{8,32}", marca):
        return marca
    return secrets.token_hex(8)


def linha_de_log(ligado, resumo, ok):
    """Uma linha para o beni-windows.log. Sem IP e sem outra linha no meio."""
    acao = "ligado" if ligado else "desligado"
    if not ok:
        return f"dns-familia: {acao} não terminou (senha cancelada ou erro)"
    texto = _RE_IP.sub("?", " ".join(str(resumo or "").split()))
    if len(texto) > 400:
        texto = texto[:400].rstrip()
    if not texto.startswith(acao):
        return f"dns-familia: {acao}"
    return "dns-familia: " + texto


def aviso_para_os_pais(ligado, resumo):
    """Texto da área dos pais quando alguma placa ficou em erro.

    O PowerShell termina com código 0 mesmo assim: a senha foi aceita e o
    registro mudou. O aviso é o que distingue "voltou" de "uma rede ficou".
    """
    if "=erro" not in (resumo or ""):
        return ""
    if ligado:
        return (
            "Uma rede ficou como estava: não deu para guardar o DNS de antes, "
            "então o filtro não entrou nela."
        )
    return (
        "O filtro foi desligado, mas uma rede não voltou ao DNS de antes. "
        "O Windows tenta de novo sozinho, quando ligar ou quando a rede aparecer."
    )


def _ler_resumo(caminho=None):
    try:
        with open(caminho or RESULTADO, encoding="utf-8-sig") as arquivo:
            return " ".join(arquivo.read(2000).split())
    except OSError:
        return ""


def _linhas_variaveis():
    return [
        f"$Pasta = {_ps(PASTA)}",
        f"$Log = {_ps(LOG)}",
        f"$Anterior = {_ps(ANTERIOR)}",
        f"$Placas = {_ps(PLACAS)}",
        f"$Resultado = {_ps(RESULTADO)}",
        f"$Chave = {_ps(CHAVE)}",
    ]


def _linhas_funcoes_comuns():
    """Funções do arquivo anterior. Sem os IPs da família: o desligar também usa."""
    return [
        "function Benikids-DnsLog($m) {",
        "  try {",
        "    $m = ([string]$m) -replace '[\\r\\n]', ' '",
        "    if (-not (Test-Path -LiteralPath $Pasta)) { New-Item -ItemType Directory -Path $Pasta | Out-Null }",
        "    $linha = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' dns-familia: ' + $m",
        "    Add-Content -LiteralPath $Log -Value $linha -Encoding UTF8 -ErrorAction Stop",
        "  } catch { }",
        "}",
        "function Benikids-Proteger($caminho) {",
        "  & icacls \"$caminho\" /inheritance:r /grant:r "
        f"'*{_SID_SYSTEM}:(F)' '*{_SID_ADMINS}:(F)' '*{_SID_USUARIOS}:(R)' | Out-Null",
        "  if ($LASTEXITCODE -ne 0) {",
        "    Benikids-DnsLog 'acl do arquivo de dns falhou'",
        "    return $false",
        "  }",
        "  return $true",
        "}",
        "function Benikids-Esc($s) {",
        "  $t = [string]$s",
        "  $bs = [string][char]92",
        "  $q = [string][char]34",
        "  return $t.Replace($bs, $bs + $bs).Replace($q, $bs + $q)",
        "}",
        "function Benikids-Lista($valor) {",
        "  $saida = New-Object System.Collections.Generic.List[string]",
        "  if ($null -eq $valor) { return ,$saida.ToArray() }",
        "  if ($valor -is [string]) {",
        "    if ($valor.Trim() -ne '') { $saida.Add($valor.Trim()) }",
        "    return ,$saida.ToArray()",
        "  }",
        "  foreach ($item in @($valor)) {",
        "    if ($null -eq $item) { continue }",
        "    $t = ([string]$item).Trim()",
        "    if ($t -ne '') { $saida.Add($t) }",
        "  }",
        "  return ,$saida.ToArray()",
        "}",
        "function Benikids-JsonServidores($lista) {",
        "  $arr = Benikids-Lista $lista",
        "  if ($arr.Count -eq 0) { return '[]' }",
        "  $p = New-Object System.Collections.Generic.List[string]",
        "  foreach ($s in $arr) { $p.Add('\"' + (Benikids-Esc ([string]$s)) + '\"') }",
        "  return '[' + ($p -join ',') + ']'",
        "}",
        "function Benikids-GravarAnterior($map) {",
        # Arquivo temporário, ACL, e só então o nome definitivo. Se a ACL não
        # fechar, o JSON antigo volta e a função devolve falso: o DNS não muda.
        "  $tmp = $Anterior + '.tmp'",
        "  $bak = $Anterior + '.bak'",
        "  try {",
        "    $linhas = New-Object System.Collections.Generic.List[string]",
        "    foreach ($guid in @($map.Keys)) {",
        "      $item = $map[$guid]",
        "      $i4 = $item.ipv4",
        "      $i6 = $item.ipv6",
        "      $s4 = Benikids-JsonServidores $i4.servidores",
        "      $s6 = Benikids-JsonServidores $i6.servidores",
        "      $linhas.Add('{\"guid\":\"' + (Benikids-Esc $guid) + '\",\"ipv4\":{\"modo\":\"' + (Benikids-Esc $i4.modo) + '\",\"servidores\":' + $s4 + '},\"ipv6\":{\"modo\":\"' + (Benikids-Esc $i6.modo) + '\",\"servidores\":' + $s6 + '}}')",
        "    }",
        "    $json = '{\"versao\":1,\"placas\":[' + ($linhas -join ',') + ']}'",
        "    Set-Content -LiteralPath $tmp -Value $json -Encoding UTF8 -ErrorAction Stop",
        "    $acl = Benikids-Proteger $tmp",
        "    if (-not $acl) {",
        "      Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue",
        "      Benikids-DnsLog 'nao guardou o dns anterior'",
        "      return $false",
        "    }",
        "    $tinha = Test-Path -LiteralPath $Anterior",
        "    if ($tinha) { Copy-Item -LiteralPath $Anterior -Destination $bak -Force -ErrorAction Stop }",
        "    Move-Item -LiteralPath $tmp -Destination $Anterior -Force -ErrorAction Stop",
        "    $acl2 = Benikids-Proteger $Anterior",
        "    if (-not $acl2) {",
        "      if ($tinha) {",
        "        Move-Item -LiteralPath $bak -Destination $Anterior -Force -ErrorAction SilentlyContinue",
        "        Benikids-Proteger $Anterior | Out-Null",
        "      } else {",
        "        Remove-Item -LiteralPath $Anterior -Force -ErrorAction SilentlyContinue",
        "      }",
        "      Benikids-DnsLog 'nao guardou o dns anterior'",
        "      return $false",
        "    }",
        "    if ($tinha) { Remove-Item -LiteralPath $bak -Force -ErrorAction SilentlyContinue }",
        "    return $true",
        "  } catch {",
        "    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue",
        "    Benikids-DnsLog 'nao guardou o dns anterior'",
        "    return $false",
        "  }",
        "}",
        "function Benikids-LerAnterior {",
        "  $map = @{}",
        "  if (-not (Test-Path -LiteralPath $Anterior)) { return $map }",
        "  try {",
        "    $bruto = Get-Content -LiteralPath $Anterior -Raw -Encoding UTF8 -ErrorAction Stop",
        "    if (-not $bruto) { return $map }",
        "    $obj = $bruto | ConvertFrom-Json",
        "    foreach ($item in @($obj.placas)) {",
        "      if (-not $item -or -not $item.guid) { continue }",
        "      $g = ([string]$item.guid).Trim().Trim('{}')",
        "      if ($g -eq '') { continue }",
        "      $map['{' + $g.ToUpper() + '}'] = $item",
        "    }",
        "  } catch { return $null }",
        "  return $map",
        "}",
        "function Benikids-Guid($placa) {",
        "  $g = ([string]$placa.InterfaceGuid).Trim().Trim('{}')",
        "  if ($g -eq '') { return '' }",
        "  return '{' + $g.ToUpper() + '}'",
        "}",
        "function Benikids-Nome($placa) {",
        "  $n = ([string]$placa.Name) -replace '[\\r\\n;\"]', ' '",
        "  $n = $n.Trim()",
        "  if ($n -eq '') { $n = 'placa' }",
        "  if ($n.Length -gt 60) { $n = $n.Substring(0, 60) }",
        "  return $n",
        "}",
    ]


def _linhas_funcoes_aplicar():
    """Olhar o DNS de hoje e decidir se a placa tem IPv6. Só o script que liga."""
    return [
        "function Benikids-Norm($ip) {",
        "  $t = ([string]$ip).Trim()",
        "  if ($t -eq '') { return '' }",
        "  try { return [System.Net.IPAddress]::Parse($t).IPAddressToString } catch { return $t.ToLower() }",
        "}",
        "function Benikids-EhFamilia($lista, $esperados) {",
        "  $a = Benikids-Lista $lista",
        "  $b = Benikids-Lista $esperados",
        "  if ($a.Count -ne $b.Count) { return $false }",
        "  foreach ($x in $b) {",
        "    $nx = Benikids-Norm $x",
        "    $achou = $false",
        "    foreach ($y in $a) { if ((Benikids-Norm $y) -eq $nx) { $achou = $true } }",
        "    if (-not $achou) { return $false }",
        "  }",
        "  return $true",
        "}",
        "function Benikids-Origem($guid, $familia) {",
        "  $raiz = 'Tcpip6'",
        "  if ($familia -eq 4) { $raiz = 'Tcpip' }",
        "  $modo = 'dhcp'",
        "  $lista = @()",
        "  try {",
        "    $caminho = 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\' + $raiz + '\\Parameters\\Interfaces\\' + $guid",
        "    $prop = Get-ItemProperty -Path $caminho -ErrorAction Stop",
        "    $nome = ([string]$prop.NameServer).Trim()",
        "    if ($nome -ne '') {",
        "      $modo = 'manual'",
        "      $lista = Benikids-Lista ($nome -split '[,\\s]+')",
        "    }",
        "  } catch { }",
        "  return @{ modo = $modo; servidores = $lista }",
        "}",
        "function Benikids-TemIpv6($i, $dns6) {",
        "  try {",
        "    $ips = @(Get-NetIPAddress -InterfaceIndex $i -AddressFamily IPv6 -ErrorAction SilentlyContinue | Where-Object {",
        "      $_.IPAddress -and ($_.IPAddress -notlike 'fe80:*') -and ($_.IPAddress -ne '::1')",
        "    })",
        "    if (@($ips).Count -gt 0) { return $true }",
        "  } catch { }",
        f"  $falsos = {_lista_ps(IPV6_PLACEHOLDER)}",
        "  foreach ($s in (Benikids-Lista $dns6)) {",
        "    $n = Benikids-Norm $s",
        "    if (($falsos -notcontains ([string]$s)) -and ($falsos -notcontains $n)) { return $true }",
        "  }",
        "  return $false",
        "}",
        "function Benikids-Ligado {",
        "  try {",
        f"    return ([int](Get-ItemProperty -Path $Chave -Name {_ps(VALOR)} -ErrorAction Stop).{VALOR} -eq 1)",
        "  } catch { return $false }",
        "}",
        "function Benikids-DnsAtual($i, $af) {",
        "  try {",
        "    return @(Get-DnsClientServerAddress -InterfaceIndex $i -AddressFamily $af -ErrorAction SilentlyContinue |",
        "      Select-Object -ExpandProperty ServerAddresses)",
        "  } catch { return @() }",
        "}",
    ]


def script_da_tarefa():
    """PowerShell que a tarefa agendada roda como SYSTEM. Idempotente.

    Com o registro em 1, guarda o DNS novo e aplica o filtro. Com o registro
    em 0 (ou ausente), não põe o filtro: se sobrou dns-familia-anterior.json,
    restaura as placas que voltaram a aparecer e as que ficaram em erro, e
    apaga o GUID que voltou. Placa que ainda não está na lista continua no
    arquivo. Com -Marca (ligar da área dos pais ou da instalação), deixa o
    resumo para o Python. Sem -Marca, a linha de "ligado" só sai se mudou
    alguma placa — a tarefa roda em toda rede nova e não enche o log à toa.
    """
    return "\n".join([
        "param([string]$Marca)",
        "$ErrorActionPreference = 'Continue'",
        *_linhas_variaveis(),
        *_linhas_funcoes_comuns(),
        *_linhas_funcoes_aplicar(),
        *_linhas_restaurar(),
        "$ligado = 0",
        "try {",
        f"  $ligado = [int](Get-ItemProperty -Path {_ps(CHAVE)} -Name {_ps(VALOR)} -ErrorAction Stop).{VALOR}",
        "} catch { $ligado = 0 }",
        "if ($ligado -ne 1) {",
        "  if (Test-Path -LiteralPath $Anterior) {",
        "    $resto = Benikids-RestaurarPendentes",
        "    if ($resto) {",
        "      $linha = 'desligado ' + $resto",
        "      if ($resto -match '=erro') {",
        "        if ($linha.Length -gt 330) { $linha = $linha.Substring(0, 330).TrimEnd() }",
        "        $linha = $linha + ' (uma rede nao voltou)'",
        "      }",
        "      if ($linha.Length -gt 360) { $linha = $linha.Substring(0, 360) }",
        "      Benikids-DnsLog $linha",
        "    }",
        "  }",
        "  exit 0",
        "}",
        f"$v4 = {_lista_ps(IPV4)}",
        f"$v6 = {_lista_ps(IPV6)}",
        "$map = Benikids-LerAnterior",
        "$podeGuardar = $true",
        "if ($null -eq $map) {",
        "  Benikids-DnsLog 'anterior ilegivel'",
        "  $map = @{}",
        "  $podeGuardar = $false",
        "}",
        "$placas = @(Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object { $_.Status -eq 'Up' })",
        "$partes = New-Object System.Collections.Generic.List[string]",
        "$mudou = $false",
        "$parou = $false",
        "foreach ($placa in $placas) {",
        "  if (-not (Benikids-Ligado)) { $parou = $true; break }",
        "  $i = $placa.ifIndex",
        "  $guid = Benikids-Guid $placa",
        "  $nome = Benikids-Nome $placa",
        "  if ($guid -eq '') { continue }",
        "  $atual4 = Benikids-DnsAtual $i 'IPv4'",
        "  $atual6 = Benikids-DnsAtual $i 'IPv6'",
        "  $ja4 = Benikids-EhFamilia $atual4 $v4",
        # Sem o JSON gravado e com a ACL fechada, o DNS desta placa não muda:
        # no desligar não haveria o que restaurar e o manual viraria automático.
        "  if (-not $map.ContainsKey($guid) -and -not $ja4) {",
        "    if (-not $podeGuardar) {",
        "      $partes.Add($nome + ' ipv4=erro ipv6=sem-ipv6')",
        "      Benikids-DnsLog ('placa ' + $nome + ' ipv4 erro')",
        "      continue",
        "    }",
        "    $map[$guid] = @{ ipv4 = (Benikids-Origem $guid 4); ipv6 = (Benikids-Origem $guid 6) }",
        "    if (-not (Benikids-GravarAnterior $map)) {",
        "      $map.Remove($guid) | Out-Null",
        "      $partes.Add($nome + ' ipv4=erro ipv6=sem-ipv6')",
        "      Benikids-DnsLog ('placa ' + $nome + ' ipv4 erro')",
        "      continue",
        "    }",
        "  }",
        "  if (-not (Benikids-Ligado)) { $parou = $true; break }",
        "  $r4 = 'ok'",
        "  if (-not $ja4) {",
        "    $mudou = $true",
        "    try {",
        "      Set-DnsClientServerAddress -InterfaceIndex $i -AddressFamily IPv4 -ServerAddresses $v4 -ErrorAction Stop",
        "    } catch {",
        "      $r4 = 'erro'",
        "      Benikids-DnsLog ('placa ' + $nome + ' ipv4 erro')",
        "    }",
        "  }",
        "  $r6 = 'sem-ipv6'",
        "  $temIpv6 = Benikids-TemIpv6 $i $atual6",
        "  if ($temIpv6) {",
        "    if (-not (Benikids-Ligado)) { $parou = $true; break }",
        "    $r6 = 'ok'",
        "    if (-not (Benikids-EhFamilia $atual6 $v6)) {",
        "      $mudou = $true",
        "      $ok6 = $false",
        "      try {",
        "        Set-DnsClientServerAddress -InterfaceIndex $i -AddressFamily IPv6 -ServerAddresses $v6 -ErrorAction Stop",
        "        $ok6 = $true",
        "      } catch {",
        "        Benikids-DnsLog ('placa ' + $nome + ' ipv6 sem cleanbrowsing')",
        "      }",
        "      if (-not $ok6) {",
        "        & netsh interface ipv6 set dnsservers name=\"$nome\" source=static address=\"$($v6[0])\" validate=no | Out-Null",
        "        if ($LASTEXITCODE -eq 0) {",
        "          & netsh interface ipv6 add dnsservers name=\"$nome\" address=\"$($v6[1])\" index=2 validate=no | Out-Null",
        "          $ok6 = $true",
        "        }",
        "      }",
        # Sem o CleanBrowsing, esvaziar. Reset devolveria o DNS do roteador.
        # address=none deixa a família sem servidor; as consultas ficam no IPv4.
        "      if (-not $ok6) {",
        "        $tem6 = ((Benikids-Lista $atual6) -join ',')",
        "        if ($tem6 -ne '') {",
        "          $limpo = $false",
        "          & netsh interface ipv6 set dnsservers name=\"$nome\" source=static address=none validate=no | Out-Null",
        "          if ($LASTEXITCODE -eq 0) { $limpo = $true }",
        "          if ($limpo) {",
        "            Benikids-DnsLog ('placa ' + $nome + ' ipv6 sem servidor (o do roteador nao vale)')",
        "            $r6 = 'sem-servidor'",
        "          } else {",
        "            Benikids-DnsLog ('placa ' + $nome + ' ipv6 continua com o dns anterior')",
        "            $r6 = 'erro'",
        "          }",
        "        } else {",
        "          Benikids-DnsLog ('placa ' + $nome + ' ipv6 sem servidor (o do roteador nao vale)')",
        "          $r6 = 'sem-servidor'",
        "        }",
        "      }",
        "    }",
        "  }",
        "  $partes.Add($nome + ' ipv4=' + $r4 + ' ipv6=' + $r6)",
        "}",
        "$resumo = 'ligado nenhuma placa ativa'",
        "if ($partes.Count -gt 0) { $resumo = 'ligado ' + ($partes -join '; ') }",
        "$resumo = $resumo -replace '[\\r\\n]', ' '",
        "if ($resumo.Length -gt 360) { $resumo = $resumo.Substring(0, 360) }",
        "try {",
        "  Set-Content -LiteralPath $Placas -Value $resumo -Encoding UTF8 -ErrorAction Stop",
        "  Benikids-Proteger $Placas | Out-Null",
        "} catch { }",
        "if (-not $parou -and ($Marca -or $mudou)) { Benikids-DnsLog $resumo }",
        "if ($Marca -and -not $parou) {",
        "  try {",
        "    Set-Content -LiteralPath $Resultado -Value ($Marca.Trim() + ' ' + $resumo) -Encoding UTF8 -ErrorAction Stop",
        "    Benikids-Proteger $Resultado | Out-Null",
        "  } catch { }",
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


def _linhas_gravar_ps1():
    """Grava o .ps1 e exige a ACL. Se a ACL falhar, o throw interrompe o lote."""
    return [
        f"New-Item -ItemType Directory -Force -Path {_ps(PASTA)} | Out-Null",
        "@'\n" + script_da_tarefa() + "\n'@ | Set-Content -LiteralPath " + _ps(SCRIPT) + " -Encoding UTF8",
        *linhas_acl_do_script(),
    ]


def _linhas_agendar():
    return [
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
        "  " + _linhas_log("gatilho de rede indisponivel"),
        "}",
        "$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest",
        "$ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-StartWhenAvailable -MultipleInstances IgnoreNew",
        f"Register-ScheduledTask -TaskName {_ps(TAREFA)} -Action $acao -Trigger $gatilhos "
        "-Principal $principal -Settings $ajustes -Force | Out-Null",
        _linhas_log("tarefa agendada (placa nova nao pede senha)"),
    ]


def linhas_ligar(marca=None):
    """Linhas do PowerShell elevado: grava o script, a tarefa e liga o filtro."""
    marca = _marca(marca)
    return [
        *_linhas_gravar_ps1(),
        *_linhas_agendar(),
        _linhas_chave(),
        f"New-ItemProperty -Path {_ps(CHAVE)} -Name {_ps(VALOR)} -Value 1 -PropertyType DWord -Force | Out-Null",
        *linhas_doh_navegador(True),
        _linhas_log("doh do chrome desligado"),
        f"& {_ps(SCRIPT)} -Marca {_ps(marca)}",
    ]


def linhas_atualizar_script():
    """Troca o .ps1 e a tarefa sem mudar o registro.

    Um PC que já tem DnsFamilia em 0 ou 1 não passa por linhas_ligar de novo.
    Sem isto a tarefa continua com o script antigo até os pais ligarem outra vez.
    Rodar o script no fim aplica o filtro se estiver em 1, ou restaura o que
    sobrou se estiver em 0. Não usa -Marca: não mistura com o resumo da área dos pais.
    """
    return [
        *_linhas_gravar_ps1(),
        *_linhas_agendar(),
        f"& {_ps(SCRIPT)}",
    ]


def _linhas_restaurar():
    """Devolve o DNS guardado. Manual volta com os servidores; o resto, ao automático.

    Benikids-RestaurarPendentes lê o JSON, aplica nas placas que estão na
    lista e apaga o GUID que voltou. Erro ou placa ausente continua no arquivo.
    Não mexe em placa que não está no JSON.
    """
    return [
        "function Benikids-AplicarSalvo($ifIndex, $nome, $af, $info) {",
        "  if (-not $info -or [string]$info.modo -ne 'manual') {",
        "    try {",
        "      Set-DnsClientServerAddress -InterfaceIndex $ifIndex -AddressFamily $af -ResetServerAddresses -ErrorAction Stop",
        "      return 'automatico'",
        "    } catch { return 'erro' }",
        "  }",
        "  $lista = Benikids-Lista $info.servidores",
        "  try {",
        "    if ($lista.Count -eq 0) {",
        "      Set-DnsClientServerAddress -InterfaceIndex $ifIndex -AddressFamily $af -ServerAddresses @() -ErrorAction Stop",
        "      return 'sem-servidor'",
        "    }",
        "    Set-DnsClientServerAddress -InterfaceIndex $ifIndex -AddressFamily $af -ServerAddresses $lista -ErrorAction Stop",
        "    return 'restaurado'",
        "  } catch { return 'erro' }",
        "}",
        "function Benikids-RestaurarPendentes {",
        "  $partes = New-Object System.Collections.Generic.List[string]",
        "  $map = Benikids-LerAnterior",
        "  if ($null -eq $map) { return 'anterior ilegivel' }",
        "  if ($map.Count -eq 0) { return '' }",
        "  $ficam = @{}",
        "  $vistos = @{}",
        "  $placas = @(Get-NetAdapter -ErrorAction SilentlyContinue)",
        "  foreach ($placa in $placas) {",
        "    if (-not $placa) { continue }",
        "    $guid = Benikids-Guid $placa",
        "    if ($guid -eq '' -or -not $map.ContainsKey($guid)) { continue }",
        "    $vistos[$guid] = $true",
        "    $item = $map[$guid]",
        "    $nome = Benikids-Nome $placa",
        "    $i = $placa.ifIndex",
        "    $r4 = Benikids-AplicarSalvo $i $nome 'IPv4' $item.ipv4",
        "    $r6 = Benikids-AplicarSalvo $i $nome 'IPv6' $item.ipv6",
        "    if ($r4 -eq 'erro' -or $r6 -eq 'erro') { $ficam[$guid] = $item }",
        "    $partes.Add($nome + ' ipv4=' + $r4 + ' ipv6=' + $r6)",
        "  }",
        "  foreach ($guid in @($map.Keys)) {",
        "    if (-not $vistos.ContainsKey($guid)) { $ficam[$guid] = $map[$guid] }",
        "  }",
        "  if ($ficam.Count -eq 0) {",
        "    Remove-Item -LiteralPath $Anterior -Force -ErrorAction SilentlyContinue",
        "  } else {",
        "    Benikids-GravarAnterior $ficam | Out-Null",
        "  }",
        "  if ($partes.Count -eq 0) { return '' }",
        "  return ($partes -join '; ')",
        "}",
    ]


def linhas_desligar(marca=None):
    """Linhas do PowerShell elevado: desliga o filtro e devolve o DNS de antes.

    A tarefa fica (sem UAC na próxima vez que ligar). O registro vai a 0 antes
    de restaurar, para a tarefa não recolocar o filtro no meio. Placa com
    registro volta ao que era (manual ou automático). Placa ativa sem registro
    volta ao automático. Placa desligada sem registro não é mexida.
    """
    marca = _marca(marca)
    return [
        f"New-Item -ItemType Directory -Force -Path {_ps(PASTA)} | Out-Null",
        "$ErrorActionPreference = 'Continue'",
        *_linhas_variaveis(),
        *_linhas_funcoes_comuns(),
        *_linhas_restaurar(),
        f"$Marca = {_ps(marca)}",
        _linhas_chave(),
        f"New-ItemProperty -Path {_ps(CHAVE)} -Name {_ps(VALOR)} -Value 0 -PropertyType DWord -Force -ErrorAction Stop | Out-Null",
        f"Stop-ScheduledTask -TaskName {_ps(TAREFA)} -ErrorAction SilentlyContinue",
        "Start-Sleep -Milliseconds 500",
        *linhas_doh_navegador(False),
        "$map = Benikids-LerAnterior",
        "$ilegivel = $false",
        "if ($null -eq $map) {",
        "  $ilegivel = $true",
        "  Remove-Item -LiteralPath $Anterior -Force -ErrorAction SilentlyContinue",
        "  $map = @{}",
        "}",
        "$partes = New-Object System.Collections.Generic.List[string]",
        "$placas = @(Get-NetAdapter -ErrorAction SilentlyContinue)",
        "foreach ($placa in $placas) {",
        "  if (-not $placa) { continue }",
        "  $guid = Benikids-Guid $placa",
        "  $nome = Benikids-Nome $placa",
        "  $i = $placa.ifIndex",
        "  if ($guid -eq '' -or $map.ContainsKey($guid)) { continue }",
        "  if ([string]$placa.Status -ne 'Up') { continue }",
        "  $r = 'automatico'",
        "  try {",
        "    Set-DnsClientServerAddress -InterfaceIndex $i -ResetServerAddresses -ErrorAction Stop",
        "  } catch { $r = 'erro' }",
        "  $partes.Add($nome + ' ipv4=' + $r + ' ipv6=' + $r)",
        "}",
        "$resto = ''",
        "if (-not $ilegivel) { $resto = Benikids-RestaurarPendentes }",
        "if ($resto -eq 'anterior ilegivel') { $ilegivel = $true }",
        "elseif ($resto) { $partes.Add($resto) }",
        "$resumo = 'desligado nenhuma placa'",
        "if ($partes.Count -gt 0) { $resumo = 'desligado ' + ($partes -join '; ') }",
        "if ($ilegivel) { $resumo = 'desligado anterior ilegivel ' + $resumo.Substring(10) }",
        "$resumo = $resumo -replace '[\\r\\n]', ' '",
        "if ($resumo -match '=erro') {",
        "  if ($resumo.Length -gt 330) { $resumo = $resumo.Substring(0, 330).TrimEnd() }",
        "  $resumo = $resumo + ' (uma rede nao voltou)'",
        "}",
        "if ($resumo.Length -gt 360) { $resumo = $resumo.Substring(0, 360) }",
        "Benikids-DnsLog $resumo",
        "try {",
        "  Set-Content -LiteralPath $Resultado -Value ($Marca + ' ' + $resumo) -Encoding UTF8 -ErrorAction Stop",
        "  Benikids-Proteger $Resultado | Out-Null",
        "} catch { }",
        # O script da tarefa, no disco, é o desta versão. O registro já está em 0:
        # se a gravação falhar, a restauração desta vez não se desfaz.
        "try {",
        "  New-Item -ItemType Directory -Force -Path " + _ps(PASTA) + " | Out-Null",
        "@'\n" + script_da_tarefa() + "\n'@ | Set-Content -LiteralPath " + _ps(SCRIPT) + " -Encoding UTF8 -ErrorAction Stop",
        *linhas_acl_do_script(),
        "} catch {",
        "  Benikids-DnsLog 'nao atualizou o script'",
        "}",
        f"Stop-ScheduledTask -TaskName {_ps(TAREFA)} -ErrorAction SilentlyContinue",
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


def _texto_do_script(conteudo):
    return str(conteudo or "").replace("\r\n", "\n").strip()


def precisa_atualizar_script(conteudo=None, winreg=None):
    """True se o filtro já foi configurado e o .ps1 do disco não é o desta versão.

    Sem configuração, quem grava é o ligar. Fora do Windows, sem `conteudo`: False.
    """
    if conteudo is None:
        if os.name != "nt":
            return False
        if not ler(winreg)["configurado"]:
            return False
        try:
            with open(SCRIPT, encoding="utf-8-sig") as arquivo:
                conteudo = arquivo.read()
        except OSError:
            return True
    return _texto_do_script(conteudo) != script_da_tarefa().strip()


def aplicar(ligado):
    """Pede o UAC e liga ou desliga. Devolve (terminou, resumo).

    Uma linha no beni-windows.log, com o nome da placa e o resultado. O arquivo
    de resultado só vale se a marca desta chamada estiver no começo: uma
    sobra de outra vez não entra no log. Código 0 com `=erro` no resumo não é
    senha cancelada: o aviso para os pais sai de aviso_para_os_pais.
    """
    if os.name != "nt":
        return False, ""
    import politicas_edge  # noqa: PLC0415 — o pedido de UAC mora lá
    import telemetria  # noqa: PLC0415

    marca = secrets.token_hex(8)
    linhas = linhas_ligar(marca) if ligado else linhas_desligar(marca)
    ok = bool(politicas_edge.rodar_como_admin(linhas))
    resumo = ""
    if ok:
        texto = _ler_resumo()
        prefixo = marca + " "
        if texto.startswith(prefixo):
            resumo = texto[len(prefixo):]
    telemetria.log_windows(linha_de_log(bool(ligado), resumo, ok))
    return ok, resumo


def main(args):
    if os.name != "nt" or not args or args[0] not in ("ligar", "desligar", "estado"):
        print("uso (Windows): dns_familia.py ligar | desligar | estado")
        return 2
    if args[0] == "estado":
        print("ligado" if ler()["ligado"] else "desligado")
        return 0
    ok, _resumo = aplicar(args[0] == "ligar")
    print("pronto" if ok else "não terminou (senha cancelada ou erro)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
