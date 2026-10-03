# Allow-list baseline blue/green: BDM Solo + TMP Solo

Dokumen ini adalah checklist rancangan, bukan skrip yang dieksekusi. Semua perintah mutasi di bawah hanya boleh dijalankan pada database baru setelah backup tervalidasi, dry-run disetujui, dan nama target disahkan. Tidak ada perintah di sini yang mengubah SQL Server atau PostgreSQL produksi yang aktif.

## Keputusan baseline

Bangun database baru dari schema [public] produksi saat ini saja, lalu isi hanya tabel referensi pada allow-list. Jangan menduplikasi seluruh database dan jangan memakai CREATE DATABASE ... TEMPLATE budimas_dev: keduanya ikut membawa transaksi lama, stok, AR, dan mapping legacy tanpa provenance.

Schema non-public tidak ikut baseline. Pada audit 2026-09-02 terdapat [legacy_16], [legacy_18], banyak schema [legacy_bdm_*]/[legacy_tmp_*], [legacy_transaction_*], dan [migration_bdm_tmp_202608]. Semua itu staging atau audit lama, bukan kontrak aplikasi baru. Staging BDM/TMP clean harus dibangun ulang dari snapshot SQL Server read-only, bukan disalin dari schema tersebut.

Audit katalog membuktikan:

- tidak ada foreign key dari [public] ke schema non-public;
- tidak ada view [public] yang mereferensikan schema legacy/migration;
- search path database adalah "$user", public;
- extension yang terpasang hanya [plpgsql] pada pg_catalog;
- trigger aplikasi yang ditemukan di [public] memanggil fungsi [public.prevent_inventory_out_during_stock_opname], sehingga tercakup oleh dump schema [public].

Dump schema public tetap membuat definisi kosong dari 48 tabel bernama [backup_*], [legacy_*], dan rollback-audit yang berada di public. Itu aman karena tidak ada data yang direstore ke sana. Jangan drop tabel tersebut pada tahap baseline; pastikan importer clean tidak pernah menulis ke sana.

## Konteks organisasi terverifikasi

Nilai ID berikut hanya hasil audit, bukan nilai yang boleh di-hard-code pada importer:

| Source system | Perusahaan (kode) | Cabang (kode) | perusahaan_cabang audit saat ini |
| --- | --- | --- | ---: |
| BDM Solo | BMM | SLO | 508 |
| TMP Solo | TMP | SLO | 328 |

Catatan penting: record cabang SLO sendiri saat ini memiliki id_perusahaan=TMP. Relasi BDM-Solo yang benar ada di perusahaan_cabang. Resolver clean wajib mencari satu perusahaan berdasarkan kode, satu cabang berdasarkan kode, lalu tepat satu perusahaan_cabang. Jangan menjadikan cabang.id_perusahaan sebagai satu-satunya dasar scope dan jangan menulis ID 508/328 tetap.

## Allow-list data referensi

Berikut satu-satunya data dari public yang boleh dibawa melalui pg_dump --data-only pada baseline pertama. Count adalah hasil COUNT(*) produksi pada audit 2026-09-02 dan menjadi rekonsiliasi awal.

### A. Organisasi, geografi, dan akses aplikasi — salin

| Urutan | Tabel | Count audit | Alasan |
| ---: | --- | ---: | --- |
| 1 | wilayah1 | 34 | lookup geografi induk |
| 2 | wilayah2 | 514 | lookup geografi; bergantung logis pada wilayah1 |
| 3 | wilayah3 | 7,215 | lookup geografi; bergantung logis pada wilayah2 |
| 4 | wilayah4 | 80,534 | lookup geografi; bergantung logis pada wilayah3 |
| 5 | perusahaan | 3 | scope BMM/TMP/MPM |
| 6 | cabang | 5 | scope cabang dan konfigurasi alamat |
| 7 | perusahaan_cabang | 9 | relasi scope; FK formal ke perusahaan/cabang |
| 8 | departemen | 5 | lookup jabatan |
| 9 | jabatan | 22 | role aplikasi |
| 10 | fitur | 1,026 | definisi fitur/menu |
| 11 | jabatan_akses | 1,215 | matriks role-fitur |
| 12 | sales_tipe | 3 | lookup jenis sales |
| 13 | status | 4 | lookup status kunjungan |
| 14 | tipe_transaksi | 12 | lookup tipe transaksi |
| 15 | modul | 8 | metadata modul |
| 16 | fitur_mal | 34 | metadata fitur template jurnal, tanpa jurnal |
| 17 | source_modul | 34 | metadata sumber modul; FK formal ke modul |

Tidak ada trigger aplikasi pada tabel reference tersebut ketika diaudit. Hubungan tanpa FK tetap harus direstore dalam urutan tabel agar ID lookup konsisten.

### B. Lookup master aman — salin

