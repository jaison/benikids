# Menu nativo (`beni-menu`)

A tela das crianças em Rust, desenhada pela GPU com o [gpui-fast](https://github.com/longbridge/gpui-fast).
Substitui o Firefox em modo quiosque que mostrava o menu. Fala com o mesmo servidor Python local
(`src/server.py`, porta 38431) e só desenha a tela da criança. A **área dos pais** continua no navegador,
que abre só quando um adulto toca em **Pais**.

## Por quê: medido no notebook do Beni

Notebook: Celeron B800 (2 núcleos, 1,5 GHz), 2,7 GB de RAM, Intel HD 2000.
CPU em % de **um** núcleo, só o processo do menu:

| | Firefox (menu web) | `beni-menu` |
|---|---|---|
| Abrir a janela | ~6 s | 0,8–1,5 s |
| Memória (PSS) | 577–657 MB | ~204 MB |
| Escolha (Aprender/Jogar), parado | 0,8% | 0,8% |
| Escolha, navegando 10 teclas/s | 7,2% | 5,2% |
| Lista de jogos (tema Herói), parado | **29,2%** | 0,7% |
| Lista de jogos, navegando | 17,8% | 5,6% |
| Atrás de um jogo aberto | — | 0,6% |

Junto com o menu nativo, três custos fixos que existiam também com o Firefox foram cortados:

| Processo | Antes | Depois |
|---|---|---|
| Laço do `cozy-kids-launcher` (checava os processos com `python3` 2×/s) | 18% | 0,7% |
| Servidor parado (relia, validava e copiava o `config.json` a cada requisição; procurava ~40 programas no PATH; relia o `controles.json` a cada evento de analógico) | 2,9% | 0,6% |
| Servidor com um jogo aberto | 2,9% | 1,1% |

## Como funciona

- O `cozy-kids-launcher` abre `~/.local/share/cozy-kids-launcher/beni-menu` no lugar do navegador e o
  registra como o processo "browser". Por isso o resto continua igual:
  - o servidor manda as teclas do controle (`xdotool`) só quando a janela do menu está na frente;
  - o ✕ do overlay e o Start+Select trazem o menu de volta;
  - "Sair" encerra o menu.
- **Sem GPU utilizável**, o menu sai com o código 75 e o script volta para o menu no navegador nessa sessão.
  Isso acontece quando a sessão perdeu o `/dev/dri` (tampa fechada ou tela de bloqueio com outro usuário
  ativo). O renderizador por CPU (llvmpipe) é recusado de propósito (`GPUI_RECUSAR_SOFTWARE=1`), porque
  seria mais lento que o Firefox.
- Se o menu cair:
  - logo no começo, o script volta para o navegador;
  - depois de aberto, o script o reabre até 3 vezes e então volta para o navegador.
- Para usar o menu web de novo: `echo web > ~/.config/cozy-kids-launcher/menu`. Apague o arquivo para
  voltar ao nativo.
- **Páginas que continuam no navegador.** A área dos pais, os sites "embutidos" e a biblioteca de mídia
  abrem no navegador por `/cliente.html?ir=<página>`. Quando a página voltaria para o menu, o
  `frontend/cliente-nativo.js` avisa o servidor (`POST /api/cliente/voltar`). O menu nativo vê o contador
  em `GET /api/cliente/estado`, fecha o navegador e volta para a frente.
- Log: `~/.cache/cozy-kids-launcher/menu-nativo.log`.

## O que foi portado (src/frontend → src/menu.rs)

- Escolha Aprender / Passatempo / Jogar, com as barras de tempo, os cadeados e os textos da regra de aprendizado.
- Lista filtrada com "Voltar", o selo da categoria e as páginas (setas nas laterais; a seta na borda troca de página).
- Grade grande (4) e pequena (9).
- Capas `img:covers/...`, o selo 🎮 e a estrela no último app aberto (`~/.cache/cozy-kids-launcher/menu-estado.json`).
- Medidores de tempo no rodapé, mensagens de "o tempo acabou", bloqueio por horário (perfil e app), aviso e
  bloqueio do timer (com PIN e +15/+30/+60), PIN para Sair/Desligar/trocar de perfil e escolha de perfil.
- Relógio, bateria e o selo de atualização disponível.
- Os 21 temas (`src/tema.rs`, traduzidos do CSS), fontes dos temas e emojis coloridos.
- Fundo que "respira" (movimento do tema, só com a janela ativa), sons de retorno (mesmos tons do web) e
  estrelinhas de comemoração.
- Voz (`/api/feedback/speak`) e texto grande.

**Não portado** (pouco usado; continua no web): alto contraste, foco reforçado, tons por hora do dia,
gestos de deslizar no touch e as animações de troca de página.

## Compilar

Pacotes (Ubuntu/Mint):
`libxkbcommon-x11-dev libxkbcommon-dev libx11-xcb-dev libxcb1-dev libfontconfig-dev libfreetype-dev libvulkan-dev libzstd-dev libwayland-dev clang cmake`.
O Rust estável vem do [rustup](https://rustup.rs).

```bash
cd cliente
cargo test --release
cargo build --release          # rápido para testar (reaproveita o que já compilou)
cargo build --profile dist     # o binário distribuído (LTO, sem símbolos)
```

Num Celeron com 2,7 GB, a primeira compilação leva ~30 min e precisa de ~4 GB de swap extra; as
seguintes, 30 s a 2 min. O `instalar.sh` instala o binário de `cliente/bin/` (o atualizador baixa) ou de
`cliente/target/{dist,release}/`.

## Distribuição

O workflow `.github/workflows/menu-nativo.yml` compila no Ubuntu 22.04 (glibc 2.35, para rodar também no
Mint 21) e roda os testes. Numa **Release publicada**, ele anexa `beni-menu-linux-x86_64` e o `.sha256`.
O `beni-atualizar`:
- baixa o binário junto com o pacote;
- confere o SHA-256;
- espera até 90 min depois da publicação, caso o build ainda esteja rodando;
- segue sem o binário se a Release não tiver um. Nesse caso fica o menu nativo que já estava instalado,
  ou o navegador.

## gpui-fast com patch (vendor/)

A Intel HD 2000 não tem Vulkan, só GL 3.3 / GLES 3.0, sem compute. O gpui-fast 0.1.14 recusa essa GL e cai
no llvmpipe. O `vendor/gpui-fast-wgpu` é o `gpui-fast-wgpu` 0.1.14 com o patch em
`vendor/gpui-fast-wgpu-gl.patch`; o porquê de cada mudança está em `vendor/LEIA-ME.md`. Versões fixadas
em `Cargo.toml` (`=0.1.14`) e `Cargo.lock`.
