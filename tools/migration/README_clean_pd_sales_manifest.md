# PD sales manifest (review-only)

`report_clean_pd_sales_manifest.py` membuat manifest JSON immutable untuk
kandidat transaksi penjualan **PD** dari snapshot BDM Solo dan TMP Solo yang
sudah dibekukan. Ini bukan importer dan tidak memiliki opsi `--apply`.

## Batas aman

- Hanya `HJualSM` + `DJualSM` kanonik dan status header tepat `PD`.
- Sesi PostgreSQL memakai `REPEATABLE READ, READ ONLY` dan target wajib
  bernama `budimas_clean_*` pada DSN maupun `--target-database`.
- SQL Server tidak dihubungi.
- `no_faktur`, `tanggal_faktur`, dan `tanggal_terkirim` selalu `null` pada
  mapping draft. Tidak ada delivery, picking, stok/HPP, pembayaran/AR,
  retur, manifest, atau rute.
- Policy PD tetap `approval_status: draft`; ia boleh dipakai untuk **report**,
  tetapi tidak pernah merupakan otorisasi write.
- Snapshot yang diterima hanya freeze serializable yang ter-attest bersama:
  maintenance window `aug2026-bdm-tmp-20260830-01`, rentang
  `[2026-08-01T00:00:00, 2026-09-01T00:00:00)`, `HJualSM` selector tanggal
  `Tanggal`, dan `DJualSM` child selector `Nota`. Selector lain ditolak.
- `TglAdd`, `TglPK`, `TglReal`, dan `TglBatal` dicatat sebagai audit saja;
  timestamp default tidak dianggap bukti pengiriman/pembatalan. Jika tersedia,
  `UserPK`, `UserReal`, `StTranfer`, `UserBatal`, atau `KetBatal` yang terisi
  menjadi hold source-qualified.
- Diskon persen ditinjau sebagai formula berantai, bukan penjumlahan persen:
  `gross × (1−Disc1/100) × (1−Disc2/100) × (1−Disc3/100)`, dengan komponen
  nominal `DiscRp`, `DiscRp1`, `DiscRp2`, dan `DiscRp3`. Rekonsiliasi total
  header/detail memakai toleransi Rp0,05; report tidak menghitung ulang atau
  mem-posting nilai finansial target.

## Menjalankan dry-run

Jalankan dari folder repository dengan DSN yang menunjuk eksplisit ke target
clean, misalnya:

```sh
python3 tools/migration/report_clean_pd_sales_manifest.py \
  --dsn "$CLEAN_PG_DSN" \
  --target-database budimas_clean_20260902_v2 \
  --bdm-stage-run-id 1 \
  --tmp-stage-run-id 1 \
  --output outputs/20260902_clean_import/pd_sales_manifest_20260902.json
```

`$CLEAN_PG_DSN` harus mengandung `dbname=budimas_clean_20260902_v2`; skrip
menolak DSN yang kosong, berbeda, atau mengarah ke produksi. Nama output tidak
boleh digunakan ulang untuk report yang berbeda. Bila report identik sudah
ada, skrip hanya mengonfirmasinya tanpa menimpa file.

Test lokal tanpa database:

```sh
python3 -m py_compile tools/migration/report_clean_pd_sales_manifest.py
python3 tools/migration/report_clean_pd_sales_manifest.py --self-test
```

## Isi JSON

Bagian utama report:

- `plan_sha256` dan `report_sha256`: fingerprint review yang deterministik.
- `stages`: schema/run/snapshot hash dan manifest hash BDM/TMP.
- `counts` serta `source_summary`: jumlah kandidat PD, detail, status yang
  dikecualikan, dan ringkasan hold.
- `candidate_documents`: kandidat source-qualified dengan target master,
  konversi UOM, rekonsiliasi nilai, serta mapping status draft `0/0`.
- `holds`: semua alasan hold lengkap dengan identity stage/hash sumber.
- `structural_blockers`: masalah kontrak target, registry, atau status draft
  numberless yang harus diselesaikan terlebih dahulu.

Di `source_summary.<source>.pd_lifecycle_audit`, report juga mencatat
ketersediaan kolom lifecycle dan jumlah timestamp/sinyal yang terisi pada
header PD. Ini membantu meninjau `TglReal` tanpa salah menganggap nilai
default sebagai pengiriman selesai.

Report yang bersih pun tetap hanya bahan UAT/review. Importer terpisah harus
memvalidasi ulang stage fingerprint dan plan pada transaksi serializable
sebelum write ke target clean.

Untuk alur UAT yang benar-benar terikat pada SHA report/plan/hold dan approval
manusia, lihat [README_apply_clean_pd_sales.md](README_apply_clean_pd_sales.md).
Applier tersebut tetap default dry-run dan hanya menerima target yang memiliki
token UAT; ia bukan bagian dari perintah reporter ini.
