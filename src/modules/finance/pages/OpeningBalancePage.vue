<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies } from '@/api/master';
import {
  createOpeningBalance,
  deleteOpeningBalance,
  getAccountCoaList,
  getOpeningBalances,
  postOpeningBalance,
  updateOpeningBalance
} from '@/api/finance';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getRowBranchIds, getRowCompanyId, isSuperUser, scopeRowsByLoginBranch } from '@/utils/accessScope';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();

const filters = reactive({
  branchId: '',
  companyId: '',
  coaId: '',
  status: '',
  from: '',
  to: '',
  search: ''
});

const form = reactive({
  id: '',
  id_cabang: '',
  id_perusahaan: '',
  id_coa: '',
  saldo_debit: '',
  saldo_kredit: '',
  tanggal_saldo: new Date().toISOString().slice(0, 10),
  keterangan: ''
});

const rows = ref([]);
const summary = reactive({
  total_debit: 0,
  total_kredit: 0,
  selisih: 0,
  draft: 0,
  posted: 0
});
const branches = ref([]);
const companies = ref([]);
const coas = ref([]);
const modalOpen = ref(false);
const mode = ref('create');
const loading = reactive({
  refs: false,
  list: false,
  save: false,
  post: ''
});
const pageError = ref('');
const actionError = ref('');
const feedback = ref('');

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const canAccessAllBranches = computed(() => isSuperUser(authStore));

const branchOptions = computed(() =>
  scopeRowsByLoginBranch(branches.value, authStore).map((item) => ({
    value: String(item.id),
    label: `${item.kode ? `${item.kode} - ` : ''}${item.nama || item.nama_cabang || `Cabang ${item.id}`}`
  }))
);

function companyIdsForBranch(branchId) {
  if (!branchId) return [];
  const ids = new Set();
  const branch = branches.value.find((item) => String(item.id) === String(branchId));
  const directCompanyId = getRowCompanyId(branch);
  if (directCompanyId) ids.add(String(directCompanyId));
  companies.value.forEach((item) => {
    if (getRowBranchIds(item).some((id) => String(id) === String(branchId))) {
      ids.add(String(item.id));
    }
  });
  return [...ids];
}

function toCompanyOption(item) {
  return {
    value: String(item.id),
    label: `${item.kode ? `${item.kode} - ` : ''}${item.nama || item.nama_perusahaan || `Perusahaan ${item.id}`}`
  };
}

const companyOptions = computed(() => {
  const ids = companyIdsForBranch(filters.branchId);
  return companies.value.filter((item) => ids.includes(String(item.id))).map(toCompanyOption);
});

const formCompanyOptions = computed(() => {
  const ids = companyIdsForBranch(form.id_cabang);
  return companies.value.filter((item) => ids.includes(String(item.id))).map(toCompanyOption);
});

const coaOptions = computed(() =>
  coas.value.map((item) => ({
    value: String(item.id_coa),
    label: `L${item.level || 2} • ${item.nomor_akun || '-'} - ${item.nama_akun || 'COA'}`
  }))
);

const statusOptions = [
  { value: '', label: 'Semua status' },
  { value: 'draft', label: 'Draft' },
  { value: 'posted', label: 'Posted' }
];

const cards = computed(() => [
  { label: 'Total Debit', value: formatCurrency(summary.total_debit), tone: 'text-emerald-700 dark:text-emerald-300' },
  { label: 'Total Kredit', value: formatCurrency(summary.total_kredit), tone: 'text-amber-700 dark:text-amber-300' },
  { label: 'Selisih', value: formatCurrency(summary.selisih), tone: Math.abs(Number(summary.selisih || 0)) < 1 ? 'text-slate-900 dark:text-white' : 'text-rose-700 dark:text-rose-300' },
  { label: 'Draft / Posted', value: `${summary.draft || 0} / ${summary.posted || 0}`, tone: 'text-brand-700 dark:text-brand-300' }
]);

