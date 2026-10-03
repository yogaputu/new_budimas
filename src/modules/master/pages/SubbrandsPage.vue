<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import {
  createProductSubbrand,
  deleteProductSubbrand,
  getProductBrands,
  getProductSubbrands,
  updateProductSubbrand
} from '@/api/master';
import { useAppStore } from '@/app/stores/app';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const app = useAppStore();

const filters = reactive({
  search: '',
  id_brand: '',
  status: 'active'
});

const subbrands = ref([]);
const brands = ref([]);
const loading = ref(false);
const error = ref('');
const modalOpen = ref(false);
const mode = ref('create');
const selectedRow = ref(null);
const saving = ref(false);
const feedback = ref('');
const actionError = ref('');

const form = reactive({
  id_brand: '',
  kode: '',
  nama: '',
  keterangan: '',
  is_active: true
});

const brandOptions = computed(() =>
  brands.value.map((item) => ({
    value: String(item.id),
    label: item.text || item.nama || item.kode || `Brand #${item.id}`
  }))
);

const filteredRows = computed(() => {
  const keyword = filters.search.trim().toLowerCase();
  return subbrands.value.filter((item) => {
    const matchesKeyword =
      !keyword ||
      [item.kode, item.nama, item.brand_nama, item.keterangan]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(keyword));
    const matchesBrand = !filters.id_brand || String(item.id_brand || '') === String(filters.id_brand);
    const matchesStatus =
      filters.status === 'all' ||
      (filters.status === 'active' && item.is_active !== false) ||
      (filters.status === 'inactive' && item.is_active === false);
    return matchesKeyword && matchesBrand && matchesStatus;
  });
});

const stats = computed(() => ({
  total: subbrands.value.length,
  active: subbrands.value.filter((item) => item.is_active !== false).length,
  inactive: subbrands.value.filter((item) => item.is_active === false).length
}));

const tableColumns = [
  { key: 'kode', label: 'Kode' },
  { key: 'nama', label: 'Sub-brand' },
  { key: 'brand_nama', label: 'Brand', render: (row) => row.brand_nama || 'Lintas brand' },
  {
    key: 'is_active',
    label: 'Status',
    render: (row) => (row.is_active === false ? 'Nonaktif' : 'Aktif')
  },
  { key: 'keterangan', label: 'Catatan', render: (row) => row.keterangan || '-' }
];

async function loadMeta() {
  const response = await getProductBrands();
  brands.value = normalizeList(unwrapResponse(response));
}

async function load() {
  loading.value = true;
  error.value = '';
  try {
    const response = await getProductSubbrands({ include_inactive: 1, limit: 1000 });
    subbrands.value = normalizeList(unwrapResponse(response));
  } catch (err) {
    error.value = normalizeError(err, 'Data sub-brand belum bisa dimuat.');
    subbrands.value = [];
  } finally {
    loading.value = false;
  }
}

function resetForm() {
  form.id_brand = '';
  form.kode = '';
  form.nama = '';
  form.keterangan = '';
  form.is_active = true;
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
  form.id_brand = row?.id_brand ? String(row.id_brand) : '';
  form.kode = row?.kode || '';
  form.nama = row?.nama || '';
  form.keterangan = row?.keterangan || '';
  form.is_active = row?.is_active !== false;
  feedback.value = '';
  actionError.value = '';
  modalOpen.value = true;
}

function closeModal() {
  modalOpen.value = false;
}

async function save() {
  saving.value = true;
  feedback.value = '';
  actionError.value = '';
  const payload = {
    id_brand: form.id_brand || null,
    kode: form.kode,
    nama: form.nama,
    keterangan: form.keterangan,
    is_active: form.is_active
  };

  try {
    if (mode.value === 'create') {
      await createProductSubbrand(payload);
      feedback.value = 'Sub-brand berhasil ditambahkan.';
      resetForm();
    } else {
      await updateProductSubbrand(selectedRow.value.id, payload);
      feedback.value = 'Sub-brand berhasil diperbarui.';
    }
    await load();
  } catch (err) {
    actionError.value = normalizeError(err, 'Sub-brand belum berhasil disimpan.');
  } finally {
    saving.value = false;
  }
}

async function setInactive() {
  if (!selectedRow.value?.id) return;
  saving.value = true;
  actionError.value = '';
  try {
    await deleteProductSubbrand(selectedRow.value.id);
    modalOpen.value = false;
    await load();
  } catch (err) {
    actionError.value = normalizeError(err, 'Sub-brand belum berhasil dinonaktifkan.');
  } finally {
    saving.value = false;
  }
}

async function setActive() {
  if (!selectedRow.value?.id) return;
  form.is_active = true;
  await save();
}

function resetFilters() {
  filters.search = '';
  filters.id_brand = '';
  filters.status = 'active';
}

onMounted(async () => {
  await loadMeta();
  await load();
});
</script>

