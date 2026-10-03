<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import {
  approveCanvasReturn,
  getCanvasOrderProducts,
  getCanvasReturnHistory,
  getCanvasSalesList,
  rejectCanvasReturn,
  returnCanvasStock
} from '@/api/salesCanvas';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import {
  getLoginBranchId,
  getLoginCompanyId,
  getLoginSalesId,
  getRowBranchIds,
  getRowCompanyId,
  isSuperUser,
  scopeRowsByLoginBranch,
  scopeSalesRowsByLogin,
  shouldLockToLoginSales
} from '@/utils/accessScope';
import { formatCurrency, getCurrentUserId } from '@/modules/sales-canvas/utils/canvasFormat';
import {
  canvasPieces,
  canvasUomValue,
  distributeCanvasPieces,
  formatCanvasUomLabel,
  isCanvasUomEnabled,
  normalizeCanvasUomValues
} from '@/modules/sales-canvas/utils/canvasUom';

const authStore = useAuthStore();

const filters = reactive({
  id_cabang: '',
  id_perusahaan: '',
  id_principal: '',
  id_sales: '',
  search: ''
});

const rows = ref([]);
const historyRows = ref([]);
const salesRows = ref([]);
const branchRows = ref([]);
const companyRows = ref([]);
const principalRows = ref([]);
const loading = ref(false);
const historyLoading = ref(false);
const refsLoading = ref(false);
const submitting = ref(false);
const returnModalOpen = ref(false);
const returnDetailOpen = ref(false);
const rejectReturnOpen = ref(false);
const selectedHistoryReturn = ref(null);
const rejectionNote = ref('');
const approvalBusy = ref(false);
const errorMessage = ref('');
const successMessage = ref('');
const productSearch = ref('');
let salesOptionsLoadKey = 0;
let stockLoadKey = 0;
let historyLoadKey = 0;

const userId = computed(() => getCurrentUserId(authStore.user));
const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(authStore.user));
const fallbackSalesId = computed(() => getLoginSalesId(authStore.user));
const canUseLoginScope = computed(() => shouldLockToLoginSales(authStore));
const shouldLockBusinessScope = computed(() => !isSuperUser(authStore));
const fallbackBranchOption = computed(() => {
  if (!fallbackBranchId.value) return null;
  const user = authStore.user || {};
  const code = user.kode_cabang || user.cabang_kode || user.cabang?.kode || '-';
  const name = user.nama_cabang || user.cabang_nama || user.cabang?.nama || 'Cabang login';
  return {
    value: String(fallbackBranchId.value),
    label: `${code} - ${name}`
  };
});

function companyIdsForBranch(branchId) {
  if (!branchId) return [];

  const ids = new Set();
  const branch = branchRows.value.find((item) => String(item.id) === String(branchId));
  const branchCompanyId = getRowCompanyId(branch);
  if (branchCompanyId) ids.add(String(branchCompanyId));
  if (fallbackCompanyId.value) ids.add(String(fallbackCompanyId.value));

  companyRows.value.forEach((item) => {
    if (getRowBranchIds(item).includes(String(branchId))) ids.add(String(item.id));
  });

  principalRows.value.forEach((item) => {
    const companyId = getRowCompanyId(item);
    const sameRegion =
      branch &&
      item.id_wilayah1 &&
      item.id_wilayah2 &&
      String(item.id_wilayah1) === String(branch.id_wilayah1) &&
      String(item.id_wilayah2) === String(branch.id_wilayah2);

    if (companyId && sameRegion) ids.add(String(companyId));
  });

  return [...ids];
}

function syncCompanyFromBranch() {
  const allowed = companyIdsForBranch(filters.id_cabang);
  filters.id_perusahaan = shouldLockBusinessScope.value && fallbackCompanyId.value
    ? String(fallbackCompanyId.value)
    : allowed.includes(String(filters.id_perusahaan)) ? String(filters.id_perusahaan) : '';
  filters.id_principal = '';
  resetSalesFilter();
}

function resetSalesFilter() {
  filters.id_sales = canUseLoginScope.value && fallbackSalesId.value ? String(fallbackSalesId.value) : '';
}

const branchOptions = computed(() => {
  const options = scopeRowsByLoginBranch(branchRows.value, authStore).map((item) => ({
    value: String(item.id),
    label: `${item.kode || '-'} - ${item.nama || item.nama_cabang || 'Cabang'}`
  }));

  if (fallbackBranchOption.value && !options.some((item) => item.value === fallbackBranchOption.value.value)) {
    options.unshift(fallbackBranchOption.value);
  }

  return options;
});

