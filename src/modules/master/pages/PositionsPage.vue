<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { createPosition, deletePosition, getDepartments, getPositions, updatePosition } from '@/api/master';
import { useRemoteCollection } from '@/composables/useRemoteCollection';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const filters = reactive({ search: '' });
const { items, loading, load, error } = useRemoteCollection(() => getPositions());
const departments = ref([]);
const modalOpen = ref(false);
const mode = ref('create');
const selectedRow = ref(null);
const form = reactive({
  kode: '',
  nama: '',
  departemen_id: ''
});
const feedback = ref('');
const actionError = ref('');
const saving = ref(false);

const departmentOptions = computed(() =>
  departments.value.map((item) => ({
    value: String(item.id),
    label: `${item.id} - ${item.nama || 'Departemen'}`
  }))
);

const departmentMap = computed(() =>
  departments.value.reduce((acc, item) => {
    acc[String(item.id)] = item.nama || `Departemen ${item.id}`;
    return acc;
  }, {})
);

const filteredItems = computed(() => {
  const query = filters.search.trim().toLowerCase();

  if (!query) {
    return items.value;
  }

  return items.value.filter((item) =>
    [item.kode, item.nama, departmentMap.value[String(item.departemen_id)]]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query))
  );
});

const tableRows = computed(() =>
  filteredItems.value.map((item) => ({
    ...item,
    nama_departemen: departmentMap.value[String(item.departemen_id)] || '-'
  }))
);

const columns = [
  { key: 'id', label: 'ID' },
  { key: 'kode', label: 'Kode' },
  { key: 'nama', label: 'Jabatan' },
  { key: 'nama_departemen', label: 'Departemen' }
];

function submit() {
  load();
}

function reset() {
  filters.search = '';
}

function resetForm() {
  form.kode = '';
  form.nama = '';
  form.departemen_id = '';
}

async function loadOptions() {
  const response = await getDepartments();
  departments.value = normalizeList(unwrapResponse(response));
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
  form.departemen_id = row?.departemen_id ? String(row.departemen_id) : '';
  modalOpen.value = true;
}

function closeModal() {
  modalOpen.value = false;
}

async function save() {
  saving.value = true;
  feedback.value = '';
  actionError.value = '';

  try {
    if (mode.value === 'create') {
      await createPosition(form);
      feedback.value = 'Jabatan berhasil ditambahkan.';
      resetForm();
    } else {
      await updatePosition(selectedRow.value?.id, form);
      feedback.value = 'Jabatan berhasil diperbarui.';
    }

    await load();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data jabatan belum berhasil disimpan.');
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
    await deletePosition(selectedRow.value.id);
    modalOpen.value = false;
    await load();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data jabatan belum berhasil dihapus.');
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  await Promise.all([submit(), loadOptions()]);
});
</script>

<template>
  <div class="space-y-4">
    <PageHeader
      title="Master Jabatan"
      description="Master jabatan sekarang sudah benar-benar siap dipakai admin, lengkap dengan relasi departemen yang lebih jelas."
    >
      <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700" @click="openCreate">
        Tambah Jabatan
      </button>
    </PageHeader>

    <AppFilterBar
      :model-value="filters"
      :fields="[{ key: 'search', label: 'Cari jabatan', placeholder: 'Kode, nama jabatan, atau departemen' }]"
      @update:model-value="Object.assign(filters, $event)"
      @submit="submit"
      @reset="reset"
    />

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ error }}
    </section>

    <AppTable
      :rows="tableRows"
      :columns="columns"
      :loading="loading"
      :clickable-rows="true"
      empty-message="Belum ada data jabatan yang bisa ditampilkan."
      @row-click="openEdit"
    />

    <AppModal :open="modalOpen" :title="mode === 'create' ? 'Tambah Jabatan' : 'Edit Jabatan'" @close="closeModal">
      <div class="space-y-4">
        <AppFormField v-model="form.kode" label="Kode Jabatan" placeholder="Contoh: ADM" />
        <AppFormField v-model="form.nama" label="Nama Jabatan" placeholder="Masukkan nama jabatan" />
        <AppSearchSelect
          v-model="form.departemen_id"
          label="Departemen"
          placeholder="Pilih departemen"
          :options="departmentOptions"
          empty-text="Departemen belum tersedia."
        />

        <div v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {{ feedback }}
        </div>
        <div v-if="actionError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {{ actionError }}
        </div>

        <div class="flex flex-wrap gap-2">
          <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white" :disabled="saving" @click="save">
            {{ saving ? 'Menyimpan...' : mode === 'create' ? 'Simpan Jabatan' : 'Update Jabatan' }}
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
