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

DEFAULT_TEST_HASH = "$2b$12$2l5/S1KZNuW8K99EACyswujjA3GWr/MjEEkJFO76E8zwfAnU8/7GK"


def connect():
    return pg8000.connect(**PG)


def scalar(cur, sql, params=()):
    cur.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


def sync_sequences(cur):
    for table, pk in [("users", "id"), ("sales", "id"), ("sales_detail", "id")]:
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
    cur.execute("DROP TABLE IF EXISTS tmp_legacy_sales_pick")
    cur.execute(
        f"""
        CREATE TEMP TABLE tmp_legacy_sales_pick AS
        WITH ranked AS (
            SELECT
                s.*,
                LOWER(REGEXP_REPLACE(TRIM(s.kode), '[^0-9A-Za-z]+', '_', 'g')) AS safe_code,
                ROW_NUMBER() OVER (
                    PARTITION BY UPPER(TRIM(s.kode))
                    ORDER BY s.source_priority ASC, s.staging_id ASC
                ) AS rn
            FROM {schema}.sales s
            WHERE NULLIF(TRIM(s.kode), '') IS NOT NULL
        )
        SELECT * FROM ranked WHERE rn = 1
        """
    )
    cur.execute("DROP TABLE IF EXISTS tmp_principal_pick")
    cur.execute(
        """
        CREATE TEMP TABLE tmp_principal_pick AS
        SELECT DISTINCT ON (UPPER(TRIM(kode)))
            id,
            kode,
            id_perusahaan
        FROM principal
        WHERE NULLIF(TRIM(COALESCE(kode, '')), '') IS NOT NULL
        ORDER BY UPPER(TRIM(kode)), id ASC
        """
    )


def counts(cur):
    candidates = scalar(cur, "SELECT COUNT(*) FROM tmp_legacy_sales_pick") or 0
    missing_detail = scalar(
        cur,
        """
        SELECT COUNT(*)
        FROM tmp_legacy_sales_pick ls
        LEFT JOIN sales_detail sd ON UPPER(TRIM(sd.kode_sales)) = UPPER(TRIM(ls.kode))
        WHERE sd.id IS NULL
        """,
    ) or 0
    existing_detail = candidates - missing_detail
    missing_principal = scalar(
        cur,
        """
        SELECT COUNT(*)
        FROM tmp_legacy_sales_pick ls
        LEFT JOIN sales_detail sd ON UPPER(TRIM(sd.kode_sales)) = UPPER(TRIM(ls.kode))
        LEFT JOIN tmp_principal_pick pr ON UPPER(TRIM(pr.kode)) = UPPER(TRIM(ls.kodeprinciple))
        WHERE sd.id IS NULL
          AND NULLIF(TRIM(COALESCE(ls.kodeprinciple, '')), '') IS NOT NULL
          AND pr.id IS NULL
        """,
    ) or 0
    existing_user = scalar(
        cur,
        """
        SELECT COUNT(*)
        FROM tmp_legacy_sales_pick ls
        LEFT JOIN sales_detail sd ON UPPER(TRIM(sd.kode_sales)) = UPPER(TRIM(ls.kode))
        JOIN users u ON u.username = CONCAT('old_', ls.safe_code)
        WHERE sd.id IS NULL
        """,
    ) or 0
    return {
        "target": "sales",
        "candidates": candidates,
        "insert": missing_detail,
        "existing_skip": existing_detail,
        "insert_missing_principal": missing_principal,
        "missing_code_existing_user": existing_user,
    }


