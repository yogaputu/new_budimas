<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  createCanvasOrder,
  getCanvasEligibleVouchers,
  getCanvasOrderDetail,
  getCanvasRequestDetail,
  getCanvasRequests,
  getCanvasOrders,
  getCanvasVoucherUsages,
  getCanvasPaymentHistory,
  getCanvasSalesList,
  getCanvasCustomers,
  submitCanvasPayment,
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
  resolveCanvasOrderStatus
} from '@/modules/sales-canvas/utils/canvasFormat';
import {
  canvasPieces,
  canvasUomValue,
  distributeCanvasPieces,
  formatCanvasQty as formatCanvasUomQty,
  formatCanvasUomLabel,
  isCanvasUomEnabled,
  normalizeCanvasUomValues
} from '@/modules/sales-canvas/utils/canvasUom';

const authStore = useAuthStore();
const route = useRoute();
const router = useRouter();

const filters = reactive({
  id_cabang: '',
  id_perusahaan: '',
  id_principal: '',
  id_sales: '',
  status: '',
  tanggal_order: '',
  search: ''
});

const orderForm = reactive({
  nama_customer: '',
  kode_customer: '',
  id_customer: '',
  customer_label: '',
  id_canvas_request: '',
  product_search: ''
});

const voucherSelections = reactive({
  2: '',
  3: ''
});

const paymentForm = reactive({
  jumlah_setoran: '',
  tipe_setoran: 'tunai',
  keterangan: ''
});

const rows = ref([]);
const detailRows = ref([]);
const paymentRows = ref([]);
const voucherUsageRows = ref([]);
const salesRows = ref([]);
const branchRows = ref([]);
const companyRows = ref([]);
const principalRows = ref([]);
const approvedRequestRows = ref([]);
const customerRows = ref([]);
const orderItems = ref([]);
const voucherRows = ref([]);
const voucherPreview = ref(null);
const selectedRow = ref(null);
const createOpen = ref(false);
const loading = ref(false);
const refsLoading = ref(false);
const requestLoading = ref(false);
const detailLoading = ref(false);
const paymentLoading = ref(false);
const voucherUsageLoading = ref(false);
const submitting = ref(false);
const submittingPayment = ref(false);
const voucherLoading = ref(false);
const customerLoading = ref(false);
const errorMessage = ref('');
const successMessage = ref('');
const voucherErrorMessage = ref('');
const voucherPreviewSignature = ref('');
const appliedVoucherRouteKey = ref('');
let voucherPreviewTimer = null;
let salesOptionsLoadKey = 0;
let approvedRequestsLoadKey = 0;
let approvedRequestDetailLoadKey = 0;
let ordersLoadKey = 0;
let selectedOrderDetailLoadKey = 0;
let customerLoadKey = 0;
let activePaymentAttempt = { signature: '', id: '' };

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

const customerOptions = computed(() =>
  customerRows.value
    .map((item) => {
      const id = item.id_customer ?? item.id ?? '';
      const code = item.kode_customer || item.kode || '-';
      const name = item.nama_customer || item.nama || 'Customer';
      const branch = item.nama_cabang || item.cabang_nama || '';
      return {
        value: String(id),
        label: `${code} - ${name}${branch ? ` | ${branch}` : ''}`,
        raw: item
      };
    })
    .filter((item) => item.value)
);

const requestOptions = computed(() =>
  approvedRequestRows.value.map((item) => ({
    value: String(item.id),
    label: `REQ-${item.id} | ${item.nama_principal || 'Principal'} | ${formatDate(item.tanggal_request)} | ${Number(item.available_qty_pcs || 0).toLocaleString('id-ID')} PCS siap | ${formatCurrency(item.total_request || 0)}`
  }))
);

function normalizeCanvasCustomer(row = {}) {
  const id = row.id_customer ?? row.id ?? '';
  const kode = String(row.kode_customer || row.kode || '').trim();
  const nama = String(row.nama_customer || row.nama || '').trim();
  return {
    ...row,
    id_customer: String(id || ''),
    kode_customer: kode,
    nama_customer: nama
  };
}

function applyOrderCustomer(customer) {
  const normalized = normalizeCanvasCustomer(customer);
  orderForm.id_customer = normalized.id_customer;
  orderForm.kode_customer = normalized.kode_customer;
  orderForm.nama_customer = normalized.nama_customer;
  const option = customerOptions.value.find((item) => String(item.value) === normalized.id_customer);
  orderForm.customer_label = option?.label || `${normalized.kode_customer || '-'} - ${normalized.nama_customer || 'Customer'}`;
}

function selectOrderCustomer(value) {
  const selected = customerRows.value.find((item) => String(item.id_customer || item.id || '') === String(value || ''));
  if (selected) {
    applyOrderCustomer(selected);
    return;
  }

  orderForm.id_customer = '';
  orderForm.kode_customer = '';
  orderForm.nama_customer = '';
  orderForm.customer_label = '';
}

async function loadCanvasCustomers(search = '') {
  if (!filters.id_principal || !filters.id_sales || !userId.value) {
    customerRows.value = [];
    return;
  }

  const loadKey = ++customerLoadKey;
  const scope = [
    filters.id_cabang,
    filters.id_perusahaan,
    filters.id_principal,
    filters.id_sales,
    userId.value,
    String(search || '').trim()
  ].map((value) => String(value || '')).join(':');

  customerLoading.value = true;
  try {
    const response = await getCanvasCustomers({
      id: userId.value,
      id_user: userId.value,
      id_cabang: filters.id_cabang,
      id_perusahaan: filters.id_perusahaan,
      id_principal: filters.id_principal,
      id_sales: filters.id_sales,
      search: String(search || '').trim(),
      limit: 50
    });
    const currentScope = [
      filters.id_cabang,
      filters.id_perusahaan,
      filters.id_principal,
      filters.id_sales,
      userId.value,
      String(search || '').trim()
    ].map((value) => String(value || '')).join(':');
    if (loadKey !== customerLoadKey || scope !== currentScope) return;

    const nextRows = normalizeList(unwrapResponse(response)).map(normalizeCanvasCustomer);
    const selectedId = String(orderForm.id_customer || '');
    const selected = customerRows.value.find((item) => String(item.id_customer || item.id || '') === selectedId);
    customerRows.value = selected && !nextRows.some((item) => String(item.id_customer || item.id || '') === selectedId)
      ? [selected, ...nextRows]
      : nextRows;
  } catch (error) {
    if (loadKey !== customerLoadKey) return;
    customerRows.value = [];
    errorMessage.value = normalizeError(error, 'Gagal memuat customer terdaftar untuk Canvas.');
  } finally {
    if (loadKey === customerLoadKey) customerLoading.value = false;
  }
}

const selectedCanvasRequest = computed(() =>
  approvedRequestRows.value.find((item) => String(item.id) === String(orderForm.id_canvas_request))
);

const orderItemRows = computed(() => {
  const query = orderForm.product_search.trim().toLowerCase();
  return orderItems.value
    .filter((item) => {
      if (!query) return true;
      return [
        item.nama_produk,
        item.nama_principal,
        item.uom1_nama,
        item.uom2_nama,
        item.uom3_nama,
        item.id_produk,
        item.id
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query));
    })
    .map((item) => {
    const qtyPieces = calculateItemPieces(item, item.qty_uom1, item.qty_uom2, item.qty_uom3);
    const subtotal = qtyPieces * Number(item.harga_per_uom1 || item.harga_beli || 0);
    item.request_qty_label = formatCanvasQty(item, item.request_qty_uom1, item.request_qty_uom2, item.request_qty_uom3);
    item.stock_label = `${orderItemAvailablePieces(item).toLocaleString('id-ID')} PCS`;
    item.order_qty_pieces = qtyPieces;
    item.subtotal_order = subtotal;
    item.subtotal_label = formatCurrency(subtotal);
    return item;
    });
});

const orderDraftTotal = computed(() =>
  orderItemRows.value.reduce((sum, item) => sum + Number(item.subtotal_order || 0), 0)
);

const hasOrderQty = computed(() =>
  orderItems.value.some((item) => canvasPieces(item, item.qty_uom1, item.qty_uom2, item.qty_uom3) > 0)
);

const voucherRowsByType = computed(() => [2, 3].reduce((groups, type) => {
  groups[type] = voucherRows.value.filter((item) =>
    Number(item.tipe_voucher) === type && isCanvasVoucherScope(item)
  );
  return groups;
}, { 2: [], 3: [] }));

const selectedVoucherSelections = computed(() =>
  [2, 3]
    .map((tipeVoucher) => ({
      tipe_voucher: tipeVoucher,
      id: Number(voucherSelections[tipeVoucher] || 0)
    }))
    .filter((item) => item.id > 0)
);

