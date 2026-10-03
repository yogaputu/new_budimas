-- Jalankan manual sebagai owner/superuser database.
-- File ini menggantikan semua CREATE/ALTER runtime yang sebelumnya sempat dijalankan dari Python.

ALTER TABLE sales_order
ADD COLUMN IF NOT EXISTS total_order_before_discount DOUBLE PRECISION DEFAULT 0,
ADD COLUMN IF NOT EXISTS unified_promo_nominal DOUBLE PRECISION DEFAULT 0,
ADD COLUMN IF NOT EXISTS manual_discount_type VARCHAR(20),
ADD COLUMN IF NOT EXISTS manual_discount_value DOUBLE PRECISION DEFAULT 0,
ADD COLUMN IF NOT EXISTS manual_discount_nominal DOUBLE PRECISION DEFAULT 0,
ADD COLUMN IF NOT EXISTS order_discount_total DOUBLE PRECISION DEFAULT 0,
ADD COLUMN IF NOT EXISTS order_discount_note TEXT,
ADD COLUMN IF NOT EXISTS unified_promo_snapshot TEXT;

ALTER TABLE faktur
ADD COLUMN IF NOT EXISTS total_penjualan_before_discount DOUBLE PRECISION DEFAULT 0,
ADD COLUMN IF NOT EXISTS unified_promo_nominal DOUBLE PRECISION DEFAULT 0,
ADD COLUMN IF NOT EXISTS manual_discount_type VARCHAR(20),
ADD COLUMN IF NOT EXISTS manual_discount_value DOUBLE PRECISION DEFAULT 0,
ADD COLUMN IF NOT EXISTS manual_discount_nominal DOUBLE PRECISION DEFAULT 0,
ADD COLUMN IF NOT EXISTS order_discount_total DOUBLE PRECISION DEFAULT 0,
ADD COLUMN IF NOT EXISTS order_discount_note TEXT,
ADD COLUMN IF NOT EXISTS unified_promo_snapshot TEXT;

