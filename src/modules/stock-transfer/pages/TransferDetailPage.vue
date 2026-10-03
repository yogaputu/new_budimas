<script setup>
import { transferJournalWarning } from '../journalFeedback';
import { transferCompanyLabel } from '../companyScope';
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  adminConfirmStockTransfer,
  confirmStockTransfer,
  getStockTransferDetail,
  getStockTransfers,
  receiveStockTransfer
} from '@/api/stockTransfer';
import { getAllFleets } from '@/api/distribution';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { exportRowsToCsv } from '@/utils/exportCsv';
import { toLocalDateInputValue } from '@/utils/date';
import { canAccessRoleGroups } from '@/utils/roleAccess';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();

const form = reactive({
  id: '',
  armada: '',
  pengambilan_oleh: '',
  tanggal_ambil: toLocalDateInputValue()
});

const transferHeader = ref({});
const fleetRows = ref([]);
const fleetLoading = ref(false);
const fleetError = ref('');
const rows = ref([]);
const loading = ref(false);
const actionLoading = ref(false);
const feedback = ref('');
const journalWarning = ref('');
const errorMessage = ref('');

const statusOptions = [
  { value: '0', label: 'Draft / Request' },
  { value: '1', label: 'Dikonfirmasi' },
  { value: '2', label: 'Dalam Pengiriman' },
  { value: '3', label: 'Diterima' },
  { value: '-2', label: 'Ditolak' }
];

const fleetOptions = computed(() => {
  const options = fleetRows.value.map((item) => ({
    value: String(item.id),
    label: `${item.no_pelat || item.no_polisi || item.kode || '-'} - ${item.nama || 'Armada'}`
  }));

  const selectedFleetId = transferHeader.value?.id_armada ? String(transferHeader.value.id_armada) : '';
  if (selectedFleetId && !options.some((item) => item.value === selectedFleetId)) {
    options.unshift({
      value: selectedFleetId,
      label: transferHeader.value?.nama_armada || `Armada tersimpan #${selectedFleetId}`
    });
  }

  return options;
});

const statusLabel = computed(() =>
  statusOptions.find((option) => String(option.value) === String(transferHeader.value?.status))?.label || `Status ${transferHeader.value?.status ?? '-'}`
);

const canProcessWarehouseAction = computed(() => canAccessRoleGroups(authStore, ['warehouse']));
const canConfirm = computed(() => canProcessWarehouseAction.value && String(transferHeader.value?.status ?? '0') === '0');
const canAdminConfirm = computed(() => canProcessWarehouseAction.value && String(transferHeader.value?.status) === '1');
const canReceive = computed(() => canProcessWarehouseAction.value && String(transferHeader.value?.status) === '2');

function formatConfiguredUom(item) {
  return [1, 2, 3]
    .filter((level) => item[`uom_${level}_configured`])
    .map((level) => `${Number(item[`uom_${level}`] || 0).toLocaleString('id-ID')} ${item[`uom_${level}_label`] || `UOM ${level}`}`)
    .join(' · ') || `${Number(item.total_pieces ?? item.jumlah ?? 0).toLocaleString('id-ID')} PCS`;
}

const detailRows = computed(() =>
  rows.value.map((item) => ({
    ...item,
    jumlah_label: formatConfiguredUom(item),
    picked_label: item.jumlah_picked || item.jumlah_picked_label || '-',
    diterima_label: item.jumlah_diterima || '-'
  }))
);

const detailSummary = computed(() => {
  const totalRequest = rows.value.reduce((acc, item) => acc + Number(item.jumlah || 0), 0);
  const totalPicked = rows.value.reduce((acc, item) => acc + Number(item.jumlah_picked || 0), 0);
  const totalReceived = rows.value.reduce((acc, item) => acc + Number(item.jumlah_diterima || 0), 0);

  return [
    { label: 'Baris Produk', value: rows.value.length.toLocaleString('id-ID') },
    { label: 'Total Request', value: totalRequest.toLocaleString('id-ID') },
    { label: 'Total Picked', value: totalPicked.toLocaleString('id-ID') },
    { label: 'Total Diterima', value: totalReceived.toLocaleString('id-ID') }
  ];
});

function buildProductPayload() {
  return rows.value.map((item) => ({
    id_stock_transfer: Number(form.id),
    id_produk: Number(item.id_produk),
    id_principal: Number(item.id_principal || 0),
    pieces: Number(item.uom_1 || item.pieces || 0),
    box: Number(item.uom_2 || item.box || 0),
    carton: Number(item.uom_3 || item.carton || 0),
    uom1: Number(item.uom_1 || 0),
    uom2: Number(item.uom_2 || 0),
    uom3: Number(item.uom_3 || 0),
    uom_1: Number(item.uom_1 || 0),
    uom_2: Number(item.uom_2 || 0),
    uom_3: Number(item.uom_3 || 0),
    keterangan: item.keterangan || ''
  }));
}

function isPositiveInteger(value) {
  return /^\d+$/.test(String(value || '').trim()) && Number(value) > 0;
}

