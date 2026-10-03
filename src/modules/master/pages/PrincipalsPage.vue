<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import {
  createPrincipal,
  deletePrincipal,
  getBranches,
  getCompanies,
  getPrincipals,
  getRegionsLevel1,
  getRegionsLevel2,
  getRegionsLevel3,
  getRegionsLevel4,
  updatePrincipal
} from '@/api/master';
import { useRemoteCollection } from '@/composables/useRemoteCollection';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getRowBranchIds, getRowCompanyId, getRowCompanyIds, isSuperUser, parseScopeIds, scopeRowsByLoginBranch } from '@/utils/accessScope';
import { useAuthStore } from '@/stores/auth';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const filters = reactive({ search: '', aktif: '' });
const { items, loading, load, error } = useRemoteCollection(() => getPrincipals());
const companies = ref([]);
const branches = ref([]);
const wilayah1Rows = ref([]);
const wilayah2Rows = ref([]);
const wilayah3Rows = ref([]);
const wilayah4Rows = ref([]);
const modalOpen = ref(false);
const mode = ref('create');
const selectedRow = ref(null);
const hydratingForm = ref(false);
const feedback = ref('');
const actionError = ref('');
const saving = ref(false);
const loginBranchId = computed(() => getLoginBranchId(authStore.user));
const loginBranch = computed(() => branches.value.find((item) => String(item.id) === String(loginBranchId.value || '')));
const selectedBranch = computed(() => branches.value.find((item) => String(item.id) === String(form.id_cabang || '')));
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
const scopedBranchCompanyIds = computed(() => {
  if (isSuperUser(authStore) || !loginBranchId.value) return null;
  return companies.value
    .filter((item) => getRowBranchIds(item).includes(String(loginBranchId.value)) || String(item.id) === String(getRowCompanyId(loginBranch.value)))
    .map((item) => String(item.id));
});
const scopedItems = computed(() =>
  items.value.filter((item) => {
    if (isSuperUser(authStore) || !loginBranch.value) return true;
    const rowCompanyIds = getRowCompanyIds(item);
    return rowCompanyIds.some((id) => scopedBranchCompanyIds.value?.includes(String(id)));
  })
);

const form = reactive({
  kode: '',
  nama: '',
  alamat: '',
  telepon: '',
  npwp: '',
  no_rekening: '',
  pic: '',
  id_cabang: '',
  id_perusahaan: '',
  id_perusahaan_list: [],
  id_wilayah1: '',
  id_wilayah2: '',
  id_wilayah3: '',
  id_wilayah4: '',
  aktif: 'true'
});

const companyOptions = computed(() => {
  let rows = companies.value;
  if (!isSuperUser(authStore) && scopedBranchCompanyIds.value?.length) {
    rows = rows.filter((item) => scopedBranchCompanyIds.value.includes(String(item.id)));
  }
  if (form.id_cabang && selectedBranchCompanyIds.value.length) {
    rows = rows.filter((item) => selectedBranchCompanyIds.value.includes(String(item.id)));
  }
  return rows.map((item) => ({
    value: String(item.id),
    label: `${item.kode || '-'} - ${item.nama || 'Perusahaan'}`
  }));
});

const branchOptions = computed(() =>
  scopeRowsByLoginBranch(branches.value, authStore).map((item) => ({
    value: String(item.id),
    label: `${item.kode || '-'} - ${item.nama || item.nama_cabang || 'Cabang'}`
  }))
);

const wilayah1Options = computed(() =>
  wilayah1Rows.value.map((item) => ({
    value: String(item.id),
    label: item.nama || `Wilayah ${item.id}`
  }))
);

const wilayah2Options = computed(() =>
  wilayah2Rows.value.map((item) => ({
    value: String(item.id),
    label: item.nama || `Wilayah ${item.id}`
  }))
);

const wilayah3Options = computed(() =>
  wilayah3Rows.value.map((item) => ({
    value: String(item.id),
    label: item.nama || `Wilayah ${item.id}`
  }))
);

const wilayah4Options = computed(() =>
  wilayah4Rows.value.map((item) => ({
    value: String(item.id),
    label: item.nama || `Wilayah ${item.id}`
  }))
);

const filteredItems = computed(() => {
  const query = filters.search.trim().toLowerCase();
  return scopedItems.value.filter((item) => {
    const statusMatch = !filters.aktif || String(isPrincipalActive(item)) === filters.aktif;
    const queryMatch = !query || [item.nama_principal, item.nama, item.kode, item.nama_perusahaan, item.pic]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query));

    return statusMatch && queryMatch;
  });
});

