-- Adminer plain runner untuk setup Jurnal Setting fitur 27-33.
-- Tanpa DO , tanpa BEGIN, tanpa UNION. Aman dijalankan ulang.
ROLLBACK;

INSERT INTO fitur_mal (id_fitur_mal, nama_fitur_mal) VALUES
    (27, 'Sales Canvas - Request Approved'),
    (28, 'Sales Canvas - Order'),
    (29, 'Sales Canvas - Pembayaran'),
    (30, 'Sales Canvas - Retur Stock'),
    (31, 'Credit Note - Refund'),
    (32, 'Retur Sales - Pembentukan Credit Note'),
    (33, 'Sales Order - Diskon Penjualan')
ON CONFLICT (id_fitur_mal) DO UPDATE SET nama_fitur_mal = EXCLUDED.nama_fitur_mal;

INSERT INTO source_modul (id_modul, nama_tabel, nama_kolom_db, nama_kolom_view)
SELECT 8, 'PubSub_Payload', 'amount', 'Nominal Sales Canvas Request Approved'
WHERE NOT EXISTS (SELECT 1 FROM source_modul WHERE nama_tabel = 'PubSub_Payload' AND nama_kolom_db = 'amount' AND nama_kolom_view = 'Nominal Sales Canvas Request Approved');

INSERT INTO source_modul (id_modul, nama_tabel, nama_kolom_db, nama_kolom_view)
SELECT 8, 'PubSub_Payload', 'amount', 'Nominal Sales Canvas Order'
WHERE NOT EXISTS (SELECT 1 FROM source_modul WHERE nama_tabel = 'PubSub_Payload' AND nama_kolom_db = 'amount' AND nama_kolom_view = 'Nominal Sales Canvas Order');

INSERT INTO source_modul (id_modul, nama_tabel, nama_kolom_db, nama_kolom_view)
SELECT 8, 'PubSub_Payload', 'amount', 'Nominal Pembayaran Canvas'
WHERE NOT EXISTS (SELECT 1 FROM source_modul WHERE nama_tabel = 'PubSub_Payload' AND nama_kolom_db = 'amount' AND nama_kolom_view = 'Nominal Pembayaran Canvas');

INSERT INTO source_modul (id_modul, nama_tabel, nama_kolom_db, nama_kolom_view)
SELECT 8, 'PubSub_Payload', 'amount', 'Nominal Retur Stock Canvas'
WHERE NOT EXISTS (SELECT 1 FROM source_modul WHERE nama_tabel = 'PubSub_Payload' AND nama_kolom_db = 'amount' AND nama_kolom_view = 'Nominal Retur Stock Canvas');

INSERT INTO source_modul (id_modul, nama_tabel, nama_kolom_db, nama_kolom_view)
SELECT 8, 'PubSub_Payload', 'amount', 'Nominal Refund Credit Note'
WHERE NOT EXISTS (SELECT 1 FROM source_modul WHERE nama_tabel = 'PubSub_Payload' AND nama_kolom_db = 'amount' AND nama_kolom_view = 'Nominal Refund Credit Note');

INSERT INTO source_modul (id_modul, nama_tabel, nama_kolom_db, nama_kolom_view)
SELECT 8, 'PubSub_Payload', 'amount', 'Nominal Pembentukan Credit Note Retur'
WHERE NOT EXISTS (SELECT 1 FROM source_modul WHERE nama_tabel = 'PubSub_Payload' AND nama_kolom_db = 'amount' AND nama_kolom_view = 'Nominal Pembentukan Credit Note Retur');

INSERT INTO source_modul (id_modul, nama_tabel, nama_kolom_db, nama_kolom_view)
SELECT 8, 'PubSub_Payload', 'amount', 'Nominal Diskon Penjualan Sales Order'
WHERE NOT EXISTS (SELECT 1 FROM source_modul WHERE nama_tabel = 'PubSub_Payload' AND nama_kolom_db = 'amount' AND nama_kolom_view = 'Nominal Diskon Penjualan Sales Order');

