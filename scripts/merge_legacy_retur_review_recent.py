#!/usr/bin/env python3
import argparse
import datetime as dt
import pg8000

PG = dict(host='127.0.0.1', port=5432, database='budimas_dev', user='postgres', password='')
NUMERIC_RE = "^-?[0-9]+(\\.[0-9]+)?$"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--min-date', default='2026-07-20')
    parser.add_argument('--max-date')
    parser.add_argument('--batch-label', default='legacy-retur-review-recent')
    args = parser.parse_args()
    max_date = args.max_date or dt.date.today().isoformat()

    conn = pg8000.connect(**PG)
    try:
        cur = conn.cursor()
        cur.execute('BEGIN')
        cur.execute('''
            CREATE SCHEMA IF NOT EXISTS legacy_transaction_sync;
            CREATE TABLE IF NOT EXISTS legacy_transaction_sync.retur_sales_review (
                id BIGSERIAL PRIMARY KEY,
                batch_label TEXT NOT NULL,
                legacy_key TEXT NOT NULL UNIQUE,
                source_system TEXT,
                source_priority INTEGER,
                tanggal_retur DATE,
                kode_retur TEXT,
                kode_customer TEXT,
                nama_customer_legacy TEXT,
                id_customer INTEGER,
                kode_principal TEXT,
                nama_principal_legacy TEXT,
                id_principal INTEGER,
                kode_sales TEXT,
                nama_sales_legacy TEXT,
                original_no_faktur TEXT,
                id_faktur INTEGER,
                id_sales_order INTEGER,
                no_dn TEXT,
                tanggal_dn DATE,
                total_retur NUMERIC,
                total_terbayar NUMERIC,
                stnota TEXT,
                approve TEXT,
                review_status TEXT NOT NULL DEFAULT 'review',
                validation_errors TEXT,
                raw_payload JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS legacy_transaction_sync.retur_sales_review_detail (
                id BIGSERIAL PRIMARY KEY,
                id_review BIGINT NOT NULL REFERENCES legacy_transaction_sync.retur_sales_review(id) ON DELETE CASCADE,
                legacy_key TEXT NOT NULL UNIQUE,
                kode_retur TEXT,
                kode_produk TEXT,
                master_kode_produk TEXT,
                nama_produk_legacy TEXT,
                id_produk INTEGER,
                unit NUMERIC,
                ct TEXT,
                satuan NUMERIC,
                pc TEXT,
                perunit NUMERIC,
                jumlah NUMERIC,
                harga NUMERIC,
                disc1 NUMERIC,
                disc2 NUMERIC,
                disc3 NUMERIC,
                discrp NUMERIC,
                jumlah_ex_ppn NUMERIC,
                jumlah_harga NUMERIC,
                urut TEXT,
                stnota TEXT,
                review_status TEXT NOT NULL DEFAULT 'review',
                validation_errors TEXT,
                raw_payload JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        ''')

        cur.execute('DROP TABLE IF EXISTS tmp_legacy_retur_review_headers')
        cur.execute(f'''
            CREATE TEMP TABLE tmp_legacy_retur_review_headers AS
            WITH ranked AS (
                SELECT *
                FROM (
                    SELECT h.*,
                           'hretursm:' || btrim(coalesce(h.nota,'')) AS legacy_key,
                           row_number() OVER (
                               PARTITION BY btrim(coalesce(h.nota,''))
                               ORDER BY h.source_priority, h.staging_id
                           ) rn
                    FROM legacy_transaction_import_server.hretursm h
                    WHERE btrim(coalesce(h.nota,'')) <> ''
                      AND h.tanggal ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}'
                      AND left(h.tanggal, 10)::date >= %s::date
                      AND left(h.tanggal, 10)::date <= %s::date
                ) x
                WHERE rn = 1
            ),
            customer_map AS (
                SELECT btrim(kode) kode, min(id) id
                FROM customer
                WHERE btrim(coalesce(kode,'')) <> ''
                GROUP BY btrim(kode)
            ),
            principal_map AS (
                SELECT btrim(kode) kode, min(id) id
                FROM principal
                WHERE btrim(coalesce(kode,'')) <> ''
                GROUP BY btrim(kode)
            ),
            faktur_map AS (
                SELECT btrim(no_faktur) no_faktur, min(id) id_faktur, min(id_sales_order) id_sales_order
                FROM faktur
                WHERE btrim(coalesce(no_faktur,'')) <> ''
                GROUP BY btrim(no_faktur)
            )
            SELECT
                r.legacy_key,
                r.source_system,
                r.source_priority,
                left(r.tanggal, 10)::date AS tanggal_retur,
                btrim(r.nota) AS kode_retur,
                NULLIF(btrim(r.kodecustomer), '') AS kode_customer,
                NULLIF(btrim(r.namacustomer), '') AS nama_customer_legacy,
                c.id AS id_customer,
                NULLIF(btrim(r.kodeprinciple), '') AS kode_principal,
                NULLIF(btrim(r.namaprinciple), '') AS nama_principal_legacy,
                pr.id AS id_principal,
                NULLIF(btrim(r.kodesales), '') AS kode_sales,
                NULLIF(btrim(r.namasales), '') AS nama_sales_legacy,
                NULLIF(btrim(r.notasm), '') AS original_no_faktur,
                f.id_faktur,
                f.id_sales_order,
                NULLIF(btrim(r.nodn), '') AS no_dn,
                CASE WHEN r.tanggaldn ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}' THEN left(r.tanggaldn, 10)::date ELSE NULL END AS tanggal_dn,
                CASE WHEN btrim(coalesce(r.totalretur,'')) ~ '{NUMERIC_RE}' THEN btrim(r.totalretur)::numeric ELSE 0 END AS total_retur,
                CASE WHEN btrim(coalesce(r.terbayar,'')) ~ '{NUMERIC_RE}' THEN btrim(r.terbayar)::numeric ELSE 0 END AS total_terbayar,
                NULLIF(btrim(r.stnota), '') AS stnota,
                NULLIF(btrim(r.approve), '') AS approve,
                CASE
                    WHEN c.id IS NULL OR pr.id IS NULL THEN 'review'
                    WHEN f.id_faktur IS NULL AND NULLIF(btrim(r.notasm), '') IS NOT NULL THEN 'review'
                    ELSE 'ready'
                END AS review_status,
                concat_ws('; ',
                    CASE WHEN c.id IS NULL THEN 'customer tidak ditemukan' END,
                    CASE WHEN pr.id IS NULL THEN 'principal tidak ditemukan' END,
                    CASE WHEN f.id_faktur IS NULL AND NULLIF(btrim(r.notasm), '') IS NOT NULL THEN 'faktur asal tidak ditemukan' END
                ) AS validation_errors,
                row_to_json(r)::jsonb AS raw_payload
            FROM ranked r
            LEFT JOIN customer_map c ON c.kode = btrim(r.kodecustomer)
            LEFT JOIN principal_map pr ON pr.kode = btrim(r.kodeprinciple)
            LEFT JOIN faktur_map f ON f.no_faktur = btrim(r.notasm)
        ''', (args.min_date, max_date))

        cur.execute('DROP TABLE IF EXISTS tmp_legacy_retur_review_details')
        cur.execute(f'''
            CREATE TEMP TABLE tmp_legacy_retur_review_details AS
            WITH ranked AS (
                SELECT *
                FROM (
                    SELECT d.*,
                           'dretursm:' || btrim(coalesce(d.nota,'')) || ':' ||
                               btrim(coalesce(d.urut,'')) || ':' ||
                               btrim(coalesce(d.kodestok,'')) AS legacy_key,
                           row_number() OVER (
                               PARTITION BY btrim(coalesce(d.nota,'')), btrim(coalesce(d.urut,'')), btrim(coalesce(d.kodestok,''))
                               ORDER BY d.source_priority, d.staging_id
                           ) rn
                    FROM legacy_transaction_import_server.dretursm d
                    WHERE btrim(coalesce(d.nota,'')) <> ''
                      AND btrim(coalesce(d.kodestok,'')) <> ''
                      AND d.tanggal ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}'
                      AND left(d.tanggal, 10)::date >= %s::date
                      AND left(d.tanggal, 10)::date <= %s::date
                ) x
                WHERE rn = 1
            ),
            produk_map AS (
                SELECT btrim(kode_sku) kode, min(id) id
                FROM produk
                WHERE btrim(coalesce(kode_sku,'')) <> ''
                GROUP BY btrim(kode_sku)
            )
            SELECT
                r.legacy_key,
                'hretursm:' || btrim(r.nota) AS header_legacy_key,
                btrim(r.nota) AS kode_retur,
                NULLIF(btrim(r.kodestok), '') AS kode_produk,
                NULLIF(btrim(r.masterkode), '') AS master_kode_produk,
                NULLIF(btrim(r.namastok), '') AS nama_produk_legacy,
                COALESCE(pm_master.id, pm_stock.id) AS id_produk,
                CASE WHEN btrim(coalesce(r.unit,'')) ~ '{NUMERIC_RE}' THEN btrim(r.unit)::numeric ELSE 0 END AS unit,
                NULLIF(btrim(r.ct), '') AS ct,
                CASE WHEN btrim(coalesce(r.satuan,'')) ~ '{NUMERIC_RE}' THEN btrim(r.satuan)::numeric ELSE 0 END AS satuan,
                NULLIF(btrim(r.pc), '') AS pc,
                CASE WHEN btrim(coalesce(r.perunit,'')) ~ '{NUMERIC_RE}' THEN btrim(r.perunit)::numeric ELSE 0 END AS perunit,
                CASE WHEN btrim(coalesce(r.jumlah,'')) ~ '{NUMERIC_RE}' THEN btrim(r.jumlah)::numeric ELSE 0 END AS jumlah,
                CASE WHEN btrim(coalesce(r.harga,'')) ~ '{NUMERIC_RE}' THEN btrim(r.harga)::numeric ELSE 0 END AS harga,
                CASE WHEN btrim(coalesce(r.disc1,'')) ~ '{NUMERIC_RE}' THEN btrim(r.disc1)::numeric ELSE 0 END AS disc1,
                CASE WHEN btrim(coalesce(r.disc2,'')) ~ '{NUMERIC_RE}' THEN btrim(r.disc2)::numeric ELSE 0 END AS disc2,
                CASE WHEN btrim(coalesce(r.disc3,'')) ~ '{NUMERIC_RE}' THEN btrim(r.disc3)::numeric ELSE 0 END AS disc3,
                CASE WHEN btrim(coalesce(r.discrp,'')) ~ '{NUMERIC_RE}' THEN btrim(r.discrp)::numeric ELSE 0 END AS discrp,
                CASE WHEN btrim(coalesce(r.jumlahexppn,'')) ~ '{NUMERIC_RE}' THEN btrim(r.jumlahexppn)::numeric ELSE 0 END AS jumlah_ex_ppn,
                CASE WHEN btrim(coalesce(r.jumlahharga,'')) ~ '{NUMERIC_RE}' THEN btrim(r.jumlahharga)::numeric ELSE 0 END AS jumlah_harga,
                NULLIF(btrim(r.urut), '') AS urut,
                NULLIF(btrim(r.stnota), '') AS stnota,
                CASE WHEN COALESCE(pm_master.id, pm_stock.id) IS NULL THEN 'review' ELSE 'ready' END AS review_status,
                CASE WHEN COALESCE(pm_master.id, pm_stock.id) IS NULL THEN 'produk tidak ditemukan' ELSE '' END AS validation_errors,
                row_to_json(r)::jsonb AS raw_payload
            FROM ranked r
            LEFT JOIN produk_map pm_master ON pm_master.kode = btrim(r.masterkode)
            LEFT JOIN produk_map pm_stock ON pm_stock.kode = btrim(r.kodestok)
        ''', (args.min_date, max_date))

        cur.execute('''
            SELECT
                (SELECT COUNT(*) FROM tmp_legacy_retur_review_headers),
                (SELECT COUNT(*) FROM tmp_legacy_retur_review_headers WHERE review_status='ready'),
                (SELECT COUNT(*) FROM tmp_legacy_retur_review_details),
                (SELECT COUNT(*) FROM tmp_legacy_retur_review_details WHERE review_status='ready'),
                (SELECT MIN(tanggal_retur) FROM tmp_legacy_retur_review_headers),
                (SELECT MAX(tanggal_retur) FROM tmp_legacy_retur_review_headers)
        ''')
        header_count, ready_headers, detail_count, ready_details, min_date, max_date = cur.fetchone()
        print(f'candidate_retur_headers={header_count}')
        print(f'candidate_retur_headers_ready={ready_headers}')
        print(f'candidate_retur_details={detail_count}')
        print(f'candidate_retur_details_ready={ready_details}')
        print(f'candidate_date_range={min_date}..{max_date}')

        if not args.apply:
            print('dry_run=true')
            cur.execute('ROLLBACK')
            return

        cur.execute('''
            INSERT INTO legacy_transaction_sync.retur_sales_review (
                batch_label, legacy_key, source_system, source_priority, tanggal_retur,
                kode_retur, kode_customer, nama_customer_legacy, id_customer,
                kode_principal, nama_principal_legacy, id_principal,
                kode_sales, nama_sales_legacy, original_no_faktur, id_faktur,
                id_sales_order, no_dn, tanggal_dn, total_retur, total_terbayar,
                stnota, approve, review_status, validation_errors, raw_payload, updated_at
            )
            SELECT
                %s, legacy_key, source_system, source_priority, tanggal_retur,
                kode_retur, kode_customer, nama_customer_legacy, id_customer,
                kode_principal, nama_principal_legacy, id_principal,
                kode_sales, nama_sales_legacy, original_no_faktur, id_faktur,
                id_sales_order, no_dn, tanggal_dn, total_retur, total_terbayar,
                stnota, approve, review_status, NULLIF(validation_errors, ''), raw_payload, NOW()
            FROM tmp_legacy_retur_review_headers
            ON CONFLICT (legacy_key) DO UPDATE SET
                source_system=EXCLUDED.source_system,
                source_priority=EXCLUDED.source_priority,
                tanggal_retur=EXCLUDED.tanggal_retur,
                kode_customer=EXCLUDED.kode_customer,
                nama_customer_legacy=EXCLUDED.nama_customer_legacy,
                id_customer=EXCLUDED.id_customer,
                kode_principal=EXCLUDED.kode_principal,
                nama_principal_legacy=EXCLUDED.nama_principal_legacy,
                id_principal=EXCLUDED.id_principal,
                kode_sales=EXCLUDED.kode_sales,
                nama_sales_legacy=EXCLUDED.nama_sales_legacy,
                original_no_faktur=EXCLUDED.original_no_faktur,
                id_faktur=EXCLUDED.id_faktur,
                id_sales_order=EXCLUDED.id_sales_order,
                no_dn=EXCLUDED.no_dn,
                tanggal_dn=EXCLUDED.tanggal_dn,
                total_retur=EXCLUDED.total_retur,
                total_terbayar=EXCLUDED.total_terbayar,
                stnota=EXCLUDED.stnota,
                approve=EXCLUDED.approve,
                review_status=EXCLUDED.review_status,
                validation_errors=EXCLUDED.validation_errors,
                raw_payload=EXCLUDED.raw_payload,
                updated_at=NOW()
        ''', (args.batch_label,))
        upserted_headers = cur.rowcount

        cur.execute('''
            INSERT INTO legacy_transaction_sync.retur_sales_review_detail (
                id_review, legacy_key, kode_retur, kode_produk, master_kode_produk,
                nama_produk_legacy, id_produk, unit, ct, satuan, pc, perunit, jumlah,
                harga, disc1, disc2, disc3, discrp, jumlah_ex_ppn, jumlah_harga,
                urut, stnota, review_status, validation_errors, raw_payload, updated_at
            )
            SELECT
                h.id, d.legacy_key, d.kode_retur, d.kode_produk, d.master_kode_produk,
                d.nama_produk_legacy, d.id_produk, d.unit, d.ct, d.satuan, d.pc, d.perunit, d.jumlah,
                d.harga, d.disc1, d.disc2, d.disc3, d.discrp, d.jumlah_ex_ppn, d.jumlah_harga,
                d.urut, d.stnota, d.review_status, NULLIF(d.validation_errors, ''), d.raw_payload, NOW()
            FROM tmp_legacy_retur_review_details d
            JOIN legacy_transaction_sync.retur_sales_review h
              ON h.legacy_key = d.header_legacy_key
            ON CONFLICT (legacy_key) DO UPDATE SET
                id_review=EXCLUDED.id_review,
                kode_produk=EXCLUDED.kode_produk,
                master_kode_produk=EXCLUDED.master_kode_produk,
                nama_produk_legacy=EXCLUDED.nama_produk_legacy,
                id_produk=EXCLUDED.id_produk,
                unit=EXCLUDED.unit,
                ct=EXCLUDED.ct,
                satuan=EXCLUDED.satuan,
                pc=EXCLUDED.pc,
                perunit=EXCLUDED.perunit,
                jumlah=EXCLUDED.jumlah,
                harga=EXCLUDED.harga,
                disc1=EXCLUDED.disc1,
                disc2=EXCLUDED.disc2,
                disc3=EXCLUDED.disc3,
                discrp=EXCLUDED.discrp,
                jumlah_ex_ppn=EXCLUDED.jumlah_ex_ppn,
                jumlah_harga=EXCLUDED.jumlah_harga,
                urut=EXCLUDED.urut,
                stnota=EXCLUDED.stnota,
                review_status=EXCLUDED.review_status,
                validation_errors=EXCLUDED.validation_errors,
                raw_payload=EXCLUDED.raw_payload,
                updated_at=NOW()
        ''')
        upserted_details = cur.rowcount

        conn.commit()
        print(f'upserted_retur_headers_review={upserted_headers}')
        print(f'upserted_retur_details_review={upserted_details}')
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
