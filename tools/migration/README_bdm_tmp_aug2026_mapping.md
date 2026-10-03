# Mapping aman BDM Solo dan TMP Solo — Agustus 2026

Folder ini mendukung migrasi bertahap dari dua SQL Server yang memakai kode
dan nomor dokumen yang dapat sama. Tidak ada skrip di sini yang boleh
menjalankan merge publik sebelum snapshot sumber final tersedia.

## Urutan kerja

1. Jalankan staging terpisah per source system dan lakukan rekonsiliasi
   read-only.
2. Buat file review dengan `export_august_2026_mapping_exceptions.py`.
3. Review `mapping_review_queue.csv` dan konfigurasi pada
   `used_product_uom.csv`.
4. Setelah kebijakan customer lintas cabang disetujui, buat registry dengan
   `20260827_create_bdm_tmp_source_aware_mapping_registry.sql`.
5. Masukkan hanya mapping yang sudah disetujui ke registry dengan
   `apply_approved_master_mappings.py`. Isi `decision` dengan
   `approve_exact`, `approve_manual`, atau `approve_created`; khusus customer
   yang berada di cabang lain gunakan `approve_cross_branch` secara eksplisit.
   Jalankan tanpa `--apply` untuk preflight, lalu ulangi dengan `--apply`
   setelah hasilnya benar. Registry memaksa source system,
   perusahaan/cabang, principal, produk, dan UOM sesuai target.
6. Staging ulang dari snapshot SQL Server yang konsisten pada jendela final,
   lalu rekonsiliasi ulang sebelum menulis `public`.

## Kebijakan customer yang sama

Gunakan aturan di `bdm_tmp_customer_merge_policy.json`:

- Customer yang sudah terpetakan ke customer PostgreSQL yang sama tidak dibuat
  duplikat.
- Untuk data master customer yang sama dari BDM dan TMP, **TMP menjadi sumber
  prioritas** dan nilainya menimpa nilai BDM.
- Data master BDM tidak dipakai sebagai fallback untuk customer yang sudah ada
  pada TMP; BDM tetap disimpan sebagai mapping sumber dan riwayat transaksi.
- Jika customer BDM sudah memiliki pasangan PostgreSQL yang terverifikasi,
  data master BDM boleh menimpa customer PostgreSQL tersebut. Bila target yang
  sama juga datang dari TMP, jalankan TMP terakhir sehingga data TMP menjadi
  hasil akhir.
- Untuk kandidat BDM yang ganda, pakai nama toko yang sama. Jika lebih dari
  satu kandidat memiliki nama toko sama, pilih `id_customer` paling kecil.
  Jika tidak ada kandidat nama toko yang sama—termasuk tidak ada kandidat sama
  sekali—lewati baris tersebut dan jangan masukkan ke PostgreSQL.
- Queue customer manual yang aktif hanya berasal dari TMP. Baris manual BDM
  bersifat referensi dan tidak boleh membuat atau memperbarui master customer.
- Jika identitas toko belum terverifikasi, tahan di review manual; jangan
  menimpa customer secara otomatis.
- Kebijakan ini tidak menggabungkan transaksi/riwayat; setiap transaksi tetap
  disimpan dengan identitas source system-nya.

## Yang tidak boleh dilakukan

- Jangan memakai skrip merge lama yang mengunci mapping pada `MIN(id)` atau
  hanya `nota`.
- Jangan menyatukan BDM dan TMP ke schema staging yang sama.
- Jangan menganggap `candidate_unique` pada CSV sebagai persetujuan otomatis.
- Jangan impor sales detail apabila `used_product_uom.csv` bukan `uom_ready`.

## Syarat cutover

SQL Server BDM dan TMP saat ini tidak menyediakan snapshot read-committed.
Final load harus memakai backup konsisten atau maintenance window/freeze
singkat; preview read-committed hanya layak untuk persiapan mapping.

### Jalur maintenance write-freeze yang terattestasi

Gunakan jalur ini hanya setelah operator benar-benar menghentikan **seluruh**
penulis pada dua sumber SQL Server: aplikasi ERP/mobile, SQL Agent/scheduler,
integrasi, import otomatis, dan sinkronisasi offline. Freeze harus mulai
sebelum staging BDM dimulai dan tetap aktif sampai staging TMP selesai dengan
status `completed`. Masa sepi saja bukan freeze dan tidak cukup.

