\pset format unaligned
SELECT l.id, l.order_id, l.proses_id_diselesaikan, l.tanggal, l.waktu, l.user_id, u.nama AS user_nama
FROM public.purchase_order_proses_log l
LEFT JOIN public.users u ON u.id = l.user_id
WHERE l.order_id = 1385
ORDER BY l.id;

SELECT d.order_id, count(*) AS detail_count,
       coalesce(sum(d.total_order),0) AS sum_order,
       coalesce(sum(d.total_terpenuhi),0) AS sum_terpenuhi,
       coalesce(sum(d.total_tersisa),0) AS sum_tersisa,
       coalesce(sum(d.subtotal),0) AS subtotal
FROM public.purchase_order_detail d
WHERE d.order_id = 1385
GROUP BY d.order_id;

SELECT d.id, d.produk_id, d.produk_kode, d.produk_nama,
       d.produk_harga_beli, d.ppn, d.total_order, d.total_terpenuhi, d.total_tersisa, d.subtotal
FROM public.purchase_order_detail d
WHERE d.order_id = 1385
ORDER BY d.id
LIMIT 20;
