# Import SQL Server Lama ke PostgreSQL Baru

Paket ini dibuat untuk import bertahap berdasarkan scope operasional:

- Per cabang: `Customer.KodeArea` SQL Server dipetakan ke `cabang.id` PostgreSQL.
- Per perusahaan: `Principle.Kode` SQL Server dipetakan ke `principal.id_perusahaan` PostgreSQL.
- Per sales: `Sales.Kode` dan `Plafon.KodeSales` SQL Server dipakai untuk membatasi data.

Untuk database SQL Server `DIST` yang sedang dipakai saat ini, asumsi UAT adalah:

- Semua data sumber masuk ke `Cabang SOLO` (`id_cabang = 5`).
- Semua data sumber masuk ke `PT Budimas Makmur Mulia` (`id_perusahaan = 1`).
- `Customer.KodeArea` tetap disimpan untuk audit, tetapi tidak menentukan cabang target.

## 1. Audit Yang Sudah Dibuat

Hasil audit ulang tersimpan di:

```text
.tmp_audit/sqlserver_to_postgres/
```

File penting:

- `old_area_counts.csv`: jumlah customer per area SQL Server.
- `old_principal_counts.csv`: principal lama dan jumlah plafon/sales.
- `old_sales_counts.csv`: sales lama dan principal-nya.
- `old_plafon_scope_counts.csv`: kombinasi area-principal-sales dari plafon lama.
- `pg_branch_company.csv`: cabang PostgreSQL.
- `pg_principal_company.csv`: principal PostgreSQL dan perusahaan.
- `pg_sales_codes.csv`: sales PostgreSQL dan kode sales.

## 2. Edit Config Scope

Copy file contoh. Untuk asumsi SQL Server `DIST` satu cabang/satu perusahaan, pakai template:

```powershell
Copy-Item .\tools\migration\scope_solo_bmm_all_sales_template.json .\tools\migration\scope_solo_bmm_sales_017.json
```

Edit `sales_codes` untuk import bertahap. `area_codes` dan `principal_codes` boleh dikosongkan kalau ingin mengambil seluruh area/principal dari SQL Server, tetapi tetap masuk ke `id_cabang = 5` dan `id_perusahaan = 1`.

Contoh import per sales:

```json
{
  "scope_name": "solo_bmm_et_sales_017",
  "branch": {
    "id_cabang": 5,
    "kode_cabang": "SLO",
    "area_codes": ["SLS", "SLU", "KTS", "SKH", "KRA", "BYL", "SRG", "GML"]
  },
  "company": {
    "id_perusahaan": 1,
    "kode_perusahaan": "BMM",
    "principal_codes": ["ET"]
  },
  "sales_codes": ["017"],
  "include_inactive": false
}
```

Jika `sales_codes` kosong, export akan mengambil semua sales pada principal scope tersebut.

## 3. Export Dari SQL Server

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\migration\export_sqlserver_scope.ps1 `
  -ConfigPath .\tools\migration\scope_solo_bmm_et.json `
  -Password "<PASSWORD_SQLSERVER>"
```

Output akan masuk ke:

```text
.tmp_audit/sqlserver_scope_exports/<scope_name>/
```

Isi output:

- `customers.csv`
- `principals.csv`
- `sales.csv`
- `plafon.csv`
- `products.csv`
- `metadata.json`

## 4. Dry-run Import ke PostgreSQL

Jalankan dry-run dulu. Dry-run akan rollback otomatis.

```powershell
D:\laragon\bin\python\python-3.10\python.exe .\tools\migration\import_scope_to_postgres.py `
  --input-dir .tmp_audit\sqlserver_scope_exports\solo_bmm_et_sales_017
```

Untuk ikut import produk:

```powershell
D:\laragon\bin\python\python-3.10\python.exe .\tools\migration\import_scope_to_postgres.py `
  --input-dir .tmp_audit\sqlserver_scope_exports\solo_bmm_et_sales_017 `
  --include-products
```

Untuk test cepat:

```powershell
D:\laragon\bin\python\python-3.10\python.exe .\tools\migration\import_scope_to_postgres.py `
  --input-dir .tmp_audit\sqlserver_scope_exports\solo_bmm_et_sales_017 `
  --limit-customers 50 --limit-sales 10 --limit-plafon 100 --limit-products 20 --include-products
```

## 5. Apply Import

Jika hasil dry-run sudah aman:

```powershell
D:\laragon\bin\python\python-3.10\python.exe .\tools\migration\import_scope_to_postgres.py `
  --input-dir .tmp_audit\sqlserver_scope_exports\solo_bmm_et_sales_017 `
  --include-products `
  --apply
```

## Catatan Penting

- Jangan import satu cabang besar langsung sebelum dry-run per sales/principal lolos.
- `principal` diinsert berdasarkan `kode + id_perusahaan`.
- `customer` diinsert berdasarkan `kode`.
- `sales` akan membuat `users`, `sales`, `sales_detail`, dan `sales_principal_assignment`.
- `plafon` dibuat jika customer, principal, dan sales sudah bisa dipetakan.
- `produk` bersifat opsional. Jika dipakai, script juga membuat UOM level 1 dan harga jual dasar agar produk baru tidak langsung error di transaksi.
- Cabang PostgreSQL saat audit masih `id_perusahaan = null`, jadi filter perusahaan tetap lebih aman ditentukan dari principal/perusahaan, bukan dari kolom cabang saja.
