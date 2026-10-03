-- Seed fitur_mal 27-33 dan mapping awal Jurnal Setting untuk Diskon Penjualan Sales Order.
-- Jalankan manual di Adminer/psql memakai user owner/migration.
--
-- Catatan akuntansi nomor 33:
--   Debit  : Diskon Penjualan
--   Kredit : Penjualan
-- Pola ini menjaga piutang tetap net sesuai invoice, tetapi laporan tetap bisa
-- menampilkan gross penjualan dan diskon penjualan secara terpisah.

BEGIN;

INSERT INTO fitur_mal (id_fitur_mal, nama_fitur_mal)
VALUES
    (27, 'Sales Canvas - Request Approved'),
    (28, 'Sales Canvas - Order'),
    (29, 'Sales Canvas - Pembayaran'),
    (30, 'Sales Canvas - Retur Stock'),
    (31, 'Credit Note - Refund'),
    (32, 'Retur Sales - Pembentukan Credit Note'),
    (33, 'Sales Order - Diskon Penjualan')
ON CONFLICT (id_fitur_mal) DO UPDATE
SET nama_fitur_mal = EXCLUDED.nama_fitur_mal;

DO $$
DECLARE
    seq_name TEXT := pg_get_serial_sequence('fitur_mal', 'id_fitur_mal');
BEGIN
    IF seq_name IS NOT NULL THEN
        EXECUTE format(
            'SELECT setval(%L, COALESCE((SELECT MAX(id_fitur_mal) FROM fitur_mal), 1), TRUE)',
            seq_name
        );
    END IF;
END $$;

DO $$
DECLARE
    seq_name TEXT := pg_get_serial_sequence('source_modul', 'id_source_data');
BEGIN
    IF seq_name IS NOT NULL THEN
        EXECUTE format(
            'SELECT setval(%L, COALESCE((SELECT MAX(id_source_data) FROM source_modul), 1), TRUE)',
            seq_name
        );
    END IF;
END $$;

WITH seed_sources(nama_kolom_view) AS (
    VALUES
        ('Nominal Sales Canvas Request Approved'),
        ('Nominal Sales Canvas Order'),
        ('Nominal Pembayaran Canvas'),
        ('Nominal Retur Stock Canvas'),
        ('Nominal Refund Credit Note'),
        ('Nominal Pembentukan Credit Note Retur'),
        ('Nominal Diskon Penjualan Sales Order')
)
INSERT INTO source_modul (id_modul, nama_tabel, nama_kolom_db, nama_kolom_view)
SELECT
    8,
    'PubSub_Payload',
    'amount',
    ss.nama_kolom_view
FROM seed_sources ss
WHERE NOT EXISTS (
    SELECT 1
    FROM source_modul sm
    WHERE sm.nama_tabel = 'PubSub_Payload'
      AND sm.nama_kolom_db = 'amount'
      AND sm.nama_kolom_view = ss.nama_kolom_view
);

DO $$
DECLARE
    seq_name TEXT := pg_get_serial_sequence('source_modul', 'id_source_data');
BEGIN
    IF seq_name IS NOT NULL THEN
        EXECUTE format(
            'SELECT setval(%L, COALESCE((SELECT MAX(id_source_data) FROM source_modul), 1), TRUE)',
            seq_name
        );
    END IF;
END $$;

-- COA operasional canvas. Jika akun ini belum ada, dibuat sebagai akun aset
-- persediaan supaya perpindahan gudang <-> canvas tidak bercampur dengan
-- piutang/penjualan.
INSERT INTO coa (
    id_kategori,
    id_perusahaan,
    nomor_akun,
    nama_akun,
    is_active,
    created_by,
    is_deleted
)
SELECT
    16,
    p.id,
    '1-10290',
    'Persediaan Canvas',
    TRUE,
    1,
    FALSE
FROM perusahaan p
WHERE NOT EXISTS (
    SELECT 1
    FROM coa c
    WHERE c.id_perusahaan = p.id
      AND LOWER(c.nama_akun) IN ('persediaan canvas', 'persediaan kanvas')
      AND COALESCE(c.is_deleted, FALSE) = FALSE
);

DO $$
DECLARE
    seq_name TEXT := pg_get_serial_sequence('coa', 'id_coa');
BEGIN
    IF seq_name IS NOT NULL THEN
        EXECUTE format(
            'SELECT setval(%L, COALESCE((SELECT MAX(id_coa) FROM coa), 1), TRUE)',
            seq_name
        );
    END IF;
END $$;

-- Mapping otomatis hanya untuk perusahaan yang sudah punya COA:
-- "Diskon Penjualan" dan akun "Penjualan" generic.
DO $$
DECLARE
    seq_name TEXT := pg_get_serial_sequence('jurnal_mal', 'id_jurnal_mal');
