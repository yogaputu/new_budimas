<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { RouterLink, RouterView, useRoute } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { useAppStore } from '@/app/stores/app';
import { markSupervisorNotificationsRead, pollSupervisorNotifications } from '@/api/supervisorNotifications';
import { navigationSections } from '@/shared/constants/navigation';

const route = useRoute();
const auth = useAuthStore();
const app = useAppStore();
const openSections = ref({});
const menuSearch = ref('');
const notificationAfterId = ref(0);
const supervisorToasts = ref([]);
const supervisorNotificationItems = ref([]);
const supervisorNotificationUnreadCount = ref(0);
const supervisorNotificationPanelOpen = ref(false);
const supervisorNotificationPanelLoading = ref(false);
let notificationTimer = null;
let notificationBusy = false;
let notificationBootstrapped = false;
let supervisorToastId = 0;

const pageTitle = computed(() => route.meta?.pageTitle || formatRouteName(route.name) || 'Budimas Internal');
const pageDescription = computed(() => route.meta?.pageDescription || 'Frontend P1 yang langsung memakai API existing.');

function formatRouteName(value) {
  return String(value || '')
    .split('-')
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

const iconPaths = {
  dashboard: 'M3.75 13.5h6.75V3.75H3.75v9.75Zm9.75 6.75h6.75v-6.75H13.5v6.75Zm0-9.75h6.75V3.75H13.5v6.75ZM3.75 20.25h6.75V16.5H3.75v3.75Z',
  user: 'M12 12a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9Zm-8.25 9a8.25 8.25 0 0 1 16.5 0',
  users: 'M8.25 10.5a3.75 3.75 0 1 0 0-7.5 3.75 3.75 0 0 0 0 7.5Zm7.5 0a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM2.25 21a6 6 0 0 1 12 0m3.75 0a5.25 5.25 0 0 0-4.2-5.145',
  briefcase: 'M9 6.75V5.25A2.25 2.25 0 0 1 11.25 3h1.5A2.25 2.25 0 0 1 15 5.25v1.5m-10.5 0h15A1.5 1.5 0 0 1 21 8.25v9A2.25 2.25 0 0 1 18.75 19.5H5.25A2.25 2.25 0 0 1 3 17.25v-9a1.5 1.5 0 0 1 1.5-1.5Zm6 5.25h3',
  building: 'M4.5 21V4.5A1.5 1.5 0 0 1 6 3h9a1.5 1.5 0 0 1 1.5 1.5V21m-9-13.5h1.5m-1.5 3h1.5m-1.5 3h1.5m3-6H14m-1.5 3H14m-1.5 3H14M3 21h18',
  map: 'M9 18.75 3.75 21V6.75L9 4.5m0 14.25 6-2.25m-6 2.25V4.5m6 12 5.25 2.25V4.5L15 2.25m0 14.25V2.25',
  package: 'M21 8.25 12 3 3 8.25m18 0-9 5.25m9-5.25v7.5L12 21m-9-12.75 9 5.25m-9-5.25v7.5L12 21m0-7.5V21',
  truck: 'M3 6.75h11.25v9H3v-9Zm11.25 3h3.3L21 13.2v2.55h-6.75m-7.5 0a2.25 2.25 0 1 0 0 4.5 2.25 2.25 0 0 0 0-4.5Zm10.5 0a2.25 2.25 0 1 0 0 4.5 2.25 2.25 0 0 0 0-4.5Z',
  document: 'M7.5 3.75h6L18 8.25v12H6v-16.5h1.5Zm6 0v4.5H18M8.25 12h7.5M8.25 15h7.5M8.25 18h4.5',
  clipboard: 'M9 4.5h6M9 4.5A1.5 1.5 0 0 0 7.5 6H6a1.5 1.5 0 0 0-1.5 1.5v12A1.5 1.5 0 0 0 6 21h12a1.5 1.5 0 0 0 1.5-1.5v-12A1.5 1.5 0 0 0 18 6h-1.5A1.5 1.5 0 0 0 15 4.5M9 4.5A1.5 1.5 0 0 1 10.5 3h3A1.5 1.5 0 0 1 15 4.5M8.25 11.25h7.5M8.25 15h5.25',
  calendar: 'M7.5 3v3m9-3v3M4.5 8.25h15M6 5.25h12A1.5 1.5 0 0 1 19.5 6.75v12A1.5 1.5 0 0 1 18 20.25H6a1.5 1.5 0 0 1-1.5-1.5v-12A1.5 1.5 0 0 1 6 5.25Z',
  money: 'M3.75 6.75h16.5v10.5H3.75V6.75Zm3 7.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Zm10.5 0a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3ZM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z',
  chart: 'M4.5 19.5V4.5m0 15h15M8.25 16.5v-6m4.5 6v-9m4.5 9v-12',
  bank: 'M3 9.75 12 4.5l9 5.25M5.25 10.5h13.5M6.75 10.5v7.5m3.5-7.5v7.5m3.5-7.5v7.5m3.5-7.5v7.5M4.5 19.5h15',
  tag: 'M3.75 12.75 12.75 21l7.5-7.5-8.25-8.25H3.75v7.5Zm4.5-3.75h.01',
  check: 'm4.5 12.75 4.5 4.5 10.5-10.5',
  shield: 'M12 3.75 19.5 6v5.25c0 4.5-3 8.25-7.5 9.75-4.5-1.5-7.5-5.25-7.5-9.75V6L12 3.75Zm-3 8.25 2.25 2.25L15.75 9.75',
  box: 'M4.5 7.5 12 3l7.5 4.5m-15 0L12 12m-7.5-4.5V16.5L12 21m7.5-13.5L12 12m7.5-4.5V16.5L12 21m0-9v9',
  settings: 'M12 8.25a3.75 3.75 0 1 0 0 7.5 3.75 3.75 0 0 0 0-7.5Zm0-5.25v2.25m0 13.5V21m8.25-9h-2.25M6 12H3.75m14.08-5.83-1.59 1.59M7.76 16.24l-1.59 1.59m11.66 0-1.59-1.59M7.76 7.76 6.17 6.17',
  grid: 'M4.5 4.5h6v6h-6v-6Zm9 0h6v6h-6v-6Zm-9 9h6v6h-6v-6Zm9 0h6v6h-6v-6Z',
  default: 'M12 3.75 20.25 12 12 20.25 3.75 12 12 3.75Z'
};

const sectionIconMap = {
  Overview: 'dashboard',
  'Master Data': 'grid',
  Akses: 'shield',
  'RBAC Setting': 'shield',
  'Data Tools': 'document',
  'Workflow Center': 'clipboard',
  AI: 'settings',
  Distribusi: 'truck',
  Distribution: 'truck',
  Finance: 'bank',
  Purchase: 'package',
  Purchasing: 'package',
  Laporan: 'chart',
  Promo: 'tag',
  Operasional: 'box',
  Warehouse: 'box',
  Stock: 'box',
  'Sales Canvas': 'truck',
  Canvassing: 'truck',
  'Supervisor Sales': 'chart',
  Supervisor: 'chart',
  Accounting: 'bank'
};

const itemIconMap = {
  Dashboard: 'dashboard',
  Profil: 'user',
  User: 'users',
  Jabatan: 'briefcase',
  Departemen: 'building',
  'Customer Tipe': 'users',
  'Tipe Customer': 'users',
  'Sales Tipe': 'users',
  'Tipe Sales': 'users',
  Sales: 'users',
  'Mapping Sales SPV': 'users',
  Customer: 'users',
  Principal: 'building',
  'Aturan Principal': 'settings',
  Wilayah: 'map',
  Perusahaan: 'building',
  Rute: 'map',
  'Tipe Harga': 'tag',
  Produk: 'package',
  Subbrand: 'tag',
  'Sub-brand': 'tag',
  'Tipe PPN': 'tag',
  Cabang: 'building',
  Armada: 'truck',
  Driver: 'user',
  Helper: 'user',
  'Periode Close': 'calendar',
  Budget: 'money',
  Inventaris: 'briefcase',
  Plafon: 'shield',
  'Hak Akses': 'shield',
  'Fitur User': 'shield',
  'Hak Akses User': 'shield',
  'Fitur Jabatan': 'shield',
  'Hak Akses Jabatan': 'shield',
  'AI Assistant': 'settings',
  'Audit Log': 'settings',
  'Task Center': 'clipboard',
  'Import / Download Data': 'document',
  'Import SO Akasha': 'document',
  'Import SO Akasha TMP': 'document',
  'Import SO Akasha Budimas': 'document',
  'DMS Import': 'document',
  'Import DMS': 'document',
  'Order Sales': 'clipboard',
  'Input Order': 'document',
  'Buat Order': 'document',
  'Retur Sales': 'truck',
  'Ajukan Retur': 'truck',
  'Tracking Retur': 'map',
  'Monitoring Retur': 'map',
  'Invoice Sales': 'document',
  'Invoice Order': 'document',
  Order: 'clipboard',
  'Approval Order': 'clipboard',
  Picking: 'check',
  'Jadwal Armada': 'calendar',
  'Jadwal Pengiriman': 'calendar',
  'Helper Driver': 'truck',
  'Monitoring Armada': 'truck',
  'Manajemen Armada': 'truck',
  'Riwayat Distribusi': 'truck',
  'Detail Faktur': 'document',
  'Revisi Faktur': 'document',
  'Batal Realisasi': 'check',
  'Request Canvas': 'document',
  'Order Canvas': 'clipboard',
  COA: 'bank',
  'Chart of Account': 'bank',
  'Saldo Awal': 'money',
  'Jurnal Setting': 'settings',
  'Jurnal Manual': 'document',
  Jurnal: 'document',
  'Credit Note': 'money',
  'Mutasi Bank': 'bank',
  'Laba Rugi': 'chart',
  Neraca: 'chart',
  'Kartu Stok Bernilai': 'box',
  Tagihan: 'document',
  'Tagihan Plafon': 'document',
  Pembayaran: 'money',
  'Pembayaran Tagihan': 'money',
  'Rekap Pembayaran': 'clipboard',
  'Batal Pembayaran': 'check',
  'Uang Muka Customer': 'money',
  'Riwayat Pembayaran Canvas': 'clipboard',
  'Piutang Customer': 'money',
  'Rekening Perusahaan': 'bank',
  'Setoran Tunai': 'money',
  'Setoran Non Tunai': 'bank',
  'Laporan Kasir': 'chart',
  'Pengeluaran Kasir': 'money',
  'Input Transaksi': 'document',
  'Surat Tagihan Sales': 'document',
  LPH: 'document',
  'Buku Besar': 'bank',
  Pajak: 'document',
  'Finalisasi Setoran': 'check',
  'Purchase Order': 'package',
  'Input Purchase Order': 'document',
  'Buat Purchase Order': 'document',
  'Laporan PO Detail': 'clipboard',
  'Laporan Purchase Order': 'clipboard',
  'Laporan Rute Customer': 'map',
  'Rute Customer': 'map',
  'Buat Request Cabang': 'document',
  'Konfirmasi Request Cabang': 'check',
  'Approval Request Cabang': 'check',
  'Konfirmasi PO': 'check',
  'Approval Purchase Order': 'check',
  'Penerimaan Barang': 'truck',
  'Input Penerimaan': 'document',
  'Input Penerimaan Barang': 'document',
  'Konfirmasi Purchase': 'check',
  'Finalisasi Purchase Order': 'check',
  'Tagihan Purchase': 'document',
  'Tagihan Purchase Order': 'document',
  'Kategori Klaim Promo': 'tag',
  Voucher: 'tag',
  'Monitoring Voucher': 'chart',
  'Voucher per Produk': 'package',
  'Approval Voucher': 'check',
  'Cashback Bertingkat': 'chart',
  'Daftar Klaim Promo': 'clipboard',
  'Approval Promo': 'check',
  'Approval Klaim Promo': 'check',
  'Ajukan Klaim': 'document',
  'Ajukan Klaim Promo': 'document',
  'Kasbon Klaim': 'money',
  'Daftar Kasbon': 'money',
  'Ajukan Kasbon': 'money',
  'Approval Kasbon': 'money',
  'Stock Transfer': 'truck',
  'Stok Transfer': 'truck',
  'Status Pengiriman': 'truck',
  WMS: 'box',
  Monitoring: 'chart',
  'Monitoring Gudang': 'chart',
  'Rak 3D': 'grid',
  'Master Rak': 'grid',
  Penempatan: 'package',
  'Penempatan Barang': 'package',
  'Buat Transfer': 'truck',
  'Buat Stok Transfer': 'truck',
  'Approval Stok Transfer': 'check',
  'Pengiriman Stok Transfer': 'truck',
  'Penerimaan Stok Transfer': 'truck',
  'Eskalasi Stok Transfer': 'check',
  'Stock Opname': 'box',
  'Stok Opname': 'box',
  'Buat Opname': 'box',
  'Buat Stok Opname': 'box',
  'Eskalasi Stok Opname': 'check',
  'Laporan Stok Gudang': 'box',
  'Stok Opname Sales': 'box',
  'Pengeluaran Driver': 'money',
  'Retur Canvas': 'truck',
  'Info Voucher Canvas': 'tag',
  'Tagihan Canvas': 'document',
  'Promo All-In': 'tag',
  'Monitoring Promo': 'chart',
  'Kunjungan Sales': 'map',
  'Dashboard SPV': 'dashboard',
  'Mapping Customer': 'map',
  'Kalender Callplan': 'calendar',
  'Kalender Call Plan': 'calendar',
  'Monitor Stok Opname': 'box',
  'Monitoring Stok Opname': 'box',
  'Setting Target Sales': 'settings',
  'Monitor Target Omset': 'chart',
  'Monitoring Target Omset': 'chart',
  'Approve Retur': 'check',
  'Absensi Sales': 'calendar',
  'Pengajuan Kasbon': 'money',
  'Approval Kasbon': 'money',
  'Analisa DOI': 'chart'
};

const permittedSections = computed(() =>
  navigationSections
    .map((section) => ({
      ...section,
      items: section.items
        .map((item) => permittedItem(item))
        .filter(Boolean)
    }))
    .filter((section) => section.items.length)
);

const visibleSections = computed(() => {
  const keyword = menuSearch.value.trim().toLowerCase();
  if (!keyword) {
    return permittedSections.value;
  }

  return permittedSections.value
    .map((section) => {
      const sectionMatches = section.title.toLowerCase().includes(keyword);
      const matchedItems = sectionMatches ? section.items : filterMenuItems(section.items, keyword);

      return {
        ...section,
        items: matchedItems
      };
    })
    .filter((section) => section.items.length);
});

function iconPath(name) {
  return iconPaths[name] || iconPaths.default;
}

function resolveSectionIcon(section) {
  return sectionIconMap[section.title] || 'default';
}

function resolveItemIcon(item) {
  return itemIconMap[item.label] || 'default';
}

function permittedItem(item) {
  const children = Array.isArray(item.children)
    ? item.children.map((child) => permittedItem(child)).filter(Boolean)
    : [];

  if (!auth.hasMenuAccess(item) && !children.length) {
    return null;
  }

  return {
    ...item,
    children
  };
}

function filterMenuItems(items, keyword) {
  return items
    .map((item) => {
      const childMatches = Array.isArray(item.children) ? filterMenuItems(item.children, keyword) : [];
      const itemMatches = item.label.toLowerCase().includes(keyword);

      if (!itemMatches && !childMatches.length) {
        return null;
      }

      return {
        ...item,
        children: itemMatches ? item.children : childMatches
      };
    })
    .filter(Boolean);
}

function flattenItems(items = []) {
  return items.flatMap((item) => [item, ...flattenItems(item.children || [])]);
}

const sectionToneMap = {
  Overview: {
    gradient: 'from-blue-500 to-cyan-500',
    shadow: 'shadow-blue-950/30',
    soft: 'bg-blue-500/10 text-blue-100 ring-blue-300/20'
  },
  'Master Data': {
    gradient: 'from-sky-500 to-indigo-500',
    shadow: 'shadow-sky-950/30',
    soft: 'bg-sky-500/10 text-sky-100 ring-sky-300/20'
  },
  Akses: {
    gradient: 'from-violet-500 to-fuchsia-500',
    shadow: 'shadow-violet-950/30',
    soft: 'bg-violet-500/10 text-violet-100 ring-violet-300/20'
  },
  'RBAC Setting': {
    gradient: 'from-violet-500 to-fuchsia-500',
    shadow: 'shadow-violet-950/30',
    soft: 'bg-violet-500/10 text-violet-100 ring-violet-300/20'
  },
  'Data Tools': {
    gradient: 'from-cyan-500 to-teal-500',
    shadow: 'shadow-cyan-950/30',
    soft: 'bg-cyan-500/10 text-cyan-100 ring-cyan-300/20'
  },
  'Workflow Center': {
    gradient: 'from-brand-500 to-indigo-500',
    shadow: 'shadow-indigo-950/30',
    soft: 'bg-brand-500/10 text-brand-100 ring-brand-300/20'
  },
  Distribusi: {
    gradient: 'from-emerald-500 to-lime-500',
    shadow: 'shadow-emerald-950/30',
    soft: 'bg-emerald-500/10 text-emerald-100 ring-emerald-300/20'
  },
  Distribution: {
    gradient: 'from-emerald-500 to-lime-500',
    shadow: 'shadow-emerald-950/30',
    soft: 'bg-emerald-500/10 text-emerald-100 ring-emerald-300/20'
  },
  Canvassing: {
    gradient: 'from-emerald-500 to-lime-500',
    shadow: 'shadow-emerald-950/30',
    soft: 'bg-emerald-500/10 text-emerald-100 ring-emerald-300/20'
  },
  Finance: {
    gradient: 'from-amber-500 to-orange-500',
    shadow: 'shadow-amber-950/30',
    soft: 'bg-amber-500/10 text-amber-100 ring-amber-300/20'
  },
  Accounting: {
    gradient: 'from-amber-500 to-orange-500',
    shadow: 'shadow-amber-950/30',
    soft: 'bg-amber-500/10 text-amber-100 ring-amber-300/20'
  },
  Purchase: {
    gradient: 'from-lime-500 to-green-600',
    shadow: 'shadow-lime-950/30',
    soft: 'bg-lime-500/10 text-lime-100 ring-lime-300/20'
  },
  Purchasing: {
    gradient: 'from-lime-500 to-green-600',
    shadow: 'shadow-lime-950/30',
    soft: 'bg-lime-500/10 text-lime-100 ring-lime-300/20'
  },
  Laporan: {
    gradient: 'from-cyan-500 to-emerald-500',
    shadow: 'shadow-cyan-950/30',
    soft: 'bg-cyan-500/10 text-cyan-100 ring-cyan-300/20'
  },
  Promo: {
    gradient: 'from-rose-500 to-pink-500',
    shadow: 'shadow-rose-950/30',
    soft: 'bg-rose-500/10 text-rose-100 ring-rose-300/20'
  },
  AI: {
    gradient: 'from-cyan-500 to-blue-500',
    shadow: 'shadow-cyan-950/30',
    soft: 'bg-cyan-500/10 text-cyan-100 ring-cyan-300/20'
  },
  Operasional: {
    gradient: 'from-purple-500 to-indigo-500',
    shadow: 'shadow-purple-950/30',
    soft: 'bg-purple-500/10 text-purple-100 ring-purple-300/20'
  },
  Warehouse: {
    gradient: 'from-purple-500 to-indigo-500',
    shadow: 'shadow-purple-950/30',
    soft: 'bg-purple-500/10 text-purple-100 ring-purple-300/20'
  },
  Stock: {
    gradient: 'from-purple-500 to-indigo-500',
    shadow: 'shadow-purple-950/30',
    soft: 'bg-purple-500/10 text-purple-100 ring-purple-300/20'
  },
  'Supervisor Sales': {
    gradient: 'from-brand-500 to-emerald-500',
    shadow: 'shadow-brand-950/30',
    soft: 'bg-brand-500/10 text-brand-100 ring-brand-300/20'
  },
  Supervisor: {
    gradient: 'from-brand-500 to-emerald-500',
    shadow: 'shadow-brand-950/30',
    soft: 'bg-brand-500/10 text-brand-100 ring-brand-300/20'
  }
};

function sectionTone(section) {
  return sectionToneMap[section.title] || sectionToneMap.Overview;
}

function sectionHasActive(section) {
  return flattenItems(section.items).some((item) => itemIsActive(section, item));
}

function itemIsActive(section, item) {
  if (Array.isArray(item.children) && item.children.some((child) => itemIsActive(section, child))) {
    return true;
  }

  if (route.path === item.to) return true;
  if (item.to === '/' || !route.path.startsWith(`${item.to}/`)) return false;

  const hasMoreSpecificMatch = flattenItems(section.items).some((other) =>
    other.to !== item.to &&
    other.to.startsWith(`${item.to}/`) &&
    (route.path === other.to || route.path.startsWith(`${other.to}/`))
  );

  return !hasMoreSpecificMatch;
}

function shouldShowChildren(section, item) {
  return Boolean(menuSearch.value.trim()) || itemIsActive(section, item);
}

function isSectionOpen(section) {
  return Boolean(openSections.value[section.title]);
}

function toggleSection(section) {
  openSections.value = visibleSections.value.reduce((state, item) => {
    state[item.title] = item.title === section.title ? !isSectionOpen(section) : false;
    return state;
  }, {});
}

watch(
  [visibleSections, () => route.path, menuSearch],
  ([sections, , search]) => {
    const hasSearch = Boolean(search.trim());
    openSections.value = sections.reduce((state, section) => {
      state[section.title] = hasSearch || sectionHasActive(section);
      return state;
    }, {});
  },
  { immediate: true }
);

async function onLogout() {
  stopSupervisorNotificationPolling();
  await auth.logout();
  window.location.href = '/login';
}

function notificationStorageKey() {
  const userId = auth.user?.id || auth.user?.id_user || auth.user?.email || 'user';
  return `budimas.supervisorNotifications.afterId.${userId}`;
}

function playSupervisorNotificationSound() {
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;

    const context = new AudioContext();
    const oscillator = context.createOscillator();
    const gain = context.createGain();

    oscillator.type = 'sine';
    oscillator.frequency.setValueAtTime(740, context.currentTime);
    oscillator.frequency.setValueAtTime(920, context.currentTime + 0.08);
    gain.gain.setValueAtTime(0.0001, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.08, context.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.22);

    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.24);
    setTimeout(() => context.close?.(), 450);
  } catch {
    // Browser may block audio before a user gesture; toast still appears.
  }
}

