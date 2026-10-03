#!/usr/bin/env python3
import argparse
import datetime as dt
import re
import sys
import tempfile
from collections import defaultdict

import pymssql
import psycopg2


SOURCES = [
    {
        "name": "legacy_18",
        "schema": "legacy_18",
        "priority": 1,
        "host": "192.168.1.8",
        "user": "sa",
        "password": "Budimas6789",
        "database": "DIST",
    },
    {
        "name": "legacy_16",
        "schema": "legacy_16",
        "priority": 2,
        "host": "192.168.1.16",
        "user": "saomax",
        "password": "Budimas789#",
        "database": "DIST",
    },
]

PG = dict(host="127.0.0.1", port=5432, database="budimas_dev", user="postgres", password="")

DATE_TYPES = {
    "date",
    "datetime",
    "datetime2",
    "smalldatetime",
    "datetimeoffset",
}

DATE_NAME_HINTS = (
    "tanggal",
    "tgl",
    "date",
    "waktu",
    "time",
    "created",
    "create",
    "updated",
    "update",
    "input",
    "entry",
)


def clean_name(value):
    value = re.sub(r"[^0-9a-zA-Z_]+", "_", str(value or "").strip())
    value = re.sub(r"_+", "_", value).strip("_").lower()
    if not value:
        value = "col"
    if value[0].isdigit():
        value = f"c_{value}"
    return value


def qident(name):
    return '"' + name.replace('"', '""') + '"'


def mssql_connect(source):
    return pymssql.connect(
        server=source["host"],
        user=source["user"],
        password=source["password"],
        database=source["database"],
        port=1433,
        login_timeout=10,
        timeout=180,
        tds_version="7.0",
        charset="UTF-8",
    )


def pg_connect():
    return psycopg2.connect(
        host=PG["host"],
        port=PG["port"],
        dbname=PG["database"],
        user=PG["user"],
        password=PG["password"],
    )


def unique_clean_columns(raw_columns):
    used = defaultdict(int)
    result = []
    for raw in raw_columns:
        base = clean_name(raw)
        used[base] += 1
        result.append(base if used[base] == 1 else f"{base}_{used[base]}")
    return result


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


def list_tables(source):
    sql = """
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_NAME
    """
    with mssql_connect(source) as conn:
        cur = conn.cursor()
        cur.execute(sql)
        return [row[0] for row in cur.fetchall()]


def get_columns(source, table):
    sql = """
        SELECT COLUMN_NAME, DATA_TYPE, ORDINAL_POSITION
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
    """
    with mssql_connect(source) as conn:
        cur = conn.cursor()
        cur.execute(sql, (table,))
        return [{"name": row[0], "type": str(row[1]).lower(), "ordinal": row[2]} for row in cur.fetchall()]


def pick_date_column(columns):
    typed = [col for col in columns if col["type"] in DATE_TYPES]
    if not typed:
        return None
    hinted = [
        col for col in typed
        if any(hint in col["name"].lower() for hint in DATE_NAME_HINTS)
    ]
    if hinted:
        return hinted[0]["name"]
    return typed[0]["name"]


def row_count(source, table):
    with mssql_connect(source) as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(1) FROM [dbo].[{table.replace(']', ']]')}]")
        return int(cur.fetchone()[0] or 0)


def ensure_table(schema, table_name, clean_columns, replace):
    with pg_connect() as conn:
        cur = conn.cursor()
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {qident(schema)}")
        if replace:
            cur.execute(f"DROP TABLE IF EXISTS {qident(schema)}.{qident(table_name)}")
        col_defs = [
            "staging_id BIGSERIAL PRIMARY KEY",
            "source_system TEXT NOT NULL",
            "legacy_table TEXT NOT NULL",
            "legacy_date_column TEXT",
            "sync_window_start TEXT",
            "sync_window_end TEXT",
            "imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
        ]
        col_defs.extend(f"{qident(col)} TEXT" for col in clean_columns)
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS {qident(schema)}.{qident(table_name)} "
            f"({', '.join(col_defs)})"
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS {qident('idx_' + table_name[:40] + '_legacy_table')} "
            f"ON {qident(schema)}.{qident(table_name)} (legacy_table)"
        )
        conn.commit()


def truncate_table(schema, table_name):
    with pg_connect() as conn:
        cur = conn.cursor()
        cur.execute(f"TRUNCATE TABLE {qident(schema)}.{qident(table_name)}")
        conn.commit()


def copy_rows(schema, table_name, copy_columns, rows):
    if not rows:
        return
    quoted_columns = ", ".join(qident(col) for col in copy_columns)
    with tempfile.NamedTemporaryFile("w+b", delete=True) as temp:
        for output in rows:
            temp.write(("\t".join(copy_escape(value) for value in output) + "\n").encode("utf-8"))
        temp.flush()
        temp.seek(0)
        conn = pg_connect()
        try:
            cur = conn.cursor()
            cur.copy_expert(
                f"COPY {qident(schema)}.{qident(table_name)} ({quoted_columns}) "
                "FROM STDIN WITH (FORMAT text, DELIMITER E'\\t', NULL '\\\\N')",
                temp,
            )
            conn.commit()
        finally:
            conn.close()