function formatCurrency(value) {
  return new Intl.NumberFormat('id-ID', {
    style: 'currency',
    currency: 'IDR',
    maximumFractionDigits: 2
  }).format(Number(value || 0));
}

function statusClass(status) {
  return status === 'posted'
    ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-200'
    : 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-200';
}

function resetForm() {
  Object.assign(form, {
    id: '',
    id_cabang: filters.branchId || (!canAccessAllBranches.value ? fallbackBranchId.value : '') || '',
    id_perusahaan: filters.companyId || '',
    id_coa: '',
    saldo_debit: '',
    saldo_kredit: '',
    tanggal_saldo: new Date().toISOString().slice(0, 10),
    keterangan: ''
  });
}

function resetFilters() {
  Object.assign(filters, {
    branchId: !canAccessAllBranches.value && fallbackBranchId.value ? String(fallbackBranchId.value) : '',
    companyId: '',
    coaId: '',
    status: '',
    from: '',
    to: '',
    search: ''
  });
  coas.value = [];
  rows.value = [];
  loadRows();
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
    pageError.value = normalizeError(error, 'Referensi cabang/perusahaan belum bisa dimuat.');
  } finally {
    loading.refs = false;
  }
}

async function loadCoas(companyId = filters.companyId) {
  if (!companyId) {
    coas.value = [];
    return;
  }
  try {
    const response = await getAccountCoaList({ id_perusahaan: companyId, include_children: true, min_level: 2 });
    coas.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    coas.value = [];
    pageError.value = normalizeError(error, 'Daftar COA belum bisa dimuat.');
  }
}

async function loadRows() {
  if (filters.branchId && !filters.companyId) {
    rows.value = [];
    return;
  }
  loading.list = true;
  pageError.value = '';
  try {
    const response = await getOpeningBalances({
      id_cabang: filters.branchId || undefined,
      id_perusahaan: filters.companyId || undefined,
      id_coa: filters.coaId || undefined,
      status: filters.status || undefined,
      periode_awal: filters.from || undefined,
      periode_akhir: filters.to || undefined,
      search: filters.search || undefined
    });
    const payload = unwrapResponse(response);
    rows.value = normalizeList(payload);
    Object.assign(summary, response?.data?.summary || payload?.summary || {});
  } catch (error) {
    rows.value = [];
    pageError.value = normalizeError(error, 'Daftar saldo awal belum bisa dimuat.');
  } finally {
    loading.list = false;
  }
}

function openCreate() {
  mode.value = 'create';
  feedback.value = '';
  actionError.value = '';
  resetForm();
  modalOpen.value = true;
  loadCoas(form.id_perusahaan);
}

function openEdit(row) {
  mode.value = 'edit';
  feedback.value = '';
  actionError.value = '';
  Object.assign(form, {
    id: row.id,
    id_cabang: row.id_cabang ? String(row.id_cabang) : '',
    id_perusahaan: row.id_perusahaan ? String(row.id_perusahaan) : '',
    id_coa: row.id_coa ? String(row.id_coa) : '',
    saldo_debit: Number(row.saldo_debit || 0) || '',
    saldo_kredit: Number(row.saldo_kredit || 0) || '',
    tanggal_saldo: row.tanggal_saldo ? String(row.tanggal_saldo).slice(0, 10) : '',
    keterangan: row.keterangan || ''
  });
  modalOpen.value = true;
  loadCoas(form.id_perusahaan);
}

function buildPayload() {
  return {
    id_cabang: form.id_cabang || null,
    id_perusahaan: form.id_perusahaan || null,
    id_coa: form.id_coa || null,
    saldo_debit: Number(form.saldo_debit || 0),
    saldo_kredit: Number(form.saldo_kredit || 0),
    tanggal_saldo: form.tanggal_saldo,
    keterangan: form.keterangan
  };
}

