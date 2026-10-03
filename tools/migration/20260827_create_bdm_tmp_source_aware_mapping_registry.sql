-- Source-aware migration registry for BDM Solo + TMP Solo.
--
-- This is deliberately separate from public application tables.  It is a
-- prerequisite for a later migration; running this file does NOT import any
-- customer, product, order, invoice, stock, or payment data.
--
-- Run once with psql -v ON_ERROR_STOP=1.  The source code columns are stored
-- in their original form plus a required lower/trimmed key so BDM/TMP code
-- collisions cannot be resolved by an accidental MIN(id) lookup.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

CREATE SCHEMA migration_bdm_tmp_202608;

CREATE TABLE migration_bdm_tmp_202608.source_context (
    source_system text PRIMARY KEY
        CHECK (source_system IN ('bdm_solo_dist', 'tmp_solo_dist')),
    target_perusahaan_cabang_id integer NOT NULL
        REFERENCES public.perusahaan_cabang(id) ON DELETE RESTRICT,
    target_company_id integer NOT NULL
        REFERENCES public.perusahaan(id) ON DELETE RESTRICT,
    target_branch_id integer NOT NULL
        REFERENCES public.cabang(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION migration_bdm_tmp_202608.assert_source_context_scope()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    actual_company integer;
    actual_branch integer;
BEGIN
    SELECT pc.id_perusahaan, pc.id_cabang
      INTO actual_company, actual_branch
      FROM public.perusahaan_cabang pc
     WHERE pc.id = NEW.target_perusahaan_cabang_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'perusahaan_cabang % tidak ditemukan', NEW.target_perusahaan_cabang_id;
    END IF;
    IF actual_company IS DISTINCT FROM NEW.target_company_id
       OR actual_branch IS DISTINCT FROM NEW.target_branch_id THEN
        RAISE EXCEPTION
            'source_context % tidak konsisten: perusahaan_cabang % adalah perusahaan/cabang %/%, bukan %/%',
            NEW.source_system, NEW.target_perusahaan_cabang_id,
            actual_company, actual_branch, NEW.target_company_id, NEW.target_branch_id;
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER source_context_scope_guard
BEFORE INSERT OR UPDATE ON migration_bdm_tmp_202608.source_context
FOR EACH ROW EXECUTE FUNCTION migration_bdm_tmp_202608.assert_source_context_scope();

INSERT INTO migration_bdm_tmp_202608.source_context (
    source_system, target_perusahaan_cabang_id, target_company_id, target_branch_id
) VALUES
    ('bdm_solo_dist', 508, 1, 5),
    ('tmp_solo_dist', 328, 2, 5);

CREATE TABLE migration_bdm_tmp_202608.principal_map (
    source_system text NOT NULL
        REFERENCES migration_bdm_tmp_202608.source_context(source_system) ON DELETE RESTRICT,
    source_principal_code text NOT NULL,
    source_principal_code_norm text NOT NULL,
    id_principal integer NOT NULL REFERENCES public.principal(id) ON DELETE RESTRICT,
    mapping_method text NOT NULL CHECK (mapping_method IN ('exact_reviewed', 'manual', 'created')),
    approved_at timestamptz NOT NULL DEFAULT now(),
    approved_by text,
    reviewer_note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_system, source_principal_code_norm),
    CHECK (source_principal_code_norm = lower(btrim(source_principal_code))),
    CHECK (source_principal_code_norm <> '')
);

CREATE TABLE migration_bdm_tmp_202608.customer_map (
    source_system text NOT NULL
        REFERENCES migration_bdm_tmp_202608.source_context(source_system) ON DELETE RESTRICT,
    source_customer_code text NOT NULL,
    source_customer_code_norm text NOT NULL,
    id_customer integer NOT NULL REFERENCES public.customer(id) ON DELETE RESTRICT,
    mapping_method text NOT NULL CHECK (
        mapping_method IN ('exact_reviewed', 'manual', 'created', 'cross_branch_approved')
    ),
    approved_at timestamptz NOT NULL DEFAULT now(),
    approved_by text,
    reviewer_note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_system, source_customer_code_norm),
    CHECK (source_customer_code_norm = lower(btrim(source_customer_code))),
    CHECK (source_customer_code_norm <> '')
);

