-- Clean, source-qualified registry for the BDM Solo + TMP Solo blue/green
-- import.  This file is deliberately a one-time DDL scaffold for a NEW
-- PostgreSQL target database only.  It must never be run against the current
-- production database (budimas_dev), SQL Server, or the old
-- migration_bdm_tmp_202608 registry.
--
-- Required invocation guard (example; substitute the approved clean target):
--   PGOPTIONS='-c migration_clean_bdm_tmp_202609.allow_ddl=acknowledge-clean-target' \
--     psql -v ON_ERROR_STOP=1 -d <new_clean_database> \
--       -f tools/migration/20260902_create_clean_import_registry.sql
--
-- This file creates provenance and audit structures only.  It does not copy
-- SQL Server data, create ERP master/transaction rows, post stock/HPP/AR, or
-- modify any existing public ERP row.
--
-- Assumptions verified read-only on 2026-09-02 against budimas_dev:
--   * perusahaan.id, cabang.id, perusahaan_cabang.id, customer.id,
--     principal.id, users.id, sales.id, sales_order.id, faktur.id, and
--     faktur_detail.id are integer.
--   * produk.id is bigint; produk_uom.id is integer and
--     produk_uom.id_produk is integer in the present ERP schema.
--   * the Solo cabang code is shared logically by both BMM and TMP through
--     public.perusahaan_cabang.  Therefore resolve_source_context() finds the
--     branch code globally, then requires exactly one matching
--     (perusahaan, cabang) row.  It intentionally does NOT assume that
--     cabang.id_perusahaan equals the BMM company for the BMM+Solo context.
--
-- The clean target must have been created from an approved schema-only
-- production baseline and must not contain legacy sales transactions.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

DO $$
DECLARE
    v_relation text;
    v_actual_type text;
    v_expected record;
BEGIN
    IF current_setting('migration_clean_bdm_tmp_202609.allow_ddl', true)
           IS DISTINCT FROM 'acknowledge-clean-target' THEN
        RAISE EXCEPTION
            'DDL clean import ditolak: set migration_clean_bdm_tmp_202609.allow_ddl=acknowledge-clean-target pada sesi psql target baru';
    END IF;

    IF current_database() IN ('budimas_dev', 'postgres', 'template0', 'template1') THEN
        RAISE EXCEPTION
            'DDL clean import ditolak untuk database "%"; gunakan database blue/green baru, bukan database produksi/template',
            current_database();
    END IF;

    IF to_regnamespace('migration_clean_bdm_tmp_202609') IS NOT NULL THEN
        RAISE EXCEPTION
            'schema migration_clean_bdm_tmp_202609 sudah ada di database "%"; scaffold ini satu-kali dan tidak boleh menimpa registry yang sudah ada',
            current_database();
    END IF;

    FOREACH v_relation IN ARRAY ARRAY[
        'public.perusahaan', 'public.cabang', 'public.perusahaan_cabang',
        'public.customer', 'public.principal', 'public.users', 'public.sales',
        'public.produk', 'public.produk_uom', 'public.sales_order',
        'public.sales_order_detail', 'public.faktur', 'public.faktur_detail'
    ] LOOP
        IF to_regclass(v_relation) IS NULL THEN
            RAISE EXCEPTION 'baseline ERP tidak lengkap: relation % tidak ditemukan', v_relation;
        END IF;
    END LOOP;

    -- Protect against accidentally attaching the registry to a populated
    -- legacy transaction database.  Master/reference rows are validated by
    -- the importer; these transactional tables must be empty before import.
    FOREACH v_relation IN ARRAY ARRAY[
        'public.sales_order', 'public.sales_order_detail',
        'public.faktur', 'public.faktur_detail'
    ] LOOP
        EXECUTE format('SELECT EXISTS (SELECT 1 FROM %s LIMIT 1)', v_relation)
           INTO STRICT v_actual_type;
        IF v_actual_type::boolean THEN
            RAISE EXCEPTION
                'clean target tidak kosong: % sudah memiliki data; jangan campur import baru dengan transaksi legacy',
                v_relation;
        END IF;
    END LOOP;

    FOR v_expected IN
        SELECT *
          FROM (VALUES
            ('public.perusahaan', 'id', 'integer'),
            ('public.perusahaan', 'kode', 'character varying'),
            ('public.cabang', 'id', 'integer'),
            ('public.cabang', 'kode', 'character varying'),
            ('public.perusahaan_cabang', 'id', 'integer'),
            ('public.perusahaan_cabang', 'id_perusahaan', 'integer'),
            ('public.perusahaan_cabang', 'id_cabang', 'integer'),
            ('public.customer', 'id', 'integer'),
            ('public.customer', 'id_cabang', 'integer'),
            ('public.principal', 'id', 'integer'),
            ('public.principal', 'id_perusahaan', 'integer'),
            ('public.users', 'id', 'integer'),
            ('public.users', 'id_perusahaan', 'integer'),
            ('public.users', 'id_cabang', 'integer'),
            ('public.sales', 'id', 'integer'),
            ('public.sales', 'id_user', 'integer'),
            ('public.sales', 'id_principal', 'integer'),
            ('public.produk', 'id', 'bigint'),
            ('public.produk', 'id_principal', 'integer'),
            ('public.produk_uom', 'id', 'integer'),
            ('public.produk_uom', 'id_produk', 'integer'),
            ('public.produk_uom', 'kode', 'character varying'),
            ('public.produk_uom', 'level', 'smallint'),
            ('public.produk_uom', 'faktor_konversi', 'integer'),
            ('public.sales_order', 'id', 'integer'),
            ('public.sales_order', 'id_cabang', 'integer'),
            ('public.sales_order_detail', 'id', 'integer'),
            ('public.sales_order_detail', 'id_sales_order', 'integer'),
            ('public.sales_order_detail', 'id_produk', 'integer'),
            ('public.faktur', 'id', 'integer'),
            ('public.faktur', 'id_sales_order', 'integer'),
            ('public.faktur_detail', 'id', 'integer'),
            ('public.faktur_detail', 'id_faktur', 'integer'),
            ('public.faktur_detail', 'id_sales_order', 'integer'),
            ('public.faktur_detail', 'id_principal', 'integer')
          ) AS expected(relation_name, column_name, expected_type)
    LOOP
        -- Compare the base type only.  `format_type(..., atttypmod)` would
        -- turn a valid varchar(25) into "character varying(25)" and reject
        -- it even though the importer intentionally accepts any varchar
        -- length that is compatible with the ERP column contract.
        SELECT a.atttypid::regtype::text
          INTO v_actual_type
          FROM pg_attribute a
         WHERE a.attrelid = v_expected.relation_name::regclass
           AND a.attname = v_expected.column_name
           AND a.attnum > 0
           AND NOT a.attisdropped;

        IF v_actual_type IS DISTINCT FROM v_expected.expected_type THEN
            RAISE EXCEPTION
                'baseline ERP tidak cocok: %.% bertipe %, diharapkan %',
                v_expected.relation_name,
                v_expected.column_name,
                coalesce(v_actual_type, '<missing>'),
                v_expected.expected_type;
        END IF;
    END LOOP;
END;
$$;

CREATE SCHEMA migration_clean_bdm_tmp_202609;

COMMENT ON SCHEMA migration_clean_bdm_tmp_202609 IS
    'Immutable source-qualified registry/audit for the blue-green BDM Solo + TMP Solo clean import. Not an ERP operational schema.';

