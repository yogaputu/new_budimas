UPDATE public.purchase_order_proses_log
SET tanggal = CURRENT_DATE,
    waktu = CURRENT_TIME
WHERE order_id = (SELECT id FROM public.purchase_order WHERE kode = '202606/SOLO/ET/0009' LIMIT 1)
  AND proses_id_diselesaikan = 2
  AND tanggal IS NULL;

SELECT po.id, po.kode, po.proses_id_berjalan, l.proses_id_diselesaikan, l.tanggal, l.waktu
FROM public.purchase_order po
LEFT JOIN public.purchase_order_proses_log l ON l.order_id = po.id
WHERE po.kode = '202606/SOLO/ET/0009'
ORDER BY l.id;
