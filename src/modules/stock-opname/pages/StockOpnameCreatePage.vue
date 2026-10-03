<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import {
  createStockOpnameSchedule,
  deleteStockOpnameSchedule,
  getStockOpnameSchedules,
  updateStockOpnameSchedule
} from '@/api/stockOpname';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getRowBranchIds, getRowCompanyId } from '@/utils/accessScope';
import { toLocalDateInputValue } from '@/utils/date';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();

const form = reactive({
  id_perusahaan: '',
  id_cabang: '',
  id_principal: '',
  tanggal_pelaksanaan: toLocalDateInputValue(),
  kode_so: '',
  ket_so: ''
});

const editForm = reactive({
  id_perusahaan: '',
  id_cabang: '',
  id_principal: '',
  tanggal_pelaksanaan: '',
  kode_so: '',
  ket_so: ''
});

const companyRows = ref([]);
const branchRows = ref([]);
const principalRows = ref([]);
const scheduleRows = ref([]);
const feedback = ref('');
const errorMessage = ref('');
const saving = ref(false);
const scheduleLoading = ref(false);
const scheduleActionId = ref('');
const scheduleSearch = ref('');
const scheduleEditOpen = ref(false);
const editingSchedule = ref(null);

const loginBranchId = computed(() =>
  authStore.user?.id_cabang || authStore.user?.cabang_id || authStore.user?.cabang?.id || ''
);

const normalizedLoginRole = computed(() =>
  [
    authStore.user?.username,
    authStore.user?.email,
    authStore.user?.nama,
    authStore.user?.nama_jabatan,
    authStore.user?.jabatan?.nama,
    authStore.roleLabel,
    authStore.roleScope
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
);

const isSuperUser = computed(() =>
  authStore.permissions?.includes('*') ||
  normalizedLoginRole.value.includes('adminit1') ||
  normalizedLoginRole.value.includes('superadmin') ||
  normalizedLoginRole.value.includes('super admin') ||
  normalizedLoginRole.value.includes('super user') ||
  normalizedLoginRole.value.includes('admin it')
);

function companyIdsForBranch(branchId) {
  if (!branchId) return [];

  const ids = new Set();
  const branch = branchRows.value.find((item) => String(item.id) === String(branchId));
  const branchCompanyId = getRowCompanyId(branch);
  if (branchCompanyId) ids.add(String(branchCompanyId));

  companyRows.value.forEach((item) => {
    if (getRowBranchIds(item).includes(String(branchId))) ids.add(String(item.id));
  });

  return Array.from(ids);
}

function companyOptionsForBranch(branchId) {
  const allowedIds = companyIdsForBranch(branchId);
  return companyRows.value
    .filter((item) => allowedIds.includes(String(item.id)))
    .map((item) => ({
      value: String(item.id),
      label: item.nama || item.nama_perusahaan || `Perusahaan ${item.id}`
    }));
}

function principalOptionsForCompany(companyId) {
  return principalRows.value
    .filter((item) => !companyId || String(item.id_perusahaan || item.company_id || '') === String(companyId))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || '-'} - ${item.nama || 'Principal'}`
    }));
}

const branchOptions = computed(() =>
  branchRows.value
    .filter((item) => isSuperUser.value || !loginBranchId.value || String(item.id) === String(loginBranchId.value))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || '-'} - ${item.nama || item.nama_cabang || 'Cabang'}`
    }))
);

const companyOptions = computed(() => companyOptionsForBranch(form.id_cabang));
const principalOptions = computed(() => principalOptionsForCompany(form.id_perusahaan));
const editCompanyOptions = computed(() => companyOptionsForBranch(editForm.id_cabang));
const editPrincipalOptions = computed(() => principalOptionsForCompany(editForm.id_perusahaan));

const selectedBranch = computed(() => branchOptions.value.find((item) => item.value === String(form.id_cabang))?.label || '-');
const selectedPrincipal = computed(() => principalOptions.value.find((item) => item.value === String(form.id_principal))?.label || '-');