CREATE FUNCTION migration_clean_bdm_tmp_202609.norm_migration_key(p_value text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
RETURNS NULL ON NULL INPUT
SET search_path = pg_catalog
AS $$
    SELECT lower(btrim(p_value));
$$;

CREATE FUNCTION migration_clean_bdm_tmp_202609.assert_nonblank_key(
    p_value text,
    p_label text
)
RETURNS void
LANGUAGE plpgsql
IMMUTABLE
PARALLEL SAFE
SET search_path = pg_catalog
AS $$
BEGIN
    IF p_value IS NULL OR btrim(p_value) = '' THEN
        RAISE EXCEPTION '% tidak boleh kosong', p_label;
    END IF;
END;
$$;

CREATE FUNCTION migration_clean_bdm_tmp_202609.assert_sha256(
    p_value text,
    p_label text
)
RETURNS void
LANGUAGE plpgsql
IMMUTABLE
PARALLEL SAFE
SET search_path = pg_catalog
AS $$
BEGIN
    IF lower(btrim(coalesce(p_value, ''))) !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION '% harus berupa checksum SHA-256 hex 64 karakter', p_label;
    END IF;
END;
$$;

-- Audit payloads must contain only provenance and reconciliation evidence.
-- The recursive key check blocks accidental placement of credential fields in
-- JSON.  Values are never inspected or logged by this function.
CREATE FUNCTION migration_clean_bdm_tmp_202609.assert_audit_payload_safe(
    p_payload jsonb,
    p_label text
)
RETURNS void
LANGUAGE plpgsql
IMMUTABLE
PARALLEL SAFE
SET search_path = pg_catalog
AS $$
DECLARE
    v_forbidden_key text;
BEGIN
    IF p_payload IS NULL OR jsonb_typeof(p_payload) <> 'object' THEN
        RAISE EXCEPTION '% harus JSON object', p_label;
    END IF;

    WITH RECURSIVE walk(key_name, value_json) AS (
        SELECT NULL::text, p_payload
        UNION ALL
        SELECT child.key_name, child.value_json
          FROM walk parent
          CROSS JOIN LATERAL (
              SELECT e.key::text AS key_name, e.value AS value_json
                FROM jsonb_each(
                    CASE WHEN jsonb_typeof(parent.value_json) = 'object'
                         THEN parent.value_json ELSE '{}'::jsonb END
                ) AS e
              UNION ALL
              SELECT NULL::text AS key_name, a.value AS value_json
                FROM jsonb_array_elements(
                    CASE WHEN jsonb_typeof(parent.value_json) = 'array'
                         THEN parent.value_json ELSE '[]'::jsonb END
                ) AS a
          ) AS child
    )
    SELECT key_name
      INTO v_forbidden_key
      FROM walk
     WHERE key_name IS NOT NULL
       AND lower(key_name) ~ '(password|passwd|secret|token|api[_-]?key|private[_-]?key|credential)'
     LIMIT 1;

    IF v_forbidden_key IS NOT NULL THEN
        RAISE EXCEPTION '% memuat key sensitif "%"; simpan secret hanya di environment server',
            p_label, v_forbidden_key;
    END IF;
END;
$$;

CREATE TABLE migration_clean_bdm_tmp_202609.source_context (
    source_system text PRIMARY KEY
        CHECK (source_system IN ('bdm_solo_dist', 'tmp_solo_dist')),
    target_company_code text NOT NULL,
    target_company_code_norm text NOT NULL,
    target_branch_code text NOT NULL,
    target_branch_code_norm text NOT NULL,
    document_prefix text NOT NULL,
    target_company_id integer NOT NULL
        REFERENCES public.perusahaan(id) ON DELETE RESTRICT,
    target_branch_id integer NOT NULL
        REFERENCES public.cabang(id) ON DELETE RESTRICT,
    target_perusahaan_cabang_id integer NOT NULL
        REFERENCES public.perusahaan_cabang(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (target_company_code_norm = migration_clean_bdm_tmp_202609.norm_migration_key(target_company_code)),
    CHECK (target_company_code_norm <> ''),
    CHECK (target_branch_code_norm = migration_clean_bdm_tmp_202609.norm_migration_key(target_branch_code)),
    CHECK (target_branch_code_norm <> ''),
    CHECK (btrim(document_prefix) = document_prefix),
    CHECK (document_prefix <> ''),
    UNIQUE (target_company_id, target_branch_id),
    UNIQUE (target_perusahaan_cabang_id),
    UNIQUE (document_prefix)
);

CREATE INDEX idx_clean_source_context_company_branch
    ON migration_clean_bdm_tmp_202609.source_context (target_company_id, target_branch_id);

CREATE INDEX idx_clean_source_context_branch
    ON migration_clean_bdm_tmp_202609.source_context (target_branch_id);

CREATE FUNCTION migration_clean_bdm_tmp_202609.assert_source_context_write()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    v_company_count integer;
    v_branch_count integer;
    v_pair_count integer;
    v_company_id integer;
    v_branch_id integer;
    v_pair_id integer;
BEGIN
    IF current_setting('migration_clean_bdm_tmp_202609.context_resolver', true)
           IS DISTINCT FROM 'enabled' THEN
        RAISE EXCEPTION
            'source_context hanya boleh ditulis melalui resolve_source_context(); ID numerik tidak boleh diisi manual';
    END IF;

    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'source_context bersifat immutable; buat target database baru bila konteks source berubah';
    END IF;

    SELECT count(*), min(p.id)
      INTO v_company_count, v_company_id
      FROM public.perusahaan p
     WHERE migration_clean_bdm_tmp_202609.norm_migration_key(p.kode) = NEW.target_company_code_norm;
    IF v_company_count <> 1 OR v_company_id IS DISTINCT FROM NEW.target_company_id THEN
        RAISE EXCEPTION 'kode perusahaan % tidak meresolusi tepat satu perusahaan target', NEW.target_company_code;
    END IF;

    -- The branch code is intentionally global.  Do not join cabang through
    -- cabang.id_perusahaan: BMM+SLO is represented by perusahaan_cabang.
    SELECT count(*), min(c.id)
      INTO v_branch_count, v_branch_id
      FROM public.cabang c
     WHERE migration_clean_bdm_tmp_202609.norm_migration_key(c.kode) = NEW.target_branch_code_norm;
    IF v_branch_count <> 1 OR v_branch_id IS DISTINCT FROM NEW.target_branch_id THEN
        RAISE EXCEPTION 'kode cabang % tidak meresolusi tepat satu cabang target secara global', NEW.target_branch_code;
    END IF;

    SELECT count(*), min(pc.id)
      INTO v_pair_count, v_pair_id
      FROM public.perusahaan_cabang pc
     WHERE pc.id_perusahaan = NEW.target_company_id
       AND pc.id_cabang = NEW.target_branch_id;
    IF v_pair_count <> 1 OR v_pair_id IS DISTINCT FROM NEW.target_perusahaan_cabang_id THEN
        RAISE EXCEPTION
            'pasangan perusahaan/cabang untuk source % harus tepat satu perusahaan_cabang',
            NEW.source_system;
    END IF;

    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER source_context_write_guard
BEFORE INSERT OR UPDATE ON migration_clean_bdm_tmp_202609.source_context
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.assert_source_context_write();

CREATE FUNCTION migration_clean_bdm_tmp_202609.resolve_source_context(
    p_source_system text,
    p_company_code text,
    p_branch_code text,
    p_document_prefix text
)
RETURNS migration_clean_bdm_tmp_202609.source_context
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    v_source_system text := migration_clean_bdm_tmp_202609.norm_migration_key(p_source_system);
    v_company_code_norm text := migration_clean_bdm_tmp_202609.norm_migration_key(p_company_code);
    v_branch_code_norm text := migration_clean_bdm_tmp_202609.norm_migration_key(p_branch_code);
    v_company_count integer;
    v_branch_count integer;
    v_pair_count integer;
    v_company_id integer;
    v_branch_id integer;
    v_pair_id integer;
    v_existing migration_clean_bdm_tmp_202609.source_context%ROWTYPE;
    v_result migration_clean_bdm_tmp_202609.source_context%ROWTYPE;
BEGIN
    PERFORM migration_clean_bdm_tmp_202609.assert_nonblank_key(p_source_system, 'source_system');
    PERFORM migration_clean_bdm_tmp_202609.assert_nonblank_key(p_company_code, 'target_company_code');
    PERFORM migration_clean_bdm_tmp_202609.assert_nonblank_key(p_branch_code, 'target_branch_code');
    PERFORM migration_clean_bdm_tmp_202609.assert_nonblank_key(p_document_prefix, 'document_prefix');

    IF v_source_system NOT IN ('bdm_solo_dist', 'tmp_solo_dist') THEN
        RAISE EXCEPTION 'source_system % tidak diizinkan', p_source_system;
    END IF;
    IF btrim(p_document_prefix) <> p_document_prefix THEN
        RAISE EXCEPTION 'document_prefix tidak boleh memiliki spasi awal/akhir';
    END IF;

    SELECT count(*), min(p.id)
      INTO v_company_count, v_company_id
      FROM public.perusahaan p
     WHERE migration_clean_bdm_tmp_202609.norm_migration_key(p.kode) = v_company_code_norm;
    IF v_company_count <> 1 THEN
        RAISE EXCEPTION 'kode perusahaan % menghasilkan % kandidat; perbaiki policy/baseline terlebih dahulu',
            p_company_code, v_company_count;
    END IF;

    -- Do not filter by cabang.id_perusahaan.  The approved context is the
    -- relation in perusahaan_cabang, not the legacy ownership column.
    SELECT count(*), min(c.id)
      INTO v_branch_count, v_branch_id
      FROM public.cabang c
     WHERE migration_clean_bdm_tmp_202609.norm_migration_key(c.kode) = v_branch_code_norm;
    IF v_branch_count <> 1 THEN
        RAISE EXCEPTION 'kode cabang % menghasilkan % kandidat global; perbaiki baseline terlebih dahulu',
            p_branch_code, v_branch_count;
    END IF;

    SELECT count(*), min(pc.id)
      INTO v_pair_count, v_pair_id
      FROM public.perusahaan_cabang pc
     WHERE pc.id_perusahaan = v_company_id
       AND pc.id_cabang = v_branch_id;
    IF v_pair_count <> 1 THEN
        RAISE EXCEPTION
            'pasangan perusahaan % dan cabang % menghasilkan % perusahaan_cabang; tidak ada fallback otomatis',
            p_company_code, p_branch_code, v_pair_count;
    END IF;

    SELECT *
      INTO v_existing
      FROM migration_clean_bdm_tmp_202609.source_context sc
     WHERE sc.source_system = v_source_system;

    IF FOUND THEN
        IF v_existing.target_company_code_norm IS DISTINCT FROM v_company_code_norm
           OR v_existing.target_branch_code_norm IS DISTINCT FROM v_branch_code_norm
           OR v_existing.document_prefix IS DISTINCT FROM p_document_prefix
           OR v_existing.target_company_id IS DISTINCT FROM v_company_id
           OR v_existing.target_branch_id IS DISTINCT FROM v_branch_id
           OR v_existing.target_perusahaan_cabang_id IS DISTINCT FROM v_pair_id THEN
            RAISE EXCEPTION
                'source_context % sudah ada dengan fingerprint berbeda; jangan mengganti scope/prefix pada database clean yang sama',
                v_source_system;
        END IF;
        RETURN v_existing;
    END IF;

    PERFORM set_config('migration_clean_bdm_tmp_202609.context_resolver', 'enabled', true);

    INSERT INTO migration_clean_bdm_tmp_202609.source_context (
        source_system,
        target_company_code,
        target_company_code_norm,
        target_branch_code,
        target_branch_code_norm,
        document_prefix,
        target_company_id,
        target_branch_id,
        target_perusahaan_cabang_id
    ) VALUES (
        v_source_system,
        btrim(p_company_code),
        v_company_code_norm,
        btrim(p_branch_code),
        v_branch_code_norm,
        p_document_prefix,
        v_company_id,
        v_branch_id,
        v_pair_id
    )
    RETURNING * INTO v_result;

    RETURN v_result;
END;
$$;

CREATE TABLE migration_clean_bdm_tmp_202609.import_run (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    import_key text NOT NULL,
    pipeline_version text NOT NULL,
    phase text NOT NULL CHECK (phase IN ('master', 'sales', 'reconciliation')),
    status text NOT NULL DEFAULT 'started'
        CHECK (status IN ('started', 'dry_run', 'verified', 'committed', 'failed', 'aborted')),
    target_database text NOT NULL DEFAULT current_database(),
    config_sha256 text NOT NULL,
    baseline_schema_sha256 text NOT NULL,
    baseline_reference_sha256 text NOT NULL,
    bdm_stage_schema text NOT NULL,
    bdm_stage_run_id bigint NOT NULL CHECK (bdm_stage_run_id > 0),
    bdm_snapshot_label text NOT NULL,
    bdm_snapshot_sha256 text NOT NULL,
    tmp_stage_schema text NOT NULL,
    tmp_stage_run_id bigint NOT NULL CHECK (tmp_stage_run_id > 0),
    tmp_snapshot_label text NOT NULL,
    tmp_snapshot_sha256 text NOT NULL,
    run_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    started_by text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    verified_at timestamptz,
    committed_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (btrim(import_key) <> ''),
    CHECK (btrim(pipeline_version) <> ''),
    CHECK (target_database = current_database()),
    CHECK (btrim(bdm_stage_schema) <> ''),
    CHECK (btrim(tmp_stage_schema) <> ''),
    CHECK (btrim(bdm_snapshot_label) <> ''),
    CHECK (btrim(tmp_snapshot_label) <> ''),
    CHECK (btrim(started_by) <> ''),
    CHECK (lower(config_sha256) ~ '^[0-9a-f]{64}$'),
    CHECK (lower(baseline_schema_sha256) ~ '^[0-9a-f]{64}$'),
    CHECK (lower(baseline_reference_sha256) ~ '^[0-9a-f]{64}$'),
    CHECK (lower(bdm_snapshot_sha256) ~ '^[0-9a-f]{64}$'),
    CHECK (lower(tmp_snapshot_sha256) ~ '^[0-9a-f]{64}$'),
    CHECK (jsonb_typeof(run_metadata) = 'object'),
    UNIQUE (import_key),
    UNIQUE (
        phase, config_sha256,
        bdm_stage_schema, bdm_stage_run_id, bdm_snapshot_sha256,
        tmp_stage_schema, tmp_stage_run_id, tmp_snapshot_sha256
    )
);

CREATE INDEX idx_clean_import_run_status_phase
    ON migration_clean_bdm_tmp_202609.import_run (status, phase, started_at DESC);

CREATE FUNCTION migration_clean_bdm_tmp_202609.assert_import_run_write()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    v_allowed boolean := false;
BEGIN
    PERFORM migration_clean_bdm_tmp_202609.assert_audit_payload_safe(NEW.run_metadata, 'import_run.run_metadata');

    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'started' THEN
            RAISE EXCEPTION 'import_run baru harus berstatus started';
        END IF;
        RETURN NEW;
    END IF;

    IF ROW(
        NEW.import_key, NEW.pipeline_version, NEW.phase, NEW.target_database,
        NEW.config_sha256, NEW.baseline_schema_sha256, NEW.baseline_reference_sha256,
        NEW.bdm_stage_schema, NEW.bdm_stage_run_id, NEW.bdm_snapshot_label, NEW.bdm_snapshot_sha256,
        NEW.tmp_stage_schema, NEW.tmp_stage_run_id, NEW.tmp_snapshot_label, NEW.tmp_snapshot_sha256,
        NEW.run_metadata, NEW.started_by, NEW.started_at
    ) IS DISTINCT FROM ROW(
        OLD.import_key, OLD.pipeline_version, OLD.phase, OLD.target_database,
        OLD.config_sha256, OLD.baseline_schema_sha256, OLD.baseline_reference_sha256,
        OLD.bdm_stage_schema, OLD.bdm_stage_run_id, OLD.bdm_snapshot_label, OLD.bdm_snapshot_sha256,
        OLD.tmp_stage_schema, OLD.tmp_stage_run_id, OLD.tmp_snapshot_label, OLD.tmp_snapshot_sha256,
        OLD.run_metadata, OLD.started_by, OLD.started_at
    ) THEN
        RAISE EXCEPTION 'fingerprint import_run % bersifat immutable', OLD.id;
    END IF;

    v_allowed := (OLD.status = NEW.status)
        OR (OLD.status = 'started' AND NEW.status IN ('dry_run', 'verified', 'failed', 'aborted'))
        OR (OLD.status = 'dry_run' AND NEW.status IN ('verified', 'failed', 'aborted'))
        OR (OLD.status = 'verified' AND NEW.status IN ('committed', 'failed', 'aborted'));
    IF NOT v_allowed THEN
        RAISE EXCEPTION 'transisi status import_run % -> % tidak diizinkan untuk run %',
            OLD.status, NEW.status, OLD.id;
    END IF;

    IF NEW.status = 'verified' AND OLD.status <> 'verified' THEN
        NEW.verified_at := now();
    END IF;
    IF NEW.status = 'committed' AND OLD.status <> 'committed' THEN
        IF NEW.verified_at IS NULL THEN
            RAISE EXCEPTION 'run % belum terverifikasi sehingga tidak boleh committed', OLD.id;
        END IF;
        NEW.committed_at := now();
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER import_run_write_guard
BEFORE INSERT OR UPDATE ON migration_clean_bdm_tmp_202609.import_run
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.assert_import_run_write();

CREATE FUNCTION migration_clean_bdm_tmp_202609.begin_import_run(
    p_import_key text,
    p_pipeline_version text,
    p_phase text,
    p_config_sha256 text,
    p_baseline_schema_sha256 text,
    p_baseline_reference_sha256 text,
    p_bdm_stage_schema text,
    p_bdm_stage_run_id bigint,
    p_bdm_snapshot_label text,
    p_bdm_snapshot_sha256 text,
    p_tmp_stage_schema text,
    p_tmp_stage_run_id bigint,
    p_tmp_snapshot_label text,
    p_tmp_snapshot_sha256 text,
    p_run_metadata jsonb,
    p_started_by text
)
RETURNS bigint
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    v_existing migration_clean_bdm_tmp_202609.import_run%ROWTYPE;
    v_id bigint;
BEGIN
    PERFORM migration_clean_bdm_tmp_202609.assert_nonblank_key(p_import_key, 'import_key');
    PERFORM migration_clean_bdm_tmp_202609.assert_nonblank_key(p_pipeline_version, 'pipeline_version');
    PERFORM migration_clean_bdm_tmp_202609.assert_nonblank_key(p_phase, 'phase');
    PERFORM migration_clean_bdm_tmp_202609.assert_nonblank_key(p_bdm_stage_schema, 'bdm_stage_schema');
    PERFORM migration_clean_bdm_tmp_202609.assert_nonblank_key(p_tmp_stage_schema, 'tmp_stage_schema');
    PERFORM migration_clean_bdm_tmp_202609.assert_nonblank_key(p_bdm_snapshot_label, 'bdm_snapshot_label');
    PERFORM migration_clean_bdm_tmp_202609.assert_nonblank_key(p_tmp_snapshot_label, 'tmp_snapshot_label');
    PERFORM migration_clean_bdm_tmp_202609.assert_nonblank_key(p_started_by, 'started_by');
    PERFORM migration_clean_bdm_tmp_202609.assert_sha256(p_config_sha256, 'config_sha256');
    PERFORM migration_clean_bdm_tmp_202609.assert_sha256(p_baseline_schema_sha256, 'baseline_schema_sha256');
    PERFORM migration_clean_bdm_tmp_202609.assert_sha256(p_baseline_reference_sha256, 'baseline_reference_sha256');
    PERFORM migration_clean_bdm_tmp_202609.assert_sha256(p_bdm_snapshot_sha256, 'bdm_snapshot_sha256');
    PERFORM migration_clean_bdm_tmp_202609.assert_sha256(p_tmp_snapshot_sha256, 'tmp_snapshot_sha256');
    PERFORM migration_clean_bdm_tmp_202609.assert_audit_payload_safe(p_run_metadata, 'begin_import_run.run_metadata');

    IF p_phase NOT IN ('master', 'sales', 'reconciliation') THEN
        RAISE EXCEPTION 'phase % tidak diizinkan', p_phase;
    END IF;
    IF p_bdm_stage_run_id IS NULL OR p_bdm_stage_run_id <= 0
       OR p_tmp_stage_run_id IS NULL OR p_tmp_stage_run_id <= 0 THEN
        RAISE EXCEPTION 'stage_run_id BDM dan TMP harus positif';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM migration_clean_bdm_tmp_202609.source_context
         WHERE source_system = 'bdm_solo_dist'
    ) OR NOT EXISTS (
        SELECT 1 FROM migration_clean_bdm_tmp_202609.source_context
         WHERE source_system = 'tmp_solo_dist'
    ) THEN
        RAISE EXCEPTION 'kedua source_context (bdm_solo_dist dan tmp_solo_dist) wajib diresolusi sebelum import run dimulai';
    END IF;

    SELECT *
      INTO v_existing
      FROM migration_clean_bdm_tmp_202609.import_run r
     WHERE r.import_key = btrim(p_import_key);

    IF FOUND THEN
        IF ROW(
            v_existing.pipeline_version, v_existing.phase,
            v_existing.config_sha256, v_existing.baseline_schema_sha256, v_existing.baseline_reference_sha256,
            v_existing.bdm_stage_schema, v_existing.bdm_stage_run_id,
            v_existing.bdm_snapshot_label, v_existing.bdm_snapshot_sha256,
            v_existing.tmp_stage_schema, v_existing.tmp_stage_run_id,
            v_existing.tmp_snapshot_label, v_existing.tmp_snapshot_sha256,
            v_existing.run_metadata
        ) IS DISTINCT FROM ROW(
            btrim(p_pipeline_version), btrim(p_phase),
            lower(btrim(p_config_sha256)), lower(btrim(p_baseline_schema_sha256)), lower(btrim(p_baseline_reference_sha256)),
            btrim(p_bdm_stage_schema), p_bdm_stage_run_id,
            btrim(p_bdm_snapshot_label), lower(btrim(p_bdm_snapshot_sha256)),
            btrim(p_tmp_stage_schema), p_tmp_stage_run_id,
            btrim(p_tmp_snapshot_label), lower(btrim(p_tmp_snapshot_sha256)),
            p_run_metadata
        ) THEN
            RAISE EXCEPTION
                'import_key % sudah dipakai dengan fingerprint sumber/config berbeda; buat key baru setelah sumber difreeze ulang',
                p_import_key;
        END IF;
        RETURN v_existing.id;
    END IF;

    INSERT INTO migration_clean_bdm_tmp_202609.import_run (
        import_key, pipeline_version, phase,
        config_sha256, baseline_schema_sha256, baseline_reference_sha256,
        bdm_stage_schema, bdm_stage_run_id, bdm_snapshot_label, bdm_snapshot_sha256,
        tmp_stage_schema, tmp_stage_run_id, tmp_snapshot_label, tmp_snapshot_sha256,
        run_metadata, started_by
    ) VALUES (
        btrim(p_import_key), btrim(p_pipeline_version), btrim(p_phase),
        lower(btrim(p_config_sha256)), lower(btrim(p_baseline_schema_sha256)), lower(btrim(p_baseline_reference_sha256)),
        btrim(p_bdm_stage_schema), p_bdm_stage_run_id, btrim(p_bdm_snapshot_label), lower(btrim(p_bdm_snapshot_sha256)),
        btrim(p_tmp_stage_schema), p_tmp_stage_run_id, btrim(p_tmp_snapshot_label), lower(btrim(p_tmp_snapshot_sha256)),
        p_run_metadata, btrim(p_started_by)
    )
    RETURNING id INTO v_id;

    RETURN v_id;
END;
$$;

CREATE FUNCTION migration_clean_bdm_tmp_202609.assert_open_import_run(p_import_run_id bigint)
RETURNS void
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog
AS $$
DECLARE
    v_status text;
BEGIN
    SELECT status INTO v_status
      FROM migration_clean_bdm_tmp_202609.import_run
     WHERE id = p_import_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'import_run % tidak ditemukan', p_import_run_id;
    END IF;
    IF v_status <> 'started' THEN
        RAISE EXCEPTION 'import_run % berstatus %, mapping hanya boleh ditulis ketika started', p_import_run_id, v_status;
    END IF;
END;
$$;

CREATE TABLE migration_clean_bdm_tmp_202609.principal_source_map (
    import_run_id bigint NOT NULL
        REFERENCES migration_clean_bdm_tmp_202609.import_run(id) ON DELETE RESTRICT,
    source_system text NOT NULL
        REFERENCES migration_clean_bdm_tmp_202609.source_context(source_system) ON DELETE RESTRICT,
    source_table text NOT NULL,
    source_stage_schema text NOT NULL,
    source_stage_run_id bigint NOT NULL CHECK (source_stage_run_id > 0),
    source_staging_id bigint NOT NULL,
    source_row_hash text NOT NULL,
    source_principal_code text NOT NULL,
    source_principal_code_norm text NOT NULL,
    id_principal integer NOT NULL REFERENCES public.principal(id) ON DELETE RESTRICT,
    mapping_method text NOT NULL CHECK (mapping_method = 'source_created'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_system, source_principal_code_norm),
    CHECK (btrim(source_table) <> ''),
    CHECK (btrim(source_stage_schema) <> ''),
    CHECK (lower(source_row_hash) ~ '^[0-9a-f]{64}$'),
    CHECK (source_principal_code_norm = migration_clean_bdm_tmp_202609.norm_migration_key(source_principal_code)),
    CHECK (source_principal_code_norm <> ''),
    UNIQUE (source_system, source_table, source_stage_schema, source_staging_id),
    UNIQUE (id_principal)
);

CREATE INDEX idx_clean_principal_map_run
    ON migration_clean_bdm_tmp_202609.principal_source_map (import_run_id);

CREATE TABLE migration_clean_bdm_tmp_202609.customer_source_map (
    import_run_id bigint NOT NULL
        REFERENCES migration_clean_bdm_tmp_202609.import_run(id) ON DELETE RESTRICT,
    source_system text NOT NULL
        REFERENCES migration_clean_bdm_tmp_202609.source_context(source_system) ON DELETE RESTRICT,
    source_table text NOT NULL,
    source_stage_schema text NOT NULL,
    source_stage_run_id bigint NOT NULL CHECK (source_stage_run_id > 0),
    source_staging_id bigint NOT NULL,
    source_row_hash text NOT NULL,
    source_customer_code text NOT NULL,
    source_customer_code_norm text NOT NULL,
    source_store_name text NOT NULL,
    source_store_name_norm text NOT NULL,
    id_customer integer NOT NULL REFERENCES public.customer(id) ON DELETE RESTRICT,
    mapping_method text NOT NULL CHECK (
        mapping_method IN ('tmp_created', 'bdm_shared_exact', 'bdm_created')
    ),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_system, source_customer_code_norm),
    CHECK (btrim(source_table) <> ''),
    CHECK (btrim(source_stage_schema) <> ''),
    CHECK (lower(source_row_hash) ~ '^[0-9a-f]{64}$'),
    CHECK (source_customer_code_norm = migration_clean_bdm_tmp_202609.norm_migration_key(source_customer_code)),
    CHECK (source_customer_code_norm <> ''),
    CHECK (source_store_name_norm = migration_clean_bdm_tmp_202609.norm_migration_key(source_store_name)),
    CHECK (source_store_name_norm <> ''),
    CHECK (
        (source_system = 'tmp_solo_dist' AND mapping_method = 'tmp_created')
        OR (source_system = 'bdm_solo_dist' AND mapping_method IN ('bdm_shared_exact', 'bdm_created'))
    ),
    UNIQUE (source_system, source_table, source_stage_schema, source_staging_id)
);

