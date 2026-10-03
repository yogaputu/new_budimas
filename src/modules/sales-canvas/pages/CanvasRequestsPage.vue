<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import {
  confirmCanvasRequest,
  createCanvasRequest,
  getCanvasRequestDetail,
  getCanvasRequestProducts,
  getCanvasRequests,
  getCanvasSalesList,
  rejectCanvasRequest,
  updateCanvasRequest
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
import {
  formatCurrency,
  formatDate,
  getCurrentUserId,
  resolveCanvasRequestStatus
} from '@/modules/sales-canvas/utils/canvasFormat';
import {
  canvasPieces,
  canvasUomValue,
  formatCanvasQty,
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
  status: '',
  tanggal_request: '',
  search: ''
});

const requestForm = reactive({
  id_produk: '',
  qty_uom1: 0,
  qty_uom2: 0,
  qty_uom3: 0
});

const requestItems = ref([]);

const rows = ref([]);
const detailRows = ref([]);
const salesRows = ref([]);
const branchRows = ref([]);
const companyRows = ref([]);
const principalRows = ref([]);
const productRows = ref([]);
const selectedRow = ref(null);
const createOpen = ref(false);
const editingRequestId = ref('');
const editingRequestContext = ref(null);
const loading = ref(false);
const refsLoading = ref(false);
const productLoading = ref(false);
const detailLoading = ref(false);
const submitting = ref(false);
const confirming = ref(false);
const rejecting = ref(false);
const rejectOpen = ref(false);
const rejectionNote = ref('');
const errorMessage = ref('');
const successMessage = ref('');
const summaryMeta = ref({});
let salesOptionsLoadKey = 0;
let productLoadKey = 0;
let rowsLoadKey = 0;
let detailLoadKey = 0;

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

const companyOptions = computed(() =>
  {
    const allowedCompanyIds = companyIdsForBranch(filters.id_cabang);
    return companyRows.value
      .filter((item) => filters.id_cabang && allowedCompanyIds.includes(String(item.id)))
      .map((item) => ({
        value: String(item.id),
        label: `${item.kode || '-'} - ${item.nama || item.nama_perusahaan || 'Perusahaan'}`
      }));
  }
);

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

const productOptions = computed(() =>
  productRows.value.map((item) => ({
    value: String(item.id),
    label: `${item.nama_produk || 'Produk'} | Stok ${Number(item.stock_gudang || 0).toLocaleString('id-ID')} pcs`
  }))
);

const validRequestItems = computed(() =>
  requestItems.value.filter((item) =>
    item.id_produk &&
    canvasPieces(getSelectedProduct(item.id_produk), item.qty_uom1, item.qty_uom2, item.qty_uom3) > 0
  )
);

const statusOptions = [
  { value: '', label: 'Semua Status' },
  { value: '1', label: 'Request' },
  { value: '2', label: 'Approved' },
  { value: '3', label: 'Closed' },
  { value: '4', label: 'Rejected' }
];

const summaryCards = computed(() => {
  const total = rows.value.length;
  const approved = rows.value.filter((item) => Number(item.status) === 2).length;
  const pending = rows.value.filter((item) => Number(item.status) === 1).length;
  const nominal = rows.value.reduce((sum, item) => sum + Number(item.total_request || 0), 0);

  return [
    { label: 'Total Request', value: String(total) },
    { label: 'Menunggu', value: String(pending) },
    { label: 'Approved', value: String(approved) },
    { label: 'Total Nilai', value: formatCurrency(nominal) },
    { label: 'Plafon Sales', value: formatCurrency(summaryMeta.value?.plafon_limit || 0) },
    { label: 'Sisa Plafon', value: formatCurrency(summaryMeta.value?.sisa_plafon || 0) }
  ];
});

const tableRows = computed(() =>
  rows.value
    .filter((item) => {
      const query = filters.search.trim().toLowerCase();
      if (!query) return true;

      return [
        item.nama_sales,
        item.nama_principal,
        item.tanggal_request,
        item.total_request,
        item.status,
        resolveCanvasRequestStatus(item.status).text
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query));
    })
    .map((item) => ({
      ...item,
      sales_label: item.nama_sales || '-',
      principal_label: item.nama_principal || '-',
      tanggal_label: formatDate(item.tanggal_request),
      total_label: formatCurrency(item.total_request),
      status_label: resolveCanvasRequestStatus(item.status),
      plafon_label: formatCurrency(item.plafon_limit)
    }))
);

