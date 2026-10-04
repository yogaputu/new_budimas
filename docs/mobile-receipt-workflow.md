# Terapkan workflow Mobile Sales

Perubahan mobile sudah diuji dan disertakan sebagai `docs/mobile-receipt-workflow.patch`. Push cloud ke repo `yogaputu/budimas-mobile` gagal karena autentikasi tulis untuk repo tersebut tidak tersedia. Patch berisi commit mobile `b1e4f3d` berbasis `aeb946f5`.

Pada Mac, jika checkout `new_budimas` dan `budimas-mobile` berdampingan:

```sh
cd /path/ke/new_budimas
git pull --ff-only origin main
cd ../budimas-mobile
git pull --ff-only origin main
git am ../new_budimas/docs/mobile-receipt-workflow.patch
git push origin main
npm ci
npm run build
npx cap sync android
```

Checkout mobile harus bersih sebelum `git am`. Jangan terapkan patch lagi jika commit sudah ada. Jika konflik, `git am --abort` lalu sesuaikan dengan perubahan terbaru.

Build APK/AAB melalui Android Studio dan install versi baru pada perangkat; untuk iOS gunakan `npx cap sync ios` lalu Xcode. Perubahan repo/API tidak otomatis mengganti aplikasi terpasang. Build dan signing native belum dilakukan di cloud.

Setelah patch, panduan lengkap ada pada repo mobile `docs/receipt-workflow.md`. Menu baru **LPH & Klaim Pembayaran** tersedia di Dashboard, LPH, dan Input Pembayaran. Workflow memerlukan koneksi online dan LPH versi Kuitansi dari Finance. Penerimaan mencocokkan semua faktur, klaim mencakup tunai/transfer/giro, pengembalian memisahkan cash ditransfer dan cash ke Kasir. Klaim belum mengurangi piutang; Finance memfinalisasi kuitansi.

Validasi cloud: build Vite berhasil; 9 tes Node lulus; tes browser mock menerima LPH, membuat klaim dan mengembalikan LPH pada viewport390px lulus. Tidak mengirim transaksi ke server bisnis.
