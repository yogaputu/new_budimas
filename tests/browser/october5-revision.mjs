// Mocked browser regression; every API request is intercepted.
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
import assert from 'node:assert/strict';
(async()=>{
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true,args:['--no-sandbox']});
try {
const p=await browser.newPage();p.setDefaultTimeout(15000);const errors=[],requests=[];
p.on('pageerror',e=>errors.push(e.message));
const user={id:1,id_user:1,nama:'Test Admin',is_superuser:true,role:'superadmin'};
await p.addInitScript(u=>localStorage.setItem('budimas_internal_auth',JSON.stringify({access_token:'test-only',user:u,permissions:['*'],menus:[]})),user);
await p.route('**/*',async route=>{
 const url=new URL(route.request().url());if(url.pathname.startsWith('/api/')){let data=[];
 if(url.pathname.includes('detail-login') || url.pathname.includes('/auth/'))data={user,permissions:['*'],menus:[]};
 else if(url.pathname.includes('getPerusahaan'))data=[{id:1,kode:'BMM',nama:'Perusahaan',id_cabang_list:'1'}];
 else if(url.pathname.includes('getCabang'))data=[{id:1,id_perusahaan:1,kode:'SLO',nama:'Solo'}];
 else if(url.pathname.includes('getPrincipal'))data=[{id:1,id_perusahaan:1,kode:'P1',nama:'Principal'}];
 else if(url.pathname.includes('laporan-stock'))data=[{id:1,nama_perusahaan:'Perusahaan',nama_cabang:'Solo',nama_principal:'Principal',kode_sku:'SKU1',nama_produk:'Produk',jumlah_ready:60,jumlah_good:100,jumlah_bad:3,jumlah_incoming:25,uom:'PCS',tanggal_update:'2026-10-05',waktu_update:'15:30:00'}];
 else if(url.pathname.includes('list-orders')) {requests.push(url);data={items:[{id:1,status_order:3,no_order:'SO1',workflow_status:'CKC',workflow_status_label:'Menunggu checker'}],status_options:[{value:'DRF',label:'DRF · Draft kiriman'},{value:'CKC',label:'CKC · Menunggu checker'}],pagination:{page:1,per_page:50,total:1,total_pages:1},summary:{total_orders:1}};}
 return route.fulfill({json:{data}});
 }
 if(url.origin!=='http://127.0.0.1:5173')return route.abort();return route.continue();
});
await p.goto('http://127.0.0.1:5173/stock-opname/report');await p.getByRole('cell',{name:'SKU1',exact:true}).waitFor();
assert.deepEqual(await p.locator('thead th').allTextContents(),['Perusahaan','Cabang','Principal','Kode SKU','Produk','Stok Ready','Good','Bad','In Transit','Satuan','Last Update']);
await p.getByRole('cell',{name:'2026-10-05 15:30:00',exact:true}).waitFor();
await p.goto('http://127.0.0.1:5173/sales-order');await p.getByRole('cell',{name:'CKC · Menunggu checker',exact:true}).waitFor();
const select=p.locator('select').filter({has:p.locator('option[value="CKC"]')});
assert.equal(await select.count(),1);assert.equal(await select.locator('option[value="PCK"]').count(),0);
await select.selectOption('CKC');await Promise.all([p.waitForResponse(r=>r.url().includes('list-orders') && new URL(r.url()).searchParams.get('workflow_status')==='CKC'),p.getByRole('button',{name:'Terapkan',exact:true}).click()]);
assert.equal(requests.at(-1).searchParams.get('include_workflow_statuses'),'true');
assert.deepEqual(errors,[]);console.log('PASS ERP: eleven stock columns, timestamp, dynamic workflow status filter.');
}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