const columns = [
  { key: 'kode', label: 'Kode' },
  { key: 'nama', label: 'Principal', render: (row) => row.nama_principal || row.nama || '-' },
  { key: 'nama_perusahaan', label: 'Perusahaan Utama' },
  { key: 'nama_perusahaan_list', label: 'Boleh Dipakai', render: (row) => row.nama_perusahaan_list || row.nama_perusahaan || '-' },
  { key: 'pic', label: 'PIC' },
  { key: 'telepon', label: 'Telepon' },
  { key: 'aktif_label', label: 'Status', render: (row) => (isPrincipalActive(row) ? 'Aktif' : 'Nonaktif') }
];

const filterFields = computed(() => [
  { key: 'search', label: 'Cari principal', placeholder: 'Nama, kode, perusahaan, atau PIC' },
  {
    key: 'aktif',
    label: 'Status',
    type: 'select',
    options: [
      { value: 'true', label: 'Aktif' },
      { value: 'false', label: 'Nonaktif' }
    ]
  }
]);

function isPrincipalActive(row) {
  if (row?.aktif === undefined || row?.aktif === null || row?.aktif === '') return true;
  if (typeof row.aktif === 'boolean') return row.aktif;
  return !['false', '0', 'nonaktif', 'inactive'].includes(String(row.aktif).toLowerCase());
}

function resetForm() {
  Object.assign(form, {
    kode: '',
    nama: '',
    alamat: '',
    telepon: '',
    npwp: '',
    no_rekening: '',
    pic: '',
    id_cabang: '',
    id_perusahaan: '',
    id_perusahaan_list: [],
    id_wilayah1: '',
    id_wilayah2: '',
    id_wilayah3: '',
    id_wilayah4: '',
    aktif: 'true'
  });
  wilayah2Rows.value = [];
  wilayah3Rows.value = [];
  wilayah4Rows.value = [];
  if (!isSuperUser(authStore) && loginBranchId.value) {
    form.id_cabang = String(loginBranchId.value);
    syncCompanyFromBranch();
  }
}

function buildPayload() {
  const payload = {};
  const companyIds = new Set(parseScopeIds(form.id_perusahaan_list));
  if (form.id_perusahaan) companyIds.add(String(form.id_perusahaan));

  Object.entries(form).forEach(([key, value]) => {
    if (key === 'id_cabang' || key === 'id_perusahaan_list') return;
    if (value !== '') payload[key] = value;
  });
  payload.id_perusahaan_list = Array.from(companyIds).join(',');
  return payload;
}

async function loadCompanies() {
  const [companiesResponse, branchResponse, wilayah1Response] = await Promise.all([getCompanies(), getBranches(), getRegionsLevel1()]);
  companies.value = normalizeList(unwrapResponse(companiesResponse));
  branches.value = normalizeList(unwrapResponse(branchResponse));
  wilayah1Rows.value = normalizeList(unwrapResponse(wilayah1Response));
  if (!isSuperUser(authStore) && loginBranchId.value) {
    form.id_cabang = String(loginBranchId.value);
    syncCompanyFromBranch();
  }
}

function syncCompanyFromBranch(preserveCurrent = false) {
  if (!form.id_cabang) {
    form.id_perusahaan = '';
    return;
  }

  const allowedCompanyIds = selectedBranchCompanyIds.value;
  if (form.id_cabang && (!preserveCurrent || !allowedCompanyIds.includes(String(form.id_perusahaan || '')))) {
    form.id_perusahaan = '';
  }
  if (form.id_perusahaan && !parseScopeIds(form.id_perusahaan_list).includes(String(form.id_perusahaan))) {
    form.id_perusahaan_list = [...parseScopeIds(form.id_perusahaan_list), String(form.id_perusahaan)];
  }
}

async function loadWilayah2(id, preserveValue = false) {
  if (!id) {
    wilayah2Rows.value = [];
    wilayah3Rows.value = [];
    wilayah4Rows.value = [];
    form.id_wilayah2 = '';
    form.id_wilayah3 = '';
    form.id_wilayah4 = '';
    return;
  }

  const response = await getRegionsLevel2(id);
  wilayah2Rows.value = normalizeList(unwrapResponse(response));
  if (!preserveValue) {
    form.id_wilayah2 = '';
    form.id_wilayah3 = '';
    form.id_wilayah4 = '';
    wilayah3Rows.value = [];
    wilayah4Rows.value = [];
  }
}

