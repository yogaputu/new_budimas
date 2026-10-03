-- Scope multi-cabang/perusahaan untuk user dan pembersihan produk BAD/BD.
-- Jalankan sebagai owner DB sebelum memakai form Master User multiple choice.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS id_cabang_list TEXT,
    ADD COLUMN IF NOT EXISTS id_perusahaan_list TEXT;

UPDATE users
SET id_cabang_list = COALESCE(NULLIF(id_cabang_list, ''), id_cabang::TEXT)
WHERE id_cabang IS NOT NULL;

UPDATE users u
SET id_perusahaan_list = COALESCE(NULLIF(u.id_perusahaan_list, ''), COALESCE(u.id_perusahaan, c.id_perusahaan)::TEXT)
FROM cabang c
WHERE c.id = u.id_cabang
  AND COALESCE(u.id_perusahaan, c.id_perusahaan) IS NOT NULL;

WITH target_produk AS (
    SELECT p.id
    FROM produk p
    LEFT JOIN principal pr ON pr.id = p.id_principal
    WHERE UPPER(TRIM(COALESCE(p.kode_sku, ''))) LIKE '%\_BD' ESCAPE '\'
       OR UPPER(TRIM(COALESCE(pr.kode, ''))) = 'BAD'
       OR UPPER(TRIM(COALESCE(pr.nama, ''))) = 'BAD'
)
DELETE FROM produk_external_mapping pem
USING target_produk target
WHERE pem.id_produk = target.id;

WITH target_produk AS (
    SELECT p.id
    FROM produk p
    LEFT JOIN principal pr ON pr.id = p.id_principal
    WHERE UPPER(TRIM(COALESCE(p.kode_sku, ''))) LIKE '%\_BD' ESCAPE '\'
       OR UPPER(TRIM(COALESCE(pr.kode, ''))) = 'BAD'
       OR UPPER(TRIM(COALESCE(pr.nama, ''))) = 'BAD'
)
DELETE FROM produk_harga_jual phj
USING target_produk target
WHERE phj.id_produk = target.id;

WITH target_produk AS (
    SELECT p.id
    FROM produk p
    LEFT JOIN principal pr ON pr.id = p.id_principal
    WHERE UPPER(TRIM(COALESCE(p.kode_sku, ''))) LIKE '%\_BD' ESCAPE '\'
       OR UPPER(TRIM(COALESCE(pr.kode, ''))) = 'BAD'
       OR UPPER(TRIM(COALESCE(pr.nama, ''))) = 'BAD'
)
DELETE FROM produk_uom pu
USING target_produk target
WHERE pu.id_produk = target.id;

WITH target_produk AS (
    SELECT p.id
    FROM produk p
    LEFT JOIN principal pr ON pr.id = p.id_principal
    WHERE UPPER(TRIM(COALESCE(p.kode_sku, ''))) LIKE '%\_BD' ESCAPE '\'
       OR UPPER(TRIM(COALESCE(pr.kode, ''))) = 'BAD'
       OR UPPER(TRIM(COALESCE(pr.nama, ''))) = 'BAD'
)
DELETE FROM stok s
USING target_produk target
WHERE s.produk_id = target.id;

WITH target_produk AS (
    SELECT p.id
    FROM produk p
    LEFT JOIN principal pr ON pr.id = p.id_principal
    WHERE UPPER(TRIM(COALESCE(p.kode_sku, ''))) LIKE '%\_BD' ESCAPE '\'
       OR UPPER(TRIM(COALESCE(pr.kode, ''))) = 'BAD'
       OR UPPER(TRIM(COALESCE(pr.nama, ''))) = 'BAD'
)
DELETE FROM proses_picking pp
USING target_produk target
WHERE pp.id_produk = target.id;

WITH target_produk AS (
    SELECT p.id
    FROM produk p
    LEFT JOIN principal pr ON pr.id = p.id_principal
    WHERE UPPER(TRIM(COALESCE(p.kode_sku, ''))) LIKE '%\_BD' ESCAPE '\'
       OR UPPER(TRIM(COALESCE(pr.kode, ''))) = 'BAD'
       OR UPPER(TRIM(COALESCE(pr.nama, ''))) = 'BAD'
)
DELETE FROM canvas_order_detail cod
USING target_produk target
WHERE cod.id_produk = target.id;

WITH target_produk AS (
    SELECT p.id
    FROM produk p
    LEFT JOIN principal pr ON pr.id = p.id_principal
    WHERE UPPER(TRIM(COALESCE(p.kode_sku, ''))) LIKE '%\_BD' ESCAPE '\'
       OR UPPER(TRIM(COALESCE(pr.kode, ''))) = 'BAD'
       OR UPPER(TRIM(COALESCE(pr.nama, ''))) = 'BAD'
)
DELETE FROM canvas_request_detail crd
USING target_produk target
WHERE crd.id_produk = target.id;

WITH target_produk AS (
    SELECT p.id
    FROM produk p
    LEFT JOIN principal pr ON pr.id = p.id_principal
    WHERE UPPER(TRIM(COALESCE(p.kode_sku, ''))) LIKE '%\_BD' ESCAPE '\'
       OR UPPER(TRIM(COALESCE(pr.kode, ''))) = 'BAD'
       OR UPPER(TRIM(COALESCE(pr.nama, ''))) = 'BAD'
)
DELETE FROM stock_canvas sc
USING target_produk target
WHERE sc.id_produk = target.id;

WITH target_produk AS (
    SELECT p.id
    FROM produk p
    LEFT JOIN principal pr ON pr.id = p.id_principal
    WHERE UPPER(TRIM(COALESCE(p.kode_sku, ''))) LIKE '%\_BD' ESCAPE '\'
       OR UPPER(TRIM(COALESCE(pr.kode, ''))) = 'BAD'
       OR UPPER(TRIM(COALESCE(pr.nama, ''))) = 'BAD'
)
DELETE FROM produk p
USING target_produk target
WHERE p.id = target.id;
