<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import {
  createUser,
  deleteUser,
  getBranches,
  getCompanies,
  getPositions,
  getUsers,
  updateUser
} from '@/api/master';
import { useRemoteCollection } from '@/composables/useRemoteCollection';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { branchMatchesCompany, getLoginBranchId, getLoginBranchIds, getLoginCompanyId, getLoginCompanyIds, getRowBranchIds, getRowCompanyIds, isSuperUser, scopeRowsByLoginBranch } from '@/utils/accessScope';
import { useAuthStore } from '@/stores/auth';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const filters = reactive({ search: '' });
const { items, loading, load, error } = useRemoteCollection(() => getUsers());
const positions = ref([]);
const branches = ref([]);
const companies = ref([]);
const modalOpen = ref(false);
const mode = ref('create');
const selectedRow = ref(null);
const feedback = ref('');
const actionError = ref('');
const saving = ref(false);
const coloumns = [
  { key: 'username', label: 'Username' },
  { key: 'nama', label: 'Nama User' },
  { key: 'email', label: 'Email' },
  { key: 'nama_jabatan', label: 'Jabatan' },
  { key: 'nama_cabang', label: 'Cabang' },
  { key: 'telepon', label: 'Telepon' }
];

const form = reactive({
  nama: '',
  email: '',
  telepon: '',
  no_rekening: '',
  npwp: '',
  nama_wp: '',
  alamat_wp: '',
  id_jabatan: '',
  id_cabang: [],
  username: '',
  password: '',
  nik: '',
  alamat: '',
  tanggal_lahir: '',
  id_perusahaan: []
});

const loginBranchId = computed(() => getLoginBranchId(authStore.user));
const loginCompanyId = computed(() => getLoginCompanyId(authStore.user));
const loginBranchIds = computed(() => getLoginBranchIds(authStore.user));
const loginCompanyIds = computed(() => getLoginCompanyIds(authStore.user));
const selectedBranchIds = computed(() => normalizeIds(form.id_cabang));
const selectedCompanyIdList = computed(() => normalizeIds(form.id_perusahaan));
const selectedCompanyIds = computed(() => {
  if (!selectedBranchIds.value.length) return [];
  const ids = new Set();

  branches.value
    .filter((item) => selectedBranchIds.value.includes(String(item.id)))
    .forEach((item) => {
      getRowCompanyIds(item).forEach((companyId) => ids.add(String(companyId)));
    });

  companies.value.forEach((item) => {
    if (selectedBranchIds.value.some((branchId) => getRowBranchIds(item).includes(String(branchId)))) {
      ids.add(String(item.id));
    }
  });

  return Array.from(ids);
});
const scopedItems = computed(() => scopeRowsByLoginBranch(items.value, authStore));
const scopedBranches = computed(() => scopeRowsByLoginBranch(branches.value, authStore));
const scopedCompanies = computed(() => {
  const companyIds = new Set(scopedBranches.value.flatMap((item) => getRowCompanyIds(item).map(String)).filter(Boolean));

  if (isSuperUser(authStore) || !companyIds.size) {
    return companies.value;
  }

  return companies.value.filter((item) => companyIds.has(String(item.id)));
});

const positionOptions = computed(() =>
  positions.value.map((item) => ({
    value: String(item.id),
    label: `${item.kode || '-'} - ${item.nama || 'Jabatan'}`
  }))
);

const branchOptions = computed(() =>
  scopedBranches.value
    .filter((item) => !selectedCompanyIdList.value.length || selectedCompanyIdList.value.some((companyId) => branchMatchesCompany(item, companyId)))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || '-'} - ${item.nama || item.nama_cabang || 'Cabang'}`
    }))
);

const companyOptions = computed(() =>
  scopedCompanies.value
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || '-'} - ${item.nama || 'Perusahaan'}`
    }))
);

const filteredItems = computed(() => {
  const query = filters.search.trim().toLowerCase();

  if (!query) {
    return scopedItems.value;
  }

  return scopedItems.value.filter((item) =>
    [item.nama, item.username, item.email, item.nik, item.nama_jabatan, item.nama_cabang]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query))
  );
});

