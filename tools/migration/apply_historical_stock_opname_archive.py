#!/usr/bin/env python3
"""Prepare or archive legacy BDM/TMP ``StokOpnameAndroid`` safely.

The legacy source is a physical count in the user-approved base/PCS unit.
It has no rack, batch, system-stock, Good/Bad, or historic-cost fields.
Accordingly this tool never writes ``public.stock_opname`` or
``public.stock_opname_detail``.  It archives only fully mapped historical
records in ``migration_bdm_tmp_202608`` and cannot create an inventory-ledger
movement.

Safety rules:

* Dry-run is the default.  ``--apply`` additionally requires
  ``--confirm-historical-archive``.
* ``--apply`` rejects every read-committed/preview staging run.  It accepts a
  completed SQL Server SNAPSHOT pair, or the explicit, matching
  ``maintenance_freeze_serializable`` pair with recorded freeze attestation.
* Customer, principal, sales, and product require committed source-aware maps.
  An ambiguous principal has no map and is held; it is never guessed.
* A visit is all-or-nothing.  If one line under the same source visit cannot be
  safely interpreted, the whole visit remains held instead of archiving an
  incomplete stock opname.
* Quantities are exact non-negative integers in PCS/base.  CT + PCS is only a
  display snapshot after the exact approved product-UOM mapping proves one
  base UOM and one CT-level UOM.  Missing/ambiguous UOM merely leaves the
  display as PCS; it never changes the source quantity.
* Existing archive records are append-only.  A source payload that differs
  from an already archived visit is held rather than updated.

The archive DDL must be installed first:

    psql -v ON_ERROR_STOP=1 -f \\
      tools/migration/20260828_create_historical_stock_opname_archive.sql

Dry-run against preview is allowed for review only:

    python3 tools/migration/apply_historical_stock_opname_archive.py \\
      --bdm-schema legacy_bdm_solo_stock_opname_preview_20260827 \\
      --tmp-schema legacy_tmp_solo_stock_opname_preview_20260827

After final snapshot staging (or an attested source write-freeze staging), a
PostgreSQL backup, and review of the dry-run:

    python3 tools/migration/apply_historical_stock_opname_archive.py \\
      --bdm-schema <bdm_final_schema> \\
      --tmp-schema <tmp_final_schema> \\
      --batch-id stock_opname_historical_final_20260828 \\
      --apply --confirm-historical-archive

This program never connects to SQL Server and never performs a DML statement
against a ``public`` table.
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
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


REGISTRY_SCHEMA = "migration_bdm_tmp_202608"
SOURCE_SYSTEMS = ("bdm_solo_dist", "tmp_solo_dist")
DEFAULT_BATCH_ID = "historical_stock_opname_final_20260828"
SNAPSHOT_CONSISTENCY_MODE = "snapshot"
MAINTENANCE_FREEZE_CONSISTENCY_MODE = "maintenance_freeze_serializable"
IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
BATCH_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,119}$")
DECIMAL_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}"
    r"(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?$"
)
MAX_BIGINT = 9_223_372_036_854_775_807
# These two names are emitted by the source-staging tool and are deliberately
# prefixed with ``__``.  Keep them out of the general identifier grammar: the
# separate helper below is an allow-list so a user supplied schema/table name
# cannot use the exception to quote arbitrary identifiers.
STAGE_METADATA_TABLES = frozenset({"__stage_run", "__stage_manifest"})
STAGE_FIXED_COLUMNS = {
    "staging_id",
    "source_system",
    "target_company_id",
    "target_branch_id",
    "legacy_table",
    "source_row_hash",
    "imported_at",
}
SOURCE_REQUIRED_COLUMNS = {
    "id",
    "kodebarang",
    "kodecustomer",
    "stokopname",
    "tanggalinput",
    "kodesales",
    "kodeprinciple",
    "idkunjungan",
}
ARCHIVE_TABLES = (
    "historical_stock_opname_import_run",
    "historical_stock_opname_header",
    "historical_stock_opname_line",
    "historical_stock_opname_hold",
    "historical_stock_opname_action",
)


class ValidationError(RuntimeError):
    """Raised when an input cannot be safely interpreted."""


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
    source_rows: int
    source_columns: tuple[str, ...]


@dataclass(frozen=True)
class StageRow:
    source_system: str
    stage_schema: str
    stage_run_id: int
    staging_id: int
    source_row_hash: str
    source_record_id: str | None
    kodebarang: str | None
    kodecustomer: str | None
    stokopname_raw: str | None
    tanggalinput_raw: str | None
    kodesales: str | None
    tgladd_raw: str | None
    kodeprinciple: str | None
    idkunjungan: str | None


@dataclass(frozen=True)
class RawIdentity:
    source_record_id: str
    source_record_id_norm: str
    source_visit_id: str
    source_visit_id_norm: str
    source_customer_code: str
    source_customer_code_norm: str
    source_principal_code: str
    source_principal_code_norm: str
    source_sales_code: str
    source_sales_code_norm: str
    source_sku: str
    source_sku_norm: str
    opname_date: date
    qty_physical_pcs: int


@dataclass(frozen=True)
class MappingValue:
    target_id: int
    method: str


@dataclass(frozen=True)
class TargetCustomer:
    id_customer: int
    id_cabang: int | None


@dataclass(frozen=True)
class TargetPrincipal:
    id_principal: int
    id_perusahaan: int | None


@dataclass(frozen=True)
class TargetSales:
    id_sales: int
    id_principal: int | None


@dataclass(frozen=True)
class TargetProduct:
    id_produk: int
    id_principal: int | None


@dataclass(frozen=True)
class UomEntry:
    id_produk_uom: int
    kode: str
    level: int
    factor: int


@dataclass(frozen=True)
class UomDisplay:
    id_base_produk_uom: int | None
    base_uom_code: str | None
    id_ct_produk_uom: int | None
    ct_uom_code: str | None
    ct_factor: int | None
    status: str


@dataclass(frozen=True)
class ResolvedLine:
    row: StageRow
    identity: RawIdentity
    id_customer: int
    id_principal: int
    id_sales: int
    id_produk: int
    id_perusahaan: int
    id_cabang: int
    uom: UomDisplay

    @property
    def source_header_key(self) -> tuple[str, str, str, str, str, date]:
        return (
            self.row.source_system,
            self.identity.source_visit_id_norm,
            self.identity.source_customer_code_norm,
            self.identity.source_principal_code_norm,
            self.identity.source_sales_code_norm,
            self.identity.opname_date,
        )


@dataclass(frozen=True)
class Hold:
    row: StageRow
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HeaderPlan:
    source_system: str
    stage_schema: str
    stage_run_id: int
    identity: RawIdentity
    id_customer: int
    id_principal: int
    id_sales: int
    id_perusahaan: int
    id_cabang: int
    lines: tuple[ResolvedLine, ...]
    source_payload_hash: str

    @property
    def key(self) -> tuple[str, str, str, str, str, date]:
        first = self.identity
        return (
            self.source_system,
            first.source_visit_id_norm,
            first.source_customer_code_norm,
            first.source_principal_code_norm,
            first.source_sales_code_norm,
            first.opname_date,
        )

    @property
    def source_header_key_text(self) -> str:
        source_system, visit_id, customer, principal, sales, opname_date = self.key
        return "|".join((source_system, visit_id, customer, principal, sales, opname_date.isoformat()))


@dataclass(frozen=True)
class ExistingHeader:
    id_historical_stock_opname: int
    source_payload_hash: str
    source_record_count: int
    id_customer: int
    id_principal: int
    id_sales: int
    id_perusahaan: int
    id_cabang: int


@dataclass(frozen=True)
class ExistingLine:
    id_historical_stock_opname: int
    source_row_hash: str
    id_produk: int
    qty_physical_pcs: int


def ident(value: str) -> str:
    if not IDENT_RE.fullmatch(value):
        raise ValidationError(f"Identifier PostgreSQL tidak aman: {value!r}")
    return f'"{value}"'


def qtable(schema: str, table: str) -> str:
    return f"{ident(schema)}.{ident(table)}"


def stage_metadata_table(schema: str, table: str) -> str:
    """Return one of the two fixed staging metadata tables safely.

    ``ident`` intentionally rejects leading underscores for all externally
    supplied identifiers.  The staging writer uses two fixed metadata table
    names that begin with ``__``; accepting only this closed allow-list keeps
    that safety boundary intact.
    """

    if table not in STAGE_METADATA_TABLES:
        raise ValidationError(f"Tabel metadata staging tidak dikenal: {table!r}")
    return f'{ident(schema)}."{table}"'


def clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def norm(value: Any) -> str | None:
    text = clean(value)
    return text.lower() if text else None


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


def parse_source_date(value: Any) -> tuple[date | None, str | None]:
    """Parse only ISO source dates; never guess local DD/MM/YY ordering."""

    text = clean(value)
    if text is None:
        return None, "blank_tanggalinput"
    try:
        if DATE_RE.fullmatch(text):
            return date.fromisoformat(text), None
        if DATETIME_RE.fullmatch(text):
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc)
            return parsed.date(), None
    except ValueError:
        pass
    return None, "invalid_tanggalinput_format"


def parse_nonnegative_pcs(value: Any) -> tuple[int | None, str | None]:
    """Accept only exact integer PCS values, including SQL decimal text ``6.0``."""

    text = clean(value)
    if text is None:
        return None, "blank_stokopname"
    if not DECIMAL_RE.fullmatch(text):
        return None, "invalid_stokopname_format"
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None, "invalid_stokopname_format"
    if not parsed.is_finite():
        return None, "invalid_stokopname_format"
    if parsed != parsed.to_integral_value():
        return None, "non_integral_stokopname_pcs"
    integer = int(parsed)
    if integer < 0:
        return None, "negative_stokopname_pcs"
    if integer > MAX_BIGINT:
        return None, "stokopname_out_of_bigint_range"
    return integer, None


def parse_raw_identity(row: StageRow) -> tuple[RawIdentity | None, str | None]:
    record_id = clean(row.source_record_id)
    if record_id is None:
        return None, "blank_source_record_id"
    visit_id = clean(row.idkunjungan)
    if visit_id is None:
        return None, "blank_idkunjungan"
    customer = clean(row.kodecustomer)
    if customer is None:
        return None, "blank_kodecustomer"
    principal = clean(row.kodeprinciple)
    if principal is None:
        return None, "blank_kodeprinciple"
    sales = clean(row.kodesales)
    if sales is None:
        return None, "blank_kodesales"
    sku = clean(row.kodebarang)
    if sku is None:
        return None, "blank_kodebarang"
    opname_date, date_reason = parse_source_date(row.tanggalinput_raw)
    if date_reason:
        return None, date_reason
    qty, qty_reason = parse_nonnegative_pcs(row.stokopname_raw)
    if qty_reason:
        return None, qty_reason
    assert opname_date is not None and qty is not None
    return RawIdentity(
        source_record_id=record_id,
        source_record_id_norm=record_id.lower(),
        source_visit_id=visit_id,
        source_visit_id_norm=visit_id.lower(),
        source_customer_code=customer,
        source_customer_code_norm=customer.lower(),
        source_principal_code=principal,
        source_principal_code_norm=principal.lower(),
        source_sales_code=sales,
        source_sales_code_norm=sales.lower(),
        source_sku=sku,
        source_sku_norm=sku.lower(),
        opname_date=opname_date,
        qty_physical_pcs=qty,
    ), None


def raw_header_key(source_system: str, identity: RawIdentity) -> tuple[str, str, str, str, str, date]:
    return (
        source_system,
        identity.source_visit_id_norm,
        identity.source_customer_code_norm,
        identity.source_principal_code_norm,
        identity.source_sales_code_norm,
        identity.opname_date,
    )


def source_visit_key(source_system: str, identity: RawIdentity) -> tuple[str, str]:
    return source_system, identity.source_visit_id_norm


def make_payload_hash(lines: Iterable[ResolvedLine]) -> str:
    # All source rows carry their legacy ID plus staging row hash.  A sort makes
    # a re-stage of the same visit stable even if SQL Server returns rows in a
    # different order.
    payload = "\x1e".join(
        f"{line.identity.source_record_id_norm}\x1f{line.row.source_row_hash}"
        for line in sorted(lines, key=lambda item: item.identity.source_record_id_norm)
    )
    return hashlib.sha256(payload.encode("utf-8", errors="surrogatepass")).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bdm-schema", help="Schema staging Stock Opname BDM Solo.")
    parser.add_argument("--tmp-schema", help="Schema staging Stock Opname TMP Solo.")
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID, help="Kode batch audit.")
    parser.add_argument("--apply", action="store_true", help="Tulis hanya archive migration, bukan tabel public.")
    parser.add_argument(
        "--confirm-historical-archive",
        action="store_true",
        help="Konfirmasi eksplisit bahwa data hanya diarsipkan sebagai historis, bukan adjustment stok.",
    )
    parser.add_argument("--pg-database", default=os.getenv("MIGRATION_PG_DATABASE", "budimas_dev"))
    parser.add_argument("--pg-user", default=os.getenv("MIGRATION_PG_USER", "postgres"))
    parser.add_argument("--pg-host", default=os.getenv("MIGRATION_PG_HOST", "127.0.0.1"))
    parser.add_argument("--pg-port", type=int, default=int(os.getenv("MIGRATION_PG_PORT", "5432")))
    parser.add_argument("--statement-timeout-seconds", type=int, default=300)
    parser.add_argument("--self-test", action="store_true", help="Jalankan test parser/UOM tanpa koneksi database.")
    return parser.parse_args()


def ensure_cli_args(args: argparse.Namespace) -> None:
    if not args.bdm_schema or not args.tmp_schema:
        raise ValidationError("--bdm-schema dan --tmp-schema wajib diisi.")
    ident(args.bdm_schema)
    ident(args.tmp_schema)
    if args.bdm_schema == args.tmp_schema:
        raise ValidationError("Schema BDM dan TMP wajib terpisah.")
    if not BATCH_RE.fullmatch(str(args.batch_id)):
        raise ValidationError("--batch-id tidak aman; gunakan huruf kecil, angka, titik, minus, atau underscore.")
    if args.statement_timeout_seconds <= 0 or args.statement_timeout_seconds > 3600:
        raise ValidationError("--statement-timeout-seconds harus di antara 1 dan 3600.")
    if args.apply and not args.confirm_historical_archive:
        raise ValidationError("--apply wajib disertai --confirm-historical-archive.")


def load_stage_columns(cur, schemas: list[str]) -> dict[tuple[str, str], set[str]]:
    cur.execute(
        """
        SELECT table_schema, table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = ANY(%s)
          AND table_name IN ('__stage_run', '__stage_manifest', 'stokopnameandroid')
        """,
        (schemas,),
    )
    result: dict[tuple[str, str], set[str]] = {}
    for schema, table, column in cur.fetchall():
        result.setdefault((str(schema), str(table)), set()).add(str(column))
    return result


def clean_name(value: str) -> str:
    name = re.sub(r"[^0-9a-zA-Z_]+", "_", str(value or "").strip())
    name = re.sub(r"_+", "_", name).strip("_").lower()
    if not name:
        name = "col"
    if name[0].isdigit():
        name = f"c_{name}"
    return name


def unique_clean_columns(raw_columns: Iterable[str]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for raw in raw_columns:
        base = clean_name(raw)
        seen[base] = seen.get(base, 0) + 1
        result.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    return result


def stage_metadata(
    cur,
    schema: str,
    expected_source: str,
    stage_columns: dict[tuple[str, str], set[str]],
) -> StageMetadata:
    run_columns = stage_columns.get((schema, "__stage_run"), set())
    manifest_columns = stage_columns.get((schema, "__stage_manifest"), set())
    source_columns_table = stage_columns.get((schema, "stokopnameandroid"), set())
    missing_run = {
        "id",
        "source_system",
        "status",
        "consistency_mode",
        "target_company_id",
        "target_branch_id",
    } - run_columns
    missing_manifest = {"legacy_table", "module", "source_columns", "source_row_count", "staged_row_count", "status"} - manifest_columns
    missing_fixed = STAGE_FIXED_COLUMNS - source_columns_table
    if missing_run or missing_manifest or missing_fixed:
        parts = []
        if missing_run:
            parts.append("__stage_run=" + ",".join(sorted(missing_run)))
        if missing_manifest:
            parts.append("__stage_manifest=" + ",".join(sorted(missing_manifest)))
        if missing_fixed:
            parts.append("stokopnameandroid=" + ",".join(sorted(missing_fixed)))
        raise ValidationError(f"Staging {schema} tidak lengkap: {'; '.join(parts)}.")

    preview_expr = "is_preview" if "is_preview" in run_columns else "(consistency_mode <> 'snapshot')"
    maintenance_window_expr = (
        "maintenance_window_id" if "maintenance_window_id" in run_columns else "NULL::text"
    )
    maintenance_attested_expr = (
        "maintenance_freeze_attested" if "maintenance_freeze_attested" in run_columns else "FALSE"
    )
    maintenance_confirmed_expr = (
        "maintenance_freeze_confirmed_at"
        if "maintenance_freeze_confirmed_at" in run_columns
        else "NULL::timestamptz"
    )
    source_isolation_expr = (
        "source_transaction_isolation" if "source_transaction_isolation" in run_columns else "NULL::text"
    )
    source_lock_timeout_expr = (
        "source_lock_timeout_ms" if "source_lock_timeout_ms" in run_columns else "NULL::integer"
    )
    cur.execute(
        f"""
        SELECT id, source_system, status, consistency_mode, {preview_expr},
               {maintenance_window_expr}, {maintenance_attested_expr},
               {maintenance_confirmed_expr}, {source_isolation_expr}, {source_lock_timeout_expr},
               target_company_id, target_branch_id
        FROM {stage_metadata_table(schema, '__stage_run')}
        ORDER BY id DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    if row is None:
        raise ValidationError(f"Staging {schema} tidak memiliki __stage_run.")
    if str(row[1]) != expected_source:
        raise ValidationError(f"Staging {schema} milik {row[1]!r}, bukan {expected_source!r}.")
    if str(row[2]) not in {"completed", "completed_preview"}:
        raise ValidationError(f"Staging {schema} belum selesai (status={row[2]!r}).")

    cur.execute(
        f"""
        SELECT status, module, source_columns, source_row_count, staged_row_count
        FROM {stage_metadata_table(schema, '__stage_manifest')}
        WHERE lower(btrim(legacy_table)) = 'stokopnameandroid'
        """
    )
    manifest = cur.fetchall()
    if len(manifest) != 1:
        raise ValidationError(f"{schema} harus memiliki tepat satu manifest StokOpnameAndroid.")
    manifest_status, manifest_module, raw_columns, source_count, staged_count = manifest[0]
    if str(manifest_status) != "done" or str(manifest_module) != "stock-opname":
        raise ValidationError(
            f"Manifest StokOpnameAndroid {schema} belum valid (status={manifest_status!r}, module={manifest_module!r})."
        )
    if source_count is None or staged_count is None or int(source_count) != int(staged_count):
        raise ValidationError(f"Manifest {schema} count tidak konsisten: source={source_count}, staged={staged_count}.")
    if isinstance(raw_columns, str):
        try:
            raw_columns = json.loads(raw_columns)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"Manifest {schema} memiliki source_columns tidak valid.") from exc
    if not isinstance(raw_columns, list) or not all(isinstance(item, str) and item.strip() for item in raw_columns):
        raise ValidationError(f"Manifest {schema} tidak memiliki daftar source_columns valid.")
    source_columns = tuple(unique_clean_columns(raw_columns))
    missing_source = SOURCE_REQUIRED_COLUMNS - set(source_columns)
    if missing_source:
        raise ValidationError(
            f"Staging {schema}.stokopnameandroid tidak memiliki kolom sumber wajib: {', '.join(sorted(missing_source))}."
        )
    missing_staged = set(source_columns) - source_columns_table
    if missing_staged:
        raise ValidationError(
            f"Tabel {schema}.stokopnameandroid tidak memuat kolom manifest: {', '.join(sorted(missing_staged))}."
        )
    return StageMetadata(
        schema=schema,
        source_system=expected_source,
        run_id=int(row[0]),
        status=str(row[2]),
        consistency_mode=str(row[3]),
        is_preview=bool(row[4]),
        maintenance_window_id=clean(row[5]),
        maintenance_freeze_attested=bool(row[6]),
        maintenance_freeze_confirmed_at=row[7] if isinstance(row[7], datetime) else None,
        source_transaction_isolation=clean(row[8]),
        source_lock_timeout_ms=int(row[9]) if row[9] is not None else None,
        target_company_id=int(row[10]),
        target_branch_id=int(row[11]),
        source_rows=int(staged_count),
        source_columns=source_columns,
    )


