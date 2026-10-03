#!/usr/bin/env python3
"""Import final BDM/TMP *sales* into active ERP tables without source collisions.

This importer is intentionally narrower and safer than the legacy one-source
scripts in ``scripts/``.  It imports only the canonical ``HJualSM`` +
``DJualSM`` family.  ``HJualSMAndroid`` is reported and held, because a large
part of that family has an already-issued ``NoFaktur`` and is therefore not a
second invoice until a source-qualified cross-reference rule is reviewed.

Important safety rules
----------------------

* SQL Server is never contacted and is never changed by this program.
* Dry-run is the default.  ``--apply`` accepts final SQL Server SNAPSHOT
  staging, or one matching, attested maintenance-freeze staging window only.
* A source identity is always
  ``source_system + HJualSM + normalized Nota``.  Every human document number
  is prefixed (``LEG-BDM-HJ-...`` / ``LEG-TMP-HJ-...``), so equal legacy notas
  cannot collide in ERP.
* Customer, principal, sales, product, base-UOM, and outer-UOM must all come
  from the committed source-aware registry.  The line invariant is exact:
  ``Jumlah = Unit × PerUnit + Satuan``.  No UOM is guessed.
* ``RL`` is eligible only as delivered; all non-RL statuses, including ``BT``,
  are held until their current ERP lifecycle semantics are approved. A legacy
  script once used ``status_order=-1`` for ``BT``, but that value is not a
  verified current ERP status and is never written by this tool.
* An ``RL`` document is not applied by default: it needs a reconciled inbound
  / opening-stock HPP baseline first. ``ledger_zero_cost`` is deliberately
  disabled, not merely hidden behind a confirmation flag. This prevents an
  unverifiable historic delivery from changing stock/HPP or being moved twice.
* Header ``Terbayar`` is preserved in audit only.  Invoice settlement stays
  unapplied until the source-aware payment allocator has matched its receipts;
  the importer never marks an invoice paid merely from an aggregate header.

Before ``--apply``, install
``20260830_create_active_sales_import_audit.sql``.  The audit DDL is confined
to ``migration_bdm_tmp_202608``.  The importer itself writes the following
public tables only when explicitly applied: ``sales_order``, ``faktur``,
``sales_order_detail``. It currently never writes ``inventory_ledger``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


REGISTRY_SCHEMA = "migration_bdm_tmp_202608"
SOURCE_SYSTEMS = ("bdm_solo_dist", "tmp_solo_dist")
SOURCE_TAG = {"bdm_solo_dist": "BDM", "tmp_solo_dist": "TMP"}
SOURCE_HEADER_TABLE = "HJualSM"
SOURCE_DETAIL_TABLE = "DJualSM"
ANDROID_HEADER_TABLE = "HJualSMAndroid"
ANDROID_DETAIL_TABLE = "DJualSMAndroid"
SOURCE_TABLES = {
    "hjualsm": SOURCE_HEADER_TABLE,
    "djualsm": SOURCE_DETAIL_TABLE,
    "hjualsmandroid": ANDROID_HEADER_TABLE,
    "djualsmandroid": ANDROID_DETAIL_TABLE,
}
STAGE_TABLES = tuple(SOURCE_TABLES)
STAGE_METADATA_TABLES = {"__stage_run", "__stage_manifest"}
STAGE_FIXED_COLUMNS = {
    "staging_id",
    "source_system",
    "target_company_id",
    "target_branch_id",
    "legacy_table",
    "source_row_hash",
    "imported_at",
}
HEADER_REQUIRED_COLUMNS = {
    "tanggal",
    "nota",
    "kodesales",
    "namasales",
    "kodecustomer",
    "namacustomer",
    "kodeprinciple",
    "totalpenjualan",
    "totalretur",
    "terbayar",
    "stnota",
    "tglreal",
    "jatuhtempo",
    "keterangan",
}
DETAIL_REQUIRED_COLUMNS = {
    "tanggal",
    "nota",
    "kodestok",
    "unit",
    "ct",
    "satuan",
    "pc",
    "perunit",
    "jumlah",
    "harga",
    "jumlahexppn",
    "jumlahharga",
    "kodesales",
    "kodecustomer",
    "kodeprinciple",
    "urut",
    "disc1",
    "disc2",
    "disc3",
    "discrp",
    "discrp1",
    "discrp2",
    "discrp3",
}
IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
BATCH_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,119}$")
DECIMAL_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}"
    r"(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?$"
)
SNAPSHOT_CONSISTENCY_MODE = "snapshot"
MAINTENANCE_FREEZE_CONSISTENCY_MODE = "maintenance_freeze_serializable"
TARGET_ERP_MAINTENANCE_CONFIRMATION = "I_CONFIRM_TARGET_ERP_MAINTENANCE_WINDOW"
LEDGER_SOURCE_TYPE = "legacy_bdm_tmp_sales_v1"
MAX_INT32 = 2_147_483_647


class ValidationError(RuntimeError):
    """Raised when an input cannot be safely applied."""


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
    manifest_rows: dict[str, int]
    source_columns: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class HeaderRow:
    source_system: str
    stage_schema: str
    stage_run_id: int
    staging_id: int
    source_row_hash: str
    source_table: str
    nota: str | None
    tanggal_raw: str | None
    kodesales: str | None
    namasales: str | None
    kodecustomer: str | None
    namacustomer: str | None
    kodeprinciple: str | None
    keterangan: str | None
    jatuhtempo_raw: str | None
    totalpenjualan_raw: str | None
    totalretur_raw: str | None
    terbayar_raw: str | None
    stnota: str | None
    tglreal_raw: str | None


@dataclass(frozen=True)
class DetailRow:
    source_system: str
    stage_schema: str
    stage_run_id: int
    staging_id: int
    source_row_hash: str
    source_table: str
    nota: str | None
    urut: str | None
    tanggal_raw: str | None
    kodestok: str | None
    masterkode: str | None
    ct: str | None
    pc: str | None
    unit_raw: str | None
    satuan_raw: str | None
    perunit_raw: str | None
    jumlah_raw: str | None
    harga_raw: str | None
    jumlahexppn_raw: str | None
    jumlahharga_raw: str | None
    kodesales: str | None
    kodecustomer: str | None
    kodeprinciple: str | None
    disc1_raw: str | None
    disc2_raw: str | None
    disc3_raw: str | None
    discrp_raw: str | None
    discrp1_raw: str | None
    discrp2_raw: str | None
    discrp3_raw: str | None


@dataclass(frozen=True)
class Hold:
    source_system: str
    stage_schema: str
    stage_run_id: int
    source_table: str
    reason: str
    source_staging_id: int | None = None
    source_nota: str | None = None
    source_nota_norm: str | None = None
    source_urut: str | None = None
    source_urut_norm: str | None = None
    source_row_hash: str | None = None
    details: dict[str, Any] | None = None


@dataclass(frozen=True)
class UomTarget:
    id_produk: int
    id_produk_uom: int
    level: int
    factor: int


@dataclass(frozen=True)
class LinePlan:
    row: DetailRow
    source_urut: str
    source_urut_norm: str
    id_produk: int
    id_base_uom: int
    id_outer_uom: int
    outer_level: int
    outer_factor: int
    qty_base: int
    pieces_order: int
    box_order: int
    karton_order: int
    harga_order: Decimal
    subtotal_dpp: Decimal
    subtotal_order: Decimal
    discount_amount: Decimal
    source_discount_percent: Decimal
    is_bonus: int


@dataclass(frozen=True)
class HeaderPlan:
    row: HeaderRow
    source_nota: str
    source_nota_norm: str
    human_document_code: str
    ledger_source_id: str
    id_customer: int
    id_principal: int
    id_sales: int
    id_plafon: int
    id_perusahaan: int
    id_cabang: int
    tanggal_order: date
    tanggal_terkirim: date | None
    tanggal_jatuh_tempo: date | None
    status_order: int
    status_faktur: int
    total_penjualan: Decimal
    total_retur: Decimal
    source_terbayar: Decimal | None
    subtotal_dpp: Decimal
    subtotal_diskon: Decimal
    pajak: Decimal
    lines: tuple[LinePlan, ...]


@dataclass(frozen=True)
class ExistingDocument:
    stage_schema: str
    staging_id: int
    source_row_hash: str
    id_sales_order: int
    id_faktur: int | None


@dataclass(frozen=True)
class ExistingLine:
    staging_id: int
    source_row_hash: str
    id_sales_order_detail: int


@dataclass(frozen=True)
class TargetColumn:
    name: str
    nullable: bool
    default: str | None
    is_identity: bool
    is_generated: bool
    max_length: int | None

    @property
    def needs_value(self) -> bool:
        return not self.nullable and self.default is None and not self.is_identity and not self.is_generated


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


def parse_decimal(value: Any, field: str, *, allow_negative: bool = False) -> tuple[Decimal | None, str | None]:
    text = clean(value)
    if text is None:
        return None, f"blank_{field}"
    if not DECIMAL_RE.fullmatch(text):
        return None, f"invalid_{field}_format"
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None, f"invalid_{field}_format"
    if not parsed.is_finite():
        return None, f"invalid_{field}_format"
    if not allow_negative and parsed < 0:
        return None, f"negative_{field}"
    return parsed, None


def parse_nonnegative_integer(value: Any, field: str) -> tuple[int | None, str | None]:
    parsed, reason = parse_decimal(value, field)
    if reason:
        return None, reason
    assert parsed is not None
    if parsed != parsed.to_integral_value():
        return None, f"non_integral_{field}"
    integer = int(parsed)
    if integer > MAX_INT32:
        return None, f"{field}_out_of_int32_range"
    return integer, None


def parse_date(value: Any, field: str, *, required: bool = True) -> tuple[date | None, str | None]:
    text = clean(value)
    if text is None:
        return (None, f"blank_{field}") if required else (None, None)
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
    return None, f"invalid_{field}_format"


def normalized_status(value: Any) -> str | None:
    text = clean(value)
    return text.upper() if text else None


def document_code(source_system: str, source_nota: str) -> str:
    """Make a visible, source-qualified and injective document code.

    ``norm`` preserves interior whitespace, so removing it here would make
    two distinct source identities collide (for example ``A B`` and ``AB``).
    A compact source-identity digest prevents that while retaining a readable
    Nota fragment for operators.
    """

    source_nota_norm = norm(source_nota)
    if source_nota_norm is None:
        raise ValidationError("Nota sumber kosong setelah normalisasi whitespace.")
    readable = re.sub(r"[^0-9A-Za-z._-]+", "_", source_nota.strip()).strip("_") or "NOTA"
    identity = f"{source_system}\x1f{SOURCE_HEADER_TABLE}\x1f{source_nota_norm}"
    suffix = hashlib.sha256(identity.encode("utf-8", errors="surrogatepass")).hexdigest()[:12]
    return f"LEG-{SOURCE_TAG[source_system]}-HJ-{readable}-{suffix}"


def ledger_source_id(source_system: str, source_table: str, source_nota_norm: str) -> str:
    # A fixed-size hash keeps the target inventory_ledger source_id within the
    # historical VARCHAR(80) bound without losing the complete identity in the
    # registry/audit tables.
    identity = f"{source_system}\x1f{source_table}\x1f{source_nota_norm}"
    digest = hashlib.sha256(identity.encode("utf-8", errors="surrogatepass")).hexdigest()[:40]
    return f"{SOURCE_TAG[source_system]}-HJ-{digest}"


def money_equal(left: Decimal, right: Decimal, tolerance: Decimal) -> bool:
    return abs(left - right) <= tolerance


def source_key(source_system: str, source_table: str, nota_norm: str) -> tuple[str, str, str]:
    return source_system, source_table, nota_norm


def line_key(source_system: str, source_table: str, nota_norm: str, urut_norm: str) -> tuple[str, str, str, str]:
    return source_system, source_table, nota_norm, urut_norm


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bdm-schema", help="Schema staging final BDM Solo untuk modul sales.")
    parser.add_argument("--tmp-schema", help="Schema staging final TMP Solo untuk modul sales.")
    parser.add_argument("--batch-id", default="active_sales_source_aware_final_20260830")
    parser.add_argument("--apply", action="store_true", help="Tulis transaksi aktif ke PostgreSQL.")
    parser.add_argument(
        "--delivered-ledger-policy",
        choices=("hold_delivered", "ledger_zero_cost"),
        default="hold_delivered",
        help=(
            "hold_delivered (default) menahan RL. ledger_zero_cost tetap ada "
            "untuk kompatibilitas CLI, tetapi sengaja ditolak sampai HPP/inbound "
            "historis direkonsiliasi."
        ),
    )
    parser.add_argument("--confirm-ledger-zero-cost", help=argparse.SUPPRESS)
    parser.add_argument(
        "--confirm-target-erp-maintenance-window",
        help=(
            "Wajib persis I_CONFIRM_TARGET_ERP_MAINTENANCE_WINDOW bersama --apply, "
            "karena apply mengunci tabel transaksi ERP."
        ),
    )
    parser.add_argument(
        "--money-tolerance",
        default="0.05",
        help="Selisih maksimum header vs jumlah detail (default 0.05).",
    )
    parser.add_argument("--statement-timeout-seconds", type=int, default=120)
    parser.add_argument(
        "--connect-timeout-seconds",
        type=int,
        default=int(os.getenv("MIGRATION_PG_CONNECT_TIMEOUT", "10")),
        help="Batas koneksi PostgreSQL untuk dry-run/apply (default: 10).",
    )
    parser.add_argument("--pg-database", default=os.getenv("MIGRATION_PG_DATABASE", "budimas_dev"))
    parser.add_argument("--pg-user", default=os.getenv("MIGRATION_PG_USER", "postgres"))
    parser.add_argument("--pg-host", default=os.getenv("MIGRATION_PG_HOST", "127.0.0.1"))
    parser.add_argument("--pg-port", type=int, default=int(os.getenv("MIGRATION_PG_PORT", "5432")))
    parser.add_argument("--output", type=Path, help="Opsional: simpan laporan JSON lokal.")
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Jangan tampilkan heartbeat JSON di stderr saat dry-run/apply berjalan.",
    )
    parser.add_argument("--self-test", action="store_true", help="Jalankan test parser tanpa database.")
    return parser.parse_args()


def ensure_cli_args(args: argparse.Namespace) -> Decimal:
    if args.self_test:
        return Decimal("0")
    if not args.bdm_schema or not args.tmp_schema:
        raise ValidationError("--bdm-schema dan --tmp-schema wajib diisi.")
    ident(args.bdm_schema)
    ident(args.tmp_schema)
    if args.bdm_schema == args.tmp_schema:
        raise ValidationError("Schema BDM dan TMP harus berbeda.")
    if not BATCH_RE.fullmatch(str(args.batch_id)):
        raise ValidationError("--batch-id hanya boleh huruf kecil, angka, titik, minus, dan underscore.")
    if not 1 <= args.statement_timeout_seconds <= 3600:
        raise ValidationError("--statement-timeout-seconds harus 1..3600.")
    if not 1 <= args.connect_timeout_seconds <= 60:
        raise ValidationError("--connect-timeout-seconds harus 1..60.")
    tolerance, reason = parse_decimal(args.money_tolerance, "money_tolerance")
    if reason or tolerance is None:
        raise ValidationError("--money-tolerance harus desimal tidak negatif.")
    if args.delivered_ledger_policy == "ledger_zero_cost" or args.confirm_ledger_zero_cost:
        raise ValidationError(
            "ledger_zero_cost dinonaktifkan sampai opening-stock/inbound dan HPP historis direkonsiliasi."
        )
    if args.apply and args.confirm_target_erp_maintenance_window != TARGET_ERP_MAINTENANCE_CONFIRMATION:
        raise ValidationError(
            "--apply membutuhkan --confirm-target-erp-maintenance-window "
            f"{TARGET_ERP_MAINTENANCE_CONFIRMATION}."
        )
    return tolerance


def fetch_stage_columns(cur, schemas: list[str]) -> dict[tuple[str, str], set[str]]:
    cur.execute(
        """
        SELECT table_schema, table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = ANY(%s)
          AND table_name = ANY(%s)
        """,
        (schemas, [*STAGE_METADATA_TABLES, *STAGE_TABLES]),
    )
    result: dict[tuple[str, str], set[str]] = {}
    for schema, table, column in cur.fetchall():
        result.setdefault((str(schema), str(table)), set()).add(str(column))
    return result


def parse_manifest_columns(raw: Any, schema: str, legacy_table: str) -> tuple[str, ...]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"Manifest {schema}/{legacy_table} memiliki source_columns tidak valid.") from exc
    if not isinstance(raw, list) or not all(isinstance(item, str) and item.strip() for item in raw):
        raise ValidationError(f"Manifest {schema}/{legacy_table} tidak memiliki source_columns valid.")
    # Stager sanitizes names deterministically.  Input source names in our two
    # sales tables are already simple, but this keeps the check aligned with it.
    cleaned: list[str] = []
    seen: Counter[str] = Counter()
    for item in raw:
        name = re.sub(r"[^0-9a-zA-Z_]+", "_", item.strip())
        name = re.sub(r"_+", "_", name).strip("_").lower() or "col"
        if name[0].isdigit():
            name = f"c_{name}"
        seen[name] += 1
        cleaned.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return tuple(cleaned)


def stage_metadata(
    cur,
    schema: str,
    expected_source: str,
    table_columns: dict[tuple[str, str], set[str]],
) -> StageMetadata:
    run_columns = table_columns.get((schema, "__stage_run"), set())
    manifest_columns = table_columns.get((schema, "__stage_manifest"), set())
    required_run = {
        "id", "source_system", "status", "consistency_mode", "target_company_id", "target_branch_id"
    }
    required_manifest = {"legacy_table", "module", "source_columns", "source_row_count", "staged_row_count", "status"}
    if required_run - run_columns or required_manifest - manifest_columns:
        missing = []
        if required_run - run_columns:
            missing.append("__stage_run=" + ",".join(sorted(required_run - run_columns)))
        if required_manifest - manifest_columns:
            missing.append("__stage_manifest=" + ",".join(sorted(required_manifest - manifest_columns)))
        raise ValidationError(f"Struktur metadata staging {schema} tidak lengkap ({'; '.join(missing)}).")
    for table in STAGE_TABLES:
        missing = STAGE_FIXED_COLUMNS - table_columns.get((schema, table), set())
        if missing:
            raise ValidationError(f"{schema}.{table} tidak memiliki kolom staging: {', '.join(sorted(missing))}.")

    preview_expr = "is_preview" if "is_preview" in run_columns else "(consistency_mode <> 'snapshot')"
    maintenance_window_expr = "maintenance_window_id" if "maintenance_window_id" in run_columns else "NULL::text"
    freeze_attested_expr = "maintenance_freeze_attested" if "maintenance_freeze_attested" in run_columns else "FALSE"
    freeze_confirmed_expr = (
        "maintenance_freeze_confirmed_at" if "maintenance_freeze_confirmed_at" in run_columns else "NULL::timestamptz"
    )
    isolation_expr = "source_transaction_isolation" if "source_transaction_isolation" in run_columns else "NULL::text"
    lock_timeout_expr = "source_lock_timeout_ms" if "source_lock_timeout_ms" in run_columns else "NULL::integer"
    cur.execute(
        f"""
        SELECT id, source_system, status, consistency_mode, {preview_expr},
               {maintenance_window_expr}, {freeze_attested_expr}, {freeze_confirmed_expr},
               {isolation_expr}, {lock_timeout_expr}, target_company_id, target_branch_id
        FROM {stage_metadata_table(schema, '__stage_run')}
        ORDER BY id DESC
        LIMIT 1
        """
    )
    run = cur.fetchone()
    if run is None:
        raise ValidationError(f"Staging {schema} tidak memiliki __stage_run.")
    if str(run[1]) != expected_source:
        raise ValidationError(f"Staging {schema} milik {run[1]!r}, bukan {expected_source!r}.")
    if str(run[2]) not in {"completed", "completed_preview"}:
        raise ValidationError(f"Staging {schema} belum selesai (status={run[2]!r}).")

    cur.execute(
        f"""
        SELECT lower(btrim(legacy_table)), status, module, source_columns, source_row_count, staged_row_count
        FROM {stage_metadata_table(schema, '__stage_manifest')}
        WHERE lower(btrim(legacy_table)) = ANY(%s)
        """,
        (list(STAGE_TABLES),),
    )
    manifests: dict[str, tuple[int, tuple[str, ...]]] = {}
    for table, status, module, source_columns, source_count, staged_count in cur.fetchall():
        table = str(table)
        if table in manifests:
            raise ValidationError(f"{schema} memiliki manifest ganda untuk {table}.")
        if str(status) != "done" or str(module) != "sales":
            raise ValidationError(f"Manifest {schema}/{table} belum valid (status={status!r}, module={module!r}).")
        if source_count is None or staged_count is None or int(source_count) != int(staged_count):
            raise ValidationError(
                f"Manifest {schema}/{table} count tidak konsisten: source={source_count}, staged={staged_count}."
            )
        manifests[table] = (int(staged_count), parse_manifest_columns(source_columns, schema, table))
    missing_manifest = set(STAGE_TABLES) - set(manifests)
    if missing_manifest:
        raise ValidationError(f"{schema} belum memiliki manifest sales lengkap: {', '.join(sorted(missing_manifest))}.")
    for table, required in (("hjualsm", HEADER_REQUIRED_COLUMNS), ("djualsm", DETAIL_REQUIRED_COLUMNS)):
        source_columns = set(manifests[table][1])
        missing_source = required - source_columns
        if missing_source:
            raise ValidationError(
                f"{schema}.{table} tidak memiliki kolom sumber wajib: {', '.join(sorted(missing_source))}."
            )
        missing_staged = source_columns - table_columns[(schema, table)]
        if missing_staged:
            raise ValidationError(
                f"{schema}.{table} tidak memuat kolom dari manifest: {', '.join(sorted(missing_staged))}."
            )
    return StageMetadata(
        schema=schema,
        source_system=expected_source,
        run_id=int(run[0]),
        status=str(run[2]),
        consistency_mode=str(run[3]),
        is_preview=bool(run[4]),
        maintenance_window_id=clean(run[5]),
        maintenance_freeze_attested=bool(run[6]),
        maintenance_freeze_confirmed_at=run[7] if isinstance(run[7], datetime) else None,
        source_transaction_isolation=clean(run[8]),
        source_lock_timeout_ms=int(run[9]) if run[9] is not None else None,
        target_company_id=int(run[10]),
        target_branch_id=int(run[11]),
        manifest_rows={table: count for table, (count, _columns) in manifests.items()},
        source_columns={table: columns for table, (_count, columns) in manifests.items()},
    )


def validate_stage_provenance(cur, stage: StageMetadata) -> None:
    for table, expected_legacy in SOURCE_TABLES.items():
        cur.execute(
            f"""
            SELECT COUNT(*)::bigint,
                   COUNT(*) FILTER (WHERE source_system IS DISTINCT FROM %s)::bigint,
                   COUNT(*) FILTER (WHERE target_company_id IS DISTINCT FROM %s OR target_branch_id IS DISTINCT FROM %s)::bigint,
                   COUNT(*) FILTER (WHERE lower(btrim(legacy_table)) <> %s)::bigint,
                   COUNT(*) FILTER (WHERE source_row_hash IS NULL OR btrim(source_row_hash) = '')::bigint
            FROM {qtable(stage.schema, table)}
            """,
            (stage.source_system, stage.target_company_id, stage.target_branch_id, table),
        )
        actual, wrong_source, wrong_scope, wrong_table, missing_hash = (int(value) for value in cur.fetchone())
        if actual != stage.manifest_rows[table]:
            raise ValidationError(
                f"{stage.schema}.{table} berisi {actual}, bukan {stage.manifest_rows[table]} menurut manifest."
            )
        invalid = {
            "wrong_source_system": wrong_source,
            "wrong_target_scope": wrong_scope,
            "wrong_legacy_table": wrong_table,
            "blank_source_row_hash": missing_hash,
        }
        if any(invalid.values()):
            raise ValidationError(
                f"Provenance {stage.schema}.{table} tidak valid: "
                + ", ".join(f"{key}={value}" for key, value in invalid.items() if value)
            )


def fetch_headers(cur, stage: StageMetadata) -> list[HeaderRow]:
    cur.execute(
        f"""
        SELECT staging_id, source_row_hash, nota, tanggal, kodesales, namasales,
               kodecustomer, namacustomer, kodeprinciple, keterangan, jatuhtempo,
               totalpenjualan, totalretur, terbayar, stnota, tglreal
        FROM {qtable(stage.schema, 'hjualsm')}
        WHERE source_system = %s
        ORDER BY staging_id
        """,
        (stage.source_system,),
    )
    return [
        HeaderRow(
            source_system=stage.source_system,
            stage_schema=stage.schema,
            stage_run_id=stage.run_id,
            staging_id=int(record[0]),
            source_row_hash=str(record[1]),
            source_table=SOURCE_HEADER_TABLE,
            nota=clean(record[2]),
            tanggal_raw=clean(record[3]),
            kodesales=clean(record[4]),
            namasales=clean(record[5]),
            kodecustomer=clean(record[6]),
            namacustomer=clean(record[7]),
            kodeprinciple=clean(record[8]),
            keterangan=clean(record[9]),
            jatuhtempo_raw=clean(record[10]),
            totalpenjualan_raw=clean(record[11]),
            totalretur_raw=clean(record[12]),
            terbayar_raw=clean(record[13]),
            stnota=clean(record[14]),
            tglreal_raw=clean(record[15]),
        )
        for record in cur.fetchall()
    ]


def fetch_details(cur, stage: StageMetadata) -> list[DetailRow]:
    cur.execute(
        f"""
        SELECT staging_id, source_row_hash, nota, urut, tanggal, kodestok, masterkode,
               ct, pc, unit, satuan, perunit, jumlah, harga, jumlahexppn, jumlahharga,
               kodesales, kodecustomer, kodeprinciple,
               disc1, disc2, disc3, discrp, discrp1, discrp2, discrp3
        FROM {qtable(stage.schema, 'djualsm')}
        WHERE source_system = %s
        ORDER BY staging_id
        """,
        (stage.source_system,),
    )
    return [
        DetailRow(
            source_system=stage.source_system,
            stage_schema=stage.schema,
            stage_run_id=stage.run_id,
            staging_id=int(record[0]),
            source_row_hash=str(record[1]),
            source_table=SOURCE_HEADER_TABLE,
            nota=clean(record[2]),
            urut=clean(record[3]),
            tanggal_raw=clean(record[4]),
            kodestok=clean(record[5]),
            masterkode=clean(record[6]),
            ct=clean(record[7]),
            pc=clean(record[8]),
            unit_raw=clean(record[9]),
            satuan_raw=clean(record[10]),
            perunit_raw=clean(record[11]),
            jumlah_raw=clean(record[12]),
            harga_raw=clean(record[13]),
            jumlahexppn_raw=clean(record[14]),
            jumlahharga_raw=clean(record[15]),
            kodesales=clean(record[16]),
            kodecustomer=clean(record[17]),
            kodeprinciple=clean(record[18]),
            disc1_raw=clean(record[19]),
            disc2_raw=clean(record[20]),
            disc3_raw=clean(record[21]),
            discrp_raw=clean(record[22]),
            discrp1_raw=clean(record[23]),
            discrp2_raw=clean(record[24]),
            discrp3_raw=clean(record[25]),
        )
        for record in cur.fetchall()
    ]


def fetch_android_counts(cur, stage: StageMetadata) -> tuple[int, int]:
    cur.execute(
        f"SELECT COUNT(*)::bigint FROM {qtable(stage.schema, 'hjualsmandroid')} WHERE source_system=%s",
        (stage.source_system,),
    )
    headers = int(cur.fetchone()[0])
    cur.execute(
        f"SELECT COUNT(*)::bigint FROM {qtable(stage.schema, 'djualsmandroid')} WHERE source_system=%s",
        (stage.source_system,),
    )
    return headers, int(cur.fetchone()[0])


def load_source_context(cur) -> dict[str, tuple[int, int]]:
    cur.execute(
        f"""
        SELECT source_system, target_company_id, target_branch_id
        FROM {qtable(REGISTRY_SCHEMA, 'source_context')}
        WHERE source_system = ANY(%s)
        """,
        (list(SOURCE_SYSTEMS),),
    )
    result = {str(source): (int(company), int(branch)) for source, company, branch in cur.fetchall()}
    if set(result) != set(SOURCE_SYSTEMS):
        raise ValidationError("source_context BDM/TMP belum lengkap.")
    return result


def load_committed_mappings(cur) -> tuple[
    dict[tuple[str, str], int],
    dict[tuple[str, str], int],
    dict[tuple[str, str, str], int],
    dict[tuple[str, str, str], int],
    dict[tuple[str, str, str, str, int], list[UomTarget]],
]:
    customers: dict[tuple[str, str], int] = {}
    principals: dict[tuple[str, str], int] = {}
    sales: dict[tuple[str, str, str], int] = {}
    products: dict[tuple[str, str, str], int] = {}
    uoms: dict[tuple[str, str, str, str, int], list[UomTarget]] = defaultdict(list)

    cur.execute(
        f"""
        SELECT source_system, source_customer_code_norm, id_customer
        FROM {qtable(REGISTRY_SCHEMA, 'customer_map')}
        WHERE source_system = ANY(%s)
        """,
        (list(SOURCE_SYSTEMS),),
    )
    for source, code, target in cur.fetchall():
        key = (str(source), str(code))
        if key in customers:
            raise ValidationError("customer_map memiliki key sumber duplikat.")
        customers[key] = int(target)

    cur.execute(
        f"""
        SELECT source_system, source_principal_code_norm, id_principal
        FROM {qtable(REGISTRY_SCHEMA, 'principal_map')}
        WHERE source_system = ANY(%s)
        """,
        (list(SOURCE_SYSTEMS),),
    )
    for source, code, target in cur.fetchall():
        key = (str(source), str(code))
        if key in principals:
            raise ValidationError("principal_map memiliki key sumber duplikat.")
        principals[key] = int(target)

    cur.execute(
        f"""
        SELECT source_system, source_principal_code_norm, source_sales_code_norm, id_sales
        FROM {qtable(REGISTRY_SCHEMA, 'sales_map')}
        WHERE source_system = ANY(%s)
        """,
        (list(SOURCE_SYSTEMS),),
    )
    for source, principal, code, target in cur.fetchall():
        key = (str(source), str(principal), str(code))
        if key in sales:
            raise ValidationError("sales_map memiliki key sumber duplikat.")
        sales[key] = int(target)

    cur.execute(
        f"""
        SELECT source_system, source_principal_code_norm, source_sku_norm, id_produk
        FROM {qtable(REGISTRY_SCHEMA, 'product_map')}
        WHERE source_system = ANY(%s)
        """,
        (list(SOURCE_SYSTEMS),),
    )
    for source, principal, sku, target in cur.fetchall():
        key = (str(source), str(principal), str(sku))
        if key in products:
            raise ValidationError("product_map memiliki key sumber duplikat.")
        products[key] = int(target)

    # Re-check the target UOM now, rather than trusting an old registry row if
    # someone edited produk_uom after its mapping was approved.
    cur.execute(
        f"""
        SELECT m.source_system, m.source_principal_code_norm, m.source_sku_norm,
               m.source_uom_code_norm, m.source_factor, m.id_produk, m.id_produk_uom,
               pu.id_produk, pu.level, pu.faktor_konversi, lower(btrim(pu.kode))
        FROM {qtable(REGISTRY_SCHEMA, 'product_uom_map')} m
        JOIN public.produk_uom pu ON pu.id = m.id_produk_uom
        WHERE m.source_system = ANY(%s)
        """,
        (list(SOURCE_SYSTEMS),),
    )
    for record in cur.fetchall():
        source, principal, sku, code, factor, id_produk, uom_id, actual_produk, level, actual_factor, actual_code = record
        if int(actual_produk) != int(id_produk) or int(actual_factor) != int(factor) or str(actual_code) != str(code):
            raise ValidationError("Target produk_uom berubah dan tidak lagi cocok dengan registry committed.")
        if int(level) not in (1, 2, 3):
            raise ValidationError("Registry product_uom_map mengarah ke level target di luar 1/2/3.")
        key = (str(source), str(principal), str(sku), str(code), int(factor))
        uoms[key].append(UomTarget(int(id_produk), int(uom_id), int(level), int(factor)))

    return customers, principals, sales, products, uoms


def load_plafon_targets(cur) -> dict[tuple[int, int, int], list[int]]:
    cur.execute("SELECT id, id_customer, id_principal, id_sales FROM public.plafon WHERE id_customer IS NOT NULL AND id_principal IS NOT NULL AND id_sales IS NOT NULL")
    result: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for item_id, customer, principal, sales in cur.fetchall():
        result[(int(customer), int(principal), int(sales))].append(int(item_id))
    return result


def load_existing_documents(cur) -> tuple[
    dict[tuple[str, str, str], ExistingDocument],
    dict[tuple[str, str, str, str], ExistingLine],
]:
    cur.execute(
        f"""
        SELECT source_system, source_table, source_nota_norm, stage_schema, source_staging_id,
               source_row_hash, id_sales_order, id_faktur
        FROM {qtable(REGISTRY_SCHEMA, 'sales_document_map')}
        WHERE source_system = ANY(%s)
        """,
        (list(SOURCE_SYSTEMS),),
    )
    documents: dict[tuple[str, str, str], ExistingDocument] = {}
    for source, table, nota, stage_schema, staging_id, row_hash, order_id, faktur_id in cur.fetchall():
        key = source_key(str(source), str(table), str(nota))
        if key in documents:
            raise ValidationError("sales_document_map memiliki source identity duplikat.")
        documents[key] = ExistingDocument(
            str(stage_schema), int(staging_id), str(row_hash), int(order_id), int(faktur_id) if faktur_id is not None else None
        )
    cur.execute(
        f"""
        SELECT source_system, source_table, source_nota_norm, source_urut_norm,
               source_staging_id, source_row_hash, id_sales_order_detail
        FROM {qtable(REGISTRY_SCHEMA, 'sales_document_line_map')}
        WHERE source_system = ANY(%s)
        """,
        (list(SOURCE_SYSTEMS),),
    )
    lines: dict[tuple[str, str, str, str], ExistingLine] = {}
    for source, table, nota, urut, staging_id, row_hash, target in cur.fetchall():
        key = line_key(str(source), str(table), str(nota), str(urut))
        if key in lines:
            raise ValidationError("sales_document_line_map memiliki source identity duplikat.")
        lines[key] = ExistingLine(int(staging_id), str(row_hash), int(target))
    return documents, lines


def header_hold(row: HeaderRow, reason: str, details: dict[str, Any] | None = None) -> Hold:
    return Hold(
        source_system=row.source_system,
        stage_schema=row.stage_schema,
        stage_run_id=row.stage_run_id,
        source_table=row.source_table,
        reason=reason,
        source_staging_id=row.staging_id,
        source_nota=row.nota,
        source_nota_norm=norm(row.nota),
        source_row_hash=row.source_row_hash,
        details=details,
    )


def detail_hold(row: DetailRow, reason: str, details: dict[str, Any] | None = None) -> Hold:
    return Hold(
        source_system=row.source_system,
        stage_schema=row.stage_schema,
        stage_run_id=row.stage_run_id,
        source_table=row.source_table,
        reason=reason,
        source_staging_id=row.staging_id,
        source_nota=row.nota,
        source_nota_norm=norm(row.nota),
        source_urut=row.urut,
        source_urut_norm=norm(row.urut),
        source_row_hash=row.source_row_hash,
        details=details,
    )


def resolve_line(
    row: DetailRow,
    header: HeaderRow,
    principal_norm: str,
    header_order_date: date,
    products: dict[tuple[str, str, str], int],
    uoms: dict[tuple[str, str, str, str, int], list[UomTarget]],
) -> tuple[LinePlan | None, Hold | None]:
    nota_norm = norm(row.nota)
    urut_norm = norm(row.urut)
    sku_norm = norm(row.kodestok)
    detail_principal_norm = norm(row.kodeprinciple)
    header_sales_norm = norm(header.kodesales)
    detail_sales_norm = norm(row.kodesales)
    header_customer_norm = norm(header.kodecustomer)
    detail_customer_norm = norm(row.kodecustomer)
    if nota_norm is None or urut_norm is None or sku_norm is None:
        return None, detail_hold(row, "missing_detail_identity")
    if detail_principal_norm != principal_norm:
        return None, detail_hold(
            row,
            "detail_principal_not_equal_header",
            {"header_principal": header.kodeprinciple, "detail_principal": row.kodeprinciple},
        )
    if header_sales_norm is None or detail_sales_norm is None or detail_sales_norm != header_sales_norm:
        return None, detail_hold(
            row,
            "detail_sales_not_equal_header",
            {"header_sales": header.kodesales, "detail_sales": row.kodesales},
        )
    if header_customer_norm is None or detail_customer_norm is None or detail_customer_norm != header_customer_norm:
        return None, detail_hold(
            row,
            "detail_customer_not_equal_header",
            {"header_customer": header.kodecustomer, "detail_customer": row.kodecustomer},
        )
    detail_date, detail_date_reason = parse_date(row.tanggal_raw, "detail_tanggal")
    if detail_date_reason:
        return None, detail_hold(row, detail_date_reason)
    if detail_date != header_order_date:
        return None, detail_hold(
            row,
            "detail_date_not_equal_header",
            {"header_date": header_order_date, "detail_date": detail_date},
        )
    product_id = products.get((row.source_system, principal_norm, sku_norm))
    if product_id is None:
        return None, detail_hold(row, "missing_committed_product_map")
    base_code = norm(row.pc)
    outer_code = norm(row.ct)
    if base_code is None or outer_code is None:
        return None, detail_hold(row, "blank_source_uom_code")
    unit, reason = parse_nonnegative_integer(row.unit_raw, "unit")
    if reason:
        return None, detail_hold(row, reason)
    pieces, reason = parse_nonnegative_integer(row.satuan_raw, "satuan")
    if reason:
        return None, detail_hold(row, reason)
    factor, reason = parse_nonnegative_integer(row.perunit_raw, "perunit")
    if reason:
        return None, detail_hold(row, reason)
    total, reason = parse_nonnegative_integer(row.jumlah_raw, "jumlah")
    if reason:
        return None, detail_hold(row, reason)
    assert unit is not None and pieces is not None and factor is not None and total is not None
    if factor <= 0:
        return None, detail_hold(row, "nonpositive_perunit")
    calculated_total = unit * factor + pieces
    if calculated_total != total:
        return None, detail_hold(
            row,
            "quantity_formula_mismatch",
            {"unit": unit, "perunit": factor, "satuan": pieces, "jumlah": total, "calculated": calculated_total},
        )
    if total > MAX_INT32:
        return None, detail_hold(row, "jumlah_out_of_int32_range")
    base_candidates = uoms.get((row.source_system, principal_norm, sku_norm, base_code, 1), [])
    if len(base_candidates) != 1 or base_candidates[0].level != 1 or base_candidates[0].id_produk != product_id:
        return None, detail_hold(row, "missing_or_ambiguous_exact_base_uom_map")
    outer_candidates = uoms.get((row.source_system, principal_norm, sku_norm, outer_code, factor), [])
    if len(outer_candidates) != 1 or outer_candidates[0].id_produk != product_id:
        return None, detail_hold(row, "missing_or_ambiguous_exact_outer_uom_map")
    outer = outer_candidates[0]
    if outer.level == 1:
        if factor != 1 or outer.id_produk_uom != base_candidates[0].id_produk_uom:
            return None, detail_hold(row, "invalid_outer_base_uom_mapping")
        pieces_order, box_order, karton_order = total, 0, 0
    elif outer.level == 2:
        pieces_order, box_order, karton_order = pieces, unit, 0
    elif outer.level == 3:
        pieces_order, box_order, karton_order = pieces, 0, unit
    else:  # guarded on load, retained as a defensive branch
        return None, detail_hold(row, "unsupported_target_uom_level")
    price, reason = parse_decimal(row.harga_raw, "harga")
    if reason:
        return None, detail_hold(row, reason)
    dpp, reason = parse_decimal(row.jumlahexppn_raw, "jumlahexppn")
    if reason:
        return None, detail_hold(row, reason)
    total_price, reason = parse_decimal(row.jumlahharga_raw, "jumlahharga")
    if reason:
        return None, detail_hold(row, reason)
    percent_parts: list[Decimal] = []
    amount_parts: list[Decimal] = []
    for field, value in (("disc1", row.disc1_raw), ("disc2", row.disc2_raw), ("disc3", row.disc3_raw)):
        parsed, parsed_reason = parse_decimal(value or "0", field)
        if parsed_reason:
            return None, detail_hold(row, parsed_reason)
        assert parsed is not None
        percent_parts.append(parsed)
    for field, value in (
        ("discrp", row.discrp_raw),
        ("discrp1", row.discrp1_raw),
        ("discrp2", row.discrp2_raw),
        ("discrp3", row.discrp3_raw),
    ):
        parsed, parsed_reason = parse_decimal(value or "0", field)
        if parsed_reason:
            return None, detail_hold(row, parsed_reason)
        assert parsed is not None
        amount_parts.append(parsed)
    assert price is not None and dpp is not None and total_price is not None
    return (
        LinePlan(
            row=row,
            source_urut=row.urut or "",
            source_urut_norm=urut_norm,
            id_produk=product_id,
            id_base_uom=base_candidates[0].id_produk_uom,
            id_outer_uom=outer.id_produk_uom,
            outer_level=outer.level,
            outer_factor=factor,
            qty_base=total,
            pieces_order=pieces_order,
            box_order=box_order,
            karton_order=karton_order,
            harga_order=price,
            subtotal_dpp=dpp,
            subtotal_order=total_price,
            discount_amount=sum(amount_parts, Decimal("0")),
            source_discount_percent=sum(percent_parts, Decimal("0")),
            is_bonus=1 if total_price == 0 and total > 0 else 0,
        ),
        None,
    )


def classify_existing(
    plan: HeaderPlan,
    existing_documents: dict[tuple[str, str, str], ExistingDocument],
    existing_lines: dict[tuple[str, str, str, str], ExistingLine],
) -> tuple[bool, Hold | None]:
    key = source_key(plan.row.source_system, plan.row.source_table, plan.source_nota_norm)
    existing = existing_documents.get(key)
    if existing is None:
        return False, None
    if existing.source_row_hash != plan.row.source_row_hash:
        return False, header_hold(
            plan.row,
            "existing_document_source_hash_changed",
            {"existing_stage_schema": existing.stage_schema, "existing_staging_id": existing.staging_id},
        )
    if existing.id_faktur is None:
        return False, header_hold(plan.row, "existing_document_missing_faktur_map")
    for line in plan.lines:
        line_existing = existing_lines.get(
            line_key(plan.row.source_system, plan.row.source_table, plan.source_nota_norm, line.source_urut_norm)
        )
        if line_existing is None:
            return False, header_hold(plan.row, "existing_document_missing_line_map")
        if line_existing.source_row_hash != line.row.source_row_hash:
            return False, header_hold(plan.row, "existing_line_source_hash_changed")
    return True, None


def build_plans(
    cur,
    metadata: dict[str, StageMetadata],
    headers_by_source: dict[str, list[HeaderRow]],
    details_by_source: dict[str, list[DetailRow]],
    money_tolerance: Decimal,
    delivered_ledger_policy: str,
) -> tuple[list[HeaderPlan], list[HeaderPlan], list[Hold], dict[str, int]]:
    """Return inserts, unchanged existing documents, holds, and Android counts."""

    if delivered_ledger_policy != "hold_delivered":
        raise ValidationError(
            "Hanya policy hold_delivered yang tersedia sampai HPP/inbound historis direkonsiliasi."
        )

    contexts = load_source_context(cur)
    for source, stage in metadata.items():
        if contexts[source] != (stage.target_company_id, stage.target_branch_id):
            raise ValidationError(f"source_context {source} tidak cocok dengan scope staging final.")
    customers, principals, sales, products, uoms = load_committed_mappings(cur)
    plafons = load_plafon_targets(cur)
    existing_documents, existing_lines = load_existing_documents(cur)
    holds: list[Hold] = []
    inserts: list[HeaderPlan] = []
    unchanged: list[HeaderPlan] = []
    android_counts: dict[str, int] = {}

    for source in SOURCE_SYSTEMS:
        stage = metadata[source]
        android_headers, android_details = fetch_android_counts(cur, stage)
        android_counts[f"{source}_headers"] = android_headers
        android_counts[f"{source}_details"] = android_details
        if android_headers or android_details:
            holds.append(
                Hold(
                    source_system=source,
                    stage_schema=stage.schema,
                    stage_run_id=stage.run_id,
                    source_table=ANDROID_HEADER_TABLE,
                    reason="android_document_family_requires_source_qualified_cross_reference_review",
                    details={"header_rows": android_headers, "detail_rows": android_details},
                )
            )

        header_groups: dict[str, list[HeaderRow]] = defaultdict(list)
        detail_groups: dict[str, list[DetailRow]] = defaultdict(list)
        for header in headers_by_source[source]:
            header_nota_norm = norm(header.nota)
            if header_nota_norm is None:
                holds.append(header_hold(header, "blank_source_nota"))
            else:
                header_groups[header_nota_norm].append(header)
        for detail in details_by_source[source]:
            detail_nota_norm = norm(detail.nota)
            if detail_nota_norm is None:
                holds.append(detail_hold(detail, "blank_source_nota"))
            else:
                detail_groups[detail_nota_norm].append(detail)

        for nota_norm, grouped in header_groups.items():
            if len(grouped) > 1:
                for header in grouped:
                    holds.append(header_hold(header, "duplicate_source_header_nota", {"source_nota_norm": nota_norm, "count": len(grouped)}))
                continue
            header = grouped[0]
            details = detail_groups.pop(nota_norm, [])
            customer_norm = norm(header.kodecustomer)
            principal_norm = norm(header.kodeprinciple)
            sales_norm = norm(header.kodesales)
            if customer_norm is None or principal_norm is None or sales_norm is None:
                holds.append(header_hold(header, "blank_source_master_code"))
                continue
            id_customer = customers.get((source, customer_norm))
            id_principal = principals.get((source, principal_norm))
            id_sales = sales.get((source, principal_norm, sales_norm))
            missing_maps = []
            if id_customer is None:
                missing_maps.append("customer")
            if id_principal is None:
                missing_maps.append("principal")
            if id_sales is None:
                missing_maps.append("sales")
            if missing_maps:
                holds.append(header_hold(header, "missing_committed_header_mapping", {"missing": missing_maps}))
                continue
            plafon_matches = plafons.get((id_customer, id_principal, id_sales), [])
            if len(plafon_matches) != 1:
                holds.append(
                    header_hold(
                        header,
                        "missing_or_duplicate_target_plafon",
                        {"id_customer": id_customer, "id_principal": id_principal, "id_sales": id_sales, "matches": plafon_matches},
                    )
                )
                continue
            order_date, reason = parse_date(header.tanggal_raw, "tanggal")
            if reason:
                holds.append(header_hold(header, reason))
                continue
            due_date, due_reason = parse_date(header.jatuhtempo_raw, "jatuhtempo", required=False)
            if due_reason:
                holds.append(header_hold(header, due_reason))
                continue
            status = normalized_status(header.stnota)
            if status == "RL":
                holds.append(header_hold(header, "delivered_requires_reconciled_hpp_and_inbound_ledger"))
                continue
            elif status == "BT":
                # Old migration SQL used -1/4 here, but the current ERP
                # status lifecycle has not established -1 as a legal order
                # state. Do not manufacture a cancellation in an active
                # system from that historical assumption.
                holds.append(header_hold(header, "cancelled_status_semantics_unverified", {"stnota": status}))
                continue
            else:
                holds.append(header_hold(header, "unsupported_nonfinal_source_status", {"stnota": status}))
                continue
            total_penjualan, total_reason = parse_decimal(header.totalpenjualan_raw, "totalpenjualan")
            if total_reason:
                holds.append(header_hold(header, total_reason))
                continue
            total_retur, retur_reason = parse_decimal(header.totalretur_raw or "0", "totalretur")
            if retur_reason:
                holds.append(header_hold(header, retur_reason))
                continue
            if total_retur is not None and total_retur != 0:
                # Return details/lifecycle (good/bad stock, credit note and
                # receivable treatment) are imported separately. Do not
                # lower a faktur balance based only on an aggregate header.
                holds.append(
                    header_hold(
                        header,
                        "nonzero_return_requires_source_qualified_return_import",
                        {"source_total_retur": total_retur},
                    )
                )
                continue
            source_terbayar, paid_reason = parse_decimal(header.terbayar_raw or "0", "terbayar")
            if paid_reason:
                holds.append(header_hold(header, paid_reason))
                continue
            assert order_date is not None and total_penjualan is not None and total_retur is not None
            line_group_reasons = False
            if not details and total_penjualan != 0:
                holds.append(header_hold(header, "header_without_detail"))
                continue
            line_by_urut: dict[str, list[DetailRow]] = defaultdict(list)
            for detail in details:
                urut_norm = norm(detail.urut)
                if urut_norm is None:
                    holds.append(detail_hold(detail, "blank_source_urut"))
                    line_group_reasons = True
                else:
                    line_by_urut[urut_norm].append(detail)
            for urut_norm, same_urut in line_by_urut.items():
                if len(same_urut) > 1:
                    for detail in same_urut:
                        holds.append(detail_hold(detail, "duplicate_source_line_urut", {"source_urut_norm": urut_norm, "count": len(same_urut)}))
                    line_group_reasons = True
            lines: list[LinePlan] = []
            if not line_group_reasons:
                for detail in details:
                    line, line_hold = resolve_line(detail, header, principal_norm, order_date, products, uoms)
                    if line_hold:
                        holds.append(line_hold)
                        line_group_reasons = True
                    elif line:
                        lines.append(line)
            if line_group_reasons:
                holds.append(header_hold(header, "header_detail_validation_failed"))
                continue
            if not lines and total_penjualan != 0:
                holds.append(header_hold(header, "header_without_eligible_detail"))
                continue
            line_total = sum((line.subtotal_order for line in lines), Decimal("0"))
            if not money_equal(total_penjualan, line_total, money_tolerance):
                holds.append(
                    header_hold(
                        header,
                        "header_detail_total_mismatch",
                        {"header_total": total_penjualan, "detail_total": line_total, "tolerance": money_tolerance},
                    )
                )
                continue
            subtotal_dpp = sum((line.subtotal_dpp for line in lines), Decimal("0"))
            subtotal_diskon = sum((line.discount_amount for line in lines), Decimal("0"))
            tax = max(total_penjualan - subtotal_dpp, Decimal("0"))
            try:
                visible_code = document_code(source, header.nota or "")
            except ValidationError:
                holds.append(header_hold(header, "invalid_source_nota_for_human_document_code"))
                continue
            plan = HeaderPlan(
                row=header,
                source_nota=header.nota or "",
                source_nota_norm=nota_norm,
                human_document_code=visible_code,
                ledger_source_id=ledger_source_id(source, SOURCE_HEADER_TABLE, nota_norm),
                id_customer=id_customer,
                id_principal=id_principal,
                id_sales=id_sales,
                id_plafon=plafon_matches[0],
                id_perusahaan=stage.target_company_id,
                id_cabang=stage.target_branch_id,
                tanggal_order=order_date,
                tanggal_terkirim=delivery_date,
                tanggal_jatuh_tempo=due_date,
                status_order=status_order,
                status_faktur=status_faktur,
                total_penjualan=total_penjualan,
                total_retur=total_retur,
                source_terbayar=source_terbayar,
                subtotal_dpp=subtotal_dpp,
                subtotal_diskon=subtotal_diskon,
                pajak=tax,
                lines=tuple(sorted(lines, key=lambda item: item.source_urut_norm)),
            )
            is_existing, existing_hold = classify_existing(plan, existing_documents, existing_lines)
            if existing_hold:
                holds.append(existing_hold)
            elif is_existing:
                unchanged.append(plan)
            else:
                inserts.append(plan)
        for orphan_nota, orphan_details in detail_groups.items():
            for detail in orphan_details:
                holds.append(detail_hold(detail, "detail_without_source_header", {"source_nota_norm": orphan_nota}))

    return inserts, unchanged, holds, android_counts


def target_columns(cur, table: str) -> dict[str, TargetColumn]:
    cur.execute(
        """
        SELECT column_name, is_nullable, column_default, is_identity, is_generated, character_maximum_length
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s
        """,
        (table,),
    )
    result: dict[str, TargetColumn] = {}
    for name, nullable, default, identity, generated, max_length in cur.fetchall():
        result[str(name)] = TargetColumn(
            name=str(name),
            nullable=str(nullable).upper() == "YES",
            default=str(default) if default is not None else None,
            is_identity=str(identity).upper() == "YES",
            is_generated=str(generated).upper() != "NEVER",
            max_length=int(max_length) if max_length is not None else None,
        )
    if not result:
        raise ValidationError(f"Tabel public.{table} tidak ditemukan.")
    return result


def validate_target_schema(cur, ledger_enabled: bool) -> dict[str, dict[str, TargetColumn]]:
    needed = ["sales_order", "faktur", "sales_order_detail"]
    if ledger_enabled:
        needed.append("inventory_ledger")
    columns = {table: target_columns(cur, table) for table in needed}
    supplied: dict[str, set[str]] = {
        "sales_order": {
            "id_plafon", "tanggal_order", "tanggal_faktur", "tanggal_terkirim", "tanggal_jatuh_tempo",
            "nama_sales", "pic_customer", "status_order", "total_order", "no_order", "no_faktur", "keterangan", "id_cabang",
        },
        "faktur": {
            "id_sales_order", "no_faktur", "nama_fakturist", "status_faktur", "jenis_faktur",
            "subtotal_penjualan", "subtotal_diskon", "total_penjualan", "total_dana_diterima",
            "pajak", "dpp", "draft_total_penjualan", "nominal_retur",
        },
        "sales_order_detail": {
            "hargaorder", "subtotaldelivered", "is_bonus", "estimasi_kubikasi", "id_sales_order", "id_produk",
            "pieces_order", "box_order", "karton_order", "pieces_booked", "box_booked", "karton_booked",
            "pieces_picked", "box_picked", "karton_picked", "pieces_shipped", "box_shipped", "karton_shipped",
            "pieces_delivered", "box_delivered", "karton_delivered", "subtotalorder",
            "total_nilai_discount", "total_persen_diskon",
        },
    }
    if ledger_enabled:
        supplied["inventory_ledger"] = {
            "movement_date", "id_produk", "id_cabang", "id_perusahaan", "id_principal", "source_module",
            "source_type", "source_id", "source_detail_id", "direction", "qty", "unit_cost", "total_cost",
            "hpp_method", "sales_order_id", "faktur_id", "notes",
        }
    for table, provided in supplied.items():
        missing_columns = provided - set(columns[table])
        if missing_columns:
            raise ValidationError(f"public.{table} tidak memiliki kolom yang diperlukan importer: {', '.join(sorted(missing_columns))}.")
        unmet = [column.name for column in columns[table].values() if column.needs_value and column.name not in provided]
        if unmet:
            raise ValidationError(
                f"public.{table} memiliki kolom wajib tanpa default yang belum dipetakan: {', '.join(sorted(unmet))}."
            )
    return columns


def validate_plan_target_lengths(plans: Iterable[HeaderPlan], columns: dict[str, dict[str, TargetColumn]]) -> list[Hold]:
    holds: list[Hold] = []
    order_code_max = columns["sales_order"]["no_order"].max_length
    invoice_code_max = columns["faktur"]["no_faktur"].max_length
    ledger_source_id_max = columns.get("inventory_ledger", {}).get("source_id", TargetColumn("source_id", True, None, False, False, None)).max_length
    ledger_line_id_max = columns.get("inventory_ledger", {}).get("source_detail_id", TargetColumn("source_detail_id", True, None, False, False, None)).max_length
    for plan in plans:
        if order_code_max is not None and len(plan.human_document_code) > order_code_max:
            holds.append(header_hold(plan.row, "human_order_code_exceeds_target_length", {"length": len(plan.human_document_code), "max": order_code_max}))
        elif invoice_code_max is not None and len(plan.human_document_code) > invoice_code_max:
            holds.append(header_hold(plan.row, "human_invoice_code_exceeds_target_length", {"length": len(plan.human_document_code), "max": invoice_code_max}))
        elif ledger_source_id_max is not None and len(plan.ledger_source_id) > ledger_source_id_max:
            holds.append(header_hold(plan.row, "ledger_source_id_exceeds_target_length"))
        else:
            for line in plan.lines:
                if ledger_line_id_max is not None and len(line.source_urut_norm) > ledger_line_id_max:
                    holds.append(detail_hold(line.row, "ledger_source_detail_id_exceeds_target_length"))
    return holds


def filter_plans_with_holds(plans: list[HeaderPlan], holds: list[Hold]) -> list[HeaderPlan]:
    blocked: set[tuple[str, str, str]] = set()
    for hold in holds:
        if hold.source_nota_norm:
            blocked.add(source_key(hold.source_system, hold.source_table, hold.source_nota_norm))
    return [plan for plan in plans if source_key(plan.row.source_system, plan.row.source_table, plan.source_nota_norm) not in blocked]


def check_intra_plan_human_code_collisions(plans: list[HeaderPlan]) -> list[Hold]:
    """Defend against a coding regression before querying target collisions."""

    grouped: dict[str, list[HeaderPlan]] = defaultdict(list)
    for plan in plans:
        grouped[plan.human_document_code.lower()].append(plan)
    holds: list[Hold] = []
    for code, same_code in grouped.items():
        if len(same_code) < 2:
            continue
        identities = [
            f"{plan.row.source_system}/{plan.row.source_table}/{plan.source_nota_norm}"
            for plan in same_code
        ]
        for plan in same_code:
            holds.append(
                header_hold(
                    plan.row,
                    "intra_plan_human_document_code_collision",
                    {"human_document_code": code, "source_identities": identities},
                )
            )
    return holds


def check_human_code_collisions(cur, plans: list[HeaderPlan]) -> list[Hold]:
    codes = sorted({plan.human_document_code.lower() for plan in plans})
    if not codes:
        return []
    cur.execute(
        """
        SELECT lower(btrim(no_order)) FROM public.sales_order
        WHERE lower(btrim(no_order)) = ANY(%s)
        UNION
        SELECT lower(btrim(no_faktur)) FROM public.faktur
        WHERE lower(btrim(no_faktur)) = ANY(%s)
        """,
        (codes, codes),
    )
    collision_codes = {str(row[0]) for row in cur.fetchall() if row[0] is not None}
    return [
        header_hold(plan.row, "prefixed_human_document_code_already_exists", {"human_document_code": plan.human_document_code})
        for plan in plans
        if plan.human_document_code.lower() in collision_codes
    ]


def reconcile_unprovenanced_legacy_header_candidates(
    cur, headers: Iterable[HeaderRow]
) -> list[Hold]:
    """Report raw-Nota target candidates even when a source status is held.

    This is reconciliation only. It intentionally does not decide whether a
    candidate belongs to BDM or TMP and never writes a provenance map.
    """

    header_rows = [row for row in headers if norm(row.nota) is not None]
    raw_notas = sorted({norm(row.nota) for row in header_rows if norm(row.nota) is not None})
    if not raw_notas:
        return []
    orders: dict[str, list[int]] = defaultdict(list)
    invoices: dict[str, list[int]] = defaultdict(list)
    cur.execute(
        """
        SELECT lower(btrim(no_order)), id
        FROM public.sales_order
        WHERE lower(btrim(no_order)) = ANY(%s)
        """,
        (raw_notas,),
    )
    for raw_nota, target_id in cur.fetchall():
        if raw_nota is not None:
            orders[str(raw_nota)].append(int(target_id))
    cur.execute(
        """
        SELECT lower(btrim(no_faktur)), id
        FROM public.faktur
        WHERE lower(btrim(no_faktur)) = ANY(%s)
        """,
        (raw_notas,),
    )
    for raw_nota, target_id in cur.fetchall():
        if raw_nota is not None:
            invoices[str(raw_nota)].append(int(target_id))
    holds: list[Hold] = []
    for row in header_rows:
        raw_nota = norm(row.nota)
        assert raw_nota is not None
        if raw_nota not in orders and raw_nota not in invoices:
            continue
        holds.append(
            header_hold(
                row,
                "unprovenanced_legacy_target_document_candidate",
                {
                    "raw_legacy_nota": row.nota,
                    "target_sales_order_ids": sorted(orders.get(raw_nota, [])),
                    "target_faktur_ids": sorted(invoices.get(raw_nota, [])),
                    "policy": "hold_until_exact_source_qualified_adoption_manifest",
                },
            )
        )
    return holds


def final_stage_gate(metadata: dict[str, StageMetadata]) -> tuple[bool, str]:
    stages = list(metadata.values())
    if len(stages) != 2:
        return False, "Metadata staging BDM/TMP tidak lengkap."
    if any(stage.status != "completed" or stage.is_preview for stage in stages):
        return False, "Kedua staging wajib completed dan bukan preview."
    if all(stage.consistency_mode == SNAPSHOT_CONSISTENCY_MODE for stage in stages):
        return True, "Kedua staging final memakai SQL Server SNAPSHOT."
    if not all(stage.consistency_mode == MAINTENANCE_FREEZE_CONSISTENCY_MODE for stage in stages):
        return False, "Kedua staging harus snapshot atau maintenance_freeze_serializable yang sama."
    windows = {stage.maintenance_window_id for stage in stages if stage.maintenance_window_id}
    if len(windows) != 1 or any(not stage.maintenance_window_id for stage in stages):
        return False, "Staging maintenance BDM/TMP wajib memiliki maintenance_window_id yang sama."
    if any(
        not stage.maintenance_freeze_attested
        or stage.maintenance_freeze_confirmed_at is None
        or (stage.source_transaction_isolation or "").lower() != "serializable"
        or not stage.source_lock_timeout_ms
        for stage in stages
    ):
        return False, "Attestation write-freeze / transaksi SERIALIZABLE staging tidak lengkap."
    return True, f"Kedua staging memakai write-freeze terattestasi ({next(iter(windows))})."


def audit_tables_ready(cur) -> bool:
    cur.execute("SELECT to_regclass(%s)", (f"{REGISTRY_SCHEMA}.active_sales_import_run",))
    return cur.fetchone()[0] is not None


def assert_target_user_triggers_reviewed(cur, *, ledger_enabled: bool) -> None:
    """Fail closed on every user trigger until its DML effect is reviewed.

    Direct SQL imports cannot safely assume that a trigger on a sales or
    ledger table is harmless: it may issue a stock/ledger move, mutate
    receivables, or be disabled to bypass a normal invariant. Internal FK
    triggers are excluded. A future writer must add an explicit, reviewed
    allow-list with a statement of each trigger's effect; this preparatory
    applier intentionally has no such allow-list.
    """

    tables = ["sales_order", "faktur", "sales_order_detail"]
    if ledger_enabled:
        tables.append("inventory_ledger")
    cur.execute(
        """
        SELECT c.relname, t.tgname, t.tgenabled
        FROM pg_trigger t
        JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public'
          AND c.relname = ANY(%s)
          AND NOT t.tgisinternal
        ORDER BY c.relname, t.tgname
        """,
        (tables,),
    )
    user_triggers = [f"{table}.{trigger}={enabled}" for table, trigger, enabled in cur.fetchall()]
    if user_triggers:
        raise ValidationError(
            "Apply ditolak: user trigger target belum memiliki allow-list side-effect yang direview: "
            + ", ".join(user_triggers)
        )


def assert_unused_batch(cur, batch_id: str) -> None:
    cur.execute(f"SELECT 1 FROM {qtable(REGISTRY_SCHEMA, 'active_sales_import_run')} WHERE batch_id=%s", (batch_id,))
    if cur.fetchone() is not None:
        raise ValidationError(f"Batch {batch_id} sudah pernah digunakan; gunakan batch baru setelah review.")


def setup_apply_temp_tables(cur) -> None:
    cur.execute(
        """
        CREATE TEMP TABLE tmp_active_sales_header_input (
            source_system text NOT NULL,
            source_table text NOT NULL,
            source_nota text NOT NULL,
            source_nota_norm text NOT NULL,
            source_stage_schema text NOT NULL,
            source_stage_run_id bigint NOT NULL,
            source_staging_id bigint NOT NULL,
            source_row_hash text NOT NULL,
            human_document_code text NOT NULL,
            ledger_source_id text NOT NULL,
            id_plafon integer NOT NULL,
            id_perusahaan integer NOT NULL,
            id_cabang integer NOT NULL,
            tanggal_order date NOT NULL,
            tanggal_terkirim date,
            tanggal_jatuh_tempo date,
            nama_sales text,
            nama_customer text,
            status_order integer NOT NULL,
            status_faktur integer NOT NULL,
            total_penjualan numeric NOT NULL,
            total_retur numeric NOT NULL,
            source_terbayar numeric,
            subtotal_dpp numeric NOT NULL,
            subtotal_diskon numeric NOT NULL,
            pajak numeric NOT NULL,
            keterangan text,
            id_sales_order integer,
            id_faktur integer,
            PRIMARY KEY (source_system, source_table, source_nota_norm)
        ) ON COMMIT DROP
        """
    )
    cur.execute(
        """
        CREATE TEMP TABLE tmp_active_sales_line_input (
            source_system text NOT NULL,
            source_table text NOT NULL,
            source_nota_norm text NOT NULL,
            source_urut text NOT NULL,
            source_urut_norm text NOT NULL,
            source_stage_schema text NOT NULL,
            source_stage_run_id bigint NOT NULL,
            source_staging_id bigint NOT NULL,
            source_row_hash text NOT NULL,
            id_produk integer NOT NULL,
            qty_base integer NOT NULL,
            pieces_order integer NOT NULL,
            box_order integer NOT NULL,
            karton_order integer NOT NULL,
            hargaorder numeric NOT NULL,
            subtotal_dpp numeric NOT NULL,
            subtotalorder numeric NOT NULL,
            total_nilai_discount numeric NOT NULL,
            total_persen_diskon integer NOT NULL,
            is_bonus integer NOT NULL,
            id_sales_order integer,
            id_faktur integer,
            ledger_source_id text NOT NULL,
            status_order integer NOT NULL,
            id_perusahaan integer NOT NULL,
            id_cabang integer NOT NULL,
            id_principal integer NOT NULL,
            PRIMARY KEY (source_system, source_table, source_nota_norm, source_urut_norm)
        ) ON COMMIT DROP
        """
    )


def upload_apply_plans(cur, execute_values, plans: list[HeaderPlan]) -> None:
    header_rows = []
    line_rows = []
    for plan in plans:
        note_parts = [
            "LEGACY_SQLSERVER_ACTIVE_IMPORT",
            f"SOURCE={plan.row.source_system}",
            f"TABLE={plan.row.source_table}",
            f"NOTA={plan.source_nota}",
            f"STNOTA={normalized_status(plan.row.stnota) or '-'}",
            "SETTLEMENT=unapplied_receivable",
        ]
        if plan.row.keterangan:
            note_parts.append(plan.row.keterangan)
        header_rows.append(
            (
                plan.row.source_system, plan.row.source_table, plan.source_nota, plan.source_nota_norm,
                plan.row.stage_schema, plan.row.stage_run_id, plan.row.staging_id, plan.row.source_row_hash,
                plan.human_document_code, plan.ledger_source_id, plan.id_plafon, plan.id_perusahaan, plan.id_cabang,
                plan.tanggal_order, plan.tanggal_terkirim, plan.tanggal_jatuh_tempo, plan.row.namasales,
                plan.row.namacustomer, plan.status_order, plan.status_faktur, plan.total_penjualan,
                plan.total_retur, plan.source_terbayar, plan.subtotal_dpp, plan.subtotal_diskon, plan.pajak,
                " | ".join(note_parts),
            )
        )
        for line in plan.lines:
            if line.source_discount_percent != line.source_discount_percent.to_integral_value():
                # Target column is integer in the running ERP.  The monetary
                # source discount remains exact; a non-integral percent is not
                # silently rounded into an asserted percentage.
                target_percent = 0
            else:
                target_percent = int(line.source_discount_percent)
            if target_percent < -MAX_INT32 or target_percent > MAX_INT32:
                target_percent = 0
            line_rows.append(
                (
                    plan.row.source_system, plan.row.source_table, plan.source_nota_norm,
                    line.source_urut, line.source_urut_norm,
                    line.row.stage_schema, line.row.stage_run_id, line.row.staging_id, line.row.source_row_hash,
                    line.id_produk, line.qty_base, line.pieces_order, line.box_order, line.karton_order,
                    line.harga_order, line.subtotal_dpp, line.subtotal_order, line.discount_amount,
                    target_percent, line.is_bonus, plan.ledger_source_id, plan.status_order,
                    plan.id_perusahaan, plan.id_cabang, plan.id_principal,
                )
            )
    execute_values(
        cur,
        """
        INSERT INTO tmp_active_sales_header_input (
            source_system, source_table, source_nota, source_nota_norm,
            source_stage_schema, source_stage_run_id, source_staging_id, source_row_hash,
            human_document_code, ledger_source_id, id_plafon, id_perusahaan, id_cabang,
            tanggal_order, tanggal_terkirim, tanggal_jatuh_tempo, nama_sales, nama_customer,
            status_order, status_faktur, total_penjualan, total_retur, source_terbayar,
            subtotal_dpp, subtotal_diskon, pajak, keterangan
        ) VALUES %s
        """,
        header_rows,
        page_size=500,
    )
    if line_rows:
        execute_values(
            cur,
            """
            INSERT INTO tmp_active_sales_line_input (
                source_system, source_table, source_nota_norm, source_urut, source_urut_norm,
                source_stage_schema, source_stage_run_id, source_staging_id, source_row_hash,
                id_produk, qty_base, pieces_order, box_order, karton_order, hargaorder,
                subtotal_dpp, subtotalorder, total_nilai_discount, total_persen_diskon, is_bonus,
                ledger_source_id, status_order, id_perusahaan, id_cabang, id_principal
            ) VALUES %s
            """,
            line_rows,
            page_size=1000,
        )


def insert_public_documents(cur) -> tuple[int, int, int]:
    """Insert headers/invoices/lines and their registry maps within one transaction."""

    cur.execute(
        """
        INSERT INTO public.sales_order (
            id_plafon, tanggal_order, tanggal_faktur, tanggal_terkirim, tanggal_jatuh_tempo,
            nama_sales, pic_customer, status_order, total_order, no_order, no_faktur, keterangan, id_cabang
        )
        SELECT id_plafon, tanggal_order,
               CASE WHEN status_order = 6 THEN tanggal_terkirim ELSE NULL END,
               tanggal_terkirim, tanggal_jatuh_tempo,
               COALESCE(nama_sales, ''), COALESCE(nama_customer, ''), status_order,
               total_penjualan::double precision, human_document_code, human_document_code, keterangan, id_cabang
        FROM tmp_active_sales_header_input
        ORDER BY source_system, source_table, source_nota_norm
        """
    )
    inserted_headers = cur.rowcount
    cur.execute(
        """
        UPDATE tmp_active_sales_header_input input
        SET id_sales_order = so.id
        FROM public.sales_order so
        WHERE so.no_order = input.human_document_code
        """
    )
    cur.execute("SELECT COUNT(*) FROM tmp_active_sales_header_input WHERE id_sales_order IS NULL")
    if int(cur.fetchone()[0]) != 0:
        raise ValidationError("Sales order baru tidak dapat dipetakan kembali melalui kode prefiks.")

    cur.execute(
        """
        INSERT INTO public.faktur (
            id_sales_order, no_faktur, nama_fakturist, status_faktur, jenis_faktur,
            subtotal_penjualan, subtotal_diskon, total_penjualan, total_dana_diterima,
            pajak, dpp, draft_total_penjualan, nominal_retur
        )
        SELECT id_sales_order, human_document_code, 'LEGACY_SQLSERVER', status_faktur, 'penjualan',
               subtotal_dpp::double precision, subtotal_diskon::double precision,
               total_penjualan::double precision, 0::double precision,
               pajak::double precision, subtotal_dpp::double precision,
               total_penjualan::double precision, 0::double precision
        FROM tmp_active_sales_header_input
        ORDER BY source_system, source_table, source_nota_norm
        """
    )
    inserted_faktur = cur.rowcount
    cur.execute(
        """
        UPDATE tmp_active_sales_header_input input
        SET id_faktur = f.id
        FROM public.faktur f
        WHERE f.no_faktur = input.human_document_code
        """
    )
    cur.execute("SELECT COUNT(*) FROM tmp_active_sales_header_input WHERE id_faktur IS NULL")
    if int(cur.fetchone()[0]) != 0:
        raise ValidationError("Faktur baru tidak dapat dipetakan kembali melalui kode prefiks.")

    cur.execute(
        f"""
        INSERT INTO {qtable(REGISTRY_SCHEMA, 'sales_document_map')} (
            source_system, source_table, source_nota, source_nota_norm, stage_schema,
            source_staging_id, source_row_hash, id_sales_order, id_faktur
        )
        SELECT source_system, source_table, source_nota, source_nota_norm, source_stage_schema,
               source_staging_id, source_row_hash, id_sales_order, id_faktur
        FROM tmp_active_sales_header_input
        """
    )

    cur.execute(
        """
        UPDATE tmp_active_sales_line_input line
        SET id_sales_order = header.id_sales_order, id_faktur = header.id_faktur
        FROM tmp_active_sales_header_input header
        WHERE header.source_system=line.source_system
          AND header.source_table=line.source_table
          AND header.source_nota_norm=line.source_nota_norm
        """
    )
    cur.execute("SELECT COUNT(*) FROM tmp_active_sales_line_input WHERE id_sales_order IS NULL OR id_faktur IS NULL")
    if int(cur.fetchone()[0]) != 0:
        raise ValidationError("Detail baru tidak dapat dipasangkan ke sales order/faktur hasil insert.")

    # A server-side loop retains the source line key while using the generated
    # sales_order_detail ID.  It avoids a fragile post-insert match on product
    # and qty: two legitimate source lines may have identical values.
    cur.execute(
        f"""
        DO $$
        DECLARE
            rec record;
            generated_detail_id integer;
            delivered_subtotal integer;
        BEGIN
            FOR rec IN
                SELECT *
                FROM tmp_active_sales_line_input
                ORDER BY source_system, source_table, source_nota_norm, source_urut_norm
            LOOP
                IF rec.status_order = 6 THEN
                    delivered_subtotal := trunc(rec.qty_base::numeric * rec.hargaorder)::integer;
                ELSE
                    delivered_subtotal := 0;
                END IF;
                INSERT INTO public.sales_order_detail (
                    hargaorder, subtotaldelivered, is_bonus, estimasi_kubikasi, id_sales_order, id_produk,
                    pieces_order, box_order, karton_order,
                    pieces_booked, box_booked, karton_booked,
                    pieces_picked, box_picked, karton_picked,
                    pieces_shipped, box_shipped, karton_shipped,
                    pieces_delivered, box_delivered, karton_delivered,
                    subtotalorder, total_nilai_discount, total_persen_diskon
                ) VALUES (
                    rec.hargaorder::double precision, delivered_subtotal, rec.is_bonus, 0,
                    rec.id_sales_order, rec.id_produk,
                    rec.pieces_order, rec.box_order, rec.karton_order,
                    CASE WHEN rec.status_order=6 THEN rec.pieces_order ELSE 0 END,
                    CASE WHEN rec.status_order=6 THEN rec.box_order ELSE 0 END,
                    CASE WHEN rec.status_order=6 THEN rec.karton_order ELSE 0 END,
                    CASE WHEN rec.status_order=6 THEN rec.pieces_order ELSE 0 END,
                    CASE WHEN rec.status_order=6 THEN rec.box_order ELSE 0 END,
                    CASE WHEN rec.status_order=6 THEN rec.karton_order ELSE 0 END,
                    CASE WHEN rec.status_order=6 THEN rec.pieces_order ELSE 0 END,
                    CASE WHEN rec.status_order=6 THEN rec.box_order ELSE 0 END,
                    CASE WHEN rec.status_order=6 THEN rec.karton_order ELSE 0 END,
                    CASE WHEN rec.status_order=6 THEN rec.pieces_order ELSE 0 END,
                    CASE WHEN rec.status_order=6 THEN rec.box_order ELSE 0 END,
                    CASE WHEN rec.status_order=6 THEN rec.karton_order ELSE 0 END,
                    rec.subtotalorder::double precision, rec.total_nilai_discount::double precision,
                    rec.total_persen_diskon
                ) RETURNING id INTO generated_detail_id;
                INSERT INTO {qtable(REGISTRY_SCHEMA, 'sales_document_line_map')} (
                    source_system, source_table, source_nota_norm, source_urut, source_urut_norm,
                    source_staging_id, source_row_hash, id_sales_order_detail
                ) VALUES (
                    rec.source_system, rec.source_table, rec.source_nota_norm, rec.source_urut,
                    rec.source_urut_norm, rec.source_staging_id, rec.source_row_hash, generated_detail_id
                );
            END LOOP;
        END $$
        """
    )
    cur.execute(f"SELECT COUNT(*) FROM {qtable(REGISTRY_SCHEMA, 'sales_document_line_map')} lm JOIN tmp_active_sales_line_input input ON input.source_system=lm.source_system AND input.source_table=lm.source_table AND input.source_nota_norm=lm.source_nota_norm AND input.source_urut_norm=lm.source_urut_norm")
    inserted_lines = int(cur.fetchone()[0])
    return inserted_headers, inserted_faktur, inserted_lines


def insert_zero_cost_ledger(cur) -> int:
    cur.execute(
        """
        SELECT COUNT(*)
        FROM public.inventory_ledger ledger
        JOIN tmp_active_sales_line_input input
          ON ledger.source_type = %s
         AND ledger.source_id = input.ledger_source_id
         AND ledger.source_detail_id = input.source_urut_norm
         AND ledger.direction = 'out'
        WHERE input.status_order=6 AND input.qty_base > 0
        """,
        (LEDGER_SOURCE_TYPE,),
    )
    if int(cur.fetchone()[0]) != 0:
        raise ValidationError("Ledger identity sumber sudah ada; apply dibatalkan agar tidak membuat mutasi stok kedua.")
    cur.execute(
        """
        INSERT INTO public.inventory_ledger (
            movement_date, id_produk, id_cabang, id_perusahaan, id_principal,
            source_module, source_type, source_id, source_detail_id, direction,
            qty, unit_cost, total_cost, hpp_method, sales_order_id, faktur_id, notes
        )
        SELECT header.tanggal_terkirim, line.id_produk, line.id_cabang, line.id_perusahaan, line.id_principal,
               'legacy_sqlserver_active_sales', %s, line.ledger_source_id, line.source_urut_norm, 'out',
               line.qty_base::numeric, 0::numeric, 0::numeric, 'historical_hpp_unknown_zero_cost',
               line.id_sales_order, line.id_faktur,
               'Historical delivery qty from source-aware BDM/TMP import; HPP is unavailable in source and intentionally zero.'
        FROM tmp_active_sales_line_input line
        JOIN tmp_active_sales_header_input header
          ON header.source_system=line.source_system
         AND header.source_table=line.source_table
         AND header.source_nota_norm=line.source_nota_norm
        WHERE line.status_order=6 AND line.qty_base > 0
        """,
        (LEDGER_SOURCE_TYPE,),
    )
    inserted = cur.rowcount
    cur.execute("SELECT COUNT(*) FROM tmp_active_sales_line_input WHERE status_order=6 AND qty_base>0")
    expected = int(cur.fetchone()[0])
    if inserted != expected:
        raise ValidationError(f"Ledger inserted={inserted}, expected={expected}; transaksi dibatalkan.")
    return inserted


def write_audit(
    cur,
    execute_values,
    batch_id: str,
    metadata: dict[str, StageMetadata],
    inserts: list[HeaderPlan],
    unchanged: list[HeaderPlan],
    holds: list[Hold],
    ledger_policy: str,
    inserted_headers: int,
    inserted_lines: int,
    inserted_ledger_lines: int,
) -> None:
    summary = Counter(hold.reason for hold in holds)
    cur.execute(
        f"""
        INSERT INTO {qtable(REGISTRY_SCHEMA, 'active_sales_import_run')} (
            batch_id, bdm_stage_schema, tmp_stage_schema, bdm_stage_run_id, tmp_stage_run_id,
            bdm_consistency_mode, tmp_consistency_mode, bdm_maintenance_window_id, tmp_maintenance_window_id,
            delivered_ledger_policy, settlement_policy, candidate_headers, candidate_lines,
            inserted_headers, inserted_lines, inserted_ledger_lines, unchanged_headers, held_headers,
            hold_summary, applied_by
        ) VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s
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
            ledger_policy,
            "unapplied_receivable",
            len(inserts),
            sum(len(plan.lines) for plan in inserts),
            inserted_headers,
            inserted_lines,
            inserted_ledger_lines,
            len(unchanged),
            len({(hold.source_system, hold.source_table, hold.source_nota_norm) for hold in holds if hold.source_nota_norm}),
            json.dumps(dict(sorted(summary.items())), ensure_ascii=False),
            "active_sales_source_aware_20260830",
        ),
    )
    if holds:
        execute_values(
            cur,
            f"""
            INSERT INTO {qtable(REGISTRY_SCHEMA, 'active_sales_import_hold')} (
                import_batch_id, source_system, source_stage_schema, source_stage_run_id, source_table,
                source_staging_id, source_nota, source_nota_norm, source_urut, source_urut_norm,
                source_row_hash, hold_reason, details
            ) VALUES %s
            """,
            [
                (
                    batch_id, hold.source_system, hold.stage_schema, hold.stage_run_id, hold.source_table,
                    hold.source_staging_id, hold.source_nota, hold.source_nota_norm, hold.source_urut,
                    hold.source_urut_norm, hold.source_row_hash, hold.reason,
                    json.dumps(json_safe(hold.details or {}), ensure_ascii=False, sort_keys=True),
                )
                for hold in holds
            ],
            page_size=1000,
        )
    actions = []
    for plan in inserts:
        actions.append(
            (
                batch_id, plan.row.source_system, plan.row.source_table, plan.source_nota, plan.source_nota_norm,
                "insert_active_document", None, None, plan.human_document_code, len(plan.lines),
                json.dumps({"status_order": plan.status_order, "source_terbayar_unapplied": plan.source_terbayar}, default=str),
            )
        )
    for plan in unchanged:
        actions.append(
            (
                batch_id, plan.row.source_system, plan.row.source_table, plan.source_nota, plan.source_nota_norm,
                "unchanged_existing_document", None, None, plan.human_document_code, len(plan.lines),
                json.dumps({"source_row_hash": plan.row.source_row_hash}),
            )
        )
    if actions:
        execute_values(
            cur,
            f"""
            INSERT INTO {qtable(REGISTRY_SCHEMA, 'active_sales_import_action')} (
                import_batch_id, source_system, source_table, source_nota, source_nota_norm,
                action, id_sales_order, id_faktur, human_document_code, line_count, details
            ) VALUES %s
            """,
            actions,
            page_size=1000,
        )
    # Backfill action target IDs only after source map rows exist; action audit
    # stays separate from ERP identity and does not drive any operational flow.
    cur.execute(
        f"""
        UPDATE {qtable(REGISTRY_SCHEMA, 'active_sales_import_action')} action
        SET id_sales_order=map.id_sales_order, id_faktur=map.id_faktur
        FROM {qtable(REGISTRY_SCHEMA, 'sales_document_map')} map
        WHERE action.import_batch_id=%s
          AND action.action IN ('insert_active_document', 'unchanged_existing_document')
          AND map.source_system=action.source_system
          AND map.source_table=action.source_table
          AND map.source_nota_norm=action.source_nota_norm
        """,
        (batch_id,),
    )


