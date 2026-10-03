<script setup>
import { computed, onDeactivated, onMounted, reactive, ref, watch } from 'vue';
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router';
import { createFleetScheduleFromSalesOrders, getFleetSchedules, updateFleetSchedule, getDraftVariantPickingNote } from '@/api/distribution';
import { MAX_PRINT_DRAFTS, shipmentKey, shipmentReference, shipmentPrintError, prepareShipmentDocument, buildShipmentDraftsHtml } from '@/utils/shipmentDraftPrint';
import { formatPrintDate, openPrintHtml, reservePrintWindow } from '@/utils/printTemplates';
import { getBranches, getCompanies, getDrivers, getFleets, getHelpers } from '@/api/master';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getLoginCompanyId, getRowBranchIds, getRowCompanyId, getRowCompanyIds, isSuperUser as resolveIsSuperUser } from '@/utils/accessScope';
import { getBranchOptionsForCompany, getCompanyOptionsForScope } from '@/utils/filterScope';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import ScheduleDraftCreateModal from '../components/ScheduleDraftCreateModal.vue';

const authStore = useAuthStore();
const route = useRoute();
const router = useRouter();

const filters = reactive({
  branchId: '',
  companyId: '',
  view: 'draft',
  search: ''
});

const scheduleForm = reactive({
  id_proses_picking: '',
  id_armada: '',
  id_driver: '',
  helperIds: [],
  dock_code: '',
  cargo_zone: '',
  delivery_notes: '',
  volume_unit: '',
  tanggal_pengiriman: ''
});

const companyRows = ref([]);
const branchRows = ref([]);
const fleetRows = ref([]);
const driverRows = ref([]);
const helperRows = ref([]);
const feedback = ref('');
const errorMessage = ref('');
const saving = ref(false);
const selectedRow = ref(null);
const detailOpen = ref(false);
const createDraftOpen = ref(false);
const items = ref([]);
const loading = ref(false);
const printing = ref(false);
const printProgress = ref('');
const checkedDrafts = ref({});
const loadedScope = ref('');
let scheduleRequest = 0;
const scopeKey = computed(() => JSON.stringify([filters.companyId, getActiveBranchId()]));
const draftRows = computed(() => filteredRows.value.filter(row => !shipmentPrintError(row)));
const selectedDrafts = computed(() => draftRows.value.filter(row => checkedDrafts.value[shipmentKey(row)]));
const selectionReady = computed(() => !loading.value && !printing.value && loadedScope.value === scopeKey.value);
const allDraftsChecked = computed(() => draftRows.value.length > 0 && draftRows.value.every(row => checkedDrafts.value[shipmentKey(row)]));
const someDraftsChecked = computed(() => selectedDrafts.value.length > 0 && !allDraftsChecked.value);
watch(() => JSON.stringify(filters), () => { checkedDrafts.value = {}; });

