// Corrected API contract, no production requests or writes.
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const origin=process.env.PURCHASE_TEST_ORIGIN||'http://127.0.0.1:5199';
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH});
try{
  for(const theme of ['light','dark']){
    const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    const user={id:1,nama:'Penguji',id_cabang:5,id_perusahaan:1,jabatan:{nama:'SUPER USER'}};
    await page.addInitScript(({theme,user})=>{
      localStorage.setItem('budimas_internal_auth',JSON.stringify({access_token:'mock-only',user,permissions:['*'],menus:[]}));
      localStorage.setItem('budimas-theme',theme);
    },{theme,user});
    const item={wms_putaway_detail_id:1,Nota:'TEST-89',id_produk:1,KodeBarang:'TESTSKU',NamaBarang:'Produk test',
      qty_pcs:89,QtyCT:1,QtyPC:9,PerUnit:80,IsiPalet:40,uom1_nama:'PCS',uom2_nama:'BOX',uom2_factor:8,
      uom3_nama:'Carton',uom3_factor:80,processed_qty:0,status:'READY',
      uoms:[{id:1,level:1,nama:'PCS',faktor_konversi:1},{id:2,level:2,nama:'BOX',faktor_konversi:8},{id:3,level:3,nama:'Carton',faktor_konversi:80}]};
    await page.route('**/*',async route=>{
      const req=route.request(),url=new URL(req.url()),p=url.pathname;
      if(!p.startsWith('/api/'))return url.origin===origin?route.continue():route.abort();
      assert.equal(req.method(),'GET','Browser QA must never submit incoming');
      let data=[];
      if(p.includes('/auth/')||p.includes('detail-login'))data={user,permissions:['*'],menus:[]};
      else if(p.endsWith('/getPerusahaan'))data=[{id:1,nama:'BMM',id_cabang_list:'5'}];
      else if(p.endsWith('/getCabang'))data=[{id:5,nama:'Solo',id_perusahaan:1}];
      else if(p.includes('/incoming/incoming/note-details'))data={items:[item],total:1,page:1};
      await route.fulfill({json:{data}});
    });
    await page.goto(origin+'/wms');
    await page.getByRole('button',{name:'Incoming',exact:true}).click();
    await page.getByRole('button',{name:'Atur Pallet',exact:true}).click();
    await page.getByText('1 CT + 9 PC',{exact:true}).waitFor();
    assert.equal(await page.getByText('11 CT + 1 PC',{exact:true}).count(),0);
    assert.ok(await page.getByText('89 PCS',{exact:true}).count()>=2);
    await page.locator('body').evaluate(async el=>{
      await new Promise(requestAnimationFrame);
      await Promise.all(el.getAnimations({subtree:true}).map(a=>a.finished.catch(()=>{})));
    });
    await page.screenshot({path:`/tmp/wms-incoming-carton-${theme}.png`,fullPage:true});
    assert.deepEqual(errors,[]);await page.close();
    console.log(`PASS ${theme}: BOX8/CTN80, 89 PCS shown as 1 CT + 9 PC; no writes`);
  }
}finally{await browser.close();}