def validate_stage_provenance(cur, metadata: StageMetadata) -> None:
    cur.execute(
        f"""
        SELECT
            COUNT(*)::bigint,
            COUNT(*) FILTER (WHERE source_system IS DISTINCT FROM %s)::bigint,
            COUNT(*) FILTER (WHERE target_company_id IS DISTINCT FROM %s OR target_branch_id IS DISTINCT FROM %s)::bigint,
            COUNT(*) FILTER (WHERE lower(btrim(legacy_table)) <> 'stokopnameandroid')::bigint,
            COUNT(*) FILTER (WHERE source_row_hash IS NULL OR btrim(source_row_hash) = '')::bigint
        FROM {qtable(metadata.schema, 'stokopnameandroid')}
        """,
        (metadata.source_system, metadata.target_company_id, metadata.target_branch_id),
    )
    actual, bad_source, bad_scope, bad_table, bad_hash = (int(value) for value in cur.fetchone())
    if actual != metadata.source_rows:
        raise ValidationError(
            f"{metadata.schema}.stokopnameandroid berisi {actual}, bukan {metadata.source_rows} menurut manifest."
        )
    invalid = {
        "wrong_source_system": bad_source,
        "wrong_target_scope": bad_scope,
        "wrong_legacy_table": bad_table,
        "blank_source_row_hash": bad_hash,
    }
    if any(invalid.values()):
        raise ValidationError(
            f"Provenance {metadata.schema}.stokopnameandroid tidak valid: "
            + ", ".join(f"{key}={value}" for key, value in invalid.items() if value)
        )


