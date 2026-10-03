import { getLoginBranchId, getRowBranchIds, getRowCompanyIds, isSuperUser, scopeRowsByLoginBranch } from '@/utils/accessScope';

export function getPromoFallbackBranchId(authStore) {
  return getLoginBranchId(authStore?.user);
}

export function canAccessAllPromoBranches(authStore) {
  return isSuperUser(authStore);
}

export function getPromoBranchOptions(branchRows, authStore) {
  return scopeRowsByLoginBranch(branchRows, authStore).map((item) => ({
    value: String(item.id),
    label: `${item.kode || '-'} - ${item.nama || item.nama_cabang || 'Cabang'}`
  }));
}

export function getPromoCompanyIdsForBranch(branchId, branchRows, companyRows) {
  if (!branchId) return [];

  const ids = new Set();
  const branch = branchRows.find((item) => String(item.id) === String(branchId));
  getRowCompanyIds(branch).forEach((companyId) => ids.add(String(companyId)));

  companyRows.forEach((item) => {
    if (getRowBranchIds(item).some((id) => String(id) === String(branchId))) {
      ids.add(String(item.id));
    }
  });

  return [...ids];
}

export function getPromoCompanyOptions(companyRows, branchRows, branchId) {
  const allowedCompanyIds = getPromoCompanyIdsForBranch(branchId, branchRows, companyRows);
  return companyRows
    .filter((item) => allowedCompanyIds.includes(String(item.id)))
    .map((item) => ({
      value: String(item.id),
      label: item.nama || item.nama_perusahaan || `Perusahaan ${item.id}`
    }));
}

export function getPromoPrincipalOptions(principalRows, companyId) {
  return principalRows
    .filter((item) => companyId && String(item.id_perusahaan || item.company_id || '') === String(companyId))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || item.id} | ${item.nama || item.nama_principal || 'Principal'}`
    }));
}
