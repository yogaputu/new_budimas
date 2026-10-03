#!/usr/bin/env python3
"""Export source-aware master/UOM mapping review files from one staging schema.

This tool is deliberately read-only against PostgreSQL.  It writes CSV and
JSON files *only* to the local output directory supplied with ``--output-dir``.
The files make BDM Solo and TMP Solo reviewable independently before any
future migration is allowed to write to ``public`` tables.

It never creates mappings, never inserts public master data, and never treats
an ambiguous code as a match.  A unique candidate is a suggestion, not an
approved mapping.

Example on the aaPanel server (as the OS postgres user):

  python3 export_august_2026_mapping_exceptions.py \
    --schema legacy_bdm_solo_aug2026_preview_01_26_r2 \
    --output-dir /tmp/bdm-mapping-review
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
FACTOR_RE_SQL = r"^[0-9]+([.][0]+)?$"


def qident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def pg_connect(database: str, user: str, host: str | None, port: int | None):
    try:
        import psycopg2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("Modul psycopg2 diperlukan untuk export rekonsiliasi PostgreSQL.") from exc
    kwargs: dict[str, Any] = {"dbname": database, "user": user}
    if host:
        kwargs["host"] = host
    if port:
        kwargs["port"] = port
    return psycopg2.connect(**kwargs)


def scalar_to_csv(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(scalar_to_csv(item) for item in value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def fetch_one_as_dict(cursor, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
    cursor.execute(query, params)
    row = cursor.fetchone()
    if row is None:
        return {}
    return {description.name: value for description, value in zip(cursor.description, row)}


def stage_metadata(cursor, schema: str) -> dict[str, Any]:
    metadata = fetch_one_as_dict(
        cursor,
        f"""
        SELECT source_system, source_server, source_database, consistency_mode,
               target_company_id, target_branch_id, window_start, window_end_exclusive,
               modules, status, created_at, completed_at
        FROM {qident(schema)}.__stage_run
        ORDER BY id DESC
        LIMIT 1
        """,
    )
    if not metadata:
        raise RuntimeError(f"Schema {schema} tidak memiliki metadata __stage_run.")
    return metadata


def assert_expected_stage(cursor, schema: str) -> None:
    cursor.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = %s
          AND table_name = ANY(%s)
        """,
        (schema, ["customer", "principle", "sales", "stok", "hjualsm", "hjualsmandroid", "djualsm", "djualsmandroid"]),
    )
    existing = {row[0] for row in cursor.fetchall()}
    required = {"customer", "principle", "sales", "stok", "hjualsm", "hjualsmandroid", "djualsm", "djualsmandroid"}
    missing = sorted(required - existing)
    if missing:
        raise RuntimeError(f"Schema {schema} bukan staging master+sales yang lengkap. Tabel kurang: {', '.join(missing)}")


def export_query(cursor, query: str, params: tuple[Any, ...], path: Path) -> dict[str, Any]:
    cursor.execute(query, params)
    fieldnames = [description.name for description in cursor.description]
    status_counter: Counter[str] = Counter()
    row_count = 0
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        while True:
            rows = cursor.fetchmany(1000)
            if not rows:
                break
            for raw_row in rows:
                row = {name: scalar_to_csv(value) for name, value in zip(fieldnames, raw_row)}
                writer.writerow(row)
                row_count += 1
                if row.get("review_status"):
                    status_counter[row["review_status"]] += 1
    return {"path": path.name, "rows": row_count, "review_status": dict(sorted(status_counter.items()))}


