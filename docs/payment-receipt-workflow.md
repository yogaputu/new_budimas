# Pembayaran Kuitansi & Giro

Panduan migrasi, RBAC, pemetaan COA dan alur operasional berada di [repo API](https://github.com/yogaputu/API/blob/main/docs/payment-receipt-workflow.md).

Pull/deploy API dan terapkan migrasi `20261004_payment_receipt_workflow.sql` sebelum frontend ini digunakan. Konfigurasi URL API mengikuti `VITE_API_BASE_URL` yang sudah digunakan.

Menu baru memakai capabilities `finance.receipts.*`, `finance.funds.*`, `finance.giro.*` dan `finance.workflow.configure`. Grant capabilities yang sesuai melalui RBAC; login ulang setelah perubahan role. Approval finalisasi dan pembatalan membutuhkan pengguna berbeda dari pembuat/pengaju.

Aktifkan perusahaan di Konfigurasi Pembayaran setelah delapan akun COA diisi. Buat LPH baru dan pilih **Kuitansi & Giro (baru)**. Gunakan **LPH & Pembayaran Sales**, setoran berlabel **Kuitansi**, **Setoran Giro**, **Pembayaran Tagihan — Kuitansi**, **Batal Kuitansi**, dan **Jurnal Pembayaran**. LPH yang sudah ada tetap menggunakan menu Rekap sebelumnya.

Klaim Sales belum mengurangi piutang. Cash harus disetujui Kasir; finalisasi Supervisor memposting jurnal dan pembayaran. Giro cair bukan setoran kedua; giro ditolak membuat draft pembatalan terkait. Kuitansi Cancelled dapat diedit dengan nomor tetap.
