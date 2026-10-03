CREATE INDEX IF NOT EXISTS idx_retur_request_sales_order
  ON retur_request (id_sales_order);

CREATE INDEX IF NOT EXISTS idx_retur_request_status_date
  ON retur_request (status_request, tanggal_request);

CREATE INDEX IF NOT EXISTS idx_retur_request_sales
  ON retur_request (id_sales);

CREATE INDEX IF NOT EXISTS idx_retur_request_principal
  ON retur_request (id_principal);

CREATE INDEX IF NOT EXISTS idx_retur_request_customer
  ON retur_request (id_customer);

CREATE INDEX IF NOT EXISTS idx_retur_request_detail_request
  ON retur_request_detail (id_request);

CREATE INDEX IF NOT EXISTS idx_faktur_sales_order
  ON faktur (id_sales_order);

CREATE INDEX IF NOT EXISTS idx_faktur_order_batch
  ON faktur (id_order_batch);

CREATE INDEX IF NOT EXISTS idx_credit_note_retur_request
  ON credit_note (id_retur_request);

CREATE INDEX IF NOT EXISTS idx_sales_order_branch
  ON sales_order (id_cabang);

CREATE INDEX IF NOT EXISTS idx_sales_order_plafon
  ON sales_order (id_plafon);

CREATE INDEX IF NOT EXISTS idx_plafon_user_sales
  ON plafon (id_user, id_sales);

CREATE INDEX IF NOT EXISTS idx_principal_company
  ON principal (id_perusahaan);