async function loadWilayah3(id, preserveValue = false) {
  if (!id) {
    wilayah3Rows.value = [];
    wilayah4Rows.value = [];
    form.id_wilayah3 = '';
    form.id_wilayah4 = '';
    return;
  }

  const response = await getRegionsLevel3(id);
  wilayah3Rows.value = normalizeList(unwrapResponse(response));
  if (!preserveValue) {
    form.id_wilayah3 = '';
    form.id_wilayah4 = '';
    wilayah4Rows.value = [];
  }
}

async function loadWilayah4(id, preserveValue = false) {
  if (!id) {
    wilayah4Rows.value = [];
    form.id_wilayah4 = '';
    return;
  }

  const response = await getRegionsLevel4(id);
  wilayah4Rows.value = normalizeList(unwrapResponse(response));
  if (!preserveValue) {
    form.id_wilayah4 = '';
  }
}

watch(
  () => form.id_wilayah1,
  async (value, previousValue) => {
    if (hydratingForm.value) return;
    if (value !== previousValue) {
      await loadWilayah2(value);
    }
  }
);

watch(
  () => form.id_wilayah2,
  async (value, previousValue) => {
    if (hydratingForm.value) return;
    if (value !== previousValue) {
      await loadWilayah3(value);
    }
  }
);

watch(
  () => form.id_wilayah3,
  async (value, previousValue) => {
    if (hydratingForm.value) return;
    if (value !== previousValue) {
      await loadWilayah4(value);
    }
  }
);

function submit() {
  load();
}

function reset() {
  filters.search = '';
  filters.aktif = '';
}

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
      kode: row?.kode || '',
      nama: row?.nama || row?.nama_principal || '',
      alamat: row?.alamat || '',
      telepon: row?.telepon || '',
      npwp: row?.npwp || '',
      no_rekening: row?.no_rekening || '',
      pic: row?.pic || '',
      id_perusahaan: row?.id_perusahaan ? String(row.id_perusahaan) : '',
      id_perusahaan_list: parseScopeIds(row?.id_perusahaan_list || row?.id_perusahaan),
      id_cabang: '',
      id_wilayah1: row?.id_wilayah1 ? String(row.id_wilayah1) : '',
      id_wilayah2: row?.id_wilayah2 ? String(row.id_wilayah2) : '',
      id_wilayah3: row?.id_wilayah3 ? String(row.id_wilayah3) : '',
      id_wilayah4: row?.id_wilayah4 ? String(row.id_wilayah4) : '',
      aktif: String(isPrincipalActive(row))
    });
    const relatedBranch = branches.value.find((branch) => {
      if (String(getRowCompanyId(branch) || '') === String(form.id_perusahaan || '')) return true;
      const company = companies.value.find((item) => String(item.id) === String(form.id_perusahaan || ''));
      return getRowBranchIds(company).includes(String(branch.id));
    });
    form.id_cabang = relatedBranch?.id ? String(relatedBranch.id) : (!isSuperUser(authStore) && loginBranchId.value ? String(loginBranchId.value) : '');
    syncCompanyFromBranch(true);
    await loadWilayah2(form.id_wilayah1, true);
    await loadWilayah3(form.id_wilayah2, true);
    await loadWilayah4(form.id_wilayah3, true);
  } finally {
    hydratingForm.value = false;
  }
  feedback.value = '';
  actionError.value = '';
  modalOpen.value = true;
}

function closeModal() {
  modalOpen.value = false;
}

async function save() {
  if (!form.nama.trim()) {
    actionError.value = 'Nama principal wajib diisi.';
    return;
  }

  saving.value = true;
  feedback.value = '';
  actionError.value = '';
  try {
    if (mode.value === 'create') {
      await createPrincipal(buildPayload());
      feedback.value = 'Principal berhasil ditambahkan.';
      resetForm();
    } else {
      await updatePrincipal(selectedRow.value?.id, buildPayload());
      feedback.value = 'Principal berhasil diperbarui.';
    }
    await load();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data principal belum berhasil disimpan.');
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
    await deletePrincipal(selectedRow.value.id);
    modalOpen.value = false;
    await load();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data principal belum berhasil dihapus.');
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  await Promise.all([submit(), loadCompanies()]);
});

