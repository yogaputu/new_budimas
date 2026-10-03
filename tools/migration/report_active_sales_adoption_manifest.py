#!/usr/bin/env python3
"""Build a read-only exact-or-skip adoption manifest for August 2026 sales.

This reporter is deliberately separate from the active-sales importer.  It
does not insert, update, delete, lock, or otherwise mutate SQL Server or the
PostgreSQL ERP.  Its only purpose is to prove whether an existing legacy
``HJualSM`` / ``DJualSM`` document can be attached to an already-existing
``sales_order`` / ``faktur`` pair by a later, explicitly approved process.

An item is ``READY_FOR_ADOPTION_REVIEW`` only when all of the following are
true at one repeatable-read snapshot:

* source identity is source-qualified and canonical (not Android);
* exactly one linked SO--faktur pair is found, with no target reuse;
* master/plafon/scope, document fields, money fields, payment state, and
  delivered lifecycle match the verified current ERP profile;
* every source detail maps bijectively to exactly one target detail with exact
  product/UOM/quantity/price/discount/fulfilment values; and
* existing provenance, if any, still points to the same immutable source and
  target hashes.

Everything else is ``SKIP_AND_AUDIT``.  The output is an immutable JSON input
for the human review workbook; it is not an authorization to write mappings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

from apply_active_sales_source_aware import (  # type: ignore[import-not-found]
    ANDROID_DETAIL_TABLE,
    ANDROID_HEADER_TABLE,
    BATCH_RE,
    MAX_INT32,
    REGISTRY_SCHEMA,
    SOURCE_HEADER_TABLE,
    SOURCE_SYSTEMS,
    StageMetadata,
    ValidationError,
    clean,
    fetch_android_counts,
    fetch_details,
    fetch_headers,
    fetch_stage_columns,
    final_stage_gate,
    json_safe,
    load_committed_mappings,
    load_existing_documents,
    load_plafon_targets,
    load_source_context,
    money_equal,
    norm,
    parse_date,
    parse_decimal,
    resolve_line,
    source_key,
    stage_metadata,
    validate_stage_provenance,
)


REPORT_VERSION = "active_sales_exact_manifest_v1"
POLICY_ID = "bdm_tmp_active_transaction_exact_or_skip_20260831"
TARGET_DELIVERED_STATUS = 6
TARGET_OPEN_INVOICE_STATUS = 2
TARGET_PAID_INVOICE_STATUS = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bdm-schema", required=True)
    parser.add_argument("--tmp-schema", required=True)
    parser.add_argument("--batch-id", default="active_sales_adoption_manifest_20260901")
    parser.add_argument("--money-tolerance", default="0.05")
    parser.add_argument("--statement-timeout-seconds", type=int, default=180)
    parser.add_argument(
        "--connect-timeout-seconds",
        type=int,
        default=int(os.getenv("MIGRATION_PG_CONNECT_TIMEOUT", "10")),
    )
    parser.add_argument("--pg-database", default=os.getenv("MIGRATION_PG_DATABASE", "budimas_dev"))
    parser.add_argument("--pg-user", default=os.getenv("MIGRATION_PG_USER", "postgres"))
    parser.add_argument("--pg-host", default=os.getenv("MIGRATION_PG_HOST", "127.0.0.1"))
    parser.add_argument("--pg-port", type=int, default=int(os.getenv("MIGRATION_PG_PORT", "5432")))
    parser.add_argument("--output", type=Path, required=True, help="Lokasi JSON manifest lokal.")
    return parser.parse_args()


def ensure_args(args: argparse.Namespace) -> Decimal:
    if args.bdm_schema == args.tmp_schema:
        raise ValidationError("Schema staging BDM dan TMP harus berbeda.")
    if not BATCH_RE.fullmatch(str(args.batch_id)):
        raise ValidationError("--batch-id tidak aman.")
    if not 1 <= args.statement_timeout_seconds <= 3600:
        raise ValidationError("--statement-timeout-seconds harus 1..3600.")
    if not 1 <= args.connect_timeout_seconds <= 60:
        raise ValidationError("--connect-timeout-seconds harus 1..60.")
    tolerance, reason = parse_decimal(args.money_tolerance, "money_tolerance")
    if reason or tolerance is None:
        raise ValidationError("--money-tolerance harus desimal tidak negatif.")
    return tolerance


def rows_as_dicts(cur) -> list[dict[str, Any]]:
    names = [str(item[0]) for item in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def decimal_value(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        parsed = Decimal(str(value))
    except Exception:
        return None
    return parsed if parsed.is_finite() else None


def int_value(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except Exception:
        return None
    if not parsed.is_finite() or parsed != parsed.to_integral_value():
        return None
    return int(parsed)


def iso_value(value: Any) -> str | None:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return clean(value)


def canonical_decimal(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def value_match(left: Any, right: Any, tolerance: Decimal) -> bool:
    left_decimal = decimal_value(left)
    right_decimal = decimal_value(right)
    return left_decimal is not None and right_decimal is not None and money_equal(left_decimal, right_decimal, tolerance)


def target_key(source_system: str, nota_norm: str) -> tuple[str, str, str]:
    return source_key(source_system, SOURCE_HEADER_TABLE, nota_norm)


def source_identity(source_system: str, nota_norm: str) -> str:
    return f"{source_system}|{SOURCE_HEADER_TABLE}|{nota_norm}"


def source_row_id(source_system: str, nota_norm: str | None, staging_id: int, source_hash: str) -> str:
    payload = "\x1f".join((source_system, SOURCE_HEADER_TABLE, nota_norm or "(blank)", str(staging_id), source_hash))
    return hashlib.sha256(payload.encode("utf-8", errors="surrogatepass")).hexdigest()[:24]


def add_reason(doc: dict[str, Any], code: str, details: dict[str, Any] | None = None) -> None:
    known = {item["code"] for item in doc["reasons"]}
    if code in known:
        return
    doc["reasons"].append({"code": code, "details": json_safe(details or {})})


def add_line_exception(
    doc: dict[str, Any],
    *,
    source_urut: str | None,
    source_sku: str | None,
    status: str,
    reasons: Iterable[str],
    target_detail_ids: Iterable[int] = (),
    fields: dict[str, Any] | None = None,
) -> None:
    doc["line_exceptions"].append(
        {
            "source_system": doc["source_system"],
            "source_identity": doc["source_identity"],
            "source_nota": doc["source_nota"],
            "source_nota_norm": doc["source_nota_norm"],
            "source_urut": source_urut,
            "source_sku": source_sku,
            "status": status,
            "reasons": sorted(set(reasons)),
            "target_detail_ids": sorted(set(int(item) for item in target_detail_ids)),
            "fields": json_safe(fields or {}),
        }
    )


def source_status_is_delivered(value: Any) -> bool:
    return (clean(value) or "").upper() == "RL"


def expected_invoice_status(total: Decimal, paid: Decimal, tolerance: Decimal) -> int:
    return TARGET_PAID_INVOICE_STATUS if money_equal(total, paid, tolerance) else TARGET_OPEN_INVOICE_STATUS


def parse_source_documents(
    metadata: dict[str, StageMetadata],
    headers_by_source: dict[str, list[Any]],
    details_by_source: dict[str, list[Any]],
    cur,
    tolerance: Decimal,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate canonical source documents without considering target rows."""

    contexts = load_source_context(cur)
    for source, stage in metadata.items():
        if contexts[source] != (stage.target_company_id, stage.target_branch_id):
            raise ValidationError(f"source_context {source} tidak sama dengan scope staging final.")
    customers, principals, sales, products, uoms = load_committed_mappings(cur)
    plafons = load_plafon_targets(cur)

    documents: list[dict[str, Any]] = []
    orphan_lines: list[dict[str, Any]] = []
    android_holds: list[dict[str, Any]] = []

    for source in SOURCE_SYSTEMS:
        stage = metadata[source]
        android_headers, android_details = fetch_android_counts(cur, stage)
        if android_headers or android_details:
            android_holds.append(
                {
                    "source_system": source,
                    "source_table": f"{ANDROID_HEADER_TABLE}+{ANDROID_DETAIL_TABLE}",
                    "decision": "SKIP_AND_AUDIT",
                    "reason": "android_document_family_requires_source_qualified_cross_reference_review",
                    "android_headers": android_headers,
                    "android_details": android_details,
                }
            )

        headers_by_note: dict[str, list[Any]] = defaultdict(list)
        details_by_note: dict[str, list[Any]] = defaultdict(list)
        for header in headers_by_source[source]:
            header_note_norm = norm(header.nota)
            if header_note_norm is None:
                doc = {
                    "row_id": source_row_id(source, None, header.staging_id, header.source_row_hash),
                    "source_system": source,
                    "source_identity": f"{source}|{SOURCE_HEADER_TABLE}|(blank)|{header.staging_id}",
                    "source_nota": header.nota,
                    "source_nota_norm": None,
                    "source_staging_id": header.staging_id,
                    "source_row_hash": header.source_row_hash,
                    "stage_schema": stage.schema,
                    "stage_run_id": stage.run_id,
                    "source_status": clean(header.stnota),
                    "source_header": {},
                    "source_lines": [],
                    "line_exceptions": [],
                    "reasons": [],
                    "target_candidate": None,
                    "target_candidate_summary": {},
                    "line_matches": [],
                }
                add_reason(doc, "blank_source_nota")
                documents.append(doc)
            else:
                headers_by_note[header_note_norm].append(header)
        for detail in details_by_source[source]:
            detail_note_norm = norm(detail.nota)
            if detail_note_norm is None:
                orphan_lines.append(
                    {
                        "source_system": source,
                        "source_nota": detail.nota,
                        "source_urut": detail.urut,
                        "source_sku": detail.kodestok,
                        "status": "SKIP_AND_AUDIT",
                        "reasons": ["blank_source_nota"],
                    }
                )
            else:
                details_by_note[detail_note_norm].append(detail)

        for nota_norm, same_headers in sorted(headers_by_note.items()):
            if len(same_headers) != 1:
                for header in same_headers:
                    doc = {
                        "row_id": source_row_id(source, nota_norm, header.staging_id, header.source_row_hash),
                        "source_system": source,
                        "source_identity": source_identity(source, nota_norm),
                        "source_nota": header.nota,
                        "source_nota_norm": nota_norm,
                        "source_staging_id": header.staging_id,
                        "source_row_hash": header.source_row_hash,
                        "stage_schema": stage.schema,
                        "stage_run_id": stage.run_id,
                        "source_status": clean(header.stnota),
                        "source_header": {},
                        "source_lines": [],
                        "line_exceptions": [],
                        "reasons": [],
                        "target_candidate": None,
                        "target_candidate_summary": {},
                        "line_matches": [],
                    }
                    add_reason(doc, "duplicate_source_header_nota", {"count": len(same_headers)})
                    documents.append(doc)
                continue

            header = same_headers[0]
            detail_rows = details_by_note.pop(nota_norm, [])
            doc: dict[str, Any] = {
                "row_id": source_row_id(source, nota_norm, header.staging_id, header.source_row_hash),
                "source_system": source,
                "source_identity": source_identity(source, nota_norm),
                "source_nota": header.nota,
                "source_nota_norm": nota_norm,
                "source_staging_id": header.staging_id,
                "source_row_hash": header.source_row_hash,
                "stage_schema": stage.schema,
                "stage_run_id": stage.run_id,
                "source_status": clean(header.stnota),
                "source_header": {},
                "source_lines": [],
                "line_exceptions": [],
                "reasons": [],
                "target_candidate": None,
                "target_candidate_summary": {},
                "line_matches": [],
            }
            customer_norm = norm(header.kodecustomer)
            principal_norm = norm(header.kodeprinciple)
            sales_norm = norm(header.kodesales)
            if customer_norm is None or principal_norm is None or sales_norm is None:
                add_reason(doc, "blank_source_master_code")
            id_customer = customers.get((source, customer_norm)) if customer_norm else None
            id_principal = principals.get((source, principal_norm)) if principal_norm else None
            id_sales = sales.get((source, principal_norm, sales_norm)) if principal_norm and sales_norm else None
            missing_mapping = [
                name
                for name, value in (("customer", id_customer), ("principal", id_principal), ("sales", id_sales))
                if value is None
            ]
            if missing_mapping:
                add_reason(doc, "missing_committed_header_mapping", {"missing": missing_mapping})

            plafon_candidates = (
                plafons.get((int(id_customer), int(id_principal), int(id_sales)), [])
                if id_customer is not None and id_principal is not None and id_sales is not None
                else []
            )
            id_plafon = plafon_candidates[0] if len(plafon_candidates) == 1 else None
            if not missing_mapping and len(plafon_candidates) != 1:
                add_reason(
                    doc,
                    "missing_or_duplicate_target_plafon",
                    {"matches": plafon_candidates, "id_customer": id_customer, "id_principal": id_principal, "id_sales": id_sales},
                )

            order_date, order_date_reason = parse_date(header.tanggal_raw, "tanggal")
            if order_date_reason:
                add_reason(doc, order_date_reason)
            due_date, due_date_reason = parse_date(header.jatuhtempo_raw, "jatuhtempo", required=False)
            if due_date_reason:
                add_reason(doc, due_date_reason)
            delivered_date, delivered_date_reason = parse_date(header.tglreal_raw, "tglreal", required=False)
            if delivered_date_reason:
                add_reason(doc, delivered_date_reason)
            if delivered_date is None:
                delivered_date = order_date

            total_penjualan, total_reason = parse_decimal(header.totalpenjualan_raw, "totalpenjualan")
            total_retur, retur_reason = parse_decimal(header.totalretur_raw or "0", "totalretur")
            terbayar, paid_reason = parse_decimal(header.terbayar_raw or "0", "terbayar")
            if total_reason:
                add_reason(doc, total_reason)
            if retur_reason:
                add_reason(doc, retur_reason)
            if paid_reason:
                add_reason(doc, paid_reason)
            if total_retur is not None and total_retur != 0:
                add_reason(doc, "nonzero_return_requires_source_qualified_return_import", {"source_total_retur": total_retur})
            if total_penjualan is not None and terbayar is not None and terbayar > total_penjualan + tolerance:
                add_reason(doc, "source_paid_amount_exceeds_source_total")
            if not source_status_is_delivered(header.stnota):
                add_reason(doc, "source_status_not_supported_for_delivered_adoption", {"source_status": clean(header.stnota)})

            doc["source_header"] = {
                "id_customer": id_customer,
                "id_principal": id_principal,
                "id_sales": id_sales,
                "id_plafon": id_plafon,
                "target_company_id": stage.target_company_id,
                "target_branch_id": stage.target_branch_id,
                "tanggal_order": order_date,
                "tanggal_jatuh_tempo": due_date,
                "tanggal_terkirim": delivered_date,
                "total_penjualan": total_penjualan,
                "total_retur": total_retur,
                "terbayar": terbayar,
                "nama_sales": clean(header.namasales),
                "nama_customer": clean(header.namacustomer),
                "keterangan": clean(header.keterangan),
            }

            details_by_urut: dict[str, list[Any]] = defaultdict(list)
            for detail in detail_rows:
                urut_norm = norm(detail.urut)
                if urut_norm is None:
                    add_reason(doc, "blank_source_detail_urut")
                    add_line_exception(
                        doc,
                        source_urut=detail.urut,
                        source_sku=detail.kodestok,
                        status="SKIP_SOURCE_VALIDATION",
                        reasons=["blank_source_urut"],
                    )
                else:
                    details_by_urut[urut_norm].append(detail)
            duplicate_uruts = {key for key, value in details_by_urut.items() if len(value) > 1}
            for urut_norm in sorted(duplicate_uruts):
                add_reason(doc, "duplicate_source_line_urut", {"source_urut_norm": urut_norm, "count": len(details_by_urut[urut_norm])})
                for detail in details_by_urut[urut_norm]:
                    add_line_exception(
                        doc,
                        source_urut=detail.urut,
                        source_sku=detail.kodestok,
                        status="SKIP_SOURCE_VALIDATION",
                        reasons=["duplicate_source_line_urut"],
                    )

            can_resolve = order_date is not None and principal_norm is not None
            line_plans: list[Any] = []
            for detail in detail_rows:
                if norm(detail.urut) is None or norm(detail.urut) in duplicate_uruts:
                    continue
                if not can_resolve:
                    add_line_exception(
                        doc,
                        source_urut=detail.urut,
                        source_sku=detail.kodestok,
                        status="SKIP_SOURCE_VALIDATION",
                        reasons=["header_validation_required_before_detail_resolution"],
                    )
                    continue
                line_plan, line_hold = resolve_line(detail, header, principal_norm, order_date, products, uoms)
                if line_hold is not None:
                    add_reason(doc, "source_detail_validation_failed")
                    add_line_exception(
                        doc,
                        source_urut=detail.urut,
                        source_sku=detail.kodestok,
                        status="SKIP_SOURCE_VALIDATION",
                        reasons=[line_hold.reason],
                        fields=line_hold.details,
                    )
                    continue
                assert line_plan is not None
                if line_plan.source_discount_percent != 0:
                    add_reason(doc, "discount_percent_semantics_unverified")
                    add_line_exception(
                        doc,
                        source_urut=line_plan.source_urut,
                        source_sku=detail.kodestok,
                        status="SKIP_SOURCE_VALIDATION",
                        reasons=["discount_percent_semantics_unverified"],
                        fields={"source_discount_percent": line_plan.source_discount_percent},
                    )
                line_plans.append(line_plan)

            if total_penjualan is not None and not line_plans and total_penjualan != 0:
                add_reason(doc, "header_without_eligible_detail")
            if line_plans:
                line_total = sum((item.subtotal_order for item in line_plans), Decimal("0"))
                if total_penjualan is not None and not money_equal(total_penjualan, line_total, tolerance):
                    add_reason(
                        doc,
                        "source_header_detail_total_mismatch",
                        {"header_total": total_penjualan, "detail_total": line_total, "tolerance": tolerance},
                    )
            else:
                line_total = Decimal("0")

            signature_counter: Counter[tuple[Any, ...]] = Counter()
            for plan in line_plans:
                signature = source_line_signature(plan)
                signature_counter[signature] += 1
            duplicate_signatures = {signature for signature, count in signature_counter.items() if count > 1}
            if duplicate_signatures:
                add_reason(doc, "ambiguous_duplicate_source_line_signature", {"count": sum(signature_counter[item] for item in duplicate_signatures)})
                for plan in line_plans:
                    if source_line_signature(plan) in duplicate_signatures:
                        add_line_exception(
                            doc,
                            source_urut=plan.source_urut,
                            source_sku=plan.row.kodestok,
                            status="SKIP_SOURCE_VALIDATION",
                            reasons=["ambiguous_duplicate_source_line_signature"],
                        )

            doc["source_lines"] = line_plans
            doc["source_header"].update(
                {
                    "source_detail_count": len(detail_rows),
                    "eligible_detail_count": len(line_plans),
                    "detail_total": line_total,
                    "subtotal_dpp": sum((item.subtotal_dpp for item in line_plans), Decimal("0")),
                    "subtotal_diskon": sum((item.discount_amount for item in line_plans), Decimal("0")),
                    "pajak": (total_penjualan - sum((item.subtotal_dpp for item in line_plans), Decimal("0")))
                    if total_penjualan is not None
                    else None,
                }
            )
            documents.append(doc)

        for orphan_nota, orphan_detail_rows in sorted(details_by_note.items()):
            for detail in orphan_detail_rows:
                orphan_lines.append(
                    {
                        "source_system": source,
                        "source_nota": detail.nota,
                        "source_nota_norm": orphan_nota,
                        "source_urut": detail.urut,
                        "source_sku": detail.kodestok,
                        "status": "SKIP_AND_AUDIT",
                        "reasons": ["detail_without_source_header"],
                    }
                )

    return documents, orphan_lines, android_holds


