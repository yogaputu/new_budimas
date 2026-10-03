CREATE TABLE IF NOT EXISTS perusahaan_cabang (
    id SERIAL PRIMARY KEY,
    id_perusahaan INTEGER NOT NULL REFERENCES perusahaan(id) ON DELETE CASCADE,
    id_cabang INTEGER NOT NULL REFERENCES cabang(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_perusahaan_cabang_unique
    ON perusahaan_cabang (id_perusahaan, id_cabang);

CREATE INDEX IF NOT EXISTS idx_perusahaan_cabang_perusahaan
    ON perusahaan_cabang (id_perusahaan);

CREATE INDEX IF NOT EXISTS idx_perusahaan_cabang_cabang
    ON perusahaan_cabang (id_cabang);

INSERT INTO perusahaan_cabang (id_perusahaan, id_cabang)
SELECT DISTINCT c.id_perusahaan, c.id
FROM cabang c
JOIN perusahaan p ON p.id = c.id_perusahaan
WHERE c.id_perusahaan IS NOT NULL
ON CONFLICT (id_perusahaan, id_cabang) DO NOTHING;
