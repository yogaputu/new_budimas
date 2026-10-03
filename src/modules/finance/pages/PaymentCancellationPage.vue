<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { getBranches, getCompanies, getSales } from '@/api/master';
import {
  cancelPreFinalPayment,
  getPreFinalPaymentCancellationCandidates
} from '@/api/finance';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import {
  branchMatchesCompany,
  getLoginBranchId,
  getLoginCompanyId,
  isSuperUser,
  scopeSalesRowsByLogin
} from '@/utils/accessScope';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const auth = useAuthStore();
const numberFormatter = new Intl.NumberFormat('id-ID', { maximumFractionDigits: 2 });

const filters = reactive({
  id_perusahaan: '',
  id_cabang: '',
  id_sales: '',
  status_setoran: '',
  search: ''
});
const cancellationForm = reactive({ reason: '' });
const rows = ref([]);
const companyRows = ref([]);
const branchRows = ref([]);
const salesRows = ref([]);
const selectedRow = ref(null);
const detailOpen = ref(false);
const pageError = ref('');
const actionError = ref('');
const feedback = ref('');
const loading = reactive({ refs: false, list: false, cancel: false });

const fallbackCompanyId = computed(() => getLoginCompanyId(auth.user));
const fallbackBranchId = computed(() => getLoginBranchId(auth.user));
const canCancel = computed(() => (
  isSuperUser(auth)
  || auth.hasPermission('finance.payment-cancellation.cancel')
  || auth.hasPermission('finance.recap.update')
  || auth.hasPermission('finance.payments.update')
));
const canSubmitCancellation = computed(() => Boolean(
  selectedRow.value
  && selectedRow.value.can_cancel
  && canCancel.value
  && cancellationForm.reason.trim().length >= 5
));

const companyOptions = computed(() => [
  { value: '', label: 'Semua perusahaan' },
  ...companyRows.value
    .map((row) => ({
      value: String(row.id || row.id_perusahaan || ''),
      label: `${row.kode || row.kode_perusahaan || ''}${row.kode || row.kode_perusahaan ? ' - ' : ''}${row.nama || row.nama_perusahaan || 'Perusahaan'}`
    }))
    .filter((row) => row.value)
]);

const branchOptions = computed(() => [
  { value: '', label: 'Semua cabang' },
  ...branchRows.value
    .filter((row) => !filters.id_perusahaan || branchMatchesCompany(row, filters.id_perusahaan))
    .map((row) => {
      const id = row.id_cabang ?? row.branch_id ?? row.id;
      const code = row.kode_cabang ?? row.kode ?? '';
      const name = row.nama_cabang ?? row.nama ?? `Cabang ${id}`;
      return { value: String(id || ''), label: `${code ? `${code} - ` : ''}${name}` };
    })
    .filter((row) => row.value)
]);

function salesId(row = {}) {
  return row.id_sales ?? row.sales_id ?? row.id ?? '';
}

function salesBranchId(row = {}) {
  return row.id_cabang ?? row.cabang_id ?? row.branch_id ?? row.id_cabang_sales ?? '';
}

function salesCompanyId(row = {}) {
  return row.id_perusahaan ?? row.perusahaan_id ?? row.company_id ?? row.id_company ?? '';
}

const salesOptions = computed(() => [
  { value: '', label: 'Semua sales' },
  ...scopeSalesRowsByLogin(salesRows.value, auth)
    .filter((row) => !filters.id_cabang || !salesBranchId(row) || String(salesBranchId(row)) === String(filters.id_cabang))
    .filter((row) => !filters.id_perusahaan || !salesCompanyId(row) || String(salesCompanyId(row)) === String(filters.id_perusahaan))
    .map((row) => {
      const id = salesId(row);
      const code = row.kode_sales ?? row.kode ?? '';
      const name = row.nama_sales ?? row.nama ?? row.name ?? `Sales ${id}`;
      return { value: String(id || ''), label: `${code ? `${code} - ` : ''}${name}` };
    })
    .filter((row) => row.value)
]);

