# Review manifest transaksi PD — BDM Solo dan TMP Solo

## Status

Dry-run final selesai pada 2 September 2026 terhadap database baseline bersih
`budimas_clean_20260902_v2`. Koneksi memakai transaksi `REPEATABLE READ,
READ ONLY`; tidak ada tabel PostgreSQL atau SQL Server yang diubah.

- Report immutable: `/www/backups/budimas_migration_20260902/pd_manifest_tools_20260902/pd_sales_manifest_baseline_20260902T165000+0700.json`
- SHA-256 report: `a2fe91c7f92eebab076f794b56c05dadc1b5476511e5010cdc708478d8a09604`
- Plan SHA-256: `7b52ae4395e1376b0de3a694c77383373050c5146df958c6d5b02946ffb388bf`
- Structural blocker: **0**

## Scope yang terkunci

- Sumber kanonik: `HJualSM` dan `DJualSM` saja; status header `PD` persis.
- Freeze BDM dan TMP sama-sama `maintenance_freeze_serializable`, ter-attest,
  `SERIALIZABLE`, dengan maintenance window
  `aug2026-bdm-tmp-20260830-01`.
- Rentang snapshot: `[2026-08-01 00:00:00, 2026-09-01 00:00:00)`.
- Selector header harus `Tanggal`; selector detail harus child `HJualSM/Nota`.
- Target draft yang direncanakan: sales order status `0`, faktur status `0`,
  tanpa nomor faktur, tanpa tanggal faktur/kirim, dan tanpa stok, picking,
  rute, manifest, pembayaran, retur, maupun HPP.

## Hasil kandidat

| Sumber | Dokumen PD | Kandidat | Detail kandidat |
| --- | ---: | ---: | ---: |
| BDM Solo | 1.455 | 1.382 | 15.774 |
| TMP Solo | 1.709 | 1.611 | 12.405 |
| Total | 3.164 | 2.993 | 28.179 |

Kandidat akan membutuhkan tepat 2.993 sales order draft, 2.993 faktur draft
tanpa nomor, 2.993 `faktur_detail`, dan 28.179 detail order jika nanti
disetujui untuk dimasukkan ke UAT.

## Hold untuk review/skip

Ada 171 dokumen berbeda yang di-hold (203 baris bukti karena satu dokumen
dapat memiliki lebih dari satu alasan).

| Alasan | Baris hold |
| --- | ---: |
| Detail/header tidak tervalidasi penuh | 29 |
| Mapping customer/sales/principal header belum tepat | 13 |
| Mapping produk exact belum ada | 3 |
| Mapping UOM dasar exact belum ada | 27 |
| Mapping plafon exact belum ada/ambigu | 64 |
| Ada pembayaran sumber | 1 |
| Ada `UserPK` (bukti picking/proses lanjut) | 65 |
| Ada `UserReal` (bukti delivery/proses lanjut) | 1 |

Kolom tanggal legacy `TglAdd`, `TglPK`, `TglReal`, dan `TglBatal` dicatat
sebagai audit saja. Kolom-kolom itu terisi default pada hampir seluruh data,
sehingga tidak dipakai sendiri untuk menyatakan pengiriman atau pembatalan.

## Keadaan target setelah dry-run

Baseline dan UAT masih nol pada `sales_order`, `faktur`,
`sales_order_detail`, serta registry `sales_document_map`.

Langkah berikutnya adalah menyiapkan importer **UAT-only** yang mengharuskan
approval eksplisit atas SHA report/plan ini dan memasukkan hanya kandidat;
semua hold akan tetap dicatat sebagai skip audit. Tidak ada cutover produksi
atau perubahan SQL Server pada tahap tersebut.
