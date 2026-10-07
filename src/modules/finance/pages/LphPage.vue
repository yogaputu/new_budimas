<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies, getSales } from '@/api/master';
import { createLph, deleteLph, getLphCreateCandidates, getLphDetail, getLphList, reprintLph, updateLph } from '@/api/finance';
import { workflowGet } from '@/api/paymentWorkflow';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getLoginCompanyId, getLoginSalesId, getRowCompanyId, hasMultiBusinessScope, hasSupervisorSalesScope, isSuperUser, scopeSalesRowsByLogin, shouldLockToLoginSales } from '@/utils/accessScope';
import { getBranchOptionsForCompany, getCompanyOptionsForScope, resetBranchWhenCompanyChanges } from '@/utils/filterScope';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const auth = useAuthStore();
const numberFormatter = new Intl.NumberFormat('id-ID');

function localDateString(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

const today = localDateString();
const LPH_STATE_STORAGE_KEY = 'budimas.finance.lph.state.v1';
const filters = reactive({
  id_cabang: '',
  id_perusahaan: '',
  tanggal_awal: '',
  tanggal_akhir: '',
  search: '',
  page: 1,
  limit: 50
});

const companyRows = ref([]);
const workflowOptions = ref([]);
const workflowOptionsError = ref('');
const preferredWorkflow = company => auth.hasPermission('finance.receipts.create') && workflowOptions.value.some(o=>o.enabled && String(o.id_perusahaan)===String(company)) ? '2' : '1';
const branchRows = ref([]);
const salesRows = ref([]);
const rows = ref([]);
const totalRows = ref(0);
const totalPages = computed(() => Math.max(1, Math.ceil(totalRows.value / Number(filters.limit || 50))));
const detailRows = ref([]);
const selectedRow = ref(null);
const restoringState = ref(false);
const loading = reactive({ list: false, detail: false, print: false, options: false, candidates: false, save: false, delete: false });
const errorMessage = ref('');
const feedback = ref('');
const createModalOpen = ref(false);
const editModalOpen = ref(false);
const candidateRows = ref([]);
const selectedCandidateIds = ref([]);
let candidateRequestController = null;
const createForm = reactive({
  payment_workflow_version: '1',
  id_cabang: '',
  id_perusahaan: '',
  id_sales: '',
  tanggal_lph: today,
  // Hanya batas opsional saat memuat kandidat; tidak mengubah tanggal
  // dokumen LPH yang akan dibuat.
  tanggal_jatuh_tempo_sampai: '',
  // 2 = gabungan: satu LPH dapat memuat kandidat Call Plan, Non Call Plan,
  // maupun faktur yang detail ordernya sendiri campuran keduanya.
  is_cp: '2',
  include_other_sales: false
});
const editForm = reactive({
  id_lph: '',
  id_sales: '',
  tanggal_lph: today,
  is_cp: '1',
  jumlah_ditagih: 0,
  total_retur: 0
});
const editDetails = ref([]);

const fallbackBranchId = computed(() => getLoginBranchId(auth.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(auth.user));
const fallbackSalesId = computed(() => getLoginSalesId(auth.user));
const canAccessAllBranches = computed(() => isSuperUser(auth));
const shouldLockBusinessScope = computed(() => !canAccessAllBranches.value && !hasSupervisorSalesScope(auth.user) && !hasMultiBusinessScope(auth.user));
const canUseLoginScope = computed(() => shouldLockToLoginSales(auth));

const branchOptions = computed(() =>
  getBranchOptionsForCompany(branchRows.value, auth, filters.id_perusahaan, false, companyRows.value)
);

const companyOptions = computed(() =>
  getCompanyOptionsForScope(companyRows.value, auth)
);

const createBranchOptions = computed(() =>
  getBranchOptionsForCompany(branchRows.value, auth, createForm.id_perusahaan, false, companyRows.value)
);

const createCompanyOptions = computed(() =>
  getCompanyOptionsForScope(companyRows.value, auth)
);

const selectedCreateCompany = computed(() =>
  companyRows.value.find((item) => String(item.id) === String(createForm.id_perusahaan || filters.id_perusahaan || ''))
);

function salesMatchesCompany(row, companyId) {
  if (!companyId) return true;
  const directCompanyId = getRowCompanyId(row);
  if (directCompanyId) return String(directCompanyId) === String(companyId);
  return true;
}

const salesOptions = computed(() =>
  scopeSalesRowsByLogin(salesRows.value, auth)
    .filter((item) => !createForm.id_cabang || String(item.id_cabang || '') === String(createForm.id_cabang))
    .filter((item) => !createForm.id_perusahaan || salesMatchesCompany(item, createForm.id_perusahaan))
    .map((item) => ({
      value: String(item.id_sales || item.sales_id || item.id),
      label: `${item.kode_sales || '-'} - ${item.nama || 'Sales'}${item.nama_cabang ? ` | ${item.nama_cabang}` : ''}`
    }))
);

const selectedCandidateRows = computed(() => {
  const selected = new Set(selectedCandidateIds.value.map((id) => String(id)));
  return candidateRows.value.filter((item) => selected.has(String(item.id_faktur)));
});

const selectedCandidateTotal = computed(() =>
  selectedCandidateRows.value.reduce((sum, item) => sum + Number(item.sisa_pembayaran || 0), 0)
);

const selectedCandidateRetur = computed(() =>
  selectedCandidateRows.value.reduce((sum, item) => sum + Number(item.nominal_retur || 0), 0)
);

const tableRows = computed(() =>
  rows.value.map((item) => ({
    ...item,
    row_key: String(item.id),
    tanggal_label: formatDate(item.tanggal_lph),
    sales_label: item.nama_sales || '-',
    pencetak_label: item.nama_pencetak || '-',
    status_label: item.status_label || resolveLphDocumentStatus(item.status_dokumen),
    tanggal_diterima_label: formatDate(item.tanggal_diterima),
    tanggal_dikembalikan_label: formatDate(item.tanggal_dikembalikan)
  }))
);

const detailTotal = computed(() =>
  detailRows.value.reduce((acc, item) => acc + Number(item.sisa_pembayaran || item.jumlah_tagihan || 0), 0)
);

const detailReturTotal = computed(() =>
  detailRows.value.reduce((acc, item) => acc + Number(item.nominal_retur || 0), 0)
);

const selectedHeader = computed(() => detailRows.value[0] || selectedRow.value || {});

const selectedDocumentStatus = computed(() =>
  String(selectedHeader.value.status_dokumen || selectedRow.value?.status_dokumen || 'AKTIF').trim().toUpperCase()
);

const canModifySelectedLph = computed(() =>
  Boolean(selectedRow.value?.id) && !['AKTIF', 'DIKEMBALIKAN'].includes(selectedDocumentStatus.value)
);

function formatCurrency(value) {
  return `Rp ${numberFormatter.format(Number(value || 0))}`;
}

function formatDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10);
  return date.toLocaleDateString('id-ID', { day: '2-digit', month: 'long', year: 'numeric' });
}

