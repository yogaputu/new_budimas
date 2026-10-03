\set ON_ERROR_STOP on
\timing on

BEGIN;

LOCK TABLE public.plafon, public.sales_order, public.sales_order_detail, public.faktur, public.faktur_detail IN SHARE ROW EXCLUSIVE MODE;

CREATE OR REPLACE FUNCTION pg_temp.legacy_num(value text)
RETURNS numeric
LANGUAGE sql
IMMUTABLE
AS $$
  WITH cleaned AS (
    SELECT replace(btrim(coalesce(value, '')), ',', '.') AS raw_value
  ), stripped AS (
    SELECT regexp_replace(raw_value, '[^0-9.\-]', '', 'g') AS numeric_value
    FROM cleaned
  )
  SELECT CASE
    WHEN numeric_value ~ '^-?[0-9]+(\.[0-9]+)?$' THEN numeric_value::numeric
    ELSE NULL
  END
  FROM stripped;
$$;

CREATE OR REPLACE FUNCTION pg_temp.legacy_date(value text)
RETURNS date
LANGUAGE sql
IMMUTABLE
AS $$
  WITH cleaned AS (
    SELECT btrim(coalesce(value, '')) AS raw_value
  )
  SELECT CASE
    WHEN raw_value ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' THEN substring(raw_value from 1 for 10)::date
    WHEN raw_value ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}' THEN to_date(substring(raw_value from 1 for 10), 'DD/MM/YYYY')
    ELSE NULL
  END
  FROM cleaned;
$$;

