-- Additive registry extension for the BDM Solo + TMP Solo clean master import.
--
-- IMPORTANT
-- =========
-- This patch is for a NEW blue/green clean database only.  It must never be
-- run against budimas_dev, SQL Server, a template database, or an old legacy
-- registry.  It contains no SQL Server connection and does not copy business
-- data.  The only destructive-looking statement replaces an *empty* clean
-- registry's erroneous UOM uniqueness constraint with the source-UOM-aware
-- equivalent; the preflight refuses to run if that map already has rows.
--
-- Invocation example (after the base clean registry DDL, on the approved new
-- database only):
--
--   PGOPTIONS='-c migration_clean_bdm_tmp_202609.allow_ddl=acknowledge-clean-target' \
--     -c migration_clean_bdm_tmp_202609.baseline_schema_sha256=<observed-public-schema-sha> \
--     -c migration_clean_bdm_tmp_202609.baseline_reference_sha256=<observed-reference-sha>' \
--     psql -v ON_ERROR_STOP=1 -d <approved_clean_database> \
--       -f tools/migration/20260902_extend_clean_import_registry_master_maps.sql
--
-- Why this extension exists
-- =========================
-- A single frozen STOK row is the evidence for two target UOMs: level 1 PCS
-- and, where verified, level 2 CT.  The base registry had a unique key on
-- only (source_system, source_table, source_stage_schema, source_staging_id),
-- which made those two maps mutually exclusive.  This extension adds a
-- source_uom_ordinal (required to equal the source UOM level) to the identity.
-- It also adds source-qualified price and plafon maps, a clean-target
-- attestation marker, and the nullable sales-user contract needed by the
-- historical master phase.  The importer preserves only latest source
-- plafon limit/term; it records sisa_bon=0 with lock_order=1, never a guessed
-- opening AR balance.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
SELECT pg_advisory_xact_lock(hashtext('migration_clean_bdm_tmp_202609:master'));

-- Refuse an accidentally selected production/non-clean database *before*
-- taking relation locks.  The detailed preflight below repeats these checks
-- while holding the locks before it performs any DDL.
DO $$
BEGIN
    IF current_setting('migration_clean_bdm_tmp_202609.allow_ddl', true)
           IS DISTINCT FROM 'acknowledge-clean-target' THEN
        RAISE EXCEPTION
            'Registry extension ditolak: set migration_clean_bdm_tmp_202609.allow_ddl=acknowledge-clean-target pada sesi target clean';
    END IF;
    IF current_database() !~ '^budimas_clean_[a-z0-9_]{1,48}$'
       OR current_database() IN ('budimas', 'budimas_dev', 'postgres', 'template0', 'template1') THEN
        RAISE EXCEPTION
            'Registry extension ditolak untuk database "%"; gunakan database blue/green bernama budimas_clean_*',
            current_database();
    END IF;
    IF to_regnamespace('migration_clean_bdm_tmp_202609') IS NULL
       OR to_regclass('migration_clean_bdm_tmp_202609.product_uom_source_map') IS NULL THEN
        RAISE EXCEPTION 'Base clean registry 20260902 belum lengkap; jangan lock atau patch target lain';
    END IF;
END;
$$;

-- This runs before the empty-map preflight so no concurrent writer can add
-- evidence between its count and the UOM identity replacement below.  If the
-- base registry/table is missing, PostgreSQL aborts this transaction without
-- changing anything.
LOCK TABLE
    migration_clean_bdm_tmp_202609.source_context,
    migration_clean_bdm_tmp_202609.import_run,
    migration_clean_bdm_tmp_202609.principal_source_map,
    migration_clean_bdm_tmp_202609.customer_source_map,
    migration_clean_bdm_tmp_202609.sales_source_map,
    migration_clean_bdm_tmp_202609.product_source_map,
    migration_clean_bdm_tmp_202609.product_uom_source_map,
    public.principal,
    public.customer,
    public.sales,
    public.sales_detail,
    public.sales_principal_assignment,
    public.produk,
    public.produk_uom,
    public.produk_harga_jual,
    public.plafon
IN SHARE ROW EXCLUSIVE MODE;

DO $$
DECLARE
    v_count bigint;
    v_schema_sha text;
    v_reference_sha text;
