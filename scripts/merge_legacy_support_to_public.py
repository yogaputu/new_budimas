#!/usr/bin/env python3
import argparse
import re

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


def table_exists(cur, table, schema="public"):
    return bool(
        scalar(
            cur,
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
            """,
            (schema, table),
        )
    )


def column_exists(cur, table, column, schema="public"):
    return bool(
        scalar(
            cur,
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s AND column_name = %s
            """,
            (schema, table, column),
        )
    )


def column_max_length(cur, table, column, schema="public", default=255):
    value = scalar(
        cur,
        """
        SELECT character_maximum_length
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s AND column_name = %s
        """,
        (schema, table, column),
    )
    return int(value or default)


def sync_sequence(cur, table, pk="id"):
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
        match = re.search(r"nextval\('([^']+)'::regclass\)", default_expr or "")
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
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_legacy_master_merge_audit_batch
        ON legacy_master_merge_audit (batch_code, target_table, action)
        """
    )


def backup_table(cur, table, batch_code, apply):
    if not apply or not table_exists(cur, table):
        return
    suffix = re.sub(r"[^0-9a-zA-Z_]+", "_", batch_code).lower()
    backup = f"backup_{table}_{suffix}"
    cur.execute(f"CREATE TABLE IF NOT EXISTS {backup} AS TABLE {table} WITH DATA")


def create_support_reference_tables(cur):
    specs = {
        "legacy_barang_class": "legacy_master_import_server.barangclass",
        "legacy_barang_group": "legacy_master_import_server.baranggroup",
        "legacy_barang_lokasi": "legacy_master_import_server.baranglokasi",
        "legacy_barang_merk": "legacy_master_import_server.barangmerk",
        "legacy_customer_area": "legacy_master_import_server.customerarea",
        "legacy_customer_group": "legacy_master_import_server.customergroup",
        "legacy_customer_jenis": "legacy_master_import_server.customerjenis",
        "legacy_customer_market_segment": "legacy_master_import_server.customermarketsegment",
        "legacy_customer_pasar": "legacy_master_import_server.customerpasar",
        "legacy_sales_jenis": "legacy_master_import_server.salesjenis",
        "legacy_target_principle": "legacy_master_import_server.targetprinciple",
    }
    for target, source in specs.items():
        cur.execute(f"CREATE TABLE IF NOT EXISTS {target} AS TABLE {source} WITH NO DATA")
        cur.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{target}_staging_id ON {target} (staging_id)")
    return specs


def merge_reference_copy(cur, batch_code, apply):
    specs = create_support_reference_tables(cur)
    results = []
    for target, source in specs.items():
        source_count = scalar(cur, f"SELECT COUNT(*) FROM {source}") or 0
        inserts = scalar(
            cur,
            f"""
            SELECT COUNT(*)
            FROM {source} s
            LEFT JOIN {target} t ON t.staging_id = s.staging_id
            WHERE t.staging_id IS NULL
            """,
        ) or 0
        if apply and inserts:
            cur.execute(
                f"""
                INSERT INTO {target}
                SELECT s.*
                FROM {source} s
                LEFT JOIN {target} t ON t.staging_id = s.staging_id
                WHERE t.staging_id IS NULL
                """
            )
            cur.execute(
                """
                INSERT INTO legacy_master_merge_audit (
                    batch_code, target_table, action, source_system,
                    source_priority, legacy_code, target_id, message
                )
                VALUES (%s, %s, 'insert', NULL, NULL, NULL, NULL, %s)
                """,
                (
                    batch_code,
                    target,
                    f"Copied {inserts} rows from {source} into reference table",
                ),
            )
        results.append({"target": target, "source_rows": source_count, "insert": inserts})
    return results


def merge_simple_name(cur, batch_code, apply, source_table, target_table):
    if not table_exists(cur, target_table):
        return {"target": target_table, "status": "missing_target"}
    backup_table(cur, target_table, batch_code, apply)
    sync_sequence(cur, target_table)
    nama_length = column_max_length(cur, target_table, "nama")
    candidates = scalar(
        cur,
        f"""
        WITH picked AS (
            SELECT DISTINCT ON (UPPER(TRIM(LEFT(nama, {nama_length}))))
                source_system, source_priority, TRIM(kode) AS kode, LEFT(TRIM(nama), {nama_length}) AS nama
            FROM legacy_master_import_server.{source_table}
            WHERE NULLIF(TRIM(nama), '') IS NOT NULL
            ORDER BY UPPER(TRIM(LEFT(nama, {nama_length}))), source_priority ASC, staging_id ASC
        )
        SELECT COUNT(*) FROM picked
        """,
    ) or 0
    inserts = scalar(
        cur,
        f"""
        WITH picked AS (
            SELECT DISTINCT ON (UPPER(TRIM(LEFT(nama, {nama_length}))))
                source_system, source_priority, TRIM(kode) AS kode, LEFT(TRIM(nama), {nama_length}) AS nama
            FROM legacy_master_import_server.{source_table}
            WHERE NULLIF(TRIM(nama), '') IS NOT NULL
            ORDER BY UPPER(TRIM(LEFT(nama, {nama_length}))), source_priority ASC, staging_id ASC
        )
        SELECT COUNT(*)
        FROM picked p
        LEFT JOIN {target_table} t ON UPPER(TRIM(t.nama)) = UPPER(TRIM(p.nama))
        WHERE t.id IS NULL
        """,
    ) or 0
    if apply and inserts:
        cur.execute(
            f"""
            WITH picked AS (
                SELECT DISTINCT ON (UPPER(TRIM(LEFT(nama, {nama_length}))))
                    source_system, source_priority, TRIM(kode) AS kode, LEFT(TRIM(nama), {nama_length}) AS nama
                FROM legacy_master_import_server.{source_table}
                WHERE NULLIF(TRIM(nama), '') IS NOT NULL
                ORDER BY UPPER(TRIM(LEFT(nama, {nama_length}))), source_priority ASC, staging_id ASC
            )
            INSERT INTO {target_table} (nama)
            SELECT p.nama
            FROM picked p
            LEFT JOIN {target_table} t ON UPPER(TRIM(t.nama)) = UPPER(TRIM(p.nama))
            WHERE t.id IS NULL
            """
        )
        cur.execute(
            f"""
            WITH picked AS (
                SELECT DISTINCT ON (UPPER(TRIM(LEFT(nama, {nama_length}))))
                    source_system, source_priority, TRIM(kode) AS kode, LEFT(TRIM(nama), {nama_length}) AS nama
                FROM legacy_master_import_server.{source_table}
                WHERE NULLIF(TRIM(nama), '') IS NOT NULL
                ORDER BY UPPER(TRIM(LEFT(nama, {nama_length}))), source_priority ASC, staging_id ASC
            )
            INSERT INTO legacy_master_merge_audit (
                batch_code, target_table, action, source_system,
                source_priority, legacy_code, target_id, message
            )
            SELECT
                %s, %s, 'insert', p.source_system,
                p.source_priority, p.kode, t.id::text,
                'Inserted support master from legacy staging'
            FROM picked p
            JOIN {target_table} t ON UPPER(TRIM(t.nama)) = UPPER(TRIM(p.nama))
            WHERE NOT EXISTS (
                SELECT 1 FROM legacy_master_merge_audit a
                WHERE a.batch_code = %s
                  AND a.target_table = %s
                  AND a.action = 'insert'
                  AND COALESCE(a.legacy_code, '') = COALESCE(p.kode, '')
            )
            """,
            (batch_code, target_table, batch_code, target_table),
        )
        sync_sequence(cur, target_table)
    return {"target": target_table, "candidates": candidates, "insert": inserts, "existing_skip": candidates - inserts}


def merge_subbrand(cur, batch_code, apply):
    target_table = "produk_subbrand"
    if not table_exists(cur, target_table):
        return {"target": target_table, "status": "missing_target"}
    backup_table(cur, target_table, batch_code, apply)
    sync_sequence(cur, target_table)
    candidates = scalar(
        cur,
        """
        WITH picked AS (
            SELECT DISTINCT ON (LOWER(TRIM(nama)))
                source_system, source_priority, TRIM(kode) AS kode, TRIM(nama) AS nama,
                COALESCE(NULLIF(TRIM(active), ''), '1') NOT IN ('0', 'false', 'False', 'FALSE') AS is_active
            FROM legacy_master_import_server.barangsubbrand
            WHERE NULLIF(TRIM(nama), '') IS NOT NULL
            ORDER BY LOWER(TRIM(nama)), source_priority ASC, staging_id ASC
        )
        SELECT COUNT(*) FROM picked
        """
    ) or 0
    inserts = scalar(
        cur,
        """
        WITH picked AS (
            SELECT DISTINCT ON (LOWER(TRIM(nama)))
                TRIM(kode) AS kode, TRIM(nama) AS nama
            FROM legacy_master_import_server.barangsubbrand
            WHERE NULLIF(TRIM(nama), '') IS NOT NULL
            ORDER BY LOWER(TRIM(nama)), source_priority ASC, staging_id ASC
        )
        SELECT COUNT(*)
        FROM picked p
        LEFT JOIN produk_subbrand t
          ON UPPER(TRIM(COALESCE(t.kode, ''))) = UPPER(TRIM(COALESCE(p.kode, '')))
          OR LOWER(TRIM(t.nama)) = LOWER(TRIM(p.nama))
        WHERE t.id IS NULL
        """
    ) or 0
    if apply and inserts:
        cur.execute(
            """
            WITH picked AS (
                SELECT DISTINCT ON (LOWER(TRIM(nama)))
                    source_system, source_priority, TRIM(kode) AS kode, TRIM(nama) AS nama,
                    COALESCE(NULLIF(TRIM(active), ''), '1') NOT IN ('0', 'false', 'False', 'FALSE') AS is_active
                FROM legacy_master_import_server.barangsubbrand
                WHERE NULLIF(TRIM(nama), '') IS NOT NULL
                ORDER BY LOWER(TRIM(nama)), source_priority ASC, staging_id ASC
            )
            INSERT INTO produk_subbrand (kode, nama, is_active)
            SELECT LEFT(p.kode, 50), LEFT(COALESCE(NULLIF(p.nama, ''), p.kode), 150), p.is_active
            FROM picked p
            LEFT JOIN produk_subbrand t
              ON UPPER(TRIM(COALESCE(t.kode, ''))) = UPPER(TRIM(COALESCE(p.kode, '')))
              OR LOWER(TRIM(t.nama)) = LOWER(TRIM(p.nama))
            WHERE t.id IS NULL
            """
        )
        cur.execute(
            """
            WITH picked AS (
                SELECT DISTINCT ON (LOWER(TRIM(nama)))
                    source_system, source_priority, TRIM(kode) AS kode, TRIM(nama) AS nama
                FROM legacy_master_import_server.barangsubbrand
                WHERE NULLIF(TRIM(nama), '') IS NOT NULL
                ORDER BY LOWER(TRIM(nama)), source_priority ASC, staging_id ASC
            )
            INSERT INTO legacy_master_merge_audit (
                batch_code, target_table, action, source_system,
                source_priority, legacy_code, target_id, message
            )
            SELECT
                %s, 'produk_subbrand', 'insert', p.source_system,
                p.source_priority, p.kode, t.id::text,
                'Inserted subbrand from legacy staging'
            FROM picked p
            JOIN produk_subbrand t
              ON UPPER(TRIM(COALESCE(t.kode, ''))) = UPPER(TRIM(COALESCE(p.kode, '')))
              OR LOWER(TRIM(t.nama)) = LOWER(TRIM(p.nama))
            WHERE NOT EXISTS (
                SELECT 1 FROM legacy_master_merge_audit a
                WHERE a.batch_code = %s
                  AND a.target_table = 'produk_subbrand'
                  AND a.action = 'insert'
                  AND a.legacy_code = p.kode
            )
            """,
            (batch_code, batch_code),
        )
        sync_sequence(cur, target_table)
    return {"target": target_table, "candidates": candidates, "insert": inserts, "existing_skip": candidates - inserts}


def merge_armada(cur, batch_code, apply):
    backup_table(cur, "armada_tipe", batch_code, apply)
    backup_table(cur, "armada", batch_code, apply)
    sync_sequence(cur, "armada_tipe")
    sync_sequence(cur, "armada")
    tipe_nama_length = column_max_length(cur, "armada_tipe", "nama")
    armada_nama_length = column_max_length(cur, "armada", "nama")
    armada_pelat_length = column_max_length(cur, "armada", "no_pelat")
    armada_ket_length = column_max_length(cur, "armada", "keterangan")
    type_insert = scalar(
        cur,
        f"""
        WITH picked AS (
            SELECT DISTINCT NULLIF(LEFT(TRIM(jenis), {tipe_nama_length}), '') AS nama
            FROM legacy_master_import_server.kendaraan
            WHERE NULLIF(TRIM(jenis), '') IS NOT NULL
        )
        SELECT COUNT(*)
        FROM picked p
        LEFT JOIN armada_tipe t ON UPPER(TRIM(t.nama)) = UPPER(TRIM(p.nama))
        WHERE t.id IS NULL
        """
    ) or 0
    vehicle_insert = scalar(
        cur,
        """
        WITH picked AS (
            SELECT DISTINCT ON (UPPER(TRIM(nopolisi)))
                TRIM(nopolisi) AS no_pelat
            FROM legacy_master_import_server.kendaraan
            WHERE NULLIF(TRIM(nopolisi), '') IS NOT NULL
            ORDER BY UPPER(TRIM(nopolisi)), source_priority ASC, staging_id ASC
        )
        SELECT COUNT(*)
        FROM picked p
        LEFT JOIN armada a ON UPPER(TRIM(a.no_pelat)) = UPPER(TRIM(p.no_pelat))
        WHERE a.id IS NULL
        """
    ) or 0
    if apply:
        if type_insert:
            cur.execute(
                f"""
                WITH picked AS (
                    SELECT DISTINCT NULLIF(LEFT(TRIM(jenis), {tipe_nama_length}), '') AS nama
                    FROM legacy_master_import_server.kendaraan
                    WHERE NULLIF(TRIM(jenis), '') IS NOT NULL
                )
                INSERT INTO armada_tipe (nama)
                SELECT p.nama
                FROM picked p
                LEFT JOIN armada_tipe t ON UPPER(TRIM(t.nama)) = UPPER(TRIM(p.nama))
                WHERE t.id IS NULL
                """
            )
            sync_sequence(cur, "armada_tipe")
        if vehicle_insert:
            cur.execute(
                f"""
                WITH picked AS (
                    SELECT DISTINCT ON (UPPER(TRIM(nopolisi)))
                        source_system, source_priority, TRIM(idkendaraan) AS kode,
                        LEFT(TRIM(nopolisi), {armada_pelat_length}) AS no_pelat,
                        LEFT(TRIM(jenis), {tipe_nama_length}) AS jenis,
                        LEFT(TRIM(merk), {armada_nama_length}) AS merk,
                        COALESCE(NULLIF(REGEXP_REPLACE(COALESCE(kapasitasvolume, '0'), '[^0-9.-]', '', 'g'), ''), '0')::numeric AS kubikasi
                    FROM legacy_master_import_server.kendaraan
                    WHERE NULLIF(TRIM(nopolisi), '') IS NOT NULL
                    ORDER BY UPPER(TRIM(nopolisi)), source_priority ASC, staging_id ASC
                )
                INSERT INTO armada (
                    id_cabang, id_tipe, nama, no_pelat, kubikasi,
                    keterangan, id_status, id_perusahaan, id_perusahaan_list
                )
                SELECT
                    5,
                    at.id,
                    LEFT(COALESCE(NULLIF(p.merk, ''), p.no_pelat), {armada_nama_length}),
                    LEFT(p.no_pelat, {armada_pelat_length}),
                    LEAST(GREATEST(COALESCE(p.kubikasi, 0), 0), 2147483647)::integer,
                    LEFT(CONCAT('Legacy SQL Server kendaraan ', p.kode), {armada_ket_length}),
                    1,
                    1,
                    '1'
                FROM picked p
                LEFT JOIN armada_tipe at ON UPPER(TRIM(at.nama)) = UPPER(TRIM(p.jenis))
                LEFT JOIN armada a ON UPPER(TRIM(a.no_pelat)) = UPPER(TRIM(p.no_pelat))
                WHERE a.id IS NULL
                """
            )
            cur.execute(
                """
                WITH picked AS (
                    SELECT DISTINCT ON (UPPER(TRIM(nopolisi)))
                        source_system, source_priority, TRIM(idkendaraan) AS kode,
                        TRIM(nopolisi) AS no_pelat
                    FROM legacy_master_import_server.kendaraan
                    WHERE NULLIF(TRIM(nopolisi), '') IS NOT NULL
                    ORDER BY UPPER(TRIM(nopolisi)), source_priority ASC, staging_id ASC
                )
                INSERT INTO legacy_master_merge_audit (
                    batch_code, target_table, action, source_system,
                    source_priority, legacy_code, target_id, message
                )
                SELECT
                    %s, 'armada', 'insert', p.source_system,
                    p.source_priority, p.kode, a.id::text,
                    'Inserted armada from legacy kendaraan'
                FROM picked p
                JOIN armada a ON UPPER(TRIM(a.no_pelat)) = UPPER(TRIM(p.no_pelat))
                WHERE NOT EXISTS (
                    SELECT 1 FROM legacy_master_merge_audit au
                    WHERE au.batch_code = %s
                      AND au.target_table = 'armada'
                      AND au.action = 'insert'
                      AND au.legacy_code = p.kode
                )
                """,
                (batch_code, batch_code),
            )
            sync_sequence(cur, "armada")
    return {"target": "armada", "type_insert": type_insert, "vehicle_insert": vehicle_insert}


def parse_numeric_expr(column):
    return f"COALESCE(NULLIF(REGEXP_REPLACE(COALESCE({column}, '0'), '[^0-9.-]', '', 'g'), ''), '0')::numeric"


def merge_wms_kartu(cur, batch_code, apply):
    target = "legacy_dist_wms_kartu_stok"
    if not table_exists(cur, target):
        cur.execute(
            """
            CREATE TABLE legacy_dist_wms_kartu_stok (
                source_id INTEGER PRIMARY KEY,
                nota TEXT,
                tanggal DATE,
                no_reff TEXT,
                keterangan TEXT,
                jenis_transaksi TEXT,
                kode_rak TEXT,
                kode_barang TEXT,
                nama_barang TEXT,
                user_add TEXT,
                urut_tanggal TIMESTAMP,
                harga NUMERIC,
                ct NUMERIC,
                pc NUMERIC,
                per_unit NUMERIC,
                ed DATE,
                no_urut_header INTEGER,
                no_urut_detail INTEGER,
                masuk NUMERIC,
                keluar NUMERIC,
                principle TEXT,
                batch_number TEXT,
                imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    backup_table(cur, target, batch_code, apply)
    source_rows = scalar(cur, "SELECT COUNT(*) FROM legacy_master_import_server.wmskartustok") or 0
    inserts = scalar(
        cur,
        """
        SELECT COUNT(*)
        FROM legacy_master_import_server.wmskartustok w
        LEFT JOIN legacy_dist_wms_kartu_stok k ON k.source_id = w.staging_id::integer
        WHERE k.source_id IS NULL
        """
    ) or 0
    if apply and inserts:
        cur.execute(
            f"""
            INSERT INTO legacy_dist_wms_kartu_stok (
                source_id, nota, tanggal, no_reff, keterangan, jenis_transaksi,
                kode_rak, kode_barang, nama_barang, user_add, urut_tanggal,
                harga, ct, pc, per_unit, ed, no_urut_header, no_urut_detail,
                masuk, keluar, principle, batch_number
            )
            SELECT
                staging_id::integer,
                NULLIF(TRIM(w.nota), ''),
                CASE WHEN TRIM(COALESCE(w.tanggal, '')) ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}' THEN LEFT(TRIM(w.tanggal), 10)::date ELSE NULL END,
                NULLIF(TRIM(w.noreff), ''),
                NULLIF(TRIM(w.keterangan), ''),
                NULLIF(TRIM(w.jenistransaksi), ''),
                NULLIF(TRIM(w.koderak), ''),
                NULLIF(TRIM(w.kodebarang), ''),
                NULLIF(TRIM(w.namabarang), ''),
                NULLIF(TRIM(w.useradd), ''),
                CASE WHEN TRIM(COALESCE(w.uruttanggal, '')) ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}' THEN TRIM(w.uruttanggal)::timestamp ELSE NULL END,
                {parse_numeric_expr('w.harga')},
                {parse_numeric_expr('w.ct')},
                {parse_numeric_expr('w.pc')},
                {parse_numeric_expr('w.perunit')},
                CASE WHEN TRIM(COALESCE(w.ed, '')) ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}' THEN LEFT(TRIM(w.ed), 10)::date ELSE NULL END,
                NULLIF(REGEXP_REPLACE(COALESCE(w.nourutheader, ''), '[^0-9-]', '', 'g'), '')::integer,
                NULLIF(REGEXP_REPLACE(COALESCE(w.nourutdetail, ''), '[^0-9-]', '', 'g'), '')::integer,
                {parse_numeric_expr('w.masuk')},
                {parse_numeric_expr('w.keluar')},
                NULLIF(TRIM(w.principle), ''),
                NULLIF(TRIM(w.batchnumber), '')
            FROM legacy_master_import_server.wmskartustok w
            LEFT JOIN legacy_dist_wms_kartu_stok k ON k.source_id = w.staging_id::integer
            WHERE k.source_id IS NULL
            """
        )
        cur.execute(
            """
            INSERT INTO legacy_master_merge_audit (
                batch_code, target_table, action, source_system,
                source_priority, legacy_code, target_id, message
            )
            VALUES (%s, 'legacy_dist_wms_kartu_stok', 'insert', NULL, NULL, NULL, NULL, %s)
            """,
            (batch_code, f"Copied {inserts} WMS kartu stok rows from legacy staging"),
        )
    return {"target": target, "source_rows": source_rows, "insert": inserts}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", default="legacy_master_import_server")
    parser.add_argument("--batch-code", default="legacy-support-merge-20260718")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    conn = connect()
    try:
        cur = conn.cursor()
        ensure_audit(cur)
        results = [
            merge_simple_name(cur, args.batch_code, args.apply, "barangbrand", "produk_brand"),
            merge_simple_name(cur, args.batch_code, args.apply, "barangsatuan", "produk_satuan"),
            merge_subbrand(cur, args.batch_code, args.apply),
            merge_armada(cur, args.batch_code, args.apply),
            merge_wms_kartu(cur, args.batch_code, args.apply),
        ]
        results.extend(merge_reference_copy(cur, args.batch_code, args.apply))
        if args.apply:
            conn.commit()
        else:
            conn.rollback()
        print("mode\t" + ("APPLY" if args.apply else "DRY_RUN"))
        for item in results:
            print("\t".join([item["target"]] + [f"{k}={v}" for k, v in item.items() if k != "target"]))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
