import { getLoginBranchId, getLoginCompanyId, getRowBranchIds, getRowCompanyIds, isSuperUser } from '@/utils/accessScope';
import { getBranchOptionsForCompany, getCompanyOptionsForScope } from '@/utils/filterScope';

export function getPurchaseFallbackBranchId(authStore) {
  return getLoginBranchId(authStore?.user);
}

export function getPurchaseFallbackCompanyId(authStore) {
  return getLoginCompanyId(authStore?.user);
}

export function canAccessAllPurchaseBranches(authStore) {
  return isSuperUser(authStore);
}

export function getPurchaseBranchOptions(branchRows, authStore, companyId = '', companyRows = []) {
  return getBranchOptionsForCompany(branchRows, authStore, companyId, false, companyRows);
}

export function getPurchaseCompanyIdsForBranch(branchId, branchRows, companyRows) {
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

export function getPurchaseCompanyOptions(companyRows, branchRows, branchId, authStore = null) {
  return getCompanyOptionsForScope(companyRows, authStore);
}

export function getPurchasePrincipalOptions(principalRows, companyId) {
  return principalRows
    .filter((item) => !companyId || String(item.id_perusahaan || item.company_id || '') === String(companyId))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || '-'} - ${item.nama || item.principal_nama || 'Principal'}`
    }));
}