CREATE INDEX idx_clean_customer_map_run
    ON migration_clean_bdm_tmp_202609.customer_source_map (import_run_id);

CREATE INDEX idx_clean_customer_map_source_name
    ON migration_clean_bdm_tmp_202609.customer_source_map
       (source_system, source_customer_code_norm, source_store_name_norm);

CREATE INDEX idx_clean_customer_map_target_customer
    ON migration_clean_bdm_tmp_202609.customer_source_map (id_customer);

-- A created target customer cannot silently represent two independently
-- created source identities.  BDM sharing is permitted only by the trigger
-- below after it proves an exact TMP code + store-name match.
CREATE UNIQUE INDEX uq_clean_customer_created_target
    ON migration_clean_bdm_tmp_202609.customer_source_map (id_customer)
    WHERE mapping_method IN ('tmp_created', 'bdm_created');

CREATE TABLE migration_clean_bdm_tmp_202609.sales_source_map (
    import_run_id bigint NOT NULL
        REFERENCES migration_clean_bdm_tmp_202609.import_run(id) ON DELETE RESTRICT,
    source_system text NOT NULL
        REFERENCES migration_clean_bdm_tmp_202609.source_context(source_system) ON DELETE RESTRICT,
    source_table text NOT NULL,
    source_stage_schema text NOT NULL,
    source_stage_run_id bigint NOT NULL CHECK (source_stage_run_id > 0),
    source_staging_id bigint NOT NULL,
    source_row_hash text NOT NULL,
    source_principal_code text NOT NULL,
    source_principal_code_norm text NOT NULL,
    source_sales_code text NOT NULL,
    source_sales_code_norm text NOT NULL,
    id_sales integer NOT NULL REFERENCES public.sales(id) ON DELETE RESTRICT,
    id_user integer NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    mapping_method text NOT NULL CHECK (mapping_method = 'source_created'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_system, source_principal_code_norm, source_sales_code_norm),
    FOREIGN KEY (source_system, source_principal_code_norm)
        REFERENCES migration_clean_bdm_tmp_202609.principal_source_map(
            source_system, source_principal_code_norm
        ) ON DELETE RESTRICT,
    CHECK (btrim(source_table) <> ''),
    CHECK (btrim(source_stage_schema) <> ''),
    CHECK (lower(source_row_hash) ~ '^[0-9a-f]{64}$'),
    CHECK (source_principal_code_norm = migration_clean_bdm_tmp_202609.norm_migration_key(source_principal_code)),
    CHECK (source_principal_code_norm <> ''),
    CHECK (source_sales_code_norm = migration_clean_bdm_tmp_202609.norm_migration_key(source_sales_code)),
    CHECK (source_sales_code_norm <> ''),
    UNIQUE (source_system, source_table, source_stage_schema, source_staging_id),
    -- One target sales identity cannot be claimed by two source identities.
    -- A user is deliberately NOT unique here: one ERP user can legitimately
    -- own separate sales/principal assignments.
    UNIQUE (id_sales)
);

