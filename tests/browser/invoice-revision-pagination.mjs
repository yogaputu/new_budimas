// All API/network requests are intercepted; no production transaction is sent.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.TEST_BASE_URL || 'http://127.0.0.1:5173';
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, headless: true });
try {
  const page = await browser.newPage();
  page.setDefaultTimeout(15000);
  const requests = [], errors = [];
  const user = { id: 1, id_user: 1, nama: 'Test', is_superuser: true, role: 'superadmin' };
  page.on('pageerror', e => errors.push(e.message));
  await page.addInitScript(user => localStorage.setItem('budimas_internal_auth', JSON.stringify({
    access_token: 'mock-only', user, permissions: ['*'], menus: []
  })), user);
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (!url.pathname.startsWith('/api/')) {
      return url.origin === origin ? route.continue() : route.abort();
    }
    requests.push(url);
    let data = [];
    if (url.pathname.includes('detail-login') || url.pathname.includes('/auth/')) data = { user, permissions: ['*'], menus: [] };
    else if (url.pathname.includes('getPerusahaan')) data = [{ id: 1, kode: 'BMM', nama: 'Perusahaan', id_cabang_list: '5' }];
    else if (url.pathname.includes('getCabang')) data = [{ id: 5, id_perusahaan: 1, nama: 'Solo', kode: 'SLO' }];
    else if (url.pathname.includes('get-list-rute-revisi-faktur')) {
      const second = url.searchParams.has('cursor');
      data = { routes: [{ id_rute: null, id_driver: null, id_armada: null, delivering_date: null,
        id_faktur: second ? '101' : '201,202', id_sales_order: second ? '11' : '21,22',
        nama_rute: second ? 'Lama tanpa jadwal' : 'Tanpa jadwal', jumlah_nota: second ? 1 : 2 }],
        pagination: { has_more: !second, next_cursor: second ? null : 201 } };
    } else if (url.pathname.includes('get-list-faktur-revisi-faktur')) data = {
      list_faktur_shipping: [{ id_faktur: 201, id_sales_order: '21', no_faktur: 'F-201', total_penjualan: 1000 }]
    };
    else if (url.pathname.includes('get-detail-faktur/')) data = { detail_faktur: { id_faktur: 201 }, list_detail_order: [] };
    return route.fulfill({ json: { data } });
  });
  await page.goto(origin + '/distribution/invoice-revisions?id_cabang=5');
  await page.getByPlaceholder('Pilih perusahaan').click();
  await page.getByRole('button', { name: /BMM.*Perusahaan/ }).click();
  await page.getByRole('button', { name: 'Muat Revisi', exact: true }).click();
  await page.getByRole('cell', { name: '- - Tanpa jadwal', exact: true }).click();
  await Promise.all([
    page.waitForResponse(r => r.url().includes('get-detail-faktur/')),
    page.getByRole('cell', { name: 'F-201', exact: true }).click()
  ]);
  const invoice = requests.find(u => u.pathname.includes('get-list-faktur-revisi-faktur'));
  assert.equal(invoice.searchParams.get('invoice_ids'), '201,202');
  assert.equal(invoice.searchParams.get('id_perusahaan'), '1');
  const detail = requests.find(u => u.pathname.includes('get-detail-faktur/'));
  assert.equal(detail.searchParams.get('id_faktur'), '201');
  assert.equal(detail.searchParams.get('revision_context'), '1');
  await page.getByRole('button', { name: 'Berikutnya', exact: true }).click();
  await page.getByRole('cell', { name: '- - Lama tanpa jadwal', exact: true }).waitFor();
  assert.equal(requests.filter(u => u.pathname.includes('get-list-rute-revisi-faktur')).at(-1).searchParams.get('cursor'), '201');
  await page.getByPlaceholder('Cari di seluruh faktur revisi').fill('F-201');
  await page.getByPlaceholder('Cari di seluruh faktur revisi').press('Enter');
  await page.getByRole('cell', { name: '- - Tanpa jadwal', exact: true }).waitFor();
  const search = requests.filter(u => u.pathname.includes('get-list-rute-revisi-faktur')).at(-1);
  assert.equal(search.searchParams.get('search'), 'F-201');
  assert.equal(search.searchParams.has('cursor'), false);
  assert.equal(search.searchParams.get('limit'), '50');
  assert.deepEqual(errors, []);
  console.log('PASS revision browser: missing schedule, exact invoice, bounded pagination and global search.');
} finally { await browser.close(); }
