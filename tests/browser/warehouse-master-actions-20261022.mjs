// Isolated UI regression: all API calls are synthetic, never production.
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const origin='http://127.0.0.1:5199';
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH});
try {
  for(const theme of ['light','dark']) {
    const page=await browser.newPage({viewport:{width:1440,height:1000}}),mutations=[],errors=[];
    const user={id:1,nama:'Penguji',id_cabang:5,id_perusahaan:1,jabatan:{nama:'SUPER USER'}};
    let rack={id:1,id_cabang:5,kode_rak:'R1',type_rak:'Tetap',active:true,status_rak:'Kosong',availability:'Kosong',
      qty_pcs:0,max_qty_karton:10,mix_mode:'single_principal',gudang:1,rak:1,level:0,kolom:1,nomor_urut:1};
    let pallet={id:1,id_cabang:5,kode_pallet:'PAL1',tipe_pallet:'Standard',active:true,status_pallet:'Aktif',
      availability:'Kosong',used_qty_pcs:0,max_qty_karton:10};
    page.on('pageerror',error=>errors.push(error.message));
    await page.addInitScript(({user,theme})=>{
      localStorage.setItem('budimas_internal_auth',JSON.stringify({access_token:'synthetic-only',user,permissions:['*'],menus:[]}));
      localStorage.setItem('budimas-theme',theme);
    },{user,theme});
    await page.route('**/*',async route=>{
      const request=route.request(),url=new URL(request.url()),path=url.pathname,method=request.method();
      if(!path.startsWith('/api/')) return url.origin===origin?route.continue():route.abort();
      let data=[];
      if(/detail-login|\/auth\//.test(path))data={user,permissions:['*'],menus:[]};
      else if(path.endsWith('/getCabang'))data=[{id:5,kode:'SLO',nama:'Solo',id_perusahaan:1}];
      else if(path.endsWith('/getPerusahaan'))data=[{id:1,kode:'BMM',nama:'BMM',id_cabang_list:'5'}];
      else if(path.endsWith('/wms/racks/1/active')||path.endsWith('/wms/pallets/1/active')) {
        assert.equal(method,'PUT');const payload=request.postDataJSON();assert.equal(typeof payload.active,'boolean');
        mutations.push({method,path,payload});
        if(path.includes('/racks/'))rack.active=payload.active;
        else {pallet.active=payload.active;pallet.status_pallet=payload.active?'Aktif':'Nonaktif';}
        data=path.includes('/racks/')?rack:pallet;
      } else if(path.endsWith('/wms/racks/1')||path.endsWith('/wms/pallets/1')) {
        assert.equal(method,'DELETE');assert.equal(url.searchParams.get('confirm_delete'),'true');
        mutations.push({method,path});if(path.includes('/racks/'))rack=null;else pallet=null;
        return route.fulfill({json:{status:'success',message:'Master diarsipkan'}});
      } else if(path.endsWith('/wms/racks')) {
        const active=url.searchParams.get('active');
        data=rack&&(!active||String(rack.active)===active)?[rack]:[];
        return route.fulfill({json:{data,total:data.length}});
      } else if(path.endsWith('/wms/pallets')) {
        const status=url.searchParams.get('status');
        data=pallet&&(!status||status===pallet.status_pallet)?[pallet]:[];
      } else if(path.endsWith('/wms/racks/next-code'))data={kode_rak:'R2'};
      else if(path.endsWith('/wms/pallets/next-code'))data={kode_pallet:'PAL2'};
      else if(method!=='GET')throw Error('Unexpected write '+method+' '+path);
      return route.fulfill({json:data});
    });
    for(const [path,code,label] of [['/wms/master-rak','R1','Rak'],['/wms/master-pallet','PAL1','Pallet']]) {
      await page.goto(origin+path);
      const row=()=>page.getByRole('row').filter({has:page.getByRole('cell',{name:code,exact:true})});
      await row().waitFor();await row().click();
      await page.getByRole('button',{name:'Hapus '+label,exact:true}).waitFor();
      page.once('dialog',dialog=>dialog.accept());
      await page.getByRole('button',{name:'Nonaktifkan '+label,exact:true}).click();
      await row().waitFor();
      assert.equal(mutations.at(-1).method,'PUT');assert.equal(mutations.at(-1).payload.active,false);
      await row().click();page.once('dialog',dialog=>dialog.accept());
      await page.getByRole('button',{name:'Aktifkan '+label,exact:true}).click();
      await row().waitFor();assert.equal(mutations.at(-1).payload.active,true);
      await row().click();
      await page.setViewportSize({width:420,height:900});
      await page.screenshot({path:`/tmp/warehouse-actions-${label}-${theme}.png`,fullPage:true,animations:'disabled'});
      page.once('dialog',dialog=>dialog.accept());
      await page.getByRole('button',{name:'Hapus '+label,exact:true}).click();
      await row().waitFor({state:'detached'});assert.equal(mutations.at(-1).method,'DELETE');
      await page.setViewportSize({width:1440,height:1000});
    }
    assert.deepEqual(errors,[]);assert.equal(mutations.length,6);
    console.log('PASS '+theme+': deactivate/reactivate never DELETE, archived master disappears only on explicit Delete; responsive buttons');
    await page.close();
  }
} finally {await browser.close();}
