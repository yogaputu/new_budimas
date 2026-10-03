<script setup>
import { transferJournalWarning } from '../journalFeedback';
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import {
  adminConfirmStockTransfer,
  closeEscalatedStockTransfer,
  confirmStockTransfer,
  getStockTransferDetail,
  getStockTransfers,
  receiveStockTransfer,
  rejectStockTransfer
} from '@/api/stockTransfer';
import { getAllFleets } from '@/api/distribution';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getLoginCompanyId, isSuperUser } from '@/utils/accessScope';
import { getBranchOptionsForCompany, getCompanyOptionsForScope, getCompanyIdsForBranch } from '@/utils/filterScope';
import { transferCompanyIds, transferCompanyLabel } from '../companyScope';
import { exportRowsToCsv } from '@/utils/exportCsv';
import { toLocalDateInputValue } from '@/utils/date';
import { canAccessRoleGroups } from '@/utils/roleAccess';
import { useAuthStore } from '@/stores/auth';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const route = useRoute();
const authStore = useAuthStore();

const processConfigs = {
  confirmation: {
    title: 'Approval Stok Transfer',
    description: 'Daftar pengajuan stok transfer yang menunggu konfirmasi gudang/cabang.',
    statuses: ['0'],
    empty: 'Belum ada pengajuan transfer yang perlu dikonfirmasi.'
  },
  shipment: {
    title: 'Pengiriman Stok Transfer',
    description: 'Monitoring transfer yang sudah dikonfirmasi dan siap diproses pengiriman.',
    statuses: ['1', '5'],
    empty: 'Belum ada transfer yang siap dikirim.'
  },
  receipt: {
    title: 'Penerimaan Barang',
    description: 'Daftar stok transfer dalam perjalanan yang perlu diterima cabang tujuan.',
    statuses: ['2'],
    empty: 'Belum ada transfer dalam pengiriman.'
  },
  status: {
    title: 'Status Pengiriman',
    description: 'Pantau seluruh status stok transfer dari request sampai diterima atau eskalasi.',
    statuses: [],
    empty: 'Belum ada histori stok transfer.'
  },
  escalation: {
    title: 'Eskalasi Stok Transfer',
    description: 'Daftar stok transfer yang ditolak/eskalasi dan perlu ditindaklanjuti.',
    statuses: ['-2', '4'],
    empty: 'Belum ada stok transfer yang masuk eskalasi.'
  }
};

const statusOptions = [
  { value: '-2', label: 'Tolak Diterima' },
  { value: '-1', label: 'Tolak Konfirmasi' },
  { value: '0', label: 'Request' },
  { value: '1', label: 'Konfirmasi' },
  { value: '2', label: 'Pengiriman' },
  { value: '3', label: 'Diterima' },
  { value: '4', label: 'Eskalasi' },
  { value: '5', label: 'Picked' },
  { value: '6', label: 'Eskalasi Closed' }
];

const filters = reactive({
  branchId: '',
  companyId: '',
  principalId: '',
  status: '',
  search: ''
});

const items = ref([]);
const branchRows = ref([]);
const companyRows = ref([]);
const principalRows = ref([]);
const fleetRows = ref([]);
const fleetLoading = ref(false);
const fleetError = ref('');
const loading = ref(false);
const detailLoading = ref(false);
const actionLoading = ref(false);
const errorMessage = ref('');
const modalError = ref('');
const feedback = ref('');
const journalWarning = ref('');
const detailModalOpen = ref(false);
const selectedTransfer = ref(null);
const detailRows = ref([]);
const processForm = reactive({
  armada: '',
  pengambilan_oleh: '',
  tanggal_ambil: toLocalDateInputValue()
});

const mode = computed(() => route.meta.processMode || 'status');
const config = computed(() => processConfigs[mode.value] || processConfigs.status);
const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(authStore.user));
const canAccessAllBranches = computed(() => isSuperUser(authStore));
const canUseLoginScope = computed(() => !canAccessAllBranches.value);
const isStatusPage = computed(() => mode.value === 'status');
const canProcessWarehouseAction = computed(() => canAccessRoleGroups(authStore, ['warehouse']));