const statusOptions = [
  { value: '', label: 'Semua tahap pra-final' },
  { value: '1', label: 'Rekap / menunggu pencatatan' },
  { value: '2', label: 'Tercatat / siap cocokkan' }
];

function formatCurrency(value) {
  return `Rp ${numberFormatter.format(Number(value || 0))}`;
}

function formatDate(value) {
  if (!value) return '-';
  const literal = String(value).match(/\d{4}-\d{2}-\d{2}/)?.[0];
  if (literal) {
    const [year, month, day] = literal.split('-').map(Number);
    return new Intl.DateTimeFormat('id-ID', { day: '2-digit', month: 'short', year: 'numeric' })
      .format(new Date(year, month - 1, day));
  }
  return String(value);
}

function stageLabel(row = {}) {
  const stage = Number(row.status_setoran || 0);
  if (stage === 1) return 'Rekap / menunggu pencatatan';
  if (stage === 2) return 'Tercatat / siap cocokkan';
  if (stage === 3) return 'Final';
  return 'Tidak aktif';
}

function stageBadge(row = {}) {
  const stage = Number(row.status_setoran || 0);
  const className = stage === 1
    ? 'inline-flex rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800 dark:bg-amber-300 dark:text-slate-950'
    : stage === 2
      ? 'inline-flex rounded-full bg-sky-100 px-3 py-1 text-xs font-semibold text-sky-800 dark:bg-sky-300 dark:text-slate-950'
      : 'inline-flex rounded-full bg-slate-200 px-3 py-1 text-xs font-semibold text-slate-700 dark:bg-slate-700 dark:text-slate-100';
  return { text: stageLabel(row), className };
}

function cancellationBadge(row = {}) {
  if (row.can_cancel) {
    return {
      text: 'Dapat dibatalkan',
      className: 'inline-flex rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-800 dark:bg-emerald-300 dark:text-slate-950'
    };
  }
  return {
    text: 'Terkunci',
    className: 'inline-flex rounded-full bg-rose-100 px-3 py-1 text-xs font-semibold text-rose-800 dark:bg-rose-300 dark:text-slate-950'
  };
}

function normalizeCandidate(row = {}) {
  return {
    ...row,
    id_setoran: row.id_setoran ?? row.id,
    nominal_setoran: Number(row.nominal_setoran ?? row.jumlah_setoran ?? 0),
    nominal_pembayaran_mobile: Number(row.nominal_pembayaran_mobile ?? 0),
    can_cancel: Boolean(row.can_cancel),
    status_setoran: Number(row.status_setoran || 0)
  };
}

const summary = computed(() => ({
  total: rows.value.length,
  ready: rows.value.filter((row) => row.can_cancel).length,
  recorded: rows.value.filter((row) => Number(row.status_setoran) === 2).length,
  blocked: rows.value.filter((row) => !row.can_cancel).length
}));

const columns = [
  {
    key: 'faktur',
    label: 'Faktur / SO',
    render: (row) => `${row.no_faktur || '-'}${row.no_order ? `\nSO: ${row.no_order}` : ''}`
  },
  {
    key: 'customer',
    label: 'Customer',
    render: (row) => `${row.nama_customer || '-'}${row.kode_customer ? `\n${row.kode_customer}` : ''}`
  },
  { key: 'nama_sales', label: 'Sales', render: (row) => row.nama_sales || '-' },
  { key: 'kode_lph', label: 'LPH', render: (row) => row.kode_lph || '-' },
  { key: 'nominal_setoran', label: 'Nilai Setoran', render: (row) => formatCurrency(row.nominal_setoran) },
  { key: 'status_setoran', label: 'Tahap', render: (row) => stageBadge(row) },
  { key: 'can_cancel', label: 'Pembatalan', render: (row) => cancellationBadge(row) }
];

