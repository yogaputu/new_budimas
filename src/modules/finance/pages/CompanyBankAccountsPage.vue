<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies } from '@/api/master';
import {
  createCompanyBankAccount,
  deleteCompanyBankAccount,
  getCompanyBankAccounts,
  updateCompanyBankAccount
} from '@/api/finance';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getRowBranchIds, getRowCompanyId, isSuperUser, scopeRowsByLoginBranch } from '@/utils/accessScope';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const PERMISSION_RESOURCE = 'finance.company-bank-accounts';
const LEGACY_PERMISSION_RESOURCE = 'm.finance.rp';

const filters = reactive({
  branchId: '',
  companyId: '',
  active: '',
  search: ''
});

const form = reactive({
  id_rekening_perusahaan: '',
  id_cabang: '',
  id_perusahaan: '',
  nama_bank: '',
  nomor_rekening: '',
  nama_pemilik: '',
  is_aktif: true
});

const rows = ref([]);
const branches = ref([]);
const companies = ref([]);
const loading = reactive({
  refs: false,
  list: false,
  save: false
});
const modalOpen = ref(false);
const mode = ref('create');
const selectedRow = ref(null);
const pageError = ref('');
const actionError = ref('');
const feedback = ref('');

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const canAccessAllBranches = computed(() => isSuperUser(authStore));
const canCreateAccount = computed(() => hasAccountPermission('create'));
const canUpdateAccount = computed(() => hasAccountPermission('update'));
const canDeleteAccount = computed(() => hasAccountPermission('delete'));
const canSaveCurrentMode = computed(() => mode.value === 'create' ? canCreateAccount.value : canUpdateAccount.value);
const isFormReadOnly = computed(() => !canSaveCurrentMode.value);

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

function companyOption(item) {
  return {
    value: String(item.id),
    label: `${item.kode ? `${item.kode} - ` : ''}${item.nama || item.nama_perusahaan || `Perusahaan ${item.id}`}`
  };
}

const filterCompanyOptions = computed(() => {
  const allowed = companyIdsForBranch(filters.branchId);
  return companies.value.filter((item) => !filters.branchId || allowed.includes(String(item.id))).map(companyOption);
});

const formCompanyOptions = computed(() => {
  const allowed = companyIdsForBranch(form.id_cabang);
  return companies.value.filter((item) => !form.id_cabang || allowed.includes(String(item.id))).map(companyOption);
});

const activeOptions = [
  { value: '', label: 'Semua status' },
  { value: 'true', label: 'Aktif' },
  { value: 'false', label: 'Nonaktif' }
];

const columns = [
  { key: 'nama_bank', label: 'Bank / Kas', render: (row) => row.nama_bank || '-' },
  { key: 'nomor_rekening', label: 'Nomor Rekening', render: (row) => row.nomor_rekening || '-' },
  { key: 'nama_pemilik', label: 'Nama Pemilik', render: (row) => row.nama_pemilik || '-' },
  { key: 'nama_perusahaan', label: 'Perusahaan', render: (row) => resolveCompanyName(row.id_perusahaan) },
  { key: 'nama_cabang', label: 'Cabang', render: (row) => resolveBranchName(row.id_cabang) },
  {
    key: 'is_aktif',
    label: 'Status',
    render: (row) => activeBadge(row.is_aktif)
  }
];

const visibleRows = computed(() => {
  const query = filters.search.trim().toLowerCase();
  return rows.value.filter((item) => {
    const sameBranch = !filters.branchId || String(item.id_cabang || '') === String(filters.branchId);
    const sameCompany = !filters.companyId || String(item.id_perusahaan || '') === String(filters.companyId);
    const sameActive = filters.active === '' || String(Boolean(item.is_aktif)) === String(filters.active);
    const matchesSearch = !query || [
      item.nama_bank,
      item.nomor_rekening,
      item.nama_pemilik,
      resolveCompanyName(item.id_perusahaan),
      resolveBranchName(item.id_cabang)
    ].filter(Boolean).some((value) => String(value).toLowerCase().includes(query));

    return sameBranch && sameCompany && sameActive && matchesSearch;
  });
});

const summary = computed(() => ({
  total: rows.value.length,
  active: rows.value.filter((item) => item.is_aktif).length,
  inactive: rows.value.filter((item) => !item.is_aktif).length
}));

function activeBadge(value) {
  return value
    ? { text: 'Aktif', className: 'inline-flex rounded-full bg-emerald-100 px-3 py-1 text-xs font-bold text-emerald-700' }
    : { text: 'Nonaktif', className: 'inline-flex rounded-full bg-slate-200 px-3 py-1 text-xs font-bold text-slate-600' };
}