CREATE TABLE migration_bdm_tmp_202608.sales_map (
    source_system text NOT NULL
        REFERENCES migration_bdm_tmp_202608.source_context(source_system) ON DELETE RESTRICT,
    source_principal_code text NOT NULL,
    source_principal_code_norm text NOT NULL,
    source_sales_code text NOT NULL,
    source_sales_code_norm text NOT NULL,
    id_sales integer NOT NULL REFERENCES public.sales(id) ON DELETE RESTRICT,
    mapping_method text NOT NULL CHECK (mapping_method IN ('exact_reviewed', 'manual', 'created')),
    approved_at timestamptz NOT NULL DEFAULT now(),
    approved_by text,
    reviewer_note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_system, source_principal_code_norm, source_sales_code_norm),
    FOREIGN KEY (source_system, source_principal_code_norm)
        REFERENCES migration_bdm_tmp_202608.principal_map(source_system, source_principal_code_norm)
        ON DELETE RESTRICT,
    CHECK (source_principal_code_norm = lower(btrim(source_principal_code))),
    CHECK (source_principal_code_norm <> ''),
    CHECK (source_sales_code_norm = lower(btrim(source_sales_code))),
    CHECK (source_sales_code_norm <> '')
);

CREATE TABLE migration_bdm_tmp_202608.product_map (
    source_system text NOT NULL
        REFERENCES migration_bdm_tmp_202608.source_context(source_system) ON DELETE RESTRICT,
    source_principal_code text NOT NULL,
    source_principal_code_norm text NOT NULL,
    source_sku text NOT NULL,
    source_sku_norm text NOT NULL,
    id_produk bigint NOT NULL REFERENCES public.produk(id) ON DELETE RESTRICT,
    mapping_method text NOT NULL CHECK (mapping_method IN ('exact_reviewed', 'manual', 'created')),
    approved_at timestamptz NOT NULL DEFAULT now(),
    approved_by text,
    reviewer_note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_system, source_principal_code_norm, source_sku_norm),
    FOREIGN KEY (source_system, source_principal_code_norm)
        REFERENCES migration_bdm_tmp_202608.principal_map(source_system, source_principal_code_norm)
        ON DELETE RESTRICT,
    CHECK (source_principal_code_norm = lower(btrim(source_principal_code))),
    CHECK (source_principal_code_norm <> ''),
    CHECK (source_sku_norm = lower(btrim(source_sku))),
    CHECK (source_sku_norm <> '')
);

CREATE TABLE migration_bdm_tmp_202608.product_uom_map (
    source_system text NOT NULL
        REFERENCES migration_bdm_tmp_202608.source_context(source_system) ON DELETE RESTRICT,
    source_principal_code text NOT NULL,
    source_principal_code_norm text NOT NULL,
    source_sku text NOT NULL,
    source_sku_norm text NOT NULL,
    source_uom_code text NOT NULL,
    source_uom_code_norm text NOT NULL,
    -- A source outer UOM may be represented by a target level 3 UOM, but
    -- only when assert_product_uom_map_scope() proves the complete target
    -- level 1 -> level 2 -> level 3 chain below.  The level alone is never
    -- used as a conversion heuristic.
    source_uom_level smallint NOT NULL CHECK (source_uom_level IN (1, 2, 3)),
    source_factor integer NOT NULL CHECK (source_factor > 0),
    id_produk bigint NOT NULL REFERENCES public.produk(id) ON DELETE RESTRICT,
    id_produk_uom integer NOT NULL REFERENCES public.produk_uom(id) ON DELETE RESTRICT,
    mapping_method text NOT NULL CHECK (mapping_method IN ('exact_reviewed', 'manual', 'created')),
    approved_at timestamptz NOT NULL DEFAULT now(),
    approved_by text,
    reviewer_note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (
        source_system, source_principal_code_norm, source_sku_norm,
        source_uom_code_norm, source_uom_level, source_factor
    ),
    FOREIGN KEY (source_system, source_principal_code_norm, source_sku_norm)
        REFERENCES migration_bdm_tmp_202608.product_map(
            source_system, source_principal_code_norm, source_sku_norm
        ) ON DELETE RESTRICT,
    CHECK (source_principal_code_norm = lower(btrim(source_principal_code))),
    CHECK (source_principal_code_norm <> ''),
    CHECK (source_sku_norm = lower(btrim(source_sku))),
    CHECK (source_sku_norm <> ''),
    CHECK (source_uom_code_norm = lower(btrim(source_uom_code))),
    CHECK (source_uom_code_norm <> '')
);

