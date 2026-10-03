const ROLE_GROUPS = {
  adminIt: ['admin it', 'adminit', 'adminit1', 'super admin', 'superadmin', 'super user', 'superuser'],
  finance: ['finance', 'accounting', 'kasir', 'ap', 'ar'],
  purchase: ['purchase', 'purchasing', 'pembelian'],
  warehouse: ['warehouse', 'gudang', 'checker', 'logistik'],
  salesSupervisor: ['sales supervisor', 'supervisor sales', 'spv sales', 'kepala sales']
};

const ROLE_PERMISSION_PREFIXES = {
  finance: ['finance.', 'purchase.bills.', 'workflow.', 'm.finance.', 'm.workflow-center.'],
  purchase: ['purchase.', 'workflow.', 'm.purchase.', 'm.workflow-center.'],
  warehouse: [
    'stock-transfer.',
    'stock-transfer_',
    'stock-opname.',
    'stock_opname.',
    'wms.',
    'distribution.picking.',
    'distribution.schedules.',
    'workflow.',
    'm.operasional.',
    'm.distribusi.',
    'm.workflow-center.'
  ],
  salesSupervisor: ['supervisor-sales.', 'sales-order.', 'sales-canvas.', 'promo.', 'workflow.', 'm.supervisor-sales.', 'm.promo.', 'm.workflow-center.']
};

const ROLE_PERMISSION_CODES = {
  finance: ['dashboard.view', 'm.overview.db.view', 'm.overview.pr.view', 'purchase.bills.view'],
  purchase: ['dashboard.view', 'm.overview.db.view', 'm.overview.pr.view'],
  warehouse: [
    'dashboard.view',
    'm.overview.db.view',
    'm.overview.pr.view',
    'wms.view',
    'distribution.picking.view',
    'distribution.schedules.view'
  ],
  salesSupervisor: ['dashboard.view', 'm.overview.db.view', 'm.overview.pr.view', 'distribution.orders.view']
};

const PERMISSION_ALIASES = {
  'purchase.orders': ['distribution.orders'],
  'purchase.branch-requests': ['distribution.orders'],
  'purchase.order-confirmations': ['distribution.orders'],
  'purchase.receipts': ['distribution.orders'],
  'purchase.confirmations': ['distribution.orders'],
  'purchase.bills': ['distribution.orders'],
  'wms': ['stock-transfer', 'stock_opname', 'stock-opname', 'distribution.picking'],
  'supervisor-sales.dashboard': ['distribution.orders'],
  'supervisor-sales.visits': ['distribution.orders'],
  'supervisor-sales.callplan': ['distribution.orders'],
  'supervisor-sales.stock-opname-monitor': ['distribution.orders'],
  'supervisor-sales.targets': ['distribution.orders'],
  'supervisor-sales.retur': ['distribution.orders'],
  'supervisor-sales.attendance': ['distribution.orders'],
  'supervisor-sales.kasbon': ['distribution.orders'],
  'supervisor-sales.doi': ['distribution.orders'],
  'supervisor-sales.audit': ['distribution.orders']
};

function normalize(value = '') {
  return String(value)
    .toLowerCase()
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

export function roleText(authStore) {
  const user = authStore?.user || {};
  return [
    user.username,
    user.email,
    user.nama,
    user.nama_jabatan,
    user.role_code,
    user.jabatan?.nama,
    user.jabatan?.scope,
    authStore?.roleLabel,
    authStore?.roleScope
  ]
    .filter(Boolean)
    .map(normalize)
    .join(' ');
}

export function hasRoleGroup(authStore, group) {
  const text = roleText(authStore);
  return (ROLE_GROUPS[group] || []).some((keyword) => text.includes(keyword));
}

export function isAdminIt(authStore) {
  return authStore?.permissions?.includes('*') || hasRoleGroup(authStore, 'adminIt');
}

export function allowedRoleGroups(authStore) {
  if (isAdminIt(authStore)) return ['adminIt', 'finance', 'purchase', 'warehouse', 'salesSupervisor'];
  return Object.keys(ROLE_GROUPS).filter((group) => group !== 'adminIt' && hasRoleGroup(authStore, group));
}

export function roleCanAccessPermission(authStore, permission) {
  if (!permission) return true;
  if (isAdminIt(authStore)) return true;

  if (Array.isArray(authStore?.permissions)) {
    return false;
  }

  const normalizedPermission = String(permission).replace(/-/g, '_');
  const baseCode = String(permission).replace(/\.(view|create|update|delete|approve|print|export)$/, '');
  const normalizedBaseCode = baseCode.replace(/-/g, '_');

  return allowedRoleGroups(authStore).some((group) => {
    const prefixes = ROLE_PERMISSION_PREFIXES[group] || [];
    const directCodes = ROLE_PERMISSION_CODES[group] || [];
    const aliases = PERMISSION_ALIASES[baseCode] || PERMISSION_ALIASES[normalizedBaseCode] || [];

    return (
      directCodes.includes(permission) ||
      directCodes.includes(normalizedPermission) ||
      prefixes.some((prefix) => permission.startsWith(prefix) || normalizedPermission.startsWith(prefix.replace(/-/g, '_'))) ||
      aliases.some((alias) => permission.startsWith(alias) || normalizedPermission.startsWith(alias.replace(/-/g, '_')))
    );
  });
}

export function canAccessRoleGroups(authStore, groups = []) {
  if (!Array.isArray(groups) || !groups.length) return true;
  if (isAdminIt(authStore)) return true;
  return groups.some((group) => hasRoleGroup(authStore, group));
}

export function isCurrentUserPic(authStore, row, extraKeys = []) {
  if (!row) return false;
  const user = authStore?.user || {};
  const userIds = [user.id, user.id_user, user.user_id].filter(Boolean).map(String);
  const userNames = [authStore?.userName, user.nama, user.username, user.email].filter(Boolean).map(normalize);
  const idKeys = ['id_user', 'user_id', 'pic_id', 'id_pic', 'created_by_id', 'id_created_by', ...extraKeys];
  const nameKeys = [
    'pic',
    'nama_pic',
    'pic_name',
    'nama_user',
    'user_name',
    'created_by',
    'requester',
    'nama_requester',
    'pic_order_nama',
    'pic_konfirmasi_nama',
    ...extraKeys
  ];

  const rowIds = idKeys.map((key) => row[key]).filter(Boolean).map(String);
  const rowNames = nameKeys.map((key) => row[key]).filter(Boolean).map(normalize);

  return rowIds.some((value) => userIds.includes(value)) || rowNames.some((value) => userNames.some((name) => value === name || value.includes(name)));
}
