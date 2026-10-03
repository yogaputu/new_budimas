-- Customer multi branch/company scope.
-- Keeps customer.id_cabang as the primary/default branch for backward compatibility.

ALTER TABLE customer
  ADD COLUMN IF NOT EXISTS id_cabang_list varchar(255),
  ADD COLUMN IF NOT EXISTS id_perusahaan_list varchar(255);

UPDATE customer
SET id_cabang_list = id_cabang::text
WHERE (id_cabang_list IS NULL OR id_cabang_list = '')
  AND id_cabang IS NOT NULL;

UPDATE customer AS c
SET id_perusahaan_list = cb.id_perusahaan::text
FROM cabang AS cb
WHERE cb.id = c.id_cabang
  AND cb.id_perusahaan IS NOT NULL
  AND (c.id_perusahaan_list IS NULL OR c.id_perusahaan_list = '');
