-- Apply already-loaded legacy_dist_wms_rak and legacy_dist_wms_kartu_stok into active WMS tables.

WITH product_map AS (
    SELECT DISTINCT ON (src.source_id)
        src.source_id,
        p.id AS id_produk,
        GREATEST(COALESCE(NULLIF(p.isiperkarton, 0), NULLIF(p.isiperbox, 0), 1), 1)::integer AS per_unit
    FROM legacy_dist_wms_rak src
    LEFT JOIN produk p
      ON LOWER(COALESCE(NULLIF(p.kode_sku, ''), NULLIF(p.kode_ean, ''), p.id::text)) = LOWER(src.kode_barang)
      OR LOWER(COALESCE(NULLIF(p.kode_ean, ''), NULLIF(p.kode_sku, ''), p.id::text)) = LOWER(src.kode_barang)
    ORDER BY src.source_id, p.id
),
rak_source AS (
    SELECT
        5::integer AS id_cabang,
        pm.id_produk,
        src.kode_barang,
        COALESCE(src.nama_barang, p.nama, src.kode_barang, src.kode_rak) AS nama_barang,
        src.kode_rak,
        COALESCE(src.type_rak, 'Tetap') AS shelf_type,
        (
            COALESCE(ROUND(src.qty_karton), 0)::integer * GREATEST(COALESCE(pm.per_unit, 1), 1)
            + COALESCE(ROUND(src.qty_pieces), 0)::integer
        ) AS qty_pcs,
        COALESCE(ROUND(src.qty_karton), 0)::integer AS qty_karton,
        NULLIF(src.batch, '') AS batch_number,
        CASE WHEN src.expired_date <= DATE '1900-01-02' THEN NULL ELSE src.expired_date END AS expired_date,
        CASE
            WHEN COALESCE(src.active, '') <> 'Yes' THEN 'INACTIVE'
            WHEN COALESCE(src.status_rak, '') ILIKE 'Kosong' THEN 'EMPTY'
            WHEN (
                COALESCE(ROUND(src.qty_karton), 0)::integer * GREATEST(COALESCE(pm.per_unit, 1), 1)
                + COALESCE(ROUND(src.qty_pieces), 0)::integer
            ) <= 0 THEN 'EMPTY'
            WHEN COALESCE(ROUND(src.qty_karton), 0)::integer <= 2 THEN 'LOW'
            ELSE 'READY'
        END AS status,
        'mssql_wmsrak' AS source_type,
        src.source_id::text AS source_id,
        COALESCE(src.created_at, NOW()::timestamp) AS created_at,
        COALESCE(src.updated_at, NOW()::timestamp) AS updated_at
    FROM legacy_dist_wms_rak src
    LEFT JOIN product_map pm ON pm.source_id = src.source_id
    LEFT JOIN produk p ON p.id = pm.id_produk
    WHERE src.kode_rak IS NOT NULL
),
cleanup AS (
    DELETE FROM wms_stock_rak
    WHERE source_type IN ('erp_stok', 'mssql_wmsrak', 'mssql_wmskartustok_balance')
    RETURNING 1
)
INSERT INTO wms_stock_rak (
    id_cabang, id_produk, kode_barang, nama_barang, kode_rak, shelf_type,
    qty_pcs, qty_karton, batch_number, expired_date, status, source_type, source_id,
    created_at, updated_at
)
SELECT
    id_cabang, id_produk, kode_barang, nama_barang, kode_rak, shelf_type,
    qty_pcs, qty_karton, batch_number, expired_date, status, source_type, source_id,
    created_at, updated_at
FROM rak_source;

DELETE FROM wms_stock_ledger
WHERE keterangan LIKE 'MSSQL WMSKartuStok%';

