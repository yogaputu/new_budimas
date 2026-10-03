<?php

declare(strict_types=1);

$outputDir = $argv[1] ?? '/tmp';
$outputDir = rtrim($outputDir, DIRECTORY_SEPARATOR);

$conn = sqlsrv_connect('192.168.1.8,1433', [
    'Database' => 'DIST',
    'UID' => 'sa',
    'PWD' => 'Budimas6789',
    'Encrypt' => false,
    'TrustServerCertificate' => true,
    'ReturnDatesAsStrings' => true,
    'CharacterSet' => 'UTF-8',
    'LoginTimeout' => 15,
]);

if (!$conn) {
    fwrite(STDERR, print_r(sqlsrv_errors(SQLSRV_ERR_ERRORS), true));
    exit(1);
}

function exportCsv($conn, string $path, string $sql, array $headers): int
{
    $stmt = sqlsrv_query($conn, $sql, [], ['QueryTimeout' => 120]);
    if (!$stmt) {
        fwrite(STDERR, print_r(sqlsrv_errors(SQLSRV_ERR_ERRORS), true));
        exit(1);
    }

    $fh = fopen($path, 'wb');
    if (!$fh) {
        fwrite(STDERR, "Cannot open output file: {$path}\n");
        exit(1);
    }

    fputcsv($fh, $headers);
    $count = 0;
    while ($row = sqlsrv_fetch_array($stmt, SQLSRV_FETCH_ASSOC)) {
        $line = [];
        foreach ($headers as $header) {
            $value = $row[$header] ?? null;
            $line[] = $value === null ? '' : $value;
        }
        fputcsv($fh, $line);
        $count++;
    }
    fclose($fh);
    sqlsrv_free_stmt($stmt);

    return $count;
}

$rakHeaders = [
    'source_id',
    'gudang',
    'rak',
    'level',
    'kolom',
    'nomor_urut',
    'kode_rak',
    'type_rak',
    'kode_barang',
    'nama_barang',
    'qty_karton',
    'qty_pieces',
    'expired_date',
    'batch',
    'status_rak',
    'active',
    'created_at',
    'updated_at',
];

$kartuHeaders = [
    'source_id',
    'nota',
    'tanggal',
    'no_reff',
    'keterangan',
    'jenis_transaksi',
    'kode_rak',
    'kode_barang',
    'nama_barang',
    'user_add',
    'urut_tanggal',
    'harga',
    'ct',
    'pc',
    'per_unit',
    'ed',
    'no_urut_header',
    'no_urut_detail',
    'masuk',
    'keluar',
    'principle',
    'batch_number',
];

$rakSql = <<<SQL
SELECT
    Id AS source_id,
    Gudang AS gudang,
    Rak AS rak,
    [Level] AS [level],
    Kolom AS kolom,
    NomorUrut AS nomor_urut,
    LTRIM(RTRIM(KodeRak)) AS kode_rak,
    LTRIM(RTRIM(TypeRak)) AS type_rak,
    NULLIF(LTRIM(RTRIM(KodeBarang)), '') AS kode_barang,
    NULLIF(LTRIM(RTRIM(NamaBarang)), '') AS nama_barang,
    QtyKarton AS qty_karton,
    QtyPieces AS qty_pieces,
    CONVERT(varchar(10), ExpiredDate, 23) AS expired_date,
    NULLIF(LTRIM(RTRIM(Batch)), '') AS batch,
    LTRIM(RTRIM(StatusRak)) AS status_rak,
    LTRIM(RTRIM(Active)) AS active,
    CONVERT(varchar(23), CreatedAt, 121) AS created_at,
    CONVERT(varchar(23), UpdatedAt, 121) AS updated_at
FROM dbo.WMSRak
ORDER BY Id
SQL;

$kartuSql = <<<SQL
SELECT
    ID AS source_id,
    NULLIF(LTRIM(RTRIM(Nota)), '') AS nota,
    CONVERT(varchar(10), Tanggal, 23) AS tanggal,
    NULLIF(LTRIM(RTRIM(NoReff)), '') AS no_reff,
    NULLIF(LTRIM(RTRIM(Keterangan)), '') AS keterangan,
    NULLIF(LTRIM(RTRIM(JenisTransaksi)), '') AS jenis_transaksi,
    NULLIF(LTRIM(RTRIM(KodeRak)), '') AS kode_rak,
    NULLIF(LTRIM(RTRIM(KodeBarang)), '') AS kode_barang,
    NULLIF(LTRIM(RTRIM(NamaBarang)), '') AS nama_barang,
    NULLIF(LTRIM(RTRIM(UserAdd)), '') AS user_add,
    CONVERT(varchar(23), UrutTanggal, 121) AS urut_tanggal,
    Harga AS harga,
    CT AS ct,
    PC AS pc,
    PerUnit AS per_unit,
    CONVERT(varchar(10), ED, 23) AS ed,
    NoUrutHeader AS no_urut_header,
    NoUrutDetail AS no_urut_detail,
    Masuk AS masuk,
    Keluar AS keluar,
    NULLIF(LTRIM(RTRIM(Principle)), '') AS principle,
    NULLIF(LTRIM(RTRIM(BatchNumber)), '') AS batch_number
FROM dbo.WMSKartuStok
ORDER BY ID
SQL;

$rakCount = exportCsv($conn, "{$outputDir}/mssql_wms_rak.csv", $rakSql, $rakHeaders);
$kartuCount = exportCsv($conn, "{$outputDir}/mssql_wms_kartu_stok.csv", $kartuSql, $kartuHeaders);
sqlsrv_close($conn);

echo "mssql_wms_rak={$rakCount}\n";
echo "mssql_wms_kartu_stok={$kartuCount}\n";

