// Local-only regression: all API calls mocked, all external traffic blocked.
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin=process.env.FRONTEND_TEST_ORIGIN || 'http://127.0.0.1:5196';
assert(['localhost','127.0.0.1'].includes(new URL(origin).hostname));
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true});
try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],writes=[];
  page.setDefaultTimeout(15000);page.on('pageerror',e=>errors.push(e.message));
  const user={id:1,id_user:1,nama:'Admin Test',is_superuser:true,role:'superadmin'};
  await page.addInitScript(user=>localStorage.setItem('budimas_internal_auth',JSON.stringify({access_token:'mock-only',user,permissions:['*'],menus:[]})),user);
  const lp={id:111,id_sales:334,nama_sales:'Sales Test',kode_lph:'LPH-PARTIAL',status_dokumen:'DIKEMBALIKAN',id_perusahaan:1,id_cabang:5,
    invoices:[{id:1,no_faktur:'F-1',id_customer:1,nama_customer:'Customer Test',total:122100,remaining:122100},{id:2,no_faktur:'F-2',id_customer:1,nama_customer:'Customer Test',total:610500,remaining:610500}],
    claims:[{id:1,id_faktur:1,method:'GIRO',amount:122100,giro_number:'BG001'},{id:2,id_faktur:2,method:'TRANSFER',amount:610500}]};
  const common={approval:'APPROVED',id_perusahaan:1,id_cabang:5,id_sales:772,transaction_type:'DEBIT'};
  const funds=[{...common,id:1,kind:'GIRO',reference:'BG001',remaining:122100,giro_status:'NOT_CLEARED'},
    {...common,id:2,kind:'TRANSFER',reference:'TF001',remaining:598900},
    {...common,id:3,kind:'RETURN',reference:'CN-TEST',id_sales:null,id_customer:1,remaining:1165500},
    {...common,id:4,kind:'ADVANCE',reference:'UM-TEST',id_sales:null,id_customer:1,remaining:300000},
    {...common,id:5,kind:'CASH',reference:'OTHER-SALES-CASH',remaining:1000},
    {...common,id:6,kind:'GIRO',reference:'OTHER-CUSTOMER',id_customer:2,remaining:1000},
    {...common,id:7,kind:'TRANSFER',reference:'OTHER-COMPANY',id_perusahaan:2,remaining:1000},
    {...common,id:8,kind:'TRANSFER',reference:'OTHER-BRANCH',id_cabang:6,remaining:1000},
    {...common,id:9,kind:'TRANSFER',reference:'OUTGOING',transaction_type:'CREDIT',remaining:1000},
    {...common,id:10,kind:'GIRO',reference:'BOUNCED',giro_status:'BOUNCED',remaining:1000}];
  let quote;
  function preview(body){
    const invoices=body.invoices.map(row=>{
      const inv=lp.invoices.find(i=>i.id===row.id_faktur),real={CASH:0,TRANSFER:0,GIRO:0},other={ADVANCE:0,RETURN:0,FEE:0},claims={CASH:0,TRANSFER:0,GIRO:0};
      for(const claim of lp.claims.filter(c=>c.id_faktur===row.id_faktur))claims[claim.method]+=claim.amount;
      for(const a of row.sources){const kind=funds.find(f=>f.id===a.id_source).kind;(kind in real?real:other)[kind]+=Number(a.amount);}
      const total_claim=Object.values(claims).reduce((a,b)=>a+b,0),total_real=Object.values(real).reduce((a,b)=>a+b,0),total_funds=total_real+Object.values(other).reduce((a,b)=>a+b,0),paid=Math.min(inv.remaining,total_funds);
      return {...inv,id_faktur:inv.id,claims,real,other,remaining_before:inv.remaining,remaining_after:inv.remaining-paid,total_claim,total_real,total_funds,paid,excess:Math.max(0,total_funds-paid),difference:total_real-total_claim,matched:total_real===total_claim,excess_treatment:'ADVANCE'};
    });
    const summary={};for(const field of ['remaining_before','remaining_after','total_claim','total_real','total_funds','paid','excess','difference'])summary[field]=invoices.reduce((n,i)=>n+i[field],0);
    for(const group of ['claims','real','other'])summary[group]=Object.fromEntries(Object.keys(invoices[0][group]).map(k=>[k,invoices.reduce((n,i)=>n+i[group][k],0)]));
    return {invoices,summary:{...summary,matched:false,advance_excess:0,fee_excess:0}};
  }
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url()),path=url.pathname,method=route.request().method();
    if(!path.startsWith('/api/'))return url.origin===origin?route.continue():route.abort();
    const body=method==='POST'?route.request().postDataJSON():null;if(body)writes.push({path,body});
    let data=[];
    if(path.includes('detail-login')||path.includes('/auth/'))data={user,permissions:['*'],menus:[]};
    else if(path.includes('getPerusahaan'))data=[{id:1,nama:'Company Test',id_cabang_list:'5'}];
    else if(path.includes('getCabang'))data=[{id:5,nama:'Branch Test',id_perusahaan:1}];
    else if(path.includes('getSales'))data=[{id:334,nama:'Sales Test'}];
    else if(path.endsWith('/workflow/lphs'))data=[lp];
    else if(path.endsWith('/workflow/lphs/111/detail'))data=lp;
    else if(path.endsWith('/workflow/funds'))data=funds;
    else if(path.endsWith('/workflow/receipts/preview'))data=quote=preview(body);
    else if(path.endsWith('/workflow/receipts')&&method==='POST')data={id:1,reconciliation:quote};
    return route.fulfill({json:{data}});
  });
  await page.goto(origin+'/finance/receipt-workflow');
  await page.getByRole('button',{name:'Buat Kuitansi',exact:true}).click();
  await page.getByPlaceholder('Pilih data',{exact:true}).click();
  await page.getByRole('button',{name:'LPH-PARTIAL — Sales Test',exact:true}).click();
  for(const id of [1,2])await page.getByLabel(`Pilih faktur F-${id}`,{exact:true}).check();
  for(const reference of ['OTHER-SALES-CASH','OTHER-CUSTOMER','OTHER-COMPANY','OTHER-BRANCH'])assert.equal(await page.getByLabel(`F-1 sumber ${reference}`,{exact:true}).count(),0);
  for(const reference of ['OUTGOING','BOUNCED'])assert.equal(await page.getByLabel(`F-1 sumber ${reference}`,{exact:true}).isDisabled(),true);
  assert.equal(await page.getByLabel('F-1 sumber BG001',{exact:true}).isDisabled(),false);
  assert.equal(await page.getByLabel('F-2 sumber TF001',{exact:true}).isDisabled(),false);
  await page.getByLabel('F-1 sumber CN-TEST',{exact:true}).check();
  const credit=page.getByLabel('F-1 nominal CN-TEST',{exact:true});
  assert.equal(await credit.inputValue(),'122100');assert.equal(await credit.isEditable(),true);
  await credit.fill('100000.25');
  await page.getByLabel('F-1 sumber BG001',{exact:true}).check();await page.getByLabel('F-1 nominal BG001',{exact:true}).fill('10000');
  await page.getByLabel('F-2 sumber CN-TEST',{exact:true}).check();
  assert.equal(await page.getByLabel('F-2 nominal CN-TEST',{exact:true}).getAttribute('max'),'1065499.75');
  await page.getByLabel('F-2 nominal CN-TEST',{exact:true}).fill('500000');
  await page.getByLabel('F-2 sumber TF001',{exact:true}).check();await page.getByLabel('F-2 nominal TF001',{exact:true}).fill('100000');
  await page.getByLabel('F-2 sumber UM-TEST',{exact:true}).check();
  const advance=page.getByLabel('F-2 nominal UM-TEST',{exact:true});
  assert.equal(await advance.inputValue(),'10500');assert.equal(await advance.isEditable(),true);await advance.fill('10000');
  await page.getByRole('button',{name:'Hitung & Tinjau Alokasi',exact:true}).click();
  await page.getByRole('button',{name:'Simpan Draft',exact:true}).waitFor();
  if(process.env.PAYMENT_SCREENSHOT)await page.screenshot({path:process.env.PAYMENT_SCREENSHOT,fullPage:true});
  await page.getByRole('button',{name:'Simpan Draft',exact:true}).click();
  const save=writes.find(w=>w.path.endsWith('/workflow/receipts'));
  assert.deepEqual(save.body.invoices.map(i=>i.sources.map(s=>s.amount)),[[100000.25,10000],[500000,100000,10000]]);
  assert.equal(quote.summary.excess,0);assert.deepEqual(errors,[]);
  console.log('PASS: cross-sales transfer/uncleared Giro; cash/customer/company/branch guards; editable partial return/advance; capped defaults; exact payload. All API requests mocked.');
} finally {await browser.close();}
