#!/usr/bin/env python3
"""Register only exact BDM/TMP product and UOM mappings from low-traffic staging.

This is a mapping-only batch: it never inserts, updates, or deletes rows in
``public.produk`` or ``public.produk_uom``.  A source product qualifies only
when all of the following are exact and unambiguous:

1. its source principal already has an approved principal mapping;
2. SKU and normalized product name match one target product under that
   principal;
3. base UOM (factor 1) and outer UOM (``NamaUnit``/``PerUnit``) both match
   existing target UOM rows.

Everything else is counted as held for review; there is no heuristic UOM
conversion or product creation in this script.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import psycopg2  # type: ignore[import-not-found]
from psycopg2.extras import execute_values  # type: ignore[import-not-found]


REGISTRY_SCHEMA = "migration_bdm_tmp_202608"
BATCH_ID = "exact_product_uom_mapping_lowtraffic_20260827"
IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
SOURCE_SYSTEMS = ("bdm_solo_dist", "tmp_solo_dist")


@dataclass(frozen=True)
class ProductMapping:
    source_system: str
    source_principal_code: str
    source_principal_code_norm: str
    source_sku: str
    source_sku_norm: str
    id_produk: int


@dataclass(frozen=True)
class UomMapping:
    source_system: str
    source_principal_code: str
    source_principal_code_norm: str
    source_sku: str
    source_sku_norm: str
    source_uom_code: str
    source_uom_code_norm: str
    source_uom_level: int
    source_factor: int
    id_produk: int
    id_produk_uom: int


def ident(value: str) -> str:
    if not IDENT_RE.fullmatch(value):
        raise ValueError(f"Identifier PostgreSQL tidak aman: {value!r}")
    return f'"{value}"'


def clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def code_norm(value: Any) -> str | None:
    value = clean(value)
    return value.lower() if value else None


def name_norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return "".join(char for char in text.casefold() if char.isalnum())


def factor(value: Any) -> int | None:
    try:
        parsed = Decimal(str(value or "").strip())
    except (InvalidOperation, ValueError):
        return None
    if parsed <= 0 or parsed != parsed.to_integral_value():
        return None
    return int(parsed)


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


def fetch_stage_rows(cur, schema: str, source_system: str) -> tuple[list[dict[str, Any]], str]:
    schema_q = ident(schema)
    cur.execute(f"SELECT status, consistency_mode FROM {schema_q}.\"__stage_run\" ORDER BY id DESC LIMIT 1")
    stage_run = cur.fetchone()
    if not stage_run or stage_run[0] != "completed":
        raise RuntimeError(f"Staging {schema} belum completed.")
    cur.execute(
        f"""
        SELECT btrim(kode), btrim(nama), btrim(principle), btrim(satuan), btrim(namaunit), perunit
        FROM {schema_q}.stok
        WHERE source_system = %s
        """,
        (source_system,),
    )
    rows = []
    seen: set[tuple[str, str]] = set()
    for raw_sku, raw_name, raw_principal, raw_base_uom, raw_outer_uom, raw_factor in cur.fetchall():
        sku = clean(raw_sku)
        principal = clean(raw_principal)
        sku_key = code_norm(sku)
        principal_key = code_norm(principal)
        if not sku or not principal or not sku_key or not principal_key:
            raise RuntimeError(f"{source_system}: STOK memiliki SKU atau principal kosong.")
        key = (principal_key, sku_key)
        if key in seen:
            raise RuntimeError(f"{source_system}: SKU STOK ganda dalam principal: {principal}/{sku}")
        seen.add(key)
        rows.append(
            {
                "source_system": source_system,
                "source_sku": sku,
                "source_sku_norm": sku_key,
                "source_name": clean(raw_name),
                "source_principal_code": principal,
                "source_principal_code_norm": principal_key,
                "base_uom": clean(raw_base_uom),
                "outer_uom": clean(raw_outer_uom),
                "factor": factor(raw_factor),
            }
        )
    return rows, str(stage_run[1])


def load_principal_maps(cur, source_system: str) -> dict[str, int]:
    cur.execute(
        f"""
        SELECT source_principal_code_norm, id_principal
        FROM {ident(REGISTRY_SCHEMA)}.principal_map
        WHERE source_system=%s
        """,
        (source_system,),
    )
    return {str(code): int(target) for code, target in cur.fetchall()}


def load_products(cur, principal_ids: set[int]) -> dict[tuple[int, str], list[tuple[int, str | None]]]:
    if not principal_ids:
        return {}
    cur.execute(
        "SELECT id, id_principal, kode_sku, nama FROM public.produk WHERE id_principal = ANY(%s)",
        (sorted(principal_ids),),
    )
    candidates: dict[tuple[int, str], list[tuple[int, str | None]]] = {}
    for product_id, principal_id, sku, name in cur.fetchall():
        sku_key = code_norm(sku)
        if sku_key:
            candidates.setdefault((int(principal_id), sku_key), []).append((int(product_id), name))
    return candidates


def load_uoms(cur, product_ids: set[int]) -> dict[int, dict[tuple[str, int, int], list[int]]]:
    if not product_ids:
        return {}
    cur.execute(
        "SELECT id, id_produk, kode, level, faktor_konversi FROM public.produk_uom WHERE id_produk = ANY(%s)",
        (sorted(product_ids),),
    )
    result: dict[int, dict[tuple[str, int, int], list[int]]] = {}
    for uom_id, product_id, code, level, uom_factor in cur.fetchall():
        uom_code = code_norm(code)
        parsed_factor = factor(uom_factor)
        parsed_level = int(level) if level is not None else None
        if uom_code and parsed_factor and parsed_level in (1, 2):
            result.setdefault(int(product_id), {}).setdefault((uom_code, parsed_level, parsed_factor), []).append(int(uom_id))
    return result


def build_mappings(
    cur,
    rows: list[dict[str, Any]],
    source_system: str,
) -> tuple[list[ProductMapping], list[UomMapping], Counter[str]]:
    principal_map = load_principal_maps(cur, source_system)
    products = load_products(cur, set(principal_map.values()))
    uoms = load_uoms(cur, {product_id for values in products.values() for product_id, _ in values})
    outcomes: Counter[str] = Counter()
    product_mappings: list[ProductMapping] = []
    uom_mappings: list[UomMapping] = []
    for source in rows:
        target_principal = principal_map.get(source["source_principal_code_norm"])
        if target_principal is None:
            outcomes["held_missing_principal_map"] += 1
            continue
        products_for_sku = products.get((target_principal, source["source_sku_norm"]), [])
        if len(products_for_sku) == 0:
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
        product_uoms = uoms.get(product_id, {})
        base_candidates = product_uoms.get((base_code, 1, 1), [])
        outer_candidates = product_uoms.get((outer_code, 2, outer_factor), [])
        if len(base_candidates) != 1:
            outcomes["held_base_uom_mismatch"] += 1
            continue
        if len(outer_candidates) != 1:
            outcomes["held_outer_uom_mismatch"] += 1
            continue
        product_mappings.append(
            ProductMapping(
                source_system,
                source["source_principal_code"],
                source["source_principal_code_norm"],
                source["source_sku"],
                source["source_sku_norm"],
                product_id,
            )
        )
        uom_mappings.append(
            UomMapping(
                source_system,
                source["source_principal_code"],
                source["source_principal_code_norm"],
                source["source_sku"],
                source["source_sku_norm"],
                source["base_uom"],
                base_code,
                1,
                1,
                product_id,
                base_candidates[0],
            )
        )
        if (outer_code, outer_factor) != (base_code, 1):
            uom_mappings.append(
                UomMapping(
                    source_system,
                    source["source_principal_code"],
                    source["source_principal_code_norm"],
                    source["source_sku"],
                    source["source_sku_norm"],
                    source["outer_uom"],
                    outer_code,
                    2,
                    outer_factor,
                    product_id,
                    outer_candidates[0],
                )
            )
        outcomes["exact_product_uom"] += 1
    product_keys = {(m.source_system, m.source_principal_code_norm, m.source_sku_norm) for m in product_mappings}
    uom_keys = {
        (m.source_system, m.source_principal_code_norm, m.source_sku_norm, m.source_uom_code_norm, m.source_uom_level, m.source_factor)
        for m in uom_mappings
    }
    if len(product_keys) != len(product_mappings) or len(uom_keys) != len(uom_mappings):
        raise RuntimeError(f"{source_system}: kandidat product/UOM mapping ganda.")
    return product_mappings, uom_mappings, outcomes


def create_audit_table(cur) -> None:
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {ident(REGISTRY_SCHEMA)}.product_uom_mapping_apply_run (
            batch_id text PRIMARY KEY,
            bdm_stage_schema text NOT NULL,
            tmp_stage_schema text NOT NULL,
            bdm_consistency_mode text NOT NULL,
            tmp_consistency_mode text NOT NULL,
            bdm_product_mapped integer NOT NULL,
            tmp_product_mapped integer NOT NULL,
            bdm_uom_mapped integer NOT NULL,
            tmp_uom_mapped integer NOT NULL,
            bdm_held jsonb NOT NULL,
            tmp_held jsonb NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def main() -> int:
    args = parse_args()
    ident(args.bdm_schema)
    ident(args.tmp_schema)
    conn = psycopg2.connect(
        dbname=args.pg_database, user=args.pg_user, host=args.pg_host, port=args.pg_port
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            staged = {
                "bdm_solo_dist": (args.bdm_schema, *fetch_stage_rows(cur, args.bdm_schema, "bdm_solo_dist")),
                "tmp_solo_dist": (args.tmp_schema, *fetch_stage_rows(cur, args.tmp_schema, "tmp_solo_dist")),
            }
            plan_data: dict[str, tuple[list[ProductMapping], list[UomMapping], Counter[str]]] = {}
            for source_system in SOURCE_SYSTEMS:
                plan_data[source_system] = build_mappings(cur, staged[source_system][1], source_system)
                for table in ("product_map", "product_uom_map"):
                    cur.execute(f"SELECT count(*) FROM {ident(REGISTRY_SCHEMA)}.{table} WHERE source_system=%s", (source_system,))
                    if int(cur.fetchone()[0]) != 0:
                        raise RuntimeError(f"Registry {table} {source_system} sudah terisi; batch tidak mencampur mapping lama.")
            bdm_products, bdm_uoms, bdm_outcomes = plan_data["bdm_solo_dist"]
            tmp_products, tmp_uoms, tmp_outcomes = plan_data["tmp_solo_dist"]
            plan = {
                "bdm_product_mapped": len(bdm_products),
                "tmp_product_mapped": len(tmp_products),
                "bdm_uom_mapped": len(bdm_uoms),
                "tmp_uom_mapped": len(tmp_uoms),
                "bdm_held": dict(sorted((key, value) for key, value in bdm_outcomes.items() if key != "exact_product_uom")),
                "tmp_held": dict(sorted((key, value) for key, value in tmp_outcomes.items() if key != "exact_product_uom")),
                "bdm_consistency_mode": staged["bdm_solo_dist"][2],
                "tmp_consistency_mode": staged["tmp_solo_dist"][2],
                "will_apply": bool(args.apply),
            }
            if not args.apply:
                print(json.dumps(plan, ensure_ascii=False, sort_keys=True))
                conn.rollback()
                return 0
            cur.execute("SET LOCAL lock_timeout = '10s'")
            cur.execute("SET LOCAL statement_timeout = '5min'")
            create_audit_table(cur)
            cur.execute(f"SELECT 1 FROM {ident(REGISTRY_SCHEMA)}.product_uom_mapping_apply_run WHERE batch_id=%s", (BATCH_ID,))
            if cur.fetchone():
                raise RuntimeError(f"Batch {BATCH_ID} sudah pernah dijalankan.")
            product_rows = [*bdm_products, *tmp_products]
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
                    (m.source_system, m.source_principal_code, m.source_principal_code_norm,
                     m.source_sku, m.source_sku_norm, m.id_produk,
                     "exact_reviewed", "policy_approved_20260827",
                     "Principal, SKU, nama produk, dan UOM sumber cocok tepat dengan target.")
                    for m in product_rows
                ],
                page_size=1000,
            )
            uom_rows = [*bdm_uoms, *tmp_uoms]
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
                    (m.source_system, m.source_principal_code, m.source_principal_code_norm,
                     m.source_sku, m.source_sku_norm, m.source_uom_code, m.source_uom_code_norm,
                     m.source_uom_level, m.source_factor, m.id_produk, m.id_produk_uom,
                     "exact_reviewed", "policy_approved_20260827",
                     "Kode UOM dan faktor konversi cocok tepat dengan target.")
                    for m in uom_rows
                ],
                page_size=1000,
            )
            cur.execute(
                f"""
                INSERT INTO {ident(REGISTRY_SCHEMA)}.product_uom_mapping_apply_run
                    (batch_id, bdm_stage_schema, tmp_stage_schema,
                     bdm_consistency_mode, tmp_consistency_mode,
                     bdm_product_mapped, tmp_product_mapped, bdm_uom_mapped, tmp_uom_mapped,
                     bdm_held, tmp_held)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                """,
                (
                    BATCH_ID, args.bdm_schema, args.tmp_schema,
                    staged["bdm_solo_dist"][2], staged["tmp_solo_dist"][2],
                    len(bdm_products), len(tmp_products), len(bdm_uoms), len(tmp_uoms),
                    json.dumps(plan["bdm_held"]), json.dumps(plan["tmp_held"]),
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