async function save() {
  const debit = Number(form.saldo_debit || 0);
  const kredit = Number(form.saldo_kredit || 0);
  if (!form.id_perusahaan || !form.id_coa || !form.tanggal_saldo) {
    actionError.value = 'Perusahaan, akun COA, dan tanggal saldo awal wajib diisi.';
    return;
  }
  if ((debit <= 0 && kredit <= 0) || (debit > 0 && kredit > 0)) {
    actionError.value = 'Isi salah satu nominal: saldo debit atau saldo kredit.';
    return;
  }

  loading.save = true;
  actionError.value = '';
  feedback.value = '';
  try {
    if (mode.value === 'edit') {
      await updateOpeningBalance(form.id, buildPayload());
      feedback.value = 'Saldo awal berhasil diperbarui.';
    } else {
      await createOpeningBalance(buildPayload());
      feedback.value = 'Saldo awal berhasil disimpan.';
      resetForm();
    }
    await loadRows();
  } catch (error) {
    actionError.value = normalizeError(error, 'Saldo awal belum berhasil disimpan.');
  } finally {
    loading.save = false;
  }
}

async function removeRow(row) {
  if (!window.confirm(`Hapus saldo awal ${row.nomor_akun} - ${row.nama_akun}?`)) return;
  try {
    await deleteOpeningBalance(row.id);
    await loadRows();
    feedback.value = 'Saldo awal berhasil dihapus.';
  } catch (error) {
    pageError.value = normalizeError(error, 'Saldo awal belum bisa dihapus.');
  }
}

async function postRow(row) {
  if (!window.confirm(`Posting jurnal pembukaan untuk ${row.nomor_akun} - ${row.nama_akun}?`)) return;
  loading.post = String(row.id);
  try {
    await postOpeningBalance(row.id);
    await loadRows();
    feedback.value = 'Jurnal pembukaan berhasil diposting.';
  } catch (error) {
    pageError.value = normalizeError(error, 'Jurnal pembukaan belum bisa diposting.');
  } finally {
    loading.post = '';
  }
}

watch(
  () => filters.branchId,
  (value, previousValue) => {
    if (String(value || '') === String(previousValue || '')) return;
    filters.companyId = '';
    filters.coaId = '';
    coas.value = [];
    rows.value = [];
  }
);

watch(
  () => filters.companyId,
  (value, previousValue) => {
    if (String(value || '') === String(previousValue || '')) return;
    filters.coaId = '';
    loadCoas(value);
  }
);

watch(
  companyOptions,
  (options) => {
    if (filters.companyId && !options.some((item) => String(item.value) === String(filters.companyId))) {
      filters.companyId = '';
    }
  }
);

watch(
  () => form.id_cabang,
  (value, previousValue) => {
    if (String(value || '') === String(previousValue || '')) return;
    form.id_perusahaan = '';
    form.id_coa = '';
  }
);

watch(
  () => form.id_perusahaan,
  (value, previousValue) => {
    if (String(value || '') === String(previousValue || '')) return;
    form.id_coa = '';
    loadCoas(value);
  }
);

watch(
  formCompanyOptions,
  (options) => {
    if (form.id_perusahaan && !options.some((item) => String(item.value) === String(form.id_perusahaan))) {
      form.id_perusahaan = '';
    }
  }
);

