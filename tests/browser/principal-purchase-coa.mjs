// All API traffic mocked: public build QA never changes live accounting.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.PURCHASE_TEST_ORIGIN || 'http://127.0.0.1:5199';
const roles = Object.entries({ SALES:'Penjualan', PURCHASE:'Pembelian', INVENTORY:'Persediaan',
  COGS:'HPP', RECEIVABLE:'Piutang', PAYABLE:'Hutang', CLAIM_EXPENSE:'Biaya Klaim',
  DISTRIBUTOR_INCENTIVE:'Biaya Insentif Distributor', SALES_RETURN:'Retur Jual', PURCHASE_RETURN:'Retur Beli',
  GOODS_IN_TRANSIT:'Goods in Transit', INPUT_VAT:'PPN Masukan', PURCHASE_DISCOUNT:'Diskon Pembelian',
  PURCHASE_EXPENSE:'Biaya Pembelian' }).map(([kind,label])=>({kind,label}));
const options = roles.map((r,i)=>({id_coa:i+1,nomor_akun:`A-${i+1}`,nama_akun:r.label,nama_kategori:'Akun'}));
const mapping = Object.fromEntries(roles.map((r,i)=>[r.kind,i+1]));
const browser = await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH});
try {
  for (const theme of ['light','dark']) {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const posts=[],errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    const user={id:1,nama:'Penguji',id_cabang:5,id_perusahaan:1,jabatan:{nama:'SUPER USER'}};
    await page.addInitScript(({user,theme})=>{
      localStorage.setItem('budimas_internal_auth',JSON.stringify({access_token:'mock-only',user,permissions:['*'],menus:[]}));
      localStorage.setItem('budimas-theme',theme);
    },{user,theme});
    await page.route('**/*',async route=>{
      const req=route.request(),url=new URL(req.url()),path=url.pathname;
      if (!path.startsWith('/api/')) return url.origin===origin?route.continue():route.abort();
      let data=[];
      if(path.includes('/auth/')||path.includes('detail-login'))data={user,permissions:['*'],menus:[]};
      else if(path.endsWith('/getPerusahaan'))data=[{id:1,kode:'BMM',nama:'BMM',id_cabang_list:'5'}];
      else if(path.endsWith('/getCabang'))data=[{id:5,nama:'Solo',id_perusahaan:1}];
      else if(path.endsWith('/coa-template')){
        if(req.method()==='PUT')posts.push(req.postDataJSON());
        return route.fulfill({json:{id_perusahaan:1,roles,options,mapping,ready:true}});
      }
      return route.fulfill({json:{data}});
    });
    await page.goto(origin+'/master/principals');
    await page.getByRole('button',{name:'Pemetaan COA Principal',exact:true}).click();
    await page.getByRole('combobox',{name:'Perusahaan',exact:true}).click();
    await page.getByRole('option',{name:'BMM - BMM',exact:true}).click();
    const save=page.getByRole('button',{name:'Simpan 14 Pemetaan',exact:true});
    await save.waitFor();assert.equal(await save.isEnabled(),true);
    for(const label of ['Goods in Transit','PPN Masukan','Diskon Pembelian','Biaya Pembelian'])
      assert.equal(await page.getByRole('combobox',{name:label,exact:true}).count(),1);
    await page.screenshot({path:`/tmp/principal-purchase-coa-${theme}.png`,fullPage:true});
    await page.setViewportSize({width:420,height:900});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.screenshot({path:`/tmp/principal-purchase-coa-${theme}-mobile.png`,fullPage:true});
    await save.click();await page.getByText('Pemetaan tersimpan. Berlaku untuk principal baru; akun lama tidak diubah.',{exact:true}).waitFor();
    assert.equal(posts.length,1);assert.equal(Object.keys(posts[0].mapping).length,14);
    assert.deepEqual(errors,[]);await page.close();
    console.log(`PASS ${theme}: 14 searchable parents, ready/save, mobile, mocked API`);
  }
}finally{await browser.close();}
