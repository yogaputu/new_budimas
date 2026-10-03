import os
from sqlalchemy import create_engine, text
engine=create_engine(f"postgresql+pg8000://{os.getenv('DB_USER','postgres')}:{os.getenv('DB_PASS','')}@{os.getenv('DB_HOST','127.0.0.1')}:{os.getenv('DB_PORT','5432')}/{os.getenv('DB_NAME','budimas_dev')}")
with engine.connect() as c:
    print([dict(r) for r in c.execute(text('''
SELECT sales.id AS id_sales, sales.id_user, users.id, users.nama, users.id_cabang, users.id_perusahaan, sales_detail.kode_sales,
       ARRAY_AGG(spa.id_principal) AS id_principals
FROM sales
LEFT JOIN users ON users.id = sales.id_user
LEFT JOIN sales_detail ON sales_detail.id_sales = sales.id
LEFT JOIN sales_principal_assignment spa ON spa.id_sales=sales.id
WHERE sales.id=142 OR sales.id_user=216 OR users.nama ILIKE '%SEPTIYANI%'
GROUP BY sales.id, sales.id_user, users.id, users.nama, users.id_cabang, users.id_perusahaan, sales_detail.kode_sales
ORDER BY sales.id
''')).mappings().all()])
    print('dashboard_exact_filters', [dict(r) for r in c.execute(text('''
SELECT so.id, so.no_order, so.tanggal_order, pl.id_user, pl.id_sales, so.id_cabang, pr.id_perusahaan, f.no_faktur
FROM sales_order so
JOIN plafon pl ON pl.id=so.id_plafon
LEFT JOIN principal pr ON pr.id=pl.id_principal
LEFT JOIN faktur f ON f.id_sales_order=so.id OR f.id_order_batch=so.id_order_batch
WHERE so.no_order='SO-20260616-010582'
  AND pl.id_sales=142 AND so.id_cabang=5 AND pr.id_perusahaan=1
  AND so.tanggal_order >= '2026-06-01' AND so.tanggal_order <= '2026-06-30'
''')).mappings().all()])
