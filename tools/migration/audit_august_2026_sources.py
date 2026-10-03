#!/usr/bin/env python3
"""Read-only preflight audit for the BDM and TMP Solo August 2026 migration.

The legacy databases must never be combined during the audit or staging phase.
This tool connects to one or both sources independently and reports the exact
transaction footprint for a date range.  It does not connect to PostgreSQL and
does not write to either SQL Server source.

Credentials intentionally come only from environment variables:

  MIGRATION_BDM_SQL_PASSWORD
  MIGRATION_TMP_SQL_PASSWORD

Optional connection overrides use the same prefix with HOST, USER and DATABASE.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCES = {
    "bdm-solo": {
        "source_system": "bdm_solo_dist",
        "company_code": "BMM",
        "company_id": 1,
        "branch_code": "SLO",
        "branch_id": 5,
        "env_prefix": "MIGRATION_BDM_SQL",
        "host": "192.168.1.8",
        "user": "sa",
        "database": "DIST",
    },
    "tmp-solo": {
        "source_system": "tmp_solo_dist",
        "company_code": "TMP",
        "company_id": 2,
        "branch_code": "SLO",
        "branch_id": 5,
        "env_prefix": "MIGRATION_TMP_SQL",
        "host": "192.168.1.16",
        "user": "saomax",
        "database": "DIST",
    },
}

# `parent` means the child is audited through the selected header documents,
# never merely by the child's own date.  This prevents partial documents when
# header and detail timestamps differ around midnight/month boundaries.
TABLE_SPECS = (
    {
        "table": "HJualSM",
        "kind": "sales_header",
        "date_columns": ("Tanggal", "Tgl"),
        "document_columns": ("Nota", "NoNota", "No_Faktur"),
    },
    {
        "table": "DJualSM",
        "kind": "sales_detail",
        "parent": "HJualSM",
        "document_columns": ("Nota", "NoNota", "No_Faktur"),
    },
    {
        "table": "HJualSMAndroid",
        "kind": "sales_mobile_header",
        "date_columns": ("Tanggal", "Tgl"),
        "document_columns": ("Nota", "NoNota", "No_Faktur"),
    },
    {
        "table": "DJualSMAndroid",
        "kind": "sales_mobile_detail",
        "parent": "HJualSMAndroid",
        "document_columns": ("Nota", "NoNota", "No_Faktur"),
    },
    {
        "table": "HBayarSM",
        "kind": "payment_header",
        "date_columns": ("Tanggal", "Tgl"),
        "document_columns": ("NoKwitansi", "NoBukti", "No_Bukti"),
    },
    {
        "table": "DBayarSM",
        "kind": "payment_detail",
        "parent": "HBayarSM",
        "document_columns": ("NoKwitansi", "NoBukti", "No_Bukti"),
    },
    {
        "table": "Pembayaran",
        "kind": "payment_ledger",
        "date_columns": ("Tanggal", "Tgl"),
        "document_columns": ("NoKwitansi", "NoBukti", "No_Bukti", "Nota", "NoFaktur"),
    },
    {
        "table": "HReturSM",
        "kind": "return_header",
        "date_columns": ("Tanggal", "Tgl"),
        "document_columns": ("Nota", "NoNota", "No_Retur"),
    },
    {
        "table": "DReturSM",
        "kind": "return_detail",
        "parent": "HReturSM",
        "document_columns": ("Nota", "NoNota", "No_Retur"),
    },
    {
        "table": "HReturSMAndroid",
        "kind": "return_mobile_header",
        "date_columns": ("Tanggal", "Tgl"),
        "document_columns": ("Nota", "NoNota", "No_Retur"),
    },
    {
        "table": "DReturSMAndroid",
        "kind": "return_mobile_detail",
        "parent": "HReturSMAndroid",
        "document_columns": ("Nota", "NoNota", "No_Retur"),
    },
    {
        "table": "KunjunganSales",
        "kind": "sales_visit",
        "date_columns": ("Tanggal", "Tgl", "TanggalKunjungan"),
        "document_columns": ("Nota", "KodeCustomer", "Kode_Customer"),
    },
    {
        "table": "StokOpnameAndroid",
        "kind": "stock_opname",
        "date_columns": ("TanggalInput", "Tanggal", "Tgl"),
        "document_columns": ("Nota", "KodeStok", "Kode_Stok"),
    },
    {
        "table": "HPembelian",
        "kind": "purchase_header",
        "date_columns": ("Tanggal", "Tgl"),
        "document_columns": ("Nota", "NoNota", "No_Faktur"),
    },
    {
        "table": "DPembelian",
        "kind": "purchase_detail",
        "parent": "HPembelian",
        "document_columns": ("Nota", "NoNota", "No_Faktur"),
    },
)

MASTER_SPECS = (
    {"table": "Customer", "key_columns": ("Kode",)},
    {"table": "Principle", "key_columns": ("Kode",)},
    {"table": "Sales", "key_columns": ("Kode",)},
    {"table": "Plafon", "key_columns": ("KodeCustomer",)},
    {"table": "STOK", "key_columns": ("Kode",)},
)


def quote_ident(name: str) -> str:
    return "[" + name.replace("]", "]]" ) + "]"


def iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def source_config(source_name: str) -> dict[str, Any]:
    source = dict(SOURCES[source_name])
    prefix = source["env_prefix"]
    source["host"] = os.getenv(f"{prefix}_HOST", source["host"])
    source["user"] = os.getenv(f"{prefix}_USER", source["user"])
    source["database"] = os.getenv(f"{prefix}_DATABASE", source["database"])
    source["port"] = int(os.getenv(f"{prefix}_PORT", "1433") or "1433")
    source["password"] = os.getenv(f"{prefix}_PASSWORD", "")
    if not source["password"]:
        raise RuntimeError(f"{prefix}_PASSWORD belum diset.")
    return source


def connect(source: dict[str, Any]):
    try:
        import pymssql  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("Modul pymssql diperlukan untuk audit SQL Server.") from exc

    return pymssql.connect(
        server=source["host"],
        user=source["user"],
        password=source["password"],
        database=source["database"],
        port=int(source.get("port") or 1433),
        login_timeout=15,
        timeout=120,
        tds_version="7.0",
        charset="UTF-8",
    )


def get_columns(cursor, table: str) -> dict[str, str]:
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
        """,
        (table,),
    )
    return {str(row[0]).lower(): str(row[0]) for row in cursor.fetchall()}


