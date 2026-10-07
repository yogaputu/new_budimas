// Mock every API request; never create financial transactions on a server.
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin='http://127.0.0.1:5196';
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true});
try {
  const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[],writes=[],reads=[];
  page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));
  const user={id:77,id_user:77,nama:'CN Test',id_perusahaan:1,id_cabang:5,jabatan:{nama:'PETUGAS'}};
  const base={id_customer:10,nama_customer:'Customer A',id_perusahaan:1,id_cabang:5,nama_cabang:'SOLO',id_principal:1,nama_principal:'Principal Test',tanggal:'2026-10-07',total_cn:110000,available_amount:110000,held_amount:0,used_amount:0,status_cn:0,funding_status:'AVAILABLE',funding_message:'Tersedia otomatis pada sumber dana customer ini.',receipt_usage:[]};
  const notes=[{...base,id:1,id_cn:1,kode_cn:'CN-PENDING-1',no_faktur_digunakan:'ASAL-1'},
    {...base,id:2,id_cn:2,kode_cn:'CN-PENDING-2',no_faktur_digunakan:'ASAL-2'},
    {...base,id:3,id_cn:3,kode_cn:'CN-LAMA',no_faktur_digunakan:'ASAL-3',status_cn:1,available_amount:0,nominal_refund:110000,kode_refund:'CNREF/LAMA',funding_status:'LEGACY_TRANSACTION',funding_message:'Ada transaksi kas/bank lama. Perlu rekonsiliasi sebelum CN dapat digunakan.'},
    {...base,id:4,id_cn:4,kode_cn:'CN-SEBAGIAN',no_faktur_digunakan:'ASAL-4',status_cn:1,available_amount:60000,used_amount:50000,funding_status:'PARTIAL',applied_invoice_numbers:'FAKTUR-A',receipt_usage:[{id_receipt:1,receipt_number:'KW-1',status:'FINALIZED',no_faktur:'FAKTUR-A',amount:50000}]}];
  const lp={id:10,id_perusahaan:1,id_cabang:5,id_sales:334,kode_lph:'LPH-TEST',nama_sales:'Sales 1',status_dokumen:'DIKEMBALIKAN',claims:[],invoices:[{id:1,id_customer:10,no_faktur:'FAKTUR-A',nama_customer:'Customer A',total:1343100,remaining:1343100}]};
  const funds=[1,2].map(id=>({id:'credit-note:'+id,external_id:id,kind:'RETURN',reference:'CN-PENDING-'+id,amount:110000,remaining:110000,id_customer:10,id_perusahaan:1,id_cabang:5,approval:'APPROVED'}));
  funds.push({...funds[0],id:'credit-note:5',external_id:5,reference:'CN-CUSTOMER-B',id_customer:20});
  await page.addInitScript(user=>localStorage.setItem('budimas_internal_auth',JSON.stringify({access_token:'mock-only',user,permissions:['*'],menus:[]})),user);
  await page.route('**/*',async route=>{
    const req=route.request(),url=new URL(req.url()),p=url.pathname;
    if(!p.startsWith('/api/'))return url.origin===origin ? route.continue():route.abort();
    reads.push(url.href);let data=[];
    if(req.method()!=='GET')writes.push({p,body:req.postDataJSON()});
    if(p.includes('detail-login')||p.includes('/auth/'))data={user,permissions:['*'],menus:[]};
    else if(p.includes('getPerusahaan'))data=[{id:1,nama:'Company Test',kode:'CO',id_cabang_list:'5'}];
    else if(p.includes('getCabang'))data=[{id:5,nama:'SOLO',kode:'SLO',id_perusahaan:1}];
    else if(p.includes('getPrincipal'))data=[{id:1,nama:'Principal Test',kode:'P',id_perusahaan:1}];
    else if(p.endsWith('/get-list-credit-note'))data=notes.filter(n=>!url.searchParams.get('funding_status')||n.funding_status===url.searchParams.get('funding_status'));
    else if(p.includes('/get-detail-credit-note/'))data={header:notes.find(n=>n.id===Number(p.split('/').at(-1))),details:[]};
    else if(p.endsWith('/workflow/funds'))data=funds;
    else if(p.endsWith('/workflow/lphs'))data=[{...lp,eligible_invoice_count:1}];
    else if(p.endsWith('/lphs/10/detail'))data=lp;
    else if(p.endsWith('/external-sources/register')){
      const id=req.postDataJSON().id;data={...funds.find(f=>f.external_id===id),id:100+id,external_id:null,id_credit_note:id};
    }
    return route.fulfill({json:{data}});
  });
  await page.goto(origin+'/finance/credit-note');
  await page.getByRole('cell',{name:'CN-PENDING-1',exact:true}).click();
  await page.getByRole('heading',{name:'Detail Credit Note CN-PENDING-1',exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Potong Tagihan',exact:true}).count(),0);
  await page.getByText('Belum ada alokasi kuitansi aktif. Faktur terkait / asal di atas bukan bukti pemakaian CN.',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Tutup',exact:true}).click();
  await page.getByRole('cell',{name:'CN-LAMA',exact:true}).click();
  await page.getByText('Transaksi kas/bank lama — perlu rekonsiliasi',{exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Buka Pembayaran Tagihan',exact:true}).count(),0);
  await page.getByRole('button',{name:'Tutup',exact:true}).click();
  await page.getByRole('cell',{name:'CN-SEBAGIAN',exact:true}).click();
  await page.getByRole('cell',{name:'KW-1',exact:true}).waitFor();
  await page.getByRole('cell',{name:'Disetujui',exact:true}).waitFor();
  await page.getByRole('button',{name:'Buka Pembayaran Tagihan',exact:true}).scrollIntoViewIfNeeded();
  await page.screenshot({path:'/tmp/budimas-cn-usage.png',animations:'disabled'});
  await page.getByRole('button',{name:'Buka Pembayaran Tagihan',exact:true}).click();
  await page.getByRole('button',{name:'Buat Kuitansi',exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Daftarkan Credit Note',exact:true}).count(),0);
  await page.getByRole('button',{name:'Buat Kuitansi',exact:true}).click();
  await page.getByPlaceholder('Pilih data',{exact:true}).click();
  await page.getByRole('button',{name:'LPH-TEST — Sales 1',exact:true}).click();
  await page.getByRole('checkbox',{name:'Pilih faktur FAKTUR-A',exact:true}).check();
  for(const id of [1,2])await page.getByRole('checkbox',{name:'FAKTUR-A sumber CN-PENDING-'+id,exact:true}).waitFor();
  assert.equal(await page.getByRole('checkbox',{name:'FAKTUR-A sumber CN-CUSTOMER-B',exact:true}).count(),0);
  assert.deepEqual(writes,[]); // Merely showing the CN never reserves anything.
  for(const id of [1,2]){
    await page.getByRole('checkbox',{name:'FAKTUR-A sumber CN-PENDING-'+id,exact:true}).check();
    assert.equal(await page.getByRole('spinbutton',{name:'FAKTUR-A nominal CN-PENDING-'+id,exact:true}).inputValue(),'110000');
  }
  await page.getByRole('spinbutton',{name:'FAKTUR-A nominal CN-PENDING-1',exact:true}).fill('50000');
  await page.getByRole('checkbox',{name:'FAKTUR-A sumber CN-PENDING-1',exact:true}).uncheck();
  await page.getByRole('checkbox',{name:'FAKTUR-A sumber CN-PENDING-1',exact:true}).check();
  assert.equal(writes.length,2);assert(writes.every(w=>w.p.endsWith('/external-sources/register')));
  await page.screenshot({path:'/tmp/budimas-cn-automatic-funds.png',fullPage:true});
  await page.goto(origin+'/finance/credit-note');
  await page.locator('select').selectOption('LEGACY_TRANSACTION');
  await page.getByRole('button',{name:'Terapkan Filter',exact:true}).click();
  await page.getByRole('cell',{name:'CN-LAMA',exact:true}).waitFor();
  await page.waitForFunction(()=>!document.body.innerText.includes('CN-PENDING-1'));
  assert(reads.some(url=>url.includes('funding_status=LEGACY_TRANSACTION')));
  assert.deepEqual(errors,[]);
  console.log('PASS: automatic customer CN, register only on selection, no old buttons, partial edits, actual invoice usage, legacy warning, consistent status filter');
} finally {await browser.close();}