def fetch_stage_rows(cur, metadata: StageMetadata) -> list[StageRow]:
    tgladd_expr = "s.tgladd" if "tgladd" in metadata.source_columns else "NULL::text"
    cur.execute(
        f"""
        SELECT s.staging_id, s.source_row_hash,
               s.id, s.kodebarang, s.kodecustomer, s.stokopname,
               s.tanggalinput, s.kodesales, {tgladd_expr}, s.kodeprinciple, s.idkunjungan
        FROM {qtable(metadata.schema, 'stokopnameandroid')} s
        WHERE s.source_system = %s
        ORDER BY s.staging_id
        """,
        (metadata.source_system,),
    )
    rows = [
        StageRow(
            source_system=metadata.source_system,
            stage_schema=metadata.schema,
            stage_run_id=metadata.run_id,
            staging_id=int(record[0]),
            source_row_hash=str(record[1]),
            source_record_id=clean(record[2]),
            kodebarang=clean(record[3]),
            kodecustomer=clean(record[4]),
            stokopname_raw=clean(record[5]),
            tanggalinput_raw=clean(record[6]),
            kodesales=clean(record[7]),
            tgladd_raw=clean(record[8]),
            kodeprinciple=clean(record[9]),
            idkunjungan=clean(record[10]),
        )
        for record in cur.fetchall()
    ]
    if len(rows) != metadata.source_rows:
        raise ValidationError(f"Jumlah row {metadata.schema}.stokopnameandroid berubah saat dibaca.")
    return rows


def load_source_context(cur, source_system: str) -> tuple[int, int]:
    cur.execute(
        f"""
        SELECT target_company_id, target_branch_id
        FROM {qtable(REGISTRY_SCHEMA, 'source_context')}
        WHERE source_system = %s
        """,
        (source_system,),
    )
    records = cur.fetchall()
    if len(records) != 1:
        raise ValidationError(f"source_context {source_system} harus tepat satu baris.")
    return int(records[0][0]), int(records[0][1])


def load_mapping(
    cur,
    source_system: str,
    table: str,
    key_columns: tuple[str, ...],
    target_column: str,
) -> dict[tuple[str, ...], MappingValue]:
    key_sql = ", ".join(ident(column) for column in key_columns)
    cur.execute(
        f"""
        SELECT {key_sql}, {ident(target_column)}, mapping_method
        FROM {qtable(REGISTRY_SCHEMA, table)}
        WHERE source_system = %s
        """,
        (source_system,),
    )
    result: dict[tuple[str, ...], MappingValue] = {}
    for record in cur.fetchall():
        key = tuple(str(value) for value in record[: len(key_columns)])
        if key in result:
            raise ValidationError(f"Registry {table} {source_system} memiliki key sumber ganda.")
        result[key] = MappingValue(int(record[len(key_columns)]), str(record[len(key_columns) + 1]))
    return result