const fleetOptions = computed(() => {
  const options = fleetRows.value.map((item) => ({
    value: String(item.id),
    label: `${item.no_pelat || item.no_polisi || item.kode || '-'} - ${item.nama || 'Armada'}`
  }));

  const selectedFleetId = selectedTransfer.value?.id_armada ? String(selectedTransfer.value.id_armada) : '';
  if (selectedFleetId && !options.some((item) => item.value === selectedFleetId)) {
    options.unshift({
      value: selectedFleetId,
      label: selectedTransfer.value?.armada_label || `Armada tersimpan #${selectedFleetId}`
    });
  }

  return options;
});

function companyIdsForBranch(branchId) {
  return getCompanyIdsForBranch(branchId, branchRows.value, companyRows.value);
}

const branchOptions = computed(() =>
  getBranchOptionsForCompany(branchRows.value, authStore, filters.companyId, false, companyRows.value)
);

const companyOptions = computed(() => getCompanyOptionsForScope(companyRows.value, authStore));

const principalOptions = computed(() =>
  principalRows.value
    .filter((item) => !filters.companyId || String(item.id_perusahaan || item.perusahaan_id || '') === String(filters.companyId))
    .map((item) => ({
      value: String(item.id),
      label: item.nama || item.nama_principal || `Principal ${item.id}`
    }))
);

const visibleStatusOptions = computed(() => {
  if (isStatusPage.value) return statusOptions;
  const allowed = new Set(config.value.statuses);
  return statusOptions.filter((item) => allowed.has(String(item.value)));
});

function statusLabel(value) {
  return statusOptions.find((item) => String(item.value) === String(value))?.label || `Status ${value ?? '-'}`;
}

function stockQtyForStatus(item) {
  const status = String(item.status ?? '');
  if (['1', '2', '5'].includes(status)) return Number(item.jumlah_picked || 0);
  if (['3', '6'].includes(status)) return Number(item.jumlah_diterima || 0);
  if (status === '-2') return Number(item.jumlah_ditolak || 0);
  return Number(item.jumlah || 0);
}

const rows = computed(() =>
  items.value.map((item) => ({
    ...item,
    id: item.id || item.id_stock_transfer,
    status_label: statusLabel(item.status),
    route_label: `${item.nama_cabang_awal || item.id_cabang_awal || '-'} -> ${item.nama_cabang_tujuan || item.id_cabang_tujuan || '-'}`,
    company_label: transferCompanyLabel(item),
    armada_label: item.no_pelat_armada || item.no_polisi_armada || item.nama_armada || '-',
    tanggal_label: item.created_at || '-',
    jumlah_status: stockQtyForStatus(item).toLocaleString('id-ID')
  }))
);

const filteredRows = computed(() => {
  const query = filters.search.trim().toLowerCase();
  const allowedStatuses = new Set(config.value.statuses);

  return rows.value.filter((item) => {
    const branchIds = [item.id_cabang, item.id_cabang_awal, item.id_cabang_tujuan, item.cabang_id, item.branch_id].filter(Boolean).map(String);
    const companyIds = transferCompanyIds(item);
    const matchMode = !allowedStatuses.size || allowedStatuses.has(String(item.status));
    const matchBranch = !filters.branchId || branchIds.includes(String(filters.branchId));
    const matchCompany = !filters.companyId || companyIds.includes(String(filters.companyId));
    const matchPrincipal = !filters.principalId || String(item.id_principal || '') === String(filters.principalId);
    const matchStatus = !filters.status || String(item.status) === String(filters.status);
    const matchSearch =
      !query ||
      [
        item.id,
        item.nota_stock_transfer,
        item.route_label,
        item.company_label,
        item.nama_principal,
        item.status_label,
        item.armada_label,
        item.pengambilan_oleh
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query));

    return matchMode && matchBranch && matchCompany && matchPrincipal && matchStatus && matchSearch;
  });
});

const summaryCards = computed(() => [
  { label: 'Total Transfer', value: filteredRows.value.length.toLocaleString('id-ID') },
  { label: 'Total Produk', value: filteredRows.value.reduce((acc, item) => acc + Number(item.total_produk || 0), 0).toLocaleString('id-ID') },
  { label: 'Qty Proses', value: filteredRows.value.reduce((acc, item) => acc + stockQtyForStatus(item), 0).toLocaleString('id-ID') },
  { label: 'Cabang Aktif', value: filters.branchId ? branchOptions.value.find((item) => item.value === String(filters.branchId))?.label || '-' : 'Semua' }
]);

