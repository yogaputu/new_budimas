import test from 'node:test';
import assert from 'node:assert/strict';
import { eligibleReceiptLphs, receiptSalesOptions, receiptLphOptions, receiptInvoices } from '../src/modules/finance/receiptLph.js';

const lph = (id, sales, extra = {}) => ({id, id_sales:sales, nama_sales:`Sales ${sales}`, status_dokumen:'DIKEMBALIKAN', eligible_invoice_count:1, ...extra});

test('only returned LPH with server-verified available invoices are candidates', () => {
  const rows=[lph(1,1), lph(2,2,{status_dokumen:'DITUTUP'}), lph(3,3,{status_dokumen:'AKTIF'}), lph(4,4,{eligible_invoice_count:0}), lph(5,5,{eligible_invoice_count:undefined})];
  assert.deepEqual(eligibleReceiptLphs(rows).map(r=>r.id),[1]);
  assert.deepEqual(receiptSalesOptions(rows),[{value:'1',label:'Sales 1 — 1 LPH tersedia'}]);
});

test('sales are grouped by identity with a count of eligible LPH, not invoices', () => {
  assert.deepEqual(receiptSalesOptions([lph(1,2),lph(2,1,{eligible_invoice_count:8}),lph(3,'1'),lph(4,null)]),[
    {value:'1',label:'Sales 1 — 2 LPH tersedia'},{value:'2',label:'Sales 2 — 1 LPH tersedia'}]);
});

test('closing the last eligible LPH removes sales but closing one of several does not', () => {
  const rows=[lph(1,1),lph(2,1),lph(3,2)];
  rows[0].status_dokumen='DITUTUP';
  assert.equal(receiptSalesOptions(rows)[0].label,'Sales 1 — 1 LPH tersedia');
  rows[1].eligible_invoice_count=0;
  assert.deepEqual(receiptSalesOptions(rows),[{value:'2',label:'Sales 2 — 1 LPH tersedia'}]);
  rows.push(lph(4,1));
  assert.equal(receiptSalesOptions(rows).length,2);
});

test('optional sales filter and historical edit have separate scopes', () => {
  const rows=[lph(1,1),lph(2,2),lph(3,3,{status_dokumen:'DITUTUP',eligible_invoice_count:0})];
  assert.deepEqual(receiptLphOptions(rows).map(r=>r.id),[1,2]);
  assert.deepEqual(receiptLphOptions(rows,'2').map(r=>r.id),[2]);
  assert.deepEqual(receiptLphOptions(rows,'2','3').map(r=>r.id),[3]);
});

test('held or settled invoices cannot be selected, even after opening an eligible LPH', () => {
  const row=lph(1,1,{invoices:[{id:1,remaining:'500'},{id:2,remaining:100,held_by_receipt_id:7},{id:3,remaining:0}]});
  assert.deepEqual(receiptInvoices(row).map(i=>i.id),[1]);
  row.status_dokumen='DITUTUP';
  assert.deepEqual(receiptInvoices(row),[]);
  assert.deepEqual(receiptInvoices(row,true).map(i=>i.id),[1]);
  assert.deepEqual(receiptInvoices(null),[]);
});