CREATE TABLE migration_bdm_tmp_202608.sales_document_map (
    source_system text NOT NULL
        REFERENCES migration_bdm_tmp_202608.source_context(source_system) ON DELETE RESTRICT,
    source_table text NOT NULL CHECK (source_table IN ('HJualSM', 'HJualSMAndroid')),
    source_nota text NOT NULL,
    source_nota_norm text NOT NULL,
    stage_schema text NOT NULL,
    source_staging_id bigint NOT NULL,
    source_row_hash text NOT NULL,
    id_sales_order integer NOT NULL REFERENCES public.sales_order(id) ON DELETE RESTRICT,
    id_faktur integer REFERENCES public.faktur(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_system, source_table, source_nota_norm),
    UNIQUE (source_system, source_table, source_staging_id),
    CHECK (source_nota_norm = lower(btrim(source_nota))),
    CHECK (source_nota_norm <> '')
);

CREATE TABLE migration_bdm_tmp_202608.sales_document_line_map (
    source_system text NOT NULL,
    source_table text NOT NULL,
    source_nota_norm text NOT NULL,
    source_urut text NOT NULL,
    source_urut_norm text NOT NULL,
    source_staging_id bigint NOT NULL,
    source_row_hash text NOT NULL,
    id_sales_order_detail integer NOT NULL REFERENCES public.sales_order_detail(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_system, source_table, source_nota_norm, source_urut_norm),
    UNIQUE (source_system, source_table, source_staging_id),
    FOREIGN KEY (source_system, source_table, source_nota_norm)
        REFERENCES migration_bdm_tmp_202608.sales_document_map(
            source_system, source_table, source_nota_norm
        ) ON DELETE RESTRICT,
    CHECK (source_urut_norm = lower(btrim(source_urut))),
    CHECK (source_urut_norm <> '')
);

CREATE OR REPLACE FUNCTION migration_bdm_tmp_202608.touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION migration_bdm_tmp_202608.assert_customer_map_scope()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    actual_branch integer;
    expected_branch integer;
BEGIN
    SELECT c.id_cabang, sc.target_branch_id
      INTO actual_branch, expected_branch
      FROM public.customer c
      JOIN migration_bdm_tmp_202608.source_context sc ON sc.source_system = NEW.source_system
     WHERE c.id = NEW.id_customer;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'customer % atau source context % tidak ditemukan', NEW.id_customer, NEW.source_system;
    END IF;
    IF actual_branch IS DISTINCT FROM expected_branch
       AND NEW.mapping_method <> 'cross_branch_approved' THEN
        RAISE EXCEPTION
            'customer % ada pada cabang %, sedangkan source % ditetapkan ke cabang %; gunakan cross_branch_approved hanya setelah persetujuan eksplisit',
            NEW.id_customer, actual_branch, NEW.source_system, expected_branch;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION migration_bdm_tmp_202608.assert_principal_map_scope()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    actual_company integer;
    expected_company integer;
