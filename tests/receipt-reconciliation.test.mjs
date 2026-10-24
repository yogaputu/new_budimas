import test from 'node:test';
import assert from 'node:assert/strict';
import { receiptReconciliationView } from '../src/modules/finance/receiptReconciliation.js';

const invoice = (real=53000,fee=2500,claim=55500)=>({id_faktur:1,total_real:real,total_claim:claim,
  total_funds:real+fee,other:{ADVANCE:0,RETURN:0,FEE:fee},difference:real-claim,matched:false});
const snapshot = (...invoices)=>({invoices,summary:{...invoice(),...Object.fromEntries(
  ['total_real','total_claim','total_funds'].map(key=>[key,invoices.reduce((n,i)=>n+Number(i[key]),0)])),
  other:{ADVANCE:0,RETURN:0,FEE:invoices.reduce((n,i)=>n+Number(i.other.FEE),0)},advance_excess:0,fee_excess:0}});

test('legacy fee snapshot displays zero adjusted difference without changing bank or stored data',()=>{
  const original=snapshot(invoice()),before=JSON.stringify(original);
  const result=receiptReconciliationView(original);
  assert.equal(result.summary.total_real,53000);assert.equal(result.summary.total_reconciled,55500);
  assert.equal(result.summary.cash_difference,-2500);assert.equal(result.summary.difference,0);
  assert.equal(result.summary.matched,true);assert.equal(JSON.stringify(original),before);
});
test('shortage and overage remain visible; different invoices cannot cancel each other out',()=>{
  const result=receiptReconciliationView(snapshot(invoice(52000),invoice(54000)));
  assert.equal(result.summary.difference,0);assert.equal(result.summary.matched,false);
  assert.deepEqual(result.invoices.map(i=>i.difference),[-1000,1000]);
});
test('CN/advance stay separate from cash and fee reconciliation',()=>{
  const input=snapshot(invoice(50000,0,50000));
  input.invoices[0].other={FEE:0,RETURN:40000,ADVANCE:10000};
  const result=receiptReconciliationView(input);
  assert.equal(result.invoices[0].total_reconciled,50000);
  assert.equal(result.invoices[0].matched,true);
});
test('decimal cents stay exact and API string values work',()=>{
  const result=receiptReconciliationView(snapshot({...invoice(),total_real:'0.10',total_claim:'0.30',other:{FEE:'0.20'}}));
  assert.equal(result.summary.difference,0);assert.equal(result.summary.matched,true);
});
test('actual fee case remains matched but other receipt overage is not hidden',()=>{
  const result=receiptReconciliationView(snapshot(invoice(),invoice(91200,0,84360)));
  assert.equal(result.invoices[0].difference,0);assert.equal(result.summary.difference,6840);
  assert.equal(result.summary.matched,false);
});
test('missing old snapshot remains absent and view does not add fake balances',()=>{
  assert.equal(receiptReconciliationView(null),null);
  assert.deepEqual(receiptReconciliationView({}),{});
});