CREATE TABLE IF NOT EXISTS payment_voucher_usage (
    id SERIAL PRIMARY KEY,
    id_setoran_customer INTEGER,
    id_sales_order INTEGER NOT NULL,
    id_faktur INTEGER,
    usage_type VARCHAR(40) NOT NULL,
    usage_id INTEGER NOT NULL,
    kode VARCHAR(100),
    nominal DOUBLE PRECISION NOT NULL DEFAULT 0,
    status INTEGER NOT NULL DEFAULT 1,
    note TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_payment_voucher_usage_active
ON payment_voucher_usage (usage_type, usage_id)
WHERE status = 1;

ALTER TABLE credit_note
ADD COLUMN IF NOT EXISTS tanggal_refund TIMESTAMP NULL,
ADD COLUMN IF NOT EXISTS nominal_refund DOUBLE PRECISION DEFAULT 0,
ADD COLUMN IF NOT EXISTS metode_refund VARCHAR(50),
ADD COLUMN IF NOT EXISTS id_rekening_perusahaan INTEGER NULL,
ADD COLUMN IF NOT EXISTS id_mutasi_acc INTEGER NULL,
ADD COLUMN IF NOT EXISTS catatan_refund TEXT,
ADD COLUMN IF NOT EXISTS user_refund INTEGER NULL;

CREATE INDEX IF NOT EXISTS idx_credit_note_refund_rekening
ON credit_note (id_rekening_perusahaan);

CREATE INDEX IF NOT EXISTS idx_credit_note_refund_accounting_entry
ON credit_note (id_mutasi_acc);

CREATE INDEX IF NOT EXISTS idx_credit_note_user_refund
ON credit_note (user_refund);

CREATE TABLE IF NOT EXISTS sales_target_monthly (
    id BIGSERIAL PRIMARY KEY,
    id_sales BIGINT NOT NULL,
    id_user BIGINT NULL,
    id_cabang BIGINT NULL,
    tahun INTEGER NOT NULL,
    bulan INTEGER NOT NULL,
    target_kunjungan INTEGER NOT NULL DEFAULT 0,
    target_omset NUMERIC(18,2) NOT NULL DEFAULT 0,
    notes TEXT NULL,
    created_by BIGINT NULL,
    updated_by BIGINT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_target_monthly_sales_period
ON sales_target_monthly (id_sales, tahun, bulan);

ALTER TABLE sales_target_monthly
ADD COLUMN IF NOT EXISTS target_kunjungan INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS produk_external_mapping (
    id SERIAL PRIMARY KEY,
    kode_external VARCHAR(120) NOT NULL,
    id_produk INTEGER NOT NULL,
    kode_sku VARCHAR(120),
    principal_code VARCHAR(80),
    source VARCHAR(80) NOT NULL DEFAULT 'sales_order_import',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP,
    UNIQUE (kode_external, source)
);

CREATE TABLE IF NOT EXISTS customer_external_mapping (
    id SERIAL PRIMARY KEY,
    kode_external VARCHAR(120) NOT NULL,
    id_customer INTEGER NOT NULL,
    kode_customer VARCHAR(120),
    source VARCHAR(80) NOT NULL DEFAULT 'sales_order_import',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP,
    UNIQUE (kode_external, source)
);

CREATE TABLE IF NOT EXISTS master_ppn (
    id SERIAL PRIMARY KEY,
    kode VARCHAR(30) UNIQUE,
    nama VARCHAR(100) NOT NULL,
    persentase DOUBLE PRECISION NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    keterangan TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP
);

INSERT INTO master_ppn (kode, nama, persentase, is_active, keterangan)
VALUES
    ('NON_PPN', 'Non PPN', 0, TRUE, 'Produk tidak dikenakan PPN'),
    ('PPN_11', 'PPN 11%', 11, TRUE, 'Tarif PPN umum 11%')
ON CONFLICT (kode) DO UPDATE
SET nama = EXCLUDED.nama,
    persentase = EXCLUDED.persentase,
    is_active = EXCLUDED.is_active,
    updated_at = NOW();

ALTER TABLE produk
ADD COLUMN IF NOT EXISTS id_ppn INTEGER;

UPDATE produk p
SET id_ppn = m.id
FROM master_ppn m
WHERE p.id_ppn IS NULL
  AND (
    (COALESCE(p.ppn, 0) <= 0 AND m.kode = 'NON_PPN')
    OR (COALESCE(p.ppn, 0) = m.persentase)
  );

CREATE TABLE IF NOT EXISTS sales_order_import_batch (
    id SERIAL PRIMARY KEY,
    import_code VARCHAR(80) NOT NULL UNIQUE,
    header_filename VARCHAR(255),
    detail_filename VARCHAR(255),
    status VARCHAR(30) NOT NULL DEFAULT 'draft',
    total_header INTEGER NOT NULL DEFAULT 0,
    total_detail INTEGER NOT NULL DEFAULT 0,
    valid_header INTEGER NOT NULL DEFAULT 0,
    valid_detail INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    processed_order_count INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMP,
    notes TEXT
);

ALTER TABLE sales_order_import_batch
ADD COLUMN IF NOT EXISTS id_cabang INTEGER,
ADD COLUMN IF NOT EXISTS id_perusahaan INTEGER,
ADD COLUMN IF NOT EXISTS id_principal INTEGER,
ADD COLUMN IF NOT EXISTS id_sales INTEGER,
ADD COLUMN IF NOT EXISTS id_customer INTEGER;

CREATE TABLE IF NOT EXISTS sales_order_import_row (
    id SERIAL PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES sales_order_import_batch(id) ON DELETE CASCADE,
    row_type VARCHAR(20) NOT NULL,
    row_number INTEGER NOT NULL,
    order_no VARCHAR(120),
    order_date DATE,
    customer_code VARCHAR(80),
    sales_code VARCHAR(80),
    product_code VARCHAR(120),
    uom_text VARCHAR(80),
    quantity NUMERIC DEFAULT 0,
    unit_price NUMERIC DEFAULT 0,
    subtotal NUMERIC DEFAULT 0,
    raw_data JSONB,
    validation_status VARCHAR(20) NOT NULL DEFAULT 'valid',
    validation_message TEXT,
    id_customer INTEGER,
    id_sales INTEGER,
    id_plafon INTEGER,
    id_produk INTEGER,
    id_principal INTEGER,
    id_sales_order INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS unified_promo_program (
    id SERIAL PRIMARY KEY,
    kode_promo VARCHAR(80) UNIQUE NOT NULL,
    nama_promo VARCHAR(180) NOT NULL,
    promo_type VARCHAR(40) NOT NULL DEFAULT 'discount',
    benefit_scope VARCHAR(40) NOT NULL DEFAULT 'invoice',
    id_cabang INTEGER NULL,
    id_perusahaan INTEGER NULL,
    id_principal INTEGER NULL,
    id_customer INTEGER NULL,
    budget_limit NUMERIC(18, 2) NOT NULL DEFAULT 0,
    budget_used NUMERIC(18, 2) NOT NULL DEFAULT 0,
    periode_mulai DATE NULL,
    periode_selesai DATE NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    keterangan TEXT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS unified_promo_rule (
    id SERIAL PRIMARY KEY,
    promo_id INTEGER NOT NULL REFERENCES unified_promo_program(id) ON DELETE CASCADE,
    nama_rule VARCHAR(180) NULL,
    target_type VARCHAR(40) NOT NULL DEFAULT 'all',
    id_produk INTEGER NULL,
    id_brand INTEGER NULL,
    id_subbrand INTEGER NULL,
    id_principal INTEGER NULL,
    id_customer INTEGER NULL,
    qty_uom VARCHAR(20) NOT NULL DEFAULT 'karton',
    min_qty NUMERIC(18, 4) NOT NULL DEFAULT 0,
    max_qty NUMERIC(18, 4) NULL,
    min_subtotal NUMERIC(18, 2) NOT NULL DEFAULT 0,
    max_subtotal NUMERIC(18, 2) NULL,
    benefit_type VARCHAR(40) NOT NULL DEFAULT 'percent',
    benefit_value NUMERIC(18, 4) NOT NULL DEFAULT 0,
    free_product_id INTEGER NULL,
    free_qty NUMERIC(18, 4) NOT NULL DEFAULT 0,
    priority INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS unified_promo_usage (
    id SERIAL PRIMARY KEY,
    promo_id INTEGER NOT NULL REFERENCES unified_promo_program(id),
    rule_id INTEGER NULL REFERENCES unified_promo_rule(id),
    id_sales_order INTEGER NULL,
    id_faktur INTEGER NULL,
    id_customer INTEGER NULL,
    id_principal INTEGER NULL,
    nominal NUMERIC(18, 2) NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'ready',
    source VARCHAR(40) NOT NULL DEFAULT 'sales_order',
    catatan TEXT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    used_at TIMESTAMP WITHOUT TIME ZONE NULL
);

CREATE TABLE IF NOT EXISTS unified_promo_customer_target (
    id SERIAL PRIMARY KEY,
    promo_id INTEGER NOT NULL REFERENCES unified_promo_program(id) ON DELETE CASCADE,
    id_customer INTEGER NOT NULL REFERENCES customer(id),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    UNIQUE (promo_id, id_customer)
);

INSERT INTO unified_promo_customer_target (promo_id, id_customer)
SELECT id, id_customer
FROM unified_promo_program
WHERE id_customer IS NOT NULL
ON CONFLICT (promo_id, id_customer) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_unified_promo_customer_target_promo
ON unified_promo_customer_target (promo_id);

CREATE INDEX IF NOT EXISTS idx_unified_promo_customer_target_customer
ON unified_promo_customer_target (id_customer);

ALTER TABLE canvas_request_detail
ADD COLUMN IF NOT EXISTS qty_uom1 DOUBLE PRECISION DEFAULT 0,
ADD COLUMN IF NOT EXISTS qty_uom2 DOUBLE PRECISION DEFAULT 0,
ADD COLUMN IF NOT EXISTS qty_uom3 DOUBLE PRECISION DEFAULT 0;

ALTER TABLE canvas_order
ADD COLUMN IF NOT EXISTS total_diskon DOUBLE PRECISION DEFAULT 0,
ADD COLUMN IF NOT EXISTS kode_customer VARCHAR(50),
ADD COLUMN IF NOT EXISTS id_kunjungan INTEGER;

ALTER TABLE canvas_order_detail
ADD COLUMN IF NOT EXISTS carton_order INTEGER DEFAULT 0;

ALTER TABLE setoran_customer
ADD COLUMN IF NOT EXISTS id_canvas_order INTEGER;

CREATE TABLE IF NOT EXISTS canvas_stock_return (
    id SERIAL PRIMARY KEY,
    id_sales INTEGER NOT NULL,
    id_user INTEGER,
    id_cabang INTEGER,
    tanggal_return DATE DEFAULT CURRENT_DATE,
    total_qty DOUBLE PRECISION DEFAULT 0,
    status INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS canvas_stock_return_detail (
    id SERIAL PRIMARY KEY,
    id_return INTEGER REFERENCES canvas_stock_return(id),
    id_produk INTEGER NOT NULL,
    qty_return DOUBLE PRECISION DEFAULT 0,
    qty_uom1 DOUBLE PRECISION DEFAULT 0,
    qty_uom2 DOUBLE PRECISION DEFAULT 0,
    qty_uom3 DOUBLE PRECISION DEFAULT 0,
    stock_canvas_before DOUBLE PRECISION DEFAULT 0,
    stock_canvas_after DOUBLE PRECISION DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mobile_visit_reason (
    id BIGSERIAL PRIMARY KEY,
    id_kunjungan BIGINT NULL,
    id_plafon BIGINT NULL,
    kode_customer VARCHAR(100) NOT NULL,
    nama_customer VARCHAR(255) NULL,
    alasan_no_order TEXT NOT NULL,
    id_user BIGINT NULL,
    id_sales BIGINT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mobile_visit_reason_kode_customer
ON mobile_visit_reason (kode_customer);

CREATE INDEX IF NOT EXISTS idx_mobile_visit_reason_id_kunjungan
ON mobile_visit_reason (id_kunjungan);

CREATE TABLE IF NOT EXISTS helper_driver_assignment (
    id BIGSERIAL PRIMARY KEY,
    assignment_type VARCHAR(30) NOT NULL DEFAULT 'delivery',
    no_reference VARCHAR(120) NOT NULL,
    id_cabang BIGINT NULL,
    id_driver BIGINT NULL,
    id_helper BIGINT NULL,
    id_armada BIGINT NULL,
    customer_name VARCHAR(255) NOT NULL,
    customer_phone VARCHAR(80) NULL,
    address TEXT NOT NULL,
    latitude NUMERIC(12,8) NULL,
    longitude NUMERIC(12,8) NULL,
    scheduled_date DATE NULL,
    priority VARCHAR(30) NOT NULL DEFAULT 'normal',
    status VARCHAR(40) NOT NULL DEFAULT 'scheduled',
    notes TEXT NULL,
    approved_return BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS helper_driver_assignment_item (
    id BIGSERIAL PRIMARY KEY,
    id_assignment BIGINT NOT NULL REFERENCES helper_driver_assignment(id) ON DELETE CASCADE,
    sku VARCHAR(120) NULL,
    product_name VARCHAR(255) NOT NULL,
    qty NUMERIC(14,2) NOT NULL DEFAULT 0,
    unit VARCHAR(40) NOT NULL DEFAULT 'PCS',
    checked_qty NUMERIC(14,2) NOT NULL DEFAULT 0,
    notes TEXT NULL
);

CREATE TABLE IF NOT EXISTS helper_driver_tracking (
    id BIGSERIAL PRIMARY KEY,
    id_assignment BIGINT NULL REFERENCES helper_driver_assignment(id) ON DELETE SET NULL,
    id_driver BIGINT NULL,
    id_armada BIGINT NULL,
    latitude NUMERIC(12,8) NOT NULL,
    longitude NUMERIC(12,8) NOT NULL,
    accuracy NUMERIC(10,2) NULL,
    speed NUMERIC(10,2) NULL,
    battery INTEGER NULL,
    status VARCHAR(40) NULL,
    recorded_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS helper_driver_proof (
    id BIGSERIAL PRIMARY KEY,
    id_assignment BIGINT NOT NULL REFERENCES helper_driver_assignment(id) ON DELETE CASCADE,
    proof_type VARCHAR(40) NOT NULL,
    receiver_name VARCHAR(255) NULL,
    photo_url TEXT NULL,
    signature_data TEXT NULL,
    notes TEXT NULL,
    latitude NUMERIC(12,8) NULL,
    longitude NUMERIC(12,8) NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS helper (
    id SERIAL PRIMARY KEY,
    id_user INTEGER NOT NULL,
    id_wilayah1 INTEGER NULL,
    id_wilayah2 INTEGER NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_helper_id_user
ON helper (id_user);

CREATE TABLE IF NOT EXISTS voucher_usage_review_note (
    id BIGSERIAL PRIMARY KEY,
    usage_kind VARCHAR(20) NOT NULL,
    usage_id BIGINT NOT NULL,
    action_type VARCHAR(20) NOT NULL,
    reviewer_note TEXT NULL,
    reviewer_user_id BIGINT NULL,
    reviewer_name VARCHAR(255) NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_voucher_usage_review_note_usage
ON voucher_usage_review_note (usage_kind, usage_id, created_at DESC);

DO $$
DECLARE
    current_constraint RECORD;
BEGIN
    SELECT
        tc.constraint_name,
        ccu.table_name AS foreign_table_name,
        ccu.column_name AS foreign_column_name
    INTO current_constraint
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON tc.constraint_name = kcu.constraint_name
     AND tc.table_schema = kcu.table_schema
    JOIN information_schema.constraint_column_usage ccu
      ON ccu.constraint_name = tc.constraint_name
     AND ccu.table_schema = tc.table_schema
    WHERE tc.constraint_type = 'FOREIGN KEY'
      AND tc.table_schema = 'public'
      AND tc.table_name = 'klaim_detail'
      AND kcu.column_name = 'id_klaim'
    LIMIT 1;

    IF current_constraint.constraint_name IS NULL THEN
        ALTER TABLE klaim_detail
        ADD CONSTRAINT fk_klaim
        FOREIGN KEY (id_klaim) REFERENCES klaim(id);
    ELSIF current_constraint.foreign_table_name <> 'klaim'
       OR current_constraint.foreign_column_name <> 'id' THEN
        EXECUTE format('ALTER TABLE klaim_detail DROP CONSTRAINT IF EXISTS %I', current_constraint.constraint_name);
        ALTER TABLE klaim_detail
        ADD CONSTRAINT fk_klaim
        FOREIGN KEY (id_klaim) REFERENCES klaim(id);
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO budimas_dev;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO budimas_dev;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO budimas_dev;