CREATE INDEX idx_clean_sales_map_run
    ON migration_clean_bdm_tmp_202609.sales_source_map (import_run_id);

CREATE INDEX idx_clean_sales_map_principal
    ON migration_clean_bdm_tmp_202609.sales_source_map
       (source_system, source_principal_code_norm);

CREATE INDEX idx_clean_sales_map_target_user
    ON migration_clean_bdm_tmp_202609.sales_source_map (id_user);

CREATE TABLE migration_clean_bdm_tmp_202609.product_source_map (
    import_run_id bigint NOT NULL
        REFERENCES migration_clean_bdm_tmp_202609.import_run(id) ON DELETE RESTRICT,
    source_system text NOT NULL
        REFERENCES migration_clean_bdm_tmp_202609.source_context(source_system) ON DELETE RESTRICT,
    source_table text NOT NULL,
    source_stage_schema text NOT NULL,
    source_stage_run_id bigint NOT NULL CHECK (source_stage_run_id > 0),
    source_staging_id bigint NOT NULL,
    source_row_hash text NOT NULL,
    source_principal_code text NOT NULL,
    source_principal_code_norm text NOT NULL,
    source_sku text NOT NULL,
    source_sku_norm text NOT NULL,
    id_produk bigint NOT NULL REFERENCES public.produk(id) ON DELETE RESTRICT,
    mapping_method text NOT NULL CHECK (mapping_method = 'source_created'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_system, source_principal_code_norm, source_sku_norm),
    FOREIGN KEY (source_system, source_principal_code_norm)
        REFERENCES migration_clean_bdm_tmp_202609.principal_source_map(
            source_system, source_principal_code_norm
        ) ON DELETE RESTRICT,
    CHECK (btrim(source_table) <> ''),
    CHECK (btrim(source_stage_schema) <> ''),
    CHECK (lower(source_row_hash) ~ '^[0-9a-f]{64}$'),
    CHECK (source_principal_code_norm = migration_clean_bdm_tmp_202609.norm_migration_key(source_principal_code)),
    CHECK (source_principal_code_norm <> ''),
    CHECK (source_sku_norm = migration_clean_bdm_tmp_202609.norm_migration_key(source_sku)),
    CHECK (source_sku_norm <> ''),
    UNIQUE (source_system, source_table, source_stage_schema, source_staging_id),
    UNIQUE (id_produk)
);

CREATE INDEX idx_clean_product_map_run
    ON migration_clean_bdm_tmp_202609.product_source_map (import_run_id);