function selectDraft(row, event) {
  const checked = event.target.checked;
  event.target.checked = !!checkedDrafts.value[shipmentKey(row)];
  if (!selectionReady.value || shipmentPrintError(row)) return;
  const next = { ...checkedDrafts.value };
  if (checked) next[shipmentKey(row)] = true;
  else delete next[shipmentKey(row)];
  if (Object.keys(next).length > MAX_PRINT_DRAFTS) {
    errorMessage.value = `Maksimal ${MAX_PRINT_DRAFTS} draf per cetakan.`;
    return;
  }
  checkedDrafts.value = next;
  errorMessage.value = '';
}
function selectAllDrafts(event) {
  const checked = event.target.checked;
  event.target.checked = allDraftsChecked.value;
  event.target.indeterminate = someDraftsChecked.value;
  if (!selectionReady.value) return;
  if (checked && draftRows.value.length > MAX_PRINT_DRAFTS) {
    errorMessage.value = `Hasil filter lebih dari ${MAX_PRINT_DRAFTS} draf. Persempit pencarian atau pilih satu per satu.`;
    return;
  }
  checkedDrafts.value = checked ? Object.fromEntries(draftRows.value.map(row => [shipmentKey(row), true])) : {};
  errorMessage.value = '';
}
async function printDrafts(rows) {
  if (!selectionReady.value || !rows.length) return;
  if (rows.length > MAX_PRINT_DRAFTS) { errorMessage.value = `Maksimal ${MAX_PRINT_DRAFTS} draf per cetakan.`; return; }
  const snapshot = rows.map(row => ({ ...row }));
  const popup = reservePrintWindow({ width: 1280, height: 820 });
  if (!popup) { errorMessage.value = 'Popup cetak diblokir. Izinkan popup untuk ERP lalu coba kembali.'; return; }
  printing.value = true; feedback.value = ''; errorMessage.value = '';
  popup.document.write('<!doctype html><title>Menyiapkan draf kiriman</title><p style="font-family:Arial;padding:24px">Menyiapkan seluruh draf. Cetak dimulai setelah semua data berhasil dimuat…</p>');
  popup.document.close();
  try {
    const documents = [];
    for (const row of snapshot) {
      if (popup.closed) throw new Error('Jendela cetak ditutup. Tidak ada draf yang dicetak.');
      printProgress.value = `Menyiapkan draf ${documents.length + 1} dari ${snapshot.length}…`;
      const response = await getDraftVariantPickingNote({ id_cabang: row.id_cabang, id_rute: row.id_rute,
        id_armada: row.id_armada, id_driver: row.id_driver, delivering_date: row.delivering_date,
        id_proses_picking: row.id_proses_picking });
      documents.push(prepareShipmentDocument(row, unwrapResponse(response)));
    }
    if (popup.closed) throw new Error('Jendela cetak ditutup. Silakan cetak kembali.');
    popup.document.open();
    openPrintHtml(`Draf Kiriman (${documents.length})`, buildShipmentDraftsHtml(documents), { printWindow: popup, delay: 500 });
    feedback.value = `${documents.length} draf siap dicetak dalam satu jendela, setiap draf dimulai pada halaman baru. Stok dan status tidak berubah.`;
  } catch (error) {
    if (!popup.closed) popup.close();
    errorMessage.value = `${normalizeError(error, 'Draf belum dapat dicetak.')} Seluruh cetakan dibatalkan; pilihan tetap disimpan.`;
  } finally { printing.value = false; printProgress.value = ''; }
}
const preselectedSalesOrderId = computed(() => String(route.query.sales_order_id || '').trim());
const routeContextInfo = computed(() => ({
  noOrder: String(route.query.no_order || '').trim(),
  customerName: String(route.query.customer_name || '').trim(),
  routeName: String(route.query.route_name || '').trim()
}));
const scheduleRouteAction = computed(() => String(route.query.schedule_action || '').trim().toLowerCase());
const hasExplicitScheduleAction = computed(() => ['create', 'edit'].includes(scheduleRouteAction.value));
const scheduleRouteContextKeys = [
  'schedule_action',
  'sales_order_id',
  'id_proses_picking',
  'id_armada',
  'id_driver',
  'helper_ids',
  'id_helper',
  'tanggal_pengiriman',
  'no_order',
  'customer_name',
  'route_name'
];

const isSuperUser = computed(() => resolveIsSuperUser(authStore));
const canCreateDraft = computed(() => isSuperUser.value || ['distribution.schedules.update', 'm.distribusi.jd.update'].some(permission => authStore.hasPermission(permission)));
const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(authStore.user));
const canUseLoginScope = computed(() => !isSuperUser.value);

function companyIdsForBranch(branchId) {
  if (!branchId) return [];

  const ids = new Set();
  const branch = branchRows.value.find((item) => String(item.id) === String(branchId));
  const branchCompanyId = getRowCompanyId(branch);

  if (branchCompanyId) ids.add(String(branchCompanyId));

  companyRows.value.forEach((item) => {
    if (getRowBranchIds(item).includes(String(branchId))) {
      ids.add(String(item.id));
    }
  });

  return Array.from(ids);
}

const companyOptions = computed(() => getCompanyOptionsForScope(companyRows.value, authStore));

const branchOptions = computed(() =>
  getBranchOptionsForCompany(branchRows.value, authStore, filters.companyId)
);

const activeBranchId = computed(() => getActiveBranchId());
const activeCompanyName = computed(() => companyOptions.value.find(item => String(item.value) === filters.companyId)?.label || '');
const activeBranchName = computed(() => {
  const branch = branchRows.value.find(item => String(item.id) === String(activeBranchId.value));
  return branchOptions.value.find(item => String(item.value) === String(activeBranchId.value))?.label || branch?.nama || branch?.nama_cabang || '';
});
const activeCompanyIds = computed(() => {
  if (filters.companyId) return [String(filters.companyId)];
  return companyIdsForBranch(activeBranchId.value);
});

const filterFields = computed(() => [
  { key: 'companyId', label: 'Perusahaan', type: 'search-select', options: companyOptions.value, placeholder: 'Pilih perusahaan', disabled: canUseLoginScope.value && !!fallbackCompanyId.value },
  { key: 'branchId', label: 'Cabang', type: 'search-select', options: branchOptions.value, placeholder: filters.companyId ? 'Pilih cabang' : 'Pilih perusahaan dahulu', emptyText: filters.companyId ? 'Cabang belum tersedia.' : 'Pilih perusahaan dahulu.', disabled: !filters.companyId || (!isSuperUser.value && !!fallbackBranchId.value) },
  { key: 'view', label: 'Tampilkan', type: 'select', options: [{ value: 'draft', label: 'Draf Kiriman' }, { value: 'all', label: 'Semua Jadwal' }] },
  { key: 'search', label: 'Cari jadwal', placeholder: 'Rute, armada, driver, faktur, sales order' }
]);

