#!/usr/bin/env python3
import argparse
import pg8000

PG = dict(host='127.0.0.1', port=5432, database='budimas_dev', user='postgres', password='')


def qident(name):
    return '"' + name.replace('"', '""') + '"'


def run(cur, sql):
    cur.execute(sql)
    try:
        return cur.fetchall()
    except Exception:
        return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--batch-label', default='legacy-stockopname-android-20260601-20260718')
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

        # Candidate headers match mobile save shape: one stock_opname per visit/customer/principal/date.
        cur.execute('DROP TABLE IF EXISTS tmp_legacy_stockopname_headers')
        cur.execute('''
            CREATE TEMP TABLE tmp_legacy_stockopname_headers AS
            WITH customer_map AS (
                SELECT btrim(kode) kode, min(id) id
                FROM customer
                WHERE btrim(coalesce(kode,''))<>''
                GROUP BY btrim(kode)
            ),
            principal_map AS (
                SELECT btrim(kode) kode, min(id) id
                FROM principal
                WHERE btrim(coalesce(kode,''))<>''
                GROUP BY btrim(kode)
            ),
            sales_map AS (
                SELECT btrim(sd.kode_sales) kode, min(s.id) id_sales, min(s.id_user) id_user
                FROM sales_detail sd
                JOIN sales s ON s.id = sd.id_sales
                WHERE btrim(coalesce(sd.kode_sales,''))<>''
                GROUP BY btrim(sd.kode_sales)
            ),
            plafon_map AS (
                SELECT id_customer, id_principal, min(id) id
                FROM plafon
                GROUP BY id_customer, id_principal
            ),
            dedup AS (
                SELECT *
                FROM (
                    SELECT s.*,
                           row_number() OVER (
                               PARTITION BY btrim(coalesce(s.tanggalinput,'')),
                                            btrim(coalesce(s.idkunjungan,'')),
                                            btrim(coalesce(s.kodecustomer,'')),
                                            btrim(coalesce(s.kodesales,'')),
                                            btrim(coalesce(s.kodeprinciple,'')),
                                            btrim(coalesce(s.kodebarang,''))
                               ORDER BY s.source_priority, s.staging_id
                           ) rn
                    FROM legacy_transaction_import_server.stokopnameandroid s
                    WHERE btrim(coalesce(s.tanggalinput,'')) <> ''
                ) x
                WHERE rn = 1
            ),
            mapped AS (
                SELECT
                    btrim(coalesce(d.tanggalinput,'')) AS tanggalinput,
                    btrim(coalesce(d.idkunjungan,'')) AS idkunjungan,
                    btrim(coalesce(d.kodecustomer,'')) AS kodecustomer,
                    btrim(coalesce(d.kodesales,'')) AS kodesales,
                    btrim(coalesce(d.kodeprinciple,'')) AS kodeprinciple,
                    c.id AS id_customer,
                    c.id AS customer_id,
                    pr.id AS id_principal,
                    pr.id_perusahaan,
                    COALESCE(c.id_cabang, u.id_cabang, 5) AS id_cabang,
                    sm.id_sales,
                    COALESCE(sm.id_user, 1) AS id_user_input,
                    pl.id AS id_plafon,
                    SUM(COALESCE(NULLIF(d.stokopname,'')::numeric,0) * COALESCE(p.harga_jual,0)) AS total,
                    COUNT(*) AS total_item
                FROM dedup d
                LEFT JOIN customer_map cm ON cm.kode=btrim(d.kodecustomer)
                LEFT JOIN customer c ON c.id=cm.id
                LEFT JOIN principal_map pm ON pm.kode=btrim(d.kodeprinciple)
                LEFT JOIN principal pr ON pr.id=pm.id
                LEFT JOIN sales_map sm ON sm.kode=btrim(d.kodesales)
                LEFT JOIN users u ON u.id=sm.id_user
                LEFT JOIN plafon_map pl ON pl.id_customer=c.id AND pl.id_principal=pr.id
                LEFT JOIN produk p ON btrim(p.kode_sku)=btrim(d.kodebarang)
                WHERE c.id IS NOT NULL AND pr.id IS NOT NULL AND sm.id_sales IS NOT NULL AND pl.id IS NOT NULL
                GROUP BY btrim(coalesce(d.tanggalinput,'')), btrim(coalesce(d.idkunjungan,'')),
                         btrim(coalesce(d.kodecustomer,'')), btrim(coalesce(d.kodesales,'')),
                         btrim(coalesce(d.kodeprinciple,'')), c.id, pr.id, pr.id_perusahaan,
                         COALESCE(c.id_cabang, u.id_cabang, 5), sm.id_sales, COALESCE(sm.id_user, 1), pl.id
            )
            SELECT
                'stokopnameandroid:' || tanggalinput || ':' || idkunjungan || ':' || kodecustomer || ':' || kodesales || ':' || kodeprinciple AS legacy_key,
                tanggalinput::date AS tanggal_so,
                idkunjungan,
                kodecustomer,
                kodesales,
                kodeprinciple,
                id_customer,
                id_principal,
                id_perusahaan,
                id_cabang,
                id_sales,
                id_user_input,
                id_plafon,
                total,
                total_item,
                (SELECT COALESCE(MAX(id_stock_opname), 0) FROM stock_opname)
                    + row_number() OVER (ORDER BY tanggalinput, idkunjungan, kodecustomer, kodesales, kodeprinciple) AS new_id
            FROM mapped m
            WHERE NOT EXISTS (
                SELECT 1 FROM legacy_transaction_sync.sync_map sm
                WHERE sm.source_table='stokopnameandroid'
                  AND sm.target_table='stock_opname'
                  AND sm.legacy_key='stokopnameandroid:' || m.tanggalinput || ':' || m.idkunjungan || ':' || m.kodecustomer || ':' || m.kodesales || ':' || m.kodeprinciple
            )
        ''')
        cur.execute('SELECT COUNT(*), COALESCE(SUM(total_item),0), COALESCE(SUM(total),0) FROM tmp_legacy_stockopname_headers')
        header_count, detail_rows_grouped, total_value = cur.fetchone()
        print(f'candidate_headers={header_count}')
        print(f'candidate_detail_rows={detail_rows_grouped}')
        print(f'candidate_total_value={total_value}')

        cur.execute('DROP TABLE IF EXISTS tmp_legacy_stockopname_details')
        cur.execute('''
            CREATE TEMP TABLE tmp_legacy_stockopname_details AS
            WITH produk_map AS (
                SELECT btrim(kode_sku) kode, min(id) id
                FROM produk
                WHERE btrim(coalesce(kode_sku,''))<>''
                GROUP BY btrim(kode_sku)
            ),
            dedup AS (
                SELECT *
                FROM (
                    SELECT s.*,
                           row_number() OVER (
                               PARTITION BY btrim(coalesce(s.tanggalinput,'')),
                                            btrim(coalesce(s.idkunjungan,'')),
                                            btrim(coalesce(s.kodecustomer,'')),
                                            btrim(coalesce(s.kodesales,'')),
                                            btrim(coalesce(s.kodeprinciple,'')),
                                            btrim(coalesce(s.kodebarang,''))
                               ORDER BY s.source_priority, s.staging_id
                           ) rn
                    FROM legacy_transaction_import_server.stokopnameandroid s
                ) x
                WHERE rn = 1
            )
            SELECT
                h.new_id AS id_stock_opname,
                pm.id AS id_produk,
                COALESCE(NULLIF(d.stokopname,'')::numeric,0)::integer AS stok,
                COALESCE(p.harga_jual,0)::double precision AS harga,
                (COALESCE(NULLIF(d.stokopname,'')::numeric,0) * COALESCE(p.harga_jual,0))::double precision AS subtotal,
                ('LEGACY_ID:' || btrim(coalesce(d.id,'')) || ' | KUNJUNGAN:' || btrim(coalesce(d.idkunjungan,''))) AS ket_produk
            FROM dedup d
            JOIN tmp_legacy_stockopname_headers h
              ON h.tanggal_so = d.tanggalinput::date
             AND h.idkunjungan = btrim(coalesce(d.idkunjungan,''))
             AND h.kodecustomer = btrim(coalesce(d.kodecustomer,''))
             AND h.kodesales = btrim(coalesce(d.kodesales,''))
             AND h.kodeprinciple = btrim(coalesce(d.kodeprinciple,''))
            JOIN produk_map pm ON pm.kode=btrim(d.kodebarang)
            JOIN produk p ON p.id=pm.id
        ''')
        cur.execute('ALTER TABLE tmp_legacy_stockopname_details ADD COLUMN new_detail_id BIGINT')
        cur.execute('''
            WITH numbered AS (
                SELECT ctid,
                       (SELECT COALESCE(MAX(id_stock_opname_detail), 0) FROM stock_opname_detail)
                           + row_number() OVER (ORDER BY id_stock_opname, id_produk, ket_produk) AS generated_id
                FROM tmp_legacy_stockopname_details
            )
            UPDATE tmp_legacy_stockopname_details d
            SET new_detail_id = numbered.generated_id
            FROM numbered
            WHERE d.ctid = numbered.ctid
        ''')
        cur.execute('SELECT COUNT(*) FROM tmp_legacy_stockopname_details')
        detail_count = cur.fetchone()[0]
        print(f'insertable_details={detail_count}')

        if not args.apply:
            print('dry_run=true')
            cur.execute('ROLLBACK')
            return

        stamp = args.batch_label.replace('-', '_')
        backup_so = f'backup_stock_opname_{stamp}'[:60]
        backup_sod = f'backup_stock_opname_detail_{stamp}'[:60]
        cur.execute(f'CREATE TABLE IF NOT EXISTS {qident(backup_so)} AS TABLE stock_opname WITH DATA')
        cur.execute(f'CREATE TABLE IF NOT EXISTS {qident(backup_sod)} AS TABLE stock_opname_detail WITH DATA')

        cur.execute('''
            INSERT INTO stock_opname (
                id_stock_opname, id_perusahaan, id_cabang, id_principal, kode_so,
                total, ket_so, tanggal_so, status_so, id_user_input, total_selisih
            )
            SELECT
                new_id, id_perusahaan, id_cabang, id_principal,
                'LEG-SOA-' || to_char(tanggal_so, 'YYYYMMDD') || '-' || left(md5(legacy_key), 10),
                total,
                'SOURCE:LEGACY_SQLSERVER | ' || legacy_key || ' | CUSTOMER:' || kodecustomer || ' | SALES:' || kodesales || ' | PRINCIPAL:' || kodeprinciple,
                tanggal_so,
                'done',
                id_user_input,
                total
            FROM tmp_legacy_stockopname_headers
        ''')
        inserted_headers = cur.rowcount

        cur.execute('''
            INSERT INTO legacy_transaction_sync.sync_map (
                batch_label, source_table, legacy_key, target_table, target_id
            )
            SELECT %s, 'stokopnameandroid', legacy_key, 'stock_opname', new_id
            FROM tmp_legacy_stockopname_headers
            ON CONFLICT (source_table, legacy_key, target_table) DO NOTHING
        ''', (args.batch_label,))

        cur.execute('''
            INSERT INTO stock_opname_detail (
                id_stock_opname_detail, id_stock_opname, id_produk, uom_1, uom_2, uom_3,
                stok, stok_sistem, harga, bad_stock, subtotal, subtotal_selisih, ket_produk
            )
            SELECT
                new_detail_id, id_stock_opname, id_produk, stok, 0, 0,
                stok, 0, harga, 0, subtotal, subtotal, ket_produk
            FROM tmp_legacy_stockopname_details
        ''')
        inserted_details = cur.rowcount

        cur.execute("SELECT setval('stock_opname_id_stock_opname_seq', COALESCE((SELECT MAX(id_stock_opname) FROM stock_opname),0), true)")
        cur.execute("SELECT setval('stock_opname_detail_id_stock_opname_detail_seq', COALESCE((SELECT MAX(id_stock_opname_detail) FROM stock_opname_detail),0), true)")
        conn.commit()
        print(f'inserted_headers={inserted_headers}')
        print(f'inserted_details={inserted_details}')
        print(f'backup_stock_opname={backup_so}')
        print(f'backup_stock_opname_detail={backup_sod}')
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    main()
