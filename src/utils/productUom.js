// Master-driven product units. Conversion factors are absolute base-unit counts.
const text = value => String(value ?? '').trim();
const positive = value => Number.isFinite(Number(value)) && Number(value) > 0 ? Number(value) : 0;
export const uomQuantity = value => Number.isFinite(Number(value)) ? Math.max(0, Math.trunc(Number(value))) : 0;

export function productUoms(product = {}) {
  const row = product || {};
  const master = [row.uoms, row.uom_list, row.product_uoms, row.konversi, row.stok?.uoms, row.stok?.uom_list].find(Array.isArray);
  if (master) {
    const seen = new Set();
    return master.map(unit => {
      const level = Number(unit.level ?? unit.uom_level);
      return { ...unit, id: unit.id ?? unit.uom_id ?? unit.id_uom ?? null, level,
        nama: text(unit.nama || unit.uom_nama || unit.name || unit.label || unit.kode),
        faktor_konversi: positive(unit.faktor_konversi ?? unit.uom_faktor_konversi ?? unit.factor ?? unit.conversion_factor) };
    }).filter(unit => {
      if (!Number.isInteger(unit.level) || unit.level < 1 || !unit.nama || !unit.faktor_konversi || seen.has(unit.level)) return false;
      seen.add(unit.level); return true;
    }).sort((a, b) => a.level - b.level);
  }
  // Older API/cache payloads are supported, without inventing missing levels.
  const legacy = { ...(row.stok || {}), ...row };
  const levels = new Set([1, 2, 3]);
  Object.keys(legacy).forEach(key => {
    const match = key.match(/^(?:uom_?|Uom|puom)(\d+)(?:_|Label|_nama|_kode|_name|Label$)/);
    if (match) levels.add(Number(match[1]));
  });
  return [...levels].sort((a,b) => a-b).flatMap(level => {
    const name = text(legacy[`Uom${level}Label`] || legacy[`uom${level}Label`] || legacy[`uom${level}_label`] || legacy[`label_uom_${level}`] || legacy[`uom_${level}`] || legacy[`uom${level}_nama`] || legacy[`puom${level}_nama`] || legacy[`puom${level}_kode`] || legacy[`uom${level}_name`] || (level === 1 ? legacy.Satuan || legacy.satuan : level === 2 ? legacy.NamaUnit || legacy.nama_unit : ''));
    const factor = positive(legacy[`konversi_${level}`] ?? legacy[`Konversi${level}`] ?? legacy[`konversi${level}`] ?? legacy[`konversi_uom_${level}`] ?? legacy[`konversi_level${level}`] ?? legacy[`uom${level}_factor`] ?? (level === 1 ? 1 : 0));
    const flag = legacy[`hasUom${level}`] ?? legacy[`HasUom${level}`] ?? legacy[`has_uom_${level}`];
    return name && factor && ![false, 0, 'false', '0'].includes(flag) ? [{ id: null, level, nama: name, faktor_konversi: factor }] : [];
  });
}
export const productUom = (row, level) => productUoms(row).find(unit => unit.level === Number(level));
export const returnUomField = (level, kind) => `${({1:'pieces',2:'box',3:'karton'})[level] || 'uom' + level}_retur_${kind}`;
export const returnUomFields = (row, kind) => productUoms(row).map(unit => returnUomField(unit.level, kind));
export const returnUomQuantities = (row, kind) => productUoms(row).map(unit => ({ uom_id: unit.id, level: unit.level, quantity: uomQuantity(row[returnUomField(unit.level, kind)]) }));
export const returnUomTotal = (row, kind) => productUoms(row).reduce((sum, unit) => sum + uomQuantity(row[returnUomField(unit.level, kind)]) * unit.faktor_konversi, 0);
export function productUomLabel(row, level) {
  const unit = productUom(row, level);
  return unit ? unit.nama + (unit.faktor_konversi === 1 ? '' : ` × ${unit.faktor_konversi.toLocaleString('id-ID')}`) : '';
}
export function productUomQuantities(row, values = row, prefix = 'uom') {
  return productUoms(row).map(unit => ({ uom_id: unit.id, level: unit.level, quantity: uomQuantity(values?.[`${prefix}${unit.level}`]) }));
}
export function productUomTotal(row, values = row, prefix = 'uom') {
  return productUoms(row).reduce((sum, unit) => sum + uomQuantity(values?.[`${prefix}${unit.level}`]) * unit.faktor_konversi, 0);
}
export function formatProductUomQty(row, values = row, prefix = 'uom') {
  return productUoms(row).filter(unit => uomQuantity(values?.[`${prefix}${unit.level}`]) > 0)
    .map(unit => `${uomQuantity(values[`${prefix}${unit.level}`]).toLocaleString('id-ID')} ${unit.nama}`).join(' / ') || '0';
}
export function emptyProductUomValues(row, prefix = 'uom') {
  return Object.fromEntries(productUoms(row).map(unit => [`${prefix}${unit.level}`, 0]));
}
export function distributeProductUom(row, baseQuantity, prefix = 'uom') {
  let remaining = uomQuantity(baseQuantity);
  const result = emptyProductUomValues(row, prefix);
  for (const unit of productUoms(row).sort((a,b) => b.faktor_konversi - a.faktor_konversi || b.level - a.level)) {
    result[`${prefix}${unit.level}`] = Math.floor(remaining / unit.faktor_konversi);
    remaining -= result[`${prefix}${unit.level}`] * unit.faktor_konversi;
  }
  return result;
}