WITH ledger_source AS (
    SELECT
        src.*,
        p.id AS id_produk,
        GREATEST(COALESCE(NULLIF(p.isiperkarton, 0), NULLIF(p.isiperbox, 0), ROUND(NULLIF(src.per_unit, 0)), 1), 1)::integer AS resolved_per_unit
    FROM legacy_dist_wms_kartu_stok src
    LEFT JOIN LATERAL (
        SELECT p.*
        FROM produk p
        WHERE LOWER(COALESCE(NULLIF(p.kode_sku, ''), NULLIF(p.kode_ean, ''), p.id::text)) = LOWER(src.kode_barang)
           OR LOWER(COALESCE(NULLIF(p.kode_ean, ''), NULLIF(p.kode_sku, ''), p.id::text)) = LOWER(src.kode_barang)
        ORDER BY p.id
        LIMIT 1
    ) p ON TRUE
),
ledger_running AS (
    SELECT
        *,
        SUM(COALESCE(ROUND(masuk), 0)::integer - COALESCE(ROUND(keluar), 0)::integer)
            OVER (
                PARTITION BY kode_rak, kode_barang, COALESCE(batch_number, ''), COALESCE(CASE WHEN ed <= DATE '1900-01-02' THEN NULL ELSE ed END, DATE '1900-01-01')
                ORDER BY COALESCE(urut_tanggal, tanggal::timestamp, NOW()::timestamp), source_id
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            )::integer AS running_saldo
    FROM ledger_source
)
INSERT INTO wms_stock_ledger (
    jenis_transaksi, reference_no, id_cabang, id_produk, kode_barang, nama_barang,
    kode_rak, batch_number, expired_date, masuk, keluar, saldo, user_id, keterangan, created_at
)
SELECT
    COALESCE(NULLIF(jenis_transaksi, ''), 'WMS') AS jenis_transaksi,
    nota AS reference_no,
    5 AS id_cabang,
    id_produk,
    kode_barang,
    nama_barang,
    kode_rak,
    NULLIF(batch_number, '') AS batch_number,
    CASE WHEN ed <= DATE '1900-01-02' THEN NULL ELSE ed END AS expired_date,
    COALESCE(ROUND(masuk), 0)::integer AS masuk,
    COALESCE(ROUND(keluar), 0)::integer AS keluar,
    running_saldo AS saldo,
    NULL AS user_id,
    'MSSQL WMSKartuStok ID:' || source_id::text AS note,
    COALESCE(urut_tanggal, tanggal::timestamp, NOW()::timestamp) AS created_at
FROM ledger_running
WHERE kode_rak IS NOT NULL
  AND kode_barang IS NOT NULL;