const selectedSummaryCards = computed(() => [
  { label: 'Nota', value: selectedTransfer.value?.nota_stock_transfer || '-' },
  { label: 'Status', value: selectedTransfer.value?.status_label || '-' },
  { label: 'Cabang', value: selectedTransfer.value?.route_label || '-' },
  { label: 'Perusahaan', value: selectedTransfer.value?.company_label || '-' },
  { label: 'Armada', value: selectedTransfer.value?.armada_label || '-' }
]);

const detailSummary = computed(() => [
  { label: 'Baris Produk', value: detailRows.value.length.toLocaleString('id-ID') },
  { label: 'Request', value: detailRows.value.reduce((acc, item) => acc + Number(item.jumlah || 0), 0).toLocaleString('id-ID') },
  { label: 'Picked', value: detailRows.value.reduce((acc, item) => acc + Number(item.jumlah_picked || 0), 0).toLocaleString('id-ID') },
  { label: 'Diterima', value: detailRows.value.reduce((acc, item) => acc + Number(item.jumlah_diterima || 0), 0).toLocaleString('id-ID') }
]);

const modalDescription = computed(() => {
  const actionMap = {
    confirmation: 'Validasi armada dan jumlah picked sebelum transfer masuk tahap konfirmasi.',
    shipment: 'Lengkapi pengambil dan tanggal ambil sebelum barang bergerak ke pengiriman.',
    receipt: 'Isi jumlah barang diterima cabang tujuan. Jika ada selisih, gunakan catatan produk.',
    escalation: 'Tutup eskalasi dengan jumlah final yang disepakati dan catatan produk.',
    status: 'Detail baca-saja untuk memantau posisi dan riwayat kuantitas transfer.'
  };

  return actionMap[mode.value] || actionMap.status;
});

const canConfirmSelected = computed(() => canProcessWarehouseAction.value && mode.value === 'confirmation' && String(selectedTransfer.value?.status) === '0');
const canAdminConfirmSelected = computed(() => canProcessWarehouseAction.value && mode.value === 'shipment' && ['1', '5'].includes(String(selectedTransfer.value?.status)));
const canReceiveSelected = computed(() => canProcessWarehouseAction.value && mode.value === 'receipt' && String(selectedTransfer.value?.status) === '2');
const canRejectSelected = computed(() => canProcessWarehouseAction.value && mode.value === 'receipt' && String(selectedTransfer.value?.status) === '2');
const canCloseEscalationSelected = computed(() => canProcessWarehouseAction.value && mode.value === 'escalation' && ['-2', '4'].includes(String(selectedTransfer.value?.status)));

function syncBranchFromCompany() {
  if (!filters.companyId) {
    if (canAccessAllBranches.value) filters.branchId = '';
    filters.principalId = '';
    return;
  }

  if (filters.branchId && !companyIdsForBranch(filters.branchId).includes(String(filters.companyId))) {
    filters.branchId = '';
  }

  if (filters.principalId && !principalOptions.value.some((item) => String(item.value) === String(filters.principalId))) {
    filters.principalId = '';
  }
}

async function loadOptions() {
  const [branchResponse, companyResponse, principalResponse] = await Promise.all([getBranches(), getCompanies(), getPrincipals()]);
  branchRows.value = normalizeList(unwrapResponse(branchResponse)).map((branch) => ({
    ...branch, id_cabang: branch.id_cabang || branch.id
  }));
  companyRows.value = normalizeList(unwrapResponse(companyResponse));
  principalRows.value = normalizeList(unwrapResponse(principalResponse));

  if (!filters.companyId && canUseLoginScope.value && fallbackCompanyId.value) {
    filters.companyId = String(fallbackCompanyId.value);
  }
  if (!canAccessAllBranches.value && fallbackBranchId.value) {
    filters.branchId = String(fallbackBranchId.value);
  }

  syncBranchFromCompany();
}

async function loadFleets(idCabang = '', idPerusahaan = '') {
  fleetLoading.value = true;
  fleetError.value = '';

  try {
    const params = {};
    if (idCabang) params.id_cabang = idCabang;
    if (idPerusahaan) params.id_perusahaan = idPerusahaan;

    const response = await getAllFleets(Object.keys(params).length ? params : undefined);
    fleetRows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    fleetRows.value = [];
    fleetError.value = normalizeError(error, 'Daftar armada belum dapat dimuat.');
  } finally {
    fleetLoading.value = false;
  }
}

