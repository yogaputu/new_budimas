param(
  [string]$NotaCsv = ".\.tmp_audit\unresolved_payment_nota_2025_candidates.csv",
  [string]$OutputRoot = ".\.tmp_audit\sqlserver_2025_unresolved_sales_check",
  [string]$Server = "192.168.1.8,1433",
  [string]$Database = "DIST",
  [string]$User = "sa",
  [string]$Password = "",
  [datetime]$StartDate = [datetime]"2025-01-01",
  [datetime]$EndExclusive = [datetime]"2026-01-01",
  [switch]$ExportRows
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $NotaCsv)) {
  throw "Nota CSV tidak ditemukan: $NotaCsv"
}

if (-not $Password -and $env:SQLSERVER_PASSWORD) {
  $Password = $env:SQLSERVER_PASSWORD
}

if (-not $Password) {
  $secure = Read-Host "SQL Server password" -AsSecureString
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try {
    $Password = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
  } finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
  }
}

function Quote-SqlIdent {
  param([string]$Value)
  return "[" + $Value.Replace("]", "]]") + "]"
}

function ConvertTo-DataRows {
  param([System.Data.DataTable]$Table)
  foreach ($row in $Table.Rows) {
    $obj = [ordered]@{}
    foreach ($col in $Table.Columns) {
      $value = $row[$col.ColumnName]
      if ($value -is [System.DBNull]) { $value = $null }
      $obj[$col.ColumnName] = $value
    }
    [pscustomobject]$obj
  }
}

function Export-DataTable {
  param(
    [System.Data.DataTable]$Table,
    [string]$Path
  )
  ConvertTo-DataRows $Table | Export-Csv -NoTypeInformation -Encoding UTF8 -Path $Path
}

function Invoke-Scalar {
  param(
    [System.Data.SqlClient.SqlConnection]$Connection,
    [string]$Sql,
    [hashtable]$Params = @{}
  )
  $cmd = $Connection.CreateCommand()
  $cmd.CommandTimeout = 120
  $cmd.CommandText = $Sql
  foreach ($name in $Params.Keys) {
    [void]$cmd.Parameters.AddWithValue($name, $Params[$name])
  }
  return $cmd.ExecuteScalar()
}

function Invoke-NonQuery {
  param(
    [System.Data.SqlClient.SqlConnection]$Connection,
    [string]$Sql,
    [hashtable]$Params = @{}
  )
  $cmd = $Connection.CreateCommand()
  $cmd.CommandTimeout = 0
  $cmd.CommandText = $Sql
  foreach ($name in $Params.Keys) {
    [void]$cmd.Parameters.AddWithValue($name, $Params[$name])
  }
  [void]$cmd.ExecuteNonQuery()
}

function Invoke-Query {
  param(
    [System.Data.SqlClient.SqlConnection]$Connection,
    [string]$Sql,
    [hashtable]$Params = @{}
  )
  $cmd = $Connection.CreateCommand()
  $cmd.CommandTimeout = 0
  $cmd.CommandText = $Sql
  foreach ($name in $Params.Keys) {
    [void]$cmd.Parameters.AddWithValue($name, $Params[$name])
  }
  $adapter = New-Object System.Data.SqlClient.SqlDataAdapter $cmd
  $table = New-Object System.Data.DataTable
  [void]$adapter.Fill($table)
  return ,$table
}

function Test-SourceColumn {
  param(
    [System.Data.SqlClient.SqlConnection]$Connection,
    [string]$TableName,
    [string]$ColumnName
  )
  $count = Invoke-Scalar $Connection @"
SELECT COUNT(*)
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'dbo'
  AND TABLE_NAME = @table_name
  AND COLUMN_NAME = @column_name
"@ @{
    "@table_name" = $TableName
    "@column_name" = $ColumnName
  }
  return ([int]$count -gt 0)
}