const columns = [
  { key: 'username', label: 'Username' },
  { key: 'nama', label: 'Nama' },
  { key: 'nama_jabatan', label: 'Jabatan' },
  { key: 'nama_perusahaan_list', label: 'Perusahaan', render: (row) => row.nama_perusahaan_list || row.nama_perusahaan || '-' },
  { key: 'nama_cabang_list', label: 'Cabang', render: (row) => row.nama_cabang_list || row.nama_cabang || '-' },
  { key: 'telepon', label: 'Telepon' }
];

function normalizeIds(value) {
  const rawValues = Array.isArray(value) ? value : String(value || '').split(',');
  return rawValues.map((item) => String(item || '').trim()).filter(Boolean);
}

function resetForm() {
  Object.assign(form, {
    nama: '',
    email: '',
    telepon: '',
    no_rekening: '',
    npwp: '',
    nama_wp: '',
    alamat_wp: '',
    id_jabatan: '',
    id_cabang: [],
    username: '',
    password: '',
    nik: '',
    alamat: '',
    tanggal_lahir: '',
    id_perusahaan: []
  });
  applyLoginBranchDefault();
}

function syncCompanyFromBranch(preserveCurrent = false) {
  if (!selectedBranchIds.value.length) {
    if (!preserveCurrent) form.id_perusahaan = [];
    return;
  }

  const allowedCompanyIds = selectedCompanyIds.value;
  const currentCompanyIds = normalizeIds(form.id_perusahaan);
  const nextCompanyIds = currentCompanyIds.filter((id) => allowedCompanyIds.includes(String(id)));

  if (!preserveCurrent || nextCompanyIds.length !== currentCompanyIds.length) {
    form.id_perusahaan = nextCompanyIds;
  }
}

function applyLoginBranchDefault() {
  if (!isSuperUser(authStore) && loginBranchId.value) {
    form.id_cabang = loginBranchIds.value.length ? loginBranchIds.value : [String(loginBranchId.value)];
    form.id_perusahaan = loginCompanyIds.value.length ? loginCompanyIds.value : (loginCompanyId.value ? [String(loginCompanyId.value)] : []);
    syncCompanyFromBranch();
  }
}

async function loadOptions() {
  const [positionsResponse, branchesResponse, companiesResponse] = await Promise.all([
    getPositions(),
    getBranches(),
    getCompanies()
  ]);

  positions.value = normalizeList(unwrapResponse(positionsResponse));
  branches.value = normalizeList(unwrapResponse(branchesResponse));
  companies.value = normalizeList(unwrapResponse(companiesResponse));
  applyLoginBranchDefault();
}

function submit() {
  load();
}

function reset() {
  filters.search = '';
}

function openCreate() {
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
    nama: row?.nama || '',
    email: row?.email || '',
    telepon: row?.telepon || '',
    no_rekening: row?.no_rekening || '',
    npwp: row?.npwp || '',
    nama_wp: row?.nama_wp || '',
    alamat_wp: row?.alamat_wp || '',
    id_jabatan: row?.id_jabatan ? String(row.id_jabatan) : '',
    id_cabang: normalizeIds(row?.id_cabang_list || row?.cabang_ids || row?.id_cabang),
    username: row?.username || '',
    password: '',
    nik: row?.nik || '',
    alamat: row?.alamat || '',
    tanggal_lahir: row?.tanggal_lahir || '',
    id_perusahaan: normalizeIds(row?.id_perusahaan_list || row?.perusahaan_ids || row?.id_perusahaan)
  });
  syncCompanyFromBranch(true);
  modalOpen.value = true;
}

function closeModal() {
  modalOpen.value = false;
}

function buildPayload() {
  const branchIds = normalizeIds(form.id_cabang);
  const companyIds = normalizeIds(form.id_perusahaan);
  const payload = {
    nama: form.nama,
    email: form.email,
    telepon: form.telepon,
    no_rekening: form.no_rekening,
    npwp: form.npwp,
    nama_wp: form.nama_wp,
    alamat_wp: form.alamat_wp,
    id_jabatan: form.id_jabatan,
    id_cabang: branchIds[0] || '',
    id_cabang_list: branchIds.join(','),
    username: form.username,
    nik: form.nik,
    alamat: form.alamat,
    tanggal_lahir: form.tanggal_lahir,
    id_perusahaan: companyIds[0] || '',
    id_perusahaan_list: companyIds.join(',')
  };

  if (form.password) {
    payload.password = form.password;
  }

  return payload;
}

