#!/usr/bin/env python3
"""Report Plafon mapping readiness without reading or changing ERP public data.

This tool deliberately reads only:

* one BDM staging schema;
* one TMP staging schema; and
* the source-aware customer/principal/sales mapping registry.

It does **not** query ``public.plafon`` (or any other ``public`` table), and
therefore cannot say whether a candidate target triple already exists, should
be inserted, or should overwrite a current credit setting.  It also does not
interpret source fields such as ``plafon``, ``term``, or the lock columns.

The JSON output is a non-final policy-review input only.  It reports which
source Plafon rows resolve through the currently committed mappings, the
number of resulting target-ID triples, and field completeness/variation
without exposing source values.  It never writes to PostgreSQL.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any


REGISTRY_SCHEMA = "migration_bdm_tmp_202608"
IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
MAX_PROFILE_FIELDS = 64

STAGE_FIXED_COLUMNS = {
    "staging_id",
    "source_system",
    "target_company_id",
    "target_branch_id",
    "legacy_table",
    "source_row_hash",
    "imported_at",
}
STAGE_REQUIRED_COLUMNS = {
    "__stage_run": {
        "id",
        "source_system",
        "consistency_mode",
        "target_company_id",
        "target_branch_id",
        "status",
    },
    "__stage_manifest": {
        "legacy_table",
        "source_columns",
        "source_row_count",
        "staged_row_count",
        "status",
    },
    "plafon": STAGE_FIXED_COLUMNS | {"kodecustomer", "kodeprinciple", "kodesales", "plafon"},
}
REGISTRY_REQUIRED_COLUMNS = {
    "source_context": {"source_system", "target_company_id", "target_branch_id"},
    "customer_map": {"source_system", "source_customer_code_norm", "id_customer"},
    "principal_map": {"source_system", "source_principal_code_norm", "id_principal"},
    "sales_map": {
        "source_system",
        "source_principal_code_norm",
        "source_sales_code_norm",
        "id_sales",
    },
}
class ValidationError(RuntimeError):
    """Raised when a staging/registry input cannot support a safe report."""


def qident(value: str) -> str:
    """Return an identifier after rejecting anything outside staging conventions."""
    if not IDENT_RE.fullmatch(value):
        raise ValidationError(f"Identifier PostgreSQL tidak aman: {value!r}")
    return f'"{value}"'


def clean_name(value: str) -> str:
    """Mirror the staging tool's SQL-Server-column to PostgreSQL-column rule."""
    name = re.sub(r"[^0-9a-zA-Z_]+", "_", str(value or "").strip())
    name = re.sub(r"_+", "_", name).strip("_").lower()
    if not name:
        name = "col"
    if name[0].isdigit():
        name = f"c_{name}"
    return name


def unique_clean_columns(raw_columns: Iterable[str]) -> list[str]:
    """Mirror the source-staging collision suffixing rule exactly."""
    counts: dict[str, int] = {}
    result: list[str] = []
    for raw_column in raw_columns:
        base = clean_name(raw_column)
        counts[base] = counts.get(base, 0) + 1
        result.append(base if counts[base] == 1 else f"{base}_{counts[base]}")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bdm-schema", required=True, help="Schema staging BDM yang sudah selesai.")
    parser.add_argument("--tmp-schema", required=True, help="Schema staging TMP yang sudah selesai.")
    parser.add_argument("--pg-database", default=os.getenv("MIGRATION_PG_DATABASE", "budimas_dev"))
    parser.add_argument("--pg-user", default=os.getenv("MIGRATION_PG_USER", "postgres"))
    parser.add_argument("--pg-host", default=os.getenv("MIGRATION_PG_HOST", "127.0.0.1"))
    parser.add_argument("--pg-port", type=int, default=int(os.getenv("MIGRATION_PG_PORT", "5432")))
    parser.add_argument(
        "--statement-timeout-seconds",
        type=int,
        default=90,
        help="Batas waktu query read-only per transaksi (default: 90).",
    )
    return parser.parse_args()


