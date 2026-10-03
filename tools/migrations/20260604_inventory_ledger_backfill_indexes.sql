CREATE INDEX IF NOT EXISTS idx_sales_order_status_delivery_date
    ON sales_order (status_order, COALESCE(tanggal_terkirim, tanggal_faktur, tanggal_order));

CREATE INDEX IF NOT EXISTS idx_faktur_penjualan_sales_order
    ON faktur (id_sales_order, id)
    WHERE jenis_faktur = 'penjualan';

CREATE INDEX IF NOT EXISTS idx_faktur_penjualan_order_batch
    ON faktur (id_order_batch, id)
    WHERE jenis_faktur = 'penjualan';

ANALYZE sales_order;
ANALYZE sales_order_detail;
ANALYZE faktur;