const detailTableRows = computed(() =>
  detailRows.value.map((item) => ({
    ...item,
    product_label: item.nama_produk || '-',
    principal_label: item.nama_principal || '-',
    qty_label: formatQtyBreakdown(item),
    qty_total_label: `${Number(item.qty_request_today || item.qty_request || 0).toLocaleString('id-ID')} pcs`,
    stock_label: `${Number(item.stock_gudang || 0)} pcs`,
    uom_label: [item.uom3_nama, item.uom2_nama, item.uom1_nama].filter(Boolean).join(' / ') || '-',
    harga_label: formatCurrency(item.harga_per_uom1 || item.harga_beli || 0)
  }))
);

function formatQtyBreakdown(item) {
  return formatCanvasQty(item, item, { separator: ' + ' });
}

const canConfirmSelectedRequest = computed(() => {
  if (!selectedRow.value) return false;
  return Number(selectedRow.value.status || 0) === 1 && selectedRow.value.can_approve === true;
});

const canRejectSelectedRequest = computed(() => {
  if (!selectedRow.value) return false;
  return Number(selectedRow.value.status || 0) === 1 && selectedRow.value.can_reject === true;
});

const canEditSelectedRequest = computed(() =>
  Boolean(selectedRow.value?.id) && Number(selectedRow.value.status || 0) === 1
);

const isEditingRequest = computed(() => Boolean(editingRequestId.value));

function updateFilters(nextFilters) {
  const previousBranch = filters.id_cabang;
  const previousCompany = filters.id_perusahaan;
  const previousPrincipal = filters.id_principal;
  Object.assign(filters, nextFilters || {});

  if (previousBranch !== filters.id_cabang) syncCompanyFromBranch();
  if (previousCompany !== filters.id_perusahaan) {
    filters.id_principal = '';
    resetSalesFilter();
  }
  if (previousPrincipal !== filters.id_principal) resetSalesFilter();
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
  filters.status = '';
  filters.tanggal_request = '';
  filters.search = '';
  if (filters.id_cabang) syncCompanyFromBranch();
  if (shouldLockBusinessScope.value && fallbackCompanyId.value) filters.id_perusahaan = String(fallbackCompanyId.value);
  if (canUseLoginScope.value && fallbackSalesId.value) filters.id_sales = String(fallbackSalesId.value);
  loadSalesOptions();
  loadRows();
}

function resetRequestForm() {
  requestForm.id_produk = '';
  requestForm.qty_uom1 = 0;
  requestForm.qty_uom2 = 0;
  requestForm.qty_uom3 = 0;
  requestItems.value = [createBlankRequestItem()];
}

function clearEditingRequest() {
  editingRequestId.value = '';
  editingRequestContext.value = null;
}

function closeRequestModal() {
  createOpen.value = false;
  clearEditingRequest();
}

function clearPrincipalDependentState({ closeCreateModal = false } = {}) {
  salesOptionsLoadKey += 1;
  productLoadKey += 1;
  rowsLoadKey += 1;
  detailLoadKey += 1;
  salesRows.value = [];
  productRows.value = [];
  rows.value = [];
  summaryMeta.value = {};
  selectedRow.value = null;
  detailRows.value = [];
  loading.value = false;
  productLoading.value = false;
  detailLoading.value = false;
  resetRequestForm();
  if (closeCreateModal) closeRequestModal();
}

function createBlankRequestItem() {
  return {
    id_produk: '',
    qty_uom1: 0,
    qty_uom2: 0,
    qty_uom3: 0
  };
}

function getSelectedProduct(idProduk) {
  return productRows.value.find((item) => String(item.id) === String(idProduk));
}

function isRequestUomEnabled(item, level) {
  const product = getSelectedProduct(item?.id_produk);
  return Boolean(product) && isCanvasUomEnabled(product, level);
}

function requestUomLabel(item, level) {
  const product = getSelectedProduct(item?.id_produk);
  return formatCanvasUomLabel(product, level);
}

function updateRequestProduct(item, productId) {
  item.id_produk = String(productId || '');
  const product = getSelectedProduct(item.id_produk);
  Object.assign(item, normalizeCanvasUomValues(product, {
    qty_uom1: 0,
    qty_uom2: 0,
    qty_uom3: 0
  }));
}