INSERT INTO coa (id_kategori, id_perusahaan, nomor_akun, nama_akun, is_active, created_by, is_deleted)
SELECT 16, p.id, '1-10290', 'Persediaan Canvas', TRUE, 1, FALSE
FROM perusahaan p
WHERE NOT EXISTS (SELECT 1 FROM coa c WHERE c.id_perusahaan = p.id AND LOWER(c.nama_akun) IN ('persediaan canvas', 'persediaan kanvas') AND COALESCE(c.is_deleted, FALSE) = FALSE);

-- 27 - Sales Canvas - Request Approved
INSERT INTO jurnal_mal (id_perusahaan, id_fitur_mal, main_coa_id, nama_mal, created_by)
SELECT p.id, 27, debit.id_coa, 'Sales Canvas - Request Approved', 1
FROM perusahaan p
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = p.id AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) IN ('persediaan canvas', 'persediaan kanvas')) ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) debit ON TRUE
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = p.id AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) IN ('persediaan barang', 'persediaan')) ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) kredit ON TRUE
WHERE NOT EXISTS (SELECT 1 FROM jurnal_mal jm WHERE jm.id_perusahaan = p.id AND jm.id_fitur_mal = 27 AND COALESCE(jm.is_deleted, FALSE) = FALSE);

INSERT INTO jurnal_mal_detail (id_jurnal_mal, id_source_data, id_coa, type, urutan, created_by, is_deleted)
SELECT jm.id_jurnal_mal, sm.id_source_data, debit.id_coa, 1, 1, 1, FALSE
FROM jurnal_mal jm
JOIN source_modul sm ON sm.nama_tabel = 'PubSub_Payload' AND sm.nama_kolom_db = 'amount' AND sm.nama_kolom_view = 'Nominal Sales Canvas Request Approved'
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = jm.id_perusahaan AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) IN ('persediaan canvas', 'persediaan kanvas')) ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) debit ON TRUE
WHERE jm.id_fitur_mal = 27 AND COALESCE(jm.is_deleted, FALSE) = FALSE
  AND NOT EXISTS (SELECT 1 FROM jurnal_mal_detail jmd WHERE jmd.id_jurnal_mal = jm.id_jurnal_mal AND jmd.id_coa = debit.id_coa AND jmd.type = 1 AND COALESCE(jmd.is_deleted, FALSE) = FALSE);

INSERT INTO jurnal_mal_detail (id_jurnal_mal, id_source_data, id_coa, type, urutan, created_by, is_deleted)
SELECT jm.id_jurnal_mal, sm.id_source_data, kredit.id_coa, 2, 2, 1, FALSE
FROM jurnal_mal jm
JOIN source_modul sm ON sm.nama_tabel = 'PubSub_Payload' AND sm.nama_kolom_db = 'amount' AND sm.nama_kolom_view = 'Nominal Sales Canvas Request Approved'
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = jm.id_perusahaan AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) IN ('persediaan barang', 'persediaan')) ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) kredit ON TRUE
WHERE jm.id_fitur_mal = 27 AND COALESCE(jm.is_deleted, FALSE) = FALSE
  AND NOT EXISTS (SELECT 1 FROM jurnal_mal_detail jmd WHERE jmd.id_jurnal_mal = jm.id_jurnal_mal AND jmd.id_coa = kredit.id_coa AND jmd.type = 2 AND COALESCE(jmd.is_deleted, FALSE) = FALSE);

-- 28 - Sales Canvas - Order
INSERT INTO jurnal_mal (id_perusahaan, id_fitur_mal, main_coa_id, nama_mal, created_by)
SELECT p.id, 28, debit.id_coa, 'Sales Canvas - Order', 1
FROM perusahaan p
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = p.id AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) = 'piutang usaha') ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) debit ON TRUE
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = p.id AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) IN ('penjualan', 'pendapatan penjualan') AND LOWER(c.nama_akun) NOT LIKE '%diskon%' AND LOWER(c.nama_akun) NOT LIKE '%retur%') ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) kredit ON TRUE
WHERE NOT EXISTS (SELECT 1 FROM jurnal_mal jm WHERE jm.id_perusahaan = p.id AND jm.id_fitur_mal = 28 AND COALESCE(jm.is_deleted, FALSE) = FALSE);

