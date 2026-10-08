// Browser regression with all application APIs intercepted.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, args: ['--no-sandbox'] });
try {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const user = { id:1, id_user:1, nama:'Test Admin', is_superuser:true, role:'superadmin', id_cabang:1 };
  await page.addInitScript(user => localStorage.setItem('budimas_internal_auth', JSON.stringify({ access_token:'test-only',user,permissions:['*'],menus:[] })), user);
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (!url.pathname.startsWith('/api/')) return url.origin === 'http://127.0.0.1:5173' ? route.continue() : route.abort();
    let data = [];
    if (/detail-login|\/auth\//.test(url.pathname)) data = {user,permissions:['*'],menus:[]};
    else if (url.pathname.includes('getCabang')) data = [{id:1,kode:'SLO',nama:'Solo'}];
    else if (url.pathname.endsWith('/wms/pallets')) data = [
      {id:1,id_cabang:1,kode_pallet:'PAL1',tipe_pallet:'Standard',status_pallet:'Aktif',active:true,used_qty_pcs:100,kode_rak_list:'B1'},
      {id:2,id_cabang:1,kode_pallet:'PAL2',tipe_pallet:'Standard',status_pallet:'Nonaktif',active:true,used_qty_pcs:0}
    ];
    return route.fulfill({json:{data}});
  });
  await page.goto('http://127.0.0.1:5173/wms/master-pallet');
  const row = page.getByRole('row').filter({has:page.getByRole('cell',{name:'PAL1',exact:true})});
  await row.waitFor();
  assert.match(await row.innerText(), /Aktif/);
  await row.getByRole('cell',{name:'B1',exact:true}).waitFor();
  await row.getByRole('cell',{name:'100',exact:true}).waitFor();
  assert.equal(await page.locator('option[value="Terisi"]').count(), 0);
  assert.equal(await page.locator('option[value="Rusak"]').count(), 0);
  await row.click();
  await page.getByText('Pallet layak digunakan (hapus centang jika rusak)',{exact:true}).waitFor();
  await page.getByText('Otomatis: Aktif jika berisi; Nonaktif jika kosong atau tidak layak digunakan.',{exact:true}).waitFor();
  assert.deepEqual(errors,[]);
  console.log('PASS ERP Master Pallet: live quantity/location, two occupancy statuses, physical usability control.');
} finally { await browser.close(); }