async function save() {
  saving.value = true;
  feedback.value = '';
  actionError.value = '';

  try {
    const payload = buildPayload();

    if (mode.value === 'create') {
      await createUser(payload);
      feedback.value = 'User berhasil ditambahkan.';
      resetForm();
    } else {
      await updateUser(selectedRow.value?.id, payload);
      feedback.value = 'User berhasil diperbarui.';
    }

    await load();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data user belum berhasil disimpan.');
  } finally {
    saving.value = false;
  }
}

async function remove() {
  if (!selectedRow.value?.id) {
    return;
  }

  saving.value = true;
  feedback.value = '';
  actionError.value = '';

  try {
    await deleteUser(selectedRow.value.id);
    modalOpen.value = false;
    await load();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data user belum berhasil dihapus.');
  } finally {
    saving.value = false;
  }
}

const userStats = computed(() => [
  {
    label: 'Total User',
    value: filteredItems.value.length,
    note: 'User sesuai filter aktif'
  },
  {
    label: 'Jabatan',
    value: positions.value.length,
    note: 'Referensi jabatan aktif'
  },
  {
    label: 'Cabang',
    value: scopedBranches.value.length,
    note: 'Cabang tersedia'
  },
  {
    label: 'Perusahaan',
    value: scopedCompanies.value.length,
    note: 'Entitas perusahaan'
  }
]);

watch(
  () => form.id_cabang,
  () => {
    syncCompanyFromBranch();
  }
);

