#!/usr/bin/env python3
import argparse
import csv
import re
import tempfile
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse, unquote

from pg8000.native import Connection
from sqlalchemy import create_engine, text


csv.field_size_limit(sys.maxsize)

SOURCE_DIRS = [
    ("sqlserver_192_168_1_8", 1, Path("/Users/macairm2/Downloads/budimas_sqlserver_master_export_20260716")),
    ("sqlserver_192_168_1_16", 2, Path("/Users/macairm2/Downloads/budimas_sqlserver_192_168_1_16_master_export_20260716")),
]


def clean_name(value):
    value = re.sub(r"[^0-9a-zA-Z_]+", "_", str(value or "").strip())
    value = re.sub(r"_+", "_", value).strip("_").lower()
    if not value:
        value = "col"
    if value[0].isdigit():
        value = f"c_{value}"
    return value


def read_manifest(export_dir):
    manifest = export_dir / "_manifest.tsv"
    rows = {}
    if not manifest.exists():
        return rows
    with manifest.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            status = row.get("status") or "exported"
            if status == "exported" and row.get("file"):
                rows[row["table_name"]] = row["file"]
    return rows


def read_columns(export_dir):
    columns_file = export_dir / "_columns.tsv"
    columns = defaultdict(list)
    if not columns_file.exists():
        return columns
    with columns_file.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        for row in reader:
            if len(row) < 3:
                continue
            table, _, column = row[:3]
            name = clean_name(column)
            if name not in columns[table]:
                columns[table].append(name)
    return columns


def load_source_metadata():
    manifests = {}
    columns_by_source = {}
    all_tables = set()
    all_columns = defaultdict(list)
    original_columns = defaultdict(dict)

    for source, priority, export_dir in SOURCE_DIRS:
        manifest = read_manifest(export_dir)
        columns = read_columns(export_dir)
        manifests[source] = (priority, export_dir, manifest)
        columns_by_source[source] = columns
        all_tables.update(manifest.keys())
        for table, names in columns.items():
            for name in names:
                if name not in all_columns[table]:
                    all_columns[table].append(name)

    for source, columns in columns_by_source.items():
        for table, names in columns.items():
            original_columns[source, table] = names

    return manifests, sorted(all_tables), all_columns, original_columns


def create_schema(conn, schema, tables, all_columns, replace):
    if replace:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))

    for table in tables:
        table_name = clean_name(table)
        column_defs = ",\n".join(f'    "{column}" TEXT' for column in all_columns[table])
        if column_defs:
            column_defs = ",\n" + column_defs
        conn.execute(text(f'''
            CREATE TABLE IF NOT EXISTS "{schema}"."{table_name}" (
                staging_id BIGSERIAL PRIMARY KEY,
                source_system TEXT NOT NULL,
                source_priority INTEGER NOT NULL,
                legacy_table TEXT NOT NULL,
                imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                {column_defs}
            )
        '''))
        conn.execute(text(f'CREATE INDEX IF NOT EXISTS "idx_{table_name}_source" ON "{schema}"."{table_name}" (source_system, source_priority)'))


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


def native_connection_from_url(db_url):
    parsed = urlparse(db_url)
    return Connection(
        user=unquote(parsed.username or "postgres"),
        password=unquote(parsed.password or ""),
        host=parsed.hostname or "127.0.0.1",
        port=parsed.port or 5432,
        database=(parsed.path or "/budimas_dev").lstrip("/"),
    )


def copy_rows(db_url, schema, table, source, priority, export_dir, file_name, source_columns, target_columns):
    path = export_dir / file_name
    if not path.exists():
        return 0

    table_name = clean_name(table)
    copy_columns = ["source_system", "source_priority", "legacy_table"] + target_columns
    quoted_columns = ", ".join(f'"{column}"' for column in copy_columns)

    total = 0
    with tempfile.NamedTemporaryFile("w+", encoding="utf-8", newline="", delete=True) as temp:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.reader(handle, delimiter="\t")
            for row in reader:
                values = {}
                for index, column in enumerate(source_columns):
                    raw = row[index] if index < len(row) else None
                    values[column] = raw.strip() if isinstance(raw, str) else raw
                output = [source, str(priority), table]
                output.extend(values.get(column) for column in target_columns)
                temp.write("\t".join(copy_escape(value) for value in output))
                temp.write("\n")
                total += 1
        temp.flush()
        temp.seek(0)
        native = native_connection_from_url(db_url)
        try:
            native.run(
                f'COPY "{schema}"."{table_name}" ({quoted_columns}) FROM STDIN WITH (FORMAT text, DELIMITER E\'\\t\', NULL \'\\\\N\')',
                stream=temp,
            )
            native.run("COMMIT")
        finally:
            native.close()
    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-url", default="postgresql+pg8000://postgres:@127.0.0.1:15432/budimas_dev")
    parser.add_argument("--schema", default="legacy_master_import")
    parser.add_argument("--append", action="store_true")
    args = parser.parse_args()

    manifests, tables, all_columns, original_columns = load_source_metadata()
    engine = create_engine(args.db_url)

    with engine.begin() as conn:
        create_schema(conn, args.schema, tables, all_columns, replace=not args.append)

    summary = []
    for source, (priority, export_dir, manifest) in manifests.items():
        for table in tables:
            file_name = manifest.get(table)
            if not file_name:
                summary.append((source, table, 0, "missing"))
                continue
            count = copy_rows(
                args.db_url,
                args.schema,
                table,
                source,
                priority,
                export_dir,
                file_name,
                original_columns.get((source, table), []),
                all_columns[table],
            )
            summary.append((source, table, count, "imported"))

    print("source_system\ttable_name\trows\tstatus")
    for row in summary:
        print("\t".join(str(item) for item in row))


if __name__ == "__main__":
    main()
