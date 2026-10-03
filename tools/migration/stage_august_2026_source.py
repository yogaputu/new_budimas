#!/usr/bin/env python3
"""Source-separated SQL Server -> PostgreSQL staging for August 2026.

This is deliberately a *staging-only* tool.  It never writes to PostgreSQL
``public`` tables, never drops an existing schema, and requires
``--apply-stage`` before it writes anything.  Run BDM and TMP in separate
schemas because their business codes and document numbers overlap.

Final staging normally requires SQL Server SNAPSHOT isolation.  When that is
not available, an operator may use a separately confirmed source write-freeze
with ``--confirm-source-write-freeze`` and a shared maintenance-window ID.
That mode opens one SQL Server ``SERIALIZABLE`` read transaction and is
recorded as ``maintenance_freeze_serializable``.  It is never inferred from a
low-traffic period or relabelled from an ordinary read-committed run.

An explicit ``--allow-non-snapshot-preview`` may be used for a non-final,
read-committed preview schema; the run is marked
``read_committed_preview`` and must not be used as a merge input.

Required source-password environment variable:

  BDM: MIGRATION_BDM_SQL_PASSWORD
  TMP: MIGRATION_TMP_SQL_PASSWORD

When run locally on the aaPanel server as the operating-system ``postgres``
user, no PostgreSQL password is needed because the connection uses the local
Unix socket and peer authentication.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from audit_august_2026_sources import connect as mssql_connect
from audit_august_2026_sources import first_column, get_columns, quote_ident, source_config, table_name_sql


MODULE_SPECS: dict[str, tuple[dict[str, Any], ...]] = {
    "masters": (
        {"table": "Customer", "mode": "all"},
        {"table": "Principle", "mode": "all"},
        {"table": "Sales", "mode": "all"},
        {"table": "Plafon", "mode": "all"},
        {"table": "STOK", "mode": "all"},
        {"table": "BarangSatuan", "mode": "all", "optional": True},
    ),
    "sales": (
        {
            "table": "HJualSM",
            "mode": "date",
            "date_columns": ("Tanggal", "Tgl"),
        },
        {
            "table": "DJualSM",
            "mode": "child",
            "parent": "HJualSM",
            "parent_date_columns": ("Tanggal", "Tgl"),
            "child_key_columns": ("Nota", "NoNota", "No_Faktur"),
            "parent_key_columns": ("Nota", "NoNota", "No_Faktur"),
        },
        {
            "table": "HJualSMAndroid",
            "mode": "date",
            "date_columns": ("Tanggal", "Tgl"),
        },
        {
            "table": "DJualSMAndroid",
            "mode": "child",
            "parent": "HJualSMAndroid",
            "parent_date_columns": ("Tanggal", "Tgl"),
            "child_key_columns": ("Nota", "NoNota", "No_Faktur"),
            "parent_key_columns": ("Nota", "NoNota", "No_Faktur"),
        },
    ),
    "payments": (
        {
            "table": "HBayarSM",
            "mode": "date",
            "date_columns": ("Tanggal", "Tgl"),
        },
        {
            "table": "DBayarSM",
            "mode": "child",
            "parent": "HBayarSM",
            "parent_date_columns": ("Tanggal", "Tgl"),
            "child_key_columns": ("NoKwitansi", "NoBukti", "No_Bukti"),
            "parent_key_columns": ("NoKwitansi", "NoBukti", "No_Bukti"),
        },
        {
            "table": "Pembayaran",
            "mode": "date",
            "date_columns": ("Tanggal", "Tgl"),
        },
    ),
    "returns": (
        {
            "table": "HReturSM",
            "mode": "date",
            "date_columns": ("Tanggal", "Tgl"),
        },
        {
            "table": "DReturSM",
            "mode": "child",
            "parent": "HReturSM",
            "parent_date_columns": ("Tanggal", "Tgl"),
            "child_key_columns": ("Nota", "NoNota", "No_Retur"),
            "parent_key_columns": ("Nota", "NoNota", "No_Retur"),
        },
        {
            "table": "HReturSMAndroid",
            "mode": "date",
            "date_columns": ("Tanggal", "Tgl"),
        },
        {
            "table": "DReturSMAndroid",
            "mode": "child",
            "parent": "HReturSMAndroid",
            "parent_date_columns": ("Tanggal", "Tgl"),
            "child_key_columns": ("Nota", "NoNota", "No_Retur"),
            "parent_key_columns": ("Nota", "NoNota", "No_Retur"),
        },
    ),
    "visits": (
        {
            "table": "KunjunganSales",
            "mode": "date",
            "date_columns": ("Tanggal", "Tgl", "TanggalKunjungan"),
        },
    ),
    "stock-opname": (
        {
            "table": "StokOpnameAndroid",
            "mode": "date",
            "date_columns": ("TanggalInput", "Tanggal", "Tgl"),
        },
    ),
    "purchase": (
        {
            "table": "HPembelian",
            "mode": "date",
            "date_columns": ("Tanggal", "Tgl"),
        },
        {
            "table": "DPembelian",
            "mode": "child",
            "parent": "HPembelian",
            "parent_date_columns": ("Tanggal", "Tgl"),
            "child_key_columns": ("Nota", "NoNota", "No_Faktur"),
            "parent_key_columns": ("Nota", "NoNota", "No_Faktur"),
        },
    ),
}

SCHEMA_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
MAINTENANCE_WINDOW_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,119}$")
FREEZE_CONFIRMATION_LITERAL = "I_CONFIRM_SOURCE_WRITES_ARE_FROZEN"
FINAL_TRANSACTION_CONSISTENCY_MODES = {"snapshot", "maintenance_freeze_serializable"}
SENSITIVE_SOURCE_COLUMNS = {
    "password",
    "passwd",
    "pass_word",
    "password_hash",
    "kata_sandi",
    "pin",
    "token",
    "auth_token",
    "access_token",
    "refresh_token",
    "secret",
    "secret_key",
    "api_key",
    "apikey",
    "private_key",
    "credential",
}
SENSITIVE_SOURCE_FRAGMENTS = ("password", "passwd", "kata_sandi", "token", "secret", "api_key", "apikey", "private_key", "credential")


def clean_name(value: str) -> str:
    name = re.sub(r"[^0-9a-zA-Z_]+", "_", str(value or "").strip())
    name = re.sub(r"_+", "_", name).strip("_").lower()
    if not name:
        name = "col"
    if name[0].isdigit():
        name = f"c_{name}"
    return name


def unique_clean_columns(raw_columns: list[str]) -> list[str]:
    seen: defaultdict[str, int] = defaultdict(int)
    result = []
    for raw in raw_columns:
        base = clean_name(raw)
        seen[base] += 1
        result.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    return result


def non_sensitive_columns(columns: dict[str, str]) -> tuple[list[str], list[str]]:
    staged: list[str] = []
    redacted: list[str] = []
    for raw_column in columns.values():
        normalized = clean_name(raw_column)
        if normalized in SENSITIVE_SOURCE_COLUMNS or any(fragment in normalized for fragment in SENSITIVE_SOURCE_FRAGMENTS):
            redacted.append(raw_column)
        else:
            staged.append(raw_column)
    return staged, redacted


def pg_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def copy_escape(value: Any) -> str:
    if value is None:
        return r"\N"
    return (
        str(value)
        .replace("\x00", "")
        .replace("\\", "\\\\")
        .replace("\t", "\\t")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def parse_modules(raw: str) -> list[str]:
    modules = [item.strip() for item in raw.split(",") if item.strip()]
    unknown = [item for item in modules if item not in MODULE_SPECS]
    if unknown:
        raise ValueError(f"Module tidak dikenal: {', '.join(unknown)}")
    if not modules:
        raise ValueError("Pilih minimal satu module.")
    return list(dict.fromkeys(modules))


def selected_specs(modules: list[str]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for module in modules:
        for spec in MODULE_SPECS[module]:
            if spec["table"] not in seen:
                specs.append(dict(spec, module=module))
                seen.add(spec["table"])
    return specs


def filter_specs_by_table(specs: list[dict[str, Any]], raw_tables: str | None) -> list[dict[str, Any]]:
    """Restrict a stage run to an explicit subset of selected tables.

    This is useful for a narrowly scoped, final master refresh (for example
    Customer only) without accidentally staging unrelated master tables.  The
    requested names must still belong to the selected modules so a typo cannot
    silently create an incomplete run.
    """
    if not raw_tables:
        return specs
    wanted = [item.strip().lower() for item in raw_tables.split(",") if item.strip()]
    if not wanted:
        raise ValueError("--tables harus berisi minimal satu nama tabel.")
    available = {str(spec["table"]).lower(): spec for spec in specs}
    unknown = [item for item in wanted if item not in available]
    if unknown:
        raise ValueError(
            "Tabel tidak tersedia pada module yang dipilih: " + ", ".join(unknown)
        )
    return [available[item] for item in dict.fromkeys(wanted)]


def normalised_key(alias: str, column: str) -> str:
    return f"NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(4000), {alias}.{quote_ident(column)}))), '')"


def source_projection(columns: list[str], alias: str = "") -> str:
    return ", ".join(f"{alias}{quote_ident(column)}" for column in columns)


def build_source_query(
    spec: dict[str, Any],
    metadata: dict[str, dict[str, str]],
    projection: str,
    start: str,
    end: str,
) -> tuple[str, tuple[Any, ...], dict[str, Any]]:
    table = spec["table"]
    mode = spec["mode"]
    columns = metadata[table]
    if mode == "all":
        return f"SELECT {projection} FROM {table_name_sql(table)}", (), {"mode": mode}
    if mode == "date":
        date_column = first_column(columns, spec["date_columns"])
        if not date_column:
            raise ValueError(f"{table}: kolom tanggal tidak ditemukan.")
        return (
            f"SELECT {projection} FROM {table_name_sql(table)} "
            f"WHERE {quote_ident(date_column)} >= %s AND {quote_ident(date_column)} < %s",
            (start, end),
            {"mode": mode, "date_column": date_column},
        )
    if mode == "child":
        parent_table = spec["parent"]
        parent_columns = metadata.get(parent_table, {})
        if not parent_columns:
            raise ValueError(f"{table}: tabel header {parent_table} tidak tersedia.")
        child_key = first_column(columns, spec["child_key_columns"])
        parent_key = first_column(parent_columns, spec["parent_key_columns"])
        parent_date = first_column(parent_columns, spec["parent_date_columns"])
        if not all((child_key, parent_key, parent_date)):
            raise ValueError(f"{table}: relasi detail ke {parent_table} tidak lengkap.")
        return (
            f"SELECT {projection} FROM {table_name_sql(table)} d "
            f"WHERE EXISTS ("
            f"SELECT 1 FROM {table_name_sql(parent_table)} h "
            f"WHERE {normalised_key('d', child_key)} = {normalised_key('h', parent_key)} "
            f"AND h.{quote_ident(parent_date)} >= %s "
            f"AND h.{quote_ident(parent_date)} < %s"
            f")",
            (start, end),
            {
                "mode": mode,
                "parent_table": parent_table,
                "child_key_column": child_key,
                "parent_key_column": parent_key,
                "parent_date_column": parent_date,
            },
        )
    raise ValueError(f"{table}: mode seleksi tidak didukung: {mode}")


def selected_count(cursor, spec: dict[str, Any], metadata: dict[str, dict[str, str]], start: str, end: str):
    query, params, selection = build_source_query(spec, metadata, "COUNT_BIG(*)", start, end)
    cursor.execute(query, params)
    return int(cursor.fetchone()[0] or 0), selection


def source_runtime_info(cursor) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT
            @@SERVERNAME,
            DB_NAME(),
            snapshot_isolation_state_desc,
            is_read_committed_snapshot_on
        FROM sys.databases
        WHERE name = DB_NAME()
        """
    )
    server_name, database_name, snapshot_state, read_committed_snapshot = cursor.fetchone()
    return {
        "server_name": str(server_name),
        "database_name": str(database_name),
        "snapshot_isolation_state": str(snapshot_state),
        "read_committed_snapshot": bool(read_committed_snapshot),
    }


