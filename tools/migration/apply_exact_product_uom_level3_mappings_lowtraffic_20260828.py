#!/usr/bin/env python3
"""Register only safe source-outer-UOM -> target-level-3 mappings.

SQL Server STOK has a base UOM (``satuan``) and one outer UOM
(``namaunit``/``perunit``).  This mapping-only batch permits the outer UOM to
be represented by target ``produk_uom.level = 3`` only when all of these are
true:

1. the principal has an existing approved mapping (ambiguous principals stay
   excluded);
2. SKU and normalized product name identify one target product;
3. source base UOM exactly equals target level 1/factor 1;
4. source outer UOM exactly equals target level 3/factor ``perunit``; and
5. that target product has exactly one valid level-2 link with a factor that
   divides the target level-3 factor.

It never creates or updates ``public.produk`` or ``public.produk_uom``.  It
only appends approved rows to the source-aware mapping registry.  It must be
run after ``20260828_extend_product_uom_map_level3.sql``.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from dataclasses import dataclass
from typing import Any

import psycopg2  # type: ignore[import-not-found]
from psycopg2.extras import execute_values  # type: ignore[import-not-found]

from apply_exact_product_uom_mappings_lowtraffic_20260827 import (
    REGISTRY_SCHEMA,
    SOURCE_SYSTEMS,
    ProductMapping,
    UomMapping,
    code_norm,
    factor,
    fetch_stage_rows,
    ident,
    load_principal_maps,
    load_products,
    name_norm,
)


BATCH_ID = "exact_product_uom_level3_mapping_lowtraffic_20260828"


@dataclass(frozen=True)
class TargetUom:
    id_produk_uom: int
    code_norm: str | None
    level: int
    conversion_factor: int | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bdm-schema", required=True)
    parser.add_argument("--tmp-schema", required=True)
    parser.add_argument("--pg-database", default=os.getenv("MIGRATION_PG_DATABASE", "budimas_dev"))
    parser.add_argument("--pg-user", default=os.getenv("MIGRATION_PG_USER", "postgres"))
    parser.add_argument("--pg-host", default=os.getenv("MIGRATION_PG_HOST", "127.0.0.1"))
    parser.add_argument("--pg-port", type=int, default=int(os.getenv("MIGRATION_PG_PORT", "5432")))
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def load_target_uoms(cur, product_ids: set[int]) -> dict[int, dict[int, list[TargetUom]]]:
    """Load every target UOM at levels 1..3.

    Invalid/blank level-2 records are intentionally retained so they make the
    chain fail as ambiguous/invalid instead of being silently ignored.
    """
    if not product_ids:
        return {}
    cur.execute(
        """
        SELECT id, id_produk, kode, level, faktor_konversi
        FROM public.produk_uom
        WHERE id_produk = ANY(%s)
          AND level IN (1, 2, 3)
        """,
        (sorted(product_ids),),
    )
    result: dict[int, dict[int, list[TargetUom]]] = {}
    for uom_id, product_id, code, level, conversion_factor in cur.fetchall():
        parsed_level = int(level) if level is not None else None
        if parsed_level not in (1, 2, 3):
            continue
        result.setdefault(int(product_id), {}).setdefault(parsed_level, []).append(
            TargetUom(
                id_produk_uom=int(uom_id),
                code_norm=code_norm(code),
                level=parsed_level,
                conversion_factor=factor(conversion_factor),
            )
        )
    return result


def load_existing_product_map_keys(cur, source_system: str) -> set[tuple[str, str]]:
    cur.execute(
        f"""
        SELECT source_principal_code_norm, source_sku_norm
        FROM {ident(REGISTRY_SCHEMA)}.product_map
        WHERE source_system = %s
        """,
        (source_system,),
    )
    return {(str(principal), str(sku)) for principal, sku in cur.fetchall()}


def unique_exact_uom(
    uoms: list[TargetUom],
    code: str,
    conversion_factor: int,
) -> list[TargetUom]:
    return [
        uom
        for uom in uoms
        if uom.code_norm == code and uom.conversion_factor == conversion_factor
    ]


def level2_chain_is_valid(
    level2: TargetUom,
    base_code: str,
    outer_code: str,
    outer_factor: int,
) -> bool:
    if not level2.code_norm or level2.code_norm in {base_code, outer_code}:
        return False
    if level2.conversion_factor is None:
        return False
    return 1 < level2.conversion_factor < outer_factor and outer_factor % level2.conversion_factor == 0


def build_mappings(
    cur,
    rows: list[dict[str, Any]],
    source_system: str,
) -> tuple[list[ProductMapping], list[UomMapping], list[UomMapping], Counter[str]]:
    principal_map = load_principal_maps(cur, source_system)
    products = load_products(cur, set(principal_map.values()))
    target_uoms = load_target_uoms(
        cur,
        {product_id for candidates in products.values() for product_id, _name in candidates},
    )
    existing_product_maps = load_existing_product_map_keys(cur, source_system)
    outcomes: Counter[str] = Counter()
    product_mappings: list[ProductMapping] = []
    base_uom_mappings: list[UomMapping] = []
    level3_uom_mappings: list[UomMapping] = []

    for source in rows:
        target_principal = principal_map.get(source["source_principal_code_norm"])
        if target_principal is None:
            outcomes["held_missing_principal_map"] += 1
            continue

        map_key = (source["source_principal_code_norm"], source["source_sku_norm"])
        if map_key in existing_product_maps:
            # A source product already mapped in the strict level-2 batch is
            # deliberately not reinterpreted as level 3.
            outcomes["held_existing_product_map"] += 1
            continue

        products_for_sku = products.get((target_principal, source["source_sku_norm"]), [])
        if not products_for_sku:
            outcomes["held_missing_target_product"] += 1
            continue
        if len(products_for_sku) > 1:
            outcomes["held_duplicate_target_product"] += 1
            continue

        product_id, target_name = products_for_sku[0]
        if not source["source_name"] or name_norm(source["source_name"]) != name_norm(target_name):
            outcomes["held_product_name_difference"] += 1
            continue

        base_code = code_norm(source["base_uom"])
        outer_code = code_norm(source["outer_uom"])
        outer_factor = source["factor"]
        if not base_code or not outer_code or outer_factor is None:
            outcomes["held_invalid_source_uom"] += 1
            continue

        product_uoms = target_uoms.get(product_id, {})
        base_candidates = unique_exact_uom(product_uoms.get(1, []), base_code, 1)
        if len(base_candidates) != 1:
            outcomes["held_base_uom_mismatch"] += 1
            continue

        outer_candidates = unique_exact_uom(product_uoms.get(3, []), outer_code, outer_factor)
        if len(outer_candidates) != 1:
            outcomes["held_outer_level3_uom_mismatch"] += 1
            continue

        level2_candidates = product_uoms.get(2, [])
        if not level2_candidates:
            outcomes["held_missing_target_level2_chain"] += 1
            continue
        if len(level2_candidates) != 1:
            outcomes["held_ambiguous_target_level2_chain"] += 1
            continue
        if not level2_chain_is_valid(level2_candidates[0], base_code, outer_code, outer_factor):
            outcomes["held_invalid_target_level2_chain"] += 1
            continue

        product_mappings.append(
            ProductMapping(
                source_system=source_system,
                source_principal_code=source["source_principal_code"],
                source_principal_code_norm=source["source_principal_code_norm"],
                source_sku=source["source_sku"],
                source_sku_norm=source["source_sku_norm"],
                id_produk=product_id,
            )
        )
        base_uom_mappings.append(
            UomMapping(
                source_system=source_system,
                source_principal_code=source["source_principal_code"],
                source_principal_code_norm=source["source_principal_code_norm"],
                source_sku=source["source_sku"],
                source_sku_norm=source["source_sku_norm"],
                source_uom_code=source["base_uom"],
                source_uom_code_norm=base_code,
                source_uom_level=1,
                source_factor=1,
                id_produk=product_id,
                id_produk_uom=base_candidates[0].id_produk_uom,
            )
        )
        level3_uom_mappings.append(
            UomMapping(
                source_system=source_system,
                source_principal_code=source["source_principal_code"],
                source_principal_code_norm=source["source_principal_code_norm"],
                source_sku=source["source_sku"],
                source_sku_norm=source["source_sku_norm"],
                source_uom_code=source["outer_uom"],
                source_uom_code_norm=outer_code,
                source_uom_level=3,
                source_factor=outer_factor,
                id_produk=product_id,
                id_produk_uom=outer_candidates[0].id_produk_uom,
            )
        )
        outcomes["exact_product_uom_level3"] += 1

    product_keys = {
        (mapping.source_system, mapping.source_principal_code_norm, mapping.source_sku_norm)
        for mapping in product_mappings
    }
    uom_keys = {
        (
            mapping.source_system,
            mapping.source_principal_code_norm,
            mapping.source_sku_norm,
            mapping.source_uom_code_norm,
            mapping.source_uom_level,
            mapping.source_factor,
        )
        for mapping in [*base_uom_mappings, *level3_uom_mappings]
    }
    if len(product_keys) != len(product_mappings):
        raise RuntimeError(f"{source_system}: kandidat product mapping ganda.")
    if len(uom_keys) != len(base_uom_mappings) + len(level3_uom_mappings):
        raise RuntimeError(f"{source_system}: kandidat UOM mapping ganda.")
    return product_mappings, base_uom_mappings, level3_uom_mappings, outcomes


def assert_level3_registry_ready(cur) -> None:
    """Fail closed when the level-3 DDL migration has not been applied."""
    cur.execute(
        """
        SELECT pg_get_constraintdef(c.oid)
        FROM pg_constraint c
        WHERE c.conrelid = 'migration_bdm_tmp_202608.product_uom_map'::regclass
          AND c.contype = 'c'
          AND pg_get_constraintdef(c.oid) ILIKE '%source_uom_level%'
        """
    )
    constraints = [str(row[0]).lower() for row in cur.fetchall()]
    if len(constraints) != 1 or "3" not in constraints[0]:
        raise RuntimeError(
            "Registry belum mengizinkan source_uom_level=3. Jalankan "
            "20260828_extend_product_uom_map_level3.sql terlebih dahulu."
        )

    cur.execute(
        """
        SELECT pg_get_functiondef(
            'migration_bdm_tmp_202608.assert_product_uom_map_scope()'::regprocedure
        )
        """
    )
    function_definition = str(cur.fetchone()[0]).lower()
    if "new.source_uom_level = 3" not in function_definition or "valid_level2_count" not in function_definition:
        raise RuntimeError(
            "Guard rantai UOM level 3 belum terpasang. Jalankan "
            "20260828_extend_product_uom_map_level3.sql terlebih dahulu."
        )


def create_audit_table(cur) -> None:
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {ident(REGISTRY_SCHEMA)}.product_uom_level3_mapping_apply_run (
            batch_id text PRIMARY KEY,
            bdm_stage_schema text NOT NULL,
            tmp_stage_schema text NOT NULL,
            bdm_consistency_mode text NOT NULL,
            tmp_consistency_mode text NOT NULL,
            bdm_product_mapped integer NOT NULL,
            tmp_product_mapped integer NOT NULL,
            bdm_base_uom_mapped integer NOT NULL,
            tmp_base_uom_mapped integer NOT NULL,
            bdm_level3_uom_mapped integer NOT NULL,
            tmp_level3_uom_mapped integer NOT NULL,
            bdm_held jsonb NOT NULL,
            tmp_held jsonb NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def insert_product_mappings(cur, mappings: list[ProductMapping]) -> None:
    if not mappings:
        return
    execute_values(
        cur,
        f"""
        INSERT INTO {ident(REGISTRY_SCHEMA)}.product_map
            (source_system, source_principal_code, source_principal_code_norm,
             source_sku, source_sku_norm, id_produk,
             mapping_method, approved_by, reviewer_note)
        VALUES %s
        """,
        [
            (
                mapping.source_system,
                mapping.source_principal_code,
                mapping.source_principal_code_norm,
                mapping.source_sku,
                mapping.source_sku_norm,
                mapping.id_produk,
                "exact_reviewed",
                "policy_approved_20260828",
                "Principal, SKU, nama produk, base UOM, dan rantai target level 1->2->3 cocok tepat.",
            )
            for mapping in mappings
        ],
        page_size=1000,
    )


def insert_uom_mappings(cur, mappings: list[UomMapping], reviewer_note: str) -> None:
    if not mappings:
        return
    execute_values(
        cur,
        f"""
        INSERT INTO {ident(REGISTRY_SCHEMA)}.product_uom_map
            (source_system, source_principal_code, source_principal_code_norm,
             source_sku, source_sku_norm, source_uom_code, source_uom_code_norm,
             source_uom_level, source_factor, id_produk, id_produk_uom,
             mapping_method, approved_by, reviewer_note)
        VALUES %s
        """,
        [
            (
                mapping.source_system,
                mapping.source_principal_code,
                mapping.source_principal_code_norm,
                mapping.source_sku,
                mapping.source_sku_norm,
                mapping.source_uom_code,
                mapping.source_uom_code_norm,
                mapping.source_uom_level,
                mapping.source_factor,
                mapping.id_produk,
                mapping.id_produk_uom,
                "exact_reviewed",
                "policy_approved_20260828",
                reviewer_note,
            )
            for mapping in mappings
        ],
        page_size=1000,
    )


def main() -> int:
    args = parse_args()
    ident(args.bdm_schema)
    ident(args.tmp_schema)
    conn = psycopg2.connect(
        dbname=args.pg_database,
        user=args.pg_user,
        host=args.pg_host,
        port=args.pg_port,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            staged = {
                "bdm_solo_dist": (
                    args.bdm_schema,
                    *fetch_stage_rows(cur, args.bdm_schema, "bdm_solo_dist"),
                ),
                "tmp_solo_dist": (
                    args.tmp_schema,
                    *fetch_stage_rows(cur, args.tmp_schema, "tmp_solo_dist"),
                ),
            }
            plan_data: dict[
                str,
                tuple[list[ProductMapping], list[UomMapping], list[UomMapping], Counter[str]],
            ] = {}
            for source_system in SOURCE_SYSTEMS:
                plan_data[source_system] = build_mappings(cur, staged[source_system][1], source_system)

            bdm_products, bdm_base_uoms, bdm_level3_uoms, bdm_outcomes = plan_data["bdm_solo_dist"]
            tmp_products, tmp_base_uoms, tmp_level3_uoms, tmp_outcomes = plan_data["tmp_solo_dist"]
            plan = {
                "bdm_product_mapped": len(bdm_products),
                "tmp_product_mapped": len(tmp_products),
                "bdm_base_uom_mapped": len(bdm_base_uoms),
                "tmp_base_uom_mapped": len(tmp_base_uoms),
                "bdm_level3_uom_mapped": len(bdm_level3_uoms),
                "tmp_level3_uom_mapped": len(tmp_level3_uoms),
                "bdm_held": dict(
                    sorted((key, value) for key, value in bdm_outcomes.items() if key != "exact_product_uom_level3")
                ),
                "tmp_held": dict(
                    sorted((key, value) for key, value in tmp_outcomes.items() if key != "exact_product_uom_level3")
                ),
                "bdm_consistency_mode": staged["bdm_solo_dist"][2],
                "tmp_consistency_mode": staged["tmp_solo_dist"][2],
                "will_apply": bool(args.apply),
            }
            if not args.apply:
                print(json.dumps(plan, ensure_ascii=False, sort_keys=True))
                conn.rollback()
                return 0

            assert_level3_registry_ready(cur)
            cur.execute("SET LOCAL lock_timeout = '10s'")
            cur.execute("SET LOCAL statement_timeout = '5min'")
            create_audit_table(cur)
            cur.execute(
                f"""
                SELECT 1
                FROM {ident(REGISTRY_SCHEMA)}.product_uom_level3_mapping_apply_run
                WHERE batch_id = %s
                """,
                (BATCH_ID,),
            )
            if cur.fetchone():
                raise RuntimeError(f"Batch {BATCH_ID} sudah pernah dijalankan.")

            product_mappings = [*bdm_products, *tmp_products]
            base_uom_mappings = [*bdm_base_uoms, *tmp_base_uoms]
            level3_uom_mappings = [*bdm_level3_uoms, *tmp_level3_uoms]
            insert_product_mappings(cur, product_mappings)
            # The registry trigger requires level 1 to exist before it allows
            # the associated level-3 map, so keep these statements separate.
            insert_uom_mappings(
                cur,
                base_uom_mappings,
                "UOM dasar source cocok tepat dengan target level 1/faktor 1.",
            )
            insert_uom_mappings(
                cur,
                level3_uom_mappings,
                "UOM outer source cocok tepat dengan target level 3; rantai target level 2 tunggal dan faktor pembagi tervalidasi.",
            )
            cur.execute(
                f"""
                INSERT INTO {ident(REGISTRY_SCHEMA)}.product_uom_level3_mapping_apply_run
                    (batch_id, bdm_stage_schema, tmp_stage_schema,
                     bdm_consistency_mode, tmp_consistency_mode,
                     bdm_product_mapped, tmp_product_mapped,
                     bdm_base_uom_mapped, tmp_base_uom_mapped,
                     bdm_level3_uom_mapped, tmp_level3_uom_mapped,
                     bdm_held, tmp_held)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                """,
                (
                    BATCH_ID,
                    args.bdm_schema,
                    args.tmp_schema,
                    staged["bdm_solo_dist"][2],
                    staged["tmp_solo_dist"][2],
                    len(bdm_products),
                    len(tmp_products),
                    len(bdm_base_uoms),
                    len(tmp_base_uoms),
                    len(bdm_level3_uoms),
                    len(tmp_level3_uoms),
                    json.dumps(plan["bdm_held"]),
                    json.dumps(plan["tmp_held"]),
                ),
            )
        conn.commit()
        print(json.dumps(plan, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
