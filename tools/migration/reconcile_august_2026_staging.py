#!/usr/bin/env python3
"""Read-only mapping and UOM reconciliation for one August 2026 staging schema.

The report is source-aware: BDM and TMP must be reconciled separately.  It
does not insert mappings or mutate application tables.  A ``ready`` result is
only a precondition for a later, explicit merge run; it is never permission to
write directly to ERP public tables.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any


SCHEMA_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def qident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def pg_connect(database: str, user: str, host: str | None, port: int | None):
    try:
        import psycopg2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("Modul psycopg2 diperlukan untuk rekonsiliasi PostgreSQL.") from exc
    kwargs: dict[str, Any] = {"dbname": database, "user": user}
    if host:
        kwargs["host"] = host
    if port:
        kwargs["port"] = port
    return psycopg2.connect(**kwargs)


def fetch_metrics(cursor, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
    cursor.execute(query, params)
    row = cursor.fetchone()
    return {description.name: value for description, value in zip(cursor.description, row)}


def run_metadata(cursor, schema: str) -> dict[str, Any]:
    cursor.execute(
        f"""
        SELECT source_system, source_server, source_database, consistency_mode,
               target_company_id, target_branch_id, window_start, window_end_exclusive,
               modules, status, created_at, completed_at
        FROM {qident(schema)}.__stage_run
        ORDER BY id DESC
        LIMIT 1
        """
    )
    row = cursor.fetchone()
    if not row:
        raise RuntimeError(f"Schema {schema} tidak memiliki metadata staging.")
    return {description.name: str(value) if hasattr(value, "isoformat") else value for description, value in zip(cursor.description, row)}


def coverage_by_code(cursor, source_schema: str, source_table: str, source_code: str, target_sql: str, params: tuple[Any, ...]) -> dict[str, int]:
    return fetch_metrics(
        cursor,
        f"""
        WITH source_codes AS (
            SELECT lower(btrim({qident(source_code)})) AS code
            FROM {qident(source_schema)}.{qident(source_table)}
            WHERE btrim(coalesce({qident(source_code)}, '')) <> ''
            GROUP BY 1
        ), target_codes AS ({target_sql})
        SELECT
            COUNT(*)::bigint AS source_codes,
            COUNT(*) FILTER (WHERE target_count = 1)::bigint AS matched_once,
            COUNT(*) FILTER (WHERE target_count IS NULL)::bigint AS missing,
            COUNT(*) FILTER (WHERE target_count > 1)::bigint AS ambiguous
        FROM source_codes s
        LEFT JOIN target_codes t USING (code)
        """,
        params,
    )


def coverage_principal(cursor, schema: str, company_id: int) -> dict[str, int]:
    return coverage_by_code(
        cursor,
        schema,
        "principle",
        "kode",
        """
        SELECT lower(btrim(kode)) AS code, COUNT(*)::bigint AS target_count
        FROM public.principal
        WHERE id_perusahaan = %s AND btrim(coalesce(kode, '')) <> ''
        GROUP BY 1
        """,
        (company_id,),
    )


def coverage_customer(cursor, schema: str, branch_id: int, branch_only: bool) -> dict[str, int]:
    branch_condition = "AND id_cabang = %s" if branch_only else ""
    params: tuple[Any, ...] = (branch_id,) if branch_only else ()
    label = "customer_branch" if branch_only else "customer_global"
    result = coverage_by_code(
        cursor,
        schema,
        "customer",
        "kode",
        f"""
        SELECT lower(btrim(kode)) AS code, COUNT(*)::bigint AS target_count
        FROM public.customer
        WHERE btrim(coalesce(kode, '')) <> '' {branch_condition}
        GROUP BY 1
        """,
        params,
    )
    result["scope"] = label
    return result


def coverage_sales(cursor, schema: str, company_id: int) -> dict[str, int]:
    return fetch_metrics(
        cursor,
        f"""
        WITH source_sales AS (
            SELECT lower(btrim(kode)) AS sales_code,
                   lower(btrim(kodeprinciple)) AS principal_code
            FROM {qident(schema)}.sales
            WHERE btrim(coalesce(kode, '')) <> ''
            GROUP BY 1, 2
        ), target_sales AS (
            SELECT lower(btrim(sd.kode_sales)) AS sales_code,
                   lower(btrim(p.kode)) AS principal_code,
                   COUNT(DISTINCT s.id)::bigint AS target_count
            FROM public.sales_detail sd
            JOIN public.sales s ON s.id = sd.id_sales
            JOIN public.principal p ON p.id = s.id_principal
            WHERE p.id_perusahaan = %s
              AND btrim(coalesce(sd.kode_sales, '')) <> ''
            GROUP BY 1, 2
        )
        SELECT
            COUNT(*)::bigint AS source_pairs,
            COUNT(*) FILTER (WHERE t.target_count = 1)::bigint AS matched_once,
            COUNT(*) FILTER (WHERE t.target_count IS NULL)::bigint AS missing,
            COUNT(*) FILTER (WHERE t.target_count > 1)::bigint AS ambiguous
        FROM source_sales s
        LEFT JOIN target_sales t USING (sales_code, principal_code)
        """,
        (company_id,),
    )


def coverage_product(cursor, schema: str, company_id: int) -> dict[str, int]:
    return fetch_metrics(
        cursor,
        f"""
        WITH source_products AS (
            SELECT lower(btrim(kode)) AS sku,
                   lower(btrim(principle)) AS principal_code
            FROM {qident(schema)}.stok
            WHERE btrim(coalesce(kode, '')) <> ''
            GROUP BY 1, 2
        ), target_products AS (
            SELECT lower(btrim(prd.kode_sku)) AS sku,
                   lower(btrim(pr.kode)) AS principal_code,
                   COUNT(DISTINCT prd.id)::bigint AS target_count
            FROM public.produk prd
            JOIN public.principal pr ON pr.id = prd.id_principal
            WHERE pr.id_perusahaan = %s
              AND btrim(coalesce(prd.kode_sku, '')) <> ''
            GROUP BY 1, 2
        )
        SELECT
            COUNT(*)::bigint AS source_pairs,
            COUNT(*) FILTER (WHERE t.target_count = 1)::bigint AS matched_once,
            COUNT(*) FILTER (WHERE t.target_count IS NULL)::bigint AS missing,
            COUNT(*) FILTER (WHERE t.target_count > 1)::bigint AS ambiguous
        FROM source_products s
        LEFT JOIN target_products t USING (sku, principal_code)
        """,
        (company_id,),
    )


def used_product_uom(cursor, schema: str, company_id: int) -> dict[str, int]:
    return fetch_metrics(
        cursor,
        f"""
        WITH used_sku AS (
            SELECT lower(btrim(kodestok)) AS sku, lower(btrim(kodeprinciple)) AS principal_code
            FROM {qident(schema)}.djualsm
            WHERE btrim(coalesce(kodestok, '')) <> ''
            UNION
            SELECT lower(btrim(kodestok)) AS sku, lower(btrim(kodeprinciple)) AS principal_code
            FROM {qident(schema)}.djualsmandroid
            WHERE btrim(coalesce(kodestok, '')) <> ''
        ), source_stock AS (
            SELECT lower(btrim(kode)) AS sku,
                   lower(btrim(principle)) AS principal_code,
                   lower(btrim(satuan)) AS base_uom,
                   lower(btrim(namaunit)) AS pack_uom,
                   btrim(perunit) AS pack_factor
            FROM {qident(schema)}.stok
            WHERE btrim(coalesce(kode, '')) <> ''
        ), matched_product AS (
            SELECT u.sku, u.principal_code, ss.base_uom, ss.pack_uom, ss.pack_factor,
                   COUNT(DISTINCT prd.id)::bigint AS product_count,
                   MIN(prd.id) AS id_produk
            FROM used_sku u
            LEFT JOIN source_stock ss USING (sku, principal_code)
            LEFT JOIN public.principal pr
              ON lower(btrim(pr.kode)) = u.principal_code
             AND pr.id_perusahaan = %s
            LEFT JOIN public.produk prd
              ON prd.id_principal = pr.id
             AND lower(btrim(prd.kode_sku)) = u.sku
            GROUP BY u.sku, u.principal_code, ss.base_uom, ss.pack_uom, ss.pack_factor
        ), uom_status AS (
            SELECT m.*,
                   EXISTS (
                       SELECT 1 FROM public.produk_uom pu
                       WHERE pu.id_produk = m.id_produk
                         AND pu.level = 1
                         AND lower(btrim(pu.kode)) = m.base_uom
                         AND COALESCE(pu.faktor_konversi, 1) = 1
                   ) AS base_uom_ok,
                   CASE
                       WHEN m.pack_factor ~ '^[0-9]+([.][0]+)?$' AND m.pack_factor::numeric > 0 THEN EXISTS (
                           SELECT 1 FROM public.produk_uom pu
                           WHERE pu.id_produk = m.id_produk
                             AND pu.level = 2
                             AND lower(btrim(pu.kode)) = m.pack_uom
                             AND pu.faktor_konversi = m.pack_factor::numeric::integer
                       )
                       ELSE FALSE
                   END AS pack_uom_level2_ok,
                   CASE
                       WHEN m.pack_factor ~ '^[0-9]+([.][0]+)?$' AND m.pack_factor::numeric > 0 THEN EXISTS (
                           SELECT 1 FROM public.produk_uom pu
                           WHERE pu.id_produk = m.id_produk
                             AND pu.level > 1
                             AND lower(btrim(pu.kode)) = m.pack_uom
                             AND pu.faktor_konversi = m.pack_factor::numeric::integer
                       )
                       ELSE FALSE
                   END AS pack_uom_equivalent_ok,
                   CASE
                       WHEN m.pack_factor ~ '^[0-9]+([.][0]+)?$' AND m.pack_factor::numeric > 0 THEN TRUE
                       ELSE FALSE
                   END AS source_factor_valid
            FROM matched_product m
        )
        SELECT
            COUNT(*)::bigint AS used_sku_pairs,
            COUNT(*) FILTER (WHERE product_count = 1)::bigint AS product_matched_once,
            COUNT(*) FILTER (WHERE product_count = 0)::bigint AS product_missing,
            COUNT(*) FILTER (WHERE product_count > 1)::bigint AS product_ambiguous,
            COUNT(*) FILTER (WHERE product_count = 1 AND NOT base_uom_ok)::bigint AS missing_base_uom,
            COUNT(*) FILTER (WHERE product_count = 1 AND NOT source_factor_valid)::bigint AS invalid_source_pack_factor,
            COUNT(*) FILTER (WHERE product_count = 1 AND source_factor_valid AND NOT pack_uom_equivalent_ok)::bigint AS missing_or_wrong_pack_uom,
            COUNT(*) FILTER (
                WHERE product_count = 1
                  AND source_factor_valid
                  AND pack_uom_equivalent_ok
                  AND NOT pack_uom_level2_ok
            )::bigint AS equivalent_pack_uom_different_level
        FROM uom_status
        """,
        (company_id,),
    )


def headers_ready(cursor, schema: str, company_id: int) -> dict[str, int]:
    return fetch_metrics(
        cursor,
        f"""
        WITH headers AS (
            SELECT lower(btrim(kodecustomer)) AS customer_code,
                   lower(btrim(kodeprinciple)) AS principal_code,
                   lower(btrim(kodesales)) AS sales_code
            FROM {qident(schema)}.hjualsm
            UNION ALL
            SELECT lower(btrim(kodecustomer)), lower(btrim(kodeprinciple)), lower(btrim(kodesales))
            FROM {qident(schema)}.hjualsmandroid
        ), customer_map AS (
            SELECT lower(btrim(kode)) AS customer_code, COUNT(*)::bigint AS target_count
            FROM public.customer
            WHERE btrim(coalesce(kode, '')) <> ''
            GROUP BY 1
        ), principal_map AS (
            SELECT lower(btrim(kode)) AS principal_code, COUNT(*)::bigint AS target_count
            FROM public.principal
            WHERE id_perusahaan = %s AND btrim(coalesce(kode, '')) <> ''
            GROUP BY 1
        ), sales_map AS (
            SELECT lower(btrim(sd.kode_sales)) AS sales_code,
                   lower(btrim(p.kode)) AS principal_code,
                   COUNT(DISTINCT s.id)::bigint AS target_count
            FROM public.sales_detail sd
            JOIN public.sales s ON s.id = sd.id_sales
            JOIN public.principal p ON p.id = s.id_principal
            WHERE p.id_perusahaan = %s AND btrim(coalesce(sd.kode_sales, '')) <> ''
            GROUP BY 1, 2
        )
        SELECT
            COUNT(*)::bigint AS header_rows,
            COUNT(*) FILTER (WHERE c.target_count = 1 AND p.target_count = 1 AND s.target_count = 1)::bigint AS all_master_matched_once,
            COUNT(*) FILTER (WHERE c.target_count IS NULL OR c.target_count <> 1)::bigint AS customer_not_resolved,
            COUNT(*) FILTER (WHERE p.target_count IS NULL OR p.target_count <> 1)::bigint AS principal_not_resolved,
            COUNT(*) FILTER (WHERE s.target_count IS NULL OR s.target_count <> 1)::bigint AS sales_not_resolved
        FROM headers h
        LEFT JOIN customer_map c USING (customer_code)
        LEFT JOIN principal_map p USING (principal_code)
        LEFT JOIN sales_map s USING (sales_code, principal_code)
        """,
        (company_id, company_id),
    )


def run_report(conn, schema: str) -> dict[str, Any]:
    with conn.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
        metadata = run_metadata(cursor, schema)
        company_id = int(metadata["target_company_id"])
        branch_id = int(metadata["target_branch_id"])
        report: dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "read_only": True,
            "stage": metadata,
            "coverage": {
                "principal": coverage_principal(cursor, schema, company_id),
                "customer_global": coverage_customer(cursor, schema, branch_id, branch_only=False),
                "customer_branch": coverage_customer(cursor, schema, branch_id, branch_only=True),
                "sales": coverage_sales(cursor, schema, company_id),
                "product": coverage_product(cursor, schema, company_id),
                "used_product_uom": used_product_uom(cursor, schema, company_id),
                "sales_headers": headers_ready(cursor, schema, company_id),
            },
        }
        report["merge_allowed"] = False
        report["merge_allowed_reason"] = (
            "Laporan hanya untuk rekonsiliasi; mapping eksplisit per source_system dan snapshot final tetap wajib."
        )
        return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--target-database", default=os.getenv("MIGRATION_PG_DATABASE", "budimas_dev"))
    parser.add_argument("--target-user", default=os.getenv("MIGRATION_PG_USER", "postgres"))
    parser.add_argument("--target-host", default=os.getenv("MIGRATION_PG_HOST", ""))
    parser.add_argument("--target-port", type=int, default=int(os.getenv("MIGRATION_PG_PORT", "0") or 0))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not SCHEMA_RE.fullmatch(args.schema):
        raise SystemExit("--schema tidak aman.")
    conn = pg_connect(args.target_database, args.target_user, args.target_host or None, args.target_port or None)
    try:
        print(json.dumps(run_report(conn, args.schema), ensure_ascii=False, indent=2))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
