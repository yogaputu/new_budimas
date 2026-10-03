<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies } from '@/api/master';
import {
  createFixedAsset,
  deleteFixedAsset,
  getFixedAssets,
  getFixedAssetSchedule,
  getInventoryTaxRules,
  updateFixedAsset
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
  status: '',
  taxRuleKey: '',
  search: ''
});

const form = reactive({
  id: '',
  kode_asset: '',
  nama_asset: '',
  id_cabang: '',
  id_perusahaan: '',
  kategori_asset: '',
  tax_rule_key: '',
  depreciation_method: 'straight_line',
  posting_policy: 'annual_dec31',
  acquisition_date: new Date().toISOString().slice(0, 10),
  start_depreciation_date: new Date().toISOString().slice(0, 10),
  acquisition_cost: '',
  residual_value: '0',
  location: '',
  serial_number: '',
  pic: '',
  status: 'active',
  notes: ''
});

const rows = ref([]);
const rules = ref([]);
const branches = ref([]);
const companies = ref([]);
const modalOpen = ref(false);
const scheduleModalOpen = ref(false);
const mode = ref('create');
const pageError = ref('');
const actionError = ref('');
const feedback = ref('');
const scheduleError = ref('');
const selectedSchedule = ref(null);

const loading = reactive({
  refs: false,
  list: false,
  save: false,
  delete: '',
  schedule: false
});

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

const ruleOptions = computed(() =>
  rules.value.map((item) => ({
    value: item.key,
    label: `${item.label} - ${item.useful_life_years} tahun`
  }))
);

const statusOptions = [
  { value: '', label: 'Semua status' },
  { value: 'active', label: 'Aktif' },
  { value: 'disposed', label: 'Dilepas' },
  { value: 'inactive', label: 'Nonaktif' }
];

const postingPolicyOptions = [
  { value: 'annual_dec31', label: 'Posting tahunan 31 Desember' },
  { value: 'monthly_fiscal', label: 'Fiskal bulanan' }
];

const selectedRule = computed(() => rules.value.find((item) => item.key === form.tax_rule_key));
const methodOptions = computed(() => {
  const options = [{ value: 'straight_line', label: 'Garis lurus' }];
  if (selectedRule.value?.declining_balance_rate_percent) {
    options.push({ value: 'declining_balance', label: 'Saldo menurun' });
  }
  return options;
});

const summary = computed(() => {
  const totals = rows.value.reduce(
    (acc, row) => {
      acc.count += 1;
      acc.cost += Number(row.acquisition_cost || 0);
      acc.accumulated += Number(row.current_accumulated_depreciation || row.accumulated_depreciation || 0);
      acc.book += Number(row.current_book_value || row.book_value || 0);
      return acc;
    },
    { count: 0, cost: 0, accumulated: 0, book: 0 }
  );
  return [
    { label: 'Total Aset', value: totals.count, tone: 'text-slate-900 dark:text-white' },
    { label: 'Nilai Perolehan', value: formatCurrency(totals.cost), tone: 'text-brand-700 dark:text-brand-300' },
    { label: 'Akumulasi Penyusutan', value: formatCurrency(totals.accumulated), tone: 'text-amber-700 dark:text-amber-300' },
    { label: 'Nilai Buku', value: formatCurrency(totals.book), tone: 'text-emerald-700 dark:text-emerald-300' }
  ];
});

function formatCurrency(value) {
  return new Intl.NumberFormat('id-ID', {
    style: 'currency',
    currency: 'IDR',
    maximumFractionDigits: 0
  }).format(Number(value || 0));
}

function formatDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString('id-ID');
}

function methodLabel(value) {
  return value === 'declining_balance' ? 'Saldo menurun' : 'Garis lurus';
}

function postingPolicyLabel(value) {
  return postingPolicyOptions.find((item) => item.value === value)?.label || 'Fiskal bulanan';
}

function statusClass(status) {
  if (status === 'active') return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-200';
  if (status === 'disposed') return 'bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-200';
  return 'bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-200';
}

