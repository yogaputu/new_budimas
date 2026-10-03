ALTER TABLE payment_voucher_usage
    ADD COLUMN IF NOT EXISTS source VARCHAR(40) DEFAULT 'payment',
    ADD COLUMN IF NOT EXISTS reserved_at TIMESTAMP WITHOUT TIME ZONE,
    ADD COLUMN IF NOT EXISTS posted_at TIMESTAMP WITHOUT TIME ZONE,
    ADD COLUMN IF NOT EXISTS released_at TIMESTAMP WITHOUT TIME ZONE,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITHOUT TIME ZONE;

DROP INDEX IF EXISTS ux_payment_voucher_usage_active;

CREATE INDEX IF NOT EXISTS ix_payment_voucher_usage_lookup
    ON payment_voucher_usage (usage_type, usage_id, status);

CREATE INDEX IF NOT EXISTS ix_payment_voucher_usage_order_status
    ON payment_voucher_usage (id_sales_order, status);

CREATE UNIQUE INDEX IF NOT EXISTS ux_payment_voucher_usage_order_reserve
    ON payment_voucher_usage (usage_type, usage_id, id_sales_order)
    WHERE status = 0;

ALTER TABLE sales_order
    ADD COLUMN IF NOT EXISTS credit_note_nominal DOUBLE PRECISION DEFAULT 0,
    ADD COLUMN IF NOT EXISTS credit_note_snapshot TEXT;

ALTER TABLE faktur
    ADD COLUMN IF NOT EXISTS credit_note_nominal DOUBLE PRECISION DEFAULT 0,
    ADD COLUMN IF NOT EXISTS credit_note_snapshot TEXT;
