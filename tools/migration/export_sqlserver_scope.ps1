param(
  [string]$ConfigPath = ".\tools\migration\sqlserver_scope_config.example.json",
  [string]$OutputRoot = ".\.tmp_audit\sqlserver_scope_exports",
  [string]$Server = "192.168.1.8,1433",
  [string]$Database = "DIST",
  [string]$User = "sa",
  [string]$Password = ""
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $ConfigPath)) {
  throw "Config file tidak ditemukan: $ConfigPath"
}

$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$scopeName = if ($config.scope_name) { $config.scope_name } else { "scope_" + (Get-Date -Format "yyyyMMddHHmmss") }
$outputDir = Join-Path $OutputRoot $scopeName
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

if (-not $Password) {
  $Password = Read-Host "SQL Server password" -AsSecureString
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Password)
  $Password = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
}

$connectionString = "Server=$Server;Database=$Database;User ID=$User;Password=$Password;TrustServerCertificate=True;Encrypt=False;Connection Timeout=15"
$connection = New-Object System.Data.SqlClient.SqlConnection $connectionString
$connection.Open()

function Quote-SqlList {
  param([object[]]$Values)
  $clean = @($Values | Where-Object { $_ -ne $null -and "$_".Trim() -ne "" } | ForEach-Object { "'" + "$_".Trim().Replace("'", "''") + "'" })
  if ($clean.Count -eq 0) { return $null }
  return ($clean -join ",")
}

function Invoke-Export {
  param([string]$Name, [string]$Sql)
  $command = $connection.CreateCommand()
  $command.CommandTimeout = 180
  $command.CommandText = $Sql
  $adapter = New-Object System.Data.SqlClient.SqlDataAdapter $command
  $table = New-Object System.Data.DataTable
  [void]$adapter.Fill($table)
  $path = Join-Path $outputDir "$Name.csv"
  $table | Export-Csv -NoTypeInformation -Encoding UTF8 -Path $path
  Write-Output "$Name : $($table.Rows.Count) rows -> $path"
}

$areaList = Quote-SqlList $config.branch.area_codes
$principalList = Quote-SqlList $config.company.principal_codes
$salesList = Quote-SqlList $config.sales_codes
$activeFilterCustomer = if ($config.include_inactive) { "" } else { "AND ISNULL(c.Active, '1') = '1'" }
$activeFilterPrincipal = if ($config.include_inactive) { "" } else { "AND ISNULL(p.Active, '1') = '1'" }
$activeFilterSales = if ($config.include_inactive) { "" } else { "AND ISNULL(s.Active, '1') = '1'" }
$activeFilterProduct = if ($config.include_inactive) { "" } else { "AND ISNULL(st.Active, '1') = '1'" }
$areaFilter = if ($areaList) { "AND RTRIM(c.KodeArea) IN ($areaList)" } else { "" }
$principalFilter = if ($principalList) { "AND RTRIM(p.Kode) IN ($principalList)" } else { "" }
$salesFilter = if ($salesList) { "AND RTRIM(s.Kode) IN ($salesList)" } else { "" }
$plafonAreaFilter = if ($areaList) { "AND RTRIM(c.KodeArea) IN ($areaList)" } else { "" }
$plafonPrincipalFilter = if ($principalList) { "AND RTRIM(pl.KodePrinciple) IN ($principalList)" } else { "" }
$plafonSalesFilter = if ($salesList) { "AND RTRIM(pl.KodeSales) IN ($salesList)" } else { "" }
$productPrincipalFilter = if ($principalList) { "AND RTRIM(st.Principle) IN ($principalList)" } else { "" }
$salesPrincipalFilter = if ($principalList) { "AND RTRIM(s.KodePrinciple) IN ($principalList)" } else { "" }

Invoke-Export "customers" @"
SELECT
  RTRIM(c.Kode) AS kode,
  RTRIM(c.Nama) AS nama,
  RTRIM(c.Alamat) AS alamat,
  RTRIM(c.Telpon) AS telepon,
  RTRIM(c.NPWP) AS npwp,
  RTRIM(c.NamaWP) AS nama_wajib_pajak,
  RTRIM(c.AlamatWP) AS alamat_wajib_pajak,
  RTRIM(c.KodeArea) AS kode_area,
  RTRIM(c.NamaArea) AS nama_area,
  CONVERT(varchar(50), c.Longitude) AS longitude,
  CONVERT(varchar(50), c.Latitude) AS latitude,
  RTRIM(c.OpsHarga) AS ops_harga,
  c.TermOfPayment AS term_of_payment,
  RTRIM(c.Active) AS active
