<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { getBranches, getCompanies, getSales } from '@/api/master';
import { approveReturBySpv, cancelReturBySpv, getReturDetail, getSalesReturList, submitReturStock } from '@/api/salesOrder';
import { useAuthStore } from '@/app/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import {
  getRowBranchIds,
  getRowCompanyId,
  scopeSalesRowsByLogin
} from '@/utils/accessScope';
import AppEmptyState from '@/shared/components/AppEmptyState.vue';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import {
  getSupervisorBranchOptions,
  getSupervisorCompanyOptions,
  resetSupervisorBranchWhenCompanyChanges,
  syncSupervisorCompanyFromBranch
} from '@/modules/supervisor-sales/utils/supervisorScope';

const router = useRouter();
const auth = useAuthStore();

const filters = reactive({
  salesUserId: '',
  branchId: '',
  companyId: '',
  status: '',
  search: ''
});

const items = ref([]);
const summary = ref({
  total_requests: 0,
  pending_requests: 0,
  kpr_requests: 0,
  processed_requests: 0,
  total_amount: 0
});
const companyRows = ref([]);
const branchRows = ref([]);
const salesRows = ref([]);
const loading = ref(false);
const loadError = ref('');
const feedback = ref('');
const selectedRow = ref(null);

const detailOpen = ref(false);
const detailLoading = ref(false);
const detailHeader = ref({});
const detailRows = ref([]);
const detailError = ref('');
const detailFeedback = ref('');
const actionLoading = ref(false);

const fallbackBranchId = computed(() => auth.user?.id_cabang || auth.user?.cabang_id || auth.user?.cabang?.id || '');

function branchMatchesCompany(branch, companyId = filters.companyId) {
  if (!companyId) return true;
  if (String(getRowCompanyId(branch) || '') === String(companyId)) return true;

  const company = companyRows.value.find((item) => String(item.id) === String(companyId));
  return getRowBranchIds(company).includes(String(branch?.id || ''));
}

function resolveSalesBranchId(sales) {
  return String(sales?.id_cabang || sales?.cabang_id || sales?.branch_id || '');
}

const companyOptions = computed(() =>
  getSupervisorCompanyOptions(companyRows.value, branchRows.value, '', auth)
);

const branchOptions = computed(() =>
  getSupervisorBranchOptions(branchRows.value, auth, false, filters.companyId, companyRows.value)
);

const salesOptions = computed(() =>
  scopeSalesRowsByLogin(salesRows.value, auth)
    .filter((item) => {
      const salesBranchId = resolveSalesBranchId(item);
      if (filters.branchId && salesBranchId !== String(filters.branchId)) return false;
      if (filters.companyId) {
        const branch = branchRows.value.find((row) => String(row.id) === salesBranchId);
        if (branch && !branchMatchesCompany(branch, filters.companyId)) return false;
      }
      return true;
    })
    .map((item) => ({
      value: String(item.id_user || item.id),
      label: `${item.kode_sales || '-'} - ${item.nama || 'Sales'}`
    }))
);

const statusOptions = [
  { value: 'pending', label: 'Pending' },
  { value: 'on_process', label: 'On Proses' },
  { value: 'canceled', label: 'Batal' }
];

const filterFields = computed(() => [
  { key: 'companyId', label: 'Perusahaan', type: 'search-select', options: companyOptions.value, placeholder: 'Semua perusahaan' },
  { key: 'branchId', label: 'Cabang', type: 'search-select', options: branchOptions.value, placeholder: 'Semua cabang', emptyText: 'Cabang belum tersedia untuk hak akses ini.' },
  { key: 'salesUserId', label: 'Sales', type: 'search-select', options: salesOptions.value, placeholder: 'Semua sales', emptyText: 'Sales belum tersedia untuk hak akses ini.' },
  { key: 'status', label: 'Status Approval', type: 'search-select', options: statusOptions, placeholder: 'Semua status' },
  { key: 'search', label: 'Cari', placeholder: 'Kode request, KPR, CN, customer, faktur' }
]);

const selectedKey = computed(() => selectedRow.value?.id_request || '');
const selectedStatus = computed(() => String(selectedRow.value?.status_request ?? ''));
const canPrintKpr = computed(() => detailOpen.value && selectedStatus.value === '0' && detailHeader.value?.kode_kpr && !actionLoading.value);
const canProcessReturStock = computed(() => detailOpen.value && selectedStatus.value === '1' && detailRows.value.length > 0 && !actionLoading.value);
const canCancelSpv = computed(() => detailOpen.value && selectedStatus.value === '0' && !actionLoading.value);

