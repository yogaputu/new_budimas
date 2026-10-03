-- Adminer minimal runner untuk setup Jurnal Setting fitur 27-33.
-- Aman dijalankan ulang. Jika sebelumnya ada transaksi gagal, ROLLBACK dulu.

ROLLBACK;

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

DO $$
DECLARE
    cfg RECORD;
    company RECORD;
    source_id INTEGER;
    debit_coa_id INTEGER;
    kredit_coa_id INTEGER;
    header_id INTEGER;
BEGIN
    FOR cfg IN
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
    LOOP
        SELECT MIN(id_source_data)
        INTO source_id
        FROM source_modul
        WHERE nama_tabel = 'PubSub_Payload'
          AND nama_kolom_db = 'amount'
          AND nama_kolom_view = cfg.source_name;

        IF source_id IS NULL THEN
            CONTINUE;
        END IF;

        FOR company IN SELECT id FROM perusahaan ORDER BY id LOOP
            SELECT id_coa
            INTO debit_coa_id
            FROM coa
            WHERE id_perusahaan = company.id
              AND COALESCE(is_active, TRUE) = TRUE
              AND COALESCE(is_deleted, FALSE) = FALSE
              AND (
                  (cfg.debit_role = 'piutang' AND LOWER(nama_akun) = 'piutang usaha')
                  OR (cfg.debit_role = 'penjualan' AND LOWER(nama_akun) IN ('penjualan', 'pendapatan penjualan') AND LOWER(nama_akun) NOT LIKE '%diskon%' AND LOWER(nama_akun) NOT LIKE '%retur%')
                  OR (cfg.debit_role = 'diskon_penjualan' AND LOWER(nama_akun) = 'diskon penjualan')
                  OR (cfg.debit_role = 'retur_penjualan' AND LOWER(nama_akun) = 'retur penjualan')
                  OR (cfg.debit_role = 'kas' AND LOWER(nama_akun) IN ('kas', 'kas besar', 'rekening bank'))
                  OR (cfg.debit_role = 'persediaan' AND LOWER(nama_akun) IN ('persediaan barang', 'persediaan'))
                  OR (cfg.debit_role = 'persediaan_canvas' AND LOWER(nama_akun) IN ('persediaan canvas', 'persediaan kanvas'))
              )
            ORDER BY
                CASE
                    WHEN LOWER(nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                id_coa
            LIMIT 1;

            SELECT id_coa
            INTO kredit_coa_id
            FROM coa
            WHERE id_perusahaan = company.id
              AND COALESCE(is_active, TRUE) = TRUE
              AND COALESCE(is_deleted, FALSE) = FALSE
              AND (
                  (cfg.kredit_role = 'piutang' AND LOWER(nama_akun) = 'piutang usaha')
                  OR (cfg.kredit_role = 'penjualan' AND LOWER(nama_akun) IN ('penjualan', 'pendapatan penjualan') AND LOWER(nama_akun) NOT LIKE '%diskon%' AND LOWER(nama_akun) NOT LIKE '%retur%')
                  OR (cfg.kredit_role = 'diskon_penjualan' AND LOWER(nama_akun) = 'diskon penjualan')
                  OR (cfg.kredit_role = 'retur_penjualan' AND LOWER(nama_akun) = 'retur penjualan')
                  OR (cfg.kredit_role = 'kas' AND LOWER(nama_akun) IN ('kas', 'kas besar', 'rekening bank'))
                  OR (cfg.kredit_role = 'persediaan' AND LOWER(nama_akun) IN ('persediaan barang', 'persediaan'))
                  OR (cfg.kredit_role = 'persediaan_canvas' AND LOWER(nama_akun) IN ('persediaan canvas', 'persediaan kanvas'))
              )
            ORDER BY
                CASE
                    WHEN LOWER(nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                id_coa
            LIMIT 1;

            IF debit_coa_id IS NULL OR kredit_coa_id IS NULL THEN
                CONTINUE;
            END IF;

            SELECT id_jurnal_mal
            INTO header_id
            FROM jurnal_mal
            WHERE id_perusahaan = company.id
              AND id_fitur_mal = cfg.id_fitur_mal
              AND COALESCE(is_deleted, FALSE) = FALSE
            ORDER BY id_jurnal_mal
            LIMIT 1;

            IF header_id IS NULL THEN
                INSERT INTO jurnal_mal (
                    id_perusahaan,
                    id_fitur_mal,
                    main_coa_id,
                    nama_mal,
                    created_by
                )
                VALUES (
                    company.id,
                    cfg.id_fitur_mal,
                    debit_coa_id,
                    cfg.nama_mal,
                    1
                )
                RETURNING id_jurnal_mal INTO header_id;
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM jurnal_mal_detail
                WHERE id_jurnal_mal = header_id
                  AND id_coa = debit_coa_id
                  AND type = 1
                  AND COALESCE(is_deleted, FALSE) = FALSE
            ) THEN
                INSERT INTO jurnal_mal_detail (
                    id_jurnal_mal,
                    id_source_data,
                    id_coa,
                    type,
                    urutan,
                    created_by,
                    is_deleted
                )
                VALUES (header_id, source_id, debit_coa_id, 1, 1, 1, FALSE);
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM jurnal_mal_detail
                WHERE id_jurnal_mal = header_id
                  AND id_coa = kredit_coa_id
                  AND type = 2
                  AND COALESCE(is_deleted, FALSE) = FALSE
            ) THEN
                INSERT INTO jurnal_mal_detail (
                    id_jurnal_mal,
                    id_source_data,
                    id_coa,
                    type,
                    urutan,
                    created_by,
                    is_deleted
                )
                VALUES (header_id, source_id, kredit_coa_id, 2, 2, 1, FALSE);
            END IF;
        END LOOP;
    END LOOP;
END $$;

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
