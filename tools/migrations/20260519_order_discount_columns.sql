-- Promo/discount columns used by sales order, invoice dashboard, and payment pages.
-- Run this as the PostgreSQL owner/superuser on every target database.

BEGIN;

ALTER TABLE sales_order
    ADD COLUMN IF NOT EXISTS total_order_before_discount DOUBLE PRECISION DEFAULT 0,
    ADD COLUMN IF NOT EXISTS unified_promo_nominal DOUBLE PRECISION DEFAULT 0,
    ADD COLUMN IF NOT EXISTS manual_discount_type VARCHAR(20),
    ADD COLUMN IF NOT EXISTS manual_discount_value DOUBLE PRECISION DEFAULT 0,
    ADD COLUMN IF NOT EXISTS manual_discount_percent_equivalent DOUBLE PRECISION DEFAULT 0,
    ADD COLUMN IF NOT EXISTS manual_discount_nominal DOUBLE PRECISION DEFAULT 0,
    ADD COLUMN IF NOT EXISTS order_discount_total DOUBLE PRECISION DEFAULT 0,
    ADD COLUMN IF NOT EXISTS order_discount_note TEXT,
    ADD COLUMN IF NOT EXISTS unified_promo_snapshot TEXT;

ALTER TABLE faktur
    ADD COLUMN IF NOT EXISTS total_penjualan_before_discount DOUBLE PRECISION DEFAULT 0,
    ADD COLUMN IF NOT EXISTS unified_promo_nominal DOUBLE PRECISION DEFAULT 0,
    ADD COLUMN IF NOT EXISTS manual_discount_type VARCHAR(20),
    ADD COLUMN IF NOT EXISTS manual_discount_value DOUBLE PRECISION DEFAULT 0,
    ADD COLUMN IF NOT EXISTS manual_discount_percent_equivalent DOUBLE PRECISION DEFAULT 0,
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

COMMIT;
