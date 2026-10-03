CREATE TABLE IF NOT EXISTS sales_supervisor_map (
    id SERIAL PRIMARY KEY,
    id_spv_user INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    id_sales_user INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    id_sales INTEGER REFERENCES sales(id) ON DELETE SET NULL,
    id_perusahaan INTEGER REFERENCES perusahaan(id) ON DELETE SET NULL,
    id_cabang INTEGER REFERENCES cabang(id) ON DELETE SET NULL,
    aktif BOOLEAN NOT NULL DEFAULT TRUE,
    start_date DATE,
    end_date DATE,
    notes TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT chk_sales_supervisor_map_not_self CHECK (id_spv_user <> id_sales_user),
    CONSTRAINT uq_sales_supervisor_map_scope UNIQUE (id_spv_user, id_sales_user, id_perusahaan, id_cabang)
);

CREATE INDEX IF NOT EXISTS idx_sales_supervisor_map_spv
    ON sales_supervisor_map (id_spv_user)
    WHERE aktif = TRUE;

CREATE INDEX IF NOT EXISTS idx_sales_supervisor_map_sales_user
    ON sales_supervisor_map (id_sales_user)
    WHERE aktif = TRUE;

CREATE INDEX IF NOT EXISTS idx_sales_supervisor_map_scope
    ON sales_supervisor_map (id_cabang, id_perusahaan)
    WHERE aktif = TRUE;
