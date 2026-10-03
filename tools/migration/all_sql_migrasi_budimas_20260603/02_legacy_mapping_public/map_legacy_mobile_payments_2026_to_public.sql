\set ON_ERROR_STOP on
\timing on

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

\echo '--- legacy mobile payment 2026 mapping summary ---'

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
