import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import { transferJournalWarning } from '../src/modules/stock-transfer/journalFeedback.js';
import { normalizeError, normalizeList, unwrapResponse } from '../src/utils/api.js';

test('successful receipt and escalation show the API journal warning', () => {
  const warning = 'Jurnal belum terbentuk karena mapping Jurnal Setting belum tersedia.';
  assert.equal(transferJournalWarning({ status: 'success', journal_status: 'not_configured', warnings: [warning] }), warning);
});

test('partially configured journals retain their warning without repeated messages', () => {
  assert.equal(transferJournalWarning({ journal_status: 'partially_created', warnings: ['Jurnal belum terbentuk.', 'Jurnal belum terbentuk.'] }), 'Jurnal belum terbentuk.');
});

test('status alone provides an actionable fallback while configured success stays clear', () => {
  assert.match(transferJournalWarning({ journal_status: 'not_configured' }), /Jurnal belum terbentuk/);
  assert.equal(transferJournalWarning({ journal_status: 'created', warnings: [] }), '');
  assert.equal(transferJournalWarning({ status: 'success' }), '');
});

for (const [mode, action, successPrefix] of [['receipt', 'receive', 'Penerimaan'], ['escalation', 'close-escalation', 'Eskalasi']]) {
  test(`${mode} action keeps the successful receipt warning after closing the modal and reloading`, async () => {
    const source = readFileSync(new URL('../src/modules/stock-transfer/pages/TransferProcessPage.vue', import.meta.url), 'utf8');
    const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import[\s\S]*?;\s*$/gm, '');
    const warning = 'Jurnal belum terbentuk karena mapping Jurnal Setting belum tersedia.';
    const calls = [];
    const receive = async () => {
      calls.push(action);
      return { data: { status: 'success', journal_status: 'not_configured', warnings: [warning] } };
    };
    const context = {
      ref: (value) => ({ value }), reactive: (value) => value,
      computed: (getter) => ({ get value() { return getter(); } }),
      onMounted: () => {}, watch: () => {},
      useRoute: () => ({ meta: { processMode: mode } }),
      useAuthStore: () => ({ user: { id: 99 } }),
      toLocalDateInputValue: () => '2026-09-28',
      transferJournalWarning, normalizeError, normalizeList, unwrapResponse,
      receiveStockTransfer: receive, closeEscalatedStockTransfer: receive,
      getStockTransfers: async () => { calls.push('reload'); return { data: [] }; }
    };
    vm.createContext(context);
    vm.runInContext(`${script}\nglobalThis.state = { runModalAction, selectedTransfer, detailRows, feedback, journalWarning, modalError };`, context);
    const state = context.state;
    state.selectedTransfer.value = { id: 8, nota_stock_transfer: 'BMM-8', id_cabang_tujuan: 6 };
    state.detailRows.value = [{ id_produk: 50, uom_1: 10 }];
    await state.runModalAction(action);
    assert.deepEqual(calls, [action, 'reload']);
    assert.equal(state.selectedTransfer.value, null);
    assert.equal(state.modalError.value, '');
    assert.match(state.feedback.value, new RegExp(`^${successPrefix} BMM-8 berhasil`));
    assert.equal(state.journalWarning.value, warning);
  });
}