const filteredScheduleRows = computed(() => {
  const keyword = scheduleSearch.value.trim().toLowerCase();
  if (!keyword) return scheduleRows.value;
  return scheduleRows.value.filter((row) =>
    [
      row.kode_so,
      row.kode_cabang,
      row.nama_cabang,
      row.kode_perusahaan,
      row.nama_perusahaan,
      row.kode_principal,
      row.nama_principal,
      row.keterangan,
      row.status_so
    ]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(keyword))
  );
});

function syncCompanyFromBranch(target) {
  const allowedIds = companyIdsForBranch(target.id_cabang);
  if (!target.id_cabang || !allowedIds.length) {
    target.id_perusahaan = '';
    return;
  }
  if (!allowedIds.includes(String(target.id_perusahaan || ''))) target.id_perusahaan = allowedIds[0] || '';
}

function syncPrincipalFromCompany(target, options) {
  if (target.id_principal && !options.some((item) => item.value === String(target.id_principal))) {
    target.id_principal = '';
  }
}

function formatDate(value) {
  const raw = String(value || '').slice(0, 10);
  const [year, month, day] = raw.split('-');
  return year && month && day ? `${day}/${month}/${year}` : '-';
}

function statusLabel(value) {
  const status = String(value || '').trim().toLowerCase();
  return {
    scheduled: 'Terjadwal',
    in_progress: 'Sedang Opname',
    'under review': 'Menunggu Verifikasi',
    under_review: 'Menunggu Verifikasi',
    completed: 'Selesai',
    done: 'Selesai',
    rejected: 'Ditolak',
    eskalasi: 'Eskalasi'
  }[status] || value || '-';
}

function statusClass(value) {
  const status = String(value || '').trim().toLowerCase();
  if (status === 'scheduled') return 'border-amber-400/30 bg-amber-500/15 text-amber-300';
  if (status === 'in_progress') return 'border-sky-400/30 bg-sky-500/15 text-sky-300';
  if (['completed', 'done'].includes(status)) return 'border-emerald-400/30 bg-emerald-500/15 text-emerald-300';
  if (status === 'rejected') return 'border-rose-400/30 bg-rose-500/15 text-rose-300';
  return 'border-slate-600 bg-slate-800 text-slate-300';
}

function canMutateSchedule(row) {
  return row?.can_edit === true || ['true', '1', 't'].includes(String(row?.can_edit || '').toLowerCase());
}

function resetEditForm() {
  Object.assign(editForm, {
    id_perusahaan: '',
    id_cabang: '',
    id_principal: '',
    tanggal_pelaksanaan: '',
    kode_so: '',
    ket_so: ''
  });
  editingSchedule.value = null;
}

function closeScheduleEdit() {
  if (scheduleActionId.value) return;
  scheduleEditOpen.value = false;
  resetEditForm();
}

async function loadOptions() {
  errorMessage.value = '';
  try {
    const [companyResponse, branchResponse, principalResponse] = await Promise.all([
      getCompanies(),
      getBranches(),
      getPrincipals()
    ]);
    companyRows.value = normalizeList(unwrapResponse(companyResponse));
    branchRows.value = normalizeList(unwrapResponse(branchResponse));
    principalRows.value = normalizeList(unwrapResponse(principalResponse));

    if (!isSuperUser.value && loginBranchId.value) form.id_cabang = String(loginBranchId.value);
    syncCompanyFromBranch(form);
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Master cabang, perusahaan, atau principal belum bisa dimuat.');
  }
}

function scheduleListParams() {
  // Daftar jadwal tidak mengikuti form pembuatan agar admin tetap dapat
  // mengelola jadwal principal/cabang lain tanpa perlu mengosongkan form.
  // Untuk akun cabang, backend tetap diberi batas cabang login.
  return {
    id_cabang: !isSuperUser.value && loginBranchId.value ? loginBranchId.value : undefined,
    limit: 100
  };
}

