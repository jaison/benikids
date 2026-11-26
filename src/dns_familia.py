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
guarda o DNS daquela placa e aplica o filtro. Só com o registro em 1. Com
o registro em 0 a tarefa não existe (o desligar tira) e o script, se ainda
rodar, não lê o JSON: não recoloca o DNS antigo. Placa virtual (Tailscale)
não entra no filtro.

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
            "Uma rede ficou como estava: o filtro não entrou nela. "
            "Pode tentar de novo."
        )
    return (
        "O filtro foi desligado, mas uma rede não voltou ao DNS de antes. "
        "Pode tentar de novo."
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
        "function Benikids-Motivo($err) {",
        "  $t = ''",
        "  try {",
        "    if ($err -and $err.Exception -and $err.Exception.Message) { $t = [string]$err.Exception.Message }",
        "  } catch { }",
        "  if (-not $t) { try { $t = [string]$err } catch { $t = '' } }",
        "  $t = ($t -replace '[\\r\\n;=]', ' ').Trim()",
        "  if ($t.Length -gt 120) { $t = $t.Substring(0, 120).Trim() }",
        "  if ($t -eq '') { $t = 'sem mensagem' }",
        "  return $t",
        "}",
        # O if (-not (funcao)) junta tudo o que a funcao escreveu. Um comando no
        # meio (icacls, Copy-Item) vira array: o bool do fim se perde. O ultimo
        # valor e a bandeira $script: sao o que vale.
        "function Benikids-Ultimo($valor) {",
        "  $arr = @($valor)",
        "  if ($arr.Count -eq 0) { return $null }",
        "  return $arr[$arr.Count - 1]",
        "}",
        "function Benikids-Proteger($caminho) {",
        "  $script:BenikidsProtegeu = $false",
        "  $saida = & icacls \"$caminho\" /inheritance:r /grant:r "
        f"'*{_SID_SYSTEM}:(F)' '*{_SID_ADMINS}:(F)' '*{_SID_USUARIOS}:(R)' 2>&1 | Out-String",
        "  $codigo = $LASTEXITCODE",
        "  $texto = ([string]$saida).Trim()",
        "  $ok = $false",
        "  if ($codigo -eq 0) { $ok = $true }",
        "  elseif ($null -eq $codigo -and $texto -match 'Successfully processed') { $ok = $true }",
        "  if (-not $ok) {",
        "    Benikids-DnsLog ('acl do arquivo de dns falhou: ' + (Benikids-Motivo $texto))",
        "    return $false",
        "  }",
        "  $script:BenikidsProtegeu = $true",
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
        # fechar, o JSON antigo volta e a bandeira fica falsa: o DNS não muda.
        # O return sozinho não basta: outro comando no meio da função escreve no
        # output e o if (-not (funcao)) vê um array. A bandeira é o resultado.
        # Move-Item -Force não substitui arquivo no Windows PowerShell 5.1: na
        # segunda placa o JSON novo não entrava e a função caía no catch.
        "  $script:BenikidsGravou = $false",
        "  $script:BenikidsErro = ''",
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
        "      [void]$linhas.Add('{\"guid\":\"' + (Benikids-Esc $guid) + '\",\"ipv4\":{\"modo\":\"' + (Benikids-Esc $i4.modo) + '\",\"servidores\":' + $s4 + '},\"ipv6\":{\"modo\":\"' + (Benikids-Esc $i6.modo) + '\",\"servidores\":' + $s6 + '}}')",
        "    }",
        "    $json = '{\"versao\":1,\"placas\":[' + ($linhas -join ',') + ']}'",
        "    $utf = New-Object System.Text.UTF8Encoding $true",
        "    [System.IO.File]::WriteAllText($tmp, $json, $utf)",
        "    Benikids-Proteger $tmp | Out-Null",
        "    if (-not $script:BenikidsProtegeu) { throw 'acl do arquivo de dns falhou' }",
        "    $tinha = Test-Path -LiteralPath $Anterior",
        "    if ($tinha) {",
        "      [System.IO.File]::Copy($Anterior, $bak, $true)",
        "      Remove-Item -LiteralPath $Anterior -Force -ErrorAction Stop",
        "    }",
        "    Move-Item -LiteralPath $tmp -Destination $Anterior -ErrorAction Stop",
        "    Benikids-Proteger $Anterior | Out-Null",
        "    if (-not $script:BenikidsProtegeu) { throw 'acl do arquivo de dns falhou' }",
        "    if ($tinha) { Remove-Item -LiteralPath $bak -Force -ErrorAction SilentlyContinue }",
        "    $script:BenikidsErro = ''",
        "    $script:BenikidsGravou = $true",
        "    return $true",
        "  } catch {",
        "    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue",
        "    if (-not (Test-Path -LiteralPath $Anterior) -and (Test-Path -LiteralPath $bak)) {",
        "      Move-Item -LiteralPath $bak -Destination $Anterior -ErrorAction SilentlyContinue",
        "      Benikids-Proteger $Anterior | Out-Null",
        "    }",
        "    $script:BenikidsErro = Benikids-Motivo $_",
        "    Benikids-DnsLog ('nao guardou o dns anterior: ' + $script:BenikidsErro)",
        "    $script:BenikidsGravou = $false",
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
        # Tailscale, Wintun e outras virtuais não aceitam o DNS do Windows.
        # O erro delas não pode fazer a placa real (Wi-Fi, Ethernet) parecer que falhou.
        "function Benikids-Virtual($placa) {",
        "  try {",
        "    if ($placa.HardwareInterface -eq $false) { return $true }",
        "    if ($placa.Virtual -eq $true) { return $true }",
        "  } catch { }",
        "  $n = ([string]$placa.InterfaceDescription) + ' ' + ([string]$placa.Name)",
        "  if ($n -match 'Tailscale|Wintun|WireGuard') { return $true }",
        "  return $false",
        "}",
        "function Benikids-NetshEstatico($nome, $familia, $lista) {",
        "  $arr = @(Benikids-Lista $lista)",
        "  if ($arr.Count -eq 0) {",
        "    & netsh interface $familia set dnsservers name=\"$nome\" source=static address=none validate=no | Out-Null",
        "    return ($LASTEXITCODE -eq 0)",
        "  }",
        "  $primeiro = [string]$arr[0]",
        "  & netsh interface $familia set dnsservers name=\"$nome\" source=static address=\"$primeiro\" validate=no | Out-Null",
        "  if ($LASTEXITCODE -ne 0) { return $false }",
        "  $n = 2",
        "  foreach ($extra in ($arr | Select-Object -Skip 1)) {",
        "    & netsh interface $familia add dnsservers name=\"$nome\" address=\"$extra\" index=$n validate=no | Out-Null",
        "    $n++",
        "  }",
        "  return $true",
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
        # Set-DnsClientServerAddress às vezes recusa (placa já no estado, ou o
        # cmdlet falha) e o DNS não muda. O netsh com validate=no é o plano B.
        # Se o registro já está certo, não é erro.
        "function Benikids-FixarIpv4($i, $nome, $guid, $esperados) {",
        "  $script:BenikidsErro = ''",
        "  try {",
        "    Set-DnsClientServerAddress -InterfaceIndex $i -AddressFamily IPv4 -ServerAddresses $esperados -ErrorAction Stop",
        "  } catch {",
        "    $script:BenikidsErro = Benikids-Motivo $_",
        "    Benikids-DnsLog ('placa ' + $nome + ' ipv4: ' + $script:BenikidsErro)",
        "  }",
        "  $o = Benikids-Origem $guid 4",
        "  if (($o.modo -eq 'manual') -and (Benikids-EhFamilia $o.servidores $esperados)) {",
        "    $script:BenikidsErro = ''",
        "    return 'ok'",
        "  }",
        "  $net = Benikids-Ultimo (Benikids-NetshEstatico $nome 'ipv4' $esperados)",
        "  if ($net -eq $true) {",
        "    $o = Benikids-Origem $guid 4",
        "    if (($o.modo -eq 'manual') -and (Benikids-EhFamilia $o.servidores $esperados)) {",
        "      $script:BenikidsErro = ''",
        "      return 'ok'",
        "    }",
        "  }",
        "  if ($script:BenikidsErro -eq '') { $script:BenikidsErro = 'nao aplicou o dns' }",
        "  return 'erro'",
        "}",
    ]


