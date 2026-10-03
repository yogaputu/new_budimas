#!/usr/bin/env python3
"""Read-only readiness report for the BDM Solo and TMP Solo clean master import.

This is a planner, never an importer. It runs each PostgreSQL connection in a
REPEATABLE READ, READ ONLY transaction and does not create, update, delete,
lock, or alter either source staging or the blue/green target database.

It accepts separate source and target database arguments. This allows final
freeze staging to remain in the audit database while the clean target baseline
is checked in a newly created database. No password, DSN, or secret is
accepted or embedded by this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPORT_VERSION = "clean_master_readiness_v1"
# PostgreSQL permits leading underscores. The staging metadata tables are
# intentionally named __stage_run and __stage_manifest, so rejecting them
# would make a read-only readiness check unable to inspect final staging.
IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
FINAL_STAGE_MODES = {"snapshot", "maintenance_freeze_serializable"}
DEFAULT_POLICY = Path(__file__).with_name("clean_import_policy.json")

STAGE_FIXED_COLUMNS = {
    "staging_id",
    "source_system",
    "target_company_id",
    "target_branch_id",
    "legacy_table",
    "source_row_hash",
    "imported_at",
}
STAGE_RUN_REQUIRED = {
    "id",
    "source_system",
    "status",
    "consistency_mode",
    "target_company_code",
    "target_company_id",
    "target_branch_code",
    "target_branch_id",
}
STAGE_MANIFEST_REQUIRED = {
    "legacy_table",
    "module",
    "source_columns",
    "source_row_count",
    "staged_row_count",
    "status",
}


@dataclass(frozen=True)
class SourceSpec:
    source_system: str
    schema: str
    company_code: str
    branch_code: str
    document_prefix: str


@dataclass(frozen=True)
class ConnectionConfig:
    database: str
    user: str
    host: str
    port: int

    def safe_label(self) -> dict[str, Any]:
        return {
            "database": self.database,
            "user": self.user,
            "host": self.host,
            "port": self.port,
        }


class ValidationError(RuntimeError):
    pass


# Every identity is source-qualified in the importer. The duplicate checks
# here discover ambiguity inside a source before an import plan exists.
MASTER_TABLES: dict[str, dict[str, Any]] = {
    "customer": {
        "required": True,
        "source_fields": ("kode", "nama"),
        "identity": (("kode",),),
    },
    "principle": {
        "required": True,
        "source_fields": ("kode", "nama"),
        "identity": (("kode",),),
    },
    "sales": {
        "required": True,
        "source_fields": ("kode",),
        "identity": (("kodeprinciple", "kode_principal"), ("kode",)),
    },
    "plafon": {
        "required": True,
        "source_fields": ("kodecustomer", "kodeprinciple", "kodesales", "plafon"),
        "identity": (
            ("kodecustomer", "kode_customer"),
            ("kodeprinciple", "kode_principal"),
            ("kodesales", "kode_sales"),
        ),
    },
    "stok": {
        "required": True,
        "source_fields": ("kode", "satuan", "perunit"),
        "identity": (("principle", "kodeprinciple", "kode_principal"), ("kode",)),
    },
    "barangsatuan": {
        "required": False,
        "source_fields": (),
        "identity": (),
    },
}

# Minimum public baseline contract. Extra required columns discovered during a
# future writer preflight must be handled by that writer; this report does not
# infer values for them.
TARGET_REQUIRED: dict[str, dict[str, tuple[str, ...]]] = {
    "perusahaan": {"columns": ("id", "kode")},
    "cabang": {"columns": ("id", "kode")},
    "perusahaan_cabang": {"columns": ("id", "id_perusahaan", "id_cabang")},
    "customer": {"columns": ("id", "kode", "nama", "id_cabang")},
    "principal": {"columns": ("id", "kode", "nama", "id_perusahaan")},
    "users": {"columns": ("id", "nama", "username", "id_jabatan", "id_cabang", "id_perusahaan")},
    "sales": {"columns": ("id", "id_user", "id_principal", "id_tipe")},
    "sales_detail": {"columns": ("id_sales", "kode_sales")},
    "sales_principal_assignment": {"columns": ("id_sales", "id_principal")},
    "produk": {"columns": ("id", "id_principal", "kode_sku", "nama")},
    "produk_uom": {"columns": ("id", "id_produk", "kode", "nama", "level", "faktor_konversi")},
    "produk_harga_jual": {"columns": ("id_produk", "id_tipe_harga", "harga")},
    "plafon": {"columns": ("id", "id_customer", "id_principal", "id_sales", "id_user", "limit_bon", "sisa_bon", "top")},
}

REFERENCE_TABLES = (
    "wilayah1", "wilayah2", "wilayah3", "wilayah4",
    "perusahaan", "cabang", "perusahaan_cabang",
    "departemen", "jabatan", "fitur", "jabatan_akses", "sales_tipe",
    "status", "tipe_transaksi", "modul", "fitur_mal", "source_modul",
    "customer_tipe", "tipe_toko_customer", "produk_tipe_harga", "master_ppn",
    "produk_satuan", "produk_kategori", "rute", "rute_cabang", "armada_tipe",
)
SOURCE_OWNED_EXPECTED_EMPTY = (
    "customer", "principal", "sales", "sales_detail", "sales_principal_assignment",
    "produk", "produk_uom", "produk_harga_jual", "plafon",
)
TRANSACTION_EXPECTED_EMPTY = ("sales_order", "sales_order_detail", "faktur", "faktur_detail")


def ident(value: str) -> str:
    if not IDENT_RE.fullmatch(value):
        raise ValidationError(f"Identifier PostgreSQL tidak aman: {value!r}.")
    return '"' + value + '"'


def qtable(schema: str, table: str) -> str:
    return ident(schema) + "." + ident(table)


def norm(value: Any) -> str | None:
    """The policy normalizer: lower(btrim), never fuzzy or nearest-name."""

    if value is None:
        return None
    result = str(value).strip()
    return result.lower() if result else None


def json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--bdm-schema", help="Override schema BDM dari policy.")
    parser.add_argument("--tmp-schema", help="Override schema TMP dari policy.")
    parser.add_argument(
        "--pg-database",
        default=os.getenv("MIGRATION_CLEAN_TARGET_PG_DATABASE") or os.getenv("MIGRATION_PG_DATABASE"),
        help="Database target blue/green atau database audit untuk mode satu koneksi.",
    )
    parser.add_argument("--pg-user", default=os.getenv("MIGRATION_CLEAN_TARGET_PG_USER") or os.getenv("MIGRATION_PG_USER", "postgres"))
    parser.add_argument("--pg-host", default=os.getenv("MIGRATION_CLEAN_TARGET_PG_HOST") or os.getenv("MIGRATION_PG_HOST", "127.0.0.1"))
    parser.add_argument("--pg-port", type=int, default=int(os.getenv("MIGRATION_CLEAN_TARGET_PG_PORT") or os.getenv("MIGRATION_PG_PORT", "5432")))
    parser.add_argument("--source-pg-database", default=os.getenv("MIGRATION_CLEAN_SOURCE_PG_DATABASE"))
    parser.add_argument("--source-pg-user", default=os.getenv("MIGRATION_CLEAN_SOURCE_PG_USER"))
    parser.add_argument("--source-pg-host", default=os.getenv("MIGRATION_CLEAN_SOURCE_PG_HOST"))
    parser.add_argument("--source-pg-port", type=int, default=int(os.getenv("MIGRATION_CLEAN_SOURCE_PG_PORT", "0") or "0"))
    parser.add_argument("--statement-timeout-seconds", type=int, default=180)
    parser.add_argument("--connect-timeout-seconds", type=int, default=int(os.getenv("MIGRATION_PG_CONNECT_TIMEOUT", "10")))
    parser.add_argument("--output", type=Path, help="Opsional: JSON laporan lokal.")
    parser.add_argument("--fail-if-not-ready", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def load_policy(path: Path) -> tuple[dict[str, SourceSpec], str]:
    if not path.is_file():
        raise ValidationError(f"Policy tidak ditemukan: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Policy bukan JSON valid: {path}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("sources"), dict):
        raise ValidationError("Policy sources tidak valid.")
    target = raw.get("target")
    context = raw.get("context_resolution")
    master_rules = raw.get("master_rules")
    if not isinstance(target, dict) or not isinstance(context, dict) or not isinstance(master_rules, dict):
        raise ValidationError("Policy target/context_resolution/master_rules tidak lengkap.")
    registry_schema = target.get("registry_schema")
    if not isinstance(registry_schema, str):
        raise ValidationError("Policy target.registry_schema tidak valid.")
    ident(registry_schema)
    if "Never hard-code numeric IDs" not in str(context.get("rule", "")):
        raise ValidationError("Policy konteks belum melarang hard-code ID numerik.")
    customer_rule = master_rules.get("customer")
    if not isinstance(customer_rule, dict) or "normalized source customer code" not in str(customer_rule.get("bdm_share_tmp_only_when", "")):
        raise ValidationError("Policy customer BDM/TMP bukan aturan source-qualified.")
    specs: dict[str, SourceSpec] = {}
    for source_system in ("bdm_solo_dist", "tmp_solo_dist"):
        source = raw["sources"].get(source_system)
        if not isinstance(source, dict):
            raise ValidationError(f"Policy tidak memiliki source {source_system}.")
        fields = ("staging_schema", "company_code", "branch_code", "document_prefix")
        if any(not isinstance(source.get(field), str) or not str(source[field]).strip() for field in fields):
            raise ValidationError(f"Policy source {source_system} tidak lengkap.")
        ident(str(source["staging_schema"]))
        specs[source_system] = SourceSpec(
            source_system=source_system,
            schema=str(source["staging_schema"]),
            company_code=str(source["company_code"]).strip(),
            branch_code=str(source["branch_code"]).strip(),
            document_prefix=str(source["document_prefix"]).strip(),
        )
    return specs, registry_schema


def configs(args: argparse.Namespace) -> tuple[ConnectionConfig, ConnectionConfig]:
    if not args.pg_database:
        raise ValidationError("--pg-database atau MIGRATION_CLEAN_TARGET_PG_DATABASE wajib diisi.")
    if not 1 <= args.pg_port <= 65535 or not 1 <= args.connect_timeout_seconds <= 60:
        raise ValidationError("Port atau connect timeout tidak valid.")
    if not 1 <= args.statement_timeout_seconds <= 3600:
        raise ValidationError("--statement-timeout-seconds harus 1..3600.")
    target = ConnectionConfig(str(args.pg_database), str(args.pg_user), str(args.pg_host), int(args.pg_port))
    source = ConnectionConfig(
        str(args.source_pg_database or target.database),
        str(args.source_pg_user or target.user),
        str(args.source_pg_host or target.host),
        int(args.source_pg_port or target.port),
    )
    if not all((target.database, target.user, target.host, source.database, source.user, source.host)):
        raise ValidationError("Database, user, dan host tidak boleh kosong.")
    if not 1 <= source.port <= 65535:
        raise ValidationError("--source-pg-port tidak valid.")
    return target, source


def connect_read_only(config: ConnectionConfig, timeout: int, application_name: str):
    try:
        import psycopg2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ValidationError("psycopg2 diperlukan untuk laporan readiness.") from exc
    try:
        connection = psycopg2.connect(
            dbname=config.database,
            user=config.user,
            host=config.host,
            port=config.port,
            connect_timeout=timeout,
            application_name=application_name,
        )
    except Exception as exc:
        raise ValidationError(
            f"Koneksi PostgreSQL read-only gagal untuk {config.database!r}: {type(exc).__name__}: {exc}"
        ) from exc
    connection.set_session(readonly=True, autocommit=False)
    return connection


def begin_snapshot(cur, timeout_seconds: int) -> None:
    cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
    cur.execute("SET LOCAL lock_timeout = '5s'")
    cur.execute("SET LOCAL statement_timeout = %s", (f"{timeout_seconds}s",))


def relation_columns(cur, schema: str, table: str) -> dict[str, dict[str, Any]]:
    cur.execute(
        """
        SELECT column_name, data_type, udt_name, is_nullable,
               character_maximum_length, column_default, is_identity, is_generated
        FROM information_schema.columns
        WHERE table_schema=%s AND table_name=%s
        ORDER BY ordinal_position
        """,
        (schema, table),
    )
    return {
        str(row[0]): {
            "data_type": str(row[1]),
            "udt_name": str(row[2]),
            "nullable": str(row[3]) == "YES",
            "max_length": int(row[4]) if row[4] is not None else None,
            "has_default": row[5] is not None,
            "is_identity": str(row[6]) == "YES",
            "is_generated": str(row[7]),
        }
        for row in cur.fetchall()
    }


def table_exists(cur, schema: str, table: str) -> bool:
    cur.execute("SELECT to_regclass(%s)", (schema + "." + table,))
    return cur.fetchone()[0] is not None


def alias_column(columns: Iterable[str], choices: tuple[str, ...]) -> str | None:
    available = set(columns)
    return next((choice for choice in choices if choice in available), None)


def stage_run(cur, spec: SourceSpec) -> dict[str, Any]:
    columns = relation_columns(cur, spec.schema, "__stage_run")
    missing = sorted(STAGE_RUN_REQUIRED - set(columns))
    result: dict[str, Any] = {"missing_required_columns": missing, "ready": False}
    if missing:
        return result
    optional = set(columns)
    def col_or_null(name: str, sql_type: str) -> str:
        return ident(name) if name in optional else "NULL::" + sql_type
    cur.execute(
        f"""
        SELECT id, source_system, status, consistency_mode,
               {col_or_null("is_preview", "boolean")},
               {col_or_null("maintenance_window_id", "text")},
               {col_or_null("maintenance_freeze_attested", "boolean")},
               {col_or_null("maintenance_freeze_confirmed_at", "timestamptz")},
               {col_or_null("source_transaction_isolation", "text")},
               {col_or_null("source_lock_timeout_ms", "integer")},
               target_company_code, target_company_id, target_branch_code, target_branch_id
        FROM {qtable(spec.schema, "__stage_run")}
        ORDER BY id DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    if row is None:
        result["reason"] = "missing_stage_run"
        return result
    mode = str(row[3])
    base_ready = str(row[2]) == "completed" and not bool(row[4]) and mode in FINAL_STAGE_MODES
    mode_ready = mode == "snapshot" or (
        mode == "maintenance_freeze_serializable"
        and bool(row[6])
        and row[7] is not None
        and norm(row[8]) == "serializable"
        and row[9] is not None
    )
    codes_ready = (
        norm(row[1]) == norm(spec.source_system)
        and norm(row[10]) == norm(spec.company_code)
        and norm(row[12]) == norm(spec.branch_code)
    )
    result["latest_run"] = {
        "id": int(row[0]),
        "source_system": str(row[1]),
        "status": str(row[2]),
        "consistency_mode": mode,
        "is_preview": bool(row[4]),
        "maintenance_window_id": str(row[5]) if row[5] is not None else None,
        "maintenance_freeze_attested": bool(row[6]),
        "maintenance_freeze_confirmed_at": row[7],
        "source_transaction_isolation": str(row[8]) if row[8] is not None else None,
        "source_lock_timeout_ms": int(row[9]) if row[9] is not None else None,
        "stage_company_code": str(row[10]),
        "stage_branch_code": str(row[12]),
        "stage_company_id_audit_only": int(row[11]),
        "stage_branch_id_audit_only": int(row[13]),
    }
    result["policy_code_match"] = {
        "source_system": norm(row[1]) == norm(spec.source_system),
        "company_code": norm(row[10]) == norm(spec.company_code),
        "branch_code": norm(row[12]) == norm(spec.branch_code),
    }
    result["ready"] = base_ready and mode_ready and codes_ready
    return result