BEGIN
    IF current_setting('migration_clean_bdm_tmp_202609.allow_ddl', true)
           IS DISTINCT FROM 'acknowledge-clean-target' THEN
        RAISE EXCEPTION
            'Registry extension ditolak: set migration_clean_bdm_tmp_202609.allow_ddl=acknowledge-clean-target pada sesi target clean';
    END IF;

    IF current_database() !~ '^budimas_clean_[a-z0-9_]{1,48}$'
       OR current_database() IN ('budimas', 'budimas_dev', 'postgres', 'template0', 'template1') THEN
        RAISE EXCEPTION
            'Registry extension ditolak untuk database "%"; gunakan database blue/green bernama budimas_clean_*',
            current_database();
    END IF;

    v_schema_sha := lower(btrim(coalesce(current_setting('migration_clean_bdm_tmp_202609.baseline_schema_sha256', true), '')));
    v_reference_sha := lower(btrim(coalesce(current_setting('migration_clean_bdm_tmp_202609.baseline_reference_sha256', true), '')));
    IF v_schema_sha !~ '^[0-9a-f]{64}$' OR v_reference_sha !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION
            'Registry extension memerlukan baseline_schema_sha256 dan baseline_reference_sha256 SHA-256 hasil dry-run read-only';
    END IF;

    IF to_regnamespace('migration_clean_bdm_tmp_202609') IS NULL
       OR to_regclass('migration_clean_bdm_tmp_202609.product_uom_source_map') IS NULL
       OR to_regclass('migration_clean_bdm_tmp_202609.import_run') IS NULL
       OR to_regclass('migration_clean_bdm_tmp_202609.product_source_map') IS NULL
       OR to_regclass('migration_clean_bdm_tmp_202609.customer_source_map') IS NULL
       OR to_regclass('migration_clean_bdm_tmp_202609.sales_source_map') IS NULL THEN
        RAISE EXCEPTION
            'Base clean registry 20260902 belum lengkap; jalankan base DDL lebih dahulu pada database clean';
    END IF;

    IF to_regclass('migration_clean_bdm_tmp_202609.clean_target_attestation') IS NOT NULL
       OR to_regclass('migration_clean_bdm_tmp_202609.product_price_source_map') IS NOT NULL
       OR to_regclass('migration_clean_bdm_tmp_202609.plafon_source_map') IS NOT NULL
       OR EXISTS (
           SELECT 1 FROM pg_attribute
            WHERE attrelid = 'migration_clean_bdm_tmp_202609.product_uom_source_map'::regclass
              AND attname = 'source_uom_ordinal'
              AND attnum > 0
              AND NOT attisdropped
       ) THEN
        RAISE EXCEPTION
            'Registry extension master maps sudah pernah dipasang atau database tidak berada pada state clean yang diharapkan';
    END IF;

    SELECT sum(row_count)
      INTO v_count
      FROM (
          SELECT count(*) AS row_count FROM migration_clean_bdm_tmp_202609.principal_source_map
          UNION ALL SELECT count(*) FROM migration_clean_bdm_tmp_202609.customer_source_map
          UNION ALL SELECT count(*) FROM migration_clean_bdm_tmp_202609.sales_source_map
          UNION ALL SELECT count(*) FROM migration_clean_bdm_tmp_202609.product_source_map
          UNION ALL SELECT count(*) FROM migration_clean_bdm_tmp_202609.product_uom_source_map
      ) AS source_map_counts;
    IF coalesce(v_count, 0) <> 0 THEN
        RAISE EXCEPTION
            'Registry source map sudah memiliki % baris; extension tidak boleh diterapkan pada evidence yang sudah ditulis',
            v_count;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'migration_clean_bdm_tmp_202609.product_uom_source_map'::regclass
           AND conname = 'product_uom_source_map_source_system_source_table_source_st_key'
           AND contype = 'u'
    ) THEN
        RAISE EXCEPTION
            'Unique constraint UOM base yang diharapkan tidak ditemukan; hentikan dan audit schema sebelum patch';
    END IF;

    SELECT sum(row_count)
      INTO v_count
      FROM (
          SELECT count(*) AS row_count FROM public.principal
          UNION ALL SELECT count(*) FROM public.customer
          UNION ALL SELECT count(*) FROM public.sales
          UNION ALL SELECT count(*) FROM public.produk
          UNION ALL SELECT count(*) FROM public.produk_uom
          UNION ALL SELECT count(*) FROM public.produk_harga_jual
          UNION ALL SELECT count(*) FROM public.plafon
      ) AS source_owned_master_counts;
    IF coalesce(v_count, 0) <> 0 THEN
        RAISE EXCEPTION
            'Target master clean sudah memiliki % baris source-owned; buat database clean baru, jangan patch/import sebagian',
            v_count;
    END IF;
