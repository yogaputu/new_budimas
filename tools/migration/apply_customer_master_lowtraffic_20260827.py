#!/usr/bin/env python3
"""Apply the approved BDM/TMP customer-master mapping for 27 August 2026.

This tool is deliberately narrow:

* it reads only the two Customer-only staging schemas;
* it does not create or delete ``public.customer`` rows;
* it updates the approved descriptive fields only;
* BDM is applied first and TMP is applied last for a shared target customer;
* unmatched BDM and all unresolved TMP source rows are excluded.

Run without ``--apply`` for a read-only validation and dry-run.  ``--apply``
executes the mapping additions and public updates in one PostgreSQL
transaction.
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

try:
    import psycopg2  # type: ignore[import-not-found]
except ImportError as exc:  # pragma: no cover - dependency error is actionable
    raise SystemExit("Modul psycopg2 diperlukan.") from exc


REGISTRY_SCHEMA = "migration_bdm_tmp_202608"
BDM_SOURCE = "bdm_solo_dist"
TMP_SOURCE = "tmp_solo_dist"
BATCH_ID = "customer_master_lowtraffic_20260827"
IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

# Target-column, source-column pairs.  Blank source values intentionally do
# not erase an existing PostgreSQL value.
FIELD_MAP = (
    ("nama", "nama"),
    ("alamat", "alamat"),
    ("telepon", "telpon"),
    ("npwp", "npwp"),
    ("email", "email"),
    ("nama_wajib_pajak", "namawp"),
    ("alamat_wajib_pajak", "alamatwp"),
    ("longitude", "longitude"),
    ("latitude", "latitude"),
)


@dataclass(frozen=True)
class Resolution:
    code_norm: str
    target_id: int
    method: str
    note: str
    exact_code: bool = False


# These 31 BDM rows were reviewed under the approved name policy: exact
# normalized store name, with the lowest public.customer id chosen only where
# equal-name candidates were tied.  The two cross-branch rows were explicitly
# approved in the same review.
BDM_NAME_RESOLUTIONS = (
    Resolution("6636kltrt", 66307, "cross_branch_approved", "Nama toko sama; target lintas cabang disetujui."),
    Resolution("9106kltrt", 65730, "cross_branch_approved", "Nama toko sama; target lintas cabang disetujui."),
    Resolution("0041ktsrt", 47236, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("0073srgrt", 47513, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("0092slurt", 47653, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("0531krart", 50155, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("0995srgrt", 52314, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("1100slurt", 52732, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("1745krart", 54723, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("1875kltrt", 89740, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("2077slsrt", 55732, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("2147slurt", 56019, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("2193skhrt", 89414, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("2195krart", 56279, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("2345bylrt", 65797, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("2350bylrt", 56720, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("2465skhrt", 57012, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("2519bylrt", 67982, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("3370srgrt", 59249, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("3774krart", 67988, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("4122skhmm", 67933, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("4158slsrt", 67922, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("4701krart", 62210, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("4703slsrt", 62215, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("4805slsrt", 62461, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("4855srgrt", 62553, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("5177slsrt", 62960, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("5288srgrt", 67931, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("6400srgrt", 63768, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("6534kltrt", 90824, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
    Resolution("7853slurt", 67994, "exact_reviewed", "Nama toko sama; target deterministik hasil review."),
)

# This customer arrived after the earlier preview.  Unlike the name-only
# cases, its source code itself exactly matches the existing PostgreSQL code.
BDM_CURRENT_EXACT_CODE = Resolution(
    "2586bylrt",
    109733,
    "exact_reviewed",
    "Kode customer sumber sama persis dengan customer PostgreSQL saat snapshot low-traffic.",
    exact_code=True,
)


def ident(value: str) -> str:
    if not IDENT_RE.fullmatch(value):
        raise ValueError(f"Identifier PostgreSQL tidak aman: {value!r}")
    return '"' + value + '"'


def clean(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


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
    parser.add_argument("--apply", action="store_true", help="Commit mapping additions and public.customer updates.")
    return parser.parse_args()


def fetch_stage(cur, schema: str, source_system: str) -> tuple[dict[str, dict[str, Any]], str]:
    schema_q = ident(schema)
    cur.execute(
        f"""
        SELECT status, consistency_mode
        FROM {schema_q}."__stage_run"
        ORDER BY id DESC
        LIMIT 1
        """
    )
    run = cur.fetchone()
    if not run or run[0] != "completed":
        raise RuntimeError(f"Staging {schema} belum berstatus completed.")
    consistency_mode = str(run[1])
    cur.execute(
        f"""
        SELECT lower(btrim(kode)) AS code_norm,
               btrim(kode) AS source_code,
               nama, alamat, telpon, npwp, email, namawp, alamatwp, longitude, latitude
        FROM {schema_q}.customer
        WHERE source_system = %s
        """,
        (source_system,),
    )
    rows: dict[str, dict[str, Any]] = {}
    for record in cur.fetchall():
        code_norm = clean(record[0])
        source_code = clean(record[1])
        if not code_norm or not source_code:
            raise RuntimeError(f"{source_system}: terdapat kode customer kosong.")
        if code_norm in rows:
            raise RuntimeError(f"{source_system}: kode customer ganda pada staging: {code_norm}")
        item = {"code_norm": code_norm, "source_code": source_code}
        for index, (_, source_column) in enumerate(FIELD_MAP, start=2):
            item[source_column] = clean(record[index])
        rows[code_norm] = item
    if not rows:
        raise RuntimeError(f"{source_system}: staging Customer kosong.")
    return rows, consistency_mode


def fetch_customer_targets(cur, target_ids: set[int]) -> dict[int, dict[str, Any]]:
    if not target_ids:
        return {}
    cur.execute(
        """
        SELECT id, kode, nama, alamat, telepon, npwp, email,
               nama_wajib_pajak, alamat_wajib_pajak, longitude, latitude
        FROM public.customer
        WHERE id = ANY(%s)
        """,
        (sorted(target_ids),),
    )
    targets: dict[int, dict[str, Any]] = {}
    for row in cur.fetchall():
        item = {"id": int(row[0]), "kode": row[1]}
        for index, (target_column, _) in enumerate(FIELD_MAP, start=2):
            item[target_column] = row[index]
        targets[item["id"]] = item
    missing = sorted(target_ids - set(targets))
    if missing:
        raise RuntimeError(f"Target public.customer tidak ditemukan: {missing[:10]}")
    return targets


def fetch_existing_maps(cur, source_system: str) -> dict[str, int]:
    cur.execute(
        f"""
        SELECT source_customer_code_norm, id_customer
        FROM {ident(REGISTRY_SCHEMA)}.customer_map
        WHERE source_system = %s
        """,
        (source_system,),
    )
    result = {str(code): int(target_id) for code, target_id in cur.fetchall()}
    if len(result) == 0:
        raise RuntimeError(f"Registry mapping {source_system} kosong.")
    if len(set(result.values())) != len(result):
        raise RuntimeError(f"Registry {source_system} memetakan lebih dari satu kode ke target yang sama.")
    return result


def fetch_target_limits(cur) -> dict[str, int]:
    target_columns = [target_column for target_column, _ in FIELD_MAP]
    cur.execute(
        """
        SELECT column_name, character_maximum_length
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'customer'
          AND column_name = ANY(%s)
        """,
        (target_columns,),
    )
    limits = {str(column): int(limit) for column, limit in cur.fetchall() if limit is not None}
    missing = [column for column in target_columns if column not in limits]
    if missing:
        raise RuntimeError(f"Batas panjang kolom public.customer tidak tersedia: {missing}")
    return limits


def source_value_within_limit(value: str | None, limit: int) -> str | None:
    """Return a nonblank source value only when it fits the target column."""
    if value is None or len(value) > limit:
        return None
    return value


def collect_overlength_values(
    source_system: str,
    rows: dict[str, dict[str, Any]],
    mapping: dict[str, int],
    target_limits: dict[str, int],
) -> list[tuple[str, str, str, int, str, int, int]]:
    """Return audit-only exceptions; the source value itself stays in staging."""
    exceptions: list[tuple[str, str, str, int, str, int, int]] = []
    for code_norm, target_id in mapping.items():
        source = rows[code_norm]
        for target_column, source_column in FIELD_MAP:
            value = source.get(source_column)
            limit = target_limits[target_column]
            if value is not None and len(value) > limit:
                exceptions.append((source_system, source["source_code"], code_norm, target_id, target_column, len(value), limit))
    return exceptions


def validate_resolutions(
    bdm_rows: dict[str, dict[str, Any]],
    bdm_map: dict[str, int],
    targets: dict[int, dict[str, Any]],
) -> list[Resolution]:
    additions = [*BDM_NAME_RESOLUTIONS, BDM_CURRENT_EXACT_CODE]
    codes = [item.code_norm for item in additions]
    target_ids = [item.target_id for item in additions]
    if len(codes) != len(set(codes)) or len(target_ids) != len(set(target_ids)):
        raise RuntimeError("Daftar resolusi BDM mengandung kode atau target ganda.")
    used_targets = set(bdm_map.values())
    for item in additions:
        source = bdm_rows.get(item.code_norm)
        target = targets.get(item.target_id)
        if source is None:
            raise RuntimeError(f"Kode resolusi BDM tidak ada pada staging sekarang: {item.code_norm}")
        if target is None:
            raise RuntimeError(f"Target resolusi BDM tidak ditemukan: {item.target_id}")
        if item.code_norm in bdm_map:
            raise RuntimeError(f"Kode resolusi BDM sudah ada pada registry: {item.code_norm}")
        if item.target_id in used_targets:
            raise RuntimeError(f"Target resolusi BDM sudah digunakan registry: {item.target_id}")
        if item.exact_code:
            if clean(target.get("kode")) is None or clean(target.get("kode")).lower() != item.code_norm:
                raise RuntimeError(f"Kode target tidak cocok untuk resolusi BDM {item.code_norm}.")
        elif name_norm(source.get("nama")) != name_norm(target.get("nama")):
            raise RuntimeError(f"Nama toko tidak lagi cocok untuk resolusi BDM {item.code_norm}.")
    return additions


def simulate(
    bdm_rows: dict[str, dict[str, Any]],
    tmp_rows: dict[str, dict[str, Any]],
    bdm_map: dict[str, int],
    tmp_map: dict[str, int],
    targets: dict[int, dict[str, Any]],
    target_limits: dict[str, int],
) -> dict[str, int]:
    original = {
        target_id: {column: target.get(column) for column, _ in FIELD_MAP}
        for target_id, target in targets.items()
    }
    state = {target_id: dict(values) for target_id, values in original.items()}
    result: dict[str, int] = {}
    for label, rows, mapping in (("bdm", bdm_rows, bdm_map), ("tmp", tmp_rows, tmp_map)):
        changed = 0
        for code_norm, target_id in mapping.items():
            source = rows.get(code_norm)
            if source is None:
                raise RuntimeError(f"Registry {label} memiliki kode yang tidak ada pada staging: {code_norm}")
            before = state[target_id]
            after = {
                target_column: source_value_within_limit(
                    source.get(source_column), target_limits[target_column]
                )
                or before[target_column]
                for target_column, source_column in FIELD_MAP
            }
            if after != before:
                changed += 1
                state[target_id] = after
        result[f"{label}_mapped_rows"] = len(mapping)
        result[f"{label}_changed_rows"] = changed
    result["shared_bdm_tmp_targets"] = len(set(bdm_map.values()) & set(tmp_map.values()))
    result["final_changed_customers"] = sum(1 for target_id in state if state[target_id] != original[target_id])
    return result


def apply_source_update(cur, schema: str, source_system: str, target_limits: dict[str, int]) -> int:
    schema_q = ident(schema)
    registry_q = ident(REGISTRY_SCHEMA)
    select_fields = ",\n               ".join(
        f"CASE WHEN char_length(NULLIF(btrim(s.{ident(source_column)}), '')) <= {target_limits[target_column]} "
        f"THEN NULLIF(btrim(s.{ident(source_column)}), '') END AS {ident(target_column)}"
        for target_column, source_column in FIELD_MAP
    )
    assignments = ",\n               ".join(
        f"{ident(target_column)} = COALESCE(staged.{ident(target_column)}, c.{ident(target_column)})"
        for target_column, _ in FIELD_MAP
    )
    current_values = ", ".join(f"c.{ident(target_column)}" for target_column, _ in FIELD_MAP)
    replacement_values = ", ".join(
        f"COALESCE(staged.{ident(target_column)}, c.{ident(target_column)})"
        for target_column, _ in FIELD_MAP
    )
    cur.execute(
        f"""
        WITH staged AS (
            SELECT m.id_customer,
               {select_fields}
            FROM {schema_q}.customer s
            JOIN {registry_q}.customer_map m
              ON m.source_system = %s
             AND m.source_customer_code_norm = lower(btrim(s.kode))
            WHERE s.source_system = %s
        ), changed AS (
            UPDATE public.customer c
            SET {assignments}
            FROM staged
            WHERE c.id = staged.id_customer
              AND ROW({current_values}) IS DISTINCT FROM ROW({replacement_values})
            RETURNING c.id
        )
        SELECT count(*) FROM changed
        """,
        (source_system, source_system),
    )
    return int(cur.fetchone()[0])


def create_run_table(cur) -> None:
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {ident(REGISTRY_SCHEMA)}.customer_master_apply_run (
            batch_id text PRIMARY KEY,
            bdm_stage_schema text NOT NULL,
            tmp_stage_schema text NOT NULL,
            bdm_consistency_mode text NOT NULL,
            tmp_consistency_mode text NOT NULL,
            bdm_mapped_rows integer NOT NULL,
            tmp_mapped_rows integer NOT NULL,
            bdm_updated_rows integer NOT NULL,
            tmp_updated_rows integer NOT NULL,
            public_customer_count_before bigint NOT NULL,
            public_customer_count_after bigint NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {ident(REGISTRY_SCHEMA)}.customer_master_value_exception (
            batch_id text NOT NULL,
            source_system text NOT NULL,
            source_customer_code text NOT NULL,
            source_customer_code_norm text NOT NULL,
            id_customer integer NOT NULL,
            target_column text NOT NULL,
            source_length integer NOT NULL,
            target_limit integer NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (batch_id, source_system, source_customer_code_norm, target_column)
        )
        """
    )


