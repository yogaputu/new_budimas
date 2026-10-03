<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  approvePaymentExpenseAdjustment,
  createPaymentExpenseAdjustment,
  getCoaCatalog,
  getPaymentExpenseAdjustments,
  getPaymentLphDetail,
  getPaymentLphs,
  voidPaymentExpenseAdjustment
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
import AppFormField from '@/shared/components/AppFormField.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const numberFormatter = new Intl.NumberFormat('id-ID', { maximumFractionDigits: 2 });
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const filters = reactive({
  id_perusahaan: '',
  id_cabang: '',
  id_sales: '',
  status: 'AKTIF',
  search: '',
  id_lph: ''
});

const companyRows = ref([]);
const branchRows = ref([]);
const salesRows = ref([]);
const lphRows = ref([]);
const detail = ref(createEmptyDetail());
const expenseRows = ref([]);
const expenseSummary = ref(createEmptyExpenseSummary());
const expenseCoaRows = ref([]);
const expenseForm = reactive({
  id_faktur: '',
  id_coa: '',
  kategori: 'ADMIN_TRANSFER',
  impact_direction: 'PENGURANG_SETORAN',
  nominal: '',
  catatan: ''
});
const feedback = ref('');
const errorMessage = ref('');
const loading = reactive({
  masters: false,
  lphs: false,
  detail: false,
  expenses: false,
  expenseSubmit: false,
  expenseActionId: ''
});

const fallbackBranchId = computed(() => getLoginBranchId(auth.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(auth.user));
const fallbackSalesId = computed(() => getLoginSalesId(auth.user));
const canAccessAllBranches = computed(() => isSuperUser(auth));
const shouldLockBusinessScope = computed(() =>
  !canAccessAllBranches.value && !hasSupervisorSalesScope(auth.user) && !hasMultiBusinessScope(auth.user)
);
const shouldLockSalesScope = computed(() => shouldLockToLoginSales(auth));

const companyOptions = computed(() => getCompanyOptionsForScope(companyRows.value, auth, true));
const branchOptions = computed(() =>
  getBranchOptionsForCompany(branchRows.value, auth, filters.id_perusahaan, true, companyRows.value)
);

function salesMatchesCompany(row, companyId) {
  if (!companyId) return true;
  const directCompanyId = getRowCompanyId(row);
  // Older sales rows do not include company. The server-side LPH lookup is
  // still constrained by company, so do not hide a valid sales option here.
  return !directCompanyId || String(directCompanyId) === String(companyId);
}

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
  { value: '', label: 'Pilih LPH untuk memuat faktur' },
  ...lphRows.value.map((row) => ({
    value: String(row.id),
    label: `${row.kode_lph || `LPH-${row.id}`} · ${row.nama_sales || 'Sales'} · ${formatDate(row.tanggal_lph)} · ${formatNumber(row.jumlah_faktur)} faktur`
  }))
]);

const selectedLph = computed(() =>
  lphRows.value.find((row) => String(row.id) === String(filters.id_lph)) || detail.value.lph || null
);

const lphIsActive = computed(() => String(detail.value.lph?.status_dokumen || selectedLph.value?.status_dokumen || '').toUpperCase() === 'AKTIF');
const invoices = computed(() => Array.isArray(detail.value.invoices) ? detail.value.invoices : []);
const payments = computed(() => Array.isArray(detail.value.payments) ? detail.value.payments : []);
const advanceUsages = computed(() => Array.isArray(detail.value.advance_usages) ? detail.value.advance_usages : []);
const summary = computed(() => detail.value.summary || {});
const paymentCompanyId = computed(() => String(
  invoices.value.find((row) => row.id_perusahaan)?.id_perusahaan
  || filters.id_perusahaan
  || ''
));
const expenseInvoiceOptions = computed(() => {
  const uniqueInvoices = new Map();
  invoices.value.forEach((invoice) => {
    const id = String(invoice.id_faktur || '');
    if (!id || uniqueInvoices.has(id)) return;
    uniqueInvoices.set(id, {
      value: id,
      label: `${invoice.no_faktur || `Faktur #${id}`} · ${invoice.nama_customer || '-'} · ${formatCurrency(invoice.total_tagihan)}`
    });
  });
  return [
    { value: '', label: 'Biaya pada LPH (tanpa faktur khusus)' },
    ...uniqueInvoices.values()
  ];
});
const expenseCoaOptions = computed(() => [
  { value: '', label: 'Pilih akun biaya (COA)' },
  ...expenseCoaRows.value.map((row) => ({
    value: String(row.id_coa || row.id || ''),
    label: `${row.nomor_akun || row.kode || '-'} · ${row.nama_akun || row.nama || 'Akun biaya'}`
  })).filter((row) => row.value)
]);
const approvedExpenseReduction = computed(() => Number(
  expenseSummary.value.total_pengurang_setoran_approved || 0
));
const expensePendingTotal = computed(() => Number(expenseSummary.value.total_pending || 0));

const paymentRows = computed(() =>
  payments.value.map((row) => {
    const depositRows = Array.isArray(row.deposit_rows) ? row.deposit_rows : [];
    const mobileAmount = Number(row.jumlah_bayar_sales || 0);
    const mobileMethod = Number(row.tipe_pembayaran_sales || 1);
    const cashDeposit = Number(
      row.setoran_tunai ?? depositRows
        .filter((deposit) => Number(deposit.tipe_setoran) === 1)
        .reduce((total, deposit) => total + Number(deposit.nominal_setoran || 0), 0)
    );
    const nonCashDeposit = Number(
      row.setoran_non_tunai ?? depositRows
        .filter((deposit) => Number(deposit.tipe_setoran) === 2)
        .reduce((total, deposit) => total + Number(deposit.nominal_setoran || 0), 0)
    );
    const totalDeposit = cashDeposit + nonCashDeposit;
    const amountForMobileMethod = mobileMethod === 1 ? cashDeposit : nonCashDeposit;
    const status = String(row.status_pencocokan || '').toUpperCase();
    const fallbackMethodMatches = mobileMethod === 1 ? nonCashDeposit <= 0.5 : cashDeposit <= 0.5;
    const fallbackAmountMatches = Math.abs(mobileAmount - amountForMobileMethod) <= 0.5;
    const hasServerMethodState = row.method_mismatch !== undefined && row.method_mismatch !== null;
    const hasServerAmountState = row.amount_matches !== undefined && row.amount_matches !== null;
    const hasServerMatchState = row.sudah_cocok !== undefined && row.sudah_cocok !== null;
    const methodMatches = hasServerMethodState
      ? !(row.method_mismatch === true || Number(row.method_mismatch) === 1)
      : fallbackMethodMatches;
    const amountMatches = hasServerAmountState
      ? row.amount_matches === true || Number(row.amount_matches) === 1
      : fallbackAmountMatches;
    // A record created by Rekap is not yet proof that Finance has received
    // the money.  Status 1 is deliberately kept as "menunggu pencatatan" in
    // the cash/non-cash menus.  Do not let the old server-side `SESUAI` flag
    // bypass that operational control on this screen.
    const deposited = depositRows.length > 0 || Number(row.jumlah_setoran_finance || 0) > 0;
    const depositRecorded = depositRows.length > 0
      && depositRows.every((deposit) => Number(deposit.status_setoran || 0) >= 2);
    const basicExactMatch = hasServerMatchState
      ? row.sudah_cocok === true || Number(row.sudah_cocok) === 1
      : deposited && methodMatches && amountMatches;
    const exactMatch = basicExactMatch && depositRecorded;
    const displayStatus = !deposited
      ? status
      : !depositRecorded
        ? 'MENUNGGU_PENCATATAN'
        : status;

    return {
      ...row,
      key: String(row.id_setoran_customer || row.id || `${row.id_sales_order || ''}-${row.tanggal_input || ''}`),
      depositRows,
      mobileAmount,
      mobileMethod,
      cashDeposit,
      nonCashDeposit,
      totalDeposit,
      amountForMobileMethod,
      amountDifference: mobileAmount - amountForMobileMethod,
      methodMatches,
      amountMatches,
      deposited,
      depositRecorded,
      exactMatch,
      status,
      displayStatus,
      depositMethodLabel: depositMethodLabel(cashDeposit, nonCashDeposit),
      proofLabel: getDepositProofLabel(row, depositRows),
      depositStageLabel: resolveDepositStageLabel(row.status_setoran, deposited, status, depositRecorded)
    };
  })
);

const pendingPaymentRows = computed(() => paymentRows.value.filter((row) => !row.deposited));
const pendingRecordingRows = computed(() => paymentRows.value.filter((row) => row.deposited && !row.depositRecorded));
const mismatchPaymentRows = computed(() => paymentRows.value.filter((row) => row.deposited && row.depositRecorded && !row.exactMatch));
const pendingPaymentTotal = computed(() => pendingPaymentRows.value.reduce((sum, row) => sum + row.mobileAmount, 0));
const pendingRecordingTotal = computed(() => pendingRecordingRows.value.reduce((sum, row) => sum + row.mobileAmount, 0));
const mismatchPaymentTotal = computed(() => mismatchPaymentRows.value.reduce((sum, row) => sum + Math.abs(row.amountDifference), 0));
const mobilePaymentsReadyForFinalization = computed(() =>
  paymentRows.value.length > 0
  // Never trust only `semua_pembayaran_sesuai` here. Older API responses
  // consider a status-1 Rekap record "sesuai" before Finance actually
  // records or receives the money.
  && paymentRows.value.every((row) => row.exactMatch && row.depositRecorded)
);
const advanceReservations = computed(() => advanceUsages.value.filter((usage) =>
  String(usage.status || '').toUpperCase() === 'RESERVED'
));
const advanceReservationsReadyForFinalization = computed(() =>
  advanceReservations.value.length > 0
  && advanceReservations.value.every((usage) => Number(usage.status_setoran || 0) >= 2)
);
const mobileFinalizationPending = computed(() => paymentRows.value.some((row) => (
  row.exactMatch
  && row.depositRecorded
  && String(row.status || '').toUpperCase() !== 'FINAL'
)));
const allDepositRows = computed(() => paymentRows.value.flatMap((row) => row.depositRows || []));
const finalizationRouteType = computed(() => {
  // One screen finalises one method at a time.  Prefer cash when both are
  // pending, then Finance can switch to non-cash for the remaining group.
  const pendingTypes = new Set(
    allDepositRows.value
      .filter((row) => Number(row.status_setoran || 0) >= 2 && Number(row.status_setoran || 0) < 3)
      .map((row) => Number(row.tipe_setoran || 0))
  );
  if (advanceReservationsReadyForFinalization.value) pendingTypes.add(2);
  return pendingTypes.has(1) ? 'cash' : 'noncash';
});
const canOpenFinalization = computed(() =>
  lphIsActive.value
  // Do not let an advance reservation bypass an unrecorded Mobile payment
  // when the LPH contains both sources.
  && (!paymentRows.value.length || mobilePaymentsReadyForFinalization.value)
  && (mobilePaymentsReadyForFinalization.value || advanceReservationsReadyForFinalization.value)
  && (mobileFinalizationPending.value || advanceReservationsReadyForFinalization.value)
);

