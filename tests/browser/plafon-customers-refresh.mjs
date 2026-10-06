// Local browser regression: all API requests are mocked; no customer is created.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, headless: true, args: ['--no-sandbox'] });
try {
  const page = await browser.newPage();
  page.setDefaultTimeout(15000);
  const user = { id: 1, nama: 'Admin', is_superuser: true, role: 'superadmin' };
  await page.addInitScript(user => localStorage.setItem('budimas_internal_auth', JSON.stringify({ access_token: 'test-only', user, permissions: ['*'], menus: [] })), user);
  let customerLoads = 0;
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith('/api/')) {
      let data = [];
      if (url.pathname.includes('detail-login') || url.pathname.includes('/auth/')) data = { user, permissions: ['*'], menus: [] };
      else if (url.pathname.includes('getCabang')) data = [{ id: 1, kode: 'SLO', nama: 'Solo', id_perusahaan: 1 }];
      else if (url.pathname.includes('getPerusahaan')) data = [{ id: 1, kode: 'BMM', nama: 'Perusahaan', id_cabang_list: '1' }];
      else if (url.pathname === '/api/base/customer/paginate') {
        const pageIndex = Number(url.searchParams.get('page'));
        assert.equal(url.searchParams.get('order_by'), 'id');
        if (pageIndex === 0) customerLoads++;
        const customers = Array.from({ length: 5001 }, (_, i) => ({ id: i + 1, kode: 'OLD' + i, nama: 'Customer lama ' + i, id_cabang: 2 }));
        if (customerLoads > 1) customers.push({ id: 5002, kode: 'NEW', nama: 'Customer baru', id_cabang: 2, id_cabang_list: '2,1' });
        const offset = pageIndex * 500;
        data = { pages: customers.slice(offset, offset + 500), total_data: customers.length };
      }
      return route.fulfill({ json: { data } });
    }
    if (url.origin !== 'http://127.0.0.1:5173') return route.abort();
    return route.continue();
  });
  const initialLastPage = page.waitForResponse(r => r.url().includes('/customer/paginate') && new URL(r.url()).searchParams.get('page') === '10');
  await page.goto('http://127.0.0.1:5173/master/plafons');
  await initialLastPage;
  await page.getByRole('heading', { name: 'Master Plafon', exact: true }).waitFor();
  await page.getByRole('button', { name: '+ Plafon', exact: true }).click();
  const branch = page.getByPlaceholder('Pilih cabang', { exact: true }).last();
  await branch.click();
  await page.getByRole('button', { name: 'SLO - Solo', exact: true }).click();
  await page.getByPlaceholder('Pilih perusahaan', { exact: true }).last().click();
  await page.getByRole('button', { name: 'BMM - Perusahaan', exact: true }).click();
  const customer = page.getByPlaceholder('Pilih customer', { exact: true });
  await customer.fill('Customer baru');
  await page.getByRole('button', { name: 'NEW - Customer baru', exact: true }).waitFor();
  assert.ok(customerLoads >= 2, 'Opening form must refresh customers loaded on page mount');
  await page.getByRole('button', { name: 'NEW - Customer baru', exact: true }).click();
  await customer.fill('Customer lama');
  assert.equal(await page.getByRole('button', { name: /^OLD/ }).count(), 0);
  assert.deepEqual(errors, []);
  console.log('PASS: customer beyond 5,000 appears after refresh via secondary branch; other branches stay excluded.');
} finally {
  await browser.close();
}