function hasAccountPermission(action) {
  return (
    authStore.hasPermission(`${PERMISSION_RESOURCE}.${action}`) ||
    authStore.hasPermission(`${LEGACY_PERMISSION_RESOURCE}.${action}`)
  );
}

function resolveCompanyName(id) {
  return companies.value.find((item) => String(item.id) === String(id))?.nama || companies.value.find((item) => String(item.id) === String(id))?.nama_perusahaan || '-';
}

function resolveBranchName(id) {
  if (!id) return '-';
  const branch = branches.value.find((item) => String(item.id) === String(id));
  if (!branch) return '-';
  return `${branch.kode ? `${branch.kode} - ` : ''}${branch.nama || branch.nama_cabang || `Cabang ${id}`}`;
}

function normalizeAccount(row = {}) {
  return {
    ...row,
    id_rekening_perusahaan: row.id_rekening_perusahaan || row.id,
    is_aktif: row.is_aktif === true || row.is_aktif === 1 || row.is_aktif === '1' || String(row.is_aktif).toLowerCase() === 'true'
  };
}

function resetForm() {
  Object.assign(form, {
    id_rekening_perusahaan: '',
    id_cabang: canAccessAllBranches.value ? (filters.branchId || '') : String(fallbackBranchId.value || filters.branchId || ''),
    id_perusahaan: filters.companyId || '',
    nama_bank: '',
    nomor_rekening: '',
    nama_pemilik: '',
    is_aktif: true
  });
}

function buildPayload() {
  return {
    id_cabang: form.id_cabang || '',
    id_perusahaan: form.id_perusahaan || '',
    nama_bank: form.nama_bank.trim(),
    nomor_rekening: form.nomor_rekening.trim(),
    nama_pemilik: form.nama_pemilik.trim(),
    is_aktif: form.is_aktif ? 'true' : 'false'
  };
}

async function loadReferences() {
  loading.refs = true;
  pageError.value = '';
  try {
    const [branchResponse, companyResponse] = await Promise.all([getBranches(), getCompanies()]);
    branches.value = normalizeList(unwrapResponse(branchResponse));
    companies.value = normalizeList(unwrapResponse(companyResponse));
    if (!canAccessAllBranches.value && fallbackBranchId.value) {
      filters.branchId = String(fallbackBranchId.value);
    }
  } catch (error) {
    pageError.value = normalizeError(error, 'Referensi cabang dan perusahaan belum bisa dimuat.');
  } finally {
    loading.refs = false;
  }
}

async function loadRows() {
  loading.list = true;
  pageError.value = '';
  try {
    const response = await getCompanyBankAccounts({
      order: 'asc',
      field: 'nama_bank'
    });
    rows.value = normalizeList(unwrapResponse(response)).map(normalizeAccount);
  } catch (error) {
    rows.value = [];
    pageError.value = normalizeError(error, 'Data rekening perusahaan belum bisa dimuat.');
  } finally {
    loading.list = false;
  }
}

function openCreate() {
  if (!canCreateAccount.value) {
    feedback.value = '';
    actionError.value = 'Role Anda belum memiliki akses tambah rekening perusahaan.';
    return;
  }

  mode.value = 'create';
  selectedRow.value = null;
  feedback.value = '';
  actionError.value = '';
  resetForm();
  modalOpen.value = true;
}

function openEdit(row) {
  mode.value = 'edit';
  selectedRow.value = row;
  feedback.value = '';
  actionError.value = '';
  Object.assign(form, {
    id_rekening_perusahaan: row.id_rekening_perusahaan || row.id || '',
    id_cabang: row.id_cabang ? String(row.id_cabang) : '',
    id_perusahaan: row.id_perusahaan ? String(row.id_perusahaan) : '',
    nama_bank: row.nama_bank || '',
    nomor_rekening: row.nomor_rekening || '',
    nama_pemilik: row.nama_pemilik || '',
    is_aktif: Boolean(row.is_aktif)
  });
  modalOpen.value = true;
}

async function save() {
  if (!canSaveCurrentMode.value) {
    actionError.value = mode.value === 'create'
      ? 'Role Anda belum memiliki akses tambah rekening perusahaan.'
      : 'Role Anda belum memiliki akses edit rekening perusahaan.';
    return;
  }

  if (!form.id_cabang) {
    actionError.value = 'Cabang wajib dipilih.';
    return;
  }
  if (!form.id_perusahaan) {
    actionError.value = 'Perusahaan wajib dipilih.';
    return;
  }
  if (!form.nama_bank.trim()) {
    actionError.value = 'Nama bank/kas wajib diisi.';
    return;
  }
  if (!form.nomor_rekening.trim()) {
    actionError.value = 'Nomor rekening wajib diisi.';
    return;
  }

  loading.save = true;
  actionError.value = '';
  feedback.value = '';
  try {
    if (mode.value === 'create') {
      await createCompanyBankAccount(buildPayload());
      feedback.value = 'Rekening perusahaan berhasil ditambahkan.';
      resetForm();
    } else {
      await updateCompanyBankAccount(form.id_rekening_perusahaan, buildPayload());
      feedback.value = 'Rekening perusahaan berhasil diperbarui.';
    }
    await loadRows();
  } catch (error) {
    actionError.value = normalizeError(error, 'Rekening perusahaan belum berhasil disimpan.');
  } finally {
    loading.save = false;
  }
}

