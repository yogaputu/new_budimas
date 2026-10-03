param(
  [string]$NotaCsv = ".\.tmp_audit\unresolved_payment_nota_2025_candidates.csv",
  [string]$OutputRoot = ".\.tmp_audit\sqlserver_2025_ar_pg_legacy",
  [string]$SqlServer = "192.168.1.8,1433",
  [string]$SqlDatabase = "DIST",
  [string]$SqlUser = "sa",
  [string]$SqlPassword = "",
  [string]$ExistingHjualsmCsv = "",
  [datetime]$StartDate = [datetime]"2025-01-01",
  [datetime]$EndExclusive = [datetime]"2026-01-01",
  [int]$ChunkSize = 100,
  [string]$PgHost = "127.0.0.1",
  [string]$PgPort = "5432",
  [string]$PgUser = "postgres",
  [string]$PgDatabase = "budimas-dev",
  [string]$PgSchema = "legacy_dist_2025_ar",
  [string]$TemplateSchema = "legacy_dist_2026",
  [string]$PsqlPath = "D:\laragon\bin\postgresql\postgresql-14.5-1\bin\psql.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $NotaCsv)) {
  throw "Nota CSV tidak ditemukan: $NotaCsv"
}
if (-not (Test-Path -LiteralPath $PsqlPath)) {
  throw "psql.exe tidak ditemukan: $PsqlPath"
}
if (-not $SqlPassword -and $env:SQLSERVER_PASSWORD) {
  $SqlPassword = $env:SQLSERVER_PASSWORD
}
if (-not $SqlPassword) {
  $secure = Read-Host "SQL Server password" -AsSecureString
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try {
    $SqlPassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
  } finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
  }
}

function Quote-PgIdent {
  param([string]$Value)
  return '"' + $Value.Replace('"', '""') + '"'
}

function Quote-SqlIdent {
  param([string]$Value)
  return "[" + $Value.Replace("]", "]]") + "]"
}

function Quote-SqlLiteral {
  param([string]$Value)
  return "'" + $Value.Replace("'", "''") + "'"
}

function Escape-SqlLiteral {
  param([string]$Value)
  return $Value.Replace("'", "''")
}

function Escape-CsvValue {
  param($Value)
  if ($null -eq $Value -or $Value -is [System.DBNull]) {
    return ""
  }
  if ($Value -is [byte[]]) {
    $text = [Convert]::ToBase64String($Value)
  } elseif ($Value -is [datetime]) {
    $text = $Value.ToString("yyyy-MM-dd HH:mm:ss.fff", [Globalization.CultureInfo]::InvariantCulture)
  } elseif ($Value -is [System.IFormattable]) {
    $text = $Value.ToString($null, [Globalization.CultureInfo]::InvariantCulture)
  } else {
    $text = [string]$Value
  }
  if ($text.Length -eq 0) {
    return '""'
  }
  if ($text -match '[,"\r\n]' -or $text.StartsWith(" ") -or $text.EndsWith(" ")) {
    return '"' + $text.Replace('"', '""') + '"'
  }
  return $text
}

function Invoke-Psql {
  param([string]$Sql)
  $env:PGPASSWORD = ""
  & $PsqlPath -h $PgHost -p $PgPort -U $PgUser -d $PgDatabase -v ON_ERROR_STOP=1 -P pager=off -c $Sql
  if ($LASTEXITCODE -ne 0) {
    throw "psql gagal dengan exit code $LASTEXITCODE"
  }
}

function Invoke-PsqlFile {
  param([string]$SqlPath)
  $env:PGPASSWORD = ""
  & $PsqlPath -h $PgHost -p $PgPort -U $PgUser -d $PgDatabase -v ON_ERROR_STOP=1 -P pager=off -f $SqlPath
  if ($LASTEXITCODE -ne 0) {
    throw "psql file gagal dengan exit code $LASTEXITCODE : $SqlPath"
  }
}

