// Integer cents keep form previews consistent with the Decimal-based API.
export function cents(value) {
  const text = String(value ?? '0');
  if (!/^\d+(\.\d{1,2})?$/.test(text)) return 0;
  const [whole, fraction = ''] = text.split('.');
  const result = Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
  return Number.isSafeInteger(result) ? result : 0;
}
export function claimsFor(invoiceId, claims = []) {
  const result = { CASH:0, TRANSFER:0, GIRO:0 };
  for (const c of claims) if (String(c.id_faktur) === String(invoiceId) && c.method in result) result[c.method] += cents(c.amount);
  return result;
}
export function sourceMatchesInvoice(source, invoice, lph) {
  return Number(source.remaining)>0 &&
    String(source.id_perusahaan)===String(lph?.id_perusahaan) &&
    String(source.id_cabang)===String(lph?.id_cabang) &&
    (!source.id_customer || String(source.id_customer)===String(invoice.id_customer)) &&
    (source.kind!=='CASH' || !source.id_sales || String(source.id_sales)===String(lph?.id_sales));
}
export function initialAllocationAmount(invoice, source, invoices, funds, claims) {
  return Math.min(allocationLimit(invoice, source, invoices, funds, claims), remainingAfterChoices(invoice));
}
export function allocationLimit(invoice, source, invoices, funds, claims) {
  let available = cents(source.remaining);
  const methods = { CASH:0, TRANSFER:0, GIRO:0 };
  for (const row of invoices.filter(i => i.selected)) for (const allocation of row.sources || []) {
    const sameSource = String(allocation.id_source) === String(source.id);
    const sameInvoice = String(row.id) === String(invoice.id);
    if (sameSource && !sameInvoice) available -= cents(allocation.amount);
    if (sameInvoice && !sameSource) {
      const kind = funds.find(f => String(f.id) === String(allocation.id_source))?.kind;
      if (kind in methods) methods[kind] += cents(allocation.amount);
    }
  }
  const claim = claimsFor(invoice.id, claims);
  let cap = available;
  if (source.kind === 'GIRO') cap = Math.min(cap, claim.GIRO - methods.GIRO);
  if (['CASH','TRANSFER'].includes(source.kind)) cap = Math.min(cap, claim.CASH + claim.TRANSFER - methods.CASH - methods.TRANSFER);
  if (source.kind === 'CASH') cap = Math.min(cap, claim.CASH - methods.CASH);
  return Math.max(0, cap) / 100;
}
export function remainingAfterChoices(invoice) {
  const used = [...(invoice.sources || []), ...(invoice.fees || [])].reduce((n,a) => n + cents(a.amount),cents(invoice.legacy_fee?.amount));
  return Math.max(0,cents(invoice.remaining)-used) / 100;
}
export function receiptPayload(form) {
  return { id_lph:form.id_lph, number:form.number, receipt_date:form.receipt_date,
    client_key:form.client_key, edit_id:form.edit_id,
    invoices:(form.invoices || []).filter(i => i.selected).map(i => ({ id_faktur:i.id,
      sources:i.sources.map(a => ({ id_source:a.id_source, amount:a.amount })),
      fees:i.fees.map(f => ({ id_fee_type:f.id_fee_type, amount:f.amount })),
      ...(i.legacy_fee ? {fee:i.legacy_fee.amount,fee_name:i.legacy_fee.name} : {}),
      excess_treatment:i.excess_treatment })) };
}
export function workflowDate(value) {
  if (!value) return '';
  const text=String(value);
  if (/^\d{4}-\d{2}-\d{2}/.test(text)) return text.slice(0,10);
  const parsed=new Date(value);
  return Number.isNaN(parsed.getTime()) ? '' : parsed.toISOString().slice(0,10);
}
