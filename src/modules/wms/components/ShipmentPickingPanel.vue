<script setup>
import AppSelect2 from '@/shared/components/AppSelect2.vue';
import { computed, onMounted, ref, watch } from 'vue';
import api from '@/api/axios';
import { unwrapResponse, normalizeError } from '@/utils/api';
import { pickingGroups } from '@/utils/shipmentPicking';
import { openPrintHtml } from '@/utils/printTemplates';
import { buildPickingReferenceHtml, pickingPrintDocument } from '@/utils/pickingReferencePrint';
import { useAuthStore } from '@/stores/auth';
const authStore = useAuthStore();
const reference = ref(''), mode = ref('variant'), rows = ref([]), document = ref(null), drafts = ref([]);
const busy = ref(false), error = ref(''), feedback = ref(''), revisionNote = ref(''), picker = ref('');
const groups = computed(() => pickingGroups(rows.value, mode.value));
const state = computed(() => document.value?.status || '');
const editable = computed(() => document.value && !document.value.task_statuses?.some(s => !['DRAFT','PICKING','PICKED','PICKING_VOID'].includes(s)));
const shortages = computed(() => rows.value.some(r => Number(r.picked_quantity) < Number(r.required_quantity)));
watch(reference, value => { if (document.value && value !== document.value.shipment_reference) { document.value = null; rows.value = []; } });
async function run(action) { busy.value = true; error.value = ''; try { await action(); } catch (e) { error.value = normalizeError(e, 'Proses belum berhasil.'); } finally { busy.value = false; } }
async function refreshDraft() {
  const data = unwrapResponse(await api.get(`/api/picking/picking/draft-detail/${encodeURIComponent(reference.value.trim())}`));
  document.value = data.document; reference.value = data.document.shipment_reference;
  rows.value = data.items.map(r => ({ ...r, qty: Math.max(0, Math.min(Number(r.required_quantity)-Number(r.picked_quantity), Number(r.rack_available_quantity ?? r.required_quantity))), rack: r.rak_tetap }));
}
function load() { document.value = null; rows.value = []; if (!reference.value.trim()) return; return run(refreshDraft); }
function scan(row) { return run(async () => {
  const result = unwrapResponse(await api.post('/api/picking/picking/scan-rak', {
    shipment_reference: reference.value, nota: reference.value, wms_task_detail_id: row.wms_task_detail_id,
    kode_rak: row.rack, kode_barang: row.product_code, batch: row.batch, expired_date: row.expired_date || row.expired,
    qty_pcs: Number(row.qty)
  }));
  if (result.status !== 'OK') throw new Error(result.msg || 'Stok belum mencukupi.');
  feedback.value = result.msg; await refreshDraft();
}); }
function finalize() { return run(async () => {
  const result = unwrapResponse(await api.post('/api/picking/picking/finalize', { nota: reference.value, task_ids: document.value.task_ids, picker_name: picker.value }));
  feedback.value = result.msg || 'Draf masuk checker.'; await refreshDraft();
}); }
function requestRevision() { if (!window.confirm('Ajukan nota yang kurang picked ke Revisi Faktur? Picking draf ditahan sampai revisi selesai.')) return; return run(async () => {
  const result = unwrapResponse(await api.post('/api/picking/picking/request-revision', { shipment_reference: reference.value, note: revisionNote.value }));
  feedback.value = result.message; await refreshDraft();
}); }
function printDraft(mode) {
  try {
    const data = pickingPrintDocument(reference.value, rows.value, document.value);
    if (!openPrintHtml(reference.value, buildPickingReferenceHtml([data], mode, { printedBy: authStore.userName }))) error.value = 'Izinkan popup untuk mencetak.';
  } catch (e) { error.value = normalizeError(e, 'Cetak belum berhasil.'); }
}
onMounted(() => run(async () => { const data = unwrapResponse(await api.get('/api/picking/picking/shipments')); drafts.value = data.data || data; }));
</script>

