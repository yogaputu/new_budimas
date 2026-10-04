# Pembayaran Kuitansi & Giro

Panduan migrasi, RBAC, pemetaan COA dan alur operasional terdapat pada `docs/payment-receipt-workflow.md` di checkout API setelah patch di bawah diterapkan.

## Terapkan perubahan backend

Frontend sudah dikirim ke GitHub. Push backend gagal karena sesi cloud belum mempunyai autentikasi tulis repo API. Seluruh commit backend `2cf5763` disertakan sebagai [patch](api-payment-workflow.patch), tanpa kredensial atau perubahan database bisnis.

Setelah pull frontend, pada checkout API yang bersih dan masih berada di `main`:

```sh
cd /path/ke/API
git pull --ff-only origin main
git am /path/ke/new_budimas/docs/api-payment-workflow.patch
```

Jika patch sudah pernah diterapkan, jangan terapkan lagi. Bila ada konflik dengan perubahan API yang lebih baru, gunakan `git am --abort` dan selesaikan penyesuaian sebelum deployment. Setelah diterapkan, commit dapat dikirim dari Mac menggunakan akses GitHub Anda: `git push origin main`.

Deploy API dan terapkan migrasi `20261004_payment_receipt_workflow.sql` sebelum frontend ini digunakan. Konfigurasi URL API mengikuti `VITE_API_BASE_URL` yang sudah digunakan.

Menu baru memakai capabilities `finance.receipts.*`, `finance.funds.*`, `finance.giro.*` dan `finance.workflow.configure`. Grant capabilities yang sesuai melalui RBAC; login ulang setelah perubahan role. Approval finalisasi dan pembatalan membutuhkan pengguna berbeda dari pembuat/pengaju.

Aktifkan perusahaan di Konfigurasi Pembayaran setelah delapan akun COA diisi. Buat LPH baru dan pilih **Kuitansi & Giro (baru)**. Gunakan **LPH & Pembayaran Sales**, setoran berlabel **Kuitansi**, **Setoran Giro**, **Pembayaran Tagihan — Kuitansi**, **Batal Kuitansi**, dan **Jurnal Pembayaran**. LPH yang sudah ada tetap menggunakan menu Rekap sebelumnya.

Klaim Sales belum mengurangi piutang. Cash harus disetujui Kasir; finalisasi Supervisor memposting jurnal dan pembayaran. Giro cair bukan setoran kedua; giro ditolak membuat draft pembatalan terkait. Kuitansi Cancelled dapat diedit dengan nomor tetap.
