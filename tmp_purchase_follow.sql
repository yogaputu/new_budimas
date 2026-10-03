\pset format unaligned
SELECT pt.id, pt.no_transaksi, pt.order_id, pt.proses_id_berjalan, pt.total, pt.status_pembayaran, pt.jatuh_tempo, pt.keterangan
FROM public.purchase_transaksi pt
WHERE pt.order_id IN (SELECT id FROM public.purchase_order WHERE kode = '202606/SOLO/ET/0009')
ORDER BY pt.id;

SELECT ptd.transaksi_id, count(*) AS detail_count,
       coalesce(sum(ptd.total_order),0) AS sum_order,
       coalesce(sum(ptd.total_terpenuhi),0) AS sum_terpenuhi,
       coalesce(sum(ptd.total_tersisa),0) AS sum_tersisa,
       coalesce(sum(ptd.subtotal),0) AS subtotal
FROM public.purchase_transaksi_detail ptd
WHERE ptd.transaksi_id IN (
  SELECT id FROM public.purchase_transaksi WHERE order_id IN (SELECT id FROM public.purchase_order WHERE kode = '202606/SOLO/ET/0009')
)
GROUP BY ptd.transaksi_id;

SELECT tg.id, tg.no_tagihan, tg.transaksi_id, tg.total, tg.nominal_pembayaran, tg.status_pembayaran, tg.jatuh_tempo, tg.tanggal_bayar
FROM public.purchase_tagihan tg
WHERE tg.transaksi_id IN (
  SELECT id FROM public.purchase_transaksi WHERE order_id IN (SELECT id FROM public.purchase_order WHERE kode = '202606/SOLO/ET/0009')
)
ORDER BY tg.id;