def source_line_signature(plan: Any) -> tuple[Any, ...]:
    return (
        plan.id_produk,
        plan.pieces_order,
        plan.box_order,
        plan.karton_order,
        canonical_decimal(plan.harga_order),
        canonical_decimal(plan.subtotal_order),
        canonical_decimal(plan.discount_amount),
        plan.is_bonus,
        canonical_decimal(plan.source_discount_percent),
        plan.qty_base,
        canonical_decimal(plan.subtotal_dpp),
    )


def target_orders(cur, notes: list[str]) -> dict[int, dict[str, Any]]:
    if not notes:
        return {}
    cur.execute(
        """
        SELECT so.id AS id_sales_order, so.id_plafon, so.tanggal_order, so.tanggal_faktur,
               so.tanggal_terkirim, so.tanggal_jatuh_tempo, so.nama_sales, so.pic_customer,
               so.status_order, so.total_order, so.no_order, so.no_faktur, so.no_tagihan,
               so.keterangan, so.id_cabang, p.id_customer AS plafon_id_customer,
               p.id_principal AS plafon_id_principal, p.id_sales AS plafon_id_sales,
               c.id_perusahaan AS cabang_id_perusahaan
        FROM public.sales_order so
        LEFT JOIN public.plafon p ON p.id = so.id_plafon
        LEFT JOIN public.cabang c ON c.id = so.id_cabang
        WHERE lower(btrim(so.no_order)) = ANY(%s)
           OR lower(btrim(so.no_faktur)) = ANY(%s)
        """,
        (notes, notes),
    )
    return {int(item["id_sales_order"]): item for item in rows_as_dicts(cur)}