BEGIN
    IF seq_name IS NOT NULL THEN
        EXECUTE format(
            'SELECT setval(%L, COALESCE((SELECT MAX(id_jurnal_mal) FROM jurnal_mal), 1), TRUE)',
            seq_name
        );
    END IF;
END $$;

WITH
source_discount AS (
    SELECT id_source_data
    FROM source_modul
    WHERE nama_tabel = 'PubSub_Payload'
      AND nama_kolom_db = 'amount'
      AND nama_kolom_view = 'Nominal Diskon Penjualan Sales Order'
    ORDER BY id_source_data
    LIMIT 1
),
coa_diskon AS (
    SELECT DISTINCT ON (id_perusahaan)
        id_perusahaan,
        id_coa
    FROM coa
    WHERE COALESCE(is_active, TRUE) = TRUE
      AND LOWER(nama_akun) = 'diskon penjualan'
    ORDER BY id_perusahaan, nomor_akun
),
coa_penjualan AS (
    SELECT DISTINCT ON (id_perusahaan)
        id_perusahaan,
        id_coa
    FROM coa
    WHERE COALESCE(is_active, TRUE) = TRUE
      AND LOWER(nama_akun) IN ('penjualan', 'pendapatan penjualan')
      AND LOWER(nama_akun) NOT LIKE '%diskon%'
      AND LOWER(nama_akun) NOT LIKE '%retur%'
    ORDER BY id_perusahaan, nomor_akun
),
insert_header AS (
    INSERT INTO jurnal_mal (
        id_perusahaan,
        id_fitur_mal,
        main_coa_id,
        nama_mal,
        created_by
    )
    SELECT
        cd.id_perusahaan,
        33,
        cd.id_coa,
        'Diskon Penjualan Sales Order',
        1
    FROM coa_diskon cd
    JOIN coa_penjualan cp ON cp.id_perusahaan = cd.id_perusahaan
    WHERE NOT EXISTS (
        SELECT 1
        FROM jurnal_mal jm
        WHERE jm.id_perusahaan = cd.id_perusahaan
          AND jm.id_fitur_mal = 33
          AND COALESCE(jm.is_deleted, FALSE) = FALSE
    )
    RETURNING id_jurnal_mal
),
target_mapping AS (
    SELECT
        jm.id_jurnal_mal,
        cd.id_coa AS id_coa_diskon,
        cp.id_coa AS id_coa_penjualan,
        sd.id_source_data
    FROM jurnal_mal jm
    JOIN coa_diskon cd ON cd.id_perusahaan = jm.id_perusahaan
    JOIN coa_penjualan cp ON cp.id_perusahaan = jm.id_perusahaan
    CROSS JOIN source_discount sd
    WHERE jm.id_fitur_mal = 33
      AND COALESCE(jm.is_deleted, FALSE) = FALSE
)
INSERT INTO jurnal_mal_detail (
    id_jurnal_mal,
    id_source_data,
    id_coa,
    type,
    urutan,
    created_by,
    is_deleted
)
SELECT
    tm.id_jurnal_mal,
    tm.id_source_data,
    v.id_coa,
    v.type,
    v.urutan,
    1,
    FALSE
FROM target_mapping tm
CROSS JOIN LATERAL (
    VALUES
        (tm.id_coa_diskon, 1, 1),
        (tm.id_coa_penjualan, 2, 2)
) AS v(id_coa, type, urutan)
WHERE NOT EXISTS (
    SELECT 1
    FROM jurnal_mal_detail jmd
    WHERE jmd.id_jurnal_mal = tm.id_jurnal_mal
      AND jmd.id_coa = v.id_coa
      AND jmd.type = v.type
      AND COALESCE(jmd.is_deleted, FALSE) = FALSE
);

DO $$
DECLARE
    seq_name TEXT := pg_get_serial_sequence('jurnal_mal', 'id_jurnal_mal');
BEGIN
    IF seq_name IS NOT NULL THEN
        EXECUTE format(
            'SELECT setval(%L, COALESCE((SELECT MAX(id_jurnal_mal) FROM jurnal_mal), 1), TRUE)',
            seq_name
        );
    END IF;
END $$;

DO $$
DECLARE
    seq_name TEXT := pg_get_serial_sequence('jurnal_mal_detail', 'id_mal_detail');
BEGIN
    IF seq_name IS NOT NULL THEN
        EXECUTE format(
            'SELECT setval(%L, COALESCE((SELECT MAX(id_mal_detail) FROM jurnal_mal_detail), 1), TRUE)',
            seq_name
        );
    END IF;
END $$;

COMMIT;