async function reloadSelectedFleets() {
  await loadFleets(
    selectedTransfer.value?.id_cabang_awal || selectedTransfer.value?.id_cabang_tujuan || filters.branchId,
    selectedTransfer.value?.id_perusahaan_awal || selectedTransfer.value?.id_perusahaan || filters.companyId
  );
}

async function loadTransfers() {
  journalWarning.value = '';
  loading.value = true;
  errorMessage.value = '';
  feedback.value = '';

  try {
    const response = await getStockTransfers({
      id_cabang: filters.branchId || undefined,
      id_perusahaan: filters.companyId || undefined,
      status: !isStatusPage.value && config.value.statuses.length === 1 ? config.value.statuses[0] : undefined
    });
    items.value = normalizeList(unwrapResponse(response));
    feedback.value = `${config.value.title} memuat ${filteredRows.value.length.toLocaleString('id-ID')} baris.`;
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Daftar proses stok transfer belum bisa dimuat.');
    items.value = [];
  } finally {
    loading.value = false;
  }
}

function reset() {
  filters.companyId = canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
  filters.branchId = !canAccessAllBranches.value && fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  filters.principalId = '';
  filters.status = '';
  filters.search = '';
  syncBranchFromCompany();
  loadTransfers();
}

function detailQuantityKey(row) {
  if (mode.value === 'receipt') return 'jumlah_picked';
  if (mode.value === 'escalation' && String(row?.status) === '-2') return 'jumlah_ditolak';
  if (mode.value === 'status' && String(row?.status) === '3') return 'jumlah_diterima';
  if (mode.value === 'status' && String(row?.status) === '-2') return 'jumlah_ditolak';
  return 'jumlah';
}

function resetModalState() {
  modalError.value = '';
  detailRows.value = [];
  selectedTransfer.value = null;
  processForm.armada = '';
  processForm.pengambilan_oleh = '';
  processForm.tanggal_ambil = toLocalDateInputValue();
  fleetError.value = '';
}

async function openDetail(row) {
  resetModalState();
  selectedTransfer.value = row;
  detailModalOpen.value = true;
  detailLoading.value = true;

  try {
    const response = await getStockTransferDetail({
      id: row.id || row.id_stock_transfer,
      select_jumlah: detailQuantityKey(row)
    });
    detailRows.value = normalizeList(unwrapResponse(response)).map((item) => ({
      ...item,
      uom_1: Number(item.uom_1 || 0),
      uom_2: Number(item.uom_2 || 0),
      uom_3: Number(item.uom_3 || 0),
      keterangan: item.keterangan || ''
    }));
    processForm.armada = row.id_armada ? String(row.id_armada) : '';
    processForm.pengambilan_oleh = row.pengambilan_oleh || '';
    processForm.tanggal_ambil = row.tanggal_ambil || toLocalDateInputValue();
    await loadFleets(
      row.id_cabang_awal || row.id_cabang_tujuan || filters.branchId,
      row.id_perusahaan_awal || row.id_perusahaan || filters.companyId
    );
  } catch (error) {
    modalError.value = normalizeError(error, 'Detail stok transfer belum bisa dimuat.');
  } finally {
    detailLoading.value = false;
  }
}

function closeDetailModal() {
  detailModalOpen.value = false;
  resetModalState();
}

function buildProductPayload() {
  return detailRows.value.map((item) => ({
    id_stock_transfer: Number(selectedTransfer.value?.id || selectedTransfer.value?.id_stock_transfer),
    id_produk: Number(item.id_produk),
    id_principal: Number(item.id_principal || 0),
    pieces: Number(item.uom_1 || 0),
    box: Number(item.uom_2 || 0),
    carton: Number(item.uom_3 || 0),
    uom1: Number(item.uom_1 || 0),
    uom2: Number(item.uom_2 || 0),
    uom3: Number(item.uom_3 || 0),
    uom_1: Number(item.uom_1 || 0),
    uom_2: Number(item.uom_2 || 0),
    uom_3: Number(item.uom_3 || 0),
    keterangan: item.keterangan || ''
  }));
}