Untuk setiap source, gunakan schema baru dan ID maintenance yang **sama**:

```bash
python3 tools/migration/stage_august_2026_source.py \
  --source bdm-solo --modules masters --tables Plafon \
  --start '2026-08-01 00:00:00' --end-exclusive '2026-09-01 00:00:00' \
  --apply-stage --schema legacy_bdm_solo_plafon_final_202608xx \
  --confirm-source-write-freeze I_CONFIRM_SOURCE_WRITES_ARE_FROZEN \
  --maintenance-window-id aug2026-bdm-tmp-01 \
  --source-lock-timeout-seconds 30

python3 tools/migration/stage_august_2026_source.py \
  --source tmp-solo --modules masters --tables Plafon \
  --start '2026-08-01 00:00:00' --end-exclusive '2026-09-01 00:00:00' \
  --apply-stage --schema legacy_tmp_solo_plafon_final_202608xx \
  --confirm-source-write-freeze I_CONFIRM_SOURCE_WRITES_ARE_FROZEN \
  --maintenance-window-id aug2026-bdm-tmp-01 \
  --source-lock-timeout-seconds 30
```

Flag konfirmasi tersebut memaksa mode
`maintenance_freeze_serializable`, bukan mengganti label sebuah preview. Tool
membuka satu transaksi SQL Server `SERIALIZABLE` untuk seluruh pembacaan dan
menetapkan batas tunggu lock; bila masih ada writer/lock yang bertabrakan,
staging gagal daripada membaca data sambil berubah. SQL Server hanya menerima
`SELECT`, `SET`, `BEGIN TRANSACTION`, `COMMIT`, atau `ROLLBACK` dari tool ini—
tidak ada `INSERT`, `UPDATE`, `DELETE`, `MERGE`, atau perubahan skema.

Namun transaksi tersebut tidak dapat membuktikan bahwa freeze operasional
benar-benar dipatuhi sebelum setiap tabel pertama kali dibaca. Karena itu,
jangan jalankan flag ini kecuali freeze sudah dikonfirmasi dan login migrasi
dibatasi ke izin baca. Jika salah satu tahap gagal/timeout, jangan gunakan
schema itu untuk merge; tetap tahan freeze, periksa writer yang tersisa, lalu
buat staging dengan nama schema baru. Alternatif yang lebih kuat tetap backup
SQL Server yang konsisten.

### Rekonsiliasi schema gabungan per sumber

Jika staging final memakai satu schema gabungan untuk BDM dan satu untuk TMP,
gunakan opt-in eksplisit berikut. Tiga argumen BDM harus menunjuk schema BDM
yang sama, tiga argumen TMP harus menunjuk schema TMP yang sama, dan kedua
schema tetap harus berbeda.

```bash
python3 tools/migration/reconcile_sales_finance_staging.py \
  --allow-shared-source-schema \
  --bdm-sales-schema <schema_bdm_final> \
  --bdm-payment-return-schema <schema_bdm_final> \
  --bdm-stock-opname-schema <schema_bdm_final> \
  --tmp-sales-schema <schema_tmp_final> \
  --tmp-payment-return-schema <schema_tmp_final> \
  --tmp-stock-opname-schema <schema_tmp_final> \
  --output /tmp/bdm-tmp-sales-finance-final-reconciliation.json

python3 tools/migration/reconcile_visit_purchase_staging.py \
  --bdm-schema <schema_bdm_final> \
  --tmp-schema <schema_tmp_final> \
  --output /tmp/bdm-tmp-visit-purchase-final-reconciliation.json
```

Kedua laporan tetap read-only dan selalu rollback. Untuk schema gabungan,
laporan sales/finance tetap menguji manifest dan provenance setiap tabel
sales, payment, retur, dan stock opname. Status `merge_input_eligible` hanya
berarti BDM dan TMP memiliki pasangan metadata konsisten: keduanya snapshot,
atau keduanya `maintenance_freeze_serializable` dengan window ID, attestation,
dan masing-masing transaksi sumber `SERIALIZABLE`. Status tersebut **bukan** izin merge;
persetujuan apply dan backup PostgreSQL tetap terpisah.