function Export-TargetTable {
  param(
    [System.Data.SqlClient.SqlConnection]$Connection,
    [string]$TableName,
    [string[]]$Columns,
    [string[]]$Notas,
    [string]$CsvPath
  )

  $utf8 = New-Object System.Text.UTF8Encoding($false)
  $writer = New-Object System.IO.StreamWriter($CsvPath, $false, $utf8)
  $total = 0L
  try {
    $writer.WriteLine((@($Columns | ForEach-Object { Escape-CsvValue $_.ToLowerInvariant() }) -join ","))
    $columnSql = (@($Columns | ForEach-Object { Quote-SqlIdent $_ }) -join ", ")
    $orderSql = if ($Columns -contains "Urut") {
      "ORDER BY [Tanggal], [Nota], [Urut]"
    } else {
      "ORDER BY [Tanggal], [Nota]"
    }

    for ($offset = 0; $offset -lt $Notas.Count; $offset += $ChunkSize) {
      $end = [Math]::Min($offset + $ChunkSize - 1, $Notas.Count - 1)
      $chunk = @($Notas[$offset..$end])
      $inList = (@($chunk | ForEach-Object { Quote-SqlLiteral $_ }) -join ",")

      $cmd = $Connection.CreateCommand()
      $cmd.CommandTimeout = 120
      $cmd.CommandText = @"
SELECT $columnSql
FROM dbo.$(Quote-SqlIdent $TableName) WITH (NOLOCK)
WHERE [Tanggal] >= @start_date
  AND [Tanggal] < @end_exclusive
  AND [Nota] IN ($inList)
$orderSql
"@
      [void]$cmd.Parameters.Add("@start_date", [System.Data.SqlDbType]::DateTime)
      [void]$cmd.Parameters.Add("@end_exclusive", [System.Data.SqlDbType]::DateTime)
      $cmd.Parameters["@start_date"].Value = $StartDate
      $cmd.Parameters["@end_exclusive"].Value = $EndExclusive

      $reader = $null
      $batchCount = 0L
      try {
        $reader = $cmd.ExecuteReader([System.Data.CommandBehavior]::SequentialAccess)
        while ($reader.Read()) {
          $values = New-Object string[] $Columns.Count
          for ($i = 0; $i -lt $Columns.Count; $i++) {
            $values[$i] = Escape-CsvValue $reader.GetValue($i)
          }
          $writer.WriteLine($values -join ",")
          $batchCount++
          $total++
        }
      } finally {
        if ($reader) { $reader.Close() }
      }
      $writer.Flush()
      Write-Host ("{0} chunk {1}-{2}: {3} rows (total {4})" -f $TableName, ($offset + 1), ($end + 1), $batchCount, $total)
    }
  } finally {
    $writer.Close()
  }
  return $total
}

$runId = Get-Date -Format "yyyyMMdd-HHmmss"
$outputDir = Join-Path $OutputRoot $runId
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

$notas = @(
  Import-Csv -LiteralPath $NotaCsv |
    ForEach-Object { "$($_.nota)".Trim().ToUpperInvariant() } |
    Where-Object { $_ -ne "" } |
    Sort-Object -Unique
)
if ($notas.Count -eq 0) {
  throw "Tidak ada nota valid di $NotaCsv"
}

$hjualsmColumns = @(
  "Tanggal", "Nota", "KodeSales", "NamaSales", "KodeCustomer", "NamaCustomer",
  "Alamat", "KodePrinciple", "NamaPrinciple", "Keterangan", "JatuhTempo",
  "TotalPenjualan", "TotalRetur", "Terbayar", "FP", "P", "Harga", "Tunai",
  "StNota", "StTranfer", "UserAdd", "TglAdd", "UserEdit", "UserPK", "TglPK",
  "UserBatal", "TglBatal", "KetBatal", "UserReal", "TglReal", "CountPrint"
)
$djualsmColumns = @(
  "Tanggal", "Nota", "KodeStok", "MasterKode", "NamaStok", "Unit", "CT",
  "Satuan", "PC", "PerUnit", "Jumlah", "Harga", "Disc1", "Disc2", "Disc3",
  "DiscRp1", "DiscRp2", "DiscRp3", "DiscRp", "JumlahExPPN", "JumlahHarga",
  "KodeSales", "NamaSales", "KodeCustomer", "NamaCustomer", "KodePrinciple",
  "Urut", "StNota", "TglReal"
)

$builder = New-Object System.Data.SqlClient.SqlConnectionStringBuilder
$builder["Data Source"] = $SqlServer
$builder["Initial Catalog"] = $SqlDatabase
$builder["User ID"] = $SqlUser
$builder["Password"] = $SqlPassword
$builder["Connect Timeout"] = 30
$builder["Encrypt"] = $false
$builder["TrustServerCertificate"] = $true
$connection = New-Object System.Data.SqlClient.SqlConnection $builder.ConnectionString

