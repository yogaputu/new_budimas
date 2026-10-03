param(
  [switch]$Commit,
  [string]$PgHost = "127.0.0.1",
  [string]$PgPort = "5432",
  [string]$PgDatabase = "budimas-dev",
  [string]$PgUser = "postgres",
  [int]$DefaultCompanyId = 1
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$workDir = Join-Path $root "tmp_dist_import"
$psql = "D:\laragon\bin\postgresql\postgresql-14.5-1\bin\psql.exe"

$csv18 = Join-Path $workDir "all_stok_brand_from_192_168_1_8.csv"
$csv16 = Join-Path $workDir "dist_stok_active.csv"
$sqlPath = Join-Path $workDir "remap_remaining_mix_principals.generated.sql"

if (-not (Test-Path $psql)) { throw "psql.exe tidak ditemukan di $psql" }
if (-not (Test-Path $csv18)) { throw "File mapping 1.8 tidak ditemukan: $csv18" }
if (-not (Test-Path $csv16)) { throw "File mapping 1.16 tidak ditemukan: $csv16" }

$csv18ForPsql = $csv18.Replace("\", "/")
$csv16ForPsql = $csv16.Replace("\", "/")
$modeLabel = if ($Commit) { "COMMIT" } else { "DRY_RUN_ROLLBACK" }
$finishSql = if ($Commit) { "COMMIT;" } else { "ROLLBACK;" }

$sql = @"
\set ON_ERROR_STOP on
BEGIN;

CREATE TEMP TABLE src_stok_18 (
  kode text,
  nama text,
  active text,
  principle text,
  jenis text,
  brand text,
  kodeprinciple text,
  namaprinciple text
);
\copy src_stok_18 FROM '$csv18ForPsql' WITH CSV HEADER;

CREATE TEMP TABLE src_stok_16 (
  kode text,
  nama text,
  active text,
  principle_kode text,
  food text,
  jenis text,
  satuan text,
  perunit text,
  nama_unit text,
  harga_beli text,
  harga_jual text,
  brand_kode text,
  brand_nama text,
  subbrand_kode text,
  subbrand_nama text,
  kategori_lama text,
  kode_ean text,
  master_kode text
);
\copy src_stok_16 FROM '$csv16ForPsql' WITH CSV HEADER;

CREATE TEMP TABLE current_mix_products AS
SELECT p.id, p.kode_sku, p.nama, pr.kode AS mix_kode, pr.nama AS mix_nama, p.id_principal AS old_principal_id
FROM produk p
JOIN principal pr ON pr.id = p.id_principal
WHERE pr.kode IN ('M1', 'M2', 'M3', 'MFT');

CREATE TEMP TABLE source_product_mapping AS
SELECT DISTINCT ON (cmp.id)
  cmp.id AS produk_id,
  cmp.kode_sku,
  cmp.nama AS produk_nama,
  cmp.mix_kode,
  cmp.old_principal_id,
  left(
    CASE
      WHEN cmp.kode_sku = 'BNSNA' THEN 'SANIA'
      ELSE COALESCE(NULLIF(trim(s18.kodeprinciple), ''), NULLIF(trim(s16.brand_kode), ''))
    END,
    100
  ) AS source_principal_kode,
  left(
    CASE
      WHEN cmp.kode_sku = 'BNSNA' THEN 'SANIA'
      ELSE COALESCE(NULLIF(trim(s18.namaprinciple), ''), NULLIF(trim(s16.brand_nama), ''))
    END,
    50
  ) AS source_principal_nama,
  CASE
    WHEN cmp.kode_sku = 'BNSNA' THEN 'manual_sania'
    WHEN NULLIF(trim(s18.kodeprinciple), '') IS NOT NULL THEN 'sql_1_8'
    WHEN NULLIF(trim(s16.brand_kode), '') IS NOT NULL THEN 'sql_1_16'
    ELSE 'kosong'
  END AS sumber_mapping
FROM current_mix_products cmp
LEFT JOIN src_stok_18 s18 ON upper(trim(s18.kode)) = upper(trim(cmp.kode_sku))
LEFT JOIN src_stok_16 s16 ON upper(trim(s16.kode)) = upper(trim(cmp.kode_sku))
ORDER BY cmp.id;

CREATE TEMP TABLE source_principals AS
SELECT DISTINCT
  mix_kode,
  source_principal_kode AS kode,
  source_principal_nama AS nama,
  regexp_replace(upper(coalesce(source_principal_nama, '')), '[^A-Z0-9]+', '', 'g') AS nama_key
FROM source_product_mapping
WHERE source_principal_kode IS NOT NULL
  AND source_principal_nama IS NOT NULL;

CREATE TEMP TABLE existing_principal_match AS
SELECT
  sp.mix_kode,
  sp.kode AS source_kode,
  sp.nama AS source_nama,
  p.id AS target_id,
  p.kode AS target_kode,
  p.nama AS target_nama
FROM source_principals sp
LEFT JOIN LATERAL (
  SELECT p.*
  FROM principal p
  WHERE p.kode NOT IN ('M1', 'M2', 'M3', 'MFB', 'MFT')
    AND (
      regexp_replace(upper(coalesce(p.nama, '')), '[^A-Z0-9]+', '', 'g') = sp.nama_key
      OR (
        upper(trim(p.kode)) = upper(trim(sp.kode))
        AND regexp_replace(upper(coalesce(p.nama, '')), '[^A-Z0-9]+', '', 'g') = sp.nama_key
      )
      OR (
        sp.nama_key <> ''
        AND regexp_replace(upper(coalesce(p.nama, '')), '[^A-Z0-9]+', '', 'g') <> ''
        AND length(regexp_replace(upper(coalesce(p.nama, '')), '[^A-Z0-9]+', '', 'g')) >= 6
        AND (
          position(regexp_replace(upper(coalesce(p.nama, '')), '[^A-Z0-9]+', '', 'g') in sp.nama_key) > 0
          OR position(sp.nama_key in regexp_replace(upper(coalesce(p.nama, '')), '[^A-Z0-9]+', '', 'g')) > 0
        )
      )
    )
  ORDER BY
    CASE
      WHEN regexp_replace(upper(coalesce(p.nama, '')), '[^A-Z0-9]+', '', 'g') = sp.nama_key THEN 0
      WHEN upper(trim(p.kode)) = upper(trim(sp.kode)) THEN 1
      ELSE 2
    END,
    length(regexp_replace(upper(coalesce(p.nama, '')), '[^A-Z0-9]+', '', 'g')) DESC,
    p.id
  LIMIT 1
) p ON true;

SELECT '$modeLabel' AS mode,
  (SELECT count(*) FROM current_mix_products) AS current_mix_products,
  (SELECT count(*) FROM source_principals) AS source_principals,
  (SELECT count(*) FROM existing_principal_match WHERE target_id IS NULL) AS principal_to_insert,
  (SELECT count(*) FROM source_product_mapping WHERE source_principal_kode IS NULL) AS products_without_source_mapping;

INSERT INTO principal (kode, nama, id_perusahaan)
SELECT source_kode, source_nama, $DefaultCompanyId
FROM existing_principal_match epm
WHERE target_id IS NULL
  AND NOT EXISTS (
    SELECT 1
    FROM principal p
    WHERE p.kode NOT IN ('M1', 'M2', 'M3', 'MFB', 'MFT')
      AND regexp_replace(upper(coalesce(p.nama, '')), '[^A-Z0-9]+', '', 'g') = regexp_replace(upper(coalesce(epm.source_nama, '')), '[^A-Z0-9]+', '', 'g')
  );

CREATE TEMP TABLE principal_match_after_insert AS
SELECT
  sp.mix_kode,
  sp.kode AS source_kode,
  sp.nama AS source_nama,
  p.id AS target_id,
  p.kode AS target_kode,
  p.nama AS target_nama
FROM source_principals sp
LEFT JOIN LATERAL (
  SELECT p.*
  FROM principal p
  WHERE p.kode NOT IN ('M1', 'M2', 'M3', 'MFB', 'MFT')
    AND (
      regexp_replace(upper(coalesce(p.nama, '')), '[^A-Z0-9]+', '', 'g') = sp.nama_key
      OR (
        upper(trim(p.kode)) = upper(trim(sp.kode))
        AND regexp_replace(upper(coalesce(p.nama, '')), '[^A-Z0-9]+', '', 'g') = sp.nama_key
      )
      OR (
        sp.nama_key <> ''
        AND regexp_replace(upper(coalesce(p.nama, '')), '[^A-Z0-9]+', '', 'g') <> ''
        AND length(regexp_replace(upper(coalesce(p.nama, '')), '[^A-Z0-9]+', '', 'g')) >= 6
        AND (
          position(regexp_replace(upper(coalesce(p.nama, '')), '[^A-Z0-9]+', '', 'g') in sp.nama_key) > 0
          OR position(sp.nama_key in regexp_replace(upper(coalesce(p.nama, '')), '[^A-Z0-9]+', '', 'g')) > 0
        )
      )
    )
  ORDER BY
    CASE
      WHEN regexp_replace(upper(coalesce(p.nama, '')), '[^A-Z0-9]+', '', 'g') = sp.nama_key THEN 0
      WHEN upper(trim(p.kode)) = upper(trim(sp.kode)) THEN 1
      ELSE 2
    END,
    length(regexp_replace(upper(coalesce(p.nama, '')), '[^A-Z0-9]+', '', 'g')) DESC,
    p.id
  LIMIT 1
) p ON true;

CREATE TEMP TABLE product_remap AS
SELECT
  spm.produk_id,
  spm.kode_sku,
  spm.produk_nama,
  spm.mix_kode,
  spm.old_principal_id,
  pmai.target_id AS new_principal_id,
  pmai.target_kode AS new_principal_kode,
  pmai.target_nama AS new_principal_nama
FROM source_product_mapping spm
LEFT JOIN principal_match_after_insert pmai
  ON pmai.mix_kode = spm.mix_kode
 AND upper(trim(pmai.source_kode)) = upper(trim(spm.source_principal_kode))
 AND regexp_replace(upper(coalesce(pmai.source_nama, '')), '[^A-Z0-9]+', '', 'g') =
     regexp_replace(upper(coalesce(spm.source_principal_nama, '')), '[^A-Z0-9]+', '', 'g');

SELECT mix_kode,
  CASE WHEN new_principal_id IS NULL THEN 'belum bisa mapping' ELSE 'siap update produk' END AS status,
  count(*) AS jumlah_produk
FROM product_remap
GROUP BY mix_kode, status
ORDER BY mix_kode, status;

UPDATE produk p
SET id_principal = pr.new_principal_id
FROM product_remap pr
WHERE p.id = pr.produk_id
  AND pr.new_principal_id IS NOT NULL;

CREATE TEMP TABLE mix_sales AS
SELECT spa.id_sales, spa.id_principal AS mix_principal_id, p.kode AS mix_kode
FROM sales_principal_assignment spa
JOIN principal p ON p.id = spa.id_principal
WHERE p.kode IN ('M1', 'M2', 'M3', 'MFT');

CREATE TEMP TABLE remap_principals AS
SELECT DISTINCT mix_kode, new_principal_id
FROM product_remap
WHERE new_principal_id IS NOT NULL;

INSERT INTO sales_principal_assignment (id_sales, id_principal)
SELECT ms.id_sales, rp.new_principal_id
FROM mix_sales ms
JOIN remap_principals rp ON rp.mix_kode = ms.mix_kode
WHERE NOT EXISTS (
  SELECT 1
  FROM sales_principal_assignment spa
  WHERE spa.id_sales = ms.id_sales
    AND spa.id_principal = rp.new_principal_id
);

DELETE FROM sales_principal_assignment spa
USING principal p
WHERE p.id = spa.id_principal
  AND p.kode IN ('M1', 'M2', 'M3', 'MFT')
  AND NOT EXISTS (
    SELECT 1 FROM produk prod WHERE prod.id_principal = p.id
  );

DELETE FROM principal p
WHERE p.kode IN ('M1', 'M2', 'M3', 'MFT')
  AND NOT EXISTS (SELECT 1 FROM produk prod WHERE prod.id_principal = p.id)
  AND NOT EXISTS (SELECT 1 FROM sales_principal_assignment spa WHERE spa.id_principal = p.id)
  AND NOT EXISTS (SELECT 1 FROM stock_transfer_detail std WHERE std.id_principal = p.id)
  AND NOT EXISTS (SELECT 1 FROM log_stockopname_sales los WHERE los.id_principal = p.id)
  AND NOT EXISTS (SELECT 1 FROM principal_special_rule psr WHERE psr.id_principal = p.id);

SELECT setval(pg_get_serial_sequence('principal', 'id'), COALESCE((SELECT max(id) FROM principal), 1), true);
SELECT setval(pg_get_serial_sequence('sales_principal_assignment', 'id'), COALESCE((SELECT max(id) FROM sales_principal_assignment), 1), true);

SELECT '$modeLabel' AS mode,
  (SELECT count(*) FROM produk p JOIN principal pr ON pr.id = p.id_principal WHERE pr.kode IN ('M1','M2','M3','MFT')) AS remaining_mix_products,
  (SELECT count(*) FROM sales_principal_assignment spa JOIN principal pr ON pr.id = spa.id_principal WHERE pr.kode IN ('M1','M2','M3','MFT')) AS remaining_mix_assignments,
  (SELECT count(*) FROM principal WHERE kode IN ('M1','M2','M3','MFT')) AS remaining_mix_principals;

$finishSql
"@

Set-Content -Path $sqlPath -Value $sql -Encoding UTF8
Write-Host "Running remaining mix remap mode: $modeLabel"
& $psql -h $PgHost -p $PgPort -U $PgUser -d $PgDatabase -f $sqlPath