function Update-StatusFromSource {
  param(
    [System.Data.SqlClient.SqlConnection]$Connection,
    [string]$TableName,
    [string]$MatchColumn,
    [string]$RowsColumn,
    [string]$MinDateColumn,
    [string]$MaxDateColumn
  )

  if (-not (Test-SourceColumn $Connection $TableName $MatchColumn)) {
    Write-Warning "Skip dbo.${TableName}.${MatchColumn}: kolom tidak ditemukan"
    return
  }
  if (-not (Test-SourceColumn $Connection $TableName "Tanggal")) {
    Write-Warning "Skip dbo.${TableName}: kolom Tanggal tidak ditemukan"
    return
  }

  $tableIdent = Quote-SqlIdent $TableName
  $matchIdent = Quote-SqlIdent $MatchColumn
  $rowsIdent = Quote-SqlIdent $RowsColumn
  $minIdent = Quote-SqlIdent $MinDateColumn
  $maxIdent = Quote-SqlIdent $MaxDateColumn

  Invoke-NonQuery $Connection @"
UPDATE s
SET $rowsIdent = x.row_count,
    $minIdent = x.min_tanggal,
    $maxIdent = x.max_tanggal
FROM #nota_status s
INNER JOIN (
  SELECT
    UPPER(LTRIM(RTRIM(CAST(src.$matchIdent AS varchar(100))))) AS nota,
    COUNT(*) AS row_count,
    MIN(src.[Tanggal]) AS min_tanggal,
    MAX(src.[Tanggal]) AS max_tanggal
  FROM dbo.$tableIdent src WITH (NOLOCK)
  INNER JOIN #target_nota n
    ON n.nota = UPPER(LTRIM(RTRIM(CAST(src.$matchIdent AS varchar(100)))))
  WHERE src.[Tanggal] >= @start_date
    AND src.[Tanggal] < @end_exclusive
  GROUP BY UPPER(LTRIM(RTRIM(CAST(src.$matchIdent AS varchar(100)))))
) x ON x.nota = s.nota
"@ @{
    "@start_date" = $StartDate
    "@end_exclusive" = $EndExclusive
  }
}

function Export-MatchingRows {
  param(
    [System.Data.SqlClient.SqlConnection]$Connection,
    [string]$TableName,
    [string]$MatchColumn,
    [string]$OutputPath
  )

  if (-not (Test-SourceColumn $Connection $TableName $MatchColumn)) {
    return
  }
  if (-not (Test-SourceColumn $Connection $TableName "Tanggal")) {
    return
  }

  $tableIdent = Quote-SqlIdent $TableName
  $matchIdent = Quote-SqlIdent $MatchColumn
  $data = Invoke-Query $Connection @"
SELECT src.*
FROM dbo.$tableIdent src WITH (NOLOCK)
INNER JOIN #target_nota n
  ON src.$matchIdent = n.nota
WHERE src.[Tanggal] >= @start_date
  AND src.[Tanggal] < @end_exclusive
ORDER BY src.[Tanggal], src.$matchIdent
"@ @{
    "@start_date" = $StartDate
    "@end_exclusive" = $EndExclusive
  }
  Export-DataTable $data $OutputPath
  Write-Host "$TableName by $MatchColumn : $($data.Rows.Count) rows -> $OutputPath"
}

$runId = Get-Date -Format "yyyyMMdd-HHmmss"
$outputDir = Join-Path $OutputRoot $runId
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

$notaRows = @(
  Import-Csv -LiteralPath $NotaCsv |
    ForEach-Object { "$($_.nota)".Trim().ToUpperInvariant() } |
    Where-Object { $_ -ne "" } |
    Sort-Object -Unique
)

if ($notaRows.Count -eq 0) {
  throw "Tidak ada nota valid di $NotaCsv"
}

$connectionString = "Server=$Server;Database=$Database;User ID=$User;Password=$Password;TrustServerCertificate=True;Encrypt=False;Connection Timeout=30"
$connection = New-Object System.Data.SqlClient.SqlConnection $connectionString