INSERT INTO jurnal_mal_detail (id_jurnal_mal, id_source_data, id_coa, type, urutan, created_by, is_deleted)
SELECT jm.id_jurnal_mal, sm.id_source_data, debit.id_coa, 1, 1, 1, FALSE
FROM jurnal_mal jm
JOIN source_modul sm ON sm.nama_tabel = 'PubSub_Payload' AND sm.nama_kolom_db = 'amount' AND sm.nama_kolom_view = 'Nominal Sales Canvas Order'
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = jm.id_perusahaan AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) = 'piutang usaha') ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) debit ON TRUE
WHERE jm.id_fitur_mal = 28 AND COALESCE(jm.is_deleted, FALSE) = FALSE
  AND NOT EXISTS (SELECT 1 FROM jurnal_mal_detail jmd WHERE jmd.id_jurnal_mal = jm.id_jurnal_mal AND jmd.id_coa = debit.id_coa AND jmd.type = 1 AND COALESCE(jmd.is_deleted, FALSE) = FALSE);

INSERT INTO jurnal_mal_detail (id_jurnal_mal, id_source_data, id_coa, type, urutan, created_by, is_deleted)
SELECT jm.id_jurnal_mal, sm.id_source_data, kredit.id_coa, 2, 2, 1, FALSE
FROM jurnal_mal jm
JOIN source_modul sm ON sm.nama_tabel = 'PubSub_Payload' AND sm.nama_kolom_db = 'amount' AND sm.nama_kolom_view = 'Nominal Sales Canvas Order'
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = jm.id_perusahaan AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) IN ('penjualan', 'pendapatan penjualan') AND LOWER(c.nama_akun) NOT LIKE '%diskon%' AND LOWER(c.nama_akun) NOT LIKE '%retur%') ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) kredit ON TRUE
WHERE jm.id_fitur_mal = 28 AND COALESCE(jm.is_deleted, FALSE) = FALSE
  AND NOT EXISTS (SELECT 1 FROM jurnal_mal_detail jmd WHERE jmd.id_jurnal_mal = jm.id_jurnal_mal AND jmd.id_coa = kredit.id_coa AND jmd.type = 2 AND COALESCE(jmd.is_deleted, FALSE) = FALSE);

-- 29 - Sales Canvas - Pembayaran
INSERT INTO jurnal_mal (id_perusahaan, id_fitur_mal, main_coa_id, nama_mal, created_by)
SELECT p.id, 29, debit.id_coa, 'Sales Canvas - Pembayaran', 1
FROM perusahaan p
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = p.id AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) IN ('kas', 'kas besar', 'rekening bank')) ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) debit ON TRUE
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = p.id AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) = 'piutang usaha') ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) kredit ON TRUE
WHERE NOT EXISTS (SELECT 1 FROM jurnal_mal jm WHERE jm.id_perusahaan = p.id AND jm.id_fitur_mal = 29 AND COALESCE(jm.is_deleted, FALSE) = FALSE);

INSERT INTO jurnal_mal_detail (id_jurnal_mal, id_source_data, id_coa, type, urutan, created_by, is_deleted)
SELECT jm.id_jurnal_mal, sm.id_source_data, debit.id_coa, 1, 1, 1, FALSE
FROM jurnal_mal jm
JOIN source_modul sm ON sm.nama_tabel = 'PubSub_Payload' AND sm.nama_kolom_db = 'amount' AND sm.nama_kolom_view = 'Nominal Pembayaran Canvas'
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = jm.id_perusahaan AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) IN ('kas', 'kas besar', 'rekening bank')) ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) debit ON TRUE
WHERE jm.id_fitur_mal = 29 AND COALESCE(jm.is_deleted, FALSE) = FALSE
  AND NOT EXISTS (SELECT 1 FROM jurnal_mal_detail jmd WHERE jmd.id_jurnal_mal = jm.id_jurnal_mal AND jmd.id_coa = debit.id_coa AND jmd.type = 1 AND COALESCE(jmd.is_deleted, FALSE) = FALSE);

