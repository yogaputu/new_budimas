#!/usr/bin/env python3
"""Read-only reconciliation for staged BDM/TMP August 2026 sales and finance.

This tool reads only source-separated staging schemas and the approved
``migration_bdm_tmp_202608`` mapping registry.  In particular, it never looks
up or changes ERP ``public`` tables, and it always ends its PostgreSQL
transaction with ``ROLLBACK``.  By default the six BDM/TMP module inputs must
be different schemas.  A final staging run may instead use one combined schema
per source (BDM and TMP) only when the caller explicitly supplies
``--allow-shared-source-schema``.  That opt-in accepts exactly three matching
schema arguments per source and still validates every required table,
manifest, source provenance, target scope, and declared module.

The report covers:

* sales: HJualSM/DJualSM and HJualSMAndroid/DJualSMAndroid;
* payments: HBayarSM/DBayarSM and Pembayaran;
* returns: HReturSM/DReturSM and HReturSMAndroid/DReturSMAndroid; and
* StokOpnameAndroid.

It is deliberately a *reconciliation*, not a merge tool.  A stage marked as a
read-committed preview or an unverified consistency mode is explicitly
reported as non-mergeable.  Even a paired final snapshot or attested
write-freeze stage is only an input-quality precondition; this script never
grants permission to merge into ERP.

Quantity columns (``unit``, ``ct``, ``satuan``, ``pc``, ``perunit``, and
``jumlah``) are reported only as raw legacy fields.  This tool does not query
``product_uom_map``, select an UOM, or calculate CT/PCS conversion.

Example (run on the PostgreSQL host with a read-only account):

    python3 tools/migration/reconcile_sales_finance_staging.py \
      --bdm-sales-schema legacy_bdm_solo_sales_preview_20260827 \
      --tmp-sales-schema legacy_tmp_solo_sales_preview_20260827 \
      --bdm-payment-return-schema legacy_bdm_solo_payment_return_preview_20260827 \
      --tmp-payment-return-schema legacy_tmp_solo_payment_return_preview_20260827 \
      --bdm-stock-opname-schema legacy_bdm_solo_stock_opname_preview_20260827 \
      --tmp-stock-opname-schema legacy_tmp_solo_stock_opname_preview_20260827 \
      --output /tmp/bdm-tmp-sales-finance-reconciliation.json

For one combined final staging schema per source, use the same schema for all
three module arguments of that source and opt in explicitly:

    python3 tools/migration/reconcile_sales_finance_staging.py \
      --allow-shared-source-schema \
      --bdm-sales-schema legacy_bdm_solo_final_freeze_20260830 \
      --bdm-payment-return-schema legacy_bdm_solo_final_freeze_20260830 \
      --bdm-stock-opname-schema legacy_bdm_solo_final_freeze_20260830 \
      --tmp-sales-schema legacy_tmp_solo_final_freeze_20260830 \
      --tmp-payment-return-schema legacy_tmp_solo_final_freeze_20260830 \
      --tmp-stock-opname-schema legacy_tmp_solo_final_freeze_20260830
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Sequence


REGISTRY_SCHEMA = "migration_bdm_tmp_202608"
IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
EXPECTED_MONTH_START = datetime(2026, 8, 1)
EXPECTED_MONTH_END = datetime(2026, 9, 1)
REQUIRED_RECONCILIATION_MODULES = frozenset({"sales", "payments", "returns", "stock-opname"})
FINAL_TRANSACTION_CONSISTENCY_MODES = frozenset({"snapshot", "maintenance_freeze_serializable"})
FREEZE_METADATA_COLUMNS = frozenset(
    {
        "maintenance_window_id",
        "maintenance_freeze_attested",
        "maintenance_freeze_confirmed_at",
        "source_transaction_isolation",
    }
)


@dataclass(frozen=True)
class StageTable:
    """One staging table and the source fields needed for this audit."""

    table: str
    legacy_table: str
    module: str
    required_columns: frozenset[str]


@dataclass(frozen=True)
class MappingSpec:
    """An approved registry map and the source fields that form its key."""

    name: str
    registry_table: str
    registry_key_columns: tuple[str, ...]
    source_columns: tuple[str, ...]
    target_id_column: str


# The names below are the deterministic lowercase names created by
# stage_august_2026_source.py.  Requiring them avoids silently treating an
# unrelated legacy table as a sales/finance source.
STAGE_TABLES: dict[str, StageTable] = {
    "hjualsm": StageTable(
        "hjualsm",
        "HJualSM",
        "sales",
        frozenset({"staging_id", "source_system", "source_row_hash", "nota", "kodecustomer", "kodeprinciple", "kodesales"}),
    ),
    "djualsm": StageTable(
        "djualsm",
        "DJualSM",
        "sales",
        frozenset({"staging_id", "source_system", "source_row_hash", "nota", "kodestok", "kodecustomer", "kodeprinciple", "kodesales"}),
    ),
    "hjualsmandroid": StageTable(
        "hjualsmandroid",
        "HJualSMAndroid",
        "sales",
        frozenset({"staging_id", "source_system", "source_row_hash", "nota", "kodecustomer", "kodeprinciple", "kodesales"}),
    ),
    "djualsmandroid": StageTable(
        "djualsmandroid",
        "DJualSMAndroid",
        "sales",
        frozenset({"staging_id", "source_system", "source_row_hash", "nota", "kodestok", "kodecustomer", "kodeprinciple", "kodesales"}),
    ),
    "hbayarsm": StageTable(
        "hbayarsm",
        "HBayarSM",
        "payments",
        frozenset({"staging_id", "source_system", "source_row_hash", "nokwitansi", "kodecustomer"}),
    ),
    "dbayarsm": StageTable(
        "dbayarsm",
        "DBayarSM",
        "payments",
        frozenset({"staging_id", "source_system", "source_row_hash", "nokwitansi", "nota", "kodecustomer"}),
    ),
    "pembayaran": StageTable(
        "pembayaran",
        "Pembayaran",
        "payments",
        frozenset({"staging_id", "source_system", "source_row_hash", "nokwitansi", "nota", "kodecustomer", "kodesales"}),
    ),
    "hretursm": StageTable(
        "hretursm",
        "HReturSM",
        "returns",
        frozenset({"staging_id", "source_system", "source_row_hash", "nota", "kodecustomer", "kodeprinciple", "kodesales", "notasm"}),
    ),
    "dretursm": StageTable(
        "dretursm",
        "DReturSM",
        "returns",
        frozenset({"staging_id", "source_system", "source_row_hash", "nota", "kodestok", "kodecustomer", "kodeprinciple", "kodesales"}),
    ),
    "hretursmandroid": StageTable(
        "hretursmandroid",
        "HReturSMAndroid",
        "returns",
        frozenset({"staging_id", "source_system", "source_row_hash", "nota", "kodecustomer", "kodeprinciple", "kodesales", "notasm"}),
    ),
    "dretursmandroid": StageTable(
        "dretursmandroid",
        "DReturSMAndroid",
        "returns",
        frozenset({"staging_id", "source_system", "source_row_hash", "nota", "kodestok", "kodecustomer", "kodeprinciple", "kodesales"}),
    ),
    "stokopnameandroid": StageTable(
        "stokopnameandroid",
        "StokOpnameAndroid",
        "stock-opname",
        frozenset({"staging_id", "source_system", "source_row_hash", "id", "kodebarang", "kodecustomer", "kodeprinciple", "kodesales"}),
    ),
}

SALES_STAGE_TABLE_NAMES = ("hjualsm", "djualsm", "hjualsmandroid", "djualsmandroid")
PAYMENT_RETURN_STAGE_TABLE_NAMES = (
    "hbayarsm",
    "dbayarsm",
    "pembayaran",
    "hretursm",
    "dretursm",
    "hretursmandroid",
    "dretursmandroid",
)
STOCK_OPNAME_STAGE_TABLE_NAMES = ("stokopnameandroid",)

CUSTOMER_MAP = MappingSpec(
    "customer_map",
    "customer_map",
    ("source_customer_code_norm",),
    ("kodecustomer",),
    "id_customer",
)
PRINCIPAL_MAP = MappingSpec(
    "principal_map",
    "principal_map",
    ("source_principal_code_norm",),
    ("kodeprinciple",),
    "id_principal",
)
SALES_MAP = MappingSpec(
    "sales_map",
    "sales_map",
    ("source_principal_code_norm", "source_sales_code_norm"),
    ("kodeprinciple", "kodesales"),
    "id_sales",
)
PRODUCT_STOCK_MAP = MappingSpec(
    "product_map",
    "product_map",
    ("source_principal_code_norm", "source_sku_norm"),
    ("kodeprinciple", "kodestok"),
    "id_produk",
)
PRODUCT_BARANG_MAP = MappingSpec(
    "product_map",
    "product_map",
    ("source_principal_code_norm", "source_sku_norm"),
    ("kodeprinciple", "kodebarang"),
    "id_produk",
)

SALES_HEADER_MAPPINGS = (CUSTOMER_MAP, PRINCIPAL_MAP, SALES_MAP)
SALES_DETAIL_MAPPINGS = (*SALES_HEADER_MAPPINGS, PRODUCT_STOCK_MAP)
PAYMENT_MAPPINGS = (CUSTOMER_MAP,)
RETURN_HEADER_MAPPINGS = SALES_HEADER_MAPPINGS
RETURN_DETAIL_MAPPINGS = SALES_DETAIL_MAPPINGS
STOCK_OPNAME_MAPPINGS = (CUSTOMER_MAP, PRINCIPAL_MAP, SALES_MAP, PRODUCT_BARANG_MAP)

RAW_QTY_FIELDS = ("unit", "ct", "satuan", "pc", "perunit", "jumlah")

REGISTRY_REQUIREMENTS: dict[str, frozenset[str]] = {
    "source_context": frozenset({"source_system", "target_company_id", "target_branch_id"}),
    "customer_map": frozenset({"source_system", "source_customer_code_norm", "id_customer"}),
    "principal_map": frozenset({"source_system", "source_principal_code_norm", "id_principal"}),
    "sales_map": frozenset(
        {"source_system", "source_principal_code_norm", "source_sales_code_norm", "id_sales"}
    ),
    "product_map": frozenset(
        {"source_system", "source_principal_code_norm", "source_sku_norm", "id_produk"}
    ),
    "sales_document_map": frozenset(
        {
            "source_system",
            "source_table",
            "source_nota_norm",
            "stage_schema",
            "source_staging_id",
            "source_row_hash",
            "id_sales_order",
        }
    ),
    "sales_document_line_map": frozenset(
        {
            "source_system",
            "source_table",
            "source_nota_norm",
            "source_urut_norm",
            "source_staging_id",
            "source_row_hash",
            "id_sales_order_detail",
        }
    ),
}


class SchemaValidationError(RuntimeError):
    """Raised before report generation when stage input is unsafe to interpret."""


def ident(value: str) -> str:
    """Safely quote a deliberately narrow PostgreSQL identifier."""

    if not IDENT_RE.fullmatch(value):
        raise ValueError(f"Identifier PostgreSQL tidak aman: {value!r}")
    return f'"{value}"'


def qtable(schema: str, table: str) -> str:
    return f"{ident(schema)}.{ident(table)}"


def normalized(alias: str, column: str) -> str:
    """Registry-compatible lower/trimmed key; blank values become NULL."""

    return f"NULLIF(lower(btrim({alias}.{ident(column)})), '')"


def json_value(value: Any) -> Any:
    """Make database scalars deterministic and JSON serialisable."""

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
    except ImportError as exc:  # pragma: no cover - depends on runner image
        raise RuntimeError("Modul psycopg2 diperlukan untuk laporan PostgreSQL.") from exc

    kwargs: dict[str, Any] = {"dbname": database, "user": user}
    if host:
        kwargs["host"] = host
    if port:
        kwargs["port"] = port
    connection = psycopg2.connect(**kwargs)
    # Read-only is set before the first statement.  build_report also starts an
    # explicit read-only transaction so a future edit cannot accidentally make
    # this a write-capable reconciliation script.
    connection.set_session(readonly=True, autocommit=False)
    return connection


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bdm-sales-schema", required=True, help="Schema staging BDM Solo untuk modul sales.")
    parser.add_argument("--tmp-sales-schema", required=True, help="Schema staging TMP Solo untuk modul sales.")
    parser.add_argument(
        "--bdm-payment-return-schema",
        required=True,
        help="Schema staging BDM Solo untuk modul payments dan returns.",
    )
    parser.add_argument(
        "--tmp-payment-return-schema",
        required=True,
        help="Schema staging TMP Solo untuk modul payments dan returns.",
    )
    parser.add_argument(
        "--bdm-stock-opname-schema",
        required=True,
        help="Schema staging BDM Solo untuk modul stock-opname.",
    )
    parser.add_argument(
        "--tmp-stock-opname-schema",
        required=True,
        help="Schema staging TMP Solo untuk modul stock-opname.",
    )
    parser.add_argument(
        "--allow-shared-source-schema",
        action="store_true",
        help=(
            "Opt-in eksplisit untuk satu schema staging gabungan per sumber. "
            "Saat aktif, tiga schema BDM harus sama persis, tiga schema TMP harus sama persis, "
            "dan schema BDM/TMP tetap harus berbeda."
        ),
    )
    parser.add_argument(
        "--pg-database",
        default=os.getenv("MIGRATION_PG_DATABASE", "budimas_dev"),
        help="Nama PostgreSQL (default: MIGRATION_PG_DATABASE atau budimas_dev).",
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
        help="Port PostgreSQL; 0 berarti default driver.",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=20,
        help="Maksimal contoh key untuk tiap isu (default: 20; maksimum: 200).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Opsional: tulis JSON lokal ke file ini, selain stdout.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    bdm_schema_args = (
        args.bdm_sales_schema,
        args.bdm_payment_return_schema,
        args.bdm_stock_opname_schema,
    )
    tmp_schema_args = (
        args.tmp_sales_schema,
        args.tmp_payment_return_schema,
        args.tmp_stock_opname_schema,
    )
    schema_args = (*bdm_schema_args, *tmp_schema_args)
    for schema in schema_args:
        ident(schema)
        if not schema.startswith("legacy_"):
            raise ValueError("Semua schema staging harus diawali legacy_.")
    if args.allow_shared_source_schema:
        if len(set(bdm_schema_args)) != 1 or len(set(tmp_schema_args)) != 1:
            raise ValueError(
                "Dengan --allow-shared-source-schema, tiga schema BDM harus sama persis "
                "dan tiga schema TMP harus sama persis."
            )
        if bdm_schema_args[0] == tmp_schema_args[0]:
            raise ValueError(
                "Schema gabungan BDM dan TMP harus berbeda agar provenance sumber tidak tercampur."
            )
    elif len(set(schema_args)) != len(schema_args):
        raise ValueError(
            "Keenam schema staging harus berbeda agar modul tidak salah dirutekan. "
            "Gunakan --allow-shared-source-schema hanya untuk satu schema gabungan per sumber."
        )
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


def require_columns(cursor, schema: str, table: str, required: frozenset[str]) -> set[str]:
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
    required = frozenset(
        {
            "id",
            "source_system",
            "source_server",
            "source_database",
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
        }
    )
    stage_run_columns = require_columns(cursor, schema, "__stage_run", required)
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
        SELECT source_system, source_server, source_database, target_company_id, target_branch_id,
               window_start, window_end_exclusive, consistency_mode, is_preview,
               modules, status, created_at, completed_at,
               {freeze_projection}
        FROM {qtable(schema, '__stage_run')}
        ORDER BY id DESC
        LIMIT 1
        """,
    )
    if not row:
        raise SchemaValidationError(f"{schema} tidak mempunyai metadata __stage_run.")
    if row["source_system"] != expected_source:
        raise SchemaValidationError(
            f"{schema} memiliki source_system {row['source_system']!r}; "
            f"seharusnya {expected_source!r}."
        )
    if row["status"] not in {"completed", "completed_preview"}:
        raise SchemaValidationError(
            f"{schema} berstatus {row['status']!r}; hanya staging selesai yang boleh direkonsiliasi."
        )
    raw_modules = str(row["modules"] or "")
    declared_modules = frozenset(
        module.strip() for module in raw_modules.split(",") if module.strip()
    )
    if not declared_modules:
        raise SchemaValidationError(f"{schema}: metadata modules kosong atau tidak valid.")
    row["declared_modules"] = sorted(declared_modules)
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
        raise SchemaValidationError(f"Registry source_context tidak ada untuk {expected_source}.")
    if (
        int(row["target_company_id"]) != int(context["target_company_id"])
        or int(row["target_branch_id"]) != int(context["target_branch_id"])
    ):
        raise SchemaValidationError(
            f"Scope {schema} ({row['target_company_id']}/{row['target_branch_id']}) tidak cocok "
            f"dengan registry {expected_source} ({context['target_company_id']}/{context['target_branch_id']})."
        )
    try:
        window_start = datetime.fromisoformat(str(row["window_start"]))
        window_end = datetime.fromisoformat(str(row["window_end_exclusive"]))
    except ValueError as exc:
        raise SchemaValidationError(f"{schema}: window staging tidak valid.") from exc
    if window_start >= window_end:
        raise SchemaValidationError(f"{schema}: window staging kosong atau terbalik.")
    # The command is scoped to the August 2026 staging set, rather than quietly
    # accepting a similarly named schema from a different period.
    if window_start.replace(tzinfo=None) < EXPECTED_MONTH_START or window_end.replace(tzinfo=None) > EXPECTED_MONTH_END:
        raise SchemaValidationError(
            f"{schema}: window {row['window_start']} s.d. {row['window_end_exclusive']} bukan subset Agustus 2026."
        )
    preview = bool(row["is_preview"]) or row["status"] != "completed"
    consistency_eligible = (
        not preview and consistency_mode in FINAL_TRANSACTION_CONSISTENCY_MODES
    )
    row["stage_consistency_eligible"] = consistency_eligible
    row["merge_input_status"] = (
        "non_mergeable_preview"
        if preview
        else (
            "consistent_stage_only_reconciliation_never_authorizes_merge"
            if consistency_eligible
            else "non_mergeable_unrecognized_consistency_mode"
        )
    )
    return row