function showSupervisorVisitToast(item) {
  const isCheckout = item.event_type === 'check_out';
  const isOrder = item.event_type === 'sales_order_created';
  const id = `${Date.now()}-${supervisorToastId += 1}`;
  supervisorToasts.value = [
    {
      id,
      title: item.title || (isOrder ? 'Order baru' : isCheckout ? 'Sales check-out' : 'Sales check-in'),
      message: item.message || (isOrder ? 'Order sales baru tercatat.' : 'Aktivitas kunjungan sales tercatat.'),
      eventType: item.event_type
    },
    ...supervisorToasts.value
  ].slice(0, 4);

  window.setTimeout(() => {
    supervisorToasts.value = supervisorToasts.value.filter((toastItem) => toastItem.id !== id);
  }, 5000);

  playSupervisorNotificationSound();
}

function dismissSupervisorToast(id) {
  supervisorToasts.value = supervisorToasts.value.filter((toastItem) => toastItem.id !== id);
}

function mergeSupervisorNotificationItems(items) {
  const mapped = items.map((item) => ({
    ...item,
    id: Number(item.id || 0)
  })).filter((item) => item.id && !item.is_read);
  const byId = new Map();
  [...mapped, ...supervisorNotificationItems.value.filter((item) => !item.is_read)].forEach((item) => {
    byId.set(item.id, item);
  });
  supervisorNotificationItems.value = Array.from(byId.values())
    .sort((a, b) => Number(b.id || 0) - Number(a.id || 0))
    .slice(0, 10);
}

