-- Core WMS tables for rack-level inventory, picking, putaway, loading,
-- quarantine, transfer, and scan/stock ledger.

CREATE TABLE IF NOT EXISTS wms_stock_rak (
    id BIGSERIAL PRIMARY KEY,
    id_cabang INTEGER,
    id_produk BIGINT,
    kode_barang VARCHAR(80),
    nama_barang VARCHAR(180),
    kode_rak VARCHAR(80) NOT NULL DEFAULT 'RAK-DEFAULT',
    shelf_type VARCHAR(40) NOT NULL DEFAULT 'Tetap',
    qty_pcs INTEGER NOT NULL DEFAULT 0,
    qty_karton INTEGER NOT NULL DEFAULT 0,
    batch_number VARCHAR(80),
    expired_date DATE,
    status VARCHAR(40) NOT NULL DEFAULT 'READY',
    source_type VARCHAR(80),
    source_id VARCHAR(120),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wms_stock_ledger (
    id BIGSERIAL PRIMARY KEY,
    jenis_transaksi VARCHAR(40) NOT NULL,
    reference_no VARCHAR(120),
    id_cabang INTEGER,
    id_produk BIGINT,
    kode_barang VARCHAR(80),
    nama_barang VARCHAR(180),
    kode_rak VARCHAR(80),
    batch_number VARCHAR(80),
    expired_date DATE,
    masuk INTEGER NOT NULL DEFAULT 0,
    keluar INTEGER NOT NULL DEFAULT 0,
    saldo INTEGER NOT NULL DEFAULT 0,
    user_id INTEGER,
    keterangan TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wms_picking_task (
    id BIGSERIAL PRIMARY KEY,
    id_sales_order INTEGER,
    no_order VARCHAR(120),
    no_faktur VARCHAR(120),
    id_cabang INTEGER,
    status VARCHAR(40) NOT NULL DEFAULT 'DRAFT',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wms_picking_task_detail (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT REFERENCES wms_picking_task(id) ON DELETE CASCADE,
    id_sales_order_detail INTEGER,
    id_produk BIGINT,
    kode_barang VARCHAR(80),
    nama_barang VARCHAR(180),
    kode_rak VARCHAR(80),
    batch_number VARCHAR(80),
    expired_date DATE,
    required_quantity INTEGER NOT NULL DEFAULT 0,
    picked_quantity INTEGER NOT NULL DEFAULT 0,
    status_draft VARCHAR(40) NOT NULL DEFAULT 'READY',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wms_putaway_task (
    id BIGSERIAL PRIMARY KEY,
    id_purchase_transaksi INTEGER,
    no_transaksi VARCHAR(120),
    status VARCHAR(40) NOT NULL DEFAULT 'DRAFT',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wms_putaway_task_detail (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT REFERENCES wms_putaway_task(id) ON DELETE CASCADE,
    id_purchase_transaksi_detail INTEGER,
    id_produk BIGINT,
    kode_barang VARCHAR(80),
    nama_barang VARCHAR(180),
    qty_pcs INTEGER NOT NULL DEFAULT 0,
    processed_qty INTEGER NOT NULL DEFAULT 0,
    per_unit INTEGER NOT NULL DEFAULT 1,
    batch_number VARCHAR(80),
    expired_date DATE,
    status VARCHAR(40) NOT NULL DEFAULT 'READY',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wms_loading_manifest (
    id BIGSERIAL PRIMARY KEY,
    no_manifest VARCHAR(120) UNIQUE,
    id_driver INTEGER,
    driver_name VARCHAR(120),
    status VARCHAR(40) NOT NULL DEFAULT 'READY',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wms_loading_manifest_detail (
    id BIGSERIAL PRIMARY KEY,
    manifest_id BIGINT REFERENCES wms_loading_manifest(id) ON DELETE CASCADE,
    picking_task_detail_id BIGINT,
    no_faktur VARCHAR(120),
    id_produk BIGINT,
    kode_barang VARCHAR(80),
    nama_barang VARCHAR(180),
    qty_pcs INTEGER NOT NULL DEFAULT 0,
    kode_rak VARCHAR(80),
    batch_number VARCHAR(80),
    expired_date DATE,
    status VARCHAR(40) NOT NULL DEFAULT 'READY',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wms_quarantine (
    id BIGSERIAL PRIMARY KEY,
    no_manifest VARCHAR(120),
    reference_no VARCHAR(120),
    id_produk BIGINT,
    kode_barang VARCHAR(80),
    nama_barang VARCHAR(180),
    qty_pcs INTEGER NOT NULL DEFAULT 0,
    kode_rak VARCHAR(80),
    reason TEXT,
    status VARCHAR(40) NOT NULL DEFAULT 'OPEN',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wms_scan_log (
    id BIGSERIAL PRIMARY KEY,
    scan_type VARCHAR(60) NOT NULL,
    reference_no VARCHAR(120),
    id_produk BIGINT,
    kode_barang VARCHAR(80),
    kode_rak VARCHAR(80),
    qty_pcs INTEGER NOT NULL DEFAULT 0,
    payload JSONB,
    user_id INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wms_stock_rak_product ON wms_stock_rak(id_cabang, id_produk, kode_barang);
CREATE INDEX IF NOT EXISTS idx_wms_stock_rak_location ON wms_stock_rak(kode_rak, status);

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
updated AS (
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

CREATE UNIQUE INDEX IF NOT EXISTS ux_wms_stock_rak_identity
ON wms_stock_rak (
    COALESCE(id_cabang, 0),
    id_produk,
    kode_rak,
    COALESCE(batch_number, ''),
    COALESCE(expired_date, DATE '1900-01-01')
);

CREATE INDEX IF NOT EXISTS idx_wms_ledger_ref ON wms_stock_ledger(reference_no, jenis_transaksi);
CREATE UNIQUE INDEX IF NOT EXISTS ux_wms_picking_task_sales ON wms_picking_task(id_sales_order);
CREATE UNIQUE INDEX IF NOT EXISTS ux_wms_picking_detail_task_order ON wms_picking_task_detail(task_id, id_sales_order_detail);
CREATE UNIQUE INDEX IF NOT EXISTS ux_wms_putaway_task_transaksi ON wms_putaway_task(id_purchase_transaksi);
CREATE UNIQUE INDEX IF NOT EXISTS ux_wms_putaway_detail_task_transaksi ON wms_putaway_task_detail(task_id, id_purchase_transaksi_detail);