def validate_declared_modules(
    schema: str,
    metadata: dict[str, Any],
    table_names: Sequence[str],
) -> None:
    """Require stage-run metadata to explicitly cover every audited table module."""

    expected_modules = frozenset(STAGE_TABLES[name].module for name in table_names)
    declared_modules = frozenset(str(module) for module in metadata["declared_modules"])
    missing_modules = sorted(expected_modules - declared_modules)
    if missing_modules:
        raise SchemaValidationError(
            f"{schema}: metadata modules tidak mencakup modul wajib untuk tabel yang diaudit: "
            f"{', '.join(missing_modules)}."
        )


def validate_manifest(cursor, schema: str, spec: StageTable) -> None:
    require_columns(
        cursor,
        schema,
        "__stage_manifest",
        frozenset({"legacy_table", "module", "source_row_count", "staged_row_count", "status"}),
    )
    manifest = fetch_one(
        cursor,
        f"""
        SELECT legacy_table, module, source_row_count, staged_row_count, status
        FROM {qtable(schema, '__stage_manifest')}
        WHERE lower(legacy_table) = lower(%s)
        """,
        (spec.legacy_table,),
    )
    if not manifest:
        raise SchemaValidationError(f"{schema}: manifest {spec.legacy_table} tidak ditemukan.")
    if manifest["status"] != "done":
        raise SchemaValidationError(
            f"{schema}: manifest {spec.legacy_table} berstatus {manifest['status']!r}, bukan done."
        )
    if manifest["module"] != spec.module:
        raise SchemaValidationError(
            f"{schema}: manifest {spec.legacy_table} ada pada modul {manifest['module']!r}, "
            f"bukan {spec.module!r}."
        )
    if (
        manifest["source_row_count"] is None
        or manifest["staged_row_count"] is None
        or int(manifest["source_row_count"]) != int(manifest["staged_row_count"])
    ):
        raise SchemaValidationError(
            f"{schema}: count source/staging {spec.legacy_table} tidak sama "
            f"({manifest['source_row_count']} vs {manifest['staged_row_count']})."
        )


