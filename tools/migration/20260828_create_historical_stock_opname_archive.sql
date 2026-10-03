-- Historical Stock Opname archive for the source-aware BDM Solo + TMP Solo
-- migration.
--
-- IMPORTANT SAFETY BOUNDARY
-- -------------------------
-- This migration creates archive/audit tables ONLY in
-- migration_bdm_tmp_202608.  It intentionally does not insert, update, or
-- add triggers to public.stock_opname, public.stock_opname_detail,
-- public.inventory_ledger, WMS stock, or any accounting table.  Therefore
-- this historical import cannot be interpreted as an approved stock
-- adjustment by the current ERP backend.
--
-- The legacy StokOpnameAndroid source has one physical/base quantity only.
-- Good, Bad, system stock, rack, batch, and historic cost are not present;
-- they stay NULL rather than being invented.  CT + PCS is a display-only
-- derivation stored only after the importer verifies the exact approved UOM
-- map for that product.
--
-- Run once after 20260827_create_bdm_tmp_source_aware_mapping_registry.sql.
-- It is safe to install before final source staging because it imports no
-- source data by itself.

BEGIN;

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '60s';

DO $$
BEGIN
    IF to_regnamespace('migration_bdm_tmp_202608') IS NULL THEN
        RAISE EXCEPTION
            'schema migration_bdm_tmp_202608 belum ada; jalankan registry source-aware terlebih dahulu';
    END IF;
    IF to_regclass('migration_bdm_tmp_202608.source_context') IS NULL
       OR to_regclass('migration_bdm_tmp_202608.product_map') IS NULL
       OR to_regclass('migration_bdm_tmp_202608.product_uom_map') IS NULL THEN
        RAISE EXCEPTION
            'registry source-aware belum lengkap; source_context, product_map, dan product_uom_map wajib tersedia';
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS migration_bdm_tmp_202608.historical_stock_opname_import_run (
    batch_id text PRIMARY KEY,
    bdm_stage_schema text NOT NULL,
    tmp_stage_schema text NOT NULL,
    bdm_stage_run_id bigint NOT NULL,
    tmp_stage_run_id bigint NOT NULL,
    bdm_consistency_mode text NOT NULL,
    tmp_consistency_mode text NOT NULL,
    bdm_maintenance_window_id text,
    tmp_maintenance_window_id text,
    bdm_maintenance_freeze_attested boolean NOT NULL DEFAULT false,
    tmp_maintenance_freeze_attested boolean NOT NULL DEFAULT false,
    bdm_maintenance_freeze_confirmed_at timestamptz,
    tmp_maintenance_freeze_confirmed_at timestamptz,
    bdm_source_transaction_isolation text,
    tmp_source_transaction_isolation text,
    bdm_source_lock_timeout_ms integer,
    tmp_source_lock_timeout_ms integer,
    bdm_source_rows bigint NOT NULL CHECK (bdm_source_rows >= 0),
    tmp_source_rows bigint NOT NULL CHECK (tmp_source_rows >= 0),
    inserted_headers bigint NOT NULL CHECK (inserted_headers >= 0),
    inserted_lines bigint NOT NULL CHECK (inserted_lines >= 0),
    unchanged_headers bigint NOT NULL CHECK (unchanged_headers >= 0),
    held_rows bigint NOT NULL CHECK (held_rows >= 0),
    uom_display_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    hold_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    applied_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (bdm_consistency_mode IN ('snapshot', 'maintenance_freeze_serializable')),
    CHECK (tmp_consistency_mode IN ('snapshot', 'maintenance_freeze_serializable')),
    CHECK (
        (bdm_consistency_mode = 'snapshot' AND tmp_consistency_mode = 'snapshot')
        OR (
            bdm_consistency_mode = 'maintenance_freeze_serializable'
            AND tmp_consistency_mode = 'maintenance_freeze_serializable'
            AND bdm_maintenance_window_id IS NOT NULL
            AND btrim(bdm_maintenance_window_id) <> ''
            AND bdm_maintenance_window_id = tmp_maintenance_window_id
            AND bdm_maintenance_freeze_attested
            AND tmp_maintenance_freeze_attested
            AND bdm_maintenance_freeze_confirmed_at IS NOT NULL
            AND tmp_maintenance_freeze_confirmed_at IS NOT NULL
            AND lower(btrim(coalesce(bdm_source_transaction_isolation, ''))) = 'serializable'
            AND lower(btrim(coalesce(tmp_source_transaction_isolation, ''))) = 'serializable'
            AND bdm_source_lock_timeout_ms > 0
            AND tmp_source_lock_timeout_ms > 0
        )
    )
);