def fetch_table_columns(cur, schemas: list[str]) -> dict[tuple[str, str], set[str]]:
    """Read metadata only for the two staging schemas and the registry schema."""
    cur.execute(
        """
        SELECT table_schema, table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = ANY(%s)
          AND table_name = ANY(%s)
        """,
        (
            schemas,
            [
                "__stage_run",
                "__stage_manifest",
                "plafon",
                "source_context",
                "customer_map",
                "principal_map",
                "sales_map",
            ],
        ),
    )
    columns: dict[tuple[str, str], set[str]] = {}
    for schema, table, column in cur.fetchall():
        columns.setdefault((str(schema), str(table)), set()).add(str(column))
    return columns


def validate_schema_columns(
    columns: dict[tuple[str, str], set[str]],
    schema: str,
    requirements: dict[str, set[str]],
) -> None:
    for table, required_columns in requirements.items():
        actual = columns.get((schema, table), set())
        missing = sorted(required_columns - actual)
        if missing:
            raise ValidationError(
                f"{schema}.{table} tidak memenuhi struktur laporan; kolom hilang: {', '.join(missing)}"
            )


def normalize_manifest_source_columns(value: Any, schema: str) -> list[str]:
    """Validate the staging manifest before using dynamic source-field names."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"{schema} manifest Plafon source_columns bukan JSON valid.") from exc
    if not isinstance(value, list) or not value:
        raise ValidationError(f"{schema} manifest Plafon tidak berisi daftar source_columns.")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ValidationError(f"{schema} manifest Plafon memuat nama kolom sumber tidak valid.")
    if len(value) > MAX_PROFILE_FIELDS:
        raise ValidationError(
            f"{schema} memiliki {len(value)} source_columns Plafon; melebihi batas profil {MAX_PROFILE_FIELDS}."
        )
    cleaned = unique_clean_columns(value)
    if any(not IDENT_RE.fullmatch(column) for column in cleaned):
        raise ValidationError(f"{schema} memiliki source_columns Plafon yang tidak aman setelah normalisasi.")
    return cleaned


def latest_stage_run(
    cur, schema: str, source_system: str, run_columns: set[str]
) -> dict[str, Any]:
    # Earlier low-traffic staging schemas predate the explicit ``is_preview``
    # column.  Their non-final status is still unambiguous from
    # ``consistency_mode = read_committed_preview``; support those immutable
    # schemas without weakening the report's non-final policy.
    preview_expression = (
        "is_preview"
        if "is_preview" in run_columns
        else "(consistency_mode <> 'snapshot')"
    )
    cur.execute(
        f"""
        SELECT source_system, consistency_mode, {preview_expression},
               target_company_id, target_branch_id, status
        FROM {qident(schema)}."__stage_run"
        ORDER BY id DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    if not row:
        raise ValidationError(f"{schema} tidak memiliki metadata __stage_run.")
    metadata = {
        "source_system": str(row[0]),
        "consistency_mode": str(row[1]),
        "is_preview": bool(row[2]),
        "target_company_id": int(row[3]),
        "target_branch_id": int(row[4]),
        "status": str(row[5]),
    }
    if metadata["source_system"] != source_system:
        raise ValidationError(
            f"{schema} ditandai untuk {metadata['source_system']}, bukan {source_system}."
        )
    if metadata["status"] not in {"completed", "completed_preview"}:
        raise ValidationError(f"{schema} belum selesai (status={metadata['status']!r}).")
    return metadata


def source_context(cur, source_system: str) -> dict[str, int]:
    registry = qident(REGISTRY_SCHEMA)
    cur.execute(
        f"""
        SELECT target_company_id, target_branch_id
        FROM {registry}.source_context
        WHERE source_system=%s
        """,
        (source_system,),
    )
    rows = cur.fetchall()
    if len(rows) != 1:
        raise ValidationError(f"source_context untuk {source_system} harus tepat satu baris.")
    return {"target_company_id": int(rows[0][0]), "target_branch_id": int(rows[0][1])}