async function toggleActive() {
  if (!selectedRow.value?.id_rekening_perusahaan) return;
  if (!canUpdateAccount.value) {
    actionError.value = 'Role Anda belum memiliki akses edit rekening perusahaan.';
    return;
  }

  loading.save = true;
  actionError.value = '';
  feedback.value = '';
  const nextActive = !form.is_aktif;
  try {
    await updateCompanyBankAccount(selectedRow.value.id_rekening_perusahaan, {
      ...buildPayload(),
      is_aktif: nextActive ? 'true' : 'false'
    });
    form.is_aktif = nextActive;
    feedback.value = nextActive ? 'Rekening berhasil diaktifkan.' : 'Rekening berhasil dinonaktifkan.';
    await loadRows();
  } catch (error) {
    actionError.value = normalizeError(error, 'Status rekening belum berhasil diubah.');
  } finally {
    loading.save = false;
  }
}

async function remove() {
  if (!selectedRow.value?.id_rekening_perusahaan) return;
  if (!canDeleteAccount.value) {
    actionError.value = 'Role Anda belum memiliki akses hapus rekening perusahaan.';
    return;
  }

  const confirmed = window.confirm('Hapus rekening perusahaan ini? Jika sudah dipakai transaksi, proses hapus bisa ditolak database.');
  if (!confirmed) return;

  loading.save = true;
  actionError.value = '';
  feedback.value = '';
  try {
    await deleteCompanyBankAccount(selectedRow.value.id_rekening_perusahaan);
    feedback.value = 'Rekening perusahaan berhasil dihapus.';
    modalOpen.value = false;
    await loadRows();
  } catch (error) {
    actionError.value = normalizeError(error, 'Rekening belum bisa dihapus. Nonaktifkan jika rekening sudah dipakai transaksi.');
  } finally {
    loading.save = false;
  }
}

watch(
  () => filters.branchId,
  () => {
    filters.companyId = '';
  }
);

