// Same menu/action bridge as API apps/lib/payment_permissions.py. No role-name bypass.
const menus = { CASH: ['stk'], TRANSFER: ['snk', 'mb'], GIRO: ['bg'] };
const aliases = {
  'finance.receipts.view': ['kw.view'],
  'finance.receipts.create': ['kw.create'],
  'finance.receipts.update': ['kw.update'],
  'finance.receipts.delete': ['kw.delete'],
  'finance.receipts.approve': ['kw.approve'],
  'finance.receipts.cancel': ['bk.create', 'kw.delete'],
  'finance.receipts.cancel-approve': ['bk.approve'],
  'finance.cancellations.view': ['bk.view', 'kw.view'],
  'finance.journals.view': ['jk.view'],
  'finance.bank-input.view': ['mb.view', 'snk.create'],
  'finance.workflow.view': ['pw.view'],
  'finance.workflow.configure': ['pw.update'],
  'finance.fees.view': ['bl.view'],
  'finance.fees.create': ['bl.create'],
  'finance.fees.update': ['bl.update'],
  'finance.fees.delete': ['bl.delete'],
  'finance.fees.manage': ['bl.create', 'bl.update'],
  'finance.giro.clear': ['bg.approve'],
  'finance.giro.bounce': ['bg.approve'],
};
export function paymentPermission(granted = [], permission, kind) {
  const managed = permission in aliases || permission.startsWith('finance.funds.') || /^m\.finance\.(kw|stk|snk|mb|bg|bk|jk|pw|bl)\./.test(permission);
  if (!managed) return null;
  if (granted.includes('*') || granted.includes(permission) || granted.includes(permission.replace(/-/g, '_'))) return true;
  if (['finance.fees.view','finance.fees.create','finance.fees.update'].includes(permission) && granted.includes('finance.fees.manage')) return true;
  const candidates = [...(aliases[permission] || [])];
  if (permission.startsWith('finance.funds.')) {
    const action = permission.split('.').at(-1);
    let selected = kind ? (menus[kind] || []) : Object.values(menus).flat();
    if (action === 'approve') selected = !kind || kind === 'CASH' ? ['stk'] : [];
    candidates.push(...selected.map(menu => `${menu}.${action}`));
    if (action === 'view') {
      candidates.push('kw.view');
      if (granted.includes('finance.receipts.view')) return true;
    }
  }
  return candidates.some(alias => granted.includes(`m.finance.${alias}`));
}
