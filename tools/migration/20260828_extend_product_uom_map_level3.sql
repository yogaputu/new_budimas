-- Extend the source-aware BDM/TMP UOM registry to support a source outer UOM
-- represented by target level 3.
--
-- This file changes only migration_bdm_tmp_202608 metadata and its guard
-- function.  It never inserts, updates, or deletes public.produk or
-- public.produk_uom.  Apply it once, before the matching level-3 mapping
-- batch.  Existing level-1/level-2 registry rows remain unchanged.
--
-- The guard is intentionally stricter than the old level check.  A level-3
-- mapping needs:
--   * one already-registered, exact level-1/base UOM mapping (factor 1); and
--   * exactly one target level-2 UOM whose factor is between 1 and level 3
--     and divides the level-3 factor.
-- This makes the target 1 -> 2 -> 3 conversion chain explicit rather than
-- inferring a missing source level-2 UOM.

BEGIN;

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '60s';

DO $$
DECLARE
    level_constraint_names text[];
    level_constraint_name text;
BEGIN
    IF to_regclass('migration_bdm_tmp_202608.product_uom_map') IS NULL THEN
        RAISE EXCEPTION
            'registry migration_bdm_tmp_202608.product_uom_map belum ada; jalankan 20260827_create_bdm_tmp_source_aware_mapping_registry.sql lebih dahulu';
    END IF;

    SELECT array_agg(c.conname ORDER BY c.conname)
      INTO level_constraint_names
      FROM pg_constraint c
     WHERE c.conrelid = 'migration_bdm_tmp_202608.product_uom_map'::regclass
       AND c.contype = 'c'
       AND pg_get_constraintdef(c.oid) ILIKE '%source_uom_level%';

    IF coalesce(array_length(level_constraint_names, 1), 0) <> 1 THEN
        RAISE EXCEPTION
            'tidak dapat menentukan satu constraint source_uom_level pada product_uom_map (ditemukan: %)',
            coalesce(array_to_string(level_constraint_names, ', '), '(tidak ada)');
    END IF;

    level_constraint_name := level_constraint_names[1];
    EXECUTE format(
        'ALTER TABLE migration_bdm_tmp_202608.product_uom_map DROP CONSTRAINT %I',
        level_constraint_name
    );
END;
$$;

ALTER TABLE migration_bdm_tmp_202608.product_uom_map
    ADD CONSTRAINT product_uom_map_source_uom_level_check
    CHECK (source_uom_level IN (1, 2, 3));

COMMENT ON CONSTRAINT product_uom_map_source_uom_level_check
    ON migration_bdm_tmp_202608.product_uom_map IS
    'Level source yang diizinkan. Level 3 tetap wajib melewati guard rantai UOM level 1 -> 2 -> 3.';

-- CREATE OR REPLACE keeps product_uom_map_scope_guard attached; no trigger is
-- dropped or disabled by this migration.
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

COMMIT;