def validate_stage_table(
    cursor, schema: str, spec: StageTable, expected_source: str, metadata: dict[str, Any]
) -> set[str]:
    columns = require_columns(cursor, schema, spec.table, spec.required_columns)
    validate_manifest(cursor, schema, spec)
    scope = fetch_one(
        cursor,
        f"""
        SELECT
            COUNT(*)::bigint AS total_rows,
            COUNT(*) FILTER (WHERE source_system <> %s)::bigint AS wrong_source_rows,
            COUNT(*) FILTER (
                WHERE target_company_id <> %s OR target_branch_id <> %s
            )::bigint AS wrong_scope_rows,
            COUNT(*) FILTER (WHERE lower(legacy_table) <> lower(%s))::bigint AS wrong_legacy_table_rows
        FROM {qtable(schema, spec.table)}
        """,
        (
            expected_source,
            int(metadata["target_company_id"]),
            int(metadata["target_branch_id"]),
            spec.legacy_table,
        ),
    )
    failures = {
        key: int(scope[key])
        for key in ("wrong_source_rows", "wrong_scope_rows", "wrong_legacy_table_rows")
        if int(scope[key]) > 0
    }
    if failures:
        raise SchemaValidationError(f"{schema}.{spec.table} memiliki scope/asal tidak konsisten: {failures!r}")
    return columns


def validate_source_schema(
    cursor, schema: str, expected_source: str, table_names: Sequence[str]
) -> tuple[dict[str, Any], dict[str, set[str]]]:
    """Validate a module-specific schema or an explicitly opted-in combined schema."""

    metadata = stage_metadata(cursor, schema, expected_source)
    validate_declared_modules(schema, metadata, table_names)
    columns = {
        name: validate_stage_table(cursor, schema, STAGE_TABLES[name], expected_source, metadata)
        for name in table_names
    }
    return metadata, columns


