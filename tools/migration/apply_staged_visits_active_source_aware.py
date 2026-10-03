#!/usr/bin/env python3
"""Safely import BDM/TMP ``KunjunganSales`` as active ERP visits.

This tool exists because the old one-source legacy script keyed a visit only
by its legacy ID and selected target master data using incidental public-table
matches.  That is unsafe for BDM and TMP: both sources can reuse the same
codes and IDs.  This implementation always keeps the source system in every
identity and uses only approved entries in
``migration_bdm_tmp_202608`` for customer, principal, and sales resolution.

The importer intentionally covers *visits only*.  A visit has a sufficiently
defined active representation in the ERP (`sales_kunjungan` plus
`sales_kunjungan_detail`) and does not create stock, receivable, payable, or
journal movements.  It does not manufacture a call-plan schedule:
``id_plafon_jadwal`` remains NULL, so the record is an actual visit rather
than a fictitious scheduled one.

Purchase records are deliberately excluded.  ``DPembelian`` carries raw
``unit``, ``perunit``, ``satuan``, and ``jumlah`` values without an
unambiguous UOM code/meaning.  A previous legacy mapper chose a nearby target
UOM and must not be used for this BDM/TMP migration.  The read-only
``reconcile_visit_purchase_staging.py`` report now lists the exact prerequisite
evidence before an active purchase/stock import can be implemented.

Safety properties:

* Dry-run is the default and ends with ROLLBACK.  It writes nothing.
* ``--apply`` requires an explicit confirmation, a final consistent BDM/TMP
  stage pair (SQL Server SNAPSHOT or one attested maintenance write-freeze),
  an externally confirmed target-ERP write freeze, and writes source
  maps/actions/holds atomically in the mapping registry.
* Existing target visits in the source date range block new inserts until a
  source-qualified 1:1 adoption manifest proves whether they are legacy
  source records or unrelated ERP rows. Timestamp equality alone is not proof.
* Blank, duplicate, or changed legacy visit IDs are held.  A re-run with the
  exact same source payload is idempotent; it is recorded as unchanged and
  never creates a second public visit.
* A row is eligible only when its customer, principal, sales, user, and
  exactly one matching `public.plafon` remain scope-valid at apply time.
* Checkout strings are interpreted only from a narrow Boolean vocabulary.
  A completed visit also requires a valid checkout timestamp.  Unknown values
  are held rather than silently becoming an open or completed visit.
* Latitude/longitude are retained in source-aware registry metadata only;
  the current ERP visit schema has no verified public target columns for them.
  The tool never invents a location field or overwrites an ERP location.

The program never connects to SQL Server and never writes to SQL Server.
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
from datetime import date, datetime, time, timezone
from typing import Any, Iterable


REGISTRY_SCHEMA = "migration_bdm_tmp_202608"
SOURCE_SYSTEMS = ("bdm_solo_dist", "tmp_solo_dist")
DEFAULT_BATCH_ID = "active_visit_source_aware_final_20260830"
SNAPSHOT_CONSISTENCY_MODE = "snapshot"
MAINTENANCE_FREEZE_CONSISTENCY_MODE = "maintenance_freeze_serializable"
CONFIRM_ACTIVE_VISIT_IMPORT = "I_CONFIRM_ACTIVE_VISIT_IMPORT"
CONFIRM_TARGET_ERP_WRITE_FREEZE = "I_CONFIRM_TARGET_ERP_WRITE_FREEZE"
IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
BATCH_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,119}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}"
    r"(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?$"
)
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
    "tanggal",
    "kodecustomer",
    "kodesales",
    "kodeprinciple",
    "checkout",
}
AUDIT_TABLES = (
    "active_visit_import_run",
    "active_visit_document_map",
    "active_visit_import_hold",
    "active_visit_import_action",
)


class ValidationError(RuntimeError):
    """Raised when a staging row or target schema cannot be used safely."""


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
    source_visit_id_raw: str | None
    tanggal_raw: str | None
    kodecustomer_raw: str | None
    kodesales_raw: str | None
    kodeprinciple_raw: str | None
    checkout_raw: str | None
    tanggalcheckout_raw: str | None
    latitude_raw: str | None
    longitude_raw: str | None


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
    id_user: int | None
    user_company_id: int | None
    user_branch_id: int | None


@dataclass(frozen=True)
class TargetPlafon:
    id_plafon: int
    id_customer: int
    id_principal: int
    id_sales: int
    id_user: int | None


@dataclass(frozen=True)
class TargetColumn:
    name: str
    data_type: str
    udt_name: str
    nullable: bool
    column_default: str | None
    is_identity: bool
    is_generated: bool

    @property
    def needs_explicit_value(self) -> bool:
        return (
            not self.nullable
            and self.column_default is None
            and not self.is_identity
            and not self.is_generated
        )


@dataclass(frozen=True)
class VisitCandidate:
    row: StageRow
    source_visit_id: str
    source_visit_id_norm: str
    visit_at: datetime
    checkout_at: datetime | None
    visit_status: int
    id_customer: int
    id_principal: int
    id_sales: int
    id_user: int
    id_plafon: int

    @property
    def key(self) -> tuple[str, str]:
        return (self.row.source_system, self.source_visit_id_norm)

    @property
    def expected_visit_payload(self) -> tuple[Any, ...]:
        return (
            self.visit_at.date(),
            self.visit_at.time(),
            self.checkout_at.time() if self.checkout_at is not None else None,
            self.visit_status,
            self.id_plafon,
            self.id_user,
        )

    @property
    def expected_detail_payload(self) -> tuple[Any, ...]:
        return (
            self.id_plafon,
            self.id_principal,
            self.id_customer,
            self.id_user,
            0,
            0,
            0,
            1,
        )


@dataclass(frozen=True)
class ExistingMap:
    source_system: str
    source_visit_id_norm: str
    source_row_hash: str
    id_sales_kunjungan: int
    id_sales_kunjungan_detail: int


@dataclass(frozen=True)
class ExistingTargetPayload:
    id_sales_kunjungan: int
    id_sales_kunjungan_detail: int
    visit_payload: tuple[Any, ...] | None
    detail_payload: tuple[Any, ...] | None


@dataclass(frozen=True)
class Hold:
    row: StageRow
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlannedInsert:
    candidate: VisitCandidate


@dataclass(frozen=True)
class PlannedUnchanged:
    candidate: VisitCandidate
    existing: ExistingMap


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
    value = str(value).strip()
    return value or None


def norm(value: Any) -> str | None:
    value = clean(value)
    return value.lower() if value else None


def json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [json_safe(item) for item in value]
    return value


def clean_name(value: str) -> str:
    value = re.sub(r"[^0-9a-zA-Z_]+", "_", str(value or "").strip())
    value = re.sub(r"_+", "_", value).strip("_").lower()
    if not value:
        value = "col"
    return f"c_{value}" if value[0].isdigit() else value


def unique_clean_columns(raw_columns: Iterable[str]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for raw in raw_columns:
        base = clean_name(raw)
        seen[base] = seen.get(base, 0) + 1
        result.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    return result


def parse_iso_datetime(value: Any, *, reason_prefix: str) -> tuple[datetime | None, str | None]:
    """Accept only ISO date/timestamp source values, never locale guesses."""

    text = clean(value)
    if text is None:
        return None, f"blank_{reason_prefix}"
    try:
        if DATE_RE.fullmatch(text):
            return datetime.combine(date.fromisoformat(text), time.min), None
        if DATETIME_RE.fullmatch(text):
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                # Explicit offsets are converted only to make ordering stable.
                # Legacy naïve SQL Server values retain their local date/time.
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed, None
    except ValueError:
        pass
    return None, f"invalid_{reason_prefix}_format"


def parse_checkout(value: Any) -> tuple[bool | None, str | None]:
    text = clean(value)
    if text is None:
        return False, None
    normalized = text.lower()
    if normalized in {"true", "1", "t", "yes", "y"}:
        return True, None
    if normalized in {"false", "0", "f", "no", "n"}:
        return False, None
    return None, "unknown_checkout_value"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bdm-schema", help="Schema staging final BDM Solo.")
    parser.add_argument("--tmp-schema", help="Schema staging final TMP Solo.")
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID, help="Kode batch audit.")
    parser.add_argument("--apply", action="store_true", help="Tulis kunjungan aktif secara atomik.")
    parser.add_argument(
        "--confirm-active-visit-import",
        choices=(CONFIRM_ACTIVE_VISIT_IMPORT,),
        metavar=CONFIRM_ACTIVE_VISIT_IMPORT,
        help="Konfirmasi eksplisit untuk membuat transaksi kunjungan aktif.",
    )
    parser.add_argument(
        "--confirm-target-erp-write-freeze",
        choices=(CONFIRM_TARGET_ERP_WRITE_FREEZE,),
        metavar=CONFIRM_TARGET_ERP_WRITE_FREEZE,
        help="Wajib saat apply: operator telah membekukan penulisan ERP target selama transaksi migrasi.",
    )
    parser.add_argument("--pg-database", default=os.getenv("MIGRATION_PG_DATABASE", "budimas_dev"))
    parser.add_argument("--pg-user", default=os.getenv("MIGRATION_PG_USER", "postgres"))
    parser.add_argument("--pg-host", default=os.getenv("MIGRATION_PG_HOST", "127.0.0.1"))
    parser.add_argument("--pg-port", type=int, default=int(os.getenv("MIGRATION_PG_PORT", "5432")))
    parser.add_argument("--statement-timeout-seconds", type=int, default=300)
    parser.add_argument("--self-test", action="store_true", help="Test parser/gate tanpa koneksi database.")
    return parser.parse_args()


def ensure_cli_args(args: argparse.Namespace) -> None:
    if not args.bdm_schema or not args.tmp_schema:
        raise ValidationError("--bdm-schema dan --tmp-schema wajib diisi.")
    ident(args.bdm_schema)
    ident(args.tmp_schema)
    if args.bdm_schema == args.tmp_schema:
        raise ValidationError("Schema BDM dan TMP wajib terpisah.")
    if not args.bdm_schema.startswith("legacy_") or not args.tmp_schema.startswith("legacy_"):
        raise ValidationError("Schema staging wajib diawali legacy_.")
    if not BATCH_RE.fullmatch(str(args.batch_id)):
        raise ValidationError("--batch-id tidak aman; gunakan huruf kecil, angka, titik, minus, atau underscore.")
    if args.pg_port <= 0 or args.pg_port > 65535:
        raise ValidationError("--pg-port harus 1 sampai 65535.")
    if args.statement_timeout_seconds <= 0 or args.statement_timeout_seconds > 3600:
        raise ValidationError("--statement-timeout-seconds harus 1 sampai 3600.")
    if args.apply and args.confirm_active_visit_import != CONFIRM_ACTIVE_VISIT_IMPORT:
        raise ValidationError("--apply wajib disertai --confirm-active-visit-import.")
    if args.apply and args.confirm_target_erp_write_freeze != CONFIRM_TARGET_ERP_WRITE_FREEZE:
        raise ValidationError("--apply wajib disertai --confirm-target-erp-write-freeze.")


def load_stage_columns(cur, schemas: list[str]) -> dict[tuple[str, str], set[str]]:
    cur.execute(
        """
        SELECT table_schema, table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = ANY(%s)
          AND table_name IN ('__stage_run', '__stage_manifest', 'kunjungansales')
        """,
        (schemas,),
    )
    result: dict[tuple[str, str], set[str]] = {}
    for schema, table, column in cur.fetchall():
        result.setdefault((str(schema), str(table)), set()).add(str(column))
    return result


def stage_metadata(
    cur,
    schema: str,
    expected_source: str,
    stage_columns: dict[tuple[str, str], set[str]],
) -> StageMetadata:
    run_columns = stage_columns.get((schema, "__stage_run"), set())
    manifest_columns = stage_columns.get((schema, "__stage_manifest"), set())
    visit_columns = stage_columns.get((schema, "kunjungansales"), set())
    missing_run = {
        "id", "source_system", "status", "consistency_mode", "target_company_id", "target_branch_id"
    } - run_columns
    missing_manifest = {
        "legacy_table", "module", "source_columns", "source_row_count", "staged_row_count", "status"
    } - manifest_columns
    missing_fixed = STAGE_FIXED_COLUMNS - visit_columns
    if missing_run or missing_manifest or missing_fixed:
        parts: list[str] = []
        if missing_run:
            parts.append("__stage_run=" + ",".join(sorted(missing_run)))
        if missing_manifest:
            parts.append("__stage_manifest=" + ",".join(sorted(missing_manifest)))
        if missing_fixed:
            parts.append("kunjungansales=" + ",".join(sorted(missing_fixed)))
        raise ValidationError(f"Staging {schema} tidak lengkap: {'; '.join(parts)}.")

    preview_expr = "is_preview" if "is_preview" in run_columns else "(consistency_mode <> 'snapshot')"
    maintenance_window_expr = "maintenance_window_id" if "maintenance_window_id" in run_columns else "NULL::text"
    maintenance_attested_expr = "maintenance_freeze_attested" if "maintenance_freeze_attested" in run_columns else "FALSE"
    maintenance_confirmed_expr = (
        "maintenance_freeze_confirmed_at" if "maintenance_freeze_confirmed_at" in run_columns else "NULL::timestamptz"
    )
    source_isolation_expr = "source_transaction_isolation" if "source_transaction_isolation" in run_columns else "NULL::text"
    source_lock_timeout_expr = "source_lock_timeout_ms" if "source_lock_timeout_ms" in run_columns else "NULL::integer"
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
        WHERE lower(btrim(legacy_table)) = 'kunjungansales'
        """
    )
    manifests = cur.fetchall()
    if len(manifests) != 1:
        raise ValidationError(f"{schema} harus memiliki tepat satu manifest KunjunganSales.")
    manifest_status, manifest_module, raw_columns, source_count, staged_count = manifests[0]
    if str(manifest_status) != "done" or str(manifest_module) != "visits":
        raise ValidationError(
            f"Manifest KunjunganSales {schema} tidak valid (status={manifest_status!r}, module={manifest_module!r})."
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
            f"Staging {schema}.kunjungansales tidak memiliki kolom sumber wajib: {', '.join(sorted(missing_source))}."
        )
    missing_staged = set(source_columns) - visit_columns
    if missing_staged:
        raise ValidationError(
            f"Tabel {schema}.kunjungansales tidak memuat kolom manifest: {', '.join(sorted(missing_staged))}."
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
            COUNT(*) FILTER (WHERE lower(btrim(legacy_table)) <> 'kunjungansales')::bigint,
            COUNT(*) FILTER (WHERE source_row_hash IS NULL OR btrim(source_row_hash) = '')::bigint
        FROM {qtable(metadata.schema, 'kunjungansales')}
        """,
        (metadata.source_system, metadata.target_company_id, metadata.target_branch_id),
    )
    actual, bad_source, bad_scope, bad_table, bad_hash = (int(value) for value in cur.fetchone())
    if actual != metadata.source_rows:
        raise ValidationError(
            f"{metadata.schema}.kunjungansales berisi {actual}, bukan {metadata.source_rows} menurut manifest."
        )
    invalid = {
        "wrong_source_system": bad_source,
        "wrong_target_scope": bad_scope,
        "wrong_legacy_table": bad_table,
        "blank_source_row_hash": bad_hash,
    }
    if any(invalid.values()):
        raise ValidationError(
            f"Provenance {metadata.schema}.kunjungansales tidak valid: "
            + ", ".join(f"{key}={value}" for key, value in invalid.items() if value)
        )


def fetch_stage_rows(cur, metadata: StageMetadata) -> list[StageRow]:
    def optional(name: str) -> str:
        return f"v.{ident(name)}" if name in metadata.source_columns else "NULL::text"

    cur.execute(
        f"""
        SELECT v.staging_id, v.source_row_hash, v.id, v.tanggal,
               v.kodecustomer, v.kodesales, v.kodeprinciple, v.checkout,
               {optional('tanggalcheckout')}, {optional('latitude')}, {optional('longitude')}
        FROM {qtable(metadata.schema, 'kunjungansales')} v
        WHERE v.source_system = %s
        ORDER BY v.staging_id
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
            source_visit_id_raw=clean(record[2]),
            tanggal_raw=clean(record[3]),
            kodecustomer_raw=clean(record[4]),
            kodesales_raw=clean(record[5]),
            kodeprinciple_raw=clean(record[6]),
            checkout_raw=clean(record[7]),
            tanggalcheckout_raw=clean(record[8]),
            latitude_raw=clean(record[9]),
            longitude_raw=clean(record[10]),
        )
        for record in cur.fetchall()
    ]
    if len(rows) != metadata.source_rows:
        raise ValidationError(f"Jumlah row {metadata.schema}.kunjungansales berubah saat dibaca.")
    return rows