SELECT setval('public.sales_order_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.sales_order), 0), 1), true);
SELECT setval('public.sales_order_detail_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.sales_order_detail), 0), 1), true);
SELECT setval('public.faktur_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.faktur), 0), 1), true);
SELECT setval('public.faktur_detail_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.faktur_detail), 0), 1), true);
SELECT setval('public.plafon_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.plafon), 0), 1), true);
SELECT setval('public.toko_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.customer), 0), 1), true);
SELECT setval('public.sales_detail_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.sales_detail), 0), 1), true);
SELECT setval('public.sales_principal_assignment_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.sales_principal_assignment), 0), 1), true);

CREATE TABLE IF NOT EXISTS legacy_dist_2026.__map_sales_order (
  source_table text NOT NULL,
  source_nota text NOT NULL,
  no_order text NOT NULL,
  no_faktur text NOT NULL,
  id_sales_order integer NOT NULL,
  id_faktur integer,
  mapped_at timestamp without time zone NOT NULL DEFAULT now(),
  PRIMARY KEY (source_table, source_nota)
);

CREATE UNIQUE INDEX IF NOT EXISTS __map_sales_order_no_faktur_uq
  ON legacy_dist_2026.__map_sales_order (no_faktur);

CREATE TABLE IF NOT EXISTS legacy_dist_2026.__map_sales_order_detail (
  source_table text NOT NULL,
  source_nota text NOT NULL,
  source_line_key text NOT NULL,
  id_sales_order integer NOT NULL,
  id_sales_order_detail integer NOT NULL,
  mapped_at timestamp without time zone NOT NULL DEFAULT now(),
  PRIMARY KEY (source_table, source_nota, source_line_key)
);

CREATE TABLE IF NOT EXISTS legacy_dist_2026.__mapping_issues (
  id bigserial PRIMARY KEY,
  run_id text NOT NULL,
  module text NOT NULL,
  source_table text,
  source_key text,
  issue_type text NOT NULL,
  issue_detail jsonb,
  created_at timestamp without time zone NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS __mapping_issues_module_idx
  ON legacy_dist_2026.__mapping_issues (module, issue_type);

DELETE FROM legacy_dist_2026.__mapping_issues
WHERE module = 'sales_2026';

CREATE TEMP TABLE tmp_run AS
SELECT to_char(clock_timestamp(), 'YYYYMMDDHH24MISS') AS run_id;

CREATE TEMP TABLE tmp_insert_counts (
  label text PRIMARY KEY,
  row_count bigint NOT NULL
);

CREATE TEMP TABLE tmp_sales_map AS
SELECT lower(btrim(kode_sales)) AS code, min(id_sales) AS id_sales
FROM public.sales_detail
WHERE nullif(btrim(kode_sales), '') IS NOT NULL
GROUP BY lower(btrim(kode_sales));

CREATE UNIQUE INDEX tmp_sales_map_code_uq ON tmp_sales_map (code);

CREATE TEMP TABLE tmp_customer_map AS
SELECT DISTINCT ON (lower(btrim(kode)))
  lower(btrim(kode)) AS code,
  id AS id_customer
FROM public.customer
WHERE nullif(btrim(kode), '') IS NOT NULL
ORDER BY lower(btrim(kode)), CASE WHEN id_cabang = 5 THEN 0 ELSE 1 END, id;

CREATE UNIQUE INDEX tmp_customer_map_code_uq ON tmp_customer_map (code);

CREATE TEMP TABLE tmp_principal_map AS
SELECT DISTINCT ON (lower(btrim(kode)))
  lower(btrim(kode)) AS code,
  id AS id_principal
FROM public.principal
WHERE nullif(btrim(kode), '') IS NOT NULL
ORDER BY lower(btrim(kode)), CASE WHEN id_perusahaan = 1 THEN 0 ELSE 1 END, id;

CREATE UNIQUE INDEX tmp_principal_map_code_uq ON tmp_principal_map (code);

CREATE TEMP TABLE tmp_product_sku_principal_map AS
SELECT DISTINCT ON (lower(btrim(kode_sku)), id_principal)
  lower(btrim(kode_sku)) AS code,
  id_principal,
  id::integer AS id_produk
FROM public.produk
WHERE nullif(btrim(kode_sku), '') IS NOT NULL
ORDER BY lower(btrim(kode_sku)), id_principal, id;

CREATE INDEX tmp_product_sku_principal_map_idx
  ON tmp_product_sku_principal_map (code, id_principal);

CREATE TEMP TABLE tmp_product_sku_any_map AS
SELECT DISTINCT ON (lower(btrim(kode_sku)))
  lower(btrim(kode_sku)) AS code,
  id::integer AS id_produk
FROM public.produk
WHERE nullif(btrim(kode_sku), '') IS NOT NULL
ORDER BY lower(btrim(kode_sku)), id;

CREATE UNIQUE INDEX tmp_product_sku_any_map_code_uq
  ON tmp_product_sku_any_map (code);

CREATE TEMP TABLE tmp_product_external_map AS
SELECT DISTINCT ON (lower(btrim(kode_external)), lower(btrim(coalesce(principal_code, ''))))
  lower(btrim(kode_external)) AS code,
  lower(btrim(coalesce(principal_code, ''))) AS principal_code,
  id_produk
FROM public.produk_external_mapping
WHERE is_active
  AND nullif(btrim(kode_external), '') IS NOT NULL
ORDER BY lower(btrim(kode_external)), lower(btrim(coalesce(principal_code, ''))), id;

CREATE INDEX tmp_product_external_map_idx
  ON tmp_product_external_map (code, principal_code);

CREATE TEMP TABLE tmp_android_detail_nofaktur_map AS
SELECT
  upper(btrim(nota)) AS source_nota,
  min(upper(btrim(nofaktur))) AS no_faktur
FROM legacy_dist_2026.djualsmandroid
WHERE nullif(btrim(nota), '') IS NOT NULL
  AND nullif(btrim(nofaktur), '') IS NOT NULL
GROUP BY upper(btrim(nota));

CREATE UNIQUE INDEX tmp_android_detail_nofaktur_map_uq
  ON tmp_android_detail_nofaktur_map (source_nota);

CREATE TEMP TABLE tmp_legacy_sales_headers_raw AS
SELECT
  'hjualsm'::text AS source_table,
  upper(btrim(nota)) AS source_nota,
  upper(btrim(nota)) AS no_order,
  upper(btrim(nota)) AS no_faktur,
  pg_temp.legacy_date(tanggal) AS tanggal_order,
  CASE WHEN upper(btrim(coalesce(stnota, ''))) = 'RL'
    THEN coalesce(pg_temp.legacy_date(tglreal), pg_temp.legacy_date(tanggal))
    ELSE NULL
  END AS tanggal_faktur,
  CASE WHEN upper(btrim(coalesce(stnota, ''))) = 'RL'
    THEN coalesce(pg_temp.legacy_date(tglreal), pg_temp.legacy_date(tanggal))
    ELSE NULL
  END AS tanggal_terkirim,
  pg_temp.legacy_date(jatuhtempo) AS tanggal_jatuh_tempo,
  nullif(btrim(kodesales), '') AS kode_sales,
  nullif(btrim(namasales), '') AS nama_sales,
  nullif(btrim(kodecustomer), '') AS kode_customer,
  nullif(btrim(namacustomer), '') AS nama_customer,
  nullif(btrim(kodeprinciple), '') AS kode_principal,
  nullif(btrim(namaprinciple), '') AS nama_principal,
  pg_temp.legacy_num(totalpenjualan) AS total_penjualan,
  pg_temp.legacy_num(totalretur) AS total_retur,
  pg_temp.legacy_num(terbayar) AS total_terbayar,
  upper(btrim(coalesce(stnota, ''))) AS status_source,
  nullif(btrim(tunai), '') AS tipe_bayar,
  nullif(btrim(keterangan), '') AS keterangan_source,
  nullif(btrim(userbatal), '') AS user_batal,
  pg_temp.legacy_date(tglbatal) AS tanggal_batal,
  nullif(btrim(ketbatal), '') AS ket_batal
FROM legacy_dist_2026.hjualsm
WHERE nullif(btrim(nota), '') IS NOT NULL
UNION ALL
SELECT
  'hjualsmandroid_uninvoiced'::text AS source_table,
  upper(btrim(nota)) AS source_nota,
  upper(btrim(nota)) AS no_order,
  coalesce(
    (SELECT adn.no_faktur FROM tmp_android_detail_nofaktur_map adn WHERE adn.source_nota = upper(btrim(nota))),
    upper(btrim(nota))
  ) AS no_faktur,
  pg_temp.legacy_date(tanggal) AS tanggal_order,
  NULL::date AS tanggal_faktur,
  NULL::date AS tanggal_terkirim,
  pg_temp.legacy_date(jatuhtempo) AS tanggal_jatuh_tempo,
  nullif(btrim(kodesales), '') AS kode_sales,
  nullif(btrim(namasales), '') AS nama_sales,
  nullif(btrim(kodecustomer), '') AS kode_customer,
  nullif(btrim(namacustomer), '') AS nama_customer,
  nullif(btrim(kodeprinciple), '') AS kode_principal,
  nullif(btrim(namaprinciple), '') AS nama_principal,
  pg_temp.legacy_num(totalpenjualan) AS total_penjualan,
  pg_temp.legacy_num(totalretur) AS total_retur,
  pg_temp.legacy_num(terbayar) AS total_terbayar,
  upper(btrim(coalesce(stnota, ''))) AS status_source,
  nullif(btrim(tunai), '') AS tipe_bayar,
  nullif(btrim(keterangan), '') AS keterangan_source,
  nullif(btrim(userbatal), '') AS user_batal,
  pg_temp.legacy_date(tglbatal) AS tanggal_batal,
  nullif(btrim(ketbatal), '') AS ket_batal
FROM legacy_dist_2026.hjualsmandroid
WHERE nullif(btrim(nota), '') IS NOT NULL
  AND nullif(btrim(nofaktur), '') IS NULL;

INSERT INTO tmp_legacy_sales_headers_raw (
  source_table, source_nota, no_order, no_faktur, tanggal_order, tanggal_faktur,
  tanggal_terkirim, tanggal_jatuh_tempo, kode_sales, nama_sales, kode_customer,
  nama_customer, kode_principal, nama_principal, total_penjualan, total_retur,
  total_terbayar, status_source, tipe_bayar, keterangan_source, user_batal,
  tanggal_batal, ket_batal
)
SELECT
  'hjualsm'::text AS source_table,
  upper(btrim(d.nota)) AS source_nota,
  upper(btrim(d.nota)) AS no_order,
  upper(btrim(d.nota)) AS no_faktur,
  min(pg_temp.legacy_date(d.tanggal)) AS tanggal_order,
  NULL::date AS tanggal_faktur,
  NULL::date AS tanggal_terkirim,
  min(pg_temp.legacy_date(d.tanggal)) AS tanggal_jatuh_tempo,
  nullif(min(btrim(d.kodesales)), '') AS kode_sales,
  nullif(min(btrim(d.namasales)), '') AS nama_sales,
  nullif(min(btrim(d.kodecustomer)), '') AS kode_customer,
  nullif(min(btrim(d.namacustomer)), '') AS nama_customer,
  nullif(min(btrim(d.kodeprinciple)), '') AS kode_principal,
  NULL::text AS nama_principal,
  sum(coalesce(pg_temp.legacy_num(d.jumlahharga), 0)) AS total_penjualan,
  0::numeric AS total_retur,
  0::numeric AS total_terbayar,
  coalesce(nullif(max(upper(btrim(d.stnota))), ''), 'PD') AS status_source,
  NULL::text AS tipe_bayar,
  'synthetic_header_from_detail'::text AS keterangan_source,
  NULL::text AS user_batal,
  NULL::date AS tanggal_batal,
  NULL::text AS ket_batal
FROM legacy_dist_2026.djualsm d
WHERE nullif(btrim(d.nota), '') IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM tmp_legacy_sales_headers_raw h
    WHERE h.source_table = 'hjualsm'
      AND h.source_nota = upper(btrim(d.nota))
  )
  AND NOT EXISTS (
    SELECT 1
    FROM tmp_android_detail_nofaktur_map adn
    JOIN tmp_legacy_sales_headers_raw ah
      ON ah.source_table = 'hjualsmandroid_uninvoiced'
     AND ah.source_nota = adn.source_nota
    WHERE adn.no_faktur = upper(btrim(d.nota))
  )
GROUP BY upper(btrim(d.nota));

INSERT INTO tmp_legacy_sales_headers_raw (
  source_table, source_nota, no_order, no_faktur, tanggal_order, tanggal_faktur,
  tanggal_terkirim, tanggal_jatuh_tempo, kode_sales, nama_sales, kode_customer,
  nama_customer, kode_principal, nama_principal, total_penjualan, total_retur,
  total_terbayar, status_source, tipe_bayar, keterangan_source, user_batal,
  tanggal_batal, ket_batal
)
SELECT
  'hjualsmandroid_uninvoiced'::text AS source_table,
  upper(btrim(d.nota)) AS source_nota,
  upper(btrim(d.nota)) AS no_order,
  coalesce(min(nullif(upper(btrim(d.nofaktur)), '')), upper(btrim(d.nota))) AS no_faktur,
  min(pg_temp.legacy_date(d.tanggal)) AS tanggal_order,
  NULL::date AS tanggal_faktur,
  NULL::date AS tanggal_terkirim,
  min(pg_temp.legacy_date(d.tanggal)) AS tanggal_jatuh_tempo,
  nullif(min(btrim(d.kodesales)), '') AS kode_sales,
  nullif(min(btrim(d.namasales)), '') AS nama_sales,
  nullif(min(btrim(d.kodecustomer)), '') AS kode_customer,
  nullif(min(btrim(d.namacustomer)), '') AS nama_customer,
  nullif(min(btrim(d.kodeprinciple)), '') AS kode_principal,
  NULL::text AS nama_principal,
  sum(coalesce(pg_temp.legacy_num(d.jumlahharga), 0)) AS total_penjualan,
  0::numeric AS total_retur,
  0::numeric AS total_terbayar,
  coalesce(nullif(max(upper(btrim(d.stnota))), ''), 'PD') AS status_source,
  NULL::text AS tipe_bayar,
  'synthetic_header_from_android_detail'::text AS keterangan_source,
  NULL::text AS user_batal,
  NULL::date AS tanggal_batal,
  NULL::text AS ket_batal
FROM legacy_dist_2026.djualsmandroid d
WHERE nullif(btrim(d.nota), '') IS NOT NULL
  AND nullif(btrim(d.nofaktur), '') IS NULL
  AND NOT EXISTS (
    SELECT 1
    FROM tmp_legacy_sales_headers_raw h
    WHERE h.source_table = 'hjualsmandroid_uninvoiced'
      AND h.source_nota = upper(btrim(d.nota))
  )
GROUP BY upper(btrim(d.nota));

CREATE UNIQUE INDEX tmp_legacy_sales_headers_raw_source_uq
  ON tmp_legacy_sales_headers_raw (source_table, source_nota);
CREATE INDEX tmp_legacy_sales_headers_raw_no_faktur_idx
  ON tmp_legacy_sales_headers_raw (no_faktur);

CREATE TEMP TABLE tmp_legacy_sales_headers_skip AS
SELECT *
FROM (VALUES
  (
    'hjualsmandroid_uninvoiced'::text,
    'SM20260419262000233'::text,
    'Skip orphan IT01/DAMAR IT BDM Android test header: no source detail, no invoice, no payment'
  ),
  (
    'hjualsmandroid_uninvoiced'::text,
    'SM20260420472000235'::text,
    'Skip orphan IT01/DAMAR IT BDM Android test header: no source detail, no invoice, no payment'
  )
) AS skipped(source_table, source_nota, reason);

DELETE FROM tmp_legacy_sales_headers_raw h
USING tmp_legacy_sales_headers_skip s
WHERE h.source_table = s.source_table
  AND h.source_nota = s.source_nota;

CREATE TEMP TABLE tmp_legacy_header_principal_inferred AS
WITH detail_rows AS (
  SELECT
    'hjualsm'::text AS source_table,
    upper(btrim(nota)) AS source_nota,
    lower(btrim(kodestok)) AS kode_stok,
    lower(btrim(masterkode)) AS master_kode,
    pg_temp.legacy_num(jumlahharga) AS jumlah_harga
  FROM legacy_dist_2026.djualsm
  WHERE nullif(btrim(nota), '') IS NOT NULL
  UNION ALL
  SELECT
    'hjualsmandroid_uninvoiced'::text AS source_table,
    upper(btrim(nota)) AS source_nota,
    lower(btrim(kodestok)) AS kode_stok,
    lower(btrim(masterkode)) AS master_kode,
    pg_temp.legacy_num(jumlahharga) AS jumlah_harga
  FROM legacy_dist_2026.djualsmandroid
  WHERE nullif(btrim(nota), '') IS NOT NULL
), mapped AS (
  SELECT
    d.source_table,
    d.source_nota,
    pr.kode AS kode_principal,
    pr.nama AS nama_principal,
    count(*) AS line_count,
    sum(coalesce(d.jumlah_harga, 0)) AS total_harga
  FROM detail_rows d
  JOIN tmp_legacy_sales_headers_raw h
    ON h.source_table = d.source_table
   AND h.source_nota = d.source_nota
  JOIN LATERAL (
    SELECT psp.id_principal
    FROM tmp_product_sku_principal_map psp
    WHERE psp.code = d.kode_stok
       OR psp.code = d.master_kode
    ORDER BY
      CASE WHEN psp.code = d.kode_stok THEN 0 ELSE 1 END,
      psp.id_principal
    LIMIT 1
  ) p ON true
  JOIN public.principal pr ON pr.id = p.id_principal
  WHERE h.kode_principal IS NULL
  GROUP BY d.source_table, d.source_nota, pr.kode, pr.nama
)
SELECT DISTINCT ON (source_table, source_nota)
  source_table,
  source_nota,
  kode_principal,
  nama_principal
FROM mapped
ORDER BY source_table, source_nota, total_harga DESC NULLS LAST, line_count DESC, kode_principal;

CREATE UNIQUE INDEX tmp_legacy_header_principal_inferred_uq
  ON tmp_legacy_header_principal_inferred (source_table, source_nota);

UPDATE tmp_legacy_sales_headers_raw h
SET kode_principal = i.kode_principal,
    nama_principal = i.nama_principal
FROM tmp_legacy_header_principal_inferred i
WHERE h.source_table = i.source_table
  AND h.source_nota = i.source_nota
  AND h.kode_principal IS NULL;

INSERT INTO tmp_insert_counts (label, row_count)
SELECT 'header_principal_inferred_from_product', count(*)
FROM tmp_legacy_header_principal_inferred
ON CONFLICT (label) DO UPDATE SET row_count = EXCLUDED.row_count;

CREATE TEMP TABLE tmp_legacy_missing_customer_candidates AS
SELECT DISTINCT ON (lower(btrim(h.kode_customer)))
  h.kode_customer,
  coalesce(nullif(btrim(c.nama), ''), h.nama_customer, h.kode_customer) AS nama_customer,
  nullif(btrim(c.alamat), '') AS alamat,
  nullif(btrim(c.telpon), '') AS telepon,
  nullif(btrim(c.npwp), '') AS npwp,
  nullif(btrim(c.namawp), '') AS nama_wajib_pajak,
  nullif(btrim(c.alamatwp), '') AS alamat_wajib_pajak,
  nullif(btrim(c.longitude), '') AS longitude,
  nullif(btrim(c.latitude), '') AS latitude
FROM tmp_legacy_sales_headers_raw h
LEFT JOIN legacy_dist_2026.customer c
  ON lower(btrim(c.kode)) = lower(btrim(h.kode_customer))
WHERE h.kode_customer IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM tmp_customer_map cm
    WHERE cm.code = lower(btrim(h.kode_customer))
  )
ORDER BY lower(btrim(h.kode_customer)), CASE WHEN c.kode IS NULL THEN 1 ELSE 0 END, h.tanggal_order DESC NULLS LAST;

CREATE UNIQUE INDEX tmp_legacy_missing_customer_candidates_uq
  ON tmp_legacy_missing_customer_candidates (lower(btrim(kode_customer)));

WITH inserted AS (
  INSERT INTO public.customer (
    kode, nama, alamat, telepon, npwp, nama_wajib_pajak, alamat_wajib_pajak,
    id_cabang, id_tipe_harga, is_ppn, longitude, latitude
  )
  SELECT
    left(c.kode_customer, 30),
    left(c.nama_customer, 50),
    left(c.alamat, 100),
    left(c.telepon, 20),
    left(c.npwp, 25),
    left(c.nama_wajib_pajak, 50),
    left(c.alamat_wajib_pajak, 100),
    5,
    2,
    1,
    left(c.longitude, 25),
    left(c.latitude, 25)
  FROM tmp_legacy_missing_customer_candidates c
  WHERE NOT EXISTS (
    SELECT 1
    FROM public.customer cu
    WHERE lower(btrim(cu.kode)) = lower(btrim(c.kode_customer))
  )
  RETURNING id, kode
), mapped AS (
  INSERT INTO tmp_customer_map (code, id_customer)
  SELECT lower(btrim(kode)), id
  FROM inserted
  ON CONFLICT (code) DO NOTHING
  RETURNING code
)
INSERT INTO tmp_insert_counts (label, row_count)
SELECT 'customer_seed_inserted', count(*)
FROM mapped
ON CONFLICT (label) DO UPDATE SET row_count = EXCLUDED.row_count;

CREATE TEMP TABLE tmp_legacy_missing_sales_candidates AS
SELECT DISTINCT ON (lower(btrim(h.kode_sales)))
  h.kode_sales,
  coalesce(h.nama_sales, h.kode_sales) AS nama_sales,
  pm.id_principal
FROM tmp_legacy_sales_headers_raw h
LEFT JOIN tmp_principal_map pm ON pm.code = lower(btrim(h.kode_principal))
WHERE h.kode_sales IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM tmp_sales_map sm
    WHERE sm.code = lower(btrim(h.kode_sales))
  )
ORDER BY lower(btrim(h.kode_sales)), h.tanggal_order DESC NULLS LAST;

CREATE UNIQUE INDEX tmp_legacy_missing_sales_candidates_uq
  ON tmp_legacy_missing_sales_candidates (lower(btrim(kode_sales)));

CREATE TEMP TABLE tmp_legacy_missing_sales_alias_targets AS
SELECT
  c.*,
  s.id AS id_sales
FROM tmp_legacy_missing_sales_candidates c
JOIN LATERAL (
  SELECT s.id
  FROM public.sales s
  JOIN public.users u ON u.id = s.id_user
  WHERE lower(btrim(u.nama)) = lower(btrim(c.nama_sales))
  ORDER BY
    CASE WHEN s.id_principal = c.id_principal THEN 0 ELSE 1 END,
    s.id
  LIMIT 1
) s ON true;

WITH inserted_detail AS (
  INSERT INTO public.sales_detail (id_sales, kode_sales)
  SELECT t.id_sales, lower(btrim(t.kode_sales))
  FROM tmp_legacy_missing_sales_alias_targets t
  WHERE NOT EXISTS (
    SELECT 1
    FROM public.sales_detail sd
    WHERE lower(btrim(sd.kode_sales)) = lower(btrim(t.kode_sales))
  )
  RETURNING id_sales, kode_sales
), mapped AS (
  INSERT INTO tmp_sales_map (code, id_sales)
  SELECT lower(btrim(kode_sales)), id_sales
  FROM inserted_detail
  ON CONFLICT (code) DO NOTHING
  RETURNING code
)
INSERT INTO tmp_insert_counts (label, row_count)
SELECT 'sales_alias_seed_inserted', count(*)
FROM mapped
ON CONFLICT (label) DO UPDATE SET row_count = EXCLUDED.row_count;

WITH inserted_assignment AS (
  INSERT INTO public.sales_principal_assignment (id_sales, id_principal)
  SELECT t.id_sales, t.id_principal
  FROM tmp_legacy_missing_sales_alias_targets t
  WHERE t.id_principal IS NOT NULL
    AND NOT EXISTS (
      SELECT 1
      FROM public.sales_principal_assignment spa
      WHERE spa.id_sales = t.id_sales
        AND spa.id_principal = t.id_principal
    )
  RETURNING id
)
INSERT INTO tmp_insert_counts (label, row_count)
SELECT 'sales_principal_assignment_seed_inserted', count(*)
FROM inserted_assignment
ON CONFLICT (label) DO UPDATE SET row_count = EXCLUDED.row_count;

CREATE TEMP TABLE tmp_legacy_plafon_exact AS
SELECT DISTINCT ON (lower(btrim(kodecustomer)), lower(btrim(kodeprinciple)), lower(btrim(kodesales)))
  lower(btrim(kodecustomer)) AS kode_customer,
  lower(btrim(kodeprinciple)) AS kode_principal,
  lower(btrim(kodesales)) AS kode_sales,
  pg_temp.legacy_num(plafon) AS limit_bon,
  pg_temp.legacy_num(term)::integer AS term,
  left(coalesce(nullif(btrim(lock1), ''), '1'), 1) AS lock_order
FROM legacy_dist_2026.plafon
WHERE nullif(btrim(kodecustomer), '') IS NOT NULL
  AND nullif(btrim(kodeprinciple), '') IS NOT NULL
  AND nullif(btrim(kodesales), '') IS NOT NULL
ORDER BY
  lower(btrim(kodecustomer)),
  lower(btrim(kodeprinciple)),
  lower(btrim(kodesales)),
  pg_temp.legacy_date(tgladd) DESC NULLS LAST,
  pg_temp.legacy_num(plafon) DESC NULLS LAST;

CREATE UNIQUE INDEX tmp_legacy_plafon_exact_code_uq
  ON tmp_legacy_plafon_exact (kode_customer, kode_principal, kode_sales);

CREATE TEMP TABLE tmp_legacy_missing_plafon_candidates AS
SELECT
  min(h.kode_customer) AS kode_customer,
  min(h.kode_principal) AS kode_principal,
  min(h.kode_sales) AS kode_sales,
  cm.id_customer,
  pm.id_principal,
  sm.id_sales,
  s.id_user,
  max(coalesce(h.total_penjualan, 0)) AS max_total_penjualan,
  count(*) AS transaksi_count
FROM tmp_legacy_sales_headers_raw h
JOIN tmp_sales_map sm ON sm.code = lower(btrim(h.kode_sales))
JOIN tmp_customer_map cm ON cm.code = lower(btrim(h.kode_customer))
JOIN tmp_principal_map pm ON pm.code = lower(btrim(h.kode_principal))
LEFT JOIN public.sales s ON s.id = sm.id_sales
WHERE NOT EXISTS (
  SELECT 1
  FROM public.plafon pl
  WHERE pl.id_customer = cm.id_customer
    AND pl.id_principal = pm.id_principal
    AND pl.id_sales = sm.id_sales
)
GROUP BY cm.id_customer, pm.id_principal, sm.id_sales, s.id_user;

CREATE UNIQUE INDEX tmp_legacy_missing_plafon_candidates_uq
  ON tmp_legacy_missing_plafon_candidates (id_customer, id_principal, id_sales);

CREATE TEMP TABLE tmp_legacy_missing_plafon_to_insert AS
SELECT
  c.*,
  coalesce(
    nullif(lp.limit_bon, 0),
    nullif(cp.limit_bon::numeric, 0),
    nullif(cust.limit_bon::numeric, 0),
    greatest(coalesce(c.max_total_penjualan, 0), 500000::numeric)
  )::double precision AS resolved_limit_bon,
  coalesce(cp.id_tipe_harga, cust.id_tipe_harga, 2) AS resolved_id_tipe_harga,
  coalesce(nullif(lp.term, 0), cp.top::integer, cp.tempo, cust.top::integer, cust.tempo, 0) AS resolved_top,
  coalesce(left(nullif(lp.lock_order, ''), 1), left(nullif(cp.lock_order, ''), 1), left(nullif(cust.lock_order, ''), 1), '1') AS resolved_lock_order,
  coalesce(nullif(lp.term, 0), cp.tempo, cp.top::integer, cust.tempo, cust.top::integer, 0) AS resolved_tempo,
  CASE
    WHEN lp.kode_customer IS NOT NULL THEN 'legacy_plafon_exact'
    WHEN cp.id IS NOT NULL THEN 'public_customer_principal'
    WHEN cust.id IS NOT NULL THEN 'public_customer'
    ELSE 'transaction_default'
  END AS seed_strategy
FROM tmp_legacy_missing_plafon_candidates c
LEFT JOIN tmp_legacy_plafon_exact lp
  ON lp.kode_customer = lower(btrim(c.kode_customer))
 AND lp.kode_principal = lower(btrim(c.kode_principal))
 AND lp.kode_sales = lower(btrim(c.kode_sales))
LEFT JOIN LATERAL (
  SELECT p.*
  FROM public.plafon p
  WHERE p.id_customer = c.id_customer
    AND p.id_principal = c.id_principal
  ORDER BY p.id DESC
  LIMIT 1
) cp ON true
LEFT JOIN LATERAL (
  SELECT p.*
  FROM public.plafon p
  WHERE p.id_customer = c.id_customer
  ORDER BY
    CASE WHEN p.id_principal = c.id_principal THEN 0 ELSE 1 END,
    p.id DESC
  LIMIT 1
) cust ON true;

INSERT INTO tmp_insert_counts (label, row_count)
SELECT 'plafon_seed_candidate_total', count(*)
FROM tmp_legacy_missing_plafon_to_insert
ON CONFLICT (label) DO UPDATE SET row_count = EXCLUDED.row_count;

INSERT INTO tmp_insert_counts (label, row_count)
SELECT 'plafon_seed_strategy_' || seed_strategy, count(*)
FROM tmp_legacy_missing_plafon_to_insert
GROUP BY seed_strategy
ON CONFLICT (label) DO UPDATE SET row_count = EXCLUDED.row_count;

WITH inserted AS (
  INSERT INTO public.plafon (
    id_customer, id_principal, id_sales, id_user, limit_bon, sisa_bon,
    kode, id_tipe_harga, top, lock_order, tempo, tempo_label
  )
  SELECT
    t.id_customer,
    t.id_principal,
    t.id_sales,
    t.id_user,
    t.resolved_limit_bon,
    t.resolved_limit_bon,
    concat(t.kode_customer, '-', t.kode_principal, '-', t.kode_sales),
    t.resolved_id_tipe_harga,
    t.resolved_top::smallint,
    t.resolved_lock_order,
    t.resolved_tempo,
    CASE WHEN t.resolved_tempo > 0 THEN concat(t.resolved_tempo, ' Hari') ELSE NULL END
  FROM tmp_legacy_missing_plafon_to_insert t
  WHERE NOT EXISTS (
    SELECT 1
    FROM public.plafon pl
    WHERE pl.id_customer = t.id_customer
      AND pl.id_principal = t.id_principal
      AND pl.id_sales = t.id_sales
  )
  RETURNING id
)
INSERT INTO tmp_insert_counts (label, row_count)
SELECT 'plafon_seed_inserted', count(*)
FROM inserted
ON CONFLICT (label) DO UPDATE SET row_count = EXCLUDED.row_count;

ANALYZE public.plafon;

CREATE TEMP TABLE tmp_legacy_sales_headers AS
SELECT
  h.*,
  sm.id_sales,
  cm.id_customer,
  pm.id_principal,
  pl.id AS id_plafon,
  CASE
    WHEN h.status_source = 'RL' THEN 6
    WHEN h.status_source = 'BT' THEN -1
    ELSE 0
  END AS target_status_order,
  CASE
    WHEN h.status_source = 'BT' THEN 4
    WHEN h.status_source = 'RL' AND coalesce(h.total_penjualan, 0) <= 0 THEN 3
    WHEN h.status_source = 'RL' AND coalesce(h.total_terbayar, 0) >= coalesce(h.total_penjualan, 0) THEN 3
    WHEN h.status_source = 'RL' THEN 2
    ELSE 0
  END AS target_status_faktur
FROM tmp_legacy_sales_headers_raw h
LEFT JOIN tmp_sales_map sm ON sm.code = lower(btrim(h.kode_sales))
LEFT JOIN tmp_customer_map cm ON cm.code = lower(btrim(h.kode_customer))
LEFT JOIN tmp_principal_map pm ON pm.code = lower(btrim(h.kode_principal))
LEFT JOIN LATERAL (
  SELECT id
  FROM public.plafon pl
  WHERE pl.id_customer = cm.id_customer
    AND pl.id_principal = pm.id_principal
    AND pl.id_sales = sm.id_sales
  ORDER BY id
  LIMIT 1
) pl ON true;

CREATE UNIQUE INDEX tmp_legacy_sales_headers_source_uq
  ON tmp_legacy_sales_headers (source_table, source_nota);
CREATE INDEX tmp_legacy_sales_headers_no_faktur_idx
  ON tmp_legacy_sales_headers (no_faktur);
CREATE INDEX tmp_legacy_sales_headers_plafon_idx
  ON tmp_legacy_sales_headers (id_plafon);

CREATE TEMP TABLE tmp_legacy_sales_details_raw AS
WITH raw_details AS (
  SELECT
    'hjualsm'::text AS source_table,
    upper(btrim(nota)) AS source_nota,
    btrim(kodestok) AS kode_stok,
    nullif(btrim(masterkode), '') AS master_kode,
    nullif(btrim(kodeprinciple), '') AS kode_principal,
    nullif(btrim(namastok), '') AS nama_stok,
    nullif(btrim(ct), '') AS unit_label,
    nullif(btrim(pc), '') AS piece_label,
    pg_temp.legacy_num(unit) AS qty_unit,
    pg_temp.legacy_num(satuan) AS qty_piece,
    pg_temp.legacy_num(jumlah) AS qty_total,
    pg_temp.legacy_num(harga) AS harga,
    pg_temp.legacy_num(disc1) AS disc1,
    pg_temp.legacy_num(disc2) AS disc2,
    pg_temp.legacy_num(disc3) AS disc3,
    pg_temp.legacy_num(discrp1) AS discrp1,
    pg_temp.legacy_num(discrp2) AS discrp2,
    pg_temp.legacy_num(discrp3) AS discrp3,
    pg_temp.legacy_num(discrp) AS discrp,
    pg_temp.legacy_num(jumlahexppn) AS jumlah_ex_ppn,
    pg_temp.legacy_num(jumlahharga) AS jumlah_harga,
    pg_temp.legacy_num(urut) AS urut,
    ctid::text AS physical_row
  FROM legacy_dist_2026.djualsm
  WHERE nullif(btrim(nota), '') IS NOT NULL
  UNION ALL
  SELECT
    'hjualsmandroid_uninvoiced'::text AS source_table,
    upper(btrim(da.nota)) AS source_nota,
    btrim(da.kodestok) AS kode_stok,
    nullif(btrim(da.masterkode), '') AS master_kode,
    nullif(btrim(da.kodeprinciple), '') AS kode_principal,
    nullif(btrim(da.namastok), '') AS nama_stok,
    nullif(btrim(da.ct), '') AS unit_label,
    nullif(btrim(da.pc), '') AS piece_label,
    pg_temp.legacy_num(da.unit) AS qty_unit,
    pg_temp.legacy_num(da.satuan) AS qty_piece,
    pg_temp.legacy_num(da.jumlah) AS qty_total,
    pg_temp.legacy_num(da.harga) AS harga,
    pg_temp.legacy_num(da.disc1) AS disc1,
    pg_temp.legacy_num(da.disc2) AS disc2,
    pg_temp.legacy_num(da.disc3) AS disc3,
    pg_temp.legacy_num(da.discrp1) AS discrp1,
    pg_temp.legacy_num(da.discrp2) AS discrp2,
    pg_temp.legacy_num(da.discrp3) AS discrp3,
    pg_temp.legacy_num(da.discrp) AS discrp,
    pg_temp.legacy_num(da.jumlahexppn) AS jumlah_ex_ppn,
    pg_temp.legacy_num(da.jumlahharga) AS jumlah_harga,
    pg_temp.legacy_num(da.urut) AS urut,
    da.ctid::text AS physical_row
  FROM legacy_dist_2026.djualsmandroid da
  WHERE nullif(btrim(da.nota), '') IS NOT NULL
    AND EXISTS (
      SELECT 1
      FROM tmp_legacy_sales_headers_raw h
      WHERE h.source_table = 'hjualsmandroid_uninvoiced'
        AND h.source_nota = upper(btrim(da.nota))
    )
)
SELECT
  *,
  lpad(row_number() OVER (
    PARTITION BY source_table, source_nota
    ORDER BY urut NULLS LAST, kode_stok, coalesce(master_kode, ''), coalesce(nama_stok, ''),
             coalesce(qty_unit, 0), coalesce(qty_piece, 0), coalesce(qty_total, 0),
             coalesce(harga, 0), coalesce(jumlah_harga, 0), physical_row
  )::text, 8, '0') AS source_line_key
FROM raw_details;

CREATE UNIQUE INDEX tmp_legacy_sales_details_raw_source_uq
  ON tmp_legacy_sales_details_raw (source_table, source_nota, source_line_key);
CREATE INDEX tmp_legacy_sales_details_raw_source_idx
  ON tmp_legacy_sales_details_raw (source_table, source_nota);
CREATE INDEX tmp_legacy_sales_details_raw_codes_idx
  ON tmp_legacy_sales_details_raw (lower(kode_stok), lower(coalesce(master_kode, '')));

CREATE TEMP TABLE tmp_legacy_sales_details AS
SELECT
  d.*,
  h.id_principal AS header_id_principal,
  h.status_source AS header_status_source,
  coalesce(psp.id_produk, pmp.id_produk, pemkp.id_produk, pemmp.id_produk, psa.id_produk, pma.id_produk, pemka.id_produk, pemma.id_produk) AS id_produk
FROM tmp_legacy_sales_details_raw d
LEFT JOIN tmp_legacy_sales_headers h
  ON h.source_table = d.source_table
 AND h.source_nota = d.source_nota
LEFT JOIN tmp_product_sku_principal_map psp
  ON psp.code = lower(d.kode_stok)
 AND psp.id_principal = h.id_principal
LEFT JOIN tmp_product_sku_principal_map pmp
  ON pmp.code = lower(coalesce(d.master_kode, ''))
 AND pmp.id_principal = h.id_principal
LEFT JOIN tmp_product_external_map pemkp
  ON pemkp.code = lower(d.kode_stok)
 AND pemkp.principal_code = lower(coalesce(d.kode_principal, ''))
LEFT JOIN tmp_product_external_map pemmp
  ON pemmp.code = lower(coalesce(d.master_kode, ''))
 AND pemmp.principal_code = lower(coalesce(d.kode_principal, ''))
LEFT JOIN tmp_product_sku_any_map psa
  ON psa.code = lower(d.kode_stok)
LEFT JOIN tmp_product_sku_any_map pma
  ON pma.code = lower(coalesce(d.master_kode, ''))
LEFT JOIN tmp_product_external_map pemka
  ON pemka.code = lower(d.kode_stok)
 AND pemka.principal_code = ''
LEFT JOIN tmp_product_external_map pemma
  ON pemma.code = lower(coalesce(d.master_kode, ''))
 AND pemma.principal_code = '';

CREATE UNIQUE INDEX tmp_legacy_sales_details_source_uq
  ON tmp_legacy_sales_details (source_table, source_nota, source_line_key);
CREATE INDEX tmp_legacy_sales_details_product_idx
  ON tmp_legacy_sales_details (id_produk);

CREATE TEMP TABLE tmp_legacy_sales_detail_agg AS
SELECT
  source_table,
  source_nota,
  count(*) AS detail_rows,
  count(*) FILTER (WHERE id_produk IS NULL) AS missing_product_rows,
  sum(coalesce(jumlah_ex_ppn, 0)) AS detail_dpp,
  sum(coalesce(jumlah_harga, 0)) AS detail_total,
  sum(coalesce(discrp, 0) + coalesce(discrp1, 0) + coalesce(discrp2, 0) + coalesce(discrp3, 0)) AS detail_discount
FROM tmp_legacy_sales_details
GROUP BY source_table, source_nota;

CREATE UNIQUE INDEX tmp_legacy_sales_detail_agg_source_uq
  ON tmp_legacy_sales_detail_agg (source_table, source_nota);

CREATE TEMP TABLE tmp_legacy_sales_headers_enriched AS
SELECT
  h.*,
  coalesce(a.detail_rows, 0) AS detail_rows,
  coalesce(a.missing_product_rows, 0) AS missing_product_rows,
  coalesce(nullif(a.detail_dpp, 0), h.total_penjualan, 0) AS resolved_dpp,
  coalesce(nullif(a.detail_total, 0), h.total_penjualan, 0) AS resolved_detail_total,
  coalesce(a.detail_discount, 0) AS resolved_discount
FROM tmp_legacy_sales_headers h
LEFT JOIN tmp_legacy_sales_detail_agg a
  ON a.source_table = h.source_table
 AND a.source_nota = h.source_nota;

CREATE UNIQUE INDEX tmp_legacy_sales_headers_enriched_source_uq
  ON tmp_legacy_sales_headers_enriched (source_table, source_nota);

INSERT INTO legacy_dist_2026.__mapping_issues (
  run_id, module, source_table, source_key, issue_type, issue_detail
)
SELECT
  r.run_id,
  'sales_2026',
  h.source_table,
  h.source_nota,
  'header_unresolved_master',
  jsonb_build_object(
    'no_faktur', h.no_faktur,
    'kode_sales', h.kode_sales,
    'missing_sales', h.id_sales IS NULL,
    'kode_customer', h.kode_customer,
    'missing_customer', h.id_customer IS NULL,
    'kode_principal', h.kode_principal,
    'missing_principal', h.id_principal IS NULL,
    'missing_plafon', h.id_plafon IS NULL AND h.id_sales IS NOT NULL AND h.id_customer IS NOT NULL AND h.id_principal IS NOT NULL
  )
FROM tmp_legacy_sales_headers h
CROSS JOIN tmp_run r
WHERE h.id_sales IS NULL
   OR h.id_customer IS NULL
   OR h.id_principal IS NULL
   OR h.id_plafon IS NULL;

INSERT INTO legacy_dist_2026.__mapping_issues (
  run_id, module, source_table, source_key, issue_type, issue_detail
)
SELECT
  r.run_id,
  'sales_2026',
  h.source_table,
  h.source_nota,
  'target_conflict_no_faktur',
  jsonb_build_object('no_faktur', h.no_faktur, 'target_faktur_id', f.id)
FROM tmp_legacy_sales_headers h
CROSS JOIN tmp_run r
JOIN public.faktur f ON f.no_faktur = h.no_faktur
LEFT JOIN legacy_dist_2026.__map_sales_order m
  ON m.source_table = h.source_table
 AND m.source_nota = h.source_nota
WHERE m.source_nota IS NULL
  AND NOT EXISTS (
    SELECT 1
    FROM legacy_dist_2026.__map_sales_order mapped
    WHERE mapped.no_faktur = h.no_faktur
  );

INSERT INTO legacy_dist_2026.__mapping_issues (
  run_id, module, source_table, source_key, issue_type, issue_detail
)
SELECT
  r.run_id,
  'sales_2026',
  d.source_table,
  d.source_nota,
  'detail_without_header',
  jsonb_build_object('detail_rows', count(*))
FROM tmp_legacy_sales_details d
CROSS JOIN tmp_run r
LEFT JOIN tmp_legacy_sales_headers h
  ON h.source_table = d.source_table
 AND h.source_nota = d.source_nota
WHERE h.source_nota IS NULL
  AND NOT (
    d.source_table = 'hjualsm'
    AND EXISTS (
      SELECT 1
      FROM tmp_legacy_sales_headers ah
      WHERE ah.source_table = 'hjualsmandroid_uninvoiced'
        AND ah.no_faktur = d.source_nota
    )
  )
GROUP BY r.run_id, d.source_table, d.source_nota;

INSERT INTO legacy_dist_2026.__mapping_issues (
  run_id, module, source_table, source_key, issue_type, issue_detail
)
SELECT
  r.run_id,
  'sales_2026',
  d.source_table,
  d.source_nota,
  'detail_missing_product',
  jsonb_build_object(
    'kode_stok', d.kode_stok,
    'master_kode', d.master_kode,
    'kode_principal', d.kode_principal,
    'nama_stok', d.nama_stok,
    'line_key', d.source_line_key
  )
FROM tmp_legacy_sales_details d
CROSS JOIN tmp_run r
JOIN tmp_legacy_sales_headers h
  ON h.source_table = d.source_table
 AND h.source_nota = d.source_nota
WHERE d.id_produk IS NULL;

INSERT INTO legacy_dist_2026.__mapping_issues (
  run_id, module, source_table, source_key, issue_type, issue_detail
)
SELECT
  r.run_id,
  'sales_2026',
  h.source_table,
  h.source_nota,
  'header_detail_not_ready',
  jsonb_build_object(
    'no_faktur', h.no_faktur,
    'total_penjualan', h.total_penjualan,
    'detail_rows', coalesce(a.detail_rows, 0),
    'missing_product_rows', coalesce(a.missing_product_rows, 0)
  )
FROM tmp_legacy_sales_headers h
CROSS JOIN tmp_run r
LEFT JOIN tmp_legacy_sales_detail_agg a
  ON a.source_table = h.source_table
 AND a.source_nota = h.source_nota
WHERE h.id_plafon IS NOT NULL
  AND (
    coalesce(a.missing_product_rows, 0) > 0
    OR (coalesce(a.detail_rows, 0) = 0 AND coalesce(h.total_penjualan, 0) <> 0)
  );

CREATE TEMP TABLE tmp_legacy_sales_headers_ready AS
SELECT
  h.*
FROM tmp_legacy_sales_headers_enriched h
LEFT JOIN legacy_dist_2026.__map_sales_order m
  ON m.source_table = h.source_table
 AND m.source_nota = h.source_nota
LEFT JOIN public.faktur f
  ON f.no_faktur = h.no_faktur
WHERE h.id_plafon IS NOT NULL
  AND m.source_nota IS NULL
  AND f.id IS NULL
  AND h.missing_product_rows = 0
  AND (h.detail_rows > 0 OR coalesce(h.total_penjualan, 0) = 0 OR h.status_source = 'BT');

CREATE UNIQUE INDEX tmp_legacy_sales_headers_ready_source_uq
  ON tmp_legacy_sales_headers_ready (source_table, source_nota);

CREATE TEMP TABLE tmp_legacy_sales_orders_to_insert AS
SELECT nextval('public.sales_order_id_seq'::regclass)::integer AS target_id, h.*
FROM tmp_legacy_sales_headers_ready h
ORDER BY h.tanggal_order, h.source_table, h.source_nota;

INSERT INTO public.sales_order (
  id,
  id_plafon,
  tanggal_order,
  tanggal_faktur,
  tanggal_terkirim,
  tanggal_jatuh_tempo,
  nama_sales,
  pic_customer,
  total_kubikasi,
  status_order,
  total_order,
  no_order,
  no_faktur,
  no_tagihan,
  keterangan,
  id_cabang,
  id_sales_tipe,
  total_order_before_discount,
  unified_promo_nominal,
  manual_discount_value,
  manual_discount_nominal,
  order_discount_total
)
SELECT
  target_id,
  id_plafon,
  tanggal_order,
  tanggal_faktur,
  tanggal_terkirim,
  tanggal_jatuh_tempo,
  nama_sales,
  nama_customer,
  0,
  target_status_order,
  coalesce(total_penjualan, 0)::double precision,
  no_order,
  no_faktur,
  no_faktur,
  concat_ws(' | ',
    'Legacy DIST 2026',
    source_table,
    'stnota=' || nullif(status_source, ''),
    nullif(keterangan_source, ''),
    CASE WHEN user_batal IS NOT NULL OR ket_batal IS NOT NULL THEN concat_ws(' ', 'batal:', user_batal, ket_batal) END
  ),
  5,
  NULL,
  coalesce(total_penjualan, 0)::double precision,
  0,
  0,
  0,
  coalesce(resolved_discount, 0)::double precision
FROM tmp_legacy_sales_orders_to_insert;

INSERT INTO legacy_dist_2026.__map_sales_order (
  source_table, source_nota, no_order, no_faktur, id_sales_order
)
SELECT source_table, source_nota, no_order, no_faktur, target_id
FROM tmp_legacy_sales_orders_to_insert
ON CONFLICT (source_table, source_nota) DO NOTHING;

INSERT INTO tmp_insert_counts (label, row_count)
SELECT 'sales_order_inserted', count(*) FROM tmp_legacy_sales_orders_to_insert
ON CONFLICT (label) DO UPDATE SET row_count = EXCLUDED.row_count;

UPDATE legacy_dist_2026.__map_sales_order m
SET id_faktur = f.id
FROM public.faktur f
WHERE m.id_faktur IS NULL
  AND f.no_faktur = m.no_faktur;

CREATE TEMP TABLE tmp_legacy_faktur_to_insert AS
SELECT nextval('public.faktur_id_seq'::regclass)::integer AS target_id, h.*, m.id_sales_order
FROM tmp_legacy_sales_headers_enriched h
JOIN legacy_dist_2026.__map_sales_order m
  ON m.source_table = h.source_table
 AND m.source_nota = h.source_nota
LEFT JOIN public.faktur f
  ON f.no_faktur = h.no_faktur
WHERE m.id_faktur IS NULL
  AND f.id IS NULL
ORDER BY h.tanggal_order, h.source_table, h.source_nota;

INSERT INTO public.faktur (
  id,
  id_sales_order,
  no_faktur,
  nama_fakturist,
  status_faktur,
  jenis_faktur,
  subtotal_penjualan,
  subtotal_diskon,
  total_penjualan,
  total_dana_diterima,
  status_faktur_pajak,
  perubahan_ke,
  pajak,
  keterangan_batal,
  dpp,
  draft_total_penjualan,
  nominal_retur,
  total_penjualan_before_discount,
  unified_promo_nominal,
  manual_discount_value,
  manual_discount_nominal,
  order_discount_total
)
SELECT
  target_id,
  id_sales_order,
  no_faktur,
  'Legacy DIST',
  target_status_faktur,
  'penjualan',
  coalesce(resolved_dpp, total_penjualan, 0)::double precision,
  coalesce(resolved_discount, 0)::double precision,
  coalesce(total_penjualan, resolved_detail_total, 0)::double precision,
  coalesce(total_terbayar, 0)::double precision,
  0,
  0,
  greatest(coalesce(total_penjualan, resolved_detail_total, 0) - coalesce(resolved_dpp, 0), 0)::double precision,
  ket_batal,
  coalesce(resolved_dpp, total_penjualan, 0)::double precision,
  coalesce(total_penjualan, resolved_detail_total, 0)::double precision,
  coalesce(total_retur, 0)::double precision,
  coalesce(total_penjualan, resolved_detail_total, 0)::double precision,
  0,
  0,
  0,
  coalesce(resolved_discount, 0)::double precision
FROM tmp_legacy_faktur_to_insert;

UPDATE legacy_dist_2026.__map_sales_order m
SET id_faktur = f.target_id
FROM tmp_legacy_faktur_to_insert f
WHERE m.source_table = f.source_table
  AND m.source_nota = f.source_nota;

INSERT INTO tmp_insert_counts (label, row_count)
SELECT 'faktur_inserted', count(*) FROM tmp_legacy_faktur_to_insert
ON CONFLICT (label) DO UPDATE SET row_count = EXCLUDED.row_count;

CREATE TEMP TABLE tmp_legacy_faktur_detail_to_insert AS
SELECT
  nextval('public.faktur_detail_id_seq'::regclass)::integer AS target_id,
  m.id_faktur,
  m.id_sales_order,
  h.id_principal,
  coalesce(h.resolved_discount, 0) AS subtotal_diskon,
  coalesce(h.resolved_dpp, h.total_penjualan, 0) AS subtotal,
  greatest(coalesce(h.total_penjualan, h.resolved_detail_total, 0) - coalesce(h.resolved_dpp, 0), 0) AS pajak,
  coalesce(h.total_penjualan, h.resolved_detail_total, 0) AS total
FROM tmp_legacy_sales_headers_enriched h
JOIN legacy_dist_2026.__map_sales_order m
  ON m.source_table = h.source_table
 AND m.source_nota = h.source_nota
WHERE m.id_faktur IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM public.faktur_detail fd
    WHERE fd.id_faktur = m.id_faktur
      AND fd.id_sales_order = m.id_sales_order
      AND fd.id_principal = h.id_principal
  );

INSERT INTO public.faktur_detail (
  id,
  id_faktur,
  id_sales_order,
  id_principal,
  subtotal_diskon,
  subtotal,
  pajak,
  draft_total,
  total
)
SELECT
  target_id,
  id_faktur,
  id_sales_order,
  id_principal,
  subtotal_diskon::double precision,
  subtotal::double precision,
  pajak::double precision,
  total::double precision,
  total::double precision
FROM tmp_legacy_faktur_detail_to_insert;

INSERT INTO tmp_insert_counts (label, row_count)
SELECT 'faktur_detail_inserted', count(*) FROM tmp_legacy_faktur_detail_to_insert
ON CONFLICT (label) DO UPDATE SET row_count = EXCLUDED.row_count;

CREATE TEMP TABLE tmp_legacy_sales_details_to_insert AS
SELECT
  nextval('public.sales_order_detail_id_seq'::regclass)::integer AS target_id,
  d.*,
  m.id_sales_order
FROM tmp_legacy_sales_details d
JOIN legacy_dist_2026.__map_sales_order m
  ON m.source_table = d.source_table
 AND m.source_nota = d.source_nota
WHERE d.id_produk IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM legacy_dist_2026.__map_sales_order_detail md
    WHERE md.source_table = d.source_table
      AND md.source_nota = d.source_nota
      AND md.source_line_key = d.source_line_key
  )
ORDER BY d.source_table, d.source_nota, d.source_line_key;

INSERT INTO public.sales_order_detail (
  id,
  hargaorder,
  subtotaldelivered,
  is_bonus,
  estimasi_kubikasi,
  id_sales_order,
  id_produk,
  pieces_order,
  box_order,
  karton_order,
  pieces_booked,
  box_booked,
  karton_booked,
  pieces_picked,
  box_picked,
  karton_picked,
  pieces_shipped,
  box_shipped,
  karton_shipped,
  pieces_delivered,
  box_delivered,
  karton_delivered,
  subtotalorder,
  total_nilai_discount,
  total_persen_diskon
)
SELECT
  target_id,
  coalesce(harga, 0)::double precision,
  least(greatest(round(coalesce(jumlah_harga, 0)), '-2147483648'::numeric), '2147483647'::numeric)::integer,
  CASE WHEN coalesce(jumlah_harga, 0) = 0 AND coalesce(qty_total, 0) <> 0 THEN 1 ELSE 0 END,
  0,
  id_sales_order,
  id_produk,
  CASE
    WHEN coalesce(qty_piece, 0) <> 0 THEN round(qty_piece)::integer
    WHEN coalesce(qty_unit, 0) = 0 THEN round(coalesce(qty_total, 0))::integer
    ELSE 0
  END,
  0,
  round(coalesce(qty_unit, 0))::integer,
  CASE
    WHEN coalesce(qty_piece, 0) <> 0 THEN round(qty_piece)::integer
    WHEN coalesce(qty_unit, 0) = 0 THEN round(coalesce(qty_total, 0))::integer
    ELSE 0
  END,
  0,
  round(coalesce(qty_unit, 0))::integer,
  CASE
    WHEN coalesce(qty_piece, 0) <> 0 THEN round(qty_piece)::integer
    WHEN coalesce(qty_unit, 0) = 0 THEN round(coalesce(qty_total, 0))::integer
    ELSE 0
  END,
  0,
  round(coalesce(qty_unit, 0))::integer,
  CASE WHEN header_status_source = 'RL' THEN
    CASE
      WHEN coalesce(qty_piece, 0) <> 0 THEN round(qty_piece)::integer
      WHEN coalesce(qty_unit, 0) = 0 THEN round(coalesce(qty_total, 0))::integer
      ELSE 0
    END
  ELSE 0 END,
  0,
  CASE WHEN header_status_source = 'RL' THEN round(coalesce(qty_unit, 0))::integer ELSE 0 END,
  CASE WHEN header_status_source = 'RL' THEN
    CASE
      WHEN coalesce(qty_piece, 0) <> 0 THEN round(qty_piece)::integer
      WHEN coalesce(qty_unit, 0) = 0 THEN round(coalesce(qty_total, 0))::integer
      ELSE 0
    END
  ELSE 0 END,
  0,
  CASE WHEN header_status_source = 'RL' THEN round(coalesce(qty_unit, 0))::integer ELSE 0 END,
  coalesce(jumlah_harga, 0)::double precision,
  coalesce(discrp, 0)::double precision,
  round(coalesce(disc1, 0) + coalesce(disc2, 0) + coalesce(disc3, 0))::integer
FROM tmp_legacy_sales_details_to_insert;

INSERT INTO legacy_dist_2026.__map_sales_order_detail (
  source_table,
  source_nota,
  source_line_key,
  id_sales_order,
  id_sales_order_detail
)
SELECT
  source_table,
  source_nota,
  source_line_key,
  id_sales_order,
  target_id
FROM tmp_legacy_sales_details_to_insert
ON CONFLICT (source_table, source_nota, source_line_key) DO NOTHING;

INSERT INTO tmp_insert_counts (label, row_count)
SELECT 'sales_order_detail_inserted', count(*) FROM tmp_legacy_sales_details_to_insert
ON CONFLICT (label) DO UPDATE SET row_count = EXCLUDED.row_count;

ANALYZE public.sales_order;
ANALYZE public.sales_order_detail;
ANALYZE public.faktur;
ANALYZE public.faktur_detail;
ANALYZE legacy_dist_2026.__map_sales_order;
ANALYZE legacy_dist_2026.__map_sales_order_detail;
ANALYZE legacy_dist_2026.__mapping_issues;

COMMIT;

\echo '--- legacy sales 2026 mapping summary ---'

SELECT label, row_count
FROM tmp_insert_counts
ORDER BY label;

SELECT
  'mapped_sales_order_total' AS label,
  count(*) AS row_count
FROM legacy_dist_2026.__map_sales_order;

SELECT
  'mapped_sales_order_detail_total' AS label,
  count(*) AS row_count
FROM legacy_dist_2026.__map_sales_order_detail;

SELECT issue_type, count(*) AS row_count
FROM legacy_dist_2026.__mapping_issues
WHERE module = 'sales_2026'
GROUP BY issue_type
ORDER BY issue_type;

SELECT
  h.status_source,
  count(*) AS mapped_headers,
  sum(coalesce(h.total_penjualan, 0))::numeric(20, 2) AS total_penjualan
FROM tmp_legacy_sales_headers h
JOIN legacy_dist_2026.__map_sales_order m
  ON m.source_table = h.source_table
 AND m.source_nota = h.source_nota
GROUP BY h.status_source
ORDER BY h.status_source;
