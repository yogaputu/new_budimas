# Scaffold clean re-import BDM Solo + TMP Solo

Dokumen ini adalah rancangan implementasi **database paralel/blue-green**.
Tidak ada perintah di sini yang boleh dipakai untuk menghapus, menimpa, atau
menonaktifkan data pada database PostgreSQL produksi yang sekarang.

Tujuannya adalah membuat database ERP baru dengan provenance yang jelas untuk
setiap data dari SQL Server BDM Solo dan TMP Solo. SQL Server tetap read-only.

## Mengapa jalur ini diperlukan

Database `public` yang sekarang memiliki data lama tanpa `source_system` yang
tepercaya. Nomor `Nota` dapat sama pada BDM dan TMP, sehingga tidak ada dasar
aman untuk mengadopsi atau mengganti record lama berdasarkan nomor dokumen,
kode customer, atau `MIN(id)`.

Jangan gunakan sebagai basis clean import:

- `import_scope_to_postgres.py`;
- `map_legacy_sales_2026_to_public.sql`;
- folder `all_sql_migrasi_budimas_20260603` dan
  `full_legacy_migration_2026`.

Skrip-skrip tersebut adalah jalur legacy dan dapat mencari target global atau
berdasarkan dokumen yang tidak source-qualified.

## Baseline database baru

Backup lokal yang tersedia adalah `.tmp_audit/budimas_dev_local_20260603_*`.
Itu adalah snapshot Juni 2026, sedangkan schema/konfigurasi produksi dapat
sudah berubah. Folder `tmp-api-deploy` juga hanya deployment parsial. Keduanya
tidak boleh menjadi baseline cutover.

Bangun database baru dari **schema-only dump produksi saat ini**, kemudian
salin **hanya** tabel referensi yang diizinkan dari produksi saat ini. Cara
ini mempertahankan extension, fungsi, trigger, indeks, serta struktur schema
terkini tanpa menyalin customer, produk, transaksi, stok, piutang, atau data
legacy lama.

Preflight read-only wajib menghasilkan allow-list eksplisit untuk data
referensi, misalnya perusahaan, cabang, `perusahaan_cabang`, jabatan,
tipe-sales, tipe harga, status produk, PPN, wilayah, gudang/rak dan lookup
lain yang benar-benar dibutuhkan aplikasi. Jangan memakai `--data-only`
untuk seluruh `public`.

Urutan operasi nanti, setelah UAT disetujui, adalah:

1. `pg_dump --schema-only` dari database produksi ke artefak baseline
   bertanggal dan simpan checksum-nya.
2. Buat database baru dari `template0`; restore schema-only dump tersebut.
3. Restore data-only untuk allow-list referensi yang sudah direview.
4. Jalankan migration aplikasi yang belum tercakup schema dump, lalu audit
   `pg_catalog` (kolom, FK, unique index, trigger, sequence) terhadap
   database produksi.
5. Jalankan staging dan importer hanya ke database baru.

`CREATE DATABASE ... TEMPLATE <database produksi>` tidak dipilih sebagai
jalur utama karena ia akan menyalin seluruh data lama dan dapat gagal saat ada
koneksi aktif. Logical schema-only dump + allow-list referensi lebih mudah
direkonsiliasi dan dikembalikan.

## File baru yang diperlukan

Implementasi tidak boleh mengubah registry lama
`migration_bdm_tmp_202608`; buat jalur baru berikut.

