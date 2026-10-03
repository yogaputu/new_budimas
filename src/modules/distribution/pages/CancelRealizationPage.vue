<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import {
  approveCancelRealizationRequest,
  createCancelRealizationRequest,
  finalApproveCancelRealizationRequest,
  finalRejectCancelRealizationRequest,
  getCancelRealizationCandidates,
  getCancelRealizationRequest,
  getCancelRealizationRequests,
  getInvoiceDetail,
  rejectCancelRealizationRequest,
  submitCancelRealizationRevision
} from '@/api/distribution';
import { getBranches, getCompanies } from '@/api/master';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getLoginCompanyId, isSuperUser } from '@/utils/accessScope';
import { getBranchOptionsForCompany, getCompanyOptionsForScope } from '@/utils/filterScope';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();

// Daftar ini hanya ringkasan workflow. Detail lengkap tetap dibuka per request.
// Batasi hasil awal supaya beban agregasi/payload lintas-cabang tidak sebesar
// daftar tanpa batas ketika halaman Super User pertama kali dibuka.
const REQUEST_LIST_LIMIT = 50;

const filters = reactive({
  id_perusahaan: '',
  id_cabang: '',
  status: '',
  search: '',
  date_from: '',
  date_to: ''
});

const createForm = reactive({
  reason: ''
});

const candidateFilters = reactive({
  q: ''
});

const decisionForm = reactive({
  note: ''
});

const revisionForm = reactive({
  note: '',
  orders: []
});

const companies = ref([]);
const branches = ref([]);
const requestRows = ref([]);
const requestDetail = ref({});
const requestInvoiceRows = ref([]);
const requestAuditRows = ref([]);
const realizationInvoices = ref([]);
const selectedInvoiceIds = ref([]);
const selectedRequest = ref(null);
const createModalOpen = ref(false);
const detailModalOpen = ref(false);
const revisionModalOpen = ref(false);
const pageLoading = ref(false);
const referenceLoading = ref(false);
const invoiceLoading = ref(false);
const requestDetailLoading = ref(false);
const createSubmitting = ref(false);
const actionSubmitting = ref(false);
const revisionLoading = ref(false);
const revisionSubmitting = ref(false);
const feedback = ref('');
const errorMessage = ref('');
const referenceError = ref('');
const detailError = ref('');
const hasLoadedRequests = ref(false);

const loginBranchId = computed(() => getLoginBranchId(authStore.user));
const loginCompanyId = computed(() => getLoginCompanyId(authStore.user));
const shouldLockScope = computed(() => !isSuperUser(authStore));
const selectedRequestId = computed(() => getRequestId(selectedRequest.value || requestDetail.value));
const selectedRequestStatus = computed(() => getRequestStatus(requestDetail.value || selectedRequest.value || {}));
const selectedRequestStage = computed(() => statusMeta(selectedRequestStatus.value).stage);
const canApproveSelected = computed(() => Boolean(requestDetail.value?.can_approve));
const canEditSelected = computed(() => Boolean(requestDetail.value?.can_edit));
const canFinalApproveSelected = computed(() => Boolean(requestDetail.value?.can_final_approve));
const initialApprovalMessage = computed(() => approvalCapabilityMessage(
  requestDetail.value?.initial_approval,
  'Menunggu tindakan dari approver yang berwenang.'
));
const finalApprovalMessage = computed(() => approvalCapabilityMessage(
  requestDetail.value?.final_approval,
  'Menunggu tindakan dari final approver yang berwenang.'
));

const processSteps = [
  { number: '01', title: 'Ajukan', note: 'Pilih faktur pada rute realisasi dan tulis alasan pembatalan.' },
  { number: '02', title: 'Approval Awal', note: 'Supervisor menilai alasan sebelum data order diubah.' },
  { number: '03', title: 'Revisi Faktur', note: 'Sesuaikan qty, harga, atau diskon dari data faktur yang terdampak.' },
  { number: '04', title: 'Finalisasi', note: 'Approval akhir baru menjalankan pembatalan realisasi secara aman.' }
];

const statusOptions = [
  { value: 'PENDING_APPROVAL', label: 'Menunggu Approval' },
  { value: 'APPROVED_EDITABLE', label: 'Menunggu Revisi' },
  { value: 'REVISION_SUBMITTED', label: 'Menunggu Finalisasi' },
  { value: 'COMPLETED', label: 'Selesai' },
  { value: 'REJECTED', label: 'Ditolak' }
];

const filterFields = computed(() => [
  {
    key: 'id_perusahaan',
    label: 'Perusahaan',
    type: 'search-select',
    options: getCompanyOptionsForScope(companies.value, authStore),
    placeholder: 'Semua perusahaan',
    disabled: shouldLockScope.value && Boolean(loginCompanyId.value)
  },
  {
    key: 'id_cabang',
    label: 'Cabang',
    type: 'search-select',
    options: getBranchOptionsForCompany(branches.value, authStore, filters.id_perusahaan, false, companies.value),
    placeholder: 'Semua cabang',
    emptyText: 'Cabang belum tersedia.',
    disabled: shouldLockScope.value && Boolean(loginBranchId.value)
  },
  { key: 'status', label: 'Status', type: 'search-select', options: statusOptions, placeholder: 'Semua status' },
  { key: 'date_from', label: 'Dari Tanggal', type: 'date' },
  { key: 'date_to', label: 'Sampai Tanggal', type: 'date' },
  { key: 'search', label: 'Cari', placeholder: 'Kode request, faktur, SO, customer, atau alasan' }
]);

const requestTableColumns = [
  { key: 'request_label', label: 'Kode Request' },
  { key: 'requested_at_label', label: 'Tanggal' },
  { key: 'invoice_label', label: 'Faktur / SO' },
  { key: 'customer_label', label: 'Customer' },
  { key: 'requester_label', label: 'Pengaju' },
  { key: 'status_display', label: 'Status' },
  { key: 'next_step', label: 'Langkah Berikutnya' }
];

const requestTableRows = computed(() =>
  requestRows.value.map((row, index) => {
    const status = statusMeta(getRequestStatus(row));
    const nextStep = status.stage === 'approval'
      ? approvalCapabilityMessage(row?.initial_approval, status.nextStep)
      : status.stage === 'final'
        ? approvalCapabilityMessage(row?.final_approval, status.nextStep)
        : status.nextStep;
    return {
      ...row,
      row_key: String(getRequestId(row) || index),
      request_label: getRequestCode(row) || `BR-${getRequestId(row) || index + 1}`,
      requested_at_label: formatDate(firstValue(row, ['created_at', 'tanggal_request', 'requested_at', 'tanggal'])),
      invoice_label: invoiceLabel(row),
      customer_label: firstValue(row, ['nama_customer', 'customer_name', 'customer']) || '-',
      requester_label: firstValue(row, ['nama_pengaju', 'requester_name', 'requested_by_name', 'created_by_name', 'nama_user']) || '-',
      status_display: { text: status.label, className: status.className },
      next_step: nextStep
    };
  })
);

const candidateInvoiceRows = computed(() =>
  realizationInvoices.value.map((row, index) => {
    const id = getInvoiceId(row);
    return {
      ...row,
      row_key: String(id || `${row.no_faktur || 'invoice'}-${index}`),
      id_faktur_candidate: id,
      invoice_label: invoiceLabel(row),
      customer_label: firstValue(row, ['nama_customer', 'customer_name', 'customer']) || '-',
      total_label: formatCurrency(firstValue(row, ['total_bayar', 'total_penjualan', 'grand_total', 'total'])),
      can_select: Boolean(id)
    };
  })
);

