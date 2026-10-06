// Local UI regression, with all API calls mocked and external requests blocked.
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true,args:['--no-sandbox']});
try {
 const page=await browser.newPage();page.setDefaultTimeout(15000);
 const user={id:1,id_user:1,nama:'Admin',is_superuser:true,role:'superadmin'};
 const errors=[],requests=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(user=>localStorage.setItem('budimas_internal_auth',JSON.stringify({access_token:'test-only',user,permissions:['*'],menus:[]})),user);
 await page.route('**/*',async route=>{
  const url=new URL(route.request().url());
  if(!url.pathname.startsWith('/api/'))return url.origin==='http://127.0.0.1:5173'?route.continue():route.abort();
  let data=[];
  if(url.pathname.includes('detail-login') || url.pathname.includes('/auth/'))data={user,permissions:['*'],menus:[]};
  else if(url.pathname.includes('getCabang'))data=[{id:1,kode:'SLO',nama:'Solo',id_perusahaan:1}];
  else if(url.pathname.includes('getPerusahaan'))data=[{id:1,kode:'BMM',nama:'Perusahaan',id_cabang_list:'1'}];
  else if(url.pathname.includes('getPrincipal'))data=[{id:1,kode:'P1',nama:'Principal',id_perusahaan:1}];
  else if(url.pathname==='/api/base/customer/paginate')data={pages:[],total_data:0};
  else if(url.pathname==='/api/base/plafon/paginate'){
   requests.push(url);const offset=Number(url.searchParams.get('page'))*50;
   data={pages:Array.from({length:Math.min(50,56-offset)},(_,i)=>({id:offset+i+1,kode:'PL'+(offset+i+1),id_principal:1,id_cabang:1,id_perusahaan:1,nama_customer:'Customer '+(offset+i+1),nama_principal:'Principal'})),total_data:56};
  }
  else if(url.pathname.endsWith('/lphs/1/detail'))data={id:1,id_perusahaan:1,id_cabang:1,id_sales:1,invoices:[{id:1,id_customer:1,no_faktur:'F1',remaining:1000}],claims:[{id:1,id_faktur:1,method:'GIRO',amount:500,giro_number:'BG-TEST',bank:'Bank Test',due_date:'2026-10-31'},{id:2,id_faktur:1,method:'TRANSFER',amount:500}]};
  else if(url.pathname.endsWith('/lphs'))data=[{id:1,kode_lph:'TTGBMM/202610/0002',nama_sales:'Sales',status_dokumen:'DIKEMBALIKAN'}];
  else if(url.pathname.endsWith('/funds')){
   assert.equal(url.searchParams.get('id_lph'),'1');
   const common={id_perusahaan:1,id_cabang:1,id_sales:1,amount:500,remaining:500,received_date:'2026-10-06'};
   data=[{...common,id:1,kind:'GIRO',reference:'BG-TEST',approval:'APPROVED',bank:'Bank Test',due_date:'2026-10-31',giro_status:'NOT_CLEARED'},{...common,id:2,kind:'TRANSFER',reference:'TR-TEST',approval:'APPROVED',account_name:'Customer'},{...common,id:3,kind:'CASH',reference:'PENDING-CASH',approval:'PENDING'}];
  }
  return route.fulfill({json:{data}});
 });
 await page.goto('http://127.0.0.1:5173/master/plafons');
 await page.getByRole('cell',{name:'PL50',exact:true}).waitFor();
 assert.equal(await page.locator('tbody tr').count(),50);
 await page.getByPlaceholder('Pilih cabang',{exact:true}).click();
 await page.getByRole('button',{name:'SLO - Solo',exact:true}).click();
 await page.getByPlaceholder('Pilih perusahaan',{exact:true}).click();
 await page.getByRole('button',{name:'BMM - Perusahaan',exact:true}).click();
 await page.getByPlaceholder('Semua principal',{exact:true}).click();
 await page.getByRole('button',{name:'P1 - Principal',exact:true}).click();
 await Promise.all([page.waitForResponse(r=>r.url().includes('/plafon/paginate') && new URL(r.url()).searchParams.get('id_principal')==='1'),page.getByRole('button',{name:'Cari',exact:true}).click()]);
 assert.equal(requests.at(-1).searchParams.get('id_cabang'),'1');
 assert.equal(requests.at(-1).searchParams.get('id_perusahaan'),'1');
 await page.getByRole('button',{name:'Next',exact:true}).click();
 await page.getByRole('cell',{name:'PL51',exact:true}).waitFor();
 assert.equal(await page.locator('tbody tr').count(),6);
 assert.equal((await page.locator('tbody tr').first().locator('td').first().textContent()).trim(),'51');
 await page.goto('http://127.0.0.1:5173/finance/receipt-workflow');
 await page.getByRole('button',{name:'Buat Kuitansi',exact:true}).click();
 await page.locator('select').filter({has:page.locator('option[value="1"]')}).selectOption('1');
 const invoice=page.locator('article').filter({hasText:'F1'});
 await invoice.locator('input[type="checkbox"]').first().check();
 await page.getByText('Klaim pembayaran Mobile Sales',{exact:true}).waitFor();
 assert.ok((await invoice.textContent()).includes('BG-TEST'));
 assert.ok((await invoice.textContent()).includes('Bank Test'));
 assert.ok((await invoice.textContent()).includes('TR-TEST'));
 assert.ok((await invoice.textContent()).includes('Jatuh tempo'));
 assert.equal(await invoice.locator('label').filter({hasText:'PENDING-CASH'}).locator('input').isDisabled(),true);
 assert.equal(await invoice.locator('label').filter({hasText:'TR-TEST'}).locator('input').isDisabled(),false);
 assert.deepEqual(errors,[]);
 console.log('PASS: Plafon filters sent before pagination, 50 then 6 rows numbered 51; receipt shows giro/transfer claims and fund details, disables pending funds.');
}finally{await browser.close();}
