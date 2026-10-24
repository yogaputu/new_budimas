// All APIs are mocked. No production LPH, CN, payment, or journal is created.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.TEST_BASE_URL || 'http://127.0.0.1:5197';
const evidence = process.env.EVIDENCE_DIR || '/tmp';
const browser = await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true});
try {
  for (const theme of ['light','dark']) {
    const context = await browser.newContext({viewport:{width:1600,height:1050}});
    const page = await context.newPage(), errors=[], writes=[];
    page.setDefaultTimeout(10000);
    page.on('pageerror',error=>errors.push(error.message));
    const user={id:1,id_user:1,nama:'Test',is_superuser:true,role:'superadmin',id_perusahaan:1};
    await context.addInitScript(({user,theme})=>{
      localStorage.setItem('budimas_internal_auth',JSON.stringify({access_token:'mock-only',user,permissions:['*'],menus:[]}));
      localStorage.setItem('budimas-theme',theme);
      window.print=()=>{};
    },{user,theme});
    const cn={source_type:'credit_note',source_id:'5479',kode:'CN/BMM-P1/20261023/0001',nominal:40000};
    const candidates=[2,8,3].map(id=>({id_faktur:id,no_faktur:'PJBMMSLO-261000000'+id,
      id_customer:id===3?2:1,kode_customer:id===3?'C2':'C1',nama_customer:id===3?'Customer 2':'Customer 1',
      nama_sales:'Sales 1',kode_perusahaan:'BMM',lph_source:id===8?'NON_CALL_PLAN':'CALL_PLAN',
      tanggal_jatuh_tempo:'2026-11-20',tanggal_faktur:'2026-10-23',sisa_pembayaran:55500,
      nominal_retur:0,kode_cn:'',retur_options:id===3?[]:[cn]}));
    let saved=null;
    await context.route('**/*',async route=>{
      const req=route.request(),url=new URL(req.url()),path=url.pathname;
      if(!path.startsWith('/api/'))return url.origin===origin?route.continue():route.abort();
      if(req.method()!=='GET')writes.push({path,body:req.postDataJSON()});
      let data=[];
      if(path.includes('detail-login')||path.includes('/auth/'))data={user,permissions:['*'],menus:[]};
      else if(path.includes('getPerusahaan'))data=[{id:1,kode:'BMM',nama:'Perusahaan',id_cabang_list:'5'}];
      else if(path.includes('getCabang'))data=[{id:5,kode:'SLO',nama:'SOLO',id_perusahaan:1}];
      else if(path.includes('getSales'))data=[{id:1533,id_sales:1533,id_perusahaan:1,id_cabang:5,kode_sales:'1533',nama:'Sales 1'}];
      else if(path.endsWith('/workflow/options'))data=[{id_perusahaan:1,enabled:true}];
      else if(path.endsWith('/get-add-lph'))data=candidates.map(row=>({...row,
        retur_options:row.retur_options.map(option=>({...option,nominal:String(option.nominal)}))}));
      else if(path.endsWith('/add-lph')){
        saved=req.postDataJSON();data={success:true,data:{id_lph:1,kode_lph:'LPH-CN-TEST'}};
      }
      else if(path.endsWith('/get-lph'))data={pages:{result:saved?[{id:1,kode_lph:'LPH-CN-TEST',
        nama_sales:'Sales 1',tanggal_lph:'2026-10-23',status_dokumen:'MENUNGGU_PENERIMAAN'}]:[]},
        total_data:saved?1:0,page:0,limit:50};
      else if(path.endsWith('/get-detail-lph'))data=saved?saved.data_tagihan.map((row,index)=>({
        ...row,id:index+1,id_lph:1,kode_lph:'LPH-CN-TEST',tanggal_lph:'2026-10-23',nama_sales:'Sales 1',
        nama_perusahaan:'BMM',alamat_perusahaan:'Solo',total_retur:saved.total_retur,
        status_dokumen:'MENUNGGU_PENERIMAAN'})):[];
      return route.fulfill({json:path.endsWith('/get-add-lph')||path.endsWith('/get-detail-lph')
        ? {result:data,status:200} : {data}});
    });
    await page.goto(origin+'/finance/lph');
    await page.getByPlaceholder('Pilih perusahaan',{exact:true}).click();
    await page.getByRole('option',{name:/BMM.*Perusahaan/}).click();
    if(!await page.getByPlaceholder('Pilih cabang',{exact:true}).inputValue()){
      await page.getByPlaceholder('Pilih cabang',{exact:true}).click();
      await page.getByRole('option',{name:/SLO.*SOLO/}).click();
    }
    await page.getByRole('button',{name:'Tambah LPH',exact:true}).click();
    const modal=page.locator('section').filter({has:page.getByRole('heading',{name:'Tambah LPH',exact:true})});
    await modal.getByPlaceholder('Pilih sales',{exact:true}).click();
    await page.getByRole('option',{name:/1533.*Sales 1/}).click();
    await modal.getByRole('button',{name:'Muat Kandidat',exact:true}).click();
    const row=id=>modal.locator('tr').filter({has:page.getByRole('cell',{name:'PJBMMSLO-261000000'+id,exact:true})});
    await row(8).locator('summary').click();
    await page.getByRole('checkbox',{name:'PJBMMSLO-2610000008 CN '+cn.kode,exact:true}).check();
    await page.getByRole('checkbox',{name:'Pilih faktur PJBMMSLO-2610000008',exact:true}).check();
    await row(8).locator('summary').click();
    await row(2).locator('summary').click();
    assert(await page.getByRole('checkbox',{name:'PJBMMSLO-2610000002 CN '+cn.kode,exact:true}).isDisabled());
    await row(2).getByText('Sudah dicantumkan pada faktur lain dalam LPH ini.',{exact:true}).waitFor();
    await row(2).locator('summary').click();
    await row(3).locator('summary').click();
    await row(3).getByText('Tidak ada Credit Note/Retur tersedia.',{exact:true}).waitFor();
    assert.equal(writes.length,0); // Choosing a print reference never registers a CN source.
    await row(3).locator('summary').click();
    await page.screenshot({path:evidence+'/lph-cn-'+theme+'.png',fullPage:true});
    await modal.getByRole('button',{name:'Simpan LPH',exact:true}).click();
    await page.getByText('LPH-CN-TEST',{exact:true}).first().waitFor();
    assert.equal(writes.length,1);
    assert.equal(writes[0].path,'/api/akuntansi/add-lph');
    assert.equal(saved.total_retur,40000);
    assert.equal(saved.data_tagihan.length,1);
    assert.equal(saved.data_tagihan[0].id_faktur,8);
    assert.equal(saved.data_tagihan[0].kode_cn,cn.kode);
    assert.deepEqual(saved.data_tagihan[0].selected_retur_options,[cn]);
    const [popup]=await Promise.all([context.waitForEvent('page'),page.getByRole('button',{name:'Cetak LPH',exact:true}).click()]);
    await popup.getByText(cn.kode,{exact:true}).waitFor();
    const printRow=popup.locator('tr').filter({has:popup.getByText('PJBMMSLO-2610000008',{exact:true})});
    assert.match(await printRow.innerText(),/40\.000/);
    await popup.screenshot({path:evidence+'/lph-cn-print-'+theme+'.png',fullPage:true});
    await page.reload();
    await page.getByRole('button',{name:'Cetak LPH',exact:true}).waitFor();
    const [again]=await Promise.all([context.waitForEvent('page'),page.getByRole('button',{name:'Cetak LPH',exact:true}).click()]);
    await again.getByText(cn.kode,{exact:true}).waitFor();
    assert.equal(writes.length,1);assert.deepEqual(errors,[]);
    await context.close();
  }
  console.log('PASS light/dark: same-customer CN from another invoice, no cross-customer choices, duplicate prevention, reference-only save, print and refresh/reprint. All APIs mocked.');
} finally {await browser.close();}
