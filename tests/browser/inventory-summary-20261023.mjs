// Compiled local ERP only. All APIs mocked; no warehouse, accounting or stock writes.
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin=process.env.FRONTEND_TEST_ORIGIN || 'http://127.0.0.1:5199';
assert.equal(new URL(origin).hostname,'127.0.0.1');
const evidence=process.env.EVIDENCE_DIR || '/tmp/budimas-return-inventory-20261023.KtuM7H';
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH});
const uoms=[{level:1,nama:'PCS',faktor_konversi:1},{level:2,nama:'BOX',faktor_konversi:8},{level:3,nama:'CTN',faktor_konversi:80}];
const row={id:1,id_cabang:5,nama_cabang:'Solo',id_produk:101,product_code:'P1P01',product_name:'Produk 1',qty_pcs:81,
 quantity_ct:1,quantity_pc:1,per_unit:80,uoms,location:'R1',shelf_type:'Tetap',status:'LOW',wms_ready_status:'Siap Picking',
 batch_number:'TEST',expiry_date:'2027-08-21',tanggal_masuk_gudang:'2026-10-22 08:37:35',fifo_rank:1,fefo_rank:2,fifo_label:'FIFO utama',fefo_label:'FEFO #2'};
const rows=[row,{...row,id:2,qty_pcs:8,quantity_ct:0,quantity_pc:8,location:'R2',expiry_date:'2027-07-21',fifo_rank:2,fefo_rank:1,fifo_label:'FIFO #2',fefo_label:'FEFO utama'},
 {...row,id:3,qty_pcs:0,quantity_ct:0,quantity_pc:0,location:'EMPTY',status:'EMPTY',expiry_date:'2026-01-01',fifo_rank:3,fefo_rank:3,fifo_label:'FIFO #3',fefo_label:'FEFO #3'},
 {...row,id:4,id_cabang:6,nama_cabang:'Klaten',qty_pcs:7,quantity_ct:0,quantity_pc:7}];
try{
 for(const theme of ['light','dark']){
  const page=await browser.newPage({viewport:{width:1500,height:1000},reducedMotion:'reduce'}),errors=[],writes=[],requests=[];
  page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));
  const user={id:77,id_user:77,nama:'Inventory Test',id_cabang:5,id_perusahaan:1};
  await page.addInitScript(({user,theme})=>{
    localStorage.setItem('budimas_internal_auth',JSON.stringify({access_token:'mock-local',user,permissions:['*'],menus:[]}));
    localStorage.setItem('budimas-theme',theme);
  },{user,theme});
  await page.route('**/*',async route=>{
    const req=route.request(),url=new URL(req.url()),path=url.pathname;
    if(!path.startsWith('/api/'))return url.origin===origin?route.continue():route.abort();
    if(req.method()!=='GET'){writes.push(path);return route.abort();}
    let data=[];
    if(/detail-login|\/auth\//.test(path))data={user,permissions:['*'],menus:[]};
    else if(path.endsWith('/inventory/inventory/inventory')){
      requests.push(Object.fromEntries(url.searchParams));data=url.searchParams.get('search')==='missing'?[]:rows;
    }else if(path.includes('/inventory/inventory/barcode/'))data=rows.filter(r=>r.id_cabang===5);
    else if(path.endsWith('/getPerusahaan'))data=[{id:1,kode:'BMM',nama:'Company',id_cabang_list:'5,6'}];
    else if(path.endsWith('/getCabang'))data=[{id:5,kode:'SLO',nama:'Solo',id_perusahaan:1},{id:6,kode:'KLT',nama:'Klaten',id_perusahaan:1}];
    else if(path.includes('ready-to-load'))data={data:[]};
    return route.fulfill({json:{data,result:data}});
  });
  const settle=()=>page.evaluate(async()=>{for(const a of document.getAnimations())a.finish();await new Promise(requestAnimationFrame);});
  await page.goto(origin+'/wms');
  await page.getByRole('button',{name:'Lihat lot P1P01 cabang 5',exact:true}).waitFor();await settle();
  assert.equal(await page.getByRole('cell',{name:'P1P01',exact:true}).count(),2,'Separate rows for different branches');
  const solo=page.getByRole('row').filter({has:page.getByRole('cell',{name:'Solo',exact:true})});
  assert.match(await solo.innerText(),/89.*1 CTN \+ 1 BOX \+ 1 PCS.*2.*2027-07-21/s);
  assert.equal(await page.getByText('FIFO utama',{exact:true}).count(),0,'FIFO badges stay in lot details');
  await solo.scrollIntoViewIfNeeded();
  await page.screenshot({path:evidence+`/inventory-summary-${theme}.png`,animations:'disabled'});
  await page.getByRole('button',{name:'Lihat lot P1P01 cabang 5',exact:true}).click();await settle();
  await page.getByRole('heading',{name:'Detail Lot P1P01',exact:true}).waitFor();
  const modal=page.locator('section').filter({has:page.getByRole('heading',{name:'Detail Lot P1P01',exact:true})}).last();
  await modal.getByRole('cell',{name:'2027-07-21',exact:true}).waitFor();
  await modal.getByRole('cell',{name:'2027-08-21',exact:true}).waitFor();
  assert.equal(await modal.getByRole('cell',{name:'TEST',exact:true}).count(),3,'Same batch name remains distinct lots');
  await modal.getByText('FIFO utama',{exact:true}).waitFor();await modal.getByText('FEFO utama',{exact:true}).waitFor();
  await page.screenshot({path:evidence+`/inventory-lots-${theme}.png`,animations:'disabled'});
  await page.setViewportSize({width:390,height:844});
  assert(await modal.evaluate(el=>el.getBoundingClientRect().right<=innerWidth));
  await page.screenshot({path:evidence+`/inventory-lots-${theme}-mobile.png`,animations:'disabled'});
  await page.getByRole('button',{name:'✕',exact:true}).click();await settle();
  await page.setViewportSize({width:1500,height:1000});
  await page.getByLabel('Scan / Barcode Produk',{exact:true}).fill('P1P01');
  await page.getByRole('button',{name:'Cek Barcode',exact:true}).click();
  await page.getByText('1 produk/cabang · 3 lot. Ringkasan mengikuti filter; buka detail untuk melihat rak, batch, expired, dan urutan FIFO/FEFO.',{exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Lihat lot P1P01 cabang 5',exact:true}).count(),2,'Barcode uses same grouping');
  await page.getByLabel('Cari Inventory',{exact:true}).fill('missing');
  await page.getByRole('button',{name:'Muat Inventory',exact:true}).click();
  await page.getByText('Belum ada stok inventory pada filter ini.',{exact:true}).waitFor();
  assert.equal(requests.at(-1).search,'missing');
  assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
  await page.close();console.log(`PASS ${theme}: product/branch summary, complete lot details, UOM/expiry/ranks, empty/search/barcode/mobile, no writes`);
 }
}finally{await browser.close();}
