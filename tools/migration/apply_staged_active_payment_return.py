#!/usr/bin/env python3
"""Safely plan/apply active BDM/TMP payment receivables and return preflight.

The legacy imports use the following deliberately narrow boundary:

* ``HBayarSM`` + ``DBayarSM`` are the only payment family eligible to become
  an active *receivable* payment.  A receipt must reconcile exactly to its
  DBayarSM invoice allocations, and every allocation must resolve through the
  immutable source-aware ``sales_document_map``.  The import creates only
  ``public.setoran_customer`` rows with ``is_rekap=1`` and synchronises the
  linked invoice payment status.  It intentionally does **not** insert
  ``setoran``, post cash/bank journals, or alter ``plafon.sisa_bon``.
* ``Pembayaran`` is retained as a hold.  Its status/method semantics are not
  yet approved and it may overlap HBayarSM; treating it as another settlement
  would risk double payment allocation.
* Legacy returns are never made active automatically.  The source lacks a
  proven Good/Bad split, a target UOM interpretation, a completed lifecycle
  status mapping, and a reliable source-sales-detail identity.  The tool can
  persist an auditable preflight/hold record only; it never writes public
  return, credit-note, stock, inventory-ledger, or accounting tables.

Dry-run is the default.  ``--apply-payments`` requires a completed final
snapshot or an attested shared maintenance write-freeze staging pair, the DDL
in ``20260830_create_active_payment_return_import.sql``, and the explicit
confirmation flag.  The tool never connects to SQL Server.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable

try:
    import psycopg2  # type: ignore[import-not-found]
    from psycopg2.extras import Json, execute_values  # type: ignore[import-not-found]
except ImportError:  # Allows --self-test / static validation without DB extras.
    psycopg2 = None  # type: ignore[assignment]
    Json = None  # type: ignore[assignment,misc]
    execute_values = None  # type: ignore[assignment]


REGISTRY_SCHEMA = "migration_bdm_tmp_202608"
SOURCE_SYSTEMS = ("bdm_solo_dist", "tmp_solo_dist")
IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
BATCH_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,119}$")
DECIMAL_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}"
    r"(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?$"
)
AMOUNT_QUANTUM = Decimal("0.01")
MAX_AMOUNT = Decimal("9999999999999999.99")
FINAL_CONSISTENCY_MODES = frozenset({"snapshot", "maintenance_freeze_serializable"})
STAGE_METADATA_TABLES = frozenset({"__stage_run", "__stage_manifest"})
SOURCE_TABLES = {
    "payment_header": "hbayarsm",
    "payment_detail": "dbayarsm",
    "supplemental_payment": "pembayaran",
    "return_header_standard": "hretursm",
    "return_detail_standard": "dretursm",
    "return_header_android": "hretursmandroid",
    "return_detail_android": "dretursmandroid",
}
LEGACY_NAMES = {
    "payment_header": "HBayarSM",
    "payment_detail": "DBayarSM",
    "supplemental_payment": "Pembayaran",
    "return_header_standard": "HReturSM",
    "return_detail_standard": "DReturSM",
    "return_header_android": "HReturSMAndroid",
    "return_detail_android": "DReturSMAndroid",
}
PAYMENT_REQUIRED_COLUMNS = {
    "hbayarsm": {
        "staging_id", "source_system", "source_row_hash", "nokwitansi", "tanggal",
        "kodecustomer", "cash", "noncash", "lain", "jumlahbayar",
    },
    "dbayarsm": {
        "staging_id", "source_system", "source_row_hash", "nokwitansi", "nota",
        "kodecustomer", "jumlahbayar",
    },
    "pembayaran": {
        "staging_id", "source_system", "source_row_hash", "nokwitansi", "nota",
        "kodecustomer", "totalbayar",
    },
}
RETURN_REQUIRED_COLUMNS = {
    "hretursm": {
        "staging_id", "source_system", "source_row_hash", "nota", "tanggal",
        "kodecustomer", "kodeprinciple", "kodesales", "notasm",
    },
    "dretursm": {
        "staging_id", "source_system", "source_row_hash", "nota", "kodestok",
        "kodecustomer", "kodeprinciple", "kodesales", "urut",
    },
    "hretursmandroid": {
        "staging_id", "source_system", "source_row_hash", "nota", "tanggal",
        "kodecustomer", "kodeprinciple", "kodesales", "notasm",
    },
    "dretursmandroid": {
        "staging_id", "source_system", "source_row_hash", "nota", "kodestok",
        "kodecustomer", "kodeprinciple", "kodesales", "urut",
    },
}
PAYMENT_DDL_TABLES = (
    "active_payment_import_run",
    "active_payment_receipt",
    "active_payment_allocation",
    "active_payment_hold",
    "active_payment_action",
)
RETURN_DDL_TABLES = (
    "active_return_preflight_run",
    "active_return_preflight_hold",
)


class ValidationError(RuntimeError):
    """The selected staging/target data is not safe to interpret."""


@dataclass(frozen=True)
class StageMetadata:
    schema: str
    source_system: str
    run_id: int
    status: str
    consistency_mode: str
    is_preview: bool
    maintenance_window_id: str | None
    maintenance_freeze_attested: bool
    maintenance_freeze_confirmed_at: datetime | None
    source_transaction_isolation: str | None
    source_lock_timeout_ms: int | None
    target_company_id: int
    target_branch_id: int
    modules: tuple[str, ...]


@dataclass(frozen=True)
class PaymentHeader:
    source_system: str
    stage_schema: str
    stage_run_id: int
    staging_id: int
    source_row_hash: str
    receipt_no: str | None
    receipt_date_raw: str | None
    customer_code: str | None
    cash_raw: str | None
    noncash_raw: str | None
    lain_raw: str | None
    amount_raw: str | None
    no_bukti: str | None
    keterangan: str | None
    nota_retur: str | None
    nilai_retur_raw: str | None


@dataclass(frozen=True)
class PaymentDetail:
    source_system: str
    stage_schema: str
    stage_run_id: int
    staging_id: int
    source_row_hash: str
    receipt_no: str | None
    invoice_no: str | None
    customer_code: str | None
    amount_raw: str | None


@dataclass(frozen=True)
class SupplementaryPayment:
    source_system: str
    stage_schema: str
    stage_run_id: int
    staging_id: int
    source_row_hash: str
    receipt_no: str | None
    invoice_no: str | None
    customer_code: str | None
    amount_raw: str | None
    status_raw: str | None
    method_raw: str | None


@dataclass(frozen=True)
class ReturnRow:
    source_system: str
    stage_schema: str
    stage_run_id: int
    source_table: str
    staging_id: int
    source_row_hash: str
    return_no: str | None
    invoice_no: str | None
    customer_code: str | None
    principal_code: str | None
    sales_code: str | None
    sku: str | None
    urut: str | None


@dataclass(frozen=True)
class Hold:
    source_system: str
    source_table: str
    stage_schema: str
    staging_id: int
    source_row_hash: str
    reason: str
    receipt_no: str | None = None
    invoice_no: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AllocationPlan:
    detail: PaymentDetail
    source_sales_table: str
    id_sales_order: int
    id_faktur: int
    id_sales: int
    amount: Decimal


@dataclass(frozen=True)
class ReceiptPlan:
    header: PaymentHeader
    receipt_no: str
    receipt_no_norm: str
    receipt_date: date
    customer_code: str
    customer_code_norm: str
    id_customer: int
    amount: Decimal
    payment_type: int
    payload_hash: str
    allocations: tuple[AllocationPlan, ...]


def ident(value: str) -> str:
    if not IDENT_RE.fullmatch(value):
        raise ValidationError(f"Identifier PostgreSQL tidak aman: {value!r}")
    return f'"{value}"'


def qtable(schema: str, table: str) -> str:
    return f"{ident(schema)}.{ident(table)}"


def stage_metadata_table(schema: str, table: str) -> str:
    if table not in STAGE_METADATA_TABLES:
        raise ValidationError(f"Tabel metadata staging tidak dikenal: {table!r}")
    return f'{ident(schema)}."{table}"'


def clean(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def norm(value: Any) -> str | None:
    result = clean(value)
    return result.lower() if result else None


def json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return value


def parse_amount(value: Any, field: str, *, allow_zero: bool = False) -> tuple[Decimal | None, str | None]:
    raw = clean(value)
    if raw is None:
        return (Decimal("0"), None) if allow_zero else (None, f"blank_{field}")
    if not DECIMAL_RE.fullmatch(raw):
        return None, f"invalid_{field}_format"
    try:
        parsed = Decimal(raw)
    except InvalidOperation:
        return None, f"invalid_{field}_format"
    if not parsed.is_finite() or abs(parsed) > MAX_AMOUNT:
        return None, f"invalid_{field}_range"
    parsed = parsed.quantize(AMOUNT_QUANTUM, rounding=ROUND_HALF_UP)
    if parsed < 0 or (parsed == 0 and not allow_zero):
        return None, f"invalid_{field}_value"
    return parsed, None


def parse_source_date(value: Any) -> tuple[date | None, str | None]:
    raw = clean(value)
    if raw is None:
        return None, "blank_receipt_date"
    try:
        if DATE_RE.fullmatch(raw):
            return date.fromisoformat(raw), None
        if DATETIME_RE.fullmatch(raw):
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date(), None
    except ValueError:
        pass
    return None, "invalid_receipt_date"


def stable_hash(payload: Any) -> str:
    data = json.dumps(json_safe(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def as_dict(cursor, row: tuple[Any, ...] | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {desc.name: value for desc, value in zip(cursor.description, row)}


def connect_from_env():
    if psycopg2 is None:
        raise RuntimeError(
            "Modul psycopg2 diperlukan untuk menjalankan dry-run/apply PostgreSQL. "
            "Pasang psycopg2-binary di environment migrasi."
        )
    kwargs: dict[str, Any] = {
        "dbname": os.getenv("MIGRATION_PG_DATABASE", "budimas_dev"),
        "user": os.getenv("MIGRATION_PG_USER", "postgres"),
    }
    host = os.getenv("MIGRATION_PG_HOST")
    port = os.getenv("MIGRATION_PG_PORT")
    password = os.getenv("MIGRATION_PG_PASSWORD")
    if host:
        kwargs["host"] = host
    if port:
        kwargs["port"] = int(port)
    if password:
        kwargs["password"] = password
    return psycopg2.connect(**kwargs)


def table_columns(cursor, schema: str, table: str) -> set[str]:
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        """,
        (schema, table),
    )
    return {str(row[0]) for row in cursor.fetchall()}


