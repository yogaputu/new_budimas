// Isolated browser QA: every API intercepted, no warehouse or journal writes.
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const origin=process.env.WAREHOUSE_TEST_ORIGIN||'http://127.0.0.1:5199';
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH});
const uoms=[{id:1,level:1,nama:'PCS',faktor_konversi:1},{id:2,level:2,nama:'BOX',faktor_konversi:8},
  {id:3,level:3,nama:'CTN',faktor_konversi:80},{id:4,level:4,nama:'PAL',faktor_konversi:800}];
const rack={id:1,id_cabang:1,kode_rak:'R1',type_rak:'Tetap',active:true,status:'Aktif',availability:'Terisi',
  status_rak:'Isi',qty_pcs:100,max_qty_karton:10,max_qty_pcs:0,mix_mode:'single_principal',placement_count:1,
  gudang:1,rak:1,level:0,kolom:1,nomor_urut:1,source_type:'manual'};
const placement={id:1,id_cabang:1,id_produk:1,kode_rak:'R1',kode_pallet:'PAL1',kode_barang:'SKU1',nama_barang:'Produk',
  batch_number:'B1',expired_date:'2027-01-31',qty_pcs:100,available_qty_pcs:80,per_unit:80,uoms,
  status:'READY',source_type:'purchase_putaway'};
const pallet={id:1,id_cabang:1,kode_pallet:'PAL1',tipe_pallet:'Kayu',nama_barang:'Produk',availability:'Terisi',
  status_pallet:'Aktif',active:true,used_qty_pcs:100,max_qty_karton:10,max_berat_kg:1000,kode_rak_list:'R1',source_type:'wms_pallet_detail'};
const stock={id:1,id_cabang:1,id_produk:1,nama_perusahaan:'BMM',nama_cabang:'Solo',nama_principal:'Principal 1',kode_sku:'SKU1',
  nama_produk:'Produk',jumlah_total:128,stok_efektif:80,stok_wms:125,jumlah_ready:999,jumlah_good:125,jumlah_bad:3,jumlah_incoming:15,jumlah_titipan:25,jumlah_in_transit:33,
  jumlah_incoming_transit:15,jumlah_loading_transit:11,jumlah_canvas_transit:7,jumlah_delivery_legacy_transit:0,
  tanggal_update:'2026-10-22',waktu_update:'10:00:00'};
