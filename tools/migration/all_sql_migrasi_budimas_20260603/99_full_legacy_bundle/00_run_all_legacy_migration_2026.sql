-- Budimas full legacy data migration 2026
-- Generated bundle: run from start to finish after staging schemas are loaded.
-- Required staging schemas: legacy_dist_2026 and legacy_dist_2025_ar.
-- Each section keeps the original BEGIN/COMMIT block from its source file.
-- psql meta-commands from source files were removed so this file is plain SQL.


-- ============================================================================
-- 01 Sales 2026 ke public
-- Source: tools\migration\map_legacy_sales_2026_to_public.sql
-- ============================================================================
SELECT '01 Sales 2026 ke public' AS migration_step;


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


-- ============================================================================
-- 02 Sales/AR 2025 tertahan ke public
-- Source: tools\migration\map_legacy_sales_2025_ar_to_public.sql
-- ============================================================================
SELECT '02 Sales/AR 2025 tertahan ke public' AS migration_step;


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
WHERE module = 'sales_2025_ar';

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
FROM legacy_dist_2025_ar.djualsmandroid
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
FROM legacy_dist_2025_ar.hjualsm
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
FROM legacy_dist_2025_ar.hjualsmandroid
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
FROM legacy_dist_2025_ar.djualsm d
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
FROM legacy_dist_2025_ar.djualsmandroid d
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

CREATE TEMP TABLE tmp_legacy_header_principal_inferred AS
WITH detail_rows AS (
  SELECT
    'hjualsm'::text AS source_table,
    upper(btrim(nota)) AS source_nota,
    lower(btrim(kodestok)) AS kode_stok,
    lower(btrim(masterkode)) AS master_kode,
    pg_temp.legacy_num(jumlahharga) AS jumlah_harga
  FROM legacy_dist_2025_ar.djualsm
  WHERE nullif(btrim(nota), '') IS NOT NULL
  UNION ALL
  SELECT
    'hjualsmandroid_uninvoiced'::text AS source_table,
    upper(btrim(nota)) AS source_nota,
    lower(btrim(kodestok)) AS kode_stok,
    lower(btrim(masterkode)) AS master_kode,
    pg_temp.legacy_num(jumlahharga) AS jumlah_harga
  FROM legacy_dist_2025_ar.djualsmandroid
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
  FROM legacy_dist_2025_ar.djualsm
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
  FROM legacy_dist_2025_ar.djualsmandroid da
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
  'sales_2025_ar',
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
  'sales_2025_ar',
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
  'sales_2025_ar',
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
  'sales_2025_ar',
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
  'sales_2025_ar',
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
    'Legacy DIST 2025 AR',
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
WHERE module = 'sales_2025_ar'
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


-- ============================================================================
-- 03 Pembayaran dbayarsm 2026 ke public
-- Source: tools\migration\map_legacy_payments_2026_to_public.sql
-- ============================================================================
SELECT '03 Pembayaran dbayarsm 2026 ke public' AS migration_step;


BEGIN;

LOCK TABLE public.setoran_customer, public.setoran, public.faktur IN SHARE ROW EXCLUSIVE MODE;

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
    WHEN raw_value ~ '^1900-01-01' THEN NULL
    WHEN raw_value ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' THEN substring(raw_value from 1 for 10)::date
    WHEN raw_value ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}' THEN to_date(substring(raw_value from 1 for 10), 'DD/MM/YYYY')
    ELSE NULL
  END
  FROM cleaned;
$$;