def begin_source_transaction(source_conn, cursor, isolation_level: str, *, lock_timeout_ms: int | None = None) -> None:
    """Begin one read transaction without taking application-controlled locks.

    SQL Server has no portable ``READ ONLY`` transaction command.  This tool
    nevertheless issues only metadata/read queries after this point; source
    safety additionally depends on the migration login being granted SELECT
    rather than DML permissions.  ``SERIALIZABLE`` is intentionally used only
    inside a real maintenance freeze: its shared/range locks are held until
    the stage completes and may otherwise make source writers wait.
    """

    if isolation_level not in {"SNAPSHOT", "SERIALIZABLE"}:
        raise ValueError(f"Isolation level source tidak diizinkan: {isolation_level!r}")
    if lock_timeout_ms is not None and lock_timeout_ms <= 0:
        raise ValueError("Source lock timeout harus lebih besar dari nol.")
    source_conn.rollback()
    source_conn.autocommit(False)
    cursor.execute(f"SET TRANSACTION ISOLATION LEVEL {isolation_level}")
    if lock_timeout_ms is not None:
        cursor.execute(f"SET LOCK_TIMEOUT {int(lock_timeout_ms)}")
    # If an unexpected source transaction conflicts, let the migration lose
    # rather than let it become a priority over the operational application.
    cursor.execute("SET DEADLOCK_PRIORITY LOW")
    cursor.execute("BEGIN TRANSACTION")


