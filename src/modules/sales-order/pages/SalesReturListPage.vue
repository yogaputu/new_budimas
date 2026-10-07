<script setup>
import { returStatusOptions, returStatusLabel } from '../returStatus';
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { getBranches, getCompanies, getPrincipals, getSales } from '@/api/master';
import { approveReturBySpv, cancelReturByDriver, cancelReturBySpv, getReturDetail, getSalesReturList, submitReturStock } from '@/api/salesOrder';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { branchMatchesCompany, getLoginBranchId, getLoginCompanyId, getLoginSalesUserId, getRowCompanyId, getRowCompanyIds, isSuperUser, scopeRowsByLoginBranch, scopeSalesRowsByLogin, shouldLockToLoginSales } from '@/utils/accessScope';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const router = useRouter();
const route = useRoute();
const auth = useAuthStore();
const filters = reactive({
  salesUserId: '',
  companyId: '',
  branchId: '',
  status: '',
  dateFrom: '',
  dateTo: '',
  search: ''
});

const items = ref([]);
const summary = ref({
  total_requests: 0,
  pending_requests: 0,
  kpr_requests: 0,
  processed_requests: 0,
  on_process_requests: 0,
  canceled_requests: 0,
  total_amount: 0
});
const companyRows = ref([]);
const branchRows = ref([]);
const principalRows = ref([]);
const salesRows = ref([]);
const loading = ref(false);
const loadError = ref('');
const selectedRow = ref(null);

