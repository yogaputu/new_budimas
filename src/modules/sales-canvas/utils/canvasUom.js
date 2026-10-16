import { productUoms, productUom, productUomLabel, productUomTotal, productUomQuantities, distributeProductUom, uomQuantity } from '../../../utils/productUom.js';

export const toCanvasInteger = uomQuantity;
export const canvasUoms = productUoms;
export const canvasUomName = (item, level) => productUom(item, level)?.nama || '';
export const canvasUomFactor = (item, level) => productUom(item, level)?.faktor_konversi || 0;
export const isCanvasUomEnabled = (item, level) => Boolean(productUom(item, level));
export const formatCanvasUomLabel = productUomLabel;
export const canvasUomValue = (item, level, value) => isCanvasUomEnabled(item, level) ? uomQuantity(value) : 0;
export function canvasPieces(item, values = item, qtyUom2 = 0, qtyUom3 = 0) {
  const quantities = typeof values === 'object' ? values : { ...item, qty_uom1: values, qty_uom2: qtyUom2, qty_uom3: qtyUom3 };
  return productUomTotal(item, quantities, 'qty_uom');
}
export function normalizeCanvasUomValues(item, values = {}) {
  const result = Object.fromEntries(productUoms(item).map(unit => [`qty_uom${unit.level}`, uomQuantity(values[`qty_uom${unit.level}`])]));
  return { ...result, uom_quantities: productUomQuantities(item, result, 'qty_uom') };
}
export const distributeCanvasPieces = (item, pieces) => distributeProductUom(item, pieces, 'qty_uom');
export function formatCanvasQty(item, values = {}, { includeZero = false, separator = ' / ' } = {}) {
  const entries = productUoms(item).sort((a,b) => b.level-a.level)
    .filter(unit => includeZero || uomQuantity(values[`qty_uom${unit.level}`]) > 0)
    .map(unit => `${uomQuantity(values[`qty_uom${unit.level}`]).toLocaleString('id-ID')} ${unit.nama}`);
  return entries.join(separator) || '0';
}
