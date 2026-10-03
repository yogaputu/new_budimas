export const FINANCE_INVOICE_STATUS_LABELS = {
  '0': 'Draft',
  '1': 'Buka Finance',
  '2': 'Belum Lunas',
  '3': 'Lunas',
  '4': 'Dibatalkan'
};

export const FINANCE_DEPOSIT_STAGE_OPTIONS = [
  { value: '', label: 'Semua Tahap' },
  { value: '0', label: 'Draft Rekap' },
  { value: '1', label: 'Menunggu Proses Kasir' },
  { value: '2', label: 'Siap Finalisasi Finance' },
  { value: '3', label: 'Final / Selesai' }
];

export function resolveFinanceInvoiceStatusLabel(value) {
  const status = String(value ?? '');
  return FINANCE_INVOICE_STATUS_LABELS[status] || (status || '-');
}

export function resolvePaymentTypeLabel(value) {
  if (String(value) === '1') return 'Tunai';
  if (String(value) === '2') return 'Non Tunai';
  return value || '-';
}

export function resolveDepositStageLabelByCode(value, fallback = '') {
  const code = Number(value);
  if (code === 0) return 'Draft Rekap';
  if (code === 1) return 'Menunggu Proses Kasir';
  if (code === 2) return 'Siap Finalisasi Finance';
  if (code === 3) return 'Final / Selesai';
  if (fallback) return fallback;
  return '-';
}

export function resolveDepositStageLabel(item) {
  const hasValue = (value) => {
    if (Array.isArray(value)) {
      return value.some((entry) => hasValue(entry));
    }

    return value !== null && value !== undefined && String(value).trim() !== '';
  };

  if (hasValue(item?.tanggal_setoran_diterima)) {
    return 'Final / Selesai';
  }

  if (hasValue(item?.id_setoran) || hasValue(item?.status_setoran)) {
    return resolveDepositStageLabelByCode(item?.status_setoran, 'Masuk Rekap');
  }

  if (Number(item?.is_rekap || 0) === 1) {
    return 'Draft Rekap';
  }

  return 'Pembayaran Customer';
}
