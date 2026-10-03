import os
from sqlalchemy import create_engine, text

code = '202606/SOLO/ET/0006'
pg_user = os.environ.get('AI_DB_USER') or os.environ.get('DB_USER') or 'postgres'
pg_pass = os.environ.get('AI_DB_PASS') or os.environ.get('DB_PASS') or ''
pg_host = os.environ.get('AI_DB_HOST') or os.environ.get('DB_HOST') or '127.0.0.1'
pg_port = os.environ.get('AI_DB_PORT') or os.environ.get('DB_PORT') or '5432'
pg_name = os.environ.get('AI_DB_NAME') or os.environ.get('DB_NAME') or 'budimas_dev'
url = f'postgresql+pg8000://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_name}'
engine = create_engine(url)
with engine.connect() as conn:
    rows = conn.execute(text('''
        SELECT po.id, po.kode, po.cabang_id, c.kode AS cabang_kode, c.nama AS cabang_nama,
               po.principal_id, p.kode AS principal_kode, p.nama AS principal_nama, p.id_perusahaan,
               per.kode AS perusahaan_kode, per.nama AS perusahaan_nama,
               po.proses_id_berjalan, po.total, po.keterangan
        FROM purchase_order po
        LEFT JOIN cabang c ON c.id = po.cabang_id
        LEFT JOIN principal p ON p.id = po.principal_id
        LEFT JOIN perusahaan per ON per.id = p.id_perusahaan
        WHERE po.kode = :code OR po.kode ILIKE :like
        ORDER BY po.id DESC
    '''), {'code': code, 'like': f'%{code}%'}).mappings().all()
    print('MATCH_COUNT', len(rows))
    for r in rows:
        print('PO', dict(r))
        oid = r['id']
        logs = conn.execute(text('''
            SELECT l.id, l.order_id, l.proses_id_diselesaikan, l.tanggal, l.waktu, l.user_id, u.nama AS user_nama
            FROM purchase_order_proses_log l
            LEFT JOIN "user" u ON u.id = l.user_id
            WHERE l.order_id = :id
            ORDER BY l.id
        '''), {'id': oid}).mappings().all()
        print('LOGS', [dict(x) for x in logs])
        detail_summary = conn.execute(text('''
            SELECT count(*) AS detail_count,
                   coalesce(sum(total_order),0) AS sum_order,
                   coalesce(sum(total_tersisa),0) AS sum_tersisa,
                   coalesce(sum(total_bayar),0) AS sum_bayar
            FROM purchase_order_detail
            WHERE order_id = :id
        '''), {'id': oid}).mappings().first()
        print('DETAIL_SUMMARY', dict(detail_summary))
        details = conn.execute(text('''
            SELECT d.id, d.produk_id, pr.kode_sku, pr.nama AS produk_nama,
                   d.total_order, d.total_tersisa, d.total_bayar, d.harga
            FROM purchase_order_detail d
            LEFT JOIN produk pr ON pr.id = d.produk_id
            WHERE d.order_id = :id
            ORDER BY d.id
            LIMIT 20
        '''), {'id': oid}).mappings().all()
        print('DETAILS', [dict(x) for x in details])

    nearby = conn.execute(text('''
        SELECT po.id, po.kode, po.cabang_id, c.nama AS cabang_nama, po.principal_id, p.kode AS principal_kode,
               p.nama AS principal_nama, p.id_perusahaan, po.proses_id_berjalan
        FROM purchase_order po
        LEFT JOIN cabang c ON c.id = po.cabang_id
        LEFT JOIN principal p ON p.id = po.principal_id
        WHERE po.kode ILIKE '%202606/SOLO/ET%'
        ORDER BY po.id DESC
        LIMIT 20
    ''')).mappings().all()
    print('NEARBY', [dict(x) for x in nearby])