def principal_candidates_sql(schema: str) -> str:
    return f"""
        WITH source_rows AS (
            SELECT lower(btrim(kode)) AS source_code,
                   min(nullif(btrim(nama), '')) AS source_name,
                   count(*)::bigint AS source_row_count
            FROM {qident(schema)}.principle
            WHERE btrim(coalesce(kode, '')) <> ''
            GROUP BY 1
        ), target_rows AS (
            SELECT lower(btrim(kode)) AS source_code,
                   count(*)::bigint AS target_candidate_count,
                   array_to_string(array_agg(id ORDER BY id), ',') AS target_candidate_ids,
                   string_agg(coalesce(nama, ''), ' | ' ORDER BY id) AS target_candidate_names
            FROM public.principal
            WHERE id_perusahaan = %s
              AND btrim(coalesce(kode, '')) <> ''
            GROUP BY 1
        )
        SELECT %s::text AS source_system,
               'principal'::text AS entity_type,
               s.source_code AS source_key_1,
               ''::text AS source_key_2,
               s.source_name,
               s.source_row_count,
               coalesce(t.target_candidate_count, 0)::bigint AS target_candidate_count,
               coalesce(t.target_candidate_ids, '') AS target_candidate_ids,
               coalesce(t.target_candidate_names, '') AS target_candidate_names,
               CASE
                   WHEN coalesce(t.target_candidate_count, 0) = 1 THEN 'candidate_unique'
                   WHEN coalesce(t.target_candidate_count, 0) = 0 THEN 'missing_target_principal'
                   ELSE 'ambiguous_target_principal'
               END AS review_status
        FROM source_rows s
        LEFT JOIN target_rows t USING (source_code)
        ORDER BY review_status, s.source_code
    """


def customer_candidates_sql(schema: str) -> str:
    return f"""
        WITH source_rows AS (
            SELECT lower(btrim(kode)) AS source_code,
                   min(nullif(btrim(nama), '')) AS source_name,
                   min(nullif(btrim(alamat), '')) AS source_address,
                   min(nullif(btrim(npwp), '')) AS source_npwp,
                   count(*)::bigint AS source_row_count
            FROM {qident(schema)}.customer
            WHERE btrim(coalesce(kode, '')) <> ''
            GROUP BY 1
        ), target_global AS (
            SELECT lower(btrim(kode)) AS source_code,
                   count(*)::bigint AS global_candidate_count,
                   array_to_string(array_agg(id ORDER BY id), ',') AS global_candidate_ids,
                   string_agg(
                       coalesce(nama, '') || ' [cabang ' || coalesce(id_cabang::text, '-') || ']',
                       ' | ' ORDER BY id
                   ) AS global_candidate_names
            FROM public.customer
            WHERE btrim(coalesce(kode, '')) <> ''
            GROUP BY 1
        ), target_branch AS (
            SELECT lower(btrim(kode)) AS source_code,
                   count(*)::bigint AS branch_candidate_count,
                   array_to_string(array_agg(id ORDER BY id), ',') AS branch_candidate_ids,
                   string_agg(coalesce(nama, ''), ' | ' ORDER BY id) AS branch_candidate_names
            FROM public.customer
            WHERE id_cabang = %s
              AND btrim(coalesce(kode, '')) <> ''
            GROUP BY 1
        )
        SELECT %s::text AS source_system,
               'customer'::text AS entity_type,
               s.source_code AS source_key_1,
               ''::text AS source_key_2,
               s.source_name,
               s.source_address,
               s.source_npwp,
               s.source_row_count,
               coalesce(b.branch_candidate_count, 0)::bigint AS target_branch_candidate_count,
               coalesce(b.branch_candidate_ids, '') AS target_branch_candidate_ids,
               coalesce(b.branch_candidate_names, '') AS target_branch_candidate_names,
               coalesce(g.global_candidate_count, 0)::bigint AS target_global_candidate_count,
               coalesce(g.global_candidate_ids, '') AS target_global_candidate_ids,
               coalesce(g.global_candidate_names, '') AS target_global_candidate_names,
               CASE
                   WHEN coalesce(b.branch_candidate_count, 0) = 1 THEN 'candidate_unique_in_target_branch'
                   WHEN coalesce(b.branch_candidate_count, 0) > 1 THEN 'ambiguous_in_target_branch'
                   WHEN coalesce(g.global_candidate_count, 0) = 1 THEN 'only_outside_target_branch_requires_policy'
                   WHEN coalesce(g.global_candidate_count, 0) = 0 THEN 'missing_target_customer'
                   ELSE 'ambiguous_global_customer'
               END AS review_status
        FROM source_rows s
        LEFT JOIN target_branch b USING (source_code)
        LEFT JOIN target_global g USING (source_code)
        ORDER BY review_status, s.source_code
    """


