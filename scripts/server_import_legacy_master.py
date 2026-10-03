#!/usr/bin/env python3
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

TABLES = [
    "BarangBrand",
    "BarangClass",
    "BarangGroup",
    "BarangLokasi",
    "BarangMerk",
    "BarangSatuan",
    "BarangSubBrand",
    "Customer",
    "CustomerArea",
    "CustomerGroup",
    "CustomerJenis",
    "CustomerKategori",
    "CustomerMarketSegment",
    "CustomerPasar",
    "Kendaraan",
    "Plafon",
    "Principle",
    "STOK",
    "Sales",
    "SalesJenis",
    "TargetPrinciple",
    "WMSKartuStok",
    "WMSRak",
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
        timeout=60,
        tds_version="7.0",
        charset="UTF-8",
    )


def pg_connect():
    return pg8000.connect(**PG)


def pg_native_connect():
    return PgNativeConnection(**PG)


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


def load_metadata():
    per_source = {}
    all_columns = defaultdict(list)
    for source in SOURCES:
        for table in TABLES:
            raw_columns = get_columns(source, table)
            clean_columns = unique_clean_columns(raw_columns)
            per_source[(source["name"], table)] = list(zip(raw_columns, clean_columns))
            for column in clean_columns:
                if column not in all_columns[table]:
                    all_columns[table].append(column)
    return per_source, all_columns


def create_schema(schema, all_columns, replace=True):
    conn = pg_connect()
    try:
        cur = conn.cursor()
        if replace:
            cur.execute(f"DROP SCHEMA IF EXISTS {quote_ident(schema)} CASCADE")
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {quote_ident(schema)}")
        for table in TABLES:
            table_name = clean_name(table)
            column_defs = [
                "staging_id BIGSERIAL PRIMARY KEY",
                "source_system TEXT NOT NULL",
                "source_priority INTEGER NOT NULL",
                "legacy_table TEXT NOT NULL",
                "imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
            ]
            column_defs.extend(f"{quote_ident(column)} TEXT" for column in all_columns[table])
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


def import_table(schema, source, table, source_columns, target_columns):
    if not source_columns:
        return 0, "missing"

    raw_columns = [raw for raw, _ in source_columns]
    clean_columns = [clean for _, clean in source_columns]
    raw_select = ", ".join(f"[{column.replace(']', ']]')}]" for column in raw_columns)
    table_select = f"[dbo].[{table.replace(']', ']]')}]"
    source_col_index = {column: index for index, column in enumerate(clean_columns)}

    copy_columns = ["source_system", "source_priority", "legacy_table"] + target_columns
    quoted_columns = ", ".join(quote_ident(column) for column in copy_columns)
    table_name = clean_name(table)

    total = 0
    with tempfile.NamedTemporaryFile("w+", encoding="utf-8", newline="", delete=True) as temp:
        with mssql_connect(source) as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT {raw_select} FROM {table_select}")
            while True:
                rows = cur.fetchmany(2000)
                if not rows:
                    break
                for row in rows:
                    output = [source["name"], str(source["priority"]), table]
                    for column in target_columns:
                        idx = source_col_index.get(column)
                        output.append(row[idx] if idx is not None and idx < len(row) else None)
                    temp.write("\t".join(copy_escape(value) for value in output))
                    temp.write("\n")
                    total += 1
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
    return total, "imported"


def main():
    schema = sys.argv[1] if len(sys.argv) > 1 else "legacy_master_import_server"
    per_source, all_columns = load_metadata()
    create_schema(schema, all_columns, replace=True)

    print("source_system\ttable_name\trows\tstatus", flush=True)
    for source in SOURCES:
        for table in TABLES:
            count, status = import_table(
                schema,
                source,
                table,
                per_source[(source["name"], table)],
                all_columns[table],
            )
            print(f"{source['name']}\t{table}\t{count}\t{status}", flush=True)


if __name__ == "__main__":
    main()