END;
$$;

-- One source STOK row can support exactly one map for each level (PCS=1,
-- CT=2, level 3 only if a later source contract proves it).  The ordinal is
-- deliberately linked to source_uom_level so it cannot become an arbitrary
-- suffix used to bypass provenance uniqueness.
ALTER TABLE migration_clean_bdm_tmp_202609.product_uom_source_map
    ADD COLUMN source_uom_ordinal smallint NOT NULL DEFAULT 1;

ALTER TABLE migration_clean_bdm_tmp_202609.product_uom_source_map
    ADD CONSTRAINT product_uom_source_map_source_uom_ordinal_check
        CHECK (source_uom_ordinal = source_uom_level);

ALTER TABLE migration_clean_bdm_tmp_202609.product_uom_source_map
    DROP CONSTRAINT product_uom_source_map_source_system_source_table_source_st_key;

ALTER TABLE migration_clean_bdm_tmp_202609.product_uom_source_map
    ADD CONSTRAINT product_uom_source_map_source_stage_uom_key
        UNIQUE (
            source_system, source_table, source_stage_schema,
            source_staging_id, source_uom_ordinal
        );

CREATE INDEX idx_clean_product_uom_map_stage_identity
    ON migration_clean_bdm_tmp_202609.product_uom_source_map (
        source_system, source_table, source_stage_schema, source_staging_id
    );

-- The marker binds this database name to the exact public schema/reference
-- fingerprints observed in a read-only dry run.  The importer recomputes
-- both fingerprints and refuses any mismatch; it is not enough merely to
-- pass arbitrary SHA strings on the command line.
CREATE TABLE migration_clean_bdm_tmp_202609.clean_target_attestation (
    target_database text PRIMARY KEY,
    target_kind text NOT NULL CHECK (target_kind = 'bluegreen_clean'),
    baseline_schema_sha256 text NOT NULL CHECK (baseline_schema_sha256 ~ '^[0-9a-f]{64}$'),
    baseline_reference_sha256 text NOT NULL CHECK (baseline_reference_sha256 ~ '^[0-9a-f]{64}$'),
    attested_by text NOT NULL DEFAULT session_user,
    attested_at timestamptz NOT NULL DEFAULT now(),
    CHECK (target_database ~ '^budimas_clean_[a-z0-9_]{1,48}$')
);

CREATE FUNCTION migration_clean_bdm_tmp_202609.assert_clean_target_attestation_scope()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF NEW.target_database IS DISTINCT FROM current_database()
       OR NEW.target_kind IS DISTINCT FROM 'bluegreen_clean' THEN
        RAISE EXCEPTION 'clean target attestation harus tepat untuk database blue/green yang sedang tersambung';
    END IF;
    IF EXISTS (SELECT 1 FROM migration_clean_bdm_tmp_202609.clean_target_attestation) THEN
        RAISE EXCEPTION 'clean target attestation hanya boleh dibuat sekali';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER clean_target_attestation_scope_guard
BEFORE INSERT OR UPDATE ON migration_clean_bdm_tmp_202609.clean_target_attestation
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.assert_clean_target_attestation_scope();

CREATE TRIGGER clean_target_attestation_no_update
BEFORE UPDATE ON migration_clean_bdm_tmp_202609.clean_target_attestation
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_update();

CREATE TRIGGER clean_target_attestation_no_delete
BEFORE DELETE ON migration_clean_bdm_tmp_202609.clean_target_attestation
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_delete();

INSERT INTO migration_clean_bdm_tmp_202609.clean_target_attestation (
    target_database, target_kind, baseline_schema_sha256, baseline_reference_sha256
) VALUES (
    current_database(),
    'bluegreen_clean',
    lower(btrim(current_setting('migration_clean_bdm_tmp_202609.baseline_schema_sha256'))),
    lower(btrim(current_setting('migration_clean_bdm_tmp_202609.baseline_reference_sha256')))
);

-- Historical master import creates sales without a login user.  The base map
-- was designed before that auth decision and required id_user, so make it
-- nullable while it is still empty and replace its scope trigger accordingly.
ALTER TABLE migration_clean_bdm_tmp_202609.sales_source_map
    ALTER COLUMN id_user DROP NOT NULL;