try {
  $connection.Open()

  Invoke-NonQuery $connection @"
CREATE TABLE #target_nota (
  nota varchar(100) NOT NULL PRIMARY KEY
);

CREATE TABLE #nota_status (
  nota varchar(100) NOT NULL PRIMARY KEY,
  hjualsm_header_rows int NOT NULL DEFAULT 0,
  hjualsm_header_min_tanggal datetime NULL,
  hjualsm_header_max_tanggal datetime NULL,
  djualsm_detail_rows int NOT NULL DEFAULT 0,
  djualsm_detail_min_tanggal datetime NULL,
  djualsm_detail_max_tanggal datetime NULL,
  hjualsmandroid_header_by_nofaktur_rows int NOT NULL DEFAULT 0,
  hjualsmandroid_header_by_nofaktur_min_tanggal datetime NULL,
  hjualsmandroid_header_by_nofaktur_max_tanggal datetime NULL,
  djualsmandroid_detail_by_nofaktur_rows int NOT NULL DEFAULT 0,
  djualsmandroid_detail_by_nofaktur_min_tanggal datetime NULL,
  djualsmandroid_detail_by_nofaktur_max_tanggal datetime NULL,
  hjualsmandroid_header_by_nota_rows int NOT NULL DEFAULT 0,
  hjualsmandroid_header_by_nota_min_tanggal datetime NULL,
  hjualsmandroid_header_by_nota_max_tanggal datetime NULL,
  djualsmandroid_detail_by_nota_rows int NOT NULL DEFAULT 0,
  djualsmandroid_detail_by_nota_min_tanggal datetime NULL,
  djualsmandroid_detail_by_nota_max_tanggal datetime NULL
);
"@

  for ($offset = 0; $offset -lt $notaRows.Count; $offset += 500) {
    $chunk = @($notaRows[$offset..([Math]::Min($offset + 499, $notaRows.Count - 1))])
    $values = New-Object System.Collections.Generic.List[string]
    $params = @{}
    for ($i = 0; $i -lt $chunk.Count; $i++) {
      $paramName = "@n$i"
      $values.Add("($paramName)")
      $params[$paramName] = $chunk[$i]
    }
    Invoke-NonQuery $connection ("INSERT INTO #target_nota (nota) VALUES " + ($values -join ",")) $params
  }

  Invoke-NonQuery $connection "INSERT INTO #nota_status (nota) SELECT nota FROM #target_nota;"

  Update-StatusFromSource $connection "HJualSM" "Nota" "hjualsm_header_rows" "hjualsm_header_min_tanggal" "hjualsm_header_max_tanggal"
  Update-StatusFromSource $connection "DJualSM" "Nota" "djualsm_detail_rows" "djualsm_detail_min_tanggal" "djualsm_detail_max_tanggal"
  Update-StatusFromSource $connection "HJualSMAndroid" "NoFaktur" "hjualsmandroid_header_by_nofaktur_rows" "hjualsmandroid_header_by_nofaktur_min_tanggal" "hjualsmandroid_header_by_nofaktur_max_tanggal"
  Update-StatusFromSource $connection "DJualSMAndroid" "NoFaktur" "djualsmandroid_detail_by_nofaktur_rows" "djualsmandroid_detail_by_nofaktur_min_tanggal" "djualsmandroid_detail_by_nofaktur_max_tanggal"
  Update-StatusFromSource $connection "HJualSMAndroid" "Nota" "hjualsmandroid_header_by_nota_rows" "hjualsmandroid_header_by_nota_min_tanggal" "hjualsmandroid_header_by_nota_max_tanggal"
  Update-StatusFromSource $connection "DJualSMAndroid" "Nota" "djualsmandroid_detail_by_nota_rows" "djualsmandroid_detail_by_nota_min_tanggal" "djualsmandroid_detail_by_nota_max_tanggal"

  $status = Invoke-Query $connection "SELECT * FROM #nota_status ORDER BY nota;"
  Export-DataTable $status (Join-Path $outputDir "nota_status.csv")

  $summary = Invoke-Query $connection @"
