<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { getBranches, getCompanies } from '@/api/master';
import {
  approveCustomerAdvance,
  getCustomerAdvanceDetail,
  getCustomerAdvanceEligibleInvoices,
  getCustomerAdvances,
  rejectCustomerAdvance,
  useCustomerAdvance
} from '@/api/finance';
import { useAuthStore } from '@/stores/auth';
import { workflowGet } from '@/api/paymentWorkflow';
import { paymentPermission } from '@/utils/paymentPermissions';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getLoginCompanyId, isSuperUser, branchMatchesCompany } from '@/utils/accessScope';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const numberFormatter = new Intl.NumberFormat('id-ID', { maximumFractionDigits: 2 });

const filters = reactive({
  id_perusahaan: '',
  id_cabang: '',
  status: '',
  search: ''
});
const approvalForm = reactive({ catatan: '' });
const useForm = reactive({ allocations: [], catatan: '' });
const rows = ref([]);
const companyRows = ref([]);
const branchRows = ref([]);
const selectedRow = ref(null);
const detail = ref(null);
const eligibleInvoices = ref([]);
const detailOpen = ref(false);
const useOpen = ref(false);
const pageError = ref('');
const actionError = ref('');
const feedback = ref('');
const loading = reactive({
  refs: false,
  list: false,
  detail: false,
  approve: false,
  reject: false,
  eligible: false,
  use: false
});

const fallbackCompanyId = computed(() => getLoginCompanyId(auth.user));
const fallbackBranchId = computed(() => getLoginBranchId(auth.user));
const canApprove = computed(() => (
  isSuperUser(auth)
  || auth.hasPermission('finance.customer-advances.approve')
  || auth.hasPermission('finance.recap.approve')
));
const canUse = computed(() => (
  isSuperUser(auth)
  || auth.hasPermission('finance.customer-advances.use')
  || auth.hasPermission('finance.recap.update')
));
const canUseReceipt = computed(() => paymentPermission(auth.permissions || [],'finance.receipts.create') === true);
const fromReceipt = row => row?.origin === 'RECEIPT';
function openReceiptPayment() { detailOpen.value=false;router.push('/finance/receipt-workflow'); }

const companyOptions = computed(() => [
  { value: '', label: 'Semua perusahaan' },
  ...companyRows.value.map((row) => ({
    value: String(row.id || row.id_perusahaan || ''),
    label: `${row.kode || row.kode_perusahaan || ''}${row.kode || row.kode_perusahaan ? ' - ' : ''}${row.nama || row.nama_perusahaan || 'Perusahaan'}`
  })).filter((row) => row.value)
]);

const branchOptions = computed(() =>
  branchRows.value
    .filter((item) => {
      // Jika tidak ada perusahaan yang dipilih di filter, tampilkan semua cabang
      if (!filters.id_perusahaan) return true;
      
      // Gunakan fungsi bawaan yang sudah terbukti berhasil mendeteksi relasi cabang
      return branchMatchesCompany(item, filters.id_perusahaan);
    })
    .map((item) => {
      // Tangkap ID, Kode, dan Nama cabang dengan aman
      const branchId = item.id_cabang ?? item.branch_id ?? item.id;
      const branchCode = item.kode_cabang ?? item.kode ?? '';
      const branchName = item.nama_cabang ?? item.nama ?? `Cabang ${branchId}`;

      return {
        value: String(branchId || ''),
        label: `${branchCode ? `${branchCode} - ` : ''}${branchName}`
      };
    })
    // Buang opsi yang kosong atau tidak valid
    .filter((opt) => opt.value && opt.value !== 'undefined')
);

const statusOptions = [
  { value: '', label: 'Semua status' },
  { value: 'PENDING_APPROVAL', label: 'Menunggu approval' },
  { value: 'APPROVED', label: 'Aktif / dapat dipakai' },
  { value: 'PARTIAL', label: 'Dipakai sebagian' },
  { value: 'USED', label: 'Sudah digunakan' },
  { value: 'RESERVED', label: 'Ditahan draft kuitansi' },
  { value: 'CANCELLED', label: 'Dibatalkan' },
  { value: 'REJECTED', label: 'Ditolak' }
];

function formatCurrency(value) {
  return `Rp ${numberFormatter.format(Number(value || 0))}`;
}

