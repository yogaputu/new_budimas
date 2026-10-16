import test from 'node:test';
import assert from 'node:assert/strict';
import { returnUomField, returnUomQuantities, returnUomTotal } from './productUom.js';
import { productUoms, productUomTotal, productUomQuantities, emptyProductUomValues, distributeProductUom, formatProductUomQty } from './productUom.js';
const master = count => ({ uoms: Array.from({length:count},(_,i)=>({id:100+i,level:i+1,nama:['PCS','BOX','CT','BUNDLE','PALLET','CONTAINER'][i],faktor_konversi:10**i})) });
test('GOOD/BAD return quantities keep extra units independent',()=>{
  const row={...master(6),[returnUomField(4,'good')]:2,[returnUomField(6,'bad')]:1};
  assert.equal(returnUomTotal(row,'good'),2000);
  assert.equal(returnUomTotal(row,'bad'),100000);
  assert.equal(returnUomQuantities(row,'good')[3].quantity,2);
});
for (const count of [1,2,3,4,6]) test(`master determines exactly ${count} units; totals and payload keep every level`,()=>{
  const product=master(count), values=Object.fromEntries(product.uoms.map(u=>[`uom${u.level}`,2]));
  assert.equal(productUoms(product).length,count);
  assert.equal(productUomTotal(product,values),2*Array.from({length:count},(_,i)=>10**i).reduce((a,b)=>a+b));
  assert.equal(productUomQuantities(product,values).at(-1).quantity,2);
  assert.equal(productUomQuantities(product,values).at(-1).level,count);
  assert.equal(Object.keys(emptyProductUomValues(product)).length,count);
  assert.equal(productUomTotal(product,distributeProductUom(product,123456)),123456);
  assert.match(formatProductUomQty(product,values),new RegExp(product.uoms.at(-1).nama));
});
test('authoritative master replaces stale legacy flags; absent units are not invented',()=>{
  assert.equal(productUoms({...master(4),hasUom3:false}).length,4);
  assert.deepEqual(productUoms({uoms:[],Uom1Label:'PCS'}),[]);
  assert.equal(productUoms({Uom1Label:'PCS',Uom2Label:'BOX',Konversi2:12}).length,2);
});
test('JSON cached stock and sparse levels preserve UOM identifiers',()=>{
  const product={stok:JSON.parse(JSON.stringify(master(6)))};
  product.stok.uoms.splice(1,1);
  assert.deepEqual(productUoms(product).map(u=>u.level),[1,3,4,5,6]);
  assert.equal(productUomQuantities(product,{uom6:1}).at(-1).uom_id,105);
});