const statusSummary = computed(() => ({
  total: items.value.length,
  pending: items.value.filter((item) => String(item.status_request ?? '') === '0').length,
  onProcess: items.value.filter((item) => ['1', '2', '3'].includes(String(item.status_request ?? ''))).length,
  canceled: items.value.filter((item) => String(item.status_request ?? '') === '9').length
}));

const normalizedRows = computed(() =>
  items.value.map((item) => ({
    ...item,
    row_key: String(item.id_request),
    amount_label: `Rp ${Number(item.total_retur || 0).toLocaleString('id-ID')}`,
    qty_label: item.qty_retur_label || formatQtyLabel(item.total_pieces_retur, item.total_box_retur, item.total_karton_retur),
    status_request_label: resolveReturBusinessStatus(item.status_request),
    next_step_label: resolveNextStep(item)
  }))
);

const detailTableRows = computed(() =>
  detailRows.value.map((item, index) => ({
    ...item,
    row_key: String(item.id_produk || item.id_request_detail || index),
    qty_request_bad_label: formatQtyLabel(item.pieces_diajukan, item.box_diajukan, item.karton_diajukan),
    qty_request_good_label: formatQtyLabel(item.pieces_good_diajukan, item.box_good_diajukan, item.karton_good_diajukan),
    qty_total_label: formatQtyLabel(item.pieces_retur, item.box_retur, item.karton_retur)
  }))
);

const tableColumns = [
  { key: 'kode_request', label: 'Kode Request' },
  { key: 'tanggal_request', label: 'Tanggal' },
  { key: 'nama_customer', label: 'Customer' },
  { key: 'nama_principal', label: 'Principal' },
  { key: 'no_faktur', label: 'No Faktur' },
  { key: 'qty_label', label: 'Qty Retur' },
  { key: 'amount_label', label: 'Nilai Retur' },
  { key: 'status_request_label', label: 'Status' },
  { key: 'next_step_label', label: 'Langkah Supervisor' }
];

function formatQtyLabel(pieces, box, karton) {
  return `${Number(pieces || 0).toLocaleString('id-ID')} pcs | ${Number(box || 0).toLocaleString('id-ID')} box | ${Number(karton || 0).toLocaleString('id-ID')} karton`;
}

function resolveReturBusinessStatus(statusRequest) {
  const status = String(statusRequest ?? '');
  if (status === '0') return 'Pending';
  if (['1', '2', '3'].includes(status)) return 'On Proses';
  if (status === '9') return 'Batal';
  return '-';
}

