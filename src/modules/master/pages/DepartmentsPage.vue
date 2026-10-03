<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { createDepartment, deleteDepartment, getDepartments, updateDepartment } from '@/api/master';
import { useRemoteCollection } from '@/composables/useRemoteCollection';
import { normalizeError } from '@/utils/api';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const filters = reactive({ search: '' });
const { items, loading, load, error } = useRemoteCollection(() => getDepartments());
const modalOpen = ref(false);
const mode = ref('create');
const selectedRow = ref(null);
const form = reactive({
  nama: ''
});
const feedback = ref('');
const actionError = ref('');
const saving = ref(false);

const filteredItems = computed(() => {
  const query = filters.search.trim().toLowerCase();

  if (!query) {
    return items.value;
  }

  return items.value.filter((item) =>
    [item.nama]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query))
  );
});

const columns = [
  { key: 'id', label: 'ID' },
  { key: 'nama', label: 'Departemen' }
];

function submit() {
  load();
}

function reset() {
  filters.search = '';
}

function resetForm() {
  form.nama = '';
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
  form.nama = row?.nama || '';
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
      await createDepartment({ nama: form.nama });
      feedback.value = 'Departemen berhasil ditambahkan.';
    } else {
      await updateDepartment(selectedRow.value?.id, { nama: form.nama });
      feedback.value = 'Departemen berhasil diperbarui.';
    }

    await load();
    if (mode.value === 'create') {
      resetForm();
    }
  } catch (err) {
    actionError.value = normalizeError(err, 'Data departemen belum berhasil disimpan.');
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
    await deleteDepartment(selectedRow.value.id);
    modalOpen.value = false;
    await load();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data departemen belum berhasil dihapus.');
  } finally {
    saving.value = false;
  }
}

onMounted(submit);
</script>

<template>
  <div class="space-y-4">
    <PageHeader
      title="Master Departemen"
      description="Referensi departemen dari admin lama dipindah dulu ke mode baca-only agar role, jabatan, dan struktur organisasi bisa ikut dimigrasikan bertahap."
    >
      <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700" @click="openCreate">
        Tambah Departemen
      </button>
    </PageHeader>

    <AppFilterBar
      :model-value="filters"
      :fields="[{ key: 'search', label: 'Cari departemen', placeholder: 'Nama departemen' }]"
      @update:model-value="Object.assign(filters, $event)"
      @submit="submit"
      @reset="reset"
    />

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ error }}
    </section>

    <AppTable
      :rows="filteredItems"
      :columns="columns"
      :loading="loading"
      :clickable-rows="true"
      empty-message="Belum ada data departemen yang bisa ditampilkan."
      @row-click="openEdit"
    />

    <AppModal :open="modalOpen" :title="mode === 'create' ? 'Tambah Departemen' : 'Edit Departemen'" @close="closeModal">
      <div class="space-y-4">
        <AppFormField v-model="form.nama" label="Nama Departemen" placeholder="Masukkan nama departemen" />

        <div v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {{ feedback }}
        </div>
        <div v-if="actionError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {{ actionError }}
        </div>

        <div class="flex flex-wrap gap-2">
          <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white" :disabled="saving" @click="save">
            {{ saving ? 'Menyimpan...' : mode === 'create' ? 'Simpan Departemen' : 'Update Departemen' }}
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
