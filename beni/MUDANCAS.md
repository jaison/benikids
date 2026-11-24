# Mudanças em relação ao Cozy Kids Launcher 0.6.0

Base: [TrissyGE/cozy-kids-launcher](https://github.com/TrissyGE/cozy-kids-launcher), commit `91b7157`
(02/09/2026). Para ver o diff completo: `git diff 91b7157 -- src scripts tests`.

> Os arquivos `src/index.html`, `src/frontend/state.js` e outros com textos eram **modelos**
> (`{{JSON_ADMIN_TITLE}}`…) que o `scripts/install.sh` preenchia. Aqui eles foram copiados da
> instalação real, já preenchidos e traduzidos. Por isso o diff desses arquivos é grande, mesmo
> quando a lógica mudou pouco.

## Arquivos novos (`src/`)
| Arquivo | Para quê |
|---|---|
| `itch_sync.py`, `jogo.html` | Coleções públicas do itch.io nos dois sistemas. A thread do servidor sincroniza 2 min depois de subir e a cada 30 min. Menina → coleção bea, menino → coleção beni; uma entrada em `itch-colecoes.json` (id do perfil) manda sobre o gênero; perfil sem gênero não recebe coleção. Jogo novo entra ligado em Jogar; visível, categoria e nome escolhidos pelos pais ficam; jogo que saiu some. No Windows o tile abre o Edge em quiosque na moldura local `jogo.html` em file:// (origem opaca; o mesmo arquivo de `beni/chromium/cozy-jogo.html`). O config guarda `benikids-jogo:#…`; o caminho, com acento e espaço codificados, só é montado na abertura. `http://127.0.0.1/jogo.html` faz o itch.io cair na página anti-hotlink. No Linux o `cozy-itch-sync` virou um invólucro dessa lógica. Capas em `themes/covers`, emoji `img:covers/…` (o menu nativo e o menu web já mostram). |
| `usage_limits.py` | Limite diário por perfil e por categoria (`jogos`, `educativo`, …). Conta o tempo só com o app aberto, grava em `~/.local/state/cozy-kids-launcher/usage-today.json`, zera à meia-noite, bloqueia tiles e fecha o app que passar do limite. Uma categoria pode dividir o limite de outra (`"pool": "jogos"`): o **Passatempo** gasta dos mesmos minutos dos Jogos. Opcional: limite diferente em cada dia da semana (`categoryLimits.weekdays.{mon..sun}`; campo ausente = usa o padrão, `null` = sem limite). Opcional: **regra de aprendizado** (`categoryLimits.learningRule`, ver abaixo); para ela o mesmo arquivo guarda um histórico curto por perfil (`history`, últimos 14 dias, só segundos por categoria; continua `usageVersion: 1`, então uma versão antiga só ignora o campo). |
| `frontend/usage-limits.js` / `.css` | Medidores na barra de baixo, mensagens de "tempo acabou" e painel em Pais → Tempo de tela (com a tabela Seg–Dom de "Tempo diferente em cada dia da semana" e o quadro da regra de aprendizado com a linha "Hoje: Jogar reduzido para 15 min porque…"). |
| `frontend/escolha.js` / `.css` | Tela inicial "O que você quer fazer? Aprender / Passatempo / Jogar" e lista filtrada por categoria (o Passatempo só aparece se o perfil tiver essa categoria). Com a regra de aprendizado valendo, Jogar/Passatempo mostram "Hoje 15 min — ontem faltou aprender 📚" e a barrinha começa pela metade; o Aprender mostra quanto falta para a meta de hoje. |
| `site_logins.py`, `frontend/site-logins.js` / `.css` | Login automático nos sites (Khan Academy e Teach Your Monster, aba "Home" da conta de família) por perfil. Pais → Crianças → "🔑 Login automático nos sites" grava e-mail/usuário e senha em `~/.config/cozy-kids-launcher/site-logins.json` (600, fora do config.json; a senha nunca volta para a página). Ao abrir o Khan, o Firefox sobe com o Marionette (controle remoto do próprio Firefox, porta 28290, só nesse tile) e uma thread preenche o login e clica em Entrar; se já estiver logado, não digita nada. Endpoints `GET`/`POST /api/site-logins` (só pais). |
| `controles.py`, `frontend/controles.js` / `.css` | Controles USB (gamepads). Lê os controles direto do kernel (`/dev/input/eventN`, sem bibliotecas). Em Pais → Sistema → "🎮 Controles", um assistente pede cada botão (direcional, ✕ ◯ □ △, L1/R1/L2/R2, Select/Start e analógicos, que podem ser pulados) e grava em `~/.config/cozy-kids-launcher/controles.json`, guardando os códigos do kernel. A partir disso gera `SDL_GAMECONTROLLERCONFIG` para os jogos SDL abertos pelo menu, o perfil do RetroArch em `~/.config/cozy-jogos/autoconfig/beni-<vendor>-<produto>.cfg` e o `~/.pcsxr/plugins/dfinput.cfg` (jogador 1 e 2 na ordem em que os controles foram ligados). O controle também navega no menu (direcional = setas, ✕ = Enter, ◯ = Esc, via `xdotool`), só com a janela do menu na frente e nenhum app aberto; sem configuração, só o direcional funciona. **Saída de emergência:** Start + Select seguros por 2 s fecham o app aberto e voltam ao menu, como o ✕ do overlay. Nos jogos de navegador (Chromium), a extensão `beni/chromium/controle/` (instalada em `~/.var/app/org.chromium.Chromium/cozy-controle`, com `mapa.js` gerado pelo servidor) entrega os controles no formato "standard" da Gamepad API; nos jogos Unity, o direcional também move o analógico. O `instalar.sh` libera `/run/udev` para o Chromium do flatpak, sem o que ele não vê nenhum controle. Tile com `"gamepad": true` ganha o selo 🎮 (Pais → Sistema → Controles). Endpoints `GET /api/controles`, `GET /api/controles/captura` e `POST /api/controles/{captura,salvar,esquecer,navegacao}`, todos só para os pais. |
| `frontend/cozy-temas.css` | Temas heroi, blocos, ninja, gelo, casinha e castelo; estilos da prévia; capas de jogos nos tiles. |
| `frontend/locales/pt.json` | Português do Brasil (todas as 237 chaves do inglês). |
| `sites/phet.html` | Pré-tela do tile "Ciências (PhET)": Física, Matemática, Química, Terra e Espaço e Biologia. Cada uma abre o PhET já filtrado no Ensino Fundamental 1 (para mudar o nível, troque `NIVEL` no arquivo). Servida pelo próprio launcher em `http://127.0.0.1:38431/sites/phet.html`. |
| `../themes/*.svg`, `../themes/fonts/` | Fundos dos temas novos e fontes (OFL). |

## Menu nativo (`cliente/`) e desempenho
A tela das crianças passou a ser um programa nativo em Rust (`cliente/`, `beni-menu`, com gpui-fast),
no lugar do Firefox em quiosque. A área dos pais continua no navegador. Detalhes, medições e como
compilar: [cliente/LEIA-ME.md](../cliente/LEIA-ME.md).

| Arquivo | Mudança |
|---|---|
| `cliente/` | O menu nativo. `vendor/gpui-fast-wgpu` é o gpui-fast-wgpu 0.1.14 com patch para GL sem compute (Intel HD 2000) e emojis coloridos (`vendor/LEIA-ME.md`). |
| `src/cliente.html`, `src/frontend/cliente-nativo.js` | Páginas abertas pelo menu nativo (área dos pais, sites embutidos, biblioteca de mídia): marcam a aba e, quando voltariam para o menu, avisam o servidor para o menu nativo fechar o navegador. Com `?pais=1`, abre direto a área dos pais. Sem a marca da aba, não fazem nada. |
| `src/server.py` | `GET /api/cliente/estado` e `POST /api/cliente/voltar`. **Cache** da configuração lida (`load_cfg`/`load_stored_cfg`): só relê, migra e valida quando o `config.json` ou o `recommendations.json` mudam; antes eram ~12 ms por requisição num Celeron. `load_recommendations(check_installed=False)`: a configuração não procura mais ~40 programas no PATH a cada requisição. |
| `src/controles.py` | O `controles.json` é lido só quando muda; o Start+Select não lê nada quando ninguém segura dois botões; com só "ruído" de analógico (o DragonRise manda dezenas de eventos por segundo), a thread acorda no máximo 10×/s. |
| `beni/bin/cozy-kids-launcher` | Abre o `beni-menu` (se instalado e sem `~/.config/cozy-kids-launcher/menu` = `web`) e volta para o navegador quando ele sai com 75 (sem GPU), cai logo no começo ou cai 3 vezes. Checagem dos processos em bash puro (`process_alive_rapido`, igual ao `process_state.py alive`) e espera de 1 s sem processo externo: o laço gastava ~18% de um núcleo. |
| `beni/bin/cozy-carregando` | Também reconhece a janela `beni-menu`. |
| `beni/sistema/beni-atualizar` | Baixa `beni-menu-linux-x86_64` da Release, confere o SHA-256 e passa para o `instalar.sh`; espera até 90 min o binário de uma Release recém-publicada. |
| `instalar.sh` | Instala o `beni-menu` (de `cliente/bin/` ou `cliente/target/`). |
| `themes/fonts/Fredoka-SemiBold.ttf` | Instância estática da Fredoka (o menu nativo não aplica o eixo de peso). |
| `.github/workflows/menu-nativo.yml` | Compila e testa o menu nativo; numa Release, anexa o binário. |
| `tests/test_menu_nativo.py` | Endpoints, cache, controles, `process_alive_rapido` × `process_state.py` e o atualizador. |

## Arquivos alterados (`src/`)
| Arquivo | Mudança |
|---|---|
| `server.py` | Junta os bloqueios por horário com os bloqueios por limite (motivos `category_limit` e `daily_limit`, campo `limitBlocked`); endpoints `GET /api/usage/status` e `POST /api/usage/reset`; liga o contador ao abrir um tile; idioma `pt`. |
| `config_validation.py`, `profile_config.py` | Aceitam `tile.category`, `profile.categoryLimits`, `profile.choiceScreenEnabled` e o idioma `pt`. |
| `overlay.py` | Barra redonda e meio transparente (fica opaca com o mouse em cima) com ✕, tempo restante e ✥ para mudar de canto (toque = próximo canto; arrastar = gruda no canto mais perto; lembra o canto de cada app). Em sites, botão "‹ Voltar" separado no canto inferior esquerdo. Ao fechar, o launcher só fica "por cima" por um instante (antes ficava preso assim e o próximo app abria escondido atrás dele). Tempo restante da categoria (com cores), contagem grande nos últimos 10 s, fechamento no 0; reposiciona a janela via X11 quando o jogo a joga para 0,0; textos em pt. |
| `application_launcher.py` | Firefox dos sites separado por criança (`external-firefox-profile` para o perfil padrão, `external-firefox-profile-<id>` para os outros, criado com as extensões e ajustes mas sem cookies/senhas); `--marionette` só quando há login automático. |
| `runtime_diagnostics.py` | Eventos `site_login.saved` e `site_login.finished` (só o resultado, nunca e-mail/senha). |
| `timer_watchdog.py`, `browser.html`, `media.html`, `no-media.html` | Textos em pt. O `browser.html` tinha um erro de JS de origem (`'Time's up!'`), corrigido com a tradução. |
| `speech_feedback.py` | Voz em português (`spd-say -l pt-BR` / `espeak-ng -v pt-br`). |
| `recommendations.json` | Campos `label_pt`, `name_pt`, `desc_pt`, `hint_pt`. |
| `frontend/icons.js` | `createTileVisual` aceita `img:covers/arquivo.png` (capa de jogo no lugar do emoji). |
| `frontend/launcher-ui.js` | Lista filtrada pela categoria escolhida; clique em tile bloqueado por limite; nomes dos temas novos e em pt. |
| `frontend/theme-runtime.js` | Registra os 6 temas novos como "mundos ilustrados". |
| `frontend/runtime-controls.js` | Teclado na tela de escolha; Esc na lista volta para a escolha; Esc com a mensagem de "tempo acabou" aberta só fecha a mensagem (antes saía do modo infantil). |
| `frontend/parent-settings.js` | Painel dos limites (o resumo mostra "📚 regra de aprendizado" quando ligada); opção "Tela inicial"; recomendações em pt; botão Desligar aparece já no carregamento. |
| `frontend/schedule-controls.js` | Repassa os motivos de bloqueio por limite; não mostra `img:…` cru no seletor. |
| `frontend/state.js`, `localization.js`, `profiles.js`, `first-run.js`, `activity-dashboard.js`, `media-library.js` | Suporte ao idioma `pt` (textos de perfis, datas pt-BR, opção 🇧🇷 no primeiro uso). |
| `index.html` | Textos em pt; links dos CSS/JS novos; botão Voltar e selo de tempo; quadros "Limite diário por categoria" e "Tela inicial". |

## Regra de aprendizado (`categoryLimits.learningRule`)
`{"enabled": true, "goalPercent": 50, "reducedPercent": 50, "mode": "fixed"}` (campos que faltarem usam esses valores; `goalPercent` 1–100, `reducedPercent` 0–100, `mode` `fixed` ou `proportional`).
- Se **ontem** a criança fez menos que `goalPercent`% do limite de 📚 Aprender (`educativo`) de ontem, **hoje** o limite de 🎮 Jogos (`jogos`) fica com `reducedPercent`% (arredondado para baixo). Ex.: ontem Aprender 0/30 → hoje Jogos 15 em vez de 30. O 🎨 Passatempo divide o pool dos Jogos e cai junto.
- `proportional`: o Jogar fica entre `reducedPercent`% e 100% conforme o quanto da meta foi feito (metade da meta com 50% → 75%).
- Sem penalidade quando: ontem o perfil não usou o notebook (nenhum segundo contado — também vale para o notebook desligado); Aprender não tinha limite ontem (não há meta; limite 0 = meta 0, sempre cumprida); Jogos está sem limite hoje; a regra ou os limites do perfil estão desligados (comportamento igual ao de antes).
- Dia da semana: a meta usa o limite de Aprender **de ontem** (coluna de ontem) e a redução vale sobre o limite de Jogos **de hoje** (coluna de hoje). As duas contas usam o config atual.
- O **total do dia não muda**: reduzir o total tiraria tempo também do Aprender, o contrário do que a regra quer. O Jogar menor já reduz o que dá para usar.
- Só conta o dia imediatamente anterior (não "o último dia usado"): depois de um fim de semana sem notebook, segunda começa sem redução.
- "Zerar o tempo de hoje" não mexe no histórico.
- `/api/usage/status` ganha `learningRule: {enabled, active, reason, mode, goalPercent, reducedPercent, percent, category, learningCategory, yesterday, yesterdayUsedSeconds, yesterdayLearnedSeconds, yesterdayLearningMinutes, goalSeconds, baseMinutes, minutes, today: {goalSeconds, learnedSeconds, met}}`; `reason` ∈ `off`, `no_goal`, `no_usage`, `goal_met`, `no_play_limit`, `goal_missed`. As categorias reduzidas trazem `learningReduced: true` e `baseMinutes`.
- **Aprender parado não conta** (`OCIOSO_APRENDER_SEGUNDOS` = 90). Com um app, site ou jogo de navegador da categoria `educativo` aberto, o segundo só entra se houve teclado, mouse, toque ou controle nesse prazo. Os segundos ociosos não vão para o uso de hoje nem para a regra de amanhã. Jogar e Passatempo seguem contando parados. Não há interruptor. A pílula mostra "⏸ mexa para contar" e o status ganha `paused` (no objeto e em `active`). Log, uma vez em cada transição: "uso: aprender pausado (sem teclado/mouse há 90 s)" e "uso: aprender voltou a contar" — no Windows em `beni-windows.log` e no `runtime.jsonl` (evento `usage.aprender`, campo `texto`); no Linux, no `runtime.jsonl`. Medição: Windows `GetLastInputInfo` (não vê XInput; o módulo de controles não roda lá, então o controle sozinho não segura a contagem). Linux: `XScreenSaverQueryInfo` via `libXss.so.1` (pacote `libxss1`), senão o comando `xprintidle`. O joystick entra por `Controles.segundos_sem_controle` (botão ou eixo útil, o mesmo filtro que já ignora ruído). Se nada disso funcionar, não pausa e loga uma vez "uso: aprender sem detecção de ociosidade, o tempo conta sempre".

## `scripts/` e `tests/`
- `scripts/install.sh`: também copia `usage_limits.py`, `site_logins.py`, `sites/phet.html`, `pt.json` e os CSS/JS novos.
- `tests/test_server.py`: 2 asserções ajustadas (texto já traduzido; campo `limitBlocked`).
- `tests/test_pista_turbo.py` (novo): projeto Scratch coerente e igual ao gerador.
- `tests/test_atualizador.py` (novo): atualizador (versões, `[forcar]`, pacote, janela da madrugada, espera de app aberto), estado em Pais → Sistema e migrações de catálogo.
- `tests/test_site_logins.py` (novo): login dos sites e perfis do Firefox por criança.
- `tests/test_usage_limits.py` (novo): limites por dia da semana, pool e regra de aprendizado (regra desligada, meta cumprida/não cumprida, dia anterior sem uso, Aprender sem limite, Jogar sem limite, pool, dia da semana, modo proporcional, histórico na virada do dia e após reiniciar, arquivo antigo sem histórico, fechamento do app no limite reduzido).
- `tests/test_config_validation.py`: validação de `categoryLimits.learningRule`.
- `tests/test_overlay.py` passa sem mudança. O `overlay.py` só pede `XMoveWindow` ao X11 quando vai usar.

## Fora do launcher (`beni/`)
| Pasta/arquivo | Instalado em | Para quê |
|---|---|---|
| `bin/cozy-kids-launcher` | `~/.local/bin` | Script de início do launcher, já preenchido (porta 38431, Firefox em modo quiosque). Respeita a trava de usuário (`cozy-usuario-permitido`). |
| `bin/cozy-usuario-permitido` | `~/.local/bin` | Trava de usuário: o menu só abre nos usuários de `USUARIOS_PERMITIDOS=` em `/etc/beni-launcher/launcher.conf` (criado pelo `instalar-sistema.sh` com o usuário das crianças; vazio ou sem arquivo = qualquer usuário). Impede que o autostart de outra conta (a dos pais) tome a porta 38431 e deixe o menu da criança com tela branca. Para testar em outra conta: `COZY_KIDS_IGNORAR_TRAVA_USUARIO=1`. |
| `bin/cozy-iniciar` | `~/.local/bin` | Usado no login: confere a trava de usuário, abre o launcher (com a tela "Abrindo o menu…") e sincroniza o itch.io em segundo plano. |
| `bin/cozy-itch-sync` | `~/.local/bin` + timer systemd | Invólucro de `src/itch_sync.py` (a mesma sincronização da thread do servidor). |
| `bin/navegador-jogos` | `~/.local/bin` | Chromium em modo quiosque com aceleração, pt-BR, sem barra de tradução, mais a tela "Carregando…". |
| `bin/cozy-fullscreen` | `~/.local/bin` | Põe em tela cheia apps que abrem em janela (`wmctrl`). |
| `bin/cozy-jogos` | `~/.local/bin` | Abre a lista de jogos SNES/PS1. |
| `bin/gcompris`, `tuxpaint`, `turbowarp`, `luanti`, `klavaro`, `klotski` | `~/.local/bin` | Abrem as versões do Flathub em tela cheia (GCompris só com atividades de nível 3–6). |
| `bin/tuxmath`, `pingus`, `hex-a-hop`, `supertux`, `frogatto` | `~/.local/bin` | Tela cheia na resolução atual + `nograb.so`. |
| `bin/supertuxkart` | `~/.local/bin` | Força a resolução atual na configuração do jogo (evita a tela apagada). |
| `bin/planetario` | `~/.local/bin` | Stellarium em tela cheia. |
| `lib/cozy-fixes/nograb.c` | `~/.local/lib/cozy-fixes/nograb.so` | Anula `SDL_WM_GrabInput` (SDL 1.2) e `SDL_SetWindowGrab`/`MouseGrab` (SDL2, também via `dlsym`). |
| `lib/cozy-fixes/carregando.py` | `~/.local/lib/cozy-fixes` | Tela "Carregando…" até o navegador estar em tela cheia. |
| `cozy-jogos/jogos.py` | `~/.local/share/cozy-jogos` | Lista de jogos SNES/PS1 em Tk, com capas, teclado, mouse e controle. |
| `chromium/cozy-jogo.html` | `~/.var/app/org.chromium.Chromium` | Moldura que amplia jogos de tamanho fixo (`#w=&h=&fh=&u=`). |
| `emuladores/retroarch.cfg` | `~/.config/cozy-jogos` | RetroArch sem menu, sem prender o mouse, sem trocar a resolução, Esc sai. |
| `emuladores/gpuPeopsMesaGL.cfg` | `~/.pcsxr/plugins` | Vídeo OpenGL do PCSX-R (o DFXVideo não funciona com o driver modesetting). |
| `emuladores/luanti-minetest.conf` | `~/.var/app/org.luanti.luanti/.minetest` | Luanti leve (distância de visão curta, sem sombras). |
| `config/config.json` | `~/.config/cozy-kids-launcher` (se não existir) | Dois perfis com apps, categorias, temas e limites 60/30/30. |
| `config/itch-colecoes.json` | idem, só se ainda não existir | Opcional: id do perfil → URL da coleção. Vazio por padrão; o gênero escolhe a coleção. O arquivo que um notebook já tem não é substituído. |
| `systemd/cozy-itch-sync.{service,timer}` | `~/.config/systemd/user` | Sincronização a cada 30 min. |
| `ferramentas/gerar-temas*.py` | — | Geram os SVG dos temas (Python puro). |

## Ajustes do sistema feitos pelo `instalar.sh`
- `python3-tk`, `wmctrl`, `xdotool` e os apps/emuladores (apt e Flathub).
- XFCE: remove os atalhos Ctrl+Alt+Del e Ctrl+Alt+L (bloqueio); desliga o bloqueio ao suspender, ao fechar a sessão e depois do protetor de tela (light-locker); deixa os painéis em "esconder sempre".
- Firefox do launcher: `accessibility.browsewithcaret` desligado (era a linha vertical piscando).
- Firefox dos sites (Escola Games etc.): bloqueador de anúncios **uBlock Origin** (`beni/firefox/`), instalado só nesse perfil.
- Escola Games: o menu "Jogos" (`/jogos-divertidos`, `/diversao/…`) e "Jogos em inglês" ficam escondidos (`beni/firefox/userContent.css`) e bloqueados (`/etc/firefox/policies/policies.json`). Os jogos educativos (`/jogos/…`) continuam.
- Escola Games com bloqueador: os jogos só abrem sem anúncio quando o script do Google **falha** ao carregar (o site tem essa saída). O uBlock trocava o script por um falso, e o jogo ficava em "Loading…" para sempre. A política em `beni/firefox/policies.json` manda o uBlock só bloquear esse script nos jogos (`assets.escolagames.com.br`).
- Avisos de cookies ("Aceitar cookies") nos sites: o uBlock liga as listas "EasyList – Cookie Notices" e "uBlock filters – Cookie Notices" (`toOverwrite.filterLists` em `beni/firefox/policies.json`, que troca a seleção inteira: por isso as listas padrão, a regional `spa-1` e `user-filters`, sem a qual a regra do Escola Games seria ignorada, estão lá também). No Firefox ESR, `cookiebanners.service.mode=1` no `user.js` (recusa o opcional, nunca aceita por nós; o Firefox comum tirou o recurso e ignora a pref; a política `Preferences` não aceita `cookiebanners.`).
- DNS com filtro para crianças em qualquer rede: **CleanBrowsing Family** (bloqueia sites adultos, proxies e VPNs; força a Busca Segura do Google/Bing e o Modo Restrito do YouTube). Vai em `/etc/systemd/resolved.conf.d/dns-familia.conf`, sem DNS reserva. `/etc/NetworkManager/conf.d/90-dns-familia.conf` (`dns=none`) impede que o DNS do roteador seja usado (o NetworkManager 1.46 ignora `global-dns` com o resolved). Os navegadores não podem contornar: Firefox com `DNSOverHTTPS` desligado e travado (`policies.json`), Chromium com `--disable-features=DnsOverHttps` (`navegador-jogos`). Para desligar: apague os dois arquivos e rode `sudo systemctl restart systemd-resolved NetworkManager`.
- Desenhar: o tile `paint` abre o **Kleki** (kleki.com) no lugar do Tux Paint. Os desenhos salvos (⬇) vão para `~/Imagens/Desenhos`, sem o painel de downloads do Firefox.
- Tiles **Autodraw** (autodraw.com) e **Colorir** (colorir-online.com), categoria Aprender. No `userContent.css`: o Colorir fica só com a parte de colorir (sem a barra de cima com Apps/Quem somos/Idiomas, rodapé, banners de outros sites de jogos, redes sociais e anúncios), e o Autodraw perde Share, Artists, About e links externos do menu. `policies.json` bloqueia `/apps` e `/quem-somos` do Colorir.
- Tile **Pista Turbo** 🏎️ (Aprender, só no perfil do Beni): jogo de corrida no Scratch, com pista laranja, chamas, turbo amarelo e 3 voltas, para jogar e depois modificar. O projeto é gerado por `beni/ferramentas/gerar-pista-turbo.py` (`src/scratch/Pista Turbo.sb3`). A cópia da criança fica em `~/Imagens/Scratch/`, a única pasta de documentos que o TurboWarp (flatpak) enxerga, e não é sobrescrita. O atalho é `beni/bin/pista-turbo`. Os números do jogo ficam em variáveis em português (velocidade máxima, curva, voltas para vencer), com um bilhete explicando.
- Tile **Kiddo Games** (kiddogames.fun, jogos simples sem anúncios), categoria Passatempo.
- Tile **Teach Your Monster** (teachyourmonster.org/account/play), categoria Passatempo, com login automático.
- **Atualizações automáticas** (`beni/sistema/beni-atualizar`, instalado em `/usr/local/sbin` pelo `beni/sistema/instalar-sistema.sh`):
  - `beni-atualizar-verificar.timer` roda de hora em hora: procura a Release mais nova de `jaison/beni-launcher`, baixa o `.tar.gz` da tag e confere se o `VERSION` bate com a tag.
  - `beni-atualizar-aplicar.service` roda no boot, antes do `display-manager`: instala como root a parte de sistema e, como o usuário, o `instalar.sh --atualizacao`, que inclui as migrações de catálogo. Antes guarda uma cópia, e volta para ela se algo falhar.
  - Com o notebook ligado, instala na hora se a Release tiver `[forcar]` nas notas, ou de madrugada; nos dois casos, só quando nenhum app está aberto. O launcher fecha, aparece um aviso pelo zenity e o launcher reabre na sessão.
  - O estado fica em `/var/lib/beni-launcher/estado.json`, que a área dos pais mostra em Pais → Sistema (`/api/update/status`). O log fica em `/var/log/beni-atualizar.log`.
- O **atualizador do projeto original** (`update.sh`), que instalaria o Cozy Kids Launcher original por cima deste projeto, é removido pelo `instalar.sh`. A verificação de versão do servidor aponta para este repositório (`legacy_update_status` continua testado).
- Versão do projeto em `VERSION` (1.0.0), gravada em `~/.local/share/cozy-kids-launcher/version`.
- `instalar.sh` agora chama `sudo beni/sistema/instalar-sistema.sh` para tudo que é root (pacotes de `pacotes-apt.txt`/`pacotes-flatpak.txt`, políticas do Firefox, DNS, atualizador) e aplica as migrações de `beni/config/migracoes.json` (`beni/ferramentas/migrar-config.py`; as já aplicadas ficam em `~/.config/cozy-kids-launcher/migracoes-aplicadas.json`).
- Autostart `~/.config/autostart/cozy-kids-launcher-autostart.desktop` → `cozy-iniciar`.
