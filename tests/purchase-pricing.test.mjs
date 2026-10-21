import test from 'node:test';
import assert from 'node:assert/strict';
import { purchasePricing } from '../src/modules/purchase/utils/purchasePricing.js';
const line = (id = 1, gross = 1000, pcs = 12, tax = 11) => ({ detail_id: id, dpp_gross: gross, quantity_pcs: pcs, tax_rate: tax });
test('product then header percentage then net PPN', () => {
  const r = purchasePricing([line()], { discount_type: 'PERCENT', discount_value: 5 }, { 1: { discount_type: 'PERCENT', discount_value: 10 } });
  assert.equal(r.total, 949.05); assert.equal(r.dpp_net, 855); assert.equal(r.total_pcs, 12);
});
test('rupiah discounts and exact proportional cents', () => {
  const r = purchasePricing([line(1, 1, 1), line(2, 1, 1, 0), line(3, 1, 1)], { discount_value: '.01' });
  assert.equal(r.lines[0].header_discount_allocated, .01); assert.equal(r.dpp_net, 2.99); assert.equal(r.ppn, .22);
});
test('reject over-discount and non-finite inputs without negative preview', () => {
  for (const form of [{ discount_value: 1001 }, { discount_type: 'PERCENT', discount_value: 101 }, { biaya_lainnya: -1 }, { discount_value: 'NaN' }])
    assert.ok(purchasePricing([line()], form).error);
});
test('full discount leaves only additional cost', () => {
  const r = purchasePricing([line()], { discount_type: 'PERCENT', discount_value: 100, biaya_lainnya: 20 });
  assert.equal(r.total, 20); assert.equal(r.ppn, 0);
});
