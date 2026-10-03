#!/usr/bin/env python3
import argparse
import re
import sys

import pg8000


PG = {
    "host": "127.0.0.1",
    "port": 5432,
    "database": "budimas_dev",
    "user": "postgres",
    "password": "",
}


def connect():
    return pg8000.connect(**PG)


def scalar(cur, sql, params=()):
    cur.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


def sync_sequences(cur):
    for table, pk in [("wms_rack_master", "id"), ("wms_stock_rak", "id")]:
        seq = scalar(cur, "SELECT pg_get_serial_sequence(%s, %s)", (table, pk))
        if not seq:
            default_expr = scalar(
                cur,
                """
                SELECT column_default
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = %s
                  AND column_name = %s
                """,
                (table, pk),
            )
            match = re.search(r"nextval\\('([^']+)'::regclass\\)", default_expr or "")
            seq = match.group(1) if match else None
        if seq:
            cur.execute(
                f"SELECT setval(%s, COALESCE((SELECT MAX({pk}) FROM {table}), 0) + 1, false)",
                (seq,),
            )


def ensure_audit(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS legacy_master_merge_audit (
            id BIGSERIAL PRIMARY KEY,
            batch_code TEXT NOT NULL,
            target_table TEXT NOT NULL,
            action TEXT NOT NULL,
            source_system TEXT,
            source_priority INTEGER,
            legacy_code TEXT,
            target_id TEXT,
            message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


def build_views(cur, schema):
    cur.execute("DROP TABLE IF EXISTS tmp_legacy_wmsrak_pick")
    cur.execute("DROP TABLE IF EXISTS tmp_legacy_wmsstock_pick")
    cur.execute(
        f"""
        CREATE TEMP TABLE tmp_legacy_wmsrak_pick AS
        WITH ranked AS (
            SELECT
                w.*,
                COALESCE(NULLIF(REGEXP_REPLACE(COALESCE(w.qtykarton, '0'), '[^0-9.-]', '', 'g'), ''), '0')::numeric AS qty_karton_num,
                COALESCE(NULLIF(REGEXP_REPLACE(COALESCE(w.qtypieces, '0'), '[^0-9.-]', '', 'g'), ''), '0')::numeric AS qty_pcs_num,
                ROW_NUMBER() OVER (
                    PARTITION BY UPPER(TRIM(w.koderak))
                    ORDER BY w.source_priority ASC, w.staging_id ASC
                ) AS rn
            FROM {schema}.wmsrak w
            WHERE NULLIF(TRIM(w.koderak), '') IS NOT NULL
        )
        SELECT * FROM ranked WHERE rn = 1
        """
    )
    cur.execute(
        f"""
        CREATE TEMP TABLE tmp_legacy_wmsstock_pick AS
        WITH prepared AS (
            SELECT
                w.*,
                COALESCE(NULLIF(REGEXP_REPLACE(COALESCE(w.qtykarton, '0'), '[^0-9.-]', '', 'g'), ''), '0')::numeric AS qty_karton_num,
                COALESCE(NULLIF(REGEXP_REPLACE(COALESCE(w.qtypieces, '0'), '[^0-9.-]', '', 'g'), ''), '0')::numeric AS qty_pcs_num,
                NULLIF(TRIM(NULLIF(COALESCE(w.batch, ''), 'N')), '') AS batch_key,
                CASE
                    WHEN TRIM(COALESCE(w.expireddate, '')) ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}' THEN LEFT(TRIM(w.expireddate), 10)::date
                    ELSE NULL
                END AS expired_key
            FROM {schema}.wmsrak w
            WHERE NULLIF(TRIM(w.koderak), '') IS NOT NULL
              AND NULLIF(TRIM(w.kodebarang), '') IS NOT NULL
        ),
        ranked AS (
            SELECT
                prepared.*,
                ROW_NUMBER() OVER (
                    PARTITION BY
                        UPPER(TRIM(koderak)),
                        UPPER(TRIM(kodebarang)),
                        COALESCE(batch_key, ''),
                        COALESCE(expired_key, DATE '1900-01-01')
                    ORDER BY source_priority ASC, staging_id ASC
                ) AS rn
            FROM prepared
        )
        SELECT * FROM ranked WHERE rn = 1
        """
    )


def merge_rack_master(cur, batch_code, apply):
    candidates = scalar(cur, "SELECT COUNT(*) FROM tmp_legacy_wmsrak_pick") or 0
    inserts = scalar(
        cur,
        """
        SELECT COUNT(*)
        FROM tmp_legacy_wmsrak_pick w
        LEFT JOIN wms_rack_master r ON UPPER(TRIM(r.kode_rak)) = UPPER(TRIM(w.koderak))
        WHERE r.id IS NULL
        """,
    ) or 0
    existing = candidates - inserts

    if apply and inserts:
        cur.execute(
            """
            INSERT INTO wms_rack_master (
                id_cabang, gudang, rak, level, kolom, nomor_urut,
                kode_rak, type_rak, status_rak, active, source_type, source_id,
                created_at, updated_at, max_qty_pcs, max_qty_karton
            )
            SELECT
                5,
                NULLIF(REGEXP_REPLACE(COALESCE(w.gudang, '0'), '[^0-9.-]', '', 'g'), '')::numeric::smallint,
                NULLIF(REGEXP_REPLACE(COALESCE(w.rak, '0'), '[^0-9.-]', '', 'g'), '')::numeric::smallint,
                NULLIF(REGEXP_REPLACE(COALESCE(w.level, '0'), '[^0-9.-]', '', 'g'), '')::numeric::smallint,
                NULLIF(REGEXP_REPLACE(COALESCE(w.kolom, '0'), '[^0-9.-]', '', 'g'), '')::numeric::smallint,
                NULLIF(REGEXP_REPLACE(COALESCE(w.nomorurut, '0'), '[^0-9.-]', '', 'g'), '')::numeric::smallint,
                LEFT(TRIM(w.koderak), 80),
                LEFT(COALESCE(NULLIF(TRIM(w.typerak), ''), 'Tetap'), 30),
                LEFT(COALESCE(NULLIF(TRIM(w.statusrak), ''), 'Kosong'), 30),
                COALESCE(NULLIF(TRIM(w.active), ''), 'Yes') NOT IN ('0', 'No', 'NO', 'no', 'false', 'False', 'FALSE'),
                'mssql_wmsrak',
                LEFT(CONCAT(w.source_system, ':', TRIM(w.id)), 80),
                COALESCE(NULLIF(TRIM(w.createdat), ''), NOW()::text)::timestamp,
                COALESCE(NULLIF(TRIM(w.updatedat), ''), NOW()::text)::timestamp,
                0,
                0
            FROM tmp_legacy_wmsrak_pick w
            LEFT JOIN wms_rack_master r ON UPPER(TRIM(r.kode_rak)) = UPPER(TRIM(w.koderak))
            WHERE r.id IS NULL
            """
        )
        cur.execute(
            """
            INSERT INTO legacy_master_merge_audit (
                batch_code, target_table, action, source_system,
                source_priority, legacy_code, target_id, message
            )
            SELECT
                %s, 'wms_rack_master', 'insert', w.source_system,
                w.source_priority, TRIM(w.koderak), r.id::text,
                'Inserted WMS rack from legacy staging'
            FROM tmp_legacy_wmsrak_pick w
            JOIN wms_rack_master r ON UPPER(TRIM(r.kode_rak)) = UPPER(TRIM(w.koderak))
            LEFT JOIN backup_wms_rack_master_20260717_legacy_merge b ON b.id = r.id
            WHERE b.id IS NULL
            """,
            (batch_code,),
        )

    return {
        "target": "wms_rack_master",
        "candidates": candidates,
        "insert": inserts,
        "existing_skip": existing,
    }


def merge_stock_rak(cur, batch_code, apply):
    candidates = scalar(
        cur,
        """
        SELECT COUNT(*)
        FROM tmp_legacy_wmsstock_pick
        WHERE qty_karton_num <> 0 OR qty_pcs_num <> 0
        """,
    ) or 0
    existing_mssql = scalar(
        cur,
        """
        SELECT COUNT(*)
        FROM wms_stock_rak
        WHERE source_type = 'mssql_wmsrak'
        """,
    ) or 0
    missing_product = scalar(
        cur,
        """
        SELECT COUNT(*)
        FROM tmp_legacy_wmsstock_pick w
        LEFT JOIN produk p ON UPPER(TRIM(p.kode_sku)) = UPPER(TRIM(w.kodebarang))
        WHERE (w.qty_karton_num <> 0 OR w.qty_pcs_num <> 0)
          AND p.id IS NULL
        """,
    ) or 0
    deleted = 0
    inserted = candidates

    if apply:
        cur.execute("DELETE FROM wms_stock_rak WHERE source_type = 'mssql_wmsrak'")
        deleted = cur.rowcount
        cur.execute(
            """
            INSERT INTO wms_stock_rak (
                id_cabang, id_produk, kode_barang, nama_barang,
                kode_rak, shelf_type, qty_pcs, qty_karton,
                batch_number, expired_date, status, source_type, source_id,
                created_at, updated_at
            )
            SELECT
                5,
                p.id,
                LEFT(TRIM(w.kodebarang), 80),
                LEFT(COALESCE(NULLIF(TRIM(w.namabarang), ''), p.nama), 120),
                LEFT(TRIM(w.koderak), 80),
                LEFT(COALESCE(NULLIF(TRIM(w.typerak), ''), 'Tetap'), 30),
                w.qty_pcs_num::integer,
                w.qty_karton_num::integer,
                w.batch_key,
                w.expired_key,
                CASE WHEN (w.qty_pcs_num <> 0 OR w.qty_karton_num <> 0) THEN 'READY' ELSE 'EMPTY' END,
                'mssql_wmsrak',
                LEFT(CONCAT(w.source_system, ':', TRIM(w.id)), 80),
                COALESCE(NULLIF(TRIM(w.createdat), ''), NOW()::text)::timestamp,
                COALESCE(NULLIF(TRIM(w.updatedat), ''), NOW()::text)::timestamp
            FROM tmp_legacy_wmsstock_pick w
            LEFT JOIN produk p ON UPPER(TRIM(p.kode_sku)) = UPPER(TRIM(w.kodebarang))
            WHERE (w.qty_karton_num <> 0 OR w.qty_pcs_num <> 0)
            """
        )
        inserted = cur.rowcount
        cur.execute(
            """
            INSERT INTO legacy_master_merge_audit (
                batch_code, target_table, action, source_system,
                source_priority, legacy_code, target_id, message
            )
            VALUES (
                %s, 'wms_stock_rak', 'replace', NULL,
                NULL, NULL, NULL,
                %s
            )
            """,
            (
                batch_code,
                (
                    "Replaced WMS rack stock from legacy staging: "
                    f"deleted={deleted}, inserted={inserted}, missing_product={missing_product}"
                ),
            ),
        )

    return {
        "target": "wms_stock_rak",
        "candidates_nonzero": candidates,
        "existing_mssql_before": existing_mssql,
        "replace_delete": deleted if apply else existing_mssql,
        "replace_insert": inserted,
        "insert_missing_product": missing_product,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", default="legacy_master_import_server")
    parser.add_argument("--batch-code", default="legacy-wms-merge-20260717")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    conn = connect()
    try:
        cur = conn.cursor()
        ensure_audit(cur)
        sync_sequences(cur)
        build_views(cur, args.schema)
        results = [
            merge_rack_master(cur, args.batch_code, args.apply),
            merge_stock_rak(cur, args.batch_code, args.apply),
        ]
        if args.apply:
            sync_sequences(cur)
            conn.commit()
        else:
            conn.rollback()
        print("mode\t" + ("APPLY" if args.apply else "DRY_RUN"))
        for item in results:
            print("\t".join([item["target"]] + [f"{k}={v}" for k, v in item.items() if k != "target"]))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
