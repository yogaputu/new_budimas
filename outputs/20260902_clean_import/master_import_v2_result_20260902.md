# Hasil impor master BDM + TMP Solo — target clean v2

Tanggal eksekusi: 2 September 2026 (WIB)  
Run: `bdm-tmp-master-v2-20260902-1240`  
Status: **committed**  
Target: `budimas_clean_20260902_v2`

## Ruang lingkup dan keselamatan

- Sumber snapshot BDM dan TMP Solo hanya dibaca; tidak ada perubahan ke SQL Server.
- Database ERP produksi `budimas_dev` tidak diubah dan aplikasi belum dialihkan ke target clean v2.
- Sebelum penulisan master, target v2 telah dibackup dalam format PostgreSQL custom dump dan arsipnya tervalidasi dengan `pg_restore -l`.
- Kebijakan bisnis yang disetujui diterapkan: PPN operasional 11% dan tipe harga A/B/C/D/E dipetakan ke MT/GT/EU/KA/WS.
- Baris yang tidak valid atau ambigu tidak dipaksakan masuk. Semuanya tersimpan dalam registry hold dengan status `skipped` dan jejak sumbernya.

## Data yang berhasil dimuat

| Entitas | Jumlah |
| --- | ---: |
| Principal | 63 |
| Customer fisik | 40.946 |
| Peta customer sumber | 43.208 |
| Sales | 447 |
| Detail/penugasan principal sales | 447 / 447 |
| Produk | 20.502 |
| UOM produk | 39.433 |
| Harga jual produk | 102.510 |
| Plafon | 26.214 |

Perbedaan peta customer sumber dan customer fisik berasal dari 2.262 customer BDM yang secara persis berbagi customer TMP, sesuai aturan deduplikasi yang disetujui.

## Rekonsiliasi akhir

- Semua source map menuju target yang ada: **0 orphan** untuk principal, customer, sales, produk, UOM, harga, dan plafon.
- Constraint publik yang belum tervalidasi: **0**.
- Produk tanpa UOM level 1 dengan faktor konversi 1: **0**.
- Produk dengan jumlah level harga selain lima: **0**.
- Sales tanpa tepat satu detail atau satu penugasan principal: **0**.
- Hold yang ditinjau dan dilewati secara audit: **11.930** entri/kejadian, seluruhnya berstatus `skipped`.
- Statistik PostgreSQL pada tabel master target sudah diperbarui dengan `ANALYZE` untuk kesiapan UAT.

## Tahap berikutnya

1. UAT master pada database clean v2: customer, produk, UOM, lima harga, plafon, dan akses cabang.
2. Menyusun manifest transaksi source-qualified dengan kriteria 1:1; transaksi ambigu/retur/lifecycle yang belum terpetakan tetap di-hold.
3. Setelah UAT dan rekonsiliasi transaksi disetujui, barulah rencanakan cutover aplikasi secara terpisah dengan rollback dump yang sudah tersedia.
