-- Unified promo/voucher replacement.
-- Run this once on the target PostgreSQL database before using Promo All-In.

BEGIN;

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

CREATE INDEX IF NOT EXISTS idx_unified_promo_program_scope
    ON unified_promo_program (status, id_cabang, id_perusahaan, id_principal, id_customer);

CREATE INDEX IF NOT EXISTS idx_unified_promo_rule_scope
    ON unified_promo_rule (promo_id, target_type, id_produk, id_brand, id_subbrand, id_principal, id_customer);

CREATE INDEX IF NOT EXISTS idx_unified_promo_usage_invoice
    ON unified_promo_usage (id_sales_order, id_faktur, status);

COMMIT;

-- Optional legacy cleanup. Use this only after backup is confirmed.
-- It archives old voucher/promo tables into legacy_backup_* tables, then empties them.
-- Keep commented until the user explicitly wants production data cleaned.

-- BEGIN;
-- CREATE TABLE IF NOT EXISTS legacy_backup_voucher_1_20260517 AS TABLE voucher_1 WITH NO DATA;
-- INSERT INTO legacy_backup_voucher_1_20260517 SELECT * FROM voucher_1;
-- CREATE TABLE IF NOT EXISTS legacy_backup_voucher_2_20260517 AS TABLE voucher_2 WITH NO DATA;
-- INSERT INTO legacy_backup_voucher_2_20260517 SELECT * FROM voucher_2;
-- CREATE TABLE IF NOT EXISTS legacy_backup_voucher_3_20260517 AS TABLE voucher_3 WITH NO DATA;
-- INSERT INTO legacy_backup_voucher_3_20260517 SELECT * FROM voucher_3;
-- CREATE TABLE IF NOT EXISTS legacy_backup_draft_voucher_20260517 AS TABLE draft_voucher WITH NO DATA;
-- INSERT INTO legacy_backup_draft_voucher_20260517 SELECT * FROM draft_voucher;
-- CREATE TABLE IF NOT EXISTS legacy_backup_draft_voucher_2_20260517 AS TABLE draft_voucher_2 WITH NO DATA;
-- INSERT INTO legacy_backup_draft_voucher_2_20260517 SELECT * FROM draft_voucher_2;
-- CREATE TABLE IF NOT EXISTS legacy_backup_trade_promo_program_20260517 AS TABLE trade_promo_program WITH NO DATA;
-- INSERT INTO legacy_backup_trade_promo_program_20260517 SELECT * FROM trade_promo_program;
-- CREATE TABLE IF NOT EXISTS legacy_backup_trade_promo_program_rule_20260517 AS TABLE trade_promo_program_rule WITH NO DATA;
-- INSERT INTO legacy_backup_trade_promo_program_rule_20260517 SELECT * FROM trade_promo_program_rule;
-- CREATE TABLE IF NOT EXISTS legacy_backup_trade_promo_rule_product_20260517 AS TABLE trade_promo_rule_product WITH NO DATA;
-- INSERT INTO legacy_backup_trade_promo_rule_product_20260517 SELECT * FROM trade_promo_rule_product;
-- TRUNCATE TABLE voucher_1, voucher_2, voucher_3, draft_voucher, draft_voucher_2 RESTART IDENTITY CASCADE;
-- TRUNCATE TABLE trade_promo_rule_product, trade_promo_program_rule, trade_promo_program RESTART IDENTITY CASCADE;
-- COMMIT;
