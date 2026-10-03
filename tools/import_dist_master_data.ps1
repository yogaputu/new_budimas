param(
  [switch]$Commit,
  [switch]$UpdateExisting,
  [switch]$UseExistingCsv,
  [string]$SqlServer = "192.168.1.16",
  [string]$SqlPort = "1433",
  [string]$SqlDatabase = "DIST",
  [string]$SqlUser = "sa",
  [string]$SqlPassword = "Budimas789",
  [string]$PgHost = "127.0.0.1",
  [string]$PgPort = "5432",
  [string]$PgDatabase = "budimas-dev",
  [string]$PgUser = "postgres",
  [int]$DefaultCompanyId = 1
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$workDir = Join-Path $root "tmp_dist_import"
New-Item -ItemType Directory -Force -Path $workDir | Out-Null

$psql = "D:\laragon\bin\postgresql\postgresql-14.5-1\bin\psql.exe"
if (-not (Test-Path $psql)) {
  throw "psql.exe tidak ditemukan di $psql"
}

$sqlConnectionString = "Server=$SqlServer,$SqlPort;Database=$SqlDatabase;User ID=$SqlUser;Password=$SqlPassword;TrustServerCertificate=True;Connection Timeout=8;"

function Export-SqlServerCsv {
  param(
    [System.Data.SqlClient.SqlConnection]$Connection,
    [string]$Query,
    [string]$Path
  )

  $cmd = $Connection.CreateCommand()
  $cmd.CommandTimeout = 120
  $cmd.CommandText = $Query
  $table = New-Object System.Data.DataTable
  $table.Load($cmd.ExecuteReader())
  $table | Export-Csv -Path $Path -NoTypeInformation -Encoding UTF8
  Write-Host "Exported $($table.Rows.Count) rows -> $Path"
}

$principleCsv = Join-Path $workDir "dist_principle.csv"
$produkCsv = Join-Path $workDir "dist_stok_active.csv"
$sqlPath = Join-Path $workDir "import_dist_master_data.generated.sql"

if ($UseExistingCsv) {
  if (-not (Test-Path $principleCsv)) { throw "CSV principle tidak ditemukan: $principleCsv" }
  if (-not (Test-Path $produkCsv)) { throw "CSV produk tidak ditemukan: $produkCsv" }
  Write-Host "Using existing CSV snapshot:"
  Write-Host "  $principleCsv"
  Write-Host "  $produkCsv"
} else {
  $conn = New-Object System.Data.SqlClient.SqlConnection $sqlConnectionString
  try {
    $conn.Open()

    Export-SqlServerCsv -Connection $conn -Path $principleCsv -Query @"
SELECT
  LTRIM(RTRIM(Kode)) AS kode,
  LTRIM(RTRIM(ISNULL(Nama, ''))) AS nama,
  LTRIM(RTRIM(ISNULL(Alamat, ''))) AS alamat,
  LTRIM(RTRIM(ISNULL(Telpon, ''))) AS telepon,
  LTRIM(RTRIM(ISNULL(NPWP, ''))) AS npwp,
  LTRIM(RTRIM(ISNULL(Account, ''))) AS no_rekening,
  LTRIM(RTRIM(ISNULL(ContactPerson, ''))) AS pic,
  LTRIM(RTRIM(ISNULL(Active, ''))) AS active
FROM dbo.Principle
WHERE NULLIF(LTRIM(RTRIM(Kode)), '') IS NOT NULL
"@

    Export-SqlServerCsv -Connection $conn -Path $produkCsv -Query @"
SELECT
  LTRIM(RTRIM(Kode)) AS kode,
  LTRIM(RTRIM(ISNULL(Nama, ''))) AS nama,
  LTRIM(RTRIM(ISNULL(Active, ''))) AS active,
  LTRIM(RTRIM(ISNULL(Principle, ''))) AS principle_kode,
  LTRIM(RTRIM(ISNULL(Food, ''))) AS food,
  LTRIM(RTRIM(ISNULL(Jenis, ''))) AS jenis,
  LTRIM(RTRIM(ISNULL(Satuan, ''))) AS satuan,
  CONVERT(varchar(50), CONVERT(decimal(18, 4), ISNULL(PerUnit, 0))) AS perunit,
  LTRIM(RTRIM(ISNULL(NamaUnit, ''))) AS nama_unit,
  CONVERT(varchar(50), CONVERT(decimal(18, 4), ISNULL(HargaAsli, 0))) AS harga_beli,
  CONVERT(varchar(50), CONVERT(decimal(18, 4), ISNULL(HargaA, 0))) AS harga_jual,
  LTRIM(RTRIM(ISNULL(Brand, ''))) AS brand_kode,
  LTRIM(RTRIM(ISNULL(NamaBrand, ''))) AS brand_nama,
  LTRIM(RTRIM(ISNULL(SubBrand, ''))) AS subbrand_kode,
  LTRIM(RTRIM(ISNULL(NamaSubBrand, ''))) AS subbrand_nama,
  LTRIM(RTRIM(ISNULL(Kategori, ''))) AS kategori_lama,
  LTRIM(RTRIM(ISNULL(NasionalKode, ''))) AS kode_ean,
  LTRIM(RTRIM(ISNULL(MasterKode, ''))) AS master_kode
FROM dbo.STOK
WHERE NULLIF(LTRIM(RTRIM(Kode)), '') IS NOT NULL
  AND LTRIM(RTRIM(ISNULL(Active, ''))) = '1'
"@
  } finally {
    if ($conn.State -ne "Closed") {
      $conn.Close()
    }
  }
}

$principlePath = $principleCsv.Replace("\", "/")
$produkPath = $produkCsv.Replace("\", "/")
$finishSql = if ($Commit) { "COMMIT;" } else { "ROLLBACK;" }
$modeLabel = if ($Commit) { "COMMIT" } else { "DRY_RUN_ROLLBACK" }
$updateExistingSql = if ($UpdateExisting) {
@"
UPDATE principal p
SET
  nama = COALESCE(s.nama, p.nama),
  alamat = COALESCE(s.alamat, p.alamat),
  telepon = COALESCE(s.telepon, p.telepon),
  npwp = COALESCE(s.npwp, p.npwp),
  no_rekening = COALESCE(s.no_rekening, p.no_rekening),
  pic = COALESCE(s.pic, p.pic)
FROM stg_principle_clean s
WHERE upper(trim(p.kode)) = upper(s.kode);
"@
} else {
@"
SELECT 'skip_existing_principal' AS action, count(*) AS skipped
FROM stg_principle_clean s
WHERE EXISTS (
  SELECT 1 FROM principal p WHERE upper(trim(p.kode)) = upper(s.kode)
);
"@
}
$updateProdukSql = if ($UpdateExisting) {
@"
UPDATE produk p
SET
  id_principal = mp.id,
  id_brand = mb.id,
  id_kategori = mc.id,
  id_subbrand = ms.id,
  id_status = CASE WHEN s.active = '1' THEN 1 ELSE 0 END,
  kode_ean = COALESCE(s.kode_ean, p.kode_ean),
  nama = COALESCE(s.nama, p.nama),
  harga_beli = s.harga_beli::double precision,
  harga_jual = s.harga_jual::double precision,
  satuan = COALESCE(s.satuan, s.nama_unit, p.satuan),
  isiperbox = COALESCE(NULLIF(round(s.perunit)::int, 0), p.isiperbox, 1),
  isiperkarton = COALESCE(NULLIF(round(s.perunit)::int, 0), p.isiperkarton, 1),
  keterangan = left(CONCAT_WS(' | ', 'DIST', NULLIF('Jenis: ' || s.jenis, 'Jenis: '), NULLIF('Kategori lama: ' || s.kategori_lama, 'Kategori lama: '), NULLIF('MasterKode: ' || s.master_kode, 'MasterKode: ')), 50)
FROM stg_produk_clean s
LEFT JOIN map_principal mp ON mp.key = upper(trim(s.principle_kode))
LEFT JOIN map_brand mb ON mb.key = upper(trim(COALESCE(s.brand_nama, s.brand_kode)))
LEFT JOIN map_category mc ON mc.key = upper(trim(COALESCE(s.food, 'LAINNYA')))
LEFT JOIN map_subbrand ms ON ms.key = upper(trim(COALESCE(s.subbrand_kode, s.subbrand_nama)))
WHERE upper(trim(p.kode_sku)) = upper(s.kode);
"@
} else {
@"
SELECT 'skip_existing_produk' AS action, count(*) AS skipped
FROM stg_produk_clean s
WHERE EXISTS (
  SELECT 1 FROM produk p WHERE upper(trim(p.kode_sku)) = upper(s.kode)
);
"@
}

$sql = @"
\set ON_ERROR_STOP on
BEGIN;

CREATE TEMP TABLE stg_principle (
  kode text,
  nama text,
  alamat text,
  telepon text,
  npwp text,
  no_rekening text,
  pic text,
  active text
);
\copy stg_principle FROM '$principlePath' WITH CSV HEADER;

CREATE TEMP TABLE stg_produk (
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
\copy stg_produk FROM '$produkPath' WITH CSV HEADER;

CREATE TEMP TABLE stg_principle_clean AS
SELECT DISTINCT ON (upper(trim(kode)))
  trim(kode) AS kode,
  left(nullif(trim(nama), ''), 50) AS nama,
  nullif(trim(alamat), '') AS alamat,
  left(nullif(trim(telepon), ''), 13) AS telepon,
  left(nullif(trim(npwp), ''), 25) AS npwp,
  left(nullif(trim(no_rekening), ''), 20) AS no_rekening,
  left(nullif(trim(pic), ''), 50) AS pic,
  nullif(trim(active), '') AS active
FROM stg_principle
WHERE nullif(trim(kode), '') IS NOT NULL
ORDER BY upper(trim(kode));

CREATE TEMP TABLE stg_produk_clean AS
SELECT DISTINCT ON (upper(trim(kode)))
  trim(kode) AS kode,
  left(nullif(trim(nama), ''), 50) AS nama,
  nullif(trim(active), '') AS active,
  nullif(trim(principle_kode), '') AS principle_kode,
  nullif(trim(food), '') AS food,
  nullif(trim(jenis), '') AS jenis,
  nullif(trim(satuan), '') AS satuan,
  nullif(trim(nama_unit), '') AS nama_unit,
  left(nullif(trim(brand_kode), ''), 25) AS brand_kode,
  left(nullif(trim(brand_nama), ''), 25) AS brand_nama,
  nullif(trim(subbrand_kode), '') AS subbrand_kode,
  nullif(trim(subbrand_nama), '') AS subbrand_nama,
  nullif(trim(kategori_lama), '') AS kategori_lama,
  left(nullif(trim(kode_ean), ''), 25) AS kode_ean,
  nullif(trim(master_kode), '') AS master_kode,
  COALESCE(nullif(trim(perunit), '')::numeric, 0) AS perunit,
  COALESCE(nullif(trim(harga_beli), '')::numeric, 0) AS harga_beli,
  COALESCE(nullif(trim(harga_jual), '')::numeric, 0) AS harga_jual
FROM stg_produk
WHERE nullif(trim(kode), '') IS NOT NULL
ORDER BY upper(trim(kode));

SELECT '$modeLabel' AS mode,
  (SELECT count(*) FROM stg_principle_clean) AS source_principal,
  (SELECT count(*) FROM stg_produk_clean) AS source_produk_active,
  (SELECT count(*) FROM stg_principle_clean s WHERE NOT EXISTS (SELECT 1 FROM principal p WHERE upper(trim(p.kode)) = upper(s.kode))) AS principal_to_insert,
  (SELECT count(*) FROM stg_produk_clean s WHERE NOT EXISTS (SELECT 1 FROM produk p WHERE upper(trim(p.kode_sku)) = upper(s.kode))) AS produk_to_insert;

$updateExistingSql

INSERT INTO principal (kode, nama, alamat, telepon, npwp, no_rekening, pic, id_perusahaan)
SELECT s.kode, s.nama, s.alamat, s.telepon, s.npwp, s.no_rekening, s.pic, $DefaultCompanyId
FROM stg_principle_clean s
WHERE NOT EXISTS (
  SELECT 1 FROM principal p WHERE upper(trim(p.kode)) = upper(s.kode)
);

INSERT INTO produk_kategori (nama)
SELECT DISTINCT COALESCE(s.food, 'LAINNYA') AS nama
FROM stg_produk_clean s
WHERE NOT EXISTS (
  SELECT 1 FROM produk_kategori pk WHERE upper(trim(pk.nama)) = upper(COALESCE(s.food, 'LAINNYA'))
);

INSERT INTO produk_brand (nama)
SELECT DISTINCT COALESCE(s.brand_nama, s.brand_kode) AS nama
FROM stg_produk_clean s
WHERE COALESCE(s.brand_nama, s.brand_kode) IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM produk_brand pb WHERE upper(trim(pb.nama)) = upper(COALESCE(s.brand_nama, s.brand_kode))
  );

CREATE TEMP TABLE map_brand AS
SELECT DISTINCT ON (upper(trim(nama))) upper(trim(nama)) AS key, id
FROM produk_brand
WHERE nullif(trim(nama), '') IS NOT NULL
ORDER BY upper(trim(nama)), id;

WITH subbrand_source AS (
  SELECT DISTINCT ON (
    COALESCE(mb.id, 0),
    upper(trim(COALESCE(s.subbrand_nama, s.subbrand_kode)))
  )
    COALESCE(s.subbrand_kode, upper(regexp_replace(COALESCE(s.subbrand_nama, 'DIST'), '\s+', '_', 'g'))) AS kode,
    COALESCE(s.subbrand_nama, s.subbrand_kode) AS nama,
    mb.id AS id_brand
  FROM stg_produk_clean s
  LEFT JOIN map_brand mb ON mb.key = upper(trim(COALESCE(s.brand_nama, s.brand_kode)))
  WHERE COALESCE(s.subbrand_nama, s.subbrand_kode) IS NOT NULL
  ORDER BY COALESCE(mb.id, 0), upper(trim(COALESCE(s.subbrand_nama, s.subbrand_kode))), COALESCE(s.subbrand_kode, '')
)
INSERT INTO produk_subbrand (kode, nama, id_brand)
SELECT source.kode, source.nama, source.id_brand
FROM subbrand_source source
WHERE NOT EXISTS (
  SELECT 1
  FROM produk_subbrand ps
  WHERE COALESCE(ps.id_brand, 0) = COALESCE(source.id_brand, 0)
    AND upper(trim(ps.nama)) = upper(trim(source.nama))
);

CREATE TEMP TABLE map_principal AS
SELECT DISTINCT ON (upper(trim(kode))) upper(trim(kode)) AS key, id
FROM principal
WHERE nullif(trim(kode), '') IS NOT NULL
ORDER BY upper(trim(kode)), id;

CREATE TEMP TABLE map_category AS
SELECT DISTINCT ON (upper(trim(nama))) upper(trim(nama)) AS key, id
FROM produk_kategori
WHERE nullif(trim(nama), '') IS NOT NULL
ORDER BY upper(trim(nama)), id;

DROP TABLE IF EXISTS map_brand;
CREATE TEMP TABLE map_brand AS
SELECT DISTINCT ON (upper(trim(nama))) upper(trim(nama)) AS key, id
FROM produk_brand
WHERE nullif(trim(nama), '') IS NOT NULL
ORDER BY upper(trim(nama)), id;

CREATE TEMP TABLE map_subbrand AS
SELECT DISTINCT ON (upper(trim(COALESCE(kode, nama)))) upper(trim(COALESCE(kode, nama))) AS key, id
FROM produk_subbrand
WHERE nullif(trim(COALESCE(kode, nama)), '') IS NOT NULL
ORDER BY upper(trim(COALESCE(kode, nama))), id;

$updateProdukSql

INSERT INTO produk (
  id_principal,
  id_brand,
  id_kategori,
  id_subbrand,
  id_status,
  kode_sku,
  kode_ean,
  nama,
  harga_beli,
  harga_jual,
  satuan,
  isiperbox,
  isiperkarton,
  ppn,
  keterangan
)
SELECT
  mp.id,
  mb.id,
  mc.id,
  ms.id,
  CASE WHEN s.active = '1' THEN 1 ELSE 0 END,
  s.kode,
  s.kode_ean,
  s.nama,
  s.harga_beli::double precision,
  s.harga_jual::double precision,
  COALESCE(s.satuan, s.nama_unit, 'PC'),
  COALESCE(NULLIF(round(s.perunit)::int, 0), 1),
  COALESCE(NULLIF(round(s.perunit)::int, 0), 1),
  11,
  left(CONCAT_WS(' | ', 'DIST', NULLIF('Jenis: ' || s.jenis, 'Jenis: '), NULLIF('Kategori lama: ' || s.kategori_lama, 'Kategori lama: '), NULLIF('MasterKode: ' || s.master_kode, 'MasterKode: ')), 50)
FROM stg_produk_clean s
LEFT JOIN map_principal mp ON mp.key = upper(trim(s.principle_kode))
LEFT JOIN map_brand mb ON mb.key = upper(trim(COALESCE(s.brand_nama, s.brand_kode)))
LEFT JOIN map_category mc ON mc.key = upper(trim(COALESCE(s.food, 'LAINNYA')))
LEFT JOIN map_subbrand ms ON ms.key = upper(trim(COALESCE(s.subbrand_kode, s.subbrand_nama)))
WHERE NOT EXISTS (
  SELECT 1 FROM produk p WHERE upper(trim(p.kode_sku)) = upper(s.kode)
);

SELECT setval(pg_get_serial_sequence('principal', 'id'), COALESCE((SELECT max(id) FROM principal), 1), true);
SELECT setval(pg_get_serial_sequence('produk', 'id'), COALESCE((SELECT max(id) FROM produk), 1), true);
SELECT setval(pg_get_serial_sequence('produk_brand', 'id'), COALESCE((SELECT max(id) FROM produk_brand), 1), true);
SELECT setval(pg_get_serial_sequence('produk_kategori', 'id'), COALESCE((SELECT max(id) FROM produk_kategori), 1), true);
SELECT setval(pg_get_serial_sequence('produk_subbrand', 'id'), COALESCE((SELECT max(id) FROM produk_subbrand), 1), true);

SELECT '$modeLabel' AS mode,
  (SELECT count(*) FROM principal) AS principal_total_after,
  (SELECT count(*) FROM produk) AS produk_total_after,
  (SELECT count(*) FROM produk_brand) AS brand_total_after,
  (SELECT count(*) FROM produk_kategori) AS kategori_total_after,
  (SELECT count(*) FROM produk_subbrand) AS subbrand_total_after;

$finishSql
"@

Set-Content -Path $sqlPath -Value $sql -Encoding UTF8

Write-Host "Running import mode: $modeLabel"
& $psql -h $PgHost -p $PgPort -U $PgUser -d $PgDatabase -f $sqlPath
