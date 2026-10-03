#!/usr/bin/env python3
import argparse
import re
import sys

import pg8000


PG = dict(host="127.0.0.1", port=5432, database="budimas_dev", user="postgres", password="")
DEFAULT_TEST_HASH = "$2b$12$2l5/S1KZNuW8K99EACyswujjA3GWr/MjEEkJFO76E8zwfAnU8/7GK"


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
                WHERE table_schema='public' AND table_name=%s AND column_name=%s
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


def ensure_objects(cur, batch_code):
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
    suffix = re.sub(r"[^0-9A-Za-z_]+", "_", batch_code).lower()
    for table in ("users", "sales", "sales_detail"):
        cur.execute(f"CREATE TABLE IF NOT EXISTS backup_{table}_{suffix} AS TABLE {table} WITH NO DATA")


def build_candidates(cur):
    cur.execute("DROP TABLE IF EXISTS tmp_legacy_order_sales_candidates")
    cur.execute(
        """
        CREATE TEMP TABLE tmp_legacy_order_sales_candidates AS
        WITH order_sales_raw AS (
            SELECT
                btrim(h.kodesales) AS kode_sales,
                NULLIF(btrim(h.namasales), '') AS nama_sales,
                h.source_system,
                h.source_priority,
                h.kodeprinciple,
                so.id_cabang,
                count(*) AS order_count
            FROM legacy_transaction_import_server.hjualsm h
            LEFT JOIN sales_order so
              ON btrim(so.no_order) = btrim(h.nota)
            WHERE btrim(coalesce(h.kodesales, '')) <> ''
            GROUP BY
                btrim(h.kodesales),
                NULLIF(btrim(h.namasales), ''),
                h.source_system,
                h.source_priority,
                h.kodeprinciple,
                so.id_cabang
        ),
        missing_codes AS (
            SELECT DISTINCT r.kode_sales
            FROM order_sales_raw r
            LEFT JOIN sales_detail sd
              ON upper(btrim(sd.kode_sales)) = upper(r.kode_sales)
            WHERE sd.id IS NULL
        ),
        name_pick AS (
            SELECT DISTINCT ON (upper(r.kode_sales))
                r.kode_sales,
                COALESCE(
                    NULLIF(
                        CASE
                            WHEN upper(coalesce(r.nama_sales, '')) = 'VACANT' THEN ''
                            ELSE r.nama_sales
                        END,
                        ''
                    ),
                    'LEGACY SALES ' || r.kode_sales
                ) AS nama_sales
            FROM order_sales_raw r
            JOIN missing_codes m ON upper(m.kode_sales) = upper(r.kode_sales)
            ORDER BY
                upper(r.kode_sales),
                CASE WHEN r.nama_sales IS NULL OR upper(r.nama_sales) = 'VACANT' THEN 1 ELSE 0 END,
                r.order_count DESC,
                r.nama_sales
        ),
        source_pick AS (
            SELECT DISTINCT ON (upper(r.kode_sales))
                r.kode_sales,
                r.source_system,
                r.source_priority
            FROM order_sales_raw r
            JOIN missing_codes m ON upper(m.kode_sales) = upper(r.kode_sales)
            ORDER BY upper(r.kode_sales), r.source_priority, r.order_count DESC
        ),
        principal_pick AS (
            SELECT DISTINCT ON (upper(r.kode_sales))
                r.kode_sales,
                pr.id AS id_principal,
                pr.id_perusahaan
            FROM order_sales_raw r
            JOIN missing_codes m ON upper(m.kode_sales) = upper(r.kode_sales)
            LEFT JOIN principal pr
              ON upper(btrim(pr.kode)) = upper(btrim(r.kodeprinciple))
            ORDER BY
                upper(r.kode_sales),
                CASE WHEN pr.id IS NULL THEN 1 ELSE 0 END,
                r.order_count DESC,
                pr.id
        ),
        cabang_pick AS (
            SELECT DISTINCT ON (upper(r.kode_sales))
                r.kode_sales,
                cb.id AS id_cabang,
                cb.id_perusahaan
            FROM order_sales_raw r
            JOIN missing_codes m ON upper(m.kode_sales) = upper(r.kode_sales)
            LEFT JOIN cabang cb ON cb.id = r.id_cabang
            ORDER BY
                upper(r.kode_sales),
                CASE WHEN cb.id IS NULL THEN 1 ELSE 0 END,
                r.order_count DESC,
                cb.id
        ),
        access_pick AS (
            SELECT
                r.kode_sales,
                string_agg(DISTINCT cb.id::text, ',' ORDER BY cb.id::text) FILTER (WHERE cb.id IS NOT NULL) AS id_cabang_list,
                string_agg(DISTINCT cb.id_perusahaan::text, ',' ORDER BY cb.id_perusahaan::text) FILTER (WHERE cb.id_perusahaan IS NOT NULL) AS id_perusahaan_list,
                sum(r.order_count) AS total_orders
            FROM order_sales_raw r
            JOIN missing_codes m ON upper(m.kode_sales) = upper(r.kode_sales)
            LEFT JOIN cabang cb ON cb.id = r.id_cabang
            GROUP BY r.kode_sales
        )
        SELECT
            m.kode_sales,
            lower(regexp_replace(m.kode_sales, '[^0-9A-Za-z]+', '_', 'g')) AS safe_code,
            n.nama_sales,
            sp.source_system,
            sp.source_priority,
            pp.id_principal,
            COALESCE(cp.id_cabang, 5) AS id_cabang,
            COALESCE(cp.id_perusahaan, pp.id_perusahaan, 1) AS id_perusahaan,
            COALESCE(ap.id_cabang_list, COALESCE(cp.id_cabang, 5)::text) AS id_cabang_list,
            COALESCE(ap.id_perusahaan_list, COALESCE(cp.id_perusahaan, pp.id_perusahaan, 1)::text) AS id_perusahaan_list,
            ap.total_orders
        FROM missing_codes m
        JOIN name_pick n ON upper(n.kode_sales) = upper(m.kode_sales)
        JOIN source_pick sp ON upper(sp.kode_sales) = upper(m.kode_sales)
        LEFT JOIN principal_pick pp ON upper(pp.kode_sales) = upper(m.kode_sales)
        LEFT JOIN cabang_pick cp ON upper(cp.kode_sales) = upper(m.kode_sales)
        LEFT JOIN access_pick ap ON upper(ap.kode_sales) = upper(m.kode_sales)
        """
    )


