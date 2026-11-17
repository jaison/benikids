# Benikids: detalhes e parte técnica

🇧🇷 **Português** · 🇺🇸 [English](benikids-technical.md) · ⬅ [README](../README.md)

Tudo o que não cabe no README: cada recurso em detalhe, ajustes finos no Linux, como funciona por
dentro, como publicar uma atualização e as correções para hardware antigo.

## Para as crianças

### Três categorias, cada uma com o seu tempo
- **Tela inicial "Aprender / Passatempo / Jogar"**: cartões grandes com barrinha e "faltam 18 min".
  - A lista mostra só a categoria escolhida, com **⬅ Voltar** (ou Esc).
  - Quando o tempo acaba, o cartão fica cinza com 🔒 "Amanhã tem mais!".
- **Medidores** verde/amarelo/vermelho no launcher. Durante o jogo, uma barra discreta mostra o tempo restante. Ela fica meio transparente, dá para arrastar para outro canto e tem o ❌ para fechar.
- Nos **sites** aparece também um botão **‹ Voltar** no canto inferior esquerdo.
- Nos **10 segundos finais**, uma contagem grande avisa ("Seu tempo de jogos está acabando! 8…") e sugere o que ainda dá para fazer ("Você ainda pode brincar de Aprender (18 min)").
- Com o **reforço de aprendizagem** ligado:
  - os cartões Jogar e Passatempo explicam com carinho: "Hoje 15 min — ontem faltou aprender 📚";
  - o cartão Aprender mostra quanto falta para ter o Jogar inteiro amanhã ("Meta de hoje cumprida! ⭐").

### O que tem em cada categoria
| 📚 Aprender | 🎨 Passatempo | 🎮 Jogar |
|---|---|---|
| Khan Academy (login automático) | Desenhar (**Kleki**, desenhos salvos em Imagens/Desenhos) | Luanti (parecido com Minecraft) |
| **PhET** com tela para escolher a matéria (Física, Matemática, Química, Terra e Espaço, Biologia), já no Ensino Fundamental 1 | **Autodraw** | SuperTux, SuperTuxKart, Frogatto |
| **Escola Games** sem anúncios e sem o menu de jogos de diversão | **Colorir** (só os desenhos, sem propaganda de outros jogos) | **Super Nintendo e PlayStation** (lista com capas, teclado/mouse/controle) |
| Scratch (TurboWarp), **Pista Turbo** (jogo de corrida pronto no Scratch para jogar e modificar), Blockly Games | **Teach Your Monster** (login automático) e **Kiddo Games** (73 joguinhos sem anúncios) | jogos de navegador do **itch.io** em tela cheia de verdade |
| Digitação (Klavaro), Planetário (Stellarium) | GCompris, Pingus, Hex-a-hop, Klotski, Music Lab | jogos de vestir/maquiagem/boneca sem anúncios |

Os pais mudam qualquer app de categoria em Pais → Tempo de tela.

### Visual
- **6 temas novos** com arte original em SVG (nenhum personagem ou logo de marca):
  - **Herói Aranha** (quadrinhos), **Blocos de Montar** e **Dojo Ninja**;
  - **Reino do Gelo**, **Casinha Mágica** e **Castelo Encantado**, com letras grandes e redondas para quem está aprendendo a ler.
- **Tudo em português do Brasil**, na tela das crianças e na área dos pais.

---

## Para os pais

### ⏳ Tempo de tela (Pais → Tempo de tela)
- **Limite diário por categoria e total do dia**, por exemplo 30 min de Aprender + 30 min de Jogar.
- O **Passatempo divide o tempo com os Jogos**: desenhar 10 min deixa 20 para jogar. Também pode ter tempo próprio.
- **Tempo diferente em cada dia da semana**: uma tabela Seg–Dom, com o dia de hoje destacado.
- **Categoria de cada app** escolhida numa lista, e um botão **"Zerar o tempo de hoje"**.
- Horários permitidos por dia e por app (do projeto original).