def manifests(cur, schema: str) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    columns = relation_columns(cur, schema, "__stage_manifest")
    missing = sorted(STAGE_MANIFEST_REQUIRED - set(columns))
    state: dict[str, Any] = {"missing_required_columns": missing, "ready": not missing}
    if missing:
        return {}, state
    cur.execute(
        f"""
        SELECT lower(btrim(legacy_table)), module, source_columns,
               source_row_count, staged_row_count, status
        FROM {qtable(schema, "__stage_manifest")}
        """
    )
    data: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for table, module, source_columns, source_count, staged_count, status in cur.fetchall():
        name = str(table)
        if name in data:
            duplicates.append(name)
            continue
        parsed: list[str] | None = None
        try:
            value = json.loads(source_columns) if isinstance(source_columns, str) else source_columns
            if isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value):
                parsed = [str(item).strip().lower() for item in value]
        except (TypeError, json.JSONDecodeError):
            parsed = None
        data[name] = {
            "module": str(module),
            "source_columns": parsed,
            "source_row_count": int(source_count) if source_count is not None else None,
            "staged_row_count": int(staged_count) if staged_count is not None else None,
            "status": str(status),
        }
    state["duplicate_manifest_rows"] = sorted(set(duplicates))
    if duplicates:
        state["ready"] = False
    return data, state