def load_targets(cur, customer_ids: set[int], principal_ids: set[int], sales_ids: set[int], product_ids: set[int]):
    customers: dict[int, TargetCustomer] = {}
    principals: dict[int, TargetPrincipal] = {}
    sales: dict[int, TargetSales] = {}
    products: dict[int, TargetProduct] = {}
    if customer_ids:
        cur.execute("SELECT id, id_cabang FROM public.customer WHERE id = ANY(%s)", (sorted(customer_ids),))
        customers = {
            int(record[0]): TargetCustomer(int(record[0]), int(record[1]) if record[1] is not None else None)
            for record in cur.fetchall()
        }
    if principal_ids:
        cur.execute("SELECT id, id_perusahaan FROM public.principal WHERE id = ANY(%s)", (sorted(principal_ids),))
        principals = {
            int(record[0]): TargetPrincipal(int(record[0]), int(record[1]) if record[1] is not None else None)
            for record in cur.fetchall()
        }
    if sales_ids:
        cur.execute("SELECT id, id_principal FROM public.sales WHERE id = ANY(%s)", (sorted(sales_ids),))
        sales = {
            int(record[0]): TargetSales(int(record[0]), int(record[1]) if record[1] is not None else None)
            for record in cur.fetchall()
        }
    if product_ids:
        cur.execute("SELECT id, id_principal FROM public.produk WHERE id = ANY(%s)", (sorted(product_ids),))
        products = {
            int(record[0]): TargetProduct(int(record[0]), int(record[1]) if record[1] is not None else None)
            for record in cur.fetchall()
        }
    return customers, principals, sales, products


def parse_positive_integer(value: Any) -> int | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or parsed <= 0 or parsed != parsed.to_integral_value():
        return None
    integer = int(parsed)
    return integer if integer <= MAX_BIGINT else None


def load_exact_uom_display(cur, product_keys: set[tuple[str, str, str]]) -> dict[tuple[str, str, str], UomDisplay]:
    """Return only source-approved UOM display snapshots.

    The source stock-opname table has no UOM column.  The user has explicitly
    defined its quantity as the base/PCS amount, therefore a level-1 mapping
    with factor one is enough to label the base.  CT is exposed only when
    exactly one committed source map says ``CT`` and points to target level 2
    or level 3.  A similarly sized target UOM alone is never sufficient.
    """

    if not product_keys:
        return {}
    source_systems = sorted({key[0] for key in product_keys})
    cur.execute(
        f"""
        SELECT
            pum.source_system,
            pum.source_principal_code_norm,
            pum.source_sku_norm,
            pum.source_uom_level,
            pum.source_uom_code_norm,
            pum.source_factor,
            pum.id_produk,
            pum.id_produk_uom,
            pu.id_produk,
            pu.kode,
            pu.level,
            pu.faktor_konversi
        FROM {qtable(REGISTRY_SCHEMA, 'product_uom_map')} pum
        JOIN public.produk_uom pu ON pu.id = pum.id_produk_uom
        WHERE pum.source_system = ANY(%s)
          AND pum.source_uom_level IN (1, 2, 3)
        """,
        (source_systems,),
    )
    raw: dict[tuple[str, str, str], dict[str, dict[int, UomEntry]]] = defaultdict(
        lambda: {"base": {}, "ct": {}}
    )
    for record in cur.fetchall():
        source_system, principal_norm, sku_norm, source_level, source_code_norm, source_factor, mapped_product, uom_id, uom_product, code, target_level, target_factor = record
        key = (str(source_system), str(principal_norm), str(sku_norm))
        if key not in product_keys:
            continue
        parsed_source_factor = parse_positive_integer(source_factor)
        parsed_target_factor = parse_positive_integer(target_factor)
        parsed_target_level = int(target_level) if target_level is not None else None
        code_clean = clean(code)
        if (
            parsed_source_factor is None
            or parsed_target_factor is None
            or parsed_target_level is None
            or code_clean is None
            or int(mapped_product) != int(uom_product)
        ):
            continue
        entry = UomEntry(int(uom_id), code_clean, parsed_target_level, parsed_target_factor)
        if int(source_level) == 1 and parsed_source_factor == 1 and entry.level == 1 and entry.factor == 1:
            raw[key]["base"][entry.id_produk_uom] = entry
        elif (
            int(source_level) in (2, 3)
            and str(source_code_norm) == "ct"
            and entry.kode.lower() == "ct"
            and parsed_source_factor > 1
            and entry.level == int(source_level)
            and entry.factor == parsed_source_factor
        ):
            raw[key]["ct"][entry.id_produk_uom] = entry

    result: dict[tuple[str, str, str], UomDisplay] = {}
    for key in product_keys:
        bases = list(raw[key]["base"].values())
        cts = list(raw[key]["ct"].values())
        if len(bases) != 1:
            result[key] = UomDisplay(None, None, None, None, None, "pcs_only_missing_exact_base_uom")
        elif not cts:
            base = bases[0]
            result[key] = UomDisplay(base.id_produk_uom, base.kode, None, None, None, "pcs_only_missing_exact_ct_uom")
        elif len(cts) != 1:
            base = bases[0]
            result[key] = UomDisplay(base.id_produk_uom, base.kode, None, None, None, "pcs_only_ambiguous_exact_ct_uom")
        else:
            base, ct = bases[0], cts[0]
            if ct.factor <= 1:
                result[key] = UomDisplay(base.id_produk_uom, base.kode, None, None, None, "pcs_only_invalid_exact_ct_uom")
            else:
                result[key] = UomDisplay(
                    base.id_produk_uom,
                    base.kode,
                    ct.id_produk_uom,
                    ct.kode,
                    ct.factor,
                    "ct_plus_pcs_exact",
                )
    return result


def add_hold(holds: list[Hold], row: StageRow, reason: str, **details: Any) -> None:
    holds.append(Hold(row=row, reason=reason, details=json_safe(details)))


