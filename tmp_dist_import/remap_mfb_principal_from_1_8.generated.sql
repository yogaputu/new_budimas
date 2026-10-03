\set ON_ERROR_STOP on
BEGIN;

CREATE TEMP TABLE src_mfb_18 (
  kode text,
  nama text,
  active text,
  principle text,
  jenis text,
  kodeprinciple text,
  namaprinciple text
);
\copy src_mfb_18 FROM 'D:/laragon/www/budimas/new_budimas/tmp_dist_import/mfb_principle_from_192_168_1_8.csv' WITH CSV HEADER;

CREATE TEMP TABLE current_mfb_products AS
SELECT p.id, p.kode_sku, p.nama, p.id_principal AS old_principal_id
FROM produk p
JOIN principal pr ON pr.id = p.id_principal
WHERE pr.kode = 'MFB';

CREATE TEMP TABLE source_product_mapping AS
SELECT DISTINCT ON (upper(trim(c.kode_sku)))
  c.id AS produk_id,
  c.kode_sku,
  c.nama AS produk_nama,
  c.old_principal_id,
  left(nullif(trim(s.kodeprinciple), ''), 100) AS source_principal_kode,
  left(nullif(trim(s.namaprinciple), ''), 50) AS source_principal_nama
FROM current_mfb_products c
LEFT JOIN src_mfb_18 s ON upper(trim(s.kode)) = upper(trim(c.kode_sku))
ORDER BY upper(trim(c.kode_sku));

CREATE TEMP TABLE source_principals AS
SELECT DISTINCT
  source_principal_kode AS kode,
  source_principal_nama AS nama,
  regexp_replace(upper(coalesce(source_principal_nama, '')), '[^A-Z0-9]+', '', 'g') AS nama_key
FROM source_product_mapping
WHERE source_principal_kode IS NOT NULL
  AND source_principal_nama IS NOT NULL;

CREATE TEMP TABLE existing_principal_match AS
SELECT
  sp.kode AS source_kode,
  sp.nama AS source_nama,
  p.id AS target_id,
  p.kode AS target_kode,
  p.nama AS target_nama
FROM source_principals sp
LEFT JOIN LATERAL (
  SELECT p.*
  FROM principal p
  WHERE p.kode <> 'MFB'
    AND (
      upper(trim(p.kode)) = upper(trim(sp.kode))
      OR regexp_replace(upper(coalesce(p.nama, '')), '[^A-Z0-9]+', '', 'g') = sp.nama_key
    )
  ORDER BY CASE WHEN upper(trim(p.kode)) = upper(trim(sp.kode)) THEN 0 ELSE 1 END, p.id
  LIMIT 1
) p ON true;

SELECT 'COMMIT' AS mode,
  (SELECT count(*) FROM current_mfb_products) AS current_mfb_products,
  (SELECT count(*) FROM source_principals) AS source_principals,
  (SELECT count(*) FROM existing_principal_match WHERE target_id IS NULL) AS principal_to_insert,
  (SELECT count(*) FROM source_product_mapping WHERE source_principal_kode IS NULL) AS products_without_source_mapping;

INSERT INTO principal (kode, nama, id_perusahaan)
SELECT source_kode, source_nama, 1
FROM existing_principal_match
WHERE target_id IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM principal p
    WHERE upper(trim(p.kode)) = upper(trim(existing_principal_match.source_kode))
       OR regexp_replace(upper(coalesce(p.nama, '')), '[^A-Z0-9]+', '', 'g') = regexp_replace(upper(coalesce(existing_principal_match.source_nama, '')), '[^A-Z0-9]+', '', 'g')
  );

CREATE TEMP TABLE principal_match_after_insert AS
SELECT
  sp.kode AS source_kode,
  sp.nama AS source_nama,
  p.id AS target_id,
  p.kode AS target_kode,
  p.nama AS target_nama