const fleetOptions = computed(() =>
  fleetRows.value
    .filter((item) => {
      if (!activeBranchId.value && !activeCompanyIds.value.length) return true;
      if (activeBranchId.value && item.id_cabang && String(item.id_cabang) === String(activeBranchId.value)) return true;
      const rowCompanyIds = getRowCompanyIds(item);
      return activeCompanyIds.value.some((id) => rowCompanyIds.includes(String(id)));
    })
    .map((item) => ({
      value: String(item.id),
      label: `${item.no_pelat || item.no_polisi || item.kode || '-'} - ${item.nama || 'Armada'}`
    }))
);

const driverOptions = computed(() =>
  driverRows.value
    .filter((item) => !activeBranchId.value || !item.id_cabang || String(item.id_cabang) === String(activeBranchId.value))
    .map((item) => ({
      value: String(item.id),
      label: `${item.nama || item.nama_driver || 'Driver'}${item.no_hp ? ` - ${item.no_hp}` : ''}`
    }))
);

const helperOptions = computed(() =>
  helperRows.value
    .filter((item) => !activeBranchId.value || !item.id_cabang || String(item.id_cabang) === String(activeBranchId.value))
    .map((item) => ({
      value: String(item.id),
      label: `${item.nama || item.nama_helper || 'Helper'}${item.no_hp ? ` - ${item.no_hp}` : ''}`
    }))
);

const filteredRows = computed(() => {
  const query = filters.search.trim().toLowerCase();
  const scoped = items.value.filter(item =>
    (!filters.companyId || String(item.id_perusahaan) === String(filters.companyId)) &&
    (filters.view !== 'draft' || !shipmentPrintError(item))
  );
  if (!query) {
    return scoped;
  }

  return scoped.filter((item) =>
    [
      item.nama_rute,
      item.kode_rute,
      item.nama_armada,
      item.nama_driver,
      item.nama_helpers,
      item.nama_helper,
      item.delivering_date,
      item.id_faktur,
      item.id_sales_order,
      item.no_order,
      item.nama_customer,
      shipmentReference(item)
    ]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query))
  );
});

const fallbackScheduleRow = computed(() => {
  if (!hasExplicitScheduleAction.value || filteredRows.value.length || (!preselectedSalesOrderId.value && !routeContextInfo.value.noOrder)) {
    return null;
  }

  return {
    id_proses_picking: route.query.id_proses_picking || `draft-${preselectedSalesOrderId.value || routeContextInfo.value.noOrder}`,
    id_sales_order: preselectedSalesOrderId.value || '-',
    primary_sales_order_id: preselectedSalesOrderId.value || '-',
    no_order: routeContextInfo.value.noOrder || '-',
    nama_customer: routeContextInfo.value.customerName || '-',
    nama_rute: routeContextInfo.value.routeName || '-',
    kode_rute: '-',
    nama_armada: route.query.id_armada ? `Armada #${route.query.id_armada}` : 'Belum dijadwalkan',
    nama_driver: route.query.id_driver ? `Driver #${route.query.id_driver}` : 'Belum dijadwalkan',
    nama_helpers: helperLabelFromIds(route.query.helper_ids || route.query.id_helper) || 'Belum dijadwalkan',
    delivering_date: route.query.tanggal_pengiriman || '-',
    id_faktur: '-',
    sales_order_count: 1,
    __draft_schedule: true
  };
});

const tableRows = computed(() => (fallbackScheduleRow.value ? [fallbackScheduleRow.value] : filteredRows.value));
const showScheduleHint = computed(() => !loading.value && !tableRows.value.length);
const isMergedSchedule = computed(() => Number(selectedRow.value?.sales_order_count || 0) > 1);
const selectedSalesOrderIds = computed(() =>
  parseCsvIds(selectedRow.value?.id_sales_order || selectedRow.value?.primary_sales_order_id || preselectedSalesOrderId.value).filter((value) => /^\d+$/.test(value))
);

function getActiveBranchId() {
  return filters.branchId || String(fallbackBranchId.value || '');
}

function openCreateDraft() {
  if (!canCreateDraft.value || loading.value || printing.value) return;
  if (!filters.companyId || !activeBranchId.value) {
    showScheduleMessage('error', 'Pilih perusahaan dan cabang sebelum membuat draf kiriman.');
    return;
  }
  resetForm();
  feedback.value = '';
  errorMessage.value = '';
  createDraftOpen.value = true;
}

async function draftCreated(message) {
  createDraftOpen.value = false;
  await clearScheduleRouteContext();
  filters.view = 'draft';
  filters.search = '';
  await loadSchedules();
  feedback.value = message || 'Draf kiriman berhasil dibuat.';
  if (errorMessage.value) errorMessage.value = `Draf sudah tersimpan, tetapi daftar belum dapat dimuat ulang. ${errorMessage.value}`;
}

watch(scopeKey, () => { createDraftOpen.value = false; });

