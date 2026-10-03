import { isAdminIt } from '@/utils/roleAccess';

export function parseScopeIds(...values) {
  return values
    .flatMap((value) => {
      if (Array.isArray(value)) return value;
      return String(value || '').split(',');
    })
    .map((value) => String(value || '').trim())
    .filter(Boolean);
}

export function getLoginBranchId(user) {
  return getLoginBranchIds(user)[0] || '';
}

export function getLoginBranchIds(user) {
  return parseScopeIds(
    user?.id_cabang_list,
    user?.cabang_ids,
    user?.branch_ids,
    user?.id_cabang,
    user?.cabang_id,
    user?.cabang?.id
  );
}

export function getLoginCompanyId(user) {
  return getLoginCompanyIds(user)[0] || '';
}

export function getLoginCompanyIds(user) {
  return parseScopeIds(
    user?.id_perusahaan_list,
    user?.perusahaan_ids,
    user?.company_ids,
    user?.id_perusahaan,
    user?.company_id,
    user?.perusahaan_id,
    user?.perusahaan?.id
  );
}

export function getLoginSalesId(user) {
  return user?.id_sales || user?.sales_id || user?.sales?.id || '';
}

export function getLoginSalesUserId(user) {
  return user?.id_user || user?.id || user?.user_id || user?.sales?.id_user || '';
}

export function getSupervisedSalesRows(user) {
  return Array.isArray(user?.supervised_sales) ? user.supervised_sales : [];
}

export function hasSupervisorSalesScope(user) {
  return getSupervisedSalesRows(user).length > 0;
}

export function hasMultiBusinessScope(user) {
  return getLoginBranchIds(user).length > 1 || getLoginCompanyIds(user).length > 1;
}

export function shouldLockToLoginSales(authStore) {
  return !isSuperUser(authStore) && !hasSupervisorSalesScope(authStore?.user);
}

export function getAllowedSalesUserIds(user) {
  return getSupervisedSalesRows(user)
    .map((item) => item?.id_user || item?.user_id || item?.id)
    .filter(Boolean)
    .map((item) => String(item));
}

export function getAllowedSalesIds(user) {
  return getSupervisedSalesRows(user)
    .map((item) => item?.id_sales || item?.sales_id)
    .filter(Boolean)
    .map((item) => String(item));
}

export function getLoginPrincipalIds(user) {
  return parseScopeIds(
    user?.id_principals,
    user?.principal_ids,
    user?.sales?.id_principals,
    user?.sales?.principal_ids,
    user?.id_principal,
    user?.sales?.id_principal
  );
}

export function getRowBranchId(row) {
  return row?.id_cabang || row?.cabang_id || row?.branch_id || row?.cabang?.id || '';
}

export function getRowBranchIds(row) {
  return parseScopeIds(
    row?.id_cabang,
    row?.cabang_id,
    row?.branch_id,
    row?.cabang?.id,
    row?.id_cabang_list,
    row?.cabang_ids,
    row?.branch_ids
  );
}

export function getRowCompanyId(row) {
  return getRowCompanyIds(row)[0] || '';
}

export function getRowCompanyIds(row) {
  return parseScopeIds(
    row?.id_perusahaan,
    row?.company_id,
    row?.perusahaan_id,
    row?.id_company,
    row?.perusahaan?.id,
    row?.id_perusahaan_list,
    row?.perusahaan_ids,
    row?.company_ids
  );
}

export function getBranchCompanyIds(branch) {
  return getRowCompanyIds(branch);
}

export function getCompanyBranchIds(company) {
  return getRowBranchIds(company);
}

export function branchMatchesCompany(branch, companyId) {
  if (!companyId) return true;
  return getBranchCompanyIds(branch).includes(String(companyId));
}

export function companyMatchesBranch(company, branchId) {
  if (!branchId) return true;
  return getCompanyBranchIds(company).includes(String(branchId));
}

export function isSuperUser(authStore) {
  return isAdminIt(authStore);
}

export function scopeRowsByLoginBranch(rows, authStore) {
  const loginBranchIds = getLoginBranchIds(authStore?.user);
  const supervisedBranchIds = getSupervisedSalesRows(authStore?.user)
    .map((item) => getRowBranchId(item))
    .filter(Boolean)
    .map((item) => String(item));

  if (supervisedBranchIds.length) {
    const allowed = new Set([...loginBranchIds, ...supervisedBranchIds].filter(Boolean).map(String));
    return rows.filter((item) => getRowBranchIds(item).some((id) => allowed.has(String(id))));
  }

  if (isSuperUser(authStore) || !loginBranchIds.length) {
    return rows;
  }

  const allowed = new Set(loginBranchIds.map(String));
  return rows.filter((item) => getRowBranchIds(item).some((id) => allowed.has(String(id))));
}

export function scopeSalesRowsByLogin(rows, authStore) {
  if (isSuperUser(authStore)) {
    return rows;
  }

  const supervisedRows = getSupervisedSalesRows(authStore?.user);
  if (supervisedRows.length) {
    const allowedUserIds = new Set(getAllowedSalesUserIds(authStore.user));
    const allowedSalesIds = new Set(getAllowedSalesIds(authStore.user));

    return rows.filter((item) => {
      const rowUserId = String(item?.id_user || item?.user_id || item?.id || '');
      const rowSalesId = String(item?.id_sales || item?.sales_id || '');
      return allowedUserIds.has(rowUserId) || allowedSalesIds.has(rowSalesId);
    });
  }

  const loginUserId = String(getLoginSalesUserId(authStore?.user) || '');
  const loginSalesId = String(getLoginSalesId(authStore?.user) || '');
  if (!loginUserId && !loginSalesId) {
    return [];
  }

  return rows.filter((item) => {
    const rowUserId = String(item?.id_user || item?.user_id || item?.id || '');
    const rowSalesId = String(item?.id_sales || item?.sales_id || '');
    return (loginUserId && rowUserId === loginUserId) || (loginSalesId && rowSalesId === loginSalesId);
  });
}