def sales_candidates_sql(schema: str) -> str:
    return f"""
        WITH source_rows AS (
            SELECT lower(btrim(kode)) AS sales_code,
                   lower(btrim(kodeprinciple)) AS principal_code,
                   min(nullif(btrim(nama), '')) AS source_name,
                   count(*)::bigint AS source_row_count
            FROM {qident(schema)}.sales
            WHERE btrim(coalesce(kode, '')) <> ''
            GROUP BY 1, 2
        ), target_rows AS (
            SELECT lower(btrim(sd.kode_sales)) AS sales_code,
                   lower(btrim(p.kode)) AS principal_code,
                   count(DISTINCT s.id)::bigint AS target_candidate_count,
                   array_to_string(array_agg(DISTINCT s.id ORDER BY s.id), ',') AS target_candidate_ids
            FROM public.sales_detail sd
            JOIN public.sales s ON s.id = sd.id_sales
            JOIN public.principal p ON p.id = s.id_principal
            WHERE p.id_perusahaan = %s
              AND btrim(coalesce(sd.kode_sales, '')) <> ''
            GROUP BY 1, 2
        )
        SELECT %s::text AS source_system,
               'sales'::text AS entity_type,
               s.sales_code AS source_key_1,
               s.principal_code AS source_key_2,
               s.source_name,
               s.source_row_count,
               coalesce(t.target_candidate_count, 0)::bigint AS target_candidate_count,
               coalesce(t.target_candidate_ids, '') AS target_candidate_ids,
               CASE
                   WHEN coalesce(t.target_candidate_count, 0) = 1 THEN 'candidate_unique'
                   WHEN coalesce(t.target_candidate_count, 0) = 0 THEN 'missing_target_sales'
                   ELSE 'ambiguous_target_sales'
               END AS review_status
        FROM source_rows s
        LEFT JOIN target_rows t USING (sales_code, principal_code)
        ORDER BY review_status, s.principal_code, s.sales_code
    """


def product_candidates_sql(schema: str) -> str:
    return f"""
        WITH source_rows AS (
            SELECT lower(btrim(kode)) AS sku,
                   lower(btrim(principle)) AS principal_code,
                   min(nullif(btrim(nama), '')) AS source_name,
                   min(nullif(lower(btrim(satuan)), '')) AS source_base_uom,
                   min(nullif(lower(btrim(namaunit)), '')) AS source_pack_uom,
                   min(nullif(btrim(perunit), '')) AS source_pack_factor,
                   count(*)::bigint AS source_row_count
            FROM {qident(schema)}.stok
            WHERE btrim(coalesce(kode, '')) <> ''
            GROUP BY 1, 2
        ), target_rows AS (
            SELECT lower(btrim(prd.kode_sku)) AS sku,
                   lower(btrim(pr.kode)) AS principal_code,
                   count(DISTINCT prd.id)::bigint AS target_candidate_count,
                   array_to_string(array_agg(DISTINCT prd.id ORDER BY prd.id), ',') AS target_candidate_ids,
                   string_agg(DISTINCT coalesce(prd.nama, ''), ' | ') AS target_candidate_names
            FROM public.produk prd
            JOIN public.principal pr ON pr.id = prd.id_principal
            WHERE pr.id_perusahaan = %s
              AND btrim(coalesce(prd.kode_sku, '')) <> ''
            GROUP BY 1, 2
        )
        SELECT %s::text AS source_system,
               'product'::text AS entity_type,
               s.sku AS source_key_1,
               s.principal_code AS source_key_2,
               s.source_name,
               s.source_base_uom,
               s.source_pack_uom,
               s.source_pack_factor,
               s.source_row_count,
               coalesce(t.target_candidate_count, 0)::bigint AS target_candidate_count,
               coalesce(t.target_candidate_ids, '') AS target_candidate_ids,
               coalesce(t.target_candidate_names, '') AS target_candidate_names,
               CASE
                   WHEN coalesce(t.target_candidate_count, 0) = 1 THEN 'candidate_unique'
                   WHEN coalesce(t.target_candidate_count, 0) = 0 THEN 'missing_target_product'
                   ELSE 'ambiguous_target_product'
               END AS review_status
        FROM source_rows s
        LEFT JOIN target_rows t USING (sku, principal_code)
        ORDER BY review_status, s.principal_code, s.sku
    """


