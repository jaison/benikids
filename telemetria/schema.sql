-- Uma linha por instalação do Benikids. Sem IP, sem nada sobre as crianças.
CREATE TABLE IF NOT EXISTS instalacoes (
  id          TEXT PRIMARY KEY,  -- aleatório, criado na instalação
  primeira    TEXT NOT NULL,     -- data (UTC) do primeiro envio
  ultima      TEXT NOT NULL,     -- data (UTC) do último envio
  envios      INTEGER NOT NULL DEFAULT 1,
  versao      TEXT,
  plataforma  TEXT,              -- windows | linux
  sistema     TEXT,              -- ex.: "Windows 10 22H2", "Linux Mint 22.3"
  cpu         TEXT,
  ram_gb      INTEGER,
  gpu         TEXT,
  menu        TEXT,              -- nativo | web
  tela        TEXT,              -- ex.: "1366x768"
  idioma      TEXT
);

-- Uso por criança (só com o consentimento dos pais). crianca = número aleatório; sem nome,
-- sem data de nascimento (só a faixa). Apagado depois de 12 meses (cron do Worker).
CREATE TABLE IF NOT EXISTS uso (
  crianca     TEXT NOT NULL,
  dia         TEXT NOT NULL,
  faixa       TEXT,
  genero      TEXT,
  minutos     INTEGER,
  categorias  TEXT,              -- JSON {categoria: minutos}
  PRIMARY KEY (crianca, dia)
);
CREATE TABLE IF NOT EXISTS uso_apps (
  crianca     TEXT NOT NULL,
  dia         TEXT NOT NULL,
  app         TEXT NOT NULL,
  nome        TEXT,
  categoria   TEXT,
  minutos     INTEGER,
  PRIMARY KEY (crianca, dia, app)
);

-- Problemas (instalação que falha, app que fecha sozinho...), já limpos no computador.
CREATE TABLE IF NOT EXISTS problemas (
  n           INTEGER PRIMARY KEY AUTOINCREMENT,
  recebido    TEXT NOT NULL,
  id          TEXT,              -- instalação
  versao      TEXT,
  plataforma  TEXT,
  sistema     TEXT,
  etapa       TEXT,
  assinatura  TEXT,
  detalhe     TEXT
);
CREATE INDEX IF NOT EXISTS problemas_assinatura ON problemas (assinatura);

-- Uma Issue pública no GitHub por assinatura de problema (cron diário do Worker; só com o
-- segredo GITHUB_TOKEN). A Issue leva só a assinatura, contagens, versões e sistemas:
-- nunca o detalhe (fim de log) nem o id da instalação.
CREATE TABLE IF NOT EXISTS issues (
  chave       TEXT PRIMARY KEY,  -- assinatura limpa
  numero      INTEGER NOT NULL   -- número da Issue
);
-- até que problemas.n o cron já olhou
CREATE TABLE IF NOT EXISTS issues_estado (
  um          INTEGER PRIMARY KEY CHECK (um = 1),
  ate_n       INTEGER NOT NULL
);