### 📚 Reforço obrigatório de aprendizagem (no mesmo quadro)
- **Meta**: fazer pelo menos *X*% do tempo de Aprender do dia (padrão 50%: com 30 min de Aprender, a meta é 15).
- **Consequência**: se a meta não foi cumprida ontem, hoje o Jogar (e o Passatempo, que divide o mesmo tempo) fica com *Y*% (padrão 50%).
- **Modo proporcional** (opcional): quem aprendeu um pouco perde menos.
- **Justo com a criança**:
  - dia sem uso do notebook não conta;
  - o Aprender e o total do dia nunca diminuem;
  - o próprio launcher fecha o jogo no limite reduzido.
- Os pais veem o motivo, por exemplo: "Hoje: Jogar reduzido para 15 min (de 30) porque ontem Aprender foi 0/30 min".
- Vem desligado e é ligado por perfil.

### 🔑 Login automático nos sites (Pais → Crianças)
- Quadro **"Login automático nos sites"**, com e-mail/usuário e senha **por criança**.
  - Hoje: Khan Academy e Teach Your Monster (conta de família, aba "Home").
- Ao abrir o site, o launcher preenche o login e clica em "Entrar". Se a sessão ainda estiver aberta, não digita nada.
- **A senha fica só neste computador**, num arquivo separado da configuração e legível só pelo usuário. Depois de salva, ela nunca aparece de novo na tela.
- **Cada criança tem o seu navegador de sites** (cookies e logins separados): o Khan da Bea não abre com a conta do Beni.
- O navegador do site com login abre com a porta de controle ligada (Firefox: 28290; Edge: 28291), só em 127.0.0.1. Enquanto esse site está aberto, qualquer programa deste computador (de qualquer conta) alcança a porta, nunca de fora dele; ela fecha quando o site fecha.
- O gerenciador de senhas do Edge fica desligado nos perfis do Benikids. Logins salvos antes não são apagados: para apagar, com o site fechado, apague os arquivos `Default\Login Data` e `Default\Login Data For Account` da pasta `%USERPROFILE%\.cache\cozy-kids-launcher\external-chromium-profile` (ou `…-<id>` da criança).
- Para acrescentar outro site, basta descrever a página de login em `src/site_logins.py`.

### 🛡️ Internet e conteúdo
- **DNS CleanBrowsing Family** em qualquer Wi‑Fi:
  - bloqueia sites adultos, proxies e VPNs;
  - força a Busca Segura do Google/Bing e o Modo Restrito do YouTube.
- Os navegadores não conseguem contornar o filtro, porque o DNS‑over‑HTTPS está desligado.
- **uBlock Origin** nos sites, já ajustado para os jogos do Escola Games abrirem sem anúncio.
- **Sites limpos com CSS próprio**:
  - Escola Games sem o menu "Jogos";
  - Colorir sem a barra de cima, banners e redes sociais;
  - Autodraw sem "Share" e links externos.

  As páginas proibidas também ficam bloqueadas por política do Firefox.
- Downloads vão direto para `~/Imagens/Desenhos`, sem o painel do Firefox, que abriria o gerenciador de arquivos.

### 🎮 Controles (Pais → Sistema → Controles)
- Funciona com **controles USB genéricos**, inclusive os baratos sem marca. Um **assistente** pede botão por botão (direcional, ✕, ◯, Start, Select…) e guarda o mapeamento.
- Com ele, o controle:
  - **navega no menu** (direcional = setas, ✕ = abrir, ◯ = voltar);
  - funciona nos **jogos SDL** (SuperTux, SuperTuxKart…), no **Super Nintendo** (RetroArch), no **PlayStation** (PCSX-R) e nos **jogos de navegador** (uma extensão do Chromium entrega o controle no formato padrão);
  - fecha o jogo aberto e volta ao menu segurando **Start + Select por 2 s**.