onMounted(async () => {
  await Promise.all([submit(), loadOptions()]);
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Master User"
      description="Kelola akun user, jabatan, cabang, perusahaan, dan akses dasar ERP Budimas."
    >
      <button
        class="rounded-2xl bg-brand-600 px-5 py-2.5 text-sm font-bold text-white shadow-sm hover:bg-brand-700"
        @click="openCreate"
      >
        + Tambah User
      </button>
    </PageHeader>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <article
        v-for="item in userStats"
        :key="item.label"
        class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950"
      >
        <p class="text-xs font-bold uppercase tracking-[0.25em] text-slate-400">
          {{ item.label }}
        </p>
        <p class="mt-3 text-3xl font-bold text-slate-950 dark:text-white">
          {{ Number(item.value || 0).toLocaleString('id-ID') }}
        </p>
        <p class="mt-2 text-sm text-slate-500 dark:text-slate-400">
          {{ item.note }}
        </p>
      </article>
    </section>

    <section class="rounded-[32px] border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-950">
      <div class="mb-5 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h3 class="text-lg font-bold text-slate-950 dark:text-white">
            Data Table User
          </h3>
          <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Klik baris user untuk melihat atau mengubah data akun.
          </p>
        </div>

        <span class="rounded-full bg-brand-50 px-3 py-1 text-xs font-bold uppercase tracking-[0.2em] text-brand-700 dark:bg-brand-500/10 dark:text-brand-300">
          {{ filteredItems.length }} Data
        </span>
      </div>

      <AppFilterBar
        :model-value="filters"
        :fields="[
          {
            key: 'search',
            label: 'Cari user',
            placeholder: 'Nama, username, email, jabatan, cabang'
          }
        ]"
        @update:model-value="Object.assign(filters, $event)"
        @submit="submit"
        @reset="reset"
      />

      <section
        v-if="error"
        class="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300"
      >
        {{ error }}
      </section>

      <div class="mt-5 overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-800">
        <AppTable
          :rows="filteredItems"
          :columns="columns"
          :loading="loading"
          :clickable-rows="true"
          empty-message="Belum ada data user yang bisa ditampilkan."
          @row-click="openEdit"
        />
      </div>
    </section>

    <AppModal
      :open="modalOpen"
      :title="mode === 'create' ? 'Tambah User ERP' : 'Edit User ERP'"
      description="Lengkapi data akun, struktur ERP, dan informasi tambahan user."
      size="6xl"
      @close="closeModal"
    >
      <div class="space-y-5">
        <section class="rounded-3xl border border-slate-200 bg-slate-50 p-5 dark:border-slate-800 dark:bg-slate-900">
          <div class="mb-4">
            <h3 class="text-base font-bold text-slate-950 dark:text-white">
              Informasi Akun
            </h3>
            <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
              Data login dan identitas utama user.
            </p>
          </div>

          <div class="grid gap-4 md:grid-cols-2">
            <AppFormField v-model="form.nama" label="Nama" />
            <AppFormField v-model="form.username" label="Username" />
            <AppFormField
              v-model="form.password"
              :label="mode === 'create' ? 'Password' : 'Password Baru'"
              type="password"
            />
            <AppFormField v-model="form.email" label="Email" type="email" />
            <AppFormField v-model="form.nik" label="NIK" />
            <AppFormField v-model="form.telepon" label="Telepon" />
          </div>
        </section>

        <section class="rounded-3xl border border-slate-200 bg-slate-50 p-5 dark:border-slate-800 dark:bg-slate-900">
          <div class="mb-4">
            <h3 class="text-base font-bold text-slate-950 dark:text-white">
              Struktur ERP
            </h3>
            <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
              Relasi user dengan jabatan, cabang, dan perusahaan.
            </p>
          </div>

          <div class="grid gap-4 md:grid-cols-2">
            <AppSearchSelect
              v-model="form.id_jabatan"
              label="Jabatan"
              placeholder="Pilih jabatan"
              :options="positionOptions"
              empty-text="Jabatan belum tersedia."
            />

            <AppSearchSelect
              v-model="form.id_perusahaan"
              label="Perusahaan"
              placeholder="Pilih satu atau beberapa perusahaan"
              :options="companyOptions"
              :disabled="!isSuperUser(authStore) && !!loginCompanyId"
              multiple
              empty-text="Perusahaan belum tersedia."
            />

            <AppSearchSelect
              v-model="form.id_cabang"
              label="Cabang"
              placeholder="Pilih satu atau beberapa cabang"
              :options="branchOptions"
              :disabled="!isSuperUser(authStore) && !!loginBranchId"
              multiple
              empty-text="Cabang belum tersedia."
            />

            <AppFormField
              v-model="form.tanggal_lahir"
              label="Tanggal Lahir"
              type="date"
            />
          </div>
        </section>

        <section class="rounded-3xl border border-slate-200 bg-slate-50 p-5 dark:border-slate-800 dark:bg-slate-900">
          <div class="mb-4">
            <h3 class="text-base font-bold text-slate-950 dark:text-white">
              Data Tambahan
            </h3>
          </div>

          <div class="grid gap-4 md:grid-cols-2">
            <AppFormField v-model="form.alamat" label="Alamat" />
            <AppFormField v-model="form.no_rekening" label="No Rekening" />
            <AppFormField v-model="form.npwp" label="NPWP" />
            <AppFormField v-model="form.nama_wp" label="Nama WP" />
          </div>

          <div class="mt-4">
            <AppFormField v-model="form.alamat_wp" label="Alamat WP" />
          </div>
        </section>

        <section class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
          Password saat edit bersifat opsional. Jika dikosongkan, password lama tidak ikut diubah.
        </section>

        <div
          v-if="feedback"
          class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300"
        >
          {{ feedback }}
        </div>

        <div
          v-if="actionError"
          class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300"
        >
          {{ actionError }}
        </div>

        <div class="flex flex-wrap justify-between gap-2 border-t border-slate-200 pt-4 dark:border-slate-800">
          <div class="flex flex-wrap gap-2">
            <button
              class="rounded-2xl bg-brand-600 px-5 py-2.5 text-sm font-bold text-white shadow-sm hover:bg-brand-700 disabled:opacity-60"
              :disabled="saving"
              @click="save"
            >
              {{ saving ? 'Menyimpan...' : mode === 'create' ? 'Simpan User' : 'Update User' }}
            </button>

            <button
              class="rounded-2xl border border-slate-200 bg-white px-5 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 dark:hover:bg-slate-900"
              :disabled="saving"
              @click="closeModal"
            >
              Tutup
            </button>
          </div>

          <button
            v-if="mode === 'edit'"
            class="rounded-2xl border border-rose-200 bg-white px-5 py-2.5 text-sm font-bold text-rose-700 hover:bg-rose-50 disabled:opacity-60 dark:border-rose-500/30 dark:bg-slate-950 dark:text-rose-300 dark:hover:bg-rose-500/10"
            :disabled="saving"
            @click="remove"
          >
            Hapus User
          </button>
        </div>
      </div>
    </AppModal>
  </div>
</template>