async function runModalAction(action) {
  modalError.value = '';
  feedback.value = '';
  journalWarning.value = '';

  if (!selectedTransfer.value || !detailRows.value.length) {
    modalError.value = 'Detail stok transfer belum tersedia.';
    return;
  }

  if (action === 'confirm' && !processForm.armada) {
    modalError.value = 'Pilih armada terlebih dahulu sebelum konfirmasi transfer.';
    return;
  }

  if (
    action === 'confirm'
    && !fleetOptions.value.some((item) => String(item.value) === String(processForm.armada))
  ) {
    modalError.value = 'Armada tidak tersedia pada cakupan transfer ini. Muat ulang detail lalu pilih armada kembali.';
    return;
  }

  actionLoading.value = true;

  try {
    const idTransfer = selectedTransfer.value.id || selectedTransfer.value.id_stock_transfer;
    const products = buildProductPayload();

    if (action === 'confirm') {
      await confirmStockTransfer({
        id_stock_transfer: idTransfer,
        id_cabang_awal: selectedTransfer.value.id_cabang_awal,
        armada: Number(processForm.armada),
        products
      });
      feedback.value = `Transfer ${selectedTransfer.value.nota_stock_transfer || idTransfer} berhasil dikonfirmasi.`;
    } else if (action === 'admin') {
      await adminConfirmStockTransfer({
        id: idTransfer,
        pengambilan_oleh: processForm.pengambilan_oleh,
        tanggal_ambil: processForm.tanggal_ambil,
        products
      });
      feedback.value = `Pengiriman ${selectedTransfer.value.nota_stock_transfer || idTransfer} berhasil diproses.`;
    } else if (action === 'receive') {
      const response = await receiveStockTransfer({
        id_stock_transfer: idTransfer,
        id_cabang_tujuan: selectedTransfer.value.id_cabang_tujuan,
        id_user: authStore.user?.id,
        list_produk: products
      });
      journalWarning.value = transferJournalWarning(unwrapResponse(response));
      feedback.value = `Penerimaan ${selectedTransfer.value.nota_stock_transfer || idTransfer} berhasil diproses.`;
    } else if (action === 'reject') {
      await rejectStockTransfer({
        id_stock_transfer: idTransfer,
        id_cabang_awal: selectedTransfer.value.id_cabang_awal,
        list_produk: products
      });
      feedback.value = `Transfer ${selectedTransfer.value.nota_stock_transfer || idTransfer} berhasil ditolak dan masuk eskalasi.`;
    } else if (action === 'close-escalation') {
      const response = await closeEscalatedStockTransfer({
        id_stock_transfer: idTransfer,
        id_cabang_tujuan: selectedTransfer.value.id_cabang_tujuan,
        id_user: authStore.user?.id,
        list_produk: products
      });
      journalWarning.value = transferJournalWarning(unwrapResponse(response));
      feedback.value = `Eskalasi ${selectedTransfer.value.nota_stock_transfer || idTransfer} berhasil ditutup.`;
    }

    const completedFeedback = feedback.value;
    const completedJournalWarning = journalWarning.value;
    closeDetailModal();
    await loadTransfers();
    feedback.value = completedFeedback;
    journalWarning.value = completedJournalWarning;
  } catch (error) {
    modalError.value = normalizeError(error, 'Aksi stok transfer belum berhasil diproses.');
  } finally {
    actionLoading.value = false;
  }
}

function exportData() {
  exportRowsToCsv(
    `stock-transfer-${mode.value}-${toLocalDateInputValue()}.csv`,
    [
      { label: 'ID', key: 'id' },
      { label: 'Nota', key: 'nota_stock_transfer' },
      { label: 'Cabang', key: 'route_label' },
      { label: 'Perusahaan', key: 'company_label' },
      { label: 'Principal', key: 'nama_principal' },
      { label: 'Status', key: 'status_label' },
      { label: 'Tanggal', key: 'tanggal_label' },
      { label: 'Armada', key: 'armada_label' },
      { label: 'Qty Proses', key: 'jumlah_status' }
    ],
    filteredRows.value
  );
}

watch(
  () => route.meta.processMode,
  () => {
    filters.status = '';
    journalWarning.value = '';
    loadTransfers();
  }
);

