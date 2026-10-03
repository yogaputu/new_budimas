const UOM_LEVELS = [1, 2, 3];

function number(value) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function uomTotal(row) {
  return UOM_LEVELS.reduce((total, level) => total + number(row[`uom_${level}`]) * number(row[`konversi_uom_${level}`]), 0);
}

function reconcileUomCounts(row) {
  if (Math.abs(uomTotal(row) - row.stok_fisik) < 0.000001) return row;
  const levels = UOM_LEVELS.filter((level) => row[`konversi_uom_${level}`] > 0)
    .sort((left, right) => row[`konversi_uom_${right}`] - row[`konversi_uom_${left}`]);
  // Missing master data must not erase the saved physical count.
  if (!levels.length) return row;
  const result = { ...row, uom_1: 0, uom_2: 0, uom_3: 0 };
  let remainder = row.stok_fisik;
  levels.forEach((level, index) => {
    const conversion = row[`konversi_uom_${level}`];
    const quantity = index === levels.length - 1 ? remainder / conversion : Math.floor(remainder / conversion);
    result[`uom_${level}`] = quantity;
    remainder -= quantity * conversion;
  });
  return result;
}

export function normalizeStockOpnameDetail(item) {
  const physical = number(item.stok_fisik ?? item.stok ?? item.stock);
  const system = number(item.stok_sistem ?? item.stock_system);
  const price = number(item.harga ?? item.harga_produk);
  const row = {
    ...item,
    stok: physical,
    stok_fisik: physical,
    good_stock: number(item.good_stock ?? item.stok ?? item.stock),
    bad_stock: number(item.bad_stock),
    stok_sistem: system,
    harga: price,
    selisih: physical - system,
    subtotal: number(item.subtotal ?? physical * price),
    subtotal_selisih: number(item.subtotal_selisih ?? (physical - system) * price)
  };
  UOM_LEVELS.forEach((level) => {
    // Unit names and conversions come only from this product's master UOM.
    row[`label_uom_${level}`] = String(item[`label_uom_${level}`] ?? '').trim();
    row[`konversi_uom_${level}`] = Math.max(number(item[`konversi_uom_${level}`]), 0);
    row[`uom_${level}`] = number(item[`uom_${level}`]);
  });
  return reconcileUomCounts(row);
}

export function updateStockOpnameDetail(item, field, value) {
  const row = { ...item, [field]: number(value) };
  // The physical editor and UOM editor must update the same canonical value.
  // Reading the old stok_fisik after editing stok used to discard the edit.
  const physical = field.startsWith('uom_') ? uomTotal(row)
    : ['stok', 'stok_fisik'].includes(field) ? number(value) : number(row.stok_fisik);
  const result = {
    ...row,
    stok: physical,
    stok_fisik: physical,
    good_stock: Math.max(physical - number(row.bad_stock), 0),
    quantity_model: 'GOOD_BAD_V1',
    selisih: physical - row.stok_sistem,
    subtotal: physical * row.harga,
    subtotal_selisih: (physical - row.stok_sistem) * row.harga
  };
  return field.startsWith('uom_') ? result : reconcileUomCounts(result);
}

export function buildStockOpnameDetailPayload(rows) {
  return rows.map((item) => ({
    id_produk: number(item.id_produk),
    stok: number(item.stok_fisik),
    stock: number(item.stok_fisik),
    stok_fisik: number(item.stok_fisik),
    good_stock: number(item.good_stock),
    bad_stock: number(item.bad_stock),
    quantity_model: item.quantity_model || '',
    stok_sistem: number(item.stok_sistem),
    harga: number(item.harga),
    harga_produk: number(item.harga),
    uom_1: number(item.uom_1),
    uom_2: number(item.uom_2),
    uom_3: number(item.uom_3),
    subtotal: number(item.subtotal),
    subtotal_selisih: number(item.subtotal_selisih),
    keterangan: item.ket_produk || ''
  }));
}