def uom_review_sql(schema: str) -> str:
    return f"""
        WITH used_sku AS (
            SELECT lower(btrim(kodestok)) AS sku, lower(btrim(kodeprinciple)) AS principal_code
            FROM {qident(schema)}.djualsm
            WHERE btrim(coalesce(kodestok, '')) <> ''
            GROUP BY 1, 2
            UNION
            SELECT lower(btrim(kodestok)) AS sku, lower(btrim(kodeprinciple)) AS principal_code
            FROM {qident(schema)}.djualsmandroid
            WHERE btrim(coalesce(kodestok, '')) <> ''
            GROUP BY 1, 2
        ), source_stock_raw AS (
            SELECT lower(btrim(kode)) AS sku,
                   lower(btrim(principle)) AS principal_code,
                   nullif(btrim(nama), '') AS source_name,
                   nullif(lower(btrim(satuan)), '') AS source_base_uom,
                   nullif(lower(btrim(namaunit)), '') AS source_pack_uom,
                   nullif(btrim(perunit), '') AS source_pack_factor
            FROM {qident(schema)}.stok
            WHERE btrim(coalesce(kode, '')) <> ''
        ), source_stock AS (
            -- Retain every distinct CT/PCS configuration per SKU.  Choosing
            -- MIN(UOM) here could hide a bad configuration that is actually
            -- used by sales history.
            SELECT sku,
                   principal_code,
                   min(source_name) AS source_name,
                   source_base_uom,
                   source_pack_uom,
                   source_pack_factor
            FROM source_stock_raw
            GROUP BY sku, principal_code, source_base_uom, source_pack_uom, source_pack_factor
        ), target_product AS (
            SELECT lower(btrim(prd.kode_sku)) AS sku,
                   lower(btrim(pr.kode)) AS principal_code,
                   count(DISTINCT prd.id)::bigint AS target_product_count,
                   array_to_string(array_agg(DISTINCT prd.id ORDER BY prd.id), ',') AS target_product_ids,
                   min(prd.id) AS id_produk
            FROM public.produk prd
            JOIN public.principal pr ON pr.id = prd.id_principal
            WHERE pr.id_perusahaan = %s
              AND btrim(coalesce(prd.kode_sku, '')) <> ''
            GROUP BY 1, 2
        ), target_uoms AS (
            SELECT pu.id_produk,
                   string_agg(
                       'level=' || coalesce(pu.level::text, '-') ||
                       ', kode=' || coalesce(pu.kode, '') ||
                       ', faktor=' || coalesce(pu.faktor_konversi::text, ''),
                       ' | ' ORDER BY pu.level, pu.id
                   ) AS target_uom_configuration
            FROM public.produk_uom pu
            GROUP BY pu.id_produk
        ), checks AS (
            SELECT u.sku,
                   u.principal_code,
                   ss.source_name,
                   ss.source_base_uom,
                   ss.source_pack_uom,
                   ss.source_pack_factor,
                   coalesce(tp.target_product_count, 0)::bigint AS target_product_count,
                   coalesce(tp.target_product_ids, '') AS target_product_ids,
                   tu.target_uom_configuration,
                   CASE
                       WHEN coalesce(tp.target_product_count, 0) = 1 THEN EXISTS (
                           SELECT 1
                           FROM public.produk_uom pu
                           WHERE pu.id_produk = tp.id_produk
                             AND pu.level = 1
                             AND lower(btrim(pu.kode)) = coalesce(ss.source_base_uom, '')
                             AND coalesce(pu.faktor_konversi, 1) = 1
                       )
                       ELSE FALSE
                   END AS base_uom_ok,
                   CASE
                       WHEN coalesce(tp.target_product_count, 0) = 1
                        AND coalesce(ss.source_pack_factor, '') ~ %s
                        AND ss.source_pack_factor::numeric > 0
                       THEN EXISTS (
                           SELECT 1
                           FROM public.produk_uom pu
                           WHERE pu.id_produk = tp.id_produk
                             AND pu.level = 2
                             AND lower(btrim(pu.kode)) = coalesce(ss.source_pack_uom, '')
                             AND pu.faktor_konversi = ss.source_pack_factor::numeric::integer
                       )
                       ELSE FALSE
                   END AS pack_uom_level2_ok,
                   CASE
                       WHEN coalesce(tp.target_product_count, 0) = 1
                        AND coalesce(ss.source_pack_factor, '') ~ %s
                        AND ss.source_pack_factor::numeric > 0
                       THEN EXISTS (
                           SELECT 1
                           FROM public.produk_uom pu
                           WHERE pu.id_produk = tp.id_produk
                             AND pu.level > 1
                             AND lower(btrim(pu.kode)) = coalesce(ss.source_pack_uom, '')
                             AND pu.faktor_konversi = ss.source_pack_factor::numeric::integer
                       )
                       ELSE FALSE
                   END AS pack_uom_equivalent_ok,
                   CASE
                       WHEN coalesce(ss.source_pack_factor, '') ~ %s
                        AND ss.source_pack_factor::numeric > 0
                       THEN TRUE
                       ELSE FALSE
                   END AS source_factor_valid
            FROM used_sku u
            LEFT JOIN source_stock ss USING (sku, principal_code)
            LEFT JOIN target_product tp USING (sku, principal_code)
            LEFT JOIN target_uoms tu ON tu.id_produk = tp.id_produk
        )
        SELECT %s::text AS source_system,
               'product_uom'::text AS entity_type,
               sku AS source_key_1,
               principal_code AS source_key_2,
               source_name,
               coalesce(source_base_uom, '') AS source_base_uom,
               coalesce(source_pack_uom, '') AS source_pack_uom,
               coalesce(source_pack_factor, '') AS source_pack_factor,
               target_product_count,
               target_product_ids,
               coalesce(target_uom_configuration, '') AS target_uom_configuration,
               base_uom_ok,
               source_factor_valid,
               pack_uom_level2_ok,
               pack_uom_equivalent_ok,
               CASE
                   WHEN target_product_count = 0 THEN 'product_missing'
                   WHEN target_product_count > 1 THEN 'product_ambiguous'
                   WHEN NOT base_uom_ok THEN 'missing_base_uom'
                   WHEN NOT source_factor_valid THEN 'invalid_source_pack_factor'
                   WHEN NOT pack_uom_equivalent_ok THEN 'missing_or_wrong_pack_uom'
                   WHEN NOT pack_uom_level2_ok THEN 'uom_ready_equivalent_level'
                   ELSE 'uom_ready'
               END AS review_status
        FROM checks
        ORDER BY review_status, principal_code, sku
    """


