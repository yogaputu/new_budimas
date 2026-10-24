import test from 'node:test';
import assert from 'node:assert/strict';
import {workflowJournalType} from '../src/modules/finance/workflowJournalType.js';
test('return and payment journal types are distinct for old and new group keys',()=>{
  for(const reference of ['sales:receipt-return:1:1:2','sales:receipt-return:1:1:retur:8'])assert.equal(workflowJournalType({reference}),'Pemakaian CN / Retur');
  assert.equal(workflowJournalType({reference:'sales:receipt:1:1:2'}),'Pelunasan SO');
  assert.equal(workflowJournalType({reference:'sales:cancel-return:1:retur:8'}),'Pembatalan CN / Retur');
  assert.equal(workflowJournalType({reference:'sales:cancel:1:2'}),'Pembatalan Pembayaran SO');
});
test('legacy bank direction and other workflow labels are preserved',()=>{
  assert.equal(workflowJournalType({reference:'FUND:1',fund_kind:'TRANSFER',fund_transaction_type:'CREDIT'}),'Mutasi Bank Keluar');
  assert.equal(workflowJournalType({reference:'FUND:1',fund_kind:'TRANSFER',fund_transaction_type:'DEBIT'}),'Mutasi Bank Masuk');
  assert.equal(workflowJournalType({reference:'RECEIPT:1:1'}),'Penerimaan Pembayaran');
  assert.equal(workflowJournalType({}),'Koreksi Setoran');
});