| File | Tanggung jawab |
| --- | --- |
| `tools/migration/20260902_create_clean_import_registry.sql` | DDL schema `migration_clean_bdm_tmp_202609`, fungsi validasi, trigger provenance, dan tabel audit. |
| `tools/migration/20260902_extend_clean_import_registry_master_maps.sql` | Extension sekali-jalan **khusus target clean kosong**: memperbaiki identity map base+outer UOM dari satu STOK row dan menambah map provenance harga/plafon. |
| `tools/migration/bootstrap_clean_erp_database.sh` | Hanya orchestrator eksplisit untuk schema-only baseline + allow-list referensi; default dry-run dan wajib nama database target baru. |
| `tools/migration/import_clean_bdm_tmp_master.py` | Membuat master source-qualified dari staging final; tidak menghubungi SQL Server. |
| `tools/migration/import_clean_bdm_tmp_sales.py` | Membuat HJualSM/DJualSM kanonik, `faktur_detail`, dan registry dokumen/line dalam satu transaksi per batch. |
| `tools/migration/reconcile_clean_bdm_tmp.py` | Read-only count, total, UOM, document, FK, trigger, sequence, dan provenance reconciliation. |
| `tools/migration/clean_import_policy.json` | Satu konfigurasi versioned untuk sumber, kode perusahaan/cabang, prefix nomor, status policy, dan lookup referensi; tidak ada ID database tetap. |

File yang sudah tersedia adalah scaffold/guard untuk jalur clean; tidak satu
pun mengotorisasi write ke produksi. Semua phase tetap harus lolos dry-run,
backup, dan UAT sebelum target blue/green dipilih untuk cutover.

## DDL registry yang harus dibuat

Gunakan schema baru `migration_clean_bdm_tmp_202609`, bukan schema registry
yang terikat ke target lama. Nama kolom detail dapat mengikuti schema ERP
terkini, tetapi tabel berikut wajib ada.

| Tabel | Primary identity / isi minimum |
| --- | --- |
| `import_run` | `run_id`, `pipeline_version`, `phase`, `status`, `config_sha256`, snapshot metadata BDM/TMP, checksum allow-list baseline, waktu mulai/verifikasi/commit. |
| `source_context` | `source_system`, `target_company_code`, `target_branch_code`, `document_prefix`, serta ID hasil-resolusi (`target_company_id`, `target_branch_id`, `target_perusahaan_cabang_id`). |
| `customer_source_map` | `(source_system, source_customer_code_norm) -> id_customer`, source store-name normalized, metode (`tmp_created`, `bdm_shared_exact`, `bdm_created`), run id dan hash row. |
| `principal_source_map` | `(source_system, source_principal_code_norm) -> id_principal`, run id dan hash row. |
| `sales_source_map` | `(source_system, source_principal_code_norm, source_sales_code_norm) -> id_sales`, `id_user`, run id dan hash row. |
| `product_source_map` | `(source_system, source_principal_code_norm, source_sku_norm) -> id_produk`, run id dan hash row. |
| `product_uom_source_map` | `(source_system, principal, sku, uom_code_norm, source_level, source_factor) -> id_produk_uom`; menyimpan faktor dan level yang telah diverifikasi. |
| `sales_document_map` | `(source_system, source_table, source_nota_norm) -> id_sales_order, id_faktur, id_faktur_detail`; menyimpan staging id dan row hash. |
| `sales_document_line_map` | `(source_system, source_table, source_nota_norm, source_urut_norm) -> id_sales_order_detail`; menyimpan staging id dan row hash. |
| `import_hold` | Kunci sumber, phase, alasan hold terstruktur, JSON detail yang tidak memuat secret, dan `run_id`. |
| `reconciliation_result` | `run_id`, check name, expected/actual, severity, JSON fingerprint, dan timestamp. |

Indeks wajib pada seluruh foreign key, seluruh `(source_system, ..._norm)` dan
`import_hold(run_id, phase, reason)`. Semua map dokumen/line harus memiliki
unique constraint target yang relevan agar satu target tidak pernah diklaim
dua source identity.

### Fungsi dan guard yang wajib

`20260902_create_clean_import_registry.sql` harus menyediakan setidaknya:

1. `norm_migration_key(text) returns text` untuk `lower(btrim(...))`, dan
   menolak blank pada fungsi caller.