def assert_registry_tables(cursor, tables: Iterable[str]) -> None:
    wanted = list(tables)
    cursor.execute(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s
          AND c.relkind IN ('r', 'p')
          AND c.relname = ANY(%s)
        """,
        (REGISTRY_SCHEMA, wanted),
    )
    present = {str(row[0]) for row in cursor.fetchall()}
    missing = sorted(set(wanted) - present)
    if missing:
        raise ValidationError(
            "DDL import transaksi aktif belum terpasang: " + ", ".join(missing)
            + ". Jalankan tools/migration/20260830_create_active_payment_return_import.sql terlebih dahulu."
        )


def assert_public_columns(cursor, table: str, required: set[str]) -> None:
    columns = table_columns(cursor, "public", table)
    missing = sorted(required - columns)
    if missing:
        raise ValidationError(f"public.{table} tidak memiliki kolom wajib: {', '.join(missing)}")


def assert_no_enabled_user_triggers(cursor, tables: tuple[str, ...]) -> None:
    """Fail closed if direct import DML has an unreviewed side effect."""

    cursor.execute(
        """
        SELECT c.relname, t.tgname
        FROM pg_trigger t
        JOIN pg_class c ON c.oid = t.tgrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relname = ANY(%s)
          AND NOT t.tgisinternal
          AND t.tgenabled <> 'D'
        ORDER BY c.relname, t.tgname
        """,
        (list(tables),),
    )
    enabled = [f"public.{row[0]}.{row[1]}" for row in cursor.fetchall()]
    if enabled:
        raise ValidationError(
            "Apply pembayaran diblokir karena ada trigger target yang belum direview: "
            + ", ".join(enabled)
        )


def read_stage_metadata(
    cursor,
    *,
    schema: str,
    source_system: str,
    required_tables: Iterable[str],
) -> StageMetadata:
    if not IDENT_RE.fullmatch(schema):
        raise ValidationError(f"Schema staging tidak aman: {schema!r}")
    run_table = stage_metadata_table(schema, "__stage_run")
    manifest_table = stage_metadata_table(schema, "__stage_manifest")
    if not table_columns(cursor, schema, "__stage_run") or not table_columns(cursor, schema, "__stage_manifest"):
        raise ValidationError(f"{schema}: metadata __stage_run/__stage_manifest tidak lengkap")
    cursor.execute(
        f"""
        SELECT id, source_system, status, consistency_mode, is_preview,
               maintenance_window_id, maintenance_freeze_attested,
               maintenance_freeze_confirmed_at, source_transaction_isolation,
               source_lock_timeout_ms, target_company_id, target_branch_id, modules
        FROM {run_table}
        ORDER BY id DESC
        LIMIT 1
        """
    )
    row = as_dict(cursor, cursor.fetchone())
    if not row:
        raise ValidationError(f"{schema}: tidak ada stage run")
    if row["source_system"] != source_system:
        raise ValidationError(
            f"{schema}: source_system {row['source_system']!r}, seharusnya {source_system!r}"
        )
    required = list(required_tables)
    cursor.execute(
        f"""
        SELECT lower(legacy_table) AS legacy_table, status
        FROM {manifest_table}
        WHERE lower(legacy_table) = ANY(%s)
        """,
        (required,),
    )
    manifest = {str(item[0]): str(item[1]) for item in cursor.fetchall()}
    absent = [name for name in required if name not in manifest]
    unfinished = [name for name in required if manifest.get(name) != "done"]
    if absent or unfinished:
        messages: list[str] = []
        if absent:
            messages.append("tidak ada=" + ", ".join(absent))
        if unfinished:
            messages.append("belum done=" + ", ".join(unfinished))
        raise ValidationError(f"{schema}: manifest staging tidak siap ({'; '.join(messages)})")
    modules = tuple(part.strip() for part in str(row.get("modules") or "").split(",") if part.strip())
    return StageMetadata(
        schema=schema,
        source_system=source_system,
        run_id=int(row["id"]),
        status=str(row["status"]),
        consistency_mode=str(row["consistency_mode"]),
        is_preview=bool(row["is_preview"]),
        maintenance_window_id=clean(row["maintenance_window_id"]),
        maintenance_freeze_attested=bool(row["maintenance_freeze_attested"]),
        maintenance_freeze_confirmed_at=row["maintenance_freeze_confirmed_at"],
        source_transaction_isolation=clean(row["source_transaction_isolation"]),
        source_lock_timeout_ms=(int(row["source_lock_timeout_ms"]) if row["source_lock_timeout_ms"] is not None else None),
        target_company_id=int(row["target_company_id"]),
        target_branch_id=int(row["target_branch_id"]),
        modules=modules,
    )


def validate_final_pair(bdm: StageMetadata, tmp: StageMetadata, *, apply: bool) -> None:
    if not apply:
        return
    for item in (bdm, tmp):
        if item.status != "completed" or item.is_preview:
            raise ValidationError(
                f"{item.schema}: apply ditolak karena stage bukan final completed/non-preview "
                f"(status={item.status!r}, is_preview={item.is_preview!r})"
            )
        if item.consistency_mode not in FINAL_CONSISTENCY_MODES:
            raise ValidationError(f"{item.schema}: mode konsistensi tidak final: {item.consistency_mode!r}")
    if bdm.consistency_mode == tmp.consistency_mode == "snapshot":
        return
    if bdm.consistency_mode != "maintenance_freeze_serializable" or tmp.consistency_mode != "maintenance_freeze_serializable":
        raise ValidationError("Stage BDM/TMP harus sama-sama snapshot atau sama-sama maintenance_freeze_serializable")
    if not bdm.maintenance_window_id or bdm.maintenance_window_id != tmp.maintenance_window_id:
        raise ValidationError("maintenance_window_id BDM/TMP harus sama dan tidak kosong")
    for item in (bdm, tmp):
        if not item.maintenance_freeze_attested or not item.maintenance_freeze_confirmed_at:
            raise ValidationError(f"{item.schema}: attestation freeze tidak lengkap")
        if (item.source_transaction_isolation or "").strip().lower() != "serializable":
            raise ValidationError(f"{item.schema}: isolation source bukan SERIALIZABLE")
        if not item.source_lock_timeout_ms or item.source_lock_timeout_ms <= 0:
            raise ValidationError(f"{item.schema}: source lock timeout tidak valid")


def validate_selected_stages(
    bdm_sales: StageMetadata,
    tmp_sales: StageMetadata,
    bdm_payment: StageMetadata,
    tmp_payment: StageMetadata,
    *,
    apply: bool,
) -> None:
    """Require final consistency for every source table family we will combine.

    A payment allocation references a sales document.  It is unsafe to use a
    final payment snapshot with a separate, arbitrary sales preview.  Either
    all tables came from one schema per source, or separate schemas must carry
    the same attested maintenance-window ID.
    """

    validate_final_pair(bdm_sales, tmp_sales, apply=apply)
    validate_final_pair(bdm_payment, tmp_payment, apply=apply)
    if not apply:
        return
    for sales, payment in ((bdm_sales, bdm_payment), (tmp_sales, tmp_payment)):
        if sales.source_system != payment.source_system:
            raise ValidationError("sales/payment staging source_system tidak sama")
        if (sales.target_company_id, sales.target_branch_id) != (payment.target_company_id, payment.target_branch_id):
            raise ValidationError(f"{sales.source_system}: scope target sales/payment tidak sama")
        if sales.schema == payment.schema:
            continue
        if (
            sales.consistency_mode != "maintenance_freeze_serializable"
            or payment.consistency_mode != "maintenance_freeze_serializable"
            or not sales.maintenance_window_id
            or sales.maintenance_window_id != payment.maintenance_window_id
        ):
            raise ValidationError(
                f"{sales.source_system}: schema sales dan payment berbeda; gunakan satu final schema "
                "atau dua stage maintenance_freeze_serializable dengan maintenance_window_id yang sama."
            )


def assert_stage_columns(cursor, schema: str, requirements: dict[str, set[str]]) -> None:
    for table, required in requirements.items():
        actual = table_columns(cursor, schema, table)
        missing = sorted(required - actual)
        if missing:
            raise ValidationError(f"{schema}.{table}: kolom staging wajib hilang: {', '.join(missing)}")


def load_source_context(cursor) -> dict[str, dict[str, int]]:
    cursor.execute(
        f"""
        SELECT source_system, target_company_id, target_branch_id
        FROM {qtable(REGISTRY_SCHEMA, 'source_context')}
        """
    )
    result: dict[str, dict[str, int]] = {}
    for source_system, company_id, branch_id in cursor.fetchall():
        result[str(source_system)] = {
            "target_company_id": int(company_id),
            "target_branch_id": int(branch_id),
        }
    missing = set(SOURCE_SYSTEMS) - set(result)
    if missing:
        raise ValidationError("source_context belum lengkap: " + ", ".join(sorted(missing)))
    return result


def load_customer_maps(cursor) -> dict[tuple[str, str], int]:
    cursor.execute(
        f"""
        SELECT source_system, source_customer_code_norm, id_customer
        FROM {qtable(REGISTRY_SCHEMA, 'customer_map')}
        """
    )
    return {(str(source), str(code)): int(target) for source, code, target in cursor.fetchall()}


def load_target_customers(cursor) -> dict[int, int | None]:
    cursor.execute("SELECT id, id_cabang FROM public.customer")
    return {int(row[0]): (int(row[1]) if row[1] is not None else None) for row in cursor.fetchall()}


def load_headers(cursor, schema: str, source_system: str, run_id: int) -> list[PaymentHeader]:
    columns = table_columns(cursor, schema, "hbayarsm")
    def optional(name: str) -> str:
        return name if name in columns else "NULL::text"
    cursor.execute(
        f"""
        SELECT staging_id, source_row_hash, nokwitansi, tanggal, kodecustomer,
               cash, noncash, lain, jumlahbayar, {optional('nobukti')}, {optional('keterangan')},
               {optional('notaretur')}, {optional('nilairetur')}
        FROM {qtable(schema, 'hbayarsm')}
        WHERE source_system = %s
        ORDER BY staging_id
        """,
        (source_system,),
    )
    return [
        PaymentHeader(
            source_system, schema, run_id, int(row[0]), str(row[1]), clean(row[2]), clean(row[3]),
            clean(row[4]), clean(row[5]), clean(row[6]), clean(row[7]), clean(row[8]),
            clean(row[9]), clean(row[10]), clean(row[11]), clean(row[12]),
        )
        for row in cursor.fetchall()
    ]


def load_details(cursor, schema: str, source_system: str, run_id: int) -> list[PaymentDetail]:
    cursor.execute(
        f"""
        SELECT staging_id, source_row_hash, nokwitansi, nota, kodecustomer, jumlahbayar
        FROM {qtable(schema, 'dbayarsm')}
        WHERE source_system = %s
        ORDER BY staging_id
        """,
        (source_system,),
    )
    return [
        PaymentDetail(
            source_system, schema, run_id, int(row[0]), str(row[1]), clean(row[2]), clean(row[3]),
            clean(row[4]), clean(row[5]),
        )
        for row in cursor.fetchall()
    ]


def load_supplemental(cursor, schema: str, source_system: str, run_id: int) -> list[SupplementaryPayment]:
    columns = table_columns(cursor, schema, "pembayaran")
    selectable = {
        "status": "status" if "status" in columns else "NULL::text",
        "metode": "metode" if "metode" in columns else "NULL::text",
    }
    cursor.execute(
        f"""
        SELECT staging_id, source_row_hash, nokwitansi, nota, kodecustomer, totalbayar,
               {selectable['status']}, {selectable['metode']}
        FROM {qtable(schema, 'pembayaran')}
        WHERE source_system = %s
        ORDER BY staging_id
        """,
        (source_system,),
    )
    return [
        SupplementaryPayment(
            source_system, schema, run_id, int(row[0]), str(row[1]), clean(row[2]), clean(row[3]),
            clean(row[4]), clean(row[5]), clean(row[6]), clean(row[7]),
        )
        for row in cursor.fetchall()
    ]


def source_return_rows(
    cursor,
    *,
    schema: str,
    source_system: str,
    run_id: int,
    table: str,
    header: bool,
) -> list[ReturnRow]:
    columns = table_columns(cursor, schema, table)
    def col(name: str) -> str:
        return name if name in columns else "NULL::text"
    if header:
        cursor.execute(
            f"""
            SELECT staging_id, source_row_hash, nota, {col('notasm')}, kodecustomer,
                   kodeprinciple, kodesales, NULL::text, NULL::text
            FROM {qtable(schema, table)}
            WHERE source_system = %s
            ORDER BY staging_id
            """,
            (source_system,),
        )
    else:
        cursor.execute(
            f"""
            SELECT staging_id, source_row_hash, nota, NULL::text, kodecustomer,
                   kodeprinciple, kodesales, {col('kodestok')}, {col('urut')}
            FROM {qtable(schema, table)}
            WHERE source_system = %s
            ORDER BY staging_id
            """,
            (source_system,),
        )
    legacy_name = next(name for name, lower in SOURCE_TABLES.items() if lower == table)
    return [
        ReturnRow(
            source_system, schema, run_id, LEGACY_NAMES[legacy_name], int(row[0]), str(row[1]),
            clean(row[2]), clean(row[3]), clean(row[4]), clean(row[5]), clean(row[6]), clean(row[7]), clean(row[8]),
        )
        for row in cursor.fetchall()
    ]


def canonical_payment_type(header: PaymentHeader) -> tuple[Decimal | None, int | None, str | None]:
    amount, amount_error = parse_amount(header.amount_raw, "receipt_amount")
    if amount_error:
        return None, None, amount_error
    cash, cash_error = parse_amount(header.cash_raw, "cash", allow_zero=True)
    noncash, noncash_error = parse_amount(header.noncash_raw, "noncash", allow_zero=True)
    lain, lain_error = parse_amount(header.lain_raw, "lain", allow_zero=True)
    if cash_error or noncash_error or lain_error:
        return None, None, cash_error or noncash_error or lain_error
    assert amount is not None and cash is not None and noncash is not None and lain is not None
    if cash + noncash + lain != amount:
        return None, None, "receipt_payment_components_do_not_reconcile"
    positive = [name for name, value in (("cash", cash), ("noncash", noncash), ("lain", lain)) if value > 0]
    if len(positive) != 1:
        return None, None, "receipt_payment_method_not_single_exact_type"
    if positive[0] == "cash":
        return amount, 1, None
    if positive[0] == "noncash":
        return amount, 2, None
    return None, None, "receipt_lain_method_requires_explicit_finance_policy"


def load_sales_document_map(cursor, source_system: str, stage_schema: str) -> dict[str, list[dict[str, Any]]]:
    cursor.execute(
        f"""
        SELECT source_nota_norm, source_table, id_sales_order, id_faktur
        FROM {qtable(REGISTRY_SCHEMA, 'sales_document_map')}
        WHERE source_system = %s
          AND stage_schema = %s
          AND source_table IN ('HJualSM', 'HJualSMAndroid')
        """,
        (source_system, stage_schema),
    )
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source_nota, source_table, id_order, id_faktur in cursor.fetchall():
        result[str(source_nota)].append(
            {
                "source_table": str(source_table),
                "id_sales_order": int(id_order),
                "id_faktur": int(id_faktur) if id_faktur is not None else None,
            }
        )
    return result


def load_target_invoice_context(cursor, invoice_ids: Iterable[int]) -> dict[int, dict[str, Any]]:
    values = sorted({int(item) for item in invoice_ids})
    if not values:
        return {}
    has_voucher_usage = bool(table_columns(cursor, "public", "payment_voucher_usage"))
    voucher_sql = (
        """
        LEFT JOIN (
            SELECT id_sales_order, COALESCE(SUM(nominal), 0) AS total_voucher
            FROM public.payment_voucher_usage
            WHERE status = 1
            GROUP BY id_sales_order
        ) pvu ON pvu.id_sales_order = so.id
        """
        if has_voucher_usage
        else ""
    )
    voucher_select = "COALESCE(pvu.total_voucher, 0)" if has_voucher_usage else "0::numeric"
    cursor.execute(
        f"""
        SELECT f.id AS id_faktur,
               f.id_sales_order,
               f.jenis_faktur,
               f.status_faktur,
               COALESCE(f.total_penjualan, so.total_order, 0)::numeric AS total_tagihan,
               COALESCE(f.nominal_retur, 0)::numeric AS nominal_retur,
               COALESCE(sc.total_setoran, 0)::numeric AS total_setoran,
               {voucher_select}::numeric AS total_voucher,
               (
                   SELECT COUNT(*)
                   FROM public.faktur sales_faktur
                   WHERE sales_faktur.id_sales_order = so.id
                     AND sales_faktur.jenis_faktur = 'penjualan'
               ) AS sales_faktur_count,
               so.id_cabang,
               pl.id_customer,
               pl.id_principal,
               pl.id_sales
        FROM public.faktur f
        JOIN public.sales_order so ON so.id = f.id_sales_order
        JOIN public.plafon pl ON pl.id = so.id_plafon
        LEFT JOIN (
            SELECT id_sales_order, COALESCE(SUM(jumlah_setoran), 0) AS total_setoran
            FROM public.setoran_customer
            GROUP BY id_sales_order
        ) sc ON sc.id_sales_order = so.id
        {voucher_sql}
        WHERE f.id = ANY(%s)
        """,
        (values,),
    )
    result: dict[int, dict[str, Any]] = {}
    for row in cursor.fetchall():
        result[int(row[0])] = {
            "id_faktur": int(row[0]),
            "id_sales_order": int(row[1]),
            "jenis_faktur": clean(row[2]),
            "status_faktur": row[3],
            "total_tagihan": Decimal(row[4] or 0),
            "nominal_retur": Decimal(row[5] or 0),
            "total_setoran": Decimal(row[6] or 0),
            "total_voucher": Decimal(row[7] or 0),
            # `setoran_customer` is linked to sales_order, not a faktur.
            # An allocation is therefore safe only where exactly one sales
            # invoice exists under that order; otherwise an order-level
            # payment/status would bleed into sibling invoices.
            "sales_faktur_count": int(row[8] or 0),
            "id_cabang": int(row[9]) if row[9] is not None else None,
            "id_customer": int(row[10]) if row[10] is not None else None,
            "id_principal": int(row[11]) if row[11] is not None else None,
            "id_sales": int(row[12]) if row[12] is not None else None,
        }
    return result


def load_return_invoice_references(cursor, schema: str, source_system: str) -> set[str]:
    refs: set[str] = set()
    for table in ("hretursm", "hretursmandroid"):
        cursor.execute(
            f"""
            SELECT NULLIF(lower(btrim(notasm)), '')
            FROM {qtable(schema, table)}
            WHERE source_system = %s
              AND NULLIF(lower(btrim(notasm)), '') IS NOT NULL
            """,
            (source_system,),
        )
        refs.update(str(row[0]) for row in cursor.fetchall())
    return refs


def registry_table_exists(cursor, table: str) -> bool:
    cursor.execute("SELECT to_regclass(%s)", (f"{REGISTRY_SCHEMA}.{table}",))
    return cursor.fetchone()[0] is not None


def existing_payment_receipts(cursor) -> dict[tuple[str, str], dict[str, Any]]:
    # Dry-run is useful before the new DDL is installed.  In that case there
    # cannot yet be a prior import, so do not turn a non-mutating review into a
    # schema-install prerequisite.
    if not registry_table_exists(cursor, "active_payment_receipt"):
        return {}
    cursor.execute(
        f"""
        SELECT id, source_system, source_receipt_no_norm, source_payload_hash, receipt_total
        FROM {qtable(REGISTRY_SCHEMA, 'active_payment_receipt')}
        """
    )
    return {
        (str(source), str(receipt)): {
            "id": int(receipt_id),
            "payload_hash": str(payload_hash),
            "amount": Decimal(amount),
        }
        for receipt_id, source, receipt, payload_hash, amount in cursor.fetchall()
    }


def amount_equal(left: Decimal, right: Decimal) -> bool:
    return left.quantize(AMOUNT_QUANTUM) == right.quantize(AMOUNT_QUANTUM)


def build_payment_plan(
    cursor,
    *,
    metadata: StageMetadata,
    sales_metadata: StageMetadata,
    customer_maps: dict[tuple[str, str], int],
    target_customers: dict[int, int | None],
    source_context: dict[str, dict[str, int]],
    return_invoice_refs: set[str],
) -> tuple[list[ReceiptPlan], list[Hold]]:
    headers = load_headers(cursor, metadata.schema, metadata.source_system, metadata.run_id)
    details = load_details(cursor, metadata.schema, metadata.source_system, metadata.run_id)
    supplemental = load_supplemental(cursor, metadata.schema, metadata.source_system, metadata.run_id)
    holds: list[Hold] = []

    for row in supplemental:
        holds.append(
            Hold(
                row.source_system, "Pembayaran", row.stage_schema, row.staging_id, row.source_row_hash,
                "supplemental_pembayaran_status_method_semantics_unapproved", row.receipt_no, row.invoice_no,
                {"status": row.status_raw, "metode": row.method_raw},
            )
        )

    headers_by_receipt: dict[str, list[PaymentHeader]] = defaultdict(list)
    details_by_receipt: dict[str, list[PaymentDetail]] = defaultdict(list)
    for header in headers:
        receipt_norm = norm(header.receipt_no)
        if not receipt_norm:
            holds.append(Hold(header.source_system, "HBayarSM", header.stage_schema, header.staging_id, header.source_row_hash,
                              "blank_receipt_number", header.receipt_no))
        else:
            headers_by_receipt[receipt_norm].append(header)
    for detail in details:
        receipt_norm = norm(detail.receipt_no)
        if not receipt_norm:
            holds.append(Hold(detail.source_system, "DBayarSM", detail.stage_schema, detail.staging_id, detail.source_row_hash,
                              "blank_receipt_number", detail.receipt_no, detail.invoice_no))
        else:
            details_by_receipt[receipt_norm].append(detail)

    # A DBayarSM detail without exactly traceable HBayarSM header must be
    # visible in the audit output.  Silently omitting it would make the
    # source-vs-target reconciliation look complete when it is not.
    for receipt_norm, receipt_details in details_by_receipt.items():
        if receipt_norm in headers_by_receipt:
            continue
        for detail in receipt_details:
            holds.append(Hold(
                detail.source_system, "DBayarSM", detail.stage_schema, detail.staging_id, detail.source_row_hash,
                "orphan_dbayarsm_receipt_header_missing", detail.receipt_no, detail.invoice_no,
            ))

    sales_map = load_sales_document_map(cursor, metadata.source_system, sales_metadata.schema)
    existing = existing_payment_receipts(cursor)
    candidate_raw: list[tuple[PaymentHeader, str, date, str, int, Decimal, int, list[PaymentDetail]]] = []
    needed_faktur_ids: set[int] = set()

    for receipt_norm, receipt_headers in headers_by_receipt.items():
        if len(receipt_headers) != 1:
            for header in receipt_headers:
                holds.append(Hold(header.source_system, "HBayarSM", header.stage_schema, header.staging_id, header.source_row_hash,
                                  "duplicate_source_receipt_header", header.receipt_no,
                                  details={"duplicate_count": len(receipt_headers)}))
            for detail in details_by_receipt.get(receipt_norm, []):
                holds.append(Hold(detail.source_system, "DBayarSM", detail.stage_schema, detail.staging_id, detail.source_row_hash,
                                  "receipt_header_not_unique", detail.receipt_no, detail.invoice_no))
            continue
        header = receipt_headers[0]
        receipt_details = details_by_receipt.get(receipt_norm, [])
        if not receipt_details:
            holds.append(Hold(header.source_system, "HBayarSM", header.stage_schema, header.staging_id, header.source_row_hash,
                              "receipt_has_no_dbayarsm_allocation", header.receipt_no))
            continue
        receipt_date, date_error = parse_source_date(header.receipt_date_raw)
        customer_code = clean(header.customer_code)
        customer_norm = norm(customer_code)
        amount, payment_type, payment_error = canonical_payment_type(header)
        row_errors = [error for error in (date_error, None if customer_norm else "blank_customer_code", payment_error) if error]
        if row_errors:
            holds.append(Hold(header.source_system, "HBayarSM", header.stage_schema, header.staging_id, header.source_row_hash,
                              row_errors[0], header.receipt_no, details={"all_errors": row_errors}))
            for detail in receipt_details:
                holds.append(Hold(detail.source_system, "DBayarSM", detail.stage_schema, detail.staging_id, detail.source_row_hash,
                                  "receipt_header_not_eligible", detail.receipt_no, detail.invoice_no))
            continue
        assert receipt_date is not None and customer_code is not None and customer_norm is not None and amount is not None and payment_type is not None
        mapped_customer = customer_maps.get((metadata.source_system, customer_norm))
        if mapped_customer is None:
            holds.append(Hold(header.source_system, "HBayarSM", header.stage_schema, header.staging_id, header.source_row_hash,
                              "missing_exact_customer_map", header.receipt_no, details={"customer_code": customer_code}))
            for detail in receipt_details:
                holds.append(Hold(detail.source_system, "DBayarSM", detail.stage_schema, detail.staging_id, detail.source_row_hash,
                                  "receipt_customer_not_mapped", detail.receipt_no, detail.invoice_no))
            continue
        target_branch = target_customers.get(mapped_customer)
        expected_branch = source_context[metadata.source_system]["target_branch_id"]
        if target_branch != expected_branch:
            holds.append(Hold(header.source_system, "HBayarSM", header.stage_schema, header.staging_id, header.source_row_hash,
                              "mapped_customer_branch_scope_mismatch", header.receipt_no,
                              details={"id_customer": mapped_customer, "actual_branch": target_branch, "expected_branch": expected_branch}))
            for detail in receipt_details:
                holds.append(Hold(detail.source_system, "DBayarSM", detail.stage_schema, detail.staging_id, detail.source_row_hash,
                                  "receipt_customer_scope_invalid", detail.receipt_no, detail.invoice_no))
            continue
        if clean(header.nota_retur) is not None:
            holds.append(Hold(header.source_system, "HBayarSM", header.stage_schema, header.staging_id, header.source_row_hash,
                              "receipt_references_unresolved_return", header.receipt_no,
                              details={"nota_retur": header.nota_retur, "nilai_retur": header.nilai_retur_raw}))
            for detail in receipt_details:
                holds.append(Hold(detail.source_system, "DBayarSM", detail.stage_schema, detail.staging_id, detail.source_row_hash,
                                  "receipt_references_unresolved_return", detail.receipt_no, detail.invoice_no))
            continue
        nilai_retur, nilai_retur_error = parse_amount(header.nilai_retur_raw, "nilai_retur", allow_zero=True)
        if nilai_retur_error or (nilai_retur is not None and nilai_retur > 0):
            holds.append(Hold(header.source_system, "HBayarSM", header.stage_schema, header.staging_id, header.source_row_hash,
                              nilai_retur_error or "receipt_has_unresolved_return_value", header.receipt_no,
                              details={"nilai_retur": header.nilai_retur_raw}))
            for detail in receipt_details:
                holds.append(Hold(detail.source_system, "DBayarSM", detail.stage_schema, detail.staging_id, detail.source_row_hash,
                                  "receipt_references_unresolved_return", detail.receipt_no, detail.invoice_no))
            continue
        duplicate_hashes = [key for key, count in Counter(item.source_row_hash for item in receipt_details).items() if count > 1]
        invoice_norms = [norm(item.invoice_no) for item in receipt_details]
        duplicate_invoices = [key for key, count in Counter(invoice_norms).items() if key and count > 1]
        if duplicate_hashes or duplicate_invoices:
            reason = "duplicate_source_payment_detail_payload" if duplicate_hashes else "duplicate_source_payment_invoice_allocation"
            holds.append(Hold(header.source_system, "HBayarSM", header.stage_schema, header.staging_id, header.source_row_hash,
                              reason, header.receipt_no,
                              details={"duplicate_row_hashes": duplicate_hashes, "duplicate_invoice_notes": duplicate_invoices}))
            for detail in receipt_details:
                holds.append(Hold(detail.source_system, "DBayarSM", detail.stage_schema, detail.staging_id, detail.source_row_hash,
                                  reason, detail.receipt_no, detail.invoice_no))
            continue
        details_total = Decimal("0")
        detail_error = False
        for detail in receipt_details:
            detail_amount, detail_amount_error = parse_amount(detail.amount_raw, "allocation_amount")
            detail_customer_norm = norm(detail.customer_code)
            invoice_norm = norm(detail.invoice_no)
            if detail_amount_error or detail_customer_norm != customer_norm or not invoice_norm:
                reason = detail_amount_error or ("allocation_customer_mismatch" if detail_customer_norm != customer_norm else "blank_invoice_number")
                holds.append(Hold(detail.source_system, "DBayarSM", detail.stage_schema, detail.staging_id, detail.source_row_hash,
                                  reason, detail.receipt_no, detail.invoice_no,
                                  {"header_customer": customer_code, "detail_customer": detail.customer_code}))
                detail_error = True
                continue
            assert detail_amount is not None
            details_total += detail_amount
            if invoice_norm in return_invoice_refs:
                holds.append(Hold(detail.source_system, "DBayarSM", detail.stage_schema, detail.staging_id, detail.source_row_hash,
                                  "allocation_invoice_has_unresolved_legacy_return", detail.receipt_no, detail.invoice_no))
                detail_error = True
                continue
            maps = sales_map.get(invoice_norm, [])
            if len(maps) != 1 or maps[0]["id_faktur"] is None:
                holds.append(Hold(detail.source_system, "DBayarSM", detail.stage_schema, detail.staging_id, detail.source_row_hash,
                                  "allocation_missing_unique_imported_sales_document", detail.receipt_no, detail.invoice_no,
                                  {"sales_document_map_count": len(maps)}))
                detail_error = True
                continue
            needed_faktur_ids.add(int(maps[0]["id_faktur"]))
        if not amount_equal(details_total, amount):
            holds.append(Hold(header.source_system, "HBayarSM", header.stage_schema, header.staging_id, header.source_row_hash,
                              "receipt_total_does_not_equal_allocation_total", header.receipt_no,
                              details={"receipt_amount": amount, "allocation_total": details_total}))
            detail_error = True
        if detail_error:
            continue
        candidate_raw.append((header, receipt_norm, receipt_date, customer_code, mapped_customer, amount, payment_type, receipt_details))

    invoice_context = load_target_invoice_context(cursor, needed_faktur_ids)
    plans: list[ReceiptPlan] = []
    batch_invoice_amounts: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    uncommitted: list[tuple[ReceiptPlan, dict[int, Decimal]]] = []

    for header, receipt_norm, receipt_date, customer_code, mapped_customer, amount, payment_type, receipt_details in candidate_raw:
        allocations: list[AllocationPlan] = []
        plan_error = False
        plan_invoice_amounts: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
        for detail in receipt_details:
            invoice_norm = norm(detail.invoice_no)
            assert invoice_norm is not None
            mapping = sales_map[invoice_norm][0]
            target = invoice_context.get(int(mapping["id_faktur"]))
            detail_amount, _ = parse_amount(detail.amount_raw, "allocation_amount")
            assert detail_amount is not None
            if not target:
                holds.append(Hold(detail.source_system, "DBayarSM", detail.stage_schema, detail.staging_id, detail.source_row_hash,
                                  "mapped_invoice_missing_in_public", detail.receipt_no, detail.invoice_no))
                plan_error = True
                continue
            errors: list[str] = []
            if target["id_sales_order"] != mapping["id_sales_order"]:
                errors.append("sales_document_map_invoice_order_mismatch")
            if target["jenis_faktur"] != "penjualan":
                errors.append("target_invoice_not_sales")
            if target["sales_faktur_count"] != 1:
                errors.append("target_sales_order_not_single_sales_invoice")
            if target["id_customer"] != mapped_customer:
                errors.append("target_invoice_customer_mismatch")
            if target["id_cabang"] != source_context[header.source_system]["target_branch_id"]:
                errors.append("target_invoice_branch_scope_mismatch")
            if target["id_sales"] is None:
                errors.append("target_invoice_sales_missing")
            if str(target["status_faktur"] or "") == "9":
                errors.append("target_invoice_cancelled")
            if errors:
                holds.append(Hold(detail.source_system, "DBayarSM", detail.stage_schema, detail.staging_id, detail.source_row_hash,
                                  errors[0], detail.receipt_no, detail.invoice_no, {"all_errors": errors}))
                plan_error = True
                continue
            allocations.append(
                AllocationPlan(
                    detail, str(mapping["source_table"]), int(mapping["id_sales_order"]), int(mapping["id_faktur"]),
                    int(target["id_sales"]), detail_amount,
                )
            )
            plan_invoice_amounts[int(mapping["id_faktur"])] += detail_amount
        payload_hash = stable_hash(
            {
                "source_system": header.source_system,
                "receipt": receipt_norm,
                "header_row_hash": header.source_row_hash,
                "receipt_date": receipt_date,
                "customer": norm(customer_code),
                "amount": amount,
                "payment_type": payment_type,
                "allocations": sorted(
                    [
                        {"row_hash": item.detail.source_row_hash, "invoice": norm(item.detail.invoice_no), "amount": item.amount,
                         "sales_table": item.source_sales_table}
                        for item in allocations
                    ],
                    key=lambda item: (str(item["invoice"]), str(item["row_hash"])),
                ),
            }
        )
        if plan_error:
            holds.append(Hold(header.source_system, "HBayarSM", header.stage_schema, header.staging_id, header.source_row_hash,
                              "receipt_has_ineligible_allocation", header.receipt_no))
            continue
        plan = ReceiptPlan(
            header, clean(header.receipt_no) or receipt_norm, receipt_norm, receipt_date, customer_code,
            norm(customer_code) or "", mapped_customer, amount, payment_type, payload_hash, tuple(allocations),
        )
        prior = existing.get((plan.header.source_system, plan.receipt_no_norm))
        if prior:
            if prior["payload_hash"] != plan.payload_hash or not amount_equal(prior["amount"], plan.amount):
                holds.append(Hold(plan.header.source_system, "HBayarSM", plan.header.stage_schema, plan.header.staging_id,
                                  plan.header.source_row_hash, "existing_imported_receipt_payload_mismatch", plan.receipt_no,
                                  details={"existing_receipt_id": prior["id"]}))
            # Equal existing receipt is idempotently reported by main; do not
            # consume invoice capacity again.
            else:
                plans.append(plan)
            continue
        for faktur_id, value in plan_invoice_amounts.items():
            batch_invoice_amounts[faktur_id] += value
        uncommitted.append((plan, plan_invoice_amounts))

    for plan, plan_invoice_amounts in uncommitted:
        overpaid = False
        for faktur_id, import_amount in plan_invoice_amounts.items():
            target = invoice_context[faktur_id]
            available = max(target["total_tagihan"] - target["nominal_retur"] - target["total_setoran"] - target["total_voucher"], Decimal("0"))
            if batch_invoice_amounts[faktur_id] > available:
                overpaid = True
                for allocation in plan.allocations:
                    if allocation.id_faktur == faktur_id:
                        holds.append(Hold(allocation.detail.source_system, "DBayarSM", allocation.detail.stage_schema,
                                          allocation.detail.staging_id, allocation.detail.source_row_hash,
                                          "batch_payment_exceeds_current_invoice_balance", allocation.detail.receipt_no,
                                          allocation.detail.invoice_no,
                                          {"available_balance": available, "batch_import_amount": batch_invoice_amounts[faktur_id]}))
        if overpaid:
            holds.append(Hold(plan.header.source_system, "HBayarSM", plan.header.stage_schema, plan.header.staging_id,
                              plan.header.source_row_hash, "receipt_would_overpay_invoice", plan.receipt_no))
        else:
            plans.append(plan)
    return plans, holds


def current_target_balance_locked(cursor, invoice_ids: Iterable[int]) -> dict[int, dict[str, Any]]:
    ids = sorted({int(item) for item in invoice_ids})
    if not ids:
        return {}
    has_voucher_usage = bool(table_columns(cursor, "public", "payment_voucher_usage"))
    voucher_sql = (
        """
        LEFT JOIN (
            SELECT id_sales_order, COALESCE(SUM(nominal), 0) AS total_voucher
            FROM public.payment_voucher_usage
            WHERE status = 1
            GROUP BY id_sales_order
        ) pvu ON pvu.id_sales_order = so.id
        """
        if has_voucher_usage
        else ""
    )
    voucher_select = "COALESCE(pvu.total_voucher, 0)" if has_voucher_usage else "0::numeric"
    cursor.execute(
        f"""
        SELECT f.id, f.id_sales_order, f.jenis_faktur, f.status_faktur,
               COALESCE(f.total_penjualan, so.total_order, 0)::numeric,
               COALESCE(f.nominal_retur, 0)::numeric,
               COALESCE(sc.total_setoran, 0)::numeric,
               {voucher_select}::numeric,
               (
                   SELECT COUNT(*)
                   FROM public.faktur sales_faktur
                   WHERE sales_faktur.id_sales_order = so.id
                     AND sales_faktur.jenis_faktur = 'penjualan'
               ),
               pl.id_customer, pl.id_sales
        FROM public.faktur f
        JOIN public.sales_order so ON so.id = f.id_sales_order
        JOIN public.plafon pl ON pl.id = so.id_plafon
        LEFT JOIN (
            SELECT id_sales_order, COALESCE(SUM(jumlah_setoran), 0) AS total_setoran
            FROM public.setoran_customer
            WHERE id_sales_order = ANY(
                SELECT id_sales_order FROM public.faktur WHERE id = ANY(%s)
            )
            GROUP BY id_sales_order
        ) sc ON sc.id_sales_order = so.id
        {voucher_sql}
        WHERE f.id = ANY(%s)
        ORDER BY so.id, f.id
        FOR UPDATE OF so, f
        """,
        (ids, ids),
    )
    return {
        int(row[0]): {
            "id_faktur": int(row[0]), "id_sales_order": int(row[1]), "jenis_faktur": clean(row[2]),
            "status_faktur": row[3], "total_tagihan": Decimal(row[4] or 0),
            "nominal_retur": Decimal(row[5] or 0), "total_setoran": Decimal(row[6] or 0),
            "total_voucher": Decimal(row[7] or 0),
            "sales_faktur_count": int(row[8] or 0),
            "id_customer": int(row[9]) if row[9] is not None else None,
            "id_sales": int(row[10]) if row[10] is not None else None,
        }
        for row in cursor.fetchall()
    }


def ensure_payment_plan_still_safe(cursor, plans: list[ReceiptPlan]) -> None:
    ids = [allocation.id_faktur for plan in plans for allocation in plan.allocations]
    targets = current_target_balance_locked(cursor, ids)
    import_totals: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    for plan in plans:
        for allocation in plan.allocations:
            import_totals[allocation.id_faktur] += allocation.amount
    for faktur_id, import_total in sorted(import_totals.items()):
        target = targets.get(faktur_id)
        if not target or target["jenis_faktur"] != "penjualan" or str(target["status_faktur"] or "") == "9":
            raise ValidationError(f"Target faktur {faktur_id} berubah/tidak lagi eligible saat apply")
        if target["sales_faktur_count"] != 1:
            raise ValidationError(
                f"Target sales order untuk faktur {faktur_id} tidak lagi memiliki tepat satu faktur penjualan; "
                "setoran_customer bersifat per sales_order sehingga apply dibatalkan."
            )
        available = max(target["total_tagihan"] - target["nominal_retur"] - target["total_setoran"] - target["total_voucher"], Decimal("0"))
        if import_total > available:
            raise ValidationError(
                f"Apply dibatalkan: pembayaran batch {import_total} melebihi sisa target faktur {faktur_id} ({available}). "
                "Jalankan dry-run baru; tidak ada data yang ditulis."
            )


def insert_payment_run(cursor, batch_id: str, bdm_sales: StageMetadata, tmp_sales: StageMetadata,
                       bdm_payment: StageMetadata, tmp_payment: StageMetadata, plans: list[ReceiptPlan], holds: list[Hold]) -> None:
    cursor.execute(
        f"""
        INSERT INTO {qtable(REGISTRY_SCHEMA, 'active_payment_import_run')} (
            batch_id, import_mode,
            bdm_sales_stage_schema, tmp_sales_stage_schema,
            bdm_payment_stage_schema, tmp_payment_stage_schema,
            bdm_sales_stage_run_id, tmp_sales_stage_run_id,
            bdm_payment_stage_run_id, tmp_payment_stage_run_id,
            bdm_consistency_mode, tmp_consistency_mode,
            bdm_maintenance_window_id, tmp_maintenance_window_id,
            bdm_maintenance_freeze_attested, tmp_maintenance_freeze_attested,
            bdm_maintenance_freeze_confirmed_at, tmp_maintenance_freeze_confirmed_at,
            bdm_source_transaction_isolation, tmp_source_transaction_isolation,
            bdm_source_lock_timeout_ms, tmp_source_lock_timeout_ms,
            source_receipts, source_allocations, inserted_receipts, inserted_allocations,
            unchanged_receipts, held_rows, hold_summary, applied_by
        ) VALUES (
            %s, 'receivable_only', %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, 0, 0, 0, %s, %s::jsonb, %s
        )
        """,
        (
            batch_id, bdm_sales.schema, tmp_sales.schema, bdm_payment.schema, tmp_payment.schema,
            bdm_sales.run_id, tmp_sales.run_id, bdm_payment.run_id, tmp_payment.run_id,
            bdm_payment.consistency_mode, tmp_payment.consistency_mode,
            bdm_payment.maintenance_window_id, tmp_payment.maintenance_window_id,
            bdm_payment.maintenance_freeze_attested, tmp_payment.maintenance_freeze_attested,
            bdm_payment.maintenance_freeze_confirmed_at, tmp_payment.maintenance_freeze_confirmed_at,
            bdm_payment.source_transaction_isolation, tmp_payment.source_transaction_isolation,
            bdm_payment.source_lock_timeout_ms, tmp_payment.source_lock_timeout_ms,
            len(plans), sum(len(plan.allocations) for plan in plans), len(holds),
            json.dumps(Counter(hold.reason for hold in holds), sort_keys=True),
            os.getenv("USER") or "migration-operator",
        ),
    )


def write_payment_holds(cursor, batch_id: str, holds: Iterable[Hold]) -> None:
    rows = [
        (
            batch_id, hold.source_system, hold.source_table, hold.stage_schema, hold.staging_id,
            hold.source_row_hash, hold.receipt_no, hold.invoice_no, hold.reason, Json(json_safe(hold.details)),
        )
        for hold in holds
    ]
    if not rows:
        return
    execute_values(
        cursor,
        f"""
        INSERT INTO {qtable(REGISTRY_SCHEMA, 'active_payment_hold')} (
            import_batch_id, source_system, source_table, source_stage_schema, source_staging_id,
            source_row_hash, source_receipt_no, source_invoice_no, hold_reason, details
        ) VALUES %s
        ON CONFLICT (import_batch_id, source_system, source_table, source_stage_schema, source_staging_id, hold_reason)
        DO NOTHING
        """,
        rows,
    )


def apply_payment_plans(cursor, batch_id: str, plans: list[ReceiptPlan]) -> dict[str, int]:
    existing = existing_payment_receipts(cursor)
    fresh = [plan for plan in plans if (plan.header.source_system, plan.receipt_no_norm) not in existing]
    unchanged = [plan for plan in plans if (plan.header.source_system, plan.receipt_no_norm) in existing]
    for plan in unchanged:
        current = existing[(plan.header.source_system, plan.receipt_no_norm)]
        if current["payload_hash"] != plan.payload_hash:
            raise ValidationError(f"Receipt existing {plan.receipt_no} berubah saat apply; batalkan batch.")
    ensure_payment_plan_still_safe(cursor, fresh)
    inserted_receipts = 0
    inserted_allocations = 0
    affected_order_ids: set[int] = set()
    affected_invoice_ids: set[int] = set()
    for plan in fresh:
        cursor.execute(
            f"""
            INSERT INTO {qtable(REGISTRY_SCHEMA, 'active_payment_receipt')} (
                import_batch_id, source_system, source_header_table, source_stage_schema, source_stage_run_id,
                source_staging_id, source_row_hash, source_receipt_no, source_receipt_no_norm,
                source_receipt_date, source_customer_code, source_customer_code_norm, id_customer,
                receipt_total, payment_type, source_no_bukti, source_keterangan, source_payload_hash
            ) VALUES (
                %s, %s, 'HBayarSM', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            ) RETURNING id
            """,
            (
                batch_id, plan.header.source_system, plan.header.stage_schema, plan.header.stage_run_id,
                plan.header.staging_id, plan.header.source_row_hash, plan.receipt_no, plan.receipt_no_norm,
                plan.receipt_date, plan.customer_code, plan.customer_code_norm, plan.id_customer,
                plan.amount, plan.payment_type, plan.header.no_bukti, plan.header.keterangan, plan.payload_hash,
            ),
        )
        receipt_id = int(cursor.fetchone()[0])
        inserted_receipts += 1
        for allocation in plan.allocations:
            # is_rekap=1 keeps an imported historical settlement out of the
            # current sales recap queue.  It deliberately has no `setoran`
            # row because cash/bank finalisation and accounting journal source
            # accounts are not present in the legacy allocation payload.
            cursor.execute(
                """
                INSERT INTO public.setoran_customer (
                    id_sales, id_sales_order, jumlah_setoran, tipe_setoran, tanggal_input, is_rekap
                ) VALUES (%s, %s, %s, %s, %s, 1)
                RETURNING id
                """,
                (allocation.id_sales, allocation.id_sales_order, allocation.amount, plan.payment_type, plan.receipt_date),
            )
            id_setoran_customer = int(cursor.fetchone()[0])
            cursor.execute(
                f"""
                INSERT INTO {qtable(REGISTRY_SCHEMA, 'active_payment_allocation')} (
                    id_active_payment_receipt, source_system, source_detail_table, source_stage_schema,
                    source_stage_run_id, source_staging_id, source_row_hash, source_invoice_no,
                    source_invoice_no_norm, source_sales_table, id_sales_order, id_faktur,
                    id_setoran_customer, allocation_amount
                ) VALUES (
                    %s, %s, 'DBayarSM', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    receipt_id, allocation.detail.source_system, allocation.detail.stage_schema, allocation.detail.stage_run_id,
                    allocation.detail.staging_id, allocation.detail.source_row_hash, clean(allocation.detail.invoice_no),
                    norm(allocation.detail.invoice_no), allocation.source_sales_table, allocation.id_sales_order,
                    allocation.id_faktur, id_setoran_customer, allocation.amount,
                ),
            )
            inserted_allocations += 1
            affected_order_ids.add(allocation.id_sales_order)
            affected_invoice_ids.add(allocation.id_faktur)
        cursor.execute(
            f"""
            INSERT INTO {qtable(REGISTRY_SCHEMA, 'active_payment_action')} (
                import_batch_id, source_system, source_receipt_no, source_receipt_no_norm,
                action, id_active_payment_receipt, allocation_count, amount, details
            ) VALUES (%s, %s, %s, %s, 'insert_receivable_payment', %s, %s, %s, %s::jsonb)
            """,
            (batch_id, plan.header.source_system, plan.receipt_no, plan.receipt_no_norm, receipt_id,
             len(plan.allocations), plan.amount,
             json.dumps({"cash_bank_finalization": "not_imported", "is_rekap": 1}, sort_keys=True)),
        )
    for plan in unchanged:
        current = existing[(plan.header.source_system, plan.receipt_no_norm)]
        cursor.execute(
            f"""
            INSERT INTO {qtable(REGISTRY_SCHEMA, 'active_payment_action')} (
                import_batch_id, source_system, source_receipt_no, source_receipt_no_norm,
                action, id_active_payment_receipt, allocation_count, amount, details
            ) VALUES (%s, %s, %s, %s, 'unchanged_existing_payment', %s, %s, %s, %s::jsonb)
            """,
            (batch_id, plan.header.source_system, plan.receipt_no, plan.receipt_no_norm, current["id"],
             len(plan.allocations), plan.amount, json.dumps({"payload_hash_verified": True}, sort_keys=True)),
        )
    if affected_order_ids:
        # Same settlement formula as Pembayaran._sync_faktur_payment_status:
        # invoice total - returns - payments - active voucher use.
        has_voucher_usage = bool(table_columns(cursor, "public", "payment_voucher_usage"))
        voucher_sql = (
            """
            LEFT JOIN (
                SELECT id_sales_order, COALESCE(SUM(nominal), 0) AS total_voucher
                FROM public.payment_voucher_usage
                WHERE status = 1
                GROUP BY id_sales_order
            ) pvu ON pvu.id_sales_order = f.id_sales_order
            """
            if has_voucher_usage else ""
        )
        voucher_value = "COALESCE(pvu.total_voucher, 0)" if has_voucher_usage else "0"
        cursor.execute(
            f"""
            WITH payments AS (
                SELECT id_sales_order, COALESCE(SUM(jumlah_setoran), 0) AS total_payment
                FROM public.setoran_customer
                WHERE id_sales_order = ANY(%s)
                GROUP BY id_sales_order
            )
            UPDATE public.faktur f
            SET status_faktur = CASE
                WHEN COALESCE(f.total_penjualan, so.total_order, 0)
                     - COALESCE(f.nominal_retur, 0)
                     - COALESCE(payments.total_payment, 0)
                     - {voucher_value} <= 0.5 THEN 3
                ELSE 2
            END
            FROM public.sales_order so
            LEFT JOIN payments ON payments.id_sales_order = f.id_sales_order
            {voucher_sql}
            WHERE f.id_sales_order = so.id
              AND f.id_sales_order = ANY(%s)
              AND f.id = ANY(%s)
              AND f.jenis_faktur = 'penjualan'
            """,
            (sorted(affected_order_ids), sorted(affected_order_ids), sorted(affected_invoice_ids)),
        )
    cursor.execute(
        f"""
        UPDATE {qtable(REGISTRY_SCHEMA, 'active_payment_import_run')}
        SET inserted_receipts = %s,
            inserted_allocations = %s,
            unchanged_receipts = %s
        WHERE batch_id = %s
        """,
        (inserted_receipts, inserted_allocations, len(unchanged), batch_id),
    )
    return {"inserted_receipts": inserted_receipts, "inserted_allocations": inserted_allocations, "unchanged_receipts": len(unchanged)}


