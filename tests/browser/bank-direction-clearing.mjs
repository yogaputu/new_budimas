// Fully mocked finance settings/journal UI; no live accounting writes.
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const origin=process.env.PURCHASE_TEST_ORIGIN||'http://127.0.0.1:5199';
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH});
const purposes=['CASH','BANK','GIRO','CLEARING','RECEIVABLE','ADVANCE','RETURN','FEE','OUTGOING_CLEARING'];
const mapping=Object.fromEntries(purposes.map((p,i)=>[p,i+1]));
const coa=purposes.map((p,i)=>({id_coa:i+1,id_perusahaan:1,nomor_akun:String(i+1),is_active:true,
  nama_akun:p==='CLEARING'?'Penerimaan Belum Teridentifikasi':p==='OUTGOING_CLEARING'?'Pembayaran Belum Teridentifikasi':p}));
const lines=[{id_jurnal_detail:1618,kode_jurnal:'1-10002',nama_akun:'Bank',debit:0,kredit:772005,keterangan:'Mutasi bank keluar TF0001'},
             {id_jurnal_detail:1619,kode_jurnal:'1-10302',nama_akun:'Pembayaran Belum Teridentifikasi',debit:772005,kredit:0,keterangan:'Mutasi bank keluar TF0001'}];
try{
  for(const theme of ['light','dark']){
    const page=await browser.newPage({viewport:{width:1440,height:1000}}),posts=[],errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    const user={id:1,nama:'Penguji',id_cabang:5,id_perusahaan:1,jabatan:{nama:'SUPER USER'}};
    await page.addInitScript(({theme,user})=>{
      localStorage.setItem('budimas_internal_auth',JSON.stringify({access_token:'mock-only',user,permissions:['*'],menus:[]}));
      localStorage.setItem('budimas-theme',theme);
    },{theme,user});
    const journal={id_jurnal:739,id_perusahaan:1,id_cabang:5,tanggal:'2026-10-21',nama_perusahaan:'BMM',nama_cabang:'Solo',
      keterangan:'Mutasi bank keluar TF0001',info_jurnal:lines,total_debit:772005,total_kredit:772005};
    await page.route('**/*',async route=>{
      const req=route.request(),url=new URL(req.url()),p=url.pathname;
      if(!p.startsWith('/api/'))return url.origin===origin?route.continue():route.abort();
      let data=[];
      if(p.includes('/auth/')||p.includes('detail-login'))data={user,permissions:['*'],menus:[]};
      else if(p.endsWith('/getPerusahaan'))data=[{id:1,kode:'BMM',nama:'BMM',id_cabang_list:'5'}];
      else if(p.endsWith('/getCabang'))data=[{id:5,kode:'SLO',nama:'Solo',id_perusahaan:1}];
      else if(p.endsWith('/get-list-coa'))data=coa;
      else if(p.endsWith('/workflow/settings')){
        if(req.method()==='PUT')posts.push(req.postDataJSON());
        data=[{id_perusahaan:1,accounts:mapping,enabled:true,max_fee:2900}];
      }else if(p.endsWith('/workflow/journals'))data=[{...journal,reference:'FUND:33',fund_kind:'TRANSFER',fund_transaction_type:'CREDIT',lines:[...lines].reverse()}];
      else if(p.endsWith('/get-jurnal'))data=[journal];
      else if(p.endsWith('/detail-jurnal/739'))data=journal;
      await route.fulfill({json:{data}});
    });
    await page.goto(origin+'/finance/payment-workflow-settings');
    await page.getByRole('combobox',{name:'Perusahaan',exact:true}).click();
    await page.getByRole('option',{name:'BMM - BMM',exact:true}).click();
    await page.getByRole('combobox',{name:'Penerimaan Belum Teridentifikasi (pemetaan lama)',exact:true}).waitFor();
    await page.getByRole('combobox',{name:'Pembayaran Belum Teridentifikasi (bank masuk/keluar & pembayaran SO)',exact:true}).waitFor();
    const save=page.getByRole('button',{name:'Simpan Pengaturan',exact:true});
    await save.click();await page.getByText('Pengaturan tersimpan.',{exact:true}).waitFor();
    assert.equal(posts.length,1);assert.notEqual(posts[0].accounts.CLEARING,posts[0].accounts.OUTGOING_CLEARING);
    await page.screenshot({path:`/tmp/bank-clearing-settings-${theme}.png`,fullPage:true});
    await page.goto(origin+'/finance/payment-workflow-journals');
    await page.getByRole('heading',{name:'FUND:33 · Mutasi Bank Keluar',exact:true}).waitFor();
    assert.ok((await page.locator('article tbody tr').first().innerText()).includes('Pembayaran Belum Teridentifikasi'));
    await page.goto(origin+'/finance/journal');
    await page.locator('tr').filter({hasText:'739'}).first().click();
    await page.getByText('ID Jurnal',{exact:true}).last().waitFor();
    const modalTable=page.locator('body > div section table').last();
    await modalTable.locator('tbody tr').first().waitFor();
    assert.ok((await modalTable.locator('tbody tr').first().innerText()).includes('Pembayaran Belum Teridentifikasi'));
    await page.locator('body').evaluate(async el=>{
      await new Promise(requestAnimationFrame);
      await Promise.all(el.getAnimations({subtree:true}).map(a=>a.finished.catch(()=>{})));
    });
    await page.screenshot({path:`/tmp/bank-clearing-journal-${theme}.png`,fullPage:true});
    assert.deepEqual(errors,[]);await page.close();console.log(`PASS ${theme}: shared new payment clearing label, preserved historical mapping, outgoing journal label, debit-first general journal`);
  }
}finally{await browser.close();}