const selectedCandidateCount = computed(() => selectedInvoiceIds.value.length);
const canSubmitCreate = computed(() => selectedCandidateCount.value > 0 && createForm.reason.trim().length >= 5 && !createSubmitting.value);

const requestSummary = computed(() => {
  const counts = { total: requestRows.value.length, pending: 0, revision: 0, final: 0, completed: 0, rejected: 0 };
  requestRows.value.forEach((row) => {
    const stage = statusMeta(getRequestStatus(row)).stage;
    if (stage === 'approval') counts.pending += 1;
    if (stage === 'revision') counts.revision += 1;
    if (stage === 'final') counts.final += 1;
    if (stage === 'completed') counts.completed += 1;
    if (stage === 'rejected') counts.rejected += 1;
  });
  return counts;
});

const detailInvoiceTableRows = computed(() =>
  requestInvoiceRows.value.map((row, index) => ({
    ...row,
    row_key: String(getInvoiceId(row) || row.id_sales_order || index),
    invoice_label: invoiceLabel(row),
    customer_label: firstValue(row, ['nama_customer', 'customer_name', 'customer']) || '-',
    total_label: formatCurrency(firstValue(row, ['total_bayar', 'total_penjualan', 'grand_total', 'total'])),
    status_label: firstValue(row, ['status_label', 'status_faktur_label', 'status']) || '-'
  }))
);

const detailAuditRows = computed(() =>
  requestAuditRows.value.map((row, index) => ({
    ...row,
    row_key: String(row.id || row.id_log || index),
    at_label: formatDateTime(firstValue(row, ['created_at', 'tanggal', 'at', 'waktu'])),
    actor_label: firstValue(row, ['nama_user', 'actor_name', 'user_name', 'actor']) || 'System',
    action_label: firstValue(row, ['aksi', 'action', 'status_label', 'status']) || '-',
    note_label: firstValue(row, ['catatan', 'note', 'keterangan', 'reason']) || '-'
  }))
);

const revisionOrderCount = computed(() => revisionForm.orders.length);
const revisionDetailCount = computed(() => revisionForm.orders.reduce((total, order) => total + order.details.length, 0));
const canSubmitRevision = computed(() =>
  revisionOrderCount.value > 0 &&
  revisionDetailCount.value > 0 &&
  revisionForm.orders.every((order) => order.id_faktur && order.id_sales_order && order.details.every((detail) => detail.id_order_detail)) &&
  !revisionSubmitting.value
);

function firstValue(row, keys = []) {
  for (const key of keys) {
    const value = row?.[key];
    if (value !== undefined && value !== null && String(value).trim() !== '') return value;
  }
  return '';
}

function toNumber(value, fallback = 0) {
  const result = Number(value);
  return Number.isFinite(result) ? result : fallback;
}

function getRequestId(row = {}) {
  return firstValue(row, ['id_request_batal_realisasi', 'id_batal_realisasi', 'id_request', 'request_id', 'id']);
}

function getRequestCode(row = {}) {
  return firstValue(row, ['kode_request', 'kode_batal_realisasi', 'request_no', 'nomor_request']);
}

function getRequestStatus(row = {}) {
  return String(firstValue(row, ['workflow_status', 'status_request', 'status_batal_realisasi', 'status', 'state']) || 'pending').trim().toLowerCase();
}

function approvalCapabilityMessage(capability, fallback) {
  const message = capability?.message;
  return typeof message === 'string' && message.trim() ? message.trim() : fallback;
}

function getInvoiceId(row = {}) {
  const value = firstValue(row, ['id_faktur', 'faktur_id', 'invoice_id', 'id_invoice']);
  return value === '' ? '' : String(value);
}

function getInvoiceBranchId(row = {}) {
  return String(firstValue(row, ['id_cabang', 'cabang_id', 'branch_id']) || '');
}