def return_preflight(
    cursor,
    *,
    return_meta: StageMetadata,
    sales_meta: StageMetadata,
    customer_maps: dict[tuple[str, str], int],
) -> tuple[list[ReturnRow], list[Hold], int]:
    headers = (
        source_return_rows(cursor, schema=return_meta.schema, source_system=return_meta.source_system,
                           run_id=return_meta.run_id, table="hretursm", header=True)
        + source_return_rows(cursor, schema=return_meta.schema, source_system=return_meta.source_system,
                             run_id=return_meta.run_id, table="hretursmandroid", header=True)
    )
    details = (
        source_return_rows(cursor, schema=return_meta.schema, source_system=return_meta.source_system,
                           run_id=return_meta.run_id, table="dretursm", header=False)
        + source_return_rows(cursor, schema=return_meta.schema, source_system=return_meta.source_system,
                             run_id=return_meta.run_id, table="dretursmandroid", header=False)
    )
    sales_map = load_sales_document_map(cursor, return_meta.source_system, sales_meta.schema)
    holds: list[Hold] = []
    reviewable_headers = 0
    header_numbers = {norm(item.return_no) for item in headers if norm(item.return_no)}
    for header in headers:
        errors: list[str] = []
        if not norm(header.return_no):
            errors.append("blank_return_number")
        if not norm(header.invoice_no):
            errors.append("blank_original_invoice_number")
        if not norm(header.customer_code):
            errors.append("blank_customer_code")
        elif (header.source_system, norm(header.customer_code) or "") not in customer_maps:
            errors.append("missing_exact_customer_map")
        maps = sales_map.get(norm(header.invoice_no) or "", [])
        if len(maps) != 1 or not maps or maps[0]["id_faktur"] is None:
            errors.append("missing_unique_imported_sales_document")
        if not errors:
            reviewable_headers += 1
        # Even fully referenced headers must be held: the source does not
        # identify return lifecycle, Good/Bad, UOM, or CN/stock policy.
        holds.append(Hold(
            header.source_system, header.source_table, header.stage_schema, header.staging_id, header.source_row_hash,
            errors[0] if errors else "return_requires_explicit_lifecycle_uom_good_bad_credit_note_policy",
            receipt_no=header.return_no, invoice_no=header.invoice_no,
            details={"all_errors": errors, "manual_lifecycle_candidate": not errors},
        ))
    for detail in details:
        errors: list[str] = []
        if not norm(detail.return_no):
            errors.append("blank_return_number")
        elif norm(detail.return_no) not in header_numbers:
            errors.append("return_detail_without_header")
        if not norm(detail.sku):
            errors.append("blank_product_code")
        if not norm(detail.urut):
            errors.append("blank_return_line_number")
        holds.append(Hold(
            detail.source_system, detail.source_table, detail.stage_schema, detail.staging_id, detail.source_row_hash,
            errors[0] if errors else "return_requires_exact_uom_good_bad_and_sales_detail_policy",
            receipt_no=detail.return_no, invoice_no=detail.invoice_no,
            details={"all_errors": errors},
        ))
    return headers + details, holds, reviewable_headers


