-- Setup Jurnal Setting legacy yang aman untuk import via Adminer.
-- Tidak memakai DO $$, ALTER TABLE, atau hardcoded id_coa/id_jurnal_mal.
-- Jalankan sebagai user aplikasi biasa selama sudah punya INSERT ke jurnal_mal dan jurnal_mal_detail.
--
-- Fitur yang diset otomatis:
-- 2  Finance - Pembayaran Hutang
-- 4  Distribusi - Shipping HPP
-- 5  Distribusi - Realisasi Penjualan
-- 6  Finance - Setoran Non Tunai
-- 7  Stock Opname - Terima Selisih
-- 8  Stock Opname - Close Eskalasi
-- 11 Finance - Pengeluaran Kasir Konfirmasi
-- 12 Finance - Setoran Tunai
-- 17 Purchase - Request Purchase
--
-- Catatan:
-- Fitur 3,9,10,13-16,18-26 belum diset di file ini karena perlu audit flow/handler lebih lanjut.
-- Fitur 27-33 sudah pernah diset dari batch sebelumnya.

WITH feature_config (id_fitur_mal, nama_mal, main_role) AS (
    VALUES
        (2,  'Finance - Pembayaran Hutang', 'hutang_usaha'),
        (4,  'Distribusi - Shipping HPP', 'hpp'),
        (5,  'Distribusi - Realisasi Penjualan', 'piutang_usaha'),
        (6,  'Finance - Setoran Non Tunai', 'pembayaran_belum'),
        (7,  'Stock Opname - Terima Selisih', 'penyesuaian_persediaan'),
        (8,  'Stock Opname - Close Eskalasi', 'piutang_karyawan'),
        (11, 'Finance - Pengeluaran Kasir Konfirmasi', 'pengeluaran_kasir'),
        (12, 'Finance - Setoran Tunai', 'kas'),
        (17, 'Purchase - Request Purchase', 'persediaan')
),
detail_config (id_fitur_mal, id_source_data, coa_role, type_jurnal, urutan) AS (
    VALUES
        (2,  5,  'hutang_usaha', 1, 1),
        (2,  4,  'kas', 2, 2),
        (4,  7,  'hpp', 1, 1),
        (4,  8,  'persediaan', 2, 2),
        (5,  10, 'piutang_usaha', 1, 1),
        (5,  11, 'penjualan', 2, 2),
        (6,  12, 'pembayaran_belum', 1, 1),
        (6,  13, 'piutang_usaha', 2, 2),
        (7,  14, 'penyesuaian_persediaan', 1, 1),
        (7,  15, 'persediaan', 2, 2),
        (8,  16, 'piutang_karyawan', 1, 1),
        (8,  17, 'persediaan', 2, 2),
        (11, 22, 'pengeluaran_kasir', 1, 1),
        (11, 23, 'kas', 2, 2),
        (12, 24, 'kas', 1, 1),
        (12, 25, 'piutang_usaha', 2, 2),
        (17, 26, 'persediaan', 1, 1),
        (17, 27, 'hutang_usaha', 2, 2)
)
INSERT INTO jurnal_mal (id_perusahaan, id_fitur_mal, nama_mal, main_coa_id, created_by)
SELECT
    p.id AS id_perusahaan,
    fc.id_fitur_mal,
    fc.nama_mal,
    main_coa.id_coa AS main_coa_id,
    1 AS created_by