2. `resolve_source_context(source_system, company_code, branch_code,
   document_prefix)` yang mencari `public.perusahaan.kode`, lalu
   `public.cabang.kode`, kemudian tepat satu `public.perusahaan_cabang` untuk
   pasangan kedua ID tersebut. Cabang fisik dapat dipakai lintas perusahaan
   (misalnya Solo), sehingga kepemilikan default pada tabel `cabang` bukan
   dasar resolusi konteks. Fungsi gagal bila hasilnya nol atau lebih dari satu;
   fungsi tidak boleh menyisipkan relasi secara diam-diam.
3. `assert_*_map_scope()` trigger untuk customer/cabang, principal/perusahaan,
   sales/principal, produk/principal, dan UOM/produk/faktor. Tidak ada lookup
   global hanya melalui kode.
4. `assert_sales_document_scope()` trigger yang membuktikan sales order berada
   pada cabang konteks, faktur mengarah ke sales order yang sama, dan
   `faktur_detail` mengarah ke faktur, sales order, serta principal yang sama.
5. `begin_import_run(...)` yang mencatat checksum config dan dua staging
   final; batch dengan source hash berbeda tidak boleh dianggap idempoten.
6. `record_import_hold(...)` untuk semua baris ambigu/tidak lengkap; importer
   harus fail-closed, bukan memilih kandidat terdekat.

Contoh resolusi konteks yang benar (pseudocode SQL) adalah:

```sql
-- ID tidak pernah ditulis tetap seperti 508 atau 328.
SELECT migration_clean_bdm_tmp_202609.resolve_source_context(
  'bdm_solo_dist', 'BMM', 'SLO', 'BDM-SLO/'
);
SELECT migration_clean_bdm_tmp_202609.resolve_source_context(
  'tmp_solo_dist', 'TMP', 'SLO', 'TMP-SLO/'
);
```

Kode `BMM`, `TMP`, dan `SLO` tetap divalidasi terlebih dahulu pada database
baru; bila kode aktual berubah, konfigurasi policy yang diperbarui dan
checksum baru diperlukan. Hard-code numeric ID tidak boleh digunakan.

## Extension registry master maps

Setelah base registry DDL berhasil dan **sebelum ada master source-owned yang
ditulis**, jalankan extension berikut hanya pada database blue/green:

```sh
PGOPTIONS='-c migration_clean_bdm_tmp_202609.allow_ddl=acknowledge-clean-target \
  -c migration_clean_bdm_tmp_202609.baseline_schema_sha256=<dry-run-schema-sha> \
  -c migration_clean_bdm_tmp_202609.baseline_reference_sha256=<dry-run-reference-sha>' \
  psql -v ON_ERROR_STOP=1 -d <database_clean_baru> \
    -f tools/migration/20260902_extend_clean_import_registry_master_maps.sql
```

Extension tersebut menolak `budimas_dev`, template PostgreSQL, registry yang
sudah berisi UOM map, serta target yang master source-owned-nya sudah terisi.
Ia tidak membaca SQL Server dan tidak memasukkan data bisnis. Perubahan satu
constraint UOM hanya boleh dilakukan saat map tersebut kosong: identity lama
terlalu sempit karena satu STOK row dapat menjadi bukti untuk UOM base level 1
dan UOM outer level 2 sekaligus.

`product_price_source_map` memberi provenance untuk harga per kolom sumber dan
`plafon_source_map` memberi provenance plafon. Extension juga membuat
`clean_target_attestation`: marker immutable yang mengikat nama database
`budimas_clean_*` dengan fingerprint schema/reference hasil dry-run read-only.
Jalankan DDL hanya setelah memasukkan kedua fingerprint itu sebagai session
setting; importer menolak marker/fingerprint yang tidak cocok.

Plafon latest yang valid menyimpan limit/term sumber, tetapi target selalu
dibuat `sisa_bon=0` dan `lock_order='1'`. Itu keadaan non-live, bukan saldo
piutang/opening AR. Identitas kosong atau duplikat tetap menjadi hold.