const selectedVoucherRows = computed(() =>
  selectedVoucherSelections.value
    .map((selection) => voucherRowsByType.value[selection.tipe_voucher]?.find((item) =>
      Number(item.id) === Number(selection.id)
    ))
    .filter(Boolean)
);

const voucherPreviewSummary = computed(() => {
  const payload = voucherPreview.value || {};
  const source = payload.selected_quote || payload.quote || payload.order_preview || payload.preview || payload.context?.preview || payload.context || payload;
  const subtotal = readPreviewNumber(source, ['subtotal', 'sub_total', 'total_before_discount', 'subtotal_order']);
  const discount = readPreviewNumber(source, ['total_diskon', 'total_discount', 'discount_total', 'diskon']);
  const total = readPreviewNumber(source, ['total_order', 'total_after_discount', 'grand_total', 'total']);
  const hasServerValue = [subtotal, discount, total].some((value) => value !== null);

  return {
    available: hasServerValue,
    subtotal,
    discount,
    total
  };
});

const voucherPreviewCurrent = computed(() =>
  Boolean(voucherPreviewSignature.value)
  && voucherPreviewSignature.value === buildVoucherPreviewSignature(buildVoucherPreviewPayload())
);

const statusOptions = [
  { value: '', label: 'Semua Status' },
  { value: '1', label: 'Draft' },
  { value: '2', label: 'Berjalan' },
  { value: '3', label: 'Menunggu Finance' },
  { value: '4', label: 'Closed' },
  { value: '5', label: 'Batal' }
];

const summaryCards = computed(() => {
  const total = rows.value.length;
  const closed = rows.value.filter((item) => Number(item.status_order) === 4).length;
  const berjalan = rows.value.filter((item) => Number(item.status_order) === 2).length;
  const nominal = rows.value.reduce((sum, item) => sum + Number(item.total_order || 0), 0);
  const paid = rows.value.reduce((sum, item) => sum + Number(item.total_dibayarkan || 0), 0);

  return [
    { label: 'Total Order', value: String(total) },
    { label: 'Berjalan', value: String(berjalan) },
    { label: 'Closed', value: String(closed) },
    { label: 'Nilai Order', value: formatCurrency(nominal) },
    { label: 'Terbayar', value: formatCurrency(paid) }
  ];
});

const tableRows = computed(() =>
  rows.value
    .filter((item) => {
      const query = filters.search.trim().toLowerCase();
      if (!query) return true;

      return [item.nama_sales, item.nama_principal, item.nama_customer, item.tanggal_order, item.total_order, resolveCanvasOrderStatus(item.status_order).text]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query));
    })
    .map((item) => ({
      ...item,
      sales_label: item.nama_sales || '-',
      principal_label: item.nama_principal || '-',
      customer_label: item.nama_customer || '-',
      tanggal_label: formatDate(item.tanggal_order),
      total_label: formatCurrency(item.total_order),
      paid_label: formatCurrency(item.total_dibayarkan),
      sisa_label: formatCurrency(Number(item.total_order || 0) - Number(item.total_dibayarkan || 0)),
      status_label: resolveCanvasOrderStatus(item.status_order)
    }))
);

const detailTableRows = computed(() =>
  detailRows.value.map((item) => ({
    ...item,
    product_label: item.nama_produk || '-',
    qty_label: formatCanvasUomQty(item, item),
    harga_label: formatCurrency(item.harga_per_uom1 || item.harga_beli || 0),
    diskon_label: formatCurrency(item.total_diskon || 0),
    subtotal_label: formatCurrency(item.subtotal_harga || item.jumlah_harga || 0)
  }))
);

const detailTotals = computed(() => {
  const subtotal = detailRows.value.reduce((sum, item) => sum + Number(item.subtotal_harga || item.jumlah_harga || 0), 0);
  const diskon = detailRows.value.reduce((sum, item) => sum + Number(item.total_diskon || 0), 0);
  const total = Number(selectedRow.value?.total_order || 0) || detailRows.value.reduce((sum, item) => sum + Number(item.jumlah_harga || item.total || 0), 0);
  return { subtotal, diskon, total };
});

const paymentTableRows = computed(() =>
  paymentRows.value.map((item, index) => ({
    ...item,
    row_id: item.id || `${item.tanggal_input || 'payment'}-${index}`,
    tanggal_label: formatDate(item.tanggal_input || item.created_at),
    nominal_label: formatCurrency(item.jumlah_setoran || item.nominal || 0),
    tipe_label: (item.tipe_setoran ?? item.tipe) === null || (item.tipe_setoran ?? item.tipe) === undefined || (item.tipe_setoran ?? item.tipe) === ''
      ? '-'
      : Number(item.tipe_setoran ?? item.tipe) === 2 ? 'Non Tunai / Transfer' : 'Tunai',
    user_label: item.nama_user || item.user_nama || '-'
  }))
);

const voucherUsageTableRows = computed(() =>
  voucherUsageRows.value.map((item, index) => ({
    ...item,
    row_id: item.id || `${item.tipe_voucher || 'voucher'}-${item.id_voucher || item.voucher_id || index}`,
    tipe_label: `Voucher ${item.tipe_voucher || '-'}`,
    voucher_label: [item.kode_voucher, item.nama_voucher].filter(Boolean).join(' · ') || '-',
    subtotal_label: formatCurrency(item.subtotal_eligible || 0),
    discount_label: formatCurrency(item.discount_amount || item.total_diskon || 0),
    tanggal_label: formatDate(item.created_at || item.tanggal_input)
  }))
);

const selectedOrderTagihan = computed(() => Number(selectedRow.value?.total_order || detailTotals.value.total || 0));
const selectedOrderPaid = computed(() =>
  paymentRows.value.reduce((sum, item) => sum + Number(item.jumlah_setoran || item.nominal || 0), 0)
);
const selectedOrderSisa = computed(() => Math.max(selectedOrderTagihan.value - selectedOrderPaid.value, 0));

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
  filters.tanggal_order = '';
  filters.search = '';
  if (filters.id_cabang) syncCompanyFromBranch();
  if (shouldLockBusinessScope.value && fallbackCompanyId.value) filters.id_perusahaan = String(fallbackCompanyId.value);
  if (canUseLoginScope.value && fallbackSalesId.value) filters.id_sales = String(fallbackSalesId.value);
  loadSalesOptions();
  loadRows();
}

function resetPaymentForm() {
  paymentForm.jumlah_setoran = '';
  paymentForm.tipe_setoran = 'tunai';
  paymentForm.keterangan = '';
  activePaymentAttempt = { signature: '', id: '' };
}

function fillRemainingPayment() {
  paymentForm.jumlah_setoran = String(selectedOrderSisa.value || '');
}

function calculateItemPieces(item, qtyUom1 = 0, qtyUom2 = 0, qtyUom3 = 0) {
  return canvasPieces(item, qtyUom1, qtyUom2, qtyUom3);
}

function formatCanvasQty(item, qtyUom1 = 0, qtyUom2 = 0, qtyUom3 = 0) {
  return formatCanvasUomQty(item, { qty_uom1: qtyUom1, qty_uom2: qtyUom2, qty_uom3: qtyUom3 });
}

function normalizeOrderItem(row) {
  const requestQty = normalizeCanvasUomValues(row, row);
  return {
    ...row,
    id_produk: row.id_produk || row.id,
    request_qty_uom1: requestQty.qty_uom1,
    request_qty_uom2: requestQty.qty_uom2,
    request_qty_uom3: requestQty.qty_uom3,
    qty_uom1: 0,
    qty_uom2: 0,
    qty_uom3: 0
  };
}

function fillAllRequestQty() {
  orderItems.value = orderItems.value.map((item) => ({
    ...item,
    ...distributeCanvasPieces(item, orderItemAvailablePieces(item))
  }));
}

function isOrderUomEnabled(item, level) {
  return isCanvasUomEnabled(item, level);
}

function orderUomLabel(item, level) {
  return formatCanvasUomLabel(item, level);
}

function updateOrderQty(item, level, value) {
  item[`qty_uom${level}`] = canvasUomValue(item, level, value);
}

function orderItemAvailablePieces(item) {
  const rawAvailable = item?.available_order_qty_pcs;
  const explicitAvailable = Number(rawAvailable);
  if (rawAvailable != null && rawAvailable !== '' && Number.isFinite(explicitAvailable)) {
    return Math.max(0, Math.trunc(explicitAvailable));
  }
  return Math.min(
    Math.max(0, Number(item?.stock_canvas || 0)),
    canvasPieces(item, item?.request_qty_uom1, item?.request_qty_uom2, item?.request_qty_uom3)
  );
}