BEGIN
    SELECT p.id_perusahaan, sc.target_company_id
      INTO actual_company, expected_company
      FROM public.principal p
      JOIN migration_bdm_tmp_202608.source_context sc ON sc.source_system = NEW.source_system
     WHERE p.id = NEW.id_principal;
    IF NOT FOUND OR actual_company IS DISTINCT FROM expected_company THEN
        RAISE EXCEPTION
            'principal % tidak berada pada perusahaan target untuk source %', NEW.id_principal, NEW.source_system;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION migration_bdm_tmp_202608.assert_sales_map_scope()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    actual_principal integer;
    expected_principal integer;
BEGIN
    SELECT s.id_principal, pm.id_principal
      INTO actual_principal, expected_principal
      FROM public.sales s
      JOIN migration_bdm_tmp_202608.principal_map pm
        ON pm.source_system = NEW.source_system
       AND pm.source_principal_code_norm = NEW.source_principal_code_norm
     WHERE s.id = NEW.id_sales;
    IF NOT FOUND OR actual_principal IS DISTINCT FROM expected_principal THEN
        RAISE EXCEPTION
            'sales % tidak cocok dengan principal map %/%',
            NEW.id_sales, NEW.source_system, NEW.source_principal_code_norm;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION migration_bdm_tmp_202608.assert_product_map_scope()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    actual_principal integer;
    expected_principal integer;
BEGIN
    SELECT prd.id_principal, pm.id_principal
      INTO actual_principal, expected_principal
      FROM public.produk prd
      JOIN migration_bdm_tmp_202608.principal_map pm
        ON pm.source_system = NEW.source_system
       AND pm.source_principal_code_norm = NEW.source_principal_code_norm
     WHERE prd.id = NEW.id_produk;
    IF NOT FOUND OR actual_principal IS DISTINCT FROM expected_principal THEN
        RAISE EXCEPTION
            'produk % tidak cocok dengan principal map %/%',
            NEW.id_produk, NEW.source_system, NEW.source_principal_code_norm;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION migration_bdm_tmp_202608.assert_product_uom_map_scope()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    uom_produk bigint;
    map_produk bigint;
    actual_uom_code text;
    actual_level smallint;
    actual_factor integer;
    mapped_base_count integer;
    mapped_base_produk bigint;
    mapped_base_code text;
    mapped_base_level smallint;
    mapped_base_factor integer;
    level2_count integer;
    valid_level2_count integer;