function formatShortDate(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10);
  return date.toLocaleDateString('id-ID', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

function formatWeekday(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleDateString('id-ID', { weekday: 'long' });
}

function formatPlainNumber(value) {
  return numberFormatter.format(Number(value || 0));
}

function formatCandidateSource(item = {}) {
  const source = String(item.lph_source || item.sumber_lph || item.tipe_lph || '').trim().toUpperCase();
  if (source === 'CALL_PLAN' || source === 'CP') return 'Call Plan';
  if (source === 'NON_CALL_PLAN' || source === 'NON_CP' || source === 'NONCALLPLAN') return 'Non Call Plan';
  if (source === 'GABUNGAN' || source === 'MIXED') return 'Gabungan (campuran)';
  return '-';
}

function resolveLphDocumentStatus(value) {
  const status = String(value || '').trim().toUpperCase();
  if (status === 'MENUNGGU_PENERIMAAN') return 'Menunggu penerimaan sales';
  if (status === 'AKTIF') return 'Aktif di sales';
  if (status === 'DIKEMBALIKAN') return 'Dikembalikan';
  return status || '-';
}

function assertSelectedLphCanBeModified() {
  if (canModifySelectedLph.value) return true;
  errorMessage.value = 'LPH yang sudah diterima sales atau sudah dikembalikan tidak dapat diubah maupun dihapus. Status dokumen diaudit dari aplikasi Mobile Sales.';
  return false;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function normalizePayloadList(payload) {
  if (Array.isArray(payload?.data)) return payload.data;
  if (Array.isArray(payload?.rows)) return payload.rows;
  if (Array.isArray(payload?.items)) return payload.items;
  return normalizeList(payload);
}

function parseReturOptions(value) {
  if (Array.isArray(value)) return value;
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    return [];
  }
}

function normalizeReturOption(option = {}) {
  const sourceType = option.source_type || option.type || 'retur';
  const sourceId = option.source_id || option.id || option.id_cn || option.id_request || option.kode || '';
  const nominal = Number(option.nominal ?? option.total_cn ?? option.total_retur ?? 0);
  const kode = option.kode || option.kode_cn || option.no_cn || option.kode_kpr || option.kode_request || '';
  return {
    ...option,
    source_type: sourceType,
    source_id: sourceId,
    kode,
    nominal,
    option_key: `${sourceType}:${sourceId}:${kode}:${nominal}`
  };
}

function normalizeSelectedReturOptions(row, options, existingNominal, existingKode) {
  const rawSelected = row.selected_retur_options || row.selected_retur_option || row.retur_selected_options;
  const selectedKeys = parseReturOptions(rawSelected)
    .map((item) => (typeof item === 'object' ? normalizeReturOption(item).option_key : String(item)))
    .filter(Boolean);

  if (selectedKeys.length) return selectedKeys;

  if (existingNominal > 0 || existingKode) {
    const matched = options.filter((item) => String(item.kode) === String(existingKode) || Number(item.nominal || 0) === existingNominal);
    return matched.length ? matched.map((item) => item.option_key) : ['manual'];
  }

  return [];
}

function normalizeCandidateRow(row = {}) {
  const options = parseReturOptions(row.retur_options).map(normalizeReturOption).filter((item) => item.nominal > 0 || item.kode);
  const existingNominal = Number(row.nominal_retur || 0);
  const existingKode = row.kode_cn || '';
  const selectedOptions = normalizeSelectedReturOptions(row, options, existingNominal, existingKode);

  const normalized = {
    ...row,
    retur_options: options,
    selected_retur_options: selectedOptions,
    nominal_retur: existingNominal,
    kode_cn: existingKode
  };

  if (selectedOptions.length && !selectedOptions.includes('manual')) {
    applyCandidateReturOptions(normalized);
  }

  return normalized;
}

function applyCandidateReturOptions(row) {
  const selectedKeys = new Set((row.selected_retur_options || []).map(String));
  if (!selectedKeys.size || selectedKeys.has('manual')) {
    if (!selectedKeys.has('manual')) {
      row.nominal_retur = 0;
      row.kode_cn = '';
      row.selected_retur_payload = [];
    }
    return;
  }

  const selected = (row.retur_options || []).filter((item) => selectedKeys.has(String(item.option_key)));
  if (!selected.length) {
    row.nominal_retur = 0;
    row.kode_cn = '';
    row.selected_retur_payload = [];
    return;
  }

  row.nominal_retur = selected.reduce((sum, item) => sum + Number(item.nominal || 0), 0);
  row.kode_cn = selected.map((item) => item.kode || item.source_id || item.source_type).filter(Boolean).join(', ');
  row.selected_retur_payload = selected.map((item) => ({
    source_type: item.source_type,
    source_id: item.source_id,
    kode: item.kode,
    nominal: Number(item.nominal || 0)
  }));
}

function toggleCandidateReturOption(row, optionKey) {
  const current = new Set((row.selected_retur_options || []).map(String).filter((item) => item !== 'manual'));
  if (current.has(String(optionKey))) {
    current.delete(String(optionKey));
  } else {
    current.add(String(optionKey));
  }
  row.selected_retur_options = Array.from(current);
  applyCandidateReturOptions(row);
}

function getStateStorageKey() {
  const userId = auth.user?.id || auth.user?.id_user || auth.user?.user_id || 'anonymous';
  return `${LPH_STATE_STORAGE_KEY}:${userId}`;
}

function saveLphState() {
  try {
    window.sessionStorage.setItem(
      getStateStorageKey(),
      JSON.stringify({
        filters: { ...filters },
        rows: rows.value,
        detailRows: detailRows.value,
        selectedRow: selectedRow.value,
        savedAt: Date.now()
      })
    );
  } catch (error) {
    // Cache halaman bersifat opsional; kegagalan storage tidak boleh mengganggu transaksi.
  }
}

function restoreLphState() {
  try {
    const raw = window.sessionStorage.getItem(getStateStorageKey());
    if (!raw) return false;

    const payload = JSON.parse(raw);
    if (!payload || typeof payload !== 'object') return false;

    restoringState.value = true;
    Object.assign(filters, {
      id_cabang: payload.filters?.id_cabang || '',
      id_perusahaan: payload.filters?.id_perusahaan || '',
      tanggal_awal: payload.filters?.tanggal_awal || '',
      tanggal_akhir: payload.filters?.tanggal_akhir || '',
      search: payload.filters?.search || '',
      page: payload.filters?.page || 1,
      limit: payload.filters?.limit || 50
    });
    rows.value = Array.isArray(payload.rows) ? payload.rows : [];
    detailRows.value = Array.isArray(payload.detailRows) ? payload.detailRows : [];
    selectedRow.value =
      payload.selectedRow ||
      rows.value.find((item) => String(item.id) === String(payload.selectedRow?.id || '')) ||
      rows.value[0] ||
      null;

    window.setTimeout(() => {
      restoringState.value = false;
    }, 0);
    return true;
  } catch (error) {
    restoringState.value = false;
    return false;
  }
}

async function loadOptions() {
  loading.options = true;
  try {
    const [companyResponse, branchResponse, salesResponse] = await Promise.all([getCompanies(), getBranches(), getSales()]);
    companyRows.value = normalizeList(unwrapResponse(companyResponse));
    branchRows.value = normalizeList(unwrapResponse(branchResponse));
    salesRows.value = normalizeList(unwrapResponse(salesResponse));
    try { workflowOptions.value=normalizeList(unwrapResponse(await workflowGet('options')));workflowOptionsError.value=''; }
    catch { workflowOptions.value=[];workflowOptionsError.value='Pengaturan alur Kuitansi belum dapat dimuat. Muat ulang sebelum memilih alur baru.'; }
    if (shouldLockBusinessScope.value && fallbackBranchId.value) {
      filters.id_cabang = String(fallbackBranchId.value);
    }
    if (shouldLockBusinessScope.value && fallbackCompanyId.value) filters.id_perusahaan = String(fallbackCompanyId.value);
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Referensi cabang belum bisa dimuat.');
  } finally {
    loading.options = false;
  }
}

function openCreateModal() {
  abortCandidateRequest();
  errorMessage.value = '';
  feedback.value = '';
  candidateRows.value = [];
  selectedCandidateIds.value = [];
  Object.assign(createForm, {
    id_perusahaan: filters.id_perusahaan || (shouldLockBusinessScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : ''),
    id_cabang: filters.id_cabang || (shouldLockBusinessScope.value && fallbackBranchId.value ? String(fallbackBranchId.value) : ''),
    id_sales: canUseLoginScope.value && fallbackSalesId.value ? String(fallbackSalesId.value) : '',
    tanggal_lph: today,
    tanggal_jatuh_tempo_sampai: '',
    is_cp: '2',
    payment_workflow_version: preferredWorkflow(filters.id_perusahaan || fallbackCompanyId.value),
    include_other_sales: false
  });
  createModalOpen.value = true;
}

function abortCandidateRequest() {
  if (!candidateRequestController) return;
  candidateRequestController.abort();
  candidateRequestController = null;
  loading.candidates = false;
}

function clearCandidateScope() {
  // A candidate response belongs to one exact combination of company, branch,
  // sales, LPH type, and "sales lain" setting.  Cancel it before clearing the
  // table so a slow response cannot repopulate the modal with the old scope.
  abortCandidateRequest();
  candidateRows.value = [];
  selectedCandidateIds.value = [];
}

function closeCreateModal() {
  abortCandidateRequest();
  createModalOpen.value = false;
}

async function loadCandidates() {
  if (!createForm.id_cabang || !createForm.id_sales || !createForm.tanggal_lph) {
    errorMessage.value = 'Pilih cabang, sales, dan tanggal LPH terlebih dahulu.';
    return;
  }

  // A user may change the scope or click reload after a slow request.  Only
  // the latest response is allowed to update the modal, otherwise an older
  // scope could replace a newer result after it eventually completes.
  abortCandidateRequest();
  const requestController = new AbortController();
  candidateRequestController = requestController;
  loading.candidates = true;
  errorMessage.value = '';
  candidateRows.value = [];
  selectedCandidateIds.value = [];

  try {
    const response = await getLphCreateCandidates({
      id_cabang: createForm.id_cabang,
      id_perusahaan: createForm.id_perusahaan || undefined,
      id_sales: createForm.id_sales,
      tanggal_lph: createForm.tanggal_lph,
      tanggal_jatuh_tempo_sampai: createForm.tanggal_jatuh_tempo_sampai || undefined,
      is_cp: createForm.is_cp,
      // The header sales remains the LPH owner.  When explicitly enabled,
      // candidates may also come from another sales in the same company and
      // branch for any LPH type.
      include_other_sales: createForm.include_other_sales ? 1 : 0
    }, { signal: requestController.signal });
    if (requestController.signal.aborted || candidateRequestController !== requestController) return;
    candidateRows.value = normalizePayloadList(unwrapResponse(response)).map(normalizeCandidateRow);
    // Mode Call Plan murni tetap boleh langsung dipilih seperti alur lama,
    // but never auto-selects candidates from other sales.  Those must be
    // selected explicitly by Finance before the LPH can be saved.
    // Mode gabungan memuat kandidat dari seluruh sumber (CP, Non CP, maupun
    // campuran), lalu tetap dipilih admin secara eksplisit.
    selectedCandidateIds.value = createForm.is_cp === '1' && !createForm.include_other_sales
      ? candidateRows.value.map((item) => String(item.id_faktur))
      : [];
  } catch (error) {
    if (requestController.signal.aborted || candidateRequestController !== requestController) return;
    errorMessage.value = error?.code === 'ECONNABORTED'
      ? 'Pemuatan kandidat LPH melebihi waktu tunggu. Silakan coba lagi; query kandidat sedang dioptimalkan di server.'
      : normalizeError(error, 'Kandidat tagihan LPH belum bisa dimuat.');
  } finally {
    if (candidateRequestController === requestController) {
      candidateRequestController = null;
      loading.candidates = false;
    }
  }
}

function toggleCandidate(id) {
  const key = String(id);
  if (selectedCandidateIds.value.includes(key)) {
    selectedCandidateIds.value = selectedCandidateIds.value.filter((item) => item !== key);
    return;
  }
  selectedCandidateIds.value = [...selectedCandidateIds.value, key];
}

async function saveCreateLph() {
  if (!selectedCandidateRows.value.length) {
    errorMessage.value = 'Pilih minimal satu tagihan untuk membuat LPH.';
    return;
  }

  loading.save = true;
  errorMessage.value = '';
  feedback.value = '';

  try {
    await createLph({
      id_cabang: createForm.id_cabang,
      id_perusahaan: createForm.id_perusahaan || undefined,
      id_sales: createForm.id_sales,
      tanggal_lph: createForm.tanggal_lph,
      is_cp: Number(createForm.is_cp || 2),
      payment_workflow_version: Number(createForm.payment_workflow_version || 1),
      include_other_sales: createForm.include_other_sales ? 1 : 0,
      id_user: auth.user?.id || auth.user?.id_user || auth.user?.user_id,
      kode_perusahaan: selectedCandidateRows.value[0]?.kode_perusahaan || selectedCreateCompany.value?.kode || '',
      jumlah_ditagih: selectedCandidateTotal.value,
      total_retur: selectedCandidateRetur.value,
      data_tagihan: selectedCandidateRows.value.map((item) => ({
        ...item,
        selected_retur_options: item.selected_retur_payload || []
      }))
    });
    feedback.value = 'LPH berhasil dibuat.';
    createModalOpen.value = false;
    await loadRows();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'LPH belum berhasil dibuat.');
  } finally {
    loading.save = false;
  }
}

