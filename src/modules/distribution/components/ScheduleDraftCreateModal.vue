<script setup>
import { onMounted, ref, watch } from 'vue';
import { getShipmentDraftOrders } from '@/api/distribution';
import { useShipmentNotePicker } from '@/composables/useShipmentNotePicker';
import { draftOrderId, draftEligibilityError, MAX_DRAFT_NOTES } from '@/utils/shipmentDraft';
import { formatPrintDate } from '@/utils/printTemplates';
import AppModal from '@/shared/components/AppModal.vue';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppTable from '@/shared/components/AppTable.vue';
import ShipmentDraftModal from '@/modules/sales-order/components/ShipmentDraftModal.vue';

const props = defineProps({ companyId: { type: String, required: true }, branchId: { type: String, required: true }, companyName: String, branchName: String });
const emit = defineEmits(['close', 'created']);
const detailsOpen = ref(false), draftRows = ref([]);
const { filters, rows, selected, selectedRows, loading, error, selectionMessage, selectionProblem,
  pagination, ready, eligibleRows, allChecked, someChecked, load, selectRows, clearSelection, reset } =
  useShipmentNotePicker(getShipmentDraftOrders, () => ({ companyId: props.companyId, branchId: props.branchId }));
const fields = [
  { key: 'dateFrom', label: 'Tanggal Nota Dari', type: 'date' },
  { key: 'dateTo', label: 'Tanggal Nota Sampai', type: 'date' },
  { key: 'search', label: 'Cari Nota / Customer', placeholder: 'Nomor nota atau nama customer' }
];
const columns = [
  { key: 'select', label: 'Pilih' }, { key: 'no_order', label: 'Nota / SO' },
  { key: 'tanggal_order', label: 'Tanggal Nota', render: row => formatPrintDate(row.tanggal_order) },
  { key: 'nama_customer', label: 'Customer' }, { key: 'nama_rute', label: 'Rute' },
  { key: 'eligibility', label: 'Keterangan', render: row => draftEligibilityError(row) || 'Terkonfirmasi · Siap dijadwalkan' }
];
function toggle(row, event) {
  const checked = event.target.checked;
  event.target.checked = !!selected.value[draftOrderId(row)];
  selectRows([row], checked);
}
function togglePage(event) {
  const checked = event.target.checked;
  event.target.checked = allChecked.value;
  event.target.indeterminate = someChecked.value;
  selectRows(eligibleRows.value, checked);
}
function continueDraft() {
  if (!ready.value || !selectedRows.value.length || selectionProblem.value) return;
  draftRows.value = selectedRows.value.map(row => ({ ...row }));
  detailsOpen.value = true;
}
// One dialog remains open throughout this two-step flow. Apply after the two
// AppModal watchers so closing one step does not unlock the background page.
function keepBackgroundLocked() { document.body.style.overflow = 'hidden'; }
watch(detailsOpen, keepBackgroundLocked, { flush: 'post' });
onMounted(() => { load(); keepBackgroundLocked(); });
</script>

<template>
  <AppModal :open="!detailsOpen" title="Pilih Nota Terkonfirmasi" description="Langkah 1 dari 2 · Pilih nota yang sudah dikonfirmasi untuk membuat draf kiriman." size="4xl" @close="emit('close')">
    <div class="space-y-4">
      <p class="text-sm font-medium">{{ companyName || `Perusahaan #${companyId}` }} · {{ branchName || `Cabang #${branchId}` }}</p>
      <AppFilterBar :model-value="filters" :fields="fields" @update:model-value="Object.assign(filters, $event)" @submit="load(1)" @reset="reset" />
      <p class="text-sm text-slate-500">Rentang tanggal memakai tanggal nota, termasuk tanggal awal dan akhir. Hanya nota terkonfirmasi yang ditampilkan; nota yang sudah dijadwalkan tidak bisa dipilih.</p>
      <p v-if="error" role="alert" class="rounded-xl bg-rose-50 p-3 text-sm text-rose-700">{{ error }}</p>
      <p v-else-if="!ready && !loading" role="status" class="text-sm text-amber-700">Filter berubah. Klik Terapkan untuk memuat nota.</p>
      <AppTable :rows="rows" :columns="columns" :loading="loading" :paginated="false" row-key="id" empty-message="Tidak ada nota terkonfirmasi sesuai filter. Coba rentang tanggal atau pencarian lain.">
        <template #header-select><input type="checkbox" aria-label="Pilih semua nota di halaman ini" :checked="allChecked" :indeterminate="someChecked" :disabled="!ready || !eligibleRows.length" @change="togglePage" /></template>
        <template #cell-select="{ row }"><input type="checkbox" :aria-label="`Pilih nota ${row.no_order}`" :title="draftEligibilityError(row) || 'Pilih nota'" :checked="!!selected[draftOrderId(row)]" :disabled="!ready || !!draftEligibilityError(row)" @change="toggle(row, $event)" /></template>
      </AppTable>
      <div class="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span>Halaman {{ pagination.page }} / {{ pagination.totalPages }} · {{ pagination.total }} nota terkonfirmasi belum dijadwalkan</span>
        <div class="flex gap-2">
          <button class="btn-erp-secondary" :disabled="!ready || pagination.page <= 1" @click="load(pagination.page - 1)">Halaman Sebelumnya</button>
          <button class="btn-erp-secondary" :disabled="!ready || pagination.page >= pagination.totalPages" @click="load(pagination.page + 1)">Halaman Berikutnya</button>
        </div>
      </div>
      <section class="rounded-xl border border-slate-200 p-3 dark:border-slate-700" aria-label="Nota terpilih">
        <div class="flex items-center justify-between gap-2"><p class="font-medium">{{ selectedRows.length }} nota dipilih</p><button class="btn-erp-secondary" :disabled="!selectedRows.length || loading" @click="clearSelection">Kosongkan Nota</button></div>
        <p class="mt-1 text-xs text-slate-500">Pilihan tetap tersimpan saat pindah halaman, dan dikosongkan jika filter berubah. Maksimal {{ MAX_DRAFT_NOTES }} nota dengan perusahaan, cabang, dan rute yang sama.</p>
        <div v-if="selectedRows.length" class="mt-3 flex max-h-28 flex-wrap gap-2 overflow-y-auto">
          <button v-for="row in selectedRows" :key="draftOrderId(row)" class="rounded-lg border border-slate-300 px-2 py-1 text-xs dark:border-slate-600" :disabled="!ready" :aria-label="`Hapus nota ${row.no_order} dari pilihan`" @click="selectRows([row], false)">{{ row.no_order }} · {{ row.nama_rute || row.id_rute }} ✕</button>
        </div>
      </section>
      <p v-if="selectionMessage || selectionProblem" role="alert" class="rounded-xl bg-amber-50 p-3 text-sm text-amber-800">{{ selectionMessage || selectionProblem }}</p>
    </div>
    <template #footer>
      <div class="flex justify-end gap-2"><button class="btn-erp-secondary" @click="emit('close')">Batal</button><button class="btn-erp-primary" :disabled="!ready || !selectedRows.length || !!selectionProblem" @click="continueDraft">Lanjut Atur Pengiriman ({{ selectedRows.length }} nota)</button></div>
    </template>
  </AppModal>
  <ShipmentDraftModal :open="detailsOpen" :rows="draftRows" @close="detailsOpen = false" @created="emit('created', $event)" />
</template>
