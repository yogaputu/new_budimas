<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import {
  createProductPpn,
  deleteProductPpn,
  getProductPpnList,
  updateProductPpn
} from '@/api/master';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const filters = reactive({ search: '' });
const rows = ref([]);
const loading = ref(false);
const error = ref('');
const feedback = ref('');
const actionError = ref('');
const modalOpen = ref(false);
const mode = ref('create');
const selectedRow = ref(null);
const saving = ref(false);

const form = reactive({
  kode: '',
  nama: '',
  persentase: 0,
  is_active: true,
  keterangan: ''
});

const filteredRows = computed(() => {
  const query = filters.search.trim().toLowerCase();
  if (!query) return rows.value;

  return rows.value.filter((item) =>
    [item.kode, item.nama, item.persentase, item.keterangan]
      .filter((value) => value !== null && value !== undefined)
      .some((value) => String(value).toLowerCase().includes(query))
  );
});

const summary = computed(() => ({
  total: rows.value.length,
  active: rows.value.filter((item) => item.is_active === true || item.is_active === 1).length,
  used: rows.value.reduce((acc, item) => acc + Number(item.total_produk || 0), 0)
}));

const columns = [
  { key: 'kode', label: 'Kode PPN' },
  { key: 'nama', label: 'Nama PPN' },
  {
    key: 'persentase',
    label: 'Persentase',
    render: (row) => `${Number(row.persentase || 0).toLocaleString('id-ID')}%`
  },
  {
    key: 'is_active',
    label: 'Status',
    render: (row) => (row.is_active === true || row.is_active === 1 ? 'Aktif' : 'Nonaktif')
  },
  {
    key: 'total_produk',
    label: 'Produk',
    render: (row) => Number(row.total_produk || 0).toLocaleString('id-ID')
  },
  { key: 'keterangan', label: 'Keterangan', render: (row) => row.keterangan || '-' }
];

function resetForm() {
  form.kode = '';
  form.nama = '';
  form.persentase = 0;
  form.is_active = true;
  form.keterangan = '';
}

async function load() {
  loading.value = true;
  error.value = '';

  try {
    const response = await getProductPpnList({ search: filters.search.trim() });
    rows.value = normalizeList(unwrapResponse(response));
  } catch (err) {
    error.value = normalizeError(err, 'Tipe PPN belum bisa dimuat.');
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

function submit() {
  load();
}

function reset() {
  filters.search = '';
  load();
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
  form.kode = row?.kode || '';
  form.nama = row?.nama || '';
  form.persentase = Number(row?.persentase || 0);
  form.is_active = row?.is_active === true || row?.is_active === 1;
  form.keterangan = row?.keterangan || '';
  modalOpen.value = true;
}

function closeModal() {
  modalOpen.value = false;
}

function buildPayload() {
  return {
    kode: form.kode,
    nama: form.nama,
    persentase: Number(form.persentase || 0),
    is_active: form.is_active,
    keterangan: form.keterangan
  };
}

async function save() {
  saving.value = true;
  feedback.value = '';
  actionError.value = '';

  try {
    if (mode.value === 'create') {
      await createProductPpn(buildPayload());
      feedback.value = 'Tipe PPN berhasil ditambahkan.';
      resetForm();
    } else {
      await updateProductPpn(selectedRow.value?.id, buildPayload());
      feedback.value = 'Tipe PPN berhasil diperbarui dan produk terkait ikut disinkronkan.';
    }

    await load();
  } catch (err) {
    actionError.value = normalizeError(err, 'Tipe PPN belum berhasil disimpan.');
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
    await deleteProductPpn(selectedRow.value.id);
    modalOpen.value = false;
    await load();
  } catch (err) {
    actionError.value = normalizeError(err, 'Tipe PPN belum berhasil dihapus.');
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="space-y-5">
    <PageHeader
      title="Tipe PPN"
      description="Kelola tarif PPN produk. Produk bisa memakai Non PPN, PPN 11%, atau tarif lain sesuai kebutuhan pajak."
    >
      <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700" @click="openCreate">
        Tambah PPN
      </button>
    </PageHeader>

    <section class="grid gap-4 md:grid-cols-3">
      <article class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <p class="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Total Tarif</p>
        <p class="mt-3 text-3xl font-bold text-slate-950 dark:text-white">{{ summary.total }}</p>
      </article>
      <article class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <p class="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Tarif Aktif</p>
        <p class="mt-3 text-3xl font-bold text-slate-950 dark:text-white">{{ summary.active }}</p>
      </article>
      <article class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <p class="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Produk Terkait</p>
        <p class="mt-3 text-3xl font-bold text-slate-950 dark:text-white">{{ summary.used.toLocaleString('id-ID') }}</p>
      </article>
    </section>

    <AppFilterBar
      :model-value="filters"
      :fields="[{ key: 'search', label: 'Cari PPN', placeholder: 'Kode, nama, persentase, atau catatan' }]"
      @update:model-value="Object.assign(filters, $event)"
      @submit="submit"
      @reset="reset"
    />

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ error }}
    </section>

    <AppTable
      :rows="filteredRows"
      :columns="columns"
      :loading="loading"
      :clickable-rows="true"
      empty-message="Belum ada master PPN yang bisa ditampilkan."
      @row-click="openEdit"
    />

    <AppModal :open="modalOpen" :title="mode === 'create' ? 'Tambah Tipe PPN' : 'Edit Tipe PPN'" @close="closeModal">
      <div class="space-y-4">
        <div class="grid gap-4 md:grid-cols-2">
          <AppFormField v-model="form.kode" label="Kode PPN" placeholder="PPN_11 / NON_PPN" />
          <AppFormField v-model="form.nama" label="Nama PPN" placeholder="PPN 11%" />
          <AppFormField v-model="form.persentase" label="Persentase" type="number" min="0" step="0.01" />
          <label class="flex items-center gap-3 rounded-2xl border border-slate-200 px-4 py-3 text-sm dark:border-slate-700">
            <input v-model="form.is_active" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500" />
            <span class="font-medium text-slate-700 dark:text-slate-200">Status aktif</span>
          </label>
        </div>

        <AppFormField v-model="form.keterangan" label="Keterangan" type="textarea" placeholder="Catatan tarif atau dasar penggunaan" />

        <div v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {{ feedback }}
        </div>
        <div v-if="actionError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {{ actionError }}
        </div>

        <div class="flex flex-wrap gap-2">
          <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white" :disabled="saving" @click="save">
            {{ saving ? 'Menyimpan...' : mode === 'create' ? 'Simpan PPN' : 'Update PPN' }}
          </button>
          <button
            v-if="mode === 'edit'"
            class="rounded-xl border border-rose-200 px-4 py-2 text-sm font-medium text-rose-700"
            :disabled="saving"
            @click="remove"
          >
            Hapus
          </button>
        </div>
      </div>
    </AppModal>
  </div>
</template>