function openEditModal() {
  if (!selectedRow.value) {
    errorMessage.value = 'Pilih LPH terlebih dahulu.';
    return;
  }
  if (!assertSelectedLphCanBeModified()) return;

  Object.assign(editForm, {
    id_lph: selectedRow.value.id,
    id_sales: selectedRow.value.id_sales ? String(selectedRow.value.id_sales) : '',
    tanggal_lph: String(selectedRow.value.tanggal_lph || today).slice(0, 10),
    is_cp: String(selectedHeader.value.is_cp ?? selectedRow.value.is_cp ?? '1'),
    jumlah_ditagih: detailTotal.value,
    total_retur: detailReturTotal.value
  });
  editDetails.value = detailRows.value.map((item) => ({
    ...item,
    jumlah_tagihan: Number(item.sisa_pembayaran || item.jumlah_tagihan || 0),
    nominal_retur: Number(item.nominal_retur || 0),
    kode_cn: item.kode_cn || ''
  }));
  editModalOpen.value = true;
}

async function saveEditLph() {
  if (!editForm.id_lph) return;

  loading.save = true;
  errorMessage.value = '';
  feedback.value = '';

  try {
    await updateLph({
      ...editForm,
      jumlah_ditagih: editDetails.value.reduce((sum, item) => sum + Number(item.jumlah_tagihan || 0), 0),
      total_retur: editDetails.value.reduce((sum, item) => sum + Number(item.nominal_retur || 0), 0),
      data_tagihan: editDetails.value
    });
    feedback.value = 'LPH berhasil diperbarui.';
    editModalOpen.value = false;
    await loadRows();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'LPH belum berhasil diperbarui.');
  } finally {
    loading.save = false;
  }
}

