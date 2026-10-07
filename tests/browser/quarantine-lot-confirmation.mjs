// Mock-only QC form test. POST is intercepted and never reaches the server.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, headless: true });
const origin = process.env.TEST_BASE_URL || 'http://127.0.0.1:5173';
try {
  const page = await browser.newPage();
  page.on('pageerror', error => console.error('Browser error:', error.message));
  page.on('console', msg => { if (msg.type() === 'error') console.error(msg.text()); });
  page.on('requestfailed', request => console.error('Request failed:', request.url()));
  page.setDefaultTimeout(15000);
  const user = { id: 1, nama: 'Test', is_superuser: true, role: 'superadmin' };
  let submitted;
  await page.addInitScript(user => localStorage.setItem('budimas_internal_auth', JSON.stringify({
    access_token: 'mock-only', user, permissions: ['*'], menus: []
  })), user);
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (!url.pathname.startsWith('/api/')) return url.origin === origin ? route.continue() : route.abort();
    let data = [];
    if (url.pathname.includes('detail-login') || url.pathname.includes('/auth/')) data = { user, permissions: ['*'], menus: [] };
    else if (url.pathname.endsWith('/quarantine/quarantine/open')) data = [{
      id: 9, qty_pcs: 10, kode_barang: 'QC-TEST', nama_barang: 'Produk', lot_status: 'MANUAL_REQUIRED', lot_options: []
    }];
    else if (url.pathname.endsWith('/quarantine/quarantine/qc')) {
      submitted = route.request().postDataJSON();
      data = { status: 'OK', message: 'Mock QC selesai' };
    }
    return route.fulfill({ json: { data } });
  });
  await page.goto(origin + '/wms');
  try {
    await page.getByRole('button', { name: /QC Karantina/ }).click();
  } catch (error) {
    console.error('Rendered page:', (await page.locator('body').innerText()).slice(0,3000));
    throw error;
  }
  await page.getByLabel('Batch fisik barang', { exact: true }).fill('BATCH-PHYSICAL');
  await page.getByLabel('Expired', { exact: true }).fill('2027-01-31');
  await page.getByLabel('GOOD (PCS)', { exact: true }).fill('0');
  await page.getByLabel('BAD (PCS)', { exact: true }).fill('10');
  await page.getByLabel('Petugas QC', { exact: true }).fill('Tester');
  await Promise.all([
    page.waitForResponse(r => r.url().endsWith('/quarantine/quarantine/qc')),
    page.getByRole('button', { name: 'Simpan QC', exact: true }).click()
  ]);
  assert.equal(submitted.batch_number, 'BATCH-PHYSICAL');
  assert.equal(submitted.expired_date, '2027-01-31');
  assert.equal(submitted.lot_confirmed, true);
  assert.equal(submitted.qty_bad, 10);
  console.log('PASS QC browser: missing lot requires physical batch/expiry and submits confirmation.');
} finally { await browser.close(); }
