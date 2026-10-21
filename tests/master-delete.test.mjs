import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { normalizeError } from '../src/utils/api.js';

test('master conflicts display the API business message', () => {
  const message = 'Customer tidak dapat dihapus karena masih digunakan pada Customer Promo/Voucher 3.';
  assert.equal(normalizeError({ response: { data: { message, error: 'MASTER_IN_USE' } } }), message);
  assert.equal(normalizeError({ response: { data: { result: [{ message }], status: 409 } } }), message);
  assert.equal(normalizeError({ message: 'Network Error' }), 'Network Error');
  assert.equal(normalizeError({}, 'Fallback'), 'Fallback');
});

test('Sales delete makes one atomic request and keeps assignments when rejected', () => {
  const source = readFileSync(new URL('../src/modules/master/pages/SalesPage.vue', import.meta.url), 'utf8');
  const remove = source.split('async function remove() {')[1].split('\nonMounted(')[0];
  assert.match(remove, /await deleteSales\(salesId\)/);
  assert.doesNotMatch(remove, /deleteSalesPrincipalAssignment\(/);
  assert.doesNotMatch(remove, /deleteSalesDetail\(/);
  assert.match(remove, /actionError\.value = normalizeError/);
  assert(remove.indexOf('modalOpen.value = false') > remove.indexOf('await deleteSales'));
});
