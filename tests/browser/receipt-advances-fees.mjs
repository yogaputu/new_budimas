// Local UI regression only: all business APIs mocked; external traffic blocked.
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin=process.env.FRONTEND_TEST_ORIGIN || 'http://127.0.0.1:5196';
assert(['127.0.0.1','localhost'].includes(new URL(origin).hostname));
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true});
try {
  const page=await browser.newPage({viewport:{width:1440,height:1000},colorScheme:'dark'}),errors=[],writes=[];
  page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));
  const user={id:77,id_user:77,nama:'Fee Test',id_perusahaan:1,id_cabang:5};
  let permissions=['*'];
  await page.addInitScript(user=>localStorage.setItem('budimas_internal_auth',JSON.stringify({access_token:'mock-only',user,permissions:['*'],menus:[]})),user);
  let fees=[{id:1,id_perusahaan:1,code:'ADMIN',name:'Biaya Administrasi',max_amount:10000,is_active:true,requires_approval:false,id_coa:8,nomor_akun:'6108',nama_akun:'Beban Administrasi',coa_active:true}];
  const accounts=[{id_coa:8,id_perusahaan:1,nomor_akun:'6108',nama_akun:'Beban Administrasi',is_active:true},{id_coa:9,id_perusahaan:1,nomor_akun:'6109',nama_akun:'Beban Bank',is_active:true}];
  const advances=[
    {id_source:1,id_uang_muka:'receipt:1',origin:'RECEIPT',kode_uang_muka:'UM-KUITANSI',source_reference:'KW-EXCESS',nama_customer:'Customer A',tanggal:'2026-10-07',nominal_awal:250000,nominal_terpakai:50000,nominal_ditahan:25000,sisa_nominal:175000,status:'PARTIAL'},
    {id_source:2,id_uang_muka:'receipt:2',origin:'RECEIPT',kode_uang_muka:'UM-BATAL',source_reference:'KW-CANCELLED',nama_customer:'Customer B',tanggal:'2026-10-07',nominal_awal:50000,nominal_terpakai:0,sisa_nominal:0,status:'CANCELLED'}
  ];
  await page.route('**/*',async route=>{
    const req=route.request(),url=new URL(req.url()),p=url.pathname,m=req.method();
    if(!p.startsWith('/api/')) return url.origin===origin ? route.continue() : route.abort();
    let data=[];
    if(m!=='GET')writes.push({p,m,body:req.postData()?req.postDataJSON():null});
    if(p.includes('detail-login')||p.includes('/auth/'))data={user,permissions,menus:[]};
    else if(p.includes('getPerusahaan'))data=[{id:1,kode:'CO',nama:'Company Test',id_cabang_list:'5'}];
    else if(p.includes('getCabang'))data=[{id:5,kode:'CB',nama:'Branch Test',id_perusahaan:1}];
    else if(p.endsWith('/fee-accounts'))data=accounts;
    else if(p.endsWith('/fee-types')){
      if(m==='POST'){
        const body=req.postDataJSON(),account=accounts.find(a=>String(a.id_coa)===String(body.id_coa));
        data={...body,id:2,nomor_akun:account.nomor_akun,nama_akun:account.nama_akun,coa_active:true};fees.push(data);
      }else data=fees;
    }
    else if(/\/fee-types\/\d+$/.test(p)){
      const id=Number(p.split('/').at(-1));
      if(m==='DELETE'){fees=fees.filter(f=>f.id!==id);data={id,deleted:true};}
      else if(m==='PUT'){const body=req.postDataJSON(),account=accounts.find(a=>String(a.id_coa)===String(body.id_coa));data={...body,id,nomor_akun:account.nomor_akun,nama_akun:account.nama_akun};fees=fees.map(f=>f.id===id?data:f);}
      else data=fees.find(f=>f.id===id);
    }
    else if(p.endsWith('/workflow/customer-advances'))data=advances.filter(a=>!url.searchParams.get('status')||a.status===url.searchParams.get('status'));
    else if(/\/workflow\/customer-advances\/\d+$/.test(p))data={...advances.find(a=>a.id_source===Number(p.split('/').at(-1))),history:[{id:1,no_faktur:'F-INVOICE',tanggal:'2026-10-07',nominal_pakai:50000,nama_user:'Approver',catatan:'KW-USED · FINALIZED'}]};
    else if(p.endsWith('/finance/customer-advances'))data=[{id_uang_muka:1,kode_uang_muka:'UM-LEGACY',kode_mutasi:'BANK-OLD',nama_customer:'Legacy Customer',tanggal:'2026-10-01',nominal_awal:10000,sisa_nominal:10000,status:'APPROVED'}];
    return route.fulfill({json:{data}});
  });
  const selectCompany=async()=>{await page.getByPlaceholder('Pilih data',{exact:true}).click();await page.getByRole('button',{name:'CO - Company Test',exact:true}).click();};
  const closeModal=async()=>{await page.getByRole('button',{name:'✕',exact:true}).click();};
  await page.goto(origin+'/finance/payment-fees');await selectCompany();
  await page.getByRole('cell',{name:'6108 — Beban Administrasi',exact:true}).waitFor();
  await page.getByRole('button',{name:'Tambah Jenis Biaya',exact:true}).click();
  await page.getByLabel('Nama Jenis Biaya',{exact:true}).fill('Biaya Baru');
  await page.getByLabel('Kode Biaya',{exact:true}).fill('NEW');
  await page.getByLabel('Batas Nominal per Faktur',{exact:true}).fill('25000');
  assert(await page.getByRole('button',{name:'Simpan Jenis Biaya',exact:true}).isDisabled());
  await page.getByPlaceholder('Cari kode / nama akun COA',{exact:true}).fill('6109');
  await page.getByRole('button',{name:'6109 — Beban Bank',exact:true}).click();
  await page.screenshot({path:'/tmp/budimas-fee-coa-form.png',animations:'disabled'});
  await page.getByRole('button',{name:'Simpan Jenis Biaya',exact:true}).click();
  const newRow=page.getByRole('row').filter({has:page.getByText('Biaya Baru',{exact:true})});
  await newRow.waitFor();assert.equal(writes.at(-1).body.id_coa,'9');
  await newRow.getByRole('button',{name:'Detail',exact:true}).click();
  await page.getByRole('heading',{name:'Detail Biaya Lain',exact:true}).waitFor();await closeModal();
  await newRow.getByRole('button',{name:'Edit',exact:true}).click();
  await page.getByLabel('Nama Jenis Biaya',{exact:true}).fill('Biaya Diperbarui');
  await page.getByRole('button',{name:'Simpan Jenis Biaya',exact:true}).click();
  const updatedRow=page.getByRole('row').filter({has:page.getByText('Biaya Diperbarui',{exact:true})});
  await updatedRow.waitFor();assert.equal(writes.at(-1).m,'PUT');
  await updatedRow.getByRole('button',{name:'Hapus',exact:true}).click();
  await page.getByText(/Riwayat transaksi dan jurnal yang sudah memakai biaya ini tetap disimpan/).waitFor();
  await page.getByRole('button',{name:'Ya, Hapus Jenis Biaya',exact:true}).click();
  await page.getByText('Jenis biaya dihapus dari daftar; riwayat tetap tersimpan.',{exact:true}).waitFor();
  assert.equal(await updatedRow.count(),0);assert.equal(writes.at(-1).m,'DELETE');
  await page.goto(origin+'/finance/customer-advances');
  await page.getByRole('cell',{name:'UM-KUITANSI',exact:true}).waitFor();
  await page.getByRole('cell',{name:'UM-LEGACY',exact:true}).waitFor();
  await page.getByRole('cell',{name:'Kuitansi KW-EXCESS',exact:true}).waitFor();
  await page.getByRole('cell',{name:'UM-KUITANSI',exact:true}).click();
  await page.getByText('KW-USED · FINALIZED',{exact:false}).waitFor();
  await page.getByRole('button',{name:'Buka Pembayaran Tagihan',exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Gunakan Uang Muka',exact:true}).count(),0);
  assert.equal(await page.getByRole('button',{name:'Tutup',exact:true}).evaluate(el=>getComputedStyle(el).color),'rgb(226, 232, 240)');
  await page.screenshot({path:'/tmp/budimas-receipt-advance-detail.png',animations:'disabled'});
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:'/tmp/budimas-receipt-advance-mobile.png',animations:'disabled'});
  await closeModal();
  await page.getByRole('cell',{name:'UM-BATAL',exact:true}).click();
  await page.getByText(/Kuitansi sumber dibatalkan/).waitFor();
  assert.equal(await page.getByRole('button',{name:'Buka Pembayaran Tagihan',exact:true}).count(),0);
  assert.equal(writes.length,3,'Viewing advances must not change balances');
  // Read-only role can view fee details but cannot modify/delete.
  permissions=['m.finance.bl.view'];
  await page.addInitScript(({user,permissions})=>localStorage.setItem('budimas_internal_auth',JSON.stringify({access_token:'mock-only',user,permissions,menus:[]})),{user,permissions});
  await page.setViewportSize({width:1440,height:1000});await page.goto(origin+'/finance/payment-fees');await selectCompany();
  await page.getByRole('button',{name:'Detail',exact:true}).waitFor();
  for(const name of ['Tambah Jenis Biaya','Edit','Hapus'])assert.equal(await page.getByRole('button',{name,exact:true}).count(),0);
  assert.deepEqual(errors,[]);
  console.log('PASS: fee CRUD + searchable COA + view-only permissions; legacy/receipt advance identities, history, reserved balances, cancelled source, no financial writes');
} finally {await browser.close();}