const companyOptions = computed(() => {
  const allowedCompanyIds = companyIdsForBranch(filters.id_cabang);
  return companyRows.value
    .filter((item) => filters.id_cabang && allowedCompanyIds.includes(String(item.id)))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || '-'} - ${item.nama || item.nama_perusahaan || 'Perusahaan'}`
    }));
});

const principalOptions = computed(() =>
  principalRows.value
    .filter((item) => !filters.id_perusahaan || String(getRowCompanyId(item)) === String(filters.id_perusahaan))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || '-'} - ${item.nama || item.principal_nama || 'Principal'}`
    }))
);

const salesOptions = computed(() =>
  scopeSalesRowsByLogin(salesRows.value, authStore).map((item) => ({
    value: String(item.id_sales || item.id || ''),
    label: `${item.kode_sales ? `${item.kode_sales} - ` : ''}${item.nama_sales || 'Sales'}${item.nama_tipe_sales ? ` | ${item.nama_tipe_sales}` : ''}`
  }))
);

const filteredRows = computed(() => {
  const query = productSearch.value.trim().toLowerCase();
  return rows.value
    .filter((item) => Number(item.stock_canvas || 0) > 0)
    .filter((item) => {
      if (!query) return true;
      return [item.nama_produk, item.nama_principal, item.id_produk, item.uom1_nama, item.uom2_nama, item.uom3_nama]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query));
    })
    .map((item) => {
      const qtyPieces = calculatePieces(item, item.return_uom1, item.return_uom2, item.return_uom3);
      item.product_label = item.nama_produk || '-';
      item.principal_label = item.nama_principal || '-';
      item.stock_label = `${Number(item.stock_canvas || 0).toLocaleString('id-ID')} pcs`;
      item.return_label = `${Number(qtyPieces || 0).toLocaleString('id-ID')} pcs`;
      item.value_label = formatCurrency(qtyPieces * Number(item.harga_per_uom1 || item.harga_beli || 0));
      return item;
    });
});

const selectedReturnRows = computed(() =>
  rows.value
    .map((item) => ({
      ...item,
      qty_return_pieces: calculatePieces(item, item.return_uom1, item.return_uom2, item.return_uom3)
    }))
    .filter((item) => Number(item.qty_return_pieces || 0) > 0)
);

const summaryCards = computed(() => [
  { label: 'Riwayat Retur', value: String(historyRows.value.length) },
  { label: 'Produk Stok Canvas', value: String(rows.value.filter((item) => Number(item.stock_canvas || 0) > 0).length) },
  { label: 'Item Diretur', value: String(selectedReturnRows.value.length) },
  {
    label: 'Estimasi Nilai',
    value: formatCurrency(selectedReturnRows.value.reduce((sum, item) => sum + Number(item.qty_return_pieces || 0) * Number(item.harga_per_uom1 || item.harga_beli || 0), 0))
  }
]);

const tableColumns = [
  { key: 'product_label', label: 'Produk' },
  { key: 'principal_label', label: 'Principal' },
  { key: 'stock_label', label: 'Stok Canvas' },
  { key: 'return_label', label: 'Qty Retur' },
  { key: 'value_label', label: 'Estimasi' }
];

const historyTableRows = computed(() =>
  historyRows.value.map((item) => ({
    ...item,
    kode_return_label: item.kode_return || `RT-CNV-${item.id_return || item.id || '-'}`,
    tanggal_label: formatDate(item.tanggal_return || item.created_at),
    sales_label: item.nama_sales || item.kode_sales || '-',
    cabang_label: item.nama_cabang || item.kode_cabang || '-',
    principal_label: item.nama_principal || '-',
    produk_label: item.nama_produk || '-',
    total_qty_label: `${Number(item.total_qty_detail || item.total_qty || 0).toLocaleString('id-ID')} pcs`,
    status_label: returnStatusLabel(item),
    warehouse_status_label: item.warehouse_status || '-'
  }))
);

const historyColumns = [
  { key: 'kode_return_label', label: 'Kode Retur' },
  { key: 'tanggal_label', label: 'Tanggal' },
  { key: 'sales_label', label: 'Sales Canvas' },
  { key: 'cabang_label', label: 'Cabang' },
  { key: 'principal_label', label: 'Principal' },
  { key: 'total_item', label: 'Item' },
  { key: 'total_qty_label', label: 'Qty Retur' },
  { key: 'status_label', label: 'Status' }
];

function formatDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString('id-ID', {
    day: '2-digit',
    month: 'short',
    year: 'numeric'
  });
}

