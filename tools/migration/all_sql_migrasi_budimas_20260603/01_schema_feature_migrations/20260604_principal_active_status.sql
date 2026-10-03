ALTER TABLE principal
  ADD COLUMN IF NOT EXISTS aktif BOOLEAN NOT NULL DEFAULT TRUE;

UPDATE principal
SET aktif = TRUE
WHERE aktif IS NULL;

CREATE INDEX IF NOT EXISTS idx_principal_aktif
  ON principal (aktif);
