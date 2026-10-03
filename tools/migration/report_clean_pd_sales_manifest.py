#!/usr/bin/env python3
"""Build an immutable, read-only review manifest for active legacy ``PD`` sales.

This program deliberately has no ``--apply`` mode.  It reads only the frozen
BDM Solo and TMP Solo PostgreSQL staging schemas named by
``clean_import_policy.json`` and a blue/green database named
``budimas_clean_*``.  SQL Server is never contacted.

The candidate scope is intentionally narrow:

* canonical ``HJualSM`` + ``DJualSM`` only;
* source status exactly ``PD``;
* a source-qualified, exact master/UOM/conversion/header-detail reconciliation;
* proposed *draft* SO/faktur statuses only.

It never assigns a faktur number, confirms delivery, creates a picking,
touches stock/HPP, allocates payment/AR, or creates a manifest/route.  A
separate, explicitly approved importer is required after UAT.  The JSON report
is deterministic for a fixed repeatable-read snapshot and cannot overwrite a
different report at the same path.
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
from typing import Any, Iterable, Mapping, Sequence

from import_clean_bdm_tmp_master import (  # type: ignore[import-not-found]
    REGISTRY_SCHEMA,
    SHA256_RE,
    GuardError,
    ImporterError,
    SourceConfig,
    assert_clean_target_database_name,
    assert_dsn_has_explicit_database,
    clean,
    load_policy,
    norm,
    qident,
    qtable,
    require_psycopg2,
    sha256_file,
    stable_hash,
    stable_json,
)


REPORT_VERSION = "clean-pd-sales-manifest-20260902.1"
SOURCE_SYSTEMS = ("bdm_solo_dist", "tmp_solo_dist")
SOURCE_HEADER_TABLE = "HJualSM"
SOURCE_DETAIL_TABLE = "DJualSM"
SOURCE_HEADER_STAGE_TABLE = "hjualsm"
SOURCE_DETAIL_STAGE_TABLE = "djualsm"
SOURCE_STATUS = "PD"
MAX_INT32 = 2_147_483_647
INT_TYPES = {"int2", "int4", "int8"}
DECIMAL_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}"
    r"(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?$"
)

STAGE_FIXED_COLUMNS = {
    "staging_id",
    "source_system",
    "target_company_id",
    "target_branch_id",
    "legacy_table",
    "source_row_hash",
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

# These columns are not part of the immutable minimal HJualSM contract: old
# source exports can legitimately omit them.  When present, they provide
# lifecycle *signals* and timestamp audit evidence only; no raw timestamp is
# treated as a delivery/cancellation decision by itself.
OPTIONAL_HEADER_AUDIT_COLUMNS = (
    "sttranfer",
    "useradd",
    "tgladd",
    "useredit",
    "userpk",
    "tglpk",
    "userbatal",
    "tglbatal",
    "ketbatal",
    "userreal",
    "countprint",
    "tunai",
)
HEADER_TIMESTAMP_AUDIT_FIELDS = ("tgladd_raw", "tglpk_raw", "tglbatal_raw", "tglreal_raw")
HEADER_LIFECYCLE_SIGNAL_FIELDS = (
    "sttranfer_raw",
    "userpk_raw",
    "userbatal_raw",
    "ketbatal_raw",
    "userreal_raw",
)


class ManifestError(ImporterError):
    """Raised when an immutable PD review manifest cannot be trusted."""


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    udt_name: str
    nullable: bool
    default: str | None
    max_length: int | None


@dataclass(frozen=True)
class StageInfo:
    source_system: str
    schema: str
    run_id: int
    consistency_mode: str
    maintenance_window_id: str | None
    maintenance_freeze_attested: bool
    maintenance_freeze_confirmed_at: str | None
    source_transaction_isolation: str | None
    window_start: datetime
    window_end_exclusive: datetime
    selection_contract: Mapping[str, Mapping[str, Any]]
    target_company_id: int
    target_branch_id: int
    snapshot_sha256: str
    manifest_sha256: str
    table_counts: Mapping[str, int]


@dataclass(frozen=True)
class DraftPolicy:
    policy_id: str
    status_order: int
    status_order_label: str
    status_faktur: int
    status_faktur_label: str
    frozen_stage_scope: "FrozenStageScope"
    money_reconciliation: Mapping[str, Any]


@dataclass(frozen=True)
class FrozenStageScope:
    """The one attested source-window contract this PD reporter may read."""

    consistency_mode: str
    maintenance_freeze_attested: bool
    maintenance_window_id: str
    source_transaction_isolation: str
    window_start: datetime
    window_end_exclusive: datetime
    header_selection: Mapping[str, str]
    detail_selection: Mapping[str, str]


@dataclass(frozen=True)
class HeaderRow:
    source_system: str
    stage_schema: str
    stage_run_id: int
    staging_id: int
    source_row_hash: str
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
    sttranfer_raw: str | None = None
    useradd_raw: str | None = None
    tgladd_raw: str | None = None
    useredit_raw: str | None = None
    userpk_raw: str | None = None
    tglpk_raw: str | None = None
    userbatal_raw: str | None = None
    tglbatal_raw: str | None = None
    ketbatal_raw: str | None = None
    userreal_raw: str | None = None
    countprint_raw: str | None = None
    tunai_raw: str | None = None


@dataclass(frozen=True)
class DetailRow:
    source_system: str
    stage_schema: str
    stage_run_id: int
    staging_id: int
    source_row_hash: str
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
class UomTarget:
    id_produk: int
    id_produk_uom: int
    level: int
    factor: int
    code_norm: str


@dataclass(frozen=True)
class PlafonTarget:
    id_plafon: int
    id_customer: int
    id_principal: int
    id_sales: int
    id_tipe_harga: int
    kode_tipe_harga: str
    lock_order: str | None
    sisa_bon: Decimal | None
    limit_bon: Decimal | None


@dataclass(frozen=True)
class ProductPriceTarget:
    id_produk: int
    id_tipe_harga: int
    id_produk_harga_jual: int
    harga: Decimal | None


@dataclass(frozen=True)
class ExistingDocument:
    stage_schema: str
    stage_run_id: int
    staging_id: int
    source_row_hash: str
    id_sales_order: int
    id_faktur: int


@dataclass(frozen=True)
class LinePlan:
    row: DetailRow
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
    id_produk_harga_jual: int
    current_master_price: Decimal | None


@dataclass(frozen=True)
class DocumentPlan:
    row: HeaderRow
    source_nota: str
    source_nota_norm: str
    sales_order_code: str
    id_customer: int
    id_principal: int
    id_sales: int
    plafon: PlafonTarget
    tanggal_order: date
    tanggal_jatuh_tempo: date | None
    total_penjualan: Decimal
    subtotal_dpp: Decimal
    subtotal_diskon: Decimal
    pajak: Decimal
    lines: tuple[LinePlan, ...]


@dataclass(frozen=True)
class Hold:
    source_system: str
    source_table: str
    stage_schema: str
    stage_run_id: int
    reason: str
    staging_id: int | None = None
    source_row_hash: str | None = None
    nota: str | None = None
    nota_norm: str | None = None
    urut: str | None = None
    urut_norm: str | None = None
    details: Mapping[str, Any] | None = None

    def identity(self) -> tuple[Any, ...]:
        return (
            self.source_system,
            self.source_table,
            self.stage_schema,
            self.stage_run_id,
            self.staging_id,
            self.source_row_hash,
            self.nota_norm,
            self.urut_norm,
            self.reason,
            stable_json(json_safe(self.details or {})),
        )

    def as_json(self) -> Mapping[str, Any]:
        return {
            "source_system": self.source_system,
            "source_table": self.source_table,
            "stage_schema": self.stage_schema,
            "stage_run_id": self.stage_run_id,
            "staging_id": self.staging_id,
            "source_row_hash": self.source_row_hash,
            "source_nota": self.nota,
            "source_nota_norm": self.nota_norm,
            "source_urut": self.urut,
            "source_urut_norm": self.urut_norm,
            "reason": self.reason,
            "details": json_safe(self.details or {}),
        }


def json_safe(value: Any) -> Any:
    """Use stable, credential-free JSON values for reports and hashing."""

    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return value


def decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def normalized_status(value: Any) -> str | None:
    text = clean(value)
    return text.upper() if text else None


def parse_nonnegative_decimal(value: Any, field: str) -> tuple[Decimal | None, str | None]:
    text = clean(value)
    if text is None:
        return None, f"blank_{field}"
    if not DECIMAL_RE.fullmatch(text):
        return None, f"invalid_{field}_format"
    try:
        result = Decimal(text)
    except InvalidOperation:
        return None, f"invalid_{field}_format"
    if not result.is_finite():
        return None, f"invalid_{field}_format"
    if result < 0:
        return None, f"negative_{field}"
    return result, None


def parse_nonnegative_integer(value: Any, field: str) -> tuple[int | None, str | None]:
    parsed, reason = parse_nonnegative_decimal(value, field)
    if reason:
        return None, reason
    assert parsed is not None
    if parsed != parsed.to_integral_value():
        return None, f"non_integral_{field}"
    result = int(parsed)
    if result > MAX_INT32:
        return None, f"{field}_out_of_int32_range"
    return result, None


def parse_source_date(value: Any, field: str, *, required: bool) -> tuple[date | None, str | None]:
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


def money_equal(left: Decimal, right: Decimal, tolerance: Decimal) -> bool:
    return abs(left - right) <= tolerance


def query_dicts(cur: Any, sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    cur.execute(sql, params or ())
    names = [item.name if hasattr(item, "name") else item[0] for item in cur.description]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def table_exists(cur: Any, schema: str, table: str) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"{schema}.{table}",))
    return bool(cur.fetchone()[0])


def fetch_columns(cur: Any, schema: str, tables: Iterable[str]) -> dict[str, dict[str, ColumnInfo]]:
    names = list(tables)
    if not names:
        return {}
    rows = query_dicts(
        cur,
        """
        SELECT table_name, column_name, udt_name, is_nullable,
               column_default, character_maximum_length
          FROM information_schema.columns
         WHERE table_schema = %s
           AND table_name = ANY(%s)
         ORDER BY table_name, ordinal_position
        """,
        (schema, names),
    )
    result: dict[str, dict[str, ColumnInfo]] = {}
    for row in rows:
        table = str(row["table_name"])
        name = str(row["column_name"])
        result.setdefault(table, {})[name] = ColumnInfo(
            name=name,
            udt_name=str(row["udt_name"]),
            nullable=str(row["is_nullable"]).upper() == "YES",
            default=clean(row["column_default"]),
            max_length=int(row["character_maximum_length"]) if row["character_maximum_length"] is not None else None,
        )
    return result


def parse_manifest_json(value: Any, label: str) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ManifestError(f"{label} bukan JSON valid.") from exc
    return value


def parse_manifest_columns(value: Any, schema: str, table: str) -> set[str]:
    raw = parse_manifest_json(value, f"Manifest {schema}/{table}.source_columns")
    if not isinstance(raw, list) or not all(isinstance(item, str) and item.strip() for item in raw):
        raise ManifestError(f"Manifest {schema}/{table} tidak memiliki source_columns valid.")
    return {str(item).strip().lower() for item in raw}


def parse_policy_timestamp(value: Any, label: str) -> datetime:
    """Parse an exact, timezone-naive stage window bound from the PD policy."""

    text = clean(value)
    if text is None or not DATETIME_RE.fullmatch(text):
        raise ManifestError(f"{label} harus timestamp ISO lengkap tanpa timezone.")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ManifestError(f"{label} bukan timestamp ISO valid.") from exc
    if parsed.tzinfo is not None:
        raise ManifestError(f"{label} harus tanpa timezone karena __stage_run memakai timestamp lokal.")
    return parsed


def coerce_stage_timestamp(value: Any, label: str) -> datetime:
    """Reject a changed stage timestamp type instead of silently converting it."""

    if isinstance(value, datetime):
        if value.tzinfo is not None:
            raise ManifestError(f"{label} tidak boleh bertimezone.")
        return value
    return parse_policy_timestamp(value, label)


def parse_frozen_stage_scope(value: Any) -> FrozenStageScope:
    if not isinstance(value, Mapping):
        raise ManifestError("PD draft policy tidak memiliki frozen_stage_scope.")
    required_text = (
        "consistency_mode",
        "maintenance_window_id",
        "source_transaction_isolation",
    )
    parsed_text: dict[str, str] = {}
    for key in required_text:
        parsed = clean(value.get(key))
        if parsed is None:
            raise ManifestError(f"PD draft policy frozen_stage_scope.{key} wajib diisi.")
        parsed_text[key] = parsed
    if value.get("maintenance_freeze_attested") is not True:
        raise ManifestError("PD draft policy harus mensyaratkan maintenance_freeze_attested=true.")
    start = parse_policy_timestamp(value.get("window_start"), "frozen_stage_scope.window_start")
    end = parse_policy_timestamp(
        value.get("window_end_exclusive"), "frozen_stage_scope.window_end_exclusive"
    )
    if end <= start:
        raise ManifestError("frozen_stage_scope window_end_exclusive harus setelah window_start.")

    def selection(name: str, required: Sequence[str]) -> Mapping[str, str]:
        raw = value.get(name)
        if not isinstance(raw, Mapping) or set(raw) != set(required):
            raise ManifestError(
                f"PD draft policy frozen_stage_scope.{name} harus memuat tepat: {', '.join(required)}."
            )
        result: dict[str, str] = {}
        for key in required:
            item = clean(raw.get(key))
            if item is None:
                raise ManifestError(f"PD draft policy frozen_stage_scope.{name}.{key} kosong.")
            result[key] = item
        return result

    return FrozenStageScope(
        consistency_mode=parsed_text["consistency_mode"],
        maintenance_freeze_attested=True,
        maintenance_window_id=parsed_text["maintenance_window_id"],
        source_transaction_isolation=parsed_text["source_transaction_isolation"],
        window_start=start,
        window_end_exclusive=end,
        header_selection=selection("header_selection", ("mode", "date_column")),
        detail_selection=selection(
            "detail_selection",
            ("mode", "parent_table", "child_key_column", "parent_key_column", "parent_date_column"),
        ),
    )


def parse_money_reconciliation(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestError("PD draft policy tidak memiliki money_reconciliation.")
    tolerance, problem = parse_nonnegative_decimal(
        value.get("header_detail_total_tolerance_rp"), "header_detail_total_tolerance_rp"
    )
    if problem or tolerance != Decimal("0.05"):
        raise ManifestError("PD money_reconciliation harus menetapkan toleransi Rp0.05.")
    formula = clean(value.get("discount_percentage_formula"))
    review_rule = clean(value.get("review_rule"))
    components = value.get("discount_amount_components")
    if formula is None or review_rule is None or components != ["DiscRp", "DiscRp1", "DiscRp2", "DiscRp3"]:
        raise ManifestError("PD money_reconciliation formula/komponen diskon tidak lengkap atau berubah.")
    return {
        "header_detail_total_tolerance_rp": decimal_text(tolerance),
        "discount_percentage_formula": formula,
        "discount_amount_components": list(components),
        "review_rule": review_rule,
    }


def validate_exact_stage_selection(
    selection: Any,
    *,
    schema: str,
    table: str,
    expected: Mapping[str, str],
) -> Mapping[str, Any]:
    """Permit only the policy's canonical date/child stage selector.

    ``redacted_columns`` is emitted by the staging tool when a source table
    contains sensitive columns; it cannot change row selection and is retained
    in the report evidence. Any other key requires a new reviewed policy.
    """

    if not isinstance(selection, Mapping):
        raise ManifestError(f"Manifest {schema}/{table}.selection harus object JSON.")
    allowed = set(expected) | {"redacted_columns"}
    unexpected = sorted(str(key) for key in selection if key not in allowed)
    if unexpected:
        raise ManifestError(
            f"Manifest {schema}/{table}.selection memiliki key di luar kontrak freeze: {', '.join(unexpected)}."
        )
    for key, expected_value in expected.items():
        actual = clean(selection.get(key))
        if actual is None or norm(actual) != norm(expected_value):
            raise ManifestError(
                f"Manifest {schema}/{table}.selection.{key} tidak cocok dengan frozen PD policy."
            )
    if "redacted_columns" in selection and not isinstance(selection["redacted_columns"], list):
        raise ManifestError(f"Manifest {schema}/{table}.selection.redacted_columns harus array.")
    return dict(selection)


def parse_positive_int(value: Any, label: str) -> int:
    text = clean(value)
    if text is None or not re.fullmatch(r"[0-9]+", text):
        raise ManifestError(f"{label} harus integer non-negatif.")
    return int(text)


def stage_scope_context(cur: Any, config: SourceConfig) -> tuple[int, int]:
    rows = query_dicts(
        cur,
        """
        SELECT p.id AS company_id, c.id AS branch_id
          FROM public.perusahaan p
          JOIN public.perusahaan_cabang pc ON pc.id_perusahaan = p.id
          JOIN public.cabang c ON c.id = pc.id_cabang
         WHERE lower(btrim(p.kode)) = lower(btrim(%s))
           AND lower(btrim(c.kode)) = lower(btrim(%s))
        """,
        (config.company_code, config.branch_code),
    )
    if len(rows) != 1:
        raise ManifestError(
            f"Context target {config.source_system} ({config.company_code}/{config.branch_code}) "
            f"harus tepat satu; ditemukan {len(rows)}."
        )
    return int(rows[0]["company_id"]), int(rows[0]["branch_id"])


def resolve_stage(
    cur: Any,
    config: SourceConfig,
    expected_run_id: int | None,
    draft: DraftPolicy,
) -> StageInfo:
    """Validate one frozen sales staging run and derive its exact fingerprint."""

    schema = config.stage_schema
    tables = ("__stage_run", "__stage_manifest", SOURCE_HEADER_STAGE_TABLE, SOURCE_DETAIL_STAGE_TABLE)
    columns = fetch_columns(cur, schema, tables)
    missing_tables = [table for table in tables if table not in columns]
    if missing_tables:
        raise ManifestError(f"{schema} tidak memiliki tabel staging: {', '.join(missing_tables)}.")

    run_columns = set(columns["__stage_run"])
    required_run = {
        "id",
        "source_system",
        "status",
        "consistency_mode",
        "is_preview",
        "target_company_id",
        "target_branch_id",
        "target_company_code",
        "target_branch_code",
        "window_start",
        "window_end_exclusive",
    }
    missing_run = sorted(required_run - run_columns)
    if missing_run:
        raise ManifestError(f"{schema}.__stage_run tidak lengkap: {', '.join(missing_run)}.")

    for table, required in (
        (SOURCE_HEADER_STAGE_TABLE, STAGE_FIXED_COLUMNS | HEADER_REQUIRED_COLUMNS),
        (SOURCE_DETAIL_STAGE_TABLE, STAGE_FIXED_COLUMNS | DETAIL_REQUIRED_COLUMNS),
    ):
        missing = sorted(required - set(columns[table]))
        if missing:
            raise ManifestError(f"{schema}.{table} tidak memiliki kolom staging: {', '.join(missing)}.")

    optional = {
        "maintenance_window_id": "NULL::text",
        "maintenance_freeze_attested": "FALSE",
        "maintenance_freeze_confirmed_at": "NULL::timestamptz",
        "source_transaction_isolation": "NULL::text",
    }
    expressions = {
        name: name if name in run_columns else fallback for name, fallback in optional.items()
    }
    rows = query_dicts(
        cur,
        f"""
        SELECT id, source_system, status, consistency_mode, is_preview,
               target_company_id, target_branch_id, target_company_code, target_branch_code,
               window_start, window_end_exclusive,
               {expressions['maintenance_window_id']} AS maintenance_window_id,
               {expressions['maintenance_freeze_attested']} AS maintenance_freeze_attested,
               {expressions['maintenance_freeze_confirmed_at']} AS maintenance_freeze_confirmed_at,
               {expressions['source_transaction_isolation']} AS source_transaction_isolation
          FROM {qtable(schema, '__stage_run')}
         WHERE status = 'completed'
           AND is_preview = false
         ORDER BY id DESC
        """,
    )
    if expected_run_id is not None:
        rows = [row for row in rows if int(row["id"]) == expected_run_id]
    if len(rows) != 1:
        selected = f" id={expected_run_id}" if expected_run_id is not None else ""
        raise ManifestError(f"{schema} harus memiliki tepat satu __stage_run completed non-preview{selected}; ditemukan {len(rows)}.")
    run = rows[0]
    if clean(run["source_system"]) != config.source_system:
        raise ManifestError(f"{schema} source_system tidak cocok dengan policy {config.source_system}.")
    if norm(run["target_company_code"]) != norm(config.company_code) or norm(run["target_branch_code"]) != norm(config.branch_code):
        raise ManifestError(f"{schema} kode company/cabang tidak cocok dengan clean policy.")
    frozen_scope = draft.frozen_stage_scope
    consistency = clean(run["consistency_mode"])
    if norm(consistency) != norm(frozen_scope.consistency_mode):
        raise ManifestError(
            f"{schema} consistency_mode harus persis {frozen_scope.consistency_mode} untuk PD final freeze."
        )
    if bool(run["maintenance_freeze_attested"]) is not frozen_scope.maintenance_freeze_attested:
        raise ManifestError(f"{schema} maintenance_freeze_attested tidak cocok dengan frozen PD policy.")
    if clean(run["maintenance_window_id"]) != frozen_scope.maintenance_window_id:
        raise ManifestError(f"{schema} maintenance_window_id tidak cocok dengan frozen PD policy.")
    if clean(run["maintenance_freeze_confirmed_at"]) is None:
        raise ManifestError(f"{schema} maintenance_freeze_confirmed_at kosong pada final freeze.")
    if norm(run["source_transaction_isolation"]) != norm(frozen_scope.source_transaction_isolation):
        raise ManifestError(
            f"{schema} source_transaction_isolation harus persis {frozen_scope.source_transaction_isolation}."
        )
    window_start = coerce_stage_timestamp(run["window_start"], f"{schema}.__stage_run.window_start")
    window_end_exclusive = coerce_stage_timestamp(
        run["window_end_exclusive"], f"{schema}.__stage_run.window_end_exclusive"
    )
    if window_start != frozen_scope.window_start or window_end_exclusive != frozen_scope.window_end_exclusive:
        raise ManifestError(
            f"{schema} window stage bukan rentang final {frozen_scope.window_start.isoformat()}.."
            f"{frozen_scope.window_end_exclusive.isoformat()}."
        )

    expected_company, expected_branch = stage_scope_context(cur, config)
    if int(run["target_company_id"]) != expected_company or int(run["target_branch_id"]) != expected_branch:
        raise ManifestError(f"{schema} target company/cabang ID tidak sesuai resolusi policy saat ini.")

    manifest_rows = query_dicts(
        cur,
        f"""
        SELECT legacy_table, module, selection, source_columns,
               source_row_count, staged_row_count, status,
               started_at, finished_at, error
          FROM {qtable(schema, '__stage_manifest')}
         WHERE lower(btrim(legacy_table)) = ANY(%s)
         ORDER BY lower(btrim(legacy_table)), legacy_table
        """,
        ([SOURCE_HEADER_STAGE_TABLE, SOURCE_DETAIL_STAGE_TABLE],),
    )
    manifests: dict[str, dict[str, Any]] = {}
    for row in manifest_rows:
        table = norm(row["legacy_table"])
        if table in manifests:
            raise ManifestError(f"{schema} memiliki manifest ganda untuk {table}.")
        assert table is not None
        manifests[table] = row
    expected_manifest_tables = {SOURCE_HEADER_STAGE_TABLE, SOURCE_DETAIL_STAGE_TABLE}
    if set(manifests) != expected_manifest_tables:
        raise ManifestError(
            f"{schema} manifest sales tidak lengkap; ditemukan {', '.join(sorted(manifests)) or '(kosong)'}.")

    # The final freeze is deliberately a date-range snapshot.  Do not weaken
    # this to a generic non-"all" selector: HJualSM must be the sanctioned
    # date parent and DJualSM the sanctioned child join, exactly as attested in
    # the reviewed draft policy and exact run window above.
    selections = {
        table: parse_manifest_json(
            manifests[table]["selection"], f"Manifest {schema}/{table}.selection"
        )
        for table in (SOURCE_HEADER_STAGE_TABLE, SOURCE_DETAIL_STAGE_TABLE)
    }
    selection_contract = {
        SOURCE_HEADER_STAGE_TABLE: validate_exact_stage_selection(
            selections[SOURCE_HEADER_STAGE_TABLE],
            schema=schema,
            table=SOURCE_HEADER_STAGE_TABLE,
            expected=frozen_scope.header_selection,
        ),
        SOURCE_DETAIL_STAGE_TABLE: validate_exact_stage_selection(
            selections[SOURCE_DETAIL_STAGE_TABLE],
            schema=schema,
            table=SOURCE_DETAIL_STAGE_TABLE,
            expected=frozen_scope.detail_selection,
        ),
    }

    digest = hashlib.sha256()
    digest.update(
        stable_json(
            {
                "schema": schema,
                "run": run,
                "source_system": config.source_system,
                "expected_context": {"company_id": expected_company, "branch_id": expected_branch},
            }
        ).encode("utf-8")
    )
    manifest_evidence: list[Mapping[str, Any]] = []
    counts: dict[str, int] = {}
    required_by_table = {
        SOURCE_HEADER_STAGE_TABLE: HEADER_REQUIRED_COLUMNS,
        SOURCE_DETAIL_STAGE_TABLE: DETAIL_REQUIRED_COLUMNS,
    }
    for table in (SOURCE_HEADER_STAGE_TABLE, SOURCE_DETAIL_STAGE_TABLE):
        manifest = manifests[table]
        selection = selection_contract[table]
        source_columns = parse_manifest_columns(manifest["source_columns"], schema, table)
        if norm(manifest["module"]) != "sales" or norm(manifest["status"]) != "done":
            raise ManifestError(f"Manifest {schema}/{table} tidak completed untuk module sales.")
        missing_source = sorted(required_by_table[table] - source_columns)
        if missing_source:
            raise ManifestError(f"Manifest {schema}/{table} kurang kolom sumber: {', '.join(missing_source)}.")
        source_count = parse_positive_int(manifest["source_row_count"], f"{schema}/{table}.source_row_count")
        staged_count = parse_positive_int(manifest["staged_row_count"], f"{schema}/{table}.staged_row_count")
        cur.execute(f"SELECT count(*)::bigint FROM {qtable(schema, table)}")
        actual_count = int(cur.fetchone()[0])
        if source_count != staged_count or staged_count != actual_count:
            raise ManifestError(f"Manifest {schema}/{table} count source/staged/actual tidak sama.")
        counts[table] = actual_count

        scope_rows = query_dicts(
            cur,
            f"""
            SELECT source_system, lower(btrim(legacy_table)) AS legacy_table,
                   target_company_id, target_branch_id, count(*)::bigint AS row_count
              FROM {qtable(schema, table)}
             GROUP BY source_system, lower(btrim(legacy_table)), target_company_id, target_branch_id
             ORDER BY source_system, lower(btrim(legacy_table)), target_company_id, target_branch_id
            """,
        )
        if actual_count:
            valid_scope = (
                len(scope_rows) == 1
                and clean(scope_rows[0]["source_system"]) == config.source_system
                and norm(scope_rows[0]["legacy_table"]) == table
                and int(scope_rows[0]["target_company_id"]) == expected_company
                and int(scope_rows[0]["target_branch_id"]) == expected_branch
                and int(scope_rows[0]["row_count"]) == actual_count
            )
            if not valid_scope:
                raise ManifestError(f"Scope row {schema}.{table} tidak cocok dengan source/context frozen.")
        elif scope_rows:
            raise ManifestError(f"{schema}.{table} kosong namun memiliki scope aggregate tidak valid.")

        cur.execute(f"SELECT staging_id, source_row_hash FROM {qtable(schema, table)} ORDER BY staging_id")
        for staging_id, row_hash in cur:
            hash_text = clean(row_hash)
            if hash_text is None or not SHA256_RE.fullmatch(hash_text.lower()):
                raise ManifestError(f"{schema}.{table} staging_id={staging_id} memiliki source_row_hash tidak valid.")
            digest.update(f"\n{table}|{int(staging_id)}|{hash_text.lower()}".encode("ascii"))
        manifest_evidence.append(
            {
                "table": table,
                "selection": selection,
                "source_columns": sorted(source_columns),
                "source_row_count": source_count,
                "staged_row_count": staged_count,
                "scope_rows": scope_rows,
                "status": clean(manifest["status"]),
                "module": clean(manifest["module"]),
                "started_at": manifest["started_at"],
                "finished_at": manifest["finished_at"],
                "error": clean(manifest["error"]),
            }
        )
    manifest_sha = stable_hash(json_safe({"source_system": config.source_system, "manifest": manifest_evidence}))
    digest.update(f"\nmanifest|{manifest_sha}".encode("ascii"))
    return StageInfo(
        source_system=config.source_system,
        schema=schema,
        run_id=int(run["id"]),
        consistency_mode=consistency or "",
        maintenance_window_id=clean(run["maintenance_window_id"]),
        maintenance_freeze_attested=bool(run["maintenance_freeze_attested"]),
        maintenance_freeze_confirmed_at=clean(run["maintenance_freeze_confirmed_at"]),
        source_transaction_isolation=clean(run["source_transaction_isolation"]),
        window_start=window_start,
        window_end_exclusive=window_end_exclusive,
        selection_contract=selection_contract,
        target_company_id=expected_company,
        target_branch_id=expected_branch,
        snapshot_sha256=digest.hexdigest(),
        manifest_sha256=manifest_sha,
        table_counts=counts,
    )


def parse_draft_policy(path: Path) -> tuple[DraftPolicy, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError(f"PD draft policy tidak ditemukan: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"PD draft policy bukan JSON valid: {path}") from exc
    if not isinstance(payload, Mapping) or payload.get("approval_status") != "draft":
        raise ManifestError("PD policy harus draft review-only; reporter ini tidak menerima policy apply.")
    source_scope = payload.get("source_scope")
    target = payload.get("target_draft_mapping")
    if not isinstance(source_scope, Mapping) or not isinstance(target, Mapping):
        raise ManifestError("PD draft policy tidak memiliki source_scope/target_draft_mapping.")
    if clean(source_scope.get("canonical_header_table")) != SOURCE_HEADER_TABLE or clean(source_scope.get("canonical_detail_table")) != SOURCE_DETAIL_TABLE:
        raise ManifestError("PD draft policy harus memakai HJualSM + DJualSM kanonik.")
    if clean(source_scope.get("source_status_exact")) != SOURCE_STATUS:
        raise ManifestError("PD draft policy harus membatasi source_status_exact=PD.")
    frozen_stage_scope = parse_frozen_stage_scope(payload.get("frozen_stage_scope"))
    money_reconciliation = parse_money_reconciliation(payload.get("money_reconciliation"))
    so = target.get("sales_order")
    faktur = target.get("faktur")
    if not isinstance(so, Mapping) or not isinstance(faktur, Mapping):
        raise ManifestError("PD draft policy target SO/faktur tidak lengkap.")
    try:
        status_order = int(so["status_order"])
        status_faktur = int(faktur["status_faktur"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ManifestError("Status draft SO/faktur harus integer eksplisit.") from exc
    if so.get("tanggal_faktur") is not None or so.get("tanggal_terkirim") is not None or faktur.get("no_faktur") is not None:
        raise ManifestError("PD draft policy tidak boleh mengisi tanggal kirim/faktur atau nomor faktur.")
    policy_id = clean(payload.get("policy_id"))
    order_label = clean(so.get("label"))
    faktur_label = clean(faktur.get("label"))
    if policy_id is None or order_label is None or faktur_label is None:
        raise ManifestError("PD draft policy memiliki identity/label kosong.")
    return (
        DraftPolicy(
            policy_id,
            status_order,
            order_label,
            status_faktur,
            faktur_label,
            frozen_stage_scope,
            money_reconciliation,
        ),
        sha256_file(path),
    )


def connect_readonly(args: argparse.Namespace) -> tuple[Any, str]:
    psycopg2 = require_psycopg2()
    assert_dsn_has_explicit_database(psycopg2, args.dsn, args.target_database)
    try:
        conn = psycopg2.connect(args.dsn, application_name="budimas-clean-pd-sales-manifest-readonly")
    except Exception as exc:
        raise GuardError("Koneksi database clean gagal; detail DSN tidak dicetak demi keamanan.") from exc
    try:
        conn.autocommit = False
        conn.set_session(isolation_level="REPEATABLE READ", readonly=True, autocommit=False)
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_user, current_setting('transaction_read_only')")
            database, user, is_readonly = cur.fetchone()
        if str(database) != args.target_database:
            raise GuardError("current_database tidak cocok dengan --target-database.")
        assert_clean_target_database_name(str(database), label="current_database")
        if str(is_readonly).lower() not in {"on", "true"}:
            raise GuardError("Sesi reporter harus transaction_read_only.")
        return conn, str(user)
    except Exception:
        conn.close()
        raise


def add_blocker(blockers: list[Mapping[str, Any]], code: str, detail: str, **extra: Any) -> None:
    candidate: Mapping[str, Any] = {"code": code, "detail": detail, **json_safe(extra)}
    marker = stable_json(candidate)
    if not any(stable_json(item) == marker for item in blockers):
        blockers.append(candidate)


def validate_target_contract(cur: Any, draft: DraftPolicy) -> tuple[dict[str, dict[str, ColumnInfo]], list[Mapping[str, Any]], Mapping[str, int]]:
    """Check only the future draft contract; this function never writes it."""

    public_tables = ("sales_order", "sales_order_detail", "faktur", "faktur_detail", "produk_harga_jual")
    registry_tables = (
        "source_context",
        "import_run",
        "principal_source_map",
        "customer_source_map",
        "sales_source_map",
        "product_source_map",
        "product_uom_source_map",
        "product_price_source_map",
        "plafon_source_map",
        "sales_document_map",
        "sales_document_line_map",
    )
    public = fetch_columns(cur, "public", public_tables)
    registry = fetch_columns(cur, REGISTRY_SCHEMA, registry_tables)
    blockers: list[Mapping[str, Any]] = []
    for table in public_tables:
        if table not in public:
            add_blocker(blockers, "target_public_table_missing", "Tabel target draft tidak ditemukan.", table=table)
    for table in registry_tables:
        if table not in registry:
            add_blocker(blockers, "clean_registry_table_missing", "Registry clean target tidak lengkap.", table=table)

    required_columns: Mapping[str, set[str]] = {
        "sales_order": {
            "id", "id_plafon", "tanggal_order", "tanggal_faktur", "tanggal_terkirim",
            "tanggal_jatuh_tempo", "status_order", "total_order", "no_order", "no_faktur", "id_cabang",
        },
        "sales_order_detail": {
            "id", "id_sales_order", "id_produk", "hargaorder", "subtotaldelivered", "is_bonus",
            "pieces_order", "box_order", "karton_order", "pieces_booked", "box_booked", "karton_booked",
            "pieces_picked", "box_picked", "karton_picked", "pieces_shipped", "box_shipped", "karton_shipped",
        },
        "faktur": {
            "id", "id_sales_order", "no_faktur", "status_faktur", "jenis_faktur", "subtotal_penjualan",
            "subtotal_diskon", "total_penjualan", "total_dana_diterima", "pajak", "dpp",
            "draft_total_penjualan", "nominal_retur",
        },
        "faktur_detail": {
            "id", "id_faktur", "id_sales_order", "id_principal", "subtotal_diskon", "subtotal",
            "pajak", "draft_total", "total",
        },
        "produk_harga_jual": {"id", "id_produk", "id_tipe_harga", "harga"},
    }
    for table, required in required_columns.items():
        actual = public.get(table, {})
        missing = sorted(required - set(actual))
        if missing:
            add_blocker(
                blockers,
                "target_required_column_missing",
                "Kolom target draft yang diperlukan tidak ada.",
                table=table,
                missing=missing,
            )
    for table, column in (("sales_order", "status_order"), ("faktur", "status_faktur")):
        item = public.get(table, {}).get(column)
        if item is not None and item.udt_name not in INT_TYPES:
            add_blocker(
                blockers,
                "target_draft_status_column_not_integer",
                "Status draft harus dapat menerima integer policy eksplisit.",
                table=table,
                column=column,
                actual_type=item.udt_name,
            )

    # A numberless faktur is deliberate for PD.  Do not paper over a NOT NULL
    # contract with a fake invoice number; surface the incompatibility instead.
    for table, column in (("faktur", "no_faktur"), ("sales_order", "no_faktur")):
        item = public.get(table, {}).get(column)
        if item is not None and not item.nullable and item.default is None:
            add_blocker(
                blockers,
                "target_numberless_pd_draft_not_supported",
                "Target mewajibkan nomor faktur walau PD policy tidak boleh menerbitkan nomor faktur.",
                table=table,
                column=column,
            )

    target_counts: dict[str, int] = {}
    for table in ("sales_order", "sales_order_detail", "faktur", "faktur_detail"):
        if table in public:
            cur.execute(f"SELECT count(*)::bigint FROM {qtable('public', table)}")
            target_counts[table] = int(cur.fetchone()[0])
            if target_counts[table]:
                add_blocker(
                    blockers,
                    "clean_target_transaction_area_not_empty",
                    "Target clean untuk manifest PD sudah memiliki transaksi; jangan mencampur run baru.",
                    table=table,
                    row_count=target_counts[table],
                )
    for table in ("sales_document_map", "sales_document_line_map"):
        if table in registry:
            cur.execute(f"SELECT count(*)::bigint FROM {qtable(REGISTRY_SCHEMA, table)}")
            target_counts[table] = int(cur.fetchone()[0])
            if target_counts[table]:
                add_blocker(
                    blockers,
                    "clean_target_document_registry_not_empty",
                    "Registry dokumen target clean sudah terisi; kandidat harus diperiksa sebagai run lanjutan tersendiri.",
                    table=table,
                    row_count=target_counts[table],
                )

    constraints: list[Mapping[str, Any]] = []
    if all(table in public for table in ("sales_order", "faktur")):
        constraints = query_dicts(
            cur,
            """
            SELECT c.conrelid::regclass::text AS relation_name, c.conname,
                   c.contype, pg_get_constraintdef(c.oid) AS definition
              FROM pg_constraint c
             WHERE c.conrelid IN ('public.sales_order'::regclass, 'public.faktur'::regclass)
               AND c.contype IN ('c', 'f')
             ORDER BY c.conrelid::regclass::text, c.conname
            """,
        )
    target_counts["target_status_order_draft"] = draft.status_order
    target_counts["target_status_faktur_draft"] = draft.status_faktur
    return {"public": public, "registry": registry, "constraints": {"items": constraints}}, blockers, target_counts


def load_source_contexts(
    cur: Any,
    configs: Mapping[str, SourceConfig],
    stages: Mapping[str, StageInfo],
    blockers: list[Mapping[str, Any]],
) -> Mapping[str, Mapping[str, Any]]:
    rows = query_dicts(
        cur,
        f"""
        SELECT source_system, target_company_id, target_branch_id, document_prefix
          FROM {qtable(REGISTRY_SCHEMA, 'source_context')}
         WHERE source_system = ANY(%s)
         ORDER BY source_system
        """,
        (list(SOURCE_SYSTEMS),),
    )
    result = {clean(row["source_system"]): row for row in rows if clean(row["source_system"]) is not None}
    if set(result) != set(SOURCE_SYSTEMS):
        add_blocker(
            blockers,
            "source_context_incomplete",
            "Kedua source_context BDM/TMP harus ada sebelum planning PD.",
            present=sorted(result),
        )
    for source in SOURCE_SYSTEMS:
        row = result.get(source)
        if row is None:
            continue
        stage = stages[source]
        config = configs[source]
        if int(row["target_company_id"]) != stage.target_company_id or int(row["target_branch_id"]) != stage.target_branch_id:
            add_blocker(
                blockers,
                "source_context_stage_scope_mismatch",
                "source_context tidak sama dengan scope staging frozen.",
                source_system=source,
            )
        if clean(row["document_prefix"]) != config.document_prefix:
            add_blocker(
                blockers,
                "source_context_document_prefix_mismatch",
                "Prefix source_context tidak sama dengan clean policy.",
                source_system=source,
            )
    return result


def source_map_is_current(
    row: Mapping[str, Any],
    stage: StageInfo,
    target_database: str,
    table: str,
    issue_counts: Counter[str],
    issue_samples: dict[str, list[Mapping[str, Any]]],
) -> bool:
    """Only use immutable maps from the same frozen stage and committed master run."""

    reason: str | None = None
    if clean(row.get("source_stage_schema")) != stage.schema or int(row.get("source_stage_run_id") or 0) != stage.run_id:
        reason = "map_stage_not_current_frozen_snapshot"
    elif clean(row.get("import_phase")) != "master" or clean(row.get("import_status")) != "committed":
        reason = "map_not_from_committed_master_run"
    elif clean(row.get("import_target_database")) != target_database:
        reason = "map_target_database_mismatch"
    if reason is None:
        return True
    issue_counts[reason] += 1
    samples = issue_samples.setdefault(reason, [])
    if len(samples) < 20:
        samples.append(
            {
                "map_table": table,
                "source_system": clean(row.get("source_system")),
                "source_stage_schema": clean(row.get("source_stage_schema")),
                "source_stage_run_id": row.get("source_stage_run_id"),
                "import_phase": clean(row.get("import_phase")),
                "import_status": clean(row.get("import_status")),
            }
        )
    return False


def map_put_unique(
    mapping: dict[Any, Any],
    key: Any,
    value: Any,
    *,
    label: str,
    issue_counts: Counter[str],
    issue_samples: dict[str, list[Mapping[str, Any]]],
) -> None:
    if key in mapping:
        issue_counts[f"duplicate_{label}_key"] += 1
        samples = issue_samples.setdefault(f"duplicate_{label}_key", [])
        if len(samples) < 20:
            samples.append({"key": json_safe(key)})
        mapping.pop(key, None)
        return
    mapping[key] = value


def load_master_maps(
    cur: Any,
    *,
    stages: Mapping[str, StageInfo],
    contexts: Mapping[str, Mapping[str, Any]],
    target_database: str,
    blockers: list[Mapping[str, Any]],
) -> Mapping[str, Any]:
    """Load source-qualified master maps and re-check their target relations."""

    issue_counts: Counter[str] = Counter()
    issue_samples: dict[str, list[Mapping[str, Any]]] = {}
    run_join = f"JOIN {qtable(REGISTRY_SCHEMA, 'import_run')} r ON r.id = m.import_run_id"
    stage_filter = "m.source_system = ANY(%s)"
    stages_by_source = stages

    principals: dict[tuple[str, str], int] = {}
    principal_rows = query_dicts(
        cur,
        f"""
        SELECT m.source_system, m.source_stage_schema, m.source_stage_run_id,
               m.source_principal_code_norm, m.id_principal,
               p.id_perusahaan, r.phase AS import_phase, r.status AS import_status,
               r.target_database AS import_target_database
          FROM {qtable(REGISTRY_SCHEMA, 'principal_source_map')} m
          {run_join}
          JOIN public.principal p ON p.id = m.id_principal
         WHERE {stage_filter}
        """,
        (list(SOURCE_SYSTEMS),),
    )
    for row in principal_rows:
        source = str(row["source_system"])
        if not source_map_is_current(row, stages_by_source[source], target_database, "principal_source_map", issue_counts, issue_samples):
            continue
        if int(row["id_perusahaan"]) != stages_by_source[source].target_company_id:
            issue_counts["principal_target_company_mismatch"] += 1
            continue
        code = norm(row["source_principal_code_norm"])
        if code is None:
            issue_counts["principal_map_blank_key"] += 1
            continue
        map_put_unique(principals, (source, code), int(row["id_principal"]), label="principal_map", issue_counts=issue_counts, issue_samples=issue_samples)

    customers: dict[tuple[str, str], tuple[int, int | None]] = {}
    customer_rows = query_dicts(
        cur,
        f"""
        SELECT m.source_system, m.source_stage_schema, m.source_stage_run_id,
               m.source_customer_code_norm, m.id_customer,
               c.id_cabang, c.id_tipe_harga,
               r.phase AS import_phase, r.status AS import_status,
               r.target_database AS import_target_database
          FROM {qtable(REGISTRY_SCHEMA, 'customer_source_map')} m
          {run_join}
          JOIN public.customer c ON c.id = m.id_customer
         WHERE {stage_filter}
        """,
        (list(SOURCE_SYSTEMS),),
    )
    for row in customer_rows:
        source = str(row["source_system"])
        if not source_map_is_current(row, stages_by_source[source], target_database, "customer_source_map", issue_counts, issue_samples):
            continue
        if int(row["id_cabang"]) != stages_by_source[source].target_branch_id:
            issue_counts["customer_target_branch_mismatch"] += 1
            continue
        code = norm(row["source_customer_code_norm"])
        if code is None:
            issue_counts["customer_map_blank_key"] += 1
            continue
        price_type = int(row["id_tipe_harga"]) if row["id_tipe_harga"] is not None else None
        map_put_unique(customers, (source, code), (int(row["id_customer"]), price_type), label="customer_map", issue_counts=issue_counts, issue_samples=issue_samples)

    sales: dict[tuple[str, str, str], int] = {}
    sales_rows = query_dicts(
        cur,
        f"""
        SELECT m.source_system, m.source_stage_schema, m.source_stage_run_id,
               m.source_principal_code_norm, m.source_sales_code_norm, m.id_sales,
               s.id_principal,
               (SELECT count(*) FROM public.sales_detail sd WHERE sd.id_sales = s.id) AS sales_detail_count,
               (SELECT count(*) FROM public.sales_principal_assignment spa
                 WHERE spa.id_sales = s.id AND spa.id_principal = s.id_principal) AS assignment_count,
               r.phase AS import_phase, r.status AS import_status,
               r.target_database AS import_target_database
          FROM {qtable(REGISTRY_SCHEMA, 'sales_source_map')} m
          {run_join}
          JOIN public.sales s ON s.id = m.id_sales
         WHERE {stage_filter}
        """,
        (list(SOURCE_SYSTEMS),),
    )
    for row in sales_rows:
        source = str(row["source_system"])
        if not source_map_is_current(row, stages_by_source[source], target_database, "sales_source_map", issue_counts, issue_samples):
            continue
        principal = norm(row["source_principal_code_norm"])
        code = norm(row["source_sales_code_norm"])
        expected_principal = principals.get((source, principal or ""))
        if principal is None or code is None or expected_principal is None or int(row["id_principal"]) != expected_principal:
            issue_counts["sales_target_principal_mismatch"] += 1
            continue
        if int(row["sales_detail_count"]) != 1 or int(row["assignment_count"]) != 1:
            issue_counts["sales_target_detail_or_assignment_not_exact"] += 1
            continue
        map_put_unique(sales, (source, principal, code), int(row["id_sales"]), label="sales_map", issue_counts=issue_counts, issue_samples=issue_samples)

    products: dict[tuple[str, str, str], int] = {}
    product_rows = query_dicts(
        cur,
        f"""
        SELECT m.source_system, m.source_stage_schema, m.source_stage_run_id,
               m.source_principal_code_norm, m.source_sku_norm, m.id_produk,
               p.id_principal,
               r.phase AS import_phase, r.status AS import_status,
               r.target_database AS import_target_database
          FROM {qtable(REGISTRY_SCHEMA, 'product_source_map')} m
          {run_join}
          JOIN public.produk p ON p.id = m.id_produk
         WHERE {stage_filter}
        """,
        (list(SOURCE_SYSTEMS),),
    )
    for row in product_rows:
        source = str(row["source_system"])
        if not source_map_is_current(row, stages_by_source[source], target_database, "product_source_map", issue_counts, issue_samples):
            continue
        principal = norm(row["source_principal_code_norm"])
        sku = norm(row["source_sku_norm"])
        expected_principal = principals.get((source, principal or ""))
        if principal is None or sku is None or expected_principal is None or int(row["id_principal"]) != expected_principal:
            issue_counts["product_target_principal_mismatch"] += 1
            continue
        map_put_unique(products, (source, principal, sku), int(row["id_produk"]), label="product_map", issue_counts=issue_counts, issue_samples=issue_samples)

    uoms: dict[tuple[str, str, str, str, int, int], list[UomTarget]] = defaultdict(list)
    uom_rows = query_dicts(
        cur,
        f"""
        SELECT m.source_system, m.source_stage_schema, m.source_stage_run_id,
               m.source_principal_code_norm, m.source_sku_norm, m.source_uom_code_norm,
               m.source_uom_level, m.source_factor, m.id_produk, m.id_produk_uom,
               pu.id_produk AS target_id_produk, pu.level AS target_level,
               pu.faktor_konversi AS target_factor, lower(btrim(pu.kode)) AS target_code,
               r.phase AS import_phase, r.status AS import_status,
               r.target_database AS import_target_database
          FROM {qtable(REGISTRY_SCHEMA, 'product_uom_source_map')} m
          {run_join}
          JOIN public.produk_uom pu ON pu.id = m.id_produk_uom
         WHERE {stage_filter}
        """,
        (list(SOURCE_SYSTEMS),),
    )
    for row in uom_rows:
        source = str(row["source_system"])
        if not source_map_is_current(row, stages_by_source[source], target_database, "product_uom_source_map", issue_counts, issue_samples):
            continue
        principal = norm(row["source_principal_code_norm"])
        sku = norm(row["source_sku_norm"])
        code = norm(row["source_uom_code_norm"])
        level = int(row["source_uom_level"])
        factor = int(row["source_factor"])
        product_id = products.get((source, principal or "", sku or ""))
        if (
            principal is None or sku is None or code is None or product_id is None
            or int(row["id_produk"]) != product_id or int(row["target_id_produk"]) != product_id
            or int(row["target_level"]) != level or int(row["target_factor"]) != factor
            or norm(row["target_code"]) != code
        ):
            issue_counts["uom_target_contract_mismatch"] += 1
            continue
        uoms[(source, principal, sku, code, level, factor)].append(
            UomTarget(product_id, int(row["id_produk_uom"]), level, factor, code)
        )

    prices: dict[tuple[str, str, str, int], list[ProductPriceTarget]] = defaultdict(list)
    price_rows = query_dicts(
        cur,
        f"""
        SELECT m.source_system, m.source_stage_schema, m.source_stage_run_id,
               m.source_principal_code_norm, m.source_sku_norm, m.id_produk,
               m.id_produk_harga_jual, ph.id_produk AS target_id_produk,
               ph.id_tipe_harga, ph.harga,
               r.phase AS import_phase, r.status AS import_status,
               r.target_database AS import_target_database
          FROM {qtable(REGISTRY_SCHEMA, 'product_price_source_map')} m
          {run_join}
          JOIN public.produk_harga_jual ph ON ph.id = m.id_produk_harga_jual
         WHERE {stage_filter}
        """,
        (list(SOURCE_SYSTEMS),),
    )
    for row in price_rows:
        source = str(row["source_system"])
        if not source_map_is_current(row, stages_by_source[source], target_database, "product_price_source_map", issue_counts, issue_samples):
            continue
        principal = norm(row["source_principal_code_norm"])
        sku = norm(row["source_sku_norm"])
        product_id = products.get((source, principal or "", sku or ""))
        if principal is None or sku is None or product_id is None or int(row["id_produk"]) != product_id or int(row["target_id_produk"]) != product_id:
            issue_counts["product_price_target_contract_mismatch"] += 1
            continue
        price, problem = parse_nonnegative_decimal(row["harga"], "target_master_price")
        if problem:
            issue_counts["product_price_target_value_invalid"] += 1
            continue
        prices[(source, principal, sku, int(row["id_tipe_harga"]))].append(
            ProductPriceTarget(product_id, int(row["id_tipe_harga"]), int(row["id_produk_harga_jual"]), price)
        )

    plafons: dict[tuple[str, str, str, str], list[PlafonTarget]] = defaultdict(list)
    plafon_rows = query_dicts(
        cur,
        f"""
        SELECT m.source_system, m.source_stage_schema, m.source_stage_run_id,
               m.source_customer_code_norm, m.source_principal_code_norm, m.source_sales_code_norm,
               m.id_plafon,
               p.id_customer, p.id_principal, p.id_sales, p.id_tipe_harga,
               p.lock_order, p.sisa_bon, p.limit_bon,
               th.kode AS kode_tipe_harga,
               r.phase AS import_phase, r.status AS import_status,
               r.target_database AS import_target_database
          FROM {qtable(REGISTRY_SCHEMA, 'plafon_source_map')} m
          {run_join}
          JOIN public.plafon p ON p.id = m.id_plafon
          LEFT JOIN public.produk_tipe_harga th ON th.id = p.id_tipe_harga
         WHERE {stage_filter}
        """,
        (list(SOURCE_SYSTEMS),),
    )
    for row in plafon_rows:
        source = str(row["source_system"])
        if not source_map_is_current(row, stages_by_source[source], target_database, "plafon_source_map", issue_counts, issue_samples):
            continue
        customer = norm(row["source_customer_code_norm"])
        principal = norm(row["source_principal_code_norm"])
        sales_code = norm(row["source_sales_code_norm"])
        customer_target = customers.get((source, customer or ""))
        principal_target = principals.get((source, principal or ""))
        sales_target = sales.get((source, principal or "", sales_code or ""))
        if (
            customer is None or principal is None or sales_code is None or customer_target is None
            or principal_target is None or sales_target is None
            or int(row["id_customer"]) != customer_target[0]
            or int(row["id_principal"]) != principal_target
            or int(row["id_sales"]) != sales_target
            or row["id_tipe_harga"] is None or clean(row["kode_tipe_harga"]) is None
        ):
            issue_counts["plafon_target_contract_mismatch"] += 1
            continue
        if customer_target[1] is None or int(row["id_tipe_harga"]) != customer_target[1]:
            issue_counts["plafon_customer_price_type_mismatch"] += 1
            continue
        sisa, sisa_problem = parse_nonnegative_decimal(row["sisa_bon"], "plafon_sisa_bon")
        limit, limit_problem = parse_nonnegative_decimal(row["limit_bon"], "plafon_limit_bon")
        if sisa_problem or limit_problem:
            issue_counts["plafon_target_amount_invalid"] += 1
            continue
        plafons[(source, customer, principal, sales_code)].append(
            PlafonTarget(
                id_plafon=int(row["id_plafon"]),
                id_customer=customer_target[0],
                id_principal=principal_target,
                id_sales=sales_target,
                id_tipe_harga=int(row["id_tipe_harga"]),
                kode_tipe_harga=str(row["kode_tipe_harga"]),
                lock_order=clean(row["lock_order"]),
                sisa_bon=sisa,
                limit_bon=limit,
            )
        )

    if issue_counts:
        add_blocker(
            blockers,
            "master_map_integrity_invalid",
            "Sebagian map master tidak cocok dengan frozen stage atau target saat ini; key tersebut tidak dipakai.",
            by_reason=dict(sorted(issue_counts.items())),
            samples={key: value for key, value in sorted(issue_samples.items())},
        )
    # An active PD plan can be reviewed while plafon remains locked; this is
    # expected from the master phase and is reported, never silently unlocked.
    locked = sum(1 for values in plafons.values() for item in values if item.lock_order == "1")
    return {
        "principals": principals,
        "customers": customers,
        "sales": sales,
        "products": products,
        "uoms": uoms,
        "prices": prices,
        "plafons": plafons,
        "summary": {
            "principal_keys": len(principals),
            "customer_keys": len(customers),
            "sales_keys": len(sales),
            "product_keys": len(products),
            "uom_keys": len(uoms),
            "price_keys": len(prices),
            "plafon_keys": len(plafons),
            "locked_non_live_plafon_rows": locked,
        },
    }


def available_header_audit_columns(cur: Any, stage: StageInfo) -> tuple[str, ...]:
    columns = fetch_columns(cur, stage.schema, (SOURCE_HEADER_STAGE_TABLE,))
    available = set(columns.get(SOURCE_HEADER_STAGE_TABLE, {}))
    return tuple(column for column in OPTIONAL_HEADER_AUDIT_COLUMNS if column in available)


def fetch_headers(
    cur: Any,
    stage: StageInfo,
    *,
    audit_columns: Sequence[str] | None = None,
) -> list[HeaderRow]:
    available = set(audit_columns if audit_columns is not None else available_header_audit_columns(cur, stage))
    optional_projection = ",\n               ".join(
        f"{qident(column)} AS {qident(column)}" if column in available else f"NULL::text AS {qident(column)}"
        for column in OPTIONAL_HEADER_AUDIT_COLUMNS
    )
    cur.execute(
        f"""
        SELECT staging_id, source_row_hash, nota, tanggal, kodesales, namasales,
               kodecustomer, namacustomer, kodeprinciple, keterangan, jatuhtempo,
               totalpenjualan, totalretur, terbayar, stnota, tglreal,
               {optional_projection}
          FROM {qtable(stage.schema, SOURCE_HEADER_STAGE_TABLE)}
         WHERE source_system = %s
         ORDER BY staging_id
        """,
        (stage.source_system,),
    )
    rows: list[HeaderRow] = []
    for record in cur.fetchall():
        rows.append(
            HeaderRow(
                source_system=stage.source_system,
                stage_schema=stage.schema,
                stage_run_id=stage.run_id,
                staging_id=int(record[0]),
                source_row_hash=str(record[1]).lower(),
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
                sttranfer_raw=clean(record[16]),
                useradd_raw=clean(record[17]),
                tgladd_raw=clean(record[18]),
                useredit_raw=clean(record[19]),
                userpk_raw=clean(record[20]),
                tglpk_raw=clean(record[21]),
                userbatal_raw=clean(record[22]),
                tglbatal_raw=clean(record[23]),
                ketbatal_raw=clean(record[24]),
                userreal_raw=clean(record[25]),
                countprint_raw=clean(record[26]),
                tunai_raw=clean(record[27]),
            )
        )
    return rows


def fetch_details(cur: Any, stage: StageInfo) -> list[DetailRow]:
    cur.execute(
        f"""
        SELECT staging_id, source_row_hash, nota, urut, tanggal, kodestok, masterkode,
               ct, pc, unit, satuan, perunit, jumlah, harga, jumlahexppn, jumlahharga,
               kodesales, kodecustomer, kodeprinciple,
               disc1, disc2, disc3, discrp, discrp1, discrp2, discrp3
          FROM {qtable(stage.schema, SOURCE_DETAIL_STAGE_TABLE)}
         WHERE source_system = %s
         ORDER BY staging_id
        """,
        (stage.source_system,),
    )
    rows: list[DetailRow] = []
    for record in cur.fetchall():
        rows.append(
            DetailRow(
                source_system=stage.source_system,
                stage_schema=stage.schema,
                stage_run_id=stage.run_id,
                staging_id=int(record[0]),
                source_row_hash=str(record[1]).lower(),
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
        )
    return rows


def header_hold(row: HeaderRow, reason: str, **details: Any) -> Hold:
    return Hold(
        source_system=row.source_system,
        source_table=SOURCE_HEADER_TABLE,
        stage_schema=row.stage_schema,
        stage_run_id=row.stage_run_id,
        staging_id=row.staging_id,
        source_row_hash=row.source_row_hash,
        nota=row.nota,
        nota_norm=norm(row.nota),
        reason=reason,
        details=details,
    )


def detail_hold(row: DetailRow, reason: str, **details: Any) -> Hold:
    return Hold(
        source_system=row.source_system,
        source_table=SOURCE_DETAIL_TABLE,
        stage_schema=row.stage_schema,
        stage_run_id=row.stage_run_id,
        staging_id=row.staging_id,
        source_row_hash=row.source_row_hash,
        nota=row.nota,
        nota_norm=norm(row.nota),
        urut=row.urut,
        urut_norm=norm(row.urut),
        reason=reason,
        details=details,
    )


def pd_lifecycle_holds(row: HeaderRow) -> list[Hold]:
    """Return only explicit lifecycle/payment/return signals for a PD header.

    Legacy ``TglReal`` and ``TglBatal`` are routinely populated with default
    operational timestamps.  They are reported as audit evidence below, but
    a timestamp alone is not proof of delivery or cancellation.  A populated
    responsible-user/transfer/cancellation field, by contrast, remains an
    explicit source signal that must stay out of this draft-only PD scope.
    """

    result: list[Hold] = []
    total_retur, retur_problem = parse_nonnegative_decimal(row.totalretur_raw or "0", "totalretur")
    terbayar, terbayar_problem = parse_nonnegative_decimal(row.terbayar_raw or "0", "terbayar")
    if retur_problem:
        result.append(header_hold(row, retur_problem))
    elif total_retur is not None and total_retur != 0:
        result.append(
            header_hold(
                row,
                "nonzero_return_requires_separate_return_policy",
                source_total_retur=total_retur,
            )
        )
    if terbayar_problem:
        result.append(header_hold(row, terbayar_problem))
    elif terbayar is not None and terbayar != 0:
        result.append(
            header_hold(
                row,
                "nonzero_payment_requires_separate_payment_policy",
                source_terbayar=terbayar,
            )
        )

    for attribute, reason, source_field in (
        ("userpk_raw", "source_userpk_requires_lifecycle_review", "UserPK"),
        ("userreal_raw", "source_userreal_requires_delivery_lifecycle_review", "UserReal"),
        ("sttranfer_raw", "source_sttranfer_requires_transfer_lifecycle_review", "StTranfer"),
        ("userbatal_raw", "source_userbatal_requires_cancellation_policy", "UserBatal"),
        ("ketbatal_raw", "source_ketbatal_requires_cancellation_policy", "KetBatal"),
    ):
        value = clean(getattr(row, attribute))
        if value is not None:
            result.append(header_hold(row, reason, source_field=source_field, source_value=value))
    return result


def pd_header_lifecycle_audit(
    headers: Sequence[HeaderRow], audit_columns: Sequence[str],
) -> Mapping[str, Any]:
    """Summarize raw lifecycle evidence without interpreting default dates."""

    available = {"tglreal", *audit_columns}

    def presence(attribute: str) -> Mapping[str, Any]:
        source_column = attribute.removesuffix("_raw")
        populated = sum(clean(getattr(item, attribute)) is not None for item in headers)
        return {
            "source_column": source_column,
            "column_present_in_stage": source_column in available,
            "nonblank_pd_headers": populated,
            "blank_or_unavailable_pd_headers": len(headers) - populated,
        }

    return {
        "audit_interpretation": (
            "TglAdd/TglPK/TglReal/TglBatal are timestamp evidence only; no timestamp alone creates a delivery or cancellation hold."
        ),
        "available_optional_header_columns": sorted(audit_columns),
        "timestamp_presence": {
            attribute.removesuffix("_raw"): presence(attribute)
            for attribute in HEADER_TIMESTAMP_AUDIT_FIELDS
        },
        "lifecycle_signal_presence": {
            attribute.removesuffix("_raw"): presence(attribute)
            for attribute in HEADER_LIFECYCLE_SIGNAL_FIELDS
        },
        "nonzero_payment_pd_headers": sum(
            (parsed is not None and problem is None and parsed != 0)
            for parsed, problem in (
                parse_nonnegative_decimal(item.terbayar_raw or "0", "terbayar") for item in headers
            )
        ),
        "nonzero_return_pd_headers": sum(
            (parsed is not None and problem is None and parsed != 0)
            for parsed, problem in (
                parse_nonnegative_decimal(item.totalretur_raw or "0", "totalretur") for item in headers
            )
        ),
    }


def resolve_line(
    row: DetailRow,
    header: HeaderRow,
    *,
    principal_norm: str,
    order_date: date,
    master: Mapping[str, Any],
) -> tuple[LinePlan | None, Hold | None]:
    """Resolve one line without nearest-code or conversion fallbacks."""

    nota_norm = norm(row.nota)
    urut_norm = norm(row.urut)
    sku_norm = norm(row.kodestok)
    if nota_norm is None or urut_norm is None or sku_norm is None:
        return None, detail_hold(row, "missing_detail_identity")
    if norm(row.kodeprinciple) != principal_norm:
        return None, detail_hold(
            row,
            "detail_principal_not_equal_header",
            header_principal=header.kodeprinciple,
            detail_principal=row.kodeprinciple,
        )
    if norm(row.kodesales) != norm(header.kodesales):
        return None, detail_hold(
            row,
            "detail_sales_not_equal_header",
            header_sales=header.kodesales,
            detail_sales=row.kodesales,
        )
    if norm(row.kodecustomer) != norm(header.kodecustomer):
        return None, detail_hold(
            row,
            "detail_customer_not_equal_header",
            header_customer=header.kodecustomer,
            detail_customer=row.kodecustomer,
        )
    detail_date, date_problem = parse_source_date(row.tanggal_raw, "detail_tanggal", required=True)
    if date_problem or detail_date is None:
        return None, detail_hold(row, date_problem or "invalid_detail_tanggal")
    if detail_date != order_date:
        return None, detail_hold(
            row,
            "detail_date_not_equal_header",
            header_date=order_date,
            detail_date=detail_date,
        )
    product_id = master["products"].get((row.source_system, principal_norm, sku_norm))
    if product_id is None:
        # masterkode remains audit evidence only; using it as a fallback would
        # make a source-qualified plan silently guess the product.
        return None, detail_hold(row, "missing_committed_exact_product_map", source_sku=row.kodestok, source_masterkode=row.masterkode)
    base_code = norm(row.pc)
    outer_code = norm(row.ct)
    if base_code is None or outer_code is None:
        return None, detail_hold(row, "blank_source_uom_code", pc=row.pc, ct=row.ct)
    unit, unit_problem = parse_nonnegative_integer(row.unit_raw, "unit")
    pieces, pieces_problem = parse_nonnegative_integer(row.satuan_raw, "satuan")
    factor, factor_problem = parse_nonnegative_integer(row.perunit_raw, "perunit")
    qty_base, quantity_problem = parse_nonnegative_integer(row.jumlah_raw, "jumlah")
    for problem in (unit_problem, pieces_problem, factor_problem, quantity_problem):
        if problem:
            return None, detail_hold(row, problem)
    assert unit is not None and pieces is not None and factor is not None and qty_base is not None
    if factor <= 0:
        return None, detail_hold(row, "nonpositive_perunit")
    calculated = unit * factor + pieces
    if calculated != qty_base:
        return None, detail_hold(
            row,
            "quantity_formula_mismatch",
            unit=unit,
            perunit=factor,
            satuan=pieces,
            jumlah=qty_base,
            calculated=calculated,
        )
    base_matches = master["uoms"].get((row.source_system, principal_norm, sku_norm, base_code, 1, 1), [])
    if len(base_matches) != 1 or base_matches[0].id_produk != product_id or base_matches[0].level != 1:
        return None, detail_hold(
            row,
            "missing_or_ambiguous_exact_base_uom_map",
            source_uom=row.pc,
            candidate_count=len(base_matches),
        )
    if outer_code == base_code and factor == 1:
        expected_outer_level = 1
    elif outer_code != base_code and factor > 1:
        expected_outer_level = 2
    else:
        return None, detail_hold(
            row,
            "unsupported_or_unproven_outer_uom_conversion",
            pc=row.pc,
            ct=row.ct,
            perunit=factor,
        )
    outer_matches = master["uoms"].get(
        (row.source_system, principal_norm, sku_norm, outer_code, expected_outer_level, factor), []
    )
    if len(outer_matches) != 1 or outer_matches[0].id_produk != product_id:
        return None, detail_hold(
            row,
            "missing_or_ambiguous_exact_outer_uom_map",
            source_uom=row.ct,
            source_uom_level=expected_outer_level,
            source_factor=factor,
            candidate_count=len(outer_matches),
        )
    outer = outer_matches[0]
    if outer.level == 1:
        if outer.id_produk_uom != base_matches[0].id_produk_uom or factor != 1:
            return None, detail_hold(row, "invalid_outer_base_uom_mapping")
        pieces_order, box_order, karton_order = qty_base, 0, 0
    elif outer.level == 2:
        pieces_order, box_order, karton_order = pieces, unit, 0
    else:
        return None, detail_hold(row, "unsupported_target_uom_level", level=outer.level)

    harga, harga_problem = parse_nonnegative_decimal(row.harga_raw, "harga")
    dpp, dpp_problem = parse_nonnegative_decimal(row.jumlahexppn_raw, "jumlahexppn")
    total, total_problem = parse_nonnegative_decimal(row.jumlahharga_raw, "jumlahharga")
    for problem in (harga_problem, dpp_problem, total_problem):
        if problem:
            return None, detail_hold(row, problem)
    assert harga is not None and dpp is not None and total is not None
    if dpp > total + Decimal("0.05"):
        return None, detail_hold(row, "line_total_less_than_dpp", dpp=dpp, total=total)
    discount_amount = Decimal("0")
    discount_percent = Decimal("0")
    for field, raw in (
        ("discrp", row.discrp_raw),
        ("discrp1", row.discrp1_raw),
        ("discrp2", row.discrp2_raw),
        ("discrp3", row.discrp3_raw),
    ):
        value, problem = parse_nonnegative_decimal(raw or "0", field)
        if problem or value is None:
            return None, detail_hold(row, problem or f"invalid_{field}")
        discount_amount += value
    for field, raw in (("disc1", row.disc1_raw), ("disc2", row.disc2_raw), ("disc3", row.disc3_raw)):
        value, problem = parse_nonnegative_decimal(raw or "0", field)
        if problem or value is None:
            return None, detail_hold(row, problem or f"invalid_{field}")
        discount_percent += value

    # The source historical price is copied as sales-detail evidence in a
    # future import.  It is not required to equal today's list price because
    # a valid historical promotion/override may differ.  We still require one
    # source-provenanced target list price for the plafon's price type.
    customer_norm = norm(header.kodecustomer)
    sales_norm = norm(header.kodesales)
    assert customer_norm is not None and sales_norm is not None
    plafon_matches = master["plafons"].get((row.source_system, customer_norm, principal_norm, sales_norm), [])
    if len(plafon_matches) != 1:
        return None, detail_hold(row, "missing_or_ambiguous_exact_plafon_map_for_line", candidate_count=len(plafon_matches))
    plafon = plafon_matches[0]
    price_matches = master["prices"].get((row.source_system, principal_norm, sku_norm, plafon.id_tipe_harga), [])
    if len(price_matches) != 1 or price_matches[0].id_produk != product_id:
        return None, detail_hold(
            row,
            "missing_or_ambiguous_source_qualified_product_price_map",
            id_tipe_harga=plafon.id_tipe_harga,
            candidate_count=len(price_matches),
        )
    price_target = price_matches[0]
    return (
        LinePlan(
            row=row,
            source_urut_norm=urut_norm,
            id_produk=product_id,
            id_base_uom=base_matches[0].id_produk_uom,
            id_outer_uom=outer.id_produk_uom,
            outer_level=outer.level,
            outer_factor=factor,
            qty_base=qty_base,
            pieces_order=pieces_order,
            box_order=box_order,
            karton_order=karton_order,
            harga_order=harga,
            subtotal_dpp=dpp,
            subtotal_order=total,
            discount_amount=discount_amount,
            source_discount_percent=discount_percent,
            id_produk_harga_jual=price_target.id_produk_harga_jual,
            current_master_price=price_target.harga,
        ),
        None,
    )


def source_order_code(document_prefix: str, source_nota: str) -> str:
    """Keep a source-qualified SO identifier while never manufacturing an invoice number."""

    source_nota_norm = norm(source_nota)
    if source_nota_norm is None:
        raise ManifestError("Nota sumber kosong tidak dapat menjadi no_order.")
    # The clean master policy owns the prefix and uses a distinct value per
    # source system.  The original nota spelling is preserved only for an SO
    # draft identifier; it is explicitly never reused as no_faktur.
    return f"{document_prefix}{source_nota.strip()}"


def load_existing_documents(cur: Any) -> tuple[Mapping[tuple[str, str], ExistingDocument], Mapping[str, int]]:
    """Read existing target identities only to prevent silent target reuse."""

    docs: dict[tuple[str, str], ExistingDocument] = {}
    map_rows = query_dicts(
        cur,
        f"""
        SELECT source_system, source_header_table, source_nota_norm,
               source_stage_schema, source_stage_run_id, source_staging_id,
               source_row_hash, id_sales_order, id_faktur
          FROM {qtable(REGISTRY_SCHEMA, 'sales_document_map')}
         WHERE source_system = ANY(%s)
           AND source_header_table = %s
        """,
        (list(SOURCE_SYSTEMS), SOURCE_HEADER_TABLE),
    )
    for row in map_rows:
        source = str(row["source_system"])
        nota = norm(row["source_nota_norm"])
        if nota is None:
            raise ManifestError("sales_document_map memiliki source_nota_norm kosong.")
        key = (source, nota)
        if key in docs:
            raise ManifestError("sales_document_map memiliki duplicate source identity.")
        docs[key] = ExistingDocument(
            stage_schema=str(row["source_stage_schema"]),
            stage_run_id=int(row["source_stage_run_id"]),
            staging_id=int(row["source_staging_id"]),
            source_row_hash=str(row["source_row_hash"]).lower(),
            id_sales_order=int(row["id_sales_order"]),
            id_faktur=int(row["id_faktur"]),
        )
    cur.execute("SELECT lower(btrim(no_order)), count(*)::bigint FROM public.sales_order WHERE no_order IS NOT NULL GROUP BY lower(btrim(no_order))")
    order_codes = {str(code): int(count) for code, count in cur.fetchall() if clean(code) is not None}
    return docs, order_codes


def target_column_length(columns: Mapping[str, Mapping[str, ColumnInfo]], table: str, column: str) -> int | None:
    item = columns.get("public", {}).get(table, {}).get(column)
    return item.max_length if item is not None else None


def target_column_nullable(columns: Mapping[str, Mapping[str, ColumnInfo]], table: str, column: str) -> bool:
    item = columns.get("public", {}).get(table, {}).get(column)
    return bool(item and item.nullable)


def append_hold(holds: list[Hold], seen: set[tuple[Any, ...]], hold: Hold) -> None:
    identity = hold.identity()
    if identity not in seen:
        seen.add(identity)
        holds.append(hold)


def plan_pd_documents(
    *,
    headers_by_source: Mapping[str, list[HeaderRow]],
    details_by_source: Mapping[str, list[DetailRow]],
    contexts: Mapping[str, Mapping[str, Any]],
    master: Mapping[str, Any],
    target_contract: Mapping[str, Any],
    money_tolerance: Decimal,
    existing_documents: Mapping[tuple[str, str], ExistingDocument],
    existing_order_codes: Mapping[str, int],
    header_audit_columns_by_source: Mapping[str, Sequence[str]] | None = None,
) -> tuple[list[DocumentPlan], list[Hold], Mapping[str, Any]]:
    """Return PD-only candidates and granular source-qualified holds."""

    holds: list[Hold] = []
    hold_seen: set[tuple[Any, ...]] = set()
    plans: list[DocumentPlan] = []
    source_summary: dict[str, Any] = {}
    no_order_length = target_column_length(target_contract, "sales_order", "no_order")
    due_date_nullable = target_column_nullable(target_contract, "sales_order", "tanggal_jatuh_tempo")
    planned_codes: dict[str, HeaderRow] = {}

    for source in SOURCE_SYSTEMS:
        all_headers = headers_by_source[source]
        all_details = details_by_source[source]
        status_counts = Counter(normalized_status(header.stnota) or "(blank)" for header in all_headers)
        headers_by_nota: dict[str, list[HeaderRow]] = defaultdict(list)
        details_by_nota: dict[str, list[DetailRow]] = defaultdict(list)
        for header in all_headers:
            key = norm(header.nota)
            if key is not None:
                headers_by_nota[key].append(header)
            elif normalized_status(header.stnota) == SOURCE_STATUS:
                append_hold(holds, hold_seen, header_hold(header, "blank_source_nota"))
        for detail in all_details:
            key = norm(detail.nota)
            if key is not None:
                details_by_nota[key].append(detail)
            # A detail with no Nota cannot be proven to be part of PD scope;
            # keep it out of PD candidates rather than guessing its header.

        pd_headers = [header for header in all_headers if normalized_status(header.stnota) == SOURCE_STATUS]
        ready_before = len(plans)
        hold_before = len(holds)
        for header in pd_headers:
            nota_norm = norm(header.nota)
            if nota_norm is None:
                continue
            same_headers = headers_by_nota.get(nota_norm, [])
            if len(same_headers) != 1:
                append_hold(
                    holds,
                    hold_seen,
                    header_hold(
                        header,
                        "duplicate_source_header_nota",
                        source_nota_norm=nota_norm,
                        count=len(same_headers),
                        status_profile=dict(sorted(Counter(normalized_status(item.stnota) or "(blank)" for item in same_headers).items())),
                    ),
                )
                continue
            lifecycle_holds = pd_lifecycle_holds(header)
            if lifecycle_holds:
                for hold in lifecycle_holds:
                    append_hold(holds, hold_seen, hold)
                continue
            details = details_by_nota.get(nota_norm, [])
            customer_norm = norm(header.kodecustomer)
            principal_norm = norm(header.kodeprinciple)
            sales_norm = norm(header.kodesales)
            if customer_norm is None or principal_norm is None or sales_norm is None:
                append_hold(
                    holds,
                    hold_seen,
                    header_hold(
                        header,
                        "blank_source_master_code",
                        kodecustomer=header.kodecustomer,
                        kodeprinciple=header.kodeprinciple,
                        kodesales=header.kodesales,
                    ),
                )
                continue
            customer_target = master["customers"].get((source, customer_norm))
            principal_target = master["principals"].get((source, principal_norm))
            sales_target = master["sales"].get((source, principal_norm, sales_norm))
            missing_maps: list[str] = []
            if customer_target is None:
                missing_maps.append("customer")
            if principal_target is None:
                missing_maps.append("principal")
            if sales_target is None:
                missing_maps.append("sales")
            if missing_maps:
                append_hold(
                    holds,
                    hold_seen,
                    header_hold(header, "missing_committed_exact_header_mapping", missing=missing_maps),
                )
                continue
            plafon_matches = master["plafons"].get((source, customer_norm, principal_norm, sales_norm), [])
            if len(plafon_matches) != 1:
                append_hold(
                    holds,
                    hold_seen,
                    header_hold(
                        header,
                        "missing_or_ambiguous_exact_plafon_map",
                        candidate_count=len(plafon_matches),
                        id_customer=customer_target[0],
                        id_principal=principal_target,
                        id_sales=sales_target,
                    ),
                )
                continue
            plafon = plafon_matches[0]
            order_date, order_date_problem = parse_source_date(header.tanggal_raw, "tanggal", required=True)
            due_date, due_date_problem = parse_source_date(header.jatuhtempo_raw, "jatuhtempo", required=False)
            if order_date_problem or order_date is None:
                append_hold(holds, hold_seen, header_hold(header, order_date_problem or "invalid_tanggal"))
                continue
            if due_date_problem:
                append_hold(holds, hold_seen, header_hold(header, due_date_problem))
                continue
            if due_date is None and not due_date_nullable:
                append_hold(holds, hold_seen, header_hold(header, "target_required_due_date_missing"))
                continue
            total_penjualan, total_problem = parse_nonnegative_decimal(header.totalpenjualan_raw, "totalpenjualan")
            if total_problem:
                append_hold(holds, hold_seen, header_hold(header, total_problem))
                continue
            else:
                assert total_penjualan is not None
                if not details:
                    append_hold(holds, hold_seen, header_hold(header, "header_without_detail"))
                    continue

                by_urut: dict[str, list[DetailRow]] = defaultdict(list)
                line_failed = False
                for detail in details:
                    urut_norm = norm(detail.urut)
                    if urut_norm is None:
                        append_hold(holds, hold_seen, detail_hold(detail, "blank_source_urut"))
                        line_failed = True
                    else:
                        by_urut[urut_norm].append(detail)
                for urut_norm, grouped in sorted(by_urut.items()):
                    if len(grouped) > 1:
                        for detail in grouped:
                            append_hold(
                                holds,
                                hold_seen,
                                detail_hold(
                                    detail,
                                    "duplicate_source_line_urut",
                                    source_urut_norm=urut_norm,
                                    count=len(grouped),
                                ),
                            )
                        line_failed = True
                lines: list[LinePlan] = []
                if not line_failed:
                    for detail in details:
                        line, line_hold = resolve_line(
                            detail,
                            header,
                            principal_norm=principal_norm,
                            order_date=order_date,
                            master=master,
                        )
                        if line_hold is not None:
                            append_hold(holds, hold_seen, line_hold)
                            line_failed = True
                        elif line is not None:
                            lines.append(line)
                if line_failed:
                    append_hold(holds, hold_seen, header_hold(header, "header_detail_validation_failed"))
                    continue
                if not lines:
                    append_hold(holds, hold_seen, header_hold(header, "header_without_eligible_detail"))
                    continue
                line_total = sum((line.subtotal_order for line in lines), Decimal("0"))
                if not money_equal(total_penjualan, line_total, money_tolerance):
                    append_hold(
                        holds,
                        hold_seen,
                        header_hold(
                            header,
                            "header_detail_total_mismatch",
                            header_total=total_penjualan,
                            detail_total=line_total,
                            tolerance=money_tolerance,
                        ),
                    )
                    continue
                subtotal_dpp = sum((line.subtotal_dpp for line in lines), Decimal("0"))
                if subtotal_dpp > total_penjualan + money_tolerance:
                    append_hold(
                        holds,
                        hold_seen,
                        header_hold(
                            header,
                            "header_total_less_than_detail_dpp",
                            header_total=total_penjualan,
                            detail_dpp=subtotal_dpp,
                        ),
                    )
                    continue
                try:
                    order_code = source_order_code(str(contexts[source]["document_prefix"]), header.nota or "")
                except ManifestError:
                    append_hold(holds, hold_seen, header_hold(header, "invalid_source_nota_for_sales_order_code"))
                    continue
                if no_order_length is not None and len(order_code) > no_order_length:
                    append_hold(
                        holds,
                        hold_seen,
                        header_hold(
                            header,
                            "sales_order_code_exceeds_target_length",
                            code_length=len(order_code),
                            max_length=no_order_length,
                        ),
                    )
                    continue
                existing = existing_documents.get((source, nota_norm))
                if existing is not None:
                    reason = "source_document_already_registered_exact" if existing.source_row_hash == header.source_row_hash else "existing_document_source_hash_changed"
                    append_hold(
                        holds,
                        hold_seen,
                        header_hold(
                            header,
                            reason,
                            existing_stage_schema=existing.stage_schema,
                            existing_stage_run_id=existing.stage_run_id,
                            existing_staging_id=existing.staging_id,
                            id_sales_order=existing.id_sales_order,
                            id_faktur=existing.id_faktur,
                        ),
                    )
                    continue
                code_key = norm(order_code)
                if code_key is None:
                    append_hold(holds, hold_seen, header_hold(header, "invalid_generated_sales_order_code"))
                    continue
                if existing_order_codes.get(code_key, 0):
                    append_hold(
                        holds,
                        hold_seen,
                        header_hold(header, "generated_sales_order_code_already_exists", no_order=order_code),
                    )
                    continue
                previous = planned_codes.get(code_key)
                if previous is not None:
                    append_hold(
                        holds,
                        hold_seen,
                        header_hold(header, "generated_sales_order_code_collision_in_plan", no_order=order_code),
                    )
                    append_hold(
                        holds,
                        hold_seen,
                        header_hold(previous, "generated_sales_order_code_collision_in_plan", no_order=order_code),
                    )
                    # The earlier row was tentatively appended before the
                    # collision was visible.  Remove it so a held source
                    # identity cannot remain in the review-candidate set.
                    plans[:] = [plan for plan in plans if plan.row is not previous]
                    planned_codes.pop(code_key, None)
                    continue
                planned_codes[code_key] = header
                plans.append(
                    DocumentPlan(
                        row=header,
                        source_nota=header.nota or "",
                        source_nota_norm=nota_norm,
                        sales_order_code=order_code,
                        id_customer=customer_target[0],
                        id_principal=principal_target,
                        id_sales=sales_target,
                        plafon=plafon,
                        tanggal_order=order_date,
                        tanggal_jatuh_tempo=due_date,
                        total_penjualan=total_penjualan,
                        subtotal_dpp=subtotal_dpp,
                        subtotal_diskon=sum((line.discount_amount for line in lines), Decimal("0")),
                        pajak=max(total_penjualan - subtotal_dpp, Decimal("0")),
                        lines=tuple(sorted(lines, key=lambda item: item.source_urut_norm)),
                    )
                )

        source_summary[source] = {
            "canonical_header_rows": len(all_headers),
            "canonical_detail_rows": len(all_details),
            "source_status_counts": dict(sorted(status_counts.items())),
            "pd_header_rows": len(pd_headers),
            "non_pd_header_rows_excluded": len(all_headers) - len(pd_headers),
            "candidate_documents": len(plans) - ready_before,
            "holds_created": len(holds) - hold_before,
            "pd_lifecycle_audit": pd_header_lifecycle_audit(
                pd_headers,
                (header_audit_columns_by_source or {}).get(source, ()),
            ),
        }
    for source in SOURCE_SYSTEMS:
        source_summary[source]["candidate_documents"] = sum(
            plan.row.source_system == source for plan in plans
        )
    return plans, holds, source_summary


def line_as_json(line: LinePlan) -> Mapping[str, Any]:
    return {
        "source": {
            "source_table": SOURCE_DETAIL_TABLE,
            "stage_schema": line.row.stage_schema,
            "stage_run_id": line.row.stage_run_id,
            "staging_id": line.row.staging_id,
            "source_row_hash": line.row.source_row_hash,
            "source_nota": line.row.nota,
            "source_nota_norm": norm(line.row.nota),
            "source_urut": line.row.urut,
            "source_urut_norm": line.source_urut_norm,
            "source_sku": line.row.kodestok,
        },
        "master_targets": {
            "id_produk": line.id_produk,
            "id_produk_uom_base": line.id_base_uom,
            "id_produk_uom_outer": line.id_outer_uom,
            "id_produk_harga_jual": line.id_produk_harga_jual,
        },
        "uom_conversion": {
            "source_base_uom": line.row.pc,
            "source_outer_uom": line.row.ct,
            "target_outer_level": line.outer_level,
            "factor": line.outer_factor,
            "qty_base": line.qty_base,
            "pieces_order": line.pieces_order,
            "box_order": line.box_order,
            "karton_order": line.karton_order,
        },
        "money": {
            "source_harga_order": decimal_text(line.harga_order),
            "current_master_list_price": decimal_text(line.current_master_price),
            "current_master_list_price_equal_source": (
                line.current_master_price is not None and line.current_master_price == line.harga_order
            ),
            "subtotal_dpp": decimal_text(line.subtotal_dpp),
            "subtotal_order": decimal_text(line.subtotal_order),
            "source_discount_amount_components_total": decimal_text(line.discount_amount),
            "source_discount_percent_components_total": decimal_text(line.source_discount_percent),
        },
    }


def document_as_json(plan: DocumentPlan, draft: DraftPolicy) -> Mapping[str, Any]:
    return {
        "decision": "REVIEW_CANDIDATE_ONLY",
        "source": {
            "source_system": plan.row.source_system,
            "source_header_table": SOURCE_HEADER_TABLE,
            "stage_schema": plan.row.stage_schema,
            "stage_run_id": plan.row.stage_run_id,
            "staging_id": plan.row.staging_id,
            "source_row_hash": plan.row.source_row_hash,
            "source_nota": plan.source_nota,
            "source_nota_norm": plan.source_nota_norm,
            "source_status": SOURCE_STATUS,
        },
        "master_targets": {
            "id_customer": plan.id_customer,
            "id_principal": plan.id_principal,
            "id_sales": plan.id_sales,
            "id_plafon": plan.plafon.id_plafon,
            "id_tipe_harga": plan.plafon.id_tipe_harga,
            "kode_tipe_harga": plan.plafon.kode_tipe_harga,
            "plafon_lock_order": plan.plafon.lock_order,
            "plafon_sisa_bon": decimal_text(plan.plafon.sisa_bon),
            "plafon_limit_bon": decimal_text(plan.plafon.limit_bon),
        },
        "target_draft_mapping": {
            "sales_order": {
                "no_order": plan.sales_order_code,
                "status_order": draft.status_order,
                "status_label": draft.status_order_label,
                "tanggal_order": plan.tanggal_order.isoformat(),
                "tanggal_faktur": None,
                "tanggal_terkirim": None,
                "tanggal_jatuh_tempo": plan.tanggal_jatuh_tempo.isoformat() if plan.tanggal_jatuh_tempo else None,
            },
            "faktur": {
                "status_faktur": draft.status_faktur,
                "status_label": draft.status_faktur_label,
                "no_faktur": None,
                "issuance": "deferred",
                "total_dana_diterima": "0",
                "nominal_retur": "0",
            },
            "operations_explicitly_absent": [
                "delivery_confirmation",
                "picking",
                "stock_or_hpp_ledger",
                "payment_or_receivable_settlement",
                "return_or_credit_note",
                "manifest_or_route_assignment",
            ],
        },
        "money": {
            "total_penjualan": decimal_text(plan.total_penjualan),
            "subtotal_dpp": decimal_text(plan.subtotal_dpp),
            "subtotal_diskon_source_components": decimal_text(plan.subtotal_diskon),
            "pajak_derived": decimal_text(plan.pajak),
        },
        "line_count": len(plan.lines),
        "lines": [line_as_json(line) for line in plan.lines],
    }


def stage_as_json(stage: StageInfo) -> Mapping[str, Any]:
    return {
        "schema": stage.schema,
        "run_id": stage.run_id,
        "consistency_mode": stage.consistency_mode,
        "maintenance_window_id": stage.maintenance_window_id,
        "maintenance_freeze_attested": stage.maintenance_freeze_attested,
        "maintenance_freeze_confirmed_at": stage.maintenance_freeze_confirmed_at,
        "source_transaction_isolation": stage.source_transaction_isolation,
        "frozen_window": {
            "start_inclusive": stage.window_start.isoformat(),
            "end_exclusive": stage.window_end_exclusive.isoformat(),
        },
        "selection_contract": json_safe(stage.selection_contract),
        "target_company_id": stage.target_company_id,
        "target_branch_id": stage.target_branch_id,
        "snapshot_sha256": stage.snapshot_sha256,
        "manifest_sha256": stage.manifest_sha256,
        "table_counts": dict(stage.table_counts),
    }


def build_report(
    *,
    target_database: str,
    clean_policy_sha256: str,
    pd_policy_sha256: str,
    draft: DraftPolicy,
    stages: Mapping[str, StageInfo],
    target_contract: Mapping[str, Any],
    target_counts: Mapping[str, int],
    master: Mapping[str, Any],
    documents: Sequence[DocumentPlan],
    holds: Sequence[Hold],
    source_summary: Mapping[str, Any],
    structural_blockers: Sequence[Mapping[str, Any]],
    money_tolerance: Decimal,
) -> Mapping[str, Any]:
    document_rows = [document_as_json(plan, draft) for plan in sorted(documents, key=lambda item: (item.row.source_system, item.source_nota_norm, item.row.staging_id))]
    hold_rows = [hold.as_json() for hold in sorted(holds, key=lambda item: stable_json(item.as_json()))]
    hold_summary = Counter(str(item["reason"]) for item in hold_rows)
    source_candidate_counts = Counter(str(item["source"]["source_system"]) for item in document_rows)
    source_line_counts = Counter(
        str(item["source"]["source_system"])
        for item in document_rows
        for _line in item["lines"]
    )
    plan_body = {
        "report_version": REPORT_VERSION,
        "target_database": target_database,
        "clean_policy_sha256": clean_policy_sha256,
        "pd_draft_policy_sha256": pd_policy_sha256,
        "status_mapping": {
            "source_status": SOURCE_STATUS,
            "sales_order_status": draft.status_order,
            "faktur_status": draft.status_faktur,
            "no_faktur": None,
            "tanggal_faktur": None,
            "tanggal_terkirim": None,
        },
        "money_tolerance": decimal_text(money_tolerance),
        "money_reconciliation": json_safe(draft.money_reconciliation),
        "stages": {source: stage_as_json(stages[source]) for source in SOURCE_SYSTEMS},
        "structural_blockers": list(structural_blockers),
        "documents": document_rows,
        "holds": hold_rows,
    }
    plan_sha256 = stable_hash(plan_body)
    execution_eligible = not structural_blockers and not hold_rows
    report_body: dict[str, Any] = {
        "format": "clean-pd-sales-manifest-v1",
        "report_version": REPORT_VERSION,
        "immutability": {
            "generated_at": None,
            "rule": "The report is deterministic for the frozen repeatable-read snapshot. A different report cannot overwrite the same output path.",
        },
        "database_access": {
            "target_database": target_database,
            "transaction_isolation": "REPEATABLE READ",
            "transaction_read_only": True,
            "target_database_writes": False,
            "sql_server_access": False,
            "apply_mode_supported": False,
        },
        "scope": {
            "source_systems": list(SOURCE_SYSTEMS),
            "canonical_source_family": f"{SOURCE_HEADER_TABLE} + {SOURCE_DETAIL_TABLE}",
            "source_status_exact": SOURCE_STATUS,
            "excluded_source_statuses": "all statuses other than PD",
            "excluded_source_families": ["HJualSMAndroid", "DJualSMAndroid"],
        },
        "policies": {
            "clean_policy_sha256": clean_policy_sha256,
            "pd_draft_policy_id": draft.policy_id,
            "pd_draft_policy_sha256": pd_policy_sha256,
            "pd_draft_policy_approval_status": "draft_review_only",
            "frozen_stage_scope": {
                "consistency_mode": draft.frozen_stage_scope.consistency_mode,
                "maintenance_freeze_attested": draft.frozen_stage_scope.maintenance_freeze_attested,
                "maintenance_window_id": draft.frozen_stage_scope.maintenance_window_id,
                "source_transaction_isolation": draft.frozen_stage_scope.source_transaction_isolation,
                "window_start": draft.frozen_stage_scope.window_start.isoformat(),
                "window_end_exclusive": draft.frozen_stage_scope.window_end_exclusive.isoformat(),
                "header_selection": dict(draft.frozen_stage_scope.header_selection),
                "detail_selection": dict(draft.frozen_stage_scope.detail_selection),
            },
        },
        "target_draft_mapping": {
            "sales_order": {
                "status_order": draft.status_order,
                "status_label": draft.status_order_label,
                "tanggal_faktur": None,
                "tanggal_terkirim": None,
            },
            "faktur": {
                "status_faktur": draft.status_faktur,
                "status_label": draft.status_faktur_label,
                "no_faktur": None,
                "issuance": "deferred",
            },
            "not_planned": [
                "delivery_confirmation",
                "picking",
                "stock_or_hpp_ledger",
                "payment_or_receivable_settlement",
                "return_or_credit_note",
                "manifest_or_route_assignment",
            ],
        },
        "money_reconciliation": {
            **json_safe(draft.money_reconciliation),
            "configured_header_detail_total_tolerance_rp": decimal_text(money_tolerance),
        },
        "stages": {source: stage_as_json(stages[source]) for source in SOURCE_SYSTEMS},
        "target_contract": {
            "transaction_counts": dict(sorted(target_counts.items())),
            "sales_order_and_faktur_constraints": target_contract.get("constraints", {}).get("items", []),
        },
        "master_map_summary": master.get("summary", {}),
        "source_summary": source_summary,
        "counts": {
            "candidate_documents": len(document_rows),
            "candidate_lines": sum(len(item["lines"]) for item in document_rows),
            "candidate_documents_by_source": dict(sorted(source_candidate_counts.items())),
            "candidate_lines_by_source": dict(sorted(source_line_counts.items())),
            "holds": len(hold_rows),
            "holds_by_reason": dict(sorted(hold_summary.items())),
            "proposed_sales_order_drafts": len(document_rows),
            "proposed_numberless_faktur_drafts": len(document_rows),
            "proposed_faktur_details": len(document_rows),
            "proposed_sales_order_details": sum(len(item["lines"]) for item in document_rows),
        },
        "execution_eligibility": {
            "eligible_for_future_apply_review": execution_eligible,
            "reason": (
                "No structural blocker or source hold remains. This remains a review-only report; a separate approved importer is still required."
                if execution_eligible
                else "At least one structural blocker or source-qualified hold remains; this report is not an apply authorization."
            ),
        },
        "plan_sha256": plan_sha256,
        "candidate_documents": document_rows,
        "holds": hold_rows,
        "structural_blockers": list(structural_blockers),
    }
    report_sha256 = stable_hash(report_body)
    return {**report_body, "report_sha256": report_sha256}


def write_immutable_report(path: Path, report: Mapping[str, Any]) -> str:
    """Create once; an existing output must be semantically byte-for-byte equivalent."""

    encoded = json.dumps(json_safe(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManifestError(f"Output manifest yang sudah ada tidak dapat diverifikasi: {path}") from exc
        if stable_json(existing) != stable_json(report):
            raise ManifestError(
                f"Output manifest sudah ada dan berbeda: {path}. Gunakan path baru; report immutable tidak boleh ditimpa."
            )
        return "already_present_identical"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
    except FileExistsError:
        # Race-safe re-check; do not replace a concurrently generated report.
        return write_immutable_report(path, report)
    return "created"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dsn", help="DSN PostgreSQL target clean; harus memuat dbname eksplisit.")
    parser.add_argument("--target-database", help="Harus persis database blue/green budimas_clean_* pada DSN.")
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path(__file__).with_name("clean_import_policy.json"),
        help="clean_import_policy.json yang mendefinisikan frozen BDM/TMP schema.",
    )
    parser.add_argument(
        "--pd-draft-policy",
        type=Path,
        default=Path(__file__).with_name("policy_drafts") / "clean_pd_sales_manifest_20260902.draft.json",
        help="Policy draft read-only PD; status draft tidak perlu dan tidak boleh menjadi approved untuk report.",
    )
    parser.add_argument("--bdm-stage-run-id", type=int, help="Pilih exact run BDM jika diperlukan.")
    parser.add_argument("--tmp-stage-run-id", type=int, help="Pilih exact run TMP jika diperlukan.")
    parser.add_argument("--money-tolerance", default="0.05", help="Toleransi header/detail total, default 0.05.")
    parser.add_argument("--statement-timeout-seconds", type=int, default=600)
    parser.add_argument("--output", type=Path, help="File JSON immutable yang wajib dibuat untuk dry-run non-test.")
    parser.add_argument("--self-test", action="store_true", help="Jalankan test lokal tanpa koneksi database.")
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace) -> Decimal:
    if args.self_test:
        return Decimal("0.05")
    if not args.dsn or not args.target_database or args.output is None:
        raise GuardError("--dsn, --target-database, dan --output wajib untuk dry-run manifest.")
    assert_clean_target_database_name(args.target_database, label="--target-database")
    if args.bdm_stage_run_id is not None and args.bdm_stage_run_id <= 0:
        raise GuardError("--bdm-stage-run-id harus positif.")
    if args.tmp_stage_run_id is not None and args.tmp_stage_run_id <= 0:
        raise GuardError("--tmp-stage-run-id harus positif.")
    if not 1 <= args.statement_timeout_seconds <= 3600:
        raise GuardError("--statement-timeout-seconds harus 1..3600.")
    tolerance, problem = parse_nonnegative_decimal(args.money_tolerance, "money_tolerance")
    if problem or tolerance is None:
        raise GuardError("--money-tolerance harus desimal non-negatif.")
    return tolerance


def run_self_test() -> int:
    assert parse_nonnegative_integer("48.000", "jumlah") == (48, None)
    assert parse_nonnegative_integer("48.5", "jumlah")[1] == "non_integral_jumlah"
    assert parse_source_date("2026-08-30 10:20:30", "tanggal", required=True) == (date(2026, 8, 30), None)
    assert parse_source_date("30/08/2026", "tanggal", required=True)[1] == "invalid_tanggal_format"
    assert source_order_code("BDM-SLO/", "SNP26080001") == "BDM-SLO/SNP26080001"
    assert source_order_code("BDM-SLO/", "A B") != source_order_code("BDM-SLO/", "AB")
    assert_clean_target_database_name("budimas_clean_uat", label="self-test")
    try:
        assert_clean_target_database_name("budimas_dev", label="self-test")
    except GuardError:
        pass
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("production database guard did not reject budimas_dev")
    test_frozen_scope = parse_frozen_stage_scope(
        {
            "consistency_mode": "maintenance_freeze_serializable",
            "maintenance_freeze_attested": True,
            "maintenance_window_id": "aug2026-bdm-tmp-20260830-01",
            "source_transaction_isolation": "SERIALIZABLE",
            "window_start": "2026-08-01T00:00:00",
            "window_end_exclusive": "2026-09-01T00:00:00",
            "header_selection": {"mode": "date", "date_column": "Tanggal"},
            "detail_selection": {
                "mode": "child",
                "parent_table": "HJualSM",
                "child_key_column": "Nota",
                "parent_key_column": "Nota",
                "parent_date_column": "Tanggal",
            },
        }
    )
    assert test_frozen_scope.window_start == datetime(2026, 8, 1)
    assert test_frozen_scope.window_end_exclusive == datetime(2026, 9, 1)
    test_money_reconciliation = parse_money_reconciliation(
        {
            "header_detail_total_tolerance_rp": "0.05",
            "discount_percentage_formula": "net_after_percent = gross × (1 - Disc1/100) × (1 - Disc2/100) × (1 - Disc3/100)",
            "discount_amount_components": ["DiscRp", "DiscRp1", "DiscRp2", "DiscRp3"],
            "review_rule": "review only",
        }
    )
    assert test_money_reconciliation["header_detail_total_tolerance_rp"] == "0.05"
    assert validate_exact_stage_selection(
        {"mode": "date", "date_column": "Tanggal"},
        schema="self_test",
        table="hjualsm",
        expected=test_frozen_scope.header_selection,
    )["mode"] == "date"
    try:
        validate_exact_stage_selection(
            {"mode": "all"},
            schema="self_test",
            table="hjualsm",
            expected=test_frozen_scope.header_selection,
        )
    except ManifestError:
        pass
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("date-range selection guard accepted mode=all")
    header = HeaderRow(
        "bdm_solo_dist", "legacy_bdm_test", 1, 1, "a" * 64,
        "SNP26080001", "2026-08-30", "S01", "Sales", "C01", "Toko", "P01", None,
        None, "100", "0", "0", "PD", "2026-08-30 08:00:00",
    )
    assert not pd_lifecycle_holds(header), "TglReal default must remain audit-only"
    header_with_userpk = HeaderRow(
        "bdm_solo_dist", "legacy_bdm_test", 1, 3, "c" * 64,
        "SNP26080002", "2026-08-30", "S01", "Sales", "C01", "Toko", "P01", None,
        None, "100", "0", "0", "PD", "2026-08-30 08:00:00",
        userpk_raw="operator",
    )
    assert [item.reason for item in pd_lifecycle_holds(header_with_userpk)] == [
        "source_userpk_requires_lifecycle_review"
    ]
    detail = DetailRow(
        "bdm_solo_dist", "legacy_bdm_test", 1, 2, "b" * 64,
        "SNP26080001", "1", "2026-08-30", "SKU", None, "CT", "PCS", "1", "0", "1", "1", "100", "100", "100",
        "S01", "C01", "P01", "0", "0", "0", "0", "0", "0", "0",
    )
    line = LinePlan(detail, "1", 1, 10, 10, 1, 1, 1, 1, 0, 0, Decimal("100"), Decimal("100"), Decimal("100"), Decimal("0"), Decimal("0"), 1, Decimal("100"))
    plafon = PlafonTarget(1, 1, 1, 1, 1, "MT", "1", Decimal("0"), Decimal("1000"))
    plan = DocumentPlan(header, "SNP26080001", "snp26080001", "BDM-SLO/SNP26080001", 1, 1, 1, plafon, date(2026, 8, 30), None, Decimal("100"), Decimal("100"), Decimal("0"), Decimal("0"), (line,))
    rendered = document_as_json(
        plan,
        DraftPolicy("test", 0, "draft", 0, "draft", test_frozen_scope, test_money_reconciliation),
    )
    assert rendered["target_draft_mapping"]["sales_order"]["status_order"] == 0
    assert rendered["target_draft_mapping"]["faktur"]["status_faktur"] == 0
    assert rendered["target_draft_mapping"]["faktur"]["no_faktur"] is None
    assert rendered["target_draft_mapping"]["sales_order"]["tanggal_faktur"] is None
    assert rendered["target_draft_mapping"]["sales_order"]["tanggal_terkirim"] is None
    detail_for_planner = DetailRow(
        "bdm_solo_dist", "legacy_bdm_test", 1, 2, "b" * 64,
        "SNP26080001", "1", "2026-08-30", "SKU", None, "CT", "PCS", "0", "1", "10", "1", "100", "100", "100",
        "S01", "C01", "P01", "0", "0", "0", "0", "0", "0", "0",
    )
    planner_master = {
        "customers": {("bdm_solo_dist", "c01"): (1, 1)},
        "principals": {("bdm_solo_dist", "p01"): 1},
        "sales": {("bdm_solo_dist", "p01", "s01"): 1},
        "products": {("bdm_solo_dist", "p01", "sku"): 1},
        "uoms": {
            ("bdm_solo_dist", "p01", "sku", "pcs", 1, 1): [UomTarget(1, 10, 1, 1, "pcs")],
            ("bdm_solo_dist", "p01", "sku", "ct", 2, 10): [UomTarget(1, 11, 2, 10, "ct")],
        },
        "prices": {("bdm_solo_dist", "p01", "sku", 1): [ProductPriceTarget(1, 1, 1, Decimal("100"))]},
        "plafons": {("bdm_solo_dist", "c01", "p01", "s01"): [plafon]},
    }
    planner_contract = {
        "public": {
            "sales_order": {
                "no_order": ColumnInfo("no_order", "varchar", False, None, 80),
                "tanggal_jatuh_tempo": ColumnInfo("tanggal_jatuh_tempo", "date", True, None, None),
            }
        }
    }
    candidate, candidate_holds, _summary = plan_pd_documents(
        headers_by_source={"bdm_solo_dist": [header], "tmp_solo_dist": []},
        details_by_source={"bdm_solo_dist": [detail_for_planner], "tmp_solo_dist": []},
        contexts={"bdm_solo_dist": {"document_prefix": "BDM-SLO/"}, "tmp_solo_dist": {"document_prefix": "TMP-SLO/"}},
        master=planner_master,
        target_contract=planner_contract,
        money_tolerance=Decimal("0.05"),
        existing_documents={},
        existing_order_codes={},
    )
    assert len(candidate) == 1 and not candidate_holds, [item.as_json() for item in candidate_holds]
    print(json.dumps({"status": "ok", "self_test": REPORT_VERSION}, ensure_ascii=False))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    tolerance = validate_args(args)
    if args.self_test:
        return run_self_test()
    assert args.target_database and args.output is not None
    _policy_payload, configs, clean_policy_sha256 = load_policy(args.policy)
    draft, pd_policy_sha256 = parse_draft_policy(args.pd_draft_policy)
    if tolerance != Decimal(draft.money_reconciliation["header_detail_total_tolerance_rp"]):
        raise GuardError("--money-tolerance harus Rp0.05 sesuai PD draft policy yang dibekukan.")
    conn, _current_user = connect_readonly(args)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SET LOCAL statement_timeout = '{args.statement_timeout_seconds}s'")
            cur.execute("SET LOCAL lock_timeout = '5s'")
            stages = {
                "bdm_solo_dist": resolve_stage(
                    cur, configs["bdm_solo_dist"], args.bdm_stage_run_id, draft
                ),
                "tmp_solo_dist": resolve_stage(
                    cur, configs["tmp_solo_dist"], args.tmp_stage_run_id, draft
                ),
            }
            target_contract, blockers, target_counts = validate_target_contract(cur, draft)
            required_registry = {
                "source_context", "import_run", "principal_source_map", "customer_source_map",
                "sales_source_map", "product_source_map", "product_uom_source_map",
                "product_price_source_map", "plafon_source_map", "sales_document_map", "sales_document_line_map",
            }
            missing_registry = required_registry - set(target_contract.get("registry", {}))
            missing_public = {"sales_order", "sales_order_detail", "faktur", "faktur_detail", "produk_harga_jual"} - set(target_contract.get("public", {}))
            header_audit_columns_by_source = {
                source: available_header_audit_columns(cur, stages[source]) for source in SOURCE_SYSTEMS
            }
            headers_by_source = {
                source: fetch_headers(
                    cur,
                    stages[source],
                    audit_columns=header_audit_columns_by_source[source],
                )
                for source in SOURCE_SYSTEMS
            }
            details_by_source = {source: fetch_details(cur, stages[source]) for source in SOURCE_SYSTEMS}
            if missing_registry or missing_public:
                # Do not query an absent target relation just to make a broad
                # per-document error list.  The structural contract is enough
                # to fail closed, while the source counts remain visible.
                master: Mapping[str, Any] = {"summary": {"not_loaded_due_to_target_contract": True}}
                documents: list[DocumentPlan] = []
                holds: list[Hold] = []
                source_summary = {
                    source: {
                        "canonical_header_rows": len(headers_by_source[source]),
                        "canonical_detail_rows": len(details_by_source[source]),
                        "pd_header_rows": sum(normalized_status(item.stnota) == SOURCE_STATUS for item in headers_by_source[source]),
                        "not_planned_due_to_target_contract": True,
                        "pd_lifecycle_audit": pd_header_lifecycle_audit(
                            [item for item in headers_by_source[source] if normalized_status(item.stnota) == SOURCE_STATUS],
                            header_audit_columns_by_source[source],
                        ),
                    }
                    for source in SOURCE_SYSTEMS
                }
            else:
                contexts = load_source_contexts(cur, configs, stages, blockers)
                master = load_master_maps(
                    cur,
                    stages=stages,
                    contexts=contexts,
                    target_database=args.target_database,
                    blockers=blockers,
                )
                existing_documents, existing_order_codes = load_existing_documents(cur)
                documents, holds, source_summary = plan_pd_documents(
                    headers_by_source=headers_by_source,
                    details_by_source=details_by_source,
                    contexts=contexts,
                    master=master,
                    target_contract=target_contract,
                    money_tolerance=tolerance,
                    existing_documents=existing_documents,
                    existing_order_codes=existing_order_codes,
                    header_audit_columns_by_source=header_audit_columns_by_source,
                )
        report = build_report(
            target_database=args.target_database,
            clean_policy_sha256=clean_policy_sha256,
            pd_policy_sha256=pd_policy_sha256,
            draft=draft,
            stages=stages,
            target_contract=target_contract,
            target_counts=target_counts,
            master=master,
            documents=documents,
            holds=holds,
            source_summary=source_summary,
            structural_blockers=blockers,
            money_tolerance=tolerance,
        )
        write_status = write_immutable_report(args.output, report)
        # Rollback is intentional even though the session is read-only: it
        # closes the repeatable-read snapshot without committing any setting.
        conn.rollback()
        print(
            json.dumps(
                {
                    "status": "ok",
                    "mode": "READ_ONLY_DRY_RUN",
                    "output": str(args.output),
                    "output_status": write_status,
                    "plan_sha256": report["plan_sha256"],
                    "report_sha256": report["report_sha256"],
                    "candidate_documents": report["counts"]["candidate_documents"],
                    "holds": report["counts"]["holds"],
                    "structural_blockers": len(report["structural_blockers"]),
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ImporterError as exc:
        print(json.dumps({"mode": "REFUSED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
