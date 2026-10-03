<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import {
  createPurchaseBill,
  createPurchaseBillPayment,
  getPurchaseBillCandidateTransactions,
  getPurchaseBillDetail,
  getPurchaseBillingQueue,
  getPurchasePayables
} from '@/api/purchase';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import {
  canAccessAllPurchaseBranches,
  getPurchaseBranchOptions,
  getPurchaseCompanyIdsForBranch,
  getPurchaseCompanyOptions,
  getPurchaseFallbackBranchId,
  getPurchaseFallbackCompanyId,
  getPurchasePrincipalOptions
} from '@/modules/purchase/utils/purchaseScope';
import { useAuthStore } from '@/stores/auth';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const route = useRoute();
const authStore = useAuthStore();

const filters = reactive({
  branchId: '',
  companyId: '',
  principalId: '',
  search: ''
});

const builderFilters = reactive({
  dateFrom: '',
  dateTo: ''
});

const loading = reactive({
  payables: false,
  payableDetail: false,
  candidates: false,
  billing: false,
  submit: false,
  payment: false
});

const companyRows = ref([]);
const branchRows = ref([]);
const principalRows = ref([]);
const payableRows = ref([]);
const candidateRows = ref([]);
const billingRows = ref([]);
const payableDetailRows = ref([]);
const errorMessage = ref('');
const successMessage = ref('');
const successToast = ref('');
const selectedPayable = ref(null);
const payableModalOpen = ref(false);
const selectedCandidateIds = ref([]);
const paymentProofFile = ref(null);
let toastTimer = null;

const paymentForm = reactive({
  tanggal_bayar: '',
  tipe_setoran: 'TRANSFER',
  keterangan: ''
});
const fallbackBranchId = computed(() => getPurchaseFallbackBranchId(authStore));
const fallbackCompanyId = computed(() => getPurchaseFallbackCompanyId(authStore));
const canAccessAllBranches = computed(() => canAccessAllPurchaseBranches(authStore));
const canUseLoginScope = computed(() => !canAccessAllBranches.value);

const filterFields = computed(() => [
  {
    key: 'companyId',
    label: 'Perusahaan',
    type: 'search-select',
    options: companyOptions.value,
    disabled: canUseLoginScope.value && !!fallbackCompanyId.value
  },
  {
    key: 'branchId',
    label: 'Cabang',
    type: 'search-select',
    options: branchOptions.value,
    disabled: (canUseLoginScope.value && !filters.companyId) || (!canAccessAllBranches.value && !!fallbackBranchId.value)
  },
  {
    key: 'principalId',
    label: 'Principal',
    type: 'search-select',
    options: principalOptions.value
  },
  {
    key: 'search',
    label: 'Cari',
    placeholder: 'No tagihan / principal'
  }
]);

const branchOptions = computed(() =>
  getPurchaseBranchOptions(branchRows.value, authStore, filters.companyId, companyRows.value)
);

const companyOptions = computed(() =>
  getPurchaseCompanyOptions(companyRows.value, branchRows.value, filters.branchId, authStore)
);

const principalOptions = computed(() =>
  getPurchasePrincipalOptions(principalRows.value, filters.companyId)
);

const payableSummary = computed(() => {
  const total = payableRows.value.length;
  const unpaid = payableRows.value.filter((item) => String(item.status_bayar || '').toLowerCase().includes('belum')).length;
  const totalTagihan = payableRows.value.reduce((sum, item) => sum + Number(item.total_tagihan || 0), 0);
  return [
    { label: 'Total Tagihan', value: String(total) },
    { label: 'Belum Lunas', value: String(unpaid) },
    { label: 'Nominal Tagihan', value: formatCurrency(totalTagihan) }
  ];
});

const payableTableRows = computed(() =>
  payableRows.value
    .filter((item) => {
      const query = filters.search.trim().toLowerCase();
      if (!query) return true;
      return [item.surat_tagihan, item.nama_principal, item.status_bayar]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query));
    })
    .map((item) => ({
      ...item,
      total_tagihan_label: formatCurrency(item.total_tagihan || 0),
      status_bayar_label: resolveBillStatus(item.status_bayar),
      jumlah_faktur_label: String(item.jumlah_faktur || 0)
    }))
);

const candidateTableRows = computed(() =>
  candidateRows.value.map((item) => ({
    ...item,
    row_key: String(item.id_purchase_transaksi),
    subtotal_label: formatCurrency(item.subtotal || 0),
    branch_label: resolveBranchName(item.id_cabang),
    company_label: resolveCompanyName(item.id_perusahaan),
    selected_label: selectedCandidateIds.value.includes(String(item.id_purchase_transaksi))
      ? 'Dipilih'
      : isCandidateSelectable(item)
        ? 'Belum'
        : 'Beda scope'
  }))
);

const billingTableRows = computed(() =>
  billingRows.value.map((item) => ({
    ...item,
    row_key: String(item.id),
    status_label: resolveBillingStage(item.proses_id_berjalan),
    subtotal_label: formatCurrency(item.subtotal || 0),
    total_label: formatCurrency(item.total || 0)
  }))
);

const selectedCandidatesTotal = computed(() =>
  candidateRows.value
    .filter((item) => selectedCandidateIds.value.includes(String(item.id_purchase_transaksi)))
    .reduce((sum, item) => sum + Number(item.subtotal || 0), 0)
);

const selectedCandidateRows = computed(() =>
  candidateRows.value.filter((item) => selectedCandidateIds.value.includes(String(item.id_purchase_transaksi)))
);

