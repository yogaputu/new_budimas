<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import { getPurchaseOrderDetail, getPurchaseOrdersPaged, importPurchaseOrderTemplate } from '@/api/purchase';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getLoginCompanyId, getRowBranchIds, getRowCompanyId, isSuperUser } from '@/utils/accessScope';
import { getBranchOptionsForCompany, getCompanyOptionsForScope } from '@/utils/filterScope';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import { useAuthStore } from '@/stores/auth';

const authStore = useAuthStore();
const router = useRouter();
const route = useRoute();

const filters = reactive({
  companyId: '',
  branchId: '',
  principalId: '',
  status: '',
  search: ''
});

const loading = ref(false);
const detailLoading = ref(false);
const errorMessage = ref('');
const companyRows = ref([]);
const branchRows = ref([]);
const principalRows = ref([]);
const rows = ref([]);
const orderSummary = ref({
  total: 0,
  request: 0,
  need_confirm: 0,
  in_transit: 0,
  closed: 0,
  nominal: 0
});
const pagination = reactive({
  page: 1,
  perPage: 25,
  total: 0,
  totalPages: 1
});
const selectedRow = ref(null);
const selectedDetail = ref(null);
const detailModalOpen = ref(false);
const importModalOpen = ref(false);
const importLoading = ref(false);
const importFile = ref(null);
const importFileInputKey = ref(0);
const importErrorMessage = ref('');
const importSuccessMessage = ref('');
const importResult = ref(null);
const importForm = reactive({
  sourceType: 'lob',
  branchId: '',
  principalId: ''
});
const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(authStore.user));
const canAccessAllBranches = computed(() => isSuperUser(authStore));
const canUseLoginScope = computed(() => !canAccessAllBranches.value);

const statusOptions = [
  { value: '1', label: 'Request' },
  { value: '2', label: 'Need Confirm' },
  { value: '3', label: 'In Transit' },
  { value: '4', label: 'Closed' }
];

const filterFields = computed(() => [
  {
    key: 'companyId',
    label: 'Perusahaan',
    type: 'search-select',
    options: companyOptions.value,
    disabled: canUseLoginScope.value && !!fallbackCompanyId.value
  },
  {
    key: 'branchId',
    label: 'Cabang',
    type: 'search-select',
    options: branchOptions.value,
    disabled: (canUseLoginScope.value && !filters.companyId) || (!canAccessAllBranches.value && !!fallbackBranchId.value)
  },
  {
    key: 'principalId',
    label: 'Principal',
    type: 'search-select',
    options: filteredPrincipalOptions.value
  },
  {
    key: 'status',
    label: 'Status',
    type: 'search-select',
    options: statusOptions
  },
  {
    key: 'search',
    label: 'Cari',
    placeholder: 'Kode PO, nota incoming, kode/nama produk'
  }
]);

const companyOptions = computed(() => getCompanyOptionsForScope(companyRows.value, authStore));

const branchOptions = computed(() =>
  getBranchOptionsForCompany(branchRows.value, authStore, filters.companyId)
);

const filteredPrincipalOptions = computed(() =>
  principalRows.value
    .filter((item) => filters.companyId && String(item.id_perusahaan || '') === String(filters.companyId))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || '-'} - ${item.nama || item.principal_nama || 'Principal'}`
    }))
);

const importPrincipalOptions = computed(() => {
  const scopedCompanyIds = new Set(companyIdsForBranch(importForm.branchId));
  return principalRows.value
    .filter((item) => !scopedCompanyIds.size || scopedCompanyIds.has(String(item.id_perusahaan || '')))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || '-'} - ${item.nama || item.principal_nama || 'Principal'}`
    }));
});

function companyIdsForBranch(branchId) {
  if (!branchId) return [];

  const ids = new Set();
  const branch = branchRows.value.find((item) => String(item.id) === String(branchId));
  const directCompanyId = getRowCompanyId(branch);
  if (directCompanyId) ids.add(String(directCompanyId));

  companyRows.value.forEach((item) => {
    if (getRowBranchIds(item).some((id) => String(id) === String(branchId))) {
      ids.add(String(item.id));
    }
  });

  return [...ids];
}

