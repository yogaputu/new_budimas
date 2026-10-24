// All API requests are mocked. No live financial transactions are changed.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.PURCHASE_TEST_ORIGIN || 'http://127.0.0.1:5199';
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH });
const invoices = ['PJBMMSLO-2610000001', 'PJBMMSLO-2610000004'];
const lines = [
  { id_jurnal_detail: 1693, nama_akun: 'Penerimaan Belum Teridentifikasi', kode_jurnal: '2-20207',
    keterangan: `Penerimaan pembayaran KW-7 | ${invoices[0]} | NTN-0002`, no_faktur: invoices[0],
    sumber_dana: 'NTN-0002', workflow_source: 'NTN-0002', debit: 99900, kredit: 0 },
  { id_jurnal_detail: 1694, nama_akun: 'Piutang Usaha', kode_jurnal: '1-10100',
    keterangan: 'Pelunasan faktur', no_faktur: invoices[0], workflow_source: 'KW-7', debit: 0, kredit: 99900 },
  { id_jurnal_detail: 1695, nama_akun: 'Penerimaan Belum Teridentifikasi', kode_jurnal: '2-20207',
    keterangan: `Penerimaan pembayaran KW-7 | ${invoices[1]} | NTN-0001`, no_faktur: invoices[1],
    sumber_dana: 'NTN-0001', workflow_source: 'NTN-0001', debit: 888000, kredit: 0 },
  { id_jurnal_detail: 1696, nama_akun: 'Piutang Usaha', kode_jurnal: '1-10100',
    keterangan: 'Pelunasan faktur', no_faktur: invoices[1], workflow_source: 'KW-7', debit: 0, kredit: 888000 }
];
const journal = { id_jurnal: 772, id_perusahaan: 1, id_cabang: 5, tanggal: '2026-10-23',
  nama_perusahaan: 'PT Budimas Makmur Mulia', nama_cabang: 'SOLO',
  keterangan: 'Penerimaan pembayaran KW-20261023-4C5BFF38 [RECEIPT:7:1]',
  info_jurnal: lines, total_debit: 987900, total_kredit: 987900 };
try {
  for (const theme of ['light', 'dark']) {
    for (const width of [1440, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 1000 } });
      const errors = [], writes = [];
      page.on('pageerror', e => errors.push(e.message));
      const user = { id: 1, nama: 'Penguji', id_cabang: 5, id_perusahaan: 1, jabatan: { nama: 'SUPER USER' } };
      await page.addInitScript(({ theme, user }) => {
        localStorage.setItem('budimas_internal_auth', JSON.stringify({ access_token: 'mock-only', user, permissions: ['*'], menus: [] }));
        localStorage.setItem('budimas-theme', theme);
      }, { theme, user });
      await page.route('**/*', async route => {
        const req = route.request(), url = new URL(req.url()), p = url.pathname;
        if (!p.startsWith('/api/')) return url.origin === origin ? route.continue() : route.abort();
        if (!['GET', 'HEAD', 'OPTIONS'].includes(req.method())) writes.push(`${req.method()} ${p}`);
        let data = [];
        if (p.includes('/auth/') || p.includes('detail-login')) data = { user, permissions: ['*'], menus: [] };
        else if (p.endsWith('/getPerusahaan')) data = [{ id: 1, kode: 'BMM', nama: 'BMM', id_cabang_list: '5' }];
        else if (p.endsWith('/getCabang')) data = [{ id: 5, kode: 'SLO', nama: 'Solo', id_perusahaan: 1 }];
        else if (p.endsWith('/get-jurnal')) data = [journal];
        else if (p.endsWith('/detail-jurnal/772')) data = journal;
        else if (p.endsWith('/workflow/journals')) data = [{ ...journal, reference: 'RECEIPT:7:1', lines }];
        await route.fulfill({ json: { data } });
      });
      await page.goto(origin + '/finance/journal');
      await page.getByRole('button', { name: 'Detail', exact: true }).click();
      await page.getByRole('heading', { name: 'Detail Jurnal 772', exact: true }).waitFor();
      const modal = page.locator('body > div section').last();
      const table = modal.locator('table');
      await table.locator('tbody tr').first().waitFor();
      assert.deepEqual(await table.locator('thead th').allTextContents(), ['Akun', 'Jenis Transaksi', 'Keterangan', 'Debit', 'Kredit']);
      assert.equal(await table.locator('tbody tr').count(), 4);
      const descriptions = await table.locator('tbody tr td:nth-child(3)').allTextContents();
      for (const invoice of invoices) assert.equal(descriptions.filter(s => s.includes(invoice)).length, 2);
      for (const desc of descriptions) {
        for (const invoice of invoices) assert.ok(desc.split(invoice).length - 1 <= 1);
        assert.ok(desc.split('NTN-0002').length - 1 <= 1);
      }
      assert.match(descriptions[2], /Faktur: PJBMMSLO-2610000001/);
      assert.match(descriptions[2], /Sumber: KW-7/);
      assert.match(await modal.innerText(), /987\.900/);
      // Narrow screens scroll inside the table, not the entire modal/page.
      assert.ok(await modal.evaluate(el => el.scrollWidth <= el.clientWidth + 1));
      await page.evaluate(async () => {
        window.scrollTo(0, 0);
        await new Promise(requestAnimationFrame);
        await Promise.all(document.getAnimations().map(a => a.finished.catch(() => {})));
      });
      if (width < 600) await modal.locator('main').evaluate(el => { el.scrollTop = el.scrollHeight; });
      await page.screenshot({ path: `/tmp/journal-compact-${theme}-${width}.png` });
      await page.goto(origin + '/finance/payment-workflow-journals');
      const workflow = page.locator('article').filter({ has: page.getByRole('heading', { name: 'RECEIPT:7:1 · Penerimaan Pembayaran', exact: true }) });
      await workflow.waitFor();
      assert.deepEqual(await workflow.locator('thead th').allTextContents(), ['Akun', 'Keterangan', 'Debit', 'Kredit']);
      assert.equal(await workflow.locator('tbody tr').count(), 4);
      assert.equal(await workflow.locator('tfoot td').first().getAttribute('colspan'), '2');
      const workflowNotes = await workflow.locator('tbody tr td:nth-child(2)').allTextContents();
      assert.match(workflowNotes[1], /Faktur: PJBMMSLO-2610000001/);
      assert.match(workflowNotes[1], /Sumber: KW-7/);
      assert.deepEqual(writes, []);
      assert.deepEqual(errors, []);
      await page.close();
      console.log(`PASS ${theme} ${width}: compact journal + payment journals; references retained; 4 rows and Rp987.900 unchanged; read-only UI`);
    }
  }
} finally {
  await browser.close();
}
