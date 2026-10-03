\pset format unaligned
SELECT po.id, po.kode, po.proses_id_berjalan,
       max(l.proses_id_diselesaikan) AS proses_id_diselesaikan,
       max(l.tanggal) AS tanggal,
       c.id AS cabang_id, c.nama AS cabang_nama,
       p.id AS principal_id, p.id_perusahaan, p.nama AS principal_nama
FROM public.purchase_order po
LEFT JOIN public.cabang c ON c.id = po.cabang_id
LEFT JOIN public.principal p ON p.id = po.principal_id
LEFT JOIN public.purchase_order_proses_log l ON l.order_id = po.id
WHERE po.cabang_id = 5
  AND p.id_perusahaan = 1
  AND p.id = 5
GROUP BY po.id, c.id, p.id
ORDER BY po.id DESC
LIMIT 20;

SELECT po.id, po.kode, po.proses_id_berjalan, p.id_perusahaan, po.cabang_id, po.principal_id
FROM public.purchase_order po
JOIN public.principal p ON p.id = po.principal_id
WHERE po.kode = '202606/SOLO/ET/0006'
  AND po.cabang_id = 5
  AND p.id_perusahaan = 1
  AND p.id = 5;
