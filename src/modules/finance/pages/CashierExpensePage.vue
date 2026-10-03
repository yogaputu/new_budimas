<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies } from '@/api/master';
import { confirmCashierExpense, createCashierExpense, getCashierExpenses, getCashierExpenseDetail, getCoaCatalog } from '@/api/finance';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getRowBranchIds, getRowCompanyIds, isSuperUser, scopeRowsByLoginBranch } from '@/utils/accessScope';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Jakarta', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
let detailKey = 0;
const newDetail = () => ({ key: ++detailKey, id_coa: '', keterangan: '', nominal: '' });

const filters = reactive({
  branchId: '',
  companyId: '',
  date: today,
  status: ''
});

const form = reactive({
  id_cabang: '',
  id_perusahaan: '',
  pic: '',
  tanggal_pengeluaran: today,
  details: [newDetail()]
});

const rows = ref([]);
const branches = ref([]);
const companies = ref([]);
const loading = reactive({ refs: false, list: false, save: false, confirm: false, coa: false, detail: false });
const pageError = ref('');
const feedback = ref('');
const actionError = ref('');
const modalOpen = ref(false);
const coaRows = ref([]);
const coaError = ref('');
const selectedExpense = ref(null);
const detailOpen = ref(false);
const detailError = ref('');
let coaSequence = 0;
let expenseSequence = 0;
const totalExpense = computed(() => form.details.reduce((sum, row) => sum + Math.round(Number(row.nominal || 0) * 100), 0) / 100);
const coaOptions = computed(() => coaRows.value.map((row) => ({ value: String(row.id_coa), label: `${row.nomor_akun} - ${row.nama_akun}` })));

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const canAccessAllBranches = computed(() => isSuperUser(authStore));

const branchOptions = computed(() =>
  scopeRowsByLoginBranch(branches.value.map((item) => ({ ...item, id_cabang: item.id })), authStore).map((item) => ({
    value: String(item.id),
    label: `${item.kode ? `${item.kode} - ` : ''}${item.nama || item.nama_cabang || `Cabang ${item.id}`}`
  }))
);

function companyIdsForBranch(branchId) {
  if (!branchId) return [];
  const ids = new Set();
  const branch = branches.value.find((item) => String(item.id) === String(branchId));
  getRowCompanyIds(branch).forEach((id) => ids.add(String(id)));

  companies.value.forEach((item) => {
    if (getRowBranchIds(item).some((id) => String(id) === String(branchId))) {
      ids.add(String(item.id));
    }
  });

  return [...ids];
}

function companyOption(item) {
  return {
    value: String(item.id),
    label: `${item.kode ? `${item.kode} - ` : ''}${item.nama || item.nama_perusahaan || `Perusahaan ${item.id}`}`
  };
}

const filterCompanyOptions = computed(() => {
  const allowed = companyIdsForBranch(filters.branchId);
  return companies.value.filter((item) => allowed.includes(String(item.id))).map(companyOption);
});

const formCompanyOptions = computed(() => {
  const allowed = companyIdsForBranch(form.id_cabang);
  return companies.value.filter((item) => allowed.includes(String(item.id))).map(companyOption);
});

const statusOptions = [
  { value: '', label: 'Semua Status' },
  { value: '1', label: 'Diajukan' },
  { value: '2', label: 'Disetujui' },
  { value: '3', label: 'Diberikan' },
  { value: '4', label: 'Ditolak' }
];

const columns = [
  { key: 'no_pengeluaran', label: 'No Pengeluaran' },
  { key: 'tanggal_pengeluaran', label: 'Tanggal Pengeluaran', render: (row) => formatDate(row.tanggal_pengeluaran || row.tanggal_pengajuan) },
  { key: 'nama_cabang', label: 'Cabang' },
  { key: 'nama_perusahaan', label: 'Perusahaan' },
  { key: 'nama_kasir', label: 'Kasir' },
  { key: 'pic', label: 'PIC' },
  { key: 'jumlah_pengeluaran', label: 'Pengeluaran', render: (row) => formatCurrency(row.jumlah_pengeluaran) },
  { key: 'status_pengeluaran', label: 'Status', render: (row) => statusBadge(row.status_pengeluaran) },
  { key: 'aksi', label: 'Aksi', render: () => 'Lihat rincian' }
];

