#!/usr/bin/env python3
"""Load explicitly reviewed BDM/TMP master mappings into the control registry.

The input is a ``mapping_review_queue.csv`` created by
``export_august_2026_mapping_exceptions.py``.  Rows are ignored until a
reviewer supplies a supported ``decision`` and ``approved_target_id``.  The
default is dry-run; ``--apply`` is required for the control-schema write.

This tool never writes application ``public`` master or transaction tables.
The registry triggers enforce company/branch/principal/product/UOM scope, so a
reviewed mapping cannot cross BDM/TMP by accident.
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
REGISTRY_SCHEMA = "migration_bdm_tmp_202608"
REQUIRED_FIELDS = {
    "source_system",
    "entity_type",
    "source_key_1",
    "source_key_2",
    "review_status",
    "decision",
    "approved_target_id",
    "reviewer_note",
}
DECISIONS = {
    "approve_exact": "exact_reviewed",
    "approve_manual": "manual",
    "approve_created": "created",
    "approve_cross_branch": "cross_branch_approved",
}
ENTITY_TABLE = {
    "principal": "principal_map",
    "customer": "customer_map",
    "sales": "sales_map",
    "product": "product_map",
}


def qident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def norm(value: str) -> str:
    return value.strip().lower()


def pg_connect(database: str, user: str, host: str | None, port: int | None):
    try:
        import psycopg2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("Modul psycopg2 diperlukan untuk mapping PostgreSQL.") from exc
    kwargs: dict[str, Any] = {"dbname": database, "user": user}
    if host:
        kwargs["host"] = host
    if port:
        kwargs["port"] = port
    return psycopg2.connect(**kwargs)


def stage_metadata(cursor, schema: str) -> dict[str, Any]:
    cursor.execute(
        f"""
        SELECT source_system, target_company_id, target_branch_id
        FROM {qident(schema)}.__stage_run
        ORDER BY id DESC
        LIMIT 1
        """
    )
    row = cursor.fetchone()
    if not row:
        raise RuntimeError(f"Schema {schema} tidak memiliki metadata staging.")
    return {description.name: value for description, value in zip(cursor.description, row)}


def assert_registry(cursor, source_system: str) -> None:
    cursor.execute(
        f"SELECT 1 FROM {qident(REGISTRY_SCHEMA)}.source_context WHERE source_system = %s",
        (source_system,),
    )
    if not cursor.fetchone():
        raise RuntimeError(
            f"Source system {source_system!r} belum terdaftar di {REGISTRY_SCHEMA}.source_context. "
            "Jalankan migration registry terlebih dahulu."
        )


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise RuntimeError("CSV tidak memiliki header.")
        missing = sorted(REQUIRED_FIELDS - set(reader.fieldnames))
        if missing:
            raise RuntimeError(f"CSV tidak memiliki kolom wajib: {', '.join(missing)}")
        return [dict(row) for row in reader]


def source_exists(cursor, schema: str, entity: str, key1: str, key2: str) -> bool:
    if entity == "principal":
        query = f"SELECT 1 FROM {qident(schema)}.principle WHERE lower(btrim(kode)) = %s LIMIT 1"
        params = (key1,)
    elif entity == "customer":
        query = f"SELECT 1 FROM {qident(schema)}.customer WHERE lower(btrim(kode)) = %s LIMIT 1"
        params = (key1,)
    elif entity == "sales":
        query = (
            f"SELECT 1 FROM {qident(schema)}.sales "
            "WHERE lower(btrim(kode)) = %s AND lower(btrim(kodeprinciple)) = %s LIMIT 1"
        )
        params = (key1, key2)
    elif entity == "product":
        query = (
            f"SELECT 1 FROM {qident(schema)}.stok "
            "WHERE lower(btrim(kode)) = %s AND lower(btrim(principle)) = %s LIMIT 1"
        )
        params = (key1, key2)
    else:
        raise ValueError(f"Entity tidak didukung: {entity}")
    cursor.execute(query, params)
    return cursor.fetchone() is not None


def existing_mapping_target(cursor, entity: str, source_system: str, key1: str, key2: str) -> int | None:
    table = f"{qident(REGISTRY_SCHEMA)}.{qident(ENTITY_TABLE[entity])}"
    if entity in {"principal", "customer"}:
        source_column = "source_principal_code_norm" if entity == "principal" else "source_customer_code_norm"
        target_column = "id_principal" if entity == "principal" else "id_customer"
        cursor.execute(
            f"SELECT {qident(target_column)} FROM {table} WHERE source_system = %s AND {qident(source_column)} = %s",
            (source_system, key1),
        )
    elif entity == "sales":
        cursor.execute(
            f"""
            SELECT id_sales FROM {table}
            WHERE source_system = %s
              AND source_sales_code_norm = %s
              AND source_principal_code_norm = %s
            """,
            (source_system, key1, key2),
        )
    else:
        cursor.execute(
            f"""
            SELECT id_produk FROM {table}
            WHERE source_system = %s
              AND source_sku_norm = %s
              AND source_principal_code_norm = %s
            """,
            (source_system, key1, key2),
        )
    row = cursor.fetchone()
    return int(row[0]) if row else None


def insert_mapping(
    cursor,
    entity: str,
    source_system: str,
    key1: str,
    key2: str,
    target_id: int,
    method: str,
    approved_by: str,
    note: str,
) -> None:
    table = f"{qident(REGISTRY_SCHEMA)}.{qident(ENTITY_TABLE[entity])}"
    if entity == "principal":
        cursor.execute(
            f"""
            INSERT INTO {table} (
                source_system, source_principal_code, source_principal_code_norm,
                id_principal, mapping_method, approved_by, reviewer_note
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (source_system, key1, key1, target_id, method, approved_by, note or None),
        )
    elif entity == "customer":
        cursor.execute(
            f"""
            INSERT INTO {table} (
                source_system, source_customer_code, source_customer_code_norm,
                id_customer, mapping_method, approved_by, reviewer_note
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (source_system, key1, key1, target_id, method, approved_by, note or None),
        )
    elif entity == "sales":
        cursor.execute(
            f"""
            INSERT INTO {table} (
                source_system,
                source_principal_code, source_principal_code_norm,
                source_sales_code, source_sales_code_norm,
                id_sales, mapping_method, approved_by, reviewer_note
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (source_system, key2, key2, key1, key1, target_id, method, approved_by, note or None),
        )
    else:
        cursor.execute(
            f"""
            INSERT INTO {table} (
                source_system,
                source_principal_code, source_principal_code_norm,
                source_sku, source_sku_norm,
                id_produk, mapping_method, approved_by, reviewer_note
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (source_system, key2, key2, key1, key1, target_id, method, approved_by, note or None),
        )


def parse_approved_rows(rows: list[dict[str, str]], expected_source: str) -> tuple[list[dict[str, Any]], Counter[str]]:
    selected: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    for line_number, row in enumerate(rows, start=2):
        decision = norm(row.get("decision", ""))
        if not decision or decision == "skip":
            skipped["blank_or_skip"] += 1
            continue
        entity = norm(row.get("entity_type", ""))
        if entity not in ENTITY_TABLE:
            raise RuntimeError(f"Baris {line_number}: entity_type {entity!r} tidak didukung.")
        if decision not in DECISIONS:
            raise RuntimeError(
                f"Baris {line_number}: decision harus salah satu {', '.join(sorted(DECISIONS))}, skip, atau kosong."
            )
        if row.get("source_system", "") != expected_source:
            raise RuntimeError(
                f"Baris {line_number}: source_system {row.get('source_system')!r} tidak sama dengan staging {expected_source!r}."
            )
        key1 = norm(row.get("source_key_1", ""))
        key2 = norm(row.get("source_key_2", ""))
        if not key1 or (entity in {"sales", "product"} and not key2):
            raise RuntimeError(f"Baris {line_number}: source key tidak lengkap untuk {entity}.")
        try:
            target_id = int(str(row.get("approved_target_id", "")).strip())
        except ValueError as exc:
            raise RuntimeError(f"Baris {line_number}: approved_target_id harus bilangan bulat positif.") from exc
        if target_id <= 0:
            raise RuntimeError(f"Baris {line_number}: approved_target_id harus bilangan bulat positif.")
        if decision == "approve_cross_branch" and entity != "customer":
            raise RuntimeError(f"Baris {line_number}: approve_cross_branch hanya untuk customer.")
        if decision != "approve_cross_branch" and entity == "customer" and row.get("review_status", "").startswith("only_outside"):
            raise RuntimeError(
                f"Baris {line_number}: customer lintas cabang memerlukan decision approve_cross_branch secara eksplisit."
            )
        selected.append(
            {
                "line_number": line_number,
                "entity": entity,
                "key1": key1,
                "key2": key2,
                "target_id": target_id,
                "method": DECISIONS[decision],
                "note": row.get("reviewer_note", "").strip(),
            }
        )
    return selected, skipped


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", required=True, help="Schema staging yang menjadi sumber review.")
    parser.add_argument("--review-csv", required=True, help="CSV review yang telah diisi manual.")
    parser.add_argument("--approved-by", default="migration-review", help="Nama/identitas reviewer untuk audit registry.")
    parser.add_argument("--apply", action="store_true", help="Tulis mapping ke control schema. Default hanya preflight.")
    parser.add_argument("--target-database", default=os.getenv("MIGRATION_PG_DATABASE", "budimas_dev"))
    parser.add_argument("--target-user", default=os.getenv("MIGRATION_PG_USER", "postgres"))
    parser.add_argument("--target-host", default=os.getenv("MIGRATION_PG_HOST", ""))
    parser.add_argument("--target-port", type=int, default=int(os.getenv("MIGRATION_PG_PORT", "0") or 0))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not SCHEMA_RE.fullmatch(args.schema):
        raise SystemExit("--schema tidak aman.")
    review_path = Path(args.review_csv).expanduser().resolve()
    if not review_path.is_file():
        raise SystemExit(f"File review tidak ditemukan: {review_path}")
    rows = read_rows(review_path)
    conn = pg_connect(args.target_database, args.target_user, args.target_host or None, args.target_port or None)
    try:
        conn.set_session(readonly=not args.apply, autocommit=False)
        with conn.cursor() as cursor:
            metadata = stage_metadata(cursor, args.schema)
            source_system = str(metadata["source_system"])
            assert_registry(cursor, source_system)
            selected, skipped = parse_approved_rows(rows, source_system)
            summary: dict[str, Any] = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "apply": bool(args.apply),
                "public_tables_written": False,
                "stage_schema": args.schema,
                "source_system": source_system,
                "rows_in_csv": len(rows),
                "selected_for_preflight": len(selected),
                "skipped": dict(sorted(skipped.items())),
                "by_entity": {},
            }
            by_entity: Counter[str] = Counter()
            inserted: Counter[str] = Counter()
            already_present: Counter[str] = Counter()
            for item in selected:
                entity = item["entity"]
                by_entity[entity] += 1
                if not source_exists(cursor, args.schema, entity, item["key1"], item["key2"]):
                    raise RuntimeError(
                        f"Baris {item['line_number']}: source key tidak ditemukan lagi pada staging {args.schema}."
                    )
                current = existing_mapping_target(cursor, entity, source_system, item["key1"], item["key2"])
                if current is not None:
                    if current != item["target_id"]:
                        raise RuntimeError(
                            f"Baris {item['line_number']}: mapping aktif sudah menunjuk target {current}, "
                            f"bukan {item['target_id']}. Perubahan mapping harus melalui review baru."
                        )
                    already_present[entity] += 1
                    continue
                if args.apply:
                    insert_mapping(
                        cursor,
                        entity,
                        source_system,
                        item["key1"],
                        item["key2"],
                        item["target_id"],
                        item["method"],
                        args.approved_by,
                        item["note"],
                    )
                    inserted[entity] += 1
            summary["by_entity"] = dict(sorted(by_entity.items()))
            summary["already_present"] = dict(sorted(already_present.items()))
            summary["inserted"] = dict(sorted(inserted.items()))
            if args.apply:
                conn.commit()
            else:
                conn.rollback()
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