## Nomor dokumen target

Gunakan aturan di `bdm_tmp_document_numbering_policy.json`:

- BDM Solo: `BDM-SLO/<nota-asli>`
- TMP Solo: `TMP-SLO/<nota-asli>`

Nomor asli dan tabel asal tetap dicatat di registry dokumen. Dengan begitu
nota/faktur yang sama di kedua SQL Server tidak pernah saling menimpa di
PostgreSQL.

## Audit dan apply Plafon

Gunakan `report_staged_plafon_mapping_readiness.py` setelah staging master
BDM dan TMP serta mapping customer/principal/sales sudah selesai. Contoh:

```bash
python3 tools/migration/report_staged_plafon_mapping_readiness.py \
  --bdm-schema legacy_bdm_solo_master_lowtraffic_20260827 \
  --tmp-schema legacy_tmp_solo_master_lowtraffic_20260827
```

Skrip ini hanya membaca dua schema staging dan registry mapping. Ia tidak
membaca `public.plafon`, tidak membuat atau memperbarui plafon, dan hasilnya
selalu `non_final_policy_review_only`. Laporan menghitung kandidat triple
`customer/principal/sales` yang sudah mendapat mapping committed serta profil
kelengkapan/variasi field sumber tanpa menampilkan nilai sumber.

Kebijakan yang telah disetujui untuk apply adalah:

- principal ambigu tetap **skip/hold**;
- hanya triple customer–principal–sales yang sudah memiliki committed mapping
  yang boleh diproses;
- plafon target yang sudah ada diperbarui, plafon yang belum ada boleh dibuat;
- bila ada beberapa baris sumber untuk triple target yang sama, pilih
  `TglAdd` terbaru;
- timestamp terbaru yang sama tetapi nilai plafon/term berbeda tetap ditahan,
  karena tidak ada dasar yang aman untuk memilih BDM atau TMP secara acak.

Gunakan `apply_staged_plafon_source_aware.py` untuk dry-run terlebih dahulu:

```bash
python3 tools/migration/apply_staged_plafon_source_aware.py \
  --bdm-schema <schema_bdm_final> \
  --tmp-schema <schema_tmp_final>
```

Script ini menolak `--apply` bila salah satu staging masih
`completed_preview`/`read_committed_preview`; preview tetap bisa dipakai untuk
melihat jumlah rencana dan hold. Apply final hanya menerima dua staging
`snapshot`, atau dua staging `maintenance_freeze_serializable` yang memiliki
`maintenance_window_id` sama serta metadata attestation dan transaksi
`SERIALIZABLE` lengkap. Setelah staging final, backup PostgreSQL, dan hasil
dry-run disetujui, jalankan dengan `--apply`.

Pemetaan yang aman adalah `Plafon → limit_bon` dan `Term → top`, `tempo`,
serta `tempo_label`. Pada update, `sisa_bon` **tidak di-reset**: pemakaian
kredit yang sudah ada dipertahankan dengan menyesuaikan selisih limit. Nilai
legacy `Lock1` tidak otomatis diubah ke `lock_order` target karena `X/x/1`
tidak mempunyai arti target yang sudah terverifikasi. Untuk plafon baru,
script hanya membuat record bila field wajib target mempunyai default/nilai
turunan yang aman. Bila `id_tipe_harga` atau `lock_order` wajib tetapi tidak
mempunyai default, masukkan kebijakan eksplisit misalnya:

```bash
python3 tools/migration/apply_staged_plafon_source_aware.py \
  --bdm-schema <schema_bdm_final> \
  --tmp-schema <schema_tmp_final> \
  --new-row-price-type-id <id_tipe_harga> \
  --new-row-lock-order <0-atau-1> \
  --apply
```

Saat apply, script mengunci hanya `public.plafon` selama transaksi PostgreSQL
singkat agar pengecekan record baru tidak berpacu dengan edit ERP. Ia tidak
menghubungi atau mengubah SQL Server. Semua selection dan hold tercatat pada
schema `migration_bdm_tmp_202608`.

## Kebijakan global transaksi aktif: exact atau skip