async function loadDetail() {
  journalWarning.value = '';
  if (!form.id) {
    errorMessage.value = 'Pilih stok transfer dari list atau isi ID transfer terlebih dahulu.';
    return;
  }

  if (!isPositiveInteger(form.id)) {
    errorMessage.value = 'ID transfer harus berupa angka.';
    rows.value = [];
    transferHeader.value = {};
    return;
  }

  loading.value = true;
  feedback.value = '';
  errorMessage.value = '';

  try {
    const response = await getStockTransferDetail({ id: form.id });
    rows.value = normalizeList(unwrapResponse(response));
    const listResponse = await getStockTransfers();
    const headerList = normalizeList(unwrapResponse(listResponse));
    transferHeader.value = headerList.find((item) => String(item.id) === String(form.id)) || {};
    await loadOptions(
      transferHeader.value?.id_cabang_awal || transferHeader.value?.id_cabang_tujuan,
      transferHeader.value?.id_perusahaan_awal || transferHeader.value?.id_perusahaan
    );
    form.armada = transferHeader.value?.id_armada ? String(transferHeader.value.id_armada) : form.armada;
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Gagal mengambil detail stok transfer.');
  } finally {
    loading.value = false;
  }
}

async function runAction(action) {
  feedback.value = '';
  journalWarning.value = '';
  errorMessage.value = '';

  if (!form.id || !rows.value.length) {
    errorMessage.value = 'Muat detail stok transfer terlebih dahulu.';
    return;
  }

  if (action === 'confirm' && !form.armada) {
    errorMessage.value = 'Pilih armada terlebih dahulu sebelum konfirmasi transfer.';
    return;
  }

  if (action === 'confirm' && !isPositiveInteger(form.armada)) {
    errorMessage.value = 'Armada tidak valid. Pilih armada dari daftar sebelum konfirmasi transfer.';
    return;
  }

  if (
    action === 'confirm'
    && !fleetOptions.value.some((item) => String(item.value) === String(form.armada))
  ) {
    errorMessage.value = 'Armada tidak tersedia pada cakupan transfer ini. Muat ulang detail lalu pilih armada kembali.';
    return;
  }

  actionLoading.value = true;

  try {
    const products = buildProductPayload();

    if (action === 'confirm') {
      await confirmStockTransfer({
        id_stock_transfer: form.id,
        id_cabang_awal: transferHeader.value.id_cabang_awal,
        armada: Number(form.armada),
        products
      });
      feedback.value = 'Transfer berhasil dikonfirmasi.';
    } else if (action === 'admin') {
      await adminConfirmStockTransfer({
        id: form.id,
        pengambilan_oleh: form.pengambilan_oleh,
        tanggal_ambil: form.tanggal_ambil,
        products
      });
      feedback.value = 'Konfirmasi admin berhasil diproses.';
    } else {
      const response = await receiveStockTransfer({
        id_stock_transfer: form.id,
        id_cabang_tujuan: transferHeader.value.id_cabang_tujuan,
        id_user: authStore.user?.id,
        list_produk: products
      });
      journalWarning.value = transferJournalWarning(unwrapResponse(response));
      feedback.value = 'Penerimaan transfer berhasil diproses.';
    }

    const completedFeedback = feedback.value;
    const completedJournalWarning = journalWarning.value;
    await loadDetail();
    feedback.value = completedFeedback;
    journalWarning.value = completedJournalWarning;
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Aksi stok transfer gagal.');
  } finally {
    actionLoading.value = false;
  }
}

async function loadOptions(idCabang = '', idPerusahaan = '') {
  fleetLoading.value = true;
  fleetError.value = '';

  try {
    const params = {};
    if (idCabang) params.id_cabang = idCabang;
    if (idPerusahaan) params.id_perusahaan = idPerusahaan;

    const response = await getAllFleets(Object.keys(params).length ? params : undefined);
    fleetRows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    // Fleet lookup must not hide the transfer detail.  It is reloaded from
    // the authoritative branch/company scope when the user retries.
    fleetRows.value = [];
    fleetError.value = normalizeError(error, 'Daftar armada belum dapat dimuat.');
  } finally {
    fleetLoading.value = false;
  }
}

async function reloadFleets() {
  await loadOptions(
    transferHeader.value?.id_cabang_awal || transferHeader.value?.id_cabang_tujuan,
    transferHeader.value?.id_perusahaan_awal || transferHeader.value?.id_perusahaan
  );
}

function goBack() {
  router.push({ name: 'stock-transfer-list' });
}

function exportDetail() {
  exportRowsToCsv(
    `stock-transfer-detail-${transferHeader.value?.nota_stock_transfer || form.id || 'data'}.csv`,
    [
      { label: 'SKU', key: 'kode_sku' },
      { label: 'Produk', key: 'nama_produk' },
      { label: 'Principal', key: 'nama_principal' },
      { label: 'Jumlah UOM', key: 'jumlah_label' },
      { label: 'Pieces', key: 'jumlah' },
      { label: 'Picked', key: 'jumlah_picked' },
      { label: 'Diterima', key: 'jumlah_diterima' }
    ],
    detailRows.value
  );
}

