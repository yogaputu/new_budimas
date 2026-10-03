#!/usr/bin/env python3
"""Apply only unambiguous BDM/TMP principal records from the low-traffic stage.

A source principal is eligible only when exactly one existing PostgreSQL
principal exists in its source-company scope with both the same trimmed code
and the same normalized name.  No principal is created or deleted.  The
remaining ambiguous/mismatched source principals are intentionally held for
review, because their product and sales depend on the chosen principal.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import psycopg2  # type: ignore[import-not-found]


REGISTRY_SCHEMA = "migration_bdm_tmp_202608"
BATCH_ID = "principal_master_lowtraffic_20260827"
IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
SOURCES = (
    ("bdm_solo_dist", "bdm"),
    ("tmp_solo_dist", "tmp"),
)
FIELD_MAP = (
    ("nama", "nama", 50),
    ("alamat", "alamat", None),
    ("telepon", "telpon", 13),
    ("npwp", "npwp", 25),
    ("no_rekening", "account", 20),
    ("pic", "contactperson", 50),
)


@dataclass(frozen=True)
class Mapping:
    source_system: str
    source_code: str
    source_code_norm: str
    target_id: int


def ident(value: str) -> str:
    if not IDENT_RE.fullmatch(value):
        raise ValueError(f"Identifier PostgreSQL tidak aman: {value!r}")
    return f'"{value}"'


def clean(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


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


def fetch_stage_rows(cur, schema: str, source_system: str) -> tuple[dict[str, dict[str, Any]], str]:
    schema_q = ident(schema)
    cur.execute(
        f"SELECT status, consistency_mode FROM {schema_q}.\"__stage_run\" ORDER BY id DESC LIMIT 1"
    )
    run = cur.fetchone()
    if not run or run[0] != "completed":
        raise RuntimeError(f"Staging {schema} belum completed.")
    cur.execute(
        f"""
        SELECT btrim(kode), lower(btrim(kode)), nama, alamat, telpon, npwp, account, contactperson
        FROM {schema_q}.principle
        WHERE source_system = %s
        """,
        (source_system,),
    )
    rows: dict[str, dict[str, Any]] = {}
    for record in cur.fetchall():
        code = clean(record[0])
        code_norm = clean(record[1])
        if not code or not code_norm:
            raise RuntimeError(f"{source_system}: kode principal kosong.")
        if code_norm in rows:
            raise RuntimeError(f"{source_system}: kode principal ganda: {code_norm}")
        item = {"source_code": code, "source_code_norm": code_norm}
        for index, (_, source_column, _) in enumerate(FIELD_MAP, start=2):
            item[source_column] = clean(record[index])
        rows[code_norm] = item
    return rows, str(run[1])


def build_mappings(cur, source_system: str, source_rows: dict[str, dict[str, Any]]) -> tuple[list[Mapping], int]:
    cur.execute(
        f"SELECT target_company_id FROM {ident(REGISTRY_SCHEMA)}.source_context WHERE source_system = %s",
        (source_system,),
    )
    context = cur.fetchone()
    if not context:
        raise RuntimeError(f"Source context belum ada: {source_system}")
    company_id = int(context[0])
    cur.execute(
        "SELECT id, kode, nama FROM public.principal WHERE id_perusahaan = %s",
        (company_id,),
    )
    candidates: dict[str, list[tuple[int, str | None]]] = {}
    for target_id, target_code, target_name in cur.fetchall():
        code_norm = clean(target_code)
        if code_norm:
            candidates.setdefault(code_norm.lower(), []).append((int(target_id), target_name))

    mappings: list[Mapping] = []
    for code_norm, source in source_rows.items():
        matches = candidates.get(code_norm, [])
        if len(matches) != 1:
            continue
        target_id, target_name = matches[0]
        if not name_norm(source.get("nama")) or name_norm(source.get("nama")) != name_norm(target_name):
            continue
        mappings.append(Mapping(source_system, source["source_code"], code_norm, target_id))
    if len({item.target_id for item in mappings}) != len(mappings):
        raise RuntimeError(f"{source_system}: target principal ganda pada kandidat otomatis.")
    return mappings, len(source_rows) - len(mappings)


def collect_exceptions(
    source_rows: dict[str, dict[str, Any]], mappings: list[Mapping]
) -> list[tuple[str, str, str, int, str, int, int]]:
    result: list[tuple[str, str, str, int, str, int, int]] = []
    for mapping in mappings:
        source = source_rows[mapping.source_code_norm]
        for target_column, source_column, limit in FIELD_MAP:
            value = source.get(source_column)
            if value is not None and limit is not None and len(value) > limit:
                result.append(
                    (
                        mapping.source_system,
                        mapping.source_code,
                        mapping.source_code_norm,
                        mapping.target_id,
                        target_column,
                        len(value),
                        limit,
                    )
                )
    return result


def create_audit_tables(cur) -> None:
    registry = ident(REGISTRY_SCHEMA)
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {registry}.principal_master_apply_run (
            batch_id text PRIMARY KEY,
            bdm_stage_schema text NOT NULL,
            tmp_stage_schema text NOT NULL,
            bdm_consistency_mode text NOT NULL,
            tmp_consistency_mode text NOT NULL,
            bdm_mapped_rows integer NOT NULL,
            tmp_mapped_rows integer NOT NULL,
            bdm_updated_rows integer NOT NULL,
            tmp_updated_rows integer NOT NULL,
            principal_count_before bigint NOT NULL,
            principal_count_after bigint NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {registry}.principal_master_value_exception (
            batch_id text NOT NULL,
            source_system text NOT NULL,
            source_principal_code text NOT NULL,
            source_principal_code_norm text NOT NULL,
            id_principal integer NOT NULL,
            target_column text NOT NULL,
            source_length integer NOT NULL,
            target_limit integer NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (batch_id, source_system, source_principal_code_norm, target_column)
        )
        """
    )


