<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import api from '@/api/axios';
import { unwrapResponse, normalizeError } from '@/utils/api';
import { pickingGroups, shipmentQrSvg } from '@/utils/shipmentPicking';
import { openPrintHtml } from '@/utils/printTemplates';
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
function load() { document.value = null; rows.value = []; return run(refreshDraft); }
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
function printQr() { openPrintHtml(reference.value, `<h1>${reference.value}</h1>${shipmentQrSvg(reference.value)}<p>Scan Draf Kiriman di Mobile WMS</p>`); }
onMounted(() => run(async () => { const data = unwrapResponse(await api.get('/api/picking/picking/shipments')); drafts.value = data.data || data; }));
</script>

<template>
  <section class="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-950">
    <h2 class="text-xl font-bold">Picking Draf Kiriman</h2>
    <p class="text-sm">Scan QR draf kiriman atau pilih draf tersimpan. Alokasi barang tetap per nota; seluruh barang harus melalui checker.</p>
    <div class="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
      <label>Pilih draf<select aria-label="Pilih draf" v-model="reference" class="field" :disabled="busy" @change="load"><option value="">Pilih draf…</option><option v-for="d in drafts" :key="d.reference" :value="d.reference">{{ d.reference }} · {{ d.delivering_date }} · {{ d.note_count }} nota</option></select></label>
      <label>Scan / referensi draf<input v-model="reference" class="field" placeholder="DRF-1-123 atau QR draf kiriman" :disabled="busy" @keyup.enter="load" /></label>
      <button class="rounded-xl bg-blue-700 px-4 py-2 text-white disabled:opacity-50" :disabled="busy || !reference" @click="load">Muat draf</button>
    </div>
    <p v-if="error" role="alert" class="rounded-lg bg-rose-50 p-3 text-rose-800">{{ error }}</p>
    <p v-if="feedback" role="status" class="rounded-lg bg-blue-50 p-3 text-blue-800">{{ feedback }}</p>
    <template v-if="document">
      <div class="flex flex-wrap items-center gap-3"><strong>{{ document.shipment_reference }} · {{ state }}</strong><button class="rounded-lg border px-3 py-2" @click="printQr">Cetak QR draf</button><label>Tampilan <select aria-label="Tampilan" v-model="mode" class="field"><option value="variant">By variant</option><option value="nota">By nota</option></select></label></div>
      <p v-if="document.task_statuses?.includes('REVISION_REQUIRED')" class="font-semibold text-amber-700">Ditahan: selesaikan Revisi Faktur ERP. Sesuaikan qty dengan picked atau pertahankan qty untuk stok susulan. Nota seluruhnya 0 tetap ditahan.</p>
      <article v-for="group in groups" :key="group.key" class="overflow-x-auto rounded-xl border p-3">
        <h3 class="font-bold">{{ group.title }}</h3><p class="text-sm">Order {{ group.required }} PCS · Picked {{ group.picked }} PCS · Kurang {{ Math.max(0, group.required-group.picked) }} PCS</p>
        <table class="mt-3 w-full text-left text-sm"><thead><tr><th>Nota</th><th>Barang</th><th>Order / Picked</th><th>Rak / Batch</th><th>Ambil (PCS)</th><th>Aksi</th></tr></thead>
          <tbody><tr v-for="row in group.rows" :key="row.wms_task_detail_id" class="border-t">
            <td class="p-2">{{ row.nota || row.no_order }}</td><td class="p-2">{{ row.product_code }}<br>{{ row.product_name }}</td><td class="p-2">{{ row.required_quantity }} / {{ row.picked_quantity }}</td>
            <td class="p-2"><input v-model="row.rack" class="field min-w-32" :disabled="!editable || busy" :aria-label="`Rak ${row.product_code}`" />{{ row.batch || '-' }}</td>
            <td class="p-2"><input v-model="row.qty" class="field w-24" type="number" min="1" step="1" :max="row.required_quantity-row.picked_quantity" :disabled="!editable || busy" :aria-label="`Qty ${row.product_code}`" /></td>
            <td><button class="rounded-lg border px-3 py-2 disabled:opacity-40" :disabled="busy || !editable || !row.rack || !Number.isInteger(Number(row.qty)) || Number(row.qty)<=0 || Number(row.qty)>row.required_quantity-row.picked_quantity" @click="scan(row)">Pick nota ini</button></td>
          </tr></tbody></table>
      </article>
      <div v-if="editable" class="space-y-3"><label>Nama picker<input v-model="picker" class="field" /></label>
        <button class="rounded-xl bg-blue-700 px-4 py-2 text-white disabled:opacity-40" :disabled="busy || shortages || !rows.some(r=>Number(r.picked_quantity)>0) || !picker.trim()" @click="finalize">Selesai Picking → Checker</button>
        <div v-if="shortages"><label>Catatan kekurangan<textarea v-model="revisionNote" class="field" maxlength="1000" placeholder="Barang / nota yang tidak kebagian dan penyebabnya" /></label><button class="mt-2 rounded-lg border border-amber-600 px-3 py-2 disabled:opacity-40" :disabled="busy || !revisionNote.trim()" @click="requestRevision">Ajukan revisi faktur kurang picked</button></div>
      </div>
    </template>
    <p v-else-if="!busy" class="py-8 text-center text-slate-500">Belum ada draf dimuat.</p>
  </section>
</template>
