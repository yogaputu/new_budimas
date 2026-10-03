import test from 'node:test';
import assert from 'node:assert/strict';
import { draftOrderId, draftEligibilityError, draftSelectionError, notaDateRangeError } from '../src/utils/shipmentDraft.js';
const row = (id, changes={}) => ({id,status_order:1,id_cabang:2,id_perusahaan:3,id_rute:4,...changes});

test('multiple confirmed notes are accepted, without merging their identities',()=>{
  assert.equal(draftSelectionError([row(11),row(12)]),'');
  assert.equal(draftOrderId(row(11)),'11');
});
test('unconfirmed, already planned, invalid and missing-scope notes are not selectable',()=>{
  for(const changes of [{status_order:0},{status_order:2},{status_order:null},{id_armada:1},{delivering_date:'2026-10-01'},{id_rute:null},{id_perusahaan:null},{id:0}])
    assert.ok(draftEligibilityError(row(11,changes)),JSON.stringify(changes));
});
test('different company, branch or route cannot be silently grouped',()=>{
  for(const changes of [{id_perusahaan:8},{id_cabang:8},{id_rute:8}])
    assert.match(draftSelectionError([row(11),row(12,changes)]),/perusahaan, cabang, dan rute/);
});
test('empty, duplicate and over-limit selections are rejected',()=>{
  assert.ok(draftSelectionError([]));
  assert.ok(draftSelectionError([row(11),row(11)]));
  assert.ok(draftSelectionError(Array.from({length:101},(_,i)=>row(i+1))));
  assert.equal(draftSelectionError(Array.from({length:100},(_,i)=>row(i+1))),'');
});
test('date range supports inclusive same day and optional bounds, rejects reversed/invalid dates',()=>{
  for(const range of [['',''],['2026-10-01',''],['','2026-10-01'],['2026-10-01','2026-10-01'],['2026-09-01','2026-10-01']])
    assert.equal(notaDateRangeError(...range),'');
  for(const range of [['2026-10-02','2026-10-01'],['2026-02-30',''],['20261001',''],['not-a-date','']])
    assert.ok(notaDateRangeError(...range));
});
