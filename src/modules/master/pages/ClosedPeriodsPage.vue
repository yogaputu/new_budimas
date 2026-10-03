<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { createClosedPeriod, deleteClosedPeriod, getBranches, getClosedPeriods, updateClosedPeriod } from '@/api/master';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, isSuperUser, scopeRowsByLoginBranch } from '@/utils/accessScope';
import { useAuthStore } from '@/stores/auth';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const filters = reactive({ search: '', id_cabang: '', status: '' });
const form = reactive({ tanggal_close: '', keterangan: '', id_cabang: '', status: '1' });

const rows = ref([]);
const branches = ref([]);
const loading = ref(false);
const saving = ref(false);
const modalOpen = ref(false);
const mode = ref('create');
const selectedRow = ref(null);
const error = ref('');
const actionError = ref('');
const feedback = ref('');
const loginBranchId = computed(() => getLoginBranchId(authStore.user));
const scopedRows = computed(() => scopeRowsByLoginBranch(rows.value, authStore));
const canAccessAllBranches = computed(() => isSuperUser(authStore));

const branchOptions = computed(() =>
  scopeRowsByLoginBranch(branches.value, authStore).map((item) => ({
    value: String(item.id),
    label: `${item.kode ? `${item.kode} - ` : ''}${item.nama || `Cabang ${item.id}`}`
  }))
);

const filteredRows = computed(() => {
  const query = filters.search.trim().toLowerCase();
  return scopedRows.value.filter((item) => {
    const matchesBranch = !filters.id_cabang || String(item.id_cabang || '') === String(filters.id_cabang);
    const itemStatus = normalizeStatus(item.status);
    const matchesStatus = filters.status === '' || String(itemStatus) === String(filters.status);
    const matchesSearch =
      !query ||
      [item.tanggal_close, item.keterangan, item.nama_cabang]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query));
    return matchesBranch && matchesStatus && matchesSearch;
  });
});

const columns = [
  { key: 'tanggal_close', label: 'Tanggal Close' },
  { key: 'nama_cabang', label: 'Cabang' },
  {
    key: 'status_label',
    label: 'Status',
    render: (row) => ({
      text: normalizeStatus(row.status) === 1 ? 'Aktif' : 'Nonaktif',
      className:
        normalizeStatus(row.status) === 1
          ? 'inline-flex rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-200'
          : 'inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300'
    })
  },
  { key: 'keterangan', label: 'Keterangan' }
];

function normalizeId(value) {
  return value === undefined || value === null || value === '' ? '' : String(value);
}

function normalizeStatus(value) {
  return value === undefined || value === null || value === '' ? 1 : Number(value);
}

function resetForm() {
  Object.assign(form, { tanggal_close: '', keterangan: '', id_cabang: '', status: '1' });
  if (!canAccessAllBranches.value && loginBranchId.value) {
    form.id_cabang = String(loginBranchId.value);
  }
}

function resetFilters() {
  Object.assign(filters, {
    search: '',
    id_cabang: !canAccessAllBranches.value && loginBranchId.value ? String(loginBranchId.value) : '',
    status: ''
  });
}

function buildPayload() {
  const payload = {};
  Object.entries(form).forEach(([key, value]) => {
    if (value !== '') payload[key] = value;
  });
  return payload;
}