const lphSalesRow = computed(() => {
  const idSales = detail.value.lph?.id_sales || selectedLph.value?.id_sales;
  return salesRows.value.find((row) =>
    [row.id_sales, row.sales_id, row.id]
      .filter((value) => value !== null && value !== undefined && value !== '')
      .map(String)
      .includes(String(idSales || ''))
  ) || null;
});

const paymentIdentity = computed(() => {
  const customerNames = uniqueTextValues(invoices.value.map((row) => row.nama_customer));
  const fallbackCustomers = uniqueTextValues(String(selectedLph.value?.customer_list || '').split(','));
  const customers = customerNames.length ? customerNames : fallbackCustomers;
  const payerName = detail.value.lph?.nama_sales || selectedLph.value?.nama_sales || '-';
  const payerCode = lphSalesRow.value?.kode_sales || lphSalesRow.value?.kode || detail.value.lph?.id_sales || selectedLph.value?.id_sales || '-';

  return {
    paymentDate: latestDateValue(payments.value.map((row) => row.tanggal_input))
      || detail.value.lph?.tanggal_lph
      || selectedLph.value?.tanggal_lph,
    customers,
    customerLabel: customers.length > 1 ? `${customers.length} customer / grup` : customers[0] || '-',
    customerDetail: customers.length > 1 ? customers.join(' · ') : '',
    payerCode,
    payerName,
    totalReceivable: invoices.value.reduce((total, row) => total + invoiceReceivableAmount(row), 0)
  };
});

const paymentSystemSummary = computed(() => {
  const deposits = allDepositRows.value;
  const depositCash = deposits.reduce((total, row) =>
    total + (Number(row.tipe_setoran) === 1 ? Number(row.nominal_setoran || 0) : 0), 0);
  const depositNonCash = deposits.reduce((total, row) =>
    total + (Number(row.tipe_setoran) === 2 ? Number(row.nominal_setoran || 0) : 0), 0);
  const cash = deposits.length ? depositCash : Number(summary.value.total_setoran_tunai || 0);
  const nonCash = deposits.length ? depositNonCash : Number(summary.value.total_setoran_non_tunai || 0);
  const returns = Number(summary.value.total_retur || 0);
  const creditNotes = Number(summary.value.total_credit_note || 0);
  const advanceReserved = Number(summary.value.total_uang_muka_direservasi || 0);
  const advanceFinal = Number(summary.value.total_uang_muka_final || 0);
  const evidence = uniqueTextValues(deposits.flatMap((row) => [
    row.bukti_transfer,
    row.kode_mutasi,
    row.no_referensi,
    row.referensi
  ]));
  const latestDepositDate = latestDateValue(deposits.map((row) =>
    row.tanggal_cair || row.tanggal_setoran || row.draft_tanggal_input
  ));
  const hasFinalDeposits = deposits.length > 0 && deposits.every((row) => Number(row.status_setoran || 0) >= 3);

  return {
    cash,
    nonCash,
    other: returns + creditNotes,
    returns,
    creditNotes,
    advanceReserved,
    advanceFinal,
    totalDeposit: cash + nonCash,
    // An approved controlled expense changes only this presentation/control
    // number. It must not make a source claim look exact, nor unlock
    // finalisation; the authoritative amount remains `totalDeposit`.
    netDepositControl: Math.max((cash + nonCash) - approvedExpenseReduction.value, 0),
    approvedExpenseReduction: approvedExpenseReduction.value,
    expensePending: expensePendingTotal.value,
    evidence,
    evidenceLabel: evidence.length ? evidence.join(' · ') : '-',
    latestDepositDate,
    stageLabel: hasFinalDeposits
      ? 'Setoran sudah final audit.'
      : pendingPaymentRows.value.length
        ? `Menunggu ${pendingPaymentRows.value.length} pembayaran dibuatkan setoran.`
        : pendingRecordingRows.value.length
          ? `Menunggu pencatatan/terima untuk ${pendingRecordingRows.value.length} setoran.`
          : mismatchPaymentRows.value.length
            ? `Ada ${mismatchPaymentRows.value.length} pembayaran yang perlu diperbaiki.`
            : canOpenFinalization.value
              ? 'Setoran sesuai, sudah dicatat, dan siap diteruskan ke finalisasi.'
              : 'Belum ada pembayaran Mobile Sales pada LPH ini.'
  };
});

function getInvoicePaymentRows(invoice = {}) {
  const invoiceId = String(invoice.id_faktur || '');
  const orderId = String(invoice.id_sales_order || '');
  return paymentRows.value.filter((payment) =>
    String(payment.source_id_faktur || payment.id_faktur || '') === invoiceId
    && String(payment.source_id_sales_order || payment.id_sales_order || '') === orderId
  );
}

function getInvoiceDisplayStatus(invoice = {}) {
  const relatedPayments = getInvoicePaymentRows(invoice);
  if (!relatedPayments.length) return String(invoice.status_pencocokan || '').toUpperCase();
  if (relatedPayments.some((payment) => !payment.deposited)) return 'MENUNGGU_REKAP';
  if (relatedPayments.some((payment) => !payment.depositRecorded)) return 'MENUNGGU_PENCATATAN';
  if (relatedPayments.some((payment) => !payment.exactMatch)) return 'SELISIH';
  if (relatedPayments.every((payment) => payment.status === 'FINAL')) return 'FINAL';
  return 'SESUAI';
}

const invoiceTableRows = computed(() => invoices.value.map((row, index) => {
  const relatedPayments = getInvoicePaymentRows(row);
  const displayStatus = getInvoiceDisplayStatus(row);
  const depositAmount = Number(row.setoran_tunai || 0) + Number(row.setoran_non_tunai || 0);
  return {
    ...row,
    sequence: index + 1,
    invoice_date_label: formatDate(row.tanggal_faktur || row.tanggal_order),
    due_date_label: formatDate(row.tanggal_jatuh_tempo),
    tagihan_label: formatCurrency(row.total_tagihan),
    payment_label: formatCurrency(row.total_bayar_mobile),
    outstanding_label: formatCurrency(row.sisa_tagihan),
    deposit_label: formatCurrency(depositAmount),
    status_pencocokan: displayStatus,
    payment_count_label: relatedPayments.length
      ? `${formatNumber(relatedPayments.filter((payment) => payment.exactMatch).length)}/${formatNumber(relatedPayments.length)} pembayaran siap finalisasi`
      : 'Belum ada pembayaran Mobile Sales',
    status_label: resolveReconciliationStatus(displayStatus)
  };
}));

const summaryCards = computed(() => [
  { label: 'Faktur dalam LPH', value: formatNumber(summary.value.jumlah_faktur || invoices.value.length), tone: 'slate' },
  { label: 'Total Tagihan', value: formatCurrency(summary.value.total_tagihan), tone: 'sky' },
  { label: 'Bayar Mobile Sales', value: formatCurrency(summary.value.total_bayar_mobile), tone: 'violet' },
  { label: 'Setoran Tunai', value: formatCurrency(summary.value.total_setoran_tunai), tone: 'emerald' },
  { label: 'Setoran Non Tunai', value: formatCurrency(summary.value.total_setoran_non_tunai), tone: 'amber' },
  {
    label: pendingRecordingRows.value.length ? 'Menunggu Dicatat' : 'Belum Direkap',
    value: formatNumber(pendingRecordingRows.value.length || pendingPaymentRows.value.length),
    tone: pendingRecordingRows.value.length ? 'amber' : 'rose'
  }
]);

const workflowSteps = computed(() => {
  const hasMobilePayment = paymentRows.value.length > 0;
  const hasDeposit = paymentRows.value.some((row) => row.deposited);
  const allPaymentsRecapped = hasMobilePayment && paymentRows.value.every((row) => row.deposited);
  const allDepositsRecorded = hasMobilePayment && paymentRows.value.every((row) => row.depositRecorded);
  const allMatched = canOpenFinalization.value;
  // A finalized advance must never hide an ordinary payment that is still
  // pending.  When both sources exist, each group has to complete its own
  // audit/finalization stage before the workflow can say "Selesai".
  const allFinal = (paymentRows.value.length > 0 || advanceUsages.value.length > 0)
    && (!paymentRows.value.length || paymentRows.value.every((row) => row.status === 'FINAL'))
    && (!advanceUsages.value.length || advanceUsages.value.every((usage) => String(usage.status || '').toUpperCase() === 'FINALIZED'));

  return [
    { number: '01', title: 'Mobile Sales Bayar', note: 'Sales mencatat nominal dan metode bayar pelanggan.', state: hasMobilePayment ? 'done' : 'waiting' },
    { number: '02', title: 'Rekap Pembayaran', note: 'Pembayaran Mobile Sales direkap sebagai sumber setoran.', state: allPaymentsRecapped ? 'done' : hasDeposit ? 'current' : hasMobilePayment ? 'next' : 'waiting', route: 'finance-recap' },
    { number: '03', title: 'Pilih Metode', note: 'Setoran dipisahkan menjadi Tunai atau Non Tunai.', state: allPaymentsRecapped ? 'done' : hasMobilePayment ? 'next' : 'waiting' },
    { number: '04', title: 'Setoran', note: 'Tunai atau transfer harus dicatat/diterima dan bukti dilampirkan.', state: allDepositsRecorded ? 'done' : allPaymentsRecapped ? 'current' : 'waiting' },
    { number: '05', title: 'Pembayaran Tagihan', note: 'Halaman ini mencocokkan LPH, faktur, nominal, dan metode.', state: allMatched ? 'done' : filters.id_lph ? 'current' : 'waiting' },
    { number: '06', title: 'Finalisasi', note: 'Finalisasi hanya setelah seluruh pencocokan sesuai.', state: allFinal ? 'done' : allMatched ? 'next' : 'waiting', route: 'finance-deposit-finalization' }
  ];
});

function createEmptyDetail() {
  return { lph: null, invoices: [], payments: [], advance_usages: [], summary: {} };
}