function notificationEventLabel(item) {
  if (item?.event_type === 'sales_order_created') return 'Order';
  return item?.event_type === 'check_out' ? 'Check-out' : 'Check-in';
}

function notificationEventTone(item) {
  if (item?.event_type === 'sales_order_created') return 'bg-sky-600';
  if (item?.event_type === 'check_out') return 'bg-amber-500';
  return 'bg-emerald-600';
}

function notificationTimeLabel(item) {
  const value = item?.created_at || item?.read_at;
  if (!value) return '-';

  const normalized = String(value).includes('T') ? String(value) : String(value).replace(' ', 'T');
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) {
    const match = String(value).match(/(\d{2}:\d{2})/);
    return match ? match[1] : String(value);
  }

  return new Intl.DateTimeFormat('id-ID', {
    hour: '2-digit',
    minute: '2-digit'
  }).format(date);
}

async function loadSupervisorNotificationPanel() {
  if (!auth.isAuthenticated) return;

  supervisorNotificationPanelLoading.value = true;
  try {
    const response = await pollSupervisorNotifications({
      limit: 10,
      unread_only: 1
    });
    const payload = response?.data || {};
    const items = Array.isArray(payload.items) ? payload.items : [];
    supervisorNotificationUnreadCount.value = Number(payload.unread_count || 0);
    mergeSupervisorNotificationItems(items);
  } catch {
    // Keep the header quiet; axios already handles auth failures.
  } finally {
    supervisorNotificationPanelLoading.value = false;
  }
}