def main() -> int:
    args = parse_args()
    ident(args.bdm_schema)
    ident(args.tmp_schema)
    connection = psycopg2.connect(
        dbname=args.pg_database,
        user=args.pg_user,
        host=args.pg_host,
        port=args.pg_port,
    )
    try:
        with connection.cursor() as cur:
            # A concurrent ERP edit to a mapped customer makes this batch
            # abort instead of silently overwriting a value seen mid-run.
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            bdm_rows, bdm_consistency = fetch_stage(cur, args.bdm_schema, BDM_SOURCE)
            tmp_rows, tmp_consistency = fetch_stage(cur, args.tmp_schema, TMP_SOURCE)
            bdm_map = fetch_existing_maps(cur, BDM_SOURCE)
            tmp_map = fetch_existing_maps(cur, TMP_SOURCE)
            target_limits = fetch_target_limits(cur)
            required_ids = set(bdm_map.values()) | set(tmp_map.values()) | {
                item.target_id for item in [*BDM_NAME_RESOLUTIONS, BDM_CURRENT_EXACT_CODE]
            }
            targets = fetch_customer_targets(cur, required_ids)
            additions = validate_resolutions(bdm_rows, bdm_map, targets)
            bdm_map_with_additions = dict(bdm_map)
            bdm_map_with_additions.update({item.code_norm: item.target_id for item in additions})
            plan = simulate(
                bdm_rows,
                tmp_rows,
                bdm_map_with_additions,
                tmp_map,
                targets,
                target_limits,
            )
            exceptions = [
                *collect_overlength_values(BDM_SOURCE, bdm_rows, bdm_map_with_additions, target_limits),
                *collect_overlength_values(TMP_SOURCE, tmp_rows, tmp_map, target_limits),
            ]
            cur.execute("SELECT count(*) FROM public.customer")
            plan["public_customer_count"] = int(cur.fetchone()[0])
            plan["bdm_resolution_mappings_to_add"] = len(additions)
            plan["overlength_values_held"] = len(exceptions)
            plan["bdm_consistency_mode"] = bdm_consistency
            plan["tmp_consistency_mode"] = tmp_consistency
            plan["will_apply"] = bool(args.apply)
            if not args.apply:
                print(json.dumps(plan, ensure_ascii=False, sort_keys=True))
                connection.rollback()
                return 0

            cur.execute("SET LOCAL lock_timeout = '10s'")
            cur.execute("SET LOCAL statement_timeout = '5min'")
            create_run_table(cur)
            cur.execute(
                f"SELECT 1 FROM {ident(REGISTRY_SCHEMA)}.customer_master_apply_run WHERE batch_id = %s",
                (BATCH_ID,),
            )
            if cur.fetchone():
                raise RuntimeError(f"Batch {BATCH_ID} sudah pernah dijalankan.")
            insert_rows = []
            for item in additions:
                source = bdm_rows[item.code_norm]
                insert_rows.append(
                    (
                        BDM_SOURCE,
                        source["source_code"],
                        item.code_norm,
                        item.target_id,
                        item.method,
                        "policy_approved_20260827",
                        item.note,
                    )
                )
            cur.executemany(
                f"""
                INSERT INTO {ident(REGISTRY_SCHEMA)}.customer_map
                    (source_system, source_customer_code, source_customer_code_norm,
                     id_customer, mapping_method, approved_by, reviewer_note)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                insert_rows,
            )
            cur.execute("SELECT count(*) FROM public.customer")
            before_count = int(cur.fetchone()[0])
            bdm_updated = apply_source_update(cur, args.bdm_schema, BDM_SOURCE, target_limits)
            tmp_updated = apply_source_update(cur, args.tmp_schema, TMP_SOURCE, target_limits)
            cur.execute("SELECT count(*) FROM public.customer")
            after_count = int(cur.fetchone()[0])
            if before_count != after_count:
                raise RuntimeError("Jumlah public.customer berubah; batch dibatalkan.")
            cur.execute(
                f"""
                INSERT INTO {ident(REGISTRY_SCHEMA)}.customer_master_apply_run
                    (batch_id, bdm_stage_schema, tmp_stage_schema,
                     bdm_consistency_mode, tmp_consistency_mode,
                     bdm_mapped_rows, tmp_mapped_rows,
                     bdm_updated_rows, tmp_updated_rows,
                     public_customer_count_before, public_customer_count_after)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    BATCH_ID,
                    args.bdm_schema,
                    args.tmp_schema,
                    bdm_consistency,
                    tmp_consistency,
                    plan["bdm_mapped_rows"],
                    plan["tmp_mapped_rows"],
                    bdm_updated,
                    tmp_updated,
                    before_count,
                    after_count,
                ),
            )
            cur.executemany(
                f"""
                INSERT INTO {ident(REGISTRY_SCHEMA)}.customer_master_value_exception
                    (batch_id, source_system, source_customer_code, source_customer_code_norm,
                     id_customer, target_column, source_length, target_limit)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [(BATCH_ID, *exception) for exception in exceptions],
            )
            plan["bdm_updated_rows"] = bdm_updated
            plan["tmp_updated_rows"] = tmp_updated
            plan["public_customer_count_before"] = before_count
            plan["public_customer_count_after"] = after_count
        connection.commit()
        print(json.dumps(plan, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
