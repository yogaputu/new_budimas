const validId = value => /^[1-9]\d*$/.test(String(value ?? ''));

export function canDecideEmployeeAdvance(row, user, allowed) {
  const actor = user?.id_user || user?.id || user?.user_id;
  return Boolean(allowed && row?.status === 'PENDING' && validId(actor)
    && validId(row.created_by) && validId(row.id_karyawan)
    && String(actor) !== String(row.created_by) && String(actor) !== String(row.id_karyawan)
    && row.can_approve !== false);
}

function validDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

export function validateEmployeeAdvance(form, employees) {
  if (![form.id_perusahaan, form.id_cabang, form.id_karyawan].every(validId)) return 'Pilih perusahaan, cabang, dan karyawan.';
  if (!employees.some(row => String(row.id) === String(form.id_karyawan))) return 'Pilih karyawan dari daftar perusahaan dan cabang yang aktif.';
  if (!validDate(form.tanggal_pengajuan)) return 'Tanggal pengajuan tidak valid.';
  if (form.tanggal_jatuh_tempo && (!validDate(form.tanggal_jatuh_tempo) || form.tanggal_jatuh_tempo < form.tanggal_pengajuan)) return 'Jatuh tempo harus valid dan tidak boleh sebelum tanggal pengajuan.';
  if (!/^\d+(\.\d{1,2})?$/.test(String(form.nominal)) || Number(form.nominal) <= 0 || Number(form.nominal) > 9999999999999.99) return 'Nominal harus positif, maksimal 9.999.999.999.999,99, dengan paling banyak dua angka desimal.';
  if (!form.keperluan?.trim() || form.keperluan.trim().length > 2000) return 'Keperluan wajib diisi, maksimal 2.000 karakter.';
  return '';
}
