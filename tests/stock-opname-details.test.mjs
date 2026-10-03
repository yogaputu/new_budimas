import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { buildStockOpnameDetailPayload, normalizeStockOpnameDetail, updateStockOpnameDetail } from '../src/modules/stock-opname/detailQuantities.js';

const snapshot = {
  id_produk: 5,
  stok: 24, stok_fisik: 24, good_stock: 21, bad_stock: 3, stok_sistem: 20,
  harga: 10, quantity_model: 'GOOD_BAD_V1',
  uom_1: 0, uom_2: 0, uom_3: 1,
  label_uom_1: 'BOTOL', label_uom_2: 'PACK', label_uom_3: 'DUS',
  konversi_uom_1: 1, konversi_uom_2: 6, konversi_uom_3: 24
};

test('physical edit survives normalization and the close-escalation request payload', () => {
  const row = updateStockOpnameDetail(normalizeStockOpnameDetail(snapshot), 'stok', '30');
  const [payload] = buildStockOpnameDetailPayload([row]);
  assert.deepEqual([payload.stok, payload.stock, payload.stok_fisik, payload.good_stock, payload.bad_stock], [30, 30, 30, 27, 3]);
  assert.deepEqual([payload.subtotal, payload.subtotal_selisih], [300, 100]);
  assert.deepEqual([payload.uom_3, payload.uom_2, payload.uom_1], [1, 1, 0]);
  assert.equal(normalizeStockOpnameDetail(payload).stok_fisik, 30);
});

test('zero is a valid physical edit and is not replaced with the old snapshot', () => {
  const row = updateStockOpnameDetail(normalizeStockOpnameDetail({ ...snapshot, bad_stock: 0 }), 'stok', '0');
  const [payload] = buildStockOpnameDetailPayload([row]);
  assert.equal(payload.stok_fisik, 0);
  assert.equal(payload.good_stock, 0);
  assert.deepEqual([payload.uom_1, payload.uom_2, payload.uom_3], [0, 0, 0]);
});

test('UOM correction uses the product master labels and conversion factors', () => {
  const row = updateStockOpnameDetail(normalizeStockOpnameDetail(snapshot), 'uom_2', '2');
  const [payload] = buildStockOpnameDetailPayload([row]);
  assert.deepEqual([row.label_uom_1, row.label_uom_2, row.label_uom_3], ['BOTOL', 'PACK', 'DUS']);
  assert.deepEqual([payload.stok_fisik, payload.good_stock, payload.bad_stock], [36, 33, 3]);
  assert.equal(payload.subtotal_selisih, 160);
});

test('opening WMS details keeps physical/Good/Bad totals even when saved UOM counts are absent', () => {
  const row = normalizeStockOpnameDetail({ ...snapshot, uom_1: 0, uom_2: 0, uom_3: 0 });
  assert.deepEqual([row.stok_fisik, row.good_stock, row.bad_stock], [24, 21, 3]);
  assert.equal(row.uom_3, 1);
});

test('missing master units have no guessed labels or conversions and do not erase counts', () => {
  const row = normalizeStockOpnameDetail({ id_produk: 5, stok: 9, stok_fisik: 9, good_stock: 8, bad_stock: 1 });
  assert.deepEqual([row.label_uom_1, row.label_uom_2, row.label_uom_3], ['', '', '']);
  assert.deepEqual([row.konversi_uom_1, row.konversi_uom_2, row.konversi_uom_3], [0, 0, 0]);
  assert.equal(buildStockOpnameDetailPayload([row])[0].stok_fisik, 9);
});

test('Bad and price corrections keep physical totals and calculate the submitted values', () => {
  const badCorrected = updateStockOpnameDetail(normalizeStockOpnameDetail(snapshot), 'bad_stock', '4');
  const priceCorrected = updateStockOpnameDetail(badCorrected, 'harga', '15');
  const [payload] = buildStockOpnameDetailPayload([priceCorrected]);
  assert.deepEqual([payload.stok_fisik, payload.good_stock, payload.bad_stock], [24, 20, 4]);
  assert.deepEqual([payload.subtotal, payload.subtotal_selisih], [360, 60]);
});

test('legacy physical count remains available when canonical columns are null', () => {
  const row = normalizeStockOpnameDetail({ ...snapshot, stok_fisik: null, good_stock: null, quantity_model: 'LEGACY' });
  assert.equal(row.stok_fisik, 24);
  assert.equal(row.good_stock, 24);
});

test('both menu pages wire the same edit and payload functions to close escalation', () => {
  for (const filename of ['StockOpnameListPage.vue', 'StockOpnameEscalationPage.vue']) {
    const source = readFileSync(new URL(`../src/modules/stock-opname/pages/${filename}`, import.meta.url), 'utf8');
    assert.match(source, /updateStockOpnameDetail\(next\[index\], field, value\)/);
    assert.match(source, /buildStockOpnameDetailPayload\(detailRows\.value\)/);
    assert.match(source, /closeEscalatedStockOpname\(/);
    assert.match(source, /data_produks: buildDetailPayload\(\)/);
  }
});
