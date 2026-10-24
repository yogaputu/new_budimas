import assert from 'node:assert/strict';
import test from 'node:test';
import {groupInventoryLots,inventoryUom,inventoryDate,inventoryPcs} from '../src/modules/wms/inventorySummary.js';
const uoms=[{nama:'PCS',faktor_konversi:1},{nama:'BOX',faktor_konversi:8},{nama:'CTN',faktor_konversi:80}];
const lot=(id,patch={})=>({id,id_cabang:5,id_produk:101,product_code:'P1P01',product_name:'Produk 1',location:'R1',qty_pcs:8,batch_number:'TEST',expiry_date:'2027-08-21',uoms,...patch});
test('one product per branch, lots and source payload are unchanged',()=>{
  const rows=[lot(1),lot(2,{location:'R2',qty_pcs:81,expiry_date:'2027-07-21',fifo_rank:2,fefo_rank:1})],before=structuredClone(rows);
  const [group]=groupInventoryLots(rows);
  assert.equal(group.qty_pcs,89);assert.equal(group.uom_label,'1 CTN + 1 BOX + 1 PCS');
  assert.equal(group.location_count,2);assert.equal(group.lot_count,2);assert.equal(group.nearest_expiry,'2027-07-21');
  assert.equal(group.lots[1].fefo_rank,1);assert.equal(group.lots[1].fifo_rank,2);
  assert.deepEqual(rows,before);
});
test('same SKU/lot label never merges different branches or product IDs',()=>{
  assert.equal(groupInventoryLots([lot(1),lot(2,{id_cabang:6}),lot(3,{id_produk:102})]).length,3);
  assert.equal(groupInventoryLots([lot(1,{id_cabang:null}),lot(2,{id_cabang:null})]).length,2);
});
test('empty lots stay inspectable but do not inflate locations or earliest expiry',()=>{
  const [g]=groupInventoryLots([lot(1),lot(2,{location:'EMPTY',qty_pcs:0,expiry_date:'2026-01-01'})]);
  assert.equal(g.location_count,1);assert.equal(g.lot_count,2);assert.equal(g.nearest_expiry,'2027-08-21');
  assert.equal(new Set(g.lots.map(r=>r.lot_key)).size,2);
});
test('date normalization handles legacy GMT, sentinel, invalid or impossible dates',()=>{
  assert.equal(inventoryDate('Wed, 21 Jul 2027 00:00:00 GMT'),'2027-07-21');
  for(const value of [null,'garbage','1900-01-01','2027-02-30'])assert.equal(inventoryDate(value),'');
});
test('PCS is authoritative rather than ready quantity or carton residue',()=>{
  const r=lot(1,{qty_pcs:89,quantity_pc:1,quantity_ct:1,available_qty_pcs:69});
  assert.equal(inventoryPcs(r),89);assert.equal(groupInventoryLots([r])[0].qty_pcs,89);
  assert.equal(inventoryUom(r,8),'1 BOX');
  assert.equal(inventoryPcs({quantity_ct:1,quantity_pc:9,per_unit:80}),89);
});
test('UOM conversion sums PCS before decomposing and supports extra master levels',()=>{
  assert.equal(groupInventoryLots([lot(1,{qty_pcs:79}),lot(2,{qty_pcs:1})])[0].uom_label,'1 CTN');
  assert.equal(inventoryUom({uoms:[...uoms,{nama:'PAL',faktor_konversi:800}]},889),'1 PAL + 1 CTN + 1 BOX + 1 PCS');
});
