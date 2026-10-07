export const returStatusOptions = [
  { value: '0', label: 'Menunggu Approval' },
  { value: '1', label: 'KPR Terbit' },
  { value: '2', label: 'Proses QC' },
  { value: '4', label: 'Menunggu CN' },
  { value: '3', label: 'CN Terbit' },
  { value: '9', label: 'Batal' },
];
export function returStatusLabel(row) {
  return returStatusOptions.find(s => s.value === String(row?.status_request))?.label || row?.status_request_label || '-';
}
