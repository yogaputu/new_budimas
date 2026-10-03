<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import {
  createFleet,
  deleteFleet,
  getBranches,
  getCompanies,
  getFleets,
  getFleetTypes,
  updateFleet
} from '@/api/master';
import { getFixedAssets } from '@/api/finance';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getRowBranchIds, getRowCompanyId, isSuperUser, parseScopeIds, scopeRowsByLoginBranch } from '@/utils/accessScope';
import { useAuthStore } from '@/stores/auth';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const filters = reactive({ search: '' });
const form = reactive({
  kode: '',
  nama: '',
  no_pelat: '',
  merek: '',
  varian: '',
  tahun_pembuatan: '',
  warna: '',
  nomor_rangka: '',
  nomor_mesin: '',
  kepemilikan: 'PERUSAHAAN',
  status_operasional: 'AVAILABLE',
  id_cabang: '',
  id_perusahaan: '',
  id_perusahaan_list: [],
  id_tipe: '',
  kubikasi: '',
  kapasitas_kg: '',
  kapasitas_pallet: '',
  tanggal_stnk: '',
  tanggal_uji: '',
  tanggal_asuransi: '',
  gps_device_code: '',
  id_inventaris: '',
  id_status: '1',
  keterangan: ''
});

const rows = ref([]);
const branches = ref([]);
const companies = ref([]);
const fleetTypes = ref([]);
const assets = ref([]);
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

const availableCompanyOptions = computed(() =>
  companies.value.map((item) => ({
    value: String(item.id),
    label: `${item.kode || '-'} - ${item.nama || 'Perusahaan'}`
  }))
);

const fleetTypeOptions = computed(() =>
  fleetTypes.value.map((item) => ({
    value: String(item.id),
    label: item.nama || item.tipe || `Tipe ${item.id}`
  }))
);

