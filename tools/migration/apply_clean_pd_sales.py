#!/usr/bin/env python3
"""Apply one reviewed canonical PD manifest to a *UAT-only* clean database.

The program is deliberately separate from the legacy active-sales importer.
It has no SQL Server connection and is dry-run by default.  ``--apply`` is
accepted only for an explicitly named ``budimas_clean_uat_*`` target, with an
approved JSON envelope bound to the immutable PD report/plan fingerprints.

The only business rows it can ever insert are draft ``sales_order``, a
numberless draft ``faktur``, exactly one ``faktur_detail`` per source header,
and ``sales_order_detail`` rows.  It additionally writes only the clean
registry's source maps, open holds, reconciliation evidence, and import run.
It never writes stock, HPP, picking, shipping, delivery, manifest/route,
payment/AR, return, credit-note, or plafon balance tables.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from import_clean_bdm_tmp_master import (  # type: ignore[import-not-found]
    REGISTRY_SCHEMA,
    GuardError,
    ImporterError,
    assert_clean_target_database_name,
    assert_dsn_has_explicit_database,
    clean,
    fetch_columns,
    load_policy,
    norm,
    observed_target_baselines,
    query_dicts,
    qident,
    qtable,
    require_psycopg2,
    sha256_file,
    stable_hash,
    stable_json,
    table_exists,
    validate_sha256,
    verify_clean_target_attestation,
)
from report_clean_pd_sales_manifest import (  # type: ignore[import-not-found]
    REPORT_VERSION as PD_REPORT_VERSION,
    SOURCE_DETAIL_TABLE,
    SOURCE_HEADER_TABLE,
    SOURCE_SYSTEMS,
    DocumentPlan,
    DraftPolicy,
    Hold,
    StageInfo,
    available_header_audit_columns,
    build_report,
    fetch_details,
    fetch_headers,
    json_safe,
    load_existing_documents,
    load_master_maps,
    load_source_contexts,
    parse_draft_policy,
    plan_pd_documents,
    resolve_stage,
    validate_target_contract,
)


SCRIPT_VERSION = "apply-clean-pd-sales-uat-20260902.1"
APPROVAL_FORMAT = "clean-pd-sales-uat-approval-v1"
# The blue/green naming convention predates this writer.  Accept a clean
# database only when its *final token* begins with ``uat`` (for example
# ``budimas_clean_20260902_v2_uat01``), never a generic/baseline clean DB.
UAT_DATABASE_RE = re.compile(r"^budimas_clean_(?:[a-z0-9_]*_)?uat[0-9a-z_]*$")
IMPORT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,119}$")
TARGET_CONFIRMATION = "I_APPROVE_PD_UAT_APPLY"
REQUIRED_ACKNOWLEDGEMENTS = {
    "compound_discount_percentage_not_reconstructed",
    "numberless_faktur_draft_only",
    "no_stock_picking_route_payment_or_return",
    "holds_recorded_open_not_imported",
    "uat_only_no_production_or_baseline",
}

# This is deliberately separate from the reporter plan.  The reporter binds
# source rows/master/UOM/money; the apply contract binds the exact *target*
# values that a reviewer authorizes.  The script file digest makes an edited
# DML implementation require a new approval even if the source plan remains
# unchanged.
APPLY_CONTRACT = {
    "format": "clean-pd-sales-uat-apply-contract-v1",
    "source_scope": {"header": "HJualSM", "detail": "DJualSM", "status": "PD"},
    "target": {
        "sales_order": {
            "status_order": 0,
            "no_faktur": None,
            "tanggal_faktur": None,
            "tanggal_terkirim": None,
        },
        "faktur": {
            "status_faktur": 0,
            "no_faktur": None,
            "jenis_faktur": "penjualan",
            "nama_fakturist": "MIGRASI_PD_UAT",
            "total_dana_diterima": "0",
            "nominal_retur": "0",
        },
        "faktur_detail": {"exactly_one_per_document": True},
        "sales_order_detail": {
            "booked": 0,
            "picked": 0,
            "shipped": 0,
            "delivered": 0,
            "subtotaldelivered": "0",
            "total_persen_diskon": "0",
        },
    },
    "registry_order": [
        "import_run", "sales_order", "faktur", "faktur_detail", "sales_document_map",
        "sales_order_detail", "sales_document_line_map", "open_holds", "reconciliation", "commit",
    ],
    "prohibited_operations": [
        "stock", "picking", "shipping", "delivery", "route", "payment", "return", "credit_note",
    ],
}
TARGET_TRANSACTION_TABLES = ("sales_order", "sales_order_detail", "faktur", "faktur_detail")
SIDE_EFFECT_TABLES = (
    "proses_picking",
    "wms_picking_task",
    "wms_picking_task_detail",
    "wms_picking_detail",
    "wms_loading_task",
    "wms_loading_task_detail",
    "wms_loading_manifest",
    "wms_loading_manifest_detail",
    "inventory_ledger",
    "stock_ledger",
    "stock_movement",
    "stock_movement_detail",
    "stok_mutasi",
    "stok_gudang",
    "setoran_customer",
    "setoran",
    "payment_voucher_usage",
    "pembayaran",
    "piutang",
    "surat_jalan",
    "pengiriman",
    "manifest",
    "delivery",
    "delivery_detail",
    "rute",
    "rute_pengiriman",
    "retur",
    "retur_detail",
    "retur_request",
    "retur_request_detail",
    "credit_note",
    "credit_note_detail",
)


class ApplyError(ImporterError):
    """Raised when a UAT PD apply request does not meet the exact contract."""


@dataclass(frozen=True)
class ReportBinding:
    report_sha256: str
    plan_sha256: str
    clean_policy_sha256: str
    pd_policy_sha256: str
    target_database: str
    candidate_documents: int
    candidate_lines: int
    hold_sha256: str
    hold_count: int


@dataclass(frozen=True)
class Approval:
    approval_sha256: str
    apply_contract_sha256: str
    approved_by: str
    approval_reference: str
    approved_at: str


@dataclass(frozen=True)
class RebuiltPlan:
    report: Mapping[str, Any]
    clean_policy_sha256: str
    pd_policy_sha256: str
    draft: DraftPolicy
    stages: Mapping[str, StageInfo]
    target_contract: Mapping[str, Any]
    documents: tuple[DocumentPlan, ...]
    holds: tuple[Hold, ...]
    structural_blockers: tuple[Mapping[str, Any], ...]
    baseline_schema_sha256: str | None
    baseline_reference_sha256: str | None


def assert_uat_target_database_name(value: str, *, label: str) -> None:
    """A generic clean target is not enough: this writer is UAT-only."""

    assert_clean_target_database_name(value, label=label)
    if not UAT_DATABASE_RE.fullmatch(value):
        raise GuardError(
            f"{label} harus bernama budimas_clean_uat_*; target clean non-UAT/baseline ditolak."
        )


def text_field(value: Any, label: str) -> str:
    result = clean(value)
    if result is None or len(result) > 240 or "\n" in result or "\r" in result:
        raise GuardError(f"{label} harus teks satu baris 1-240 karakter.")
    return result


def approval_timestamp(value: Any) -> str:
    text = clean(value)
    if text is None:
        raise GuardError("approval.approved_at wajib timestamp ISO-8601 bertimezone.")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GuardError("approval.approved_at bukan timestamp ISO-8601 valid.") from exc
    if parsed.tzinfo is None:
        raise GuardError("approval.approved_at wajib menyertakan timezone.")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GuardError(f"{label} tidak ditemukan: {path}") from exc
    except json.JSONDecodeError as exc:
        raise GuardError(f"{label} bukan JSON valid: {path}") from exc
    if not isinstance(value, Mapping):
        raise GuardError(f"{label} harus JSON object.")
    return value


def hold_digest(report: Mapping[str, Any]) -> tuple[str, int]:
    holds = report.get("holds")
    if not isinstance(holds, list):
        raise GuardError("Report PD tidak memiliki daftar holds valid.")
    return stable_hash(holds), len(holds)


def current_apply_contract_sha256() -> str:
    """Fingerprint the approved target mapping and exact local applier code."""

    return stable_hash(
        {
            "apply_contract": APPLY_CONTRACT,
            "script_version": SCRIPT_VERSION,
            "script_sha256": sha256_file(Path(__file__)),
            "planner_sha256": sha256_file(Path(__file__).with_name("report_clean_pd_sales_manifest.py")),
            "master_helper_sha256": sha256_file(Path(__file__).with_name("import_clean_bdm_tmp_master.py")),
        }
    )


def validate_report_binding(report: Mapping[str, Any], target_database: str) -> ReportBinding:
    """Validate an immutable reporter artifact before a database connection."""

    if report.get("format") != "clean-pd-sales-manifest-v1":
        raise GuardError("--report-json bukan clean PD sales manifest yang didukung.")
    if report.get("report_version") != PD_REPORT_VERSION:
        raise GuardError("Versi report PD tidak cocok dengan applier ini; buat report baru.")
    declared_report_sha = validate_sha256(clean(report.get("report_sha256")), "report.report_sha256")
    report_without_sha = {key: value for key, value in report.items() if key != "report_sha256"}
    if stable_hash(report_without_sha) != declared_report_sha:
        raise GuardError("Checksum report PD tidak valid; file report telah berubah.")
    declared_plan_sha = validate_sha256(clean(report.get("plan_sha256")), "report.plan_sha256")
    access = report.get("database_access")
    if not isinstance(access, Mapping):
        raise GuardError("Report PD tidak memiliki database_access valid.")
    report_database = clean(access.get("target_database"))
    if report_database != target_database:
        raise GuardError("Target database pada report tidak sama dengan --target-database.")
    if (
        access.get("transaction_isolation") != "REPEATABLE READ"
        or access.get("transaction_read_only") is not True
        or access.get("target_database_writes") is not False
        or access.get("sql_server_access") is not False
        or access.get("apply_mode_supported") is not False
    ):
        raise GuardError("Report PD harus berasal dari reporter read-only tanpa akses SQL Server/write.")
    assert_uat_target_database_name(target_database, label="target database report")
    mapping = report.get("status_mapping")
    if not isinstance(mapping, Mapping) or mapping != {
        "source_status": "PD",
        "sales_order_status": 0,
        "faktur_status": 0,
        "no_faktur": None,
        "tanggal_faktur": None,
        "tanggal_terkirim": None,
    }:
        raise GuardError("Report PD tidak memakai mapping draft PD 0/0 numberless yang wajib.")
    scope = report.get("scope")
    if (
        not isinstance(scope, Mapping)
        or scope.get("canonical_source_family") != "HJualSM + DJualSM"
        or scope.get("source_status_exact") != "PD"
        or scope.get("source_systems") != list(SOURCE_SYSTEMS)
    ):
        raise GuardError("Scope report bukan HJualSM/DJualSM PD kanonik.")
    policies = report.get("policies")
    if not isinstance(policies, Mapping) or policies.get("pd_draft_policy_approval_status") != "draft_review_only":
        raise GuardError("Report tidak terikat pada PD draft review policy yang benar.")
    target_mapping = report.get("target_draft_mapping")
    if not isinstance(target_mapping, Mapping):
        raise GuardError("Report PD tidak memiliki target_draft_mapping valid.")
    not_planned = target_mapping.get("not_planned")
    required_absent = {
        "delivery_confirmation", "picking", "stock_or_hpp_ledger",
        "payment_or_receivable_settlement", "return_or_credit_note", "manifest_or_route_assignment",
    }
    if not isinstance(not_planned, list) or not required_absent.issubset(set(not_planned)):
        raise GuardError("Report PD tidak mendeklarasikan seluruh operasi terlarang sebagai absent.")
    counts = report.get("counts")
    if not isinstance(counts, Mapping):
        raise GuardError("Report PD tidak memiliki counts valid.")
    candidates = counts.get("candidate_documents")
    lines = counts.get("candidate_lines")
    if not isinstance(candidates, int) or candidates < 0 or not isinstance(lines, int) or lines < 0:
        raise GuardError("Counts kandidat pada report PD tidak valid.")
    clean_sha = validate_sha256(clean(policies.get("clean_policy_sha256")), "report.clean_policy_sha256")
    pd_sha = validate_sha256(clean(policies.get("pd_draft_policy_sha256")), "report.pd_draft_policy_sha256")
    holds_sha, holds_count = hold_digest(report)
    return ReportBinding(
        report_sha256=declared_report_sha,
        plan_sha256=declared_plan_sha,
        clean_policy_sha256=clean_sha,
        pd_policy_sha256=pd_sha,
        target_database=target_database,
        candidate_documents=candidates,
        candidate_lines=lines,
        hold_sha256=holds_sha,
        hold_count=holds_count,
    )


def pending_approval_template(
    binding: ReportBinding,
    *,
    baseline_schema_sha256: str | None,
    baseline_reference_sha256: str | None,
) -> Mapping[str, Any]:
    return {
        "format": APPROVAL_FORMAT,
        "approval": {
            "approval_status": "pending_review",
            "environment": "uat",
            "target_database": binding.target_database,
            "approved_plan_sha256": binding.plan_sha256,
            "approved_report_sha256": binding.report_sha256,
            "approved_apply_contract_sha256": current_apply_contract_sha256(),
            "approved_clean_policy_sha256": binding.clean_policy_sha256,
            "approved_pd_draft_policy_sha256": binding.pd_policy_sha256,
            "approved_baseline_schema_sha256": baseline_schema_sha256,
            "approved_baseline_reference_sha256": baseline_reference_sha256,
            "approved_candidate_documents": binding.candidate_documents,
            "approved_candidate_lines": binding.candidate_lines,
            "approved_hold_sha256": binding.hold_sha256,
            "approved_hold_count": binding.hold_count,
            "hold_disposition": "record_open_do_not_import",
            "approved_by": None,
            "approval_reference": None,
            "approved_at": None,
            "acknowledgements": {
                "compound_discount_percentage_not_reconstructed": False,
                "numberless_faktur_draft_only": False,
                "no_stock_picking_route_payment_or_return": False,
                "holds_recorded_open_not_imported": False,
                "uat_only_no_production_or_baseline": False,
            },
        },
    }


def validate_approval(
    path: Path | None,
    binding: ReportBinding,
    plan: RebuiltPlan,
) -> Approval:
    if path is None:
        raise GuardError("--apply memerlukan --approval-json yang sudah approved.")
    envelope = read_json(path, "approval JSON PD UAT")
    if set(envelope) != {"format", "approval"} or envelope.get("format") != APPROVAL_FORMAT:
        raise GuardError("Approval JSON PD UAT harus memiliki format/envelope yang tepat.")
    approval = envelope.get("approval")
    expected_keys = {
        "approval_status", "environment", "target_database", "approved_plan_sha256",
        "approved_report_sha256", "approved_apply_contract_sha256",
        "approved_clean_policy_sha256", "approved_pd_draft_policy_sha256",
        "approved_baseline_schema_sha256", "approved_baseline_reference_sha256",
        "approved_candidate_documents", "approved_candidate_lines", "approved_hold_sha256",
        "approved_hold_count", "hold_disposition", "approved_by", "approval_reference",
        "approved_at", "acknowledgements",
    }
    if not isinstance(approval, Mapping) or set(approval) != expected_keys:
        raise GuardError("Field approval JSON PD UAT tidak tepat; gunakan template yang digenerate.")
    if approval.get("approval_status") != "approved" or approval.get("environment") != "uat":
        raise GuardError("Approval harus approval_status=approved dan environment=uat.")
    if approval.get("target_database") != binding.target_database:
        raise GuardError("Approval target_database tidak sama dengan report/target saat ini.")
    for key, expected in (
        ("approved_plan_sha256", binding.plan_sha256),
        ("approved_report_sha256", binding.report_sha256),
        ("approved_apply_contract_sha256", current_apply_contract_sha256()),
        ("approved_clean_policy_sha256", binding.clean_policy_sha256),
        ("approved_pd_draft_policy_sha256", binding.pd_policy_sha256),
        ("approved_baseline_schema_sha256", plan.baseline_schema_sha256),
        ("approved_baseline_reference_sha256", plan.baseline_reference_sha256),
        ("approved_hold_sha256", binding.hold_sha256),
    ):
        actual = validate_sha256(clean(approval.get(key)), f"approval.{key}")
        if actual != expected:
            raise GuardError(f"approval.{key} tidak cocok dengan report/target yang direbuild.")
    if approval.get("approved_candidate_documents") != binding.candidate_documents:
        raise GuardError("approval.approved_candidate_documents tidak cocok.")
    if approval.get("approved_candidate_lines") != binding.candidate_lines:
        raise GuardError("approval.approved_candidate_lines tidak cocok.")
    if approval.get("approved_hold_count") != binding.hold_count:
        raise GuardError("approval.approved_hold_count tidak cocok.")
    if approval.get("hold_disposition") != "record_open_do_not_import":
        raise GuardError("Hold PD harus tetap direkam open dan tidak boleh diimpor/diskip.")
    acknowledgements = approval.get("acknowledgements")
    if not isinstance(acknowledgements, Mapping) or set(acknowledgements) != REQUIRED_ACKNOWLEDGEMENTS:
        raise GuardError("Acknowledgements approval PD UAT tidak lengkap.")
    if any(acknowledgements.get(key) is not True for key in REQUIRED_ACKNOWLEDGEMENTS):
        raise GuardError("Seluruh acknowledgement UAT PD wajib true sebelum --apply.")
    normalized = {
        "approval_status": "approved",
        "environment": "uat",
        "target_database": binding.target_database,
        "approved_plan_sha256": binding.plan_sha256,
        "approved_report_sha256": binding.report_sha256,
        "approved_apply_contract_sha256": current_apply_contract_sha256(),
        "approved_clean_policy_sha256": binding.clean_policy_sha256,
        "approved_pd_draft_policy_sha256": binding.pd_policy_sha256,
        "approved_baseline_schema_sha256": plan.baseline_schema_sha256,
        "approved_baseline_reference_sha256": plan.baseline_reference_sha256,
        "approved_candidate_documents": binding.candidate_documents,
        "approved_candidate_lines": binding.candidate_lines,
        "approved_hold_sha256": binding.hold_sha256,
        "approved_hold_count": binding.hold_count,
        "hold_disposition": "record_open_do_not_import",
        "approved_by": text_field(approval.get("approved_by"), "approval.approved_by"),
        "approval_reference": text_field(approval.get("approval_reference"), "approval.approval_reference"),
        "approved_at": approval_timestamp(approval.get("approved_at")),
        "acknowledgements": dict(sorted((str(key), bool(value)) for key, value in acknowledgements.items())),
    }
    return Approval(
        approval_sha256=stable_hash(normalized),
        apply_contract_sha256=normalized["approved_apply_contract_sha256"],
        approved_by=normalized["approved_by"],
        approval_reference=normalized["approval_reference"],
        approved_at=normalized["approved_at"],
    )


def write_json_once(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = json.dumps(json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GuardError(f"Output lokal tidak dapat diverifikasi: {path}") from exc
        if stable_json(existing) != stable_json(payload):
            raise GuardError(f"Output lokal sudah ada dan berbeda: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
    except FileExistsError:
        write_json_once(path, payload)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dsn", help="DSN PostgreSQL eksplisit ke target budimas_clean_uat_*.")
    parser.add_argument("--target-database", help="Nama target UAT yang harus sama persis dengan DSN.")
    parser.add_argument("--report-json", type=Path, help="Manifest PD immutable yang sudah direview.")
    parser.add_argument("--approval-json", type=Path, help="Envelope approval JSON; wajib hanya bersama --apply.")
    parser.add_argument("--apply", action="store_true", help="Terapkan ke UAT setelah seluruh gate serializable lolos.")
    parser.add_argument("--import-key", help="Identity import UAT baru, lower-case [a-z0-9_.-].")
    parser.add_argument(
        "--confirm-uat-apply",
        help=f"Harus persis {TARGET_CONFIRMATION} bersama --apply.",
    )
    parser.add_argument(
        "--policy", type=Path, default=Path(__file__).with_name("clean_import_policy.json"),
        help="Clean policy frozen BDM/TMP.",
    )
    parser.add_argument(
        "--pd-draft-policy", type=Path,
        default=Path(__file__).with_name("policy_drafts") / "clean_pd_sales_manifest_20260902.draft.json",
        help="PD policy draft yang digunakan oleh reporter.",
    )
    parser.add_argument("--bdm-stage-run-id", type=int, help="Run BDM exact; bila diisi wajib sama report.")
    parser.add_argument("--tmp-stage-run-id", type=int, help="Run TMP exact; bila diisi wajib sama report.")
    parser.add_argument("--statement-timeout-seconds", type=int, default=600)
    parser.add_argument("--output", type=Path, help="Output JSON lokal immutable untuk ringkasan dry-run/apply.")
    parser.add_argument(
        "--write-approval-template", type=Path,
        help="Pada dry-run, tulis template approval dengan SHA report/current baseline yang sudah terisi.",
    )
    parser.add_argument("--self-test", action="store_true", help="Validasi helper lokal tanpa koneksi database.")
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace) -> None:
    if args.self_test:
        return
    if not args.dsn or not args.target_database or args.report_json is None:
        raise GuardError("--dsn, --target-database, dan --report-json wajib.")
    assert_uat_target_database_name(args.target_database, label="--target-database")
    if not 1 <= args.statement_timeout_seconds <= 3600:
        raise GuardError("--statement-timeout-seconds harus 1..3600.")
    for label, value in (("--bdm-stage-run-id", args.bdm_stage_run_id), ("--tmp-stage-run-id", args.tmp_stage_run_id)):
        if value is not None and value <= 0:
            raise GuardError(f"{label} harus positif.")
    if args.apply:
        if args.write_approval_template is not None:
            raise GuardError("--write-approval-template hanya untuk dry-run, bukan --apply.")
        if args.approval_json is None:
            raise GuardError("--apply memerlukan --approval-json.")
        if args.confirm_uat_apply != TARGET_CONFIRMATION:
            raise GuardError("--apply memerlukan --confirm-uat-apply literal UAT yang tepat.")
        if not args.import_key or not IMPORT_KEY_RE.fullmatch(args.import_key):
            raise GuardError("--apply memerlukan --import-key lower-case 3-120 karakter.")
        if args.output is not None:
            raise GuardError("--output tidak boleh dipakai bersama --apply; receipt committed hanya dicetak ke stdout agar kegagalan I/O lokal tidak memicu retry ambigu.")
    elif args.approval_json is not None:
        raise GuardError("--approval-json hanya boleh dipakai bersama --apply.")


def connect_target(args: argparse.Namespace, *, readonly: bool) -> tuple[Any, str]:
    psycopg2 = require_psycopg2()
    assert_dsn_has_explicit_database(psycopg2, args.dsn, args.target_database)
    try:
        conn = psycopg2.connect(args.dsn, application_name="budimas-clean-pd-sales-uat-applier")
    except Exception as exc:
        raise GuardError("Koneksi target UAT gagal; DSN tidak dicetak demi keamanan.") from exc
    try:
        # Verify the endpoint in autocommit mode, then leave *no open
        # transaction*.  For --apply the next transaction must begin with
        # physical table locks, before a SERIALIZABLE snapshot is acquired.
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_user")
            database, user = cur.fetchone()
        if str(database) != args.target_database:
            raise GuardError("current_database tidak cocok dengan --target-database.")
        assert_uat_target_database_name(str(database), label="current_database")
        # Session-only timeout configuration happens outside the future apply
        # transaction, so it cannot create its serializable snapshot either.
        with conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = '{args.statement_timeout_seconds}s'")
            cur.execute("SET lock_timeout = '5s'")
        conn.set_session(
            isolation_level="REPEATABLE READ" if readonly else "SERIALIZABLE",
            readonly=readonly,
            # Configure default transaction characteristics while autocommit
            # is still enabled, so this SET cannot become an apply snapshot.
            autocommit=True,
        )
        conn.autocommit = False
        return conn, str(user)
    except Exception:
        conn.close()
        raise


def add_blocker(blockers: list[Mapping[str, Any]], code: str, detail: str, **extra: Any) -> None:
    """Append one deterministic, credential-free blocker exactly once."""

    item: Mapping[str, Any] = {"code": code, "detail": detail, **json_safe(extra)}
    marker = stable_json(item)
    if not any(stable_json(existing) == marker for existing in blockers):
        blockers.append(item)


def stage_id_from_report(report: Mapping[str, Any], source: str) -> int:
    stages = report.get("stages")
    if not isinstance(stages, Mapping) or not isinstance(stages.get(source), Mapping):
        raise GuardError(f"Report PD tidak memiliki stage {source}.")
    try:
        run_id = int(stages[source]["run_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise GuardError(f"Report PD memiliki run_id {source} tidak valid.") from exc
    if run_id <= 0:
        raise GuardError(f"Report PD memiliki run_id {source} tidak positif.")
    return run_id


def assert_stage_args_match_report(args: argparse.Namespace, report: Mapping[str, Any]) -> None:
    for source, actual in (
        ("bdm_solo_dist", args.bdm_stage_run_id),
        ("tmp_solo_dist", args.tmp_stage_run_id),
    ):
        if actual is not None and actual != stage_id_from_report(report, source):
            raise GuardError(f"--{source[:3]}-stage-run-id tidak sama dengan report PD.")


def target_transaction_counts(cur: Any) -> Mapping[str, int]:
    """Count only relations this writer is allowed to create.

    An UAT apply is deliberately initial-load-only.  Reusing a target with
    sales rows would make target ownership and registry provenance ambiguous,
    even if a particular document happens not to collide.
    """

    counts: dict[str, int] = {}
    for table in TARGET_TRANSACTION_TABLES:
        if not table_exists(cur, "public", table):
            counts[table] = -1
            continue
        cur.execute(f"SELECT count(*)::bigint FROM {qtable('public', table)}")
        counts[table] = int(cur.fetchone()[0])
    for table in ("sales_document_map", "sales_document_line_map"):
        if not table_exists(cur, REGISTRY_SCHEMA, table):
            counts[f"{REGISTRY_SCHEMA}.{table}"] = -1
            continue
        cur.execute(f"SELECT count(*)::bigint FROM {qtable(REGISTRY_SCHEMA, table)}")
        counts[f"{REGISTRY_SCHEMA}.{table}"] = int(cur.fetchone()[0])
    return counts


def target_empty_blockers(cur: Any) -> list[Mapping[str, Any]]:
    counts = target_transaction_counts(cur)
    blockers: list[Mapping[str, Any]] = []
    missing = sorted(name for name, count in counts.items() if count < 0)
    if missing:
        add_blocker(
            blockers,
            "uat_target_transaction_relation_missing",
            "Target UAT tidak memiliki seluruh relation transaksi/registry yang wajib.",
            missing=missing,
        )
    non_empty = {name: count for name, count in counts.items() if count > 0}
    if non_empty:
        add_blocker(
            blockers,
            "uat_target_transactions_not_empty",
            "Apply PD hanya boleh ke target UAT transaksi kosong; buat clone UAT baru, jangan adopsi row lama.",
            counts=non_empty,
        )
    return blockers


def rebuild_plan(
    cur: Any,
    args: argparse.Namespace,
    *,
    require_empty_target: bool,
) -> RebuiltPlan:
    """Re-execute the read-only PD planner inside the current transaction.

    The report JSON is evidence, not an executable plan.  This function is
    intentionally the sole bridge to the reporter planner so an apply cannot
    reuse stale IDs, stale master maps, or a changed frozen stage.
    """

    _policy_payload, configs, clean_policy_sha256 = load_policy(args.policy)
    draft, pd_policy_sha256 = parse_draft_policy(args.pd_draft_policy)
    stages = {
        source: resolve_stage(
            cur,
            configs[source],
            args.bdm_stage_run_id if source == "bdm_solo_dist" else args.tmp_stage_run_id,
            draft,
        )
        for source in SOURCE_SYSTEMS
    }
    target_contract, blockers, target_counts = validate_target_contract(cur, draft)
    observed_schema_sha256, observed_reference_sha256, baseline_blockers = observed_target_baselines(cur)
    blockers.extend(baseline_blockers)
    blockers.extend(
        verify_clean_target_attestation(
            cur,
            target_database=args.target_database,
            observed_schema_sha256=observed_schema_sha256,
            observed_reference_sha256=observed_reference_sha256,
        )
    )
    if require_empty_target:
        blockers.extend(target_empty_blockers(cur))

    required_registry = {
        "source_context", "import_run", "principal_source_map", "customer_source_map",
        "sales_source_map", "product_source_map", "product_uom_source_map",
        "product_price_source_map", "plafon_source_map", "sales_document_map",
        "sales_document_line_map",
    }
    required_public = {"sales_order", "sales_order_detail", "faktur", "faktur_detail", "produk_harga_jual"}
    missing_registry = required_registry - set(target_contract.get("registry", {}))
    missing_public = required_public - set(target_contract.get("public", {}))
    header_audit_columns_by_source = {
        source: available_header_audit_columns(cur, stages[source]) for source in SOURCE_SYSTEMS
    }
    headers_by_source = {
        source: fetch_headers(cur, stages[source], audit_columns=header_audit_columns_by_source[source])
        for source in SOURCE_SYSTEMS
    }
    details_by_source = {source: fetch_details(cur, stages[source]) for source in SOURCE_SYSTEMS}
    if missing_registry or missing_public:
        # Never query potentially absent maps just to produce more partial
        # candidates.  A future apply must fail on the structural contract.
        master: Mapping[str, Any] = {"summary": {"not_loaded_due_to_target_contract": True}}
        documents: list[DocumentPlan] = []
        holds: list[Hold] = []
        source_summary: Mapping[str, Any] = {
            source: {
                "canonical_header_rows": len(headers_by_source[source]),
                "canonical_detail_rows": len(details_by_source[source]),
                "not_planned_due_to_target_contract": True,
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
            money_tolerance=Decimal(draft.money_reconciliation["header_detail_total_tolerance_rp"]),
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
        money_tolerance=Decimal(draft.money_reconciliation["header_detail_total_tolerance_rp"]),
    )
    return RebuiltPlan(
        report=report,
        clean_policy_sha256=clean_policy_sha256,
        pd_policy_sha256=pd_policy_sha256,
        draft=draft,
        stages=stages,
        target_contract=target_contract,
        documents=tuple(documents),
        holds=tuple(holds),
        structural_blockers=tuple(blockers),
        baseline_schema_sha256=observed_schema_sha256,
        baseline_reference_sha256=observed_reference_sha256,
    )


def assert_rebuilt_matches_report(
    binding: ReportBinding,
    supplied_report: Mapping[str, Any],
    rebuilt: RebuiltPlan,
) -> None:
    """Require a byte-semantic fingerprint match, not merely equal counts."""

    rebuilt_report = rebuilt.report
    current_report_sha = validate_sha256(clean(rebuilt_report.get("report_sha256")), "current report_sha256")
    current_plan_sha = validate_sha256(clean(rebuilt_report.get("plan_sha256")), "current plan_sha256")
    if current_report_sha != binding.report_sha256 or current_plan_sha != binding.plan_sha256:
        raise GuardError(
            "Frozen PD plan/report berubah sejak review; buat report dan approval baru. Tidak ada apply dilakukan."
        )
    # The declared JSON checksum was checked above.  Comparing semantic shape
    # catches a hypothetical reporter regression where its hash contract would
    # accidentally omit an execution-relevant field.
    if stable_json(rebuilt_report) != stable_json(supplied_report):
        raise GuardError("Report PD yang direbuild tidak identik dengan artefak review.")
    if rebuilt.clean_policy_sha256 != binding.clean_policy_sha256:
        raise GuardError("Clean policy saat ini tidak sama dengan report reviewed.")
    if rebuilt.pd_policy_sha256 != binding.pd_policy_sha256:
        raise GuardError("PD draft policy saat ini tidak sama dengan report reviewed.")
    if rebuilt.structural_blockers:
        raise GuardError("Target/stage/master contract memiliki structural blocker; apply ditolak.")
    rebuilt_hold_sha, rebuilt_hold_count = hold_digest(rebuilt_report)
    if rebuilt_hold_sha != binding.hold_sha256 or rebuilt_hold_count != binding.hold_count:
        raise GuardError("Fingerprint hold PD berubah sejak review; apply ditolak.")
    counts = rebuilt_report.get("counts")
    if not isinstance(counts, Mapping) or counts.get("candidate_documents") != binding.candidate_documents or counts.get("candidate_lines") != binding.candidate_lines:
        raise GuardError("Count kandidat current plan tidak sama dengan report reviewed.")


def lock_relation_if_present(cur: Any, schema: str, table: str, mode: str) -> None:
    if table_exists(cur, schema, table):
        cur.execute(f"LOCK TABLE {qtable(schema, table)} IN {mode} MODE")


def lock_required_relation(cur: Any, schema: str, table: str, mode: str) -> None:
    """Lock a contract relation without a preceding SELECT/snapshot."""

    try:
        cur.execute(f"LOCK TABLE {qtable(schema, table)} IN {mode} MODE")
    except Exception as exc:
        raise GuardError(f"Relation wajib untuk lock apply tidak tersedia: {schema}.{table}") from exc


def user_business_trigger_blockers(cur: Any) -> list[Mapping[str, Any]]:
    rows = query_dicts(
        cur,
        """
        SELECT c.relname AS table_name, t.tgname AS trigger_name,
               pg_get_triggerdef(t.oid, true) AS definition
          FROM pg_trigger t
          JOIN pg_class c ON c.oid = t.tgrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public'
           AND c.relname = ANY(%s)
           AND NOT t.tgisinternal
         ORDER BY c.relname, t.tgname
        """,
        (list(TARGET_TRANSACTION_TABLES),),
    )
    return [
        {
            "code": "target_business_trigger_unreviewed",
            "detail": "Target memiliki user trigger pada tabel draft; applier tidak menonaktifkan atau menebak efeknya.",
            "table": row["table_name"],
            "trigger": row["trigger_name"],
            "definition": row["definition"],
        }
        for row in rows
    ]


def business_rewrite_rule_blockers(cur: Any) -> list[Mapping[str, Any]]:
    """Rules can rewrite INSERT/UPDATE without appearing in pg_trigger."""

    rows = query_dicts(
        cur,
        """
        SELECT c.relname AS table_name, r.rulename,
               pg_get_ruledef(r.oid, true) AS definition
          FROM pg_rewrite r
          JOIN pg_class c ON c.oid = r.ev_class
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public'
           AND c.relname = ANY(%s)
           AND r.rulename <> '_RETURN'
         ORDER BY c.relname, r.rulename
        """,
        (list(TARGET_TRANSACTION_TABLES),),
    )
    return [
        {
            "code": "target_business_rewrite_rule_unreviewed",
            "detail": "Target memiliki rewrite rule pada tabel draft; applier tidak menonaktifkan atau menebak efeknya.",
            "table": row["table_name"],
            "rule": row["rulename"],
            "definition": row["definition"],
        }
        for row in rows
    ]


def side_effect_counts(cur: Any) -> Mapping[str, int]:
    counts: dict[str, int] = {}
    for table in SIDE_EFFECT_TABLES:
        if table_exists(cur, "public", table):
            cur.execute(f"SELECT count(*)::bigint FROM {qtable('public', table)}")
            counts[table] = int(cur.fetchone()[0])
    return counts


def write_contract_blockers(cur: Any) -> list[Mapping[str, Any]]:
    """Reject unknown required business columns instead of inventing values."""

    columns = fetch_columns(cur, "public", TARGET_TRANSACTION_TABLES)
    supplied = {
        "sales_order": {
            "id_plafon", "tanggal_order", "tanggal_faktur", "tanggal_terkirim",
            "tanggal_jatuh_tempo", "nama_sales", "pic_customer", "keterangan",
            "status_order", "total_order", "no_order", "no_faktur", "id_cabang",
        },
        "faktur": {
            "id_sales_order", "no_faktur", "nama_fakturist", "status_faktur", "jenis_faktur", "subtotal_penjualan",
            "subtotal_diskon", "total_penjualan", "total_dana_diterima", "pajak", "dpp",
            "draft_total_penjualan", "nominal_retur",
        },
        "faktur_detail": {
            "id_faktur", "id_sales_order", "id_principal", "subtotal_diskon", "subtotal",
            "pajak", "draft_total", "total",
        },
        "sales_order_detail": {
            "id_sales_order", "id_produk", "hargaorder", "subtotaldelivered", "is_bonus",
            "pieces_order", "box_order", "karton_order", "pieces_booked", "box_booked", "karton_booked",
            "pieces_picked", "box_picked", "karton_picked", "pieces_shipped", "box_shipped", "karton_shipped",
            # These appear on the currently audited target.  They are written
            # as explicit draft-safe zero/derived values if present.
            "pieces_delivered", "box_delivered", "karton_delivered", "subtotalorder",
            "total_nilai_discount", "total_persen_diskon", "estimasi_kubikasi",
        },
    }
    blockers: list[Mapping[str, Any]] = []
    for table in TARGET_TRANSACTION_TABLES:
        if table not in columns:
            add_blocker(blockers, "target_write_table_missing", "Tabel target apply tidak ada.", table=table)
            continue
        for name, column in columns[table].items():
            if column.needs_insert_value and name not in supplied[table]:
                add_blocker(
                    blockers,
                    "target_required_column_unmapped",
                    "Kolom NOT NULL tanpa default belum memiliki mapping PD draft aman.",
                    table=table,
                    column=name,
                )
    return blockers


def assert_draft_null_contract(cur: Any) -> None:
    """The PD contract is intentionally numberless and undelivered."""

    columns = fetch_columns(cur, "public", ("sales_order", "faktur"))
    required_nulls = (
        ("sales_order", "no_faktur"),
        ("sales_order", "tanggal_faktur"),
        ("sales_order", "tanggal_terkirim"),
        ("faktur", "no_faktur"),
    )
    bad = [
        f"{table}.{column}"
        for table, column in required_nulls
        if table not in columns or column not in columns[table] or not columns[table][column].nullable
    ]
    if bad:
        raise GuardError(
            "Target tidak mendukung draft PD numberless/undelivered (kolom wajib nullable): "
            + ", ".join(bad)
        )


def payload_length_blockers(
    documents: Sequence[DocumentPlan],
    draft: DraftPolicy,
    columns: Mapping[str, Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Check values outside the reporter's minimal contract before any write."""

    blockers: list[Mapping[str, Any]] = []
    for plan in documents:
        payloads = document_payload(plan, draft, columns)
        for table, payload in payloads.items():
            for name, value in payload.items():
                limit = getattr(columns[table].get(name), "max_length", None)
                if isinstance(value, str) and limit is not None and len(value) > limit:
                    add_blocker(
                        blockers,
                        "target_payload_text_exceeds_length",
                        "Nilai sumber tidak muat pada kolom target; tidak ada pemotongan otomatis.",
                        table=table,
                        column=name,
                        source_system=plan.row.source_system,
                        source_nota=plan.source_nota,
                        max_length=limit,
                        actual_length=len(value),
                    )
    return blockers


