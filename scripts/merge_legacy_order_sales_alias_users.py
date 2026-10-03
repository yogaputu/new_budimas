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
    for table, pk in [("users", "id"), ("sales", "id")]:
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


def build_placeholder_updates(cur):
    cur.execute("DROP TABLE IF EXISTS tmp_legacy_sales_placeholder_updates")
    cur.execute(
        """
        CREATE TEMP TABLE tmp_legacy_sales_placeholder_updates AS
        WITH latest_name AS (
            SELECT DISTINCT ON (upper(btrim(h.kodesales)))
                btrim(h.kodesales) AS kode_sales,
                btrim(h.namasales) AS nama_sales,
                h.source_system,
                h.source_priority,
                left(h.tanggal, 10)::date AS tanggal_terakhir
            FROM legacy_transaction_import_server.hjualsm h
            WHERE btrim(coalesce(h.kodesales, '')) <> ''
              AND btrim(coalesce(h.namasales, '')) <> ''
              AND upper(btrim(h.namasales)) <> 'VACANT'
              AND h.tanggal ~ '^\\d{4}-\\d{2}-\\d{2}'
            ORDER BY
                upper(btrim(h.kodesales)),
                left(h.tanggal, 10)::date DESC,
                h.source_priority,
                h.staging_id DESC
        )
        SELECT
            sd.kode_sales,
            u.id AS id_user,
            u.nama AS old_nama,
            l.nama_sales AS new_nama,
            l.source_system,
            l.source_priority
        FROM sales_detail sd
        JOIN sales s ON s.id = sd.id_sales
        JOIN users u ON u.id = s.id_user
        JOIN latest_name l ON upper(l.kode_sales) = upper(btrim(sd.kode_sales))
        WHERE (
            upper(btrim(coalesce(u.nama, ''))) = 'VACANT'
            OR upper(btrim(coalesce(u.nama, ''))) = upper('LEGACY SALES ' || btrim(sd.kode_sales))
        )
          AND upper(btrim(coalesce(u.nama, ''))) <> upper(btrim(l.nama_sales))
        """
    )