INSERT INTO jurnal_mal_detail (id_jurnal_mal, id_source_data, id_coa, type, urutan, created_by, is_deleted)
SELECT jm.id_jurnal_mal, sm.id_source_data, kredit.id_coa, 2, 2, 1, FALSE
FROM jurnal_mal jm
JOIN source_modul sm ON sm.nama_tabel = 'PubSub_Payload' AND sm.nama_kolom_db = 'amount' AND sm.nama_kolom_view = 'Nominal Pembayaran Canvas'
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = jm.id_perusahaan AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) = 'piutang usaha') ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) kredit ON TRUE
WHERE jm.id_fitur_mal = 29 AND COALESCE(jm.is_deleted, FALSE) = FALSE
  AND NOT EXISTS (SELECT 1 FROM jurnal_mal_detail jmd WHERE jmd.id_jurnal_mal = jm.id_jurnal_mal AND jmd.id_coa = kredit.id_coa AND jmd.type = 2 AND COALESCE(jmd.is_deleted, FALSE) = FALSE);

-- 30 - Sales Canvas - Retur Stock
INSERT INTO jurnal_mal (id_perusahaan, id_fitur_mal, main_coa_id, nama_mal, created_by)
SELECT p.id, 30, debit.id_coa, 'Sales Canvas - Retur Stock', 1
FROM perusahaan p
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = p.id AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) IN ('persediaan barang', 'persediaan')) ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) debit ON TRUE
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = p.id AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) IN ('persediaan canvas', 'persediaan kanvas')) ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) kredit ON TRUE
WHERE NOT EXISTS (SELECT 1 FROM jurnal_mal jm WHERE jm.id_perusahaan = p.id AND jm.id_fitur_mal = 30 AND COALESCE(jm.is_deleted, FALSE) = FALSE);

INSERT INTO jurnal_mal_detail (id_jurnal_mal, id_source_data, id_coa, type, urutan, created_by, is_deleted)
SELECT jm.id_jurnal_mal, sm.id_source_data, debit.id_coa, 1, 1, 1, FALSE
FROM jurnal_mal jm
JOIN source_modul sm ON sm.nama_tabel = 'PubSub_Payload' AND sm.nama_kolom_db = 'amount' AND sm.nama_kolom_view = 'Nominal Retur Stock Canvas'
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = jm.id_perusahaan AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) IN ('persediaan barang', 'persediaan')) ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) debit ON TRUE
WHERE jm.id_fitur_mal = 30 AND COALESCE(jm.is_deleted, FALSE) = FALSE
  AND NOT EXISTS (SELECT 1 FROM jurnal_mal_detail jmd WHERE jmd.id_jurnal_mal = jm.id_jurnal_mal AND jmd.id_coa = debit.id_coa AND jmd.type = 1 AND COALESCE(jmd.is_deleted, FALSE) = FALSE);

INSERT INTO jurnal_mal_detail (id_jurnal_mal, id_source_data, id_coa, type, urutan, created_by, is_deleted)
SELECT jm.id_jurnal_mal, sm.id_source_data, kredit.id_coa, 2, 2, 1, FALSE
FROM jurnal_mal jm
JOIN source_modul sm ON sm.nama_tabel = 'PubSub_Payload' AND sm.nama_kolom_db = 'amount' AND sm.nama_kolom_view = 'Nominal Retur Stock Canvas'
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = jm.id_perusahaan AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) IN ('persediaan canvas', 'persediaan kanvas')) ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) kredit ON TRUE
WHERE jm.id_fitur_mal = 30 AND COALESCE(jm.is_deleted, FALSE) = FALSE
  AND NOT EXISTS (SELECT 1 FROM jurnal_mal_detail jmd WHERE jmd.id_jurnal_mal = jm.id_jurnal_mal AND jmd.id_coa = kredit.id_coa AND jmd.type = 2 AND COALESCE(jmd.is_deleted, FALSE) = FALSE);

-- 31 - Credit Note - Refund
INSERT INTO jurnal_mal (id_perusahaan, id_fitur_mal, main_coa_id, nama_mal, created_by)
SELECT p.id, 31, debit.id_coa, 'Credit Note - Refund', 1
FROM perusahaan p
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = p.id AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) = 'retur penjualan') ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) debit ON TRUE
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = p.id AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) IN ('kas', 'kas besar', 'rekening bank')) ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) kredit ON TRUE
WHERE NOT EXISTS (SELECT 1 FROM jurnal_mal jm WHERE jm.id_perusahaan = p.id AND jm.id_fitur_mal = 31 AND COALESCE(jm.is_deleted, FALSE) = FALSE);