watch(
  () => form.id_cabang,
  () => {
    if (form.id_perusahaan && !formCompanyOptions.value.some((item) => String(item.value) === String(form.id_perusahaan))) {
      form.id_perusahaan = '';
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
    <PageHeader
      title="Rekening Perusahaan"
      description="Kelola rekening kas/bank perusahaan yang dipakai untuk refund CN, mutasi bank, setoran non tunai, dan transaksi kas/bank."
    >
      <button
        v-if="canCreateAccount"
        class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-bold text-white hover:bg-brand-700 disabled:opacity-60"
        :disabled="loading.refs"
        @click="openCreate"
      >
        Tambah Rekening
      </button>
    </PageHeader>

    <section class="panel p-5">
      <div class="grid gap-4 xl:grid-cols-[minmax(180px,1fr)_minmax(220px,1.2fr)_minmax(160px,0.8fr)_minmax(240px,1.2fr)_auto]">
        <AppSearchSelect
          v-model="filters.branchId"
          label="Cabang"
          placeholder="Semua cabang"
          :options="branchOptions"
          :disabled="!canAccessAllBranches && !!fallbackBranchId"
        />
        <AppSearchSelect
          v-model="filters.companyId"
          label="Perusahaan"
          placeholder="Semua perusahaan"
          :options="filterCompanyOptions"
          :disabled="!!filters.branchId && !filterCompanyOptions.length"
          empty-text="Perusahaan tidak ditemukan."
        />
        <AppSearchSelect v-model="filters.active" label="Status" placeholder="Semua status" :options="activeOptions" />
        <AppFormField v-model="filters.search" label="Cari" placeholder="Bank, nomor rekening, pemilik" />
        <button class="self-end rounded-xl bg-slate-900 px-4 py-3 text-sm font-bold text-white hover:bg-slate-800 dark:bg-brand-600 dark:hover:bg-brand-700" @click="loadRows">
          Refresh
        </button>
      </div>
    </section>

    <section class="grid gap-4 md:grid-cols-3">
      <div class="panel p-5">
        <p class="text-sm font-semibold text-slate-500 dark:text-slate-400">Total Rekening</p>
        <p class="mt-3 text-3xl font-black text-slate-950 dark:text-white">{{ summary.total.toLocaleString('id-ID') }}</p>
      </div>
      <div class="panel p-5">
        <p class="text-sm font-semibold text-slate-500 dark:text-slate-400">Aktif</p>
        <p class="mt-3 text-3xl font-black text-emerald-600">{{ summary.active.toLocaleString('id-ID') }}</p>
      </div>
      <div class="panel p-5">
        <p class="text-sm font-semibold text-slate-500 dark:text-slate-400">Nonaktif</p>
        <p class="mt-3 text-3xl font-black text-slate-500">{{ summary.inactive.toLocaleString('id-ID') }}</p>
      </div>
    </section>

    <section v-if="feedback" class="rounded-2xl border border-emerald-300/40 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
      {{ feedback }}
    </section>
    <section v-if="pageError" class="rounded-2xl border border-rose-300/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
      {{ pageError }}
    </section>

    <AppTable
      :rows="visibleRows"
      :columns="columns"
      :loading="loading.list || loading.refs"
      clickable-rows
      row-key="id_rekening_perusahaan"
      empty-message="Rekening perusahaan belum tersedia."
      @row-click="openEdit"
    />

    <AppModal
      :open="modalOpen"
      :title="mode === 'create' ? 'Tambah Rekening Perusahaan' : 'Edit Rekening Perusahaan'"
      description="Rekening aktif akan muncul di dropdown refund CN dan transaksi kas/bank."
      size="4xl"
      @close="modalOpen = false"
    >
      <section v-if="actionError" class="mb-4 rounded-2xl border border-rose-300/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
        {{ actionError }}
      </section>

      <div class="grid gap-4 md:grid-cols-2">
        <AppSearchSelect
          v-model="form.id_cabang"
          label="Cabang"
          placeholder="Pilih cabang"
          :options="branchOptions"
          :disabled="isFormReadOnly || (!canAccessAllBranches && !!fallbackBranchId)"
        />
        <AppSearchSelect
          v-model="form.id_perusahaan"
          label="Perusahaan"
          placeholder="Pilih perusahaan"
          :options="formCompanyOptions"
          :disabled="isFormReadOnly || !form.id_cabang"
          empty-text="Pilih cabang terlebih dahulu."
        />
        <AppFormField v-model="form.nama_bank" label="Bank / Kas" placeholder="Contoh: BCA, Mandiri, Kas Besar" :readonly="isFormReadOnly" />
        <AppFormField v-model="form.nomor_rekening" label="Nomor Rekening" placeholder="Nomor rekening / kode kas" :readonly="isFormReadOnly" />
        <AppFormField v-model="form.nama_pemilik" label="Nama Pemilik" placeholder="Atas nama rekening" :readonly="isFormReadOnly" />
        <label class="flex min-h-[68px] items-end gap-3 rounded-xl border border-slate-700 px-4 py-3 text-sm font-semibold text-slate-200" :class="isFormReadOnly ? 'cursor-not-allowed opacity-75' : ''">
          <input v-model="form.is_aktif" type="checkbox" class="h-4 w-4 rounded border-slate-500 text-brand-600 focus:ring-brand-500 disabled:cursor-not-allowed" :disabled="isFormReadOnly" />
          Rekening aktif
        </label>
      </div>

      <template #footer>
        <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div class="flex gap-2">
            <button
              v-if="mode === 'edit' && canUpdateAccount"
              class="rounded-xl border border-amber-300/50 px-4 py-3 text-sm font-bold text-amber-200 hover:bg-amber-500/10 disabled:opacity-60"
              :disabled="loading.save"
              @click="toggleActive"
            >
              {{ form.is_aktif ? 'Nonaktifkan' : 'Aktifkan' }}
            </button>
            <button
              v-if="mode === 'edit' && canDeleteAccount"
              class="rounded-xl border border-rose-300/50 px-4 py-3 text-sm font-bold text-rose-200 hover:bg-rose-500/10 disabled:opacity-60"
              :disabled="loading.save"
              @click="remove"
            >
              Hapus
            </button>
          </div>
          <div class="flex justify-end gap-3">
            <button class="rounded-xl border border-slate-700 px-4 py-3 text-sm font-bold" @click="modalOpen = false">Tutup</button>
            <button v-if="canSaveCurrentMode" class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-bold text-white disabled:opacity-60" :disabled="loading.save" @click="save">
              {{ loading.save ? 'Menyimpan...' : mode === 'create' ? 'Simpan Rekening' : 'Perbarui Rekening' }}
            </button>
          </div>
        </div>
      </template>
    </AppModal>
  </div>
</template>