- Os jogos que funcionam com controle ganham o selo 🎮 no menu.
- No Windows, os jogos usam o controle sozinhos, mas o menu ainda não é navegado pelo controle.

### Outros
- **Coleções do itch.io**: cada criança tem uma coleção pública. Jogo adicionado na coleção vira ícone (com capa), e jogo removido some. A sincronização roda no login e a cada 30 min, então os pais testam antes e só então liberam.
- Em Pais → Aparência → **Tela inicial**, você liga ou desliga a pergunta Aprender/Passatempo/Jogar em cada perfil.

### 🔄 Atualizações automáticas
- O notebook procura uma **Release nova** deste repositório no GitHub de hora em hora e baixa sozinho. Commits no `main` **não** chegam às crianças; só Releases.
- **Quando instala**:
  - **ao ligar o notebook**, antes de o menu aparecer (padrão);
  - **de madrugada (2h–5h)**, se o notebook ficar sempre ligado e ninguém estiver usando;
  - **na hora**, se a Release tiver **`[forcar]`** nas notas. Ele espera nenhum app estar aberto, o menu fecha com o aviso "🔧 Atualizando o computador… volta em um minutinho!" e reabre sozinho.
- A atualização traz código, apps novos (apt/Flathub), sites, regras do Firefox e do DNS e **mudanças de catálogo** (adicionar/remover jogos). O que os pais configuraram (limites, temas, PIN, logins) não é tocado.
- Se a instalação falhar, ela **volta sozinha** para a versão anterior e não tenta de novo a mesma versão.
- Em Pais → Sistema → **Ver atualizações** aparecem a versão instalada, a última verificação e se há uma versão baixada esperando.

---

## Ajustes finos no Linux

Depois de instalar, antes de entregar para a criança:
- **Pais → Sistema: crie o PIN dos pais.** Sem PIN, qualquer um entra no painel, sai do modo infantil, zera o tempo ou vê o e-mail das contas salvas.
- Ajuste nomes, temas e limites em Pais. A configuração inicial traz dois perfis de exemplo, com os apps já separados em Aprender/Passatempo/Jogar.
- Se quiser, ligue o **reforço de aprendizagem** (Pais → Tempo de tela) e salve os **logins dos sites** (Pais → Crianças).
- Luanti: abra uma vez e instale o jogo **Mineclonia** (Conteúdo → Procurar).
- Coloque seus jogos de SNES/PS1 em `~/Jogos/SNES` e `~/Jogos/PS1`. A BIOS do PS1 vai em `~/Jogos/PS1/BIOS` (veja `~/Jogos/LEIA-ME.txt`).
- Troque as coleções do itch.io em `~/.config/cozy-kids-launcher/itch-colecoes.json`. O arquivo liga o **id do perfil** à URL pública da coleção.

Rodar `./instalar.sh` de novo atualiza os arquivos e **não apaga** a configuração, os logins
salvos nem os jogos. Use `./instalar.sh --sem-apps` para não mexer em apt/flatpak.

---

## Como funciona (resumo técnico)

```
login → ~/.config/autostart → cozy-iniciar
          ├─ cozy-itch-sync      (coleções do itch.io → tiles "itch-*" no config.json)
          └─ cozy-kids-launcher  (servidor Python em 127.0.0.1:38431 + menu nativo beni-menu;
                 │                    sem GPU utilizável, Firefox em modo quiosque)
                 ├─ Pais → PIN na tela do menu + Firefox/Edge atrás dele com a área dos pais
                 │         (aparece com o PIN certo; fecha ao voltar)
                 ├─ usage_limits.py   (tempo por categoria, dia da semana, reforço de aprendizagem)
                 └─ tocar num ícone → process_supervisor.py + overlay.py (❌, tempo, ‹ Voltar)
                        ├─ apps locais: atalhos em ~/.local/bin (supertux, gcompris, …)
                        ├─ sites: Firefox em modo quiosque, um perfil por criança
                        │     (uBlock, CSS dos sites; site_logins.py faz o login pelo Marionette)
                        └─ jogos de navegador: navegador-jogos → Chromium em modo quiosque
                               → cozy-jogo.html (amplia o jogo) + carregando.py (tela de espera)
```