def header_exceptions_sql(schema: str) -> str:
    return f"""
        WITH headers AS (
            SELECT 'HJualSM'::text AS source_table,
                   staging_id,
                   nullif(btrim(nota), '') AS nota,
                   nullif(btrim(tanggal), '') AS tanggal,
                   lower(btrim(kodecustomer)) AS customer_code,
                   nullif(btrim(namacustomer), '') AS customer_name,
                   lower(btrim(kodeprinciple)) AS principal_code,
                   lower(btrim(kodesales)) AS sales_code
            FROM {qident(schema)}.hjualsm
            UNION ALL
            SELECT 'HJualSMAndroid'::text,
                   staging_id,
                   nullif(btrim(nota), ''),
                   nullif(btrim(tanggal), ''),
                   lower(btrim(kodecustomer)),
                   nullif(btrim(namacustomer), ''),
                   lower(btrim(kodeprinciple)),
                   lower(btrim(kodesales))
            FROM {qident(schema)}.hjualsmandroid
        ), customer_map AS (
            SELECT lower(btrim(kode)) AS customer_code,
                   count(*)::bigint AS candidate_count,
                   array_to_string(array_agg(id ORDER BY id), ',') AS candidate_ids
            FROM public.customer
            WHERE btrim(coalesce(kode, '')) <> ''
            GROUP BY 1
        ), principal_map AS (
            SELECT lower(btrim(kode)) AS principal_code,
                   count(*)::bigint AS candidate_count,
                   array_to_string(array_agg(id ORDER BY id), ',') AS candidate_ids
            FROM public.principal
            WHERE id_perusahaan = %s
              AND btrim(coalesce(kode, '')) <> ''
            GROUP BY 1
        ), sales_map AS (
            SELECT lower(btrim(sd.kode_sales)) AS sales_code,
                   lower(btrim(p.kode)) AS principal_code,
                   count(DISTINCT s.id)::bigint AS candidate_count,
                   array_to_string(array_agg(DISTINCT s.id ORDER BY s.id), ',') AS candidate_ids
            FROM public.sales_detail sd
            JOIN public.sales s ON s.id = sd.id_sales
            JOIN public.principal p ON p.id = s.id_principal
            WHERE p.id_perusahaan = %s
              AND btrim(coalesce(sd.kode_sales, '')) <> ''
            GROUP BY 1, 2
        )
        SELECT %s::text AS source_system,
               h.source_table,
               h.staging_id,
               coalesce(h.nota, '') AS nota,
               coalesce(h.tanggal, '') AS tanggal,
               h.customer_code,
               h.customer_name,
               h.principal_code,
               h.sales_code,
               coalesce(c.candidate_count, 0)::bigint AS customer_candidate_count,
               coalesce(c.candidate_ids, '') AS customer_candidate_ids,
               coalesce(p.candidate_count, 0)::bigint AS principal_candidate_count,
               coalesce(p.candidate_ids, '') AS principal_candidate_ids,
               coalesce(s.candidate_count, 0)::bigint AS sales_candidate_count,
               coalesce(s.candidate_ids, '') AS sales_candidate_ids,
               concat_ws('; ',
                   CASE WHEN coalesce(c.candidate_count, 0) <> 1 THEN 'customer_not_resolved' END,
                   CASE WHEN coalesce(p.candidate_count, 0) <> 1 THEN 'principal_not_resolved' END,
                   CASE WHEN coalesce(s.candidate_count, 0) <> 1 THEN 'sales_not_resolved' END
               ) AS review_status
        FROM headers h
        LEFT JOIN customer_map c USING (customer_code)
        LEFT JOIN principal_map p USING (principal_code)
        LEFT JOIN sales_map s USING (sales_code, principal_code)
        WHERE coalesce(c.candidate_count, 0) <> 1
           OR coalesce(p.candidate_count, 0) <> 1
           OR coalesce(s.candidate_count, 0) <> 1
        ORDER BY h.source_table, h.tanggal, h.nota, h.staging_id
    """


