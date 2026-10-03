-- Master Data > Aturan Principal
-- Jalankan manual sebagai owner database sebelum membuka halaman /master/principal-rules.

CREATE TABLE IF NOT EXISTS public.principal_special_rule (
    id BIGSERIAL PRIMARY KEY,
    id_perusahaan INTEGER NOT NULL REFERENCES public.perusahaan(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    id_cabang INTEGER NOT NULL REFERENCES public.cabang(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    id_principal INTEGER REFERENCES public.principal(id) ON UPDATE CASCADE ON DELETE SET NULL,
    principal_group VARCHAR(100),
    target_doi_hari INTEGER NOT NULL DEFAULT 0,
    lead_time_hari INTEGER NOT NULL DEFAULT 0,
    moq_unit INTEGER NOT NULL DEFAULT 0,
    kelipatan_qty INTEGER NOT NULL DEFAULT 1,
    top_hari INTEGER NOT NULL DEFAULT 0,
    target_sell_in NUMERIC(18, 2) NOT NULL DEFAULT 0,
    target_sell_out NUMERIC(18, 2) NOT NULL DEFAULT 0,
    keterangan TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT principal_special_rule_target_check CHECK (
        id_principal IS NOT NULL OR NULLIF(BTRIM(principal_group), '') IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS idx_principal_special_rule_scope
    ON public.principal_special_rule (id_cabang, id_perusahaan, id_principal);

CREATE INDEX IF NOT EXISTS idx_principal_special_rule_group
    ON public.principal_special_rule (principal_group);

CREATE INDEX IF NOT EXISTS idx_principal_special_rule_active
    ON public.principal_special_rule (is_active);

-- Dummy UAT. Aman dijalankan ulang karena dicegah oleh NOT EXISTS.
WITH seed_rows AS (
    SELECT * FROM (VALUES
        (1, 5, 5, NULL::varchar, 45, 7, 1, 1, 60, 1773780000::numeric, 1773780000::numeric, 'Dummy UAT ET: target DOI principal mengikuti contoh awal.'),
        (1, 5, NULL::integer, 'NU', 45, 7, 1, 1, 45, 1800000000::numeric, 1800000000::numeric, 'Dummy UAT principal group NU.'),
        (1, 5, NULL::integer, 'UNI', 30, 7, 1, 1, 30, 1000000000::numeric, 1200000000::numeric, 'Dummy UAT principal group UNI.'),
        (1, 5, 4, NULL::varchar, 35, 5, 5, 5, 45, 850000000::numeric, 900000000::numeric, 'Dummy UAT Dolphin: MOQ dan kelipatan lebih besar.'),
        (2, 5, 11, NULL::varchar, 40, 7, 1, 1, 45, 700000000::numeric, 750000000::numeric, 'Dummy UAT TMP Solo.')
    ) AS v(id_perusahaan, id_cabang, id_principal, principal_group, target_doi_hari, lead_time_hari, moq_unit, kelipatan_qty, top_hari, target_sell_in, target_sell_out, keterangan)
)
INSERT INTO public.principal_special_rule (
    id_perusahaan, id_cabang, id_principal, principal_group,
    target_doi_hari, lead_time_hari, moq_unit, kelipatan_qty, top_hari,
    target_sell_in, target_sell_out, keterangan, is_active, created_at, updated_at
)
SELECT
    s.id_perusahaan, s.id_cabang, s.id_principal, s.principal_group,
    s.target_doi_hari, s.lead_time_hari, s.moq_unit, s.kelipatan_qty, s.top_hari,
    s.target_sell_in, s.target_sell_out, s.keterangan, TRUE, NOW(), NOW()
FROM seed_rows s
WHERE EXISTS (SELECT 1 FROM public.perusahaan p WHERE p.id = s.id_perusahaan)
  AND EXISTS (SELECT 1 FROM public.cabang c WHERE c.id = s.id_cabang)
  AND (s.id_principal IS NULL OR EXISTS (SELECT 1 FROM public.principal pr WHERE pr.id = s.id_principal))
  AND NOT EXISTS (
      SELECT 1 FROM public.principal_special_rule r
      WHERE r.id_perusahaan = s.id_perusahaan
        AND r.id_cabang = s.id_cabang
        AND COALESCE(r.id_principal, 0) = COALESCE(s.id_principal, 0)
        AND COALESCE(r.principal_group, '') = COALESCE(s.principal_group, '')
  );
