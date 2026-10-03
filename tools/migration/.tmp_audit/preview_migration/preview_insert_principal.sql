-- PREVIEW ONLY. Review id_perusahaan target before executing.
-- Replace :id_perusahaan_target with target perusahaan id.
INSERT INTO principal (kode, nama, id_perusahaan) VALUES ('42', 'X', :id_perusahaan_target) ON CONFLICT DO NOTHING;
INSERT INTO principal (kode, nama, id_perusahaan) VALUES ('60A', 'NFI GIMMICK', :id_perusahaan_target) ON CONFLICT DO NOTHING;
INSERT INTO principal (kode, nama, id_perusahaan) VALUES ('BK', 'PT.BRANDS KONNECT INTERN', :id_perusahaan_target) ON CONFLICT DO NOTHING;
INSERT INTO principal (kode, nama, id_perusahaan) VALUES ('M3', 'MIX 3', :id_perusahaan_target) ON CONFLICT DO NOTHING;
INSERT INTO principal (kode, nama, id_perusahaan) VALUES ('M6', 'MIX 6', :id_perusahaan_target) ON CONFLICT DO NOTHING;
INSERT INTO principal (kode, nama, id_perusahaan) VALUES ('MFB', 'Mix Food Budimas', :id_perusahaan_target) ON CONFLICT DO NOTHING;
