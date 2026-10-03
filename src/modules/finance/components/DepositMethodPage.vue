<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  allocateNonCashMutation,
  confirmDepositStage,
  createBankMutation,
  getBankMutations,
  getCompanyBankAccounts,
  getPaymentLphDetail,
  getPaymentLphs,
  importBankMutations,
  saveCashierDeposit
} from '@/api/finance';
import { getBranches, getCompanies, getSales } from '@/api/master';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import {
  getLoginBranchId,
  getLoginCompanyId,
  getLoginSalesId,
  getRowCompanyId,
  hasMultiBusinessScope,
  hasSupervisorSalesScope,
  isSuperUser,
  scopeSalesRowsByLogin,
  shouldLockToLoginSales
} from '@/utils/accessScope';
import { getBranchOptionsForCompany, getCompanyOptionsForScope } from '@/utils/filterScope';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const props = defineProps({
  method: {
    type: String,
    required: true,
    validator: (value) => ['cash', 'noncash'].includes(value)
  }
});

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const numberFormatter = new Intl.NumberFormat('id-ID', { maximumFractionDigits: 2 });

const filters = reactive({
  id_perusahaan: '',
  id_cabang: '',
  id_sales: '',
  status: 'AKTIF',
  search: '',
  id_lph: ''
});
const form = reactive({
  officerName: ''
});
const importForm = reactive({
  id_perusahaan: '',
  id_rekening_perusahaan: '',
  fileName: '',
  id_mutasi: '',
  customer_scope_key: '',
  allocation_mode: 'FIFO',
  allocations: [],
  surplus_disposition: 'ADVANCE',
  catatan: ''
});
// Manual transfer/BG evidence becomes a controlled incoming bank movement.
// It must still be allocated to a Rekap source before any deposit can move
// beyond the waiting stage; this is intentionally not a direct finalisation.
const manualMutationForm = reactive({
  instrument_type: 'TRANSFER_MANUAL',
  tanggal_mutasi: new Date().toISOString().slice(0, 10),
  nomor_referensi: '',
  nominal_mutasi: '',
  catatan: ''
});

const companyRows = ref([]);
const branchRows = ref([]);
const salesRows = ref([]);
const lphRows = ref([]);
const bankAccountRows = ref([]);
const importedMutationRows = ref([]);
const importPreviewRows = ref([]);
const detail = ref(createEmptyDetail());
const proofByDepositId = reactive({});
const feedback = ref('');
const errorMessage = ref('');
const importError = ref('');
const importFeedback = ref('');
const importOpen = ref(false);
const mutationEntryMode = ref('IMPORT');
const loading = reactive({
  masters: false,
  lphs: false,
  detail: false,
  record: false,
  importParse: false,
  importSave: false,
  importMutations: false,
  manualMutation: false,
  bindMutation: false
});

const isCash = computed(() => props.method === 'cash');
const methodCode = computed(() => (isCash.value ? 1 : 2));
const methodTitle = computed(() => (isCash.value ? 'Setoran Tunai' : 'Setoran Non Tunai'));
const methodDescription = computed(() => (
  isCash.value
    ? 'Terima kas dari hasil Rekap Pembayaran, tanpa mengubah nominal atau metode yang dicatat Mobile Sales.'
    : 'Import mutasi bank langsung dan cocokkan dengan setoran dari Rekap Pembayaran, tanpa mengubah nominal atau metode yang dicatat Mobile Sales.'
));
const fallbackBranchId = computed(() => getLoginBranchId(auth.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(auth.user));
const fallbackSalesId = computed(() => getLoginSalesId(auth.user));
const canAccessAllBranches = computed(() => isSuperUser(auth));
const shouldLockBusinessScope = computed(() => (
  !canAccessAllBranches.value && !hasSupervisorSalesScope(auth.user) && !hasMultiBusinessScope(auth.user)
));
const shouldLockSalesScope = computed(() => shouldLockToLoginSales(auth));

const companyOptions = computed(() => getCompanyOptionsForScope(companyRows.value, auth, true));
const branchOptions = computed(() => (
  getBranchOptionsForCompany(branchRows.value, auth, filters.id_perusahaan, true, companyRows.value)
));
const salesOptions = computed(() => [
  { value: '', label: 'Semua sales' },
  ...scopeSalesRowsByLogin(salesRows.value, auth)
    .filter((row) => !filters.id_cabang || String(row.id_cabang || row.cabang_id || '') === String(filters.id_cabang))
    .filter((row) => salesMatchesCompany(row, filters.id_perusahaan))
    .map((row) => ({
      value: String(row.id_sales || row.sales_id || row.id || ''),
      label: `${row.kode_sales || '-'} - ${row.nama_sales || row.nama || 'Sales'}${row.nama_cabang ? ` | ${row.nama_cabang}` : ''}`
    }))
    .filter((row) => row.value)
]);
const lphOptions = computed(() => [
  { value: '', label: 'Pilih LPH untuk melihat setoran' },
  ...lphRows.value.map((row) => ({
    value: String(row.id),
    label: `${row.kode_lph || `LPH-${row.id}`} · ${row.nama_sales || 'Sales'} · ${formatDate(row.tanggal_lph)} · ${formatNumber(row.jumlah_faktur)} faktur`
  }))
]);
const selectedLph = computed(() => (
  lphRows.value.find((row) => String(row.id) === String(filters.id_lph)) || detail.value.lph || null
));
const lphIsActive = computed(() => (
  String(detail.value.lph?.status_dokumen || selectedLph.value?.status_dokumen || '').toUpperCase() === 'AKTIF'
));
const invoices = computed(() => Array.isArray(detail.value.invoices) ? detail.value.invoices : []);
const payments = computed(() => Array.isArray(detail.value.payments) ? detail.value.payments : []);
const summary = computed(() => detail.value.summary || {});

const bankAccountOptions = computed(() => bankAccountRows.value
  .filter((row) => !importForm.id_perusahaan || String(row.id_perusahaan || '') === String(importForm.id_perusahaan))
  .map((row) => ({
    value: String(row.id_rekening_perusahaan || row.id || ''),
    label: `${row.nama_bank || 'Bank'} - ${row.nomor_rekening || '-'} (${row.nama_pemilik || '-'})`
  }))
  .filter((row) => row.value));

const unmatchedIncomingMutations = computed(() => importedMutationRows.value
  .filter((row) => Number(row.tipe || 0) === 1)
  // A partly allocated CR must remain selectable until its `sisa` reaches
  // zero.  The allocation API owns the exact status transition; the legacy
  // single `id_setoran` field is no longer a valid availability signal.
  .filter((row) => [1, '1', 'PARTIAL', 'MENUNGGU_ALOKASI'].includes(row.status_mutasi))
  .filter((row) => !importForm.id_rekening_perusahaan || String(row.id_rekening_perusahaan || '') === String(importForm.id_rekening_perusahaan))
  .filter((row) => Number(row.sisa ?? row.nominal_mutasi ?? 0) > 0));

const mutationOptions = computed(() => unmatchedIncomingMutations.value.map((row) => ({
  value: String(row.id_mutasi || row.id || ''),
  label: `${row.kode_mutasi || `Mutasi #${row.id_mutasi || row.id}`} · ${formatDate(row.tanggal_mutasi)} · ${formatCurrency(row.sisa ?? row.nominal_mutasi)}`
})).filter((row) => row.value));

const selectedImportedMutation = computed(() => (
  unmatchedIncomingMutations.value.find((row) => String(row.id_mutasi || row.id || '') === String(importForm.id_mutasi || '')) || null
));

const selectedMutationAmount = computed(() => Number(
  selectedImportedMutation.value?.sisa
  ?? selectedImportedMutation.value?.nominal_mutasi
  ?? 0
));

const methodPayments = computed(() => payments.value
  .filter((payment) => getPaymentMethod(payment) === methodCode.value)
  .map((payment) => buildPaymentRow(payment)));

const depositRows = computed(() => methodPayments.value.flatMap((payment) => payment.depositRows));
const pendingDepositRows = computed(() => depositRows.value.filter((row) => Number(row.status_setoran || 0) === 1));
const acceptedDepositRows = computed(() => depositRows.value.filter((row) => Number(row.status_setoran || 0) >= 2));
const invalidPaymentRows = computed(() => methodPayments.value.filter((row) => !row.hasSource || !row.amountMatches || !row.methodMatches));
const pendingRekapRows = computed(() => methodPayments.value.filter((row) => !row.hasSource));
const actionLabel = computed(() => (
  isCash.value ? 'Terima Tunai & Siap Cocokkan' : 'Import & Cocokkan Mutasi Bank'
));
const actionDisabled = computed(() => (
  loading.record
  || !lphIsActive.value
  || !pendingDepositRows.value.length
  || invalidPaymentRows.value.length > 0
));

function invoiceForPayment(payment = {}) {
  return invoices.value.find((invoice) => (
    String(invoice.id_faktur || '') && String(invoice.id_faktur) === String(payment.id_faktur || '')
  )) || invoices.value.find((invoice) => (
    String(invoice.id_sales_order || '') && String(invoice.id_sales_order) === String(payment.id_sales_order || '')
  )) || {};
}

function allocationCustomerKey(row = {}) {
  return String(
    row.id_customer
    ?? row.customer_id
    ?? row.kode_customer
    ?? row.nama_customer
    ?? ''
  );
}

function allocationCustomerLabel(row = {}) {
  const code = row.kode_customer ? `${row.kode_customer} - ` : '';
  return `${code}${row.nama_customer || row.customer_name || 'Customer belum diketahui'}`;
}

// Allocation is intentionally based on an already-created Rekap deposit, not
// on an arbitrary invoice amount. Every selected source must be allocated in
// full: Finance may choose several source rows, but may never split/change a
// Mobile Sales claim from this screen. This keeps the bank evidence, Rekap,
// and the original Mobile Sales nominal auditable.
const allNonCashAllocationCandidates = computed(() => {
  const rowsByDepositId = new Map();
  methodPayments.value
    .filter((payment) => payment.expectedMethod === 2)
    .filter((payment) => payment.hasSource && payment.methodMatches && payment.amountMatches)
    .forEach((payment) => {
      const invoice = invoiceForPayment(payment);
      payment.depositRows
        .filter((deposit) => Number(deposit.status_setoran || 0) === 1)
        .filter((deposit) => deposit.id_setoran)
        .forEach((deposit) => {
          const id = String(deposit.id_setoran);
          if (rowsByDepositId.has(id)) return;
          const nominalTersedia = Math.max(0, Number(
            deposit.sisa_alokasi
            ?? deposit.nominal_belum_dialokasikan
            ?? deposit.sisa_setoran
            ?? getDepositAmount(deposit)
          ));
          if (!nominalTersedia) return;
          const candidate = {
            id_setoran: deposit.id_setoran,
            id_setoran_customer: payment.id_setoran_customer,
            id_faktur: payment.id_faktur || invoice.id_faktur || null,
            no_faktur: payment.no_faktur || invoice.no_faktur || '',
            id_sales_order: payment.id_sales_order || invoice.id_sales_order || null,
            id_customer: payment.id_customer ?? invoice.id_customer ?? null,
            kode_customer: payment.kode_customer || invoice.kode_customer || '',
            nama_customer: payment.nama_customer || invoice.nama_customer || '',
            customer_key: allocationCustomerKey({ ...invoice, ...payment }),
            customer_label: allocationCustomerLabel({ ...invoice, ...payment }),
            nominal_tersedia: nominalTersedia,
            tanggal_jatuh_tempo: invoice.tanggal_jatuh_tempo || null
          };
          rowsByDepositId.set(id, candidate);
        });
    });

  return [...rowsByDepositId.values()]
    .filter((row) => row.customer_key)
    .sort((left, right) => {
      const leftDate = String(left.tanggal_jatuh_tempo || '9999-12-31');
      const rightDate = String(right.tanggal_jatuh_tempo || '9999-12-31');
      return leftDate.localeCompare(rightDate) || String(left.no_faktur).localeCompare(String(right.no_faktur));
    });
});

const allocationCustomerOptions = computed(() => {
  const rowsByCustomer = new Map();
  allNonCashAllocationCandidates.value.forEach((candidate) => {
    if (!rowsByCustomer.has(candidate.customer_key)) {
      rowsByCustomer.set(candidate.customer_key, {
        value: candidate.customer_key,
        label: candidate.customer_label,
        id_customer: candidate.id_customer || null
      });
    }
  });
  return [...rowsByCustomer.values()];
});

const selectedAllocationCustomer = computed(() => (
  allocationCustomerOptions.value.find((item) => String(item.value) === String(importForm.customer_scope_key || '')) || null
));

const allocationCandidates = computed(() => allNonCashAllocationCandidates.value
  .filter((candidate) => !importForm.customer_scope_key || candidate.customer_key === importForm.customer_scope_key));

const selectedAllocationRows = computed(() => {
  const candidateById = new Map(allocationCandidates.value.map((candidate) => [String(candidate.id_setoran), candidate]));
  return importForm.allocations
    .map((allocation) => ({
      ...allocation,
      candidate: candidateById.get(String(allocation.id_setoran)) || null,
      nominal_alokasi: Number(allocation.nominal_alokasi || 0)
    }))
    .filter((allocation) => allocation.candidate);
});

const allocatedMutationAmount = computed(() => selectedAllocationRows.value
  .reduce((total, allocation) => total + Math.max(0, Number(allocation.nominal_alokasi || 0)), 0));
const mutationRemainder = computed(() => Math.max(0, selectedMutationAmount.value - allocatedMutationAmount.value));
const allocationExceedsMutation = computed(() => allocatedMutationAmount.value > selectedMutationAmount.value + 0.5);
const allocationHasInvalidAmount = computed(() => selectedAllocationRows.value.some((allocation) => (
  Number(allocation.nominal_alokasi || 0) <= 0
  || Math.abs(
    Number(allocation.nominal_alokasi || 0) - Number(allocation.candidate?.nominal_tersedia || 0)
  ) > 0.5
)));
const hasCustomerAdvance = computed(() => mutationRemainder.value > 0.5 && importForm.surplus_disposition === 'ADVANCE');
const canAllocateImportedMutation = computed(() => Boolean(
  filters.id_lph
  && selectedImportedMutation.value
  && selectedAllocationCustomer.value
  && String(form.officerName || '').trim()
  && selectedAllocationRows.value.length
  && allocatedMutationAmount.value > 0
  && !allocationExceedsMutation.value
  && !allocationHasInvalidAmount.value
));
const summaryCards = computed(() => [
  { label: 'Pembayaran Mobile', value: formatCurrency(methodPayments.value.reduce((sum, row) => sum + row.mobileAmount, 0)), tone: 'violet' },
  { label: 'Setoran Tercatat', value: formatCurrency(methodPayments.value.reduce((sum, row) => sum + row.depositAmount, 0)), tone: isCash.value ? 'emerald' : 'amber' },
  { label: 'Menunggu Dicatat', value: formatNumber(pendingDepositRows.value.length), tone: 'rose' },
  { label: 'Siap Cocokkan', value: formatNumber(acceptedDepositRows.value.length), tone: 'sky' }
]);

function createEmptyDetail() {
  return { lph: null, invoices: [], payments: [], summary: {} };
}

function formatNumber(value) {
  return numberFormatter.format(Number(value || 0));
}

function formatCurrency(value) {
  return `Rp ${numberFormatter.format(Number(value || 0))}`;
}

function formatDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10);
  return date.toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' });
}

