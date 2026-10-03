export const MAX_DRAFT_NOTES = 100;

export function draftOrderId(row) {
  return String(row?.id_sales_order || row?.sales_order_id || row?.id || '');
}

export function draftEligibilityError(row) {
  if (!/^[1-9]\d*$/.test(draftOrderId(row))) return 'ID nota tidak valid.';
  if (row?.status_order == null || Number(row.status_order) !== 1) return 'Hanya nota terkonfirmasi (RL / Booked) yang bisa dipilih.';
  if (row?.id_armada || row?.delivering_date) return 'Nota sudah memiliki jadwal pengiriman.';
  if (!row?.id_perusahaan || !row?.id_cabang || !row?.id_rute) return 'Perusahaan, cabang, atau rute customer belum lengkap.';
  return '';
}

export function draftSelectionError(rows) {
  if (!rows.length) return 'Centang minimal satu nota.';
  if (rows.length > MAX_DRAFT_NOTES) return `Maksimal ${MAX_DRAFT_NOTES} nota per draf.`;
  if (new Set(rows.map(draftOrderId)).size !== rows.length) return 'Ada nota yang dipilih dua kali.';
  for (const row of rows) {
    const error = draftEligibilityError(row);
    if (error) return error;
  }
  if (rows.some(row => ['id_perusahaan', 'id_cabang', 'id_rute'].some(key => String(row[key]) !== String(rows[0][key])))) {
    return 'Pilih nota dari perusahaan, cabang, dan rute yang sama untuk satu draf kiriman.';
  }
  return '';
}

export function notaDateRangeError(from, to) {
  for (const value of [from, to].filter(Boolean)) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || Number.isNaN(Date.parse(value)) || new Date(value).toISOString().slice(0, 10) !== value) {
      return 'Tanggal nota harus berupa tanggal yang valid.';
    }
  }
  return from && to && from > to ? 'Tanggal nota awal tidak boleh melewati tanggal akhir.' : '';
}
