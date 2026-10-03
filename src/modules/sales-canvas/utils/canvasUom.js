function toFiniteNumber(value, fallback = 0) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

export function toCanvasInteger(value) {
  return Math.max(0, Math.trunc(toFiniteNumber(value)));
}

export function canvasUomName(item, level) {
  const name = String(item?.[`uom${level}_nama`] ?? '').trim();
  if (name) return name;
  return level === 1 ? 'PCS' : '';
}

export function canvasUomFactor(item, level) {
  const configured = toFiniteNumber(item?.[`uom${level}_factor`]);
  if (configured > 0) return configured;

  // PCS adalah satuan dasar legacy Canvas. Level 2 dan 3 tidak boleh diberi
  // fallback agar field-nya tetap terkunci ketika tidak ada di master produk.
  return level === 1 ? 1 : 0;
}

export function isCanvasUomEnabled(item, level) {
  if (![1, 2, 3].includes(Number(level))) return false;
  if (canvasUomFactor(item, level) <= 0) return false;
  return level === 1 || Boolean(canvasUomName(item, level));
}

export function formatCanvasUomLabel(item, level) {
  if (!isCanvasUomEnabled(item, level)) return 'Tidak tersedia';
  const name = canvasUomName(item, level);
  const factor = canvasUomFactor(item, level);
  return level === 1 ? name : `${name} x ${factor.toLocaleString('id-ID')}`;
}

export function canvasUomValue(item, level, value) {
  return isCanvasUomEnabled(item, level) ? toCanvasInteger(value) : 0;
}

export function canvasPieces(item, qtyUom1 = 0, qtyUom2 = 0, qtyUom3 = 0) {
  return (
    canvasUomValue(item, 1, qtyUom1) * canvasUomFactor(item, 1) +
    canvasUomValue(item, 2, qtyUom2) * canvasUomFactor(item, 2) +
    canvasUomValue(item, 3, qtyUom3) * canvasUomFactor(item, 3)
  );
}

export function normalizeCanvasUomValues(item, values = {}) {
  return {
    qty_uom1: canvasUomValue(item, 1, values.qty_uom1),
    qty_uom2: canvasUomValue(item, 2, values.qty_uom2),
    qty_uom3: canvasUomValue(item, 3, values.qty_uom3)
  };
}

export function distributeCanvasPieces(item, pieces) {
  let remaining = toCanvasInteger(pieces);
  const result = { qty_uom1: 0, qty_uom2: 0, qty_uom3: 0 };

  [3, 2, 1].forEach((level) => {
    if (!isCanvasUomEnabled(item, level)) return;
    const factor = canvasUomFactor(item, level);
    result[`qty_uom${level}`] = Math.floor(remaining / factor);
    remaining -= result[`qty_uom${level}`] * factor;
  });

  return result;
}

export function formatCanvasQty(item, values = {}, { includeZero = false, separator = ' / ' } = {}) {
  const entries = [3, 2, 1]
    .filter((level) => isCanvasUomEnabled(item, level))
    .map((level) => ({
      level,
      qty: canvasUomValue(item, level, values[`qty_uom${level}`]),
      name: canvasUomName(item, level)
    }))
    .filter((entry) => includeZero || entry.qty > 0)
    .map((entry) => `${entry.qty.toLocaleString('id-ID')} ${entry.name}`);

  return entries.length ? entries.join(separator) : '0 PCS';
}
