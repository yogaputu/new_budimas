<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import {
  createCompany,
  deleteCompany,
  getBranches,
  getCompanies,
  getRegionsLevel1,
  getRegionsLevel2,
  getRegionsLevel3,
  getRegionsLevel4,
  replaceCompanyBranches,
  updateCompany
} from '@/api/master';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { useAuthStore } from '@/stores/auth';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const RESOURCE = 'master.branches';

const filters = reactive({ search: '' });
const form = reactive({
  id_cabang: [],
  kode: '',
  nama: '',
  alamat: '',
  telepon: '',
  npwp: '',
  tin: '',
  id_tku: '',
  document_type: 'TIN',
  document_number: '',
  country_code: 'IDN',
  email_pajak: '',
  id_wilayah1: '',
  id_wilayah2: '',
  id_wilayah3: '',
  id_wilayah4: ''
});

const rows = ref([]);
const branches = ref([]);
const wilayah1Rows = ref([]);
const wilayah2Rows = ref([]);
const wilayah3Rows = ref([]);
const wilayah4Rows = ref([]);
const loading = ref(false);
const saving = ref(false);
const optionsLoading = ref(false);
const modalOpen = ref(false);
const mode = ref('create');
const selectedRow = ref(null);
const previousBranchIds = ref([]);
const hydratingForm = ref(false);
const error = ref('');
const actionError = ref('');
const feedback = ref('');

const canCreate = computed(() => authStore.canCreate(RESOURCE));
const canUpdate = computed(() => authStore.canUpdate(RESOURCE));
const canDelete = computed(() => authStore.canDelete(RESOURCE));

const filteredRows = computed(() => {
  const query = filters.search.trim().toLowerCase();
  if (!query) return rows.value;
  return rows.value.filter((item) =>
    [item.kode, item.nama, item.alamat, item.telepon, item.npwp, item.nama_cabang_list, item.kode_cabang_list]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query))
  );
});

const branchOptions = computed(() =>
  branches.value.map((item) => ({
    value: String(item.id),
    label: `${item.kode || '-'} - ${item.nama || item.nama_cabang || 'Cabang'}`
  }))
);

const wilayah1Options = computed(() => buildRegionOptions(wilayah1Rows.value, 'Provinsi'));
const wilayah2Options = computed(() => buildRegionOptions(wilayah2Rows.value, 'Kota/Kabupaten'));
const wilayah3Options = computed(() => buildRegionOptions(wilayah3Rows.value, 'Kecamatan'));
const wilayah4Options = computed(() => buildRegionOptions(wilayah4Rows.value, 'Kelurahan/Desa'));

const columns = [
  { key: 'kode', label: 'Kode Perusahaan' },
  { key: 'nama', label: 'Nama Perusahaan' },
  { key: 'nama_cabang_list', label: 'Cabang Terkait', render: (row) => row.nama_cabang_list || '-' },
  { key: 'alamat', label: 'Alamat' },
  { key: 'telepon', label: 'Telepon' },
  { key: 'npwp', label: 'NPWP' },
  { key: 'tin', label: 'TIN', render: (row) => row.tin || row.npwp || '-' },
  { key: 'id_tku', label: 'IDTKU', render: (row) => row.id_tku || '-' }
];

function buildRegionOptions(items, fallbackLabel) {
  return items.map((item) => ({
    value: String(item.id),
    label: item.nama || `${fallbackLabel} ${item.id}`
  }));
}

