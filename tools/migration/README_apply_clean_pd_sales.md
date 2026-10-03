# Apply PD sales ke UAT saja

`apply_clean_pd_sales.py` adalah penerap yang terpisah dari importer legacy.
Ia **tidak** menghubungi SQL Server dan tidak menggunakan skrip active-sales
lama. Mode bawaan selalu dry-run PostgreSQL `REPEATABLE READ, READ ONLY`.

Penerapan hanya mungkin dengan `--apply` pada database yang namanya memiliki
token UAT, misalnya `budimas_clean_20260902_v2_uat02`. Database baseline
`budimas_clean_20260902_v2`, `budimas_dev`, produksi, atau DSN dengan dbname
berbeda ditolak. Target juga harus memiliki attestation clean yang cocok dan
relation transaksi kosong; untuk percobaan ulang, buat clone UAT baru, jangan
menimpa/mengadopsi row yang sudah ada.

## Lingkup write

Apabila seluruh gate lolos, satu kandidat PD hanya membuat:

- satu `sales_order` draft (`status_order=0`);
- satu `faktur` draft numberless (`status_faktur=0`, `no_faktur=NULL`);
- tepat satu `faktur_detail`;
- detail `sales_order_detail` dengan booked/picked/shipped/delivered dan
  `subtotaldelivered` bernilai nol;
- `sales_document_map`, `sales_document_line_map`, hold **open**, hasil
  rekonsiliasi, serta `import_run` registry append-only.

Tidak ada write terhadap stok/HPP, picking, loading/shipping, pengiriman,
manifest/rute, pembayaran/AR, retur, credit note, atau saldo plafon.
`tanggal_faktur` dan `tanggal_terkirim` tetap `NULL`. Nomor nota sumber hanya
menjadi `no_order` yang sudah diberi prefix source; ia tidak pernah menjadi
`no_faktur`.

Komponen diskon nominal sumber dicatat ke `total_nilai_discount`. Diskon persen
sumber bersifat berantai, sehingga importer tidak menebak satu nilai persen:
`total_persen_diskon` diisi `0`; formula dan komponen mentah tetap ada pada
manifest review. Reviewer wajib mengakui keputusan ini di approval envelope.

## Dry-run dan template approval

Sebelum meminta approval, buat manifest read-only menggunakan
`report_clean_pd_sales_manifest.py` terhadap **database UAT yang sama**.
Kemudian jalankan applier tanpa `--apply`; ini merebuild manifest di snapshot
baru dan hanya berhasil bila report, plan, stage freeze, master map, baseline,
target ownership, serta jumlah hold masih persis sama.

```sh
python3 tools/migration/apply_clean_pd_sales.py \
  --dsn "$UAT_PG_DSN" \
  --target-database budimas_clean_20260902_v2_uat02 \
  --report-json outputs/pd_sales_manifest_uat.json \
  --bdm-stage-run-id 1 \
  --tmp-stage-run-id 1 \
  --write-approval-template outputs/pd_sales_uat_approval.json \
  --output outputs/pd_sales_uat_dry_run.json
```

Tidak ada row target atau registry yang ditulis oleh perintah di atas. Template
yang dihasilkan memiliki hash report/plan/policy/baseline/holds dan count yang
sudah terikat, termasuk `approved_apply_contract_sha256` untuk mapping target
dan file applier yang tepat. Isi hanya setelah peninjauan manusia:

- ubah `approval_status` ke `approved`;
- isi `approved_by`, `approval_reference`, dan `approved_at` ISO-8601 dengan
  timezone;
- pertahankan seluruh SHA, count, target database, dan
  `hold_disposition=record_open_do_not_import` apa adanya;
- ubah semua acknowledgement menjadi `true`.

Hold yang sudah disetujui tetap **tidak** diimpor. Ia hanya dicatat open pada
registry run sehingga tidak ada fallback atau penghapusan sumber diam-diam.
Template dasar tersedia di
`policy_drafts/clean_pd_sales_uat_approval.template.json`; gunakan output
dry-run sebagai template yang benar-benar terikat ke snapshot tersebut.

## Apply UAT eksplisit

Perintah berikut hanya dijalankan setelah dry-run baru dan approval JSON sudah
ditinjau. Ia membuka satu transaksi `SERIALIZABLE`, mengunci scope stage/master
dan registry, lalu merebuild plan sekali lagi sebelum write.

```sh
python3 tools/migration/apply_clean_pd_sales.py \
  --dsn "$UAT_PG_DSN" \
  --target-database budimas_clean_20260902_v2_uat02 \
  --report-json outputs/pd_sales_manifest_uat.json \
  --approval-json outputs/pd_sales_uat_approval.json \
  --bdm-stage-run-id 1 \
  --tmp-stage-run-id 1 \
  --import-key pd-uat-202608-final-r1 \
  --confirm-uat-apply I_APPROVE_PD_UAT_APPLY \
  --apply
```

Approval yang berbeda satu karakter SHA/count/baseline atau target akan ditolak.
Perubahan kode applier/planner/helper atau mapping target (termasuk perlakuan
diskon persen) juga mengubah apply-contract SHA dan wajib mendapat approval
baru.
Applier juga menolak user trigger bisnis yang belum direview; ia tidak pernah
menonaktifkan trigger maupun rewrite rule. `--import-key` bersifat unik dan provenance registry
tidak pernah memakai `ON CONFLICT` untuk mengadopsi dokumen lain.

Receipt committed dicetak sebagai JSON ke stdout. `--output` sengaja hanya
tersedia untuk dry-run: menulis file lokal sesudah commit bisa gagal dan
membuat operator salah mengira transaksi belum masuk lalu menjalankan ulang.

## Rekonsiliasi dan rollback

Sebelum commit, importer membuktikan jumlah SO/faktur/faktur-detail/detail,
map header/detail, tepat satu `faktur_detail` per dokumen, hold open, dan
bahwa tabel terlarang tidak berubah. Bila salah satu gagal, seluruh transaksi
serializable rollback—termasuk `import_run` dan semua evidence.

Setelah commit, jangan melakukan `DELETE` atau `UPDATE` manual terhadap
business row maupun registry append-only. Rollback aman setelah commit adalah
restorasi atau pembuatan ulang database UAT dari snapshot sebelum apply, lalu
perbaiki policy/source dan buat run baru. Ini tidak pernah mengubah SQL Server
atau database produksi.

## Smoke test lokal

```sh
python3 -m py_compile tools/migration/apply_clean_pd_sales.py
python3 tools/migration/apply_clean_pd_sales.py --self-test
python3 tools/migration/apply_clean_pd_sales.py --help
```

Smoke test tidak membuka koneksi database.
