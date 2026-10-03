param(
  [string]$CandidateCsv = ".\docs\migration_candidates_DIST_2026-01-01_to_2026-06-02.csv",
  [string]$SqlServer = "192.168.1.8,1433",
  [string]$SqlDatabase = "DIST",
  [string]$SqlUser = "sa",
  [string]$SqlPassword = "",
  [datetime]$StartDate = [datetime]"2026-01-01",
  [datetime]$EndExclusive = [datetime]"2026-06-03",
  [string]$PgHost = "127.0.0.1",
  [string]$PgPort = "5432",
  [string]$PgUser = "postgres",
  [string]$PgDatabase = "budimas-dev",
  [string]$PgSchema = "legacy_dist_2026",
  [string]$PsqlPath = "D:\laragon\bin\postgresql\postgresql-14.5-1\bin\psql.exe",
  [string]$OutputRoot = ".\.tmp_audit\sqlserver_2026_pg_legacy",
  [int]$MaxTables = 0,
  [int]$BatchDays = 7,
  [ValidateSet("candidate", "small-first", "large-first")]
  [string]$Order = "candidate"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $CandidateCsv)) {
  throw "Candidate CSV tidak ditemukan: $CandidateCsv"
}
if (-not (Test-Path -LiteralPath $PsqlPath)) {
  throw "psql.exe tidak ditemukan: $PsqlPath"
}
if (-not $SqlPassword) {
  $secure = Read-Host "SQL Server password" -AsSecureString
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  $SqlPassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
}

$runId = Get-Date -Format "yyyyMMdd-HHmmss"
$outputDir = Join-Path $OutputRoot $runId
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

function Quote-PgIdent {
  param([string]$Value)
  return '"' + $Value.Replace('"', '""') + '"'
}

function Quote-SqlIdent {
  param([string]$Value)
  return "[" + $Value.Replace("]", "]]") + "]"
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

function Get-SourceColumns {
  param($Connection, [string]$SchemaName, [string]$TableName)
  $cmd = $Connection.CreateCommand()
  $cmd.CommandText = @"
SELECT c.name AS column_name, ty.name AS data_type, c.column_id
FROM sys.tables t
JOIN sys.schemas s ON s.schema_id = t.schema_id
JOIN sys.columns c ON c.object_id = t.object_id
JOIN sys.types ty ON ty.user_type_id = c.user_type_id
WHERE s.name = @schema_name
  AND t.name = @table_name
ORDER BY c.column_id
"@
  [void]$cmd.Parameters.Add("@schema_name", [System.Data.SqlDbType]::NVarChar, 128)
  [void]$cmd.Parameters.Add("@table_name", [System.Data.SqlDbType]::NVarChar, 128)
  $cmd.Parameters["@schema_name"].Value = $SchemaName
  $cmd.Parameters["@table_name"].Value = $TableName
  $adapter = New-Object System.Data.SqlClient.SqlDataAdapter $cmd
  $table = New-Object System.Data.DataTable
  [void]$adapter.Fill($table)
  return @($table.Rows | ForEach-Object {
    [pscustomobject]@{
      Name = [string]$_["column_name"]
      DataType = [string]$_["data_type"]
      ColumnId = [int]$_["column_id"]
    }
  })
}

function Export-TableCsv {
  param(
    $Connection,
    [string]$SchemaName,
    [string]$TableName,
    [string]$DateColumn,
    [object[]]$Columns,
    [string]$CsvPath
  )
  $columnSql = ($Columns | ForEach-Object { Quote-SqlIdent $_.Name }) -join ", "
  $utf8 = New-Object System.Text.UTF8Encoding($false)
  $writer = New-Object System.IO.StreamWriter($CsvPath, $false, $utf8)
  $count = 0L
  try {
    $writer.WriteLine(($Columns | ForEach-Object { Escape-CsvValue $_.Name }) -join ",")
    $batchStart = $StartDate
    while ($batchStart -lt $EndExclusive) {
      $batchEnd = $batchStart.AddDays($BatchDays)
      if ($batchEnd -gt $EndExclusive) {
        $batchEnd = $EndExclusive
      }
      $cmd = $Connection.CreateCommand()
      $cmd.CommandTimeout = 0
      $cmd.CommandText = "SELECT $columnSql FROM $(Quote-SqlIdent $SchemaName).$(Quote-SqlIdent $TableName) WITH (NOLOCK) WHERE $(Quote-SqlIdent $DateColumn) >= @start AND $(Quote-SqlIdent $DateColumn) < @endExclusive"
      [void]$cmd.Parameters.Add("@start", [System.Data.SqlDbType]::DateTime)
      [void]$cmd.Parameters.Add("@endExclusive", [System.Data.SqlDbType]::DateTime)
      $cmd.Parameters["@start"].Value = $batchStart
      $cmd.Parameters["@endExclusive"].Value = $batchEnd
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
          $count++
          $batchCount++
        }
      } finally {
        if ($reader) { $reader.Close() }
      }
      $writer.Flush()
      Write-Host ("  batch {0:yyyy-MM-dd}..{1:yyyy-MM-dd}: {2} rows (total {3})" -f $batchStart, $batchEnd, $batchCount, $count)
      $batchStart = $batchEnd
    }
  } finally {
    $writer.Close()
  }
  return $count
}

