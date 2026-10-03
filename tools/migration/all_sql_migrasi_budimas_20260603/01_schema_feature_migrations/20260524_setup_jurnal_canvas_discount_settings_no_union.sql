-- Versi aman Adminer: setup Jurnal Setting fitur 27-33 tanpa UNION ALL.
-- Jalankan full file ini dari BEGIN sampai COMMIT.

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

INSERT INTO source_modul (id_modul, nama_tabel, nama_kolom_db, nama_kolom_view)
SELECT 8, 'PubSub_Payload', 'amount', source_name
FROM (
    VALUES
        ('Nominal Sales Canvas Request Approved'),
        ('Nominal Sales Canvas Order'),
        ('Nominal Pembayaran Canvas'),
        ('Nominal Retur Stock Canvas'),
        ('Nominal Refund Credit Note'),
        ('Nominal Pembentukan Credit Note Retur'),
        ('Nominal Diskon Penjualan Sales Order')
) AS s(source_name)
WHERE NOT EXISTS (
    SELECT 1
    FROM source_modul sm
    WHERE sm.nama_tabel = 'PubSub_Payload'
      AND sm.nama_kolom_db = 'amount'
      AND sm.nama_kolom_view = s.source_name
);

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

WITH feature_config AS (
    SELECT *
    FROM (
        VALUES
            (27, 'Sales Canvas - Request Approved', 'Nominal Sales Canvas Request Approved', 'persediaan_canvas', 'persediaan'),
            (28, 'Sales Canvas - Order', 'Nominal Sales Canvas Order', 'piutang', 'penjualan'),
            (29, 'Sales Canvas - Pembayaran', 'Nominal Pembayaran Canvas', 'kas', 'piutang'),
            (30, 'Sales Canvas - Retur Stock', 'Nominal Retur Stock Canvas', 'persediaan', 'persediaan_canvas'),
            (31, 'Credit Note - Refund', 'Nominal Refund Credit Note', 'retur_penjualan', 'kas'),
            (32, 'Retur Sales - Pembentukan Credit Note', 'Nominal Pembentukan Credit Note Retur', 'retur_penjualan', 'piutang'),
            (33, 'Sales Order - Diskon Penjualan', 'Nominal Diskon Penjualan Sales Order', 'diskon_penjualan', 'penjualan')
    ) AS v(id_fitur_mal, nama_mal, source_name, debit_role, kredit_role)
),
source_lookup AS (
    SELECT nama_kolom_view, MIN(id_source_data) AS id_source_data
    FROM source_modul
    WHERE nama_tabel = 'PubSub_Payload'
      AND nama_kolom_db = 'amount'
    GROUP BY nama_kolom_view
),
eligible_mapping AS (
    SELECT
        fc.id_fitur_mal,
        fc.nama_mal,
        sl.id_source_data,
        perusahaan.id AS id_perusahaan,
        debit_coa.id_coa AS debit_coa_id,
        kredit_coa.id_coa AS kredit_coa_id
    FROM feature_config fc
    JOIN source_lookup sl ON sl.nama_kolom_view = fc.source_name
    JOIN perusahaan ON TRUE
    JOIN LATERAL (
        SELECT c.id_coa
        FROM coa c
        WHERE c.id_perusahaan = perusahaan.id
          AND COALESCE(c.is_active, TRUE) = TRUE
          AND COALESCE(c.is_deleted, FALSE) = FALSE
          AND (
              (fc.debit_role = 'piutang' AND LOWER(c.nama_akun) = 'piutang usaha')
              OR (fc.debit_role = 'penjualan' AND LOWER(c.nama_akun) IN ('penjualan', 'pendapatan penjualan') AND LOWER(c.nama_akun) NOT LIKE '%diskon%' AND LOWER(c.nama_akun) NOT LIKE '%retur%')
              OR (fc.debit_role = 'diskon_penjualan' AND LOWER(c.nama_akun) = 'diskon penjualan')
              OR (fc.debit_role = 'retur_penjualan' AND LOWER(c.nama_akun) = 'retur penjualan')
              OR (fc.debit_role = 'kas' AND LOWER(c.nama_akun) IN ('kas', 'kas besar', 'rekening bank'))
              OR (fc.debit_role = 'persediaan' AND LOWER(c.nama_akun) IN ('persediaan barang', 'persediaan'))
              OR (fc.debit_role = 'persediaan_canvas' AND LOWER(c.nama_akun) IN ('persediaan canvas', 'persediaan kanvas'))
          )
        ORDER BY
            CASE
                WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                ELSE 3
            END,
            c.id_coa
        LIMIT 1
    ) debit_coa ON TRUE
    JOIN LATERAL (
        SELECT c.id_coa
        FROM coa c
        WHERE c.id_perusahaan = perusahaan.id
          AND COALESCE(c.is_active, TRUE) = TRUE
          AND COALESCE(c.is_deleted, FALSE) = FALSE
          AND (
              (fc.kredit_role = 'piutang' AND LOWER(c.nama_akun) = 'piutang usaha')
              OR (fc.kredit_role = 'penjualan' AND LOWER(c.nama_akun) IN ('penjualan', 'pendapatan penjualan') AND LOWER(c.nama_akun) NOT LIKE '%diskon%' AND LOWER(c.nama_akun) NOT LIKE '%retur%')
              OR (fc.kredit_role = 'diskon_penjualan' AND LOWER(c.nama_akun) = 'diskon penjualan')
              OR (fc.kredit_role = 'retur_penjualan' AND LOWER(c.nama_akun) = 'retur penjualan')
              OR (fc.kredit_role = 'kas' AND LOWER(c.nama_akun) IN ('kas', 'kas besar', 'rekening bank'))
              OR (fc.kredit_role = 'persediaan' AND LOWER(c.nama_akun) IN ('persediaan barang', 'persediaan'))
              OR (fc.kredit_role = 'persediaan_canvas' AND LOWER(c.nama_akun) IN ('persediaan canvas', 'persediaan kanvas'))
          )
        ORDER BY
            CASE
                WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                ELSE 3
            END,
            c.id_coa
        LIMIT 1
    ) kredit_coa ON TRUE
),
insert_headers AS (
    INSERT INTO jurnal_mal (
        id_perusahaan,
        id_fitur_mal,
        main_coa_id,
        nama_mal,
        created_by
    )
    SELECT
        em.id_perusahaan,
        em.id_fitur_mal,
        em.debit_coa_id,
        em.nama_mal,
        1
    FROM eligible_mapping em
    WHERE NOT EXISTS (
        SELECT 1
        FROM jurnal_mal jm
        WHERE jm.id_perusahaan = em.id_perusahaan
          AND jm.id_fitur_mal = em.id_fitur_mal
          AND COALESCE(jm.is_deleted, FALSE) = FALSE
    )
    RETURNING id_jurnal_mal
),
target_mapping AS (
    SELECT
        jm.id_jurnal_mal,
        em.id_source_data,
        em.debit_coa_id,
        em.kredit_coa_id
    FROM jurnal_mal jm
    JOIN eligible_mapping em
        ON em.id_perusahaan = jm.id_perusahaan
       AND em.id_fitur_mal = jm.id_fitur_mal
    WHERE COALESCE(jm.is_deleted, FALSE) = FALSE
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
    detail_account.id_coa,
    detail_account.type,
    detail_account.urutan,
    1,
    FALSE
FROM target_mapping tm
CROSS JOIN LATERAL (
    VALUES
        (tm.debit_coa_id, 1, 1),
        (tm.kredit_coa_id, 2, 2)
) AS detail_account(id_coa, type, urutan)
WHERE NOT EXISTS (
    SELECT 1
    FROM jurnal_mal_detail jmd
    WHERE jmd.id_jurnal_mal = tm.id_jurnal_mal
      AND jmd.id_coa = detail_account.id_coa
      AND jmd.type = detail_account.type
      AND COALESCE(jmd.is_deleted, FALSE) = FALSE
);

DO $$
DECLARE
    seq_name TEXT;
BEGIN
    seq_name := pg_get_serial_sequence('fitur_mal', 'id_fitur_mal');
    IF seq_name IS NOT NULL THEN
        EXECUTE format('SELECT setval(%L, COALESCE((SELECT MAX(id_fitur_mal) FROM fitur_mal), 1), TRUE)', seq_name);
    END IF;

    seq_name := pg_get_serial_sequence('source_modul', 'id_source_data');
    IF seq_name IS NOT NULL THEN
        EXECUTE format('SELECT setval(%L, COALESCE((SELECT MAX(id_source_data) FROM source_modul), 1), TRUE)', seq_name);
    END IF;

    seq_name := pg_get_serial_sequence('coa', 'id_coa');
    IF seq_name IS NOT NULL THEN
        EXECUTE format('SELECT setval(%L, COALESCE((SELECT MAX(id_coa) FROM coa), 1), TRUE)', seq_name);
    END IF;

    seq_name := pg_get_serial_sequence('jurnal_mal', 'id_jurnal_mal');
    IF seq_name IS NOT NULL THEN
        EXECUTE format('SELECT setval(%L, COALESCE((SELECT MAX(id_jurnal_mal) FROM jurnal_mal), 1), TRUE)', seq_name);
    END IF;

    seq_name := pg_get_serial_sequence('jurnal_mal_detail', 'id_mal_detail');
    IF seq_name IS NOT NULL THEN
        EXECUTE format('SELECT setval(%L, COALESCE((SELECT MAX(id_mal_detail) FROM jurnal_mal_detail), 1), TRUE)', seq_name);
    END IF;
END $$;

COMMIT;