def apply_merge(cur, batch_code):
    cur.execute(
        """
        INSERT INTO users (
            nama, email, telepon, id_jabatan, id_cabang, username, password,
            alamat, id_perusahaan, id_cabang_list, id_perusahaan_list
        )
        SELECT
            LEFT(COALESCE(NULLIF(TRIM(ls.nama), ''), TRIM(ls.kode)), 100),
            LEFT(CONCAT('sales_', ls.safe_code, '@migration.local'), 100),
            LEFT(NULLIF(TRIM(ls.telpon), ''), 50),
            4,
            5,
            LEFT(CONCAT('old_', ls.safe_code), 100),
            %s,
            LEFT(NULLIF(TRIM(CONCAT_WS(' ', NULLIF(TRIM(ls.alamat), ''), NULLIF(TRIM(ls.kota), ''))), ''), 255),
            COALESCE(pr.id_perusahaan, 1),
            '5',
            COALESCE(pr.id_perusahaan, 1)::text
        FROM tmp_legacy_sales_pick ls
        LEFT JOIN sales_detail sd ON UPPER(TRIM(sd.kode_sales)) = UPPER(TRIM(ls.kode))
        LEFT JOIN tmp_principal_pick pr ON UPPER(TRIM(pr.kode)) = UPPER(TRIM(ls.kodeprinciple))
        LEFT JOIN users u ON u.username = CONCAT('old_', ls.safe_code)
        WHERE sd.id IS NULL
          AND u.id IS NULL
        """,
        (DEFAULT_TEST_HASH,),
    )

    cur.execute(
        """
        INSERT INTO sales (id_user, id_principal, id_tipe, plafon_limit)
        SELECT
            u.id,
            pr.id,
            1,
            0
        FROM tmp_legacy_sales_pick ls
        LEFT JOIN sales_detail sd ON UPPER(TRIM(sd.kode_sales)) = UPPER(TRIM(ls.kode))
        JOIN users u ON u.username = CONCAT('old_', ls.safe_code)
        LEFT JOIN tmp_principal_pick pr ON UPPER(TRIM(pr.kode)) = UPPER(TRIM(ls.kodeprinciple))
        LEFT JOIN sales s
          ON s.id_user = u.id
         AND s.id_principal IS NOT DISTINCT FROM pr.id
        WHERE sd.id IS NULL
          AND s.id IS NULL
        """
    )

    cur.execute(
        """
        INSERT INTO sales_detail (id_sales, kode_sales)
        SELECT
            s.id,
            LEFT(TRIM(ls.kode), 50)
        FROM tmp_legacy_sales_pick ls
        LEFT JOIN sales_detail sd ON UPPER(TRIM(sd.kode_sales)) = UPPER(TRIM(ls.kode))
        JOIN users u ON u.username = CONCAT('old_', ls.safe_code)
        LEFT JOIN tmp_principal_pick pr ON UPPER(TRIM(pr.kode)) = UPPER(TRIM(ls.kodeprinciple))
        JOIN sales s
          ON s.id_user = u.id
         AND s.id_principal IS NOT DISTINCT FROM pr.id
        WHERE sd.id IS NULL
        """
    )

    cur.execute(
        """
        INSERT INTO legacy_master_merge_audit (
            batch_code, target_table, action, source_system,
            source_priority, legacy_code, target_id, message
        )
        SELECT
            %s, 'users', 'insert', ls.source_system,
            ls.source_priority, TRIM(ls.kode), u.id::text,
            'Inserted sales user from legacy staging'
        FROM tmp_legacy_sales_pick ls
        JOIN users u ON u.username = CONCAT('old_', ls.safe_code)
        LEFT JOIN backup_users_20260717_legacy_merge b ON b.id = u.id
        WHERE b.id IS NULL
        """,
        (batch_code,),
    )
    cur.execute(
        """
        INSERT INTO legacy_master_merge_audit (
            batch_code, target_table, action, source_system,
            source_priority, legacy_code, target_id, message
        )
        SELECT
            %s, 'sales', 'insert', ls.source_system,
            ls.source_priority, TRIM(ls.kode), s.id::text,
            'Inserted sales from legacy staging'
        FROM tmp_legacy_sales_pick ls
        JOIN users u ON u.username = CONCAT('old_', ls.safe_code)
        LEFT JOIN tmp_principal_pick pr ON UPPER(TRIM(pr.kode)) = UPPER(TRIM(ls.kodeprinciple))
        JOIN sales s
          ON s.id_user = u.id
         AND s.id_principal IS NOT DISTINCT FROM pr.id
        LEFT JOIN backup_sales_20260717_legacy_merge b ON b.id = s.id
        WHERE b.id IS NULL
        """,
        (batch_code,),
    )
    cur.execute(
        """
        INSERT INTO legacy_master_merge_audit (
            batch_code, target_table, action, source_system,
            source_priority, legacy_code, target_id, message
        )
        SELECT
            %s, 'sales_detail', 'insert', ls.source_system,
            ls.source_priority, TRIM(ls.kode), sd.id::text,
            'Inserted sales_detail code from legacy staging'
        FROM tmp_legacy_sales_pick ls
        JOIN sales_detail sd ON UPPER(TRIM(sd.kode_sales)) = UPPER(TRIM(ls.kode))
        LEFT JOIN backup_sales_detail_20260717_legacy_merge b ON b.id = sd.id
        WHERE b.id IS NULL
        """,
        (batch_code,),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", default="legacy_master_import_server")
    parser.add_argument("--batch-code", default="legacy-sales-merge-20260717")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    conn = connect()
    try:
        cur = conn.cursor()
        ensure_audit(cur)
        sync_sequences(cur)
        build_views(cur, args.schema)
        result = counts(cur)
        if args.apply:
            apply_merge(cur, args.batch_code)
            sync_sequences(cur)
            conn.commit()
        else:
            conn.rollback()
        print("mode\t" + ("APPLY" if args.apply else "DRY_RUN"))
        print("\t".join([result["target"]] + [f"{k}={v}" for k, v in result.items() if k != "target"]))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