FROM dbo.Customer c
WHERE 1=1
  $areaFilter
  AND EXISTS (
    SELECT 1
    FROM dbo.Plafon pl
    WHERE RTRIM(pl.KodeCustomer) = RTRIM(c.Kode)
      $plafonPrincipalFilter
      $plafonSalesFilter
  )
  $activeFilterCustomer
ORDER BY c.Kode
"@

Invoke-Export "principals" @"
SELECT
  RTRIM(p.Kode) AS kode,
  RTRIM(p.Nama) AS nama,
  RTRIM(p.Alamat) AS alamat,
  RTRIM(p.Telpon) AS telepon,
  RTRIM(p.NPWP) AS npwp,
  RTRIM(p.ContactPerson) AS pic,
  RTRIM(p.Active) AS active
FROM dbo.Principle p
WHERE 1=1
  $principalFilter
  $activeFilterPrincipal
ORDER BY p.Kode
"@

Invoke-Export "sales" @"
SELECT
  RTRIM(s.Kode) AS kode,
  RTRIM(s.Nama) AS nama,
  RTRIM(s.KodePrinciple) AS kode_principal,
  RTRIM(s.NamaPrinciple) AS nama_principal,
  RTRIM(s.Telpon) AS telepon,
  RTRIM(s.Active) AS active
FROM dbo.Sales s
WHERE 1=1
  $salesPrincipalFilter
  $salesFilter
  $activeFilterSales
ORDER BY s.Kode
"@

Invoke-Export "plafon" @"
SELECT
  RTRIM(pl.KodeCustomer) AS kode_customer,
  RTRIM(pl.KodePrinciple) AS kode_principal,
  RTRIM(pl.KodeSales) AS kode_sales,
  CONVERT(float, pl.Plafon) AS limit_bon,
  CONVERT(float, pl.Term) AS term,
  RTRIM(pl.Lock1) AS lock_order,
  RTRIM(c.KodeArea) AS kode_area,
  RTRIM(c.NamaArea) AS nama_area
FROM dbo.Plafon pl
INNER JOIN dbo.Customer c ON RTRIM(c.Kode) = RTRIM(pl.KodeCustomer)
INNER JOIN dbo.Principle p ON RTRIM(p.Kode) = RTRIM(pl.KodePrinciple)
LEFT JOIN dbo.Sales s ON RTRIM(s.Kode) = RTRIM(pl.KodeSales)
WHERE 1=1
  $plafonAreaFilter
  $plafonPrincipalFilter
  $plafonSalesFilter
  $activeFilterCustomer
  $activeFilterPrincipal
  AND (RTRIM(ISNULL(pl.KodeSales, '')) = '' OR s.Kode IS NOT NULL)
  AND (RTRIM(ISNULL(pl.KodeSales, '')) = '' OR ISNULL(s.Active, '1') = '1')
ORDER BY pl.KodeCustomer, pl.KodePrinciple, pl.KodeSales
"@

Invoke-Export "products" @"
SELECT
  RTRIM(st.Kode) AS kode_sku,
  RTRIM(st.Nama) AS nama,
  RTRIM(st.Principle) AS kode_principal,
  RTRIM(st.Satuan) AS satuan,
  CONVERT(float, st.PerUnit) AS per_unit,
  RTRIM(st.NamaUnit) AS nama_unit,
  CONVERT(float, st.HargaAsli) AS harga_beli,
  CONVERT(float, st.HargaA) AS harga_a,
  CONVERT(float, st.HargaB) AS harga_b,
  CONVERT(float, st.HargaC) AS harga_c,
  CONVERT(float, st.HargaD) AS harga_d,
  CONVERT(float, st.HargaE) AS harga_e,
  RTRIM(st.MasterKode) AS master_kode,
  RTRIM(st.NasionalKode) AS nasional_kode,
  RTRIM(st.KodeDMS) AS kode_dms,
  RTRIM(st.Active) AS active
FROM dbo.STOK st
WHERE 1=1
  $productPrincipalFilter
  $activeFilterProduct
ORDER BY st.Kode
"@

$metadata = [ordered]@{
  scope_name = $scopeName
  source_server = $Server
  source_database = $Database
  id_cabang = $config.branch.id_cabang
  kode_cabang = $config.branch.kode_cabang
  area_codes = $config.branch.area_codes
  id_perusahaan = $config.company.id_perusahaan
  kode_perusahaan = $config.company.kode_perusahaan
  principal_codes = $config.company.principal_codes
  sales_codes = $config.sales_codes
  include_inactive = $config.include_inactive
  exported_at = (Get-Date).ToString("s")
}
$metadata | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -Path (Join-Path $outputDir "metadata.json")

$connection.Close()
Write-Output "Export selesai: $outputDir"