| Urutan | Tabel | Count audit | Aturan |
| ---: | --- | ---: | --- |
| 18 | customer_tipe | 13 | lookup tipe customer, bukan customer |
| 19 | tipe_toko_customer | 3 | lookup tipe toko, bukan customer |
| 20 | produk_tipe_harga | 6 | lookup kelas harga |
| 21 | master_ppn | 2 | resolve berdasarkan kode, bukan ID tetap |
| 22 | produk_satuan | 32 | kamus satuan umum; produk_uom tetap dari source |
| 23 | produk_kategori | 7 | kamus UI; tidak mencocokkan produk lintas source |
| 24 | rute | 152 | konfigurasi rute |
| 25 | rute_cabang | 146 | relasi rute-cabang |
| 26 | armada_tipe | 12 | lookup jenis armada, bukan armada/driver |

Produk_kategori disalin sebagai kamus umum saja. Bila taxonomy SQL Server tidak ada atau ambigu, importer membuat/menahan taxonomy source-qualified dengan audit record; tidak boleh memilih nama terdekat atau ID terkecil.

### C. Bukan data-only baseline; impor dari source BDM/TMP

Tabel berikut tidak boleh diambil dari public lama. Mereka dibangun dari snapshot final SQL Server dengan key provenance (source_system, source key) dan registry clean baru:

- principal dan principal_special_rule;
- customer, customer_external_mapping, customer_product_rule;
- users untuk sales, sales, sales_detail, sales_principal_assignment, sales_supervisor_map, dan target sales;
- produk, produk_uom, produk_harga_jual, produk_brand, produk_subbrand, dan taxonomy produk bila dipakai source;
- plafon, plafon_jadwal, dan plafon_week.

Plafon khususnya tidak aman disalin karena memiliki sisa_bon, yaitu state piutang berjalan. Untuk histori, ambil plafon terbaru dari source sesuai kebijakan; jangan menebak saldo piutang aktif.

### D. Seed terpisah dan terkendali — bukan allow-list

| Area | Mengapa dikecualikan | Jalur sebelum cutover |
| --- | --- | --- |
| users dan users_akses | memuat password hash/token; ID dipakai data lama | buat satu admin UAT melalui proses aplikasi/seed yang disetujui; buat akun sales source-owned tanpa menyalin password SQL Server |
| coa, jurnal, rekening_perusahaan, pajak, accounting_entry | membawa saldo awal, rekening, jurnal, atau FK faktur | proyek baseline akuntansi dengan rekonsiliasi saldo |
| wms_rack_master | 7,046 baris memiliki status_rak dan source marker | seed layout fisik terpisah; hanya kolom lokasi/kapasitas yang direview, status diinisialisasi kosong |
| wms_stock_rak, pallet/task/ledger | state stok dan operasional | menunggu opening stock/HPP dan UAT WMS |
| armada, driver, helper | driver/helper bergantung user; data operasional | migrasi konfigurasi fleet setelah user map bersih |
| promo, voucher, canvas | mengacu ke customer, principal, produk, atau transaksi | rebuild setelah master clean tersedia dan scope disetujui |

### E. Dilarang disalin

Jangan restore data dari:

- seluruh schema legacy_*, migration_*, dan staging/audit lama;
- seluruh tabel backup_*, legacy_*, dan *_rollback_backup_* di public;
- sales_order*, faktur*, order_batch, setoran*, lph*, retur, payment, purchase, stock opname, inventory/stok ledger, WMS ledger/picking/loading/manifest/pallet, log, audit, notification, dan fleet event/GPS;
- stok, inventori, inventory_ledger, wms_stock_rak, wms_stock_ledger, atau state persediaan apa pun.

Dokumen HJualSM + DJualSM nantinya menghasilkan sales_order, sales_order_detail, faktur, dan satu faktur_detail per scope principal melalui importer clean. Itu bukan allow-list dan tidak boleh dianggap delivered/live sebelum opening stock, HPP, AR, payment, dan retur direkonsiliasi.

## Checklist perintah (tidak dieksekusi)

Contoh memakai placeholder, tanpa hostname, credential, password, atau connection string.

### 1. Preflight read-only

~~~
readonly PG_BIN=/www/server/pgsql/bin
readonly SOURCE_DB=budimas_dev
readonly TARGET_DB=budimas_clean_bdm_tmp_YYYYMMDD
readonly ARTIFACT_DIR=/path/approved/bluegreen-artifacts

"$PG_BIN/psql" -X -d "$SOURCE_DB" -v ON_ERROR_STOP=1 -c \
  "SELECT current_database(), version(), now();"
"$PG_BIN/pg_dump" --version
df -h "$ARTIFACT_DIR"
~~~

Pastikan tidak ada backup yang masih berjalan sebelum artefak dijadikan dasar keputusan. Backup/dump produksi harus lolos pg_restore --list, checksum, dan uji restore terpisah; file yang ada belum membuktikan backup dapat dipakai.

### 2. Ambil schema baseline saja

~~~
readonly SCHEMA_DUMP="$ARTIFACT_DIR/$SOURCE_DB-public-schema-YYYYMMDD.dump"