function normalizeIds(value) {
  if (Array.isArray(value)) {
    return value.map((item) => String(item || '').trim()).filter(Boolean);
  }

  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function sameIds(left, right) {
  const normalizedLeft = normalizeIds(left).sort();
  const normalizedRight = normalizeIds(right).sort();
  return normalizedLeft.length === normalizedRight.length && normalizedLeft.every((value, index) => value === normalizedRight[index]);
}

function resetForm() {
  Object.assign(form, {
    id_cabang: [],
    kode: '',
    nama: '',
    alamat: '',
    telepon: '',
    npwp: '',
    tin: '',
    id_tku: '',
    document_type: 'TIN',
    document_number: '',
    country_code: 'IDN',
    email_pajak: '',
    id_wilayah1: '',
    id_wilayah2: '',
    id_wilayah3: '',
    id_wilayah4: ''
  });
  previousBranchIds.value = [];
  wilayah2Rows.value = [];
  wilayah3Rows.value = [];
  wilayah4Rows.value = [];
}

function buildPayload() {
  return {
    kode: form.kode,
    nama: form.nama,
    alamat: form.alamat,
    telepon: form.telepon,
    npwp: form.npwp,
    tin: form.tin || form.npwp,
    id_tku: form.id_tku,
    document_type: form.document_type || 'TIN',
    document_number: form.document_number,
    country_code: form.country_code || 'IDN',
    email_pajak: form.email_pajak,
    id_wilayah1: form.id_wilayah1,
    id_wilayah2: form.id_wilayah2,
    id_wilayah3: form.id_wilayah3,
    id_wilayah4: form.id_wilayah4
  };
}

async function loadRows() {
  loading.value = true;
  error.value = '';

  try {
    const response = await getCompanies();
    rows.value = normalizeList(unwrapResponse(response));
  } catch (err) {
    error.value = normalizeError(err, 'Data perusahaan belum bisa dimuat.');
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

async function loadOptions() {
  optionsLoading.value = true;
  try {
    const [branchResponse, wilayah1Response] = await Promise.all([getBranches(), getRegionsLevel1()]);
    branches.value = normalizeList(unwrapResponse(branchResponse));
    wilayah1Rows.value = normalizeList(unwrapResponse(wilayah1Response));
  } catch (err) {
    actionError.value = normalizeError(err, 'Referensi cabang atau wilayah belum bisa dimuat.');
  } finally {
    optionsLoading.value = false;
  }
}

async function loadWilayah2(id, preserveValue = false) {
  if (!id) {
    wilayah2Rows.value = [];
    wilayah3Rows.value = [];
    wilayah4Rows.value = [];
    if (!preserveValue) {
      form.id_wilayah2 = '';
      form.id_wilayah3 = '';
      form.id_wilayah4 = '';
    }
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
    if (!preserveValue) {
      form.id_wilayah3 = '';
      form.id_wilayah4 = '';
    }
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
    if (!preserveValue) form.id_wilayah4 = '';
    return;
  }

  const response = await getRegionsLevel4(id);
  wilayah4Rows.value = normalizeList(unwrapResponse(response));
  if (!preserveValue) form.id_wilayah4 = '';
}

async function hydrateRegions(row) {
  hydratingForm.value = true;
  form.id_wilayah1 = row?.id_wilayah1 ? String(row.id_wilayah1) : '';
  form.id_wilayah2 = row?.id_wilayah2 ? String(row.id_wilayah2) : '';
  form.id_wilayah3 = row?.id_wilayah3 ? String(row.id_wilayah3) : '';
  form.id_wilayah4 = row?.id_wilayah4 ? String(row.id_wilayah4) : '';

  try {
    await loadWilayah2(form.id_wilayah1, true);
    await loadWilayah3(form.id_wilayah2, true);
    await loadWilayah4(form.id_wilayah3, true);
  } finally {
    hydratingForm.value = false;
  }
}

function openCreate() {
  if (!canCreate.value) return;
  mode.value = 'create';
  selectedRow.value = null;
  resetForm();
  feedback.value = '';
  actionError.value = '';
  modalOpen.value = true;
}

async function openEdit(row) {
  if (!canUpdate.value) return;
  mode.value = 'edit';
  selectedRow.value = row;
  const branchIds = normalizeIds(row?.id_cabang_list || row?.cabang_ids || row?.id_cabang);
  previousBranchIds.value = branchIds;
  Object.assign(form, {
    id_cabang: branchIds,
    kode: row?.kode || '',
    nama: row?.nama || '',
    alamat: row?.alamat || '',
    telepon: row?.telepon || '',
    npwp: row?.npwp || '',
    tin: row?.tin || row?.npwp || '',
    id_tku: row?.id_tku || '',
    document_type: row?.document_type || 'TIN',
    document_number: row?.document_number || '',
    country_code: row?.country_code || 'IDN',
    email_pajak: row?.email_pajak || ''
  });
  feedback.value = '';
  actionError.value = '';
  modalOpen.value = true;
  await hydrateRegions(row);
}

async function resolveCreatedCompanyId(response) {
  const returnedRows = normalizeList(unwrapResponse(response));
  const returnedId = returnedRows[0]?.id || returnedRows[0]?.ID;
  if (returnedId) return returnedId;

  await loadRows();
  const matched = rows.value
    .filter((item) => String(item.kode || '') === String(form.kode || '') && String(item.nama || '') === String(form.nama || ''))
    .map((item) => Number(item.id))
    .filter((item) => Number.isFinite(item))
    .sort((a, b) => b - a)[0];
  return matched || '';
}

async function syncCompanyBranches(companyId) {
  if (!companyId) return;

  const selectedIds = normalizeIds(form.id_cabang);
  // Do not send a destructive mapping mutation merely because the company
  // form is saved.  Unchanged pairs can be referenced by audit data and do
  // not need to be recreated.
  if (sameIds(selectedIds, previousBranchIds.value)) return;

  await replaceCompanyBranches(companyId, selectedIds);
  previousBranchIds.value = selectedIds;
}

async function save() {
  if (!form.kode.trim()) {
    actionError.value = 'Kode perusahaan wajib diisi.';
    return;
  }

  if (!form.nama.trim()) {
    actionError.value = 'Nama perusahaan wajib diisi.';
    return;
  }

  if (mode.value === 'create' && !canCreate.value) {
    actionError.value = 'Hak akses Anda tidak memiliki izin tambah perusahaan.';
    return;
  }

  if (mode.value === 'edit' && !canUpdate.value) {
    actionError.value = 'Hak akses Anda tidak memiliki izin ubah perusahaan.';
    return;
  }

  saving.value = true;
  feedback.value = '';
  actionError.value = '';

  try {
    if (mode.value === 'create') {
      const response = await createCompany(buildPayload(), {
        returning: JSON.stringify({ fields: 'id' })
      });
      const companyId = await resolveCreatedCompanyId(response);
      await syncCompanyBranches(companyId);
      feedback.value = 'Perusahaan berhasil ditambahkan.';
      resetForm();
    } else {
      await updateCompany(selectedRow.value?.id, buildPayload());
      await syncCompanyBranches(selectedRow.value?.id);
      feedback.value = 'Perusahaan berhasil diperbarui.';
    }
    await Promise.all([loadRows(), loadOptions()]);
  } catch (err) {
    actionError.value = normalizeError(err, 'Data perusahaan belum berhasil disimpan.');
  } finally {
    saving.value = false;
  }
}

async function remove() {
  if (!selectedRow.value?.id || !canDelete.value) return;
  saving.value = true;
  feedback.value = '';
  actionError.value = '';

  try {
    const companyId = selectedRow.value.id;
    await replaceCompanyBranches(companyId, []);
    await deleteCompany(companyId);
    modalOpen.value = false;
    await Promise.all([loadRows(), loadOptions()]);
  } catch (err) {
    actionError.value = normalizeError(err, 'Data perusahaan belum berhasil dihapus.');
  } finally {
    saving.value = false;
  }
}

watch(
  () => form.id_wilayah1,
  async (value, previousValue) => {
    if (hydratingForm.value || value === previousValue) return;
    await loadWilayah2(value);
  }
);

watch(
  () => form.id_wilayah2,
  async (value, previousValue) => {
    if (hydratingForm.value || value === previousValue) return;
    await loadWilayah3(value);
  }
);

watch(
  () => form.id_wilayah3,
  async (value, previousValue) => {
    if (hydratingForm.value || value === previousValue) return;
    await loadWilayah4(value);
  }
);

onMounted(async () => {
  await Promise.all([loadRows(), loadOptions()]);
});
</script>

<template>
  <div class="space-y-4">
    <PageHeader title="Master Perusahaan" description="Kelola data perusahaan, cabang terkait, alamat, NPWP, dan wilayah operasional.">
      <button
        class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-500"
        :disabled="!canCreate"
        @click="openCreate"
      >
        Tambah Perusahaan
      </button>
    </PageHeader>

    <AppFilterBar
      :model-value="filters"
      :fields="[
        { key: 'search', label: 'Cari perusahaan', placeholder: 'Kode, nama, cabang, alamat, telepon, atau NPWP' }
      ]"
      @update:model-value="Object.assign(filters, $event)"
      @submit="loadRows"
      @reset="filters.search = ''"
    />

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ error }}</section>

    <AppTable
      :rows="filteredRows"
      :columns="columns"
      :loading="loading"
      :clickable-rows="canUpdate"
      empty-message="Belum ada data perusahaan."
      @row-click="openEdit"
    />

    <AppModal :open="modalOpen" :title="mode === 'create' ? 'Tambah Perusahaan' : 'Edit Perusahaan'" panel-class="max-w-5xl" @close="modalOpen = false">
      <div class="space-y-4">
        <div class="grid gap-4 md:grid-cols-2">
          <AppSearchSelect
            v-model="form.id_cabang"
            label="Cabang Terkait"
            placeholder="Pilih cabang"
            :options="branchOptions"
            :loading="optionsLoading"
            multiple
            empty-text="Cabang belum tersedia."
          />
          <AppFormField v-model="form.kode" label="Kode" />
          <AppFormField v-model="form.nama" label="Nama Perusahaan" />
          <AppFormField v-model="form.alamat" label="Alamat" />
          <AppFormField v-model="form.telepon" label="Telepon" />
          <AppFormField v-model="form.npwp" label="NPWP" />
          <AppFormField v-model="form.tin" label="TIN Faktur Pajak" />
          <AppFormField v-model="form.id_tku" label="Seller IDTKU" />
          <AppSearchSelect
            v-model="form.document_type"
            label="Dokumen Pajak"
            placeholder="Pilih dokumen"
            :options="[
              { value: 'TIN', label: 'TIN' },
              { value: 'Other ID', label: 'Other ID' }
            ]"
          />
          <AppFormField v-model="form.document_number" label="Nomor Dokumen" />
          <AppFormField v-model="form.country_code" label="Kode Negara" />
          <AppFormField v-model="form.email_pajak" label="Email Pajak" />
          <AppSearchSelect v-model="form.id_wilayah1" label="Wilayah 1 = Provinsi" placeholder="Pilih provinsi" :options="wilayah1Options" empty-text="Provinsi belum tersedia." />
          <AppSearchSelect v-model="form.id_wilayah2" label="Wilayah 2 = Kota/Kabupaten" placeholder="Pilih kota/kabupaten" :options="wilayah2Options" :disabled="!form.id_wilayah1" empty-text="Pilih provinsi dahulu." />
          <AppSearchSelect v-model="form.id_wilayah3" label="Wilayah 3 = Kecamatan" placeholder="Pilih kecamatan" :options="wilayah3Options" :disabled="!form.id_wilayah2" empty-text="Pilih kota/kabupaten dahulu." />
          <AppSearchSelect v-model="form.id_wilayah4" label="Wilayah 4 = Kelurahan/Desa" placeholder="Pilih kelurahan/desa" :options="wilayah4Options" :disabled="!form.id_wilayah3" empty-text="Pilih kecamatan dahulu." />
        </div>

        <div v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{{ feedback }}</div>
        <div v-if="actionError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ actionError }}</div>

        <div class="flex flex-wrap gap-2">
          <button
            class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
            :disabled="saving || (mode === 'create' ? !canCreate : !canUpdate)"
            @click="save"
          >
            {{ saving ? 'Menyimpan...' : mode === 'create' ? 'Simpan' : 'Update' }}
          </button>
          <button v-if="mode === 'edit'" class="rounded-xl border border-rose-200 px-4 py-2 text-sm font-medium text-rose-700 disabled:opacity-60" :disabled="saving || !canDelete" @click="remove">
            Hapus
          </button>
        </div>
      </div>
    </AppModal>
  </div>
</template>