| Onde | O quê |
|---|---|
| `src/` | código do launcher (original + mudanças) → `~/.local/share/cozy-kids-launcher` |
| `src/beni_windows.py`, `src/plataforma_windows.py` | no Windows: inicia o servidor e o menu, e faz o papel do bash/`xdotool` (árvore de processos, Job Object para fechar o app inteiro, foco das janelas) |
| `src/catalogo/windows.json`, `src/instalar_apps.py` | catálogo de apps do Windows e a instalação pelo `winget` |
| `scripts/windows/` | instalador e configuração inicial do pacote do Windows (montado pelo GitHub Actions em `menu-nativo.yml`) |
| `cliente/` | **menu nativo** (`beni-menu`, Rust + gpui-fast): a tela das crianças sem navegador. Veja [cliente/LEIA-ME.md](../cliente/LEIA-ME.md) |
| `src/usage_limits.py`, `src/frontend/usage-limits.*` | tempo de tela por categoria, dia da semana e reforço de aprendizagem |
| `src/site_logins.py`, `src/frontend/site-logins.*` | login automático nos sites (senhas em `~/.config/cozy-kids-launcher/site-logins.json`) |
| `src/frontend/escolha.*` | tela Aprender/Passatempo/Jogar |
| `src/sites/phet.html` | pré-tela de matérias do PhET |
| `src/frontend/cozy-temas.css`, `themes/*.svg`, `themes/fonts/` | temas novos |
| `src/frontend/locales/pt.json` | tradução |
| `beni/bin/` | atalhos dos apps, `cozy-itch-sync`, `navegador-jogos`, `cozy-iniciar` … → `~/.local/bin` |
| `beni/firefox/` | uBlock Origin, CSS dos sites e políticas do Firefox (`/etc/firefox/policies`) |
| `beni/sistema/` | parte do sistema (`instalar-sistema.sh`: pacotes, Firefox, DNS com filtro) e o atualizador automático (`beni-atualizar` + serviços do systemd) |
| `beni/ferramentas/migrar-config.py`, `beni/config/migracoes.json` | mudanças de catálogo aplicadas uma vez em cada notebook |
| `beni/lib/cozy-fixes/` | `nograb.c` (compilado na instalação) e `carregando.py` |
| `beni/cozy-jogos/jogos.py` | lista de jogos SNES/PS1 |
| `beni/chromium/cozy-jogo.html` | moldura que amplia jogos de navegador |
| `beni/config/` | configuração inicial (perfis, apps, categorias, limites) e coleções do itch.io |
| `beni/emuladores/` | configurações do RetroArch, PCSX-R e Luanti para hardware fraco |
| `beni/systemd/` | timer da sincronização do itch.io |
| `beni/ferramentas/` | scripts que geram os SVG dos temas |

O código ainda usa os nomes internos do original (`cozy-kids-launcher`, porta 38431, pastas em
`~/.local/share/cozy-kids-launcher`). Assim fica fácil comparar com o projeto original e trazer
correções de lá.

### Área dos pais pelo menu nativo (PIN no menu, navegador atrás dele)

Medido num i5 de 2012 com Windows: de clicar em "Pais" até o PIN aparecer levava ~3 s
(~1,1 s só para o Edge abrir, ~0,5 s de passagem para o quiosque, ~1 s da página até o PIN).
Agora, com PIN configurado:

1. O menu mostra **na hora** a tela de PIN nativa (a mesma de sair/desligar) e pede ao
   servidor uma "espera" (`POST /api/pais/preparar`).
