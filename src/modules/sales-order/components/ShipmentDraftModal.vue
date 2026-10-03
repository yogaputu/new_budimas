<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { createFleetScheduleFromSalesOrders } from '@/api/distribution';
import { getDrivers, getFleets, getHelpers } from '@/api/master';
import { getRowCompanyIds } from '@/utils/accessScope';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { draftOrderId, draftSelectionError } from '@/utils/shipmentDraft';
import AppModal from '@/shared/components/AppModal.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';

const props = defineProps({ open: Boolean, rows: { type: Array, default: () => [] } });
const emit = defineEmits(['close', 'created']);
const form = reactive({ id_armada: '', id_driver: '', helper_ids: [], tanggal_pengiriman: '', dock_code: '', cargo_zone: '', volume_unit: '', delivery_notes: '' });
const fleets = ref([]), drivers = ref([]), helpers = ref([]);
const loading = ref(false), saving = ref(false), error = ref('');
const selectionError = computed(() => draftSelectionError(props.rows));
const branch = computed(() => String(props.rows[0]?.id_cabang || ''));
const company = computed(() => String(props.rows[0]?.id_perusahaan || ''));
const fleetOptions = computed(() => fleets.value.filter(row =>
  row.id_cabang ? String(row.id_cabang) === branch.value : getRowCompanyIds(row).includes(company.value)
).map(row => ({ value: String(row.id), label: `${row.no_pelat || row.no_polisi || row.kode || '-'} - ${row.nama || 'Armada'}` })));
function personOptions(rows) {
  return rows.filter(row => !row.id_cabang || String(row.id_cabang) === branch.value)
    .map(row => ({ value: String(row.id), label: row.nama || row.nama_driver || row.nama_helper || `#${row.id}` }));
}
const driverOptions = computed(() => personOptions(drivers.value));
const helperOptions = computed(() => personOptions(helpers.value));
let referenceRequest = 0;
watch(() => props.open, async open => {
  const requestId = ++referenceRequest;
  if (!open) return;
  Object.assign(form, { id_armada: '', id_driver: '', helper_ids: [], tanggal_pengiriman: '', dock_code: '', cargo_zone: '', volume_unit: '', delivery_notes: '' });
  error.value = ''; loading.value = true;
  fleets.value = []; drivers.value = []; helpers.value = [];
  try {
    const responses = await Promise.all([getFleets(), getDrivers(), getHelpers()]);
    if (requestId !== referenceRequest) return;
    [fleets.value, drivers.value, helpers.value] = responses.map(response => normalizeList(unwrapResponse(response)));
  } catch (cause) {
    if (requestId === referenceRequest) error.value = normalizeError(cause, 'Referensi armada belum dapat dimuat. Tutup lalu buka kembali form.');
  } finally {
    if (requestId === referenceRequest) loading.value = false;
  }
});
function close() { if (!saving.value) emit('close'); }
async function save() {
  if (saving.value || loading.value) return;
  error.value = selectionError.value;
  if (error.value) return;
  if (!fleetOptions.value.some(item => item.value === String(form.id_armada)) ||
      !driverOptions.value.some(item => item.value === String(form.id_driver)) ||
      !form.helper_ids.length || form.helper_ids.some(id => !helperOptions.value.some(item => item.value === String(id))) ||
      !form.tanggal_pengiriman || !form.dock_code.trim() || !['FOOD', 'NON_FOOD'].includes(form.cargo_zone) || !['CM3', 'M3'].includes(form.volume_unit)) {
    error.value = 'Lengkapi armada, driver, helper, tanggal kirim, loading dock, zona, dan satuan volume.';
    return;
  }
  saving.value = true;
  try {
    const response = await createFleetScheduleFromSalesOrders({ ...form,
      id_sales_orders: props.rows.map(row => Number(draftOrderId(row))),
      id_armada: Number(form.id_armada), id_driver: Number(form.id_driver),
      helper_ids: form.helper_ids.map(Number), id_helper: Number(form.helper_ids[0]),
      dock_code: form.dock_code.trim()
    });
    emit('created', unwrapResponse(response)?.message || `Draf kiriman untuk ${props.rows.length} nota berhasil dibuat.`);
  } catch (cause) {
    error.value = normalizeError(cause, 'Draf gagal dibuat. Pilihan nota tetap disimpan; cek status terbaru sebelum mencoba kembali.');
  } finally { saving.value = false; }
}
</script>

