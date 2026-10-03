<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import {
  createHelper,
  deleteHelper,
  getBranches,
  getCompanies,
  getHelpers,
  getHelperUsers,
  getRegionsLevel1,
  getRegionsLevel2,
  updateHelper
} from '@/api/master';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { branchMatchesCompany, getLoginBranchId, getLoginCompanyId, getRowBranchIds, getRowCompanyIds, isSuperUser, scopeRowsByLoginBranch } from '@/utils/accessScope';
import { useAuthStore } from '@/stores/auth';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const filters = reactive({ search: '', id_perusahaan: '', id_cabang: '' });
const form = reactive({
  id_perusahaan: '',
  id_cabang: '',
  id_user: '',
  id_wilayah1: '',
  id_wilayah2: ''
});

const rows = ref([]);
const users = ref([]);
const branches = ref([]);
const companies = ref([]);
const wilayah1Rows = ref([]);
const wilayah2Rows = ref([]);
const loading = ref(false);
const saving = ref(false);
const modalOpen = ref(false);
const mode = ref('create');
const selectedRow = ref(null);
const hydratingForm = ref(false);
const error = ref('');
const actionError = ref('');
const feedback = ref('');
const loginBranchId = computed(() => getLoginBranchId(authStore.user));
const loginCompanyId = computed(() => getLoginCompanyId(authStore.user));
const scopedRows = computed(() => scopeRowsByLoginBranch(rows.value, authStore));
const scopedBranches = computed(() => scopeRowsByLoginBranch(branches.value, authStore));
const scopedCompanies = computed(() => {
  if (isSuperUser(authStore)) return companies.value;

  const companyIds = new Set(scopedBranches.value.flatMap((branch) => getRowCompanyIds(branch)).map(String));
  if (!companyIds.size && loginCompanyId.value) companyIds.add(String(loginCompanyId.value));
  if (!companyIds.size) return companies.value;

  return companies.value.filter((company) => companyIds.has(String(company.id)));
});

const selectedFilterBranch = computed(() => branches.value.find((item) => String(item.id) === String(filters.id_cabang || '')));
const selectedFormUser = computed(() => users.value.find((item) => String(item.id) === String(form.id_user || '')));
const selectedFormBranch = computed(() => branches.value.find((item) => String(item.id) === String(form.id_cabang || '')));

function buildCompanyOptions(items) {
  return items.map((item) => ({
    value: String(item.id),
    label: `${item.kode || '-'} - ${item.nama || item.nama_perusahaan || 'Perusahaan'}`
  }));
}

