import test from 'node:test';
import assert from 'node:assert/strict';
import { h, Fragment, Comment } from 'vue';
import { selectOptions, selectedOptionValues } from '../src/shared/utils/selectOptions.js';

test('searchable select preserves numeric IDs, zero and boolean master values', () => {
  const options = selectOptions([h('option', { value: '' }, 'Pilih data'), h(Fragment, null, [
    h('option', { value: 12 }, '  PO-12  ·  Produk A '),
    h('option', { value: 0 }, 'Nol'), h('option', { value: false }, 'Nonaktif')
  ])]);
  assert.deepEqual(options.map(o => o.value), ['', 12, 0, false]);
  assert.equal(options[1].label, 'PO-12 · Produk A');
  assert.deepEqual(selectedOptionValues(['12', '0', 'false'], options, true), [12, 0, false]);
});

test('disabled groups and options remain unselectable; empty attribute means disabled', () => {
  const options = selectOptions([
    h('option', { value: 1, disabled: '' }, 'Perlu approval'),
    h('option', { value: 2, disabled: false }, 'Aktif'),
    h('optgroup', { disabled: true }, [h('option', { value: 3 }, 'Nonaktif')])
  ]);
  assert.deepEqual(options.map(o => o.disabled), [true, false, true]);
});

test('conditional slots and fallback option values do not create phantom choices', () => {
  assert.deepEqual(selectOptions([h(Comment, null, 'v-if'), h('option', null, 'Transfer')]), [
    { value: 'Transfer', label: 'Transfer', disabled: false }
  ]);
});

test('multiple selection preserves source IDs and never includes missing options', () => {
  assert.deepEqual(selectedOptionValues(['7', '999', '8'], [{ value: 7 }, { value: 8 }], true), [7, 8]);
  assert.deepEqual(selectedOptionValues('', [{ value: 7 }], true), []);
});
