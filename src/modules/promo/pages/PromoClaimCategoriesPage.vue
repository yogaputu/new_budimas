<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import {
  createPromoClaimCategory,
  deletePromoClaimCategory,
  getPromoClaimCategories,
  updatePromoClaimCategory
} from '@/api/promo';
import { useRemoteCollection } from '@/composables/useRemoteCollection';
import { normalizeError } from '@/utils/api';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const filters = reactive({ search: '' });
const { items, loading, load, error } = useRemoteCollection(() => getPromoClaimCategories());
const modalOpen = ref(false);
const mode = ref('create');
const selectedRow = ref(null);
const saving = ref(false);
const feedback = ref('');
const actionError = ref('');
const form = reactive({
  nama: '',
  deskripsi: ''
});

const columns = [
  { key: 'id', label: 'ID' },
  { key: 'nama', label: 'Kategori Klaim' },
  { key: 'deskripsi', label: 'Deskripsi' }
];

const filteredItems = computed(() => {
  const query = filters.search.trim().toLowerCase();
  if (!query) return items.value;

  return items.value.filter((item) =>
    [item.nama, item.deskripsi]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query))
  );
});

function resetForm() {
  form.nama = '';
  form.deskripsi = '';
}

function resetFilters() {
  filters.search = '';
}

function submit() {
  load();
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
  form.nama = row?.nama || '';
  form.deskripsi = row?.deskripsi || '';
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

  try {
    if (mode.value === 'create') {
      await createPromoClaimCategory({
        nama: form.nama,
        deskripsi: form.deskripsi
      });
      feedback.value = 'Kategori klaim promo berhasil ditambahkan.';
      resetForm();
    } else {
      await updatePromoClaimCategory(selectedRow.value?.id, {
        nama: form.nama,
        deskripsi: form.deskripsi
      });
      feedback.value = 'Kategori klaim promo berhasil diperbarui.';
    }

    await load();
  } catch (err) {
    actionError.value = normalizeError(err, 'Kategori klaim promo belum berhasil disimpan.');
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
    await deletePromoClaimCategory(selectedRow.value.id);
    modalOpen.value = false;
    await load();
  } catch (err) {
    actionError.value = normalizeError(err, 'Kategori klaim promo belum berhasil dihapus.');
  } finally {
    saving.value = false;
  }
}

onMounted(submit);
</script>

<template>
  <div class="space-y-4">
    <PageHeader
      title="Master Kategori Klaim Promo"
      description="Kategori klaim promo sekarang bisa dikelola langsung dari frontend baru, jadi tim tidak perlu isi manual lewat database saat menyiapkan pengajuan klaim."
    >
      <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700" @click="openCreate">
        Tambah Kategori
      </button>
    </PageHeader>

    <AppFilterBar
      :model-value="filters"
      :fields="[{ key: 'search', label: 'Cari kategori', placeholder: 'Nama atau deskripsi kategori klaim' }]"
      @update:model-value="Object.assign(filters, $event)"
      @submit="submit"
      @reset="resetFilters"
    />

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ error }}
    </section>

    <AppTable
      :rows="filteredItems"
      :columns="columns"
      :loading="loading"
      :clickable-rows="true"
      empty-message="Belum ada kategori klaim promo."
      @row-click="openEdit"
    />

    <AppModal :open="modalOpen" :title="mode === 'create' ? 'Tambah Kategori Klaim Promo' : 'Edit Kategori Klaim Promo'" @close="closeModal">
      <div class="space-y-4">
        <AppFormField v-model="form.nama" label="Nama Kategori" />
        <AppFormField v-model="form.deskripsi" label="Deskripsi" type="textarea" />

        <div v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {{ feedback }}
        </div>

        <div v-if="actionError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {{ actionError }}
        </div>

        <div class="flex flex-wrap gap-2">
          <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white" :disabled="saving" @click="save">
            {{ saving ? 'Menyimpan...' : mode === 'create' ? 'Simpan' : 'Update' }}
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