def script_da_tarefa():
    """PowerShell que a tarefa agendada roda como SYSTEM. Idempotente.

    Com o registro em 1, guarda o DNS novo e aplica o filtro. Com o registro
    em 0 (ou ausente), não põe o filtro e não lê o JSON: uma tarefa antiga
    recolocava o DNS manual por cima do automático que a pessoa acabou de
    escolher. Com -Marca (ligar da área dos pais ou da instalação), deixa o
    resumo para o Python. Sem -Marca, a linha de "ligado" só sai se mudou
    alguma placa — a tarefa roda em toda rede nova e não enche o log à toa.
    """
    return "\n".join([
        "param([string]$Marca)",
        "$ErrorActionPreference = 'Continue'",
        *_linhas_variaveis(),
        *_linhas_funcoes_comuns(),
        *_linhas_funcoes_aplicar(),
        "$ligado = 0",
        "try {",
        f"  $ligado = [int](Get-ItemProperty -Path {_ps(CHAVE)} -Name {_ps(VALOR)} -ErrorAction Stop).{VALOR}",
        "} catch { $ligado = 0 }",
        # Desligado: não restaura o JSON. Isso recolocava o DNS antigo (manual
        # 1.1.1.1, por exemplo) depois que a pessoa voltou a placa ao automático.
        "if ($ligado -ne 1) {",
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
        "  $nome = Benikids-Nome $placa",
        "  if ((Benikids-Ultimo (Benikids-Virtual $placa)) -eq $true) {",
        "    if ($Marca) { Benikids-DnsLog ('placa ' + $nome + ' virtual, sem mexer') }",
        "    continue",
        "  }",
        "  $i = $placa.ifIndex",
        "  $guid = Benikids-Guid $placa",
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
        "    Benikids-GravarAnterior $map | Out-Null",
        "    if (-not $script:BenikidsGravou) {",
        "      $map.Remove($guid) | Out-Null",
        "      $linha = $nome + ' ipv4=erro ipv6=sem-ipv6'",
        "      if ($script:BenikidsErro) { $linha = $linha + ' (' + $script:BenikidsErro + ')' }",
        "      $partes.Add($linha)",
        "      Benikids-DnsLog ('placa ' + $nome + ' ipv4 erro: ' + $script:BenikidsErro)",
        "      continue",
        "    }",
        "  }",
        "  if (-not (Benikids-Ligado)) { $parou = $true; break }",
        "  $r4 = 'ok'",
        "  $e4 = ''",
        "  if (-not $ja4) {",
        "    $mudou = $true",
        "    $r4 = [string](Benikids-Ultimo (Benikids-FixarIpv4 $i $nome $guid $v4))",
        "    $e4 = [string]$script:BenikidsErro",
        "    if ($r4 -ne 'ok') { $r4 = 'erro' }",
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
        "        Benikids-DnsLog ('placa ' + $nome + ' ipv6 sem cleanbrowsing: ' + (Benikids-Motivo $_))",
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
        "  $p4 = $r4",
        "  if ($r4 -eq 'erro' -and $e4 -ne '') { $p4 = 'erro (' + $e4 + ')' }",
        "  $partes.Add($nome + ' ipv4=' + $p4 + ' ipv6=' + $r6)",
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
    Com o filtro em 1, roda o script (aplica nas placas reais). Com o filtro em 0,
    tira a tarefa: ela não recoloca o DNS do JSON. Não usa -Marca.
    """
    return [
        *_linhas_gravar_ps1(),
        "try {",
        f"  $ligado = [int](Get-ItemProperty -Path {_ps(CHAVE)} -Name {_ps(VALOR)} -ErrorAction Stop).{VALOR}",
        "} catch { $ligado = 0 }",
        # Desligado: não recria a tarefa. Ela reaplicaria o JSON antigo.
        "if ($ligado -eq 1) {",
        *_linhas_agendar(),
        f"  & {_ps(SCRIPT)}",
        "} else {",
        f"  Unregister-ScheduledTask -TaskName {_ps(TAREFA)} -Confirm:$false -ErrorAction SilentlyContinue",
        "}",
    ]


def _linhas_restaurar():
    """Devolve o DNS guardado. Manual volta com os servidores; o resto, ao automático.

    Benikids-RestaurarPendentes lê o JSON, aplica nas placas que estão na
    lista e apaga o GUID que voltou. Erro ou placa ausente continua no arquivo.
    Não mexe em placa que não está no JSON.
    """
    return [
        "function Benikids-AplicarSalvo($ifIndex, $nome, $af, $info, $guid) {",
        # Já está no estado guardado: não chama o cmdlet. No Windows sem IPv6,
        # o reset do IPv6 falha e o desligar marcava erro mesmo com o IPv4 certo.
        "  $script:BenikidsErro = ''",
        "  $familia = 6",
        "  $net = 'ipv6'",
        "  if ($af -eq 'IPv4') { $familia = 4; $net = 'ipv4' }",
        "  $manual = ($info -and [string]$info.modo -eq 'manual')",
        "  $lista = @()",
        "  if ($manual) { $lista = @(Benikids-Lista $info.servidores) }",
        "  $origem = Benikids-Origem $guid $familia",
        "  if (-not $manual) {",
        "    if ($origem.modo -eq 'dhcp') { return 'automatico' }",
        "  } elseif ($origem.modo -eq 'manual' -and (Benikids-EhFamilia $origem.servidores $lista)) {",
        "    if ($lista.Count -eq 0) { return 'sem-servidor' }",
        "    return 'restaurado'",
        "  }",
        "  try {",
        "    if (-not $manual) {",
        "      Set-DnsClientServerAddress -InterfaceIndex $ifIndex -AddressFamily $af -ResetServerAddresses -ErrorAction Stop",
        "    } else {",
        "      Set-DnsClientServerAddress -InterfaceIndex $ifIndex -AddressFamily $af -ServerAddresses $lista -ErrorAction Stop",
        "    }",
        "  } catch {",
        "    $script:BenikidsErro = Benikids-Motivo $_",
        "    Benikids-DnsLog ('placa ' + $nome + ' ' + $net + ': ' + $script:BenikidsErro)",
        "  }",
        "  $origem = Benikids-Origem $guid $familia",
        "  if (-not $manual -and $origem.modo -eq 'dhcp') { $script:BenikidsErro = ''; return 'automatico' }",
        "  if ($manual -and $origem.modo -eq 'manual' -and (Benikids-EhFamilia $origem.servidores $lista)) {",
        "    $script:BenikidsErro = ''",
        "    if ($lista.Count -eq 0) { return 'sem-servidor' }",
        "    return 'restaurado'",
        "  }",
        "  $netOk = $false",
        "  if (-not $manual) {",
        "    & netsh interface $net set dnsservers name=\"$nome\" source=dhcp | Out-Null",
        "    $netOk = ($LASTEXITCODE -eq 0)",
        "  } else {",
        "    $netOk = ((Benikids-Ultimo (Benikids-NetshEstatico $nome $net $lista)) -eq $true)",
        "  }",
        "  if ($netOk) {",
        "    $origem = Benikids-Origem $guid $familia",
        "    if (-not $manual -and $origem.modo -eq 'dhcp') { $script:BenikidsErro = ''; return 'automatico' }",
        "    if ($manual -and $origem.modo -eq 'manual' -and (Benikids-EhFamilia $origem.servidores $lista)) {",
        "      $script:BenikidsErro = ''",
        "      if ($lista.Count -eq 0) { return 'sem-servidor' }",
        "      return 'restaurado'",
        "    }",
        "  }",
        "  if ($af -eq 'IPv6') {",
        "    $tem = Benikids-Ultimo (Benikids-TemIpv6 $ifIndex $null)",
        "    if ($tem -ne $true) { $script:BenikidsErro = ''; return 'sem-ipv6' }",
        "  }",
        "  if ($script:BenikidsErro -eq '') { $script:BenikidsErro = 'nao voltou' }",
        "  return 'erro'",
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
        "    $nome = Benikids-Nome $placa",
        "    if ((Benikids-Ultimo (Benikids-Virtual $placa)) -eq $true) {",
        # Tenta devolver, mas não segura o JSON nem o resumo: o erro da
        # Tailscale não pode fazer o Wi-Fi parecer que não voltou.
        "      if ($guid -ne '' -and $map.ContainsKey($guid)) {",
        "        $vistos[$guid] = $true",
        "        $item = $map[$guid]",
        "        $i = $placa.ifIndex",
        "        $rv4 = [string](Benikids-Ultimo (Benikids-AplicarSalvo $i $nome 'IPv4' $item.ipv4 $guid))",
        "        $rv6 = [string](Benikids-Ultimo (Benikids-AplicarSalvo $i $nome 'IPv6' $item.ipv6 $guid))",
        "        Benikids-DnsLog ('placa ' + $nome + ' virtual ipv4=' + $rv4 + ' ipv6=' + $rv6)",
        "      }",
        "      continue",
        "    }",
        "    if ($guid -eq '' -or -not $map.ContainsKey($guid)) { continue }",
        "    $vistos[$guid] = $true",
        "    $item = $map[$guid]",
        "    $i = $placa.ifIndex",
        "    $script:BenikidsErro = ''",
        "    $r4 = [string](Benikids-Ultimo (Benikids-AplicarSalvo $i $nome 'IPv4' $item.ipv4 $guid))",
        "    $e4 = [string]$script:BenikidsErro",
        "    $script:BenikidsErro = ''",
        "    $r6 = [string](Benikids-Ultimo (Benikids-AplicarSalvo $i $nome 'IPv6' $item.ipv6 $guid))",
        "    $e6 = [string]$script:BenikidsErro",
        "    if ($r4 -eq 'erro' -or $r6 -eq 'erro') { $ficam[$guid] = $item }",
        "    $p4 = $r4",
        "    $p6 = $r6",
        "    if ($r4 -eq 'erro' -and $e4 -ne '') { $p4 = 'erro (' + $e4 + ')' }",
        "    if ($r6 -eq 'erro' -and $e6 -ne '') { $p6 = 'erro (' + $e6 + ')' }",
        "    [void]$partes.Add($nome + ' ipv4=' + $p4 + ' ipv6=' + $p6)",
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

    O registro vai a 0 e a tarefa sai antes de restaurar, para ela não recolocar
    o DNS no meio. Placa com registro volta ao que era (manual ou automático).
    Placa ativa sem registro volta ao automático. Placa virtual não entra.
    Placa desligada sem registro não é mexida.
    """
    marca = _marca(marca)
    return [
        f"New-Item -ItemType Directory -Force -Path {_ps(PASTA)} | Out-Null",
        "$ErrorActionPreference = 'Continue'",
        *_linhas_variaveis(),
        *_linhas_funcoes_comuns(),
        *_linhas_funcoes_aplicar(),
        *_linhas_restaurar(),
        f"$Marca = {_ps(marca)}",
        _linhas_chave(),
        f"New-ItemProperty -Path {_ps(CHAVE)} -Name {_ps(VALOR)} -Value 0 -PropertyType DWord -Force -ErrorAction Stop | Out-Null",
        f"Stop-ScheduledTask -TaskName {_ps(TAREFA)} -ErrorAction SilentlyContinue",
        f"Unregister-ScheduledTask -TaskName {_ps(TAREFA)} -Confirm:$false -ErrorAction SilentlyContinue",
        "Start-Sleep -Milliseconds 500",
        # Troca o .ps1 antes de restaurar. Se a tarefa não saiu, o script novo
        # vê o registro em 0 e não recoloca o DNS do JSON.
        "try {",
        "  New-Item -ItemType Directory -Force -Path " + _ps(PASTA) + " | Out-Null",
        "@'\n" + script_da_tarefa() + "\n'@ | Set-Content -LiteralPath " + _ps(SCRIPT) + " -Encoding UTF8 -ErrorAction Stop",
        *linhas_acl_do_script(),
        "} catch {",
        "  Benikids-DnsLog 'nao atualizou o script'",
        "}",
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
        "  $nome = Benikids-Nome $placa",
        "  if ((Benikids-Ultimo (Benikids-Virtual $placa)) -eq $true) { continue }",
        "  $guid = Benikids-Guid $placa",
        "  $i = $placa.ifIndex",
        "  if ($guid -eq '' -or $map.ContainsKey($guid)) { continue }",
        "  if ([string]$placa.Status -ne 'Up') { continue }",
        "  $script:BenikidsErro = ''",
        "  $r4 = [string](Benikids-Ultimo (Benikids-AplicarSalvo $i $nome 'IPv4' $null $guid))",
        "  $e4 = [string]$script:BenikidsErro",
        "  $script:BenikidsErro = ''",
        "  $r6 = [string](Benikids-Ultimo (Benikids-AplicarSalvo $i $nome 'IPv6' $null $guid))",
        "  $e6 = [string]$script:BenikidsErro",
        "  $p4 = $r4",
        "  $p6 = $r6",
        "  if ($r4 -eq 'erro' -and $e4 -ne '') { $p4 = 'erro (' + $e4 + ')' }",
        "  if ($r6 -eq 'erro' -and $e6 -ne '') { $p6 = 'erro (' + $e6 + ')' }",
        "  $partes.Add($nome + ' ipv4=' + $p4 + ' ipv6=' + $p6)",
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
