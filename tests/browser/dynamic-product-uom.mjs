// No live ERP calls; all API reads and promo previews use synthetic fixtures.
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin=process.env.TEST_BASE_URL || 'http://127.0.0.1:5176';
assert.ok(['localhost','127.0.0.1'].includes(new URL(origin).hostname));
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true});
try {
  for(const count of [1,2,3,4,6]) {
    const context=await browser.newContext();
    const user={id:1,id_user:1,nama:'Test Admin',is_superuser:true,role:'superadmin',id_cabang:1,id_perusahaan:1};
    const units=Array.from({length:count},(_,i)=>({id:101+i,level:i+1,nama:['PCS','CT','BOX','PALET','BUNDLE','PACK'][i],faktor_konversi:10**i}));
    await context.addInitScript(u=>localStorage.setItem('budimas_internal_auth',JSON.stringify({access_token:'test-only',user:u,permissions:['*'],menus:[]})),user);
    let preview;
    await context.route('**/*',route=>{
      const url=new URL(route.request().url());if(!url.pathname.startsWith('/api/'))return url.origin===origin?route.continue():route.abort();
      let data=[];
      if(url.pathname.includes('detail-login')||url.pathname.includes('/auth/'))data={user,permissions:['*'],menus:[]};
      else if(url.pathname.includes('getPerusahaan'))data=[{id:1,kode:'BMM',nama:'Perusahaan',id_cabang_list:'1'}];
      else if(url.pathname.includes('getCabang'))data=[{id:1,id_perusahaan:1,kode:'SLO',nama:'Solo'}];
      else if(url.pathname.includes('getPrincipal'))data=[{id:1,id_perusahaan:1,kode:'P1',nama:'Principal'}];
      else if(url.pathname.includes('getSales'))data=[{id:1,id_user:1,id_sales:1,nama:'Sales',id_cabang:1,id_perusahaan:1,id_principal:1}];
      else if(url.pathname.includes('order-edit'))data={header:{id:1,status_order:0,id_plafon:1,id_cabang:1,id_perusahaan:1,id_user_sales:1,id_customer:1,id_principal:1},details:[{id_produk:1,pieces_order:2*10**(count-1),uom_quantities:[{uom_id:100+count,level:count,quantity:2}]}]};
      else if(url.pathname.includes('list-sales-customer'))data=[{id:1,id_rute:1,kode:'C1',nama:'Customer'}];
      else if(url.pathname.includes('sisa-plafon'))data=[{id:1,id_plafon:1,id_principal:1,id_perusahaan:1,id_cabang:1,id_user:1,limit_bon:99999999,sisa_bon:99999999}];
      else if(url.pathname.includes('get-produk-so'))data=[{id:1,id_produk:1,id_principal:1,nama:'Produk',kode_sku:'SKU1',harga_jual:100,jumlah_ready:999999,uoms:units,id_ppn:1,ppn:0}];
      else if(url.pathname.includes('preview-sales-order')) {preview=route.request().postDataJSON();data={groups:[]};}
      return route.fulfill({json:{data}});
    });
    const page=await context.newPage(), errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(origin+'/sales-order/create?edit_id=1');
    const inputs=page.locator('input[aria-label^="Produk —"]');await inputs.last().waitFor();
    assert.equal(await inputs.count(),count);
    await page.waitForFunction(()=>Array.from(document.querySelectorAll('input[aria-label^="Produk —"]')).at(-1)?.value==='2');
    assert.equal(await inputs.last().inputValue(),'2');
    if(count>1)assert.equal(await inputs.first().inputValue(),'0'); // folded PCS must not be counted twice on edit
    await inputs.last().fill('3');
    await Promise.all([page.waitForResponse(r=>r.url().includes('preview-sales-order')),page.getByRole('button',{name:'Refresh Promo',exact:true}).click()]);
    assert.equal(preview.products[0].uom_quantities.length,count);
    assert.equal(preview.products[0].uom_quantities.at(-1).quantity,3);
    assert.equal(preview.products[0].total_pieces,3*10**(count-1));
    for(const width of [390,768,1440]) {
      await page.setViewportSize({width,height:900});
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`ERP UOM ${count}, width ${width}`);
    }
    if(count===4)await page.screenshot({path:'/tmp/budimas-erp-uom-four.png',fullPage:true});
    assert.deepEqual(errors,[]);await context.close();
  }
  console.log('PASS ERP: 1/2/3/4/6 master UOMs, edit snapshot, no double count, payload and responsive layout.');
} finally {await browser.close();}