async function loadReferences() {
  loading.refs = true;
  try {
    const [companies, branches, sales] = await Promise.all([getCompanies(), getBranches(), getSales()]);
    companyRows.value = normalizeList(unwrapResponse(companies));
    branchRows.value = normalizeList(unwrapResponse(branches));
    salesRows.value = normalizeList(unwrapResponse(sales));
    if (fallbackCompanyId.value) filters.id_perusahaan = String(fallbackCompanyId.value);
    if (fallbackBranchId.value) filters.id_cabang = String(fallbackBranchId.value);
  } catch (error) {
    pageError.value = normalizeError(error, 'Referensi filter belum dapat dimuat.');
  } finally {
    loading.refs = false;
  }
}

async function loadRows() {
  loading.list = true;
  pageError.value = '';
  try {
    const response = await getPreFinalPaymentCancellationCandidates({
      id_perusahaan: filters.id_perusahaan || undefined,
      id_cabang: filters.id_cabang || undefined,
      id_sales: filters.id_sales || undefined,
      status_setoran: filters.status_setoran || undefined,
      search: filters.search.trim() || undefined,
      limit: 300
    });
    rows.value = normalizeList(unwrapResponse(response)).map(normalizeCandidate);
  } catch (error) {
    rows.value = [];
    pageError.value = normalizeError(error, 'Daftar pembayaran pra-final belum dapat dimuat.');
  } finally {
    loading.list = false;
  }
}

function resetFilters() {
  filters.id_perusahaan = String(fallbackCompanyId.value || '');
  filters.id_cabang = String(fallbackBranchId.value || '');
  filters.id_sales = '';
  filters.status_setoran = '';
  filters.search = '';
  loadRows();
}

function openDetail(row) {
  selectedRow.value = row;
  cancellationForm.reason = '';
  actionError.value = '';
  detailOpen.value = true;
}

async function submitCancellation() {
  if (!selectedRow.value || !canSubmitCancellation.value) {
    actionError.value = !canCancel.value
      ? 'Pembatalan membutuhkan hak akses Finance untuk memperbarui Rekap Pembayaran.'
      : 'Alasan pembatalan wajib diisi minimal 5 karakter.';
    return;
  }

  loading.cancel = true;
  actionError.value = '';
  try {
    const response = await cancelPreFinalPayment({
      id_setoran: selectedRow.value.id_setoran,
      reason: cancellationForm.reason.trim()
    });
    const payload = unwrapResponse(response) || {};
    feedback.value = payload.message || 'Pembayaran pra-final dibatalkan dan jejak audit telah disimpan.';
    detailOpen.value = false;
    selectedRow.value = null;
    await loadRows();
  } catch (error) {
    actionError.value = normalizeError(error, 'Pembatalan pembayaran belum dapat disimpan.');
  } finally {
    loading.cancel = false;
  }
}

onMounted(async () => {
  await loadReferences();
  await loadRows();
});
</script>

