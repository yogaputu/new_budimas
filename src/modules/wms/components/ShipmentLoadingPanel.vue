<script setup>
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
function submit(group, action) { if(!window.confirm(action==='start'?'Mulai loading barang pada jadwal ini?':'Semua barang sudah masuk armada? Selesaikan loading dan buat manifest?')) return; return run(async()=>{ const data=unwrapResponse(await api.post('/api/loading/loading/process',{...selection(),items:group.rows,action})); message.value=data.message||data.msg||`Loading berhasil ${data.no_manifest||''}`; await refresh(); }); }
onMounted(()=>run(async()=>{ const data=unwrapResponse(await api.get('/api/loading/loading/assignments')); assignments.value=data.data||data; }));
</script>
<template><section class="space-y-4 rounded-2xl border p-5">
  <h2 class="text-xl font-bold">Loading Armada</h2><p>Pilih armada, driver, dan tanggal pengiriman terlebih dahulu. Hanya barang pada jadwal tersebut yang sudah lolos checker ditampilkan.</p>
  <div class="grid gap-3 md:grid-cols-4"><label>Armada<select aria-label="Armada" v-model="fleet" class="field" :disabled="busy"><option value="">Pilih armada</option><option v-for="[id,name] in fleets" :key="id" :value="id">{{name}}</option></select></label><label>Driver<select aria-label="Driver" v-model="driver" class="field" :disabled="busy || !fleet"><option value="">Pilih driver</option><option v-for="[id,name] in drivers" :key="id" :value="id">{{name}}</option></select></label><label>Tanggal pengiriman<input v-model="day" type="date" class="field" :disabled="busy" /></label><button class="rounded-xl bg-blue-700 px-4 py-2 text-white disabled:opacity-40" :disabled="busy || !valid" @click="run(refresh)">Tampilkan barang</button></div>
  <p v-if="error" role="alert" class="text-rose-700">{{error}}</p><p v-if="message" role="status" class="text-blue-700">{{message}}</p>
  <p v-if="!loaded && !busy" class="py-8 text-center text-slate-500">Lengkapi pilihan jadwal lalu tampilkan barang.</p><p v-if="loaded && !rows.length" class="py-8 text-center">Belum ada barang lolos checker / seluruh barang sudah dimuat pada jadwal ini.</p>
  <article v-for="group in groups" :key="group.key" class="overflow-x-auto rounded-xl border p-4"><h3 class="font-bold">{{group.rows[0].ArmadaRencana}} · {{group.rows[0].DriverRencana}} · {{group.rows[0].ScheduledDeliveryDate}}</h3><p>Helper: {{group.rows[0].HelperRencana}}</p>
    <table class="my-4 w-full text-left text-sm"><thead><tr><th>Draf / Nota</th><th>Barang</th><th>Qty (PCS)</th><th>Status</th></tr></thead><tbody><tr v-for="row in group.rows" :key="row.wms_task_detail_id" class="border-t"><td class="p-2">{{row.ShipmentReference}}<br>{{row.Nota}}</td><td>{{row.KodeBarang}} · {{row.NamaBarang}}</td><td>{{row.picked_quantity}}</td><td>{{row.loading_status}}</td></tr></tbody></table>
    <button class="rounded-lg border px-4 py-2 disabled:opacity-40" :disabled="busy || group.rows.every(r=>r.loading_status==='LOADING')" @click="submit(group,'start')">Mulai Loading</button><button class="ml-3 rounded-lg bg-blue-700 px-4 py-2 text-white disabled:opacity-40" :disabled="busy || group.rows.some(r=>r.loading_status!=='LOADING')" @click="submit(group,'complete')">Selesaikan Loading</button>
  </article>
</section></template>