onMounted(async () => {
  await loadOptions();
  await loadFleets(filters.branchId, filters.companyId);
  await loadTransfers();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader :title="config.title" :description="config.description">
      <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800" @click="exportData">
        Export CSV
      </button>
    </PageHeader>

    <AppFilterBar
      :model-value="filters"
      :fields="[
        { key: 'companyId', label: 'Perusahaan', type: 'search-select', options: companyOptions, disabled: canUseLoginScope && !!fallbackCompanyId },
        { key: 'branchId', label: 'Cabang', type: 'search-select', options: branchOptions, disabled: !filters.companyId || (!canAccessAllBranches && !!fallbackBranchId) },
        { key: 'principalId', label: 'Principal', type: 'search-select', options: principalOptions, disabled: !filters.companyId },
        { key: 'status', label: 'Status', type: 'search-select', options: visibleStatusOptions },
        { key: 'search', label: 'Cari', placeholder: 'Nota, cabang, principal, armada' }
      ]"
      @update:model-value="Object.assign(filters, $event); syncBranchFromCompany()"
      @submit="loadTransfers"
      @reset="reset"
    />

    <section class="grid gap-4 md:grid-cols-4">
      <article v-for="item in summaryCards" :key="item.label" class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">{{ item.label }}</p>
        <p class="mt-3 text-lg font-semibold text-slate-900 dark:text-white">{{ item.value }}</p>
      </article>
    </section>

    <div v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200">
      {{ feedback }}
    </div>
    <div v-if="journalWarning" role="alert" class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
      {{ journalWarning }}
    </div>
    <div v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
      {{ errorMessage }}
    </div>

    <AppTable
      :rows="filteredRows"
      :columns="[
        { key: 'nota_stock_transfer', label: 'Nota' },
        { key: 'tanggal_label', label: 'Tanggal' },
        { key: 'route_label', label: 'Cabang' },
        { key: 'company_label', label: 'Perusahaan' },
        { key: 'nama_principal', label: 'Principal' },
        { key: 'jumlah_status', label: 'Qty' },
        { key: 'armada_label', label: 'Armada' },
        { key: 'status_label', label: 'Status' }
      ]"
      :loading="loading"
      :clickable-rows="true"
      :empty-message="config.empty"
      @row-click="openDetail"
    />

    <AppModal
      :open="detailModalOpen"
      :title="selectedTransfer?.nota_stock_transfer || 'Detail Stok Transfer'"
      :description="modalDescription"
      size="7xl"
      @close="closeDetailModal"
    >
      <div class="space-y-5">
        <section class="grid gap-3 md:grid-cols-4">
          <article v-for="item in selectedSummaryCards" :key="item.label" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-950">
            <p class="text-xs uppercase tracking-[0.22em] text-slate-400">{{ item.label }}</p>
            <p class="mt-2 font-semibold text-slate-900 dark:text-white">{{ item.value }}</p>
          </article>
        </section>

        <section class="grid gap-3 md:grid-cols-4">
          <article v-for="item in detailSummary" :key="item.label" class="rounded-2xl border border-slate-200 px-4 py-3 dark:border-slate-700">
            <p class="text-xs uppercase tracking-[0.22em] text-slate-400">{{ item.label }}</p>
            <p class="mt-2 font-semibold text-slate-900 dark:text-white">{{ item.value }}</p>
          </article>
        </section>

        <section v-if="mode === 'confirmation'" class="grid gap-3 md:grid-cols-2">
          <AppSearchSelect v-model="processForm.armada" label="Armada" placeholder="Pilih armada" :options="fleetOptions" :loading="fleetLoading" empty-text="Armada belum tersedia untuk cabang/perusahaan transfer ini." />
          <div class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
            Pastikan qty picked sesuai jumlah barang yang akan dibooking dari cabang asal.
          </div>
        </section>

        <div v-if="mode === 'confirmation' && fleetError" class="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
          <span>{{ fleetError }}</span>
          <button type="button" class="rounded-xl border border-rose-300 px-3 py-2 text-xs font-semibold text-rose-700 hover:bg-rose-100 disabled:opacity-60 dark:border-rose-400/50 dark:text-rose-200 dark:hover:bg-rose-500/10" :disabled="fleetLoading" @click="reloadSelectedFleets">
            Muat Ulang Armada
          </button>
        </div>

        <section v-if="mode === 'shipment'" class="grid gap-3 md:grid-cols-2">
          <AppFormField v-model="processForm.pengambilan_oleh" label="Pengambilan oleh" placeholder="Nama pengambil / driver" />
          <AppFormField v-model="processForm.tanggal_ambil" label="Tanggal ambil" type="date" />
        </section>

        <div v-if="modalError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
          {{ modalError }}
        </div>

        <div class="overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-700">
          <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-700">
            <thead class="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-950 dark:text-slate-400">
              <tr>
                <th class="px-4 py-3">Produk</th>
                <th class="px-4 py-3">Principal</th>
                <th class="px-4 py-3 text-right">Request</th>
                <th class="px-4 py-3 text-right">Picked</th>
                <th class="px-4 py-3 text-right">Diterima</th>
                <th class="px-4 py-3">UOM 1</th>
                <th class="px-4 py-3">UOM 2</th>
                <th class="px-4 py-3">UOM 3</th>
                <th class="px-4 py-3">Catatan</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-200 dark:divide-slate-800">
              <tr v-if="detailLoading">
                <td colspan="9" class="px-4 py-8 text-center text-slate-500">Memuat detail stok transfer...</td>
              </tr>
              <tr v-else-if="!detailRows.length">
                <td colspan="9" class="px-4 py-8 text-center text-slate-500">Detail produk belum tersedia.</td>
              </tr>
              <tr v-for="item in detailRows" v-else :key="`${item.id_stock_transfer}-${item.id_produk}`" class="text-slate-700 dark:text-slate-200">
                <td class="px-4 py-3">
                  <p class="font-semibold text-slate-900 dark:text-white">{{ item.nama_produk || '-' }}</p>
                  <p class="text-xs text-slate-500">{{ item.kode_sku || item.id_produk }}</p>
                </td>
                <td class="px-4 py-3">{{ item.nama_principal || '-' }}</td>
                <td class="px-4 py-3 text-right">{{ Number(item.jumlah || 0).toLocaleString('id-ID') }}</td>
                <td class="px-4 py-3 text-right">{{ Number(item.jumlah_picked || 0).toLocaleString('id-ID') }}</td>
                <td class="px-4 py-3 text-right">{{ Number(item.jumlah_diterima || 0).toLocaleString('id-ID') }}</td>
                <td class="px-4 py-3">
                  <p class="mb-1 text-xs text-slate-500">{{ item.uom_1_label }}<span v-if="item.uom_1_factor"> × {{ item.uom_1_factor }}</span></p>
                  <input v-model.number="item.uom_1" type="number" min="0" step="any" class="w-24 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950" :disabled="mode === 'status' || !canProcessWarehouseAction || !item.uom_1_configured" />
                </td>
                <td class="px-4 py-3">
                  <p class="mb-1 text-xs text-slate-500">{{ item.uom_2_label }}<span v-if="item.uom_2_factor"> × {{ item.uom_2_factor }}</span></p>
                  <input v-model.number="item.uom_2" type="number" min="0" step="any" class="w-24 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950" :disabled="mode === 'status' || !canProcessWarehouseAction || !item.uom_2_configured" />
                </td>
                <td class="px-4 py-3">
                  <p class="mb-1 text-xs text-slate-500">{{ item.uom_3_label }}<span v-if="item.uom_3_factor"> × {{ item.uom_3_factor }}</span></p>
                  <input v-model.number="item.uom_3" type="number" min="0" step="any" class="w-24 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950" :disabled="mode === 'status' || !canProcessWarehouseAction || !item.uom_3_configured" />
                </td>
                <td class="px-4 py-3">
                  <input v-model="item.keterangan" type="text" class="min-w-48 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950" :disabled="mode === 'status' || !canProcessWarehouseAction" placeholder="Catatan selisih / penerimaan" />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <template #footer>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800" @click="closeDetailModal">
            Tutup
          </button>
          <div class="flex flex-wrap gap-2">
            <button v-if="canConfirmSelected" class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60" :disabled="actionLoading || detailLoading || fleetLoading || !processForm.armada" @click="runModalAction('confirm')">
              Approval Stok Transfer
            </button>
            <button v-if="canAdminConfirmSelected" class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60" :disabled="actionLoading || detailLoading" @click="runModalAction('admin')">
              Proses Pengiriman
            </button>
            <button v-if="canReceiveSelected" class="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60" :disabled="actionLoading || detailLoading" @click="runModalAction('receive')">
              Terima Barang
            </button>
            <button v-if="canRejectSelected" class="rounded-xl border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-600 disabled:opacity-60 dark:border-rose-500/40 dark:text-rose-300" :disabled="actionLoading || detailLoading" @click="runModalAction('reject')">
              Tolak / Eskalasi
            </button>
            <button v-if="canCloseEscalationSelected" class="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60" :disabled="actionLoading || detailLoading" @click="runModalAction('close-escalation')">
              Close Eskalasi
            </button>
          </div>
        </div>
      </template>
    </AppModal>
  </div>
</template>
