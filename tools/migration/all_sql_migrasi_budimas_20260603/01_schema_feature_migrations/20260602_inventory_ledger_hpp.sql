CREATE TABLE IF NOT EXISTS inventory_ledger (
    id BIGSERIAL PRIMARY KEY,
    movement_date DATE NOT NULL,
    id_produk INTEGER NOT NULL,
    id_cabang INTEGER NULL,
    id_perusahaan INTEGER NULL,
    id_principal INTEGER NULL,
    source_module VARCHAR(80) NULL,
    source_type VARCHAR(60) NOT NULL,
    source_id VARCHAR(80) NULL,
    source_detail_id VARCHAR(80) NULL,
    direction VARCHAR(12) NOT NULL CHECK (direction IN ('in', 'out', 'adjust')),
    qty NUMERIC(18, 4) NOT NULL DEFAULT 0,
    unit_cost NUMERIC(18, 4) NOT NULL DEFAULT 0,
    total_cost NUMERIC(18, 2) NOT NULL DEFAULT 0,
    hpp_method VARCHAR(30) NULL,
    sales_order_id INTEGER NULL,
    faktur_id INTEGER NULL,
    purchase_order_id INTEGER NULL,
    purchase_transaksi_id INTEGER NULL,
    notes TEXT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    created_by INTEGER NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_inventory_ledger_source_detail
    ON inventory_ledger (source_type, source_id, source_detail_id, direction);

CREATE INDEX IF NOT EXISTS idx_inventory_ledger_period
    ON inventory_ledger (movement_date, direction);

CREATE INDEX IF NOT EXISTS idx_inventory_ledger_product_scope
    ON inventory_ledger (id_produk, id_cabang, id_perusahaan, movement_date);

CREATE INDEX IF NOT EXISTS idx_inventory_ledger_sales_order
    ON inventory_ledger (sales_order_id);

COMMENT ON TABLE inventory_ledger IS 'Kartu stok bernilai untuk HPP FIFO / Moving Average. Isi saat barang masuk, keluar, adjustment, dan transaksi historis/backfill.';
COMMENT ON COLUMN inventory_ledger.direction IS 'in = stok masuk, out = stok keluar/terjual, adjust = koreksi opname/penyesuaian.';
COMMENT ON COLUMN inventory_ledger.unit_cost IS 'Harga pokok per unit terkecil pada tanggal movement.';
COMMENT ON COLUMN inventory_ledger.total_cost IS 'Nilai HPP movement. Untuk out dapat disimpan final, atau dihitung ulang laporan dari in/out.';
