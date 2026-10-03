// Company choices belong to the transfer, even when both companies share a branch.
export function transferCompanyIds(row = {}) {
  const endpointIds = [row.id_perusahaan_awal, row.id_perusahaan_tujuan, row.id_perusahaan_transfer]
    .filter((value) => value !== null && value !== undefined && value !== '').map(String);
  return [...new Set(endpointIds.length ? endpointIds : [row.id_perusahaan || row.company_id || row.perusahaan_id].filter(Boolean).map(String))];
}

export function transferCompanyLabel(row = {}) {
  const origin = row.nama_perusahaan_awal || row.nama_perusahaan_transfer;
  const destination = row.nama_perusahaan_tujuan;
  if (origin && destination && origin !== destination) return `${origin} → ${destination}`;
  return origin || destination || row.nama_perusahaan || '-';
}

export function principalBelongsToTransferCompany(principal = {}, companyId) {
  return !!companyId && String(principal.id_perusahaan || principal.perusahaan_id || '') === String(companyId);
}
