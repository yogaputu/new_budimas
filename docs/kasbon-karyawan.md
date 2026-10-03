# Kasbon Karyawan

Menu Finance → Kasbon Karyawan menyediakan daftar dan form pengajuan. Finance → Approval Kasbon Karyawan menampilkan antrean `PENDING` tanpa pembatasan bulan secara default. Klik baris untuk detail, riwayat, dan keputusan.

Hak akses: `finance.employee-advances.view`, `finance.employee-advances.create`, dan `finance.employee-advances.approve`. Alasan penolakan wajib. Pengaju dan penerima tidak boleh memutuskan kasbon sendiri. Approval belum mencairkan dana atau memotong gaji.

## Integrasi backend

Frontend menggunakan kontrak yang sudah ada di `src/api/finance.js`. Implementasi backend tersedia di repository `yogaputu/API`, checkout `/workspace/API`, pada `apps/services/Akuntansi/EmployeeCashAdvance.py` dan `apps/routes/akuntansi.py`. Kontraknya sesuai dengan frontend; pengujian browser tetap menggunakan API simulasi.

| Metode | Endpoint | Kegunaan |
| --- | --- | --- |
| GET | `/api/akuntansi/employee-advances` | Daftar dengan `id_perusahaan`, `id_cabang`, `status`, `periode_awal`, `periode_akhir`, `page`, `limit`; hasil `{data: [...], total}` |
| GET | `/api/akuntansi/employee-advances/employees` | Pilihan karyawan dalam perusahaan/cabang; hasil daftar `{id, nama, nama_jabatan}` |
| POST | `/api/akuntansi/employee-advances` | Pengajuan: perusahaan, cabang, karyawan, tanggal, jatuh tempo opsional, nominal string desimal, keperluan, `client_request_id` |
| GET | `/api/akuntansi/employee-advances/:id` | Detail termasuk `created_by`, `id_karyawan`, `status`, dan `events` |
| POST | `/api/akuntansi/employee-advances/:id/decision` | `{decision: 'APPROVED' atau 'REJECTED', catatan}` |

Status: `PENDING`, `APPROVED`, `REJECTED`. Backend menyimpan `created_by` dan `id_karyawan` sebagai ID tabel `users`, sehingga dapat dibandingkan langsung dengan ID user login.

Backend wajib memeriksa hak akses dan cakupan perusahaan/cabang pada setiap endpoint, menolak approval oleh pengaju/penerima, serta memvalidasi nominal dan tanggal. Pengajuan harus idempoten berdasarkan `client_request_id`; keputusan harus mengubah status `PENDING` secara atomik dan menyimpan audit actor/waktu/catatan. Jangan mempercayai identitas atau status dari klien. Kembalikan konflik bila sudah diputuskan oleh petugas lain. Validasi frontend tidak menggantikan pemeriksaan server.

## Validasi lokal

`node --test tests/*.test.mjs`

Build melalui runtime cloud: `cd /workspace/.budimas-runtime && npm run build -- --config cloud.vite.config.mjs`. Hindari menimpa direktori `dist` dan `node_modules` yang dilacak Git.


## Backend dan database

Migrasi tersedia di `/workspace/API/tools/migrations/20261001_employee_cash_advance.sql`. Terapkan ke database development/staging yang sudah memiliki skema dasar aplikasi sebelum mengaktifkan fitur. Migrasi mendaftarkan fitur tetapi tidak memberikan izin otomatis; berikan izin pengajuan/approval kepada role yang sesuai. Approval belum mencairkan dana, memotong gaji, atau membuat jurnal.

Validasi backend lokal: `cd /workspace/API && PYTHONDONTWRITEBYTECODE=1 /workspace/.budimas-api-venv/bin/python -m unittest discover -s apps/test -p test_finance_revision_part2.py -v` (23 tes lulus). Gunicorn lokal berhasil dijalankan; GET Kasbon tanpa autentikasi menghasilkan 401. Penyimpanan ke PostgreSQL belum diuji karena database development dan akun uji belum dipilih.
