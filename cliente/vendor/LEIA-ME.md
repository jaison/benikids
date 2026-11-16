# gpui-fast-wgpu 0.1.16 com um patch mínimo

`gpui-fast-wgpu/` é o crate [`gpui-fast-wgpu` 0.1.16](https://crates.io/crates/gpui-fast-wgpu)
(Apache-2.0, licença em `gpui-fast-wgpu/LICENSE`) com a mudança de `gpui-fast-wgpu-software.patch`, usado
via `[patch.crates-io]` no `cliente/Cargo.toml`. Para gerar o patch de novo:
`diff -ru ~/.cargo/registry/src/*/gpui-fast-wgpu-0.1.16 gpui-fast-wgpu`.

## O que já está no upstream

O suporte a GL nativo sem compute (Intel HD 2000/3000, GLES 3.0) e os emojis coloridos como fallback
entraram no gpui-fast pelo nosso PR [longbridge/gpui-fast#141](https://github.com/longbridge/gpui-fast/pull/141),
publicado na 0.1.16. Até a 0.1.14 isso vinha deste `vendor/`.

## O que continua aqui

**Recusar o renderizador por CPU sob pedido** (`WgpuContext::new`). Com `GPUI_RECUSAR_SOFTWARE=1`, o
llvmpipe é pulado (como já acontece na recuperação de "device lost") e a abertura da janela falha. O
`beni-menu` usa isso para voltar ao menu do navegador quando a sessão está sem GPU. Ficou fora do PR
porque as regras do upstream não aceitam API pública nova. Se um dia virar opção da API
(`WindowOptions`), dá para tirar este `vendor/`.