def build_resolved_lines(
    cur,
    metadata: dict[str, StageMetadata],
    rows_by_source: dict[str, list[StageRow]],
) -> tuple[list[ResolvedLine], list[Hold]]:
    """Resolve records, holding ambiguity before any archive action is planned."""

    holds: list[Hold] = []
    # ``staging_id`` is only unique inside one staging schema; BDM and TMP
    # both begin at one.  Every in-memory key therefore remains source/schema
    # qualified as well.
    identities: dict[tuple[str, str, int], RawIdentity] = {}
    initial_held: set[tuple[str, str, int]] = set()
    record_ids: dict[tuple[str, str], list[StageRow]] = defaultdict(list)
    visit_headers: dict[tuple[str, str], set[tuple[str, str, str, str, str, date]]] = defaultdict(set)
    rows_by_header: dict[tuple[str, str, str, str, str, date], list[StageRow]] = defaultdict(list)

    for source_system, rows in rows_by_source.items():
        for row in rows:
            row_key = (source_system, row.stage_schema, row.staging_id)
            identity, reason = parse_raw_identity(row)
            if reason:
                add_hold(holds, row, reason)
                initial_held.add(row_key)
                continue
            assert identity is not None
            identities[row_key] = identity
            record_ids[(source_system, identity.source_record_id_norm)].append(row)
            header_key = raw_header_key(source_system, identity)
            visit_headers[source_visit_key(source_system, identity)].add(header_key)
            rows_by_header[header_key].append(row)

    duplicate_record_rows: set[tuple[str, str, int]] = set()
    for (source_system, record_id), rows in record_ids.items():
        if len(rows) > 1:
            for row in rows:
                row_key = (source_system, row.stage_schema, row.staging_id)
                duplicate_record_rows.add(row_key)
                add_hold(holds, row, "duplicate_source_record_id", source_record_id=record_id, duplicate_count=len(rows))

    conflicting_visit_rows: set[tuple[str, str, int]] = set()
    for visit_key, header_keys in visit_headers.items():
        if len(header_keys) <= 1:
            continue
        for header_key in header_keys:
            for row in rows_by_header[header_key]:
                row_key = (row.source_system, row.stage_schema, row.staging_id)
                conflicting_visit_rows.add(row_key)
                add_hold(
                    holds,
                    row,
                    "conflicting_header_identity_for_visit",
                    source_visit_id=visit_key[1],
                    distinct_header_identities=len(header_keys),
                )

    maps: dict[str, dict[str, dict[tuple[str, ...], MappingValue]]] = {}
    all_customer_ids: set[int] = set()
    all_principal_ids: set[int] = set()
    all_sales_ids: set[int] = set()
    all_product_ids: set[int] = set()
    for source_system in SOURCE_SYSTEMS:
        customer = load_mapping(cur, source_system, "customer_map", ("source_customer_code_norm",), "id_customer")
        principal = load_mapping(cur, source_system, "principal_map", ("source_principal_code_norm",), "id_principal")
        sales = load_mapping(
            cur,
            source_system,
            "sales_map",
            ("source_principal_code_norm", "source_sales_code_norm"),
            "id_sales",
        )
        product = load_mapping(
            cur,
            source_system,
            "product_map",
            ("source_principal_code_norm", "source_sku_norm"),
            "id_produk",
        )
        maps[source_system] = {"customer": customer, "principal": principal, "sales": sales, "product": product}
        all_customer_ids.update(value.target_id for value in customer.values())
        all_principal_ids.update(value.target_id for value in principal.values())
        all_sales_ids.update(value.target_id for value in sales.values())
        all_product_ids.update(value.target_id for value in product.values())

    customers, principals, sales_targets, products = load_targets(
        cur, all_customer_ids, all_principal_ids, all_sales_ids, all_product_ids
    )
    resolved_without_uom: list[tuple[StageRow, RawIdentity, int, int, int, int, int, int]] = []
    for source_system, rows in rows_by_source.items():
        stage_meta = metadata[source_system]
        context_company, context_branch = load_source_context(cur, source_system)
        if (context_company, context_branch) != (stage_meta.target_company_id, stage_meta.target_branch_id):
            raise ValidationError(
                f"Scope staging {stage_meta.schema} ({stage_meta.target_company_id}/{stage_meta.target_branch_id}) "
                f"tidak sama dengan source_context {source_system} ({context_company}/{context_branch})."
            )
        for row in rows:
            row_key = (source_system, row.stage_schema, row.staging_id)
            if row_key in initial_held or row_key in duplicate_record_rows or row_key in conflicting_visit_rows:
                continue
            identity = identities.get(row_key)
            if identity is None:
                raise ValidationError("Identitas row hilang setelah validasi dasar.")
            source_maps = maps[source_system]
            customer_map = source_maps["customer"].get((identity.source_customer_code_norm,))
            if customer_map is None:
                add_hold(holds, row, "missing_customer_map", kodecustomer=identity.source_customer_code)
                initial_held.add(row_key)
                continue
            principal_map = source_maps["principal"].get((identity.source_principal_code_norm,))
            if principal_map is None:
                # Principal ambigu memang tidak memiliki committed map.
                add_hold(holds, row, "missing_or_ambiguous_principal_map", kodeprinciple=identity.source_principal_code)
                initial_held.add(row_key)
                continue
            sales_map = source_maps["sales"].get((identity.source_principal_code_norm, identity.source_sales_code_norm))
            if sales_map is None:
                add_hold(holds, row, "missing_sales_map", kodesales=identity.source_sales_code)
                initial_held.add(row_key)
                continue
            product_map = source_maps["product"].get((identity.source_principal_code_norm, identity.source_sku_norm))
            if product_map is None:
                add_hold(holds, row, "missing_product_map", kodebarang=identity.source_sku)
                initial_held.add(row_key)
                continue

            customer = customers.get(customer_map.target_id)
            principal = principals.get(principal_map.target_id)
            sales_target = sales_targets.get(sales_map.target_id)
            product = products.get(product_map.target_id)
            if customer is None or principal is None or sales_target is None or product is None:
                add_hold(holds, row, "mapped_target_missing")
                initial_held.add(row_key)
                continue
            if customer.id_cabang != context_branch and customer_map.method != "cross_branch_approved":
                add_hold(
                    holds,
                    row,
                    "customer_target_outside_source_branch",
                    id_customer=customer.id_customer,
                    target_branch=customer.id_cabang,
                    expected_branch=context_branch,
                )
                initial_held.add(row_key)
                continue
            if principal.id_perusahaan != context_company:
                add_hold(
                    holds,
                    row,
                    "principal_target_outside_source_company",
                    id_principal=principal.id_principal,
                    target_company=principal.id_perusahaan,
                    expected_company=context_company,
                )
                initial_held.add(row_key)
                continue
            if sales_target.id_principal != principal.id_principal:
                add_hold(
                    holds,
                    row,
                    "sales_target_principal_mismatch",
                    id_sales=sales_target.id_sales,
                    id_principal=principal.id_principal,
                    sales_principal=sales_target.id_principal,
                )
                initial_held.add(row_key)
                continue
            if product.id_principal != principal.id_principal:
                add_hold(
                    holds,
                    row,
                    "product_target_principal_mismatch",
                    id_produk=product.id_produk,
                    id_principal=principal.id_principal,
                    product_principal=product.id_principal,
                )
                initial_held.add(row_key)
                continue
            resolved_without_uom.append(
                (
                    row,
                    identity,
                    customer.id_customer,
                    principal.id_principal,
                    sales_target.id_sales,
                    product.id_produk,
                    context_company,
                    context_branch,
                )
            )

    # Hold the whole visit if any individual line failed.  A partial archive
    # would look like a complete stock count while silently omitting a product.
    blocked_headers: set[tuple[str, str, str, str, str, date]] = set()
    blocked_visits: set[tuple[str, str]] = set()
    for hold in holds:
        hold_row_key = (hold.row.source_system, hold.row.stage_schema, hold.row.staging_id)
        identity = identities.get(hold_row_key)
        if identity is not None:
            blocked_headers.add(raw_header_key(hold.row.source_system, identity))
        visit_id_norm = norm(hold.row.idkunjungan)
        if visit_id_norm is not None:
            blocked_visits.add((hold.row.source_system, visit_id_norm))
    resolved_pre_group: list[ResolvedLine] = []
    uom_keys = {
        (row.source_system, identity.source_principal_code_norm, identity.source_sku_norm)
        for row, identity, *_rest in resolved_without_uom
    }
    uom_display = load_exact_uom_display(cur, uom_keys)
    for row, identity, id_customer, id_principal, id_sales, id_produk, id_perusahaan, id_cabang in resolved_without_uom:
        header_key = raw_header_key(row.source_system, identity)
        if header_key in blocked_headers or source_visit_key(row.source_system, identity) in blocked_visits:
            add_hold(holds, row, "incomplete_visit_due_to_held_line", source_visit_id=identity.source_visit_id)
            continue
        display = uom_display[(row.source_system, identity.source_principal_code_norm, identity.source_sku_norm)]
        resolved_pre_group.append(
            ResolvedLine(
                row=row,
                identity=identity,
                id_customer=id_customer,
                id_principal=id_principal,
                id_sales=id_sales,
                id_produk=id_produk,
                id_perusahaan=id_perusahaan,
                id_cabang=id_cabang,
                uom=display,
            )
        )

    # Product duplicate inside one visit cannot be summed safely: source has
    # no line type/version field.  Keep all lines of the visit out of archive.
    grouped: dict[tuple[str, str, str, str, str, date], list[ResolvedLine]] = defaultdict(list)
    for line in resolved_pre_group:
        grouped[line.source_header_key].append(line)
    duplicate_product_headers: set[tuple[str, str, str, str, str, date]] = set()
    for header_key, lines in grouped.items():
        product_counts = Counter(line.id_produk for line in lines)
        if any(count > 1 for count in product_counts.values()):
            duplicate_product_headers.add(header_key)
            for line in lines:
                add_hold(
                    holds,
                    line.row,
                    "duplicate_product_within_visit",
                    source_visit_id=line.identity.source_visit_id,
                    duplicate_product_ids=sorted(product_id for product_id, count in product_counts.items() if count > 1),
                )
    return [line for line in resolved_pre_group if line.source_header_key not in duplicate_product_headers], holds


def build_header_plans(lines: list[ResolvedLine]) -> list[HeaderPlan]:
    grouped: dict[tuple[str, str, str, str, str, date], list[ResolvedLine]] = defaultdict(list)
    for line in lines:
        grouped[line.source_header_key].append(line)
    plans: list[HeaderPlan] = []
    for key, group in sorted(grouped.items(), key=lambda item: item[0]):
        first = group[0]
        distinct_target_tuples = {
            (line.id_customer, line.id_principal, line.id_sales, line.id_perusahaan, line.id_cabang)
            for line in group
        }
        if len(distinct_target_tuples) != 1:
            raise ValidationError(f"Header {key!r} memetakan ke target berbeda; seharusnya sudah ditahan.")
        plans.append(
            HeaderPlan(
                source_system=first.row.source_system,
                stage_schema=first.row.stage_schema,
                stage_run_id=first.row.stage_run_id,
                identity=first.identity,
                id_customer=first.id_customer,
                id_principal=first.id_principal,
                id_sales=first.id_sales,
                id_perusahaan=first.id_perusahaan,
                id_cabang=first.id_cabang,
                lines=tuple(sorted(group, key=lambda line: line.identity.source_record_id_norm)),
                source_payload_hash=make_payload_hash(group),
            )
        )
    return plans


def archive_tables_ready(cur) -> bool:
    cur.execute("SELECT to_regclass(%s)", (f"{REGISTRY_SCHEMA}.{ARCHIVE_TABLES[0]}",))
    return cur.fetchone()[0] is not None


