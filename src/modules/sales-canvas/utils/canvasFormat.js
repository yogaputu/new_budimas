export function formatCurrency(value) {
  return `Rp ${new Intl.NumberFormat('id-ID').format(Number(value || 0))}`;
}

export function formatDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('id-ID', {
    day: '2-digit',
    month: 'short',
    year: 'numeric'
  }).format(date);
}

export function getCurrentUserId(user) {
  return user?.id_user || user?.id || user?.user_id || '';
}

export function resolveCanvasRequestStatus(value) {
  const key = Number(value || 0);
  const map = {
    1: { text: 'Request', className: 'inline-flex rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700' },
    2: { text: 'Approved', className: 'inline-flex rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700' },
    3: { text: 'Closed', className: 'inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700' },
    4: { text: 'Rejected', className: 'inline-flex rounded-full bg-rose-100 px-3 py-1 text-xs font-semibold text-rose-700' }
  };

  return map[key] || { text: `Status ${key || '-'}`, className: 'inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600' };
}

export function resolveCanvasOrderStatus(value) {
  const key = Number(value || 0);
  const map = {
    1: { text: 'Draft', className: 'inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700' },
    2: { text: 'Berjalan', className: 'inline-flex rounded-full bg-sky-100 px-3 py-1 text-xs font-semibold text-sky-700' },
    // A Canvas payment from Sales is only a source claim.  It stays in this
    // state until Finance has rekap/recorded/finalised the money, even when
    // the claimed total equals the order total.
    3: { text: 'Menunggu Finance', className: 'inline-flex rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700' },
    4: { text: 'Closed', className: 'inline-flex rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700' },
    5: { text: 'Batal', className: 'inline-flex rounded-full bg-rose-100 px-3 py-1 text-xs font-semibold text-rose-700' }
  };

  return map[key] || { text: `Status ${key || '-'}`, className: 'inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600' };
}