INSERT INTO jurnal_mal_detail (id_jurnal_mal, id_source_data, id_coa, type, urutan, created_by, is_deleted)
SELECT jm.id_jurnal_mal, sm.id_source_data, debit.id_coa, 1, 1, 1, FALSE
FROM jurnal_mal jm
JOIN source_modul sm ON sm.nama_tabel = 'PubSub_Payload' AND sm.nama_kolom_db = 'amount' AND sm.nama_kolom_view = 'Nominal Refund Credit Note'
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = jm.id_perusahaan AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) = 'retur penjualan') ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) debit ON TRUE
WHERE jm.id_fitur_mal = 31 AND COALESCE(jm.is_deleted, FALSE) = FALSE
  AND NOT EXISTS (SELECT 1 FROM jurnal_mal_detail jmd WHERE jmd.id_jurnal_mal = jm.id_jurnal_mal AND jmd.id_coa = debit.id_coa AND jmd.type = 1 AND COALESCE(jmd.is_deleted, FALSE) = FALSE);

INSERT INTO jurnal_mal_detail (id_jurnal_mal, id_source_data, id_coa, type, urutan, created_by, is_deleted)
SELECT jm.id_jurnal_mal, sm.id_source_data, kredit.id_coa, 2, 2, 1, FALSE
FROM jurnal_mal jm
JOIN source_modul sm ON sm.nama_tabel = 'PubSub_Payload' AND sm.nama_kolom_db = 'amount' AND sm.nama_kolom_view = 'Nominal Refund Credit Note'
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = jm.id_perusahaan AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) IN ('kas', 'kas besar', 'rekening bank')) ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) kredit ON TRUE
WHERE jm.id_fitur_mal = 31 AND COALESCE(jm.is_deleted, FALSE) = FALSE
  AND NOT EXISTS (SELECT 1 FROM jurnal_mal_detail jmd WHERE jmd.id_jurnal_mal = jm.id_jurnal_mal AND jmd.id_coa = kredit.id_coa AND jmd.type = 2 AND COALESCE(jmd.is_deleted, FALSE) = FALSE);

-- 32 - Retur Sales - Pembentukan Credit Note
INSERT INTO jurnal_mal (id_perusahaan, id_fitur_mal, main_coa_id, nama_mal, created_by)
SELECT p.id, 32, debit.id_coa, 'Retur Sales - Pembentukan Credit Note', 1
FROM perusahaan p
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = p.id AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) = 'retur penjualan') ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) debit ON TRUE
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = p.id AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) = 'piutang usaha') ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) kredit ON TRUE
WHERE NOT EXISTS (SELECT 1 FROM jurnal_mal jm WHERE jm.id_perusahaan = p.id AND jm.id_fitur_mal = 32 AND COALESCE(jm.is_deleted, FALSE) = FALSE);

INSERT INTO jurnal_mal_detail (id_jurnal_mal, id_source_data, id_coa, type, urutan, created_by, is_deleted)
SELECT jm.id_jurnal_mal, sm.id_source_data, debit.id_coa, 1, 1, 1, FALSE
FROM jurnal_mal jm
JOIN source_modul sm ON sm.nama_tabel = 'PubSub_Payload' AND sm.nama_kolom_db = 'amount' AND sm.nama_kolom_view = 'Nominal Pembentukan Credit Note Retur'
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = jm.id_perusahaan AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) = 'retur penjualan') ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) debit ON TRUE
WHERE jm.id_fitur_mal = 32 AND COALESCE(jm.is_deleted, FALSE) = FALSE
  AND NOT EXISTS (SELECT 1 FROM jurnal_mal_detail jmd WHERE jmd.id_jurnal_mal = jm.id_jurnal_mal AND jmd.id_coa = debit.id_coa AND jmd.type = 1 AND COALESCE(jmd.is_deleted, FALSE) = FALSE);

