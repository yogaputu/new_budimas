import test from 'node:test';
import assert from 'node:assert/strict';
import { buildPickingReferenceHtml, pickingPrintDocument } from './pickingReferencePrint.js';

const rows = [
  { nota: 'N1', product_code: 'P1', product_name: '<script>bad</script>', required_quantity: 20, picked_quantity: 10 },
  { nota: 'N2', product_code: 'P1', product_name: '<script>bad</script>', required_quantity: 30, picked_quantity: 30 },
];
test('group totals retain each invoice and sum variant allocations', () => {
  const d = pickingPrintDocument('DRF-5-10', rows);
  assert.equal(d.orders.length, 2);
  assert.equal(d.products.length, 1);
  assert.equal(d.products[0].orderPcs, 50);
  assert.equal(d.products[0].pickedPcs, 40);
});
test('three formats escape product names and retain draft QR anchor', () => {
  const d = pickingPrintDocument('DRF-5-10', rows);
  for (const mode of ['nota', 'variant', 'qr']) {
    const html = buildPickingReferenceHtml([d], mode);
    assert.match(html, /DRF-5-10/);
    assert.ok(!html.includes('<script>bad</script>'));
  }
  assert.match(buildPickingReferenceHtml([d], 'variant'), /&lt;script&gt;/);
  assert.match(buildPickingReferenceHtml([d], 'nota'), /—/);
  assert.match(buildPickingReferenceHtml([d], 'qr'), /<svg/);
});
test('reject invalid mode, empty selection, oversized selection and forged QR', () => {
  const d = pickingPrintDocument('DRF-5-10', rows);
  assert.throws(() => buildPickingReferenceHtml([d], 'unknown'));
  assert.throws(() => buildPickingReferenceHtml([], 'nota'));
  assert.throws(() => buildPickingReferenceHtml(Array(51).fill(d), 'nota'));
  assert.throws(() => buildPickingReferenceHtml([{ ...d, reference: '<script>' }], 'qr'));
});

test('combined invoice totals count each source order once, not once per product', () => {
  const lines = [
    { ...rows[0], nota: 'F1', id_sales_order: 1, order_amount: 100, order_date: '2026-10-12' },
    { ...rows[0], nota: 'F1', product_code: 'P2', id_sales_order: 1, order_amount: 100 },
    { ...rows[1], nota: 'F1', id_sales_order: 2, order_amount: 200 },
  ];
  const d = pickingPrintDocument('DRF-5-10', lines);
  assert.equal(d.orders.length, 1);
  assert.equal(d.orders[0].amount, 300);
  lines[2].order_amount = null;
  assert.equal(pickingPrintDocument('DRF-5-10', lines).orders[0].amount, null);
});

test('nota includes grand total, operator and cost fields without fabricating missing costs', () => {
  const d = pickingPrintDocument('DRF-5-10', rows.map((r,i) => ({...r,order_amount:i ? 200 : 100,order_date:'2026-10-01'})));
  d.document.delivering_date='2026-10-01';
  const html=buildPickingReferenceHtml([d],'nota',{printedBy:'ADMIN <test>',printedAt:'2026-10-01T10:27:00Z'});
  assert.match(html,/<strong>300\.00<\/strong>/);
  assert.match(html,/ADMIN &lt;test&gt;/);
  assert.match(html,/01\/10\/2026 17:27/);
  assert.match(html,/Perkiraan Biaya Parkir: —/);
  assert.match(html,/KAMIS \/ 01 - 10 - 2026/);
  d.document.estimated_parking_cost=0;d.document.estimated_unloading_cost=10000;
  assert.match(buildPickingReferenceHtml([d],'nota'),/Total Perkiraan Biaya: 10,000\.00/);
});

test('QR uses real draft date or missing marker, never generated time', () => {
  const d=pickingPrintDocument('DRF-5-10',rows);
  d.document.generated_at='2026-10-12T13:00:00Z';
  d.document.delivering_date='2026-10-01';d.document.driver={name:'BU MEYLIANA'};d.row.cargo_zone='FOOD';
  let html=buildPickingReferenceHtml([d],'qr');
  assert.match(html,/<div class="label-meta"><p>—<\/p>/);
  assert.ok(!html.includes('12/10/2026 20:00'));
  d.document.draft_created_at='2026-10-01 14:45:00';
  html=buildPickingReferenceHtml([d],'qr');
  assert.match(html,/01\/10\/2026 14:45/);assert.match(html,/BU MEYLIANA/);assert.match(html,/FOOD/);
});

test('missing amount is not converted to zero or included in a partial grand total', () => {
  const d=pickingPrintDocument('DRF-5-10',rows.map((r,i)=>({...r,order_amount:i?'':100})));
  assert.equal(d.orders[1].amount,null);
  assert.match(buildPickingReferenceHtml([d],'nota'),/<strong>—<\/strong>/);
});

test('each draft starts a new page and physical page numbering is browser-generated', () => {
  const d=pickingPrintDocument('DRF-5-10',rows);
  const html=buildPickingReferenceHtml([d,{...d,reference:'DRF-5-20'}],'variant');
  assert.equal((html.match(/class="report-sheet"/g)||[]).length,2);
  assert.match(html,/break-before: page/);assert.match(html,/counter\(pages\)/);
  assert.match(html,/<th>Dock<\/th><th>Ricikan<\/th>/);
});

test('Dock and Ricikan show unresolved formula text instead of location or picked quantity', () => {
  const d = pickingPrintDocument('DRF-5-10', rows);
  d.row.dock_code = 'DOCK-TEST';
  const html = buildPickingReferenceHtml([d], 'variant');
  assert.match(html, /<td>Rumus belum ditemukan<\/td><td>Rumus belum ditemukan<\/td>/);
  assert.equal((html.match(/Rumus belum ditemukan/g) || []).length, 2);
  assert.ok(!html.includes('DOCK-TEST'));
  assert.ok(!html.includes('Picked (PCS)'));
});