BEGIN
    SELECT pu.id_produk, pm.id_produk, lower(btrim(pu.kode)), pu.level, pu.faktor_konversi
      INTO uom_produk, map_produk, actual_uom_code, actual_level, actual_factor
      FROM public.produk_uom pu
      JOIN migration_bdm_tmp_202608.product_map pm
        ON pm.source_system = NEW.source_system
       AND pm.source_principal_code_norm = NEW.source_principal_code_norm
       AND pm.source_sku_norm = NEW.source_sku_norm
     WHERE pu.id = NEW.id_produk_uom;
    IF NOT FOUND
       OR uom_produk IS DISTINCT FROM NEW.id_produk
       OR map_produk IS DISTINCT FROM NEW.id_produk
       OR actual_uom_code IS DISTINCT FROM NEW.source_uom_code_norm
       OR actual_level IS DISTINCT FROM NEW.source_uom_level
       OR actual_factor IS DISTINCT FROM NEW.source_factor THEN
        RAISE EXCEPTION
            'produk_uom % tidak cocok dengan produk/UOM source %/%/%',
            NEW.id_produk_uom, NEW.source_system, NEW.source_principal_code_norm, NEW.source_sku_norm;
    END IF;

    -- SQL Server STOK exposes a base UOM plus one outer UOM.  If that outer
    -- UOM maps to target level 3, it is safe only when the corresponding base
    -- mapping already exists and the target product has one unambiguous,
    -- mathematically valid level 2 link.  This prevents a level 3 UOM from
    -- being treated as an arbitrary substitute for level 2.
    IF NEW.source_uom_level = 3 THEN
        SELECT count(*),
               min(pu.id_produk),
               min(lower(btrim(pu.kode))),
               min(pu.level),
               min(pu.faktor_konversi)
          INTO mapped_base_count,
               mapped_base_produk,
               mapped_base_code,
               mapped_base_level,
               mapped_base_factor
          FROM migration_bdm_tmp_202608.product_uom_map base_map
          JOIN public.produk_uom pu ON pu.id = base_map.id_produk_uom
         WHERE base_map.source_system = NEW.source_system
           AND base_map.source_principal_code_norm = NEW.source_principal_code_norm
           AND base_map.source_sku_norm = NEW.source_sku_norm
           AND base_map.source_uom_level = 1
           AND base_map.source_factor = 1;

        IF mapped_base_count <> 1
           OR mapped_base_produk IS DISTINCT FROM NEW.id_produk
           OR mapped_base_code IS NULL
           OR mapped_base_level IS DISTINCT FROM 1
           OR mapped_base_factor IS DISTINCT FROM 1 THEN
            RAISE EXCEPTION
                'produk_uom level 3 % memerlukan tepat satu mapping UOM dasar level 1/faktor 1 untuk source %/%/%',
                NEW.id_produk_uom, NEW.source_system, NEW.source_principal_code_norm, NEW.source_sku_norm;
        END IF;

        SELECT count(*),
               count(*) FILTER (
                   WHERE nullif(btrim(pu.kode), '') IS NOT NULL
                     AND lower(btrim(pu.kode)) <> actual_uom_code
                     AND lower(btrim(pu.kode)) <> mapped_base_code
                     AND pu.faktor_konversi > 1
                     AND pu.faktor_konversi < actual_factor
                     AND mod(actual_factor::numeric, pu.faktor_konversi::numeric) = 0
               )
          INTO level2_count, valid_level2_count
          FROM public.produk_uom pu
         WHERE pu.id_produk = NEW.id_produk
           AND pu.level = 2;

        IF level2_count <> 1 OR valid_level2_count <> 1 THEN
            RAISE EXCEPTION
                'produk_uom level 3 % tidak memiliki rantai level 2 tunggal dan valid (faktor level 2 harus membagi faktor level 3) untuk produk %',
                NEW.id_produk_uom, NEW.id_produk;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION migration_bdm_tmp_202608.assert_sales_document_scope()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    order_branch integer;
    expected_branch integer;
    invoice_order integer;
BEGIN
    SELECT so.id_cabang, sc.target_branch_id
      INTO order_branch, expected_branch
      FROM public.sales_order so
      JOIN migration_bdm_tmp_202608.source_context sc ON sc.source_system = NEW.source_system
     WHERE so.id = NEW.id_sales_order;
    IF NOT FOUND OR order_branch IS DISTINCT FROM expected_branch THEN
        RAISE EXCEPTION 'sales_order % tidak berada pada cabang target source %', NEW.id_sales_order, NEW.source_system;
    END IF;
    IF NEW.id_faktur IS NOT NULL THEN
        SELECT f.id_sales_order INTO invoice_order FROM public.faktur f WHERE f.id = NEW.id_faktur;
        IF NOT FOUND OR invoice_order IS DISTINCT FROM NEW.id_sales_order THEN
            RAISE EXCEPTION 'faktur % tidak terkait dengan sales_order %', NEW.id_faktur, NEW.id_sales_order;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION migration_bdm_tmp_202608.assert_sales_document_line_scope()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    expected_order integer;
    actual_order integer;
