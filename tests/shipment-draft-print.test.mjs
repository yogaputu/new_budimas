import test from 'node:test';
import assert from 'node:assert/strict';
import { schedule, payload } from './fixtures/shipment-draft-print.mjs';
import { MAX_PRINT_DRAFTS, shipmentKey, shipmentReference, shipmentPrintError, prepareShipmentDocument, buildShipmentDraftsHtml } from '../src/utils/shipmentDraftPrint.js';

test('only persisted DRF schedules, including rescheduled DRF, can print', () => {
  assert.equal(shipmentPrintError(schedule()), '');
  assert.equal(shipmentPrintError(schedule(1,{status_order:'2,10'})), '');
  for (const changes of [{status_order:'2,3'}, {status_order:'4'}, {status_order:''}, {__draft_schedule:true}, {id_proses_picking:''}, {id_armada:null}]) {
    assert.ok(shipmentPrintError(schedule(1,changes)));
  }
});
test('reference and selection key do not depend on CSV ordering', () => {
  const row=schedule(1,{id_proses_picking:'32,11,32'});
  assert.equal(shipmentKey(row),'11,32'); assert.equal(shipmentReference(row),'DRF-2-11');
});
test('single draft contains all notes and exact ordered/picked totals', () => {
  const row=schedule(), data=payload(row);
  row.id_proses_picking='11,12'; row.id_sales_order='101,102';
  data.document.source_picking_ids.push(12);
  data.variants[0].allocations.push({...data.variants[0].allocations[0],id_proses_picking:12,id_order_detail:120,id_sales_order:102,no_order:'SO-2',customer_id:102,customer_name:'Toko 2'});
  const result=prepareShipmentDocument(row,data);
  assert.equal(result.orders.length,2); assert.equal(result.orderPcs,28); assert.equal(result.pickedPcs,28);
});
test('split picking batches count ordered quantity once per sales order detail', () => {
  const row=schedule(1,{id_proses_picking:'11,12'}), data=payload(schedule());
  data.document.source_picking_ids=[11,12];
  data.variants[0].allocations[0].draft_picked_pcs=5;
  data.variants[0].allocations.push({...data.variants[0].allocations[0],id_proses_picking:12,draft_picked_pcs:9});
  const result=prepareShipmentDocument(row,data);
  assert.equal(result.orderPcs,14); assert.equal(result.pickedPcs,14);
  assert.equal(result.products[0].quantities.box,1);
});
test('reject partial, moved, missing, duplicated or invalid data instead of partial printing', () => {
  for (const edit of [data=>data.document.source_picking_ids.push(99), data=>data.document.fleet.id=99,
    data=>data.document.branch.id=99, data=>data.variants=[], data=>data.variants[0].allocations.push(data.variants[0].allocations[0]),
    data=>data.variants[0].allocations[0].id_sales_order=999, data=>data.variants[0].allocations[0].total_order_pcs=-1]) {
    const data=payload(); edit(data); assert.throws(()=>prepareShipmentDocument(schedule(),data));
  }
});
test('accept Flask RFC dates and ISO dates for the same delivery day', () => {
  assert.equal(prepareShipmentDocument(schedule(1,{delivering_date:'Fri, 02 Oct 2026 00:00:00 GMT'}),payload()).orderPcs,14);
});
test('batch print is one HTML document with a separate sheet and page break per draft', () => {
  const documents=[1,2].map(id=>prepareShipmentDocument(schedule(id),payload(schedule(id))));
  const html=buildShipmentDraftsHtml(documents);
  assert.equal((html.match(/<!doctype html>/g)||[]).length,1);
  assert.equal((html.match(/class="draft-sheet"/g)||[]).length,2);
  assert.ok(html.includes('break-before: page')); assert.ok(html.includes('display: table-header-group'));
  assert.ok(html.includes('SO-1')&&html.includes('SO-2'));
  assert.throws(()=>buildShipmentDraftsHtml([]));
  assert.throws(()=>buildShipmentDraftsHtml(Array(MAX_PRINT_DRAFTS+1).fill(documents[0])));
});
test('untrusted customer names, notes and product text are HTML escaped', () => {
  const row=schedule(1,{delivery_notes:'<img src=x onerror=alert(1)>'}), data=payload(row);
  data.variants[0].product_name='<script>alert(1)</script>';
  const html=buildShipmentDraftsHtml([prepareShipmentDocument(row,data)]);
  assert.ok(!html.includes('<script>')); assert.ok(!html.includes('<img'));
  assert.ok(html.includes('&lt;script&gt;')&&html.includes('&lt;img'));
});