def write_return_preflight(cursor, batch_id: str, bdm_sales: StageMetadata, tmp_sales: StageMetadata,
                           bdm_return: StageMetadata, tmp_return: StageMetadata,
                           source_rows: list[ReturnRow], reviewable_headers: int, holds: list[Hold]) -> None:
    headers = sum(1 for item in source_rows if item.source_table in ("HReturSM", "HReturSMAndroid"))
    details = len(source_rows) - headers
    cursor.execute(
        f"""
        INSERT INTO {qtable(REGISTRY_SCHEMA, 'active_return_preflight_run')} (
            batch_id, bdm_sales_stage_schema, tmp_sales_stage_schema,
            bdm_return_stage_schema, tmp_return_stage_schema,
            bdm_sales_stage_run_id, tmp_sales_stage_run_id,
            bdm_return_stage_run_id, tmp_return_stage_run_id,
            source_headers, source_details, eligible_for_manual_lifecycle_review,
            held_rows, hold_summary
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        """,
        (
            batch_id, bdm_sales.schema, tmp_sales.schema, bdm_return.schema, tmp_return.schema,
            bdm_sales.run_id, tmp_sales.run_id, bdm_return.run_id, tmp_return.run_id,
            headers, details, reviewable_headers, len(holds), json.dumps(Counter(item.reason for item in holds), sort_keys=True),
        ),
    )
    rows = [
        (batch_id, hold.source_system, hold.source_table, hold.stage_schema, hold.staging_id,
         hold.source_row_hash, hold.receipt_no, hold.invoice_no, hold.reason, Json(json_safe(hold.details)))
        for hold in holds
    ]
    if rows:
        execute_values(
            cursor,
            f"""
            INSERT INTO {qtable(REGISTRY_SCHEMA, 'active_return_preflight_hold')} (
                import_batch_id, source_system, source_table, source_stage_schema, source_staging_id,
                source_row_hash, source_return_no, source_invoice_no, hold_reason, details
            ) VALUES %s
            ON CONFLICT (import_batch_id, source_system, source_table, source_stage_schema, source_staging_id, hold_reason)
            DO NOTHING
            """,
            rows,
        )