function orderQuantityValidationError() {
  const invalid = orderItems.value.find((item) => {
    const entered = canvasPieces(item, item.qty_uom1, item.qty_uom2, item.qty_uom3);
    return entered > orderItemAvailablePieces(item);
  });

  if (!invalid) return '';
  return `Qty ${invalid.nama_produk || invalid.id_produk} melebihi sisa request approved / stok canvas (${orderItemAvailablePieces(invalid).toLocaleString('id-ID')} PCS).`;
}

function readPreviewNumber(source, keys = []) {
  if (!source || typeof source !== 'object') return null;
  for (const key of keys) {
    const value = Number(source[key]);
    if (Number.isFinite(value)) return value;
  }
  return null;
}

function isVoucherEligible(row) {
  return row?.eligible === true
    || row?.eligible === 1
    || String(row?.eligible || '').toLowerCase() === 'true';
}

function normalizeVoucherChannelScope(row) {
  const scope = String(row?.channel_scope || row?.voucher_scope || '').trim().toLowerCase();
  // Pre-migration responses have no scope and keep legacy `both` behaviour.
  return ['promo', 'canvas', 'both'].includes(scope) ? scope : 'both';
}

function isCanvasVoucherScope(row) {
  return ['canvas', 'both'].includes(normalizeVoucherChannelScope(row));
}

function voucherDiscountLabel(row) {
  const preview = row?.discount_preview;
  if (typeof preview === 'string' && preview.trim()) return preview;
  if (typeof preview === 'number') return formatCurrency(preview);
  if (preview && typeof preview === 'object') {
    const label = preview.label || preview.text || preview.description;
    if (label) return String(label);
    const nominal = readPreviewNumber(preview, ['total_diskon', 'total_discount', 'discount', 'nominal', 'nilai']);
    if (nominal !== null) return formatCurrency(nominal);
  }
  return '-';
}

function voucherReason(row) {
  const reason = row?.reason || row?.message || row?.eligibility_reason || row?.keterangan;
  if (reason) return String(reason);
  return isVoucherEligible(row) ? 'Memenuhi syarat berdasarkan data order saat ini.' : 'Belum memenuhi syarat voucher.';
}

function voucherScopeLabel(row) {
  const channelScope = normalizeVoucherChannelScope(row);
  if (channelScope === 'canvas') return 'Canvas';
  if (channelScope === 'both') return 'Promo All-In & Canvas';
  if (channelScope === 'promo') return 'Promo All-In';
  const scope = row?.scope;
  if (typeof scope === 'string' && scope.trim()) return scope;
  if (Array.isArray(scope)) return scope.filter(Boolean).join(' • ');
  if (scope && typeof scope === 'object') {
    return scope.label || scope.description || Object.values(scope).filter((value) => typeof value === 'string' && value).join(' • ');
  }
  return row?.nama_principal || 'Voucher Canvas';
}

function buildVoucherPreviewItems() {
  return orderItems.value.reduce((items, item) => {
    const quantities = normalizeCanvasUomValues(item, item);
    if (canvasPieces(item, quantities.qty_uom1, quantities.qty_uom2, quantities.qty_uom3) <= 0) return items;

    items.push({
      id_produk: Number(item.id_produk || item.id || 0),
      qty_uom1: Number(quantities.qty_uom1 || 0),
      qty_uom2: Number(quantities.qty_uom2 || 0),
      qty_uom3: Number(quantities.qty_uom3 || 0)
    });
    return items;
  }, []).filter((item) => item.id_produk > 0);
}

function buildVoucherPreviewPayload() {
  return {
    id_user: userId.value || undefined,
    id_sales: filters.id_sales || undefined,
    id_principal: selectedCanvasRequest.value?.id_principal || filters.id_principal || undefined,
    id_customer: orderForm.id_customer || undefined,
    kode_customer: orderForm.kode_customer?.trim() || undefined,
    nama_customer: orderForm.nama_customer?.trim() || undefined,
    list_items: buildVoucherPreviewItems(),
    voucher_selections: selectedVoucherSelections.value.map((item) => ({
      tipe_voucher: Number(item.tipe_voucher),
      id: Number(item.id)
    }))
  };
}

function buildVoucherPreviewSignature(payload = buildVoucherPreviewPayload()) {
  return JSON.stringify({
    id_user: String(payload.id_user || ''),
    id_sales: String(payload.id_sales || ''),
    id_principal: String(payload.id_principal || ''),
    id_customer: String(payload.id_customer || ''),
    kode_customer: String(payload.kode_customer || '').trim().toUpperCase(),
    nama_customer: String(payload.nama_customer || '').trim().toUpperCase(),
    list_items: (payload.list_items || []).map((item) => ({
      id_produk: Number(item.id_produk || 0),
      qty_uom1: Number(item.qty_uom1 || 0),
      qty_uom2: Number(item.qty_uom2 || 0),
      qty_uom3: Number(item.qty_uom3 || 0)
    })),
    voucher_selections: (payload.voucher_selections || []).map((item) => ({
      tipe_voucher: Number(item.tipe_voucher || 0),
      id: Number(item.id || 0)
    }))
  });
}

function clearVoucherSelections() {
  voucherSelections[2] = '';
  voucherSelections[3] = '';
}

function selectedVouchersAreConfirmed() {
  if (!selectedVoucherSelections.value.length) return true;
  if (!voucherPreviewCurrent.value) return false;

  const rowsConfirmed = selectedVoucherSelections.value.every((selection) => voucherRows.value.some((row) =>
    Number(row.tipe_voucher) === Number(selection.tipe_voucher)
    && Number(row.id) === Number(selection.id)
    && isCanvasVoucherScope(row)
    && isVoucherEligible(row)
  ));
  if (!rowsConfirmed) return false;

  const quote = voucherPreview.value?.selected_quote || voucherPreview.value?.quote;
  return !quote || isVoucherEligible(quote);
}

function applyVoucherFromRoute() {
  const type = Number(route.query.voucher_type || route.query.tipe_voucher || 0);
  const id = Number(route.query.voucher_id || route.query.id_voucher || 0);
  if (![2, 3].includes(type) || id <= 0) return;

  const routeKey = `${type}:${id}`;
  if (appliedVoucherRouteKey.value === routeKey) return false;
  appliedVoucherRouteKey.value = routeKey;

  const row = voucherRows.value.find((item) =>
    Number(item.tipe_voucher) === type
    && Number(item.id) === id
    && isCanvasVoucherScope(item)
  );
  let selected = false;
  if (row && isVoucherEligible(row)) {
    voucherSelections[type] = String(id);
    selected = true;
  } else if (row) {
    voucherErrorMessage.value = `Voucher ${row.kode_voucher || row.nama_voucher || id} belum dapat dipakai: ${voucherReason(row)}`;
  }

  const nextQuery = { ...route.query };
  delete nextQuery.voucher_type;
  delete nextQuery.tipe_voucher;
  delete nextQuery.voucher_id;
  delete nextQuery.id_voucher;
  router.replace({ query: nextQuery }).catch(() => {});
  return selected;
}

async function loadEligibleVouchers({ preserveSelection = true } = {}) {
  const payload = buildVoucherPreviewPayload();
  const signature = buildVoucherPreviewSignature(payload);
  voucherErrorMessage.value = '';

  if (!payload.id_user || !payload.id_principal || !payload.id_sales || !payload.list_items.length) {
    voucherRows.value = [];
    voucherPreview.value = null;
    voucherPreviewSignature.value = '';
    if (!preserveSelection) clearVoucherSelections();
    return false;
  }

  voucherLoading.value = true;
  try {
    const response = await getCanvasEligibleVouchers(payload);
    const result = unwrapResponse(response) || {};
    voucherRows.value = normalizeList(result.rows || result.vouchers || result.eligible_vouchers || result)
      .filter((row) => isCanvasVoucherScope(row));
    voucherPreview.value = result;
    voucherPreviewSignature.value = signature;

    [2, 3].forEach((type) => {
      const selectedId = Number(voucherSelections[type] || 0);
      if (!selectedId) return;
      const selected = voucherRows.value.find((row) => Number(row.tipe_voucher) === type && Number(row.id) === selectedId);
      if (!selected || !isCanvasVoucherScope(selected) || !isVoucherEligible(selected)) voucherSelections[type] = '';
    });

    const selectedQuote = result.selected_quote || result.quote;
    if (selectedVoucherSelections.value.length && selectedQuote && !isVoucherEligible(selectedQuote)) {
      voucherErrorMessage.value = selectedQuote.reason || 'Kombinasi voucher tidak memenuhi syarat untuk order saat ini.';
    }

    if (applyVoucherFromRoute()) {
      return loadEligibleVouchers({ preserveSelection: true });
    }
    return true;
  } catch (error) {
    voucherRows.value = [];
    voucherPreview.value = null;
    voucherPreviewSignature.value = '';
    voucherErrorMessage.value = normalizeError(error, 'Voucher Canvas belum dapat dicek ke server.');
    if (!preserveSelection) clearVoucherSelections();
    return false;
  } finally {
    voucherLoading.value = false;
  }
}

