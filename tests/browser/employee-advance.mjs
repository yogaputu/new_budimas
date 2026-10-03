import assert from 'node:assert/strict';
// All business API requests are intercepted; this test never writes to a live API.
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', args: ['--no-sandbox', '--disable-dev-shm-usage', '--no-proxy-server'] });
try {
 const origin = process.env.PREVIEW_ORIGIN || 'http://127.0.0.1:5173';
 assert.equal(new URL(origin).hostname, '127.0.0.1');
 const page = await browser.newPage();
 await page.addInitScript(() => localStorage.setItem('budimas_internal_auth', JSON.stringify({ access_token: 'LOCAL-MOCK-ONLY', user: { id: 9, id_perusahaan: 1, id_cabang: 2 }, permissions: ['finance.employee-advances.view', 'finance.employee-advances.create', 'finance.employee-advances.approve'], menus: [] })));
 let row = { id: 1, nomor: 'KB-UJI-001', status: 'PENDING', created_by: 4, id_karyawan: 3, nama_karyawan: 'Karyawan Uji', nama_pengaju: 'Pengaju Uji', nominal: '100000', tanggal_pengajuan: '2026-09-01', keperluan: 'Keperluan uji', events: [] };
 const writes = [], queries = [], errors = [];
 page.on('pageerror', e => errors.push(e.message));
 page.on('dialog', d => d.accept());
 await page.route('**/*', async route => {
  const req = route.request(), url = new URL(req.url()), path = url.pathname;
  if (!path.startsWith('/api/')) return url.hostname === '127.0.0.1' ? route.continue() : route.abort();
  let data = [];
  if (path.endsWith('getPerusahaan')) data = [{ id: 1, nama: 'Perusahaan Uji', id_cabang_list: '2' }];
  else if (path.endsWith('getCabang')) data = [{ id: 2, id_cabang: 2, nama: 'Cabang Uji', id_perusahaan: 1 }];
  else if (path.endsWith('/employees')) data = [{ id: 3, nama: 'Karyawan Uji' }];
  else if (path.endsWith('/decision')) { const body = req.postDataJSON(); writes.push(body); row = { ...row, status: body.decision }; data = { message: 'Keputusan tersimpan.' }; }
  else if (path.endsWith('/employee-advances/1')) data = row;
  else if (path.endsWith('/employee-advances') && req.method() === 'POST') { const body = req.postDataJSON(); writes.push(body); data = { message: 'Pengajuan tersimpan.' }; }
  else if (path.endsWith('/employee-advances')) { queries.push(url.searchParams); data = { data: row.status === 'PENDING' ? [row] : [], total: row.status === 'PENDING' ? 1 : 0 }; }
  return route.fulfill({ json: data });
 });
 await page.goto(`${origin}/finance/employee-advances/approval`);
 await page.getByText('KB-UJI-001', { exact: true }).click();
 assert.equal(queries.at(-1).get('status'), 'PENDING');
 assert.equal(queries.at(-1).has('periode_awal'), false);
 await page.getByRole('button', { name: 'Tolak', exact: true }).click();
 await page.getByText('Alasan penolakan wajib diisi.').waitFor();
 assert.equal(writes.length, 0);
 await page.locator('textarea').fill('Alasan uji');
 await page.getByRole('button', { name: 'Tolak', exact: true }).click();
 await page.getByText('Keputusan tersimpan.', { exact: true }).waitFor();
 assert.deepEqual(writes[0], { decision: 'REJECTED', catatan: 'Alasan uji' });
 await page.getByRole('button', { name: 'Tutup', exact: true }).click();
 await page.getByRole('button', { name: 'Daftar Pengajuan', exact: true }).click();
 await page.getByRole('button', { name: 'Ajukan Kasbon', exact: true }).click();
 await page.getByRole('button', { name: 'Kirim Pengajuan', exact: true }).click();
 await page.getByText('Pilih perusahaan, cabang, dan karyawan.').waitFor();
 const dialog = page.locator('fieldset');
 await dialog.locator('label').filter({ hasText: 'Karyawan' }).locator('input').click();
 await dialog.getByRole('button', { name: 'Karyawan Uji', exact: true }).click();
 await dialog.locator('input[type=number]').fill('100000');
 await dialog.locator('textarea').fill('Keperluan uji');
 await page.getByRole('button', { name: 'Kirim Pengajuan', exact: true }).click();
 await page.getByText('Pengajuan tersimpan.', { exact: true }).waitFor();
 assert.equal(writes[1].id_karyawan, '3');
 assert.equal(writes[1].nominal, '100000');
 assert.ok(writes[1].client_request_id);
 assert.deepEqual(errors, []);
 console.log('PASS: antrean lintas tanggal, alasan penolakan wajib, keputusan API, validasi form, pengajuan API; seluruh API dimock tanpa transaksi nyata.');
} finally { await browser.close(); }