<template>
  <AppModal :open="open" title="Buat Draf Kiriman" description="Gabungkan nota terpilih dalam satu jadwal pengiriman. Nomor nota masing-masing tetap terpisah." size="4xl" @close="close">
    <div class="space-y-5">
      <p class="rounded-xl bg-sky-50 p-3 text-sm text-sky-900 dark:bg-sky-950 dark:text-sky-100">
        {{ rows.length }} nota · Rute: {{ rows[0]?.nama_rute || rows[0]?.id_rute || '-' }}. Satu armada, driver, dan tanggal kirim untuk seluruh pilihan.
      </p>
      <div class="max-h-48 overflow-auto rounded-xl border border-slate-200 dark:border-slate-700">
        <table class="w-full text-left text-sm">
          <thead><tr><th class="p-2">Nota / SO</th><th class="p-2">Tanggal Nota</th><th class="p-2">Customer</th></tr></thead>
          <tbody><tr v-for="row in rows" :key="draftOrderId(row)"><td class="p-2">{{ row.no_order }}</td><td class="p-2">{{ row.tanggal_order }}</td><td class="p-2">{{ row.nama_customer }}</td></tr></tbody>
        </table>
      </div>
      <p v-if="loading" role="status">Memuat armada, driver, dan helper…</p>
      <fieldset :disabled="saving || loading" class="grid min-w-0 gap-4 md:grid-cols-2">
        <AppSearchSelect v-model="form.id_armada" label="Armada" :options="fleetOptions" :disabled="saving || loading" />
        <AppSearchSelect v-model="form.id_driver" label="Driver" :options="driverOptions" :disabled="saving || loading" />
        <AppSearchSelect v-model="form.helper_ids" label="Helper / Kernet" multiple :options="helperOptions" :disabled="saving || loading" />
        <AppFormField v-model="form.tanggal_pengiriman" label="Tanggal Pengiriman" type="date" />
        <AppFormField v-model="form.dock_code" label="Loading Dock" maxlength="60" />
        <label class="text-sm">Zona muatan<select v-model="form.cargo_zone" aria-label="Zona muatan" class="field mt-1"><option value="">Pilih zona</option><option value="FOOD">FOOD</option><option value="NON_FOOD">NON-FOOD</option></select></label>
        <label class="text-sm">Satuan estimasi volume<select v-model="form.volume_unit" aria-label="Satuan estimasi volume" class="field mt-1"><option value="">Pilih satuan</option><option value="CM3">cm³</option><option value="M3">m³</option></select></label>
        <AppFormField v-model="form.delivery_notes" label="Catatan Pengiriman" maxlength="2000" />
      </fieldset>
      <p v-if="error || selectionError" role="alert" class="rounded-xl bg-rose-50 p-3 text-sm text-rose-700">{{ error || selectionError }}</p>
      <p class="text-xs text-slate-500">Satuan volume harus sesuai master produk. Draf tidak menggabungkan tagihan antarcustomer dan belum menyatakan barang sudah dikirim.</p>
    </div>
    <template #footer>
      <div class="flex justify-end gap-2">
        <button class="btn-erp-secondary" :disabled="saving" @click="close">Batal</button>
        <button class="btn-erp-primary" :disabled="saving || loading || !!selectionError" @click="save">{{ saving ? 'Menyimpan…' : `Simpan Draf (${rows.length} nota)` }}</button>
      </div>
    </template>
  </AppModal>
</template>