def begin_consistent_source_read(
    source_conn,
    cursor,
    *,
    allow_non_snapshot_preview: bool,
    confirmed_source_write_freeze: bool,
    maintenance_window_id: str | None,
    source_lock_timeout_seconds: int,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """Choose and start the only supported source-read consistency modes.

    ``maintenance_freeze_serializable`` is an operator attestation, not an
    automatic proof that source writers stopped.  The caller must require the
    explicit CLI confirmation and preserve it in staging metadata so a later
    public-table apply can reject ordinary preview data.
    """

    runtime = source_runtime_info(cursor)
    if confirmed_source_write_freeze:
        if not maintenance_window_id:
            raise RuntimeError("Maintenance window ID wajib ada untuk source write-freeze.")
        lock_timeout_ms = source_lock_timeout_seconds * 1000
        begin_source_transaction(
            source_conn,
            cursor,
            "SERIALIZABLE",
            lock_timeout_ms=lock_timeout_ms,
        )
        return runtime, "maintenance_freeze_serializable", {
            "is_preview": False,
            "maintenance_window_id": maintenance_window_id,
            "maintenance_freeze_attested": True,
            "maintenance_freeze_confirmed_at": datetime.now(timezone.utc),
            "source_transaction_isolation": "SERIALIZABLE",
            "source_lock_timeout_ms": lock_timeout_ms,
        }
    if runtime["snapshot_isolation_state"] == "ON":
        begin_source_transaction(source_conn, cursor, "SNAPSHOT")
        return runtime, "snapshot", {
            "is_preview": False,
            "maintenance_window_id": None,
            "maintenance_freeze_attested": False,
            "maintenance_freeze_confirmed_at": None,
            "source_transaction_isolation": "SNAPSHOT",
            "source_lock_timeout_ms": None,
        }
    if allow_non_snapshot_preview:
        source_conn.rollback()
        source_conn.autocommit(True)
        return runtime, "read_committed_preview", {
            "is_preview": True,
            "maintenance_window_id": None,
            "maintenance_freeze_attested": False,
            "maintenance_freeze_confirmed_at": None,
            "source_transaction_isolation": "READ COMMITTED",
            "source_lock_timeout_ms": None,
        }
    raise RuntimeError(
        "SQL Server sumber tidak mengaktifkan SNAPSHOT isolation. "
        "Staging final dihentikan agar tidak mengambil data yang berubah di tengah proses. "
        "Gunakan backup konsisten, atau jalankan hanya saat write-freeze benar-benar aktif "
        "dengan --confirm-source-write-freeze dan --maintenance-window-id; "
        "alternatifnya jalankan preview eksplisit."
    )


def pg_connect(database: str, user: str, host: str | None, port: int | None):
    try:
        import psycopg2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("Modul psycopg2 diperlukan untuk staging PostgreSQL.") from exc
    kwargs: dict[str, Any] = {"dbname": database, "user": user}
    if host:
        kwargs["host"] = host
    if port:
        kwargs["port"] = port
    return psycopg2.connect(**kwargs)


def ensure_new_schema(
    conn,
    schema: str,
    source: dict[str, Any],
    runtime: dict[str, Any],
    consistency_mode: str,
    consistency_details: dict[str, Any],
    start: str,
    end: str,
    modules: list[str],
):
    with conn.cursor() as cursor:
        cursor.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = %s", (schema,))
        if cursor.fetchone():
            raise RuntimeError(
                f"Schema {schema} sudah ada. Tool ini menolak menimpa staging yang sudah ada. "
                "Gunakan nama run baru setelah memeriksa schema lama."
            )
        cursor.execute(f"CREATE SCHEMA {pg_ident(schema)}")
        cursor.execute(
            f"""
            CREATE TABLE {pg_ident(schema)}.__stage_run (
                id BIGSERIAL PRIMARY KEY,
                source_system TEXT NOT NULL,
                source_server TEXT NOT NULL,
                source_database TEXT NOT NULL,
                consistency_mode TEXT NOT NULL,
                is_preview BOOLEAN NOT NULL DEFAULT FALSE,
                maintenance_window_id TEXT,
                maintenance_freeze_attested BOOLEAN NOT NULL DEFAULT FALSE,
                maintenance_freeze_confirmed_at TIMESTAMPTZ,
                source_transaction_isolation TEXT NOT NULL,
                source_lock_timeout_ms INTEGER,
                target_company_code TEXT NOT NULL,
                target_company_id INTEGER NOT NULL,
                target_branch_code TEXT NOT NULL,
                target_branch_id INTEGER NOT NULL,
                window_start TIMESTAMP NOT NULL,
                window_end_exclusive TIMESTAMP NOT NULL,
                modules TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                completed_at TIMESTAMPTZ,
                error TEXT
            )
            """
        )
        cursor.execute(
            f"""
            INSERT INTO {pg_ident(schema)}.__stage_run
                (source_system, source_server, source_database, consistency_mode,
                 is_preview, maintenance_window_id, maintenance_freeze_attested,
                 maintenance_freeze_confirmed_at, source_transaction_isolation, source_lock_timeout_ms,
                 target_company_code, target_company_id, target_branch_code, target_branch_id,
                 window_start, window_end_exclusive, modules)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                source["source_system"],
                runtime["server_name"],
                runtime["database_name"],
                consistency_mode,
                bool(consistency_details["is_preview"]),
                consistency_details["maintenance_window_id"],
                bool(consistency_details["maintenance_freeze_attested"]),
                consistency_details["maintenance_freeze_confirmed_at"],
                consistency_details["source_transaction_isolation"],
                consistency_details["source_lock_timeout_ms"],
                source["company_code"],
                source["company_id"],
                source["branch_code"],
                source["branch_id"],
                start,
                end,
                ",".join(modules),
            ),
        )
        cursor.execute(
            f"""
            CREATE TABLE {pg_ident(schema)}.__stage_manifest (
                legacy_table TEXT PRIMARY KEY,
                module TEXT NOT NULL,
                selection JSONB NOT NULL,
                source_columns JSONB NOT NULL,
                source_row_count BIGINT,
                staged_row_count BIGINT,
                status TEXT NOT NULL,
                started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                finished_at TIMESTAMPTZ,
                error TEXT
            )
            """
        )
    conn.commit()


def finish_stage_run(conn, schema: str, status: str, error: str | None = None):
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {pg_ident(schema)}.__stage_run
            SET status = %s, completed_at = NOW(), error = %s
            WHERE id = (SELECT MAX(id) FROM {pg_ident(schema)}.__stage_run)
            """,
            (status, error),
        )
    conn.commit()


def create_stage_table(conn, schema: str, table: str, clean_columns: list[str]):
    definitions = [
        "staging_id BIGSERIAL PRIMARY KEY",
        "source_system TEXT NOT NULL",
        "target_company_id INTEGER NOT NULL",
        "target_branch_id INTEGER NOT NULL",
        "legacy_table TEXT NOT NULL",
        "source_row_hash TEXT NOT NULL",
        "imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    ]
    definitions.extend(f"{pg_ident(column)} TEXT" for column in clean_columns)
    with conn.cursor() as cursor:
        cursor.execute(
            f"CREATE TABLE {pg_ident(schema)}.{pg_ident(clean_name(table))} ({', '.join(definitions)})"
        )
        cursor.execute(
            f"CREATE INDEX {pg_ident('idx_' + clean_name(table) + '_source')} "
            f"ON {pg_ident(schema)}.{pg_ident(clean_name(table))} (source_system)"
        )
        cursor.execute(
            f"CREATE INDEX {pg_ident('idx_' + clean_name(table) + '_row_hash')} "
            f"ON {pg_ident(schema)}.{pg_ident(clean_name(table))} (source_system, source_row_hash)"
        )
    conn.commit()


def write_manifest(conn, schema: str, table: str, module: str, selection: dict[str, Any], raw_columns: list[str], status: str, source_rows=None, staged_rows=None, error=None):
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {pg_ident(schema)}.__stage_manifest
                (legacy_table, module, selection, source_columns, source_row_count, staged_row_count, status, finished_at, error)
            VALUES (%s, %s, %s::jsonb, %s::jsonb, %s, %s, %s,
                    CASE WHEN %s IN ('done', 'failed') THEN NOW() ELSE NULL END, %s)
            ON CONFLICT (legacy_table) DO UPDATE SET
                selection = EXCLUDED.selection,
                source_columns = EXCLUDED.source_columns,
                source_row_count = EXCLUDED.source_row_count,
                staged_row_count = EXCLUDED.staged_row_count,
                status = EXCLUDED.status,
                finished_at = EXCLUDED.finished_at,
                error = EXCLUDED.error
            """,
            (
                table,
                module,
                json.dumps(selection),
                json.dumps(raw_columns),
                source_rows,
                staged_rows,
                status,
                status,
                error,
            ),
        )
    conn.commit()


def source_row_hash(table: str, row: tuple[Any, ...]) -> str:
    payload = "\x1f".join("<NULL>" if value is None else str(value) for value in row)
    return hashlib.sha256((table + "\x1e" + payload).encode("utf-8", errors="surrogatepass")).hexdigest()


def copy_chunk(conn, schema: str, table: str, clean_columns: list[str], source: dict[str, Any], rows: list[tuple[Any, ...]]):
    if not rows:
        return
    staging_columns = [
        "source_system",
        "target_company_id",
        "target_branch_id",
        "legacy_table",
        "source_row_hash",
        *clean_columns,
    ]
    data = io.StringIO()
    for row in rows:
        values = (
            source["source_system"],
            source["company_id"],
            source["branch_id"],
            table,
            source_row_hash(table, row),
            *row,
        )
        data.write("\t".join(copy_escape(value) for value in values) + "\n")
    data.seek(0)
    copy_sql = (
        f"COPY {pg_ident(schema)}.{pg_ident(clean_name(table))} "
        f"({', '.join(pg_ident(column) for column in staging_columns)}) "
        "FROM STDIN WITH (FORMAT text, DELIMITER E'\\t', NULL '\\N')"
    )
    with conn.cursor() as cursor:
        cursor.copy_expert(copy_sql, data)
    conn.commit()


def stage_table(
    source_cursor,
    target_conn,
    schema: str,
    source: dict[str, Any],
    spec: dict[str, Any],
    metadata: dict[str, dict[str, str]],
    start: str,
    end: str,
    chunk_size: int,
) -> dict[str, Any]:
    table = spec["table"]
    raw_columns, redacted_columns = non_sensitive_columns(metadata[table])
    clean_columns = unique_clean_columns(raw_columns)
    projection_prefix = "d." if spec["mode"] == "child" else ""
    query, params, selection = build_source_query(
        spec,
        metadata,
        source_projection(raw_columns, projection_prefix),
        start,
        end,
    )
    expected_rows, _ = selected_count(source_cursor, spec, metadata, start, end)
    if redacted_columns:
        selection = {**selection, "redacted_columns": redacted_columns}
    write_manifest(
        target_conn,
        schema,
        table,
        spec["module"],
        selection,
        raw_columns,
        "started",
        source_rows=expected_rows,
    )
    create_stage_table(target_conn, schema, table, clean_columns)
    staged_rows = 0
    try:
        source_cursor.execute(query, params)
        while True:
            rows = source_cursor.fetchmany(chunk_size)
            if not rows:
                break
            copy_chunk(target_conn, schema, table, clean_columns, source, rows)
            staged_rows += len(rows)
            print(json.dumps({"table": table, "staged_rows": staged_rows}, ensure_ascii=False), flush=True)
        with target_conn.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM {pg_ident(schema)}.{pg_ident(clean_name(table))}")
            target_rows = int(cursor.fetchone()[0] or 0)
        if target_rows != staged_rows or staged_rows != expected_rows:
            raise RuntimeError(
                f"{table}: count tidak cocok (source={expected_rows}, copied={staged_rows}, target={target_rows})."
            )
        write_manifest(
            target_conn,
            schema,
            table,
            spec["module"],
            selection,
            raw_columns,
            "done",
            source_rows=expected_rows,
            staged_rows=staged_rows,
        )
        return {"table": table, "status": "done", "source_rows": expected_rows, "staged_rows": staged_rows, "selection": selection}
    except Exception as exc:
        write_manifest(
            target_conn,
            schema,
            table,
            spec["module"],
            selection,
            raw_columns,
            "failed",
            source_rows=expected_rows,
            staged_rows=staged_rows,
            error=str(exc),
        )
        raise


def preflight(source: dict[str, Any], specs: list[dict[str, Any]], start: str, end: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "read_only": True,
        "source_system": source["source_system"],
        "window": {"start_inclusive": start, "end_exclusive": end},
        "tables": [],
    }
    with mssql_connect(source) as conn:
        cursor = conn.cursor()
        result["source_runtime"] = source_runtime_info(cursor)
        metadata = {spec["table"]: get_columns(cursor, spec["table"]) for spec in specs}
        for spec in specs:
            table = spec["table"]
            item = {"table": table, "module": spec["module"]}
            if not metadata[table]:
                item["status"] = "missing_table"
                if not spec.get("optional"):
                    result["tables"].append(item)
                    continue
            elif metadata[table]:
                try:
                    count, selection = selected_count(cursor, spec, metadata, start, end)
                    item.update({"status": "ready", "source_rows": count, "selection": selection})
                except Exception as exc:
                    item.update({"status": "not_ready", "error": str(exc)})
            result["tables"].append(item)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("bdm-solo", "tmp-solo"), required=True)
    parser.add_argument(
        "--modules",
        required=True,
        help=f"Comma-separated: {', '.join(MODULE_SPECS)}. Pilih eksplisit agar batch tidak diam-diam tidak lengkap.",
    )
    parser.add_argument(
        "--tables",
        help="Optional comma-separated table subset from the selected modules (for example: Customer).",
    )
    parser.add_argument("--start", default="2026-08-01 00:00:00")
    parser.add_argument("--end-exclusive", default="2026-08-28 00:00:00")
    parser.add_argument("--schema", help="New PostgreSQL staging schema. Required with --apply-stage.")
    parser.add_argument("--apply-stage", action="store_true", help="Create a new isolated staging schema and load it.")
    parser.add_argument(
        "--allow-non-snapshot-preview",
        action="store_true",
        help=(
            "Jika SQL Server SNAPSHOT isolation tidak tersedia, izinkan staging read-committed "
            "yang ditandai non-final/preview. Tidak boleh dipakai sebagai input merge."
        ),
    )
    parser.add_argument(
        "--confirm-source-write-freeze",
        choices=(FREEZE_CONFIRMATION_LITERAL,),
        metavar=FREEZE_CONFIRMATION_LITERAL,
        help=(
            "Hanya untuk maintenance window yang sudah benar-benar menghentikan seluruh write SQL Server "
            "(aplikasi, job, integrasi, dan sinkronisasi). Memaksa satu transaksi baca SERIALIZABLE; "
            "wajib disertai --maintenance-window-id."
        ),
    )
    parser.add_argument(
        "--maintenance-window-id",
        help=(
            "ID maintenance/freeze yang sama untuk staging BDM dan TMP, misalnya aug2026-bdm-tmp-01. "
            "Wajib dengan --confirm-source-write-freeze dan dicatat sebagai bukti audit."
        ),
    )
    parser.add_argument(
        "--source-lock-timeout-seconds",
        type=int,
        default=30,
        help=(
            "Batas tunggu lock SQL Server dalam mode write-freeze (default 30 detik). "
            "Jika ada writer/lock yang masih aktif, staging gagal alih-alih menunggu tanpa batas."
        ),
    )
    parser.add_argument("--chunk-size", type=int, default=5000)
    parser.add_argument("--target-database", default=os.getenv("MIGRATION_PG_DATABASE", "budimas_dev"))
    parser.add_argument("--target-user", default=os.getenv("MIGRATION_PG_USER", "postgres"))
    parser.add_argument("--target-host", default=os.getenv("MIGRATION_PG_HOST", ""))
    parser.add_argument("--target-port", type=int, default=int(os.getenv("MIGRATION_PG_PORT", "0") or 0))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        start_at = datetime.fromisoformat(args.start)
        end_at = datetime.fromisoformat(args.end_exclusive)
    except ValueError as exc:
        raise SystemExit(f"Format tanggal tidak valid: {exc}") from exc
    if start_at >= end_at:
        raise SystemExit("--end-exclusive harus lebih besar daripada --start.")
    if args.chunk_size <= 0:
        raise SystemExit("--chunk-size harus lebih besar dari nol.")
    if args.source_lock_timeout_seconds <= 0:
        raise SystemExit("--source-lock-timeout-seconds harus lebih besar dari nol.")
    if args.source_lock_timeout_seconds > 3600:
        raise SystemExit("--source-lock-timeout-seconds maksimal 3600 detik.")
    freeze_confirmed = args.confirm_source_write_freeze == FREEZE_CONFIRMATION_LITERAL
    if freeze_confirmed and args.allow_non_snapshot_preview:
        raise SystemExit(
            "--confirm-source-write-freeze tidak boleh digabung dengan --allow-non-snapshot-preview."
        )
    if freeze_confirmed and not args.maintenance_window_id:
        raise SystemExit("--maintenance-window-id wajib saat memakai --confirm-source-write-freeze.")
    if args.maintenance_window_id and not freeze_confirmed:
        raise SystemExit(
            "--maintenance-window-id hanya boleh dipakai bersama --confirm-source-write-freeze."
        )
    if args.maintenance_window_id and not MAINTENANCE_WINDOW_RE.fullmatch(args.maintenance_window_id):
        raise SystemExit(
            "--maintenance-window-id harus 3-120 karakter: huruf/angka lalu huruf, angka, titik, garis bawah, titik dua, atau strip."
        )
    if (freeze_confirmed or args.maintenance_window_id) and not args.apply_stage:
        raise SystemExit("Mode source write-freeze hanya berlaku bersama --apply-stage, bukan preflight.")
    try:
        modules = parse_modules(args.modules)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    source = source_config(args.source)
    try:
        specs = filter_specs_by_table(selected_specs(modules), args.tables)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    if not args.apply_stage:
        print(json.dumps(preflight(source, specs, args.start, args.end_exclusive), ensure_ascii=False, indent=2))
        return 0
    if not args.schema or not SCHEMA_RE.fullmatch(args.schema):
        raise SystemExit("--schema wajib berupa identifier PostgreSQL lowercase yang aman.")
    if not args.schema.startswith("legacy_"):
        raise SystemExit("--schema staging wajib diawali legacy_.")

    source_conn = mssql_connect(source)
    target_conn = None
    try:
        source_cursor = source_conn.cursor()
        runtime, consistency_mode, consistency_details = begin_consistent_source_read(
            source_conn,
            source_cursor,
            allow_non_snapshot_preview=args.allow_non_snapshot_preview,
            confirmed_source_write_freeze=freeze_confirmed,
            maintenance_window_id=args.maintenance_window_id,
            source_lock_timeout_seconds=args.source_lock_timeout_seconds,
        )
        metadata = {spec["table"]: get_columns(source_cursor, spec["table"]) for spec in specs}
        missing_required = [spec["table"] for spec in specs if not metadata[spec["table"]] and not spec.get("optional")]
        if missing_required:
            raise RuntimeError(f"Tabel sumber wajib tidak ditemukan: {', '.join(missing_required)}")

        target_conn = pg_connect(args.target_database, args.target_user, args.target_host or None, args.target_port or None)
        ensure_new_schema(
            target_conn,
            args.schema,
            source,
            runtime,
            consistency_mode,
            consistency_details,
            args.start,
            args.end_exclusive,
            modules,
        )
        results = []
        for spec in specs:
            if not metadata[spec["table"]]:
                print(json.dumps({"table": spec["table"], "status": "skipped_missing_optional"}), flush=True)
                continue
            results.append(
                stage_table(
                    source_cursor,
                    target_conn,
                    args.schema,
                    source,
                    spec,
                    metadata,
                    args.start,
                    args.end_exclusive,
                    args.chunk_size,
                )
            )
        if consistency_mode in FINAL_TRANSACTION_CONSISTENCY_MODES:
            source_conn.commit()
        final_status = "completed_preview" if consistency_mode == "read_committed_preview" else "completed"
        finish_stage_run(target_conn, args.schema, final_status)
        print(
            json.dumps(
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "schema": args.schema,
                    "source_system": source["source_system"],
                    "consistency_mode": consistency_mode,
                    "is_preview": bool(consistency_details["is_preview"]),
                    "maintenance_window_id": consistency_details["maintenance_window_id"],
                    "maintenance_freeze_attested": bool(consistency_details["maintenance_freeze_attested"]),
                    "source_transaction_isolation": consistency_details["source_transaction_isolation"],
                    "source_lock_timeout_ms": consistency_details["source_lock_timeout_ms"],
                    "tables": results,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except Exception as exc:
        if target_conn:
            try:
                finish_stage_run(target_conn, args.schema, "failed", str(exc))
            except Exception:
                pass
        raise
    finally:
        if source_conn:
            try:
                source_conn.rollback()
            except Exception:
                pass
            source_conn.close()
        if target_conn:
            target_conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