try{
  for(const theme of ['light','dark']){
    const page=await browser.newPage({viewport:{width:1440,height:1050}}),errors=[],writes=[],rackRequests=[],placementRequests=[];
    const user={id:1,nama:'Penguji',id_cabang:1,id_perusahaan:1,jabatan:{nama:'SUPER USER'}};
    page.on('pageerror',e=>errors.push(e.message));
    await page.addInitScript(({user,theme})=>{
      localStorage.setItem('budimas_internal_auth',JSON.stringify({access_token:'mock-only',user,permissions:['*'],menus:[]}));
      localStorage.setItem('budimas-theme',theme);
    },{user,theme});
    await page.route('**/*',async route=>{
      const req=route.request(),url=new URL(req.url()),path=url.pathname;
      if(!path.startsWith('/api/'))return url.origin===origin?route.continue():route.abort();
      let data=[];
      if(/detail-login|\/auth\//.test(path))data={user,permissions:['*'],menus:[]};
      else if(path.endsWith('/getCabang'))data=[{id:1,kode:'SLO',nama:'Solo',id_perusahaan:1,id_perusahaan_list:'1,2'}];
      else if(path.endsWith('/getPerusahaan'))data=[{id:1,kode:'BMM',nama:'BMM',id_cabang_list:'1'},{id:2,kode:'TMP',nama:'TMP',id_cabang_list:'1'}];
      else if(path.endsWith('/getPrincipal'))data=[{id:1,kode:'P1',nama:'Principal 1',id_perusahaan:1},{id:2,kode:'P2',nama:'Principal shared',id_perusahaan:1,id_perusahaan_list:'1,2',id_cabang_list:'1'}];
      else if(path.endsWith('/principal-rules')&&req.method()==='POST'){
        writes.push(req.postDataJSON());return route.fulfill({json:{status:200,id:88,message:'Aturan principal berhasil ditambahkan'}});
      }else if(path.endsWith('/wms/racks')){
        rackRequests.push(Object.fromEntries(url.searchParams));
        const rows=url.searchParams.get('active')==='false'?[{...rack,id:2,kode_rak:'OFF1',active:false,status:'Nonaktif'}]:[rack];
        return route.fulfill({json:{data:rows,total:rows.length}});
      }else if(path.endsWith('/wms/placements')){placementRequests.push(Object.fromEntries(url.searchParams));data=[placement];}
      else if(path.endsWith('/wms/pallets'))data=[pallet];
      else if(path.endsWith('/wms/products/options'))data=[{id:1,kode_sku:'SKU1',nama:'Produk',per_unit:80,uoms}];
      else if(path.endsWith('/wms/racks/next-code'))data={...rack,kode_rak:'R2'};
      else if(path.endsWith('/wms/pallets/next-code'))data={kode_pallet:'PAL2',id_cabang:1};
      else if(path.endsWith('/stock-opname/laporan-stock'))data=[stock];
      else if(path.includes('ready-to-load'))data={data:[]};
      else if(req.method()!=='GET')throw Error('Unexpected mutation '+req.method()+' '+path);
      return route.fulfill({json:{data,result:data}});
    });
    const headers=()=>page.locator('table').first().locator('thead th').allTextContents().then(v=>v.map(t=>t.trim()));
    await page.goto(origin+'/wms/master-rak');await page.getByRole('cell',{name:'R1',exact:true}).waitFor();
    assert.deepEqual(await headers(),['Kode Rak','Tipe','Ketersediaan','Status','Jumlah Produk (PCS)','Kapasitas Jumlah (CT)','Principal','Group','Penempatan','Posisi','Sumber']);
    await page.getByRole('combobox',{name:'Status Rak',exact:true}).click();
    await page.getByRole('option',{name:'Nonaktif',exact:true}).click();
    await page.getByRole('button',{name:'Muat Rak',exact:true}).click();
    await page.getByRole('cell',{name:'OFF1',exact:true}).waitFor();
    assert.equal(rackRequests.at(-1).active,'false');assert.equal(rackRequests.at(-1).status_rak,undefined);
    await page.screenshot({path:`/tmp/warehouse-racks-${theme}.png`,fullPage:true,animations:'disabled'});
    await page.goto(origin+'/wms/master-pallet');await page.getByRole('cell',{name:'PAL1',exact:true}).waitFor();
    assert.deepEqual(await headers(),['Kode Pallet','Tipe Pallet','Produk','Ketersediaan','Status','Jumlah Produk (PCS)','Kapasitas Jumlah (CT)','Kapasitas Berat (Kg)','Posisi Rak','Sumber']);
    await page.getByRole('row').filter({has:page.getByRole('cell',{name:'PAL1',exact:true})}).click();
    await page.getByRole('combobox',{name:'Produk',exact:true}).waitFor();
    await page.getByRole('button',{name:'Batal',exact:true}).click();
    await page.goto(origin+'/wms/penempatan');await page.getByRole('cell',{name:'SKU1',exact:true}).waitFor();
    assert.deepEqual(await headers(),['Rak','Pallet','Kode Barang','Produk','Batch','Expired','Rincian UOM','Jumlah Produk (PCS)','Status','Sumber']);
    await page.getByRole('cell',{name:'1 CTN + 2 BOX + 4 PCS',exact:true}).waitFor();
    assert.equal(placementRequests.at(-1).availability,undefined,'Placement is physical, not an effective-ready lot projection');
    await page.screenshot({path:`/tmp/warehouse-placements-${theme}.png`,fullPage:true,animations:'disabled'});
    await page.getByRole('button',{name:'Tambah Penempatan',exact:true}).click();
    await page.getByText('Tanpa pallet',{exact:true}).waitFor();
    await page.getByRole('button',{name:'Batal',exact:true}).click();
    await page.goto(origin+'/stock-opname/report');await page.getByRole('cell',{name:'SKU1',exact:true}).waitFor();
    assert.deepEqual(await headers(),['Perusahaan','Cabang','Principal','Kode SKU','Nama Produk','Total Stok (PCS)','Stok Efektif (PCS)','Stok WMS (PCS)','Good (PCS)','Bad (PCS)','In Transit (PCS)','Last Update']);
    const report=page.getByRole('row').filter({has:page.getByRole('cell',{name:'SKU1',exact:true})});
    await report.getByRole('cell',{name:'80',exact:true}).waitFor();
    await report.getByRole('cell',{name:'128',exact:true}).waitFor();
    assert.equal(await report.getByRole('cell',{name:'125',exact:true}).count(),2);
    await report.getByRole('cell',{name:'33',exact:true}).waitFor();
    await page.getByText('PO/transfer, loading driver, dan canvas',{exact:true}).waitFor();
    assert.equal(await report.getByRole('cell',{name:'999',exact:true}).count(),0);
    await page.screenshot({path:`/tmp/warehouse-report-${theme}.png`,fullPage:true,animations:'disabled'});
    await page.setViewportSize({width:420,height:900});
    await page.screenshot({path:`/tmp/warehouse-report-${theme}-mobile.png`,fullPage:true,animations:'disabled'});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.setViewportSize({width:1440,height:1050});
    await page.goto(origin+'/master/principal-rules');await page.getByRole('button',{name:'+ Tambah Aturan Baru',exact:true}).click();
    const dialog=page.locator('section').filter({has:page.getByRole('heading',{name:'Tambah Aturan Principal',exact:true})}).last();
    for(const [name,option] of [['Cabang','SLO - Solo'],['Perusahaan','TMP - TMP'],['Principal','P2 - Principal shared']]){
      await dialog.getByRole('combobox',{name,exact:true}).click();
      await page.getByRole('option',{name:option,exact:true}).click();
    }
    await dialog.getByRole('button',{name:'Simpan Aturan',exact:true}).click();
    await page.getByText('Aturan principal berhasil ditambahkan.',{exact:true}).waitFor();
    assert.equal(Number(writes[0].id_perusahaan),2);assert.equal(Number(writes[0].id_principal),2);
    assert.deepEqual(errors,[]);await page.close();
    console.log(`PASS ${theme}: principal shared-company form, inactive rack search, exact column orders, physical/UOM values, effective stock, responsive table`);
  }
}finally{await browser.close();}