def write_review_queue(output_dir: Path, source_system: str) -> dict[str, Any]:
    fields = [
        "source_system",
        "entity_type",
        "source_key_1",
        "source_key_2",
        "source_name",
        "review_status",
        "suggested_target_id",
        "decision",
        "approved_target_id",
        "reviewer_note",
    ]
    queue_path = output_dir / "mapping_review_queue.csv"
    rows = 0
    with queue_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for entity, filename in (
            ("principal", "principal_candidates.csv"),
            ("customer", "customer_candidates.csv"),
            ("sales", "sales_candidates.csv"),
            ("product", "product_candidates.csv"),
        ):
            with (output_dir / filename).open(encoding="utf-8-sig", newline="") as source_file:
                for row in csv.DictReader(source_file):
                    if row.get("review_status", "").startswith("candidate_unique"):
                        continue
                    suggested = row.get("target_candidate_ids", "")
                    if entity == "customer":
                        suggested = row.get("target_branch_candidate_ids", "") or row.get("target_global_candidate_ids", "")
                    writer.writerow(
                        {
                            "source_system": source_system,
                            "entity_type": entity,
                            "source_key_1": row.get("source_key_1", ""),
                            "source_key_2": row.get("source_key_2", ""),
                            "source_name": row.get("source_name", ""),
                            "review_status": row.get("review_status", ""),
                            "suggested_target_id": suggested,
                            "decision": "",
                            "approved_target_id": "",
                            "reviewer_note": "",
                        }
                    )
                    rows += 1
    return {"path": queue_path.name, "rows": rows}