Untuk seluruh sisa adopsi/migrasi transaksi aktif, gunakan kebijakan
[`bdm_tmp_active_transaction_policy.json`](bdm_tmp_active_transaction_policy.json):

- hanya kecocokan source–target yang **exact 1:1** dan memenuhi seluruh
  prasyarat modul yang boleh diproses;
- ambigu, tidak ditemukan, mapping tidak lengkap, mismatch header/detail,
  atau lifecycle belum terbukti = **skip dan audit**;
- tidak ada fallback nama/kode terdekat, overwrite target, atau mutasi
  stok/HPP/kas/jurnal dari data yang belum proven.

Kebijakan ini berlaku untuk tahap yang tersisa. Master dan arsip historis yang
sudah selesai tidak diubah mundur.

## Transaksi aktif: kunjungan—dry-run dan adopsi dulu; pembelian hold UOM

Pilihan **transaksi aktif** tidak berarti setiap tabel source boleh langsung
menulis stok atau hutang. Untuk data Agustus ini, `KunjunganSales` adalah jalur
aktif yang dapat dibuktikan lebih dahulu: ia hanya membuat
`public.sales_kunjungan` dan `public.sales_kunjungan_detail`. Tidak ada stok,
piutang, hutang, jurnal, atau jadwal call-plan palsu yang dibuat.

Namun pada target saat review Agustus 2026 sudah ada **14.690** kunjungan
Agustus tanpa source-qualified registry map. Karena target tidak menyimpan ID
kunjungan BDM/TMP dan timestamp/status dari import lama dapat ternormalisasi,
hasil dry-run `9.390` kandidat insert **bukan** izin untuk memasukkan data.
Tool sekarang menolak apply baru selama masih ada visit target pada rentang
tanggal source. Buat terlebih dahulu manifest adopsi 1:1
`source_system + legacy visit ID -> sales_kunjungan + detail`, dengan:

- exact header dan detail yang unik boleh diusulkan untuk adopsi;
- kandidat toleransi/ambigu harus direview manual;
- kandidat yang benar-benar baru hanya boleh diinsert setelah target lama
  diklasifikasikan sebagai tidak terkait.

Gunakan dry-run setelah staging final, backup PostgreSQL, dan Plafon sudah
tersedia:

```bash
python3 tools/migration/apply_staged_visits_active_source_aware.py \
  --bdm-schema <schema_bdm_final> \
  --tmp-schema <schema_tmp_final> \
  --batch-id active_visit_source_aware_final_20260830
```

Setelah manifest adopsi disetujui, hasil hold direview, staging final, backup
PostgreSQL tervalidasi, dan penulisan ERP target benar-benar di-freeze, apply
memerlukan dua konfirmasi eksplisit:

```bash
python3 tools/migration/apply_staged_visits_active_source_aware.py \
  --bdm-schema <schema_bdm_final> \
  --tmp-schema <schema_tmp_final> \
  --batch-id active_visit_source_aware_final_20260830 \
  --apply \
  --confirm-active-visit-import I_CONFIRM_ACTIVE_VISIT_IMPORT \
  --confirm-target-erp-write-freeze I_CONFIRM_TARGET_ERP_WRITE_FREEZE
```

Tool mengharuskan mapping customer–principal–sales yang committed, user sales
yang masih sesuai perusahaan/cabang, dan tepat satu Plafon target. Identitas
visit adalah `(source_system, legacy visit ID)`, sehingga ID BDM dan TMP yang
sama tidak pernah bertabrakan. Rerun dengan payload sama adalah idempotent;
payload yang berubah atau ID source ganda ditahan. Lokasi source disimpan
hanya sebagai metadata audit registry karena belum ada kolom target ERP yang
terverifikasi untuk menimpa lokasi kunjungan.

## Transaksi aktif: sales order/faktur (rekonsiliasi dulu, dry-run default)

`apply_active_sales_source_aware.py` adalah jalur baru untuk keluarga kanonik
`HJualSM` + `DJualSM`. Ia **tidak menghubungi SQL Server**, dan tanpa `--apply`
ia selalu melakukan dry-run/rollback PostgreSQL. Nomor target baru memakai
prefix `LEG-BDM-HJ-` atau `LEG-TMP-HJ-` plus fingerprint identitas sumber;
identitas teknis tetap lengkap di
`migration_bdm_tmp_202608.sales_document_map`:
`source_system + HJualSM + Nota-normalized`.