function updateFilters(nextFilters) {
  Object.assign(filters, nextFilters || {});
  syncBranchFromCompany();
  syncPrincipalFromCompany();
}

function syncBranchFromCompany() {
  if (!filters.companyId) {
    if (canAccessAllBranches.value) filters.branchId = '';
    filters.principalId = '';
    return;
  }

  if (filters.branchId && !companyIdsForBranch(filters.branchId).includes(String(filters.companyId))) {
    filters.branchId = '';
    filters.principalId = '';
  }
}

function syncPrincipalFromCompany() {
  if (filters.principalId && !filteredPrincipalOptions.value.some((item) => item.value === String(filters.principalId))) {
    filters.principalId = '';
  }
}

const summaryCards = computed(() => {
  const total = Number(orderSummary.value.total || pagination.total || 0);
  const request = Number(orderSummary.value.request || 0);
  const needConfirm = Number(orderSummary.value.need_confirm || 0);
  const inTransit = Number(orderSummary.value.in_transit || 0);
  const closed = Number(orderSummary.value.closed || 0);
  const nominal = Number(orderSummary.value.nominal || 0);
  return [
    { label: 'Total PO', value: String(total) },
    { label: 'Request', value: String(request) },
    { label: 'Need Confirm', value: String(needConfirm) },
    { label: 'In Transit', value: String(inTransit) },
    { label: 'Closed', value: String(closed) },
    { label: 'Nilai PO', value: formatCurrency(nominal) }
  ];
});

const tableRows = computed(() =>
  rows.value
    .map((item) => ({
      ...item,
      status_label: resolveOrderStatus(item.proses_id_berjalan),
      principal_label: item.principal_nama || '-',
      cabang_label: item.cabang_nama || '-',
      nota_incoming_label: item.nota_incoming || '-',
      request_pic_label: item.pic_order_nama || '-',
      confirm_pic_label: item.pic_konfirmasi_nama || '-'
    }))
);

const detailProductRows = computed(() =>
  normalizeList(selectedDetail.value?.detail).map((item, index) => {
    const qtyRows = normalizeList(item.jumlah);
    const derivedSubtotal = qtyRows.reduce((sum, qty) => sum + Number(qty.subtotal || 0), 0);

    return {
      ...item,
      row_key: `${item.id || item.produk_kode || index}`,
      subtotal_label: formatCurrency(item.subtotal ?? derivedSubtotal),
      jumlah_ringkas: qtyRows
        .map((qty) => `${qty.jumlah || 0} ${qty.uom_kode || qty.uom_nama || ''}`.trim())
        .join(', ')
    };
  })
);

const detailMetaCards = computed(() => {
  if (!selectedDetail.value && !selectedRow.value) return [];

  const source = selectedDetail.value || selectedRow.value;
  return [
    { label: 'Status', value: resolveOrderStatus(source.proses_id_berjalan) },
    { label: 'Nilai PO', value: formatCurrency(source.total || 0) },
    { label: 'Total SKU', value: String(normalizeList(selectedDetail.value?.detail).length || 0) },
    { label: 'PIC Request', value: selectedDetail.value?.request_log?.user_nama || source.pic_order_nama || '-' },
    { label: 'Nota Incoming', value: selectedRow.value?.nota_incoming || '-' }
  ];
});

const canGoPreviousPage = computed(() => pagination.page > 1);
const canGoNextPage = computed(() => pagination.page < pagination.totalPages);
const pageRange = computed(() => {
  if (!pagination.total) return '0';
  const start = ((pagination.page - 1) * pagination.perPage) + 1;
  const end = Math.min(start + pagination.perPage - 1, pagination.total);
  return `${start}-${end}`;
});

const canEditSelectedOrder = computed(() => {
  const status = Number(selectedDetail.value?.proses_id_berjalan || selectedRow.value?.proses_id_berjalan || 0);
  return !!selectedRow.value && [1, 2].includes(status);
});

