import os
from sqlalchemy import create_engine, text
engine=create_engine(f"postgresql+pg8000://{os.getenv('DB_USER','postgres')}:{os.getenv('DB_PASS','')}@{os.getenv('DB_HOST','127.0.0.1')}:{os.getenv('DB_PORT','5432')}/{os.getenv('DB_NAME','budimas_dev')}")
with engine.connect() as c:
    print('REMOTE_PATCH_LINE', c.execute(text('select 1')).scalar())
    rows=c.execute(text('''
SELECT so.id, so.no_order, so.tanggal_order, pl.id_user, pl.id_sales, so.id_cabang, pr.id_perusahaan, f.no_faktur, f.status_faktur
FROM sales_order so
JOIN plafon pl ON pl.id=so.id_plafon
LEFT JOIN principal pr ON pr.id=pl.id_principal
LEFT JOIN faktur f ON f.id_sales_order=so.id OR f.id_order_batch=so.id_order_batch
WHERE pl.id_user=216
  AND so.id_cabang=5
  AND pr.id_perusahaan=1
  AND so.tanggal_order >= '2026-06-01'
  AND so.tanggal_order <= '2026-06-30'
  AND so.no_order='SO-20260616-010582'
''')).mappings().all()
    print('NEW_FILTER_MATCH', [dict(r) for r in rows])
