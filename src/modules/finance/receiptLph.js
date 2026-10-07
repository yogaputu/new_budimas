// Eligibility comes from the API's finalized ledger, not historical LPH totals.
export function eligibleReceiptLphs(rows = []) {
  return rows.filter(row => row.status_dokumen === 'DIKEMBALIKAN' && Number(row.eligible_invoice_count) > 0);
}

export function receiptSalesOptions(rows = []) {
  const sales = new Map();
  for (const row of eligibleReceiptLphs(rows)) {
    if (!row.id_sales) continue;
    const id = String(row.id_sales);
    const option = sales.get(id) || { value:id, name:row.nama_sales || `Sales ${id}`, count:0 };
    option.count += 1;
    sales.set(id, option);
  }
  return [...sales.values()].sort((a,b) => a.name.localeCompare(b.name, 'id'))
    .map(option => ({ value:option.value, label:`${option.name} — ${option.count} LPH tersedia` }));
}

export function receiptLphOptions(rows = [], salesId = '', editLphId = '') {
  // Historical documents keep their original LPH even after it is closed.
  if (editLphId) return rows.filter(row => String(row.id) === String(editLphId));
  return eligibleReceiptLphs(rows).filter(row => !salesId || String(row.id_sales) === String(salesId));
}

export function receiptInvoices(lph, editing = false) {
  if (!lph || (!editing && lph.status_dokumen !== 'DIKEMBALIKAN')) return [];
  return (lph.invoices || []).filter(invoice => Number(invoice.remaining) > 0 && !invoice.held_by_receipt_id);
}