def insert_returning_id(cur: Any, table: str, payload: Mapping[str, Any]) -> int:
    if not payload:
        raise ApplyError(f"Payload kosong untuk public.{table}.")
    columns = tuple(payload)
    sql = (
        f"INSERT INTO {qtable('public', table)} "
        f"({', '.join(qident(column) for column in columns)}) "
        f"VALUES ({', '.join(['%s'] * len(columns))}) RETURNING id"
    )
    cur.execute(sql, tuple(payload[column] for column in columns))
    value = cur.fetchone()
    if value is None or int(value[0]) <= 0:
        raise ApplyError(f"INSERT public.{table} tidak menghasilkan id valid.")
    return int(value[0])


def present_payload(columns: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    """Use optional mapped fields only when the concrete UAT table has them."""

    return {name: value for name, value in payload.items() if name in columns}


def document_payload(plan: DocumentPlan, draft: DraftPolicy, columns: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Mapping[str, Any]]:
    """Map one exact planned document to **draft-only** target rows.

    Notice that source discount percentages are compound in the final PD
    policy.  There is no safe generic single-percent representation in the
    target; fixed discount evidence is retained in `total_nilai_discount` and
    the percent aggregate is deliberately zero.  The approved report retains
    the raw components/formula for review.
    """

    zero = Decimal("0")
    sales_order = present_payload(
        columns["sales_order"],
        {
            "id_plafon": plan.plafon.id_plafon,
            "tanggal_order": plan.tanggal_order,
            "tanggal_faktur": None,
            "tanggal_terkirim": None,
            "tanggal_jatuh_tempo": plan.tanggal_jatuh_tempo,
            "nama_sales": plan.row.namasales or "",
            "pic_customer": plan.row.namacustomer or "",
            "keterangan": plan.row.keterangan,
            "status_order": draft.status_order,
            "total_order": plan.total_penjualan,
            "no_order": plan.sales_order_code,
            "no_faktur": None,
        },
    )
    # `id_cabang` belongs to the frozen source context, not to customer
    # identity.  It is filled by the caller after stage validation.
    faktur = present_payload(
        columns["faktur"],
        {
            "id_sales_order": None,
            "no_faktur": None,
            "nama_fakturist": "MIGRASI_PD_UAT",
            "status_faktur": draft.status_faktur,
            "jenis_faktur": "penjualan",
            "subtotal_penjualan": plan.subtotal_dpp,
            "subtotal_diskon": plan.subtotal_diskon,
            "total_penjualan": plan.total_penjualan,
            "total_dana_diterima": zero,
            "pajak": plan.pajak,
            "dpp": plan.subtotal_dpp,
            "draft_total_penjualan": plan.total_penjualan,
            "nominal_retur": zero,
        },
    )
    faktur_detail = present_payload(
        columns["faktur_detail"],
        {
            "id_faktur": None,
            "id_sales_order": None,
            "id_principal": plan.id_principal,
            "subtotal_diskon": plan.subtotal_diskon,
            "subtotal": plan.subtotal_dpp,
            "pajak": plan.pajak,
            "draft_total": plan.total_penjualan,
            "total": plan.total_penjualan,
        },
    )
    return {"sales_order": sales_order, "faktur": faktur, "faktur_detail": faktur_detail}


def line_payload(
    plan: DocumentPlan,
    line: Any,
    id_sales_order: int,
    columns: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    zero = Decimal("0")
    bonus_value: bool | int = (
        False
        if getattr(columns["sales_order_detail"].get("is_bonus"), "udt_name", None) == "bool"
        else 0
    )
    return present_payload(
        columns["sales_order_detail"],
        {
            "hargaorder": line.harga_order,
            "subtotaldelivered": zero,
            "is_bonus": bonus_value,
            "estimasi_kubikasi": zero,
            "id_sales_order": id_sales_order,
            "id_produk": line.id_produk,
            "pieces_order": line.pieces_order,
            "box_order": line.box_order,
            "karton_order": line.karton_order,
            "pieces_booked": 0,
            "box_booked": 0,
            "karton_booked": 0,
            "pieces_picked": 0,
            "box_picked": 0,
            "karton_picked": 0,
            "pieces_shipped": 0,
            "box_shipped": 0,
            "karton_shipped": 0,
            "pieces_delivered": 0,
            "box_delivered": 0,
            "karton_delivered": 0,
            "subtotalorder": line.subtotal_order,
            "total_nilai_discount": line.discount_amount,
            "total_persen_diskon": zero,
        },
    )


def insert_document_map(
    cur: Any,
    *,
    run_id: int,
    plan: DocumentPlan,
    id_sales_order: int,
    id_faktur: int,
    id_faktur_detail: int,
) -> None:
    row = plan.row
    principal = clean(row.kodeprinciple)
    if principal is None:
        raise ApplyError("Planner menghasilkan kandidat dengan principal header kosong.")
    cur.execute(
        f"""
        INSERT INTO {qtable(REGISTRY_SCHEMA, 'sales_document_map')} (
            import_run_id, source_system, source_header_table,
            source_stage_schema, source_stage_run_id, source_staging_id, source_row_hash,
            source_nota, source_nota_norm, source_principal_code, source_principal_code_norm,
            id_sales_order, id_faktur, id_faktur_detail
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            run_id, row.source_system, SOURCE_HEADER_TABLE,
            row.stage_schema, row.stage_run_id, row.staging_id, row.source_row_hash,
            plan.source_nota, plan.source_nota_norm, principal, norm(principal),
            id_sales_order, id_faktur, id_faktur_detail,
        ),
    )


def insert_line_map(cur: Any, *, run_id: int, plan: DocumentPlan, line: Any, id_detail: int) -> None:
    row = line.row
    principal = clean(plan.row.kodeprinciple)
    sku = clean(row.kodestok)
    uom = clean(row.ct)
    if principal is None or sku is None or uom is None:
        raise ApplyError("Planner menghasilkan kandidat line dengan identity registry kosong.")
    cur.execute(
        f"""
        INSERT INTO {qtable(REGISTRY_SCHEMA, 'sales_document_line_map')} (
            import_run_id, source_system, source_header_table, source_line_table,
            source_stage_schema, source_stage_run_id, source_staging_id, source_row_hash,
            source_nota, source_nota_norm, source_urut, source_urut_norm,
            source_principal_code, source_principal_code_norm, source_sku, source_sku_norm,
            source_uom_code, source_uom_code_norm, source_uom_level, source_factor,
            id_sales_order_detail
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            run_id, row.source_system, SOURCE_HEADER_TABLE, SOURCE_DETAIL_TABLE,
            row.stage_schema, row.stage_run_id, row.staging_id, row.source_row_hash,
            plan.source_nota, plan.source_nota_norm, row.urut, line.source_urut_norm,
            principal, norm(principal), sku, norm(sku), uom, norm(uom), line.outer_level,
            line.outer_factor, id_detail,
        ),
    )


def assert_candidate_hold_disjoint(documents: Sequence[DocumentPlan], holds: Sequence[Hold]) -> None:
    """A held source identity must never also become an insert candidate."""

    candidate_headers = {
        (document.row.source_system, document.row.stage_schema, document.row.stage_run_id, document.row.staging_id)
        for document in documents
    }
    overlaps = [
        hold.as_json()
        for hold in holds
        if hold.source_table == SOURCE_HEADER_TABLE
        and hold.staging_id is not None
        and (hold.source_system, hold.stage_schema, hold.stage_run_id, hold.staging_id) in candidate_headers
    ]
    if overlaps:
        raise ApplyError(
            "Planner menghasilkan kandidat yang juga memiliki hold header; tidak ada skip/fallback yang diizinkan."
        )


def assert_holds_fit_registry(holds: Sequence[Hold]) -> None:
    """The registry must retain every reviewed hold entry exactly once."""

    seen: set[tuple[Any, ...]] = set()
    duplicate: list[Mapping[str, Any]] = []
    for hold in holds:
        if hold.staging_id is None or hold.source_row_hash is None:
            raise ApplyError("Hold tanpa staging_id/source_row_hash tidak dapat direkam secara immutable.")
        key = (
            hold.source_system, hold.source_table, hold.stage_schema, hold.stage_run_id,
            hold.staging_id, hold.reason,
        )
        if key in seen:
            duplicate.append(hold.as_json())
        seen.add(key)
    if duplicate:
        raise ApplyError(
            "Report memiliki hold berbeda yang akan berbenturan pada identity immutable registry; perbaiki/pecah policy hold sebelum apply. "
            + stable_json(duplicate[:5])
        )


def begin_import_run(
    cur: Any,
    *,
    args: argparse.Namespace,
    rebuilt: RebuiltPlan,
    binding: ReportBinding,
    approval: Approval,
    current_user: str,
) -> int:
    bdm = rebuilt.stages["bdm_solo_dist"]
    tmp = rebuilt.stages["tmp_solo_dist"]
    if rebuilt.baseline_schema_sha256 is None or rebuilt.baseline_reference_sha256 is None:
        raise ApplyError("Baseline UAT tidak dapat di-attest sehingga import run tidak boleh dibuat.")
    metadata = {
        "mode": "approved_uat_pd_apply",
        "report_sha256": binding.report_sha256,
        "plan_sha256": binding.plan_sha256,
        "approval_sha256": approval.approval_sha256,
        "apply_contract_sha256": approval.apply_contract_sha256,
        "approval_reference": approval.approval_reference,
        "approved_by": approval.approved_by,
        "approved_at": approval.approved_at,
        "hold_sha256": binding.hold_sha256,
        "hold_count": binding.hold_count,
        "candidate_documents": binding.candidate_documents,
        "candidate_lines": binding.candidate_lines,
        "operations_explicitly_absent": [
            "stock", "picking", "shipping", "delivery", "route", "payment", "return",
        ],
        "discount_percent_target_value": "0",
        "discount_percent_reason": "source percentage components are compound; no generic single-percent target mapping",
    }
    cur.execute(
        f"""
        SELECT {qtable(REGISTRY_SCHEMA, 'begin_import_run')}(
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s,
            %s::jsonb, %s
        )
        """,
        (
            args.import_key, SCRIPT_VERSION, "sales", rebuilt.clean_policy_sha256,
            rebuilt.baseline_schema_sha256, rebuilt.baseline_reference_sha256,
            bdm.schema, bdm.run_id, f"{bdm.schema}:run-{bdm.run_id}", bdm.snapshot_sha256,
            tmp.schema, tmp.run_id, f"{tmp.schema}:run-{tmp.run_id}", tmp.snapshot_sha256,
            stable_json(json_safe(metadata)), current_user,
        ),
    )
    row = cur.fetchone()
    if row is None or int(row[0]) <= 0:
        raise ApplyError("begin_import_run tidak menghasilkan id valid.")
    return int(row[0])


def record_open_holds(cur: Any, *, run_id: int, holds: Sequence[Hold]) -> int:
    """Persist only immutable, still-open source holds—never a skip decision."""

    recorded = 0
    for hold in sorted(holds, key=lambda item: stable_json(item.as_json())):
        if hold.staging_id is None or hold.source_row_hash is None:
            raise ApplyError("Hold tanpa staging_id/source_row_hash tidak dapat direkam secara immutable.")
        source_key = {
            "source_system": hold.source_system,
            "source_table": hold.source_table,
            "stage_schema": hold.stage_schema,
            "stage_run_id": hold.stage_run_id,
            "staging_id": hold.staging_id,
            "source_nota_norm": hold.nota_norm,
            "source_urut_norm": hold.urut_norm,
        }
        source_identity = stable_hash(source_key)
        cur.execute(
            f"""
            SELECT {qtable(REGISTRY_SCHEMA, 'record_import_hold')}(
                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s::jsonb, %s, %s::jsonb, %s, %s
            )
            """,
            (
                run_id, "sales", hold.source_system, hold.source_table,
                hold.stage_schema, hold.stage_run_id, hold.staging_id, source_identity,
                hold.source_row_hash, stable_json(json_safe(source_key)), hold.reason,
                stable_json(json_safe(hold.details or {})), hold.nota, hold.urut,
            ),
        )
        result = cur.fetchone()
        if result is None or int(result[0]) <= 0:
            raise ApplyError("record_import_hold tidak menghasilkan id valid.")
        recorded += 1
    return recorded


def current_run_counts(cur: Any, run_id: int) -> Mapping[str, int]:
    queries = {
        "sales_document_map": f"SELECT count(*)::bigint FROM {qtable(REGISTRY_SCHEMA, 'sales_document_map')} WHERE import_run_id = %s",
        "sales_document_line_map": f"SELECT count(*)::bigint FROM {qtable(REGISTRY_SCHEMA, 'sales_document_line_map')} WHERE import_run_id = %s",
        "holds": f"SELECT count(*)::bigint FROM {qtable(REGISTRY_SCHEMA, 'import_hold')} WHERE import_run_id = %s AND resolution_status = 'open'",
        "faktur_detail": f"""
            SELECT count(*)::bigint
              FROM {qtable(REGISTRY_SCHEMA, 'sales_document_map')} dm
              JOIN public.faktur_detail fd ON fd.id = dm.id_faktur_detail
             WHERE dm.import_run_id = %s
        """,
        "sales_order_detail": f"""
            SELECT count(*)::bigint
              FROM {qtable(REGISTRY_SCHEMA, 'sales_document_line_map')} lm
              JOIN public.sales_order_detail sod ON sod.id = lm.id_sales_order_detail
             WHERE lm.import_run_id = %s
        """,
    }
    queries["one_faktur_detail_per_document"] = f"""
        SELECT count(*)::bigint
          FROM {qtable(REGISTRY_SCHEMA, 'sales_document_map')} dm
          JOIN {qtable(REGISTRY_SCHEMA, 'principal_source_map')} pm
            ON pm.source_system = dm.source_system
           AND pm.source_principal_code_norm = dm.source_principal_code_norm
         WHERE dm.import_run_id = %s
           AND 1 = (
               SELECT count(*)
                 FROM public.faktur_detail fd
                WHERE fd.id_faktur = dm.id_faktur
                  AND fd.id_sales_order = dm.id_sales_order
                  AND fd.id_principal = pm.id_principal
           )
    """
    results: dict[str, int] = {}
    for key, sql in queries.items():
        cur.execute(sql, (run_id,))
        results[key] = int(cur.fetchone()[0])
    return results


def record_reconciliation(
    cur: Any,
    *,
    run_id: int,
    binding: ReportBinding,
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
    name: str,
    severity: str,
    status: str,
    details: Mapping[str, Any] | None = None,
) -> None:
    scope = {
        "target_database": binding.target_database,
        "report_sha256": binding.report_sha256,
        "plan_sha256": binding.plan_sha256,
        "check": name,
    }
    fingerprint = stable_hash({"scope": scope, "expected": json_safe(expected), "actual": json_safe(actual), "status": status})
    cur.execute(
        f"""
        SELECT {qtable(REGISTRY_SCHEMA, 'record_reconciliation_result')}(
            %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s, %s::jsonb
        )
        """,
        (
            run_id, name, stable_hash(scope), stable_json(json_safe(scope)),
            stable_json(json_safe(expected)), stable_json(json_safe(actual)),
            severity, status, fingerprint, stable_json(json_safe(details or {})),
        ),
    )
    if cur.fetchone() is None:
        raise ApplyError(f"record_reconciliation_result gagal untuk {name}.")


def apply_rebuilt_plan(
    cur: Any,
    *,
    args: argparse.Namespace,
    rebuilt: RebuiltPlan,
    binding: ReportBinding,
    approval: Approval,
    current_user: str,
) -> Mapping[str, Any]:
    """Insert only the approved PD draft rows and immutable evidence."""

    blockers = (
        user_business_trigger_blockers(cur)
        + business_rewrite_rule_blockers(cur)
        + write_contract_blockers(cur)
    )
    public_columns = fetch_columns(cur, "public", TARGET_TRANSACTION_TABLES)
    blockers.extend(payload_length_blockers(rebuilt.documents, rebuilt.draft, public_columns))
    if blockers:
        raise GuardError("Kontrak UAT tidak aman untuk direct draft insert: " + stable_json(blockers))
    assert_draft_null_contract(cur)
    assert_candidate_hold_disjoint(rebuilt.documents, rebuilt.holds)
    assert_holds_fit_registry(rebuilt.holds)
    before_side_effects = side_effect_counts(cur)
    run_id = begin_import_run(
        cur, args=args, rebuilt=rebuilt, binding=binding, approval=approval, current_user=current_user
    )
    inserted_documents = 0
    inserted_lines = 0
    for plan in sorted(rebuilt.documents, key=lambda item: (item.row.source_system, item.source_nota_norm, item.row.staging_id)):
        payloads = document_payload(plan, rebuilt.draft, public_columns)
        stage = rebuilt.stages[plan.row.source_system]
        payloads["sales_order"]["id_cabang"] = stage.target_branch_id
        id_sales_order = insert_returning_id(cur, "sales_order", payloads["sales_order"])
        payloads["faktur"]["id_sales_order"] = id_sales_order
        id_faktur = insert_returning_id(cur, "faktur", payloads["faktur"])
        payloads["faktur_detail"]["id_faktur"] = id_faktur
        payloads["faktur_detail"]["id_sales_order"] = id_sales_order
        id_faktur_detail = insert_returning_id(cur, "faktur_detail", payloads["faktur_detail"])
        insert_document_map(
            cur,
            run_id=run_id,
            plan=plan,
            id_sales_order=id_sales_order,
            id_faktur=id_faktur,
            id_faktur_detail=id_faktur_detail,
        )
        for line in plan.lines:
            id_detail = insert_returning_id(
                cur, "sales_order_detail", line_payload(plan, line, id_sales_order, public_columns)
            )
            insert_line_map(cur, run_id=run_id, plan=plan, line=line, id_detail=id_detail)
            inserted_lines += 1
        inserted_documents += 1
    recorded_holds = record_open_holds(cur, run_id=run_id, holds=rebuilt.holds)
    actual = current_run_counts(cur, run_id)
    expected = {
        "sales_document_map": inserted_documents,
        "sales_document_line_map": inserted_lines,
        "faktur_detail": inserted_documents,
        "sales_order_detail": inserted_lines,
        "one_faktur_detail_per_document": inserted_documents,
        "holds": recorded_holds,
    }
    if actual != expected:
        record_reconciliation(
            cur, run_id=run_id, binding=binding, expected=expected, actual=actual,
            name="pd_draft_rows_and_registry", severity="fatal", status="fail",
        )
        raise ApplyError("Rekonsiliasi PD draft/registry tidak cocok; transaksi akan rollback.")
    record_reconciliation(
        cur, run_id=run_id, binding=binding, expected=expected, actual=actual,
        name="pd_draft_rows_and_registry", severity="fatal", status="pass",
        details={"faktur_numbering": "NULL", "status_order": 0, "status_faktur": 0},
    )
    post_side_effects = side_effect_counts(cur)
    if post_side_effects != before_side_effects:
        record_reconciliation(
            cur, run_id=run_id, binding=binding, expected=before_side_effects, actual=post_side_effects,
            name="prohibited_side_effect_relations_unchanged", severity="fatal", status="fail",
        )
        raise ApplyError("Tabel stock/picking/route/payment/return berubah; transaksi akan rollback.")
    record_reconciliation(
        cur, run_id=run_id, binding=binding, expected=before_side_effects, actual=post_side_effects,
        name="prohibited_side_effect_relations_unchanged", severity="fatal", status="pass",
    )
    record_reconciliation(
        cur,
        run_id=run_id,
        binding=binding,
        expected={"holds": binding.hold_count, "disposition": "open_do_not_import"},
        actual={"holds": recorded_holds, "resolution_status": "open"},
        name="reviewed_holds_recorded_open",
        severity="info",
        status="held" if recorded_holds else "pass",
    )
    cur.execute(
        f"UPDATE {qtable(REGISTRY_SCHEMA, 'import_run')} SET status = 'verified' WHERE id = %s AND status = 'started'",
        (run_id,),
    )
    if cur.rowcount != 1:
        raise ApplyError("import_run tidak dapat dipindahkan ke verified.")
    cur.execute(
        f"UPDATE {qtable(REGISTRY_SCHEMA, 'import_run')} SET status = 'committed' WHERE id = %s AND status = 'verified'",
        (run_id,),
    )
    if cur.rowcount != 1:
        raise ApplyError("import_run tidak dapat dipindahkan ke committed.")
    return {
        "import_run_id": run_id,
        "approval_sha256": approval.approval_sha256,
        "apply_contract_sha256": approval.apply_contract_sha256,
        "inserted_sales_order": inserted_documents,
        "inserted_faktur": inserted_documents,
        "inserted_faktur_detail": inserted_documents,
        "inserted_sales_order_detail": inserted_lines,
        "recorded_open_holds": recorded_holds,
        "side_effect_counts": post_side_effects,
    }


def lock_apply_scope_from_policy(cur: Any, args: argparse.Namespace) -> None:
    """Acquire locks from the frozen local policy *before* planning writes."""

    _payload, configs, _policy_sha = load_policy(args.policy)
    # Do not run SELECT/table_exists here.  PostgreSQL obtains a serializable
    # snapshot at the first query, therefore all stage/master/target locks
    # need to precede advisory locking and planner reads.
    for source in SOURCE_SYSTEMS:
        schema = configs[source].stage_schema
        for table in ("__stage_run", "__stage_manifest", "hjualsm", "djualsm"):
            lock_required_relation(cur, schema, table, "SHARE")
    for table in (
        "sales_order", "sales_order_detail", "faktur", "faktur_detail",
        "perusahaan", "cabang", "perusahaan_cabang", "principal", "customer", "users",
        "sales", "sales_detail", "sales_principal_assignment", "sales_tipe", "jabatan",
        "produk", "produk_uom", "produk_harga_jual", "produk_tipe_harga", "plafon",
    ):
        lock_required_relation(cur, "public", table, "SHARE ROW EXCLUSIVE")
    for table in (
        "source_context", "import_run", "principal_source_map", "customer_source_map",
        "sales_source_map", "product_source_map", "product_uom_source_map",
        "product_price_source_map", "plafon_source_map", "sales_document_map",
        "sales_document_line_map", "import_hold", "reconciliation_result", "clean_target_attestation",
    ):
        lock_required_relation(cur, REGISTRY_SCHEMA, table, "SHARE ROW EXCLUSIVE")
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{REGISTRY_SCHEMA}:pd-sales-uat-apply",))
    for table in SIDE_EFFECT_TABLES:
        lock_relation_if_present(cur, "public", table, "SHARE ROW EXCLUSIVE")


def assert_output_path_fresh(path: Path | None) -> None:
    if path is not None and path.exists():
        raise GuardError(f"--output harus path baru agar bukti hasil tidak tertimpa: {path}")


def result_payload(
    *,
    mode: str,
    binding: ReportBinding,
    rebuilt: RebuiltPlan,
    result: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    return {
        "format": "clean-pd-sales-uat-apply-result-v1",
        "script_version": SCRIPT_VERSION,
        "mode": mode,
        "target_database": binding.target_database,
        "report_sha256": binding.report_sha256,
        "plan_sha256": binding.plan_sha256,
        "clean_policy_sha256": binding.clean_policy_sha256,
        "pd_draft_policy_sha256": binding.pd_policy_sha256,
        "apply_contract_sha256": current_apply_contract_sha256(),
        "baseline_schema_sha256": rebuilt.baseline_schema_sha256,
        "baseline_reference_sha256": rebuilt.baseline_reference_sha256,
        "candidate_documents": binding.candidate_documents,
        "candidate_lines": binding.candidate_lines,
        "hold_sha256": binding.hold_sha256,
        "hold_count": binding.hold_count,
        "mapping": {
            "source_status": "PD",
            "sales_order_status": 0,
            "faktur_status": 0,
            "no_faktur": None,
            "tanggal_faktur": None,
            "tanggal_terkirim": None,
        },
        "operations_explicitly_absent": [
            "stock", "picking", "shipping", "delivery", "route", "payment", "return", "credit_note",
        ],
        "rollback": {
            "before_commit": "Any exception rolls back the serializable transaction; no partial business or registry rows persist.",
            "after_commit": "Do not delete/update immutable registry or individual live rows. Restore/recreate the UAT database from its pre-apply snapshot for rollback.",
        },
        "result": json_safe(result or {}),
    }


def run_self_test() -> int:
    assert_uat_target_database_name("budimas_clean_20260902_v2_uat01", label="self-test")
    assert_uat_target_database_name("budimas_clean_demo_uat", label="self-test")
    assert_uat_target_database_name("budimas_clean_uat", label="self-test")
    for rejected in ("budimas_clean_20260902_v2", "budimas_dev", "budimas", "postgres"):
        try:
            assert_uat_target_database_name(rejected, label="self-test")
        except GuardError:
            pass
        else:  # pragma: no cover - defensive assertion
            raise AssertionError(f"UAT guard accepted {rejected}")
    assert approval_timestamp("2026-09-02T10:30:00+07:00") == "2026-09-02T03:30:00Z"
    binding = ReportBinding(
        report_sha256="a" * 64,
        plan_sha256="b" * 64,
        clean_policy_sha256="c" * 64,
        pd_policy_sha256="d" * 64,
        target_database="budimas_clean_20260902_v2_uat01",
        candidate_documents=2,
        candidate_lines=3,
        hold_sha256="e" * 64,
        hold_count=1,
    )
    template = pending_approval_template(
        binding,
        baseline_schema_sha256="f" * 64,
        baseline_reference_sha256="0" * 64,
    )
    assert template["format"] == APPROVAL_FORMAT
    assert template["approval"]["approved_plan_sha256"] == binding.plan_sha256
    assert template["approval"]["approved_apply_contract_sha256"] == current_apply_contract_sha256()
    assert template["approval"]["hold_disposition"] == "record_open_do_not_import"
    print(json.dumps({"status": "ok", "self_test": SCRIPT_VERSION}, ensure_ascii=False))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    validate_args(args)
    if args.self_test:
        return run_self_test()
    assert args.report_json is not None and args.target_database is not None
    if not args.apply:
        assert_output_path_fresh(args.output)
    supplied_report = read_json(args.report_json, "report JSON PD")
    binding = validate_report_binding(supplied_report, args.target_database)
    assert_stage_args_match_report(args, supplied_report)
    conn, current_user = connect_target(args, readonly=not args.apply)
    try:
        with conn.cursor() as cur:
            if args.apply:
                # Must be the transaction's first data-access operation;
                # `lock_apply_scope_from_policy` locks before taking any
                # serializable snapshot used by the re-plan.
                lock_apply_scope_from_policy(cur, args)
                rebuilt = rebuild_plan(cur, args, require_empty_target=True)
                assert_rebuilt_matches_report(binding, supplied_report, rebuilt)
                approval = validate_approval(args.approval_json, binding, rebuilt)
                applied = apply_rebuilt_plan(
                    cur,
                    args=args,
                    rebuilt=rebuilt,
                    binding=binding,
                    approval=approval,
                    current_user=current_user,
                )
                result = result_payload(mode="APPLIED_UAT", binding=binding, rebuilt=rebuilt, result=applied)
                conn.commit()
            else:
                # The default path is a real PostgreSQL read-only transaction.
                # It checks the same report binding/baseline/empty target gate
                # but cannot create even an import_run row.
                cur.execute("SHOW transaction_read_only")
                if str(cur.fetchone()[0]).lower() not in {"on", "true"}:
                    raise GuardError("Dry-run harus benar-benar transaction_read_only.")
                rebuilt = rebuild_plan(cur, args, require_empty_target=True)
                assert_rebuilt_matches_report(binding, supplied_report, rebuilt)
                result = result_payload(mode="READ_ONLY_DRY_RUN", binding=binding, rebuilt=rebuilt)
                if args.write_approval_template is not None:
                    template = pending_approval_template(
                        binding,
                        baseline_schema_sha256=rebuilt.baseline_schema_sha256,
                        baseline_reference_sha256=rebuilt.baseline_reference_sha256,
                    )
                    write_json_once(args.write_approval_template, template)
                conn.rollback()
        if not args.apply and args.output is not None:
            write_json_once(args.output, result)
        print(
            json.dumps(
                {
                    "status": "ok",
                    "mode": result["mode"],
                    "output": str(args.output) if args.output is not None else None,
                    "report_sha256": binding.report_sha256,
                    "plan_sha256": binding.plan_sha256,
                    "candidate_documents": binding.candidate_documents,
                    "candidate_lines": binding.candidate_lines,
                    "holds": binding.hold_count,
                    "result": result.get("result", {}),
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
