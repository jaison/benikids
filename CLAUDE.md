# Benikids — contexto para o Claude Code

Lançador para crianças (Windows e Linux): menu em tela cheia com jogos e apps livres,
limites de tempo, área dos pais com PIN, controle de videogame. Público: pais leigos —
baixar, instalar, a criança usa. Textos para o usuário em **português**, simples.

## Ambientes (quem faz o quê)

- **Sessão principal (Mac mini do mantenedor):** todo o contexto do projeto, código,
  commits, Releases, site e telemetria. Só ela muda o repositório.
- **claude-win** (notebook Windows 10, Remote Control): só testes no Windows. Recebe
  roteiros por SendMessage, instala o pacote do Actions, testa, manda o relatório. Não
  altera o repositório.
- **claude-linux** (Linux de teste, Remote Control): só testes no Linux, nos mesmos moldes.
- Roteiro de cada agente de teste: [docs/AGENTES-DE-TESTE.md](docs/AGENTES-DE-TESTE.md).
  Mande roteiros completos (o agente não tem o contexto da sessão principal): o que mudou,
  passo a passo, o que medir, o formato do relatório, e "não altere o repositório".

## Mapa do código

- `src/server.py` — servidor local (Python, sem dependências), API `/api/*`, o mesmo nos
  dois sistemas. `src/index.html` + `src/frontend/` — menu web. `src/configurar.html` —
  configuração inicial em 3 passos.
- `cliente/` — menu nativo `beni-menu` (Rust + gpui-fast; o suporte a Intel HD 2000
  veio do nosso PR longbridge/gpui-fast#141, na 0.1.16; `cliente/vendor/` só recusa o llvmpipe).
- Windows: `src/beni_windows.py` (iniciador), `src/catalogo/windows.json` +
  `src/catalogo_windows.py` (catálogo, uma entrada por linha — edite com cuidado para não
  reformatar), `src/instalar_apps.py` (winget, download direto, pasta do KDE),
  `src/atualizar_windows.py` (atualização pelas Releases), `scripts/windows/`.
- Linux: `beni/` (instalação, wrappers em `beni/bin/`, `beni/config/config.json` +
  `beni/config/migracoes.json` para jogos novos em notebooks já instalados,
  `beni/sistema/beni-atualizar`).
- `telemetria/` — Cloudflare Worker + D1 (`telemetria.benikids.app`); `site/` — benikids.app
  (Cloudflare Pages). Privacidade: `docs/PRIVACY.md`.

## Testes

- Unitários: `python3 -m unittest discover -s tests` (~2,5 min).
- Navegador: `python3 scripts/wsl/browser-e2e.py --artifacts <pasta>` (precisa de Chromium
  no PATH como `chromium` e do pacote `websocket-client`). O CI roda os dois.
- Menu nativo: `cd cliente && cargo test --release` (o CI compila Linux e Windows).
- O pacote do Windows sai do workflow "Menu nativo" (artefato `Beni-Windows`); sem login:
  `https://nightly.link/jaison/benikids/actions/runs/<id>/Beni-Windows.zip`.

## Publicar

- **Release** (chega sozinha aos notebooks Linux e, desde a 1.0.5, aos Windows): ponha a
  versão em `VERSION`, commit "Versão X.Y.Z", tag anotada `vX.Y.Z`, push, depois
  `gh release create vX.Y.Z --title X.Y.Z --notes "..."`. O CI anexa o menu nativo do Linux
  e o `Benikids-Windows.zip` (+ `.sha256`). `[forcar]` nas notas instala na hora no Linux.
  (`docs/RELEASING.md` é do projeto original e não vale para o Benikids.)
- **Cloudflare** (Worker, D1, Pages): token em `~/.config/benikids-cloudflare.env`
  (`CLOUDFLARE_API_TOKEN`, chmod 600) e `CLOUDFLARE_ACCOUNT_ID` exportado (sem ele, erro
  9106). Comandos em `telemetria/LEIA-ME.md`; site: `npx wrangler@3 pages deploy site
  --project-name benikids --branch main`. Nunca mostre o token em respostas ou comandos.
- Problemas da telemetria viram Issues com a etiqueta `telemetria` (cron diário 03:17 UTC).

## Regras

- Commits e mensagens em português, explicando o porquê. Nada de dados pessoais (nomes
  das crianças, e-mail, localização) no repositório, que é público. `node_modules/` fica
  fora do git.
- Jogos novos: só livres e leves, que rodem em notebook antigo (Celeron, 2–4 GB, Intel HD).
  No Linux, wrapper em `beni/bin/` (tela cheia, idioma, sem internet) + migração; no
  Windows, entrada no catálogo (exe, escopo, tipo de instalador, args).
- Teste em máquina real (claude-win / claude-linux) antes de dizer que algo funciona no
  Windows ou no Linux.
