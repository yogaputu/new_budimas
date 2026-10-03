-- Import WMSRak and WMSKartuStok from SQL Server DIST into PostgreSQL WMS tables.
-- Source branch/gudang is SOLO, mapped to id_cabang = 5.

CREATE TABLE IF NOT EXISTS legacy_dist_wms_rak (
    source_id BIGINT PRIMARY KEY,
    gudang SMALLINT,
    rak SMALLINT,
    level SMALLINT,
    kolom SMALLINT,
    nomor_urut SMALLINT,
    kode_rak TEXT,
    type_rak TEXT,
    kode_barang TEXT,
    nama_barang TEXT,
    qty_karton NUMERIC,
    qty_pieces NUMERIC,
    expired_date DATE,
    batch TEXT,
    status_rak TEXT,
    active TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS legacy_dist_wms_kartu_stok (
    source_id INTEGER PRIMARY KEY,
    nota TEXT,
    tanggal DATE,
    no_reff TEXT,
    keterangan TEXT,
    jenis_transaksi TEXT,
    kode_rak TEXT,
    kode_barang TEXT,
    nama_barang TEXT,
    user_add TEXT,
    urut_tanggal TIMESTAMP,
    harga NUMERIC,
    ct NUMERIC,
    pc NUMERIC,
    per_unit NUMERIC,
    ed DATE,
    no_urut_header INTEGER,
    no_urut_detail INTEGER,
    masuk NUMERIC,
    keluar NUMERIC,
    principle TEXT,
    batch_number TEXT,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_legacy_wms_rak_code ON legacy_dist_wms_rak(kode_rak, kode_barang);
CREATE INDEX IF NOT EXISTS idx_legacy_wms_kartu_code ON legacy_dist_wms_kartu_stok(kode_rak, kode_barang, tanggal);

CREATE TABLE IF NOT EXISTS wms_stock_rak (
    id BIGSERIAL PRIMARY KEY,
    id_cabang INTEGER,
    id_produk BIGINT,
    kode_barang VARCHAR(80),
    nama_barang VARCHAR(255),
    kode_rak VARCHAR(80) NOT NULL,
    shelf_type VARCHAR(40) NOT NULL DEFAULT 'Tetap',
    qty_pcs INTEGER NOT NULL DEFAULT 0,
    qty_karton INTEGER NOT NULL DEFAULT 0,
    batch_number VARCHAR(120),
    expired_date DATE,
    status VARCHAR(30) NOT NULL DEFAULT 'READY',
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
    nama_barang VARCHAR(255),
    kode_rak VARCHAR(80),
    batch_number VARCHAR(120),
    expired_date DATE,
    masuk INTEGER NOT NULL DEFAULT 0,
    keluar INTEGER NOT NULL DEFAULT 0,
    saldo INTEGER NOT NULL DEFAULT 0,
    user_id INTEGER,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_wms_stock_rak_identity
ON wms_stock_rak (
    COALESCE(id_cabang, 0),
    id_produk,
    kode_rak,
    COALESCE(batch_number, ''),
    COALESCE(expired_date, DATE '1900-01-01')
);

CREATE INDEX IF NOT EXISTS idx_wms_stock_rak_product ON wms_stock_rak(id_cabang, id_produk, kode_barang);
CREATE INDEX IF NOT EXISTS idx_wms_stock_rak_location ON wms_stock_rak(kode_rak, status);
CREATE INDEX IF NOT EXISTS idx_wms_ledger_ref ON wms_stock_ledger(reference_no, jenis_transaksi);

TRUNCATE legacy_dist_wms_rak;
TRUNCATE legacy_dist_wms_kartu_stok;

-- CSV load happens between this file's setup section and apply section:
-- \copy legacy_dist_wms_rak (...) FROM '/tmp/mssql_wms_rak.csv' WITH (FORMAT csv, HEADER true, NULL '');
-- \copy legacy_dist_wms_kartu_stok (...) FROM '/tmp/mssql_wms_kartu_stok.csv' WITH (FORMAT csv, HEADER true, NULL '');