async function toggleSupervisorNotificationPanel() {
  supervisorNotificationPanelOpen.value = !supervisorNotificationPanelOpen.value;
  if (supervisorNotificationPanelOpen.value) {
    await loadSupervisorNotificationPanel();
  }
}

async function markSupervisorNotificationPanelRead() {
  if (!supervisorNotificationItems.value.length && supervisorNotificationUnreadCount.value <= 0) return;

  const ids = supervisorNotificationItems.value
    .filter((item) => !item.is_read)
    .map((item) => item.id)
    .filter(Boolean);

  try {
    await markSupervisorNotificationsRead(ids.length ? { ids } : {});
    supervisorNotificationUnreadCount.value = 0;
    supervisorNotificationItems.value = [];
  } catch {
    // The next poll will recover unread state.
  }
}

async function pollSupervisorVisitNotifications() {
  if (!auth.isAuthenticated || notificationBusy) return;

  notificationBusy = true;
  try {
    const params = {
      limit: notificationBootstrapped ? 20 : 1
    };

    if (notificationAfterId.value > 0) {
      params.after_id = notificationAfterId.value;
    }

    const response = await pollSupervisorNotifications(params);
    const payload = response?.data || {};
    const items = Array.isArray(payload.items) ? payload.items : [];
    const latestId = Number(payload.latest_id || 0);
    supervisorNotificationUnreadCount.value = Number(payload.unread_count || 0);

    if (!notificationBootstrapped && notificationAfterId.value <= 0) {
      notificationAfterId.value = latestId;
      localStorage.setItem(notificationStorageKey(), String(notificationAfterId.value || 0));
      notificationBootstrapped = true;
      return;
    }

    if (items.length) {
      mergeSupervisorNotificationItems(items.filter((item) => !item.is_read));
      items.forEach(showSupervisorVisitToast);
      notificationAfterId.value = Math.max(
        notificationAfterId.value || 0,
        ...items.map((item) => Number(item.id || 0))
      );
      localStorage.setItem(notificationStorageKey(), String(notificationAfterId.value || 0));
    } else if (latestId > notificationAfterId.value) {
      notificationAfterId.value = latestId;
      localStorage.setItem(notificationStorageKey(), String(notificationAfterId.value || 0));
    }

    notificationBootstrapped = true;
  } catch {
    // Keep polling quiet; auth/network errors are handled by axios interceptors.
  } finally {
    notificationBusy = false;
  }
}