const assetOptions = computed(() =>
  assets.value
    .filter((item) => {
      if (form.id_cabang && String(item.id_cabang || '') !== String(form.id_cabang)) return false;
      if (form.id_perusahaan && String(item.id_perusahaan || '') !== String(form.id_perusahaan)) return false;
      return true;
    })
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode_asset || `INV-${item.id}`} - ${item.nama_asset || 'Inventaris'}`
    }))
);

const statusOptions = [
  { value: '1', label: 'Aktif' },
  { value: '0', label: 'Nonaktif' }
];

const ownershipOptions = [
  { value: 'PERUSAHAAN', label: 'Milik Perusahaan' },
  { value: 'SEWA', label: 'Sewa' },
  { value: 'MITRA', label: 'Mitra' }
];

const operationalStatusOptions = [
  { value: 'AVAILABLE', label: 'Siap Digunakan' },
  { value: 'ON_TRIP', label: 'Sedang Perjalanan' },
  { value: 'SERVICE', label: 'Servis' },
  { value: 'REPAIR', label: 'Perbaikan' },
  { value: 'INACTIVE', label: 'Tidak Aktif' }
];

const filteredRows = computed(() => {
  const keyword = filters.search.trim().toLowerCase();
  if (!keyword) return scopedRows.value;
  return scopedRows.value.filter((item) =>
    [item.kode, item.nama, item.no_pelat, item.merek, item.varian, item.nama_cabang, item.tipe, item.gps_device_code, item.keterangan]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(keyword))
  );
});

const columns = [
  { key: 'kode', label: 'Kode' },
  { key: 'nama', label: 'Armada' },
  { key: 'no_pelat', label: 'No Pelat' },
  { key: 'nama_cabang', label: 'Cabang' },
  { key: 'nama_perusahaan', label: 'Perusahaan Utama' },
  { key: 'nama_perusahaan_list', label: 'Boleh Dipakai', render: (row) => row.nama_perusahaan_list || row.nama_perusahaan || '-' },
  { key: 'tipe', label: 'Tipe' },
  { key: 'status_operasional', label: 'Operasional', render: (row) => operationalStatusOptions.find((item) => item.value === row.status_operasional)?.label || row.status_operasional || '-' },
  { key: 'kapasitas_kg', label: 'Kap. Kg', render: (row) => row.kapasitas_kg ? Number(row.kapasitas_kg).toLocaleString('id-ID') : '-' },
  { key: 'kapasitas_pallet', label: 'Pallet', render: (row) => row.kapasitas_pallet || '-' },
  { key: 'gps_device_code', label: 'GPS', render: (row) => row.gps_device_code || '-' },
  { key: 'tanggal_stnk', label: 'STNK' },
  { key: 'tanggal_uji', label: 'KIR / Uji' }
];

function normalizeId(value) {
  return value === undefined || value === null || value === '' ? '' : String(value);
}

function normalizeIds(value) {
  return parseScopeIds(value);
}

function resetForm() {
  Object.assign(form, {
    kode: '',
    nama: '',
    no_pelat: '',
    merek: '',
    varian: '',
    tahun_pembuatan: '',
    warna: '',
    nomor_rangka: '',
    nomor_mesin: '',
    kepemilikan: 'PERUSAHAAN',
    status_operasional: 'AVAILABLE',
    id_cabang: '',
    id_perusahaan: '',
    id_perusahaan_list: [],
    id_tipe: '',
    kubikasi: '',
    kapasitas_kg: '',
    kapasitas_pallet: '',
    tanggal_stnk: '',
    tanggal_uji: '',
    tanggal_asuransi: '',
    gps_device_code: '',
    id_inventaris: '',
    id_status: '1',
    keterangan: ''
  });
  if (!isSuperUser(authStore) && loginBranchId.value) {
    form.id_cabang = String(loginBranchId.value);
  }
  syncCompanyFromBranch();
}

function buildPayload() {
  const payload = {};
  const companyIds = new Set(normalizeIds(form.id_perusahaan_list));
  if (form.id_perusahaan) companyIds.add(String(form.id_perusahaan));

  Object.entries(form).forEach(([key, value]) => {
    if (key === 'id_perusahaan_list') return;
    if (value !== '') payload[key] = value;
  });
  ['kode', 'no_pelat', 'gps_device_code', 'kepemilikan', 'status_operasional'].forEach((key) => {
    if (payload[key]) payload[key] = String(payload[key]).trim().toUpperCase();
  });
  if (payload.keterangan) payload.keterangan = String(payload.keterangan).trim().slice(0, 25);
  payload.id_perusahaan_list = Array.from(companyIds).join(',');
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
  if (form.id_perusahaan && !normalizeIds(form.id_perusahaan_list).includes(String(form.id_perusahaan))) {
    form.id_perusahaan_list = [...normalizeIds(form.id_perusahaan_list), String(form.id_perusahaan)];
  }
}

async function loadRows() {
  loading.value = true;
  error.value = '';
  try {
    const response = await getFleets();
    rows.value = normalizeList(unwrapResponse(response));
  } catch (err) {
    error.value = normalizeError(err, 'Data armada belum bisa dimuat.');
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

async function loadReferences() {
  const [branchResponse, companyResponse, fleetTypeResponse, assetResponse] = await Promise.all([
    getBranches(),
    getCompanies(),
    getFleetTypes(),
    getFixedAssets({ status: 'active' }).catch(() => null)
  ]);
  branches.value = normalizeList(unwrapResponse(branchResponse));
  companies.value = normalizeList(unwrapResponse(companyResponse));
  fleetTypes.value = normalizeList(unwrapResponse(fleetTypeResponse));
  assets.value = assetResponse ? normalizeList(unwrapResponse(assetResponse)) : [];
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
    nama: row?.nama || '',
    no_pelat: row?.no_pelat || '',
    merek: row?.merek || '',
    varian: row?.varian || '',
    tahun_pembuatan: row?.tahun_pembuatan ?? '',
    warna: row?.warna || '',
    nomor_rangka: row?.nomor_rangka || '',
    nomor_mesin: row?.nomor_mesin || '',
    kepemilikan: row?.kepemilikan || 'PERUSAHAAN',
    status_operasional: row?.status_operasional || (String(row?.id_status) === '0' ? 'INACTIVE' : 'AVAILABLE'),
    id_cabang: normalizeId(row?.id_cabang),
    id_perusahaan: normalizeId(row?.id_perusahaan),
    id_perusahaan_list: normalizeIds(row?.id_perusahaan_list || row?.id_perusahaan),
    id_tipe: normalizeId(row?.id_tipe),
    kubikasi: row?.kubikasi ?? '',
    kapasitas_kg: row?.kapasitas_kg ?? '',
    kapasitas_pallet: row?.kapasitas_pallet ?? '',
    tanggal_stnk: String(row?.tanggal_stnk || '').slice(0, 10),
    tanggal_uji: String(row?.tanggal_uji || '').slice(0, 10),
    tanggal_asuransi: String(row?.tanggal_asuransi || '').slice(0, 10),
    gps_device_code: row?.gps_device_code || '',
    id_inventaris: normalizeId(row?.id_inventaris),
    id_status: normalizeId(row?.id_status ?? 1),
    keterangan: row?.keterangan || ''
  });
  syncCompanyFromBranch(true);
  feedback.value = '';
  actionError.value = '';
  modalOpen.value = true;
}

async function save() {
  if (!form.kode.trim()) {
    actionError.value = 'Kode armada wajib diisi.';
    return;
  }
  if (!form.nama.trim()) {
    actionError.value = 'Nama armada wajib diisi.';
    return;
  }
  if (!form.no_pelat.trim()) {
    actionError.value = 'Nomor pelat wajib diisi.';
    return;
  }

  saving.value = true;
  feedback.value = '';
  actionError.value = '';
  try {
    if (mode.value === 'create') {
      await createFleet(buildPayload());
      feedback.value = 'Armada berhasil ditambahkan.';
      resetForm();
    } else {
      await updateFleet(selectedRow.value?.id, buildPayload());
      feedback.value = 'Armada berhasil diperbarui.';
    }
    await loadRows();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data armada belum berhasil disimpan.');
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
    await deleteFleet(selectedRow.value.id);
    modalOpen.value = false;
    await loadRows();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data armada belum berhasil dihapus.');
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

watch(
  () => form.id_perusahaan,
  (value) => {
    if (value && !normalizeIds(form.id_perusahaan_list).includes(String(value))) {
      form.id_perusahaan_list = [...normalizeIds(form.id_perusahaan_list), String(value)];
    }
  }
);
</script>

<template>
  <div class="space-y-4">
    <PageHeader title="Master Armada" description="Sumber data kendaraan untuk distribusi, WMS, dan aplikasi operasional.">
      <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700" @click="openCreate">
        Tambah Armada
      </button>
    </PageHeader>

    <AppFilterBar
      :model-value="filters"
      :fields="[{ key: 'search', label: 'Cari armada', placeholder: 'Kode, nama, pelat, merek, GPS, cabang' }]"
      @update:model-value="Object.assign(filters, $event)"
      @submit="loadRows"
      @reset="filters.search = ''"
    />

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ error }}</section>

    <AppTable :rows="filteredRows" :columns="columns" :loading="loading" :clickable-rows="true" empty-message="Belum ada data armada." @row-click="openEdit" />

    <AppModal :open="modalOpen" :title="mode === 'create' ? 'Tambah Armada' : 'Edit Armada'" panel-class="max-w-5xl" @close="modalOpen = false">
      <div class="space-y-6">
        <section class="space-y-3">
          <h3 class="text-sm font-semibold text-slate-900 dark:text-white">Identitas kendaraan</h3>
          <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <AppFormField v-model="form.kode" label="Kode Armada" placeholder="Contoh: ARM-SLO-001" />
            <AppFormField v-model="form.nama" label="Nama Armada" placeholder="Contoh: Truk Distribusi Solo 01" />
            <AppFormField v-model="form.no_pelat" label="No Pelat" placeholder="Contoh: AD 1234 XYZ" />
            <AppSearchSelect v-model="form.id_tipe" label="Tipe Armada" placeholder="Pilih tipe" :options="fleetTypeOptions" empty-text="Tipe armada belum tersedia." />
            <AppFormField v-model="form.merek" label="Merek" placeholder="Contoh: Mitsubishi" />
            <AppFormField v-model="form.varian" label="Varian / Model" placeholder="Contoh: Fuso Canter" />
            <AppFormField v-model="form.tahun_pembuatan" label="Tahun Pembuatan" type="number" min="1900" max="2100" />
            <AppFormField v-model="form.warna" label="Warna" />
            <AppFormField v-model="form.nomor_rangka" label="Nomor Rangka" />
            <AppFormField v-model="form.nomor_mesin" label="Nomor Mesin" />
          </div>
        </section>

        <section class="space-y-3 border-t border-slate-200 pt-5 dark:border-slate-800">
          <h3 class="text-sm font-semibold text-slate-900 dark:text-white">Cakupan dan operasional</h3>
          <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <AppSearchSelect v-model="form.id_cabang" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="!isSuperUser(authStore) && !!loginBranchId" />
            <AppSearchSelect v-model="form.id_perusahaan" label="Perusahaan Utama" :placeholder="form.id_cabang ? 'Pilih perusahaan utama' : 'Pilih cabang dulu'" :options="companyOptions" :disabled="!form.id_cabang" empty-text="Perusahaan belum tersedia." />
            <AppSearchSelect v-model="form.id_perusahaan_list" label="Boleh Dipakai Perusahaan" placeholder="Pilih perusahaan pemakai" :options="availableCompanyOptions" multiple empty-text="Perusahaan belum tersedia." />
            <AppSearchSelect v-model="form.kepemilikan" label="Kepemilikan" placeholder="Pilih kepemilikan" :options="ownershipOptions" />
            <AppSearchSelect v-model="form.status_operasional" label="Status Operasional" placeholder="Pilih status operasional" :options="operationalStatusOptions" />
            <AppSearchSelect v-model="form.id_status" label="Status Master" placeholder="Pilih status" :options="statusOptions" />
            <AppSearchSelect v-model="form.id_inventaris" label="Inventaris Terkait" placeholder="Pilih inventaris kendaraan" :options="assetOptions" empty-text="Inventaris aktif belum tersedia." />
            <AppFormField v-model="form.gps_device_code" label="Kode Perangkat GPS" placeholder="Opsional" />
          </div>
        </section>

        <section class="space-y-3 border-t border-slate-200 pt-5 dark:border-slate-800">
          <h3 class="text-sm font-semibold text-slate-900 dark:text-white">Kapasitas dan dokumen</h3>
          <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <AppFormField v-model="form.kubikasi" label="Kubikasi (m3)" type="number" min="0" step="1" />
            <AppFormField v-model="form.kapasitas_kg" label="Kapasitas Berat (kg)" type="number" min="0" step="0.01" />
            <AppFormField v-model="form.kapasitas_pallet" label="Kapasitas Pallet" type="number" min="0" step="1" />
            <AppFormField v-model="form.tanggal_stnk" label="Berlaku Sampai STNK" type="date" />
            <AppFormField v-model="form.tanggal_uji" label="Berlaku Sampai KIR / Uji" type="date" />
            <AppFormField v-model="form.tanggal_asuransi" label="Berlaku Sampai Asuransi" type="date" />
          </div>
        </section>

        <section class="border-t border-slate-200 pt-5 dark:border-slate-800">
          <AppFormField v-model="form.keterangan" label="Keterangan" type="textarea" maxlength="25" placeholder="Catatan singkat kendaraan" />
        </section>

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
