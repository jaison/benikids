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
- Vale para o programa que usa o DNS do sistema. No Linux, o Firefox tem o DNS‑over‑HTTPS travado e o Chromium dos jogos desliga o DoH. No Windows, o Edge do computador e o Chrome instalado também desligam o DoH. Outro navegador com DNS seguro (o Firefox, por exemplo) pode furar.
- **No Windows** o mesmo filtro entra na instalação, no lote que já pede a senha do administrador (não há um UAC só para o DNS). Vale para as placas de rede ativas. Ao ligar, o DNS anterior de cada placa (IPv4 e IPv6, automático ou manual) fica em `C:\ProgramData\Benikids\dns-familia-anterior.json`, com a mesma ACL do script. Ao desligar, a placa volta ao que era; sem esse registro, volta ao automático. O IPv4 recebe o CleanBrowsing. O IPv6 da família (`2a0d:2a00:1::` e `2a0d:2a00:2::`; o `::1` é o filtro Adulto) só entra na placa que tem IPv6 de verdade. Se o IPv6 não aceitar, a placa fica sem servidor DNS IPv6 e o IPv4 filtrado continua. Uma placa que aparecer depois (Wi‑Fi novo, outro adaptador) é reaplicada pela tarefa agendada `Benikids DNS Familia`, que roda como o sistema, sem pedir senha de novo: guarda o DNS daquela placa e aplica o filtro. **Sair** não desliga o filtro: é proteção do computador. Para desligar, Pais → Sistema → **Filtro de internet** (o Windows pede a senha). Ligar e desligar deixam uma linha em `%USERPROFILE%\.cache\cozy-kids-launcher\beni-windows.log` e em `C:\ProgramData\Benikids\dns-familia.log`.
- **uBlock Origin** nos sites, já ajustado para os jogos do Escola Games abrirem sem anúncio.
- **Sites limpos com CSS próprio**:
  - Escola Games sem o menu "Jogos";
  - Colorir sem a barra de cima, banners e redes sociais;
  - Autodraw sem "Share" e links externos;
  - Kiddo Games sem "Spread the fun" (X, Facebook, Pinterest);
  - Music Lab e PhET sem os links que saem do experimento.

  No Linux isso é o `userContent.css` do Firefox. No Windows é a extensão do Edge (`src/edge/sites-limpos/`), as mesmas regras de CSS. Não vai no uBlock Origin Lite: filtrar a Escola Games travava o jogo, e o uBOL não tem filtro cosmético avulso na política.
  As páginas proibidas também ficam bloqueadas por política do Firefox (no Windows, `URLBlocklist` do Edge).
  **No Windows**, a mesma extensão limita a navegação da janela do site aos domínios daquele tile (e, no PhET, só `/sims/html/` e a página local). Outro site volta para o tile. Não pede senha de administrador: as regras vão na cópia da extensão, no cache, ao abrir. O Firefox do Linux não tem essa lista; lá o bloqueio continua sendo o dos caminhos do `policies.json` mais o CSS.
  O comando do Chromium monta as flags num lugar só (`flags_do_chromium`): um `--disable-features` e um `--load-extension` com a lista de pastas. A extensão de controle entra nessa lista; uma segunda flag de qualquer uma das duas é ignorada pelo navegador.
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
- **Coleções do itch.io**: cada perfil recebe a coleção do menino ou da menina (os dois endereços públicos ficam no programa). Jogo adicionado na coleção vira ícone ligado, na categoria Jogar, com capa; jogo removido some. O que os pais mudaram (ligado, categoria, nome) fica. Perfil sem menino/menina não recebe coleção. A sincronização roda 2 min depois de abrir o menu e a cada 30 min (no Linux, também no login e no timer). Para forçar outra coleção num perfil, o id dele em `itch-colecoes.json` manda.
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
- As coleções do itch.io seguem o menino/menina de cada perfil (menina → coleção bea, menino → coleção beni). Um perfil antigo sem esse campo não recebe coleção. Para trocar a de um perfil, edite `~/.config/cozy-kids-launcher/itch-colecoes.json`: o **id do perfil** aponta para a URL pública, e essa entrada manda sobre o gênero. Não apague o arquivo de um notebook que já o tem.

Rodar `./instalar.sh` de novo atualiza os arquivos e **não apaga** a configuração, os logins
salvos nem os jogos. Use `./instalar.sh --sem-apps` para não mexer em apt/flatpak.