async function loadRows() {
  loading.value = true;
  error.value = '';
  try {
    const response = await getClosedPeriods({
      id_cabang: filters.id_cabang || undefined,
      status: filters.status || undefined
    });
    rows.value = normalizeList(unwrapResponse(response));
  } catch (err) {
    error.value = normalizeError(err, 'Data periode close belum bisa dimuat.');
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

async function loadReferences() {
  const response = await getBranches();
  branches.value = normalizeList(unwrapResponse(response));
  if (!canAccessAllBranches.value && loginBranchId.value) {
    filters.id_cabang = String(loginBranchId.value);
    form.id_cabang = String(loginBranchId.value);
  }
}

function openCreate() {
  mode.value = 'create';
  selectedRow.value = null;
  resetForm();
  feedback.value = '';
  actionError.value = '';
  modalOpen.value = true;
}

function openEdit(row) {
  mode.value = 'edit';
  selectedRow.value = row;
  Object.assign(form, {
    tanggal_close: row?.tanggal_close || '',
    keterangan: row?.keterangan || '',
    id_cabang: normalizeId(row?.id_cabang),
    status: normalizeId(row?.status ?? 1)
  });
  feedback.value = '';
  actionError.value = '';
  modalOpen.value = true;
}

async function save() {
  if (!form.tanggal_close) {
    actionError.value = 'Tanggal close wajib diisi.';
    return;
  }

  saving.value = true;
  feedback.value = '';
  actionError.value = '';
  try {
    if (mode.value === 'create') {
      await createClosedPeriod(buildPayload());
      feedback.value = 'Periode close berhasil ditambahkan.';
      resetForm();
    } else {
      await updateClosedPeriod(selectedRow.value?.id_periode, buildPayload());
      feedback.value = 'Periode close berhasil diperbarui.';
    }
    await loadRows();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data periode close belum berhasil disimpan.');
  } finally {
    saving.value = false;
  }
}

async function remove() {
  if (!selectedRow.value?.id_periode) return;
  saving.value = true;
  feedback.value = '';
  actionError.value = '';
  try {
    await deleteClosedPeriod(selectedRow.value.id_periode);
    modalOpen.value = false;
    await loadRows();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data periode close belum berhasil dihapus.');
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  await Promise.all([loadReferences(), loadRows()]);
});

watch(
  () => [filters.id_cabang, filters.status],
  () => {
    loadRows();
  }
);
</script>

<template>
  <div class="space-y-4">
    <PageHeader title="Master Periode Close" description="Penutupan periode sekarang memakai pilihan cabang langsung agar input lebih aman.">
      <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700" @click="openCreate">Tambah Periode</button>
    </PageHeader>

    <section class="panel p-4">
      <div class="grid gap-3 md:grid-cols-[1fr_1fr_1.2fr_auto_auto] md:items-end">
        <AppSearchSelect
          v-model="filters.id_cabang"
          label="Cabang"
          placeholder="Semua cabang"
          :options="branchOptions"
          :disabled="!canAccessAllBranches && !!loginBranchId"
          empty-text="Cabang belum tersedia."
        />
        <label class="block">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Status</span>
          <select v-model="filters.status" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white">
            <option value="">Semua status</option>
            <option value="1">Aktif</option>
            <option value="0">Nonaktif</option>
          </select>
        </label>
        <label class="block">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Cari Periode</span>
          <input v-model="filters.search" type="text" placeholder="Tanggal, keterangan, atau cabang" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
        </label>
        <button class="rounded-xl bg-brand-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-brand-700" @click="loadRows">Terapkan</button>
        <button class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800" @click="resetFilters">Reset</button>
      </div>
    </section>

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ error }}</section>

    <AppTable :rows="filteredRows" :columns="columns" :loading="loading" :clickable-rows="true" empty-message="Belum ada data periode close." @row-click="openEdit" />

    <AppModal :open="modalOpen" :title="mode === 'create' ? 'Tambah Periode Close' : 'Edit Periode Close'" panel-class="max-w-2xl" @close="modalOpen = false">
      <div class="space-y-4">
        <div class="grid gap-4 md:grid-cols-2">
          <AppFormField v-model="form.tanggal_close" label="Tanggal Close" type="date" />
          <AppSearchSelect v-model="form.id_cabang" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="!canAccessAllBranches && !!loginBranchId" empty-text="Cabang belum tersedia." />
        </div>
        <label class="block">
          <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Status</span>
          <select v-model="form.status" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white">
            <option value="1">Aktif</option>
            <option value="0">Nonaktif</option>
          </select>
        </label>
        <AppFormField v-model="form.keterangan" label="Keterangan" />

        <div v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{{ feedback }}</div>
        <div v-if="actionError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ actionError }}</div>

        <div class="flex flex-wrap gap-2">
          <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60" :disabled="saving" @click="save">
            {{ saving ? 'Menyimpan...' : mode === 'create' ? 'Simpan' : 'Update' }}
          </button>
          <button v-if="mode === 'edit'" class="rounded-xl border border-rose-200 px-4 py-2 text-sm font-medium text-rose-700 disabled:opacity-60" :disabled="saving" @click="remove">
            Hapus
          </button>
        </div>
      </div>
    </AppModal>
  </div>
</template>