def validate_stage_manifest(cur, schema: str, source_system: str, table_columns: set[str]) -> list[str]:
    cur.execute(
        f"""
        SELECT status, source_row_count, staged_row_count, source_columns
        FROM {qident(schema)}."__stage_manifest"
        WHERE lower(btrim(legacy_table)) = 'plafon'
        """
    )
    rows = cur.fetchall()
    if len(rows) != 1:
        raise ValidationError(f"{schema} harus memiliki tepat satu manifest Plafon.")
    status, source_count, staged_count, raw_source_columns = rows[0]
    if status != "done":
        raise ValidationError(f"{schema} manifest Plafon belum selesai (status={status!r}).")
    if source_count is None or staged_count is None or int(source_count) != int(staged_count):
        raise ValidationError(
            f"{schema} manifest Plafon tidak konsisten: source_row_count={source_count}, staged_row_count={staged_count}."
        )
    source_columns = normalize_manifest_source_columns(raw_source_columns, schema)
    missing_source_columns = sorted(set(source_columns) - table_columns)
    if missing_source_columns:
        raise ValidationError(
            f"{schema}.plafon tidak memuat kolom yang dicatat manifest: {', '.join(missing_source_columns)}"
        )
    required_source_columns = {"kodecustomer", "kodeprinciple", "kodesales", "plafon"}
    missing_required = sorted(required_source_columns - set(source_columns))
    if missing_required:
        raise ValidationError(
            f"{schema} manifest Plafon tidak memiliki kunci/field wajib: {', '.join(missing_required)}"
        )
    return source_columns


def validate_stage_rows(
    cur,
    schema: str,
    source_system: str,
    context: dict[str, int],
    expected_manifest_rows: int,
) -> dict[str, int]:
    cur.execute(
        f"""
        SELECT
            COUNT(*)::bigint AS rows,
            COUNT(*) FILTER (WHERE source_system IS DISTINCT FROM %s)::bigint AS wrong_source_system,
            COUNT(*) FILTER (
                WHERE target_company_id IS DISTINCT FROM %s
                   OR target_branch_id IS DISTINCT FROM %s
            )::bigint AS wrong_target_scope,
            COUNT(*) FILTER (WHERE lower(btrim(legacy_table)) <> 'plafon')::bigint AS wrong_legacy_table,
            COUNT(*) FILTER (WHERE source_row_hash IS NULL OR btrim(source_row_hash) = '')::bigint AS blank_source_row_hash
        FROM {qident(schema)}.plafon
        """,
        (source_system, context["target_company_id"], context["target_branch_id"]),
    )
    row = cur.fetchone()
    result = {
        "stage_rows": int(row[0]),
        "wrong_source_system": int(row[1]),
        "wrong_target_scope": int(row[2]),
        "wrong_legacy_table": int(row[3]),
        "blank_source_row_hash": int(row[4]),
        "manifest_staged_rows": expected_manifest_rows,
    }
    if result["stage_rows"] != expected_manifest_rows:
        raise ValidationError(
            f"{schema}.plafon baris aktual {result['stage_rows']} tidak sama dengan manifest {expected_manifest_rows}."
        )
    invalid = [key for key in ("wrong_source_system", "wrong_target_scope", "wrong_legacy_table", "blank_source_row_hash") if result[key]]
    if invalid:
        raise ValidationError(
            f"{schema}.plafon gagal validasi provenance: "
            + ", ".join(f"{key}={result[key]}" for key in invalid)
        )
    return result


def validate_mapping_keys(cur, source_system: str) -> dict[str, dict[str, int]]:
    """Defend against a manually altered registry without consulting public tables."""
    registry = qident(REGISTRY_SCHEMA)
    checks = {
        "customer_map": ("source_customer_code_norm",),
        "principal_map": ("source_principal_code_norm",),
        "sales_map": ("source_principal_code_norm", "source_sales_code_norm"),
    }
    result: dict[str, dict[str, int]] = {}
    for table, key_columns in checks.items():
        select_keys = ", ".join(qident(column) for column in key_columns)
        group_keys = select_keys
        cur.execute(
            f"""
            SELECT
                COALESCE(SUM(key_count), 0)::bigint AS mapping_rows,
                COUNT(*) FILTER (WHERE key_count > 1)::bigint AS duplicate_source_keys,
                COALESCE(SUM(key_count - 1) FILTER (WHERE key_count > 1), 0)::bigint AS extra_duplicate_rows
            FROM (
                SELECT {select_keys}, COUNT(*)::bigint AS key_count
                FROM {registry}.{qident(table)}
                WHERE source_system=%s
                GROUP BY {group_keys}
            ) key_counts
            """,
            (source_system,),
        )
        row = cur.fetchone()
        result[table] = {
            "mapping_rows": int(row[0]),
            "duplicate_source_keys": int(row[1]),
            "extra_duplicate_rows": int(row[2]),
        }
        if result[table]["duplicate_source_keys"]:
            raise ValidationError(
                f"Registry {table} untuk {source_system} memiliki source key duplikat; laporan dihentikan."
            )
    return result