CREATE TABLE IF NOT EXISTS migration_bdm_tmp_202608.historical_stock_opname_header (
    id bigserial PRIMARY KEY,
    import_batch_id text NOT NULL
        REFERENCES migration_bdm_tmp_202608.historical_stock_opname_import_run(batch_id)
        ON DELETE RESTRICT,
    source_system text NOT NULL
        REFERENCES migration_bdm_tmp_202608.source_context(source_system)
        ON DELETE RESTRICT,
    source_stage_schema text NOT NULL,
    source_stage_run_id bigint NOT NULL,
    source_visit_id text NOT NULL,
    source_visit_id_norm text NOT NULL,
    source_customer_code text NOT NULL,
    source_customer_code_norm text NOT NULL,
    source_principal_code text NOT NULL,
    source_principal_code_norm text NOT NULL,
    source_sales_code text NOT NULL,
    source_sales_code_norm text NOT NULL,
    source_opname_date date NOT NULL,
    id_customer integer NOT NULL REFERENCES public.customer(id) ON DELETE RESTRICT,
    id_principal integer NOT NULL REFERENCES public.principal(id) ON DELETE RESTRICT,
    id_sales integer NOT NULL REFERENCES public.sales(id) ON DELETE RESTRICT,
    id_perusahaan integer NOT NULL REFERENCES public.perusahaan(id) ON DELETE RESTRICT,
    id_cabang integer NOT NULL REFERENCES public.cabang(id) ON DELETE RESTRICT,
    source_record_count integer NOT NULL CHECK (source_record_count > 0),
    source_payload_hash text NOT NULL CHECK (btrim(source_payload_hash) <> ''),
    import_status text NOT NULL DEFAULT 'historical_import'
        CHECK (import_status = 'historical_import'),
    -- The legacy payload has no approved Good/Bad/system-stock semantics.
    quantity_semantics text NOT NULL DEFAULT 'legacy_physical_base_pcs_good_bad_unknown'
        CHECK (quantity_semantics = 'legacy_physical_base_pcs_good_bad_unknown'),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (source_visit_id_norm = lower(btrim(source_visit_id))),
    CHECK (source_visit_id_norm <> ''),
    CHECK (source_customer_code_norm = lower(btrim(source_customer_code))),
    CHECK (source_customer_code_norm <> ''),
    CHECK (source_principal_code_norm = lower(btrim(source_principal_code))),
    CHECK (source_principal_code_norm <> ''),
    CHECK (source_sales_code_norm = lower(btrim(source_sales_code))),
    CHECK (source_sales_code_norm <> ''),
    UNIQUE (
        source_system,
        source_visit_id_norm,
        source_customer_code_norm,
        source_principal_code_norm,
        source_sales_code_norm,
        source_opname_date
    )
);

CREATE INDEX IF NOT EXISTS idx_historical_stock_opname_header_scope_date
    ON migration_bdm_tmp_202608.historical_stock_opname_header
       (source_system, id_cabang, source_opname_date, id_principal);

CREATE TABLE IF NOT EXISTS migration_bdm_tmp_202608.historical_stock_opname_line (
    id bigserial PRIMARY KEY,
    id_historical_stock_opname bigint NOT NULL
        REFERENCES migration_bdm_tmp_202608.historical_stock_opname_header(id)
        ON DELETE RESTRICT,
    source_system text NOT NULL
        REFERENCES migration_bdm_tmp_202608.source_context(source_system)
        ON DELETE RESTRICT,
    source_stage_schema text NOT NULL,
    source_stage_run_id bigint NOT NULL,
    source_staging_id bigint NOT NULL,
    source_row_hash text NOT NULL CHECK (btrim(source_row_hash) <> ''),
    source_record_id text NOT NULL,
    source_record_id_norm text NOT NULL,
    source_sku text NOT NULL,
    source_sku_norm text NOT NULL,
    id_produk bigint NOT NULL REFERENCES public.produk(id) ON DELETE RESTRICT,
    qty_physical_pcs bigint NOT NULL CHECK (qty_physical_pcs >= 0),
    -- Unknown is safer than treating a legacy physical count as Good stock.
    qty_good_pcs bigint,
    qty_bad_pcs bigint,
    qty_system_pcs bigint,
    source_qty_raw text NOT NULL,
    source_tgladd_raw text,
    -- Conversion is display-only.  Both UOM rows come from exact approved
    -- registry mappings and remain nullable when CT cannot be proven.
    id_base_produk_uom integer REFERENCES public.produk_uom(id) ON DELETE RESTRICT,
    base_uom_code text,
    id_ct_produk_uom integer REFERENCES public.produk_uom(id) ON DELETE RESTRICT,
    ct_uom_code text,
    ct_factor bigint,
    uom_display_status text NOT NULL CHECK (
        uom_display_status IN (
            'ct_plus_pcs_exact',
            'pcs_only_missing_exact_base_uom',
            'pcs_only_missing_exact_ct_uom',
            'pcs_only_ambiguous_exact_ct_uom',
            'pcs_only_invalid_exact_ct_uom'
        )
    ),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (source_record_id_norm = lower(btrim(source_record_id))),
    CHECK (source_record_id_norm <> ''),
    CHECK (source_sku_norm = lower(btrim(source_sku))),
    CHECK (source_sku_norm <> ''),
    CHECK ((id_base_produk_uom IS NULL) = (base_uom_code IS NULL)),
    CHECK (
        (id_ct_produk_uom IS NULL AND ct_uom_code IS NULL AND ct_factor IS NULL)
        OR (id_ct_produk_uom IS NOT NULL AND ct_uom_code IS NOT NULL AND ct_factor > 1)
    ),
    CHECK (
        (uom_display_status = 'ct_plus_pcs_exact' AND id_base_produk_uom IS NOT NULL AND id_ct_produk_uom IS NOT NULL)
        OR (uom_display_status <> 'ct_plus_pcs_exact' AND id_ct_produk_uom IS NULL)
    ),
    UNIQUE (source_system, source_record_id_norm),
    UNIQUE (id_historical_stock_opname, id_produk)
);