FROM perusahaan p
JOIN feature_config fc ON TRUE
JOIN LATERAL (
    SELECT c.id_coa
    FROM coa c
    WHERE c.id_perusahaan = p.id
      AND COALESCE(c.is_active, TRUE) = TRUE
      AND COALESCE(c.is_deleted, FALSE) = FALSE
      AND (
          (fc.main_role = 'kas' AND LOWER(c.nama_akun) IN ('kas', 'kas besar', 'bmm-kas', 'bank'))
          OR (fc.main_role = 'hutang_usaha' AND LOWER(c.nama_akun) IN ('hutang usaha', 'hutang dagang'))
          OR (fc.main_role = 'piutang_usaha' AND LOWER(c.nama_akun) IN ('piutang usaha', 'piutang dagang'))
          OR (fc.main_role = 'penjualan' AND LOWER(c.nama_akun) IN ('penjualan', 'pendapatan penjualan'))
          OR (fc.main_role = 'persediaan' AND LOWER(c.nama_akun) IN ('persediaan barang', 'persediaan'))
          OR (fc.main_role = 'hpp' AND LOWER(c.nama_akun) IN ('beban pokok penjualan', 'hpp'))
          OR (fc.main_role = 'pembayaran_belum' AND LOWER(c.nama_akun) IN ('pembayaran belum teridentifikasi'))
          OR (fc.main_role = 'penyesuaian_persediaan' AND LOWER(c.nama_akun) IN ('penyesuaian persediaan'))
          OR (fc.main_role = 'piutang_karyawan' AND LOWER(c.nama_akun) IN ('piutang karyawan'))
          OR (fc.main_role = 'pengeluaran_kasir' AND LOWER(c.nama_akun) IN ('biaya penjualan', 'pengeluaran barang rusak'))
      )
    ORDER BY
      CASE
        WHEN fc.main_role = 'kas' AND LOWER(c.nama_akun) = 'kas' THEN 1
        WHEN fc.main_role = 'kas' AND LOWER(c.nama_akun) = 'kas besar' THEN 2
        WHEN fc.main_role = 'kas' AND LOWER(c.nama_akun) = 'bmm-kas' THEN 3
        WHEN fc.main_role = 'kas' AND LOWER(c.nama_akun) = 'bank' THEN 4
        WHEN fc.main_role = 'hpp' AND LOWER(c.nama_akun) = 'beban pokok penjualan' THEN 1
        WHEN fc.main_role = 'hpp' AND LOWER(c.nama_akun) = 'hpp' THEN 2
        WHEN fc.main_role = 'pengeluaran_kasir' AND LOWER(c.nama_akun) = 'biaya penjualan' THEN 1
        WHEN fc.main_role = 'pengeluaran_kasir' AND LOWER(c.nama_akun) = 'pengeluaran barang rusak' THEN 2
        ELSE 10
      END,
      c.id_coa
    LIMIT 1
) main_coa ON TRUE
WHERE EXISTS (SELECT 1 FROM fitur_mal fm WHERE fm.id_fitur_mal = fc.id_fitur_mal)
  AND NOT EXISTS (
      SELECT 1
      FROM detail_config dc
      WHERE dc.id_fitur_mal = fc.id_fitur_mal
        AND NOT EXISTS (SELECT 1 FROM source_modul sm WHERE sm.id_source_data = dc.id_source_data)
  )
  AND NOT EXISTS (
      SELECT 1
      FROM detail_config dc
      WHERE dc.id_fitur_mal = fc.id_fitur_mal
        AND NOT EXISTS (
            SELECT 1
            FROM coa c
            WHERE c.id_perusahaan = p.id
              AND COALESCE(c.is_active, TRUE) = TRUE
              AND COALESCE(c.is_deleted, FALSE) = FALSE
              AND (
                  (dc.coa_role = 'kas' AND LOWER(c.nama_akun) IN ('kas', 'kas besar', 'bmm-kas', 'bank'))
                  OR (dc.coa_role = 'hutang_usaha' AND LOWER(c.nama_akun) IN ('hutang usaha', 'hutang dagang'))
                  OR (dc.coa_role = 'piutang_usaha' AND LOWER(c.nama_akun) IN ('piutang usaha', 'piutang dagang'))
                  OR (dc.coa_role = 'penjualan' AND LOWER(c.nama_akun) IN ('penjualan', 'pendapatan penjualan'))
                  OR (dc.coa_role = 'persediaan' AND LOWER(c.nama_akun) IN ('persediaan barang', 'persediaan'))
                  OR (dc.coa_role = 'hpp' AND LOWER(c.nama_akun) IN ('beban pokok penjualan', 'hpp'))
                  OR (dc.coa_role = 'pembayaran_belum' AND LOWER(c.nama_akun) IN ('pembayaran belum teridentifikasi'))
                  OR (dc.coa_role = 'penyesuaian_persediaan' AND LOWER(c.nama_akun) IN ('penyesuaian persediaan'))
                  OR (dc.coa_role = 'piutang_karyawan' AND LOWER(c.nama_akun) IN ('piutang karyawan'))
                  OR (dc.coa_role = 'pengeluaran_kasir' AND LOWER(c.nama_akun) IN ('biaya penjualan', 'pengeluaran barang rusak'))
              )
        )
  )
  AND NOT EXISTS (
      SELECT 1
      FROM jurnal_mal jm
      WHERE jm.id_perusahaan = p.id
        AND jm.id_fitur_mal = fc.id_fitur_mal
        AND COALESCE(jm.is_deleted, FALSE) = FALSE
  );

WITH detail_config (id_fitur_mal, id_source_data, coa_role, type_jurnal, urutan) AS (
    VALUES
        (2,  5,  'hutang_usaha', 1, 1),
        (2,  4,  'kas', 2, 2),
        (4,  7,  'hpp', 1, 1),
        (4,  8,  'persediaan', 2, 2),
        (5,  10, 'piutang_usaha', 1, 1),
        (5,  11, 'penjualan', 2, 2),
        (6,  12, 'pembayaran_belum', 1, 1),
        (6,  13, 'piutang_usaha', 2, 2),
        (7,  14, 'penyesuaian_persediaan', 1, 1),
        (7,  15, 'persediaan', 2, 2),
        (8,  16, 'piutang_karyawan', 1, 1),
        (8,  17, 'persediaan', 2, 2),
        (11, 22, 'pengeluaran_kasir', 1, 1),
        (11, 23, 'kas', 2, 2),
        (12, 24, 'kas', 1, 1),
        (12, 25, 'piutang_usaha', 2, 2),
        (17, 26, 'persediaan', 1, 1),
        (17, 27, 'hutang_usaha', 2, 2)
)
INSERT INTO jurnal_mal_detail (id_jurnal_mal, id_source_data, id_coa, type, urutan, created_by)
SELECT
    jm.id_jurnal_mal,
    dc.id_source_data,
    coa_pick.id_coa,
    dc.type_jurnal,
    dc.urutan,
    1 AS created_by
