import os
from sqlalchemy import create_engine, text
NO='SO-20260616-010582'
engine=create_engine(f"postgresql+pg8000://{os.getenv('DB_USER','postgres')}:{os.getenv('DB_PASS','')}@{os.getenv('DB_HOST','127.0.0.1')}:{os.getenv('DB_PORT','5432')}/{os.getenv('DB_NAME','budimas_dev')}")
with engine.connect() as c:
    print('SO_BINDING', [dict(r) for r in c.execute(text('''
      SELECT so.id, so.no_order, so.tanggal_order, so.id_cabang, so.status_order,
             pl.id AS id_plafon, pl.id_user, pl.id_sales, pl.id_principal,
             u.nama AS nama_user_sales,
             pr.kode AS kode_principal, pr.nama AS principal, pr.id_perusahaan,
             f.no_faktur, f.status_faktur, f.total_penjualan
      FROM sales_order so
      JOIN plafon pl ON pl.id=so.id_plafon
      LEFT JOIN users u ON u.id=pl.id_user
      LEFT JOIN principal pr ON pr.id=pl.id_principal
      LEFT JOIN faktur f ON f.id_sales_order=so.id OR f.id_order_batch=so.id_order_batch
      WHERE so.no_order=:no
    '''), {'no':NO}).mappings().all()])
    print('SALES_ROW_ID_340_OR_USER_340', [dict(r) for r in c.execute(text('''
      SELECT s.*, u.nama AS user_name
      FROM sales s LEFT JOIN users u ON u.id=s.id_user
      WHERE s.id=340 OR s.id_user=340
      ORDER BY s.id
    ''')).mappings().all()])
    print('MATCH_PL_USER_340', [dict(r) for r in c.execute(text('''
      SELECT so.id, so.no_order FROM sales_order so
      JOIN plafon pl ON pl.id=so.id_plafon
      WHERE so.no_order=:no AND pl.id_user=340 AND so.id_cabang=5 AND so.tanggal_order BETWEEN '2026-06-01' AND '2026-06-30'
    '''), {'no':NO}).mappings().all()])
    print('MATCH_PL_SALES_340', [dict(r) for r in c.execute(text('''
      SELECT so.id, so.no_order FROM sales_order so
      JOIN plafon pl ON pl.id=so.id_plafon
      WHERE so.no_order=:no AND pl.id_sales=340 AND so.id_cabang=5 AND so.tanggal_order BETWEEN '2026-06-01' AND '2026-06-30'
    '''), {'no':NO}).mappings().all()])