const selectedCandidatePrincipal = computed(() => {
  const principals = [...new Set(selectedCandidateRows.value.map((item) => String(item.nama_principal || item.principal || '')))].filter(Boolean);
  return principals.length === 1 ? principals[0] : principals.length > 1 ? 'Multi Principal' : '-';
});

const selectedCandidateScope = computed(() => {
  const [firstRow] = selectedCandidateRows.value;
  if (!firstRow) return null;
  return {
    key: getCandidateScopeKey(firstRow),
    branchId: firstRow.id_cabang,
    companyId: firstRow.id_perusahaan,
    principalId: firstRow.id_principal,
    branchName: resolveBranchName(firstRow.id_cabang),
    companyName: resolveCompanyName(firstRow.id_perusahaan),
    principalName: firstRow.nama_principal || '-'
  };
});

const selectedCandidateScopeLabel = computed(() => {
  if (!selectedCandidateScope.value) return '-';
  return [
    selectedCandidateScope.value.branchName,
    selectedCandidateScope.value.companyName,
    selectedCandidateScope.value.principalName
  ].filter(Boolean).join(' | ');
});

const selectedCandidateScopeValid = computed(() => {
  if (!selectedCandidateRows.value.length) return true;
  const scopeKey = selectedCandidateScope.value?.key || '';
  return selectedCandidateRows.value.every((item) => getCandidateScopeKey(item) === scopeKey);
});

const billBuilderMessage = computed(() => {
  if (!selectedCandidateRows.value.length) {
    return 'Satu tagihan purchase hanya boleh berisi transaksi dari Cabang + Perusahaan + Principal yang sama.';
  }
  if (!selectedCandidateScopeValid.value) {
    return 'Ada transaksi beda cabang/perusahaan/principal. Pisahkan tagihan sesuai kombinasi masing-masing.';
  }
  return `Tagihan akan dibuat untuk ${selectedCandidateScopeLabel.value}.`;
});

const canCreateBill = computed(() =>
  selectedCandidateIds.value.length > 0 &&
  selectedCandidatePrincipal.value !== 'Multi Principal' &&
  selectedCandidateScopeValid.value
);

const selectedDueDateRange = computed(() => {
  const dates = selectedCandidateRows.value.map((item) => item.jatuh_tempo).filter(Boolean).sort();
  if (!dates.length) return '-';
  if (dates.length === 1) return dates[0];
  return `${dates[0]} s/d ${dates[dates.length - 1]}`;
});

const payableDetailTableRows = computed(() =>
  payableDetailRows.value.map((item, index) => ({
    ...item,
    row_key: `${item.id_tagihan_detail || index}`,
    subtotal_label: formatCurrency(item.subtotal || 0),
    status_bayar_label: resolveBillStatus(item.status_bayar || '-')
  }))
);

const selectedPayableMeta = computed(() => {
  if (!selectedPayable.value) return [];
  return [
    { label: 'No Tagihan', value: selectedPayable.value.surat_tagihan || '-' },
    { label: 'Principal', value: selectedPayable.value.nama_principal || '-' },
    { label: 'Total Tagihan', value: formatCurrency(selectedPayable.value.total_tagihan || 0) },
    { label: 'Status', value: resolveBillStatus(selectedPayable.value.status_bayar || '-') },
    { label: 'Jatuh Tempo', value: selectedPayable.value.jatuh_tempo || '-' },
    { label: 'Tanggal Bayar', value: selectedPayable.value.tanggal_bayar || '-' },
    { label: 'Metode Bayar', value: selectedPayable.value.tipe_setoran || '-' }
  ];
});

const paymentHistoryRows = computed(() => {
  if (!selectedPayable.value) return [];
  return [
    {
      row_key: `${selectedPayable.value.id_tagihan || selectedPayable.value.surat_tagihan}-history`,
      tanggal_bayar: selectedPayable.value.tanggal_bayar || '-',
      nominal_label: formatCurrency(selectedPayable.value.total_tagihan || 0),
      status_label: resolveBillStatus(selectedPayable.value.status_bayar || '-'),
      metode: selectedPayable.value.tipe_setoran || '-',
      keterangan: selectedPayable.value.keterangan || '-'
    }
  ];
});

const canSubmitPayment = computed(() => {
  if (!selectedPayable.value) return false;
  return String(selectedPayable.value.status_bayar || '').toLowerCase().includes('belum');
});

function formatCurrency(value) {
  return `Rp ${new Intl.NumberFormat('id-ID').format(Number(value || 0))}`;
}

function formatInputDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function addDays(date, days) {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

function setBuilderDateRange(daysAhead = 120) {
  const today = new Date();
  builderFilters.dateFrom = formatInputDate(today);
  builderFilters.dateTo = formatInputDate(addDays(today, daysAhead));
}

function clearBuilderDateRange() {
  builderFilters.dateFrom = '';
  builderFilters.dateTo = '';
}

function formatDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('id-ID', { day: '2-digit', month: 'long', year: 'numeric' }).format(date);
}

