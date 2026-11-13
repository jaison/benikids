# Telemetria anônima (Cloudflare Worker + D1)

Cada instalação do Benikids manda **um envio por dia**, se os pais não desligarem
(Pais → Sistema). O conteúdo está em `src/telemetria.py` e em `docs/PRIVACY.md`:
um número aleatório da instalação, a versão, o sistema, a CPU, a memória, a placa de vídeo,
o tipo de menu, a resolução da tela e o idioma. **Nada sobre as crianças nem sobre o uso**,
e o Worker não grava o IP.

## Publicar (uma vez)

```bash
cd telemetria
npx wrangler@3 login
npx wrangler@3 d1 create benikids-telemetria       # copie o database_id para o wrangler.toml
npx wrangler@3 d1 execute benikids-telemetria --remote --file schema.sql
npx wrangler@3 deploy                              # mostra o endereço *.workers.dev
```

O endereço vai em `ENDERECO` no `src/telemetria.py`.

## Consultas

```bash
npx wrangler@3 d1 execute benikids-telemetria --remote --command \
  "SELECT plataforma, sistema, gpu, menu, COUNT(*) n FROM instalacoes
   WHERE ultima >= date('now','-30 day') GROUP BY 1,2,3,4 ORDER BY n DESC"
```

Instalações ativas = último envio nos últimos 30 dias.