def mapping_coverage(cur, schema: str, source_system: str) -> dict[str, int]:
    registry = qident(REGISTRY_SCHEMA)
    cur.execute(
        f"""
        WITH source_rows AS (
            SELECT
                NULLIF(lower(btrim(p.kodecustomer)), '') AS customer_code_norm,
                NULLIF(lower(btrim(p.kodeprinciple)), '') AS principal_code_norm,
                NULLIF(lower(btrim(p.kodesales)), '') AS sales_code_norm
            FROM {qident(schema)}.plafon p
            WHERE p.source_system=%s
        ), resolved AS (
            SELECT s.*, cm.id_customer, pm.id_principal, sm.id_sales
            FROM source_rows s
            LEFT JOIN {registry}.customer_map cm
              ON cm.source_system=%s
             AND cm.source_customer_code_norm=s.customer_code_norm
            LEFT JOIN {registry}.principal_map pm
              ON pm.source_system=%s
             AND pm.source_principal_code_norm=s.principal_code_norm
            LEFT JOIN {registry}.sales_map sm
              ON sm.source_system=%s
             AND sm.source_principal_code_norm=s.principal_code_norm
             AND sm.source_sales_code_norm=s.sales_code_norm
        )
        SELECT
            COUNT(*)::bigint AS source_rows,
            COUNT(DISTINCT (customer_code_norm, principal_code_norm, sales_code_norm))::bigint AS source_key_triples,
            COUNT(DISTINCT (customer_code_norm, principal_code_norm, sales_code_norm)) FILTER (
                WHERE customer_code_norm IS NOT NULL
                  AND principal_code_norm IS NOT NULL
                  AND sales_code_norm IS NOT NULL
            )::bigint AS complete_source_key_triples,
            COUNT(*) FILTER (WHERE customer_code_norm IS NULL)::bigint AS blank_customer_rows,
            COUNT(*) FILTER (WHERE principal_code_norm IS NULL)::bigint AS blank_principal_rows,
            COUNT(*) FILTER (WHERE sales_code_norm IS NULL)::bigint AS blank_sales_rows,
            COUNT(*) FILTER (WHERE customer_code_norm IS NOT NULL AND id_customer IS NULL)::bigint AS unmapped_customer_rows,
            COUNT(*) FILTER (WHERE principal_code_norm IS NOT NULL AND id_principal IS NULL)::bigint AS unmapped_principal_rows,
            COUNT(*) FILTER (WHERE sales_code_norm IS NOT NULL AND id_sales IS NULL)::bigint AS unmapped_sales_rows,
            COUNT(*) FILTER (WHERE id_customer IS NOT NULL AND id_principal IS NOT NULL AND id_sales IS NOT NULL)::bigint AS fully_mapped_rows,
            COUNT(DISTINCT (customer_code_norm, principal_code_norm, sales_code_norm)) FILTER (
                WHERE id_customer IS NOT NULL AND id_principal IS NOT NULL AND id_sales IS NOT NULL
            )::bigint AS fully_mapped_source_key_triples,
            COUNT(*) FILTER (
                WHERE customer_code_norm IS NOT NULL
                  AND principal_code_norm IS NOT NULL
                  AND sales_code_norm IS NOT NULL
                  AND (id_customer IS NULL OR id_principal IS NULL OR id_sales IS NULL)
            )::bigint AS complete_source_keys_but_not_fully_mapped_rows
        FROM resolved
        """,
        (source_system, source_system, source_system, source_system),
    )
    row = cur.fetchone()
    names = [description.name for description in cur.description]
    return {name: int(value) for name, value in zip(names, row)}


