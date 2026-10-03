#!/usr/bin/env python3
import argparse
import pg8000

PG = dict(host='127.0.0.1', port=5432, database='budimas_dev', user='postgres', password='')


def qident(name):
    return '"' + name.replace('"', '""') + '"'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--headers-only', action='store_true')
    parser.add_argument('--batch-label', default='legacy-sales-order-header-hjualsm')
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

        cur.execute('DROP TABLE IF EXISTS tmp_existing_sales_order_codes')
        cur.execute('''
            CREATE TEMP TABLE tmp_existing_sales_order_codes AS
            SELECT btrim(no_order) AS code
            FROM sales_order
            WHERE btrim(coalesce(no_order,'')) <> ''
            UNION
            SELECT btrim(no_faktur) AS code
            FROM sales_order
            WHERE btrim(coalesce(no_faktur,'')) <> ''
        ''')
        cur.execute('CREATE INDEX ON tmp_existing_sales_order_codes (code)')

        cur.execute('DROP TABLE IF EXISTS tmp_legacy_sales_order_headers')
        cur.execute('''
            CREATE TEMP TABLE tmp_legacy_sales_order_headers AS
            WITH customer_map AS (
                SELECT btrim(kode) kode, min(id) id FROM customer
                WHERE btrim(coalesce(kode,''))<>'' GROUP BY btrim(kode)
            ),
            principal_map AS (
                SELECT btrim(kode) kode, min(id) id FROM principal
                WHERE btrim(coalesce(kode,''))<>'' GROUP BY btrim(kode)
            ),
            sales_map AS (
                SELECT btrim(sd.kode_sales) kode, min(s.id) id_sales, min(s.id_user) id_user
                FROM sales_detail sd
                JOIN sales s ON s.id = sd.id_sales
                WHERE btrim(coalesce(sd.kode_sales,''))<>''
                GROUP BY btrim(sd.kode_sales)
            ),
            plafon_map AS (
                SELECT id_customer, id_principal, min(id) id FROM plafon GROUP BY id_customer, id_principal
            ),
            ranked AS (
                SELECT *
                FROM (
                    SELECT h.*,
                           row_number() OVER (PARTITION BY btrim(h.nota) ORDER BY h.source_priority, h.staging_id) rn
                    FROM legacy_transaction_import_server.hjualsm h
                    WHERE btrim(coalesce(h.nota,'')) <> ''
                ) x
                WHERE rn = 1
            ),
            mapped AS (
                SELECT
                    'hjualsm:' || btrim(h.nota) AS legacy_key,
                    btrim(h.nota) AS nota,
                    btrim(h.kodecustomer) AS kodecustomer,
                    btrim(h.kodeprinciple) AS kodeprinciple,
                    btrim(h.kodesales) AS kodesales,
                    h.namasales,
                    h.namacustomer,
                    h.keterangan,
                    NULLIF(h.tanggal,'')::timestamp::date AS tanggal_order,
                    NULLIF(h.tanggal,'')::timestamp::date AS tanggal_faktur,
                    NULLIF(h.tglreal,'')::timestamp::date AS tanggal_terkirim,
                    NULLIF(h.jatuhtempo,'')::timestamp::date AS tanggal_jatuh_tempo,
                    CASE WHEN btrim(coalesce(h.totalpenjualan,'')) ~ '^-?[0-9]+(\\.[0-9]+)?$'
                        THEN btrim(h.totalpenjualan)::numeric ELSE 0 END::double precision AS total_order,
                    CASE WHEN btrim(coalesce(h.totalretur,'')) ~ '^-?[0-9]+(\\.[0-9]+)?$'
                        THEN btrim(h.totalretur)::numeric ELSE 0 END::double precision AS nominal_retur,
                    CASE WHEN btrim(coalesce(h.terbayar,'')) ~ '^-?[0-9]+(\\.[0-9]+)?$'
                        THEN btrim(h.terbayar)::numeric ELSE 0 END::double precision AS terbayar,
                    h.stnota,
                    h.tunai,
                    c.id AS id_customer,
                    pr.id AS id_principal,
                    pr.id_perusahaan,
                    pl.id AS id_plafon,
                    COALESCE(c.id_cabang, u.id_cabang, 5) AS id_cabang,
                    sm.id_sales,
                    COALESCE(sm.id_user, 1) AS id_user,
                    (SELECT COALESCE(MAX(id), 0) FROM sales_order)
                        + row_number() OVER (ORDER BY NULLIF(h.tanggal,'')::timestamp::date, btrim(h.nota)) AS new_sales_order_id,
                    (SELECT COALESCE(MAX(id), 0) FROM faktur)
                        + row_number() OVER (ORDER BY NULLIF(h.tanggal,'')::timestamp::date, btrim(h.nota)) AS new_faktur_id
                FROM ranked h
                LEFT JOIN customer_map cm ON cm.kode=btrim(h.kodecustomer)
                LEFT JOIN customer c ON c.id=cm.id
                LEFT JOIN principal_map pm ON pm.kode=btrim(h.kodeprinciple)
                LEFT JOIN principal pr ON pr.id=pm.id
                LEFT JOIN sales_map sm ON sm.kode=btrim(h.kodesales)
                LEFT JOIN users u ON u.id=sm.id_user
                LEFT JOIN plafon_map pl ON pl.id_customer=c.id AND pl.id_principal=pr.id
            )
            SELECT *
            FROM mapped m
            WHERE id_plafon IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM legacy_transaction_sync.sync_map sm
                WHERE sm.source_table='hjualsm'
                  AND sm.target_table='sales_order'
                  AND sm.legacy_key=m.legacy_key
              )
              AND NOT EXISTS (
                SELECT 1 FROM tmp_existing_sales_order_codes e
                WHERE e.code=m.nota
              )
        ''')
        cur.execute('SELECT COUNT(*), COALESCE(SUM(total_order),0), MIN(tanggal_order), MAX(tanggal_order) FROM tmp_legacy_sales_order_headers')
        row = cur.fetchone()
        print(f'candidate_sales_order_headers={row[0]}')
        print(f'candidate_total_order={row[1]}')
        print(f'candidate_date_range={row[2]}..{row[3]}')

        if not args.apply:
            print('dry_run=true')
            cur.execute('ROLLBACK')
            return

        stamp = args.batch_label.replace('-', '_')[:40]
        backup_so = f'backup_sales_order_{stamp}'[:60]
        backup_faktur = f'backup_faktur_{stamp}'[:60]
        cur.execute(f'CREATE TABLE IF NOT EXISTS {qident(backup_so)} AS TABLE sales_order WITH DATA')
        cur.execute(f'CREATE TABLE IF NOT EXISTS {qident(backup_faktur)} AS TABLE faktur WITH DATA')

        cur.execute('''
            INSERT INTO sales_order (
                id, id_plafon, tanggal_order, tanggal_faktur, tanggal_terkirim, tanggal_jatuh_tempo,
                nama_sales, pic_customer, status_order, total_order, no_order, no_faktur,
                keterangan, id_cabang
            )
            SELECT
                new_sales_order_id, id_plafon, tanggal_order, tanggal_faktur, tanggal_terkirim, tanggal_jatuh_tempo,
                btrim(coalesce(namasales,'')), btrim(coalesce(namacustomer,'')),
                CASE WHEN btrim(coalesce(stnota,'')) IN ('BT','BATAL') THEN -1 ELSE 5 END,
                total_order,
                nota,
                nota,
                'SOURCE:LEGACY_SQLSERVER | ' || legacy_key || ' | CUSTOMER:' || kodecustomer || ' | SALES:' || kodesales || ' | PRINCIPAL:' || kodeprinciple || ' | PAY:' || btrim(coalesce(tunai,'')) || ' | ' || btrim(coalesce(keterangan,'')),
                id_cabang
            FROM tmp_legacy_sales_order_headers
        ''')
        inserted_orders = cur.rowcount

        cur.execute('''
            INSERT INTO faktur (
                id, id_sales_order, no_faktur, nama_fakturist, status_faktur, jenis_faktur,
                subtotal_penjualan, subtotal_diskon, total_penjualan, total_dana_diterima,
                perubahan_ke, pajak, dpp, draft_total_penjualan, nominal_retur
            )
            SELECT
                new_faktur_id, new_sales_order_id, nota, 'LEGACY_SQLSERVER',
                CASE WHEN terbayar >= total_order AND total_order > 0 THEN 6 ELSE 1 END,
                'penjualan',
                total_order, 0, total_order, terbayar,
                0,
                GREATEST(total_order - (total_order / 1.11), 0),
                total_order / 1.11,
                total_order,
                nominal_retur
            FROM tmp_legacy_sales_order_headers
        ''')
        inserted_faktur = cur.rowcount

        cur.execute('''
            INSERT INTO legacy_transaction_sync.sync_map (batch_label, source_table, legacy_key, target_table, target_id)
            SELECT %s, 'hjualsm', legacy_key, 'sales_order', new_sales_order_id
            FROM tmp_legacy_sales_order_headers
            ON CONFLICT (source_table, legacy_key, target_table) DO NOTHING
        ''', (args.batch_label,))
        cur.execute('''
            INSERT INTO legacy_transaction_sync.sync_map (batch_label, source_table, legacy_key, target_table, target_id)
            SELECT %s, 'hjualsm', legacy_key, 'faktur', new_faktur_id
            FROM tmp_legacy_sales_order_headers
            ON CONFLICT (source_table, legacy_key, target_table) DO NOTHING
        ''', (args.batch_label,))

        cur.execute("SELECT setval('sales_order_id_seq', COALESCE((SELECT MAX(id) FROM sales_order),0), true)")
        cur.execute("SELECT setval('faktur_id_seq', COALESCE((SELECT MAX(id) FROM faktur),0), true)")
        conn.commit()
        print(f'inserted_sales_order={inserted_orders}')
        print(f'inserted_faktur={inserted_faktur}')
        print(f'backup_sales_order={backup_so}')
        print(f'backup_faktur={backup_faktur}')
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    main()