def first_column(columns: dict[str, str], choices: tuple[str, ...]) -> str | None:
    for choice in choices:
        matched = columns.get(choice.lower())
        if matched:
            return matched
    return None


def table_name_sql(table: str) -> str:
    return f"{quote_ident('dbo')}.{quote_ident(table)}"


def base_summary(cursor, table: str, date_column: str, document_column: str | None, start: str, end: str):
    document_expr = "NULL"
    if document_column:
        document_expr = f"CONVERT(nvarchar(4000), {quote_ident(document_column)})"
    sql = f"""
        SELECT
            COUNT_BIG(*) AS row_count,
            MIN({quote_ident(date_column)}) AS min_date,
            MAX({quote_ident(date_column)}) AS max_date,
            COUNT(DISTINCT NULLIF(LTRIM(RTRIM({document_expr})), '')) AS document_count
        FROM {table_name_sql(table)}
        WHERE {quote_ident(date_column)} >= %s
          AND {quote_ident(date_column)} < %s
    """
    cursor.execute(sql, (start, end))
    rows, min_date, max_date, documents = cursor.fetchone()
    return {
        "row_count": int(rows or 0),
        "document_count": int(documents or 0),
        "min_date": iso(min_date),
        "max_date": iso(max_date),
    }


def child_summary(
    cursor,
    child_table: str,
    child_document: str,
    parent_table: str,
    parent_document: str,
    parent_date: str,
    start: str,
    end: str,
):
    child_alias = "d"
    parent_alias = "h"
    child_key = f"NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(4000), {child_alias}.{quote_ident(child_document)}))), '')"
    parent_key = f"NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(4000), {parent_alias}.{quote_ident(parent_document)}))), '')"
    sql = f"""
        SELECT
            COUNT_BIG(*) AS row_count,
            COUNT(DISTINCT {child_key}) AS document_count
        FROM {table_name_sql(child_table)} {child_alias}
        JOIN {table_name_sql(parent_table)} {parent_alias}
          ON {child_key} = {parent_key}
        WHERE {parent_alias}.{quote_ident(parent_date)} >= %s
          AND {parent_alias}.{quote_ident(parent_date)} < %s
    """
    cursor.execute(sql, (start, end))
    rows, documents = cursor.fetchone()
    return {"row_count": int(rows or 0), "document_count": int(documents or 0)}


def master_summary(cursor, table: str, key_column: str | None) -> dict[str, int]:
    key_expr = "NULL"
    if key_column:
        key_expr = f"NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(4000), {quote_ident(key_column)}))), '')"
    cursor.execute(
        f"""
        SELECT COUNT_BIG(*), COUNT(DISTINCT {key_expr})
        FROM {table_name_sql(table)}
        """
    )
    rows, keys = cursor.fetchone()
    return {"row_count": int(rows or 0), "distinct_key_count": int(keys or 0)}


