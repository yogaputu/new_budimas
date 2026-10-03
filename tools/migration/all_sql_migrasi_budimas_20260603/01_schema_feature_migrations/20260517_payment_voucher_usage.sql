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
