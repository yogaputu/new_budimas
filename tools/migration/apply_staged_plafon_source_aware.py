#!/usr/bin/env python3
"""Safely apply source-aware BDM/TMP Plafon records to ``public.plafon``.

This is deliberately separate from the older one-source legacy merge scripts.
It has the following non-negotiable rules:

* BDM and TMP remain separate source systems until their mapped target triple
  (customer, principal, sales) is known.
* Only rows with committed customer, principal, and sales mappings are eligible.
  Principal ambiguity therefore remains a hold, never a code-only guess.
* ``TglAdd`` is the only available source ordering timestamp.  The newest
  parseable source record wins.  Equal newest timestamps with different credit
  values are held instead of using an arbitrary source priority.
* Source ``Plafon`` maps to ``limit_bon`` and ``Term`` maps to both ``top`` and
  ``tempo``.  No source field describes the target price type, and the legacy
  ``Lock1`` values (commonly ``X``/``x``/``1``) are not silently translated to
  the target application's ``lock_order`` semantics.
* Updating an existing record preserves already-used credit: ``sisa_bon`` is
  adjusted by the limit delta rather than reset to the new limit.  A new record
  starts with ``sisa_bon = limit_bon``.
* A new record is created only when all non-nullable target fields have a
  database default, a defensible derived value, or an explicitly supplied
  command-line policy.  In particular, ``--new-row-price-type-id`` is required
  if ``id_tipe_harga`` has no default and cannot be NULL.
* Dry-run is the default.  ``--apply`` additionally rejects preview/non-final
  staging.  It accepts either SQL Server SNAPSHOT for both sources, or the
  explicit, matching ``maintenance_freeze_serializable`` attestation generated
  by the staging tool for both sources.  It locks only PostgreSQL
  ``public.plafon`` during the short atomic write and stores run, selection,
  and hold audits in the mapping registry.

The tool never connects to SQL Server and never changes SQL Server data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

import psycopg2  # type: ignore[import-not-found]
from psycopg2.extras import execute_values  # type: ignore[import-not-found]


REGISTRY_SCHEMA = "migration_bdm_tmp_202608"
DEFAULT_BATCH_ID = "plafon_source_aware_final_20260828"
IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
BATCH_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,119}$")
DECIMAL_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}"
    r"(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?$"
)
SOURCE_SYSTEMS = ("bdm_solo_dist", "tmp_solo_dist")
SNAPSHOT_CONSISTENCY_MODE = "snapshot"
MAINTENANCE_FREEZE_CONSISTENCY_MODE = "maintenance_freeze_serializable"
SOURCE_REQUIRED_COLUMNS = {
    "kodecustomer",
    "kodeprinciple",
    "kodesales",
    "plafon",
    "term",
    "tgladd",
}
STAGE_FIXED_COLUMNS = {
    "staging_id",
    "source_system",
    "target_company_id",
    "target_branch_id",
    "legacy_table",
    "source_row_hash",
    "imported_at",
}
TARGET_BASE_COLUMNS = {
    "id",
    "id_customer",
    "id_principal",
    "id_sales",
    "limit_bon",
    "sisa_bon",
    "top",
    "tempo",
    "tempo_label",
}


class ValidationError(RuntimeError):
    """A migration input is insufficient for a safe plan or apply."""


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
    manifest_rows: int
    source_columns: tuple[str, ...]


@dataclass(frozen=True)
class MappingTarget:
    target_id: int
    method: str


@dataclass(frozen=True)
class CustomerTarget:
    id_customer: int
    id_cabang: int | None


@dataclass(frozen=True)
class PrincipalTarget:
    id_principal: int
    id_perusahaan: int | None


@dataclass(frozen=True)
class SalesTarget:
    id_sales: int
    id_principal: int | None
    id_user: int | None
    user_company_id: int | None
    user_branch_id: int | None


@dataclass(frozen=True)
class TargetColumn:
    name: str
    data_type: str
    udt_name: str
    nullable: bool
    column_default: str | None
    is_identity: bool
    is_generated: bool
    max_length: int | None
    numeric_precision: int | None
    numeric_scale: int | None

    @property
    def requires_value_on_insert(self) -> bool:
        return (
            not self.nullable
            and self.column_default is None
            and not self.is_identity
            and not self.is_generated
        )


@dataclass(frozen=True)
class StageRow:
    source_system: str
    stage_schema: str
    staging_id: int
    source_row_hash: str
    kodecustomer: str | None
    kodeprinciple: str | None
    kodesales: str | None
    plafon_raw: str | None
    term_raw: str | None
    tgladd_raw: str | None
    lock1_raw: str | None


@dataclass(frozen=True)
class Candidate:
    row: StageRow
    id_customer: int
    id_principal: int
    id_sales: int
    id_user: int | None
    source_added_at: datetime
    limit_bon: Decimal
    term: int

    @property
    def target_key(self) -> tuple[int, int, int]:
        return (self.id_customer, self.id_principal, self.id_sales)

    @property
    def semantic_payload(self) -> tuple[str, int]:
        # Decimal's canonical fixed-point representation makes ``500.0`` and
        # ``500.000`` equal for timestamp-tie comparison without using float.
        return (format(self.limit_bon.normalize(), "f"), self.term)


@dataclass(frozen=True)
class Hold:
    row: StageRow
    reason: str
    id_customer: int | None = None
    id_principal: int | None = None
    id_sales: int | None = None
    detail: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExistingPlafon:
    id_plafon: int
    id_customer: int
    id_principal: int
    id_sales: int
    limit_bon: Any
    sisa_bon: Any
    top: Any
    tempo: Any
    tempo_label: Any


@dataclass(frozen=True)
class PlannedAction:
    candidate: Candidate
    action: str  # insert, update, unchanged
    id_plafon: int | None
    limit_bon: Decimal
    sisa_bon: Decimal
    top: int
    tempo: int
    tempo_label: str | None
    generated_kode: str | None
    sisa_strategy: str


def ident(value: str) -> str:
    if not IDENT_RE.fullmatch(value):
        raise ValidationError(f"Identifier PostgreSQL tidak aman: {value!r}")
    return f'"{value}"'


def clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def norm_code(value: Any) -> str | None:
    text = clean(value)
    return text.lower() if text else None


def stage_row_key(row: StageRow) -> tuple[str, str, int]:
    """Return the source-qualified identity of a staged row.

    ``staging_id`` is only unique inside one staging schema, so BDM and TMP
    must never be keyed by that integer alone.
    """

    return (row.source_system, row.stage_schema, row.staging_id)


def clean_name(value: str) -> str:
    name = re.sub(r"[^0-9a-zA-Z_]+", "_", str(value or "").strip())
    name = re.sub(r"_+", "_", name).strip("_").lower()
    if not name:
        name = "col"
    if name[0].isdigit():
        name = f"c_{name}"
    return name


def unique_clean_columns(raw_columns: Iterable[str]) -> list[str]:
    counts: dict[str, int] = {}
    cleaned: list[str] = []
    for raw_column in raw_columns:
        base = clean_name(raw_column)
        counts[base] = counts.get(base, 0) + 1
        cleaned.append(base if counts[base] == 1 else f"{base}_{counts[base]}")
    return cleaned


def parse_decimal(value: Any) -> tuple[Decimal | None, str | None]:
    text = clean(value)
    if text is None:
        return None, "blank_limit_bon"
    if not DECIMAL_RE.fullmatch(text):
        return None, "invalid_limit_bon_format"
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None, "invalid_limit_bon_format"
    if not parsed.is_finite():
        return None, "invalid_limit_bon_format"
    if parsed < 0:
        return None, "negative_limit_bon"
    return parsed, None


def parse_nonnegative_integer(value: Any) -> tuple[int | None, str | None]:
    text = clean(value)
    if text is None:
        return None, "blank_term"
    # SQL Server decimal columns are staged as text, so ordinary values such
    # as ``10.0`` and ``24.0000`` must remain eligible.  A decimal is accepted
    # only when its numeric value is exactly integral; ``10.5`` is not rounded
    # or truncated into a payment term.
    if not DECIMAL_RE.fullmatch(text):
        return None, "invalid_term_format"
    try:
        parsed_decimal = Decimal(text)
    except InvalidOperation:
        return None, "invalid_term_format"
    if not parsed_decimal.is_finite():
        return None, "invalid_term_format"
    if parsed_decimal != parsed_decimal.to_integral_value():
        return None, "non_integral_term"
    parsed = int(parsed_decimal)
    if parsed < 0:
        return None, "negative_term"
    # This is a source sanity ceiling, not a target-column assumption.  Exact
    # target range validation happens after target metadata is read.
    if parsed > 2_147_483_647:
        return None, "term_out_of_supported_range"
    return parsed, None


def parse_source_timestamp(value: Any) -> tuple[datetime | None, str | None]:
    """Parse only unambiguous ISO-like legacy timestamps.

    No locale-dependent DD/MM/YY interpretation is permitted.  A source value
    with an explicit offset is normalised to UTC; SQL Server's normal naive
    timestamps remain naive and therefore retain their source-local ordering.
    """

    text = clean(value)
    if text is None:
        return None, "blank_tgladd"
    try:
        if DATE_RE.fullmatch(text):
            parsed = datetime.combine(date.fromisoformat(text), datetime.min.time())
        elif DATETIME_RE.fullmatch(text):
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            return None, "invalid_tgladd_format"
    except ValueError:
        return None, "invalid_tgladd_format"
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed, None


def decimal_from_target(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValidationError("Nilai numerik public.plafon tidak dapat dibaca dengan aman.")
    if not parsed.is_finite():
        raise ValidationError("Nilai numerik public.plafon bukan angka terbatas.")
    return parsed


def decimal_equal(left: Any, right: Decimal) -> bool:
    current = decimal_from_target(left)
    return current is not None and current == right


def target_integer_equal(left: Any, right: int) -> bool:
    if left is None:
        return False
    try:
        return int(left) == right
    except (TypeError, ValueError):
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bdm-schema", required=True, help="Schema staging final BDM.")
    parser.add_argument("--tmp-schema", required=True, help="Schema staging final TMP.")
    parser.add_argument(
        "--batch-id",
        default=DEFAULT_BATCH_ID,
        help=f"Kode batch audit (default: {DEFAULT_BATCH_ID}).",
    )
    parser.add_argument(
        "--new-row-price-type-id",
        type=int,
        help=(
            "Kebijakan eksplisit id_tipe_harga untuk plafon baru. Tidak dipakai "
            "untuk plafon lama dan wajib bila kolom target tidak punya default."
        ),
    )
    parser.add_argument(
        "--new-row-lock-order",
        choices=("0", "1"),
        help=(
            "Kebijakan eksplisit lock_order untuk plafon baru bila target "
            "mewajibkannya. Lock1 sumber tidak dikonversi otomatis."
        ),
    )
    parser.add_argument("--apply", action="store_true", help="Lakukan write atomik ke PostgreSQL.")
    parser.add_argument("--pg-database", default=os.getenv("MIGRATION_PG_DATABASE", "budimas_dev"))
    parser.add_argument("--pg-user", default=os.getenv("MIGRATION_PG_USER", "postgres"))
    parser.add_argument("--pg-host", default=os.getenv("MIGRATION_PG_HOST", "127.0.0.1"))
    parser.add_argument("--pg-port", type=int, default=int(os.getenv("MIGRATION_PG_PORT", "5432")))
    parser.add_argument(
        "--statement-timeout-seconds",
        type=int,
        default=300,
        help="Batas query per transaksi (default 300 detik).",
    )
    return parser.parse_args()


def fetch_stage_column_names(cur, schemas: list[str]) -> dict[tuple[str, str], set[str]]:
    cur.execute(
        """
        SELECT table_schema, table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = ANY(%s)
          AND table_name IN ('__stage_run', '__stage_manifest', 'plafon')
        """,
        (schemas,),
    )
    result: dict[tuple[str, str], set[str]] = {}
    for schema, table, column in cur.fetchall():
        result.setdefault((str(schema), str(table)), set()).add(str(column))
    return result


def latest_stage_metadata(
    cur,
    schema: str,
    expected_source: str,
    stage_columns: dict[tuple[str, str], set[str]],
) -> StageMetadata:
    run_columns = stage_columns.get((schema, "__stage_run"), set())
    manifest_columns = stage_columns.get((schema, "__stage_manifest"), set())
    plafon_columns = stage_columns.get((schema, "plafon"), set())
    missing_run = {
        "id",
        "source_system",
        "consistency_mode",
        "target_company_id",
        "target_branch_id",
        "status",
    } - run_columns
    missing_manifest = {
        "legacy_table",
        "source_columns",
        "source_row_count",
        "staged_row_count",
        "status",
    } - manifest_columns
    missing_fixed = STAGE_FIXED_COLUMNS - plafon_columns
    if missing_run or missing_manifest or missing_fixed:
        messages = []
        if missing_run:
            messages.append(f"__stage_run: {', '.join(sorted(missing_run))}")
        if missing_manifest:
            messages.append(f"__stage_manifest: {', '.join(sorted(missing_manifest))}")
        if missing_fixed:
            messages.append(f"plafon: {', '.join(sorted(missing_fixed))}")
        raise ValidationError(f"Struktur staging {schema} tidak lengkap ({'; '.join(messages)}).")

    preview_expression = "is_preview" if "is_preview" in run_columns else "(consistency_mode <> 'snapshot')"
    maintenance_window_expression = (
        "maintenance_window_id" if "maintenance_window_id" in run_columns else "NULL::text"
    )
    maintenance_attested_expression = (
        "maintenance_freeze_attested"
        if "maintenance_freeze_attested" in run_columns
        else "FALSE"
    )
    maintenance_confirmed_expression = (
        "maintenance_freeze_confirmed_at"
        if "maintenance_freeze_confirmed_at" in run_columns
        else "NULL::timestamptz"
    )
    source_isolation_expression = (
        "source_transaction_isolation"
        if "source_transaction_isolation" in run_columns
        else "NULL::text"
    )
    source_lock_timeout_expression = (
        "source_lock_timeout_ms" if "source_lock_timeout_ms" in run_columns else "NULL::integer"
    )
    cur.execute(
        f"""
        SELECT id, source_system, status, consistency_mode, {preview_expression},
               {maintenance_window_expression}, {maintenance_attested_expression},
               {maintenance_confirmed_expression}, {source_isolation_expression},
               {source_lock_timeout_expression}, target_company_id, target_branch_id
        FROM {ident(schema)}."__stage_run"
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
        SELECT status, source_row_count, staged_row_count, source_columns
        FROM {ident(schema)}."__stage_manifest"
        WHERE lower(btrim(legacy_table)) = 'plafon'
        """
    )
    manifest_rows = cur.fetchall()
    if len(manifest_rows) != 1:
        raise ValidationError(f"{schema} harus memiliki tepat satu manifest Plafon.")
    manifest_status, source_count, staged_count, raw_columns = manifest_rows[0]
    if manifest_status != "done":
        raise ValidationError(f"Manifest Plafon {schema} belum selesai (status={manifest_status!r}).")
    if source_count is None or staged_count is None or int(source_count) != int(staged_count):
        raise ValidationError(
            f"Manifest Plafon {schema} tidak konsisten: source={source_count}, staged={staged_count}."
        )
    if isinstance(raw_columns, str):
        try:
            raw_columns = json.loads(raw_columns)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"Manifest Plafon {schema} memuat source_columns tidak valid.") from exc
    if not isinstance(raw_columns, list) or not all(isinstance(item, str) and item.strip() for item in raw_columns):
        raise ValidationError(f"Manifest Plafon {schema} tidak memuat daftar source_columns valid.")
    source_columns = unique_clean_columns(raw_columns)
    missing_source = SOURCE_REQUIRED_COLUMNS - set(source_columns)
    if missing_source:
        raise ValidationError(
            f"Manifest Plafon {schema} tidak memiliki kolom wajib: {', '.join(sorted(missing_source))}."
        )
    missing_staged = set(source_columns) - plafon_columns
    if missing_staged:
        raise ValidationError(
            f"Tabel {schema}.plafon tidak memuat kolom manifest: {', '.join(sorted(missing_staged))}."
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
        manifest_rows=int(staged_count),
        source_columns=tuple(source_columns),
    )


def validate_stage_rows(cur, metadata: StageMetadata) -> None:
    cur.execute(
        f"""
        SELECT
            COUNT(*)::bigint,
            COUNT(*) FILTER (WHERE source_system IS DISTINCT FROM %s)::bigint,
            COUNT(*) FILTER (
                WHERE target_company_id IS DISTINCT FROM %s
                   OR target_branch_id IS DISTINCT FROM %s
            )::bigint,
            COUNT(*) FILTER (WHERE lower(btrim(legacy_table)) <> 'plafon')::bigint,
            COUNT(*) FILTER (WHERE source_row_hash IS NULL OR btrim(source_row_hash) = '')::bigint
        FROM {ident(metadata.schema)}.plafon
        """,
        (metadata.source_system, metadata.target_company_id, metadata.target_branch_id),
    )
    row = cur.fetchone()
    actual, wrong_source, wrong_scope, wrong_table, blank_hash = (int(value) for value in row)
    if actual != metadata.manifest_rows:
        raise ValidationError(
            f"{metadata.schema}.plafon berisi {actual} baris, bukan {metadata.manifest_rows} sesuai manifest."
        )
    invalid = {
        "wrong_source_system": wrong_source,
        "wrong_target_scope": wrong_scope,
        "wrong_legacy_table": wrong_table,
        "blank_source_row_hash": blank_hash,
    }
    if any(invalid.values()):
        raise ValidationError(
            f"Provenance {metadata.schema}.plafon tidak valid: "
            + ", ".join(f"{key}={value}" for key, value in invalid.items() if value)
        )


def final_stage_gate(stage_metadata: dict[str, StageMetadata]) -> tuple[bool, str]:
    """Return whether the pair of staging runs is safe to apply to public.

    SQL Server SNAPSHOT remains the preferred proof.  For installations where
    it is disabled, the only alternate path is the explicit staging mode
    produced by ``stage_august_2026_source.py`` during one confirmed write
    freeze.  A generic completed/read-committed run cannot be upgraded merely
    by editing its status or consistency label: the maintenance mode also
    needs its recorded attestation, timestamp, SERIALIZABLE transaction, a
    bounded lock timeout, and the same window ID for BDM and TMP.
    """

    values = list(stage_metadata.values())
    if len(values) != len(SOURCE_SYSTEMS):
        return False, "Apply ditolak: metadata staging BDM/TMP tidak lengkap."
    common_final = all(item.status == "completed" and not item.is_preview for item in values)
    if not common_final:
        return (
            False,
            "Apply ditolak sampai kedua staging berstatus completed dan bukan preview.",
        )
    if all(item.consistency_mode == SNAPSHOT_CONSISTENCY_MODE for item in values):
        return True, "Kedua staging final memakai SQL Server SNAPSHOT."
    if not all(item.consistency_mode == MAINTENANCE_FREEZE_CONSISTENCY_MODE for item in values):
        return (
            False,
            "Apply ditolak: kedua source harus sama-sama memakai SNAPSHOT, atau sama-sama "
            "maintenance_freeze_serializable dari satu maintenance window.",
        )
    window_ids = {item.maintenance_window_id for item in values if item.maintenance_window_id}
    if len(window_ids) != 1 or any(not item.maintenance_window_id for item in values):
        return (
            False,
            "Apply ditolak: staging maintenance BDM dan TMP harus memiliki maintenance_window_id yang sama.",
        )
    if any(
        not item.maintenance_freeze_attested
        or item.maintenance_freeze_confirmed_at is None
        or (item.source_transaction_isolation or "").strip().lower() != "serializable"
        or item.source_lock_timeout_ms is None
        or item.source_lock_timeout_ms <= 0
        for item in values
    ):
        return (
            False,
            "Apply ditolak: bukti write-freeze/transaction SERIALIZABLE pada staging tidak lengkap.",
        )
    window_id = next(iter(window_ids))
    return (
        True,
        "Kedua staging final memakai maintenance write-freeze terattestasi "
        f"(window {window_id}) dan transaksi SQL Server SERIALIZABLE.",
    )


def iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def fetch_stage_rows(cur, metadata: StageMetadata) -> list[StageRow]:
    lock_column = "lock1" if "lock1" in metadata.source_columns else None
    selected_lock = f"p.{ident(lock_column)}" if lock_column else "NULL::text"
    cur.execute(
        f"""
        SELECT p.staging_id, p.source_row_hash,
               p.kodecustomer, p.kodeprinciple, p.kodesales,
               p.plafon, p.term, p.tgladd, {selected_lock}
        FROM {ident(metadata.schema)}.plafon p
        WHERE p.source_system = %s
        ORDER BY p.staging_id
        """,
        (metadata.source_system,),
    )
    rows: list[StageRow] = []
    for record in cur.fetchall():
        rows.append(
            StageRow(
                source_system=metadata.source_system,
                stage_schema=metadata.schema,
                staging_id=int(record[0]),
                source_row_hash=str(record[1]),
                kodecustomer=clean(record[2]),
                kodeprinciple=clean(record[3]),
                kodesales=clean(record[4]),
                plafon_raw=clean(record[5]),
                term_raw=clean(record[6]),
                tgladd_raw=clean(record[7]),
                lock1_raw=clean(record[8]),
            )
        )
    if len(rows) != metadata.manifest_rows:
        raise ValidationError(f"Jumlah row Plafon {metadata.schema} berubah saat dibaca.")
    return rows


def fetch_source_context(cur, source_system: str) -> tuple[int, int]:
    cur.execute(
        f"""
        SELECT target_company_id, target_branch_id
        FROM {ident(REGISTRY_SCHEMA)}.source_context
        WHERE source_system = %s
        """,
        (source_system,),
    )
    rows = cur.fetchall()
    if len(rows) != 1:
        raise ValidationError(f"source_context {source_system} harus tepat satu baris.")
    return int(rows[0][0]), int(rows[0][1])


def fetch_mapping_table(
    cur,
    source_system: str,
    table: str,
    key_columns: tuple[str, ...],
    id_column: str,
) -> dict[tuple[str, ...], MappingTarget]:
    key_sql = ", ".join(ident(value) for value in key_columns)
    cur.execute(
        f"""
        SELECT {key_sql}, {ident(id_column)}, mapping_method
        FROM {ident(REGISTRY_SCHEMA)}.{ident(table)}
        WHERE source_system = %s
        """,
        (source_system,),
    )
    result: dict[tuple[str, ...], MappingTarget] = {}
    for record in cur.fetchall():
        key = tuple(str(value) for value in record[: len(key_columns)])
        if key in result:
            raise ValidationError(f"Registry {table} {source_system} memiliki source key duplikat.")
        result[key] = MappingTarget(int(record[len(key_columns)]), str(record[len(key_columns) + 1]))
    return result


def fetch_target_columns(cur) -> dict[str, TargetColumn]:
    cur.execute(
        """
        SELECT column_name, data_type, udt_name, is_nullable, column_default,
               is_identity, is_generated, character_maximum_length,
               numeric_precision, numeric_scale
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'plafon'
        """
    )
    columns: dict[str, TargetColumn] = {}
    for row in cur.fetchall():
        name = str(row[0])
        columns[name] = TargetColumn(
            name=name,
            data_type=str(row[1]),
            udt_name=str(row[2]),
            nullable=str(row[3]) == "YES",
            column_default=str(row[4]) if row[4] is not None else None,
            is_identity=str(row[5]) == "YES",
            is_generated=str(row[6]) != "NEVER",
            max_length=int(row[7]) if row[7] is not None else None,
            numeric_precision=int(row[8]) if row[8] is not None else None,
            numeric_scale=int(row[9]) if row[9] is not None else None,
        )
    missing = TARGET_BASE_COLUMNS - set(columns)
    if missing:
        raise ValidationError(
            "public.plafon tidak memiliki kolom dasar yang diperlukan: " + ", ".join(sorted(missing))
        )
    return columns


def fetch_customer_targets(cur, ids: set[int]) -> dict[int, CustomerTarget]:
    if not ids:
        return {}
    cur.execute("SELECT id, id_cabang FROM public.customer WHERE id = ANY(%s)", (sorted(ids),))
    return {
        int(record[0]): CustomerTarget(int(record[0]), int(record[1]) if record[1] is not None else None)
        for record in cur.fetchall()
    }


def fetch_principal_targets(cur, ids: set[int]) -> dict[int, PrincipalTarget]:
    if not ids:
        return {}
    cur.execute("SELECT id, id_perusahaan FROM public.principal WHERE id = ANY(%s)", (sorted(ids),))
    return {
        int(record[0]): PrincipalTarget(int(record[0]), int(record[1]) if record[1] is not None else None)
        for record in cur.fetchall()
    }


def fetch_sales_targets(cur, ids: set[int]) -> dict[int, SalesTarget]:
    if not ids:
        return {}
    cur.execute(
        """
        SELECT s.id, s.id_principal, s.id_user, u.id_perusahaan, u.id_cabang
        FROM public.sales s
        LEFT JOIN public.users u ON u.id = s.id_user
        WHERE s.id = ANY(%s)
        """,
        (sorted(ids),),
    )
    return {
        int(record[0]): SalesTarget(
            id_sales=int(record[0]),
            id_principal=int(record[1]) if record[1] is not None else None,
            id_user=int(record[2]) if record[2] is not None else None,
            user_company_id=int(record[3]) if record[3] is not None else None,
            user_branch_id=int(record[4]) if record[4] is not None else None,
        )
        for record in cur.fetchall()
    }


def integer_bounds(column: TargetColumn) -> tuple[int | None, int | None]:
    if column.data_type == "smallint":
        return (-32768, 32767)
    if column.data_type == "integer":
        return (-2_147_483_648, 2_147_483_647)
    if column.data_type == "bigint":
        return (-9_223_372_036_854_775_808, 9_223_372_036_854_775_807)
    if column.data_type in {"numeric", "decimal"}:
        if column.numeric_scale not in {None, 0}:
            return None, None
        if column.numeric_precision is not None:
            return (-(10 ** column.numeric_precision - 1), 10 ** column.numeric_precision - 1)
    return None, None


def decimal_fits_column(value: Decimal, column: TargetColumn) -> bool:
    if column.data_type in {"smallint", "integer", "bigint"}:
        if value != value.to_integral_value():
            return False
        lower, upper = integer_bounds(column)
        return (lower is None or value >= lower) and (upper is None or value <= upper)
    if column.data_type in {"numeric", "decimal"}:
        if column.numeric_scale is not None:
            decimal_places = max(0, -value.as_tuple().exponent)
            if decimal_places > column.numeric_scale:
                return False
        if column.numeric_precision is not None:
            scaled = value.copy_abs().scaleb(column.numeric_scale or 0)
            digits = len(str(int(scaled.to_integral_value()))) if scaled else 1
            if digits > column.numeric_precision:
                return False
        return True
    if column.data_type in {"double precision", "real"}:
        try:
            return math.isfinite(float(value))
        except (OverflowError, ValueError):
            return False
    # A surprising target data type should be a hard schema problem, not a
    # best-effort cast that might alter financial values.
    raise ValidationError(f"Kolom {column.name} bertipe {column.data_type!r}, bukan tipe numerik aman.")


def integer_fits_column(value: int, column: TargetColumn) -> bool:
    lower, upper = integer_bounds(column)
    if column.data_type not in {"smallint", "integer", "bigint", "numeric", "decimal"}:
        raise ValidationError(f"Kolom {column.name} bertipe {column.data_type!r}, bukan tipe angka bulat aman.")
    if column.data_type in {"numeric", "decimal"} and column.numeric_scale not in {None, 0}:
        raise ValidationError(f"Kolom {column.name} memiliki skala desimal; tidak aman untuk Term.")
    return (lower is None or value >= lower) and (upper is None or value <= upper)


def label_for_term(term: int) -> str | None:
    return f"{term} Hari" if term > 0 else None


def text_fits_column(value: str | None, column: TargetColumn) -> bool:
    if value is None:
        return column.nullable or column.column_default is not None
    if column.data_type not in {"character varying", "character", "text"}:
        raise ValidationError(f"Kolom {column.name} bertipe {column.data_type!r}, bukan teks aman.")
    return column.max_length is None or len(value) <= column.max_length


def resolve_candidates(
    rows: Iterable[StageRow],
    source_system: str,
    context: tuple[int, int],
    customer_map: dict[tuple[str, ...], MappingTarget],
    principal_map: dict[tuple[str, ...], MappingTarget],
    sales_map: dict[tuple[str, ...], MappingTarget],
    customers: dict[int, CustomerTarget],
    principals: dict[int, PrincipalTarget],
    sales: dict[int, SalesTarget],
    target_columns: dict[str, TargetColumn],
) -> tuple[list[Candidate], list[Hold], Counter[str]]:
    candidates: list[Candidate] = []
    holds: list[Hold] = []
    notices: Counter[str] = Counter()
    expected_company, expected_branch = context
    for row in rows:
        customer_code = norm_code(row.kodecustomer)
        principal_code = norm_code(row.kodeprinciple)
        sales_code = norm_code(row.kodesales)
        if customer_code is None:
            holds.append(Hold(row, "blank_customer_code"))
            continue
        if principal_code is None:
            holds.append(Hold(row, "blank_principal_code"))
            continue
        if sales_code is None:
            holds.append(Hold(row, "blank_sales_code"))
            continue
        customer = customer_map.get((customer_code,))
        if customer is None:
            holds.append(Hold(row, "missing_customer_map"))
            continue
        principal = principal_map.get((principal_code,))
        if principal is None:
            holds.append(Hold(row, "missing_principal_map", id_customer=customer.target_id))
            continue
        sales_mapping = sales_map.get((principal_code, sales_code))
        if sales_mapping is None:
            holds.append(
                Hold(
                    row,
                    "missing_sales_map",
                    id_customer=customer.target_id,
                    id_principal=principal.target_id,
                )
            )
            continue
        customer_target = customers.get(customer.target_id)
        principal_target = principals.get(principal.target_id)
        sales_target = sales.get(sales_mapping.target_id)
        if customer_target is None:
            holds.append(Hold(row, "mapped_customer_not_found", customer.target_id, principal.target_id, sales_mapping.target_id))
            continue
        if principal_target is None:
            holds.append(Hold(row, "mapped_principal_not_found", customer.target_id, principal.target_id, sales_mapping.target_id))
            continue
        if sales_target is None:
            holds.append(Hold(row, "mapped_sales_not_found", customer.target_id, principal.target_id, sales_mapping.target_id))
            continue
        if (
            customer_target.id_cabang != expected_branch
            and customer.method != "cross_branch_approved"
        ):
            holds.append(Hold(row, "mapped_customer_branch_scope_changed", customer.target_id, principal.target_id, sales_mapping.target_id))
            continue
        if principal_target.id_perusahaan != expected_company:
            holds.append(Hold(row, "mapped_principal_company_scope_changed", customer.target_id, principal.target_id, sales_mapping.target_id))
            continue
        if sales_target.id_principal != principal.target_id:
            holds.append(Hold(row, "mapped_sales_principal_scope_changed", customer.target_id, principal.target_id, sales_mapping.target_id))
            continue
        if sales_target.id_user is None:
            holds.append(Hold(row, "mapped_sales_missing_user", customer.target_id, principal.target_id, sales_mapping.target_id))
            continue
        if sales_target.user_company_id != expected_company or sales_target.user_branch_id != expected_branch:
            holds.append(Hold(row, "mapped_sales_user_scope_changed", customer.target_id, principal.target_id, sales_mapping.target_id))
            continue
        limit_bon, limit_reason = parse_decimal(row.plafon_raw)
        if limit_reason:
            holds.append(Hold(row, limit_reason, customer.target_id, principal.target_id, sales_mapping.target_id))
            continue
        term, term_reason = parse_nonnegative_integer(row.term_raw)
        if term_reason:
            holds.append(Hold(row, term_reason, customer.target_id, principal.target_id, sales_mapping.target_id))
            continue
        source_added_at, time_reason = parse_source_timestamp(row.tgladd_raw)
        if time_reason:
            holds.append(Hold(row, time_reason, customer.target_id, principal.target_id, sales_mapping.target_id))
            continue
        assert limit_bon is not None and term is not None and source_added_at is not None
        if not decimal_fits_column(limit_bon, target_columns["limit_bon"]):
            holds.append(Hold(row, "limit_bon_out_of_target_range", customer.target_id, principal.target_id, sales_mapping.target_id))
            continue
        if not integer_fits_column(term, target_columns["top"]):
            holds.append(Hold(row, "term_out_of_target_top_range", customer.target_id, principal.target_id, sales_mapping.target_id))
            continue
        if not integer_fits_column(term, target_columns["tempo"]):
            holds.append(Hold(row, "term_out_of_target_tempo_range", customer.target_id, principal.target_id, sales_mapping.target_id))
            continue
        if not text_fits_column(label_for_term(term), target_columns["tempo_label"]):
            holds.append(Hold(row, "tempo_label_out_of_target_range", customer.target_id, principal.target_id, sales_mapping.target_id))
            continue
        if row.lock1_raw is not None:
            notices["ignored_legacy_lock1_nonblank"] += 1
        candidates.append(
            Candidate(
                row=row,
                id_customer=customer.target_id,
                id_principal=principal.target_id,
                id_sales=sales_mapping.target_id,
                id_user=sales_target.id_user,
                source_added_at=source_added_at,
                limit_bon=limit_bon,
                term=term,
            )
        )
    return candidates, holds, notices


def select_newest_candidates(candidates: Iterable[Candidate]) -> tuple[list[Candidate], list[Hold]]:
    """Choose one newest source candidate per mapped target triple.

    No BDM/TMP priority is used here.  Equal timestamps only select a stable
    source when their mapped business payload is identical; otherwise every
    newest tied row is held for review.
    """

    grouped: dict[tuple[int, int, int], list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.target_key].append(candidate)
    selected: list[Candidate] = []
    holds: list[Hold] = []
    for target_key, items in grouped.items():
        newest_at = max(item.source_added_at for item in items)
        newest = [item for item in items if item.source_added_at == newest_at]
        payloads = {item.semantic_payload for item in newest}
        if len(payloads) > 1:
            for item in newest:
                holds.append(
                    Hold(
                        item.row,
                        "conflicting_equal_newest_tgladd",
                        *target_key,
                        detail={"candidate_count_at_timestamp": len(newest)},
                    )
                )
            for item in items:
                if item.source_added_at != newest_at:
                    holds.append(
                        Hold(item.row, "superseded_by_conflicting_newest_tgladd", *target_key)
                    )
            continue
        chosen = min(newest, key=lambda item: (item.row.source_system, item.row.staging_id))
        selected.append(chosen)
        for item in items:
            if item is chosen:
                continue
            reason = (
                "duplicate_equal_newest_tgladd_identical_payload"
                if item.source_added_at == newest_at
                else "superseded_by_newer_tgladd"
            )
            holds.append(Hold(item.row, reason, *target_key))
    return selected, holds


def chunks(values: list[Any], size: int) -> Iterable[list[Any]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def fetch_existing_plafon(
    cur,
    target_keys: Iterable[tuple[int, int, int]],
    *,
    lock_rows: bool,
) -> dict[tuple[int, int, int], list[ExistingPlafon]]:
    keys = sorted(set(target_keys))
    result: dict[tuple[int, int, int], list[ExistingPlafon]] = defaultdict(list)
    if not keys:
        return result
    suffix = " FOR UPDATE OF p" if lock_rows else ""
    for batch in chunks(keys, 1000):
        execute_values(
            cur,
            f"""
            WITH requested(id_customer, id_principal, id_sales) AS (VALUES %s)
            SELECT p.id, p.id_customer, p.id_principal, p.id_sales,
                   p.limit_bon, p.sisa_bon, p.top, p.tempo, p.tempo_label
            FROM public.plafon p
            JOIN requested r
              ON r.id_customer = p.id_customer
             AND r.id_principal = p.id_principal
             AND r.id_sales = p.id_sales
            {suffix}
            """,
            batch,
            page_size=len(batch),
        )
        for record in cur.fetchall():
            existing = ExistingPlafon(
                id_plafon=int(record[0]),
                id_customer=int(record[1]),
                id_principal=int(record[2]),
                id_sales=int(record[3]),
                limit_bon=record[4],
                sisa_bon=record[5],
                top=record[6],
                tempo=record[7],
                tempo_label=record[8],
            )
            result[(existing.id_customer, existing.id_principal, existing.id_sales)].append(existing)
    return result


def generated_kode(candidate: Candidate, column: TargetColumn) -> str | None:
    if column.max_length is not None and column.max_length < 16:
        return None
    source = "|".join(str(value) for value in candidate.target_key)
    digest = hashlib.sha256(f"plafon-source-aware-v1|{source}".encode("utf-8")).hexdigest().upper()
    value = f"MIGPLF-{digest}"
    return value if column.max_length is None else value[: column.max_length]


def fetch_kode_collisions(cur, codes: set[str]) -> set[str]:
    if not codes:
        return set()
    cur.execute(
        """
        SELECT lower(btrim(kode))
        FROM public.plafon
        WHERE kode IS NOT NULL
          AND lower(btrim(kode)) = ANY(%s)
        """,
        (sorted(code.lower() for code in codes),),
    )
    return {str(record[0]) for record in cur.fetchall()}


def insert_column_policy(
    target_columns: dict[str, TargetColumn], args: argparse.Namespace
) -> tuple[list[str], list[str]]:
    """Return insert columns and globally unsupported required target fields."""

    supplied = {
        "id_customer",
        "id_principal",
        "id_sales",
        "id_user",
        "limit_bon",
        "sisa_bon",
        "top",
        "tempo",
        "tempo_label",
    }
    if args.new_row_price_type_id is not None:
        supplied.add("id_tipe_harga")
    if args.new_row_lock_order is not None:
        supplied.add("lock_order")
    kode_required = "kode" in target_columns and target_columns["kode"].requires_value_on_insert
    if kode_required:
        supplied.add("kode")
    unsupported = sorted(
        name
        for name, column in target_columns.items()
        if column.requires_value_on_insert and name not in supplied
    )
    columns = [
        name
        for name in (
            "id_customer",
            "id_principal",
            "id_sales",
            "id_user",
            "limit_bon",
            "sisa_bon",
            "kode",
            "id_tipe_harga",
            "top",
            "lock_order",
            "tempo",
            "tempo_label",
        )
        if name in target_columns and name in supplied
    ]
    return columns, unsupported


def build_actions(
    cur,
    selected: Iterable[Candidate],
    existing: dict[tuple[int, int, int], list[ExistingPlafon]],
    target_columns: dict[str, TargetColumn],
    args: argparse.Namespace,
) -> tuple[list[PlannedAction], list[Hold], list[str]]:
    selected_list = list(selected)
    holds: list[Hold] = []
    actions: list[PlannedAction] = []
    insert_columns, unsupported_required = insert_column_policy(target_columns, args)
    generated_codes: dict[tuple[str, str, int], str] = {}
    if "kode" in insert_columns:
        for candidate in selected_list:
            if len(existing.get(candidate.target_key, [])) == 0:
                value = generated_kode(candidate, target_columns["kode"])
                if value is None:
                    holds.append(Hold(candidate.row, "target_kode_length_too_short", *candidate.target_key))
                else:
                    generated_codes[stage_row_key(candidate.row)] = value
        duplicate_codes = {
            code
            for code, count in Counter(generated_codes.values()).items()
            if count > 1
        }
        for candidate in selected_list:
            value = generated_codes.get(stage_row_key(candidate.row))
            if value is not None and value in duplicate_codes:
                holds.append(Hold(candidate.row, "generated_kode_not_unique", *candidate.target_key))
        collisions = fetch_kode_collisions(cur, set(generated_codes.values()))
        for candidate in selected_list:
            value = generated_codes.get(stage_row_key(candidate.row))
            if value is not None and value.lower() in collisions:
                holds.append(Hold(candidate.row, "generated_kode_collision", *candidate.target_key))

    already_held = {stage_row_key(item.row) for item in holds}
    for candidate in selected_list:
        if stage_row_key(candidate.row) in already_held:
            continue
        matching = existing.get(candidate.target_key, [])
        if len(matching) > 1:
            holds.append(Hold(candidate.row, "duplicate_existing_target_plafon", *candidate.target_key))
            continue
        label = label_for_term(candidate.term)
        if len(matching) == 0:
            if unsupported_required:
                holds.append(
                    Hold(
                        candidate.row,
                        "new_target_required_fields_without_policy",
                        *candidate.target_key,
                        detail={"columns": unsupported_required},
                    )
                )
                continue
            if "id_user" in insert_columns and candidate.id_user is None:
                holds.append(Hold(candidate.row, "new_target_missing_sales_user", *candidate.target_key))
                continue
            actions.append(
                PlannedAction(
                    candidate=candidate,
                    action="insert",
                    id_plafon=None,
                    limit_bon=candidate.limit_bon,
                    sisa_bon=candidate.limit_bon,
                    top=candidate.term,
                    tempo=candidate.term,
                    tempo_label=label,
                    generated_kode=generated_codes.get(stage_row_key(candidate.row)),
                    sisa_strategy="new_record_equals_limit",
                )
            )
            continue

        current = matching[0]
        old_limit = decimal_from_target(current.limit_bon)
        old_sisa = decimal_from_target(current.sisa_bon)
        if old_sisa is None:
            new_sisa = candidate.limit_bon
            sisa_strategy = "initialized_missing_sisa_to_limit"
        elif old_limit is None:
            new_sisa = old_sisa
            sisa_strategy = "preserved_sisa_missing_old_limit"
        else:
            new_sisa = old_sisa + (candidate.limit_bon - old_limit)
            sisa_strategy = "preserved_used_credit_by_limit_delta"
        if not decimal_fits_column(new_sisa, target_columns["sisa_bon"]):
            holds.append(Hold(candidate.row, "derived_sisa_bon_out_of_target_range", *candidate.target_key))
            continue
        changed = not (
            decimal_equal(current.limit_bon, candidate.limit_bon)
            and decimal_equal(current.sisa_bon, new_sisa)
            and target_integer_equal(current.top, candidate.term)
            and target_integer_equal(current.tempo, candidate.term)
            and current.tempo_label == label
        )
        actions.append(
            PlannedAction(
                candidate=candidate,
                action="update" if changed else "unchanged",
                id_plafon=current.id_plafon,
                limit_bon=candidate.limit_bon,
                sisa_bon=new_sisa,
                top=candidate.term,
                tempo=candidate.term,
                tempo_label=label,
                generated_kode=None,
                sisa_strategy=sisa_strategy,
            )
        )
    return actions, holds, insert_columns


def create_audit_tables(cur) -> None:
    registry = ident(REGISTRY_SCHEMA)
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {registry}.plafon_apply_run (
            batch_id text PRIMARY KEY,
            bdm_stage_schema text NOT NULL,
            tmp_stage_schema text NOT NULL,
            bdm_stage_run_id bigint NOT NULL,
            tmp_stage_run_id bigint NOT NULL,
            bdm_consistency_mode text NOT NULL,
            tmp_consistency_mode text NOT NULL,
            source_rows bigint NOT NULL,
            eligible_rows bigint NOT NULL,
            selected_rows bigint NOT NULL,
            inserted_rows bigint NOT NULL,
            updated_rows bigint NOT NULL,
            unchanged_rows bigint NOT NULL,
            held_rows bigint NOT NULL,
            ignored_source_fields jsonb NOT NULL,
            policy jsonb NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {registry}.plafon_apply_hold (
            batch_id text NOT NULL REFERENCES {registry}.plafon_apply_run(batch_id) ON DELETE CASCADE,
            source_system text NOT NULL,
            stage_schema text NOT NULL,
            source_staging_id bigint NOT NULL,
            source_row_hash text NOT NULL,
            hold_reason text NOT NULL,
            id_customer integer,
            id_principal integer,
            id_sales integer,
            detail jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            recorded_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (batch_id, source_system, source_staging_id, hold_reason)
        )
        """
    )
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {registry}.plafon_apply_selection (
            batch_id text NOT NULL REFERENCES {registry}.plafon_apply_run(batch_id) ON DELETE CASCADE,
            source_system text NOT NULL,
            stage_schema text NOT NULL,
            source_staging_id bigint NOT NULL,
            source_row_hash text NOT NULL,
            source_tgladd timestamp without time zone NOT NULL,
            id_customer integer NOT NULL,
            id_principal integer NOT NULL,
            id_sales integer NOT NULL,
            id_plafon bigint NOT NULL,
            action text NOT NULL CHECK (action IN ('insert', 'update', 'unchanged')),
            source_limit_bon numeric NOT NULL,
            source_term integer NOT NULL,
            resulting_sisa_bon numeric NOT NULL,
            sisa_strategy text NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (batch_id, source_system, source_staging_id)
        )
        """
    )


def write_holds(cur, batch_id: str, holds: Iterable[Hold]) -> None:
    values = [
        (
            batch_id,
            hold.row.source_system,
            hold.row.stage_schema,
            hold.row.staging_id,
            hold.row.source_row_hash,
            hold.reason,
            hold.id_customer,
            hold.id_principal,
            hold.id_sales,
            json.dumps(hold.detail or {}, ensure_ascii=False, sort_keys=True),
        )
        for hold in holds
    ]
    if not values:
        return
    execute_values(
        cur,
        f"""
        INSERT INTO {ident(REGISTRY_SCHEMA)}.plafon_apply_hold
            (batch_id, source_system, stage_schema, source_staging_id, source_row_hash,
             hold_reason, id_customer, id_principal, id_sales, detail)
        VALUES %s
        """,
        values,
        page_size=1000,
    )


def apply_updates(cur, actions: Iterable[PlannedAction]) -> set[int]:
    values = [
        (
            action.id_plafon,
            action.limit_bon,
            action.sisa_bon,
            action.top,
            action.tempo,
            action.tempo_label,
        )
        for action in actions
        if action.action == "update" and action.id_plafon is not None
    ]
    updated: set[int] = set()
    for batch in chunks(values, 1000):
        execute_values(
            cur,
            """
            WITH payload(id, limit_bon, sisa_bon, top, tempo, tempo_label) AS (VALUES %s),
            changed AS (
                UPDATE public.plafon p
                SET limit_bon = v.limit_bon,
                    sisa_bon = v.sisa_bon,
                    top = v.top,
                    tempo = v.tempo,
                    tempo_label = v.tempo_label
                FROM payload v
                WHERE p.id = v.id
                  AND ROW(p.limit_bon, p.sisa_bon, p.top, p.tempo, p.tempo_label)
                      IS DISTINCT FROM ROW(v.limit_bon, v.sisa_bon, v.top, v.tempo, v.tempo_label)
                RETURNING p.id
            )
            SELECT id FROM changed
            """,
            batch,
            page_size=len(batch),
        )
        updated.update(int(row[0]) for row in cur.fetchall())
    return updated


def insert_value_tuple(action: PlannedAction, columns: list[str], args: argparse.Namespace) -> tuple[Any, ...]:
    values: dict[str, Any] = {
        "id_customer": action.candidate.id_customer,
        "id_principal": action.candidate.id_principal,
        "id_sales": action.candidate.id_sales,
        "id_user": action.candidate.id_user,
        "limit_bon": action.limit_bon,
        "sisa_bon": action.sisa_bon,
        "kode": action.generated_kode,
        "id_tipe_harga": args.new_row_price_type_id,
        "top": action.top,
        "lock_order": args.new_row_lock_order,
        "tempo": action.tempo,
        "tempo_label": action.tempo_label,
    }
    return tuple(values[column] for column in columns)


def apply_inserts(
    cur, actions: Iterable[PlannedAction], columns: list[str], args: argparse.Namespace
) -> dict[tuple[int, int, int], int]:
    inserts = [action for action in actions if action.action == "insert"]
    if not inserts:
        return {}
    column_sql = ", ".join(ident(column) for column in columns)
    returned: dict[tuple[int, int, int], int] = {}
    for batch in chunks(inserts, 500):
        values = [insert_value_tuple(action, columns, args) for action in batch]
        execute_values(
            cur,
            f"""
            INSERT INTO public.plafon ({column_sql})
            VALUES %s
            RETURNING id, id_customer, id_principal, id_sales
            """,
            values,
            page_size=len(batch),
        )
        for target_id, id_customer, id_principal, id_sales in cur.fetchall():
            key = (int(id_customer), int(id_principal), int(id_sales))
            if key in returned:
                raise ValidationError("INSERT plafon mengembalikan triple target ganda.")
            returned[key] = int(target_id)
    if len(returned) != len(inserts):
        raise ValidationError("Jumlah plafon baru tidak sama dengan hasil INSERT.")
    return returned


def write_selections(
    cur,
    batch_id: str,
    actions: Iterable[PlannedAction],
    inserted_ids: dict[tuple[int, int, int], int],
) -> None:
    values: list[tuple[Any, ...]] = []
    for action in actions:
        target_id = (
            inserted_ids.get(action.candidate.target_key)
            if action.action == "insert"
            else action.id_plafon
        )
        if target_id is None:
            raise ValidationError("Audit selection tidak menemukan id_plafon hasil apply.")
        candidate = action.candidate
        values.append(
            (
                batch_id,
                candidate.row.source_system,
                candidate.row.stage_schema,
                candidate.row.staging_id,
                candidate.row.source_row_hash,
                candidate.source_added_at,
                candidate.id_customer,
                candidate.id_principal,
                candidate.id_sales,
                target_id,
                action.action,
                candidate.limit_bon,
                candidate.term,
                action.sisa_bon,
                action.sisa_strategy,
            )
        )
    if not values:
        return
    execute_values(
        cur,
        f"""
        INSERT INTO {ident(REGISTRY_SCHEMA)}.plafon_apply_selection
            (batch_id, source_system, stage_schema, source_staging_id, source_row_hash,
             source_tgladd, id_customer, id_principal, id_sales, id_plafon,
             action, source_limit_bon, source_term, resulting_sisa_bon, sisa_strategy)
        VALUES %s
        """,
        values,
        page_size=1000,
    )


def plan_summary(
    stage_metadata: dict[str, StageMetadata],
    source_rows: dict[str, list[StageRow]],
    eligible: list[Candidate],
    actions: list[PlannedAction],
    holds: list[Hold],
    notices: Counter[str],
    args: argparse.Namespace,
    insert_columns: list[str],
) -> dict[str, Any]:
    action_counts = Counter(action.action for action in actions)
    hold_counts = Counter(hold.reason for hold in holds)
    final_stage, final_stage_reason = final_stage_gate(stage_metadata)
    return {
        "batch_id": args.batch_id,
        "source_rows": sum(len(rows) for rows in source_rows.values()),
        "eligible_rows": len(eligible),
        "selected_rows": len(actions),
        "planned_insert_rows": action_counts["insert"],
        "planned_update_rows": action_counts["update"],
        "planned_unchanged_rows": action_counts["unchanged"],
        "held_rows": len(holds),
        "held_by_reason": dict(sorted(hold_counts.items())),
        "ignored_source_fields": dict(sorted(notices.items())),
        "new_row_insert_columns": insert_columns,
        "new_row_price_type_policy": args.new_row_price_type_id,
        "new_row_lock_order_policy": args.new_row_lock_order,
        "stage": {
            source_system: {
                "schema": metadata.schema,
                "run_id": metadata.run_id,
                "status": metadata.status,
                "consistency_mode": metadata.consistency_mode,
                "is_preview": metadata.is_preview,
                "maintenance_window_id": metadata.maintenance_window_id,
                "maintenance_freeze_attested": metadata.maintenance_freeze_attested,
                "maintenance_freeze_confirmed_at": iso_or_none(metadata.maintenance_freeze_confirmed_at),
                "source_transaction_isolation": metadata.source_transaction_isolation,
                "source_lock_timeout_ms": metadata.source_lock_timeout_ms,
                "rows": len(source_rows[source_system]),
            }
            for source_system, metadata in stage_metadata.items()
        },
        "apply_allowed": final_stage,
        "apply_allowed_reason": final_stage_reason,
        "will_apply": bool(args.apply),
        "update_sisa_bon_policy": "preserve_used_credit_by_limit_delta",
        "unmapped_source_fields": [
            "lock1",
            "useradd",
            "disc1",
            "lockplan",
            "hari",
            "week",
            "kategori",
            "keterangan",
            "autolockplan",
            "autolockjt",
            "timelockplan",
            "timelockjt",
        ],
    }


def build_plan(cur, args: argparse.Namespace, *, lock_target: bool) -> tuple[
    dict[str, Any],
    dict[str, StageMetadata],
    list[PlannedAction],
    list[Hold],
    list[str],
]:
    stage_columns = fetch_stage_column_names(cur, [args.bdm_schema, args.tmp_schema])
    metadata = {
        "bdm_solo_dist": latest_stage_metadata(cur, args.bdm_schema, "bdm_solo_dist", stage_columns),
        "tmp_solo_dist": latest_stage_metadata(cur, args.tmp_schema, "tmp_solo_dist", stage_columns),
    }
    for source_metadata in metadata.values():
        validate_stage_rows(cur, source_metadata)
        target_company, target_branch = fetch_source_context(cur, source_metadata.source_system)
        if (
            target_company != source_metadata.target_company_id
            or target_branch != source_metadata.target_branch_id
        ):
            raise ValidationError(
                f"Scope {source_metadata.schema} berbeda dari registry source_context {source_metadata.source_system}."
            )
    if lock_target:
        stage_is_final, finality_reason = final_stage_gate(metadata)
        if not stage_is_final:
            raise ValidationError(finality_reason)
    source_rows = {source: fetch_stage_rows(cur, item) for source, item in metadata.items()}
    mappings = {
        source: {
            "customer": fetch_mapping_table(cur, source, "customer_map", ("source_customer_code_norm",), "id_customer"),
            "principal": fetch_mapping_table(cur, source, "principal_map", ("source_principal_code_norm",), "id_principal"),
            "sales": fetch_mapping_table(
                cur,
                source,
                "sales_map",
                ("source_principal_code_norm", "source_sales_code_norm"),
                "id_sales",
            ),
        }
        for source in SOURCE_SYSTEMS
    }
    if lock_target:
        # Acquire this before the first public-table read.  The lock blocks only
        # writers to plafon during the atomic PostgreSQL apply and prevents an
        # absence check from racing a concurrent new plafond insertion.
        cur.execute("LOCK TABLE public.plafon IN SHARE ROW EXCLUSIVE MODE")
    target_columns = fetch_target_columns(cur)
    customer_ids = {
        item.target_id
        for source in SOURCE_SYSTEMS
        for item in mappings[source]["customer"].values()
    }
    principal_ids = {
        item.target_id
        for source in SOURCE_SYSTEMS
        for item in mappings[source]["principal"].values()
    }
    sales_ids = {
        item.target_id
        for source in SOURCE_SYSTEMS
        for item in mappings[source]["sales"].values()
    }
    customers = fetch_customer_targets(cur, customer_ids)
    principals = fetch_principal_targets(cur, principal_ids)
    sales = fetch_sales_targets(cur, sales_ids)
    eligible: list[Candidate] = []
    holds: list[Hold] = []
    notices: Counter[str] = Counter()
    for source in SOURCE_SYSTEMS:
        source_metadata = metadata[source]
        source_candidates, source_holds, source_notices = resolve_candidates(
            source_rows[source],
            source,
            (source_metadata.target_company_id, source_metadata.target_branch_id),
            mappings[source]["customer"],
            mappings[source]["principal"],
            mappings[source]["sales"],
            customers,
            principals,
            sales,
            target_columns,
        )
        eligible.extend(source_candidates)
        holds.extend(source_holds)
        notices.update(source_notices)
    selected, selection_holds = select_newest_candidates(eligible)
    holds.extend(selection_holds)
    existing = fetch_existing_plafon(cur, (item.target_key for item in selected), lock_rows=lock_target)
    actions, action_holds, insert_columns = build_actions(cur, selected, existing, target_columns, args)
    holds.extend(action_holds)
    # A selected candidate turned into an action hold must not be reported as
    # selected.  It is still present in ``eligible_rows`` because mapping and
    # source validation were successful.
    summary = plan_summary(metadata, source_rows, eligible, actions, holds, notices, args, insert_columns)
    return summary, metadata, actions, holds, insert_columns


def ensure_applyable(summary: dict[str, Any]) -> None:
    if not summary["apply_allowed"]:
        raise ValidationError(str(summary["apply_allowed_reason"]))


def apply_plan(
    cur,
    args: argparse.Namespace,
    summary: dict[str, Any],
    metadata: dict[str, StageMetadata],
    actions: list[PlannedAction],
    holds: list[Hold],
    insert_columns: list[str],
) -> dict[str, Any]:
    ensure_applyable(summary)
    create_audit_tables(cur)
    cur.execute(
        f"SELECT 1 FROM {ident(REGISTRY_SCHEMA)}.plafon_apply_run WHERE batch_id = %s",
        (args.batch_id,),
    )
    if cur.fetchone() is not None:
        raise ValidationError(f"Batch {args.batch_id} sudah pernah dijalankan.")
    updated_ids = apply_updates(cur, actions)
    inserted_ids = apply_inserts(cur, actions, insert_columns, args)
    planned_updates = {action.id_plafon for action in actions if action.action == "update" and action.id_plafon is not None}
    if updated_ids != planned_updates:
        raise ValidationError("Jumlah/id plafon ter-update tidak sama dengan rencana; batch dibatalkan.")
    policy = {
        "source_order": "newest_parseable_tgladd_only",
        "equal_newest_conflict": "hold",
        "existing_target": "update_limit_term_and_preserve_used_credit",
        "missing_target": "insert_only_when_required_fields_are_safe",
        "source_field_map": {"plafon": "limit_bon", "term": ["top", "tempo", "tempo_label"]},
        "unmapped_lock1": True,
        "new_row_price_type_id": args.new_row_price_type_id,
        "new_row_lock_order": args.new_row_lock_order,
        "stage_consistency_gate": summary["apply_allowed_reason"],
        "stage_consistency": summary["stage"],
    }
    action_counts = Counter(action.action for action in actions)
    cur.execute(
        f"""
        INSERT INTO {ident(REGISTRY_SCHEMA)}.plafon_apply_run
            (batch_id, bdm_stage_schema, tmp_stage_schema, bdm_stage_run_id, tmp_stage_run_id,
             bdm_consistency_mode, tmp_consistency_mode, source_rows, eligible_rows,
             selected_rows, inserted_rows, updated_rows, unchanged_rows, held_rows,
             ignored_source_fields, policy)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s::jsonb, %s::jsonb)
        """,
        (
            args.batch_id,
            metadata["bdm_solo_dist"].schema,
            metadata["tmp_solo_dist"].schema,
            metadata["bdm_solo_dist"].run_id,
            metadata["tmp_solo_dist"].run_id,
            metadata["bdm_solo_dist"].consistency_mode,
            metadata["tmp_solo_dist"].consistency_mode,
            summary["source_rows"],
            summary["eligible_rows"],
            len(actions),
            action_counts["insert"],
            action_counts["update"],
            action_counts["unchanged"],
            len(holds),
            json.dumps(summary["ignored_source_fields"], ensure_ascii=False, sort_keys=True),
            json.dumps(policy, ensure_ascii=False, sort_keys=True),
        ),
    )
    write_holds(cur, args.batch_id, holds)
    write_selections(cur, args.batch_id, actions, inserted_ids)
    summary = dict(summary)
    summary.update(
        {
            "actual_insert_rows": action_counts["insert"],
            "actual_update_rows": action_counts["update"],
            "actual_unchanged_rows": action_counts["unchanged"],
            "audit_written": True,
        }
    )
    return summary


def main() -> int:
    args = parse_args()
    for schema in (args.bdm_schema, args.tmp_schema):
        ident(schema)
    if args.bdm_schema == args.tmp_schema:
        raise SystemExit("--bdm-schema dan --tmp-schema harus berbeda.")
    if not BATCH_RE.fullmatch(args.batch_id):
        raise SystemExit("--batch-id hanya boleh berisi huruf kecil, angka, titik, garis bawah, atau strip.")
    if args.statement_timeout_seconds <= 0:
        raise SystemExit("--statement-timeout-seconds harus lebih besar dari nol.")
    if args.new_row_price_type_id is not None and args.new_row_price_type_id <= 0:
        raise SystemExit("--new-row-price-type-id harus lebih besar dari nol.")
    try:
        connection = psycopg2.connect(
            dbname=args.pg_database,
            user=args.pg_user,
            host=args.pg_host,
            port=args.pg_port,
        )
    except psycopg2.Error as exc:
        print(f"Apply Plafon tidak dapat terhubung ke PostgreSQL: {exc}", file=sys.stderr)
        return 2
    try:
        if not args.apply:
            connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cur:
            mode = "REPEATABLE READ" if args.apply else "REPEATABLE READ, READ ONLY"
            cur.execute(f"SET TRANSACTION ISOLATION LEVEL {mode}")
            cur.execute("SET LOCAL lock_timeout = '10s'")
            cur.execute(f"SET LOCAL statement_timeout = '{args.statement_timeout_seconds}s'")
            # In apply mode, build_plan locks public.plafon before the first
            # public-table read.  Dry-runs stay read-only and take no table lock.
            summary, metadata, actions, holds, insert_columns = build_plan(
                cur, args, lock_target=bool(args.apply)
            )
            if not args.apply:
                print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
                connection.rollback()
                return 0
            summary = apply_plan(cur, args, summary, metadata, actions, holds, insert_columns)
        connection.commit()
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0
    except (ValidationError, psycopg2.Error) as exc:
        connection.rollback()
        print(f"Apply Plafon dibatalkan: {exc}", file=sys.stderr)
        return 2
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
