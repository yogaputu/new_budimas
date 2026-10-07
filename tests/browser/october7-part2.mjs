// All API requests are mocked. Never create production financial transactions.
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin='http://127.0.0.1:5196';
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true});
try{
  const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[],writes=[];
  page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(10000);
  const user={id:77,id_user:77,nama:'Part2 Test',id_perusahaan:1,id_cabang:5,jabatan:{nama:'PETUGAS'}};
  const lp={id:10,id_perusahaan:1,id_cabang:5,id_sales:334,kode_lph:'LPH-TEST',nama_sales:'Sales 1',status_dokumen:'DIKEMBALIKAN',claims:[],invoices:[{id:1,id_customer:10,no_faktur:'FAKTUR-A',nama_customer:'Customer A',total:1000,remaining:1000}]};
  const base={id_perusahaan:1,id_cabang:5,approval:'APPROVED',amount:1500,remaining:1500};
  const funds=[{...base,id:1,kind:'GIRO',id_customer:10,reference:'GIRO-A'}, {...base,id:2,kind:'GIRO',id_customer:20,reference:'GIRO-B'}, {...base,id:3,kind:'RETURN',id_customer:10,reference:'RETUR-A'}, {...base,id:4,kind:'ADVANCE',id_customer:20,reference:'UM-B'}, {...base,id:5,kind:'CASH',id_sales:334,reference:'MANUAL-CASH'}, {...base,id:6,kind:'TRANSFER',reference:'BANK-IN',transaction_type:'DEBIT'}, {...base,id:7,kind:'GIRO',id_customer:null,reference:'GIRO-UNKNOWN'}];
  await page.addInitScript(user=>localStorage.setItem('budimas_internal_auth',JSON.stringify({access_token:'mock-only',user,permissions:['*'],menus:[]})),user);
  await page.route('**/*',async route=>{
    const req=route.request(),url=new URL(req.url()),p=url.pathname;
    if(!p.startsWith('/api/'))return url.origin===origin?route.continue():route.abort();
    const raw=req.postData();let body=null;
    if(raw){body=req.headers()['content-type']?.includes('application/json')?req.postDataJSON():raw;writes.push({p,body});}
    let data=[];
    if(p.includes('detail-login')||p.includes('/auth/'))data={user,permissions:['*'],menus:[]};
    else if(p.includes('getPerusahaan'))data=[{id:1,nama:'Company Test',kode:'CO',id_cabang_list:'5'}];
    else if(p.includes('getCabang'))data=[{id:5,nama:'Branch Test',kode:'CB',id_perusahaan:1}];
    else if(p.includes('getSales'))data=[{id:772,id_user:772,id_sales:334,nama:'Sales 1',id_cabang:5}];
    else if(p.endsWith('/fund-customers'))data=[{id:10,kode:'CA',nama:'Customer A'},{id:20,kode:'CB',nama:'Customer B'}];
    else if(p.endsWith('/workflow/funds'))data=req.method()==='GET'?funds:{...body,id:100};
    else if(p.endsWith('/workflow/lphs'))data=[{...lp,eligible_invoice_count:1}];
    else if(p.endsWith('/lphs/10/detail'))data=lp;
    else if(p.endsWith('/mutations/file/preview'))data={fingerprint:'testhash',skipped:0,rows:[{row:2,reference:'CSV-1',bank:'BCA',received_date:'2026-10-07',amount:'1000.00',transaction_type:'DEBIT',description:'Test'}]};
    else if(p.endsWith('/mutations/file/import'))data={created:1,skipped:0};
    else if(p.endsWith('/wms/placements'))data=[{id:1,id_cabang:5,id_produk:1487,kode_barang:'P2P1',nama_barang:'P2 Produk1',kode_rak:'R1',qty_pcs:370,available_qty_pcs:125,uom1_nama:'PCS',uom1_factor:1}];
    return route.fulfill({json:{data}});
  });
  const selectScope=async()=>{
    const inputs=page.getByPlaceholder('Pilih data',{exact:true});
    await inputs.nth(0).click();await page.getByRole('button',{name:'CO - Company Test',exact:true}).click();
    await inputs.nth(1).click();await page.getByRole('button',{name:'CB - Branch Test',exact:true}).click();
  };
  await page.goto(origin+'/finance/bank-input');
  await page.getByRole('button',{name:'Input Manual',exact:true}).click();
  assert.equal(await page.getByText('Sales Penyerah',{exact:true}).count(),0);
  await selectScope();await page.getByLabel('Nominal (Rp)',{exact:true}).fill('1000');await page.getByLabel('Bank',{exact:true}).fill('BCA');await page.getByLabel('Deskripsi',{exact:true}).fill('Masuk bank');
  await page.getByRole('button',{name:'Simpan Setoran',exact:true}).click();await page.getByText('Setoran tersimpan.',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Import Mutasi',exact:true}).click();await selectScope();
  await page.locator('input[type=file]').setInputFiles({name:'bank.csv',mimeType:'text/csv',buffer:Buffer.from('tanggal,referensi,bank,nama_rekening,keterangan,debit,kredit\n2026-10-07,CSV-1,BCA,Test,Masuk,1000,0')});
  await page.getByRole('button',{name:'Tinjau File',exact:true}).click();await page.getByRole('button',{name:'Simpan 1 Mutasi',exact:true}).click();
  await page.getByText('1 mutasi diimpor; 0 duplikat dilewati.',{exact:true}).waitFor();
  assert(writes.find(w=>w.p.endsWith('/file/import')).body.includes('testhash'));
  await page.goto(origin+'/finance/giro-deposits');await page.getByRole('button',{name:'Tambah Setoran',exact:true}).click();await selectScope();
  await page.getByPlaceholder('Pilih customer',{exact:true}).click();await page.getByRole('button',{name:'CA — Customer A',exact:true}).click();
  const sales=page.getByPlaceholder('Pilih data',{exact:true}).nth(2);await sales.click();await page.getByRole('button',{name:'Sales 1',exact:true}).click();
  await page.getByLabel('Nomor referensi / BG').fill('BG-TEST');await page.getByLabel('Nominal (Rp)',{exact:true}).fill('1000');await page.getByLabel('Bank',{exact:true}).fill('BCA');await page.getByLabel('Jatuh Tempo Giro').fill('2026-10-30');
  await page.getByRole('button',{name:'Simpan Setoran',exact:true}).click();await page.getByText('Setoran tersimpan.',{exact:true}).waitFor();
  assert.equal(writes.filter(w=>w.p.endsWith('/workflow/funds')).at(-1).body.id_customer,'10');
  await page.goto(origin+'/finance/receipt-workflow');await page.getByRole('button',{name:'Buat Kuitansi',exact:true}).click();
  await page.getByPlaceholder('Pilih data',{exact:true}).click();await page.getByRole('button',{name:'LPH-TEST — Sales 1',exact:true}).click();
  await page.getByRole('checkbox',{name:'Pilih faktur FAKTUR-A',exact:true}).check();
  for(const name of ['GIRO-A','RETUR-A','MANUAL-CASH','BANK-IN'])await page.getByRole('checkbox',{name:`FAKTUR-A sumber ${name}`,exact:true}).waitFor();
  for(const name of ['GIRO-B','UM-B','GIRO-UNKNOWN'])assert.equal(await page.getByRole('checkbox',{name:`FAKTUR-A sumber ${name}`,exact:true}).count(),0);
  await page.getByRole('checkbox',{name:'FAKTUR-A sumber MANUAL-CASH',exact:true}).check();
  assert.equal(await page.getByRole('spinbutton',{name:'FAKTUR-A nominal MANUAL-CASH',exact:true}).inputValue(),'1000');
  await page.screenshot({path:'/tmp/budimas-oct7-part2.JbT1tO/receipt-ui.png',fullPage:true});
  await page.goto(origin+'/wms/penempatan');await page.getByRole('cell',{name:'125 PCS',exact:true}).waitFor();
  assert.equal(await page.getByText('Saldo Penempatan — Acuan Laporan Stok Gudang',{exact:true}).count(),0);
  await page.screenshot({path:'/tmp/budimas-oct7-part2.JbT1tO/rack-ui.png',fullPage:true});
  assert.deepEqual(errors,[]);console.log('PASS Part2: bank CSV, no sales on transfer, Giro customer, scoped sources, uncapped approved cash, rack ready without summary');
}finally{await browser.close();}
