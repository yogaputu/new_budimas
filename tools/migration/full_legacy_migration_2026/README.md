# Full Legacy Migration 2026

Folder ini mengumpulkan SQL migrasi data legacy dari awal sampai akhir.

## File Utama

- `00_run_all_legacy_migration_2026.sql`
  - File gabungan tunggal.
  - Bisa dijalankan langsung via `psql` atau tool SQL yang menerima multi-statement.
  - Setiap tahap masih mempertahankan `BEGIN` / `COMMIT` asli dari file sumber.

- `00_run_all_legacy_migration_2026_psql_runner.sql`
  - Runner khusus `psql` yang memanggil file di folder `steps`.
  - Lebih enak untuk debug per tahap.

## Urutan Tahap

1. `01_map_legacy_sales_2026_to_public.sql`
2. `02_map_legacy_sales_2025_ar_to_public.sql`
3. `03_map_legacy_payments_2026_to_public.sql`
4. `04_map_legacy_mobile_payments_2026_to_public.sql`
5. `05_map_legacy_purchase_2026_to_public.sql`
6. `06_map_legacy_retur_2026_to_public.sql`

## Syarat Sebelum Run

- Schema staging `legacy_dist_2026` sudah terisi.
- Schema staging `legacy_dist_2025_ar` sudah terisi untuk invoice AR 2025.
- Master customer, principal, produk, sales, plafon, dan mapping eksternal sudah siap.
- Jalankan di database target `budimas_dev` / `budimas-dev`.

## Contoh Run

```powershell
$env:PGPASSWORD='postgres'
& 'D:\laragon\bin\postgresql\postgresql-14.5-1\bin\psql.exe' `
  -h 127.0.0.1 -p 5432 -U postgres -d budimas-dev `
  -v ON_ERROR_STOP=1 `
  -f 'D:\laragon\www\budimas\new_budimas\tools\migration\full_legacy_migration_2026\00_run_all_legacy_migration_2026.sql'
```

Untuk server via SSH tunnel:

```powershell
$env:PGPASSWORD='postgres'
& 'D:\laragon\bin\postgresql\postgresql-14.5-1\bin\psql.exe' `
  -h 127.0.0.1 -p 15432 -U postgres -d budimas_dev `
  -v ON_ERROR_STOP=1 `
  -f 'D:\laragon\www\budimas\new_budimas\tools\migration\full_legacy_migration_2026\00_run_all_legacy_migration_2026.sql'
```
