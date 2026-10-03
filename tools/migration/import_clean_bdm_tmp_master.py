#!/usr/bin/env python3
"""Plan (and, only when fully safe, import) the clean BDM/TMP master data.

This is the source-qualified master importer for the *blue/green* database
described by :mod:`clean_import_policy.json`.  It deliberately does not talk
to SQL Server: both source systems must already be present in their frozen
PostgreSQL staging schemas.

Safety properties
=================

* ``--dsn`` and ``--target-database`` are required.  The database named by
  both is checked after connecting.  Only a database explicitly named
  ``budimas_clean_*`` is eligible; ``budimas_dev``, the legacy/production
  names, and PostgreSQL templates are rejected even for a dry run.
* Dry-run is the default and runs in ``REPEATABLE READ, READ ONLY``.  It never
  creates an import run, resolves a source context, or writes an import hold.
* ``--apply`` is deliberately harder to invoke.  It requires immutable
  baseline fingerprints, a named import key, a non-production target, and a
  clean source-owned master area.  It uses one serializable transaction.
  Holds remain a hard stop by default.  A partial run is possible only with
  an exact generated hold manifest, a reviewer-filled approval envelope, its
  SHA-256 on the command line, and an explicit acknowledgement; every skipped
  hold is then persisted as immutable audit evidence.
* Every lookup is source-qualified.  TMP customers are planned first.  A BDM
  customer can share a TMP target only when both normalized source customer
  code *and* normalized store name match exactly.
* Missing semantics are reported as explicit holds.  They are never replaced
  by closest-name matching, ``MIN(id)``, numeric IDs baked into the source,
  or guessed UOM/price/plafon mappings.

The base ``20260902_create_clean_import_registry.sql`` needs the compatible
clean-target-only extension
``20260902_extend_clean_import_registry_master_maps.sql`` before UOM or price
rows can be applied.  The extension fixes two registry contracts:

1. ``product_uom_source_map`` has a unique key on a staging row alone, while
   one ``STOK`` row can be the evidence for both its verified base and outer
   UOM records.  It therefore cannot record both source-qualified maps.
2. There is no source-qualified price or plafon map table.  Writing either
   target without one would make a rerun/non-destructive audit impossible.

The script detects a missing extension during dry-run and blocks ``--apply``.
That is intentional fail-closed behavior, not an invitation to bypass the
registry.  For an approved clean historical target, a validated latest plafon
row preserves only its source limit/term.  It is created in an explicit
non-live state (``sisa_bon = 0`` and locked), never as an inferred opening AR
balance.  Blank or ambiguous identities remain import holds.

Typical dry-run (the DSN must name the parallel database explicitly)::

    python3 tools/migration/import_clean_bdm_tmp_master.py \
      --dsn "$CLEAN_PG_DSN" --target-database budimas_clean_20260902

No credentials are written to output, hold details, or the registry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


SCRIPT_VERSION = "clean-master-importer-20260902.3"
REGISTRY_SCHEMA = "migration_clean_bdm_tmp_202609"
SOURCE_ORDER = ("tmp_solo_dist", "bdm_solo_dist")
SOURCE_TABLES = ("principle", "customer", "sales", "stok", "barangsatuan", "plafon")
PROHIBITED_DATABASES = {"budimas", "budimas_dev", "postgres", "template0", "template1"}
CLEAN_DATABASE_RE = re.compile(r"^budimas_clean_[a-z0-9_]{1,48}$")
IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
INT_RE = re.compile(r"^[+-]?\d+(?:\.0+)?$")
DECIMAL_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$")
HOLD_MANIFEST_FORMAT = "clean-master-hold-manifest-v1"
HOLD_APPROVAL_ENVELOPE_FORMAT = "clean-master-hold-approval-envelope-v1"

# These are the public relations that define the write contract for this
# importer.  The registry has its own concrete contract validation below; it
# is deliberately excluded from the baseline fingerprint because the clean
# registry extension itself is installed after the baseline was cloned.
PUBLIC_IMPORT_TABLES = (
    "perusahaan",
    "cabang",
    "perusahaan_cabang",
    "principal",
    "customer",
    "users",
    "sales",
    "sales_detail",
    "sales_principal_assignment",
    "sales_tipe",
    "jabatan",
    "produk",
    "produk_uom",
    "produk_harga_jual",
    "produk_tipe_harga",
    "plafon",
    "sales_order",
    "sales_order_detail",
    "faktur",
    "faktur_detail",
)


class ImporterError(RuntimeError):
    """Raised for an unsafe input or an unsupported schema contract."""


class GuardError(ImporterError):
    """Raised before a connection may be used as a clean target."""


@dataclass(frozen=True)
class SourceConfig:
    source_system: str
    stage_schema: str
    company_code: str
    branch_code: str
    document_prefix: str


@dataclass(frozen=True)
class StageInfo:
    source_system: str
    schema: str
    run_id: int
    consistency_mode: str
    is_preview: bool
    maintenance_window_id: str | None
    maintenance_freeze_attested: bool
    maintenance_freeze_confirmed_at: str | None
    source_transaction_isolation: str | None
    status: str
    company_code: str
    branch_code: str
    snapshot_label: str
    snapshot_sha256: str
    manifest_sha256: str
    table_counts: Mapping[str, int]


@dataclass(frozen=True)
class TargetColumn:
    table: str
    name: str
    data_type: str
    udt_name: str
    nullable: bool
    default: str | None
    is_identity: bool
    is_generated: bool
    max_length: int | None

    @property
    def needs_insert_value(self) -> bool:
        return not self.nullable and not self.default and not self.is_identity and not self.is_generated


@dataclass(frozen=True)
class StageRow:
    source_system: str
    schema: str
    run_id: int
    table: str
    staging_id: int
    source_row_hash: str
    values: Mapping[str, Any]

    def value(self, column: str) -> str | None:
        return clean(self.values.get(column))


@dataclass(frozen=True)
class Hold:
    row: StageRow
    reason: str
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def source_identity_sha256(self) -> str:
        return stable_hash(
            {
                "source_system": self.row.source_system,
                "source_schema": self.row.schema,
                "source_table": self.row.table,
                "source_staging_id": self.row.staging_id,
            }
        )


@dataclass(frozen=True)
class PrincipalAction:
    row: StageRow
    source_code: str
    source_code_norm: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class CustomerAction:
    row: StageRow
    source_code: str
    source_code_norm: str
    source_name: str
    source_name_norm: str
    mapping_method: str
    shared_tmp_key: tuple[str, str] | None
    payload: Mapping[str, Any] | None


@dataclass(frozen=True)
class SalesAction:
    row: StageRow
    source_principal_code: str
    source_principal_code_norm: str
    source_sales_code: str
    source_sales_code_norm: str
    classification_basis: str
    payload_sales: Mapping[str, Any]
    payload_sales_detail: Mapping[str, Any]


@dataclass(frozen=True)
class ProductAction:
    row: StageRow
    source_principal_code: str
    source_principal_code_norm: str
    source_sku: str
    source_sku_norm: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class UomAction:
    product_key: tuple[str, str, str]
    row: StageRow
    source_uom_code: str
    source_uom_code_norm: str
    source_uom_ordinal: int
    level: int
    factor: int
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class PriceAction:
    product_key: tuple[str, str, str]
    row: StageRow
    source_price_column: str
    target_price_type_code: str
    value: Decimal


@dataclass(frozen=True)
class PlafonAction:
    row: StageRow
    source_customer_code_norm: str
    source_principal_code_norm: str
    source_sales_code_norm: str
    limit_bon: Decimal
    term: int
    source_added_at_raw: str
    source_added_at: datetime
    opening_balance_strategy: str = "non_live_zero_sisa_bon_locked"


@dataclass
class MasterPlan:
    target_database: str
    policy_sha256: str
    stages: Mapping[str, StageInfo]
    observed_schema_sha256: str | None = None
    observed_reference_sha256: str | None = None
    structural_blockers: list[Mapping[str, Any]] = field(default_factory=list)
    holds: list[Hold] = field(default_factory=list)
    principals: list[PrincipalAction] = field(default_factory=list)
    customers: list[CustomerAction] = field(default_factory=list)
    sales: list[SalesAction] = field(default_factory=list)
    products: list[ProductAction] = field(default_factory=list)
    uoms: list[UomAction] = field(default_factory=list)
    prices: list[PriceAction] = field(default_factory=list)
    plafon: list[PlafonAction] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def apply_eligible(self) -> bool:
        # A blue/green master run is intentionally all-or-nothing.  Once even
        # one immutable source row is held, writing the rest would leave a
        # target that cannot safely be rerun under the clean-target guard.
        return not self.structural_blockers and not self.holds


@dataclass(frozen=True)
class ApprovedHoldApproval:
    """Reviewed, source-bound authorization to skip exactly the listed holds."""

    manifest_sha256: str
    approval_sha256: str
    approved_by: str
    approval_reference: str
    approved_at: str
    hold_occurrences: int
    hold_entries: int
    entries: tuple[Mapping[str, Any], ...]


def clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def norm(value: Any) -> str | None:
    text = clean(value)
    return text.lower() if text else None


def qident(value: str) -> str:
    if not IDENT_RE.fullmatch(value):
        raise ImporterError(f"Identifier PostgreSQL tidak aman: {value!r}")
    return f'"{value}"'


def qtable(schema: str, table: str) -> str:
    return f"{qident(schema)}.{qident(table)}"


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_sha256(value: str | None, label: str) -> str:
    candidate = (value or "").strip().lower()
    if not SHA256_RE.fullmatch(candidate):
        raise GuardError(f"{label} harus SHA-256 hex 64 karakter")
    return candidate


def parse_int(value: Any, label: str, *, minimum: int | None = None) -> tuple[int | None, str | None]:
    text = clean(value)
    if text is None:
        return None, f"{label}_blank"
    if not INT_RE.fullmatch(text):
        return None, f"{label}_not_integer"
    try:
        parsed = int(Decimal(text))
    except (InvalidOperation, ValueError):
        return None, f"{label}_not_integer"
    if minimum is not None and parsed < minimum:
        return None, f"{label}_below_minimum"
    return parsed, None


def parse_decimal(value: Any, label: str, *, minimum: Decimal | None = None) -> tuple[Decimal | None, str | None]:
    text = clean(value)
    if text is None:
        return None, f"{label}_blank"
    if not DECIMAL_RE.fullmatch(text):
        return None, f"{label}_invalid"
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None, f"{label}_invalid"
    if not parsed.is_finite():
        return None, f"{label}_invalid"
    if minimum is not None and parsed < minimum:
        return None, f"{label}_below_minimum"
    return parsed, None


def decimal_as_finite_float(value: Decimal, label: str) -> tuple[float | None, str | None]:
    """Convert only values representable by a PostgreSQL ``float8`` target."""

    try:
        converted = float(value)
    except (OverflowError, ValueError):
        return None, f"{label}_outside_float8_range"
    if not math.isfinite(converted):
        return None, f"{label}_outside_float8_range"
    return converted, None


def parse_timestamp(value: Any) -> tuple[datetime | None, str | None]:
    text = clean(value)
    if text is None:
        return None, "source_tgladd_blank"
    candidates = (text, text.replace("/", "-"))
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc), None
        except ValueError:
            continue
    for fmt in ("%d-%m-%Y", "%d-%m-%Y %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc), None
        except ValueError:
            continue
    return None, "source_tgladd_invalid"


def parse_source_active(value: Any) -> tuple[bool | None, str | None]:
    text = norm(value)
    if text in {"1", "y", "yes", "true", "t", "aktif", "active"}:
        return True, None
    if text in {"0", "n", "no", "false", "f", "nonaktif", "inactive"}:
        return False, None
    if text is None:
        return None, "source_active_blank"
    return None, "source_active_unknown"


def too_long(value: str | None, limit: int | None) -> bool:
    return bool(value is not None and limit is not None and len(value) > limit)


def report_blocker(code: str, detail: str, **extra: Any) -> Mapping[str, Any]:
    return {"code": code, "detail": detail, **extra}


def policy_path_default() -> Path:
    return Path(__file__).with_name("clean_import_policy.json")


def load_policy(path: Path) -> tuple[Mapping[str, Any], Mapping[str, SourceConfig], str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ImporterError(f"Policy tidak ditemukan: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ImporterError(f"Policy JSON tidak valid: {path}: {exc}") from exc

    if payload.get("policy_id") != "clean_bdm_tmp_solo_bluegreen_20260902":
        raise ImporterError("policy_id clean import tidak sesuai")
    target = payload.get("target")
    if not isinstance(target, Mapping) or target.get("registry_schema") != REGISTRY_SCHEMA:
        raise ImporterError("registry_schema policy tidak sesuai dengan clean registry")
    sources = payload.get("sources")
    if not isinstance(sources, Mapping):
        raise ImporterError("Policy tidak memiliki sources")

    configs: dict[str, SourceConfig] = {}
    for source_system in ("bdm_solo_dist", "tmp_solo_dist"):
        source = sources.get(source_system)
        if not isinstance(source, Mapping):
            raise ImporterError(f"Policy source {source_system} tidak lengkap")
        stage_schema = clean(source.get("staging_schema"))
        company_code = clean(source.get("company_code"))
        branch_code = clean(source.get("branch_code"))
        document_prefix = clean(source.get("document_prefix"))
        if not all((stage_schema, company_code, branch_code, document_prefix)):
            raise ImporterError(f"Policy source {source_system} memiliki nilai kosong")
        # The policy may define source data and human document prefixes, but
        # numeric IDs are intentionally never part of the clean contract.
        if any(str(key).lower().endswith("_id") for key in source):
            raise ImporterError(f"Policy source {source_system} tidak boleh memuat ID target tetap")
        configs[source_system] = SourceConfig(
            source_system=source_system,
            stage_schema=stage_schema,
            company_code=company_code,
            branch_code=branch_code,
            document_prefix=document_prefix,
        )
    return payload, configs, sha256_file(path)


def require_psycopg2() -> Any:
    try:
        import psycopg2  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise ImporterError(
            "Dependency PostgreSQL belum tersedia. Pasang psycopg2 pada environment "
            "runner import (bukan pada database target)."
        ) from exc
    return psycopg2


def assert_clean_target_database_name(value: str, *, label: str) -> str:
    """Accept only the deliberately named blue/green clean database.

    A negative guard such as ``dbname != budimas_dev`` is not strong enough:
    it would still accept a future production/legacy database with another
    name.  Requiring the explicit clean naming convention makes a mistaken
    DSN fail before the script starts reading or writing any data.
    """

    candidate = clean(value)
    if candidate is None or candidate != candidate.lower() or not CLEAN_DATABASE_RE.fullmatch(candidate):
        raise GuardError(f"{label} harus database blue/green bernama budimas_clean_<label>")
    if candidate in PROHIBITED_DATABASES:
        raise GuardError(f"{label} produksi/template ditolak")
    return candidate


def assert_dsn_has_explicit_database(psycopg2: Any, dsn: str, target_database: str) -> None:
    try:
        params = psycopg2.extensions.parse_dsn(dsn)
    except Exception as exc:  # parse_dsn exposes driver-specific exception types
        raise GuardError("--dsn PostgreSQL tidak dapat diparse") from exc
    supplied_db = clean(params.get("dbname"))
    if supplied_db is None:
        raise GuardError("--dsn wajib menyebutkan database target secara eksplisit")
    if supplied_db != target_database:
        raise GuardError("dbname pada --dsn harus sama persis dengan --target-database")
    assert_clean_target_database_name(supplied_db, label="dbname pada --dsn")


def connect_checked(args: argparse.Namespace, *, readonly: bool) -> tuple[Any, Any]:
    psycopg2 = require_psycopg2()
    assert_dsn_has_explicit_database(psycopg2, args.dsn, args.target_database)
    try:
        conn = psycopg2.connect(args.dsn, application_name="budimas-clean-master-importer")
    except Exception as exc:
        raise GuardError("Koneksi database clean gagal; detail DSN tidak dicetak demi keamanan") from exc

    try:
        conn.autocommit = False
        conn.set_session(isolation_level="REPEATABLE READ", readonly=readonly, autocommit=False)
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_user")
            current_database, current_user = cur.fetchone()
        if current_database != args.target_database:
            raise GuardError("current_database tidak cocok dengan --target-database")
        assert_clean_target_database_name(str(current_database), label="current_database")
        return conn, current_user
    except Exception:
        conn.close()
        raise


def query_dicts(cur: Any, sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    cur.execute(sql, params or ())
    names = [column.name if hasattr(column, "name") else column[0] for column in cur.description]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def table_exists(cur: Any, schema: str, table: str) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"{schema}.{table}",))
    return bool(cur.fetchone()[0])


def fetch_columns(cur: Any, schema: str, tables: Iterable[str]) -> dict[str, dict[str, TargetColumn]]:
    table_list = list(tables)
    if not table_list:
        return {}
    rows = query_dicts(
        cur,
        """
        SELECT table_name, column_name, data_type, udt_name, is_nullable,
               column_default, is_identity, is_generated,
               character_maximum_length
          FROM information_schema.columns
         WHERE table_schema = %s
           AND table_name = ANY(%s)
         ORDER BY table_name, ordinal_position
        """,
        (schema, table_list),
    )
    result: dict[str, dict[str, TargetColumn]] = defaultdict(dict)
    for row in rows:
        table = str(row["table_name"])
        result[table][str(row["column_name"])] = TargetColumn(
            table=table,
            name=str(row["column_name"]),
            data_type=str(row["data_type"]),
            udt_name=str(row["udt_name"]),
            nullable=row["is_nullable"] == "YES",
            default=clean(row["column_default"]),
            is_identity=row["is_identity"] == "YES",
            is_generated=row["is_generated"] != "NEVER",
            max_length=row["character_maximum_length"],
        )
    return dict(result)


def observed_target_baselines(cur: Any) -> tuple[str | None, str | None, list[Mapping[str, Any]]]:
    """Fingerprint the concrete public baseline used by the importer.

    The command-line SHA arguments are not trusted declarations.  A dry run
    emits these observed values, the one-time clean-target attestation stores
    them, and ``--apply`` requires all three values to match.  Registry DDL is
    intentionally not in this fingerprint: the registry extension is applied
    *after* cloning the public ERP baseline and has its own strict contract.
    """

    blockers: list[Mapping[str, Any]] = []
    missing = [table for table in PUBLIC_IMPORT_TABLES if not table_exists(cur, "public", table)]
    if missing:
        blockers.append(
            report_blocker(
                "baseline_public_table_missing",
                "Tidak dapat menghitung baseline karena tabel public yang dipakai importer tidak lengkap.",
                missing=missing,
            )
        )
        return None, None, blockers

    column_rows = query_dicts(
        cur,
        """
        SELECT table_name, column_name, data_type, udt_name, is_nullable,
               column_default, is_identity, is_generated,
               character_maximum_length, ordinal_position
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = ANY(%s)
         ORDER BY table_name, ordinal_position
        """,
        (list(PUBLIC_IMPORT_TABLES),),
    )
    constraint_rows = query_dicts(
        cur,
        """
        SELECT c.relname AS table_name, con.conname, con.contype,
               pg_get_constraintdef(con.oid, true) AS definition
          FROM pg_constraint con
          JOIN pg_class c ON c.oid = con.conrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public'
           AND c.relname = ANY(%s)
         ORDER BY c.relname, con.conname
        """,
        (list(PUBLIC_IMPORT_TABLES),),
    )
    index_rows = query_dicts(
        cur,
        """
        SELECT c.relname AS table_name, i.relname AS index_name,
               ix.indisprimary, ix.indisunique,
               pg_get_indexdef(ix.indexrelid) AS definition
          FROM pg_index ix
          JOIN pg_class c ON c.oid = ix.indrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
          JOIN pg_class i ON i.oid = ix.indexrelid
         WHERE n.nspname = 'public'
           AND c.relname = ANY(%s)
         ORDER BY c.relname, i.relname
        """,
        (list(PUBLIC_IMPORT_TABLES),),
    )
    schema_sha = stable_hash(
        {
            "algorithm": "public-import-contract-v1",
            "tables": list(PUBLIC_IMPORT_TABLES),
            "columns": column_rows,
            "constraints": constraint_rows,
            "indexes": index_rows,
        }
    )

    reference_specs = (
        ("perusahaan", ("id", "kode")),
        ("cabang", ("id", "kode")),
        ("perusahaan_cabang", ("id", "id_perusahaan", "id_cabang")),
        ("produk_tipe_harga", ("id", "kode")),
        ("sales_tipe", ("id", "nama")),
        ("jabatan", ("id", "kode")),
    )
    references: dict[str, list[dict[str, Any]]] = {}
    for table, fields in reference_specs:
        available = fetch_columns(cur, "public", {table}).get(table, {})
        missing_fields = [field for field in fields if field not in available]
        if missing_fields:
            blockers.append(
                report_blocker(
                    "baseline_reference_column_missing",
                    "Tidak dapat menghitung baseline referensi karena kolom lookup tidak lengkap.",
                    table=table,
                    missing=missing_fields,
                )
            )
            continue
        selected = ", ".join(qident(field) for field in fields)
        ordering = ", ".join(qident(field) for field in fields)
        references[table] = query_dicts(cur, f"SELECT {selected} FROM {qtable('public', table)} ORDER BY {ordering}")
    if blockers:
        return schema_sha, None, blockers
    reference_sha = stable_hash({"algorithm": "public-import-reference-v1", "references": references})
    return schema_sha, reference_sha, blockers


def assert_no_unmodeled_unique_indexes(cur: Any, blockers: list[Mapping[str, Any]]) -> None:
    """Reject a future target uniqueness contract until it is mapped explicitly.

    The current clean target has only primary keys on the imported tables.  A
    new unique index can change whether source-qualified identities fit in a
    single public display column, so proceeding generically would be unsafe.
    """

    imported_tables = (
        "principal",
        "customer",
        "users",
        "sales",
        "sales_detail",
        "sales_principal_assignment",
        "produk",
        "produk_uom",
        "produk_harga_jual",
        "plafon",
    )
    rows = query_dicts(
        cur,
        """
        SELECT c.relname AS table_name, i.relname AS index_name,
               pg_get_indexdef(ix.indexrelid) AS definition
          FROM pg_index ix
          JOIN pg_class c ON c.oid = ix.indrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
          JOIN pg_class i ON i.oid = ix.indexrelid
         WHERE n.nspname = 'public'
           AND c.relname = ANY(%s)
           AND ix.indisunique
           AND NOT ix.indisprimary
         ORDER BY c.relname, i.relname
        """,
        (list(imported_tables),),
    )
    for row in rows:
        blockers.append(
            report_blocker(
                "target_unique_index_unmodeled",
                "Target memiliki unique index non-primary yang belum mempunyai preflight collision eksplisit.",
                table=row["table_name"],
                index=row["index_name"],
                definition=row["definition"],
            )
        )


def require_columns(
    blockers: list[Mapping[str, Any]],
    columns: Mapping[str, Mapping[str, TargetColumn]],
    table: str,
    required: Mapping[str, set[str] | None],
    *,
    schema: str = "public",
) -> None:
    actual = columns.get(table)
    if actual is None:
        blockers.append(report_blocker("target_table_missing", f"Tabel {schema}.{table} tidak ditemukan", table=table))
        return
    for column, allowed_types in required.items():
        item = actual.get(column)
        if item is None:
            blockers.append(
                report_blocker(
                    "target_column_missing",
                    f"Kolom {schema}.{table}.{column} tidak ditemukan",
                    table=table,
                    column=column,
                )
            )
        elif allowed_types is not None and item.udt_name not in allowed_types:
            blockers.append(
                report_blocker(
                    "target_column_type_unexpected",
                    f"Kolom {schema}.{table}.{column} bertipe {item.udt_name}, bukan kontrak importer",
                    table=table,
                    column=column,
                    actual_type=item.udt_name,
                    allowed_types=sorted(allowed_types),
                )
            )


def unexpected_required_columns(
    columns: Mapping[str, Mapping[str, TargetColumn]],
    table: str,
    supplied: set[str],
    blockers: list[Mapping[str, Any]],
) -> None:
    for name, column in columns.get(table, {}).items():
        if column.needs_insert_value and name not in supplied:
            blockers.append(
                report_blocker(
                    "target_required_column_unmapped",
                    f"{table}.{name} wajib diisi tetapi importer tidak memiliki semantik aman",
                    table=table,
                    column=name,
                )
            )


def inspect_target_contract(cur: Any) -> tuple[dict[str, dict[str, TargetColumn]], list[Mapping[str, Any]]]:
    """Read the current ERP/registry contract and return apply blockers.

    The importer intentionally validates concrete columns rather than relying
    on a historical local dump.  A changed schema should produce a clear dry
    run report and stop apply, never silently adapt a semantic mapping.
    """

    blockers: list[Mapping[str, Any]] = []
    public_tables = set(PUBLIC_IMPORT_TABLES)
    columns = fetch_columns(cur, "public", public_tables)
    require_columns(blockers, columns, "perusahaan", {"id": {"int4"}, "kode": {"varchar"}})
    require_columns(blockers, columns, "cabang", {"id": {"int4"}, "kode": {"varchar"}})
    require_columns(
        blockers,
        columns,
        "perusahaan_cabang",
        {"id": {"int4"}, "id_perusahaan": {"int4"}, "id_cabang": {"int4"}},
    )
    require_columns(
        blockers,
        columns,
        "principal",
        {
            "id": {"int4"},
            "id_perusahaan": {"int4"},
            "kode": {"varchar"},
            "nama": {"varchar"},
            "alamat": {"text", "varchar"},
            "telepon": {"varchar"},
            "npwp": {"varchar"},
            "no_rekening": {"varchar"},
            "pic": {"varchar"},
            "aktif": {"bool"},
        },
    )
    for table, column in (("sales", "id_user"), ("plafon", "id_user")):
        item = columns.get(table, {}).get(column)
        if item is not None and not item.nullable:
            blockers.append(
                report_blocker(
                    "target_nonlogin_user_column_not_nullable",
                    "Historical master phase menulis id_user NULL agar tidak membuat akun login; target harus mengizinkannya.",
                    table=table,
                    column=column,
                )
            )
    require_columns(
        blockers,
        columns,
        "customer",
        {
            "id": {"int4"},
            "id_cabang": {"int4"},
            "kode": {"varchar"},
            "nama": {"varchar"},
            "alamat": {"varchar", "text"},
            "telepon": {"varchar"},
            "npwp": {"varchar"},
            "pic": {"varchar"},
            "longitude": {"varchar", "text"},
            "latitude": {"varchar", "text"},
            "email": {"varchar"},
            "nama_wajib_pajak": {"varchar", "text"},
            "alamat_wajib_pajak": {"varchar", "text"},
            "id_tipe_harga": {"int4"},
            "is_ppn": {"int4"},
        },
    )
    require_columns(
        blockers,
        columns,
        "users",
        {
            "id": {"int4"},
        },
    )
    require_columns(blockers, columns, "sales", {"id": {"int4"}, "id_user": {"int4"}, "id_principal": {"int4"}, "id_tipe": {"int2"}})
    require_columns(blockers, columns, "sales_detail", {"id": {"int4"}, "id_sales": {"int4"}, "kode_sales": {"varchar"}})
    require_columns(
        blockers,
        columns,
        "sales_principal_assignment",
        {"id": {"int4"}, "id_sales": {"int4"}, "id_principal": {"int4"}},
    )
    require_columns(
        blockers,
        columns,
        "produk",
        {
            "id": {"int8"},
            "id_principal": {"int4"},
            "kode_sku": {"varchar"},
            "nama": {"varchar"},
            "satuan": {"varchar"},
            "harga_beli": {"float8"},
            "harga_jual": {"float8"},
            "keterangan": {"varchar", "text"},
            "ppn": {"float8"},
        },
    )
    require_columns(
        blockers,
        columns,
        "produk_uom",
        {
            "id": {"int4"},
            "id_produk": {"int4"},
            "kode": {"varchar"},
            "nama": {"varchar"},
            "level": {"int2"},
            "packing_satuan": {"varchar"},
            "faktor_konversi": {"int4"},
            "set_default_sales": {"int2"},
            "set_default_storage": {"int2"},
        },
    )
    require_columns(
        blockers,
        columns,
        "produk_harga_jual",
        {"id": {"int4"}, "id_produk": {"int4"}, "id_tipe_harga": {"int4"}, "harga": {"float8"}},
    )
    require_columns(blockers, columns, "produk_tipe_harga", {"id": {"int4"}, "kode": {"varchar"}})
    require_columns(blockers, columns, "sales_tipe", {"id": {"int4"}, "nama": {"varchar"}})
    require_columns(blockers, columns, "jabatan", {"id": {"int4"}, "kode": {"varchar"}})
    require_columns(
        blockers,
        columns,
        "plafon",
        {
            "id": {"int4"},
            "id_customer": {"int4"},
            "id_principal": {"int4"},
            "id_sales": {"int4"},
            "id_user": {"int4"},
            "id_tipe_harga": {"int4"},
            "limit_bon": {"float8"},
            "sisa_bon": {"float8"},
            "top": {"int2"},
            "lock_order": {"varchar"},
            "tempo": {"int4"},
        },
    )

    # We write only these documented columns.  New NOT NULL/no-default columns
    # must receive an explicit semantic mapping, not a generic NULL/default.
    unexpected_required_columns(
        columns,
        "principal",
        {"id", "nama", "alamat", "telepon", "npwp", "no_rekening", "pic", "id_perusahaan", "kode", "aktif"},
        blockers,
    )
    unexpected_required_columns(
        columns,
        "customer",
        {
            "id", "nama", "alamat", "telepon", "npwp", "id_cabang", "pic", "longitude", "latitude", "kode", "email",
            "nama_wajib_pajak", "alamat_wajib_pajak", "id_tipe_harga", "is_ppn",
        },
        blockers,
    )
    # User rows are intentionally not imported in the historical master
    # phase.  The target's current auth schema has no disabled/non-login
    # contract, so its non-key columns are not part of this write contract.
    unexpected_required_columns(columns, "sales", {"id", "id_user", "id_principal", "id_tipe"}, blockers)
    unexpected_required_columns(columns, "sales_detail", {"id", "id_sales", "kode_sales"}, blockers)
    unexpected_required_columns(columns, "sales_principal_assignment", {"id", "id_sales", "id_principal"}, blockers)
    unexpected_required_columns(
        columns,
        "produk",
        {"id", "id_principal", "kode_sku", "nama", "satuan", "harga_beli", "harga_jual", "keterangan", "ppn"},
        blockers,
    )
    unexpected_required_columns(
        columns,
        "produk_uom",
        {
            "id", "id_produk", "kode", "nama", "level", "packing_satuan",
            "faktor_konversi", "set_default_sales", "set_default_storage",
        },
        blockers,
    )
    unexpected_required_columns(columns, "produk_harga_jual", {"id", "id_produk", "id_tipe_harga", "harga"}, blockers)
    unexpected_required_columns(
        columns,
        "plafon",
        {
            "id", "id_customer", "id_principal", "id_sales", "id_user", "id_tipe_harga",
            "limit_bon", "sisa_bon", "top", "lock_order", "tempo", "tempo_label",
        },
        blockers,
    )

    assert_no_unmodeled_unique_indexes(cur, blockers)

    registry_tables = {
        "source_context",
        "clean_target_attestation",
        "import_run",
        "principal_source_map",
        "customer_source_map",
        "sales_source_map",
        "product_source_map",
        "product_uom_source_map",
        "import_hold",
        "reconciliation_result",
    }
    registry_columns = fetch_columns(cur, REGISTRY_SCHEMA, registry_tables)
    for table in registry_tables:
        if table not in registry_columns:
            blockers.append(
                report_blocker("registry_table_missing", f"DDL clean registry belum lengkap: {REGISTRY_SCHEMA}.{table}", table=table)
            )

    if table_exists(cur, REGISTRY_SCHEMA, "clean_target_attestation"):
        attestation_columns = fetch_columns(cur, REGISTRY_SCHEMA, {"clean_target_attestation"})
        require_columns(
            blockers,
            attestation_columns,
            "clean_target_attestation",
            {
                "target_database": {"text"},
                "target_kind": {"text"},
                "baseline_schema_sha256": {"text"},
                "baseline_reference_sha256": {"text"},
            },
            schema=REGISTRY_SCHEMA,
        )

    # These columns are the base DDL contract the importer actually writes.
    require_columns(
        blockers,
        registry_columns,
        "product_uom_source_map",
        {
            "import_run_id": {"int8"},
            "source_system": {"text"},
            "source_staging_id": {"int8"},
            "source_uom_code_norm": {"text"},
            "source_uom_level": {"int2"},
            "source_uom_ordinal": {"int2"},
            "source_factor": {"int4"},
            "id_produk": {"int8"},
            "id_produk_uom": {"int4"},
        },
        schema=REGISTRY_SCHEMA,
    )
    require_columns(
        blockers,
        registry_columns,
        "sales_source_map",
        {
            "import_run_id": {"int8"},
            "source_system": {"text"},
            "source_staging_id": {"int8"},
            "source_principal_code_norm": {"text"},
            "source_sales_code_norm": {"text"},
            "id_sales": {"int4"},
            "id_user": {"int4"},
        },
        schema=REGISTRY_SCHEMA,
    )
    sales_map_user = registry_columns.get("sales_source_map", {}).get("id_user")
    if sales_map_user is not None and not sales_map_user.nullable:
        blockers.append(
            report_blocker(
                "registry_sales_map_user_not_nullable",
                "Historical master phase tidak membuat akun login; sales_source_map.id_user harus nullable.",
            )
        )

    # Two explicit gaps/contradictions are detected from the actual DDL instead
    # of hard-coding an assumption about a future revision.
    if not table_exists(cur, REGISTRY_SCHEMA, "product_price_source_map"):
        blockers.append(
            report_blocker(
                "registry_product_price_map_missing",
                "Tidak ada product_price_source_map; harga tidak dapat diaudit/idempoten per source.",
            )
        )
    else:
        registry_columns = fetch_columns(cur, REGISTRY_SCHEMA, {"product_price_source_map"})
        require_columns(
            blockers,
            registry_columns,
            "product_price_source_map",
            {
                "import_run_id": {"int8"},
                "source_system": {"text"},
                "source_staging_id": {"int8"},
                "source_price_column_norm": {"text"},
                "target_price_type_code_norm": {"text"},
                "source_price": {"numeric"},
                "id_produk": {"int8"},
                "id_produk_harga_jual": {"int4"},
            },
            schema=REGISTRY_SCHEMA,
        )
    if not table_exists(cur, REGISTRY_SCHEMA, "plafon_source_map"):
        blockers.append(
            report_blocker(
                "registry_plafon_map_missing",
                "Tidak ada plafon_source_map; plafon tidak dapat diulang atau direkonsiliasi per source.",
            )
        )
    else:
        registry_columns = fetch_columns(cur, REGISTRY_SCHEMA, {"plafon_source_map"})
        require_columns(
            blockers,
            registry_columns,
            "plafon_source_map",
            {
                "import_run_id": {"int8"},
                "source_system": {"text"},
                "source_staging_id": {"int8"},
                "source_customer_code_norm": {"text"},
                "source_principal_code_norm": {"text"},
                "source_sales_code_norm": {"text"},
                "source_added_at_raw": {"text"},
                "source_added_at": {"timestamptz"},
                "source_limit_bon": {"numeric"},
                "source_term": {"int4"},
                "opening_balance_strategy": {"text"},
                "id_plafon": {"int4"},
            },
            schema=REGISTRY_SCHEMA,
        )

    if table_exists(cur, REGISTRY_SCHEMA, "product_uom_source_map"):
        rows = query_dicts(
            cur,
            """
            SELECT indexrelid::regclass::text AS index_name,
                   array_agg(a.attname ORDER BY ord.n) AS columns
              FROM pg_index i
              JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS ord(attnum, n) ON true
              JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ord.attnum
             WHERE i.indrelid = %s::regclass
               AND i.indisunique
             GROUP BY indexrelid
            """,
            (f"{REGISTRY_SCHEMA}.product_uom_source_map",),
        )
        source_row_identity = {"source_system", "source_table", "source_stage_schema", "source_staging_id"}
        source_row_uom_identity = source_row_identity | {"source_uom_ordinal"}
        has_uom_ordinal_identity = False
        for row in rows:
            index_columns = set(row["columns"] or [])
            if index_columns == source_row_identity:
                blockers.append(
                    report_blocker(
                        "registry_uom_multirow_contract_conflict",
                        "Unique key product_uom_source_map hanya memakai satu staging row, padahal STOK satu baris menghasilkan PCS dan CT.",
                        index=str(row["index_name"]),
                    )
                )
                break
            if index_columns == source_row_uom_identity:
                has_uom_ordinal_identity = True
        if not has_uom_ordinal_identity:
            blockers.append(
                report_blocker(
                    "registry_uom_source_ordinal_identity_missing",
                    "Registry UOM harus memiliki unique identity source staging row + source_uom_ordinal.",
                )
            )
    return columns, blockers


def verify_clean_target_attestation(
    cur: Any,
    *,
    target_database: str,
    observed_schema_sha256: str | None,
    observed_reference_sha256: str | None,
) -> list[Mapping[str, Any]]:
    """Require the immutable marker produced by the clean registry extension."""

    blockers: list[Mapping[str, Any]] = []
    if observed_schema_sha256 is None or observed_reference_sha256 is None:
        blockers.append(
            report_blocker(
                "clean_target_attestation_not_verifiable",
                "Fingerprint baseline target belum dapat dihitung; marker clean tidak bisa dipercaya.",
            )
        )
        return blockers
    if not table_exists(cur, REGISTRY_SCHEMA, "clean_target_attestation"):
        blockers.append(
            report_blocker(
                "clean_target_attestation_missing",
                "Target belum memiliki marker immutable clean_target_attestation dari extension registry.",
            )
        )
        return blockers
    rows = query_dicts(
        cur,
        f"""
        SELECT target_database, target_kind, baseline_schema_sha256,
               baseline_reference_sha256
          FROM {qtable(REGISTRY_SCHEMA, 'clean_target_attestation')}
        """,
    )
    if len(rows) != 1:
        blockers.append(
            report_blocker(
                "clean_target_attestation_ambiguous",
                "clean_target_attestation harus berisi tepat satu marker immutable.",
                row_count=len(rows),
            )
        )
        return blockers
    marker = rows[0]
    if clean(marker.get("target_database")) != target_database or clean(marker.get("target_kind")) != "bluegreen_clean":
        blockers.append(
            report_blocker(
                "clean_target_attestation_identity_mismatch",
                "Marker target clean tidak cocok dengan database yang tersambung.",
                marker_database=clean(marker.get("target_database")),
                marker_kind=clean(marker.get("target_kind")),
            )
        )
    marker_schema = clean(marker.get("baseline_schema_sha256"))
    marker_reference = clean(marker.get("baseline_reference_sha256"))
    if marker_schema != observed_schema_sha256:
        blockers.append(
            report_blocker(
                "clean_target_attestation_schema_mismatch",
                "Schema public saat ini tidak sama dengan baseline yang di-attest pada target clean.",
                observed_schema_sha256=observed_schema_sha256,
                marker_schema_sha256=marker_schema,
            )
        )
    if marker_reference != observed_reference_sha256:
        blockers.append(
            report_blocker(
                "clean_target_attestation_reference_mismatch",
                "Reference baseline saat ini tidak sama dengan marker target clean.",
                observed_reference_sha256=observed_reference_sha256,
                marker_reference_sha256=marker_reference,
            )
        )
    return blockers


def stage_required_columns() -> Mapping[str, set[str]]:
    fixed = {"staging_id", "source_system", "target_company_id", "target_branch_id", "legacy_table", "source_row_hash"}
    return {
        "principle": fixed | {"kode", "nama", "alamat", "telpon", "npwp", "account", "contactperson", "active"},
        "customer": fixed | {"kode", "nama", "alamat", "telpon", "npwp", "contactperson", "email", "namawp", "alamatwp", "longitude", "latitude", "opsharga", "fp"},
        "sales": fixed | {"kode", "nama", "kodeprinciple", "type", "jenisitr"},
        "stok": fixed | {"kode", "nama", "principle", "satuan", "namaunit", "perunit", "hargaa", "hargab", "hargac", "hargad", "hargae", "fakturpajak"},
        "plafon": fixed | {"kodecustomer", "kodeprinciple", "kodesales", "plafon", "term", "tgladd"},
        "barangsatuan": fixed | {"kode", "nama"},
    }


def resolve_expected_stage_context(
    cur: Any,
    config: SourceConfig,
    structural_blockers: list[Mapping[str, Any]],
) -> tuple[int, int] | None:
    """Resolve current public IDs only to validate frozen staging scope.

    IDs are deliberately read from the target baseline at runtime.  They are
    never copied from policy or hard-coded into the importer.
    """

    required_tables = ("perusahaan", "cabang", "perusahaan_cabang")
    if not all(table_exists(cur, "public", table) for table in required_tables):
        return None
    rows = query_dicts(
        cur,
        """
        SELECT p.id AS company_id, b.id AS branch_id
          FROM public.perusahaan p
          JOIN public.perusahaan_cabang pc ON pc.id_perusahaan = p.id
          JOIN public.cabang b ON b.id = pc.id_cabang
         WHERE lower(btrim(p.kode)) = lower(btrim(%s))
           AND lower(btrim(b.kode)) = lower(btrim(%s))
        """,
        (config.company_code, config.branch_code),
    )
    if len(rows) != 1:
        structural_blockers.append(
            report_blocker(
                "stage_scope_context_not_exact",
                "Kode perusahaan/cabang policy harus meresolusi tepat satu pair sebelum scope staging dipercaya.",
                source_system=config.source_system,
                company_code=config.company_code,
                branch_code=config.branch_code,
                candidate_count=len(rows),
            )
        )
        return None
    return int(rows[0]["company_id"]), int(rows[0]["branch_id"])


def as_manifest_columns(value: Any) -> set[str] | None:
    """Normalize the JSON array recorded by the staging exporter."""

    candidate = value
    if isinstance(candidate, str):
        try:
            candidate = json.loads(candidate)
        except json.JSONDecodeError:
            return None
    if not isinstance(candidate, list) or not all(isinstance(item, str) for item in candidate):
        return None
    return {item.strip().lower() for item in candidate if item.strip()}


def as_manifest_selection(value: Any) -> Mapping[str, Any] | None:
    candidate = value
    if isinstance(candidate, str):
        try:
            candidate = json.loads(candidate)
        except json.JSONDecodeError:
            return None
    return candidate if isinstance(candidate, Mapping) else None


def validate_stage_manifest_and_scope(
    cur: Any,
    *,
    config: SourceConfig,
    source_columns: Mapping[str, Mapping[str, TargetColumn]],
    table_counts: Mapping[str, int],
    structural_blockers: list[Mapping[str, Any]],
) -> str:
    """Validate completed full-table manifest and row scope for every source.

    A row hash proves the individual content but not that the exporter staged
    the intended table, source system, or BMM/TMP+Solo scope.  The manifest
    and staging metadata provide that missing evidence and are folded into the
    stage snapshot fingerprint.
    """

    expected_context = resolve_expected_stage_context(cur, config, structural_blockers)
    manifest_rows = query_dicts(
        cur,
        f"""
        SELECT legacy_table, module, selection, source_columns,
               source_row_count, staged_row_count, status,
               started_at, finished_at, error
          FROM {qtable(config.stage_schema, '__stage_manifest')}
         WHERE lower(btrim(legacy_table)) = ANY(%s)
         ORDER BY lower(btrim(legacy_table)), legacy_table
        """,
        (list(SOURCE_TABLES),),
    )
    by_table: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in manifest_rows:
        legacy_table_norm = norm(row.get("legacy_table"))
        if legacy_table_norm is not None:
            by_table[legacy_table_norm].append(row)

    evidence: list[Mapping[str, Any]] = []
    for table in SOURCE_TABLES:
        rows = by_table.get(table, [])
        if len(rows) != 1:
            structural_blockers.append(
                report_blocker(
                    "stage_manifest_table_not_exact",
                    "Manifest staging harus memiliki tepat satu entry untuk setiap tabel master yang diimpor.",
                    source_system=config.source_system,
                    table=table,
                    entry_count=len(rows),
                )
            )
            continue
        row = rows[0]
        selection = as_manifest_selection(row.get("selection"))
        source_manifest_columns = as_manifest_columns(row.get("source_columns"))
        source_count, source_count_problem = parse_int(row.get("source_row_count"), "manifest_source_row_count", minimum=0)
        staged_count, staged_count_problem = parse_int(row.get("staged_row_count"), "manifest_staged_row_count", minimum=0)
        if norm(row.get("module")) != "masters":
            structural_blockers.append(
                report_blocker("stage_manifest_module_unexpected", "Manifest master harus berasal dari module masters.", source_system=config.source_system, table=table, actual=row.get("module")))
        if norm(row.get("status")) != "done":
            structural_blockers.append(
                report_blocker("stage_manifest_not_done", "Manifest table belum berstatus done.", source_system=config.source_system, table=table, actual=row.get("status")))
        if selection is None or norm(selection.get("mode")) != "all":
            structural_blockers.append(
                report_blocker("stage_manifest_not_full_table", "Master staging harus memakai selection.mode=all, bukan subset/preview.", source_system=config.source_system, table=table, selection=selection))
        source_business_columns = stage_required_columns()[table] - {
            "staging_id", "source_system", "target_company_id", "target_branch_id", "legacy_table", "source_row_hash"
        }
        if source_manifest_columns is None or not source_business_columns <= source_manifest_columns:
            structural_blockers.append(
                report_blocker(
                    "stage_manifest_source_columns_incomplete",
                    "Manifest tidak membuktikan seluruh kolom sumber yang dipakai importer.",
                    source_system=config.source_system,
                    table=table,
                    missing=sorted(source_business_columns - (source_manifest_columns or set())),
                )
            )
        if source_count_problem or staged_count_problem or source_count is None or staged_count is None:
            structural_blockers.append(
                report_blocker("stage_manifest_count_invalid", "Count manifest tidak valid.", source_system=config.source_system, table=table))
        elif source_count != staged_count or staged_count != table_counts.get(table):
            structural_blockers.append(
                report_blocker(
                    "stage_manifest_count_mismatch",
                    "Count source/manifest/actual staging harus sama.",
                    source_system=config.source_system,
                    table=table,
                    source_row_count=source_count,
                    staged_row_count=staged_count,
                    actual_table_count=table_counts.get(table),
                )
            )

        # Do aggregate validation rather than trusting the table name alone:
        # every frozen row must carry exactly the planned source+context scope.
        if table not in source_columns:
            continue
        scope_rows = query_dicts(
            cur,
            f"""
            SELECT source_system, legacy_table, target_company_id, target_branch_id,
                   count(*) AS row_count
              FROM {qtable(config.stage_schema, table)}
             GROUP BY source_system, legacy_table, target_company_id, target_branch_id
             ORDER BY source_system, legacy_table, target_company_id, target_branch_id
            """,
        )
        observed_company_id, company_id_problem = (
            parse_int(scope_rows[0].get("target_company_id"), "stage_target_company_id", minimum=1)
            if len(scope_rows) == 1
            else (None, "scope_not_singleton")
        )
        observed_branch_id, branch_id_problem = (
            parse_int(scope_rows[0].get("target_branch_id"), "stage_target_branch_id", minimum=1)
            if len(scope_rows) == 1
            else (None, "scope_not_singleton")
        )
        observed_row_count, row_count_problem = (
            parse_int(scope_rows[0].get("row_count"), "stage_scope_row_count", minimum=0)
            if len(scope_rows) == 1
            else (None, "scope_not_singleton")
        )
        valid_scope = (
            len(scope_rows) == 1
            and clean(scope_rows[0].get("source_system")) == config.source_system
            and norm(scope_rows[0].get("legacy_table")) == table
            and expected_context is not None
            and company_id_problem is None
            and branch_id_problem is None
            and row_count_problem is None
            and observed_company_id == expected_context[0]
            and observed_branch_id == expected_context[1]
            and observed_row_count == table_counts.get(table)
        )
        # Empty full-table exports have no scope rows.  They remain valid only
        # when manifest count proves the table was intentionally empty.
        if not scope_rows and table_counts.get(table) == 0:
            valid_scope = True
        if not valid_scope:
            structural_blockers.append(
                report_blocker(
                    "stage_row_scope_mismatch",
                    "Setiap row staging harus memiliki source_system, legacy_table, dan target company/cabang sesuai policy.",
                    source_system=config.source_system,
                    table=table,
                    expected_company_id=expected_context[0] if expected_context else None,
                    expected_branch_id=expected_context[1] if expected_context else None,
                    observed_scope=scope_rows[:10],
                )
            )
        evidence.append(
            {
                "table": table,
                "legacy_table": row.get("legacy_table"),
                "module": row.get("module"),
                "selection": selection,
                "source_columns": sorted(source_manifest_columns or []),
                "source_row_count": source_count,
                "staged_row_count": staged_count,
                "status": row.get("status"),
                "started_at": row.get("started_at"),
                "finished_at": row.get("finished_at"),
                "error": row.get("error"),
                "scope_rows": scope_rows,
            }
        )
    return stable_hash({"source_system": config.source_system, "manifest": evidence})


def resolve_stage_info(
    cur: Any,
    config: SourceConfig,
    expected_run_id: int | None,
    structural_blockers: list[Mapping[str, Any]],
) -> StageInfo | None:
    schema = config.stage_schema
    if not table_exists(cur, schema, "__stage_run"):
        structural_blockers.append(report_blocker("stage_metadata_missing", f"{schema}.__stage_run tidak ditemukan", source_system=config.source_system))
        return None
    if not table_exists(cur, schema, "__stage_manifest"):
        structural_blockers.append(report_blocker("stage_manifest_missing", f"{schema}.__stage_manifest tidak ditemukan", source_system=config.source_system))
        return None

    candidate_rows = query_dicts(
        cur,
        f"""
        SELECT id, source_system, consistency_mode, is_preview,
               maintenance_window_id, maintenance_freeze_attested,
               maintenance_freeze_confirmed_at, source_transaction_isolation,
               status, target_company_code, target_branch_code
          FROM {qtable(schema, '__stage_run')}
         WHERE status = 'completed'
           AND is_preview = false
         ORDER BY id DESC
        """,
    )
    if expected_run_id is not None:
        candidate_rows = [row for row in candidate_rows if int(row["id"]) == expected_run_id]
    if len(candidate_rows) != 1:
        structural_blockers.append(
            report_blocker(
                "stage_run_ambiguous",
                "Harus ada tepat satu stage run completed non-preview (atau pilih dengan --*-stage-run-id).",
                source_system=config.source_system,
                candidate_count=len(candidate_rows),
            )
        )
        return None
    row = candidate_rows[0]
    source_system = clean(row["source_system"])
    mode = clean(row["consistency_mode"])
    company_code = clean(row["target_company_code"])
    branch_code = clean(row["target_branch_code"])
    if source_system != config.source_system:
        structural_blockers.append(report_blocker("stage_source_system_mismatch", "source_system stage tidak sama dengan policy", expected=config.source_system, actual=source_system))
    if norm(company_code) != norm(config.company_code) or norm(branch_code) != norm(config.branch_code):
        structural_blockers.append(
            report_blocker(
                "stage_context_code_mismatch",
                "Kode perusahaan/cabang stage tidak sama dengan clean policy.",
                source_system=config.source_system,
                expected_company=config.company_code,
                actual_company=company_code,
                expected_branch=config.branch_code,
                actual_branch=branch_code,
            )
        )
    if mode not in {"snapshot", "maintenance_freeze_serializable"}:
        structural_blockers.append(report_blocker("stage_consistency_unsupported", "consistency_mode stage tidak aman untuk import", source_system=config.source_system, actual=mode))
    if mode == "maintenance_freeze_serializable" and not bool(row["maintenance_freeze_attested"]):
        structural_blockers.append(report_blocker("stage_freeze_not_attested", "Stage maintenance freeze belum di-attest", source_system=config.source_system))

    source_columns = fetch_columns(cur, schema, SOURCE_TABLES)
    for table, required in stage_required_columns().items():
        actual = source_columns.get(table, {})
        missing = sorted(required - set(actual))
        if missing:
            structural_blockers.append(
                report_blocker(
                    "stage_columns_missing",
                    f"{schema}.{table} tidak memiliki kolom staging yang dibutuhkan.",
                    source_system=config.source_system,
                    table=table,
                    missing=missing,
                )
            )

    table_counts: dict[str, int] = {}
    digest = hashlib.sha256()
    digest.update(stable_json({"schema": schema, "run": int(row["id"]), "metadata": row}).encode("utf-8"))
    for table in SOURCE_TABLES:
        if table not in source_columns:
            continue
        cur.execute(f"SELECT staging_id, source_row_hash FROM {qtable(schema, table)} ORDER BY staging_id")
        count = 0
        for staging_id, source_row_hash in cur:
            count += 1
            hash_text = clean(source_row_hash)
            if hash_text is None or not SHA256_RE.fullmatch(hash_text.lower()):
                structural_blockers.append(
                    report_blocker(
                        "stage_row_hash_invalid",
                        "source_row_hash stage harus SHA-256 valid untuk provenance.",
                        source_system=config.source_system,
                        table=table,
                        staging_id=int(staging_id),
                    )
                )
                continue
            digest.update(f"\n{table}|{int(staging_id)}|{hash_text.lower()}".encode("ascii"))
        table_counts[table] = count
    manifest_sha = validate_stage_manifest_and_scope(
        cur,
        config=config,
        source_columns=source_columns,
        table_counts=table_counts,
        structural_blockers=structural_blockers,
    )
    digest.update(f"\nmanifest|{manifest_sha}".encode("ascii"))
    snapshot_label = f"{schema}:run-{int(row['id'])}"
    return StageInfo(
        source_system=config.source_system,
        schema=schema,
        run_id=int(row["id"]),
        consistency_mode=mode or "",
        is_preview=bool(row["is_preview"]),
        maintenance_window_id=clean(row["maintenance_window_id"]),
        maintenance_freeze_attested=bool(row["maintenance_freeze_attested"]),
        maintenance_freeze_confirmed_at=clean(row["maintenance_freeze_confirmed_at"]),
        source_transaction_isolation=clean(row["source_transaction_isolation"]),
        status=clean(row["status"]) or "",
        company_code=company_code or "",
        branch_code=branch_code or "",
        snapshot_label=snapshot_label,
        snapshot_sha256=digest.hexdigest(),
        manifest_sha256=manifest_sha,
        table_counts=table_counts,
    )


def load_stage_rows(cur: Any, stage: StageInfo, table: str, wanted_columns: Sequence[str]) -> list[StageRow]:
    select_columns = ["staging_id", "source_row_hash", *wanted_columns]
    columns_sql = ", ".join(qident(column) for column in select_columns)
    rows = query_dicts(
        cur,
        f"SELECT {columns_sql} FROM {qtable(stage.schema, table)} ORDER BY staging_id",
    )
    result: list[StageRow] = []
    for row in rows:
        staging_id, problem = parse_int(row.get("staging_id"), "staging_id", minimum=1)
        if problem or staging_id is None:
            raise ImporterError(f"{stage.schema}.{table} memiliki staging_id tidak valid")
        source_hash = clean(row.get("source_row_hash"))
        if source_hash is None or not SHA256_RE.fullmatch(source_hash.lower()):
            raise ImporterError(f"{stage.schema}.{table} staging_id={staging_id} memiliki source_row_hash tidak valid")
        values = {key: value for key, value in row.items() if key not in {"staging_id", "source_row_hash"}}
        result.append(
            StageRow(
                source_system=stage.source_system,
                schema=stage.schema,
                run_id=stage.run_id,
                table=table,
                staging_id=staging_id,
                source_row_hash=source_hash.lower(),
                values=values,
            )
        )
    return result


def add_hold(plan: MasterPlan, row: StageRow, reason: str, **details: Any) -> None:
    plan.holds.append(Hold(row=row, reason=reason, details=details))


def row_has_hold(plan: MasterPlan, row: StageRow) -> bool:
    """Whether any validation has held this exact immutable staging row."""

    return any(
        hold.row.source_system == row.source_system
        and hold.row.schema == row.schema
        and hold.row.table == row.table
        and hold.row.staging_id == row.staging_id
        for hold in plan.holds
    )


def unique_source_rows(plan: MasterPlan, rows: Iterable[StageRow], key_column: str, *, label: str) -> dict[tuple[str, str], StageRow]:
    groups: dict[tuple[str, str], list[StageRow]] = defaultdict(list)
    for row in rows:
        source_value = row.value(key_column)
        key = norm(source_value)
        if key is None:
            add_hold(plan, row, f"{label}_source_key_blank", source_column=key_column)
            continue
        groups[(row.source_system, key)].append(row)
    unique: dict[tuple[str, str], StageRow] = {}
    for key, group in groups.items():
        if len(group) != 1:
            for row in group:
                add_hold(plan, row, f"{label}_source_key_duplicate", source_column=key_column, source_key=key[1], duplicate_count=len(group))
            continue
        unique[key] = group[0]
    return unique


def unique_source_rows_by_columns(
    plan: MasterPlan,
    rows: Iterable[StageRow],
    key_columns: Sequence[str],
    *,
    label: str,
) -> dict[tuple[str, ...], StageRow]:
    """Return source rows unique for their full source-qualified key.

    Sales and product identity includes a principal.  Treating a sales code or
    SKU as globally unique within one legacy source would silently erase valid
    source identities, so the entire declared key is grouped here.
    """

    groups: dict[tuple[str, ...], list[StageRow]] = defaultdict(list)
    for row in rows:
        values = tuple(norm(row.value(column)) for column in key_columns)
        if any(value is None for value in values):
            add_hold(plan, row, f"{label}_source_key_blank", source_columns=list(key_columns))
            continue
        groups[(row.source_system, *(value for value in values if value is not None))].append(row)
    unique: dict[tuple[str, ...], StageRow] = {}
    for key, group in groups.items():
        if len(group) != 1:
            for row in group:
                add_hold(
                    plan,
                    row,
                    f"{label}_source_key_duplicate",
                    source_columns=list(key_columns),
                    source_key=list(key[1:]),
                    duplicate_count=len(group),
                )
            continue
        unique[key] = group[0]
    return unique


def target_value_or_hold(
    plan: MasterPlan,
    row: StageRow,
    value: str | None,
    column: TargetColumn | None,
    field: str,
    *,
    required: bool = False,
) -> str | None:
    if required and value is None:
        add_hold(plan, row, f"{field}_blank")
        return None
    if value is not None and column is not None and too_long(value, column.max_length):
        add_hold(plan, row, f"{field}_too_long", target_column=column.name, max_length=column.max_length, actual_length=len(value))
        return None
    return value


def plan_principals(plan: MasterPlan, rows_by_source: Mapping[str, list[StageRow]], columns: Mapping[str, Mapping[str, TargetColumn]]) -> dict[tuple[str, str], PrincipalAction]:
    principal_columns = columns.get("principal", {})
    source_rows = [row for source in SOURCE_ORDER for row in rows_by_source[source]]
    unique_rows = unique_source_rows(plan, source_rows, "kode", label="principal")
    result: dict[tuple[str, str], PrincipalAction] = {}
    for key, row in sorted(unique_rows.items()):
        source_code = row.value("kode")
        source_code_norm = norm(source_code)
        assert source_code is not None and source_code_norm is not None
        name = target_value_or_hold(plan, row, row.value("nama"), principal_columns.get("nama"), "principal_name", required=True)
        code = target_value_or_hold(plan, row, source_code, principal_columns.get("kode"), "principal_code", required=True)
        active, active_problem = parse_source_active(row.value("active"))
        if active_problem:
            add_hold(plan, row, active_problem)
        if name is None or code is None or active is None:
            continue
        payload = {
            "nama": name,
            "alamat": target_value_or_hold(plan, row, row.value("alamat"), principal_columns.get("alamat"), "principal_address"),
            "telepon": target_value_or_hold(plan, row, row.value("telpon"), principal_columns.get("telepon"), "principal_phone"),
            "npwp": target_value_or_hold(plan, row, row.value("npwp"), principal_columns.get("npwp"), "principal_npwp"),
            "no_rekening": target_value_or_hold(plan, row, row.value("account"), principal_columns.get("no_rekening"), "principal_account"),
            "pic": target_value_or_hold(plan, row, row.value("contactperson"), principal_columns.get("pic"), "principal_pic"),
            "kode": code,
            "aktif": active,
        }
        if row_has_hold(plan, row):
            continue
        action = PrincipalAction(row=row, source_code=source_code, source_code_norm=source_code_norm, payload=payload)
        plan.principals.append(action)
        result[key] = action
    return result


def require_approved_subpolicy(payload: Mapping[str, Any], label: str) -> None:
    """Keep candidate/draft mappings from ever becoming an apply input."""

    status = norm(payload.get("approval_status"))
    if status != "approved":
        raise ImporterError(f"{label} harus memiliki approval_status=approved; file draft hanya untuk review")


def load_customer_pricing_tax_policy(path: Path | None) -> tuple[Mapping[str, str], Mapping[str, int]] | None:
    """Load explicit legacy customer price-type and tax-flag semantics.

    The clean policy intentionally does not guess what legacy ``OpsHarga`` A-E
    or ``FP`` values mean.  A reviewable separate policy is therefore required
    before a customer is eligible for write.
    """

    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ImporterError(f"Customer pricing/tax policy tidak ditemukan: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ImporterError(f"Customer pricing/tax policy JSON tidak valid: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ImporterError("Customer pricing/tax policy harus JSON object")
    require_approved_subpolicy(payload, "Customer pricing/tax policy")
    source_price = payload.get("source_opsharga_to_price_type_code")
    source_tax = payload.get("source_fp_to_is_ppn")
    if not isinstance(source_price, Mapping) or not isinstance(source_tax, Mapping):
        raise ImporterError(
            "Customer pricing/tax policy wajib memiliki source_opsharga_to_price_type_code dan source_fp_to_is_ppn"
        )
    price_mapping: dict[str, str] = {}
    tax_mapping: dict[str, int] = {}
    for legacy_value, target_code in source_price.items():
        legacy_norm = norm(legacy_value)
        target_code_clean = clean(target_code)
        if legacy_norm is None or target_code_clean is None:
            raise ImporterError("Customer price-type policy memiliki key/value kosong")
        price_mapping[legacy_norm] = target_code_clean
    for legacy_value, is_ppn in source_tax.items():
        legacy_norm = norm(legacy_value)
        try:
            parsed_is_ppn = int(is_ppn)
        except (TypeError, ValueError):
            parsed_is_ppn = -1
        if legacy_norm is None or isinstance(is_ppn, bool) or parsed_is_ppn not in {0, 1}:
            raise ImporterError("Customer tax policy hanya boleh memetakan nilai source ke 0 atau 1")
        tax_mapping[legacy_norm] = parsed_is_ppn
    return price_mapping, tax_mapping


def plan_customers(
    plan: MasterPlan,
    rows_by_source: Mapping[str, list[StageRow]],
    columns: Mapping[str, Mapping[str, TargetColumn]],
    customer_policy: tuple[Mapping[str, str], Mapping[str, int]] | None,
    cur: Any,
) -> dict[tuple[str, str], CustomerAction]:
    customer_columns = columns.get("customer", {})
    unique_rows = unique_source_rows(
        plan,
        [row for source in SOURCE_ORDER for row in rows_by_source[source]],
        "kode",
        label="customer",
    )
    tmp_by_exact: dict[tuple[str, str], CustomerAction] = {}
    result: dict[tuple[str, str], CustomerAction] = {}
    # TMP precedence is determined from the frozen source identity, not only
    # from rows that happened to pass a later policy check.  If the exact TMP
    # counterpart is held, BDM must be held too; it may not silently become a
    # different BDM-created customer just because TMP was incomplete.
    tmp_codes: set[str] = set()
    tmp_source_exact_keys: set[tuple[str, str]] = set()
    for row in rows_by_source["tmp_solo_dist"]:
        code_norm = norm(row.value("kode"))
        if code_norm is None:
            continue
        tmp_codes.add(code_norm)
        source_name_norm = norm(row.value("nama"))
        if source_name_norm is not None:
            tmp_source_exact_keys.add((code_norm, source_name_norm))
    resolved_price_type_ids: dict[str, int] = {}
    if customer_policy is not None:
        price_mapping, _ = customer_policy
        for target_code in set(price_mapping.values()):
            target_id = exact_reference_id(cur, "produk_tipe_harga", "kode", target_code)
            if target_id is None:
                plan.structural_blockers.append(
                    report_blocker(
                        "customer_price_type_lookup_not_exact",
                        "produk_tipe_harga.kode customer policy harus meresolusi tepat satu row.",
                        target_price_type_code=target_code,
                    )
                )
            else:
                resolved_price_type_ids[target_code] = target_id

    for source_system in SOURCE_ORDER:
        for (system, code_norm), row in sorted(unique_rows.items()):
            if system != source_system:
                continue
            source_code = row.value("kode")
            source_name = row.value("nama")
            source_name_norm = norm(source_name)
            assert source_code is not None
            if source_name is None or source_name_norm is None:
                add_hold(plan, row, "customer_store_name_blank")
                continue
            source_code_checked = target_value_or_hold(plan, row, source_code, customer_columns.get("kode"), "customer_code", required=True)
            source_name_checked = target_value_or_hold(plan, row, source_name, customer_columns.get("nama"), "customer_name", required=True)
            if source_code_checked is None or source_name_checked is None:
                continue

            exact_tmp_key = (code_norm, source_name_norm)
            is_bdm_tmp_exact_source = source_system == "bdm_solo_dist" and exact_tmp_key in tmp_source_exact_keys
            is_bdm_shared_exact = source_system == "bdm_solo_dist" and exact_tmp_key in tmp_by_exact
            if is_bdm_tmp_exact_source and not is_bdm_shared_exact:
                add_hold(
                    plan,
                    row,
                    "customer_tmp_exact_counterpart_not_planned",
                    source_customer_code=source_code,
                    source_store_name=source_name,
                )
                continue
            target_price_id: int | None = None
            mapped_tax: int | None = None
            if not is_bdm_shared_exact:
                if customer_policy is None:
                    add_hold(plan, row, "customer_price_tax_policy_missing", required="--customer-pricing-tax-policy-json")
                    continue
                price_mapping, tax_mapping = customer_policy
                source_price_type = norm(row.value("opsharga"))
                source_tax_flag = norm(row.value("fp"))
                if source_price_type not in price_mapping:
                    add_hold(plan, row, "customer_source_price_type_unmapped", source_opsharga=row.value("opsharga"))
                    continue
                if source_tax_flag not in tax_mapping:
                    add_hold(plan, row, "customer_source_tax_flag_unmapped", source_fp=row.value("fp"))
                    continue
                target_price_code = price_mapping[source_price_type]
                target_price_id = resolved_price_type_ids.get(target_price_code)
                if target_price_id is None:
                    add_hold(plan, row, "customer_target_price_type_not_resolved", target_price_type_code=target_price_code)
                    continue
                mapped_tax = tax_mapping[source_tax_flag]

            mapping_method = "tmp_created"
            shared_tmp_key: tuple[str, str] | None = None
            payload: Mapping[str, Any] | None
            if source_system == "tmp_solo_dist":
                assert target_price_id is not None and mapped_tax is not None
                payload = {
                    "nama": source_name_checked,
                    "alamat": target_value_or_hold(plan, row, row.value("alamat"), customer_columns.get("alamat"), "customer_address"),
                    "telepon": target_value_or_hold(plan, row, row.value("telpon"), customer_columns.get("telepon"), "customer_phone"),
                    "npwp": target_value_or_hold(plan, row, row.value("npwp"), customer_columns.get("npwp"), "customer_npwp"),
                    "pic": target_value_or_hold(plan, row, row.value("contactperson"), customer_columns.get("pic"), "customer_pic"),
                    "longitude": target_value_or_hold(plan, row, row.value("longitude"), customer_columns.get("longitude"), "customer_longitude"),
                    "latitude": target_value_or_hold(plan, row, row.value("latitude"), customer_columns.get("latitude"), "customer_latitude"),
                    "email": target_value_or_hold(plan, row, row.value("email"), customer_columns.get("email"), "customer_email"),
                    "nama_wajib_pajak": target_value_or_hold(plan, row, row.value("namawp"), customer_columns.get("nama_wajib_pajak"), "customer_tax_name"),
                    "alamat_wajib_pajak": target_value_or_hold(plan, row, row.value("alamatwp"), customer_columns.get("alamat_wajib_pajak"), "customer_tax_address"),
                    "kode": source_code_checked,
                    "id_tipe_harga": target_price_id,
                    "is_ppn": mapped_tax,
                }
            else:
                if is_bdm_shared_exact:
                    mapping_method = "bdm_shared_exact"
                    shared_tmp_key = exact_tmp_key
                    payload = None
                else:
                    assert target_price_id is not None and mapped_tax is not None
                    mapping_method = "bdm_created"
                    target_code = source_code_checked
                    # No global merge by code.  When BDM has the same source
                    # code but a different TMP store name, give its target
                    # display code a deterministic visible source prefix.
                    if code_norm in tmp_codes:
                        target_code = f"BDM/{source_code_checked}"
                        if too_long(target_code, customer_columns.get("kode").max_length if customer_columns.get("kode") else None):
                            add_hold(plan, row, "customer_bdm_prefixed_code_too_long", source_code=source_code_checked)
                            continue
                    payload = {
                        "nama": source_name_checked,
                        "alamat": target_value_or_hold(plan, row, row.value("alamat"), customer_columns.get("alamat"), "customer_address"),
                        "telepon": target_value_or_hold(plan, row, row.value("telpon"), customer_columns.get("telepon"), "customer_phone"),
                        "npwp": target_value_or_hold(plan, row, row.value("npwp"), customer_columns.get("npwp"), "customer_npwp"),
                        "pic": target_value_or_hold(plan, row, row.value("contactperson"), customer_columns.get("pic"), "customer_pic"),
                        "longitude": target_value_or_hold(plan, row, row.value("longitude"), customer_columns.get("longitude"), "customer_longitude"),
                        "latitude": target_value_or_hold(plan, row, row.value("latitude"), customer_columns.get("latitude"), "customer_latitude"),
                        "email": target_value_or_hold(plan, row, row.value("email"), customer_columns.get("email"), "customer_email"),
                        "nama_wajib_pajak": target_value_or_hold(plan, row, row.value("namawp"), customer_columns.get("nama_wajib_pajak"), "customer_tax_name"),
                        "alamat_wajib_pajak": target_value_or_hold(plan, row, row.value("alamatwp"), customer_columns.get("alamat_wajib_pajak"), "customer_tax_address"),
                        "kode": target_code,
                        "id_tipe_harga": target_price_id,
                        "is_ppn": mapped_tax,
                    }
            if row_has_hold(plan, row):
                continue
            action = CustomerAction(
                row=row,
                source_code=source_code,
                source_code_norm=code_norm,
                source_name=source_name,
                source_name_norm=source_name_norm,
                mapping_method=mapping_method,
                shared_tmp_key=shared_tmp_key,
                payload=payload,
            )
            result[(source_system, code_norm)] = action
            plan.customers.append(action)
            if source_system == "tmp_solo_dist":
                tmp_by_exact[(code_norm, source_name_norm)] = action
    return result


def load_sales_policy(path: Path | None) -> Mapping[str, Any] | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ImporterError(f"Sales policy tidak ditemukan: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ImporterError(f"Sales policy JSON tidak valid: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ImporterError("Sales policy harus JSON object")
    require_approved_subpolicy(payload, "Sales policy")
    required = {"source_type_to_sales_tipe_name"}
    missing = sorted(required - set(payload))
    if missing:
        raise ImporterError(f"Sales policy belum lengkap: {', '.join(missing)}")
    if not isinstance(payload["source_type_to_sales_tipe_name"], Mapping):
        raise ImporterError("sales policy source_type_to_sales_tipe_name harus object")
    fallback = payload.get("source_jenisitr_to_sales_tipe_name")
    if fallback is not None and not isinstance(fallback, Mapping):
        raise ImporterError("sales policy source_jenisitr_to_sales_tipe_name harus object bila dipakai")
    if not payload["source_type_to_sales_tipe_name"] and not fallback:
        raise ImporterError("Sales policy harus memiliki minimal satu mapping type atau jenisitr")
    return payload


def exact_reference_id(cur: Any, table: str, column: str, value: str) -> int | None:
    rows = query_dicts(
        cur,
        f"SELECT id FROM {qtable('public', table)} WHERE lower(btrim({qident(column)}::text)) = lower(btrim(%s))",
        (value,),
    )
    if len(rows) != 1:
        return None
    return int(rows[0]["id"])


def plan_sales(
    plan: MasterPlan,
    rows_by_source: Mapping[str, list[StageRow]],
    principals: Mapping[tuple[str, str], PrincipalAction],
    columns: Mapping[str, Mapping[str, TargetColumn]],
    sales_policy: Mapping[str, Any] | None,
    cur: Any,
) -> dict[tuple[str, str, str], SalesAction]:
    unique_rows = unique_source_rows_by_columns(
        plan,
        [row for source in SOURCE_ORDER for row in rows_by_source[source]],
        ("kodeprinciple", "kode"),
        label="sales",
    )
    result: dict[tuple[str, str, str], SalesAction] = {}
    if sales_policy is None:
        for row in unique_rows.values():
            add_hold(plan, row, "sales_user_policy_missing", required="--sales-policy-json")
        return result

    type_mapping = sales_policy.get("source_type_to_sales_tipe_name")
    jenisitr_mapping = sales_policy.get("source_jenisitr_to_sales_tipe_name", {})
    if not isinstance(type_mapping, Mapping) or not isinstance(jenisitr_mapping, Mapping):
        raise ImporterError("Sales policy tidak dapat dipakai")
    target_type_ids_by_type: dict[str, int] = {}
    target_type_ids_by_jenisitr: dict[str, int] = {}

    def resolve_type_mapping(
        raw_mapping: Mapping[str, Any],
        destination: dict[str, int],
        *,
        source_field: str,
    ) -> None:
        for source_value, target_name in raw_mapping.items():
            source_value_norm = norm(source_value)
            target_name_text = clean(target_name)
            if source_value_norm is None or target_name_text is None:
                raise ImporterError(f"Sales policy memiliki mapping {source_field} kosong")
            target_id = exact_reference_id(cur, "sales_tipe", "nama", target_name_text)
            if target_id is None:
                plan.structural_blockers.append(
                    report_blocker(
                        "sales_type_lookup_not_exact",
                        "Nama sales_tipe pada policy harus meresolusi tepat satu row",
                        source_field=source_field,
                        source_value=source_value,
                        target_name=target_name_text,
                    )
                )
            else:
                destination[source_value_norm] = target_id

    resolve_type_mapping(type_mapping, target_type_ids_by_type, source_field="type")
    resolve_type_mapping(jenisitr_mapping, target_type_ids_by_jenisitr, source_field="jenisitr")

    sales_detail_columns = columns.get("sales_detail", {})
    for (source_system, _source_principal_code_norm, source_sales_code_norm), row in sorted(unique_rows.items()):
        principal_code = row.value("kodeprinciple")
        principal_code_norm = norm(principal_code)
        source_sales_code = row.value("kode")
        type_code_norm = norm(row.value("type"))
        jenisitr_norm = norm(row.value("jenisitr"))
        if principal_code is None or principal_code_norm is None:
            add_hold(plan, row, "sales_principal_code_blank")
            continue
        if (source_system, principal_code_norm) not in principals:
            add_hold(plan, row, "sales_principal_not_planned", source_principal_code=principal_code)
            continue
        if source_sales_code is None:
            add_hold(plan, row, "sales_code_blank")
            continue
        # Direct legacy type has precedence.  A type not explicitly approved
        # in the policy may fall back to the separately audited JenisITR value;
        # there is deliberately no generic "default sales type".
        target_type_id = target_type_ids_by_type.get(type_code_norm or "")
        classification_basis = "type"
        if target_type_id is None:
            target_type_id = target_type_ids_by_jenisitr.get(jenisitr_norm or "")
            classification_basis = "jenisitr"
        if target_type_id is None:
            add_hold(
                plan,
                row,
                "sales_type_and_jenisitr_not_mapped",
                source_type=row.value("type"),
                source_jenisitr=row.value("jenisitr"),
            )
            continue
        source_code_checked = target_value_or_hold(plan, row, source_sales_code, sales_detail_columns.get("kode_sales"), "sales_code", required=True)
        if source_code_checked is None:
            continue
        if row_has_hold(plan, row):
            continue
        result_key = (source_system, principal_code_norm, source_sales_code_norm)
        action = SalesAction(
            row=row,
            source_principal_code=principal_code,
            source_principal_code_norm=principal_code_norm,
            source_sales_code=source_sales_code,
            source_sales_code_norm=source_sales_code_norm,
            classification_basis=classification_basis,
            payload_sales={"id_tipe": target_type_id},
            payload_sales_detail={"kode_sales": source_code_checked},
        )
        plan.sales.append(action)
        result[result_key] = action
    return result


def load_product_tax_policy(path: Path | None) -> Mapping[str, Decimal] | None:
    """Load the explicitly approved legacy FakturPajak -> target PPN mapping."""

    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ImporterError(f"Product tax policy tidak ditemukan: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ImporterError(f"Product tax policy JSON tidak valid: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ImporterError("Product tax policy harus JSON object")
    require_approved_subpolicy(payload, "Product tax policy")
    mapping = payload.get("source_fakturpajak_to_ppn")
    if not isinstance(mapping, Mapping) or not mapping:
        raise ImporterError("Product tax policy wajib memiliki source_fakturpajak_to_ppn")
    result: dict[str, Decimal] = {}
    for legacy_value, ppn in mapping.items():
        legacy_norm = norm(legacy_value)
        parsed_ppn, problem = parse_decimal(ppn, "product_ppn", minimum=Decimal("0"))
        if legacy_norm is None or problem or parsed_ppn is None or parsed_ppn > Decimal("100"):
            raise ImporterError("Product tax policy hanya boleh memetakan FakturPajak ke persen PPN 0..100")
        result[legacy_norm] = parsed_ppn
    return result


def plan_products(
    plan: MasterPlan,
    rows_by_source: Mapping[str, list[StageRow]],
    principals: Mapping[tuple[str, str], PrincipalAction],
    columns: Mapping[str, Mapping[str, TargetColumn]],
    product_tax_policy: Mapping[str, Decimal] | None,
) -> dict[tuple[str, str, str], ProductAction]:
    unique_rows = unique_source_rows_by_columns(
        plan,
        [row for source in SOURCE_ORDER for row in rows_by_source[source]],
        ("principle", "kode"),
        label="product",
    )
    product_columns = columns.get("produk", {})
    result: dict[tuple[str, str, str], ProductAction] = {}
    for (source_system, _source_principal_code_norm, source_sku_norm), row in sorted(unique_rows.items()):
        principal_code = row.value("principle")
        principal_code_norm = norm(principal_code)
        source_sku = row.value("kode")
        source_name = row.value("nama")
        base_uom = row.value("satuan")
        if principal_code is None or principal_code_norm is None:
            add_hold(plan, row, "product_principal_code_blank")
            continue
        if (source_system, principal_code_norm) not in principals:
            add_hold(plan, row, "product_principal_not_planned", source_principal_code=principal_code)
            continue
        if source_sku is None or source_name is None or base_uom is None:
            add_hold(plan, row, "product_required_source_value_blank")
            continue
        if product_tax_policy is None:
            add_hold(plan, row, "product_tax_policy_missing", required="--product-tax-policy-json")
            continue
        source_tax = norm(row.value("fakturpajak"))
        if source_tax not in product_tax_policy:
            add_hold(plan, row, "product_source_tax_flag_unmapped", source_fakturpajak=row.value("fakturpajak"))
            continue
        sku = target_value_or_hold(plan, row, source_sku, product_columns.get("kode_sku"), "product_sku", required=True)
        name = target_value_or_hold(plan, row, source_name, product_columns.get("nama"), "product_name", required=True)
        satuan = target_value_or_hold(plan, row, base_uom, product_columns.get("satuan"), "product_base_uom", required=True)
        if sku is None or name is None or satuan is None:
            continue
        # Cost/HPP and active selling price are intentionally excluded from
        # phase one.  The source fields are retained in staging but no policy
        # currently proves their target price-type/cost semantics.
        action = ProductAction(
            row=row,
            source_principal_code=principal_code,
            source_principal_code_norm=principal_code_norm,
            source_sku=source_sku,
            source_sku_norm=source_sku_norm,
            payload={
                "kode_sku": sku,
                "nama": name,
                "satuan": satuan,
                "harga_beli": None,
                "harga_jual": None,
                "keterangan": None,
                "ppn": float(product_tax_policy[source_tax]),
            },
        )
        plan.products.append(action)
        result[(source_system, principal_code_norm, source_sku_norm)] = action
    return result


def build_verified_uom_names(
    plan: MasterPlan,
    rows_by_source: Mapping[str, list[StageRow]],
) -> Mapping[tuple[str, str], str]:
    """Resolve exact source UOM labels from frozen ``BarangSatuan`` rows.

    A conflicting source reference label is not selected arbitrarily.  The
    conflict is carried forward as a product-level hold only when a STOK row
    actually needs that UOM code.
    """

    groups: dict[tuple[str, str], list[StageRow]] = defaultdict(list)
    for source_system in SOURCE_ORDER:
        for row in rows_by_source[source_system]:
            code_norm = norm(row.value("kode"))
            if code_norm is not None:
                groups[(source_system, code_norm)].append(row)
    result: dict[tuple[str, str], str] = {}
    for key, rows in groups.items():
        names = {clean(row.value("nama")) for row in rows}
        names.discard(None)
        normalized_names = {norm(name) for name in names}
        if len(normalized_names) != 1:
            continue
        # Preserve a deterministic original source spelling after proving its
        # semantic label is unique under normalization.
        result[key] = sorted((name for name in names if name is not None), key=lambda item: (norm(item) or "", item))[0]
    return result


def plan_uoms(
    plan: MasterPlan,
    products: dict[tuple[str, str, str], ProductAction],
    columns: Mapping[str, Mapping[str, TargetColumn]],
    verified_uom_names: Mapping[tuple[str, str], str],
) -> None:
    """Plan UOMs atomically with their product.

    A base UOM is valid only when its exact source code resolves through the
    frozen ``BarangSatuan`` reference; it becomes level 1 with factor 1.
    A distinct outer source UOM is valid only when it also resolves through
    that reference and ``STOK.PerUnit`` proves a factor greater than 1; it
    becomes level 2.  No generic PCS/CT meaning is inferred: source code and
    label are preserved exactly, and no unproven level 3/factor chain is made.
    """

    uom_columns = columns.get("produk_uom", {})

    def hold_product(product_key: tuple[str, str, str], product: ProductAction, reason: str, **details: Any) -> None:
        add_hold(plan, product.row, reason, **details)
        products.pop(product_key, None)
        plan.products = [candidate for candidate in plan.products if candidate is not product]

    for product_key, product in list(sorted(products.items())):
        row = product.row
        base_code = row.value("satuan")
        base_code_norm = norm(base_code)
        outer_code = row.value("namaunit")
        outer_code_norm = norm(outer_code)
        per_unit, per_unit_problem = parse_int(row.value("perunit"), "uom_factor", minimum=1)
        if base_code is None or base_code_norm is None:
            hold_product(product_key, product, "uom_base_reference_name_not_verified", source_base_uom=base_code)
            continue
        base_name = verified_uom_names.get((row.source_system, base_code_norm))
        if base_name is None:
            hold_product(product_key, product, "uom_base_reference_name_not_verified", source_base_uom=base_code)
            continue
        base_code_checked = target_value_or_hold(plan, row, base_code, uom_columns.get("kode"), "uom_base_code", required=True)
        base_name_checked = target_value_or_hold(plan, row, base_name, uom_columns.get("nama"), "uom_base_name", required=True)
        base_packing = target_value_or_hold(plan, row, base_code_checked, uom_columns.get("packing_satuan"), "uom_base_packing", required=True)
        if base_code_checked is None or base_name_checked is None or base_packing is None or row_has_hold(plan, row):
            products.pop(product_key, None)
            plan.products = [candidate for candidate in plan.products if candidate is not product]
            continue

        actions = [
            UomAction(
                product_key=product_key,
                row=row,
                source_uom_code=base_code,
                source_uom_code_norm=base_code_norm,
                source_uom_ordinal=1,
                level=1,
                factor=1,
                payload={
                    "kode": base_code_checked,
                    "nama": base_name_checked,
                    "level": 1,
                    "packing_satuan": base_packing,
                    "faktor_konversi": 1,
                    "set_default_sales": 1,
                    "set_default_storage": 1,
                },
            )
        ]
        if outer_code_norm is None:
            plan.uoms.extend(actions)
            continue
        if outer_code_norm == base_code_norm:
            if per_unit_problem is None and per_unit == 1:
                plan.uoms.extend(actions)
                continue
            hold_product(product_key, product, "uom_outer_same_as_base_with_conversion", source_outer_uom=outer_code, source_factor=row.value("perunit"))
            continue
        if per_unit_problem or per_unit is None or per_unit <= 1:
            hold_product(product_key, product, per_unit_problem or "uom_outer_factor_must_be_gt_one", source_outer_uom=outer_code)
            continue
        outer_name = verified_uom_names.get((row.source_system, outer_code_norm))
        if outer_name is None:
            hold_product(product_key, product, "uom_outer_reference_name_not_verified", source_outer_uom=outer_code)
            continue
        outer_code_checked = target_value_or_hold(plan, row, outer_code, uom_columns.get("kode"), "uom_outer_code", required=True)
        outer_name_checked = target_value_or_hold(plan, row, outer_name, uom_columns.get("nama"), "uom_outer_name", required=True)
        outer_packing = target_value_or_hold(plan, row, outer_code_checked, uom_columns.get("packing_satuan"), "uom_outer_packing", required=True)
        if outer_code_checked is None or outer_name_checked is None or outer_packing is None or row_has_hold(plan, row):
            products.pop(product_key, None)
            plan.products = [candidate for candidate in plan.products if candidate is not product]
            continue
        actions.append(
            UomAction(
                product_key=product_key,
                row=row,
                source_uom_code=outer_code,
                source_uom_code_norm=outer_code_norm,
                source_uom_ordinal=2,
                level=2,
                factor=per_unit,
                payload={
                    "kode": outer_code_checked,
                    "nama": outer_name_checked,
                    "level": 2,
                    "packing_satuan": outer_packing,
                    "faktor_konversi": per_unit,
                    "set_default_sales": 0,
                    "set_default_storage": 0,
                },
            )
        )
        plan.uoms.extend(actions)


def load_price_policy(path: Path | None) -> Mapping[str, str] | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ImporterError(f"Price policy tidak ditemukan: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ImporterError(f"Price policy JSON tidak valid: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ImporterError("Price policy harus JSON object")
    require_approved_subpolicy(payload, "Price policy")
    mapping = payload.get("source_price_columns")
    if not isinstance(mapping, Mapping) or not mapping:
        raise ImporterError("Price policy wajib berisi source_price_columns")
    result: dict[str, str] = {}
    for source_column, target_price_type_code in mapping.items():
        source_column_clean = clean(source_column)
        target_price_type_clean = clean(target_price_type_code)
        if source_column_clean not in {"hargaa", "hargab", "hargac", "hargad", "hargae"} or target_price_type_clean is None:
            raise ImporterError("Price policy memiliki mapping source/tipe harga tidak aman")
        result[source_column_clean] = target_price_type_clean
    normalized_target_types = [norm(value) for value in result.values()]
    if any(value is None for value in normalized_target_types) or len(set(normalized_target_types)) != len(normalized_target_types):
        raise ImporterError("Price policy harus injective: satu tipe harga target hanya boleh berasal dari satu kolom source")
    return result


def plan_prices(
    plan: MasterPlan,
    products: Mapping[tuple[str, str, str], ProductAction],
    price_policy: Mapping[str, str] | None,
    cur: Any,
) -> None:
    if price_policy is None:
        for product in products.values():
            add_hold(plan, product.row, "price_policy_missing", required="--price-policy-json")
        return
    valid_price_types: dict[str, int] = {}
    for source_column, target_price_type_code in price_policy.items():
        target_id = exact_reference_id(cur, "produk_tipe_harga", "kode", target_price_type_code)
        if target_id is None:
            plan.structural_blockers.append(
                report_blocker(
                    "price_type_lookup_not_exact",
                    "produk_tipe_harga.kode dari policy harus meresolusi tepat satu row.",
                    source_column=source_column,
                    target_price_type_code=target_price_type_code,
                )
            )
        else:
            valid_price_types[source_column] = target_id
    if len(valid_price_types) != len(price_policy):
        return
    for product_key, product in products.items():
        for source_column, target_price_type_code in price_policy.items():
            value, problem = parse_decimal(product.row.value(source_column), f"price_{source_column}", minimum=Decimal("0"))
            if problem or value is None:
                add_hold(plan, product.row, problem or "price_invalid", source_column=source_column)
                continue
            _, float_problem = decimal_as_finite_float(value, f"price_{source_column}")
            if float_problem:
                add_hold(plan, product.row, float_problem, source_column=source_column)
                continue
            plan.prices.append(
                PriceAction(
                    product_key=product_key,
                    row=product.row,
                    source_price_column=source_column,
                    target_price_type_code=target_price_type_code,
                    value=value,
                )
            )


def plan_plafon(
    plan: MasterPlan,
    rows_by_source: Mapping[str, list[StageRow]],
    customers: Mapping[tuple[str, str], CustomerAction],
    principals: Mapping[tuple[str, str], PrincipalAction],
    sales: Mapping[tuple[str, str, str], SalesAction],
    columns: Mapping[str, Mapping[str, TargetColumn]],
) -> None:
    candidates: dict[tuple[str, str, str, str], list[PlafonAction]] = defaultdict(list)
    for source_system in SOURCE_ORDER:
        for row in rows_by_source[source_system]:
            customer_code_norm = norm(row.value("kodecustomer"))
            principal_code_norm = norm(row.value("kodeprinciple"))
            sales_code_norm = norm(row.value("kodesales"))
            if not all((customer_code_norm, principal_code_norm, sales_code_norm)):
                add_hold(plan, row, "plafon_source_key_blank")
                continue
            if (source_system, customer_code_norm) not in customers:
                add_hold(plan, row, "plafon_customer_not_planned")
                continue
            if (source_system, principal_code_norm) not in principals:
                add_hold(plan, row, "plafon_principal_not_planned")
                continue
            if (source_system, principal_code_norm, sales_code_norm) not in sales:
                add_hold(plan, row, "plafon_sales_not_planned")
                continue
            limit_bon, limit_problem = parse_decimal(row.value("plafon"), "plafon_limit", minimum=Decimal("0"))
            term, term_problem = parse_int(row.value("term"), "plafon_term", minimum=0)
            source_added_at_raw = row.value("tgladd")
            source_added_at, timestamp_problem = parse_timestamp(source_added_at_raw)
            if limit_problem or term_problem or timestamp_problem or limit_bon is None or term is None or source_added_at is None:
                add_hold(plan, row, limit_problem or term_problem or timestamp_problem or "plafon_invalid")
                continue
            if term > 32_767:
                add_hold(plan, row, "plafon_term_exceeds_target_top_range", source_term=term)
                continue
            _, float_problem = decimal_as_finite_float(limit_bon, "plafon_limit")
            if float_problem:
                add_hold(plan, row, float_problem)
                continue
            tempo_label = f"{term} Hari" if term > 0 else None
            tempo_label_checked = target_value_or_hold(
                plan,
                row,
                tempo_label,
                columns.get("plafon", {}).get("tempo_label"),
                "plafon_tempo_label",
            )
            if tempo_label is not None and tempo_label_checked is None:
                continue
            candidate = PlafonAction(
                row=row,
                source_customer_code_norm=customer_code_norm,
                source_principal_code_norm=principal_code_norm,
                source_sales_code_norm=sales_code_norm,
                limit_bon=limit_bon,
                term=term,
                source_added_at_raw=source_added_at_raw or "",
                source_added_at=source_added_at,
            )
            candidates[(source_system, customer_code_norm, principal_code_norm, sales_code_norm)].append(candidate)

    for _, choices in candidates.items():
        latest = max(choice.source_added_at for choice in choices)
        newest = [choice for choice in choices if choice.source_added_at == latest]
        semantic = {(format(choice.limit_bon.normalize(), "f"), choice.term) for choice in newest}
        if len(semantic) != 1:
            for choice in newest:
                add_hold(plan, choice.row, "plafon_latest_timestamp_conflict", same_timestamp=latest.isoformat(), candidate_count=len(newest))
            continue
        # Multiple same-timestamp rows with exactly the same economics are
        # still source duplicates.  No arbitrary staging_id tie-break is
        # permitted for a source-qualified master identity.
        if len(newest) != 1:
            for choice in newest:
                add_hold(plan, choice.row, "plafon_latest_duplicate_source_rows", same_timestamp=latest.isoformat(), candidate_count=len(newest))
            continue
        # Preserve the latest source limit/term only.  Apply initializes the
        # public row with sisa_bon=0 and lock_order='1', a deliberately
        # non-live state that cannot be mistaken for inferred opening AR.
        plan.plafon.append(newest[0])


def stage_row_key(row: StageRow) -> tuple[str, str, int, str, int, str]:
    """Return the immutable identity used to keep a partial plan closed.

    A reviewed hold is a decision about a *specific frozen row*, not merely a
    code/name.  Actions sourced by such a row must never leak into a partial
    import just because they were planned before a later validation (for
    example a price validation) added the hold.
    """

    return (
        row.source_system,
        row.schema,
        row.run_id,
        row.table,
        row.staging_id,
        row.source_row_hash,
    )


def has_hold_reason(plan: MasterPlan, row: StageRow, reason: str) -> bool:
    return any(stage_row_key(hold.row) == stage_row_key(row) and hold.reason == reason for hold in plan.holds)


def close_actions_over_held_rows(plan: MasterPlan) -> None:
    """Remove every target action whose evidence is held, with dependencies.

    Normal ``--apply`` never reaches this path with a hold.  It is nevertheless
    essential for an explicitly approved partial run: a product with one
    invalid price must not be imported together with its remaining UOM/price
    rows.  Dependent actions that lose an upstream master acquire their own
    hold so the manifest records each skipped source row explicitly.
    """

    original = {
        "principals": len(plan.principals),
        "customers": len(plan.customers),
        "sales": len(plan.sales),
        "products": len(plan.products),
        "uoms": len(plan.uoms),
        "prices": len(plan.prices),
        "plafon": len(plan.plafon),
    }
    for _ in range(8):
        held_rows = {stage_row_key(hold.row) for hold in plan.holds}
        plan.principals = [item for item in plan.principals if stage_row_key(item.row) not in held_rows]
        plan.customers = [item for item in plan.customers if stage_row_key(item.row) not in held_rows]
        plan.sales = [item for item in plan.sales if stage_row_key(item.row) not in held_rows]
        plan.products = [item for item in plan.products if stage_row_key(item.row) not in held_rows]
        plan.plafon = [item for item in plan.plafon if stage_row_key(item.row) not in held_rows]

        principal_keys = {(item.row.source_system, item.source_code_norm) for item in plan.principals}
        customer_keys = {(item.row.source_system, item.source_code_norm) for item in plan.customers}
        sales_keys = {
            (item.row.source_system, item.source_principal_code_norm, item.source_sales_code_norm)
            for item in plan.sales
        }
        product_keys = {
            (item.row.source_system, item.source_principal_code_norm, item.source_sku_norm)
            for item in plan.products
        }

        new_holds: list[Hold] = []
        for item in plan.customers:
            if item.mapping_method == "bdm_shared_exact" and item.shared_tmp_key is not None:
                tmp_key = ("tmp_solo_dist", item.shared_tmp_key[0])
                if tmp_key not in customer_keys and not has_hold_reason(plan, item.row, "customer_tmp_shared_target_not_available_after_hold"):
                    new_holds.append(
                        Hold(
                            row=item.row,
                            reason="customer_tmp_shared_target_not_available_after_hold",
                            details={"tmp_customer_code_norm": item.shared_tmp_key[0]},
                        )
                    )
        for item in plan.sales:
            if (item.row.source_system, item.source_principal_code_norm) not in principal_keys:
                if not has_hold_reason(plan, item.row, "sales_principal_not_available_after_hold"):
                    new_holds.append(
                        Hold(
                            row=item.row,
                            reason="sales_principal_not_available_after_hold",
                            details={"source_principal_code_norm": item.source_principal_code_norm},
                        )
                    )
        for item in plan.products:
            if (item.row.source_system, item.source_principal_code_norm) not in principal_keys:
                if not has_hold_reason(plan, item.row, "product_principal_not_available_after_hold"):
                    new_holds.append(
                        Hold(
                            row=item.row,
                            reason="product_principal_not_available_after_hold",
                            details={"source_principal_code_norm": item.source_principal_code_norm},
                        )
                    )
        for item in plan.plafon:
            missing: list[str] = []
            if (item.row.source_system, item.source_customer_code_norm) not in customer_keys:
                missing.append("customer")
            if (item.row.source_system, item.source_principal_code_norm) not in principal_keys:
                missing.append("principal")
            if (
                item.row.source_system,
                item.source_principal_code_norm,
                item.source_sales_code_norm,
            ) not in sales_keys:
                missing.append("sales")
            if missing and not has_hold_reason(plan, item.row, "plafon_dependency_not_available_after_hold"):
                new_holds.append(
                    Hold(
                        row=item.row,
                        reason="plafon_dependency_not_available_after_hold",
                        details={"missing_dependencies": sorted(missing)},
                    )
                )

        plan.uoms = [
            item
            for item in plan.uoms
            if stage_row_key(item.row) not in held_rows and item.product_key in product_keys
        ]
        plan.prices = [
            item
            for item in plan.prices
            if stage_row_key(item.row) not in held_rows and item.product_key in product_keys
        ]
        if not new_holds:
            break
        plan.holds.extend(new_holds)
    else:
        plan.structural_blockers.append(
            report_blocker(
                "held_action_dependency_closure_nonconvergent",
                "Closure action atas hold tidak konvergen; import parsial tidak aman.",
            )
        )

    held_rows = {stage_row_key(hold.row) for hold in plan.holds}
    remaining_product_keys = {
        (item.row.source_system, item.source_principal_code_norm, item.source_sku_norm)
        for item in plan.products
    }
    leaked = [
        label
        for label, actions in (
            ("principal", plan.principals),
            ("customer", plan.customers),
            ("sales", plan.sales),
            ("product", plan.products),
            ("uom", plan.uoms),
            ("price", plan.prices),
            ("plafon", plan.plafon),
        )
        if any(stage_row_key(item.row) in held_rows for item in actions)
    ]
    orphaned_product_children = [
        label
        for label, actions in (("uom", plan.uoms), ("price", plan.prices))
        if any(item.product_key not in remaining_product_keys for item in actions)
    ]
    if leaked or orphaned_product_children:
        plan.structural_blockers.append(
            report_blocker(
                "held_action_closure_incomplete",
                "Aksi target masih memakai evidence hold atau produk yang tidak lagi eligible.",
                leaked_action_groups=sorted(set(leaked)),
                orphaned_product_children=sorted(set(orphaned_product_children)),
            )
        )
    removed = {
        "principals": original["principals"] - len(plan.principals),
        "customers": original["customers"] - len(plan.customers),
        "sales": original["sales"] - len(plan.sales),
        "products": original["products"] - len(plan.products),
        "uoms": original["uoms"] - len(plan.uoms),
        "prices": original["prices"] - len(plan.prices),
        "plafon": original["plafon"] - len(plan.plafon),
    }
    if any(removed.values()):
        plan.notes.append(
            "Aksi yang bergantung pada source row hold dipangkas dari plan; "
            f"perubahan={stable_json({key: value for key, value in removed.items() if value})}."
        )


def target_master_counts(cur: Any) -> Mapping[str, int | None]:
    # User accounts are not part of this historical master phase.  A clean
    # baseline may contain a bootstrap administrator without making the
    # source-owned master area non-empty.
    tables = ("principal", "customer", "sales", "sales_detail", "sales_principal_assignment", "produk", "produk_uom", "produk_harga_jual", "plafon")
    result: dict[str, int | None] = {}
    for table in tables:
        if not table_exists(cur, "public", table):
            result[table] = None
            continue
        cur.execute(f"SELECT count(*) FROM {qtable('public', table)}")
        result[table] = int(cur.fetchone()[0])
    return result


def build_plan(
    cur: Any,
    *,
    target_database: str,
    policy_sha256: str,
    configs: Mapping[str, SourceConfig],
    args: argparse.Namespace,
) -> MasterPlan:
    columns, blockers = inspect_target_contract(cur)
    observed_schema_sha, observed_reference_sha, baseline_blockers = observed_target_baselines(cur)
    blockers.extend(baseline_blockers)
    blockers.extend(
        verify_clean_target_attestation(
            cur,
            target_database=target_database,
            observed_schema_sha256=observed_schema_sha,
            observed_reference_sha256=observed_reference_sha,
        )
    )
    stages: dict[str, StageInfo] = {}
    expected_ids = {
        "bdm_solo_dist": args.bdm_stage_run_id,
        "tmp_solo_dist": args.tmp_stage_run_id,
    }
    for source_system in ("bdm_solo_dist", "tmp_solo_dist"):
        stage = resolve_stage_info(cur, configs[source_system], expected_ids[source_system], blockers)
        if stage is not None:
            stages[source_system] = stage
    plan = MasterPlan(
        target_database=target_database,
        policy_sha256=policy_sha256,
        stages=stages,
        observed_schema_sha256=observed_schema_sha,
        observed_reference_sha256=observed_reference_sha,
        structural_blockers=blockers,
    )
    if set(stages) != {"bdm_solo_dist", "tmp_solo_dist"}:
        plan.notes.append("Stage tidak lengkap; planner master dihentikan sebelum membaca data sumber.")
        return plan

    if stages["bdm_solo_dist"].consistency_mode != stages["tmp_solo_dist"].consistency_mode:
        plan.structural_blockers.append(
            report_blocker("stage_consistency_modes_differ", "BDM dan TMP harus memakai consistency mode yang sama.")
        )
    if stages["bdm_solo_dist"].consistency_mode == "maintenance_freeze_serializable":
        bdm_window = stages["bdm_solo_dist"].maintenance_window_id
        tmp_window = stages["tmp_solo_dist"].maintenance_window_id
        if not bdm_window or not tmp_window or bdm_window != tmp_window:
            plan.structural_blockers.append(
                report_blocker(
                    "stage_maintenance_window_mismatch",
                    "Maintenance-freeze BDM/TMP harus menggunakan maintenance_window_id yang sama dan tidak kosong.",
                    bdm_window=bdm_window,
                    tmp_window=tmp_window,
                )
            )

    rows: dict[str, dict[str, list[StageRow]]] = {source: {} for source in SOURCE_ORDER}
    wanted = {
        "principle": ("kode", "nama", "alamat", "telpon", "npwp", "account", "contactperson", "active"),
        "customer": ("kode", "nama", "alamat", "telpon", "npwp", "contactperson", "email", "namawp", "alamatwp", "longitude", "latitude", "opsharga", "fp"),
        "sales": ("kode", "nama", "kodeprinciple", "type", "jenisitr"),
        "stok": ("kode", "nama", "principle", "satuan", "namaunit", "perunit", "hargaa", "hargab", "hargac", "hargad", "hargae", "fakturpajak"),
        "plafon": ("kodecustomer", "kodeprinciple", "kodesales", "plafon", "term", "tgladd"),
        "barangsatuan": ("kode", "nama"),
    }
    for source_system in SOURCE_ORDER:
        for table, fields in wanted.items():
            rows[source_system][table] = load_stage_rows(cur, stages[source_system], table, fields)

    principals = plan_principals(plan, {source: rows[source]["principle"] for source in SOURCE_ORDER}, columns)
    customer_policy = load_customer_pricing_tax_policy(args.customer_pricing_tax_policy_json)
    customers = plan_customers(
        plan,
        {source: rows[source]["customer"] for source in SOURCE_ORDER},
        columns,
        customer_policy,
        cur,
    )
    sales_policy = load_sales_policy(args.sales_policy_json)
    sales = plan_sales(plan, {source: rows[source]["sales"] for source in SOURCE_ORDER}, principals, columns, sales_policy, cur)
    product_tax_policy = load_product_tax_policy(args.product_tax_policy_json)
    products = plan_products(
        plan,
        {source: rows[source]["stok"] for source in SOURCE_ORDER},
        principals,
        columns,
        product_tax_policy,
    )
    verified_uom_names = build_verified_uom_names(plan, {source: rows[source]["barangsatuan"] for source in SOURCE_ORDER})
    plan_uoms(plan, products, columns, verified_uom_names)
    price_policy = load_price_policy(args.price_policy_json)
    plan_prices(plan, products, price_policy, cur)
    plan_plafon(plan, {source: rows[source]["plafon"] for source in SOURCE_ORDER}, customers, principals, sales, columns)
    # Strict mode will still reject every hold.  This closure is only relevant
    # if a separately reviewed manifest later authorizes a partial import.
    # Run it before hashing/reporting so the reviewed plan captures exactly
    # which target actions are absent with the held source rows.
    close_actions_over_held_rows(plan)
    return plan


def compact_blockers(blockers: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    # Preserve distinct details while ensuring the JSON report stays readable.
    seen: set[str] = set()
    compacted: list[Mapping[str, Any]] = []
    for blocker in blockers:
        marker = stable_json(blocker)
        if marker not in seen:
            seen.add(marker)
            compacted.append(blocker)
    return compacted


def plan_sha256(plan: MasterPlan) -> str:
    """Hash all deterministic decisions that an operator must review.

    The report prints only this digest, not source business values.  Apply
    rebuilds the plan under serializable locks and requires the same digest so
    a changed policy, lookup, staging row, hold, or plan action cannot slip
    through between review and write.
    """

    def source(row: StageRow) -> Mapping[str, Any]:
        return {
            "source_system": row.source_system,
            "schema": row.schema,
            "run_id": row.run_id,
            "table": row.table,
            "staging_id": row.staging_id,
            "row_hash": row.source_row_hash,
        }

    return stable_hash(
        {
            "version": SCRIPT_VERSION,
            "target_database": plan.target_database,
            "policy_sha256": plan.policy_sha256,
            "observed_schema_sha256": plan.observed_schema_sha256,
            "observed_reference_sha256": plan.observed_reference_sha256,
            "stages": {
                key: {
                    "run_id": value.run_id,
                    "snapshot_sha256": value.snapshot_sha256,
                    "manifest_sha256": value.manifest_sha256,
                }
                for key, value in sorted(plan.stages.items())
            },
            "principals": [
                {"source": source(item.row), "code_norm": item.source_code_norm, "payload": item.payload}
                for item in plan.principals
            ],
            "customers": [
                {
                    "source": source(item.row),
                    "code_norm": item.source_code_norm,
                    "name_norm": item.source_name_norm,
                    "mapping_method": item.mapping_method,
                    "shared_tmp_key": item.shared_tmp_key,
                    "payload": item.payload,
                }
                for item in plan.customers
            ],
            "sales": [
                {
                    "source": source(item.row),
                    "principal_norm": item.source_principal_code_norm,
                    "sales_norm": item.source_sales_code_norm,
                    "classification_basis": item.classification_basis,
                    "sales_payload": item.payload_sales,
                    "detail_payload": item.payload_sales_detail,
                }
                for item in plan.sales
            ],
            "products": [
                {
                    "source": source(item.row),
                    "principal_norm": item.source_principal_code_norm,
                    "sku_norm": item.source_sku_norm,
                    "payload": item.payload,
                }
                for item in plan.products
            ],
            "uoms": [
                {
                    "source": source(item.row),
                    "product_key": item.product_key,
                    "code_norm": item.source_uom_code_norm,
                    "ordinal": item.source_uom_ordinal,
                    "factor": item.factor,
                    "payload": item.payload,
                }
                for item in plan.uoms
            ],
            "prices": [
                {
                    "source": source(item.row),
                    "product_key": item.product_key,
                    "source_column": item.source_price_column,
                    "target_price_type_code": item.target_price_type_code,
                    "value": item.value,
                }
                for item in plan.prices
            ],
            "plafon": [
                {
                    "source": source(item.row),
                    "customer_norm": item.source_customer_code_norm,
                    "principal_norm": item.source_principal_code_norm,
                    "sales_norm": item.source_sales_code_norm,
                    "limit_bon": item.limit_bon,
                    "term": item.term,
                    "source_added_at_raw": item.source_added_at_raw,
                    "source_added_at": item.source_added_at,
                    "opening_balance_strategy": item.opening_balance_strategy,
                }
                for item in plan.plafon
            ],
            "holds": [
                {"source": source(item.row), "reason": item.reason, "details": item.details}
                for item in plan.holds
            ],
            "structural_blockers": compact_blockers(plan.structural_blockers),
        }
    )


def canonical_json_value(value: Any) -> Any:
    """Convert a value to the exact JSON representation used for hashing."""

    return json.loads(stable_json(value))


def hold_manifest_entries(plan: MasterPlan) -> list[Mapping[str, Any]]:
    """Produce an exact, registry-compatible list of planned source holds.

    ``import_hold`` groups repeat sightings by source identity and reason.  A
    plan that would collapse different details into that same registry key is
    not audit-safe for approved skipping and must be fixed before it can be
    applied.  The dry-run can still show the root planning error, but it must
    not mint a misleading approval artifact.
    """

    grouped: dict[tuple[str, str, str, str], tuple[Mapping[str, Any], int]] = {}
    for hold in plan.holds:
        entry: Mapping[str, Any] = {
            "source_system": hold.row.source_system,
            "source_stage_schema": hold.row.schema,
            "source_stage_run_id": hold.row.run_id,
            "source_table": hold.row.table,
            "source_staging_id": hold.row.staging_id,
            "source_identity_sha256": hold.source_identity_sha256,
            "source_row_hash": hold.row.source_row_hash,
            "source_key": {
                "source_system": hold.row.source_system,
                "source_table": hold.row.table,
                "staging_id": hold.row.staging_id,
            },
            "hold_reason": hold.reason,
            "details": canonical_json_value(dict(hold.details)),
        }
        registry_key = (
            hold.row.source_system,
            hold.row.table,
            hold.source_identity_sha256,
            hold.reason,
        )
        existing = grouped.get(registry_key)
        if existing is None:
            grouped[registry_key] = (entry, 1)
            continue
        existing_entry, occurrence_count = existing
        if stable_json(existing_entry) != stable_json(entry):
            raise GuardError(
                "Satu identity/reason hold memiliki detail berbeda; evidence registry tidak dapat "
                "mengagregasikannya secara audit-safe. Perbaiki planner sebelum meminta skip."
            )
        grouped[registry_key] = (existing_entry, occurrence_count + 1)
    entries = [
        {**entry, "occurrence_count": occurrence_count}
        for entry, occurrence_count in grouped.values()
    ]
    return sorted(entries, key=stable_json)


def build_hold_manifest(plan: MasterPlan) -> Mapping[str, Any]:
    """Build the deterministic, reviewer-facing approval subject.

    The payload contains neither DSN nor credentials.  It binds the complete
    exact hold list to the target, stage snapshot/manifest, policies,
    baseline fingerprints, and complete action plan.  The caller may wrap it
    in an approval envelope, but must never alter this inner manifest.
    """

    entries = hold_manifest_entries(plan)
    payload: dict[str, Any] = {
        "format": HOLD_MANIFEST_FORMAT,
        "pipeline_version": SCRIPT_VERSION,
        "target_database": plan.target_database,
        "plan_sha256": plan_sha256(plan),
        "policy_sha256": plan.policy_sha256,
        "observed_baseline": {
            "schema_sha256": plan.observed_schema_sha256,
            "reference_sha256": plan.observed_reference_sha256,
        },
        "stages": {
            source_system: {
                "schema": stage.schema,
                "run_id": stage.run_id,
                "snapshot_label": stage.snapshot_label,
                "snapshot_sha256": stage.snapshot_sha256,
                "manifest_sha256": stage.manifest_sha256,
            }
            for source_system, stage in sorted(plan.stages.items())
        },
        "hold_occurrences": len(plan.holds),
        "hold_entries": entries,
        "hold_entries_sha256": stable_hash(entries),
        "skip_consequence": (
            "Rows in this exact manifest are intentionally absent from this blue/green target; "
            "a later correction requires a fresh clean target and a new reviewed import."
        ),
    }
    return {**payload, "manifest_sha256": stable_hash(payload)}


def hold_manifest_summary(plan: MasterPlan) -> Mapping[str, Any]:
    manifest = build_hold_manifest(plan)
    return {
        "format": manifest["format"],
        "manifest_sha256": manifest["manifest_sha256"],
        "hold_occurrences": manifest["hold_occurrences"],
        "hold_entries": len(manifest["hold_entries"]),
        "hold_entries_sha256": manifest["hold_entries_sha256"],
    }


def write_hold_approval_envelope(path: Path, plan: MasterPlan) -> Mapping[str, Any]:
    """Write a pending-review envelope around an immutable generated manifest."""

    manifest = build_hold_manifest(plan)
    envelope = {
        "format": HOLD_APPROVAL_ENVELOPE_FORMAT,
        "manifest": manifest,
        "approval": {
            "approval_status": "pending_review",
            "approved_manifest_sha256": manifest["manifest_sha256"],
            "approved_by": None,
            "approval_reference": None,
            "approved_at": None,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return hold_manifest_summary(plan)


def validate_approval_text(value: Any, label: str) -> str:
    text = clean(value)
    if text is None or len(text) > 240 or "\n" in text or "\r" in text:
        raise GuardError(f"{label} harus teks satu baris 1-240 karakter")
    return text


def validate_approval_timestamp(value: Any) -> str:
    text = clean(value)
    if text is None:
        raise GuardError("approval.approved_at wajib timestamp ISO-8601 dengan timezone")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GuardError("approval.approved_at harus timestamp ISO-8601 valid") from exc
    if parsed.tzinfo is None:
        raise GuardError("approval.approved_at wajib menyertakan timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_approved_hold_manifest(
    path: Path | None,
    requested_manifest_sha256: str | None,
    acknowledge: bool,
    plan: MasterPlan,
) -> ApprovedHoldApproval:
    """Validate an approval envelope against the freshly built exact plan."""

    if path is None or requested_manifest_sha256 is None or not acknowledge:
        raise GuardError(
            "--apply dengan hold memerlukan --approved-hold-manifest-json, "
            "--approved-hold-manifest-sha256, dan --acknowledge-approved-holds."
        )
    requested_sha = validate_sha256(requested_manifest_sha256, "--approved-hold-manifest-sha256")
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GuardError(f"Approved hold manifest tidak ditemukan: {path}") from exc
    except json.JSONDecodeError as exc:
        raise GuardError(f"Approved hold manifest bukan JSON valid: {path}") from exc
    if not isinstance(envelope, Mapping) or set(envelope) != {"format", "manifest", "approval"}:
        raise GuardError("Approved hold manifest harus envelope exact format/manifest/approval")
    if envelope.get("format") != HOLD_APPROVAL_ENVELOPE_FORMAT:
        raise GuardError("Format approved hold manifest tidak cocok dengan importer ini")
    manifest = envelope.get("manifest")
    if not isinstance(manifest, Mapping):
        raise GuardError("Approved hold manifest tidak memiliki inner manifest object")
    declared_sha = validate_sha256(clean(manifest.get("manifest_sha256")), "manifest.manifest_sha256")
    manifest_without_digest = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if stable_hash(manifest_without_digest) != declared_sha:
        raise GuardError("Checksum inner hold manifest tidak valid; regenerate dry-run artifact")
    expected = build_hold_manifest(plan)
    if declared_sha != requested_sha:
        raise GuardError("--approved-hold-manifest-sha256 tidak cocok dengan manifest file")
    if stable_json(manifest) != stable_json(expected):
        raise GuardError(
            "Approved hold manifest tidak persis sama dengan hold plan saat ini; "
            "jalankan dry-run baru, review ulang, lalu buat approval baru."
        )

    approval = envelope.get("approval")
    expected_approval_keys = {
        "approval_status",
        "approved_manifest_sha256",
        "approved_by",
        "approval_reference",
        "approved_at",
    }
    if not isinstance(approval, Mapping) or set(approval) != expected_approval_keys:
        raise GuardError("approval harus memiliki status, manifest SHA, reviewer, reference, dan waktu yang lengkap")
    if approval.get("approval_status") != "approved_skip":
        raise GuardError("approval.approval_status harus bernilai approved_skip")
    approved_manifest_sha = validate_sha256(approval.get("approved_manifest_sha256"), "approval.approved_manifest_sha256")
    if approved_manifest_sha != declared_sha:
        raise GuardError("approval.approved_manifest_sha256 tidak cocok dengan inner manifest")
    normalized_approval = {
        "approval_status": "approved_skip",
        "approved_manifest_sha256": approved_manifest_sha,
        "approved_by": validate_approval_text(approval.get("approved_by"), "approval.approved_by"),
        "approval_reference": validate_approval_text(approval.get("approval_reference"), "approval.approval_reference"),
        "approved_at": validate_approval_timestamp(approval.get("approved_at")),
    }
    return ApprovedHoldApproval(
        manifest_sha256=declared_sha,
        approval_sha256=stable_hash(normalized_approval),
        approved_by=normalized_approval["approved_by"],
        approval_reference=normalized_approval["approval_reference"],
        approved_at=normalized_approval["approved_at"],
        hold_occurrences=int(expected["hold_occurrences"]),
        hold_entries=len(expected["hold_entries"]),
        entries=tuple(expected["hold_entries"]),
    )


def plan_report(plan: MasterPlan, target_counts: Mapping[str, int | None]) -> Mapping[str, Any]:
    hold_counts = Counter(hold.reason for hold in plan.holds)
    manifest_summary = hold_manifest_summary(plan)
    hold_examples: list[Mapping[str, Any]] = []
    for hold in plan.holds[:25]:
        hold_examples.append(
            {
                "source_system": hold.row.source_system,
                "source_table": hold.row.table,
                "staging_id": hold.row.staging_id,
                "reason": hold.reason,
                "details": hold.details,
            }
        )
    stage_report = {
        source_system: {
            "schema": stage.schema,
            "run_id": stage.run_id,
            "consistency_mode": stage.consistency_mode,
            "maintenance_window_id": stage.maintenance_window_id,
            "snapshot_label": stage.snapshot_label,
            "snapshot_sha256": stage.snapshot_sha256,
            "manifest_sha256": stage.manifest_sha256,
            "table_counts": dict(stage.table_counts),
        }
        for source_system, stage in plan.stages.items()
    }
    return {
        "pipeline_version": SCRIPT_VERSION,
        "mode": "APPLY_ELIGIBLE" if plan.apply_eligible else "DRY_RUN_BLOCKED",
        "target_database": plan.target_database,
        "policy_sha256": plan.policy_sha256,
        "observed_baseline": {
            "schema_sha256": plan.observed_schema_sha256,
            "reference_sha256": plan.observed_reference_sha256,
        },
        "plan_sha256": plan_sha256(plan),
        "stages": stage_report,
        "target_source_owned_master_counts": dict(target_counts),
        "actions": {
            "principals": len(plan.principals),
            "customers": {
                "total": len(plan.customers),
                "tmp_created": sum(action.mapping_method == "tmp_created" for action in plan.customers),
                "bdm_shared_exact": sum(action.mapping_method == "bdm_shared_exact" for action in plan.customers),
                "bdm_created": sum(action.mapping_method == "bdm_created" for action in plan.customers),
            },
            "sales_without_login_users": len(plan.sales),
            "products": len(plan.products),
            "product_uoms": len(plan.uoms),
            "prices": len(plan.prices),
            "plafon_latest_candidates": len(plan.plafon),
        },
        "holds": {"total": len(plan.holds), "by_reason": dict(sorted(hold_counts.items())), "examples": hold_examples},
        "hold_manifest": manifest_summary,
        "structural_blockers": compact_blockers(plan.structural_blockers),
        "notes": plan.notes,
    }


def ensure_apply_request(
    args: argparse.Namespace,
    plan: MasterPlan,
    target_counts: Mapping[str, int | None],
) -> ApprovedHoldApproval | None:
    if not args.apply:
        return
    if not args.import_key:
        raise GuardError("--apply memerlukan --import-key baru yang eksplisit")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,119}", args.import_key):
        raise GuardError("--import-key harus lower-case [a-z0-9_.-], panjang 3-120")
    requested_schema_sha = validate_sha256(args.baseline_schema_sha256, "--baseline-schema-sha256")
    requested_reference_sha = validate_sha256(args.baseline_reference_sha256, "--baseline-reference-sha256")
    reviewed_plan_sha = validate_sha256(args.reviewed_plan_sha256, "--reviewed-plan-sha256")
    if requested_schema_sha != plan.observed_schema_sha256:
        raise GuardError("--baseline-schema-sha256 tidak cocok dengan fingerprint schema target yang benar-benar terbaca")
    if requested_reference_sha != plan.observed_reference_sha256:
        raise GuardError("--baseline-reference-sha256 tidak cocok dengan fingerprint reference target yang benar-benar terbaca")
    if reviewed_plan_sha != plan_sha256(plan):
        raise GuardError("--reviewed-plan-sha256 tidak cocok dengan plan dry-run saat ini")
    if plan.structural_blockers:
        codes = ", ".join(sorted({str(item["code"]) for item in plan.structural_blockers}))
        raise GuardError(f"--apply diblokir karena kontrak clean belum lengkap: {codes}")
    approved_holds: ApprovedHoldApproval | None = None
    if plan.holds:
        approved_holds = load_approved_hold_manifest(
            args.approved_hold_manifest_json,
            args.approved_hold_manifest_sha256,
            args.acknowledge_approved_holds,
            plan,
        )
    elif (
        args.approved_hold_manifest_json is not None
        or args.approved_hold_manifest_sha256 is not None
        or args.acknowledge_approved_holds
    ):
        raise GuardError("Tidak ada import hold pada plan; approval skip hold tidak boleh dipakai")
    nonempty = {table: count for table, count in target_counts.items() if count != 0}
    if nonempty:
        raise GuardError(f"Clean target master harus kosong sebelum import; ditemukan data: {nonempty}")
    return approved_holds


def get_context_ids(cur: Any, config: SourceConfig) -> Mapping[str, int]:
    rows = query_dicts(
        cur,
        f"""
        SELECT sc.target_company_id, sc.target_branch_id, sc.target_perusahaan_cabang_id
          FROM {qtable(REGISTRY_SCHEMA, 'source_context')} sc
         WHERE sc.source_system = %s
        """,
        (config.source_system,),
    )
    if len(rows) != 1:
        raise ImporterError(f"source_context {config.source_system} tidak teresolusi tepat satu row")
    return {key: int(value) for key, value in rows[0].items()}


def insert_returning_id(cur: Any, schema: str, table: str, payload: Mapping[str, Any]) -> int:
    columns = list(payload)
    if not columns:
        raise ImporterError(f"Payload INSERT {schema}.{table} kosong")
    values_sql = ", ".join(["%s"] * len(columns))
    cur.execute(
        f"INSERT INTO {qtable(schema, table)} ({', '.join(qident(column) for column in columns)}) "
        f"VALUES ({values_sql}) RETURNING id",
        tuple(payload[column] for column in columns),
    )
    return int(cur.fetchone()[0])


def call_record_hold(cur: Any, import_run_id: int, hold: Hold) -> int:
    source_key = {
        "source_system": hold.row.source_system,
        "source_table": hold.row.table,
        "staging_id": hold.row.staging_id,
    }
    cur.execute(
        f"""
        SELECT {qident(REGISTRY_SCHEMA)}.record_import_hold(
            %s, 'master', %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb
        )
        """,
        (
            import_run_id,
            hold.row.source_system,
            hold.row.table,
            hold.row.schema,
            hold.row.run_id,
            hold.row.staging_id,
            hold.source_identity_sha256,
            hold.row.source_row_hash,
            stable_json(source_key),
            hold.reason,
            stable_json(dict(hold.details)),
        ),
    )
    return int(cur.fetchone()[0])


def approved_hold_resolution_note(approval: ApprovedHoldApproval) -> str:
    return (
        f"approved_skip manifest={approval.manifest_sha256}; "
        f"reference={approval.approval_reference}; approved_at={approval.approved_at}"
    )


def mark_hold_skipped(
    cur: Any,
    hold_id: int,
    approval: ApprovedHoldApproval,
) -> None:
    """Finalize the existing immutable hold evidence as an approved skip."""

    note = approved_hold_resolution_note(approval)
    cur.execute(
        f"""
        SELECT resolution_status, reviewed_by, resolution_note
          FROM {qtable(REGISTRY_SCHEMA, 'import_hold')}
         WHERE id = %s
        """,
        (hold_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise ImporterError("import_hold yang baru ditulis tidak dapat ditemukan")
    status, reviewed_by, resolution_note = row
    if status == "skipped":
        if reviewed_by != approval.approved_by or resolution_note != note:
            raise GuardError("Hold yang sama sudah memiliki approval berbeda dalam run ini")
        return
    if status != "open":
        raise GuardError(f"Hold {hold_id} berstatus {status}; tidak boleh dipaksa menjadi skip")
    cur.execute(
        f"""
        UPDATE {qtable(REGISTRY_SCHEMA, 'import_hold')}
           SET resolution_status = 'skipped', reviewed_by = %s, resolution_note = %s
         WHERE id = %s AND resolution_status = 'open'
        """,
        (approval.approved_by, note, hold_id),
    )
    if cur.rowcount != 1:
        raise GuardError("Status hold berubah saat approval sedang direkam; import dibatalkan")


def verify_approved_hold_records(
    cur: Any,
    import_run_id: int,
    approval: ApprovedHoldApproval,
) -> None:
    """Verify that the registry contains exactly the reviewed skip evidence."""

    cur.execute(
        f"""
        SELECT source_system, source_table, source_stage_schema, source_stage_run_id,
               source_staging_id, source_identity_sha256, source_row_hash,
               source_key, hold_reason, details, occurrence_count,
               resolution_status, reviewed_by, resolution_note
          FROM {qtable(REGISTRY_SCHEMA, 'import_hold')}
         WHERE import_run_id = %s AND phase = 'master'
         ORDER BY source_system, source_table, source_identity_sha256, hold_reason
        """,
        (import_run_id,),
    )
    actual_rows = cur.fetchall()
    expected_by_key = {
        (
            entry["source_system"],
            entry["source_table"],
            entry["source_identity_sha256"],
            entry["hold_reason"],
        ): entry
        for entry in approval.entries
    }
    if len(actual_rows) != len(expected_by_key):
        raise GuardError("Jumlah evidence hold registry tidak sama dengan manifest yang direview")
    note = approved_hold_resolution_note(approval)
    for row in actual_rows:
        (
            source_system,
            source_table,
            source_stage_schema,
            source_stage_run_id,
            source_staging_id,
            source_identity_sha256,
            source_row_hash,
            source_key,
            hold_reason,
            details,
            occurrence_count,
            resolution_status,
            reviewed_by,
            resolution_note,
        ) = row
        key = (source_system, source_table, source_identity_sha256, hold_reason)
        expected = expected_by_key.pop(key, None)
        if expected is None:
            raise GuardError("Registry memuat hold yang tidak tercantum pada manifest approval")
        if (
            source_stage_schema != expected["source_stage_schema"]
            or int(source_stage_run_id) != int(expected["source_stage_run_id"])
            or int(source_staging_id) != int(expected["source_staging_id"])
            or source_row_hash != expected["source_row_hash"]
            or stable_json(source_key) != stable_json(expected["source_key"])
            or stable_json(details) != stable_json(expected["details"])
            or int(occurrence_count) != int(expected["occurrence_count"])
            or resolution_status != "skipped"
            or reviewed_by != approval.approved_by
            or resolution_note != note
        ):
            raise GuardError("Evidence hold registry berbeda dari manifest approval; seluruh import dibatalkan")
    if expected_by_key:
        raise GuardError("Sebagian hold manifest tidak tercatat di registry; seluruh import dibatalkan")


def apply_plan(
    conn: Any,
    current_user: str,
    args: argparse.Namespace,
    configs: Mapping[str, SourceConfig],
    plan: MasterPlan,
) -> None:
    """Apply only after every structural contract has passed.

    This is reachable only after the clean-target-only registry extension has
    installed its UOM, price, plafon, and target-attestation contracts.  It
    deliberately creates no login users: sales carry a NULL ``id_user`` until
    a post-UAT authentication migration is approved separately.
    """

    baseline_schema_sha = validate_sha256(args.baseline_schema_sha256, "--baseline-schema-sha256")
    baseline_reference_sha = validate_sha256(args.baseline_reference_sha256, "--baseline-reference-sha256")
    reviewed_initial_plan_sha = plan_sha256(plan)

    # Start a new serializable write transaction only after the read-only plan
    # passed.  We lock the frozen stage, public reference/master area, and
    # registry, then rebuild the entire plan.  A changed policy, snapshot,
    # lookup, trigger contract, or hold cannot inherit a reviewed dry run.
    conn.set_session(isolation_level="SERIALIZABLE", readonly=False, autocommit=False)
    with conn.cursor() as cur:
        cur.execute("SET LOCAL lock_timeout = '5s'")
        cur.execute("SET LOCAL statement_timeout = '10min'")
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("migration_clean_bdm_tmp_202609:master",))
        for source_system in ("bdm_solo_dist", "tmp_solo_dist"):
            stage_schema = configs[source_system].stage_schema
            cur.execute(
                "LOCK TABLE "
                + ", ".join(
                    qtable(stage_schema, table)
                    for table in ("__stage_run", "__stage_manifest", *SOURCE_TABLES)
                )
                + " IN SHARE MODE"
            )
        cur.execute(
            "LOCK TABLE public.perusahaan, public.cabang, public.perusahaan_cabang, "
            "public.produk_tipe_harga, public.sales_tipe, public.jabatan IN SHARE MODE"
        )
        cur.execute(
            "LOCK TABLE public.principal, public.customer, public.sales, "
            "public.sales_detail, public.sales_principal_assignment, public.produk, "
            "public.produk_uom, public.produk_harga_jual, public.plafon IN SHARE ROW EXCLUSIVE MODE"
        )
        cur.execute(
            "LOCK TABLE "
            + ", ".join(
                qtable(REGISTRY_SCHEMA, table)
                for table in (
                    "source_context", "clean_target_attestation", "import_run",
                    "principal_source_map", "customer_source_map", "sales_source_map",
                    "product_source_map", "product_uom_source_map", "product_price_source_map",
                    "plafon_source_map", "import_hold", "reconciliation_result",
                )
            )
            + " IN SHARE ROW EXCLUSIVE MODE"
        )

        _, refreshed_configs, refreshed_policy_sha = load_policy(args.policy)
        if refreshed_configs != configs:
            raise GuardError("Policy source/context berubah setelah dry-run; apply dibatalkan")
        refreshed_plan = build_plan(
            cur,
            target_database=args.target_database,
            policy_sha256=refreshed_policy_sha,
            configs=refreshed_configs,
            args=args,
        )
        refreshed_counts = target_master_counts(cur)
        approved_holds = ensure_apply_request(args, refreshed_plan, refreshed_counts)
        if plan_sha256(refreshed_plan) != reviewed_initial_plan_sha:
            raise GuardError("Plan berubah setelah dry-run; jalankan dan review dry-run baru sebelum apply")
        plan = refreshed_plan

        # Context IDs are created exclusively by the DDL resolver; numeric
        # values never come from this script/policy/source staging.
        for source_system in ("bdm_solo_dist", "tmp_solo_dist"):
            config = configs[source_system]
            cur.execute(
                f"SELECT {qident(REGISTRY_SCHEMA)}.resolve_source_context(%s, %s, %s, %s)",
                (config.source_system, config.company_code, config.branch_code, config.document_prefix),
            )
        contexts = {source: get_context_ids(cur, configs[source]) for source in configs}

        cur.execute(
            f"SELECT 1 FROM {qtable(REGISTRY_SCHEMA, 'import_run')} WHERE import_key = %s",
            (args.import_key,),
        )
        if cur.fetchone() is not None:
            raise GuardError("--import-key sudah pernah dipakai; evidence lama tidak boleh ditimpa")

        bdm_stage = plan.stages["bdm_solo_dist"]
        tmp_stage = plan.stages["tmp_solo_dist"]
        run_metadata = {
            "script_version": SCRIPT_VERSION,
            "mode": "apply",
            "master_action_counts": {
                "principals": len(plan.principals),
                "customers": len(plan.customers),
                "sales": len(plan.sales),
                "products": len(plan.products),
                "uoms": len(plan.uoms),
                "prices": len(plan.prices),
                "plafon": len(plan.plafon),
                "holds": len(plan.holds),
            },
        }
        if approved_holds is not None:
            run_metadata["approved_hold_manifest"] = {
                "manifest_sha256": approved_holds.manifest_sha256,
                "approval_sha256": approved_holds.approval_sha256,
                "approved_by": approved_holds.approved_by,
                "approval_reference": approved_holds.approval_reference,
                "approved_at": approved_holds.approved_at,
                "hold_occurrences": approved_holds.hold_occurrences,
                "hold_entries": approved_holds.hold_entries,
            }
        cur.execute(
            f"""
            SELECT {qident(REGISTRY_SCHEMA)}.begin_import_run(
                %s, %s, 'master', %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s::jsonb, %s
            )
            """,
            (
                args.import_key,
                SCRIPT_VERSION,
                plan.policy_sha256,
                baseline_schema_sha,
                baseline_reference_sha,
                bdm_stage.schema,
                bdm_stage.run_id,
                bdm_stage.snapshot_label,
                bdm_stage.snapshot_sha256,
                tmp_stage.schema,
                tmp_stage.run_id,
                tmp_stage.snapshot_label,
                tmp_stage.snapshot_sha256,
                stable_json(run_metadata),
                current_user,
            ),
        )
        import_run_id = int(cur.fetchone()[0])

        principal_ids: dict[tuple[str, str], int] = {}
        for action in plan.principals:
            payload = {**action.payload, "id_perusahaan": contexts[action.row.source_system]["target_company_id"]}
            target_id = insert_returning_id(cur, "public", "principal", payload)
            cur.execute(
                f"""
                INSERT INTO {qtable(REGISTRY_SCHEMA, 'principal_source_map')} (
                    import_run_id, source_system, source_table, source_stage_schema, source_stage_run_id,
                    source_staging_id, source_row_hash, source_principal_code, source_principal_code_norm,
                    id_principal, mapping_method
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'source_created')
                """,
                (
                    import_run_id, action.row.source_system, action.row.table, action.row.schema, action.row.run_id,
                    action.row.staging_id, action.row.source_row_hash, action.source_code, action.source_code_norm, target_id,
                ),
            )
            principal_ids[(action.row.source_system, action.source_code_norm)] = target_id

        customer_ids: dict[tuple[str, str], int] = {}
        customer_price_type_ids: dict[tuple[str, str], int] = {}
        for action in plan.customers:
            if action.mapping_method == "bdm_shared_exact":
                assert action.shared_tmp_key is not None
                target_id = customer_ids[("tmp_solo_dist", action.shared_tmp_key[0])]
                price_type_id = customer_price_type_ids[("tmp_solo_dist", action.shared_tmp_key[0])]
            else:
                assert action.payload is not None
                payload = {**action.payload, "id_cabang": contexts[action.row.source_system]["target_branch_id"]}
                target_id = insert_returning_id(cur, "public", "customer", payload)
                price_type_id = int(action.payload["id_tipe_harga"])
            cur.execute(
                f"""
                INSERT INTO {qtable(REGISTRY_SCHEMA, 'customer_source_map')} (
                    import_run_id, source_system, source_table, source_stage_schema, source_stage_run_id,
                    source_staging_id, source_row_hash, source_customer_code, source_customer_code_norm,
                    source_store_name, source_store_name_norm, id_customer, mapping_method
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    import_run_id, action.row.source_system, action.row.table, action.row.schema, action.row.run_id,
                    action.row.staging_id, action.row.source_row_hash, action.source_code, action.source_code_norm,
                    action.source_name, action.source_name_norm, target_id, action.mapping_method,
                ),
            )
            customer_ids[(action.row.source_system, action.source_code_norm)] = target_id
            customer_price_type_ids[(action.row.source_system, action.source_code_norm)] = price_type_id

        sales_ids: dict[tuple[str, str, str], int] = {}
        for action in plan.sales:
            sales_payload = {
                **action.payload_sales,
                "id_user": None,
                "id_principal": principal_ids[(action.row.source_system, action.source_principal_code_norm)],
            }
            sales_id = insert_returning_id(cur, "public", "sales", sales_payload)
            insert_returning_id(cur, "public", "sales_detail", {**action.payload_sales_detail, "id_sales": sales_id})
            insert_returning_id(
                cur,
                "public",
                "sales_principal_assignment",
                {"id_sales": sales_id, "id_principal": principal_ids[(action.row.source_system, action.source_principal_code_norm)]},
            )
            cur.execute(
                f"""
                INSERT INTO {qtable(REGISTRY_SCHEMA, 'sales_source_map')} (
                    import_run_id, source_system, source_table, source_stage_schema, source_stage_run_id,
                    source_staging_id, source_row_hash, source_principal_code, source_principal_code_norm,
                    source_sales_code, source_sales_code_norm, id_sales, id_user, mapping_method
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'source_created')
                """,
                (
                    import_run_id, action.row.source_system, action.row.table, action.row.schema, action.row.run_id,
                    action.row.staging_id, action.row.source_row_hash, action.source_principal_code,
                    action.source_principal_code_norm, action.source_sales_code, action.source_sales_code_norm,
                    sales_id, None,
                ),
            )
            sales_ids[(action.row.source_system, action.source_principal_code_norm, action.source_sales_code_norm)] = sales_id

        product_ids: dict[tuple[str, str, str], int] = {}
        products_by_key: dict[tuple[str, str, str], ProductAction] = {
            (action.row.source_system, action.source_principal_code_norm, action.source_sku_norm): action
            for action in plan.products
        }
        for action in plan.products:
            payload = {**action.payload, "id_principal": principal_ids[(action.row.source_system, action.source_principal_code_norm)]}
            product_id = insert_returning_id(cur, "public", "produk", payload)
            if product_id > 2_147_483_647:
                raise ImporterError("produk.id melewati range produk_uom.id_produk integer")
            cur.execute(
                f"""
                INSERT INTO {qtable(REGISTRY_SCHEMA, 'product_source_map')} (
                    import_run_id, source_system, source_table, source_stage_schema, source_stage_run_id,
                    source_staging_id, source_row_hash, source_principal_code, source_principal_code_norm,
                    source_sku, source_sku_norm, id_produk, mapping_method
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'source_created')
                """,
                (
                    import_run_id, action.row.source_system, action.row.table, action.row.schema, action.row.run_id,
                    action.row.staging_id, action.row.source_row_hash, action.source_principal_code,
                    action.source_principal_code_norm, action.source_sku, action.source_sku_norm, product_id,
                ),
            )
            product_ids[(action.row.source_system, action.source_principal_code_norm, action.source_sku_norm)] = product_id

        for action in plan.uoms:
            product_id = product_ids[action.product_key]
            product = products_by_key[action.product_key]
            uom_payload = {**action.payload, "id_produk": product_id}
            product_uom_id = insert_returning_id(cur, "public", "produk_uom", uom_payload)
            cur.execute(
                f"""
                INSERT INTO {qtable(REGISTRY_SCHEMA, 'product_uom_source_map')} (
                    import_run_id, source_system, source_table, source_stage_schema, source_stage_run_id,
                    source_staging_id, source_row_hash, source_principal_code, source_principal_code_norm,
                    source_sku, source_sku_norm, source_uom_code, source_uom_code_norm,
                    source_uom_level, source_uom_ordinal, source_factor,
                    id_produk, id_produk_uom, mapping_method
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, 'source_created'
                )
                """,
                (
                    import_run_id, action.row.source_system, action.row.table, action.row.schema, action.row.run_id,
                    action.row.staging_id, action.row.source_row_hash,
                    product.source_principal_code, product.source_principal_code_norm,
                    product.source_sku, product.source_sku_norm, action.source_uom_code, action.source_uom_code_norm,
                    action.level, action.source_uom_ordinal, action.factor, product_id, product_uom_id,
                ),
            )

        for action in plan.prices:
            product_id = product_ids[action.product_key]
            price_type_id = exact_reference_id(cur, "produk_tipe_harga", "kode", action.target_price_type_code)
            if price_type_id is None:
                raise ImporterError("produk_tipe_harga berubah setelah dry-run; serializable apply dihentikan")
            price_id = insert_returning_id(
                cur,
                "public",
                "produk_harga_jual",
                {"id_produk": product_id, "id_tipe_harga": price_type_id, "harga": float(action.value)},
            )
            product = products_by_key[action.product_key]
            cur.execute(
                f"""
                INSERT INTO {qtable(REGISTRY_SCHEMA, 'product_price_source_map')} (
                    import_run_id, source_system, source_table, source_stage_schema, source_stage_run_id,
                    source_staging_id, source_row_hash, source_principal_code, source_principal_code_norm,
                    source_sku, source_sku_norm, source_price_column, source_price_column_norm,
                    target_price_type_code, target_price_type_code_norm, source_price,
                    id_produk, id_produk_harga_jual, mapping_method
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, 'source_created'
                )
                """,
                (
                    import_run_id, action.row.source_system, action.row.table, action.row.schema, action.row.run_id,
                    action.row.staging_id, action.row.source_row_hash,
                    product.source_principal_code, product.source_principal_code_norm,
                    product.source_sku, product.source_sku_norm,
                    action.source_price_column, norm(action.source_price_column),
                    action.target_price_type_code, norm(action.target_price_type_code),
                    action.value, product_id, price_id,
                ),
            )

        for action in plan.plafon:
            customer_key = (action.row.source_system, action.source_customer_code_norm)
            principal_key = (action.row.source_system, action.source_principal_code_norm)
            sales_key = (action.row.source_system, action.source_principal_code_norm, action.source_sales_code_norm)
            limit_bon, limit_problem = decimal_as_finite_float(action.limit_bon, "plafon_limit")
            if limit_problem or limit_bon is None:
                raise ImporterError("Nilai plafon berubah menjadi tidak dapat ditulis setelah dry-run")
            source_customer_code = action.row.value("kodecustomer")
            source_principal_code = action.row.value("kodeprinciple")
            source_sales_code = action.row.value("kodesales")
            if source_customer_code is None or source_principal_code is None or source_sales_code is None:
                raise ImporterError("Identity plafon berubah kosong setelah dry-run")
            plafon_payload = {
                "id_customer": customer_ids[customer_key],
                "id_principal": principal_ids[principal_key],
                "id_sales": sales_ids[sales_key],
                # Sales historical rows intentionally have no login account
                # in this phase; users are a later auth-reviewed migration.
                "id_user": None,
                "id_tipe_harga": customer_price_type_ids[customer_key],
                "limit_bon": limit_bon,
                # This is *not* source AR.  Zero plus lock_order=1 creates a
                # non-live credit state until opening AR is reconciled.
                "sisa_bon": 0.0,
                "top": action.term,
                "lock_order": "1",
                "tempo": action.term,
                "tempo_label": f"{action.term} Hari" if action.term > 0 else None,
            }
            plafon_id = insert_returning_id(cur, "public", "plafon", plafon_payload)
            cur.execute(
                f"""
                INSERT INTO {qtable(REGISTRY_SCHEMA, 'plafon_source_map')} (
                    import_run_id, source_system, source_table, source_stage_schema, source_stage_run_id,
                    source_staging_id, source_row_hash,
                    source_customer_code, source_customer_code_norm,
                    source_principal_code, source_principal_code_norm,
                    source_sales_code, source_sales_code_norm,
                    source_added_at_raw, source_added_at, source_limit_bon, source_term,
                    opening_balance_strategy, id_plafon, mapping_method
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, 'source_created'
                )
                """,
                (
                    import_run_id, action.row.source_system, action.row.table, action.row.schema, action.row.run_id,
                    action.row.staging_id, action.row.source_row_hash,
                    source_customer_code, action.source_customer_code_norm,
                    source_principal_code, action.source_principal_code_norm,
                    source_sales_code, action.source_sales_code_norm,
                    action.source_added_at_raw, action.source_added_at, action.limit_bon, action.term,
                    action.opening_balance_strategy, plafon_id,
                ),
            )

        if plan.holds:
            if approved_holds is None:
                raise GuardError("Hold ditemukan setelah preflight tanpa approval manifest; import dibatalkan")
            for hold in plan.holds:
                hold_id = call_record_hold(cur, import_run_id, hold)
                mark_hold_skipped(cur, hold_id, approved_holds)
            verify_approved_hold_records(cur, import_run_id, approved_holds)

            approved_scope = {
                "phase": "master",
                "approved_hold_manifest_sha256": approved_holds.manifest_sha256,
            }
            approved_expected = {
                "hold_occurrences": approved_holds.hold_occurrences,
                "hold_entries": approved_holds.hold_entries,
                "resolution_status": "skipped",
            }
            approved_actual = dict(approved_expected)
            cur.execute(
                f"SELECT {qident(REGISTRY_SCHEMA)}.record_reconciliation_result(%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, 'warning', 'held', %s, %s::jsonb)",
                (
                    import_run_id,
                    "approved_master_holds",
                    stable_hash(approved_scope),
                    stable_json(approved_scope),
                    stable_json(approved_expected),
                    stable_json(approved_actual),
                    stable_hash(
                        {
                            "scope": approved_scope,
                            "expected": approved_expected,
                            "actual": approved_actual,
                            "approval_sha256": approved_holds.approval_sha256,
                        }
                    ),
                    stable_json(
                        {
                            "approval_sha256": approved_holds.approval_sha256,
                            "approved_by": approved_holds.approved_by,
                            "approval_reference": approved_holds.approval_reference,
                            "approved_at": approved_holds.approved_at,
                        }
                    ),
                ),
            )

        scope = {"phase": "master", "import_key": args.import_key}
        expected = {"planned_principals": len(plan.principals), "planned_customers": len(plan.customers), "planned_products": len(plan.products)}
        actual = {"written_principals": len(principal_ids), "written_customers": len(customer_ids), "written_products": len(product_ids)}
        cur.execute(
            f"SELECT {qident(REGISTRY_SCHEMA)}.record_reconciliation_result(%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, 'info', 'pass', %s, %s::jsonb)",
            (
                import_run_id,
                "master_write_counts",
                stable_hash(scope),
                stable_json(scope),
                stable_json(expected),
                stable_json(actual),
                stable_hash({"scope": scope, "expected": expected, "actual": actual}),
                stable_json({"holds": len(plan.holds)}),
            ),
        )
        cur.execute(f"UPDATE {qtable(REGISTRY_SCHEMA, 'import_run')} SET status = 'verified' WHERE id = %s", (import_run_id,))
        cur.execute(f"UPDATE {qtable(REGISTRY_SCHEMA, 'import_run')} SET status = 'committed' WHERE id = %s", (import_run_id,))
    conn.commit()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dsn", required=True, help="DSN PostgreSQL clean target; harus menyertakan dbname eksplisit.")
    parser.add_argument("--target-database", required=True, help="Nama database clean yang harus sama persis dengan dbname DSN.")
    parser.add_argument("--policy", type=Path, default=policy_path_default(), help="Path clean_import_policy.json.")
    parser.add_argument("--bdm-stage-run-id", type=int, help="Pilih stage run BDM eksplisit bila schema memiliki lebih dari satu run completed.")
    parser.add_argument("--tmp-stage-run-id", type=int, help="Pilih stage run TMP eksplisit bila schema memiliki lebih dari satu run completed.")
    parser.add_argument(
        "--customer-pricing-tax-policy-json",
        type=Path,
        help="Policy eksplisit legacy OpsHarga/FP -> target id_tipe_harga/is_ppn; tanpa ini customer di-hold.",
    )
    parser.add_argument(
        "--product-tax-policy-json",
        type=Path,
        help="Policy eksplisit legacy FakturPajak -> target persen PPN; tanpa ini produk di-hold.",
    )
    parser.add_argument("--sales-policy-json", type=Path, help="Policy eksplisit jabatan/type/non-login user untuk mengaktifkan planning sales/users.")
    parser.add_argument("--price-policy-json", type=Path, help="Policy eksplisit source price column -> produk_tipe_harga.kode.")
    parser.add_argument(
        "--write-hold-manifest",
        type=Path,
        help=(
            "Dry-run only: tulis envelope hold exact untuk direview. File ini belum merupakan approval "
            "sampai reviewer mengisi bagian approval dan --apply memakai SHA manifest yang sama."
        ),
    )
    parser.add_argument("--apply", action="store_true", help="Tulis ke clean target hanya setelah semua guard/schema contract lulus.")
    parser.add_argument("--import-key", help="Kunci import immutable; wajib dengan --apply.")
    parser.add_argument("--baseline-schema-sha256", help="Checksum schema-only baseline; wajib dengan --apply.")
    parser.add_argument("--baseline-reference-sha256", help="Checksum allow-list reference baseline; wajib dengan --apply.")
    parser.add_argument("--reviewed-plan-sha256", help="Plan SHA-256 dari dry-run yang direview; wajib dengan --apply.")
    parser.add_argument(
        "--approved-hold-manifest-json",
        type=Path,
        help="Envelope hold generated yang telah diisi approval; hanya diperlukan bila dry-run masih memiliki hold.",
    )
    parser.add_argument(
        "--approved-hold-manifest-sha256",
        help="SHA-256 inner hold manifest exact yang direview; wajib bersama approval envelope saat ada hold.",
    )
    parser.add_argument(
        "--acknowledge-approved-holds",
        action="store_true",
        help="Acknowledgement eksplisit bahwa seluruh hold pada manifest yang tepat akan diskip dari target blue/green.",
    )
    parser.add_argument("--report-json", type=Path, help="Simpan ringkasan dry-run JSON lokal (tidak pernah memuat DSN/password).")
    return parser.parse_args(argv)