function escapeHtml(value) {
  return String(value ?? '-')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function showToast(message) {
  successToast.value = message;
  if (toastTimer) {
    clearTimeout(toastTimer);
  }
  toastTimer = setTimeout(() => {
    successToast.value = '';
  }, 3200);
}

function resolveBillStatus(value) {
  const text = String(value || '-');
  if (text.toLowerCase().includes('belum')) {
    return { text, className: 'inline-flex rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700' };
  }
  if (text.toLowerCase().includes('lunas')) {
    return { text, className: 'inline-flex rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700' };
  }
  return { text, className: 'inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600' };
}

function resolveBillingStage(value) {
  const key = Number(value || 0);
  const map = {
    3: { text: 'Siap Tagihan', className: 'inline-flex rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700' },
    4: { text: 'Pelunasan', className: 'inline-flex rounded-full bg-indigo-100 px-3 py-1 text-xs font-semibold text-indigo-700' },
    5: { text: 'Lunas', className: 'inline-flex rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700' }
  };
  return map[key] || { text: `Status ${key || '-'}`, className: 'inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600' };
}

function resolveBranchName(branchId) {
  const branch = branchRows.value.find((item) => String(item.id) === String(branchId));
  return branch?.nama || branch?.cabang_nama || (branchId ? `Cabang ${branchId}` : '-');
}

function resolveCompanyName(companyId) {
  const company = companyRows.value.find((item) => String(item.id) === String(companyId));
  return company?.nama || company?.nama_perusahaan || (companyId ? `Perusahaan ${companyId}` : '-');
}

function getCandidateScopeKey(row) {
  return [
    row?.id_cabang || '',
    row?.id_perusahaan || '',
    row?.id_principal || ''
  ].join('|');
}

function isCandidateSelectable(row) {
  if (!selectedCandidateScope.value) return true;
  return getCandidateScopeKey(row) === selectedCandidateScope.value.key;
}

function getBranchCompanyIds(branchId) {
  return getPurchaseCompanyIdsForBranch(branchId, branchRows.value, companyRows.value).map(String);
}

function branchMatchesSelectedCompany(branchId, companyId = filters.companyId) {
  if (!branchId || !companyId) return true;
  return getBranchCompanyIds(branchId).includes(String(companyId));
}

function updateFilters(nextFilters = {}) {
  const previousCompanyId = String(filters.companyId || '');
  const previousBranchId = String(filters.branchId || '');
  const nextCompanyId = String(nextFilters.companyId || '');
  const nextBranchId = String(nextFilters.branchId || '');

  filters.companyId = nextCompanyId;
  filters.search = nextFilters.search || '';

  if (nextCompanyId !== previousCompanyId) {
    filters.principalId = '';
    if (nextBranchId && !branchMatchesSelectedCompany(nextBranchId, nextCompanyId)) {
      filters.branchId = '';
      errorMessage.value = 'Cabang dikosongkan karena tidak terdaftar pada perusahaan yang dipilih.';
    } else {
      filters.branchId = nextBranchId;
    }
    clearBillSelections();
    return;
  }

  if (nextBranchId !== previousBranchId && nextBranchId && !branchMatchesSelectedCompany(nextBranchId, nextCompanyId)) {
    filters.branchId = '';
    filters.principalId = '';
    errorMessage.value = 'Cabang yang dipilih tidak sesuai dengan perusahaan aktif.';
    clearBillSelections();
    return;
  }

  filters.branchId = nextBranchId;
  filters.principalId = nextFilters.principalId || '';
  syncPrincipalFromCompany();
}

function resetFilters() {
  filters.companyId = canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
  filters.branchId = String(fallbackBranchId.value || '');
  filters.principalId = '';
  filters.search = '';
  syncBranchFromCompany();
  loadAll();
}

function resetBuilderSelection() {
  selectedCandidateIds.value = [];
}

function resetPaymentForm() {
  paymentForm.tanggal_bayar = '';
  paymentForm.tipe_setoran = 'TRANSFER';
  paymentForm.keterangan = '';
  paymentProofFile.value = null;
}

async function loadPrincipals() {
  const [companyResponse, branchResponse, principalResponse] = await Promise.all([getCompanies(), getBranches(), getPrincipals()]);
  companyRows.value = normalizeList(unwrapResponse(companyResponse));
  branchRows.value = normalizeList(unwrapResponse(branchResponse));
  principalRows.value = normalizeList(unwrapResponse(principalResponse));
  if (!filters.branchId && route.query.branchId) {
    filters.branchId = String(route.query.branchId);
  } else if (!filters.branchId && fallbackBranchId.value) {
    filters.branchId = String(fallbackBranchId.value);
  }
  if (!filters.companyId && route.query.companyId) {
    filters.companyId = String(route.query.companyId);
  } else if (!filters.companyId && canUseLoginScope.value && fallbackCompanyId.value) {
    filters.companyId = String(fallbackCompanyId.value);
  }
  if (!filters.principalId && route.query.principalId) {
    filters.principalId = String(route.query.principalId);
  }
  syncBranchFromCompany();
  syncPrincipalFromCompany();
}

function clearBillSelections() {
  payableRows.value = [];
  billingRows.value = [];
  candidateRows.value = [];
  selectedPayable.value = null;
  payableModalOpen.value = false;
  payableDetailRows.value = [];
  resetBuilderSelection();
}

function syncBranchFromCompany() {
  if (!filters.companyId) {
    filters.principalId = '';
    return;
  }

  if (
    filters.branchId &&
    !branchMatchesSelectedCompany(filters.branchId)
  ) {
    filters.branchId = '';
    filters.principalId = '';
  }
}

function syncPrincipalFromCompany() {
  if (filters.principalId && !principalOptions.value.some((item) => item.value === String(filters.principalId))) {
    filters.principalId = '';
  }
}

async function loadPayables() {
  loading.payables = true;
  try {
    const params = { 'no-paginate': 'true', field: 'id', order: 'desc' };
    if (filters.branchId) params.id_cabang = filters.branchId;
    if (filters.companyId) params.id_perusahaan = filters.companyId;
    if (filters.principalId) params.principal = filters.principalId;
    const response = await getPurchasePayables(params);
    payableRows.value = normalizeList(unwrapResponse(response));
  } finally {
    loading.payables = false;
  }
}

async function loadBillingQueue() {
  loading.billing = true;
  try {
    const params = { 'no-paginate': 'true', field: 'id', order: 'desc' };
    if (filters.branchId) params.cabang_id = filters.branchId;
    if (filters.companyId) params.id_perusahaan = filters.companyId;
    if (filters.principalId) params.principal_id = filters.principalId;
    const response = await getPurchaseBillingQueue(params);
    billingRows.value = normalizeList(unwrapResponse(response));
  } finally {
    loading.billing = false;
  }
}

async function loadCandidateTransactions() {
  loading.candidates = true;
  errorMessage.value = '';
  successMessage.value = '';
  try {
    const params = { 'no-paginate': 'true', field: 'id', order: 'desc' };
    if (filters.branchId) params.id_cabang = filters.branchId;
    if (filters.companyId) params.id_perusahaan = filters.companyId;
    if (filters.principalId) params.principal = filters.principalId;
    if (builderFilters.dateFrom) params.mulai_jatuh_tempo = builderFilters.dateFrom;
    if (builderFilters.dateTo) params.selesai_jatuh_tempo = builderFilters.dateTo;
    const response = await getPurchaseBillCandidateTransactions(params);
    candidateRows.value = normalizeList(unwrapResponse(response));
    resetBuilderSelection();
  } catch (error) {
    candidateRows.value = [];
    errorMessage.value = normalizeError(error, 'Calon tagihan purchase belum bisa dimuat.');
  } finally {
    loading.candidates = false;
  }
}

async function loadAll() {
  errorMessage.value = '';
  successMessage.value = '';
  try {
    await Promise.all([loadPayables(), loadBillingQueue()]);
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Data tagihan purchase belum bisa dimuat.');
  }
}

async function openPayable(row) {
  selectedPayable.value = row;
  payableModalOpen.value = true;
  payableDetailRows.value = [];
  resetPaymentForm();
  loading.payableDetail = true;
  try {
    const response = await getPurchaseBillDetail(row.surat_tagihan);
    payableDetailRows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    payableDetailRows.value = [];
    errorMessage.value = normalizeError(error, 'Detail tagihan purchase belum bisa dimuat.');
  } finally {
    loading.payableDetail = false;
  }
}

function closePayableModal() {
  payableModalOpen.value = false;
}

function toggleCandidate(row) {
  const id = String(row.id_purchase_transaksi);
  if (selectedCandidateIds.value.includes(id)) {
    selectedCandidateIds.value = selectedCandidateIds.value.filter((item) => item !== id);
  } else {
    if (!isCandidateSelectable(row)) {
      errorMessage.value = 'Transaksi beda cabang/perusahaan/principal. Buat tagihan terpisah untuk scope tersebut.';
      return;
    }
    selectedCandidateIds.value = [...selectedCandidateIds.value, id];
  }
}

function selectAllCandidates() {
  const sourceRows = selectedCandidateRows.value.length
    ? candidateRows.value.filter((item) => isCandidateSelectable(item))
    : candidateRows.value.filter((item) => {
        const firstSelectable = candidateRows.value[0];
        return firstSelectable ? getCandidateScopeKey(item) === getCandidateScopeKey(firstSelectable) : false;
      });
  selectedCandidateIds.value = sourceRows.map((item) => String(item.id_purchase_transaksi));
}

async function submitCreateBill() {
  if (!selectedCandidateIds.value.length) {
    errorMessage.value = 'Pilih minimal satu transaksi purchase untuk dibuatkan tagihan.';
    return;
  }
  if (selectedCandidatePrincipal.value === 'Multi Principal') {
    errorMessage.value = 'Tagihan purchase harus dibentuk dari transaksi dengan principal yang sama.';
    return;
  }
  if (!selectedCandidateScopeValid.value) {
    errorMessage.value = 'Tagihan purchase harus dibentuk dari cabang, perusahaan, dan principal yang sama.';
    return;
  }

  loading.submit = true;
  errorMessage.value = '';
  successMessage.value = '';
  try {
    const payload = {
      purchase_transaksis: candidateRows.value
        .filter((item) => selectedCandidateIds.value.includes(String(item.id_purchase_transaksi)))
        .map((item) => ({
          id_purchase_transaksi: item.id_purchase_transaksi,
          subtotal: item.subtotal
        }))
    };
    await createPurchaseBill(payload);
    successMessage.value = 'Tagihan purchase berhasil dibuat dari transaksi terpilih.';
    showToast(successMessage.value);
    await Promise.all([loadAll(), loadCandidateTransactions()]);
    selectedPayable.value = null;
    payableModalOpen.value = false;
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Tagihan purchase belum berhasil dibuat.');
  } finally {
    loading.submit = false;
  }
}

function onPaymentProofChange(event) {
  const [file] = event?.target?.files || [];
  paymentProofFile.value = file || null;
}

async function submitPayment() {
  if (!selectedPayable.value) {
    errorMessage.value = 'Pilih tagihan purchase terlebih dahulu.';
    return;
  }
  if (!canSubmitPayment.value) {
    errorMessage.value = 'Tagihan ini sudah dibayar atau tidak valid untuk pembayaran.';
    return;
  }
  if (!paymentForm.tanggal_bayar) {
    errorMessage.value = 'Tanggal bayar wajib diisi.';
    return;
  }

  loading.payment = true;
  errorMessage.value = '';
  successMessage.value = '';
  try {
    const formData = new FormData();
    formData.append('no_tagihan', selectedPayable.value.surat_tagihan);
    formData.append('tanggal_bayar', paymentForm.tanggal_bayar);
    formData.append('tipe_setoran', paymentForm.tipe_setoran);
    formData.append('keterangan', paymentForm.keterangan || '');
    if (paymentProofFile.value) {
      formData.append('bukti_bayar', paymentProofFile.value);
    }

    await createPurchaseBillPayment(formData);
    successMessage.value = `Pembayaran tagihan ${selectedPayable.value.surat_tagihan} berhasil diproses.`;
    showToast(successMessage.value);
    await loadAll();
    const refreshed = payableRows.value.find((item) => item.surat_tagihan === selectedPayable.value?.surat_tagihan);
    if (refreshed) {
      await openPayable(refreshed);
    } else {
      selectedPayable.value = null;
      payableDetailRows.value = [];
    }
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Pembayaran tagihan purchase belum berhasil diproses.');
  } finally {
    loading.payment = false;
  }
}

function ensurePrintableBill() {
  if (!selectedPayable.value) {
    errorMessage.value = 'Pilih tagihan purchase terlebih dahulu sebelum mencetak.';
    return false;
  }
  if (loading.payableDetail) {
    errorMessage.value = 'Detail tagihan masih dimuat. Tunggu sebentar sebelum mencetak.';
    return false;
  }
  return true;
}

function printHtml(title, body) {
  const win = window.open('', '_blank', 'width=1024,height=768');
  if (!win) {
    errorMessage.value = 'Popup cetak diblokir browser. Izinkan popup untuk halaman ini.';
    return;
  }

  win.document.write(`
    <!doctype html>
    <html>
      <head>
        <title>${escapeHtml(title)}</title>
        <style>
          * { box-sizing: border-box; }
          body { margin: 0; padding: 28px; color: #0f172a; font-family: Arial, sans-serif; font-size: 12px; background: #fff; }
          .sheet { max-width: 960px; margin: 0 auto; border: 1px solid #0f172a; padding: 24px; }
          .header { display: flex; justify-content: space-between; gap: 24px; border-bottom: 2px solid #0f172a; padding-bottom: 14px; margin-bottom: 18px; }
          h1 { margin: 0; font-size: 18px; letter-spacing: 0.08em; text-transform: uppercase; }
          h2 { margin: 4px 0 0; font-size: 13px; font-weight: 500; }
          .meta { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 28px; margin-bottom: 18px; }
          .meta div { display: grid; grid-template-columns: 120px 1fr; gap: 8px; }
          table { width: 100%; border-collapse: collapse; }
          th, td { border: 1px solid #cbd5e1; padding: 8px; vertical-align: top; }
          th { background: #f1f5f9; text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; }
          .text-right { text-align: right; }
          .summary { margin-top: 18px; display: flex; justify-content: flex-end; }
          .summary table { width: 340px; }
          .signatures { display: grid; grid-template-columns: repeat(3, 1fr); gap: 28px; margin-top: 48px; text-align: center; }
          .line { margin-top: 56px; border-top: 1px solid #0f172a; padding-top: 6px; }
          @media print { body { padding: 0; } .sheet { border: 0; max-width: none; } }
        </style>
      </head>
      <body>${body}</body>
    </html>
  `);
  win.document.close();
  win.focus();
  setTimeout(() => win.print(), 250);
}

function printPurchaseInvoice() {
  if (!ensurePrintableBill()) return;
  const payable = selectedPayable.value;
  const rows = payableDetailTableRows.value;
  const detailRows = rows.length
    ? rows.map((item, index) => `
        <tr>
          <td>${index + 1}</td>
          <td>${escapeHtml(item.no_transaksi || '-')}</td>
          <td>${escapeHtml(item.kode_order || '-')}</td>
          <td>${escapeHtml(formatDate(item.jatuh_tempo))}</td>
          <td class="text-right">${escapeHtml(item.subtotal_label || formatCurrency(item.subtotal || 0))}</td>
          <td>${escapeHtml(item.status_bayar_label?.text || item.status_bayar || '-')}</td>
        </tr>
      `).join('')
    : '<tr><td colspan="6">Belum ada rincian transaksi.</td></tr>';

  printHtml(
    `Faktur Purchase ${payable.surat_tagihan || ''}`,
    `
      <section class="sheet">
        <div class="header">
          <div>
            <h1>Faktur Purchase</h1>
            <h2>PT. Budimas Makmur Mulia</h2>
          </div>
          <div><strong>No Tagihan</strong><br>${escapeHtml(payable.surat_tagihan || '-')}</div>
        </div>
        <div class="meta">
          <div><strong>Principal</strong><span>${escapeHtml(payable.nama_principal || '-')}</span></div>
          <div><strong>Status Bayar</strong><span>${escapeHtml(resolveBillStatus(payable.status_bayar).text)}</span></div>
          <div><strong>Jatuh Tempo</strong><span>${escapeHtml(formatDate(payable.jatuh_tempo))}</span></div>
          <div><strong>Tanggal Bayar</strong><span>${escapeHtml(formatDate(payable.tanggal_bayar))}</span></div>
          <div><strong>Jumlah Faktur</strong><span>${escapeHtml(payable.jumlah_faktur || 0)}</span></div>
          <div><strong>Total Tagihan</strong><span>${escapeHtml(formatCurrency(payable.total_tagihan || 0))}</span></div>
        </div>
        <table>
          <thead>
            <tr>
              <th style="width: 48px;">No</th>
              <th>No Transaksi</th>
              <th>Kode Order</th>
              <th>Jatuh Tempo</th>
              <th class="text-right">Subtotal</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>${detailRows}</tbody>
        </table>
        <div class="summary">
          <table>
            <tr><th>Total Tagihan</th><td class="text-right">${escapeHtml(formatCurrency(payable.total_tagihan || 0))}</td></tr>
          </table>
        </div>
        <div class="signatures">
          <div><div class="line">Purchasing</div></div>
          <div><div class="line">Accounting</div></div>
          <div><div class="line">Supervisor</div></div>
        </div>
      </section>
    `
  );
}

function printPaymentHistory() {
  if (!ensurePrintableBill()) return;
  const payable = selectedPayable.value;
  const rows = paymentHistoryRows.value;
  const historyRows = rows.length
    ? rows.map((item, index) => `
        <tr>
          <td>${index + 1}</td>
          <td>${escapeHtml(formatDate(item.tanggal_bayar))}</td>
          <td class="text-right">${escapeHtml(item.nominal_label || '-')}</td>
          <td>${escapeHtml(item.status_label?.text || item.status_label || '-')}</td>
          <td>${escapeHtml(item.keterangan || '-')}</td>
        </tr>
      `).join('')
    : '<tr><td colspan="5">Belum ada histori pembayaran.</td></tr>';

  printHtml(
    `Riwayat Pelunasan ${payable.surat_tagihan || ''}`,
    `
      <section class="sheet">
        <div class="header">
          <div>
            <h1>Riwayat Pelunasan Purchase</h1>
            <h2>PT. Budimas Makmur Mulia</h2>
          </div>
          <div><strong>No Tagihan</strong><br>${escapeHtml(payable.surat_tagihan || '-')}</div>
        </div>
        <div class="meta">
          <div><strong>Principal</strong><span>${escapeHtml(payable.nama_principal || '-')}</span></div>
          <div><strong>Status Bayar</strong><span>${escapeHtml(resolveBillStatus(payable.status_bayar).text)}</span></div>
          <div><strong>Total Tagihan</strong><span>${escapeHtml(formatCurrency(payable.total_tagihan || 0))}</span></div>
          <div><strong>Tanggal Bayar</strong><span>${escapeHtml(formatDate(payable.tanggal_bayar))}</span></div>
        </div>
        <table>
          <thead>
            <tr>
              <th style="width: 48px;">No</th>
              <th>Tanggal Bayar</th>
              <th class="text-right">Nominal</th>
              <th>Status</th>
              <th>Keterangan</th>
            </tr>
          </thead>
          <tbody>${historyRows}</tbody>
        </table>
        <div class="signatures">
          <div><div class="line">Kasir</div></div>
          <div><div class="line">Accounting</div></div>
          <div><div class="line">Supervisor</div></div>
        </div>
      </section>
    `
  );
}

onMounted(async () => {
  setBuilderDateRange();
  await loadPrincipals();
  await loadAll();
});

watch(
  () => filters.companyId,
  (companyId, previousCompanyId) => {
    if (String(companyId || '') === String(previousCompanyId || '')) return;
    syncBranchFromCompany();
    syncPrincipalFromCompany();
    clearBillSelections();
  }
);

watch(
  () => filters.branchId,
  (branchId, previousBranchId) => {
    if (String(branchId || '') !== String(previousBranchId || '')) {
      filters.principalId = '';
      clearBillSelections();
    }
  }
);
</script>

<template>
  <div class="space-y-6">
    <div v-if="successToast" class="fixed right-4 top-4 z-50 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-800 shadow-lg">
      {{ successToast }}
    </div>

    <PageHeader
      title="Tagihan Purchase Order"
      description="Monitoring hutang purchase yang sudah terbentuk, daftar transaksi siap tagihan, dan alur pembuatan tagihan purchase yang tervalidasi berdasarkan scope serta audit Finance."
    />

    <AppFilterBar :model-value="filters" :fields="filterFields" @update:model-value="updateFilters" @submit="loadPayables" @reset="resetFilters" />

    <section v-if="successMessage" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
      {{ successMessage }}
    </section>
    <section v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ errorMessage }}
    </section>

    <section class="grid gap-4 md:grid-cols-3">
      <article v-for="item in payableSummary" :key="item.label" class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">{{ item.label }}</p>
        <p class="mt-3 text-lg font-semibold text-slate-900">{{ item.value }}</p>
      </article>
    </section>

    <section class="space-y-3">
      <h3 class="text-lg font-semibold text-slate-900">Daftar Tagihan Purchase Order</h3>
      <AppTable
        :rows="payableTableRows"
        :columns="[
          { key: 'surat_tagihan', label: 'No Tagihan' },
          { key: 'nama_principal', label: 'Principal' },
          { key: 'total_tagihan_label', label: 'Total Tagihan' },
          { key: 'jumlah_faktur_label', label: 'Jumlah Faktur' },
          { key: 'status_bayar_label', label: 'Status Bayar' },
          { key: 'jatuh_tempo', label: 'Jatuh Tempo' }
        ]"
        :loading="loading.payables"
        :clickable-rows="true"
        empty-message="Belum ada tagihan purchase."
        @row-click="openPayable"
      />
    </section>

    <AppModal
      :open="payableModalOpen"
      :title="selectedPayable?.surat_tagihan || 'Ringkasan Tagihan'"
      :description="selectedPayable ? `Tagihan principal ${selectedPayable.nama_principal || '-'} dengan ${selectedPayable.jumlah_faktur || 0} faktur.` : 'Detail tagihan purchase.'"
      size="6xl"
      @close="closePayableModal"
    >
      <div v-if="!selectedPayable" class="rounded-2xl border border-dashed border-slate-200 px-4 py-6 text-sm text-slate-500">
        Detail tagihan belum tersedia.
      </div>

      <div v-else class="space-y-5">
        <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <div v-for="meta in selectedPayableMeta" :key="meta.label" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">{{ meta.label }}</p>
            <div class="mt-2 text-sm font-semibold text-slate-900">
              <span v-if="meta.value && typeof meta.value === 'object'" :class="meta.value.className">{{ meta.value.text }}</span>
              <span v-else>{{ meta.value }}</span>
            </div>
          </div>
        </div>

        <div class="rounded-2xl border border-slate-200 px-4 py-4">
          <div class="mb-3 flex items-center justify-between gap-3">
            <h4 class="text-sm font-semibold text-slate-900">Detail Tagihan Purchase Order</h4>
            <span
              :class="[
                'rounded-full px-3 py-1 text-xs font-semibold',
                canSubmitPayment ? 'bg-amber-100 text-amber-700' : 'bg-emerald-100 text-emerald-700'
              ]"
            >
              {{ canSubmitPayment ? 'Belum Lunas' : 'Sudah Lunas' }}
            </span>
          </div>
          <AppTable
            :rows="payableDetailTableRows"
            :columns="[
              { key: 'no_transaksi', label: 'No Transaksi' },
              { key: 'kode_order', label: 'Kode Order' },
              { key: 'subtotal_label', label: 'Subtotal' },
              { key: 'jatuh_tempo', label: 'Jatuh Tempo' },
              { key: 'status_bayar_label', label: 'Status Bayar' }
            ]"
            :loading="loading.payableDetail"
            empty-message="Belum ada detail tagihan yang dipilih."
          />
        </div>

        <div class="rounded-2xl border border-slate-200 px-4 py-4">
          <div class="mb-3">
            <h4 class="text-sm font-semibold text-slate-900">Histori Pembayaran</h4>
            <p class="mt-1 text-xs text-slate-500">Status pembayaran dan catatan pelunasan tagihan ini.</p>
          </div>
          <AppTable
            :rows="paymentHistoryRows"
            :columns="[
              { key: 'tanggal_bayar', label: 'Tanggal Bayar' },
              { key: 'nominal_label', label: 'Nominal' },
              { key: 'metode', label: 'Metode' },
              { key: 'status_label', label: 'Status' },
              { key: 'keterangan', label: 'Keterangan' }
            ]"
            :paginated="false"
            empty-message="Belum ada histori pembayaran."
          />
        </div>

        <div class="rounded-2xl border border-slate-200 px-4 py-4">
          <div class="mb-3">
            <h4 class="text-sm font-semibold text-slate-900">Cetak Dokumen Purchase</h4>
            <p class="mt-1 text-xs text-slate-500">Cetak faktur purchase dan riwayat pelunasan dari tagihan yang sedang dipilih.</p>
          </div>
          <div class="flex flex-wrap gap-3">
            <button class="rounded-xl bg-slate-900 px-4 py-3 text-sm font-medium text-white" @click="printPurchaseInvoice">
              Cetak Faktur Purchase
            </button>
            <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700" @click="printPaymentHistory">
              Cetak Riwayat Pelunasan
            </button>
          </div>
        </div>

        <div class="rounded-2xl border border-slate-200 px-4 py-4">
          <div class="mb-3">
            <h4 class="text-sm font-semibold text-slate-900">Input Pembayaran Tagihan</h4>
            <p class="mt-1 text-xs text-slate-500">Pelunasan penuh akan mengunci tagihan dan transaksi sumber, mencatat audit Finance, lalu mengirim jurnal pembayaran.</p>
          </div>

          <div class="grid gap-3 md:grid-cols-3">
            <AppFormField v-model="paymentForm.tanggal_bayar" label="Tanggal Bayar" type="date" />
            <label class="block">
              <span class="mb-1.5 block text-sm font-medium text-slate-700">Metode Pembayaran</span>
              <select v-model="paymentForm.tipe_setoran" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none transition focus:border-brand-400">
                <option value="TRANSFER">Transfer</option>
                <option value="TUNAI">Tunai</option>
                <option value="GIRO">Bilyet Giro</option>
                <option value="LAINNYA">Lainnya</option>
              </select>
            </label>
            <AppFormField v-model="paymentForm.keterangan" label="Keterangan Pembayaran" placeholder="Catatan pembayaran / referensi transfer" />
          </div>
          <div class="mt-3">
            <label class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Bukti Bayar</label>
            <input type="file" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none" @change="onPaymentProofChange" />
            <p class="mt-2 text-xs text-slate-500">{{ paymentProofFile?.name || 'Belum ada file dipilih.' }}</p>
          </div>
          <div class="mt-4 flex flex-wrap gap-3">
            <button
              class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white"
              :disabled="loading.payment || !canSubmitPayment"
              @click="submitPayment"
            >
              {{ loading.payment ? 'Memproses...' : 'Proses Pembayaran' }}
            </button>
            <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700" @click="resetPaymentForm">
              Reset Form
            </button>
          </div>
        </div>
      </div>
    </AppModal>

    <section class="panel p-5 space-y-5">
      <div class="flex flex-col gap-2 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p class="text-xs font-medium uppercase tracking-[0.25em] text-slate-400">Builder Tagihan Purchase Order</p>
          <h3 class="mt-2 text-lg font-semibold text-slate-900">Transaksi Siap Tagihan</h3>
          <p class="mt-1 text-sm text-slate-500">Pilih transaksi yang sudah selesai konfirmasi purchase untuk dibundel menjadi satu tagihan purchase.</p>
        </div>
        <div class="flex flex-wrap gap-3">
          <span class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm font-medium text-slate-600">
            {{ filters.principalId ? 'Kandidat mengikuti principal filter' : 'Semua principal pada filter aktif' }}
          </span>
          <label class="flex flex-col gap-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
            JT dari
            <input v-model="builderFilters.dateFrom" type="date" class="rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm font-normal normal-case tracking-normal text-slate-900 outline-none" />
          </label>
          <label class="flex flex-col gap-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
            JT sampai
            <input v-model="builderFilters.dateTo" type="date" class="rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm font-normal normal-case tracking-normal text-slate-900 outline-none" />
          </label>
          <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700" @click="setBuilderDateRange">
            120 Hari
          </button>
          <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700" @click="clearBuilderDateRange">
            Semua JT
          </button>
          <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white" @click="loadCandidateTransactions">
            Muat Kandidat
          </button>
        </div>
      </div>

      <div class="grid gap-4 md:grid-cols-3">
        <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
          <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Dipilih</p>
          <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedCandidateIds.length }} transaksi</p>
        </article>
        <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
          <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Total Kandidat</p>
          <p class="mt-2 text-sm font-semibold text-slate-900">{{ candidateRows.length }} transaksi</p>
        </article>
        <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
          <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Nominal Dipilih</p>
          <p class="mt-2 text-sm font-semibold text-slate-900">{{ formatCurrency(selectedCandidatesTotal) }}</p>
        </article>
      </div>

      <div class="grid gap-3 md:grid-cols-3">
        <div class="rounded-2xl border border-slate-200 px-4 py-3">
          <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Principal Dipilih</p>
          <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedCandidatePrincipal }}</p>
        </div>
        <div class="rounded-2xl border border-slate-200 px-4 py-3">
          <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Rentang Jatuh Tempo</p>
          <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedDueDateRange }}</p>
        </div>
        <div class="rounded-2xl border border-slate-200 px-4 py-3">
          <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Catatan Builder</p>
          <p class="mt-2 text-sm font-semibold text-slate-900">
            {{ billBuilderMessage }}
          </p>
        </div>
      </div>

      <section class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        Filter tanggal di builder memakai jatuh tempo transaksi. Transaksi yang dipilih akan dikunci per kombinasi Cabang + Perusahaan + Principal.
        Kalau ada transaksi dari kombinasi lain, buat tagihan purchase terpisah agar jurnal dan faktur purchase masuk ke perusahaan yang benar.
      </section>

      <AppTable
        :rows="candidateTableRows"
        :columns="[
          { key: 'selected_label', label: 'Pilih' },
          { key: 'no_transaksi', label: 'No Transaksi' },
          { key: 'kode_order', label: 'Kode Order' },
          { key: 'branch_label', label: 'Cabang' },
          { key: 'company_label', label: 'Perusahaan' },
          { key: 'nama_principal', label: 'Principal' },
          { key: 'subtotal_label', label: 'Subtotal' },
          { key: 'jatuh_tempo', label: 'Jatuh Tempo' }
        ]"
        :loading="loading.candidates"
        :clickable-rows="true"
        empty-message="Belum ada kandidat transaksi untuk tagihan purchase."
        @row-click="toggleCandidate"
      />

      <div class="flex flex-wrap gap-3">
        <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700" @click="selectAllCandidates">
          Pilih Semua
        </button>
        <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700" @click="resetBuilderSelection">
          Bersihkan Pilihan
        </button>
        <button
          class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white"
          :disabled="loading.submit || !canCreateBill"
          @click="submitCreateBill"
        >
          {{ loading.submit ? 'Memproses...' : 'Buat Tagihan Purchase Order' }}
        </button>
        <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700" @click="loadAll">
          Refresh Tagihan
        </button>
      </div>

      <section v-if="selectedCandidateRows.length" class="space-y-3">
        <h4 class="text-sm font-semibold text-slate-900">Detail Transaksi Terpilih</h4>
        <AppTable
          :rows="selectedCandidateRows.map((item) => ({
            ...item,
            row_key: `${item.id_purchase_transaksi}-selected`,
            subtotal_label: formatCurrency(item.subtotal || 0)
          }))"
          :columns="[
            { key: 'no_transaksi', label: 'No Transaksi' },
            { key: 'kode_order', label: 'Kode Order' },
            { key: 'nama_principal', label: 'Principal' },
            { key: 'subtotal_label', label: 'Subtotal' },
            { key: 'jatuh_tempo', label: 'Jatuh Tempo' }
          ]"
          :paginated="false"
          empty-message="Belum ada transaksi yang dipilih."
        />
      </section>
    </section>

    <section class="space-y-3">
      <h3 class="text-lg font-semibold text-slate-900">Transaksi Proses Tagihan</h3>
      <AppTable
        :rows="billingTableRows"
        :columns="[
          { key: 'no_transaksi', label: 'No Transaksi' },
          { key: 'order_kode', label: 'Kode Order' },
          { key: 'principal_nama', label: 'Principal' },
          { key: 'subtotal_label', label: 'Subtotal' },
          { key: 'total_label', label: 'Total' },
          { key: 'status_label', label: 'Status' }
        ]"
        :loading="loading.billing"
        empty-message="Belum ada transaksi di proses tagihan."
      />
    </section>
  </div>
</template>