async function loadSchedules() {
  scheduleLoading.value = true;
  try {
    const response = await getStockOpnameSchedules(scheduleListParams());
    scheduleRows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    scheduleRows.value = [];
    errorMessage.value = normalizeError(error, 'Daftar jadwal stok opname belum bisa dimuat.');
  } finally {
    scheduleLoading.value = false;
  }
}

async function submitForm() {
  feedback.value = '';
  errorMessage.value = '';

  if (!form.id_cabang || !form.id_perusahaan || !form.id_principal || !form.tanggal_pelaksanaan) {
    errorMessage.value = 'Lengkapi cabang, perusahaan, principal, dan tanggal pelaksanaan.';
    return;
  }

  saving.value = true;
  try {
    const response = await createStockOpnameSchedule({
      id_cabang: form.id_cabang,
      id_principal: form.id_principal,
      tanggal_pelaksanaan: form.tanggal_pelaksanaan,
      kode_so: form.kode_so.trim() || undefined,
      keterangan: form.ket_so,
      id_user_input: authStore.user?.id
    });
    const result = unwrapResponse(response)?.data || unwrapResponse(response) || {};
    feedback.value = `Jadwal ${result.kode_so || form.kode_so || 'stok opname'} berhasil dibuat untuk ${formatDate(form.tanggal_pelaksanaan)}.`;
    form.kode_so = '';
    form.ket_so = '';
    await loadSchedules();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Gagal membuat jadwal stok opname.');
  } finally {
    saving.value = false;
  }
}

function openScheduleEdit(row) {
  if (!canMutateSchedule(row)) {
    errorMessage.value = row.edit_lock_reason || 'Jadwal ini sudah tidak dapat diubah.';
    return;
  }

  Object.assign(editForm, {
    id_perusahaan: String(row.id_perusahaan || ''),
    id_cabang: String(row.id_cabang || ''),
    id_principal: String(row.id_principal || ''),
    tanggal_pelaksanaan: String(row.tanggal_pelaksanaan || '').slice(0, 10),
    kode_so: row.kode_so || '',
    ket_so: row.keterangan || row.ket_so || ''
  });
  editingSchedule.value = row;
  scheduleEditOpen.value = true;
}

async function saveScheduleEdit() {
  const row = editingSchedule.value;
  if (!row) return;

  if (!editForm.id_cabang || !editForm.id_perusahaan || !editForm.id_principal || !editForm.tanggal_pelaksanaan) {
    errorMessage.value = 'Lengkapi cabang, perusahaan, principal, dan tanggal pelaksanaan.';
    return;
  }

  feedback.value = '';
  errorMessage.value = '';
  scheduleActionId.value = `edit-${row.id_stock_opname || row.id}`;
  try {
    await updateStockOpnameSchedule(row.id_stock_opname || row.id, {
      id_cabang: editForm.id_cabang,
      id_principal: editForm.id_principal,
      tanggal_pelaksanaan: editForm.tanggal_pelaksanaan,
      kode_so: editForm.kode_so.trim(),
      keterangan: editForm.ket_so
    });
    feedback.value = `Jadwal ${row.kode_so || row.id_stock_opname} berhasil diperbarui.`;
    scheduleEditOpen.value = false;
    resetEditForm();
    await loadSchedules();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Gagal memperbarui jadwal stok opname.');
  } finally {
    scheduleActionId.value = '';
  }
}

async function removeSchedule(row) {
  if (!canMutateSchedule(row)) {
    errorMessage.value = row.edit_lock_reason || 'Jadwal ini sudah tidak dapat dihapus.';
    return;
  }

  const label = row.kode_so || `#${row.id_stock_opname || row.id}`;
  if (!window.confirm(`Hapus jadwal ${label}? Jadwal yang belum dimulai akan dihapus permanen.`)) return;

  feedback.value = '';
  errorMessage.value = '';
  scheduleActionId.value = `delete-${row.id_stock_opname || row.id}`;
  try {
    await deleteStockOpnameSchedule(row.id_stock_opname || row.id);
    feedback.value = `Jadwal ${label} berhasil dihapus.`;
    await loadSchedules();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Gagal menghapus jadwal stok opname.');
  } finally {
    scheduleActionId.value = '';
  }
}