def target_triple_summary(cur, schema: str, source_system: str) -> dict[str, int]:
    """Count target-ID candidates only; no public target table is consulted."""
    registry = qident(REGISTRY_SCHEMA)
    cur.execute(
        f"""
        WITH source_rows AS (
            SELECT
                p.source_row_hash,
                NULLIF(lower(btrim(p.kodecustomer)), '') AS customer_code_norm,
                NULLIF(lower(btrim(p.kodeprinciple)), '') AS principal_code_norm,
                NULLIF(lower(btrim(p.kodesales)), '') AS sales_code_norm
            FROM {qident(schema)}.plafon p
            WHERE p.source_system=%s
        ), resolved AS (
            SELECT s.source_row_hash, cm.id_customer, pm.id_principal, sm.id_sales
            FROM source_rows s
            JOIN {registry}.customer_map cm
              ON cm.source_system=%s
             AND cm.source_customer_code_norm=s.customer_code_norm
            JOIN {registry}.principal_map pm
              ON pm.source_system=%s
             AND pm.source_principal_code_norm=s.principal_code_norm
            JOIN {registry}.sales_map sm
              ON sm.source_system=%s
             AND sm.source_principal_code_norm=s.principal_code_norm
             AND sm.source_sales_code_norm=s.sales_code_norm
        ), target_triples AS (
            SELECT id_customer, id_principal, id_sales,
                   COUNT(*)::bigint AS staged_rows,
                   COUNT(DISTINCT source_row_hash)::bigint AS distinct_source_rows
            FROM resolved
            GROUP BY id_customer, id_principal, id_sales
        )
        SELECT
            COUNT(*)::bigint AS candidate_target_triples,
            COALESCE(SUM(staged_rows), 0)::bigint AS fully_mapped_source_rows,
            COUNT(*) FILTER (WHERE staged_rows > 1)::bigint AS target_triples_with_multiple_staged_rows,
            COALESCE(SUM(staged_rows - 1) FILTER (WHERE staged_rows > 1), 0)::bigint AS extra_staged_rows_after_target_grouping,
            COUNT(*) FILTER (WHERE distinct_source_rows < staged_rows)::bigint AS target_triples_with_duplicate_source_row_hashes
        FROM target_triples
        """,
        (source_system, source_system, source_system, source_system),
    )
    row = cur.fetchone()
    names = [description.name for description in cur.description]
    return {name: int(value) for name, value in zip(names, row)}


def source_field_profile(cur, schema: str, source_system: str, source_columns: list[str]) -> dict[str, dict[str, int]]:
    """Return non-sensitive counts/lengths, never source field values."""
    report: dict[str, dict[str, int]] = {}
    for column in source_columns:
        column_q = qident(column)
        cur.execute(
            f"""
            SELECT
                COUNT(*)::bigint AS source_rows,
                COUNT(*) FILTER (WHERE NULLIF(btrim({column_q}), '') IS NULL)::bigint AS blank_or_null_rows,
                COUNT(DISTINCT NULLIF(btrim({column_q}), ''))::bigint AS distinct_nonblank_values,
                COALESCE(MAX(char_length({column_q})), 0)::bigint AS max_raw_length,
                COUNT(*) FILTER (
                    WHERE {column_q} IS NOT NULL AND {column_q} <> btrim({column_q})
                )::bigint AS leading_or_trailing_whitespace_rows
            FROM {qident(schema)}.plafon
            WHERE source_system=%s
            """,
            (source_system,),
        )
        row = cur.fetchone()
        names = [description.name for description in cur.description]
        report[column] = {name: int(value) for name, value in zip(names, row)}
    return report