<template>
  <section class="workflow-ui workflow-card space-y-5" :aria-busy="busy">
    <header>
      <h2 class="workflow-heading">Picking Draf Kiriman</h2>
      <p class="workflow-caption mt-1">Scan QR draf kiriman atau pilih draf tersimpan. Alokasi barang tetap per nota; seluruh barang harus melalui checker.</p>
    </header>
    <div class="workflow-inset grid items-end gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
      <label class="workflow-label">Pilih draf<AppSelect2 aria-label="Pilih draf" v-model="reference"  :disabled="busy" @change="load"><option value="">Pilih draf…</option><option v-for="d in drafts" :key="d.reference" :value="d.reference">{{ d.reference }} · {{ d.delivering_date }} · {{ d.note_count }} nota</option></AppSelect2></label>
      <label class="workflow-label">Scan / referensi draf<input v-model="reference" class="workflow-input" placeholder="DRF-1-123 atau QR draf kiriman" :disabled="busy" @keyup.enter="load" /></label>
      <button class="workflow-btn workflow-btn-primary" :disabled="busy || !reference" @click="load">Muat draf</button>
    </div>
    <p v-if="error" role="alert" class="workflow-notice workflow-notice-error">{{ error }}</p>
    <p v-if="feedback" role="status" class="workflow-notice workflow-notice-success">{{ feedback }}</p>
    <template v-if="document">
      <div class="workflow-toolbar">
        <div class="min-w-0">
          <p class="workflow-caption">Draf kiriman</p>
          <div class="mt-1 flex flex-wrap items-center gap-2"><strong class="break-all text-base">{{ document.shipment_reference }}</strong><span class="workflow-badge">{{ state }}</span></div>
        </div>
        <label class="workflow-label w-full sm:w-48">Tampilan <AppSelect2 aria-label="Tampilan" v-model="mode" ><option value="variant">By variant</option><option value="nota">By nota</option></AppSelect2></label>
      </div>
      <div class="workflow-actions"><button class="workflow-btn" :disabled="busy" @click="printDraft('qr')">Cetak QR draf</button><button class="workflow-btn" :disabled="busy" @click="printDraft('nota')">Cetak By Nota</button><button class="workflow-btn" :disabled="busy" @click="printDraft('variant')">Cetak By Varian</button></div>
      <p v-if="document.task_statuses?.includes('REVISION_REQUIRED')" class="workflow-notice workflow-notice-warning">Ditahan: selesaikan Revisi Faktur ERP. Sesuaikan qty dengan picked atau pertahankan qty untuk stok susulan. Nota seluruhnya 0 tetap ditahan.</p>
      <article v-for="group in groups" :key="group.key" class="min-w-0 space-y-3">
        <div class="workflow-toolbar">
          <h3 class="min-w-0 break-words font-semibold">{{ group.title }}</h3>
          <div class="flex flex-wrap gap-2 text-xs"><span class="workflow-badge">Order {{ group.required }} PCS</span><span class="workflow-badge">Picked {{ group.picked }} PCS</span><span class="workflow-badge">Kurang {{ Math.max(0, group.required-group.picked) }} PCS</span></div>
        </div>
        <div class="workflow-table-wrap" tabindex="0" aria-label="Rincian picking; geser untuk melihat semua kolom">
        <table class="workflow-table workflow-picking-table"><thead><tr><th scope="col">Nota</th><th scope="col">Barang</th><th scope="col">Stok Ready</th><th scope="col">Order / Picked</th><th scope="col">Rak / Batch</th><th scope="col">Ambil (PCS)</th><th scope="col">Aksi</th></tr></thead>
          <tbody><tr v-for="row in group.rows" :key="row.wms_task_detail_id">
            <td class="whitespace-nowrap font-medium">{{ row.nota || row.no_order }}</td><td><strong class="text-xs">{{ row.product_code }}</strong><p class="mt-1 min-w-36">{{ row.product_name }}</p></td><td class="whitespace-nowrap tabular-nums">{{ row.stok_ready ?? "-" }} PCS</td><td class="whitespace-nowrap tabular-nums">{{ row.required_quantity }} / {{ row.picked_quantity }}</td>
            <td><input v-model="row.rack" class="workflow-input min-w-44" :disabled="!editable || busy" :aria-label="`Rak ${row.product_code}`" /><p class="workflow-caption mt-1">Batch: {{ row.batch || '-' }}</p></td>
            <td><input v-model="row.qty" class="workflow-input w-24" type="number" min="1" step="1" :max="row.required_quantity-row.picked_quantity" :disabled="!editable || busy" :aria-label="`Qty ${row.product_code}`" /></td>
            <td><button class="workflow-btn whitespace-nowrap" :disabled="busy || !editable || !row.rack || !Number.isInteger(Number(row.qty)) || Number(row.qty)<=0 || Number(row.qty)>row.required_quantity-row.picked_quantity" @click="scan(row)">Pick nota ini</button></td>
          </tr></tbody></table>
        </div>
      </article>
      <div v-if="editable" class="workflow-inset space-y-4"><label class="workflow-label max-w-lg">Nama picker<input v-model="picker" class="workflow-input" /></label>
        <button class="workflow-btn workflow-btn-primary" :disabled="busy || shortages || !rows.some(r=>Number(r.picked_quantity)>0) || !picker.trim()" @click="finalize">Selesai Picking → Checker</button>
        <div v-if="shortages" class="space-y-3"><label class="workflow-label">Catatan kekurangan<textarea v-model="revisionNote" class="workflow-input" maxlength="1000" placeholder="Barang / nota yang tidak kebagian dan penyebabnya" /></label><button class="workflow-btn workflow-btn-warning" :disabled="busy || !revisionNote.trim()" @click="requestRevision">Ajukan revisi faktur kurang picked</button></div>
      </div>
    </template>
    <p v-else-if="!busy" class="workflow-empty">Belum ada draf dimuat.</p>
  </section>
</template>