2. No mesmo instante abre o navegador **atrás do menu**, com `cliente.html?ir=…#espera=<id>`
   (o id vai depois do `#`, que não chega ao servidor). A página carrega o `index.html`
   coberta com o fundo da marca e fica presa em `POST /api/pais/espera` (o pedido espera
   até 20 s pelo PIN; sem timer, que o navegador atrasa em janela coberta). Antes do PIN
   ela não abre a área dos pais nem pede os dados dela (exigem o cookie de admin).
3. O PIN vai para `POST /api/pais/liberar` — mesma validação, mesma mensagem e o mesmo
   bloqueio de tentativas do `verify-pin`. Certo: nasce um **token de uso único que vale
   30 s**; a espera o entrega uma vez à página, que o troca pelo cookie de admin normal em
   `POST /api/pais/entrar`. Token usado, vencido ou inventado é recusado. Esses endereços só
   respondem a pedidos do próprio computador (127.0.0.1/::1) e recusam páginas de outros
   sites; nem o id, nem o token, nem o PIN vão para log.
4. O menu traz o navegador para a frente, e a área dos pais abre sem pedir o PIN de novo.
   Cancelar (ou o PIN sair da tela por outro motivo, como o tempo esgotado) fecha o
   navegador que esperava: o job inteiro no Windows, TERM no Linux.

Sem PIN configurado, abre direto como antes. Quem usa o menu web (sem menu nativo) continua
com o PIN da página. Se algo falhar (servidor antigo, espera vencida), a página cai no PIN
dela.

**Como o navegador fica atrás do menu** (`cliente/src/navegador.rs`): uma thread vigia as
janelas desta abertura, com o mesmo laço nos dois sistemas (`vigiar`, testado com um sistema
de janelas de mentira).
- **Esperando o PIN:** o menu fica "sempre por cima" e com o foco. Cada janela do navegador
  que nasce é **guardada** atrás do menu, fora do Alt+Tab e da barra de tarefas. Ela **não é
  escondida**: no pacote 13 o Edge escondido (`SW_HIDE`) voltava todo branco, porque o
  Chromium para de desenhar e não retoma.
- **PIN aceito:** a janela guardada volta ao normal e vem para a frente com o foco. Se ela
  ainda não nasceu (PIN digitado em 0,3 s, e o Edge leva ~1 s), vem para a frente quando
  nascer; até lá o menu mostra "Abrindo a área dos pais...". Um novo clique em "Pais" com o
  navegador já aberto o traz para a frente.
- **Windows:** `WS_EX_TOOLWINDOW` sem `WS_EX_APPWINDOW` (fora do Alt+Tab; refeito se o
  Chromium mudar o estilo), `ITaskbarList::DeleteTab`/`AddTab` (barra de tarefas),
  `HWND_BOTTOM`, menu `HWND_TOPMOST` (conferido a cada volta) e `LockSetForegroundWindow`.
  O Edge abre com `--disable-backgrounding-occluded-windows --disable-renderer-backgrounding
  --disable-features=CalculateNativeWinOcclusion`, para continuar desenhando coberto.
- **Linux (X11):** `wmctrl` põe a janela do Firefox `below`, `skip_taskbar` e `skip_pager`, e
  o menu `above`; o `xdotool` devolve o foco ao menu e, depois do PIN, ativa o Firefox.
- **Risco:** a janela nasce tentando pegar o foco; o Windows recusa por causa da trava, e, se
  pegar, a vigia devolve ao menu em até 10 ms (80 ms no Linux). Uma tecla digitada bem nesse
  instante pode ir para o navegador. O Gerenciador de Tarefas do Windows lista o Edge e
  permite "Alternar para" — vale para qualquer programa e não muda com isto. No Linux, o
  Alt+Tab do xfwm4 pular janelas `skip_taskbar` precisa ser conferido no notebook.

### Testes
`python3 -m unittest discover -s tests` roda **388 testes**, os do projeto original e os novos:
limites por categoria e dia da semana, categorias que dividem tempo, reforço de aprendizagem,
login automático, atualizador, mudanças de catálogo, configuração inicial, catálogo do Windows e a
integração com o menu nativo. O menu nativo
tem os seus em Rust (`cd cliente && cargo test --release`). Três testes do original foram ajustados ao comportamento novo: textos já
traduzidos e o campo `limitBlocked`.