def field_variation_by_candidate_target(
    cur,
    schema: str,
    source_system: str,
    source_columns: list[str],
) -> dict[str, dict[str, int]]:
    """Show duplicate-source variation per mapped target ID triple without choosing a winner."""
    registry = qident(REGISTRY_SCHEMA)
    key_columns = {"kodecustomer", "kodeprinciple", "kodesales"}
    result: dict[str, dict[str, int]] = {}
    for column in source_columns:
        if column in key_columns:
            continue
        column_q = qident(column)
        cur.execute(
            f"""
            WITH resolved AS (
                SELECT
                    cm.id_customer,
                    pm.id_principal,
                    sm.id_sales,
                    NULLIF(btrim(p.{column_q}), '') AS source_value
                FROM {qident(schema)}.plafon p
                JOIN {registry}.customer_map cm
                  ON cm.source_system=%s
                 AND cm.source_customer_code_norm=NULLIF(lower(btrim(p.kodecustomer)), '')
                JOIN {registry}.principal_map pm
                  ON pm.source_system=%s
                 AND pm.source_principal_code_norm=NULLIF(lower(btrim(p.kodeprinciple)), '')
                JOIN {registry}.sales_map sm
                  ON sm.source_system=%s
                 AND sm.source_principal_code_norm=NULLIF(lower(btrim(p.kodeprinciple)), '')
                 AND sm.source_sales_code_norm=NULLIF(lower(btrim(p.kodesales)), '')
                WHERE p.source_system=%s
            ), per_target AS (
                SELECT
                    id_customer,
                    id_principal,
                    id_sales,
                    COUNT(*)::bigint AS staged_rows,
                    COUNT(DISTINCT source_value)::bigint AS distinct_nonblank_values,
                    BOOL_OR(source_value IS NULL) AS has_blank_value,
                    BOOL_OR(source_value IS NOT NULL) AS has_nonblank_value
                FROM resolved
                GROUP BY id_customer, id_principal, id_sales
            )
            SELECT
                COUNT(*)::bigint AS candidate_target_triples,
                COUNT(*) FILTER (WHERE staged_rows > 1)::bigint AS target_triples_with_multiple_staged_rows,
                COUNT(*) FILTER (WHERE distinct_nonblank_values > 1)::bigint AS target_triples_with_multiple_nonblank_source_values,
                COUNT(*) FILTER (WHERE has_blank_value AND has_nonblank_value)::bigint AS target_triples_with_blank_and_nonblank_source_values
            FROM per_target
            """,
            (source_system, source_system, source_system, source_system),
        )
        row = cur.fetchone()
        names = [description.name for description in cur.description]
        result[column] = {name: int(value) for name, value in zip(names, row)}
    return result


def report_one_source(
    cur,
    schema: str,
    source_system: str,
    columns: dict[tuple[str, str], set[str]],
) -> dict[str, Any]:
    stage_columns = columns[(schema, "plafon")]
    metadata = latest_stage_run(
        cur, schema, source_system, columns[(schema, "__stage_run")]
    )
    context = source_context(cur, source_system)
    if (
        metadata["target_company_id"] != context["target_company_id"]
        or metadata["target_branch_id"] != context["target_branch_id"]
    ):
        raise ValidationError(
            f"{schema} target scope tidak sama dengan registry source_context untuk {source_system}."
        )
    source_columns = validate_stage_manifest(cur, schema, source_system, stage_columns)
    cur.execute(
        f"""
        SELECT staged_row_count
        FROM {qident(schema)}."__stage_manifest"
        WHERE lower(btrim(legacy_table))='plafon'
        """
    )
    expected_rows = int(cur.fetchone()[0])
    stage_validation = validate_stage_rows(cur, schema, source_system, context, expected_rows)
    mappings = validate_mapping_keys(cur, source_system)
    coverage = mapping_coverage(cur, schema, source_system)
    target_triples = target_triple_summary(cur, schema, source_system)
    profile = source_field_profile(cur, schema, source_system, source_columns)
    variation = field_variation_by_candidate_target(cur, schema, source_system, source_columns)
    return {
        "stage_schema": schema,
        "source_system": source_system,
        "stage_metadata": metadata,
        "registry_source_context": context,
        "stage_validation": stage_validation,
        "committed_mapping_registry": mappings,
        "mapping_coverage": coverage,
        "candidate_target_triples": target_triples,
        "source_field_profile": profile,
        "candidate_target_field_variation": variation,
    }


