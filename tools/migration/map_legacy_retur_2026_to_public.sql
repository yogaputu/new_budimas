\set ON_ERROR_STOP on
\timing on

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
