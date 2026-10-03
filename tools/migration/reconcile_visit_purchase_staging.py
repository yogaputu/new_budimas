#!/usr/bin/env python3
"""Read-only reconciliation for source-separated August 2026 visits/purchases.

The report intentionally reads only the two isolated staging schemas and the
approved source-aware mapping registry ``migration_bdm_tmp_202608``.  It never
reads or writes ``public`` application tables, does not create audit tables,
and ends the PostgreSQL transaction with ``ROLLBACK``.

It is safe to run against either a final snapshot stage, an attested
``maintenance_freeze_serializable`` stage, or a clearly labelled
read-committed preview stage.  A preview or unverified consistency stage is
reported as non-final; this tool is a coverage report, not permission to merge
anything into ERP.

Example (on the PostgreSQL host):

    python3 tools/migration/reconcile_visit_purchase_staging.py \
      --bdm-schema legacy_bdm_solo_aug2026_preview \
      --tmp-schema legacy_tmp_solo_aug2026_preview

The JSON output deliberately keeps DPembelian quantity fields as raw source
signals.  It does *not* infer an UOM code or conversion from ``unit``,
``perunit``, ``satuan``, or ``jumlah``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable


REGISTRY_SCHEMA = "migration_bdm_tmp_202608"
FINAL_TRANSACTION_CONSISTENCY_MODES = frozenset({"snapshot", "maintenance_freeze_serializable"})
FREEZE_METADATA_COLUMNS = frozenset(
    {
        "maintenance_window_id",
        "maintenance_freeze_attested",
        "maintenance_freeze_confirmed_at",
        "source_transaction_isolation",
    }
)
# Schema arguments are additionally required to start with ``legacy_`` below.
# Internal stage metadata tables intentionally begin with ``__``.
IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
STAGE_TABLES = {
    "kunjungansales": {
        "required_columns": {"staging_id", "source_system", "kodecustomer", "kodeprinciple", "kodesales"},
        "legacy_table": "KunjunganSales",
    },
    "hpembelian": {
        "required_columns": {"staging_id", "source_system", "nota", "kodeprinciple"},
        "legacy_table": "HPembelian",
    },
    "dpembelian": {
        "required_columns": {"staging_id", "source_system", "nota", "kodeprinciple", "kodestok"},
        "legacy_table": "DPembelian",
    },
}
QUANTITY_COLUMNS = ("unit", "perunit", "satuan", "jumlah")
ACTIVE_PURCHASE_IMPORT_REQUIREMENTS = (
    "Deklarasi yang disetujui untuk arti setiap field DPembelian: field mana yang merupakan qty UOM, qty PCS/base, faktor konversi, dan harga per UOM/base. Nilai numerik raw tidak boleh dipakai sebagai kode UOM.",
    "Mapping UOM eksplisit per source_system + principal + SKU ke product_uom_map yang exact (kode, level, faktor, id_produk, dan id_produk_uom), serta bukti setiap detail memenuhi qty_uom × faktor = qty_base tanpa pembulatan.",
    "Konfirmasi arti HPembelian.stnota dan lifecycle target: apakah nota merupakan PO, penerimaan barang, transaksi selesai, batal, atau retur. Status tidak boleh diterjemahkan dengan asumsi lama.",
    "Kebijakan penerimaan aktif untuk batch, expired date, gudang/rak, dan kuantitas diterima. Bila data itu tidak tersedia, import tidak boleh membuat inventory_ledger, stok WMS, atau penerimaan selesai.",
    "Mapping tagihan/pembayaran supplier dan nomor dokumen source-aware (BDM-SLO/TMP-SLO), termasuk aturan total, retur, diskon, PPN, dan jatuh tempo yang direkonsiliasi per nota.",
)
REGISTRY_REQUIREMENTS = {
    "source_context": {"source_system", "target_company_id", "target_branch_id"},
    "customer_map": {"source_system", "source_customer_code_norm", "id_customer"},
    "principal_map": {"source_system", "source_principal_code_norm", "id_principal"},
    "sales_map": {
        "source_system",
        "source_principal_code_norm",
        "source_sales_code_norm",
        "id_sales",
    },
    "product_map": {
        "source_system",
        "source_principal_code_norm",
        "source_sku_norm",
        "id_produk",
    },
}


class SchemaValidationError(RuntimeError):
    """Raised before reporting when a schema cannot be interpreted safely."""


def ident(value: str) -> str:
    """Quote a PostgreSQL identifier after a deliberately narrow validation."""

    if not IDENT_RE.fullmatch(value):
        raise ValueError(f"Identifier PostgreSQL tidak aman: {value!r}")
    return f'"{value}"'


def qtable(schema: str, table: str) -> str:
    return f"{ident(schema)}.{ident(table)}"


def normalized(alias: str, column: str) -> str:
    """Normalise legacy text keys exactly like the mapping registry keys."""

    return f"NULLIF(lower(btrim({alias}.{ident(column)})), '')"


def json_value(value: Any) -> Any:
    """Convert PostgreSQL/Python scalar values to stable JSON values."""

    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def as_dict(cursor, row: tuple[Any, ...] | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {
        description.name: json_value(value)
        for description, value in zip(cursor.description, row)
    }


def fetch_one(cursor, query: str, params: Iterable[Any] = ()) -> dict[str, Any]:
    cursor.execute(query, tuple(params))
    return as_dict(cursor, cursor.fetchone())


def fetch_all(cursor, query: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    cursor.execute(query, tuple(params))
    return [as_dict(cursor, row) for row in cursor.fetchall()]


def pg_connect(database: str, user: str, host: str | None, port: int | None):
    try:
        import psycopg2  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on runtime image
        raise RuntimeError("Modul psycopg2 diperlukan untuk laporan PostgreSQL.") from exc

    kwargs: dict[str, Any] = {"dbname": database, "user": user}
    if host:
        kwargs["host"] = host
    if port:
        kwargs["port"] = port
    connection = psycopg2.connect(**kwargs)
    # This applies before the first query and protects against accidental
    # future writes while the report evolves.
    connection.set_session(readonly=True, autocommit=False)
    return connection


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bdm-schema", required=True, help="Schema staging BDM Solo yang terpisah.")
    parser.add_argument("--tmp-schema", required=True, help="Schema staging TMP Solo yang terpisah.")
    parser.add_argument(
        "--pg-database",
        default=os.getenv("MIGRATION_PG_DATABASE", "budimas_dev"),
        help="Nama database PostgreSQL (default: MIGRATION_PG_DATABASE atau budimas_dev).",
    )
    parser.add_argument(
        "--pg-user",
        default=os.getenv("MIGRATION_PG_USER", "postgres"),
        help="User PostgreSQL read-only (default: MIGRATION_PG_USER atau postgres).",
    )
    parser.add_argument(
        "--pg-host",
        default=os.getenv("MIGRATION_PG_HOST", ""),
        help="Host PostgreSQL; kosong berarti Unix socket lokal.",
    )
    parser.add_argument(
        "--pg-port",
        type=int,
        default=int(os.getenv("MIGRATION_PG_PORT", "0") or 0),
        help="Port PostgreSQL; 0 berarti driver default.",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=20,
        help="Maksimal contoh per isu kunci dokumen (default: 20).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Opsional: simpan JSON ke file ini selain mencetaknya ke stdout.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    ident(args.bdm_schema)
    ident(args.tmp_schema)
    if args.bdm_schema == args.tmp_schema:
        raise ValueError("--bdm-schema dan --tmp-schema wajib berbeda.")
    if not args.bdm_schema.startswith("legacy_") or not args.tmp_schema.startswith("legacy_"):
        raise ValueError("Kedua schema staging wajib diawali legacy_.")
    if args.pg_port < 0 or args.pg_port > 65535:
        raise ValueError("--pg-port harus 0 sampai 65535.")
    if args.sample_limit <= 0 or args.sample_limit > 200:
        raise ValueError("--sample-limit harus 1 sampai 200.")


def table_columns(cursor, schema: str, table: str) -> set[str]:
    rows = fetch_all(
        cursor,
        """
        SELECT lower(column_name) AS column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        """,
        (schema, table),
    )
    return {str(row["column_name"]) for row in rows}


def require_columns(cursor, schema: str, table: str, required: set[str]) -> set[str]:
    columns = table_columns(cursor, schema, table)
    if not columns:
        raise SchemaValidationError(f"Tabel wajib tidak ditemukan: {schema}.{table}")
    missing = sorted(required - columns)
    if missing:
        raise SchemaValidationError(
            f"{schema}.{table} tidak memiliki kolom wajib: {', '.join(missing)}"
        )
    return columns


def validate_registry(cursor) -> None:
    for table, required in REGISTRY_REQUIREMENTS.items():
        require_columns(cursor, REGISTRY_SCHEMA, table, required)


def stage_metadata(cursor, schema: str, expected_source: str) -> dict[str, Any]:
    stage_run_columns = require_columns(
        cursor,
        schema,
        "__stage_run",
        {
            "source_system",
            "id",
            "target_company_id",
            "target_branch_id",
            "window_start",
            "window_end_exclusive",
            "consistency_mode",
            "is_preview",
            "modules",
            "status",
            "created_at",
            "completed_at",
        },
    )
    freeze_projection = ",\n               ".join(
        (
            ident(column)
            if column in stage_run_columns
            else f"NULL AS {ident(column)}"
        )
        for column in sorted(FREEZE_METADATA_COLUMNS)
    )
    row = fetch_one(
        cursor,
        f"""
        SELECT source_system, target_company_id, target_branch_id,
               window_start, window_end_exclusive, consistency_mode, is_preview,
               modules, status, created_at, completed_at,
               {freeze_projection}
        FROM {qtable(schema, '__stage_run')}
        ORDER BY id DESC
        LIMIT 1
        """,
    )
    if not row:
        raise SchemaValidationError(f"{schema} tidak memiliki metadata __stage_run.")
    if row["source_system"] != expected_source:
        raise SchemaValidationError(
            f"{schema} memiliki source_system {row['source_system']!r}; "
            f"diharapkan {expected_source!r}."
        )
    if row["status"] not in {"completed", "completed_preview"}:
        raise SchemaValidationError(
            f"{schema} berstatus {row['status']!r}; laporan hanya menerima staging selesai."
        )
    consistency_mode = str(row["consistency_mode"] or "")
    if consistency_mode == "maintenance_freeze_serializable":
        missing_freeze_metadata = sorted(FREEZE_METADATA_COLUMNS - stage_run_columns)
        if missing_freeze_metadata:
            raise SchemaValidationError(
                f"{schema}: metadata write-freeze tidak lengkap: {', '.join(missing_freeze_metadata)}."
            )
        if not str(row["maintenance_window_id"] or "").strip():
            raise SchemaValidationError(f"{schema}: maintenance_window_id write-freeze kosong.")
        if row["maintenance_freeze_attested"] is not True:
            raise SchemaValidationError(
                f"{schema}: maintenance_freeze_attested harus true untuk write-freeze final."
            )
        if row["maintenance_freeze_confirmed_at"] is None:
            raise SchemaValidationError(
                f"{schema}: maintenance_freeze_confirmed_at write-freeze kosong."
            )
        if str(row["source_transaction_isolation"] or "").strip().lower() != "serializable":
            raise SchemaValidationError(
                f"{schema}: source_transaction_isolation harus SERIALIZABLE untuk write-freeze final."
            )
    context = fetch_one(
        cursor,
        f"""
        SELECT target_company_id, target_branch_id
        FROM {qtable(REGISTRY_SCHEMA, 'source_context')}
        WHERE source_system = %s
        """,
        (expected_source,),
    )
    if not context:
        raise SchemaValidationError(f"source_context registry tidak ada untuk {expected_source}.")
    if (
        int(row["target_company_id"]) != int(context["target_company_id"])
        or int(row["target_branch_id"]) != int(context["target_branch_id"])
    ):
        raise SchemaValidationError(
            f"Scope {schema} ({row['target_company_id']}/{row['target_branch_id']}) "
            f"tidak sesuai registry {expected_source} "
            f"({context['target_company_id']}/{context['target_branch_id']})."
        )
    row["stage_consistency_eligible"] = (
        row["status"] == "completed"
        and not bool(row["is_preview"])
        and consistency_mode in FINAL_TRANSACTION_CONSISTENCY_MODES
    )
    # Pair eligibility is calculated only after both BDM and TMP metadata have
    # been read.  This provisional value is deliberately not merge authority.
    row["merge_input_eligible"] = False
    return row


def paired_stage_input_status(
    bdm_metadata: dict[str, Any], tmp_metadata: dict[str, Any]
) -> dict[str, Any]:
    """Check that BDM/TMP final stages are a consistent pair, never a merge grant."""

    reasons: list[str] = []
    if not bdm_metadata["stage_consistency_eligible"] or not tmp_metadata["stage_consistency_eligible"]:
        reasons.append("salah_satu_stage_bukan_snapshot_atau_write_freeze_terattestasi")
    if bdm_metadata["consistency_mode"] != tmp_metadata["consistency_mode"]:
        reasons.append("consistency_mode_bdm_tmp_berbeda")
    if (
        bdm_metadata["window_start"] != tmp_metadata["window_start"]
        or bdm_metadata["window_end_exclusive"] != tmp_metadata["window_end_exclusive"]
    ):
        reasons.append("window_bdm_tmp_berbeda")
    if (
        bdm_metadata["consistency_mode"] == "maintenance_freeze_serializable"
        and tmp_metadata["consistency_mode"] == "maintenance_freeze_serializable"
        and bdm_metadata["maintenance_window_id"] != tmp_metadata["maintenance_window_id"]
    ):
        reasons.append("maintenance_window_id_bdm_tmp_berbeda")
    return {
        "pair_consistency_eligible": not reasons,
        "consistency_mode": {
            "bdm_solo_dist": bdm_metadata["consistency_mode"],
            "tmp_solo_dist": tmp_metadata["consistency_mode"],
        },
        "window_start": {
            "bdm_solo_dist": bdm_metadata["window_start"],
            "tmp_solo_dist": tmp_metadata["window_start"],
        },
        "window_end_exclusive": {
            "bdm_solo_dist": bdm_metadata["window_end_exclusive"],
            "tmp_solo_dist": tmp_metadata["window_end_exclusive"],
        },
        "maintenance_window_id": {
            "bdm_solo_dist": bdm_metadata["maintenance_window_id"],
            "tmp_solo_dist": tmp_metadata["maintenance_window_id"],
        },
        "reasons_not_eligible": reasons,
        "merge_permission": "never granted by this reconciliation script",
    }


def validate_stage_manifest(cursor, schema: str, table: str, legacy_table: str) -> None:
    require_columns(
        cursor,
        schema,
        "__stage_manifest",
        {"legacy_table", "module", "source_row_count", "staged_row_count", "status"},
    )
    manifest = fetch_one(
        cursor,
        f"""
        SELECT legacy_table, module, source_row_count, staged_row_count, status
        FROM {qtable(schema, '__stage_manifest')}
        WHERE lower(legacy_table) = lower(%s)
        """,
        (legacy_table,),
    )
    if not manifest:
        raise SchemaValidationError(f"{schema}: manifest {legacy_table} tidak ditemukan.")
    if manifest["status"] != "done":
        raise SchemaValidationError(
            f"{schema}: manifest {legacy_table} berstatus {manifest['status']!r}, bukan done."
        )
    if (
        manifest["source_row_count"] is None
        or manifest["staged_row_count"] is None
        or manifest["source_row_count"] != manifest["staged_row_count"]
    ):
        raise SchemaValidationError(
            f"{schema}: jumlah source/staged {legacy_table} tidak cocok "
            f"({manifest['source_row_count']} vs {manifest['staged_row_count']})."
        )


def validate_stage_table(cursor, schema: str, table: str, expected_source: str) -> set[str]:
    spec = STAGE_TABLES[table]
    columns = require_columns(cursor, schema, table, set(spec["required_columns"]))
    validate_stage_manifest(cursor, schema, table, str(spec["legacy_table"]))
    source_counts = fetch_all(
        cursor,
        f"""
        SELECT source_system, COUNT(*)::bigint AS row_count
        FROM {qtable(schema, table)}
        GROUP BY source_system
        """,
    )
    unexpected = [
        row
        for row in source_counts
        if row["source_system"] != expected_source and int(row["row_count"]) > 0
    ]
    if unexpected:
        raise SchemaValidationError(
            f"{schema}.{table} mengandung source_system yang tidak sesuai: {unexpected!r}"
        )
    return columns


def validate_source_schema(cursor, schema: str, expected_source: str) -> tuple[dict[str, Any], dict[str, set[str]]]:
    metadata = stage_metadata(cursor, schema, expected_source)
    columns = {
        table: validate_stage_table(cursor, schema, table, expected_source)
        for table in STAGE_TABLES
    }
    return metadata, columns


def map_coverage(
    cursor,
    *,
    schema: str,
    table: str,
    source_system: str,
    source_column: str,
    registry_table: str,
    registry_key_column: str,
    registry_id_column: str,
) -> dict[str, Any]:
    """Report one simple source-code -> approved-registry-map coverage."""

    key_expr = normalized("s", source_column)
    return fetch_one(
        cursor,
        f"""
        WITH source_rows AS (
            SELECT {key_expr} AS source_code
            FROM {qtable(schema, table)} s
            WHERE s.source_system = %s
        )
        SELECT
            COUNT(*)::bigint AS total_rows,
            COUNT(*) FILTER (WHERE source_code IS NOT NULL)::bigint AS source_code_present_rows,
            COUNT(*) FILTER (WHERE source_code IS NULL)::bigint AS source_code_missing_rows,
            COUNT(*) FILTER (WHERE m.{ident(registry_id_column)} IS NOT NULL)::bigint AS mapped_rows,
            COUNT(*) FILTER (
                WHERE source_code IS NOT NULL AND m.{ident(registry_id_column)} IS NULL
            )::bigint AS unmapped_rows
        FROM source_rows s
        LEFT JOIN {qtable(REGISTRY_SCHEMA, registry_table)} m
          ON m.source_system = %s
         AND m.{ident(registry_key_column)} = s.source_code
        """,
        (source_system, source_system),
    )


def visit_report(cursor, schema: str, source_system: str) -> dict[str, Any]:
    customer = map_coverage(
        cursor,
        schema=schema,
        table="kunjungansales",
        source_system=source_system,
        source_column="kodecustomer",
        registry_table="customer_map",
        registry_key_column="source_customer_code_norm",
        registry_id_column="id_customer",
    )
    principal = map_coverage(
        cursor,
        schema=schema,
        table="kunjungansales",
        source_system=source_system,
        source_column="kodeprinciple",
        registry_table="principal_map",
        registry_key_column="source_principal_code_norm",
        registry_id_column="id_principal",
    )
    sales = fetch_one(
        cursor,
        f"""
        WITH source_rows AS (
            SELECT
                {normalized('v', 'kodeprinciple')} AS principal_code,
                {normalized('v', 'kodesales')} AS sales_code
            FROM {qtable(schema, 'kunjungansales')} v
            WHERE v.source_system = %s
        )
        SELECT
            COUNT(*)::bigint AS total_rows,
            COUNT(*) FILTER (WHERE principal_code IS NULL)::bigint AS source_principal_code_missing_rows,
            COUNT(*) FILTER (WHERE sales_code IS NULL)::bigint AS source_sales_code_missing_rows,
            COUNT(*) FILTER (
                WHERE principal_code IS NOT NULL AND sales_code IS NOT NULL
            )::bigint AS source_pair_present_rows,
            COUNT(*) FILTER (WHERE sm.id_sales IS NOT NULL)::bigint AS mapped_rows,
            COUNT(*) FILTER (
                WHERE principal_code IS NOT NULL
                  AND sales_code IS NOT NULL
                  AND sm.id_sales IS NULL
            )::bigint AS unmapped_rows
        FROM source_rows s
        LEFT JOIN {qtable(REGISTRY_SCHEMA, 'sales_map')} sm
          ON sm.source_system = %s
         AND sm.source_principal_code_norm = s.principal_code
         AND sm.source_sales_code_norm = s.sales_code
        """,
        (source_system, source_system),
    )
    full = fetch_one(
        cursor,
        f"""
        WITH source_rows AS (
            SELECT
                {normalized('v', 'kodecustomer')} AS customer_code,
                {normalized('v', 'kodeprinciple')} AS principal_code,
                {normalized('v', 'kodesales')} AS sales_code
            FROM {qtable(schema, 'kunjungansales')} v
            WHERE v.source_system = %s
        )
        SELECT
            COUNT(*)::bigint AS total_rows,
            COUNT(*) FILTER (
                WHERE cm.id_customer IS NOT NULL
                  AND pm.id_principal IS NOT NULL
                  AND sm.id_sales IS NOT NULL
            )::bigint AS fully_mapped_rows,
            COUNT(*) FILTER (
                WHERE cm.id_customer IS NULL
                   OR pm.id_principal IS NULL
                   OR sm.id_sales IS NULL
            )::bigint AS held_rows
        FROM source_rows s
        LEFT JOIN {qtable(REGISTRY_SCHEMA, 'customer_map')} cm
          ON cm.source_system = %s
         AND cm.source_customer_code_norm = s.customer_code
        LEFT JOIN {qtable(REGISTRY_SCHEMA, 'principal_map')} pm
          ON pm.source_system = %s
         AND pm.source_principal_code_norm = s.principal_code
        LEFT JOIN {qtable(REGISTRY_SCHEMA, 'sales_map')} sm
          ON sm.source_system = %s
         AND sm.source_principal_code_norm = s.principal_code
         AND sm.source_sales_code_norm = s.sales_code
        """,
        (source_system, source_system, source_system, source_system),
    )
    return {
        "mapping_policy": "customer_map + principal_map + sales_map; no public-table lookup",
        "customer_map": customer,
        "principal_map": principal,
        "sales_map": sales,
        "combined": full,
    }


def document_key_report(
    cursor,
    *,
    schema: str,
    table: str,
    source_system: str,
    key_column: str,
    sample_limit: int,
) -> dict[str, Any]:
    key_expr = normalized("s", key_column)
    metrics = fetch_one(
        cursor,
        f"""
        WITH source_rows AS (
            SELECT staging_id, {key_expr} AS document_key
            FROM {qtable(schema, table)} s
            WHERE s.source_system = %s
        ), key_groups AS (
            SELECT document_key, COUNT(*)::bigint AS row_count
            FROM source_rows
            WHERE document_key IS NOT NULL
            GROUP BY document_key
        )
        SELECT
            (SELECT COUNT(*)::bigint FROM source_rows) AS total_rows,
            (SELECT COUNT(*)::bigint FROM source_rows WHERE document_key IS NULL) AS missing_key_rows,
            (SELECT COUNT(*)::bigint FROM source_rows WHERE document_key IS NOT NULL) AS keyed_rows,
            (SELECT COUNT(*)::bigint FROM key_groups) AS distinct_keys,
            (SELECT COUNT(*)::bigint FROM key_groups WHERE row_count > 1) AS duplicate_key_groups,
            (SELECT COALESCE(SUM(row_count - 1), 0)::bigint FROM key_groups WHERE row_count > 1)
                AS duplicate_key_rows_excess
        """,
        (source_system,),
    )
    duplicate_samples = fetch_all(
        cursor,
        f"""
        WITH source_rows AS (
            SELECT {key_expr} AS document_key
            FROM {qtable(schema, table)} s
            WHERE s.source_system = %s
        )
        SELECT document_key, COUNT(*)::bigint AS row_count
        FROM source_rows
        WHERE document_key IS NOT NULL
        GROUP BY document_key
        HAVING COUNT(*) > 1
        ORDER BY row_count DESC, document_key
        LIMIT %s
        """,
        (source_system, sample_limit),
    )
    missing_samples = fetch_all(
        cursor,
        f"""
        SELECT staging_id
        FROM {qtable(schema, table)} s
        WHERE s.source_system = %s
          AND {key_expr} IS NULL
        ORDER BY staging_id
        LIMIT %s
        """,
        (source_system, sample_limit),
    )
    return {
        **metrics,
        "normalization": "lower(trim(key)); blank is treated as missing",
        "duplicate_key_samples": duplicate_samples,
        "missing_key_staging_id_samples": missing_samples,
    }


def purchase_header_report(
    cursor, schema: str, source_system: str, sample_limit: int
) -> dict[str, Any]:
    principal = map_coverage(
        cursor,
        schema=schema,
        table="hpembelian",
        source_system=source_system,
        source_column="kodeprinciple",
        registry_table="principal_map",
        registry_key_column="source_principal_code_norm",
        registry_id_column="id_principal",
    )
    eligible = fetch_one(
        cursor,
        f"""
        WITH source_rows AS (
            SELECT
                {normalized('h', 'nota')} AS document_key,
                {normalized('h', 'kodeprinciple')} AS principal_code
            FROM {qtable(schema, 'hpembelian')} h
            WHERE h.source_system = %s
        )
        SELECT
            COUNT(*)::bigint AS total_rows,
            COUNT(*) FILTER (
                WHERE document_key IS NOT NULL AND pm.id_principal IS NOT NULL
            )::bigint AS document_key_and_principal_mapped_rows,
            COUNT(*) FILTER (
                WHERE document_key IS NULL OR pm.id_principal IS NULL
            )::bigint AS held_rows
        FROM source_rows s
        LEFT JOIN {qtable(REGISTRY_SCHEMA, 'principal_map')} pm
          ON pm.source_system = %s
         AND pm.source_principal_code_norm = s.principal_code
        """,
        (source_system, source_system),
    )
    return {
        "document_keys": document_key_report(
            cursor,
            schema=schema,
            table="hpembelian",
            source_system=source_system,
            key_column="nota",
            sample_limit=sample_limit,
        ),
        "principal_map": principal,
        "combined": eligible,
    }


def detail_product_report(cursor, schema: str, source_system: str) -> dict[str, Any]:
    return fetch_one(
        cursor,
        f"""
        WITH source_rows AS (
            SELECT
                {normalized('d', 'kodeprinciple')} AS principal_code,
                {normalized('d', 'kodestok')} AS product_code
            FROM {qtable(schema, 'dpembelian')} d
            WHERE d.source_system = %s
        )
        SELECT
            COUNT(*)::bigint AS total_rows,
            COUNT(*) FILTER (WHERE principal_code IS NULL)::bigint AS source_principal_code_missing_rows,
            COUNT(*) FILTER (WHERE principal_code IS NOT NULL)::bigint AS source_principal_code_present_rows,
            COUNT(*) FILTER (WHERE pm.id_principal IS NOT NULL)::bigint AS principal_mapped_rows,
            COUNT(*) FILTER (
                WHERE principal_code IS NOT NULL AND pm.id_principal IS NULL
            )::bigint AS principal_unmapped_rows,
            COUNT(*) FILTER (WHERE product_code IS NULL)::bigint AS source_product_code_missing_rows,
            COUNT(*) FILTER (WHERE product_code IS NOT NULL)::bigint AS source_product_code_present_rows,
            COUNT(*) FILTER (
                WHERE principal_code IS NOT NULL AND product_code IS NOT NULL
            )::bigint AS source_principal_product_pair_present_rows,
            COUNT(*) FILTER (WHERE prd.id_produk IS NOT NULL)::bigint AS product_mapped_rows,
            COUNT(*) FILTER (
                WHERE principal_code IS NOT NULL
                  AND product_code IS NOT NULL
                  AND prd.id_produk IS NULL
            )::bigint AS product_unmapped_rows,
            COUNT(*) FILTER (
                WHERE pm.id_principal IS NOT NULL AND prd.id_produk IS NOT NULL
            )::bigint AS fully_mapped_rows,
            COUNT(*) FILTER (
                WHERE pm.id_principal IS NULL OR prd.id_produk IS NULL
            )::bigint AS held_rows
        FROM source_rows s
        LEFT JOIN {qtable(REGISTRY_SCHEMA, 'principal_map')} pm
          ON pm.source_system = %s
         AND pm.source_principal_code_norm = s.principal_code
        LEFT JOIN {qtable(REGISTRY_SCHEMA, 'product_map')} prd
          ON prd.source_system = %s
         AND prd.source_principal_code_norm = s.principal_code
         AND prd.source_sku_norm = s.product_code
        """,
        (source_system, source_system, source_system),
    )


def purchase_detail_line_key_report(
    cursor,
    *,
    schema: str,
    source_system: str,
    has_baris: bool,
    sample_limit: int,
) -> dict[str, Any]:
    if not has_baris:
        return {
            "available": False,
            "reason": "Kolom baris tidak ada; duplicate line key tidak dapat dinilai tanpa membuat kunci sintetis.",
        }
    metrics = fetch_one(
        cursor,
        f"""
        WITH source_rows AS (
            SELECT
                {normalized('d', 'nota')} AS document_key,
                {normalized('d', 'baris')} AS line_key
            FROM {qtable(schema, 'dpembelian')} d
            WHERE d.source_system = %s
        ), key_groups AS (
            SELECT document_key, line_key, COUNT(*)::bigint AS row_count
            FROM source_rows
            WHERE document_key IS NOT NULL AND line_key IS NOT NULL
            GROUP BY document_key, line_key
        )
        SELECT
            (SELECT COUNT(*)::bigint FROM source_rows) AS total_rows,
            (SELECT COUNT(*)::bigint FROM source_rows WHERE document_key IS NULL)
                AS missing_document_key_rows,
            (SELECT COUNT(*)::bigint FROM source_rows
             WHERE document_key IS NOT NULL AND line_key IS NULL) AS missing_line_key_rows,
            (SELECT COUNT(*)::bigint FROM source_rows
             WHERE document_key IS NOT NULL AND line_key IS NOT NULL) AS complete_key_rows,
            (SELECT COUNT(*)::bigint FROM key_groups WHERE row_count > 1) AS duplicate_line_key_groups,
            (SELECT COALESCE(SUM(row_count - 1), 0)::bigint
             FROM key_groups WHERE row_count > 1) AS duplicate_line_key_rows_excess
        """,
        (source_system,),
    )
    duplicate_samples = fetch_all(
        cursor,
        f"""
        WITH source_rows AS (
            SELECT
                {normalized('d', 'nota')} AS document_key,
                {normalized('d', 'baris')} AS line_key
            FROM {qtable(schema, 'dpembelian')} d
            WHERE d.source_system = %s
        )
        SELECT document_key, line_key, COUNT(*)::bigint AS row_count
        FROM source_rows
        WHERE document_key IS NOT NULL AND line_key IS NOT NULL
        GROUP BY document_key, line_key
        HAVING COUNT(*) > 1
        ORDER BY row_count DESC, document_key, line_key
        LIMIT %s
        """,
        (source_system, sample_limit),
    )
    return {
        "available": True,
        "normalization": "lower(trim(nota)), lower(trim(baris)); blank is missing",
        **metrics,
        "duplicate_line_key_samples": duplicate_samples,
    }


def quantity_field_profile(
    cursor,
    *,
    schema: str,
    source_system: str,
    available_columns: set[str],
) -> dict[str, Any]:
    present_columns = [column for column in QUANTITY_COLUMNS if column in available_columns]
    missing_columns = [column for column in QUANTITY_COLUMNS if column not in available_columns]
    if not present_columns:
        total = fetch_one(
            cursor,
            f"SELECT COUNT(*)::bigint AS total_rows FROM {qtable(schema, 'dpembelian')} WHERE source_system = %s",
            (source_system,),
        )
        return {
            "policy": "raw_fields_only_no_uom_inference",
            "product_uom_map_used": False,
            "total_rows": total["total_rows"],
            "available_columns": [],
            "missing_expected_columns": missing_columns,
            "field_presence": {},
        }

    select_fields = ["COUNT(*)::bigint AS total_rows"]
    for column in present_columns:
        select_fields.append(
            f"COUNT(*) FILTER (WHERE {normalized('d', column)} IS NOT NULL)::bigint AS {ident(column + '_present_rows')}"
        )
    metrics = fetch_one(
        cursor,
        f"""
        SELECT {', '.join(select_fields)}
        FROM {qtable(schema, 'dpembelian')} d
        WHERE d.source_system = %s
        """,
        (source_system,),
    )
    total_rows = int(metrics.pop("total_rows"))
    field_presence = {
        column: {
            "nonblank_rows": int(metrics[column + "_present_rows"]),
            "blank_or_null_rows": total_rows - int(metrics[column + "_present_rows"]),
            "interpretation": "raw legacy value; semantic/UOM meaning is not inferred",
        }
        for column in present_columns
    }
    return {
        "policy": "raw_fields_only_no_uom_inference",
        "product_uom_map_used": False,
        "total_rows": total_rows,
        "available_columns": present_columns,
        "missing_expected_columns": missing_columns,
        "field_presence": field_presence,
    }


def purchase_relationship_report(
    cursor, schema: str, source_system: str, sample_limit: int
) -> dict[str, Any]:
    metrics = fetch_one(
        cursor,
        f"""
        WITH headers AS (
            SELECT {normalized('h', 'nota')} AS document_key
            FROM {qtable(schema, 'hpembelian')} h
            WHERE h.source_system = %s
        ), details AS (
            SELECT {normalized('d', 'nota')} AS document_key
            FROM {qtable(schema, 'dpembelian')} d
            WHERE d.source_system = %s
        ), header_keys AS (
            SELECT document_key, COUNT(*)::bigint AS header_rows
            FROM headers
            WHERE document_key IS NOT NULL
            GROUP BY document_key
        ), detail_keys AS (
            SELECT document_key, COUNT(*)::bigint AS detail_rows
            FROM details
            WHERE document_key IS NOT NULL
            GROUP BY document_key
        )
        SELECT
            (SELECT COUNT(*)::bigint FROM details WHERE document_key IS NULL)
                AS detail_rows_missing_document_key,
            (SELECT COALESCE(SUM(d.detail_rows), 0)::bigint
             FROM detail_keys d
             LEFT JOIN header_keys h USING (document_key)
             WHERE h.document_key IS NULL) AS detail_rows_without_header,
            (SELECT COALESCE(SUM(d.detail_rows), 0)::bigint
             FROM detail_keys d
             JOIN header_keys h USING (document_key)
             WHERE h.header_rows = 1) AS detail_rows_with_exactly_one_header,
            (SELECT COALESCE(SUM(d.detail_rows), 0)::bigint
             FROM detail_keys d
             JOIN header_keys h USING (document_key)
             WHERE h.header_rows > 1) AS detail_rows_with_duplicate_header,
            (SELECT COUNT(*)::bigint
             FROM header_keys h
             LEFT JOIN detail_keys d USING (document_key)
             WHERE d.document_key IS NULL) AS header_document_keys_without_details,
            (SELECT COALESCE(SUM(h.header_rows), 0)::bigint
             FROM header_keys h
             LEFT JOIN detail_keys d USING (document_key)
             WHERE d.document_key IS NULL) AS header_rows_without_details
        """,
        (source_system, source_system),
    )
    orphan_samples = fetch_all(
        cursor,
        f"""
        WITH header_keys AS (
            SELECT {normalized('h', 'nota')} AS document_key
            FROM {qtable(schema, 'hpembelian')} h
            WHERE h.source_system = %s
            GROUP BY {normalized('h', 'nota')}
        ), detail_keys AS (
            SELECT {normalized('d', 'nota')} AS document_key, COUNT(*)::bigint AS detail_rows
            FROM {qtable(schema, 'dpembelian')} d
            WHERE d.source_system = %s
              AND {normalized('d', 'nota')} IS NOT NULL
            GROUP BY {normalized('d', 'nota')}
        )
        SELECT d.document_key, d.detail_rows
        FROM detail_keys d
        LEFT JOIN header_keys h USING (document_key)
        WHERE h.document_key IS NULL
        ORDER BY d.detail_rows DESC, d.document_key
        LIMIT %s
        """,
        (source_system, source_system, sample_limit),
    )
    headers_without_detail_samples = fetch_all(
        cursor,
        f"""
        WITH header_keys AS (
            SELECT {normalized('h', 'nota')} AS document_key, COUNT(*)::bigint AS header_rows
            FROM {qtable(schema, 'hpembelian')} h
            WHERE h.source_system = %s
              AND {normalized('h', 'nota')} IS NOT NULL
            GROUP BY {normalized('h', 'nota')}
        ), detail_keys AS (
            SELECT {normalized('d', 'nota')} AS document_key
            FROM {qtable(schema, 'dpembelian')} d
            WHERE d.source_system = %s
            GROUP BY {normalized('d', 'nota')}
        )
        SELECT h.document_key, h.header_rows
        FROM header_keys h
        LEFT JOIN detail_keys d USING (document_key)
        WHERE d.document_key IS NULL
        ORDER BY h.header_rows DESC, h.document_key
        LIMIT %s
        """,
        (source_system, source_system, sample_limit),
    )
    return {
        **metrics,
        "orphan_detail_document_key_samples": orphan_samples,
        "header_without_detail_document_key_samples": headers_without_detail_samples,
    }


def purchase_detail_report(
    cursor,
    schema: str,
    source_system: str,
    stage_columns: set[str],
    sample_limit: int,
) -> dict[str, Any]:
    return {
        "document_keys": document_key_report(
            cursor,
            schema=schema,
            table="dpembelian",
            source_system=source_system,
            key_column="nota",
            sample_limit=sample_limit,
        ),
        "principal_product_map": detail_product_report(cursor, schema, source_system),
        "line_keys": purchase_detail_line_key_report(
            cursor,
            schema=schema,
            source_system=source_system,
            has_baris="baris" in stage_columns,
            sample_limit=sample_limit,
        ),
        "quantity_fields": quantity_field_profile(
            cursor,
            schema=schema,
            source_system=source_system,
            available_columns=stage_columns,
        ),
    }


def source_report(
    cursor,
    *,
    source_system: str,
    schema: str,
    metadata: dict[str, Any],
    stage_columns: dict[str, set[str]],
    sample_limit: int,
) -> dict[str, Any]:
    return {
        "source_system": source_system,
        "stage_schema": schema,
        "stage": metadata,
        "visits": visit_report(cursor, schema, source_system),
        "purchase": {
            "headers": purchase_header_report(cursor, schema, source_system, sample_limit),
            "details": purchase_detail_report(
                cursor,
                schema,
                source_system,
                stage_columns["dpembelian"],
                sample_limit,
            ),
            "header_detail_relationship": purchase_relationship_report(
                cursor, schema, source_system, sample_limit
            ),
        },
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    connection = pg_connect(
        args.pg_database,
        args.pg_user,
        args.pg_host or None,
        args.pg_port or None,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            cursor.execute("SET LOCAL statement_timeout = '120s'")
            validate_registry(cursor)
            bdm_metadata, bdm_columns = validate_source_schema(
                cursor, args.bdm_schema, "bdm_solo_dist"
            )
            tmp_metadata, tmp_columns = validate_source_schema(
                cursor, args.tmp_schema, "tmp_solo_dist"
            )
            paired_input = paired_stage_input_status(bdm_metadata, tmp_metadata)
            # This is only an input-consistency label.  It remains explicitly
            # separate from permission to apply any merge.
            bdm_metadata["merge_input_eligible"] = paired_input["pair_consistency_eligible"]
            tmp_metadata["merge_input_eligible"] = paired_input["pair_consistency_eligible"]
            report = {
                "report": "bdm_tmp_aug2026_visit_purchase_reconciliation",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "read_only": True,
                "registry_schema": REGISTRY_SCHEMA,
                "scope": {
                    "does_not_read_public_tables": True,
                    "does_not_write_staging_or_registry": True,
                    "uom_policy": "DPembelian unit/perunit/satuan/jumlah are reported raw; no UOM code or conversion is inferred.",
                    "merge_permission": "never granted by this reconciliation script",
                },
                "active_purchase_import_readiness": {
                    "eligible": False,
                    "status": "blocked_pending_explicit_purchase_semantics",
                    "why": (
                        "Ketersediaan mapping principal/produk tidak cukup untuk transaksi pembelian aktif. "
                        "Source DPembelian tidak membuktikan arti unit/perunit/satuan/jumlah sebagai UOM atau konversi."
                    ),
                    "required_before_any_public_purchase_or_inventory_write": list(
                        ACTIVE_PURCHASE_IMPORT_REQUIREMENTS
                    ),
                    "safe_current_path": (
                        "Kunjungan dapat diproses oleh apply_staged_visits_active_source_aware.py "
                        "setelah staging final dan dry-run bersih; pembelian tetap hold."
                    ),
                },
                "merge_input_status": (
                    "consistent_paired_stages_observed_but_manual_merge_authorization_still_required"
                    if paired_input["pair_consistency_eligible"]
                    else "non_mergeable_preview_or_unverified_consistency"
                ),
                "paired_stage_input": paired_input,
                "sources": {
                    "bdm_solo_dist": source_report(
                        cursor,
                        source_system="bdm_solo_dist",
                        schema=args.bdm_schema,
                        metadata=bdm_metadata,
                        stage_columns=bdm_columns,
                        sample_limit=args.sample_limit,
                    ),
                    "tmp_solo_dist": source_report(
                        cursor,
                        source_system="tmp_solo_dist",
                        schema=args.tmp_schema,
                        metadata=tmp_metadata,
                        stage_columns=tmp_columns,
                        sample_limit=args.sample_limit,
                    ),
                },
            }
        # Every query was inside a read-only transaction.  Roll back explicitly
        # so a later maintenance edit cannot accidentally turn this into a
        # state-changing script through an implicit commit.
        connection.rollback()
        return report
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> int:
    args = parse_args()
    try:
        validate_args(args)
        report = build_report(args)
    except (ValueError, SchemaValidationError, RuntimeError) as exc:
        print(
            json.dumps(
                {"status": "error", "read_only": True, "error": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2

    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