def build_report(
    conn,
    bdm_schema: str,
    tmp_schema: str,
    statement_timeout_seconds: int,
) -> dict[str, Any]:
    """Build one repeatable-read report while keeping the transaction read-only."""
    with conn.cursor() as cur:
        # This is the first SQL command on the connection, so PostgreSQL enforces
        # the transaction mode before any metadata or registry reads happen.
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        cur.execute("SET LOCAL lock_timeout = '5s'")
        # The value is an already validated positive integer, so embedding it
        # keeps this utility statement compatible with PostgreSQL drivers that
        # do not permit bind parameters in SET.
        cur.execute(f"SET LOCAL statement_timeout = '{statement_timeout_seconds}s'")

        columns = fetch_table_columns(cur, [bdm_schema, tmp_schema, REGISTRY_SCHEMA])
        validate_schema_columns(columns, REGISTRY_SCHEMA, REGISTRY_REQUIRED_COLUMNS)
        validate_schema_columns(columns, bdm_schema, STAGE_REQUIRED_COLUMNS)
        validate_schema_columns(columns, tmp_schema, STAGE_REQUIRED_COLUMNS)

        bdm = report_one_source(cur, bdm_schema, "bdm_solo_dist", columns)
        tmp = report_one_source(cur, tmp_schema, "tmp_solo_dist", columns)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report_kind": "staged_plafon_mapping_readiness",
        "read_only": True,
        "writes_to_postgresql": False,
        "public_tables_read": False,
        "final_status": "non_final_policy_review_only",
        "merge_allowed": False,
        "merge_allowed_reason": (
            "Laporan hanya menghitung kandidat ID dari mapping yang sudah committed. "
            "Tidak ada pengecekan public.plafon, tidak ada aturan create/update, dan tidak ada "
            "keputusan field sumber yang boleh menimpa kredit saat ini."
        ),
        "unresolved_policy_required": [
            "Pemetaan semantik field Plafon sumber ke field kredit target.",
            "Apakah kandidat triple yang sudah ada di target dipertahankan atau diperbarui.",
            "Apakah kandidat triple yang belum ada di target dibuat atau dilewati.",
            "Prioritas bila beberapa baris sumber memetakan ke triple target yang sama.",
            "Penanganan baris dengan customer/principal/sales yang belum memiliki committed map.",
        ],
        "sources": {"bdm_solo_dist": bdm, "tmp_solo_dist": tmp},
    }


def main() -> int:
    args = parse_args()
    if args.statement_timeout_seconds <= 0:
        raise SystemExit("--statement-timeout-seconds harus lebih besar dari nol.")
    for schema in (args.bdm_schema, args.tmp_schema):
        qident(schema)
    if args.bdm_schema == args.tmp_schema:
        raise SystemExit("--bdm-schema dan --tmp-schema harus berbeda.")

    try:
        import psycopg2  # type: ignore[import-not-found]
    except ImportError:
        print("Laporan Plafon memerlukan modul psycopg2 (misalnya psycopg2-binary).", file=sys.stderr)
        return 2

    # ``set_session(readonly=True)`` is a second guard in addition to the
    # explicit SET TRANSACTION statement used by build_report().
    try:
        conn = psycopg2.connect(
            dbname=args.pg_database,
            user=args.pg_user,
            host=args.pg_host,
            port=args.pg_port,
        )
    except psycopg2.Error as exc:
        print(f"Laporan Plafon tidak dapat terhubung ke PostgreSQL: {exc}", file=sys.stderr)
        return 2
    try:
        conn.set_session(readonly=True, autocommit=False)
        report = build_report(
            conn,
            args.bdm_schema,
            args.tmp_schema,
            args.statement_timeout_seconds,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        conn.rollback()
        return 0
    except (ValidationError, psycopg2.Error) as exc:
        conn.rollback()
        print(f"Laporan Plafon tidak dijalankan: {exc}", file=sys.stderr)
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
