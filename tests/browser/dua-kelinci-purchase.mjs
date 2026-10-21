// Mock-only browser QA. No real orders, token or API/server writes.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.DK_PO_TEST_ORIGIN || 'http://127.0.0.1:5198';
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH });
const prefix = '/api/extra/data-import/dua-kelinci/purchase';
const units = [{ id: 101, level: 1, nama: 'PAK', faktor_konversi: 1 }, { id: 104, level: 4, nama: 'KRT', faktor_konversi: 120 }];
const product = { id: 100, kode_sku: '000-DK', nama: 'Produk contoh', harga_beli: null, ppn_rate: null, uoms: units };
function fixture(status = 'need_review', revision = 2, price = '1000') {
  const ready = status !== 'need_review';
  return {
    batch: { id: 12, id_perusahaan: 1, id_cabang: 14, id_principal: 246, source_ref: 'INVTR-CONTOH', filename: 'synthetic.xls', quantity_basis: 'terima', status, revision },
    principal_mapping: { id: 246, kode: 'DK-BMM', nama: 'PT DUA KELINCI' },
    source: { source_date: '2026-10-03', distributor: 'Distributor contoh', shipment_ref: 'KIRIM-CONTOH', warnings: ['Metadata OLE dibaca dalam mode kompatibilitas.'] },
    preview: { complete: ready, error_count: ready ? 0 : 1, totals: { dpp: ready ? String(240 * Number(price)) : '0', tax_amount: '0', total: ready ? String(240 * Number(price)) : '0' }, rows: [{
      row_number: 15, product_code: '000-DK', product_name: 'Produk sumber', delivery_ref: 'SJ-CONTOH',
      kirim: [{ quantity: 2, unit: 'KRT' }, ...Array.from({ length: 4 }, () => ({ quantity: 0, unit: '' }))],
      terima: [{ quantity: 2, unit: 'KRT' }, ...Array.from({ length: 4 }, () => ({ quantity: 0, unit: '' }))],
      product, uoms: units, override: ready ? { id_produk: 100, price, ppn: '0', uom_ids: [null, null, null, null, null] } : {},
      warnings: [], errors: ready ? [] : ['Harga beli satuan dasar wajib diisi.'],
      resolved: ready ? { nama: product.nama, total_base: 240, base_unit: 'PAK', price, ppn: '0', total: String(240 * Number(price)) } : null
    }] }, order: status === 'processed' ? { id: 123, kode: 'PO/DK/202610/00000123', proses_id_berjalan: 2 } : null
  };
}
try {
  for (const theme of ['light', 'dark']) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, colorScheme: theme === 'dark' ? 'light' : 'dark' });
    page.setDefaultTimeout(10000);
    const errors = [], writes = [];
    let payload = fixture(), processCount = 0;
    const user = { id: 1, nama: 'Penguji contoh', id_perusahaan: 1, id_cabang: 14, jabatan: { nama: 'PETUGAS' } };
    page.on('pageerror', (error) => errors.push(error.message));
    await page.addInitScript(({ user, theme }) => {
      localStorage.setItem('budimas_internal_auth', JSON.stringify({ access_token: 'mock-only', user, permissions: ['*'], menus: [] }));
      localStorage.setItem('budimas-theme', theme);
    }, { user, theme });
    await page.route('**/*', async (route) => {
      const request = route.request(), url = new URL(request.url()), path = url.pathname;
      if (!path.startsWith('/api/')) return url.origin === origin ? route.continue() : route.abort();
      if (request.method() !== 'GET') writes.push(path);
      let result = [];
      if (path.includes('/auth/') || path.includes('detail-login')) result = { user, permissions: ['*'], menus: [] };
      else if (path.endsWith('/getPerusahaan')) result = [{ id: 1, nama: 'Budimas contoh', kode: 'BMM', id_cabang_list: '14' }];
      else if (path.endsWith('/getCabang')) result = [{ id: 14, nama: 'Salatiga', kode: 'SLTG', id_perusahaan: 1 }];
      else if (path.endsWith('/getPrincipal')) result = [
        { id: 246, kode: 'DK-BMM', nama: 'PT DUA KELINCI', id_perusahaan: 1, aktif: true },
        { id: 247, kode: 'OTHER', nama: 'Principal lain', id_perusahaan: 1, aktif: true },
        { id: 248, kode: 'DK-LAIN', nama: 'PT DUA KELINCI', id_perusahaan: 2, aktif: true }
      ];
      else if (path === prefix + '/preview') {
        assert.match(request.postData(), /name="quantity_basis"\r\n\r\nterima/);
        assert.match(request.postData(), /name="id_principal"\r\n\r\n246/);
        result = payload;
      } else if (path === prefix + '/batches') result = [{ id: 12, source_ref: 'INVTR-CONTOH', status: payload.batch.status }];
      else if (path.endsWith('/products')) result = [product];
      else if (path.endsWith('/review')) {
        assert.deepEqual(request.postDataJSON(), { revision: 2, quantity_basis: 'terima', lines: [{ row_number: 15, id_produk: 100, price: '1000', ppn: '0', uom_ids: [null, null, null, null, null] }] });
        payload = fixture('ready', 3); result = payload;
      } else if (path.endsWith('/process')) {
        processCount++;
        assert.deepEqual(request.postDataJSON(), { revision: processCount === 1 ? 3 : 4, confirm: true });
        if (processCount === 1) {
          payload = fixture('ready', 4, '1200');
          return route.fulfill({ status: 409, json: { message: 'Master/harga/UOM berubah. Tinjau preview terbaru lalu konfirmasi kembali.', result: payload } });
        }
        payload = fixture('processed', 5, '1200'); result = payload;
      } else if (path === prefix + '/batches/12') result = payload;
      return route.fulfill({ json: { status: 'success', result } });
    });
    await page.goto(origin + '/purchase/import-dua-kelinci');
    await page.getByRole('heading', { name: '1. File dan tujuan pembelian', exact: true }).waitFor();
    await page.getByLabel('File pembelian Dua Kelinci').setInputFiles({ name: 'synthetic.xls', mimeType: 'application/vnd.ms-excel', buffer: Buffer.from('mock-only') });
    assert.equal(await page.getByRole('button', { name: 'Preview File PO', exact: true }).isDisabled(), true);
    await page.getByPlaceholder('Pilih principal Dua Kelinci', { exact: true }).click();
    assert.equal(await page.getByRole('option', { name: /OTHER|DK-LAIN/ }).count(), 0);
    await page.getByRole('option', { name: 'DK-BMM — PT DUA KELINCI', exact: true }).click();
    await page.getByPlaceholder('Pilih Kirim atau Terima', { exact: true }).click();
    await page.getByRole('option', { name: 'QTY Terima', exact: true }).click();
    await page.getByRole('button', { name: 'Preview File PO', exact: true }).click();
    await page.getByText('Harga beli satuan dasar wajib diisi.', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Buat Draft PO', exact: true }).isDisabled(), true);
    assert.match(page.url(), /batch_id=12/);
    await page.getByRole('button', { name: 'Koreksi baris 15', exact: true }).click();
    await page.getByRole('heading', { name: 'Koreksi baris pembelian', exact: true }).waitFor();
    await page.getByLabel('Harga beli satuan dasar', { exact: true }).fill('1000');
    await page.getByLabel('PPN persen', { exact: true }).fill('0');
    await page.screenshot({ path: `/tmp/budimas-dk-po-${theme}-modal.png`, animations: 'disabled' });
    await page.getByRole('button', { name: 'Simpan Koreksi & Validasi', exact: true }).click();
    await page.getByRole('heading', { name: 'Koreksi baris pembelian', exact: true }).waitFor({ state: 'hidden' });
    await page.getByText('240 PAK', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Buat Draft PO', exact: true }).isDisabled(), false);
    assert.equal(await page.locator('.dkpo-panel').first().evaluate((el) => getComputedStyle(el).backgroundColor), theme === 'dark' ? 'rgb(15, 23, 42)' : 'rgb(255, 255, 255)');
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: `/tmp/budimas-dk-po-${theme}.png`, fullPage: true, animations: 'disabled' });
    await page.setViewportSize({ width: 420, height: 900 });
    await page.waitForFunction(() => document.querySelector('aside').getBoundingClientRect().right <= 1);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: `/tmp/budimas-dk-po-${theme}-mobile.png`, fullPage: true, animations: 'disabled' });
    await page.getByRole('button', { name: 'Buat Draft PO', exact: true }).click();
    assert.equal(processCount, 0);
    await page.getByRole('button', { name: 'Ya, Buat Draft PO', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'Master/harga/UOM berubah' }).waitFor();
    await page.getByRole('cell', { name: 'Rp 288.000', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Buat Draft PO', exact: true }).click();
    await page.getByRole('button', { name: 'Ya, Buat Draft PO', exact: true }).click();
    await page.getByText('PO PO/DK/202610/00000123 sudah dibuat. Status proses: 2.', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Buat Draft PO', exact: true }).count(), 0);
    assert.equal(processCount, 2); assert.deepEqual(errors, []);
    assert.equal(writes.every((path) => path.startsWith(prefix)), true);
    await page.reload();
    await page.getByText('PO PO/DK/202610/00000123 sudah dibuat. Status proses: 2.', { exact: true }).waitFor();
    await page.close();
  }
  console.log('Dua Kelinci PO browser QA passed: light/dark, mobile, correction, 409 re-review, confirm, resume, no real writes.');
} finally { await browser.close(); }