def report(cur):
    cur.execute(
        """
        SELECT
            count(*) AS candidates,
            count(*) FILTER (WHERE id_principal IS NULL) AS missing_principal,
            coalesce(sum(total_orders), 0) AS covered_orders
        FROM tmp_legacy_order_sales_candidates
        """
    )
    row = cur.fetchone()
    return {
        "candidates": row[0],
        "missing_principal": row[1],
        "covered_orders": row[2],
    }


def apply_merge(cur, batch_code):
    cur.execute(
        """
        INSERT INTO users (
            nama, email, telepon, id_jabatan, id_cabang, username, password,
            alamat, id_perusahaan, id_cabang_list, id_perusahaan_list
        )
        SELECT
            LEFT(c.nama_sales, 100),
            LEFT('sales_order_' || c.safe_code || '@migration.local', 100),
            NULL,
            4,
            c.id_cabang,
            LEFT('old_order_' || c.safe_code, 100),
            %s,
            'Migrated from legacy sales order header',
            c.id_perusahaan,
            c.id_cabang_list,
            c.id_perusahaan_list
        FROM tmp_legacy_order_sales_candidates c
        LEFT JOIN users u ON u.username = LEFT('old_order_' || c.safe_code, 100)
        WHERE u.id IS NULL
        """,
        (DEFAULT_TEST_HASH,),
    )
    inserted_users = cur.rowcount

    cur.execute(
        """
        INSERT INTO sales (id_user, id_principal, id_tipe, plafon_limit)
        SELECT
            u.id,
            c.id_principal,
            1,
            0
        FROM tmp_legacy_order_sales_candidates c
        JOIN users u ON u.username = LEFT('old_order_' || c.safe_code, 100)
        LEFT JOIN sales s
          ON s.id_user = u.id
         AND s.id_principal IS NOT DISTINCT FROM c.id_principal
        WHERE s.id IS NULL
        """
    )
    inserted_sales = cur.rowcount

    cur.execute(
        """
        INSERT INTO sales_detail (id_sales, kode_sales)
        SELECT
            s.id,
            LEFT(c.kode_sales, 50)
        FROM tmp_legacy_order_sales_candidates c
        JOIN users u ON u.username = LEFT('old_order_' || c.safe_code, 100)
        JOIN sales s
          ON s.id_user = u.id
         AND s.id_principal IS NOT DISTINCT FROM c.id_principal
        LEFT JOIN sales_detail sd
          ON upper(btrim(sd.kode_sales)) = upper(c.kode_sales)
        WHERE sd.id IS NULL
        """
    )
    inserted_sales_detail = cur.rowcount

    cur.execute(
        """
        INSERT INTO legacy_master_merge_audit (
            batch_code, target_table, action, source_system,
            source_priority, legacy_code, target_id, message
        )
        SELECT
            %s, 'sales_detail', 'insert_from_order_header', c.source_system,
            c.source_priority, c.kode_sales, sd.id::text,
            'Inserted missing sales/user from legacy order header'
        FROM tmp_legacy_order_sales_candidates c
        JOIN sales_detail sd
          ON upper(btrim(sd.kode_sales)) = upper(c.kode_sales)
        """,
        (batch_code,),
    )

    return {
        "inserted_users": inserted_users,
        "inserted_sales": inserted_sales,
        "inserted_sales_detail": inserted_sales_detail,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--batch-code", default="legacy-order-sales-users-20260720")
    args = parser.parse_args()

    conn = pg8000.connect(**PG)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")
        ensure_objects(cur, args.batch_code)
        sync_sequences(cur)
        build_candidates(cur)
        result = report(cur)
        applied = {}
        if args.apply:
            applied = apply_merge(cur, args.batch_code)
            sync_sequences(cur)
            conn.commit()
        else:
            conn.rollback()

        print("mode=" + ("APPLY" if args.apply else "DRY_RUN"))
        for key, value in {**result, **applied}.items():
            print(f"{key}={value}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
