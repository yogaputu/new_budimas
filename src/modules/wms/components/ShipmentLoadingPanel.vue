<script setup>
import AppSelect2 from '@/shared/components/AppSelect2.vue';
import { computed, onMounted, ref, watch } from 'vue';
import api from '@/api/axios';
import { normalizeError, unwrapResponse } from '@/utils/api';
const assignments = ref([]), fleet = ref(''), driver = ref(''), day = ref(''), rows = ref([]), loaded = ref(false), busy = ref(false), message = ref(''), error = ref('');
const fleets = computed(() => [...new Map(assignments.value.map(a => [String(a.id_armada), a.vehicle])).entries()]);
const drivers = computed(() => [...new Map(assignments.value.filter(a=>String(a.id_armada)===fleet.value).map(a=>[String(a.id_driver), a.driver])).entries()]);
const valid = computed(() => assignments.value.some(a=>String(a.id_armada)===fleet.value && String(a.id_driver)===driver.value && a.delivery_date===day.value));
const groups = computed(() => [...new Set(rows.value.map(r=>r.ScheduleKey))].map(key=>({key, rows:rows.value.filter(r=>r.ScheduleKey===key)})));
function selection() { return { id_armada: Number(fleet.value), id_driver: Number(driver.value), delivery_date: day.value }; }
watch([fleet, driver, day], () => { rows.value=[]; loaded.value=false; error.value=''; message.value=''; });
watch(fleet, () => { driver.value=''; });
async function run(fn) { busy.value=true; error.value=''; try { await fn(); } catch(e) { error.value=normalizeError(e, 'Loading belum berhasil.'); } finally { busy.value=false; } }
async function refresh() { rows.value=[]; loaded.value=false; const data=unwrapResponse(await api.get('/api/loading/loading/ready-to-load',{params:selection()})); rows.value=data.data||data; loaded.value=true; }
function factor(row) { return Math.max(1,Number(row.PerUnit || 1)); }
function total(row) { return Number(row.required_quantity ?? row.picked_quantity ?? 0); }
function allocationTotal(row) {
  const ct = Number(row.loaded_cartons), pc = Number(row.loaded_pieces);
  if (row.loaded_cartons === '' || row.loaded_pieces === '' || !Number.isInteger(ct) || !Number.isInteger(pc) || ct < 0 || pc < 0 || pc >= factor(row)) return -1;
  return ct * factor(row) + pc;
}
function fillFull(row) {
  row.loaded_cartons = Math.floor(total(row) / factor(row));
  row.loaded_pieces = total(row) % factor(row);
  row.loading_verified = false;
}
function quantityChanged(row) { row.loading_verified = false; }
function submit(group, action) {
  if (action !== 'start' && group.rows.some(row => allocationTotal(row) < 0 || allocationTotal(row) > total(row))) {
    error.value = 'Isi CT/unit dan PCS lepas yang valid; jumlah tidak boleh melebihi barang yang akan dimuat.';
    return;
  }
  if (action === 'complete' && group.rows.some(row => allocationTotal(row) !== total(row) || !row.loading_verified)) {
    error.value = 'Lengkapi CT/PCS dan centang pemeriksaan setiap barang sebelum menyelesaikan loading.';
    return;
  }
  if (action !== 'save' && !window.confirm(action==='start'?'Mulai loading barang pada jadwal ini?':'Semua barang sudah masuk armada? Selesaikan loading dan buat manifest?')) return;
  return run(async()=>{
    const data=unwrapResponse(await api.post('/api/loading/loading/process',{
      ...selection(), items:group.rows, action, verification_version:1
    }));
    message.value=data.message||data.msg||`Loading berhasil ${data.no_manifest||''}`;
    await refresh();
  });
}
onMounted(()=>run(async()=>{ const data=unwrapResponse(await api.get('/api/loading/loading/assignments')); assignments.value=data.data||data; }));
</script>
<template>
<section class="workflow-ui workflow-card space-y-5" :aria-busy="busy">
  <header>
    <h2 class="workflow-heading">Loading Armada</h2>
    <p class="workflow-caption mt-1">Pilih armada, driver, dan tanggal pengiriman terlebih dahulu. Hanya barang pada jadwal tersebut yang sudah lolos checker ditampilkan.</p>
  </header>
  <div class="workflow-inset grid items-end gap-4 sm:grid-cols-2 xl:grid-cols-[1fr_1fr_1fr_auto]">
    <label class="workflow-label">Armada<AppSelect2 aria-label="Armada" v-model="fleet"  :disabled="busy"><option value="">Pilih armada</option><option v-for="[id,name] in fleets" :key="id" :value="id">{{name}}</option></AppSelect2></label>
    <label class="workflow-label">Driver<AppSelect2 aria-label="Driver" v-model="driver"  :disabled="busy || !fleet"><option value="">Pilih driver</option><option v-for="[id,name] in drivers" :key="id" :value="id">{{name}}</option></AppSelect2></label>
    <label class="workflow-label">Tanggal pengiriman<input v-model="day" type="date" class="workflow-input" :disabled="busy" /></label>
    <button class="workflow-btn workflow-btn-primary" :disabled="busy || !valid" @click="run(refresh)">Tampilkan barang</button>
  </div>
  <p v-if="error" role="alert" class="workflow-notice workflow-notice-error">{{error}}</p><p v-if="message" role="status" class="workflow-notice workflow-notice-success">{{message}}</p>
  <p v-if="!loaded && !busy" class="workflow-empty">Lengkapi pilihan jadwal lalu tampilkan barang.</p><p v-if="loaded && !rows.length" class="workflow-empty">Belum ada barang lolos checker / seluruh barang sudah dimuat pada jadwal ini.</p>
  <article v-for="group in groups" :key="group.key" class="min-w-0 space-y-4">
    <header class="workflow-inset">
      <h3 class="break-words font-semibold">{{group.rows[0].ArmadaRencana}} · {{group.rows[0].DriverRencana}} · {{group.rows[0].ScheduledDeliveryDate}}</h3>
      <p class="workflow-caption mt-1">Helper: {{group.rows[0].HelperRencana}}</p>
    </header>
    <div class="workflow-table-wrap" tabindex="0" aria-label="Rincian muatan; geser untuk melihat semua kolom">
      <table class="workflow-table"><thead><tr><th scope="col">Draf / Nota</th><th scope="col">Barang</th><th scope="col">Jumlah muatan</th><th scope="col">Status</th></tr></thead><tbody><tr v-for="row in group.rows" :key="row.wms_task_detail_id"><td class="whitespace-nowrap"><strong>{{row.ShipmentReference}}</strong><p class="workflow-caption mt-1">{{row.Nota}}</p></td><td>{{row.KodeBarang}} · {{row.NamaBarang}}</td><td class="whitespace-nowrap tabular-nums">{{Math.floor(total(row)/factor(row))}} {{factor(row)>1?'CT/unit':'PCS'}} + {{total(row)%factor(row)}} PCS lepas<br><span class="workflow-caption">Total {{total(row)}} PCS · 1 CT/unit = {{factor(row)}} PCS</span></td><td><span class="workflow-badge">{{row.loading_status}}</span></td></tr></tbody></table>
    </div>
    <div v-for="row in group.rows" :key="`allocation-${row.wms_task_detail_id}`" class="workflow-inset space-y-3">
      <p class="break-words font-semibold">{{row.Nota}} · {{row.NamaBarang}}</p>
      <div class="grid items-end gap-4 sm:grid-cols-[1fr_1fr_auto]">
        <label class="workflow-label">{{factor(row)>1?'CT / unit':'PCS'}}<input v-model="row.loaded_cartons" type="number" min="0" step="1" class="workflow-input" :disabled="busy || row.loading_status!=='LOADING'" @input="quantityChanged(row)" /></label>
        <label class="workflow-label">PCS lepas<input v-model="row.loaded_pieces" type="number" min="0" :max="factor(row)-1" step="1" class="workflow-input" :disabled="busy || row.loading_status!=='LOADING'" @input="quantityChanged(row)" /></label>
        <button class="workflow-btn" :disabled="busy || row.loading_status!=='LOADING'" @click="fillFull(row)">Isi Full</button>
      </div>
      <p class="workflow-caption">{{allocationTotal(row)<0?'Jumlah tidak valid':`Isi ${allocationTotal(row)} PCS · Sisa ${total(row)-allocationTotal(row)} PCS`}}</p>
      <label class="flex items-center gap-3 text-sm font-medium"><input v-model="row.loading_verified" type="checkbox" class="h-4 w-4 accent-brand-600" :disabled="busy || row.loading_status!=='LOADING' || allocationTotal(row)!==total(row)" /> Sudah diperiksa dan sesuai</label>
    </div>
    <div class="workflow-actions border-t pt-4" style="border-color: var(--workflow-border)">
      <button class="workflow-btn" :disabled="busy || group.rows.every(r=>r.loading_status==='LOADING')" @click="submit(group,'start')">Mulai Loading</button>
      <button class="workflow-btn" :disabled="busy || group.rows.some(r=>r.loading_status!=='LOADING')" @click="submit(group,'save')">Simpan Alokasi</button>
      <button class="workflow-btn workflow-btn-primary" :disabled="busy || group.rows.some(r=>r.loading_status!=='LOADING')" @click="submit(group,'complete')">Selesaikan Loading</button>
    </div>
  </article>
</section>
</template>