def target_orders_by_ids(cur, order_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not order_ids:
        return {}
    cur.execute(
        """
        SELECT so.id AS id_sales_order, so.id_plafon, so.tanggal_order, so.tanggal_faktur,
               so.tanggal_terkirim, so.tanggal_jatuh_tempo, so.nama_sales, so.pic_customer,
               so.status_order, so.total_order, so.no_order, so.no_faktur, so.no_tagihan,
               so.keterangan, so.id_cabang, p.id_customer AS plafon_id_customer,
               p.id_principal AS plafon_id_principal, p.id_sales AS plafon_id_sales,
               c.id_perusahaan AS cabang_id_perusahaan
        FROM public.sales_order so
        LEFT JOIN public.plafon p ON p.id = so.id_plafon
        LEFT JOIN public.cabang c ON c.id = so.id_cabang
        WHERE so.id = ANY(%s)
        """,
        (order_ids,),
    )
    return {int(item["id_sales_order"]): item for item in rows_as_dicts(cur)}


def target_invoices_by_notes(cur, notes: list[str]) -> dict[int, dict[str, Any]]:
    if not notes:
        return {}
    cur.execute(
        """
        SELECT id AS id_faktur, id_sales_order, no_faktur, status_faktur, jenis_faktur,
               subtotal_penjualan, subtotal_diskon, total_penjualan, total_dana_diterima,
               pajak, dpp, draft_total_penjualan, nominal_retur, credit_note_nominal
        FROM public.faktur
        WHERE lower(btrim(no_faktur)) = ANY(%s)
        """,
        (notes,),
    )
    return {int(item["id_faktur"]): item for item in rows_as_dicts(cur)}


def target_invoices_by_order_ids(cur, order_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not order_ids:
        return {}
    cur.execute(
        """
        SELECT id AS id_faktur, id_sales_order, no_faktur, status_faktur, jenis_faktur,
               subtotal_penjualan, subtotal_diskon, total_penjualan, total_dana_diterima,
               pajak, dpp, draft_total_penjualan, nominal_retur, credit_note_nominal
        FROM public.faktur
        WHERE id_sales_order = ANY(%s)
        """,
        (order_ids,),
    )
    return {int(item["id_faktur"]): item for item in rows_as_dicts(cur)}


def fetch_target_context(cur, notes: list[str]) -> dict[str, Any]:
    direct_orders = target_orders(cur, notes)
    direct_invoices = target_invoices_by_notes(cur, notes)
    linked_order_ids = {int(item["id_sales_order"]) for item in direct_invoices.values() if item["id_sales_order"] is not None}
    all_orders = dict(direct_orders)
    all_orders.update(target_orders_by_ids(cur, sorted(linked_order_ids - set(all_orders))))
    all_invoices = dict(direct_invoices)
    all_invoices.update(target_invoices_by_order_ids(cur, sorted(all_orders)))
    all_order_ids = sorted(all_orders)
    if all_order_ids:
        cur.execute(
            """
            SELECT id AS id_sales_order_detail, id_sales_order, id_produk, hargaorder,
                   subtotaldelivered, is_bonus, pieces_order, box_order, karton_order,
                   pieces_booked, box_booked, karton_booked, pieces_picked, box_picked,
                   karton_picked, pieces_shipped, box_shipped, karton_shipped,
                   pieces_delivered, box_delivered, karton_delivered, subtotalorder,
                   pieces_retur, box_retur, karton_retur, total_nilai_discount,
                   total_persen_diskon, keterangan_retur
            FROM public.sales_order_detail
            WHERE id_sales_order = ANY(%s)
            ORDER BY id_sales_order, id
            """,
            (all_order_ids,),
        )
        target_details = rows_as_dicts(cur)
        cur.execute(
            """
            SELECT id AS id_faktur_detail, id_faktur, id_sales_order, id_principal,
                   subtotal_diskon, subtotal, pajak, draft_total, total
            FROM public.faktur_detail
            WHERE id_sales_order = ANY(%s)
            ORDER BY id_sales_order, id
            """,
            (all_order_ids,),
        )
        target_faktur_details = rows_as_dicts(cur)
    else:
        target_details = []
        target_faktur_details = []
    details_by_order: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in target_details:
        details_by_order[int(item["id_sales_order"])].append(item)
    invoices_by_order: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in all_invoices.values():
        if item["id_sales_order"] is not None:
            invoices_by_order[int(item["id_sales_order"])].append(item)
    faktur_details_by_faktur: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in target_faktur_details:
        faktur_details_by_faktur[int(item["id_faktur"])].append(item)
    return {
        "orders": all_orders,
        "direct_orders": direct_orders,
        "invoices": all_invoices,
        "direct_invoices": direct_invoices,
        "invoices_by_order": invoices_by_order,
        "details_by_order": details_by_order,
        "faktur_details_by_faktur": faktur_details_by_faktur,
    }


def target_candidate_for_note(note: str, context: dict[str, Any]) -> dict[str, Any]:
    orders = context["orders"]
    invoices = context["invoices"]
    direct_orders = {
        item_id
        for item_id, item in context["direct_orders"].items()
        if note in {norm(item.get("no_order")), norm(item.get("no_faktur"))}
    }
    direct_invoices = {
        item_id
        for item_id, item in context["direct_invoices"].items()
        if note == norm(item.get("no_faktur"))
    }
    pair_ids: set[tuple[int, int]] = set()
    order_ids: set[int] = set(direct_orders)
    invoice_ids: set[int] = set(direct_invoices)
    unlinked_invoice_ids: set[int] = set()
    for order_id in direct_orders:
        for invoice in context["invoices_by_order"].get(order_id, []):
            pair_ids.add((order_id, int(invoice["id_faktur"])))
            invoice_ids.add(int(invoice["id_faktur"]))
    for invoice_id in direct_invoices:
        invoice = invoices[invoice_id]
        linked_order = int_value(invoice.get("id_sales_order"))
        if linked_order is None or linked_order not in orders:
            unlinked_invoice_ids.add(invoice_id)
            continue
        pair_ids.add((linked_order, invoice_id))
        order_ids.add(linked_order)
    return {
        "order_ids": sorted(order_ids),
        "invoice_ids": sorted(invoice_ids),
        "unlinked_invoice_ids": sorted(unlinked_invoice_ids),
        "pairs": sorted(pair_ids),
    }


def compare_money_field(errors: list[str], label: str, source: Any, target: Any, tolerance: Decimal) -> None:
    if not value_match(source, target, tolerance):
        errors.append(label)


def compare_date_field(errors: list[str], label: str, source: Any, target: Any) -> None:
    source_value = iso_value(source)
    target_value = iso_value(target)
    if source_value != target_value:
        errors.append(label)


def check_target_header(doc: dict[str, Any], context: dict[str, Any], tolerance: Decimal) -> None:
    note = doc["source_nota_norm"]
    if note is None:
        return
    candidate = target_candidate_for_note(note, context)
    doc["target_candidate_summary"] = json_safe(candidate)
    pairs = candidate["pairs"]
    if len(pairs) == 0:
        if candidate["order_ids"] or candidate["invoice_ids"] or candidate["unlinked_invoice_ids"]:
            add_reason(doc, "target_candidate_is_not_a_complete_linked_so_faktur_pair", candidate)
        else:
            add_reason(doc, "no_target_candidate_for_source_note")
        return
    if len(pairs) != 1:
        add_reason(doc, "ambiguous_target_so_faktur_pair", candidate)
        return
    sales_order_id, faktur_id = pairs[0]
    order = context["orders"].get(sales_order_id)
    invoice = context["invoices"].get(faktur_id)
    if order is None or invoice is None:
        add_reason(doc, "target_pair_missing_after_lookup")
        return
    doc["target_candidate"] = {"id_sales_order": sales_order_id, "id_faktur": faktur_id}
    source_header = doc["source_header"]
    source_note = note
    invoices_for_order = context["invoices_by_order"].get(sales_order_id, [])
    if len(invoices_for_order) != 1 or int(invoices_for_order[0]["id_faktur"]) != faktur_id:
        add_reason(
            doc,
            "target_sales_order_does_not_have_exactly_one_linked_faktur",
            {"id_sales_order": sales_order_id, "linked_faktur_ids": [item["id_faktur"] for item in invoices_for_order]},
        )
    target_note_fields = {
        "target_no_order_not_equal_source_nota": norm(order.get("no_order")),
        "target_so_no_faktur_not_equal_source_nota": norm(order.get("no_faktur")),
        "target_faktur_no_faktur_not_equal_source_nota": norm(invoice.get("no_faktur")),
    }
    for code, value in target_note_fields.items():
        if value != source_note:
            add_reason(doc, code, {"actual": value, "expected": source_note})
    if norm(order.get("no_tagihan")) not in (None, source_note):
        add_reason(doc, "target_no_tagihan_not_equal_source_nota", {"actual": norm(order.get("no_tagihan")), "expected": source_note})

    expected_scope = (source_header.get("target_company_id"), source_header.get("target_branch_id"))
    actual_scope = (int_value(order.get("cabang_id_perusahaan")), int_value(order.get("id_cabang")))
    if expected_scope != actual_scope:
        add_reason(doc, "target_company_or_branch_not_equal_source_context", {"expected": expected_scope, "actual": actual_scope})
    expected_plafon = source_header.get("id_plafon")
    actual_plafon = int_value(order.get("id_plafon"))
    if expected_plafon is None or expected_plafon != actual_plafon:
        add_reason(doc, "target_plafon_not_equal_committed_source_mapping", {"expected": expected_plafon, "actual": actual_plafon})
    expected_master = (source_header.get("id_customer"), source_header.get("id_principal"), source_header.get("id_sales"))
    actual_master = (
        int_value(order.get("plafon_id_customer")),
        int_value(order.get("plafon_id_principal")),
        int_value(order.get("plafon_id_sales")),
    )
    if expected_master != actual_master:
        add_reason(doc, "target_plafon_master_not_equal_committed_source_mapping", {"expected": expected_master, "actual": actual_master})

    compare_errors: list[str] = []
    compare_date_field(compare_errors, "target_tanggal_order_not_equal_source", source_header.get("tanggal_order"), order.get("tanggal_order"))
    compare_date_field(compare_errors, "target_tanggal_faktur_not_equal_source_order_date", source_header.get("tanggal_order"), order.get("tanggal_faktur"))
    compare_date_field(compare_errors, "target_tanggal_terkirim_not_equal_source_real_date", source_header.get("tanggal_terkirim"), order.get("tanggal_terkirim"))
    compare_date_field(compare_errors, "target_tanggal_jatuh_tempo_not_equal_source", source_header.get("tanggal_jatuh_tempo"), order.get("tanggal_jatuh_tempo"))
    for code in compare_errors:
        add_reason(doc, code)

    total = source_header.get("total_penjualan")
    subtotal_dpp = source_header.get("subtotal_dpp")
    subtotal_diskon = source_header.get("subtotal_diskon")
    pajak = source_header.get("pajak")
    terbayar = source_header.get("terbayar")
    total_retur = source_header.get("total_retur")
    monetary_checks = (
        ("target_so_total_order_not_equal_source_total", total, order.get("total_order")),
        ("target_faktur_total_penjualan_not_equal_source_total", total, invoice.get("total_penjualan")),
        ("target_faktur_draft_total_not_equal_source_total", total, invoice.get("draft_total_penjualan")),
        ("target_faktur_dpp_not_equal_source_detail_dpp", subtotal_dpp, invoice.get("dpp")),
        ("target_faktur_subtotal_not_equal_source_detail_dpp", subtotal_dpp, invoice.get("subtotal_penjualan")),
        ("target_faktur_discount_not_equal_source_detail_discount", subtotal_diskon, invoice.get("subtotal_diskon")),
        ("target_faktur_pajak_not_equal_source_detail_tax", pajak, invoice.get("pajak")),
        ("target_faktur_paid_not_equal_source_terbayar", terbayar, invoice.get("total_dana_diterima")),
        ("target_faktur_return_not_equal_source_return", total_retur, invoice.get("nominal_retur")),
    )
    for code, source_value, target_value in monetary_checks:
        if source_value is None or not value_match(source_value, target_value, tolerance):
            add_reason(doc, code, {"source": source_value, "target": target_value})
    if decimal_value(invoice.get("credit_note_nominal")) not in (None, Decimal("0")):
        add_reason(doc, "target_credit_note_nominal_is_nonzero")
    if (clean(invoice.get("jenis_faktur")) or "").lower() != "penjualan":
        add_reason(doc, "target_invoice_type_is_not_penjualan", {"actual": clean(invoice.get("jenis_faktur"))})
    if int_value(order.get("status_order")) != TARGET_DELIVERED_STATUS:
        add_reason(doc, "target_sales_order_not_in_delivered_status", {"actual": int_value(order.get("status_order")), "expected": TARGET_DELIVERED_STATUS})
    if total is not None and terbayar is not None:
        expected_status = expected_invoice_status(total, terbayar, tolerance)
        if int_value(invoice.get("status_faktur")) != expected_status:
            add_reason(doc, "target_faktur_status_not_equal_payment_state", {"actual": int_value(invoice.get("status_faktur")), "expected": expected_status})

    faktur_details = context["faktur_details_by_faktur"].get(faktur_id, [])
    if len(faktur_details) != 1:
        add_reason(doc, "target_faktur_does_not_have_exactly_one_faktur_detail", {"count": len(faktur_details)})
    else:
        faktur_detail = faktur_details[0]
        if int_value(faktur_detail.get("id_sales_order")) != sales_order_id:
            add_reason(doc, "target_faktur_detail_order_not_equal_target_order")
        if int_value(faktur_detail.get("id_principal")) != source_header.get("id_principal"):
            add_reason(doc, "target_faktur_detail_principal_not_equal_source_mapping")
        for code, source_value, target_value in (
            ("target_faktur_detail_discount_not_equal_source", subtotal_diskon, faktur_detail.get("subtotal_diskon")),
            ("target_faktur_detail_subtotal_not_equal_source", subtotal_dpp, faktur_detail.get("subtotal")),
            ("target_faktur_detail_tax_not_equal_source", pajak, faktur_detail.get("pajak")),
            ("target_faktur_detail_draft_total_not_equal_source", total, faktur_detail.get("draft_total")),
            ("target_faktur_detail_total_not_equal_source", total, faktur_detail.get("total")),
        ):
            if source_value is None or not value_match(source_value, target_value, tolerance):
                add_reason(doc, code, {"source": source_value, "target": target_value})

    if clean(source_header.get("nama_sales")) and norm(source_header.get("nama_sales")) != norm(order.get("nama_sales")):
        doc.setdefault("audit_notes", []).append("nama_sales_target_berbeda")
    if clean(source_header.get("nama_customer")) and norm(source_header.get("nama_customer")) != norm(order.get("pic_customer")):
        doc.setdefault("audit_notes", []).append("nama_customer_target_berbeda")


def target_line_compare_errors(plan: Any, target: dict[str, Any], tolerance: Decimal) -> list[str]:
    errors: list[str] = []
    expected_ints = {
        "id_produk": plan.id_produk,
        "pieces_order": plan.pieces_order,
        "box_order": plan.box_order,
        "karton_order": plan.karton_order,
        "pieces_booked": plan.pieces_order,
        "box_booked": plan.box_order,
        "karton_booked": plan.karton_order,
        "pieces_picked": plan.pieces_order,
        "box_picked": plan.box_order,
        "karton_picked": plan.karton_order,
        "pieces_shipped": plan.pieces_order,
        "box_shipped": plan.box_order,
        "karton_shipped": plan.karton_order,
        "pieces_delivered": plan.pieces_order,
        "box_delivered": plan.box_order,
        "karton_delivered": plan.karton_order,
        "is_bonus": plan.is_bonus,
        "pieces_retur": 0,
        "box_retur": 0,
        "karton_retur": 0,
        "total_persen_diskon": 0,
    }
    for field, expected in expected_ints.items():
        actual = int_value(target.get(field))
        if actual != expected:
            errors.append(f"{field}_mismatch")
    expected_delivered = int(plan.subtotal_order.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if int_value(target.get("subtotaldelivered")) != expected_delivered:
        errors.append("subtotaldelivered_mismatch")
    for field, expected in (
        ("hargaorder", plan.harga_order),
        ("subtotalorder", plan.subtotal_order),
        ("total_nilai_discount", plan.discount_amount),
    ):
        if not value_match(expected, target.get(field), tolerance):
            errors.append(f"{field}_mismatch")
    if clean(target.get("keterangan_retur")) is not None:
        errors.append("keterangan_retur_is_not_blank")
    return errors


def check_target_details(doc: dict[str, Any], context: dict[str, Any], tolerance: Decimal) -> None:
    candidate = doc.get("target_candidate")
    if candidate is None:
        return
    target_lines = context["details_by_order"].get(candidate["id_sales_order"], [])
    source_lines = doc["source_lines"]
    if len(source_lines) != doc["source_header"].get("source_detail_count"):
        add_reason(doc, "cannot_compare_target_details_until_all_source_details_are_valid")
        return
    if len(source_lines) != len(target_lines):
        add_reason(
            doc,
            "target_detail_count_not_equal_source_detail_count",
            {"source_count": len(source_lines), "target_count": len(target_lines)},
        )

    target_compatibility: dict[str, list[dict[str, Any]]] = {}
    target_usage: Counter[int] = Counter()
    all_target_ids = {int(item["id_sales_order_detail"]) for item in target_lines}
    for plan in source_lines:
        compatible = [item for item in target_lines if not target_line_compare_errors(plan, item, tolerance)]
        target_compatibility[plan.source_urut_norm] = compatible
        if len(compatible) == 1:
            target_usage[int(compatible[0]["id_sales_order_detail"])] += 1
        else:
            same_product = [item for item in target_lines if int_value(item.get("id_produk")) == plan.id_produk]
            best = same_product[:3]
            compare_reasons: list[str] = ["no_exact_target_line"] if not compatible else ["ambiguous_exact_target_line"]
            for item in best:
                compare_reasons.extend(target_line_compare_errors(plan, item, tolerance))
            add_reason(doc, "target_detail_not_bijective")
            add_line_exception(
                doc,
                source_urut=plan.source_urut,
                source_sku=plan.row.kodestok,
                status="SKIP_TARGET_DETAIL_MISMATCH",
                reasons=compare_reasons,
                target_detail_ids=[int(item["id_sales_order_detail"]) for item in best],
            )
    reused_targets = {target_id for target_id, count in target_usage.items() if count > 1}
    for plan in source_lines:
        compatible = target_compatibility[plan.source_urut_norm]
        if len(compatible) == 1:
            target_id = int(compatible[0]["id_sales_order_detail"])
            if target_id in reused_targets:
                add_reason(doc, "target_detail_reused_by_multiple_source_lines")
                add_line_exception(
                    doc,
                    source_urut=plan.source_urut,
                    source_sku=plan.row.kodestok,
                    status="SKIP_TARGET_DETAIL_MISMATCH",
                    reasons=["target_detail_reused_by_multiple_source_lines"],
                    target_detail_ids=[target_id],
                )
            else:
                doc["line_matches"].append(
                    {
                        "source_urut": plan.source_urut,
                        "source_urut_norm": plan.source_urut_norm,
                        "source_sku": plan.row.kodestok,
                        "id_sales_order_detail": target_id,
                    }
                )
    matched_target_ids = {item["id_sales_order_detail"] for item in doc["line_matches"]}
    unmatched = all_target_ids - matched_target_ids
    if unmatched:
        add_reason(doc, "target_detail_unmatched_or_extra", {"target_detail_ids": sorted(unmatched)})
        for target_id in sorted(unmatched):
            add_line_exception(
                doc,
                source_urut=None,
                source_sku=None,
                status="SKIP_TARGET_DETAIL_MISMATCH",
                reasons=["target_detail_unmatched_or_extra"],
                target_detail_ids=[target_id],
            )


def target_fingerprint(doc: dict[str, Any], context: dict[str, Any]) -> str | None:
    candidate = doc.get("target_candidate")
    if candidate is None:
        return None
    order_id = candidate["id_sales_order"]
    faktur_id = candidate["id_faktur"]
    payload = {
        "sales_order": context["orders"].get(order_id),
        "faktur": context["invoices"].get(faktur_id),
        "sales_order_detail": context["details_by_order"].get(order_id, []),
        "faktur_detail": context["faktur_details_by_faktur"].get(faktur_id, []),
    }
    encoded = json.dumps(json_safe(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def check_existing_registry(documents: list[dict[str, Any]], cur) -> list[dict[str, Any]]:
    existing_documents, existing_lines = load_existing_documents(cur)
    source_by_target_order: dict[int, list[tuple[str, str, str]]] = defaultdict(list)
    source_by_target_faktur: dict[int, list[tuple[str, str, str]]] = defaultdict(list)
    source_by_target_detail: dict[int, list[tuple[str, str, str, str]]] = defaultdict(list)
    for key, item in existing_documents.items():
        source_by_target_order[item.id_sales_order].append(key)
        if item.id_faktur is not None:
            source_by_target_faktur[item.id_faktur].append(key)
    for key, item in existing_lines.items():
        source_by_target_detail[item.id_sales_order_detail].append(key)

    already_mapped_rows: list[dict[str, Any]] = []
    for doc in documents:
        note = doc["source_nota_norm"]
        if note is None:
            continue
        source_doc_key = target_key(doc["source_system"], note)
        existing = existing_documents.get(source_doc_key)
        candidate = doc.get("target_candidate")
        if existing is not None:
            doc["existing_document_map"] = {
                "id_sales_order": existing.id_sales_order,
                "id_faktur": existing.id_faktur,
                "source_row_hash": existing.source_row_hash,
                "stage_schema": existing.stage_schema,
                "source_staging_id": existing.staging_id,
            }
            if existing.source_row_hash != doc["source_row_hash"]:
                add_reason(doc, "existing_document_source_hash_changed")
            if candidate is None or (existing.id_sales_order, existing.id_faktur) != (
                candidate["id_sales_order"],
                candidate["id_faktur"],
            ):
                add_reason(doc, "existing_document_target_pair_not_equal_current_candidate")
        if candidate is not None:
            other_orders = [item for item in source_by_target_order.get(candidate["id_sales_order"], []) if item != source_doc_key]
            other_fakturs = [item for item in source_by_target_faktur.get(candidate["id_faktur"], []) if item != source_doc_key]
            if other_orders or other_fakturs:
                add_reason(doc, "target_pair_already_mapped_to_different_source", {"other_orders": other_orders, "other_fakturs": other_fakturs})
        for line_match in doc.get("line_matches", []):
            line_key = (doc["source_system"], SOURCE_HEADER_TABLE, note, line_match["source_urut_norm"])
            existing_line = existing_lines.get(line_key)
            if existing is not None:
                if existing_line is None:
                    add_reason(doc, "existing_document_missing_line_map")
                elif existing_line.source_row_hash != next(
                    (item.row.source_row_hash for item in doc["source_lines"] if item.source_urut_norm == line_match["source_urut_norm"]),
                    None,
                ):
                    add_reason(doc, "existing_line_source_hash_changed")
                elif existing_line.id_sales_order_detail != line_match["id_sales_order_detail"]:
                    add_reason(doc, "existing_line_target_not_equal_current_candidate")
            other_lines = [item for item in source_by_target_detail.get(line_match["id_sales_order_detail"], []) if item != line_key]
            if other_lines:
                add_reason(doc, "target_detail_already_mapped_to_different_source", {"other_source_lines": other_lines})
        if existing is not None:
            already_mapped_rows.append(
                {
                    "source_system": doc["source_system"],
                    "source_nota": doc["source_nota"],
                    "source_nota_norm": note,
                    "source_staging_id": doc["source_staging_id"],
                    "id_sales_order": existing.id_sales_order,
                    "id_faktur": existing.id_faktur,
                    "source_row_hash_matches": existing.source_row_hash == doc["source_row_hash"],
                }
            )
    return already_mapped_rows


def apply_cross_source_collision_rules(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order_sources: dict[int, list[dict[str, Any]]] = defaultdict(list)
    faktur_sources: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for doc in documents:
        candidate = doc.get("target_candidate")
        if candidate is not None:
            order_sources[candidate["id_sales_order"]].append(doc)
            faktur_sources[candidate["id_faktur"]].append(doc)
    collisions: list[dict[str, Any]] = []
    for label, mapping in (("sales_order", order_sources), ("faktur", faktur_sources)):
        for target_id, docs in sorted(mapping.items()):
            identities = sorted({item["source_identity"] for item in docs})
            if len(identities) <= 1:
                continue
            collisions.append(
                {"target_type": label, "target_id": target_id, "source_identities": identities, "reason": "target_reused_by_multiple_source_identities"}
            )
            for doc in docs:
                add_reason(doc, "target_reused_by_multiple_source_identities", {"target_type": label, "target_id": target_id, "source_identities": identities})
    return collisions


def finalize_decisions(documents: list[dict[str, Any]], context: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ready_lines: list[dict[str, Any]] = []
    for doc in documents:
        candidate = doc.get("target_candidate")
        if not doc["reasons"] and candidate is not None:
            if doc.get("existing_document_map") is not None:
                decision = "ALREADY_ADOPTED_EXACT"
            else:
                decision = "READY_FOR_ADOPTION_REVIEW"
        else:
            decision = "SKIP_AND_AUDIT"
        doc["decision"] = decision
        doc["target_fingerprint"] = target_fingerprint(doc, context)
        doc["reason_codes"] = [item["code"] for item in doc["reasons"]]
        if decision in {"READY_FOR_ADOPTION_REVIEW", "ALREADY_ADOPTED_EXACT"}:
            for line in doc["line_matches"]:
                ready_lines.append(
                    {
                        "source_system": doc["source_system"],
                        "source_identity": doc["source_identity"],
                        "source_nota": doc["source_nota"],
                        "source_urut": line["source_urut"],
                        "source_sku": line["source_sku"],
                        "id_sales_order": candidate["id_sales_order"],
                        "id_faktur": candidate["id_faktur"],
                        "id_sales_order_detail": line["id_sales_order_detail"],
                        "status": "EXACT_LINE_MATCH",
                    }
                )
    return documents, ready_lines


def report_document_row(doc: dict[str, Any]) -> dict[str, Any]:
    source = doc["source_header"]
    candidate = doc.get("target_candidate") or {}
    return {
        "row_id": doc["row_id"],
        "decision": doc.get("decision"),
        "source_system": doc["source_system"],
        "source_identity": doc["source_identity"],
        "source_nota": doc["source_nota"],
        "source_nota_norm": doc["source_nota_norm"],
        "source_staging_id": doc["source_staging_id"],
        "source_row_hash": doc["source_row_hash"],
        "stage_schema": doc["stage_schema"],
        "stage_run_id": doc["stage_run_id"],
        "source_status": doc["source_status"],
        "source_tanggal_order": source.get("tanggal_order"),
        "source_tanggal_terkirim": source.get("tanggal_terkirim"),
        "source_tanggal_jatuh_tempo": source.get("tanggal_jatuh_tempo"),
        "source_total_penjualan": source.get("total_penjualan"),
        "source_total_retur": source.get("total_retur"),
        "source_terbayar": source.get("terbayar"),
        "source_id_customer": source.get("id_customer"),
        "source_id_principal": source.get("id_principal"),
        "source_id_sales": source.get("id_sales"),
        "source_id_plafon": source.get("id_plafon"),
        "source_detail_count": source.get("source_detail_count"),
        "source_eligible_detail_count": source.get("eligible_detail_count"),
        "id_sales_order": candidate.get("id_sales_order"),
        "id_faktur": candidate.get("id_faktur"),
        "candidate_pair_count": len(doc.get("target_candidate_summary", {}).get("pairs", [])),
        "candidate_order_ids": doc.get("target_candidate_summary", {}).get("order_ids", []),
        "candidate_faktur_ids": doc.get("target_candidate_summary", {}).get("invoice_ids", []),
        "reason_codes": doc.get("reason_codes", []),
        "reason_count": len(doc.get("reasons", [])),
        "audit_notes": doc.get("audit_notes", []),
        "target_fingerprint": doc.get("target_fingerprint"),
        "existing_document_map": doc.get("existing_document_map"),
    }


def build_report(
    cur,
    args: argparse.Namespace,
    tolerance: Decimal,
) -> dict[str, Any]:
    columns = fetch_stage_columns(cur, [args.bdm_schema, args.tmp_schema])
    metadata = {
        "bdm_solo_dist": stage_metadata(cur, args.bdm_schema, "bdm_solo_dist", columns),
        "tmp_solo_dist": stage_metadata(cur, args.tmp_schema, "tmp_solo_dist", columns),
    }
    for stage in metadata.values():
        validate_stage_provenance(cur, stage)
    stage_ok, stage_reason = final_stage_gate(metadata)
    if not stage_ok:
        raise ValidationError("Staging final tidak memenuhi gate manifest: " + stage_reason)
    headers_by_source = {source: fetch_headers(cur, stage) for source, stage in metadata.items()}
    details_by_source = {source: fetch_details(cur, stage) for source, stage in metadata.items()}
    documents, orphan_lines, android_holds = parse_source_documents(
        metadata, headers_by_source, details_by_source, cur, tolerance
    )
    notes = sorted({doc["source_nota_norm"] for doc in documents if doc["source_nota_norm"]})
    context = fetch_target_context(cur, notes)
    for doc in documents:
        check_target_header(doc, context, tolerance)
        check_target_details(doc, context, tolerance)
    collisions = apply_cross_source_collision_rules(documents)
    already_mapped = check_existing_registry(documents, cur)
    documents, ready_lines = finalize_decisions(documents, context)
    document_rows = [report_document_row(doc) for doc in documents]
    line_exceptions = [item for doc in documents for item in doc["line_exceptions"]]
    decisions = Counter(item["decision"] for item in documents)
    reasons = Counter(code for item in documents for code in item["reason_codes"])
    source_counts = {source: sum(1 for item in documents if item["source_system"] == source) for source in SOURCE_SYSTEMS}
    return {
        "report_type": "active_sales_adoption_manifest",
        "report_version": REPORT_VERSION,
        "policy_id": POLICY_ID,
        "batch_id": args.batch_id,
        "generated_at": datetime.now(timezone.utc),
        "read_only": True,
        "writes_sql_server": False,
        "writes_postgresql": False,
        "scope": "BDM Solo + TMP Solo, canonical HJualSM + DJualSM, August 2026 final freeze staging",
        "status_profile": {
            "source_status": "RL only",
            "target_sales_order_status": TARGET_DELIVERED_STATUS,
            "target_faktur_status_open": TARGET_OPEN_INVOICE_STATUS,
            "target_faktur_status_paid": TARGET_PAID_INVOICE_STATUS,
            "target_faktur_date": "source Tanggal",
            "target_delivery_date": "source TglReal, or source Tanggal when TglReal is blank",
        },
        "stage_gate": stage_reason,
        "stages": {
            source: {
                "schema": stage.schema,
                "run_id": stage.run_id,
                "consistency_mode": stage.consistency_mode,
                "maintenance_window_id": stage.maintenance_window_id,
                "target_company_id": stage.target_company_id,
                "target_branch_id": stage.target_branch_id,
                "headers": len(headers_by_source[source]),
                "details": len(details_by_source[source]),
            }
            for source, stage in metadata.items()
        },
        "summary": {
            "source_documents": len(documents),
            "by_source": source_counts,
            "decisions": dict(sorted(decisions.items())),
            "skip_reason_counts": dict(sorted(reasons.items())),
            "line_exceptions": len(line_exceptions),
            "orphan_detail_rows": len(orphan_lines),
            "android_holds": android_holds,
            "collisions": len(collisions),
            "existing_registry_rows": len(already_mapped),
        },
        "documents": document_rows,
        "line_exceptions": line_exceptions,
        "ready_lines": ready_lines,
        "orphan_lines": orphan_lines,
        "android_holds": android_holds,
        "collisions": collisions,
        "already_mapped": already_mapped,
    }


def write_report(report: dict[str, Any], output: Path) -> str:
    output.parent.mkdir(parents=True, exist_ok=True)
    serializable = json_safe(report)
    payload = json.dumps(serializable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    serializable["report_sha256"] = digest
    output.write_text(json.dumps(serializable, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return digest


def main() -> int:
    args = parse_args()
    tolerance = ensure_args(args)
    try:
        import psycopg2  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        raise ValidationError("psycopg2 diperlukan untuk membuat manifest sales.") from exc
    connection = psycopg2.connect(
        dbname=args.pg_database,
        user=args.pg_user,
        host=args.pg_host,
        port=args.pg_port,
        connect_timeout=args.connect_timeout_seconds,
        application_name="bdm_tmp_active_sales_adoption_manifest_read_only",
    )
    try:
        with connection.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cur.execute("SET LOCAL lock_timeout = '10s'")
            cur.execute("SET LOCAL statement_timeout = %s", (f"{args.statement_timeout_seconds}s",))
            report = build_report(cur, args, tolerance)
        connection.rollback()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    digest = write_report(report, args.output)
    print(
        json.dumps(
            {
                "status": "ok",
                "output": str(args.output),
                "report_sha256": digest,
                "summary": json_safe(report["summary"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "error", "error_type": type(exc).__name__, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