BEGIN
    SELECT dm.id_sales_order, sod.id_sales_order
      INTO expected_order, actual_order
      FROM migration_bdm_tmp_202608.sales_document_map dm
      JOIN public.sales_order_detail sod ON sod.id = NEW.id_sales_order_detail
     WHERE dm.source_system = NEW.source_system
       AND dm.source_table = NEW.source_table
       AND dm.source_nota_norm = NEW.source_nota_norm;
    IF NOT FOUND OR expected_order IS DISTINCT FROM actual_order THEN
        RAISE EXCEPTION 'sales_order_detail % tidak terkait dengan dokumen sumber yang sama', NEW.id_sales_order_detail;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER principal_map_scope_guard
BEFORE INSERT OR UPDATE ON migration_bdm_tmp_202608.principal_map
FOR EACH ROW EXECUTE FUNCTION migration_bdm_tmp_202608.assert_principal_map_scope();

CREATE TRIGGER customer_map_scope_guard
BEFORE INSERT OR UPDATE ON migration_bdm_tmp_202608.customer_map
FOR EACH ROW EXECUTE FUNCTION migration_bdm_tmp_202608.assert_customer_map_scope();

CREATE TRIGGER sales_map_scope_guard
BEFORE INSERT OR UPDATE ON migration_bdm_tmp_202608.sales_map
FOR EACH ROW EXECUTE FUNCTION migration_bdm_tmp_202608.assert_sales_map_scope();

CREATE TRIGGER product_map_scope_guard
BEFORE INSERT OR UPDATE ON migration_bdm_tmp_202608.product_map
FOR EACH ROW EXECUTE FUNCTION migration_bdm_tmp_202608.assert_product_map_scope();

CREATE TRIGGER product_uom_map_scope_guard
BEFORE INSERT OR UPDATE ON migration_bdm_tmp_202608.product_uom_map
FOR EACH ROW EXECUTE FUNCTION migration_bdm_tmp_202608.assert_product_uom_map_scope();

CREATE TRIGGER sales_document_scope_guard
BEFORE INSERT OR UPDATE ON migration_bdm_tmp_202608.sales_document_map
FOR EACH ROW EXECUTE FUNCTION migration_bdm_tmp_202608.assert_sales_document_scope();

CREATE TRIGGER sales_document_line_scope_guard
BEFORE INSERT OR UPDATE ON migration_bdm_tmp_202608.sales_document_line_map
FOR EACH ROW EXECUTE FUNCTION migration_bdm_tmp_202608.assert_sales_document_line_scope();

CREATE TRIGGER principal_map_touch
BEFORE UPDATE ON migration_bdm_tmp_202608.principal_map
FOR EACH ROW EXECUTE FUNCTION migration_bdm_tmp_202608.touch_updated_at();

CREATE TRIGGER customer_map_touch
BEFORE UPDATE ON migration_bdm_tmp_202608.customer_map
FOR EACH ROW EXECUTE FUNCTION migration_bdm_tmp_202608.touch_updated_at();

CREATE TRIGGER sales_map_touch
BEFORE UPDATE ON migration_bdm_tmp_202608.sales_map
FOR EACH ROW EXECUTE FUNCTION migration_bdm_tmp_202608.touch_updated_at();

CREATE TRIGGER product_map_touch
BEFORE UPDATE ON migration_bdm_tmp_202608.product_map
FOR EACH ROW EXECUTE FUNCTION migration_bdm_tmp_202608.touch_updated_at();

CREATE TRIGGER product_uom_map_touch
BEFORE UPDATE ON migration_bdm_tmp_202608.product_uom_map
FOR EACH ROW EXECUTE FUNCTION migration_bdm_tmp_202608.touch_updated_at();

CREATE TRIGGER sales_document_map_touch
BEFORE UPDATE ON migration_bdm_tmp_202608.sales_document_map
FOR EACH ROW EXECUTE FUNCTION migration_bdm_tmp_202608.touch_updated_at();

CREATE TRIGGER sales_document_line_map_touch
BEFORE UPDATE ON migration_bdm_tmp_202608.sales_document_line_map
FOR EACH ROW EXECUTE FUNCTION migration_bdm_tmp_202608.touch_updated_at();

COMMIT;