FROM source_principals sp
LEFT JOIN LATERAL (
  SELECT p.*
  FROM principal p
  WHERE p.kode <> 'MFB'
    AND (
      upper(trim(p.kode)) = upper(trim(sp.kode))
      OR regexp_replace(upper(coalesce(p.nama, '')), '[^A-Z0-9]+', '', 'g') = sp.nama_key
    )
  ORDER BY CASE WHEN upper(trim(p.kode)) = upper(trim(sp.kode)) THEN 0 ELSE 1 END, p.id
  LIMIT 1
) p ON true;

CREATE TEMP TABLE product_remap AS
SELECT
  spm.produk_id,
  spm.kode_sku,
  spm.produk_nama,
  spm.old_principal_id,
  pmai.target_id AS new_principal_id,
  pmai.target_kode AS new_principal_kode,
  pmai.target_nama AS new_principal_nama
FROM source_product_mapping spm
LEFT JOIN principal_match_after_insert pmai
  ON upper(trim(pmai.source_kode)) = upper(trim(spm.source_principal_kode));

SELECT
  CASE WHEN new_principal_id IS NULL THEN 'belum bisa mapping' ELSE 'siap update produk' END AS status,
  count(*) AS jumlah_produk
FROM product_remap
GROUP BY 1
ORDER BY 1;

UPDATE produk p
SET id_principal = pr.new_principal_id
FROM product_remap pr
WHERE p.id = pr.produk_id
  AND pr.new_principal_id IS NOT NULL;

CREATE TEMP TABLE mfb_sales AS
SELECT spa.id_sales, spa.id_principal AS mfb_principal_id
FROM sales_principal_assignment spa
JOIN principal p ON p.id = spa.id_principal
WHERE p.kode = 'MFB';

CREATE TEMP TABLE remap_principals AS
SELECT DISTINCT new_principal_id
FROM product_remap
WHERE new_principal_id IS NOT NULL;

INSERT INTO sales_principal_assignment (id_sales, id_principal)
SELECT ms.id_sales, rp.new_principal_id
FROM mfb_sales ms
CROSS JOIN remap_principals rp
WHERE NOT EXISTS (
  SELECT 1
  FROM sales_principal_assignment spa
  WHERE spa.id_sales = ms.id_sales
    AND spa.id_principal = rp.new_principal_id
);

DELETE FROM sales_principal_assignment spa
USING principal p
WHERE p.id = spa.id_principal
  AND p.kode = 'MFB'
  AND NOT EXISTS (
    SELECT 1 FROM produk prod WHERE prod.id_principal = p.id
  );

DELETE FROM principal p
WHERE p.kode = 'MFB'
  AND NOT EXISTS (SELECT 1 FROM produk prod WHERE prod.id_principal = p.id)
  AND NOT EXISTS (SELECT 1 FROM sales_principal_assignment spa WHERE spa.id_principal = p.id)
  AND NOT EXISTS (SELECT 1 FROM stock_transfer_detail std WHERE std.id_principal = p.id)
  AND NOT EXISTS (SELECT 1 FROM log_stockopname_sales los WHERE los.id_principal = p.id)
  AND NOT EXISTS (SELECT 1 FROM principal_special_rule psr WHERE psr.id_principal = p.id);

SELECT setval(pg_get_serial_sequence('principal', 'id'), COALESCE((SELECT max(id) FROM principal), 1), true);
SELECT setval(pg_get_serial_sequence('sales_principal_assignment', 'id'), COALESCE((SELECT max(id) FROM sales_principal_assignment), 1), true);

SELECT 'COMMIT' AS mode,
  (SELECT count(*) FROM produk p JOIN principal pr ON pr.id = p.id_principal WHERE pr.kode = 'MFB') AS remaining_mfb_products,
  (SELECT count(*) FROM sales_principal_assignment spa JOIN principal pr ON pr.id = spa.id_principal WHERE pr.kode = 'MFB') AS remaining_mfb_assignments,
  (SELECT count(*) FROM principal WHERE kode = 'MFB') AS remaining_mfb_principal,
  (SELECT count(*) FROM principal WHERE kode in (SELECT kode FROM source_principals)) AS source_principals_in_target;

COMMIT;
