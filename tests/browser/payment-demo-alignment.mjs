// Local-only UI regression. All business APIs are intercepted; never submits live transactions.
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin=process.env.FRONTEND_TEST_ORIGIN || 'http://127.0.0.1:5196';
assert(['localhost','127.0.0.1'].includes(new URL(origin).hostname));
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true});
try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],writes=[];
  page.setDefaultTimeout(15000);page.on('pageerror',e=>errors.push(e.message));
  const user={id:2,id_user:2,nama:'Supervisor Test',is_superuser:true,role:'superadmin',id_perusahaan:1};
  await page.addInitScript(user=>localStorage.setItem('budimas_internal_auth',JSON.stringify({access_token:'mock-only',user,permissions:['*'],menus:[]})),user);
  const lp={id:10,id_sales:1,nama_sales:'Sales Test',kode_lph:'LPH-DEMO',status_dokumen:'DIKEMBALIKAN',id_perusahaan:1,id_cabang:1,
    invoices:[1,2].map(id=>({id,no_faktur:`F-${id}`,nama_customer:'Customer Test',id_customer:1,total:1000,remaining:1000})),
    claims:[1,2].map(id=>({id,id_faktur:id,method:'CASH',amount:1000}))};
  const funds=[{id:1,kind:'CASH',reference:'CASH-A',amount:1500,remaining:1500,approval:'APPROVED',id_perusahaan:1,id_cabang:1,id_sales:1,received_date:'2026-10-06',allocation_status:'UNIDENTIFIED'},
    {id:2,kind:'TRANSFER',reference:'BANK-B',amount:1000,remaining:1000,approval:'APPROVED',transaction_type:'DEBIT',bank:'Bank Test',id_perusahaan:1,id_cabang:1,received_date:'2026-10-06',allocation_status:'UNIDENTIFIED'},
    {id:3,kind:'GIRO',reference:'BG-C',amount:1000,remaining:1000,approval:'APPROVED',giro_status:'NOT_CLEARED',id_perusahaan:1,id_cabang:1,received_date:'2026-10-06',due_date:'2026-10-31',allocation_status:'UNIDENTIFIED'}];
  const fees=[{id:1,id_perusahaan:1,code:'ROUNDING',name:'Pembulatan',max_amount:500,is_active:true,requires_approval:false}];
  const receipt={id:1,created_by:1,number:'KW-DEMO',kode_lph:lp.kode_lph,id_lph:10,status:'DRAFT',receipt_date:'2026-10-06',total:1500,invoices:[],allocations:[],audit:[]};
  let quote;
  function preview(body){
    const invoices=body.invoices.map(i=>{
      const real={CASH:0,TRANSFER:0,GIRO:0};for(const s of i.sources) real[funds.find(f=>String(f.id)===String(s.id_source)).kind]+=Number(s.amount);
      const fee=i.fees.reduce((n,f)=>n+Number(f.amount),0),total_real=real.CASH+real.TRANSFER+real.GIRO,total_funds=total_real+fee,paid=Math.min(1000,total_funds);
      return{id_faktur:i.id_faktur,no_faktur:`F-${i.id_faktur}`,nama_customer:'Customer Test',claims:{CASH:1000,TRANSFER:0,GIRO:0},real,other:{ADVANCE:0,RETURN:0,FEE:fee},remaining_before:1000,remaining_after:1000-paid,total_claim:1000,total_real,total_funds,paid,excess:Math.max(0,total_funds-1000),difference:total_real-1000,matched:total_real===1000,excess_treatment:i.excess_treatment};
    });
    const summary={};for(const f of ['remaining_before','remaining_after','total_claim','total_real','total_funds','paid','excess','difference'])summary[f]=invoices.reduce((n,i)=>n+i[f],0);
    for(const group of ['claims','real','other']){summary[group]={};for(const k of Object.keys(invoices[0][group]))summary[group][k]=invoices.reduce((n,i)=>n+i[group][k],0);}
    summary.matched=invoices.every(i=>i.matched);summary.advance_excess=summary.excess;summary.fee_excess=0;return {invoices,summary};
  }
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url()),path=url.pathname,method=route.request().method();
    if(!path.startsWith('/api/'))return url.origin===origin?route.continue():route.abort();
    let data=[];const body=method==='POST'||method==='PUT'?route.request().postDataJSON():null;
    if(method!=='GET' && method!=='OPTIONS')writes.push({path,body});
    if(path.includes('detail-login')||path.includes('/auth/'))data={user,permissions:['*'],menus:[]};
    else if(path.includes('getPerusahaan'))data=[{id:1,nama:'Company Test',kode:'CO',id_cabang_list:'1'}];
    else if(path.includes('getCabang'))data=[{id:1,nama:'Branch Test',kode:'CB',id_perusahaan:1}];
    else if(path.includes('getSales'))data=[{id:3,id_sales:1,nama:'Sales Test'}];
    else if(path.endsWith('/workflow/lphs'))data=[{...lp,eligible_invoice_count:2}];
    else if(path.endsWith('/workflow/lphs/10/detail'))data=lp;
    else if(path.endsWith('/workflow/funds'))data=funds;
    else if(path.endsWith('/workflow/funds/1'))data={...funds[0],allocations:[{id:1,number:'KW-DEMO',no_faktur:'F-1',nama_customer:'Customer Test',amount:600,status:'FINALIZED'}],clearings:[],audit:[{id:1,action:'CREATED',nama:'Kasir',created_at:'2026-10-06'}]};
    else if(path.endsWith('/workflow/fee-types'))data=fees;
    else if(path.endsWith('/workflow/receipts/preview')){quote=preview(body);data=quote;}
    else if(path.endsWith('/workflow/receipts') && method==='POST'){receipt.reconciliation=quote;data=receipt;}
    else if(path.endsWith('/workflow/receipts'))data=[receipt,{...receipt,id:2,number:'KW-FINAL-2',status:'FINALIZED'},{...receipt,id:3,number:'KW-FINAL-3',status:'FINALIZED'}];
    else if(path.endsWith('/workflow/receipts/1'))data=receipt;
    else if(path.endsWith('/workflow/bank-mutations'))data=[1,2].map(id=>({id_mutasi:id,kode_mutasi:`MUT-${id}`,tanggal_mutasi:'2026-10-06',nominal_mutasi:1000,keterangan:'Dana masuk'}));
    else if(path.endsWith('/workflow/settings'))data=[{id_perusahaan:1,enabled:true,accounts:{},max_fee:3000}];
    return route.fulfill({json:{data}});
  });
  await page.goto(origin+'/finance/receipt-workflow');
  await page.getByRole('button',{name:'Buat Kuitansi',exact:true}).click();
  await page.getByPlaceholder('Pilih data',{exact:true}).click();
  await page.getByRole('button',{name:'LPH-DEMO — Sales Test',exact:true}).click();
  for(const id of [1,2])await page.getByLabel(`Pilih faktur F-${id}`,{exact:true}).check();
  await page.getByLabel('F-1 sumber CASH-A',{exact:true}).check();
  await page.getByLabel('F-1 nominal CASH-A',{exact:true}).fill('600');
  await page.getByLabel('F-2 sumber CASH-A',{exact:true}).check();
  await page.getByLabel('F-2 nominal CASH-A',{exact:true}).fill('900');
  await page.getByRole('button',{name:'Hitung & Tinjau Alokasi',exact:true}).click();
  await page.getByRole('heading',{name:'Ringkasan & Rekonsiliasi Tiga Arah'}).waitFor();
  await page.getByText('ADA SELISIH KLAIM — periksa setiap faktur sebelum finalisasi',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Simpan Draft',exact:true}).scrollIntoViewIfNeeded();
  await page.screenshot({path:process.env.PAYMENT_SCREENSHOT || '/tmp/budimas-payment-demo-reconciliation.png',fullPage:true});
  await page.getByRole('button',{name:'Simpan Draft',exact:true}).click();
  const save=writes.find(w=>w.path.endsWith('/workflow/receipts'));
  assert.deepEqual(save.body.invoices.map(i=>i.sources[0].amount),[600,900]);
  await page.getByRole('button',{name:'Tinjau & Finalisasi',exact:true}).click();
  await page.getByRole('button',{name:'Konfirmasi Rekonsiliasi & Finalisasi',exact:true}).click();
  assert.equal(await page.getByRole('button',{name:'Setujui & Finalisasi',exact:true}).isDisabled(),true);
  await page.getByRole('checkbox',{name:/Saya telah memeriksa/}).check();
  await page.getByRole('button',{name:'Setujui & Finalisasi',exact:true}).click();
  assert.equal(writes.find(w=>w.path.endsWith('/receipts/1/finalize')).body.confirm_reconciliation,true);
  await page.goto(origin+'/finance/bank-input');await page.getByRole('button',{name:'Import Mutasi',exact:true}).click();
  await page.getByRole('heading',{name:'Import Mutasi Bank CSV / XLSX',exact:true}).waitFor();
  // Actual file selection, preview and commit are covered by october7-part2.mjs.
  await page.goto(origin+'/finance/giro-deposits');await page.getByRole('button',{name:'Pencairan',exact:true}).click();
  await page.getByPlaceholder('Pilih setoran nominal cocok',{exact:true}).click();await page.getByRole('button',{name:/BANK-B · Bank Test/}).click();
  await page.getByRole('button',{name:'Konfirmasi Pencairan',exact:true}).click();assert.equal(writes.find(w=>w.path.endsWith('/giro/3/clear')).body.id_payment_source,'2');
  await page.goto(origin+'/finance/receipt-cancellation');await page.getByRole('button',{name:'Buat Pengajuan Pembatalan',exact:true}).click();
  await page.getByLabel('Batalkan KW-FINAL-2',{exact:true}).check();await page.getByLabel('Batalkan KW-FINAL-3',{exact:true}).check();
  await page.getByLabel('Alasan Pembatalan',{exact:true}).fill('Salah alokasi');await page.getByRole('button',{name:'Ajukan 2 Kuitansi',exact:true}).click();
  assert.deepEqual(writes.find(w=>w.path.endsWith('/receipts/cancel-batch')).body.ids,[2,3]);
  await page.goto(origin+'/finance/receipt-cash');await page.getByRole('button',{name:'Detail & Tujuan',exact:true}).click();await page.getByRole('cell',{name:'KW-DEMO',exact:true}).waitFor();
  receipt.created_by=user.id;receipt.status='DRAFT';
  await page.goto(origin+'/finance/receipt-workflow');await page.getByRole('button',{name:'Tinjau & Finalisasi',exact:true}).first().click();
  await page.getByRole('button',{name:'Tarik Draft untuk Koreksi',exact:true}).click();
  await page.getByLabel('Alasan koreksi',{exact:true}).fill('Saldo faktur berubah');
  await page.getByRole('button',{name:'Konfirmasi Penarikan Draft',exact:true}).click();
  assert.equal(writes.find(w=>w.path.endsWith('/receipts/1/discard')).body.reason,'Saldo faktur berubah');
  assert.deepEqual(errors,[]);
  console.log('PASS: explicit split allocations, three-way reconciliation, approval confirmation, multi-import, existing bank giro clearing, batch cancellation, source allocation audit, stale draft recovery. All API requests mocked.');
} finally {await browser.close();}
