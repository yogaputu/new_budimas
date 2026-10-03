BEGIN;

CREATE TABLE IF NOT EXISTS fixed_asset (
    id BIGSERIAL PRIMARY KEY,
    kode_asset VARCHAR(80) NOT NULL,
    nama_asset VARCHAR(255) NOT NULL,
    id_perusahaan INTEGER NOT NULL,
    id_cabang INTEGER NOT NULL,
    kategori_asset VARCHAR(120),
    tax_rule_key VARCHAR(80) NOT NULL,
    tax_group VARCHAR(40) NOT NULL,
    asset_type VARCHAR(40) NOT NULL,
    depreciation_method VARCHAR(40) NOT NULL DEFAULT 'straight_line',
    useful_life_years INTEGER NOT NULL,
    tax_rate_percent NUMERIC(8,4) NOT NULL,
    acquisition_date DATE NOT NULL,
    start_depreciation_date DATE NOT NULL,
    acquisition_cost NUMERIC(18,2) NOT NULL DEFAULT 0,
    residual_value NUMERIC(18,2) NOT NULL DEFAULT 0,
    location VARCHAR(255),
    serial_number VARCHAR(120),
    pic VARCHAR(120),
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    notes TEXT,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    created_by INTEGER,
    updated_by INTEGER,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT fixed_asset_method_check CHECK (depreciation_method IN ('straight_line', 'declining_balance')),
    CONSTRAINT fixed_asset_status_check CHECK (status IN ('active', 'inactive', 'disposed')),
    CONSTRAINT fixed_asset_cost_check CHECK (acquisition_cost > 0),
    CONSTRAINT fixed_asset_residual_check CHECK (residual_value >= 0 AND residual_value < acquisition_cost)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_fixed_asset_kode_active
    ON fixed_asset (kode_asset)
    WHERE COALESCE(is_deleted, FALSE) = FALSE;

CREATE INDEX IF NOT EXISTS idx_fixed_asset_scope
    ON fixed_asset (id_perusahaan, id_cabang, status)
    WHERE COALESCE(is_deleted, FALSE) = FALSE;

CREATE INDEX IF NOT EXISTS idx_fixed_asset_tax_rule
    ON fixed_asset (tax_rule_key, depreciation_method)
    WHERE COALESCE(is_deleted, FALSE) = FALSE;

COMMIT;
