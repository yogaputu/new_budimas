// Local-only browser test. All business APIs and all external traffic are intercepted.
import assert from 'node:assert/strict';
import { chromium } from '/Users/macairm2/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs';
const origin='http://127.0.0.1:5183', out='/tmp/budimas-draft-picking-20261002.Zuty1L';
const browser=await chromium.launch({headless:true,channel:'chrome'});
const context=await browser.newContext({viewport:{width:1440,height:1000}});
await context.addInitScript(()=>{
  localStorage.setItem('budimas-theme','light');
  localStorage.setItem('budimas_internal_auth',JSON.stringify({access_token:'LOCAL-MOCK-ONLY',user:{id:9,nama:'Operator Uji',id_cabang:2,id_perusahaan:3,id_jabatan:16},permissions:['*'],menus:[]}));
  window.print=()=>{};
});
const rows=[{wms_task_detail_id:41,wms_task_id:31,id_picking:31,nota:'SO-A',product_code:'SKU',product_name:'Produk Uji',required_quantity:10,picked_quantity:10,rak_tetap:'A-01',rack_available_quantity:20},
  {wms_task_detail_id:42,wms_task_id:32,id_picking:32,nota:'SO-B',product_code:'SKU',product_name:'Produk Uji',required_quantity:5,picked_quantity:0,rak_tetap:'A-01',rack_available_quantity:3}];