def plan_summary(
    metadata: dict[str, StageMetadata],
    headers_by_source: dict[str, list[HeaderRow]],
    details_by_source: dict[str, list[DetailRow]],
    inserts: list[HeaderPlan],
    unchanged: list[HeaderPlan],
    holds: list[Hold],
    android_counts: dict[str, int],
    ledger_policy: str,
    mode: str,
) -> dict[str, Any]:
    held_header_keys = {
        (hold.source_system, hold.source_table, hold.source_nota_norm)
        for hold in holds
        if hold.source_nota_norm
    }
    return {
        "mode": mode,
        "writes_sql_server": False,
        "canonical_source_family": "HJualSM + DJualSM",
        "android_policy": "held_pending_source_qualified_cross_reference_review",
        "settlement_policy": "unapplied_receivable",
        "delivered_ledger_policy": ledger_policy,
        "stage": {
            source: {
                "schema": metadata[source].schema,
                "run_id": metadata[source].run_id,
                "status": metadata[source].status,
                "consistency_mode": metadata[source].consistency_mode,
                "is_preview": metadata[source].is_preview,
                "maintenance_window_id": metadata[source].maintenance_window_id,
                "standard_headers": len(headers_by_source[source]),
                "standard_details": len(details_by_source[source]),
                "android_headers_held": android_counts.get(f"{source}_headers", 0),
                "android_details_held": android_counts.get(f"{source}_details", 0),
            }
            for source in SOURCE_SYSTEMS
        },
        "plan": {
            "insert_headers": len(inserts),
            "insert_lines": sum(len(plan.lines) for plan in inserts),
            "unchanged_existing_headers": len(unchanged),
            "held_document_headers": len(held_header_keys),
            "hold_rows": len(holds),
            "hold_summary": dict(sorted(Counter(hold.reason for hold in holds).items())),
            "delivered_headers": sum(1 for plan in inserts if plan.status_order == 6),
            "cancelled_headers": 0,
        },
    }


