#!/usr/bin/env python3
import argparse
import csv
import re
import sys
import tempfile
from collections import defaultdict

import pg8000
from pg8000.native import Connection as PgNativeConnection
import pymssql


csv.field_size_limit(sys.maxsize)

SOURCES = [
    {
        "name": "sqlserver_192_168_1_8",
        "priority": 1,
        "host": "192.168.1.8",
        "user": "sa",
        "password": "Budimas6789",
        "database": "DIST",
    },
    {
        "name": "sqlserver_192_168_1_16",
        "priority": 2,
        "host": "192.168.1.16",
        "user": "saomax",
        "password": "Budimas789#",
        "database": "DIST",
    },
]

PHASE1_TABLES = [
    "HJualSM",
    "DJualSM",
    "HBayarSM",
    "DBayarSM",
    "HReturSM",
    "DReturSM",
    "HJualKanvas",
    "DJualKanvas",
    "HBayarKV",
    "DBayarKV",
    "Invoice",
    "Pembayaran",
    "KunjunganSales",
]

HEAVY_TABLES = [
    "StokOpnameAndroid",
]

PG = {
    "host": "127.0.0.1",
    "port": 5432,
    "database": "budimas_dev",
    "user": "postgres",
    "password": "",
}


def clean_name(value):
    value = re.sub(r"[^0-9a-zA-Z_]+", "_", str(value or "").strip())
    value = re.sub(r"_+", "_", value).strip("_").lower()
    if not value:
        value = "col"
    if value[0].isdigit():
        value = f"c_{value}"
    return value


def unique_clean_columns(raw_columns):
    used = defaultdict(int)
    result = []
    for raw in raw_columns:
        base = clean_name(raw)
        used[base] += 1
        result.append(base if used[base] == 1 else f"{base}_{used[base]}")
    return result


def quote_ident(name):
    return '"' + name.replace('"', '""') + '"'


def mssql_connect(source):
    return pymssql.connect(
        server=source["host"],
        user=source["user"],
        password=source["password"],
        database=source["database"],
        port=1433,
        login_timeout=10,
        timeout=120,
        tds_version="7.0",
        charset="UTF-8",
    )


def pg_connect():
    return pg8000.connect(**PG)


def pg_native_connect():
    return PgNativeConnection(**PG)


def table_exists(source, table):
    sql = """
        SELECT 1
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = %s
    """
    with mssql_connect(source) as conn:
        cur = conn.cursor()
        cur.execute(sql, (table,))
        return bool(cur.fetchone())


def get_columns(source, table):
    sql = """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
    """
    with mssql_connect(source) as conn:
        cur = conn.cursor()
        cur.execute(sql, (table,))
        return [row[0] for row in cur.fetchall()]


def load_metadata(tables):
    per_source = {}
    all_columns = defaultdict(list)
    for source in SOURCES:
        for table in tables:
            if not table_exists(source, table):
                per_source[(source["name"], table)] = []
                continue
            raw_columns = get_columns(source, table)
            clean_columns = unique_clean_columns(raw_columns)
            per_source[(source["name"], table)] = list(zip(raw_columns, clean_columns))
            for column in clean_columns:
                if column not in all_columns[table]:
                    all_columns[table].append(column)
    return per_source, all_columns


def create_schema(schema, tables, all_columns, replace):
    conn = pg_connect()
    try:
        cur = conn.cursor()
        if replace:
            cur.execute(f"DROP SCHEMA IF EXISTS {quote_ident(schema)} CASCADE")
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {quote_ident(schema)}")
        for table in tables:
            table_name = clean_name(table)
            if not all_columns[table]:
                continue
            column_defs = [
                "staging_id BIGSERIAL PRIMARY KEY",
                "source_system TEXT NOT NULL",
                "source_priority INTEGER NOT NULL",
                "legacy_table TEXT NOT NULL",
                "imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
            ]
            column_defs.extend(f"{quote_ident(column)} TEXT" for column in all_columns[table])
            cur.execute(
                f"DROP TABLE IF EXISTS {quote_ident(schema)}.{quote_ident(table_name)}"
            )
            cur.execute(
                f"CREATE TABLE {quote_ident(schema)}.{quote_ident(table_name)} "
                f"({', '.join(column_defs)})"
            )
            cur.execute(
                f"CREATE INDEX {quote_ident('idx_' + table_name + '_source')} "
                f"ON {quote_ident(schema)}.{quote_ident(table_name)} "
                f"(source_system, source_priority)"
            )
        conn.commit()
    finally:
        conn.close()