def write_readme(output_dir: Path, metadata: dict[str, Any]) -> None:
    text = f"""# Review mapping staging {metadata['source_system']}

Staging schema: `{metadata.get('schema', '')}`  
Jendela data: `{metadata['window_start']}` sampai sebelum `{metadata['window_end_exclusive']}`  
Mode konsistensi sumber: `{metadata['consistency_mode']}`

Semua file di folder ini adalah hasil **read-only**. Tidak ada data pada tabel
`public` yang dibuat atau diubah oleh exporter ini.

- `*_candidates.csv` berisi semua kode sumber dan kandidat target berdasarkan
  kode bisnis serta scope perusahaan/cabang. Status `candidate_unique` adalah
  kandidat saja, belum persetujuan merge.
- `mapping_review_queue.csv` hanya berisi master yang tidak memiliki kandidat
  unik. Isi `decision`, `approved_target_id`, dan `reviewer_note` setelah
  diverifikasi.
- `used_product_uom.csv` wajib berstatus `uom_ready` untuk SKU yang dipakai
  transaksi sebelum sales detail boleh dimigrasikan. Jangan mengubah qty CT/PCS
  menjadi angka target tanpa konfigurasi UOM yang cocok.
- `sales_header_exceptions.csv` adalah dampak master yang belum resolvable pada
  dokumen. Jangan membuat faktur/order publik untuk baris tersebut.

Catatan pelanggan: `only_outside_target_branch_requires_policy` berarti kode
pelanggan hanya ditemukan pada cabang lain. Pilih secara eksplisit apakah akan
dipakai sebagai pelanggan lintas cabang atau dibuat/dikaitkan pada cabang Solo;
jangan dipetakan otomatis hanya berdasarkan kode.
"""
    (output_dir / "README.md").write_text(text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", required=True, help="Nama schema staging yang akan dibaca.")
    parser.add_argument("--output-dir", required=True, help="Direktori baru untuk CSV/JSON hasil export.")
    parser.add_argument("--target-database", default=os.getenv("MIGRATION_PG_DATABASE", "budimas_dev"))
    parser.add_argument("--target-user", default=os.getenv("MIGRATION_PG_USER", "postgres"))
    parser.add_argument("--target-host", default=os.getenv("MIGRATION_PG_HOST", ""))
    parser.add_argument("--target-port", type=int, default=int(os.getenv("MIGRATION_PG_PORT", "0") or 0))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not SCHEMA_RE.fullmatch(args.schema):
        raise SystemExit("--schema tidak aman.")
    output_dir = Path(args.output_dir).expanduser().resolve()
    if output_dir.exists():
        if any(output_dir.iterdir()):
            raise SystemExit(f"--output-dir harus baru/kosong agar hasil lama tidak tertimpa: {output_dir}")
    else:
        output_dir.mkdir(parents=True)

    conn = pg_connect(args.target_database, args.target_user, args.target_host or None, args.target_port or None)
    try:
        conn.set_session(readonly=True, autocommit=False)
        with conn.cursor() as cursor:
            assert_expected_stage(cursor, args.schema)
            metadata = stage_metadata(cursor, args.schema)
            metadata["schema"] = args.schema
            company_id = int(metadata["target_company_id"])
            branch_id = int(metadata["target_branch_id"])
            source_system = str(metadata["source_system"])

            outputs = {
                "principal_candidates": export_query(
                    cursor,
                    principal_candidates_sql(args.schema),
                    (company_id, source_system),
                    output_dir / "principal_candidates.csv",
                ),
                "customer_candidates": export_query(
                    cursor,
                    customer_candidates_sql(args.schema),
                    (branch_id, source_system),
                    output_dir / "customer_candidates.csv",
                ),
                "sales_candidates": export_query(
                    cursor,
                    sales_candidates_sql(args.schema),
                    (company_id, source_system),
                    output_dir / "sales_candidates.csv",
                ),
                "product_candidates": export_query(
                    cursor,
                    product_candidates_sql(args.schema),
                    (company_id, source_system),
                    output_dir / "product_candidates.csv",
                ),
                "used_product_uom": export_query(
                    cursor,
                    uom_review_sql(args.schema),
                    (company_id, FACTOR_RE_SQL, FACTOR_RE_SQL, FACTOR_RE_SQL, source_system),
                    output_dir / "used_product_uom.csv",
                ),
                "sales_header_exceptions": export_query(
                    cursor,
                    header_exceptions_sql(args.schema),
                    (company_id, company_id, source_system),
                    output_dir / "sales_header_exceptions.csv",
                ),
            }
            conn.rollback()

        outputs["mapping_review_queue"] = write_review_queue(output_dir, source_system)
        write_readme(output_dir, metadata)
        summary = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "read_only": True,
            "merge_allowed": False,
            "merge_allowed_reason": "Hasil ini hanya review mapping. Snapshot final dan mapping eksplisit per source_system tetap wajib.",
            "stage": {key: scalar_to_csv(value) for key, value in metadata.items()},
            "outputs": outputs,
        }
        (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