def load_and_plan(cur, args: argparse.Namespace, tolerance: Decimal) -> tuple[
    dict[str, StageMetadata],
    dict[str, list[HeaderRow]],
    dict[str, list[DetailRow]],
    list[HeaderPlan],
    list[HeaderPlan],
    list[Hold],
    dict[str, int],
]:
    columns = fetch_stage_columns(cur, [args.bdm_schema, args.tmp_schema])
    metadata = {
        "bdm_solo_dist": stage_metadata(cur, args.bdm_schema, "bdm_solo_dist", columns),
        "tmp_solo_dist": stage_metadata(cur, args.tmp_schema, "tmp_solo_dist", columns),
    }
    for stage in metadata.values():
        validate_stage_provenance(cur, stage)
    headers_by_source = {source: fetch_headers(cur, stage) for source, stage in metadata.items()}
    details_by_source = {source: fetch_details(cur, stage) for source, stage in metadata.items()}
    reconciliation_holds = reconcile_unprovenanced_legacy_header_candidates(
        cur, (row for rows in headers_by_source.values() for row in rows)
    )
    inserts, unchanged, holds, android_counts = build_plans(
        cur,
        metadata,
        headers_by_source,
        details_by_source,
        tolerance,
        args.delivered_ledger_policy,
    )
    if reconciliation_holds:
        holds.extend(reconciliation_holds)
        inserts = filter_plans_with_holds(inserts, reconciliation_holds)
    target_meta = validate_target_schema(cur, args.delivered_ledger_policy == "ledger_zero_cost")
    length_holds = validate_plan_target_lengths(inserts, target_meta)
    if length_holds:
        holds.extend(length_holds)
        inserts = filter_plans_with_holds(inserts, length_holds)
    intra_plan_holds = check_intra_plan_human_code_collisions(inserts)
    if intra_plan_holds:
        holds.extend(intra_plan_holds)
        inserts = filter_plans_with_holds(inserts, intra_plan_holds)
    collision_holds = check_human_code_collisions(cur, inserts)
    if collision_holds:
        holds.extend(collision_holds)
        inserts = filter_plans_with_holds(inserts, collision_holds)
    return metadata, headers_by_source, details_by_source, inserts, unchanged, holds, android_counts