function formatDate(value) {
  if (!value) return '-';
  const text = String(value);
  const localDate = text.match(/\d{4}-\d{2}-\d{2}/)?.[0];
  if (localDate) {
    const [year, month, day] = localDate.split('-').map(Number);
    return new Intl.DateTimeFormat('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(year, month - 1, day));
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? text.slice(0, 10) : date.toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' });
}

function advanceId(row = {}) {
  return row.id_uang_muka ?? row.id_customer_advance ?? row.id_advance ?? row.advance_id ?? row.id ?? null;
}

function advanceAmount(row = {}) {
  return Number(row.nominal_awal ?? row.nominal_uang_muka ?? row.nominal ?? row.jumlah ?? 0);
}

function advanceUsed(row = {}) {
  return Number(row.nominal_terpakai ?? row.total_dipakai ?? row.nominal_digunakan ?? 0);
}

function advanceRemaining(row = {}) {
  const explicit = row.sisa_nominal ?? row.sisa_uang_muka ?? row.sisa;
  return Math.max(0, Number(explicit ?? (advanceAmount(row) - advanceUsed(row))));
}

function advanceStatus(row = {}) {
  const raw = String(row.status_uang_muka ?? row.status_approval ?? row.status ?? '').trim().toUpperCase();
  // Workflow status is exact (including sub-rupiah balances), not rounded to 0.5.
  if (fromReceipt(row) && ['APPROVED','PARTIAL','USED','RESERVED','CANCELLED'].includes(raw)) return raw;
  if (['CANCELLED','RESERVED'].includes(raw)) return raw;
  if (['PENDING', 'PENDING_APPROVAL', 'MENUNGGU_APPROVAL', 'MENUNGGU PERSETUJUAN'].includes(raw)) return 'PENDING_APPROVAL';
  if (['REJECTED', 'DITOLAK', 'CANCELED', 'BATAL'].includes(raw)) return 'REJECTED';
  if (['USED', 'HABIS', 'CLOSED', 'SELESAI'].includes(raw) || (advanceRemaining(row) <= 0.5 && advanceAmount(row) > 0)) return 'USED';
  if (['PARTIAL', 'SEBAGIAN'].includes(raw) || advanceUsed(row) > 0.5) return 'PARTIAL';
  return 'APPROVED';
}

function advanceStatusLabel(row = {}) {
  const status = advanceStatus(row);
  return {
    PENDING_APPROVAL: 'Menunggu approval',
    APPROVED: 'Aktif',
    PARTIAL: 'Dipakai sebagian',
    USED: 'Sudah digunakan',
    RESERVED: 'Ditahan draft',
    CANCELLED: 'Dibatalkan',
    REJECTED: 'Ditolak'
  }[status] || status;
}

function statusBadge(row) {
  const status = advanceStatus(row);
  const classes = {
    RESERVED: 'inline-flex rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800 dark:bg-amber-300 dark:text-slate-950',
    CANCELLED: 'inline-flex rounded-full bg-slate-200 px-3 py-1 text-xs font-semibold text-slate-700 dark:bg-slate-700 dark:text-slate-100',
    PENDING_APPROVAL: 'inline-flex rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800 dark:bg-amber-300 dark:text-slate-950',
    APPROVED: 'inline-flex rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-800 dark:bg-emerald-300 dark:text-slate-950',
    PARTIAL: 'inline-flex rounded-full bg-sky-100 px-3 py-1 text-xs font-semibold text-sky-800 dark:bg-sky-300 dark:text-slate-950',
    USED: 'inline-flex rounded-full bg-slate-200 px-3 py-1 text-xs font-semibold text-slate-700 dark:bg-slate-700 dark:text-slate-100',
    REJECTED: 'inline-flex rounded-full bg-rose-100 px-3 py-1 text-xs font-semibold text-rose-800 dark:bg-rose-300 dark:text-slate-950'
  };
  return { text: advanceStatusLabel(row), className: classes[status] };
}

function normalizeAdvance(row = {}) {
  return {
    ...row,
    id_uang_muka: advanceId(row),
    kode_uang_muka: row.kode_uang_muka || row.kode_advance || row.kode || `UM-${advanceId(row) || '-'}`,
    nominal_awal: advanceAmount(row),
    nominal_terpakai: advanceUsed(row),
    sisa_nominal: advanceRemaining(row),
    status_normalized: advanceStatus(row)
  };
}

const summary = computed(() => ({
  total: rows.value.reduce((total, row) => total + advanceAmount(row), 0),
  pending: rows.value.filter((row) => advanceStatus(row) === 'PENDING_APPROVAL').reduce((total, row) => total + advanceRemaining(row), 0),
  active: rows.value.filter((row) => ['APPROVED', 'PARTIAL'].includes(advanceStatus(row))).reduce((total, row) => total + advanceRemaining(row), 0),
  used: rows.value.reduce((total, row) => total + advanceUsed(row), 0)
}));

const columns = [
  { key: 'kode_uang_muka', label: 'Kode Uang Muka' },
  { key: 'nama_customer', label: 'Customer', render: (row) => row.nama_customer || row.customer_name || '-' },
  { key: 'kode_mutasi', label: 'Dokumen Sumber', render: (row) => fromReceipt(row) ? `Kuitansi ${row.source_reference}` : row.kode_mutasi || row.no_referensi || '-' },
  { key: 'tanggal_mutasi', label: 'Tanggal', render: (row) => formatDate(row.tanggal_mutasi || row.tanggal) },
  { key: 'nominal_awal', label: 'Nilai Awal', render: (row) => formatCurrency(row.nominal_awal) },
  { key: 'nominal_terpakai', label: 'Terpakai', render: (row) => formatCurrency(row.nominal_terpakai) },
  { key: 'nominal_ditahan', label: 'Ditahan Draft', render: (row) => formatCurrency(row.nominal_ditahan) },
  { key: 'sisa_nominal', label: 'Sisa Tersedia', render: (row) => formatCurrency(row.sisa_nominal) },
  { key: 'status', label: 'Status', render: (row) => statusBadge(row) }
];

const useRows = computed(() => useForm.allocations
  .map((allocation) => ({
    ...allocation,
    invoice: eligibleInvoices.value.find((invoice) => String(invoice.id_faktur) === String(allocation.id_faktur)) || null,
    nominal_pakai: Number(allocation.nominal_pakai || 0)
  }))
  .filter((allocation) => allocation.invoice));
const totalUseAmount = computed(() => useRows.value.reduce((total, allocation) => total + Math.max(0, allocation.nominal_pakai), 0));
const selectedAdvance = computed(() => detail.value || selectedRow.value || null);
const useExceedsAdvance = computed(() => totalUseAmount.value > advanceRemaining(selectedAdvance.value || {}) + 0.5);
const useHasInvalidAmount = computed(() => useRows.value.some((allocation) => (
  allocation.nominal_pakai <= 0 || allocation.nominal_pakai > Number(allocation.invoice?.sisa_tagihan ?? allocation.invoice?.nominal_tersedia ?? 0) + 0.5
)));
const canSubmitUse = computed(() => Boolean(
  selectedAdvance.value && useRows.value.length && totalUseAmount.value > 0 && !useExceedsAdvance.value && !useHasInvalidAmount.value
));

function isInvoiceSelected(invoice) {
  return useForm.allocations.some((item) => String(item.id_faktur) === String(invoice.id_faktur));
}

function useEntryFor(invoice) {
  return useForm.allocations.find((item) => String(item.id_faktur) === String(invoice.id_faktur));
}

function toggleInvoice(invoice, selected) {
  if (!selected) {
    useForm.allocations = useForm.allocations.filter((item) => String(item.id_faktur) !== String(invoice.id_faktur));
    return;
  }
  if (isInvoiceSelected(invoice)) return;
  const available = Math.max(0, advanceRemaining(selectedAdvance.value || {}) - totalUseAmount.value);
  const due = Number(invoice.sisa_tagihan ?? invoice.nominal_tersedia ?? 0);
  useForm.allocations.push({ id_faktur: invoice.id_faktur, nominal_pakai: Math.min(available, due) });
}

function setUseAmount(invoice, value) {
  const entry = useEntryFor(invoice);
  if (!entry) return;
  const maximum = Number(invoice.sisa_tagihan ?? invoice.nominal_tersedia ?? 0);
  entry.nominal_pakai = Math.max(0, Math.min(Number(value || 0), maximum));
}

function applyUseFifo() {
  let remaining = advanceRemaining(selectedAdvance.value || {});
  const rows = [];
  eligibleInvoices.value.forEach((invoice) => {
    if (remaining <= 0.5) return;
    const due = Number(invoice.sisa_tagihan ?? invoice.nominal_tersedia ?? 0);
    const nominal = Math.min(remaining, due);
    if (nominal <= 0) return;
    rows.push({ id_faktur: invoice.id_faktur, nominal_pakai: nominal });
    remaining -= nominal;
  });
  useForm.allocations = rows;
}

async function loadReferences() {
  loading.refs = true;
  try {
    const [companies, branches] = await Promise.all([getCompanies(), getBranches()]);
    companyRows.value = normalizeList(unwrapResponse(companies));
    branchRows.value = normalizeList(unwrapResponse(branches));
    if (fallbackCompanyId.value) filters.id_perusahaan = String(fallbackCompanyId.value);
    if (fallbackBranchId.value) filters.id_cabang = String(fallbackBranchId.value);
  } catch (error) {
    pageError.value = normalizeError(error, 'Referensi perusahaan dan cabang belum dapat dimuat.');
  } finally {
    loading.refs = false;
  }
}

let listSequence=0;
async function loadRows() {
  const sequence=++listSequence;
  loading.list = true;
  pageError.value = '';
  try {
    const params = {
      id_perusahaan: filters.id_perusahaan || undefined,
      id_cabang: filters.id_cabang || undefined,
      status: filters.status || undefined,
      search: filters.search.trim() || undefined,
      limit: 250
    };
    // Distinct source identities; receipt advances are not copied into the old ledger.
    const responses = await Promise.all([
      ['RESERVED','CANCELLED'].includes(params.status) ? Promise.resolve({data:[]}) : getCustomerAdvances(params),
      workflowGet('customer-advances',params)
    ]);
    if(sequence!==listSequence)return;
    rows.value = responses.flatMap(response=>normalizeList(unwrapResponse(response))).map(normalizeAdvance)
      .sort((a,b)=>new Date(b.tanggal || b.created_at || b.tanggal_mutasi || 0)-new Date(a.tanggal || a.created_at || a.tanggal_mutasi || 0));
  } catch (error) {
    if(sequence!==listSequence)return;
    rows.value = [];
    pageError.value = normalizeError(error, 'Daftar Uang Muka Customer belum dapat dimuat.');
  } finally {
    if(sequence===listSequence)loading.list = false;
  }
}

function resetFilters() {
  filters.id_perusahaan = String(fallbackCompanyId.value || '');
  filters.id_cabang = String(fallbackBranchId.value || '');
  filters.status = '';
  filters.search = '';
  loadRows();
}

async function openDetail(row) {
  selectedRow.value = row;
  detail.value = row;
  approvalForm.catatan = '';
  actionError.value = '';
  feedback.value = '';
  detailOpen.value = true;
  loading.detail = true;
  try {
    const response = fromReceipt(row) ? await workflowGet(`customer-advances/${row.id_source}`) : await getCustomerAdvanceDetail(advanceId(row));
    const payload = unwrapResponse(response) || {};
    detail.value = normalizeAdvance(payload.data || payload);
  } catch (error) {
    actionError.value = normalizeError(error, 'Detail uang muka belum dapat dimuat.');
  } finally {
    loading.detail = false;
  }
}

async function approveSelected() {
  if (!selectedAdvance.value || !canApprove.value) return;
  loading.approve = true;
  actionError.value = '';
  try {
    const response = await approveCustomerAdvance(advanceId(selectedAdvance.value), {
      catatan_approval: approvalForm.catatan.trim() || undefined
    });
    const payload = unwrapResponse(response) || {};
    feedback.value = payload.message || 'Uang Muka Customer disetujui dan siap digunakan.';
    await loadRows();
    // The transition response is intentionally compact.  Preserve the detail
    // already loaded (customer, source mutation, scope, history) so the open
    // modal can immediately continue to the controlled use step.
    detail.value = normalizeAdvance({
      ...selectedAdvance.value,
      ...(payload.data || {}),
      id_uang_muka: advanceId(payload.data || selectedAdvance.value),
      status: payload.data?.status || 'APPROVED'
    });
  } catch (error) {
    actionError.value = normalizeError(error, 'Approval uang muka belum dapat disimpan.');
  } finally {
    loading.approve = false;
  }
}

async function rejectSelected() {
  if (!selectedAdvance.value || !canApprove.value) return;
  loading.reject = true;
  actionError.value = '';
  try {
    const response = await rejectCustomerAdvance(advanceId(selectedAdvance.value), {
      catatan_penolakan: approvalForm.catatan.trim() || undefined
    });
    const payload = unwrapResponse(response) || {};
    feedback.value = payload.message || 'Uang Muka Customer ditolak.';
    await loadRows();
    detail.value = normalizeAdvance({
      ...selectedAdvance.value,
      ...(payload.data || {}),
      id_uang_muka: advanceId(payload.data || selectedAdvance.value),
      status: payload.data?.status || 'REJECTED'
    });
  } catch (error) {
    actionError.value = normalizeError(error, 'Penolakan uang muka belum dapat disimpan.');
  } finally {
    loading.reject = false;
  }
}

async function openUseAdvance() {
  if (!selectedAdvance.value || !canUse.value) return;
  useForm.allocations = [];
  useForm.catatan = '';
  eligibleInvoices.value = [];
  actionError.value = '';
  loading.eligible = true;
  try {
    const response = await getCustomerAdvanceEligibleInvoices(advanceId(selectedAdvance.value), { limit: 200 });
    eligibleInvoices.value = normalizeList(unwrapResponse(response))
      .map((row) => ({
        ...row,
        id_faktur: row.id_faktur || row.id,
        sisa_tagihan: Number(row.sisa_tagihan ?? row.nominal_tersedia ?? row.total_tagihan ?? 0)
      }))
      .filter((row) => row.id_faktur && row.sisa_tagihan > 0);
    applyUseFifo();
    useOpen.value = true;
  } catch (error) {
    actionError.value = normalizeError(error, 'Faktur yang dapat memakai Uang Muka belum dapat dimuat.');
  } finally {
    loading.eligible = false;
  }
}

async function submitUseAdvance() {
  if (!canSubmitUse.value) {
    actionError.value = useExceedsAdvance.value
      ? 'Total pemakaian tidak boleh melebihi sisa Uang Muka.'
      : 'Pilih minimal satu faktur dan isi nominal pemakaian yang valid.';
    return;
  }
  loading.use = true;
  actionError.value = '';
  try {
    const response = await useCustomerAdvance(advanceId(selectedAdvance.value), {
      allocations: useRows.value.map((row) => ({ id_faktur: row.id_faktur, nominal_pakai: row.nominal_pakai })),
      catatan: useForm.catatan.trim() || undefined
    });
    const payload = unwrapResponse(response) || {};
    feedback.value = payload.message || 'Pemakaian Uang Muka Customer berhasil disimpan.';
    useOpen.value = false;
    await loadRows();
    if (detailOpen.value && selectedAdvance.value) await openDetail(selectedAdvance.value);
  } catch (error) {
    actionError.value = normalizeError(error, 'Pemakaian Uang Muka Customer belum dapat disimpan.');
  } finally {
    loading.use = false;
  }
}

function openNonCashDeposit() {
  router.push({ name: 'finance-noncash-deposits' });
}

onMounted(async () => {
  await loadReferences();
  if (route.query.id_perusahaan) filters.id_perusahaan = String(route.query.id_perusahaan);
  if (route.query.id_cabang) filters.id_cabang = String(route.query.id_cabang);
  if (route.query.status) filters.status = String(route.query.status);
  await loadRows();
});
</script>

<template>
  <section class="space-y-6">
    <PageHeader
      title="Uang Muka Customer"
      description="Pantau uang muka dari kelebihan kuitansi dan mutasi bank, beserta saldo serta riwayat penggunaannya."
    >
      <div class="flex flex-wrap gap-2">
        <button class="button-secondary" :disabled="loading.list" @click="loadRows">{{ loading.list ? 'Memuat...' : 'Muat Ulang' }}</button>
        <button class="button-primary" @click="openNonCashDeposit">Buka Setoran Non Tunai</button>
      </div>
    </PageHeader>

    <section class="rounded-2xl border border-violet-200 bg-violet-50 px-5 py-4 text-sm text-violet-950 dark:border-violet-500/30 dark:bg-violet-500/10 dark:text-violet-100">
      <p class="font-semibold">Alur aman saldo lebih</p>
      <p class="mt-1">Kelebihan dana di atas sisa piutang yang dipilih sebagai Uang Muka muncul setelah kuitansi disetujui, bukan saat Draft. Selisih terhadap klaim sales saja bukan kelebihan piutang. Uang muka kuitansi otomatis tersedia di Pembayaran Tagihan untuk customer, perusahaan, dan cabang yang sama; dana yang ditahan draft lain belum dapat dipakai lagi.</p>
    </section>

    <section class="panel p-5">
      <div class="grid min-w-0 gap-4 [grid-template-columns:repeat(auto-fit,minmax(200px,1fr))]">
        <AppSearchSelect
          :model-value="filters.id_perusahaan"
          label="Perusahaan"
          placeholder="Semua perusahaan"
          :options="companyOptions"
          @update:model-value="(value) => { filters.id_perusahaan = String(value || ''); filters.id_cabang = ''; }"
        />
        <AppSearchSelect
          :model-value="filters.id_cabang"
          label="Cabang"
          placeholder="Semua cabang"
          :options="branchOptions"
          @update:model-value="(value) => { filters.id_cabang = String(value || ''); }"
        />
        <AppSearchSelect
          :model-value="filters.status"
          label="Status"
          placeholder="Semua status"
          :options="statusOptions"
          @update:model-value="(value) => { filters.status = String(value || ''); }"
        />
        <label class="block">
          <span class="field-label">Cari</span>
          <input v-model="filters.search" class="field-control" placeholder="Kode UM, customer, kuitansi, atau mutasi" @keyup.enter="loadRows" />
        </label>
        <div class="flex items-end gap-2">
          <button class="button-primary w-full" :disabled="loading.list" @click="loadRows">Terapkan</button>
          <button class="button-secondary shrink-0" @click="resetFilters">Reset</button>
        </div>
      </div>
    </section>

    <section class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <article class="panel p-5"><p class="section-eyebrow">Total dibuat</p><p class="mt-2 text-xl font-bold text-violet-600">{{ formatCurrency(summary.total) }}</p></article>
      <article class="panel p-5"><p class="section-eyebrow">Menunggu approval</p><p class="mt-2 text-xl font-bold text-amber-600">{{ formatCurrency(summary.pending) }}</p></article>
      <article class="panel p-5"><p class="section-eyebrow">Saldo aktif</p><p class="mt-2 text-xl font-bold text-emerald-600">{{ formatCurrency(summary.active) }}</p></article>
      <article class="panel p-5"><p class="section-eyebrow">Sudah dipakai</p><p class="mt-2 text-xl font-bold text-sky-600">{{ formatCurrency(summary.used) }}</p></article>
    </section>

    <p v-if="pageError" class="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">{{ pageError }}</p>
    <p v-if="feedback" class="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200">{{ feedback }}</p>

    <AppTable
      :rows="rows"
      :columns="columns"
      :loading="loading.list"
      row-key="id_uang_muka"
      :selected-key="selectedRow?.id_uang_muka"
      clickable-rows
      empty-message="Belum ada Uang Muka Customer pada filter ini."
      @row-click="openDetail"
    />

    <AppModal :open="detailOpen" title="Detail Uang Muka Customer" description="Dokumen sumber, status, dan riwayat penggunaan tersimpan sebagai jejak audit." size="4xl" @close="detailOpen = false">
      <div v-if="selectedAdvance" class="space-y-5">
        <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div class="rounded-xl border border-slate-200 p-3 dark:border-slate-700"><p class="section-eyebrow">Kode</p><p class="mt-1 font-bold text-slate-950 dark:text-white">{{ selectedAdvance.kode_uang_muka }}</p></div>
          <div class="rounded-xl border border-slate-200 p-3 dark:border-slate-700"><p class="section-eyebrow">Customer</p><p class="mt-1 font-bold text-slate-950 dark:text-white">{{ selectedAdvance.nama_customer || '-' }}</p></div>
          <div class="rounded-xl border border-slate-200 p-3 dark:border-slate-700"><p class="section-eyebrow">{{ fromReceipt(selectedAdvance) ? 'Kuitansi sumber' : 'Mutasi' }}</p><p class="mt-1 font-bold text-slate-950 dark:text-white">{{ selectedAdvance.source_reference || selectedAdvance.kode_mutasi || '-' }}</p></div>
          <div class="rounded-xl border border-slate-200 p-3 dark:border-slate-700"><p class="section-eyebrow">Status</p><div class="mt-1"><span :class="statusBadge(selectedAdvance).className">{{ statusBadge(selectedAdvance).text }}</span></div></div>
        </div>

        <div class="grid gap-3 sm:grid-cols-3">
          <div class="rounded-xl bg-slate-50 p-4 dark:bg-slate-900"><p class="section-eyebrow">Nilai awal</p><p class="mt-1 text-lg font-bold text-slate-950 dark:text-white">{{ formatCurrency(advanceAmount(selectedAdvance)) }}</p></div>
          <div class="rounded-xl bg-sky-50 p-4 dark:bg-sky-500/10"><p class="section-eyebrow">Terpakai</p><p class="mt-1 text-lg font-bold text-sky-700 dark:text-sky-200">{{ formatCurrency(advanceUsed(selectedAdvance)) }}</p></div>
          <div class="rounded-xl bg-emerald-50 p-4 dark:bg-emerald-500/10"><p class="section-eyebrow">Saldo tersisa</p><p class="mt-1 text-lg font-bold text-emerald-700 dark:text-emerald-200">{{ formatCurrency(advanceRemaining(selectedAdvance)) }}</p></div>
        </div>

        <div v-if="fromReceipt(selectedAdvance)" class="space-y-3 rounded-xl border border-sky-200 bg-sky-50 p-4 text-sky-950 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-100">
          <p>Ditahan draft: <b>{{ formatCurrency(selectedAdvance.nominal_ditahan) }}</b>. Sisa tersedia sudah dikurangi pemakaian final dan dana yang ditahan draft.</p>
          <p v-if="advanceStatus(selectedAdvance)==='CANCELLED'">Kuitansi sumber dibatalkan. Uang muka ini tidak dapat dipakai; riwayat tetap disimpan.</p>
          <template v-else><p>Uang muka ini telah disahkan bersama approval kuitansi. Gunakan melalui sumber dana pada Pembayaran Tagihan; tidak perlu approval atau pendaftaran ulang.</p><button v-if="canUseReceipt && advanceRemaining(selectedAdvance)>0" class="button-primary" @click="openReceiptPayment">Buka Pembayaran Tagihan</button></template>
        </div>
        <div v-else-if="advanceStatus(selectedAdvance) === 'PENDING_APPROVAL'" class="rounded-xl border border-amber-200 bg-amber-50 p-4 dark:border-amber-500/30 dark:bg-amber-500/10">
          <p class="font-semibold text-amber-950 dark:text-amber-100">Menunggu keputusan Finance</p>
          <textarea v-model="approvalForm.catatan" class="field-control mt-3 min-h-20" placeholder="Catatan approval/penolakan (opsional)" />
          <div class="mt-3 flex flex-wrap gap-2">
            <button v-if="canApprove" class="button-primary" :disabled="loading.approve" @click="approveSelected">{{ loading.approve ? 'Menyetujui...' : 'Setujui Uang Muka' }}</button>
            <button v-if="canApprove" class="button-danger" :disabled="loading.reject" @click="rejectSelected">{{ loading.reject ? 'Memproses...' : 'Tolak' }}</button>
            <p v-else class="text-sm text-amber-800 dark:text-amber-200">Anda dapat melihat data ini, tetapi approval membutuhkan hak akses Finance.</p>
          </div>
        </div>

        <div v-else-if="['APPROVED', 'PARTIAL'].includes(advanceStatus(selectedAdvance)) && advanceRemaining(selectedAdvance) > 0.5" class="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-500/30 dark:bg-emerald-500/10">
          <div><p class="font-semibold text-emerald-950 dark:text-emerald-100">Uang Muka siap digunakan</p><p class="mt-1 text-sm text-emerald-800 dark:text-emerald-200">Pemakaian hanya dapat dialokasikan ke faktur terbuka customer, cabang, dan sales yang sama.</p></div>
          <button v-if="canUse" class="button-primary" :disabled="loading.eligible" @click="openUseAdvance">{{ loading.eligible ? 'Memuat faktur...' : 'Gunakan Uang Muka' }}</button>
        </div>

        <section>
          <p class="section-eyebrow">Riwayat penggunaan</p>
          <div class="mt-2 overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-700">
            <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
              <thead class="bg-slate-50 dark:bg-slate-900"><tr><th class="px-3 py-2 text-left">Tanggal</th><th class="px-3 py-2 text-left">Faktur</th><th class="px-3 py-2 text-right">Nominal</th><th class="px-3 py-2 text-left">Petugas / Catatan</th></tr></thead>
              <tbody class="divide-y divide-slate-100 dark:divide-slate-800">
                <tr v-if="loading.detail"><td colspan="4" class="px-3 py-6 text-center text-slate-500">Memuat riwayat...</td></tr>
                <tr v-else-if="!(detail?.history || detail?.usage_history || detail?.uses || []).length"><td colspan="4" class="px-3 py-6 text-center text-slate-500">Belum ada pemakaian uang muka.</td></tr>
                <tr v-for="(item, index) in (detail?.history || detail?.usage_history || detail?.uses || [])" v-else :key="item.id || index"><td class="px-3 py-2">{{ formatDate(item.tanggal || item.created_at || item.tanggal_pakai) }}</td><td class="px-3 py-2">{{ item.no_faktur || item.kode_faktur || '-' }}</td><td class="px-3 py-2 text-right font-semibold">{{ formatCurrency(item.nominal_pakai || item.nominal || item.jumlah) }}</td><td class="px-3 py-2">{{ item.nama_user || item.created_by_name || item.dibuat_oleh_nama || '-' }}<span v-if="item.catatan"> · {{ item.catatan }}</span></td></tr>
              </tbody>
            </table>
          </div>
        </section>
        <p v-if="actionError" class="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">{{ actionError }}</p>
      </div>
      <template #footer><button class="button-secondary" @click="detailOpen = false">Tutup</button></template>
    </AppModal>

    <AppModal :open="useOpen" title="Gunakan Uang Muka Customer" description="Alokasikan saldo uang muka yang telah disetujui ke satu atau beberapa faktur terbuka customer, cabang, dan sales yang sama." size="4xl" @close="useOpen = false">
      <div class="space-y-4">
        <div class="grid gap-3 sm:grid-cols-3">
          <div class="rounded-xl bg-emerald-50 p-3 dark:bg-emerald-500/10"><p class="section-eyebrow">Saldo uang muka</p><p class="mt-1 text-lg font-bold text-emerald-700 dark:text-emerald-200">{{ formatCurrency(advanceRemaining(selectedAdvance || {})) }}</p></div>
          <div class="rounded-xl bg-sky-50 p-3 dark:bg-sky-500/10"><p class="section-eyebrow">Akan dipakai</p><p class="mt-1 text-lg font-bold text-sky-700 dark:text-sky-200">{{ formatCurrency(totalUseAmount) }}</p></div>
          <div class="rounded-xl bg-amber-50 p-3 dark:bg-amber-500/10"><p class="section-eyebrow">Sisa sesudah pakai</p><p class="mt-1 text-lg font-bold text-amber-700 dark:text-amber-200">{{ formatCurrency(Math.max(0, advanceRemaining(selectedAdvance || {}) - totalUseAmount)) }}</p></div>
        </div>
        <div class="flex justify-end"><button class="button-secondary" @click="applyUseFifo">Isi FIFO</button></div>
        <div class="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-700">
          <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
            <thead class="bg-slate-50 dark:bg-slate-900"><tr><th class="w-12 px-3 py-2">Pilih</th><th class="px-3 py-2 text-left">Faktur / SO</th><th class="px-3 py-2 text-left">Jatuh tempo</th><th class="px-3 py-2 text-right">Sisa tagihan</th><th class="min-w-[180px] px-3 py-2 text-right">Pakai uang muka</th></tr></thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-800">
              <tr v-if="!eligibleInvoices.length"><td colspan="5" class="px-3 py-8 text-center text-slate-500">Tidak ada faktur terbuka yang dapat memakai uang muka ini.</td></tr>
              <tr v-for="invoice in eligibleInvoices" v-else :key="invoice.id_faktur"><td class="px-3 py-2 text-center"><input type="checkbox" :checked="isInvoiceSelected(invoice)" @change="toggleInvoice(invoice, $event.target.checked)" /></td><td class="px-3 py-2"><p class="font-semibold">{{ invoice.no_faktur || '-' }}</p><p class="text-xs text-slate-500">SO: {{ invoice.id_sales_order || '-' }}</p></td><td class="px-3 py-2">{{ formatDate(invoice.tanggal_jatuh_tempo) }}</td><td class="px-3 py-2 text-right font-semibold">{{ formatCurrency(invoice.sisa_tagihan) }}</td><td class="px-3 py-2"><input :value="isInvoiceSelected(invoice) ? useEntryFor(invoice)?.nominal_pakai : ''" type="number" min="0" :max="invoice.sisa_tagihan" step="0.01" class="field-control text-right" :disabled="!isInvoiceSelected(invoice)" placeholder="0" @input="setUseAmount(invoice, $event.target.value)" /></td></tr>
            </tbody>
          </table>
        </div>
        <p v-if="useExceedsAdvance || useHasInvalidAmount" class="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">{{ useExceedsAdvance ? 'Total pemakaian melebihi saldo uang muka.' : 'Nominal pemakaian harus lebih dari nol dan tidak melebihi sisa tagihan.' }}</p>
        <label class="block"><span class="field-label">Catatan pemakaian <span class="font-normal text-slate-400">(opsional)</span></span><textarea v-model="useForm.catatan" class="field-control min-h-20" placeholder="Catatan audit pemakaian uang muka." /></label>
      </div>
      <template #footer><div class="flex flex-wrap justify-end gap-2"><button class="button-secondary" @click="useOpen = false">Batal</button><button class="button-primary" :disabled="loading.use || !canSubmitUse" @click="submitUseAdvance">{{ loading.use ? 'Menyimpan...' : 'Simpan Pemakaian' }}</button></div></template>
    </AppModal>
  </section>
</template>

<style scoped>
.button-primary,
.button-secondary,
.button-danger {
  border-radius: 0.75rem;
  padding: 0.7rem 1rem;
  font-size: 0.875rem;
  font-weight: 700;
}
.button-primary { background: rgb(37 99 235); color: white; }
.button-primary:hover:not(:disabled) { background: rgb(29 78 216); }
.button-secondary { border: 1px solid rgb(203 213 225); color: rgb(51 65 85); }
.dark .button-secondary { border-color: rgb(51 65 85); color: rgb(226 232 240); }
.button-danger { background: rgb(225 29 72); color: white; }
.button-danger:hover:not(:disabled) { background: rgb(190 24 93); }
.button-primary:disabled, .button-secondary:disabled, .button-danger:disabled { cursor: not-allowed; opacity: .55; }
.field-label, .section-eyebrow { display: block; font-size: .72rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: rgb(100 116 139); }
.field-control { width: 100%; margin-top: .35rem; border: 1px solid rgb(203 213 225); border-radius: .75rem; background: white; padding: .7rem .8rem; color: rgb(15 23 42); }
.dark .field-control { border-color: rgb(51 65 85); background: rgb(2 6 23); color: rgb(226 232 240); }
</style>
