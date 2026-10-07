import test from 'node:test';
import assert from 'node:assert/strict';
import { paymentPermission } from '../src/utils/paymentPermissions.js';
import { depositSalesOptions } from '../src/modules/finance/depositSales.js';
import { returStatusOptions, returStatusLabel } from '../src/modules/sales-order/returStatus.js';
import { placementBalances } from '../src/modules/wms/placementBalances.js';

test('deposits use sales FK, deduplicate joins, preserve different people with the same name', () => {
  const rows=[{id:772,id_sales:334,nama:'Sales 1 (Test)',id_cabang:5},{id:772,id_sales:334,nama:'Sales 1 (Test)',id_cabang:5},{id:773,id_sales:335,nama:'Sales 1 (Test)',id_cabang:5},{id:774,id_sales:336,nama:'Other',id_cabang:6},{id:777,nama:'Not a sales FK'}];
  assert.deepEqual(depositSalesOptions(rows,5).map(s=>s.value),['334','335']);
});
test('Hak Akses actions are independent and deposit writes are kind-specific', () => {
  for(const action of ['view','create','update','delete','approve']) for(const required of ['view','create','update','delete','approve'])
    assert.equal(paymentPermission([`m.finance.kw.${action}`],`finance.receipts.${required}`),action===required);
  assert.equal(paymentPermission(['m.finance.stk.create'],'finance.funds.create','GIRO'),false);
  assert.equal(paymentPermission(['m.finance.stk.create'],'finance.funds.create','CASH'),true);
  assert.equal(paymentPermission([],'finance.receipts.approve'),false);
  assert.equal(paymentPermission(['m.finance.kw.view'],'finance.funds.view','CASH'),true);
  assert.equal(paymentPermission(['m.finance.kw.view'],'finance.funds.update','CASH'),false);
  assert.equal(paymentPermission(['m.finance.mb.view'],'finance.bank-input.view'),true);
});
test('retur status options and displayed labels always agree', () => {
  assert.deepEqual(returStatusOptions.map(s=>s.value),['0','1','2','4','3','9']);
  for(const option of returStatusOptions) assert.equal(returStatusLabel({status_request:Number(option.value)}),option.label);
});
test('placement quantity uses warehouse report once per SKU and does not invent rack quantities', () => {
  const report=[{id_produk:24,id_cabang:5,kode_sku:'AUTOSOL',jumlah_ready:1000,jumlah_good:1000,jumlah_rak_tetap:4}];
  const lots=[{id:1,id_produk:24,id_cabang:5,qty_pcs:3},{id:2,id_produk:24,id_cabang:5,qty_pcs:1}];
  const rows=placementBalances(report,lots);
  assert.equal(rows.length,1);assert.equal(rows[0].qty_pcs,1000);assert.equal(rows[0].mapping_gap,996);
  assert.deepEqual(lots.map(r=>r.qty_pcs),[3,1]);
  const afterBooking=placementBalances([{...report[0],jumlah_ready:850}],lots)[0];
  assert.equal(afterBooking.qty_pcs,850);assert.equal(afterBooking.mapping_gap,996);
  assert.equal(placementBalances(report,[],{rack:'OTHER'}).length,0);
});
test('multiple legacy stock rows match report totals without duplicate Vue keys or rack totals', () => {
  const report=[{id:7,id_produk:24,id_cabang:5,jumlah_ready:970,jumlah_good:948,jumlah_rak_tetap:4}, {id:24,id_produk:24,id_cabang:5,jumlah_ready:1000,jumlah_good:1000,jumlah_rak_tetap:4}];
  const rows=placementBalances(report,[]);
  assert.equal(rows.length,1);assert.equal(rows[0].qty_pcs,1970);
  assert.equal(rows[0].jumlah_good,1948);assert.equal(rows[0].mapped_pcs,4);
  assert.equal(rows[0].mapping_gap,1944);
  assert.deepEqual(report.map(r=>r.jumlah_ready),[970,1000]);
});