def apply_plans(
    cur,
    execute_values,
    args: argparse.Namespace,
    metadata: dict[str, StageMetadata],
    inserts: list[HeaderPlan],
    unchanged: list[HeaderPlan],
    holds: list[Hold],
) -> dict[str, int]:
    if args.delivered_ledger_policy != "hold_delivered":
        raise ValidationError("Apply sales ditolak: policy ledger selain hold_delivered belum tersedia.")
    allowed, reason = final_stage_gate(metadata)
    if not allowed:
        raise ValidationError("--apply ditolak: " + reason)
    if not audit_tables_ready(cur):
        raise ValidationError(
            "Audit DDL belum terpasang. Jalankan tools/migration/20260830_create_active_sales_import_audit.sql terlebih dahulu."
        )
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("bdm_tmp_active_sales_import",))
    locks = [
        "public.sales_order",
        "public.sales_order_detail",
        "public.faktur",
        f"{REGISTRY_SCHEMA}.sales_document_map",
        f"{REGISTRY_SCHEMA}.sales_document_line_map",
        f"{REGISTRY_SCHEMA}.active_sales_import_run",
        f"{REGISTRY_SCHEMA}.active_sales_import_hold",
        f"{REGISTRY_SCHEMA}.active_sales_import_action",
    ]
    if args.delivered_ledger_policy == "ledger_zero_cost":
        locks.append("public.inventory_ledger")
    cur.execute("LOCK TABLE " + ", ".join(locks) + " IN SHARE ROW EXCLUSIVE MODE")
    assert_target_user_triggers_reviewed(
        cur, ledger_enabled=args.delivered_ledger_policy == "ledger_zero_cost"
    )
    assert_unused_batch(cur, str(args.batch_id))
    if not inserts:
        write_audit(
            cur, execute_values, str(args.batch_id), metadata, [], unchanged, holds,
            args.delivered_ledger_policy, 0, 0, 0,
        )
        return {"inserted_headers": 0, "inserted_lines": 0, "inserted_ledger_lines": 0}
    setup_apply_temp_tables(cur)
    upload_apply_plans(cur, execute_values, inserts)
    inserted_headers, _inserted_faktur, inserted_lines = insert_public_documents(cur)
    expected_headers = len(inserts)
    expected_lines = sum(len(plan.lines) for plan in inserts)
    if inserted_headers != expected_headers or inserted_lines != expected_lines:
        raise ValidationError(
            f"Jumlah hasil insert tidak sesuai rencana: header={inserted_headers}/{expected_headers}, line={inserted_lines}/{expected_lines}."
        )
    inserted_ledger = 0
    if args.delivered_ledger_policy == "ledger_zero_cost":
        inserted_ledger = insert_zero_cost_ledger(cur)
    write_audit(
        cur, execute_values, str(args.batch_id), metadata, inserts, unchanged, holds,
        args.delivered_ledger_policy, inserted_headers, inserted_lines, inserted_ledger,
    )
    return {
        "inserted_headers": inserted_headers,
        "inserted_lines": inserted_lines,
        "inserted_ledger_lines": inserted_ledger,
    }