CREATE OR REPLACE FUNCTION migration_clean_bdm_tmp_202609.assert_sales_source_map_scope()
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
           sc.target_company_id, sc.target_branch_id
      INTO v_sales_principal, v_sales_user, v_expected_principal,
           v_expected_company, v_expected_branch
      FROM public.sales s
      JOIN migration_clean_bdm_tmp_202609.principal_source_map pm
        ON pm.source_system = NEW.source_system
       AND pm.source_principal_code_norm = NEW.source_principal_code_norm
      JOIN migration_clean_bdm_tmp_202609.source_context sc
        ON sc.source_system = NEW.source_system
     WHERE s.id = NEW.id_sales;
    IF NOT FOUND
       OR v_sales_principal IS DISTINCT FROM v_expected_principal
       OR v_sales_user IS DISTINCT FROM NEW.id_user THEN
        RAISE EXCEPTION
            'sales/user %/% tidak cocok dengan principal source-qualified',
            NEW.id_sales, NEW.id_user;
    END IF;
    IF NEW.id_user IS NULL THEN
        RETURN NEW;
    END IF;
    SELECT u.id_perusahaan, u.id_cabang
      INTO v_user_company, v_user_branch
      FROM public.users u
     WHERE u.id = NEW.id_user;
    IF NOT FOUND
       OR v_user_company IS DISTINCT FROM v_expected_company
       OR v_user_branch IS DISTINCT FROM v_expected_branch THEN
        RAISE EXCEPTION
            'user % tidak cocok dengan company/cabang context %', NEW.id_user, NEW.source_system;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TABLE migration_clean_bdm_tmp_202609.product_price_source_map (
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
    source_price_column text NOT NULL,
    source_price_column_norm text NOT NULL,
    target_price_type_code text NOT NULL,
    target_price_type_code_norm text NOT NULL,
    source_price numeric NOT NULL CHECK (source_price >= 0),
    id_produk bigint NOT NULL REFERENCES public.produk(id) ON DELETE RESTRICT,
    id_produk_harga_jual integer NOT NULL
        REFERENCES public.produk_harga_jual(id) ON DELETE RESTRICT,
    mapping_method text NOT NULL CHECK (mapping_method = 'source_created'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (
        source_system, source_principal_code_norm, source_sku_norm,
        source_price_column_norm
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
    CHECK (source_price_column_norm = migration_clean_bdm_tmp_202609.norm_migration_key(source_price_column)),
    CHECK (source_price_column_norm IN ('hargaa', 'hargab', 'hargac', 'hargad', 'hargae')),
    CHECK (target_price_type_code_norm = migration_clean_bdm_tmp_202609.norm_migration_key(target_price_type_code)),
    CHECK (target_price_type_code_norm <> ''),
    UNIQUE (
        source_system, source_table, source_stage_schema,
        source_staging_id, source_price_column_norm
    ),
    UNIQUE (id_produk_harga_jual)
);

CREATE INDEX idx_clean_product_price_map_run
    ON migration_clean_bdm_tmp_202609.product_price_source_map (import_run_id);

CREATE INDEX idx_clean_product_price_map_product
    ON migration_clean_bdm_tmp_202609.product_price_source_map
       (source_system, source_principal_code_norm, source_sku_norm);

CREATE INDEX idx_clean_product_price_map_target_product
    ON migration_clean_bdm_tmp_202609.product_price_source_map (id_produk);

CREATE FUNCTION migration_clean_bdm_tmp_202609.assert_product_price_source_map_scope()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    v_target_product bigint;
    v_expected_product bigint;
    v_target_price_type_code text;
    v_target_price double precision;
BEGIN
    PERFORM migration_clean_bdm_tmp_202609.assert_open_import_run(NEW.import_run_id);

    SELECT phj.id_produk::bigint, pm.id_produk,
           migration_clean_bdm_tmp_202609.norm_migration_key(pth.kode), phj.harga
      INTO v_target_product, v_expected_product, v_target_price_type_code, v_target_price
      FROM public.produk_harga_jual phj
      JOIN public.produk_tipe_harga pth ON pth.id = phj.id_tipe_harga
      JOIN migration_clean_bdm_tmp_202609.product_source_map pm
        ON pm.source_system = NEW.source_system
       AND pm.source_principal_code_norm = NEW.source_principal_code_norm
       AND pm.source_sku_norm = NEW.source_sku_norm
     WHERE phj.id = NEW.id_produk_harga_jual;

    IF NOT FOUND
       OR v_target_product IS DISTINCT FROM NEW.id_produk
       OR v_expected_product IS DISTINCT FROM NEW.id_produk
       OR v_target_price_type_code IS DISTINCT FROM NEW.target_price_type_code_norm
       OR v_target_price IS DISTINCT FROM NEW.source_price::double precision THEN
        RAISE EXCEPTION
            'produk_harga_jual % tidak cocok dengan source product/tipe harga identity',
            NEW.id_produk_harga_jual;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER product_price_source_map_scope_guard
BEFORE INSERT OR UPDATE ON migration_clean_bdm_tmp_202609.product_price_source_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.assert_product_price_source_map_scope();

CREATE TRIGGER product_price_source_map_no_update
BEFORE UPDATE ON migration_clean_bdm_tmp_202609.product_price_source_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_update();

CREATE TRIGGER product_price_source_map_no_delete
BEFORE DELETE ON migration_clean_bdm_tmp_202609.product_price_source_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_delete();

CREATE TABLE migration_clean_bdm_tmp_202609.plafon_source_map (
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
    source_principal_code text NOT NULL,
    source_principal_code_norm text NOT NULL,
    source_sales_code text NOT NULL,
    source_sales_code_norm text NOT NULL,
    source_added_at_raw text NOT NULL CHECK (btrim(source_added_at_raw) <> ''),
    source_added_at timestamptz NOT NULL,
    source_limit_bon numeric NOT NULL CHECK (source_limit_bon >= 0),
    source_term integer NOT NULL CHECK (source_term BETWEEN 0 AND 32767),
    opening_balance_strategy text NOT NULL
        CHECK (opening_balance_strategy = 'non_live_zero_sisa_bon_locked'),
    id_plafon integer NOT NULL REFERENCES public.plafon(id) ON DELETE RESTRICT,
    mapping_method text NOT NULL CHECK (mapping_method = 'source_created'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (
        source_system, source_customer_code_norm,
        source_principal_code_norm, source_sales_code_norm
    ),
    FOREIGN KEY (source_system, source_customer_code_norm)
        REFERENCES migration_clean_bdm_tmp_202609.customer_source_map(
            source_system, source_customer_code_norm
        ) ON DELETE RESTRICT,
    FOREIGN KEY (source_system, source_principal_code_norm)
        REFERENCES migration_clean_bdm_tmp_202609.principal_source_map(
            source_system, source_principal_code_norm
        ) ON DELETE RESTRICT,
    FOREIGN KEY (source_system, source_principal_code_norm, source_sales_code_norm)
        REFERENCES migration_clean_bdm_tmp_202609.sales_source_map(
            source_system, source_principal_code_norm, source_sales_code_norm
        ) ON DELETE RESTRICT,
    CHECK (btrim(source_table) <> ''),
    CHECK (btrim(source_stage_schema) <> ''),
    CHECK (lower(source_row_hash) ~ '^[0-9a-f]{64}$'),
    CHECK (source_customer_code_norm = migration_clean_bdm_tmp_202609.norm_migration_key(source_customer_code)),
    CHECK (source_customer_code_norm <> ''),
    CHECK (source_principal_code_norm = migration_clean_bdm_tmp_202609.norm_migration_key(source_principal_code)),
    CHECK (source_principal_code_norm <> ''),
    CHECK (source_sales_code_norm = migration_clean_bdm_tmp_202609.norm_migration_key(source_sales_code)),
    CHECK (source_sales_code_norm <> ''),
    UNIQUE (source_system, source_table, source_stage_schema, source_staging_id),
    UNIQUE (id_plafon)
);

CREATE INDEX idx_clean_plafon_map_run
    ON migration_clean_bdm_tmp_202609.plafon_source_map (import_run_id);

CREATE INDEX idx_clean_plafon_map_customer
    ON migration_clean_bdm_tmp_202609.plafon_source_map
       (source_system, source_customer_code_norm);

CREATE INDEX idx_clean_plafon_map_principal_sales
    ON migration_clean_bdm_tmp_202609.plafon_source_map
       (source_system, source_principal_code_norm, source_sales_code_norm);

CREATE FUNCTION migration_clean_bdm_tmp_202609.assert_plafon_source_map_scope()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    v_target_customer integer;
    v_target_principal integer;
    v_target_sales integer;
    v_target_user integer;
    v_target_price_type integer;
    v_target_limit_bon double precision;
    v_target_sisa_bon double precision;
    v_target_top smallint;
    v_target_lock_order text;
    v_target_tempo integer;
    v_expected_customer integer;
    v_expected_principal integer;
    v_expected_sales integer;
    v_expected_price_type integer;
BEGIN
    PERFORM migration_clean_bdm_tmp_202609.assert_open_import_run(NEW.import_run_id);

    SELECT p.id_customer, p.id_principal, p.id_sales, p.id_user,
           p.id_tipe_harga, p.limit_bon, p.sisa_bon, p.top, p.lock_order, p.tempo,
           cm.id_customer, pm.id_principal, sm.id_sales, c.id_tipe_harga
      INTO v_target_customer, v_target_principal, v_target_sales, v_target_user,
           v_target_price_type, v_target_limit_bon, v_target_sisa_bon, v_target_top,
           v_target_lock_order, v_target_tempo,
           v_expected_customer, v_expected_principal, v_expected_sales, v_expected_price_type
      FROM public.plafon p
      JOIN migration_clean_bdm_tmp_202609.customer_source_map cm
        ON cm.source_system = NEW.source_system
       AND cm.source_customer_code_norm = NEW.source_customer_code_norm
      JOIN migration_clean_bdm_tmp_202609.principal_source_map pm
        ON pm.source_system = NEW.source_system
       AND pm.source_principal_code_norm = NEW.source_principal_code_norm
      JOIN migration_clean_bdm_tmp_202609.sales_source_map sm
        ON sm.source_system = NEW.source_system
       AND sm.source_principal_code_norm = NEW.source_principal_code_norm
       AND sm.source_sales_code_norm = NEW.source_sales_code_norm
      JOIN public.customer c ON c.id = cm.id_customer
     WHERE p.id = NEW.id_plafon;

    IF NOT FOUND
       OR v_target_customer IS DISTINCT FROM v_expected_customer
       OR v_target_principal IS DISTINCT FROM v_expected_principal
       OR v_target_sales IS DISTINCT FROM v_expected_sales
       OR v_target_user IS NOT NULL
       OR v_target_price_type IS DISTINCT FROM v_expected_price_type
       OR v_target_limit_bon IS DISTINCT FROM NEW.source_limit_bon::double precision
       OR v_target_sisa_bon IS DISTINCT FROM 0::double precision
       OR v_target_top::integer IS DISTINCT FROM NEW.source_term
       OR v_target_tempo IS DISTINCT FROM NEW.source_term
       OR v_target_lock_order IS DISTINCT FROM '1' THEN
        RAISE EXCEPTION
            'plafon % tidak cocok dengan customer/principal/sales source-qualified',
            NEW.id_plafon;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER plafon_source_map_scope_guard
BEFORE INSERT OR UPDATE ON migration_clean_bdm_tmp_202609.plafon_source_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.assert_plafon_source_map_scope();

CREATE TRIGGER plafon_source_map_no_update
BEFORE UPDATE ON migration_clean_bdm_tmp_202609.plafon_source_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_update();

CREATE TRIGGER plafon_source_map_no_delete
BEFORE DELETE ON migration_clean_bdm_tmp_202609.plafon_source_map
FOR EACH ROW EXECUTE FUNCTION migration_clean_bdm_tmp_202609.prevent_registry_delete();

COMMENT ON COLUMN migration_clean_bdm_tmp_202609.product_uom_source_map.source_uom_ordinal IS
    'Source UOM ordinal, intentionally equal to source_uom_level. Enables PCS and CT maps derived from the same frozen STOK row.';

COMMENT ON TABLE migration_clean_bdm_tmp_202609.product_price_source_map IS
    'Immutable source-qualified target price provenance, including the exact source numeric price, for a clean BDM/TMP master import.';

COMMENT ON TABLE migration_clean_bdm_tmp_202609.plafon_source_map IS
    'Immutable source-qualified plafon provenance. Latest source limit/term is stored, while target initial sisa_bon is zero and locked; this is not live AR.';

COMMENT ON TABLE migration_clean_bdm_tmp_202609.clean_target_attestation IS
    'One immutable marker binding a budimas_clean_* database to observed public schema and reference baseline fingerprints.';

COMMIT;
