# Bukti Mapping Harga dan PPN — BDM/TMP Solo

Tanggal audit: 2 September 2026.  Semua pemeriksaan sumber dilakukan read-only
pada snapshot BDM/TMP beku; tidak ada perubahan pada SQL Server atau
`budimas_dev`.

## Harga

`OpsHarga` merupakan bukti kuat untuk memilih kolom harga sumber, bukan bukti
semantik kode harga target ERP:

| Sumber | Observasi yang cocok |
|---|---:|
| BDM A → HargaA | 8.263 / 9.669 (85,46%) |
| BDM B → HargaB | 47.154 / 56.511 (83,44%) |
| BDM E → HargaE | 516 / 532 (96,99%) |
| TMP A → HargaA | 6.222 / 6.224 (99,97%) |
| TMP B → HargaB | 54.900 / 54.946 (99,92%) |
| TMP E → HargaE | 837 / 845 (99,05%) |

Kode C/D hanya dipakai oleh masing-masing 2/1 customer TMP.  Karena sumber
tidak menyebut nama tipe harga target (`MT`, `GT`, `EU`, `KA`, `WS`), pemetaan
`HargaA-E` ke kode target tersebut tetap memerlukan konfirmasi bisnis.

## PPN customer

`FP` **bukan** penanda PPN customer.  Pada detail transaksi bernilai DPP
positif, nilai `FP=T` dan `FP=Y` sama-sama hampir seluruhnya menghasilkan PPN
11%.  Draft aturan `T=non-PPN`, `Y=PPN` sudah ditolak dan tidak boleh dipakai.

## PPN produk

`FakturPajak=YA` sangat kuat menunjuk PPN 11%.  Namun `FakturPajak=TIDAK`
tidak membuktikan PPN 0%: seluruh 99 observasi detail TMP bernilai positif
berflag `TIDAK` tetap ber-PPN 11%.  Ada satu produk TMP dengan nilai kosong.

## Keputusan aman saat ini

Jangan menjalankan import master yang menulis `customer.is_ppn` atau
`produk.ppn` hingga Finance menetapkan aturan sumber yang eksplisit.  Target
blue/green tetap kosong dari data master bisnis dan dapat dibangun ulang tanpa
mengganggu produksi.
