<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getDistributionHistory } from '@/api/distribution';
import { getBranches, getCompanies } from '@/api/master';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getRowBranchIds, getRowCompanyId, isSuperUser } from '@/utils/accessScope';
import { getBranchOptionsForCompany, getCompanyOptionsForScope } from '@/utils/filterScope';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();

const today = new Date();
const monthAgo = new Date(today.getFullYear(), today.getMonth() - 1, today.getDate());

const filters = reactive({
  branchId: '',
  companyId: '',
  periodeAwal: toDateInput(monthAgo),
  periodeAkhir: toDateInput(today),
  status: 'all',
  search: ''
});

const branchRows = ref([]);
const companyRows = ref([]);
const rows = ref([]);
const loading = ref(false);
const errorMessage = ref('');
const selectedRow = ref(null);
const detailOpen = ref(false);

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));

function toDateInput(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function formatDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }).format(date);
}

function companyIdsForBranch(branchId) {
  if (!branchId) return [];
  const ids = new Set();
  const branch = branchRows.value.find((item) => String(item.id) === String(branchId));
  const branchCompanyId = getRowCompanyId(branch);
  if (branchCompanyId) ids.add(String(branchCompanyId));
  companyRows.value.forEach((item) => {
    if (getRowBranchIds(item).includes(String(branchId))) ids.add(String(item.id));
  });
  return Array.from(ids);
}

const branchOptions = computed(() => getBranchOptionsForCompany(branchRows.value, authStore, filters.companyId));

const companyOptions = computed(() => getCompanyOptionsForScope(companyRows.value, authStore));

const normalizedRows = computed(() =>
  rows.value.map((item, index) => ({
    ...item,
    row_key: `${item.id_sales_order || item.id || item.no_faktur || index}-${index}`,
    status_label: Number(item.status_order) === 9 ? 'Realisasi' : 'Shipping',
    tanggal_label: formatDate(item.tanggal_terkirim || item.delivering_date),
    cabang_label: item.nama_cabang || item.kode_cabang || '-',
    perusahaan_label: item.nama_perusahaan || '-'
  }))
);

const filteredRows = computed(() => {
  const query = filters.search.trim().toLowerCase();
  return normalizedRows.value.filter((item) => {
    const statusMatch = filters.status === 'all' || String(item.status_order) === String(filters.status);
    if (!statusMatch) return false;
    if (!query) return true;
    return [
      item.no_faktur,
      item.no_order,
      item.nama_customer,
      item.kode_rute,
      item.nama_armada,
      item.status_label,
      item.tanggal_label
    ]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query));
  });
});

const summary = computed(() => ({
  total: filteredRows.value.length,
  shipping: filteredRows.value.filter((item) => Number(item.status_order) === 4).length,
  realisasi: filteredRows.value.filter((item) => Number(item.status_order) === 9).length
}));

function syncBranchFromCompany() {
  if (!filters.companyId || !filters.branchId) return;
  if (!companyIdsForBranch(filters.branchId).includes(String(filters.companyId))) {
    filters.branchId = '';
  }
}

async function loadOptions() {
  const [branchesResponse, companiesResponse] = await Promise.all([getBranches(), getCompanies()]);
  branchRows.value = normalizeList(unwrapResponse(branchesResponse));
  companyRows.value = normalizeList(unwrapResponse(companiesResponse));
  if (!filters.branchId && fallbackBranchId.value) filters.branchId = String(fallbackBranchId.value);
  syncBranchFromCompany();
}

async function loadRows() {
  loading.value = true;
  errorMessage.value = '';
  selectedRow.value = null;
  try {
    const response = await getDistributionHistory({
      id_cabang: filters.branchId || undefined,
      id_perusahaan: filters.companyId || undefined,
      periode_awal: filters.periodeAwal || undefined,
      periode_akhir: filters.periodeAkhir || undefined,
      field: 'id',
      order: 'desc',
      'no-paginate': true
    });
    rows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    rows.value = [];
    errorMessage.value = normalizeError(error, 'Riwayat distribusi belum bisa dimuat.');
  } finally {
    loading.value = false;
  }
}

function openDetail(row) {
  selectedRow.value = row;
  detailOpen.value = true;
}

