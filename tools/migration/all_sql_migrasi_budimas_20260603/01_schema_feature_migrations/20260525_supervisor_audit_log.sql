-- Supervisor Audit Log
-- Import manual ke server. Backend tidak membuat tabel otomatis.

CREATE TABLE IF NOT EXISTS supervisor_audit_log (
    id BIGSERIAL PRIMARY KEY,
    id_user INTEGER,
    nama_user VARCHAR(120),
    id_cabang INTEGER,
    id_perusahaan INTEGER,
    module VARCHAR(80) NOT NULL,
    action VARCHAR(80) NOT NULL,
    target_type VARCHAR(80),
    target_id VARCHAR(80),
    target_code VARCHAR(120),
    before_data JSONB,
    after_data JSONB,
    note TEXT,
    ip_address VARCHAR(80),
    user_agent TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_supervisor_audit_log_created_at
    ON supervisor_audit_log (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_supervisor_audit_log_scope
    ON supervisor_audit_log (id_cabang, id_perusahaan, id_user);

CREATE INDEX IF NOT EXISTS idx_supervisor_audit_log_module_action
    ON supervisor_audit_log (module, action);

CREATE INDEX IF NOT EXISTS idx_supervisor_audit_log_target
    ON supervisor_audit_log (target_type, target_id, target_code);

-- Contoh seed UAT opsional. Hapus/comment kalau tidak ingin data dummy.
-- INSERT INTO supervisor_audit_log (
--     id_user, nama_user, id_cabang, id_perusahaan, module, action,
--     target_type, target_id, target_code, before_data, after_data, note
-- ) VALUES (
--     1, 'Admin IT 1', 5, 1, 'retur-approval', 'approve',
--     'retur_request', 'RTBMM-0001', 'RTBMM-0001',
--     '{"status":"Pengajuan"}'::jsonb,
--     '{"status":"Disetujui"}'::jsonb,
--     'Contoh audit approval retur untuk UAT'
-- );