def apply_source(cur, schema: str, source_system: str) -> int:
    schema_q = ident(schema)
    registry = ident(REGISTRY_SCHEMA)
    selected = ",\n               ".join(
        (
            f"NULLIF(btrim(s.{ident(source_column)}), '') AS {ident(target_column)}"
            if limit is None
            else f"CASE WHEN char_length(NULLIF(btrim(s.{ident(source_column)}), '')) <= {limit} "
            f"THEN NULLIF(btrim(s.{ident(source_column)}), '') END AS {ident(target_column)}"
        )
        for target_column, source_column, limit in FIELD_MAP
    )
    assignments = ",\n               ".join(
        f"{ident(target_column)} = COALESCE(staged.{ident(target_column)}, p.{ident(target_column)})"
        for target_column, _, _ in FIELD_MAP
    )
    current = ", ".join(f"p.{ident(target_column)}" for target_column, _, _ in FIELD_MAP)
    replacement = ", ".join(
        f"COALESCE(staged.{ident(target_column)}, p.{ident(target_column)})"
        for target_column, _, _ in FIELD_MAP
    )
    cur.execute(
        f"""
        WITH staged AS (
            SELECT m.id_principal,
               {selected}
            FROM {schema_q}.principle s
            JOIN {registry}.principal_map m
              ON m.source_system = %s
             AND m.source_principal_code_norm = lower(btrim(s.kode))
            WHERE s.source_system = %s
        ), changed AS (
            UPDATE public.principal p
            SET {assignments}
            FROM staged
            WHERE p.id = staged.id_principal
              AND ROW({current}) IS DISTINCT FROM ROW({replacement})
            RETURNING p.id
        )
        SELECT count(*) FROM changed
        """,
        (source_system, source_system),
    )
    return int(cur.fetchone()[0])


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
            stages = {
                "bdm_solo_dist": (args.bdm_schema, *fetch_stage_rows(cur, args.bdm_schema, "bdm_solo_dist")),
                "tmp_solo_dist": (args.tmp_schema, *fetch_stage_rows(cur, args.tmp_schema, "tmp_solo_dist")),
            }
            mappings: dict[str, list[Mapping]] = {}
            held: dict[str, int] = {}
            for source_system, (_, source_rows, _) in stages.items():
                mappings[source_system], held[source_system] = build_mappings(cur, source_system, source_rows)
                cur.execute(
                    f"SELECT count(*) FROM {ident(REGISTRY_SCHEMA)}.principal_map WHERE source_system = %s",
                    (source_system,),
                )
                if int(cur.fetchone()[0]) != 0:
                    raise RuntimeError(f"Registry principal_map {source_system} sudah terisi; batch ini tidak mencampur mapping lama.")
            exceptions = [
                *collect_exceptions(stages["bdm_solo_dist"][1], mappings["bdm_solo_dist"]),
                *collect_exceptions(stages["tmp_solo_dist"][1], mappings["tmp_solo_dist"]),
            ]
            cur.execute("SELECT count(*) FROM public.principal")
            principal_count = int(cur.fetchone()[0])
            plan = {
                "bdm_mapped_rows": len(mappings["bdm_solo_dist"]),
                "tmp_mapped_rows": len(mappings["tmp_solo_dist"]),
                "bdm_held_for_review": held["bdm_solo_dist"],
                "tmp_held_for_review": held["tmp_solo_dist"],
                "overlength_values_held": len(exceptions),
                "public_principal_count": principal_count,
                "bdm_consistency_mode": stages["bdm_solo_dist"][2],
                "tmp_consistency_mode": stages["tmp_solo_dist"][2],
                "will_apply": bool(args.apply),
            }
            if not args.apply:
                print(json.dumps(plan, ensure_ascii=False, sort_keys=True))
                conn.rollback()
                return 0
            cur.execute("SET LOCAL lock_timeout = '10s'")
            cur.execute("SET LOCAL statement_timeout = '5min'")
            create_audit_tables(cur)
            cur.execute(f"SELECT 1 FROM {ident(REGISTRY_SCHEMA)}.principal_master_apply_run WHERE batch_id=%s", (BATCH_ID,))
            if cur.fetchone():
                raise RuntimeError(f"Batch {BATCH_ID} sudah pernah dijalankan.")
            all_mappings = [*mappings["bdm_solo_dist"], *mappings["tmp_solo_dist"]]
            cur.executemany(
                f"""
                INSERT INTO {ident(REGISTRY_SCHEMA)}.principal_map
                    (source_system, source_principal_code, source_principal_code_norm,
                     id_principal, mapping_method, approved_by, reviewer_note)
                VALUES (%s, %s, %s, %s, 'exact_reviewed', 'policy_approved_20260827',
                        'Kode dan nama principal cocok tepat dalam scope perusahaan sumber.')
                """,
                [(m.source_system, m.source_code, m.source_code_norm, m.target_id) for m in all_mappings],
            )
            bdm_updated = apply_source(cur, args.bdm_schema, "bdm_solo_dist")
            tmp_updated = apply_source(cur, args.tmp_schema, "tmp_solo_dist")
            cur.execute("SELECT count(*) FROM public.principal")
            after_count = int(cur.fetchone()[0])
            if after_count != principal_count:
                raise RuntimeError("Jumlah public.principal berubah; transaksi dibatalkan.")
            cur.execute(
                f"""
                INSERT INTO {ident(REGISTRY_SCHEMA)}.principal_master_apply_run
                    (batch_id, bdm_stage_schema, tmp_stage_schema,
                     bdm_consistency_mode, tmp_consistency_mode,
                     bdm_mapped_rows, tmp_mapped_rows,
                     bdm_updated_rows, tmp_updated_rows,
                     principal_count_before, principal_count_after)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    BATCH_ID, args.bdm_schema, args.tmp_schema,
                    stages["bdm_solo_dist"][2], stages["tmp_solo_dist"][2],
                    len(mappings["bdm_solo_dist"]), len(mappings["tmp_solo_dist"]),
                    bdm_updated, tmp_updated, principal_count, after_count,
                ),
            )
            cur.executemany(
                f"""
                INSERT INTO {ident(REGISTRY_SCHEMA)}.principal_master_value_exception
                    (batch_id, source_system, source_principal_code, source_principal_code_norm,
                     id_principal, target_column, source_length, target_limit)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [(BATCH_ID, *item) for item in exceptions],
            )
            plan.update({
                "bdm_updated_rows": bdm_updated,
                "tmp_updated_rows": tmp_updated,
                "public_principal_count_after": after_count,
            })
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
