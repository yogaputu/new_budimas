CREATE TABLE IF NOT EXISTS master_ppn (
    id SERIAL PRIMARY KEY,
    kode VARCHAR(30) UNIQUE,
    nama VARCHAR(100) NOT NULL,
    persentase DOUBLE PRECISION NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    keterangan TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP
);

INSERT INTO master_ppn (kode, nama, persentase, is_active, keterangan)
VALUES
    ('NON_PPN', 'Non PPN', 0, TRUE, 'Produk tidak dikenakan PPN'),
    ('PPN_11', 'PPN 11%', 11, TRUE, 'Tarif PPN umum 11%')
ON CONFLICT (kode) DO UPDATE
SET nama = EXCLUDED.nama,
    persentase = EXCLUDED.persentase,
    is_active = EXCLUDED.is_active,
    updated_at = NOW();

ALTER TABLE produk
ADD COLUMN IF NOT EXISTS id_ppn INTEGER;

UPDATE produk p
SET id_ppn = m.id
FROM master_ppn m
WHERE p.id_ppn IS NULL
  AND (
    (COALESCE(p.ppn, 0) <= 0 AND m.kode = 'NON_PPN')
    OR (COALESCE(p.ppn, 0) = m.persentase)
  );

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'produk_id_ppn_fkey'
    ) THEN
        ALTER TABLE produk
        ADD CONSTRAINT produk_id_ppn_fkey
        FOREIGN KEY (id_ppn) REFERENCES master_ppn(id);
    END IF;
END $$;
