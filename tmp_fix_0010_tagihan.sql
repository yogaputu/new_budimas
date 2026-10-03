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
WHERE po.kode = '202606/SOLO/ET/0010'
ORDER BY ptd.id;

SELECT purchase_tagihan.id AS id,
       purchase_tagihan.id AS id_tagihan,
       purchase_tagihan.no_tagihan AS surat_tagihan,
       COALESCE(purchase_tagihan.total, 0) AS total_tagihan,
       CASE WHEN purchase_tagihan.status_pembayaran = 1 THEN 'belum lunas'
            WHEN purchase_tagihan.status_pembayaran = 2 THEN 'lunas'
            ELSE 'tidak diketahui' END AS status_bayar,
       purchase_tagihan.tanggal_bayar,
       purchase_tagihan.jatuh_tempo,
       COALESCE(STRING_AGG(DISTINCT principal.nama, ', '), '-') AS nama_principal,
       COALESCE(COUNT(purchase_tagihan_detail.id), 0) AS jumlah_faktur,
       MIN(principal.id) AS id_principal,
       MIN(principal.id_perusahaan) AS id_perusahaan,
       MIN(purchase_order.cabang_id) AS id_cabang
FROM public.purchase_tagihan
LEFT JOIN public.purchase_tagihan_detail ON purchase_tagihan.id = purchase_tagihan_detail.tagihan_id
LEFT JOIN public.purchase_transaksi ON purchase_tagihan_detail.transaksi_id = purchase_transaksi.id
LEFT JOIN public.purchase_order ON purchase_transaksi.order_id = purchase_order.id
LEFT JOIN public.principal ON purchase_order.principal_id = principal.id
WHERE purchase_order.cabang_id = 5
  AND principal.id_perusahaan = 1
  AND principal.id = 5
  AND purchase_tagihan.no_tagihan = 'TP-20260616140334'
GROUP BY purchase_tagihan.id, purchase_tagihan.no_tagihan, purchase_tagihan.total,
         purchase_tagihan.status_pembayaran, purchase_tagihan.tanggal_bayar, purchase_tagihan.jatuh_tempo;