function formatCurrency(value) {
  return new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value || 0));
}

function formatDate(value) { return value ? new Intl.DateTimeFormat('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(String(value).slice(0, 10) + 'T00:00:00')) : '-'; }

function formatDateTime(value) {
  if (!value) return '-';
  return new Intl.DateTimeFormat('id-ID', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  }).format(new Date(value));
}

function statusBadge(status) {
  const map = {
    1: { text: 'Diajukan', className: 'inline-flex rounded-full bg-amber-100 px-3 py-1 text-xs font-bold text-amber-700' },
    2: { text: 'Disetujui', className: 'inline-flex rounded-full bg-blue-100 px-3 py-1 text-xs font-bold text-blue-700' },
    3: { text: 'Diberikan', className: 'inline-flex rounded-full bg-emerald-100 px-3 py-1 text-xs font-bold text-emerald-700' },
    4: { text: 'Ditolak', className: 'inline-flex rounded-full bg-rose-100 px-3 py-1 text-xs font-bold text-rose-700' }
  };
  return map[Number(status)] || { text: 'Unknown', className: 'inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-bold text-slate-700' };
}

function userId() {
  return authStore.user?.id || authStore.user?.id_user || '';
}

function userPositionId() {
  return authStore.user?.id_jabatan || authStore.user?.jabatan_id || authStore.user?.jabatan?.id || '';
}

function resetForm() {
  Object.assign(form, {
    id_cabang: filters.branchId || (!canAccessAllBranches.value ? fallbackBranchId.value : ''),
    id_perusahaan: filters.companyId || '',
    pic: authStore.user?.nama || '',
    tanggal_pengeluaran: filters.date || today,
    details: [newDetail()]
  });
}

async function loadReferences() {
  loading.refs = true;
  try {
    const [branchResponse, companyResponse] = await Promise.all([getBranches(), getCompanies()]);
    branches.value = normalizeList(unwrapResponse(branchResponse));
    companies.value = normalizeList(unwrapResponse(companyResponse));
    if (!canAccessAllBranches.value && fallbackBranchId.value) {
      filters.branchId = String(fallbackBranchId.value);
    }
  } catch (error) {
    pageError.value = normalizeError(error, 'Referensi pengeluaran kasir belum bisa dimuat.');
  } finally {
    loading.refs = false;
  }
}

async function loadRows() {
  loading.list = true;
  pageError.value = '';
  try {
    const response = await getCashierExpenses({
      id_cabang: filters.branchId || undefined,
      id_perusahaan: filters.companyId || undefined,
      tanggal_pengeluaran: filters.date || undefined,
      status_pengeluaran: filters.status || undefined,
      id_user: userId(),
      id_jabatan: userPositionId(),
      'no-paginate': 'true'
    });
    rows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    rows.value = [];
    pageError.value = normalizeError(error, 'Daftar pengeluaran kasir belum bisa dimuat.');
  } finally {
    loading.list = false;
  }
}

function openCreate() {
  feedback.value = '';
  actionError.value = '';
  resetForm();
  modalOpen.value = true;
}

async function saveExpense() {
  if (loading.save) return;
  if (!form.id_cabang || !form.id_perusahaan || !form.pic.trim() || !form.tanggal_pengeluaran) {
    actionError.value = 'Cabang, perusahaan, tanggal pengeluaran, dan PIC wajib diisi.';
    return;
  }
  if (loading.coa || coaError.value || !form.details.length || form.details.some((row) => !coaOptions.value.some((option) => option.value === String(row.id_coa)) || !row.keterangan.trim() || !Number.isFinite(Number(row.nominal)) || Number(row.nominal) <= 0 || Math.abs(Number(row.nominal) * 100 - Math.round(Number(row.nominal) * 100)) > 0.0001)) {
    actionError.value = 'Setiap detail wajib berisi COA, keterangan, dan nominal positif (maksimal 2 desimal).';
    return;
  }

  loading.save = true;
  actionError.value = '';
  feedback.value = '';
  try {
    await createCashierExpense({
      ...form,
      details: form.details.map(({ id_coa, keterangan, nominal }) => ({ id_coa: Number(id_coa), keterangan: keterangan.trim(), nominal: String(nominal) })),
      id_user: userId()
    });
    feedback.value = 'Pengeluaran kasir berhasil ditambahkan.';
    modalOpen.value = false;
    await loadRows();
  } catch (error) {
    actionError.value = normalizeError(error, 'Pengeluaran kasir belum berhasil disimpan.');
  } finally {
    loading.save = false;
  }
}

async function confirmExpense(row) {
  if (loading.confirm || Number(row.status_pengeluaran) !== 1) return;
  const confirmed = window.confirm(`Konfirmasi pengeluaran ${row.no_pengeluaran}?`);
  if (!confirmed) return;

  loading.confirm = true;
  pageError.value = '';
  feedback.value = '';
  try {
    await confirmCashierExpense({ id_pengeluaran: row.id });
    feedback.value = 'Pengeluaran kasir berhasil dikonfirmasi.';
    detailOpen.value = false;
    await loadRows();
  } catch (error) {
    detailError.value = normalizeError(error, 'Pengeluaran kasir belum bisa dikonfirmasi.');
  } finally {
    loading.confirm = false;
  }
}

async function loadCoa() {
  const sequence = ++coaSequence;
  coaRows.value = [];
  coaError.value = '';
  form.details.forEach((row) => { row.id_coa = ''; });
  if (!form.id_perusahaan || !form.id_cabang) { loading.coa = false; return; }
  loading.coa = true;
  try {
    const response = await getCoaCatalog({ id_perusahaan: form.id_perusahaan, id_cabang: form.id_cabang, is_active: 'true', 'no-paginate': 'true' });
    if (sequence === coaSequence) coaRows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    if (sequence === coaSequence) coaError.value = normalizeError(error, 'COA belum bisa dimuat.');
  } finally { if (sequence === coaSequence) loading.coa = false; }
}

async function openDetail(row) {
  const sequence = ++expenseSequence;
  selectedExpense.value = null;
  detailError.value = '';
  detailOpen.value = true;
  loading.detail = true;
  try {
    const response = await getCashierExpenseDetail(row.id);
    if (sequence === expenseSequence) selectedExpense.value = unwrapResponse(response);
  } catch (error) {
    if (sequence === expenseSequence) detailError.value = normalizeError(error, 'Rincian pengeluaran belum bisa dimuat.');
  } finally { if (sequence === expenseSequence) loading.detail = false; }
}

watch(
  () => filters.branchId,
  () => {
    filters.companyId = '';
    rows.value = [];
  }
);

watch(
  () => form.id_cabang,
  () => {
    if (!formCompanyOptions.value.some((option) => option.value === String(form.id_perusahaan))) form.id_perusahaan = '';
  }
);
watch(() => [form.id_cabang, form.id_perusahaan], loadCoa);

onMounted(async () => {
  await loadReferences();
  await loadRows();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Pengeluaran Kasir"
      description="Pengajuan, monitoring, dan konfirmasi pengeluaran kasir per cabang dan perusahaan."
    >
      <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-bold text-white" @click="openCreate">
        Tambah Pengeluaran
      </button>
    </PageHeader>

    <section class="panel p-5">
      <div class="grid gap-4 lg:grid-cols-5">
        <AppSearchSelect
          v-model="filters.branchId"
          label="Cabang"
          placeholder="Pilih cabang"
          :options="branchOptions"
          :disabled="!canAccessAllBranches && !!fallbackBranchId"
        />
        <AppSearchSelect
          v-model="filters.companyId"
          label="Perusahaan"
          placeholder="Semua perusahaan"
          :options="filterCompanyOptions"
          :disabled="!filters.branchId"
          empty-text="Pilih cabang terlebih dahulu."
        />
        <AppSearchSelect v-model="filters.status" label="Status" placeholder="Semua status" :options="statusOptions" />
        <div>
          <label class="field-label">Tanggal Pengeluaran</label>
          <input v-model="filters.date" type="date" class="field-control" />
        </div>
        <button class="self-end rounded-xl bg-brand-600 px-4 py-3 text-sm font-bold text-white" @click="loadRows">
          Terapkan
        </button>
      </div>
    </section>

    <section v-if="feedback" class="rounded-2xl border border-emerald-300/40 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-700 dark:text-emerald-200">
      {{ feedback }}
    </section>
    <section v-if="pageError" class="rounded-2xl border border-rose-300/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-700 dark:text-rose-200">
      {{ pageError }}
    </section>

    <AppTable
      :columns="columns"
      :rows="rows"
      :loading="loading.list || loading.confirm"
      clickable-rows
      row-key="id"
      empty-message="Belum ada pengeluaran kasir pada filter ini."
      @row-click="openDetail"
    />

    <AppModal
      :open="modalOpen"
      title="Tambah Pengeluaran Kasir"
      description="Pilih perusahaan dan cabang, kemudian rincikan akun serta nominal pengeluaran."
      size="4xl"
      :close-on-backdrop="!loading.save"
      :hide-close="loading.save"
      @close="!loading.save && (modalOpen = false)"
    >
      <section v-if="actionError" class="mb-4 rounded-2xl border border-rose-300/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-700 dark:text-rose-200">
        {{ actionError }}
      </section>
      <fieldset :disabled="loading.save" class="min-w-0">
      <div class="grid gap-4 md:grid-cols-2">
        <AppSearchSelect
          v-model="form.id_cabang"
          label="Cabang"
          placeholder="Pilih cabang"
          :options="branchOptions"
          :disabled="loading.save || (!canAccessAllBranches && !!fallbackBranchId)"
        />
        <AppSearchSelect
          v-model="form.id_perusahaan"
          label="Perusahaan"
          placeholder="Pilih perusahaan"
          :options="formCompanyOptions"
          :disabled="loading.save || !form.id_cabang"
          empty-text="Pilih cabang terlebih dahulu."
        />
        <div>
          <label for="expense-date" class="field-label">Tanggal Pengeluaran</label>
          <input id="expense-date" v-model="form.tanggal_pengeluaran" type="date" class="field-control" required />
        </div>
        <div>
          <label for="expense-pic" class="field-label">PIC</label>
          <input id="expense-pic" v-model="form.pic" type="text" maxlength="100" class="field-control" />
        </div>
      </div>
      <div class="mt-6 flex items-center justify-between gap-3">
        <h3 class="font-bold">Detail Pengeluaran</h3>
        <button class="rounded-xl border border-slate-500 px-3 py-2 text-sm font-bold disabled:opacity-50" :disabled="form.details.length >= 200 || loading.save" @click="form.details.push(newDetail())">+ Tambah Detail</button>
      </div>
      <p class="my-2 text-sm text-slate-400">Setiap baris memiliki akun COA, keterangan, dan nominal. Total dihitung otomatis.</p>
      <p v-if="coaError" role="alert" class="my-2 text-sm text-rose-400">{{ coaError }} <button class="underline" @click="loadCoa">Coba lagi</button></p>
      <div class="overflow-x-auto">
        <table class="expense-details w-full min-w-[740px] text-sm">
          <thead><tr><th>No.</th><th class="w-[32%]">Akun COA</th><th>Keterangan</th><th class="w-[20%]">Nominal (Rp)</th><th>Aksi</th></tr></thead>
          <tbody><tr v-for="(line, index) in form.details" :key="line.key">
            <td>{{ index + 1 }}</td>
            <td><AppSearchSelect v-model="line.id_coa" :label="`COA baris ${index + 1}`" :options="coaOptions" :loading="loading.coa" :disabled="loading.save || !form.id_perusahaan || !form.id_cabang" placeholder="Pilih akun COA" empty-text="Tidak ada COA aktif untuk perusahaan/cabang ini." /></td>
            <td><textarea v-model="line.keterangan" :aria-label="`Keterangan baris ${index + 1}`" rows="2" maxlength="2000" class="field-control" placeholder="Keterangan pengeluaran" /></td>
            <td><input v-model="line.nominal" :aria-label="`Nominal baris ${index + 1}`" type="number" min="0.01" step="0.01" max="9999999999999.99" class="field-control" placeholder="0" /></td>
            <td><button :aria-label="`Hapus baris ${index + 1}`" class="text-rose-400 disabled:opacity-40" :disabled="loading.save || form.details.length === 1" @click="form.details.splice(index, 1)">Hapus</button></td>
          </tr></tbody>
        </table>
      </div>
      <div class="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-500/40 p-4">
        <span class="font-bold">Total Pengeluaran · {{ form.details.length }} detail</span>
        <output aria-label="Total pengeluaran" class="text-xl font-bold">{{ formatCurrency(totalExpense) }}</output>
      </div>
      </fieldset>
      <template #footer>
        <div class="flex justify-end gap-3">
          <button class="rounded-xl border border-slate-700 px-4 py-3 text-sm font-bold" :disabled="loading.save" @click="modalOpen = false">Tutup</button>
          <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-bold text-white disabled:opacity-60" :disabled="loading.save || loading.coa || !!coaError" @click="saveExpense">
            {{ loading.save ? 'Menyimpan...' : 'Simpan Pengeluaran' }}
          </button>
        </div>
      </template>
    </AppModal>

    <AppModal :open="detailOpen" title="Rincian Pengeluaran Kasir" size="4xl" :hide-close="loading.confirm" :close-on-backdrop="!loading.confirm" @close="!loading.confirm && (detailOpen = false)">
      <p v-if="loading.detail">Memuat rincian…</p>
      <p v-if="detailError" role="alert" class="mb-4 text-rose-400">{{ detailError }}</p>
      <template v-if="selectedExpense && !loading.detail">
        <dl class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <div><dt class="field-label">No Pengeluaran</dt><dd>{{ selectedExpense.no_pengeluaran }}</dd></div>
          <div><dt class="field-label">Perusahaan</dt><dd>{{ selectedExpense.nama_perusahaan }}</dd></div>
          <div><dt class="field-label">Cabang</dt><dd>{{ selectedExpense.nama_cabang }}</dd></div>
          <div><dt class="field-label">Tanggal Pengeluaran</dt><dd>{{ formatDate(selectedExpense.tanggal_pengeluaran) }}</dd></div>
          <div><dt class="field-label">PIC</dt><dd>{{ selectedExpense.pic }}</dd></div>
          <div><dt class="field-label">Dicatat pada</dt><dd>{{ formatDateTime(selectedExpense.tanggal_pengajuan) }}</dd></div>
        </dl>
        <div v-if="selectedExpense.details?.length" class="mt-5 overflow-x-auto">
          <table class="expense-details w-full min-w-[560px] text-sm">
            <thead><tr><th>No.</th><th>Akun COA</th><th>Keterangan</th><th>Nominal</th></tr></thead>
            <tbody><tr v-for="line in selectedExpense.details" :key="line.id"><td>{{ line.nomor_baris }}</td><td>{{ line.nomor_akun }} — {{ line.nama_akun }}</td><td class="whitespace-pre-wrap">{{ line.keterangan }}</td><td class="whitespace-nowrap">{{ formatCurrency(line.nominal) }}</td></tr></tbody>
          </table>
        </div>
        <div v-else class="mt-5 rounded-xl border border-amber-500/40 p-4 text-sm">
          <p>Dokumen lama: rincian COA per baris belum tersedia.</p><p class="mt-2 whitespace-pre-wrap">{{ selectedExpense.keterangan_pengeluaran || '-' }}</p>
        </div>
        <p class="mt-5 text-right text-xl font-bold">Total {{ formatCurrency(selectedExpense.jumlah_pengeluaran) }}</p>
      </template>
      <template #footer><div class="flex justify-end gap-3">
        <button class="rounded-xl border border-slate-500 px-4 py-3 font-bold" :disabled="loading.confirm" @click="detailOpen = false">Tutup</button>
        <button v-if="selectedExpense && !loading.detail && Number(selectedExpense.status_pengeluaran) === 1" class="rounded-xl bg-brand-600 px-4 py-3 font-bold text-white disabled:opacity-50" :disabled="loading.confirm" @click="confirmExpense(selectedExpense)">{{ loading.confirm ? 'Memproses…' : 'Konfirmasi Pengeluaran' }}</button>
      </div></template>
    </AppModal>
  </div>
</template>

<style scoped>
.expense-details th, .expense-details td { padding: 12px 8px; text-align: left; border-bottom: 1px solid #64748b40; vertical-align: top; }
.expense-details th { font-weight: 700; }
</style>
