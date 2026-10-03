-- Source-aware active transaction import support for BDM Solo + TMP Solo.
--
-- This migration intentionally separates a receivable payment import from a
-- cash/bank finalisation.  A legacy payment can be applied to the exact ERP
-- invoice only after its receipt and allocation reconcile.  No trigger in
-- this DDL posts journals, changes stock, creates a credit note, or changes
-- SQL Server.
--
-- Sales returns are recorded as preflight/audit data only.  The legacy return
-- payload does not establish a safe Good/Bad split, target UOM conversion, or
-- a completed return lifecycle, so it must not be inserted to public
-- retur_request / credit_note / inventory tables by this migration.

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
       OR to_regclass('migration_bdm_tmp_202608.customer_map') IS NULL
       OR to_regclass('migration_bdm_tmp_202608.sales_document_map') IS NULL THEN
        RAISE EXCEPTION
            'registry source-aware belum lengkap; source_context, customer_map, dan sales_document_map wajib tersedia';
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS migration_bdm_tmp_202608.active_payment_import_run (
    batch_id text PRIMARY KEY,
    import_mode text NOT NULL CHECK (import_mode = 'receivable_only'),
    bdm_sales_stage_schema text NOT NULL,
    tmp_sales_stage_schema text NOT NULL,
    bdm_payment_stage_schema text NOT NULL,
    tmp_payment_stage_schema text NOT NULL,
    bdm_sales_stage_run_id bigint NOT NULL,
    tmp_sales_stage_run_id bigint NOT NULL,
    bdm_payment_stage_run_id bigint NOT NULL,
    tmp_payment_stage_run_id bigint NOT NULL,
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
    source_receipts bigint NOT NULL CHECK (source_receipts >= 0),
    source_allocations bigint NOT NULL CHECK (source_allocations >= 0),
    inserted_receipts bigint NOT NULL CHECK (inserted_receipts >= 0),
    inserted_allocations bigint NOT NULL CHECK (inserted_allocations >= 0),
    unchanged_receipts bigint NOT NULL CHECK (unchanged_receipts >= 0),
    held_rows bigint NOT NULL CHECK (held_rows >= 0),
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

CREATE TABLE IF NOT EXISTS migration_bdm_tmp_202608.active_payment_receipt (
    id bigserial PRIMARY KEY,
    import_batch_id text NOT NULL
        REFERENCES migration_bdm_tmp_202608.active_payment_import_run(batch_id)
        ON DELETE RESTRICT,
    source_system text NOT NULL
        REFERENCES migration_bdm_tmp_202608.source_context(source_system)
        ON DELETE RESTRICT,
    source_header_table text NOT NULL CHECK (source_header_table = 'HBayarSM'),
    source_stage_schema text NOT NULL,
    source_stage_run_id bigint NOT NULL,
    source_staging_id bigint NOT NULL,
    source_row_hash text NOT NULL CHECK (btrim(source_row_hash) <> ''),
    source_receipt_no text NOT NULL,
    source_receipt_no_norm text NOT NULL,
    source_receipt_date date NOT NULL,
    source_customer_code text NOT NULL,
    source_customer_code_norm text NOT NULL,
    id_customer integer NOT NULL REFERENCES public.customer(id) ON DELETE RESTRICT,
    receipt_total numeric(18,2) NOT NULL CHECK (receipt_total > 0),
    payment_type smallint NOT NULL CHECK (payment_type IN (1, 2)),
    source_no_bukti text,
    source_keterangan text,
    source_payload_hash text NOT NULL CHECK (btrim(source_payload_hash) <> ''),
    import_status text NOT NULL DEFAULT 'receivable_applied'
        CHECK (import_status = 'receivable_applied'),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (source_receipt_no_norm = lower(btrim(source_receipt_no))),
    CHECK (source_receipt_no_norm <> ''),
    CHECK (source_customer_code_norm = lower(btrim(source_customer_code))),
    CHECK (source_customer_code_norm <> ''),
    UNIQUE (source_system, source_header_table, source_receipt_no_norm)
);

CREATE INDEX IF NOT EXISTS idx_active_payment_receipt_customer_date
    ON migration_bdm_tmp_202608.active_payment_receipt
       (id_customer, source_receipt_date, source_system);

CREATE TABLE IF NOT EXISTS migration_bdm_tmp_202608.active_payment_allocation (
    id bigserial PRIMARY KEY,
    id_active_payment_receipt bigint NOT NULL
        REFERENCES migration_bdm_tmp_202608.active_payment_receipt(id)
        ON DELETE RESTRICT,
    source_system text NOT NULL
        REFERENCES migration_bdm_tmp_202608.source_context(source_system)
        ON DELETE RESTRICT,
    source_detail_table text NOT NULL CHECK (source_detail_table = 'DBayarSM'),
    source_stage_schema text NOT NULL,
    source_stage_run_id bigint NOT NULL,
    source_staging_id bigint NOT NULL,
    source_row_hash text NOT NULL CHECK (btrim(source_row_hash) <> ''),
    source_invoice_no text NOT NULL,
    source_invoice_no_norm text NOT NULL,
    source_sales_table text NOT NULL CHECK (source_sales_table IN ('HJualSM', 'HJualSMAndroid')),
    id_sales_order integer NOT NULL REFERENCES public.sales_order(id) ON DELETE RESTRICT,
    id_faktur integer NOT NULL REFERENCES public.faktur(id) ON DELETE RESTRICT,
    id_setoran_customer integer NOT NULL REFERENCES public.setoran_customer(id) ON DELETE RESTRICT,
    allocation_amount numeric(18,2) NOT NULL CHECK (allocation_amount > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (source_invoice_no_norm = lower(btrim(source_invoice_no))),
    CHECK (source_invoice_no_norm <> ''),
    -- The source detail table has no immutable line ID.  The canonical row
    -- hash becomes the durable identity only after duplicate payload rows are
    -- rejected by the importer.
    UNIQUE (source_system, source_detail_table, source_row_hash)
);

CREATE INDEX IF NOT EXISTS idx_active_payment_allocation_target_invoice
    ON migration_bdm_tmp_202608.active_payment_allocation
       (id_faktur, id_sales_order);

CREATE TABLE IF NOT EXISTS migration_bdm_tmp_202608.active_payment_hold (
    id bigserial PRIMARY KEY,
    import_batch_id text NOT NULL
        REFERENCES migration_bdm_tmp_202608.active_payment_import_run(batch_id)
        ON DELETE RESTRICT,
    source_system text NOT NULL,
    source_table text NOT NULL,
    source_stage_schema text NOT NULL,
    source_staging_id bigint NOT NULL,
    source_row_hash text NOT NULL,
    source_receipt_no text,
    source_invoice_no text,
    hold_reason text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (import_batch_id, source_system, source_table, source_stage_schema, source_staging_id, hold_reason)
);

CREATE INDEX IF NOT EXISTS idx_active_payment_hold_reason
    ON migration_bdm_tmp_202608.active_payment_hold (import_batch_id, hold_reason);

CREATE TABLE IF NOT EXISTS migration_bdm_tmp_202608.active_payment_action (
    id bigserial PRIMARY KEY,
    import_batch_id text NOT NULL
        REFERENCES migration_bdm_tmp_202608.active_payment_import_run(batch_id)
        ON DELETE RESTRICT,
    source_system text NOT NULL,
    source_receipt_no text NOT NULL,
    source_receipt_no_norm text NOT NULL,
    action text NOT NULL CHECK (action IN ('insert_receivable_payment', 'unchanged_existing_payment')),
    id_active_payment_receipt bigint
        REFERENCES migration_bdm_tmp_202608.active_payment_receipt(id)
        ON DELETE RESTRICT,
    allocation_count integer NOT NULL CHECK (allocation_count > 0),
    amount numeric(18,2) NOT NULL CHECK (amount > 0),
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (source_receipt_no_norm = lower(btrim(source_receipt_no))),
    CHECK (source_receipt_no_norm <> ''),
    UNIQUE (import_batch_id, source_system, source_receipt_no_norm)
);

CREATE TABLE IF NOT EXISTS migration_bdm_tmp_202608.active_return_preflight_run (
    batch_id text PRIMARY KEY,
    bdm_sales_stage_schema text NOT NULL,
    tmp_sales_stage_schema text NOT NULL,
    bdm_return_stage_schema text NOT NULL,
    tmp_return_stage_schema text NOT NULL,
    bdm_sales_stage_run_id bigint NOT NULL,
    tmp_sales_stage_run_id bigint NOT NULL,
    bdm_return_stage_run_id bigint NOT NULL,
    tmp_return_stage_run_id bigint NOT NULL,
    source_headers bigint NOT NULL CHECK (source_headers >= 0),
    source_details bigint NOT NULL CHECK (source_details >= 0),
    eligible_for_manual_lifecycle_review bigint NOT NULL CHECK (eligible_for_manual_lifecycle_review >= 0),
    held_rows bigint NOT NULL CHECK (held_rows >= 0),
    hold_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS migration_bdm_tmp_202608.active_return_preflight_hold (
    id bigserial PRIMARY KEY,
    import_batch_id text NOT NULL
        REFERENCES migration_bdm_tmp_202608.active_return_preflight_run(batch_id)
        ON DELETE RESTRICT,
    source_system text NOT NULL,
    source_table text NOT NULL CHECK (source_table IN ('HReturSM', 'HReturSMAndroid', 'DReturSM', 'DReturSMAndroid')),
    source_stage_schema text NOT NULL,
    source_staging_id bigint NOT NULL,
    source_row_hash text NOT NULL,
    source_return_no text,
    source_invoice_no text,
    hold_reason text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (import_batch_id, source_system, source_table, source_stage_schema, source_staging_id, hold_reason)
);

CREATE INDEX IF NOT EXISTS idx_active_return_preflight_hold_reason
    ON migration_bdm_tmp_202608.active_return_preflight_hold (import_batch_id, hold_reason);

COMMENT ON TABLE migration_bdm_tmp_202608.active_payment_import_run IS
    'Audit run for exact active legacy payments. Import mode receivable_only intentionally does not finalise cash/bank or post accounting journals.';
COMMENT ON TABLE migration_bdm_tmp_202608.active_payment_allocation IS
    'Exact DBayarSM allocation to an immutable source-aware sales document and its setoran_customer row.';
COMMENT ON TABLE migration_bdm_tmp_202608.active_return_preflight_hold IS
    'Return source rows held pending explicit lifecycle, UOM, Good/Bad, CN, and stock policy. No public return/stock write is permitted from this table.';

COMMIT;
