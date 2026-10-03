<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { createPriceType, deletePriceType, getPriceTypes, updatePriceType } from '@/api/master';
import { useRemoteCollection } from '@/composables/useRemoteCollection';
import { normalizeError } from '@/utils/api';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const filters = reactive({ search: '' });
const { items, loading, load, error } = useRemoteCollection(() => getPriceTypes());
const modalOpen = ref(false);
const mode = ref('create');
const selectedRow = ref(null);
const form = reactive({ kode: '', nama: '' });
const feedback = ref('');
const actionError = ref('');
const saving = ref(false);

const filteredItems = computed(() => {
  const query = filters.search.trim().toLowerCase();
  if (!query) return items.value;
  return items.value.filter((item) => [item.kode, item.nama].filter(Boolean).some((value) => String(value).toLowerCase().includes(query)));
});

const columns = [
  { key: 'id', label: 'ID' },
  { key: 'kode', label: 'Kode' },
  { key: 'nama', label: 'Tipe Harga' }
];

function resetForm() {
  form.kode = '';
  form.nama = '';
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
  resetForm();
  feedback.value = '';
  actionError.value = '';
  modalOpen.value = true;
}

function openEdit(row) {
  mode.value = 'edit';
  selectedRow.value = row;
  form.kode = row?.kode || '';
  form.nama = row?.nama || '';
  feedback.value = '';
  actionError.value = '';
  modalOpen.value = true;
}

function closeModal() {
  modalOpen.value = false;
}

async function save() {
  if (!form.nama.trim()) {
    actionError.value = 'Nama tipe harga wajib diisi.';
    return;
  }

  saving.value = true;
  feedback.value = '';
  actionError.value = '';
  try {
    if (mode.value === 'create') {
      await createPriceType(form);
      feedback.value = 'Tipe harga berhasil ditambahkan.';
      resetForm();
    } else {
      await updatePriceType(selectedRow.value?.id, form);
      feedback.value = 'Tipe harga berhasil diperbarui.';
    }
    await load();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data tipe harga belum berhasil disimpan.');
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
    await deletePriceType(selectedRow.value.id);
    modalOpen.value = false;
    await load();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data tipe harga belum berhasil dihapus.');
  } finally {
    saving.value = false;
  }
}

onMounted(submit);
</script>

<template>
  <div class="space-y-4">
    <PageHeader title="Master Tipe Harga" description="Referensi tipe harga untuk customer, plafon, dan harga jual produk.">
      <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700" @click="openCreate">
        Tambah Tipe Harga
      </button>
    </PageHeader>

    <AppFilterBar
      :model-value="filters"
      :fields="[{ key: 'search', label: 'Cari tipe harga', placeholder: 'Kode atau nama tipe harga' }]"
      @update:model-value="Object.assign(filters, $event)"
      @submit="submit"
      @reset="reset"
    />

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ error }}</section>

    <AppTable :rows="filteredItems" :columns="columns" :loading="loading" :clickable-rows="true" empty-message="Belum ada tipe harga." @row-click="openEdit" />

    <AppModal :open="modalOpen" :title="mode === 'create' ? 'Tambah Tipe Harga' : 'Edit Tipe Harga'" @close="closeModal">
      <div class="space-y-4">
        <AppFormField v-model="form.kode" label="Kode" placeholder="Contoh: MT, RT, GT" />
        <AppFormField v-model="form.nama" label="Nama Tipe Harga" placeholder="Contoh: Modern Trade" />

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
