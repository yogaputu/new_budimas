// Local, fully mocked production-build QA; outbound network is blocked.
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const origin=process.env.PURCHASE_TEST_ORIGIN||'http://127.0.0.1:5199';
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH});
const billNumber='PP-20261020-6BCE3A3C-D037-4BDF-BE69-416DBAABCDEF';
try{
  for(const [theme,source] of [['light','legacy'],['dark','legacy'],['light','native'],['dark','native']]){
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[],posts=[];page.on('pageerror',e=>errors.push(e.message));
    const user={id:1,nama:'Penguji',id_cabang:5,id_perusahaan:1,jabatan:{nama:'SUPER USER'}};
    await page.addInitScript(({theme,user})=>{
      localStorage.setItem('budimas_internal_auth',JSON.stringify({access_token:'mock-only',user,permissions:['*'],menus:[]}));
      localStorage.setItem('budimas-theme',theme);
    },{theme,user});
    const candidates=[{id_purchase_transaksi:101,no_transaksi:'RC-101',kode_order:'PO-10',subtotal:2220},
      {id_purchase_transaksi:102,no_transaksi:'RC-102',kode_order:'PO-10',subtotal:3330}]
      .map(r=>({...r,id_cabang:5,id_perusahaan:1,id_principal:5,nama_principal:'Principal Test',jatuh_tempo:'2026-11-20'}));
    let plan=null,kuReady=false;
    const bill=()=>({id:1,id_tagihan:1,surat_tagihan:billNumber,nama_principal:'Principal Test',total_tagihan:5550,
      jumlah_faktur:2,status_bayar:plan?.status==='PAID'?'lunas':plan?.status==='CANCELLED'?'dibatalkan':'belum lunas',
      id_cabang:5,id_perusahaan:1,id_principal:5,jatuh_tempo:'2026-11-20'});
    await page.route('**/*',async route=>{
      const req=route.request(),url=new URL(req.url()),p=url.pathname;
      if(!p.startsWith('/api/'))return url.origin===origin?route.continue():route.abort();
      let data=[];
      if(p.includes('/auth/')||p.includes('detail-login'))data={user,permissions:['*'],menus:[]};
      else if(p.endsWith('/getPerusahaan'))data=[{id:1,nama:'BMM',id_cabang_list:'5'}];
      else if(p.endsWith('/getCabang'))data=[{id:5,nama:'Solo',id_perusahaan:1}];
      else if(p.endsWith('/getPrincipal'))data=[{id:5,nama:'Principal Test',id_perusahaan:1,id_cabang_list:'5'}];
      else if(p.endsWith('/get-add-tagihan-purchase'))data=plan?[]:candidates;
      else if(p.endsWith('/get-hutang'))data=plan?[bill()]:[];
      else if(p.endsWith('/detail-tagihan-purchase'))data=candidates;
      else if(p.endsWith('/payment-requests/options'))data={total:'5550.00',receipts:candidates.map(r=>({id:r.id_purchase_transaksi,no_transaksi:r.no_transaksi,total:r.subtotal})),
        banks:[{id:1,nama_bank:'Bank Test',nomor_rekening:'000'}],
        accounts:[{id_coa:10,nomor_akun:'CLEAR',nama_akun:'Pembayaran Belum Teridentifikasi',id_kategori:2},
          {id_coa:11,nomor_akun:'CLAIM',nama_akun:'Piutang Klaim',id_kategori:5}],
        credits:[{id:100,number:'RET-1',kind:'RETURN',remaining:'925.00'},{id:101,number:'CLM-1',kind:'PROMO',remaining:'1000.00'}]};
      else if(p.endsWith('/payment-requests')&&req.method()==='POST'){
        const body=req.postDataJSON();posts.push(body);
        plan={id:1,no_tagihan:billNumber,status:'SUBMITTED',bill_total:'5550.00',return_amount:'500',claim_amount:'1000',
          discount_amount:'200',penalty_amount:'0',cash_amount:'3850',snapshot:candidates.map(r=>({receipt_id:r.id_purchase_transaksi,no_transaksi:r.no_transaksi,amount:r.subtotal}))};
        data=plan;
      }else if(p.endsWith('/payment-requests/by-bill'))data=plan;
      else if(p.endsWith('/outgoing-options'))data=kuReady?[{...(source==='native'?{id_fund_source:33,source_kind:'FUND',source_key:'fund:33'}:{id_mutasi:1}),kode_mutasi:'KU-TEST-A',tanggal_mutasi:'2026-10-20',nominal_mutasi:'2000'},
        {...(source==='native'?{id_fund_source:34,source_kind:'FUND',source_key:'fund:34'}:{id_mutasi:2}),kode_mutasi:'KU-TEST-B',tanggal_mutasi:'2026-10-20',nominal_mutasi:'1850'}]:[];
      else if(p.endsWith('/payment-requests/1/pay')){posts.push(req.postDataJSON());plan={...plan,status:'PAID',...(source==='native'?{id_fund_source:33}:{id_mutasi:1}),id_jurnal:99,paid_date:'2026-10-20'};data=plan;}
      else if(p.endsWith('/payment-requests/1/cancel')){posts.push(req.postDataJSON());plan={...plan,status:'CANCELLED'};data=plan;}
      else if(['/api/akuntansi/create-tagihan-purchase','/api/finance/purchase-bill-payments','/api/purchase/principal-claims/settlements'].includes(p))throw Error('UI called retired API '+p);
      await route.fulfill({json:{data}});
    });
    await page.goto(origin+'/purchase/bills');
    await page.getByRole('button',{name:'Muat Kandidat',exact:true}).click();
    await page.getByText('RC-101',{exact:true}).click();
    await page.getByText('RC-102',{exact:true}).first().click();
    await page.getByRole('button',{name:'Ajukan Pembayaran ke Principal',exact:true}).click();
    await page.getByRole('combobox',{name:'Rekening Kas/Bank untuk pembayaran',exact:true}).click();
    await page.getByRole('option',{name:'Bank Test · 000',exact:true}).click();
    await page.getByLabel('Referensi / keterangan pengajuan',{exact:true}).fill('AJU-TEST');
    await page.getByRole('combobox',{name:'Penyesuaian pembayaran',exact:true}).click();
    try{await page.getByRole('option',{name:'Diskon (mengurangi tagihan)',exact:true}).click({timeout:3000});}
    catch(error){await page.screenshot({path:'/tmp/purchase-payment-debug.png',fullPage:true});console.log(await page.getByRole('option').allTextContents());throw error;}
    await page.getByLabel('Nominal diskon (Rp)',{exact:true}).fill('200');
    await page.getByLabel('Alokasi RET-1',{exact:true}).fill('500');
    await page.getByLabel('Alokasi CLM-1',{exact:true}).fill('1000');
    await page.getByRole('combobox',{name:'COA Piutang Klaim (kredit)',exact:true}).click();
    await page.getByRole('option',{name:'CLAIM — Piutang Klaim',exact:true}).click();
    assert.ok(await page.getByRole('button',{name:'Simpan Pengajuan Pembayaran',exact:true}).isDisabled());
    await page.getByRole('button',{name:'Isi nominal sisa',exact:true}).click();
    assert.equal(await page.getByLabel('Nominal Kas/Bank yang diajukan (Rp)',{exact:true}).inputValue(),'3850');
    await page.screenshot({path:`/tmp/purchase-payment-proposal-${theme}.png`,fullPage:true});
    await page.setViewportSize({width:420,height:900});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.screenshot({path:`/tmp/purchase-payment-proposal-${theme}-mobile.png`,fullPage:true});
    await page.getByRole('button',{name:'Simpan Pengajuan Pembayaran',exact:true}).click();
    await page.getByText(billNumber,{exact:true}).waitFor();
    assert.equal(posts.length,1);assert.deepEqual(posts[0].receipt_ids,[101,102]);
    assert.equal(posts[0].cash_amount,'3850');assert.equal(posts[0].credits.length,2);
    await page.getByText(billNumber,{exact:true}).click();
    await page.getByText('Belum ada KU bank keluar yang cocok.',{exact:false}).waitFor();
    kuReady=true;
    await page.getByRole('button',{name:'Refresh KU',exact:true}).click();
    await page.getByRole('combobox',{name:'KU — mutasi bank keluar (DB)',exact:true}).click();
    await page.getByRole('option',{name:/KU-TEST-A/}).click();
    await page.getByLabel('Referensi pelunasan',{exact:true}).fill('KU-TEST');
    await page.getByRole('checkbox',{name:/Saya sudah memeriksa/}).check();
    assert.ok(await page.getByRole('button',{name:'Cocokkan KU & Lunasi',exact:true}).isDisabled());
    await page.getByRole('combobox',{name:'KU — mutasi bank keluar (DB)',exact:true}).click();
    await page.getByRole('option',{name:/KU-TEST-B/}).click();
    await page.getByLabel('Referensi pelunasan',{exact:true}).fill('KU-TEST');
    await page.getByLabel('Tanggal bayar',{exact:true}).fill('2026-10-20');
    await page.getByRole('checkbox',{name:/Saya sudah memeriksa/}).check();
    await page.screenshot({path:`/tmp/purchase-payment-ku-${theme}-mobile.png`,fullPage:true});
    await page.getByRole('button',{name:'Cocokkan KU & Lunasi',exact:true}).click();
    await page.getByText(billNumber+' · PAID',{exact:true}).waitFor();
    assert.equal(posts.length,2);
    assert.deepEqual(posts[1].bank_sources,source==='native'?[{id_fund_source:33},{id_fund_source:34}]:[{id_mutasi:1},{id_mutasi:2}]);
    assert.deepEqual(errors,[]);
    await page.close();console.log(`PASS ${theme}/${source}: proposal composition, required cash, searchable bank/COA/KU, absent KU, exact match, mobile layout, settlement`);
  }
}finally{await browser.close();}