def write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    assert_clean_target_database_name(args.target_database, label="--target-database")
    if args.apply and args.write_hold_manifest is not None:
        raise GuardError("--write-hold-manifest hanya boleh dipakai pada dry-run, bukan bersama --apply")
    if args.bdm_stage_run_id is not None and args.bdm_stage_run_id <= 0:
        raise GuardError("--bdm-stage-run-id harus positif")
    if args.tmp_stage_run_id is not None and args.tmp_stage_run_id <= 0:
        raise GuardError("--tmp-stage-run-id harus positif")

    _, configs, policy_sha = load_policy(args.policy)
    conn, current_user = connect_checked(args, readonly=not args.apply)
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '10min'")
            plan = build_plan(cur, target_database=args.target_database, policy_sha256=policy_sha, configs=configs, args=args)
            counts = target_master_counts(cur)
        report = plan_report(plan, counts)
        if args.write_hold_manifest:
            report["hold_manifest"]["written_to"] = str(args.write_hold_manifest)
            write_hold_approval_envelope(args.write_hold_manifest, plan)
        if args.report_json:
            write_report(args.report_json, report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        if not args.apply:
            conn.rollback()
            return 0

        ensure_apply_request(args, plan, counts)
        # The transaction used for planning is read-write in apply mode only to
        # allow immediate guard introspection.  It has performed no writes and
        # is rolled back before entering the serializable write transaction.
        conn.rollback()
        apply_plan(conn, current_user, args, configs, plan)
        print(json.dumps({"mode": "APPLIED", "import_key": args.import_key, "target_database": args.target_database}, ensure_ascii=False))
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
