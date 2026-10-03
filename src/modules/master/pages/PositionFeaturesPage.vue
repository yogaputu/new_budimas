<script setup>
import { computed, onMounted, ref } from 'vue';
import { createFeaturePositionAssignment, deleteFeaturePositionAssignment, getFeaturePositionAssignments, getFeaturePositionAvailable, getPositions } from '@/api/master';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const positions = ref([]);
const selectedPositionId = ref('');
const assignedRows = ref([]);
const availableRows = ref([]);
const loading = ref(false);
const feedback = ref('');
const errorMessage = ref('');
const featureToAdd = ref('');

const positionOptions = computed(() =>
  positions.value.map((item) => ({
    value: String(item.id),
    label: `${item.kode || '-'} - ${item.nama || 'Jabatan'}`
  }))
);

const availableOptions = computed(() =>
  availableRows.value.map((item) => ({
    value: String(item.id),
    label: item.nama || `Fitur ${item.id}`
  }))
);

async function loadPositions() {
  const response = await getPositions();
  positions.value = normalizeList(unwrapResponse(response));
}

async function loadAssignments() {
  if (!selectedPositionId.value) {
    assignedRows.value = [];
    availableRows.value = [];
    return;
  }

  loading.value = true;
  feedback.value = '';
  errorMessage.value = '';

  try {
    const [assignedResponse, availableResponse] = await Promise.all([
      getFeaturePositionAssignments(selectedPositionId.value),
      getFeaturePositionAvailable(selectedPositionId.value)
    ]);

    assignedRows.value = normalizeList(unwrapResponse(assignedResponse));
    availableRows.value = normalizeList(unwrapResponse(availableResponse));
  } catch (err) {
    errorMessage.value = normalizeError(err, 'Fitur jabatan belum bisa dimuat.');
    assignedRows.value = [];
    availableRows.value = [];
  } finally {
    loading.value = false;
  }
}

async function addFeature() {
  if (!selectedPositionId.value || !featureToAdd.value) return;
  loading.value = true;
  feedback.value = '';
  errorMessage.value = '';
  try {
    await createFeaturePositionAssignment({
      id_jabatan: selectedPositionId.value,
      id_fitur: featureToAdd.value
    });
    featureToAdd.value = '';
    feedback.value = 'Fitur jabatan berhasil ditambahkan.';
    await loadAssignments();
  } catch (err) {
    errorMessage.value = normalizeError(err, 'Fitur jabatan belum berhasil ditambahkan.');
  } finally {
    loading.value = false;
  }
}

async function removeFeature(row) {
  loading.value = true;
  feedback.value = '';
  errorMessage.value = '';
  try {
    await deleteFeaturePositionAssignment(row.id);
    feedback.value = 'Fitur jabatan berhasil dihapus.';
    await loadAssignments();
  } catch (err) {
    errorMessage.value = normalizeError(err, 'Fitur jabatan belum berhasil dihapus.');
  } finally {
    loading.value = false;
  }
}

onMounted(loadPositions);
</script>

<template>
  <div class="space-y-6">
    <PageHeader title="Hak Akses Jabatan" description="Kelola mapping fitur per jabatan agar role admin lama bisa benar-benar dibawa ke shell baru." />

    <section class="panel p-5">
      <div class="grid gap-4 md:grid-cols-[1fr_auto]">
        <AppSearchSelect v-model="selectedPositionId" label="Jabatan" placeholder="Pilih jabatan" :options="positionOptions" empty-text="Jabatan belum tersedia." />
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
          <h3 class="text-lg font-semibold text-slate-900">Fitur Aktif Jabatan</h3>
          <p class="mt-1 text-sm text-slate-500">Klik baris untuk menghapus assignment fitur dari jabatan terpilih.</p>
        </div>
        <AppTable
          :rows="assignedRows"
          :columns="[
            { key: 'id', label: 'ID' },
            { key: 'nama_fitur', label: 'Fitur' }
          ]"
          :loading="loading"
          :clickable-rows="true"
          empty-message="Belum ada assignment fitur jabatan."
          @row-click="removeFeature"
        />
      </section>

      <section>
        <div class="mb-3">
          <h3 class="text-lg font-semibold text-slate-900">Fitur Tersedia</h3>
          <p class="mt-1 text-sm text-slate-500">Daftar fitur yang belum dipasang pada jabatan terpilih.</p>
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
