#!/usr/bin/env python3
"""Register only exact legacy sales mappings without changing public sales/users.

Eligibility is deliberately strict: a source sales row must have an approved
principal mapping and exactly one existing ``public.sales`` record whose user
belongs to the source company/branch and has the same normalized name.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any

import psycopg2  # type: ignore[import-not-found]
from psycopg2.extras import execute_values  # type: ignore[import-not-found]


REGISTRY_SCHEMA = "migration_bdm_tmp_202608"
BATCH_ID = "exact_sales_mapping_lowtraffic_20260827"
IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
SOURCE_SYSTEMS = ("bdm_solo_dist", "tmp_solo_dist")


@dataclass(frozen=True)
class SalesMapping:
    source_system: str
    source_principal_code: str
    source_principal_code_norm: str
    source_sales_code: str
    source_sales_code_norm: str
    id_sales: int


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
    text = clean(value)
    return text.lower() if text else None


def name_norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return "".join(char for char in text.casefold() if char.isalnum())


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


def fetch_stage_rows(cur, schema: str, source_system: str) -> tuple[list[dict[str, str]], str]:
    schema_q = ident(schema)
    cur.execute(f"SELECT status, consistency_mode FROM {schema_q}.\"__stage_run\" ORDER BY id DESC LIMIT 1")
    run = cur.fetchone()
    if not run or run[0] != "completed":
        raise RuntimeError(f"Staging {schema} belum completed.")
    cur.execute(
        f"SELECT btrim(kode), nama, btrim(kodeprinciple) FROM {schema_q}.sales WHERE source_system=%s",
        (source_system,),
    )
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw_code, raw_name, raw_principal in cur.fetchall():
        sales_code, principal_code = clean(raw_code), clean(raw_principal)
        sales_norm, principal_norm = code_norm(sales_code), code_norm(principal_code)
        if not sales_code or not sales_norm:
            rows.append({"invalid": "source_sales_code"})
            continue
        if not principal_code or not principal_norm:
            rows.append({"invalid": "source_principal_code"})
            continue
        key = (principal_norm, sales_norm)
        if key in seen:
            raise RuntimeError(f"{source_system}: kode sales ganda dalam principal: {principal_code}/{sales_code}")
        seen.add(key)
        rows.append(
            {
                "source_sales_code": sales_code,
                "source_sales_code_norm": sales_norm,
                "source_name": clean(raw_name) or "",
                "source_principal_code": principal_code,
                "source_principal_code_norm": principal_norm,
            }
        )
    return rows, str(run[1])


def build_mappings(cur, source_system: str, source_rows: list[dict[str, str]]) -> tuple[list[SalesMapping], Counter[str]]:
    registry = ident(REGISTRY_SCHEMA)
    cur.execute(f"SELECT target_company_id,target_branch_id FROM {registry}.source_context WHERE source_system=%s", (source_system,))
    context = cur.fetchone()
    if not context:
        raise RuntimeError(f"Source context belum tersedia: {source_system}")
    company_id, branch_id = (int(context[0]), int(context[1]))
    cur.execute(f"SELECT source_principal_code_norm,id_principal FROM {registry}.principal_map WHERE source_system=%s", (source_system,))
    principal_map = {str(code): int(principal_id) for code, principal_id in cur.fetchall()}
    cur.execute(
        """
        SELECT s.id,s.id_principal,u.nama
        FROM public.sales s
        JOIN public.users u ON u.id=s.id_user
        WHERE u.id_perusahaan=%s AND u.id_cabang=%s
        """,
        (company_id, branch_id),
    )
    targets: dict[tuple[int, str], list[int]] = {}
    for sales_id, principal_id, user_name in cur.fetchall():
        normalized_name = name_norm(user_name)
        if normalized_name and principal_id is not None:
            targets.setdefault((int(principal_id), normalized_name), []).append(int(sales_id))
    outcomes: Counter[str] = Counter()
    mappings: list[SalesMapping] = []
    for source in source_rows:
        if "invalid" in source:
            outcomes[f"held_{source['invalid']}"] += 1
            continue
        target_principal = principal_map.get(source["source_principal_code_norm"])
        if target_principal is None:
            outcomes["held_missing_principal_map"] += 1
            continue
        normalized_name = name_norm(source["source_name"])
        if not normalized_name:
            outcomes["held_blank_sales_name"] += 1
            continue
        candidates = targets.get((target_principal, normalized_name), [])
        if len(candidates) == 0:
            outcomes["held_missing_target_sales"] += 1
            continue
        if len(candidates) > 1:
            outcomes["held_duplicate_target_sales"] += 1
            continue
        mappings.append(
            SalesMapping(
                source_system,
                source["source_principal_code"],
                source["source_principal_code_norm"],
                source["source_sales_code"],
                source["source_sales_code_norm"],
                candidates[0],
            )
        )
    if len({(m.source_principal_code_norm, m.source_sales_code_norm) for m in mappings}) != len(mappings):
        raise RuntimeError(f"{source_system}: kandidat mapping sales ganda.")
    target_counts = Counter(item.id_sales for item in mappings)
    duplicate_targets = {target_id for target_id, count in target_counts.items() if count > 1}
    if duplicate_targets:
        outcomes["held_duplicate_source_target"] += sum(
            1 for item in mappings if item.id_sales in duplicate_targets
        )
        mappings = [item for item in mappings if item.id_sales not in duplicate_targets]
    outcomes["exact_sales"] = len(mappings)
    return mappings, outcomes


def create_audit_table(cur) -> None:
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {ident(REGISTRY_SCHEMA)}.sales_mapping_apply_run (
            batch_id text PRIMARY KEY,
            bdm_stage_schema text NOT NULL,
            tmp_stage_schema text NOT NULL,
            bdm_consistency_mode text NOT NULL,
            tmp_consistency_mode text NOT NULL,
            bdm_mapped integer NOT NULL,
            tmp_mapped integer NOT NULL,
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
    conn = psycopg2.connect(dbname=args.pg_database, user=args.pg_user, host=args.pg_host, port=args.pg_port)
    try:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            staged = {
                "bdm_solo_dist": (args.bdm_schema, *fetch_stage_rows(cur, args.bdm_schema, "bdm_solo_dist")),
                "tmp_solo_dist": (args.tmp_schema, *fetch_stage_rows(cur, args.tmp_schema, "tmp_solo_dist")),
            }
            bdm_mappings, bdm_outcomes = build_mappings(cur, "bdm_solo_dist", staged["bdm_solo_dist"][1])
            tmp_mappings, tmp_outcomes = build_mappings(cur, "tmp_solo_dist", staged["tmp_solo_dist"][1])
            for source_system in SOURCE_SYSTEMS:
                cur.execute(f"SELECT count(*) FROM {ident(REGISTRY_SCHEMA)}.sales_map WHERE source_system=%s", (source_system,))
                if int(cur.fetchone()[0]) != 0:
                    raise RuntimeError(f"Registry sales_map {source_system} sudah terisi; batch tidak mencampur mapping lama.")
            plan = {
                "bdm_mapped": len(bdm_mappings),
                "tmp_mapped": len(tmp_mappings),
                "bdm_held": dict(sorted((key, value) for key, value in bdm_outcomes.items() if key != "exact_sales")),
                "tmp_held": dict(sorted((key, value) for key, value in tmp_outcomes.items() if key != "exact_sales")),
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
            cur.execute(f"SELECT 1 FROM {ident(REGISTRY_SCHEMA)}.sales_mapping_apply_run WHERE batch_id=%s", (BATCH_ID,))
            if cur.fetchone():
                raise RuntimeError(f"Batch {BATCH_ID} sudah pernah dijalankan.")
            mappings = [*bdm_mappings, *tmp_mappings]
            execute_values(
                cur,
                f"""
                INSERT INTO {ident(REGISTRY_SCHEMA)}.sales_map
                    (source_system, source_principal_code, source_principal_code_norm,
                     source_sales_code, source_sales_code_norm, id_sales,
                     mapping_method, approved_by, reviewer_note)
                VALUES %s
                """,
                [
                    (m.source_system, m.source_principal_code, m.source_principal_code_norm,
                     m.source_sales_code, m.source_sales_code_norm, m.id_sales,
                     "exact_reviewed", "policy_approved_20260827",
                     "Principal, perusahaan/cabang, dan nama sales cocok tepat dengan target.")
                    for m in mappings
                ],
                page_size=500,
            )
            cur.execute(
                f"""
                INSERT INTO {ident(REGISTRY_SCHEMA)}.sales_mapping_apply_run
                    (batch_id,bdm_stage_schema,tmp_stage_schema,
                     bdm_consistency_mode,tmp_consistency_mode,
                     bdm_mapped,tmp_mapped,bdm_held,tmp_held)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)
                """,
                (
                    BATCH_ID, args.bdm_schema, args.tmp_schema,
                    staged["bdm_solo_dist"][2], staged["tmp_solo_dist"][2],
                    len(bdm_mappings), len(tmp_mappings),
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
