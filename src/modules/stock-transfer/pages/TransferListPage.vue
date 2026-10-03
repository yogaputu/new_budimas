<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { getStockTransfers } from '@/api/stockTransfer';
import { getBranches, getCompanies } from '@/api/master';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getLoginCompanyId, isSuperUser } from '@/utils/accessScope';
import { getBranchOptionsForCompany, getCompanyOptionsForScope, getCompanyIdsForBranch } from '@/utils/filterScope';
import { transferCompanyIds, transferCompanyLabel } from '../companyScope';
import { exportRowsToCsv } from '@/utils/exportCsv';
import { toLocalDateInputValue } from '@/utils/date';
import { useAuthStore } from '@/stores/auth';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const router = useRouter();
const authStore = useAuthStore();

const filters = reactive({
  branchId: '',
  companyId: '',
  search: '',
  status: ''
});
const items = ref([]);
const branchRows = ref([]);
const companyRows = ref([]);
const loading = ref(false);
const errorMessage = ref('');
const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(authStore.user));
const canAccessAllBranches = computed(() => isSuperUser(authStore));
const canUseLoginScope = computed(() => !canAccessAllBranches.value);

const statusOptions = [
  { value: '0', label: 'Draft / Request' },
  { value: '1', label: 'Dikonfirmasi' },
  { value: '2', label: 'Dalam Pengiriman' },
  { value: '3', label: 'Diterima' },
  { value: '-2', label: 'Ditolak' }
];

const rows = computed(() =>
  items.value.map((item) => ({
    ...item,
    status_label: statusOptions.find((option) => String(option.value) === String(item.status))?.label || `Status ${item.status ?? '-'}`,
    route_label: `${item.nama_cabang_awal || item.id_cabang_awal || '-'} -> ${item.nama_cabang_tujuan || item.id_cabang_tujuan || '-'}`,
    company_label: transferCompanyLabel(item),
    created_label: item.created_at || item.tanggal_input || '-'
  }))
);

function companyIdsForBranch(branchId) {
  return getCompanyIdsForBranch(branchId, branchRows.value, companyRows.value);
}

const branchOptions = computed(() =>
  getBranchOptionsForCompany(branchRows.value, authStore, filters.companyId, false, companyRows.value)
);

const companyOptions = computed(() => getCompanyOptionsForScope(companyRows.value, authStore));

const filteredRows = computed(() => {
  const query = filters.search.trim().toLowerCase();
  return rows.value.filter((item) => {
    const branchIds = [
      item.id_cabang,
      item.id_cabang_awal,
      item.id_cabang_tujuan,
      item.cabang_id,
      item.branch_id
    ]
      .filter(Boolean)
      .map(String);
    const companyIds = transferCompanyIds(item);
    const matchBranch = !filters.branchId || branchIds.includes(String(filters.branchId));
    const matchCompany = !filters.companyId || companyIds.includes(String(filters.companyId));
    const matchStatus = !filters.status || String(item.status) === String(filters.status);
    const matchSearch =
      !query ||
      [item.id, item.nota_stock_transfer, item.route_label, item.company_label, item.status_label, item.created_label]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query));

    return matchBranch && matchCompany && matchStatus && matchSearch;
  });
});

async function loadOptions() {
  const [branchResponse, companyResponse] = await Promise.all([getBranches(), getCompanies()]);
  branchRows.value = normalizeList(unwrapResponse(branchResponse)).map((branch) => ({
    ...branch, id_cabang: branch.id_cabang || branch.id
  }));
  companyRows.value = normalizeList(unwrapResponse(companyResponse));

  if (!filters.companyId && canUseLoginScope.value && fallbackCompanyId.value) {
    filters.companyId = String(fallbackCompanyId.value);
  }
  if (!canAccessAllBranches.value && fallbackBranchId.value) {
    filters.branchId = String(fallbackBranchId.value);
  }
  syncBranchFromCompany();
}

function syncBranchFromCompany() {
  if (!filters.companyId || !filters.branchId) {
    return;
  }
  if (!companyIdsForBranch(filters.branchId).includes(String(filters.companyId))) {
    filters.branchId = '';
  }
}

async function loadTransfers() {
  loading.value = true;
  errorMessage.value = '';

  try {
    const response = await getStockTransfers({
      id_cabang: filters.branchId || undefined,
      id_perusahaan: filters.companyId || undefined,
      status: filters.status || undefined
    });
    items.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Daftar stok transfer belum bisa dimuat.');
    items.value = [];
  } finally {
    loading.value = false;
  }
}

function openDetail(row) {
  router.push({
    name: 'stock-transfer-detail',
    query: { id: row.id }
  });
}

function openCreate() {
  router.push({ name: 'stock-transfer-create' });
}

function reset() {
  filters.companyId = canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
  filters.branchId = !canAccessAllBranches.value && fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  syncBranchFromCompany();
  filters.search = '';
  filters.status = '';
  loadTransfers();
}

function exportTransfers() {
  exportRowsToCsv(
    `stock-transfer-${toLocalDateInputValue()}.csv`,
    [
      { label: 'ID', key: 'id' },
      { label: 'Nota', key: 'nota_stock_transfer' },
      { label: 'Cabang', key: 'route_label' },
      { label: 'Perusahaan', key: 'company_label' },
      { label: 'Status', key: 'status_label' },
      { label: 'Tanggal', key: 'created_label' },
      { label: 'Pengambil', key: 'pengambilan_oleh' }
    ],
    filteredRows.value
  );
}

onMounted(async () => {
  await loadOptions();
  loadTransfers();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader title="Stok Transfer" description="Daftar pengiriman stok transfer untuk operasional gudang dan cabang.">
      <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="exportTransfers">
        Export CSV
      </button>
      <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700" @click="openCreate">
        Buat Stok Transfer
      </button>
    </PageHeader>

    <AppFilterBar
      :model-value="filters"
      :fields="[
        { key: 'companyId', label: 'Perusahaan', type: 'search-select', options: companyOptions, disabled: canUseLoginScope && !!fallbackCompanyId },
        { key: 'branchId', label: 'Cabang', type: 'search-select', options: branchOptions, disabled: !filters.companyId || (!canAccessAllBranches && !!fallbackBranchId) },
        { key: 'search', label: 'Cari transfer', placeholder: 'Nota, cabang, status' },
        { key: 'status', label: 'Status', type: 'search-select', options: statusOptions }
      ]"
      @update:model-value="Object.assign(filters, $event); syncBranchFromCompany()"
      @submit="loadTransfers"
      @reset="reset"
    />

    <div v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ errorMessage }}
    </div>

    <AppTable
      :rows="filteredRows"
      :columns="[
        { key: 'id', label: 'ID' },
        { key: 'nota_stock_transfer', label: 'Nota' },
        { key: 'route_label', label: 'Cabang' },
        { key: 'company_label', label: 'Perusahaan' },
        { key: 'status_label', label: 'Status' },
        { key: 'created_label', label: 'Tanggal' },
        { key: 'pengambilan_oleh', label: 'Pengambil' }
      ]"
      :loading="loading"
      :clickable-rows="true"
      empty-message="Belum ada stok transfer."
      @row-click="openDetail"
    />
  </div>
</template>
