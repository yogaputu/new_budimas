#!/usr/bin/env python3
import argparse
import pg8000

PG = dict(host='127.0.0.1', port=5432, database='budimas_dev', user='postgres', password='')

NUMERIC_RE = "^-?[0-9]+(\\.[0-9]+)?$"


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
    parser.add_argument('--batch-label', default='legacy-payment-dbayarsm')
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
        ''')

        cur.execute('DROP TABLE IF EXISTS tmp_legacy_payments_dbayarsm')
        cur.execute(f'''
            CREATE TEMP TABLE tmp_legacy_payments_dbayarsm AS
            WITH ranked AS (
                SELECT *
                FROM (
                    SELECT d.*,
                           'dbayarsm:' || btrim(coalesce(d.nokwitansi,'')) || ':' ||
                               btrim(coalesce(d.nota,'')) || ':' ||
                               btrim(coalesce(d.tanggal,'')) || ':' ||
                               btrim(coalesce(d.jumlahbayar,'')) AS legacy_key,
                           row_number() OVER (
                               PARTITION BY
                                   btrim(coalesce(d.nokwitansi,'')),
                                   btrim(coalesce(d.nota,'')),
                                   btrim(coalesce(d.tanggal,'')),
                                   btrim(coalesce(d.jumlahbayar,''))
                               ORDER BY d.source_priority, d.staging_id
                           ) rn
                    FROM legacy_transaction_import_server.dbayarsm d
                    WHERE btrim(coalesce(d.nota,'')) <> ''
                      AND btrim(coalesce(d.nokwitansi,'')) <> ''
                      AND btrim(coalesce(d.jumlahbayar,'')) ~ '{NUMERIC_RE}'
                      AND btrim(d.jumlahbayar)::numeric > 0
                ) x
                WHERE rn = 1
            ),
            faktur_map AS (
                SELECT btrim(f.no_faktur) AS no_faktur, min(f.id) AS id_faktur, min(f.id_sales_order) AS id_sales_order
                FROM faktur f
                WHERE btrim(coalesce(f.no_faktur,'')) <> ''
                GROUP BY btrim(f.no_faktur)
            )
            SELECT
                r.legacy_key,
                fm.id_faktur,
                so.id AS id_sales_order,
                pl.id_sales,
                CASE WHEN r.tanggal ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}' THEN left(r.tanggal, 10)::date ELSE so.tanggal_order END AS tanggal_input,
                btrim(r.jumlahbayar)::numeric::double precision AS jumlah_setoran,
                CASE
                    WHEN upper(coalesce(r.nobukti,'')) LIKE '%BANK%'
                      OR upper(coalesce(r.nobukti,'')) LIKE '%TRANSFER%'
                      OR upper(coalesce(r.nobukti,'')) LIKE '%TF%'
                      OR upper(coalesce(r.nobukti,'')) LIKE '%GIRO%'
                    THEN 2
                    ELSE 1
                END::integer AS tipe_setoran,
                NULLIF(btrim(r.nobukti), '') AS bukti_transfer,
                NULLIF(btrim(r.keterangan), '') AS keterangan,
                NULLIF(btrim(r.namapembayar), '') AS nama_pj,
                (SELECT COALESCE(MAX(id),0) FROM setoran_customer)
                    + row_number() OVER (ORDER BY so.id, r.legacy_key) AS new_setoran_customer_id,
                (SELECT COALESCE(MAX(id),0) FROM setoran)
                    + row_number() OVER (ORDER BY so.id, r.legacy_key) AS new_setoran_id
            FROM ranked r
            JOIN faktur_map fm ON fm.no_faktur = btrim(r.nota)
            JOIN sales_order so ON so.id = fm.id_sales_order
            LEFT JOIN plafon pl ON pl.id = so.id_plafon
            WHERE NOT EXISTS (
                SELECT 1 FROM legacy_transaction_sync.sync_map sm
                WHERE sm.source_table='dbayarsm'
                  AND sm.target_table='setoran_customer'
                  AND sm.legacy_key=r.legacy_key
            )
        ''')

        cur.execute('''
            SELECT COUNT(*), COALESCE(SUM(jumlah_setoran),0), MIN(tanggal_input), MAX(tanggal_input)
            FROM tmp_legacy_payments_dbayarsm
        ''')
        total, amount, min_date, max_date = cur.fetchone()
        print(f'candidate_setoran_customer={total}')
        print(f'candidate_amount={amount}')
        print(f'candidate_date_range={min_date}..{max_date}')

        if not args.apply:
            print('dry_run=true')
            cur.execute('ROLLBACK')
            return

        stamp = args.batch_label.replace('-', '_')[:42]
        backup_sc = f'backup_setoran_customer_{stamp}'[:60]
        backup_s = f'backup_setoran_{stamp}'[:60]
        cur.execute(f'CREATE TABLE IF NOT EXISTS {qident(backup_sc)} AS TABLE setoran_customer WITH DATA')
        cur.execute(f'CREATE TABLE IF NOT EXISTS {qident(backup_s)} AS TABLE setoran WITH DATA')

        cur.execute('''
            INSERT INTO setoran_customer (
                id, id_sales, id_sales_order, jumlah_setoran, tipe_setoran, tanggal_input, is_rekap
            )
            SELECT
                new_setoran_customer_id, id_sales, id_sales_order, jumlah_setoran, tipe_setoran, tanggal_input, 1
            FROM tmp_legacy_payments_dbayarsm
        ''')
        inserted_sc = cur.rowcount

        cur.execute('''
            INSERT INTO setoran (
                id, id_sales_order, draft_tanggal_input, draft_jumlah_setor, draft_tipe_setor,
                keterangan, nama_pj, jumlah_setoran, tipe_setoran, tanggal_setoran_diterima,
                keterangan_kasir, nama_kasir, status_audit, nama_auditor, metode_pembayaran,
                bukti_transfer, status_setoran, biaya_lainnya, ket_biaya_lainnya, setoran_bersih,
                id_setoran_customer, pj_setoran
            )
            SELECT
                new_setoran_id, id_sales_order, tanggal_input, jumlah_setoran, tipe_setoran,
                keterangan, COALESCE(nama_pj, 'LEGACY'), jumlah_setoran, tipe_setoran, tanggal_input,
                'Migrasi pembayaran legacy DBayarSM', 'LEGACY', 1, 'LEGACY',
                CASE WHEN tipe_setoran = 2 THEN 'Non Tunai' ELSE 'Tunai' END,
                bukti_transfer, 3, 0, NULL, jumlah_setoran,
                new_setoran_customer_id, 1
            FROM tmp_legacy_payments_dbayarsm
        ''')
        inserted_s = cur.rowcount

        cur.execute('''
            INSERT INTO legacy_transaction_sync.sync_map (batch_label, source_table, legacy_key, target_table, target_id)
            SELECT %s, 'dbayarsm', legacy_key, 'setoran_customer', new_setoran_customer_id
            FROM tmp_legacy_payments_dbayarsm
            ON CONFLICT (source_table, legacy_key, target_table) DO NOTHING
        ''', (args.batch_label,))

        cur.execute('''
            INSERT INTO legacy_transaction_sync.sync_map (batch_label, source_table, legacy_key, target_table, target_id)
            SELECT %s, 'dbayarsm', legacy_key, 'setoran', new_setoran_id
            FROM tmp_legacy_payments_dbayarsm
            ON CONFLICT (source_table, legacy_key, target_table) DO NOTHING
        ''', (args.batch_label,))

        sync_sequence(cur, 'setoran_customer', 'id')
        sync_sequence(cur, 'setoran', 'id')
        conn.commit()
        print(f'inserted_setoran_customer={inserted_sc}')
        print(f'inserted_setoran={inserted_s}')
        print(f'backup_setoran_customer={backup_sc}')
        print(f'backup_setoran={backup_s}')
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