## Aturan import master

Gunakan staging final terpisah dari `stage_august_2026_source.py`. Setiap
source system mempunyai schema staging sendiri dan metadata snapshot/freeze
yang sama-sama valid.

1. Muat data referensi ERP baseline terlebih dahulu.
2. Buat principal per sumber dan per perusahaan. Kode sama di BDM dan TMP
   bukan alasan untuk memakai principal lintas perusahaan.
3. Customer TMP dibuat terlebih dahulu. Customer BDM memakai customer TMP
   yang sama **hanya** apabila kode customer normalisasi dan nama toko
   normalisasi sama persis. Selain itu BDM membuat customer source-owned
   sendiri; kode tampilan diberi prefix bila target memakai uniqueness global.
   Tidak ada fallback nama terdekat maupun pilihan ID terkecil.
   Mapping legacy `OpsHarga` A-E ke `produk_tipe_harga.kode` harus berasal dari
   policy eksplisit yang direview. Audit read-only 2 September 2026 membuktikan
   `FP` bukan toggle PPN customer (nilai `T` dan `Y` sama-sama menghasilkan
   transaksi PPN 11%); karena itu source flag tersebut tidak boleh ditafsirkan
   berbeda per nilai. Hanya policy operasional eksplisit yang menetapkan semua
   customer sebagai PPN yang boleh memetakan kedua nilai ke `is_ppn=1`.
4. Buat sales tanpa akun login (`sales.id_user=NULL`) dari tipe sales yang
   dipetakan eksplisit. `Type` dipakai dahulu; hanya Type yang blank/tidak
   dipetakan boleh fallback ke `JenisITR`. Password SQL Server tidak pernah
   disalin. Migrasi akun user/login adalah fase post-UAT terpisah karena schema
   saat ini tidak memiliki flag disable/non-login yang dapat dibuktikan aman.
5. Buat produk per `(source_system, principal, SKU)`, lalu rantai
   `produk_uom` menggunakan kode/nama base source yang terverifikasi pada
   level 1/faktor 1, serta kode/nama outer source yang berbeda dan
   terverifikasi pada level 2/faktor `PerUnit > 1`. Tidak ada asumsi bahwa
   base harus PCS atau outer harus CT; nama dan kode source dipertahankan.
   Level 3 hanya boleh dibuat bila rantai faktor lengkap dibuktikan. Pada fase
   transaksi, invariant harus memakai base UOM termap
   (`base = outer × PerUnit + sisa_base`), bukan memaksakan konversi PCS;
   kegagalan invariant menjadi hold.
   Flag legacy `FakturPajak` harus lebih dahulu dipetakan eksplisit ke persen
   PPN target. Audit menunjukkan `YA -> 11%` kuat, tetapi `TIDAK` tidak sama
   dengan 0% (observasi TMP yang positif tetap 11%). Oleh sebab itu hanya
   policy operasional eksplisit yang menetapkan PPN 11% seragam boleh memetakan
   `YA` dan `TIDAK` ke 11; nilai blank tetap hold. Default PPN PostgreSQL bukan
   bukti bahwa source memakai nilai tersebut.
6. Buat harga dan plafon hanya setelah semua map di atas valid. Plafon memilih
   `TglAdd` terbaru; timestamp sama dengan nilai berbeda atau baris duplikat
   menjadi hold. Nilai `sisa_bon`/piutang aktif tidak pernah ditebak dari
   header penjualan.

