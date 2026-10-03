<script setup>
import { computed, onMounted, ref } from 'vue';
import { createRegion, deleteRegion, getRegionsLevel1, getRegionsLevel2, getRegionsLevel3, getRegionsLevel4, updateRegion } from '@/api/master';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const loading = ref({
  level1: false,
  level2: false,
  level3: false,
  level4: false
});

const errorMessage = ref('');
const level1Rows = ref([]);
const level2Rows = ref([]);
const level3Rows = ref([]);
const level4Rows = ref([]);

const selectedLevel1 = ref(null);
const selectedLevel2 = ref(null);
const selectedLevel3 = ref(null);
const modalOpen = ref(false);
const modalLevel = ref(1);
const modalMode = ref('create');
const modalSaving = ref(false);
const modalFeedback = ref('');
const modalError = ref('');
const regionForm = ref({
  nama: ''
});
const selectedRegionRow = ref(null);

const hierarchySummary = computed(() => [
  { label: 'Provinsi', value: selectedLevel1.value?.nama || '-' },
  { label: 'Kab/Kota', value: selectedLevel2.value?.nama || '-' },
  { label: 'Kecamatan', value: selectedLevel3.value?.nama || '-' }
]);

const columns = [
  { key: 'id', label: 'ID' },
  { key: 'nama', label: 'Nama Wilayah' }
];

const modalTitle = computed(() => {
  const labels = {
    1: 'Provinsi',
    2: 'Kabupaten/Kota',
    3: 'Kecamatan',
    4: 'Kelurahan'
  };

  return `${modalMode.value === 'create' ? 'Tambah' : 'Edit'} ${labels[modalLevel.value]}`;
});

async function loadLevel1() {
  loading.value.level1 = true;
  errorMessage.value = '';

  try {
    const response = await getRegionsLevel1();
    level1Rows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Data wilayah level 1 belum bisa dimuat.');
    level1Rows.value = [];
  } finally {
    loading.value.level1 = false;
  }
}

async function refreshLevel(level) {
  if (level === 1) {
    await loadLevel1();
    return;
  }

  if (level === 2 && selectedLevel1.value?.id) {
    await selectLevel1(selectedLevel1.value);
    return;
  }

  if (level === 3 && selectedLevel2.value?.id) {
    await selectLevel2(selectedLevel2.value);
    return;
  }

  if (level === 4 && selectedLevel3.value?.id) {
    await selectLevel3(selectedLevel3.value);
  }
}

async function selectLevel1(row) {
  selectedLevel1.value = row;
  selectedLevel2.value = null;
  selectedLevel3.value = null;
  level3Rows.value = [];
  level4Rows.value = [];
  loading.value.level2 = true;
  errorMessage.value = '';

  try {
    const response = await getRegionsLevel2(row.id);
    level2Rows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Data kabupaten/kota belum bisa dimuat.');
    level2Rows.value = [];
  } finally {
    loading.value.level2 = false;
  }
}

async function selectLevel2(row) {
  selectedLevel2.value = row;
  selectedLevel3.value = null;
  level4Rows.value = [];
  loading.value.level3 = true;
  errorMessage.value = '';

  try {
    const response = await getRegionsLevel3(row.id);
    level3Rows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Data kecamatan belum bisa dimuat.');
    level3Rows.value = [];
  } finally {
    loading.value.level3 = false;
  }
}

async function selectLevel3(row) {
  selectedLevel3.value = row;
  loading.value.level4 = true;
  errorMessage.value = '';

  try {
    const response = await getRegionsLevel4(row.id);
    level4Rows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Data kelurahan belum bisa dimuat.');
    level4Rows.value = [];
  } finally {
    loading.value.level4 = false;
  }
}

function openCreate(level) {
  modalLevel.value = level;
  modalMode.value = 'create';
  selectedRegionRow.value = null;
  regionForm.value = { nama: '' };
  modalFeedback.value = '';
  modalError.value = '';
  modalOpen.value = true;
}

function openEdit(level, row) {
  modalLevel.value = level;
  modalMode.value = 'edit';
  selectedRegionRow.value = row;
  regionForm.value = { nama: row?.nama || '' };
  modalFeedback.value = '';
  modalError.value = '';
  modalOpen.value = true;
}

function closeModal() {
  modalOpen.value = false;
}

function buildRegionPayload() {
  const payload = {
    nama: regionForm.value.nama
  };

  if (modalLevel.value === 2) {
    payload.id_wilayah1 = selectedLevel1.value?.id || '';
  }

  if (modalLevel.value === 3) {
    payload.id_wilayah2 = selectedLevel2.value?.id || '';
  }

  if (modalLevel.value === 4) {
    payload.id_wilayah3 = selectedLevel3.value?.id || '';
  }

  return payload;
}

async function saveRegion() {
  modalSaving.value = true;
  modalFeedback.value = '';
  modalError.value = '';

  try {
    if (modalMode.value === 'create') {
      await createRegion(modalLevel.value, buildRegionPayload());
      modalFeedback.value = 'Wilayah berhasil ditambahkan.';
      regionForm.value.nama = '';
    } else {
      await updateRegion(modalLevel.value, selectedRegionRow.value?.id, buildRegionPayload());
      modalFeedback.value = 'Wilayah berhasil diperbarui.';
    }

    await refreshLevel(modalLevel.value);
  } catch (error) {
    modalError.value = normalizeError(error, 'Data wilayah belum berhasil disimpan.');
  } finally {
    modalSaving.value = false;
  }
}