CREATE INDEX idx_clean_product_map_principal
    ON migration_clean_bdm_tmp_202609.product_source_map
       (source_system, source_principal_code_norm);

CREATE TABLE migration_clean_bdm_tmp_202609.product_uom_source_map (
    import_run_id bigint NOT NULL
        REFERENCES migration_clean_bdm_tmp_202609.import_run(id) ON DELETE RESTRICT,
    source_system text NOT NULL
        REFERENCES migration_clean_bdm_tmp_202609.source_context(source_system) ON DELETE RESTRICT,
    source_table text NOT NULL,
    source_stage_schema text NOT NULL,
    source_stage_run_id bigint NOT NULL CHECK (source_stage_run_id > 0),
    source_staging_id bigint NOT NULL,
    source_row_hash text NOT NULL,
    source_principal_code text NOT NULL,
    source_principal_code_norm text NOT NULL,
    source_sku text NOT NULL,
    source_sku_norm text NOT NULL,
    source_uom_code text NOT NULL,
    source_uom_code_norm text NOT NULL,
    source_uom_level smallint NOT NULL CHECK (source_uom_level IN (1, 2, 3)),
    source_factor integer NOT NULL CHECK (source_factor > 0),
    id_produk bigint NOT NULL REFERENCES public.produk(id) ON DELETE RESTRICT,
    id_produk_uom integer NOT NULL REFERENCES public.produk_uom(id) ON DELETE RESTRICT,
    mapping_method text NOT NULL CHECK (mapping_method = 'source_created'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (
        source_system, source_principal_code_norm, source_sku_norm,
        source_uom_code_norm, source_uom_level, source_factor
    ),
    FOREIGN KEY (source_system, source_principal_code_norm, source_sku_norm)
        REFERENCES migration_clean_bdm_tmp_202609.product_source_map(
            source_system, source_principal_code_norm, source_sku_norm
        ) ON DELETE RESTRICT,
    CHECK (btrim(source_table) <> ''),
    CHECK (btrim(source_stage_schema) <> ''),
    CHECK (lower(source_row_hash) ~ '^[0-9a-f]{64}$'),
    CHECK (source_principal_code_norm = migration_clean_bdm_tmp_202609.norm_migration_key(source_principal_code)),
    CHECK (source_principal_code_norm <> ''),
    CHECK (source_sku_norm = migration_clean_bdm_tmp_202609.norm_migration_key(source_sku)),
    CHECK (source_sku_norm <> ''),
    CHECK (source_uom_code_norm = migration_clean_bdm_tmp_202609.norm_migration_key(source_uom_code)),
    CHECK (source_uom_code_norm <> ''),
    UNIQUE (source_system, source_table, source_stage_schema, source_staging_id),
    UNIQUE (id_produk_uom)
);

CREATE INDEX idx_clean_product_uom_map_run
    ON migration_clean_bdm_tmp_202609.product_uom_source_map (import_run_id);

CREATE INDEX idx_clean_product_uom_map_product
    ON migration_clean_bdm_tmp_202609.product_uom_source_map
       (source_system, source_principal_code_norm, source_sku_norm);

CREATE INDEX idx_clean_product_uom_map_target_product
    ON migration_clean_bdm_tmp_202609.product_uom_source_map (id_produk);

CREATE TABLE migration_clean_bdm_tmp_202609.sales_document_map (
    import_run_id bigint NOT NULL
        REFERENCES migration_clean_bdm_tmp_202609.import_run(id) ON DELETE RESTRICT,
    source_system text NOT NULL
        REFERENCES migration_clean_bdm_tmp_202609.source_context(source_system) ON DELETE RESTRICT,
    -- Android headers remain in import_hold until a separate source-qualified
    -- duplicate policy is approved.  Only the canonical HJualSM family can
    -- enter the clean sales registry.
    source_header_table text NOT NULL CHECK (source_header_table = 'HJualSM'),
    source_stage_schema text NOT NULL,
    source_stage_run_id bigint NOT NULL CHECK (source_stage_run_id > 0),
    source_staging_id bigint NOT NULL,
    source_row_hash text NOT NULL,
    source_nota text NOT NULL,
    source_nota_norm text NOT NULL,
    source_principal_code text NOT NULL,
    source_principal_code_norm text NOT NULL,
    id_sales_order integer NOT NULL REFERENCES public.sales_order(id) ON DELETE RESTRICT,
    id_faktur integer NOT NULL REFERENCES public.faktur(id) ON DELETE RESTRICT,
    id_faktur_detail integer NOT NULL REFERENCES public.faktur_detail(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_system, source_header_table, source_nota_norm),
    FOREIGN KEY (source_system, source_principal_code_norm)
        REFERENCES migration_clean_bdm_tmp_202609.principal_source_map(
            source_system, source_principal_code_norm
        ) ON DELETE RESTRICT,
    CHECK (btrim(source_stage_schema) <> ''),
    CHECK (lower(source_row_hash) ~ '^[0-9a-f]{64}$'),
    CHECK (source_nota_norm = migration_clean_bdm_tmp_202609.norm_migration_key(source_nota)),
    CHECK (source_nota_norm <> ''),
    CHECK (source_principal_code_norm = migration_clean_bdm_tmp_202609.norm_migration_key(source_principal_code)),
    CHECK (source_principal_code_norm <> ''),
    UNIQUE (source_system, source_header_table, source_stage_schema, source_staging_id),
    UNIQUE (id_sales_order),
    UNIQUE (id_faktur),
    UNIQUE (id_faktur_detail)
);

CREATE INDEX idx_clean_sales_document_map_run
    ON migration_clean_bdm_tmp_202609.sales_document_map (import_run_id);

CREATE INDEX idx_clean_sales_document_map_principal
    ON migration_clean_bdm_tmp_202609.sales_document_map
       (source_system, source_principal_code_norm);

CREATE TABLE migration_clean_bdm_tmp_202609.sales_document_line_map (
    import_run_id bigint NOT NULL
        REFERENCES migration_clean_bdm_tmp_202609.import_run(id) ON DELETE RESTRICT,
    source_system text NOT NULL
        REFERENCES migration_clean_bdm_tmp_202609.source_context(source_system) ON DELETE RESTRICT,
    source_header_table text NOT NULL CHECK (source_header_table = 'HJualSM'),
    source_line_table text NOT NULL CHECK (source_line_table = 'DJualSM'),
    source_stage_schema text NOT NULL,
    source_stage_run_id bigint NOT NULL CHECK (source_stage_run_id > 0),
    source_staging_id bigint NOT NULL,
    source_row_hash text NOT NULL,
    source_nota text NOT NULL,
    source_nota_norm text NOT NULL,
    source_urut text NOT NULL,
    source_urut_norm text NOT NULL,
    source_principal_code text NOT NULL,
    source_principal_code_norm text NOT NULL,
    source_sku text NOT NULL,
    source_sku_norm text NOT NULL,
    source_uom_code text NOT NULL,
    source_uom_code_norm text NOT NULL,
    source_uom_level smallint NOT NULL CHECK (source_uom_level IN (1, 2, 3)),
    source_factor integer NOT NULL CHECK (source_factor > 0),
    id_sales_order_detail integer NOT NULL
        REFERENCES public.sales_order_detail(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_system, source_header_table, source_nota_norm, source_urut_norm),
    FOREIGN KEY (source_system, source_header_table, source_nota_norm)
        REFERENCES migration_clean_bdm_tmp_202609.sales_document_map(
            source_system, source_header_table, source_nota_norm
        ) ON DELETE RESTRICT,
    FOREIGN KEY (
        source_system, source_principal_code_norm, source_sku_norm,
        source_uom_code_norm, source_uom_level, source_factor
    ) REFERENCES migration_clean_bdm_tmp_202609.product_uom_source_map(
        source_system, source_principal_code_norm, source_sku_norm,
        source_uom_code_norm, source_uom_level, source_factor
    ) ON DELETE RESTRICT,
    CHECK (btrim(source_stage_schema) <> ''),
    CHECK (lower(source_row_hash) ~ '^[0-9a-f]{64}$'),
    CHECK (source_nota_norm = migration_clean_bdm_tmp_202609.norm_migration_key(source_nota)),
    CHECK (source_nota_norm <> ''),
    CHECK (source_urut_norm = migration_clean_bdm_tmp_202609.norm_migration_key(source_urut)),
    CHECK (source_urut_norm <> ''),
    CHECK (source_principal_code_norm = migration_clean_bdm_tmp_202609.norm_migration_key(source_principal_code)),
    CHECK (source_principal_code_norm <> ''),
    CHECK (source_sku_norm = migration_clean_bdm_tmp_202609.norm_migration_key(source_sku)),
    CHECK (source_sku_norm <> ''),
    CHECK (source_uom_code_norm = migration_clean_bdm_tmp_202609.norm_migration_key(source_uom_code)),
    CHECK (source_uom_code_norm <> ''),
    UNIQUE (source_system, source_line_table, source_stage_schema, source_staging_id),
    UNIQUE (id_sales_order_detail)
);

CREATE INDEX idx_clean_sales_document_line_map_run
    ON migration_clean_bdm_tmp_202609.sales_document_line_map (import_run_id);

CREATE INDEX idx_clean_sales_document_line_map_product
    ON migration_clean_bdm_tmp_202609.sales_document_line_map
       (source_system, source_principal_code_norm, source_sku_norm);

CREATE INDEX idx_clean_sales_document_line_map_uom
    ON migration_clean_bdm_tmp_202609.sales_document_line_map (
        source_system, source_principal_code_norm, source_sku_norm,
        source_uom_code_norm, source_uom_level, source_factor
    );

CREATE TABLE migration_clean_bdm_tmp_202609.import_hold (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    import_run_id bigint NOT NULL
        REFERENCES migration_clean_bdm_tmp_202609.import_run(id) ON DELETE RESTRICT,
    phase text NOT NULL CHECK (phase IN ('master', 'sales', 'reconciliation')),
    source_system text NOT NULL
        REFERENCES migration_clean_bdm_tmp_202609.source_context(source_system) ON DELETE RESTRICT,
    source_table text NOT NULL,
    source_stage_schema text NOT NULL,
    source_stage_run_id bigint NOT NULL CHECK (source_stage_run_id > 0),
    source_staging_id bigint NOT NULL,
    source_identity_sha256 text NOT NULL,
    source_row_hash text NOT NULL,
    source_key jsonb NOT NULL,
    source_nota text,
    source_nota_norm text,
    source_urut text,
    source_urut_norm text,
    hold_reason text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    resolution_status text NOT NULL DEFAULT 'open'
        CHECK (resolution_status IN ('open', 'reviewed', 'skipped', 'resolved')),
    reviewed_by text,
    resolution_note text,
    occurrence_count integer NOT NULL DEFAULT 1 CHECK (occurrence_count > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    CHECK (btrim(source_table) <> ''),
    CHECK (btrim(source_stage_schema) <> ''),
    CHECK (lower(source_identity_sha256) ~ '^[0-9a-f]{64}$'),
    CHECK (lower(source_row_hash) ~ '^[0-9a-f]{64}$'),
    CHECK (jsonb_typeof(source_key) = 'object'),
    CHECK (jsonb_typeof(details) = 'object'),
    CHECK (
        (source_nota IS NULL AND source_nota_norm IS NULL)
        OR (
            source_nota IS NOT NULL
            AND source_nota_norm = migration_clean_bdm_tmp_202609.norm_migration_key(source_nota)
            AND source_nota_norm <> ''
        )
    ),
    CHECK (
        (source_urut IS NULL AND source_urut_norm IS NULL)
        OR (
            source_urut IS NOT NULL
            AND source_urut_norm = migration_clean_bdm_tmp_202609.norm_migration_key(source_urut)
            AND source_urut_norm <> ''
        )
    ),
    CHECK (
        (resolution_status IN ('open', 'reviewed') AND resolved_at IS NULL)
        OR (resolution_status IN ('skipped', 'resolved') AND resolved_at IS NOT NULL)
    ),
    CHECK (
        resolution_status NOT IN ('skipped', 'resolved')
        OR (reviewed_by IS NOT NULL AND btrim(reviewed_by) <> ''
            AND resolution_note IS NOT NULL AND btrim(resolution_note) <> '')
    ),
    UNIQUE (import_run_id, phase, source_system, source_table, source_identity_sha256, hold_reason)
);

CREATE INDEX idx_clean_import_hold_run_phase_reason
    ON migration_clean_bdm_tmp_202609.import_hold (import_run_id, phase, hold_reason);

CREATE INDEX idx_clean_import_hold_source_document
    ON migration_clean_bdm_tmp_202609.import_hold
       (source_system, source_table, source_nota_norm, source_urut_norm);

CREATE TABLE migration_clean_bdm_tmp_202609.reconciliation_result (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    import_run_id bigint NOT NULL
        REFERENCES migration_clean_bdm_tmp_202609.import_run(id) ON DELETE RESTRICT,
    check_name text NOT NULL,
    scope_sha256 text NOT NULL,
    scope jsonb NOT NULL DEFAULT '{}'::jsonb,
    expected_value jsonb NOT NULL,
    actual_value jsonb NOT NULL,
    severity text NOT NULL CHECK (severity IN ('fatal', 'error', 'warning', 'info')),
    status text NOT NULL CHECK (status IN ('pass', 'fail', 'held', 'not_applicable')),
    fingerprint_sha256 text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    observed_at timestamptz NOT NULL DEFAULT now(),
    CHECK (btrim(check_name) <> ''),
    CHECK (lower(scope_sha256) ~ '^[0-9a-f]{64}$'),
    CHECK (lower(fingerprint_sha256) ~ '^[0-9a-f]{64}$'),
    CHECK (jsonb_typeof(scope) = 'object'),
    CHECK (jsonb_typeof(expected_value) IN ('object', 'array', 'number', 'string', 'boolean', 'null')),
    CHECK (jsonb_typeof(actual_value) IN ('object', 'array', 'number', 'string', 'boolean', 'null')),
    CHECK (jsonb_typeof(details) = 'object'),
    UNIQUE (import_run_id, check_name, scope_sha256, fingerprint_sha256)
);

CREATE INDEX idx_clean_reconciliation_run_severity
    ON migration_clean_bdm_tmp_202609.reconciliation_result
       (import_run_id, severity, status, check_name);

CREATE FUNCTION migration_clean_bdm_tmp_202609.assert_principal_source_map_scope()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    v_target_company integer;
    v_expected_company integer;
BEGIN
    PERFORM migration_clean_bdm_tmp_202609.assert_open_import_run(NEW.import_run_id);
    SELECT p.id_perusahaan, sc.target_company_id
      INTO v_target_company, v_expected_company
      FROM public.principal p
      JOIN migration_clean_bdm_tmp_202609.source_context sc
        ON sc.source_system = NEW.source_system
     WHERE p.id = NEW.id_principal;
    IF NOT FOUND OR v_target_company IS DISTINCT FROM v_expected_company THEN
        RAISE EXCEPTION 'principal % tidak berada pada perusahaan context source %', NEW.id_principal, NEW.source_system;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION migration_clean_bdm_tmp_202609.assert_customer_source_map_scope()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    v_target_branch integer;
    v_expected_branch integer;
    v_tmp_customer_id integer;
BEGIN
    PERFORM migration_clean_bdm_tmp_202609.assert_open_import_run(NEW.import_run_id);
    SELECT c.id_cabang, sc.target_branch_id
      INTO v_target_branch, v_expected_branch
      FROM public.customer c
      JOIN migration_clean_bdm_tmp_202609.source_context sc
        ON sc.source_system = NEW.source_system
     WHERE c.id = NEW.id_customer;
    IF NOT FOUND OR v_target_branch IS DISTINCT FROM v_expected_branch THEN
        RAISE EXCEPTION 'customer % tidak berada pada cabang context source %', NEW.id_customer, NEW.source_system;
    END IF;

    IF NEW.mapping_method = 'bdm_shared_exact' THEN
        SELECT cm.id_customer
          INTO v_tmp_customer_id
          FROM migration_clean_bdm_tmp_202609.customer_source_map cm
         WHERE cm.source_system = 'tmp_solo_dist'
           AND cm.source_customer_code_norm = NEW.source_customer_code_norm
           AND cm.source_store_name_norm = NEW.source_store_name_norm
           AND cm.mapping_method = 'tmp_created';
        IF NOT FOUND OR v_tmp_customer_id IS DISTINCT FROM NEW.id_customer THEN
            RAISE EXCEPTION
                'customer BDM shared_exact harus mempunyai tepat satu customer TMP dengan kode dan nama toko normalisasi yang sama';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION migration_clean_bdm_tmp_202609.assert_sales_source_map_scope()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    v_sales_principal integer;
    v_sales_user integer;
    v_expected_principal integer;
    v_user_company integer;
    v_user_branch integer;
    v_expected_company integer;
    v_expected_branch integer;
BEGIN
    PERFORM migration_clean_bdm_tmp_202609.assert_open_import_run(NEW.import_run_id);
    SELECT s.id_principal, s.id_user, pm.id_principal,
           u.id_perusahaan, u.id_cabang, sc.target_company_id, sc.target_branch_id
      INTO v_sales_principal, v_sales_user, v_expected_principal,
           v_user_company, v_user_branch, v_expected_company, v_expected_branch
      FROM public.sales s
      JOIN public.users u ON u.id = s.id_user
      JOIN migration_clean_bdm_tmp_202609.principal_source_map pm
        ON pm.source_system = NEW.source_system
       AND pm.source_principal_code_norm = NEW.source_principal_code_norm
      JOIN migration_clean_bdm_tmp_202609.source_context sc
        ON sc.source_system = NEW.source_system
     WHERE s.id = NEW.id_sales;
    IF NOT FOUND
       OR v_sales_principal IS DISTINCT FROM v_expected_principal
       OR v_sales_user IS DISTINCT FROM NEW.id_user
       OR v_user_company IS DISTINCT FROM v_expected_company
       OR v_user_branch IS DISTINCT FROM v_expected_branch THEN
        RAISE EXCEPTION
            'sales/user %/% tidak cocok dengan principal dan company/cabang context %',
            NEW.id_sales, NEW.id_user, NEW.source_system;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION migration_clean_bdm_tmp_202609.assert_product_source_map_scope()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    v_product_principal integer;
    v_expected_principal integer;
BEGIN
    PERFORM migration_clean_bdm_tmp_202609.assert_open_import_run(NEW.import_run_id);
    SELECT pr.id_principal, pm.id_principal
      INTO v_product_principal, v_expected_principal
      FROM public.produk pr
      JOIN migration_clean_bdm_tmp_202609.principal_source_map pm
        ON pm.source_system = NEW.source_system
       AND pm.source_principal_code_norm = NEW.source_principal_code_norm
     WHERE pr.id = NEW.id_produk;
    IF NOT FOUND OR v_product_principal IS DISTINCT FROM v_expected_principal THEN
        RAISE EXCEPTION 'produk % tidak cocok dengan principal source %/%',
            NEW.id_produk, NEW.source_system, NEW.source_principal_code_norm;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION migration_clean_bdm_tmp_202609.assert_product_uom_source_map_scope()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    v_uom_product bigint;
    v_map_product bigint;
    v_uom_code text;
    v_uom_level smallint;
    v_uom_factor integer;
    v_base_count integer;
    v_level2_count integer;
    v_level2_valid_count integer;
BEGIN
    PERFORM migration_clean_bdm_tmp_202609.assert_open_import_run(NEW.import_run_id);
    SELECT pu.id_produk::bigint, pm.id_produk,
           migration_clean_bdm_tmp_202609.norm_migration_key(pu.kode),
           pu.level, pu.faktor_konversi
      INTO v_uom_product, v_map_product, v_uom_code, v_uom_level, v_uom_factor
      FROM public.produk_uom pu
      JOIN migration_clean_bdm_tmp_202609.product_source_map pm
        ON pm.source_system = NEW.source_system
       AND pm.source_principal_code_norm = NEW.source_principal_code_norm
       AND pm.source_sku_norm = NEW.source_sku_norm
     WHERE pu.id = NEW.id_produk_uom;
    IF NOT FOUND
       OR v_uom_product IS DISTINCT FROM NEW.id_produk
       OR v_map_product IS DISTINCT FROM NEW.id_produk
       OR v_uom_code IS DISTINCT FROM NEW.source_uom_code_norm
       OR v_uom_level IS DISTINCT FROM NEW.source_uom_level
       OR v_uom_factor IS DISTINCT FROM NEW.source_factor THEN
        RAISE EXCEPTION 'produk_uom % tidak cocok dengan source product/UOM identity', NEW.id_produk_uom;
    END IF;

    -- A level-3 source UOM is accepted only with exactly one mapped PCS base
    -- and exactly one mathematically valid level-2 link.  No factor guessing.
    IF NEW.source_uom_level = 3 THEN
        SELECT count(*)
          INTO v_base_count
          FROM migration_clean_bdm_tmp_202609.product_uom_source_map base_map
         WHERE base_map.source_system = NEW.source_system
           AND base_map.source_principal_code_norm = NEW.source_principal_code_norm
           AND base_map.source_sku_norm = NEW.source_sku_norm
           AND base_map.source_uom_level = 1
           AND base_map.source_factor = 1
           AND base_map.id_produk = NEW.id_produk;
        IF v_base_count <> 1 THEN
            RAISE EXCEPTION 'UOM level 3 membutuhkan tepat satu map PCS level 1/faktor 1';
        END IF;

        SELECT count(*),
               count(*) FILTER (
                   WHERE pu.faktor_konversi > 1
                     AND pu.faktor_konversi < NEW.source_factor
                     AND mod(NEW.source_factor, pu.faktor_konversi) = 0
               )
          INTO v_level2_count, v_level2_valid_count
          FROM public.produk_uom pu
         WHERE pu.id_produk::bigint = NEW.id_produk
           AND pu.level = 2;
        IF v_level2_count <> 1 OR v_level2_valid_count <> 1 THEN
            RAISE EXCEPTION 'UOM level 3 membutuhkan tepat satu rantai level 2 yang membagi faktor level 3';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION migration_clean_bdm_tmp_202609.assert_sales_document_map_scope()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    v_order_branch integer;
    v_expected_branch integer;
    v_invoice_order integer;
    v_fd_invoice integer;
    v_fd_order integer;
    v_fd_principal integer;
    v_expected_principal integer;
    v_matching_fd_count integer;
BEGIN
    PERFORM migration_clean_bdm_tmp_202609.assert_open_import_run(NEW.import_run_id);
    SELECT so.id_cabang, sc.target_branch_id, f.id_sales_order,
           fd.id_faktur, fd.id_sales_order, fd.id_principal, pm.id_principal
      INTO v_order_branch, v_expected_branch, v_invoice_order,
           v_fd_invoice, v_fd_order, v_fd_principal, v_expected_principal
      FROM public.sales_order so
      JOIN public.faktur f ON f.id = NEW.id_faktur
      JOIN public.faktur_detail fd ON fd.id = NEW.id_faktur_detail
      JOIN migration_clean_bdm_tmp_202609.source_context sc
        ON sc.source_system = NEW.source_system
      JOIN migration_clean_bdm_tmp_202609.principal_source_map pm
        ON pm.source_system = NEW.source_system
       AND pm.source_principal_code_norm = NEW.source_principal_code_norm
     WHERE so.id = NEW.id_sales_order;
    IF NOT FOUND
       OR v_order_branch IS DISTINCT FROM v_expected_branch
       OR v_invoice_order IS DISTINCT FROM NEW.id_sales_order
       OR v_fd_invoice IS DISTINCT FROM NEW.id_faktur
       OR v_fd_order IS DISTINCT FROM NEW.id_sales_order
       OR v_fd_principal IS DISTINCT FROM v_expected_principal THEN
        RAISE EXCEPTION
            'sales document source %/% tidak konsisten dengan sales_order, faktur, faktur_detail, atau context',
            NEW.source_system, NEW.source_nota;
    END IF;

    SELECT count(*)
      INTO v_matching_fd_count
      FROM public.faktur_detail fd
     WHERE fd.id_faktur = NEW.id_faktur
       AND fd.id_sales_order = NEW.id_sales_order
       AND fd.id_principal = v_expected_principal;
    IF v_matching_fd_count <> 1 THEN
        RAISE EXCEPTION
            'faktur_detail untuk faktur/order/principal source harus tepat satu, ditemukan %',
            v_matching_fd_count;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION migration_clean_bdm_tmp_202609.assert_sales_document_line_map_scope()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    v_document_order integer;
    v_document_principal text;
    v_line_order integer;
    v_line_product bigint;
    v_expected_product bigint;
BEGIN
    PERFORM migration_clean_bdm_tmp_202609.assert_open_import_run(NEW.import_run_id);
    SELECT dm.id_sales_order, dm.source_principal_code_norm,
           sod.id_sales_order, sod.id_produk::bigint, pm.id_produk
      INTO v_document_order, v_document_principal,
           v_line_order, v_line_product, v_expected_product
      FROM migration_clean_bdm_tmp_202609.sales_document_map dm
      JOIN public.sales_order_detail sod ON sod.id = NEW.id_sales_order_detail
      JOIN migration_clean_bdm_tmp_202609.product_source_map pm
        ON pm.source_system = NEW.source_system
       AND pm.source_principal_code_norm = NEW.source_principal_code_norm
       AND pm.source_sku_norm = NEW.source_sku_norm
     WHERE dm.source_system = NEW.source_system
       AND dm.source_header_table = NEW.source_header_table
       AND dm.source_nota_norm = NEW.source_nota_norm;
    IF NOT FOUND
       OR v_document_principal IS DISTINCT FROM NEW.source_principal_code_norm
       OR v_document_order IS DISTINCT FROM v_line_order
       OR v_line_product IS DISTINCT FROM v_expected_product THEN
        RAISE EXCEPTION
            'sales_order_detail % tidak konsisten dengan dokumen/principal/produk source yang sama',
            NEW.id_sales_order_detail;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION migration_clean_bdm_tmp_202609.assert_import_hold_write()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    PERFORM migration_clean_bdm_tmp_202609.assert_audit_payload_safe(NEW.source_key, 'import_hold.source_key');
    PERFORM migration_clean_bdm_tmp_202609.assert_audit_payload_safe(NEW.details, 'import_hold.details');

    IF TG_OP = 'INSERT' THEN
        RETURN NEW;
    END IF;

    IF ROW(
        NEW.import_run_id, NEW.phase, NEW.source_system, NEW.source_table,
        NEW.source_stage_schema, NEW.source_stage_run_id, NEW.source_staging_id,
        NEW.source_identity_sha256, NEW.source_row_hash, NEW.source_key,
        NEW.source_nota, NEW.source_nota_norm, NEW.source_urut, NEW.source_urut_norm,
        NEW.hold_reason, NEW.details, NEW.created_at
    ) IS DISTINCT FROM ROW(
        OLD.import_run_id, OLD.phase, OLD.source_system, OLD.source_table,
        OLD.source_stage_schema, OLD.source_stage_run_id, OLD.source_staging_id,
        OLD.source_identity_sha256, OLD.source_row_hash, OLD.source_key,
        OLD.source_nota, OLD.source_nota_norm, OLD.source_urut, OLD.source_urut_norm,
        OLD.hold_reason, OLD.details, OLD.created_at
    ) THEN
        RAISE EXCEPTION 'evidence import_hold % bersifat immutable', OLD.id;
    END IF;
    IF OLD.resolution_status IN ('skipped', 'resolved')
       AND NEW.resolution_status IS DISTINCT FROM OLD.resolution_status THEN
        RAISE EXCEPTION 'hold % telah final dan tidak boleh dibuka ulang; buat run baru bila sumber berubah', OLD.id;
    END IF;
    IF NEW.resolution_status IN ('skipped', 'resolved')
       AND OLD.resolution_status NOT IN ('skipped', 'resolved') THEN
        NEW.resolved_at := now();
    END IF;
    IF NEW.occurrence_count < OLD.occurrence_count THEN
        RAISE EXCEPTION 'occurrence_count hold % tidak boleh berkurang', OLD.id;
    END IF;
    NEW.last_seen_at := now();
    RETURN NEW;
END;
$$;

CREATE FUNCTION migration_clean_bdm_tmp_202609.assert_reconciliation_result_write()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    PERFORM migration_clean_bdm_tmp_202609.assert_audit_payload_safe(NEW.scope, 'reconciliation_result.scope');
    PERFORM migration_clean_bdm_tmp_202609.assert_audit_payload_safe(NEW.details, 'reconciliation_result.details');
    RETURN NEW;
END;
$$;

CREATE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_delete()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION 'DELETE tidak diizinkan pada registry clean import (%). Buat database target baru untuk run baru.', TG_TABLE_NAME;
END;
$$;

CREATE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_update()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION
        'UPDATE tidak diizinkan pada registry provenance (%). Buat import_run atau database target baru untuk evidence yang berubah.',
        TG_TABLE_NAME;
END;
$$;

CREATE TRIGGER principal_source_map_scope_guard
BEFORE INSERT OR UPDATE ON migration_clean_bdm_tmp_202609.principal_source_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.assert_principal_source_map_scope();

CREATE TRIGGER customer_source_map_scope_guard
BEFORE INSERT OR UPDATE ON migration_clean_bdm_tmp_202609.customer_source_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.assert_customer_source_map_scope();

CREATE TRIGGER sales_source_map_scope_guard
BEFORE INSERT OR UPDATE ON migration_clean_bdm_tmp_202609.sales_source_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.assert_sales_source_map_scope();

CREATE TRIGGER product_source_map_scope_guard
BEFORE INSERT OR UPDATE ON migration_clean_bdm_tmp_202609.product_source_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.assert_product_source_map_scope();

CREATE TRIGGER product_uom_source_map_scope_guard
BEFORE INSERT OR UPDATE ON migration_clean_bdm_tmp_202609.product_uom_source_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.assert_product_uom_source_map_scope();

CREATE TRIGGER sales_document_map_scope_guard
BEFORE INSERT OR UPDATE ON migration_clean_bdm_tmp_202609.sales_document_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.assert_sales_document_map_scope();

CREATE TRIGGER sales_document_line_map_scope_guard
BEFORE INSERT OR UPDATE ON migration_clean_bdm_tmp_202609.sales_document_line_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.assert_sales_document_line_map_scope();

CREATE TRIGGER import_hold_write_guard
BEFORE INSERT OR UPDATE ON migration_clean_bdm_tmp_202609.import_hold
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.assert_import_hold_write();

CREATE TRIGGER reconciliation_result_write_guard
BEFORE INSERT ON migration_clean_bdm_tmp_202609.reconciliation_result
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.assert_reconciliation_result_write();

CREATE FUNCTION migration_clean_bdm_tmp_202609.record_import_hold(
    p_import_run_id bigint,
    p_phase text,
    p_source_system text,
    p_source_table text,
    p_source_stage_schema text,
    p_source_stage_run_id bigint,
    p_source_staging_id bigint,
    p_source_identity_sha256 text,
    p_source_row_hash text,
    p_source_key jsonb,
    p_hold_reason text,
    p_details jsonb DEFAULT '{}'::jsonb,
    p_source_nota text DEFAULT NULL,
    p_source_urut text DEFAULT NULL
)
RETURNS bigint
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    v_id bigint;
BEGIN
    PERFORM migration_clean_bdm_tmp_202609.assert_nonblank_key(p_phase, 'hold.phase');
    PERFORM migration_clean_bdm_tmp_202609.assert_nonblank_key(p_source_system, 'hold.source_system');
    PERFORM migration_clean_bdm_tmp_202609.assert_nonblank_key(p_source_table, 'hold.source_table');
    PERFORM migration_clean_bdm_tmp_202609.assert_nonblank_key(p_source_stage_schema, 'hold.source_stage_schema');
    PERFORM migration_clean_bdm_tmp_202609.assert_nonblank_key(p_hold_reason, 'hold.hold_reason');
    PERFORM migration_clean_bdm_tmp_202609.assert_sha256(p_source_identity_sha256, 'hold.source_identity_sha256');
    PERFORM migration_clean_bdm_tmp_202609.assert_sha256(p_source_row_hash, 'hold.source_row_hash');
    PERFORM migration_clean_bdm_tmp_202609.assert_audit_payload_safe(p_source_key, 'hold.source_key');
    PERFORM migration_clean_bdm_tmp_202609.assert_audit_payload_safe(p_details, 'hold.details');

    IF p_phase NOT IN ('master', 'sales', 'reconciliation')
       OR migration_clean_bdm_tmp_202609.norm_migration_key(p_source_system)
          NOT IN ('bdm_solo_dist', 'tmp_solo_dist')
       OR p_source_stage_run_id IS NULL OR p_source_stage_run_id <= 0
       OR p_source_staging_id IS NULL THEN
        RAISE EXCEPTION 'parameter hold tidak valid';
    END IF;

    INSERT INTO migration_clean_bdm_tmp_202609.import_hold (
        import_run_id, phase, source_system, source_table,
        source_stage_schema, source_stage_run_id, source_staging_id,
        source_identity_sha256, source_row_hash, source_key,
        source_nota, source_nota_norm, source_urut, source_urut_norm,
        hold_reason, details
    ) VALUES (
        p_import_run_id, btrim(p_phase), migration_clean_bdm_tmp_202609.norm_migration_key(p_source_system), btrim(p_source_table),
        btrim(p_source_stage_schema), p_source_stage_run_id, p_source_staging_id,
        lower(btrim(p_source_identity_sha256)), lower(btrim(p_source_row_hash)), p_source_key,
        nullif(btrim(p_source_nota), ''), nullif(migration_clean_bdm_tmp_202609.norm_migration_key(p_source_nota), ''),
        nullif(btrim(p_source_urut), ''), nullif(migration_clean_bdm_tmp_202609.norm_migration_key(p_source_urut), ''),
        btrim(p_hold_reason), p_details
    )
    ON CONFLICT (import_run_id, phase, source_system, source_table, source_identity_sha256, hold_reason)
    DO UPDATE
       SET occurrence_count = migration_clean_bdm_tmp_202609.import_hold.occurrence_count + 1,
           last_seen_at = now()
    RETURNING id INTO v_id;

    RETURN v_id;
END;
$$;

CREATE FUNCTION migration_clean_bdm_tmp_202609.record_reconciliation_result(
    p_import_run_id bigint,
    p_check_name text,
    p_scope_sha256 text,
    p_scope jsonb,
    p_expected_value jsonb,
    p_actual_value jsonb,
    p_severity text,
    p_status text,
    p_fingerprint_sha256 text,
    p_details jsonb DEFAULT '{}'::jsonb
)
RETURNS bigint
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    v_id bigint;
BEGIN
    PERFORM migration_clean_bdm_tmp_202609.assert_nonblank_key(p_check_name, 'reconciliation.check_name');
    PERFORM migration_clean_bdm_tmp_202609.assert_sha256(p_scope_sha256, 'reconciliation.scope_sha256');
    PERFORM migration_clean_bdm_tmp_202609.assert_sha256(p_fingerprint_sha256, 'reconciliation.fingerprint_sha256');
    PERFORM migration_clean_bdm_tmp_202609.assert_audit_payload_safe(p_scope, 'reconciliation.scope');
    PERFORM migration_clean_bdm_tmp_202609.assert_audit_payload_safe(p_details, 'reconciliation.details');
    IF p_expected_value IS NULL OR p_actual_value IS NULL THEN
        RAISE EXCEPTION 'expected_value dan actual_value tidak boleh NULL';
    END IF;
    IF p_severity NOT IN ('fatal', 'error', 'warning', 'info')
       OR p_status NOT IN ('pass', 'fail', 'held', 'not_applicable') THEN
        RAISE EXCEPTION 'severity/status reconciliation tidak valid';
    END IF;

    INSERT INTO migration_clean_bdm_tmp_202609.reconciliation_result (
        import_run_id, check_name, scope_sha256, scope,
        expected_value, actual_value, severity, status,
        fingerprint_sha256, details
    ) VALUES (
        p_import_run_id, btrim(p_check_name), lower(btrim(p_scope_sha256)), p_scope,
        p_expected_value, p_actual_value, p_severity, p_status,
        lower(btrim(p_fingerprint_sha256)), p_details
    )
    RETURNING id INTO v_id;
    RETURN v_id;
END;
$$;

-- Registry evidence is append-only.  A corrected source snapshot must be
-- represented by a new import run/target database, never by deleting history.
CREATE TRIGGER source_context_no_delete
BEFORE DELETE ON migration_clean_bdm_tmp_202609.source_context
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_delete();

CREATE TRIGGER principal_source_map_no_update
BEFORE UPDATE ON migration_clean_bdm_tmp_202609.principal_source_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_update();

CREATE TRIGGER customer_source_map_no_update
BEFORE UPDATE ON migration_clean_bdm_tmp_202609.customer_source_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_update();

CREATE TRIGGER sales_source_map_no_update
BEFORE UPDATE ON migration_clean_bdm_tmp_202609.sales_source_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_update();

CREATE TRIGGER product_source_map_no_update
BEFORE UPDATE ON migration_clean_bdm_tmp_202609.product_source_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_update();

CREATE TRIGGER product_uom_source_map_no_update
BEFORE UPDATE ON migration_clean_bdm_tmp_202609.product_uom_source_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_update();

CREATE TRIGGER sales_document_map_no_update
BEFORE UPDATE ON migration_clean_bdm_tmp_202609.sales_document_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_update();

CREATE TRIGGER sales_document_line_map_no_update
BEFORE UPDATE ON migration_clean_bdm_tmp_202609.sales_document_line_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_update();

CREATE TRIGGER reconciliation_result_no_update
BEFORE UPDATE ON migration_clean_bdm_tmp_202609.reconciliation_result
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_update();

CREATE TRIGGER import_run_no_delete
BEFORE DELETE ON migration_clean_bdm_tmp_202609.import_run
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_delete();

CREATE TRIGGER principal_source_map_no_delete
BEFORE DELETE ON migration_clean_bdm_tmp_202609.principal_source_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_delete();

CREATE TRIGGER customer_source_map_no_delete
BEFORE DELETE ON migration_clean_bdm_tmp_202609.customer_source_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_delete();

CREATE TRIGGER sales_source_map_no_delete
BEFORE DELETE ON migration_clean_bdm_tmp_202609.sales_source_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_delete();

CREATE TRIGGER product_source_map_no_delete
BEFORE DELETE ON migration_clean_bdm_tmp_202609.product_source_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_delete();

CREATE TRIGGER product_uom_source_map_no_delete
BEFORE DELETE ON migration_clean_bdm_tmp_202609.product_uom_source_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_delete();

CREATE TRIGGER sales_document_map_no_delete
BEFORE DELETE ON migration_clean_bdm_tmp_202609.sales_document_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_delete();

CREATE TRIGGER sales_document_line_map_no_delete
BEFORE DELETE ON migration_clean_bdm_tmp_202609.sales_document_line_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_delete();

CREATE TRIGGER import_hold_no_delete
BEFORE DELETE ON migration_clean_bdm_tmp_202609.import_hold
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_delete();

CREATE TRIGGER reconciliation_result_no_delete
BEFORE DELETE ON migration_clean_bdm_tmp_202609.reconciliation_result
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_delete();

COMMENT ON FUNCTION migration_clean_bdm_tmp_202609.resolve_source_context(text, text, text, text) IS
    'Resolve company code and globally unique branch code, then require the exact perusahaan_cabang pair. Never accepts fixed numeric IDs.';
COMMENT ON TABLE migration_clean_bdm_tmp_202609.customer_source_map IS
    'TMP customer is created first. BDM may share it only for an exact normalized source customer code AND exact normalized store name; otherwise BDM gets a source-owned target.';
COMMENT ON TABLE migration_clean_bdm_tmp_202609.sales_document_map IS
    'Canonical HJualSM/HJualSMAndroid source header provenance to sales_order, faktur, and exactly scoped faktur_detail.';
COMMENT ON TABLE migration_clean_bdm_tmp_202609.import_hold IS
    'Fail-closed ambiguity/incomplete evidence ledger. No nearest-name or MIN(id) fallback is allowed.';
COMMENT ON TABLE migration_clean_bdm_tmp_202609.reconciliation_result IS
    'Append-only dry-run/UAT evidence for counts, totals, UOM conversions, document identity, and target integrity.';

COMMIT;
