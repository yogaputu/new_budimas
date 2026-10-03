import os
from sqlalchemy import create_engine, text

NO_ORDER = "SO-20260616-010582"
engine = create_engine(f"postgresql+pg8000://{os.getenv('DB_USER','postgres')}:{os.getenv('DB_PASS','')}@{os.getenv('DB_HOST','127.0.0.1')}:{os.getenv('DB_PORT','5432')}/{os.getenv('DB_NAME','budimas_dev')}")

def rows(conn, sql, params=None):
    return [dict(r._mapping) for r in conn.execute(text(sql), params or {}).fetchall()]

with engine.connect() as conn:
    so_rows = rows(conn, """
        SELECT so.id, so.no_order, so.status_order, so.id_cabang, cb.nama AS nama_cabang,
               so.id_plafon, so.tanggal_order, so.tanggal_faktur, so.tanggal_terkirim,
               so.no_faktur, so.no_tagihan, so.id_order_batch, so.total_order,
               pl.id_customer, cu.kode AS kode_customer, cu.nama AS nama_customer,
               cu.id_rute, r.kode AS kode_rute, r.nama_rute
        FROM sales_order so
        LEFT JOIN cabang cb ON cb.id = so.id_cabang
        LEFT JOIN plafon pl ON pl.id = so.id_plafon
        LEFT JOIN customer cu ON cu.id = pl.id_customer
        LEFT JOIN rute r ON r.id = cu.id_rute
        WHERE so.no_order = :no
    """, {"no": NO_ORDER})
    print("SALES_ORDER", so_rows)
    if not so_rows:
        raise SystemExit
    so_id = so_rows[0]["id"]
    batch = so_rows[0].get("id_order_batch")
    print("DETAIL_COUNT", rows(conn, """
        SELECT count(*) AS rows, coalesce(sum(pieces_order),0) AS pieces_order,
               coalesce(sum(box_order),0) AS box_order, coalesce(sum(karton_order),0) AS karton_order,
               coalesce(sum(subtotalorder),0) AS subtotal
        FROM sales_order_detail WHERE id_sales_order = :id
    """, {"id": so_id}))
    print("FAKTUR_BY_SO", rows(conn, """
        SELECT id, id_sales_order, no_faktur, jenis_faktur, status_faktur, total_penjualan
        FROM faktur WHERE id_sales_order = :id ORDER BY id
    """, {"id": so_id}))
    if batch:
        print("FAKTUR_DETAIL_BATCH", rows(conn, """
            SELECT fd.id, fd.id_faktur, fd.id_sales_order, f.no_faktur, f.jenis_faktur, f.status_faktur
            FROM faktur_detail fd LEFT JOIN faktur f ON f.id = fd.id_faktur
            WHERE fd.id_sales_order = :id OR fd.id_order_batch = :batch
            ORDER BY fd.id
        """, {"id": so_id, "batch": batch}))
    print("PICKING_SUMMARY", rows(conn, """
        SELECT count(*) AS rows,
               count(*) FILTER (WHERE pp.id_armada IS NOT NULL) AS rows_with_armada,
               count(*) FILTER (WHERE pp.id_driver IS NOT NULL) AS rows_with_driver,
               count(*) FILTER (WHERE pp.delivering_date IS NOT NULL) AS rows_with_date,
               string_agg(distinct pp.id_armada::text, ',') AS armada_ids,
               string_agg(distinct pp.id_driver::text, ',') AS driver_ids,
               string_agg(distinct pp.delivering_date::text, ',') AS dates,
               coalesce(sum(pp.jumlah_picked),0) AS jumlah_picked
        FROM proses_picking pp
        JOIN sales_order_detail sod ON sod.id = pp.id_order_detail
        WHERE sod.id_sales_order = :id
    """, {"id": so_id}))
    print("PICKING_ROWS", rows(conn, """
        SELECT pp.id, pp.id_order_detail, pp.id_produk, p.kode_sku, p.nama AS produk,
               pp.jumlah_picked, pp.id_armada, a.no_pelat,
               pp.id_driver, u.nama AS nama_driver, pp.id_helper,
               pp.delivering_date
        FROM proses_picking pp
        JOIN sales_order_detail sod ON sod.id = pp.id_order_detail
        LEFT JOIN produk p ON p.id = pp.id_produk
        LEFT JOIN armada a ON a.id = pp.id_armada
        LEFT JOIN driver d ON d.id = pp.id_driver
        LEFT JOIN users u ON u.id = d.id_user
        WHERE sod.id_sales_order = :id
        ORDER BY pp.id
        LIMIT 20
    """, {"id": so_id}))
    print("INVOICE_SHIPPING_MATCH", rows(conn, """
        SELECT so.id AS id_sales_order, so.no_order, so.status_order, f.id AS id_faktur, f.no_faktur,
               pp.id_armada, pp.id_driver, pp.delivering_date, cu.id_cabang, cu.id_rute
        FROM customer cu
        JOIN rute r ON cu.id_rute = r.id
        JOIN plafon pl ON pl.id_customer = cu.id
        JOIN sales_order so ON so.id_plafon = pl.id
        JOIN faktur f ON f.id_sales_order = so.id
        JOIN sales_order_detail sod ON so.id = sod.id_sales_order
        JOIN proses_picking pp ON sod.id = pp.id_order_detail
        WHERE so.id = :id
          AND f.jenis_faktur = 'penjualan'
          AND so.status_order IN (3,10)
          AND pp.id_armada IS NOT NULL
          AND pp.id_driver IS NOT NULL
          AND pp.delivering_date IS NOT NULL
        LIMIT 20
    """, {"id": so_id}))
    print("INVOICE_REALISASI_MATCH", rows(conn, """
        SELECT so.id AS id_sales_order, so.no_order, so.status_order, f.id AS id_faktur, f.no_faktur,
               pp.id_armada, pp.id_driver, pp.delivering_date, cu.id_cabang, cu.id_rute
        FROM customer cu
        JOIN rute r ON cu.id_rute = r.id
        JOIN plafon pl ON pl.id_customer = cu.id
        JOIN sales_order so ON so.id_plafon = pl.id
        JOIN faktur f ON f.id_sales_order = so.id
        JOIN sales_order_detail sod ON so.id = sod.id_sales_order
        JOIN proses_picking pp ON sod.id = pp.id_order_detail
        WHERE so.id = :id
          AND f.jenis_faktur = 'penjualan'
          AND so.status_order IN (4,11)
          AND pp.id_armada IS NOT NULL
          AND pp.id_driver IS NOT NULL
          AND pp.delivering_date IS NOT NULL
        LIMIT 20
    """, {"id": so_id}))
