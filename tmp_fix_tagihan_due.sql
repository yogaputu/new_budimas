UPDATE public.purchase_tagihan tg
SET jatuh_tempo = src.jatuh_tempo
FROM (
    SELECT ptd.tagihan_id, MAX(pt.jatuh_tempo) AS jatuh_tempo
    FROM public.purchase_tagihan_detail ptd
    JOIN public.purchase_transaksi pt ON pt.id = ptd.transaksi_id
    WHERE pt.jatuh_tempo IS NOT NULL
    GROUP BY ptd.tagihan_id
) src
WHERE tg.id = src.tagihan_id
  AND tg.jatuh_tempo IS NULL;

SELECT ptd.id AS tagihan_detail_id, ptd.transaksi_id, ptd.tagihan_id, ptd.subtotal,
       tg.no_tagihan, tg.total AS total_tagihan, tg.status_pembayaran, tg.jatuh_tempo, tg.tanggal_bayar,
       pt.no_transaksi, po.kode AS kode_po
FROM public.purchase_tagihan_detail ptd
JOIN public.purchase_tagihan tg ON tg.id = ptd.tagihan_id
JOIN public.purchase_transaksi pt ON pt.id = ptd.transaksi_id
JOIN public.purchase_order po ON po.id = pt.order_id
WHERE po.kode = '202606/SOLO/ET/0009'
ORDER BY ptd.id;
