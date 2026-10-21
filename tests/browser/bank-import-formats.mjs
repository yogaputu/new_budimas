// Local-only UI test: every API is mocked, no bank record is submitted live.
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const origin='http://127.0.0.1:5199';
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH});
try {
  for(const theme of ['light','dark']) for(const scenario of ['MANUAL','BCA','BCA_PENDING','BCA_SETUP']) {
    const format=scenario==='MANUAL'?'MANUAL':'BCA',includePending=scenario==='BCA_PENDING',missingSetup=scenario==='BCA_SETUP';
    const page=await browser.newPage({viewport:{width:420,height:900}}),errors=[],writes=[];
    page.setDefaultTimeout(12000);page.on('pageerror',e=>errors.push(e.message));
    const user={id:1,nama:'Test',id_cabang:5,id_perusahaan:1,jabatan:{nama:'SUPER USER'}};
    await page.addInitScript(({theme,user})=>{
      localStorage.setItem('budimas_internal_auth',JSON.stringify({access_token:'mock',user,permissions:['*'],menus:[]}));
      localStorage.setItem('budimas-theme',theme);
    },{theme,user});
    await page.route('**/*',async route=>{
      const req=route.request(),url=new URL(req.url()),p=url.pathname;
      if(!p.startsWith('/api/'))return url.origin===origin?route.continue():route.abort();
      let data=[];
      if(p.includes('/auth/')||p.includes('detail-login'))data={user,permissions:['*'],menus:[]};
      else if(p.endsWith('/getPerusahaan'))data=[{id:1,nama:'Company Test',kode:'CO',id_cabang_list:'5'}];
      else if(p.endsWith('/getCabang'))data=[{id:5,nama:'Solo',kode:'SLO',id_perusahaan:1}];
      else if(p.endsWith('/rekening_perusahaan/all'))data=[{id_rekening_perusahaan:7,id_perusahaan:1,id_cabang:5,is_aktif:true,nama_bank:'BCA',nomor_rekening:'000123'}];
      else if(p.endsWith('/file/preview')||p.endsWith('/file/import')) {
        const body=req.postData();writes.push({p,body});
        assert(body.includes(`\r\n${format}\r\n`));
        if(format==='BCA')assert(body.includes('name="bank_account_id"\r\n\r\n7'));
        const hasPendingDate=body.includes('name="pending_date"\r\n\r\n2026-10-02');
        if(p.endsWith('/preview'))data={setup:{ready:!missingSetup,issues:missingSetup?[{purpose:'CLEARING',message:'Akun Penerimaan Belum Teridentifikasi belum dipetakan.'}]:[]},fingerprint:hasPendingDate?'PREVIEW-HASH-PEND':'PREVIEW-HASH',skipped:includePending?1:0,rows:[{row:7,reference:'BCA-TEST',bank:'7',received_date:'2026-10-01',amount:'200.50',transaction_type:'CREDIT',description:'Transfer test',duplicate:includePending},
          ...(hasPendingDate?[{row:8,reference:'BCA-PEND-TEST',bank:'7',received_date:'2026-10-02',amount:'50',transaction_type:'DEBIT',description:'Pending test',was_pending:true}]:[])],
          ...(format==='BCA'?{account_masked:'••••0123',period:{start:'2026-10-01',end:'2026-10-02'},totals:{DEBIT:'0',CREDIT:'200.50'},
            warnings:[hasPendingDate?'1 transaksi PEND disertakan dengan tanggal pembukuan pilihan Anda: 02/10/2026.':'1 transaksi PEND dilewati karena belum memiliki tanggal transaksi pasti.'],
            pending:hasPendingDate?[]:[{row:8,amount:'50',reason:'PEND: tanggal transaksi belum tersedia; tidak diimpor.'}],pending_included:hasPendingDate?1:0}: {})};
        else {assert(body.includes(includePending?'PREVIEW-HASH-PEND':'PREVIEW-HASH'));if(includePending)assert(hasPendingDate);data={created:1,skipped:includePending?1:0};}
      }
      await route.fulfill({json:{data}});
    });
    await page.goto(origin+'/finance/bank-input');
    await page.getByRole('button',{name:'Import Mutasi',exact:true}).click();
    for(const [label,option] of [['Perusahaan','CO - Company Test'],['Cabang','SLO - Solo']]){
      await page.getByRole('combobox',{name:label,exact:true}).click();
      await page.getByRole('option',{name:option,exact:true}).click();
    }
    if(format==='BCA'){
      await page.getByRole('combobox',{name:'Format import',exact:true}).click();
      await page.getByRole('option',{name:'BCA (CSV mutasi rekening asli)',exact:true}).click();
      assert(await page.getByRole('button',{name:'Tinjau File',exact:true}).isDisabled());
      await page.getByRole('combobox',{name:'Rekening perusahaan pada file BCA',exact:true}).click();
      await page.getByRole('option',{name:'BCA · 000123',exact:true}).click();
    }else await page.getByRole('button',{name:'Unduh Template Manual / Non-BCA',exact:true}).waitFor();
    await page.locator('input[type=file]').setInputFiles({name:'test.csv',mimeType:'text/csv',buffer:Buffer.from('synthetic mock only')});
    await page.getByRole('button',{name:'Tinjau File',exact:true}).click();
    if(format==='BCA')await page.getByText('1 transaksi PEND dilewati karena belum memiliki tanggal transaksi pasti.',{exact:true}).waitFor();
    if(includePending){
      assert(await page.getByRole('button',{name:'Simpan 0 Mutasi',exact:true}).isDisabled());
      await page.getByRole('button',{name:'Gunakan tanggal akhir periode 2026-10-02 untuk PEND',exact:true}).click();
      assert.equal(await page.getByLabel('Tanggal pembukuan PEND (opsional)',{exact:true}).inputValue(),'2026-10-02');
      assert.equal(await page.getByRole('button',{name:/Simpan \d+ Mutasi/}).count(),0,'Date change must invalidate old preview');
      await page.getByRole('button',{name:'Tinjau File',exact:true}).click();
      await page.getByText('1 transaksi PEND disertakan dengan tanggal pembukuan pilihan Anda: 02/10/2026.',{exact:true}).waitFor();
      await page.getByText('Asal PEND · tanggal pilihan',{exact:true}).waitFor();
    }
    await page.getByRole('button',{name:'Simpan 1 Mutasi',exact:true}).waitFor();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    assert.equal(await page.locator('fieldset').evaluate(e=>e.scrollWidth<=e.clientWidth+1),true,'Import form must fit inside mobile modal');
    await page.waitForFunction(()=>!document.querySelector('fieldset').disabled);
    if(missingSetup)await page.getByRole('alert').scrollIntoViewIfNeeded();
    await page.screenshot({path:`/tmp/bank-import-${scenario}-${theme}.png`,fullPage:true});
    if(missingSetup){
      assert(await page.getByRole('button',{name:'Simpan 1 Mutasi',exact:true}).isDisabled());
      await page.getByText('Akun Penerimaan Belum Teridentifikasi belum dipetakan.',{exact:true}).waitFor();
      assert.equal(await page.getByRole('alert').getByRole('link',{name:'Pengaturan Workflow Pembayaran',exact:true}).getAttribute('href'),'/finance/payment-workflow-settings');
      assert.equal(writes.length,1,'Missing mapping must never submit an import');assert.deepEqual(errors,[]);
      console.log(`PASS bank import ${theme}/${scenario}: missing account explained before commit; no import`);
      await page.close();continue;
    }
    await page.getByRole('button',{name:'Simpan 1 Mutasi',exact:true}).click();
    await page.getByText(`1 mutasi diimpor; ${includePending?1:0} duplikat dilewati.`,{exact:true}).waitFor();
    assert.equal(writes.length,includePending?3:2);assert.deepEqual(errors,[]);
    console.log(`PASS bank import ${theme}/${scenario}: searchable scope/account, preview, pending date, warnings, fingerprint, mobile commit`);
    await page.close();
  }
}finally{await browser.close();}