def final_stage_gate(metadata: dict[str, StageMetadata]) -> tuple[bool, str]:
    values = [metadata.get(source) for source in SOURCE_SYSTEMS]
    if any(item is None for item in values):
        return False, "Metadata BDM/TMP tidak lengkap."
    stages = [item for item in values if item is not None]
    if any(item.status != "completed" or item.is_preview for item in stages):
        return False, "Kedua staging wajib completed dan bukan preview."
    if all(item.consistency_mode == SNAPSHOT_CONSISTENCY_MODE for item in stages):
        return True, "Kedua staging memakai SQL Server SNAPSHOT."
    if not all(item.consistency_mode == MAINTENANCE_FREEZE_CONSISTENCY_MODE for item in stages):
        return False, "Staging harus sama-sama SNAPSHOT atau satu maintenance write-freeze terattestasi."
    window_ids = {item.maintenance_window_id for item in stages if item.maintenance_window_id}
    if len(window_ids) != 1 or any(not item.maintenance_window_id for item in stages):
        return False, "Staging maintenance wajib memiliki maintenance_window_id yang sama."
    if any(
        not item.maintenance_freeze_attested
        or item.maintenance_freeze_confirmed_at is None
        or (item.source_transaction_isolation or "").lower() != "serializable"
        or item.source_lock_timeout_ms is None
        or item.source_lock_timeout_ms <= 0
        for item in stages
    ):
        return False, "Bukti freeze/SERIALIZABLE staging tidak lengkap."
    return True, f"Kedua staging memakai maintenance write-freeze {next(iter(window_ids))}."