const nextActionHint = computed(() => {
  const status = Number(selectedDetail.value?.proses_id_berjalan || selectedRow.value?.proses_id_berjalan || 0);
  const map = {
    1: 'Purchase order masih di tahap request. Lanjutkan ke proses konfirmasi jika approval sudah siap.',
    2: 'Purchase order sudah menunggu konfirmasi. Tim gudang bisa lanjut ke input penerimaan barang.',
    3: 'Order sedang berjalan di transaksi penerimaan. Pantau receipt dan lanjutkan ke konfirmasi purchase.',
    4: 'Order sudah closed. Fokus berikutnya ada di tagihan dan pelunasan purchase.'
  };
  return map[status] || 'Pilih purchase order untuk membaca langkah operasional berikutnya.';
});

function resolveOrderStatus(value) {
  const key = Number(value || 0);
  const map = {
    1: { text: 'Request', className: 'inline-flex rounded-full bg-sky-100 px-3 py-1 text-xs font-semibold text-sky-700' },
    2: { text: 'Need Confirm', className: 'inline-flex rounded-full bg-rose-100 px-3 py-1 text-xs font-semibold text-rose-700' },
    3: { text: 'In Transit', className: 'inline-flex rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700' },
    4: { text: 'Closed', className: 'inline-flex rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700' }
  };
  return map[key] || { text: `Status ${key || '-'}`, className: 'inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600' };
}

function formatCurrency(value) {
  return `Rp ${new Intl.NumberFormat('id-ID').format(Number(value || 0))}`;
}

function editSelectedOrder() {
  const id = selectedDetail.value?.id || selectedRow.value?.id;
  if (!id) return;
  router.push(`/purchase/orders/edit/${id}`);
}

function resetFilters() {
  filters.companyId = canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
  filters.branchId = String(fallbackBranchId.value || '');
  filters.principalId = '';
  filters.status = '';
  filters.search = '';
  syncBranchFromCompany();
  pagination.page = 1;
  loadOrders();
}

function applyFilters() {
  pagination.page = 1;
  loadOrders();
}

function applyRouteFilters() {
  if (route.query.branchId) {
    filters.branchId = String(route.query.branchId);
  }
  if (route.query.companyId) {
    filters.companyId = String(route.query.companyId);
  }
  if (route.query.principalId) {
    filters.principalId = String(route.query.principalId);
  }
  if (route.query.search) {
    filters.search = String(route.query.search);
  }
  if (route.query.status) {
    filters.status = String(route.query.status);
  }
  if (route.query.page) {
    const page = Number(route.query.page);
    if (Number.isInteger(page) && page > 0) pagination.page = page;
  }
}

async function loadMeta() {
  const [companies, branches, principals] = await Promise.all([getCompanies(), getBranches(), getPrincipals()]);
  companyRows.value = normalizeList(unwrapResponse(companies));
  branchRows.value = normalizeList(unwrapResponse(branches));
  principalRows.value = normalizeList(unwrapResponse(principals));

  if (!filters.companyId && canUseLoginScope.value && fallbackCompanyId.value) {
    filters.companyId = String(fallbackCompanyId.value);
  }
  if (!filters.branchId && authStore.user?.id_cabang) {
    filters.branchId = String(fallbackBranchId.value || authStore.user.id_cabang);
  }
  syncBranchFromCompany();
}

