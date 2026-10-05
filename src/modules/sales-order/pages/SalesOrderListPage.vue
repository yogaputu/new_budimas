<script setup>
import { computed, nextTick, onDeactivated, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { getInvoiceDetail, recordInvoicePrint } from '@/api/distribution';
import { getBranches, getCompanies, getPrincipals, getSales } from '@/api/master';
import { previewUnifiedPromoSalesOrder } from '@/api/promo';
import { getSalesMonthlyInfo, getSalesOmset, getSalesOrderList } from '@/api/salesOrder';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { buildSalesDocumentHtml, openPrintHtml, reservePrintWindow } from '@/utils/printTemplates';
import {
  branchMatchesCompany,
  getLoginBranchId,
  getLoginCompanyId,
  getLoginSalesUserId,
  getRowCompanyId,
  isSuperUser,
  scopeRowsByLoginBranch,
  scopeSalesRowsByLogin,
  shouldLockToLoginSales
} from '@/utils/accessScope';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import ShipmentDraftModal from '../components/ShipmentDraftModal.vue';
import { MAX_DRAFT_NOTES, draftOrderId, draftEligibilityError, draftSelectionError, notaDateRangeError } from '@/utils/shipmentDraft';

const router = useRouter();
const route = useRoute();
const auth = useAuthStore();

const filters = reactive({
  salesUserId: '',
  companyId: '',
  branchId: '',
  status: '',
  taxStatus: '',
  dateFrom: '',
  dateTo: '',
  search: ''
});

const items = ref([]);
const summary = ref({
  total_orders: 0,
  draft_orders: 0,
  active_orders: 0,
  completed_orders: 0,
  total_amount: 0
});
const pagination = reactive({
  page: 1,
  perPage: 50,
  total: 0,
  totalPages: 1
});
const performance = ref({
  totalOrder: 0,
  totalCustomerOrder: 0,
  belumKunjungan: 0,
  sudahBerkunjung: 0,
  totalTransaksi: 0,
  totalPencapaian: 0,
  totalOmset: 0
});
const companyRows = ref([]);
const branchRows = ref([]);
const principalRows = ref([]);
const salesRows = ref([]);
const loading = ref(false);
const detailLoading = ref(false);
const loadError = ref('');
const detailError = ref('');
const printError = ref('');
const printSubmitting = ref(false);
const selectedRow = ref(null);
const detailHeader = ref({});
const detailRows = ref([]);
const detailOpen = ref(false);
const promoPreview = ref({ total_estimated_benefit: 0, total_estimated_cashback: 0, total_estimated_discount: 0, qualified_count: 0, groups: [] });
const promoPreviewLoading = ref(false);
const promoPreviewError = ref('');
const checkedDraftRows = ref({});
const draftOpen = ref(false);
const draftFeedback = ref('');
const draftSelectionMessage = ref('');
const loadedFilterKey = ref('');
let ordersRequestId = 0;
const filterKey = computed(() => JSON.stringify(filters));
const selectedDraftRows = computed(() => Object.values(checkedDraftRows.value));
const canCreateDraft = computed(() => isSuperUser(auth) || ['distribution.schedules.update', 'm.distribusi.jd.update'].some(permission => auth.hasPermission(permission)));
const draftSelectionReady = computed(() => canCreateDraft.value && !loading.value && !loadError.value && loadedFilterKey.value === filterKey.value);
const eligiblePageRows = computed(() => normalizedRows.value.filter(row => !draftEligibilityError(row)));
const allPageDraftRowsChecked = computed(() => eligiblePageRows.value.length > 0 && eligiblePageRows.value.every(row => checkedDraftRows.value[draftOrderId(row)]));
const somePageDraftRowsChecked = computed(() => eligiblePageRows.value.some(row => checkedDraftRows.value[draftOrderId(row)]) && !allPageDraftRowsChecked.value);
const draftSelectionProblem = computed(() => selectedDraftRows.value.length ? draftSelectionError(selectedDraftRows.value) : '');

function clearDraftSelection() {
  checkedDraftRows.value = {};
  draftSelectionMessage.value = '';
}
function toggleDraftRow(row, event) {
  const checked = event.target.checked;
  // Restore the controlled state first, including when validation rejects this click.
  event.target.checked = !!checkedDraftRows.value[draftOrderId(row)];
  if (!draftSelectionReady.value || draftEligibilityError(row)) return;
  const next = { ...checkedDraftRows.value };
  if (checked) next[draftOrderId(row)] = row;
  else delete next[draftOrderId(row)];
  if (Object.keys(next).length > MAX_DRAFT_NOTES) {
    draftSelectionMessage.value = `Maksimal ${MAX_DRAFT_NOTES} nota per draf. Kurangi pilihan atau buat draf berikutnya.`;
    return;
  }
  checkedDraftRows.value = next;
  draftSelectionMessage.value = '';
}
function toggleDraftPage(event) {
  const checked = event.target.checked;
  event.target.checked = allPageDraftRowsChecked.value;
  event.target.indeterminate = somePageDraftRowsChecked.value;
  if (!draftSelectionReady.value) return;
  const next = { ...checkedDraftRows.value };
  for (const row of eligiblePageRows.value) {
    if (checked) next[draftOrderId(row)] = row;
    else delete next[draftOrderId(row)];
  }
  if (Object.keys(next).length > MAX_DRAFT_NOTES) {
    draftSelectionMessage.value = `Pilih semua dibatalkan: maksimal ${MAX_DRAFT_NOTES} nota per draf.`;
    return;
  }
  checkedDraftRows.value = next;
  draftSelectionMessage.value = '';
}
function openDraft() {
  if (draftSelectionReady.value && selectedDraftRows.value.length && !draftSelectionProblem.value) draftOpen.value = true;
}
async function draftCreated(message) {
  draftOpen.value = false;
  clearDraftSelection();
  draftFeedback.value = message;
  await loadOrders();
}
watch(filterKey, () => { clearDraftSelection(); draftFeedback.value = ''; }, { flush: 'sync' });

const fallbackUserId = computed(() => getLoginSalesUserId(auth.user));
const fallbackBranchId = computed(() => getLoginBranchId(auth.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(auth.user));
const activeCompanyId = computed(() => String(filters.companyId || fallbackCompanyId.value || ''));
const canUseLoginScope = computed(() => shouldLockToLoginSales(auth));
const shouldLockBusinessScope = computed(() => !isSuperUser(auth));

function resetBranchIfOutsideCompany(companyId = filters.companyId) {
  if (!companyId) {
    filters.branchId = '';
    return;
  }

  if (!filters.branchId) return;
  const currentBranch = branchRows.value.find((item) => String(item.id) === String(filters.branchId));
  if (!branchMatchesCompany(currentBranch, companyId)) {
    filters.branchId = '';
  }
}

function salesMatchesCompany(row, companyId) {
  if (!companyId) return true;

  const directCompanyId = getRowCompanyId(row);
  if (directCompanyId) {
    return String(directCompanyId) === String(companyId);
  }

  const principalIds = [
    row?.id_principal,
    row?.principal_id,
    row?.id_principals,
    row?.principal_ids
  ]
    .flatMap((value) => String(value || '').split(','))
    .map((value) => value.trim())
    .filter(Boolean);

  if (!principalIds.length) return false;

  return principalIds.some((principalId) => {
    const principal = principalRows.value.find((item) => String(item.id) === String(principalId));
    return String(getRowCompanyId(principal)) === String(companyId);
  });
}

function salesQuery() {
  return filters.salesUserId ? { sales_user_id: filters.salesUserId } : {};
}

function getSalesOrderId(row = {}) {
  return row.id_sales_order || row.sales_order_id || row.id_order || row.id;
}

function firstId(value) {
  if (Array.isArray(value)) return firstId(value[0]);

  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .find(Boolean) || '';
}

function buildCompletedInvoiceDetailParams(row = {}, header = {}) {
  const params = {
    include_batch_invoice: 1
  };
  const invoiceId = firstId(header?.id_faktur || row?.id_faktur);
  const batchId = firstId(header?.id_order_batch || row?.id_order_batch);
  const salesOrderId = firstId(getSalesOrderId(row));

  if (invoiceId) params.id_faktur = invoiceId;
  if (batchId) params.id_order_batch = batchId;
  if (salesOrderId) params.id_sales_orders = salesOrderId;

  return params;
}

function closeDetailModal() {
  detailOpen.value = false;
}

async function navigateFromDetail(targetRoute) {
  if (!targetRoute) return;

  closeDetailModal();
  await nextTick();
  router.push(targetRoute);
}

function openEditOrder() {
  const orderId = getSalesOrderId(selectedRow.value || {});
  if (!orderId) {
    detailError.value = 'ID sales order tidak ditemukan, belum bisa membuka halaman edit.';
    return;
  }

  navigateFromDetail({ name: 'sales-order-edit', params: { id: String(orderId) } });
}

const companyOptions = computed(() =>
  [
    { value: '', label: '' },
    ...companyRows.value
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || item.kode_perusahaan || '-'} - ${item.nama || item.nama_perusahaan || `Perusahaan ${item.id}`}`
    }))
  ]
);

const branchOptions = computed(() =>
  [
    { value: '', label: '' },
    ...scopeRowsByLoginBranch(branchRows.value, auth)
    .filter((item) => !filters.companyId || branchMatchesCompany(item, filters.companyId))
    .map((item) => ({
    value: String(item.id),
    label: `${item.kode || '-'} - ${item.nama || item.nama_cabang || 'Cabang'}`
    }))
  ]
);

const salesOptions = computed(() =>
  [
    { value: '', label: '' },
    ...scopeSalesRowsByLogin(salesRows.value, auth)
    .filter((item) => !filters.branchId || String(item.id_cabang || item.cabang_id || item.idCabang || '') === String(filters.branchId))
    .filter((item) => !filters.companyId || salesMatchesCompany(item, filters.companyId))
    .map((item) => ({
    value: String(item.id_user || item.id),
    label: `${item.kode_sales || '-'} - ${item.nama || 'Sales'}`
    }))
  ]
);

const statusOptions = ref([]);

const taxStatusOptions = [
  { value: 'pkp', label: 'PKP' },
  { value: 'non_pkp', label: 'Non PKP' },
  { value: 'npwp', label: 'NPWP' },
  { value: 'lain_lain', label: 'Lain-lain' }
];

const statusTimeline = [
  { key: 'PD', label: 'PD · Draft order', statuses: [0] },
  { key: 'RL', label: 'RL · Validasi', statuses: [1] },
  { key: 'DRF', label: 'DRF · Draft kiriman', statuses: [2, 10] },
  { key: 'PCK', label: 'PCK · Picking', statuses: [3] },
  { key: 'CKC', label: 'CKC · Checker', statuses: [] },
  { key: 'LDG', label: 'LDG · Loading', statuses: [] },
  { key: 'DLV', label: 'DLV · Pengiriman', statuses: [4, 11] },
  { key: 'DELIVERED', label: 'Delivered', statuses: [6] }
];

const filterFields = computed(() => [
  { key: 'companyId', label: 'Perusahaan', type: 'search-select', options: companyOptions.value, placeholder: 'Pilih perusahaan', emptyText: 'Perusahaan belum tersedia.', disabled: shouldLockBusinessScope.value && !!fallbackCompanyId.value },
  { key: 'branchId', label: 'Cabang', type: 'search-select', options: branchOptions.value, placeholder: filters.companyId ? 'Pilih cabang' : 'Pilih perusahaan dahulu', emptyText: filters.companyId ? 'Cabang belum tersedia.' : 'Pilih perusahaan dahulu.', disabled: !filters.companyId || (!isSuperUser(auth) && !!fallbackBranchId.value) },
  { key: 'salesUserId', label: 'Sales', type: 'search-select', options: salesOptions.value, placeholder: filters.branchId ? 'Pilih sales' : 'Pilih cabang dahulu', emptyText: filters.branchId ? 'Sales belum tersedia.' : 'Pilih cabang dahulu.', disabled: !filters.branchId || (canUseLoginScope.value && !!fallbackUserId.value) },
  { key: 'status', label: 'Status', type: 'select', options: statusOptions.value },
  { key: 'taxStatus', label: 'Status Pajak / PKP', type: 'select', options: taxStatusOptions },
  { key: 'dateFrom', label: 'Tanggal Nota Dari', type: 'date' },
  { key: 'dateTo', label: 'Tanggal Nota Sampai', type: 'date' },
  { key: 'search', label: 'Cari', placeholder: 'No order, customer, sales, principal, faktur' }
]);

const normalizedRows = computed(() =>
  items.value.map((item) => ({
    ...item,
    row_key: String(getSalesOrderId(item)),
    tanggal_label: item.tanggal_order || '-',
    customer_label: [item.kode_customer, item.nama_customer].filter(Boolean).join(' - ') || '-',
    principal_label: item.nama_principal || item.kode_principal || '-',
    order_total_label: `Rp ${Number(item.total_penjualan || item.total_order || 0).toLocaleString('id-ID')}`,
    faktur_label: item.no_faktur || '-',
    pieces_label: Number(item.total_pieces_order || 0).toLocaleString('id-ID'),
    produk_label: Number(item.total_produk || 0).toLocaleString('id-ID'),
    schedule_label: item.delivering_date || '-',
    status_badge: item.workflow_status ? `${item.workflow_status} · ${item.workflow_status_label}` : buildStatusBadge(item.status_order, item.status_order_label),
    next_step_label: resolveNextStep(item)
  }))
);

const canGoPreviousPage = computed(() => pagination.page > 1);
const canGoNextPage = computed(() => pagination.page < pagination.totalPages);
const pageRange = computed(() => {
  if (!pagination.total) return '0';
  const start = ((pagination.page - 1) * pagination.perPage) + 1;
  const end = Math.min(start + pagination.perPage - 1, pagination.total);
  return `${start}-${end}`;
});

const selectedKey = computed(() => selectedRow.value?.id || '');
const isCompletedOrder = computed(() => Number(selectedRow.value?.status_order) === 6);
const completedInvoiceContext = computed(() => {
  const row = selectedRow.value || {};
  const header = detailHeader.value || {};

  return {
    idSalesOrder: firstId(getSalesOrderId(row)),
    idFaktur: firstId(header.id_faktur || row.id_faktur),
    idOrderBatch: firstId(header.id_order_batch || row.id_order_batch),
    idPlafon: firstId(header.id_plafon || row.id_plafon),
    idSales: firstId(header.id_sales || row.id_sales || filters.salesUserId || fallbackUserId.value),
    noFaktur: String(header.nomor_faktur || header.no_faktur || row.no_faktur || '').trim(),
    noOrder: String(header.no_order || row.no_order || '').trim(),
    customerName: String(header.nama_customer || row.nama_customer || '').trim(),
    companyId: firstId(header.id_perusahaan || row.id_perusahaan || filters.companyId || fallbackCompanyId.value),
    branchId: firstId(header.id_cabang || row.id_cabang || filters.branchId || fallbackBranchId.value)
  };
});

function detailUomName(item, level, fallback) {
  const keys = [
    `uom${level}_nama`,
    `uom_${level}_nama`,
    `puom${level}_nama`,
    `uom${level}Nama`,
    `nama_uom_${level}`,
    `uom${level}_name`
  ];
  return keys.map((key) => String(item?.[key] || '').trim()).find(Boolean) || fallback;
}

function detailUomFactor(item, level, fallback) {
  const keys = [
    `uom${level}_factor`,
    `uom_${level}_factor`,
    `uom${level}Factor`,
    `faktor_uom_${level}`,
    `uom${level}_faktor_konversi`,
    `konversi_level${level}`
  ];
  const value = keys.map((key) => Number(item?.[key] || 0)).find((candidate) => candidate > 0);
  return value || fallback;
}

function detailBaseQty(item) {
  const canonicalFields = ['total_pieces_order', 'total_pcs', 'qty_pcs'];
  for (const field of canonicalFields) {
    const rawValue = item?.[field];
    if (rawValue === null || rawValue === undefined || rawValue === '') continue;
    const value = Number(rawValue);
    if (Number.isFinite(value) && value >= 0) return value;
  }

  const pcs = Number(item?.pieces_order || 0);
  const uom1Factor = detailUomFactor(item, 1, 1);
  const uom2Factor = detailUomFactor(item, 2, Number(item?.isiperbox || 1));
  const uom3Factor = detailUomFactor(item, 3, Number(item?.isiperkarton || item?.isiperbox || 1));
  return pcs * uom1Factor + Number(item?.box_order || 0) * uom2Factor + Number(item?.karton_order || 0) * uom3Factor;
}

function detailQtyLabel(item) {
  const pcs = Number(item?.pieces_order || 0);
  const uom2 = Number(item?.box_order || 0);
  const uom3 = Number(item?.karton_order || 0);
  const parts = [];

  if (uom3) parts.push(`${uom3.toLocaleString('id-ID')} ${detailUomName(item, 3, 'Karton')}`);
  if (uom2) parts.push(`${uom2.toLocaleString('id-ID')} ${detailUomName(item, 2, 'CT')}`);
  if (pcs || parts.length === 0) parts.push(`${pcs.toLocaleString('id-ID')} ${detailUomName(item, 1, 'PCS')}`);

  return `${parts.join(' | ')} (${detailBaseQty(item).toLocaleString('id-ID')} PCS)`;
}

const detailSummary = computed(() => {
  const totalRows = detailRows.value.length;
  const totalSubtotal = detailRows.value.reduce((total, item) => total + Number(item.subtotalorder || 0), 0);
  const totalQty = detailRows.value.reduce((total, item) => total + detailBaseQty(item), 0);

  return [
    { label: 'Baris Produk', value: totalRows.toLocaleString('id-ID') },
    { label: 'Total (PCS)', value: totalQty.toLocaleString('id-ID') },
    { label: 'Subtotal', value: `Rp ${totalSubtotal.toLocaleString('id-ID')}` }
  ];
});

const selectedTimeline = computed(() => {
  const currentStatus = Number(selectedRow.value?.status_order ?? -999);
  const code = selectedRow.value?.workflow_status || statusTimeline.find((step) => step.statuses.includes(currentStatus))?.key;
  const steps = code === 'FD' ? [...statusTimeline.slice(0, -1), { key: 'FD', label: 'FD · Gagal / kendala kirim' }] : statusTimeline;
  const index = steps.findIndex((step) => step.key === code);
  return steps.map((step, position) => ({ ...step, state: position === index ? 'current' : index >= 0 && position < index ? 'done' : 'upcoming' }));
});

const selectedStageRoute = computed(() => {
  const status = Number(selectedRow.value?.status_order ?? -999);
  if ([4, 5, 11, 6, 8].includes(status)) {
    return 'realisasi';
  }

  return 'shipping';
});

const detailTableRows = computed(() =>
  detailRows.value.map((item) => ({
    ...item,
    qty_label: detailQtyLabel(item),
    subtotal_label: `Rp ${Number(item.subtotalorder || 0).toLocaleString('id-ID')}`
  }))
);

function money(value) {
  return `Rp ${Number(value || 0).toLocaleString('id-ID')}`;
}

const orderAmountSummary = computed(() => {
  const row = selectedRow.value || {};
  const detailSubtotal = detailRows.value.reduce((total, item) => total + Number(item.subtotalorder || 0), 0);
  const subtotalBeforeDiscount = Number(row.total_order_before_discount || row.faktur_total_before_discount || detailSubtotal || 0);
  const promoDiscount = Number(row.unified_promo_nominal || row.faktur_unified_promo_nominal || 0);
  const manualDiscount = Number(row.manual_discount_nominal || row.faktur_manual_discount_nominal || 0);
  const totalDiscount = Number(row.order_discount_total || row.faktur_order_discount_total || promoDiscount + manualDiscount || 0);
  const dpp = Number(row.dpp || Math.max(subtotalBeforeDiscount - totalDiscount, 0));
  const tax = Number(row.pajak || 0);
  const grandTotal = Number(row.total_penjualan || row.total_order || dpp + tax || 0);
  const manualType = row.manual_discount_type || row.faktur_manual_discount_type || '';
  const manualValue = Number(row.manual_discount_value || row.faktur_manual_discount_value || 0);
  const manualPercentEquivalent = Number(row.manual_discount_percent_equivalent || row.faktur_manual_discount_percent_equivalent || 0);
  const manualLabel = manualDiscount > 0
    ? manualType === 'percent'
      ? `Manual ${manualValue.toLocaleString('id-ID')}%`
      : `Manual nominal${manualPercentEquivalent > 0 ? ` setara ${manualPercentEquivalent.toLocaleString('id-ID', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%` : ''}`
    : 'Tidak ada';

  return [
    { label: 'Subtotal Sebelum Diskon', value: money(subtotalBeforeDiscount), tone: 'default' },
    { label: 'Promo All-In', value: money(promoDiscount), tone: promoDiscount > 0 ? 'success' : 'default' },
    { label: `Diskon ${manualLabel}`, value: money(manualDiscount), tone: manualDiscount > 0 ? 'warning' : 'default' },
    { label: 'Total Diskon', value: money(totalDiscount), tone: totalDiscount > 0 ? 'warning' : 'default' },
    { label: 'DPP Setelah Diskon', value: money(dpp), tone: 'default' },
    { label: 'PPN', value: money(tax), tone: 'default' },
    { label: 'Grand Total', value: money(grandTotal), tone: 'strong' }
  ];
});

const qualifiedPromoRows = computed(() =>
  normalizeList(promoPreview.value?.groups)
    .filter((item) => item.qualified || Number(item.estimated_benefit || item.estimated_cashback || 0) > 0)
    .map((item, index) => ({
      ...item,
      key: `${item.program_id || 'promo'}-${item.rule_id || index}`,
      benefit_label: `Rp ${Number(item.estimated_benefit || item.estimated_cashback || 0).toLocaleString('id-ID')}`,
      qty_label: `${Number(item.qty || 0).toLocaleString('id-ID')} ${item.qty_uom || ''}`.trim()
    }))
);

const promoSummaryCards = computed(() => [
  {
    label: 'Promo All-In Eligible',
    value: Number(promoPreview.value?.qualified_count || 0).toLocaleString('id-ID')
  },
  {
    label: 'Estimasi Benefit Promo',
    value: `Rp ${Number(promoPreview.value?.total_estimated_benefit || 0).toLocaleString('id-ID')}`
  },
  {
    label: 'Rule Promo Dicek',
    value: normalizeList(promoPreview.value?.groups).length.toLocaleString('id-ID')
  }
]);

const primaryDistributionAction = computed(() => {
  if (!selectedRow.value) {
    return null;
  }

  const status = Number(selectedRow.value.status_order ?? -999);

  if (status === 0) {
    return {
      label: 'Buka Verifikasi Order',
      route: {
        name: 'distribution-orders',
        query: {
          id_cabang: selectedRow.value.id_cabang,
          sales_order_id: selectedRow.value.id,
          no_order: selectedRow.value.no_order || ''
        }
      }
    };
  }

  if (status === 1) {
    return { label: 'Buka Jadwal Pengiriman', route: buildScheduleRoute(selectedRow.value) };
  }

  if ([2, 9, 10].includes(status)) {
    return { label: 'Buka Picking', route: { name: 'distribution-picking' } };
  }

  if (status === 3) {
    return {
      label: 'Buka Shipping',
      route: {
        name: 'distribution-invoices',
        query: {
          stage: 'shipping',
          id_cabang: selectedRow.value.id_cabang,
          sales_order_id: selectedRow.value.id
        }
      }
    };
  }

  if ([4, 11].includes(status)) {
    return {
      label: 'Buka Realisasi',
      route: {
        name: 'distribution-invoices',
        query: {
          stage: 'realisasi',
          id_cabang: selectedRow.value.id_cabang,
          sales_order_id: selectedRow.value.id
        }
      }
    };
  }

  if (status === 5) {
    return {
      label: 'Buka Revisi Faktur',
      route: {
        name: 'distribution-invoice-revisions',
        query: {
          id_cabang: selectedRow.value.id_cabang,
          sales_order_id: selectedRow.value.id
        }
      }
    };
  }

  if (status === 6) {
    return null;
  }

  return {
    label: 'Buka Detail Faktur',
    route: {
      name: 'distribution-invoices',
      query: {
        stage: selectedStageRoute.value,
        id_cabang: selectedRow.value.id_cabang,
        sales_order_id: selectedRow.value.id
      }
    }
  };
});

const tableColumns = [
  { key: 'draft_select', label: 'Pilih Draf' },
  { key: 'no_order', label: 'No Order' },
  { key: 'tanggal_label', label: 'Tanggal' },
  { key: 'customer_label', label: 'Customer' },
  { key: 'nama_rute', label: 'Rute' },
  { key: 'nama_sales', label: 'Sales' },
  { key: 'principal_label', label: 'Principal' },
  { key: 'produk_label', label: 'Produk' },
  { key: 'pieces_label', label: 'Total PCS' },
  { key: 'order_total_label', label: 'Total' },
  { key: 'status_badge', label: 'Status Order' },
  { key: 'faktur_label', label: 'No Faktur' },
  { key: 'status_faktur_label', label: 'Status Faktur' },
  { key: 'next_step_label', label: 'Langkah Berikutnya' }
];

function buildStatusBadge(status, label) {
  const numericStatus = Number(status);

  if (numericStatus === 6) return `SELESAI | ${label}`;
  if (numericStatus === 5) return `PERLU REVISI | ${label}`;
  if ([4, 11].includes(numericStatus)) return `PENGIRIMAN | ${label}`;
  if (numericStatus === 3) return `FAKTUR SIAP | ${label}`;
  if ([2, 9, 10].includes(numericStatus)) return `JADWAL AKTIF | ${label}`;
  if (numericStatus === 1) return `MENUNGGU JADWAL | ${label}`;
  if (numericStatus === 0) return `MENUNGGU VERIFIKASI | ${label}`;
  if (numericStatus === -1) return `DITOLAK | ${label}`;

  return label || '-';
}

function buildScheduleRoute(row) {
  const scheduleSalesUserId = filters.salesUserId || (canUseLoginScope.value ? fallbackUserId.value : '');

  return {
    name: 'distribution-schedules',
    query: {
      schedule_action: row?.id_proses_picking ? 'edit' : 'create',
      sales_user_id: scheduleSalesUserId ? String(scheduleSalesUserId) : '',
      sales_order_id: row?.id ? String(row.id) : '',
      id_cabang: row?.id_cabang ? String(row.id_cabang) : '',
      id_proses_picking: row?.id_proses_picking ? String(row.id_proses_picking) : '',
      id_armada: row?.id_armada ? String(row.id_armada) : '',
      id_driver: row?.id_driver ? String(row.id_driver) : '',
      tanggal_pengiriman: row?.delivering_date || '',
      no_order: row?.no_order || '',
      customer_name: row?.nama_customer || '',
      route_name: row?.nama_rute || ''
    }
  };
}

function resolveNextStep(item) {
  const numericStatus = Number(item.status_order);

  if (numericStatus === 0) return 'Buka verifikasi order';
  if (numericStatus === 1) return 'Buka jadwal armada';
  if ([2, 9, 10].includes(numericStatus)) return 'Buka picking';
  if (numericStatus === 3) return 'Buka shipping';
  if ([4, 11].includes(numericStatus)) return 'Buka realisasi';
  if (numericStatus === 5) return 'Tindak lanjuti revisi faktur';
  if (numericStatus === 6) return 'Cetak faktur, pembayaran, atau retur';
  if (numericStatus === -1) return 'Periksa alasan penolakan';

  return '-';
}

function resetFilters() {
  filters.salesUserId = route.query.sales_user_id ? String(route.query.sales_user_id) : canUseLoginScope.value && fallbackUserId.value ? String(fallbackUserId.value) : '';
  filters.branchId = shouldLockBusinessScope.value && fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  filters.companyId = shouldLockBusinessScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
  if (!filters.companyId && filters.branchId) {
    const branch = branchRows.value.find((item) => String(item.id) === String(filters.branchId));
    const branchCompanyId = getRowCompanyId(branch);
    if (branchCompanyId) filters.companyId = String(branchCompanyId);
  }
  resetBranchIfOutsideCompany();
  filters.status = '';
  filters.taxStatus = '';
  filters.dateFrom = '';
  filters.dateTo = '';
  filters.search = '';
  items.value = [];
  pagination.page = 1;
  resetDetail();
  loadOrders();
}

function resetDetail() {
  selectedRow.value = null;
  detailHeader.value = {};
  detailRows.value = [];
  detailError.value = '';
  printError.value = '';
  detailOpen.value = false;
  promoPreview.value = { total_estimated_benefit: 0, total_estimated_cashback: 0, total_estimated_discount: 0, qualified_count: 0, groups: [] };
  promoPreviewError.value = '';
}

function buildDetailPromoPreviewPayload(row) {
  return {
    order_date: row?.tanggal_order || detailHeader.value?.tanggal_order || '',
    id_cabang: row?.id_cabang || filters.branchId || fallbackBranchId.value || '',
    id_perusahaan: row?.id_perusahaan || activeCompanyId.value || filters.companyId || '',
    id_principal: row?.id_principal || row?.principal_id || detailHeader.value?.id_principal || '',
    id_customer: row?.id_customer || detailHeader.value?.id_customer || '',
    products: detailRows.value.map((item) => ({
      id_produk: Number(item.id_produk || 0),
      harga_jual: Number(item.harga_jual || item.hargaorder || 0),
      pieces_order: Number(item.pieces_order || 0),
      box_order: Number(item.box_order || 0),
      karton_order: Number(item.karton_order || 0),
      konversi_2: Number(item.konversi_level2 || item.konversi_2 || 1),
      konversi_3: Number(item.konversi_level3 || item.konversi_3 || 1),
      subtotalorder: Number(item.subtotalorder || 0)
    }))
  };
}

async function refreshDetailPromoPreview(row) {
  if (!detailRows.value.length) {
    promoPreview.value = { total_estimated_benefit: 0, total_estimated_cashback: 0, total_estimated_discount: 0, qualified_count: 0, groups: [] };
    return;
  }

  promoPreviewLoading.value = true;
  promoPreviewError.value = '';
  try {
    const response = await previewUnifiedPromoSalesOrder(buildDetailPromoPreviewPayload(row));
    promoPreview.value = unwrapResponse(response) || { total_estimated_benefit: 0, total_estimated_cashback: 0, total_estimated_discount: 0, qualified_count: 0, groups: [] };
  } catch (error) {
    promoPreview.value = { total_estimated_benefit: 0, total_estimated_cashback: 0, total_estimated_discount: 0, qualified_count: 0, groups: [] };
    promoPreviewError.value = normalizeError(error, 'Promo order belum bisa dicek.');
  } finally {
    promoPreviewLoading.value = false;
  }
}

async function loadReferenceData() {
  const [companiesResponse, branchesResponse, principalsResponse, salesResponse] = await Promise.all([getCompanies(), getBranches(), getPrincipals(), getSales()]);
  companyRows.value = normalizeList(unwrapResponse(companiesResponse));
  branchRows.value = normalizeList(unwrapResponse(branchesResponse));
  principalRows.value = normalizeList(unwrapResponse(principalsResponse));
  salesRows.value = normalizeList(unwrapResponse(salesResponse));

  if (shouldLockBusinessScope.value && fallbackBranchId.value) filters.branchId = String(fallbackBranchId.value);
  if (shouldLockBusinessScope.value && fallbackCompanyId.value) filters.companyId = String(fallbackCompanyId.value);
  if (!filters.companyId && filters.branchId) {
    const branch = branchRows.value.find((item) => String(item.id) === String(filters.branchId));
    const branchCompanyId = getRowCompanyId(branch);
    if (branchCompanyId) filters.companyId = String(branchCompanyId);
  }
  resetBranchIfOutsideCompany();
  if (canUseLoginScope.value && fallbackUserId.value && !filters.salesUserId) filters.salesUserId = String(fallbackUserId.value);
}

function updateFilters(nextFilters) {
  const previousBranchId = filters.branchId;
  const previousCompanyId = filters.companyId;

  Object.assign(filters, nextFilters);

  if (filters.companyId !== previousCompanyId) {
    resetBranchIfOutsideCompany(filters.companyId);
    filters.salesUserId = canUseLoginScope.value && fallbackUserId.value ? String(fallbackUserId.value) : '';
    items.value = [];
    pagination.page = 1;
    resetDetail();
    return;
  }

  if (filters.branchId !== previousBranchId) {
    filters.salesUserId = canUseLoginScope.value && fallbackUserId.value ? String(fallbackUserId.value) : '';
    items.value = [];
    pagination.page = 1;
    resetDetail();
  }
}

function applyFilters() {
  pagination.page = 1;
  loadOrders();
}

function changePage(direction) {
  const nextPage = Math.min(
    Math.max(1, pagination.page + direction),
    pagination.totalPages || 1
  );
  if (nextPage !== pagination.page) loadOrders(nextPage);
}

function changePageSize() {
  pagination.page = 1;
  loadOrders();
}

async function loadPerformance() {
  const userId = filters.salesUserId || (canUseLoginScope.value ? fallbackUserId.value : '');
  if (!userId) {
    performance.value = {
      totalOrder: 0,
      totalCustomerOrder: 0,
      belumKunjungan: 0,
      sudahBerkunjung: 0,
      totalTransaksi: 0,
      totalPencapaian: 0,
      totalOmset: 0
    };
    return;
  }

  const current = new Date();
  const tahun = current.getFullYear();
  const bulan = String(current.getMonth() + 1).padStart(2, '0');

  try {
    const [infoResponse, omsetResponse] = await Promise.all([
      getSalesMonthlyInfo({ user_id: userId, tahun, bulan }),
      getSalesOmset({ user_id: userId, tahun, bulan })
    ]);

    const info = unwrapResponse(infoResponse) || {};
    const omsetRows = normalizeList(unwrapResponse(omsetResponse));
    performance.value = {
      totalOrder: Number(info.totalOrder || 0),
      totalCustomerOrder: Number(info.totalCustomerOrder || 0),
      belumKunjungan: Number(info.belumKunjungan || 0),
      sudahBerkunjung: Number(info.sudahBerkunjung || 0),
      totalTransaksi: Number(info.totalTransaksi || 0),
      totalPencapaian: Number(info.totalPencapaian || 0),
      totalOmset: omsetRows.reduce((total, item) => total + Number(item.omset || 0), 0)
    };
  } catch (error) {
    performance.value = {
      totalOrder: 0,
      totalCustomerOrder: 0,
      belumKunjungan: 0,
      sudahBerkunjung: 0,
      totalTransaksi: 0,
      totalPencapaian: 0,
      totalOmset: 0
    };
  }
}

async function loadOrders(page = pagination.page) {
  const requestId = ++ordersRequestId;
  const requestedFilterKey = filterKey.value;
  const dateError = notaDateRangeError(filters.dateFrom, filters.dateTo);
  if (dateError) {
    loadError.value = dateError;
    loading.value = false;
    loadedFilterKey.value = '';
    items.value = [];
    clearDraftSelection();
    return;
  }
  loading.value = true;
  loadError.value = '';
  resetDetail();

  try {
    const requestedPage = Math.max(1, Number(page) || 1);
    const response = await getSalesOrderList({
      user_id: filters.salesUserId || (canUseLoginScope.value ? fallbackUserId.value : undefined),
      id_cabang: filters.branchId || (shouldLockBusinessScope.value ? fallbackBranchId.value : undefined),
      id_perusahaan: filters.companyId || undefined,
      workflow_status: filters.status || undefined,
      include_workflow_statuses: true,
      status_pajak: filters.taxStatus || undefined,
      date_from: filters.dateFrom || undefined,
      date_to: filters.dateTo || undefined,
      search: filters.search || undefined,
      page: requestedPage,
      per_page: pagination.perPage
    });

    const payload = unwrapResponse(response) || {};
    if (requestId !== ordersRequestId || requestedFilterKey !== filterKey.value) return;
    statusOptions.value = payload.status_options || [];
    const meta = payload?.pagination || {};
    items.value = normalizeList(payload);
    loadedFilterKey.value = requestedFilterKey;
    const nextSelection = { ...checkedDraftRows.value };
    for (const row of items.value) {
      const id = draftOrderId(row);
      if (nextSelection[id]) {
        if (draftEligibilityError(row)) delete nextSelection[id];
        else nextSelection[id] = row;
      }
    }
    checkedDraftRows.value = nextSelection;
    const total = Number(meta.total ?? payload?.summary?.total_orders ?? items.value.length ?? 0);
    pagination.page = Math.max(1, Number(meta.page || requestedPage));
    pagination.perPage = Math.max(1, Number(meta.per_page || pagination.perPage || 50));
    pagination.total = Math.max(0, total);
    pagination.totalPages = Math.max(1, Number(meta.total_pages || Math.ceil(total / pagination.perPage) || 1));
    summary.value = {
      total_orders: Number(payload?.summary?.total_orders || items.value.length || 0),
      draft_orders: Number(payload?.summary?.draft_orders || 0),
      active_orders: Number(payload?.summary?.active_orders || 0),
      completed_orders: Number(payload?.summary?.completed_orders || 0),
      total_amount: Number(payload?.summary?.total_amount || 0)
    };
  } catch (error) {
    if (requestId !== ordersRequestId || requestedFilterKey !== filterKey.value) return;
    loadError.value = normalizeError(error, 'Daftar sales order belum bisa dimuat.');
    items.value = [];
    pagination.total = 0;
    pagination.totalPages = 1;
    summary.value = {
      total_orders: 0,
      draft_orders: 0,
      active_orders: 0,
      completed_orders: 0,
      total_amount: 0
    };
  } finally {
    if (requestId === ordersRequestId) loading.value = false;
  }
}

async function openDetail(row) {
  selectedRow.value = row;
  detailHeader.value = {};
  detailRows.value = [];
  detailError.value = '';
  printError.value = '';
  detailOpen.value = true;
  detailLoading.value = true;

  try {
    const isCompleted = Number(row?.status_order) === 6;
    const salesOrderId = getSalesOrderId(row);
    const params = isCompleted
      ? buildCompletedInvoiceDetailParams(row)
      : row.id_order_batch
        ? { id_order_batch: row.id_order_batch, id_sales_orders: String(salesOrderId) }
        : {};
    const response = await getInvoiceDetail(salesOrderId, params);
    const payload = unwrapResponse(response) || {};
    detailHeader.value = payload?.detail_faktur || {};
    detailRows.value = normalizeList(payload?.list_detail_order || payload);
    await refreshDetailPromoPreview(row);
  } catch (error) {
    detailError.value = normalizeError(error, 'Detail order sales belum bisa dimuat.');
    detailHeader.value = {};
    detailRows.value = [];
    promoPreview.value = { total_estimated_benefit: 0, total_estimated_cashback: 0, total_estimated_discount: 0, qualified_count: 0, groups: [] };
  } finally {
    detailLoading.value = false;
  }
}

function buildInvoicePrintHeader(row, detail, rows) {
  const activeCompany = companyRows.value.find((item) =>
    String(item.id) === String(detail?.id_perusahaan || row?.id_perusahaan || filters.companyId || fallbackCompanyId.value)
  );
  const activeBranch = branchRows.value.find((item) =>
    String(item.id) === String(detail?.id_cabang || row?.id_cabang || filters.branchId || fallbackBranchId.value)
  );
  const subtotal = rows.reduce((total, item) =>
    total + Number(item.subtotalorder || item.subtotal || item.total_harga || 0), 0
  );
  const taxTotal = Number(
    detail?.pajak || detail?.ppn || rows.reduce((total, item) => total + Number(item.ppn || 0), 0)
  );

  return {
    idFaktur: firstId(detail?.id_faktur || row?.id_faktur),
    noFaktur: detail?.nomor_faktur || detail?.no_faktur || row?.no_faktur || '-',
    noOrder: detail?.no_order || row?.no_order || '-',
    date: detail?.tanggal_faktur || detail?.tanggal_order || row?.tanggal_order || new Date().toISOString().slice(0, 10),
    dueDate: detail?.tanggal_jatuh_tempo || row?.tanggal_jatuh_tempo || '',
    customer: detail?.nama_customer || row?.nama_customer || '-',
    kodeCustomer: detail?.kode_customer || row?.kode_customer || '-',
    address: detail?.alamat_customer || detail?.alamat || row?.alamat || '-',
    sales: detail?.nama_sales_order || detail?.nama_sales || row?.nama_sales || '-',
    fakturist: auth.user?.nama || auth.user?.name || auth.user?.nama_user || '-',
    routeCode: detail?.kode_rute || detail?.kode_principal || '-',
    po: detail?.po || detail?.no_po || row?.po || row?.no_po || '',
    companyName: detail?.nama_perusahaan || activeCompany?.nama || 'PT. BUDIMAS MAKMUR MULIA',
    companyAddress: detail?.alamat_perusahaan || activeBranch?.alamat || '',
    companyPhone: detail?.telepon_perusahaan || activeBranch?.telepon || activeCompany?.telepon || '',
    companyBank: detail?.rekening_perusahaan || '',
    printTime: new Date().toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' }),
    subtotal,
    taxTotal,
    grandTotal: Number(detail?.total_penjualan || detail?.total_bayar || row?.total_penjualan || subtotal + taxTotal),
    printCount: Number(detail?.jumlah_cetak || row?.jumlah_cetak || 0)
  };
}

async function printCompletedInvoice() {
  const row = selectedRow.value;
  if (!row || !isCompletedOrder.value || printSubmitting.value) return;

  printError.value = '';
  const printWindow = reservePrintWindow({ width: 1280, height: 760 });
  if (!printWindow) {
    printError.value = 'Popup cetak diblokir browser. Izinkan popup untuk mencetak faktur.';
    return;
  }

  printSubmitting.value = true;
  try {
    printWindow.document.write('<!doctype html><title>Menyiapkan cetakan</title><p style="font-family:Arial,sans-serif;padding:24px">Menyiapkan faktur…</p>');
    printWindow.document.close();

    // Reload through the completed-invoice API path: it verifies the exact
    // invoice and returns every Sales Order in a multi-principal batch.
    const response = await getInvoiceDetail(
      getSalesOrderId(row),
      buildCompletedInvoiceDetailParams(row, detailHeader.value)
    );
    const payload = unwrapResponse(response) || {};
    const rows = normalizeList(payload?.list_detail_order || payload).filter((item) => item && typeof item === 'object');
    const detail = payload?.detail_faktur || {};
    if (!rows.length) {
      throw new Error('Detail faktur belum tersedia sehingga belum dapat dicetak.');
    }

    detailHeader.value = detail;
    detailRows.value = rows;
    const header = buildInvoicePrintHeader(row, detail, rows);
    const invoiceId = Number(header.idFaktur || 0);
    if (!invoiceId) {
      throw new Error('ID faktur belum tersedia. Muat ulang data lalu coba cetak kembali.');
    }

    const printResponse = await recordInvoicePrint(invoiceId);
    const printResult = unwrapResponse(printResponse) || {};
    header.printCount = Number(printResult?.jumlah_cetak || header.printCount + 1);
    detailHeader.value = { ...detailHeader.value, jumlah_cetak: header.printCount };
    selectedRow.value = { ...row, jumlah_cetak: header.printCount };

    const html = buildSalesDocumentHtml({
      type: 'invoice',
      title: 'Faktur Penjualan',
      header,
      rows,
      company: {
        name: header.companyName,
        address: header.companyAddress,
        phone: header.companyPhone
      }
    });
    if (!openPrintHtml(`Faktur Penjualan - ${header.noFaktur}`, html, { printWindow, width: 1280, height: 760 })) {
      throw new Error('Popup cetak diblokir browser. Izinkan popup untuk mencetak faktur.');
    }
  } catch (error) {
    if (!printWindow.closed) printWindow.close();
    printError.value = normalizeError(error, 'Faktur belum dapat disiapkan untuk dicetak.');
  } finally {
    printSubmitting.value = false;
  }
}

function completedPaymentRoute() {
  const context = completedInvoiceContext.value;
  const query = {
    ...salesQuery(),
    id_sales_order: context.idSalesOrder,
    no_faktur: context.noFaktur,
    customer_name: context.customerName
  };

  if (context.idPlafon) query.id_plafon = context.idPlafon;
  if (context.idSales) query.id_sales = context.idSales;
  if (context.idFaktur) query.id_faktur = context.idFaktur;
  if (context.idOrderBatch) query.id_order_batch = context.idOrderBatch;
  if (context.companyId) query.id_perusahaan = context.companyId;
  if (context.branchId) query.id_cabang = context.branchId;

  return { name: 'finance-payments', query };
}

function completedReturRoute() {
  const context = completedInvoiceContext.value;
  const query = {
    ...salesQuery(),
    id_sales_order: context.idSalesOrder,
    id_sales: context.idSales,
    id_plafon: context.idPlafon,
    no_order: context.noOrder,
    no_faktur: context.noFaktur,
    customer_name: context.customerName
  };

  if (context.idFaktur) query.id_faktur = context.idFaktur;
  if (context.idOrderBatch) query.id_order_batch = context.idOrderBatch;
  if (context.companyId) query.id_perusahaan = context.companyId;
  if (context.branchId) query.id_cabang = context.branchId;

  return { name: 'sales-order-retur', query };
}

onMounted(async () => {
  filters.salesUserId = route.query.sales_user_id ? String(route.query.sales_user_id) : canUseLoginScope.value && fallbackUserId.value ? String(fallbackUserId.value) : '';
  filters.branchId = shouldLockBusinessScope.value && fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  filters.companyId = shouldLockBusinessScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';

  try {
    await loadReferenceData();
  } catch (error) {
    loadError.value = normalizeError(error, 'Referensi sales dan cabang belum bisa dimuat.');
  }

  await loadOrders();
  await loadPerformance();
});

onDeactivated(() => {
  closeDetailModal();
  draftOpen.value = false;
  clearDraftSelection();
});

watch(
  () => filters.companyId,
  (companyId, previousCompanyId) => {
    if (companyId === previousCompanyId) return;

    resetBranchIfOutsideCompany(companyId);
    filters.salesUserId = canUseLoginScope.value && fallbackUserId.value ? String(fallbackUserId.value) : '';
    items.value = [];
    resetDetail();
  }
);

watch(
  () => filters.branchId,
  (branchId, previousBranchId) => {
    if (branchId === previousBranchId) return;

    filters.salesUserId = canUseLoginScope.value && fallbackUserId.value ? String(fallbackUserId.value) : '';
    items.value = [];
    resetDetail();
  }
);
</script>

<template>
  <div class="space-y-6 text-slate-200">
    <PageHeader
      title="Sales Order Control Center"
      description="ERP dashboard untuk memantau order sales, status distribusi, faktur, retur, dan progres operasional Budimas secara terpusat."
    >
      <div class="flex flex-wrap gap-2">
        <button class="btn-erp-secondary" @click="loadOrders">
          Refresh
        </button>

        <button class="btn-erp-secondary" @click="router.push({ name: 'sales-order-invoices', query: salesQuery() })">
          Invoice Order
        </button>

        <button class="btn-erp-secondary" @click="router.push({ name: 'sales-order-retur-list', query: salesQuery() })">
          Monitoring Retur
        </button>

        <button
          class="btn-erp-secondary disabled:cursor-not-allowed disabled:border-slate-700/70 disabled:bg-slate-800/60 disabled:text-slate-500"
          :disabled="!selectedRow"
          @click="
            selectedRow
              ? router.push({
                  name: 'sales-order-retur',
                  query: {
                    ...salesQuery(),
                    id_sales_order: selectedRow.id,
                    id_sales: selectedRow.id_sales,
                    id_plafon: selectedRow.id_plafon,
                    no_order: selectedRow.no_order,
                    no_faktur: selectedRow.no_faktur,
                    customer_name: selectedRow.nama_customer
                  }
                })
              : null
          "
        >
          Ajukan Retur
        </button>

        <button class="btn-erp-primary" @click="router.push({ name: 'sales-order-create' })">
          + Buat Sales Order
        </button>
      </div>
    </PageHeader>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <article class="erp-card">
        <div class="flex items-center justify-between">
          <p class="erp-label">Total Order</p>
          <span class="erp-chip bg-blue-500/15 text-blue-200 ring-1 ring-blue-300/20">SO</span>
        </div>
        <p class="erp-value">{{ summary.total_orders.toLocaleString('id-ID') }}</p>
        <p class="erp-muted">Semua order sesuai filter aktif</p>
      </article>

      <article class="erp-card">
        <div class="flex items-center justify-between">
          <p class="erp-label">Draft</p>
          <span class="erp-chip bg-amber-500/15 text-amber-200 ring-1 ring-amber-300/20">Pending</span>
        </div>
        <p class="erp-value">{{ summary.draft_orders.toLocaleString('id-ID') }}</p>
        <p class="erp-muted">Menunggu verifikasi awal</p>
      </article>

      <article class="erp-card">
        <div class="flex items-center justify-between">
          <p class="erp-label">Aktif Operasional</p>
          <span class="erp-chip bg-indigo-500/15 text-indigo-200 ring-1 ring-indigo-300/20">Process</span>
        </div>
        <p class="erp-value">{{ summary.active_orders.toLocaleString('id-ID') }}</p>
        <p class="erp-muted">Dalam proses distribusi</p>
      </article>

      <article class="erp-card border-brand-500/30 bg-slate-950 text-white">
        <div class="flex items-center justify-between">
          <p class="text-xs font-semibold uppercase tracking-[0.25em] text-slate-300">Nilai Order</p>
          <span class="rounded-full bg-white/10 px-2.5 py-1 text-xs font-semibold text-white">Revenue</span>
        </div>
        <p class="mt-3 text-2xl font-bold">Rp {{ Number(summary.total_amount || 0).toLocaleString('id-ID') }}</p>
        <p class="mt-1 text-xs text-slate-300">Total nilai order berjalan</p>
      </article>
    </section>

    <section class="panel-dark">
      <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 class="text-base font-semibold text-white">Performance Bulan Ini</h3>
          <p class="text-sm text-slate-400">Ringkasan aktivitas sales berdasarkan user yang dipilih.</p>
        </div>
      </div>

      <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <article class="erp-mini-card">
          <p class="erp-label">Customer Order</p>
          <p class="erp-mini-value">{{ performance.totalCustomerOrder.toLocaleString('id-ID') }}</p>
        </article>

        <article class="erp-mini-card">
          <p class="erp-label">Sudah Berkunjung</p>
          <p class="erp-mini-value">{{ performance.sudahBerkunjung.toLocaleString('id-ID') }}</p>
        </article>

        <article class="erp-mini-card">
          <p class="erp-label">Total Transaksi</p>
          <p class="erp-mini-value">Rp {{ performance.totalTransaksi.toLocaleString('id-ID') }}</p>
        </article>

        <article class="erp-mini-card">
          <p class="erp-label">Omset Bulan Ini</p>
          <p class="erp-mini-value">Rp {{ performance.totalOmset.toLocaleString('id-ID') }}</p>
        </article>
      </div>
    </section>

    <section class="panel-dark">
      <div class="mb-4">
        <h3 class="text-base font-semibold text-white">Control Panel Filter</h3>
        <p class="text-sm text-slate-400">Filter rentang tanggal nota memakai tanggal order (termasuk tanggal awal dan akhir), bukan tanggal pengiriman. Klik Terapkan, lalu centang nota yang akan dijadikan draf.</p>
      </div>

      <AppFilterBar
        :model-value="filters"
        :fields="filterFields"
        @update:model-value="updateFilters"
        @submit="applyFilters"
        @reset="resetFilters"
      />
    </section>

    <div v-if="loadError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-medium text-rose-700">
      {{ loadError }}
    </div>

    <section>
      <div class="panel-dark">
        <div class="mb-4 rounded-xl border border-sky-400/30 bg-sky-500/10 p-4">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p class="font-semibold">{{ selectedDraftRows.length }} nota dipilih untuk draf kiriman</p>
              <p class="mt-1 text-sm text-slate-400">Hanya RL / Booked yang belum dijadwalkan. Pilihan tersimpan saat pindah halaman (maks. 100), dan dikosongkan jika filter diubah. Satu draf harus satu perusahaan, cabang, dan rute.</p>
            </div>
            <div class="flex gap-2">
              <button class="btn-erp-secondary" :disabled="!selectedDraftRows.length || draftOpen" @click="clearDraftSelection">Kosongkan Pilihan</button>
              <button class="btn-erp-primary" :disabled="!draftSelectionReady || !selectedDraftRows.length || !!draftSelectionProblem" @click="openDraft">Buat Draf Kiriman ({{ selectedDraftRows.length }})</button>
            </div>
          </div>
          <p v-if="!canCreateDraft" class="mt-2 text-sm text-amber-300">Akun memerlukan hak ubah Jadwal Pengiriman untuk membuat draf.</p>
          <p v-else-if="loadedFilterKey !== filterKey && !loading" class="mt-2 text-sm text-amber-300">Filter berubah. Klik Terapkan sebelum memilih nota.</p>
          <p v-if="draftSelectionMessage || draftSelectionProblem" role="alert" class="mt-2 text-sm text-amber-300">{{ draftSelectionMessage || draftSelectionProblem }}</p>
          <p v-if="draftFeedback" role="status" class="mt-2 text-sm text-emerald-400">{{ draftFeedback }}</p>
        </div>
        <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 class="text-lg font-bold text-white">Order Monitoring</h3>
            <p class="mt-1 text-sm text-slate-400">Klik baris order untuk membuka detail, timeline, dan aksi operasional dalam modal.</p>
          </div>

          <div class="rounded-2xl border border-emerald-400/20 bg-emerald-500/10 px-4 py-2 text-sm text-emerald-200">
            Delivered:
            <span class="font-bold">{{ summary.completed_orders.toLocaleString('id-ID') }}</span>
          </div>
        </div>

        <div class="table-dark">
          <AppTable
            :columns="tableColumns"
            :rows="normalizedRows"
            :loading="loading"
            :paginated="false"
            row-key="row_key"
            :selected-key="selectedKey"
            :clickable-rows="true"
            empty-message="Belum ada sales order yang cocok dengan filter."
            @row-click="openDetail"
          >
            <template #header-draft_select>
              <input type="checkbox" aria-label="Pilih semua nota yang memenuhi syarat di halaman ini" :checked="allPageDraftRowsChecked" :indeterminate="somePageDraftRowsChecked" :disabled="!draftSelectionReady || !eligiblePageRows.length" @change="toggleDraftPage($event)" />
            </template>
            <template #cell-draft_select="{ row }">
              <span @click.stop>
                <input type="checkbox" :aria-label="`Pilih nota ${row.no_order}`" :title="draftEligibilityError(row) || 'Pilih untuk draf kiriman'" :checked="!!checkedDraftRows[draftOrderId(row)]" :disabled="!draftSelectionReady || !!draftEligibilityError(row)" @change="toggleDraftRow(row, $event)" />
              </span>
            </template>
          </AppTable>
        </div>

        <div v-if="!loading" class="mt-4 flex flex-wrap items-center justify-between gap-3 px-1 text-sm text-slate-400">
          <span>Menampilkan {{ pageRange }} dari {{ pagination.total.toLocaleString('id-ID') }} sales order</span>
          <div class="flex flex-wrap items-center gap-2">
            <label class="flex items-center gap-2">
              <span>Per halaman</span>
              <select
                v-model.number="pagination.perPage"
                class="rounded-xl border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100 outline-none"
                @change="changePageSize"
              >
                <option :value="25">25</option>
                <option :value="50">50</option>
                <option :value="100">100</option>
              </select>
            </label>
            <button
              class="rounded-xl border border-slate-700 bg-slate-950 px-3 py-1.5 font-medium text-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="!canGoPreviousPage"
              @click="changePage(-1)"
            >
              Sebelumnya
            </button>
            <span class="px-1 font-medium text-slate-300">Hal {{ pagination.page }} / {{ pagination.totalPages }}</span>
            <button
              class="rounded-xl border border-slate-700 bg-slate-950 px-3 py-1.5 font-medium text-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="!canGoNextPage"
              @click="changePage(1)"
            >
              Berikutnya
            </button>
          </div>
        </div>
      </div>
    </section>

    <ShipmentDraftModal :open="draftOpen" :rows="selectedDraftRows" @close="draftOpen = false" @created="draftCreated" />
    <AppModal
      :open="detailOpen"
      title="Detail Sales Order"
      :description="selectedRow ? 'Ringkasan order, timeline operasional, detail produk, dan aksi cepat.' : 'Pilih order dari tabel untuk membuka detail.'"
      size="7xl"
      @close="closeDetailModal"
    >
      <div v-if="detailError" class="mb-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
        {{ detailError }}
      </div>

      <div v-if="printError" class="mb-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
        {{ printError }}
      </div>

      <div v-if="selectedRow" class="space-y-5">
        <section class="rounded-2xl bg-slate-900 p-4 text-white dark:bg-slate-950">
          <p class="text-xs uppercase tracking-[0.25em] text-slate-300">No Order</p>
          <div class="mt-2 flex flex-wrap items-end justify-between gap-3">
            <div>
              <p class="text-2xl font-bold">{{ selectedRow.no_order }}</p>
              <p class="mt-1 text-sm text-slate-300">{{ selectedRow.nama_customer || '-' }}</p>
            </div>
            <p class="rounded-full bg-white/10 px-3 py-1 text-xs font-bold text-white">
              {{ selectedRow.status_badge || selectedRow.status_order_label || '-' }}
            </p>
          </div>
        </section>

        <section class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <article class="erp-detail-box dark:border-slate-700 dark:bg-slate-800/70">
            <p class="erp-label">Status Order</p>
            <p class="mt-2 font-semibold text-slate-900 dark:text-white">{{ selectedRow.status_badge || selectedRow.status_order_label || '-' }}</p>
          </article>

          <article class="erp-detail-box dark:border-slate-700 dark:bg-slate-800/70">
            <p class="erp-label">No Faktur</p>
            <p class="mt-2 font-semibold text-slate-900 dark:text-white">{{ selectedRow.no_faktur || detailHeader.no_faktur || detailHeader.nomor_faktur || '-' }}</p>
          </article>

          <article class="erp-detail-box dark:border-slate-700 dark:bg-slate-800/70">
            <p class="erp-label">Customer</p>
            <p class="mt-2 font-semibold text-slate-900 dark:text-white">{{ selectedRow.nama_customer || detailHeader.nama_customer || '-' }}</p>
          </article>

          <article class="erp-detail-box dark:border-slate-700 dark:bg-slate-800/70">
            <p class="erp-label">Jadwal Kirim</p>
            <p class="mt-2 font-semibold text-slate-900 dark:text-white">{{ selectedRow.schedule_label || '-' }}</p>
          </article>
        </section>

        <section class="grid gap-3 md:grid-cols-3">
          <article v-for="item in detailSummary" :key="item.label" class="erp-detail-box dark:border-slate-700 dark:bg-slate-800/70">
            <p class="erp-label">{{ item.label }}</p>
            <p class="mt-2 text-lg font-bold text-slate-900 dark:text-white">{{ item.value }}</p>
          </article>
        </section>

        <section class="rounded-2xl border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-400/30 dark:bg-emerald-500/10">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 class="text-lg font-bold text-emerald-950 dark:text-emerald-100">Ringkasan Nilai Order</h3>
              <p class="text-sm text-emerald-800/80 dark:text-emerald-100/75">
                Subtotal, diskon promo/manual, DPP, PPN, dan total akhir yang tersimpan untuk order ini.
              </p>
            </div>
          </div>

          <div class="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <article
              v-for="item in orderAmountSummary"
              :key="item.label"
              class="rounded-2xl border px-4 py-3"
              :class="
                item.tone === 'strong'
                  ? 'border-emerald-300 bg-emerald-600 text-white dark:border-emerald-300/50 dark:bg-emerald-500/30'
                  : item.tone === 'warning'
                    ? 'border-amber-200 bg-amber-50 dark:border-amber-400/30 dark:bg-amber-500/10'
                    : item.tone === 'success'
                      ? 'border-cyan-200 bg-cyan-50 dark:border-cyan-400/30 dark:bg-cyan-500/10'
                      : 'border-white/60 bg-white/75 dark:border-slate-700 dark:bg-slate-900/60'
              "
            >
              <p
                class="text-xs uppercase tracking-[0.2em]"
                :class="item.tone === 'strong' ? 'text-emerald-50' : 'text-slate-500 dark:text-slate-400'"
              >
                {{ item.label }}
              </p>
              <p
                class="mt-2 text-lg font-bold"
                :class="item.tone === 'strong' ? 'text-white' : 'text-slate-950 dark:text-white'"
              >
                {{ item.value }}
              </p>
            </article>
          </div>
        </section>

        <section class="rounded-2xl border border-amber-200 bg-amber-50 p-4 dark:border-amber-400/30 dark:bg-amber-500/10">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 class="text-lg font-bold text-amber-950 dark:text-amber-100">Promo All-In Order</h3>
              <p class="text-sm text-amber-800/80 dark:text-amber-100/75">
                Menampilkan promo all-in yang eligible dari isi order berdasarkan scope, strata, budget, dan periode aktif.
              </p>
            </div>
            <span v-if="promoPreviewLoading" class="rounded-full bg-white/70 px-3 py-1 text-xs font-semibold text-amber-800 dark:bg-amber-950/40 dark:text-amber-100">
              Mengecek promo...
            </span>
          </div>

          <div class="mt-4 grid gap-3 md:grid-cols-3">
            <article v-for="item in promoSummaryCards" :key="item.label" class="rounded-2xl border border-amber-200 bg-white/70 px-4 py-3 dark:border-amber-400/20 dark:bg-slate-900/60">
              <p class="text-xs uppercase tracking-[0.2em] text-amber-700 dark:text-amber-200">{{ item.label }}</p>
              <p class="mt-2 text-lg font-bold text-slate-950 dark:text-white">{{ item.value }}</p>
            </article>
          </div>

          <div v-if="promoPreviewError" class="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
            {{ promoPreviewError }}
          </div>

          <div class="mt-4">
            <div class="rounded-2xl border border-amber-200 bg-white/70 p-4 dark:border-amber-400/20 dark:bg-slate-900/60">
              <h4 class="font-semibold text-slate-900 dark:text-white">Promo All-In Eligible</h4>
              <div v-if="qualifiedPromoRows.length" class="mt-3 space-y-2">
                <article v-for="item in qualifiedPromoRows" :key="item.key" class="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800">
                  <div class="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <p class="font-semibold text-slate-900 dark:text-white">{{ item.nama_promo || item.nama_program || item.kode_promo || '-' }}</p>
                      <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">{{ item.target_name || '-' }} | {{ item.qty_label }}</p>
                    </div>
                    <p class="font-bold text-emerald-700 dark:text-emerald-200">{{ item.benefit_label }}</p>
                  </div>
                </article>
              </div>
              <p v-else class="mt-3 rounded-xl border border-dashed border-amber-300 px-3 py-3 text-sm text-amber-800 dark:border-amber-300/30 dark:text-amber-100/75">
                Belum ada promo all-in yang memenuhi syarat untuk order ini.
              </p>
            </div>
          </div>
        </section>

        <section>
          <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 class="text-lg font-bold text-slate-900 dark:text-white">Operational Timeline</h3>
              <p class="text-sm text-slate-500 dark:text-slate-400">{{ selectedRow.workflow_status_label || selectedRow.status_order_label }} · Tahap operasional bersumber dari ERP, WMS, dan POD; bukan status pelunasan faktur.</p>
            </div>
          </div>

          <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <article
              v-for="step in selectedTimeline"
              :key="step.key"
              class="rounded-2xl border px-4 py-3"
              :class="
                step.state === 'current'
                  ? 'border-brand-300 bg-brand-50 dark:border-brand-400/40 dark:bg-brand-500/15'
                  : step.state === 'done'
                    ? 'border-emerald-200 bg-emerald-50 dark:border-emerald-400/40 dark:bg-emerald-500/15'
                    : 'border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/70'
              "
            >
              <p
                class="text-xs font-semibold uppercase tracking-[0.22em]"
                :class="step.state === 'current' ? 'text-brand-700 dark:text-brand-200' : step.state === 'done' ? 'text-emerald-700 dark:text-emerald-200' : 'text-slate-400'"
              >
                {{ step.state === 'current' ? 'Aktif' : step.state === 'done' ? 'Selesai' : 'Berikutnya' }}
              </p>

              <p
                class="mt-2 font-bold"
                :class="step.state === 'current' ? 'text-brand-900 dark:text-brand-100' : step.state === 'done' ? 'text-emerald-900 dark:text-emerald-100' : 'text-slate-700 dark:text-slate-200'"
              >
                {{ step.label }}
              </p>
            </article>
          </div>
        </section>

        <section class="overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-700">
          <AppTable
            :rows="detailTableRows"
            :columns="[
              { key: 'kode_sku', label: 'SKU' },
              { key: 'nama_produk', label: 'Produk' },
              { key: 'qty_label', label: 'Qty Order' },
              { key: 'subtotal_label', label: 'Subtotal' }
            ]"
            :loading="detailLoading"
            empty-message="Detail item order belum tersedia."
          />
        </section>
      </div>

      <div v-else class="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-400">
        Belum ada order dipilih.
      </div>

      <template #footer>
        <div class="flex flex-wrap justify-end gap-2">
          <button class="btn-erp-secondary" @click="closeDetailModal">
            Tutup
          </button>

          <button
            v-if="selectedRow && Number(selectedRow.status_order) === 0"
            class="btn-erp-secondary"
            @click="openEditOrder"
          >
            Edit Order
          </button>

          <!-- <button
            v-if="selectedRow && Number(selectedRow.status_order) < 2"
            class="btn-erp-secondary"
            @click="
              router.push({
                name: 'distribution-orders',
                query: {
                  id_cabang: selectedRow.id_cabang,
                  sales_order_id: selectedRow.id,
                  no_order: selectedRow.no_order || ''
                }
              })
            "
          >
            
          </button> -->

          <template v-if="isCompletedOrder">
            <button
              class="btn-erp-primary disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="printSubmitting || detailLoading || !completedInvoiceContext.idSalesOrder"
              @click="printCompletedInvoice"
            >
              {{ printSubmitting ? 'Menyiapkan Faktur...' : 'Cetak Faktur' }}
            </button>

            <button
              class="btn-erp-secondary disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="!completedInvoiceContext.idSalesOrder"
              @click="navigateFromDetail(completedPaymentRoute())"
            >
              Buka Pembayaran
            </button>

            <button
              class="btn-erp-secondary disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="!completedInvoiceContext.idSalesOrder || !completedInvoiceContext.noFaktur"
              @click="navigateFromDetail(completedReturRoute())"
            >
              Ajukan Retur
            </button>
          </template>

          <button
            v-else-if="selectedRow && primaryDistributionAction"
            class="btn-erp-primary"
            @click="navigateFromDetail(primaryDistributionAction.route)"
          >
            {{ primaryDistributionAction.label || (selectedStageRoute === 'realisasi' ? 'Buka Realisasi Faktur' : 'Buka Shipping Faktur') }}
          </button>
        </div>
      </template>
    </AppModal>
  </div>
</template>
