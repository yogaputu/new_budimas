// All API calls are mocked. Never creates real returns, journals, or stock moves.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.PURCHASE_TEST_ORIGIN || 'http://127.0.0.1:5199';
const base = '/api/purchase/principal-claims';
const items = [
  {id:501,qty:'1',uom_code:'PCS',uom_factor:'1'},
  {id:502,qty:'8',uom_code:'BOX',uom_factor:'8'},
  {id:503,qty:'80',uom_code:'CTN',uom_factor:'80'}
].map(r=>({...r,product_id:1,kode_sku:'P1P01',product_name:'Produk 1',available_qty:r.qty,
  purchase_order_id:1440,purchase_transaksi_id:1118,batch_number:'TEST',expired_date:'2027-08-21'}));
const notes = [
  {receipt_key:'receipt:1118',purchase_transaksi_id:1118,receipt_number:'PTR-20261021-1118',
    purchase_order_ids:[1440],movement_date:'2026-10-21',qty:'89',available_qty:'89',product_count:1,source_count:3,items},
  {receipt_key:'receipt:1119',purchase_transaksi_id:1119,receipt_number:'PTR-20261021-1119',
    purchase_order_ids:[1440],movement_date:'2026-10-21',qty:'1',available_qty:'1',product_count:1,source_count:1,
    items:[{...items[0],id:504,purchase_transaksi_id:1119}]}
];
const claim={id:900,number:'RPO-MOCK-900',kind:'RETURN',status:'SUBMITTED',requested_method:'CREDIT',
  requested_amount:'94905',id_perusahaan:1,id_cabang:5,id_principal:247,lines:[],history:[],return_lines:[]};
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH});
try {
  for (const theme of ['light','dark']) {
    const page=await browser.newPage({viewport:{width:1440,height:1100}});
    const errors=[],posts=[],lotRequests=[],sourceRequests=[],unexpectedWrites=[];
    const user={id:1,nama:'Penguji',id_cabang:5,id_perusahaan:1,jabatan:{nama:'SUPER USER'}};
    page.on('pageerror',e=>errors.push(e.message));
    await page.addInitScript(({user,theme})=>{
      localStorage.setItem('budimas_internal_auth',JSON.stringify({access_token:'mock-only',user,permissions:['*'],menus:[]}));
      localStorage.setItem('budimas-theme',theme);
    },{user,theme});
    await page.route('**/*',async route=>{
      const req=route.request(),url=new URL(req.url()),path=url.pathname;
      if(!path.startsWith('/api/'))return url.origin===origin?route.continue():route.abort();
      let data=[];
      if(path.includes('/auth/')||path.includes('detail-login'))data={user,permissions:['*'],menus:[]};
      else if(path.endsWith('/getPerusahaan'))data=[{id:1,kode:'BMM',nama:'Budimas',id_cabang_list:'5'}];
      else if(path.endsWith('/getCabang'))data=[{id:5,kode:'SLO',nama:'Solo',id_perusahaan:1}];
      else if(path.endsWith('/getPrincipal'))data=[{id:247,kode:'P1',nama:'Principal 1',id_perusahaan:1}];
      else if(path===base)data={rows:[],total:0};
      else if(path===base+'/return-sources'){
        sourceRequests.push(Object.fromEntries(url.searchParams));
        assert.equal(url.searchParams.get('group_by'),'receipt');
        assert.equal(url.searchParams.get('id_principal'),'247');
        if(url.searchParams.get('search')==='failed')return route.fulfill({status:500,json:{message:'Uji gagal membaca nota'}});
        data={rows:url.searchParams.get('search')==='missing'?[]:notes,has_more:false,group_by:'receipt'};
      } else if(path.startsWith(base+'/return-sources/')&&path.endsWith('/lots')){
        const id=Number(path.split('/').at(-2));lotRequests.push(id);
        const source=items.find(r=>r.id===id);assert.ok(source,'Lot uses original ledger ID, not receipt header ID');
        data={receipt:{...source,unit_cost:'9500',pricelist_price:'760000',pricelist_factor:'80',
          return_unit_dpp:'9500',tax_rate:'11'},rows:[{stock_kind:'RACK',stock_id:599,kode_rak:'G1R01',
            batch_number:'TEST',expired_date:'2027-08-21',available_qty:80}]};
      } else if(path===base+'/returns'&&req.method()==='POST'){
        posts.push(req.postDataJSON());data=claim;
      } else if(path===base+'/returns/900')data=claim;
      else if(req.method()!=='GET')unexpectedWrites.push(`${req.method()} ${path}`);
      return route.fulfill({json:{data}});
    });
    await page.goto(origin+'/purchase/returns');
    await page.getByRole('button',{name:'Ajukan Retur / Pemusnahan',exact:true}).click();
    for(const [label,option] of [['Perusahaan','BMM Budimas'],['Cabang','SLO Solo'],['Principal','P1 Principal 1']]){
      await page.getByRole('combobox',{name:label,exact:true}).click();
      await page.getByRole('option',{name:option,exact:true}).click();
    }
    await page.getByRole('button',{name:'Cari Penerimaan PO',exact:true}).click();
    const table=page.getByRole('table',{name:'Nota penerimaan PO'});
    await table.getByText('PTR-20261021-1118',{exact:true}).waitFor();
    assert.equal(await table.locator('tbody tr').count(),2,'Same PO, two receipts; not four UOM rows');
    const row=table.locator('tbody tr').filter({hasText:'PTR-20261021-1118'});
    assert.match(await row.textContent(),/3 rincian UOM/);
    assert.equal(await row.getByText('89 PCS',{exact:true}).count(),2);
    await row.getByRole('button',{name:'Lihat Rincian',exact:true}).click();
    const details=page.getByRole('region',{name:'Rincian PTR-20261021-1118'});
    assert.equal(await details.locator('article').count(),3);
    for(const text of ['1 PCS × 1 PCS','1 BOX × 8 PCS','1 CTN × 80 PCS'])
      assert.equal(await details.getByText(text,{exact:false}).count(),1);
    await page.screenshot({path:`/tmp/principal-return-notes-${theme}.png`,fullPage:true,animations:'disabled'});
    await page.setViewportSize({width:420,height:900});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.screenshot({path:`/tmp/principal-return-notes-${theme}-mobile.png`,fullPage:true,animations:'disabled'});
    await details.getByRole('button',{name:/sumber 503$/}).click();
    await page.getByLabel('Jumlah retur PCS',{exact:true}).fill('9');
    await page.getByRole('button',{name:'Tambahkan Lot',exact:true}).click();
    assert.deepEqual(lotRequests,[503]);
    await page.getByLabel('Alasan retur / pemusnahan',{exact:true}).fill('Uji nota berisi 3 UOM');
    await page.getByRole('button',{name:'Ajukan ke Principal',exact:true}).click();
    await page.getByText('Pengajuan dikirim ke portal principal. Stok belum berkurang.',{exact:true}).waitFor();
    assert.equal(posts.length,1);
    assert.deepEqual(posts[0].lines,[{receipt_ledger_id:503,stock_kind:'RACK',stock_id:599,qty_pcs:9}]);
    assert.equal(posts[0].kind,'RETURN');assert.equal(posts[0].requested_method,'CREDIT');
    // Failed searches must not leave selectable results from an old search.
    await page.getByRole('button',{name:'Ajukan Retur / Pemusnahan',exact:true}).click();
    for(const [label,option] of [['Perusahaan','BMM Budimas'],['Cabang','SLO Solo'],['Principal','P1 Principal 1']]){
      await page.getByRole('combobox',{name:label,exact:true}).click();
      await page.getByRole('option',{name:option,exact:true}).click();
    }
    const search=page.getByLabel('Cari nota / SKU / produk / ID PO',{exact:true});
    await search.fill('missing');await page.getByRole('button',{name:'Cari Penerimaan PO',exact:true}).click();
    await page.getByText('Nota penerimaan tidak ditemukan pada filter ini.',{exact:true}).waitFor();
    await search.fill('');await page.getByRole('button',{name:'Cari Penerimaan PO',exact:true}).click();
    await table.getByText('PTR-20261021-1118',{exact:true}).waitFor();
    await search.fill('failed');await page.getByRole('button',{name:'Cari Penerimaan PO',exact:true}).click();
    await page.getByRole('alert').filter({hasText:'Uji gagal membaca nota'}).waitFor();
    assert.equal(await table.getByRole('button',{name:'Lihat Rincian'}).count(),0);
    assert.equal(sourceRequests.length,4);assert.deepEqual(unexpectedWrites,[]);assert.deepEqual(errors,[]);
    await page.close();
    console.log(`PASS ${theme}: one row/note, 89 PCS, UOM details, original lot/submission IDs, mobile, empty/error states`);
  }
} finally {await browser.close();}
