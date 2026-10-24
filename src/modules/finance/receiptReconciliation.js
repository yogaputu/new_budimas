import { cents } from './receiptAllocation.js';

function withFees(row) {
  const real = cents(row.total_real), claim = cents(row.total_claim), fee = cents(row.other?.FEE);
  return { ...row, total_reconciled:(real+fee)/100, cash_difference:(real-claim)/100,
    difference:(real+fee-claim)/100, matched:real+fee===claim };
}

// Read-only projection also supports stored snapshots from before the fee fix.
// Actual bank/cash, allocations, balances and stored snapshots are never changed.
export function receiptReconciliationView(value) {
  if (!value?.summary) return value;
  const invoices = (value.invoices || []).map(withFees);
  let summary = withFees(value.summary);
  if (invoices.length) {
    summary = { ...summary, matched:invoices.every(row=>row.matched) };
    for (const key of ['total_reconciled','cash_difference','difference']) {
      summary[key] = Math.round(invoices.reduce((total,row)=>total+Math.round(row[key]*100),0))/100;
    }
  }
  return { ...value, invoices, summary };
}
