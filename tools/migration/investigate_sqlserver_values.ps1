
param(
  [string]$ValuesPath = ".\tools\migration\.tmp_audit\c015_investigation_values.json",
  [string]$OutputPath = ".\tools\migration\.tmp_audit\c015_sqlserver_value_hits.csv",
  [string]$Server = "192.168.1.8,1433",
  [string]$Database = "DIST",
  [string]$User = "sa",
  [string]$Password = "Budimas6789"
)
$ErrorActionPreference = "Stop"
$valuesJson = Get-Content -LiteralPath $ValuesPath -Raw | ConvertFrom-Json
$tokens = New-Object System.Collections.Generic.HashSet[string]
function Add-Token([string]$value) {
  if ([string]::IsNullOrWhiteSpace($value)) { return }
  $v = $value.Trim()
  if ($v.Length -lt 4) { return }
  if ($v -match '^[0-9]+(\.[0-9]+)?$' -and $v.Length -lt 6) { return }
  [void]$tokens.Add($v)
}
foreach ($fileProp in $valuesJson.PSObject.Properties) {
  foreach ($colProp in $fileProp.Value.PSObject.Properties) {
    foreach ($v in @($colProp.Value)) { Add-Token "$v" }
  }
}
# Focus tokens to keep search practical.
$focus = @($tokens | Where-Object {
  $_ -like 'C015*' -or $_ -like 'SIC015*' -or $_ -like 'U-SOC015*' -or $_ -match '^[0-9]{4}[A-Z]' -or $_ -like 'I13-*' -or $_ -like 'SOI13-*' -or $_ -like 'TI*' -or $_ -like '4.*' -or $_ -like 'KKIC*' -or $_ -like 'MC*' -or $_ -like 'MK*' -or $_ -like 'SZ*' -or $_ -in @('0181','2304','2306','2313','C000015','C01505','C01507','C01514','C01517')
} | Select-Object -Unique)
Write-Host "Tokens to search: $($focus.Count)"
$quoted = ($focus | ForEach-Object { "'" + $_.Replace("'", "''") + "'" }) -join ","
$connStr = "Server=$Server;Database=$Database;User ID=$User;Password=$Password;TrustServerCertificate=True;Encrypt=False;Connection Timeout=45"
$conn = New-Object System.Data.SqlClient.SqlConnection $connStr
$conn.Open()
$cmd = $conn.CreateCommand()
$cmd.CommandTimeout = 120
$cmd.CommandText = @"
SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'dbo'
  AND DATA_TYPE IN ('char','varchar','nchar','nvarchar','text','ntext')
ORDER BY TABLE_NAME, ORDINAL_POSITION
"@
$adapter = New-Object System.Data.SqlClient.SqlDataAdapter $cmd
$cols = New-Object System.Data.DataTable
[void]$adapter.Fill($cols)
$result = New-Object System.Collections.Generic.List[object]
foreach ($r in $cols.Rows) {
  $schema = $r.TABLE_SCHEMA; $table = $r.TABLE_NAME; $col = $r.COLUMN_NAME
  $sql = "SELECT TOP 5 RTRIM(CAST([$col] AS varchar(255))) AS hit_value, COUNT(*) OVER() AS total_hits FROM [$schema].[$table] WHERE RTRIM(CAST([$col] AS varchar(255))) IN ($quoted)"
  try {
    $c = $conn.CreateCommand(); $c.CommandTimeout = 8; $c.CommandText = $sql
    $da = New-Object System.Data.SqlClient.SqlDataAdapter $c
    $dt = New-Object System.Data.DataTable
    [void]$da.Fill($dt)
    if ($dt.Rows.Count -gt 0) {
      $sample = @($dt.Rows | ForEach-Object { $_.hit_value }) -join '; '
      $result.Add([pscustomobject]@{ table="$schema.$table"; column=$col; total_hits=$dt.Rows[0].total_hits; sample_values=$sample })
      Write-Host "HIT $schema.$table.$col -> $($dt.Rows[0].total_hits)"
    }
  } catch {
    # Skip broken views/legacy text conversion errors.
  }
}
$conn.Close()
$result | Sort-Object {[int]$_.total_hits} -Descending | Export-Csv -NoTypeInformation -Encoding UTF8 -Path $OutputPath
Write-Host "Saved: $OutputPath"