function returnStatusLabel(item) {
  if (item?.status_label) return item.status_label;
  const status = Number(item?.status || 0);
  const warehouseStatus = String(item?.warehouse_status || '').toUpperCase();
  if (status === 9 || warehouseStatus === 'DITOLAK') return 'Ditolak';
  if (status === 3 || warehouseStatus === 'QC_SELESAI') return 'QC selesai';
  if (status === 2 || warehouseStatus === 'MENUNGGU_QC') return 'Menunggu QC';
  if (status === 1 && warehouseStatus === 'MENUNGGU_APPROVAL') return 'Menunggu approval';
  return 'Riwayat retur';
}

function openHistoryReturn(row) {
  selectedHistoryReturn.value = row;
  rejectionNote.value = '';
  returnDetailOpen.value = true;
}

async function refreshHistoryReturnSelection() {
  const selectedId = selectedHistoryReturn.value?.id_return || selectedHistoryReturn.value?.id;
  await loadHistory();
  if (!selectedId) return;
  selectedHistoryReturn.value = historyRows.value.find((item) => String(item.id_return || item.id) === String(selectedId)) || null;
}

async function approveHistoryReturn() {
  const row = selectedHistoryReturn.value;
  if (!row?.can_approve || approvalBusy.value) return;
  if (!window.confirm(`Setujui ${row.kode_return || 'pengajuan retur Canvas'} dan kirim ke QC Karantina? Stok Canvas akan dikurangi, sedangkan stok gudang hanya bertambah setelah QC GOOD.`)) return;

  approvalBusy.value = true;
  errorMessage.value = '';
  try {
    await approveCanvasReturn({ id_return: row.id_return || row.id });
    successMessage.value = 'Retur Canvas disetujui dan dikirim ke QC Karantina. Stok gudang belum berubah.';
    await refreshHistoryReturnSelection();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Gagal menyetujui retur Canvas.');
  } finally {
    approvalBusy.value = false;
  }
}

function openRejectReturn() {
  if (!selectedHistoryReturn.value?.can_reject) return;
  rejectionNote.value = '';
  rejectReturnOpen.value = true;
}

async function submitRejectReturn() {
  const row = selectedHistoryReturn.value;
  if (!row?.can_reject || approvalBusy.value) return;
  if (rejectionNote.value.trim().length < 3) {
    errorMessage.value = 'Catatan penolakan minimal 3 karakter.';
    return;
  }
  approvalBusy.value = true;
  errorMessage.value = '';
  try {
    await rejectCanvasReturn({
      id_return: row.id_return || row.id,
      rejection_note: rejectionNote.value.trim()
    });
    rejectReturnOpen.value = false;
    successMessage.value = 'Pengajuan retur Canvas ditolak. Stok Canvas dan stok gudang tidak berubah.';
    await refreshHistoryReturnSelection();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Gagal menolak retur Canvas.');
  } finally {
    approvalBusy.value = false;
  }
}

function calculatePieces(item, qtyUom1 = 0, qtyUom2 = 0, qtyUom3 = 0) {
  return canvasPieces(item, qtyUom1, qtyUom2, qtyUom3);
}

function resetRows() {
  stockLoadKey += 1;
  rows.value = [];
  productSearch.value = '';
  loading.value = false;
}

function clearPrincipalDependentState() {
  salesOptionsLoadKey += 1;
  stockLoadKey += 1;
  historyLoadKey += 1;
  salesRows.value = [];
  rows.value = [];
  historyRows.value = [];
  productSearch.value = '';
  returnModalOpen.value = false;
  loading.value = false;
  historyLoading.value = false;
}

function selectBranch(value) {
  filters.id_cabang = String(value || '');
}

function selectCompany(value) {
  filters.id_perusahaan = String(value || '');
}

function selectPrincipal(value) {
  filters.id_principal = String(value || '');
}

function resetFilters() {
  filters.id_cabang = shouldLockBusinessScope.value && fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  filters.id_perusahaan = shouldLockBusinessScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
  filters.id_principal = '';
  filters.id_sales = canUseLoginScope.value && fallbackSalesId.value ? String(fallbackSalesId.value) : '';
  filters.search = '';
  if (filters.id_cabang) syncCompanyFromBranch();
  if (shouldLockBusinessScope.value && fallbackCompanyId.value) filters.id_perusahaan = String(fallbackCompanyId.value);
  if (canUseLoginScope.value && fallbackSalesId.value) filters.id_sales = String(fallbackSalesId.value);
  loadSalesOptions();
  resetRows();
  loadHistory();
}

function fillAllStock() {
  rows.value = rows.value.map((item) => {
    const quantities = distributeCanvasPieces(item, item.stock_canvas);
    return {
      ...item,
      return_uom1: quantities.qty_uom1,
      return_uom2: quantities.qty_uom2,
      return_uom3: quantities.qty_uom3
    };
  });
}