def fetch_existing_archive(cur) -> tuple[
    dict[tuple[str, str, str, str, str, date], ExistingHeader],
    dict[tuple[str, str], ExistingLine],
]:
    cur.execute(
        f"""
        SELECT source_system, source_visit_id_norm, source_customer_code_norm,
               source_principal_code_norm, source_sales_code_norm, source_opname_date,
               id, source_payload_hash, source_record_count,
               id_customer, id_principal, id_sales, id_perusahaan, id_cabang
        FROM {qtable(REGISTRY_SCHEMA, 'historical_stock_opname_header')}
        WHERE source_system = ANY(%s)
        """,
        (list(SOURCE_SYSTEMS),),
    )
    headers: dict[tuple[str, str, str, str, str, date], ExistingHeader] = {}
    for record in cur.fetchall():
        key = (str(record[0]), str(record[1]), str(record[2]), str(record[3]), str(record[4]), record[5])
        if key in headers:
            raise ValidationError("Archive header memiliki source identity duplikat.")
        headers[key] = ExistingHeader(
            int(record[6]),
            str(record[7]),
            int(record[8]),
            int(record[9]),
            int(record[10]),
            int(record[11]),
            int(record[12]),
            int(record[13]),
        )
    cur.execute(
        f"""
        SELECT source_system, source_record_id_norm, id_historical_stock_opname,
               source_row_hash, id_produk, qty_physical_pcs
        FROM {qtable(REGISTRY_SCHEMA, 'historical_stock_opname_line')}
        WHERE source_system = ANY(%s)
        """,
        (list(SOURCE_SYSTEMS),),
    )
    lines: dict[tuple[str, str], ExistingLine] = {}
    for record in cur.fetchall():
        key = (str(record[0]), str(record[1]))
        if key in lines:
            raise ValidationError("Archive line memiliki source record ID duplikat.")
        lines[key] = ExistingLine(int(record[2]), str(record[3]), int(record[4]), int(record[5]))
    return headers, lines


def classify_archive_actions(
    plans: list[HeaderPlan],
    existing_headers: dict[tuple[str, str, str, str, str, date], ExistingHeader],
    existing_lines: dict[tuple[str, str], ExistingLine],
) -> tuple[list[HeaderPlan], list[tuple[HeaderPlan, ExistingHeader]], list[Hold]]:
    inserts: list[HeaderPlan] = []
    unchanged: list[tuple[HeaderPlan, ExistingHeader]] = []
    holds: list[Hold] = []
    for plan in plans:
        existing_header = existing_headers.get(plan.key)
        if existing_header is not None:
            if (
                existing_header.id_customer != plan.id_customer
                or existing_header.id_principal != plan.id_principal
                or existing_header.id_sales != plan.id_sales
                or existing_header.id_perusahaan != plan.id_perusahaan
                or existing_header.id_cabang != plan.id_cabang
            ):
                for line in plan.lines:
                    add_hold(
                        holds,
                        line.row,
                        "existing_archive_target_mapping_conflict",
                        historical_stock_opname_id=existing_header.id_historical_stock_opname,
                    )
                continue
            if (
                existing_header.source_payload_hash != plan.source_payload_hash
                or existing_header.source_record_count != len(plan.lines)
            ):
                for line in plan.lines:
                    add_hold(
                        holds,
                        line.row,
                        "existing_archive_header_payload_conflict",
                        historical_stock_opname_id=existing_header.id_historical_stock_opname,
                    )
                continue
            line_conflict = False
            for line in plan.lines:
                current = existing_lines.get((plan.source_system, line.identity.source_record_id_norm))
                if (
                    current is None
                    or current.id_historical_stock_opname != existing_header.id_historical_stock_opname
                    or current.source_row_hash != line.row.source_row_hash
                    or current.id_produk != line.id_produk
                    or current.qty_physical_pcs != line.identity.qty_physical_pcs
                ):
                    line_conflict = True
                    break
            if line_conflict:
                for line in plan.lines:
                    add_hold(
                        holds,
                        line.row,
                        "existing_archive_line_mismatch",
                        historical_stock_opname_id=existing_header.id_historical_stock_opname,
                    )
                continue
            unchanged.append((plan, existing_header))
            continue
        record_conflicts = [
            existing_lines.get((plan.source_system, line.identity.source_record_id_norm))
            for line in plan.lines
            if (plan.source_system, line.identity.source_record_id_norm) in existing_lines
        ]
        if record_conflicts:
            for line in plan.lines:
                add_hold(holds, line.row, "existing_archive_source_record_conflict")
            continue
        inserts.append(plan)
    return inserts, unchanged, holds


def count_holds(holds: Iterable[Hold]) -> dict[str, int]:
    return dict(sorted(Counter(hold.reason for hold in holds).items()))


def count_uom_status(plans: Iterable[HeaderPlan]) -> dict[str, int]:
    return dict(sorted(Counter(line.uom.status for plan in plans for line in plan.lines).items()))


def plan_summary(
    metadata: dict[str, StageMetadata],
    rows_by_source: dict[str, list[StageRow]],
    inserts: list[HeaderPlan],
    unchanged: list[tuple[HeaderPlan, ExistingHeader]],
    holds: list[Hold],
    archive_ready: bool,
    mode: str,
) -> dict[str, Any]:
    eligible_plans = [*inserts, *(plan for plan, _existing in unchanged)]
    apply_allowed, apply_allowed_reason = final_stage_gate(metadata)
    return {
        "mode": mode,
        "writes_public_tables": False,
        "creates_inventory_ledger_movements": False,
        "archive_schema_ready": archive_ready,
        "stage": {
            source: {
                "schema": stage.schema,
                "run_id": stage.run_id,
                "source_rows": len(rows_by_source[source]),
                "status": stage.status,
                "consistency_mode": stage.consistency_mode,
                "is_preview": stage.is_preview,
                "maintenance_window_id": stage.maintenance_window_id,
                "maintenance_freeze_attested": stage.maintenance_freeze_attested,
                "maintenance_freeze_confirmed_at": (
                    stage.maintenance_freeze_confirmed_at.isoformat()
                    if stage.maintenance_freeze_confirmed_at is not None
                    else None
                ),
                "source_transaction_isolation": stage.source_transaction_isolation,
                "source_lock_timeout_ms": stage.source_lock_timeout_ms,
            }
            for source, stage in metadata.items()
        },
        "apply_allowed": apply_allowed,
        "apply_allowed_reason": apply_allowed_reason,
        "archive_plan": {
            "headers_to_insert": len(inserts),
            "lines_to_insert": sum(len(plan.lines) for plan in inserts),
            "unchanged_existing_headers": len(unchanged),
            "unchanged_existing_lines": sum(len(plan.lines) for plan, _existing in unchanged),
            "eligible_headers": len(eligible_plans),
            "held_rows": len(holds),
            "hold_reasons": count_holds(holds),
            "uom_display": count_uom_status(eligible_plans),
        },
        "quantity_policy": {
            "source_unit": "PCS/base physical count",
            "good_bad": "unknown; not inferred",
            "system_stock": "unknown; not inferred",
            "ct_pcs": "display-only from exactly one approved base and CT UOM map",
        },
    }


def final_stage_gate(metadata: dict[str, StageMetadata]) -> tuple[bool, str]:
    """Accept only independently auditable final staging pairs.

    SNAPSHOT is the normal route.  The only alternate route is the explicit
    maintenance-freeze mode emitted by ``stage_august_2026_source.py`` after
    an operator has confirmed all source writers are frozen.  A completed
    read-committed run is never upgraded by relabelling it.
    """

    values = list(metadata.values())
    if len(values) != len(SOURCE_SYSTEMS):
        return False, "Metadata staging BDM/TMP tidak lengkap."
    if any(stage.status != "completed" or stage.is_preview for stage in values):
        return False, "Kedua staging wajib completed dan bukan preview."
    if all(stage.consistency_mode == SNAPSHOT_CONSISTENCY_MODE for stage in values):
        return True, "Kedua staging final memakai SQL Server SNAPSHOT."
    if not all(stage.consistency_mode == MAINTENANCE_FREEZE_CONSISTENCY_MODE for stage in values):
        return (
            False,
            "Kedua staging harus sama-sama SNAPSHOT atau maintenance_freeze_serializable dari satu window.",
        )
    window_ids = {stage.maintenance_window_id for stage in values if stage.maintenance_window_id}
    if len(window_ids) != 1 or any(not stage.maintenance_window_id for stage in values):
        return False, "Staging maintenance BDM/TMP wajib memiliki maintenance_window_id yang sama."
    if any(
        not stage.maintenance_freeze_attested
        or stage.maintenance_freeze_confirmed_at is None
        or (stage.source_transaction_isolation or "").strip().lower() != "serializable"
        or stage.source_lock_timeout_ms is None
        or stage.source_lock_timeout_ms <= 0
        for stage in values
    ):
        return False, "Attestation write-freeze atau transaksi SERIALIZABLE tidak lengkap."
    return True, f"Kedua staging memakai write-freeze terattestasi ({next(iter(window_ids))})."


