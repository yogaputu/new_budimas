# Rebuild UAT02 clean master target

Runbook ini membangun database baru
`budimas_clean_20260902_v2_uat02` dari artefak PostgreSQL yang sudah ada di
server. Ini bukan perintah untuk produksi, SQL Server, baseline
`budimas_clean_20260902_v2`, atau UAT01.

Skripnya adalah [rebuild_clean_uat02.sh](rebuild_clean_uat02.sh). Simpan dan
review di workspace dahulu; skrip tidak dijalankan otomatis oleh Codex.

## Aturan sumber yang tidak boleh dilanggar

- Gunakan `budimas_dev_schema_only_20260902T003000+0700.dump` hanya dengan
  seleksi `--schema=public`, lalu hanya dua definisi schema staging final:
  `legacy_bdm_solo_final_freeze_20260830` dan
  `legacy_tmp_solo_final_freeze_20260830`.
- Gunakan `budimas_dev_reference_allowlist_20260902T003300+0700.dump` untuk
  data referensi yang sudah di-allow-list saja.
- Gunakan `bdm_tmp_final_freeze_20260830_data_20260902T003100+0700.dump`
  hanya untuk data kedua staging final.
- Jangan restore dump `*_pre_master_apply_*` atau
  `*_post_master_committed_*` ke UAT02. Keduanya memuat registry/attestation
  yang terikat pada nama database lama.
- Jangan menyalin `clean_target_attestation`. Setelah baseline, reference,
  dan freeze stage selesai dipulihkan, skrip menjalankan dry-run read-only
  untuk menghitung fingerprint nyata dan extension registry membuat satu
  attestation baru khusus `budimas_clean_20260902_v2_uat02`.

## Tahapan

1. Audit tanpa write:

   ```sh
   ./rebuild_clean_uat02.sh
   ```

   Ini memeriksa eksistensi produksi/baseline/UAT01, ketiadaan UAT02,
   checksum artefak, policy yang approved, serta TOC archive. Tidak ada
   database yang dibuat atau diubah.

2. Buat baseline UAT02 dan dry-run master:

   ```sh
   I_UNDERSTAND_UAT02_BUILD=CREATE-budimas_clean_20260902_v2_uat02-ONLY \
     ./rebuild_clean_uat02.sh --build-target
   ```

   Script berhenti setelah membuat fresh hold envelope milik UAT02. Jika
   build gagal, target parsial sengaja tidak dihapus agar dapat diaudit;
   script juga tidak akan menimpa target tersebut.

### Melanjutkan seed UAT02 yang sudah ada

Jika `budimas_clean_20260902_v2_uat02` sudah dibuat sampai public/reference,
freeze stage, dan **base** registry saja, jangan jalankan `--build-target`
lagi. Jalankan preflight read-only berikut:

```sh
./rebuild_clean_uat02.sh --preflight-existing-target
```

Gate tersebut mewajibkan target masih kosong dari master/transaksi, extension
registry belum dipasang, staging run 1 BDM/TMP completed dengan
`maintenance_freeze_serializable`, reference count sama dengan baseline v2,
dan produksi/baseline/UAT01 tetap ada.

Setelah gate lulus, lanjutkan hanya sampai attestation dan master dry-run:

```sh
I_UNDERSTAND_UAT02_PREPARE=PREPARE-budimas_clean_20260902_v2_uat02-ONLY \
  ./rebuild_clean_uat02.sh --prepare-existing-target
```

Mode ini memasang extension sekali pada target yang masih kosong, membuat
`clean_target_attestation` baru dengan fingerprint hasil dry-run nyata, lalu
menulis report dan envelope hold UAT02. Ia **belum** menulis master.

3. Review file
   `master_hold_manifest_uat02.pending.json` dalam run directory. Approval
   hold lama tidak bisa dipakai langsung karena `target_database`, plan, dan
   attestation merupakan bagian immutable dari manifest. Bila source plan
   identik, skrip sudah membuktikan `hold_entries_sha256`, stage snapshot,
   policy, action plan, dan baseline sama dengan evidence v2. Pemilik data
   tetap harus menyetujui ulang envelope **baru** dengan mengubah bagian
   `approval` saja; bagian `manifest` tidak boleh diubah.

4. Setelah approval UAT02 baru tersedia:

   ```sh
   UAT02_RUN_DIR=/www/backups/budimas_migration_20260902/uat02_rebuild_<timestamp> \
   UAT02_APPROVED_HOLDS=/path/approval-uat02.json \
   I_UNDERSTAND_UAT02_MASTER_APPLY=APPLY-budimas_clean_20260902_v2_uat02-ONLY \
     ./rebuild_clean_uat02.sh --apply-master
   ```

   Importer tetap melakukan ulang seluruh guard dalam satu transaksi
   serializable. Ia tidak membuat transaksi penjualan, stok, AR, WMS,
   shipment, atau data SQL Server.

5. Verifikasi ulang bila perlu:

   ```sh
   UAT02_RUN_DIR=/www/backups/budimas_migration_20260902/uat02_rebuild_<timestamp> \
     ./rebuild_clean_uat02.sh --verify
   ```

## Gate akhir

`--verify` mensyaratkan attestation tepat satu dan tepat nama database,
fingerprint public/reference sama dengan dry-run, source context dua, master
run committed, count master/map sesuai evidence, tidak ada orphan map, semua
hold tercatat, dan `sales_order`, `faktur`, serta detailnya masih kosong.
Jadi hasilnya tetap UAT master-only, belum live/cutover.
