// Display-only grouping. Lot identity, ranking and quantities remain untouched.
const quantity=value=>Number.isFinite(Number(value))?Math.max(0,Number(value)):0;
export function inventoryPcs(row) {
  for(const key of ['qty_pcs','quantity_pcs','total_pcs']) {
    if(row[key]!==null&&row[key]!==undefined&&row[key]!=='')return quantity(row[key]);
  }
  const factor=Number(row.per_unit || row.isiperkarton || 0);
  return quantity(row.quantity_pc)+(factor>0?quantity(row.quantity_ct)*factor:0);
}

export function inventoryDate(value) {
  if(!value)return '';
  const raw=String(value),parsed=new Date(raw);
  const iso=/^\d{4}-\d{2}-\d{2}/.test(raw)?raw.slice(0,10):Number.isFinite(parsed.getTime())?parsed.toISOString():'';
  if(!iso)return '';
  const day=iso.slice(0,10),date=new Date(day+'T00:00:00Z');
  return Number.isFinite(date.getTime())&&date.toISOString().slice(0,10)===day&&day>'1900-01-01'?day:'';
}

export function inventoryUom(row,total=inventoryPcs(row)) {
  const raw=Array.isArray(row.uoms)&&row.uoms.length?row.uoms:[
    {nama:row.uom3_nama || 'CTN',faktor_konversi:row.uom3_factor || row.per_unit || row.isiperkarton},
    {nama:row.uom2_nama || 'BOX',faktor_konversi:row.uom2_factor || row.isiperbox}
  ];
  const seen=new Set(),units=[...raw,{nama:'PCS',faktor_konversi:1}]
    .map(u=>({name:u.nama||u.name,factor:Number(u.faktor_konversi||u.factor)}))
    .filter(u=>u.name&&Number.isSafeInteger(u.factor)&&u.factor>0)
    .sort((a,b)=>b.factor-a.factor).filter(u=>!seen.has(u.factor)&&seen.add(u.factor));
  let remaining=quantity(total);const parts=[];
  for(const unit of units){const n=Math.floor(remaining/unit.factor);remaining-=n*unit.factor;if(n)parts.push(`${n.toLocaleString('id-ID')} ${unit.name}`);}
  return parts.join(' + ') || '0 PCS';
}

export function groupInventoryLots(rows=[]) {
  const grouped=new Map();
  rows.forEach((row,index)=>{
    const branch=row.id_cabang,product=row.id_produk || row.product_code;
    const key=JSON.stringify([branch??`unknown-${index}`,product||`unknown-${index}`]);
    if(!grouped.has(key))grouped.set(key,{...row,group_key:key,qty_pcs:0,location_count:0,lot_count:0,nearest_expiry:'',lots:[],_locations:new Set()});
    const group=grouped.get(key),pcs=inventoryPcs(row);
    group.qty_pcs+=pcs;group.lot_count++;
    group.lots.push({...row,lot_key:JSON.stringify([branch,row.id??index,index])});
    if(pcs>0){
      if(row.location)group._locations.add(row.location);
      const day=inventoryDate(row.expiry_date);
      if(day&&(!group.nearest_expiry||day<group.nearest_expiry))group.nearest_expiry=day;
    }
  });
  return [...grouped.values()].map(({_locations,...group})=>({...group,location_count:_locations.size,uom_label:inventoryUom(group,group.qty_pcs)}));
}