onMounted(async () => {
  await loadReferences();
  await loadCoas();
  await loadRows();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Saldo Awal"
      description="Input saldo awal COA, validasi debit/kredit, lalu posting jurnal pembukaan agar masuk Buku Besar dan Neraca."
    >
      <div class="flex flex-wrap gap-3">
        <button class="rounded-2xl border border-slate-300 px-4 py-3 text-sm font-bold text-slate-700 dark:border-slate-700 dark:text-slate-200" @click="loadRows">
          Reload
        </button>
        <button class="rounded-2xl bg-brand-600 px-4 py-3 text-sm font-bold text-white" @click="openCreate">
          Tambah Saldo Awal
        </button>
      </div>
    </PageHeader>

    <section class="panel p-5">
      <div class="grid gap-4 lg:grid-cols-4 xl:grid-cols-6">
        <AppSearchSelect v-model="filters.branchId" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="!canAccessAllBranches && !!fallbackBranchId" />
        <AppSearchSelect v-model="filters.companyId" label="Perusahaan" :placeholder="filters.branchId ? 'Pilih perusahaan' : 'Pilih cabang dulu'" :options="companyOptions" :disabled="!filters.branchId" />
        <AppSearchSelect v-model="filters.coaId" label="Akun COA" :placeholder="filters.companyId ? 'Semua akun' : 'Pilih perusahaan dulu'" :options="coaOptions" :disabled="!filters.companyId" />
        <AppSearchSelect v-model="filters.status" label="Status" placeholder="Semua status" :options="statusOptions" />
        <div>
          <label class="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Dari Tanggal</label>
          <input v-model="filters.from" type="date" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
        </div>
        <div>
          <label class="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Sampai Tanggal</label>
          <input v-model="filters.to" type="date" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
        </div>
        <div class="lg:col-span-2">
          <label class="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Cari</label>
          <input v-model="filters.search" type="text" placeholder="Cari akun, keterangan, cabang, perusahaan..." class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
        </div>
        <div class="flex items-end gap-3">
          <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-bold text-white" @click="loadRows">Terapkan</button>
          <button class="rounded-xl border border-slate-300 px-4 py-3 text-sm font-bold text-slate-700 dark:border-slate-700 dark:text-slate-200" @click="resetFilters">Reset</button>
        </div>
      </div>
    </section>

    <section v-if="pageError || feedback" :class="['rounded-2xl border px-4 py-3 text-sm', pageError ? 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200' : 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200']">
      {{ pageError || feedback }}
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <article v-for="card in cards" :key="card.label" class="panel p-5">
        <p class="text-xs font-bold uppercase tracking-[0.3em] text-slate-500">{{ card.label }}</p>
        <p :class="['mt-3 text-xl font-black', card.tone]">{{ card.value }}</p>
      </article>
    </section>

    <section class="panel overflow-hidden">
      <div class="overflow-x-auto">
        <table class="min-w-full divide-y divide-slate-200 dark:divide-slate-800">
          <thead class="bg-slate-50 dark:bg-slate-900/80">
            <tr class="text-left text-xs font-bold uppercase tracking-wide text-slate-500">
              <th class="px-5 py-4">Tanggal</th>
              <th class="px-5 py-4">Cabang</th>
              <th class="px-5 py-4">Perusahaan</th>
              <th class="px-5 py-4">COA</th>
              <th class="px-5 py-4 text-right">Debit</th>
              <th class="px-5 py-4 text-right">Kredit</th>
              <th class="px-5 py-4">Status</th>
              <th class="px-5 py-4">Aksi</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-200 dark:divide-slate-800">
            <tr v-if="loading.list">
              <td colspan="8" class="px-5 py-8 text-center text-sm text-slate-500">Memuat saldo awal...</td>
            </tr>
            <tr v-else-if="!rows.length">
              <td colspan="8" class="px-5 py-8 text-center text-sm text-slate-500">Belum ada saldo awal untuk filter ini.</td>
            </tr>
            <tr v-for="row in rows" v-else :key="row.id" class="text-sm text-slate-700 dark:text-slate-200">
              <td class="px-5 py-4">{{ row.tanggal_saldo || '-' }}</td>
              <td class="px-5 py-4">{{ row.nama_cabang || '-' }}</td>
              <td class="px-5 py-4">{{ row.nama_perusahaan || '-' }}</td>
              <td class="px-5 py-4">
                <p class="font-bold">{{ row.nomor_akun || '-' }}</p>
                <p class="text-xs text-slate-500">{{ row.nama_akun || '-' }}</p>
              </td>
              <td class="px-5 py-4 text-right font-bold">{{ formatCurrency(row.saldo_debit) }}</td>
              <td class="px-5 py-4 text-right font-bold">{{ formatCurrency(row.saldo_kredit) }}</td>
              <td class="px-5 py-4">
                <span :class="['inline-flex rounded-full px-3 py-1 text-xs font-bold', statusClass(row.status)]">{{ row.status }}</span>
              </td>
              <td class="px-5 py-4">
                <div class="flex flex-wrap gap-2">
                  <button class="rounded-lg border border-slate-300 px-3 py-2 text-xs font-bold dark:border-slate-700" :disabled="row.status === 'posted'" @click="openEdit(row)">Edit</button>
                  <button class="rounded-lg bg-brand-600 px-3 py-2 text-xs font-bold text-white disabled:opacity-50" :disabled="row.status === 'posted' || loading.post === String(row.id)" @click="postRow(row)">
                    {{ loading.post === String(row.id) ? 'Posting...' : 'Posting' }}
                  </button>
                  <button class="rounded-lg border border-rose-300 px-3 py-2 text-xs font-bold text-rose-600 disabled:opacity-50 dark:border-rose-500/40 dark:text-rose-200" :disabled="row.status === 'posted'" @click="removeRow(row)">Hapus</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <AppModal
      :open="modalOpen"
      :title="mode === 'create' ? 'Tambah Saldo Awal' : 'Edit Saldo Awal'"
      description="Isi salah satu sisi saldo. Posting akan otomatis membuat jurnal pembukaan yang balance."
      size="2xl"
      @close="modalOpen = false"
    >
      <div class="space-y-5">
        <section v-if="actionError || feedback" :class="['rounded-2xl border px-4 py-3 text-sm', actionError ? 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200' : 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200']">
          {{ actionError || feedback }}
        </section>

        <div class="grid gap-4 md:grid-cols-2">
          <AppSearchSelect v-model="form.id_cabang" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="!canAccessAllBranches && !!fallbackBranchId" />
          <AppSearchSelect v-model="form.id_perusahaan" label="Perusahaan" :placeholder="form.id_cabang ? 'Pilih perusahaan' : 'Pilih cabang dulu'" :options="formCompanyOptions" :disabled="!form.id_cabang" />
          <AppSearchSelect v-model="form.id_coa" label="Akun COA" :placeholder="form.id_perusahaan ? 'Pilih akun COA' : 'Pilih perusahaan dulu'" :options="coaOptions" :disabled="!form.id_perusahaan" />
          <div>
            <label class="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Tanggal Saldo Awal</label>
            <input v-model="form.tanggal_saldo" type="date" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
          </div>
          <div>
            <label class="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Saldo Debit</label>
            <input v-model="form.saldo_debit" type="number" min="0" placeholder="0" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
          </div>
          <div>
            <label class="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Saldo Kredit</label>
            <input v-model="form.saldo_kredit" type="number" min="0" placeholder="0" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
          </div>
          <div class="md:col-span-2">
            <label class="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Keterangan</label>
            <textarea v-model="form.keterangan" rows="3" placeholder="Contoh: Saldo awal kas per awal periode" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white"></textarea>
          </div>
        </div>
      </div>

      <template #footer>
        <div class="flex justify-end gap-3">
          <button class="rounded-xl border border-slate-300 px-4 py-3 text-sm font-bold text-slate-700 dark:border-slate-700 dark:text-slate-200" @click="modalOpen = false">Tutup</button>
          <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-bold text-white disabled:opacity-60" :disabled="loading.save" @click="save">
            {{ loading.save ? 'Menyimpan...' : 'Simpan Saldo Awal' }}
          </button>
        </div>
      </template>
    </AppModal>
  </div>
</template>