CREATE INDEX IF NOT EXISTS idx_historical_stock_opname_line_product
    ON migration_bdm_tmp_202608.historical_stock_opname_line (id_produk, id_historical_stock_opname);

CREATE TABLE IF NOT EXISTS migration_bdm_tmp_202608.historical_stock_opname_hold (
    id bigserial PRIMARY KEY,
    import_batch_id text NOT NULL
        REFERENCES migration_bdm_tmp_202608.historical_stock_opname_import_run(batch_id)
        ON DELETE RESTRICT,
    source_system text NOT NULL,
    source_stage_schema text NOT NULL,
    source_staging_id bigint NOT NULL,
    source_record_id text,
    source_row_hash text NOT NULL,
    hold_reason text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (import_batch_id, source_system, source_stage_schema, source_staging_id, hold_reason)
);

CREATE INDEX IF NOT EXISTS idx_historical_stock_opname_hold_reason
    ON migration_bdm_tmp_202608.historical_stock_opname_hold (import_batch_id, hold_reason);

CREATE TABLE IF NOT EXISTS migration_bdm_tmp_202608.historical_stock_opname_action (
    id bigserial PRIMARY KEY,
    import_batch_id text NOT NULL
        REFERENCES migration_bdm_tmp_202608.historical_stock_opname_import_run(batch_id)
        ON DELETE RESTRICT,
    source_system text NOT NULL,
    source_header_key text NOT NULL,
    action text NOT NULL CHECK (action IN ('insert_header_and_lines', 'unchanged_existing_archive')),
    id_historical_stock_opname bigint
        REFERENCES migration_bdm_tmp_202608.historical_stock_opname_header(id)
        ON DELETE RESTRICT,
    line_count integer NOT NULL CHECK (line_count > 0),
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (import_batch_id, source_system, source_header_key)
);

CREATE OR REPLACE VIEW migration_bdm_tmp_202608.historical_stock_opname_line_display AS
SELECT
    h.id AS historical_stock_opname_id,
    h.source_system,
    h.source_visit_id,
    h.source_opname_date,
    h.id_perusahaan,
    h.id_cabang,
    h.id_customer,
    h.id_principal,
    h.id_sales,
    h.import_status,
    h.quantity_semantics,
    l.id AS historical_stock_opname_line_id,
    l.source_record_id,
    l.source_sku,
    l.id_produk,
    l.qty_physical_pcs,
    l.qty_good_pcs,
    l.qty_bad_pcs,
    l.qty_system_pcs,
    l.base_uom_code,
    l.ct_uom_code,
    l.ct_factor,
    l.uom_display_status,
    CASE
        WHEN l.ct_factor IS NOT NULL THEN l.qty_physical_pcs / l.ct_factor
        ELSE NULL
    END AS qty_ct_display,
    CASE
        WHEN l.ct_factor IS NOT NULL THEN mod(l.qty_physical_pcs, l.ct_factor)
        ELSE l.qty_physical_pcs
    END AS qty_pcs_display
FROM migration_bdm_tmp_202608.historical_stock_opname_header h
JOIN migration_bdm_tmp_202608.historical_stock_opname_line l
  ON l.id_historical_stock_opname = h.id;

COMMENT ON TABLE migration_bdm_tmp_202608.historical_stock_opname_header IS
    'Arsip historis Stock Opname legacy. Bukan public.stock_opname dan tidak boleh menjadi trigger inventory ledger atau penyesuaian stok.';
COMMENT ON TABLE migration_bdm_tmp_202608.historical_stock_opname_line IS
    'Qty legacy tersimpan sebagai physical base/PCS. Good, Bad, system stock, cost, rack, dan batch tidak diisi bila tidak tersedia pada sumber.';
COMMENT ON VIEW migration_bdm_tmp_202608.historical_stock_opname_line_display IS
    'Tampilan CT + PCS hanya menggunakan faktor CT exact yang telah diverifikasi oleh importer; jika tidak ada, qty tetap PCS saja.';

COMMIT;
