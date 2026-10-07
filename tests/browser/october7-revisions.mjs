// Local browser only. Every business request is intercepted; no live transactions.
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin=process.env.FRONTEND_TEST_ORIGIN || 'http://127.0.0.1:5196';
assert(['127.0.0.1','localhost'].includes(new URL(origin).hostname));
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true});
try {
  const page=await browser.newPage({viewport:{width:1440,height:1100}}),writes=[],errors=[],returRequests=[];
  page.setDefaultTimeout(15000);page.on('pageerror',e=>errors.push(e.message));
  let permissions=['m.finance.kw.view','m.finance.kw.create','m.finance.kw.approve','m.finance.kw.update','m.finance.kw.delete',...['stk','snk','bg'].flatMap(m=>['view','create','update','delete','approve'].map(a=>`m.finance.${m}.${a}`))];
  const user={id:77,id_user:77,nama:'Petugas Uji',id_perusahaan:1,id_cabang:5,jabatan:{nama:'PETUGAS'}};
  const receipt={id:1,created_by:77,number:'KW-SELF',kode_lph:'LPH-TEST',id_lph:10,status:'DRAFT',total:1000,receipt_date:'2026-10-07',invoices:[],allocations:[]};
  const funds=[{id:1,kind:'TRANSFER',reference:'BANK-IN',amount:1000,remaining:1000,transaction_type:'DEBIT',received_date:'2026-10-07',approval:'APPROVED'},
    {id:2,kind:'TRANSFER',reference:'BANK-OUT',amount:500,remaining:500,transaction_type:'CREDIT',received_date:'2026-10-07',approval:'APPROVED'}];
  let ready=1000;
  await page.addInitScript(({user,permissions})=>{ if(!localStorage.getItem('budimas_internal_auth'))localStorage.setItem('budimas_internal_auth',JSON.stringify({access_token:'mock-only',user,permissions,menus:[]})); },{user,permissions});
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url()),path=url.pathname,method=route.request().method();
    if(!path.startsWith('/api/'))return url.origin===origin?route.continue():route.abort();
    const body=['POST','PUT'].includes(method)?route.request().postDataJSON():null;
    if(body)writes.push({path,body});
    let data=[];
    if(path.includes('detail-login')||path.includes('/auth/'))data={user,permissions,menus:[]};
    else if(path.includes('getPerusahaan'))data=[{id:1,nama:'Company Test',kode:'CO',id_cabang_list:'5'}];
    else if(path.includes('getCabang'))data=[{id:5,nama:'Branch Test',kode:'CB',id_perusahaan:1}];
    else if(path.includes('getSales'))data=[{id:772,id_user:772,id_sales:334,nama:'Sales 1 (Test)',id_cabang:5,kode_sales:'A'}, {id:772,id_user:772,id_sales:334,nama:'Sales 1 (Test)',id_cabang:5,kode_sales:'B'}, {id:998,id_sales:772,nama:'YUNITA TRI MAHARINI',id_cabang:5}];
    else if(path.endsWith('/workflow/receipts'))data=[receipt];
    else if(path.endsWith('/workflow/receipts/1'))data=receipt;
    else if(path.endsWith('/workflow/funds'))data=funds;
    else if(path.endsWith('/wms/placements'))data=[{id:1,id_cabang:5,id_produk:24,kode_barang:'AUTOSOL',nama_barang:'Autosol 15 GR',kode_rak:'R1',qty_pcs:4,qty_karton:0,uom1_nama:'PCS',uom1_factor:1}];
    else if(path.endsWith('/stock-opname/laporan-stock'))data=[{id:1,id_cabang:5,id_produk:24,kode_sku:'AUTOSOL',nama_produk:'Autosol 15 GR',nama_cabang:'Solo',jumlah_ready:ready,jumlah_good:1000,jumlah_rak_tetap:4,uom:'PCS'}];
    else if(path.endsWith('/sales/retur-tracking')){
      returRequests.push(Object.fromEntries(url.searchParams));
      data=[0,1,2,4,3,9].filter(s=>!url.searchParams.has('status') || String(s)===url.searchParams.get('status')).map(s=>({id_request:s+1,status_request:s,kode_request:`RET-${s}`}));
    }
    return route.fulfill({json:{data}});
  });
  await page.goto(origin+'/finance/receipt-workflow');
  await page.getByRole('button',{name:'Tinjau & Finalisasi',exact:true}).click();
  await page.getByRole('button',{name:'Konfirmasi Rekonsiliasi & Finalisasi',exact:true}).click();
  assert.equal(await page.getByRole('button',{name:'Setujui & Finalisasi',exact:true}).isDisabled(),true);
  await page.getByRole('checkbox',{name:/Saya telah memeriksa/}).check();
  await page.getByRole('button',{name:'Setujui & Finalisasi',exact:true}).click();
  assert.equal(writes.find(w=>w.path.endsWith('/receipts/1/finalize')).body.confirm_reconciliation,true);

  // The non-cash list has incoming funds only and no input/import/edit actions.
  await page.goto(origin+'/finance/receipt-transfer');await page.getByText('BANK-IN',{exact:true}).waitFor();
  assert.equal(await page.getByText('BANK-OUT',{exact:true}).count(),0);
  for(const name of ['Tambah Setoran','Input Manual','Import Mutasi','Edit','Hapus']) assert.equal(await page.getByRole('button',{name,exact:true}).count(),0);
  await page.goto(origin+'/finance/bank-input');await page.getByText('BANK-OUT',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Import Mutasi',exact:true}).waitFor();
  await page.getByRole('button',{name:'Input Manual',exact:true}).click();
  const modal=page.locator('form').filter({has:page.getByRole('button',{name:'Simpan Setoran',exact:true})});
  const selects=modal.getByPlaceholder('Pilih data',{exact:true});
  await selects.nth(0).click();await page.getByRole('button',{name:'CO - Company Test',exact:true}).click();
  await selects.nth(1).click();await page.getByRole('button',{name:'CB - Branch Test',exact:true}).click();
  await selects.nth(2).click();
  assert.equal(await page.getByRole('button',{name:'Sales 1 (Test)',exact:true}).count(),1);
  await selects.nth(2).fill('Sales 1');
  assert.equal(await page.getByRole('button',{name:'YUNITA TRI MAHARINI',exact:true}).count(),0);
  await page.getByRole('button',{name:'Sales 1 (Test)',exact:true}).click();
  await modal.getByLabel('Nominal (Rp)',{exact:true}).fill('1000');
  await modal.getByLabel('Bank',{exact:true}).fill('Bank Test');
  await modal.getByLabel('Deskripsi',{exact:true}).fill('Setoran pengujian lokal');
  await modal.getByRole('button',{name:'Simpan Setoran',exact:true}).click();
  assert.equal(writes.find(w=>w.path.endsWith('/workflow/funds')).body.id_sales,'334');

  // Merely naming a user IT ADMIN must not bypass the configured grants.
  permissions=['m.finance.kw.view'];user.nama='IT ADMIN';
  await page.evaluate(({user,permissions})=>localStorage.setItem('budimas_internal_auth',JSON.stringify({access_token:'mock-only',user,permissions,menus:[]})),{user,permissions});
  await page.goto(origin+'/finance/receipt-workflow');
  await page.getByRole('button',{name:'Rincian',exact:true}).click();
  assert.equal(await page.getByRole('button',{name:'Konfirmasi Rekonsiliasi & Finalisasi',exact:true}).count(),0);
  assert.equal(await page.getByRole('button',{name:'Buat Kuitansi',exact:true}).count(),0);
  permissions=['*'];
  await page.evaluate(({user,permissions})=>localStorage.setItem('budimas_internal_auth',JSON.stringify({access_token:'mock-only',user,permissions,menus:[]})),{user,permissions});
  await page.goto(origin+'/sales-order/retur-tracking');
  for(const label of ['Menunggu Approval','KPR Terbit','Proses QC','Menunggu CN','CN Terbit','Batal'])await page.getByRole('cell',{name:label,exact:true}).waitFor();
  assert.equal(returRequests.at(-1).status_group,'all');
  await page.getByPlaceholder('Semua status',{exact:true}).click();
  await page.getByRole('button',{name:'Menunggu CN',exact:true}).click();
  await page.getByRole('button',{name:/Terapkan/}).click();
  await page.waitForResponse(r=>r.url().includes('/sales/retur-tracking') && new URL(r.url()).searchParams.get('status')==='4');
  assert.equal(returRequests.at(-1).status,'4');
  assert.equal(returRequests.at(-1).status_group,undefined);
  await page.goto(origin+'/wms/penempatan');
  await page.getByRole('heading',{name:'Saldo Penempatan — Acuan Laporan Stok Gudang',exact:true}).waitFor();
  await page.getByRole('cell',{name:'1.000 PCS',exact:true}).waitFor();
  await page.getByRole('cell',{name:'996',exact:true}).waitFor();
  await page.getByRole('cell',{name:'4 PCS',exact:true}).waitFor();
  ready=850;
  await page.getByRole('button',{name:'Muat Penempatan',exact:true}).click();
  await page.getByRole('cell',{name:'850 PCS',exact:true}).waitFor();
  await page.getByRole('cell',{name:'4 PCS',exact:true}).waitFor();
  await page.screenshot({path:'/tmp/budimas-oct7-revision.YYqw4V/placement-report.png',fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS: menu-only ACL, self-approval, no name-based bypass, bank input separation, Debit-only list, unique sales FK, exact retur filters, warehouse-authoritative placement quantities and live reload without changing lot quantities. Mock APIs only.');
} finally { await browser.close(); }
