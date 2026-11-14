# Agentes de teste (claude-win, claude-linux)

Sessões do Claude Code nas máquinas de teste, ligadas por Remote Control. A sessão
principal manda um roteiro por SendMessage; o agente executa e responde com o relatório.

## Regras para os dois

- **Não altere o repositório** nem faça commits: só a sessão principal muda o código.
- Não instale nada que peça senha de administrador sem o mantenedor estar na frente do
  computador. Peça para ninguém mexer no mouse durante um teste.
- Relatório: o que foi testado, OK/falhou por item, prints (caminho), trechos de log
  relevantes, e o que ficou pendente. Tabela quando forem muitos apps:
  `app | instalou | abriu | tela cheia | idioma | obs`.
- Ao investigar um problema, diga a causa confirmada separada da suspeita.

## claude-win (Windows)

- Pacote: artefato `Beni-Windows` do workflow "Menu nativo" (link nightly.link no roteiro).
  Extrair numa pasta nova e rodar `Instalar Benikids.cmd` no usuário da criança.
- Instalado em `%USERPROFILE%\.local\share\cozy-kids-launcher`; config em
  `%USERPROFILE%\.config\cozy-kids-launcher\config.json`; logs em
  `%USERPROFILE%\.cache\cozy-kids-launcher\` (`beni-windows.log`, `menu-nativo.log`).
  Dados por app (SuperTux etc.): `C:\ProgramData\Benikids\dados\<usuário>\<app>`.
  Problemas na fila: `problemas-pendentes.jsonl`.
- Prints em tela cheia exclusiva saem pretos: descreva o que se vê ou peça ao mantenedor.

## claude-linux (Linux)

- Base parecida com a dos notebooks: Linux Mint 22 / Ubuntu 24.04 (os notebooks reais são
  antigos: Celeron, 2–4 GB, Intel HD 2000–4000; anote quando o teste é em máquina mais forte).
- Instalação de teste: `./instalar.sh` do repositório clonado (só leitura) numa conta de
  criança; atualizador em `/usr/local/sbin/beni-atualizar` (`verificar`, `aplicar`,
  `estado`).
- Testar wrappers de jogos (`beni/bin/`) como o usuário da criança na sessão gráfica
  (`DISPLAY=:0`); medir com `xdotool` (janela/tamanho) e `scrot` (print).
- Pacotes só para teste: guarde `dpkg --get-selections` antes, instale, e no fim remova
  exatamente a diferença, deixando o sistema como estava.