function resetForm() {
  Object.assign(form, {
    id: '',
    kode_asset: '',
    nama_asset: '',
    id_cabang: filters.branchId || (!canAccessAllBranches.value ? fallbackBranchId.value : '') || '',
    id_perusahaan: filters.companyId || '',
    kategori_asset: '',
    tax_rule_key: rules.value[0]?.key || '',
    depreciation_method: 'straight_line',
    posting_policy: 'annual_dec31',
    acquisition_date: new Date().toISOString().slice(0, 10),
    start_depreciation_date: new Date().toISOString().slice(0, 10),
    acquisition_cost: '',
    residual_value: '0',
    location: '',
    serial_number: '',
    pic: '',
    status: 'active',
    notes: ''
  });
}

function resetFilters() {
  Object.assign(filters, {
    branchId: !canAccessAllBranches.value && fallbackBranchId.value ? String(fallbackBranchId.value) : '',
    companyId: '',
    status: '',
    taxRuleKey: '',
    search: ''
  });
  loadRows();
}

async function loadReferences() {
  loading.refs = true;
  try {
    const [branchResponse, companyResponse, ruleResponse] = await Promise.all([getBranches(), getCompanies(), getInventoryTaxRules()]);
    branches.value = normalizeList(unwrapResponse(branchResponse));
    companies.value = normalizeList(unwrapResponse(companyResponse));
    rules.value = normalizeList(unwrapResponse(ruleResponse));
    if (!canAccessAllBranches.value && fallbackBranchId.value) {
      filters.branchId = String(fallbackBranchId.value);
    }
  } catch (error) {
    pageError.value = normalizeError(error, 'Referensi inventaris belum bisa dimuat.');
  } finally {
    loading.refs = false;
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
    const response = await getFixedAssets({
      id_cabang: filters.branchId || undefined,
      id_perusahaan: filters.companyId || undefined,
      status: filters.status || undefined,
      tax_rule_key: filters.taxRuleKey || undefined,
      search: filters.search || undefined
    });
    rows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    rows.value = [];
    pageError.value = normalizeError(error, 'Daftar inventaris belum bisa dimuat.');
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
}

function openEdit(row) {
  mode.value = 'edit';
  feedback.value = '';
  actionError.value = '';
  Object.assign(form, {
    id: row.id,
    kode_asset: row.kode_asset || '',
    nama_asset: row.nama_asset || '',
    id_cabang: row.id_cabang ? String(row.id_cabang) : '',
    id_perusahaan: row.id_perusahaan ? String(row.id_perusahaan) : '',
    kategori_asset: row.kategori_asset || '',
    tax_rule_key: row.tax_rule_key || '',
    depreciation_method: row.depreciation_method || 'straight_line',
    posting_policy: row.posting_policy || 'monthly_fiscal',
    acquisition_date: String(row.acquisition_date || '').slice(0, 10),
    start_depreciation_date: String(row.start_depreciation_date || row.acquisition_date || '').slice(0, 10),
    acquisition_cost: row.acquisition_cost || '',
    residual_value: row.residual_value ?? '0',
    location: row.location || '',
    serial_number: row.serial_number || '',
    pic: row.pic || '',
    status: row.status || 'active',
    notes: row.notes || ''
  });
  modalOpen.value = true;
}

function buildPayload() {
  return {
    kode_asset: form.kode_asset,
    nama_asset: form.nama_asset,
    id_cabang: form.id_cabang || null,
    id_perusahaan: form.id_perusahaan || null,
    kategori_asset: form.kategori_asset,
    tax_rule_key: form.tax_rule_key,
    depreciation_method: form.depreciation_method,
    posting_policy: form.posting_policy,
    acquisition_date: form.acquisition_date,
    start_depreciation_date: form.start_depreciation_date || form.acquisition_date,
    acquisition_cost: form.acquisition_cost,
    residual_value: form.residual_value || 0,
    location: form.location,
    serial_number: form.serial_number,
    pic: form.pic,
    status: form.status,
    notes: form.notes
  };
}

async function save() {
  loading.save = true;
  actionError.value = '';
  feedback.value = '';
  try {
    if (mode.value === 'edit' && form.id) {
      await updateFixedAsset(form.id, buildPayload());
      feedback.value = 'Inventaris berhasil diperbarui.';
    } else {
      await createFixedAsset(buildPayload());
      feedback.value = 'Inventaris berhasil ditambahkan.';
    }
    await loadRows();
    modalOpen.value = false;
  } catch (error) {
    actionError.value = normalizeError(error, 'Inventaris belum bisa disimpan.');
  } finally {
    loading.save = false;
  }
}

async function removeRow(row) {
  if (!confirm(`Hapus inventaris ${row.kode_asset || row.nama_asset}?`)) return;
  loading.delete = String(row.id);
  pageError.value = '';
  try {
    await deleteFixedAsset(row.id);
    await loadRows();
  } catch (error) {
    pageError.value = normalizeError(error, 'Inventaris belum bisa dihapus.');
  } finally {
    loading.delete = '';
  }
}

async function openSchedule(row) {
  scheduleModalOpen.value = true;
  scheduleError.value = '';
  selectedSchedule.value = null;
  loading.schedule = true;
  try {
    const response = await getFixedAssetSchedule(row.id);
    selectedSchedule.value = unwrapResponse(response);
  } catch (error) {
    scheduleError.value = normalizeError(error, 'Jadwal penyusutan belum bisa dimuat.');
  } finally {
    loading.schedule = false;
  }
}

watch(
  () => filters.branchId,
  () => {
    if (filters.companyId && !companyOptions.value.some((item) => item.value === String(filters.companyId))) {
      filters.companyId = '';
    }
    loadRows();
  }
);

watch(
  () => filters.companyId,
  () => loadRows()
);

watch(
  () => [filters.status, filters.taxRuleKey],
  () => loadRows()
);

watch(
  () => form.id_cabang,
  () => {
    if (form.id_perusahaan && !formCompanyOptions.value.some((item) => item.value === String(form.id_perusahaan))) {
      form.id_perusahaan = '';
    }
  }
);

watch(
  () => form.tax_rule_key,
  () => {
    if (!methodOptions.value.some((item) => item.value === form.depreciation_method)) {
      form.depreciation_method = 'straight_line';
    }
  }
);

onMounted(async () => {
  await loadReferences();
  await loadRows();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader title="Inventaris" description="Kelola aset tetap, hitung penyusutan fiskal, dan pilih posting bulanan atau tahunan 31 Desember." >
      <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-bold text-white shadow-sm hover:bg-brand-700" @click="openCreate">
        Tambah Inventaris
      </button>
    </PageHeader>

    <section v-if="pageError || feedback" :class="['rounded-2xl border px-5 py-4 text-sm font-semibold', pageError ? 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200' : 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200']">
      {{ pageError || feedback }}
    </section>

    <section class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div class="grid gap-4 lg:grid-cols-5">
        <AppSearchSelect v-model="filters.branchId" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="loading.refs || (!canAccessAllBranches && !!fallbackBranchId)" />
        <AppSearchSelect v-model="filters.companyId" label="Perusahaan" :placeholder="filters.branchId ? 'Pilih perusahaan' : 'Pilih cabang dulu'" :options="companyOptions" :disabled="loading.refs || !filters.branchId" />
        <AppSearchSelect v-model="filters.taxRuleKey" label="Kelompok Fiskal" placeholder="Semua kelompok" :options="[{ value: '', label: 'Semua kelompok' }, ...ruleOptions]" />
        <AppSearchSelect v-model="filters.status" label="Status" placeholder="Semua status" :options="statusOptions" />
        <div>
          <label class="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Cari</label>
          <input v-model="filters.search" type="search" placeholder="Kode, nama, lokasi, PIC" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-brand-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white" @keyup.enter="loadRows" />
        </div>
      </div>
      <div class="mt-4 flex flex-wrap gap-3">
        <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-bold text-white disabled:opacity-60" :disabled="loading.list" @click="loadRows">
          {{ loading.list ? 'Memuat...' : 'Terapkan' }}
        </button>
        <button class="rounded-xl border border-slate-300 px-4 py-3 text-sm font-bold text-slate-700 dark:border-slate-700 dark:text-slate-200" @click="resetFilters">
          Reset
        </button>
      </div>
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <div v-for="card in summary" :key="card.label" class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <p class="text-xs font-bold uppercase tracking-[0.25em] text-slate-500">{{ card.label }}</p>
        <p :class="['mt-3 text-2xl font-black', card.tone]">{{ card.value }}</p>
      </div>
    </section>

    <section class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div class="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <p class="text-xs font-bold uppercase tracking-[0.25em] text-brand-600 dark:text-brand-300">Acuan fiskal</p>
          <h2 class="text-xl font-black text-slate-900 dark:text-white">Kelompok dan tarif penyusutan</h2>
        </div>
        <p class="max-w-3xl text-sm text-slate-500 dark:text-slate-400">
          Bangunan memakai metode garis lurus. Harta bukan bangunan dapat memakai garis lurus atau saldo menurun sesuai kelompok fiskal.
        </p>
      </div>
      <div class="mt-4 grid gap-3 lg:grid-cols-3">
        <div v-for="rule in rules" :key="rule.key" class="rounded-2xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-950/60">
          <p class="font-black text-slate-900 dark:text-white">{{ rule.label }}</p>
          <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">{{ rule.description }}</p>
          <div class="mt-3 grid grid-cols-3 gap-2 text-xs font-bold">
            <span class="rounded-xl bg-white px-3 py-2 text-slate-700 dark:bg-slate-900 dark:text-slate-200">{{ rule.useful_life_years }} tahun</span>
            <span class="rounded-xl bg-white px-3 py-2 text-emerald-700 dark:bg-slate-900 dark:text-emerald-200">GL {{ rule.straight_line_rate_percent }}%</span>
            <span class="rounded-xl bg-white px-3 py-2 text-amber-700 dark:bg-slate-900 dark:text-amber-200">SM {{ rule.declining_balance_rate_percent || '-' }}%</span>
          </div>
        </div>
      </div>
    </section>

    <section class="rounded-3xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div class="border-b border-slate-200 px-5 py-4 dark:border-slate-800">
        <h2 class="text-xl font-black text-slate-900 dark:text-white">Daftar Inventaris</h2>
        <p class="text-sm text-slate-500">Nilai buku mengikuti kebijakan posting: bulanan fiskal atau tahunan per 31 Desember.</p>
      </div>
      <div class="overflow-x-auto">
        <table class="min-w-full divide-y divide-slate-200 text-left dark:divide-slate-800">
          <thead class="bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-950/60">
            <tr>
              <th class="px-5 py-4">Inventaris</th>
              <th class="px-5 py-4">Scope</th>
              <th class="px-5 py-4">Kelompok</th>
              <th class="px-5 py-4">Metode</th>
              <th class="px-5 py-4">Posting</th>
              <th class="px-5 py-4">Tanggal</th>
              <th class="px-5 py-4 text-right">Perolehan</th>
              <th class="px-5 py-4 text-right">Akumulasi</th>
              <th class="px-5 py-4 text-right">Nilai Buku</th>
              <th class="px-5 py-4">Status</th>
              <th class="px-5 py-4">Aksi</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-200 dark:divide-slate-800">
            <tr v-if="loading.list">
              <td colspan="11" class="px-5 py-10 text-center text-sm text-slate-500">Memuat inventaris...</td>
            </tr>
            <tr v-else-if="!rows.length">
              <td colspan="11" class="px-5 py-10 text-center text-sm text-slate-500">Belum ada inventaris untuk filter ini.</td>
            </tr>
            <tr v-for="row in rows" v-else :key="row.id" class="text-sm text-slate-700 dark:text-slate-200">
              <td class="px-5 py-4">
                <p class="font-black">{{ row.kode_asset || '-' }}</p>
                <p class="text-xs text-slate-500">{{ row.nama_asset || '-' }}</p>
              </td>
              <td class="px-5 py-4">
                <p class="font-bold">{{ row.nama_cabang || '-' }}</p>
                <p class="text-xs text-slate-500">{{ row.nama_perusahaan || '-' }}</p>
              </td>
              <td class="px-5 py-4">
                <p class="font-bold">{{ row.tax_group || '-' }}</p>
                <p class="text-xs text-slate-500">{{ row.kategori_asset || '-' }}</p>
              </td>
              <td class="px-5 py-4">{{ methodLabel(row.depreciation_method) }}</td>
              <td class="px-5 py-4">
                <p class="font-bold">{{ postingPolicyLabel(row.posting_policy) }}</p>
                <p v-if="row.posting_policy === 'annual_dec31'" class="text-xs text-slate-500">Akumulasi ditampilkan per akhir tahun</p>
              </td>
              <td class="px-5 py-4">
                <p>{{ formatDate(row.acquisition_date) }}</p>
                <p class="text-xs text-slate-500">Mulai {{ formatDate(row.start_depreciation_date) }}</p>
              </td>
              <td class="px-5 py-4 text-right font-bold">{{ formatCurrency(row.acquisition_cost) }}</td>
              <td class="px-5 py-4 text-right font-bold text-amber-700 dark:text-amber-200">{{ formatCurrency(row.current_accumulated_depreciation || row.accumulated_depreciation) }}</td>
              <td class="px-5 py-4 text-right font-bold text-emerald-700 dark:text-emerald-200">{{ formatCurrency(row.current_book_value || row.book_value) }}</td>
              <td class="px-5 py-4">
                <span :class="['inline-flex rounded-full px-3 py-1 text-xs font-bold', statusClass(row.status)]">{{ row.status }}</span>
              </td>
              <td class="px-5 py-4">
                <div class="flex flex-wrap gap-2">
                  <button class="rounded-lg bg-slate-900 px-3 py-2 text-xs font-bold text-white dark:bg-slate-700" @click="openSchedule(row)">Jadwal</button>
                  <button class="rounded-lg border border-slate-300 px-3 py-2 text-xs font-bold dark:border-slate-700" @click="openEdit(row)">Edit</button>
                  <button class="rounded-lg border border-rose-300 px-3 py-2 text-xs font-bold text-rose-600 disabled:opacity-50 dark:border-rose-500/40 dark:text-rose-200" :disabled="loading.delete === String(row.id)" @click="removeRow(row)">Hapus</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <AppModal
      :open="modalOpen"
      :title="mode === 'create' ? 'Tambah Inventaris' : 'Edit Inventaris'"
      description="Kelompok fiskal menentukan masa manfaat dan tarif penyusutan."
      size="4xl"
      @close="modalOpen = false"
    >
      <div class="space-y-5">
        <section v-if="actionError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-semibold text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
          {{ actionError }}
        </section>

        <div class="grid gap-4 md:grid-cols-2">
          <div>
            <label class="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Kode Inventaris</label>
            <input v-model="form.kode_asset" placeholder="Contoh: INV-BMM-0001" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
          </div>
          <div>
            <label class="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Nama Inventaris</label>
            <input v-model="form.nama_asset" placeholder="Laptop, kendaraan, rak gudang, dll" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
          </div>
          <AppSearchSelect v-model="form.id_cabang" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="!canAccessAllBranches && !!fallbackBranchId" />
          <AppSearchSelect v-model="form.id_perusahaan" label="Perusahaan" :placeholder="form.id_cabang ? 'Pilih perusahaan' : 'Pilih cabang dulu'" :options="formCompanyOptions" :disabled="!form.id_cabang" />
          <div>
            <label class="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Kategori Internal</label>
            <input v-model="form.kategori_asset" placeholder="IT, kendaraan, bangunan, gudang" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
          </div>
          <AppSearchSelect v-model="form.tax_rule_key" label="Kelompok Fiskal" placeholder="Pilih kelompok fiskal" :options="ruleOptions" />
          <AppSearchSelect v-model="form.depreciation_method" label="Metode Penyusutan" placeholder="Pilih metode" :options="methodOptions" />
          <AppSearchSelect v-model="form.posting_policy" label="Kebijakan Posting" placeholder="Pilih kebijakan posting" :options="postingPolicyOptions" />
          <AppSearchSelect v-model="form.status" label="Status" placeholder="Pilih status" :options="statusOptions.filter((item) => item.value)" />
          <div>
            <label class="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Tanggal Perolehan</label>
            <input v-model="form.acquisition_date" type="date" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
          </div>
          <div>
            <label class="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Mulai Penyusutan</label>
            <input v-model="form.start_depreciation_date" type="date" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
          </div>
          <div>
            <label class="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Nilai Perolehan</label>
            <input v-model="form.acquisition_cost" type="number" min="0" placeholder="0" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
          </div>
          <div>
            <label class="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Nilai Residu</label>
            <input v-model="form.residual_value" type="number" min="0" placeholder="0" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
          </div>
          <div>
            <label class="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Lokasi</label>
            <input v-model="form.location" placeholder="Gudang, kantor, cabang" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
          </div>
          <div>
            <label class="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Serial Number</label>
            <input v-model="form.serial_number" placeholder="Opsional" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
          </div>
          <div>
            <label class="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">PIC</label>
            <input v-model="form.pic" placeholder="Penanggung jawab" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
          </div>
          <div class="md:col-span-2">
            <label class="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Catatan</label>
            <textarea v-model="form.notes" rows="3" placeholder="Catatan inventaris" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white"></textarea>
          </div>
        </div>
      </div>

      <template #footer>
        <div class="flex justify-end gap-3">
          <button class="rounded-xl border border-slate-300 px-4 py-3 text-sm font-bold text-slate-700 dark:border-slate-700 dark:text-slate-200" @click="modalOpen = false">Tutup</button>
          <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-bold text-white disabled:opacity-60" :disabled="loading.save" @click="save">
            {{ loading.save ? 'Menyimpan...' : 'Simpan Inventaris' }}
          </button>
        </div>
      </template>
    </AppModal>

    <AppModal
      :open="scheduleModalOpen"
      title="Jadwal Penyusutan"
      description="Jadwal mengikuti kebijakan posting aset. Mode tahunan menggabungkan penyusutan ke tanggal 31 Desember."
      size="7xl"
      @close="scheduleModalOpen = false"
    >
      <div v-if="loading.schedule" class="py-10 text-center text-sm text-slate-500">Memuat jadwal penyusutan...</div>
      <section v-else-if="scheduleError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-semibold text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
        {{ scheduleError }}
      </section>
      <div v-else-if="selectedSchedule" class="space-y-4">
        <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div class="rounded-2xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-950/60">
            <p class="text-xs font-bold uppercase tracking-wide text-slate-500">Aset</p>
            <p class="mt-2 break-words font-black leading-snug text-slate-900 dark:text-white">{{ selectedSchedule.asset?.kode_asset }}</p>
            <p class="text-xs text-slate-500">{{ selectedSchedule.asset?.nama_asset }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-950/60">
            <p class="text-xs font-bold uppercase tracking-wide text-slate-500">Nilai Perolehan</p>
            <p class="mt-2 whitespace-nowrap text-lg font-black text-slate-900 dark:text-white">{{ formatCurrency(selectedSchedule.asset?.acquisition_cost) }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-950/60">
            <p class="text-xs font-bold uppercase tracking-wide text-slate-500">Akumulasi</p>
            <p class="mt-2 whitespace-nowrap text-lg font-black text-amber-700 dark:text-amber-200">{{ formatCurrency(selectedSchedule.summary?.accumulated_depreciation) }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-950/60">
            <p class="text-xs font-bold uppercase tracking-wide text-slate-500">Nilai Buku</p>
            <p class="mt-2 whitespace-nowrap text-lg font-black text-emerald-700 dark:text-emerald-200">{{ formatCurrency(selectedSchedule.summary?.book_value) }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-950/60 md:col-span-2 xl:col-span-4">
            <p class="text-xs font-bold uppercase tracking-wide text-slate-500">Kebijakan Posting</p>
            <p class="mt-2 font-black text-slate-900 dark:text-white">{{ postingPolicyLabel(selectedSchedule.asset?.posting_policy) }}</p>
          </div>
        </div>
        <div class="max-h-[60vh] overflow-auto rounded-2xl border border-slate-200 dark:border-slate-800">
          <table class="min-w-full divide-y divide-slate-200 text-left text-sm dark:divide-slate-800">
            <thead class="sticky top-0 bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-950">
              <tr>
                <th class="px-5 py-3">Periode / Tanggal Posting</th>
                <th class="px-5 py-3 text-right">Penyusutan</th>
                <th class="px-5 py-3 text-right">Akumulasi</th>
                <th class="px-5 py-3 text-right">Nilai Buku</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-200 dark:divide-slate-800">
              <tr v-for="item in selectedSchedule.schedule || []" :key="item.period" class="align-top">
                <td class="px-5 py-4 font-bold">
                  <p>{{ item.period }}</p>
                  <p v-if="item.posting_date" class="text-xs font-semibold text-slate-500">{{ formatDate(item.posting_date) }}</p>
                </td>
                <td class="whitespace-nowrap px-5 py-4 text-right font-semibold">{{ formatCurrency(item.depreciation_amount) }}</td>
                <td class="whitespace-nowrap px-5 py-4 text-right font-semibold">{{ formatCurrency(item.accumulated_depreciation) }}</td>
                <td class="whitespace-nowrap px-5 py-4 text-right font-semibold">{{ formatCurrency(item.book_value) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </AppModal>
  </div>
</template>