function createEmptyExpenseSummary() {
  return {
    total_rows: 0,
    total_pending: 0,
    total_approved: 0,
    total_pengurang_setoran_approved: 0,
    total_informatif_approved: 0
  };
}

function formatNumber(value) {
  return numberFormatter.format(Number(value || 0));
}

function formatCurrency(value) {
  return `Rp ${numberFormatter.format(Number(value || 0))}`;
}

function formatSignedCurrency(value) {
  const amount = Number(value || 0);
  if (Math.abs(amount) <= 0.5) return formatCurrency(0);
  return `${amount > 0 ? '+' : '-'} ${formatCurrency(Math.abs(amount))}`;
}

function formatDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10);
  return date.toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' });
}

function uniqueTextValues(values = []) {
  return [...new Set(
    values
      .flatMap((value) => String(value || '').split(','))
      .map((value) => value.trim())
      .filter(Boolean)
  )];
}

function latestDateValue(values = []) {
  const datedValues = values
    .filter(Boolean)
    .map((value) => ({ value, timestamp: new Date(value).getTime() }))
    .filter((item) => !Number.isNaN(item.timestamp));

  if (!datedValues.length) return null;
  return datedValues.sort((left, right) => right.timestamp - left.timestamp)[0].value;
}

function invoiceReceivableAmount(row = {}) {
  return Math.max(
    Number(row.total_tagihan || 0)
      - Number(row.nominal_retur || 0)
      - Number(row.total_credit_note || 0),
    0
  );
}

function paymentMethodLabel(value) {
  return Number(value) === 2 ? 'Non Tunai / Transfer' : 'Tunai';
}

function depositMethodLabel(cashAmount, nonCashAmount) {
  const hasCash = Number(cashAmount || 0) > 0.5;
  const hasNonCash = Number(nonCashAmount || 0) > 0.5;
  if (hasCash && hasNonCash) return 'Tunai + Non Tunai';
  if (hasNonCash) return 'Non Tunai / Transfer';
  if (hasCash) return 'Tunai';
  return 'Belum ada setoran';
}

function getDepositProofLabel(row = {}, deposits = []) {
  const evidence = uniqueTextValues([
    row.bukti_transfer,
    row.kode_mutasi,
    row.no_referensi,
    row.referensi,
    row.kode_setoran,
    ...deposits.flatMap((deposit) => [
      deposit.bukti_transfer,
      deposit.kode_mutasi,
      deposit.no_referensi,
      deposit.referensi,
      deposit.kode_setoran,
      deposit.id_setoran ? `Setoran #${deposit.id_setoran}` : ''
    ])
  ]);
  return evidence.length ? evidence.join(' · ') : '-';
}

function resolveDepositStageLabel(value, deposited = false, reconciliationStatus = '', depositRecorded = false) {
  if (!deposited) return 'Belum direkap menjadi setoran';

  // A status-1 record is created by Rekap but still has not been received
  // (cash) or verified against transfer evidence (non-cash).  It must remain
  // visibly pending even when a legacy reconciliation response says SESUAI.
  if (!depositRecorded) return 'Menunggu pencatatan / penerimaan';

  if (reconciliationStatus === 'FINAL') return 'Final audit';
  if (reconciliationStatus === 'SESUAI') return 'Sesuai · menunggu finalisasi';
  if (reconciliationStatus === 'SELISIH') return 'Perlu koreksi';
  const stage = Number(value || 0);
  if (stage >= 3) return 'Final';
  if (stage === 2) return 'Diterima / diverifikasi';
  return 'Menunggu pencatatan / penerimaan';
}

function lphStatusLabel(value) {
  const status = String(value || '').trim().toUpperCase();
  if (status === 'AKTIF') return 'Aktif di sales';
  if (status === 'MENUNGGU_PENERIMAAN') return 'Menunggu diterima sales';
  if (status === 'DIKEMBALIKAN') return 'Dikembalikan sales';
  return status || '-';
}

function resolveReconciliationStatus(value) {
  const status = String(value || '').toUpperCase();
  if (status === 'MENUNGGU_REKAP') return 'Belum ada setoran';
  if (status === 'MENUNGGU_PENCATATAN') return 'Menunggu pencatatan setoran';
  if (status === 'MENUNGGU_FINALISASI_UANG_MUKA') return 'Uang muka siap difinalisasi';
  if (status === 'SESUAI') return 'Sesuai · menunggu finalisasi';
  if (status === 'FINAL') return 'Setoran sudah final';
  if (status === 'SELISIH') return 'Ada selisih';
  if (status === 'BELUM_ADA_BAYAR') return 'Belum ada pembayaran';
  return status || '-';
}

function reconciliationStatusClass(value) {
  const status = String(value || '').toUpperCase();
  if (status === 'FINAL') return 'status-final';
  if (status === 'SESUAI') return 'status-matched';
  if (status === 'SELISIH') return 'status-mismatch';
  if (status === 'MENUNGGU_PENCATATAN') return 'status-pending';
  if (status === 'MENUNGGU_REKAP') return 'status-pending';
  if (status === 'MENUNGGU_FINALISASI_UANG_MUKA') return 'status-pending';
  return 'status-neutral';
}

function selectedSalesRow() {
  return salesRows.value.find((row) =>
    [row.id_sales, row.sales_id, row.id]
      .filter((value) => value !== null && value !== undefined && value !== '')
      .map(String)
      .includes(String(filters.id_sales || ''))
  ) || null;
}

function clearDetail() {
  detail.value = createEmptyDetail();
  expenseRows.value = [];
  expenseSummary.value = createEmptyExpenseSummary();
  expenseCoaRows.value = [];
  resetExpenseForm();
}

function clearSelectedLph() {
  filters.id_lph = '';
  clearDetail();
}

function onCompanyChanged(value) {
  filters.id_perusahaan = String(value || '');
  const branchIsAvailable = branchOptions.value.some((option) => String(option.value) === String(filters.id_cabang));
  if (!branchIsAvailable) filters.id_cabang = '';
  filters.id_sales = '';
  clearSelectedLph();
}

function onBranchChanged(value) {
  filters.id_cabang = String(value || '');
  const salesIsAvailable = salesOptions.value.some((option) => String(option.value) === String(filters.id_sales));
  if (!salesIsAvailable) filters.id_sales = '';
  clearSelectedLph();
}

function onSalesChanged(value) {
  filters.id_sales = String(value || '');
  clearSelectedLph();
}

function buildLphParams() {
  const sales = selectedSalesRow();
  return {
    id_perusahaan: filters.id_perusahaan || undefined,
    id_cabang: filters.id_cabang || undefined,
    id_sales: sales?.id_sales || sales?.sales_id || filters.id_sales || undefined,
    sales_user_id: sales?.id_user || sales?.user_id || undefined,
    status: filters.status || undefined,
    search: filters.search?.trim() || undefined,
    limit: 500
  };
}

async function loadMasters() {
  loading.masters = true;
  try {
    const [companiesResponse, branchesResponse, salesResponse] = await Promise.all([
      getCompanies(),
      getBranches(),
      getSales()
    ]);
    companyRows.value = normalizeList(unwrapResponse(companiesResponse));
    branchRows.value = normalizeList(unwrapResponse(branchesResponse));
    salesRows.value = normalizeList(unwrapResponse(salesResponse));
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Pilihan perusahaan, cabang, atau sales belum dapat dimuat.');
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
    if (!preserveSelection || !selectedExists) {
      if (!selectedExists) clearSelectedLph();
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
      advance_usages: Array.isArray(payload.advance_usages) ? payload.advance_usages : [],
      summary: payload.summary || {}
    };
    // The adjustment document is deliberately independent from the payment
    // detail API so old deployments fail clearly until the additive migration
    // is applied, without hiding invoice/setoran data that is still useful.
    await Promise.allSettled([
      loadPaymentExpenseAdjustments({ quiet: true }),
      loadExpenseCoaOptions({ quiet: true })
    ]);
  } catch (error) {
    clearDetail();
    errorMessage.value = normalizeError(error, 'Detail tagihan LPH belum dapat dimuat.');
  } finally {
    loading.detail = false;
  }
}

function resetExpenseForm() {
  expenseForm.id_faktur = '';
  expenseForm.id_coa = '';
  expenseForm.kategori = 'ADMIN_TRANSFER';
  expenseForm.impact_direction = 'PENGURANG_SETORAN';
  expenseForm.nominal = '';
  expenseForm.catatan = '';
}

async function loadPaymentExpenseAdjustments({ quiet = false } = {}) {
  if (!filters.id_lph) {
    expenseRows.value = [];
    expenseSummary.value = createEmptyExpenseSummary();
    return;
  }
  loading.expenses = true;
  try {
    const response = await getPaymentExpenseAdjustments({ id_lph: filters.id_lph });
    const payload = unwrapResponse(response) || {};
    expenseRows.value = normalizeList(payload.data ?? payload);
    expenseSummary.value = {
      ...createEmptyExpenseSummary(),
      ...(payload.summary || {})
    };
  } catch (error) {
    expenseRows.value = [];
    expenseSummary.value = createEmptyExpenseSummary();
    if (!quiet) {
      errorMessage.value = normalizeError(error, 'Penyesuaian biaya belum dapat dimuat.');
    }
  } finally {
    loading.expenses = false;
  }
}

async function loadExpenseCoaOptions({ quiet = false } = {}) {
  if (!paymentCompanyId.value) {
    expenseCoaRows.value = [];
    return;
  }
  try {
    const response = await getCoaCatalog({
      id_perusahaan: paymentCompanyId.value,
      id_cabang: filters.id_cabang || undefined,
      is_active: true,
      limit: 200
    });
    expenseCoaRows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    expenseCoaRows.value = [];
    if (!quiet) {
      errorMessage.value = normalizeError(error, 'Daftar COA biaya belum dapat dimuat.');
    }
  }
}

async function submitPaymentExpenseAdjustment() {
  feedback.value = '';
  errorMessage.value = '';
  if (!filters.id_lph || !lphIsActive.value) {
    errorMessage.value = 'LPH harus aktif di sales sebelum biaya pembayaran dicatat.';
    return;
  }
  if (!expenseForm.id_coa || Number(expenseForm.nominal || 0) <= 0 || String(expenseForm.catatan || '').trim().length < 3) {
    errorMessage.value = 'Pilih COA, isi nominal lebih dari Rp 0, dan isi catatan minimal 3 karakter.';
    return;
  }
  loading.expenseSubmit = true;
  try {
    const response = await createPaymentExpenseAdjustment({
      id_lph: Number(filters.id_lph),
      id_faktur: expenseForm.id_faktur ? Number(expenseForm.id_faktur) : undefined,
      id_coa: Number(expenseForm.id_coa),
      kategori: expenseForm.kategori,
      impact_direction: expenseForm.impact_direction,
      nominal: Number(expenseForm.nominal),
      catatan: String(expenseForm.catatan).trim()
    });
    const payload = unwrapResponse(response) || {};
    feedback.value = payload.message || 'Penyesuaian biaya tersimpan dan menunggu approval Finance.';
    resetExpenseForm();
    await loadPaymentExpenseAdjustments();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Penyesuaian biaya gagal disimpan.');
  } finally {
    loading.expenseSubmit = false;
  }
}

