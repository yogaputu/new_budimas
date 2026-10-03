BEGIN;

ALTER TABLE public.coa
  ADD COLUMN IF NOT EXISTS saldo_awal DOUBLE PRECISION DEFAULT 0;

CREATE TABLE IF NOT EXISTS public.coa_opening_balance (
  id SERIAL PRIMARY KEY,
  id_cabang INTEGER,
  id_perusahaan INTEGER NOT NULL,
  id_coa INTEGER NOT NULL,
  saldo_debit DOUBLE PRECISION NOT NULL DEFAULT 0,
  saldo_kredit DOUBLE PRECISION NOT NULL DEFAULT 0,
  tanggal_saldo DATE NOT NULL,
  keterangan TEXT,
  status VARCHAR(20) NOT NULL DEFAULT 'draft',
  id_jurnal INTEGER,
  created_by INTEGER,
  posted_by INTEGER,
  posted_at TIMESTAMP,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
  CONSTRAINT coa_opening_balance_one_side_check CHECK (
    (COALESCE(saldo_debit, 0) > 0 AND COALESCE(saldo_kredit, 0) = 0)
    OR
    (COALESCE(saldo_kredit, 0) > 0 AND COALESCE(saldo_debit, 0) = 0)
  )
);

CREATE INDEX IF NOT EXISTS idx_coa_opening_balance_company
  ON public.coa_opening_balance (id_perusahaan, id_cabang, tanggal_saldo);

CREATE INDEX IF NOT EXISTS idx_coa_opening_balance_coa
  ON public.coa_opening_balance (id_coa, status);

INSERT INTO public.fitur_mal (id_fitur_mal, nama_fitur_mal)
SELECT 34, 'Saldo Awal COA'
WHERE NOT EXISTS (
  SELECT 1 FROM public.fitur_mal WHERE id_fitur_mal = 34
);

WITH equity_category AS (
  SELECT COALESCE(
    (
      SELECT id_category
      FROM public.coa_category
      WHERE LOWER(nama_kategori) LIKE '%modal%'
         OR LOWER(nama_kategori) LIKE '%ekuitas%'
      ORDER BY id_category
      LIMIT 1
    ),
    (
      SELECT id_category
      FROM public.coa_category
      ORDER BY id_category
      LIMIT 1
    )
  ) AS id_category
),
company_scope AS (
  SELECT id
  FROM public.perusahaan
),
missing_balance_coa AS (
  SELECT cs.id AS id_perusahaan, ec.id_category
  FROM company_scope cs
  CROSS JOIN equity_category ec
  WHERE ec.id_category IS NOT NULL
    AND NOT EXISTS (
      SELECT 1
      FROM public.coa c
      WHERE c.id_perusahaan = cs.id
        AND LOWER(TRIM(c.nama_akun)) IN ('saldo awal', 'modal saldo awal', 'modal / saldo awal')
    )
)
INSERT INTO public.coa (
  id_kategori,
  id_perusahaan,
  nomor_akun,
  nama_akun,
  is_active,
  created_at,
  created_by,
  parent_id,
  principal_id,
  saldo_awal
)
SELECT
  id_category,
  id_perusahaan,
  '3-99999',
  'Saldo Awal',
  TRUE,
  NOW(),
  NULL,
  NULL,
  NULL,
  0
FROM missing_balance_coa;

WITH balance_coa AS (
  SELECT DISTINCT ON (id_perusahaan)
    id_perusahaan,
    id_coa
  FROM public.coa
  WHERE LOWER(TRIM(nama_akun)) IN ('saldo awal', 'modal saldo awal', 'modal / saldo awal')
  ORDER BY id_perusahaan, id_coa
)
INSERT INTO public.jurnal_mal (
  id_perusahaan,
  id_fitur_mal,
  main_coa_id,
  nama_mal,
  created_at,
  update_at,
  created_by
)
SELECT
  bc.id_perusahaan,
  34,
  bc.id_coa,
  'Saldo Awal COA',
  NOW(),
  NOW(),
  NULL
FROM balance_coa bc
WHERE NOT EXISTS (
  SELECT 1
  FROM public.jurnal_mal jm
  WHERE jm.id_perusahaan = bc.id_perusahaan
    AND jm.id_fitur_mal = 34
);

UPDATE public.coa c
SET saldo_awal = COALESCE((
  SELECT SUM(COALESCE(ob.saldo_debit, 0) - COALESCE(ob.saldo_kredit, 0))
  FROM public.coa_opening_balance ob
  WHERE ob.id_coa = c.id_coa
    AND COALESCE(ob.status, 'draft') != 'deleted'
), 0);

COMMIT;