function scheduleVoucherPreview() {
  window.clearTimeout(voucherPreviewTimer);
  voucherPreviewSignature.value = '';
  voucherPreview.value = null;
  clearVoucherSelections();
  voucherPreviewTimer = window.setTimeout(() => {
    loadEligibleVouchers({ preserveSelection: false });
  }, 350);
}

async function toggleVoucherSelection(row) {
  const type = Number(row?.tipe_voucher || 0);
  if (![2, 3].includes(type)) return;
  if (!voucherPreviewCurrent.value || !isVoucherEligible(row)) {
    voucherErrorMessage.value = 'Voucher harus lolos pengecekan server untuk customer dan qty order saat ini sebelum dipilih.';
    return;
  }
  voucherSelections[type] = Number(voucherSelections[type] || 0) === Number(row.id) ? '' : String(row.id);
  await loadEligibleVouchers({ preserveSelection: true });
}

function resetOrderForm() {
  orderForm.nama_customer = '';
  orderForm.kode_customer = '';
  orderForm.id_customer = '';
  orderForm.customer_label = '';
  orderForm.id_canvas_request = '';
  orderForm.product_search = '';
  approvedRequestRows.value = [];
  customerRows.value = [];
  orderItems.value = [];
  voucherRows.value = [];
  voucherPreview.value = null;
  voucherPreviewSignature.value = '';
  voucherErrorMessage.value = '';
  clearVoucherSelections();
}

