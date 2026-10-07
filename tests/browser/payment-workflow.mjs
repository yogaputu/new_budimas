// Mocked browser smoke: never submits transactions to a business API.
// PLAYWRIGHT_MODULE=/path/to/playwright-core/index.mjs CHROMIUM_PATH=/usr/bin/chromium node tests/browser/payment-workflow.mjs
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.FRONTEND_TEST_ORIGIN || 'http://127.0.0.1:5173';
assert(['127.0.0.1', 'localhost'].includes(new URL(origin).hostname), 'Use a local frontend only.');
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, headless: true, args: ['--no-sandbox'] });
try {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const profile = { access_token: 'workflow-mocked-test-only', user: { id: 2, nama: 'Supervisor Test', role_code: 'SUPERUSER' }, permissions: ['*'], menus: [] };
  await page.addInitScript(p => localStorage.setItem('budimas_internal_auth', JSON.stringify(p)), profile);
  const receipt = { id: 1, created_by: 1, status: 'DRAFT', number: 'KW-TEST', kode_lph: 'LPH-TEST', receipt_date: '2026-10-04', total: 1000, invoices: [], allocations: [], audit: [] };
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith('/api/')) {
      const data = url.pathname.includes('detail-login') ? profile : url.pathname.endsWith('/workflow/receipts') ? [receipt] : url.pathname.endsWith('/workflow/receipts/1') ? receipt : [];
      return route.fulfill({ json: { data } });
    }
    if (url.origin !== new URL(origin).origin) return route.abort();
    return route.continue();
  });
  const pages = [
    ['/finance/receipt-workflow', 'Pembayaran Tagihan — Kuitansi'],
    ['/finance/receipt-cash', 'Setoran Tunai — Kuitansi'],
    ['/finance/receipt-transfer', 'Setoran Non Tunai — Kuitansi'],
    ['/finance/giro-deposits', 'Setoran Giro'],
    ['/finance/receipt-cancellation', 'Batal Kuitansi'],
    ['/finance/payment-workflow-journals', 'Jurnal Pembayaran'],
    ['/finance/payment-workflow-settings', 'Pengaturan Workflow Pembayaran'],
    ['/finance/payment-fees', 'Master Biaya Lain'],
    ['/sales-order/receipt-lph', 'LPH & Pembayaran Sales']
  ];
  for (const [path, title] of pages) {
    await page.goto(origin + path);
    await page.getByRole('heading', { name: title, exact: true, level: 1 }).waitFor();
    if (path === '/finance/receipt-workflow') {
      await page.getByRole('button', { name: 'Tinjau & Finalisasi', exact: true }).click();
      await page.getByRole('button', { name: 'Konfirmasi Rekonsiliasi & Finalisasi', exact: true }).waitFor();
    }
    if (path === '/finance/receipt-cash') {
      await page.getByRole('button', { name: 'Tambah Setoran', exact: true }).click();
      await page.getByText('Nomor referensi / BG', { exact: true }).waitFor();
      assert.equal(await page.getByLabel('Tanggal Penerimaan',{exact:true}).inputValue(), new Date().toLocaleDateString('en-CA'));
    }
    console.log('PASS', path);
  }
  assert.deepEqual(errors, []);
} finally {
  await browser.close();
}
