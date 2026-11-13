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
