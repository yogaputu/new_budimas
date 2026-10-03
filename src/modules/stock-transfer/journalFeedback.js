export function transferJournalWarning(payload = {}) {
  const warnings = Array.isArray(payload?.warnings)
    ? [...new Set(payload.warnings.filter((value) => typeof value === 'string' && value.trim()))]
    : [];
  if (warnings.length) return warnings.join(' ');
  if (['not_configured', 'partially_created'].includes(payload?.journal_status)) {
    return 'Jurnal belum terbentuk sepenuhnya. Hubungi tim Finance untuk memeriksa Jurnal Setting dan menindaklanjuti pencatatan jurnal.';
  }
  return '';
}
