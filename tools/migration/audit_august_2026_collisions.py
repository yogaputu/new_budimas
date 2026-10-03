#!/usr/bin/env python3
"""Read-only collision audit between BDM Solo and TMP Solo legacy sources.

It intentionally reports counts only; legacy codes and document numbers are not
printed.  The result determines whether a source-aware mapping is mandatory
before a batch can be staged or merged into PostgreSQL.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from audit_august_2026_sources import connect, first_column, get_columns, quote_ident, source_config, table_name_sql


SPECS = (
    {
        "name": "sales_standard_nota",
        "table": "HJualSM",
        "key_columns": ("Nota", "NoNota", "No_Faktur"),
        "date_columns": ("Tanggal", "Tgl"),
    },
    {
        "name": "sales_mobile_nota",
        "table": "HJualSMAndroid",
        "key_columns": ("Nota", "NoNota", "No_Faktur"),
        "date_columns": ("Tanggal", "Tgl"),
    },
    {
        "name": "return_standard_nota",
        "table": "HReturSM",
        "key_columns": ("Nota", "NoNota", "No_Retur"),
        "date_columns": ("Tanggal", "Tgl"),
    },
    {
        "name": "return_mobile_nota",
        "table": "HReturSMAndroid",
        "key_columns": ("Nota", "NoNota", "No_Retur"),
        "date_columns": ("Tanggal", "Tgl"),
    },
    {
        "name": "payment_receipt",
        "table": "HBayarSM",
        "key_columns": ("NoKwitansi", "NoBukti", "No_Bukti"),
        "date_columns": ("Tanggal", "Tgl"),
    },
    {"name": "customer_code", "table": "Customer", "key_columns": ("Kode",)},
    {"name": "principal_code", "table": "Principle", "key_columns": ("Kode",)},
    {"name": "sales_code", "table": "Sales", "key_columns": ("Kode",)},
    {"name": "product_sku", "table": "STOK", "key_columns": ("Kode",)},
)


def fetch_keys(source_name: str, spec: dict, start: str, end: str):
    source = source_config(source_name)
    with connect(source) as connection:
        cursor = connection.cursor()
        columns = get_columns(cursor, spec["table"])
        key_column = first_column(columns, spec["key_columns"])
        date_column = first_column(columns, spec.get("date_columns", ()))
        if not key_column:
            return None, {"status": "missing_key_column"}
        key_expr = f"NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(4000), {quote_ident(key_column)}))), '')"
        params = ()
        where = ""
        if spec.get("date_columns"):
            if not date_column:
                return None, {"status": "missing_date_column", "key_column": key_column}
            where = f" WHERE {quote_ident(date_column)} >= %s AND {quote_ident(date_column)} < %s"
            params = (start, end)
        cursor.execute(
            f"SELECT DISTINCT {key_expr} FROM {table_name_sql(spec['table'])}{where}",
            params,
        )
        values = {str(row[0]).strip() for row in cursor.fetchall() if row[0] is not None and str(row[0]).strip()}
        return values, {
            "status": "ok",
            "key_column": key_column,
            "date_column": date_column,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2026-08-01 00:00:00")
    parser.add_argument("--end-exclusive", default="2026-08-28 00:00:00")
    parser.add_argument("--output", type=Path)
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

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "window": {"start_inclusive": args.start, "end_exclusive": args.end_exclusive},
        "sources": {
            "bdm-solo": source_config("bdm-solo")["source_system"],
            "tmp-solo": source_config("tmp-solo")["source_system"],
        },
        "collisions": [],
    }
    failed = False
    for spec in SPECS:
        item = {"name": spec["name"], "table": spec["table"]}
        try:
            bdm_values, bdm_meta = fetch_keys("bdm-solo", spec, args.start, args.end_exclusive)
            tmp_values, tmp_meta = fetch_keys("tmp-solo", spec, args.start, args.end_exclusive)
            item["bdm"] = {"count": len(bdm_values or ()), **bdm_meta}
            item["tmp"] = {"count": len(tmp_values or ()), **tmp_meta}
            if bdm_values is None or tmp_values is None:
                item["status"] = "incomplete"
                failed = True
            else:
                item["status"] = "ok"
                item["collision_count"] = len(bdm_values.intersection(tmp_values))
        except Exception as exc:
            item.update({"status": "error", "error": str(exc)})
            failed = True
        report["collisions"].append(item)

    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