try {
  $connection.Open()
  if ($ExistingHjualsmCsv) {
    if (-not (Test-Path -LiteralPath $ExistingHjualsmCsv)) {
      throw "Existing HJualSM CSV tidak ditemukan: $ExistingHjualsmCsv"
    }
    $hjualsmCsv = (Resolve-Path -LiteralPath $ExistingHjualsmCsv).Path
    $hjualsmRows = [Math]::Max(((Get-Content -LiteralPath $hjualsmCsv | Measure-Object -Line).Lines - 1), 0)
    Write-Host "Reuse HJualSM CSV: $hjualsmCsv ($hjualsmRows rows)"
  } else {
    $hjualsmCsv = Join-Path $outputDir "HJualSM.csv"
    $hjualsmRows = Export-TargetTable $connection "HJualSM" $hjualsmColumns $notas $hjualsmCsv
  }
  $djualsmCsv = Join-Path $outputDir "DJualSM.csv"
  $djualsmRows = Export-TargetTable $connection "DJualSM" $djualsmColumns $notas $djualsmCsv
} finally {
  if ($connection.State -eq [System.Data.ConnectionState]::Open) {
    $connection.Close()
  }
}

$pgSchemaIdent = Quote-PgIdent $PgSchema
$templateSchemaIdent = Quote-PgIdent $TemplateSchema

Invoke-Psql @"
CREATE SCHEMA IF NOT EXISTS $pgSchemaIdent;
CREATE TABLE IF NOT EXISTS $pgSchemaIdent."hjualsm" (LIKE $templateSchemaIdent."hjualsm" INCLUDING ALL);
CREATE TABLE IF NOT EXISTS $pgSchemaIdent."djualsm" (LIKE $templateSchemaIdent."djualsm" INCLUDING ALL);
CREATE TABLE IF NOT EXISTS $pgSchemaIdent."hjualsmandroid" (LIKE $templateSchemaIdent."hjualsmandroid" INCLUDING ALL);
CREATE TABLE IF NOT EXISTS $pgSchemaIdent."djualsmandroid" (LIKE $templateSchemaIdent."djualsmandroid" INCLUDING ALL);
TRUNCATE TABLE $pgSchemaIdent."hjualsm";
TRUNCATE TABLE $pgSchemaIdent."djualsm";
TRUNCATE TABLE $pgSchemaIdent."hjualsmandroid";
TRUNCATE TABLE $pgSchemaIdent."djualsmandroid";
"@

$hCopyPath = (Resolve-Path -LiteralPath $hjualsmCsv).Path.Replace("\", "/").Replace("'", "''")
$dCopyPath = (Resolve-Path -LiteralPath $djualsmCsv).Path.Replace("\", "/").Replace("'", "''")
$hColumnList = (@($hjualsmColumns | ForEach-Object { Quote-PgIdent $_.ToLowerInvariant() }) -join ", ")
$dColumnList = (@($djualsmColumns | ForEach-Object { Quote-PgIdent $_.ToLowerInvariant() }) -join ", ")
$copySqlPath = Join-Path $outputDir "copy_to_pg.sql"
@"
\copy $pgSchemaIdent."hjualsm" ($hColumnList) FROM '$hCopyPath' WITH (FORMAT csv, HEADER true, NULL '')
\copy $pgSchemaIdent."djualsm" ($dColumnList) FROM '$dCopyPath' WITH (FORMAT csv, HEADER true, NULL '')
"@ | Set-Content -Encoding ASCII -Path $copySqlPath
Invoke-PsqlFile $copySqlPath

$manifestPath = Join-Path $outputDir "manifest.csv"
@(
  [pscustomobject]@{ table_name = "dbo.HJualSM"; rows_exported = $hjualsmRows; csv_path = (Resolve-Path -LiteralPath $hjualsmCsv).Path }
  [pscustomobject]@{ table_name = "dbo.DJualSM"; rows_exported = $djualsmRows; csv_path = (Resolve-Path -LiteralPath $djualsmCsv).Path }
) | Export-Csv -NoTypeInformation -Encoding UTF8 -Path $manifestPath

Invoke-Psql @"
CREATE TABLE IF NOT EXISTS $pgSchemaIdent.__migration_manifest (
  table_name text PRIMARY KEY,
  rows_exported bigint NOT NULL,
  csv_path text NOT NULL,
  imported_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO $pgSchemaIdent.__migration_manifest (table_name, rows_exported, csv_path, imported_at)
VALUES
  ('dbo.HJualSM', $hjualsmRows, '$(Escape-SqlLiteral (Resolve-Path -LiteralPath $hjualsmCsv).Path)', now()),
  ('dbo.DJualSM', $djualsmRows, '$(Escape-SqlLiteral (Resolve-Path -LiteralPath $djualsmCsv).Path)', now())
ON CONFLICT (table_name)
DO UPDATE SET rows_exported = EXCLUDED.rows_exported,
              csv_path = EXCLUDED.csv_path,
              imported_at = now();
ANALYZE $pgSchemaIdent."hjualsm";
ANALYZE $pgSchemaIdent."djualsm";
"@

Write-Host "Import selesai: $outputDir"
Write-Host "HJualSM rows: $hjualsmRows"
Write-Host "DJualSM rows: $djualsmRows"