watch(
  () => form.id_cabang,
  () => {
    syncCompanyFromBranch(form);
    syncPrincipalFromCompany(form, principalOptions.value);
  }
);

watch(
  () => form.id_perusahaan,
  () => syncPrincipalFromCompany(form, principalOptions.value)
);

watch(
  () => editForm.id_cabang,
  () => {
    syncCompanyFromBranch(editForm);
    syncPrincipalFromCompany(editForm, editPrincipalOptions.value);
  }
);

watch(
  () => editForm.id_perusahaan,
  () => syncPrincipalFromCompany(editForm, editPrincipalOptions.value)
);

onMounted(async () => {
  await loadOptions();
  await loadSchedules();
});
</script>

<template>
  <div class="space-y-5">
    <PageHeader
      title="Jadwalkan Stok Opname Gudang"
      description="Buat jadwal dari ERP, lalu petugas melaksanakan hitung fisik per rak melalui WMS mobile. Jadwal hanya dapat diubah atau dihapus sebelum proses dimulai."
    />

    <section class="panel overflow-hidden">
      <div class="border-b border-slate-800 px-5 py-4">
        <h2 class="text-lg font-bold text-white">Informasi Jadwal Baru</h2>
        <p class="mt-1 text-sm text-slate-400">Satu jadwal aktif berlaku untuk satu cabang dan satu principal.</p>
      </div>

      <div class="grid gap-5 p-5 lg:grid-cols-2">
        <AppSearchSelect
          v-model="form.id_cabang"
          label="Cabang"
          placeholder="Cari / pilih cabang"
          :options="branchOptions"
          :disabled="!isSuperUser && !!loginBranchId"
          empty-text="Cabang belum tersedia."
        />
        <AppSearchSelect
          v-model="form.id_perusahaan"
          label="Perusahaan"
          :placeholder="form.id_cabang ? 'Pilih perusahaan' : 'Pilih cabang dulu'"
          :options="companyOptions"
          :disabled="!form.id_cabang"
          empty-text="Pilih cabang terlebih dahulu."
        />
        <AppSearchSelect
          v-model="form.id_principal"
          label="Principal"
          :placeholder="form.id_perusahaan ? 'Cari / pilih principal' : 'Pilih perusahaan dulu'"
          :options="principalOptions"
          :disabled="!form.id_perusahaan"
          :max-visible-options="80"
          empty-text="Principal belum tersedia."
        />
        <AppFormField
          v-model="form.tanggal_pelaksanaan"
          label="Tanggal Pelaksanaan"
          type="date"
          :min="toLocalDateInputValue()"
        />
        <AppFormField v-model="form.kode_so" label="Kode Jadwal" placeholder="Kosongkan untuk nomor otomatis" />
        <AppFormField v-model="form.ket_so" label="Catatan" type="textarea" placeholder="Catatan pelaksanaan (opsional)" />
      </div>

      <div class="border-t border-slate-800 bg-slate-950/30 px-5 py-4">
        <div class="grid gap-3 sm:grid-cols-3">
          <div>
            <p class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Cabang</p>
            <p class="mt-1 text-sm font-semibold text-slate-200">{{ selectedBranch }}</p>
          </div>
          <div>
            <p class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Principal</p>
            <p class="mt-1 text-sm font-semibold text-slate-200">{{ selectedPrincipal }}</p>
          </div>
          <div>
            <p class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Status Awal</p>
            <p class="mt-1 text-sm font-semibold text-amber-300">Terjadwal</p>
          </div>
        </div>
      </div>
    </section>

    <div v-if="feedback" class="rounded-lg border border-emerald-700/50 bg-emerald-950/30 px-4 py-3 text-sm text-emerald-300">
      {{ feedback }}
    </div>
    <div v-if="errorMessage" class="rounded-lg border border-rose-700/50 bg-rose-950/30 px-4 py-3 text-sm text-rose-300">
      {{ errorMessage }}
    </div>

    <div class="flex justify-end">
      <button class="btn-primary" type="button" :disabled="saving" @click="submitForm">
        {{ saving ? 'Menyimpan...' : 'Simpan Jadwal' }}
      </button>
    </div>

    <section class="panel overflow-hidden">
      <div class="flex flex-wrap items-start justify-between gap-4 border-b border-slate-800 px-5 py-4">
        <div>
          <h2 class="text-lg font-bold text-white">Daftar Jadwal Stok Opname</h2>
          <p class="mt-1 text-sm text-slate-400">Ubah atau hapus hanya saat status masih Terjadwal dan belum ada proses hitung dari WMS.</p>
        </div>
        <button class="btn-secondary" type="button" :disabled="scheduleLoading" @click="loadSchedules">
          {{ scheduleLoading ? 'Memuat...' : 'Muat Ulang' }}
        </button>
      </div>

      <div class="border-b border-slate-800 px-5 py-3">
        <label class="block max-w-xl text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
          Cari Jadwal
          <input
            v-model="scheduleSearch"
            class="field mt-1"
            placeholder="Kode jadwal, cabang, perusahaan, principal, atau status"
          />
        </label>
      </div>

      <div class="overflow-x-auto">
        <table class="min-w-[1040px] w-full divide-y divide-slate-800 text-sm">
          <thead class="bg-slate-900 text-left text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">
            <tr>
              <th class="px-4 py-3">Kode / Tanggal</th>
              <th class="px-4 py-3">Cabang</th>
              <th class="px-4 py-3">Perusahaan / Principal</th>
              <th class="px-4 py-3">Catatan</th>
              <th class="px-4 py-3">Status</th>
              <th class="px-4 py-3">Aksi</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800 bg-slate-950 text-slate-200">
            <tr v-if="scheduleLoading">
              <td colspan="6" class="px-4 py-10 text-center text-slate-400">Memuat jadwal stok opname...</td>
            </tr>
            <tr v-else-if="!filteredScheduleRows.length">
              <td colspan="6" class="px-4 py-10 text-center text-slate-400">Belum ada jadwal stok opname untuk filter saat ini.</td>
            </tr>
            <tr v-for="row in filteredScheduleRows" :key="row.id_stock_opname || row.id" class="align-top hover:bg-slate-900/70">
              <td class="px-4 py-3">
                <p class="font-semibold text-white">{{ row.kode_so || `#${row.id_stock_opname || row.id}` }}</p>
                <p class="mt-1 text-xs text-slate-400">Pelaksanaan: {{ formatDate(row.tanggal_pelaksanaan) }}</p>
                <p v-if="row.tanggal_dibuat" class="mt-1 text-xs text-slate-500">Dibuat: {{ formatDate(row.tanggal_dibuat) }}</p>
              </td>
              <td class="px-4 py-3">
                <p class="font-medium text-slate-100">{{ row.nama_cabang || '-' }}</p>
                <p class="mt-1 text-xs text-slate-500">{{ row.kode_cabang || '-' }}</p>
              </td>
              <td class="px-4 py-3">
                <p class="font-medium text-slate-100">{{ row.nama_perusahaan || '-' }}</p>
                <p class="mt-1 text-xs text-slate-400">{{ row.nama_principal || '-' }}</p>
              </td>
              <td class="max-w-sm px-4 py-3 text-slate-300">
                <p class="whitespace-pre-line break-words">{{ row.keterangan || '-' }}</p>
                <p v-if="row.dibuat_oleh" class="mt-2 text-xs text-slate-500">Pembuat: {{ row.dibuat_oleh }}</p>
              </td>
              <td class="px-4 py-3">
                <span :class="['inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold', statusClass(row.status_so)]">
                  {{ statusLabel(row.status_so) }}
                </span>
                <p v-if="row.started_at" class="mt-2 text-xs text-slate-400">Mulai: {{ row.started_at }}</p>
                <p v-if="row.finished_at" class="mt-1 text-xs text-slate-400">Selesai: {{ row.finished_at }}</p>
              </td>
              <td class="px-4 py-3">
                <div class="flex min-w-[205px] flex-wrap gap-2">
                  <button
                    class="btn-secondary !px-3 !py-1.5"
                    type="button"
                    :disabled="!canMutateSchedule(row) || !!scheduleActionId"
                    :title="canMutateSchedule(row) ? 'Ubah jadwal' : (row.edit_lock_reason || 'Jadwal tidak dapat diubah')"
                    @click="openScheduleEdit(row)"
                  >
                    Ubah
                  </button>
                  <button
                    class="btn-danger !px-3 !py-1.5"
                    type="button"
                    :disabled="!canMutateSchedule(row) || !!scheduleActionId"
                    :title="canMutateSchedule(row) ? 'Hapus jadwal' : (row.edit_lock_reason || 'Jadwal tidak dapat dihapus')"
                    @click="removeSchedule(row)"
                  >
                    {{ scheduleActionId === `delete-${row.id_stock_opname || row.id}` ? 'Menghapus...' : 'Hapus' }}
                  </button>
                </div>
                <p v-if="!canMutateSchedule(row)" class="mt-2 max-w-[240px] text-xs leading-5 text-slate-500">
                  {{ row.edit_lock_reason || 'Jadwal terkunci setelah proses opname dimulai.' }}
                </p>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <AppModal
      :open="scheduleEditOpen"
      title="Ubah Jadwal Stok Opname"
      description="Perubahan hanya dapat disimpan sebelum petugas memulai proses stok opname di WMS."
      size="xl"
      :close-on-backdrop="!scheduleActionId"
      @close="closeScheduleEdit"
    >
      <div class="grid gap-5 md:grid-cols-2">
        <AppSearchSelect
          v-model="editForm.id_cabang"
          label="Cabang"
          placeholder="Cari / pilih cabang"
          :options="branchOptions"
          :disabled="!isSuperUser && !!loginBranchId"
          empty-text="Cabang belum tersedia."
        />
        <AppSearchSelect
          v-model="editForm.id_perusahaan"
          label="Perusahaan"
          :placeholder="editForm.id_cabang ? 'Pilih perusahaan' : 'Pilih cabang dulu'"
          :options="editCompanyOptions"
          :disabled="!editForm.id_cabang"
          empty-text="Pilih cabang terlebih dahulu."
        />
        <AppSearchSelect
          v-model="editForm.id_principal"
          label="Principal"
          :placeholder="editForm.id_perusahaan ? 'Cari / pilih principal' : 'Pilih perusahaan dulu'"
          :options="editPrincipalOptions"
          :disabled="!editForm.id_perusahaan"
          :max-visible-options="80"
          empty-text="Principal belum tersedia."
        />
        <AppFormField v-model="editForm.tanggal_pelaksanaan" label="Tanggal Pelaksanaan" type="date" :min="toLocalDateInputValue()" />
        <AppFormField v-model="editForm.kode_so" label="Kode Jadwal" placeholder="Kosongkan untuk nomor otomatis" />
        <AppFormField v-model="editForm.ket_so" label="Catatan" type="textarea" placeholder="Catatan pelaksanaan (opsional)" />
      </div>

      <template #footer>
        <div class="flex flex-wrap justify-end gap-2">
          <button class="btn-secondary" type="button" :disabled="!!scheduleActionId" @click="closeScheduleEdit">Batal</button>
          <button class="btn-primary" type="button" :disabled="!!scheduleActionId" @click="saveScheduleEdit">
            {{ scheduleActionId ? 'Menyimpan...' : 'Simpan Perubahan' }}
          </button>
        </div>
      </template>
    </AppModal>
  </div>
</template>
