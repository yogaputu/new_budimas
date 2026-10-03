-- Audit-only tables for the source-aware BDM Solo + TMP Solo active-sales
-- importer.  This DDL does not modify SQL Server or any public ERP table.
--
-- The actual importer uses migration_bdm_tmp_202608.sales_document_map and
-- sales_document_line_map as the immutable source identity.  These tables
-- only retain the review/apply history and rows that were deliberately held.

BEGIN;

CREATE TABLE IF NOT EXISTS migration_bdm_tmp_202608.active_sales_import_run (
    batch_id text PRIMARY KEY,
    bdm_stage_schema text NOT NULL,
    tmp_stage_schema text NOT NULL,
    bdm_stage_run_id bigint NOT NULL,
    tmp_stage_run_id bigint NOT NULL,
    bdm_consistency_mode text NOT NULL,
    tmp_consistency_mode text NOT NULL,
    bdm_maintenance_window_id text,
    tmp_maintenance_window_id text,
    delivered_ledger_policy text NOT NULL,
    settlement_policy text NOT NULL,
    candidate_headers integer NOT NULL DEFAULT 0,
    candidate_lines integer NOT NULL DEFAULT 0,
    inserted_headers integer NOT NULL DEFAULT 0,
    inserted_lines integer NOT NULL DEFAULT 0,
    inserted_ledger_lines integer NOT NULL DEFAULT 0,
    unchanged_headers integer NOT NULL DEFAULT 0,
    held_headers integer NOT NULL DEFAULT 0,
    hold_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    applied_by text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS migration_bdm_tmp_202608.active_sales_import_hold (
    id bigserial PRIMARY KEY,
    import_batch_id text NOT NULL
        REFERENCES migration_bdm_tmp_202608.active_sales_import_run(batch_id) ON DELETE RESTRICT,
    source_system text NOT NULL,
    source_stage_schema text NOT NULL,
    source_stage_run_id bigint NOT NULL,
    source_table text NOT NULL,
    source_staging_id bigint,
    source_nota text,
    source_nota_norm text,
    source_urut text,
    source_urut_norm text,
    source_row_hash text,
    hold_reason text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_active_sales_import_hold_batch_reason
    ON migration_bdm_tmp_202608.active_sales_import_hold (import_batch_id, hold_reason);

CREATE INDEX IF NOT EXISTS idx_active_sales_import_hold_source_document
    ON migration_bdm_tmp_202608.active_sales_import_hold
       (source_system, source_table, source_nota_norm, source_urut_norm);

CREATE TABLE IF NOT EXISTS migration_bdm_tmp_202608.active_sales_import_action (
    id bigserial PRIMARY KEY,
    import_batch_id text NOT NULL
        REFERENCES migration_bdm_tmp_202608.active_sales_import_run(batch_id) ON DELETE RESTRICT,
    source_system text NOT NULL,
    source_table text NOT NULL,
    source_nota text NOT NULL,
    source_nota_norm text NOT NULL,
    action text NOT NULL,
    id_sales_order integer,
    id_faktur integer,
    human_document_code text,
    line_count integer NOT NULL DEFAULT 0,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_active_sales_import_action_batch
    ON migration_bdm_tmp_202608.active_sales_import_action (import_batch_id, action);

COMMIT;
