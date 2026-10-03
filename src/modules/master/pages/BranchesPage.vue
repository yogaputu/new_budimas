<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { createBranch, deleteBranch, getBranches, updateBranch } from '@/api/master';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { useAuthStore } from '@/stores/auth';
import { scopeRowsByLoginBranch } from '@/utils/accessScope';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const RESOURCE = 'master.branches';

const filters = reactive({ search: '' });
const form = reactive({
  kode: '',
  nama: '',
  alamat: '',
  telepon: ''
});

const rows = ref([]);
const loading = ref(false);
const saving = ref(false);
const modalOpen = ref(false);
const mode = ref('create');
const selectedRow = ref(null);
const error = ref('');
const actionError = ref('');
const feedback = ref('');

const canCreate = computed(() => authStore.canCreate(RESOURCE));
const canUpdate = computed(() => authStore.canUpdate(RESOURCE));
const canDelete = computed(() => authStore.canDelete(RESOURCE));
const scopedRows = computed(() => scopeRowsByLoginBranch(rows.value, authStore));

const filteredRows = computed(() => {
  const keyword = filters.search.trim().toLowerCase();
  if (!keyword) return scopedRows.value;
  return scopedRows.value.filter((item) =>
    [item.kode, item.nama, item.alamat, item.telepon]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(keyword))
  );
});

const columns = [
  { key: 'kode', label: 'Kode Cabang' },
  { key: 'nama', label: 'Nama Cabang' },
  { key: 'alamat', label: 'Alamat' },
  { key: 'telepon', label: 'Nomor Telepon' }
];

function resetForm() {
  Object.assign(form, {
    kode: '',
    nama: '',
    alamat: '',
    telepon: ''
  });
}

function buildPayload() {
  return {
    kode: form.kode,
    nama: form.nama,
    alamat: form.alamat,
    telepon: form.telepon
  };
}

async function loadRows() {
  loading.value = true;
  error.value = '';

  try {
    const response = await getBranches();
    rows.value = normalizeList(unwrapResponse(response));
  } catch (err) {
    error.value = normalizeError(err, 'Data cabang belum bisa dimuat.');
    rows.value = [];
  } finally {
    loading.value = false;
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

function openEdit(row) {
  if (!canUpdate.value) return;
  mode.value = 'edit';
  selectedRow.value = row;
  Object.assign(form, {
    kode: row?.kode || '',
    nama: row?.nama || '',
    alamat: row?.alamat || '',
    telepon: row?.telepon || ''
  });
  feedback.value = '';
  actionError.value = '';
  modalOpen.value = true;
}

async function save() {
  if (!form.kode.trim()) {
    actionError.value = 'Kode cabang wajib diisi.';
    return;
  }

  if (!form.nama.trim()) {
    actionError.value = 'Nama cabang wajib diisi.';
    return;
  }

  if (mode.value === 'create' && !canCreate.value) {
    actionError.value = 'Hak akses Anda tidak memiliki izin tambah cabang.';
    return;
  }

  if (mode.value === 'edit' && !canUpdate.value) {
    actionError.value = 'Hak akses Anda tidak memiliki izin ubah cabang.';
    return;
  }

  saving.value = true;
  feedback.value = '';
  actionError.value = '';

  try {
    if (mode.value === 'create') {
      await createBranch(buildPayload());
      feedback.value = 'Cabang berhasil ditambahkan.';
      resetForm();
    } else {
      await updateBranch(selectedRow.value?.id, buildPayload());
      feedback.value = 'Cabang berhasil diperbarui.';
    }
    await loadRows();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data cabang belum berhasil disimpan.');
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
    await deleteBranch(selectedRow.value.id);
    modalOpen.value = false;
    await loadRows();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data cabang belum berhasil dihapus.');
  } finally {
    saving.value = false;
  }
}

onMounted(loadRows);
</script>

<template>
  <div class="space-y-4">
    <PageHeader title="Master Cabang" description="Data cabang berdiri sendiri dan hanya menyimpan kode, nama, alamat, serta nomor telepon.">
      <button
        class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-500"
        :disabled="!canCreate"
        @click="openCreate"
      >
        Tambah Cabang
      </button>
    </PageHeader>

    <AppFilterBar
      :model-value="filters"
      :fields="[{ key: 'search', label: 'Cari cabang', placeholder: 'Kode, nama, alamat, atau nomor telepon' }]"
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
      empty-message="Belum ada data cabang."
      @row-click="openEdit"
    />

    <AppModal :open="modalOpen" :title="mode === 'create' ? 'Tambah Cabang' : 'Edit Cabang'" panel-class="max-w-2xl" @close="modalOpen = false">
      <div class="space-y-4">
        <div class="grid gap-4 md:grid-cols-2">
          <AppFormField v-model="form.kode" label="Kode Cabang" />
          <AppFormField v-model="form.nama" label="Nama Cabang" />
          <AppFormField v-model="form.telepon" label="Nomor Telepon" />
          <AppFormField v-model="form.alamat" label="Alamat" />
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