def validate_source_stage_alignment(
    *, source_system: str, stage_metadata_by_module: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Require the three independently staged modules to be the same source/window/scope."""

    required_modules = ("sales", "payment_return", "stock_opname")
    missing = [module for module in required_modules if module not in stage_metadata_by_module]
    if missing:
        raise SchemaValidationError(
            f"{source_system}: metadata modul tidak lengkap: {', '.join(missing)}."
        )
    baseline_name = required_modules[0]
    baseline = stage_metadata_by_module[baseline_name]
    alignment_fields = (
        "source_system",
        "source_server",
        "source_database",
        "target_company_id",
        "target_branch_id",
        "window_start",
        "window_end_exclusive",
        "consistency_mode",
        "is_preview",
        "stage_consistency_eligible",
        "maintenance_window_id",
        "maintenance_freeze_attested",
        "maintenance_freeze_confirmed_at",
        "source_transaction_isolation",
    )
    mismatches: dict[str, dict[str, Any]] = {}
    for module in required_modules[1:]:
        current = stage_metadata_by_module[module]
        differences = {
            field: {baseline_name: baseline[field], module: current[field]}
            for field in alignment_fields
            if current[field] != baseline[field]
        }
        if differences:
            mismatches[module] = differences
    if mismatches:
        raise SchemaValidationError(
            f"{source_system}: schema sales/payment-return/stock-opname tidak berasal dari source, periode, atau scope yang sama: {mismatches!r}"
        )
    return {
        "validated_modules": list(required_modules),
        "same_source_system": True,
        "same_source_server": True,
        "same_source_database": True,
        "same_target_scope": True,
        "same_window": True,
        "same_consistency_attestation": True,
        "source_system": baseline["source_system"],
        "source_server": baseline["source_server"],
        "source_database": baseline["source_database"],
        "target_company_id": baseline["target_company_id"],
        "target_branch_id": baseline["target_branch_id"],
        "window_start": baseline["window_start"],
        "window_end_exclusive": baseline["window_end_exclusive"],
        "consistency_mode": baseline["consistency_mode"],
        "stage_consistency_eligible": baseline["stage_consistency_eligible"],
        "maintenance_window_id": baseline["maintenance_window_id"],
    }


def validate_combined_schema_metadata(
    *, source_system: str, schema: str, stage_metadata_by_module: dict[str, dict[str, Any]]
) -> None:
    """Require an opted-in combined schema to declare every audited module."""

    baseline = stage_metadata_by_module["sales"]
    declared_modules = frozenset(str(module) for module in baseline["declared_modules"])
    missing_modules = sorted(REQUIRED_RECONCILIATION_MODULES - declared_modules)
    if missing_modules:
        raise SchemaValidationError(
            f"{source_system}: schema gabungan {schema} tidak mendeklarasikan modul wajib: "
            f"{', '.join(missing_modules)}."
        )


def paired_stage_input_status(
    *,
    bdm_metadata_by_module: dict[str, dict[str, Any]],
    tmp_metadata_by_module: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate final-input consistency without ever granting merge permission."""

    bdm = bdm_metadata_by_module["sales"]
    tmp = tmp_metadata_by_module["sales"]
    reasons: list[str] = []
    if not bdm["stage_consistency_eligible"] or not tmp["stage_consistency_eligible"]:
        reasons.append("salah_satu_stage_bukan_snapshot_atau_write_freeze_terattestasi")
    if bdm["consistency_mode"] != tmp["consistency_mode"]:
        reasons.append("consistency_mode_bdm_tmp_berbeda")
    if (
        bdm["window_start"] != tmp["window_start"]
        or bdm["window_end_exclusive"] != tmp["window_end_exclusive"]
    ):
        reasons.append("window_bdm_tmp_berbeda")
    if (
        bdm["consistency_mode"] == "maintenance_freeze_serializable"
        and tmp["consistency_mode"] == "maintenance_freeze_serializable"
        and bdm["maintenance_window_id"] != tmp["maintenance_window_id"]
    ):
        reasons.append("maintenance_window_id_bdm_tmp_berbeda")
    eligible = not reasons
    return {
        "pair_consistency_eligible": eligible,
        "consistency_mode": {
            "bdm_solo_dist": bdm["consistency_mode"],
            "tmp_solo_dist": tmp["consistency_mode"],
        },
        "window_start": {
            "bdm_solo_dist": bdm["window_start"],
            "tmp_solo_dist": tmp["window_start"],
        },
        "window_end_exclusive": {
            "bdm_solo_dist": bdm["window_end_exclusive"],
            "tmp_solo_dist": tmp["window_end_exclusive"],
        },
        "maintenance_window_id": {
            "bdm_solo_dist": bdm["maintenance_window_id"],
            "tmp_solo_dist": tmp["maintenance_window_id"],
        },
        "reasons_not_eligible": reasons,
        "merge_permission": "never granted by this reconciliation script",
    }


def map_coverage(
    cursor,
    *,
    schema: str,
    table: str,
    source_system: str,
    mapping: MappingSpec,
) -> dict[str, Any]:
    """Coverage for one approved registry mapping, with no public-table lookup."""

    source_select = ", ".join(
        f"{normalized('s', column)} AS key_{index}"
        for index, column in enumerate(mapping.source_columns)
    )
    key_complete = " AND ".join(f"s.key_{index} IS NOT NULL" for index in range(len(mapping.source_columns)))
    joins = " AND ".join(
        f"m.{ident(registry_column)} = s.key_{index}"
        for index, registry_column in enumerate(mapping.registry_key_columns)
    )
    return {
        "mapping_key": {
            "source_columns": list(mapping.source_columns),
            "normalization": "lower(trim(value)); blank is treated as missing",
        },
        **fetch_one(
            cursor,
            f"""
            WITH source_rows AS (
                SELECT {source_select}
                FROM {qtable(schema, table)} s
                WHERE s.source_system = %s
            )
            SELECT
                COUNT(*)::bigint AS total_rows,
                COUNT(*) FILTER (WHERE {key_complete})::bigint AS source_key_complete_rows,
                COUNT(*) FILTER (WHERE NOT ({key_complete}))::bigint AS source_key_incomplete_rows,
                COUNT(*) FILTER (
                    WHERE {key_complete} AND m.{ident(mapping.target_id_column)} IS NOT NULL
                )::bigint AS mapped_rows,
                COUNT(*) FILTER (
                    WHERE {key_complete} AND m.{ident(mapping.target_id_column)} IS NULL
                )::bigint AS unmapped_rows
            FROM source_rows s
            LEFT JOIN {qtable(REGISTRY_SCHEMA, mapping.registry_table)} m
              ON m.source_system = %s
             AND {joins}
            """,
            (source_system, source_system),
        ),
    }


def combined_mapping_coverage(
    cursor,
    *,
    schema: str,
    table: str,
    source_system: str,
    mappings: Sequence[MappingSpec],
) -> dict[str, Any]:
    """Count rows that satisfy every relevant approved mapping precondition."""

    unique_columns: list[str] = []
    for mapping in mappings:
        for column in mapping.source_columns:
            if column not in unique_columns:
                unique_columns.append(column)
    source_select = ", ".join(
        f"{normalized('s', column)} AS {ident('key_' + column)}" for column in unique_columns
    )
    joins: list[str] = []
    map_present: list[str] = []
    map_key_complete: list[str] = []
    params: list[Any] = [source_system]
    for index, mapping in enumerate(mappings):
        alias = f"m{index}"
        key_complete = " AND ".join(
            f"s.{ident('key_' + source_column)} IS NOT NULL"
            for source_column in mapping.source_columns
        )
        map_key_complete.append(f"({key_complete})")
        key_matches = " AND ".join(
            f"{alias}.{ident(registry_column)} = s.{ident('key_' + source_column)}"
            for registry_column, source_column in zip(mapping.registry_key_columns, mapping.source_columns)
        )
        joins.append(
            f"LEFT JOIN {qtable(REGISTRY_SCHEMA, mapping.registry_table)} {alias} "
            f"ON {alias}.source_system = %s AND {key_matches}"
        )
        params.append(source_system)
        map_present.append(f"{alias}.{ident(mapping.target_id_column)} IS NOT NULL")
    all_keys_complete = " AND ".join(map_key_complete)
    all_maps_present = " AND ".join(map_present)
    return {
        "policy": "all listed registry maps must exist; no target ERP table is queried",
        "required_maps": [mapping.name for mapping in mappings],
        **fetch_one(
            cursor,
            f"""
            WITH source_rows AS (
                SELECT {source_select}
                FROM {qtable(schema, table)} s
                WHERE s.source_system = %s
            )
            SELECT
                COUNT(*)::bigint AS total_rows,
                COUNT(*) FILTER (WHERE {all_keys_complete})::bigint AS all_source_keys_complete_rows,
                COUNT(*) FILTER (WHERE NOT ({all_keys_complete}))::bigint AS source_key_incomplete_rows,
                COUNT(*) FILTER (
                    WHERE {all_keys_complete} AND {all_maps_present}
                )::bigint AS fully_mapped_rows,
                COUNT(*) FILTER (
                    WHERE NOT ({all_keys_complete}) OR NOT ({all_maps_present})
                )::bigint AS held_rows
            FROM source_rows s
            {' '.join(joins)}
            """,
            params,
        ),
    }


def mapping_report(
    cursor,
    *,
    schema: str,
    table: str,
    source_system: str,
    mappings: Sequence[MappingSpec],
) -> dict[str, Any]:
    return {
        "policy": "approved mapping registry only; no ERP public-table lookup",
        "maps": {
            mapping.name: map_coverage(
                cursor,
                schema=schema,
                table=table,
                source_system=source_system,
                mapping=mapping,
            )
            for mapping in mappings
        },
        "combined": combined_mapping_coverage(
            cursor,
            schema=schema,
            table=table,
            source_system=source_system,
            mappings=mappings,
        ),
    }


def raw_field_profile(
    cursor,
    *,
    schema: str,
    table: str,
    source_system: str,
    available_columns: set[str],
    fields: Sequence[str],
    policy: str,
) -> dict[str, Any]:
    """Report field presence, never interpret or convert its legacy value."""

    present = [field for field in fields if field in available_columns]
    missing = [field for field in fields if field not in available_columns]
    total = fetch_one(
        cursor,
        f"SELECT COUNT(*)::bigint AS total_rows FROM {qtable(schema, table)} WHERE source_system = %s",
        (source_system,),
    )
    total_rows = int(total["total_rows"])
    if not present:
        return {
            "policy": policy,
            "total_rows": total_rows,
            "available_fields": [],
            "missing_expected_fields": missing,
            "field_presence": {},
        }
    select_fields = ["COUNT(*)::bigint AS total_rows"]
    for field in present:
        expression = normalized("s", field)
        select_fields.extend(
            [
                f"COUNT(*) FILTER (WHERE {expression} IS NOT NULL)::bigint AS {ident(field + '_present')}",
                f"COUNT(*) FILTER (WHERE {expression} ~ '^[+-]?([0-9]+([.][0-9]+)?|[.][0-9]+)$')::bigint AS {ident(field + '_numeric_literal')}",
            ]
        )
    metrics = fetch_one(
        cursor,
        f"""
        SELECT {', '.join(select_fields)}
        FROM {qtable(schema, table)} s
        WHERE s.source_system = %s
        """,
        (source_system,),
    )
    return {
        "policy": policy,
        "total_rows": total_rows,
        "available_fields": present,
        "missing_expected_fields": missing,
        "field_presence": {
            field: {
                "nonblank_rows": int(metrics[field + "_present"]),
                "blank_or_null_rows": total_rows - int(metrics[field + "_present"]),
                "numeric_literal_rows": int(metrics[field + "_numeric_literal"]),
                "non_numeric_nonblank_rows": int(metrics[field + "_present"])
                - int(metrics[field + "_numeric_literal"]),
                "interpretation": "raw legacy text only",
            }
            for field in present
        },
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
    key_expression = normalized("s", key_column)
    metrics = fetch_one(
        cursor,
        f"""
        WITH source_rows AS (
            SELECT staging_id, {key_expression} AS document_key
            FROM {qtable(schema, table)} s
            WHERE s.source_system = %s
        ), grouped AS (
            SELECT document_key, COUNT(*)::bigint AS row_count
            FROM source_rows
            WHERE document_key IS NOT NULL
            GROUP BY document_key
        )
        SELECT
            (SELECT COUNT(*)::bigint FROM source_rows) AS total_rows,
            (SELECT COUNT(*)::bigint FROM source_rows WHERE document_key IS NULL) AS missing_key_rows,
            (SELECT COUNT(*)::bigint FROM source_rows WHERE document_key IS NOT NULL) AS keyed_rows,
            (SELECT COUNT(*)::bigint FROM grouped) AS distinct_keys,
            (SELECT COUNT(*)::bigint FROM grouped WHERE row_count > 1) AS duplicate_key_groups,
            (SELECT COALESCE(SUM(row_count - 1), 0)::bigint FROM grouped WHERE row_count > 1)
                AS duplicate_key_rows_excess
        """,
        (source_system,),
    )
    duplicate_samples = fetch_all(
        cursor,
        f"""
        WITH source_rows AS (
            SELECT {key_expression} AS document_key
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
        WHERE s.source_system = %s AND {key_expression} IS NULL
        ORDER BY staging_id
        LIMIT %s
        """,
        (source_system, sample_limit),
    )
    return {
        "key_column": key_column,
        "normalization": "lower(trim(key)); blank is treated as missing",
        **metrics,
        "duplicate_key_samples": duplicate_samples,
        "missing_key_staging_id_samples": missing_samples,
    }


def line_key_report(
    cursor,
    *,
    schema: str,
    table: str,
    source_system: str,
    available_columns: set[str],
    document_column: str,
    line_column: str,
    sample_limit: int,
) -> dict[str, Any]:
    if line_column not in available_columns:
        return {
            "available": False,
            "reason": f"Kolom {line_column} tidak ada; tidak membuat line key sintetis.",
        }
    document_expression = normalized("s", document_column)
    line_expression = normalized("s", line_column)
    metrics = fetch_one(
        cursor,
        f"""
        WITH source_rows AS (
            SELECT {document_expression} AS document_key, {line_expression} AS line_key
            FROM {qtable(schema, table)} s
            WHERE s.source_system = %s
        ), grouped AS (
            SELECT document_key, line_key, COUNT(*)::bigint AS row_count
            FROM source_rows
            WHERE document_key IS NOT NULL AND line_key IS NOT NULL
            GROUP BY document_key, line_key
        )
        SELECT
            (SELECT COUNT(*)::bigint FROM source_rows) AS total_rows,
            (SELECT COUNT(*)::bigint FROM source_rows WHERE document_key IS NULL) AS missing_document_key_rows,
            (SELECT COUNT(*)::bigint FROM source_rows WHERE document_key IS NOT NULL AND line_key IS NULL)
                AS missing_line_key_rows,
            (SELECT COUNT(*)::bigint FROM source_rows WHERE document_key IS NOT NULL AND line_key IS NOT NULL)
                AS complete_key_rows,
            (SELECT COUNT(*)::bigint FROM grouped WHERE row_count > 1) AS duplicate_line_key_groups,
            (SELECT COALESCE(SUM(row_count - 1), 0)::bigint FROM grouped WHERE row_count > 1)
                AS duplicate_line_key_rows_excess
        """,
        (source_system,),
    )
    samples = fetch_all(
        cursor,
        f"""
        WITH source_rows AS (
            SELECT {document_expression} AS document_key, {line_expression} AS line_key
            FROM {qtable(schema, table)} s
            WHERE s.source_system = %s
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
        "normalization": "lower(trim(document)), lower(trim(line)); blank is missing",
        **metrics,
        "duplicate_line_key_samples": samples,
    }


def header_detail_relationship(
    cursor,
    *,
    schema: str,
    source_system: str,
    header_table: str,
    detail_table: str,
    header_key: str,
    detail_key: str,
    sample_limit: int,
) -> dict[str, Any]:
    """Relationship quality for source header/detail tables by their raw key."""

    header_expression = normalized("h", header_key)
    detail_expression = normalized("d", detail_key)
    metrics = fetch_one(
        cursor,
        f"""
        WITH headers AS (
            SELECT {header_expression} AS document_key
            FROM {qtable(schema, header_table)} h
            WHERE h.source_system = %s
        ), details AS (
            SELECT {detail_expression} AS document_key
            FROM {qtable(schema, detail_table)} d
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
            (SELECT COUNT(*)::bigint FROM details WHERE document_key IS NULL) AS detail_rows_missing_document_key,
            (SELECT COALESCE(SUM(d.detail_rows), 0)::bigint
             FROM detail_keys d LEFT JOIN header_keys h USING (document_key)
             WHERE h.document_key IS NULL) AS detail_rows_without_header,
            (SELECT COALESCE(SUM(d.detail_rows), 0)::bigint
             FROM detail_keys d JOIN header_keys h USING (document_key)
             WHERE h.header_rows = 1) AS detail_rows_with_exactly_one_header,
            (SELECT COALESCE(SUM(d.detail_rows), 0)::bigint
             FROM detail_keys d JOIN header_keys h USING (document_key)
             WHERE h.header_rows > 1) AS detail_rows_with_duplicate_header,
            (SELECT COUNT(*)::bigint
             FROM header_keys h LEFT JOIN detail_keys d USING (document_key)
             WHERE d.document_key IS NULL) AS header_document_keys_without_details,
            (SELECT COALESCE(SUM(h.header_rows), 0)::bigint
             FROM header_keys h LEFT JOIN detail_keys d USING (document_key)
             WHERE d.document_key IS NULL) AS header_rows_without_details
        """,
        (source_system, source_system),
    )
    orphan_samples = fetch_all(
        cursor,
        f"""
        WITH header_keys AS (
            SELECT {header_expression} AS document_key
            FROM {qtable(schema, header_table)} h
            WHERE h.source_system = %s
            GROUP BY {header_expression}
        ), detail_keys AS (
            SELECT {detail_expression} AS document_key, COUNT(*)::bigint AS detail_rows
            FROM {qtable(schema, detail_table)} d
            WHERE d.source_system = %s AND {detail_expression} IS NOT NULL
            GROUP BY {detail_expression}
        )
        SELECT d.document_key, d.detail_rows
        FROM detail_keys d LEFT JOIN header_keys h USING (document_key)
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
            SELECT {header_expression} AS document_key, COUNT(*)::bigint AS header_rows
            FROM {qtable(schema, header_table)} h
            WHERE h.source_system = %s AND {header_expression} IS NOT NULL
            GROUP BY {header_expression}
        ), detail_keys AS (
            SELECT {detail_expression} AS document_key
            FROM {qtable(schema, detail_table)} d
            WHERE d.source_system = %s
            GROUP BY {detail_expression}
        )
        SELECT h.document_key, h.header_rows
        FROM header_keys h LEFT JOIN detail_keys d USING (document_key)
        WHERE d.document_key IS NULL
        ORDER BY h.header_rows DESC, h.document_key
        LIMIT %s
        """,
        (source_system, source_system, sample_limit),
    )
    return {
        "header_key_column": header_key,
        "detail_key_column": detail_key,
        "normalization": "lower(trim(key)); blank is missing",
        **metrics,
        "orphan_detail_document_key_samples": orphan_samples,
        "header_without_detail_document_key_samples": headers_without_detail_samples,
    }


def reference_to_header_family(
    cursor,
    *,
    source_schema: str,
    header_schema: str,
    source_system: str,
    source_table: str,
    source_key: str,
    header_tables: Sequence[tuple[str, str]],
    sample_limit: int,
) -> dict[str, Any]:
    """Check a raw reference against a pair of standard/mobile header tables."""

    reference_expression = normalized("s", source_key)
    header_unions = []
    params: list[Any] = [source_system]
    for header_table, header_key in header_tables:
        header_unions.append(
            f"SELECT {normalized('h', header_key)} AS document_key, %s::text AS header_table "
            f"FROM {qtable(header_schema, header_table)} h WHERE h.source_system = %s"
        )
        params.extend([header_table, source_system])
    headers_sql = " UNION ALL ".join(header_unions)
    metrics = fetch_one(
        cursor,
        f"""
        WITH source_references AS (
            SELECT {reference_expression} AS document_key
            FROM {qtable(source_schema, source_table)} s
            WHERE s.source_system = %s
        ), headers AS ({headers_sql}), header_counts AS (
            SELECT document_key, COUNT(*)::bigint AS header_rows
            FROM headers
            WHERE document_key IS NOT NULL
            GROUP BY document_key
        )
        SELECT
            COUNT(*)::bigint AS reference_rows,
            COUNT(*) FILTER (WHERE r.document_key IS NULL)::bigint AS missing_reference_rows,
            COUNT(*) FILTER (WHERE r.document_key IS NOT NULL AND hc.document_key IS NULL)::bigint
                AS reference_rows_without_source_header,
            COUNT(*) FILTER (WHERE hc.header_rows = 1)::bigint
                AS reference_rows_with_exactly_one_source_header,
            COUNT(*) FILTER (WHERE hc.header_rows > 1)::bigint
                AS reference_rows_with_multiple_source_headers
        FROM source_references r
        LEFT JOIN header_counts hc USING (document_key)
        """,
        params,
    )
    sample_params = [source_system, *params[1:], sample_limit]
    missing_samples = fetch_all(
        cursor,
        f"""
        WITH source_references AS (
            SELECT {reference_expression} AS document_key
            FROM {qtable(source_schema, source_table)} s
            WHERE s.source_system = %s
        ), headers AS ({headers_sql}), header_counts AS (
            SELECT document_key, COUNT(*)::bigint AS header_rows
            FROM headers
            WHERE document_key IS NOT NULL
            GROUP BY document_key
        )
        SELECT r.document_key
        FROM source_references r LEFT JOIN header_counts hc USING (document_key)
        WHERE r.document_key IS NOT NULL AND hc.document_key IS NULL
        GROUP BY r.document_key
        ORDER BY r.document_key
        LIMIT %s
        """,
        sample_params,
    )
    return {
        "reference_key_column": source_key,
        "source_schema": source_schema,
        "header_schema": header_schema,
        "header_tables": [table for table, _ in header_tables],
        "normalization": "lower(trim(key)); blank is missing",
        **metrics,
        "reference_without_source_header_samples": missing_samples,
    }


def sales_document_registry_coverage(
    cursor,
    *,
    schema: str,
    source_system: str,
    table: str,
    legacy_header_table: str,
) -> dict[str, Any]:
    """Detect whether a sales header's registry document map is stale/missing."""

    nota_expression = normalized("s", "nota")
    return {
        "policy": "registry identity is source_system + source_table + normalized nota; no ERP lookup",
        **fetch_one(
            cursor,
            f"""
            WITH source_rows AS (
                SELECT staging_id, source_row_hash, {nota_expression} AS document_key
                FROM {qtable(schema, table)} s
                WHERE s.source_system = %s
            )
            SELECT
                COUNT(*)::bigint AS total_rows,
                COUNT(*) FILTER (WHERE document_key IS NULL)::bigint AS missing_document_key_rows,
                COUNT(*) FILTER (WHERE document_key IS NOT NULL AND m.id_sales_order IS NOT NULL)::bigint
                    AS registered_rows,
                COUNT(*) FILTER (WHERE document_key IS NOT NULL AND m.id_sales_order IS NULL)::bigint
                    AS unregistered_rows,
                COUNT(*) FILTER (
                    WHERE m.id_sales_order IS NOT NULL AND m.stage_schema = %s
                )::bigint AS registered_same_stage_schema_rows,
                COUNT(*) FILTER (
                    WHERE m.id_sales_order IS NOT NULL AND m.source_staging_id = s.staging_id
                )::bigint AS registered_same_staging_id_rows,
                COUNT(*) FILTER (
                    WHERE m.id_sales_order IS NOT NULL AND m.source_row_hash = s.source_row_hash
                )::bigint AS registered_same_row_hash_rows
            FROM source_rows s
            LEFT JOIN {qtable(REGISTRY_SCHEMA, 'sales_document_map')} m
              ON m.source_system = %s
             AND m.source_table = %s
             AND m.source_nota_norm = s.document_key
            """,
            (source_system, schema, source_system, legacy_header_table),
        ),
    }


def sales_line_registry_coverage(
    cursor,
    *,
    schema: str,
    source_system: str,
    table: str,
    legacy_header_table: str,
    available_columns: set[str],
) -> dict[str, Any]:
    if "urut" not in available_columns:
        return {
            "available": False,
            "reason": "Kolom urut tidak ada; tidak membuat line key sintetis untuk registry.",
        }
    nota_expression = normalized("s", "nota")
    urut_expression = normalized("s", "urut")
    return {
        "available": True,
        "policy": "registry line identity uses source_system + header source_table + nota + urut; no ERP lookup",
        **fetch_one(
            cursor,
            f"""
            WITH source_rows AS (
                SELECT staging_id, source_row_hash,
                       {nota_expression} AS document_key, {urut_expression} AS line_key
                FROM {qtable(schema, table)} s
                WHERE s.source_system = %s
            )
            SELECT
                COUNT(*)::bigint AS total_rows,
                COUNT(*) FILTER (WHERE document_key IS NULL OR line_key IS NULL)::bigint
                    AS incomplete_registry_key_rows,
                COUNT(*) FILTER (
                    WHERE document_key IS NOT NULL AND line_key IS NOT NULL
                      AND lm.id_sales_order_detail IS NOT NULL
                )::bigint AS registered_rows,
                COUNT(*) FILTER (
                    WHERE document_key IS NOT NULL AND line_key IS NOT NULL
                      AND lm.id_sales_order_detail IS NULL
                )::bigint AS unregistered_rows,
                COUNT(*) FILTER (
                    WHERE lm.id_sales_order_detail IS NOT NULL AND lm.source_staging_id = s.staging_id
                )::bigint AS registered_same_staging_id_rows,
                COUNT(*) FILTER (
                    WHERE lm.id_sales_order_detail IS NOT NULL AND lm.source_row_hash = s.source_row_hash
                )::bigint AS registered_same_row_hash_rows
            FROM source_rows s
            LEFT JOIN {qtable(REGISTRY_SCHEMA, 'sales_document_line_map')} lm
              ON lm.source_system = %s
             AND lm.source_table = %s
             AND lm.source_nota_norm = s.document_key
             AND lm.source_urut_norm = s.line_key
            """,
            (source_system, source_system, legacy_header_table),
        ),
    }


def payment_sales_code_note(
    cursor,
    *,
    schema: str,
    source_system: str,
    table: str,
) -> dict[str, Any]:
    """Do not map a sales code if its companion principal code does not exist."""

    metrics = fetch_one(
        cursor,
        f"""
        SELECT
            COUNT(*)::bigint AS total_rows,
            COUNT(*) FILTER (WHERE {normalized('s', 'kodesales')} IS NOT NULL)::bigint
                AS nonblank_sales_code_rows
        FROM {qtable(schema, table)} s
        WHERE s.source_system = %s
        """,
        (source_system,),
    )
    return {
        "policy": "sales_map is deliberately not queried: Pembayaran has no kodeprinciple, so mapping by sales code alone is unsafe.",
        **metrics,
    }


def sales_pair_report(
    cursor,
    *,
    schema: str,
    source_system: str,
    header_table: str,
    detail_table: str,
    header_legacy_table: str,
    header_columns: set[str],
    detail_columns: set[str],
    sample_limit: int,
) -> dict[str, Any]:
    return {
        "headers": {
            "document_keys": document_key_report(
                cursor,
                schema=schema,
                table=header_table,
                source_system=source_system,
                key_column="nota",
                sample_limit=sample_limit,
            ),
            "mapping_coverage": mapping_report(
                cursor,
                schema=schema,
                table=header_table,
                source_system=source_system,
                mappings=SALES_HEADER_MAPPINGS,
            ),
            "document_registry": sales_document_registry_coverage(
                cursor,
                schema=schema,
                source_system=source_system,
                table=header_table,
                legacy_header_table=header_legacy_table,
            ),
        },
        "details": {
            "document_keys": document_key_report(
                cursor,
                schema=schema,
                table=detail_table,
                source_system=source_system,
                key_column="nota",
                sample_limit=sample_limit,
            ),
            "mapping_coverage": mapping_report(
                cursor,
                schema=schema,
                table=detail_table,
                source_system=source_system,
                mappings=SALES_DETAIL_MAPPINGS,
            ),
            "line_keys": line_key_report(
                cursor,
                schema=schema,
                table=detail_table,
                source_system=source_system,
                available_columns=detail_columns,
                document_column="nota",
                line_column="urut",
                sample_limit=sample_limit,
            ),
            "document_line_registry": sales_line_registry_coverage(
                cursor,
                schema=schema,
                source_system=source_system,
                table=detail_table,
                legacy_header_table=header_legacy_table,
                available_columns=detail_columns,
            ),
            "raw_quantity_fields": raw_field_profile(
                cursor,
                schema=schema,
                table=detail_table,
                source_system=source_system,
                available_columns=detail_columns,
                fields=RAW_QTY_FIELDS,
                policy=(
                    "raw_fields_only_no_uom_inference; product_uom_map is not queried; "
                    "no CT/PCS conversion is calculated"
                ),
            ),
        },
        "header_detail_relationship": header_detail_relationship(
            cursor,
            schema=schema,
            source_system=source_system,
            header_table=header_table,
            detail_table=detail_table,
            header_key="nota",
            detail_key="nota",
            sample_limit=sample_limit,
        ),
        "source_columns_confirmed": {
            "header_columns": sorted(header_columns),
            "detail_columns": sorted(detail_columns),
        },
    }


def payment_report(
    cursor,
    *,
    schema: str,
    sales_schema: str,
    source_system: str,
    columns: dict[str, set[str]],
    sample_limit: int,
) -> dict[str, Any]:
    payment_amount_policy = "raw legacy amount fields only; no amount conversion or settlement allocation is inferred"
    sales_headers = (("hjualsm", "nota"), ("hjualsmandroid", "nota"))
    return {
        "hbayar_dbayar": {
            "headers": {
                "document_keys": document_key_report(
                    cursor,
                    schema=schema,
                    table="hbayarsm",
                    source_system=source_system,
                    key_column="nokwitansi",
                    sample_limit=sample_limit,
                ),
                "mapping_coverage": mapping_report(
                    cursor,
                    schema=schema,
                    table="hbayarsm",
                    source_system=source_system,
                    mappings=PAYMENT_MAPPINGS,
                ),
                "raw_amount_fields": raw_field_profile(
                    cursor,
                    schema=schema,
                    table="hbayarsm",
                    source_system=source_system,
                    available_columns=columns["hbayarsm"],
                    fields=("cash", "noncash", "lain", "jumlahbayar", "nilairetur"),
                    policy=payment_amount_policy,
                ),
            },
            "details": {
                "receipt_keys": document_key_report(
                    cursor,
                    schema=schema,
                    table="dbayarsm",
                    source_system=source_system,
                    key_column="nokwitansi",
                    sample_limit=sample_limit,
                ),
                "sales_note_keys": document_key_report(
                    cursor,
                    schema=schema,
                    table="dbayarsm",
                    source_system=source_system,
                    key_column="nota",
                    sample_limit=sample_limit,
                ),
                "mapping_coverage": mapping_report(
                    cursor,
                    schema=schema,
                    table="dbayarsm",
                    source_system=source_system,
                    mappings=PAYMENT_MAPPINGS,
                ),
                "raw_amount_fields": raw_field_profile(
                    cursor,
                    schema=schema,
                    table="dbayarsm",
                    source_system=source_system,
                    available_columns=columns["dbayarsm"],
                    fields=("jumlahbayar",),
                    policy=payment_amount_policy,
                ),
                "sales_header_reference": reference_to_header_family(
                    cursor,
                    source_schema=schema,
                    header_schema=sales_schema,
                    source_system=source_system,
                    source_table="dbayarsm",
                    source_key="nota",
                    header_tables=sales_headers,
                    sample_limit=sample_limit,
                ),
            },
            "header_detail_relationship": header_detail_relationship(
                cursor,
                schema=schema,
                source_system=source_system,
                header_table="hbayarsm",
                detail_table="dbayarsm",
                header_key="nokwitansi",
                detail_key="nokwitansi",
                sample_limit=sample_limit,
            ),
        },
        "pembayaran": {
            "receipt_keys": document_key_report(
                cursor,
                schema=schema,
                table="pembayaran",
                source_system=source_system,
                key_column="nokwitansi",
                sample_limit=sample_limit,
            ),
            "sales_note_keys": document_key_report(
                cursor,
                schema=schema,
                table="pembayaran",
                source_system=source_system,
                key_column="nota",
                sample_limit=sample_limit,
            ),
            "mapping_coverage": mapping_report(
                cursor,
                schema=schema,
                table="pembayaran",
                source_system=source_system,
                mappings=PAYMENT_MAPPINGS,
            ),
            "sales_code_without_principal": payment_sales_code_note(
                cursor,
                schema=schema,
                source_system=source_system,
                table="pembayaran",
            ),
            "sales_header_reference": reference_to_header_family(
                cursor,
                source_schema=schema,
                header_schema=sales_schema,
                source_system=source_system,
                source_table="pembayaran",
                source_key="nota",
                header_tables=sales_headers,
                sample_limit=sample_limit,
            ),
            "hbayar_receipt_reference": reference_to_header_family(
                cursor,
                source_schema=schema,
                header_schema=schema,
                source_system=source_system,
                source_table="pembayaran",
                source_key="nokwitansi",
                header_tables=(("hbayarsm", "nokwitansi"),),
                sample_limit=sample_limit,
            ),
            "raw_amount_fields": raw_field_profile(
                cursor,
                schema=schema,
                table="pembayaran",
                source_system=source_system,
                available_columns=columns["pembayaran"],
                fields=("totaltagihan", "totalbayar"),
                policy=payment_amount_policy,
            ),
        },
    }


def return_pair_report(
    cursor,
    *,
    schema: str,
    sales_schema: str,
    source_system: str,
    header_table: str,
    detail_table: str,
    header_columns: set[str],
    detail_columns: set[str],
    sample_limit: int,
) -> dict[str, Any]:
    return {
        "headers": {
            "document_keys": document_key_report(
                cursor,
                schema=schema,
                table=header_table,
                source_system=source_system,
                key_column="nota",
                sample_limit=sample_limit,
            ),
            "mapping_coverage": mapping_report(
                cursor,
                schema=schema,
                table=header_table,
                source_system=source_system,
                mappings=RETURN_HEADER_MAPPINGS,
            ),
            "original_sales_note_reference": reference_to_header_family(
                cursor,
                source_schema=schema,
                header_schema=sales_schema,
                source_system=source_system,
                source_table=header_table,
                source_key="notasm",
                header_tables=(("hjualsm", "nota"), ("hjualsmandroid", "nota")),
                sample_limit=sample_limit,
            ),
        },
        "details": {
            "document_keys": document_key_report(
                cursor,
                schema=schema,
                table=detail_table,
                source_system=source_system,
                key_column="nota",
                sample_limit=sample_limit,
            ),
            "mapping_coverage": mapping_report(
                cursor,
                schema=schema,
                table=detail_table,
                source_system=source_system,
                mappings=RETURN_DETAIL_MAPPINGS,
            ),
            "line_keys": line_key_report(
                cursor,
                schema=schema,
                table=detail_table,
                source_system=source_system,
                available_columns=detail_columns,
                document_column="nota",
                line_column="urut",
                sample_limit=sample_limit,
            ),
            "raw_quantity_fields": raw_field_profile(
                cursor,
                schema=schema,
                table=detail_table,
                source_system=source_system,
                available_columns=detail_columns,
                fields=RAW_QTY_FIELDS,
                policy=(
                    "raw_fields_only_no_uom_inference; product_uom_map is not queried; "
                    "no CT/PCS conversion is calculated"
                ),
            ),
        },
        "header_detail_relationship": header_detail_relationship(
            cursor,
            schema=schema,
            source_system=source_system,
            header_table=header_table,
            detail_table=detail_table,
            header_key="nota",
            detail_key="nota",
            sample_limit=sample_limit,
        ),
        "source_columns_confirmed": {
            "header_columns": sorted(header_columns),
            "detail_columns": sorted(detail_columns),
        },
    }


def stock_opname_report(
    cursor,
    *,
    schema: str,
    source_system: str,
    columns: set[str],
    sample_limit: int,
) -> dict[str, Any]:
    return {
        "record_keys": document_key_report(
            cursor,
            schema=schema,
            table="stokopnameandroid",
            source_system=source_system,
            key_column="id",
            sample_limit=sample_limit,
        ),
        "mapping_coverage": mapping_report(
            cursor,
            schema=schema,
            table="stokopnameandroid",
            source_system=source_system,
            mappings=STOCK_OPNAME_MAPPINGS,
        ),
        "raw_stock_opname_field": raw_field_profile(
            cursor,
            schema=schema,
            table="stokopnameandroid",
            source_system=source_system,
            available_columns=columns,
            fields=("stokopname",),
            policy=(
                "raw_fields_only_no_uom_inference; source does not supply an approved UOM mapping here; "
                "no CT/PCS conversion is calculated"
            ),
        ),
    }


def source_report(
    cursor,
    *,
    source_system: str,
    schemas: dict[str, str],
    metadata: dict[str, dict[str, Any]],
    stage_alignment: dict[str, Any],
    columns: dict[str, set[str]],
    sample_limit: int,
) -> dict[str, Any]:
    sales_schema = schemas["sales"]
    payment_return_schema = schemas["payment_return"]
    stock_opname_schema = schemas["stock_opname"]
    return {
        "source_system": source_system,
        "stage_schemas": schemas,
        "stages": metadata,
        "stage_alignment": stage_alignment,
        "sales": {
            "standard": sales_pair_report(
                cursor,
                schema=sales_schema,
                source_system=source_system,
                header_table="hjualsm",
                detail_table="djualsm",
                header_legacy_table="HJualSM",
                header_columns=columns["hjualsm"],
                detail_columns=columns["djualsm"],
                sample_limit=sample_limit,
            ),
            "android": sales_pair_report(
                cursor,
                schema=sales_schema,
                source_system=source_system,
                header_table="hjualsmandroid",
                detail_table="djualsmandroid",
                header_legacy_table="HJualSMAndroid",
                header_columns=columns["hjualsmandroid"],
                detail_columns=columns["djualsmandroid"],
                sample_limit=sample_limit,
            ),
        },
        "payments": payment_report(
            cursor,
            schema=payment_return_schema,
            sales_schema=sales_schema,
            source_system=source_system,
            columns=columns,
            sample_limit=sample_limit,
        ),
        "returns": {
            "standard": return_pair_report(
                cursor,
                schema=payment_return_schema,
                sales_schema=sales_schema,
                source_system=source_system,
                header_table="hretursm",
                detail_table="dretursm",
                header_columns=columns["hretursm"],
                detail_columns=columns["dretursm"],
                sample_limit=sample_limit,
            ),
            "android": return_pair_report(
                cursor,
                schema=payment_return_schema,
                sales_schema=sales_schema,
                source_system=source_system,
                header_table="hretursmandroid",
                detail_table="dretursmandroid",
                header_columns=columns["hretursmandroid"],
                detail_columns=columns["dretursmandroid"],
                sample_limit=sample_limit,
            ),
        },
        "stock_opname": stock_opname_report(
            cursor,
            schema=stock_opname_schema,
            source_system=source_system,
            columns=columns["stokopnameandroid"],
            sample_limit=sample_limit,
        ),
    }


def cross_source_key_collisions(
    cursor,
    *,
    table_keys: Sequence[tuple[str, str, str, str, str]],
    sample_limit: int,
) -> dict[str, Any]:
    """Compare source-aware keys using the explicit BDM/TMP schema of each table."""

    unions: list[str] = []
    params: list[Any] = []
    for stage_table, source_table, key_column, bdm_schema, tmp_schema in table_keys:
        for schema, source_system in ((bdm_schema, "bdm_solo_dist"), (tmp_schema, "tmp_solo_dist")):
            unions.append(
                f"SELECT %s::text AS source_system, %s::text AS source_table, "
                f"{normalized('s', key_column)} AS document_key "
                f"FROM {qtable(schema, stage_table)} s WHERE s.source_system = %s"
            )
            params.extend((source_system, source_table, source_system))
    all_rows = " UNION ALL ".join(unions)
    metrics = fetch_one(
        cursor,
        f"""
        WITH all_rows AS ({all_rows}),
        keyed AS (
            SELECT * FROM all_rows WHERE document_key IS NOT NULL
        ), by_key AS (
            SELECT document_key,
                   COUNT(*)::bigint AS row_count,
                   COUNT(DISTINCT source_system)::bigint AS source_system_count,
                   COUNT(DISTINCT source_table)::bigint AS source_table_count
            FROM keyed
            GROUP BY document_key
        ), by_origin_table AS (
            SELECT document_key, source_table,
                   COUNT(DISTINCT source_system)::bigint AS source_system_count
            FROM keyed
            GROUP BY document_key, source_table
        ), by_source_key AS (
            SELECT document_key, source_system,
                   COUNT(DISTINCT source_table)::bigint AS source_table_count
            FROM keyed
            GROUP BY document_key, source_system
        )
        SELECT
            (SELECT COUNT(*)::bigint FROM all_rows) AS total_header_or_record_rows,
            (SELECT COUNT(*)::bigint FROM all_rows WHERE document_key IS NULL) AS missing_key_rows,
            (SELECT COUNT(*)::bigint FROM by_key WHERE source_system_count > 1)
                AS cross_source_key_groups_any_table,
            (SELECT COUNT(DISTINCT document_key)::bigint FROM by_origin_table WHERE source_system_count > 1)
                AS cross_source_key_groups_same_origin_table,
            (SELECT COUNT(DISTINCT document_key)::bigint FROM by_source_key WHERE source_table_count > 1)
                AS same_source_key_groups_across_standard_mobile_tables
        """,
        params,
    )
    sample_rows = fetch_all(
        cursor,
        f"""
        WITH all_rows AS ({all_rows}), keyed AS (
            SELECT * FROM all_rows WHERE document_key IS NOT NULL
        ), grouped AS (
            SELECT document_key,
                   COUNT(*)::bigint AS row_count,
                   COUNT(DISTINCT source_system)::bigint AS source_system_count,
                   COUNT(DISTINCT source_table)::bigint AS source_table_count,
                   array_agg(DISTINCT source_system ORDER BY source_system) AS source_systems,
                   array_agg(DISTINCT source_table ORDER BY source_table) AS source_tables
            FROM keyed
            GROUP BY document_key
        )
        SELECT document_key, row_count, source_system_count, source_table_count, source_systems, source_tables
        FROM grouped
        WHERE source_system_count > 1
        ORDER BY row_count DESC, document_key
        LIMIT %s
        """,
        (*params, sample_limit),
    )
    return {
        "identity_policy": (
            "A collision is a review signal only. Target identity must retain source_system and source_table; "
            "this report never deduplicates or merges it."
        ),
        "tables": [
            {
                "stage_table": stage_table,
                "source_table": source_table,
                "key_column": key_column,
                "bdm_schema": bdm_schema,
                "tmp_schema": tmp_schema,
            }
            for stage_table, source_table, key_column, bdm_schema, tmp_schema in table_keys
        ],
        "normalization": "lower(trim(key)); blank is missing",
        **metrics,
        "cross_source_key_samples": sample_rows,
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
            bdm_schemas = {
                "sales": args.bdm_sales_schema,
                "payment_return": args.bdm_payment_return_schema,
                "stock_opname": args.bdm_stock_opname_schema,
            }
            tmp_schemas = {
                "sales": args.tmp_sales_schema,
                "payment_return": args.tmp_payment_return_schema,
                "stock_opname": args.tmp_stock_opname_schema,
            }
            module_tables = {
                "sales": SALES_STAGE_TABLE_NAMES,
                "payment_return": PAYMENT_RETURN_STAGE_TABLE_NAMES,
                "stock_opname": STOCK_OPNAME_STAGE_TABLE_NAMES,
            }

            bdm_metadata: dict[str, dict[str, Any]] = {}
            bdm_columns: dict[str, set[str]] = {}
            tmp_metadata: dict[str, dict[str, Any]] = {}
            tmp_columns: dict[str, set[str]] = {}
            for module, table_names in module_tables.items():
                bdm_module_metadata, bdm_module_columns = validate_source_schema(
                    cursor, bdm_schemas[module], "bdm_solo_dist", table_names
                )
                tmp_module_metadata, tmp_module_columns = validate_source_schema(
                    cursor, tmp_schemas[module], "tmp_solo_dist", table_names
                )
                bdm_metadata[module] = bdm_module_metadata
                bdm_columns.update(bdm_module_columns)
                tmp_metadata[module] = tmp_module_metadata
                tmp_columns.update(tmp_module_columns)
            bdm_alignment = validate_source_stage_alignment(
                source_system="bdm_solo_dist", stage_metadata_by_module=bdm_metadata
            )
            tmp_alignment = validate_source_stage_alignment(
                source_system="tmp_solo_dist", stage_metadata_by_module=tmp_metadata
            )
            if args.allow_shared_source_schema:
                validate_combined_schema_metadata(
                    source_system="bdm_solo_dist",
                    schema=args.bdm_sales_schema,
                    stage_metadata_by_module=bdm_metadata,
                )
                validate_combined_schema_metadata(
                    source_system="tmp_solo_dist",
                    schema=args.tmp_sales_schema,
                    stage_metadata_by_module=tmp_metadata,
                )
            paired_input = paired_stage_input_status(
                bdm_metadata_by_module=bdm_metadata,
                tmp_metadata_by_module=tmp_metadata,
            )
            # This field means only that both sources passed the read-only
            # consistency checks as a pair.  It remains explicitly distinct
            # from authority to merge, which this tool never grants.
            for source_metadata in (bdm_metadata, tmp_metadata):
                for metadata in source_metadata.values():
                    metadata["merge_input_eligible"] = paired_input["pair_consistency_eligible"]
            report = {
                "report": "bdm_tmp_aug2026_sales_finance_stockopname_reconciliation",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "read_only": True,
                "registry_schema": REGISTRY_SCHEMA,
                "scope": {
                    "queries_only": ["staging schemas", "migration registry", "information_schema validation"],
                    "does_not_query_public_tables": True,
                    "does_not_write_staging_or_registry": True,
                    "does_not_perform_uom_inference": True,
                    "does_not_query_product_uom_map": True,
                    "merge_permission": "never granted by this reconciliation script",
                },
                "merge_input_status": (
                    "consistent_paired_stages_observed_but_manual_merge_authorization_still_required"
                    if paired_input["pair_consistency_eligible"]
                    else "non_mergeable_preview_or_unverified_consistency"
                ),
                "paired_stage_input": paired_input,
                "stage_schema_layout": {
                    "allow_shared_source_schema": bool(args.allow_shared_source_schema),
                    "bdm_solo_dist": (
                        "combined_per_source"
                        if args.allow_shared_source_schema
                        else "separate_per_module"
                    ),
                    "tmp_solo_dist": (
                        "combined_per_source"
                        if args.allow_shared_source_schema
                        else "separate_per_module"
                    ),
                },
                "sources": {
                    "bdm_solo_dist": source_report(
                        cursor,
                        source_system="bdm_solo_dist",
                        schemas=bdm_schemas,
                        metadata=bdm_metadata,
                        stage_alignment=bdm_alignment,
                        columns=bdm_columns,
                        sample_limit=args.sample_limit,
                    ),
                    "tmp_solo_dist": source_report(
                        cursor,
                        source_system="tmp_solo_dist",
                        schemas=tmp_schemas,
                        metadata=tmp_metadata,
                        stage_alignment=tmp_alignment,
                        columns=tmp_columns,
                        sample_limit=args.sample_limit,
                    ),
                },
                "cross_source_collisions": {
                    "sales_headers": cross_source_key_collisions(
                        cursor,
                        table_keys=(
                            (
                                "hjualsm",
                                "HJualSM",
                                "nota",
                                args.bdm_sales_schema,
                                args.tmp_sales_schema,
                            ),
                            (
                                "hjualsmandroid",
                                "HJualSMAndroid",
                                "nota",
                                args.bdm_sales_schema,
                                args.tmp_sales_schema,
                            ),
                        ),
                        sample_limit=args.sample_limit,
                    ),
                    "payment_receipts": cross_source_key_collisions(
                        cursor,
                        table_keys=(
                            (
                                "hbayarsm",
                                "HBayarSM",
                                "nokwitansi",
                                args.bdm_payment_return_schema,
                                args.tmp_payment_return_schema,
                            ),
                            (
                                "pembayaran",
                                "Pembayaran",
                                "nokwitansi",
                                args.bdm_payment_return_schema,
                                args.tmp_payment_return_schema,
                            ),
                        ),
                        sample_limit=args.sample_limit,
                    ),
                    "return_headers": cross_source_key_collisions(
                        cursor,
                        table_keys=(
                            (
                                "hretursm",
                                "HReturSM",
                                "nota",
                                args.bdm_payment_return_schema,
                                args.tmp_payment_return_schema,
                            ),
                            (
                                "hretursmandroid",
                                "HReturSMAndroid",
                                "nota",
                                args.bdm_payment_return_schema,
                                args.tmp_payment_return_schema,
                            ),
                        ),
                        sample_limit=args.sample_limit,
                    ),
                    "stock_opname_record_ids": cross_source_key_collisions(
                        cursor,
                        table_keys=(
                            (
                                "stokopnameandroid",
                                "StokOpnameAndroid",
                                "id",
                                args.bdm_stock_opname_schema,
                                args.tmp_stock_opname_schema,
                            ),
                        ),
                        sample_limit=args.sample_limit,
                    ),
                },
            }
        # Every SQL statement ran under a read-only transaction.  Explicit
        # rollback remains even if someone changes a connection default later.
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
            json.dumps({"status": "error", "read_only": True, "error": str(exc)}, ensure_ascii=False),
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
