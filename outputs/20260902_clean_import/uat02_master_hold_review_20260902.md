# Review master import UAT02 — 2 September 2026

## Ruang lingkup

Target satu-satunya adalah `budimas_clean_20260902_v2_uat02`.
Tidak ada koneksi atau perubahan ke SQL Server, `budimas_dev`, baseline
`budimas_clean_20260902_v2`, maupun UAT01.

Sebelum write master, checkpoint UAT02 sudah dibuat pada server:

```text
/www/backups/budimas_migration_20260902/uat02_rebuild_20260902T20260902T101348Z/budimas_clean_20260902_v2_uat02_pre_master_20260902T101348Z.dump
SHA-256: 5b7ab516d935b854c14a7a2fecaf16f5db2f29505f2a44c3355bd216724a0e3a
```

## Evidence UAT02 yang direview

| Item | Nilai |
| --- | --- |
| Target | `budimas_clean_20260902_v2_uat02` |
| Plan SHA-256 | `5ee9ea19ac7ccced17cdfc00f735f5af1c502ac25a53192a9b75cb195ab75966` |
| Hold manifest SHA-256 | `a2bc48e88aab2d4ece849feee81770fbd49d6e63f30d979909ebcd916c961ee7` |
| Exact hold entries SHA-256 | `c01ecfd1b84905a4ac0b9846b10723611ab6a8bc7c112ab0d944bb60a36a882b` |
| Schema fingerprint | `5622604f90ecd4b24a4739beedff9b818131da5352ec1aa9e50c389f4f729f94` |
| Reference fingerprint | `423e0ffdc0a2ba724194e5b13a74c7149c655847e5805c30eb53ca7ace3a7926` |
| Manifest approval status | `pending_review` |

Hasilnya identik dengan evidence baseline untuk policy, data freeze,
rencana tindakan, seluruh reason/count hold, dan hash isi hold. Snapshot
freeze BDM/TMP yang sama juga terverifikasi. Laporan UAT menambahkan metadata
konsistensi freeze dan jumlah tabel; karena metadata tambahan itu objek JSON
stage tidak dibandingkan byte-per-byte dengan format evidence lama.

## Data yang akan ditulis jika disetujui

- 63 principal
- 40.946 customer fisik dari 43.208 source mapping
- 447 sales tanpa akun login
- 20.502 produk dan 39.433 UOM
- 102.510 harga
- 26.214 plafon terbaru, non-live (`sisa_bon=0`, terkunci)

Tidak ada sales order, faktur, stok, AR, picking, manifest, pengiriman,
retur, maupun pembayaran yang ditulis pada tahap master ini.

## Hold yang akan dilewati dan dicatat permanen

Total: **11.930** baris hold.

| Reason | Jumlah |
| --- | ---: |
| `plafon_source_key_blank` | 5.560 |
| `plafon_sales_not_planned` | 4.737 |
| `product_principal_not_planned` | 730 |
| `plafon_customer_not_planned` | 213 |
| `plafon_latest_duplicate_source_rows` | 156 |
| `uom_outer_factor_must_be_gt_one` | 148 |
| `product_required_source_value_blank` | 78 |
| `plafon_latest_timestamp_conflict` | 72 |
| `customer_tax_address_too_long` | 49 |
| `uom_base_reference_name_not_verified` | 45 |
| `sales_source_key_blank` | 42 |
| `sales_principal_not_planned` | 33 |
| `plafon_principal_not_planned` | 31 |
| `uom_outer_same_as_base_with_conversion` | 23 |
| `uom_outer_reference_name_not_verified` | 4 |
| `customer_tmp_exact_counterpart_not_planned` | 3 |
| `principal_phone_too_long` | 3 |
| `customer_tax_name_too_long` | 2 |
| `product_source_tax_flag_unmapped` | 1 |

## Keputusan yang diperlukan

Setujui `approved_skip` hanya untuk manifest UAT02 persis di atas agar
import master dapat dijalankan ke UAT02. Semua 11.930 hold tetap tersimpan
dalam registry audit dan tidak akan dibuat secara diam-diam.