let status='DRAFT', shortageError=true, loadingStatus='READY_DOCK', completed=false;
let revisionSaved=false;
const requests=[],writes=[],errors=[];
await context.route('**/*',async route=>{
  const req=route.request(),u=new URL(req.url()),p=u.pathname;
  if(p.startsWith('/api/')) {
    requests.push(p); let data=[];
    if(req.method()==='POST') {
      const body=req.postDataJSON(); writes.push({p,body});
      if(p.endsWith('/scan-rak')) {
        assert.equal(body.nota,'DRF-2-100'); assert.equal(body.wms_task_detail_id,42);
        if(shortageError) return route.fulfill({json:{status:'EMPTY',msg:'Stok rak tidak cukup.'}});
        rows[1].picked_quantity+=body.qty_pcs; data={status:'OK',msg:'Picking tersimpan.'};
      } else if(p.endsWith('/request-revision')) { status='REVISION_REQUIRED'; data={status:'OK',message:'Nota masuk Revisi Faktur ERP.'}; }
      else if(p.endsWith('/finalize')) { assert.deepEqual(body.task_ids,[31,32]); status='CHECKER_PENDING'; data={status:'OK',msg:'Draf masuk checker.'}; }
      else if(p.endsWith('/loading/process')) {
        assert.equal(body.id_driver,1); assert.equal(body.id_armada,2); assert.equal(body.delivery_date,'2026-10-02');
        loadingStatus='LOADING'; if(body.action==='complete') completed=true; data={status:'OK',message:'Loading tersimpan.'};
      } else if(p.endsWith('/checker/confirm')) { assert.equal(body.items.length,1); assert.equal(body.items[0].checked_quantity,10); data={status:'OK',message:'Checker OK.'}; }
      else if(p.endsWith('/submit-revisi-faktur')) { assert.equal(body.faktur_data[0].detail_produk[0].pieces_order,3); revisionSaved=true; data={message:'Revisi picking tersimpan.'}; }
      else throw new Error(`Unexpected write ${p}`);
    } else if(p.endsWith('/picking/shipments')) data={data:[{reference:'DRF-2-100',delivering_date:'2026-10-02',note_count:2}]};
    else if(p.includes('/picking/draft-detail/')) data={document:{shipment_reference:'DRF-2-100',nota:'DRF-2-100',status,task_statuses:[status],task_ids:[31,32]},items:rows};
    else if(p.endsWith('/loading/assignments')) data={data:[{id_armada:2,id_driver:1,vehicle:'B 1234 UJI',driver:'Driver Uji',delivery_date:'2026-10-02'}]};
    else if(p.endsWith('/loading/ready-to-load')) {
      assert.equal(u.searchParams.get('id_armada'),'2'); assert.equal(u.searchParams.get('id_driver'),'1'); assert.equal(u.searchParams.get('delivery_date'),'2026-10-02');
      data={data:completed?[]:rows.map(r=>({wms_task_detail_id:r.wms_task_detail_id,ShipmentReference:'DRF-2-100',Nota:r.nota,KodeBarang:'SKU',NamaBarang:'Produk Uji',picked_quantity:r.picked_quantity,ScheduleKey:'1|2|2026-10-02|1',ScheduleStatus:'SCHEDULED',ArmadaRencana:'B 1234 UJI',DriverRencana:'Driver Uji',HelperRencana:'Helper Uji',ScheduledDeliveryDate:'2026-10-02',loading_status:loadingStatus}))};
    } else if(p.endsWith('/checker/pending')) data=[{id:31,nota:'SO-A',shipment_reference:'DRF-2-100',status:'CHECKER_PENDING',total_item:1,details:[{id:41,kode_barang:'SKU',nama_barang:'Produk Uji',picked_quantity:10,handling_class:'CARTON'}]}];
    else if(p.endsWith('/getPerusahaan')) data=[{id:3,nama:'Perusahaan Uji',id_cabang_list:'2'}];
    else if(p.endsWith('/getCabang')) data=[{id:2,nama:'Cabang Uji',id_perusahaan:3}];
    else if(p.endsWith('/get-list-rute-revisi-faktur')) data=revisionSaved?[]:[{id_rute:4,id_armada:2,id_driver:1,delivering_date:'2026-10-02',id_sales_order:'12',nama_rute:'Rute Uji',kode:'R1'}];
    else if(p.endsWith('/get-list-faktur-revisi-faktur')) data=[{id_sales_order:'12',no_faktur:'INV-B',nama_customer:'Toko B'}];
    else if(p.endsWith('/get-detail-faktur/12')) data={detail_faktur:{id_sales_order:12,picking_revision:true},list_detail_order:[{id_order_detail:21,id_sales_order:12,id_produk:1,nama_produk:'Produk Uji',kode_sku:'SKU',pieces_order:5,pieces_delivered:0,box_order:0,karton_order:0,hargaorder:100,subtotalorder:500,total_nilai_discount:0,puom1_kode:'PCS',puom1_nama:'PCS',konversi_level1:1,picking_actual_pcs:3,shipment_reference:'DRF-2-100'}]};
    return route.fulfill({json:data});
  }
  if(u.origin!==origin) return route.abort();
  return route.continue();
});
const page=await context.newPage(); page.on('pageerror',e=>errors.push(e.message)); page.on('dialog',d=>d.accept());
try {
  await page.goto(origin+'/distribution/picking');
  await page.getByLabel('Pilih draf',{exact:true}).selectOption('DRF-2-100');
  await page.getByRole('button',{name:'Pick nota ini'}).last().waitFor();
  assert.equal(await page.getByRole('button',{name:'Selesai Picking → Checker'}).isDisabled(),true);
  await page.getByLabel('Tampilan',{exact:true}).selectOption('nota');
  assert.equal(await page.locator('article').count(),2);
  await page.getByLabel('Tampilan',{exact:true}).selectOption('variant');
  assert.equal(await page.locator('article').count(),1);
  await page.getByRole('button',{name:'Pick nota ini'}).last().click();
  await page.getByRole('alert').filter({hasText:'Stok rak tidak cukup'}).waitFor();
  shortageError=false;
  await page.getByRole('button',{name:'Pick nota ini'}).last().click();
  await page.getByRole('status').filter({hasText:'Picking tersimpan'}).waitFor();
  await page.getByLabel('Catatan kekurangan').fill('SO-B hanya mendapat 3 PCS.');
  await page.getByRole('button',{name:'Ajukan revisi faktur kurang picked'}).click();
  await page.getByText(/Ditahan: selesaikan Revisi Faktur/).waitFor();
  assert.equal(await page.getByRole('button',{name:'Selesai Picking → Checker'}).count(),0);
  await page.screenshot({path:out+'/picking-revision.png',fullPage:true});
  rows[1].required_quantity=3; status='DRAFT';
  await page.getByRole('button',{name:'Muat draf',exact:true}).click();
  await page.getByLabel('Nama picker',{exact:true}).fill('Picker Uji');
  await page.getByRole('button',{name:'Selesai Picking → Checker'}).click();
  await page.getByRole('status').filter({hasText:'Draf masuk checker'}).waitFor();
  const popupPromise=page.waitForEvent('popup'); await page.getByRole('button',{name:'Cetak QR draf'}).click(); const popup=await popupPromise;
  await popup.locator('svg').waitFor(); await popup.close();
  await page.goto(origin+'/wms');
  await page.getByRole('button',{name:'Loading',exact:true}).click();
  assert.equal(requests.filter(p=>p.endsWith('/loading/ready-to-load')).length,0);
  assert.equal(await page.getByRole('button',{name:'Tampilkan barang',exact:true}).isDisabled(),true);
  await page.getByLabel('Armada',{exact:true}).selectOption('2');
  await page.getByLabel('Driver',{exact:true}).selectOption('1');
  await page.getByLabel('Tanggal pengiriman',{exact:true}).fill('2026-10-02');
  await page.getByRole('button',{name:'Tampilkan barang',exact:true}).click();
  await page.getByRole('button',{name:'Mulai Loading',exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Selesaikan Loading',exact:true}).isDisabled(),true);
  await page.screenshot({path:out+'/loading-selected.png',fullPage:true});
  await page.getByRole('button',{name:'Mulai Loading',exact:true}).click();
  await page.getByRole('button',{name:'Selesaikan Loading',exact:true}).click();
  await page.getByText('Belum ada barang lolos checker / seluruh barang sudah dimuat pada jadwal ini.').waitFor();
  await page.getByRole('button',{name:'Checker',exact:true}).click();
  await page.getByLabel('Nama Checker',{exact:true}).fill('Checker Uji');
  await page.getByLabel('Loading Dock',{exact:true}).fill('A');
  await page.getByPlaceholder('Hasil hitung fisik').fill('10');
  await page.getByLabel('Kondisi',{exact:true}).selectOption('GOOD');
  await page.getByRole('button',{name:'Simpan Hasil Checker OK / NG'}).click();
  await page.getByText('Checker OK.',{exact:true}).waitFor();
  await page.goto(origin+'/distribution/invoice-revisions?id_cabang=2&sales_order_id=12');
  await page.getByText(/Revisi kekurangan picking: qty disiapkan/).waitFor();
  const revisionRow=page.locator('tr').filter({has:page.getByText('DRF-2-100 · Picked 3 PCS',{exact:true})});
  assert.equal(await revisionRow.locator('input[type=number]').first().inputValue(),'3');
  assert.equal(await page.getByRole('button',{name:'Hapus',exact:true}).count(),0);
  assert.equal(await page.getByRole('button',{name:'Tambah Produk',exact:true}).count(),0);
  await page.screenshot({path:out+'/invoice-revision.png',fullPage:true});
  await Promise.all([
    page.waitForResponse(r=>new URL(r.url()).pathname.endsWith('/get-list-rute-revisi-faktur')),
    page.getByRole('button',{name:'Submit Revisi Faktur',exact:true}).click()
  ]);
  assert.equal(revisionSaved,true);
  assert.deepEqual(errors,[]);
  console.log(`PASS: draft QR, variant/nota, stock error, partial pick, revision hold, finalize, carton checker, explicit loading filters/start/complete; ${writes.length} mocked writes.`);
} catch (error) {
  console.error('Page:',page.url(),'Errors:',errors,'Body:',(await page.locator('body').innerText()).slice(0,8000));
  await page.screenshot({path:out+'/ui-failure.png',fullPage:true}); throw error;
} finally { await browser.close(); }