function reset() {
  filters.branchId = String(fallbackBranchId.value || '');
  syncBranchFromCompany();
  filters.periodeAwal = toDateInput(monthAgo);
  filters.periodeAkhir = toDateInput(today);
  filters.status = 'all';
  filters.search = '';
  loadRows();
}

watch(() => filters.companyId, syncBranchFromCompany);

onMounted(async () => {
  await loadOptions();
  await loadRows();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Distribution History"
      description="Riwayat faktur distribusi yang sudah masuk tahap shipping atau realisasi, dengan filter Perusahaan -> Cabang."
    />

    <AppFilterBar
      :model-value="filters"
      :fields="[
        { key: 'companyId', label: 'Perusahaan', type: 'search-select', options: companyOptions },
        { key: 'branchId', label: 'Cabang', type: 'search-select', options: branchOptions, disabled: !filters.companyId || (!isSuperUser(authStore) && !!fallbackBranchId) },
        { key: 'periodeAwal', label: 'Dari Tanggal', type: 'date' },
        { key: 'periodeAkhir', label: 'Sampai Tanggal', type: 'date' },
        { key: 'status', label: 'Tahap', type: 'search-select', options: [
          { value: 'all', label: 'Semua Tahap' },
          { value: '4', label: 'Shipping' },
          { value: '9', label: 'Realisasi' }
        ] },
        { key: 'search', label: 'Cari', placeholder: 'Faktur, order, customer, rute, armada' }
      ]"
      @update:model-value="Object.assign(filters, $event)"
      @submit="loadRows"
      @reset="reset"
    />

    <div v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-semibold text-rose-700">
      {{ errorMessage }}
    </div>

    <section class="grid gap-4 md:grid-cols-3">
      <div class="panel p-5">
        <p class="text-xs font-black uppercase tracking-[0.2em] text-slate-400">Total Riwayat</p>
        <p class="mt-3 text-2xl font-black text-slate-900">{{ summary.total }}</p>
      </div>
      <div class="panel p-5">
        <p class="text-xs font-black uppercase tracking-[0.2em] text-slate-400">Shipping</p>
        <p class="mt-3 text-2xl font-black text-emerald-700">{{ summary.shipping }}</p>
      </div>
      <div class="panel p-5">
        <p class="text-xs font-black uppercase tracking-[0.2em] text-slate-400">Realisasi</p>
        <p class="mt-3 text-2xl font-black text-blue-700">{{ summary.realisasi }}</p>
      </div>
    </section>

    <AppTable
      :rows="filteredRows"
      :columns="[
        { key: 'no_faktur', label: 'No Faktur' },
        { key: 'no_order', label: 'No Order' },
        { key: 'nama_customer', label: 'Customer' },
        { key: 'kode_rute', label: 'Rute' },
        { key: 'nama_armada', label: 'Armada' },
        { key: 'tanggal_label', label: 'Tanggal Terkirim' },
        { key: 'status_label', label: 'Tahap' }
      ]"
      :loading="loading"
      :clickable-rows="true"
      row-key="row_key"
      empty-message="Belum ada riwayat distribusi pada filter ini."
      @row-click="openDetail"
    />

    <AppModal :open="detailOpen" title="Detail Riwayat Distribusi" size="lg" @close="detailOpen = false">
      <div v-if="selectedRow" class="grid gap-4 md:grid-cols-2">
        <div v-for="item in [
          ['No Faktur', selectedRow.no_faktur],
          ['No Order', selectedRow.no_order],
          ['Customer', selectedRow.nama_customer],
          ['Rute', selectedRow.kode_rute],
          ['Armada', selectedRow.nama_armada],
          ['Tanggal Terkirim', selectedRow.tanggal_label],
          ['Tahap', selectedRow.status_label],
          ['Perusahaan', selectedRow.perusahaan_label]
        ]" :key="item[0]" class="rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <p class="text-xs font-bold uppercase tracking-[0.18em] text-slate-400">{{ item[0] }}</p>
          <p class="mt-2 font-semibold text-slate-900">{{ item[1] || '-' }}</p>
        </div>
      </div>
    </AppModal>
  </div>
</template>
