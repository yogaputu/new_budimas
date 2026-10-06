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
      else if (url.pathname === '/api/base/customer/all') {
        customerLoads++;
        data = [{ id: 1, kode: 'OLD', nama: 'Customer lama', id_cabang: 1 }];
        if (customerLoads > 1) data.push({ id: 2, kode: 'NEW', nama: 'Customer baru', id_cabang: 1 }, { id: 3, kode: 'OTHER', nama: 'Cabang lain', id_cabang: 2 });
      }
      return route.fulfill({ json: { data } });
    }
    if (url.origin !== 'http://127.0.0.1:5173') return route.abort();
    return route.continue();
  });
  await page.goto('http://127.0.0.1:5173/master/plafons');
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
  await customer.fill('Cabang lain');
  assert.equal(await page.getByRole('button', { name: 'OTHER - Cabang lain', exact: true }).count(), 0);
  assert.deepEqual(errors, []);
  console.log('PASS: new customer appears without page reload; other branch stays excluded.');
} finally {
  await browser.close();
}
