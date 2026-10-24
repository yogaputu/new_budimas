// Local compiled ERP only; every API is mocked and all business writes rejected.
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin=process.env.FRONTEND_TEST_ORIGIN || 'http://127.0.0.1:5198';
assert.equal(new URL(origin).hostname,'127.0.0.1');
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true});
const evidence=process.env.EVIDENCE_DIR || '/tmp/budimas-part3-20261023.5j4EuL';
try {
  const page=await browser.newPage({viewport:{width:1440,height:1000},colorScheme:'light',reducedMotion:'reduce'}),errors=[],writes=[];
  page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));
  const user={id:77,id_user:77,nama:'Local Receipt Test',id_perusahaan:1,id_cabang:5};
  await page.addInitScript(user=>{
    localStorage.setItem('budimas_internal_auth',JSON.stringify({access_token:'local-mock',user,permissions:['*'],menus:[]}));
    if(!localStorage.getItem('budimas-theme'))localStorage.setItem('budimas-theme','dark');
  },user);
  const fee={id_faktur:2,no_faktur:'PJBMMSLO-2610000002',nama_customer:'Customer 1',claims:{TRANSFER:55500},real:{TRANSFER:53000},other:{FEE:2500,RETURN:0,ADVANCE:0},total_claim:55500,total_real:53000,total_funds:55500,paid:55500,remaining_before:55500,remaining_after:0,excess:0,difference:-2500,matched:false};
  const cn={id_faktur:9,no_faktur:'PJBMMSLO-2610000009',nama_customer:'Customer 1',claims:{CASH:84360},real:{CASH:66700,TRANSFER:24500},other:{FEE:0,RETURN:40000,ADVANCE:0},total_claim:84360,total_real:91200,total_funds:131200,paid:84360,remaining_before:84360,remaining_after:0,excess:46840,difference:6840,matched:false};
  let extra=false;
  const detail=()=>{
    const rows=extra?[fee,cn]:[fee];
    return {id:8,number:'KW-PART3-LOCAL',status:'FINALIZED',invoices:[],allocations:[],audit:[],reconciliation:{invoices:rows,summary:{...fee,claims:{TRANSFER:55500,CASH:extra?84360:0},real:{TRANSFER:extra?77500:53000,CASH:extra?66700:0},other:{FEE:2500,RETURN:extra?40000:0,ADVANCE:0},total_real:extra?144200:53000,total_claim:extra?139860:55500,total_funds:extra?186700:55500,paid:extra?139860:55500,advance_excess:extra?46840:0}}};
  };
  await page.route('**/*',async route=>{
    const req=route.request(),url=new URL(req.url()),p=url.pathname;
    if(!p.startsWith('/api/'))return url.origin===origin?route.continue():route.abort();
    if(req.method()!=='GET'){writes.push(p);return route.abort();}
    let data=[];
    if(p.includes('detail-login')||p.includes('/auth/'))data={user,permissions:['*'],menus:[]};
    else if(p.includes('getPerusahaan'))data=[{id:1,kode:'BMM',nama:'Company Test',id_cabang_list:'5'}];
    else if(p.includes('getCabang'))data=[{id:5,kode:'SLO',nama:'Solo',id_perusahaan:1}];
    else if(p.endsWith('/workflow/receipts'))data=[{id:8,number:'KW-PART3-LOCAL',status:'FINALIZED',total:55500,receipt_date:'2026-10-23'}];
    else if(p.endsWith('/workflow/receipts/8'))data=detail();
    return route.fulfill({json:{data}});
  });
  const settle=async()=>page.evaluate(async()=>{
    for(const animation of document.getAnimations())animation.finish();
    await new Promise(requestAnimationFrame);
  });
  const open=async()=>{
    await page.goto(origin+'/finance/receipt-workflow');
    await page.getByRole('button',{name:'Rincian',exact:true}).click();
    await page.getByRole('heading',{name:'Ringkasan & Rekonsiliasi Tiga Arah'}).waitFor();
    await settle();
  };
  await open();
  const section=page.getByRole('region',{name:'Rekonsiliasi tiga arah'});
  await section.getByText('SEIMBANG (COCOK)',{exact:true}).waitFor();
  const total=section.getByRole('row').filter({has:page.getByText('Total Dana Riil + Biaya',{exact:true})});
  assert.match(await total.innerText(),/55\.500(?:,00)?.*55\.500(?:,00)?.*Rp\s*0(?:,00)?/s);
  const raw=section.getByRole('row').filter({has:page.getByText('Subtotal Dana Riil',{exact:true})});
  assert.match(await raw.innerText(),/53\.000(?:,00)?.*-.*2\.500(?:,00)?/s);
  assert.equal(await page.locator('html').getAttribute('data-theme'),'dark');
  await page.screenshot({path:evidence+'/reconciliation-dark.png',animations:'disabled'});
  await page.getByRole('button',{name:'✕',exact:true}).click();await settle();
  await page.getByRole('button',{name:'Light',exact:true}).click();
  await settle();
  assert.equal(await page.locator('html').getAttribute('data-theme'),'light');
  await page.getByRole('button',{name:'Rincian',exact:true}).click();await settle();
  await page.screenshot({path:evidence+'/reconciliation-light.png'});
  await page.setViewportSize({width:390,height:844});
  await section.getByText('Total Dana Riil + Biaya',{exact:true}).scrollIntoViewIfNeeded();
  assert(await section.evaluate(el=>{
    const box=el.getBoundingClientRect();
    return box.left>=0&&box.right<=innerWidth&&[...el.querySelectorAll('.overflow-x-auto')].every(t=>t.clientWidth<=el.clientWidth);
  }),'Reconciliation stays inside mobile modal; wide tables scroll in their own container');
  await page.screenshot({path:evidence+'/reconciliation-mobile.png'});
  extra=true;await page.setViewportSize({width:1440,height:1000});await open();
  await section.getByText('ADA SELISIH KLAIM — periksa setiap faktur sebelum finalisasi',{exact:true}).waitFor();
  const last=section.getByRole('row').filter({has:page.getByText('PJBMMSLO-2610000009',{exact:true})});
  assert.match(await last.innerText(),/6\.840(?:,00)?/);
  const corrected=section.getByRole('row').filter({has:page.getByText('PJBMMSLO-2610000002',{exact:true})});
  assert.match(await corrected.locator('td').nth(6).innerText(),/^Rp\s*0(?:,00)?$/);
  assert.match(await total.innerText(),/6\.840(?:,00)?/);
  await page.screenshot({path:evidence+'/reconciliation-real-discrepancy.png'});
  assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
  console.log('PASS compiled ERP: fee offset is zero, real bank unchanged, CN/advance separate, genuine 6840 mismatch retained, light/dark/mobile, no financial writes');
} finally {await browser.close();}