function normalizeHelperIds(value) {
  let values = value;
  if (typeof values === 'string') {
    try {
      values = JSON.parse(values);
    } catch {
      values = values.split(',');
    }
  }
  if (!Array.isArray(values)) values = [values];

  return Array.from(new Set(
    values
      .map((item) => (typeof item === 'object' && item !== null ? item.id || item.id_helper || item.value : item))
      .map((item) => String(item ?? '').trim())
      .filter(Boolean)
  ));
}

function helperLabelFromIds(value) {
  return normalizeHelperIds(value).map((id) => `Helper #${id}`).join(', ');
}

function scheduleHelperName(row) {
  return row?.nama_helpers || row?.nama_helper || helperLabelFromIds(row?.id_helpers || row?.id_helper) || '-';
}

function resetForm() {
  scheduleForm.id_proses_picking = '';
  scheduleForm.id_armada = '';
  scheduleForm.id_driver = '';
  scheduleForm.helperIds = [];
  scheduleForm.tanggal_pengiriman = '';
  scheduleForm.dock_code = '';
  scheduleForm.cargo_zone = '';
  scheduleForm.delivery_notes = '';
  scheduleForm.volume_unit = '';
  selectedRow.value = null;
  detailOpen.value = false;
}

function hasScheduleRouteContext() {
  return hasExplicitScheduleAction.value && scheduleRouteContextKeys.some((key) => route.query[key] !== undefined && route.query[key] !== '');
}

async function clearScheduleRouteContext() {
  if (!hasScheduleRouteContext()) return;

  const nextQuery = { ...route.query };
  scheduleRouteContextKeys.forEach((key) => {
    delete nextQuery[key];
  });

  await router.replace({ name: route.name, query: nextQuery });
}

async function closeScheduleModal() {
  detailOpen.value = false;
  await clearScheduleRouteContext();
}

function isValidIdList(value) {
  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
    .every((item) => /^\d+$/.test(item));
}

