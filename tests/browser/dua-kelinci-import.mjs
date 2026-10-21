// All API traffic is mocked. Never upload or create orders on a real server.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.DK_TEST_ORIGIN || 'http://127.0.0.1:5196';
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, headless: true });
const prefix = '/api/extra/data-import/dua-kelinci';
const fixture = (status = 'need_review', total = '9435.0000') => ({
  batch: { id: 12, import_code: 'SOIMP-SYNTHETIC-DK', status, id_perusahaan: 1, id_cabang: 5, id_principal: 88 },
  principal_mapping: { id: 88, kode: 'DK-TMP', nama: 'Dua Kelinci tujuan' },
  source_detail_count: 3,
  excluded_rows: [{row_number:78,order_no:'DK1002',product_code:'SKU-REJECT-ONLY',quantity:'0',reason:'REJECT=1 dan QTY=0'}],
  rows: [
    { id: 1, row_type: 'header', order_no: 'DK1001', order_date: '2026-10-19', customer_code: 'OUTLET-TEST', sales_code: 'S-TEST', subtotal: total,
      validation_status: status === 'need_review' ? 'error' : 'valid', validation_message: status === 'need_review' ? 'Customer tidak ditemukan' : '',
      raw_data: status === 'need_review' ? {} : { _resolved_customer_code: 'C-TEST', _resolved_customer_name: 'Outlet contoh' } },
    ...[false, true].map((bonus, i) => ({ id: i + 2, row_type: 'detail', row_number: i + 2, order_no: 'DK1001', product_code: 'SKU-DK', customer_code: 'OUTLET-TEST', quantity: 10,
      validation_status: status === 'need_review' ? 'error' : 'valid', validation_message: '',
      raw_data: { _product_name: 'Produk DK contoh', _is_bonus: bonus, _bonus_reason: bonus ? 'SKU berulang dalam SO (aturan bridging)' : '',
        _finance: { unit_price: total === '20535.0000' ? '2000.0000' : '1000.0000',
          discount_amount: bonus ? (total === '20535.0000' ? '20000.0000' : '10000.0000') : '1500.0000',
          dpp: bonus ? '0.0000' : (total === '20535.0000' ? '18500.0000' : '8500.0000'),
          tax_rate: '11.0000', tax_amount: bonus ? '0.0000' : (total === '20535.0000' ? '2035.0000' : '935.0000'), total: bonus ? '0.0000' : total } } }))
  ]
});
try {
  for (const theme of ['light', 'dark']) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.setDefaultTimeout(10000);
    const errors = [], writes = [];
    let payload = fixture(), processCount = 0;
    page.on('pageerror', error => errors.push(error.message));
    const user = { id: 1, nama: 'Penguji contoh', id_perusahaan: 1, id_cabang: 5, jabatan: { nama: 'PETUGAS' } };
    await page.addInitScript(({ user, theme }) => {
      localStorage.setItem('budimas_internal_auth', JSON.stringify({ access_token: 'synthetic-only', user, permissions: ['*'], menus: [] }));
      localStorage.setItem('budimas-theme', theme);
    }, { user, theme });
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url()), path = url.pathname;
      if (!path.startsWith('/api/')) return url.origin === origin ? route.continue() : route.abort();
      if (request.method() !== 'GET') writes.push(path);
      let result = [];
      if (path.includes('/auth/') || path.includes('detail-login')) result = { user, permissions: ['*'], menus: [] };
      else if (path.endsWith('/getPerusahaan')) result = [{ id: 1, kode: 'BMM', nama: 'Budimas contoh', id_cabang_list: '5' }];
      else if (path.endsWith('/getCabang')) result = [{ id: 5, kode: 'SLO', nama: 'SOLO', id_perusahaan: 1 }];
      else if (path.endsWith('/getPrincipal')) result = [
        { id: 88, kode: 'DK-TMP', nama: 'Dua Kelinci tujuan', id_perusahaan: 1, aktif: true },
        { id: 90, kode: 'DK-LAIN', nama: 'Perusahaan lain', id_perusahaan: 2, aktif: true },
        { id: 91, kode: 'DK-NONAKTIF', nama: 'Principal nonaktif', id_perusahaan: 1, aktif: false }
      ];
      else if (path === prefix + '/preview') {
        assert.match(request.headers()['content-type'], /^multipart\/form-data; boundary=/);
        assert.match(request.postData(), /name="excel_file"/);
        assert.match(request.postData(), /name="id_cabang"\r\n\r\n5/);
        assert.match(request.postData(), /name="id_principal"\r\n\r\n88/);
        payload = fixture(); result = payload;
      } else if (path.endsWith('/customers')) result = [{ id: 10, kode: 'C-TEST', nama: 'Outlet contoh' }];
      else if (path.endsWith('/customer-mapping')) {
        assert.deepEqual(request.postDataJSON(), { outlet_code: 'OUTLET-TEST', id_customer: 10 });
        payload = fixture('ready'); result = payload;
      } else if (path.endsWith('/process')) {
        processCount += 1;
        if (processCount === 1) {
          payload = fixture('ready', '20535.0000');
          return route.fulfill({ status: 409, json: { message: 'Master/harga/mapping berubah. Tinjau preview terbaru sebelum Import ulang.', result: payload } });
        }
        payload.batch.status = 'processed';
        result = { processed_order_count: 1, processed_order_ids: [123], message: 'Sales Order dibuat. Lanjutkan di Distribusi → Approval Order.' };
      } else if (path === prefix + '/batches/12') result = payload;
      return route.fulfill({ json: { status: 'success', result } });
    });
    await page.goto(origin + '/data-tools/import-dua-kelinci');
    await page.getByRole('heading', { name: '1. File dan tujuan import', exact: true }).waitFor();
    const file = page.getByLabel('File export Dua Kelinci');
    await file.setInputFiles({ name: 'contoh.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: Buffer.from('mock-only') });
    // Never guess a principal, even if only one active option exists.
    assert.equal(await page.getByRole('button', { name: 'Preview File', exact: true }).isDisabled(), true);
    const principal = page.getByPlaceholder('Pilih principal tujuan Dua Kelinci', { exact: true });
    await principal.click();
    await page.getByRole('option', { name: 'DK-TMP — Dua Kelinci tujuan', exact: true }).waitFor();
    assert.equal(await page.getByRole('option', { name: /DK-LAIN|DK-NONAKTIF/ }).count(), 0);
    await page.getByRole('option', { name: 'DK-TMP — Dua Kelinci tujuan', exact: true }).click();
    await page.getByRole('button', { name: 'Preview File', exact: true }).click();
    await page.getByRole('region', { name: 'Tujuan mapping principal', exact: true }).getByText('DK-TMP — Dua Kelinci tujuan', { exact: true }).waitFor();
    await page.getByRole('cell', { name: 'Customer tidak ditemukan', exact: true }).waitFor();
    await page.getByRole('heading', {name:'1 baris sumber dilewati',exact:true}).waitFor();
    await page.getByRole('cell', {name:'SKU-REJECT-ONLY',exact:true}).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Import ke Sales Order', exact: true }).isDisabled(), true);
    assert.match(page.url(), /batch_id=12/);
    const outlet = page.getByText('OUTLET_CODE dari file', { exact: true }).locator('..').getByRole('combobox');
    await outlet.click();
    await page.getByRole('option', { name: 'OUTLET-TEST', exact: true }).click();
    await page.getByPlaceholder('Cari kode/nama customer', { exact: true }).fill('Outlet');
    await page.getByRole('option', { name: 'C-TEST — Outlet contoh', exact: true }).click();
    await page.getByRole('button', { name: 'Simpan Mapping & Validasi', exact: true }).click();
    await page.getByRole('cell', { name: 'OUTLET-TEST C-TEST · Outlet contoh', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Import ke Sales Order', exact: true }).click();
    await page.getByText('Principal tujuan: DK-TMP — Dua Kelinci tujuan', { exact: true }).waitFor();
    await page.getByText('1 baris REJECT=1 dan QTY=0 tidak ikut dibuat menjadi detail order.',{exact:true}).waitFor();
    assert.equal(processCount, 0);
    await page.getByRole('button', { name: 'Ya, Import', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'Master/harga/mapping berubah' }).waitFor();
    await page.getByRole('cell', { name: 'Rp 20.535', exact: true }).waitFor();
    assert.equal(await page.locator('.dk-panel').first().evaluate(el => getComputedStyle(el).backgroundColor), theme === 'dark' ? 'rgb(15, 23, 42)' : 'rgb(255, 255, 255)');
    await page.screenshot({ path: `/tmp/budimas-dua-kelinci-${theme}.png`, fullPage: true, animations: 'disabled' });
    await page.setViewportSize({ width: 420, height: 900 });
    await page.waitForFunction(() => document.querySelector('aside').getBoundingClientRect().right <= 1);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await page.screenshot({ path: `/tmp/budimas-dua-kelinci-${theme}-mobile.png`, fullPage: true, animations: 'disabled' });
    await page.getByRole('button', { name: 'Import ke Sales Order', exact: true }).click();
    await page.getByRole('button', { name: 'Ya, Import', exact: true }).click();
    await page.getByText('Batch sudah diimpor.', { exact: false }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Import ke Sales Order', exact: true }).isDisabled(), true);
    assert.equal(await page.getByRole('button', { name: 'Simpan Mapping & Validasi', exact: true }).count(), 0);
    await page.waitForFunction(() => !document.querySelector('input[type="file"]').disabled);
    await file.setInputFiles({ name: 'lain.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: Buffer.from('mock-only-2') });
    await page.waitForURL(origin + '/data-tools/import-dua-kelinci');
    await page.getByRole('button', { name: 'Import ke Sales Order', exact: true }).waitFor({ state: 'detached' });
    assert.equal(await page.getByRole('heading',{name:'1 baris sumber dilewati',exact:true}).count(),0);
    assert.equal(await page.getByRole('button', { name: 'Import ke Sales Order', exact: true }).count(), 0);
    assert.equal(await page.getByRole('alert').count(), 0);
    assert.deepEqual(writes, [prefix + '/preview', prefix + '/batches/12/customer-mapping', prefix + '/batches/12/process', prefix + '/batches/12/process']);
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log('PASS: light/dark, narrow layout, explicit non-76 principal mapping, company/active option filtering, scoped outlet mapping, multipart preview, target confirmation, 409 re-review, processed guard, file reset; all APIs mocked.');
} finally { await browser.close(); }