def import_table(source, table, days, chunk_size, max_full_rows, replace):
    columns = get_columns(source, table)
    if not columns:
        return {"table": table, "rows": 0, "status": "no_columns", "date_column": None}

    raw_columns = [col["name"] for col in columns]
    clean_columns = unique_clean_columns(raw_columns)
    clean_by_raw = dict(zip(raw_columns, clean_columns))
    date_column = pick_date_column(columns)
    table_name = clean_name(table)
    schema = source["schema"]

    count_total = row_count(source, table)
    if not date_column and count_total > max_full_rows:
        ensure_table(schema, table_name, clean_columns, replace=replace)
        return {
            "table": table,
            "rows": 0,
            "status": f"skipped_no_date_large:{count_total}",
            "date_column": None,
        }

    ensure_table(schema, table_name, clean_columns, replace=replace)
    if replace:
        truncate_table(schema, table_name)

    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=days)
    where_sql = ""
    params = ()
    if date_column:
        safe_date = date_column.replace("]", "]]")
        where_sql = f" WHERE [{safe_date}] >= %s AND [{safe_date}] < DATEADD(day, 1, %s)"
        params = (start_date.isoformat(), end_date.isoformat())

    raw_select = ", ".join(f"[{col.replace(']', ']]')}]" for col in raw_columns)
    source_table = f"[dbo].[{table.replace(']', ']]')}]"
    copy_columns = [
        "source_system",
        "legacy_table",
        "legacy_date_column",
        "sync_window_start",
        "sync_window_end",
    ] + clean_columns
    inserted = 0

    with mssql_connect(source) as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT {raw_select} FROM {source_table}{where_sql}", params)
        while True:
            rows = cur.fetchmany(chunk_size)
            if not rows:
                break
            output_rows = []
            for row in rows:
                output = [
                    source["name"],
                    table,
                    date_column,
                    start_date.isoformat() if date_column else None,
                    end_date.isoformat() if date_column else None,
                ]
                output.extend(row)
                output_rows.append(output)
            copy_rows(schema, table_name, copy_columns, output_rows)
            inserted += len(output_rows)
            print(f"{source['name']}\t{table}\tchunk_total={inserted}", flush=True)

    status = "recent_by_date" if date_column else "full_no_date"
    return {"table": table, "rows": inserted, "status": status, "date_column": date_column}


def write_audit_start(days, max_full_rows):
    with pg_connect() as conn:
        cur = conn.cursor()
        cur.execute("CREATE SCHEMA IF NOT EXISTS legacy_audit")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS legacy_audit.full_staging_runs (
                id BIGSERIAL PRIMARY KEY,
                started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                finished_at TIMESTAMPTZ,
                days INTEGER NOT NULL,
                max_full_rows INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                notes TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS legacy_audit.full_staging_table_results (
                id BIGSERIAL PRIMARY KEY,
                run_id BIGINT NOT NULL,
                source_system TEXT NOT NULL,
                schema_name TEXT NOT NULL,
                table_name TEXT NOT NULL,
                date_column TEXT,
                rows_imported BIGINT NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute(
            "INSERT INTO legacy_audit.full_staging_runs (days, max_full_rows) VALUES (%s, %s) RETURNING id",
            (days, max_full_rows),
        )
        run_id = cur.fetchone()[0]
        conn.commit()
        return run_id


def write_result(run_id, source, result):
    with pg_connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO legacy_audit.full_staging_table_results
            (run_id, source_system, schema_name, table_name, date_column, rows_imported, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                source["name"],
                source["schema"],
                result["table"],
                result["date_column"],
                result["rows"],
                result["status"],
            ),
        )
        conn.commit()


def finish_run(run_id, status, notes=None):
    with pg_connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE legacy_audit.full_staging_runs SET finished_at=NOW(), status=%s, notes=%s WHERE id=%s",
            (status, notes, run_id),
        )
        conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--chunk-size", type=int, default=5000)
    parser.add_argument("--max-full-rows", type=int, default=50000)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--tables", help="Comma-separated table whitelist.")
    args = parser.parse_args()

    run_id = write_audit_start(args.days, args.max_full_rows)
    try:
        for source in SOURCES:
            tables = [item.strip() for item in args.tables.split(",")] if args.tables else list_tables(source)
            print(f"source={source['name']} tables={len(tables)}", flush=True)
            for table in tables:
                try:
                    result = import_table(
                        source,
                        table,
                        args.days,
                        args.chunk_size,
                        args.max_full_rows,
                        args.replace,
                    )
                except Exception as exc:
                    result = {"table": table, "rows": 0, "status": f"error:{exc}", "date_column": None}
                    print(f"{source['name']}\t{table}\tERROR\t{exc}", flush=True)
                write_result(run_id, source, result)
                print(
                    f"{source['name']}\t{table}\t{result['rows']}\t{result['status']}\tdate={result['date_column']}",
                    flush=True,
                )
        finish_run(run_id, "done")
    except Exception as exc:
        finish_run(run_id, "error", str(exc))
        raise


if __name__ == "__main__":
    sys.exit(main())