WITH balance AS (
    SELECT
        5::integer AS id_cabang,
        src.kode_rak,
        src.kode_barang,
        MAX(src.nama_barang) AS nama_barang,
        NULLIF(src.batch_number, '') AS batch_number,
        CASE WHEN src.ed <= DATE '1900-01-02' THEN NULL ELSE src.ed END AS expired_date,
        SUM(COALESCE(ROUND(src.masuk), 0)::integer - COALESCE(ROUND(src.keluar), 0)::integer)::integer AS qty_pcs,
        MAX(src.resolved_per_unit)::integer AS per_unit,
        MAX(src.id_produk) AS id_produk,
        MAX(COALESCE(src.urut_tanggal, src.tanggal::timestamp, NOW()::timestamp)) AS updated_at
    FROM (
        SELECT
            k.*,
            p.id AS id_produk,
            GREATEST(COALESCE(NULLIF(p.isiperkarton, 0), NULLIF(p.isiperbox, 0), ROUND(NULLIF(k.per_unit, 0)), 1), 1)::integer AS resolved_per_unit
        FROM legacy_dist_wms_kartu_stok k
        LEFT JOIN LATERAL (
            SELECT p.*
            FROM produk p
            WHERE LOWER(COALESCE(NULLIF(p.kode_sku, ''), NULLIF(p.kode_ean, ''), p.id::text)) = LOWER(k.kode_barang)
               OR LOWER(COALESCE(NULLIF(p.kode_ean, ''), NULLIF(p.kode_sku, ''), p.id::text)) = LOWER(k.kode_barang)
            ORDER BY p.id
            LIMIT 1
        ) p ON TRUE
    ) src
    WHERE src.kode_rak IS NOT NULL
      AND src.kode_barang IS NOT NULL
    GROUP BY src.kode_rak, src.kode_barang, NULLIF(src.batch_number, ''), CASE WHEN src.ed <= DATE '1900-01-02' THEN NULL ELSE src.ed END
),
updated_master AS (
    UPDATE wms_stock_rak r
    SET
        qty_pcs = GREATEST(balance.qty_pcs, 0),
        qty_karton = FLOOR(GREATEST(balance.qty_pcs, 0)::numeric / GREATEST(balance.per_unit, 1))::integer,
        status = CASE
            WHEN GREATEST(balance.qty_pcs, 0) <= 0 THEN 'EMPTY'
            WHEN FLOOR(GREATEST(balance.qty_pcs, 0)::numeric / GREATEST(balance.per_unit, 1)) <= 2 THEN 'LOW'
            ELSE 'READY'
        END,
        batch_number = balance.batch_number,
        expired_date = balance.expired_date,
        updated_at = balance.updated_at
    FROM balance
    WHERE r.source_type = 'mssql_wmsrak'
      AND r.kode_rak = balance.kode_rak
      AND COALESCE(r.kode_barang, '') = COALESCE(balance.kode_barang, '')
      AND COALESCE(r.batch_number, '') = COALESCE(balance.batch_number, '')
      AND COALESCE(r.expired_date, DATE '1900-01-01') = COALESCE(balance.expired_date, DATE '1900-01-01')
    RETURNING balance.kode_rak, balance.kode_barang, balance.batch_number, balance.expired_date
)
INSERT INTO wms_stock_rak (
    id_cabang, id_produk, kode_barang, nama_barang, kode_rak, shelf_type,
    qty_pcs, qty_karton, batch_number, expired_date, status, source_type, source_id,
    created_at, updated_at
)
SELECT
    balance.id_cabang,
    balance.id_produk,
    balance.kode_barang,
    balance.nama_barang,
    balance.kode_rak,
    'Titipan' AS shelf_type,
    GREATEST(balance.qty_pcs, 0) AS qty_pcs,
    FLOOR(GREATEST(balance.qty_pcs, 0)::numeric / GREATEST(balance.per_unit, 1))::integer AS qty_karton,
    balance.batch_number,
    balance.expired_date,
    CASE
        WHEN GREATEST(balance.qty_pcs, 0) <= 0 THEN 'EMPTY'
        WHEN FLOOR(GREATEST(balance.qty_pcs, 0)::numeric / GREATEST(balance.per_unit, 1)) <= 2 THEN 'LOW'
        ELSE 'READY'
    END AS status,
    'mssql_wmskartustok_balance' AS source_type,
    balance.kode_rak || ':' || balance.kode_barang || ':' || COALESCE(balance.batch_number, '') || ':' || COALESCE(balance.expired_date::text, '') AS source_id,
    balance.updated_at,
    balance.updated_at
FROM balance
WHERE NOT EXISTS (
    SELECT 1
    FROM updated_master u
    WHERE u.kode_rak = balance.kode_rak
      AND COALESCE(u.kode_barang, '') = COALESCE(balance.kode_barang, '')
      AND COALESCE(u.batch_number, '') = COALESCE(balance.batch_number, '')
      AND COALESCE(u.expired_date, DATE '1900-01-01') = COALESCE(balance.expired_date, DATE '1900-01-01')
);

WITH grouped AS (
    SELECT
        MIN(id) AS keep_id,
        ARRAY_AGG(id) AS row_ids,
        SUM(qty_pcs)::integer AS qty_pcs,
        SUM(qty_karton)::integer AS qty_karton
    FROM wms_stock_rak
    GROUP BY
        COALESCE(id_cabang, 0),
        id_produk,
        kode_rak,
        COALESCE(batch_number, ''),
        COALESCE(expired_date, DATE '1900-01-01')
    HAVING COUNT(*) > 1
),
refresh_keep AS (
    UPDATE wms_stock_rak r
    SET
        qty_pcs = grouped.qty_pcs,
        qty_karton = grouped.qty_karton,
        status = CASE
            WHEN grouped.qty_pcs <= 0 THEN 'EMPTY'
            WHEN grouped.qty_karton <= 2 THEN 'LOW'
            ELSE 'READY'
        END,
        updated_at = NOW()
    FROM grouped
    WHERE r.id = grouped.keep_id
    RETURNING r.id
)
DELETE FROM wms_stock_rak r
USING grouped
WHERE r.id = ANY(grouped.row_ids)
  AND r.id <> grouped.keep_id;

ANALYZE legacy_dist_wms_rak;
ANALYZE legacy_dist_wms_kartu_stok;
ANALYZE wms_stock_rak;
ANALYZE wms_stock_ledger;