function buildBranchOptions(items, companyId) {
  return items
    .filter((item) => branchMatchesCompany(item, companyId))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || '-'} - ${item.nama || item.nama_cabang || 'Cabang'}`
    }));
}

const companyOptions = computed(() => buildCompanyOptions(scopedCompanies.value));
const filterBranchOptions = computed(() => buildBranchOptions(scopedBranches.value, filters.id_perusahaan));
const formBranchOptions = computed(() => buildBranchOptions(scopedBranches.value, form.id_perusahaan));

const filterFields = computed(() => [
  { key: 'search', label: 'Cari helper', placeholder: 'Nama, email, telepon, cabang, perusahaan, wilayah' },
  { key: 'id_perusahaan', label: 'Perusahaan', type: 'search-select', placeholder: 'Semua perusahaan', options: companyOptions.value },
  {
    key: 'id_cabang',
    label: 'Cabang',
    type: 'search-select',
    placeholder: filters.id_perusahaan ? 'Semua cabang perusahaan' : 'Semua cabang',
    options: filterBranchOptions.value,
    emptyText: filters.id_perusahaan ? 'Cabang perusahaan ini belum tersedia.' : 'Cabang belum tersedia.'
  }
]);

const userOptions = computed(() =>
  scopeRowsByLoginBranch(users.value, authStore)
    .filter((item) => rowMatchesCompanyBranch(item, form.id_perusahaan, form.id_cabang))
    .map((item) => ({
      value: String(item.id),
      label: [item.nama, item.email || item.nik || item.username, item.nama_cabang, item.user_jabatan_nama].filter(Boolean).join(' - ') || `User ${item.id}`
    }))
);

const wilayah1Options = computed(() => wilayah1Rows.value.map((item) => ({ value: String(item.id), label: item.nama || `Wilayah ${item.id}` })));
const wilayah2Options = computed(() => wilayah2Rows.value.map((item) => ({ value: String(item.id), label: item.nama || `Wilayah ${item.id}` })));

const filteredRows = computed(() => {
  const keyword = filters.search.trim().toLowerCase();
  const scoped = scopedRows.value.filter((item) => rowMatchesCompanyBranch(item, filters.id_perusahaan, filters.id_cabang));
  if (!keyword) return scoped;
  return scoped.filter((item) =>
    [item.nama, item.email, item.telepon, item.nama_perusahaan, item.nama_cabang, item.nama_wilayah1, item.nama_wilayah2]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(keyword))
  );
});

const columns = [
  { key: 'nama', label: 'Helper / Kernet' },
  { key: 'email', label: 'Email' },
  { key: 'telepon', label: 'Telepon' },
  { key: 'nama_perusahaan', label: 'Perusahaan', render: (row) => row.nama_perusahaan || '-' },
  { key: 'nama_cabang', label: 'Cabang' },
  { key: 'nama_wilayah1', label: 'Provinsi' },
  { key: 'nama_wilayah2', label: 'Kota/Kabupaten' }
];

function getBranchById(branchId) {
  return branches.value.find((item) => String(item.id) === String(branchId || ''));
}

function rowCompanyIds(row) {
  const ids = new Set(getRowCompanyIds(row).map(String));
  getRowBranchIds(row).forEach((branchId) => {
    getRowCompanyIds(getBranchById(branchId)).forEach((companyId) => ids.add(String(companyId)));
  });
  return Array.from(ids);
}

function rowMatchesCompanyBranch(row, companyId, branchId) {
  const rowBranchIds = getRowBranchIds(row);
  const matchesBranch = !branchId || rowBranchIds.includes(String(branchId));
  const matchesCompany = !companyId || rowCompanyIds(row).includes(String(companyId));
  return matchesCompany && matchesBranch;
}

function normalizeId(value) {
  return value === undefined || value === null || value === '' ? '' : String(value);
}

function resetForm() {
  Object.assign(form, {
    id_perusahaan: '',
    id_cabang: '',
    id_user: '',
    id_wilayah1: '',
    id_wilayah2: ''
  });
  if (!isSuperUser(authStore)) {
    form.id_perusahaan = loginCompanyId.value ? String(loginCompanyId.value) : '';
    form.id_cabang = loginBranchId.value ? String(loginBranchId.value) : '';
  }
  wilayah2Rows.value = [];
}

function buildPayload() {
  const payload = {};
  Object.entries(form).forEach(([key, value]) => {
    if (['id_perusahaan', 'id_cabang'].includes(key)) return;
    if (value !== '') payload[key] = value;
  });
  return payload;
}

async function loadRows() {
  loading.value = true;
  error.value = '';
  try {
    const response = await getHelpers();
    rows.value = normalizeList(unwrapResponse(response));
  } catch (err) {
    error.value = normalizeError(err, 'Data helper belum bisa dimuat.');
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

async function loadReferences() {
  const [userResponse, branchResponse, companyResponse, wilayah1Response] = await Promise.all([
    getHelperUsers(),
    getBranches(),
    getCompanies(),
    getRegionsLevel1()
  ]);
  users.value = normalizeList(unwrapResponse(userResponse));
  branches.value = normalizeList(unwrapResponse(branchResponse));
  companies.value = normalizeList(unwrapResponse(companyResponse));
  wilayah1Rows.value = normalizeList(unwrapResponse(wilayah1Response));
}

async function loadWilayah2(id, preserveValue = false) {
  if (!id) {
    wilayah2Rows.value = [];
    form.id_wilayah2 = '';
    return;
  }
  const response = await getRegionsLevel2(id);
  wilayah2Rows.value = normalizeList(unwrapResponse(response));
  if (!preserveValue) form.id_wilayah2 = '';
}

watch(() => form.id_wilayah1, async (value, oldValue) => {
  if (hydratingForm.value) return;
  if (value !== oldValue) await loadWilayah2(value);
});

watch(
  () => filters.id_perusahaan,
  () => {
    if (filters.id_cabang && selectedFilterBranch.value && !branchMatchesCompany(selectedFilterBranch.value, filters.id_perusahaan)) {
      filters.id_cabang = '';
    }
  }
);

watch(
  () => [form.id_perusahaan, form.id_cabang],
  () => {
    if (hydratingForm.value) return;
    if (form.id_cabang && selectedFormBranch.value && !branchMatchesCompany(selectedFormBranch.value, form.id_perusahaan)) {
      form.id_cabang = '';
    }
    if (form.id_user && selectedFormUser.value && !rowMatchesCompanyBranch(selectedFormUser.value, form.id_perusahaan, form.id_cabang)) {
      form.id_user = '';
    }
  }
);

watch(
  () => form.id_user,
  (value) => {
    if (hydratingForm.value || !value) return;
    const user = selectedFormUser.value;
    if (!user) return;
    form.id_cabang = normalizeId(user.id_cabang || form.id_cabang);
    form.id_perusahaan = normalizeId(user.id_perusahaan || form.id_perusahaan);
  }
);

function openCreate() {
  mode.value = 'create';
  selectedRow.value = null;
  resetForm();
  feedback.value = '';
  actionError.value = '';
  modalOpen.value = true;
}

async function openEdit(row) {
  mode.value = 'edit';
  selectedRow.value = row;
  hydratingForm.value = true;
  try {
    Object.assign(form, {
      id_perusahaan: normalizeId(row?.id_perusahaan),
      id_cabang: normalizeId(row?.id_cabang),
      id_user: normalizeId(row?.id_user),
      id_wilayah1: normalizeId(row?.id_wilayah1),
      id_wilayah2: normalizeId(row?.id_wilayah2)
    });
    await loadWilayah2(form.id_wilayah1, true);
  } finally {
    hydratingForm.value = false;
  }
  feedback.value = '';
  actionError.value = '';
  modalOpen.value = true;
}

async function save() {
  if (!form.id_user) {
    actionError.value = 'User helper wajib dipilih.';
    return;
  }

  saving.value = true;
  feedback.value = '';
  actionError.value = '';
  try {
    if (mode.value === 'create') {
      await createHelper(buildPayload());
      feedback.value = 'Helper berhasil ditambahkan.';
      resetForm();
    } else {
      await updateHelper(selectedRow.value?.id, buildPayload());
      feedback.value = 'Helper berhasil diperbarui.';
    }
    await loadRows();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data helper belum berhasil disimpan.');
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
    await deleteHelper(selectedRow.value.id);
    modalOpen.value = false;
    await loadRows();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data helper belum berhasil dihapus.');
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  await Promise.all([loadReferences(), loadRows()]);
});
</script>

<template>
  <div class="space-y-4">
    <PageHeader title="Master Helper / Kernet" description="Daftar helper operasional untuk pendamping armada saat jadwal kirim dan picking.">
      <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700" @click="openCreate">
        Tambah Helper
      </button>
    </PageHeader>

    <AppFilterBar
      :model-value="filters"
      :fields="filterFields"
      @update:model-value="Object.assign(filters, $event)"
      @submit="loadRows"
      @reset="Object.assign(filters, { search: '', id_perusahaan: '', id_cabang: '' })"
    />

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ error }}</section>

    <AppTable :rows="filteredRows" :columns="columns" :loading="loading" :clickable-rows="true" empty-message="Belum ada data helper." @row-click="openEdit" />

    <AppModal :open="modalOpen" :title="mode === 'create' ? 'Tambah Helper' : 'Edit Helper'" panel-class="max-w-3xl" @close="modalOpen = false">
      <div class="space-y-4">
        <div class="grid gap-4 md:grid-cols-2">
          <AppSearchSelect v-model="form.id_perusahaan" label="Perusahaan" placeholder="Pilih perusahaan" :options="companyOptions" empty-text="Perusahaan belum tersedia." />
          <AppSearchSelect v-model="form.id_cabang" label="Cabang" :placeholder="form.id_perusahaan ? 'Pilih cabang perusahaan' : 'Pilih cabang'" :options="formBranchOptions" empty-text="Cabang belum tersedia." />
          <AppSearchSelect v-model="form.id_user" label="User Helper / Kernet" placeholder="Pilih user" :options="userOptions" empty-text="User helper belum tersedia." />
          <AppSearchSelect v-model="form.id_wilayah1" label="Wilayah 1 = Provinsi" placeholder="Pilih provinsi" :options="wilayah1Options" />
          <AppSearchSelect v-model="form.id_wilayah2" label="Wilayah 2 = Kota/Kabupaten" placeholder="Pilih kota/kabupaten" :options="wilayah2Options" empty-text="Pilih provinsi dahulu." />
        </div>

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
