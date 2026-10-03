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


def connect():
    return pg8000.connect(**PG)


def scalar(cur, sql, params=()):
    cur.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


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
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_legacy_master_merge_audit_batch
        ON legacy_master_merge_audit (batch_code, target_table, action)
        """
    )


def sync_sequences(cur):
    for table, pk in [("principal", "id"), ("produk", "id"), ("customer", "id"), ("plafon", "id")]:
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


def build_legacy_views(cur, schema):
    cur.execute(f"DROP TABLE IF EXISTS tmp_legacy_principle_pick")
    cur.execute(f"DROP TABLE IF EXISTS tmp_legacy_stok_pick")
    cur.execute(f"DROP TABLE IF EXISTS tmp_legacy_customer_pick")
    cur.execute(f"DROP TABLE IF EXISTS tmp_legacy_plafon_pick")

    cur.execute(
        f"""
        CREATE TEMP TABLE tmp_legacy_principle_pick AS
        WITH ranked AS (
            SELECT
                p.*,
                ROW_NUMBER() OVER (
                    PARTITION BY NULLIF(TRIM(p.kode), '')
                    ORDER BY p.source_priority ASC, p.staging_id ASC
                ) AS rn
            FROM {schema}.principle p
            WHERE NULLIF(TRIM(p.kode), '') IS NOT NULL
        )
        SELECT * FROM ranked WHERE rn = 1
        """
    )

    cur.execute(
        f"""
        CREATE TEMP TABLE tmp_legacy_stok_pick AS
        WITH ranked AS (
            SELECT
                s.*,
                ROW_NUMBER() OVER (
                    PARTITION BY NULLIF(TRIM(s.kode), '')
                    ORDER BY s.source_priority ASC, s.staging_id ASC
                ) AS rn
            FROM {schema}.stok s
            WHERE NULLIF(TRIM(s.kode), '') IS NOT NULL
        )
        SELECT * FROM ranked WHERE rn = 1
        """
    )
    cur.execute(
        f"""
        CREATE TEMP TABLE tmp_legacy_customer_pick AS
        WITH ranked AS (
            SELECT
                c.*,
                ROW_NUMBER() OVER (
                    PARTITION BY UPPER(TRIM(c.kode))
                    ORDER BY c.source_priority ASC, c.staging_id ASC
                ) AS rn
            FROM {schema}.customer c
            WHERE NULLIF(TRIM(c.kode), '') IS NOT NULL
        )
        SELECT * FROM ranked WHERE rn = 1
        """
    )
    cur.execute(
        f"""
        CREATE TEMP TABLE tmp_legacy_plafon_pick AS
        WITH ranked AS (
            SELECT
                pl.*,
                ROW_NUMBER() OVER (
                    PARTITION BY UPPER(TRIM(pl.kodecustomer)), UPPER(TRIM(pl.kodeprinciple))
                    ORDER BY pl.source_priority ASC, pl.staging_id ASC
                ) AS rn
            FROM {schema}.plafon pl
            WHERE NULLIF(TRIM(pl.kodecustomer), '') IS NOT NULL
              AND NULLIF(TRIM(pl.kodeprinciple), '') IS NOT NULL
        )
        SELECT * FROM ranked WHERE rn = 1
        """
    )
    build_principal_pick(cur)
    build_customer_pick(cur)
    build_sales_detail_pick(cur)


def build_principal_pick(cur):
    cur.execute(f"DROP TABLE IF EXISTS tmp_principal_pick")
    cur.execute(
        """
        CREATE TEMP TABLE tmp_principal_pick AS
        SELECT DISTINCT ON (UPPER(TRIM(kode)))
            id,
            kode
        FROM principal
        WHERE NULLIF(TRIM(COALESCE(kode, '')), '') IS NOT NULL
        ORDER BY UPPER(TRIM(kode)), id ASC
        """
    )


def build_customer_pick(cur):
    cur.execute(f"DROP TABLE IF EXISTS tmp_customer_pick")
    cur.execute(
        """
        CREATE TEMP TABLE tmp_customer_pick AS
        SELECT DISTINCT ON (UPPER(TRIM(kode)))
            id,
            kode
        FROM customer
        WHERE NULLIF(TRIM(COALESCE(kode, '')), '') IS NOT NULL
        ORDER BY UPPER(TRIM(kode)), id ASC
        """
    )


def build_sales_detail_pick(cur):
    cur.execute(f"DROP TABLE IF EXISTS tmp_sales_detail_pick")
    cur.execute(
        """
        CREATE TEMP TABLE tmp_sales_detail_pick AS
        SELECT DISTINCT ON (UPPER(TRIM(kode_sales)))
            id_sales,
            kode_sales
        FROM sales_detail
        WHERE NULLIF(TRIM(COALESCE(kode_sales, '')), '') IS NOT NULL
        ORDER BY UPPER(TRIM(kode_sales)), id ASC
        """
    )


def merge_principal(cur, batch_code, apply):
    candidates = scalar(cur, "SELECT COUNT(*) FROM tmp_legacy_principle_pick") or 0
    inserts = scalar(
        cur,
        """
        SELECT COUNT(*)
        FROM tmp_legacy_principle_pick lp
        LEFT JOIN principal p ON UPPER(TRIM(p.kode)) = UPPER(TRIM(lp.kode))
        WHERE p.id IS NULL
        """,
    ) or 0
    existing = candidates - inserts

    if apply and inserts:
        cur.execute(
            """
            INSERT INTO principal (
                kode, nama, alamat, telepon, npwp, no_rekening, pic,
                id_perusahaan, aktif
            )
            SELECT
                LEFT(TRIM(lp.kode), 100),
                LEFT(COALESCE(NULLIF(TRIM(lp.nama), ''), TRIM(lp.kode)), 50),
                LEFT(NULLIF(TRIM(lp.alamat), ''), 100),
                LEFT(NULLIF(TRIM(lp.telpon), ''), 15),
                LEFT(NULLIF(TRIM(lp.npwp), ''), 25),
                LEFT(NULLIF(TRIM(lp.account), ''), 20),
                LEFT(NULLIF(TRIM(lp.contactperson), ''), 50),
                1,
                COALESCE(NULLIF(TRIM(lp.active), ''), '1') NOT IN ('0', 'false', 'False', 'FALSE')
            FROM tmp_legacy_principle_pick lp
            LEFT JOIN principal p ON UPPER(TRIM(p.kode)) = UPPER(TRIM(lp.kode))
            WHERE p.id IS NULL
            """
        )
        cur.execute(
            """
            INSERT INTO legacy_master_merge_audit (
                batch_code, target_table, action, source_system,
                source_priority, legacy_code, target_id, message
            )
            SELECT
                %s, 'principal', 'insert', lp.source_system,
                lp.source_priority, TRIM(lp.kode), p.id::text,
                'Inserted principal from legacy staging'
            FROM tmp_legacy_principle_pick lp
            JOIN principal p ON UPPER(TRIM(p.kode)) = UPPER(TRIM(lp.kode))
            WHERE NOT EXISTS (
                SELECT 1 FROM legacy_master_merge_audit a
                WHERE a.batch_code = %s
                  AND a.target_table = 'principal'
                  AND a.action = 'insert'
                  AND a.legacy_code = TRIM(lp.kode)
            )
            """,
            (batch_code, batch_code),
        )

    return {
        "target": "principal",
        "candidates": candidates,
        "insert": inserts,
        "existing_skip": existing,
    }


def merge_produk(cur, batch_code, apply):
    candidates = scalar(cur, "SELECT COUNT(*) FROM tmp_legacy_stok_pick") or 0
    inserts = scalar(
        cur,
        """
        SELECT COUNT(*)
        FROM tmp_legacy_stok_pick ls
        LEFT JOIN produk p ON UPPER(TRIM(p.kode_sku)) = UPPER(TRIM(ls.kode))
        WHERE p.id IS NULL
        """,
    ) or 0
    missing_principal = scalar(
        cur,
        """
        SELECT COUNT(*)
        FROM tmp_legacy_stok_pick ls
        LEFT JOIN produk p ON UPPER(TRIM(p.kode_sku)) = UPPER(TRIM(ls.kode))
        LEFT JOIN tmp_principal_pick pr ON UPPER(TRIM(pr.kode)) = UPPER(TRIM(ls.principle))
        WHERE p.id IS NULL
          AND NULLIF(TRIM(COALESCE(ls.principle, '')), '') IS NOT NULL
          AND pr.id IS NULL
        """,
    ) or 0
    existing = candidates - inserts

    if apply and inserts:
        cur.execute(
            """
            INSERT INTO produk (
                id_principal, kode_sku, kode_ean, nama, harga_beli, harga_jual,
                satuan, isiperbox, isiperkarton, kategori_customer, keterangan
            )
            SELECT
                pr.id,
                LEFT(TRIM(ls.kode), 25),
                LEFT(NULLIF(TRIM(ls.nasionalkode), ''), 25),
                LEFT(COALESCE(NULLIF(TRIM(ls.nama), ''), TRIM(ls.kode)), 50),
                NULLIF(REGEXP_REPLACE(COALESCE(ls.hargaasli, '0'), '[^0-9.-]', '', 'g'), '')::double precision,
                NULLIF(REGEXP_REPLACE(COALESCE(ls.hargaa, '0'), '[^0-9.-]', '', 'g'), '')::double precision,
                LEFT(NULLIF(TRIM(ls.satuan), ''), 30),
                NULLIF(REGEXP_REPLACE(COALESCE(ls.perunit, '0'), '[^0-9.-]', '', 'g'), '')::numeric::integer,
                NULLIF(REGEXP_REPLACE(COALESCE(ls.perunit, '0'), '[^0-9.-]', '', 'g'), '')::numeric::integer,
                LEFT(NULLIF(TRIM(ls.kategori), ''), 30),
                LEFT(CONCAT_WS(' | ', 'legacy', ls.source_system, NULLIF(TRIM(ls.kodedms), '')), 50)
            FROM tmp_legacy_stok_pick ls
            LEFT JOIN produk p ON UPPER(TRIM(p.kode_sku)) = UPPER(TRIM(ls.kode))
            LEFT JOIN tmp_principal_pick pr ON UPPER(TRIM(pr.kode)) = UPPER(TRIM(ls.principle))
            WHERE p.id IS NULL
            """
        )
        cur.execute(
            """
            INSERT INTO legacy_master_merge_audit (
                batch_code, target_table, action, source_system,
                source_priority, legacy_code, target_id, message
            )
            SELECT
                %s, 'produk', 'insert', ls.source_system,
                ls.source_priority, TRIM(ls.kode), p.id::text,
                CASE WHEN p.id_principal IS NULL
                     THEN 'Inserted product but principal was not resolved'
                     ELSE 'Inserted product from legacy staging'
                END
            FROM tmp_legacy_stok_pick ls
            JOIN produk p ON UPPER(TRIM(p.kode_sku)) = UPPER(TRIM(ls.kode))
            WHERE NOT EXISTS (
                SELECT 1 FROM legacy_master_merge_audit a
                WHERE a.batch_code = %s
                  AND a.target_table = 'produk'
                  AND a.action = 'insert'
                  AND a.legacy_code = TRIM(ls.kode)
            )
            """,
            (batch_code, batch_code),
        )

    return {
        "target": "produk",
        "candidates": candidates,
        "insert": inserts,
        "existing_skip": existing,
        "insert_missing_principal": missing_principal,
    }


def merge_customer(cur, batch_code, apply):
    candidates = scalar(cur, "SELECT COUNT(*) FROM tmp_legacy_customer_pick") or 0
    inserts = scalar(
        cur,
        """
        SELECT COUNT(*)
        FROM tmp_legacy_customer_pick lc
        LEFT JOIN tmp_customer_pick c ON UPPER(TRIM(c.kode)) = UPPER(TRIM(lc.kode))
        WHERE c.id IS NULL
        """,
    ) or 0
    missing_tipe = scalar(
        cur,
        """
        SELECT COUNT(*)
        FROM tmp_legacy_customer_pick lc
        LEFT JOIN tmp_customer_pick c ON UPPER(TRIM(c.kode)) = UPPER(TRIM(lc.kode))
        LEFT JOIN customer_tipe ct ON UPPER(TRIM(ct.kode)) = UPPER(TRIM(lc.kodejenis))
        WHERE c.id IS NULL
          AND NULLIF(TRIM(COALESCE(lc.kodejenis, '')), '') IS NOT NULL
          AND ct.id IS NULL
        """,
    ) or 0
    existing = candidates - inserts

    if apply and inserts:
        cur.execute(
            """
            INSERT INTO customer (
                kode, nama, alamat, telepon, telepon2, npwp, email,
                nama_wajib_pajak, alamat_wajib_pajak, pic, longitude, latitude,
                id_tipe, id_cabang, id_cabang_list, id_perusahaan_list,
                is_ppn
            )
            SELECT
                LEFT(TRIM(lc.kode), 30),
                LEFT(COALESCE(NULLIF(TRIM(lc.nama), ''), TRIM(lc.kode)), 50),
                LEFT(NULLIF(TRIM(lc.alamat), ''), 100),
                LEFT(NULLIF(TRIM(lc.telpon), ''), 20),
                LEFT(NULLIF(TRIM(lc.fax), ''), 20),
                LEFT(NULLIF(TRIM(lc.npwp), ''), 25),
                LEFT(NULLIF(TRIM(lc.email), ''), 50),
                LEFT(NULLIF(TRIM(lc.namawp), ''), 50),
                LEFT(NULLIF(TRIM(lc.alamatwp), ''), 100),
                LEFT(NULLIF(TRIM(lc.contactperson), ''), 50),
                LEFT(NULLIF(TRIM(lc.longitude), ''), 25),
                LEFT(NULLIF(TRIM(lc.latitude), ''), 25),
                ct.id,
                COALESCE(cb.id, 5),
                COALESCE(cb.id, 5)::text,
                COALESCE(cb.id_perusahaan, 2)::text,
                CASE WHEN COALESCE(NULLIF(TRIM(lc.fp), ''), '0') IN ('1', 'Y', 'y', 'true', 'TRUE') THEN 1 ELSE 0 END
            FROM tmp_legacy_customer_pick lc
            LEFT JOIN tmp_customer_pick c ON UPPER(TRIM(c.kode)) = UPPER(TRIM(lc.kode))
            LEFT JOIN customer_tipe ct ON UPPER(TRIM(ct.kode)) = UPPER(TRIM(lc.kodejenis))
            LEFT JOIN cabang cb ON UPPER(TRIM(cb.kode)) = UPPER(TRIM(lc.kodearea))
            WHERE c.id IS NULL
            """
        )
        cur.execute(
            """
            INSERT INTO legacy_master_merge_audit (
                batch_code, target_table, action, source_system,
                source_priority, legacy_code, target_id, message
            )
            SELECT
                %s, 'customer', 'insert', lc.source_system,
                lc.source_priority, TRIM(lc.kode), c.id::text,
                'Inserted customer from legacy staging'
            FROM tmp_legacy_customer_pick lc
            JOIN customer c ON UPPER(TRIM(c.kode)) = UPPER(TRIM(lc.kode))
            LEFT JOIN backup_customer_20260717_legacy_merge b ON b.id = c.id
            WHERE b.id IS NULL
            """,
            (batch_code,),
        )

    return {
        "target": "customer",
        "candidates": candidates,
        "insert": inserts,
        "existing_skip": existing,
        "insert_missing_tipe": missing_tipe,
    }


def merge_plafon(cur, batch_code, apply):
    candidates = scalar(cur, "SELECT COUNT(*) FROM tmp_legacy_plafon_pick") or 0
    inserts = scalar(
        cur,
        """
        SELECT COUNT(*)
        FROM tmp_legacy_plafon_pick lp
        JOIN tmp_customer_pick c ON UPPER(TRIM(c.kode)) = UPPER(TRIM(lp.kodecustomer))
        JOIN tmp_principal_pick pr ON UPPER(TRIM(pr.kode)) = UPPER(TRIM(lp.kodeprinciple))
        LEFT JOIN plafon pl ON pl.id_customer = c.id AND pl.id_principal = pr.id
        WHERE pl.id IS NULL
        """,
    ) or 0
    missing_customer = scalar(
        cur,
        """
        SELECT COUNT(*)
        FROM tmp_legacy_plafon_pick lp
        LEFT JOIN tmp_customer_pick c ON UPPER(TRIM(c.kode)) = UPPER(TRIM(lp.kodecustomer))
        WHERE c.id IS NULL
        """,
    ) or 0
    missing_principal = scalar(
        cur,
        """
        SELECT COUNT(*)
        FROM tmp_legacy_plafon_pick lp
        LEFT JOIN tmp_principal_pick pr ON UPPER(TRIM(pr.kode)) = UPPER(TRIM(lp.kodeprinciple))
        WHERE pr.id IS NULL
        """,
    ) or 0
    existing = candidates - inserts - missing_customer - missing_principal
    if existing < 0:
        existing = 0

    if apply and inserts:
        cur.execute(
            """
            INSERT INTO plafon (
                id_customer, id_principal, id_sales, limit_bon, kode,
                top, lock_order, sisa_bon, tempo, tempo_label,
                kategori_izin, minimal_order, sistem_pembayaran
            )
            SELECT
                c.id,
                pr.id,
                sd.id_sales,
                NULLIF(REGEXP_REPLACE(COALESCE(lp.plafon, '0'), '[^0-9.-]', '', 'g'), '')::double precision,
                LEFT(CONCAT(TRIM(lp.kodecustomer), '-', TRIM(lp.kodeprinciple)), 25),
                NULLIF(REGEXP_REPLACE(COALESCE(lp.term, '0'), '[^0-9.-]', '', 'g'), '')::numeric::smallint,
                LEFT(NULLIF(TRIM(lp.lock1), ''), 1),
                NULLIF(REGEXP_REPLACE(COALESCE(lp.plafon, '0'), '[^0-9.-]', '', 'g'), '')::double precision,
                NULLIF(REGEXP_REPLACE(COALESCE(lp.term, '0'), '[^0-9.-]', '', 'g'), '')::numeric::integer,
                CASE
                    WHEN NULLIF(TRIM(lp.term), '') IS NULL THEN NULL
                    ELSE CONCAT(REGEXP_REPLACE(COALESCE(lp.term, '0'), '[^0-9.-]', '', 'g'), ' hari')
                END,
                LEFT(NULLIF(TRIM(lp.kategori), ''), 30),
                0,
                'kredit'
            FROM tmp_legacy_plafon_pick lp
            JOIN tmp_customer_pick c ON UPPER(TRIM(c.kode)) = UPPER(TRIM(lp.kodecustomer))
            JOIN tmp_principal_pick pr ON UPPER(TRIM(pr.kode)) = UPPER(TRIM(lp.kodeprinciple))
            LEFT JOIN tmp_sales_detail_pick sd ON UPPER(TRIM(sd.kode_sales)) = UPPER(TRIM(lp.kodesales))
            LEFT JOIN plafon pl ON pl.id_customer = c.id AND pl.id_principal = pr.id
            WHERE pl.id IS NULL
            """
        )
        cur.execute(
            """
            INSERT INTO legacy_master_merge_audit (
                batch_code, target_table, action, source_system,
                source_priority, legacy_code, target_id, message
            )
            SELECT
                %s, 'plafon', 'insert', lp.source_system,
                lp.source_priority, CONCAT(TRIM(lp.kodecustomer), '-', TRIM(lp.kodeprinciple)),
                pl.id::text,
                'Inserted plafon from legacy staging'
            FROM tmp_legacy_plafon_pick lp
            JOIN tmp_customer_pick c ON UPPER(TRIM(c.kode)) = UPPER(TRIM(lp.kodecustomer))
            JOIN tmp_principal_pick pr ON UPPER(TRIM(pr.kode)) = UPPER(TRIM(lp.kodeprinciple))
            JOIN plafon pl ON pl.id_customer = c.id AND pl.id_principal = pr.id
            LEFT JOIN backup_plafon_20260717_legacy_merge b ON b.id = pl.id
            WHERE b.id IS NULL
            """,
            (batch_code,),
        )

    return {
        "target": "plafon",
        "candidates": candidates,
        "insert": inserts,
        "existing_skip": existing,
        "missing_customer": missing_customer,
        "missing_principal": missing_principal,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", default="legacy_master_import_server")
    parser.add_argument("--batch-code", default="legacy-master-merge-20260717")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    conn = connect()
    try:
        cur = conn.cursor()
        ensure_audit(cur)
        sync_sequences(cur)
        build_legacy_views(cur, args.schema)
        results = [merge_principal(cur, args.batch_code, args.apply)]
        build_principal_pick(cur)
        results.append(merge_produk(cur, args.batch_code, args.apply))
        results.append(merge_customer(cur, args.batch_code, args.apply))
        build_customer_pick(cur)
        results.append(merge_plafon(cur, args.batch_code, args.apply))
        if args.apply:
            sync_sequences(cur)
            conn.commit()
        else:
            conn.rollback()

        mode = "APPLY" if args.apply else "DRY_RUN"
        print(f"mode\t{mode}")
        for item in results:
            print(
                "\t".join(
                    [
                        item["target"],
                        f"candidates={item['candidates']}",
                        f"insert={item['insert']}",
                        f"existing_skip={item['existing_skip']}",
                    ]
                    + [
                        f"{key}={value}"
                        for key, value in item.items()
                        if key not in {"target", "candidates", "insert", "existing_skip"}
                    ]
                )
            )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
