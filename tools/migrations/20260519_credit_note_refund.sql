ALTER TABLE credit_note
  ADD COLUMN IF NOT EXISTS tanggal_refund TIMESTAMP NULL,
  ADD COLUMN IF NOT EXISTS nominal_refund DOUBLE PRECISION DEFAULT 0,
  ADD COLUMN IF NOT EXISTS metode_refund VARCHAR(50),
  ADD COLUMN IF NOT EXISTS id_rekening_perusahaan INTEGER NULL,
  ADD COLUMN IF NOT EXISTS id_mutasi_acc INTEGER NULL,
  ADD COLUMN IF NOT EXISTS catatan_refund TEXT,
  ADD COLUMN IF NOT EXISTS user_refund INTEGER NULL;

CREATE INDEX IF NOT EXISTS idx_credit_note_refund_rekening
  ON credit_note (id_rekening_perusahaan);

CREATE INDEX IF NOT EXISTS idx_credit_note_refund_accounting_entry
  ON credit_note (id_mutasi_acc);

CREATE INDEX IF NOT EXISTS idx_credit_note_user_refund
  ON credit_note (user_refund);