def assert_final_staging(metadata: dict[str, StageMetadata]) -> None:
    allowed, reason = final_stage_gate(metadata)
    if not allowed:
        raise ValidationError("--apply ditolak: " + reason)


def ensure_apply_batch_unused(cur, batch_id: str) -> None:
    cur.execute(
        f"SELECT 1 FROM {qtable(REGISTRY_SCHEMA, 'historical_stock_opname_import_run')} WHERE batch_id = %s",
        (batch_id,),
    )
    if cur.fetchone() is not None:
        raise ValidationError(f"Batch {batch_id} sudah pernah digunakan; gunakan batch baru setelah review.")


def apply_archive(
    cur,
    execute_values,
    batch_id: str,
    metadata: dict[str, StageMetadata],
    inserts: list[HeaderPlan],
    unchanged: list[tuple[HeaderPlan, ExistingHeader]],
    holds: list[Hold],
) -> dict[str, Any]:
    """Insert archive records only.  This function never touches public tables."""

    cur.execute(f"LOCK TABLE {qtable(REGISTRY_SCHEMA, 'historical_stock_opname_header')} IN SHARE ROW EXCLUSIVE MODE")
    cur.execute(f"LOCK TABLE {qtable(REGISTRY_SCHEMA, 'historical_stock_opname_line')} IN SHARE ROW EXCLUSIVE MODE")
    ensure_apply_batch_unused(cur, batch_id)
    all_plans = [*inserts, *(plan for plan, _existing in unchanged)]
    hold_summary = count_holds(holds)
    uom_summary = count_uom_status(all_plans)
    cur.execute(
        f"""
        INSERT INTO {qtable(REGISTRY_SCHEMA, 'historical_stock_opname_import_run')}
            (batch_id, bdm_stage_schema, tmp_stage_schema, bdm_stage_run_id, tmp_stage_run_id,
             bdm_consistency_mode, tmp_consistency_mode,
             bdm_maintenance_window_id, tmp_maintenance_window_id,
             bdm_maintenance_freeze_attested, tmp_maintenance_freeze_attested,
             bdm_maintenance_freeze_confirmed_at, tmp_maintenance_freeze_confirmed_at,
             bdm_source_transaction_isolation, tmp_source_transaction_isolation,
             bdm_source_lock_timeout_ms, tmp_source_lock_timeout_ms,
             bdm_source_rows, tmp_source_rows,
             inserted_headers, inserted_lines, unchanged_headers, held_rows,
             uom_display_summary, hold_summary, applied_by)
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s,
            %s, %s,
            %s, %s,
            %s, %s,
            %s, %s,
            %s, %s,
            %s, %s,
            %s, %s, %s, %s,
            %s::jsonb, %s::jsonb, %s
        )
        """,
        (
            batch_id,
            metadata["bdm_solo_dist"].schema,
            metadata["tmp_solo_dist"].schema,
            metadata["bdm_solo_dist"].run_id,
            metadata["tmp_solo_dist"].run_id,
            metadata["bdm_solo_dist"].consistency_mode,
            metadata["tmp_solo_dist"].consistency_mode,
            metadata["bdm_solo_dist"].maintenance_window_id,
            metadata["tmp_solo_dist"].maintenance_window_id,
            metadata["bdm_solo_dist"].maintenance_freeze_attested,
            metadata["tmp_solo_dist"].maintenance_freeze_attested,
            metadata["bdm_solo_dist"].maintenance_freeze_confirmed_at,
            metadata["tmp_solo_dist"].maintenance_freeze_confirmed_at,
            metadata["bdm_solo_dist"].source_transaction_isolation,
            metadata["tmp_solo_dist"].source_transaction_isolation,
            metadata["bdm_solo_dist"].source_lock_timeout_ms,
            metadata["tmp_solo_dist"].source_lock_timeout_ms,
            metadata["bdm_solo_dist"].source_rows,
            metadata["tmp_solo_dist"].source_rows,
            len(inserts),
            sum(len(plan.lines) for plan in inserts),
            len(unchanged),
            len(holds),
            json.dumps(uom_summary, ensure_ascii=False, sort_keys=True),
            json.dumps(hold_summary, ensure_ascii=False, sort_keys=True),
            "migration_historical_stock_opname_20260828",
        ),
    )

    header_id_by_key: dict[tuple[str, str, str, str, str, date], int] = {}
    if inserts:
        header_rows = [
            (
                batch_id,
                plan.source_system,
                plan.stage_schema,
                plan.stage_run_id,
                plan.identity.source_visit_id,
                plan.identity.source_visit_id_norm,
                plan.identity.source_customer_code,
                plan.identity.source_customer_code_norm,
                plan.identity.source_principal_code,
                plan.identity.source_principal_code_norm,
                plan.identity.source_sales_code,
                plan.identity.source_sales_code_norm,
                plan.identity.opname_date,
                plan.id_customer,
                plan.id_principal,
                plan.id_sales,
                plan.id_perusahaan,
                plan.id_cabang,
                len(plan.lines),
                plan.source_payload_hash,
            )
            for plan in inserts
        ]
        inserted_headers = execute_values(
            cur,
            f"""
            INSERT INTO {qtable(REGISTRY_SCHEMA, 'historical_stock_opname_header')}
                (import_batch_id, source_system, source_stage_schema, source_stage_run_id,
                 source_visit_id, source_visit_id_norm, source_customer_code, source_customer_code_norm,
                 source_principal_code, source_principal_code_norm, source_sales_code, source_sales_code_norm,
                 source_opname_date, id_customer, id_principal, id_sales, id_perusahaan, id_cabang,
                 source_record_count, source_payload_hash)
            VALUES %s
            RETURNING id, source_system, source_visit_id_norm, source_customer_code_norm,
                      source_principal_code_norm, source_sales_code_norm, source_opname_date
            """,
            header_rows,
            page_size=1000,
            fetch=True,
        )
        for record in inserted_headers:
            key = (str(record[1]), str(record[2]), str(record[3]), str(record[4]), str(record[5]), record[6])
            if key in header_id_by_key:
                raise ValidationError("INSERT archive header mengembalikan key duplikat.")
            header_id_by_key[key] = int(record[0])
        if len(header_id_by_key) != len(inserts):
            raise ValidationError("Jumlah archive header yang masuk tidak cocok dengan rencana.")

        line_rows = []
        for plan in inserts:
            header_id = header_id_by_key.get(plan.key)
            if header_id is None:
                raise ValidationError("Header archive hasil INSERT tidak ditemukan saat menulis line.")
            for line in plan.lines:
                line_rows.append(
                    (
                        header_id,
                        plan.source_system,
                        line.row.stage_schema,
                        line.row.stage_run_id,
                        line.row.staging_id,
                        line.row.source_row_hash,
                        line.identity.source_record_id,
                        line.identity.source_record_id_norm,
                        line.identity.source_sku,
                        line.identity.source_sku_norm,
                        line.id_produk,
                        line.identity.qty_physical_pcs,
                        line.row.stokopname_raw,
                        line.row.tgladd_raw,
                        line.uom.id_base_produk_uom,
                        line.uom.base_uom_code,
                        line.uom.id_ct_produk_uom,
                        line.uom.ct_uom_code,
                        line.uom.ct_factor,
                        line.uom.status,
                    )
                )
        execute_values(
            cur,
            f"""
            INSERT INTO {qtable(REGISTRY_SCHEMA, 'historical_stock_opname_line')}
                (id_historical_stock_opname, source_system, source_stage_schema, source_stage_run_id,
                 source_staging_id, source_row_hash, source_record_id, source_record_id_norm,
                 source_sku, source_sku_norm, id_produk, qty_physical_pcs, source_qty_raw, source_tgladd_raw,
                 id_base_produk_uom, base_uom_code, id_ct_produk_uom, ct_uom_code, ct_factor, uom_display_status)
            VALUES %s
            """,
            line_rows,
            page_size=1000,
        )

    if holds:
        hold_rows = [
            (
                batch_id,
                hold.row.source_system,
                hold.row.stage_schema,
                hold.row.staging_id,
                hold.row.source_record_id,
                hold.row.source_row_hash,
                hold.reason,
                json.dumps(hold.details, ensure_ascii=False, sort_keys=True),
            )
            for hold in holds
        ]
        execute_values(
            cur,
            f"""
            INSERT INTO {qtable(REGISTRY_SCHEMA, 'historical_stock_opname_hold')}
                (import_batch_id, source_system, source_stage_schema, source_staging_id,
                 source_record_id, source_row_hash, hold_reason, details)
            VALUES %s
            """,
            hold_rows,
            page_size=1000,
        )

    actions = []
    for plan in inserts:
        actions.append(
            (
                batch_id,
                plan.source_system,
                plan.source_header_key_text,
                "insert_header_and_lines",
                header_id_by_key[plan.key],
                len(plan.lines),
                json.dumps({"source_payload_hash": plan.source_payload_hash}, ensure_ascii=False, sort_keys=True),
            )
        )
    for plan, existing in unchanged:
        actions.append(
            (
                batch_id,
                plan.source_system,
                plan.source_header_key_text,
                "unchanged_existing_archive",
                existing.id_historical_stock_opname,
                len(plan.lines),
                json.dumps({"source_payload_hash": plan.source_payload_hash}, ensure_ascii=False, sort_keys=True),
            )
        )
    if actions:
        execute_values(
            cur,
            f"""
            INSERT INTO {qtable(REGISTRY_SCHEMA, 'historical_stock_opname_action')}
                (import_batch_id, source_system, source_header_key, action,
                 id_historical_stock_opname, line_count, details)
            VALUES %s
            """,
            actions,
            page_size=1000,
        )
    return {
        "batch_id": batch_id,
        "inserted_headers": len(inserts),
        "inserted_lines": sum(len(plan.lines) for plan in inserts),
        "unchanged_existing_headers": len(unchanged),
        "held_rows": len(holds),
    }


