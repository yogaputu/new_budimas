#!/usr/bin/env python3
import argparse
import os
from datetime import datetime

import pg8000


PG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("DB_NAME", "budimas_dev"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASS", ""),
}


def connect():
    return pg8000.connect(**PG)


def fetch_one(cur, sql, params=()):
    cur.execute(sql, params)
    return cur.fetchone()


def sync_sequence(cur, sequence_name, table_name):
    cur.execute(
        f"SELECT setval(%s, COALESCE((SELECT MAX(id) FROM {table_name}), 0) + 1, false)",
        (sequence_name,),
    )


def ensure_audit(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS legacy_product_uom_backfill_audit (
            id BIGSERIAL PRIMARY KEY,
            batch_code TEXT NOT NULL,
            action TEXT NOT NULL,
            id_produk BIGINT,
            kode_sku TEXT,
            source_system TEXT,
            legacy_satuan TEXT,
            legacy_namaunit TEXT,
            legacy_perunit INTEGER,
            message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_legacy_product_uom_backfill_batch
        ON legacy_product_uom_backfill_audit (batch_code, action)
        """
    )


def create_source_view(cur, schema):
    cur.execute("DROP TABLE IF EXISTS tmp_legacy_product_uom_source")
    cur.execute(
        f"""
        CREATE TEMP TABLE tmp_legacy_product_uom_source AS
        WITH unit_name AS (
            SELECT DISTINCT ON (UPPER(TRIM(kode)))
                UPPER(TRIM(kode)) AS kode,
                NULLIF(TRIM(nama), '') AS nama
            FROM {schema}.barangsatuan
            WHERE NULLIF(TRIM(kode), '') IS NOT NULL
            ORDER BY UPPER(TRIM(kode)), staging_id ASC
        ),
        ranked AS (
            SELECT
                s.*,
                ROW_NUMBER() OVER (
                    PARTITION BY UPPER(TRIM(s.kode))
                    ORDER BY s.source_priority ASC, s.staging_id ASC
                ) AS rn
            FROM {schema}.stok s
            WHERE NULLIF(TRIM(s.kode), '') IS NOT NULL
        ),
        clean AS (
            SELECT
                p.id AS id_produk,
                p.kode_sku,
                p.satuan AS produk_satuan,
                p.isiperbox,
                p.isiperkarton,
                r.source_system,
                COALESCE(NULLIF(UPPER(TRIM(r.satuan)), ''), NULLIF(UPPER(TRIM(p.satuan)), ''), 'PC') AS base_code,
                COALESCE(bu.nama, NULLIF(UPPER(TRIM(r.satuan)), ''), NULLIF(UPPER(TRIM(p.satuan)), ''), 'PIECE') AS base_name,
                COALESCE(NULLIF(UPPER(TRIM(r.namaunit)), ''), 'CT') AS large_code,
                COALESCE(lu.nama, NULLIF(UPPER(TRIM(r.namaunit)), ''), 'CARTON') AS large_name,
                NULLIF(REGEXP_REPLACE(COALESCE(r.perunit, '0'), '[^0-9.-]', '', 'g'), '')::numeric AS legacy_perunit,
                NULLIF(TRIM(r.satuan), '') AS legacy_satuan,
                NULLIF(TRIM(r.namaunit), '') AS legacy_namaunit
            FROM ranked r
            JOIN produk p ON UPPER(TRIM(p.kode_sku)) = UPPER(TRIM(r.kode))
            LEFT JOIN unit_name bu ON bu.kode = UPPER(TRIM(r.satuan))
            LEFT JOIN unit_name lu ON lu.kode = UPPER(TRIM(r.namaunit))
            WHERE r.rn = 1
        )
        SELECT
            *,
            CASE
                WHEN large_code IN ('BX', 'BOX', 'PK', 'PACK', 'RT', 'RTG', 'SCH', 'BD', 'BG', 'BT', 'CP', 'JR', 'KL', 'PH', 'ST', 'STR', 'TB', 'TP', 'TR')
                    THEN 2
                ELSE 3
            END AS large_level
        FROM clean
        WHERE legacy_perunit IS NOT NULL
          AND legacy_perunit > 0
          AND legacy_perunit = FLOOR(legacy_perunit)
        """
    )


def report(cur):
    rows = []
    checks = (
        (
            "matched_products",
            "SELECT COUNT(*) FROM tmp_legacy_product_uom_source",
        ),
        (
            "will_update_produk_satuan",
            """
            SELECT COUNT(*) FROM tmp_legacy_product_uom_source s
            JOIN produk p ON p.id = s.id_produk
            WHERE p.satuan IS NULL OR BTRIM(p.satuan) = ''
            """,
        ),
        (
            "will_update_produk_isiperkarton",
            """
            SELECT COUNT(*) FROM tmp_legacy_product_uom_source s
            JOIN produk p ON p.id = s.id_produk
            WHERE COALESCE(p.isiperkarton, 0) = 0
            """,
        ),
        (
            "will_update_produk_isiperbox_for_box_units",
            """
            SELECT COUNT(*) FROM tmp_legacy_product_uom_source s
            JOIN produk p ON p.id = s.id_produk
            WHERE COALESCE(p.isiperbox, 0) = 0
              AND s.large_level = 2
            """,
        ),
        (
            "will_insert_base_uom",
            """
            SELECT COUNT(*) FROM tmp_legacy_product_uom_source s
            WHERE NOT EXISTS (
                SELECT 1 FROM produk_uom pu
                WHERE pu.id_produk = s.id_produk
                  AND UPPER(TRIM(COALESCE(pu.kode, ''))) = s.base_code
                  AND COALESCE(pu.faktor_konversi, 0) = 1
            )
            """,
        ),
        (
            "will_insert_large_uom",
            """
            SELECT COUNT(*) FROM tmp_legacy_product_uom_source s
            WHERE NOT EXISTS (
                SELECT 1 FROM produk_uom pu
                WHERE pu.id_produk = s.id_produk
                  AND UPPER(TRIM(COALESCE(pu.kode, ''))) = s.large_code
                  AND COALESCE(pu.faktor_konversi, 0) = s.legacy_perunit::integer
            )
            """,
        ),
    )
    for name, sql in checks:
        rows.append((name, fetch_one(cur, sql)[0]))
    return rows


def apply_changes(cur, batch_code):
    cur.execute(
        """
        INSERT INTO legacy_product_uom_backfill_audit (
            batch_code, action, id_produk, kode_sku, source_system,
            legacy_satuan, legacy_namaunit, legacy_perunit, message
        )
        SELECT
            %s, 'candidate', id_produk, kode_sku, source_system,
            legacy_satuan, legacy_namaunit, legacy_perunit::integer,
            'Legacy STOK UOM candidate'
        FROM tmp_legacy_product_uom_source
        """,
        (batch_code,),
    )

    cur.execute(
        """
        UPDATE produk p
        SET
            satuan = CASE
                WHEN p.satuan IS NULL OR BTRIM(p.satuan) = '' THEN s.base_code
                ELSE p.satuan
            END,
            isiperkarton = CASE
                WHEN COALESCE(p.isiperkarton, 0) = 0 THEN s.legacy_perunit::integer
                ELSE p.isiperkarton
            END,
            isiperbox = CASE
                WHEN COALESCE(p.isiperbox, 0) = 0 AND s.large_level = 2 THEN s.legacy_perunit::integer
                ELSE p.isiperbox
            END
        FROM tmp_legacy_product_uom_source s
        WHERE p.id = s.id_produk
          AND (
              p.satuan IS NULL OR BTRIM(p.satuan) = ''
              OR COALESCE(p.isiperkarton, 0) = 0
              OR (COALESCE(p.isiperbox, 0) = 0 AND s.large_level = 2)
          )
        """
    )
    updated_produk = cur.rowcount

    sync_sequence(cur, "produk_uom_id_seq", "produk_uom")

    cur.execute(
        """
        INSERT INTO produk_uom (
            kode, nama, level, packing_satuan, set_default_sales,
            set_default_storage, id_produk, faktor_konversi
        )
        SELECT
            LEFT(s.base_code, 25),
            LEFT(s.base_name, 50),
            1,
            LEFT(s.base_code, 15),
            1,
            1,
            s.id_produk,
            1
        FROM tmp_legacy_product_uom_source s
        WHERE NOT EXISTS (
            SELECT 1 FROM produk_uom pu
            WHERE pu.id_produk = s.id_produk
              AND UPPER(TRIM(COALESCE(pu.kode, ''))) = s.base_code
              AND COALESCE(pu.faktor_konversi, 0) = 1
        )
        """
    )
    inserted_base = cur.rowcount

    sync_sequence(cur, "produk_uom_id_seq", "produk_uom")

    cur.execute(
        """
        INSERT INTO produk_uom (
            kode, nama, level, packing_satuan, set_default_sales,
            set_default_storage, id_produk, faktor_konversi
        )
        SELECT
            LEFT(s.large_code, 25),
            LEFT(s.large_name, 50),
            s.large_level,
            LEFT(s.large_code, 15),
            0,
            0,
            s.id_produk,
            s.legacy_perunit::integer
        FROM tmp_legacy_product_uom_source s
        WHERE s.legacy_perunit > 1
          AND NOT EXISTS (
              SELECT 1 FROM produk_uom pu
              WHERE pu.id_produk = s.id_produk
                AND UPPER(TRIM(COALESCE(pu.kode, ''))) = s.large_code
                AND COALESCE(pu.faktor_konversi, 0) = s.legacy_perunit::integer
          )
        """
    )
    inserted_large = cur.rowcount

    sync_sequence(cur, "produk_uom_id_seq", "produk_uom")

    return {
        "updated_produk": updated_produk,
        "inserted_base_uom": inserted_base,
        "inserted_large_uom": inserted_large,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", default="legacy_master_import_server")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--batch-code", default=None)
    args = parser.parse_args()

    batch_code = args.batch_code or f"legacy-product-uom-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    conn = connect()
    try:
        cur = conn.cursor()
        ensure_audit(cur)
        create_source_view(cur, args.schema)
        before = report(cur)

        print(f"mode\t{'APPLY' if args.apply else 'DRY_RUN'}")
        print(f"batch_code\t{batch_code}")
        for name, value in before:
            print(f"{name}\t{value}")

        if args.apply:
            suffix = datetime.now().strftime("%Y%m%d%H%M%S")
            cur.execute(f"CREATE TABLE IF NOT EXISTS backup_produk_uom_{suffix} AS TABLE produk_uom")
            cur.execute(f"CREATE TABLE IF NOT EXISTS backup_produk_{suffix} AS TABLE produk")
            result = apply_changes(cur, batch_code)
            conn.commit()
            print(f"backup_produk\tbackup_produk_{suffix}")
            print(f"backup_produk_uom\tbackup_produk_uom_{suffix}")
            for name, value in result.items():
                print(f"{name}\t{value}")
        else:
            conn.rollback()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
