-- Customer tax identity fields for PKP/Non PKP/NPWP/Lain-lain status.

BEGIN;

ALTER TABLE customer
    ADD COLUMN IF NOT EXISTS status_pajak VARCHAR(30),
    ADD COLUMN IF NOT EXISTS jenis_identitas_pajak VARCHAR(30);

UPDATE customer
SET status_pajak = CASE
        WHEN LOWER(COALESCE(is_ppn::TEXT, '')) IN ('1', 'true', 't', 'pkp', 'ppn') THEN 'pkp'
        ELSE 'non_pkp'
    END
WHERE status_pajak IS NULL OR status_pajak = '';

UPDATE customer
SET jenis_identitas_pajak = CASE
        WHEN status_pajak IN ('pkp', 'npwp') THEN 'npwp'
        WHEN status_pajak = 'lain_lain' THEN 'lain_lain'
        ELSE 'nik'
    END
WHERE jenis_identitas_pajak IS NULL OR jenis_identitas_pajak = '';

COMMIT;