---

## Como funciona (resumo técnico)

```
login → ~/.config/autostart → cozy-iniciar
          ├─ cozy-itch-sync      (invólucro de itch_sync.py: coleções → tiles "itch-*")
          └─ cozy-kids-launcher  (servidor Python em 127.0.0.1:38431 + menu nativo beni-menu;
                                  a mesma sincronização roda numa thread do servidor)
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
| `src/dns_familia.py` | DNS CleanBrowsing no Windows (lote com UAC + tarefa agendada) e o interruptor da área dos pais |
| `src/sites/tiles.json`, `src/sites_windows.py` | tiles `special:` que um Windows já instalado recebe uma vez |
| `src/edge/sites-limpos/` | extensão do Edge: CSS dos sites e, ao abrir, o limite de navegação do tile |
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
| `src/itch_sync.py`, `src/jogo.html` | coleções do itch.io (Windows e Linux). No Linux a moldura abre em file://; no Windows o Edge abre o `jogo.html` da instalação também em file:// (`benikids-jogo:` no config) |
| `beni/chromium/cozy-jogo.html` | a mesma moldura, aberta pelo Chromium no Linux |
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

**O id da espera na linha de comando.** O endereço com `#espera=<id>` fica na linha de
comando do navegador, que outro programa do mesmo usuário consegue ler. Por isso cada espera
aceita **um pedido esperando de cada vez**: um 2º pedido simultâneo recebe 409 e vira o
evento `pais.espera_ocupada` no diagnóstico (sem o id). Assim, um programa não consegue
esperar junto com a página e disputar o token quando o PIN chega. O que sobra: um programa
que leia o id e comece a esperar ANTES da página pode levar o token. Nesse caso a página
recebe 409 e cai no PIN dela, e o aviso fica no log. Tirar o id da linha de comando (a
página buscar o id num endereço de uso único nos primeiros segundos) só mudaria a corrida
de lugar: o mesmo programa poderia buscá-lo primeiro. O risco é baixo, porque um programa
do mesmo usuário já consegue ler o perfil do Edge, inclusive o cookie de admin.

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
  `HWND_BOTTOM` e menu `HWND_TOPMOST` (conferido a cada volta). Ao devolver, a barra de
  tarefas é avisada de que a janela é de tela cheia (`ITaskbarList2::MarkFullscreenWindow`);
  sem isso ela ficava por cima da área dos pais. **Não** usa `LockSetForegroundWindow`: a
  trava vale para todos os programas e só sai se quem destrava estiver na frente — no
  roteiro 17 a tela "Acabou o tempo!" ficou sem teclado. Em qualquer fim da espera (PIN
  aceito, cancelado, timer, navegador que fechou, erro) o menu deixa de ficar por cima.
  O Edge abre com `--disable-backgrounding-occluded-windows --disable-renderer-backgrounding
  --disable-features=CalculateNativeWinOcclusion,DnsOverHttps`, para continuar desenhando coberto
  e não trocar o DNS da família por um DNS-over-HTTPS próprio.
- **Linux (X11):** `wmctrl` põe a janela do Firefox `below`, `skip_taskbar` e `skip_pager`, e
  o menu `above`; o `xdotool` devolve o foco ao menu e, depois do PIN, ativa o Firefox.
- **Risco:** a janela nasce tentando pegar o foco; se pegar, a vigia devolve ao menu em até
  10 ms (80 ms no Linux). Uma tecla digitada bem nesse
  instante pode ir para o navegador. O Gerenciador de Tarefas do Windows lista o Edge e
  permite "Alternar para" — vale para qualquer programa e não muda com isto. No Linux, o
  Alt+Tab do xfwm4 pular janelas `skip_taskbar` precisa ser conferido no notebook.