async function approveExpenseAdjustment(row) {
  const id = Number(row?.id || 0);
  if (!id) return;
  feedback.value = '';
  errorMessage.value = '';
  loading.expenseActionId = String(id);
  try {
    const response = await approvePaymentExpenseAdjustment(id, {});
    const payload = unwrapResponse(response) || {};
    feedback.value = payload.message || 'Penyesuaian biaya disetujui Finance.';
    await loadPaymentExpenseAdjustments();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Approval penyesuaian biaya gagal.');
  } finally {
    loading.expenseActionId = '';
  }
}

async function voidExpenseAdjustment(row) {
  const id = Number(row?.id || 0);
  if (!id) return;
  const reason = window.prompt('Alasan pembatalan penyesuaian biaya (minimal 5 karakter):');
  if (reason === null) return;
  if (String(reason).trim().length < 5) {
    errorMessage.value = 'Alasan pembatalan biaya wajib diisi minimal 5 karakter.';
    return;
  }
  feedback.value = '';
  errorMessage.value = '';
  loading.expenseActionId = String(id);
  try {
    const response = await voidPaymentExpenseAdjustment(id, { void_reason: String(reason).trim() });
    const payload = unwrapResponse(response) || {};
    feedback.value = payload.message || 'Penyesuaian biaya dibatalkan.';
    await loadPaymentExpenseAdjustments();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Pembatalan penyesuaian biaya gagal.');
  } finally {
    loading.expenseActionId = '';
  }
}

async function chooseLph(value) {
  filters.id_lph = String(value || '');
  await loadLphDetail();
}

function openPaymentRecap() {
  router.push({
    name: 'finance-recap',
    query: {
      id_lph: filters.id_lph || undefined,
      id_sales: detail.value.lph?.id_sales || selectedLph.value?.id_sales || undefined
    }
  });
}

function openCashDeposit() {
  router.push({ name: 'finance-cash-deposits', query: { id_lph: filters.id_lph || undefined } });
}

function openNonCashDeposit() {
  router.push({ name: 'finance-noncash-deposits', query: { id_lph: filters.id_lph || undefined } });
}

function openFinalization() {
  if (!canOpenFinalization.value) {
    errorMessage.value = pendingRecordingRows.value.length
      ? 'Finalisasi belum dapat dibuka. Setoran yang sudah direkap harus dicatat/diterima terlebih dahulu di menu Setoran Tunai atau Setoran Non Tunai.'
      : 'Finalisasi belum dapat dibuka. Setiap pembayaran LPH harus sudah memiliki setoran dengan nominal dan metode yang sesuai.';
    return;
  }
  router.push({
    name: 'finance-deposit-finalization',
    query: {
      id_lph: filters.id_lph || undefined,
      type: finalizationRouteType.value
    }
  });
}