function resolveNextStep(item) {
  const status = String(item.status_request ?? '');
  if (status === '0') return 'Cetak KPR';
  if (status === '1') return 'Proses retur stock';
  if (status === '2') return 'Tunggu credit note';
  if (status === '3') return 'Proses credit note';
  if (status === '9') return 'Batal';
  return '-';
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
  row[field] = Math.max(0, Number(value || 0));
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

function resetDetailState() {
  detailHeader.value = {};
  detailRows.value = [];
  detailError.value = '';
  detailFeedback.value = '';
}

async function loadReferenceData() {
  const [companiesResponse, branchesResponse, salesResponse] = await Promise.all([getCompanies(), getBranches(), getSales()]);
  companyRows.value = normalizeList(unwrapResponse(companiesResponse));
  branchRows.value = normalizeList(unwrapResponse(branchesResponse));
  salesRows.value = normalizeList(unwrapResponse(salesResponse));
  syncSupervisorCompanyFromBranch(filters, 'branchId', 'companyId', branchRows.value, companyRows.value);
}

async function loadReturRows(preserveRequestId = null) {
  loading.value = true;
  loadError.value = '';
  feedback.value = '';
  const targetId = preserveRequestId || selectedRow.value?.id_request || null;

  try {
    const response = await getSalesReturList({
      id_cabang: filters.branchId || undefined,
      id_perusahaan: filters.companyId || undefined,
      user_id: filters.salesUserId || undefined,
      status_group: filters.status || undefined,
      search: filters.search || undefined
    });

    const payload = unwrapResponse(response) || {};
    items.value = normalizeList(payload);
    summary.value = {
      total_requests: Number(payload?.summary?.total_requests || items.value.length || 0),
      pending_requests: Number(payload?.summary?.pending_requests || 0),
      kpr_requests: Number(payload?.summary?.kpr_requests || 0),
      processed_requests: Number(payload?.summary?.processed_requests || 0),
      total_amount: Number(payload?.summary?.total_amount || 0)
    };
    selectedRow.value = targetId ? items.value.find((item) => String(item.id_request) === String(targetId)) || null : null;
    feedback.value = `Supervisor memuat ${items.value.length} retur untuk antrian approval saat ini.`;
  } catch (error) {
    loadError.value = normalizeError(error, 'Data approval retur belum bisa dimuat.');
    items.value = [];
    selectedRow.value = null;
    summary.value = {
      total_requests: 0,
      pending_requests: 0,
      kpr_requests: 0,
      processed_requests: 0,
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
  if (!row?.id_request) return;

  selectedRow.value = row;
  detailOpen.value = true;
  resetDetailState();
  await loadReturDetail(row.id_request);
}

async function handleApproveSpv() {
  if (!selectedRow.value?.id_request || !detailHeader.value?.kode_kpr) return;

  actionLoading.value = true;
  detailError.value = '';
  detailFeedback.value = '';

  try {
    await approveReturBySpv(selectedRow.value.id_request, {
      kode_kpr: detailHeader.value.kode_kpr
    });
    detailFeedback.value = 'Retur berhasil diapprove SPV. KPR dicetak dan retur sekarang berpindah ke antrian retur stock.';
    await loadReturRows(selectedRow.value.id_request);
    await loadReturDetail(selectedRow.value.id_request);
  } catch (error) {
    detailError.value = normalizeError(error, 'Retur belum berhasil diapprove SPV.');
  } finally {
    actionLoading.value = false;
  }
}

async function handleProcessReturStock() {
  if (!selectedRow.value?.id_request) return;

  actionLoading.value = true;
  detailError.value = '';
  detailFeedback.value = '';

  try {
    await submitReturStock(selectedRow.value.id_request, buildReturStockPayload());
    detailFeedback.value = 'Retur stock berhasil diproses dan siap diteruskan ke proses credit note.';
    await loadReturRows(selectedRow.value.id_request);
    await loadReturDetail(selectedRow.value.id_request);
  } catch (error) {
    detailError.value = normalizeError(error, 'Retur stock belum berhasil diproses.');
  } finally {
    actionLoading.value = false;
  }
}

async function handleCancelSpv() {
  if (!selectedRow.value?.id_request) return;

  const reason = window.prompt('Alasan batal oleh SPV?', 'Tidak disetujui SPV');
  if (reason === null) return;

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

function resetFilters() {
  filters.salesUserId = '';
  filters.branchId = fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  filters.companyId = '';
  syncSupervisorCompanyFromBranch(filters, 'branchId', 'companyId', branchRows.value, companyRows.value);
  filters.status = '';
  filters.search = '';
  loadReturRows();
}

onMounted(async () => {
  filters.branchId = fallbackBranchId.value ? String(fallbackBranchId.value) : '';

  try {
    await loadReferenceData();
  } catch (error) {
    loadError.value = normalizeError(error, 'Referensi sales dan cabang belum bisa dimuat.');
  }

  await loadReturRows();
});

watch(
  () => filters.companyId,
  (value) => {
    if (!value) {
      filters.branchId = '';
      filters.salesUserId = '';
      return;
    }

    if (resetSupervisorBranchWhenCompanyChanges(filters, 'companyId', 'branchId', branchRows.value, auth, companyRows.value)) {
      filters.salesUserId = '';
    }

    if (filters.salesUserId && !salesOptions.value.some((item) => item.value === String(filters.salesUserId))) {
      filters.salesUserId = '';
    }
  }
);

watch(
  () => filters.branchId,
  (value) => {
    if (
      filters.salesUserId &&
      !salesOptions.value.some((item) => item.value === String(filters.salesUserId))
    ) {
      filters.salesUserId = '';
    }
  }
);
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Approve Retur"
      description="Supervisor memantau antrian retur, membuka detail permintaan, lalu menjalankan approval operasional seperti cetak KPR dan proses retur stock."
    >
      <div class="flex flex-wrap gap-2">
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="resetFilters">
          Reset Filter
        </button>
        <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700" @click="loadReturRows">
          Refresh Data
        </button>
      </div>
    </PageHeader>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Total Retur</p>
        <p class="mt-3 text-2xl font-semibold text-slate-900">{{ statusSummary.total.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Pending</p>
        <p class="mt-3 text-2xl font-semibold text-amber-600">{{ statusSummary.pending.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">On Proses</p>
        <p class="mt-3 text-2xl font-semibold text-brand-700">{{ statusSummary.onProcess.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Batal</p>
        <p class="mt-3 text-2xl font-semibold text-rose-600">{{ statusSummary.canceled.toLocaleString('id-ID') }}</p>
      </article>
    </section>

    <AppFilterBar v-model="filters" :fields="filterFields" @submit="loadReturRows" @reset="resetFilters" />

    <section v-if="feedback" class="rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-700">
      {{ feedback }}
    </section>

    <section v-if="loadError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ loadError }}
    </section>

    <div class="grid gap-6 xl:grid-cols-[minmax(0,1.2fr)_minmax(340px,0.8fr)]">
      <section class="panel p-5">
        <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 class="text-lg font-semibold text-slate-900">Antrian Approval Retur</h3>
            <p class="mt-1 text-sm text-slate-500">Klik salah satu retur untuk membuka detail dan tindak lanjut supervisor.</p>
          </div>
          <div class="text-sm text-slate-500">
            Nilai: <span class="font-semibold text-slate-900">Rp {{ Number(summary.total_amount || 0).toLocaleString('id-ID') }}</span>
          </div>
        </div>

        <AppTable
          :columns="tableColumns"
          :rows="normalizedRows"
          :loading="loading"
          row-key="row_key"
          :selected-key="selectedKey"
          :clickable-rows="true"
          empty-message="Belum ada retur yang masuk ke antrian approval supervisor."
          @row-click="selectedRow = $event"
        />
      </section>

      <section class="panel p-5">
        <div v-if="selectedRow" class="space-y-4">
          <div>
            <h3 class="text-lg font-semibold text-slate-900">Ringkasan Retur Terpilih</h3>
            <p class="mt-1 text-sm text-slate-500">Status dan aksi cepat supervisor untuk retur yang sedang dipilih.</p>
          </div>

          <div class="grid gap-3 md:grid-cols-2">
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-wide text-slate-400">Customer</p>
              <p class="mt-2 font-semibold text-slate-900">{{ selectedRow.nama_customer || '-' }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-wide text-slate-400">Principal</p>
              <p class="mt-2 font-semibold text-slate-900">{{ selectedRow.nama_principal || '-' }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-wide text-slate-400">Status</p>
              <p class="mt-2 font-semibold text-slate-900">{{ selectedRow.status_request_label || '-' }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-wide text-slate-400">No Faktur</p>
              <p class="mt-2 font-semibold text-slate-900">{{ selectedRow.no_faktur || '-' }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-wide text-slate-400">Kode KPR</p>
              <p class="mt-2 font-semibold text-slate-900">{{ selectedRow.kode_kpr || '-' }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-wide text-slate-400">No CN</p>
              <p class="mt-2 font-semibold text-slate-900">{{ selectedRow.no_cn || '-' }}</p>
            </article>
          </div>

          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
            {{ resolveNextStep(selectedRow) }}
          </div>

          <div class="flex flex-wrap gap-2">
            <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700" @click="openDetailModal(selectedRow)">
              Buka Detail Approval
            </button>
            <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="router.push({ name: 'sales-order-retur-list', query: { sales_user_id: selectedRow.id_sales || filters.salesUserId || '' } })">
              Buka Tracking Sales
            </button>
          </div>
        </div>

        <div v-else class="py-8">
          <AppEmptyState
            title="Belum ada retur terpilih"
            description="Pilih salah satu baris retur di tabel kiri agar supervisor bisa melihat detail dan melanjutkan approval."
          />
        </div>
      </section>
    </div>

    <AppModal
      :open="detailOpen"
      title="Detail Approval Retur"
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
            <p class="mt-2 font-semibold text-slate-900">{{ selectedRow?.status_request_label || '-' }}</p>
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
          <p v-if="selectedStatus === '0'">Supervisor dapat mencetak KPR untuk meneruskan retur ke tahap penerimaan barang.</p>
          <p v-else-if="selectedStatus === '1'">Supervisor memeriksa kuantitas retur stock dan mengonfirmasi barang good/bad sebelum sinkron ke credit note.</p>
          <p v-else>Retur ini sudah melewati tahap approval utama dan tinggal menjadi referensi finance.</p>
        </div>

        <div class="overflow-x-auto rounded-2xl border border-slate-200">
          <table class="min-w-full divide-y divide-slate-200 text-sm">
            <thead class="bg-slate-50 text-left text-xs uppercase tracking-[0.2em] text-slate-500">
              <tr>
                <th class="px-4 py-3">Produk</th>
                <th class="px-4 py-3">Pengajuan Bad</th>
                <th class="px-4 py-3">Pengajuan Good</th>
                <th class="px-4 py-3">Total Retur</th>
                <th class="px-4 py-3">Penerimaan Bad</th>
                <th class="px-4 py-3">Penerimaan Good</th>
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
                    <input :value="row.accepted_bad_pieces" type="number" min="0" :disabled="selectedStatus !== '1'" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-slate-900 outline-none focus:border-brand-400 disabled:bg-slate-100 disabled:text-slate-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:disabled:bg-slate-800 dark:disabled:text-slate-400" @input="updateAcceptedField(row, 'accepted_bad_pieces', $event.target.value)">
                    <input :value="row.accepted_bad_box" type="number" min="0" :disabled="selectedStatus !== '1'" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-slate-900 outline-none focus:border-brand-400 disabled:bg-slate-100 disabled:text-slate-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:disabled:bg-slate-800 dark:disabled:text-slate-400" @input="updateAcceptedField(row, 'accepted_bad_box', $event.target.value)">
                    <input :value="row.accepted_bad_karton" type="number" min="0" :disabled="selectedStatus !== '1'" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-slate-900 outline-none focus:border-brand-400 disabled:bg-slate-100 disabled:text-slate-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:disabled:bg-slate-800 dark:disabled:text-slate-400" @input="updateAcceptedField(row, 'accepted_bad_karton', $event.target.value)">
                  </div>
                </td>
                <td class="px-4 py-3 align-top">
                  <div class="grid gap-2 md:grid-cols-3">
                    <input :value="row.accepted_good_pieces" type="number" min="0" :disabled="selectedStatus !== '1'" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-slate-900 outline-none focus:border-brand-400 disabled:bg-slate-100 disabled:text-slate-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:disabled:bg-slate-800 dark:disabled:text-slate-400" @input="updateAcceptedField(row, 'accepted_good_pieces', $event.target.value)">
                    <input :value="row.accepted_good_box" type="number" min="0" :disabled="selectedStatus !== '1'" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-slate-900 outline-none focus:border-brand-400 disabled:bg-slate-100 disabled:text-slate-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:disabled:bg-slate-800 dark:disabled:text-slate-400" @input="updateAcceptedField(row, 'accepted_good_box', $event.target.value)">
                    <input :value="row.accepted_good_karton" type="number" min="0" :disabled="selectedStatus !== '1'" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-slate-900 outline-none focus:border-brand-400 disabled:bg-slate-100 disabled:text-slate-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:disabled:bg-slate-800 dark:disabled:text-slate-400" @input="updateAcceptedField(row, 'accepted_good_karton', $event.target.value)">
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
          <button v-if="selectedStatus === '0'" class="rounded-xl border border-rose-200 px-4 py-2 text-sm font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-60 dark:border-rose-900/60 dark:text-rose-300 dark:hover:bg-rose-950/30" :disabled="!canCancelSpv" @click="handleCancelSpv">
            {{ actionLoading ? 'Memproses...' : 'Batal SPV' }}
          </button>
          <button v-if="selectedStatus === '0'" class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60" :disabled="!canPrintKpr" @click="handleApproveSpv">
            {{ actionLoading ? 'Memproses...' : 'Approve SPV & Cetak KPR' }}
          </button>
          <button v-if="selectedStatus === '1'" class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60" :disabled="!canProcessReturStock" @click="handleProcessReturStock">
            {{ actionLoading ? 'Memproses...' : 'Proses Retur Stock' }}
          </button>
        </div>
      </div>
    </AppModal>
  </div>
</template>