async function removeRegion() {
  if (!selectedRegionRow.value?.id) {
    return;
  }

  modalSaving.value = true;
  modalFeedback.value = '';
  modalError.value = '';

  try {
    await deleteRegion(modalLevel.value, selectedRegionRow.value.id);
    modalOpen.value = false;
    await refreshLevel(modalLevel.value);
  } catch (error) {
    modalError.value = normalizeError(error, 'Data wilayah belum berhasil dihapus.');
  } finally {
    modalSaving.value = false;
  }
}

onMounted(loadLevel1);
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Master Wilayah"
      description="Struktur wilayah dimigrasikan bertahap dengan pola hierarki level 1 sampai 4 agar referensi cabang, customer, sales, dan principal tetap terbaca."
    >
      <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50" @click="loadLevel1">
        Refresh wilayah
      </button>
    </PageHeader>

    <section v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ errorMessage }}
    </section>

    <section class="grid gap-4 md:grid-cols-3">
      <article v-for="item in hierarchySummary" :key="item.label" class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">{{ item.label }}</p>
        <p class="mt-3 text-base font-semibold text-slate-900">{{ item.value }}</p>
      </article>
    </section>

    <div class="grid gap-6 xl:grid-cols-2">
      <section>
        <div class="mb-3 flex items-center justify-between gap-3">
          <div>
          <h3 class="text-lg font-semibold text-slate-900">Wilayah 1: Provinsi</h3>
          <p class="mt-1 text-sm text-slate-500">Klik salah satu provinsi untuk memuat daftar kabupaten/kota di kolom berikutnya.</p>
          </div>
          <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700" @click="openCreate(1)">
            Tambah
          </button>
        </div>
        <AppTable
          :rows="level1Rows"
          :columns="columns"
          :loading="loading.level1"
          :clickable-rows="true"
          empty-message="Belum ada data provinsi."
          @row-click="(row) => { selectLevel1(row); openEdit(1, row); }"
        />
      </section>

      <section>
        <div class="mb-3 flex items-center justify-between gap-3">
          <div>
          <h3 class="text-lg font-semibold text-slate-900">Wilayah 2: Kabupaten/Kota</h3>
          <p class="mt-1 text-sm text-slate-500">Data akan muncul setelah memilih provinsi dari tabel sebelah kiri.</p>
          </div>
          <button
            class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:bg-slate-300"
            :disabled="!selectedLevel1"
            @click="openCreate(2)"
          >
            Tambah
          </button>
        </div>
        <AppTable
          :rows="level2Rows"
          :columns="columns"
          :loading="loading.level2"
          :clickable-rows="true"
          empty-message="Pilih provinsi terlebih dahulu."
          @row-click="(row) => { selectLevel2(row); openEdit(2, row); }"
        />
      </section>
    </div>

    <div class="grid gap-6 xl:grid-cols-2">
      <section>
        <div class="mb-3 flex items-center justify-between gap-3">
          <div>
          <h3 class="text-lg font-semibold text-slate-900">Wilayah 3: Kecamatan</h3>
          <p class="mt-1 text-sm text-slate-500">Klik kecamatan untuk memuat kelurahan di level terakhir.</p>
          </div>
          <button
            class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:bg-slate-300"
            :disabled="!selectedLevel2"
            @click="openCreate(3)"
          >
            Tambah
          </button>
        </div>
        <AppTable
          :rows="level3Rows"
          :columns="columns"
          :loading="loading.level3"
          :clickable-rows="true"
          empty-message="Pilih kabupaten/kota terlebih dahulu."
          @row-click="(row) => { selectLevel3(row); openEdit(3, row); }"
        />
      </section>

      <section>
        <div class="mb-3 flex items-center justify-between gap-3">
          <div>
          <h3 class="text-lg font-semibold text-slate-900">Wilayah 4: Kelurahan</h3>
          <p class="mt-1 text-sm text-slate-500">Level paling detail dari struktur wilayah yang dipakai modul legacy.</p>
          </div>
          <button
            class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:bg-slate-300"
            :disabled="!selectedLevel3"
            @click="openCreate(4)"
          >
            Tambah
          </button>
        </div>
        <AppTable
          :rows="level4Rows"
          :columns="columns"
          :loading="loading.level4"
          :clickable-rows="true"
          empty-message="Pilih kecamatan terlebih dahulu."
          @row-click="(row) => openEdit(4, row)"
        />
      </section>
    </div>

    <AppModal :open="modalOpen" :title="modalTitle" @close="closeModal">
      <div class="space-y-4">
        <AppFormField v-model="regionForm.nama" label="Nama Wilayah" placeholder="Masukkan nama wilayah" />

        <div v-if="modalFeedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {{ modalFeedback }}
        </div>
        <div v-if="modalError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {{ modalError }}
        </div>

        <div class="flex flex-wrap gap-2">
          <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white" :disabled="modalSaving" @click="saveRegion">
            {{ modalSaving ? 'Menyimpan...' : modalMode === 'create' ? 'Simpan Wilayah' : 'Update Wilayah' }}
          </button>
          <button
            v-if="modalMode === 'edit'"
            class="rounded-xl border border-rose-200 px-4 py-2 text-sm font-medium text-rose-700"
            :disabled="modalSaving"
            @click="removeRegion"
          >
            Hapus
          </button>
        </div>
      </div>
    </AppModal>
  </div>
</template>