FROM jurnal_mal jm
JOIN detail_config dc ON dc.id_fitur_mal = jm.id_fitur_mal
JOIN LATERAL (
    SELECT c.id_coa
    FROM coa c
    WHERE c.id_perusahaan = jm.id_perusahaan
      AND COALESCE(c.is_active, TRUE) = TRUE
      AND COALESCE(c.is_deleted, FALSE) = FALSE
      AND (
          (dc.coa_role = 'kas' AND LOWER(c.nama_akun) IN ('kas', 'kas besar', 'bmm-kas', 'bank'))
          OR (dc.coa_role = 'hutang_usaha' AND LOWER(c.nama_akun) IN ('hutang usaha', 'hutang dagang'))
          OR (dc.coa_role = 'piutang_usaha' AND LOWER(c.nama_akun) IN ('piutang usaha', 'piutang dagang'))
          OR (dc.coa_role = 'penjualan' AND LOWER(c.nama_akun) IN ('penjualan', 'pendapatan penjualan'))
          OR (dc.coa_role = 'persediaan' AND LOWER(c.nama_akun) IN ('persediaan barang', 'persediaan'))
          OR (dc.coa_role = 'hpp' AND LOWER(c.nama_akun) IN ('beban pokok penjualan', 'hpp'))
          OR (dc.coa_role = 'pembayaran_belum' AND LOWER(c.nama_akun) IN ('pembayaran belum teridentifikasi'))
          OR (dc.coa_role = 'penyesuaian_persediaan' AND LOWER(c.nama_akun) IN ('penyesuaian persediaan'))
          OR (dc.coa_role = 'piutang_karyawan' AND LOWER(c.nama_akun) IN ('piutang karyawan'))
          OR (dc.coa_role = 'pengeluaran_kasir' AND LOWER(c.nama_akun) IN ('biaya penjualan', 'pengeluaran barang rusak'))
      )
    ORDER BY
      CASE
        WHEN dc.coa_role = 'kas' AND LOWER(c.nama_akun) = 'kas' THEN 1
        WHEN dc.coa_role = 'kas' AND LOWER(c.nama_akun) = 'kas besar' THEN 2
        WHEN dc.coa_role = 'kas' AND LOWER(c.nama_akun) = 'bmm-kas' THEN 3
        WHEN dc.coa_role = 'kas' AND LOWER(c.nama_akun) = 'bank' THEN 4
        WHEN dc.coa_role = 'hpp' AND LOWER(c.nama_akun) = 'beban pokok penjualan' THEN 1
        WHEN dc.coa_role = 'hpp' AND LOWER(c.nama_akun) = 'hpp' THEN 2
        WHEN dc.coa_role = 'pengeluaran_kasir' AND LOWER(c.nama_akun) = 'biaya penjualan' THEN 1
        WHEN dc.coa_role = 'pengeluaran_kasir' AND LOWER(c.nama_akun) = 'pengeluaran barang rusak' THEN 2
        ELSE 10
      END,
      c.id_coa
    LIMIT 1
) coa_pick ON TRUE
WHERE COALESCE(jm.is_deleted, FALSE) = FALSE
  AND EXISTS (SELECT 1 FROM source_modul sm WHERE sm.id_source_data = dc.id_source_data)
  AND NOT EXISTS (
      SELECT 1
      FROM jurnal_mal_detail jmd
      WHERE jmd.id_jurnal_mal = jm.id_jurnal_mal
        AND jmd.id_source_data = dc.id_source_data
        AND jmd.type = dc.type_jurnal
        AND COALESCE(jmd.is_deleted, FALSE) = FALSE
  );

-- Validasi hasil setup.
SELECT
    fm.id_fitur_mal,
    fm.nama_fitur_mal,
    COUNT(DISTINCT jm.id_jurnal_mal) AS header_count,
    COUNT(jmd.id_mal_detail) AS detail_count
FROM fitur_mal fm
LEFT JOIN jurnal_mal jm
    ON jm.id_fitur_mal = fm.id_fitur_mal
    AND COALESCE(jm.is_deleted, FALSE) = FALSE
LEFT JOIN jurnal_mal_detail jmd
    ON jmd.id_jurnal_mal = jm.id_jurnal_mal
    AND COALESCE(jmd.is_deleted, FALSE) = FALSE
WHERE fm.id_fitur_mal IN (2,4,5,6,7,8,11,12,17,27,28,29,30,31,32,33)
GROUP BY fm.id_fitur_mal, fm.nama_fitur_mal
ORDER BY fm.id_fitur_mal;