def assert_final_staging(metadata: dict[str, StageMetadata]) -> None:
    allowed, reason = final_stage_gate(metadata)
    if not allowed:
        raise ValidationError("--apply ditolak: " + reason)


def load_mapping(
    cur,
    source_system: str,
    table: str,
    key_columns: tuple[str, ...],
    target_column: str,
) -> dict[tuple[str, ...], MappingValue]:
    keys = ", ".join(ident(column) for column in key_columns)
    cur.execute(
        f"""
        SELECT {keys}, {ident(target_column)}, mapping_method
        FROM {qtable(REGISTRY_SCHEMA, table)}
        WHERE source_system = %s
        """,
        (source_system,),
    )
    result: dict[tuple[str, ...], MappingValue] = {}
    for record in cur.fetchall():
        key = tuple(str(value) for value in record[: len(key_columns)])
        if key in result:
            raise ValidationError(f"Registry {table} {source_system} memiliki key duplikat.")
        result[key] = MappingValue(int(record[len(key_columns)]), str(record[len(key_columns) + 1]))
    return result


def load_source_context(cur, source_system: str) -> tuple[int, int]:
    cur.execute(
        f"""
        SELECT target_company_id, target_branch_id
        FROM {qtable(REGISTRY_SCHEMA, 'source_context')}
        WHERE source_system = %s
        """,
        (source_system,),
    )
    rows = cur.fetchall()
    if len(rows) != 1:
        raise ValidationError(f"source_context {source_system} harus tepat satu baris.")
    return int(rows[0][0]), int(rows[0][1])


def fetch_customer_targets(cur, ids: set[int]) -> dict[int, TargetCustomer]:
    if not ids:
        return {}
    cur.execute("SELECT id, id_cabang FROM public.customer WHERE id = ANY(%s)", (sorted(ids),))
    return {
        int(row[0]): TargetCustomer(int(row[0]), int(row[1]) if row[1] is not None else None)
        for row in cur.fetchall()
    }


def fetch_principal_targets(cur, ids: set[int]) -> dict[int, TargetPrincipal]:
    if not ids:
        return {}
    cur.execute("SELECT id, id_perusahaan FROM public.principal WHERE id = ANY(%s)", (sorted(ids),))
    return {
        int(row[0]): TargetPrincipal(int(row[0]), int(row[1]) if row[1] is not None else None)
        for row in cur.fetchall()
    }


def fetch_sales_targets(cur, ids: set[int]) -> dict[int, TargetSales]:
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
        int(row[0]): TargetSales(
            id_sales=int(row[0]),
            id_principal=int(row[1]) if row[1] is not None else None,
            id_user=int(row[2]) if row[2] is not None else None,
            user_company_id=int(row[3]) if row[3] is not None else None,
            user_branch_id=int(row[4]) if row[4] is not None else None,
        )
        for row in cur.fetchall()
    }