async function handleDeleteLph() {
  if (!selectedRow.value?.id) {
    errorMessage.value = 'Pilih LPH terlebih dahulu.';
    return;
  }
  if (!assertSelectedLphCanBeModified()) return;

  const confirmed = window.confirm(`Hapus LPH ${selectedRow.value.kode_lph || ''}? Detail LPH ikut terhapus.`);
  if (!confirmed) return;

  loading.delete = true;
  errorMessage.value = '';
  feedback.value = '';

  try {
    await deleteLph({ id_lph: selectedRow.value.id });
    feedback.value = 'LPH berhasil dihapus.';
    selectedRow.value = null;
    detailRows.value = [];
    await loadRows();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'LPH belum berhasil dihapus.');
  } finally {
    loading.delete = false;
  }
}

async function loadRows(requestedPage = 1) {
  if (!filters.id_cabang) {
    errorMessage.value = 'Pilih cabang terlebih dahulu untuk memuat LPH.';
    return;
  }

  loading.list = true;
  errorMessage.value = '';
  feedback.value = '';
  const page = Number.isInteger(requestedPage) ? Math.max(1, requestedPage) : 1;
  filters.limit = Math.min(200, Math.max(1, Math.trunc(Number(filters.limit) || 50)));

  try {
    const response = await getLphList({
      id_cabang: filters.id_cabang,
      id_perusahaan: filters.id_perusahaan || undefined,
      tanggal_awal: filters.tanggal_awal || undefined,
      tanggal_akhir: filters.tanggal_akhir || undefined,
      filters: filters.search || undefined,
      page: page - 1,
      limit: filters.limit
    });
    const payload = unwrapResponse(response) || {};
    rows.value = normalizePayloadList(payload);
    totalRows.value = Number(payload.total_data || 0);
    filters.page = Number.isInteger(payload.page) ? payload.page + 1 : page;
    selectedRow.value = rows.value[0] || null;
    detailRows.value = [];
    if (selectedRow.value?.id) {
      await loadDetail(selectedRow.value);
    } else {
      saveLphState();
    }
  } catch (error) {
    rows.value = [];
    totalRows.value = 0;
    detailRows.value = [];
    selectedRow.value = null;
    errorMessage.value = normalizeError(error, 'Daftar LPH belum bisa dimuat.');
  } finally {
    loading.list = false;
  }
}

async function loadDetail(row) {
  if (!row?.id) return;
  selectedRow.value = row;
  loading.detail = true;
  errorMessage.value = '';

  try {
    const response = await getLphDetail({ id_lph: row.id });
    detailRows.value = normalizeList(unwrapResponse(response));
    saveLphState();
  } catch (error) {
    detailRows.value = [];
    errorMessage.value = normalizeError(error, 'Detail LPH belum bisa dimuat.');
  } finally {
    loading.detail = false;
  }
}

async function handleReprint() {
  if (!selectedRow.value?.id) return;
  loading.print = true;
  feedback.value = '';
  errorMessage.value = '';

  try {
    const batch = Number(selectedHeader.value.batch_cetak || selectedRow.value.batch_cetak || 0) + 1;
    await reprintLph({ id_lph: selectedRow.value.id, batch_cetak: batch });
    feedback.value = 'Batch cetak LPH berhasil diperbarui.';
    await loadDetail(selectedRow.value);
    printLph();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Cetak ulang LPH belum berhasil diproses.');
  } finally {
    loading.print = false;
  }
}

