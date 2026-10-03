import test from 'node:test';
import assert from 'node:assert/strict';
import { pickingGroups, shipmentQrSvg } from '../src/utils/shipmentPicking.js';
const rows = [
  {wms_task_id:1,nota:'SO-A',product_code:'SKU',product_name:'Barang',required_quantity:10,picked_quantity:10},
  {wms_task_id:2,nota:'SO-B',product_code:'SKU',product_name:'Barang',required_quantity:5,picked_quantity:2},
];
test('variant grouping preserves separate invoice allocations and shortage',()=>{
  const groups=pickingGroups(rows,'variant'); assert.equal(groups.length,1);
  assert.equal(groups[0].required,15); assert.equal(groups[0].picked,12); assert.equal(groups[0].rows.length,2);
});
test('nota view separates the same SKU for two invoices',()=>{assert.equal(pickingGroups(rows,'nota').length,2);});
test('shipment QR only accepts canonical safe references',()=>{
  assert.match(shipmentQrSvg('DRF-2-100'),/^<svg/);
  for(const reference of ['SO-A','<script>','DRF-0-2']) assert.throws(()=>shipmentQrSvg(reference));
});