def copy_escape(value):
    if value is None or value == "":
        return r"\N"
    return (
        str(value)
        .replace("\x00", "")
        .replace("\\", "\\\\")
        .replace("\t", "\\t")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def copy_rows(schema, table_name, copy_columns, rows):
    if not rows:
        return
    quoted_columns = ", ".join(quote_ident(column) for column in copy_columns)
    with tempfile.NamedTemporaryFile("w+b", delete=True) as temp:
        for output in rows:
            line = "\t".join(copy_escape(value) for value in output) + "\n"
            temp.write(line.encode("utf-8"))
        temp.flush()
        temp.seek(0)
        native = pg_native_connect()
        try:
            native.run(
                f"COPY {quote_ident(schema)}.{quote_ident(table_name)} ({quoted_columns}) "
                "FROM STDIN WITH (FORMAT text, DELIMITER E'\\t', NULL '\\\\N')",
                stream=temp,
            )
            native.run("COMMIT")
        finally:
            native.close()


def import_table(
    schema,
    source,
    table,
    source_columns,
    target_columns,
    chunk_size,
    date_filter=None,
):
    if not source_columns:
        return 0, "missing"

    raw_columns = [raw for raw, _ in source_columns]
    clean_columns = [clean for _, clean in source_columns]
    raw_select = ", ".join(f"[{column.replace(']', ']]')}]" for column in raw_columns)
    table_select = f"[dbo].[{table.replace(']', ']]')}]"
    source_col_index = {column: index for index, column in enumerate(clean_columns)}

    copy_columns = ["source_system", "source_priority", "legacy_table"] + target_columns
    table_name = clean_name(table)

    total = 0
    where_sql = ""
    params = ()
    if date_filter:
        date_column, date_start, date_end = date_filter
        available_columns = {column.lower(): column for column in raw_columns}
        matched_column = available_columns.get(date_column.lower())
        if not matched_column:
            return 0, f"missing_date_column:{date_column}"
        where_sql = f" WHERE [{matched_column.replace(']', ']]')}] >= %s AND [{matched_column.replace(']', ']]')}] <= %s"
        params = (date_start, date_end)

    with mssql_connect(source) as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT {raw_select} FROM {table_select}{where_sql}", params)
        while True:
            rows = cur.fetchmany(chunk_size)
            if not rows:
                break
            output_rows = []
            for row in rows:
                output = [source["name"], str(source["priority"]), table]
                for column in target_columns:
                    idx = source_col_index.get(column)
                    output.append(row[idx] if idx is not None and idx < len(row) else None)
                output_rows.append(output)
            copy_rows(schema, table_name, copy_columns, output_rows)
            total += len(output_rows)
            print(f"{source['name']}\t{table}\tchunk_total={total}", flush=True)
    return total, "imported"


def parse_tables(args):
    if args.tables:
        return [item.strip() for item in args.tables.split(",") if item.strip()]
    tables = list(PHASE1_TABLES)
    if args.include_heavy:
        tables.extend(HEAVY_TABLES)
    return tables


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", default="legacy_transaction_import_server")
    parser.add_argument("--tables", help="Comma separated legacy table names.")
    parser.add_argument("--include-heavy", action="store_true")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--chunk-size", type=int, default=10000)
    parser.add_argument("--date-column", help="Optional SQL Server date column filter.")
    parser.add_argument("--date-start", help="Inclusive start date, e.g. 2026-06-01.")
    parser.add_argument("--date-end", help="Inclusive end date, e.g. 2026-07-18.")
    args = parser.parse_args()

    tables = parse_tables(args)
    per_source, all_columns = load_metadata(tables)
    create_schema(args.schema, tables, all_columns, replace=args.replace)

    print("source_system\ttable_name\trows\tstatus", flush=True)
    date_filter = None
    if args.date_column or args.date_start or args.date_end:
        if not (args.date_column and args.date_start and args.date_end):
            raise SystemExit("--date-column, --date-start, and --date-end must be used together")
        date_filter = (args.date_column, args.date_start, args.date_end)

    for source in SOURCES:
        for table in tables:
            count, status = import_table(
                args.schema,
                source,
                table,
                per_source[(source["name"], table)],
                all_columns[table],
                args.chunk_size,
                date_filter=date_filter,
            )
            print(f"{source['name']}\t{table}\t{count}\t{status}", flush=True)


if __name__ == "__main__":
    main()
