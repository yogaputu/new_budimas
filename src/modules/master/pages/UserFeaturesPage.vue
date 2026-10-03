<script setup>
import { computed, onMounted, ref } from 'vue';
import { createFeatureUserAssignment, deleteFeatureUserAssignment, getFeatureUserAvailable, getFeatureUsers, getUsers } from '@/api/master';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const users = ref([]);
const selectedUserId = ref('');
const assignedRows = ref([]);
const availableRows = ref([]);
const loading = ref(false);
const feedback = ref('');
const errorMessage = ref('');
const featureToAdd = ref('');

const userOptions = computed(() =>
  users.value.map((item) => ({
    value: String(item.id),
    label: `${item.username || item.nama || 'User'}${item.nama_jabatan ? ` - ${item.nama_jabatan}` : ''}`
  }))
);

const availableOptions = computed(() =>
  availableRows.value.map((item) => ({
    value: String(item.id),
    label: item.nama || `Fitur ${item.id}`
  }))
);

async function loadUsers() {
  const response = await getUsers();
  users.value = normalizeList(unwrapResponse(response));
}

async function loadAssignments() {
  if (!selectedUserId.value) {
    assignedRows.value = [];
    availableRows.value = [];
    return;
  }

  loading.value = true;
  feedback.value = '';
  errorMessage.value = '';

  try {
    const [assignedResponse, availableResponse] = await Promise.all([
      getFeatureUsers(),
      getFeatureUserAvailable(selectedUserId.value)
    ]);

    assignedRows.value = normalizeList(unwrapResponse(assignedResponse)).filter((item) => String(item.id_user) === String(selectedUserId.value));
    availableRows.value = normalizeList(unwrapResponse(availableResponse));
  } catch (err) {
    errorMessage.value = normalizeError(err, 'Fitur user belum bisa dimuat.');
    assignedRows.value = [];
    availableRows.value = [];
  } finally {
    loading.value = false;
  }
}

async function addFeature() {
  if (!selectedUserId.value || !featureToAdd.value) return;
  loading.value = true;
  feedback.value = '';
  errorMessage.value = '';
  try {
    await createFeatureUserAssignment({
      id_user: selectedUserId.value,
      id_fitur: featureToAdd.value
    });
    featureToAdd.value = '';
    feedback.value = 'Fitur user berhasil ditambahkan.';
    await loadAssignments();
  } catch (err) {
    errorMessage.value = normalizeError(err, 'Fitur user belum berhasil ditambahkan.');
  } finally {
    loading.value = false;
  }
}

async function removeFeature(row) {
  loading.value = true;
  feedback.value = '';
  errorMessage.value = '';
  try {
    await deleteFeatureUserAssignment(row.id);
    feedback.value = 'Fitur user berhasil dihapus.';
    await loadAssignments();
  } catch (err) {
    errorMessage.value = normalizeError(err, 'Fitur user belum berhasil dihapus.');
  } finally {
    loading.value = false;
  }
}

onMounted(loadUsers);
</script>

<template>
  <div class="space-y-6">
    <PageHeader title="Hak Akses User" description="Kelola assignment fitur per user untuk melengkapi migrasi admin ke mode operasional." />

    <section class="panel p-5">
      <div class="grid gap-4 md:grid-cols-[1fr_auto]">
        <AppSearchSelect v-model="selectedUserId" label="User" placeholder="Pilih user" :options="userOptions" empty-text="User belum tersedia." />
        <button class="self-end rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50" @click="loadAssignments">
          Muat Fitur
        </button>
      </div>
    </section>

    <section class="panel p-5">
      <div class="grid gap-4 md:grid-cols-[1fr_auto]">
        <AppSearchSelect v-model="featureToAdd" label="Fitur Tersedia" placeholder="Pilih fitur" :options="availableOptions" empty-text="Tidak ada fitur tersedia." />
        <button class="self-end rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700" @click="addFeature">
          Tambah Fitur
        </button>
      </div>
    </section>

    <section v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{{ feedback }}</section>
    <section v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ errorMessage }}</section>

    <div class="grid gap-6 xl:grid-cols-2">
      <section>
        <div class="mb-3">
          <h3 class="text-lg font-semibold text-slate-900">Fitur Aktif User</h3>
          <p class="mt-1 text-sm text-slate-500">Klik baris untuk menghapus assignment fitur dari user terpilih.</p>
        </div>
        <AppTable
          :rows="assignedRows"
          :columns="[
            { key: 'id', label: 'ID' },
            { key: 'nama_fitur', label: 'Fitur' }
          ]"
          :loading="loading"
          :clickable-rows="true"
          empty-message="Belum ada assignment fitur user."
          @row-click="removeFeature"
        />
      </section>

      <section>
        <div class="mb-3">
          <h3 class="text-lg font-semibold text-slate-900">Fitur Tersedia</h3>
          <p class="mt-1 text-sm text-slate-500">Daftar fitur yang belum terpasang pada user terpilih.</p>
        </div>
        <AppTable
          :rows="availableRows"
          :columns="[
            { key: 'id', label: 'ID' },
            { key: 'nama', label: 'Fitur' }
          ]"
          :loading="loading"
          empty-message="Tidak ada fitur tersedia."
        />
      </section>
    </div>
  </div>
</template>