def chunks(values: list[Any], size: int = 800) -> Iterable[list[Any]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def fetch_plafon_targets(cur, triples: set[tuple[int, int, int]], *, lock_rows: bool) -> dict[tuple[int, int, int], list[TargetPlafon]]:
    """Load only exact mapped triples and preserve duplicate targets for holds."""

    if not triples:
        return {}
    try:
        from psycopg2.extras import execute_values  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - runtime dependency
        raise ValidationError("psycopg2 diperlukan untuk membaca PostgreSQL.") from exc
    result: dict[tuple[int, int, int], list[TargetPlafon]] = defaultdict(list)
    # A visit apply locks only the exact Plafon rows it is going to reference.
    # This protects their owner/scope while the plan is rebuilt, without taking
    # a table-wide lock that would block normal ERP visit inserts.
    suffix = " FOR SHARE OF p" if lock_rows else ""
    for batch in chunks(sorted(triples)):
        rows = execute_values(
            cur,
            f"""
            WITH requested(id_customer, id_principal, id_sales) AS (VALUES %s)
            SELECT p.id, p.id_customer, p.id_principal, p.id_sales, p.id_user
            FROM public.plafon p
            JOIN requested r
              ON r.id_customer = p.id_customer
             AND r.id_principal = p.id_principal
             AND r.id_sales = p.id_sales
            {suffix}
            """,
            batch,
            page_size=len(batch),
            fetch=True,
        )
        for row in rows:
            target = TargetPlafon(
                id_plafon=int(row[0]),
                id_customer=int(row[1]),
                id_principal=int(row[2]),
                id_sales=int(row[3]),
                id_user=int(row[4]) if row[4] is not None else None,
            )
            result[(target.id_customer, target.id_principal, target.id_sales)].append(target)
    return result


def load_target_columns(cur, table: str) -> dict[str, TargetColumn]:
    cur.execute(
        """
        SELECT column_name, data_type, udt_name, is_nullable, column_default, is_identity, is_generated
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table,),
    )
    result = {
        str(row[0]): TargetColumn(
            name=str(row[0]),
            data_type=str(row[1]),
            udt_name=str(row[2]),
            nullable=str(row[3]) == "YES",
            column_default=str(row[4]) if row[4] is not None else None,
            is_identity=str(row[5]) == "YES",
            is_generated=str(row[6]) != "NEVER",
        )
        for row in cur.fetchall()
    }
    if not result:
        raise ValidationError(f"Tabel target public.{table} tidak ditemukan.")
    return result


def assert_id_column_auto(columns: dict[str, TargetColumn], table: str) -> str:
    column = columns.get("id")
    if column is None:
        raise ValidationError(f"public.{table} tidak memiliki id.")
    if column.udt_name not in {"int4", "int8"}:
        raise ValidationError(f"public.{table}.id bertipe {column.data_type!r}; hanya int4/int8 didukung aman.")
    if column.column_default is None and not column.is_identity:
        raise ValidationError(f"public.{table}.id tidak memiliki default/identity; importer tidak membuat ID manual.")
    return "integer" if column.udt_name == "int4" else "bigint"


def assert_integer_column(columns: dict[str, TargetColumn], table: str, name: str) -> None:
    column = columns.get(name)
    if column is None or column.udt_name not in {"int2", "int4", "int8"}:
        raise ValidationError(f"public.{table}.{name} wajib ada dan bertipe integer.")


def assert_date_column(columns: dict[str, TargetColumn], table: str, name: str) -> None:
    column = columns.get(name)
    if column is None or column.data_type != "date":
        raise ValidationError(f"public.{table}.{name} wajib bertipe date.")


def assert_time_column(columns: dict[str, TargetColumn], table: str, name: str) -> None:
    column = columns.get(name)
    if column is None or column.data_type not in {"time without time zone", "time with time zone"}:
        raise ValidationError(f"public.{table}.{name} wajib bertipe time.")


def validate_target_schema(cur) -> tuple[dict[str, TargetColumn], dict[str, TargetColumn], str, str]:
    visits = load_target_columns(cur, "sales_kunjungan")
    details = load_target_columns(cur, "sales_kunjungan_detail")
    visit_id_type = assert_id_column_auto(visits, "sales_kunjungan")
    detail_id_type = assert_id_column_auto(details, "sales_kunjungan_detail")
    for name in ("status", "id_plafon", "id_user"):
        assert_integer_column(visits, "sales_kunjungan", name)
    assert_date_column(visits, "sales_kunjungan", "tanggal")
    assert_time_column(visits, "sales_kunjungan", "waktu_mulai")
    if "waktu_selesai" in visits:
        assert_time_column(visits, "sales_kunjungan", "waktu_selesai")
    schedule = visits.get("id_plafon_jadwal")
    if schedule is not None and not schedule.nullable:
        raise ValidationError(
            "public.sales_kunjungan.id_plafon_jadwal tidak nullable; sumber tidak membawa mapping jadwal yang aman."
        )
    for name in (
        "id_sales_kunjungan", "id_plafon", "id_principal", "id_customer", "id_user",
        "status_proses1", "status_proses2", "status_proses3", "status_checkin",
    ):
        assert_integer_column(details, "sales_kunjungan_detail", name)
    known_visit = {"id", "tanggal", "waktu_mulai", "waktu_selesai", "status", "id_plafon", "id_plafon_jadwal", "id_user"}
    known_detail = {
        "id", "id_sales_kunjungan", "id_plafon", "id_principal", "id_customer", "id_user",
        "status_proses1", "status_proses2", "status_proses3", "status_checkin",
    }
    unsupported_visit = sorted(name for name, column in visits.items() if column.needs_explicit_value and name not in known_visit)
    unsupported_detail = sorted(name for name, column in details.items() if column.needs_explicit_value and name not in known_detail)
    if unsupported_visit or unsupported_detail:
        bits = []
        if unsupported_visit:
            bits.append("sales_kunjungan=" + ",".join(unsupported_visit))
        if unsupported_detail:
            bits.append("sales_kunjungan_detail=" + ",".join(unsupported_detail))
        raise ValidationError("Target memiliki kolom wajib tanpa nilai sumber/policy: " + "; ".join(bits))
    return visits, details, visit_id_type, detail_id_type


def assert_no_enabled_user_triggers(cur) -> None:
    """Reject apply when direct DML could invoke unreviewed business logic.

    The importer deliberately writes the two verified visit tables directly.
    An enabled application trigger would be an additional, unverified side
    effect (for example an inventory, journal, or notification action), so it
    must be reviewed explicitly instead of being triggered incidentally.
    """

    cur.execute(
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
        (["sales_kunjungan", "sales_kunjungan_detail"],),
    )
    enabled = [f"public.{row[0]}.{row[1]}" for row in cur.fetchall()]
    if enabled:
        raise ValidationError(
            "Apply kunjungan diblokir karena ada trigger target yang belum direview: "
            + ", ".join(enabled)
        )


def resolve_candidates(
    rows_by_source: dict[str, list[StageRow]],
    metadata: dict[str, StageMetadata],
    contexts: dict[str, tuple[int, int]],
    customer_maps: dict[str, dict[tuple[str, ...], MappingValue]],
    principal_maps: dict[str, dict[tuple[str, ...], MappingValue]],
    sales_maps: dict[str, dict[tuple[str, ...], MappingValue]],
    customers: dict[int, TargetCustomer],
    principals: dict[int, TargetPrincipal],
    sales: dict[int, TargetSales],
    plafons: dict[tuple[int, int, int], list[TargetPlafon]],
    visit_columns: dict[str, TargetColumn],
) -> tuple[list[VisitCandidate], list[Hold]]:
    candidates: list[VisitCandidate] = []
    holds: list[Hold] = []
    for source_system, rows in rows_by_source.items():
        expected_company, expected_branch = contexts[source_system]
        for row in rows:
            source_visit_id = clean(row.source_visit_id_raw)
            customer_code = norm(row.kodecustomer_raw)
            principal_code = norm(row.kodeprinciple_raw)
            sales_code = norm(row.kodesales_raw)
            if source_visit_id is None:
                holds.append(Hold(row, "blank_source_visit_id"))
                continue
            if customer_code is None:
                holds.append(Hold(row, "blank_customer_code"))
                continue
            if principal_code is None:
                holds.append(Hold(row, "blank_principal_code"))
                continue
            if sales_code is None:
                holds.append(Hold(row, "blank_sales_code"))
                continue
            customer_map = customer_maps[source_system].get((customer_code,))
            principal_map = principal_maps[source_system].get((principal_code,))
            sales_map = sales_maps[source_system].get((principal_code, sales_code))
            if customer_map is None:
                holds.append(Hold(row, "missing_customer_map"))
                continue
            if principal_map is None:
                holds.append(Hold(row, "missing_principal_map", {"id_customer": customer_map.target_id}))
                continue
            if sales_map is None:
                holds.append(Hold(row, "missing_sales_map", {"id_customer": customer_map.target_id, "id_principal": principal_map.target_id}))
                continue
            customer = customers.get(customer_map.target_id)
            principal = principals.get(principal_map.target_id)
            salesperson = sales.get(sales_map.target_id)
            if customer is None:
                holds.append(Hold(row, "mapped_customer_not_found"))
                continue
            if principal is None:
                holds.append(Hold(row, "mapped_principal_not_found"))
                continue
            if salesperson is None:
                holds.append(Hold(row, "mapped_sales_not_found"))
                continue
            if customer.id_cabang != expected_branch and customer_map.method != "cross_branch_approved":
                holds.append(Hold(row, "mapped_customer_branch_scope_changed"))
                continue
            if principal.id_perusahaan != expected_company:
                holds.append(Hold(row, "mapped_principal_company_scope_changed"))
                continue
            if salesperson.id_principal != principal.id_principal:
                holds.append(Hold(row, "mapped_sales_principal_scope_changed"))
                continue
            if salesperson.id_user is None:
                holds.append(Hold(row, "mapped_sales_missing_user"))
                continue
            if salesperson.user_company_id != expected_company or salesperson.user_branch_id != expected_branch:
                holds.append(Hold(row, "mapped_sales_user_scope_changed"))
                continue
            target_key = (customer.id_customer, principal.id_principal, salesperson.id_sales)
            target_plafons = plafons.get(target_key, [])
            if len(target_plafons) == 0:
                holds.append(Hold(row, "missing_target_plafon", {"target_key": target_key}))
                continue
            if len(target_plafons) > 1:
                holds.append(Hold(row, "duplicate_target_plafon", {"target_key": target_key, "count": len(target_plafons)}))
                continue
            target_plafon = target_plafons[0]
            if target_plafon.id_user != salesperson.id_user:
                holds.append(Hold(row, "target_plafon_user_mismatch", {"id_plafon": target_plafon.id_plafon}))
                continue
            visit_at, visit_reason = parse_iso_datetime(row.tanggal_raw, reason_prefix="tanggal")
            if visit_reason:
                holds.append(Hold(row, visit_reason))
                continue
            checkout, checkout_reason = parse_checkout(row.checkout_raw)
            if checkout_reason:
                holds.append(Hold(row, checkout_reason))
                continue
            assert visit_at is not None and checkout is not None
            checkout_at: datetime | None = None
            if checkout:
                checkout_at, checkout_at_reason = parse_iso_datetime(row.tanggalcheckout_raw, reason_prefix="tanggalcheckout")
                if checkout_at_reason:
                    holds.append(Hold(row, checkout_at_reason))
                    continue
                assert checkout_at is not None
                if checkout_at < visit_at:
                    holds.append(Hold(row, "checkout_before_checkin"))
                    continue
                # The verified ERP target stores only a time for checkout, not
                # a checkout date.  Persisting a next-day checkout would make
                # the end time look earlier than the start time, so retain it
                # as a hold until the target model can represent it correctly.
                if checkout_at.date() != visit_at.date():
                    holds.append(Hold(row, "checkout_crosses_day"))
                    continue
                status = 2
            else:
                if clean(row.tanggalcheckout_raw) is not None:
                    holds.append(Hold(row, "checkout_false_with_checkout_timestamp"))
                    continue
                status = 1
            if visit_columns["waktu_mulai"].needs_explicit_value and visit_at.time() == time.min and DATE_RE.fullmatch(clean(row.tanggal_raw) or ""):
                holds.append(Hold(row, "missing_visit_start_time"))
                continue
            if "waktu_selesai" in visit_columns and visit_columns["waktu_selesai"].needs_explicit_value and checkout_at is None:
                holds.append(Hold(row, "missing_checkout_time_for_required_target"))
                continue
            candidates.append(
                VisitCandidate(
                    row=row,
                    source_visit_id=source_visit_id,
                    source_visit_id_norm=source_visit_id.lower(),
                    visit_at=visit_at,
                    checkout_at=checkout_at,
                    visit_status=status,
                    id_customer=customer.id_customer,
                    id_principal=principal.id_principal,
                    id_sales=salesperson.id_sales,
                    id_user=salesperson.id_user,
                    id_plafon=target_plafon.id_plafon,
                )
            )
    return candidates, holds


def hold_duplicate_source_ids(candidates: Iterable[VisitCandidate]) -> tuple[list[VisitCandidate], list[Hold]]:
    grouped: dict[tuple[str, str], list[VisitCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.key].append(candidate)
    unique: list[VisitCandidate] = []
    holds: list[Hold] = []
    for key, items in grouped.items():
        if len(items) == 1:
            unique.append(items[0])
            continue
        hashes = sorted({item.row.source_row_hash for item in items})
        for item in items:
            holds.append(Hold(item.row, "duplicate_source_visit_id", {"source_key": key, "row_count": len(items), "distinct_hashes": len(hashes)}))
    return unique, holds


def audit_table_presence(cur) -> set[str]:
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = %s AND table_name = ANY(%s)
        """,
        (REGISTRY_SCHEMA, list(AUDIT_TABLES)),
    )
    return {str(row[0]) for row in cur.fetchall()}


def audit_tables_ready(cur) -> bool:
    present = audit_table_presence(cur)
    if present and present != set(AUDIT_TABLES):
        raise ValidationError(
            "Registry audit kunjungan hanya terpasang sebagian: "
            + ", ".join(sorted(present))
            + ". Perbaiki schema audit terlebih dahulu; dry-run tidak boleh mengabaikan map yang mungkin sudah ada."
        )
    return present == set(AUDIT_TABLES)


def ensure_audit_tables(cur, visit_id_type: str, detail_id_type: str) -> None:
    registry = ident(REGISTRY_SCHEMA)
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {registry}.active_visit_import_run (
            id BIGSERIAL PRIMARY KEY,
            batch_id TEXT NOT NULL,
            bdm_stage_schema TEXT NOT NULL,
            tmp_stage_schema TEXT NOT NULL,
            bdm_stage_run_id BIGINT NOT NULL,
            tmp_stage_run_id BIGINT NOT NULL,
            finality_reason TEXT NOT NULL,
            source_summary JSONB NOT NULL,
            plan_hash TEXT NOT NULL,
            inserted_visits BIGINT NOT NULL,
            unchanged_visits BIGINT NOT NULL,
            held_rows BIGINT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {registry}.active_visit_document_map (
            source_system TEXT NOT NULL
                REFERENCES {registry}.source_context(source_system) ON DELETE RESTRICT,
            source_visit_id TEXT NOT NULL,
            source_visit_id_norm TEXT NOT NULL,
            source_stage_schema TEXT NOT NULL,
            source_stage_run_id BIGINT NOT NULL,
            source_staging_id BIGINT NOT NULL,
            source_row_hash TEXT NOT NULL,
            source_tanggal_raw TEXT,
            source_tanggalcheckout_raw TEXT,
            source_checkout_raw TEXT,
            source_latitude_raw TEXT,
            source_longitude_raw TEXT,
            id_sales_kunjungan {visit_id_type} NOT NULL
                REFERENCES public.sales_kunjungan(id) ON DELETE RESTRICT,
            id_sales_kunjungan_detail {detail_id_type} NOT NULL
                REFERENCES public.sales_kunjungan_detail(id) ON DELETE RESTRICT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (source_system, source_visit_id_norm),
            UNIQUE (source_system, source_stage_schema, source_staging_id),
            UNIQUE (id_sales_kunjungan),
            UNIQUE (id_sales_kunjungan_detail),
            CHECK (source_visit_id_norm = lower(btrim(source_visit_id))),
            CHECK (source_visit_id_norm <> '')
        )
        """
    )
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {registry}.active_visit_import_hold (
            id BIGSERIAL PRIMARY KEY,
            import_run_id BIGINT NOT NULL
                REFERENCES {registry}.active_visit_import_run(id) ON DELETE RESTRICT,
            source_system TEXT NOT NULL,
            source_stage_schema TEXT NOT NULL,
            source_stage_run_id BIGINT NOT NULL,
            source_staging_id BIGINT NOT NULL,
            source_visit_id TEXT,
            source_row_hash TEXT NOT NULL,
            hold_reason TEXT NOT NULL,
            details JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {registry}.active_visit_import_action (
            id BIGSERIAL PRIMARY KEY,
            import_run_id BIGINT NOT NULL
                REFERENCES {registry}.active_visit_import_run(id) ON DELETE RESTRICT,
            source_system TEXT NOT NULL,
            source_visit_id_norm TEXT NOT NULL,
            source_stage_schema TEXT NOT NULL,
            source_staging_id BIGINT NOT NULL,
            source_row_hash TEXT NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('inserted_active_visit', 'unchanged_existing_active_visit')),
            id_sales_kunjungan BIGINT NOT NULL,
            id_sales_kunjungan_detail BIGINT NOT NULL,
            details JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    # Fail closed when a manually created/old audit table has an incomplete
    # shape.  CREATE IF NOT EXISTS alone would otherwise make reruns unsafe.
    required = {
        "active_visit_import_run": {"id", "batch_id", "source_summary", "plan_hash"},
        "active_visit_document_map": {"source_system", "source_visit_id_norm", "source_row_hash", "id_sales_kunjungan", "id_sales_kunjungan_detail"},
        "active_visit_import_hold": {"import_run_id", "source_system", "source_staging_id", "hold_reason"},
        "active_visit_import_action": {"import_run_id", "action", "id_sales_kunjungan", "id_sales_kunjungan_detail"},
    }
    cur.execute(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = ANY(%s)
        """,
        (REGISTRY_SCHEMA, list(required)),
    )
    present: dict[str, set[str]] = defaultdict(set)
    for table, column in cur.fetchall():
        present[str(table)].add(str(column))
    for table, required_columns in required.items():
        missing = required_columns - present.get(table, set())
        if missing:
            raise ValidationError(f"Audit table {REGISTRY_SCHEMA}.{table} tidak lengkap: {', '.join(sorted(missing))}.")


def fetch_existing_maps(cur, keys: set[tuple[str, str]]) -> dict[tuple[str, str], ExistingMap]:
    if not keys:
        return {}
    try:
        from psycopg2.extras import execute_values  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        raise ValidationError("psycopg2 diperlukan untuk membaca PostgreSQL.") from exc
    result: dict[tuple[str, str], ExistingMap] = {}
    for batch in chunks(sorted(keys)):
        rows = execute_values(
            cur,
            f"""
            WITH requested(source_system, source_visit_id_norm) AS (VALUES %s)
            SELECT m.source_system, m.source_visit_id_norm, m.source_row_hash,
                   m.id_sales_kunjungan, m.id_sales_kunjungan_detail
            FROM {qtable(REGISTRY_SCHEMA, 'active_visit_document_map')} m
            JOIN requested r
              ON r.source_system = m.source_system
             AND r.source_visit_id_norm = m.source_visit_id_norm
            """,
            batch,
            page_size=len(batch),
            fetch=True,
        )
        for row in rows:
            item = ExistingMap(str(row[0]), str(row[1]), str(row[2]), int(row[3]), int(row[4]))
            if item.source_system not in SOURCE_SYSTEMS:
                raise ValidationError("active_visit_document_map mengandung source system tidak dikenal.")
            if (item.source_system, item.source_visit_id_norm) in result:
                raise ValidationError("active_visit_document_map memiliki source key duplikat.")
            result[(item.source_system, item.source_visit_id_norm)] = item
    return result


def fetch_existing_target_payloads(
    cur,
    existing: Iterable[ExistingMap],
    *,
    has_waktu_selesai: bool,
) -> dict[tuple[str, str], ExistingTargetPayload]:
    items = list(existing)
    if not items:
        return {}
    visit_ids = sorted({item.id_sales_kunjungan for item in items})
    detail_ids = sorted({item.id_sales_kunjungan_detail for item in items})
    checkout_expr = "v.waktu_selesai" if has_waktu_selesai else "NULL::time"
    cur.execute(
        f"""
        SELECT v.id, v.tanggal, v.waktu_mulai, {checkout_expr}, v.status, v.id_plafon, v.id_user
        FROM public.sales_kunjungan v
        WHERE v.id = ANY(%s)
        """,
        (visit_ids,),
    )
    visits = {
        int(row[0]): (row[1], row[2], row[3], int(row[4]), int(row[5]), int(row[6]))
        for row in cur.fetchall()
    }
    cur.execute(
        """
        SELECT d.id, d.id_sales_kunjungan, d.id_plafon, d.id_principal, d.id_customer, d.id_user,
               d.status_proses1, d.status_proses2, d.status_proses3, d.status_checkin
        FROM public.sales_kunjungan_detail d
        WHERE d.id = ANY(%s)
        """,
        (detail_ids,),
    )
    details = {
        int(row[0]): (int(row[1]), int(row[2]), int(row[3]), int(row[4]), int(row[5]), int(row[6]), int(row[7]), int(row[8]), int(row[9]), int(row[10]))
        for row in cur.fetchall()
    }
    result: dict[tuple[str, str], ExistingTargetPayload] = {}
    for item in items:
        visit = visits.get(item.id_sales_kunjungan)
        detail = details.get(item.id_sales_kunjungan_detail)
        visit_payload = visit if visit is not None else None
        detail_payload = None
        if detail is not None and detail[0] == item.id_sales_kunjungan:
            detail_payload = detail[1:]
        result[(item.source_system, item.source_visit_id_norm)] = ExistingTargetPayload(
            item.id_sales_kunjungan,
            item.id_sales_kunjungan_detail,
            visit_payload,
            detail_payload,
        )
    return result


def find_unprovenanced_target_visit_candidates(
    cur,
    candidates: Iterable[VisitCandidate],
    *,
    has_waktu_selesai: bool,
) -> dict[tuple[str, str], int]:
    """Find existing public visits that look like an unmapped source visit.

    The current ERP already contains historical visits, but those rows have no
    source-qualified migration key.  Inserting another row merely because the
    registry is empty would duplicate a real check-in.  This is deliberately a
    conservative *hold* detector: an exact header match is enough to require
    later adoption/reconciliation; it never guesses that an old row belongs to
    a particular BDM/TMP source record.
    """

    items = list(candidates)
    if not items:
        return {}
    try:
        from psycopg2.extras import execute_values  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - runtime dependency
        raise ValidationError("psycopg2 diperlukan untuk memeriksa kunjungan target.") from exc

    finish_match = "v.waktu_selesai IS NOT DISTINCT FROM r.waktu_selesai" if has_waktu_selesai else "TRUE"
    result: dict[tuple[str, str], int] = {}
    for batch in chunks(items):
        rows = [
            (
                item.row.source_system,
                item.source_visit_id_norm,
                item.visit_at.date(),
                item.visit_at.time(),
                item.checkout_at.time() if item.checkout_at is not None else None,
                item.visit_status,
                item.id_plafon,
                item.id_user,
            )
            for item in batch
        ]
        matches = execute_values(
            cur,
            f"""
            WITH requested(
                source_system, source_visit_id_norm, tanggal, waktu_mulai,
                waktu_selesai, status, id_plafon, id_user
            ) AS (VALUES %s)
            SELECT r.source_system, r.source_visit_id_norm, COUNT(v.id)
            FROM requested r
            JOIN public.sales_kunjungan v
              ON v.tanggal = r.tanggal
             AND v.waktu_mulai = r.waktu_mulai
             AND {finish_match}
             AND v.status = r.status
             AND v.id_plafon = r.id_plafon
             AND v.id_user = r.id_user
            GROUP BY r.source_system, r.source_visit_id_norm
            """,
            rows,
            page_size=len(rows),
            fetch=True,
        )
        for source_system, source_visit_id_norm, match_count in matches:
            result[(str(source_system), str(source_visit_id_norm))] = int(match_count)
    return result


def classify_actions(
    candidates: Iterable[VisitCandidate],
    existing_maps: dict[tuple[str, str], ExistingMap],
    existing_payloads: dict[tuple[str, str], ExistingTargetPayload],
) -> tuple[list[PlannedInsert], list[PlannedUnchanged], list[Hold]]:
    inserts: list[PlannedInsert] = []
    unchanged: list[PlannedUnchanged] = []
    holds: list[Hold] = []
    for candidate in candidates:
        existing = existing_maps.get(candidate.key)
        if existing is None:
            inserts.append(PlannedInsert(candidate))
            continue
        if existing.source_row_hash != candidate.row.source_row_hash:
            holds.append(Hold(candidate.row, "source_row_hash_changed_after_apply", {"source_key": candidate.key}))
            continue
        target = existing_payloads.get(candidate.key)
        if target is None or target.visit_payload is None or target.detail_payload is None:
            holds.append(Hold(candidate.row, "existing_mapped_target_missing_or_broken", {"source_key": candidate.key}))
            continue
        if target.visit_payload != candidate.expected_visit_payload or target.detail_payload != candidate.expected_detail_payload:
            holds.append(Hold(candidate.row, "existing_mapped_target_drift", {"source_key": candidate.key}))
            continue
        unchanged.append(PlannedUnchanged(candidate, existing))
    return inserts, unchanged, holds


def hold_summary(holds: Iterable[Hold]) -> dict[str, int]:
    return dict(sorted(Counter(item.reason for item in holds).items()))


def source_summary(metadata: dict[str, StageMetadata], rows_by_source: dict[str, list[StageRow]]) -> dict[str, Any]:
    return {
        source: {
            "stage_schema": item.schema,
            "stage_run_id": item.run_id,
            "source_rows": len(rows_by_source[source]),
            "consistency_mode": item.consistency_mode,
            "is_preview": item.is_preview,
            "maintenance_window_id": item.maintenance_window_id,
        }
        for source, item in metadata.items()
    }


def plan_hash(inserts: Iterable[PlannedInsert], unchanged: Iterable[PlannedUnchanged], holds: Iterable[Hold]) -> str:
    payload = {
        "inserts": sorted((item.candidate.key, item.candidate.row.source_row_hash) for item in inserts),
        "unchanged": sorted((item.candidate.key, item.candidate.row.source_row_hash) for item in unchanged),
        "holds": sorted((item.row.source_system, item.row.staging_id, item.reason, item.row.source_row_hash) for item in holds),
    }
    return hashlib.sha256(json.dumps(json_safe(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def plan_summary(
    metadata: dict[str, StageMetadata],
    rows_by_source: dict[str, list[StageRow]],
    inserts: list[PlannedInsert],
    unchanged: list[PlannedUnchanged],
    holds: list[Hold],
    *,
    mode: str,
) -> dict[str, Any]:
    final_ok, final_reason = final_stage_gate(metadata)
    return {
        "status": mode,
        "module": "active_visit_only",
        "source_summary": source_summary(metadata, rows_by_source),
        "final_stage_eligible": final_ok,
        "final_stage_reason": final_reason,
        "planned_inserted_active_visits": len(inserts),
        "planned_unchanged_existing_active_visits": len(unchanged),
        "held_rows": len(holds),
        "hold_summary": hold_summary(holds),
        "plan_hash": plan_hash(inserts, unchanged, holds),
        "purchase_active_import": {
            "status": "blocked_pending_explicit_uom_semantics",
            "reason": "DPembelian tidak memiliki UOM source yang dapat dibuktikan dari unit/perunit/satuan/jumlah saja; tool ini tidak memilih UOM terdekat atau membuat mutasi stok.",
            "next_tool": "reconcile_visit_purchase_staging.py",
        },
        "no_sql_server_writes": True,
    }


def apply_plan(
    cur,
    metadata: dict[str, StageMetadata],
    rows_by_source: dict[str, list[StageRow]],
    inserts: list[PlannedInsert],
    unchanged: list[PlannedUnchanged],
    holds: list[Hold],
    args: argparse.Namespace,
    visit_id_type: str,
    detail_id_type: str,
    visit_columns: dict[str, TargetColumn],
) -> dict[str, Any]:
    """Write public visits and registry audit in one PostgreSQL transaction."""

    assert_final_staging(metadata)
    ensure_audit_tables(cur, visit_id_type, detail_id_type)
    # The caller serializes this importer with an advisory lock.  It also
    # rebuilds the plan after obtaining row-level locks on the exact Plafon
    # records.  Do not take a table-wide lock here: this batch can contain
    # thousands of visits and normal ERP activity must remain available.
    # The run is intentionally tied to the caller's precomputed source rows;
    # source staging itself is immutable/final and has already been validated.
    current_summary = plan_summary(metadata, rows_by_source, inserts, unchanged, holds, mode="apply_prelock")
    cur.execute(
        f"""
        INSERT INTO {qtable(REGISTRY_SCHEMA, 'active_visit_import_run')}
            (batch_id, bdm_stage_schema, tmp_stage_schema, bdm_stage_run_id, tmp_stage_run_id,
             finality_reason, source_summary, plan_hash, inserted_visits, unchanged_visits, held_rows)
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            args.batch_id,
            metadata["bdm_solo_dist"].schema,
            metadata["tmp_solo_dist"].schema,
            metadata["bdm_solo_dist"].run_id,
            metadata["tmp_solo_dist"].run_id,
            current_summary["final_stage_reason"],
            json.dumps(current_summary["source_summary"], ensure_ascii=False, sort_keys=True),
            current_summary["plan_hash"],
            len(inserts),
            len(unchanged),
            len(holds),
        ),
    )
    import_run_id = int(cur.fetchone()[0])

    inserted_actions: list[tuple[VisitCandidate, int, int]] = []
    include_finish = "waktu_selesai" in visit_columns
    include_schedule = "id_plafon_jadwal" in visit_columns
    for planned in inserts:
        candidate = planned.candidate
        columns = ["tanggal", "waktu_mulai"]
        values: list[Any] = [candidate.visit_at.date(), candidate.visit_at.time()]
        if include_finish:
            columns.append("waktu_selesai")
            values.append(candidate.checkout_at.time() if candidate.checkout_at is not None else None)
        columns.extend(["status", "id_plafon"])
        values.extend([candidate.visit_status, candidate.id_plafon])
        if include_schedule:
            columns.append("id_plafon_jadwal")
            values.append(None)
        columns.append("id_user")
        values.append(candidate.id_user)
        cur.execute(
            f"INSERT INTO public.sales_kunjungan ({', '.join(ident(column) for column in columns)}) "
            f"VALUES ({', '.join(['%s'] * len(values))}) RETURNING id",
            tuple(values),
        )
        visit_id = int(cur.fetchone()[0])
        cur.execute(
            """
            INSERT INTO public.sales_kunjungan_detail
                (id_sales_kunjungan, id_plafon, id_principal, id_customer, id_user,
                 status_proses1, status_proses2, status_proses3, status_checkin)
            VALUES (%s, %s, %s, %s, %s, 0, 0, 0, 1)
            RETURNING id
            """,
            (visit_id, candidate.id_plafon, candidate.id_principal, candidate.id_customer, candidate.id_user),
        )
        detail_id = int(cur.fetchone()[0])
        cur.execute(
            f"""
            INSERT INTO {qtable(REGISTRY_SCHEMA, 'active_visit_document_map')}
                (source_system, source_visit_id, source_visit_id_norm,
                 source_stage_schema, source_stage_run_id, source_staging_id, source_row_hash,
                 source_tanggal_raw, source_tanggalcheckout_raw, source_checkout_raw,
                 source_latitude_raw, source_longitude_raw,
                 id_sales_kunjungan, id_sales_kunjungan_detail)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                candidate.row.source_system,
                candidate.source_visit_id,
                candidate.source_visit_id_norm,
                candidate.row.stage_schema,
                candidate.row.stage_run_id,
                candidate.row.staging_id,
                candidate.row.source_row_hash,
                candidate.row.tanggal_raw,
                candidate.row.tanggalcheckout_raw,
                candidate.row.checkout_raw,
                candidate.row.latitude_raw,
                candidate.row.longitude_raw,
                visit_id,
                detail_id,
            ),
        )
        inserted_actions.append((candidate, visit_id, detail_id))

    try:
        from psycopg2.extras import execute_values  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        raise ValidationError("psycopg2 diperlukan untuk menulis audit PostgreSQL.") from exc
    if holds:
        execute_values(
            cur,
            f"""
            INSERT INTO {qtable(REGISTRY_SCHEMA, 'active_visit_import_hold')}
                (import_run_id, source_system, source_stage_schema, source_stage_run_id,
                 source_staging_id, source_visit_id, source_row_hash, hold_reason, details)
            VALUES %s
            """,
            [
                (
                    import_run_id,
                    hold.row.source_system,
                    hold.row.stage_schema,
                    hold.row.stage_run_id,
                    hold.row.staging_id,
                    hold.row.source_visit_id_raw,
                    hold.row.source_row_hash,
                    hold.reason,
                    json.dumps(json_safe(hold.details), ensure_ascii=False, sort_keys=True),
                )
                for hold in holds
            ],
            page_size=1000,
        )
    actions: list[tuple[Any, ...]] = [
        (
            import_run_id,
            candidate.row.source_system,
            candidate.source_visit_id_norm,
            candidate.row.stage_schema,
            candidate.row.staging_id,
            candidate.row.source_row_hash,
            "inserted_active_visit",
            visit_id,
            detail_id,
            json.dumps({"status": candidate.visit_status}, ensure_ascii=False),
        )
        for candidate, visit_id, detail_id in inserted_actions
    ]
    actions.extend(
        (
            import_run_id,
            item.candidate.row.source_system,
            item.candidate.source_visit_id_norm,
            item.candidate.row.stage_schema,
            item.candidate.row.staging_id,
            item.candidate.row.source_row_hash,
            "unchanged_existing_active_visit",
            item.existing.id_sales_kunjungan,
            item.existing.id_sales_kunjungan_detail,
            json.dumps({"status": item.candidate.visit_status}, ensure_ascii=False),
        )
        for item in unchanged
    )
    if actions:
        execute_values(
            cur,
            f"""
            INSERT INTO {qtable(REGISTRY_SCHEMA, 'active_visit_import_action')}
                (import_run_id, source_system, source_visit_id_norm, source_stage_schema,
                 source_staging_id, source_row_hash, action,
                 id_sales_kunjungan, id_sales_kunjungan_detail, details)
            VALUES %s
            """,
            actions,
            page_size=1000,
        )
    return {"import_run_id": import_run_id, "inserted_active_visits": len(inserted_actions), "unchanged_active_visits": len(unchanged), "held_rows": len(holds)}


def assert_no_unprovenanced_target_visit_context(
    cur,
    inserts: Iterable[PlannedInsert],
) -> None:
    """Block live inserts when the target period has legacy visits to adopt.

    `sales_kunjungan` has no source key and no unique natural-key constraint.
    An equal timestamp is not proof that a target row is unrelated to this
    source: previous imports can normalize timezone, checkout, or status.
    Until a source-qualified 1:1 adoption manifest exists, a target row in the
    proposed date range makes a new visit insert unsafe.
    """

    planned = list(inserts)
    if not planned:
        return
    start_date = min(item.candidate.visit_at.date() for item in planned)
    end_date = max(item.candidate.visit_at.date() for item in planned)
    cur.execute(
        """
        SELECT COUNT(*)
        FROM public.sales_kunjungan
        WHERE tanggal >= %s
          AND tanggal <= %s
        """,
        (start_date, end_date),
    )
    target_count = int(cur.fetchone()[0])
    if target_count:
        raise ValidationError(
            "Apply kunjungan diblokir: public.sales_kunjungan sudah berisi "
            f"{target_count} baris pada periode {start_date.isoformat()} s.d. {end_date.isoformat()} "
            "tanpa manifest adopsi source-qualified 1:1. Rekonsiliasikan/adopsi target lama atau "
            "review manual sebelum membuat kunjungan baru."
        )


def build_plan(cur, args: argparse.Namespace, *, lock_plafon: bool) -> tuple[
    dict[str, StageMetadata], dict[str, list[StageRow]], list[PlannedInsert], list[PlannedUnchanged], list[Hold], dict[str, TargetColumn], str, str
]:
    stage_columns = load_stage_columns(cur, [args.bdm_schema, args.tmp_schema])
    metadata = {
        "bdm_solo_dist": stage_metadata(cur, args.bdm_schema, "bdm_solo_dist", stage_columns),
        "tmp_solo_dist": stage_metadata(cur, args.tmp_schema, "tmp_solo_dist", stage_columns),
    }
    for item in metadata.values():
        validate_stage_provenance(cur, item)
    visit_columns, _detail_columns, visit_id_type, detail_id_type = validate_target_schema(cur)
    rows_by_source = {source: fetch_stage_rows(cur, item) for source, item in metadata.items()}
    contexts = {source: load_source_context(cur, source) for source in SOURCE_SYSTEMS}
    for source, item in metadata.items():
        if contexts[source] != (item.target_company_id, item.target_branch_id):
            raise ValidationError(f"Scope staging {item.schema} tidak sesuai registry source_context {source}.")
    customer_maps = {source: load_mapping(cur, source, "customer_map", ("source_customer_code_norm",), "id_customer") for source in SOURCE_SYSTEMS}
    principal_maps = {source: load_mapping(cur, source, "principal_map", ("source_principal_code_norm",), "id_principal") for source in SOURCE_SYSTEMS}
    sales_maps = {source: load_mapping(cur, source, "sales_map", ("source_principal_code_norm", "source_sales_code_norm"), "id_sales") for source in SOURCE_SYSTEMS}
    customer_ids = {value.target_id for mapping in customer_maps.values() for value in mapping.values()}
    principal_ids = {value.target_id for mapping in principal_maps.values() for value in mapping.values()}
    sales_ids = {value.target_id for mapping in sales_maps.values() for value in mapping.values()}
    customers = fetch_customer_targets(cur, customer_ids)
    principals = fetch_principal_targets(cur, principal_ids)
    sales = fetch_sales_targets(cur, sales_ids)
    # Derive all possible triples before resolving rows.  The later resolver
    # still verifies exact user/scope and holds impossible source records.
    triples: set[tuple[int, int, int]] = set()
    for source in SOURCE_SYSTEMS:
        for row in rows_by_source[source]:
            customer = customer_maps[source].get((norm(row.kodecustomer_raw) or "",))
            principal = principal_maps[source].get((norm(row.kodeprinciple_raw) or "",))
            sales_map = sales_maps[source].get((norm(row.kodeprinciple_raw) or "", norm(row.kodesales_raw) or ""))
            if customer and principal and sales_map:
                triples.add((customer.target_id, principal.target_id, sales_map.target_id))
    plafons = fetch_plafon_targets(cur, triples, lock_rows=lock_plafon)
    candidates, validation_holds = resolve_candidates(
        rows_by_source, metadata, contexts, customer_maps, principal_maps, sales_maps,
        customers, principals, sales, plafons, visit_columns,
    )
    candidates, duplicate_holds = hold_duplicate_source_ids(candidates)
    holds = [*validation_holds, *duplicate_holds]
    if audit_tables_ready(cur):
        maps = fetch_existing_maps(cur, {candidate.key for candidate in candidates})
        payloads = fetch_existing_target_payloads(cur, maps.values(), has_waktu_selesai="waktu_selesai" in visit_columns)
        inserts, unchanged, action_holds = classify_actions(candidates, maps, payloads)
        holds.extend(action_holds)
    else:
        # In dry-run, lack of the new registry tables is a preflight state. In
        # apply they are installed atomically before the locked plan is rebuilt.
        maps = {}
        inserts, unchanged = [PlannedInsert(candidate) for candidate in candidates], []

    # The registry only proves documents imported by this tool.  Existing ERP
    # visits without a registry row must not be treated as absent: hold any
    # exact header candidate for source-qualified adoption instead of creating
    # a second real visit.
    target_candidates = find_unprovenanced_target_visit_candidates(
        cur, candidates, has_waktu_selesai="waktu_selesai" in visit_columns,
    )
    safe_inserts: list[PlannedInsert] = []
    for planned in inserts:
        candidate = planned.candidate
        match_count = target_candidates.get(candidate.key, 0)
        if candidate.key not in maps and match_count:
            holds.append(
                Hold(
                    candidate.row,
                    "unprovenanced_existing_target_visit_candidate",
                    {"matching_target_visit_count": match_count},
                )
            )
            continue
        safe_inserts.append(planned)
    inserts = safe_inserts
    return metadata, rows_by_source, inserts, unchanged, holds, visit_columns, visit_id_type, detail_id_type


def run_self_test() -> int:
    assert parse_iso_datetime("2026-08-01", reason_prefix="tanggal")[0] == datetime(2026, 8, 1)
    assert parse_iso_datetime("2026-08-01 07:01:02.123", reason_prefix="tanggal")[0] == datetime(2026, 8, 1, 7, 1, 2, 123000)
    assert parse_iso_datetime("01/08/2026", reason_prefix="tanggal")[1] == "invalid_tanggal_format"
    assert parse_checkout("true") == (True, None)
    assert parse_checkout("0") == (False, None)
    assert parse_checkout("maybe")[1] == "unknown_checkout_value"
    assert stage_metadata_table("legacy_test", "__stage_run") == '"legacy_test"."__stage_run"'
    preview = StageMetadata("legacy_preview", "bdm_solo_dist", 1, "completed_preview", "read_committed_preview", True, None, False, None, "READ COMMITTED", None, 1, 5, 0, ())
    allowed, _reason = final_stage_gate({"bdm_solo_dist": preview, "tmp_solo_dist": preview})
    assert not allowed
    bdm = StageMetadata("legacy_bdm", "bdm_solo_dist", 1, "completed", "maintenance_freeze_serializable", False, "freeze-1", True, datetime(2026, 8, 30), "SERIALIZABLE", 30_000, 1, 5, 0, ())
    tmp = StageMetadata("legacy_tmp", "tmp_solo_dist", 1, "completed", "maintenance_freeze_serializable", False, "freeze-1", True, datetime(2026, 8, 30), "SERIALIZABLE", 30_000, 2, 5, 0, ())
    assert final_stage_gate({"bdm_solo_dist": bdm, "tmp_solo_dist": tmp})[0]
    print(json.dumps({"status": "ok", "self_test": "active_visit_source_aware"}, ensure_ascii=False))
    return 0


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()
    ensure_cli_args(args)
    try:
        import psycopg2  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - runtime environment
        raise ValidationError("psycopg2 diperlukan untuk PostgreSQL.") from exc
    conn = psycopg2.connect(dbname=args.pg_database, user=args.pg_user, host=args.pg_host, port=args.pg_port)
    try:
        with conn.cursor() as cur:
            # A dry-run needs one stable read snapshot.  An apply instead uses
            # READ COMMITTED and rebuilds the plan after acquiring public-table
            # locks, so it cannot write based on a snapshot taken before a
            # concurrent ERP edit completed.
            if args.apply:
                cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            else:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cur.execute("SET LOCAL lock_timeout = '10s'")
            cur.execute("SET LOCAL statement_timeout = %s", (f"{args.statement_timeout_seconds}s",))
            metadata, rows, inserts, unchanged, holds, visit_columns, visit_id_type, detail_id_type = build_plan(cur, args, lock_plafon=False)
            if not args.apply:
                print(json.dumps(plan_summary(metadata, rows, inserts, unchanged, holds, mode="dry_run"), ensure_ascii=False, sort_keys=True))
                conn.rollback()
                return 0
            assert_final_staging(metadata)
            # Audit DDL must exist before the locked rebuild so an existing map
            # from a prior batch is observed.  Rebuild inside a fresh lock is
            # intentionally not skipped even if the first plan was clean.
            ensure_audit_tables(cur, visit_id_type, detail_id_type)
            # Serialize only this importer.  Do not take a table-wide lock on
            # live ERP visit tables; the registry's source key plus this
            # advisory lock provide idempotency without blocking routine ERP
            # activity.  Exact referenced Plafon rows are locked on rebuild.
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)",
                ("migration_bdm_tmp_202608:active_visit_import",),
            )
            assert_no_enabled_user_triggers(cur)
            metadata, rows, inserts, unchanged, holds, visit_columns, visit_id_type, detail_id_type = build_plan(cur, args, lock_plafon=True)
            assert_no_unprovenanced_target_visit_context(cur, inserts)
            result = apply_plan(cur, metadata, rows, inserts, unchanged, holds, args, visit_id_type, detail_id_type, visit_columns)
        conn.commit()
        output = plan_summary(metadata, rows, inserts, unchanged, holds, mode="applied_active_visits")
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