Sebelum membaca satu transaksi, tool mewajibkan mapping committed
customer/principal/sales/product/UOM serta membuktikan persis rumus sumber:

`Jumlah = Unit × PerUnit + Satuan`

UOM PCS harus faktor 1 dan UOM luar harus memiliki kode serta faktor yang
identik di registry. Ambigu, produk/UOM tidak dikenal, kuantitas pecahan,
total header-detail tidak sama, dan status sumber yang tidak dapat dibuktikan
semuanya menjadi hold.

Karena dokumen standar kemungkinan sudah pernah dibuat oleh script lama
dengan `no_order`/`no_faktur` berupa Nota mentah tanpa provenance, dry-run
juga mencari kecocokan Nota mentah di target. Kecocokan tersebut ditahan
sebagai `unprovenanced_legacy_target_document_candidate`—bukan otomatis
diadopsi dan bukan dibuat ulang. Raw Nota tidak cukup membedakan BDM dari TMP.
Adopsi hanya boleh dilakukan melalui manifest review terpisah yang membuktikan
source system, customer/principal/sales/plafon, status, faktur, dan semua
detail (produk, harga, CT/PCS) satu-banding-satu. Sampai manifest tersebut
disetujui, tool tidak akan menulis provenance ke dokumen lama.

Contoh review lokal/target PostgreSQL (tidak ada `--apply`):

```bash
python3 tools/migration/apply_active_sales_source_aware.py \
  --bdm-schema <schema_bdm_final> \
  --tmp-schema <schema_tmp_final> \
  --batch-id active_sales_source_aware_review_20260830 \
  --output /tmp/active-sales-review.json
```

Keluarga `HJualSMAndroid`/`DJualSMAndroid` selalu di-hold pada tahap ini,
karena banyak baris sudah memiliki `NoFaktur` dan berisiko merupakan tampilan
atau duplikasi dokumen standar. Pembayaran `Terbayar` dicatat sebagai audit,
tetapi faktur tidak ditandai lunas sebelum alokasi kuitansi source-aware
diselesaikan.

Status `RL` (terkirim) juga di-hold secara default. Sumber sales tidak
memuat HPP historis; `ledger_zero_cost` sengaja **dinonaktifkan total** sampai
opening-stock/inbound dan HPP historis direkonsiliasi. Dengan demikian
pengiriman lama tidak diproses ulang oleh alur picking/shipping ERP dan tidak
menimbulkan mutasi ganda. Status `BT` pun hold sampai lifecycle pembatalan
target telah dibuktikan—nilai `status_order=-1` dari script lama tidak dipakai.

Jika tahap write nantinya dibuka, `--apply` tetap membutuhkan konfirmasi
maintenance window ERP eksplisit. Tool memeriksa setiap user trigger pada
`public.sales_order`, `public.faktur`, dan `public.sales_order_detail`; adanya
trigger user yang belum memiliki allow-list side-effect ter-review membuat
apply gagal. Ini mencegah direct SQL memicu mutasi stok/piutang tersembunyi,
mengunci tabel transaksi, atau melewati invariant aplikasi secara diam-diam.

`HPembelian`/`DPembelian` **belum** boleh menjadi transaksi pembelian aktif.
Empat field kuantitas source (`unit`, `perunit`, `satuan`, `jumlah`) hanya
berupa nilai raw dan tidak membuktikan kode UOM, level, faktor konversi, harga
per-UOM, atau apakah status pembelian berarti PO/penerimaan/selesai. Jangan
pakai `map_legacy_purchase_2026_to_public.sql` lama: skrip itu memilih UOM
target terdekat dan dapat membuat angka stok salah.

Laporan `reconcile_visit_purchase_staging.py` kini mengeluarkan
`active_purchase_import_readiness` yang selalu hold sampai bukti berikut
tersedia dan disetujui:

- arti field qty/harga DPembelian per source;
- mapping exact UOM per source–principal–SKU dan bukti `qty_uom × faktor = PCS`;
- arti `HPembelian.stnota` terhadap lifecycle ERP;
- data penerimaan aktif yang cukup (batch, expired, gudang/rak, dan qty terima),
  atau kebijakan eksplisit bahwa tidak ada mutasi stok;