function clearReturnQty() {
  rows.value = rows.value.map((item) => ({
    ...item,
    return_uom1: 0,
    return_uom2: 0,
    return_uom3: 0
  }));
}

function normalizeProduct(row) {
  return {
    ...row,
    id_produk: row.id_produk || row.id,
    return_uom1: 0,
    return_uom2: 0,
    return_uom3: 0
  };
}

function isReturnUomEnabled(item, level) {
  return isCanvasUomEnabled(item, level);
}

function returnUomLabel(item, level) {
  return formatCanvasUomLabel(item, level);
}

function updateReturnQty(item, level, value) {
  item[`return_uom${level}`] = canvasUomValue(item, level, value);
}

function normalizedReturnUomValues(item) {
  const normalized = normalizeCanvasUomValues(item, {
    qty_uom1: item.return_uom1,
    qty_uom2: item.return_uom2,
    qty_uom3: item.return_uom3
  });
  return {
    qty_uom1: normalized.qty_uom1,
    qty_uom2: normalized.qty_uom2,
    qty_uom3: normalized.qty_uom3
  };
}

async function loadHistory() {
  if (!userId.value) {
    errorMessage.value = 'User login tidak memiliki ID untuk memuat riwayat retur canvas.';
    return;
  }

  const loadKey = ++historyLoadKey;
  const scope = [filters.id_cabang, filters.id_perusahaan, filters.id_principal, filters.id_sales, filters.search].map((value) => String(value || '')).join(':');
  historyLoading.value = true;
  errorMessage.value = '';

  try {
    const response = await getCanvasReturnHistory(userId.value, {
      id_cabang: filters.id_cabang || undefined,
      id_perusahaan: filters.id_perusahaan || undefined,
      id_principal: filters.id_principal || undefined,
      id_sales: filters.id_sales || undefined,
      search: filters.search || undefined
    });
    if (loadKey !== historyLoadKey || scope !== [filters.id_cabang, filters.id_perusahaan, filters.id_principal, filters.id_sales, filters.search].map((value) => String(value || '')).join(':')) return;
    historyRows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    if (loadKey !== historyLoadKey) return;
    historyRows.value = [];
    errorMessage.value = normalizeError(error, 'Gagal memuat riwayat retur canvas.');
  } finally {
    if (loadKey === historyLoadKey) historyLoading.value = false;
  }
}

async function openReturnModal() {
  if (!filters.id_principal || !filters.id_sales) {
    errorMessage.value = 'Pilih Cabang, Perusahaan, Principal, dan Sales Canvas terlebih dahulu sebelum tambah retur.';
    return;
  }

  returnModalOpen.value = true;
  if (!rows.value.length) {
    await loadRows();
  }
}

async function loadRefs() {
  refsLoading.value = true;
  try {
    const [branchResponse, companyResponse, principalResponse] = await Promise.allSettled([getBranches(), getCompanies(), getPrincipals()]);
    const errors = [];

    if (branchResponse.status === 'fulfilled') branchRows.value = normalizeList(unwrapResponse(branchResponse.value));
    else errors.push(`Cabang: ${normalizeError(branchResponse.reason)}`);

    if (companyResponse.status === 'fulfilled') companyRows.value = normalizeList(unwrapResponse(companyResponse.value));
    else errors.push(`Perusahaan: ${normalizeError(companyResponse.reason)}`);

    if (principalResponse.status === 'fulfilled') principalRows.value = normalizeList(unwrapResponse(principalResponse.value));
    else errors.push(`Principal: ${normalizeError(principalResponse.reason)}`);

    if (errors.length) errorMessage.value = `Sebagian filter belum termuat. ${errors.join(' | ')}`;

    if (!filters.id_cabang && shouldLockBusinessScope.value && fallbackBranchId.value) {
      filters.id_cabang = String(fallbackBranchId.value);
      syncCompanyFromBranch();
    }
    if (shouldLockBusinessScope.value && fallbackCompanyId.value) filters.id_perusahaan = String(fallbackCompanyId.value);
    if (canUseLoginScope.value && fallbackSalesId.value) filters.id_sales = String(fallbackSalesId.value);
  } finally {
    refsLoading.value = false;
  }
}

async function loadSalesOptions() {
  const loadKey = ++salesOptionsLoadKey;
  const scope = [filters.id_cabang, filters.id_perusahaan, filters.id_principal].map((value) => String(value || '')).join(':');
  try {
    const response = await getCanvasSalesList({
      id_cabang: filters.id_cabang || undefined,
      id_perusahaan: filters.id_perusahaan || undefined,
      id_principal: filters.id_principal || undefined
    });
    if (loadKey !== salesOptionsLoadKey || scope !== [filters.id_cabang, filters.id_perusahaan, filters.id_principal].map((value) => String(value || '')).join(':')) return;
    salesRows.value = normalizeList(unwrapResponse(response));
    if (canUseLoginScope.value && fallbackSalesId.value) {
      filters.id_sales = String(fallbackSalesId.value);
      return;
    }
    if (!filters.id_sales && salesOptions.value.length === 1) {
      filters.id_sales = String(salesOptions.value[0].value || '');
    }
  } catch {
    if (loadKey !== salesOptionsLoadKey) return;
    salesRows.value = [];
  }
}

