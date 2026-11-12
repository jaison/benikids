# gpui-fast-wgpu 0.1.14 com patch para GPUs antigas

`gpui-fast-wgpu/` é o crate [`gpui-fast-wgpu` 0.1.14](https://crates.io/crates/gpui-fast-wgpu)
(Apache-2.0, licença em `gpui-fast-wgpu/LICENSE`) com as mudanças de `gpui-fast-wgpu-gl.patch`, usado
via `[patch.crates-io]` no `cliente/Cargo.toml`. Para gerar o patch de novo:
`diff -ru ~/.cargo/registry/src/*/gpui-fast-wgpu-0.1.14 gpui-fast-wgpu`.

## As mudanças

1. **GL nativo sem compute** (`wgpu_context.rs`, `required_limits`). Com o backend GL, pede ao device os
   limites que o adaptador tem. Antes pedia `Limits::downlevel_defaults()`, que exige compute
   (`max_compute_workgroups_per_dimension` etc.), e uma GLES 3.0 (Intel HD 2000/3000, Sandy Bridge) não
   tem compute: o device falhava e o gpui caía no llvmpipe.
2. **Instâncias sem storage buffer no GL nativo** (`uses_webgl_instance_data`). O transporte por textura,
   que já existe para WebGL, passa a valer também para `WgpuBackend::Native(Backend::Gl)`. Sem
   isso o layout de instâncias pede `VERTEX_STORAGE`, que a GLES 3.0 não tem, e toda cena falha com
   "scene too large… maximum of 0".
3. **Recusar o renderizador por CPU sob pedido** (`WgpuContext::new`). Com `GPUI_RECUSAR_SOFTWARE=1`, o
   llvmpipe é pulado (como já acontecia na recuperação de "device lost"), e a abertura da janela falha.
   O `beni-menu` usa isso para voltar ao menu do navegador quando a sessão está sem GPU.
4. **Emojis coloridos como fallback** (`cosmic_text_system.rs`, `load_family`). Fontes de emoji conhecidas
   (`NotoColorEmoji`) podem ser carregadas mesmo sem o glifo "m". Sem isso não dá para pô-las na lista de
   fallbacks do usuário, e emojis como 📚 e 🎮 saem monocromáticos da "Noto Sans Symbols2".

## Para propor no upstream (longbridge/gpui-fast)

Título: *wgpu: support native GL adapters without compute (GLES 3.0) and color emoji fallbacks*

> On Linux machines whose only hardware adapter is GL without compute shaders (e.g. Intel HD 2000/3000,
> GLES 3.0, no Vulkan), gpui-fast falls back to llvmpipe. Native GL currently requests
> `Limits::downlevel_defaults()`, which needs compute, and uses storage-buffer instance data, which GLES
> 3.0 lacks in vertex shaders. This patch (1) requests the adapter's own limits on the GL backend and
> (2) reuses the existing WebGL texture-based instance transport for `Native(Backend::Gl)`. Measured on a
> Celeron B800 + HD 2000: the window renders on the GPU at ~1% CPU idle, versus ~55% of a core on llvmpipe.
> It also (3) allows known emoji fonts to load as user fallbacks even though they have no Latin "m"
> glyph, so `FontFallbacks(["Noto Color Emoji"])` works, and (4) adds an opt-in env var to reject software
> adapters at startup, so apps can fall back to another UI.

Os itens 1, 2 e 4 da lista acima são gerais. O 3 (variável de ambiente) talvez seja melhor como opção
da API (`WindowOptions`) no upstream.
