// Presentation regression checks. Every API request is intercepted; no ERP data
// or live transaction is read or written, including when Vite has a remote proxy.
import assert from 'node:assert/strict';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.TEST_BASE_URL || 'http://127.0.0.1:5176';
assert.ok(['localhost', '127.0.0.1'].includes(new URL(origin).hostname));
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, headless: true });
const user = { id: 1, id_user: 1, nama: 'UI Test Admin', is_superuser: true, role: 'superadmin', id_cabang: 5, id_perusahaan: 1 };
const claim = {
  id: 1, number: 'CLM-UI-001', principal_name: 'Principal UI', company_name: 'BMM',
  kind: 'PROMO', status: 'SUBMITTED', requested_amount: 110000, requested_method: 'CREDIT',
  approved_amount: 0, approved_method: null, period_from: '2026-10-01', period_to: '2026-10-15',
  note: 'Pengujian tampilan', lines: [], history: [], goods: [], revision: 1
};
let checks = 0;

async function responsive(page, label) {
  for (const width of [390, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${label}: page overflow at ${width}`);
    for (const button of await page.locator('.workflow-btn:visible').all()) {
      const box = await button.boundingBox();
      assert.ok(box.height >= 43, `${label}: button target too small`);
    }
    checks++;
  }
}

async function hasContrast(locator, label) {
  const ratio = await locator.evaluate(el => {
    const luminance = color => {
      const c = color.match(/[\d.]+/g).slice(0, 3).map(Number).map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
      return c[0] * .2126 + c[1] * .7152 + c[2] * .0722;
    };
    const s = getComputedStyle(el), a = luminance(s.color), b = luminance(s.backgroundColor);
    return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
  });
  assert.ok(ratio >= 4.5, `${label}: contrast ${ratio.toFixed(2)}`);
  checks++;
}

try {
  for (const theme of ['light', 'dark']) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    await context.addInitScript(({ user, theme }) => {
      localStorage.setItem('budimas_internal_auth', JSON.stringify({ access_token: 'test-only', user, permissions: ['*'], menus: [] }));
      localStorage.setItem('budimas-theme', theme);
    }, { user, theme });
    const errors = [], writes = [];
    let locked = true, rejectDraft = false, picked = 0;
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url()), path = url.pathname;
      if (!path.startsWith('/api/')) return url.origin === origin ? route.continue() : route.abort();
      let data = [];
      if (request.method() !== 'GET' && request.method() !== 'OPTIONS') writes.push({ path, payload: request.postDataJSON() });
      if (path.includes('detail-login') || path.includes('/auth/')) data = { user, permissions: ['*'], menus: [] };
      else if (path.includes('getPerusahaan')) data = [{ id: 1, kode: 'BMM', nama: 'BMM', id_cabang_list: '5' }];
      else if (path.includes('getCabang')) data = [{ id: 5, id_perusahaan: 1, kode: 'SLO', nama: 'Solo' }];
      else if (path.includes('getPrincipal')) data = [{ id: 1, id_perusahaan: 1, kode: 'P3', nama: 'Principal UI' }];
      else if (path.endsWith('/picking/shipments')) data = [{ reference: 'DRF-5-3785', delivering_date: '2026-10-14', note_count: 1 }];
      else if (path.includes('/picking/draft-detail/')) {
        if (rejectDraft) return route.fulfill({ status: 500, json: { message: 'Draf uji tidak dapat dimuat.' } });
        data = {
          document: { shipment_reference: 'DRF-5-3785', status: locked ? 'LOADED' : 'PICKING', task_statuses: [locked ? 'LOADED' : 'PICKING'], task_ids: [11] },
          items: [{ wms_task_detail_id: 21, wms_task_id: 11, id_produk: 1, id_sales_order_detail: 31, nota: 'NPBMMSLO-2610000014', product_code: 'P3P1', product_name: 'P3 - Produk 1', required_quantity: 90, picked_quantity: locked ? 90 : picked, stok_ready: 800, rack_available_quantity: 800, rak_tetap: 'G99R01L0K01N05', batch: 'TEST', expired_date: '2027-10-14' }]
        };
      } else if (path.endsWith('/picking/scan-rak')) { picked = 90; data = { status: 'OK', msg: 'Picking tersimpan.' }; }
      else if (path.endsWith('/loading/assignments')) data = [{ id_armada: 1, id_driver: 2, vehicle: 'AD 9728 TA', driver: 'Driver UI', delivery_date: '2026-10-15' }];
      else if (path.endsWith('/loading/ready-to-load')) data = [{ ScheduleKey: 'S1', ArmadaRencana: 'AD 9728 TA', DriverRencana: 'Driver UI', HelperRencana: 'Helper UI', ScheduledDeliveryDate: '2026-10-15', ShipmentReference: 'DRF-5-3785', Nota: 'NPBMMSLO-2610000014', KodeBarang: 'P3P1', NamaBarang: 'P3 - Produk 1', PerUnit: 12, required_quantity: 91, picked_quantity: 91, wms_task_detail_id: 21, loading_status: 'LOADING', loaded_cartons: 0, loaded_pieces: 0, loading_verified: false }];
      else if (path.endsWith('/principal-claims/accounts')) data = [{ id: 1, login: 'principal-ui', display_name: 'Principal UI', principal_name: 'Principal UI', company_name: 'BMM', active: true }];
      else if (path.endsWith('/principal-claims/1')) data = claim;
      else if (path.endsWith('/principal-claims')) data = { rows: [claim], total: 1 };
      else if (path.endsWith('/principal-portal/login')) data = { token: 'portal-test-only', user: { display_name: 'Principal UI' } };
      else if (path.endsWith('/principal-portal/claims')) data = { rows: [claim], total: 1 };
      else if (path.endsWith('/principal-portal/claims/1')) data = claim;
      return route.fulfill({ json: { data } });
    });
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(origin + '/distribution/picking');
    await page.getByRole('combobox', { name: 'Pilih draf', exact: true }).waitFor();
    await page.getByRole('combobox', { name: 'Pilih draf', exact: true }).fill('DRF-5-3785');
    await page.getByRole('option', { name: /DRF-5-3785/ }).click();
    await page.getByText('LOADED', { exact: true }).waitFor();
    assert.ok(await page.getByRole('button', { name: 'Pick nota ini', exact: true }).isDisabled());
    assert.equal(await page.getByRole('button', { name: 'Picking Draf Kiriman', exact: true }).getAttribute('aria-pressed'), 'true');
    await hasContrast(page.locator('.workflow-btn-primary').first(), `Picking primary ${theme}`);
    await hasContrast(page.locator('.workflow-table th').first(), `Table heading ${theme}`);
    await responsive(page, `Picking ${theme}`);
    await page.screenshot({ path: `/tmp/budimas-ui-picking-${theme}.png`, fullPage: true });
    await page.getByRole('combobox', { name: 'Tampilan', exact: true }).fill('nota');
    await page.getByRole('option', { name: 'By nota', exact: true }).click();
    assert.equal(await page.getByLabel('Qty P3P1', { exact: true }).inputValue(), '0');
    locked = false;
    await page.getByRole('button', { name: 'Muat draf', exact: true }).click();
    await page.getByText('PICKING', { exact: true }).waitFor();
    await page.getByLabel('Qty P3P1', { exact: true }).fill('91');
    assert.ok(await page.getByRole('button', { name: 'Pick nota ini', exact: true }).isDisabled());
    await page.getByLabel('Qty P3P1', { exact: true }).fill('90');
    await page.getByRole('button', { name: 'Pick nota ini', exact: true }).click();
    await page.getByRole('status').filter({ hasText: 'Picking tersimpan.' }).waitFor();
    assert.deepEqual(writes.at(-1), { path: '/api/picking/picking/scan-rak', payload: { shipment_reference: 'DRF-5-3785', nota: 'DRF-5-3785', wms_task_detail_id: 21, kode_rak: 'G99R01L0K01N05', kode_barang: 'P3P1', batch: 'TEST', expired_date: '2027-10-14', qty_pcs: 90 } });
    assert.ok(await page.getByRole('button', { name: 'Selesai Picking → Checker', exact: true }).isDisabled());
    await page.getByLabel('Nama picker', { exact: true }).fill('Picker UI');
    assert.ok(await page.getByRole('button', { name: 'Selesai Picking → Checker', exact: true }).isEnabled());
    rejectDraft = true;
    await page.getByRole('button', { name: 'Muat draf', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'Draf uji' }).waitFor();
    checks += 8;

    for (const [path, action] of [
      ['/purchase/principal-claims', 'Ajukan klaim promo'],
      ['/purchase/returns', 'Ajukan Retur / Pemusnahan'],
      ['/purchase/principal-accounts', 'Buat akun']
    ]) {
      await page.goto(origin + path);
      await page.getByRole('button', { name: action, exact: true }).click();
      await page.locator('.workflow-ui [role="combobox"]').first().waitFor();
      await responsive(page, `${path} ${theme}`);
      if (path.endsWith('principal-claims')) await page.screenshot({ path: `/tmp/budimas-ui-claims-${theme}.png`, fullPage: true });
    }

    await page.goto(origin + '/wms');
    await page.locator('.workflow-flow-step').first().waitFor();
    await hasContrast(page.locator('.workflow-flow-step').first(), `WMS flow card ${theme}`);
    await page.getByRole('button', { name: 'Loading', exact: true }).click();
    await page.getByRole('combobox', { name: 'Armada', exact: true }).fill('9728');
    await page.getByRole('option', { name: 'AD 9728 TA', exact: true }).click();
    await page.getByRole('combobox', { name: 'Driver', exact: true }).fill('Driver UI');
    await page.getByRole('option', { name: 'Driver UI', exact: true }).click();
    await page.getByLabel('Tanggal pengiriman', { exact: true }).fill('2026-10-15');
    await page.getByRole('button', { name: 'Tampilkan barang', exact: true }).click();
    await page.getByRole('button', { name: 'Isi Full', exact: true }).click();
    assert.equal(await page.getByLabel('CT / unit', { exact: true }).inputValue(), '7');
    assert.equal(await page.getByLabel('PCS lepas', { exact: true }).inputValue(), '7');
    await page.getByLabel('Sudah diperiksa dan sesuai', { exact: true }).check();
    await responsive(page, `Loading ${theme}`);
    await page.screenshot({ path: `/tmp/budimas-ui-loading-${theme}.png`, fullPage: true });
    checks += 3;

    await page.goto(origin + '/principal-portal');
    await page.getByLabel('Username / email', { exact: true }).fill('principal-ui');
    await hasContrast(page.locator('.workflow-input').first(), `Portal field ${theme}`);
    await responsive(page, `Portal login ${theme}`);
    await page.getByLabel('Password', { exact: true }).fill('ui-test-not-a-real-password');
    await page.getByRole('button', { name: 'Masuk', exact: true }).click();
    await page.getByRole('button', { name: 'Tinjau', exact: true }).click();
    await page.getByRole('heading', { name: 'Keputusan principal', exact: true }).waitFor();
    await responsive(page, `Portal detail ${theme}`);
    assert.ok(!writes.some(r => /settlements|dispatch|fulfilments|decision/.test(r.path)), 'No financial mutations allowed in UI tests');
    assert.deepEqual(errors, [], `No browser errors (${theme})`);
    await context.close();
  }
  console.log(`PASS ${checks} UI checks: light/dark, 390/768/1440px, Picking, Loading, claims, returns, accounts, portal, unchanged picking payload and CT/PCS allocation.`);
} finally {
  await browser.close();
}