function updateRequestQty(item, level, value) {
  const product = getSelectedProduct(item?.id_produk);
  item[`qty_uom${level}`] = canvasUomValue(product, level, value);
}

function addRequestItem() {
  requestItems.value.push(createBlankRequestItem());
}

function removeRequestItem(index) {
  requestItems.value.splice(index, 1);
  if (!requestItems.value.length) {
    addRequestItem();
  }
}

async function loadRefs() {
  refsLoading.value = true;
  try {
    const [branchResponse, companyResponse, principalResponse] = await Promise.allSettled([getBranches(), getCompanies(), getPrincipals()]);
    const errors = [];

    if (branchResponse.status === 'fulfilled') {
      branchRows.value = normalizeList(unwrapResponse(branchResponse.value));
    } else {
      branchRows.value = [];
      errors.push(`Cabang: ${normalizeError(branchResponse.reason)}`);
    }

    if (companyResponse.status === 'fulfilled') {
      companyRows.value = normalizeList(unwrapResponse(companyResponse.value));
    } else {
      companyRows.value = [];
      errors.push(`Perusahaan: ${normalizeError(companyResponse.reason)}`);
    }

    if (principalResponse.status === 'fulfilled') {
      principalRows.value = normalizeList(unwrapResponse(principalResponse.value));
    } else {
      principalRows.value = [];
      errors.push(`Principal: ${normalizeError(principalResponse.reason)}`);
    }

    if (errors.length) {
      errorMessage.value = `Sebagian filter belum termuat. ${errors.join(' | ')}`;
    }

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

async function loadProducts(context = {}) {
  const principalId = context.id_principal || filters.id_principal;
  const salesId = context.id_sales || filters.id_sales;
  if (!principalId || !salesId || !userId.value) {
    productRows.value = [];
    return;
  }

  const loadKey = ++productLoadKey;
  const scope = [principalId, salesId, userId.value].map((value) => String(value || '')).join(':');
  productLoading.value = true;
  try {
    const response = await getCanvasRequestProducts(userId.value, {
      id_sales: salesId,
      id_principal: principalId,
      limit: 500
    });
    if (loadKey !== productLoadKey || scope !== [principalId, salesId, userId.value].map((value) => String(value || '')).join(':')) return;
    productRows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    if (loadKey !== productLoadKey) return;
    productRows.value = [];
    errorMessage.value = normalizeError(error, 'Gagal memuat produk canvas.');
  } finally {
    if (loadKey === productLoadKey) productLoading.value = false;
  }
}

async function loadRows() {
  if (!userId.value) {
    errorMessage.value = 'User login tidak memiliki ID untuk memuat Sales Canvas.';
    return;
  }

  const loadKey = ++rowsLoadKey;
  const scope = [filters.id_principal, filters.id_sales, filters.status, filters.tanggal_request].map((value) => String(value || '')).join(':');
  loading.value = true;
  errorMessage.value = '';

  try {
    const response = await getCanvasRequests(userId.value, {
      id_principal: filters.id_principal || undefined,
      id_sales: filters.id_sales || undefined,
      status: filters.status || undefined,
      tanggal_request: filters.tanggal_request || undefined,
      limit: 100,
      page: 1
    });
    const payload = unwrapResponse(response);
    if (loadKey !== rowsLoadKey || scope !== [filters.id_principal, filters.id_sales, filters.status, filters.tanggal_request].map((value) => String(value || '')).join(':')) return;
    rows.value = normalizeList(payload);
    summaryMeta.value = payload || {};
  } catch (error) {
    if (loadKey !== rowsLoadKey) return;
    rows.value = [];
    errorMessage.value = normalizeError(error, 'Gagal memuat Request Canvas.');
  } finally {
    if (loadKey === rowsLoadKey) loading.value = false;
  }
}

async function selectRow(row) {
  const loadKey = ++detailLoadKey;
  selectedRow.value = row;
  detailRows.value = [];
  rejectOpen.value = false;
  rejectionNote.value = '';
  detailLoading.value = true;

  try {
    const response = await getCanvasRequestDetail(userId.value, row.id, row.tanggal_request, {
      id_sales: row.id_sales || filters.id_sales || undefined,
      id_principal: row.id_principal || filters.id_principal || undefined
    });
    if (loadKey !== detailLoadKey || String(selectedRow.value?.id || '') !== String(row.id || '')) return;
    detailRows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    if (loadKey !== detailLoadKey) return;
    errorMessage.value = normalizeError(error, 'Gagal memuat detail Request Canvas.');
  } finally {
    if (loadKey === detailLoadKey) detailLoading.value = false;
  }
}

async function openCreateModal() {
  if (!filters.id_principal || !filters.id_sales) {
    errorMessage.value = 'Pilih Cabang, Perusahaan, Principal, dan Sales Canvas terlebih dahulu.';
    return;
  }

  successMessage.value = '';
  errorMessage.value = '';
  clearEditingRequest();
  resetRequestForm();
  createOpen.value = true;
  await loadProducts();
}

async function openEditModal() {
  if (!canEditSelectedRequest.value || !selectedRow.value) {
    errorMessage.value = 'Hanya Request Canvas yang masih berstatus Pengajuan yang dapat diedit.';
    return;
  }

  const request = selectedRow.value;
  const context = {
    id_principal: request.id_principal || filters.id_principal,
    id_sales: request.id_sales || filters.id_sales
  };
  if (!context.id_principal || !context.id_sales) {
    errorMessage.value = 'Konteks principal atau sales untuk Request Canvas belum tersedia.';
    return;
  }

  errorMessage.value = '';
  successMessage.value = '';
  await loadProducts(context);

  if (!detailRows.value.length) {
    const loadKey = ++detailLoadKey;
    detailLoading.value = true;
    try {
      const response = await getCanvasRequestDetail(userId.value, request.id, request.tanggal_request, context);
      if (loadKey !== detailLoadKey || String(selectedRow.value?.id || '') !== String(request.id || '')) return;
      detailRows.value = normalizeList(unwrapResponse(response));
    } catch (error) {
      errorMessage.value = normalizeError(error, 'Gagal memuat detail Request Canvas untuk diedit.');
      return;
    } finally {
      if (loadKey === detailLoadKey) detailLoading.value = false;
    }
  }

  const nextItems = detailRows.value
    .map((item) => {
      const productId = item.id_produk || item.id;
      const product = getSelectedProduct(productId);
      if (!product) return null;
      return {
        id_produk: String(productId),
        ...normalizeCanvasUomValues(product, item)
      };
    })
    .filter(Boolean);

  if (!nextItems.length) {
    errorMessage.value = 'Produk Request Canvas tidak tersedia pada principal yang dipilih. Muat ulang lalu coba lagi.';
    return;
  }

  editingRequestId.value = String(request.id);
  editingRequestContext.value = context;
  requestItems.value = nextItems;
  selectedRow.value = null;
  createOpen.value = true;
}

async function submitRequest() {
  const context = editingRequestContext.value || {
    id_principal: filters.id_principal,
    id_sales: filters.id_sales
  };
  if (!context.id_principal || !context.id_sales) {
    errorMessage.value = 'Pilih principal dan sales canvas terlebih dahulu.';
    return;
  }

  submitting.value = true;
  errorMessage.value = '';
  successMessage.value = '';

  try {
    const payload = {
      id: userId.value,
      id_user: userId.value,
      id_sales: context.id_sales,
      id_principal: context.id_principal,
      items: validRequestItems.value.map((item) => ({
        id_produk: item.id_produk,
        ...normalizeCanvasUomValues(getSelectedProduct(item.id_produk), item)
      }))
    };
    if (isEditingRequest.value) {
      await updateCanvasRequest({
        ...payload,
        canvas_request_id: editingRequestId.value
      });
      successMessage.value = `${validRequestItems.value.length} produk Canvas Request berhasil diperbarui.`;
    } else {
      await createCanvasRequest(payload);
      successMessage.value = `${validRequestItems.value.length} produk canvas request berhasil disimpan.`;
    }
    closeRequestModal();
    await loadRows();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Gagal menyimpan canvas request.');
  } finally {
    submitting.value = false;
  }
}

async function approveSelectedRequest() {
  if (!selectedRow.value?.id) return;

  confirming.value = true;
  errorMessage.value = '';
  successMessage.value = '';

  try {
    await confirmCanvasRequest({
      canvas_request_id: selectedRow.value.id,
      id: userId.value,
      id_user: userId.value,
      id_principal: selectedRow.value.id_principal || filters.id_principal || undefined
    });
    successMessage.value = 'Canvas request berhasil dikonfirmasi.';
    closeRequestDetail();
    await loadRows();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Gagal mengonfirmasi Request Canvas.');
  } finally {
    confirming.value = false;
  }
}

function closeRequestDetail() {
  selectedRow.value = null;
  detailRows.value = [];
  rejectOpen.value = false;
  rejectionNote.value = '';
}

function openRejectPanel() {
  if (!canRejectSelectedRequest.value) {
    errorMessage.value = 'Anda tidak berwenang menolak Request Canvas ini.';
    return;
  }
  errorMessage.value = '';
  rejectOpen.value = true;
  rejectionNote.value = '';
}

function closeRejectPanel() {
  rejectOpen.value = false;
  rejectionNote.value = '';
}

async function rejectSelectedRequest() {
  if (!selectedRow.value?.id || !canRejectSelectedRequest.value) return;

  const note = rejectionNote.value.trim();
  if (note.length < 3) {
    errorMessage.value = 'Catatan penolakan minimal 3 karakter.';
    return;
  }

  rejecting.value = true;
  errorMessage.value = '';
  successMessage.value = '';

  try {
    await rejectCanvasRequest({
      canvas_request_id: selectedRow.value.id,
      rejection_note: note
    });
    successMessage.value = 'Canvas request ditolak. Stok gudang dan stok canvas tidak berubah.';
    closeRequestDetail();
    await loadRows();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Gagal menolak Request Canvas.');
  } finally {
    rejecting.value = false;
  }
}

function buildRequestDocumentHtml(title, rowsForPrint = detailTableRows.value) {
  const selected = selectedRow.value || {};
  const rowsHtml = rowsForPrint.map((item, index) => `
    <tr>
      <td>${index + 1}</td>
      <td>${item.product_label || '-'}</td>
      <td>${item.principal_label || '-'}</td>
      <td>${item.qty_label || '-'}</td>
      <td>${item.qty_total_label || '-'}</td>
      <td>${item.stock_label || '-'}</td>
    </tr>
  `).join('');

  return `
    <html>
      <head>
        <title>${title}</title>
        <style>
          body { font-family: Arial, sans-serif; color: #111827; padding: 24px; }
          h1 { font-size: 20px; margin: 0 0 6px; }
          .meta { margin: 0 0 18px; font-size: 12px; color: #475569; }
          table { width: 100%; border-collapse: collapse; font-size: 12px; }
          th, td { border: 1px solid #94a3b8; padding: 8px; text-align: left; }
          th { background: #e2e8f0; }
          .signatures { display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; margin-top: 48px; text-align: center; font-size: 12px; }
          .line { margin-top: 64px; border-top: 1px solid #111827; padding-top: 6px; }
        </style>
      </head>
      <body>
        <h1>${title}</h1>
        <p class="meta">Sales: ${selected.nama_sales || '-'} | Tanggal Request: ${formatDate(selected.tanggal_request)} | Status: ${resolveCanvasRequestStatus(selected.status).text}</p>
        <table>
          <thead>
            <tr>
              <th>No</th>
              <th>Produk</th>
              <th>Principal</th>
              <th>Qty Request</th>
              <th>Total PCS</th>
              <th>Stok Gudang</th>
            </tr>
          </thead>
          <tbody>${rowsHtml || '<tr><td colspan="6">Tidak ada detail produk.</td></tr>'}</tbody>
        </table>
        <div class="signatures">
          <div><div class="line">Admin / Gudang</div></div>
          <div><div class="line">Sales Canvas</div></div>
          <div><div class="line">Penerima</div></div>
        </div>
      </body>
    </html>
  `;
}

function printRequestDocument(title) {
  const popup = window.open('', '_blank', 'width=960,height=720');
  if (!popup) {
    errorMessage.value = 'Popup browser diblokir. Izinkan popup untuk mencetak dokumen canvas.';
    return;
  }
  popup.document.write(buildRequestDocumentHtml(title));
  popup.document.close();
  popup.focus();
  popup.print();
}

watch(
  () => filters.id_cabang,
  (value, previous) => {
    if (String(value || '') === String(previous || '')) return;
    syncCompanyFromBranch();
    loadSalesOptions();
  }
);

watch(
  () => filters.id_perusahaan,
  (value, previous) => {
    if (String(value || '') === String(previous || '')) return;
    filters.id_principal = '';
    resetSalesFilter();
    loadSalesOptions();
  }
);

watch(
  () => filters.id_principal,
  (value, previous) => {
    if (String(value || '') === String(previous || '')) return;
    resetSalesFilter();
    clearPrincipalDependentState({ closeCreateModal: true });
    loadSalesOptions();
  }
);

watch(
  () => filters.id_sales,
  () => {
    productLoadKey += 1;
    productRows.value = [];
    productLoading.value = false;
    resetRequestForm();
    if (isEditingRequest.value) closeRequestModal();
  }
);

onMounted(async () => {
  await loadRefs();
  await loadSalesOptions();
  await loadRows();
});
</script>

<template>
  <div>
    <PageHeader
      title="Request Canvas"
      description="Monitoring dan input request barang canvas sales dengan filter Cabang -> Perusahaan -> Principal -> Sales."
    >
      <div class="flex gap-2">
        <button class="btn-secondary" :disabled="loading" @click="loadRows">Reload</button>
        <button class="btn-primary" :disabled="refsLoading" @click="openCreateModal">+ Tambah Request</button>
      </div>
    </PageHeader>

    <section class="panel-muted p-4">
      <div>
        <h2 class="text-sm font-black text-slate-950 dark:text-white">Filter Request Canvas</h2>
        <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">Urutan filter dikunci: Cabang -> Perusahaan -> Principal -> Sales Canvas.</p>
      </div>

      <div class="mt-4 grid min-w-0 gap-3 lg:grid-cols-2 2xl:grid-cols-4">
        <AppSearchSelect v-model="filters.id_cabang" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="refsLoading || (shouldLockBusinessScope && !!fallbackBranchId)" empty-text="Cabang belum tersedia." @update:model-value="selectBranch" />
        <AppSearchSelect v-model="filters.id_perusahaan" label="Perusahaan" :placeholder="filters.id_cabang ? 'Pilih perusahaan' : 'Pilih cabang dulu'" :options="companyOptions" :disabled="!filters.id_cabang || (shouldLockBusinessScope && !!fallbackCompanyId)" empty-text="Perusahaan belum tersedia untuk cabang ini." @update:model-value="selectCompany" />
        <AppSearchSelect v-model="filters.id_principal" label="Principal" :placeholder="filters.id_perusahaan ? 'Pilih principal' : 'Pilih perusahaan dulu'" :options="principalOptions" :disabled="!filters.id_perusahaan" empty-text="Principal belum tersedia." @update:model-value="selectPrincipal" />
        <AppSearchSelect v-model="filters.id_sales" label="Sales Canvas" :placeholder="filters.id_principal ? 'Pilih sales canvas' : 'Pilih principal dulu'" :options="salesOptions" :disabled="!filters.id_principal || (canUseLoginScope && !!fallbackSalesId)" empty-text="Sales canvas belum tersedia." />
        <label class="block">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">Status</span>
          <select v-model="filters.status" class="field">
            <option v-for="option in statusOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </label>
        <label class="block">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">Tanggal Request</span>
          <input v-model="filters.tanggal_request" type="date" class="field" />
        </label>
        <label class="block min-w-0 lg:col-span-2">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">Cari</span>
          <input v-model="filters.search" class="field" placeholder="Sales, tanggal, total, status" />
        </label>
      </div>

      <div class="mt-4 flex flex-wrap gap-2">
        <button class="btn-primary" :disabled="loading || refsLoading" @click="loadRows">Terapkan</button>
        <button class="btn-secondary" @click="resetFilters">Reset</button>
      </div>
    </section>

    <div class="mt-5 grid gap-3 md:grid-cols-3 xl:grid-cols-6">
      <div v-for="card in summaryCards" :key="card.label" class="panel p-4">
        <p class="text-xs font-bold uppercase tracking-[0.25em] text-slate-500 dark:text-slate-400">{{ card.label }}</p>
        <p class="mt-3 text-xl font-black text-slate-950 dark:text-white">{{ card.value }}</p>
      </div>
    </div>

    <div v-if="successMessage" class="mt-4 rounded-2xl border border-emerald-300 bg-emerald-50 px-4 py-3 text-sm font-semibold text-emerald-700 dark:border-emerald-500/40 dark:bg-emerald-950/40 dark:text-emerald-200">
      {{ successMessage }}
    </div>

    <div v-if="errorMessage" class="mt-4 rounded-2xl border border-rose-300 bg-rose-50 px-4 py-3 text-sm font-semibold text-rose-700 dark:border-rose-500/40 dark:bg-rose-950/40 dark:text-rose-200">
      {{ errorMessage }}
    </div>

    <section class="mt-6">
      <AppTable
        :columns="[
          { key: 'sales_label', label: 'Sales' },
          { key: 'principal_label', label: 'Principal' },
          { key: 'tanggal_label', label: 'Tanggal' },
          { key: 'total_label', label: 'Total Request' },
          { key: 'plafon_label', label: 'Plafon' },
          { key: 'status_label', label: 'Status' }
        ]"
        :rows="tableRows"
        :loading="loading"
        :clickable-rows="true"
        :selected-key="selectedRow?.id || ''"
        empty-message="Belum ada canvas request untuk filter ini."
        @row-click="selectRow"
      />
    </section>

    <AppModal
      :open="createOpen"
      :title="isEditingRequest ? 'Edit Request Canvas' : 'Tambah Request Canvas'"
      :description="isEditingRequest ? 'Ubah produk atau quantity sebelum Request Canvas disetujui.' : 'Input beberapa produk canvas sekaligus berdasarkan sales terpilih.'"
      size="6xl"
      @close="closeRequestModal"
    >
      <div class="space-y-4">
        <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-300">
          {{ isEditingRequest
            ? 'Request hanya dapat diedit sebelum disetujui. Setelah disetujui, perubahan stok dan transfer harus diproses melalui alur operasional.'
            : 'Tambahkan satu atau beberapa produk. Jika produk yang sama dipilih lebih dari sekali, backend akan menggabungkan quantity-nya agar detail tidak dobel.' }}
        </div>

        <div
          v-for="(item, index) in requestItems"
          :key="index"
          class="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-700 dark:bg-slate-950/30"
        >
          <div class="mb-3 flex items-center justify-between gap-3">
            <p class="text-sm font-black text-slate-950 dark:text-white">Produk {{ index + 1 }}</p>
            <button class="btn-secondary px-3 py-2 text-xs" :disabled="requestItems.length === 1" @click="removeRequestItem(index)">Hapus</button>
          </div>

          <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <AppSearchSelect
              v-model="item.id_produk"
              class="md:col-span-2 xl:col-span-4"
              label="Produk"
              placeholder="Pilih produk canvas"
              :options="productOptions"
              :disabled="productLoading"
              empty-text="Produk canvas belum tersedia."
              @update:model-value="updateRequestProduct(item, $event)"
            />
            <label class="block">
              <span class="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">{{ requestUomLabel(item, 1) }}</span>
              <input :value="item.qty_uom1" type="number" min="0" step="1" inputmode="numeric" class="field mt-1" :disabled="!isRequestUomEnabled(item, 1)" @input="updateRequestQty(item, 1, $event.target.value)" />
            </label>
            <label class="block">
              <span class="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">{{ requestUomLabel(item, 2) }}</span>
              <input :value="item.qty_uom2" type="number" min="0" step="1" inputmode="numeric" class="field mt-1" :disabled="!isRequestUomEnabled(item, 2)" @input="updateRequestQty(item, 2, $event.target.value)" />
            </label>
            <label class="block">
              <span class="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">{{ requestUomLabel(item, 3) }}</span>
              <input :value="item.qty_uom3" type="number" min="0" step="1" inputmode="numeric" class="field mt-1" :disabled="!isRequestUomEnabled(item, 3)" @input="updateRequestQty(item, 3, $event.target.value)" />
            </label>
            <div class="rounded-2xl border border-slate-200 p-4 text-sm dark:border-slate-700">
              <p class="font-bold text-slate-900 dark:text-white">Info Produk</p>
              <p class="mt-1 text-slate-500 dark:text-slate-400">Stok gudang: {{ Number(getSelectedProduct(item.id_produk)?.stock_gudang || 0).toLocaleString('id-ID') }} pcs</p>
              <p class="text-slate-500 dark:text-slate-400">Harga: {{ formatCurrency(getSelectedProduct(item.id_produk)?.harga_per_uom1 || getSelectedProduct(item.id_produk)?.harga_beli || 0) }}</p>
            </div>
          </div>
        </div>

        <button class="btn-secondary" type="button" @click="addRequestItem">+ Tambah Baris Produk</button>
      </div>
      <template #footer>
        <button class="btn-secondary" @click="closeRequestModal">Batal</button>
        <button class="btn-primary" :disabled="submitting || !validRequestItems.length" @click="submitRequest">
          {{ submitting ? 'Menyimpan...' : (isEditingRequest ? 'Simpan Perubahan' : 'Simpan Request') }}
        </button>
      </template>
    </AppModal>

    <AppModal
      :open="!!selectedRow"
      title="Detail Request Canvas"
      :description="selectedRow ? `Request tanggal ${formatDate(selectedRow.tanggal_request)}` : ''"
      size="6xl"
      @close="closeRequestDetail"
    >
      <div v-if="rejectOpen" class="rounded-2xl border border-rose-200 bg-rose-50 p-4 dark:border-rose-500/40 dark:bg-rose-950/20">
        <h4 class="text-base font-black text-rose-900 dark:text-rose-100">Tolak Request Canvas</h4>
        <p class="mt-1 text-sm text-rose-800 dark:text-rose-200">Request akan berstatus Ditolak dan tidak ada stok gudang maupun stok canvas yang diubah.</p>
        <label class="mt-4 block">
          <span class="text-xs font-bold uppercase tracking-wide text-rose-800 dark:text-rose-200">Catatan Penolakan</span>
          <textarea v-model="rejectionNote" class="field mt-1 min-h-28" maxlength="1000" placeholder="Tulis alasan penolakan minimal 3 karakter" :disabled="rejecting" />
        </label>
        <div class="mt-4 flex flex-wrap justify-end gap-2">
          <button class="btn-secondary" :disabled="rejecting" @click="closeRejectPanel">Kembali</button>
          <button class="btn-danger" :disabled="rejecting || rejectionNote.trim().length < 3" @click="rejectSelectedRequest">
            {{ rejecting ? 'Menolak...' : 'Konfirmasi Tolak' }}
          </button>
        </div>
      </div>
      <AppTable
        v-else
        :columns="[
          { key: 'product_label', label: 'Produk' },
          { key: 'principal_label', label: 'Principal' },
          { key: 'qty_label', label: 'Qty Request' },
          { key: 'qty_total_label', label: 'Total Pcs' },
          { key: 'stock_label', label: 'Stok Gudang' },
          { key: 'uom_label', label: 'UOM' },
          { key: 'harga_label', label: 'Harga' }
        ]"
        :rows="detailTableRows"
        :loading="detailLoading"
        :paginated="true"
        empty-message="Detail produk request belum tersedia."
      />
      <template #footer>
        <div v-if="!rejectOpen" class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div class="flex flex-wrap gap-2">
            <button class="btn-secondary" :disabled="detailLoading" @click="printRequestDocument('Transfer to Canvas (TTK)')">Cetak TTK</button>
            <button class="btn-secondary" :disabled="detailLoading" @click="printRequestDocument('Picking List Canvas')">Picking List</button>
            <button class="btn-secondary" :disabled="detailLoading" @click="printRequestDocument('Proof of Transfer (POD)')">POD</button>
          </div>
          <div class="flex flex-wrap justify-end gap-2">
            <button class="btn-secondary" :disabled="confirming || rejecting" @click="closeRequestDetail">Tutup</button>
            <button v-if="canEditSelectedRequest" class="btn-secondary" :disabled="detailLoading || confirming || rejecting" @click="openEditModal">
              Edit Request
            </button>
            <button v-if="canRejectSelectedRequest" class="btn-danger" :disabled="detailLoading || confirming || rejecting" @click="openRejectPanel">
              Tolak Request
            </button>
            <button v-if="canConfirmSelectedRequest" class="btn-primary" :disabled="confirming || detailLoading || rejecting" @click="approveSelectedRequest">
              {{ confirming ? 'Memproses...' : 'Konfirmasi Request' }}
            </button>
          </div>
        </div>
        <div v-else class="flex justify-end">
          <button class="btn-secondary" :disabled="rejecting" @click="closeRejectPanel">Kembali ke Detail</button>
        </div>
      </template>
    </AppModal>
  </div>
</template>