async function loadRows() {
  if (!filters.id_principal || !filters.id_sales) {
    errorMessage.value = 'Pilih Cabang, Perusahaan, Principal, dan Sales Canvas terlebih dahulu.';
    return;
  }

  if (!userId.value) {
    errorMessage.value = 'User login tidak memiliki ID untuk memuat stok canvas.';
    return;
  }

  const loadKey = ++stockLoadKey;
  const scope = [filters.id_principal, filters.id_sales, productSearch.value, userId.value].map((value) => String(value || '')).join(':');
  loading.value = true;
  errorMessage.value = '';
  successMessage.value = '';

  try {
    const response = await getCanvasOrderProducts(userId.value, {
      id_sales: filters.id_sales,
      id_principal: filters.id_principal,
      filters: productSearch.value || undefined,
      limit: 500,
      page: 1
    });
    if (loadKey !== stockLoadKey || scope !== [filters.id_principal, filters.id_sales, productSearch.value, userId.value].map((value) => String(value || '')).join(':')) return;
    rows.value = normalizeList(unwrapResponse(response)).map(normalizeProduct);
  } catch (error) {
    if (loadKey !== stockLoadKey) return;
    rows.value = [];
    errorMessage.value = normalizeError(error, 'Gagal memuat stok canvas.');
  } finally {
    if (loadKey === stockLoadKey) loading.value = false;
  }
}

async function submitReturn() {
  if (!filters.id_principal || !filters.id_sales) {
    errorMessage.value = 'Pilih principal dan sales canvas terlebih dahulu.';
    return;
  }

  if (!selectedReturnRows.value.length) {
    errorMessage.value = 'Isi qty retur minimal untuk satu produk.';
    return;
  }

  const invalid = selectedReturnRows.value.find((item) => Number(item.qty_return_pieces || 0) > Number(item.stock_canvas || 0));
  if (invalid) {
    errorMessage.value = `Qty retur ${invalid.nama_produk || invalid.id_produk} melebihi stok canvas.`;
    return;
  }

  submitting.value = true;
  errorMessage.value = '';
  successMessage.value = '';

  try {
    await returnCanvasStock({
      id: userId.value,
      id_user: userId.value,
      id_sales: filters.id_sales,
      id_principal: filters.id_principal,
      list_items: selectedReturnRows.value.map((item) => ({
        id_produk: item.id_produk || item.id,
        ...normalizedReturnUomValues(item)
      }))
    });
    successMessage.value = 'Pengajuan retur Canvas tersimpan dan menunggu approval. Stok gudang belum berubah.';
    await loadRows();
    await loadHistory();
    returnModalOpen.value = false;
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Gagal menyimpan retur canvas.');
  } finally {
    submitting.value = false;
  }
}

watch(
  () => filters.id_cabang,
  (value, previous) => {
    if (String(value || '') === String(previous || '')) return;
    syncCompanyFromBranch();
    resetRows();
    loadSalesOptions();
    loadHistory();
  }
);

watch(
  () => filters.id_perusahaan,
  (value, previous) => {
    if (String(value || '') === String(previous || '')) return;
    filters.id_principal = '';
    resetSalesFilter();
    resetRows();
    loadSalesOptions();
    loadHistory();
  }
);

watch(
  () => filters.id_principal,
  (value, previous) => {
    if (String(value || '') === String(previous || '')) return;
    resetSalesFilter();
    clearPrincipalDependentState();
    loadSalesOptions();
    loadHistory();
  }
);

watch(
  () => filters.id_sales,
  (value, previous) => {
    if (String(value || '') === String(previous || '')) return;
    resetRows();
    returnModalOpen.value = false;
    loadHistory();
  }
);

onMounted(async () => {
  await loadRefs();
  await loadSalesOptions();
  await loadHistory();
});
</script>

