import test from 'node:test';
import assert from 'node:assert/strict';
import { cents, allocationLimit, remainingAfterChoices, receiptPayload, workflowDate, sourceMatchesInvoice, initialAllocationAmount } from '../src/modules/finance/receiptAllocation.js';
const cash={id:1,kind:'CASH',remaining:'1000.00'}, bank={id:2,kind:'TRANSFER',remaining:'1000.00'};
const claims=[{id_faktur:1,method:'CASH',amount:'1000.00'},{id_faktur:2,method:'CASH',amount:'1000.00'}];
const invoice=id=>({id,selected:true,remaining:'1000',sources:[],fees:[],excess_treatment:'ADVANCE'});
test('allocation cents remain exact and invalid values do not become money',()=>{assert.equal(cents('0.29'),29);assert.equal(cents('25.3'),2530);for(const v of ['-1','1.001','NaN'])assert.equal(cents(v),0);});
test('one source shared between invoices has a shared remaining cap',()=>{const a=invoice(1),b=invoice(2);a.sources=[{id_source:1,amount:'600'}];assert.equal(allocationLimit(b,cash,[a,b],[cash,bank],claims),400);assert.equal(allocationLimit(a,cash,[a,b],[cash,bank],claims),1000);});
test('cash conversion can fund second invoice without rewriting first invoice claim',()=>{const a=invoice(1),b=invoice(2);assert.equal(allocationLimit(b,bank,[a,b],[cash,bank],claims),1000);a.sources=[{id_source:1,amount:'1000'}];assert.equal(allocationLimit(b,bank,[a,b],[cash,bank],claims),1000);});
test('cash and transfer share a claim pool but cash cannot consume transfer-only claim',()=>{const a=invoice(1);a.sources=[{id_source:1,amount:'600'}];assert.equal(allocationLimit(a,bank,[a],[cash,bank],claims),400);a.sources=[];assert.equal(allocationLimit(a,cash,[a],[cash,bank],[{id_faktur:1,method:'TRANSFER',amount:1000}]),0);});
test('payload preserves explicit source amounts and multiple fees',()=>{const a=invoice(1);a.sources=[{id_source:1,amount:'600.25'}];a.fees=[{id_fee_type:2,amount:'10'}];assert.equal(remainingAfterChoices(a),389.75);assert.deepEqual(receiptPayload({invoices:[a]}).invoices[0],{id_faktur:1,sources:[{id_source:1,amount:'600.25'}],fees:[{id_fee_type:2,amount:'10'}],excess_treatment:'ADVANCE'});});
test('editing a cancelled legacy receipt preserves its named fee',()=>{const a=invoice(1);a.legacy_fee={name:'Meterai lama',amount:'100'};assert.equal(remainingAfterChoices(a),900);const payload=receiptPayload({invoices:[a]}).invoices[0];assert.equal(payload.fee,'100');assert.equal(payload.fee_name,'Meterai lama');});
test('date filters support ISO and Flask RFC date serialization',()=>{for(const v of ['2026-10-06','2026-10-06T00:00:00','Tue, 06 Oct 2026 00:00:00 GMT'])assert.equal(workflowDate(v),'2026-10-06');assert.equal(workflowDate('not a date'),'');assert.equal(workflowDate(null),'');});
test('bank and giro can cross sales while cash remains owned by LPH sales',()=>{
  const lph={id_perusahaan:1,id_cabang:5,id_sales:334},i={...invoice(1),id_customer:10};
  const f={remaining:100,id_perusahaan:1,id_cabang:5,id_sales:772};
  for(const kind of ['TRANSFER','GIRO'])assert.equal(sourceMatchesInvoice({...f,kind},i,lph),true);
  assert.equal(sourceMatchesInvoice({...f,kind:'CASH'},i,lph),false);
  assert.equal(sourceMatchesInvoice({...f,kind:'CASH',id_sales:'334'},i,lph),true);
});
test('all sources retain company branch customer and positive balance restrictions',()=>{
  const lph={id_perusahaan:1,id_cabang:5,id_sales:334},i={...invoice(1),id_customer:10};
  for(const kind of ['CASH','TRANSFER','GIRO','RETURN','ADVANCE']){
    const f={kind,remaining:100,id_perusahaan:1,id_cabang:5,id_customer:10};
    assert.equal(sourceMatchesInvoice(f,i,lph),true);
    for(const change of [{id_perusahaan:2},{id_cabang:6},{id_customer:11},{remaining:0}])assert.equal(sourceMatchesInvoice({...f,...change},i,lph),false);
  }
});
test('return defaults to invoice need not the entire credit note; edit amount is preserved',()=>{
  const a={...invoice(1),remaining:'122100'},b=invoice(2),f={id:3,kind:'RETURN',remaining:'1165500'};
  assert.equal(initialAllocationAmount(a,f,[a,b],[f],[]),122100);
  a.sources=[{id_source:3,amount:'100000.25'}];
  assert.equal(allocationLimit(b,f,[a,b],[f],[]),1065499.75);
  assert.equal(receiptPayload({invoices:[a]}).invoices[0].sources[0].amount,'100000.25');
});
test('advance supports split and does not automatically overallocate a covered invoice',()=>{
  const a=invoice(1),b=invoice(2),f={id:4,kind:'ADVANCE',remaining:'1500'};
  assert.equal(initialAllocationAmount(a,f,[a,b],[f],[]),1000);
  a.sources=[{id_source:4,amount:'600'}];
  assert.equal(initialAllocationAmount(b,f,[a,b],[f],[]),900);
  b.sources=[{id_source:4,amount:'900'}];
  assert.equal(allocationLimit(a,f,[a,b],[f],[]),600);
  a.sources=[{id_source:1,amount:'1000'}];
  assert.equal(initialAllocationAmount(a,f,[a,b],[cash,f],claims),0);
});