function clearOrderPrincipalDependentState({ closeCreateModal = false } = {}) {
  salesOptionsLoadKey += 1;
  approvedRequestsLoadKey += 1;
  approvedRequestDetailLoadKey += 1;
  ordersLoadKey += 1;
  selectedOrderDetailLoadKey += 1;
  customerLoadKey += 1;
  window.clearTimeout(voucherPreviewTimer);
  salesRows.value = [];
  rows.value = [];
  detailRows.value = [];
  paymentRows.value = [];
  voucherUsageRows.value = [];
  selectedRow.value = null;
  loading.value = false;
  requestLoading.value = false;
  detailLoading.value = false;
  paymentLoading.value = false;
  voucherUsageLoading.value = false;
  voucherLoading.value = false;
  customerLoading.value = false;
  resetPaymentForm();
  resetOrderForm();
  if (closeCreateModal) createOpen.value = false;
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
    if (shouldLockBusinessScope.value && fallbackCompanyId.value) {
      filters.id_perusahaan = String(fallbackCompanyId.value);
    }
    if (canUseLoginScope.value && fallbackSalesId.value) {
      filters.id_sales = String(fallbackSalesId.value);
    }
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

async function loadApprovedRequests() {
  if (!filters.id_principal || !filters.id_sales || !userId.value) {
    approvedRequestDetailLoadKey += 1;
    approvedRequestRows.value = [];
    orderItems.value = [];
    orderForm.id_canvas_request = '';
    return;
  }

  const loadKey = ++approvedRequestsLoadKey;
  approvedRequestDetailLoadKey += 1;
  const scope = [filters.id_principal, filters.id_sales, userId.value].map((value) => String(value || '')).join(':');
  approvedRequestRows.value = [];
  orderItems.value = [];
  orderForm.id_canvas_request = '';
  requestLoading.value = true;
  try {
    const response = await getCanvasRequests(userId.value, {
      id_principal: filters.id_principal,
      id_sales: filters.id_sales,
      status: 2,
      eligible_only: 1,
      limit: 50,
      page: 1
    });
    if (loadKey !== approvedRequestsLoadKey || scope !== [filters.id_principal, filters.id_sales, userId.value].map((value) => String(value || '')).join(':')) return;
    approvedRequestRows.value = normalizeList(unwrapResponse(response));
    if (!approvedRequestRows.value.length) {
      orderForm.id_canvas_request = '';
      orderItems.value = [];
      errorMessage.value = 'Belum ada request canvas approved yang masih memiliki sisa approval dan stok canvas.';
      return;
    }
    const existingSelection = String(orderForm.id_canvas_request || '');
    orderForm.id_canvas_request = approvedRequestRows.value.some((item) => String(item.id) === existingSelection)
      ? existingSelection
      : String(approvedRequestRows.value[0].id);
    await loadApprovedRequestDetail();
  } catch (error) {
    if (loadKey !== approvedRequestsLoadKey) return;
    approvedRequestRows.value = [];
    orderItems.value = [];
    errorMessage.value = normalizeError(error, 'Gagal memuat canvas request approved.');
  } finally {
    if (loadKey === approvedRequestsLoadKey) requestLoading.value = false;
  }
}

async function loadApprovedRequestDetail() {
  if (!orderForm.id_canvas_request || !filters.id_principal || !userId.value) {
    approvedRequestDetailLoadKey += 1;
    orderItems.value = [];
    return;
  }

  const loadKey = ++approvedRequestDetailLoadKey;
  const requestId = String(orderForm.id_canvas_request);
  const selectedPrincipalId = selectedCanvasRequest.value?.id_principal || filters.id_principal;
  const scope = [selectedPrincipalId, filters.id_sales, userId.value, requestId].map((value) => String(value || '')).join(':');
  requestLoading.value = true;
  try {
    const requestRow = selectedCanvasRequest.value;
    const response = await getCanvasRequestDetail(
      userId.value,
      orderForm.id_canvas_request,
      requestRow?.tanggal_request,
      {
        id_sales: filters.id_sales,
        id_principal: selectedPrincipalId,
        eligible_only: 1
      }
    );
    if (loadKey !== approvedRequestDetailLoadKey || scope !== [selectedCanvasRequest.value?.id_principal || filters.id_principal, filters.id_sales, userId.value, String(orderForm.id_canvas_request)].map((value) => String(value || '')).join(':')) return;
    orderItems.value = normalizeList(unwrapResponse(response))
      .map(normalizeOrderItem)
      .filter((item) => orderItemAvailablePieces(item) > 0);
  } catch (error) {
    if (loadKey !== approvedRequestDetailLoadKey) return;
    orderItems.value = [];
    errorMessage.value = normalizeError(error, 'Gagal memuat detail request approved.');
  } finally {
    if (loadKey === approvedRequestDetailLoadKey) requestLoading.value = false;
  }
}

async function loadRows() {
  if (!userId.value) {
    errorMessage.value = 'User login tidak memiliki ID untuk memuat Order Canvas.';
    return;
  }

  const loadKey = ++ordersLoadKey;
  const scope = [filters.id_principal, filters.id_sales, filters.status, filters.tanggal_order].map((value) => String(value || '')).join(':');
  loading.value = true;
  errorMessage.value = '';
  successMessage.value = '';

  try {
    const response = await getCanvasOrders(userId.value, {
      id_principal: filters.id_principal || undefined,
      id_sales: filters.id_sales || undefined,
      status: filters.status || undefined,
      status_order: filters.status || undefined,
      tanggal_order: filters.tanggal_order || undefined,
      limit: 100,
      page: 1
    });
    if (loadKey !== ordersLoadKey || scope !== [filters.id_principal, filters.id_sales, filters.status, filters.tanggal_order].map((value) => String(value || '')).join(':')) return;
    rows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    if (loadKey !== ordersLoadKey) return;
    rows.value = [];
    errorMessage.value = normalizeError(error, 'Gagal memuat Order Canvas.');
  } finally {
    if (loadKey === ordersLoadKey) loading.value = false;
  }
}

async function selectRow(row) {
  const loadKey = ++selectedOrderDetailLoadKey;
  selectedRow.value = row;
  detailRows.value = [];
  paymentRows.value = [];
  voucherUsageRows.value = [];
  errorMessage.value = '';
  resetPaymentForm();
  detailLoading.value = true;
  paymentLoading.value = true;
  voucherUsageLoading.value = true;

  const [detailResult, paymentResult, voucherUsageResult] = await Promise.allSettled([
    getCanvasOrderDetail(row.id, {
      id: userId.value || undefined,
      id_user: userId.value || undefined,
      id_principal: row.id_principal || filters.id_principal || undefined
    }),
    getCanvasPaymentHistory(row.id, {
      id: userId.value || undefined,
      id_user: userId.value || undefined,
      id_principal: row.id_principal || filters.id_principal || undefined
    }),
    getCanvasVoucherUsages(row.id, {
      id: userId.value || undefined,
      id_user: userId.value || undefined,
      id_principal: row.id_principal || filters.id_principal || undefined
    })
  ]);

  if (loadKey !== selectedOrderDetailLoadKey || String(selectedRow.value?.id || '') !== String(row.id || '')) return;

  if (detailResult.status === 'fulfilled') {
    detailRows.value = normalizeList(unwrapResponse(detailResult.value));
  } else {
    errorMessage.value = normalizeError(detailResult.reason, 'Gagal memuat detail Order Canvas.');
  }

  if (paymentResult.status === 'fulfilled') {
    paymentRows.value = normalizeList(unwrapResponse(paymentResult.value));
  } else if (!errorMessage.value) {
    errorMessage.value = normalizeError(paymentResult.reason, 'Gagal memuat riwayat pembayaran Canvas.');
  }

  // Order lama tetap dapat dibuka apabila tabel audit voucher belum dimigrasikan.
  if (voucherUsageResult.status === 'fulfilled') {
    voucherUsageRows.value = normalizeList(unwrapResponse(voucherUsageResult.value));
  }

  if (loadKey === selectedOrderDetailLoadKey) {
    detailLoading.value = false;
    paymentLoading.value = false;
    voucherUsageLoading.value = false;
  }
}

async function openCreateModal() {
  if (!filters.id_principal || !filters.id_sales) {
    errorMessage.value = 'Pilih Cabang, Perusahaan, Principal, dan Sales Canvas terlebih dahulu.';
    return;
  }

  successMessage.value = '';
  errorMessage.value = '';
  resetOrderForm();
  createOpen.value = true;
  await Promise.all([
    loadApprovedRequests(),
    loadCanvasCustomers()
  ]);
}

async function submitOrder() {
  if (!filters.id_principal || !filters.id_sales) {
    errorMessage.value = 'Pilih principal dan sales canvas terlebih dahulu.';
    return;
  }
  if (!orderForm.id_canvas_request) {
    errorMessage.value = 'Pilih Request Canvas yang masih siap dijual terlebih dahulu.';
    return;
  }
  if (!orderForm.id_customer) {
    errorMessage.value = 'Pilih customer terdaftar terlebih dahulu.';
    return;
  }

  const requestPrincipalId = selectedCanvasRequest.value?.id_principal || filters.id_principal;
  if (!requestPrincipalId || String(requestPrincipalId) !== String(filters.id_principal)) {
    errorMessage.value = 'Request Canvas tidak sesuai dengan principal yang dipilih. Muat ulang request lalu pilih kembali.';
    return;
  }

  const validationError = orderQuantityValidationError();
  if (validationError) {
    errorMessage.value = validationError;
    return;
  }

  const payloadItems = orderItems.value.reduce((items, item) => {
    const quantities = normalizeCanvasUomValues(item, item);
    if (canvasPieces(item, quantities.qty_uom1, quantities.qty_uom2, quantities.qty_uom3) > 0) {
      items.push({ id_produk: item.id_produk || item.id, ...quantities });
    }
    return items;
  }, []);

  if (!payloadItems.length) {
    errorMessage.value = 'Isi minimal satu qty order pada UOM yang tersedia.';
    return;
  }

  if (selectedVoucherSelections.value.length) {
    const previewLoaded = await loadEligibleVouchers({ preserveSelection: true });
    if (!previewLoaded || !selectedVouchersAreConfirmed()) {
      errorMessage.value = voucherErrorMessage.value || 'Pilihan voucher sudah tidak sesuai dengan customer atau qty order terbaru. Cek ulang voucher terlebih dahulu.';
      return;
    }
  }

  submitting.value = true;
  errorMessage.value = '';
  successMessage.value = '';

  try {
    await createCanvasOrder({
      id: userId.value,
      id_user: userId.value,
      id_sales: filters.id_sales,
      id_principal: requestPrincipalId,
      id_canvas_request: orderForm.id_canvas_request,
      nama_customer: orderForm.nama_customer,
      kode_customer: orderForm.kode_customer,
      id_customer: orderForm.id_customer || undefined,
      id_voucher_2: Number(voucherSelections[2] || 0) || null,
      id_voucher_3: Number(voucherSelections[3] || 0) || null,
      voucher_selections: selectedVoucherSelections.value.map((item) => ({
        tipe_voucher: Number(item.tipe_voucher),
        id: Number(item.id)
      })),
      list_items: payloadItems
    });
    successMessage.value = 'Canvas order berhasil disimpan.';
    createOpen.value = false;
    await loadRows();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Gagal menyimpan canvas order.');
  } finally {
    submitting.value = false;
  }
}

async function submitPayment() {
  errorMessage.value = '';
  successMessage.value = '';
  if (!selectedRow.value) {
    errorMessage.value = 'Pilih Order Canvas terlebih dahulu.';
    return;
  }

  const nominal = Number(paymentForm.jumlah_setoran || 0);
  if (!Number.isFinite(nominal) || nominal <= 0) {
    errorMessage.value = 'Nominal pembayaran harus lebih dari Rp 0.';
    return;
  }
  if (nominal > Number(selectedOrderSisa.value || 0) + 0.005) {
    errorMessage.value = 'Nominal pembayaran melebihi sisa tagihan Canvas.';
    return;
  }

  const signature = [
    selectedRow.value.id,
    nominal.toFixed(2),
    paymentForm.tipe_setoran || 'tunai'
  ].join(':');
  if (activePaymentAttempt.signature !== signature) {
    const generatedId = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `canvas-${Date.now()}-${Math.random().toString(36).slice(2, 14)}`;
    activePaymentAttempt = { signature, id: generatedId };
  }

  submittingPayment.value = true;
  try {
    await submitCanvasPayment({
      id_canvas_order: selectedRow.value.id,
      jumlah_dibayarkan: nominal,
      tipe_setoran: paymentForm.tipe_setoran,
      payment_id: activePaymentAttempt.id
    });
    activePaymentAttempt = { signature: '', id: '' };
    successMessage.value = 'Pembayaran Canvas tercatat sebagai claim sales dan menunggu Rekap pada Piutang Canvas Finance.';

    const selectedId = String(selectedRow.value.id);
    await loadRows();
    const refreshedRow = rows.value.find((row) => String(row.id) === selectedId);
    if (refreshedRow) await selectRow(refreshedRow);
  } catch (error) {
    // Keep the same payment_id for an unchanged retry.  If the server did
    // save the claim before a network timeout, it will reply idempotently
    // instead of creating a duplicate payment.
    errorMessage.value = normalizeError(error, 'Gagal menyimpan pembayaran Canvas.');
  } finally {
    submittingPayment.value = false;
  }
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function buildCanvasInvoiceHtml() {
  const order = selectedRow.value || {};
  const rowsHtml = detailTableRows.value.map((item, index) => `
    <tr>
      <td>${index + 1}</td>
      <td>${item.product_label || '-'}</td>
      <td>${item.qty_label || '-'}</td>
      <td class="right">${item.harga_label || '-'}</td>
      <td class="right">${item.diskon_label || '-'}</td>
      <td class="right">${item.subtotal_label || '-'}</td>
    </tr>
  `).join('');
  const voucherHtml = voucherUsageTableRows.value.length
    ? `<div class="meta" style="margin-bottom: 16px;"><strong>Voucher:</strong><br />${voucherUsageTableRows.value
      .map((item) => `${escapeHtml(item.tipe_label)} · ${escapeHtml(item.voucher_label)} (${escapeHtml(item.discount_label)})`)
      .join('<br />')}</div>`
    : '';

  return `
    <html>
      <head>
        <title>Faktur Kanvas</title>
        <style>
          body { font-family: Arial, sans-serif; color: #111827; padding: 24px; }
          .header { display: flex; justify-content: space-between; gap: 24px; border-bottom: 2px solid #111827; padding-bottom: 12px; margin-bottom: 16px; }
          h1 { font-size: 22px; margin: 0 0 6px; }
          .meta { font-size: 12px; color: #475569; line-height: 1.6; }
          table { width: 100%; border-collapse: collapse; font-size: 12px; }
          th, td { border: 1px solid #94a3b8; padding: 8px; text-align: left; vertical-align: top; }
          th { background: #e2e8f0; }
          .right { text-align: right; }
          .totals { width: 320px; margin-left: auto; margin-top: 16px; font-size: 13px; }
          .totals div { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #cbd5e1; }
          .signatures { display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; margin-top: 48px; text-align: center; font-size: 12px; }
          .line { margin-top: 64px; border-top: 1px solid #111827; padding-top: 6px; }
        </style>
      </head>
      <body>
        <div class="header">
          <div>
            <h1>FAKTUR PENJUALAN KANVAS</h1>
            <div class="meta">Cash only | Sales Canvas</div>
          </div>
          <div class="meta">
            <strong>No Order:</strong> CANVAS-${order.id || '-'}<br />
            <strong>Tanggal:</strong> ${formatDate(order.tanggal_order)}<br />
            <strong>Status:</strong> ${resolveCanvasOrderStatus(order.status_order).text}
          </div>
        </div>
        <div class="meta" style="margin-bottom: 16px;">
          <strong>Customer:</strong> ${order.nama_customer || '-'}<br />
          <strong>Sales:</strong> ${order.nama_sales || '-'}
        </div>
        ${voucherHtml}
        <table>
          <thead>
            <tr>
              <th>No</th>
              <th>Produk</th>
              <th>Qty</th>
              <th>Harga</th>
              <th>Diskon</th>
              <th>Subtotal</th>
            </tr>
          </thead>
          <tbody>${rowsHtml || '<tr><td colspan="6">Tidak ada detail produk.</td></tr>'}</tbody>
        </table>
        <div class="totals">
          <div><span>Subtotal</span><strong>${formatCurrency(detailTotals.value.subtotal)}</strong></div>
          <div><span>Diskon</span><strong>${formatCurrency(detailTotals.value.diskon)}</strong></div>
          <div><span>Total</span><strong>${formatCurrency(detailTotals.value.total)}</strong></div>
        </div>
        <div class="signatures">
          <div><div class="line">Sales Canvas</div></div>
          <div><div class="line">Customer</div></div>
          <div><div class="line">Admin</div></div>
        </div>
      </body>
    </html>
  `;
}

function buildPaymentReceiptHtml(row = null) {
  const order = selectedRow.value || {};
  const payment = row || paymentTableRows.value[0] || {};
  const nominal = Number(payment.jumlah_setoran || payment.nominal || paymentForm.jumlah_setoran || 0);
  const metode = payment.tipe_label || payment.tipe_setoran || paymentForm.tipe_setoran || 'Tunai';

  return `
    <html>
      <head>
        <title>Bukti Bayar Canvas</title>
        <style>
          body { font-family: Arial, sans-serif; color: #111827; padding: 24px; }
          .receipt { border: 1px solid #111827; padding: 24px; max-width: 720px; margin: auto; }
          h1 { font-size: 22px; margin: 0 0 6px; text-transform: uppercase; }
          .meta { color: #475569; font-size: 12px; line-height: 1.6; }
          .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-top: 18px; }
          .box { border: 1px solid #cbd5e1; border-radius: 10px; padding: 12px; }
          .box span { color: #64748b; display: block; font-size: 11px; font-weight: 700; text-transform: uppercase; }
          .box strong { display: block; margin-top: 6px; }
          .total { background: #ecfdf5; border-color: #10b981; font-size: 20px; }
          .signatures { display: grid; grid-template-columns: repeat(2, 1fr); gap: 48px; margin-top: 48px; text-align: center; font-size: 12px; }
          .line { margin-top: 56px; border-top: 1px solid #111827; padding-top: 6px; }
        </style>
      </head>
      <body>
        <div class="receipt">
          <h1>Bukti Bayar Canvas</h1>
          <div class="meta">No Order: CANVAS-${escapeHtml(order.id || '-')} | ${escapeHtml(formatDate(order.tanggal_order))}</div>
          <div class="grid">
            <div class="box"><span>Customer</span><strong>${escapeHtml(order.nama_customer || '-')}</strong></div>
            <div class="box"><span>Sales Canvas</span><strong>${escapeHtml(order.nama_sales || '-')}</strong></div>
            <div class="box"><span>Total Tagihan</span><strong>${escapeHtml(formatCurrency(selectedOrderTagihan.value))}</strong></div>
            <div class="box"><span>Sudah Dibayar</span><strong>${escapeHtml(formatCurrency(selectedOrderPaid.value))}</strong></div>
            <div class="box total"><span>Nominal Bayar</span><strong>${escapeHtml(formatCurrency(nominal))}</strong></div>
            <div class="box"><span>Metode</span><strong>${escapeHtml(metode)}</strong></div>
          </div>
          <div class="signatures">
            <div><div class="line">Sales Canvas</div></div>
            <div><div class="line">Customer</div></div>
          </div>
        </div>
      </body>
    </html>
  `;
}

function printCanvasInvoice() {
  const popup = window.open('', '_blank', 'width=960,height=720');
  if (!popup) {
    errorMessage.value = 'Popup browser diblokir. Izinkan popup untuk mencetak faktur kanvas.';
    return;
  }
  popup.document.write(buildCanvasInvoiceHtml());
  popup.document.close();
  popup.focus();
  popup.print();
}

function printPaymentReceipt(row = null) {
  const popup = window.open('', '_blank', 'width=760,height=900');
  if (!popup) {
    errorMessage.value = 'Popup browser diblokir. Izinkan popup untuk mencetak bukti bayar canvas.';
    return;
  }
  popup.document.write(buildPaymentReceiptHtml(row));
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
    clearOrderPrincipalDependentState({ closeCreateModal: true });
    loadSalesOptions();
  }
);

watch(
  () => filters.id_sales,
  (value, previous) => {
    if (String(value || '') === String(previous || '')) return;
    approvedRequestsLoadKey += 1;
    approvedRequestDetailLoadKey += 1;
    window.clearTimeout(voucherPreviewTimer);
    approvedRequestRows.value = [];
    orderItems.value = [];
    orderForm.id_canvas_request = '';
    voucherRows.value = [];
    voucherPreview.value = null;
    voucherPreviewSignature.value = '';
    voucherErrorMessage.value = '';
    requestLoading.value = false;
    voucherLoading.value = false;
    clearVoucherSelections();
    if (createOpen.value) createOpen.value = false;
  }
);

watch(
  () => orderForm.id_canvas_request,
  (value, previous) => {
    if (String(value || '') === String(previous || '')) return;
    loadApprovedRequestDetail();
  }
);

watch(
  () => [
    orderForm.nama_customer,
    orderForm.kode_customer,
    orderForm.id_customer,
    filters.id_principal,
    filters.id_sales,
    orderForm.id_canvas_request
  ],
  (value, previous) => {
    if (JSON.stringify(value) === JSON.stringify(previous)) return;
    scheduleVoucherPreview();
  }
);

watch(
  orderItems,
  () => {
    scheduleVoucherPreview();
  },
  { deep: true }
);

onUnmounted(() => {
  window.clearTimeout(voucherPreviewTimer);
});

onMounted(async () => {
  await loadRefs();
  await loadSalesOptions();
  await loadRows();
});
</script>

<template>
  <div>
    <PageHeader
      title="Order Canvas"
      description="Monitoring, input order, detail produk, dan pembayaran canvas dengan filter Cabang -> Perusahaan -> Principal -> Sales."
    >
      <div class="flex gap-2">
        <button class="btn-secondary" :disabled="loading" @click="loadRows">Reload</button>
        <button class="btn-primary" :disabled="refsLoading" @click="openCreateModal">+ Tambah Order</button>
      </div>
    </PageHeader>

    <section class="panel-muted p-4">
      <div>
        <h2 class="text-sm font-black text-slate-950 dark:text-white">Filter Order Canvas</h2>
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
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">Tanggal Order</span>
          <input v-model="filters.tanggal_order" type="date" class="field" />
        </label>
        <label class="block min-w-0 lg:col-span-2">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">Cari</span>
          <input v-model="filters.search" class="field" placeholder="Sales, customer, tanggal, nominal" />
        </label>
      </div>

      <div class="mt-4 flex flex-wrap gap-2">
        <button class="btn-primary" :disabled="loading || refsLoading" @click="loadRows">Terapkan</button>
        <button class="btn-secondary" @click="resetFilters">Reset</button>
      </div>
    </section>

    <div class="mt-5 grid gap-3 md:grid-cols-3 xl:grid-cols-5">
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
          { key: 'customer_label', label: 'Customer' },
          { key: 'total_label', label: 'Total Order' },
          { key: 'paid_label', label: 'Terbayar' },
          { key: 'sisa_label', label: 'Sisa' },
          { key: 'status_label', label: 'Status' }
        ]"
        :rows="tableRows"
        :loading="loading"
        :clickable-rows="true"
        :selected-key="selectedRow?.id || ''"
        empty-message="Belum ada canvas order untuk filter ini."
        @row-click="selectRow"
      />
    </section>

    <AppModal
      :open="createOpen"
      title="Tambah Order Canvas"
      description="Order hanya memakai barang dari Request Canvas yang sudah approved dan sudah menjadi stok canvas sales."
      size="7xl"
      @close="createOpen = false"
    >
      <div class="grid gap-4 md:grid-cols-2">
        <AppSearchSelect
          v-model="orderForm.id_canvas_request"
          class="md:col-span-2"
          label="Request Canvas yang Siap Dijual"
          placeholder="Pilih request approved dengan stok canvas tersedia"
          :options="requestOptions"
          :disabled="requestLoading"
          empty-text="Belum ada request approved untuk sales ini."
        />
        <AppSearchSelect
          v-model="orderForm.id_customer"
          class="md:col-span-2"
          label="Customer Terdaftar"
          placeholder="Cari kode atau nama toko/customer..."
          :options="customerOptions"
          :display-value="orderForm.customer_label"
          :loading="customerLoading"
          remote-search
          :search-debounce-ms="250"
          empty-text="Customer terdaftar tidak ditemukan pada cakupan cabang ini."
          @update:model-value="selectOrderCustomer"
          @search="loadCanvasCustomers"
        />
        <p class="-mt-2 text-xs text-slate-500 dark:text-slate-400 md:col-span-2">
          Customer dipilih dari toko yang telah terdaftar. Kode dan nama akan diambil langsung dari master customer.
        </p>
        <section class="md:col-span-2 rounded-2xl border border-violet-200 bg-violet-50/70 p-4 dark:border-violet-500/30 dark:bg-violet-950/20">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p class="font-black text-slate-950 dark:text-white">Voucher Canvas</p>
              <p class="mt-1 text-xs text-slate-600 dark:text-slate-300">
                Voucher hanya dapat dipilih setelah server memeriksa customer, cabang sales, produk, dan qty order yang diisi.
              </p>
            </div>
            <button class="btn-secondary" type="button" :disabled="voucherLoading || !hasOrderQty" @click="loadEligibleVouchers({ preserveSelection: true })">
              {{ voucherLoading ? 'Mengecek...' : 'Cek Voucher ke Server' }}
            </button>
          </div>

          <p v-if="!hasOrderQty" class="mt-4 rounded-xl border border-dashed border-violet-300 px-3 py-2 text-xs text-violet-800 dark:border-violet-400/40 dark:text-violet-200">
            Isi minimal satu qty barang terlebih dahulu untuk melihat voucher yang benar-benar memenuhi syarat.
          </p>
          <p v-if="voucherErrorMessage" class="mt-4 rounded-xl border border-rose-300 bg-rose-50 px-3 py-2 text-xs font-semibold text-rose-700 dark:border-rose-500/40 dark:bg-rose-950/30 dark:text-rose-200">
            {{ voucherErrorMessage }}
          </p>
          <p v-if="voucherLoading" class="mt-4 text-xs text-slate-500 dark:text-slate-400">Memeriksa voucher Canvas ke server…</p>
          <p v-else-if="hasOrderQty && !voucherRows.length" class="mt-4 rounded-xl border border-dashed border-slate-300 px-3 py-2 text-xs text-slate-600 dark:border-slate-700 dark:text-slate-300">
            Tidak ada voucher Canvas yang tersedia untuk data order saat ini.
          </p>

          <div v-if="voucherRows.length" class="mt-4 grid gap-3 xl:grid-cols-2">
            <section v-for="type in [2, 3]" :key="type" class="rounded-2xl border border-violet-200/80 bg-white/80 p-3 dark:border-violet-500/25 dark:bg-slate-950/40">
              <div class="flex items-center justify-between gap-3">
                <div>
                  <p class="text-xs font-black uppercase tracking-[0.18em] text-violet-700 dark:text-violet-200">Voucher {{ type }}</p>
                  <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">Pilih maksimal satu voucher per tipe.</p>
                </div>
                <span class="rounded-full px-2.5 py-1 text-xs font-bold" :class="voucherSelections[type] ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-200' : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'">
                  {{ voucherSelections[type] ? 'Dipilih' : 'Opsional' }}
                </span>
              </div>

              <div v-if="!voucherRowsByType[type].length" class="mt-3 rounded-xl border border-dashed border-slate-200 px-3 py-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
                Voucher tipe ini tidak tersedia.
              </div>
              <div v-else class="mt-3 space-y-2">
                <button
                  v-for="voucher in voucherRowsByType[type]"
                  :key="`${voucher.tipe_voucher}-${voucher.id}`"
                  type="button"
                  class="w-full rounded-xl border p-3 text-left transition"
                  :class="[
                    Number(voucherSelections[type] || 0) === Number(voucher.id)
                      ? 'border-violet-500 bg-violet-100/70 ring-2 ring-violet-300/50 dark:bg-violet-500/15 dark:ring-violet-400/25'
                      : isVoucherEligible(voucher)
                        ? 'border-slate-200 bg-white hover:border-violet-300 dark:border-slate-700 dark:bg-slate-900 dark:hover:border-violet-400/60'
                        : 'cursor-not-allowed border-slate-200 bg-slate-100/80 opacity-70 dark:border-slate-800 dark:bg-slate-950/50',
                    !voucherPreviewCurrent ? 'opacity-60' : ''
                  ]"
                  :disabled="voucherLoading || !voucherPreviewCurrent || !isVoucherEligible(voucher)"
                  @click="toggleVoucherSelection(voucher)"
                >
                  <span class="flex items-start justify-between gap-3">
                    <span>
                      <span class="block text-sm font-black text-slate-950 dark:text-white">{{ voucher.nama_voucher || voucher.kode_voucher || `Voucher ${type}` }}</span>
                      <span class="mt-1 block text-xs text-slate-500 dark:text-slate-400">{{ voucher.kode_voucher || '-' }} · {{ voucherScopeLabel(voucher) }}</span>
                    </span>
                    <span class="shrink-0 rounded-full px-2 py-1 text-xs font-black" :class="isVoucherEligible(voucher) ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-200' : 'bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-200'">
                      {{ isVoucherEligible(voucher) ? 'Memenuhi' : 'Belum memenuhi' }}
                    </span>
                  </span>
                  <span class="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs">
                    <span class="font-bold text-emerald-700 dark:text-emerald-300">Preview server: {{ voucherDiscountLabel(voucher) }}</span>
                    <span class="text-slate-500 dark:text-slate-400">{{ voucherReason(voucher) }}</span>
                  </span>
                </button>
              </div>
            </section>
          </div>

          <div v-if="voucherPreviewSummary.available" class="mt-4 grid gap-2 rounded-2xl border border-violet-200 bg-white/70 p-3 text-sm sm:grid-cols-3 dark:border-violet-500/25 dark:bg-slate-950/40">
            <div>
              <p class="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Subtotal server</p>
              <p class="mt-1 font-black text-slate-950 dark:text-white">{{ voucherPreviewSummary.subtotal === null ? '-' : formatCurrency(voucherPreviewSummary.subtotal) }}</p>
            </div>
            <div>
              <p class="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Diskon server</p>
              <p class="mt-1 font-black text-emerald-700 dark:text-emerald-300">{{ voucherPreviewSummary.discount === null ? '-' : formatCurrency(voucherPreviewSummary.discount) }}</p>
            </div>
            <div>
              <p class="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">{{ selectedVoucherSelections.length ? 'Total setelah voucher' : 'Total order server' }}</p>
              <p class="mt-1 font-black text-violet-700 dark:text-violet-200">{{ voucherPreviewSummary.total === null ? '-' : formatCurrency(voucherPreviewSummary.total) }}</p>
            </div>
          </div>
        </section>
        <div class="md:col-span-2 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm dark:border-slate-700 dark:bg-slate-950/50">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p class="font-bold text-slate-900 dark:text-white">Barang dari request approved</p>
              <p class="mt-1 text-slate-500 dark:text-slate-400">
                Hanya produk dengan sisa approval dan stok canvas yang masih tersedia ditampilkan dari {{ selectedCanvasRequest ? `REQ-${selectedCanvasRequest.id}` : 'request terpilih' }}.
              </p>
            </div>
            <button class="btn-secondary" type="button" :disabled="!orderItems.length" @click="fillAllRequestQty">
              Pakai Semua Qty Tersedia
            </button>
          </div>
          <label class="mt-4 block">
            <span class="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Cari Barang</span>
            <input
              v-model="orderForm.product_search"
              class="field mt-1"
              placeholder="Cari nama barang, principal, atau UOM..."
            />
          </label>
          <div class="mt-4 overflow-x-auto rounded-2xl border border-slate-200 dark:border-slate-700">
            <table class="min-w-full text-left text-sm">
              <thead class="bg-slate-100 text-xs uppercase tracking-[0.18em] text-slate-500 dark:bg-slate-900 dark:text-slate-400">
                <tr>
                  <th class="px-4 py-3">Produk</th>
                  <th class="px-4 py-3">Qty Siap Dijual</th>
                  <th class="px-4 py-3">Siap Order (PCS)</th>
                  <th class="px-4 py-3">Order UOM Besar</th>
                  <th class="px-4 py-3">Order UOM Tengah</th>
                  <th class="px-4 py-3">Order UOM Kecil</th>
                  <th class="px-4 py-3 text-right">Subtotal Est.</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-200 dark:divide-slate-800">
                <tr v-if="requestLoading">
                  <td colspan="7" class="px-4 py-8 text-center text-slate-500 dark:text-slate-400">Memuat detail request...</td>
                </tr>
                <tr v-else-if="!orderItemRows.length">
                  <td colspan="7" class="px-4 py-8 text-center text-slate-500 dark:text-slate-400">Tidak ada item dengan sisa approval dan stok canvas.</td>
                </tr>
                <template v-else>
                  <tr v-for="item in orderItemRows" :key="item.id_canvas_request_detail || item.id_produk">
                    <td class="px-4 py-3">
                      <p class="font-bold text-slate-950 dark:text-white">{{ item.nama_produk || '-' }}</p>
                      <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">{{ item.nama_principal || '-' }}</p>
                    </td>
                    <td class="px-4 py-3 text-slate-600 dark:text-slate-300">{{ item.request_qty_label }}</td>
                    <td class="px-4 py-3 text-slate-600 dark:text-slate-300">{{ item.stock_label }}</td>
                    <td class="px-4 py-3">
                      <p class="mb-1 text-xs font-semibold text-slate-500 dark:text-slate-400">{{ orderUomLabel(item, 3) }}</p>
                      <input :value="item.qty_uom3" type="number" min="0" step="1" inputmode="numeric" class="field min-w-[110px]" :disabled="!isOrderUomEnabled(item, 3)" @input="updateOrderQty(item, 3, $event.target.value)" />
                    </td>
                    <td class="px-4 py-3">
                      <p class="mb-1 text-xs font-semibold text-slate-500 dark:text-slate-400">{{ orderUomLabel(item, 2) }}</p>
                      <input :value="item.qty_uom2" type="number" min="0" step="1" inputmode="numeric" class="field min-w-[110px]" :disabled="!isOrderUomEnabled(item, 2)" @input="updateOrderQty(item, 2, $event.target.value)" />
                    </td>
                    <td class="px-4 py-3">
                      <p class="mb-1 text-xs font-semibold text-slate-500 dark:text-slate-400">{{ orderUomLabel(item, 1) }}</p>
                      <input :value="item.qty_uom1" type="number" min="0" step="1" inputmode="numeric" class="field min-w-[110px]" :disabled="!isOrderUomEnabled(item, 1)" @input="updateOrderQty(item, 1, $event.target.value)" />
                    </td>
                    <td class="px-4 py-3 text-right font-bold text-slate-950 dark:text-white">{{ item.subtotal_label }}</td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>
          <div class="mt-4 flex justify-end text-sm">
            <div class="rounded-2xl border border-slate-200 px-4 py-3 dark:border-slate-700">
              Estimasi subtotal: <strong class="text-emerald-700 dark:text-emerald-300">{{ formatCurrency(orderDraftTotal) }}</strong>
            </div>
          </div>
        </div>
      </div>
      <template #footer>
        <button class="btn-secondary" @click="createOpen = false">Batal</button>
        <button class="btn-primary" :disabled="submitting || !orderForm.id_customer || !orderForm.id_canvas_request || !hasOrderQty" @click="submitOrder">Simpan Order</button>
      </template>
    </AppModal>

    <AppModal
      :open="!!selectedRow"
      title="Detail Order Canvas"
      :description="selectedRow ? `${selectedRow.nama_customer || '-'} - ${formatDate(selectedRow.tanggal_order)}` : ''"
      size="7xl"
      @close="selectedRow = null"
    >
      <div class="mb-4 flex flex-wrap justify-end gap-2">
        <button class="btn-secondary" :disabled="detailLoading" @click="printCanvasInvoice">Cetak Faktur Kanvas</button>
        <button class="btn-secondary" :disabled="detailLoading" @click="printCanvasInvoice">Bukti Penjualan</button>
      </div>
      <div class="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
        <section>
          <h3 class="mb-3 text-sm font-black uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">Rincian Produk</h3>
          <AppTable
            :columns="[
              { key: 'product_label', label: 'Produk' },
              { key: 'qty_label', label: 'Qty' },
              { key: 'harga_label', label: 'Harga' },
              { key: 'diskon_label', label: 'Diskon' },
              { key: 'subtotal_label', label: 'Subtotal' }
            ]"
            :rows="detailTableRows"
            :loading="detailLoading"
            :paginated="true"
            empty-message="Detail produk order belum tersedia."
          />
          <div class="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm dark:border-slate-700 dark:bg-slate-900">
            <div class="flex justify-between py-1">
              <span class="text-slate-500 dark:text-slate-400">Subtotal</span>
              <strong>{{ formatCurrency(detailTotals.subtotal) }}</strong>
            </div>
            <div class="flex justify-between py-1">
              <span class="text-slate-500 dark:text-slate-400">Diskon</span>
              <strong>{{ formatCurrency(detailTotals.diskon) }}</strong>
            </div>
            <div class="mt-2 flex justify-between border-t border-slate-200 pt-3 text-base dark:border-slate-700">
              <span class="font-black text-slate-900 dark:text-white">Total Order</span>
              <strong class="text-emerald-700 dark:text-emerald-300">{{ formatCurrency(detailTotals.total) }}</strong>
            </div>
          </div>
          <div class="mt-5">
            <h3 class="mb-3 text-sm font-black uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">Voucher yang Dipakai</h3>
            <AppTable
              :columns="[
                { key: 'tipe_label', label: 'Tipe' },
                { key: 'voucher_label', label: 'Voucher' },
                { key: 'subtotal_label', label: 'Subtotal Syarat' },
                { key: 'discount_label', label: 'Diskon' }
              ]"
              :rows="voucherUsageTableRows"
              :loading="voucherUsageLoading"
              :paginated="false"
              row-key="row_id"
              empty-message="Tidak ada voucher yang dipakai pada order ini."
            />
          </div>
        </section>

        <section class="space-y-4">
          <div class="panel p-4">
            <h3 class="text-sm font-black uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">Input Pembayaran</h3>
            <div class="mt-4 space-y-3">
              <label class="block">
                <span class="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Nominal</span>
                <input v-model="paymentForm.jumlah_setoran" type="number" min="0" class="field mt-1" placeholder="0" />
              </label>
              <div class="grid gap-2 rounded-2xl border border-slate-200 bg-slate-50 p-3 text-xs dark:border-slate-700 dark:bg-slate-950/60">
                <div class="flex justify-between gap-3">
                  <span class="text-slate-500 dark:text-slate-400">Total tagihan</span>
                  <strong>{{ formatCurrency(selectedOrderTagihan) }}</strong>
                </div>
                <div class="flex justify-between gap-3">
                  <span class="text-slate-500 dark:text-slate-400">Sudah dibayar</span>
                  <strong>{{ formatCurrency(selectedOrderPaid) }}</strong>
                </div>
                <div class="flex justify-between gap-3 text-sm">
                  <span class="font-black text-slate-900 dark:text-white">Sisa tagihan</span>
                  <strong class="text-emerald-700 dark:text-emerald-300">{{ formatCurrency(selectedOrderSisa) }}</strong>
                </div>
                <button class="btn-secondary w-full justify-center" :disabled="selectedOrderSisa <= 0" @click="fillRemainingPayment">
                  Isi Sisa Tagihan
                </button>
              </div>
              <label class="block">
                <span class="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Tipe Setoran</span>
                <select v-model="paymentForm.tipe_setoran" class="field mt-1">
                  <option value="tunai">Tunai</option>
                  <option value="non_tunai">Non Tunai</option>
                </select>
              </label>
              <label class="block">
                <span class="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Keterangan</span>
                <textarea v-model="paymentForm.keterangan" rows="3" class="field mt-1" placeholder="Opsional"></textarea>
              </label>
              <button
                class="btn-primary w-full"
                :disabled="submittingPayment || !selectedRow || selectedOrderSisa <= 0"
                @click="submitPayment"
              >
                {{ submittingPayment ? 'Menyimpan...' : 'Simpan Claim Pembayaran Canvas' }}
              </button>
              <button class="btn-secondary w-full justify-center" :disabled="!selectedRow" @click="printPaymentReceipt()">
                Cetak Bukti Bayar
              </button>
            </div>
          </div>

          <div>
            <h3 class="mb-3 text-sm font-black uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">Riwayat Pembayaran</h3>
            <AppTable
              :columns="[
                { key: 'tanggal_label', label: 'Tanggal' },
                { key: 'nominal_label', label: 'Nominal' },
                { key: 'tipe_label', label: 'Tipe' }
              ]"
              :rows="paymentTableRows"
              :loading="paymentLoading"
              :paginated="false"
              row-key="row_id"
              empty-message="Belum ada pembayaran canvas."
              clickable-rows
              @row-click="printPaymentReceipt"
            />
          </div>
        </section>
      </div>
    </AppModal>
  </div>
</template>