<template>
  <div class="space-y-4">
    <PageHeader
      title="Sub-brand"
      description="Referensi sub-brand untuk produk dan mekanik promo cashback bertingkat."
    >
      <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700" @click="openCreate">
        + Sub-brand
      </button>
    </PageHeader>

    <section class="grid gap-3 md:grid-cols-3">
      <div :class="['rounded-2xl border p-4', app.isDark ? 'border-slate-800 bg-slate-900' : 'border-slate-200 bg-white']">
        <p :class="['text-xs font-semibold uppercase tracking-[0.25em]', app.isDark ? 'text-slate-400' : 'text-slate-500']">Total</p>
        <p class="mt-2 text-2xl font-bold">{{ stats.total }}</p>
      </div>
      <div :class="['rounded-2xl border p-4', app.isDark ? 'border-slate-800 bg-slate-900' : 'border-slate-200 bg-white']">
        <p :class="['text-xs font-semibold uppercase tracking-[0.25em]', app.isDark ? 'text-slate-400' : 'text-slate-500']">Aktif</p>
        <p class="mt-2 text-2xl font-bold text-emerald-400">{{ stats.active }}</p>
      </div>
      <div :class="['rounded-2xl border p-4', app.isDark ? 'border-slate-800 bg-slate-900' : 'border-slate-200 bg-white']">
        <p :class="['text-xs font-semibold uppercase tracking-[0.25em]', app.isDark ? 'text-slate-400' : 'text-slate-500']">Nonaktif</p>
        <p class="mt-2 text-2xl font-bold text-amber-400">{{ stats.inactive }}</p>
      </div>
    </section>

    <section :class="['rounded-2xl border p-4', app.isDark ? 'border-slate-800 bg-slate-900' : 'border-slate-200 bg-white']">
      <div class="grid gap-3 lg:grid-cols-[1.2fr_1fr_0.7fr_auto]">
        <AppFormField v-model="filters.search" label="Cari Sub-brand" placeholder="Kode, nama, brand, atau catatan" />
        <AppSearchSelect
          v-model="filters.id_brand"
          label="Brand"
          :options="brandOptions"
          placeholder="Semua brand"
          empty-text="Brand belum tersedia."
        />
        <label class="block">
          <span :class="['mb-1.5 block text-sm font-medium', app.isDark ? 'text-slate-300' : 'text-slate-700']">Status</span>
          <select
            v-model="filters.status"
            :class="[
              'h-[42px] w-full rounded-xl px-3 text-sm outline-none',
              app.isDark ? 'border border-slate-700 bg-slate-950 text-slate-100' : 'border border-slate-200 bg-white text-slate-900'
            ]"
          >
            <option value="active">Aktif</option>
            <option value="inactive">Nonaktif</option>
            <option value="all">Semua Status</option>
          </select>
        </label>
        <div class="flex items-end gap-2">
          <button class="rounded-xl border px-4 py-2 text-sm font-semibold" @click="load">Reload</button>
          <button class="rounded-xl border px-4 py-2 text-sm font-semibold" @click="resetFilters">Reset</button>
        </div>
      </div>
    </section>

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ error }}</section>

    <AppTable
      :rows="filteredRows"
      :columns="tableColumns"
      :loading="loading"
      :clickable-rows="true"
      empty-message="Belum ada sub-brand."
      @row-click="openEdit"
    />

    <AppModal :open="modalOpen" :title="mode === 'create' ? 'Tambah Sub-brand' : 'Edit Sub-brand'" @close="closeModal">
      <div class="space-y-4">
        <AppSearchSelect
          v-model="form.id_brand"
          label="Brand"
          :options="brandOptions"
          placeholder="Lintas brand / tidak spesifik"
          empty-text="Brand belum tersedia."
        />
        <div class="grid gap-3 md:grid-cols-2">
          <AppFormField v-model="form.nama" label="Nama Sub-brand" placeholder="Contoh: Frio, Pino, MKL Hanger" />
          <AppFormField v-model="form.kode" label="Kode" placeholder="Otomatis jika kosong" />
        </div>
        <AppFormField v-model="form.keterangan" label="Catatan" type="textarea" placeholder="Catatan promo atau cakupan produk" />
        <label class="flex items-center gap-3 text-sm">
          <input v-model="form.is_active" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-brand-600" />
          <span :class="app.isDark ? 'text-slate-200' : 'text-slate-700'">Sub-brand aktif dan bisa dipilih di master produk.</span>
        </label>

        <div v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{{ feedback }}</div>
        <div v-if="actionError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ actionError }}</div>

        <div class="flex flex-wrap gap-2">
          <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white" :disabled="saving" @click="save">
            {{ saving ? 'Menyimpan...' : mode === 'create' ? 'Simpan' : 'Update' }}
          </button>
          <button
            v-if="mode === 'edit' && selectedRow?.is_active !== false"
            class="rounded-xl border border-amber-200 px-4 py-2 text-sm font-medium text-amber-600"
            :disabled="saving"
            @click="setInactive"
          >
            Nonaktifkan
          </button>
          <button
            v-if="mode === 'edit' && selectedRow?.is_active === false"
            class="rounded-xl border border-emerald-200 px-4 py-2 text-sm font-medium text-emerald-600"
            :disabled="saving"
            @click="setActive"
          >
            Aktifkan Lagi
          </button>
        </div>
      </div>
    </AppModal>
  </div>
</template>