function parseCsvLine(line) {
  const values = [];
  let current = '';
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    const next = line[index + 1];
    if (character === '"' && quoted && next === '"') {
      current += '"';
      index += 1;
    } else if (character === '"') {
      quoted = !quoted;
    } else if (character === ',' && !quoted) {
      values.push(current.trim());
      current = '';
    } else {
      current += character;
    }
  }
  values.push(current.trim());
  return values;
}

function parseBankCurrency(value) {
  const text = String(value || '').replace(/"/g, '').trim();
  const tipe = /\bDB\b/i.test(text) ? 'db' : 'cr';
  const jumlah = Number(text.replace(/\b(CR|DB)\b/gi, '').replace(/,/g, '').trim() || 0);
  return { tipe, jumlah };
}

function extractCsvPeriodEnd(lines) {
  const periodLine = lines.find((line) => line.toLowerCase().includes('periode'));
  const match = periodLine?.match(/(\d{2}\/\d{2}\/\d{4})\s*-\s*(\d{2}\/\d{2}\/\d{4})/);
  return match?.[2] || '';
}

function normalizeBankDate(value, periodEnd = '') {
  const text = String(value || '').trim();
  if (/^\d{2}\/\d{2}\/\d{4}$/.test(text)) return text;
  if (text.toUpperCase() === 'PEND' && periodEnd) return periodEnd;
  return '';
}

function parseBankCsv(text) {
  const lines = String(text || '').split(/\r?\n/).filter((line) => line.trim());
  const periodEnd = extractCsvPeriodEnd(lines);
  const headerIndex = lines.findIndex((line) => (
    line.toLowerCase().startsWith('tanggal transaksi,keterangan,cabang,jumlah,saldo')
  ));
  if (headerIndex < 0) throw new Error('Header CSV mutasi bank tidak ditemukan. Gunakan file CSV mutasi dari internet banking.');

  return lines.slice(headerIndex + 1)
    .map(parseCsvLine)
    .filter((columns) => columns.length >= 5 && !String(columns[0] || '').toLowerCase().includes('saldo'))
    .map((columns) => {
      const amount = parseBankCurrency(columns[3]);
      return {
        tanggal: normalizeBankDate(columns[0], periodEnd),
        keterangan: columns[1],
        cabang: columns[2],
        jumlah: amount.jumlah,
        saldo: Number(String(columns[4] || '').replace(/,/g, '').replace(/"/g, '') || 0),
        tipe: amount.tipe
      };
    })
    .filter((item) => item.tanggal && item.jumlah > 0);
}

function isoDateFromBankDate(value) {
  const match = String(value || '').match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  return match ? `${match[3]}-${match[2]}-${match[1]}` : '';
}

function importDateRange() {
  const values = importPreviewRows.value
    .map((row) => isoDateFromBankDate(row.tanggal))
    .filter(Boolean)
    .sort();
  return {
    periode_awal: values[0] || undefined,
    periode_akhir: values[values.length - 1] || undefined
  };
}

function paymentMethodLabel(value) {
  return Number(value) === 2 ? 'Non Tunai / Transfer' : 'Tunai';
}

function lphStatusLabel(value) {
  const status = String(value || '').trim().toUpperCase();
  if (status === 'AKTIF') return 'Aktif di sales';
  if (status === 'MENUNGGU_PENERIMAAN') return 'Menunggu diterima sales';
  if (status === 'DIKEMBALIKAN') return 'Dikembalikan sales';
  return status || '-';
}

function resolveDepositStage(value) {
  const stage = Number(value || 0);
  if (stage >= 3) return 'Final';
  if (stage === 2) return 'Tercatat / siap cocokkan';
  if (stage === 1) return 'Menunggu pencatatan';
  return 'Belum direkap';
}

function resolveStatusClass(stage) {
  if (Number(stage || 0) >= 3) return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-200';
  if (Number(stage || 0) === 2) return 'bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-200';
  if (Number(stage || 0) === 1) return 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-200';
  return 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300';
}

function getPaymentMethod(payment = {}) {
  const value = payment.tipe_pembayaran_sales
    ?? payment.tipe_setoran
    ?? payment.metode
    ?? payment.metode_pembayaran;
  if (typeof value === 'string') {
    const normalized = value.trim().toUpperCase();
    if (normalized.includes('NON') || normalized.includes('TRANSFER')) return 2;
    if (normalized.includes('TUNAI') || normalized.includes('CASH')) return 1;
  }
  return Number(value || 1) === 2 ? 2 : 1;
}

function getDepositMethod(row = {}) {
  return getPaymentMethod({
    tipe_pembayaran_sales: row.tipe_setoran ?? row.draft_tipe_setor ?? row.metode
  });
}

function getDepositAmount(row = {}) {
  return Number(
    row.nominal_setoran
    ?? row.draft_jumlah_setor
    ?? row.jumlah_setoran
    ?? row.nominal
    ?? 0
  );
}

function getDepositRows(payment = {}) {
  const candidates = [
    ...(Array.isArray(payment.deposit_rows) ? payment.deposit_rows : []),
    ...(Array.isArray(payment.setoran_rows) ? payment.setoran_rows : []),
    ...(payment.deposit_row && typeof payment.deposit_row === 'object' ? [payment.deposit_row] : [])
  ];
  const rowsById = new Map();
  candidates.forEach((item, index) => {
    if (!item || typeof item !== 'object') return;
    const id = item.id_setoran ?? item.id ?? `${payment.id_setoran_customer || payment.id || 'deposit'}-${index}`;
    if (rowsById.has(String(id))) return;
    rowsById.set(String(id), {
      ...item,
      id_setoran: item.id_setoran ?? item.id ?? null
    });
  });
  return [...rowsById.values()];
}

function buildPaymentRow(payment) {
  const expectedMethod = getPaymentMethod(payment);
  const allRows = getDepositRows(payment);
  const sourceRows = allRows.filter((row) => getDepositMethod(row) === expectedMethod);
  const otherMethodRows = allRows.filter((row) => getDepositMethod(row) !== expectedMethod);
  const depositAmount = sourceRows.reduce((sum, row) => sum + getDepositAmount(row), 0);
  const mobileAmount = Number(payment.jumlah_bayar_sales ?? payment.total_bayar ?? payment.nominal ?? 0);
  const methodMatches = otherMethodRows.length === 0;
  const amountMatches = sourceRows.length > 0 && Math.abs(mobileAmount - depositAmount) <= 0.5;

  return {
    ...payment,
    key: String(payment.id_setoran_customer || payment.id || `${payment.id_sales_order || ''}-${payment.tanggal_input || ''}`),
    mobileAmount,
    expectedMethod,
    depositRows: sourceRows,
    allDepositRows: allRows,
    depositAmount,
    hasSource: sourceRows.length > 0,
    methodMatches,
    amountMatches,
    difference: mobileAmount - depositAmount
  };
}

function selectedSalesRow() {
  return salesRows.value.find((row) => (
    [row.id_sales, row.sales_id, row.id]
      .filter((value) => value !== null && value !== undefined && value !== '')
      .map(String)
      .includes(String(filters.id_sales || ''))
  )) || null;
}

function salesMatchesCompany(row, companyId) {
  if (!companyId) return true;
  const directCompanyId = getRowCompanyId(row);
  // Older sales records often do not store company directly. The server LPH
  // query applies the real company scope, so client-side filtering must not
  // hide an otherwise valid sales option.
  return !directCompanyId || String(directCompanyId) === String(companyId);
}

function buildLphParams() {
  const sales = selectedSalesRow();
  return {
    id_perusahaan: filters.id_perusahaan || undefined,
    id_cabang: filters.id_cabang || undefined,
    id_sales: sales?.id_sales || sales?.sales_id || filters.id_sales || undefined,
    sales_user_id: sales?.id_user || sales?.user_id || undefined,
    status: filters.status || undefined,
    search: filters.search.trim() || undefined,
    limit: 500
  };
}

function clearDetail() {
  detail.value = createEmptyDetail();
  Object.keys(proofByDepositId).forEach((key) => delete proofByDepositId[key]);
}

async function loadMasters() {
  loading.masters = true;
  try {
    const [companyResponse, branchResponse, salesResponse, bankAccountResponse] = await Promise.all([
      getCompanies(),
      getBranches(),
      getSales(),
      getCompanyBankAccounts()
    ]);
    companyRows.value = normalizeList(unwrapResponse(companyResponse));
    branchRows.value = normalizeList(unwrapResponse(branchResponse));
    salesRows.value = normalizeList(unwrapResponse(salesResponse));
    bankAccountRows.value = normalizeList(unwrapResponse(bankAccountResponse));
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Pilihan perusahaan, cabang, sales, atau rekening belum dapat dimuat.');
  } finally {
    loading.masters = false;
  }
}

async function loadLphs({ preserveSelection = true } = {}) {
  loading.lphs = true;
  feedback.value = '';
  errorMessage.value = '';
  try {
    const response = await getPaymentLphs(buildLphParams());
    lphRows.value = normalizeList(unwrapResponse(response));
    const selectedExists = lphRows.value.some((row) => String(row.id) === String(filters.id_lph));
    if (!preserveSelection && !selectedExists) {
      filters.id_lph = '';
      clearDetail();
    }
    if (filters.id_lph && selectedExists) {
      await loadLphDetail();
    }
  } catch (error) {
    lphRows.value = [];
    clearDetail();
    errorMessage.value = normalizeError(error, 'Daftar LPH belum dapat dimuat.');
  } finally {
    loading.lphs = false;
  }
}

async function loadLphDetail() {
  if (!filters.id_lph) {
    clearDetail();
    return;
  }

  loading.detail = true;
  errorMessage.value = '';
  try {
    const response = await getPaymentLphDetail({ id_lph: filters.id_lph });
    const payload = unwrapResponse(response) || {};
    detail.value = {
      lph: payload.lph || null,
      invoices: Array.isArray(payload.invoices) ? payload.invoices : [],
      payments: Array.isArray(payload.payments) ? payload.payments : [],
      summary: payload.summary || {}
    };
    Object.keys(proofByDepositId).forEach((key) => delete proofByDepositId[key]);
    depositRows.value.forEach((row) => {
      if (row.id_setoran) proofByDepositId[String(row.id_setoran)] = row.bukti_transfer || row.kode_mutasi || '';
    });
  } catch (error) {
    clearDetail();
    errorMessage.value = normalizeError(error, 'Detail pembayaran LPH belum dapat dimuat.');
  } finally {
    loading.detail = false;
  }
}

async function chooseLph(value) {
  filters.id_lph = String(value || '');
  await loadLphDetail();
}

function onCompanyChanged(value) {
  filters.id_perusahaan = String(value || '');
  if (!branchOptions.value.some((option) => String(option.value) === String(filters.id_cabang))) {
    filters.id_cabang = '';
  }
  filters.id_sales = '';
  filters.id_lph = '';
  clearDetail();
}

function onBranchChanged(value) {
  filters.id_cabang = String(value || '');
  if (!salesOptions.value.some((option) => String(option.value) === String(filters.id_sales))) {
    filters.id_sales = '';
  }
  filters.id_lph = '';
  clearDetail();
}

function onSalesChanged(value) {
  filters.id_sales = String(value || '');
  filters.id_lph = '';
  clearDetail();
}

function openRecap() {
  router.push({
    name: 'finance-recap',
    query: {
      id_lph: filters.id_lph || undefined,
      id_sales: detail.value.lph?.id_sales || selectedLph.value?.id_sales || filters.id_sales || undefined
    }
  });
}

function openPaymentTagihan() {
  router.push({ name: 'finance-payments', query: { id_lph: filters.id_lph || undefined } });
}

function resetMutationSelection() {
  importForm.id_mutasi = '';
  importForm.customer_scope_key = '';
  importForm.allocation_mode = 'FIFO';
  importForm.allocations = [];
  importForm.surplus_disposition = 'ADVANCE';
  importForm.catatan = '';
}

function resetManualMutationForm() {
  manualMutationForm.instrument_type = 'TRANSFER_MANUAL';
  manualMutationForm.tanggal_mutasi = new Date().toISOString().slice(0, 10);
  manualMutationForm.nomor_referensi = '';
  manualMutationForm.nominal_mutasi = '';
  manualMutationForm.catatan = '';
}

function onImportCompanyChanged(value) {
  importForm.id_perusahaan = String(value || '');
  importForm.id_rekening_perusahaan = '';
  importedMutationRows.value = [];
  resetMutationSelection();
}

async function onImportAccountChanged(value) {
  importForm.id_rekening_perusahaan = String(value || '');
  resetMutationSelection();
  importError.value = '';
  if (importForm.id_rekening_perusahaan) {
    await loadImportedMutations();
  } else {
    importedMutationRows.value = [];
  }
}

function onImportedMutationChanged(value) {
  importForm.id_mutasi = String(value || '');
  importForm.allocations = [];
  importForm.catatan = '';

  if (!importForm.id_mutasi) {
    importForm.customer_scope_key = '';
    return;
  }

  // A combined LPH may contain more than one customer.  Do not silently
  // assign a surplus to whichever customer happens to be first; only infer it
  // when there is exactly one eligible customer.
  if (allocationCustomerOptions.value.length === 1) {
    importForm.customer_scope_key = allocationCustomerOptions.value[0].value;
    applyFifoAllocation();
  } else if (!allocationCustomerOptions.value.some((item) => item.value === importForm.customer_scope_key)) {
    importForm.customer_scope_key = '';
  } else if (importForm.allocation_mode === 'FIFO') {
    applyFifoAllocation();
  }
}

function onAllocationCustomerChanged(value) {
  importForm.customer_scope_key = String(value || '');
  importForm.allocations = [];
  if (importForm.allocation_mode === 'FIFO') applyFifoAllocation();
}

function onAllocationModeChanged(value) {
  importForm.allocation_mode = value === 'MANUAL' ? 'MANUAL' : 'FIFO';
  if (importForm.allocation_mode === 'FIFO') applyFifoAllocation();
}

function allocationEntryFor(candidate) {
  return importForm.allocations.find((item) => String(item.id_setoran) === String(candidate.id_setoran));
}

function isAllocationSelected(candidate) {
  return Boolean(allocationEntryFor(candidate));
}

function applyFifoAllocation() {
  if (!selectedImportedMutation.value || !importForm.customer_scope_key) {
    importForm.allocations = [];
    return;
  }

  let remaining = selectedMutationAmount.value;
  const rows = [];
  for (const candidate of allocationCandidates.value) {
    if (remaining <= 0.5) break;
    const nominal = Number(candidate.nominal_tersedia || 0);
    // FIFO is intentionally all-or-nothing per Rekap source. Do not create a
    // Finance-side partial claim merely because the bank mutation is smaller.
    // That case must first be recorded as the actual partial payment in Mobile
    // Sales, then appear here as a matching Rekap source.
    if (nominal > remaining + 0.5) break;
    if (nominal <= 0) continue;
    rows.push({ id_setoran: candidate.id_setoran, nominal_alokasi: nominal });
    remaining -= nominal;
  }
  importForm.allocations = rows;
}

function canSelectFullCandidate(candidate) {
  if (isAllocationSelected(candidate)) return true;
  return Number(candidate.nominal_tersedia || 0) <= mutationRemainder.value + 0.5;
}

function toggleAllocationCandidate(candidate, isSelected) {
  const existing = allocationEntryFor(candidate);
  if (!isSelected) {
    importForm.allocations = importForm.allocations.filter((item) => String(item.id_setoran) !== String(candidate.id_setoran));
    return;
  }
  if (existing) return;
  if (!canSelectFullCandidate(candidate)) {
    importError.value = 'Sisa mutasi tidak cukup untuk memilih setoran ini secara penuh. Catat pembayaran parsial terlebih dahulu dari Mobile Sales agar Rekap membuat sumber setoran dengan nominal yang sama.';
    return;
  }
  importError.value = '';
  importForm.allocations.push({
    id_setoran: candidate.id_setoran,
    nominal_alokasi: Number(candidate.nominal_tersedia || 0)
  });
}

async function loadImportedMutations() {
  if (!importForm.id_perusahaan || !importForm.id_rekening_perusahaan) {
    importedMutationRows.value = [];
    return;
  }
  loading.importMutations = true;
  try {
    const response = await getBankMutations({
      id_perusahaan: importForm.id_perusahaan,
      id_rekening_perusahaan: importForm.id_rekening_perusahaan,
      tipe: 1,
      ...importDateRange()
    });
    importedMutationRows.value = normalizeList(unwrapResponse(response));
    if (!unmatchedIncomingMutations.value.some((row) => String(row.id_mutasi || row.id || '') === String(importForm.id_mutasi || ''))) {
      resetMutationSelection();
    }
  } catch (error) {
    importedMutationRows.value = [];
    importError.value = normalizeError(error, 'Daftar mutasi CR yang belum dipakai belum dapat dimuat.');
  } finally {
    loading.importMutations = false;
  }
}

function openDirectMutationImport() {
  if (!filters.id_lph) {
    errorMessage.value = 'Pilih LPH terlebih dahulu. Mutasi hanya boleh dicocokkan dengan faktur sumber pada satu LPH.';
    return;
  }
  if (!lphIsActive.value) {
    errorMessage.value = 'LPH belum aktif di sales, sehingga mutasi belum dapat dicatat.';
    return;
  }
  importForm.id_perusahaan = String(filters.id_perusahaan || fallbackCompanyId.value || '');
  importForm.id_rekening_perusahaan = '';
  importForm.fileName = '';
  importPreviewRows.value = [];
  importedMutationRows.value = [];
  resetMutationSelection();
  resetManualMutationForm();
  mutationEntryMode.value = 'IMPORT';
  importError.value = '';
  importFeedback.value = '';
  importOpen.value = true;
}

function openManualNonCashEntry() {
  if (!filters.id_lph) {
    errorMessage.value = 'Pilih LPH terlebih dahulu. Pencatatan manual tetap harus dialokasikan ke setoran sumber pada LPH.';
    return;
  }
  if (!lphIsActive.value) {
    errorMessage.value = 'LPH belum aktif di sales, sehingga bukti non tunai belum dapat dicatat.';
    return;
  }
  importForm.id_perusahaan = String(filters.id_perusahaan || fallbackCompanyId.value || '');
  importForm.id_rekening_perusahaan = '';
  importPreviewRows.value = [];
  importedMutationRows.value = [];
  resetMutationSelection();
  resetManualMutationForm();
  mutationEntryMode.value = 'MANUAL';
  importError.value = '';
  importFeedback.value = '';
  importOpen.value = true;
}

async function submitManualNonCashMutation() {
  if (!importForm.id_perusahaan || !importForm.id_rekening_perusahaan) {
    importError.value = 'Pilih perusahaan dan rekening tujuan terlebih dahulu.';
    return;
  }
  const nominal = Number(manualMutationForm.nominal_mutasi || 0);
  const reference = String(manualMutationForm.nomor_referensi || '').trim();
  const instrument = String(manualMutationForm.instrument_type || '').trim();
  if (!manualMutationForm.tanggal_mutasi || !reference || !instrument || nominal <= 0) {
    importError.value = 'Isi tanggal, jenis instrumen, nomor referensi, dan nominal lebih dari Rp 0.';
    return;
  }
  loading.manualMutation = true;
  importError.value = '';
  importFeedback.value = '';
  try {
    const note = String(manualMutationForm.catatan || '').trim();
    const response = await createBankMutation({
      id_perusahaan: Number(importForm.id_perusahaan),
      id_rekening_perusahaan: Number(importForm.id_rekening_perusahaan),
      tanggal_mutasi: manualMutationForm.tanggal_mutasi,
      nominal_mutasi: nominal,
      tipe: 1,
      // The existing controlled Mutasi API persists the actor, company
      // account, timestamp, code, and description. Keep the instrument
      // visible in both the code and immutable audit text.
      kode_mutasi: reference,
      keterangan: `[MANUAL:${instrument}] ${note || `Referensi ${reference}`}`
    });
    const payload = unwrapResponse(response) || {};
    const createdId = payload?.data?.id_mutasi ?? payload?.id_mutasi;
    importFeedback.value = payload.message || 'Bukti non tunai manual tersimpan sebagai mutasi CR dan menunggu alokasi.';
    await loadImportedMutations();
    if (createdId) {
      onImportedMutationChanged(String(createdId));
    }
    // Keep the manual entry visible after save. The selected CR below still
    // needs an audited allocation before it can advance any payment stage.
    mutationEntryMode.value = 'MANUAL';
  } catch (error) {
    importError.value = normalizeError(error, 'Bukti non tunai manual belum dapat disimpan.');
  } finally {
    loading.manualMutation = false;
  }
}

async function handleMutationImportFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  loading.importParse = true;
  importError.value = '';
  importFeedback.value = '';
  importForm.fileName = file.name;
  importedMutationRows.value = [];
  resetMutationSelection();
  try {
    importPreviewRows.value = parseBankCsv(await file.text());
    if (!importPreviewRows.value.length) {
      throw new Error('Tidak ada baris mutasi valid yang dapat diimport dari CSV.');
    }
  } catch (error) {
    importPreviewRows.value = [];
    importError.value = normalizeError(error, 'File mutasi bank belum dapat diparsing.');
  } finally {
    loading.importParse = false;
    event.target.value = '';
  }
}

async function submitMutationImport() {
  if (!importForm.id_perusahaan || !importForm.id_rekening_perusahaan) {
    importError.value = 'Pilih perusahaan dan rekening tujuan terlebih dahulu.';
    return;
  }
  if (!importPreviewRows.value.length) {
    importError.value = 'Upload file CSV mutasi bank terlebih dahulu.';
    return;
  }
  loading.importSave = true;
  importError.value = '';
  importFeedback.value = '';
  try {
    const response = await importBankMutations({
      id_perusahaan: importForm.id_perusahaan,
      id_rekening_perusahaan: importForm.id_rekening_perusahaan,
      data_mutasi: importPreviewRows.value
    });
    const payload = unwrapResponse(response) || {};
    importFeedback.value = payload.message || `${importPreviewRows.value.length} mutasi bank berhasil diimport.`;
    await loadImportedMutations();
  } catch (error) {
    importError.value = normalizeError(error, 'Import mutasi bank belum berhasil.');
  } finally {
    loading.importSave = false;
  }
}

async function allocateImportedMutation() {
  if (!canAllocateImportedMutation.value) {
    importError.value = !String(form.officerName || '').trim()
      ? 'Isi nama petugas verifikasi transfer sebelum menyimpan alokasi mutasi.'
      : allocationExceedsMutation.value
      ? 'Total alokasi tidak boleh melebihi sisa mutasi CR.'
      : allocationHasInvalidAmount.value
        ? 'Nilai alokasi harus sama persis dengan nominal setoran sumber dari Rekap Pembayaran.'
        : 'Pilih customer, lalu alokasikan mutasi ke minimal satu setoran sumber.';
    return;
  }
  loading.bindMutation = true;
  importError.value = '';
  importFeedback.value = '';
  try {
    const response = await allocateNonCashMutation({
      id_lph: filters.id_lph,
      id_mutasi: importForm.id_mutasi,
      // New API may derive the customer from the selected deposits, but the
      // explicit id is sent whenever the LPH detail already exposes it.
      id_customer: selectedAllocationCustomer.value?.id_customer || undefined,
      allocations: selectedAllocationRows.value.map((allocation) => ({
        id_setoran: allocation.id_setoran,
        nominal_alokasi: Number(allocation.nominal_alokasi || 0)
      })),
      // Pencatatan tahap 2 membutuhkan petugas yang benar-benar memeriksa
      // bukti transfer/mutasi. Server kembali memvalidasi nilai ini dan
      // mencatatkannya bersama jurnal setoran.
      verified_by: String(form.officerName || '').trim(),
      surplus_disposition: mutationRemainder.value > 0.5 ? importForm.surplus_disposition : 'UNALLOCATED',
      catatan: String(importForm.catatan || '').trim() || undefined
    });
    const payload = unwrapResponse(response) || {};
    importFeedback.value = payload.message || (hasCustomerAdvance.value
      ? 'Alokasi mutasi tersimpan. Sisa dana dibuat sebagai Uang Muka Customer dan menunggu approval Finance.'
      : 'Alokasi mutasi tersimpan. Setoran yang teralokasi siap dicocokkan.');
    await Promise.all([loadLphDetail(), loadImportedMutations()]);
    resetMutationSelection();
  } catch (error) {
    importError.value = normalizeError(error, 'Alokasi mutasi bank belum dapat disimpan.');
  } finally {
    loading.bindMutation = false;
  }
}

function openBankMutation() {
  router.push({ name: 'finance-bank-mutations', query: { id_lph: filters.id_lph || undefined } });
}

function openCustomerAdvances() {
  router.push({
    name: 'finance-customer-advances',
    query: {
      id_perusahaan: importForm.id_perusahaan || filters.id_perusahaan || undefined,
      id_cabang: filters.id_cabang || undefined
    }
  });
}

function getEffectiveProof(row) {
  return String(
    proofByDepositId[String(row.id_setoran || '')]
    || row.bukti_transfer
    || row.kode_mutasi
    || ''
  ).trim();
}

function getExpectedCashReceipt(row) {
  return getDepositAmount(row);
}

async function recordCashDeposit() {
  if (!String(form.officerName || '').trim()) {
    errorMessage.value = 'Isi nama kasir yang menerima setoran tunai terlebih dahulu.';
    return;
  }
  if (invalidPaymentRows.value.length) {
    errorMessage.value = 'Nominal atau metode setoran tidak sama dengan input Mobile Sales. Perbaiki melalui Rekap Pembayaran, bukan dari halaman ini.';
    return;
  }

  const rows = pendingDepositRows.value.filter((row) => row.id_setoran);
  if (!rows.length) {
    errorMessage.value = 'Tidak ada setoran tunai yang menunggu pencatatan.';
    return;
  }

  const deltaMap = {};
  for (const row of rows) {
    const expected = getExpectedCashReceipt(row);
    const current = Number(row.setor_diterima_kasir || 0);
    if (current > expected + 0.5) {
      errorMessage.value = `Penerimaan kas untuk setoran ${row.id_setoran} melebihi nominal Rekap Pembayaran.`;
      return;
    }
    if (expected - current > 0.5) deltaMap[String(row.id_setoran)] = expected - current;
  }

  loading.record = true;
  feedback.value = '';
  errorMessage.value = '';
  try {
    if (Object.keys(deltaMap).length) {
      await saveCashierDeposit({
        id_setoran: rows.map((row) => row.id_setoran),
        nama_kasir: String(form.officerName).trim(),
        diterima_kasir: deltaMap,
        // Preserve the active Payment Tagihan document boundary on the
        // stage-2 cash write; the API revalidates this server-side.
        id_lph: filters.id_lph || undefined
      });
    }
    await confirmDepositStage({
      id_setoran: rows.map((row) => row.id_setoran),
      status_setoran: 2,
      nama_konfirmasi: String(form.officerName).trim(),
      id_lph: filters.id_lph || undefined
    });
    feedback.value = 'Setoran tunai tercatat. Lanjutkan ke Pembayaran Tagihan untuk pencocokan LPH, faktur, nominal, dan metode.';
    await loadLphDetail();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Setoran tunai belum dapat dicatat.');
  } finally {
    loading.record = false;
  }
}

async function recordNonCashDeposit() {
  if (invalidPaymentRows.value.length) {
    errorMessage.value = 'Nominal atau metode setoran tidak sama dengan input Mobile Sales. Perbaiki melalui Rekap Pembayaran, bukan dari halaman ini.';
    return;
  }

  const rows = pendingDepositRows.value.filter((row) => row.id_setoran);
  if (!rows.length) {
    errorMessage.value = 'Tidak ada setoran non tunai yang menunggu pencatatan.';
    return;
  }
  // A transfer is never recorded merely from a typed reference.  The
  // selected CR bank mutation is the evidence and can be allocated to one
  // or more complete Mobile Sales claims only through the guarded modal.
  errorMessage.value = '';
  feedback.value = 'Pilih mutasi CR hasil import atau catat bukti transfer/BG manual pada rekening perusahaan, lalu alokasikan ke setoran sumber di modal berikut.';
  openDirectMutationImport();
}

async function recordDeposits() {
  if (isCash.value) return recordCashDeposit();
  return recordNonCashDeposit();
}

function resetFilters() {
  filters.id_perusahaan = shouldLockBusinessScope.value ? String(fallbackCompanyId.value || '') : '';
  filters.id_cabang = shouldLockBusinessScope.value ? String(fallbackBranchId.value || '') : '';
  filters.id_sales = shouldLockSalesScope.value ? String(fallbackSalesId.value || '') : '';
  filters.status = 'AKTIF';
  filters.search = '';
  filters.id_lph = '';
  form.officerName = '';
  lphRows.value = [];
  clearDetail();
  feedback.value = '';
  errorMessage.value = '';
}

async function initialize() {
  await loadMasters();
  if (fallbackCompanyId.value) filters.id_perusahaan = String(fallbackCompanyId.value);
  if (fallbackBranchId.value) filters.id_cabang = String(fallbackBranchId.value);
  if (fallbackSalesId.value && shouldLockSalesScope.value) filters.id_sales = String(fallbackSalesId.value);
  if (route.query.id_lph) filters.id_lph = String(route.query.id_lph);
  await loadLphs({ preserveSelection: true });
  if (filters.id_lph && !detail.value.lph) await loadLphDetail();
}

watch(
  () => route.query.id_lph,
  async (value) => {
    const nextValue = String(value || '');
    if (!nextValue || nextValue === String(filters.id_lph || '')) return;
    filters.id_lph = nextValue;
    await loadLphs({ preserveSelection: true });
    if (!detail.value.lph) await loadLphDetail();
  }
);

onMounted(initialize);
</script>

<template>
  <div class="deposit-method-page space-y-6">
    <PageHeader :title="methodTitle" :description="methodDescription">
      <div class="flex flex-wrap gap-2">
        <button class="button-secondary" :disabled="loading.lphs" @click="loadLphs()">
          {{ loading.lphs ? 'Memuat...' : 'Muat Ulang' }}
        </button>
        <button class="button-secondary" @click="openRecap">Buka Rekap Pembayaran</button>
        <button v-if="!isCash" class="button-primary" :disabled="!filters.id_lph" @click="openDirectMutationImport">Import Mutasi Bank</button>
        <button v-if="!isCash" class="button-secondary" :disabled="!filters.id_lph" @click="openManualNonCashEntry">Catat Transfer/BG Manual</button>
        <button v-if="!isCash" class="button-secondary" @click="openBankMutation">Riwayat Mutasi</button>
        <button v-if="!isCash" class="button-secondary" @click="openCustomerAdvances">Uang Muka Customer</button>
        <button class="button-primary" :disabled="!filters.id_lph" @click="openPaymentTagihan">Buka Pembayaran Tagihan</button>
      </div>
    </PageHeader>

    <section class="panel p-5">
      <div class="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <p class="section-eyebrow">{{ isCash ? '03A' : '03B' }} · Sumber Setoran</p>
          <h2 class="section-title">Pilih LPH dan {{ isCash ? 'terima kas' : 'cocokkan mutasi transfer' }}</h2>
          <p class="section-description">LPH menjaga setiap setoran tetap terhubung pada faktur serta pembayaran Mobile Sales yang benar.</p>
        </div>
        <span class="scope-note">{{ formatNumber(lphRows.length) }} LPH ditemukan</span>
      </div>

      <div class="grid min-w-0 gap-4 [grid-template-columns:repeat(auto-fit,minmax(210px,1fr))]">
        <AppSearchSelect
          :model-value="filters.id_perusahaan"
          label="Perusahaan"
          placeholder="Semua perusahaan"
          :options="companyOptions"
          :disabled="shouldLockBusinessScope && !!fallbackCompanyId"
          empty-text="Perusahaan belum tersedia."
          @update:model-value="onCompanyChanged"
        />
        <AppSearchSelect
          :model-value="filters.id_cabang"
          label="Cabang"
          placeholder="Semua cabang"
          :options="branchOptions"
          :disabled="!filters.id_perusahaan || (shouldLockBusinessScope && !!fallbackBranchId)"
          empty-text="Pilih perusahaan terlebih dahulu."
          @update:model-value="onBranchChanged"
        />
        <AppSearchSelect
          :model-value="filters.id_sales"
          label="Sales"
          placeholder="Semua sales"
          :options="salesOptions"
          :disabled="shouldLockSalesScope && !!fallbackSalesId"
          empty-text="Sales belum tersedia."
          @update:model-value="onSalesChanged"
        />
        <label class="block">
          <span class="field-label">Cari LPH</span>
          <input v-model="filters.search" class="field-control" placeholder="Kode LPH atau nama sales" @keyup.enter="loadLphs({ preserveSelection: false })" />
        </label>
        <div class="flex items-end gap-2">
          <button class="button-primary w-full" :disabled="loading.lphs" @click="loadLphs({ preserveSelection: false })">
            Tampilkan LPH
          </button>
          <button class="button-secondary shrink-0" @click="resetFilters">Reset</button>
        </div>
      </div>

      <div class="mt-4 grid min-w-0 gap-4 [grid-template-columns:minmax(0,1fr)]">
        <AppSearchSelect
          :model-value="filters.id_lph"
          label="LPH"
          placeholder="Pilih LPH untuk melihat setoran"
          :options="lphOptions"
          :loading="loading.lphs"
          empty-text="Tidak ada LPH pada scope ini."
          @update:model-value="chooseLph"
        />
      </div>

      <div class="mt-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
        <p>
          Alur: <span class="font-semibold text-slate-900 dark:text-white">Mobile Sales → Rekap Pembayaran → {{ methodTitle }} → Pembayaran Tagihan → Finalisasi</span>.
        </p>
        <p class="mt-1">
          Nominal dan metode di halaman ini bersifat kontrol: keduanya berasal dari pembayaran Mobile Sales dan tidak dapat diganti di Setoran.
        </p>
      </div>
    </section>

    <section v-if="filters.id_lph" class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <article v-for="item in summaryCards" :key="item.label" class="panel p-5">
        <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">{{ item.label }}</p>
        <p
          class="mt-3 text-xl font-bold"
          :class="{
            'text-emerald-600': item.tone === 'emerald',
            'text-amber-600': item.tone === 'amber',
            'text-sky-600': item.tone === 'sky',
            'text-violet-600': item.tone === 'violet',
            'text-rose-600': item.tone === 'rose'
          }"
        >
          {{ item.value }}
        </p>
      </article>
    </section>

    <section v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
      {{ errorMessage }}
    </section>
    <section v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200">
      {{ feedback }}
    </section>

    <section v-if="!filters.id_lph" class="panel px-5 py-12 text-center">
      <p class="text-lg font-semibold text-slate-900 dark:text-white">Pilih LPH untuk memulai pencatatan setoran.</p>
      <p class="mt-2 text-sm text-slate-500">Faktur, metode bayar, dan nominal akan ditarik langsung dari LPH terpilih.</p>
    </section>

    <template v-else>
      <section class="panel p-5">
        <div class="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <p class="section-eyebrow">LPH Terpilih</p>
            <h2 class="mt-1 text-2xl font-bold text-slate-950 dark:text-white">{{ detail.lph?.kode_lph || selectedLph?.kode_lph || `LPH-${filters.id_lph}` }}</h2>
            <p class="mt-1 text-sm text-slate-500">
              Sales: <strong>{{ detail.lph?.nama_sales || selectedLph?.nama_sales || '-' }}</strong>
              <span class="mx-2">·</span>
              Tanggal: <strong>{{ formatDate(detail.lph?.tanggal_lph || selectedLph?.tanggal_lph) }}</strong>
            </p>
          </div>
          <span
            class="inline-flex w-fit rounded-full px-3 py-1 text-xs font-semibold"
            :class="lphIsActive ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-200' : 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-200'"
          >
            {{ lphStatusLabel(detail.lph?.status_dokumen || selectedLph?.status_dokumen) }}
          </span>
        </div>

        <div v-if="!lphIsActive" class="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-100">
          LPH belum aktif di sales. Sales perlu menekan <strong>Terima LPH</strong> pada Mobile Sales sebelum setoran dapat dicatat.
        </div>
        <div v-else-if="pendingRekapRows.length" class="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-100">
          <span>{{ pendingRekapRows.length }} pembayaran {{ isCash ? 'tunai' : 'non tunai' }} belum menjadi setoran dari Rekap Pembayaran.</span>
          <button class="button-secondary" @click="openRecap">Buka Rekap Pembayaran</button>
        </div>
      </section>

      <section class="panel overflow-hidden">
        <div class="flex flex-col gap-2 border-b border-slate-200 px-5 py-4 dark:border-slate-800">
          <h3 class="text-lg font-semibold text-slate-900 dark:text-white">Antrian {{ methodTitle }}</h3>
          <p class="text-sm text-slate-500">Setiap baris tetap terikat pada pembayaran Mobile Sales dan faktur sumbernya. Nominal maupun metode tidak bisa diedit di sini.</p>
        </div>

        <div class="overflow-x-auto">
          <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
            <thead class="bg-slate-50 dark:bg-slate-900">
              <tr>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Faktur</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Pembayaran Mobile</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Setoran Rekap</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Bukti / Referensi</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Status</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 bg-white dark:divide-slate-800 dark:bg-slate-950">
              <tr v-if="loading.detail">
                <td colspan="5" class="px-4 py-10 text-center text-slate-500">Memuat pembayaran LPH...</td>
              </tr>
              <tr v-else-if="!methodPayments.length">
                <td colspan="5" class="px-4 py-10 text-center text-slate-500">Belum ada pembayaran {{ isCash ? 'tunai' : 'non tunai' }} pada LPH ini.</td>
              </tr>
              <tr v-for="payment in methodPayments" v-else :key="payment.key">
                <td class="px-4 py-3 align-top text-slate-700 dark:text-slate-200">
                  <p class="font-semibold">{{ payment.no_faktur || '-' }}</p>
                  <p class="mt-1 text-xs text-slate-500">SO: {{ payment.id_sales_order || '-' }}</p>
                </td>
                <td class="px-4 py-3 align-top text-slate-700 dark:text-slate-200">
                  <p class="font-semibold">{{ formatCurrency(payment.mobileAmount) }}</p>
                  <p class="mt-1 text-xs text-slate-500">{{ paymentMethodLabel(payment.expectedMethod) }}</p>
                </td>
                <td class="px-4 py-3 align-top text-slate-700 dark:text-slate-200">
                  <template v-if="payment.depositRows.length">
                    <div v-for="row in payment.depositRows" :key="row.id_setoran || `${payment.key}-${row.id}`" class="mb-2 last:mb-0">
                      <p class="font-semibold">{{ formatCurrency(getDepositAmount(row)) }}</p>
                      <p class="mt-1 text-xs text-slate-500">ID Setoran: {{ row.id_setoran || '-' }}</p>
                    </div>
                  </template>
                  <span v-else-if="payment.allDepositRows.length" class="text-rose-600 dark:text-rose-300">Metode setoran Rekap tidak sesuai</span>
                  <span v-else class="text-rose-600 dark:text-rose-300">Belum direkap</span>
                </td>
                <td class="min-w-[260px] px-4 py-3 align-top text-slate-700 dark:text-slate-200">
                  <template v-if="payment.depositRows.length">
                    <div v-for="row in payment.depositRows" :key="`proof-${row.id_setoran || payment.key}`" class="mb-2 last:mb-0">
                      <p class="text-sm font-medium">{{ getEffectiveProof(row) || (isCash ? 'Kas fisik diterima kasir' : 'Menunggu mutasi CR dialokasikan') }}</p>
                      <p v-if="!isCash && Number(row.status_setoran || 0) === 1" class="mt-1 text-xs text-amber-700 dark:text-amber-200">
                        Catat melalui import mutasi CR atau bukti transfer/BG manual, lalu alokasikan secara terkontrol.
                      </p>
                      <p v-if="row.kode_mutasi" class="mt-1 text-xs text-slate-500">Mutasi: {{ row.kode_mutasi }}</p>
                    </div>
                  </template>
                  <span v-else class="text-slate-400">-</span>
                </td>
                <td class="px-4 py-3 align-top">
                  <div class="flex flex-col items-start gap-2">
                    <span
                      v-for="row in payment.depositRows"
                      :key="`status-${row.id_setoran || payment.key}`"
                      class="inline-flex rounded-full px-3 py-1 text-xs font-semibold"
                      :class="resolveStatusClass(row.status_setoran)"
                    >
                      {{ resolveDepositStage(row.status_setoran) }}
                    </span>
                    <span v-if="!payment.depositRows.length" class="inline-flex rounded-full bg-rose-100 px-3 py-1 text-xs font-semibold text-rose-700 dark:bg-rose-500/15 dark:text-rose-200">
                      Menunggu Rekap
                    </span>
                    <span v-if="payment.allDepositRows.length && (!payment.amountMatches || !payment.methodMatches)" class="text-xs font-semibold text-rose-600 dark:text-rose-300">
                      Selisih {{ formatCurrency(payment.difference) }} / metode tidak sesuai
                    </span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel p-5">
        <div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-end">
          <label class="block">
            <span class="field-label">{{ isCash ? 'Nama Kasir Penerima' : 'Nama Petugas Verifikasi Transfer' }}</span>
            <input v-model="form.officerName" class="field-control" :placeholder="isCash ? 'Nama kasir yang menerima fisik uang' : 'Nama petugas yang memeriksa bukti transfer'" />
          </label>
          <div class="flex flex-wrap gap-2">
            <button class="button-secondary" :disabled="!filters.id_lph" @click="openPaymentTagihan">Cek di Pembayaran Tagihan</button>
            <button class="button-primary" :disabled="actionDisabled" @click="recordDeposits">
              {{ loading.record ? 'Memproses...' : actionLabel }}
            </button>
          </div>
        </div>
        <p class="mt-3 text-sm text-slate-500">
          {{ isCash
            ? 'Sistem akan mencatat nilai tunai persis sebesar nilai hasil Rekap. Selisih harus dikoreksi di Rekap Pembayaran.'
            : 'Setoran non tunai dicatat dari mutasi CR yang diimpor atau bukti transfer/BG manual yang direkam pada rekening perusahaan, lalu wajib dialokasikan ke setoran sumber. Nominal dan metode tetap dikunci.' }}
        </p>
      </section>
    </template>

    <AppModal
      v-if="!isCash"
      :open="importOpen"
      title="Catat & Cocokkan Setoran Non Tunai"
      description="Import mutasi CR atau catat bukti transfer/BG manual pada rekening perusahaan, lalu alokasikan ke satu atau beberapa setoran sumber pada customer yang sama. Pencatatan tidak membuat finalisasi."
      size="4xl"
      @close="importOpen = false"
    >
      <div class="space-y-6">
        <section class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p class="section-eyebrow">01 · Sumber dana</p>
              <h3 class="mt-1 text-lg font-bold text-slate-950 dark:text-white">Pilih rekening tujuan dan bukti penerimaan</h3>
              <p class="mt-1 text-sm text-slate-500">Gunakan mutasi <strong>CR / dana masuk</strong> hasil import, atau catat transfer/Bilyet Giro manual dengan nomor referensi yang dapat diaudit.</p>
            </div>
            <span class="scope-note">LPH: {{ detail.lph?.kode_lph || selectedLph?.kode_lph || `LPH-${filters.id_lph}` }}</span>
          </div>

          <div class="mt-4 flex flex-wrap gap-2">
            <button class="button-secondary" :class="mutationEntryMode === 'IMPORT' ? 'ring-2 ring-blue-500' : ''" @click="mutationEntryMode = 'IMPORT'">Import CSV</button>
            <button class="button-secondary" :class="mutationEntryMode === 'MANUAL' ? 'ring-2 ring-blue-500' : ''" @click="mutationEntryMode = 'MANUAL'">Catat Transfer/BG Manual</button>
          </div>

          <div class="mt-4 grid gap-4 md:grid-cols-2">
            <AppSearchSelect
              :model-value="importForm.id_perusahaan"
              label="Perusahaan rekening"
              placeholder="Pilih perusahaan"
              :options="companyOptions"
              :disabled="shouldLockBusinessScope && !!fallbackCompanyId"
              empty-text="Perusahaan belum tersedia."
              @update:model-value="onImportCompanyChanged"
            />
            <AppSearchSelect
              :model-value="importForm.id_rekening_perusahaan"
              label="Rekening perusahaan"
              placeholder="Pilih rekening tujuan"
              :options="bankAccountOptions"
              :disabled="!importForm.id_perusahaan"
              empty-text="Pilih perusahaan atau siapkan rekening aktif terlebih dahulu."
              @update:model-value="onImportAccountChanged"
            />
            <label v-if="mutationEntryMode === 'IMPORT'" class="block md:col-span-2">
              <span class="field-label">File CSV mutasi bank</span>
              <input
                type="file"
                accept=".csv,text/csv"
                class="field-control file:mr-3 file:rounded-lg file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-sm file:font-semibold file:text-slate-700 dark:file:bg-slate-800 dark:file:text-slate-100"
                @change="handleMutationImportFile"
              />
            </label>
          </div>

          <div v-if="mutationEntryMode === 'MANUAL'" class="mt-4 grid gap-4 rounded-xl border border-violet-200 bg-violet-50/60 p-4 md:grid-cols-2 dark:border-violet-500/30 dark:bg-violet-500/10">
            <label class="block">
              <span class="field-label">Jenis instrumen</span>
              <select v-model="manualMutationForm.instrument_type" class="field-control">
                <option value="TRANSFER_MANUAL">Transfer bank manual</option>
                <option value="BILYET_GIRO">Bilyet Giro</option>
                <option value="CEK">Cek</option>
                <option value="GIRO">Giro</option>
                <option value="LAINNYA">Lainnya</option>
              </select>
            </label>
            <label class="block">
              <span class="field-label">Tanggal instrumen</span>
              <input v-model="manualMutationForm.tanggal_mutasi" type="date" class="field-control" />
            </label>
            <label class="block">
              <span class="field-label">Nomor referensi / BG</span>
              <input v-model="manualMutationForm.nomor_referensi" class="field-control" placeholder="Wajib diisi dan dapat ditelusuri" />
            </label>
            <label class="block">
              <span class="field-label">Nominal diterima</span>
              <input v-model="manualMutationForm.nominal_mutasi" min="1" step="0.01" type="number" inputmode="decimal" class="field-control" placeholder="0" />
            </label>
            <label class="block md:col-span-2">
              <span class="field-label">Catatan bukti <span class="font-normal text-slate-400">(opsional)</span></span>
              <textarea v-model="manualMutationForm.catatan" class="field-control min-h-20" placeholder="Contoh: Bukti transfer diterima dari toko, menunggu mutasi rekening; atau nomor BG dan tanggal cair." />
            </label>
            <div class="md:col-span-2 rounded-lg border border-violet-200 bg-white px-3 py-3 text-sm text-violet-900 dark:border-violet-500/30 dark:bg-slate-950 dark:text-violet-100">
              Pencatatan manual hanya membuat mutasi CR yang diaudit (rekening, pelaku, waktu, instrumen, referensi). Dana tetap <strong>belum melunasi faktur</strong> sampai dialokasikan ke sumber Rekap dan melalui finalisasi Finance.
            </div>
          </div>

          <div v-if="mutationEntryMode === 'IMPORT'" class="mt-4 grid gap-3 sm:grid-cols-4">
            <div class="rounded-xl bg-slate-50 p-3 dark:bg-slate-900">
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">File</p>
              <p class="mt-1 truncate text-sm font-semibold text-slate-900 dark:text-white">{{ importForm.fileName || '-' }}</p>
            </div>
            <div class="rounded-xl bg-slate-50 p-3 dark:bg-slate-900">
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Baris valid</p>
              <p class="mt-1 text-lg font-bold text-slate-900 dark:text-white">{{ formatNumber(importPreviewRows.length) }}</p>
            </div>
            <div class="rounded-xl bg-emerald-50 p-3 dark:bg-emerald-500/10">
              <p class="text-xs font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-200">CR / masuk</p>
              <p class="mt-1 text-sm font-bold text-emerald-700 dark:text-emerald-200">{{ formatCurrency(importPreviewRows.filter((row) => row.tipe === 'cr').reduce((total, row) => total + Number(row.jumlah || 0), 0)) }}</p>
            </div>
            <div class="rounded-xl bg-rose-50 p-3 dark:bg-rose-500/10">
              <p class="text-xs font-semibold uppercase tracking-wide text-rose-700 dark:text-rose-200">DB / keluar</p>
              <p class="mt-1 text-sm font-bold text-rose-700 dark:text-rose-200">{{ formatCurrency(importPreviewRows.filter((row) => row.tipe === 'db').reduce((total, row) => total + Number(row.jumlah || 0), 0)) }}</p>
            </div>
          </div>

          <div v-if="mutationEntryMode === 'IMPORT'" class="mt-4 max-h-52 overflow-auto rounded-xl border border-slate-200 dark:border-slate-700">
            <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
              <thead class="bg-slate-50 text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                <tr>
                  <th class="px-3 py-2 text-left font-semibold">Tanggal</th>
                  <th class="px-3 py-2 text-left font-semibold">Tipe</th>
                  <th class="px-3 py-2 text-right font-semibold">Nominal</th>
                  <th class="px-3 py-2 text-left font-semibold">Keterangan</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100 bg-white text-slate-700 dark:divide-slate-800 dark:bg-slate-950 dark:text-slate-200">
                <tr v-if="loading.importParse"><td colspan="4" class="px-3 py-6 text-center text-slate-500">Membaca file...</td></tr>
                <tr v-else-if="!importPreviewRows.length"><td colspan="4" class="px-3 py-6 text-center text-slate-500">Pilih file CSV untuk melihat preview.</td></tr>
                <tr v-for="(row, index) in importPreviewRows.slice(0, 100)" v-else :key="`${row.tanggal}-${row.keterangan}-${index}`">
                  <td class="px-3 py-2">{{ row.tanggal }}</td>
                  <td class="px-3 py-2 font-semibold" :class="row.tipe === 'cr' ? 'text-emerald-700 dark:text-emerald-200' : 'text-rose-700 dark:text-rose-200'">{{ row.tipe.toUpperCase() }}</td>
                  <td class="px-3 py-2 text-right">{{ formatCurrency(row.jumlah) }}</td>
                  <td class="px-3 py-2">{{ row.keterangan || '-' }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-if="mutationEntryMode === 'IMPORT'" class="mt-4 flex justify-end">
            <button class="button-secondary" :disabled="loading.importSave || !importPreviewRows.length" @click="submitMutationImport">
              {{ loading.importSave ? 'Mengimport...' : 'Import & Tampilkan Mutasi CR' }}
            </button>
          </div>
          <div v-else class="mt-4 flex justify-end">
            <button class="button-secondary" :disabled="loading.manualMutation || !importForm.id_rekening_perusahaan" @click="submitManualNonCashMutation">
              {{ loading.manualMutation ? 'Menyimpan...' : 'Catat Mutasi CR Manual' }}
            </button>
          </div>
        </section>

        <section class="rounded-2xl border border-sky-200 bg-sky-50/60 p-4 dark:border-sky-500/30 dark:bg-sky-500/10">
          <div>
            <p class="section-eyebrow">02 · Alokasi mutasi</p>
            <h3 class="mt-1 text-lg font-bold text-slate-950 dark:text-white">Alokasikan satu transfer ke beberapa faktur</h3>
            <p class="mt-1 text-sm text-slate-600 dark:text-slate-300">Pilih satu customer pemilik dana, lalu pilih beberapa setoran sumber secara penuh. Alokasi hanya bisa dilakukan dalam customer, perusahaan, dan cabang yang sama agar audit tetap aman.</p>
          </div>

          <div class="mt-4 grid gap-4 md:grid-cols-2">
            <AppSearchSelect
              :model-value="importForm.id_mutasi"
              label="Mutasi CR yang masih bersisa"
              placeholder="Pilih mutasi hasil import atau pencatatan manual"
              :options="mutationOptions"
              :loading="loading.importMutations"
              empty-text="Import CSV atau catat bukti transfer/BG manual terlebih dahulu; atau tidak ada mutasi CR yang masih bersisa."
              @update:model-value="onImportedMutationChanged"
            />
            <AppSearchSelect
              :model-value="importForm.customer_scope_key"
              label="Customer pemilik dana"
              placeholder="Pilih customer sebelum alokasi"
              :options="allocationCustomerOptions"
              :disabled="!selectedImportedMutation"
              empty-text="Belum ada setoran non tunai yang direkap dan menunggu pencatatan."
              @update:model-value="onAllocationCustomerChanged"
            />
          </div>

          <template v-if="selectedImportedMutation">
            <div class="mt-4 grid gap-3 sm:grid-cols-3">
              <div class="rounded-xl bg-white p-3 dark:bg-slate-950">
                <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Sisa mutasi</p>
                <p class="mt-1 text-lg font-bold text-slate-950 dark:text-white">{{ formatCurrency(selectedMutationAmount) }}</p>
              </div>
              <div class="rounded-xl bg-emerald-50 p-3 dark:bg-emerald-500/10">
                <p class="text-xs font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-200">Dialokasikan</p>
                <p class="mt-1 text-lg font-bold text-emerald-700 dark:text-emerald-200">{{ formatCurrency(allocatedMutationAmount) }}</p>
              </div>
              <div class="rounded-xl bg-amber-50 p-3 dark:bg-amber-500/10">
                <p class="text-xs font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-200">Sisa setelah alokasi</p>
                <p class="mt-1 text-lg font-bold text-amber-700 dark:text-amber-200">{{ formatCurrency(mutationRemainder) }}</p>
              </div>
            </div>

            <div class="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-sky-200 bg-white px-4 py-3 text-sm text-slate-700 dark:border-sky-500/30 dark:bg-slate-950 dark:text-slate-200">
              <div>
                <p class="font-semibold">Metode alokasi</p>
                <p class="mt-1 text-xs text-slate-500">FIFO memilih setoran utuh berdasarkan jatuh tempo. Manual memilih setoran utuh yang diinginkan; nominalnya tetap mengikuti Rekap Pembayaran.</p>
              </div>
              <div class="flex flex-wrap gap-2">
                <label class="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-700">
                  <input type="radio" name="mutation-allocation-mode" value="FIFO" :checked="importForm.allocation_mode === 'FIFO'" @change="onAllocationModeChanged('FIFO')" />
                  FIFO
                </label>
                <label class="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-700">
                  <input type="radio" name="mutation-allocation-mode" value="MANUAL" :checked="importForm.allocation_mode === 'MANUAL'" @change="onAllocationModeChanged('MANUAL')" />
                  Manual
                </label>
                <button class="button-secondary" :disabled="!selectedAllocationCustomer" @click="applyFifoAllocation">Isi FIFO</button>
              </div>
            </div>

            <div v-if="!selectedAllocationCustomer" class="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-100">
              Pilih customer terlebih dahulu. Satu mutasi tidak dapat dibagi ke customer yang berbeda, termasuk saat terdapat saldo lebih.
            </div>

            <div v-else class="mt-4 overflow-hidden rounded-xl border border-slate-200 dark:border-slate-700">
              <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
                  <thead class="bg-slate-50 text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                    <tr>
                      <th class="w-12 px-3 py-3 text-center font-semibold">Pilih</th>
                      <th class="px-3 py-3 text-left font-semibold">Faktur / SO</th>
                      <th class="px-3 py-3 text-left font-semibold">Jatuh tempo</th>
                      <th class="px-3 py-3 text-right font-semibold">Sisa setoran</th>
                      <th class="min-w-[180px] px-3 py-3 text-right font-semibold">Alokasi penuh</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-slate-100 bg-white text-slate-700 dark:divide-slate-800 dark:bg-slate-950 dark:text-slate-200">
                    <tr v-if="!allocationCandidates.length">
                      <td colspan="5" class="px-3 py-8 text-center text-slate-500">Tidak ada setoran non tunai yang dapat dialokasikan untuk customer ini.</td>
                    </tr>
                    <tr v-for="candidate in allocationCandidates" v-else :key="candidate.id_setoran">
                      <td class="px-3 py-3 text-center">
                        <input
                          type="checkbox"
                          :checked="isAllocationSelected(candidate)"
                          :disabled="!isAllocationSelected(candidate) && !canSelectFullCandidate(candidate)"
                          :title="!isAllocationSelected(candidate) && !canSelectFullCandidate(candidate) ? 'Sisa mutasi belum cukup untuk memilih setoran ini secara penuh.' : 'Pilih atau batalkan setoran sumber ini.'"
                          @change="toggleAllocationCandidate(candidate, $event.target.checked)"
                        />
                      </td>
                      <td class="px-3 py-3">
                        <p class="font-semibold">{{ candidate.no_faktur || '-' }}</p>
                        <p class="mt-1 text-xs text-slate-500">SO: {{ candidate.id_sales_order || '-' }} · Setoran #{{ candidate.id_setoran }}</p>
                      </td>
                      <td class="px-3 py-3">{{ formatDate(candidate.tanggal_jatuh_tempo) }}</td>
                      <td class="px-3 py-3 text-right font-semibold">{{ formatCurrency(candidate.nominal_tersedia) }}</td>
                      <td class="px-3 py-3 text-right">
                        <p v-if="isAllocationSelected(candidate)" class="font-semibold text-emerald-700 dark:text-emerald-200">{{ formatCurrency(allocationEntryFor(candidate)?.nominal_alokasi) }}</p>
                        <p v-else class="font-semibold text-slate-400">-</p>
                        <p class="mt-1 text-xs" :class="isAllocationSelected(candidate) ? 'text-slate-500' : (canSelectFullCandidate(candidate) ? 'text-slate-500' : 'text-amber-700 dark:text-amber-200')">
                          {{ isAllocationSelected(candidate) ? 'Nominal Rekap dikunci' : (canSelectFullCandidate(candidate) ? 'Pilih alokasi penuh' : 'Sisa mutasi belum cukup') }}
                        </p>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <div class="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-100">
              <p class="font-semibold">Aturan audit nominal</p>
              <p class="mt-1">Finance hanya boleh memilih sumber Rekap secara penuh; nominal Mobile Sales tidak dapat diubah atau dipecah di halaman ini. Jika transfer hanya sebagian dari satu faktur, catat dahulu nominal pembayaran parsial yang sebenarnya di Mobile Sales agar Rekap membuat setoran sumber dengan nominal yang sama.</p>
            </div>

            <div v-if="allocationExceedsMutation" class="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
              Total alokasi melebihi sisa mutasi. Kurangi salah satu nominal alokasi.
            </div>
            <div v-else-if="allocationHasInvalidAmount" class="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
              Setiap alokasi harus sama persis dengan nominal setoran sumber dari Rekap Pembayaran.
            </div>

            <div v-if="mutationRemainder > 0.5" class="mt-4 rounded-xl border border-violet-200 bg-violet-50 p-4 dark:border-violet-500/30 dark:bg-violet-500/10">
              <div class="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p class="font-semibold text-violet-950 dark:text-violet-100">Ada saldo lebih {{ formatCurrency(mutationRemainder) }}</p>
                  <p class="mt-1 text-sm text-violet-800 dark:text-violet-200">Saldo lebih tidak boleh hilang atau otomatis melunasi faktur lain. Pilih perlakuannya secara eksplisit.</p>
                </div>
                <div class="flex flex-wrap gap-2">
                  <label class="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-violet-200 bg-white px-3 py-2 text-sm dark:border-violet-500/30 dark:bg-slate-950">
                    <input v-model="importForm.surplus_disposition" type="radio" value="ADVANCE" />
                    Jadikan Uang Muka
                  </label>
                  <label class="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-violet-200 bg-white px-3 py-2 text-sm dark:border-violet-500/30 dark:bg-slate-950">
                    <input v-model="importForm.surplus_disposition" type="radio" value="UNALLOCATED" />
                    Biarkan belum dialokasikan
                  </label>
                </div>
              </div>
              <p v-if="hasCustomerAdvance" class="mt-3 text-sm font-medium text-violet-900 dark:text-violet-100">Uang Muka akan berstatus <strong>menunggu approval Finance</strong> dan baru boleh dipakai pada faktur lain setelah disetujui.</p>
            </div>

            <label class="mt-4 block">
              <span class="field-label">Nama petugas verifikasi transfer</span>
              <input v-model="form.officerName" class="field-control" placeholder="Nama petugas yang memeriksa mutasi/bukti transfer" />
              <span class="mt-1 block text-xs text-slate-500">Wajib diisi untuk mencatat setoran tahap verifikasi. Nama ini masuk ke jejak audit dan jurnal.</span>
            </label>

            <label class="mt-4 block">
              <span class="field-label">Catatan alokasi <span class="font-normal text-slate-400">(opsional)</span></span>
              <textarea v-model="importForm.catatan" class="field-control min-h-20" placeholder="Contoh: Transfer gabungan faktur A dan B; sisa disimpan sebagai uang muka customer." />
            </label>
          </template>
        </section>

        <p v-if="importError" class="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">{{ importError }}</p>
        <p v-if="importFeedback" class="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200">{{ importFeedback }}</p>
      </div>

      <template #footer>
        <div class="flex flex-wrap justify-end gap-2">
          <button class="button-secondary" @click="importOpen = false">Tutup</button>
          <button class="button-primary" :disabled="loading.bindMutation || !canAllocateImportedMutation" @click="allocateImportedMutation">
            {{ loading.bindMutation ? 'Menyimpan...' : (hasCustomerAdvance ? 'Simpan Alokasi & Uang Muka' : 'Simpan Alokasi Mutasi') }}
          </button>
        </div>
      </template>
    </AppModal>
  </div>
</template>

<style scoped>
.button-primary,
.button-secondary {
  border-radius: 0.75rem;
  padding: 0.7rem 1rem;
  font-size: 0.875rem;
  font-weight: 700;
  transition: background-color 0.15s ease, border-color 0.15s ease, opacity 0.15s ease;
}

.button-primary {
  background: rgb(37 99 235);
  color: #fff;
}

.button-primary:hover:not(:disabled) {
  background: rgb(29 78 216);
}

.button-secondary {
  border: 1px solid rgb(203 213 225);
  color: rgb(51 65 85);
}

:global(.dark) .button-secondary {
  border-color: rgb(51 65 85);
  color: rgb(226 232 240);
}

.button-secondary:hover:not(:disabled) {
  background: rgb(248 250 252);
}

:global(.dark) .button-secondary:hover:not(:disabled) {
  background: rgb(30 41 59);
}

.button-primary:disabled,
.button-secondary:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.section-eyebrow {
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: rgb(100 116 139);
}

.section-title {
  margin-top: 0.25rem;
  font-size: 1.2rem;
  font-weight: 700;
  color: rgb(15 23 42);
}

:global(.dark) .section-title {
  color: rgb(248 250 252);
}

.section-description {
  margin-top: 0.25rem;
  font-size: 0.9rem;
  color: rgb(100 116 139);
}

.scope-note {
  border-radius: 9999px;
  background: rgb(241 245 249);
  padding: 0.4rem 0.75rem;
  font-size: 0.75rem;
  font-weight: 700;
  color: rgb(71 85 105);
}

:global(.dark) .scope-note {
  background: rgb(30 41 59);
  color: rgb(203 213 225);
}
</style>