<template>
  <section class="space-y-6">
    <PageHeader
      title="Batal Pembayaran"
      description="Batalkan setoran Rekap yang belum final secara terkendali; sumber pembayaran Mobile Sales akan dibuka kembali untuk diproses ulang."
    >
      <button class="button-secondary" :disabled="loading.list" @click="loadRows">
        {{ loading.list ? 'Memuat...' : 'Muat Ulang' }}
      </button>
    </PageHeader>

    <section class="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-950 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-100">
      <p class="font-semibold">Batas pembatalan aman</p>
      <p class="mt-1">Menu ini hanya untuk pembayaran dari Mobile Sales yang sudah masuk Rekap/Setoran tetapi belum final. Jika sudah ada alokasi mutasi, penggunaan uang muka, mutasi lama, atau jurnal Finance, batalkan dahulu melalui alur audit terkait. Data tidak dihapus.</p>
    </section>

    <section class="panel p-5">
      <div class="grid min-w-0 gap-4 [grid-template-columns:repeat(auto-fit,minmax(200px,1fr))]">
        <AppSearchSelect
          :model-value="filters.id_perusahaan"
          label="Perusahaan"
          placeholder="Semua perusahaan"
          :options="companyOptions"
          :loading="loading.refs"
          @update:model-value="(value) => { filters.id_perusahaan = String(value || ''); filters.id_cabang = ''; filters.id_sales = ''; }"
        />
        <AppSearchSelect
          :model-value="filters.id_cabang"
          label="Cabang"
          placeholder="Semua cabang"
          :options="branchOptions"
          :loading="loading.refs"
          @update:model-value="(value) => { filters.id_cabang = String(value || ''); filters.id_sales = ''; }"
        />
        <AppSearchSelect
          :model-value="filters.id_sales"
          label="Sales"
          placeholder="Semua sales"
          :options="salesOptions"
          :loading="loading.refs"
          @update:model-value="(value) => { filters.id_sales = String(value || ''); }"
        />
        <AppSearchSelect
          :model-value="filters.status_setoran"
          label="Tahap setoran"
          placeholder="Semua tahap pra-final"
          :options="statusOptions"
          @update:model-value="(value) => { filters.status_setoran = String(value || ''); }"
        />
        <label class="block">
          <span class="field-label">Cari</span>
          <input v-model="filters.search" class="field-control" placeholder="Faktur, SO, customer, atau ID setoran" @keyup.enter="loadRows" />
        </label>
        <div class="flex items-end gap-2">
          <button class="button-primary w-full" :disabled="loading.list" @click="loadRows">Terapkan</button>
          <button class="button-secondary shrink-0" @click="resetFilters">Reset</button>
        </div>
      </div>
    </section>

    <section class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <article class="panel p-5"><p class="section-eyebrow">Pembayaran pra-final</p><p class="mt-2 text-xl font-bold text-slate-950 dark:text-white">{{ summary.total }}</p></article>
      <article class="panel p-5"><p class="section-eyebrow">Dapat dibatalkan</p><p class="mt-2 text-xl font-bold text-emerald-600 dark:text-emerald-300">{{ summary.ready }}</p></article>
      <article class="panel p-5"><p class="section-eyebrow">Sudah tercatat</p><p class="mt-2 text-xl font-bold text-sky-600 dark:text-sky-300">{{ summary.recorded }}</p></article>
      <article class="panel p-5"><p class="section-eyebrow">Terkunci oleh audit</p><p class="mt-2 text-xl font-bold text-rose-600 dark:text-rose-300">{{ summary.blocked }}</p></article>
    </section>

    <p v-if="pageError" class="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">{{ pageError }}</p>
    <p v-if="feedback" class="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200">{{ feedback }}</p>

    <section class="space-y-2">
      <p class="text-sm text-slate-500 dark:text-slate-400">Klik satu baris untuk meninjau detail dan alasan pembatalan.</p>
      <AppTable
        :rows="rows"
        :columns="columns"
        :loading="loading.list"
        row-key="id_setoran"
        :selected-key="selectedRow?.id_setoran"
        clickable-rows
        empty-message="Tidak ada pembayaran pra-final pada filter ini."
        @row-click="openDetail"
      />
    </section>

    <AppModal
      :open="detailOpen"
      title="Tinjau Batal Pembayaran"
      description="Pastikan data dan alasannya benar. Tindakan ini tidak menghapus setoran; statusnya dinonaktifkan dan pembayarannya kembali ke antrean Rekap."
      size="xl"
      @close="detailOpen = false"
    >
      <div v-if="selectedRow" class="space-y-5">
        <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <div class="summary-card"><p class="section-eyebrow">Faktur / SO</p><p class="mt-1 font-bold text-slate-950 dark:text-white">{{ selectedRow.no_faktur || '-' }}</p><p class="text-xs text-slate-500 dark:text-slate-400">{{ selectedRow.no_order ? `SO: ${selectedRow.no_order}` : 'SO tidak tersedia' }}</p></div>
          <div class="summary-card"><p class="section-eyebrow">Customer</p><p class="mt-1 font-bold text-slate-950 dark:text-white">{{ selectedRow.nama_customer || '-' }}</p><p class="text-xs text-slate-500 dark:text-slate-400">{{ selectedRow.kode_customer || '-' }}</p></div>
          <div class="summary-card"><p class="section-eyebrow">Sales / LPH</p><p class="mt-1 font-bold text-slate-950 dark:text-white">{{ selectedRow.nama_sales || '-' }}</p><p class="text-xs text-slate-500 dark:text-slate-400">{{ selectedRow.kode_lph || 'Tanpa LPH terhubung' }}</p></div>
          <div class="summary-card"><p class="section-eyebrow">Pembayaran Mobile</p><p class="mt-1 font-bold text-slate-950 dark:text-white">{{ formatCurrency(selectedRow.nominal_pembayaran_mobile) }}</p><p class="text-xs text-slate-500 dark:text-slate-400">{{ selectedRow.tipe_pembayaran_mobile || '-' }}</p></div>
          <div class="summary-card"><p class="section-eyebrow">Nilai setoran</p><p class="mt-1 font-bold text-slate-950 dark:text-white">{{ formatCurrency(selectedRow.nominal_setoran) }}</p><p class="text-xs text-slate-500 dark:text-slate-400">ID setoran: {{ selectedRow.id_setoran }}</p></div>
          <div class="summary-card"><p class="section-eyebrow">Tahap</p><div class="mt-2"><span :class="stageBadge(selectedRow).className">{{ stageBadge(selectedRow).text }}</span></div></div>
        </div>

        <div v-if="!selectedRow.can_cancel" class="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-100">
          <p class="font-semibold">Pembatalan dikunci</p>
          <p class="mt-1">{{ selectedRow.cancellation_block_reason || 'Setoran tidak memenuhi syarat pembatalan pra-final.' }}</p>
        </div>

        <div v-else-if="!canCancel" class="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-100">
          Anda dapat melihat data ini, tetapi pembatalan membutuhkan hak akses Finance untuk memperbarui Rekap Pembayaran.
        </div>

        <label v-else class="block">
          <span class="field-label">Alasan pembatalan</span>
          <textarea v-model="cancellationForm.reason" class="field-control min-h-28" placeholder="Contoh: nominal atau metode pembayaran salah; pembayaran perlu diperbaiki oleh sales." />
          <span class="mt-1 block text-xs text-slate-500 dark:text-slate-400">Minimal 5 karakter. Alasan ini disimpan pada audit Finance.</span>
        </label>

        <p v-if="actionError" class="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">{{ actionError }}</p>
      </div>
      <template #footer>
        <div class="flex flex-wrap justify-end gap-2">
          <button class="button-secondary" @click="detailOpen = false">Tutup</button>
          <button v-if="selectedRow?.can_cancel && canCancel" class="button-danger" :disabled="loading.cancel || !canSubmitCancellation" @click="submitCancellation">
            {{ loading.cancel ? 'Menyimpan audit...' : 'Batalkan Pembayaran Pra-final' }}
          </button>
        </div>
      </template>
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
:global(.dark) .button-secondary { border-color: rgb(51 65 85); color: rgb(226 232 240); }
.button-danger { background: rgb(225 29 72); color: white; }
.button-danger:hover:not(:disabled) { background: rgb(190 24 93); }
.button-primary:disabled, .button-secondary:disabled, .button-danger:disabled { cursor: not-allowed; opacity: .55; }
.field-label, .section-eyebrow { display: block; font-size: .72rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: rgb(100 116 139); }
.field-control { width: 100%; margin-top: .35rem; border: 1px solid rgb(203 213 225); border-radius: .75rem; background: white; padding: .7rem .8rem; color: rgb(15 23 42); }
:global(.dark) .field-control { border-color: rgb(51 65 85); background: rgb(2 6 23); color: rgb(226 232 240); }
.summary-card { border: 1px solid rgb(226 232 240); border-radius: .8rem; padding: .85rem; }
:global(.dark) .summary-card { border-color: rgb(51 65 85); }
</style>
