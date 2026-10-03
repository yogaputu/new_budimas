-- psql runner for the copied step files in ./steps
-- Use with: psql -v ON_ERROR_STOP=1 -f 00_run_all_legacy_migration_2026_psql_runner.sql

\\echo 01 Sales 2026 ke public
\\ir steps/01_map_legacy_sales_2026_to_public.sql

\\echo 02 Sales/AR 2025 tertahan ke public
\\ir steps/02_map_legacy_sales_2025_ar_to_public.sql

\\echo 03 Pembayaran dbayarsm 2026 ke public
\\ir steps/03_map_legacy_payments_2026_to_public.sql

\\echo 04 Pembayaran non-dbayarsm/mobile 2026 ke public
\\ir steps/04_map_legacy_mobile_payments_2026_to_public.sql

\\echo 05 Pembelian 2026 ke hutang pembelian
\\ir steps/05_map_legacy_purchase_2026_to_public.sql

\\echo 06 Retur sales 2026 ke retur request/CN
\\ir steps/06_map_legacy_retur_2026_to_public.sql

