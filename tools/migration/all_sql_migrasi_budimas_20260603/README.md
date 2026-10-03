# All SQL Migrasi Budimas

Folder ini mengumpulkan semua SQL migrasi yang tersebar dari pekerjaan migrasi kemarin-kemarin.

## Isi Folder

- `01_schema_feature_migrations/`: migrasi schema dan fitur dari `tools/migrations`.
- `02_legacy_mapping_public/`: mapping data legacy/staging ke tabel public.
- `03_preview_master_mapping/`: SQL preview insert master/mapping yang dipakai saat audit master.
- `04_sqlserver_staging_copy/`: SQL staging/copy dari hasil dump SQL Server ke PostgreSQL staging.
- `99_full_legacy_bundle/`: bundle gabungan legacy yang sebelumnya dibuat, termasuk runner dan steps.

## Jumlah File

- Schema/fitur: 22
- Legacy mapping public: 6
- Preview master/mapping: 6
- SQL Server staging/copy: 70
- Full legacy bundle SQL: 8
- Total SQL: 112

## Catatan

- Folder ini adalah arsip/koleksi SQL. Jangan langsung menjalankan semua file tanpa memilih kelompok yang sesuai.
- Untuk migrasi data legacy ke public, gunakan file di `99_full_legacy_bundle/00_run_all_legacy_migration_2026.sql` atau file per tahap di `02_legacy_mapping_public/`.
- Untuk setup schema/fitur aplikasi, gunakan file di `01_schema_feature_migrations/` sesuai urutan tanggal nama file.
- Detail lengkap daftar file ada di `INDEX_SQL.txt`.