- rekonsiliasi tagihan, total/retur/diskon/PPN/jatuh tempo dan prefix nomor
  dokumen `BDM-SLO`/`TMP-SLO`.

Sampai itu ada, pembelian tetap berada di staging/review—bukan dimasukkan ke
`purchase_transaksi`, inventory ledger, WMS, atau hutang aktif.

## Stock Opname historis (PCS/base, tanpa adjustment stok)

`StokOpnameAndroid` dari SQL Server hanya membawa jumlah fisik per produk:
`Id`, `IDKunjungan`, kode customer/principal/sales/produk, `StokOpname`, dan
tanggal. Tidak ada nilai stok sistem, Good/Bad, rak, batch, harga historis,
atau jenis baris yang cukup untuk membuat penyesuaian inventori dengan aman.

Karena itu jalur migrasinya **bukan** ke `public.stock_opname` maupun
`public.stock_opname_detail`. Kedua tabel tersebut saat ini dapat dibaca oleh
`InventoryLedgerService.backfill_stock_opnames()` sebagai adjustment. Data
legacy diarsipkan terpisah ke `migration_bdm_tmp_202608` dengan status tetap
`historical_import`, sehingga tidak dapat membuat mutasi `inventory_ledger`,
WMS stock, jurnal, atau perubahan stok tersedia.

Kebijakan kuantitas yang dipakai:

- `StokOpname` dibaca sebagai jumlah fisik **PCS/base** yang harus berupa
  integer tidak negatif; angka pecahan/negatif ditahan.
- Good, Bad, stok sistem, harga, rak, dan batch tetap `NULL`/unknown. Nilai
  tersebut tidak ditebak dari stok fisik lama.
- Tampilan `CT + PCS` hanya tersedia jika source-specific
  `product_uom_map` yang sudah committed membuktikan tepat satu UOM base
  faktor 1 dan tepat satu UOM `CT` exact pada level 2 **atau** level 3. Jika
  tidak, jumlah tetap ditampilkan PCS saja tanpa konversi perkiraan.
- Principal ambigu, mapping customer/sales/produk yang belum committed,
  source record ID ganda, dan produk ganda dalam satu `IDKunjungan` ditahan.
  Satu visit diperlakukan all-or-nothing agar tidak tersimpan sebagai opname
  yang tampak lengkap padahal ada produk yang terlewat.

Pasang DDL archive satu kali (DDL ini tidak memindahkan data dan tidak
menyentuh tabel `public`):

```bash
psql -v ON_ERROR_STOP=1 \
  -f tools/migration/20260828_create_historical_stock_opname_archive.sql
```

Review terlebih dahulu dengan dry-run. Preview read-committed boleh dipakai
hanya untuk melihat hold/rencana, tidak untuk apply:

```bash
python3 tools/migration/apply_historical_stock_opname_archive.py \
  --bdm-schema legacy_bdm_solo_stock_opname_preview_20260827 \
  --tmp-schema legacy_tmp_solo_stock_opname_preview_20260827
```

Sesudah sumber dipastikan snapshot konsisten **atau** kedua staging berasal
dari maintenance write-freeze yang terattestasi dengan
`maintenance_window_id` sama, PostgreSQL sudah dibackup, dan hasil dry-run
disetujui, apply archive membutuhkan dua flag eksplisit:

```bash
python3 tools/migration/apply_historical_stock_opname_archive.py \
  --bdm-schema <schema_bdm_final> \
  --tmp-schema <schema_tmp_final> \
  --batch-id stock_opname_historical_final_20260828 \
  --apply --confirm-historical-archive
```

Script menolak `--apply` untuk `completed_preview`,
`read_committed_preview`, dan mode lain yang tidak dapat dibuktikan. Selain
pasangan `snapshot`, satu-satunya jalur non-snapshot yang diterima adalah dua
`maintenance_freeze_serializable` dengan window ID sama, attestation, waktu
konfirmasi, transaksi sumber `SERIALIZABLE`, dan lock timeout positif.
Setiap batch menulis audit run, action, dan hold. Rerun dengan source visit
dan payload yang sama dicatat sebagai `unchanged_existing_archive`; payload
yang berbeda ditahan, bukan menimpa arsip lama.

