import {
  branchMatchesCompany,
  getLoginCompanyIds,
  getRowCompanyIds,
  isSuperUser,
  scopeRowsByLoginBranch
} from '@/utils/accessScope';

export function normalizeFilterIds(value) {
  if (Array.isArray(value)) return value.map((item) => String(item || '').trim()).filter(Boolean);
  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function getOptionId(item, keys = ['id']) {
  const key = keys.find((name) => item?.[name] !== undefined && item?.[name] !== null && item?.[name] !== '');
  return key ? String(item[key]) : '';
}

export function formatBranchOption(item) {
  const id = getOptionId(item, ['id', 'id_cabang', 'cabang_id', 'branch_id']);
  return {
    value: id,
    label: `${item?.kode || item?.kode_cabang || id || '-'} - ${item?.nama || item?.nama_cabang || 'Cabang'}`
  };
}

export function formatCompanyOption(item) {
  const id = getOptionId(item, ['id', 'id_perusahaan', 'company_id', 'perusahaan_id', 'id_company']);
  return {
    value: id,
    label: `${item?.kode || item?.kode_perusahaan || id || '-'} - ${item?.nama || item?.nama_perusahaan || 'Perusahaan'}`
  };
}

export function getScopedCompanyRows(companyRows = [], authStore) {
  const loginCompanyIds = getLoginCompanyIds(authStore?.user).map(String);

  if (isSuperUser(authStore) || !loginCompanyIds.length) {
    return companyRows;
  }

  return companyRows.filter((item) => loginCompanyIds.includes(formatCompanyOption(item).value));
}

export function getCompanyOptionsForScope(companyRows = [], authStore, includeAll = false) {
  const options = getScopedCompanyRows(companyRows, authStore).map(formatCompanyOption).filter((item) => item.value);
  return includeAll ? [{ value: '', label: 'Semua perusahaan' }, ...options] : options;
}

function branchBelongsToCompany(branch, companyId = '', companyRows = []) {
  if (!companyId) return true;
  if (branchMatchesCompany(branch, companyId)) return true;

  const branchId = formatBranchOption(branch).value;
  if (!branchId) return false;

  const company = companyRows.find((item) => formatCompanyOption(item).value === String(companyId));
  return normalizeFilterIds(company?.id_cabang_list || company?.cabang_ids || company?.branch_ids || company?.id_cabang)
    .includes(branchId);
}

export function getBranchOptionsForCompany(branchRows = [], authStore, companyId = '', includeAll = false, companyRows = []) {
  const companyIds = normalizeFilterIds(companyId);
  const options = scopeRowsByLoginBranch(branchRows, authStore)
    .filter((item) => !companyIds.length || companyIds.some((id) => branchBelongsToCompany(item, id, companyRows)))
    .map(formatBranchOption)
    .filter((item) => item.value);

  return includeAll ? [{ value: '', label: 'Semua cabang' }, ...options] : options;
}

export function getCompanyIdsForBranch(branchId, branchRows = [], companyRows = []) {
  if (!branchId) return [];

  const ids = new Set();
  const branch = branchRows.find((item) => String(item.id) === String(branchId));
  getRowCompanyIds(branch).forEach((id) => ids.add(String(id)));

  companyRows.forEach((item) => {
    const branchIds = normalizeFilterIds(item?.id_cabang_list || item?.cabang_ids || item?.branch_ids || item?.id_cabang);
    if (branchIds.includes(String(branchId))) ids.add(formatCompanyOption(item).value);
  });

  return Array.from(ids);
}

export function resetBranchWhenCompanyChanges(target, companyKey = 'companyId', branchKey = 'branchId', branchRows = [], authStore, companyRows = []) {
  const branchId = target?.[branchKey];
  const companyIds = normalizeFilterIds(target?.[companyKey]);
  if (!branchId || !companyIds.length) return false;

  const branch = scopeRowsByLoginBranch(branchRows, authStore).find((item) => formatBranchOption(item).value === String(branchId));
  const matches = companyIds.some((companyId) => branchBelongsToCompany(branch, companyId, companyRows));
  if (matches) return false;

  target[branchKey] = '';
  return true;
}