def stage_table(
    cur,
    spec: SourceSpec,
    table: str,
    table_spec: dict[str, Any],
    run: dict[str, Any],
    source_manifests: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    columns = relation_columns(cur, spec.schema, table)
    output: dict[str, Any] = {
        "required": bool(table_spec["required"]),
        "table_exists": bool(columns),
        "missing_fixed_columns": sorted(STAGE_FIXED_COLUMNS - set(columns)),
        "missing_required_source_columns": sorted(set(table_spec["source_fields"]) - set(columns)),
        "manifest": source_manifests.get(table),
        "ready": False,
    }
    if not columns or output["missing_fixed_columns"]:
        return output
    manifest = source_manifests.get(table)
    latest = run.get("latest_run")
    if manifest is None or not isinstance(latest, dict):
        return output
    if manifest["source_columns"] is None:
        output["manifest_source_columns_valid"] = False
        return output
    output["manifest_source_columns_valid"] = True
    output["manifest_columns_missing_from_stage"] = sorted(set(manifest["source_columns"]) - set(columns))
    cur.execute(
        f"""
        SELECT COUNT(*)::bigint,
               COUNT(*) FILTER (WHERE source_system IS DISTINCT FROM %s)::bigint,
               COUNT(*) FILTER (
                   WHERE target_company_id IS DISTINCT FROM %s
                      OR target_branch_id IS DISTINCT FROM %s
               )::bigint,
               COUNT(*) FILTER (WHERE lower(btrim(legacy_table)) <> %s)::bigint,
               COUNT(*) FILTER (WHERE source_row_hash IS NULL OR btrim(source_row_hash)='')::bigint
        FROM {qtable(spec.schema, table)}
        """,
        (
            spec.source_system,
            latest["stage_company_id_audit_only"],
            latest["stage_branch_id_audit_only"],
            table,
        ),
    )
    actual, wrong_source, wrong_scope, wrong_table, blank_hash = [int(value) for value in cur.fetchone()]
    provenance = {
        "actual_rows": actual,
        "wrong_source_system_rows": wrong_source,
        "wrong_stage_scope_rows": wrong_scope,
        "wrong_legacy_table_rows": wrong_table,
        "blank_source_row_hash_rows": blank_hash,
        "manifest_source_row_count": manifest["source_row_count"],
        "manifest_staged_row_count": manifest["staged_row_count"],
        "manifest_status": manifest["status"],
        "manifest_module": manifest["module"],
    }
    output["provenance"] = provenance
    output["ready"] = (
        manifest["status"] == "done"
        and manifest["module"] == "masters"
        and manifest["source_row_count"] is not None
        and manifest["staged_row_count"] is not None
        and manifest["source_row_count"] == manifest["staged_row_count"] == actual
        and not any((wrong_source, wrong_scope, wrong_table, blank_hash))
        and not output["missing_required_source_columns"]
        and not output["manifest_columns_missing_from_stage"]
    )
    return output


def identity_columns(table_spec: dict[str, Any], available: Iterable[str]) -> tuple[str, ...] | None:
    resolved: list[str] = []
    for alternatives in table_spec["identity"]:
        column = alias_column(available, tuple(alternatives))
        if column is None:
            return None
        resolved.append(column)
    return tuple(resolved) if resolved else None


def identity_profile(cur, schema: str, table: str, source_system: str, columns: tuple[str, ...]) -> dict[str, Any]:
    selected = ", ".join(
        "NULLIF(lower(btrim(" + ident(column) + ")), '') AS k_" + str(index)
        for index, column in enumerate(columns)
    )
    complete = " AND ".join("k_" + str(index) + " IS NOT NULL" for index in range(len(columns)))
    grouped = ", ".join("k_" + str(index) for index in range(len(columns)))
    cur.execute(
        f"""
        WITH rows AS (
            SELECT {selected}
            FROM {qtable(schema, table)}
            WHERE source_system=%s
        ), complete_rows AS (
            SELECT * FROM rows WHERE {complete}
        ), groups AS (
            SELECT {grouped}, COUNT(*)::bigint AS n
            FROM complete_rows GROUP BY {grouped}
        )
        SELECT
            (SELECT COUNT(*)::bigint FROM rows),
            (SELECT COUNT(*)::bigint FROM complete_rows),
            (SELECT COUNT(*)::bigint FROM rows WHERE NOT ({complete})),
            (SELECT COUNT(*)::bigint FROM groups),
            (SELECT COUNT(*)::bigint FROM groups WHERE n > 1),
            (SELECT COALESCE(SUM(n - 1), 0)::bigint FROM groups WHERE n > 1)
        """,
        (source_system,),
    )
    row = [int(value) for value in cur.fetchone()]
    return {
        "available": True,
        "normalization": "lower(btrim(...))",
        "identity_columns": list(columns),
        "source_rows": row[0],
        "complete_identity_rows": row[1],
        "blank_identity_rows": row[2],
        "distinct_complete_identities": row[3],
        "duplicate_identity_groups": row[4],
        "duplicate_extra_rows": row[5],
    }


def source_report(cur, spec: SourceSpec) -> dict[str, Any]:
    run = stage_run(cur, spec)
    source_manifests, manifest_state = manifests(cur, spec.schema)
    tables: dict[str, Any] = {}
    identities: dict[str, Any] = {}
    for table, table_spec in MASTER_TABLES.items():
        tables[table] = stage_table(cur, spec, table, table_spec, run, source_manifests)
        cols = relation_columns(cur, spec.schema, table)
        keys = identity_columns(table_spec, cols)
        if keys is None:
            identities[table] = {
                "available": False,
                "reason": "missing_identity_column_or_optional_identity",
                "expected": table_spec["identity"],
            }
        else:
            identities[table] = identity_profile(cur, spec.schema, table, spec.source_system, keys)
    master_ready = all(item["ready"] for item in tables.values() if item["required"])
    return {
        "source_system": spec.source_system,
        "schema": spec.schema,
        "run": run,
        "manifest": manifest_state,
        "tables": tables,
        "duplicate_normalized_identities": identities,
        "master_stage_ready": bool(run["ready"]) and bool(manifest_state["ready"]) and master_ready,
    }


def freeze_pair(source_reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not all(source_reports[source]["run"]["ready"] for source in ("bdm_solo_dist", "tmp_solo_dist")):
        return {"ready": False, "reason": "one_or_both_stage_runs_not_final_freeze_ready"}
    runs = [source_reports[source]["run"]["latest_run"] for source in ("bdm_solo_dist", "tmp_solo_dist")]
    modes = {str(item["consistency_mode"]) for item in runs}
    if modes == {"snapshot"}:
        return {"ready": True, "consistency_mode": "snapshot", "reason": "both_sources_snapshot"}
    if modes != {"maintenance_freeze_serializable"}:
        return {"ready": False, "reason": "mixed_final_freeze_modes"}
    windows = {item["maintenance_window_id"] for item in runs}
    if len(windows) != 1 or None in windows:
        return {"ready": False, "reason": "maintenance_freeze_window_not_shared"}
    return {
        "ready": True,
        "consistency_mode": "maintenance_freeze_serializable",
        "maintenance_window_id": next(iter(windows)),
        "reason": "both_sources_same_attested_maintenance_freeze",
    }


def customer_groups(cur, spec: SourceSpec) -> list[dict[str, Any]]:
    cur.execute(
        f"""
        WITH rows AS (
            SELECT NULLIF(lower(btrim(kode)), '') AS code_norm,
                   NULLIF(lower(btrim(nama)), '') AS name_norm
            FROM {qtable(spec.schema, "customer")}
            WHERE source_system=%s
        )
        SELECT code_norm, COUNT(*)::bigint,
               COUNT(DISTINCT name_norm)::bigint,
               MIN(name_norm) FILTER (WHERE name_norm IS NOT NULL),
               BOOL_OR(name_norm IS NULL)
        FROM rows
        GROUP BY code_norm
        """,
        (spec.source_system,),
    )
    return [
        {
            "code_norm": str(row[0]) if row[0] is not None else None,
            "rows": int(row[1]),
            "distinct_nonblank_names": int(row[2]),
            "name_norm": str(row[3]) if row[3] is not None else None,
            "has_blank_name": bool(row[4]),
        }
        for row in cur.fetchall()
    ]


def classify_customer_groups(groups: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], Counter[str]]:
    valid: dict[str, dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    for item in groups:
        code, rows = item["code_norm"], int(item["rows"])
        if code is None:
            counts["hold_blank_code_rows"] += rows
        elif rows != 1:
            counts["hold_duplicate_code_rows"] += rows
        elif item["has_blank_name"] or item["name_norm"] is None:
            counts["hold_blank_store_name_rows"] += rows
        else:
            valid[code] = item
            counts["valid_unique_customer_rows"] += rows
    counts["source_rows"] = sum(int(item["rows"]) for item in groups)
    counts["normalized_code_groups"] = len(groups)
    counts["held_rows"] = (
        counts["hold_blank_code_rows"]
        + counts["hold_duplicate_code_rows"]
        + counts["hold_blank_store_name_rows"]
    )
    return valid, counts


def global_customer_code_unique(cur) -> bool | None:
    if not table_exists(cur, "public", "customer"):
        return None
    cur.execute(
        """
        SELECT i.indnkeyatts, pg_get_indexdef(i.indexrelid)
        FROM pg_index i
        JOIN pg_class c ON c.oid=i.indrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relname='customer' AND i.indisunique
        """
    )
    for key_count, definition in cur.fetchall():
        if int(key_count) == 1 and "kode" in str(definition).lower():
            return True
    return False


def customer_plan(cur, bdm: SourceSpec, tmp: SourceSpec, target_code_unique: bool | None) -> dict[str, Any]:
    for spec in (bdm, tmp):
        columns = relation_columns(cur, spec.schema, "customer")
        required = {"source_system", "kode", "nama"}
        missing = sorted(required - set(columns))
        if missing:
            return {
                "available": False,
                "reason": "customer_stage_missing_required_columns",
                "source_system": spec.source_system,
                "missing_columns": missing,
                "tmp_source": {},
                "bdm_source": {},
                "plan": {},
            }
    tmp_valid, tmp_counts = classify_customer_groups(customer_groups(cur, tmp))
    bdm_valid, bdm_counts = classify_customer_groups(customer_groups(cur, bdm))
    plan: Counter[str] = Counter()
    plan["tmp_create_source_owned"] = len(tmp_valid)
    for code, bdm_item in bdm_valid.items():
        tmp_item = tmp_valid.get(code)
        if tmp_item is not None and tmp_item["name_norm"] == bdm_item["name_norm"]:
            plan["bdm_shared_exact_with_tmp"] += 1
        elif tmp_item is not None:
            plan["bdm_create_source_owned_name_mismatch"] += 1
            if target_code_unique:
                plan["bdm_create_requires_display_code_prefix"] += 1
        else:
            plan["bdm_create_source_owned_no_exact_tmp_pair"] += 1
    plan["tmp_hold_rows"] = tmp_counts["held_rows"]
    plan["bdm_hold_rows"] = bdm_counts["held_rows"]
    return {
        "available": True,
        "normalization": {
            "customer_code": "lower(btrim(kode))",
            "store_name": "lower(btrim(nama))",
            "fuzzy_matching": False,
            "nearest_name_matching": False,
        },
        "tmp_source": dict(sorted(tmp_counts.items())),
        "bdm_source": dict(sorted(bdm_counts.items())),
        "plan": dict(sorted(plan.items())),
        "target_global_customer_code_unique": target_code_unique,
        "policy_outcome": {
            "load_order": "TMP first",
            "share": "BDM shares only an exact TMP normalized code plus store-name pair",
            "create": "Every other valid BDM identity creates a source-owned BDM customer",
            "hold": "Blank code/name and duplicate source code rows are not auto-created",
        },
    }


def compatible_target_type(column: str, data_type: str) -> bool:
    if column == "id" or column.startswith("id_"):
        return data_type in {"smallint", "integer", "bigint"}
    if column in {"kode", "nama", "username", "kode_sales", "kode_sku"}:
        return data_type in {"character varying", "text"}
    if column in {"level", "faktor_konversi", "top"}:
        return data_type in {"smallint", "integer", "bigint"}
    if column in {"harga", "limit_bon", "sisa_bon"}:
        return data_type in {"smallint", "integer", "bigint", "numeric", "real", "double precision"}
    return True


def public_table(cur, table: str, required: tuple[str, ...]) -> dict[str, Any]:
    columns = relation_columns(cur, "public", table)
    missing = sorted(set(required) - set(columns))
    type_mismatches = {
        name: columns[name]["data_type"]
        for name in required
        if name in columns and not compatible_target_type(name, columns[name]["data_type"])
    }
    return {
        "table_exists": bool(columns),
        "missing_required_columns": missing,
        "type_mismatches": type_mismatches,
        "ready": bool(columns) and not missing and not type_mismatches,
        "columns": {
            name: {
                "data_type": columns[name]["data_type"],
                "nullable": columns[name]["nullable"],
                "max_length": columns[name]["max_length"],
                "has_default": columns[name]["has_default"],
                "is_identity": columns[name]["is_identity"],
                "is_generated": columns[name]["is_generated"],
            }
            for name in required if name in columns
        },
    }


def count_rows(cur, schema: str, table: str) -> int | None:
    if not table_exists(cur, schema, table):
        return None
    cur.execute("SELECT COUNT(*)::bigint FROM " + qtable(schema, table))
    return int(cur.fetchone()[0])


def target_context(cur, spec: SourceSpec) -> dict[str, Any]:
    checks = {
        "perusahaan": ("id", "kode"),
        "cabang": ("id", "kode"),
        "perusahaan_cabang": ("id", "id_perusahaan", "id_cabang"),
    }
    if any(not set(required).issubset(relation_columns(cur, "public", table)) for table, required in checks.items()):
        return {"ready": False, "reason": "organization_reference_table_or_column_missing"}
    cur.execute(
        "SELECT id FROM public.perusahaan WHERE NULLIF(lower(btrim(kode)), '')=%s ORDER BY id",
        (norm(spec.company_code),),
    )
    companies = [int(row[0]) for row in cur.fetchall()]
    cur.execute(
        "SELECT id FROM public.cabang WHERE NULLIF(lower(btrim(kode)), '')=%s ORDER BY id",
        (norm(spec.branch_code),),
    )
    branches = [int(row[0]) for row in cur.fetchall()]
    pairs: list[int] = []
    if len(companies) == 1 and len(branches) == 1:
        cur.execute(
            "SELECT id FROM public.perusahaan_cabang WHERE id_perusahaan=%s AND id_cabang=%s ORDER BY id",
            (companies[0], branches[0]),
        )
        pairs = [int(row[0]) for row in cur.fetchall()]
    return {
        "ready": len(companies) == len(branches) == len(pairs) == 1,
        "rule": "resolve company and branch code independently, then require one perusahaan_cabang pair",
        "company_code": spec.company_code,
        "branch_code": spec.branch_code,
        "company_match_count": len(companies),
        "branch_match_count": len(branches),
        "perusahaan_cabang_pair_match_count": len(pairs),
        "resolved_ids_audit_only": {
            "company_id": companies[0] if len(companies) == 1 else None,
            "branch_id": branches[0] if len(branches) == 1 else None,
            "perusahaan_cabang_id": pairs[0] if len(pairs) == 1 else None,
        },
    }


def registry(cur, schema: str) -> dict[str, Any]:
    expected = (
        "import_run", "source_context", "customer_source_map", "principal_source_map",
        "sales_source_map", "product_source_map", "product_uom_source_map",
        "sales_document_map", "sales_document_line_map", "import_hold", "reconciliation_result",
    )
    tables = {table: table_exists(cur, schema, table) for table in expected}
    return {
        "schema": schema,
        "registry_ddl_installed": all(tables.values()),
        "tables": tables,
        "note": "A missing registry is a blocker for import, but not for a baseline preflight report.",
    }


def target_report(cur, specs: dict[str, SourceSpec], registry_schema: str) -> dict[str, Any]:
    compatibility = {
        table: public_table(cur, table, values["columns"])
        for table, values in TARGET_REQUIRED.items()
    }
    contexts = {name: target_context(cur, spec) for name, spec in specs.items()}
    reference_counts = {table: count_rows(cur, "public", table) for table in REFERENCE_TABLES}
    master_counts = {table: count_rows(cur, "public", table) for table in SOURCE_OWNED_EXPECTED_EMPTY}
    transaction_counts = {table: count_rows(cur, "public", table) for table in TRANSACTION_EXPECTED_EMPTY}
    masters_nonempty = {table: value for table, value in master_counts.items() if value is not None and value > 0}
    transactions_nonempty = {table: value for table, value in transaction_counts.items() if value is not None and value > 0}
    return {
        "target_master_table_compatibility": compatibility,
        "target_columns_ready": all(item["ready"] for item in compatibility.values()),
        "context_resolver": contexts,
        "target_context_ready": all(item["ready"] for item in contexts.values()),
        "reference_baseline_row_counts": reference_counts,
        "source_owned_master_expected_empty": {
            "counts": master_counts,
            "nonempty": masters_nonempty,
            "ready": not masters_nonempty,
        },
        "transaction_expected_empty": {
            "counts": transaction_counts,
            "nonempty": transactions_nonempty,
            "ready": not transactions_nonempty,
        },
        "customer_code_global_unique": global_customer_code_unique(cur),
        "clean_registry": registry(cur, registry_schema),
    }


def blockers(report: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for source, source_report in report["source_staging"].items():
        if not source_report["master_stage_ready"]:
            result.append("source_stage_not_ready:" + source)
    if not report["source_pair_final_freeze"]["ready"]:
        result.append("source_pair_final_freeze_not_ready")
    target = report["target_baseline"]
    if not target["target_columns_ready"]:
        result.append("target_master_columns_not_ready")
    if not target["target_context_ready"]:
        result.append("target_context_resolution_not_ready")
    if not target["source_owned_master_expected_empty"]["ready"]:
        result.append("target_source_owned_master_not_empty")
    if not target["transaction_expected_empty"]["ready"]:
        result.append("target_transactions_not_empty")
    if not target["clean_registry"]["registry_ddl_installed"]:
        result.append("clean_registry_ddl_not_installed")
    customer = report["customer_source_plan"]
    if not customer.get("available", False):
        result.append("customer_source_plan_unavailable")
        return result
    if customer["tmp_source"].get("held_rows", 0) or customer["bdm_source"].get("held_rows", 0):
        result.append("customer_source_identity_holds_present")
    return result


def source_hold_summary(source_reports: dict[str, dict[str, Any]], customer: dict[str, Any]) -> list[dict[str, Any]]:
    """Summarize rows that a future importer must hold or handle explicitly.

    A hold is not an infrastructure blocker: the approved clean policy is
    deliberately fail-closed per identity, so unambiguous source rows can
    still be planned while ambiguous rows are written to import_hold by the
    later writer. The report keeps the two concepts separate.
    """

    result: list[dict[str, Any]] = []
    for source, report in source_reports.items():
        for table, profile in report["duplicate_normalized_identities"].items():
            if not profile.get("available"):
                continue
            blank = int(profile.get("blank_identity_rows", 0))
            duplicate = int(profile.get("duplicate_extra_rows", 0))
            if blank or duplicate:
                result.append(
                    {
                        "source_system": source,
                        "entity": table,
                        "blank_identity_rows": blank,
                        "duplicate_extra_rows": duplicate,
                        "action": "hold_or_apply_entity_specific_policy",
                    }
                )
    if customer.get("available"):
        for label in ("tmp", "bdm"):
            count = int(customer.get(label + "_source", {}).get("held_rows", 0))
            if count:
                result.append(
                    {
                        "source_system": label + "_solo_dist",
                        "entity": "customer",
                        "blank_identity_rows": count,
                        "duplicate_extra_rows": 0,
                        "action": "hold_no_auto_customer_create",
                    }
                )
    return result


def build_report(
    source_connection,
    target_connection,
    specs: dict[str, SourceSpec],
    registry_schema: str,
    timeout: int,
    policy_path: Path,
) -> dict[str, Any]:
    same_connection = source_connection is target_connection
    with source_connection.cursor() as source_cur:
        begin_snapshot(source_cur, timeout)
        sources = {name: source_report(source_cur, spec) for name, spec in specs.items()}
        pair = freeze_pair(sources)
        if same_connection:
            target = target_report(source_cur, specs, registry_schema)
            customers = customer_plan(
                source_cur, specs["bdm_solo_dist"], specs["tmp_solo_dist"],
                target["customer_code_global_unique"],
            )
        else:
            with target_connection.cursor() as target_cur:
                begin_snapshot(target_cur, timeout)
                target = target_report(target_cur, specs, registry_schema)
            customers = customer_plan(
                source_cur, specs["bdm_solo_dist"], specs["tmp_solo_dist"],
                target["customer_code_global_unique"],
            )
    report: dict[str, Any] = {
        "report_kind": "clean_bdm_tmp_master_readiness",
        "report_version": REPORT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "writes_to_sql_server": False,
        "writes_to_postgresql": False,
        "policy": {
            "path": str(policy_path),
            "sha256": sha256_file(policy_path),
            "normalization": "lower(btrim(...))",
            "source_qualified": True,
        },
        "source_staging": sources,
        "source_pair_final_freeze": pair,
        "target_baseline": target,
        "customer_source_plan": customers,
        "data_holds_or_policy_review": source_hold_summary(sources, customers),
        "cross_database_snapshot_atomic": same_connection,
        "next_write_authorization": "none: this report does not authorize database creation, registry DDL, or import writes.",
    }
    report["blockers"] = blockers(report)
    report["ready_for_clean_master_import"] = not report["blockers"]
    return report


def emit(report: dict[str, Any], output: Path | None) -> None:
    encoded = json.dumps(json_safe(report), ensure_ascii=False, sort_keys=True, indent=2)
    print(encoded)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded + "\n", encoding="utf-8")


def run_self_test() -> int:
    groups = [
        {"code_norm": "same", "rows": 1, "name_norm": "toko", "has_blank_name": False},
        {"code_norm": "dup", "rows": 2, "name_norm": "toko", "has_blank_name": False},
        {"code_norm": None, "rows": 1, "name_norm": "toko", "has_blank_name": False},
        {"code_norm": "blank", "rows": 1, "name_norm": None, "has_blank_name": True},
    ]
    valid, totals = classify_customer_groups(groups)
    assert set(valid) == {"same"}
    assert totals["held_rows"] == 4
    assert norm("  BMM ") == "bmm"
    assert norm("  ") is None
    print(json.dumps({"status": "ok", "self_test": REPORT_VERSION}, ensure_ascii=False))
    return 0


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()
    specs, registry_schema = load_policy(args.policy)
    if args.bdm_schema:
        ident(args.bdm_schema)
        specs["bdm_solo_dist"] = SourceSpec(
            specs["bdm_solo_dist"].source_system, args.bdm_schema,
            specs["bdm_solo_dist"].company_code, specs["bdm_solo_dist"].branch_code,
            specs["bdm_solo_dist"].document_prefix,
        )
    if args.tmp_schema:
        ident(args.tmp_schema)
        specs["tmp_solo_dist"] = SourceSpec(
            specs["tmp_solo_dist"].source_system, args.tmp_schema,
            specs["tmp_solo_dist"].company_code, specs["tmp_solo_dist"].branch_code,
            specs["tmp_solo_dist"].document_prefix,
        )
    if specs["bdm_solo_dist"].schema == specs["tmp_solo_dist"].schema:
        raise ValidationError("Schema staging BDM dan TMP harus berbeda.")
    target_config, source_config = configs(args)
    source_connection = connect_read_only(source_config, args.connect_timeout_seconds, "clean_master_readiness_source")
    target_connection = source_connection
    try:
        if target_config != source_config:
            target_connection = connect_read_only(target_config, args.connect_timeout_seconds, "clean_master_readiness_target")
        report = build_report(
            source_connection, target_connection, specs, registry_schema,
            args.statement_timeout_seconds, args.policy,
        )
        report["connections"] = {
            "source_staging": source_config.safe_label(),
            "target_baseline": target_config.safe_label(),
        }
        emit(report, args.output)
        return 3 if args.fail_if_not_ready and not report["ready_for_clean_master_import"] else 0
    finally:
        try:
            source_connection.rollback()
        finally:
            source_connection.close()
        if target_connection is not source_connection:
            try:
                target_connection.rollback()
            finally:
                target_connection.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            json.dumps(
                {"status": "error", "error_type": type(exc).__name__, "error": str(exc), "read_only": True},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2)
