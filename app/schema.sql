PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS brands (
  id     INTEGER PRIMARY KEY,
  name   TEXT NOT NULL UNIQUE,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS sub_brands (
  id       INTEGER PRIMARY KEY,
  brand_id INTEGER NOT NULL REFERENCES brands(id),
  name     TEXT NOT NULL,
  UNIQUE (brand_id, name)
);

CREATE TABLE IF NOT EXISTS stages (
  id     INTEGER PRIMARY KEY,
  name   TEXT NOT NULL UNIQUE,
  rank   INTEGER NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS users (
  id     INTEGER PRIMARY KEY,
  name   TEXT NOT NULL UNIQUE,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS lots (
  id            INTEGER PRIMARY KEY,
  brand_id      INTEGER NOT NULL REFERENCES brands(id),
  sub_brand_id  INTEGER REFERENCES sub_brands(id),
  ct_number     TEXT NOT NULL,
  material_code TEXT,
  fabric        TEXT,
  total_qty     INTEGER NOT NULL CHECK (total_qty > 0),
  acr           INTEGER,
  fi_date       DATE,
  fabric_date   DATE,
  remark        TEXT,
  created_at    TIMESTAMP NOT NULL,
  closed_at     TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_lots_ct   ON lots(ct_number);
CREATE INDEX IF NOT EXISTS ix_lots_open ON lots(closed_at);

CREATE TABLE IF NOT EXISTS positions (
  lot_id     INTEGER NOT NULL REFERENCES lots(id) ON DELETE CASCADE,
  stage_id   INTEGER NOT NULL REFERENCES stages(id),
  qty        INTEGER NOT NULL CHECK (qty > 0),
  entered_at TIMESTAMP NOT NULL,
  PRIMARY KEY (lot_id, stage_id)
);

CREATE TABLE IF NOT EXISTS movements (
  id            INTEGER PRIMARY KEY,
  lot_id        INTEGER NOT NULL REFERENCES lots(id) ON DELETE CASCADE,
  from_stage_id INTEGER REFERENCES stages(id),
  to_stage_id   INTEGER NOT NULL REFERENCES stages(id),
  qty           INTEGER NOT NULL CHECK (qty > 0),
  moved_at      TIMESTAMP NOT NULL,
  moved_by      INTEGER REFERENCES users(id),
  note          TEXT,
  reverses_id   INTEGER REFERENCES movements(id)
);
CREATE INDEX IF NOT EXISTS ix_mov_lot      ON movements(lot_id, moved_at);
CREATE INDEX IF NOT EXISTS ix_mov_reverses ON movements(reverses_id);
