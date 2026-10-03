// Run against a local Vite preview. Every API call is intercepted; no business writes.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { schedule } from '../fixtures/shipment-draft-print.mjs';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.PREVIEW_ORIGIN || 'http://127.0.0.1:4175';
assert.equal(new URL(origin).hostname, '127.0.0.1');
const out = process.env.QA_OUTPUT;
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const context = await browser.newContext({ viewport: { width: 1500, height: 1100 } });
const note = (id, changes = {}) => ({ id, no_order: `SO-${id}`, status_order: 1, id_perusahaan: 3, id_cabang: 2, id_rute: 4, nama_rute: 'Rute Utara', nama_customer: `Toko ${id}`, tanggal_order: '2026-09-30', ...changes });
const notes = [note(101), note(102, { id_armada: 5 }), note(103, { status_order: 0 }), note(104, { id_perusahaan: 9 }), note(105, { id_rute: 5, nama_rute: 'Rute Selatan' })];
const posted = [], requests = [], errors = [], blocked = [];
let failSave = true, failList = false, created = false, scheduleReads = 0;
await context.addInitScript(() => {
  if (localStorage.getItem('budimas_internal_auth')) return;
  localStorage.setItem('budimas_internal_auth', JSON.stringify({ access_token: 'MOCK-ONLY',
    user: { id: 99, nama: 'Operator Uji', id_cabang: 2, id_perusahaan: 3, id_jabatan: 7 },
    permissions: ['distribution.schedules.view', 'distribution.schedules.update'], menus: [] }));
});
await context.route('**/*', async route => {
  const request = route.request(), url = new URL(request.url());
  if (url.pathname.startsWith('/api/')) {
    requests.push({ method: request.method(), path: url.pathname, params: Object.fromEntries(url.searchParams) });
    if (request.method() === 'POST' && url.pathname === '/api/distribusi/update') {
      posted.push(request.postDataJSON());
      if (failSave) return route.fulfill({ status: 409, json: { message: 'Status nota sudah berubah. Muat ulang daftar.' } });
      created = true;
      return route.fulfill({ json: { message: 'Draf untuk 2 nota berhasil dibuat.' } });
    }
    if (request.method() !== 'GET') { blocked.push(request.url()); return route.abort(); }
    let data = [];
    if (url.pathname === '/api/extra/getPerusahaan') data = [{ id: 3, nama: 'Perusahaan Uji', id_cabang_list: '2' }];
    if (url.pathname === '/api/extra/getCabang') data = [{ id: 2, nama: 'Cabang Uji', id_perusahaan: 3 }];
    if (url.pathname === '/api/extra/getArmada') data = [{ id: 8, nama: 'Truk Uji', no_pelat: 'B 1234 UJI', id_cabang: 2 }, { id: 80, nama: 'Armada Cabang Lain', id_cabang: 9 }];
    if (url.pathname === '/api/extra/getDriver') data = [{ id: 9, nama: 'Driver Uji', id_cabang: 2 }];
    if (url.pathname === '/api/extra/getHelper') data = [{ id: 10, nama: 'Helper Uji', id_cabang: 2 }];
    if (url.pathname === '/api/distribusi/get-jadwal-armada') { scheduleReads++; data = created ? [schedule(4, { no_order: 'SO-101, SO-106', id_sales_order: '101,106', sales_order_count: 2 })] : []; }
    if (url.pathname === '/api/distribusi/shipment-draft-orders') {
      if (failList) return route.fulfill({ status: 503, json: { message: 'Daftar nota belum tersedia.' } });
      const page = Number(url.searchParams.get('page'));
      assert.equal(url.searchParams.get('status'), '1'); assert.equal(url.searchParams.get('id_perusahaan'), '3'); assert.equal(url.searchParams.get('id_cabang'), '2');
      assert.equal(url.searchParams.has('user_id'), false);
      data = { items: page === 1 ? notes : [note(106)], pagination: { page, total: 51, total_pages: 2 } };
    }
    return route.fulfill({ json: data });
  }
  if (url.origin !== origin) { blocked.push(request.url()); return route.abort(); }
  return route.continue();
});
const page = await context.newPage(); page.on('pageerror', error => errors.push(error.message));
const pick = id => page.getByRole('checkbox', { name: `Pilih nota SO-${id}`, exact: true });
const modal = title => page.locator('section').filter({ has: page.getByRole('heading', { name: title, exact: true }) }).last();
const next = count => page.getByRole('button', { name: `Lanjut Atur Pengiriman (${count} nota)`, exact: true });
async function choose(label, option) {
  const input = modal('Buat Draf Kiriman').locator('label').filter({ hasText: label }).locator('input');
  await input.fill(option); await page.getByRole('button', { name: option, exact: true }).click();
}
try {
  await page.goto(origin + '/distribution/schedules');
  await page.getByRole('button', { name: 'Buat Draf Kiriman', exact: true }).click();
  await pick(101).waitFor();
  assert.equal(await pick(103).count(), 0); assert.equal(await pick(104).count(), 0); assert.equal(await pick(102).isDisabled(), true);
  await pick(101).check(); await pick(105).check();
  assert.equal(await next(2).isDisabled(), true); await page.getByRole('alert').filter({ hasText: 'rute yang sama' }).waitFor();
  await pick(105).uncheck(); await next(1).waitFor();
  await page.getByLabel('Tanggal Nota Dari', { exact: true }).fill('2026-10-02');
  await page.getByLabel('Tanggal Nota Sampai', { exact: true }).fill('2026-10-01');
  assert.equal(await next(0).isDisabled(), true);
  const beforeInvalid = requests.filter(r => r.path.endsWith('shipment-draft-orders')).length;
  await modal('Pilih Nota Terkonfirmasi').getByRole('button', { name: 'Terapkan', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: 'Tanggal nota awal' }).waitFor();
  assert.equal(requests.filter(r => r.path.endsWith('shipment-draft-orders')).length, beforeInvalid);
  await page.getByLabel('Tanggal Nota Dari', { exact: true }).fill('2026-09-29');
  await modal('Pilih Nota Terkonfirmasi').getByRole('button', { name: 'Terapkan', exact: true }).click();
  await pick(101).check(); await page.getByRole('button', { name: 'Halaman Berikutnya', exact: true }).click(); await pick(106).check();
  const dated = requests.filter(r => r.path.endsWith('shipment-draft-orders')).at(-1).params;
  assert.equal(dated.date_from, '2026-09-29'); assert.equal(dated.date_to, '2026-10-01');
  if (out) await page.screenshot({ path: out + '/picker.png', fullPage: true, animations: 'disabled' });
  await next(2).click();
  await modal('Buat Draf Kiriman').getByRole('button', { name: 'Batal', exact: true }).click();
  await page.getByRole('heading', { name: 'Buat Draf Kiriman', exact: true }).waitFor({ state: 'hidden' });
  await next(2).waitFor(); assert.equal(await pick(106).isChecked(), true);
  assert.equal(await page.evaluate(() => document.body.style.overflow), 'hidden');
  await next(2).click();
  await page.getByRole('heading', { name: 'Pilih Nota Terkonfirmasi', exact: true }).waitFor({ state: 'hidden' });
  await choose('Armada', 'B 1234 UJI - Truk Uji');
  await choose('Driver', 'Driver Uji'); await choose('Helper / Kernet', 'Helper Uji');
  await page.getByLabel('Tanggal Pengiriman', { exact: true }).fill('2026-10-02');
  await page.getByLabel('Loading Dock', { exact: true }).fill('DOCK-A');
  await page.getByLabel('Zona muatan', { exact: true }).selectOption('FOOD');
  await page.getByLabel('Satuan estimasi volume', { exact: true }).selectOption('M3');
  await page.getByLabel('Catatan Pengiriman', { exact: true }).fill('Dua nota untuk rute utara');
  await modal('Buat Draf Kiriman').getByRole('heading').click();
  if (out) await page.screenshot({ path: out + '/form.png', fullPage: true, animations: 'disabled' });
  await page.getByRole('button', { name: 'Simpan Draf (2 nota)', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: 'Status nota sudah berubah' }).waitFor();
  assert.equal(await modal('Buat Draf Kiriman').getByText('SO-101', { exact: true }).count(), 1);
  failSave = false;
  await page.getByRole('button', { name: 'Simpan Draf (2 nota)', exact: true }).click();
  await page.getByRole('status').filter({ hasText: 'Draf untuk 2 nota berhasil dibuat' }).waitFor();
  await page.getByText('SO-101, SO-106', { exact: true }).waitFor();
  assert(scheduleReads >= 2);
  assert.deepEqual(posted[1].id_sales_orders, [101, 106]);
  assert.deepEqual(posted[1].helper_ids, [10]); assert.equal(posted[1].id_armada, 8); assert.equal(posted[1].id_driver, 9);
  assert.equal(posted[1].tanggal_pengiriman, '2026-10-02');
  await page.getByRole('button', { name: 'Buat Draf Kiriman', exact: true }).click();
  await pick(101).waitFor(); assert.equal(await pick(101).isChecked(), false); await next(0).waitFor();
  failList = true;
  await modal('Pilih Nota Terkonfirmasi').getByRole('button', { name: 'Terapkan', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: 'Daftar nota belum tersedia' }).waitFor(); assert.equal(await next(0).isDisabled(), true);
  failList = false;
  await modal('Pilih Nota Terkonfirmasi').getByRole('button', { name: 'Terapkan', exact: true }).click(); await pick(101).waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  if (out) await page.screenshot({ path: out + '/mobile.png', fullPage: false, animations: 'disabled' });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  await modal('Pilih Nota Terkonfirmasi').getByRole('button', { name: 'Batal', exact: true }).click();
  await page.evaluate(() => {
    const session = JSON.parse(localStorage.getItem('budimas_internal_auth'));
    session.permissions = ['distribution.schedules.view'];
    localStorage.setItem('budimas_internal_auth', JSON.stringify(session));
  });
  await page.reload(); await page.getByRole('heading', { name: 'Jadwal Pengiriman', exact: true }).waitFor();
  assert.equal(await page.getByRole('button', { name: 'Buat Draf Kiriman', exact: true }).count(), 0);
  assert.deepEqual(errors, []); assert.deepEqual(blocked, []);
  const result = { pass: true, interceptedSaveCalls: posted.length, productionRequests: 0, checks: ['permission gate', 'confirmed-only scoped notes', 'scheduled notes disabled', 'mixed-route rejection', 'date bounds and invalid dates', 'cross-page selection', 'back preserves selection', '409 retains form', 'exact combined payload', 'list refresh after save', 'reopen resets selection', 'load failure and retry', 'mobile viewport'], requests };
  if (out) await fs.writeFile(out + '/browser-result.json', JSON.stringify(result, null, 2));
  console.log(JSON.stringify({ ...result, requests: requests.length }));
} catch (error) {
  if (out) await page.screenshot({ path: out + '/failure.png', fullPage: true });
  console.error({ errors, blocked, body: (await page.locator('body').innerText()).slice(-3000) });
  throw error;
} finally { await browser.close(); }
