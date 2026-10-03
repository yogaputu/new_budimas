<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { createRoute, deleteRoute, getBranches, getCompanies, getRoutes, updateRoute } from '@/api/master';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getRowBranchIds, getRowCompanyId, isSuperUser, scopeRowsByLoginBranch } from '@/utils/accessScope';
import { useAuthStore } from '@/stores/auth';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const filters = reactive({ search: '' });
const form = reactive({ kode: '', nama_rute: '', deskripsi: '', id_cabang: '', id_perusahaan: '', prioritas: '' });

const rows = ref([]);
const branches = ref([]);
const companies = ref([]);
const loading = ref(false);
const saving = ref(false);
const modalOpen = ref(false);
const mode = ref('create');
const selectedRow = ref(null);
const error = ref('');
const actionError = ref('');
const feedback = ref('');
const loginBranchId = computed(() => getLoginBranchId(authStore.user));
const selectedBranch = computed(() => branches.value.find((item) => String(item.id) === String(form.id_cabang || '')));
const scopedRows = computed(() => scopeRowsByLoginBranch(rows.value, authStore));
const selectedBranchCompanyIds = computed(() => {
  if (!form.id_cabang) return [];
  const ids = new Set();
  const branchCompanyId = getRowCompanyId(selectedBranch.value);

  if (branchCompanyId) ids.add(String(branchCompanyId));

  companies.value.forEach((item) => {
    if (getRowBranchIds(item).includes(String(form.id_cabang))) {
      ids.add(String(item.id));
    }
  });

  return Array.from(ids);
});

const branchOptions = computed(() =>
  scopeRowsByLoginBranch(branches.value, authStore).map((item) => ({
    value: String(item.id),
    label: `${item.kode ? `${item.kode} - ` : ''}${item.nama || `Cabang ${item.id}`}`
  }))
);

const companyOptions = computed(() =>
  companies.value
    .filter((item) => form.id_cabang && selectedBranchCompanyIds.value.includes(String(item.id)))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || '-'} - ${item.nama || 'Perusahaan'}`
    }))
);

const filteredRows = computed(() => {
  const query = filters.search.trim().toLowerCase();
  if (!query) return scopedRows.value;
  return scopedRows.value.filter((item) =>
    [item.kode, item.nama_rute, item.deskripsi, item.nama_cabang]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query))
  );
});

const columns = [
  { key: 'kode', label: 'Kode' },
  { key: 'nama_rute', label: 'Nama Rute' },
  { key: 'nama_cabang', label: 'Cabang' },
  { key: 'prioritas', label: 'Prioritas' },
  { key: 'deskripsi', label: 'Deskripsi' }
];

function normalizeId(value) {
  return value === undefined || value === null || value === '' ? '' : String(value);
}

function resetForm() {
  Object.assign(form, { kode: '', nama_rute: '', deskripsi: '', id_cabang: '', id_perusahaan: '', prioritas: '' });
  if (!isSuperUser(authStore) && loginBranchId.value) {
    form.id_cabang = String(loginBranchId.value);
  }
  syncCompanyFromBranch();
}

function buildPayload() {
  const payload = {};
  Object.entries(form).forEach(([key, value]) => {
    if (key === 'id_perusahaan') return;
    if (value !== '') payload[key] = value;
  });
  return payload;
}

function syncCompanyFromBranch(preserveCurrent = false) {
  if (!form.id_cabang) {
    form.id_perusahaan = '';
    return;
  }

  const allowedCompanyIds = selectedBranchCompanyIds.value;
  if (!preserveCurrent || !allowedCompanyIds.includes(String(form.id_perusahaan || ''))) {
    form.id_perusahaan = '';
  }
}

async function loadRows() {
  loading.value = true;
  error.value = '';
  try {
    const response = await getRoutes();
    rows.value = normalizeList(unwrapResponse(response));
  } catch (err) {
    error.value = normalizeError(err, 'Data rute belum bisa dimuat.');
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

async function loadReferences() {
  const [branchResponse, companyResponse] = await Promise.all([getBranches(), getCompanies()]);
  branches.value = normalizeList(unwrapResponse(branchResponse));
  companies.value = normalizeList(unwrapResponse(companyResponse));
  if (!isSuperUser(authStore) && loginBranchId.value) {
    form.id_cabang = String(loginBranchId.value);
    syncCompanyFromBranch();
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
    kode: row?.kode || '',
    nama_rute: row?.nama_rute || '',
    deskripsi: row?.deskripsi || '',
    id_cabang: normalizeId(row?.id_cabang),
    id_perusahaan: '',
    prioritas: row?.prioritas ?? ''
  });
  syncCompanyFromBranch(true);
  feedback.value = '';
  actionError.value = '';
  modalOpen.value = true;
}

async function save() {
  if (!form.nama_rute.trim()) {
    actionError.value = 'Nama rute wajib diisi.';
    return;
  }

  saving.value = true;
  feedback.value = '';
  actionError.value = '';
  try {
    if (mode.value === 'create') {
      await createRoute(buildPayload());
      feedback.value = 'Rute berhasil ditambahkan.';
      resetForm();
    } else {
      await updateRoute(selectedRow.value?.id, buildPayload());
      feedback.value = 'Rute berhasil diperbarui.';
    }
    await loadRows();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data rute belum berhasil disimpan.');
  } finally {
    saving.value = false;
  }
}

async function remove() {
  if (!selectedRow.value?.id) return;
  saving.value = true;
  feedback.value = '';
  actionError.value = '';
  try {
    await deleteRoute(selectedRow.value.id);
    modalOpen.value = false;
    await loadRows();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data rute belum berhasil dihapus.');
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  await Promise.all([loadReferences(), loadRows()]);
});

watch(
  () => form.id_cabang,
  () => {
    syncCompanyFromBranch();
  }
);
</script>

<template>
  <div class="space-y-4">
    <PageHeader title="Master Rute" description="Rute distribusi sekarang bisa memilih cabang langsung tanpa input ID manual.">
      <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700" @click="openCreate">Tambah Rute</button>
    </PageHeader>

    <AppFilterBar :model-value="filters" :fields="[{ key: 'search', label: 'Cari rute', placeholder: 'Kode, nama rute, deskripsi, cabang' }]" @update:model-value="Object.assign(filters, $event)" @submit="loadRows" @reset="filters.search = ''" />

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ error }}</section>

    <AppTable :rows="filteredRows" :columns="columns" :loading="loading" :clickable-rows="true" empty-message="Belum ada data rute." @row-click="openEdit" />

    <AppModal :open="modalOpen" :title="mode === 'create' ? 'Tambah Rute' : 'Edit Rute'" panel-class="max-w-2xl" @close="modalOpen = false">
      <div class="space-y-4">
        <div class="grid gap-4 md:grid-cols-2">
          <AppFormField v-model="form.kode" label="Kode Rute" />
          <AppFormField v-model="form.nama_rute" label="Nama Rute" />
          <AppSearchSelect v-model="form.id_cabang" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="!isSuperUser(authStore) && !!loginBranchId" empty-text="Cabang belum tersedia." />
          <AppSearchSelect v-model="form.id_perusahaan" label="Perusahaan" :placeholder="form.id_cabang ? 'Pilih perusahaan' : 'Pilih cabang dulu'" :options="companyOptions" :disabled="!form.id_cabang" empty-text="Perusahaan belum tersedia." />
          <AppFormField v-model="form.prioritas" label="Prioritas" type="number" />
        </div>
        <AppFormField v-model="form.deskripsi" label="Deskripsi" />

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
