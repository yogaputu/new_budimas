// Isolated browser with fully mocked API; no production requests or mutations.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.TEST_BASE_URL || 'http://127.0.0.1:5186';
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, headless: true });
try {
  const page = await browser.newPage();
  page.setDefaultTimeout(15000);
  const requests = [], errors = [];
  const user = { id:1, id_user:1, nama:'Test', is_superuser:true, role:'superadmin', id_perusahaan:1 };
  page.on('pageerror', e => errors.push(e.message));
  await page.addInitScript(user => localStorage.setItem('budimas_internal_auth', JSON.stringify({
    access_token:'mock-only', user, permissions:['*'], menus:[]
  })), user);
  const invoice = { id_faktur:101, no_faktur:'F-GABUNGAN', no_order:'SO-GABUNGAN',
    nama_principal:'Principal 1 (Test), Principal 2 (Test)', total_penjualan:2265522,
    total_bayar:0, total_voucher:0, nominal_retur:0, outstanding:2265522, status_bayar:'unpaid' };
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (!url.pathname.startsWith('/api/')) return url.origin === origin ? route.continue() : route.abort();
    requests.push(url);
    let data = [];
    if (url.pathname.includes('detail-login') || url.pathname.includes('/auth/')) data = { user, permissions:['*'], menus:[] };
    else if (url.pathname.includes('getPerusahaan')) data = [{ id:1, kode:'BMM', nama:'Perusahaan', id_cabang_list:'5' }];
    else if (url.pathname.includes('getCabang')) data = [{ id:5, id_perusahaan:1, nama:'Solo', kode:'SLO' }];
    else if (url.pathname.includes('getPrincipal')) data = [
      { id:33, id_perusahaan:1, kode:'P2', nama:'Principal 2 (Test)' },
      { id:232, id_perusahaan:1, kode:'P1', nama:'Principal 1 (Test)' }];
    else if (url.pathname.endsWith('/get-lph')) {
      const index = Number(url.searchParams.get('page') || 0), limit = Number(url.searchParams.get('limit') || 50);
      const total = url.searchParams.get('filters') ? 1 : 125;
      const rows = Array.from({length:Math.min(limit, Math.max(0,total-index*limit))}, (_,i) => ({
        id:total-index*limit-i, kode_lph:`LPH-${total-index*limit-i}`, tanggal_lph:'2026-10-06',
        status_dokumen:'AKTIF', nama_sales:'Sales Test', nama_pencetak:'Admin Test'
      }));
      data = {pages:{result:rows,status:200},total_data:total,page:index,limit,total_pages:Math.ceil(total/limit)};
    } else if (url.pathname.endsWith('/customer-receivable-balances')) {
      data = {result:[{id_customer:1,kode_customer:'C1',nama_customer:'Customer 1 (Test)',id_cabang:5,
        id_perusahaan:1,nama_cabang:'Solo',nama_perusahaan:'Perusahaan',principal_list:invoice.nama_principal,
        jumlah_faktur:1,faktur_belum_lunas:1,total_tagihan:2265522,saldo_piutang:2265522}],
        summary:{total_customer:1,total_saldo_piutang:2265522,total_tagihan:2265522,total_bayar:0,total_cn:0}};
    } else if (url.pathname.endsWith('/customer-receivable-invoices')) {
      data = {result:[invoice],summary:{jumlah_faktur:1,total_tagihan:2265522,total_bayar:0,total_cn:0,saldo_piutang:2265522}};
    }
    return route.fulfill({ json:{data} });
  });
  await page.goto(origin + '/finance/lph');
  await page.getByPlaceholder('Pilih perusahaan', {exact:true}).click();
  await page.getByRole('button', {name:/BMM.*Perusahaan/}).click();
  if (!await page.getByPlaceholder('Pilih cabang', {exact:true}).inputValue()) {
    await page.getByPlaceholder('Pilih cabang', {exact:true}).click();
    await page.getByRole('button', {name:/SLO.*Solo/}).click();
  }
  await page.getByRole('button', {name:'Tampilkan',exact:true}).click();
  await page.getByText('Halaman 1 dari 3 · 125 LPH').waitFor();
  assert.equal(requests.filter(u=>u.pathname.endsWith('/get-lph')).at(-1).searchParams.get('page'),'0');
  assert.equal(await page.getByRole('cell', {name:/^LPH-/}).count(),50);
  assert.equal(await page.getByRole('button', {name:'Berikutnya',exact:true}).count(),1);
  await page.getByRole('button', {name:'Berikutnya',exact:true}).click();
  await page.getByText('Halaman 2 dari 3 · 125 LPH').waitFor();
  await page.getByRole('cell', {name:'LPH-75',exact:true}).waitFor();
  await page.reload();
  await page.getByText('Halaman 2 dari 3 · 125 LPH').waitFor();
  assert.equal(requests.filter(u=>u.pathname.endsWith('/get-lph')).at(-1).searchParams.get('page'),'1');
  await page.getByRole('button', {name:'Berikutnya',exact:true}).click();
  await page.getByText('Halaman 3 dari 3 · 125 LPH').waitFor();
  assert.equal(await page.getByRole('cell', {name:/^LPH-/}).count(),25);
  assert.equal(await page.getByRole('button', {name:'Berikutnya',exact:true}).isDisabled(),true);
  await page.getByRole('button', {name:'Tampilkan',exact:true}).click();
  await page.getByText('Halaman 1 dari 3 · 125 LPH').waitFor();

  await page.goto(origin + '/finance/customer-receivable-balances');
  await page.getByRole('cell', {name:'Customer 1 (Test)',exact:true}).waitFor();
  await page.getByPlaceholder('Semua principal', {exact:true}).click();
  await page.getByRole('button', {name:/P2.*Principal 2/}).click();
  await Promise.all([page.waitForResponse(r=>r.url().includes('/customer-receivable-balances')),
    page.getByRole('button', {name:'Terapkan',exact:true}).click()]);
  await page.getByRole('cell', {name:'Customer 1 (Test)',exact:true}).click();
  await page.getByRole('cell', {name:'F-GABUNGAN',exact:true}).waitFor();
  const detailRequest = requests.filter(u=>u.pathname.endsWith('/customer-receivable-invoices')).at(-1);
  assert.equal(detailRequest.searchParams.get('id_principal'),'33');
  const invoiceRow = page.getByRole('row').filter({has:page.getByRole('cell',{name:'F-GABUNGAN',exact:true})});
  assert.match(await invoiceRow.innerText(), /Principal 1 \(Test\), Principal 2 \(Test\)/);
  assert.match(await invoiceRow.innerText(), /2\.265\.522/);
  assert.match(await invoiceRow.innerText(), /Belum Bayar/);
  assert.deepEqual(errors,[]);
  console.log('PASS: LPH zero-based request, 125 documents across three pages, single paginator, restored-page refresh; principal filter keeps combined invoice labels, total and unpaid status.');
} finally { await browser.close(); }