def report_plans(plans: list[ReceiptPlan], holds: list[Hold], return_summary: dict[str, Any]) -> dict[str, Any]:
    unchanged_possible = 0
    return {
        "payment_policy": {
            "active_scope": "receivable_only",
            "creates_public_setoran_customer": True,
            "creates_public_setoran": False,
            "posts_cash_bank_journal": False,
            "updates_plafon_sisa_bon": False,
            "supplemental_pembayaran": "held_pending_status_and_method_policy",
        },
        "payment": {
            "eligible_receipts": len(plans),
            "eligible_allocations": sum(len(plan.allocations) for plan in plans),
            "eligible_amount": str(sum((plan.amount for plan in plans), Decimal("0"))),
            "hold_rows": len(holds),
            "hold_summary": dict(sorted(Counter(hold.reason for hold in holds).items())),
            "sample_receipts": [
                {
                    "source_system": plan.header.source_system,
                    "receipt": plan.receipt_no,
                    "date": plan.receipt_date.isoformat(),
                    "amount": str(plan.amount),
                    "allocations": len(plan.allocations),
                }
                for plan in plans[:10]
            ],
            "unchanged_possible": unchanged_possible,
        },
        "returns": return_summary,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    # Keep the pure parser/gate tests runnable without database-stage input.
    # All required stage arguments remain mandatory for a real dry-run/apply.
    if "--self-test" in argv:
        return argparse.Namespace(self_test=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bdm-sales-schema", required=True)
    parser.add_argument("--tmp-sales-schema", required=True)
    parser.add_argument("--bdm-payment-return-schema", required=True)
    parser.add_argument("--tmp-payment-return-schema", required=True)
    parser.add_argument("--batch-id", default="active_payment_return_final_20260830")
    parser.add_argument("--output", help="Path JSON report; stdout remains concise.")
    parser.add_argument("--apply-payments", action="store_true", help="Apply exact receivable payments after final staging validation.")
    parser.add_argument(
        "--confirm-active-payment-receivable-import",
        action="store_true",
        help="Required together with --apply-payments. Does not authorize cash/bank finalisation.",
    )
    parser.add_argument(
        "--record-return-preflight",
        action="store_true",
        help="Persist only return preflight holds in registry; never writes public return/stock tables.",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if not BATCH_RE.fullmatch(args.batch_id):
        parser.error("--batch-id hanya boleh huruf kecil, angka, titik, strip, atau underscore (3-120 karakter).")
    for value in (args.bdm_sales_schema, args.tmp_sales_schema, args.bdm_payment_return_schema, args.tmp_payment_return_schema):
        if not IDENT_RE.fullmatch(value):
            parser.error(f"schema PostgreSQL tidak aman: {value!r}")
    if args.apply_payments and not args.confirm_active_payment_receivable_import:
        parser.error("--apply-payments memerlukan --confirm-active-payment-receivable-import")
    return args


def run_self_test() -> None:
    assert parse_amount("100.00", "amount") == (Decimal("100.00"), None)
    assert parse_amount("10,00", "amount")[1] == "invalid_amount_format"
    assert parse_source_date("2026-08-30 12:20:00")[0] == date(2026, 8, 30)
    header = PaymentHeader("bdm_solo_dist", "s", 1, 1, "h", "K1", "2026-08-30", "C1", "100", "0", "0", "100", None, None, None, "0")
    assert canonical_payment_type(header) == (Decimal("100.00"), 1, None)
    multi = PaymentHeader("bdm_solo_dist", "s", 1, 1, "h", "K1", "2026-08-30", "C1", "50", "50", "0", "100", None, None, None, "0")
    assert canonical_payment_type(multi)[2] == "receipt_payment_method_not_single_exact_type"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.self_test:
        run_self_test()
        print("self_test=ok")
        return 0
    conn = connect_from_env()
    try:
        if args.apply_payments:
            # PostgreSQL only accepts this setting before the first statement
            # in the transaction; later balance reads are protected by the
            # serializable transaction plus deterministic invoice row locks.
            conn.set_session(isolation_level="SERIALIZABLE")
        conn.autocommit = False
        with conn.cursor() as cursor:
            if not args.apply_payments and not args.record_return_preflight:
                # Enforce the default review path at the database level.  The
                # dry-run must stay read-only even if a later code change
                # accidentally adds DML before its final rollback.
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            assert_public_columns(cursor, "setoran_customer", {"id", "id_sales", "id_sales_order", "jumlah_setoran", "tipe_setoran", "tanggal_input", "is_rekap"})
            assert_public_columns(cursor, "faktur", {"id", "id_sales_order", "jenis_faktur", "status_faktur", "total_penjualan", "nominal_retur"})
            assert_public_columns(cursor, "sales_order", {"id", "id_plafon", "total_order", "id_cabang"})
            assert_public_columns(cursor, "plafon", {"id", "id_customer", "id_principal", "id_sales"})
            bdm_sales = read_stage_metadata(cursor, schema=args.bdm_sales_schema, source_system="bdm_solo_dist",
                                             required_tables=("hjualsm", "djualsm", "hjualsmandroid", "djualsmandroid"))
            tmp_sales = read_stage_metadata(cursor, schema=args.tmp_sales_schema, source_system="tmp_solo_dist",
                                             required_tables=("hjualsm", "djualsm", "hjualsmandroid", "djualsmandroid"))
            bdm_payment = read_stage_metadata(cursor, schema=args.bdm_payment_return_schema, source_system="bdm_solo_dist",
                                               required_tables=tuple(PAYMENT_REQUIRED_COLUMNS) + tuple(RETURN_REQUIRED_COLUMNS))
            tmp_payment = read_stage_metadata(cursor, schema=args.tmp_payment_return_schema, source_system="tmp_solo_dist",
                                               required_tables=tuple(PAYMENT_REQUIRED_COLUMNS) + tuple(RETURN_REQUIRED_COLUMNS))
            assert_stage_columns(cursor, bdm_payment.schema, PAYMENT_REQUIRED_COLUMNS)
            assert_stage_columns(cursor, tmp_payment.schema, PAYMENT_REQUIRED_COLUMNS)
            assert_stage_columns(cursor, bdm_payment.schema, RETURN_REQUIRED_COLUMNS)
            assert_stage_columns(cursor, tmp_payment.schema, RETURN_REQUIRED_COLUMNS)
            validate_selected_stages(
                bdm_sales, tmp_sales, bdm_payment, tmp_payment,
                apply=args.apply_payments or args.record_return_preflight,
            )
            source_context = load_source_context(cursor)
            customer_maps = load_customer_maps(cursor)
            target_customers = load_target_customers(cursor)
            bdm_return_refs = load_return_invoice_references(cursor, bdm_payment.schema, "bdm_solo_dist")
            tmp_return_refs = load_return_invoice_references(cursor, tmp_payment.schema, "tmp_solo_dist")
            bdm_plans, bdm_holds = build_payment_plan(
                cursor, metadata=bdm_payment, sales_metadata=bdm_sales, customer_maps=customer_maps,
                target_customers=target_customers, source_context=source_context, return_invoice_refs=bdm_return_refs,
            )
            tmp_plans, tmp_holds = build_payment_plan(
                cursor, metadata=tmp_payment, sales_metadata=tmp_sales, customer_maps=customer_maps,
                target_customers=target_customers, source_context=source_context, return_invoice_refs=tmp_return_refs,
            )
            bdm_return_rows, bdm_return_holds, bdm_reviewable = return_preflight(
                cursor, return_meta=bdm_payment, sales_meta=bdm_sales, customer_maps=customer_maps,
            )
            tmp_return_rows, tmp_return_holds, tmp_reviewable = return_preflight(
                cursor, return_meta=tmp_payment, sales_meta=tmp_sales, customer_maps=customer_maps,
            )
            plans = bdm_plans + tmp_plans
            holds = bdm_holds + tmp_holds
            return_holds = bdm_return_holds + tmp_return_holds
            return_summary = {
                "automatic_active_import": False,
                "reason": "requires_explicit_return_lifecycle_uom_good_bad_credit_note_and_stock_policy",
                "source_headers": sum(1 for row in bdm_return_rows + tmp_return_rows if row.source_table in ("HReturSM", "HReturSMAndroid")),
                "source_details": sum(1 for row in bdm_return_rows + tmp_return_rows if row.source_table in ("DReturSM", "DReturSMAndroid")),
                "manual_lifecycle_candidates": bdm_reviewable + tmp_reviewable,
                "hold_rows": len(return_holds),
                "hold_summary": dict(sorted(Counter(hold.reason for hold in return_holds).items())),
            }
            report = report_plans(plans, holds, return_summary)
            report["staging"] = {
                "bdm_sales": json_safe(bdm_sales.__dict__), "tmp_sales": json_safe(tmp_sales.__dict__),
                "bdm_payment_return": json_safe(bdm_payment.__dict__), "tmp_payment_return": json_safe(tmp_payment.__dict__),
            }
            report["mode"] = "apply-payments" if args.apply_payments else "dry-run"
            if args.apply_payments or args.record_return_preflight:
                assert_registry_tables(cursor, PAYMENT_DDL_TABLES if args.apply_payments else RETURN_DDL_TABLES)
            if args.apply_payments:
                assert_no_enabled_user_triggers(cursor, ("setoran_customer", "faktur"))
                cursor.execute("SET LOCAL lock_timeout = '5s'")
                cursor.execute("SET LOCAL statement_timeout = '120s'")
                cursor.execute("SELECT pg_advisory_xact_lock(hashtext('migration_bdm_tmp_202608.active_payment_receivable'))")
                insert_payment_run(cursor, args.batch_id, bdm_sales, tmp_sales, bdm_payment, tmp_payment, plans, holds)
                write_payment_holds(cursor, args.batch_id, holds)
                applied = apply_payment_plans(cursor, args.batch_id, plans)
                report["applied"] = applied
            if args.record_return_preflight:
                assert_registry_tables(cursor, RETURN_DDL_TABLES)
                cursor.execute("SET LOCAL lock_timeout = '5s'")
                write_return_preflight(cursor, args.batch_id, bdm_sales, tmp_sales, bdm_payment, tmp_payment,
                                       bdm_return_rows + tmp_return_rows, bdm_reviewable + tmp_reviewable, return_holds)
                report["return_preflight_recorded"] = True
            if args.apply_payments or args.record_return_preflight:
                conn.commit()
            else:
                conn.rollback()
            report_text = json.dumps(json_safe(report), indent=2, sort_keys=True)
            if args.output:
                with open(args.output, "w", encoding="utf-8") as handle:
                    handle.write(report_text + "\n")
            print(f"mode={report['mode']}")
            print(f"payment_eligible_receipts={report['payment']['eligible_receipts']}")
            print(f"payment_eligible_allocations={report['payment']['eligible_allocations']}")
            print(f"payment_hold_rows={report['payment']['hold_rows']}")
            print(f"return_hold_rows={report['returns']['hold_rows']}")
            if args.output:
                print(f"report={args.output}")
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
