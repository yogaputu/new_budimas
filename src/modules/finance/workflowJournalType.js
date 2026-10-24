export function workflowJournalType(row) {
  const ref=String(row.reference || '');
  if(ref.startsWith('sales:receipt-return:'))return 'Pemakaian CN / Retur';
  if(ref.startsWith('sales:receipt:'))return 'Pelunasan SO';
  if(ref.startsWith('sales:cancel-return:'))return 'Pembatalan CN / Retur';
  if(ref.startsWith('sales:cancel:'))return 'Pembatalan Pembayaran SO';
  if(ref.startsWith('FUND:')&&row.fund_kind==='TRANSFER')return row.fund_transaction_type==='CREDIT'?'Mutasi Bank Keluar':'Mutasi Bank Masuk';
  return {FUND:'Penerimaan Setoran',RECEIPT:'Penerimaan Pembayaran',CLEAR:'Pencairan Giro',BOUNCE:'Giro Ditolak',CANCEL:'Pembatalan Pembayaran'}[ref.split(':')[0]] || 'Koreksi Setoran';
}
