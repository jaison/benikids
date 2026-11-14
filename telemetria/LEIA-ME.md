# Telemetria anônima (Cloudflare Worker + D1)

Endereço: `https://telemetria.benikids.app`. O Worker não grava IP nem cabeçalhos.

| Rota | O quê | Quando |
|---|---|---|
| `/v1/ping` | o computador: versão, sistema, CPU, memória, placa de vídeo, menu, tela, idioma | 1×/dia, padrão ligado |
| `/v1/problema` | instalação que falhou, app que fecha sozinho, menu nativo que caiu (texto já limpo no computador) | quando acontece, com a telemetria ligada |
| `/v1/uso` | por criança: número aleatório, faixa de idade, menino/menina, minutos por app e categoria em cada dia | 1×/dia, **só se os pais marcarem** |
| `/v1/apagar` | apaga o que esta instalação e as suas crianças enviaram | botão em Pais → Sistema |

Limpeza automática (cron diário): uso com mais de 12 meses, problemas com mais de 6 meses.
Detalhes em `src/telemetria.py` e `docs/PRIVACY.md`.

## Problemas viram Issues no GitHub

No cron diário, cada assinatura de problema nova vira uma Issue em `jaison/benikids`
(etiqueta `telemetria`, no máximo 5 novas por dia); se a assinatura já tem Issue, ganha um
comentário com as ocorrências novas. O repositório é público, então a Issue leva só a
assinatura, as contagens, as versões e os sistemas: nunca o fim do log nem o id da
instalação. Sem o segredo `GITHUB_TOKEN` o Worker não faz nada disso.

O token é *fine-grained*, só do repositório `jaison/benikids`, com **Issues: Read and write**:

```bash
npx wrangler@3 secret put GITHUB_TOKEN
```

## Publicar (uma vez)

```bash
cd telemetria
npx wrangler@3 login
npx wrangler@3 d1 create benikids-telemetria       # copie o database_id para o wrangler.toml
npx wrangler@3 d1 execute benikids-telemetria --remote --file schema.sql
npx wrangler@3 deploy                              # publica em telemetria.benikids.app
```

## Consultas

```bash
npx wrangler@3 d1 execute benikids-telemetria --remote --command \
  "SELECT plataforma, sistema, gpu, menu, COUNT(*) n FROM instalacoes
   WHERE ultima >= date('now','-30 day') GROUP BY 1,2,3,4 ORDER BY n DESC"
```

Instalações ativas = último envio nos últimos 30 dias.

```bash
# apps mais usados por faixa de idade nos últimos 30 dias
npx wrangler@3 d1 execute benikids-telemetria --remote --command \
  "SELECT u.faixa, a.app, SUM(a.minutos) min, COUNT(DISTINCT a.crianca) criancas
   FROM uso_apps a JOIN uso u USING (crianca, dia)
   WHERE a.dia >= date('now','-30 day') GROUP BY 1,2 ORDER BY 1, min DESC"

# problemas mais comuns
npx wrangler@3 d1 execute benikids-telemetria --remote --command \
  "SELECT assinatura, COUNT(*) n, COUNT(DISTINCT id) maquinas, MAX(recebido) ultimo
   FROM problemas GROUP BY 1 ORDER BY n DESC LIMIT 20"
```