function parseCsvIds(value) {
  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function showScheduleMessage(type, message) {
  if (type === 'success') {
    feedback.value = message;
    errorMessage.value = '';
    return;
  }

  errorMessage.value = message;
  feedback.value = '';
}

function rowMatchesRouteContext(item) {
  const routePickingIds = parseCsvIds(route.query.id_proses_picking);
  const rowPickingIds = parseCsvIds(item?.id_proses_picking);
  const samePicking =
    routePickingIds.length > 0 &&
    routePickingIds.some((routeId) => rowPickingIds.includes(routeId));

  const rowSalesOrderIds = parseCsvIds(item?.id_sales_order);
  const sameSalesOrder =
    Boolean(preselectedSalesOrderId.value) &&
    rowSalesOrderIds.includes(preselectedSalesOrderId.value);

  const sameOrderNumber =
    Boolean(routeContextInfo.value.noOrder) &&
    String(item?.no_order || '')
      .split(',')
      .map((value) => value.trim().toLowerCase())
      .filter(Boolean)
      .includes(routeContextInfo.value.noOrder.toLowerCase());

  return samePicking || sameSalesOrder || sameOrderNumber;
}

async function loadOptions() {
  const [companyResponse, branchResponse, fleetResponse, driverResponse, helperResponse] = await Promise.all([
    getCompanies(),
    getBranches(),
    getFleets(),
    getDrivers(),
    getHelpers()
  ]);

  companyRows.value = normalizeList(unwrapResponse(companyResponse));
  branchRows.value = normalizeList(unwrapResponse(branchResponse));
  fleetRows.value = normalizeList(unwrapResponse(fleetResponse));
  driverRows.value = normalizeList(unwrapResponse(driverResponse));
  helperRows.value = normalizeList(unwrapResponse(helperResponse));

  if (!filters.companyId && canUseLoginScope.value && fallbackCompanyId.value) {
    filters.companyId = String(fallbackCompanyId.value);
  }
  if (!filters.branchId && fallbackBranchId.value) {
    filters.branchId = String(fallbackBranchId.value);
  }
  syncBranchFromCompany();
}

async function loadSchedules() {
  const requestId = ++scheduleRequest;
  const requestedScope = scopeKey.value;
  loading.value = true;
  checkedDrafts.value = {};
  feedback.value = '';
  errorMessage.value = '';

  try {
    const branchId = getActiveBranchId();
    const response = await getFleetSchedules({ ...(branchId ? { id_cabang: branchId } : {}), id_perusahaan: filters.companyId || undefined });
    if (requestId !== scheduleRequest || requestedScope !== scopeKey.value) return;
    items.value = normalizeList(unwrapResponse(response));
    loadedScope.value = requestedScope;
    applyRoutePrefill();
  } catch (error) {
    if (requestId !== scheduleRequest || requestedScope !== scopeKey.value) return;
    errorMessage.value = normalizeError(error, 'Jadwal armada belum bisa dimuat.');
    items.value = [];
    loadedScope.value = '';
  } finally {
    if (requestId === scheduleRequest) loading.value = false;
  }
}

function submit() {
  loadSchedules();
}

function reset() {
  filters.companyId = canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
  filters.branchId = fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  syncBranchFromCompany();
  filters.search = '';
  filters.view = 'draft';
  resetForm();
  loadSchedules();
}

function updateFilters(nextFilters) {
  const previousBranchId = filters.branchId;
  const previousCompanyId = filters.companyId;

  Object.assign(filters, nextFilters);

  if (filters.companyId !== previousCompanyId) {
    syncBranchFromCompany();
    resetForm();
    return;
  }

  if (filters.branchId !== previousBranchId) {
    resetForm();
  }
}

function syncBranchFromCompany() {
  if (!filters.companyId || !filters.branchId) {
    return;
  }

  if (!companyIdsForBranch(filters.branchId).includes(String(filters.companyId))) {
    filters.branchId = '';
  }
}

function openEdit(row) {
  selectedRow.value = row;
  scheduleForm.id_proses_picking = row?.id_proses_picking || '';
  scheduleForm.id_armada = row?.id_armada ? String(row.id_armada) : '';
  scheduleForm.id_driver = row?.id_driver ? String(row.id_driver) : '';
  scheduleForm.helperIds = normalizeHelperIds(row?.id_helpers || row?.id_helper);
  scheduleForm.tanggal_pengiriman = row?.delivering_date || '';
  scheduleForm.dock_code = row?.dock_code || '';
  scheduleForm.cargo_zone = row?.cargo_zone || '';
  scheduleForm.delivery_notes = row?.delivery_notes || '';
  scheduleForm.volume_unit = row?.volume_unit || '';
  feedback.value = '';
  errorMessage.value = '';
  detailOpen.value = true;
}

function applyRoutePrefill() {
  if (!hasExplicitScheduleAction.value) {
    return;
  }

  if (!filters.search) {
    filters.search = route.query.no_order || route.query.sales_order_id || '';
  }

  const pickedRow = items.value.find((item) => rowMatchesRouteContext(item));

  if (pickedRow) {
    openEdit(pickedRow);
    return;
  }

  if (preselectedSalesOrderId.value || route.query.id_proses_picking) {
    selectedRow.value = {
      id_sales_order: preselectedSalesOrderId.value || '-',
      primary_sales_order_id: preselectedSalesOrderId.value || '-',
      id_proses_picking: route.query.id_proses_picking || '-',
      nama_rute: routeContextInfo.value.routeName || '-',
      nama_customer: routeContextInfo.value.customerName || '-',
      no_order: routeContextInfo.value.noOrder || '-',
      id_faktur: '-',
      nama_helpers: helperLabelFromIds(route.query.helper_ids || route.query.id_helper) || '-',
      sales_order_count: 1
    };
    scheduleForm.id_proses_picking = String(route.query.id_proses_picking || '');
    scheduleForm.id_armada = String(route.query.id_armada || '');
    scheduleForm.id_driver = String(route.query.id_driver || '');
    scheduleForm.helperIds = normalizeHelperIds(route.query.helper_ids || route.query.id_helper);
    scheduleForm.tanggal_pengiriman = String(route.query.tanggal_pengiriman || '');
    scheduleForm.dock_code = '';
    scheduleForm.cargo_zone = '';
    scheduleForm.delivery_notes = '';
    scheduleForm.volume_unit = '';
    detailOpen.value = true;
  }
}

watch(
  () => filters.companyId,
  (value, previousValue) => {
    if (value === previousValue) return;
    syncBranchFromCompany();
    resetForm();
  }
);

watch(
  () => filters.branchId,
  (branchId, previousBranchId) => {
    if (branchId === previousBranchId) return;
    resetForm();
  }
);

async function saveSchedule() {
  feedback.value = '';
  errorMessage.value = '';

  if (!scheduleForm.dock_code.trim() || !['FOOD', 'NON_FOOD'].includes(scheduleForm.cargo_zone)) {
    showScheduleMessage('error', 'Isi loading dock dan pilih zona FOOD / NON-FOOD.');
    return;
  }
  if (!['CM3', 'M3'].includes(scheduleForm.volume_unit)) {
    showScheduleMessage('error', 'Pilih satuan estimasi volume sesuai data produk, agar utilisasi tidak salah hitung.');
    return;
  }

  if (!scheduleForm.id_armada || !scheduleForm.id_driver || !scheduleForm.tanggal_pengiriman) {
    showScheduleMessage('error', 'Lengkapi armada, driver, helper, dan tanggal pengiriman terlebih dahulu.');
    return;
  }

  if (!scheduleForm.helperIds.length) {
    showScheduleMessage('error', 'Pilih minimal satu helper atau kernet sebelum jadwal disimpan.');
    return;
  }

  saving.value = true;

  try {
    let message = '';

    if (scheduleForm.id_proses_picking && isValidIdList(scheduleForm.id_proses_picking)) {
      const res = await updateFleetSchedule({
        id_proses_picking: scheduleForm.id_proses_picking,
        id_armada: scheduleForm.id_armada,
        id_driver: scheduleForm.id_driver,
        id_helper: Number(scheduleForm.helperIds[0]),
        helper_ids: scheduleForm.helperIds.map((value) => Number(value)),
        tanggal_pengiriman: scheduleForm.tanggal_pengiriman,
        dock_code: scheduleForm.dock_code,
        cargo_zone: scheduleForm.cargo_zone,
        delivery_notes: scheduleForm.delivery_notes,
        volume_unit: scheduleForm.volume_unit
      });

      const data = unwrapResponse(res) || res;
      message = data?.message || 'Jadwal pengiriman berhasil diubah';
    } else if (selectedSalesOrderIds.value.length) {
      const res = await createFleetScheduleFromSalesOrders({
        id_sales_orders: selectedSalesOrderIds.value.map((value) => Number(value)),
        id_armada: Number(scheduleForm.id_armada),
        id_driver: Number(scheduleForm.id_driver),
        id_helper: Number(scheduleForm.helperIds[0]),
        helper_ids: scheduleForm.helperIds.map((value) => Number(value)),
        tanggal_pengiriman: scheduleForm.tanggal_pengiriman,
        dock_code: scheduleForm.dock_code,
        cargo_zone: scheduleForm.cargo_zone,
        delivery_notes: scheduleForm.delivery_notes,
        volume_unit: scheduleForm.volume_unit
      });

      const data = unwrapResponse(res) || res;
      message = data?.message || 'Jadwal armada berhasil dibuat';
    } else {
      showScheduleMessage('error', 'Sales order terkait belum ditemukan untuk membuat jadwal baru.');
      return;
    }

    if (hasScheduleRouteContext()) {
      detailOpen.value = false;
      await clearScheduleRouteContext();
    }

    await loadSchedules();
    showScheduleMessage('success', message);
  } catch (error) {
    const msg = normalizeError(error, 'Update jadwal armada gagal.');
    showScheduleMessage('error', msg);
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  if (route.query.id_cabang) {
    filters.branchId = String(route.query.id_cabang);
  }
  try {
    await loadOptions();
    await loadSchedules();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Referensi jadwal belum dapat dimuat. Silakan muat ulang halaman.');
  }
});

onDeactivated(() => {
  createDraftOpen.value = false;
  resetForm();
  checkedDrafts.value = {};
});

onBeforeRouteLeave(() => {
  createDraftOpen.value = false;
  resetForm();
});

watch(
  () => [route.query.schedule_action, route.query.sales_order_id, route.query.id_proses_picking, route.query.id_armada, route.query.id_driver, route.query.helper_ids, route.query.id_helper, route.query.tanggal_pengiriman],
  () => {
    applyRoutePrefill();
  }
);
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Jadwal Pengiriman"
      description="Lihat draf kiriman gabungan nota, cetak satu draf atau beberapa sekaligus, dan kelola jadwal armada."
    >
      <button v-if="canCreateDraft" class="btn-erp-primary" :disabled="loading || printing" @click="openCreateDraft">Buat Draf Kiriman</button>
      <button
        class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        @click="router.push({ name: 'sales-order-list', query: route.query.sales_user_id ? { sales_user_id: route.query.sales_user_id } : {} })"
      >
        Kembali ke Sales Order
      </button>
    </PageHeader>

    <fieldset :disabled="printing" class="min-w-0">
    <AppFilterBar
      :model-value="filters"
      :fields="filterFields"
      @update:model-value="updateFilters"
      @submit="submit"
      @reset="reset"
    />
    </fieldset>

    <div v-if="feedback" role="status" class="rounded-xl bg-emerald-50 p-4 text-sm text-emerald-800">{{ feedback }}</div>
    <div v-if="errorMessage" role="alert" class="rounded-xl bg-rose-50 p-4 text-sm text-rose-800">{{ errorMessage }}</div>
    <section class="panel flex flex-wrap items-center justify-between gap-3 p-4">
      <div><h2 class="font-semibold">{{ filters.view === 'draft' ? 'Draf Kiriman' : 'Semua Jadwal Pengiriman' }}</h2>
        <p class="mt-1 text-sm text-slate-500">{{ selectedDrafts.length }} draf dipilih. Pilih semua mencakup seluruh hasil filter, termasuk halaman lain (maks. {{ MAX_PRINT_DRAFTS }}).</p>
        <p v-if="loadedScope !== scopeKey && !loading" class="mt-1 text-sm text-amber-700">Klik Terapkan untuk memuat perusahaan/cabang yang dipilih.</p>
        <p v-if="printProgress" role="status" class="mt-1 text-sm">{{ printProgress }}</p>
      </div>
      <div class="flex gap-2"><button class="btn-erp-secondary" :disabled="printing || !selectedDrafts.length" @click="checkedDrafts = {}">Kosongkan Pilihan</button>
        <button class="btn-erp-primary" :disabled="!selectionReady || !selectedDrafts.length" @click="printDrafts(selectedDrafts)">{{ printing ? 'Menyiapkan…' : `Cetak Terpilih (${selectedDrafts.length})` }}</button></div>
    </section>

    <section>
      <AppTable
        :rows="tableRows"
        :columns="[
          { key: 'print_select', label: 'Pilih Cetak' },
          { key: 'draft_reference', label: 'Referensi Draf', render: shipmentReference },
          { key: 'print_action', label: 'Cetak' },
          {
            key: 'schedule_type',
            label: 'Jenis Jadwal',
            render: (row) => row.__draft_schedule ? 'Perlu dibuat' : Number(row.sales_order_count || 0) > 1 ? `Gabungan (${row.sales_order_count} SO)` : 'Tunggal'
          },
          { key: 'draft_status', label: 'Status', render: (row) => row.__draft_schedule ? 'Belum dibuat' : shipmentPrintError(row) ? 'Bukan draf aktif' : 'DRF · Draf Kiriman' },
          { key: 'no_order', label: 'Nota / SO' },
          { key: 'nama_customer', label: 'Customer' },
          { key: 'nama_perusahaan', label: 'Perusahaan' },
          { key: 'kode_rute', label: 'Kode Rute' },
          { key: 'nama_rute', label: 'Rute' },
          { key: 'nama_armada', label: 'Armada', render: (row) => row.nama_armada || (row.id_armada ? `Armada #${row.id_armada}` : '-') },
          { key: 'nama_driver', label: 'Driver', render: (row) => row.nama_driver || (row.id_driver ? `Driver #${row.id_driver}` : '-') },
          { key: 'nama_helpers', label: 'Helper', render: (row) => scheduleHelperName(row) },
          { key: 'delivering_date', label: 'Tanggal Kirim', render: (row) => formatPrintDate(row.delivering_date) },
          { key: 'estimasi_kubikasi', label: 'Est. Kubikasi' },
          { key: 'dock_code', label: 'Dock' },
          { key: 'cargo_zone', label: 'Zona' },
          { key: 'utilisasi_persen', label: 'Utilisasi', render: (row) => row.utilisasi_persen == null ? 'Satuan / kapasitas belum diisi' : `${Number(row.utilisasi_persen).toLocaleString('id-ID')}%` }
        ]"
        :loading="loading"
        :clickable-rows="true"
        row-key="id_proses_picking"
        :selected-key="selectedRow?.id_proses_picking || ''"
        :empty-message="filters.view === 'draft' ? 'Belum ada draf kiriman aktif sesuai filter.' : 'Belum ada jadwal armada sesuai filter.'"
        @row-click="openEdit"
      >
        <template #header-print_select><input type="checkbox" aria-label="Pilih semua draf pada hasil filter" :checked="allDraftsChecked" :indeterminate="someDraftsChecked" :disabled="!selectionReady || !draftRows.length" @change="selectAllDrafts" /></template>
        <template #cell-print_select="{ row }"><span @click.stop><input type="checkbox" :aria-label="`Pilih cetak ${shipmentReference(row)}`" :title="shipmentPrintError(row) || 'Pilih draf untuk dicetak'" :checked="!!checkedDrafts[shipmentKey(row)]" :disabled="!selectionReady || !!shipmentPrintError(row)" @change="selectDraft(row, $event)" /></span></template>
        <template #cell-print_action="{ row }"><button class="btn-erp-secondary whitespace-nowrap" :aria-label="`Cetak ${shipmentReference(row)}`" :disabled="!selectionReady || !!shipmentPrintError(row)" :title="shipmentPrintError(row)" @click.stop="printDrafts([row])">Cetak Draf</button></template>
      </AppTable>

      <section v-if="showScheduleHint" class="mt-4 rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-800 dark:border-amber-400/30 dark:bg-amber-500/10 dark:text-amber-100">
        <p class="font-semibold text-amber-950 dark:text-amber-100">Belum ada draf / jadwal sesuai filter.</p>
        <p class="mt-2 leading-6">
          Gunakan Buat Draf Kiriman untuk memilih nota yang sudah dikonfirmasi langsung dari halaman ini, atau melalui Sales Order. Draf yang sudah diproses dapat dilihat pada pilihan Semua Jadwal.
        </p>
        <p class="mt-2 leading-6">
          Periksa perusahaan, cabang, dan pencarian; lalu klik Terapkan untuk memuat ulang.
        </p>
      </section>
    </section>

    <ScheduleDraftCreateModal v-if="createDraftOpen" :company-id="filters.companyId" :branch-id="activeBranchId" :company-name="activeCompanyName" :branch-name="activeBranchName" @close="createDraftOpen = false" @created="draftCreated" />

    <AppModal
      :open="detailOpen"
      title="Edit Jadwal Pengiriman"
      :description="selectedRow ? 'Isi armada, driver, satu atau lebih helper, dan tanggal pengiriman untuk jadwal terpilih.' : 'Pilih jadwal dari tabel untuk membuka detail.'"
      size="4xl"
      @close="closeScheduleModal"
    >
      <div v-if="selectedRow" class="space-y-5">
        <section class="grid gap-4 md:grid-cols-2">
          <AppFormField v-model="scheduleForm.id_proses_picking" label="ID Proses Picking" />
          <AppSearchSelect v-model="scheduleForm.id_armada" label="Armada" placeholder="Pilih armada" :options="fleetOptions" empty-text="Armada belum tersedia." />
          <AppSearchSelect v-model="scheduleForm.id_driver" label="Driver" placeholder="Pilih driver" :options="driverOptions" empty-text="Driver belum tersedia." />
          <AppSearchSelect v-model="scheduleForm.helperIds" multiple label="Helper / Kernet" placeholder="Pilih satu atau lebih helper" :options="helperOptions" empty-text="Helper atau kernet belum tersedia." />
          <AppFormField v-model="scheduleForm.tanggal_pengiriman" label="Tanggal Pengiriman" type="date" />
          <AppFormField v-model="scheduleForm.dock_code" label="Loading Dock" placeholder="Contoh: DOCK-A" maxlength="60" />
          <label class="block text-sm">Zona muatan
            <select v-model="scheduleForm.cargo_zone" class="field mt-1">
              <option value="">Pilih zona</option><option value="FOOD">FOOD</option><option value="NON_FOOD">NON-FOOD</option>
            </select>
          </label>
          <AppFormField v-model="scheduleForm.delivery_notes" label="Catatan Pengiriman" maxlength="2000" />
          <label class="block text-sm">Satuan estimasi volume
            <select v-model="scheduleForm.volume_unit" class="field mt-1"><option value="">Pilih satuan sumber data produk</option><option value="CM3">cm³</option><option value="M3">m³</option></select>
            <span class="text-xs text-slate-500">Kapasitas armada memakai m³. Jangan campurkan satuan produk dalam satu jadwal.</span>
          </label>
        </section>

        <section class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-300">
          <div
            v-if="isMergedSchedule"
            class="mb-3 rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-400/30 dark:bg-amber-500/10 dark:text-amber-100"
          >
            Jadwal gabungan: row ini memuat {{ selectedRow?.sales_order_count }} sales order. Pastikan perubahan armada, driver, helper, dan tanggal kirim memang berlaku untuk seluruh order di jadwal ini.
          </div>
          <div
            v-else-if="selectedRow?.__draft_schedule"
            class="mb-3 rounded-2xl border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-800 dark:border-sky-400/30 dark:bg-sky-500/10 dark:text-sky-100"
          >
            Jadwal belum terbentuk di backend. Anda bisa pilih armada, driver, helper, dan tanggal kirim lalu simpan untuk membuat jadwal baru dari sales order ini.
          </div>
          <div class="grid gap-3 md:grid-cols-2">
            <p>Rute aktif: <span class="font-semibold text-slate-900 dark:text-white">{{ selectedRow?.nama_rute || '-' }}</span></p>
            <p>No order: <span class="font-semibold text-slate-900 dark:text-white">{{ selectedRow?.no_order || routeContextInfo.noOrder || '-' }}</span></p>
            <p>Customer: <span class="font-semibold text-slate-900 dark:text-white">{{ selectedRow?.nama_customer || routeContextInfo.customerName || '-' }}</span></p>
            <p>Helper aktif: <span class="font-semibold text-slate-900 dark:text-white">{{ scheduleHelperName(selectedRow) }}</span></p>
            <p>Faktur terkait: <span class="font-semibold text-slate-900 dark:text-white">{{ selectedRow?.id_faktur || '-' }}</span></p>
            <p>Sales order terkait: <span class="font-semibold text-slate-900 dark:text-white">{{ selectedRow?.id_sales_order || '-' }}</span></p>
            <p>Primary sales order: <span class="font-semibold text-slate-900 dark:text-white">{{ selectedRow?.primary_sales_order_id || '-' }}</span></p>
            <p>Jumlah sales order tergabung: <span class="font-semibold text-slate-900 dark:text-white">{{ selectedRow?.sales_order_count || 0 }}</span></p>
          </div>
        </section>

        <div v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-400/30 dark:bg-emerald-500/10 dark:text-emerald-100">
          {{ feedback }}
        </div>
        <div v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-400/30 dark:bg-rose-500/10 dark:text-rose-100">
          {{ errorMessage }}
        </div>

        <section class="flex flex-wrap justify-end gap-2">
          <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800" :disabled="saving" @click="closeScheduleModal">
            Tutup
          </button>
          <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800" :disabled="saving" @click="resetForm">
            Reset Form
          </button>
          <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60" :disabled="saving" @click="saveSchedule">
            {{ saving ? 'Menyimpan...' : 'Simpan Perubahan' }}
          </button>
        </section>
      </div>
    </AppModal>
  </div>
</template>
