import {
  branchMatchesCompany,
  getLoginCompanyIds,
  getRowBranchIds,
  getRowCompanyId,
  getRowCompanyIds,
  isSuperUser,
  scopeRowsByLoginBranch
} from '@/utils/accessScope';

function getOptionId(item, keys = ['id']) {
  const key = keys.find((name) => item?.[name] !== undefined && item?.[name] !== null && item?.[name] !== '');
  return key ? String(item[key]) : '';
}

function formatCompanyOption(item) {
  const id = getOptionId(item, ['id', 'id_perusahaan', 'company_id', 'perusahaan_id', 'id_company']);
  return {
    value: id,
    label: `${item.kode || item.kode_perusahaan || id || '-'} - ${item.nama || item.nama_perusahaan || 'Perusahaan'}`
  };
}

function formatBranchOption(item) {
  const id = getOptionId(item, ['id', 'id_cabang', 'cabang_id', 'branch_id']);
  return {
    value: id,
    label: `${item.kode || item.kode_cabang || id || '-'} - ${item.nama || item.nama_cabang || 'Cabang'}`
  };
}

function getScopedCompanyRows(companies = [], branches = [], authStore) {
  if (!authStore || isSuperUser(authStore)) {
    return companies;
  }

  const loginCompanyIds = getLoginCompanyIds(authStore.user).map(String);
  const scopedBranches = scopeRowsByLoginBranch(branches, authStore);
  const scopedBranchIds = new Set(scopedBranches.map((item) => getOptionId(item, ['id', 'id_cabang', 'cabang_id', 'branch_id'])).filter(Boolean));
  const scopedCompanyIds = new Set(scopedBranches.flatMap((item) => getRowCompanyIds(item).map(String)).filter(Boolean));

  return companies.filter((item) => {
    const companyId = formatCompanyOption(item).value;
    if (loginCompanyIds.includes(companyId) || scopedCompanyIds.has(companyId)) return true;
    const companyBranchIds = getRowBranchIds(item).map(String);
    return companyBranchIds.some((id) => scopedBranchIds.has(id));
  });
}

function branchBelongsToCompany(branch, companyId = '', companies = []) {
  if (!companyId) return true;
  if (branchMatchesCompany(branch, companyId)) return true;

  const branchId = formatBranchOption(branch).value;
  if (!branchId) return false;

  const company = companies.find((item) => formatCompanyOption(item).value === String(companyId));
  return getRowBranchIds(company).includes(branchId);
}

export function getSupervisorCompanyIdsForBranch(branchId, branches = [], companies = []) {
  if (!branchId) return [];

  const ids = new Set();
  const branch = branches.find((item) => formatBranchOption(item).value === String(branchId));
  getRowCompanyIds(branch).forEach((id) => ids.add(String(id)));

  companies.forEach((item) => {
    if (getRowBranchIds(item).includes(String(branchId))) {
      ids.add(formatCompanyOption(item).value);
    }
  });

  return Array.from(ids);
}

export function getSupervisorCompanyOptions(companies = [], branches = [], _branchId = '', authStore = null, includeAll = false) {
  const options = getScopedCompanyRows(companies, branches, authStore)
    .map(formatCompanyOption)
    .filter((item) => item.value);

  return includeAll ? [{ value: '', label: 'Semua perusahaan' }, ...options] : options;
}

export function getSupervisorBranchOptions(branches = [], authStore, includeAll = false, companyId = '', companies = []) {
  const options = scopeRowsByLoginBranch(branches, authStore)
    .filter((item) => branchBelongsToCompany(item, companyId, companies))
    .map(formatBranchOption)
    .filter((item) => item.value);

  return includeAll ? [{ value: '', label: 'Semua cabang' }, ...options] : options;
}

export function getSupervisorPrincipalOptions(principals = [], companyId, includeAll = false) {
  const options = principals
    .filter((item) => companyId && String(item.id_perusahaan || item.company_id || '') === String(companyId))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || item.id || '-'} | ${item.nama || item.nama_principal || 'Principal'}`
    }));

  return includeAll ? [{ value: '', label: 'Semua principal' }, ...options] : options;
}

export function syncSupervisorCompanyFromBranch(target, branchKey, companyKey, branches = [], companies = []) {
  const branchId = target[branchKey];
  const allowedIds = getSupervisorCompanyIdsForBranch(branchId, branches, companies);

  if (!branchId || !allowedIds.length) {
    target[companyKey] = '';
    return false;
  }

  if (!allowedIds.includes(String(target[companyKey] || ''))) {
    target[companyKey] = allowedIds.length === 1 ? allowedIds[0] : '';
    return true;
  }

  return false;
}

export function resetSupervisorBranchWhenCompanyChanges(target, companyKey, branchKey, branches = [], authStore, companies = []) {
  const branchId = String(target?.[branchKey] || '');
  const companyId = String(target?.[companyKey] || '');
  if (!branchId || !companyId) return false;

  const branch = scopeRowsByLoginBranch(branches, authStore)
    .find((item) => formatBranchOption(item).value === branchId);

  if (branch && branchBelongsToCompany(branch, companyId, companies)) return false;

  target[branchKey] = '';
  return true;
}