def run_self_test() -> int:
    assert parse_nonnegative_integer("48.000", "jumlah") == (48, None)
    assert parse_nonnegative_integer("48.5", "jumlah")[1] == "non_integral_jumlah"
    assert parse_nonnegative_integer("-1", "jumlah")[1] == "negative_jumlah"
    assert parse_date("2026-08-27 12:30:44.120", "tanggal") == (date(2026, 8, 27), None)
    assert parse_date("27/08/2026", "tanggal")[1] == "invalid_tanggal_format"
    assert document_code("bdm_solo_dist", "SNP26080001") != document_code("tmp_solo_dist", "SNP26080001")
    assert document_code("bdm_solo_dist", "A B") != document_code("bdm_solo_dist", "AB")
    assert ledger_source_id("bdm_solo_dist", "HJualSM", "same") != ledger_source_id("tmp_solo_dist", "HJualSM", "same")
    frozen = StageMetadata(
        schema="legacy_bdm_final_test",
        source_system="bdm_solo_dist",
        run_id=1,
        status="completed",
        consistency_mode=MAINTENANCE_FREEZE_CONSISTENCY_MODE,
        is_preview=False,
        maintenance_window_id="test-window",
        maintenance_freeze_attested=True,
        maintenance_freeze_confirmed_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
        source_transaction_isolation="SERIALIZABLE",
        source_lock_timeout_ms=5000,
        target_company_id=1,
        target_branch_id=5,
        manifest_rows={},
        source_columns={},
    )
    frozen_tmp = StageMetadata(
        **{**frozen.__dict__, "schema": "legacy_tmp_final_test", "source_system": "tmp_solo_dist", "target_company_id": 2}
    )
    assert final_stage_gate({"bdm_solo_dist": frozen, "tmp_solo_dist": frozen_tmp})[0]
    preview = StageMetadata(**{**frozen.__dict__, "is_preview": True, "status": "completed_preview", "consistency_mode": "read_committed_preview"})
    assert not final_stage_gate({"bdm_solo_dist": preview, "tmp_solo_dist": frozen_tmp})[0]
    print(json.dumps({"status": "ok", "self_test": "active_sales_source_aware"}, ensure_ascii=False))
    return 0