function printLph() {
  if (!selectedRow.value || !detailRows.value.length) {
    errorMessage.value = 'Pilih LPH dan pastikan detail tagihan sudah tampil sebelum cetak.';
    return;
  }

  const header = selectedHeader.value;
  const lphDate = header.tanggal_lph || selectedRow.value.tanggal_lph || today;
  const printedAt = new Date();
  const totalTagihan = detailTotal.value;
  const totalRetur = detailReturTotal.value;
  const rowsHtml = detailRows.value.map((item, index) => `
    <tr>
      <td class="center">${index + 1}.</td>
      <td class="outlet">${escapeHtml(item.nama_customer || '-')}</td>
      <td class="center">${escapeHtml(formatShortDate(item.tanggal_faktur))}</td>
      <td class="center">${escapeHtml(item.no_faktur || '-')}</td>
      <td class="right">${formatPlainNumber(item.sisa_pembayaran || item.jumlah_tagihan)}</td>
      <td class="center">${escapeHtml(formatShortDate(item.tanggal_jatuh_tempo))}</td>
      <td class="center">${escapeHtml(item.kode_cn || '')}</td>
      <td class="right">${Number(item.nominal_retur || 0) ? formatPlainNumber(item.nominal_retur) : ''}</td>
      <td class="right"></td>
      <td class="center"></td>
      <td class="center"></td>
      <td class="center"></td>
      <td class="right"></td>
    </tr>
  `).join('');

  const win = window.open('', '_blank', 'width=1120,height=820');
  if (!win) return;

  win.document.write(`
    <html>
      <head>
        <title>LPH ${escapeHtml(header.kode_lph || selectedRow.value.kode_lph || '')}</title>
        <style>
          * { box-sizing: border-box; }
          body { margin: 0; background: #9ca3af; color: #111827; font-family: "Times New Roman", Times, serif; }
          .sheet {
            width: 287mm;
            min-height: 190mm;
            margin: 8mm auto;
            background: #fff;
            padding: 11mm 13mm 8mm;
            box-shadow: 4px 4px 0 #111;
          }
          .header-grid { display: grid; grid-template-columns: 1fr 180px 1fr; align-items: start; gap: 16px; font-size: 12px; }
          .company { font-size: 15px; font-weight: 700; letter-spacing: .02em; text-transform: uppercase; }
          .meta-line { margin-top: 4px; }
          .label { display: inline-block; min-width: 60px; }
          .document-no { font-size: 12px; line-height: 1.55; }
          .top-rule { border-top: 1.5px solid #111; margin-top: 10px; }
          table { width: 100%; border-collapse: collapse; margin-top: 6px; font-size: 11px; line-height: 1.2; }
          th, td { border-bottom: 1px solid #111; padding: 4px 5px; vertical-align: middle; }
          th { font-weight: 700; text-align: center; }
          .subhead th { border-bottom: 1px solid #111; font-weight: 400; padding-top: 1px; padding-bottom: 2px; }
          .center { text-align: center; }
          .right { text-align: right; }
          .outlet { font-weight: 700; text-transform: uppercase; }
          .total-row td { border-bottom: 0; font-weight: 700; }
          .summary-signature { display: grid; grid-template-columns: 220px 1fr; gap: 24px; margin-top: 10px; font-size: 11px; }
          .summary-line { margin-top: 4px; }
          .signature { display: grid; grid-template-columns: repeat(3, 180px); justify-content: center; gap: 32px; text-align: center; font-size: 11px; }
          .signature-title { font-weight: 700; letter-spacing: .04em; text-transform: uppercase; }
          .signature-name { margin-top: 42px; }
          .footer { margin-top: 14px; display: flex; gap: 22px; align-items: center; font-size: 11px; }
          .page { font-weight: 700; text-decoration: underline; }
          @page { size: A4 landscape; margin: 8mm; }
          @media print {
            body { background: #fff; }
            .sheet { width: auto; min-height: auto; margin: 0; padding: 0; box-shadow: none; }
          }
        </style>
      </head>
      <body>
        <main class="sheet">
          <section class="header-grid">
            <div>
              <div class="company">${escapeHtml(header.nama_perusahaan || selectedRow.value.nama_perusahaan || 'PT. BUDIMAS SOLO')}</div>
              <div class="meta-line"><span class="label">Penagih :</span>${escapeHtml(header.nama_sales || selectedRow.value.nama_sales || '-')}</div>
              <div class="meta-line"><span class="label">Hari :</span>${escapeHtml(formatWeekday(lphDate))}</div>
            </div>
            <div></div>
            <div class="document-no">
              <div><span class="label">No :</span>${escapeHtml(header.kode_lph || selectedRow.value.kode_lph || '-')}</div>
              <div><span class="label">Tanggal :</span>${escapeHtml(formatShortDate(lphDate))}</div>
            </div>
          </section>

          <div class="top-rule"></div>

          <table>
            <thead>
              <tr>
                <th rowspan="2" style="width: 34px;">No.</th>
                <th rowspan="2" style="width: 210px; text-align: left;">Nama Outlet</th>
                <th colspan="3">Faktur</th>
                <th rowspan="2" style="width: 72px;">Tanggal<br>JT</th>
                <th rowspan="2" style="width: 72px;">Nota<br>Retur</th>
                <th rowspan="2" style="width: 84px;">Nilai Retur</th>
                <th rowspan="2" style="width: 76px;">Tunai</th>
                <th rowspan="2" style="width: 86px;">Nota<br>Kembali</th>
                <th>Titipan</th>
                <th colspan="2">BG</th>
              </tr>
              <tr class="subhead">
                <th style="width: 72px;">Tgl</th>
                <th style="width: 112px;">Nomor</th>
                <th style="width: 84px;">Rp</th>
                <th style="width: 72px;">Tgl</th>
                <th style="width: 110px;">No Bank</th>
                <th style="width: 110px;">Nominal</th>
              </tr>
            </thead>
            <tbody>
              ${rowsHtml}
              <tr class="total-row">
                <td></td>
                <td></td>
                <td></td>
                <td class="center">TOTAL</td>
                <td class="right">${formatPlainNumber(totalTagihan)}</td>
                <td colspan="9"></td>
              </tr>
            </tbody>
          </table>

          <section class="summary-signature">
            <div>
              <div class="summary-line">Jumlah Faktur Terbawa : <strong>${detailRows.value.length}</strong></div>
              <div class="summary-line">Jumlah Faktur Kembali : <strong></strong></div>
              <div class="summary-line">Total Retur : <strong>${totalRetur ? formatPlainNumber(totalRetur) : ''}</strong></div>
            </div>
            <div class="signature">
              <div>
                <div class="signature-title">Salesman</div>
                <div class="signature-name">(............................)</div>
              </div>
              <div>
                <div class="signature-title">Supervisor</div>
                <div class="signature-name">(............................)</div>
              </div>
              <div>
                <div class="signature-title">Admin</div>
                <div class="signature-name">(............................)</div>
              </div>
            </div>
          </section>

          <footer class="footer">
            <span class="page">Page 1 of 1</span>
            <span>${escapeHtml(formatShortDate(printedAt))}</span>
            <span>${escapeHtml(printedAt.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit' }))}</span>
            <span>${escapeHtml((auth.user?.nama || auth.user?.username || '').toString().toUpperCase())}</span>
          </footer>
        </main>
      </body>
    </html>
  `);
  win.document.close();
  win.focus();
  win.print();
}

onMounted(async () => {
  await loadOptions();
  restoreLphState();
  await loadRows(Number(filters.page) || 1);
});
watch(()=>createForm.id_perusahaan,company=>{createForm.payment_workflow_version=preferredWorkflow(company);});

onBeforeUnmount(() => {
  abortCandidateRequest();
  saveLphState();
});

watch(
  () => filters.id_perusahaan,
  (value, previousValue) => {
    if (restoringState.value) return;
    if (String(value || '') === String(previousValue || '')) return;
    resetBranchWhenCompanyChanges(filters, 'id_perusahaan', 'id_cabang', branchRows.value, auth, companyRows.value);
    filters.page = 1;
    totalRows.value = 0;
    rows.value = [];
    detailRows.value = [];
    selectedRow.value = null;
  }
);

watch(
  () => filters.id_cabang,
  (branchId, previousBranchId) => {
    if (restoringState.value) return;
    if (String(branchId || '') === String(previousBranchId || '')) return;
    filters.page = 1;
    totalRows.value = 0;
    rows.value = [];
    detailRows.value = [];
    selectedRow.value = null;
  }
);

watch(
  () => filters.tanggal_awal,
  (value) => {
    if (value && filters.tanggal_akhir && filters.tanggal_akhir < value) {
      filters.tanggal_akhir = value;
    }
  }
);

watch(
  () => createForm.id_cabang,
  (branchId, previousBranchId) => {
    if (String(branchId || '') === String(previousBranchId || '')) return;
    createForm.id_sales = canUseLoginScope.value && fallbackSalesId.value ? String(fallbackSalesId.value) : '';
    clearCandidateScope();
  }
);