def build_alias_candidates(cur):
    cur.execute("DROP TABLE IF EXISTS tmp_legacy_sales_alias_candidates")
    cur.execute(
        """
        CREATE TEMP TABLE tmp_legacy_sales_alias_candidates AS
        WITH raw AS (
            SELECT
                btrim(h.kodesales) AS kode_sales,
                btrim(h.namasales) AS nama_sales,
                h.source_system,
                h.source_priority,
                h.kodeprinciple,
                so.id_cabang,
                count(*) AS order_count
            FROM legacy_transaction_import_server.hjualsm h
            LEFT JOIN sales_order so ON btrim(so.no_order) = btrim(h.nota)
            WHERE btrim(coalesce(h.kodesales, '')) <> ''
              AND btrim(coalesce(h.namasales, '')) <> ''
              AND upper(btrim(h.namasales)) <> 'VACANT'
            GROUP BY
                btrim(h.kodesales),
                btrim(h.namasales),
                h.source_system,
                h.source_priority,
                h.kodeprinciple,
                so.id_cabang
        ),
        names AS (
            SELECT kode_sales, nama_sales, sum(order_count) AS total_orders
            FROM raw
            GROUP BY kode_sales, nama_sales
        ),
        missing_names AS (
            SELECT n.*
            FROM names n
            LEFT JOIN users u ON upper(btrim(u.nama)) = upper(n.nama_sales)
            WHERE u.id IS NULL
        ),
        source_pick AS (
            SELECT DISTINCT ON (upper(r.kode_sales), upper(r.nama_sales))
                r.kode_sales,
                r.nama_sales,
                r.source_system,
                r.source_priority
            FROM raw r
            JOIN missing_names m
              ON upper(m.kode_sales) = upper(r.kode_sales)
             AND upper(m.nama_sales) = upper(r.nama_sales)
            ORDER BY upper(r.kode_sales), upper(r.nama_sales), r.source_priority, r.order_count DESC
        ),
        principal_pick AS (
            SELECT DISTINCT ON (upper(r.kode_sales), upper(r.nama_sales))
                r.kode_sales,
                r.nama_sales,
                pr.id AS id_principal,
                pr.id_perusahaan
            FROM raw r
            JOIN missing_names m
              ON upper(m.kode_sales) = upper(r.kode_sales)
             AND upper(m.nama_sales) = upper(r.nama_sales)
            LEFT JOIN principal pr ON upper(btrim(pr.kode)) = upper(btrim(r.kodeprinciple))
            ORDER BY
                upper(r.kode_sales),
                upper(r.nama_sales),
                CASE WHEN pr.id IS NULL THEN 1 ELSE 0 END,
                r.order_count DESC,
                pr.id
        ),
        cabang_pick AS (
            SELECT DISTINCT ON (upper(r.kode_sales), upper(r.nama_sales))
                r.kode_sales,
                r.nama_sales,
                cb.id AS id_cabang,
                cb.id_perusahaan
            FROM raw r
            JOIN missing_names m
              ON upper(m.kode_sales) = upper(r.kode_sales)
             AND upper(m.nama_sales) = upper(r.nama_sales)
            LEFT JOIN cabang cb ON cb.id = r.id_cabang
            ORDER BY
                upper(r.kode_sales),
                upper(r.nama_sales),
                CASE WHEN cb.id IS NULL THEN 1 ELSE 0 END,
                r.order_count DESC,
                cb.id
        ),
        access_pick AS (
            SELECT
                r.kode_sales,
                r.nama_sales,
                string_agg(DISTINCT cb.id::text, ',' ORDER BY cb.id::text) FILTER (WHERE cb.id IS NOT NULL) AS id_cabang_list,
                string_agg(DISTINCT cb.id_perusahaan::text, ',' ORDER BY cb.id_perusahaan::text) FILTER (WHERE cb.id_perusahaan IS NOT NULL) AS id_perusahaan_list
            FROM raw r
            JOIN missing_names m
              ON upper(m.kode_sales) = upper(r.kode_sales)
             AND upper(m.nama_sales) = upper(r.nama_sales)
            LEFT JOIN cabang cb ON cb.id = r.id_cabang
            GROUP BY r.kode_sales, r.nama_sales
        )
        SELECT
            m.kode_sales,
            m.nama_sales,
            lower(regexp_replace(m.kode_sales, '[^0-9A-Za-z]+', '_', 'g')) AS safe_code,
            lower(regexp_replace(left(m.nama_sales, 40), '[^0-9A-Za-z]+', '_', 'g')) AS safe_name,
            sp.source_system,
            sp.source_priority,
            pp.id_principal,
            COALESCE(cp.id_cabang, 5) AS id_cabang,
            COALESCE(cp.id_perusahaan, pp.id_perusahaan, 1) AS id_perusahaan,
            COALESCE(ap.id_cabang_list, COALESCE(cp.id_cabang, 5)::text) AS id_cabang_list,
            COALESCE(ap.id_perusahaan_list, COALESCE(cp.id_perusahaan, pp.id_perusahaan, 1)::text) AS id_perusahaan_list,
            m.total_orders
        FROM missing_names m
        JOIN source_pick sp
          ON upper(sp.kode_sales) = upper(m.kode_sales)
         AND upper(sp.nama_sales) = upper(m.nama_sales)
        LEFT JOIN principal_pick pp
          ON upper(pp.kode_sales) = upper(m.kode_sales)
         AND upper(pp.nama_sales) = upper(m.nama_sales)
        LEFT JOIN cabang_pick cp
          ON upper(cp.kode_sales) = upper(m.kode_sales)
         AND upper(cp.nama_sales) = upper(m.nama_sales)
        LEFT JOIN access_pick ap
          ON upper(ap.kode_sales) = upper(m.kode_sales)
         AND upper(ap.nama_sales) = upper(m.nama_sales)
        """
    )


