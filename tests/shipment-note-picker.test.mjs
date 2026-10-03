import test from 'node:test';
import assert from 'node:assert/strict';
import { effectScope, reactive } from 'vue';
import { useShipmentNotePicker } from '../src/composables/useShipmentNotePicker.js';

const note = (id, changes = {}) => ({ id, no_order: `SO-${id}`, status_order: 1, id_perusahaan: 3, id_cabang: 2, id_rute: 4, ...changes });
const response = (items, page = 1, total = items.length) => ({ data: { items, pagination: { page, total, total_pages: Math.max(1, Math.ceil(total / 50)) } } });
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
function setup(t, request) {
  const scope = effectScope(), business = reactive({ companyId: '3', branchId: '2' });
  const picker = scope.run(() => useShipmentNotePicker(request, () => business));
  t.after(() => scope.stop());
  return { ...picker, scope, business };
}

test('picker requests confirmed notes with bounded server pagination and inclusive date bounds', async t => {
  const calls = [], p = setup(t, async query => { calls.push(query); return response([note(1)]); });
  Object.assign(p.filters, { dateFrom: '2026-09-29', dateTo: '2026-10-01', search: ' SO-1 ' });
  await p.load();
  assert.deepEqual(calls[0], { id_perusahaan: '3', id_cabang: '2', status: 1, date_from: '2026-09-29', date_to: '2026-10-01', search: 'SO-1', page: 1, per_page: 50 });
  assert.equal(p.ready.value, true);
});
test('unconfirmed and out-of-scope results fail closed; already scheduled and incomplete notes cannot be selected', async t => {
  const p = setup(t, async () => response([note(1), note(2, { status_order: 0 }), note(3, { status_order: null }), note(4, { id_perusahaan: 9 }), note(5, { id_cabang: 9 }), note(6, { id_armada: 1 }), note(7, { id_rute: null })]));
  await p.load(); p.selectRows(p.rows.value, true);
  assert.deepEqual(p.rows.value.map(r => r.id), [1, 6, 7]);
  assert.deepEqual(p.selectedRows.value.map(r => r.id), [1]);
});
test('selection survives server pagination, page-select and removal work without losing other pages', async t => {
  const p = setup(t, async query => response([note(query.page)], query.page, 51));
  await p.load(1); p.selectRows(p.eligibleRows.value, true);
  await p.load(2); p.selectRows(p.eligibleRows.value, true);
  assert.deepEqual(p.selectedRows.value.map(r => r.id), [1, 2]);
  p.selectRows(p.eligibleRows.value, false);
  assert.deepEqual(p.selectedRows.value.map(r => r.id), [1]);
  p.selectRows(p.selectedRows.value, false);
  assert.equal(p.selectedRows.value.length, 0);
});
test('mixed routes cannot proceed to a single draft', async t => {
  const p = setup(t, async () => response([note(1), note(2, { id_rute: 9 })]));
  await p.load(); p.selectRows(p.rows.value, true);
  assert.match(p.selectionProblem.value, /rute yang sama/);
});
test('filter and business-scope changes immediately discard selections and disable stale rows', async t => {
  const p = setup(t, async () => response([note(1)]));
  await p.load(); p.selectRows(p.rows.value, true); p.filters.search = 'new';
  assert.equal(p.selectedRows.value.length, 0); assert.equal(p.ready.value, false); assert.equal(p.rows.value.length, 0);
  await p.load(); p.selectRows(p.rows.value, true); p.business.companyId = '9';
  assert.equal(p.selectedRows.value.length, 0); assert.equal(p.ready.value, false);
});
test('invalid dates or missing business scope prevent network requests', async t => {
  let calls = 0; const p = setup(t, async () => { calls++; return response([]); });
  p.filters.dateFrom = '2026-02-30'; await p.load(); assert.match(p.error.value, /tanggal yang valid/);
  Object.assign(p.filters, { dateFrom: '2026-10-02', dateTo: '2026-10-01' }); await p.load();
  assert.match(p.error.value, /awal/);
  Object.assign(p.filters, { dateFrom: '', dateTo: '' }); p.business.branchId = ''; await p.load();
  assert.equal(calls, 0); assert.equal(p.ready.value, false);
});
test('late responses cannot overwrite a new filter or page response', async t => {
  const pending = [], p = setup(t, () => { const d = deferred(); pending.push(d); return d.promise; });
  const first = p.load(); p.filters.search = 'new'; const second = p.load();
  pending[1].resolve(response([note(2)])); await second;
  pending[0].resolve(response([note(1)])); await first;
  assert.deepEqual(p.rows.value.map(r => r.id), [2]); assert.equal(p.ready.value, true);
});
test('selection is unavailable while loading and on failure, preserved for a safe retry', async t => {
  let fail = false; const p = setup(t, async () => { if (fail) throw new Error('Network test failure'); return response([note(1)]); });
  await p.load(); p.selectRows(p.rows.value, true); fail = true;
  const task = p.load(2); assert.equal(p.ready.value, false); await task;
  assert.equal(p.ready.value, false); assert.equal(p.selectedRows.value.length, 1);
  fail = false; await p.load(); assert.equal(p.ready.value, true); assert.equal(p.selectedRows.value.length, 1);
});
test('changed status on a revisited page removes a stale selected note', async t => {
  let status = 1; const p = setup(t, async () => response([note(1, { status_order: status })]));
  await p.load(); p.selectRows(p.rows.value, true); status = 2; await p.load();
  assert.equal(p.selectedRows.value.length, 0); assert.equal(p.rows.value.length, 0);
});
test('100-note limit rejects the entire extra selection without corrupting checkboxes', async t => {
  const p = setup(t, async query => response(Array.from({ length: 50 }, (_, i) => note((query.page - 1) * 50 + i + 1)), query.page, 150));
  for (const page of [1, 2]) { await p.load(page); p.selectRows(p.rows.value, true); }
  await p.load(3); p.selectRows(p.rows.value, true);
  assert.equal(p.selectedRows.value.length, 100); assert.equal(p.allChecked.value, false); assert.match(p.selectionMessage.value, /Maksimal 100/);
});
test('closing the picker discards late requests', async t => {
  const d = deferred(), p = setup(t, () => d.promise); const task = p.load();
  p.scope.stop(); d.resolve(response([note(1)])); await task;
  assert.equal(p.rows.value.length, 0); assert.equal(p.ready.value, false);
});
test('reset reloads with empty filters and clears selection even when filters were already empty', async t => {
  const p = setup(t, async () => response([note(1)])); await p.load(); p.selectRows(p.rows.value, true);
  await p.reset(); assert.equal(p.selectedRows.value.length, 0); assert.equal(p.ready.value, true);
});
