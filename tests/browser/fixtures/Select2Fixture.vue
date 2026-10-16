<script setup>
import { computed, onMounted, ref } from 'vue';
import AppSelect2 from '@/shared/components/AppSelect2.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppModal from '@/shared/components/AppModal.vue';
import { useAppStore } from '@/app/stores/app';
const app = useAppStore();
const number = ref(''), active = ref(false), zero = ref(0), selected = ref([7]), draft = ref(''), fee = ref('');
const disabled = ref(false), submits = ref(0), changes = ref(0), lastEvent = ref(''), modal = ref(false);
const remote = ref(''), remoteOptions = ref([]), remoteQuery = ref(''), loading = ref(false);
const filter = ref({ status: '2' }), search = ref('');
const filterFields = [{ key: 'status', label: 'Status filter', type: 'select', options: [{ value: 1, label: 'Baru' }, { value: 2, label: 'Selesai' }] }];
const drafts = Array.from({ length: 220 }, (_, i) => ({ id: `DRF-5-${String(i + 1).padStart(4, '0')}`, label: `DRF-5-${String(i + 1).padStart(4, '0')} · 2026-10-15 · ${i + 1} nota` }));
const state = computed(() => JSON.stringify({ number: number.value, numberType: typeof number.value, active: active.value, zero: zero.value, selected: selected.value, draft: draft.value, fee: fee.value, changes: changes.value, lastEvent: lastEvent.value, submits: submits.value, filter: filter.value, remote: remote.value, remoteQuery: remoteQuery.value }));
function changed(event) { changes.value++; lastEvent.value = event.target.value; }
function find(query) {
  remoteQuery.value = query; loading.value = true;
  window.setTimeout(() => { remoteOptions.value = query ? [{ value: 99, label: `Produk ${query}` }] : []; loading.value = false; }, 100);
}
onMounted(() => app.initializeTheme());
</script>
<template>
  <main class="workflow-ui mx-auto max-w-4xl space-y-5 p-4">
    <h1>Select2 compatibility</h1>
    <pre id="state" class="overflow-auto text-xs">{{ state }}</pre>
    <form id="required-form" class="space-y-4" @submit.prevent="submits++">
      <AppSelect2 label="COA wajib" v-model.number="number" required @change="changed">
        <option value="">Pilih COA</option><option value="42">1101 · Kas Besar</option><option :value="43">1102 · Kas Gudang</option>
      </AppSelect2>
      <button type="submit" class="workflow-btn">Kirim formulir</button>
    </form>
    <div class="grid gap-4 sm:grid-cols-2">
      <AppSelect2 label="Status aktif" v-model="active"><option :value="true">Aktif</option><option :value="false">Nonaktif</option></AppSelect2>
      <AppSelect2 label="Nilai nol" v-model="zero"><option :value="0">Nol</option><option :value="1">Satu</option></AppSelect2>
      <AppSelect2 label="Group principal" v-model="selected" multiple><option :value="7">Principal Tujuh</option><option :value="8">Principal Delapan</option></AppSelect2>
      <AppSelect2 label="Jenis biaya" v-model="fee"><option value="">Pilih biaya</option><option :value="1" disabled>Biaya perlu approval</option><option :value="2">Meterai</option><optgroup label="Nonaktif" disabled><option :value="3">Biaya nonaktif</option></optgroup></AppSelect2>
    </div>
    <button type="button" class="workflow-btn" @click="disabled=!disabled">Ubah fieldset</button>
    <fieldset :disabled="disabled" class="space-y-4">
      <AppSelect2 label="Pilih draf" v-model="draft"><option value="">Pilih draf</option><option v-for="d in drafts" :key="d.id" :value="d.id">{{ d.label }}</option></AppSelect2>
    </fieldset>
    <AppFilterBar v-model="filter" :fields="filterFields" />
    <AppSearchSelect label="Cari remote" v-model="remote" :options="remoteOptions" remote-search :loading="loading" clear-search-on-open @search="find" />
    <input v-model="search" aria-label="Input setelah dropdown" class="workflow-input" />
    <button type="button" class="workflow-btn" @click="modal=true">Buka modal</button>
    <AppModal :open="modal" title="Pilih data dalam modal" @close="modal=false">
      <AppSelect2 label="Draf dalam modal" v-model="draft"><option value="">Pilih draf</option><option v-for="d in drafts" :key="d.id" :value="d.id">{{ d.label }}</option></AppSelect2>
    </AppModal>
  </main>
</template>