watch(
  () => createForm.id_sales,
  (salesId, previousSalesId) => {
    if (String(salesId || '') === String(previousSalesId || '')) return;
    clearCandidateScope();
  }
);

watch(
  () => createForm.id_perusahaan,
  (value, previousValue) => {
    if (String(value || '') === String(previousValue || '')) return;
    resetBranchWhenCompanyChanges(createForm, 'id_perusahaan', 'id_cabang', branchRows.value, auth, companyRows.value);
    createForm.id_sales = canUseLoginScope.value && fallbackSalesId.value ? String(fallbackSalesId.value) : '';
    clearCandidateScope();
  }
);

watch(
  () => createForm.is_cp,
  (value, previousValue) => {
    if (String(value || '') === String(previousValue || '')) return;
    clearCandidateScope();
  }
);

watch(
  () => createForm.include_other_sales,
  (value, previousValue) => {
    if (value === previousValue) return;
    clearCandidateScope();
  }
);

watch(
  () => [createForm.tanggal_lph, createForm.tanggal_jatuh_tempo_sampai],
  (value, previousValue) => {
    if (
      value?.[0] === previousValue?.[0]
      && value?.[1] === previousValue?.[1]
    ) return;
    clearCandidateScope();
  }
);
</script>

<template>
  <div class="space-y-6">
    <PageHeader title="LPH" description="Cetak dan audit Laporan Penagihan Harian dari data LPH yang sudah dibuat backend.">
      <div class="flex flex-wrap gap-2">
        <button class="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700" @click="openCreateModal">
          Tambah LPH
        </button>
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60" :disabled="!canModifySelectedLph" @click="openEditModal">
          Edit
        </button>
        <button class="rounded-xl border border-rose-200 px-4 py-2 text-sm font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-60" :disabled="!canModifySelectedLph || loading.delete" @click="handleDeleteLph">
          Hapus
        </button>
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="loadRows">
          Refresh
        </button>
        <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60" :disabled="!detailRows.length" @click="printLph">
          Cetak LPH
        </button>
      </div>
    </PageHeader>

    <section class="panel p-5">
      <div class="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-12">
        <AppSearchSelect v-model="filters.id_perusahaan" class="min-w-0 2xl:col-span-2" label="Perusahaan" placeholder="Pilih perusahaan" :options="companyOptions" :disabled="shouldLockBusinessScope && !!fallbackCompanyId" empty-text="Perusahaan belum tersedia." />
        <AppSearchSelect v-model="filters.id_cabang" class="min-w-0 2xl:col-span-2" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="!filters.id_perusahaan || (shouldLockBusinessScope && !!fallbackBranchId)" empty-text="Pilih perusahaan terlebih dahulu." />
        <AppFormField v-model="filters.tanggal_awal" class="min-w-0 2xl:col-span-2" label="Tanggal Awal" type="date" />
        <AppFormField v-model="filters.tanggal_akhir" class="min-w-0 2xl:col-span-2" label="Tanggal Akhir" type="date" :min="filters.tanggal_awal || undefined" />
        <label class="min-w-0 2xl:col-span-2">
          <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Cari LPH</span>
          <input
            v-model="filters.search"
            type="search"
            placeholder="Kode LPH, sales, pencetak..."
            class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
            @keyup.enter="loadRows"
          >
        </label>
        <label class="min-w-0 2xl:col-span-1">
          <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Limit</span>
          <input v-model="filters.limit" type="number" min="10" max="200" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none">
        </label>
        <button class="self-end rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white 2xl:col-span-1" @click="loadRows">
          Tampilkan
        </button>
      </div>
    </section>

    <div v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{{ feedback }}</div>
    <div v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ errorMessage }}</div>

    <section class="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(420px,0.85fr)]">
      <article class="panel p-5">
        <div class="mb-4">
          <h3 class="text-lg font-semibold text-slate-900">Daftar LPH</h3>
          <p class="mt-1 text-sm text-slate-500">Klik baris untuk melihat detail tagihan dan status serah-terima LPH. Edit/hapus hanya tersedia sebelum LPH diterima sales.</p>
        </div>
        <AppTable
          :rows="tableRows"
          :paginated="false"
          :columns="[
            { key: 'kode_lph', label: 'Kode LPH' },
            { key: 'tanggal_label', label: 'Tanggal' },
            { key: 'sales_label', label: 'Sales' },
            { key: 'status_label', label: 'Status Dokumen' },
            { key: 'tanggal_diterima_label', label: 'Diterima Sales' },
            { key: 'tanggal_dikembalikan_label', label: 'Dikembalikan' },
            { key: 'pencetak_label', label: 'Pencetak' }
          ]"
          :loading="loading.list"
          :clickable-rows="true"
          row-key="row_key"
          :selected-key="selectedRow?.id || ''"
          empty-message="Belum ada LPH pada cabang ini."
          @row-click="loadDetail"
        />
        <div class="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm text-slate-600">
          <span>Halaman {{ filters.page }} dari {{ totalPages }} · {{ totalRows.toLocaleString('id-ID') }} LPH</span>
          <div class="flex gap-2">
            <button class="rounded-xl border border-slate-200 px-3 py-2 disabled:opacity-40" :disabled="loading.list || filters.page <= 1" @click="loadRows(filters.page - 1)">Sebelumnya</button>
            <button class="rounded-xl border border-slate-200 px-3 py-2 disabled:opacity-40" :disabled="loading.list || filters.page >= totalPages" @click="loadRows(filters.page + 1)">Berikutnya</button>
          </div>
        </div>
      </article>

      <article class="panel p-5">
        <div class="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 class="text-lg font-semibold text-slate-900">Ringkasan Cetak</h3>
            <p class="mt-1 text-sm text-slate-500">{{ selectedRow ? selectedRow.kode_lph : 'Pilih LPH terlebih dahulu.' }}</p>
          </div>
          <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60" :disabled="!detailRows.length || loading.print" @click="handleReprint">
            Cetak Ulang
          </button>
        </div>

        <section class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-slate-400">Total Faktur</p>
            <p class="mt-2 text-xl font-semibold text-slate-900">{{ detailRows.length.toLocaleString('id-ID') }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-slate-400">Total Tagihan</p>
            <p class="mt-2 text-xl font-semibold text-slate-900">{{ formatCurrency(detailTotal) }}</p>
          </div>
          <div class="rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-sky-600">Status Dokumen</p>
            <p class="mt-2 text-base font-semibold text-sky-900">{{ selectedHeader.status_label || resolveLphDocumentStatus(selectedDocumentStatus) }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-slate-400">Serah Terima</p>
            <p class="mt-2 text-sm font-semibold text-slate-900">{{ formatDate(selectedHeader.tanggal_diterima) }}</p>
            <p class="mt-1 text-xs text-slate-500">Kembali: {{ formatDate(selectedHeader.tanggal_dikembalikan) }}</p>
          </div>
        </section>

        <p class="mt-3 text-xs leading-5 text-slate-500">Status dokumen berubah dari aplikasi Mobile Sales saat sales menerima atau mengembalikan LPH. LPH yang sudah aktif/dikembalikan dikunci agar catatan tagihan dan pembayaran tetap dapat diaudit.</p>

        <div class="mt-4 overflow-hidden rounded-2xl border border-slate-200">
          <AppTable
            :rows="detailRows.map((item, index) => ({
              ...item,
              row_key: `${item.id || index}`,
              tagihan_label: formatCurrency(item.sisa_pembayaran || item.jumlah_tagihan),
              jatuh_tempo_label: formatDate(item.tanggal_jatuh_tempo),
              retur_label: formatCurrency(item.nominal_retur)
            }))"
            :columns="[
              { key: 'no_faktur', label: 'Faktur' },
              { key: 'nama_customer', label: 'Customer' },
              { key: 'tagihan_label', label: 'Tagihan' },
              { key: 'jatuh_tempo_label', label: 'Jatuh Tempo' },
              { key: 'retur_label', label: 'Retur' }
            ]"
            :loading="loading.detail"
            row-key="row_key"
            empty-message="Detail LPH belum tersedia."
          />
        </div>
      </article>
    </section>

    <AppModal
      :open="createModalOpen"
      title="Tambah LPH"
      description="Pilih perusahaan, cabang, dan sales. Tipe LPH mengikuti asal seluruh detail order pada setiap faktur."
      size="6xl"
      @close="closeCreateModal"
    >
      <div class="space-y-5">
        <section class="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-12">
          <AppSearchSelect v-model="createForm.id_perusahaan" class="min-w-0 xl:col-span-2" label="Perusahaan" placeholder="Pilih perusahaan" :options="createCompanyOptions" :disabled="shouldLockBusinessScope && !!fallbackCompanyId" empty-text="Perusahaan belum tersedia." />
          <AppSearchSelect v-model="createForm.id_cabang" class="min-w-0 xl:col-span-2" label="Cabang" placeholder="Pilih cabang" :options="createBranchOptions" :disabled="!createForm.id_perusahaan || (shouldLockBusinessScope && !!fallbackBranchId)" empty-text="Pilih perusahaan terlebih dahulu." />
          <AppSearchSelect v-model="createForm.id_sales" class="min-w-0 xl:col-span-2" label="Sales" placeholder="Pilih sales" :options="salesOptions" :disabled="canUseLoginScope && !!fallbackSalesId" empty-text="Sales belum tersedia." />
          <label v-if="auth.hasPermission('finance.receipts.create')" class="min-w-0 xl:col-span-2 field-label">Alur pembayaran<select v-model="createForm.payment_workflow_version" class="field-control mt-1"><option value="2" :disabled="preferredWorkflow(createForm.id_perusahaan)!=='2'">Kuitansi &amp; Giro (baru)</option><option value="1">Rekap lama</option></select><span class="mt-1 block text-xs">Alur baru dipilih otomatis untuk perusahaan yang sudah diaktifkan. Dokumen lama tidak diubah.</span><span v-if="workflowOptionsError" class="text-amber-700">{{ workflowOptionsError }}</span></label>
          <AppFormField v-model="createForm.tanggal_lph" class="min-w-0 xl:col-span-2" label="Tanggal LPH" type="date" />
          <AppFormField v-model="createForm.tanggal_jatuh_tempo_sampai" class="min-w-0 xl:col-span-2" label="Jatuh Tempo s.d." type="date" />
          <AppSearchSelect
            v-model="createForm.is_cp"
            class="min-w-0 xl:col-span-2"
            label="Tipe"
            placeholder="Pilih tipe"
            :options="[
              { value: '2', label: 'Gabungan (Call Plan + Non Call Plan)' },
              { value: '1', label: 'Call Plan' },
              { value: '0', label: 'Non Call Plan' }
            ]"
          />
        </section>

        <p class="-mt-2 text-xs text-slate-500">
          Tanggal LPH menentukan tanggal dokumen. Field jatuh tempo bersifat opsional dan hanya membatasi kandidat yang ditampilkan.
        </p>

        <div class="flex flex-wrap items-center gap-3 rounded-2xl border border-sky-100 bg-sky-50 px-4 py-3 text-sm text-sky-900">
          <template v-if="createForm.is_cp === '2'">
            <span class="font-semibold">Mode gabungan menampilkan seluruh faktur eligible: Call Plan, Non Call Plan, maupun faktur dengan detail order campuran.</span>
            <span class="text-sky-700">Pilih faktur yang diperlukan satu per satu; satu faktur tetap hanya boleh tercatat pada satu LPH aktif.</span>
          </template>
          <template v-else-if="createForm.is_cp === '1'">
            <span class="font-semibold">Call Plan mengambil faktur belum lunas yang seluruh detail ordernya berasal dari kunjungan Call Plan.</span>
            <span class="text-sky-700">Klasifikasi memakai riwayat kunjungan pada tanggal sumber order, bukan jadwal yang bisa berubah setelah transaksi.</span>
          </template>
          <template v-else>
            <span class="font-semibold">Non Call Plan mengambil faktur belum lunas yang seluruh detail ordernya bukan berasal dari kunjungan Call Plan.</span>
          </template>

          <label
            class="flex items-center gap-2 font-semibold"
            :class="createForm.id_perusahaan ? 'cursor-pointer' : 'cursor-not-allowed opacity-60'"
            :title="createForm.id_perusahaan ? 'Tampilkan kandidat dari sales lain dalam perusahaan dan cabang yang dipilih.' : 'Pilih perusahaan terlebih dahulu untuk menampilkan kandidat dari sales lain.'"
          >
            <input
              v-model="createForm.include_other_sales"
              type="checkbox"
              :disabled="!createForm.id_perusahaan"
              class="h-4 w-4 rounded border-sky-300 text-brand-600 focus:ring-brand-500 disabled:cursor-not-allowed"
            >
            Tampilkan kandidat faktur dari sales lain
          </label>
          <span v-if="!createForm.id_perusahaan" class="text-sky-700">Pilih perusahaan terlebih dahulu untuk memakai opsi ini.</span>
          <span class="text-sky-700">
            Kandidat tetap dibatasi pada perusahaan dan cabang yang dipilih; sales pada header tetap menjadi pemegang LPH.
          </span>
          <span v-if="createForm.include_other_sales" class="text-sky-700">
            Pilih faktur satu per satu sebelum menyimpan, termasuk pada tipe Call Plan.
          </span>
          <span v-else-if="createForm.is_cp === '1'" class="text-sky-700">
            Kandidat Call Plan dari sales di header dipilih otomatis seperti alur sebelumnya.
          </span>
        </div>

        <div class="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <div>
            <p class="text-sm font-semibold text-slate-900">Kandidat tagihan terpilih: {{ selectedCandidateRows.length }}</p>
            <p class="text-xs text-slate-500">Total: {{ formatCurrency(selectedCandidateTotal) }} | Retur: {{ formatCurrency(selectedCandidateRetur) }}</p>
          </div>
          <button class="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-60" :disabled="loading.candidates" @click="loadCandidates">
            {{ loading.candidates ? 'Memuat...' : 'Muat Kandidat' }}
          </button>
        </div>

        <div class="max-h-[44vh] overflow-auto rounded-2xl border border-slate-200">
          <table class="min-w-full divide-y divide-slate-200 text-sm">
            <thead class="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th class="px-3 py-3">Pilih</th>
                <th class="px-3 py-3">Faktur</th>
                <th class="px-3 py-3">Jatuh Tempo</th>
                <th class="px-3 py-3">Customer</th>
                <th class="px-3 py-3">Sales Sumber</th>
                <th class="px-3 py-3">Asal Faktur</th>
                <th class="px-3 py-3">Credit Note / Retur</th>
                <th class="px-3 py-3 text-right">Retur</th>
                <th class="px-3 py-3 text-right">Sisa Tagihan</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100">
              <tr v-for="item in candidateRows" :key="item.id_faktur">
                <td class="px-3 py-3">
                  <input type="checkbox" :checked="selectedCandidateIds.includes(String(item.id_faktur))" @change="toggleCandidate(item.id_faktur)">
                </td>
                <td class="px-3 py-3 font-semibold text-slate-900">{{ item.no_faktur || '-' }}</td>
                <td class="px-3 py-3">{{ formatDate(item.tanggal_jatuh_tempo) }}</td>
                <td class="px-3 py-3">{{ item.kode_customer || '-' }} - {{ item.nama_customer || '-' }}</td>
                <td class="px-3 py-3">{{ item.nama_sales || '-' }}</td>
                <td class="px-3 py-3">{{ formatCandidateSource(item) }}</td>
                <td class="px-3 py-3">
                  <details class="relative w-64">
                    <summary class="flex cursor-pointer list-none items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 outline-none">
                      <span class="truncate">
                        {{ item.selected_retur_options?.length ? `${item.selected_retur_options.length} CN/Retur dipilih` : 'Tanpa Retur/CN' }}
                      </span>
                      <span class="text-xs text-slate-400">v</span>
                    </summary>
                    <div class="absolute z-20 mt-2 w-80 rounded-xl border border-slate-200 bg-white p-2 shadow-xl">
                      <label v-if="item.nominal_retur && item.selected_retur_options?.includes('manual')" class="flex items-start gap-2 rounded-lg px-2 py-2 text-sm text-slate-700">
                        <input type="checkbox" checked disabled class="mt-1">
                        <span>
                          <span class="block font-medium">{{ item.kode_cn || 'Retur tersimpan' }}</span>
                          <span class="block text-xs text-slate-500">{{ formatCurrency(item.nominal_retur) }}</span>
                        </span>
                      </label>
                      <label v-for="option in item.retur_options || []" :key="option.option_key" class="flex cursor-pointer items-start gap-2 rounded-lg px-2 py-2 text-sm text-slate-700 hover:bg-slate-50">
                        <input
                          type="checkbox"
                          class="mt-1"
                          :checked="item.selected_retur_options?.includes(option.option_key)"
                          @change="toggleCandidateReturOption(item, option.option_key)"
                        >
                        <span>
                          <span class="block font-medium">{{ option.kode || option.source_type }}</span>
                          <span class="block text-xs text-slate-500">{{ formatCurrency(option.nominal) }}</span>
                        </span>
                      </label>
                      <p v-if="!(item.retur_options || []).length && !item.nominal_retur" class="px-2 py-3 text-sm text-slate-500">
                        Tidak ada Credit Note/Retur tersedia.
                      </p>
                    </div>
                  </details>
                </td>
                <td class="px-3 py-3 text-right">{{ formatCurrency(item.nominal_retur) }}</td>
                <td class="px-3 py-3 text-right">{{ formatCurrency(item.sisa_pembayaran) }}</td>
              </tr>
              <tr v-if="!candidateRows.length">
                <td colspan="9" class="px-3 py-8 text-center text-slate-500">Belum ada kandidat. Klik Muat Kandidat setelah filter lengkap.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <template #footer>
        <div class="flex justify-end gap-2">
          <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700" @click="closeCreateModal">Batal</button>
          <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60" :disabled="loading.save || !selectedCandidateRows.length" @click="saveCreateLph">
            {{ loading.save ? 'Menyimpan...' : 'Simpan LPH' }}
          </button>
        </div>
      </template>
    </AppModal>

    <AppModal
      :open="editModalOpen"
      title="Edit LPH"
      description="Revisi header dan nominal detail LPH."
      size="6xl"
      @close="editModalOpen = false"
    >
      <div class="space-y-5">
        <section class="grid gap-4 md:grid-cols-4">
          <AppSearchSelect v-model="editForm.id_sales" label="Sales pemegang LPH" placeholder="Pilih sales" :options="salesOptions" disabled empty-text="Sales belum tersedia." />
          <AppFormField v-model="editForm.tanggal_lph" label="Tanggal LPH" type="date" />
          <AppSearchSelect
            v-model="editForm.is_cp"
            label="Tipe sumber"
            placeholder="Pilih tipe"
            disabled
            :options="[
              { value: '2', label: 'Gabungan (Call Plan + Non Call Plan)' },
              { value: '1', label: 'Call Plan' },
              { value: '0', label: 'Non Call Plan' }
            ]"
          />
          <AppFormField v-model="editForm.id_lph" label="ID LPH" readonly />
        </section>

        <div class="max-h-[48vh] overflow-auto rounded-2xl border border-slate-200">
          <table class="min-w-full divide-y divide-slate-200 text-sm">
            <thead class="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th class="px-3 py-3">Faktur</th>
                <th class="px-3 py-3">Customer</th>
                <th class="px-3 py-3">Kode CN</th>
                <th class="px-3 py-3">Retur</th>
                <th class="px-3 py-3">Jumlah Tagihan</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100">
              <tr v-for="item in editDetails" :key="item.id">
                <td class="px-3 py-3 font-semibold text-slate-900">{{ item.no_faktur || '-' }}</td>
                <td class="px-3 py-3">{{ item.kode_customer || '-' }} - {{ item.nama_customer || '-' }}</td>
                <td class="px-3 py-3">
                  <input v-model="item.kode_cn" class="w-36 rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand-400">
                </td>
                <td class="px-3 py-3">
                  <input v-model.number="item.nominal_retur" type="number" min="0" class="w-32 rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand-400">
                </td>
                <td class="px-3 py-3">
                  <input v-model.number="item.jumlah_tagihan" type="number" min="0" class="w-36 rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand-400">
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <template #footer>
        <div class="flex justify-end gap-2">
          <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700" @click="editModalOpen = false">Batal</button>
          <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60" :disabled="loading.save" @click="saveEditLph">
            {{ loading.save ? 'Menyimpan...' : 'Update LPH' }}
          </button>
        </div>
      </template>
    </AppModal>
  </div>
</template>