async function loadOrders(page = pagination.page) {
  loading.value = true;
  errorMessage.value = '';
  try {
    const requestedPage = Math.max(1, Number(page || 1));
    const params = {
      page: requestedPage,
      per_page: pagination.perPage
    };
    if (filters.branchId) params.cabang_id = filters.branchId;
    if (filters.companyId) params.id_perusahaan = filters.companyId;
    if (filters.principalId) params.principal_id = filters.principalId;
    if (filters.status) params.status = filters.status;
    if (filters.search.trim()) params.search = filters.search.trim();

    const response = await getPurchaseOrdersPaged(params);
    const payload = unwrapResponse(response) || {};
    const meta = payload.meta || {};
    const summary = payload.summary || {};
    const nextRows = normalizeList(payload.rows || payload);
    const total = Number(meta.total ?? payload.total ?? nextRows.length ?? 0);

    rows.value = nextRows;
    pagination.page = Math.max(1, Number(meta.page || requestedPage));
    pagination.perPage = Math.max(10, Number(meta.per_page || pagination.perPage || 25));
    pagination.total = Math.max(0, total);
    pagination.totalPages = Math.max(1, Number(meta.total_pages || Math.ceil(total / pagination.perPage) || 1));
    orderSummary.value = {
      total: Number(summary.total ?? total),
      request: Number(summary.request || 0),
      need_confirm: Number(summary.need_confirm || 0),
      in_transit: Number(summary.in_transit || 0),
      closed: Number(summary.closed || 0),
      nominal: Number(summary.nominal || 0)
    };
  } catch (error) {
    rows.value = [];
    pagination.total = 0;
    pagination.totalPages = 1;
    orderSummary.value = {
      total: 0,
      request: 0,
      need_confirm: 0,
      in_transit: 0,
      closed: 0,
      nominal: 0
    };
    errorMessage.value = normalizeError(error, 'Daftar purchase order belum bisa dimuat.');
  } finally {
    loading.value = false;
  }
}

function changePage(direction) {
  const nextPage = Math.min(
    Math.max(1, pagination.page + direction),
    pagination.totalPages || 1
  );
  if (nextPage !== pagination.page) loadOrders(nextPage);
}

function changePageSize() {
  pagination.page = 1;
  loadOrders();
}

async function openDetail(row) {
  selectedRow.value = row;
  selectedDetail.value = null;
  detailModalOpen.value = true;
  detailLoading.value = true;
  errorMessage.value = '';
  try {
    const response = await getPurchaseOrderDetail(row.id);
    selectedDetail.value = unwrapResponse(response);
  } catch (error) {
    selectedDetail.value = null;
    errorMessage.value = normalizeError(error, 'Detail purchase order belum bisa dimuat.');
  } finally {
    detailLoading.value = false;
  }
}

function closeDetailModal() {
  detailModalOpen.value = false;
}

function openImportModal() {
  importForm.sourceType = 'lob';
  importForm.branchId = '';
  importForm.principalId = '';
  importFile.value = null;
  importFileInputKey.value += 1;
  importErrorMessage.value = '';
  importSuccessMessage.value = '';
  importResult.value = null;
  importModalOpen.value = true;
}

function selectImportSource(sourceType) {
  importForm.sourceType = sourceType;
  importErrorMessage.value = '';
  importSuccessMessage.value = '';
  importResult.value = null;
  if (sourceType === 'lob') {
    // LOB boleh memuat lebih dari satu kombinasi cabang/principal dari export DOI.
    // Jangan sisakan filter BD yang dapat menolak baris LOB tanpa disengaja.
    importForm.branchId = '';
    importForm.principalId = '';
  }
}

function closeImportModal() {
  if (!importLoading.value) {
    importModalOpen.value = false;
  }
}

function onImportFileChange(event) {
  importFile.value = event.target?.files?.[0] || null;
  importErrorMessage.value = '';
  importSuccessMessage.value = '';
  importResult.value = null;
}

async function submitImportTemplate() {
  importErrorMessage.value = '';
  importSuccessMessage.value = '';
  importResult.value = null;

  if (!importFile.value) {
    importErrorMessage.value = 'Pilih file Excel (.xlsx) terlebih dahulu.';
    return;
  }
  if (importForm.sourceType === 'bd' && !importForm.branchId) {
    importErrorMessage.value = 'Cabang tujuan wajib dipilih untuk impor Form Order Barang (BD).';
    return;
  }

  const formData = new FormData();
  formData.append('file', importFile.value);
  formData.append('source_type', importForm.sourceType);
  if (importForm.branchId) formData.append('cabang_id', importForm.branchId);
  if (importForm.principalId) formData.append('principal_id', importForm.principalId);

  importLoading.value = true;
  try {
    const response = await importPurchaseOrderTemplate(formData);
    const payload = unwrapResponse(response) || {};
    importResult.value = payload;
    const orders = normalizeList(payload.created_orders);
    importSuccessMessage.value = payload.message || `${orders.length} Purchase Order berhasil dibuat.`;
    await loadOrders(1);
  } catch (error) {
    importErrorMessage.value = normalizeError(error, 'Import Purchase Order belum berhasil diproses.');
  } finally {
    importLoading.value = false;
  }
}

