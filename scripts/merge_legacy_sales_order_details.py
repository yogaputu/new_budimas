#!/usr/bin/env python3
import argparse
import pg8000

PG = dict(host='127.0.0.1', port=5432, database='budimas_dev', user='postgres', password='')


def qident(name):
    return '"' + name.replace('"', '""') + '"'


NUMERIC_RE = "^-?[0-9]+(\\.[0-9]+)?$"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--batch-label', default='legacy-sales-order-detail-djualsm')
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

        cur.execute('DROP TABLE IF EXISTS tmp_legacy_sales_order_details')
        cur.execute(f'''
            CREATE TEMP TABLE tmp_legacy_sales_order_details AS
            WITH produk_map AS (
                SELECT btrim(kode_sku) kode, min(id) id
                FROM produk
                WHERE btrim(coalesce(kode_sku,'')) <> ''
                GROUP BY btrim(kode_sku)
            ),
            mapped_order AS (
                SELECT replace(legacy_key, 'hjualsm:', '') AS nota, target_id AS id_sales_order
                FROM legacy_transaction_sync.sync_map
                WHERE source_table='hjualsm' AND target_table='sales_order'
            ),
            ranked AS (
                SELECT *
                FROM (
                    SELECT d.*,
                           'djualsm:' || btrim(coalesce(d.nota,'')) || ':' || btrim(coalesce(d.urut,'')) || ':' || btrim(coalesce(d.kodestok,'')) AS legacy_key,
                           row_number() OVER (
                               PARTITION BY btrim(coalesce(d.nota,'')), btrim(coalesce(d.urut,'')), btrim(coalesce(d.kodestok,''))
                               ORDER BY d.source_priority, d.staging_id
                           ) rn
                    FROM legacy_transaction_import_server.djualsm d
                    WHERE btrim(coalesce(d.nota,'')) <> ''
                      AND btrim(coalesce(d.kodestok,'')) <> ''
                ) x
                WHERE rn=1
            )
            SELECT
                r.legacy_key,
                mo.id_sales_order,
                p.id AS id_produk,
                CASE WHEN btrim(coalesce(r.harga,'')) ~ '{NUMERIC_RE}' THEN btrim(r.harga)::numeric ELSE 0 END::double precision AS hargaorder,
                CASE WHEN btrim(coalesce(r.unit,'')) ~ '{NUMERIC_RE}' THEN btrim(r.unit)::numeric ELSE 0 END::integer AS karton_order,
                0::integer AS box_order,
                CASE WHEN btrim(coalesce(r.satuan,'')) ~ '{NUMERIC_RE}' THEN btrim(r.satuan)::numeric ELSE 0 END::integer AS pieces_order,
                CASE WHEN btrim(coalesce(r.jumlahharga,'')) ~ '{NUMERIC_RE}' THEN btrim(r.jumlahharga)::numeric ELSE 0 END::double precision AS subtotalorder,
                CASE WHEN btrim(coalesce(r.jumlahharga,'')) ~ '{NUMERIC_RE}' THEN btrim(r.jumlahharga)::numeric ELSE 0 END::integer AS subtotaldelivered,
                CASE WHEN btrim(coalesce(r.discrp,'')) ~ '{NUMERIC_RE}' THEN btrim(r.discrp)::numeric ELSE 0 END::double precision AS total_nilai_discount,
                CASE WHEN btrim(coalesce(r.disc1,'')) ~ '{NUMERIC_RE}' THEN btrim(r.disc1)::numeric ELSE 0 END::integer AS total_persen_diskon,
                (SELECT COALESCE(MAX(id),0) FROM sales_order_detail)
                    + row_number() OVER (ORDER BY mo.id_sales_order, btrim(coalesce(r.urut,'')), p.id, r.legacy_key) AS new_detail_id
            FROM ranked r
            JOIN mapped_order mo ON mo.nota=btrim(r.nota)
            JOIN produk_map p ON p.kode=btrim(r.kodestok)
            WHERE NOT EXISTS (
                SELECT 1 FROM legacy_transaction_sync.sync_map sm
                WHERE sm.source_table='djualsm'
                  AND sm.target_table='sales_order_detail'
                  AND sm.legacy_key=r.legacy_key
            )
        ''')

        cur.execute('''
            SELECT COUNT(*), COALESCE(SUM(subtotalorder),0), MIN(id_sales_order), MAX(id_sales_order)
            FROM tmp_legacy_sales_order_details
        ''')
        total, subtotal, min_order, max_order = cur.fetchone()
        print(f'candidate_sales_order_details={total}')
        print(f'candidate_subtotal={subtotal}')
        print(f'candidate_sales_order_id_range={min_order}..{max_order}')

        if not args.apply:
            print('dry_run=true')
            cur.execute('ROLLBACK')
            return

        stamp = args.batch_label.replace('-', '_')[:42]
        backup_detail = f'backup_sales_order_detail_{stamp}'[:60]
        cur.execute(f'CREATE TABLE IF NOT EXISTS {qident(backup_detail)} AS TABLE sales_order_detail WITH DATA')

        cur.execute('''
            INSERT INTO sales_order_detail (
                id, hargaorder, subtotaldelivered, is_bonus, id_sales_order, id_produk,
                pieces_order, box_order, karton_order,
                pieces_booked, box_booked, karton_booked,
                pieces_picked, box_picked, karton_picked,
                pieces_shipped, box_shipped, karton_shipped,
                pieces_delivered, box_delivered, karton_delivered,
                subtotalorder, total_nilai_discount, total_persen_diskon
            )
            SELECT
                new_detail_id, hargaorder, subtotaldelivered, 0, id_sales_order, id_produk,
                pieces_order, box_order, karton_order,
                pieces_order, box_order, karton_order,
                pieces_order, box_order, karton_order,
                pieces_order, box_order, karton_order,
                pieces_order, box_order, karton_order,
                subtotalorder, total_nilai_discount, total_persen_diskon
            FROM tmp_legacy_sales_order_details
        ''')
        inserted_details = cur.rowcount

        cur.execute('''
            INSERT INTO legacy_transaction_sync.sync_map (batch_label, source_table, legacy_key, target_table, target_id)
            SELECT %s, 'djualsm', legacy_key, 'sales_order_detail', new_detail_id
            FROM tmp_legacy_sales_order_details
            ON CONFLICT (source_table, legacy_key, target_table) DO NOTHING
        ''', (args.batch_label,))

        cur.execute("""
            SELECT setval(
                COALESCE(
                    pg_get_serial_sequence('sales_order_detail','id'),
                    regexp_replace(
                        (SELECT column_default
                         FROM information_schema.columns
                         WHERE table_schema='public'
                           AND table_name='sales_order_detail'
                           AND column_name='id'),
                        '^nextval\\(''([^'']+)''::regclass\\)$',
                        '\\1'
                    )
                )::regclass,
                COALESCE((SELECT MAX(id) FROM sales_order_detail),0),
                true
            )
        """)
        conn.commit()
        print(f'inserted_sales_order_details={inserted_details}')
        print(f'backup_sales_order_detail={backup_detail}')
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    main()
