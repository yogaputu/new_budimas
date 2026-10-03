\set ON_ERROR_STOP on
\timing on

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
