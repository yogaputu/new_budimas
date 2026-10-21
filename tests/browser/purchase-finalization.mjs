// Production-build UI QA, entirely mocked. Never posts to a real ERP endpoint.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.PURCHASE_TEST_ORIGIN || 'http://127.0.0.1:5199';
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH });
try {
  for (const theme of ['light', 'dark']) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [], posts = [];
    page.on('pageerror', error => errors.push(error.message));
    const user = { id: 1, nama: 'Penguji', id_cabang: 5, id_perusahaan: 1, jabatan: { nama: 'SUPER USER' } };
    await page.addInitScript(({ user, theme }) => {
      localStorage.setItem('budimas_internal_auth', JSON.stringify({ access_token: 'mock-only', user, permissions: ['*'], menus: [] }));
      localStorage.setItem('budimas-theme', theme);
    }, { user, theme });
    const row = { id: 101, no_transaksi: 'RC-TEST', proses_id_berjalan: 2, subtotal: 2000,
      cabang_id: 5, cabang_nama: 'Solo', principal_id: 5, principal_nama: 'Principal', order_kode: 'PO-TEST' };
    const detail = { ...row, detail: [{ id: 10001, detail_id: 10001, produk_kode: 'SKU', produk_nama: 'Produk fixture',
      subtotal: 2000, dpp_gross: '2000.00', quantity_pcs: 24, tax_rate: '11',batch_number:'BATCH-1',tanggal_expired:'2028-12-31',
      jumlah: [{ jumlah: 2, uom_kode: 'CT', uom_faktor_konversi: 12,uom_harga_beli:1000 },
        {jumlah:0,uom_kode:'PCS',uom_faktor_konversi:1,uom_harga_beli:83.333333},
        {jumlah:0,uom_kode:'BOX',uom_faktor_konversi:120,uom_harga_beli:10000},
        {jumlah:0,uom_kode:'PALLET',uom_faktor_konversi:1200,uom_harga_beli:100000}] }] };
    let done = false;
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url()), path = url.pathname;
      if (!path.startsWith('/api/')) return url.origin === origin ? route.continue() : route.abort();
      let data = [];
      if (path.includes('/auth/') || path.includes('detail-login')) data = { user, permissions: ['*'], menus: [] };
      else if (path.endsWith('/getPerusahaan')) data = [{ id: 1, nama: 'BMM', id_cabang_list: '5' }];
      else if (path.endsWith('/getCabang')) data = [{ id: 5, nama: 'Solo', id_perusahaan: 1 }];
      else if (path.endsWith('/getPrincipal')) data = [{ id: 5, nama: 'Principal', id_perusahaan: 1 }];
      else if (path.endsWith('/daftar-konfirmasi')) data = done ? [] : [row];
      else if (path.endsWith('/detail-riwayat/101')) data = detail;
      else if (path.endsWith('/proses/konfirmasi')) { posts.push(request.postDataJSON()); done = true; data = { status: 'success' }; }
      return route.fulfill({ json: { data } });
    });
    await page.goto(origin + '/purchase/confirmations');
    await page.getByText('RC-TEST', { exact: true }).click();
    await page.getByTestId('total-pcs').waitFor();
    assert.match(await page.getByTestId('total-pcs').innerText(), /24 PCS/);
    const table=page.getByRole('table',{name:'Tabel finalisasi produk'});
    assert.deepEqual(await table.getByRole('columnheader').allTextContents(),[
      'Kode Produk','Nama Produk','Batch','Expired','Rincian UOM','TOTAL (PCS)','Harga Pricelist','Diskon','Harga Bersih']);
    assert.match(await table.innerText(),/BATCH-1/);assert.match(await table.innerText(),/2028-12-31/);
    assert.match(await table.innerText(),/PALLET/);
    await page.getByLabel('Jatuh Tempo', { exact: true }).fill('2026-11-20');
    await page.getByRole('combobox', { name: 'Jenis diskon produk 1', exact: true }).click();
    await page.getByRole('option', { name: 'Persen (%)', exact: true }).click();
    await page.getByLabel('Diskon produk 1 (%)', { exact: true }).fill('10');
    await page.getByRole('combobox', { name: 'Jenis diskon keseluruhan', exact: true }).click();
    await page.getByRole('option', { name: 'Persen (%)', exact: true }).click();
    await page.getByLabel('Diskon keseluruhan (%)', { exact: true }).fill('5');
    await page.getByLabel('Total finalisasi').getByText('Rp 1.898,1', { exact: true }).waitFor();
    await page.getByLabel('Diskon keseluruhan (%)', { exact: true }).fill('101');
    assert.ok(await page.getByRole('button', { name: 'Finalisasi Purchase Order', exact: true }).isDisabled());
    await page.getByLabel('Diskon keseluruhan (%)', { exact: true }).fill('5');
    await page.screenshot({ path: `/tmp/purchase-finalization-${theme}.png`, fullPage: true });
    await page.setViewportSize({ width: 420, height: 900 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: `/tmp/purchase-finalization-${theme}-mobile.png`, fullPage: true });
    await page.getByRole('button', { name: 'Finalisasi Purchase Order', exact: true }).click();
    await page.getByTestId('total-pcs').waitFor({ state: 'hidden' });
    assert.equal(posts.length, 1);assert.equal(posts[0].discount_type, 'PERCENT');
    assert.equal(posts[0].discount_value, '5');
    assert.deepEqual(posts[0].line_discounts, [{ detail_id: 10001, discount_type: 'PERCENT', discount_value: '10' }]);
    assert.deepEqual(errors, []);await page.close();
    console.log(`PASS ${theme}: percent/rupiah controls, totals, invalid discount, mobile layout, mock finalization`);
  }
} finally { await browser.close(); }
