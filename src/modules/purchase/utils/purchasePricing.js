// Display-only estimate. The API revalidates and calculates Decimal totals from
// saved receipt quantities/prices; no browser financial total is trusted.
export function purchasePricing(rows, form = {}, discounts = {}) {
  const cents = value => Math.round((Number(value || 0) + Number.EPSILON) * 100);
  const amount = (base, type, value, label) => {
    const n = Number(value || 0);
    if (!Number.isFinite(n) || n < 0) throw new Error(`${label} harus nol atau lebih.`);
    if (!['AMOUNT', 'PERCENT'].includes(type)) throw new Error(`Jenis ${label.toLowerCase()} tidak valid.`);
    if (type === 'PERCENT' && n > 100) throw new Error(`${label} tidak boleh melebihi 100%.`);
    const result = type === 'PERCENT' ? Math.round(base * n / 100) : cents(n);
    if (result > base) throw new Error(`${label} tidak boleh melebihi DPP yang tersedia.`);
    return result;
  };
  try {
    const lines = rows.map(row => {
      const input = discounts[row.detail_id ?? row.id] || {};
      const gross = cents(row.dpp_gross ?? row.subtotal);
      const discount = amount(gross, input.discount_type || 'AMOUNT', input.discount_value, 'Diskon produk');
      return { ...row, detail_id: Number(row.detail_id ?? row.id), gross, product: discount, base: gross - discount };
    }).sort((a, b) => a.detail_id - b.detail_id);
    const base = lines.reduce((sum, row) => sum + row.base, 0);
    const header = amount(base, form.discount_type || 'AMOUNT', form.discount_value, 'Diskon keseluruhan');
    const shares = lines.map(row => base ? header * row.base / base : 0);
    const allocation = shares.map(Math.floor);
    const remaining = header - allocation.reduce((sum, value) => sum + value, 0);
    [...lines.keys()].sort((a, b) => (shares[b] - allocation[b]) - (shares[a] - allocation[a]) || lines[a].detail_id - lines[b].detail_id)
      .slice(0, remaining).forEach(index => allocation[index]++);
    const fee = Number(form.biaya_lainnya || 0);
    if (!Number.isFinite(fee) || fee < 0) throw new Error('Biaya lainnya harus nol atau lebih.');
    lines.forEach((row, index) => {
      const net = row.base - allocation[index];
      const tax = Math.round(net * Number(row.tax_rate || 0) / 100);
      Object.assign(row, {
        dpp_gross: row.gross / 100, product_discount: row.product / 100,
        header_discount_allocated: allocation[index] / 100, dpp_net: net / 100,
        unit_dpp_net: row.quantity_pcs ? net / 100 / row.quantity_pcs : 0,
        ppn: tax / 100, total: (net + tax) / 100
      });
    });
    const sum = key => lines.reduce((total, row) => total + cents(row[key]), 0) / 100;
    const gross = sum('dpp_gross'), product = sum('product_discount'), net = sum('dpp_net'), tax = sum('ppn');
    return { lines, dpp_gross: gross, product_discount_total: product,
      header_discount_amount: header / 100, discount_total: product + header / 100,
      dpp_net: net, ppn: tax, other_cost: cents(fee) / 100, total: (cents(net) + cents(tax) + cents(fee)) / 100,
      total_pcs: lines.reduce((total, row) => total + Number(row.quantity_pcs || 0), 0), error: '' };
  } catch (error) {
    return { lines: [], error: error.message };
  }
}