function getSalesOrderIds(row = {}) {
  const raw = firstValue(row, ['id_sales_order', 'faktur_id_sales_order', 'id_sales_orders', 'sales_order_id', 'sales_order_ids', 'no_order']);
  if (Array.isArray(raw)) return raw.map((item) => String(item)).filter(Boolean);
  return String(raw || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function invoiceLabel(row = {}) {
  const noFaktur = firstValue(row, ['no_faktur', 'nomor_faktur', 'invoice_no', 'faktur_no']);
  const salesOrders = getSalesOrderIds(row);
  if (noFaktur && salesOrders.length) return `${noFaktur} · SO ${salesOrders.join(', ')}`;
  if (noFaktur) return String(noFaktur);
  if (salesOrders.length) return `SO ${salesOrders.join(', ')}`;
  return '-';
}

function formatCurrency(value) {
  return `Rp ${toNumber(value).toLocaleString('id-ID')}`;
}

function formatDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' });
}

function formatDateTime(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString('id-ID', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function statusMeta(statusValue) {
  const status = String(statusValue || '').trim().toLowerCase();
  if (/(final_reject|final-reject|reject|ditolak|denied|cancel)/.test(status)) {
    return { stage: 'rejected', label: 'Ditolak', nextStep: 'Tidak ada tindakan lanjutan', className: 'font-semibold text-rose-600 dark:text-rose-300' };
  }
  if (/(final_approve|final-approve|complete|completed|finalized|selesai|done)/.test(status)) {
    return { stage: 'completed', label: 'Selesai', nextStep: 'Pembatalan realisasi telah difinalisasi', className: 'font-semibold text-emerald-600 dark:text-emerald-300' };
  }
  if (/(revision_submitted|revision-submitted|waiting_final|waiting-final|pending_final|pending-final|final_approval|final-approval|menunggu final)/.test(status)) {
    return { stage: 'final', label: 'Menunggu Finalisasi', nextStep: 'Menunggu approval akhir', className: 'font-semibold text-violet-600 dark:text-violet-300' };
  }
  if (/(approved|waiting_revision|waiting-revision|need_revision|need-revision|revision|revisi)/.test(status)) {
    return { stage: 'revision', label: 'Menunggu Revisi', nextStep: 'Lengkapi revisi faktur', className: 'font-semibold text-sky-600 dark:text-sky-300' };
  }
  return { stage: 'approval', label: 'Menunggu Approval', nextStep: 'Menunggu persetujuan awal', className: 'font-semibold text-amber-600 dark:text-amber-300' };
}

function normalizeRequestRows(payload) {
  const body = payload?.requests || payload?.items || payload?.data || payload?.result || payload || [];
  return normalizeList(body);
}

function clearFeedback() {
  feedback.value = '';
  errorMessage.value = '';
}

function requestParams() {
  return {
    id_perusahaan: filters.id_perusahaan || undefined,
    id_cabang: filters.id_cabang || undefined,
    status: filters.status || undefined,
    search: filters.search || undefined,
    date_from: filters.date_from || undefined,
    date_to: filters.date_to || undefined,
    limit: REQUEST_LIST_LIMIT
  };
}

function applyDefaultScope() {
  // User non-Super wajib mengikuti scope login. Super User tetap boleh
  // memuat daftar lintas cabang tanpa harus memilih filter lebih dulu.
  if (!shouldLockScope.value) return;
  if (!filters.id_perusahaan && loginCompanyId.value) {
    filters.id_perusahaan = String(loginCompanyId.value);
  }
  if (!filters.id_cabang && loginBranchId.value) {
    filters.id_cabang = String(loginBranchId.value);
  }
}

function isTimeoutError(error) {
  return error?.code === 'ECONNABORTED' || /timeout of \d+ms exceeded/i.test(String(error?.message || ''));
}

function resetFilters() {
  filters.id_perusahaan = shouldLockScope.value && loginCompanyId.value ? String(loginCompanyId.value) : '';
  filters.id_cabang = shouldLockScope.value && loginBranchId.value ? String(loginBranchId.value) : '';
  filters.status = '';
  filters.search = '';
  filters.date_from = '';
  filters.date_to = '';
  applyDefaultScope();
  loadRequests();
}

async function loadReferences() {
  referenceLoading.value = true;
  referenceError.value = '';
  try {
    const [companyResponse, branchResponse] = await Promise.all([getCompanies(), getBranches()]);
    companies.value = normalizeList(unwrapResponse(companyResponse));
    branches.value = normalizeList(unwrapResponse(branchResponse));
    if (shouldLockScope.value && loginCompanyId.value) filters.id_perusahaan = String(loginCompanyId.value);
    if (shouldLockScope.value && loginBranchId.value) filters.id_cabang = String(loginBranchId.value);
    applyDefaultScope();
  } catch (error) {
    // Referensi filter dimuat paralel dengan daftar request. Jangan menimpa
    // hasil/error daftar request dengan pesan Axios mentah dari referensi.
    referenceError.value = isTimeoutError(error)
      ? 'Pilihan perusahaan atau cabang belum selesai dimuat. Daftar request tetap dapat digunakan; coba muat ulang halaman bila filter diperlukan.'
      : normalizeError(error, 'Referensi perusahaan dan cabang belum dapat dimuat.');
  } finally {
    referenceLoading.value = false;
  }
}

async function loadRequests() {
  pageLoading.value = true;
  clearFeedback();
  try {
    const response = await getCancelRealizationRequests(requestParams());
    requestRows.value = normalizeRequestRows(unwrapResponse(response));
    hasLoadedRequests.value = true;
    if (!requestRows.value.length) feedback.value = 'Belum ada request pembatalan realisasi pada filter ini.';
  } catch (error) {
    requestRows.value = [];
    hasLoadedRequests.value = false;
    errorMessage.value = isTimeoutError(error)
      ? 'Pemuatan daftar request melewati batas waktu. Persempit filter cabang/perusahaan, periode, status, atau pencarian lalu klik Terapkan.'
      : normalizeError(error, 'Daftar request pembatalan realisasi belum dapat dimuat.');
  } finally {
    pageLoading.value = false;
  }
}

function resetCreateContext() {
  createForm.reason = '';
  candidateFilters.q = '';
  realizationInvoices.value = [];
  selectedInvoiceIds.value = [];
}

async function openCreateRequest() {
  clearFeedback();
  resetCreateContext();
  createModalOpen.value = true;
  await loadCancelRealizationCandidates();
}

async function loadCancelRealizationCandidates() {
  realizationInvoices.value = [];
  selectedInvoiceIds.value = [];
  invoiceLoading.value = true;
  try {
    const response = await getCancelRealizationCandidates({
      q: candidateFilters.q.trim() || undefined,
      id_cabang: filters.id_cabang || undefined,
      id_perusahaan: filters.id_perusahaan || undefined,
      limit: 100
    });
    const payload = unwrapResponse(response);
    realizationInvoices.value = normalizeList(payload?.items || payload?.invoices || payload?.data || payload);
    if (!realizationInvoices.value.length) feedback.value = 'Tidak ada faktur selesai realisasi yang dapat diajukan pada scope ini.';
  } catch (error) {
    errorMessage.value = isTimeoutError(error)
      ? 'Pemuatan kandidat faktur melewati batas waktu. Server sedang menyiapkan daftar faktur selesai realisasi; coba lagi sesaat.'
      : normalizeError(error, 'Daftar kandidat faktur selesai realisasi belum dapat dimuat.');
  } finally {
    invoiceLoading.value = false;
  }
}

function isInvoiceSelected(row) {
  const id = getInvoiceId(row);
  return Boolean(id) && selectedInvoiceIds.value.includes(String(id));
}

function toggleInvoice(row) {
  const id = getInvoiceId(row);
  if (!id) {
    errorMessage.value = 'ID faktur tidak tersedia pada data ini sehingga belum dapat diajukan. Muat ulang daftar faktur atau periksa data faktur di server.';
    return;
  }
  const normalizedId = String(id);
  const selectedRows = candidateInvoiceRows.value.filter((item) => selectedInvoiceIds.value.includes(String(item.id_faktur_candidate)));
  const selectedBranchId = getInvoiceBranchId(selectedRows[0]);
  const candidateBranchId = getInvoiceBranchId(row);
  if (!isInvoiceSelected(row) && selectedRows.length && selectedBranchId && candidateBranchId && selectedBranchId !== candidateBranchId) {
    errorMessage.value = 'Satu request pembatalan realisasi hanya boleh berisi faktur dari cabang yang sama.';
    return;
  }
  selectedInvoiceIds.value = isInvoiceSelected(row)
    ? selectedInvoiceIds.value.filter((item) => item !== normalizedId)
    : [...selectedInvoiceIds.value, normalizedId];
}

async function submitCreateRequest() {
  if (!canSubmitCreate.value) {
    errorMessage.value = 'Pilih minimal satu faktur dan isi alasan pembatalan paling sedikit 5 karakter.';
    return;
  }

  createSubmitting.value = true;
  clearFeedback();
  try {
    const response = await createCancelRealizationRequest({
      invoice_ids: selectedInvoiceIds.value,
      reason: createForm.reason.trim()
    });
    const payload = unwrapResponse(response) || {};
    const created = payload?.request || payload?.data || payload;
    const createdId = getRequestId(created);
    feedback.value = firstValue(payload, ['message']) || 'Request pembatalan realisasi berhasil diajukan.';
    createModalOpen.value = false;
    await loadRequests();
    if (createdId) await openRequest(created);
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Request pembatalan realisasi belum berhasil diajukan.');
  } finally {
    createSubmitting.value = false;
  }
}

function extractDetailPayload(payload) {
  const container = payload?.data || payload?.result || payload || {};
  const header = container?.request || payload?.request || container?.header || container;
  const invoices = normalizeList(
    container?.invoices ||
    container?.fakturs ||
    container?.invoice_rows ||
    container?.items ||
    header?.invoices ||
    header?.items ||
    []
  );
  const audit = normalizeList(container?.audit || container?.history || container?.logs || header?.audit || header?.history || []);
  return { header, invoices, audit };
}

async function openRequest(row) {
  const id = getRequestId(row);
  if (!id) {
    errorMessage.value = 'ID request pembatalan realisasi tidak tersedia.';
    return;
  }
  selectedRequest.value = row;
  requestDetail.value = {};
  requestInvoiceRows.value = [];
  requestAuditRows.value = [];
  decisionForm.note = '';
  detailError.value = '';
  detailModalOpen.value = true;
  await loadRequestDetail(id);
}

async function loadRequestDetail(id = selectedRequestId.value) {
  if (!id) return;
  requestDetailLoading.value = true;
  detailError.value = '';
  try {
    const response = await getCancelRealizationRequest(id);
    const detail = extractDetailPayload(unwrapResponse(response));
    requestDetail.value = detail.header;
    requestInvoiceRows.value = detail.invoices;
    requestAuditRows.value = detail.audit;
    selectedRequest.value = { ...(selectedRequest.value || {}), ...detail.header };
  } catch (error) {
    detailError.value = normalizeError(error, 'Detail request pembatalan realisasi belum dapat dimuat.');
  } finally {
    requestDetailLoading.value = false;
  }
}

async function refreshSelectedRequest(message = '') {
  if (message) feedback.value = message;
  await Promise.all([loadRequests(), loadRequestDetail()]);
}

async function runInitialDecision(action) {
  if (!selectedRequestId.value) return;
  if (action === 'reject' && decisionForm.note.trim().length < 3) {
    detailError.value = 'Catatan penolakan wajib diisi minimal 3 karakter.';
    return;
  }
  actionSubmitting.value = true;
  detailError.value = '';
  try {
    const payload = { note: decisionForm.note.trim() };
    const response = action === 'approve'
      ? await approveCancelRealizationRequest(selectedRequestId.value, payload)
      : await rejectCancelRealizationRequest(selectedRequestId.value, payload);
    const body = unwrapResponse(response) || {};
    decisionForm.note = '';
    await refreshSelectedRequest(firstValue(body, ['message']) || (action === 'approve' ? 'Request disetujui. Lanjutkan revisi faktur.' : 'Request pembatalan realisasi ditolak.'));
  } catch (error) {
    detailError.value = normalizeError(error, action === 'approve' ? 'Approval awal belum berhasil diproses.' : 'Penolakan request belum berhasil diproses.');
  } finally {
    actionSubmitting.value = false;
  }
}

function invoiceOrderRows() {
  const orders = [];
  const seen = new Set();
  requestInvoiceRows.value.forEach((invoice) => {
    const snapshot = invoice?.current_snapshot || invoice?.original_snapshot || {};
    const nestedOrders = normalizeList(
      invoice?.orders ||
      invoice?.sales_orders ||
      invoice?.order_rows ||
      snapshot?.orders ||
      []
    );
    const sourceOrders = nestedOrders.length
      ? nestedOrders.map((order) => ({
          ...order,
          id_sales_order: firstValue(order, ['id_sales_order', 'sales_order_id', 'id'])
        }))
      : getSalesOrderIds(invoice).map((idSalesOrder) => ({ id_sales_order: idSalesOrder }));

    sourceOrders.forEach((sourceOrder) => {
      const idSalesOrder = sourceOrder.id_sales_order;
      const key = String(idSalesOrder);
      if (!key || seen.has(key)) return;
      seen.add(key);
      orders.push({
        ...sourceOrder,
        id_sales_order: key,
        id_order_batch: firstValue(sourceOrder, ['id_order_batch', 'order_batch_id']) || firstValue(invoice, ['id_order_batch', 'order_batch_id']),
        id_faktur: getInvoiceId(sourceOrder) || getInvoiceId(invoice),
        invoice
      });
    });
  });
  return orders;
}

function buildRevisionDetail(row, index) {
  const pieces = toNumber(firstValue(row, ['pieces_order', 'pieces_delivered', 'pieces', 'jumlah_pcs']));
  const box = toNumber(firstValue(row, ['box_order', 'box_delivered', 'box', 'jumlah_box']));
  const karton = toNumber(firstValue(row, ['karton_order', 'karton_delivered', 'karton', 'jumlah_karton']));
  return {
    ...row,
    row_key: String(firstValue(row, ['id_order_detail', 'id_detail_sales', 'id_detail', 'id']) || `${index}-${row.id_produk || ''}`),
    id_order_detail: firstValue(row, ['id_order_detail', 'id_detail_sales', 'id_detail', 'id']),
    kode_sku: firstValue(row, ['kode_sku', 'kode_produk', 'kode']) || '-',
    nama_produk: firstValue(row, ['nama_produk', 'nama_barang', 'nama']) || 'Produk',
    pieces_order: pieces,
    box_order: box,
    karton_order: karton,
    hargaorder: toNumber(firstValue(row, ['hargaorder', 'harga_order', 'harga_jual', 'harga'])),
    total_diskon: toNumber(firstValue(row, ['total_diskon', 'total_nilai_discount', 'diskon_total', 'diskon'])),
    konversi_level1: toNumber(firstValue(row, ['konversi_level1', 'konversi1', 'faktor_1']), 1) || 1,
    konversi_level2: toNumber(firstValue(row, ['konversi_level2', 'konversi2', 'faktor_2'])),
    konversi_level3: toNumber(firstValue(row, ['konversi_level3', 'konversi3', 'faktor_3']))
  };
}

function extractOrderDetails(order) {
  return normalizeList(order?.details || order?.list_detail_order || order?.detail_produk || order?.products || []);
}

async function loadRevisionOrder(order) {
  const existingDetails = extractOrderDetails(order);
  if (existingDetails.length) {
    return {
      id_sales_order: String(order.id_sales_order || order.sales_order_id || order.id),
      id_faktur: getInvoiceId(order) || getInvoiceId(order.invoice),
      invoice_label: invoiceLabel(order.invoice || order),
      details: existingDetails.map(buildRevisionDetail)
    };
  }

  const idSalesOrder = String(order.id_sales_order || order.sales_order_id || order.id || '');
  if (!idSalesOrder) return null;
  const params = order.id_order_batch ? { id_order_batch: order.id_order_batch, id_sales_orders: idSalesOrder } : {};
  const response = await getInvoiceDetail(idSalesOrder, params);
  const payload = unwrapResponse(response) || {};
  const details = normalizeList(payload?.list_detail_order || payload?.details || payload?.data || payload);
  const header = payload?.detail_faktur || payload?.header || order.invoice || {};
  return {
    id_sales_order: idSalesOrder,
    id_faktur: getInvoiceId(order) || getInvoiceId(header) || getInvoiceId(order.invoice),
    invoice_label: invoiceLabel(header) || invoiceLabel(order.invoice || order),
    details: details.map(buildRevisionDetail)
  };
}

async function openRevision() {
  if (!selectedRequestId.value) return;
  revisionLoading.value = true;
  detailError.value = '';
  revisionForm.note = '';
  revisionForm.orders = [];
  revisionModalOpen.value = true;
  try {
    const inlineOrders = normalizeList(requestDetail.value?.orders || requestDetail.value?.sales_orders || []);
    const sourceOrders = inlineOrders.length
      ? inlineOrders.map((order) => {
          const matchingInvoice = requestInvoiceRows.value.find((invoice) =>
            getSalesOrderIds(invoice).includes(String(order.id_sales_order || order.sales_order_id || ''))
          );
          return {
            ...order,
            id_faktur: getInvoiceId(order) || getInvoiceId(matchingInvoice),
            invoice: order.invoice || matchingInvoice || order
          };
        })
      : invoiceOrderRows();
    const loadedOrders = await Promise.all(sourceOrders.map(loadRevisionOrder));
    revisionForm.orders = loadedOrders.filter((order) => order && order.details.length);
    if (!revisionForm.orders.length) {
      detailError.value = 'Detail order untuk revisi belum tersedia pada request ini.';
    }
  } catch (error) {
    detailError.value = normalizeError(error, 'Detail faktur untuk revisi belum dapat dimuat.');
  } finally {
    revisionLoading.value = false;
  }
}

function uomName(row, level) {
  const names = [
    ['puom1_nama', 'uom1_nama', 'uom_1_nama', 'uom1', 'satuan'],
    ['puom2_nama', 'uom2_nama', 'uom_2_nama', 'uom2'],
    ['puom3_nama', 'uom3_nama', 'uom_3_nama', 'uom3']
  ];
  const codes = [
    ['puom1_kode', 'uom1_kode', 'uom_1_kode'],
    ['puom2_kode', 'uom2_kode', 'uom_2_kode'],
    ['puom3_kode', 'uom3_kode', 'uom_3_kode']
  ];
  return String(firstValue(row, [...names[level - 1], ...codes[level - 1]]) || (level === 1 ? 'PCS' : '')).trim();
}

function isUomEnabled(row, level) {
  if (level === 1) return true;
  const conversion = toNumber(row?.[`konversi_level${level}`] ?? row?.[`konversi${level}`]);
  return Boolean(uomName(row, level)) || conversion > 0;
}

function uomFields(row) {
  return [
    { key: 'pieces_order', level: 1, label: uomName(row, 1) || 'PCS' },
    { key: 'box_order', level: 2, label: uomName(row, 2) || 'UOM 2' },
    { key: 'karton_order', level: 3, label: uomName(row, 3) || 'UOM 3' }
  ].filter((field) => isUomEnabled(row, field.level));
}

function normalizeNonNegative(row, key) {
  row[key] = Math.max(0, toNumber(row[key]));
}

function revisionPieces(row) {
  return (
    toNumber(row.pieces_order) * (toNumber(row.konversi_level1, 1) || 1) +
    toNumber(row.box_order) * toNumber(row.konversi_level2) +
    toNumber(row.karton_order) * toNumber(row.konversi_level3)
  );
}

function revisionLineTotal(row) {
  return Math.max(0, revisionPieces(row) * toNumber(row.hargaorder) - toNumber(row.total_diskon));
}

function revisionOrderTotal(order) {
  return order.details.reduce((total, row) => total + revisionLineTotal(row), 0);
}

function buildRevisionPayload() {
  const invoicesById = new Map();
  revisionForm.orders.forEach((order) => {
    const invoiceId = String(order.id_faktur || '');
    if (!invoiceId) return;
    if (!invoicesById.has(invoiceId)) invoicesById.set(invoiceId, []);
    invoicesById.get(invoiceId).push({
      id_sales_order: Number(order.id_sales_order),
      details: order.details.map((row) => ({
        id_order_detail: Number(row.id_order_detail),
        pieces_order: Math.max(0, toNumber(row.pieces_order)),
        box_order: Math.max(0, toNumber(row.box_order)),
        karton_order: Math.max(0, toNumber(row.karton_order)),
        hargaorder: Math.max(0, toNumber(row.hargaorder)),
        total_diskon: Math.max(0, toNumber(row.total_diskon))
      }))
    });
  });

  return {
    note: revisionForm.note.trim(),
    invoices: Array.from(invoicesById, ([id_faktur, orders]) => ({ id_faktur: Number(id_faktur), orders }))
  };
}

async function submitRevision() {
  if (!canSubmitRevision.value || !selectedRequestId.value) {
    detailError.value = 'Data revisi belum lengkap. Pastikan setiap baris memiliki detail order.';
    return;
  }
  if (revisionForm.note.trim().length < 3) {
    detailError.value = 'Catatan revisi wajib diisi minimal 3 karakter.';
    return;
  }

  revisionSubmitting.value = true;
  try {
    const response = await submitCancelRealizationRevision(selectedRequestId.value, buildRevisionPayload());
    const body = unwrapResponse(response) || {};
    revisionModalOpen.value = false;
    await refreshSelectedRequest(firstValue(body, ['message']) || 'Revisi faktur tersimpan dan menunggu approval final.');
  } catch (error) {
    detailError.value = normalizeError(error, 'Revisi faktur belum berhasil disimpan.');
  } finally {
    revisionSubmitting.value = false;
  }
}

async function runFinalDecision(action) {
  if (!selectedRequestId.value) return;
  if (action === 'reject' && decisionForm.note.trim().length < 3) {
    detailError.value = 'Catatan pengembalian revisi wajib diisi minimal 3 karakter.';
    return;
  }
  actionSubmitting.value = true;
  detailError.value = '';
  try {
    const payload = { note: decisionForm.note.trim() };
    const response = action === 'approve'
      ? await finalApproveCancelRealizationRequest(selectedRequestId.value, payload)
      : await finalRejectCancelRealizationRequest(selectedRequestId.value, payload);
    const body = unwrapResponse(response) || {};
    decisionForm.note = '';
    await refreshSelectedRequest(firstValue(body, ['message']) || (action === 'approve' ? 'Pembatalan realisasi telah difinalisasi.' : 'Revisi faktur ditolak pada approval final.'));
  } catch (error) {
    detailError.value = normalizeError(error, action === 'approve' ? 'Approval final belum berhasil diproses.' : 'Penolakan final belum berhasil diproses.');
  } finally {
    actionSubmitting.value = false;
  }
}

watch(
  () => filters.id_perusahaan,
  (companyId) => {
    if (!filters.id_cabang || !companyId) return;
    const validBranchIds = new Set(
      getBranchOptionsForCompany(branches.value, authStore, companyId, false, companies.value).map((item) => String(item.value))
    );
    if (!validBranchIds.has(String(filters.id_cabang))) filters.id_cabang = '';
  }
);

onMounted(() => {
  // Referensi filter tidak boleh menahan daftar request. Saat Super User
  // membuka halaman, endpoint daftar langsung berjalan dengan limit ringan.
  void loadReferences();
  void loadRequests();
});
</script>

<template>
  <div class="space-y-5">
    <PageHeader
      title="Batal Realisasi"
      description="Alur terkendali untuk membatalkan realisasi: request, approval awal, revisi faktur, lalu approval final. Stok dan status tidak diubah sebelum finalisasi disetujui."
    >
      <!--
        Keep these controls on the default slot for backwards compatibility
        with the PageHeader bundle currently served in production. That bundle
        only renders its default slot; using #actions makes both controls get
        silently dropped even though this page chunk has loaded.
      -->
      <template #default>
        <button
          class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
          :disabled="pageLoading"
          @click="loadRequests"
        >
          {{ pageLoading ? 'Memuat...' : 'Muat Ulang' }}
        </button>
        <button
          class="rounded-xl bg-rose-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="referenceLoading"
          @click="openCreateRequest"
        >
          + Ajukan Batal Realisasi
        </button>
      </template>
    </PageHeader>

    <section class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      <article v-for="step in processSteps" :key="step.number" class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <p class="text-xs font-black tracking-[0.22em] text-rose-500">{{ step.number }}</p>
        <h2 class="mt-2 font-bold text-slate-900 dark:text-white">{{ step.title }}</h2>
        <p class="mt-1 text-sm leading-5 text-slate-500 dark:text-slate-400">{{ step.note }}</p>
      </article>
    </section>

    <AppFilterBar v-model="filters" :fields="filterFields" @submit="loadRequests" @reset="resetFilters" />

    <p v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
      {{ errorMessage }}
    </p>
    <p v-else-if="referenceError" class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-100">
      {{ referenceError }}
    </p>
    <p v-else-if="feedback" class="rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-100">
      {{ feedback }}
    </p>

    <section class="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
      <article class="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <p class="text-xs font-bold uppercase tracking-[0.18em] text-slate-400">Total Request</p>
        <p class="mt-2 text-2xl font-black text-slate-900 dark:text-white">{{ requestSummary.total }}</p>
      </article>
      <article class="rounded-2xl border border-amber-200 bg-amber-50 p-4 dark:border-amber-500/30 dark:bg-amber-500/10">
        <p class="text-xs font-bold uppercase tracking-[0.18em] text-amber-700 dark:text-amber-200">Approval Awal</p>
        <p class="mt-2 text-2xl font-black text-amber-800 dark:text-amber-100">{{ requestSummary.pending }}</p>
      </article>
      <article class="rounded-2xl border border-sky-200 bg-sky-50 p-4 dark:border-sky-500/30 dark:bg-sky-500/10">
        <p class="text-xs font-bold uppercase tracking-[0.18em] text-sky-700 dark:text-sky-200">Menunggu Revisi</p>
        <p class="mt-2 text-2xl font-black text-sky-800 dark:text-sky-100">{{ requestSummary.revision }}</p>
      </article>
      <article class="rounded-2xl border border-violet-200 bg-violet-50 p-4 dark:border-violet-500/30 dark:bg-violet-500/10">
        <p class="text-xs font-bold uppercase tracking-[0.18em] text-violet-700 dark:text-violet-200">Finalisasi</p>
        <p class="mt-2 text-2xl font-black text-violet-800 dark:text-violet-100">{{ requestSummary.final }}</p>
      </article>
      <article class="rounded-2xl border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-500/30 dark:bg-emerald-500/10">
        <p class="text-xs font-bold uppercase tracking-[0.18em] text-emerald-700 dark:text-emerald-200">Selesai</p>
        <p class="mt-2 text-2xl font-black text-emerald-800 dark:text-emerald-100">{{ requestSummary.completed }}</p>
      </article>
    </section>

    <section class="space-y-3">
      <div class="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 class="text-lg font-bold text-slate-900 dark:text-white">Daftar Request</h2>
          <p class="text-sm text-slate-500 dark:text-slate-400">
            {{ hasLoadedRequests
              ? `Menampilkan maksimal ${REQUEST_LIST_LIMIT} request terbaru sesuai filter. Klik satu request untuk melihat faktur, audit, dan tindakan pada tahapnya.`
              : 'Tentukan filter lalu klik Terapkan untuk memuat daftar request.' }}
          </p>
        </div>
        <p class="text-xs text-slate-500 dark:text-slate-400">{{ requestSummary.rejected }} request ditolak pada filter ini.</p>
      </div>
      <AppTable
        :columns="requestTableColumns"
        :rows="requestTableRows"
        :loading="pageLoading"
        :selected-key="selectedRequestId"
        row-key="row_key"
        clickable-rows
        empty-message="Belum ada request pembatalan realisasi."
        @row-click="openRequest"
      />
    </section>

    <AppModal
      :open="createModalOpen"
      title="Ajukan Batal Realisasi"
      description="Cari lalu centang faktur yang telah selesai direalisasi. Request tidak langsung mengubah stok atau status faktur."
      size="6xl"
      @close="createModalOpen = false"
    >
      <div class="space-y-5">
        <div class="rounded-2xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-950/50">
          <div class="flex flex-wrap items-end justify-between gap-3">
            <label class="min-w-[260px] flex-1">
              <span class="text-xs font-bold uppercase tracking-[0.16em] text-slate-400">Cari Faktur Selesai Realisasi</span>
              <input v-model="candidateFilters.q" class="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none focus:border-rose-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" placeholder="Nomor faktur, SO, atau nama customer" @keyup.enter="loadCancelRealizationCandidates">
            </label>
            <button
              class="rounded-xl border border-slate-300 px-3 py-2.5 text-sm font-semibold text-slate-700 hover:bg-white disabled:opacity-60 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
              :disabled="invoiceLoading"
              @click="loadCancelRealizationCandidates"
            >
              {{ invoiceLoading ? 'Memuat...' : 'Cari Faktur' }}
            </button>
          </div>
          <p class="mt-3 text-xs text-slate-500 dark:text-slate-400">
            Kandidat berasal dari faktur yang sudah selesai direalisasi. Satu request hanya dapat berisi faktur dari cabang yang sama.
          </p>
        </div>

        <div>
          <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 class="font-bold text-slate-900 dark:text-white">1. Pilih Faktur Selesai Realisasi</h3>
              <p class="text-sm text-slate-500 dark:text-slate-400">Faktur yang dicentang akan berada dalam satu request yang sama.</p>
            </div>
            <span class="rounded-full bg-rose-100 px-3 py-1 text-xs font-bold text-rose-700 dark:bg-rose-500/15 dark:text-rose-200">{{ selectedCandidateCount }} dipilih</span>
          </div>
          <div v-if="invoiceLoading" class="rounded-2xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">Memuat kandidat faktur...</div>
          <div v-else-if="!candidateInvoiceRows.length" class="rounded-2xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">Tidak ada faktur selesai realisasi yang dapat diajukan.</div>
          <div v-else-if="candidateInvoiceRows.length" class="overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-800">
            <div class="overflow-x-auto">
              <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
                <thead class="bg-slate-50 dark:bg-slate-950">
                  <tr>
                    <th class="w-14 px-4 py-3 text-left text-xs font-bold uppercase tracking-wide text-slate-400">Pilih</th>
                    <th class="px-4 py-3 text-left text-xs font-bold uppercase tracking-wide text-slate-400">Faktur / SO</th>
                    <th class="px-4 py-3 text-left text-xs font-bold uppercase tracking-wide text-slate-400">Customer</th>
                    <th class="px-4 py-3 text-right text-xs font-bold uppercase tracking-wide text-slate-400">Total</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-slate-100 bg-white dark:divide-slate-800 dark:bg-slate-900">
                  <tr v-for="row in candidateInvoiceRows" :key="row.row_key" :class="isInvoiceSelected(row) ? 'bg-rose-50/70 dark:bg-rose-500/10' : ''">
                    <td class="px-4 py-3">
                      <input type="checkbox" :checked="isInvoiceSelected(row)" :disabled="!row.can_select" class="h-4 w-4 rounded border-slate-300 text-rose-600 focus:ring-rose-500" @change="toggleInvoice(row)">
                    </td>
                    <td class="px-4 py-3 font-semibold text-slate-800 dark:text-slate-100">
                      {{ row.invoice_label }}
                      <p v-if="!row.can_select" class="mt-1 text-xs font-normal text-rose-600 dark:text-rose-300">ID faktur tidak tersedia.</p>
                    </td>
                    <td class="px-4 py-3 text-slate-600 dark:text-slate-300">{{ row.customer_label }}</td>
                    <td class="px-4 py-3 text-right font-semibold text-slate-800 dark:text-slate-100">{{ row.total_label }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <label class="block">
          <span class="text-sm font-bold text-slate-800 dark:text-slate-100">2. Alasan Pembatalan <span class="text-rose-600">*</span></span>
          <textarea v-model="createForm.reason" rows="4" maxlength="1000" placeholder="Contoh: salah realisasi qty saat barang diterima, perlu perbaikan faktur sebelum proses berikutnya." class="mt-2 w-full rounded-2xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-rose-500 focus:ring-2 focus:ring-rose-100 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:focus:ring-rose-500/20" />
          <span class="mt-1 block text-xs text-slate-500 dark:text-slate-400">{{ createForm.reason.length }}/1000 karakter</span>
        </label>
      </div>
      <template #footer>
        <div class="flex flex-wrap justify-end gap-2">
          <button class="rounded-xl border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800" @click="createModalOpen = false">Batal</button>
          <button class="rounded-xl bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-60" :disabled="!canSubmitCreate" @click="submitCreateRequest">
            {{ createSubmitting ? 'Mengajukan...' : `Ajukan ${selectedCandidateCount || ''} Faktur` }}
          </button>
        </div>
      </template>
    </AppModal>

    <AppModal
      :open="detailModalOpen"
      title="Detail Batal Realisasi"
      description="Audit request, faktur terdampak, dan jalankan tindakan sesuai tahap workflow."
      size="6xl"
      @close="detailModalOpen = false"
    >
      <div class="space-y-5">
        <p v-if="detailError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-100">{{ detailError }}</p>
        <div v-if="requestDetailLoading" class="rounded-2xl border border-dashed border-slate-300 p-10 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">Memuat detail request...</div>
        <template v-else>
          <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <article class="rounded-2xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-950/60">
              <p class="text-xs font-bold uppercase tracking-[0.16em] text-slate-400">Kode Request</p>
              <p class="mt-2 font-bold text-slate-900 dark:text-white">{{ getRequestCode(requestDetail) || getRequestCode(selectedRequest) || '-' }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-950/60">
              <p class="text-xs font-bold uppercase tracking-[0.16em] text-slate-400">Status</p>
              <p :class="['mt-2 font-bold', statusMeta(selectedRequestStatus).className]">{{ statusMeta(selectedRequestStatus).label }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-950/60">
              <p class="text-xs font-bold uppercase tracking-[0.16em] text-slate-400">Pengaju</p>
              <p class="mt-2 font-bold text-slate-900 dark:text-white">{{ firstValue(requestDetail, ['nama_pengaju', 'requester_name', 'requested_by_name', 'nama_user']) || firstValue(selectedRequest, ['nama_pengaju', 'requester_name', 'requested_by_name', 'nama_user']) || '-' }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-950/60">
              <p class="text-xs font-bold uppercase tracking-[0.16em] text-slate-400">Tanggal</p>
              <p class="mt-2 font-bold text-slate-900 dark:text-white">{{ formatDateTime(firstValue(requestDetail, ['created_at', 'tanggal_request', 'requested_at']) || firstValue(selectedRequest, ['created_at', 'tanggal_request', 'requested_at'])) }}</p>
            </article>
          </div>

          <section class="rounded-2xl border border-amber-200 bg-amber-50 p-4 dark:border-amber-500/30 dark:bg-amber-500/10">
            <p class="text-xs font-bold uppercase tracking-[0.16em] text-amber-700 dark:text-amber-200">Alasan Pembatalan</p>
            <p class="mt-2 whitespace-pre-line text-sm leading-6 text-amber-900 dark:text-amber-100">{{ firstValue(requestDetail, ['reason', 'alasan', 'keterangan', 'keterangan_batal']) || firstValue(selectedRequest, ['reason', 'alasan', 'keterangan', 'keterangan_batal']) || '-' }}</p>
          </section>

          <section>
            <div class="mb-3 flex items-end justify-between gap-3">
              <div>
                <h3 class="font-bold text-slate-900 dark:text-white">Faktur Terdampak</h3>
                <p class="text-sm text-slate-500 dark:text-slate-400">Revisi hanya akan tersedia setelah approval awal diterima.</p>
              </div>
              <span class="text-xs text-slate-500 dark:text-slate-400">{{ detailInvoiceTableRows.length }} faktur</span>
            </div>
            <div class="overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-800">
              <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
                  <thead class="bg-slate-50 dark:bg-slate-950">
                    <tr>
                      <th class="px-4 py-3 text-left text-xs font-bold uppercase tracking-wide text-slate-400">Faktur / SO</th>
                      <th class="px-4 py-3 text-left text-xs font-bold uppercase tracking-wide text-slate-400">Customer</th>
                      <th class="px-4 py-3 text-right text-xs font-bold uppercase tracking-wide text-slate-400">Total</th>
                      <th class="px-4 py-3 text-left text-xs font-bold uppercase tracking-wide text-slate-400">Status</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-slate-100 bg-white dark:divide-slate-800 dark:bg-slate-900">
                    <tr v-if="!detailInvoiceTableRows.length"><td colspan="4" class="px-4 py-8 text-center text-sm text-slate-500 dark:text-slate-400">Belum ada rincian faktur dari server.</td></tr>
                    <tr v-for="row in detailInvoiceTableRows" v-else :key="row.row_key">
                      <td class="px-4 py-3 font-semibold text-slate-800 dark:text-slate-100">{{ row.invoice_label }}</td>
                      <td class="px-4 py-3 text-slate-600 dark:text-slate-300">{{ row.customer_label }}</td>
                      <td class="px-4 py-3 text-right font-semibold text-slate-800 dark:text-slate-100">{{ row.total_label }}</td>
                      <td class="px-4 py-3 text-slate-600 dark:text-slate-300">{{ row.status_label }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </section>

          <section v-if="selectedRequestStage === 'approval' || selectedRequestStage === 'final'" class="rounded-2xl border border-slate-200 p-4 dark:border-slate-800">
            <label class="block">
              <span class="text-sm font-bold text-slate-800 dark:text-slate-100">Catatan Keputusan</span>
              <textarea v-model="decisionForm.note" rows="3" maxlength="1000" placeholder="Catatan approval atau alasan penolakan (opsional, tetapi disarankan untuk audit)." class="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:focus:ring-brand-500/20" />
            </label>
            <div class="mt-4 flex flex-wrap justify-end gap-2">
              <template v-if="selectedRequestStage === 'approval'">
                <template v-if="canApproveSelected">
                  <button class="rounded-xl border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-60 dark:border-rose-500/50 dark:text-rose-200 dark:hover:bg-rose-500/10" :disabled="actionSubmitting" @click="runInitialDecision('reject')">Tolak Request</button>
                  <button class="rounded-xl bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-700 disabled:opacity-60" :disabled="actionSubmitting" @click="runInitialDecision('approve')">{{ actionSubmitting ? 'Memproses...' : 'Setujui Awal' }}</button>
                </template>
                <p v-else class="max-w-2xl text-sm leading-6 text-amber-700 dark:text-amber-200">{{ initialApprovalMessage }}</p>
              </template>
              <template v-else>
                <template v-if="canFinalApproveSelected">
                  <button class="rounded-xl border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-60 dark:border-rose-500/50 dark:text-rose-200 dark:hover:bg-rose-500/10" :disabled="actionSubmitting" @click="runFinalDecision('reject')">Kembalikan Revisi</button>
                  <button class="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-60" :disabled="actionSubmitting" @click="runFinalDecision('approve')">{{ actionSubmitting ? 'Memproses...' : 'Setujui & Finalisasi' }}</button>
                </template>
                <p v-else class="max-w-2xl text-sm leading-6 text-amber-700 dark:text-amber-200">{{ finalApprovalMessage }}</p>
              </template>
            </div>
          </section>

          <section v-else-if="selectedRequestStage === 'revision'" class="rounded-2xl border border-sky-200 bg-sky-50 p-4 dark:border-sky-500/30 dark:bg-sky-500/10">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 class="font-bold text-sky-900 dark:text-sky-100">Approval awal diterima</h3>
                <p class="mt-1 text-sm text-sky-800 dark:text-sky-200">Periksa kembali qty, harga, dan diskon sebelum request masuk ke approval final.</p>
              </div>
              <button v-if="canEditSelected" class="rounded-xl bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-700" @click="openRevision">Buka Revisi Faktur</button>
              <p v-else class="text-sm text-sky-800 dark:text-sky-200">Menunggu pengaju atau petugas revisi yang berwenang.</p>
            </div>
          </section>

          <section v-if="detailAuditRows.length">
            <h3 class="mb-3 font-bold text-slate-900 dark:text-white">Audit Workflow</h3>
            <div class="overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-800">
              <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
                  <thead class="bg-slate-50 dark:bg-slate-950"><tr><th class="px-4 py-3 text-left text-xs font-bold uppercase tracking-wide text-slate-400">Waktu</th><th class="px-4 py-3 text-left text-xs font-bold uppercase tracking-wide text-slate-400">User</th><th class="px-4 py-3 text-left text-xs font-bold uppercase tracking-wide text-slate-400">Aksi</th><th class="px-4 py-3 text-left text-xs font-bold uppercase tracking-wide text-slate-400">Catatan</th></tr></thead>
                  <tbody class="divide-y divide-slate-100 bg-white dark:divide-slate-800 dark:bg-slate-900"><tr v-for="row in detailAuditRows" :key="row.row_key"><td class="px-4 py-3 text-slate-600 dark:text-slate-300">{{ row.at_label }}</td><td class="px-4 py-3 font-semibold text-slate-800 dark:text-slate-100">{{ row.actor_label }}</td><td class="px-4 py-3 text-slate-600 dark:text-slate-300">{{ row.action_label }}</td><td class="px-4 py-3 text-slate-600 dark:text-slate-300">{{ row.note_label }}</td></tr></tbody>
                </table>
              </div>
            </div>
          </section>
        </template>
      </div>
      <template #footer>
        <div class="flex justify-end"><button class="rounded-xl border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800" @click="detailModalOpen = false">Tutup</button></div>
      </template>
    </AppModal>

    <AppModal
      :open="revisionModalOpen"
      title="Revisi Faktur sebelum Finalisasi"
      description="Periksa setiap baris produk dari faktur yang terdampak. Nilai ini akan dikirim sebagai usulan revisi, belum mengubah stok sampai approval final disetujui."
      size="7xl"
      @close="revisionModalOpen = false"
    >
      <div class="space-y-5">
        <div v-if="revisionLoading" class="rounded-2xl border border-dashed border-slate-300 p-10 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">Memuat detail faktur untuk revisi...</div>
        <template v-else>
          <p v-if="!revisionForm.orders.length" class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-100">Tidak ada detail order yang dapat direvisi pada request ini.</p>
          <article v-for="order in revisionForm.orders" :key="order.id_sales_order" class="overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-800">
            <header class="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-950">
              <div>
                <p class="text-xs font-bold uppercase tracking-[0.16em] text-slate-400">Sales Order</p>
                <h3 class="mt-1 font-bold text-slate-900 dark:text-white">{{ order.invoice_label || `SO ${order.id_sales_order}` }}</h3>
              </div>
              <p class="text-sm font-bold text-slate-700 dark:text-slate-200">Estimasi total: {{ formatCurrency(revisionOrderTotal(order)) }}</p>
            </header>
            <div class="overflow-x-auto">
              <table class="min-w-[900px] w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
                <thead class="bg-slate-50 dark:bg-slate-950"><tr><th class="px-4 py-3 text-left text-xs font-bold uppercase tracking-wide text-slate-400">Produk</th><th class="px-4 py-3 text-left text-xs font-bold uppercase tracking-wide text-slate-400">Qty per UOM</th><th class="px-4 py-3 text-right text-xs font-bold uppercase tracking-wide text-slate-400">Harga/PCS</th><th class="px-4 py-3 text-right text-xs font-bold uppercase tracking-wide text-slate-400">Diskon</th><th class="px-4 py-3 text-right text-xs font-bold uppercase tracking-wide text-slate-400">Estimasi</th></tr></thead>
                <tbody class="divide-y divide-slate-100 bg-white dark:divide-slate-800 dark:bg-slate-900">
                  <tr v-for="row in order.details" :key="row.row_key">
                    <td class="px-4 py-3 align-top"><p class="font-semibold text-slate-900 dark:text-white">{{ row.kode_sku }}</p><p class="mt-1 text-slate-600 dark:text-slate-300">{{ row.nama_produk }}</p></td>
                    <td class="px-4 py-3 align-top"><div class="flex flex-wrap gap-2"><label v-for="field in uomFields(row)" :key="field.key" class="w-28"><span class="mb-1 block text-[11px] font-bold uppercase tracking-wide text-slate-400">{{ field.label }}</span><input v-model.number="row[field.key]" type="number" min="0" step="1" class="w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm text-slate-900 outline-none focus:border-brand-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" @blur="normalizeNonNegative(row, field.key)"></label></div></td>
                    <td class="px-4 py-3 align-top text-right"><input v-model.number="row.hargaorder" type="number" min="0" step="1" class="w-32 rounded-lg border border-slate-300 bg-white px-2 py-2 text-right text-sm text-slate-900 outline-none focus:border-brand-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" @blur="normalizeNonNegative(row, 'hargaorder')"></td>
                    <td class="px-4 py-3 align-top text-right"><input v-model.number="row.total_diskon" type="number" min="0" step="1" class="w-32 rounded-lg border border-slate-300 bg-white px-2 py-2 text-right text-sm text-slate-900 outline-none focus:border-brand-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" @blur="normalizeNonNegative(row, 'total_diskon')"></td>
                    <td class="px-4 py-3 align-top text-right font-bold text-slate-900 dark:text-white">{{ formatCurrency(revisionLineTotal(row)) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </article>
          <label class="block"><span class="text-sm font-bold text-slate-800 dark:text-slate-100">Catatan Revisi</span><textarea v-model="revisionForm.note" rows="3" maxlength="1000" placeholder="Jelaskan perubahan qty, harga, atau diskon bila diperlukan." class="mt-2 w-full rounded-2xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:focus:ring-brand-500/20" /></label>
        </template>
      </div>
      <template #footer>
        <div class="flex flex-wrap justify-end gap-2"><button class="rounded-xl border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800" @click="revisionModalOpen = false">Batal</button><button class="rounded-xl bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-60" :disabled="!canSubmitRevision" @click="submitRevision">{{ revisionSubmitting ? 'Menyimpan...' : 'Kirim Revisi ke Finalisasi' }}</button></div>
      </template>
    </AppModal>
  </div>
</template>