SELECT setval('public.setoran_customer_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.setoran_customer), 0), 1), true);
SELECT setval('public.setoran_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.setoran), 0), 1), true);

CREATE TABLE IF NOT EXISTS legacy_dist_2026.__map_payment_setoran (
  source_table text NOT NULL,
  source_receipt text NOT NULL,
  source_nota text NOT NULL,
  source_line_key text NOT NULL,
  id_sales_order integer NOT NULL,
  id_setoran_customer integer NOT NULL,
  id_setoran integer NOT NULL,
  mapped_at timestamp without time zone NOT NULL DEFAULT now(),
  PRIMARY KEY (source_table, source_receipt, source_nota, source_line_key)
);

CREATE INDEX IF NOT EXISTS __map_payment_setoran_order_idx
  ON legacy_dist_2026.__map_payment_setoran (id_sales_order);

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
WHERE module = 'payment_2026_dbayarsm';

CREATE TEMP TABLE tmp_run AS
SELECT to_char(clock_timestamp(), 'YYYYMMDDHH24MISS') AS run_id;

CREATE TEMP TABLE tmp_insert_counts (
  label text PRIMARY KEY,
  row_count bigint NOT NULL
);

CREATE TEMP TABLE tmp_legacy_payments_raw AS
WITH raw_payments AS (
  SELECT
    'dbayarsm'::text AS source_table,
    btrim(d.nokwitansi) AS source_receipt,
    btrim(d.nota) AS source_nota,
    pg_temp.legacy_date(d.tanggal) AS tanggal_bayar,
    nullif(btrim(d.kodecustomer), '') AS kode_customer,
    nullif(btrim(d.namacustomer), '') AS nama_customer,
    pg_temp.legacy_num(d.jumlahbayar) AS jumlah_bayar,
    nullif(btrim(d.nobukti), '') AS no_bukti,
    pg_temp.legacy_date(d.tglcair) AS tanggal_cair,
    nullif(btrim(d.keterangan), '') AS keterangan_detail,
    pg_temp.legacy_num(h.cash) AS header_cash,
    pg_temp.legacy_num(h.noncash) AS header_noncash,
    pg_temp.legacy_num(h.lain) AS header_lain,
    pg_temp.legacy_num(h.jumlahbayar) AS header_jumlah_bayar,
    nullif(btrim(h.nobukti), '') AS header_no_bukti,
    nullif(btrim(h.keterangan), '') AS header_keterangan,
    nullif(btrim(h.namapembayar), '') AS nama_pembayar,
    d.ctid::text AS physical_row
  FROM legacy_dist_2026.dbayarsm d
  LEFT JOIN legacy_dist_2026.hbayarsm h
    ON lower(btrim(h.nokwitansi)) = lower(btrim(d.nokwitansi))
  WHERE nullif(btrim(d.nokwitansi), '') IS NOT NULL
    AND nullif(btrim(d.nota), '') IS NOT NULL
    AND coalesce(pg_temp.legacy_num(d.jumlahbayar), 0) > 0
)
SELECT
  *,
  lpad(row_number() OVER (
    PARTITION BY source_table, source_receipt, source_nota
    ORDER BY tanggal_bayar NULLS LAST, jumlah_bayar, coalesce(no_bukti, ''), physical_row
  )::text, 8, '0') AS source_line_key,
  CASE
    WHEN coalesce(header_cash, 0) > 0 THEN 1
    WHEN coalesce(header_noncash, 0) > 0 THEN 2
    ELSE 2
  END AS tipe_setoran,
  CASE
    WHEN coalesce(header_cash, 0) > 0 THEN 'Tunai'
    WHEN coalesce(header_noncash, 0) > 0 THEN 'Non Tunai'
    ELSE 'Lainnya'
  END AS metode_pembayaran
FROM raw_payments;

CREATE UNIQUE INDEX tmp_legacy_payments_raw_source_uq
  ON tmp_legacy_payments_raw (source_table, source_receipt, source_nota, source_line_key);
CREATE INDEX tmp_legacy_payments_raw_nota_idx
  ON tmp_legacy_payments_raw (lower(source_nota));

CREATE TEMP TABLE tmp_legacy_payments_resolved AS
SELECT
  p.*,
  m.id_sales_order,
  m.id_faktur,
  so.id_plafon,
  pl.id_sales
FROM tmp_legacy_payments_raw p
LEFT JOIN legacy_dist_2026.__map_sales_order m
  ON lower(m.no_faktur) = lower(p.source_nota)
LEFT JOIN public.sales_order so
  ON so.id = m.id_sales_order
LEFT JOIN public.plafon pl
  ON pl.id = so.id_plafon;

CREATE UNIQUE INDEX tmp_legacy_payments_resolved_source_uq
  ON tmp_legacy_payments_resolved (source_table, source_receipt, source_nota, source_line_key);
CREATE INDEX tmp_legacy_payments_resolved_order_idx
  ON tmp_legacy_payments_resolved (id_sales_order);

INSERT INTO legacy_dist_2026.__mapping_issues (
  run_id, module, source_table, source_key, issue_type, issue_detail
)
SELECT
  r.run_id,
  'payment_2026_dbayarsm',
  p.source_table,
  p.source_receipt || '|' || p.source_nota || '|' || p.source_line_key,
  'payment_unresolved_sales_order',
  jsonb_build_object(
    'receipt', p.source_receipt,
    'nota', p.source_nota,
    'tanggal_bayar', p.tanggal_bayar,
    'jumlah_bayar', p.jumlah_bayar,
    'kode_customer', p.kode_customer,
    'nama_customer', p.nama_customer
  )
FROM tmp_legacy_payments_resolved p
CROSS JOIN tmp_run r
WHERE p.id_sales_order IS NULL;

CREATE TEMP TABLE tmp_legacy_payments_ready AS
SELECT p.*
FROM tmp_legacy_payments_resolved p
LEFT JOIN legacy_dist_2026.__map_payment_setoran m
  ON m.source_table = p.source_table
 AND m.source_receipt = p.source_receipt
 AND m.source_nota = p.source_nota
 AND m.source_line_key = p.source_line_key
WHERE p.id_sales_order IS NOT NULL
  AND m.source_line_key IS NULL;

CREATE UNIQUE INDEX tmp_legacy_payments_ready_source_uq
  ON tmp_legacy_payments_ready (source_table, source_receipt, source_nota, source_line_key);

CREATE TEMP TABLE tmp_legacy_payments_to_insert AS
SELECT
  nextval('public.setoran_customer_id_seq'::regclass)::integer AS target_setoran_customer_id,
  nextval('public.setoran_id_seq'::regclass)::integer AS target_setoran_id,
  p.*
FROM tmp_legacy_payments_ready p
ORDER BY p.tanggal_bayar, p.source_receipt, p.source_nota, p.source_line_key;

INSERT INTO public.setoran_customer (
  id,
  id_sales,
  id_sales_order,
  jumlah_setoran,
  tipe_setoran,
  tanggal_input,
  is_rekap
)
SELECT
  target_setoran_customer_id,
  id_sales,
  id_sales_order,
  jumlah_bayar::double precision,
  tipe_setoran,
  tanggal_bayar,
  1
FROM tmp_legacy_payments_to_insert;

INSERT INTO public.setoran (
  id,
  id_sales_order,
  draft_tanggal_input,
  draft_jumlah_setor,
  draft_tipe_setor,
  keterangan,
  nama_pj,
  jumlah_setoran,
  tipe_setoran,
  tanggal_setoran_diterima,
  keterangan_kasir,
  nama_kasir,
  metode_pembayaran,
  bukti_transfer,
  status_setoran,
  setoran_bersih,
  id_setoran_customer
)
SELECT
  target_setoran_id,
  id_sales_order,
  tanggal_bayar,
  jumlah_bayar::double precision,
  tipe_setoran,
  concat_ws(' | ',
    'Legacy DIST 2026 dbayarsm',
    'kwitansi=' || source_receipt,
    'nota=' || source_nota,
    nullif(keterangan_detail, ''),
    nullif(header_keterangan, '')
  ),
  coalesce(nama_pembayar, nama_customer),
  jumlah_bayar::double precision,
  tipe_setoran,
  tanggal_bayar,
  header_keterangan,
  'Legacy DIST',
  metode_pembayaran,
  coalesce(no_bukti, header_no_bukti),
  3,
  jumlah_bayar::double precision,
  target_setoran_customer_id
FROM tmp_legacy_payments_to_insert;

INSERT INTO legacy_dist_2026.__map_payment_setoran (
  source_table,
  source_receipt,
  source_nota,
  source_line_key,
  id_sales_order,
  id_setoran_customer,
  id_setoran
)
SELECT
  source_table,
  source_receipt,
  source_nota,
  source_line_key,
  id_sales_order,
  target_setoran_customer_id,
  target_setoran_id
FROM tmp_legacy_payments_to_insert
ON CONFLICT (source_table, source_receipt, source_nota, source_line_key) DO NOTHING;

INSERT INTO tmp_insert_counts (label, row_count)
SELECT 'setoran_customer_inserted', count(*) FROM tmp_legacy_payments_to_insert
ON CONFLICT (label) DO UPDATE SET row_count = EXCLUDED.row_count;

INSERT INTO tmp_insert_counts (label, row_count)
SELECT 'setoran_inserted', count(*) FROM tmp_legacy_payments_to_insert
ON CONFLICT (label) DO UPDATE SET row_count = EXCLUDED.row_count;

WITH paid AS (
  SELECT
    m.id_sales_order,
    sum(coalesce(sc.jumlah_setoran, 0)) AS total_paid
  FROM legacy_dist_2026.__map_payment_setoran m
  JOIN public.setoran_customer sc
    ON sc.id = m.id_setoran_customer
  GROUP BY m.id_sales_order
), updated AS (
  UPDATE public.faktur f
  SET
    total_dana_diterima = greatest(coalesce(f.total_dana_diterima, 0), paid.total_paid),
    status_faktur = CASE
      WHEN f.status_faktur = 4 THEN 4
      WHEN greatest(coalesce(f.total_dana_diterima, 0), paid.total_paid) >= coalesce(f.total_penjualan, 0) - 1 THEN 3
      WHEN f.status_faktur = 3 THEN 3
      ELSE 2
    END
  FROM paid
  WHERE f.id_sales_order = paid.id_sales_order
    AND f.jenis_faktur = 'penjualan'
  RETURNING f.id
)
INSERT INTO tmp_insert_counts (label, row_count)
SELECT 'faktur_payment_summary_updated', count(*) FROM updated
ON CONFLICT (label) DO UPDATE SET row_count = EXCLUDED.row_count;

ANALYZE public.setoran_customer;
ANALYZE public.setoran;
ANALYZE public.faktur;
ANALYZE legacy_dist_2026.__map_payment_setoran;
ANALYZE legacy_dist_2026.__mapping_issues;

COMMIT;


SELECT label, row_count
FROM tmp_insert_counts
ORDER BY label;

SELECT
  'mapped_payment_total' AS label,
  count(*) AS row_count
FROM legacy_dist_2026.__map_payment_setoran;

SELECT issue_type, count(*) AS row_count
FROM legacy_dist_2026.__mapping_issues
WHERE module = 'payment_2026_dbayarsm'
GROUP BY issue_type
ORDER BY issue_type;

SELECT
  min(sc.tanggal_input) AS min_payment_date,
  max(sc.tanggal_input) AS max_payment_date,
  sum(sc.jumlah_setoran)::numeric(20, 2) AS total_payment
FROM legacy_dist_2026.__map_payment_setoran m
JOIN public.setoran_customer sc
  ON sc.id = m.id_setoran_customer;


-- ============================================================================
-- 04 Pembayaran non-dbayarsm/mobile 2026 ke public
-- Source: tools\migration\map_legacy_mobile_payments_2026_to_public.sql
-- ============================================================================
SELECT '04 Pembayaran non-dbayarsm/mobile 2026 ke public' AS migration_step;


BEGIN;

LOCK TABLE public.setoran_customer, public.setoran, public.faktur IN SHARE ROW EXCLUSIVE MODE;

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
    WHEN raw_value ~ '^1900-01-01' THEN NULL
    WHEN raw_value ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' THEN substring(raw_value from 1 for 10)::date
    WHEN raw_value ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}' THEN to_date(substring(raw_value from 1 for 10), 'DD/MM/YYYY')
    ELSE NULL
  END
  FROM cleaned;
$$;

SELECT setval('public.setoran_customer_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.setoran_customer), 0), 1), true);
SELECT setval('public.setoran_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.setoran), 0), 1), true);

CREATE TABLE IF NOT EXISTS legacy_dist_2026.__map_payment_setoran (
  source_table text NOT NULL,
  source_receipt text NOT NULL,
  source_nota text NOT NULL,
  source_line_key text NOT NULL,
  id_sales_order integer NOT NULL,
  id_setoran_customer integer NOT NULL,
  id_setoran integer NOT NULL,
  mapped_at timestamp without time zone NOT NULL DEFAULT now(),
  PRIMARY KEY (source_table, source_receipt, source_nota, source_line_key)
);

CREATE INDEX IF NOT EXISTS __map_payment_setoran_order_idx
  ON legacy_dist_2026.__map_payment_setoran (id_sales_order);

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

DELETE FROM legacy_dist_2026.__mapping_issues
WHERE module = 'payment_2026_mobile';

CREATE TEMP TABLE tmp_run AS
SELECT to_char(clock_timestamp(), 'YYYYMMDDHH24MISS') AS run_id;

CREATE TEMP TABLE tmp_insert_counts (
  label text PRIMARY KEY,
  row_count bigint NOT NULL
);

CREATE TEMP TABLE tmp_mobile_payments_raw AS
SELECT
  'pembayaran_non_dbayarsm'::text AS source_table,
  btrim(p.nokwitansi) AS source_receipt,
  btrim(p.nota) AS source_nota,
  '00000001'::text AS source_line_key,
  pg_temp.legacy_date(p.tanggal) AS tanggal_bayar,
  nullif(btrim(p.kodecustomer), '') AS kode_customer,
  nullif(btrim(p.kodesales), '') AS kode_sales,
  pg_temp.legacy_num(p.totaltagihan) AS total_tagihan,
  pg_temp.legacy_num(p.totalbayar) AS jumlah_bayar,
  nullif(btrim(p.status), '') AS status_source,
  nullif(btrim(p.metode), '') AS metode_source,
  nullif(btrim(p.nobukti), '') AS no_bukti,
  nullif(btrim(p.idkunjungan), '') AS id_kunjungan,
  CASE WHEN upper(btrim(coalesce(p.metode, ''))) = 'TUNAI' THEN 1 ELSE 2 END AS tipe_setoran,
  CASE WHEN upper(btrim(coalesce(p.metode, ''))) = 'TUNAI' THEN 'Tunai' ELSE 'Non Tunai' END AS metode_pembayaran
FROM legacy_dist_2026.pembayaran p
JOIN legacy_dist_2026.__map_sales_order m
  ON lower(btrim(m.no_faktur)) = lower(btrim(p.nota))
WHERE nullif(btrim(p.nokwitansi), '') IS NOT NULL
  AND nullif(btrim(p.nota), '') IS NOT NULL
  AND coalesce(pg_temp.legacy_num(p.totalbayar), 0) > 0
  AND NOT EXISTS (
    SELECT 1
    FROM legacy_dist_2026.dbayarsm d
    WHERE lower(btrim(d.nota)) = lower(btrim(p.nota))
  );

CREATE UNIQUE INDEX tmp_mobile_payments_raw_source_uq
  ON tmp_mobile_payments_raw (source_table, source_receipt, source_nota, source_line_key);

CREATE TEMP TABLE tmp_mobile_payments_ready AS
SELECT
  p.*,
  m.id_sales_order,
  m.id_faktur,
  so.id_plafon,
  pl.id_sales
FROM tmp_mobile_payments_raw p
JOIN legacy_dist_2026.__map_sales_order m
  ON lower(m.no_faktur) = lower(p.source_nota)
JOIN public.sales_order so
  ON so.id = m.id_sales_order
LEFT JOIN public.plafon pl
  ON pl.id = so.id_plafon
LEFT JOIN legacy_dist_2026.__map_payment_setoran existing
  ON existing.source_table = p.source_table
 AND existing.source_receipt = p.source_receipt
 AND existing.source_nota = p.source_nota
 AND existing.source_line_key = p.source_line_key
WHERE existing.source_line_key IS NULL;

CREATE TEMP TABLE tmp_mobile_payments_to_insert AS
SELECT
  nextval('public.setoran_customer_id_seq'::regclass)::integer AS target_setoran_customer_id,
  nextval('public.setoran_id_seq'::regclass)::integer AS target_setoran_id,
  p.*
FROM tmp_mobile_payments_ready p
ORDER BY p.tanggal_bayar, p.source_receipt, p.source_nota;

INSERT INTO public.setoran_customer (
  id,
  id_sales,
  id_sales_order,
  jumlah_setoran,
  tipe_setoran,
  tanggal_input,
  is_rekap
)
SELECT
  target_setoran_customer_id,
  id_sales,
  id_sales_order,
  jumlah_bayar::double precision,
  tipe_setoran,
  tanggal_bayar,
  1
FROM tmp_mobile_payments_to_insert;

INSERT INTO public.setoran (
  id,
  id_sales_order,
  draft_tanggal_input,
  draft_jumlah_setor,
  draft_tipe_setor,
  keterangan,
  nama_pj,
  jumlah_setoran,
  tipe_setoran,
  tanggal_setoran_diterima,
  keterangan_kasir,
  nama_kasir,
  metode_pembayaran,
  bukti_transfer,
  status_setoran,
  setoran_bersih,
  id_setoran_customer
)
SELECT
  target_setoran_id,
  id_sales_order,
  tanggal_bayar,
  jumlah_bayar::double precision,
  tipe_setoran,
  concat_ws(' | ',
    'Legacy DIST 2026 pembayaran',
    'kwitansi=' || source_receipt,
    'nota=' || source_nota,
    'status=' || coalesce(status_source, ''),
    'idkunjungan=' || coalesce(id_kunjungan, '')
  ),
  kode_sales,
  jumlah_bayar::double precision,
  tipe_setoran,
  tanggal_bayar,
  metode_source,
  'Legacy DIST',
  metode_pembayaran,
  no_bukti,
  3,
  jumlah_bayar::double precision,
  target_setoran_customer_id
FROM tmp_mobile_payments_to_insert;

INSERT INTO legacy_dist_2026.__map_payment_setoran (
  source_table,
  source_receipt,
  source_nota,
  source_line_key,
  id_sales_order,
  id_setoran_customer,
  id_setoran
)
SELECT
  source_table,
  source_receipt,
  source_nota,
  source_line_key,
  id_sales_order,
  target_setoran_customer_id,
  target_setoran_id
FROM tmp_mobile_payments_to_insert
ON CONFLICT (source_table, source_receipt, source_nota, source_line_key) DO NOTHING;

INSERT INTO tmp_insert_counts (label, row_count)
SELECT 'setoran_customer_inserted', count(*) FROM tmp_mobile_payments_to_insert
ON CONFLICT (label) DO UPDATE SET row_count = EXCLUDED.row_count;

INSERT INTO tmp_insert_counts (label, row_count)
SELECT 'setoran_inserted', count(*) FROM tmp_mobile_payments_to_insert
ON CONFLICT (label) DO UPDATE SET row_count = EXCLUDED.row_count;

WITH paid AS (
  SELECT
    m.id_sales_order,
    sum(coalesce(sc.jumlah_setoran, 0)) AS total_paid
  FROM legacy_dist_2026.__map_payment_setoran m
  JOIN public.setoran_customer sc
    ON sc.id = m.id_setoran_customer
  GROUP BY m.id_sales_order
), updated AS (
  UPDATE public.faktur f
  SET
    total_dana_diterima = greatest(coalesce(f.total_dana_diterima, 0), paid.total_paid),
    status_faktur = CASE
      WHEN f.status_faktur = 4 THEN 4
      WHEN greatest(coalesce(f.total_dana_diterima, 0), paid.total_paid) >= coalesce(f.total_penjualan, 0) - 1 THEN 3
      WHEN f.status_faktur = 3 THEN 3
      ELSE 2
    END
  FROM paid
  WHERE f.id_sales_order = paid.id_sales_order
    AND f.jenis_faktur = 'penjualan'
  RETURNING f.id
)
INSERT INTO tmp_insert_counts (label, row_count)
SELECT 'faktur_payment_summary_updated', count(*) FROM updated
ON CONFLICT (label) DO UPDATE SET row_count = EXCLUDED.row_count;

ANALYZE public.setoran_customer;
ANALYZE public.setoran;
ANALYZE public.faktur;
ANALYZE legacy_dist_2026.__map_payment_setoran;

COMMIT;


SELECT label, row_count
FROM tmp_insert_counts
ORDER BY label;

SELECT
  'mapped_mobile_payment_total' AS label,
  count(*) AS row_count,
  sum(sc.jumlah_setoran)::numeric(20, 2) AS total_payment
FROM legacy_dist_2026.__map_payment_setoran m
JOIN public.setoran_customer sc
  ON sc.id = m.id_setoran_customer
WHERE m.source_table = 'pembayaran_non_dbayarsm';


-- ============================================================================
-- 05 Pembelian 2026 ke hutang pembelian
-- Source: tools\migration\map_legacy_purchase_2026_to_public.sql
-- ============================================================================
SELECT '05 Pembelian 2026 ke hutang pembelian' AS migration_step;


BEGIN;

LOCK TABLE
  public.purchase_order,
  public.purchase_order_detail,
  public.purchase_order_detail_jumlah,
  public.purchase_transaksi,
  public.purchase_transaksi_detail,
  public.purchase_transaksi_detail_jumlah,
  public.purchase_tagihan,
  public.purchase_tagihan_detail
IN SHARE ROW EXCLUSIVE MODE;

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

-- A few purchase tables still use legacy sequence names that are not owned by
-- the id column, so use the actual sequence names from the column defaults.
SELECT setval('public.purchase_request_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.purchase_order), 0), 1), true);
SELECT setval('public.purchase_request_detail_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.purchase_order_detail), 0), 1), true);
SELECT setval('public.purchase_order_detail_jumlah_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.purchase_order_detail_jumlah), 0), 1), true);
SELECT setval('public.purchase_transaksi_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.purchase_transaksi), 0), 1), true);
SELECT setval('public.purchase_transaksi_detail_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.purchase_transaksi_detail), 0), 1), true);
SELECT setval('public.purchas_transaksi_detail_jumlah_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.purchase_transaksi_detail_jumlah), 0), 1), true);
SELECT setval('public.purchase_tagihan_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.purchase_tagihan), 0), 1), true);
SELECT setval('public.purchase_tagihan_pelunasan_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.purchase_tagihan_detail), 0), 1), true);

CREATE TABLE IF NOT EXISTS legacy_dist_2026.__map_purchase_header (
  source_nota text PRIMARY KEY,
  source_status text NOT NULL,
  source_invoice_no text,
  id_purchase_order integer NOT NULL,
  id_purchase_transaksi integer,
  id_purchase_tagihan integer,
  mapped_at timestamp without time zone NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS legacy_dist_2026.__map_purchase_detail (
  source_nota text NOT NULL,
  source_line_key text NOT NULL,
  id_purchase_order_detail integer NOT NULL,
  id_purchase_order_detail_jumlah integer NOT NULL,
  id_purchase_transaksi_detail integer NOT NULL,
  id_purchase_transaksi_detail_jumlah integer NOT NULL,
  mapped_at timestamp without time zone NOT NULL DEFAULT now(),
  PRIMARY KEY (source_nota, source_line_key)
);

CREATE TABLE IF NOT EXISTS legacy_dist_2026.__map_purchase_tagihan (
  source_tagihan_key text PRIMARY KEY,
  no_tagihan text NOT NULL,
  id_purchase_tagihan integer NOT NULL,
  mapped_at timestamp without time zone NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS legacy_dist_2026.__purchase_mapping_issues (
  id bigserial PRIMARY KEY,
  run_id text NOT NULL,
  source_table text,
  source_key text,
  issue_type text NOT NULL,
  issue_detail jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamp without time zone NOT NULL DEFAULT now()
);

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

CREATE TEMP TABLE tmp_legacy_purchase_headers AS
SELECT
  btrim(h.nota) AS source_nota,
  lower(btrim(h.kodeprinciple)) AS kode_principal,
  btrim(h.kodeprinciple) AS kode_principal_raw,
  btrim(h.namaprinciple) AS nama_principal,
  upper(coalesce(nullif(btrim(h.stnota), ''), '<BLANK>')) AS source_status,
  pg_temp.legacy_date(h.tanggal) AS tanggal,
  coalesce(nullif(btrim(h.nofaktur), ''), btrim(h.nota)) AS invoice_no,
  nullif(btrim(h.keterangan), '') AS keterangan_source,
  pg_temp.legacy_num(h.jumlahharga) AS subtotal,
  coalesce(pg_temp.legacy_num(h.totalretur), 0) AS total_retur,
  pm.id_principal
FROM legacy_dist_2026.hpembelian h
LEFT JOIN tmp_principal_map pm ON pm.code = lower(btrim(h.kodeprinciple))
WHERE nullif(btrim(h.nota), '') IS NOT NULL;

CREATE UNIQUE INDEX tmp_legacy_purchase_headers_nota_uq
  ON tmp_legacy_purchase_headers (source_nota);

CREATE TEMP TABLE tmp_legacy_purchase_headers_ready AS
SELECT
  *,
  greatest(coalesce(subtotal, 0) - coalesce(total_retur, 0), 0) AS total
FROM tmp_legacy_purchase_headers
WHERE source_status = 'P'
  AND id_principal IS NOT NULL;

CREATE TEMP TABLE tmp_legacy_purchase_details AS
SELECT
  h.source_nota,
  coalesce(nullif(btrim(d.baris), ''), row_number() OVER (PARTITION BY btrim(d.nota) ORDER BY btrim(d.kodestok), btrim(d.namabarang))::text) AS source_line_key,
  lower(btrim(d.kodestok)) AS kode_produk,
  btrim(d.kodestok) AS kode_produk_raw,
  btrim(d.namabarang) AS nama_produk_source,
  pg_temp.legacy_num(d.unit) AS qty_uom,
  pg_temp.legacy_num(d.perunit) AS qty_per_uom,
  pg_temp.legacy_num(d.jumlah) AS qty_base,
  pg_temp.legacy_num(d.harga) AS harga_beli,
  pg_temp.legacy_num(d.jumlahharga) AS subtotal,
  coalesce(psp.id_produk, psm.id_produk) AS id_produk
FROM legacy_dist_2026.dpembelian d
JOIN tmp_legacy_purchase_headers_ready h ON h.source_nota = btrim(d.nota)
LEFT JOIN tmp_product_sku_principal_map psp
  ON psp.code = lower(btrim(d.kodestok))
 AND psp.id_principal = h.id_principal
LEFT JOIN tmp_product_sku_any_map psm ON psm.code = lower(btrim(d.kodestok))
WHERE nullif(btrim(d.nota), '') IS NOT NULL;

CREATE INDEX tmp_legacy_purchase_details_idx
  ON tmp_legacy_purchase_details (source_nota, source_line_key);

INSERT INTO legacy_dist_2026.__purchase_mapping_issues (
  run_id, source_table, source_key, issue_type, issue_detail
)
SELECT
  'legacy_purchase_2026_to_public',
  'hpembelian',
  source_nota,
  'purchase_header_skipped_status',
  jsonb_build_object('stnota', source_status, 'invoice_no', invoice_no, 'total', subtotal)
FROM tmp_legacy_purchase_headers
WHERE source_status <> 'P'
  AND NOT EXISTS (
    SELECT 1
    FROM legacy_dist_2026.__purchase_mapping_issues i
    WHERE i.run_id = 'legacy_purchase_2026_to_public'
      AND i.source_table = 'hpembelian'
      AND i.source_key = tmp_legacy_purchase_headers.source_nota
      AND i.issue_type = 'purchase_header_skipped_status'
  );

INSERT INTO legacy_dist_2026.__purchase_mapping_issues (
  run_id, source_table, source_key, issue_type, issue_detail
)
SELECT
  'legacy_purchase_2026_to_public',
  'hpembelian',
  source_nota,
  'missing_principal',
  jsonb_build_object('kode_principal', kode_principal_raw, 'nama_principal', nama_principal)
FROM tmp_legacy_purchase_headers
WHERE source_status = 'P'
  AND id_principal IS NULL
  AND NOT EXISTS (
    SELECT 1
    FROM legacy_dist_2026.__purchase_mapping_issues i
    WHERE i.run_id = 'legacy_purchase_2026_to_public'
      AND i.source_table = 'hpembelian'
      AND i.source_key = tmp_legacy_purchase_headers.source_nota
      AND i.issue_type = 'missing_principal'
  );

INSERT INTO legacy_dist_2026.__purchase_mapping_issues (
  run_id, source_table, source_key, issue_type, issue_detail
)
SELECT
  'legacy_purchase_2026_to_public',
  'dpembelian',
  source_nota || ':' || source_line_key,
  'missing_product',
  jsonb_build_object('kode_produk', kode_produk_raw, 'nama_produk', nama_produk_source)
FROM tmp_legacy_purchase_details
WHERE id_produk IS NULL
  AND NOT EXISTS (
    SELECT 1
    FROM legacy_dist_2026.__purchase_mapping_issues i
    WHERE i.run_id = 'legacy_purchase_2026_to_public'
      AND i.source_table = 'dpembelian'
      AND i.source_key = tmp_legacy_purchase_details.source_nota || ':' || tmp_legacy_purchase_details.source_line_key
      AND i.issue_type = 'missing_product'
  );

CREATE TEMP TABLE tmp_purchase_headers_to_insert AS
SELECT
  nextval('public.purchase_request_id_seq'::regclass)::integer AS id_purchase_order,
  nextval('public.purchase_transaksi_id_seq'::regclass)::integer AS id_purchase_transaksi,
  h.*
FROM tmp_legacy_purchase_headers_ready h
WHERE NOT EXISTS (
  SELECT 1
  FROM legacy_dist_2026.__map_purchase_header m
  WHERE m.source_nota = h.source_nota
);

INSERT INTO public.purchase_order (
  id, cabang_id, principal_id, proses_id_berjalan, kode, keterangan,
  batch_pengiriman, total
)
SELECT
  id_purchase_order,
  5,
  id_principal,
  4,
  source_nota,
  left('Legacy DIST HPembelian | stnota=' || source_status || ' | faktur=' || invoice_no, 100),
  1,
  total::double precision
FROM tmp_purchase_headers_to_insert;

INSERT INTO public.purchase_transaksi (
  id, order_id, no_transaksi, subtotal, potongan, biaya_lainnya, total,
  status_pembayaran, proses_id_berjalan, batch, keterangan, jatuh_tempo
)
SELECT
  id_purchase_transaksi,
  id_purchase_order,
  source_nota,
  subtotal::double precision,
  total_retur::double precision,
  0,
  total::double precision,
  1,
  4,
  1,
  left('Legacy DIST HPembelian | faktur=' || invoice_no, 100),
  tanggal
FROM tmp_purchase_headers_to_insert;

INSERT INTO legacy_dist_2026.__map_purchase_header (
  source_nota, source_status, source_invoice_no,
  id_purchase_order, id_purchase_transaksi
)
SELECT
  source_nota,
  source_status,
  invoice_no,
  id_purchase_order,
  id_purchase_transaksi
FROM tmp_purchase_headers_to_insert;

CREATE TEMP TABLE tmp_purchase_details_to_insert AS
SELECT
  nextval('public.purchase_request_detail_id_seq'::regclass)::integer AS id_purchase_order_detail,
  nextval('public.purchase_order_detail_jumlah_id_seq'::regclass)::integer AS id_purchase_order_detail_jumlah,
  nextval('public.purchase_transaksi_detail_id_seq'::regclass)::integer AS id_purchase_transaksi_detail,
  nextval('public.purchas_transaksi_detail_jumlah_id_seq'::regclass)::integer AS id_purchase_transaksi_detail_jumlah,
  mh.id_purchase_order,
  mh.id_purchase_transaksi,
  d.*,
  p.nama AS nama_produk,
  coalesce(p.ppn, 11) AS ppn,
  u.id AS uom_id,
  u.kode AS uom_kode,
  u.nama AS uom_nama,
  u.level AS uom_level,
  coalesce(u.faktor_konversi::numeric, d.qty_per_uom, 1) AS uom_faktor_konversi
FROM tmp_legacy_purchase_details d
JOIN legacy_dist_2026.__map_purchase_header mh ON mh.source_nota = d.source_nota
JOIN public.produk p ON p.id = d.id_produk
LEFT JOIN LATERAL (
  SELECT pu.*
  FROM public.produk_uom pu
  WHERE pu.id_produk = d.id_produk
  ORDER BY
    CASE
      WHEN d.qty_per_uom IS NOT NULL
       AND round(coalesce(pu.faktor_konversi, 0)::numeric, 4) = round(d.qty_per_uom, 4)
        THEN 0
      ELSE 1
    END,
    CASE
      WHEN d.qty_per_uom IS NOT NULL
        THEN abs(coalesce(pu.faktor_konversi, 0)::numeric - d.qty_per_uom)
      ELSE 999999
    END,
    pu.level,
    pu.id
  LIMIT 1
) u ON true
WHERE d.id_produk IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM legacy_dist_2026.__map_purchase_detail md
    WHERE md.source_nota = d.source_nota
      AND md.source_line_key = d.source_line_key
  );

INSERT INTO public.purchase_order_detail (
  id, produk_id, produk_kode, produk_nama, produk_harga_beli, order_id,
  ppn, total_order, total_terpenuhi, total_tersisa, subtotal
)
SELECT
  id_purchase_order_detail,
  id_produk,
  kode_produk_raw,
  left(coalesce(nama_produk, nama_produk_source), 100),
  harga_beli::double precision,
  id_purchase_order,
  ppn::real,
  coalesce(qty_base, qty_uom * qty_per_uom, qty_uom, 0)::double precision,
  coalesce(qty_base, qty_uom * qty_per_uom, qty_uom, 0)::double precision,
  0,
  coalesce(subtotal, 0)::double precision
FROM tmp_purchase_details_to_insert;

INSERT INTO public.purchase_order_detail_jumlah (
  id, uom_id, uom_kode, uom_nama, uom_level, uom_faktor_konversi,
  uom_harga_beli, uom_harga_beli_ppn, jumlah, subtotal,
  order_id, order_detail_id, jumlah_per_uom
)
SELECT
  id_purchase_order_detail_jumlah,
  uom_id,
  left(coalesce(uom_kode, 'UNIT'), 100),
  left(coalesce(uom_nama, 'UNIT'), 100),
  coalesce(uom_level, 1)::smallint,
  coalesce(uom_faktor_konversi, qty_per_uom, 1)::real,
  (coalesce(harga_beli, 0) * coalesce(qty_per_uom, uom_faktor_konversi, 1))::double precision,
  CASE
    WHEN coalesce(qty_uom, 0) <> 0 THEN (coalesce(subtotal, 0) / qty_uom)::double precision
    ELSE (coalesce(harga_beli, 0) * coalesce(qty_per_uom, uom_faktor_konversi, 1))::double precision
  END,
  round(coalesce(qty_uom, 0))::integer,
  coalesce(subtotal, 0)::double precision,
  id_purchase_order,
  id_purchase_order_detail,
  round(coalesce(qty_per_uom, uom_faktor_konversi, 1))::integer
FROM tmp_purchase_details_to_insert;

INSERT INTO public.purchase_transaksi_detail (
  id, transaksi_id, tanggal_expired, subtotal, batch_number, order_detail_id
)
SELECT
  id_purchase_transaksi_detail,
  id_purchase_transaksi,
  NULL::date,
  coalesce(subtotal, 0)::double precision,
  NULL::text,
  id_purchase_order_detail
FROM tmp_purchase_details_to_insert;

INSERT INTO public.purchase_transaksi_detail_jumlah (
  id, transaksi_id, jumlah, subtotal, order_detail_jumlah_id, transaksi_detail_id
)
SELECT
  id_purchase_transaksi_detail_jumlah,
  id_purchase_transaksi,
  round(coalesce(qty_uom, 0))::integer,
  coalesce(subtotal, 0)::double precision,
  id_purchase_order_detail_jumlah,
  id_purchase_transaksi_detail
FROM tmp_purchase_details_to_insert;

INSERT INTO legacy_dist_2026.__map_purchase_detail (
  source_nota, source_line_key,
  id_purchase_order_detail, id_purchase_order_detail_jumlah,
  id_purchase_transaksi_detail, id_purchase_transaksi_detail_jumlah
)
SELECT
  source_nota,
  source_line_key,
  id_purchase_order_detail,
  id_purchase_order_detail_jumlah,
  id_purchase_transaksi_detail,
  id_purchase_transaksi_detail_jumlah
FROM tmp_purchase_details_to_insert;

CREATE TEMP TABLE tmp_purchase_tagihan_groups AS
SELECT
  lower(h.kode_principal_raw) || '|' || lower(h.invoice_no) AS source_tagihan_key,
  h.invoice_no AS no_tagihan,
  min(h.tanggal) AS tanggal,
  sum(h.total) AS total,
  min(mh.id_purchase_transaksi) AS sample_transaksi_id,
  count(*) AS transaksi_count
FROM tmp_legacy_purchase_headers_ready h
JOIN legacy_dist_2026.__map_purchase_header mh ON mh.source_nota = h.source_nota
GROUP BY lower(h.kode_principal_raw) || '|' || lower(h.invoice_no), h.invoice_no;

CREATE UNIQUE INDEX tmp_purchase_tagihan_groups_key_uq
  ON tmp_purchase_tagihan_groups (source_tagihan_key);

CREATE TEMP TABLE tmp_purchase_tagihan_to_insert AS
SELECT
  nextval('public.purchase_tagihan_id_seq'::regclass)::integer AS id_purchase_tagihan,
  g.*
FROM tmp_purchase_tagihan_groups g
WHERE NOT EXISTS (
  SELECT 1
  FROM legacy_dist_2026.__map_purchase_tagihan mt
  WHERE mt.source_tagihan_key = g.source_tagihan_key
);

INSERT INTO public.purchase_tagihan (
  id, transaksi_id, jatuh_tempo, total, nominal_pembayaran, status_pembayaran,
  tipe_setoran, keterangan, tanggal_bayar, no_tagihan, bukti_bayar, pic_pembayaran
)
SELECT
  id_purchase_tagihan,
  NULL,
  NULL,
  total::double precision,
  0,
  1,
  NULL,
  left('Legacy DIST HPembelian | ' || transaksi_count || ' nota', 100),
  NULL,
  no_tagihan,
  NULL,
  NULL
FROM tmp_purchase_tagihan_to_insert;

INSERT INTO legacy_dist_2026.__map_purchase_tagihan (
  source_tagihan_key, no_tagihan, id_purchase_tagihan
)
SELECT
  source_tagihan_key,
  no_tagihan,
  id_purchase_tagihan
FROM tmp_purchase_tagihan_to_insert;

UPDATE legacy_dist_2026.__map_purchase_header mh
SET id_purchase_tagihan = mt.id_purchase_tagihan
FROM tmp_legacy_purchase_headers_ready h
JOIN tmp_purchase_tagihan_groups g
  ON g.source_tagihan_key = lower(h.kode_principal_raw) || '|' || lower(h.invoice_no)
JOIN legacy_dist_2026.__map_purchase_tagihan mt
  ON mt.source_tagihan_key = g.source_tagihan_key
WHERE mh.source_nota = h.source_nota
  AND mh.id_purchase_tagihan IS DISTINCT FROM mt.id_purchase_tagihan;

INSERT INTO public.purchase_tagihan_detail (
  tagihan_id, transaksi_id, subtotal
)
SELECT
  mh.id_purchase_tagihan,
  mh.id_purchase_transaksi,
  h.total::double precision
FROM tmp_legacy_purchase_headers_ready h
JOIN legacy_dist_2026.__map_purchase_header mh ON mh.source_nota = h.source_nota
WHERE mh.id_purchase_tagihan IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM public.purchase_tagihan_detail ptd
    WHERE ptd.tagihan_id = mh.id_purchase_tagihan
      AND ptd.transaksi_id = mh.id_purchase_transaksi
  );

SELECT setval('public.purchase_request_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.purchase_order), 0), 1), true);
SELECT setval('public.purchase_request_detail_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.purchase_order_detail), 0), 1), true);
SELECT setval('public.purchase_order_detail_jumlah_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.purchase_order_detail_jumlah), 0), 1), true);
SELECT setval('public.purchase_transaksi_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.purchase_transaksi), 0), 1), true);
SELECT setval('public.purchase_transaksi_detail_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.purchase_transaksi_detail), 0), 1), true);
SELECT setval('public.purchas_transaksi_detail_jumlah_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.purchase_transaksi_detail_jumlah), 0), 1), true);
SELECT setval('public.purchase_tagihan_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.purchase_tagihan), 0), 1), true);
SELECT setval('public.purchase_tagihan_pelunasan_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.purchase_tagihan_detail), 0), 1), true);

SELECT
  'legacy_purchase_summary' AS metric,
  (SELECT count(*) FROM tmp_legacy_purchase_headers WHERE source_status = 'P') AS hpembelian_p_headers,
  (SELECT count(*) FROM tmp_legacy_purchase_headers WHERE source_status <> 'P') AS hpembelian_skipped_headers,
  (SELECT count(*) FROM legacy_dist_2026.__map_purchase_header) AS mapped_headers,
  (SELECT count(*) FROM legacy_dist_2026.__map_purchase_detail) AS mapped_detail_rows,
  (SELECT count(*) FROM legacy_dist_2026.__map_purchase_tagihan) AS mapped_tagihan,
  (SELECT count(*) FROM legacy_dist_2026.__purchase_mapping_issues WHERE run_id = 'legacy_purchase_2026_to_public' AND issue_type <> 'purchase_header_skipped_status') AS blocking_issues;

COMMIT;


-- ============================================================================
-- 06 Retur sales 2026 ke retur request/CN
-- Source: tools\migration\map_legacy_retur_2026_to_public.sql
-- ============================================================================
SELECT '06 Retur sales 2026 ke retur request/CN' AS migration_step;


BEGIN;

LOCK TABLE
  public.plafon,
  public.sales_order,
  public.retur_request,
  public.retur_request_detail,
  public.credit_note,
  public.credit_note_detail
IN SHARE ROW EXCLUSIVE MODE;

CREATE INDEX IF NOT EXISTS sales_order_detail_sales_order_produk_idx
  ON public.sales_order_detail (id_sales_order, id_produk);

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

SELECT setval('public.plafon_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.plafon), 0), 1), true);
SELECT setval('public.sales_order_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.sales_order), 0), 1), true);
SELECT setval(pg_get_serial_sequence('public.retur_request', 'id_request')::regclass, GREATEST(coalesce((SELECT max(id_request) FROM public.retur_request), 0), 1), true);
SELECT setval(pg_get_serial_sequence('public.retur_request_detail', 'id_request_detail')::regclass, GREATEST(coalesce((SELECT max(id_request_detail) FROM public.retur_request_detail), 0), 1), true);
SELECT setval(pg_get_serial_sequence('public.credit_note', 'id_cn')::regclass, GREATEST(coalesce((SELECT max(id_cn) FROM public.credit_note), 0), 1), true);
SELECT setval(pg_get_serial_sequence('public.credit_note_detail', 'id_cn_detail')::regclass, GREATEST(coalesce((SELECT max(id_cn_detail) FROM public.credit_note_detail), 0), 1), true);

CREATE TABLE IF NOT EXISTS legacy_dist_2026.__map_retur_request (
  source_table text NOT NULL,
  source_nota text NOT NULL,
  source_status text NOT NULL,
  id_retur_request integer NOT NULL,
  id_sales_order integer NOT NULL,
  id_credit_note integer,
  mapped_at timestamp without time zone NOT NULL DEFAULT now(),
  PRIMARY KEY (source_table, source_nota)
);

CREATE TABLE IF NOT EXISTS legacy_dist_2026.__map_retur_request_detail (
  source_table text NOT NULL,
  source_nota text NOT NULL,
  source_line_key text NOT NULL,
  id_retur_request integer NOT NULL,
  id_retur_request_detail integer NOT NULL,
  id_credit_note_detail integer,
  mapped_at timestamp without time zone NOT NULL DEFAULT now(),
  PRIMARY KEY (source_table, source_nota, source_line_key)
);

CREATE TABLE IF NOT EXISTS legacy_dist_2026.__map_retur_placeholder_sales_order (
  source_table text NOT NULL,
  source_nota text NOT NULL,
  id_sales_order integer NOT NULL,
  mapped_at timestamp without time zone NOT NULL DEFAULT now(),
  PRIMARY KEY (source_table, source_nota)
);

CREATE TABLE IF NOT EXISTS legacy_dist_2026.__retur_mapping_issues (
  id bigserial PRIMARY KEY,
  run_id text NOT NULL,
  source_table text,
  source_key text,
  issue_type text NOT NULL,
  issue_detail jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamp without time zone NOT NULL DEFAULT now()
);

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

CREATE TEMP TABLE tmp_sales_code_principal_map AS
SELECT DISTINCT ON (lower(btrim(sd.kode_sales)), s.id_principal)
  lower(btrim(sd.kode_sales)) AS code,
  s.id_principal,
  s.id AS id_sales,
  s.id_user
FROM public.sales s
JOIN public.sales_detail sd ON sd.id_sales = s.id
WHERE nullif(btrim(sd.kode_sales), '') IS NOT NULL
ORDER BY lower(btrim(sd.kode_sales)), s.id_principal, s.id;

CREATE INDEX tmp_sales_code_principal_map_idx
  ON tmp_sales_code_principal_map (code, id_principal);

CREATE TEMP TABLE tmp_sales_code_any_map AS
SELECT DISTINCT ON (lower(btrim(sd.kode_sales)))
  lower(btrim(sd.kode_sales)) AS code,
  s.id AS id_sales,
  s.id_user
FROM public.sales s
JOIN public.sales_detail sd ON sd.id_sales = s.id
WHERE nullif(btrim(sd.kode_sales), '') IS NOT NULL
ORDER BY lower(btrim(sd.kode_sales)), s.id;

CREATE UNIQUE INDEX tmp_sales_code_any_map_code_uq
  ON tmp_sales_code_any_map (code);

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

CREATE TEMP TABLE tmp_sales_ref_map AS
WITH refs AS (
  SELECT lower(btrim(source_nota)) AS ref, id_sales_order, id_faktur
  FROM legacy_dist_2026.__map_sales_order
  UNION ALL
  SELECT lower(btrim(no_order)), id_sales_order, id_faktur
  FROM legacy_dist_2026.__map_sales_order
  UNION ALL
  SELECT lower(btrim(no_faktur)), id_sales_order, id_faktur
  FROM legacy_dist_2026.__map_sales_order
  UNION ALL
  SELECT lower(btrim(so.no_order)), so.id, f.id
  FROM public.sales_order so
  LEFT JOIN public.faktur f ON f.id_sales_order = so.id
  UNION ALL
  SELECT lower(btrim(so.no_faktur)), so.id, f.id
  FROM public.sales_order so
  LEFT JOIN public.faktur f ON f.id_sales_order = so.id
  UNION ALL
  SELECT lower(btrim(f.no_faktur)), so.id, f.id
  FROM public.faktur f
  JOIN public.sales_order so ON so.id = f.id_sales_order
)
SELECT DISTINCT ON (ref)
  ref,
  id_sales_order,
  id_faktur
FROM refs
WHERE nullif(ref, '') IS NOT NULL
ORDER BY ref, id_faktur NULLS LAST, id_sales_order;

CREATE UNIQUE INDEX tmp_sales_ref_map_ref_uq ON tmp_sales_ref_map (ref);

CREATE TEMP TABLE tmp_legacy_retur_headers_raw AS
WITH official_headers AS (
  SELECT DISTINCT ON (btrim(nota))
    'hretursm'::text AS source_table,
    btrim(nota) AS source_nota,
    lower(btrim(kodecustomer)) AS kode_customer,
    lower(btrim(kodesales)) AS kode_sales,
    lower(btrim(kodeprinciple)) AS kode_principal,
    upper(coalesce(nullif(btrim(stnota), ''), '<BLANK>')) AS source_status,
    pg_temp.legacy_date(tanggal) AS tanggal_request,
    pg_temp.legacy_date(tanggaldn) AS tanggal_retur,
    lower(nullif(btrim(notasm), '')) AS ref_notasm,
    lower(nullif(btrim(nodn), '')) AS ref_nodn,
    nullif(btrim(keterangan), '') AS keterangan_source,
    pg_temp.legacy_num(totalretur) AS total_retur_source,
    3::integer AS target_status_request,
    CASE
      WHEN upper(coalesce(nullif(btrim(stnota), ''), '<BLANK>')) = 'LN' THEN 1
      ELSE 0
    END AS target_status_cn,
    ('KPR-LEGACY-' || btrim(nota))::text AS kode_kpr,
    ('CN-LEGACY-' || btrim(nota))::text AS no_cn
  FROM legacy_dist_2026.hretursm
  WHERE upper(coalesce(nullif(btrim(stnota), ''), '<BLANK>')) IN ('LN', 'RL')
    AND nullif(btrim(nota), '') IS NOT NULL
  ORDER BY btrim(nota), ctid
),
android_headers AS (
  SELECT DISTINCT ON (btrim(nota))
    'hretursmandroid'::text AS source_table,
    btrim(nota) AS source_nota,
    lower(btrim(kodecustomer)) AS kode_customer,
    lower(btrim(kodesales)) AS kode_sales,
    lower(btrim(kodeprinciple)) AS kode_principal,
    upper(coalesce(nullif(btrim(stnota), ''), '<BLANK>')) AS source_status,
    pg_temp.legacy_date(tanggal) AS tanggal_request,
    pg_temp.legacy_date(tanggaldn) AS tanggal_retur,
    lower(nullif(btrim(notasm), '')) AS ref_notasm,
    lower(nullif(btrim(nodn), '')) AS ref_nodn,
    nullif(btrim(keterangan), '') AS keterangan_source,
    pg_temp.legacy_num(totalretur) AS total_retur_source,
    CASE
      WHEN upper(coalesce(nullif(btrim(stnota), ''), '<BLANK>')) = 'PD' THEN 0
      WHEN upper(coalesce(nullif(btrim(stnota), ''), '<BLANK>')) = 'OP' THEN 1
      WHEN upper(coalesce(nullif(btrim(stnota), ''), '<BLANK>')) = 'RL' THEN 3
      ELSE 0
    END AS target_status_request,
    CASE
      WHEN upper(coalesce(nullif(btrim(stnota), ''), '<BLANK>')) = 'RL' THEN 0
      ELSE NULL
    END AS target_status_cn,
    CASE
      WHEN upper(coalesce(nullif(btrim(stnota), ''), '<BLANK>')) IN ('OP', 'RL') THEN ('KPR-LEGACY-' || btrim(nota))
      ELSE NULL
    END AS kode_kpr,
    CASE
      WHEN upper(coalesce(nullif(btrim(stnota), ''), '<BLANK>')) = 'RL' THEN ('CN-LEGACY-' || btrim(nota))
      ELSE NULL
    END AS no_cn
  FROM legacy_dist_2026.hretursmandroid
  WHERE (
      upper(coalesce(nullif(btrim(stnota), ''), '<BLANK>')) IN ('PD', 'OP')
      OR (
        upper(coalesce(nullif(btrim(stnota), ''), '<BLANK>')) = 'RL'
        AND nullif(btrim(noretur), '') IS NULL
      )
    )
    AND nullif(btrim(nota), '') IS NOT NULL
  ORDER BY btrim(nota), ctid
)
SELECT * FROM official_headers
UNION ALL
SELECT * FROM android_headers;

CREATE UNIQUE INDEX tmp_legacy_retur_headers_raw_uq
  ON tmp_legacy_retur_headers_raw (source_table, source_nota);

CREATE TEMP TABLE tmp_legacy_retur_headers AS
SELECT
  h.*,
  cm.id_customer,
  pm.id_principal,
  coalesce(smp.id_sales, sma.id_sales) AS id_sales,
  coalesce(smp.id_user, sma.id_user) AS id_user,
  coalesce(sr1.id_sales_order, sr2.id_sales_order) AS matched_sales_order_id,
  coalesce(sr1.id_faktur, sr2.id_faktur) AS matched_faktur_id
FROM tmp_legacy_retur_headers_raw h
LEFT JOIN tmp_customer_map cm ON cm.code = h.kode_customer
LEFT JOIN tmp_principal_map pm ON pm.code = h.kode_principal
LEFT JOIN tmp_sales_code_principal_map smp
  ON smp.code = h.kode_sales
 AND smp.id_principal = pm.id_principal
LEFT JOIN tmp_sales_code_any_map sma ON sma.code = h.kode_sales
LEFT JOIN tmp_sales_ref_map sr1 ON sr1.ref = h.ref_notasm
LEFT JOIN tmp_sales_ref_map sr2 ON sr2.ref = h.ref_nodn;

CREATE UNIQUE INDEX tmp_legacy_retur_headers_uq
  ON tmp_legacy_retur_headers (source_table, source_nota);

CREATE TEMP TABLE tmp_legacy_retur_details_raw AS
WITH official_details AS (
  SELECT DISTINCT ON (
    btrim(nota), btrim(urut), btrim(kodestok), btrim(masterkode), btrim(namastok),
    btrim(unit), btrim(satuan), btrim(jumlah), btrim(harga), btrim(jumlahharga)
  )
    'hretursm'::text AS source_table,
    btrim(nota) AS source_nota,
    btrim(kodestok) AS kode_stok,
    nullif(btrim(masterkode), '') AS master_kode,
    lower(nullif(btrim(kodeprinciple), '')) AS kode_principal,
    nullif(btrim(namastok), '') AS nama_stok,
    pg_temp.legacy_num(unit) AS qty_unit,
    pg_temp.legacy_num(satuan) AS qty_piece,
    pg_temp.legacy_num(jumlah) AS qty_total,
    pg_temp.legacy_num(harga) AS harga,
    pg_temp.legacy_num(discrp) AS discrp,
    pg_temp.legacy_num(jumlahexppn) AS jumlah_ex_ppn,
    pg_temp.legacy_num(jumlahharga) AS jumlah_harga,
    pg_temp.legacy_num(urut) AS urut
  FROM legacy_dist_2026.dretursm
  WHERE nullif(btrim(nota), '') IS NOT NULL
  ORDER BY btrim(nota), btrim(urut), btrim(kodestok), btrim(masterkode), btrim(namastok),
           btrim(unit), btrim(satuan), btrim(jumlah), btrim(harga), btrim(jumlahharga), ctid
),
android_details AS (
  SELECT DISTINCT ON (
    btrim(nota), btrim(urut), btrim(kodestok), btrim(masterkode), btrim(namastok),
    btrim(unit), btrim(satuan), btrim(jumlah), btrim(harga), btrim(jumlahharga)
  )
    'hretursmandroid'::text AS source_table,
    btrim(nota) AS source_nota,
    btrim(kodestok) AS kode_stok,
    nullif(btrim(masterkode), '') AS master_kode,
    lower(nullif(btrim(kodeprinciple), '')) AS kode_principal,
    nullif(btrim(namastok), '') AS nama_stok,
    pg_temp.legacy_num(unit) AS qty_unit,
    pg_temp.legacy_num(satuan) AS qty_piece,
    pg_temp.legacy_num(jumlah) AS qty_total,
    pg_temp.legacy_num(harga) AS harga,
    pg_temp.legacy_num(discrp) AS discrp,
    pg_temp.legacy_num(jumlahexppn) AS jumlah_ex_ppn,
    pg_temp.legacy_num(jumlahharga) AS jumlah_harga,
    pg_temp.legacy_num(urut) AS urut
  FROM legacy_dist_2026.dretursmandroid
  WHERE nullif(btrim(nota), '') IS NOT NULL
  ORDER BY btrim(nota), btrim(urut), btrim(kodestok), btrim(masterkode), btrim(namastok),
           btrim(unit), btrim(satuan), btrim(jumlah), btrim(harga), btrim(jumlahharga), ctid
),
raw_details AS (
  SELECT * FROM official_details
  UNION ALL
  SELECT * FROM android_details
)
SELECT
  *,
  lpad(row_number() OVER (
    PARTITION BY source_table, source_nota
    ORDER BY urut NULLS LAST, kode_stok, coalesce(master_kode, ''), coalesce(nama_stok, ''),
             coalesce(qty_unit, 0), coalesce(qty_piece, 0), coalesce(qty_total, 0),
             coalesce(harga, 0), coalesce(jumlah_harga, 0)
  )::text, 8, '0') AS source_line_key
FROM raw_details;

CREATE UNIQUE INDEX tmp_legacy_retur_details_raw_uq
  ON tmp_legacy_retur_details_raw (source_table, source_nota, source_line_key);

CREATE TEMP TABLE tmp_legacy_retur_details AS
SELECT
  d.*,
  h.id_principal AS header_id_principal,
  coalesce(psp.id_produk, pmp.id_produk, psa.id_produk, pma.id_produk) AS id_produk
FROM tmp_legacy_retur_details_raw d
JOIN tmp_legacy_retur_headers h
  ON h.source_table = d.source_table
 AND h.source_nota = d.source_nota
LEFT JOIN tmp_product_sku_principal_map psp
  ON psp.code = lower(d.kode_stok)
 AND psp.id_principal = h.id_principal
LEFT JOIN tmp_product_sku_principal_map pmp
  ON pmp.code = lower(coalesce(d.master_kode, ''))
 AND pmp.id_principal = h.id_principal
LEFT JOIN tmp_product_sku_any_map psa ON psa.code = lower(d.kode_stok)
LEFT JOIN tmp_product_sku_any_map pma ON pma.code = lower(coalesce(d.master_kode, ''));

CREATE UNIQUE INDEX tmp_legacy_retur_details_uq
  ON tmp_legacy_retur_details (source_table, source_nota, source_line_key);

CREATE TEMP TABLE tmp_legacy_retur_detail_agg AS
SELECT
  source_table,
  source_nota,
  count(*) AS detail_rows,
  sum(coalesce(jumlah_harga, 0)) AS total_retur_detail,
  sum(coalesce(jumlah_ex_ppn, jumlah_harga, 0)) AS subtotal_retur_detail,
  sum(greatest(coalesce(jumlah_harga, 0) - coalesce(jumlah_ex_ppn, jumlah_harga, 0), 0)) AS ppn_retur_detail
FROM tmp_legacy_retur_details
GROUP BY source_table, source_nota;

CREATE UNIQUE INDEX tmp_legacy_retur_detail_agg_uq
  ON tmp_legacy_retur_detail_agg (source_table, source_nota);

INSERT INTO legacy_dist_2026.__retur_mapping_issues (
  run_id, source_table, source_key, issue_type, issue_detail
)
SELECT
  'legacy_retur_2026_to_public',
  source_table,
  source_nota,
  'missing_master',
  jsonb_build_object(
    'missing_customer', id_customer IS NULL,
    'missing_principal', id_principal IS NULL,
    'missing_sales', id_sales IS NULL,
    'kode_customer', kode_customer,
    'kode_principal', kode_principal,
    'kode_sales', kode_sales
  )
FROM tmp_legacy_retur_headers h
WHERE (id_customer IS NULL OR id_principal IS NULL OR id_sales IS NULL)
  AND NOT EXISTS (
    SELECT 1 FROM legacy_dist_2026.__retur_mapping_issues i
    WHERE i.run_id = 'legacy_retur_2026_to_public'
      AND i.source_table = h.source_table
      AND i.source_key = h.source_nota
      AND i.issue_type = 'missing_master'
  );

INSERT INTO legacy_dist_2026.__retur_mapping_issues (
  run_id, source_table, source_key, issue_type, issue_detail
)
SELECT
  'legacy_retur_2026_to_public',
  source_table,
  source_nota || ':' || source_line_key,
  'missing_product',
  jsonb_build_object('kode_stok', kode_stok, 'master_kode', master_kode, 'nama_stok', nama_stok)
FROM tmp_legacy_retur_details d
WHERE id_produk IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM legacy_dist_2026.__retur_mapping_issues i
    WHERE i.run_id = 'legacy_retur_2026_to_public'
      AND i.source_table = d.source_table
      AND i.source_key = d.source_nota || ':' || d.source_line_key
      AND i.issue_type = 'missing_product'
  );

INSERT INTO legacy_dist_2026.__retur_mapping_issues (
  run_id, source_table, source_key, issue_type, issue_detail
)
SELECT
  'legacy_retur_2026_to_public',
  h.source_table,
  h.source_nota,
  'missing_detail',
  jsonb_build_object('source_status', h.source_status)
FROM tmp_legacy_retur_headers h
LEFT JOIN tmp_legacy_retur_detail_agg a
  ON a.source_table = h.source_table
 AND a.source_nota = h.source_nota
WHERE coalesce(a.detail_rows, 0) = 0
  AND NOT EXISTS (
    SELECT 1 FROM legacy_dist_2026.__retur_mapping_issues i
    WHERE i.run_id = 'legacy_retur_2026_to_public'
      AND i.source_table = h.source_table
      AND i.source_key = h.source_nota
      AND i.issue_type = 'missing_detail'
  );

CREATE TEMP TABLE tmp_legacy_retur_headers_valid AS
SELECT h.*
FROM tmp_legacy_retur_headers h
JOIN tmp_legacy_retur_detail_agg a
  ON a.source_table = h.source_table
 AND a.source_nota = h.source_nota
WHERE h.id_customer IS NOT NULL
  AND h.id_principal IS NOT NULL
  AND h.id_sales IS NOT NULL
  AND a.detail_rows > 0;

CREATE TEMP TABLE tmp_legacy_retur_missing_plafon AS
SELECT DISTINCT
  h.id_customer,
  h.id_principal,
  h.id_sales,
  h.id_user
FROM tmp_legacy_retur_headers_valid h
LEFT JOIN public.plafon pl
  ON pl.id_customer = h.id_customer
 AND pl.id_principal = h.id_principal
 AND pl.id_sales = h.id_sales
WHERE pl.id IS NULL;

INSERT INTO public.plafon (
  id_customer, id_principal, id_sales, id_user, limit_bon, sisa_bon,
  kode, id_tipe_harga, top, lock_order, tempo, tempo_label
)
SELECT
  id_customer,
  id_principal,
  id_sales,
  id_user,
  0,
  0,
  concat('LEGACY-RETUR-', id_customer, '-', id_principal, '-', id_sales),
  2,
  0,
  '1',
  0,
  NULL
FROM tmp_legacy_retur_missing_plafon mp
WHERE NOT EXISTS (
  SELECT 1
  FROM public.plafon pl
  WHERE pl.id_customer = mp.id_customer
    AND pl.id_principal = mp.id_principal
    AND pl.id_sales = mp.id_sales
);

CREATE TEMP TABLE tmp_legacy_retur_headers_ready AS
SELECT
  h.*,
  so.id_plafon AS matched_sales_order_plafon_id,
  pl.id AS target_plafon_id,
  coalesce(a.total_retur_detail, h.total_retur_source, 0) AS total_retur,
  coalesce(a.subtotal_retur_detail, h.total_retur_source, 0) AS subtotal_retur,
  coalesce(a.ppn_retur_detail, 0) AS ppn_retur
FROM tmp_legacy_retur_headers_valid h
LEFT JOIN public.sales_order so ON so.id = h.matched_sales_order_id
JOIN public.plafon pl
  ON pl.id_customer = h.id_customer
 AND pl.id_principal = h.id_principal
 AND pl.id_sales = h.id_sales
JOIN tmp_legacy_retur_detail_agg a
  ON a.source_table = h.source_table
 AND a.source_nota = h.source_nota;

CREATE UNIQUE INDEX tmp_legacy_retur_headers_ready_uq
  ON tmp_legacy_retur_headers_ready (source_table, source_nota);

UPDATE public.sales_order so
SET id_plafon = h.target_plafon_id
FROM tmp_legacy_retur_headers_ready h
WHERE so.id = h.matched_sales_order_id
  AND so.id_plafon IS NULL;

CREATE TEMP TABLE tmp_retur_placeholder_so_to_insert AS
SELECT
  nextval('public.sales_order_id_seq'::regclass)::integer AS id_sales_order,
  h.*
FROM tmp_legacy_retur_headers_ready h
WHERE h.matched_sales_order_id IS NULL
  AND NOT EXISTS (
    SELECT 1
    FROM legacy_dist_2026.__map_retur_placeholder_sales_order m
    WHERE m.source_table = h.source_table
      AND m.source_nota = h.source_nota
  );

INSERT INTO public.sales_order (
  id, id_plafon, tanggal_order, tanggal_faktur, tanggal_terkirim,
  tanggal_jatuh_tempo, nama_sales, pic_customer, total_kubikasi,
  status_order, total_order, no_order, no_faktur, no_tagihan,
  keterangan, id_cabang, id_order_batch, id_sales_tipe
)
SELECT
  id_sales_order,
  target_plafon_id,
  tanggal_request,
  NULL,
  CASE WHEN target_status_request = 3 THEN coalesce(tanggal_retur, tanggal_request) ELSE NULL END,
  NULL,
  NULL,
  NULL,
  0,
  8,
  0,
  'RETUR-' || source_nota,
  upper(coalesce(ref_notasm, ref_nodn, source_nota)),
  NULL,
  left('Legacy DIST retur placeholder | ' || source_table || ' | stnota=' || source_status, 255),
  5,
  NULL,
  NULL
FROM tmp_retur_placeholder_so_to_insert;

INSERT INTO legacy_dist_2026.__map_retur_placeholder_sales_order (
  source_table, source_nota, id_sales_order
)
SELECT source_table, source_nota, id_sales_order
FROM tmp_retur_placeholder_so_to_insert;

CREATE TEMP TABLE tmp_legacy_retur_headers_mapped AS
SELECT
  h.*,
  coalesce(h.matched_sales_order_id, mp.id_sales_order) AS id_sales_order_final,
  h.matched_faktur_id AS id_faktur_final
FROM tmp_legacy_retur_headers_ready h
LEFT JOIN legacy_dist_2026.__map_retur_placeholder_sales_order mp
  ON mp.source_table = h.source_table
 AND mp.source_nota = h.source_nota;

CREATE UNIQUE INDEX tmp_legacy_retur_headers_mapped_uq
  ON tmp_legacy_retur_headers_mapped (source_table, source_nota);

CREATE TEMP TABLE tmp_retur_request_to_insert AS
SELECT
  nextval(pg_get_serial_sequence('public.retur_request', 'id_request')::regclass)::integer AS id_retur_request,
  h.*
FROM tmp_legacy_retur_headers_mapped h
WHERE h.id_sales_order_final IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM legacy_dist_2026.__map_retur_request m
    WHERE m.source_table = h.source_table
      AND m.source_nota = h.source_nota
  );

INSERT INTO public.retur_request (
  id_request, id_sales_order, kode_request, id_sales, id_customer,
  id_principal, tanggal_request, status_request, subtotal_retur,
  total_dpp_retur, total_diskon_retur, total_ppn_retur, total_retur,
  tanggal_retur, kode_kpr, no_cn
)
SELECT
  id_retur_request,
  id_sales_order_final,
  source_nota,
  id_user,
  id_customer,
  id_principal,
  tanggal_request,
  target_status_request::text,
  subtotal_retur::double precision,
  subtotal_retur::double precision,
  0,
  ppn_retur::double precision,
  total_retur::double precision,
  CASE WHEN target_status_request = 3 THEN coalesce(tanggal_retur, tanggal_request) ELSE NULL END,
  kode_kpr,
  no_cn
FROM tmp_retur_request_to_insert;

INSERT INTO legacy_dist_2026.__map_retur_request (
  source_table, source_nota, source_status, id_retur_request, id_sales_order
)
SELECT
  source_table,
  source_nota,
  source_status,
  id_retur_request,
  id_sales_order_final
FROM tmp_retur_request_to_insert;

CREATE TEMP TABLE tmp_retur_details_to_insert AS
SELECT
  nextval(pg_get_serial_sequence('public.retur_request_detail', 'id_request_detail')::regclass)::integer AS id_retur_request_detail,
  mr.id_retur_request,
  hm.id_sales_order_final,
  hm.keterangan_source,
  d.*,
  sod.id AS id_sales_order_detail
FROM tmp_legacy_retur_details d
JOIN tmp_legacy_retur_headers_mapped hm
  ON hm.source_table = d.source_table
 AND hm.source_nota = d.source_nota
JOIN legacy_dist_2026.__map_retur_request mr
  ON mr.source_table = d.source_table
 AND mr.source_nota = d.source_nota
LEFT JOIN LATERAL (
  SELECT sod_inner.id
  FROM public.sales_order_detail sod_inner
  WHERE sod_inner.id_sales_order = hm.id_sales_order_final
    AND sod_inner.id_produk = d.id_produk
  ORDER BY sod_inner.id
  LIMIT 1
) sod ON true
WHERE d.id_produk IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM legacy_dist_2026.__map_retur_request_detail md
    WHERE md.source_table = d.source_table
      AND md.source_nota = d.source_nota
      AND md.source_line_key = d.source_line_key
  );

INSERT INTO public.retur_request_detail (
  id_request_detail, id_request, id_sales_order_detail, id_produk,
  pieces_diajukan, box_diajukan, karton_diajukan, alasan_retur,
  harga_satuan, subtotal_retur, diskon_retur, dpp_retur, ppn_retur,
  total_retur, pieces_retur, box_retur, karton_retur,
  pieces_good_diajukan, box_good_diajukan, karton_good_diajukan
)
SELECT
  id_retur_request_detail,
  id_retur_request,
  id_sales_order_detail,
  id_produk,
  CASE
    WHEN coalesce(qty_piece, 0) <> 0 THEN round(qty_piece)::integer
    WHEN coalesce(qty_unit, 0) = 0 THEN round(coalesce(qty_total, 0))::integer
    ELSE 0
  END,
  0,
  round(coalesce(qty_unit, 0))::integer,
  coalesce(keterangan_source, nama_stok, 'Legacy DIST retur')::text,
  coalesce(harga, 0)::double precision,
  coalesce(jumlah_ex_ppn, jumlah_harga, 0)::double precision,
  coalesce(discrp, 0)::double precision,
  coalesce(jumlah_ex_ppn, jumlah_harga, 0)::double precision,
  greatest(coalesce(jumlah_harga, 0) - coalesce(jumlah_ex_ppn, jumlah_harga, 0), 0)::double precision,
  coalesce(jumlah_harga, 0)::double precision,
  CASE
    WHEN coalesce(qty_piece, 0) <> 0 THEN round(qty_piece)::integer
    WHEN coalesce(qty_unit, 0) = 0 THEN round(coalesce(qty_total, 0))::integer
    ELSE 0
  END,
  0,
  round(coalesce(qty_unit, 0))::integer,
  0,
  0,
  0
FROM tmp_retur_details_to_insert;

INSERT INTO legacy_dist_2026.__map_retur_request_detail (
  source_table, source_nota, source_line_key, id_retur_request, id_retur_request_detail
)
SELECT
  source_table,
  source_nota,
  source_line_key,
  id_retur_request,
  id_retur_request_detail
FROM tmp_retur_details_to_insert;

CREATE TEMP TABLE tmp_credit_note_to_insert AS
SELECT
  nextval(pg_get_serial_sequence('public.credit_note', 'id_cn')::regclass)::integer AS id_credit_note,
  mr.id_retur_request,
  h.*
FROM tmp_legacy_retur_headers_mapped h
JOIN legacy_dist_2026.__map_retur_request mr
  ON mr.source_table = h.source_table
 AND mr.source_nota = h.source_nota
WHERE h.target_status_request = 3
  AND mr.id_credit_note IS NULL;

INSERT INTO public.credit_note (
  id_cn, kode_cn, id_customer, id_principal, tanggal, status_cn,
  id_retur_request, total_cn, id_faktur, tanggal_refund,
  nominal_refund, metode_refund, id_rekening_perusahaan,
  id_mutasi_acc, catatan_refund, user_refund
)
SELECT
  id_credit_note,
  left(no_cn, 50),
  id_customer,
  id_principal,
  coalesce(tanggal_retur, tanggal_request)::timestamp,
  target_status_cn,
  id_retur_request,
  total_retur::double precision,
  id_faktur_final,
  NULL,
  0,
  NULL,
  NULL,
  NULL,
  left('Legacy DIST retur | ' || source_table || ' | stnota=' || source_status, 255),
  NULL
FROM tmp_credit_note_to_insert;

UPDATE legacy_dist_2026.__map_retur_request mr
SET id_credit_note = cn.id_credit_note
FROM tmp_credit_note_to_insert cn
WHERE mr.source_table = cn.source_table
  AND mr.source_nota = cn.source_nota;

CREATE TEMP TABLE tmp_credit_note_detail_to_insert AS
SELECT
  nextval(pg_get_serial_sequence('public.credit_note_detail', 'id_cn_detail')::regclass)::integer AS id_credit_note_detail,
  mr.id_credit_note,
  md.id_retur_request_detail,
  d.source_table,
  d.source_nota,
  d.source_line_key,
  coalesce(d.jumlah_harga, 0) AS jumlah_harga,
  coalesce(d.jumlah_ex_ppn, d.jumlah_harga, 0) AS jumlah_ex_ppn,
  h.tanggal_request,
  h.tanggal_retur
FROM tmp_legacy_retur_details d
JOIN tmp_legacy_retur_headers_mapped h
  ON h.source_table = d.source_table
 AND h.source_nota = d.source_nota
JOIN legacy_dist_2026.__map_retur_request mr
  ON mr.source_table = d.source_table
 AND mr.source_nota = d.source_nota
JOIN legacy_dist_2026.__map_retur_request_detail md
  ON md.source_table = d.source_table
 AND md.source_nota = d.source_nota
 AND md.source_line_key = d.source_line_key
WHERE h.target_status_request = 3
  AND mr.id_credit_note IS NOT NULL
  AND md.id_credit_note_detail IS NULL;

INSERT INTO public.credit_note_detail (
  id_cn_detail, id_cn, id_retur_request_detail, nominal_cn, tanggal, subtotal
)
SELECT
  id_credit_note_detail,
  id_credit_note,
  id_retur_request_detail,
  jumlah_harga::double precision,
  coalesce(tanggal_retur, tanggal_request)::timestamp,
  round(jumlah_ex_ppn)::integer
FROM tmp_credit_note_detail_to_insert;

UPDATE legacy_dist_2026.__map_retur_request_detail md
SET id_credit_note_detail = cnd.id_credit_note_detail
FROM tmp_credit_note_detail_to_insert cnd
WHERE md.source_table = cnd.source_table
  AND md.source_nota = cnd.source_nota
  AND md.source_line_key = cnd.source_line_key;

SELECT setval('public.plafon_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.plafon), 0), 1), true);
SELECT setval('public.sales_order_id_seq'::regclass, GREATEST(coalesce((SELECT max(id) FROM public.sales_order), 0), 1), true);
SELECT setval(pg_get_serial_sequence('public.retur_request', 'id_request')::regclass, GREATEST(coalesce((SELECT max(id_request) FROM public.retur_request), 0), 1), true);
SELECT setval(pg_get_serial_sequence('public.retur_request_detail', 'id_request_detail')::regclass, GREATEST(coalesce((SELECT max(id_request_detail) FROM public.retur_request_detail), 0), 1), true);
SELECT setval(pg_get_serial_sequence('public.credit_note', 'id_cn')::regclass, GREATEST(coalesce((SELECT max(id_cn) FROM public.credit_note), 0), 1), true);
SELECT setval(pg_get_serial_sequence('public.credit_note_detail', 'id_cn_detail')::regclass, GREATEST(coalesce((SELECT max(id_cn_detail) FROM public.credit_note_detail), 0), 1), true);

SELECT
  'legacy_retur_summary' AS metric,
  (SELECT count(*) FROM tmp_legacy_retur_headers_raw) AS source_headers,
  (SELECT count(*) FROM tmp_legacy_retur_headers_mapped) AS mapped_candidate_headers,
  (SELECT count(*) FROM legacy_dist_2026.__map_retur_request) AS mapped_retur_request,
  (SELECT count(*) FROM legacy_dist_2026.__map_retur_request_detail) AS mapped_retur_detail,
  (SELECT count(*) FROM legacy_dist_2026.__map_retur_request WHERE id_credit_note IS NOT NULL) AS mapped_credit_note,
  (SELECT count(*) FROM legacy_dist_2026.__retur_mapping_issues WHERE run_id = 'legacy_retur_2026_to_public' AND issue_type IN ('missing_master', 'missing_product', 'missing_detail')) AS blocking_issues;

COMMIT;

SELECT 'FULL LEGACY MIGRATION 2026 FINISHED' AS migration_step;