Secara default importer master menolak `--apply` bila masih ada hold. Hanya
skip yang sudah disetujui secara eksplisit boleh berjalan: dry-run menghasilkan
envelope exact melalui `--write-hold-manifest`; reviewer mengisi identitas,
referensi, waktu, dan `approval_status=approved_skip`; lalu apply wajib
memasukkan file tersebut, SHA manifest, serta
`--acknowledge-approved-holds`. Manifest memuat seluruh identity/hash/alasan
hold dan dibandingkan ulang di transaksi serializable. Bila snapshot, policy,
atau plan berubah, approval menjadi tidak valid. Aksi yang bergantung pada row
hold dipangkas sebelum write dan seluruh skip dicatat di `import_hold` sebagai
`skipped`.

Sebelum apply, operator tetap wajib mereview `plan_sha256`, lalu
memasukkannya kembali bersama fingerprint baseline schema/reference. Pada
transaksi serializable importer mengunci stage/reference/registry dan
membangun ulang plan; perubahan sekecil apa pun membatalkan apply.

Candidate policy yang belum disetujui berada di `tools/migration/policy_drafts/`.
File dengan status selain `approval_status=approved` sengaja ditolak importer.
Draft customer/PPN yang terbukti tidak aman diberi status
`rejected_pending_business_rule`; jangan mengubahnya menjadi approved tanpa
aturan Finance yang baru. Tidak ada mapping harga, PPN, atau tipe sales yang
dipakai sebagai default diam-diam.

## Aturan import penjualan historis

Phase pertama hanya memakai keluarga kanonik `HJualSM` + `DJualSM`.
`HJualSMAndroid` dan `DJualSMAndroid` tetap dicatat sebagai hold sampai ada
aturan source-qualified yang membuktikan mereka bukan duplikasi.

Untuk satu dokumen, importer membuat secara atomik:

1. `public.sales_order` dengan nomor `BDM-SLO/<nota>` atau
   `TMP-SLO/<nota>`;
2. `public.faktur` dengan nomor prefix yang sama;
3. **satu `public.faktur_detail`** untuk `(faktur, sales_order, principal)`;
4. semua `public.sales_order_detail` yang source-qualified;
5. `sales_document_map` dan `sales_document_line_map` beserta hash sumber.

Importer baru tidak boleh menyalin perilaku
`apply_active_sales_source_aware.py`, karena tool itu belum membuat
`faktur_detail` dan sengaja tidak layak untuk replay histori delivered.

Sampai opening stock/HPP, saldo piutang, pembayaran, dan retur direkonsiliasi,
phase ini **tidak** boleh membuat `inventory_ledger`, picking, shipping,
manifest, kas/jurnal, pembayaran, retur, atau saldo piutang berjalan. Status
operasional historis harus dikendalikan policy eksplisit yang diuji terhadap
trigger ERP; tidak boleh menganggap `RL` otomatis aman untuk menulis ledger.
Karena itu database hasil phase ini adalah database UAT/historical sampai
baseline stok dan AR disetujui; belum layak untuk cutover produksi.

## Dry-run, rekonsiliasi, dan cutover

Dry-run harus menjalankan `REPEATABLE READ, READ ONLY` untuk semua laporan dan
memeriksa minimal:

- source header/detail count per BDM/TMP dan per principal;
- 1:1 map source-to-target, tanpa reused target;
- jumlah PCS/CT dan faktor UOM pada setiap detail;
- total, diskon, DPP, PPN, dan total faktur/detail;
- tepat satu `faktur_detail` per faktur/principal source;
- no_order/no_faktur prefix unik dan source nota asli tetap tersimpan;
- FK, user trigger, sequence, nullability, dan unique index pada target;
- semua hold terhitung dan diekspor, tidak disembunyikan.

Hanya setelah dry-run bersih, backup PostgreSQL baru tervalidasi, source
snapshot final tersedia, dan UAT disetujui, database baru dapat dipilih untuk
cutover. Cutover produksi memerlukan freeze singkat aplikasi/API/worker,
perubahan connection string yang dapat dibalik, smoke test, serta rollback
yang cukup dengan mengarahkan ulang ke database lama. Database lama tidak
diubah atau dihapus oleh proses ini.