## Pembayaran aktif dan retur: batas aman

Transaksi pembayaran dan retur mempunyai dampak piutang, kas, Credit Note,
dan stok. Karena itu keduanya tidak memakai skrip legacy satu-sumber. Pasang
DDL source-aware berikut sekali terlebih dahulu:

```bash
psql -v ON_ERROR_STOP=1 \
  -f tools/migration/20260830_create_active_payment_return_import.sql
```

`apply_staged_active_payment_return.py` hanya dapat membuat pembayaran aktif
pada tingkat **piutang** untuk pasangan `HBayarSM` + `DBayarSM` yang seluruhnya
terbukti exact. Ia membuat `setoran_customer` dan memperbarui status faktur,
tetapi sengaja tidak membuat `setoran`, jurnal kas/bank, atau perubahan
`plafon.sisa_bon`. Hal ini mencegah kas/bank dan piutang dihitung dua kali
ketika jalur penerimaan kas legacy belum memiliki akun dan status finalisasi
yang terverifikasi.

Syarat tiap kuitansi:

- nomor kuitansi unik dalam source;
- total header sama persis dengan jumlah semua alokasi `DBayarSM`;
- hanya satu metode yang dapat dibuktikan (`Cash` atau `NonCash`), bukan
  campuran/`Lain`;
- customer, invoice, sales order, dan faktur target semuanya exact melalui
  registry source-aware serta berada di perusahaan/cabang yang tepat;
- saldo faktur tidak boleh terlampaui setelah memperhitungkan pembayaran dan
  voucher target yang sudah ada;
- tidak ada retur source yang belum terselesaikan pada nota tersebut;
- payload source yang telah diimpor sebelumnya harus sama persis agar rerun
  tetap idempotent.

`Pembayaran` ditahan terlebih dahulu karena status/metode pembayarannya belum
memiliki arti final yang disetujui dan dapat menyalin kuitansi `HBayarSM`.
Pada kondisi target saat ini, `sales_document_map` sumber belum terisi karena
sales lama menunggu manifest adopsi; akibatnya dry-run pembayaran yang benar
memang menghasilkan nol alokasi eligible, bukan memasukkan piutang secara
paksa.

Dry-run final:

```bash
python3 tools/migration/apply_staged_active_payment_return.py \
  --bdm-sales-schema <schema_bdm_final> \
  --tmp-sales-schema <schema_tmp_final> \
  --bdm-payment-return-schema <schema_bdm_final> \
  --tmp-payment-return-schema <schema_tmp_final> \
  --batch-id active_payment_return_final_20260830 \
  --output /tmp/active-payment-return-review.json
```

Setelah backup PostgreSQL diverifikasi dan hasil hold direview, apply piutang
memerlukan konfirmasi eksplisit:

```bash
python3 tools/migration/apply_staged_active_payment_return.py \
  --bdm-sales-schema <schema_bdm_final> \
  --tmp-sales-schema <schema_tmp_final> \
  --bdm-payment-return-schema <schema_bdm_final> \
  --tmp-payment-return-schema <schema_tmp_final> \
  --batch-id active_payment_return_final_20260830 \
  --apply-payments \
  --confirm-active-payment-receivable-import
```

`--apply-payments` menolak preview dan mensyaratkan seluruh staging sales dan
payment/return final. Jika sales dan payment menggunakan schema berbeda,
keduanya wajib berasal dari maintenance freeze yang sama; schema gabungan
final per source adalah pilihan paling sederhana.

Retur tidak pernah diaktifkan otomatis oleh tool ini. `HReturSM` dan
`DReturSM` tidak membuktikan pembagian Good/Bad, arti UOM/`Unit`/`Satuan`,
status lifecycle target, referensi detail sales asal, atau kebijakan CN dan
stok. Setelah aturan tersebut telah disahkan, data hold dapat direkam tanpa
menyentuh tabel publik dengan `--record-return-preflight`; sampai saat itu
retur tidak boleh dimasukkan ke `retur_request`, `credit_note`, stok, ledger,
atau jurnal.
