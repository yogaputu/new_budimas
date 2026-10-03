param(
  [string]$NotaCsv = ".\.tmp_audit\unresolved_payment_nota_2025_candidates.csv",
  [string]$ExistingHjualsmCsv = ".\.tmp_audit\sqlserver_2025_ar_pg_legacy\20260603-034653\HJualSM.csv",
  [string]$OutputRoot = ".\.tmp_audit\sqlserver_2025_ar_pg_legacy",
  [string]$RunName = "targeted_2025_ar",
  [string]$SqlServer = "192.168.1.8,1433",
  [string]$SqlDatabase = "DIST",
  [string]$SqlUser = "sa",
  [string]$SqlPassword = "",
  [datetime]$StartDate = [datetime]"2025-01-01",
  [datetime]$EndExclusive = [datetime]"2026-01-01",
  [int]$ChunkSize = 50,
  [int]$MaxChunkAttempts = 5,
  [int]$RetryDelaySeconds = 10,
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
if (-not (Test-Path -LiteralPath $ExistingHjualsmCsv)) {
  throw "HJualSM CSV tidak ditemukan: $ExistingHjualsmCsv"
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

function New-SqlConnection {
  $builder = New-Object System.Data.SqlClient.SqlConnectionStringBuilder
  $builder["Data Source"] = $SqlServer
  $builder["Initial Catalog"] = $SqlDatabase
  $builder["User ID"] = $SqlUser
  $builder["Password"] = $SqlPassword
  $builder["Connect Timeout"] = 30
  $builder["Encrypt"] = $false
  $builder["TrustServerCertificate"] = $true
  return New-Object System.Data.SqlClient.SqlConnection $builder.ConnectionString
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

function Export-DjualsmChunk {
  param(
    [string[]]$Notas,
    [string[]]$Columns,
    [string]$ChunkPath
  )

  $tmpPath = "$ChunkPath.tmp"
  if (Test-Path -LiteralPath $tmpPath) {
    Remove-Item -LiteralPath $tmpPath -Force
  }

  $connection = New-SqlConnection
  $writer = $null
  $reader = $null
  $count = 0L
  try {
    $connection.Open()
    $columnSql = (@($Columns | ForEach-Object { Quote-SqlIdent $_ }) -join ", ")
    $inList = (@($Notas | ForEach-Object { Quote-SqlLiteral $_ }) -join ",")
    $cmd = $connection.CreateCommand()
    $cmd.CommandTimeout = 180
    $cmd.CommandText = @"
SELECT $columnSql
FROM dbo.$(Quote-SqlIdent "DJualSM") WITH (NOLOCK)
WHERE [Tanggal] >= @start_date
  AND [Tanggal] < @end_exclusive
  AND [Nota] IN ($inList)
ORDER BY [Tanggal], [Nota], [Urut]
"@
    [void]$cmd.Parameters.Add("@start_date", [System.Data.SqlDbType]::DateTime)
    [void]$cmd.Parameters.Add("@end_exclusive", [System.Data.SqlDbType]::DateTime)
    $cmd.Parameters["@start_date"].Value = $StartDate
    $cmd.Parameters["@end_exclusive"].Value = $EndExclusive

    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $writer = New-Object System.IO.StreamWriter($tmpPath, $false, $utf8)
    $writer.WriteLine((@($Columns | ForEach-Object { Escape-CsvValue $_.ToLowerInvariant() }) -join ","))

    $reader = $cmd.ExecuteReader([System.Data.CommandBehavior]::SequentialAccess)
    while ($reader.Read()) {
      $values = New-Object string[] $Columns.Count
      for ($i = 0; $i -lt $Columns.Count; $i++) {
        $values[$i] = Escape-CsvValue $reader.GetValue($i)
      }
      $writer.WriteLine($values -join ",")
      $count++
    }
  } finally {
    if ($reader) { $reader.Close() }
    if ($writer) { $writer.Close() }
    if ($connection.State -eq [System.Data.ConnectionState]::Open) { $connection.Close() }
  }

  if (Test-Path -LiteralPath $ChunkPath) {
    Remove-Item -LiteralPath $ChunkPath -Force
  }
  Move-Item -LiteralPath $tmpPath -Destination $ChunkPath
  return $count
}

function Combine-CsvChunks {
  param(
    [string[]]$ChunkPaths,
    [string]$OutputPath
  )

  $utf8 = New-Object System.Text.UTF8Encoding($false)
  $writer = New-Object System.IO.StreamWriter($OutputPath, $false, $utf8)
  $total = 0L
  try {
    $wroteHeader = $false
    foreach ($path in $ChunkPaths) {
      $reader = New-Object System.IO.StreamReader($path)
      try {
        $header = $reader.ReadLine()
        if (-not $wroteHeader) {
          $writer.WriteLine($header)
          $wroteHeader = $true
        }
        while (-not $reader.EndOfStream) {
          $line = $reader.ReadLine()
          if ($line -ne $null) {
            $writer.WriteLine($line)
            $total++
          }
        }
      } finally {
        $reader.Close()
      }
    }
  } finally {
    $writer.Close()
  }
  return $total
}

$notas = @(
  Import-Csv -LiteralPath $NotaCsv |
    ForEach-Object { "$($_.nota)".Trim().ToUpperInvariant() } |
    Where-Object { $_ -ne "" } |
    Sort-Object -Unique
)
if ($notas.Count -eq 0) {
  throw "Tidak ada nota valid di $NotaCsv"
}

$outputDir = Join-Path $OutputRoot $RunName
$chunkDir = Join-Path $outputDir "djualsm_chunks"
New-Item -ItemType Directory -Force -Path $chunkDir | Out-Null

$djualsmColumns = @(
  "Tanggal", "Nota", "KodeStok", "MasterKode", "NamaStok", "Unit", "CT",
  "Satuan", "PC", "PerUnit", "Jumlah", "Harga", "Disc1", "Disc2", "Disc3",
  "DiscRp1", "DiscRp2", "DiscRp3", "DiscRp", "JumlahExPPN", "JumlahHarga",
  "KodeSales", "NamaSales", "KodeCustomer", "NamaCustomer", "KodePrinciple",
  "Urut", "StNota", "TglReal"
)

$chunkPaths = New-Object System.Collections.Generic.List[string]
$chunkIndex = 0
for ($offset = 0; $offset -lt $notas.Count; $offset += $ChunkSize) {
  $chunkIndex++
  $end = [Math]::Min($offset + $ChunkSize - 1, $notas.Count - 1)
  $chunk = @($notas[$offset..$end])
  $chunkPath = Join-Path $chunkDir ("DJualSM_{0:D4}_{1:D5}-{2:D5}.csv" -f $chunkIndex, ($offset + 1), ($end + 1))
  [void]$chunkPaths.Add($chunkPath)

  if (Test-Path -LiteralPath $chunkPath) {
    $existingRows = [Math]::Max(((Get-Content -LiteralPath $chunkPath | Measure-Object -Line).Lines - 1), 0)
    Write-Host ("DJualSM chunk {0}-{1}: skip existing {2} rows" -f ($offset + 1), ($end + 1), $existingRows)
    continue
  }

  $success = $false
  for ($attempt = 1; $attempt -le $MaxChunkAttempts; $attempt++) {
    try {
      $rows = Export-DjualsmChunk $chunk $djualsmColumns $chunkPath
      Write-Host ("DJualSM chunk {0}-{1}: {2} rows" -f ($offset + 1), ($end + 1), $rows)
      $success = $true
      break
    } catch {
      if (Test-Path -LiteralPath "$chunkPath.tmp") {
        Remove-Item -LiteralPath "$chunkPath.tmp" -Force
      }
      Write-Warning ("DJualSM chunk {0}-{1} attempt {2}/{3} failed: {4}" -f ($offset + 1), ($end + 1), $attempt, $MaxChunkAttempts, $_.Exception.Message.Split([Environment]::NewLine)[0])
      if ($attempt -lt $MaxChunkAttempts) {
        Start-Sleep -Seconds $RetryDelaySeconds
      }
    }
  }
  if (-not $success) {
    throw "Gagal export DJualSM chunk $($offset + 1)-$($end + 1) setelah $MaxChunkAttempts attempt"
  }
}

$hjualsmCsv = (Resolve-Path -LiteralPath $ExistingHjualsmCsv).Path
$djualsmCsv = Join-Path $outputDir "DJualSM.csv"
$djualsmRows = Combine-CsvChunks (@($chunkPaths)) $djualsmCsv
$hjualsmRows = [Math]::Max(((Get-Content -LiteralPath $hjualsmCsv | Measure-Object -Line).Lines - 1), 0)

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

$hCopyPath = $hjualsmCsv.Replace("\", "/").Replace("'", "''")
$dCopyPath = (Resolve-Path -LiteralPath $djualsmCsv).Path.Replace("\", "/").Replace("'", "''")
$hColumnList = '"tanggal", "nota", "kodesales", "namasales", "kodecustomer", "namacustomer", "alamat", "kodeprinciple", "namaprinciple", "keterangan", "jatuhtempo", "totalpenjualan", "totalretur", "terbayar", "fp", "p", "harga", "tunai", "stnota", "sttranfer", "useradd", "tgladd", "useredit", "userpk", "tglpk", "userbatal", "tglbatal", "ketbatal", "userreal", "tglreal", "countprint"'
$dColumnList = (@($djualsmColumns | ForEach-Object { Quote-PgIdent $_.ToLowerInvariant() }) -join ", ")
$copySqlPath = Join-Path $outputDir "copy_to_pg.sql"
@"
\copy $pgSchemaIdent."hjualsm" ($hColumnList) FROM '$hCopyPath' WITH (FORMAT csv, HEADER true, NULL '')
\copy $pgSchemaIdent."djualsm" ($dColumnList) FROM '$dCopyPath' WITH (FORMAT csv, HEADER true, NULL '')
"@ | Set-Content -Encoding ASCII -Path $copySqlPath
Invoke-PsqlFile $copySqlPath

Invoke-Psql @"
CREATE TABLE IF NOT EXISTS $pgSchemaIdent.__migration_manifest (
  table_name text PRIMARY KEY,
  rows_exported bigint NOT NULL,
  csv_path text NOT NULL,
  imported_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO $pgSchemaIdent.__migration_manifest (table_name, rows_exported, csv_path, imported_at)
VALUES
  ('dbo.HJualSM', $hjualsmRows, '$(Escape-SqlLiteral $hjualsmCsv)', now()),
  ('dbo.DJualSM', $djualsmRows, '$(Escape-SqlLiteral (Resolve-Path -LiteralPath $djualsmCsv).Path)', now())
ON CONFLICT (table_name)
DO UPDATE SET rows_exported = EXCLUDED.rows_exported,
              csv_path = EXCLUDED.csv_path,
              imported_at = now();
ANALYZE $pgSchemaIdent."hjualsm";
ANALYZE $pgSchemaIdent."djualsm";
ANALYZE $pgSchemaIdent."hjualsmandroid";
ANALYZE $pgSchemaIdent."djualsmandroid";
"@

Write-Host "Import selesai: $outputDir"
Write-Host "HJualSM rows: $hjualsmRows"
Write-Host "DJualSM rows: $djualsmRows"