SELECT 'target_nota' AS metric, CAST(COUNT(*) AS bigint) AS value FROM #nota_status
UNION ALL SELECT 'found_any_table', COUNT(*) FROM #nota_status
WHERE hjualsm_header_rows > 0
   OR djualsm_detail_rows > 0
   OR hjualsmandroid_header_by_nofaktur_rows > 0
   OR djualsmandroid_detail_by_nofaktur_rows > 0
   OR hjualsmandroid_header_by_nota_rows > 0
   OR djualsmandroid_detail_by_nota_rows > 0
UNION ALL SELECT 'hjualsm_header_nota', COUNT(*) FROM #nota_status WHERE hjualsm_header_rows > 0
UNION ALL SELECT 'djualsm_detail_nota', COUNT(*) FROM #nota_status WHERE djualsm_detail_rows > 0
UNION ALL SELECT 'hjualsmandroid_header_nofaktur', COUNT(*) FROM #nota_status WHERE hjualsmandroid_header_by_nofaktur_rows > 0
UNION ALL SELECT 'djualsmandroid_detail_nofaktur', COUNT(*) FROM #nota_status WHERE djualsmandroid_detail_by_nofaktur_rows > 0
UNION ALL SELECT 'hjualsmandroid_header_nota', COUNT(*) FROM #nota_status WHERE hjualsmandroid_header_by_nota_rows > 0
UNION ALL SELECT 'djualsmandroid_detail_nota', COUNT(*) FROM #nota_status WHERE djualsmandroid_detail_by_nota_rows > 0
UNION ALL SELECT 'missing_all_tables', COUNT(*) FROM #nota_status
WHERE hjualsm_header_rows = 0
  AND djualsm_detail_rows = 0
  AND hjualsmandroid_header_by_nofaktur_rows = 0
  AND djualsmandroid_detail_by_nofaktur_rows = 0
  AND hjualsmandroid_header_by_nota_rows = 0
  AND djualsmandroid_detail_by_nota_rows = 0
ORDER BY metric;
"@
  Export-DataTable $summary (Join-Path $outputDir "summary.csv")

  $missing = Invoke-Query $connection @"
SELECT nota
FROM #nota_status
WHERE hjualsm_header_rows = 0
  AND djualsm_detail_rows = 0
  AND hjualsmandroid_header_by_nofaktur_rows = 0
  AND djualsmandroid_detail_by_nofaktur_rows = 0
  AND hjualsmandroid_header_by_nota_rows = 0
  AND djualsmandroid_detail_by_nota_rows = 0
ORDER BY nota;
"@
  Export-DataTable $missing (Join-Path $outputDir "missing_all_tables.csv")

  if ($ExportRows) {
    Export-MatchingRows $connection "HJualSM" "Nota" (Join-Path $outputDir "HJualSM.csv")
    Export-MatchingRows $connection "DJualSM" "Nota" (Join-Path $outputDir "DJualSM.csv")
    Export-MatchingRows $connection "HJualSMAndroid" "NoFaktur" (Join-Path $outputDir "HJualSMAndroid_by_NoFaktur.csv")
    Export-MatchingRows $connection "DJualSMAndroid" "NoFaktur" (Join-Path $outputDir "DJualSMAndroid_by_NoFaktur.csv")
    Export-MatchingRows $connection "HJualSMAndroid" "Nota" (Join-Path $outputDir "HJualSMAndroid_by_Nota.csv")
    Export-MatchingRows $connection "DJualSMAndroid" "Nota" (Join-Path $outputDir "DJualSMAndroid_by_Nota.csv")
  }

  Write-Host "Check selesai: $outputDir"
  ConvertTo-DataRows $summary | Format-Table -AutoSize
} finally {
  if ($connection.State -eq [System.Data.ConnectionState]::Open) {
    $connection.Close()
  }
}
