#!/usr/bin/env python3
import argparse
import datetime as dt
import os
import subprocess
import sys

import pg8000


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMPORT_SCRIPT = os.path.join(BASE_DIR, "server_import_legacy_transactions.py")
MERGE_SCRIPTS = [
    "merge_legacy_sales_orders.py",
    "merge_legacy_sales_order_details.py",
    "merge_legacy_payments_dbayarsm.py",
    "merge_legacy_stockopname_recent.py",
    "merge_legacy_kunjungan_sales.py",
    "merge_legacy_retur_review_recent.py",
]

PG = dict(host='127.0.0.1', port=5432, database='budimas_dev', user='postgres', password='')
MAIN_SCHEMA = "legacy_transaction_import_server"
DELTA_SCHEMA = "legacy_transaction_import_delta"

DATE_GROUPS = [
    {
        "date_column": "tanggal",
        "tables": [
            "HJualSM",
            "DJualSM",
            "HBayarSM",
            "DBayarSM",
            "Pembayaran",
            "HReturSM",
            "DReturSM",
            "HJualKanvas",
            "DJualKanvas",
            "HBayarKV",
            "DBayarKV",
            "Invoice",
            "KunjunganSales",
        ],
    },
    {
        "date_column": "TanggalInput",
        "tables": ["StokOpnameAndroid"],
    },
]


def qident(name):
    return '"' + name.replace('"', '""') + '"'


def clean_name(value):
    import re

    value = re.sub(r"[^0-9a-zA-Z_]+", "_", str(value or "").strip())
    value = re.sub(r"_+", "_", value).strip("_").lower()
    if not value:
        value = "col"
    if value[0].isdigit():
        value = f"c_{value}"
    return value


def run_command(cmd):
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def refresh_main_staging(date_column, tables, start_date, end_date):
    conn = pg8000.connect(**PG)
    try:
        cur = conn.cursor()
        for table in tables:
            table_name = clean_name(table)
            cur.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema=%s AND table_name=%s
                ORDER BY ordinal_position
            """, (DELTA_SCHEMA, table_name))
            delta_columns = [row[0] for row in cur.fetchall()]
            if not delta_columns:
                print(f"skip_refresh={table_name}:no_delta_table", flush=True)
                continue

            cur.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema=%s AND table_name=%s
                ORDER BY ordinal_position
            """, (MAIN_SCHEMA, table_name))
            main_columns = [row[0] for row in cur.fetchall()]
            insert_columns = [
                col for col in delta_columns
                if col != "staging_id" and col in main_columns
            ]
            if date_column.lower() not in {col.lower() for col in insert_columns}:
                print(f"skip_refresh={table_name}:missing_date_column:{date_column}", flush=True)
                continue

            date_col = next(col for col in insert_columns if col.lower() == date_column.lower())
            cols_sql = ", ".join(qident(col) for col in insert_columns)
            cur.execute(
                f"""
                DELETE FROM {qident(MAIN_SCHEMA)}.{qident(table_name)}
                WHERE {qident(date_col)} >= %s AND {qident(date_col)} <= %s
                """,
                (start_date, end_date),
            )
            deleted = cur.rowcount
            cur.execute(
                f"""
                INSERT INTO {qident(MAIN_SCHEMA)}.{qident(table_name)} ({cols_sql})
                SELECT {cols_sql}
                FROM {qident(DELTA_SCHEMA)}.{qident(table_name)}
                """,
            )
            inserted = cur.rowcount
            print(f"refresh_main_staging={table_name} deleted={deleted} inserted={inserted}", flush=True)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--chunk-size", type=int, default=10000)
    parser.add_argument("--skip-merge", action="store_true")
    args = parser.parse_args()

    today = dt.date.today()
    start_date = args.start_date or (today - dt.timedelta(days=args.days)).isoformat()
    end_date = args.end_date or today.isoformat()
    end_bound = f"{end_date} 23:59:59.997"
    print(f"sync_window={start_date}..{end_bound}", flush=True)

    for group in DATE_GROUPS:
        tables = group["tables"]
        date_column = group["date_column"]
        run_command([
            sys.executable,
            IMPORT_SCRIPT,
            "--schema",
            DELTA_SCHEMA,
            "--tables",
            ",".join(tables),
            "--replace",
            "--chunk-size",
            str(args.chunk_size),
            "--date-column",
            date_column,
            "--date-start",
            start_date,
            "--date-end",
            end_bound,
        ])
        refresh_main_staging(date_column, tables, start_date, end_bound)

    if args.skip_merge:
        print("skip_merge=true", flush=True)
        return

    for script in MERGE_SCRIPTS:
        run_command([sys.executable, os.path.join(BASE_DIR, script), "--apply"])


if __name__ == "__main__":
    main()