def product_uom_summary(cursor, product_columns: dict[str, str]) -> dict[str, int] | None:
    code = first_column(product_columns, ("Kode",))
    base_uom = first_column(product_columns, ("Satuan",))
    pack_uom = first_column(product_columns, ("NamaUnit",))
    pack_factor = first_column(product_columns, ("PerUnit",))
    if not all((code, base_uom, pack_uom, pack_factor)):
        return None
    cursor.execute(
        f"""
        SELECT
            COUNT_BIG(*) AS product_count,
            COUNT(DISTINCT NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(4000), {quote_ident(code)}))), '')) AS sku_count,
            SUM(CASE WHEN NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(4000), {quote_ident(base_uom)}))), '') IS NULL THEN 1 ELSE 0 END) AS missing_base_uom,
            SUM(CASE WHEN NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(4000), {quote_ident(pack_uom)}))), '') IS NULL THEN 1 ELSE 0 END) AS missing_pack_uom,
            SUM(CASE WHEN NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(4000), {quote_ident(pack_factor)}))), '') IS NULL THEN 1 ELSE 0 END) AS missing_pack_factor
        FROM {table_name_sql('STOK')}
        """
    )
    products, skus, missing_base, missing_pack, missing_factor = cursor.fetchone()
    return {
        "product_count": int(products or 0),
        "sku_count": int(skus or 0),
        "missing_base_uom": int(missing_base or 0),
        "missing_pack_uom": int(missing_pack or 0),
        "missing_pack_factor": int(missing_factor or 0),
    }


def august_sales_uom_summary(cursor, metadata: dict[str, dict[str, str]], start: str, end: str) -> dict[str, int] | None:
    pairs = (("HJualSM", "DJualSM"), ("HJualSMAndroid", "DJualSMAndroid"))
    source_queries: list[str] = []
    for header_table, detail_table in pairs:
        header_columns = metadata.get(header_table, {})
        detail_columns = metadata.get(detail_table, {})
        header_date = first_column(header_columns, ("Tanggal", "Tgl"))
        header_note = first_column(header_columns, ("Nota", "NoNota", "No_Faktur"))
        detail_note = first_column(detail_columns, ("Nota", "NoNota", "No_Faktur"))
        detail_sku = first_column(detail_columns, ("KodeStok", "Kode", "Kode_Stok"))
        if not all((header_date, header_note, detail_note, detail_sku)):
            continue
        source_queries.append(
            f"""
            SELECT DISTINCT NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(4000), d.{quote_ident(detail_sku)}))), '') AS sku
            FROM {table_name_sql(detail_table)} d
            JOIN {table_name_sql(header_table)} h
              ON NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(4000), d.{quote_ident(detail_note)}))), '')
               = NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(4000), h.{quote_ident(header_note)}))), '')
            WHERE h.{quote_ident(header_date)} >= %s
              AND h.{quote_ident(header_date)} < %s
            """
        )
    stock_columns = metadata.get("STOK", {})
    stock_code = first_column(stock_columns, ("Kode",))
    stock_base_uom = first_column(stock_columns, ("Satuan",))
    stock_pack_uom = first_column(stock_columns, ("NamaUnit",))
    stock_pack_factor = first_column(stock_columns, ("PerUnit",))
    if not source_queries or not all((stock_code, stock_base_uom, stock_pack_uom, stock_pack_factor)):
        return None
    union_sql = " UNION ".join(source_queries)
    params = tuple(value for _ in source_queries for value in (start, end))
    cursor.execute(
        f"""
        WITH used_sku AS ({union_sql})
        SELECT
            COUNT(*) AS used_sku_count,
            SUM(CASE WHEN s.{quote_ident(stock_code)} IS NULL THEN 1 ELSE 0 END) AS missing_product,
            SUM(CASE WHEN s.{quote_ident(stock_code)} IS NOT NULL
                         AND NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(4000), s.{quote_ident(stock_base_uom)}))), '') IS NULL
                     THEN 1 ELSE 0 END) AS missing_base_uom,
            SUM(CASE WHEN s.{quote_ident(stock_code)} IS NOT NULL
                         AND (NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(4000), s.{quote_ident(stock_pack_uom)}))), '') IS NULL
                              OR NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(4000), s.{quote_ident(stock_pack_factor)}))), '') IS NULL)
                     THEN 1 ELSE 0 END) AS incomplete_pack_uom
        FROM used_sku u
        LEFT JOIN {table_name_sql('STOK')} s
          ON NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(4000), s.{quote_ident(stock_code)}))), '') = u.sku
        WHERE u.sku IS NOT NULL
        """,
        params,
    )
    used_sku, missing_product, missing_base, incomplete_pack = cursor.fetchone()
    return {
        "used_sku_count": int(used_sku or 0),
        "missing_product": int(missing_product or 0),
        "missing_base_uom": int(missing_base or 0),
        "incomplete_pack_uom": int(incomplete_pack or 0),
    }