### Windows: tecla Windows e barra de tarefas presas (`src/trava_windows.py`)
Enquanto o Benikids está aberto (menu nativo ou web, app aberto pelo menu, área dos pais),
a criança não sai pela tecla Windows nem pela barra de tarefas. Quem cuida é o iniciador
(`beni_windows.py`): é o único processo que vive do começo ao fim e reabre os outros quando
caem. O menu nativo cai e volta, e pode ser trocado pelo menu web; o overlay só existe com
um app aberto.
- **Tecla Windows:** um gancho de teclado de baixo nível (`WH_KEYBOARD_LL`, numa thread com
  fila de mensagens própria) engole LWin/RWin, e com elas todas as combinações (Win+X, Win+D,
  Win+E, Win+R, Win+Tab…), além de Ctrl+Esc, que também abre o Iniciar. Alt+Tab e
  Ctrl+Shift+Esc passam; Ctrl+Alt+Del o Windows não deixa bloquear. Não usa política
  (`NoWinKeys`), que pede administrador e logoff. O gancho é posto de novo a cada 30 s,
  porque o Windows tira em silêncio um gancho que demorou a responder.
- **Barra de tarefas** (outra thread, para a do gancho nunca esperar o Explorer):
  - `Shell_TrayWnd` e `Shell_SecondaryTrayWnd` ficam escondidas (`ShowWindowAsync(SW_HIDE)`) e
    voltam no Sair (`SW_SHOWNA`). Só isso: o Benikids **não muda nenhuma preferência do
    usuário**.
    - O "ocultar automaticamente" (`ABM_SETSTATE`) foi abandonado no roteiro 27. É uma
      preferência que o Windows grava no `StuckRects3` quando quer. Ele vazou depois de um
      Explorer reiniciado e desfez a escolha de um usuário que o desligou pelas
      Configurações, porque o registro fica atrasado em relação a elas. Ao ser ligado, o
      Kapman maximizado saiu de maximizado.
    - `SPI_SETWORKAREA` também não: o Explorer reescrevia a área (roteiro 24).
  - A barra escondida continua reservando a faixa dela, então um app maximizado para 40 px
    acima do fim da tela. Quem cobre essa faixa é o overlay do app (`overlay.py`, `TelaCheia`):
    - a cada 1 s, a janela do app que está maximizada (`IsZoomed`) e ocupa a área de trabalho
      vira **tela cheia sem moldura**. O overlay tira `WS_MAXIMIZE`, `WS_CAPTION` e
      `WS_THICKFRAME` (`SetWindowLongPtr`) e põe a janela no tamanho do monitor
      (`MonitorFromWindow` + `GetMonitorInfo`, `SetWindowPos` com `SWP_FRAMECHANGED`). Somem
      também o título e os botões minimizar/maximizar/fechar, que a pílula cobria;
    - esticar a janela ainda maximizada não segurava: no roteiro 28, o Kapman, o KBlocks e o
      Pencil2D a devolviam à área de trabalho em menos de 100 ms;
    - não usei a tela cheia dos próprios apps (a dos KDE é Ctrl+Shift+F). Ela não fica gravada
      no `*rc` de um jeito que valha para todos, e mandar a tecla seria um liga/desliga às
      cegas. A tela cheia sem moldura vale para qualquer app maximizado;
    - janelas que não estão maximizadas (Klavaro, Quinze) e as que já cobrem a tela (menu,
      Edge dos pais, jogos em tela cheia) não mudam;
    - uma janela comum do tamanho do monitor com o título para fora da tela (o Tux Paint
      com `--windowsize`, porque o `--fullscreen` e o `--fullscreen --native` saem com
      código 52 no Intel HD 4000) fica como está. No roteiro 31 ela virava tela cheia sem
      moldura, mas o SDL desfazia 4 vezes, e o roteiro 32 tirou a regra. O travamento no
      splash era o Direct3D 9 do driver NVIDIA numa GPU híbrida (roteiro 33: também
      0xC0000005 em `nvd3dumx.dll`, mesmo à mão). O catálogo agora roda o Tux Paint com
      `SDL_RENDER_DRIVER=opengl` (campo `"env"` do catálogo: só no processo daquele app; se
      o OpenGL falhar, o SDL tenta os outros renderizadores na ordem normal) e com
      `--nolockfile` (sem ele, abrir de novo menos de 30 s depois sai sem janela);
    - `"sem_moldura": false` no catálogo deixa o app só maximizado, sem a tela cheia sem
      moldura (Pingus: o SDL a desfazia 4 vezes, e o desfaz-refaz era feio);
    - se o app desfizer isso 5 vezes, o overlay devolve a moldura e a janela como era
      (maximizada, ou no retângulo de antes) e desiste daquela janela. O log diz "overlay:
      app em tela cheia sem moldura…", "o app desfez…; refeita" e "devolvida a janela como era".
  - Janela de outro app, sem travar (roteiro 31). No PC de teste, a pílula travou junto com
    o Tux Paint, e o menu parou de pintar e de receber toques por 8 min. A pílula ligava a
    fila de entrada dela à da janela da frente (`AttachThreadInput`) e chamava `ShowWindow`
    e `BringWindowToTop` enquanto o Tux Paint ainda criava a janela. As regras agora:
    - nada de `AttachThreadInput`, nem no Python nem no menu nativo. Para trazer uma janela
      para a frente: `SetForegroundWindow` direto e, se o Windows recusar, com a tecla Alt
      apertada (entrada sintética, que só entra na fila de quem está na frente);
    - janela "Não respondendo" (`IsHungAppWindow`) não é tocada, e a volta não conta para
      os limites;
    - só chamadas assíncronas (`ShowWindowAsync`, `SetWindowPos` com `SWP_ASYNCWINDOWPOS`).
      O `SetWindowLongPtr` do estilo (tela cheia sem moldura) espera o app, então só vai
      depois de ele responder a um `SendMessageTimeout` de 300 ms;
    - no overlay, tudo isso roda numa thread de trabalho (`janelas_seguras.Trabalhador`),
      nunca na thread do Tk. Se ela ficar presa, os pedidos novos são recusados, a pílula
      segue viva e o log diz "overlay: … preso há mais de 5 s numa janela de outro app".
    - nada numa janela que acabou de aparecer (roteiro 32). Ela precisa estar de pé
      (`janelas_seguras.DePe`): responder a um `SendMessageTimeout` de 300 ms em todas as
      conferências por 2 s seguidos, com o processo ocioso pelo `WaitForInputIdle` (espera
      0). Vale para trazer para a frente, maximizar e tirar a moldura. Nos KDE, a tela
      cheia sem moldura passa de 0,4–0,8 s para uns 2,5–3,5 s depois de a janela aparecer;
    - cada ação numa janela de outro app é logada ANTES, com milissegundos ("overlay: vou
      trazer o app (hwnd …)", "vou tirar a moldura", "vou maximizar", "vou mandar Alt+←").
      Num travamento, a última linha diz o que foi feito por último.
  - Vigia da pílula (`src/vigia_da_pilula.py`, uma thread do servidor no Windows), a cada 1 s
    enquanto um app está aberto:
    - pílula morta por 3 s, ou travada (sem responder a um `SendMessageTimeout` de 500 ms)
      por 6 s: encerra o overlay e abre de novo com os mesmos argumentos ("overlay: pílula
      travada; reaberta"). No máximo 3 vezes por app aberto;
    - app "Não respondendo": o tempo de uso para de contar ("app: … não responde; o tempo
      de uso não conta"). Depois de 15 s, loga "app: … não responde há N s". Com 30 s
      seguidos, FECHA o app (roteiro 33, decisão do mantenedor: com o app travado, o
      Windows põe a janela-fantasma do DWM na frente, ativa, e o ✕ da pílula não recebe o
      clique, nem pelo vigia do ✕). Encerra a pílula e o supervisor (o Job Object leva a
      árvore), traz o menu e loga "app: … travado há 30 s; fechado". O menu nativo e o web
      mostram "O jogo travou e foi fechado." uma vez (`appTravadoFechado` no
      `/api/usage/status`, por 2 min). A telemetria `app.travou:<tile>` vai com
      `fechado=True`, ou `fechado=False` se ele voltou a responder entre 15 e 30 s;
    - o ✕ (roteiro 32: com o Tux Paint travado, 6 cliques não chegaram ao Tk). O
      `on_close` loga "overlay: ✕ tocado" antes de tudo e encerra o supervisor
      (`TerminateProcess`; o Job Object leva a árvore). Cada aperto e soltura no botão vai
      para o log. Um vigia do ✕ (thread do overlay) lê o mouse direto do sistema
      (`GetAsyncKeyState`, `GetCursorPos`, `WindowFromPoint`) a cada 30 ms; se um clique
      no ✕ não virou `on_close` em 0,8 s, ele fecha o app e a pílula sozinho e manda
      `overlay.x_sem_tk:<tile>` para a telemetria;
    - app que fecha logo ao abrir: o supervisor sai com o código do app, e o servidor
      manda `app.caiu:<tile>` (NTSTATUS de erro, de 0xC0000000 para cima, com o código em
      hexa no detalhe) ou `app.fechou_sozinho:<tile>`, 1 por dia;
    - toda exceção que vai para a telemetria vai também para o `beni-windows.log`, com o
      traceback. A marca "já mandei hoje" só é gravada depois de o problema entrar na fila,
      e o envio troca o nome da fila antes de ler (o que chega no meio não se perde).
      O `overlay.pid` e o `tile-process.pid` são trocados e apagados com novas tentativas
      por até 0,5 s: o Windows recusa (WinError 32) enquanto outro processo os lê;
    - telemetria, no máximo 1 por assinatura por dia: `overlay.travou:<tile>`,
      `overlay.caiu:<tile>`, `app.travou:<tile>` e `excecao:<processo>:<Tipo>` (exceção
      não tratada no iniciador, no overlay, no servidor e no vigia, com o traceback limpo).
  - Um app por vez: o servidor recusa (429) um pedido de abertura enquanto outro está
    abrindo e nos 3 s depois de um app ter aberto, e o menu nativo não manda outro pedido
    enquanto espera a resposta. No roteiro 31, os toques represados no menu congelado
    viraram ~32 aberturas seguidas do mesmo site.
  - A pílula, o ‹ Voltar e a contagem do overlay nunca pegam o foco nem entram no Alt+Tab
    (`WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW`), mas continuam clicáveis. No roteiro 28, o
    Alt+Tab e o Jogo do Quinze deixavam o foco na pílula, e o jogo ficava sem teclado.
    - O Tk recria a janela de fora, com outro HWND, sempre que muda o exstyle que ele
      controla, por exemplo o `-alpha` ligando ou desligando o `WS_EX_LAYERED`. No roteiro
      29, o estilo ficava na janela antiga. Por isso:
      - o estilo vai na raiz (`GetAncestor(GA_ROOT)`) do `winfo_id()`;
      - o `-toolwindow` vai pelo próprio Tk;
      - no Windows, o mouse em cima da pílula leva a transparência a 0,99 e não a 1,0;
      - a cada 0,5 s e depois de cada mudança de transparência, o estilo é conferido de
        novo na janela atual e ela é posta por cima com `SWP_NOACTIVATE`, no lugar do
        `lift`/`-topmost` do Tk, que podem ativá-la.
    - O log diz uma vez por janela "overlay: pílula sem ativar (hwnd …, exstyle …)", e "o
      estilo NÃO ficou" se a leitura de volta não tiver os dois bits.
  - A barra nova de um Explorer reiniciado é escondida pelo aviso do próprio Windows
    (`SetWinEventHook` de `EVENT_OBJECT_CREATE`/`EVENT_OBJECT_SHOW`, fora de contexto, na
    thread da barra), assim que ela aparece. O log diz "barra: aviso de janela ligado" e
    "barra: aviso de janela escondeu a barra nova (…, N ms depois de ela aparecer)". Sem o autohide, ela ficava até 2 s por cima do
    jogo. A janela invisível do `TaskbarCreated` (que chega ~5 s depois) e a conferência a
    cada 250 ms ficam de reserva; depois de um reinício, a conferência roda a cada 50 ms
    por 5 s.
  - Se o foco ficar na área de trabalho (`Progman`/`WorkerW`) ou na barra por duas voltas,
    volta para a última janela que estava na frente (menu ou app). Logo depois de o Explorer
    voltar, "nenhuma janela na frente" também conta.
  - No `beni-windows.log`: "barra: vigiando", "barra: Explorer voltou; escondida de novo",
    "foco: … devolvido ao menu/app". Uma thread da trava que cair deixa "trava (barra): a
    thread caiu" com o erro: no `pythonw` não há stderr, e no pacote 22 a thread da barra
    morria no primeiro timer sem deixar rastro (lia `msg.hwnd`, mas o campo do
    `wintypes.MSG` é `hWnd`).
- **Saída:** no Sair com PIN, no `exit-kids`, quando o menu fecha e antes de instalar uma
  atualização, o `finally` do iniciador desfaz o gancho e mostra a barra. O `atexit` repete isso; a segunda chamada não
  faz nada.
- **Job da sessão:** o iniciador entra num Job Object com `KILL_ON_JOB_CLOSE`, e tudo o que ele
  abre entra junto, por herança: servidor, vigia, menu e, por eles, os apps da criança, o
  overlay e o Edge da área dos pais.
  - Se o iniciador cair, o Windows encerra tudo. Sem servidor nem vigia, um app aberto não
    teria mais limite de tempo, e o menu ficaria em tela cheia por cima da barra.
  - Os jobs do supervisor de apps e do menu ficam aninhados neste (Windows 8+).
  - Só o instalador da atualização e a instalação de apps pedida pelos pais saem do job
    (`CREATE_BREAKAWAY_FROM_JOB`), para continuar depois que o Benikids fecha.
- **Limpeza na abertura** (`queda_windows.py`): a nova instância (dona do mutex
  `Local\BeniLauncher`) encerra sempre o que sobrou de um Benikids anterior, reconhecido pelo
  caminho e não pelo nome. Sempre, e não só quando o `sessao.json` ou a
  `barra-escondida.json` ficaram: as versões até a 1.0.6 não deixavam marcador.
  - `<instalação>\beni-menu.exe`;
  - os scripts `server.py`, `timer_watchdog.py`, `overlay.py` e `process_supervisor.py` da
    instalação;
  - o navegador com perfil em `~/.cache/cozy-kids-launcher/menu-*`.
  Só conta o que é da mesma sessão do Windows. Isso acontece antes de instalar uma atualização,
  para o `beni-menu.exe` não ficar preso.
- **Instalador com o Benikids aberto:** se o `beni-menu.exe` está rodando, mas nenhum iniciador
  segura o mutex, é resto de uma queda (sem servidor, o Sair não funciona). O "Instalar
  Benikids.cmd" e a atualização automática encerram esses restos pelo mesmo critério e seguem.
  Com o iniciador vivo, o instalador continua pedindo "Pais → Sair". Os avisos do instalador
  saem com `MB_TOPMOST | MB_SETFOREGROUND`, por cima do menu, que é topmost.
- **Queda do iniciador:** o Windows desfaz o gancho e encerra o job, então a tecla Windows volta
  na hora e nenhum menu fica por cima. A barra continua escondida até:
  - o Explorer reiniciar ou a pessoa sair e entrar no Windows;
  - o Benikids abrir e fechar de novo. A `~/.cache/cozy-kids-launcher/barra-escondida.json`
    marca que a barra foi escondida e não voltou.
- **Como o adulto recupera a barra:** Ctrl+Alt+Del → Gerenciador de Tarefas → em Processos,
  "Windows Explorer" → Reiniciar. Ou abrir e fechar o Benikids.

### Windows: DNS com filtro e sites (`src/dns_familia.py`)

Os IPs são os do Linux (`185.228.168.168`, `185.228.169.168`, `2a0d:2a00:1::`, `2a0d:2a00:2::`). Na documentação do CleanBrowsing o `::1` é o filtro Adulto, que não bloqueia proxy: o Benikids fica no Family. O lote elevado da instalação grava `C:\ProgramData\Benikids\dns-familia.ps1` (ACL: SYSTEM e Administradores com controle total, Usuários só leitura, sem herança), põe `HKLM\SOFTWARE\Benikids\DnsFamilia = 1` e cria a tarefa `Benikids DNS Familia` como SYSTEM, com o caminho do script entre aspas. A tarefa sobe com o Windows e também no evento 10000 (rede conectou). Se esse evento não existir na máquina, a subida ainda reaplica. Com o registro em 0 a tarefa não põe o filtro. Se ainda existir `dns-familia-anterior.json`, ela restaura essas placas (na subida e no evento 10000) e apaga o GUID que voltou.

Antes de trocar o DNS, o script grava o anterior (registro `NameServer` vazio = automático; preenchido = manual) em `dns-familia-anterior.json`, com a mesma ACL. O DNS da placa só muda se essa gravação e a ACL deram certo. Se não der, a placa fica como está (`ipv4=erro`). Não grava de novo se a placa já está no filtro: senão o "anterior" viraria o próprio CleanBrowsing. Placa nova passa pelo mesmo caminho. Ao desligar, o registro vai a 0, a tarefa para, e cada placa com arquivo volta ao modo guardado. Se a volta falhar, a placa continua no arquivo, a área dos pais avisa e o `beni-windows.log` leva `nao voltou`. Placa que não estava na lista (USB, VPN) fica no arquivo até reaparecer; a tarefa, com o registro em 0, restaura e apaga esse GUID. Placa ativa sem arquivo volta ao automático (`ResetServerAddresses`). Placa desligada sem arquivo fica quieta. Uma atualização com o filtro já em 0 ou 1 troca o `.ps1` no lote que pede senha, sem ligar de novo o que os pais desligaram.

IPv6 só muda se a placa tem um endereço que não é link-local (`fe80::`) ou um DNS IPv6 que não seja o `fec0:0:0:ffff::1/2/3` (o Windows mostra esses quando a rede não deu DNS IPv6). Sem isso, o script não mexe no IPv6. Se `Set-DnsClientServerAddress` do IPv6 falhar, tenta o `netsh` com `validate=no` (o endereço `::` às vezes é recusado). Se ainda falhar, `address=none`: não usa `ResetServerAddresses`, que devolveria o DNS do roteador. O IPv4 já filtrado fica. O log de falha é `ipv6 sem cleanbrowsing` e, se esvaziar, `ipv6 sem servidor (o do roteador nao vale)`.

O Edge do computador ganha a política `DnsOverHttpsMode=off`. O mesmo lote do filtro põe `DnsOverHttpsMode=off` em `HKLM\SOFTWARE\Policies\Google\Chrome` e `…\Chromium`, e tira esses valores ao desligar o filtro. Não há NRPT: uma regra para todos os nomes atrapalha impressora, VPN e nome local. O DoH do próprio Windows não troca o CleanBrowsing por outro provedor (esses IPs não estão na lista automática), então não mexemos nele. Os navegadores que o Benikids abre (sites e menu) também desligam o DoH na linha de comando (`--disable-features=…DnsOverHttps`) ou, no Firefox, `network.trr.mode=5`. Um Firefox (ou outro navegador) aberto fora, com DNS seguro, continua podendo furar. O log do filtro é `C:\ProgramData\Benikids\dns-familia.log`; o do navegador é `%USERPROFILE%\.cache\cozy-kids-launcher\beni-windows.log`.

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
   - No **Windows já instalado**, o tile `special:` também precisa estar em `src/sites/tiles.json` (o teste `test_sites_windows` confere que este arquivo é o config do Linux mais as migrações). Não acrescente o id novo em `SITES_JA_ENTREGUES` (`src/sites_windows.py`): essa tupla é a foto dos sites que já vinham no pacote, para um site apagado pelos pais não voltar. Um id fora dela é oferecido uma vez (`sitesSeen`).
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
| SuperTuxKart trocava a resolução e **a tela ficava apagada** ao fechar | os atalhos sempre usam a resolução atual da tela (no Windows também `--fullscreen --screensize=<tela>` e o `config.xml` em `%APPDATA%\supertuxkart\config-0.10`) |
| SuperTuxKart no Windows perguntava sobre a internet e abria "Criar usuário" com o nome do usuário do Windows (dado pessoal) | antes de cada abertura: `enable_internet` = 2 (não permitido) no `config.xml` (um mínimo com `version="8"` se não existir) e, sem `players.xml`, um com o jogador "Benikids" como atual |
| Luanti mostrava "Uma nova versão está disponível" (com "Visitar site") e abria em janela | antes de abrir, o `minetest.conf` ganha só as chaves que faltam: `update_information_url` vazio, `language = pt_BR`, `fullscreen = true` (Linux: `beni/bin/luanti`; Windows: ao lado da pasta `builtin` do Luanti portátil do winget) |
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
- O filtro de DNS pode bloquear algum site inofensivo. No Linux, para desligar, veja `beni/MUDANCAS.md`. No Windows: Pais → Sistema → **Filtro de internet** (pede a senha). Sair e reinstalar não desligam um filtro que os pais desligaram de propósito, nem ligam sozinhos um computador antigo: nele o filtro entra na próxima instalação de apps (o mesmo pedido de senha) ou pelo interruptor da área dos pais.
- O `src/index.html` (e outros arquivos com textos) já vem em pt-BR, não é mais um modelo com `{{…}}`. O `scripts/install.sh` original continua funcionando, mas o caminho recomendado é o `instalar.sh`.
- ROMs comerciais não são fornecidas. Use cópias dos seus próprios discos/cartuchos ou jogos homebrew.