def run_self_test() -> int:
    tests = [
        (parse_nonnegative_pcs("6"), (6, None)),
        (parse_nonnegative_pcs("6.000"), (6, None)),
        (parse_nonnegative_pcs("6.5")[1], "non_integral_stokopname_pcs"),
        (parse_nonnegative_pcs("-1")[1], "negative_stokopname_pcs"),
        (parse_source_date("2026-08-01"), (date(2026, 8, 1), None)),
        (parse_source_date("2026-08-01 08:05:35.480"), (date(2026, 8, 1), None)),
        (parse_source_date("01/08/2026")[1], "invalid_tanggalinput_format"),
    ]
    for actual, expected in tests:
        assert actual == expected, f"self-test gagal: actual={actual!r}, expected={expected!r}"

    identity, identity_reason = parse_raw_identity(
        StageRow(
            source_system="bdm_solo_dist",
            stage_schema="legacy_test",
            stage_run_id=1,
            staging_id=1,
            source_row_hash="test-row-hash",
            source_record_id="100",
            kodebarang="SKU-1",
            kodecustomer="CUST-1",
            stokopname_raw="48.000",
            tanggalinput_raw="2026-08-01",
            kodesales="SLS-1",
            tgladd_raw=None,
            kodeprinciple="PR-1",
            idkunjungan="VISIT-1",
        )
    )
    assert identity_reason is None and identity is not None
    assert identity.qty_physical_pcs == 48
    assert stage_metadata_table("legacy_test", "__stage_run") == '"legacy_test"."__stage_run"'

    class FakeCursor:
        def execute(self, _query, _params=None):
            return None

        def fetchall(self):
            # Base PC plus source/target CT at level 3.  This proves the
            # display selection never assumes level 2 only.
            return [
                ("bdm_solo_dist", "p", "sku", 1, "pc", 1, 99, 501, 99, "PC", 1, 1),
                ("bdm_solo_dist", "p", "sku", 3, "ct", 48, 99, 503, 99, "CT", 3, 48),
                # A similarly sized but non-CT map must not become CT.
                ("bdm_solo_dist", "p", "other", 1, "pc", 1, 100, 601, 100, "PC", 1, 1),
                ("bdm_solo_dist", "p", "other", 2, "karton", 24, 100, 602, 100, "KARTON", 2, 24),
            ]

    displays = load_exact_uom_display(
        FakeCursor(),
        {("bdm_solo_dist", "p", "sku"), ("bdm_solo_dist", "p", "other")},
    )
    assert displays[("bdm_solo_dist", "p", "sku")].status == "ct_plus_pcs_exact"
    assert displays[("bdm_solo_dist", "p", "sku")].ct_factor == 48
    assert displays[("bdm_solo_dist", "p", "other")].status == "pcs_only_missing_exact_ct_uom"

    preview_stage = StageMetadata(
        schema="legacy_preview_test",
        source_system="bdm_solo_dist",
        run_id=1,
        status="completed_preview",
        consistency_mode="read_committed_preview",
        is_preview=True,
        maintenance_window_id=None,
        maintenance_freeze_attested=False,
        maintenance_freeze_confirmed_at=None,
        source_transaction_isolation="READ COMMITTED",
        source_lock_timeout_ms=None,
        target_company_id=1,
        target_branch_id=5,
        source_rows=0,
        source_columns=(),
    )
    try:
        assert_final_staging({"bdm_solo_dist": preview_stage, "tmp_solo_dist": preview_stage})
    except ValidationError:
        pass
    else:
        raise AssertionError("preview staging tidak boleh lolos untuk --apply")
    frozen_bdm = StageMetadata(
        schema="legacy_bdm_freeze_test",
        source_system="bdm_solo_dist",
        run_id=2,
        status="completed",
        consistency_mode=MAINTENANCE_FREEZE_CONSISTENCY_MODE,
        is_preview=False,
        maintenance_window_id="test-window",
        maintenance_freeze_attested=True,
        maintenance_freeze_confirmed_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
        source_transaction_isolation="SERIALIZABLE",
        source_lock_timeout_ms=5000,
        target_company_id=1,
        target_branch_id=5,
        source_rows=0,
        source_columns=(),
    )
    frozen_tmp = StageMetadata(
        schema="legacy_tmp_freeze_test",
        source_system="tmp_solo_dist",
        run_id=2,
        status="completed",
        consistency_mode=MAINTENANCE_FREEZE_CONSISTENCY_MODE,
        is_preview=False,
        maintenance_window_id="test-window",
        maintenance_freeze_attested=True,
        maintenance_freeze_confirmed_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
        source_transaction_isolation="SERIALIZABLE",
        source_lock_timeout_ms=5000,
        target_company_id=2,
        target_branch_id=5,
        source_rows=0,
        source_columns=(),
    )
    assert final_stage_gate({"bdm_solo_dist": frozen_bdm, "tmp_solo_dist": frozen_tmp})[0]
    print(json.dumps({"status": "ok", "self_test": "historical_stock_opname"}, ensure_ascii=False))
    return 0


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()
    ensure_cli_args(args)
    try:
        import psycopg2  # type: ignore[import-not-found]
        from psycopg2.extras import execute_values  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ValidationError("psycopg2 diperlukan untuk membaca PostgreSQL.") from exc

    conn = psycopg2.connect(
        dbname=args.pg_database,
        user=args.pg_user,
        host=args.pg_host,
        port=args.pg_port,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cur.execute("SET LOCAL lock_timeout = '10s'")
            cur.execute("SET LOCAL statement_timeout = %s", (f"{args.statement_timeout_seconds}s",))
            stage_columns = load_stage_columns(cur, [args.bdm_schema, args.tmp_schema])
            metadata = {
                "bdm_solo_dist": stage_metadata(cur, args.bdm_schema, "bdm_solo_dist", stage_columns),
                "tmp_solo_dist": stage_metadata(cur, args.tmp_schema, "tmp_solo_dist", stage_columns),
            }
            for item in metadata.values():
                validate_stage_provenance(cur, item)
            rows_by_source = {source: fetch_stage_rows(cur, stage) for source, stage in metadata.items()}
            resolved, validation_holds = build_resolved_lines(cur, metadata, rows_by_source)
            plans = build_header_plans(resolved)
            archive_ready = archive_tables_ready(cur)
            if archive_ready:
                existing_headers, existing_lines = fetch_existing_archive(cur)
                inserts, unchanged, archive_holds = classify_archive_actions(plans, existing_headers, existing_lines)
            else:
                inserts, unchanged, archive_holds = plans, [], []
            holds = [*validation_holds, *archive_holds]
            if not args.apply:
                print(
                    json.dumps(
                        plan_summary(metadata, rows_by_source, inserts, unchanged, holds, archive_ready, "dry_run"),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                conn.rollback()
                return 0
            assert_final_staging(metadata)
            if not archive_ready:
                raise ValidationError(
                    "Archive DDL belum terpasang. Jalankan 20260828_create_historical_stock_opname_archive.sql terlebih dahulu."
                )
            result = apply_archive(cur, execute_values, str(args.batch_id), metadata, inserts, unchanged, holds)
        conn.commit()
        output = plan_summary(metadata, rows_by_source, inserts, unchanged, holds, archive_ready, "applied_historical_archive")
        output["apply_result"] = result
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