def report(cur):
    cur.execute("SELECT count(*) FROM tmp_legacy_sales_placeholder_updates")
    placeholder_updates = cur.fetchone()[0]
    cur.execute(
        """
        SELECT
            count(*),
            count(*) FILTER (WHERE id_principal IS NULL),
            coalesce(sum(total_orders), 0)
        FROM tmp_legacy_sales_alias_candidates
        """
    )
    aliases, missing_principal, covered_orders = cur.fetchone()
    return {
        "placeholder_updates": placeholder_updates,
        "alias_candidates": aliases,
        "alias_missing_principal": missing_principal,
        "alias_covered_orders": covered_orders,
    }


def apply_merge(cur, batch_code):
    cur.execute(
        """
        UPDATE users u
        SET nama = LEFT(p.new_nama, 40)
        FROM tmp_legacy_sales_placeholder_updates p
        WHERE u.id = p.id_user
        """
    )
    updated_placeholders = cur.rowcount

    cur.execute(
        """
        INSERT INTO legacy_master_merge_audit (
            batch_code, target_table, action, source_system,
            source_priority, legacy_code, target_id, message
        )
        SELECT
            %s, 'users', 'update_placeholder_name', source_system,
            source_priority, kode_sales, id_user::text,
            'Updated placeholder sales name from legacy order header: ' || old_nama || ' -> ' || new_nama
        FROM tmp_legacy_sales_placeholder_updates
        """,
        (batch_code,),
    )

    cur.execute(
        """
        INSERT INTO users (
            nama, email, telepon, id_jabatan, id_cabang, username, password,
            alamat, id_perusahaan, id_cabang_list, id_perusahaan_list
        )
        SELECT
            LEFT(c.nama_sales, 40),
            LEFT('sales_alias_' || c.safe_code || '_' || c.safe_name || '@migration.local', 100),
            NULL,
            4,
            c.id_cabang,
            LEFT('oa_' || md5(c.kode_sales || ':' || c.nama_sales), 25),
            %s,
            'Legacy sales name alias from order header',
            c.id_perusahaan,
            c.id_cabang_list,
            c.id_perusahaan_list
        FROM tmp_legacy_sales_alias_candidates c
        LEFT JOIN users u ON upper(btrim(u.nama)) = upper(c.nama_sales)
        LEFT JOIN users ux ON ux.username = LEFT('oa_' || md5(c.kode_sales || ':' || c.nama_sales), 25)
        WHERE u.id IS NULL
          AND ux.id IS NULL
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
        FROM tmp_legacy_sales_alias_candidates c
        JOIN users u ON upper(btrim(u.nama)) = upper(c.nama_sales)
        LEFT JOIN sales s
          ON s.id_user = u.id
         AND s.id_principal IS NOT DISTINCT FROM c.id_principal
        WHERE s.id IS NULL
        """
    )
    inserted_sales = cur.rowcount

    cur.execute(
        """
        INSERT INTO legacy_master_merge_audit (
            batch_code, target_table, action, source_system,
            source_priority, legacy_code, target_id, message
        )
        SELECT
            %s, 'users', 'insert_sales_name_alias', c.source_system,
            c.source_priority, c.kode_sales, u.id::text,
            'Inserted legacy sales name alias from order header'
        FROM tmp_legacy_sales_alias_candidates c
        JOIN users u ON upper(btrim(u.nama)) = upper(c.nama_sales)
        """,
        (batch_code,),
    )

    return {
        "updated_placeholders": updated_placeholders,
        "inserted_alias_users": inserted_users,
        "inserted_alias_sales": inserted_sales,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--batch-code", default="legacy-order-sales-alias-users-20260720")
    args = parser.parse_args()

    conn = pg8000.connect(**PG)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")
        ensure_audit(cur)
        sync_sequences(cur)
        build_placeholder_updates(cur)
        build_alias_candidates(cur)
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
