#!/usr/bin/env python3
import argparse
import pg8000

PG = dict(host='127.0.0.1', port=5432, database='budimas_dev', user='postgres', password='')


def qident(name):
    return '"' + name.replace('"', '""') + '"'


def sync_sequence(cur, table_name, column_name):
    cur.execute("""
        SELECT setval(
            COALESCE(
                pg_get_serial_sequence(%s, %s),
                regexp_replace(
                    (SELECT column_default
                     FROM information_schema.columns
                     WHERE table_schema='public'
                       AND table_name=%s
                       AND column_name=%s),
                    '^nextval\\(''([^'']+)''::regclass\\)$',
                    '\\1'
                )
            )::regclass,
            COALESCE((SELECT MAX(id) FROM public.""" + qident(table_name) + """), 0),
            true
        )
    """, (table_name, column_name, table_name, column_name))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--batch-label', default='legacy-kunjungan-sales')
    args = parser.parse_args()

    conn = pg8000.connect(**PG)
    try:
        cur = conn.cursor()
        cur.execute('BEGIN')
        cur.execute('''
            CREATE SCHEMA IF NOT EXISTS legacy_transaction_sync;
            CREATE TABLE IF NOT EXISTS legacy_transaction_sync.sync_map (
                id BIGSERIAL PRIMARY KEY,
                batch_label TEXT NOT NULL,
                source_table TEXT NOT NULL,
                legacy_key TEXT NOT NULL,
                target_table TEXT NOT NULL,
                target_id BIGINT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (source_table, legacy_key, target_table)
            );
            CREATE TABLE IF NOT EXISTS legacy_transaction_sync.kunjungan_sales_location (
                id BIGSERIAL PRIMARY KEY,
                legacy_key TEXT NOT NULL UNIQUE,
                id_sales_kunjungan BIGINT NOT NULL,
                legacy_id TEXT,
                kode_customer TEXT,
                kode_principal TEXT,
                kode_sales TEXT,
                latitude TEXT,
                longitude TEXT,
                tanggal_checkin TEXT,
                tanggal_checkout TEXT,
                checkout TEXT,
                source_system TEXT,
                source_priority INTEGER,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        ''')

        cur.execute('DROP TABLE IF EXISTS tmp_legacy_kunjungan_sales')
        cur.execute('''
            CREATE TEMP TABLE tmp_legacy_kunjungan_sales AS
            WITH ranked AS (
                SELECT *
                FROM (
                    SELECT k.*,
                           'kunjungansales:' || btrim(coalesce(k.id,'')) AS legacy_key,
                           row_number() OVER (
                               PARTITION BY btrim(coalesce(k.id,''))
                               ORDER BY k.source_priority, k.staging_id
                           ) rn
                    FROM legacy_transaction_import_server.kunjungansales k
                    WHERE btrim(coalesce(k.id,'')) <> ''
                      AND k.tanggal ~ '^\\d{4}-\\d{2}-\\d{2}'
                ) x
                WHERE rn = 1
            ),
            plafon_map AS (
                SELECT *
                FROM (
                    SELECT
                        pl.id AS id_plafon,
                        pl.id_customer,
                        pl.id_principal,
                        COALESCE(s.id_user, pl.id_user) AS id_user,
                        row_number() OVER (
                            PARTITION BY pl.id_customer, pl.id_principal
                            ORDER BY
                                CASE WHEN COALESCE(s.id_user, pl.id_user) IS NULL THEN 1 ELSE 0 END,
                                pl.id
                        ) rn
                    FROM plafon pl
                    LEFT JOIN sales s ON s.id = pl.id_sales
                ) x
                WHERE rn = 1
            )
            SELECT
                base.*,
                (SELECT COALESCE(MAX(id),0) FROM sales_kunjungan)
                    + row_number() OVER (ORDER BY base.tanggal, base.legacy_key) AS new_kunjungan_id,
                (SELECT COALESCE(MAX(id),0) FROM sales_kunjungan_detail)
                    + row_number() OVER (ORDER BY base.tanggal, base.legacy_key) AS new_detail_id
            FROM (
                SELECT *
                FROM (
                    SELECT
                        r.legacy_key,
                        r.id AS legacy_id,
                        c.id AS id_customer,
                        pr.id AS id_principal,
                        pm.id_plafon,
                        COALESCE(pm.id_user, legacy_sales.id_user, legacy_user.id) AS id_user,
                        left(r.tanggal, 10)::date AS tanggal,
                        substring(r.tanggal from 12 for 8)::time AS waktu_mulai,
                        CASE
                            WHEN lower(btrim(coalesce(r.checkout,''))) IN ('true','1','t','yes','y')
                             AND r.tanggalcheckout ~ '^\\d{4}-\\d{2}-\\d{2}'
                            THEN substring(r.tanggalcheckout from 12 for 8)::time
                            ELSE NULL
                        END AS waktu_selesai,
                        CASE WHEN lower(btrim(coalesce(r.checkout,''))) IN ('true','1','t','yes','y') THEN 2 ELSE 1 END::smallint AS status,
                        r.kodecustomer,
                        r.kodeprinciple,
                        r.kodesales,
                        r.latitude,
                        r.longitude,
                        r.tanggal AS tanggal_checkin_raw,
                        r.tanggalcheckout AS tanggal_checkout_raw,
                        r.checkout,
                        r.source_system,
                        r.source_priority,
                        row_number() OVER (
                            PARTITION BY r.legacy_key
                            ORDER BY
                                CASE WHEN COALESCE(pm.id_user, legacy_sales.id_user, legacy_user.id) IS NULL THEN 1 ELSE 0 END,
                                c.id,
                                pr.id,
                                pm.id_plafon
                        ) final_rn
                    FROM ranked r
                    JOIN customer c ON btrim(c.kode) = btrim(r.kodecustomer)
                    JOIN principal pr ON btrim(pr.kode) = btrim(r.kodeprinciple)
                    JOIN plafon_map pm ON pm.id_customer = c.id AND pm.id_principal = pr.id
                    LEFT JOIN sales legacy_sales ON legacy_sales.id::text = ltrim(btrim(r.kodesales), '0')
                    LEFT JOIN users legacy_user ON legacy_user.id::text = ltrim(btrim(r.kodesales), '0')
                    WHERE NOT EXISTS (
                        SELECT 1 FROM legacy_transaction_sync.sync_map sm
                        WHERE sm.source_table='kunjungansales'
                          AND sm.target_table='sales_kunjungan'
                          AND sm.legacy_key=r.legacy_key
                    )
                ) dedup
                WHERE final_rn = 1
            ) base
        ''')

        cur.execute('''
            SELECT COUNT(*), MIN(tanggal), MAX(tanggal),
                   COUNT(*) FILTER (WHERE status = 2),
                   COUNT(*) FILTER (WHERE id_user IS NULL)
            FROM tmp_legacy_kunjungan_sales
        ''')
        total, min_date, max_date, checked_out, missing_user = cur.fetchone()
        print(f'candidate_sales_kunjungan={total}')
        print(f'candidate_date_range={min_date}..{max_date}')
        print(f'candidate_checked_out={checked_out}')
        print(f'candidate_missing_id_user={missing_user}')

        if not args.apply:
            print('dry_run=true')
            cur.execute('ROLLBACK')
            return

        stamp = args.batch_label.replace('-', '_')[:42]
        backup_visit = f'backup_sales_kunjungan_{stamp}'[:60]
        backup_detail = f'backup_sales_kunjungan_detail_{stamp}'[:60]
        cur.execute(f'CREATE TABLE IF NOT EXISTS {qident(backup_visit)} AS TABLE sales_kunjungan WITH DATA')
        cur.execute(f'CREATE TABLE IF NOT EXISTS {qident(backup_detail)} AS TABLE sales_kunjungan_detail WITH DATA')

        cur.execute('''
            INSERT INTO sales_kunjungan (
                id, tanggal, waktu_mulai, waktu_selesai, status, id_plafon, id_plafon_jadwal, id_user
            )
            SELECT
                new_kunjungan_id, tanggal, waktu_mulai, waktu_selesai, status, id_plafon, NULL, id_user
            FROM tmp_legacy_kunjungan_sales
        ''')
        inserted_visits = cur.rowcount

        cur.execute('''
            INSERT INTO sales_kunjungan_detail (
                id, id_sales_kunjungan, id_plafon, id_principal, id_customer, id_user,
                status_proses1, status_proses2, status_proses3, status_checkin
            )
            SELECT
                new_detail_id, new_kunjungan_id, id_plafon, id_principal, id_customer, id_user,
                0, 0, 0, 1
            FROM tmp_legacy_kunjungan_sales
        ''')
        inserted_details = cur.rowcount

        cur.execute('''
            INSERT INTO legacy_transaction_sync.kunjungan_sales_location (
                legacy_key, id_sales_kunjungan, legacy_id, kode_customer, kode_principal, kode_sales,
                latitude, longitude, tanggal_checkin, tanggal_checkout, checkout, source_system, source_priority
            )
            SELECT
                legacy_key, new_kunjungan_id, legacy_id, kodecustomer, kodeprinciple, kodesales,
                latitude, longitude, tanggal_checkin_raw, tanggal_checkout_raw, checkout, source_system, source_priority
            FROM tmp_legacy_kunjungan_sales
            ON CONFLICT (legacy_key) DO UPDATE SET
                id_sales_kunjungan = EXCLUDED.id_sales_kunjungan,
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude,
                tanggal_checkin = EXCLUDED.tanggal_checkin,
                tanggal_checkout = EXCLUDED.tanggal_checkout,
                checkout = EXCLUDED.checkout
        ''')
        archived_locations = cur.rowcount

        cur.execute('''
            INSERT INTO legacy_transaction_sync.sync_map (batch_label, source_table, legacy_key, target_table, target_id)
            SELECT %s, 'kunjungansales', legacy_key, 'sales_kunjungan', new_kunjungan_id
            FROM tmp_legacy_kunjungan_sales
            ON CONFLICT (source_table, legacy_key, target_table) DO NOTHING
        ''', (args.batch_label,))

        cur.execute('''
            INSERT INTO legacy_transaction_sync.sync_map (batch_label, source_table, legacy_key, target_table, target_id)
            SELECT %s, 'kunjungansales', legacy_key, 'sales_kunjungan_detail', new_detail_id
            FROM tmp_legacy_kunjungan_sales
            ON CONFLICT (source_table, legacy_key, target_table) DO NOTHING
        ''', (args.batch_label,))

        sync_sequence(cur, 'sales_kunjungan', 'id')
        sync_sequence(cur, 'sales_kunjungan_detail', 'id')
        conn.commit()
        print(f'inserted_sales_kunjungan={inserted_visits}')
        print(f'inserted_sales_kunjungan_detail={inserted_details}')
        print(f'archived_locations={archived_locations}')
        print(f'backup_sales_kunjungan={backup_visit}')
        print(f'backup_sales_kunjungan_detail={backup_detail}')
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