watch(
  () => form.id_cabang,
  () => {
    if (hydratingForm.value) return;
    syncCompanyFromBranch();
  }
);

watch(
  () => form.id_perusahaan,
  (value) => {
    if (value && !parseScopeIds(form.id_perusahaan_list).includes(String(value))) {
      form.id_perusahaan_list = [...parseScopeIds(form.id_perusahaan_list), String(value)];
    }
  }
);
</script>

<template>
  <div class="space-y-4">
    <PageHeader title="Master Principal" description="Principal sekarang naik ke CRUD operasional yang lebih matang, termasuk selector wilayah bertingkat agar input tidak lagi memakai ID mentah.">
      <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700" @click="openCreate">
        Tambah Principal
      </button>
    </PageHeader>

    <AppFilterBar
      :model-value="filters"
      :fields="filterFields"
      @update:model-value="Object.assign(filters, $event)"
      @submit="submit"
      @reset="reset"
    />

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ error }}</section>

    <AppTable :rows="filteredItems" :columns="columns" :loading="loading" :clickable-rows="true" empty-message="Belum ada principal yang bisa ditampilkan." @row-click="openEdit" />

    <AppModal :open="modalOpen" :title="mode === 'create' ? 'Tambah Principal' : 'Edit Principal'" panel-class="max-w-4xl" @close="closeModal">
      <div class="space-y-4">
        <div class="grid gap-4 md:grid-cols-2">
          <AppFormField v-model="form.kode" label="Kode Principal" />
          <AppFormField v-model="form.nama" label="Nama Principal" />
          <AppFormField v-model="form.alamat" label="Alamat" />
          <AppFormField v-model="form.telepon" label="Telepon" />
          <AppFormField v-model="form.npwp" label="NPWP" />
          <AppFormField v-model="form.no_rekening" label="No Rekening" />
          <AppFormField v-model="form.pic" label="PIC" />
          <label class="block">
            <span class="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">Status</span>
            <select
              v-model="form.aktif"
              class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none transition focus:border-brand-400 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            >
              <option value="true">Aktif</option>
              <option value="false">Nonaktif</option>
            </select>
          </label>
          <AppSearchSelect v-model="form.id_cabang" label="Cabang Acuan" placeholder="Opsional untuk membatasi perusahaan" :options="branchOptions" :disabled="!isSuperUser(authStore) && !!loginBranchId" empty-text="Cabang belum tersedia." />
          <AppSearchSelect v-model="form.id_perusahaan" label="Perusahaan Utama" placeholder="Pilih perusahaan utama" :options="companyOptions" empty-text="Perusahaan belum tersedia." />
          <AppSearchSelect v-model="form.id_perusahaan_list" label="Boleh Dipakai Perusahaan" placeholder="Pilih perusahaan pemakai" :options="companyOptions" multiple empty-text="Perusahaan belum tersedia." />
          <AppSearchSelect v-model="form.id_wilayah1" label="Wilayah 1 = Provinsi" placeholder="Pilih provinsi" :options="wilayah1Options" empty-text="Provinsi belum tersedia." />
          <AppSearchSelect v-model="form.id_wilayah2" label="Wilayah 2 = Kota/Kabupaten" placeholder="Pilih kota/kabupaten" :options="wilayah2Options" empty-text="Pilih provinsi dahulu." />
          <AppSearchSelect v-model="form.id_wilayah3" label="Wilayah 3 = Kecamatan" placeholder="Pilih kecamatan" :options="wilayah3Options" empty-text="Pilih kota/kabupaten dahulu." />
          <AppSearchSelect v-model="form.id_wilayah4" label="Wilayah 4 = Kelurahan/Desa" placeholder="Pilih kelurahan/desa" :options="wilayah4Options" empty-text="Pilih kecamatan dahulu." />
        </div>

        <div v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{{ feedback }}</div>
        <div v-if="actionError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ actionError }}</div>

        <div class="flex flex-wrap gap-2">
          <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white" :disabled="saving" @click="save">
            {{ saving ? 'Menyimpan...' : mode === 'create' ? 'Simpan' : 'Update' }}
          </button>
          <button v-if="mode === 'edit'" class="rounded-xl border border-rose-200 px-4 py-2 text-sm font-medium text-rose-700" :disabled="saving" @click="remove">
            Hapus
          </button>
        </div>
      </div>
    </AppModal>
  </div>
</template>