function resetFilters() {
  filters.id_perusahaan = shouldLockBusinessScope.value ? String(fallbackCompanyId.value || '') : '';
  filters.id_cabang = shouldLockBusinessScope.value ? String(fallbackBranchId.value || '') : '';
  filters.id_sales = shouldLockSalesScope.value ? String(fallbackSalesId.value || '') : '';
  filters.status = 'AKTIF';
  filters.search = '';
  clearSelectedLph();
  lphRows.value = [];
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

onMounted(initialize);
</script>

<template>
  <div class="payment-page space-y-6">
    <PageHeader
      title="Pembayaran Tagihan"
      description="Tahap verifikasi setelah setoran: cocokkan faktur LPH, pembayaran Mobile Sales, nominal, metode, dan bukti setoran sebelum finalisasi."
    >
      <div class="flex flex-wrap gap-2">
        <button class="button-secondary" :disabled="loading.lphs" @click="loadLphs()">
          {{ loading.lphs ? 'Memuat...' : 'Muat Ulang' }}
        </button>
        <button class="button-primary" :disabled="loading.masters || loading.lphs" @click="loadLphs({ preserveSelection: false })">
          Tampilkan LPH
        </button>
      </div>
    </PageHeader>

    <section class="panel p-5">
      <div class="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <p class="section-eyebrow">01 · Scope dan LPH</p>
          <h2 class="section-title">Pilih LPH sebagai sumber tagihan</h2>
          <p class="section-description">Faktur yang tampil hanya berasal dari LPH pilihan. Perusahaan dipilih lebih dulu, lalu cabang dan sales.</p>
        </div>
        <span class="scope-note">{{ loading.masters ? 'Memuat master...' : `${formatNumber(lphRows.length)} LPH ditemukan` }}</span>
      </div>

      <div class="scope-grid">
        <AppSearchSelect
          v-model="filters.id_perusahaan"
          label="Perusahaan"
          placeholder="Semua perusahaan"
          :options="companyOptions"
          :disabled="shouldLockBusinessScope && !!fallbackCompanyId"
          @update:model-value="onCompanyChanged"
        />
        <AppSearchSelect
          v-model="filters.id_cabang"
          label="Cabang"
          placeholder="Semua cabang"
          :options="branchOptions"
          :disabled="!filters.id_perusahaan || (shouldLockBusinessScope && !!fallbackBranchId)"
          @update:model-value="onBranchChanged"
        />
        <AppSearchSelect
          v-model="filters.id_sales"
          label="Sales"
          placeholder="Semua sales"
          :options="salesOptions"
          :disabled="shouldLockSalesScope && !!fallbackSalesId"
          @update:model-value="onSalesChanged"
        />
        <AppSearchSelect
          v-model="filters.status"
          label="Status LPH"
          placeholder="Pilih status"
          :options="[
            { value: '', label: 'Semua status' },
            { value: 'AKTIF', label: 'Aktif di sales' },
            { value: 'MENUNGGU_PENERIMAAN', label: 'Menunggu diterima sales' },
            { value: 'DIKEMBALIKAN', label: 'Dikembalikan sales' }
          ]"
          @update:model-value="clearSelectedLph"
        />
        <AppFormField v-model="filters.search" label="Cari LPH" placeholder="Kode LPH atau nama sales" />
        <div class="flex items-end gap-2">
          <button class="button-primary flex-1" :disabled="loading.lphs" @click="loadLphs({ preserveSelection: false })">Cari LPH</button>
          <button class="button-secondary" title="Reset filter" @click="resetFilters">Reset</button>
        </div>
      </div>

      <div class="mt-5 border-t border-slate-200 pt-5 dark:border-slate-800">
        <AppSearchSelect
          v-model="filters.id_lph"
          label="LPH Terpilih"
          placeholder="Cari kode LPH, sales, atau tanggal"
          :options="lphOptions"
          :loading="loading.lphs"
          :disabled="!lphRows.length"
          empty-text="Tidak ada LPH pada filter ini."
          @update:model-value="chooseLph"
        />
      </div>
    </section>

    <section class="flow-grid" aria-label="Alur pembayaran wajib">
      <article v-for="step in workflowSteps" :key="step.number" class="flow-card" :class="`flow-card--${step.state}`">
        <div class="flow-card-header"><span>{{ step.number }}</span><em>{{ step.state === 'done' ? 'Selesai' : step.state === 'current' ? 'Tahap ini' : step.state === 'next' ? 'Berikutnya' : 'Menunggu' }}</em></div>
        <h3>{{ step.title }}</h3>
        <p>{{ step.note }}</p>
      </article>
    </section>

    <section v-if="feedback" class="alert-success">{{ feedback }}</section>
    <section v-if="errorMessage" class="alert-error">{{ errorMessage }}</section>

    <template v-if="!filters.id_lph">
      <section class="empty-state panel">
        <div class="empty-state-icon">LPH</div>
        <h2>Pilih LPH untuk memulai pembayaran</h2>
        <p>Pilih perusahaan, cabang, dan sales bila diperlukan; kemudian pilih satu LPH. Sistem akan menampilkan seluruh faktur dan pembayaran Mobile Sales dalam dokumen itu.</p>
      </section>
    </template>

    <template v-else>
      <section class="lph-context panel" :class="{ 'lph-context--inactive': !lphIsActive }">
        <div class="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p class="section-eyebrow">LPH Aktif di Pembayaran</p>
            <h2 class="lph-context-title">{{ detail.lph?.kode_lph || selectedLph?.kode_lph || `LPH-${filters.id_lph}` }}</h2>
            <p class="lph-context-copy">
              Sales: <strong>{{ detail.lph?.nama_sales || selectedLph?.nama_sales || '-' }}</strong><span class="separator">·</span>Tanggal LPH: <strong>{{ formatDate(detail.lph?.tanggal_lph || selectedLph?.tanggal_lph) }}</strong>
            </p>
          </div>
          <div class="text-right">
            <span class="status-pill" :class="lphIsActive ? 'status-matched' : 'status-pending'">{{ lphStatusLabel(detail.lph?.status_dokumen || selectedLph?.status_dokumen) }}</span>
            <p v-if="!lphIsActive" class="lph-context-warning">Pembayaran tidak dapat direkap sebelum sales menekan <strong>Terima LPH</strong> pada Mobile Sales.</p>
          </div>
        </div>
      </section>

      <section class="legacy-payment-header panel" aria-label="Identitas pembayaran LPH">
        <div class="legacy-section-heading">
          <div>
            <p class="section-eyebrow">Identitas pembayaran</p>
            <h2 class="section-title">Ringkasan pembayaran dari LPH</h2>
            <p class="section-description">Seluruh informasi ini ditarik dari LPH, faktur, pembayaran Mobile Sales, dan setoran yang telah dibuat. Tidak ada nilai yang bisa diubah dari halaman ini.</p>
          </div>
          <span class="status-pill" :class="canOpenFinalization ? 'status-matched' : 'status-pending'">
            {{ canOpenFinalization ? 'Siap finalisasi' : pendingRecordingRows.length ? 'Menunggu pencatatan setoran' : 'Menunggu pencocokan' }}
          </span>
        </div>

        <dl class="legacy-identity-grid">
          <div class="legacy-info-cell">
            <dt>Tanggal Bayar</dt>
            <dd>{{ formatDate(paymentIdentity.paymentDate) }}</dd>
            <small>Tanggal input pembayaran Mobile Sales</small>
          </div>
          <div class="legacy-info-cell">
            <dt>Customer / Grup</dt>
            <dd>{{ paymentIdentity.customerLabel }}</dd>
            <small>{{ paymentIdentity.customerDetail || 'Customer pada faktur LPH' }}</small>
          </div>
          <div class="legacy-info-cell">
            <dt>Kode / Nama Pembayar</dt>
            <dd>{{ paymentIdentity.payerCode }} · {{ paymentIdentity.payerName }}</dd>
            <small>Sales pemegang LPH</small>
          </div>
          <div class="legacy-info-cell legacy-info-cell--total">
            <dt>Total Piutang</dt>
            <dd>{{ formatCurrency(paymentIdentity.totalReceivable) }}</dd>
            <small>Tagihan setelah retur dan credit note</small>
          </div>
        </dl>
      </section>

      <section class="legacy-payment-system panel" aria-label="Sistem pembayaran LPH">
        <div class="legacy-section-heading">
          <div>
            <p class="section-eyebrow">Sistem pembayaran</p>
            <h2 class="section-title">Ringkasan setoran yang sudah tercatat</h2>
            <p class="section-description">Nilai Cash dan Non Cash adalah setoran finance yang telah terhubung langsung dengan pembayaran Mobile Sales pada LPH ini.</p>
          </div>
          <button class="button-secondary" :disabled="loading.detail" @click="loadLphDetail">{{ loading.detail ? 'Memuat...' : 'Perbarui Data' }}</button>
        </div>

        <div class="legacy-method-grid">
          <article class="legacy-method-card legacy-method-card--cash">
            <p>Cash</p>
            <strong>{{ formatCurrency(paymentSystemSummary.cash) }}</strong>
            <small>Setoran Tunai terhubung</small>
          </article>
          <article class="legacy-method-card legacy-method-card--noncash">
            <p>Non Cash</p>
            <strong>{{ formatCurrency(paymentSystemSummary.nonCash) }}</strong>
            <small>Transfer / mutasi bank terhubung</small>
          </article>
          <article class="legacy-method-card legacy-method-card--advance">
            <p>Uang Muka Customer</p>
            <strong>{{ formatCurrency(paymentSystemSummary.advanceReserved + paymentSystemSummary.advanceFinal) }}</strong>
            <small>
              {{ paymentSystemSummary.advanceFinal
                ? `Final ${formatCurrency(paymentSystemSummary.advanceFinal)}`
                : advanceReservationsReadyForFinalization
                  ? 'Siap finalisasi setoran'
                  : 'Menunggu finalisasi setoran' }}
              <template v-if="paymentSystemSummary.advanceReserved"> · Reservasi {{ formatCurrency(paymentSystemSummary.advanceReserved) }}</template>
            </small>
          </article>
          <article class="legacy-method-card legacy-method-card--other">
            <p>Retur / Credit Note</p>
            <strong>{{ formatCurrency(paymentSystemSummary.other) }}</strong>
            <small>Retur {{ formatCurrency(paymentSystemSummary.returns) }} · CN {{ formatCurrency(paymentSystemSummary.creditNotes) }}</small>
          </article>
        </div>

        <dl class="legacy-system-grid">
          <div class="legacy-info-cell">
            <dt>No Bukti</dt>
            <dd>{{ paymentSystemSummary.evidenceLabel }}</dd>
            <small>Referensi setoran atau mutasi bank</small>
          </div>
          <div class="legacy-info-cell">
            <dt>Tanggal Cair</dt>
            <dd>{{ formatDate(paymentSystemSummary.latestDepositDate) }}</dd>
            <small>Tanggal setoran yang tercatat</small>
          </div>
          <div class="legacy-info-cell">
            <dt>Keterangan</dt>
            <dd>{{ paymentSystemSummary.stageLabel }}</dd>
            <small>Hasil pemeriksaan otomatis</small>
          </div>
          <div class="legacy-info-cell legacy-info-cell--total">
            <dt>Total Rp</dt>
            <dd>{{ formatCurrency(paymentSystemSummary.totalDeposit) }}</dd>
            <small>Total setoran finance yang terhubung</small>
          </div>
        </dl>
      </section>

      <section class="expense-adjustment panel" aria-label="Penyesuaian biaya terkontrol">
        <div class="legacy-section-heading">
          <div>
            <p class="section-eyebrow">Kontrol biaya / lain-lain</p>
            <h2 class="section-title">Penyesuaian biaya terkontrol</h2>
            <p class="section-description">Meterai, biaya admin transfer, pembulatan, atau biaya lain dicatat dengan COA dan approval Finance. Baris ini tidak mengubah pembayaran Mobile Sales, nominal faktur, atau status finalisasi.</p>
          </div>
          <button class="button-secondary" :disabled="loading.expenses" @click="loadPaymentExpenseAdjustments()">
            {{ loading.expenses ? 'Memuat...' : 'Perbarui Biaya' }}
          </button>
        </div>

        <div class="expense-control-summary">
          <div>
            <span>Pengurang setoran disetujui</span>
            <strong>{{ formatCurrency(paymentSystemSummary.approvedExpenseReduction) }}</strong>
          </div>
          <div>
            <span>Netto kontrol setoran</span>
            <strong>{{ formatCurrency(paymentSystemSummary.netDepositControl) }}</strong>
          </div>
          <div>
            <span>Menunggu approval</span>
            <strong>{{ formatCurrency(paymentSystemSummary.expensePending) }}</strong>
          </div>
        </div>
        <p class="expense-policy-note">Pengurang setoran hanya untuk angka kontrol/review Finance setelah disetujui. Nominal setoran sumber tetap harus cocok penuh sebelum tombol finalisasi dapat dibuka.</p>

        <div class="table-shell expense-table-shell">
          <table>
            <thead><tr><th>Kategori</th><th>COA</th><th>Faktur</th><th>Nominal</th><th>Arah</th><th>Status / Audit</th><th>Aksi</th></tr></thead>
            <tbody>
              <tr v-if="loading.expenses"><td colspan="7" class="table-empty">Memuat penyesuaian biaya...</td></tr>
              <tr v-else-if="!expenseRows.length"><td colspan="7" class="table-empty">Belum ada penyesuaian biaya untuk LPH ini.</td></tr>
              <tr v-for="row in expenseRows" v-else :key="row.id">
                <td><strong>{{ row.kategori || '-' }}</strong><small>{{ row.catatan || '-' }}</small></td>
                <td><strong>{{ row.nomor_akun || '-' }}</strong><small>{{ row.nama_akun || '-' }}</small></td>
                <td><strong>{{ row.no_faktur || 'LPH' }}</strong><small>{{ row.no_order || 'Tanpa faktur khusus' }}</small></td>
                <td><strong>{{ formatCurrency(row.nominal) }}</strong></td>
                <td><span class="status-pill" :class="row.impact_direction === 'PENGURANG_SETORAN' ? 'status-pending' : 'status-neutral'">{{ row.impact_label || row.impact_direction }}</span></td>
                <td><span class="status-pill" :class="row.status === 'APPROVED' ? 'status-matched' : row.status === 'VOID' ? 'status-neutral' : 'status-pending'">{{ row.status_label || row.status }}</span><small v-if="row.approved_by_name">Disetujui: {{ row.approved_by_name }}</small><small v-else-if="row.created_by_name">Dibuat: {{ row.created_by_name }}</small></td>
                <td>
                  <div class="flex flex-wrap gap-2">
                    <button v-if="row.status === 'PENDING_APPROVAL'" class="button-secondary expense-action" :disabled="loading.expenseActionId === String(row.id)" @click="approveExpenseAdjustment(row)">Setujui</button>
                    <button v-if="row.status !== 'VOID'" class="button-secondary expense-action" :disabled="loading.expenseActionId === String(row.id)" @click="voidExpenseAdjustment(row)">Batalkan</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <form class="expense-entry-form" @submit.prevent="submitPaymentExpenseAdjustment">
          <AppSearchSelect v-model="expenseForm.id_faktur" label="Faktur terkait" placeholder="Biaya tingkat LPH" :options="expenseInvoiceOptions" />
          <AppSearchSelect v-model="expenseForm.id_coa" label="Akun biaya (COA)" placeholder="Pilih akun biaya" :options="expenseCoaOptions" :loading="loading.detail" empty-text="COA biaya belum tersedia pada scope LPH." />
          <label class="expense-field"><span>Kategori</span><select v-model="expenseForm.kategori"><option value="METERAI">Meterai</option><option value="ADMIN_TRANSFER">Admin transfer</option><option value="PEMBULATAN">Pembulatan</option><option value="LAINNYA">Lain-lain</option></select></label>
          <label class="expense-field"><span>Arah kontrol</span><select v-model="expenseForm.impact_direction"><option value="PENGURANG_SETORAN">Pengurang kontrol setoran</option><option value="INFORMATIF">Informatif (tanpa pengaruh)</option></select></label>
          <label class="expense-field"><span>Nominal</span><input v-model="expenseForm.nominal" min="1" step="0.01" type="number" inputmode="decimal" placeholder="0" /></label>
          <label class="expense-field expense-field--wide"><span>Catatan</span><textarea v-model="expenseForm.catatan" rows="2" placeholder="Contoh: biaya admin transfer bank pada setoran LPH" /></label>
          <div class="expense-entry-action"><button class="button-primary" type="submit" :disabled="loading.expenseSubmit || !lphIsActive">{{ loading.expenseSubmit ? 'Menyimpan...' : 'Tambah Penyesuaian Biaya' }}</button><small>Setelah disimpan, biaya berstatus menunggu approval Finance.</small></div>
        </form>
      </section>

      <section class="summary-grid">
        <article v-for="card in summaryCards" :key="card.label" class="summary-card" :class="`summary-card--${card.tone}`"><p>{{ card.label }}</p><strong>{{ card.value }}</strong></article>
      </section>

      <section class="panel p-5">
        <div class="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <p class="section-eyebrow">02 · Faktur LPH</p>
            <h2 class="section-title">Rincian faktur pembayaran</h2>
            <p class="section-description">Format ringkas mengikuti informasi pembayaran legacy. Kolom Pembayaran berasal dari Mobile Sales, sementara Jumlah Bayar menunjukkan setoran finance yang benar-benar terhubung.</p>
          </div>
          <button class="button-secondary" :disabled="loading.detail" @click="loadLphDetail">{{ loading.detail ? 'Memuat...' : 'Muat Detail' }}</button>
        </div>

        <div class="table-shell table-shell--legacy">
          <table>
            <thead><tr><th>No</th><th># Faktur</th><th>Tanggal Faktur</th><th>Jatuh Tempo</th><th>Tagihan</th><th>Pembayaran</th><th>Sisa Piutang</th><th>Jumlah Bayar</th></tr></thead>
            <tbody>
              <tr v-if="loading.detail"><td colspan="8" class="table-empty">Memuat detail LPH...</td></tr>
              <tr v-else-if="!invoiceTableRows.length"><td colspan="8" class="table-empty">Belum ada faktur penjualan di LPH ini.</td></tr>
              <tr v-for="row in invoiceTableRows" v-else :key="row.id_faktur || row.id_sales_order">
                <td>{{ row.sequence }}</td>
                <td><strong>{{ row.no_faktur || '-' }}</strong><small>SO {{ row.no_order || row.id_sales_order || '-' }} · {{ row.nama_customer || '-' }}</small></td>
                <td>{{ row.invoice_date_label }}</td>
                <td>{{ row.due_date_label }}</td>
                <td>{{ row.tagihan_label }}</td>
                <td><strong>{{ row.payment_label }}</strong><small>{{ row.payment_count_label }}</small></td>
                <td>{{ row.outstanding_label }}</td>
                <td><strong>{{ row.deposit_label }}</strong><small><span class="status-pill" :class="reconciliationStatusClass(row.status_pencocokan)">{{ row.status_label }}</span></small></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel p-5">
        <div class="mb-5 flex flex-wrap items-start justify-between gap-3">
          <div>
            <p class="section-eyebrow">05 · Pembayaran Tagihan</p>
            <h2 class="section-title">Verifikasi setoran terhadap pembayaran dan faktur LPH</h2>
            <p class="section-description">Halaman ini bersifat pemeriksaan. Setoran harus dibuat lebih dahulu melalui Rekap Pembayaran lalu menu Setoran Tunai atau Setoran Non Tunai; halaman ini tidak membuat setoran baru.</p>
          </div>
          <div class="flex flex-wrap gap-2">
            <button class="button-secondary" @click="openPaymentRecap">Buka Rekap Pembayaran</button>
            <button class="button-secondary" @click="openCashDeposit">Setoran Tunai</button>
            <button class="button-secondary" @click="openNonCashDeposit">Setoran Non Tunai</button>
          </div>
        </div>

        <div class="reconciliation-note">
          <div><strong>Aturan verifikasi</strong><p>Bandingkan data yang sudah ada: pembayaran Mobile Sales versus setoran finance. Bila belum ada setoran atau ada selisih, kembali ke tahap sebelumnya untuk memperbaiki data; faktur dan pembayaran asli tidak diubah dari halaman ini.</p><p class="reconciliation-policy-note">Uang muka dan retur/credit note ikut dihitung sebagai sumber alokasi. Bilyet giro dan biaya meterai, admin transfer, atau pembulatan belum boleh diperlakukan sebagai setoran Mobile Sales sampai mempunyai pencatatan instrumen/akun biaya yang diaudit.</p></div>
          <strong class="reconciliation-note-total">
            {{ pendingRecordingRows.length
              ? `Menunggu dicatat/diterima: ${pendingRecordingRows.length} baris · ${formatCurrency(pendingRecordingTotal)}`
              : `Belum direkap: ${pendingPaymentRows.length} baris · ${formatCurrency(pendingPaymentTotal)}` }}
          </strong>
        </div>

        <div class="table-shell table-shell--reconciliation">
          <table>
            <thead><tr><th>Faktur</th><th>Input Mobile Sales</th><th>Rekap / Setoran</th><th>Metode Setoran</th><th>Nominal Setoran</th><th>Bukti / Referensi</th><th>Selisih</th><th>Tahap</th><th>Status Verifikasi</th></tr></thead>
            <tbody>
              <tr v-if="loading.detail"><td colspan="9" class="table-empty">Memuat pembayaran Mobile Sales dan setoran...</td></tr>
              <tr v-else-if="!paymentRows.length"><td colspan="9" class="table-empty">Belum ada pembayaran dari Mobile Sales untuk faktur dalam LPH ini.</td></tr>
              <tr v-for="row in paymentRows" v-else :key="row.key">
                <td><strong>{{ row.no_faktur || '-' }}</strong><small>{{ formatDate(row.tanggal_input) }}</small></td>
                <td><strong>{{ paymentMethodLabel(row.mobileMethod) }}</strong><small>{{ formatCurrency(row.mobileAmount) }}</small></td>
                <td>
                  <strong>{{ !row.deposited ? 'Belum direkap' : row.depositRecorded ? 'Tercatat / diterima' : 'Sudah direkap · menunggu pencatatan' }}</strong>
                  <small>{{ row.jumlah_baris_setoran ? `${row.jumlah_baris_setoran} catatan setoran` : 'Belum ada catatan setoran' }}</small>
                </td>
                <td><strong>{{ row.depositMethodLabel }}</strong><small>Tunai {{ formatCurrency(row.cashDeposit) }} · Non Tunai {{ formatCurrency(row.nonCashDeposit) }}</small></td>
                <td><strong>{{ formatCurrency(row.amountForMobileMethod) }}</strong><small>Total setoran: {{ formatCurrency(row.totalDeposit) }}</small></td>
                <td><strong>{{ row.proofLabel }}</strong><small>{{ Number(row.mobileMethod) === 2 ? 'Mutasi / bukti transfer' : 'Referensi setoran tunai' }}</small></td>
                <td>
                  <strong :class="['reconciliation-difference', row.exactMatch ? 'reconciliation-difference--match' : 'reconciliation-difference--mismatch']">{{ formatSignedCurrency(row.amountDifference) }}</strong>
                  <small :class="['reconciliation-method-note', { 'reconciliation-method-note--mismatch': !row.methodMatches }]">{{ row.methodMatches ? 'Metode sesuai' : 'Metode berbeda' }}</small>
                </td>
                <td><span class="status-pill" :class="Number(row.status_setoran) >= 3 ? 'status-final' : row.depositRecorded ? 'status-matched' : 'status-pending'">{{ row.depositStageLabel }}</span></td>
                <td><span class="status-pill" :class="reconciliationStatusClass(row.displayStatus)">{{ resolveReconciliationStatus(row.displayStatus) }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
          <div class="verification-summary">
            <p><strong>Belum direkap:</strong> {{ formatCurrency(pendingPaymentTotal) }}</p>
            <p v-if="pendingRecordingRows.length" class="verification-summary-message verification-summary-message--pending">Ada {{ pendingRecordingRows.length }} setoran yang sudah direkap, tetapi belum dicatat/diterima. Catat penerimaan tunai atau verifikasi transfer di menu Setoran sebelum finalisasi.</p>
            <p v-else-if="mismatchPaymentRows.length" class="verification-summary-message verification-summary-message--mismatch">Ada {{ mismatchPaymentRows.length }} baris setoran dengan selisih {{ formatCurrency(mismatchPaymentTotal) }} atau metode tidak sesuai. Perbaiki melalui Rekap/Setoran sebelum finalisasi.</p>
            <p v-else-if="!lphIsActive" class="verification-summary-message verification-summary-message--pending">LPH belum aktif di sales. Data boleh dilihat, tetapi alur pembayaran belum dapat diproses.</p>
            <p v-else-if="canOpenFinalization" class="verification-summary-message verification-summary-message--match">Seluruh pembayaran sudah cocok, serta setoran tunai/transfer telah dicatat atau diterima. Data siap diteruskan ke finalisasi.</p>
          </div>
          <button
            class="button-primary button-reconcile"
            :disabled="!canOpenFinalization"
            :title="pendingRecordingRows.length ? 'Catat atau terima setoran terlebih dahulu di menu Setoran.' : ''"
            @click="openFinalization"
          >Buka Finalisasi Setoran</button>
        </div>
      </section>

      <section class="next-step-grid">
        <article class="next-step-card"><div><p class="section-eyebrow">Tahap sebelumnya · Rekap</p><h2>Rekap Pembayaran</h2><p>Gunakan bila pembayaran Mobile Sales belum menjadi catatan setoran finance.</p></div><button class="button-secondary" @click="openPaymentRecap">Buka Rekap Pembayaran</button></article>
        <article class="next-step-card"><div><p class="section-eyebrow">Tahap sebelumnya · Setoran</p><h2>Setoran Tunai / Non Tunai</h2><p>Gunakan untuk melengkapi nominal, metode, serta bukti mutasi atau referensi setoran sebelum verifikasi.</p></div><div class="flex flex-wrap gap-2"><button class="button-secondary" @click="openCashDeposit">Tunai</button><button class="button-secondary" @click="openNonCashDeposit">Non Tunai</button></div></article>
      </section>
    </template>
  </div>
</template>

<style scoped>
/* Keep the complete selector in :global(): theme is stored on html[data-theme], not Tailwind's media query. */
.payment-page { margin-inline: auto; max-width: 1780px; }
.button-primary, .button-secondary { border-radius: .75rem; padding: .7rem 1rem; font-size: .875rem; font-weight: 700; transition: 160ms ease; }
.button-primary { background: rgb(37 99 235); color: white; }
.button-primary:hover:not(:disabled) { background: rgb(29 78 216); }
.button-secondary { border: 1px solid rgb(203 213 225); color: rgb(51 65 85); background: white; }
.button-secondary:hover:not(:disabled) { background: rgb(248 250 252); }
:global(html[data-theme='dark'] .payment-page .button-secondary) { border-color: rgb(51 65 85); color: rgb(226 232 240); background: rgb(15 23 42); }
:global(html[data-theme='dark'] .payment-page .button-secondary:hover:not(:disabled)) { background: rgb(30 41 59); }
.button-primary:disabled, .button-secondary:disabled { cursor: not-allowed; opacity: .55; }
.section-eyebrow { color: rgb(37 99 235); font-size: .7rem; font-weight: 800; letter-spacing: .16em; text-transform: uppercase; }
.section-title { margin-top: .3rem; color: rgb(15 23 42); font-size: 1.125rem; font-weight: 750; }
.section-description { margin-top: .4rem; max-width: 54rem; color: rgb(100 116 139); font-size: .875rem; line-height: 1.5; }
:global(html[data-theme='dark'] .payment-page .section-title) { color: white; }
:global(html[data-theme='dark'] .payment-page .section-description) { color: rgb(148 163 184); }
.scope-note, .status-pill { display: inline-flex; align-items: center; border-radius: 999px; font-size: .75rem; font-weight: 700; }
.scope-note { background: rgb(241 245 249); color: rgb(71 85 105); padding: .4rem .75rem; }
:global(html[data-theme='dark'] .payment-page .scope-note) { background: rgb(30 41 59); color: rgb(203 213 225); }
.scope-grid, .flow-grid, .summary-grid, .next-step-grid { display: grid; gap: 1rem; }
.scope-grid { grid-template-columns: repeat(1, minmax(0, 1fr)); }
.flow-card, .summary-card, .next-step-card { min-width: 0; border: 1px solid rgb(226 232 240); border-radius: 1rem; background: white; }
.flow-card { padding: 1rem; }
.flow-card-header { display: flex; align-items: center; justify-content: space-between; gap: .75rem; }
.flow-card span { color: rgb(37 99 235); font-size: .75rem; font-weight: 800; letter-spacing: .15em; }
.flow-card em { border-radius: 999px; background: rgb(241 245 249); color: rgb(100 116 139); padding: .2rem .45rem; font-size: .65rem; font-style: normal; font-weight: 750; }
.flow-card h3 { margin-top: .4rem; color: rgb(15 23 42); font-size: .95rem; font-weight: 750; }
.flow-card p { margin-top: .35rem; color: rgb(100 116 139); font-size: .78rem; line-height: 1.45; }
.flow-card--done { border-color: rgb(167 243 208); background: rgb(236 253 245); }
.flow-card--done span { color: rgb(5 150 105); }.flow-card--done em { background: rgb(209 250 229); color: rgb(6 95 70); }
.flow-card--current { border-color: rgb(147 197 253); background: rgb(239 246 255); }.flow-card--current em { background: rgb(219 234 254); color: rgb(30 64 175); }
.flow-card--next { border-color: rgb(253 230 138); background: rgb(255 251 235); }.flow-card--next em { background: rgb(254 243 199); color: rgb(146 64 14); }
:global(html[data-theme='dark'] .payment-page .flow-card), :global(html[data-theme='dark'] .payment-page .summary-card), :global(html[data-theme='dark'] .payment-page .next-step-card) { border-color: rgb(51 65 85); background: rgb(15 23 42); }
:global(html[data-theme='dark'] .payment-page .flow-card h3) { color: white; }
:global(html[data-theme='dark'] .payment-page .flow-card p) { color: rgb(148 163 184); }
:global(html[data-theme='dark'] .payment-page .flow-card em) { background: rgb(51 65 85); color: rgb(203 213 225); }
:global(html[data-theme='dark'] .payment-page .flow-card--done) { border-color: rgb(6 78 59); background: rgb(6 78 59 / .3); }:global(html[data-theme='dark'] .payment-page .flow-card--done em) { background: rgb(6 78 59); color: rgb(167 243 208); }
:global(html[data-theme='dark'] .payment-page .flow-card--current) { border-color: rgb(30 64 175); background: rgb(30 64 175 / .25); }:global(html[data-theme='dark'] .payment-page .flow-card--current em) { background: rgb(30 64 175); color: rgb(191 219 254); }
:global(html[data-theme='dark'] .payment-page .flow-card--next) { border-color: rgb(120 53 15); background: rgb(120 53 15 / .25); }:global(html[data-theme='dark'] .payment-page .flow-card--next em) { background: rgb(120 53 15); color: rgb(253 230 138); }
.alert-success, .alert-error { border-radius: 1rem; border: 1px solid; padding: .9rem 1rem; font-size: .875rem; }
.alert-success { border-color: rgb(167 243 208); background: rgb(236 253 245); color: rgb(6 95 70); }
.alert-error { border-color: rgb(254 202 202); background: rgb(254 242 242); color: rgb(153 27 27); }
:global(html[data-theme='dark'] .payment-page .alert-success) { border-color: rgb(6 78 59); background: rgb(6 78 59 / .25); color: rgb(167 243 208); }
:global(html[data-theme='dark'] .payment-page .alert-error) { border-color: rgb(127 29 29); background: rgb(127 29 29 / .2); color: rgb(254 202 202); }
.empty-state { padding: 3.5rem 1.5rem; text-align: center; }
.empty-state-icon { display: inline-flex; align-items: center; justify-content: center; width: 4rem; height: 4rem; border-radius: 1rem; background: rgb(219 234 254); color: rgb(29 78 216); font-weight: 800; }
.empty-state h2 { margin-top: 1rem; color: rgb(15 23 42); font-size: 1.15rem; font-weight: 750; }
.empty-state p { max-width: 38rem; margin: .55rem auto 0; color: rgb(100 116 139); font-size: .875rem; line-height: 1.6; }
:global(html[data-theme='dark'] .payment-page .empty-state h2) { color: white; }
:global(html[data-theme='dark'] .payment-page .empty-state p) { color: rgb(148 163 184); }
.lph-context { border: 1px solid rgb(186 230 253); padding: 1.25rem; background: linear-gradient(125deg, rgb(240 249 255), white 60%, rgb(236 253 245)); }
.lph-context--inactive { border-color: rgb(253 230 138); background: linear-gradient(125deg, rgb(255 251 235), white); }
:global(html[data-theme='dark'] .payment-page .lph-context) { border-color: rgb(3 105 161); background: linear-gradient(125deg, rgb(12 74 110 / .45), rgb(15 23 42)); }
:global(html[data-theme='dark'] .payment-page .lph-context--inactive) { border-color: rgb(146 64 14); background: linear-gradient(125deg, rgb(120 53 15 / .3), rgb(15 23 42)); }
.lph-context-title { margin-top: .25rem; color: rgb(15 23 42); font-size: 1.5rem; font-weight: 700; line-height: 1.25; }
.lph-context-copy { margin-top: .5rem; color: rgb(71 85 105); font-size: .875rem; line-height: 1.5; }
.lph-context-warning { margin-top: .5rem; max-width: 24rem; color: rgb(146 64 14); font-size: .75rem; line-height: 1.65; }
:global(html[data-theme='dark'] .payment-page .lph-context-title) { color: rgb(248 250 252); }
:global(html[data-theme='dark'] .payment-page .lph-context-copy) { color: rgb(203 213 225); }
:global(html[data-theme='dark'] .payment-page .lph-context-warning) { color: rgb(253 230 138); }
.legacy-payment-header, .legacy-payment-system { padding: 1.25rem; }
.expense-adjustment { padding: 1.25rem; }
.expense-control-summary { display: grid; gap: .75rem; margin-top: 1rem; }
.expense-control-summary > div { min-width: 0; border: 1px solid rgb(191 219 254); border-radius: .85rem; padding: .8rem .9rem; background: rgb(239 246 255); }
.expense-control-summary span { display: block; color: rgb(71 85 105); font-size: .68rem; font-weight: 800; letter-spacing: .07em; text-transform: uppercase; }
.expense-control-summary strong { display: block; margin-top: .3rem; color: rgb(30 64 175); font-size: 1rem; }
.expense-policy-note { margin-top: .75rem; color: rgb(71 85 105); font-size: .78rem; line-height: 1.5; }
.expense-table-shell { margin-top: 1rem; }
.expense-table-shell table { min-width: 1120px; }
.expense-action { padding: .45rem .65rem; font-size: .75rem; }
.expense-entry-form { display: grid; gap: .85rem; margin-top: 1rem; border-top: 1px solid rgb(226 232 240); padding-top: 1rem; }
.expense-field { display: grid; gap: .35rem; min-width: 0; color: rgb(71 85 105); font-size: .7rem; font-weight: 800; letter-spacing: .06em; text-transform: uppercase; }
.expense-field input, .expense-field select, .expense-field textarea { width: 100%; border: 1px solid rgb(203 213 225); border-radius: .7rem; background: white; color: rgb(15 23 42); padding: .65rem .75rem; font: inherit; font-size: .85rem; font-weight: 500; letter-spacing: normal; text-transform: none; outline: none; }
.expense-field textarea { resize: vertical; }
.expense-field input:focus, .expense-field select:focus, .expense-field textarea:focus { border-color: rgb(96 165 250); box-shadow: 0 0 0 3px rgb(219 234 254); }
.expense-entry-action { display: flex; flex-wrap: wrap; align-items: center; gap: .75rem; }
.expense-entry-action small { color: rgb(100 116 139); font-size: .75rem; line-height: 1.45; }
:global(html[data-theme='dark'] .payment-page .expense-control-summary > div) { border-color: rgb(30 64 175); background: rgb(30 64 175 / .2); }
:global(html[data-theme='dark'] .payment-page .expense-control-summary span), :global(html[data-theme='dark'] .payment-page .expense-policy-note), :global(html[data-theme='dark'] .payment-page .expense-entry-action small) { color: rgb(191 219 254); }
:global(html[data-theme='dark'] .payment-page .expense-control-summary strong) { color: rgb(191 219 254); }
:global(html[data-theme='dark'] .payment-page .expense-entry-form) { border-color: rgb(51 65 85); }
:global(html[data-theme='dark'] .payment-page .expense-field) { color: rgb(148 163 184); }
:global(html[data-theme='dark'] .payment-page .expense-field input), :global(html[data-theme='dark'] .payment-page .expense-field select), :global(html[data-theme='dark'] .payment-page .expense-field textarea) { border-color: rgb(51 65 85); background: rgb(2 6 23); color: rgb(226 232 240); }
:global(html[data-theme='dark'] .payment-page .expense-field input:focus), :global(html[data-theme='dark'] .payment-page .expense-field select:focus), :global(html[data-theme='dark'] .payment-page .expense-field textarea:focus) { border-color: rgb(96 165 250); box-shadow: 0 0 0 3px rgb(30 64 175 / .45); }
.legacy-section-heading { display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: 1rem; }
.legacy-identity-grid, .legacy-system-grid, .legacy-method-grid { display: grid; gap: .75rem; margin-top: 1rem; }
.legacy-info-cell { min-width: 0; border: 1px solid rgb(226 232 240); border-radius: .85rem; padding: .85rem .95rem; background: rgb(248 250 252); }
.legacy-info-cell dt, .legacy-method-card p { color: rgb(100 116 139); font-size: .68rem; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
.legacy-info-cell dd { margin-top: .35rem; overflow-wrap: anywhere; color: rgb(15 23 42); font-size: .96rem; font-weight: 750; line-height: 1.35; }
.legacy-info-cell small, .legacy-method-card small { display: block; margin-top: .3rem; color: rgb(100 116 139); font-size: .72rem; line-height: 1.4; }
.legacy-info-cell--total { border-color: rgb(134 239 172); background: rgb(240 253 244); }
.legacy-info-cell--total dd { color: rgb(22 101 52); font-size: 1.1rem; }
.legacy-method-card { min-width: 0; border: 1px solid rgb(226 232 240); border-radius: .85rem; padding: .9rem .95rem; background: white; }
.legacy-method-card strong { display: block; margin-top: .35rem; color: rgb(15 23 42); font-size: 1.15rem; }
.legacy-method-card--cash { border-color: rgb(167 243 208); background: rgb(236 253 245); }.legacy-method-card--cash strong { color: rgb(6 95 70); }
.legacy-method-card--noncash { border-color: rgb(191 219 254); background: rgb(239 246 255); }.legacy-method-card--noncash strong { color: rgb(30 64 175); }
.legacy-method-card--advance { border-color: rgb(253 230 138); background: rgb(255 251 235); }.legacy-method-card--advance strong { color: rgb(146 64 14); }
.legacy-method-card--other { border-color: rgb(253 230 138); background: rgb(255 251 235); }.legacy-method-card--other strong { color: rgb(146 64 14); }
:global(html[data-theme='dark'] .payment-page .legacy-info-cell) { border-color: rgb(51 65 85); background: rgb(15 23 42); }
:global(html[data-theme='dark'] .payment-page .legacy-info-cell dt), :global(html[data-theme='dark'] .payment-page .legacy-method-card p), :global(html[data-theme='dark'] .payment-page .legacy-info-cell small), :global(html[data-theme='dark'] .payment-page .legacy-method-card small) { color: rgb(148 163 184); }
:global(html[data-theme='dark'] .payment-page .legacy-info-cell dd), :global(html[data-theme='dark'] .payment-page .legacy-method-card strong) { color: white; }
:global(html[data-theme='dark'] .payment-page .legacy-info-cell--total) { border-color: rgb(6 78 59); background: rgb(6 78 59 / .3); }:global(html[data-theme='dark'] .payment-page .legacy-info-cell--total dd) { color: rgb(167 243 208); }
:global(html[data-theme='dark'] .payment-page .legacy-method-card) { border-color: rgb(51 65 85); background: rgb(15 23 42); }
:global(html[data-theme='dark'] .payment-page .legacy-method-card--cash) { border-color: rgb(6 78 59); background: rgb(6 78 59 / .3); }:global(html[data-theme='dark'] .payment-page .legacy-method-card--cash strong) { color: rgb(167 243 208); }
:global(html[data-theme='dark'] .payment-page .legacy-method-card--noncash) { border-color: rgb(30 64 175); background: rgb(30 64 175 / .25); }:global(html[data-theme='dark'] .payment-page .legacy-method-card--noncash strong) { color: rgb(191 219 254); }
:global(html[data-theme='dark'] .payment-page .legacy-method-card--advance) { border-color: rgb(120 53 15); background: rgb(120 53 15 / .25); }:global(html[data-theme='dark'] .payment-page .legacy-method-card--advance strong) { color: rgb(253 230 138); }
:global(html[data-theme='dark'] .payment-page .legacy-method-card--other) { border-color: rgb(120 53 15); background: rgb(120 53 15 / .25); }:global(html[data-theme='dark'] .payment-page .legacy-method-card--other strong) { color: rgb(253 230 138); }
.separator { margin-inline: .45rem; color: rgb(148 163 184); }
.reconciliation-policy-note { margin-top: .45rem; color: rgb(71 85 105); font-size: .8rem; line-height: 1.45; }
:global(html[data-theme='dark'] .payment-page .reconciliation-policy-note) { color: rgb(203 213 225); }
.summary-grid { grid-template-columns: repeat(1, minmax(0, 1fr)); }
.summary-card { padding: 1rem; }
.summary-card p { color: rgb(100 116 139); font-size: .7rem; font-weight: 750; letter-spacing: .1em; text-transform: uppercase; }
.summary-card strong { display: block; margin-top: .45rem; color: rgb(15 23 42); font-size: 1.1rem; }
.summary-card--sky { border-color: rgb(186 230 253); }.summary-card--violet { border-color: rgb(221 214 254); }.summary-card--emerald { border-color: rgb(167 243 208); }.summary-card--amber { border-color: rgb(253 230 138); }.summary-card--rose { border-color: rgb(254 202 202); }
:global(html[data-theme='dark'] .payment-page .summary-card strong) { color: white; }:global(html[data-theme='dark'] .payment-page .summary-card p) { color: rgb(148 163 184); }
.table-shell { overflow: auto; border: 1px solid rgb(226 232 240); border-radius: 1rem; }
.table-shell table { min-width: 780px; width: 100%; border-collapse: collapse; }
.table-shell th { padding: .8rem .9rem; background: rgb(248 250 252); color: rgb(100 116 139); font-size: .68rem; font-weight: 800; letter-spacing: .07em; text-align: left; text-transform: uppercase; white-space: nowrap; }
.table-shell td { border-top: 1px solid rgb(241 245 249); padding: .75rem .9rem; color: rgb(51 65 85); font-size: .82rem; vertical-align: middle; }
.table-shell strong { display: block; color: rgb(15 23 42); font-weight: 750; }.table-shell small { display: block; margin-top: .2rem; color: rgb(100 116 139); font-size: .7rem; }.table-empty { padding-block: 2.5rem !important; color: rgb(100 116 139) !important; text-align: center; }
:global(html[data-theme='dark'] .payment-page .table-shell) { border-color: rgb(51 65 85); }:global(html[data-theme='dark'] .payment-page .table-shell th) { background: rgb(30 41 59); color: rgb(148 163 184); }:global(html[data-theme='dark'] .payment-page .table-shell td) { border-top-color: rgb(30 41 59); color: rgb(203 213 225); }:global(html[data-theme='dark'] .payment-page .table-shell strong) { color: white; }:global(html[data-theme='dark'] .payment-page .table-shell small) { color: rgb(148 163 184); }
.table-shell .reconciliation-difference { color: rgb(4 120 87); }
.table-shell .reconciliation-difference--mismatch { color: rgb(190 24 93); }
.table-shell .reconciliation-method-note { color: rgb(71 85 105); }
.table-shell .reconciliation-method-note--mismatch { color: rgb(190 24 93); }
:global(html[data-theme='dark'] .payment-page .table-shell .reconciliation-difference) { color: rgb(110 231 183); }
:global(html[data-theme='dark'] .payment-page .table-shell .reconciliation-difference--mismatch) { color: rgb(253 164 175); }
:global(html[data-theme='dark'] .payment-page .table-shell .reconciliation-method-note) { color: rgb(203 213 225); }
:global(html[data-theme='dark'] .payment-page .table-shell .reconciliation-method-note--mismatch) { color: rgb(253 164 175); }
.status-pill { padding: .3rem .55rem; line-height: 1.2; white-space: nowrap; }.status-neutral { background: rgb(241 245 249); color: rgb(71 85 105); }.status-pending { background: rgb(254 243 199); color: rgb(146 64 14); }.status-matched { background: rgb(209 250 229); color: rgb(6 95 70); }.status-final { background: rgb(219 234 254); color: rgb(30 64 175); }.status-mismatch { background: rgb(254 226 226); color: rgb(153 27 27); }
:global(html[data-theme='dark'] .payment-page .status-neutral) { background: rgb(51 65 85); color: rgb(203 213 225); }:global(html[data-theme='dark'] .payment-page .status-pending) { background: rgb(120 53 15 / .4); color: rgb(253 230 138); }:global(html[data-theme='dark'] .payment-page .status-matched) { background: rgb(6 78 59 / .5); color: rgb(167 243 208); }:global(html[data-theme='dark'] .payment-page .status-final) { background: rgb(30 64 175 / .35); color: rgb(191 219 254); }:global(html[data-theme='dark'] .payment-page .status-mismatch) { background: rgb(127 29 29 / .4); color: rgb(254 202 202); }
.reconciliation-note { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: .75rem; margin-bottom: 1rem; border: 1px solid rgb(191 219 254); border-radius: .9rem; background: rgb(239 246 255); padding: .85rem 1rem; color: rgb(30 64 175); font-size: .8rem; }.reconciliation-note p { margin-top: .2rem; max-width: 54rem; color: rgb(30 64 175); line-height: 1.45; }.reconciliation-note-total { white-space: nowrap; }
:global(html[data-theme='dark'] .payment-page .reconciliation-note) { border-color: rgb(30 64 175); background: rgb(30 64 175 / .2); color: rgb(191 219 254); }:global(html[data-theme='dark'] .payment-page .reconciliation-note p) { color: rgb(191 219 254); }
.verification-summary { color: rgb(71 85 105); font-size: .875rem; line-height: 1.5; }
.verification-summary-message { margin-top: .25rem; font-weight: 600; }
.verification-summary-message--mismatch { color: rgb(190 24 93); }
.verification-summary-message--pending { color: rgb(146 64 14); }
.verification-summary-message--match { color: rgb(4 120 87); }
:global(html[data-theme='dark'] .payment-page .verification-summary) { color: rgb(203 213 225); }
:global(html[data-theme='dark'] .payment-page .verification-summary-message--mismatch) { color: rgb(253 164 175); }
:global(html[data-theme='dark'] .payment-page .verification-summary-message--pending) { color: rgb(253 230 138); }
:global(html[data-theme='dark'] .payment-page .verification-summary-message--match) { color: rgb(110 231 183); }
.table-shell--legacy table { min-width: 1120px; }
.table-shell--reconciliation table { min-width: 1280px; }
.button-reconcile { min-width: 16rem; }.next-step-card { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 1rem; padding: 1.25rem; }.next-step-card h2 { margin-top: .25rem; color: rgb(15 23 42); font-size: 1rem; font-weight: 750; }.next-step-card p { max-width: 34rem; margin-top: .3rem; color: rgb(100 116 139); font-size: .82rem; line-height: 1.5; }:global(html[data-theme='dark'] .payment-page .next-step-card h2) { color: white; }:global(html[data-theme='dark'] .payment-page .next-step-card p) { color: rgb(148 163 184); }
@media (min-width: 640px) { .scope-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.flow-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.summary-grid, .legacy-identity-grid, .legacy-system-grid, .legacy-method-grid, .expense-control-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }.expense-entry-form { grid-template-columns: repeat(2, minmax(0, 1fr)); }.expense-field--wide, .expense-entry-action { grid-column: 1 / -1; } }
@media (min-width: 1024px) { .flow-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (min-width: 1280px) { .scope-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }.flow-grid { grid-template-columns: repeat(6, minmax(0, 1fr)); }.summary-grid { grid-template-columns: repeat(6, minmax(0, 1fr)); }.legacy-identity-grid, .legacy-system-grid, .legacy-method-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }.expense-control-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); }.expense-entry-form { grid-template-columns: repeat(3, minmax(0, 1fr)); }.next-step-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
