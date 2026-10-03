import { navigationSections } from './navigation';

export const permissionActions = [
  { key: 'view', label: 'Lihat' },
  { key: 'create', label: 'Tambah' },
  { key: 'update', label: 'Edit' },
  { key: 'delete', label: 'Hapus' },
  { key: 'approve', label: 'Approve' },
  { key: 'print', label: 'Cetak' },
  { key: 'export', label: 'Export' }
];

function titleCase(value = '') {
  return String(value)
    .replace(/[-_.]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function resolveBaseCode(permission) {
  if (!permission) return '';
  return permission.endsWith('.view') ? permission.slice(0, -5) : permission;
}

function resolveModuleName(sectionTitle, permission) {
  if (sectionTitle && sectionTitle !== 'Overview') return sectionTitle;
  const moduleCode = String(permission || '').split('.')[0] || sectionTitle || 'General';
  return titleCase(moduleCode);
}

export function buildPermissionDefinitions() {
  const resources = [];

  navigationSections.forEach((section) => {
    collectPermissionItems(section, section.items, resources);
  });

  return resources.map((resource) => ({
    ...resource,
    permissions: resource.actions.map((action) => ({
      action,
      code: `${resource.baseCode}.${action}`,
      label: permissionActions.find((item) => item.key === action)?.label || titleCase(action)
    }))
  }));
}

export const rolePermissionDefinitions = buildPermissionDefinitions();

function collectPermissionItems(section, items = [], resources = []) {
  items.forEach((item) => {
    if (item.menuPermission) {
      const baseCode = resolveBaseCode(item.menuPermission);

      resources.push({
        module: resolveModuleName(section.title, item.permission),
        label: item.label,
        baseCode,
        actions: section.title === 'Overview' ? ['view'] : permissionActions.map((action) => action.key),
        legacyPermission: item.permission || null
      });
    }

    if (Array.isArray(item.children) && item.children.length) {
      collectPermissionItems(section, item.children, resources);
    }
  });
}