INSERT INTO jurnal_mal_detail (id_jurnal_mal, id_source_data, id_coa, type, urutan, created_by, is_deleted)
SELECT jm.id_jurnal_mal, sm.id_source_data, kredit.id_coa, 2, 2, 1, FALSE
FROM jurnal_mal jm
JOIN source_modul sm ON sm.nama_tabel = 'PubSub_Payload' AND sm.nama_kolom_db = 'amount' AND sm.nama_kolom_view = 'Nominal Pembentukan Credit Note Retur'
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = jm.id_perusahaan AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) = 'piutang usaha') ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) kredit ON TRUE
WHERE jm.id_fitur_mal = 32 AND COALESCE(jm.is_deleted, FALSE) = FALSE
  AND NOT EXISTS (SELECT 1 FROM jurnal_mal_detail jmd WHERE jmd.id_jurnal_mal = jm.id_jurnal_mal AND jmd.id_coa = kredit.id_coa AND jmd.type = 2 AND COALESCE(jmd.is_deleted, FALSE) = FALSE);

-- 33 - Sales Order - Diskon Penjualan
INSERT INTO jurnal_mal (id_perusahaan, id_fitur_mal, main_coa_id, nama_mal, created_by)
SELECT p.id, 33, debit.id_coa, 'Sales Order - Diskon Penjualan', 1
FROM perusahaan p
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = p.id AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) = 'diskon penjualan') ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) debit ON TRUE
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = p.id AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) IN ('penjualan', 'pendapatan penjualan') AND LOWER(c.nama_akun) NOT LIKE '%diskon%' AND LOWER(c.nama_akun) NOT LIKE '%retur%') ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) kredit ON TRUE
WHERE NOT EXISTS (SELECT 1 FROM jurnal_mal jm WHERE jm.id_perusahaan = p.id AND jm.id_fitur_mal = 33 AND COALESCE(jm.is_deleted, FALSE) = FALSE);

INSERT INTO jurnal_mal_detail (id_jurnal_mal, id_source_data, id_coa, type, urutan, created_by, is_deleted)
SELECT jm.id_jurnal_mal, sm.id_source_data, debit.id_coa, 1, 1, 1, FALSE
FROM jurnal_mal jm
JOIN source_modul sm ON sm.nama_tabel = 'PubSub_Payload' AND sm.nama_kolom_db = 'amount' AND sm.nama_kolom_view = 'Nominal Diskon Penjualan Sales Order'
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = jm.id_perusahaan AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) = 'diskon penjualan') ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) debit ON TRUE
WHERE jm.id_fitur_mal = 33 AND COALESCE(jm.is_deleted, FALSE) = FALSE
  AND NOT EXISTS (SELECT 1 FROM jurnal_mal_detail jmd WHERE jmd.id_jurnal_mal = jm.id_jurnal_mal AND jmd.id_coa = debit.id_coa AND jmd.type = 1 AND COALESCE(jmd.is_deleted, FALSE) = FALSE);

INSERT INTO jurnal_mal_detail (id_jurnal_mal, id_source_data, id_coa, type, urutan, created_by, is_deleted)
SELECT jm.id_jurnal_mal, sm.id_source_data, kredit.id_coa, 2, 2, 1, FALSE
FROM jurnal_mal jm
JOIN source_modul sm ON sm.nama_tabel = 'PubSub_Payload' AND sm.nama_kolom_db = 'amount' AND sm.nama_kolom_view = 'Nominal Diskon Penjualan Sales Order'
JOIN LATERAL (SELECT c.id_coa FROM coa c WHERE c.id_perusahaan = jm.id_perusahaan AND COALESCE(c.is_active, TRUE) = TRUE AND COALESCE(c.is_deleted, FALSE) = FALSE AND (LOWER(c.nama_akun) IN ('penjualan', 'pendapatan penjualan') AND LOWER(c.nama_akun) NOT LIKE '%diskon%' AND LOWER(c.nama_akun) NOT LIKE '%retur%') ORDER BY CASE
                    WHEN LOWER(c.nama_akun) IN ('kas', 'persediaan barang') THEN 1
                    WHEN LOWER(c.nama_akun) IN ('kas besar', 'persediaan') THEN 2
                    ELSE 3
                END,
                c.id_coa LIMIT 1) kredit ON TRUE
WHERE jm.id_fitur_mal = 33 AND COALESCE(jm.is_deleted, FALSE) = FALSE
  AND NOT EXISTS (SELECT 1 FROM jurnal_mal_detail jmd WHERE jmd.id_jurnal_mal = jm.id_jurnal_mal AND jmd.id_coa = kredit.id_coa AND jmd.type = 2 AND COALESCE(jmd.is_deleted, FALSE) = FALSE);