$candidates = @(Import-Csv -LiteralPath $CandidateCsv | Where-Object { [int64]$_.RowsInRange -gt 0 })
if ($Order -eq "small-first") {
  $candidates = @($candidates | Sort-Object {[int64]$_.RowsInRange}, TableName)
} elseif ($Order -eq "large-first") {
  $candidates = @($candidates | Sort-Object {[int64]$_.RowsInRange} -Descending)
}
if ($MaxTables -gt 0) {
  $candidates = @($candidates | Select-Object -First $MaxTables)
}

$manifestPath = Join-Path $outputDir "manifest.csv"
$summary = New-Object System.Collections.Generic.List[object]

Invoke-Psql "CREATE SCHEMA IF NOT EXISTS $(Quote-PgIdent $PgSchema);"
Invoke-Psql @"
CREATE TABLE IF NOT EXISTS $(Quote-PgIdent $PgSchema).__migration_manifest (
  table_name text PRIMARY KEY,
  date_column text NOT NULL,
  rows_exported bigint NOT NULL,
  candidate_rows bigint NOT NULL,
  csv_path text NOT NULL,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz NOT NULL DEFAULT now()
);
"@

$builder = New-Object System.Data.SqlClient.SqlConnectionStringBuilder
$builder["Data Source"] = $SqlServer
$builder["Initial Catalog"] = $SqlDatabase
$builder["User ID"] = $SqlUser
$builder["Password"] = $SqlPassword
$builder["Connect Timeout"] = 15
$builder["Encrypt"] = $false
$builder["TrustServerCertificate"] = $true
$source = New-Object System.Data.SqlClient.SqlConnection $builder.ConnectionString

try {
  $source.Open()
  foreach ($candidate in $candidates) {
    $parts = ([string]$candidate.TableName).Split([char[]]@("."), 2)
    if ($parts.Count -ne 2) {
      throw "Nama tabel tidak valid: $($candidate.TableName)"
    }
    $schemaName = $parts[0]
    $tableName = $parts[1]
    $dateColumn = [string]$candidate.DateColumn
    $columns = @(Get-SourceColumns $source $schemaName $tableName)
    if ($columns.Count -eq 0) {
      Write-Warning "Skip $($candidate.TableName): kolom tidak ditemukan"
      continue
    }

    $stageTableName = $tableName.ToLowerInvariant()
    $pgTable = Quote-PgIdent $stageTableName
    $pgSchemaIdent = Quote-PgIdent $PgSchema
    $columnDefinitions = ($columns | ForEach-Object { "$(Quote-PgIdent ($_.Name.ToLowerInvariant())) text" }) -join ",`n  "
    Invoke-Psql "CREATE TABLE IF NOT EXISTS $pgSchemaIdent.$pgTable (`n  $columnDefinitions`n); TRUNCATE TABLE $pgSchemaIdent.$pgTable;"

    $csvPath = Join-Path $outputDir ($tableName + ".csv")
    Write-Output "Export $($candidate.TableName) [$dateColumn]..."
    $rows = Export-TableCsv $source $schemaName $tableName $dateColumn $columns $csvPath

    $copyPath = (Resolve-Path -LiteralPath $csvPath).Path.Replace("\", "/").Replace("'", "''")
    $columnList = ($columns | ForEach-Object { Quote-PgIdent ($_.Name.ToLowerInvariant()) }) -join ", "
    $copySqlPath = Join-Path $outputDir ($tableName + ".copy.sql")
    "\copy $pgSchemaIdent.$pgTable ($columnList) FROM '$copyPath' WITH (FORMAT csv, HEADER true, NULL '')" | Set-Content -Encoding ASCII -Path $copySqlPath
    Invoke-PsqlFile $copySqlPath

    $escapedTable = Escape-SqlLiteral ([string]$candidate.TableName)
    $escapedDateColumn = Escape-SqlLiteral $dateColumn
    $escapedCsv = Escape-SqlLiteral (Resolve-Path -LiteralPath $csvPath).Path
    Invoke-Psql @"
INSERT INTO $pgSchemaIdent.__migration_manifest (table_name, date_column, rows_exported, candidate_rows, csv_path, finished_at)
VALUES ('$escapedTable', '$escapedDateColumn', $rows, $($candidate.RowsInRange), '$escapedCsv', now())
ON CONFLICT (table_name)
DO UPDATE SET date_column = EXCLUDED.date_column,
              rows_exported = EXCLUDED.rows_exported,
              candidate_rows = EXCLUDED.candidate_rows,
              csv_path = EXCLUDED.csv_path,
              finished_at = now();
"@

    $summary.Add([pscustomobject]@{
      TableName = [string]$candidate.TableName
      DateColumn = $dateColumn
      RowsExported = $rows
      CandidateRows = [int64]$candidate.RowsInRange
      CsvPath = (Resolve-Path -LiteralPath $csvPath).Path
    }) | Out-Null
    Write-Output "Imported $($candidate.TableName): $rows rows"
  }
} finally {
  $source.Close()
}

$summary | Export-Csv -NoTypeInformation -Encoding UTF8 -Path $manifestPath
Write-Output "Legacy staging selesai."
Write-Output "Schema=$PgSchema"
Write-Output "OutputDir=$outputDir"
Write-Output "Manifest=$manifestPath"
Write-Output "Tables=$($summary.Count)"
Write-Output "Rows=$([int64](($summary | Measure-Object RowsExported -Sum).Sum))"