watch(
  () => filters.companyId,
  () => {
    syncBranchFromCompany();
    syncPrincipalFromCompany();
  }
);

watch(
  () => filters.branchId,
  () => syncPrincipalFromCompany()
);

watch(
  () => importForm.branchId,
  () => {
    if (importForm.principalId && !importPrincipalOptions.value.some((item) => item.value === String(importForm.principalId))) {
      importForm.principalId = '';
    }
  }
);

onMounted(async () => {
  applyRouteFilters();
  await loadMeta();
  await loadOrders();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Purchase Order"
      description="Fase pertama modul purchase untuk memantau permintaan pembelian, status proses, dan detail item order dari API lama."
    >
      <button class="rounded-xl border border-brand-200 bg-white px-4 py-3 text-sm font-semibold text-brand-700 hover:bg-brand-50" @click="openImportModal">
        Import PO Excel
      </button>
    </PageHeader>

    <AppFilterBar :model-value="filters" :fields="filterFields" @update:model-value="updateFilters" @submit="applyFilters" @reset="resetFilters" />

    <section v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ errorMessage }}
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
      <article v-for="item in summaryCards" :key="item.label" class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">{{ item.label }}</p>
        <p class="mt-3 text-lg font-semibold text-slate-900">{{ item.value }}</p>
      </article>
    </section>

    <section class="flex flex-wrap gap-3">
      <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white" @click="router.push('/purchase/orders/create')">
        Buat Purchase Order
      </button>
      <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700" @click="router.push('/purchase/receipts/create')">
        Input Penerimaan Barang
      </button>
      <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700" @click="router.push('/purchase/order-reports')">
        Laporan Purchase Order
      </button>
    </section>

    <section class="min-w-0 space-y-3">
      <h3 class="text-lg font-semibold text-slate-900">Daftar Purchase Order</h3>
      <AppTable
        :rows="tableRows"
        :columns="[
          { key: 'kode', label: 'Kode PO' },
          { key: 'nota_incoming_label', label: 'Nota Incoming' },
          { key: 'principal_label', label: 'Principal' },
          { key: 'cabang_label', label: 'Cabang' },
          { key: 'status_label', label: 'Status' },
          { key: 'request_pic_label', label: 'PIC Request' },
          { key: 'confirm_pic_label', label: 'PIC Confirm' }
        ]"
        :loading="loading"
        :paginated="false"
        :clickable-rows="true"
        empty-message="Belum ada purchase order pada filter ini."
        @row-click="openDetail"
      />

      <div v-if="!loading" class="flex flex-wrap items-center justify-between gap-3 px-1 text-sm text-slate-500">
        <span>Menampilkan {{ pageRange }} dari {{ pagination.total }} purchase order</span>
        <div class="flex flex-wrap items-center gap-2">
          <label class="flex items-center gap-2">
            <span>Per halaman</span>
            <select
              v-model.number="pagination.perPage"
              class="rounded-xl border border-slate-200 bg-white px-2 py-1.5 text-sm text-slate-700 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"
              @change="changePageSize"
            >
              <option :value="10">10</option>
              <option :value="25">25</option>
              <option :value="50">50</option>
              <option :value="100">100</option>
            </select>
          </label>
          <button
            class="rounded-xl border border-slate-200 px-3 py-1.5 font-medium text-slate-700 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200"
            :disabled="!canGoPreviousPage"
            @click="changePage(-1)"
          >
            Sebelumnya
          </button>
          <span class="px-1 font-medium text-slate-600 dark:text-slate-300">Hal {{ pagination.page }} / {{ pagination.totalPages }}</span>
          <button
            class="rounded-xl border border-slate-200 px-3 py-1.5 font-medium text-slate-700 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200"
            :disabled="!canGoNextPage"
            @click="changePage(1)"
          >
            Berikutnya
          </button>
        </div>
      </div>
    </section>

    <AppModal
      :open="detailModalOpen"
      :title="selectedRow?.kode || 'Detail Purchase Order'"
      :description="selectedDetail?.keterangan || selectedRow?.keterangan || 'Header, log proses, dan rincian item purchase order.'"
      size="6xl"
      @close="closeDetailModal"
    >
      <div v-if="detailLoading" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
        Memuat detail purchase order...
      </div>

      <div v-else-if="!selectedDetail" class="rounded-2xl border border-dashed border-slate-200 px-4 py-6 text-sm text-slate-500">
        Detail purchase order belum tersedia.
      </div>

      <div v-else class="space-y-5">
        <div class="rounded-2xl border border-brand-100 bg-brand-50 px-4 py-3 text-sm text-brand-700">
          {{ nextActionHint }}
        </div>

        <div v-if="canEditSelectedOrder" class="flex flex-wrap gap-3">
          <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white" @click="editSelectedOrder">
            Edit/Revisi PO
          </button>
          <p class="self-center text-xs text-slate-500">
            Revisi hanya tersedia sebelum PO masuk proses penerimaan barang.
          </p>
        </div>

        <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          <div v-for="card in detailMetaCards" :key="card.label" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">{{ card.label }}</p>
            <div class="mt-2 text-sm font-semibold text-slate-900">
              <span v-if="card.value && typeof card.value === 'object'" :class="card.value.className">{{ card.value.text }}</span>
              <span v-else>{{ card.value }}</span>
            </div>
          </div>
        </div>

        <div class="grid gap-3 md:grid-cols-2">
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Cabang</p>
            <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedRow?.cabang_label || selectedDetail.cabang_id || '-' }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Principal</p>
            <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedRow?.principal_label || selectedDetail.principal_id || '-' }}</p>
          </div>
        </div>

        <div class="grid gap-3 md:grid-cols-2">
          <div class="rounded-2xl border border-slate-200 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Request Log</p>
            <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedDetail.request_log?.user_nama || '-' }}</p>
            <p class="text-xs text-slate-500">{{ selectedDetail.request_log?.tanggal || '-' }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Konfirmasi Log</p>
            <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedDetail.konfirmasi_log?.user_nama || '-' }}</p>
            <p class="text-xs text-slate-500">{{ selectedDetail.konfirmasi_log?.tanggal || '-' }}</p>
          </div>
        </div>

        <div>
          <p class="mb-3 text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Rincian Produk</p>
          <AppTable
            :rows="detailProductRows"
            :columns="[
              { key: 'produk_kode', label: 'Kode Produk' },
              { key: 'produk_nama', label: 'Nama Produk' },
              { key: 'total_order', label: 'Total Order' },
              { key: 'total_tersisa', label: 'Sisa' },
              { key: 'subtotal_label', label: 'Subtotal' },
              { key: 'jumlah_ringkas', label: 'Rincian UOM' }
            ]"
            empty-message="Belum ada rincian produk pada purchase order ini."
          />
        </div>
      </div>
    </AppModal>

    <AppModal
      :open="importModalOpen"
      title="Import Purchase Order dari Excel"
      description="Gunakan file hasil ekspor Analisa DOI atau isi sheet Form Order Barang (BD) pada template yang sama."
      size="xl"
      :close-on-backdrop="!importLoading"
      @close="closeImportModal"
    >
      <div class="space-y-5">
        <div class="grid gap-3 sm:grid-cols-2">
          <button
            type="button"
            :class="[
              'rounded-2xl border p-4 text-left transition',
              importForm.sourceType === 'lob'
                ? 'border-brand-400 bg-brand-50 text-brand-800'
                : 'border-slate-200 bg-white text-slate-700 hover:border-brand-200'
            ]"
            @click="selectImportSource('lob')"
          >
            <p class="font-semibold">Analisa DOI (LOB)</p>
            <p class="mt-1 text-xs leading-5 opacity-80">Upload file yang diekspor dari menu Analisa DOI. Sistem membaca kolom <b>Final OB SPV</b>.</p>
          </button>
          <button
            type="button"
            :class="[
              'rounded-2xl border p-4 text-left transition',
              importForm.sourceType === 'bd'
                ? 'border-brand-400 bg-brand-50 text-brand-800'
                : 'border-slate-200 bg-white text-slate-700 hover:border-brand-200'
            ]"
            @click="selectImportSource('bd')"
          >
            <p class="font-semibold">Form Order Barang (BD)</p>
            <p class="mt-1 text-xs leading-5 opacity-80">Isi sheet BD: kolom A kode principal, B kode produk/distributor, dan D Qty Order (CTN).</p>
          </button>
        </div>

        <div v-if="importForm.sourceType === 'lob'" class="rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm leading-6 text-sky-800">
          File LOB harus berasal dari tombol <b>Export Excel</b> di Analisa DOI agar cabang, principal, dan produk dapat diverifikasi. Anda dapat mengubah angka pada kolom <b>Final OB SPV</b>; PO akan dipisahkan otomatis per cabang dan principal.
        </div>
        <div v-else class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-800">
          Sheet BD menggunakan qty dalam karton. Cabang tujuan wajib dipilih; principal di setiap baris dibaca dari kode principal pada kolom A.
        </div>

        <div class="grid gap-4 md:grid-cols-2">
          <label v-if="importForm.sourceType === 'bd'" class="block">
            <span class="mb-1.5 block text-sm font-medium text-slate-700">Cabang Tujuan <span class="text-rose-600">*</span></span>
            <select v-model="importForm.branchId" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none focus:border-brand-400">
              <option value="">Pilih cabang</option>
              <option v-for="item in branchOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
            </select>
          </label>
          <label v-if="importForm.sourceType === 'bd'" class="block">
            <span class="mb-1.5 block text-sm font-medium text-slate-700">Validasi Principal (opsional)</span>
            <select v-model="importForm.principalId" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none focus:border-brand-400">
              <option value="">Sesuai kode di file</option>
              <option v-for="item in importPrincipalOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
            </select>
          </label>
        </div>

        <label class="block">
          <span class="mb-1.5 block text-sm font-medium text-slate-700">File Excel <span class="text-rose-600">*</span></span>
          <input
            :key="importFileInputKey"
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none file:mr-3 file:rounded-lg file:border-0 file:bg-slate-100 file:px-3 file:py-2 file:text-sm file:font-medium"
            @change="onImportFileChange"
          >
          <p v-if="importFile" class="mt-2 text-xs text-slate-500">{{ importFile.name }} · {{ (importFile.size / 1024).toLocaleString('id-ID', { maximumFractionDigits: 1 }) }} KB</p>
        </label>

        <div v-if="importErrorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 whitespace-pre-line text-sm text-rose-700">
          {{ importErrorMessage }}
        </div>
        <div v-if="importSuccessMessage" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {{ importSuccessMessage }}
        </div>

        <div v-if="normalizeList(importResult?.created_orders).length" class="rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <p class="text-sm font-semibold text-slate-900">PO yang dibuat</p>
          <ul class="mt-2 space-y-1 text-sm text-slate-600">
            <li v-for="order in normalizeList(importResult?.created_orders)" :key="order.id">
              {{ order.kode }} · {{ order.cabang_nama || '-' }} · {{ order.principal_kode || order.principal_nama || '-' }} · {{ order.total_produk || 0 }} produk
            </li>
          </ul>
        </div>
      </div>

      <template #footer>
        <div class="flex flex-wrap justify-end gap-3">
          <button class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700" :disabled="importLoading" @click="closeImportModal">
            Batal
          </button>
          <button class="rounded-xl bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300" :disabled="importLoading" @click="submitImportTemplate">
            {{ importLoading ? 'Mengimpor...' : 'Import Purchase Order' }}
          </button>
        </div>
      </template>
    </AppModal>
  </div>
</template>