function startSupervisorNotificationPolling() {
  if (!auth.isAuthenticated || notificationTimer) return;

  const stored = Number(localStorage.getItem(notificationStorageKey()) || 0);
  notificationAfterId.value = Number.isFinite(stored) ? stored : 0;
  notificationBootstrapped = false;
  pollSupervisorVisitNotifications();
  notificationTimer = window.setInterval(pollSupervisorVisitNotifications, 10000);
}

function stopSupervisorNotificationPolling() {
  if (notificationTimer) {
    window.clearInterval(notificationTimer);
    notificationTimer = null;
  }
  notificationBusy = false;
  supervisorNotificationPanelOpen.value = false;
}

onMounted(() => {
  startSupervisorNotificationPolling();
});

onUnmounted(() => {
  stopSupervisorNotificationPolling();
});

watch(
  () => auth.isAuthenticated,
  (isAuthenticated) => {
    if (isAuthenticated) {
      startSupervisorNotificationPolling();
    } else {
      stopSupervisorNotificationPolling();
    }
  }
);
</script>

<template>
  <div
    :class="[
      'min-h-screen transition-colors duration-300',
      app.isDark ? 'bg-slate-950 text-slate-100' : 'bg-slate-100 text-slate-900'
    ]"
  >
    <div class="flex min-h-screen">
      <aside
        :class="[
          'fixed inset-y-0 left-0 z-40 flex h-dvh w-72 min-h-0 shrink-0 flex-col overflow-hidden px-5 py-6 transition-transform lg:sticky lg:top-0 lg:h-dvh lg:translate-x-0',
          app.isDark
            ? 'border-r border-slate-800 bg-slate-950 text-white'
            : 'border-r border-emerald-800/20 bg-gradient-to-b from-emerald-900 via-sky-900 to-slate-950 text-white shadow-2xl shadow-emerald-950/20',
          app.sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        ]"
      >
        <div class="flex items-center justify-between">
          <div>
            <p :class="['text-xs uppercase tracking-[0.25em]', app.isDark ? 'text-brand-300' : 'text-emerald-200']">Budimas</p>
            <h1 class="mt-2 text-xl font-semibold">Internal App</h1>
          </div>
          <button class="rounded-full p-2 text-slate-300 lg:hidden" @click="app.closeSidebar">X</button>
        </div>

        <div
          :class="[
            'mt-8 rounded-2xl border p-4',
            app.isDark
              ? 'border-white/10 bg-white/5'
              : 'border-white/20 bg-white/10 shadow-lg shadow-sky-950/10'
          ]"
        >
          <p class="text-sm font-medium">{{ auth.userName }}</p>
          <p :class="['mt-1 text-xs', app.isDark ? 'text-slate-300' : 'text-emerald-100']">{{ auth.roleLabel }}</p>
          <p :class="['mt-1 text-xs', app.isDark ? 'text-slate-400' : 'text-sky-100/80']">{{ auth.branchName }}</p>
        </div>

        <div class="mt-4">
          <label class="sr-only" for="sidebar-menu-search">Cari menu</label>
          <div
            :class="[
              'flex items-center gap-2 rounded-2xl border px-3 py-2.5 transition',
              app.isDark
                ? 'border-white/10 bg-white/5 focus-within:border-brand-400/70'
                : 'border-white/20 bg-white/10 focus-within:border-emerald-200/80'
            ]"
          >
            <svg class="h-4 w-4 shrink-0 text-white/55" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="m21 21-4.35-4.35M10.5 18a7.5 7.5 0 1 1 0-15 7.5 7.5 0 0 1 0 15Z" />
            </svg>
            <input
              id="sidebar-menu-search"
              v-model="menuSearch"
              type="search"
              class="min-w-0 flex-1 border-0 bg-transparent p-0 text-sm text-white outline-none placeholder:text-white/45"
              placeholder="Cari menu..."
            />
            <button
              v-if="menuSearch"
              type="button"
              class="rounded-lg px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.15em] text-white/55 transition hover:bg-white/10 hover:text-white"
              @click="menuSearch = ''"
            >
              Clear
            </button>
          </div>
        </div>

        <div class="mt-6 min-h-0 flex-1 overflow-y-auto overscroll-contain pr-1 [scrollbar-gutter:stable]">
          <nav class="space-y-2 pb-8">
            <section v-for="section in visibleSections" :key="section.title">
              <button
                type="button"
                class="group relative flex w-full items-center justify-between overflow-hidden rounded-2xl px-3 py-3 text-left transition"
                :class="
                  sectionHasActive(section)
                    ? [
                        'bg-white/10 text-white shadow-lg ring-1 ring-white/15',
                        sectionTone(section).shadow
                      ]
                    : (app.isDark
                        ? 'text-slate-300 hover:bg-white/5 hover:text-white'
                        : 'text-emerald-50/85 hover:bg-white/10 hover:text-white')
                "
                @click="toggleSection(section)"
              >
                <span
                  v-if="sectionHasActive(section)"
                  class="absolute left-0 top-1/2 h-10 w-1 -translate-y-1/2 rounded-r-full"
                  :class="['bg-gradient-to-b', sectionTone(section).gradient]"
                />
                <span
                  v-if="sectionHasActive(section)"
                  class="pointer-events-none absolute inset-0 bg-gradient-to-r opacity-15 transition group-hover:opacity-25"
                  :class="sectionTone(section).gradient"
                />
                <span class="flex min-w-0 items-center gap-3">
                  <span
                    :class="[
                      'flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl ring-1 transition',
                      sectionHasActive(section)
                        ? ['bg-white/20 text-white shadow-lg ring-white/30']
                        : ['bg-gradient-to-br text-white/95 ring-white/10 opacity-90', sectionTone(section).gradient]
                    ]"
                  >
                    <svg class="h-[18px] w-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                      <path :d="iconPath(resolveSectionIcon(section))" />
                    </svg>
                  </span>
                  <span class="min-w-0">
                    <span class="block truncate text-xs font-semibold uppercase tracking-[0.2em]">{{ section.title }}</span>
                    <span :class="['mt-1 block text-[11px]', sectionHasActive(section) ? 'text-white/75' : (app.isDark ? 'text-slate-500 group-hover:text-slate-300' : 'text-emerald-100/70')]">
                      {{ section.items.length }} menu
                    </span>
                  </span>
                </span>
                <span class="ml-3 flex shrink-0 items-center gap-2">
                  <span
                    v-if="sectionHasActive(section)"
                    class="hidden rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.16em] text-white ring-1 ring-white/20 xl:inline"
                    :class="['bg-gradient-to-r', sectionTone(section).gradient]"
                  >
                    Aktif
                  </span>
                  <span
                    class="flex h-7 w-7 items-center justify-center rounded-xl text-sm transition-transform"
                    :class="[
                      sectionHasActive(section)
                        ? 'bg-white/20 text-white ring-1 ring-white/20'
                        : (app.isDark ? 'bg-white/5 text-slate-300' : 'bg-white/10 text-emerald-50'),
                      isSectionOpen(section) ? 'rotate-180' : ''
                    ]"
                  >
                    v
                  </span>
                </span>
              </button>
              <div v-show="isSectionOpen(section)" class="mt-2 space-y-1 pl-1">
                <div v-for="item in section.items" :key="item.to" class="space-y-1">
                  <RouterLink
                    :to="item.to"
                    class="relative flex items-center gap-3 rounded-2xl px-3 py-2.5 text-sm transition"
                    :class="
                      itemIsActive(section, item)
                        ? [
                            'bg-gradient-to-r text-white shadow-lg ring-1 ring-white/20',
                            sectionTone(section).gradient,
                            sectionTone(section).shadow
                          ]
                        : (app.isDark
                            ? 'text-slate-300 hover:bg-white/5 hover:text-white'
                            : 'text-emerald-50/90 hover:bg-white/10 hover:text-white')
                    "
                    @click="app.closeSidebar"
                  >
                    <span
                      v-if="itemIsActive(section, item)"
                      class="absolute left-0 top-1/2 h-7 w-1 -translate-y-1/2 rounded-full"
                      :class="['bg-gradient-to-b', sectionTone(section).gradient]"
                    />
                    <span
                      :class="[
                        'flex h-8 w-8 items-center justify-center rounded-xl ring-1 transition',
                        itemIsActive(section, item)
                          ? 'bg-white/20 text-white ring-white/25'
                          : ['bg-gradient-to-br text-white shadow-sm ring-white/10 opacity-95', sectionTone(section).gradient]
                      ]"
                    >
                      <svg class="h-[17px] w-[17px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                        <path :d="iconPath(resolveItemIcon(item))" />
                      </svg>
                    </span>
                    <span>{{ item.label }}</span>
                  </RouterLink>

                  <div v-if="item.children?.length && shouldShowChildren(section, item)" class="ml-7 space-y-1 border-l border-white/10 pl-3">
                    <RouterLink
                      v-for="child in item.children"
                      :key="child.to"
                      :to="child.to"
                      class="relative flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-semibold transition"
                      :class="
                        itemIsActive(section, child)
                          ? 'bg-white/15 text-white ring-1 ring-white/15'
                          : (app.isDark
                              ? 'text-slate-400 hover:bg-white/5 hover:text-white'
                              : 'text-emerald-100/80 hover:bg-white/10 hover:text-white')
                      "
                      @click="app.closeSidebar"
                    >
                      <span
                        :class="[
                          'h-1.5 w-1.5 rounded-full',
                          itemIsActive(section, child) ? 'bg-white' : 'bg-white/35'
                        ]"
                      />
                      <span class="truncate">{{ child.label }}</span>
                    </RouterLink>
                  </div>
                </div>
              </div>
            </section>
            <div
              v-if="!visibleSections.length"
              :class="[
                'rounded-2xl border px-4 py-5 text-center text-sm',
                app.isDark
                  ? 'border-white/10 bg-white/5 text-slate-400'
                  : 'border-white/20 bg-white/10 text-emerald-100/80'
              ]"
            >
              Menu tidak ditemukan.
            </div>
          </nav>
        </div>
      </aside>

      <div class="flex min-h-screen min-w-0 flex-1 flex-col">
        <header
          :class="[
            'sticky top-0 z-30 border-b backdrop-blur transition-colors duration-300',
            app.isDark
              ? 'border-slate-800 bg-slate-950/90'
              : 'border-slate-200 bg-white/90'
          ]"
        >
          <div class="flex items-center justify-between px-4 py-4 sm:px-6">
            <div class="flex items-center gap-3">
              <button
                :class="[
                  'rounded-xl px-3 py-2 lg:hidden transition-colors',
                  app.isDark
                    ? 'border border-slate-700 bg-slate-900 text-slate-100 hover:bg-slate-800'
                    : 'border border-slate-200 bg-white text-slate-900 hover:bg-slate-50'
                ]"
                @click="app.toggleSidebar"
              >
                Menu
              </button>
              <div>
                <h2 :class="['text-lg font-semibold', app.isDark ? 'text-slate-100' : 'text-slate-900']">
                  {{ pageTitle }}
                </h2>
                <p :class="['text-sm', app.isDark ? 'text-slate-400' : 'text-slate-500']">
                  {{ pageDescription }}
                </p>
              </div>
            </div>
            <div class="flex items-center gap-2">
              <div class="relative">
                <button
                  type="button"
                  :class="[
                    'relative flex h-10 w-10 items-center justify-center rounded-xl border transition-colors',
                    app.isDark
                      ? 'border-slate-700 bg-slate-900 text-slate-100 hover:bg-slate-800'
                      : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
                  ]"
                  aria-label="Notifikasi supervisor"
                  @click="toggleSupervisorNotificationPanel"
                >
                  <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M15 17.25a3 3 0 0 1-6 0" />
                    <path d="M18.75 15.75H5.25c.9-1.05 1.5-2.25 1.5-4.5V9a5.25 5.25 0 0 1 10.5 0v2.25c0 2.25.6 3.45 1.5 4.5Z" />
                  </svg>
                  <span
                    v-if="supervisorNotificationUnreadCount > 0"
                    class="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-black leading-none text-white ring-2 ring-white dark:ring-slate-950"
                  >
                    {{ supervisorNotificationUnreadCount > 9 ? '9+' : supervisorNotificationUnreadCount }}
                  </span>
                </button>

                <div
                  v-if="supervisorNotificationPanelOpen"
                  :class="[
                    'absolute right-0 top-12 z-[70] w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-2xl border shadow-2xl',
                    app.isDark
                      ? 'border-slate-700 bg-slate-900 text-slate-100 shadow-slate-950/40'
                      : 'border-slate-200 bg-white text-slate-900 shadow-slate-950/15'
                  ]"
                >
                  <div :class="['flex items-center justify-between border-b px-4 py-3', app.isDark ? 'border-slate-800' : 'border-slate-100']">
                    <div>
                      <p class="text-sm font-bold">Notifikasi</p>
                      <p :class="['text-xs', app.isDark ? 'text-slate-400' : 'text-slate-500']">
                        {{ supervisorNotificationUnreadCount }} belum dibaca
                      </p>
                    </div>
                    <button
                      type="button"
                      :class="[
                        'rounded-lg px-3 py-1.5 text-xs font-bold transition',
                        app.isDark ? 'bg-white/10 text-slate-200 hover:bg-white/15' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                      ]"
                      @click="markSupervisorNotificationPanelRead"
                    >
                      Tandai baca
                    </button>
                  </div>

                  <div class="max-h-80 overflow-y-auto">
                    <div v-if="supervisorNotificationPanelLoading" :class="['px-4 py-5 text-sm', app.isDark ? 'text-slate-400' : 'text-slate-500']">
                      Memuat notifikasi...
                    </div>
                    <div v-else-if="!supervisorNotificationItems.length" :class="['px-4 py-5 text-sm', app.isDark ? 'text-slate-400' : 'text-slate-500']">
                      Belum ada notifikasi.
                    </div>
                    <button
                      v-for="item in supervisorNotificationItems"
                      v-else
                      :key="item.id"
                      type="button"
                      :class="[
                        'block w-full border-b px-4 py-3 text-left transition last:border-b-0',
                        app.isDark
                          ? 'border-slate-800 hover:bg-white/5'
                          : 'border-slate-100 hover:bg-slate-50',
                        !item.is_read ? (app.isDark ? 'bg-sky-500/10' : 'bg-sky-50') : ''
                      ]"
                    >
                      <div class="flex items-start gap-3">
                        <span class="mt-0.5 flex w-16 shrink-0 flex-col items-start gap-1">
                          <span
                            :class="[
                              'rounded-lg px-2 py-1 text-[10px] font-black uppercase tracking-[0.12em] text-white',
                              notificationEventTone(item)
                            ]"
                          >
                            {{ notificationEventLabel(item) }}
                          </span>
                          <span :class="['pl-1 text-[11px] font-semibold', app.isDark ? 'text-slate-400' : 'text-slate-500']">
                            {{ notificationTimeLabel(item) }}
                          </span>
                        </span>
                        <span class="min-w-0 flex-1">
                          <span class="block truncate text-sm font-semibold">{{ item.title }}</span>
                          <span :class="['mt-1 block text-xs leading-5', app.isDark ? 'text-slate-400' : 'text-slate-500']">
                            {{ item.message }}
                          </span>
                        </span>
                      </div>
                    </button>
                  </div>
                </div>
              </div>

              <button
                :class="[
                  'rounded-xl px-3 py-2 text-sm font-medium transition-colors',
                  app.isDark
                    ? 'border border-slate-700 bg-slate-900 text-slate-100 hover:bg-slate-800'
                    : 'border border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
                ]"
                @click="app.toggleTheme"
              >
                {{ app.isDark ? 'Light' : 'Dark' }}
              </button>
              <button
                :class="[
                  'rounded-xl px-4 py-2 text-sm transition-colors',
                  app.isDark
                    ? 'border border-slate-700 bg-slate-900 text-slate-100 hover:bg-slate-800'
                    : 'border border-slate-200 bg-white text-slate-900 hover:bg-slate-50'
                ]"
                @click="onLogout"
              >
                Logout
              </button>
            </div>
          </div>
        </header>

        <main class="min-w-0 flex-1 overflow-x-hidden px-4 py-6 sm:px-6">
          <RouterView v-slot="{ Component, route }">
            <KeepAlive>
              <component :is="Component" :key="route.fullPath" />
            </KeepAlive>
          </RouterView>
        </main>
      </div>
    </div>

    <div
      v-if="supervisorToasts.length"
      class="pointer-events-none fixed right-4 top-4 z-[80] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-3"
      aria-live="polite"
      aria-atomic="true"
    >
      <div
        v-for="toastItem in supervisorToasts"
        :key="toastItem.id"
        :class="[
          'pointer-events-auto overflow-hidden rounded-2xl border p-4 shadow-2xl backdrop-blur transition',
          app.isDark
            ? 'border-sky-400/25 bg-slate-900/95 text-slate-100 shadow-sky-950/30'
            : 'border-emerald-200 bg-white/95 text-slate-900 shadow-slate-950/10'
        ]"
      >
        <div class="flex items-start gap-3">
          <span
            :class="[
              'mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-sm font-bold text-white',
              notificationEventTone({ event_type: toastItem.eventType })
            ]"
          >
            {{ toastItem.eventType === 'sales_order_created' ? 'OR' : toastItem.eventType === 'check_out' ? 'CO' : 'CI' }}
          </span>
          <div class="min-w-0 flex-1">
            <p class="text-sm font-semibold leading-5">{{ toastItem.title }}</p>
            <p :class="['mt-1 text-sm leading-5', app.isDark ? 'text-slate-300' : 'text-slate-600']">
              {{ toastItem.message }}
            </p>
          </div>
          <button
            type="button"
            :class="[
              'rounded-lg px-2 py-1 text-xs font-semibold transition',
              app.isDark ? 'text-slate-400 hover:bg-white/10 hover:text-white' : 'text-slate-500 hover:bg-slate-100 hover:text-slate-900'
            ]"
            @click="dismissSupervisorToast(toastItem.id)"
          >
            X
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
