import os
from sqlalchemy import create_engine, text
NO='SO-20260616-010582'
engine=create_engine(f"postgresql+pg8000://{os.getenv('DB_USER','postgres')}:{os.getenv('DB_PASS','')}@{os.getenv('DB_HOST','127.0.0.1')}:{os.getenv('DB_PORT','5432')}/{os.getenv('DB_NAME','budimas_dev')}")
with engine.connect() as c:
  for name, where, params in [
    ('dashboard_no_filter', 'so.no_order=:no', {'no':NO}),
    ('dashboard_date_to_2026_06_16', 'so.no_order=:no AND so.tanggal_order <= :to', {'no':NO,'to':'2026-06-16'}),
    ('dashboard_cabang_solo', 'so.no_order=:no AND so.id_cabang=:cab', {'no':NO,'cab':5}),
  ]:
    rs=c.execute(text(f'''
      SELECT so.id, so.no_order, so.tanggal_order, so.status_order, so.id_cabang,
             c.nama AS customer, pr.id AS id_principal, pr.kode AS kode_principal, pr.nama AS principal,
             pr.id_perusahaan, f.id AS id_faktur, f.no_faktur, f.status_faktur,
             COALESCE(f.total_penjualan, so.total_order, 0) AS total_penjualan
      FROM sales_order so
      JOIN plafon pl ON pl.id=so.id_plafon
      LEFT JOIN customer c ON c.id=pl.id_customer
      LEFT JOIN principal pr ON pr.id=pl.id_principal
      LEFT JOIN faktur f ON f.id_sales_order=so.id OR f.id_order_batch=so.id_order_batch
      WHERE {where}
    '''), params).mappings().all()
    print(name, [dict(r) for r in rs])