onMounted(async () => {
  await loadOptions();
  if (route.query.id) {
    form.id = String(route.query.id);
    await loadDetail();
  }
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader title="Detail Stok Transfer" description="Cek detail transfer sekaligus jalankan konfirmasi admin dan penerimaan barang.">
      <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" :disabled="!detailRows.length" @click="exportDetail">
        Export Detail CSV
      </button>
    </PageHeader>
    <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="goBack">
      Kembali ke Stok Transfer
    </button>
    <section class="panel p-5">
      <div class="grid gap-3 md:grid-cols-[0.7fr_1fr_1fr_1fr_auto]">
        <AppFormField v-model="form.id" label="ID Transfer" type="number" min="1" step="1" />
        <AppSearchSelect v-model="form.armada" label="Armada" placeholder="Pilih armada" :options="fleetOptions" :loading="fleetLoading" empty-text="Armada belum tersedia untuk cabang/perusahaan transfer ini." />
        <AppFormField v-model="form.pengambilan_oleh" label="Pengambilan oleh" />
        <AppFormField v-model="form.tanggal_ambil" label="Tanggal ambil" type="date" />
        <button class="self-end rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white" :disabled="loading" @click="loadDetail">Cari detail</button>
      </div>

      <div v-if="fleetError" class="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
        <span>{{ fleetError }}</span>
        <button type="button" class="rounded-xl border border-rose-300 px-3 py-2 text-xs font-semibold text-rose-700 hover:bg-rose-100 disabled:opacity-60 dark:border-rose-400/50 dark:text-rose-200 dark:hover:bg-rose-500/10" :disabled="fleetLoading" @click="reloadFleets">
          Muat Ulang Armada
        </button>
      </div>

      <div class="mt-4 grid gap-3 md:grid-cols-4 text-sm text-slate-600">
        <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
          <p class="text-xs uppercase tracking-wide text-slate-400">Nota</p>
          <p class="mt-2 font-semibold text-slate-900">{{ transferHeader.nota_stock_transfer || '-' }}</p>
        </div>
        <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
          <p class="text-xs uppercase tracking-wide text-slate-400">Cabang asal</p>
          <p class="mt-2 font-semibold text-slate-900">{{ transferHeader.nama_cabang_awal || transferHeader.id_cabang_awal || '-' }}</p>
        </div>
        <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
          <p class="text-xs uppercase tracking-wide text-slate-400">Cabang tujuan</p>
          <p class="mt-2 font-semibold text-slate-900">{{ transferHeader.nama_cabang_tujuan || transferHeader.id_cabang_tujuan || '-' }}</p>
        </div>
        <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
          <p class="text-xs uppercase tracking-wide text-slate-400">Perusahaan</p>
          <p class="mt-2 font-semibold text-slate-900">{{ transferCompanyLabel(transferHeader) }}</p>
        </div>
        <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
          <p class="text-xs uppercase tracking-wide text-slate-400">Status</p>
          <p class="mt-2 font-semibold text-slate-900">{{ statusLabel }}</p>
        </div>
      </div>

      <div class="mt-4 flex flex-wrap gap-2">
        <button v-if="canConfirm" class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 disabled:opacity-60" :disabled="actionLoading || fleetLoading || !form.armada" @click="runAction('confirm')">
          Konfirmasi
        </button>
        <button v-if="canAdminConfirm" class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 disabled:opacity-60" :disabled="actionLoading" @click="runAction('admin')">
          Admin confirm
        </button>
        <button v-if="canReceive" class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 disabled:opacity-60" :disabled="actionLoading" @click="runAction('receive')">
          Terima barang
        </button>
      </div>
      <p class="mt-2 text-xs text-slate-500">
        Urutan proses: Draft/Request -> Konfirmasi -> Admin confirm -> Terima barang.
      </p>

      <div v-if="feedback" class="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
        {{ feedback }}
      </div>
      <div v-if="journalWarning" role="alert" class="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        {{ journalWarning }}
      </div>
      <div v-if="errorMessage" class="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
        {{ errorMessage }}
      </div>
    </section>

    <section v-if="rows.length" class="grid gap-4 md:grid-cols-4">
      <article v-for="item in detailSummary" :key="item.label" class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">{{ item.label }}</p>
        <p class="mt-3 text-lg font-semibold text-slate-900">{{ item.value }}</p>
      </article>
    </section>

    <AppTable
      :rows="detailRows"
      :columns="[
        { key: 'kode_sku', label: 'SKU' },
        { key: 'nama_produk', label: 'Produk' },
        { key: 'nama_principal', label: 'Principal' },
        { key: 'jumlah_label', label: 'Jumlah UOM' },
        { key: 'jumlah', label: 'Pieces' },
        { key: 'jumlah_picked', label: 'Picked' },
        { key: 'jumlah_diterima', label: 'Diterima' }
      ]"
      :loading="loading"
      empty-message="Detail produk stok transfer belum dimuat."
    />
  </div>
</template>
