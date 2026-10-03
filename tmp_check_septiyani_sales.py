import os
from sqlalchemy import create_engine, text
engine=create_engine(f"postgresql+pg8000://{os.getenv('DB_USER','postgres')}:{os.getenv('DB_PASS','')}@{os.getenv('DB_HOST','127.0.0.1')}:{os.getenv('DB_PORT','5432')}/{os.getenv('DB_NAME','budimas_dev')}")
with engine.connect() as c:
    print('SALES_DUP', [dict(r) for r in c.execute(text('''
      SELECT s.id AS id_sales, s.id_user, u.nama AS nama_user,
             sd.kode_sales,
             s.id_principal AS direct_principal_id,
             p0.kode AS direct_principal_code,
             p0.nama AS direct_principal_name,
             array_agg(DISTINCT spa.id_principal) FILTER (WHERE spa.id_principal IS NOT NULL) AS assigned_principal_ids,
             string_agg(DISTINCT p.kode || ' - ' || p.nama, '; ') FILTER (WHERE p.id IS NOT NULL) AS assigned_principals
      FROM sales s
      LEFT JOIN users u ON u.id=s.id_user
      LEFT JOIN sales_detail sd ON sd.id_sales=s.id
      LEFT JOIN principal p0 ON p0.id=s.id_principal
      LEFT JOIN sales_principal_assignment spa ON spa.id_sales=s.id
      LEFT JOIN principal p ON p.id=spa.id_principal
      WHERE s.id_user=216 OR s.id IN (142,304)
      GROUP BY s.id, s.id_user, u.nama, sd.kode_sales, s.id_principal, p0.kode, p0.nama
      ORDER BY s.id
    ''')).mappings().all()])
    print('PLAFON_COUNTS', [dict(r) for r in c.execute(text('''
      SELECT pl.id_sales, pl.id_user, pl.id_principal, pr.kode AS kode_principal, pr.nama AS principal,
             count(*) AS plafon_count,
             count(DISTINCT pl.id_customer) AS customer_count
      FROM plafon pl
      LEFT JOIN principal pr ON pr.id=pl.id_principal
      WHERE pl.id_user=216 OR pl.id_sales IN (142,304)
      GROUP BY pl.id_sales, pl.id_user, pl.id_principal, pr.kode, pr.nama
      ORDER BY pl.id_sales, pl.id_principal
    ''')).mappings().all()])
    print('SO_COUNTS_2026', [dict(r) for r in c.execute(text('''
      SELECT pl.id_sales, pl.id_user, pl.id_principal, pr.kode AS kode_principal, pr.nama AS principal,
             count(*) AS so_count,
             max(so.tanggal_order) AS last_order
      FROM sales_order so
      JOIN plafon pl ON pl.id=so.id_plafon
      LEFT JOIN principal pr ON pr.id=pl.id_principal
      WHERE (pl.id_user=216 OR pl.id_sales IN (142,304)) AND so.tanggal_order >= '2026-01-01'
      GROUP BY pl.id_sales, pl.id_user, pl.id_principal, pr.kode, pr.nama
      ORDER BY pl.id_sales, pl.id_principal
    ''')).mappings().all()])