def emit_output(payload: dict[str, Any], output: Path | None) -> None:
    encoded = json.dumps(json_safe(payload), ensure_ascii=False, sort_keys=True)
    print(encoded)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded + "\n", encoding="utf-8")


def emit_progress(args: argparse.Namespace, phase: str) -> None:
    """Keep a potentially large dry-run observable without polluting stdout."""

    if args.quiet:
        return
    print(
        json.dumps(
            {"status": "running", "mode": "apply" if args.apply else "dry_run", "phase": phase},
            ensure_ascii=False,
        ),
        file=sys.stderr,
        flush=True,
    )


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()
    tolerance = ensure_cli_args(args)
    try:
        import psycopg2  # type: ignore[import-not-found]
        from psycopg2.extras import execute_values  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - runner dependency
        raise ValidationError("psycopg2 diperlukan untuk import sales source-aware.") from exc
    emit_progress(args, "connecting_postgresql")
    try:
        connection = psycopg2.connect(
            dbname=args.pg_database,
            user=args.pg_user,
            host=args.pg_host,
            port=args.pg_port,
            connect_timeout=args.connect_timeout_seconds,
            application_name=(
                "bdm_tmp_active_sales_source_aware_dry_run"
                if not args.apply else "bdm_tmp_active_sales_source_aware_apply"
            ),
        )
    except Exception as exc:
        raise ValidationError(
            f"Koneksi PostgreSQL gagal atau melewati {args.connect_timeout_seconds}s: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    try:
        with connection.cursor() as cur:
            emit_progress(args, "validating_and_planning")
            # A dry-run must be enforced by PostgreSQL itself, not merely by
            # convention in the planner.  Any future accidental DML therefore
            # fails before it can change an active ERP transaction.
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cur.execute("SET LOCAL lock_timeout = '10s'")
            cur.execute("SET LOCAL statement_timeout = %s", (f"{args.statement_timeout_seconds}s",))
            metadata, headers, details, inserts, unchanged, holds, android_counts = load_and_plan(cur, args, tolerance)
            preview = plan_summary(
                metadata, headers, details, inserts, unchanged, holds, android_counts,
                args.delivered_ledger_policy, "dry_run" if not args.apply else "pre_apply_plan",
            )
            if not args.apply:
                emit_output(preview, args.output)
                connection.rollback()
                return 0
            allowed, reason = final_stage_gate(metadata)
            if not allowed:
                raise ValidationError("--apply ditolak: " + reason)
        # Re-plan under a new transaction after locks are acquired.  This
        # eliminates the check-then-insert race without treating a dry plan as
        # an authorization to write changed data.
        connection.rollback()
        with connection.cursor() as cur:
            emit_progress(args, "locking_and_replanning_for_apply")
            cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            cur.execute("SET LOCAL lock_timeout = '10s'")
            cur.execute("SET LOCAL statement_timeout = %s", (f"{args.statement_timeout_seconds}s",))
            # Apply locks before rebuilding the plan.  Registry/document
            # identity is therefore stable for the short, atomic write.
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("bdm_tmp_active_sales_import",))
            locks = [
                "public.sales_order", "public.sales_order_detail", "public.faktur",
                f"{REGISTRY_SCHEMA}.sales_document_map", f"{REGISTRY_SCHEMA}.sales_document_line_map",
                f"{REGISTRY_SCHEMA}.active_sales_import_run", f"{REGISTRY_SCHEMA}.active_sales_import_hold",
                f"{REGISTRY_SCHEMA}.active_sales_import_action",
            ]
            if args.delivered_ledger_policy == "ledger_zero_cost":
                locks.append("public.inventory_ledger")
            cur.execute("LOCK TABLE " + ", ".join(locks) + " IN SHARE ROW EXCLUSIVE MODE")
            metadata, headers, details, inserts, unchanged, holds, android_counts = load_and_plan(cur, args, tolerance)
            # The helper takes its own lock as well; it is re-entrant inside
            # this transaction and keeps direct callers safe too.
            result = apply_plans(cur, execute_values, args, metadata, inserts, unchanged, holds)
        connection.commit()
        final = plan_summary(metadata, headers, details, inserts, unchanged, holds, android_counts, args.delivered_ledger_policy, "applied")
        final["apply_result"] = result
        emit_output(final, args.output)
        return 0
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            json.dumps(
                {"status": "error", "error_type": type(exc).__name__, "error": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2)
