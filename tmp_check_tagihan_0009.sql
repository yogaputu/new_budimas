\pset format unaligned
SELECT pt.id, pt.no_transaksi, pt.order_id, po.kode AS kode_po, pt.proses_id_berjalan, pt.total, pt.status_pembayaran, pt.jatuh_tempo
FROM public.purchase_transaksi pt
JOIN public.purchase_order po ON po.id = pt.order_id
WHERE po.kode = '202606/SOLO/ET/0009';

SELECT ptd.id AS tagihan_detail_id, ptd.transaksi_id, ptd.tagihan_id, ptd.subtotal,
       tg.no_tagihan, tg.total AS total_tagihan, tg.status_pembayaran, tg.jatuh_tempo, tg.tanggal_bayar
FROM public.purchase_tagihan_detail ptd
LEFT JOIN public.purchase_tagihan tg ON tg.id = ptd.tagihan_id
WHERE ptd.transaksi_id IN (
  SELECT pt.id FROM public.purchase_transaksi pt
  JOIN public.purchase_order po ON po.id = pt.order_id
  WHERE po.kode = '202606/SOLO/ET/0009'
)
ORDER BY ptd.id;

SELECT ptl.id, ptl.transaksi_id, ptl.proses_id_diselesaikan, ptl.tanggal, ptl.waktu, ptl.user_id
FROM public.purchase_transaksi_proses_log ptl
WHERE ptl.transaksi_id IN (
  SELECT pt.id FROM public.purchase_transaksi pt
  JOIN public.purchase_order po ON po.id = pt.order_id
  WHERE po.kode = '202606/SOLO/ET/0009'
)
ORDER BY ptl.id;