<template>
  <div>
    <PageHeader
      title="Retur Canvas"
      description="Ajukan retur stok Canvas, tunggu approval, lalu WMS memeriksa barang di QC Karantina sebelum stok GOOD masuk ke rak."
    >
      <div class="flex flex-wrap gap-2">
        <button class="btn-secondary" :disabled="historyLoading" @click="loadHistory">Muat Riwayat</button>
        <button class="btn-primary" :disabled="!filters.id_principal || !filters.id_sales" @click="openReturnModal">+ Tambah Retur</button>
      </div>
    </PageHeader>

    <section class="panel-muted relative z-30 p-4">
      <div>
        <h2 class="text-sm font-black text-slate-950 dark:text-white">Filter Retur Canvas</h2>
        <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">Urutan filter dikunci: Cabang -> Perusahaan -> Principal -> Sales Canvas.</p>
      </div>

      <div class="mt-4 grid min-w-0 gap-3 lg:grid-cols-2 2xl:grid-cols-4">
        <AppSearchSelect v-model="filters.id_cabang" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="refsLoading || (shouldLockBusinessScope && !!fallbackBranchId)" empty-text="Cabang belum tersedia." @update:model-value="selectBranch" />
        <AppSearchSelect v-model="filters.id_perusahaan" label="Perusahaan" :placeholder="filters.id_cabang ? 'Pilih perusahaan' : 'Pilih cabang dulu'" :options="companyOptions" :disabled="!filters.id_cabang || (shouldLockBusinessScope && !!fallbackCompanyId)" empty-text="Perusahaan belum tersedia untuk cabang ini." @update:model-value="selectCompany" />
        <AppSearchSelect v-model="filters.id_principal" label="Principal" :placeholder="filters.id_perusahaan ? 'Pilih principal' : 'Pilih perusahaan dulu'" :options="principalOptions" :disabled="!filters.id_perusahaan" empty-text="Principal belum tersedia." @update:model-value="selectPrincipal" />
        <AppSearchSelect v-model="filters.id_sales" label="Sales Canvas" :placeholder="filters.id_principal ? 'Pilih sales canvas' : 'Pilih principal dulu'" :options="salesOptions" :disabled="!filters.id_principal || (canUseLoginScope && !!fallbackSalesId)" empty-text="Sales canvas belum tersedia." />
        <label class="block min-w-0 2xl:col-span-2">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">Cari Riwayat / Produk</span>
          <input v-model="filters.search" class="field" placeholder="Kode retur, sales, produk, principal..." @keyup.enter="loadHistory" />
        </label>
      </div>

      <div class="mt-4 flex flex-wrap gap-2">
        <button class="btn-primary" :disabled="historyLoading" @click="loadHistory">Terapkan</button>
        <button class="btn-secondary" @click="resetFilters">Reset</button>
      </div>
    </section>

    <p v-if="errorMessage" class="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-semibold text-rose-700 dark:border-rose-500/40 dark:bg-rose-500/10 dark:text-rose-200">
      {{ errorMessage }}
    </p>
    <p v-if="successMessage" class="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-semibold text-emerald-700 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-200">
      {{ successMessage }}
    </p>

    <section class="relative z-0 mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <div v-for="card in summaryCards" :key="card.label" class="panel-muted p-4">
        <p class="text-xs font-black uppercase tracking-[0.3em] text-slate-500 dark:text-slate-400">{{ card.label }}</p>
        <p class="mt-3 text-xl font-black text-slate-950 dark:text-white">{{ card.value }}</p>
      </div>
    </section>

    <section class="panel-muted mt-5 p-4">
      <div class="mb-4 flex flex-col gap-2 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 class="text-lg font-black text-slate-950 dark:text-white">Riwayat Retur Canvas</h2>
          <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">Klik satu baris untuk melihat status, alasan penolakan, atau tindakan approval yang tersedia.</p>
        </div>
        <div class="rounded-2xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 dark:border-slate-700 dark:text-slate-300">
          {{ historyTableRows.length }} retur tampil
        </div>
      </div>

      <AppTable
        :columns="historyColumns"
        :rows="historyTableRows"
        :loading="historyLoading"
        :clickable-rows="true"
        :selected-key="selectedHistoryReturn?.id_return || selectedHistoryReturn?.id || ''"
        empty-message="Belum ada riwayat retur canvas untuk filter ini."
        @row-click="openHistoryReturn"
      />
    </section>

    <AppModal
      :open="returnModalOpen"
      title="Tambah Retur Canvas"
      description="Isi qty barang canvas yang kembali ke gudang."
      size="7xl"
      @close="returnModalOpen = false"
    >
      <div class="space-y-5">
        <section class="flex flex-col gap-3 rounded-3xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-900/70 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 class="text-lg font-black text-slate-950 dark:text-white">Stok Canvas Sales</h2>
            <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">Isi qty barang yang diajukan kembali. Stok Canvas baru berkurang setelah approval; stok gudang hanya bertambah dari hasil QC GOOD.</p>
          </div>
          <div class="flex flex-wrap gap-2">
            <button class="btn-secondary" :disabled="loading" @click="loadRows">{{ loading ? 'Memuat...' : 'Muat Stok' }}</button>
            <button class="btn-secondary" :disabled="!rows.length" @click="fillAllStock">Retur Semua Stok</button>
            <button class="btn-secondary" :disabled="!rows.length" @click="clearReturnQty">Kosongkan Qty</button>
          </div>
        </section>

        <label class="block">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">Cari Barang Retur</span>
          <input v-model="productSearch" class="field" placeholder="Nama produk, principal, atau UOM" @keyup.enter="loadRows" />
        </label>

        <section class="overflow-x-auto rounded-3xl border border-slate-200 dark:border-slate-700">
          <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
            <thead class="bg-slate-50 dark:bg-slate-900">
              <tr>
                <th class="px-4 py-3 text-left font-black uppercase tracking-[0.25em] text-slate-500 dark:text-slate-400">Produk</th>
                <th class="px-4 py-3 text-left font-black uppercase tracking-[0.25em] text-slate-500 dark:text-slate-400">Stok Canvas</th>
                <th class="px-4 py-3 text-left font-black uppercase tracking-[0.25em] text-slate-500 dark:text-slate-400">Retur UOM Besar</th>
                <th class="px-4 py-3 text-left font-black uppercase tracking-[0.25em] text-slate-500 dark:text-slate-400">Retur UOM Tengah</th>
                <th class="px-4 py-3 text-left font-black uppercase tracking-[0.25em] text-slate-500 dark:text-slate-400">Retur UOM Kecil</th>
                <th class="px-4 py-3 text-left font-black uppercase tracking-[0.25em] text-slate-500 dark:text-slate-400">Total</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-200 bg-white dark:divide-slate-800 dark:bg-slate-950">
              <tr v-if="loading">
                <td colspan="6" class="px-4 py-10 text-center text-slate-500 dark:text-slate-400">Memuat stok canvas...</td>
              </tr>
              <tr v-else-if="!filteredRows.length">
                <td colspan="6" class="px-4 py-10 text-center text-slate-500 dark:text-slate-400">Belum ada stok canvas untuk filter ini.</td>
              </tr>
              <tr v-for="item in filteredRows" v-else :key="item.id_produk" class="align-top">
                <td class="px-4 py-3">
                  <p class="font-black text-slate-950 dark:text-white">{{ item.product_label }}</p>
                  <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">{{ item.principal_label }}</p>
                </td>
                <td class="px-4 py-3 font-semibold text-slate-700 dark:text-slate-200">{{ item.stock_label }}</td>
                <td class="px-4 py-3">
                  <input :value="item.return_uom3" type="number" min="0" step="1" inputmode="numeric" class="field max-w-[160px]" :disabled="!isReturnUomEnabled(item, 3)" @input="updateReturnQty(item, 3, $event.target.value)" />
                  <p class="mt-1 text-xs text-slate-500">{{ returnUomLabel(item, 3) }}</p>
                </td>
                <td class="px-4 py-3">
                  <input :value="item.return_uom2" type="number" min="0" step="1" inputmode="numeric" class="field max-w-[160px]" :disabled="!isReturnUomEnabled(item, 2)" @input="updateReturnQty(item, 2, $event.target.value)" />
                  <p class="mt-1 text-xs text-slate-500">{{ returnUomLabel(item, 2) }}</p>
                </td>
                <td class="px-4 py-3">
                  <input :value="item.return_uom1" type="number" min="0" step="1" inputmode="numeric" class="field max-w-[160px]" :disabled="!isReturnUomEnabled(item, 1)" @input="updateReturnQty(item, 1, $event.target.value)" />
                  <p class="mt-1 text-xs text-slate-500">{{ returnUomLabel(item, 1) }}</p>
                </td>
                <td class="px-4 py-3">
                  <p class="font-black text-slate-950 dark:text-white">{{ item.return_label }}</p>
                  <p class="mt-1 text-xs text-emerald-600 dark:text-emerald-300">{{ item.value_label }}</p>
                </td>
              </tr>
            </tbody>
          </table>
        </section>

        <section>
          <h2 class="mb-3 text-lg font-black text-slate-950 dark:text-white">Ringkasan Retur</h2>
          <AppTable
            :columns="tableColumns"
            :rows="selectedReturnRows.map((item) => ({
              ...item,
              product_label: item.nama_produk || '-',
              principal_label: item.nama_principal || '-',
              stock_label: `${Number(item.stock_canvas || 0).toLocaleString('id-ID')} pcs`,
              return_label: `${Number(item.qty_return_pieces || 0).toLocaleString('id-ID')} pcs`,
              value_label: formatCurrency(Number(item.qty_return_pieces || 0) * Number(item.harga_per_uom1 || item.harga_beli || 0))
            }))"
            :paginated="false"
            empty-message="Belum ada qty retur yang diisi."
          />
        </section>
      </div>

      <template #footer>
        <div class="flex flex-wrap justify-end gap-2">
          <button class="btn-secondary" @click="returnModalOpen = false">Batal</button>
          <button class="btn-primary" :disabled="submitting || !selectedReturnRows.length" @click="submitReturn">
            {{ submitting ? 'Menyimpan...' : 'Submit Retur' }}
          </button>
        </div>
      </template>
    </AppModal>

    <AppModal
      :open="returnDetailOpen"
      title="Detail Retur Canvas"
      description="Jejak pengajuan, approval, dan penerimaan QC Karantina."
      size="lg"
      @close="returnDetailOpen = false"
    >
      <div v-if="selectedHistoryReturn" class="space-y-4">
        <section class="grid gap-3 sm:grid-cols-2">
          <div class="rounded-2xl border border-slate-200 p-3 dark:border-slate-700">
            <p class="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Kode Retur</p>
            <p class="mt-1 font-black text-slate-950 dark:text-white">{{ selectedHistoryReturn.kode_return || `RT-CNV-${selectedHistoryReturn.id_return || selectedHistoryReturn.id}` }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 p-3 dark:border-slate-700">
            <p class="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Status</p>
            <p class="mt-1 font-black text-slate-950 dark:text-white">{{ returnStatusLabel(selectedHistoryReturn) }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 p-3 dark:border-slate-700">
            <p class="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Sales / Cabang</p>
            <p class="mt-1 font-semibold text-slate-950 dark:text-white">{{ selectedHistoryReturn.nama_sales || '-' }} · {{ selectedHistoryReturn.nama_cabang || '-' }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 p-3 dark:border-slate-700">
            <p class="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Produk / Qty</p>
            <p class="mt-1 font-semibold text-slate-950 dark:text-white">{{ selectedHistoryReturn.nama_produk || '-' }} · {{ Number(selectedHistoryReturn.total_qty_detail || selectedHistoryReturn.total_qty || 0).toLocaleString('id-ID') }} pcs</p>
          </div>
        </section>

        <section class="rounded-2xl border border-sky-200 bg-sky-50 p-4 text-sm text-sky-900 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-100">
          <p class="font-black">Alur stok</p>
          <p class="mt-1">Approval mengurangi stok Canvas dan membuat antrean QC. Stok gudang hanya ditambah ketika petugas QC menetapkan qty GOOD ke rak tujuan.</p>
        </section>

        <section v-if="selectedHistoryReturn.rejection_note" class="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-100">
          <p class="font-black">Catatan penolakan</p>
          <p class="mt-1 whitespace-pre-wrap">{{ selectedHistoryReturn.rejection_note }}</p>
        </section>

        <p v-if="selectedHistoryReturn.approval_reason && !selectedHistoryReturn.can_approve" class="text-sm text-slate-500 dark:text-slate-400">
          {{ selectedHistoryReturn.approval_reason }}
        </p>
      </div>

      <template #footer>
        <div class="flex flex-wrap justify-end gap-2">
          <button class="btn-secondary" @click="returnDetailOpen = false">Tutup</button>
          <button v-if="selectedHistoryReturn?.can_reject" class="btn-danger" :disabled="approvalBusy" @click="openRejectReturn">Tolak</button>
          <button v-if="selectedHistoryReturn?.can_approve" class="btn-primary" :disabled="approvalBusy" @click="approveHistoryReturn">
            {{ approvalBusy ? 'Memproses...' : 'Setujui & Kirim QC' }}
          </button>
        </div>
      </template>
    </AppModal>

    <AppModal
      :open="rejectReturnOpen"
      title="Tolak Retur Canvas"
      description="Penolakan tidak mengubah stok Canvas maupun stok gudang."
      size="md"
      @close="rejectReturnOpen = false"
    >
      <label class="block">
        <span class="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Catatan Penolakan</span>
        <textarea v-model="rejectionNote" class="field min-h-28" maxlength="1000" placeholder="Jelaskan alasan penolakan..." />
      </label>
      <template #footer>
        <div class="flex justify-end gap-2">
          <button class="btn-secondary" :disabled="approvalBusy" @click="rejectReturnOpen = false">Batal</button>
          <button class="btn-danger" :disabled="approvalBusy || rejectionNote.trim().length < 3" @click="submitRejectReturn">
            {{ approvalBusy ? 'Memproses...' : 'Simpan Penolakan' }}
          </button>
        </div>
      </template>
    </AppModal>
  </div>
</template>