---

## Publicar uma atualização (para o mantenedor)

1. Faça as mudanças no repositório e teste num notebook com `./instalar.sh`.
2. **Jogos/sites/apps novos ou removidos** precisam ir em **dois lugares**:
   - em `beni/config/config.json`, que é o que um notebook **novo** recebe;
   - numa **migração** em `beni/config/migracoes.json`, que é o que os notebooks **já entregues** aplicam, uma vez cada. Exemplo:
     ```json
     {"id": "2026-11-01-jogo-x", "descricao": "Jogo X no Passatempo",
      "operacoes": [
        {"op": "adicionar_tile", "perfis": "todos", "depois_de": "kiddogames",
         "tile": {"id": "jogox", "label": "Jogo X", "emoji": "🧩",
                  "cmd": ["special:external-browser:https://exemplo.org/"],
                  "visible": true, "category": "passatempo"}},
        {"op": "remover_tile", "id": "site-antigo"},
        {"op": "atualizar_tile", "id": "phet", "campos": {"visible": false}},
        {"op": "definir", "perfis": ["default"], "caminho": "categoryLimits.totalMinutes",
         "valor": 60, "so_se_ausente": true}
      ]}
     ```
     `perfis` aceita `"todos"` ou uma lista de ids (`default` = Beni, `child-2501513b5fcb` = Bea).
     O `id` da migração nunca pode se repetir.
   - Pacotes novos vão em `beni/sistema/pacotes-apt.txt` / `pacotes-flatpak.txt`.
3. Suba o número em **`VERSION`** (ex.: `1.1.0`), faça o commit e o push.
4. Crie a Release com a **tag igual à versão**:
   ```bash
   gh release create v1.1.0 --title "1.1.0" --notes "Jogo X no Passatempo"
   # urgente (notebook sempre ligado instala já, sem esperar religar):
   gh release create v1.1.1 --title "1.1.1" --notes "Correção do login [forcar]"
   ```
   A tag tem que bater com o `VERSION`, senão o notebook recusa o pacote. Rascunhos e pré-releases são ignorados.
   Ao publicar a Release, o GitHub Actions compila o menu nativo (`menu-nativo.yml`, ~15 min) e anexa
   `beni-menu-linux-x86_64` + `.sha256`. Os notebooks esperam até 90 min por esse binário antes de instalar.
5. Para acompanhar num notebook: `beni-atualizar estado` e `/var/log/beni-atualizar.log`.

O endereço do repositório e a janela da madrugada ficam em `/etc/beni-launcher/atualizar.conf`.

---