"$PG_BIN/pg_dump" \
  --format=custom --schema-only --schema=public \
  --no-owner --no-privileges \
  --file="$SCHEMA_DUMP" "$SOURCE_DB"
sha256sum "$SCHEMA_DUMP" > "$SCHEMA_DUMP.sha256"
"$PG_BIN/pg_restore" --list "$SCHEMA_DUMP" | sed -n '1,120p'

# template0 sudah memiliki schema public. Hilangkan hanya item CREATE SCHEMA
# dari TOC agar restore tidak gagal karena schema tersebut sudah ada.
readonly SCHEMA_TOC="$SCHEMA_DUMP.toc"
"$PG_BIN/pg_restore" --list "$SCHEMA_DUMP" \
  | sed '/ SCHEMA - public / s/^/;/' > "$SCHEMA_TOC"
~~~

Jangan memakai --clean, --create, atau dump seluruh database. Batas --schema=public disengaja agar schema staging/migration non-public tidak ikut. Filter TOC hanya diterapkan pada database target baru; ia tidak mengubah dump sumber.

### 3. Ambil reference data dengan allow-list eksplisit

~~~
readonly REF_DUMP="$ARTIFACT_DIR/$SOURCE_DB-reference-allowlist-YYYYMMDD.dump"
REF_TABLES=(
  --table=public.wilayah1
  --table=public.wilayah2
  --table=public.wilayah3
  --table=public.wilayah4
  --table=public.perusahaan
  --table=public.cabang
  --table=public.perusahaan_cabang
  --table=public.departemen
  --table=public.jabatan
  --table=public.fitur
  --table=public.jabatan_akses
  --table=public.sales_tipe
  --table=public.status
  --table=public.tipe_transaksi
  --table=public.modul
  --table=public.fitur_mal
  --table=public.source_modul
  --table=public.customer_tipe
  --table=public.tipe_toko_customer
  --table=public.produk_tipe_harga
  --table=public.master_ppn
  --table=public.produk_satuan
  --table=public.produk_kategori
  --table=public.rute
  --table=public.rute_cabang
  --table=public.armada_tipe
)

"$PG_BIN/pg_dump" \
  --format=custom --data-only --no-owner --no-privileges \
  "${REF_TABLES[@]}" \
  --file="$REF_DUMP" "$SOURCE_DB"
sha256sum "$REF_DUMP" > "$REF_DUMP.sha256"
"$PG_BIN/pg_restore" --list "$REF_DUMP" | sed -n '1,220p'
~~~

Jika archive tidak memuat SEQUENCE SET untuk sebuah tabel berserial, catat sebagai hold dan sinkronkan sequence hanya di target baru setelah membandingkan archive dan MAX(id) target. Jangan mengasumsikan nilai sequence.

### 4. Mutasi hanya sesudah persetujuan eksplisit

~~~
# Semua baris ini mengubah TARGET_DB baru, bukan SOURCE_DB.
"$PG_BIN/createdb" --template=template0 "$TARGET_DB"
"$PG_BIN/psql" -X -d "$TARGET_DB" -v ON_ERROR_STOP=1 \
  -c 'CREATE EXTENSION IF NOT EXISTS plpgsql;'
"$PG_BIN/pg_restore" --exit-on-error --single-transaction \
  --no-owner --no-privileges --use-list="$SCHEMA_TOC" \
  --dbname="$TARGET_DB" "$SCHEMA_DUMP"
"$PG_BIN/pg_restore" --exit-on-error --single-transaction --data-only \
  --no-owner --no-privileges --dbname="$TARGET_DB" "$REF_DUMP"
~~~

Setelah restore, audit table/kolom/constraint/FK/trigger/index/sequence dan count reference antara source/target. Baru buat registry clean, staging hasil extract SQL Server read-only, dan jalankan importer dry-run. Nama database target, owner, lokasi artefak, retensi backup, dan waktu cutover harus ada di change record sebelum blok mutasi.

## Acceptance gate sebelum importer master

1. perusahaan memuat BMM dan TMP; cabang memuat SLO; resolver membuktikan pasangan BMM/SLO dan TMP/SLO masing-masing tepat satu pada perusahaan_cabang.
2. Count semua tabel allow-list di target sama dengan source atau selisihnya tercatat/disetujui.
3. Tidak ada data users, customer, principal, produk, plafon, invoice, stock, ledger, WMS, backup, atau schema legacy pada target sebelum pipeline clean memasukkannya.
4. Admin UAT dibuat melalui jalur aman dan dapat login; password/token lama tidak disalin.
5. pg_restore --list dan checksum kedua dump tersimpan pada import run.
6. Registry clean me-resolve ID per run dari kode dan menyimpan source snapshot hash; tidak ada ID produksi yang di-hard-code.

Bila satu gate gagal, importer berhenti dan menulis import_hold. Ia tidak memilih kandidat terdekat dan tidak mengubah data produksi lama.