def audit_source(source_name: str, start: str, end: str, include_used_sku_uom: bool) -> dict[str, Any]:
    source = source_config(source_name)
    report: dict[str, Any] = {
        "source": {key: value for key, value in source.items() if key != "password"},
        "window": {"start_inclusive": start, "end_exclusive": end},
        "tables": [],
        "masters": [],
    }
    with connect(source) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT @@SERVERNAME, DB_NAME()")
        server_name, database_name = cursor.fetchone()
        report["sql_server"] = {"server_name": str(server_name), "database_name": str(database_name)}

        metadata: dict[str, dict[str, str]] = {}
        for spec in TABLE_SPECS:
            metadata[spec["table"]] = get_columns(cursor, spec["table"])
        for spec in MASTER_SPECS:
            metadata[spec["table"]] = get_columns(cursor, spec["table"])

        parent_specs = {spec["table"]: spec for spec in TABLE_SPECS}
        for spec in TABLE_SPECS:
            table = spec["table"]
            columns = metadata[table]
            result: dict[str, Any] = {"table": table, "kind": spec["kind"]}
            if not columns:
                result["status"] = "missing_table"
                report["tables"].append(result)
                continue

            document_column = first_column(columns, spec.get("document_columns", ()))
            parent_table = spec.get("parent")
            if parent_table:
                parent = parent_specs[parent_table]
                parent_columns = metadata[parent_table]
                parent_document = first_column(parent_columns, parent.get("document_columns", ()))
                parent_date = first_column(parent_columns, parent.get("date_columns", ()))
                if not document_column or not parent_document or not parent_date:
                    result.update(
                        {
                            "status": "missing_relation_columns",
                            "document_column": document_column,
                            "parent": parent_table,
                            "parent_document_column": parent_document,
                            "parent_date_column": parent_date,
                        }
                    )
                else:
                    result.update(
                        {
                            "status": "ok_parent_selected",
                            "document_column": document_column,
                            "parent": parent_table,
                            "parent_document_column": parent_document,
                            "parent_date_column": parent_date,
                        }
                    )
                    result.update(
                        child_summary(
                            cursor,
                            table,
                            document_column,
                            parent_table,
                            parent_document,
                            parent_date,
                            start,
                            end,
                        )
                    )
            else:
                date_column = first_column(columns, spec.get("date_columns", ()))
                if not date_column:
                    result.update({"status": "missing_date_column", "document_column": document_column})
                else:
                    result.update(
                        {
                            "status": "ok_date_selected",
                            "date_column": date_column,
                            "document_column": document_column,
                        }
                    )
                    result.update(base_summary(cursor, table, date_column, document_column, start, end))
            report["tables"].append(result)

        for spec in MASTER_SPECS:
            table = spec["table"]
            columns = metadata[table]
            result = {"table": table}
            if not columns:
                result["status"] = "missing_table"
            else:
                key_column = first_column(columns, spec.get("key_columns", ()))
                result.update({"status": "ok", "key_column": key_column})
                result.update(master_summary(cursor, table, key_column))
            report["masters"].append(result)

        report["stock_uom"] = product_uom_summary(cursor, metadata["STOK"])
        if include_used_sku_uom:
            report["august_sales_uom"] = august_sales_uom_summary(cursor, metadata, start, end)
        else:
            report["august_sales_uom"] = {"status": "not_run"}
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        action="append",
        choices=tuple(SOURCES),
        required=True,
        help="Source to audit. May be supplied more than once; each is kept separate.",
    )
    parser.add_argument("--start", default="2026-08-01 00:00:00")
    parser.add_argument("--end-exclusive", default="2026-08-28 00:00:00")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--include-used-sku-uom",
        action="store_true",
        help="Run the heavier August transaction-to-SKU UOM audit. Use only during a low-traffic window.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        start = datetime.fromisoformat(args.start)
        end = datetime.fromisoformat(args.end_exclusive)
    except ValueError as exc:
        raise SystemExit(f"Format tanggal tidak valid: {exc}") from exc
    if start >= end:
        raise SystemExit("--end-exclusive harus lebih besar daripada --start.")

    generated_at = datetime.now(timezone.utc).isoformat()
    reports = []
    failures = []
    for source_name in dict.fromkeys(args.source):
        try:
            reports.append(
                audit_source(
                    source_name,
                    args.start,
                    args.end_exclusive,
                    args.include_used_sku_uom,
                )
            )
        except Exception as exc:  # Print source-specific errors but continue the other source.
            failures.append({"source": source_name, "error": str(exc)})

    output = {
        "generated_at": generated_at,
        "read_only": True,
        "reports": reports,
        "failures": failures,
    }
    rendered = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    print(rendered, end="")
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for report in reports:
            source_system = report["source"]["source_system"]
            (args.output_dir / f"audit_{source_system}_aug2026.json").write_text(
                json.dumps(
                    {
                        "generated_at": generated_at,
                        "read_only": True,
                        "report": report,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