## Correções para notebooks antigos e jogos "rebeldes"
| Problema | Solução |
|---|---|
| Nenhum app abria (o ❌ por cima falhava) | `python3-tk` passa a ser instalado |
| GCompris não abria (`gcompris` × `gcompris-qt`) | atalho `beni/bin/gcompris` |
| TuxMath, Pingus etc. **prendiam o mouse** e o ❌ não funcionava | `nograb.so` (LD_PRELOAD) anula o "prender mouse" do SDL 1.2/SDL2 |
| SuperTuxKart trocava a resolução e **a tela ficava apagada** ao fechar | os atalhos sempre usam a resolução atual da tela |
| Apps que abrem em janela (Scratch, Klavaro, Klotski) | `cozy-fullscreen` coloca em tela cheia via `wmctrl` |
| Depois de fechar um app pelo ❌, o próximo abria **escondido atrás do menu** | o launcher só fica "por cima" por um instante |
| Ctrl+Alt+Del bloqueava a tela, e ao voltar ficava preta | atalho e bloqueios automáticos desligados |
| Barra do Linux aparecia ao abrir jogos | painéis do XFCE escondidos (aparecem com o mouse na borda) |
| Linha vertical piscando no launcher (F7 do Firefox) | navegação com cursor desligada |
| Esc numa mensagem de "tempo acabou" saía do modo infantil | agora Esc só fecha a mensagem |
| Jogos 3D de navegador lentos no Firefox | jogos de navegador abrem no Chromium com aceleração forçada (≈2× mais FPS neste hardware) |
| Jogos do Escola Games ficavam em "Loading…" com bloqueador de anúncios | o uBlock só bloqueia o script do Google (o jogo tem saída quando ele falha) |
| O DNS global do NetworkManager 1.46 era ignorado | o DNS com filtro vai direto no `systemd-resolved` |
| O menu no Firefox ocupava ~600 MB e até 29% de um núcleo parado | **menu nativo** (`cliente/`): ~200 MB, ~1% parado, abre em ~1 s ([detalhes](../cliente/LEIA-ME.md)) |
| O script do launcher gastava ~18% de um núcleo o tempo todo (abria `python3` 2× por segundo), inclusive com jogo aberto | checagem dos processos em bash puro: 0,7% |
| O servidor gastava ~3% parado (relia e validava a configuração a cada requisição) | cache da configuração e dos controles: 0,6% |

A lista detalhada, arquivo por arquivo, está em [beni/MUDANCAS.md](../beni/MUDANCAS.md).

---

## Ambientes em que foi feito e testado

**Linux:**

| | |
|---|---|
| Notebook | Samsung RV419/RV420 (≈2011) |
| Processador | Intel Celeron B800 1.5 GHz, 2 núcleos |
| Memória | 2,8 GB |
| Vídeo | Intel HD Graphics 2000 (Sandy Bridge), OpenGL 3.3 (Mesa 25.0) |
| Tela | 1366×768 |
| Rede | Atheros AR9285 (só Wi-Fi, **sem Bluetooth**) |
| Sistema | **Linux Mint 22.3 "Zena" XFCE** (base Ubuntu 24.04), kernel 6.14, sessão X11 |
| Navegadores | Firefox 146 (launcher e sites) · Chromium 155 via Flathub (jogos de navegador) |
| Python | 3.12 (só biblioteca padrão) |

**Requisitos:**
- Linux Mint XFCE ou outra distro baseada em Ubuntu 24.04 com XFCE.
- Sessão **X11** (não Wayland).
- Internet na instalação.
- Um usuário comum para as crianças, com login automático.

Em Mint Cinnamon/MATE quase tudo funciona, mas os ajustes de barra e bloqueio são específicos do XFCE.

**Windows:** notebook com Windows 10, Intel Core i5, Intel HD 4000 + GeForce GTX 660M, 16 GB, tela
ultrawide 2560×1080, usuário da criança sem administrador. O menu fica em 0% de CPU parado e ~190 MB.

---

## Limitações conhecidas
- Jogos de navegador demoram 10 a 50 s para abrir num Celeron. Jogos 3D pesados ficam abaixo de 10 FPS e foram escondidos.
- O emulador de PS1 (PCSX-R) é antigo. O core `pcsx_rearmed` do RetroArch seria melhor, mas não está nos repositórios do Ubuntu.
- **Login automático**:
  - Só funciona com contas de e-mail/usuário e senha (não "Entrar com Google").
  - Se o site mudar a página de login, é preciso ajustar `src/site_logins.py`.
  - A senha fica protegida só pela permissão do arquivo, sem cifra. Proteja a área dos pais com PIN.
- O filtro de DNS pode bloquear algum site inofensivo. Para desligar, veja `beni/MUDANCAS.md`.
- O `src/index.html` (e outros arquivos com textos) já vem em pt-BR, não é mais um modelo com `{{…}}`. O `scripts/install.sh` original continua funcionando, mas o caminho recomendado é o `instalar.sh`.
- ROMs comerciais não são fornecidas. Use cópias dos seus próprios discos/cartuchos ou jogos homebrew.