const detailOpen = ref(false);
const detailLoading = ref(false);
const detailHeader = ref({});
const detailRows = ref([]);
const detailError = ref('');
const detailFeedback = ref('');
const actionLoading = ref(false);
const fallbackUserId = computed(() => getLoginSalesUserId(auth.user));
const fallbackBranchId = computed(() => getLoginBranchId(auth.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(auth.user));
const canUseLoginScope = computed(() => shouldLockToLoginSales(auth));
const shouldLockBusinessScope = computed(() => !isSuperUser(auth));

function salesQuery() {
  return filters.salesUserId ? { sales_user_id: filters.salesUserId } : {};
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

const companyOptions = computed(() =>
  companyRows.value
    .filter((item) => {
      if (isSuperUser(auth)) return true;
      const scopedCompanyIds = new Set(
        scopeRowsByLoginBranch(branchRows.value, auth)
          .flatMap((branch) => getRowCompanyIds(branch).map(String))
          .filter(Boolean)
      );
      return scopedCompanyIds.has(String(item.id)) || String(item.id) === String(fallbackCompanyId.value || '');
    })
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || item.kode_perusahaan || '-'} - ${item.nama || item.nama_perusahaan || `Perusahaan ${item.id}`}`
    }))
);

const branchOptions = computed(() =>
  scopeRowsByLoginBranch(branchRows.value, auth)
    .filter((item) => !filters.companyId || branchMatchesCompany(item, filters.companyId))
    .map((item) => ({
    value: String(item.id),
    label: `${item.kode || '-'} - ${item.nama || item.nama_cabang || 'Cabang'}`
    }))
);

const salesOptions = computed(() =>
  scopeSalesRowsByLogin(salesRows.value, auth)
    .filter((item) => !filters.branchId || String(item.id_cabang || item.cabang_id || item.idCabang || '') === String(filters.branchId))
    .filter((item) => !filters.companyId || salesMatchesCompany(item, filters.companyId))
    .map((item) => ({
    value: String(item.id_user || item.id),
    label: `${item.kode_sales || '-'} - ${item.nama || 'Sales'}`
    }))
);

const statusOptions = returStatusOptions;

const filterFields = computed(() => [
  { key: 'companyId', label: 'Perusahaan', type: 'search-select', options: companyOptions.value, placeholder: 'Semua perusahaan', disabled: shouldLockBusinessScope.value && !!fallbackCompanyId.value },
  { key: 'branchId', label: 'Cabang', type: 'search-select', options: branchOptions.value, placeholder: 'Semua cabang', emptyText: 'Cabang belum tersedia.', disabled: !isSuperUser(auth) && !!fallbackBranchId.value },
  { key: 'salesUserId', label: 'Sales', type: 'search-select', options: salesOptions.value, placeholder: 'Semua sales', emptyText: 'Sales belum tersedia.', disabled: canUseLoginScope.value && !!fallbackUserId.value },
  { key: 'status', label: 'Status Retur', type: 'search-select', options: statusOptions, placeholder: 'Semua status' },
  { key: 'dateFrom', label: 'Dari Tanggal', type: 'date' },
  { key: 'dateTo', label: 'Sampai Tanggal', type: 'date' },
  { key: 'search', label: 'Cari', placeholder: 'Kode request, KPR, CN, order, faktur, customer' }
]);

const normalizedRows = computed(() =>
  items.value.map((item) => ({
    ...item,
    row_key: String(item.id_request),
    request_label: item.kode_request || '-',
    qty_label: item.qty_retur_label || formatQtyLabel(item.total_pieces_retur, item.total_box_retur, item.total_karton_retur),
    amount_label: `Rp ${Number(item.total_retur || 0).toLocaleString('id-ID')}`,
    status_badge: resolveReturBusinessStatus(item),
    next_step_label: resolveNextStep(item),
    faktur_label: item.no_faktur || '-'
  }))
);

const selectedKey = computed(() => selectedRow.value?.id_request || '');
const selectedStatus = computed(() => String(selectedRow.value?.status_request ?? ''));
const canPrintKpr = computed(() => detailOpen.value && selectedStatus.value === '0' && detailHeader.value?.kode_kpr && !actionLoading.value);
const canCancelSpv = computed(() => detailOpen.value && selectedStatus.value === '0' && !actionLoading.value);
const canProcessReturStock = computed(() => detailOpen.value && selectedStatus.value === '1' && detailRows.value.length > 0 && !actionLoading.value);
const canCancelDriver = computed(() => detailOpen.value && selectedStatus.value === '1' && !actionLoading.value);
const canPrintReturDocument = computed(() => detailOpen.value && detailRows.value.length > 0 && !detailLoading.value);
const detailTableRows = computed(() =>
  detailRows.value.map((item, index) => ({
    ...item,
    row_key: String(item.id_produk || item.id_request_detail || index),
    qty_request_bad_label: formatQtyLabel(item.pieces_diajukan, item.box_diajukan, item.karton_diajukan, item),
    qty_request_good_label: formatQtyLabel(item.pieces_good_diajukan, item.box_good_diajukan, item.karton_good_diajukan, item),
    qty_total_label: formatQtyLabel(item.pieces_retur, item.box_retur, item.karton_retur, item)
  }))
);

const tableColumns = [
  { key: 'request_label', label: 'Kode Request' },
  { key: 'tanggal_request', label: 'Tanggal' },
  { key: 'nama_customer', label: 'Customer' },
  { key: 'nama_principal', label: 'Principal' },
  { key: 'no_order', label: 'No Order' },
  { key: 'faktur_label', label: 'No Faktur' },
  { key: 'qty_label', label: 'Qty Retur' },
  { key: 'amount_label', label: 'Nilai Retur' },
  { key: 'status_badge', label: 'Status Retur' },
  { key: 'next_step_label', label: 'Langkah Berikutnya' }
];

function parseUomList(row) {
  const rawList = row?.uom_list;
  if (Array.isArray(rawList)) return rawList;

  if (typeof rawList === 'string') {
    try {
      const parsed = JSON.parse(rawList);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }

  return [];
}

function getDetailUom(row, level) {
  return parseUomList(row).find((item) => Number(item.level) === Number(level)) || {};
}

function getDetailUomName(row, level) {
  const uom = getDetailUom(row, level);
  return uom.nama || uom.kode || '';
}

function getDetailUomConversion(row, level) {
  const value = getDetailUom(row, level).faktor_konversi;
  if (level === 1 && (value === undefined || value === null || value === '')) return 1;
  return Number(value || 0);
}

function isDetailUomEnabled(row, level) {
  return Boolean(getDetailUomName(row, level)) && getDetailUomConversion(row, level) > 0;
}

function formatDetailUomLabel(row, level) {
  const name = getDetailUomName(row, level) || `UOM ${level} belum diset`;
  if (level === 1) return name;
  return `${name} x ${Number(getDetailUomConversion(row, level) || 0).toLocaleString('id-ID')}`;
}

function getAcceptedFieldLevel(field) {
  if (field.includes('pieces')) return 1;
  if (field.includes('box')) return 2;
  if (field.includes('karton')) return 3;
  return 0;
}

function formatQtyLabel(pieces, box, karton, row = null) {
  if (!row) {
    return `${Number(pieces || 0).toLocaleString('id-ID')} pcs | ${Number(box || 0).toLocaleString('id-ID')} box | ${Number(karton || 0).toLocaleString('id-ID')} karton`;
  }

  const qtyRows = [
    { level: 1, value: pieces },
    { level: 2, value: box },
    { level: 3, value: karton }
  ]
    .filter(({ level }) => isDetailUomEnabled(row, level))
    .map(({ level, value }) => `${Number(value || 0).toLocaleString('id-ID')} ${getDetailUomName(row, level)}`);

  return qtyRows.length ? qtyRows.join(' | ') : 'UOM produk belum lengkap';
}

function formatCurrency(value) {
  return `Rp ${Number(value || 0).toLocaleString('id-ID')}`;
}

function formatDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString('id-ID', { day: '2-digit', month: 'long', year: 'numeric' });
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function resolveNextStep(item) {
  const status = String(item.status_request ?? '');
  if (status === '0') return 'Menunggu approval SPV';
  if (status === '1') return 'Kirim barang ke QC Karantina WMS';
  if (status === '2') return 'Menunggu hasil QC Gudang';
  if (status === '4') return 'QC selesai — menunggu Credit Note finance';
  if (status === '3') return 'Credit Note selesai';
  if (status === '9') return 'Retur batal';
  return '-';
}

function resolveReturBusinessStatus(item) {
  return returStatusLabel(item);
}

function normalizeDetailRow(item) {
  return {
    ...item,
    accepted_bad_pieces: Number(item.pieces_diajukan || 0),
    accepted_bad_box: Number(item.box_diajukan || 0),
    accepted_bad_karton: Number(item.karton_diajukan || 0),
    accepted_good_pieces: Number(item.pieces_good_diajukan || 0),
    accepted_good_box: Number(item.box_good_diajukan || 0),
    accepted_good_karton: Number(item.karton_good_diajukan || 0)
  };
}

function updateAcceptedField(row, field, value) {
  const level = getAcceptedFieldLevel(field);
  const normalizedValue = isDetailUomEnabled(row, level) ? Math.max(0, Math.floor(Number(value || 0))) : 0;
  const target = detailRows.value.find((item) =>
    String(item.id_request_detail || item.id_produk) === String(row.id_request_detail || row.id_produk)
  );

  if (target) {
    target[field] = normalizedValue;
  }

  row[field] = normalizedValue;
}

function totalAcceptedPieces(row, fieldPrefix) {
  const fields = fieldPrefix === 'requested'
    ? ['pieces_retur', 'box_retur', 'karton_retur']
    : fieldPrefix === 'accepted_bad'
      ? ['accepted_bad_pieces', 'accepted_bad_box', 'accepted_bad_karton']
      : ['accepted_good_pieces', 'accepted_good_box', 'accepted_good_karton'];
  return fields.reduce((total, field, index) =>
    total + Number(row[field] || 0) * Number(getDetailUomConversion(row, index + 1) || 0), 0
  );
}

function validateAcceptedRetur() {
  for (const row of detailRows.value) {
    const requested = totalAcceptedPieces(row, 'requested');
    const acceptedBad = totalAcceptedPieces(row, 'accepted_bad');
    const acceptedGood = totalAcceptedPieces(row, 'accepted_good');
    if (requested !== acceptedBad + acceptedGood) {
      return `${row.nama_produk || row.kode_sku || 'Produk'}: total GOOD + BAD harus sama dengan jumlah retur (${requested.toLocaleString('id-ID')} PCS).`;
    }
  }
  return '';
}

function buildReturStockPayload() {
  return {
    items: detailRows.value.map((item) => ({
      id_produk: Number(item.id_produk),
      pieces_diajukan: Number(item.accepted_bad_pieces || 0),
      box_diajukan: Number(item.accepted_bad_box || 0),
      karton_diajukan: Number(item.accepted_bad_karton || 0),
      pieces_good_diajukan: Number(item.accepted_good_pieces || 0),
      box_good_diajukan: Number(item.accepted_good_box || 0),
      karton_good_diajukan: Number(item.accepted_good_karton || 0)
    }))
  };
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
  filters.status = '';
  filters.dateFrom = '';
  filters.dateTo = '';
  filters.search = '';
  items.value = [];
  selectedRow.value = null;
  loadReturRows();
}

function resetDetailState() {
  detailHeader.value = {};
  detailRows.value = [];
  detailError.value = '';
  detailFeedback.value = '';
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
  if (canUseLoginScope.value && fallbackUserId.value && !filters.salesUserId) filters.salesUserId = String(fallbackUserId.value);
}

function updateFilters(nextFilters) {
  const previousBranchId = filters.branchId;
  const previousCompanyId = filters.companyId;

  Object.assign(filters, nextFilters);

  if (filters.companyId !== previousCompanyId) {
    if (!filters.companyId) {
      filters.branchId = '';
    } else if (filters.branchId) {
      const currentBranch = branchRows.value.find((item) => String(item.id) === String(filters.branchId));
      if (!branchMatchesCompany(currentBranch, filters.companyId)) {
        filters.branchId = '';
      }
    }
    filters.salesUserId = canUseLoginScope.value && fallbackUserId.value ? String(fallbackUserId.value) : '';
    items.value = [];
    selectedRow.value = null;
    return;
  }

  if (filters.branchId !== previousBranchId) {
    filters.salesUserId = canUseLoginScope.value && fallbackUserId.value ? String(fallbackUserId.value) : '';
    items.value = [];
    selectedRow.value = null;
  }
}

async function loadReturRows(preserveRequestId = null) {
  loading.value = true;
  loadError.value = '';
  const targetId = preserveRequestId || selectedRow.value?.id_request || null;

  try {
    const response = await getSalesReturList({
      user_id: filters.salesUserId || (canUseLoginScope.value ? fallbackUserId.value : undefined),
      id_cabang: filters.branchId || (shouldLockBusinessScope.value ? fallbackBranchId.value : undefined),
      id_perusahaan: filters.companyId || undefined,
      status: filters.status || undefined,
      status_group: filters.status ? undefined : 'all',
      date_from: filters.dateFrom || undefined,
      date_to: filters.dateTo || undefined,
      search: filters.search || undefined
    });
    const payload = unwrapResponse(response) || {};
    items.value = normalizeList(payload);
    summary.value = {
      total_requests: Number(payload?.summary?.total_requests || items.value.length || 0),
      pending_requests: Number(payload?.summary?.pending_requests || 0),
      kpr_requests: Number(payload?.summary?.kpr_requests || 0),
      processed_requests: Number(payload?.summary?.processed_requests || 0),
      on_process_requests: Number(payload?.summary?.on_process_requests || 0),
      canceled_requests: Number(payload?.summary?.canceled_requests || 0),
      total_amount: Number(payload?.summary?.total_amount || 0)
    };
    selectedRow.value = targetId ? items.value.find((item) => String(item.id_request) === String(targetId)) || null : null;
  } catch (error) {
    loadError.value = normalizeError(error, 'Tracking retur sales belum bisa dimuat.');
    items.value = [];
    selectedRow.value = null;
    summary.value = {
      total_requests: 0,
      pending_requests: 0,
      kpr_requests: 0,
      processed_requests: 0,
      on_process_requests: 0,
      canceled_requests: 0,
      total_amount: 0
    };
  } finally {
    loading.value = false;
  }
}

async function loadReturDetail(idRequest) {
  detailLoading.value = true;
  detailError.value = '';
  detailFeedback.value = '';

  try {
    const response = await getReturDetail(idRequest);
    const payload = unwrapResponse(response) || {};
    detailHeader.value = payload?.header || {};
    detailRows.value = normalizeList(payload?.detail || payload?.data || payload).map(normalizeDetailRow);
  } catch (error) {
    detailError.value = normalizeError(error, 'Detail retur belum bisa dimuat.');
    detailHeader.value = {};
    detailRows.value = [];
  } finally {
    detailLoading.value = false;
  }
}

async function openDetailModal(row = selectedRow.value) {
  if (!row?.id_request) {
    return;
  }

  selectedRow.value = row;
  detailOpen.value = true;
  resetDetailState();
  await loadReturDetail(row.id_request);
}

async function handleApproveSpv() {
  if (!selectedRow.value?.id_request || !detailHeader.value?.kode_kpr) {
    return;
  }

  actionLoading.value = true;
  detailError.value = '';
  detailFeedback.value = '';

  try {
    await approveReturBySpv(selectedRow.value.id_request, {
      kode_kpr: detailHeader.value.kode_kpr
    });
    detailFeedback.value = 'Retur berhasil diapprove SPV. KPR dicetak dan status retur dinaikkan ke tahap berikutnya.';
    await loadReturRows(selectedRow.value.id_request);
    if (selectedRow.value?.id_request) {
      await loadReturDetail(selectedRow.value.id_request);
    }
    printReturDocument('kpr');
  } catch (error) {
    detailError.value = normalizeError(error, 'KPR belum berhasil dicetak.');
  } finally {
    actionLoading.value = false;
  }
}

async function handleCancelSpv() {
  if (!selectedRow.value?.id_request) {
    return;
  }

  const reason = window.prompt('Alasan batal oleh SPV?', 'Tidak disetujui SPV');
  if (reason === null) {
    return;
  }

  actionLoading.value = true;
  detailError.value = '';
  detailFeedback.value = '';

  try {
    await cancelReturBySpv(selectedRow.value.id_request, {
      reason: reason.trim() || 'Tidak disetujui SPV'
    });
    detailFeedback.value = 'Retur berhasil dibatalkan oleh SPV.';
    detailOpen.value = false;
    await loadReturRows();
  } catch (error) {
    detailError.value = normalizeError(error, 'Retur belum berhasil dibatalkan oleh SPV.');
  } finally {
    actionLoading.value = false;
  }
}

function printReturDocument(type = 'retur') {
  if (!detailRows.value.length) {
    detailError.value = 'Detail barang retur belum tersedia untuk dicetak.';
    return;
  }

  const header = detailHeader.value || {};
  const row = selectedRow.value || {};
  const title = type === 'kpr' ? 'Kartu Penerimaan Retur' : 'Dokumen Retur Barang';
  const requestCode = header.kode_request || row.kode_request || '-';
  const noFaktur = header.no_faktur || row.no_faktur || '-';
  const kodeKpr = header.kode_kpr || row.kode_kpr || '-';
  const totalRetur = detailRows.value.reduce((acc, item) => acc + Number(item.total_retur || item.subtotal_retur || 0), 0);
  const rowsHtml = detailRows.value.map((item, index) => `
    <tr>
      <td>${index + 1}</td>
      <td>${escapeHtml(item.kode_sku || '-')}<br><strong>${escapeHtml(item.nama_produk || '-')}</strong></td>
      <td>${escapeHtml(item.alasan_retur || '-')}</td>
      <td>${formatQtyLabel(item.pieces_diajukan, item.box_diajukan, item.karton_diajukan)}</td>
      <td>${formatQtyLabel(item.pieces_good_diajukan, item.box_good_diajukan, item.karton_good_diajukan)}</td>
      <td class="right">${formatCurrency(item.harga_satuan)}</td>
      <td class="right">${formatCurrency(item.subtotal_retur || item.total_retur)}</td>
    </tr>
  `).join('');
  const tableHeader = '<tr><th>No</th><th>Produk</th><th>Alasan</th><th>Bad Stock</th><th>Good Stock</th><th>Harga</th><th>Subtotal</th></tr>';
  const signatureLabels = ['Sales', 'Gudang', 'Admin Retur', 'Customer'];

  const win = window.open('', '_blank', 'width=1120,height=820');
  if (!win) return;

  win.document.write(`
    <html>
      <head>
        <title>${escapeHtml(title)} ${escapeHtml(row.kode_request || '')}</title>
        <style>
          * { box-sizing: border-box; }
          body { font-family: Arial, sans-serif; margin: 28px; color: #0f172a; }
          h1 { margin: 0; font-size: 22px; text-transform: uppercase; letter-spacing: .08em; }
          .header { display: flex; justify-content: space-between; gap: 24px; border-bottom: 2px solid #0f172a; padding-bottom: 16px; }
          .muted { color: #64748b; font-size: 12px; }
          .notice { margin-top: 16px; border: 1px solid #94a3b8; padding: 10px; font-size: 12px; color: #334155; }
          .grid { margin-top: 18px; display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
          .card { border: 1px solid #cbd5e1; border-radius: 10px; padding: 10px; }
          .label { color: #64748b; font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }
          .value { margin-top: 5px; font-weight: 700; }
          table { width: 100%; border-collapse: collapse; margin-top: 18px; font-size: 12px; }
          th, td { border: 1px solid #cbd5e1; padding: 8px; vertical-align: top; }
          th { background: #f1f5f9; text-align: left; text-transform: uppercase; font-size: 11px; }
          .right { text-align: right; }
          .signature { margin-top: 42px; display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; text-align: center; font-size: 12px; }
          .line { margin-top: 58px; border-top: 1px solid #0f172a; padding-top: 8px; }
          @media print { body { margin: 16mm; } }
        </style>
      </head>
      <body>
        <div class="header">
          <div>
            <h1>${escapeHtml(title)}</h1>
            <p class="muted">${escapeHtml(row.nama_principal || header.nama_principal || '')}</p>
          </div>
          <div class="right">
            <strong>${escapeHtml(requestCode)}</strong><br>
            <span class="muted">${formatDate(header.tanggal_retur || row.tanggal_retur || header.tanggal_request || row.tanggal_request)}</span>
          </div>
        </div>
        <section class="grid">
          <div class="card"><div class="label">Customer</div><div class="value">${escapeHtml(header.nama || row.nama_customer || '-')}</div></div>
          <div class="card"><div class="label">No Faktur</div><div class="value">${escapeHtml(noFaktur)}</div></div>
          <div class="card"><div class="label">Kode KPR</div><div class="value">${escapeHtml(kodeKpr)}</div></div>
          <div class="card"><div class="label">Total Retur</div><div class="value">${formatCurrency(totalRetur || row.total_retur || header.total_retur)}</div></div>
        </section>
        <table>
          <thead>${tableHeader}</thead>
          <tbody>${rowsHtml}</tbody>
        </table>
        <section class="signature">
          ${signatureLabels.map((label) => `<div><div class="line">${escapeHtml(label)}</div></div>`).join('')}
        </section>
      </body>
    </html>
  `);
  win.document.close();
  win.focus();
  win.print();
}

async function handleProcessReturStock() {
  if (!selectedRow.value?.id_request) {
    return;
  }

  actionLoading.value = true;
  detailError.value = '';
  detailFeedback.value = '';

  try {
    await submitReturStock(selectedRow.value.id_request, buildReturStockPayload());
    detailFeedback.value = 'Retur sudah dikirim ke antrean QC Karantina WMS. Belum ada stok maupun Credit Note yang berubah; petugas gudang menentukan hasil GOOD/BAD setelah barang fisik diterima.';
    await loadReturRows(selectedRow.value.id_request);
    if (selectedRow.value?.id_request) {
      await loadReturDetail(selectedRow.value.id_request);
    }
  } catch (error) {
    detailError.value = normalizeError(error, 'Retur belum berhasil dikirim ke QC Gudang.');
  } finally {
    actionLoading.value = false;
  }
}

async function handleCancelDriver() {
  if (!selectedRow.value?.id_request) {
    return;
  }

  const reason = window.prompt('Alasan batal oleh driver?', 'Barang retur tidak sesuai');
  if (reason === null) {
    return;
  }

  actionLoading.value = true;
  detailError.value = '';
  detailFeedback.value = '';

  try {
    await cancelReturByDriver(selectedRow.value.id_request, {
      reason: reason.trim() || 'Barang retur tidak sesuai'
    });
    detailFeedback.value = 'Retur berhasil dibatalkan oleh driver.';
    detailOpen.value = false;
    await loadReturRows();
  } catch (error) {
    detailError.value = normalizeError(error, 'Retur belum berhasil dibatalkan oleh driver.');
  } finally {
    actionLoading.value = false;
  }
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

  await loadReturRows();
});

watch(
  () => filters.companyId,
  (companyId, previousCompanyId) => {
    if (companyId === previousCompanyId) return;

    if (!companyId) {
      filters.branchId = '';
    } else if (filters.branchId) {
      const currentBranch = branchRows.value.find((item) => String(item.id) === String(filters.branchId));
      if (!branchMatchesCompany(currentBranch, companyId)) {
        filters.branchId = '';
      }
    }
    filters.salesUserId = canUseLoginScope.value && fallbackUserId.value ? String(fallbackUserId.value) : '';
    items.value = [];
    selectedRow.value = null;
  }
);

watch(
  () => filters.branchId,
  (branchId, previousBranchId) => {
    if (branchId === previousBranchId) return;

    filters.salesUserId = canUseLoginScope.value && fallbackUserId.value ? String(fallbackUserId.value) : '';
    items.value = [];
    selectedRow.value = null;
  }
);
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Monitoring Retur"
      description="Pantau request retur dari sisi sales. Stok berubah setelah QC WMS; setelah QC selesai, Finance menerbitkan Credit Note secara terkontrol."
    >
      <div class="flex flex-wrap gap-2">
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="loadReturRows">
          Refresh Data
        </button>
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="router.push({ name: 'sales-order-retur', query: salesQuery() })">
          Buka Form Retur
        </button>
        <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700" @click="router.push({ name: 'sales-order-list', query: salesQuery() })">
          Kembali ke Order Sales
        </button>
      </div>
    </PageHeader>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Total Request</p>
        <p class="mt-3 text-2xl font-semibold text-slate-900">{{ summary.total_requests.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Pending</p>
        <p class="mt-3 text-2xl font-semibold text-slate-900">{{ summary.pending_requests.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">On Proses</p>
        <p class="mt-3 text-2xl font-semibold text-slate-900">{{ Number(summary.on_process_requests || (summary.kpr_requests + summary.processed_requests) || 0).toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Nilai Retur</p>
        <p class="mt-3 text-2xl font-semibold text-slate-900">Rp {{ Number(summary.total_amount || 0).toLocaleString('id-ID') }}</p>
      </article>
    </section>

    <AppFilterBar
      :model-value="filters"
      :fields="filterFields"
      @update:model-value="updateFilters"
      @submit="loadReturRows"
      @reset="resetFilters"
    />

    <div v-if="loadError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ loadError }}
    </div>

    <section class="panel p-5">
      <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 class="text-lg font-semibold text-slate-900">Daftar Retur</h3>
          <p class="mt-1 text-sm text-slate-500">Klik salah satu retur untuk membuka ringkasan, detail produk, dan aksi operasional retur.</p>
        </div>
        <div class="text-sm text-slate-500">
          Diproses: <span class="font-semibold text-slate-900">{{ summary.processed_requests.toLocaleString('id-ID') }}</span>
        </div>
      </div>

      <AppTable
        :columns="tableColumns"
        :rows="normalizedRows"
        :loading="loading"
        row-key="row_key"
        :selected-key="selectedKey"
        :clickable-rows="true"
        empty-message="Belum ada retur yang cocok dengan filter."
        @row-click="openDetailModal($event)"
      />
    </section>

    <AppModal
      :open="detailOpen"
      title="Detail Retur Operasional"
      panel-class="max-w-6xl"
      @close="detailOpen = false"
    >
      <div v-if="detailFeedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
        {{ detailFeedback }}
      </div>
      <div v-if="detailError" class="mt-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
        {{ detailError }}
      </div>

      <div v-if="detailLoading" class="py-10 text-center text-sm text-slate-500">
        Memuat detail retur...
      </div>

      <div v-else class="space-y-5">
        <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-slate-400">Status</p>
            <p class="mt-2 font-semibold text-slate-900">{{ resolveReturBusinessStatus(selectedRow) }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-slate-400">Kode Request</p>
            <p class="mt-2 font-semibold text-slate-900">{{ selectedRow?.kode_request || '-' }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-slate-400">Kode KPR</p>
            <p class="mt-2 font-semibold text-slate-900">{{ detailHeader.kode_kpr || selectedRow?.kode_kpr || '-' }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-slate-400">No CN</p>
            <p class="mt-2 font-semibold text-slate-900">{{ selectedRow?.no_cn || '-' }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-slate-400">Customer</p>
            <p class="mt-2 font-semibold text-slate-900">{{ detailHeader.nama || selectedRow?.nama_customer || '-' }}</p>
          </article>
        </section>

        <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
          <p v-if="selectedStatus === '0'">Tahap ini menyiapkan dokumen KPR. Setelah dicetak, barang harus diterima fisik melalui QC Karantina WMS.</p>
          <template v-else-if="selectedStatus === '1'">
            <p>KPR sudah siap. Kirim retur ke QC Karantina WMS ketika barang fisik tiba di gudang.</p>
            <p class="mt-2 text-xs">Aksi ini hanya membuat antrean QC. <span class="font-semibold text-emerald-700">GOOD</span> baru masuk rak/stock ready setelah QC, sedangkan <span class="font-semibold text-rose-700">BAD</span> masuk stok bad setelah QC. Credit Note tidak dibuat otomatis.</p>
          </template>
          <template v-else-if="selectedStatus === '2'">
            <p>Barang retur sedang menunggu QC Gudang. Stok dan Credit Note belum berubah.</p>
          </template>
          <template v-else-if="selectedStatus === '4'">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <p>QC Gudang sudah selesai. Hasil GOOD/BAD sudah menjadi dasar stok WMS; Finance dapat menerbitkan Credit Note dari menu Credit Note.</p>
              <button
                class="rounded-xl bg-brand-600 px-3 py-2 text-xs font-semibold text-white hover:bg-brand-700"
                @click="router.push({ name: 'finance-credit-note', query: { search: selectedRow?.kode_request || detailHeader.kode_kpr || '' } })"
              >
                Buka Credit Note
              </button>
            </div>
          </template>
          <p v-else-if="selectedStatus === '9'">Retur ini sudah dibatalkan dan tidak aktif.</p>
          <p v-else>Detail ini sudah masuk tahap akhir retur. Nomor credit note dan nilai retur akan dipakai sebagai referensi finance.</p>
        </div>

        <div class="overflow-x-auto rounded-2xl border border-slate-200">
          <table class="min-w-full divide-y divide-slate-200 text-sm">
            <thead class="bg-slate-50 text-left text-xs uppercase tracking-[0.2em] text-slate-500">
              <tr>
                <th class="px-4 py-3">Produk</th>
                <th class="px-4 py-3">Pengajuan Bad</th>
                <th class="px-4 py-3">Pengajuan Good</th>
                <th class="px-4 py-3">Total Retur</th>
                <th class="px-4 py-3">Rencana Bad</th>
                <th class="px-4 py-3">Rencana Good</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 bg-white">
              <tr v-for="row in detailTableRows" :key="row.row_key">
                <td class="px-4 py-3 align-top">
                  <p class="font-semibold text-slate-900">{{ row.nama_produk || '-' }}</p>
                  <p class="mt-1 text-xs text-slate-500">{{ row.kode_sku || '-' }}</p>
                  <p class="mt-1 text-xs text-slate-400">{{ row.alasan_retur || '-' }}</p>
                </td>
                <td class="px-4 py-3 align-top text-slate-600">{{ row.qty_request_bad_label }}</td>
                <td class="px-4 py-3 align-top text-slate-600">{{ row.qty_request_good_label }}</td>
                <td class="px-4 py-3 align-top text-slate-600">{{ row.qty_total_label }}</td>
                <td class="px-4 py-3 align-top">
                  <div class="grid gap-2 md:grid-cols-3">
                    <label class="grid gap-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                      {{ formatDetailUomLabel(row, 1) }}
                      <input
                        :value="row.accepted_bad_pieces"
                        type="number"
                        min="0"
                        :disabled="true"
                        class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-normal tracking-normal text-slate-900 outline-none focus:border-brand-400 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:disabled:bg-slate-800 dark:disabled:text-slate-400"
                        @input="updateAcceptedField(row, 'accepted_bad_pieces', $event.target.value)"
                      >
                    </label>
                    <label class="grid gap-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                      {{ formatDetailUomLabel(row, 2) }}
                      <input
                        :value="row.accepted_bad_box"
                        type="number"
                        min="0"
                        :disabled="true"
                        class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-normal tracking-normal text-slate-900 outline-none focus:border-brand-400 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:disabled:bg-slate-800 dark:disabled:text-slate-400"
                        @input="updateAcceptedField(row, 'accepted_bad_box', $event.target.value)"
                      >
                    </label>
                    <label class="grid gap-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                      {{ formatDetailUomLabel(row, 3) }}
                      <input
                        :value="row.accepted_bad_karton"
                        type="number"
                        min="0"
                        :disabled="true"
                        class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-normal tracking-normal text-slate-900 outline-none focus:border-brand-400 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:disabled:bg-slate-800 dark:disabled:text-slate-400"
                        @input="updateAcceptedField(row, 'accepted_bad_karton', $event.target.value)"
                      >
                    </label>
                  </div>
                </td>
                <td class="px-4 py-3 align-top">
                  <div class="grid gap-2 md:grid-cols-3">
                    <label class="grid gap-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                      {{ formatDetailUomLabel(row, 1) }}
                      <input
                        :value="row.accepted_good_pieces"
                        type="number"
                        min="0"
                        :disabled="true"
                        class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-normal tracking-normal text-slate-900 outline-none focus:border-brand-400 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:disabled:bg-slate-800 dark:disabled:text-slate-400"
                        @input="updateAcceptedField(row, 'accepted_good_pieces', $event.target.value)"
                      >
                    </label>
                    <label class="grid gap-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                      {{ formatDetailUomLabel(row, 2) }}
                      <input
                        :value="row.accepted_good_box"
                        type="number"
                        min="0"
                        :disabled="true"
                        class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-normal tracking-normal text-slate-900 outline-none focus:border-brand-400 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:disabled:bg-slate-800 dark:disabled:text-slate-400"
                        @input="updateAcceptedField(row, 'accepted_good_box', $event.target.value)"
                      >
                    </label>
                    <label class="grid gap-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                      {{ formatDetailUomLabel(row, 3) }}
                      <input
                        :value="row.accepted_good_karton"
                        type="number"
                        min="0"
                        :disabled="true"
                        class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-normal tracking-normal text-slate-900 outline-none focus:border-brand-400 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:disabled:bg-slate-800 dark:disabled:text-slate-400"
                        @input="updateAcceptedField(row, 'accepted_good_karton', $event.target.value)"
                      >
                    </label>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="flex flex-wrap justify-end gap-2">
          <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="detailOpen = false">
            Tutup
          </button>
          <button
            v-if="selectedRow"
            class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            @click="
              router.push({
                name: 'sales-order-retur',
                query: {
                  ...salesQuery(),
                  id_sales_order: selectedRow.id_sales_order,
                  id_sales: filters.salesUserId || fallbackUserId,
                  id_plafon: selectedRow.id_plafon,
                  no_order: selectedRow.no_order,
                  no_faktur: selectedRow.no_faktur,
                  customer_name: selectedRow.nama_customer
                }
              })
            "
          >
            Buka Form Retur
          </button>
          <button
            v-if="selectedRow"
            class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            @click="
              router.push({
                name: 'distribution-invoices',
                query: {
                  stage: selectedRow.status_order >= 4 ? 'realisasi' : 'shipping',
                  id_cabang: selectedRow.id_cabang,
                  sales_order_id: selectedRow.id_sales_order
                }
              })
            "
          >
            Buka Faktur Terkait
          </button>
          <button
            class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60"
            :disabled="!canPrintReturDocument"
            @click="printReturDocument('retur')"
          >
            Cetak Dokumen Retur
          </button>
          <button
            v-if="selectedStatus === '0'"
            class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
            :disabled="!canPrintKpr"
            @click="handleApproveSpv"
          >
            {{ actionLoading ? 'Memproses...' : 'Approve SPV & Cetak KPR' }}
          </button>
          <button
            v-if="selectedStatus === '0'"
            class="rounded-xl border border-rose-200 px-4 py-2 text-sm font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-60 dark:border-rose-900/60 dark:text-rose-300 dark:hover:bg-rose-950/30"
            :disabled="!canCancelSpv"
            @click="handleCancelSpv"
          >
            {{ actionLoading ? 'Memproses...' : 'Batal SPV' }}
          </button>
          <button
            v-if="selectedStatus === '1'"
            class="rounded-xl border border-rose-200 px-4 py-2 text-sm font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-60 dark:border-rose-900/60 dark:text-rose-300 dark:hover:bg-rose-950/30"
            :disabled="!canCancelDriver"
            @click="handleCancelDriver"
          >
            {{ actionLoading ? 'Memproses...' : 'Batal Driver' }}
          </button>
          <button
            v-if="selectedStatus === '1'"
            class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
            :disabled="!canProcessReturStock"
            @click="handleProcessReturStock"
          >
            {{ actionLoading ? 'Memproses...' : 'Kirim ke QC Gudang' }}
          </button>
        </div>
      </div>
    </AppModal>
  </div>
</template>
