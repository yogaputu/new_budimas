param(
  [switch]$Commit,
  [switch]$SkipBackup,
  [switch]$UseExistingCsv,
  [string]$PgHost = "127.0.0.1",
  [string]$PgPort = "15432",
  [string]$PgDatabase = "budimas_dev",
  [string]$PgUser = "postgres",
  [string]$BackupDir = "",
  [int]$DefaultCompanyId = 1
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$psql = "D:\laragon\bin\postgresql\postgresql-14.5-1\bin\psql.exe"

if (-not (Test-Path $psql)) { throw "psql.exe tidak ditemukan di $psql" }

if ([string]::IsNullOrWhiteSpace($BackupDir)) {
  $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
  $BackupDir = Join-Path $root "tmp_dist_import\server_backup_$stamp"
}

$mode = if ($Commit) { "COMMIT" } else { "DRY RUN (ROLLBACK)" }
Write-Host "Target PostgreSQL : ${PgHost}:${PgPort}/${PgDatabase} as ${PgUser}"
Write-Host "Mode              : $mode"

& $psql -h $PgHost -p $PgPort -U $PgUser -d $PgDatabase -v ON_ERROR_STOP=1 -c @"
SELECT
  current_database() AS database,
  current_user AS user_name,
  inet_server_addr() AS server_addr,
  inet_server_port() AS server_port;
"@

& $psql -h $PgHost -p $PgPort -U $PgUser -d $PgDatabase -v ON_ERROR_STOP=1 -c @"
SELECT
  (SELECT count(*) FROM principal WHERE kode IN ('MFB','M1','M2','M3','MFT')) AS mix_principals,
  (SELECT count(*) FROM produk p JOIN principal pr ON pr.id = p.id_principal WHERE pr.kode IN ('MFB','M1','M2','M3','MFT')) AS mix_products,
  (SELECT count(*) FROM sales_principal_assignment spa JOIN principal pr ON pr.id = spa.id_principal WHERE pr.kode IN ('MFB','M1','M2','M3','MFT')) AS mix_assignments,
  (SELECT count(*) FROM principal) AS total_principal,
  (SELECT count(*) FROM produk) AS total_produk;
"@

if (-not $SkipBackup) {
  New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
  Write-Host "Backup tabel terkait -> $BackupDir"
  $backupTables = @(
    "principal",
    "produk",
    "produk_brand",
    "produk_subbrand",
    "produk_external_mapping",
    "produk_uom",
    "sales_principal_assignment"
  )
  foreach ($tableName in $backupTables) {
    $backupFile = (Join-Path $BackupDir "$tableName.csv").Replace("\", "/")
    & $psql -h $PgHost -p $PgPort -U $PgUser -d $PgDatabase -v ON_ERROR_STOP=1 -c "\copy public.$tableName TO '$backupFile' WITH CSV HEADER"
  }
}

$commonArgs = @{
  PgHost = $PgHost
  PgPort = $PgPort
  PgDatabase = $PgDatabase
  PgUser = $PgUser
  DefaultCompanyId = $DefaultCompanyId
}

if ($Commit) {
  & (Join-Path $PSScriptRoot "import_dist_master_data.ps1") @commonArgs -Commit -UseExistingCsv:$UseExistingCsv
  & (Join-Path $PSScriptRoot "remap_mfb_principal_from_1_8.ps1") @commonArgs -Commit -UseExistingCsv:$UseExistingCsv
  & (Join-Path $PSScriptRoot "remap_remaining_mix_principals.ps1") @commonArgs -Commit
} else {
  & (Join-Path $PSScriptRoot "import_dist_master_data.ps1") @commonArgs -UseExistingCsv:$UseExistingCsv
  & (Join-Path $PSScriptRoot "remap_mfb_principal_from_1_8.ps1") @commonArgs -UseExistingCsv:$UseExistingCsv
  & (Join-Path $PSScriptRoot "remap_remaining_mix_principals.ps1") @commonArgs
}

& $psql -h $PgHost -p $PgPort -U $PgUser -d $PgDatabase -v ON_ERROR_STOP=1 -c @"
SELECT
  (SELECT count(*) FROM principal WHERE kode IN ('MFB','M1','M2','M3','MFT')) AS mix_principals,
  (SELECT count(*) FROM produk p JOIN principal pr ON pr.id = p.id_principal WHERE pr.kode IN ('MFB','M1','M2','M3','MFT')) AS mix_products,
  (SELECT count(*) FROM sales_principal_assignment spa JOIN principal pr ON pr.id = spa.id_principal WHERE pr.kode IN ('MFB','M1','M2','M3','MFT')) AS mix_assignments,
  (SELECT count(*) FROM principal) AS total_principal,
  (SELECT count(*) FROM produk) AS total_produk;
"@

Write-Host "Selesai: $mode"
