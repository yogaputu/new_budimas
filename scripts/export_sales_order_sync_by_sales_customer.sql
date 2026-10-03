COPY (
WITH h_dedup AS (
    SELECT *
    FROM (
        SELECT
            h.*,
            row_number() OVER (
                PARTITION BY btrim(h.nota)
                ORDER BY h.source_priority, h.staging_id
            ) AS rn
        FROM legacy_transaction_import_server.hjualsm h
        WHERE btrim(coalesce(h.nota, '')) <> ''
    ) x
    WHERE rn = 1
)
SELECT
    h.source_system,
    h.source_priority,
    coalesce(per.kode, '') AS kode_perusahaan,
    coalesce(per.nama, '') AS nama_perusahaan,
    coalesce(cb.kode, '') AS kode_cabang,
    coalesce(cb.nama, '') AS nama_cabang,
    btrim(coalesce(so.nama_sales, '')) AS nama_sales,
    btrim(coalesce(h.kodesales, '')) AS kode_sales_legacy,
    btrim(coalesce(h.kodecustomer, '')) AS kode_customer_legacy,
    btrim(coalesce(h.namacustomer, so.pic_customer, '')) AS nama_customer,
    count(*) AS jumlah_order,
    min(so.tanggal_order) AS tanggal_order_pertama,
    max(so.tanggal_order) AS tanggal_order_terakhir,
    sum(coalesce(so.total_order, 0)) AS total_order,
    min(so.no_order) AS contoh_no_order
FROM sales_order so
JOIN h_dedup h
  ON btrim(h.nota) = btrim(so.no_order)
LEFT JOIN cabang cb
  ON cb.id = so.id_cabang
LEFT JOIN perusahaan per
  ON per.id = cb.id_perusahaan
WHERE btrim(coalesce(so.nama_sales, '')) <> ''
GROUP BY
    h.source_system,
    h.source_priority,
    per.kode,
    per.nama,
    cb.kode,
    cb.nama,
    btrim(coalesce(so.nama_sales, '')),
    btrim(coalesce(h.kodesales, '')),
    btrim(coalesce(h.kodecustomer, '')),
    btrim(coalesce(h.namacustomer, so.pic_customer, ''))
ORDER BY
    nama_perusahaan,
    nama_cabang,
    nama_sales,
    nama_customer,
    source_priority
) TO '/tmp/sales_order_sync_by_sales_customer_20260719.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');
