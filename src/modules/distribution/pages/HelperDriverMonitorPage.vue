<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import { getBranches, getCompanies } from '@/api/master';
import {
  getHelperDriverAssignments,
  getHelperDriverDashboard,
  getHelperDriverLatestTracking
} from '@/api/helperDriver';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getLoginCompanyId, getRowBranchIds, getRowCompanyId, isSuperUser } from '@/utils/accessScope';
import { getBranchOptionsForCompany, getCompanyOptionsForScope } from '@/utils/filterScope';
import { toLocalDateInputValue } from '@/utils/date';

const authStore = useAuthStore();

const filters = reactive({
  branchId: '',
  companyId: '',
  date: toLocalDateInputValue(),
  type: '',
  status: '',
  search: ''
});

const companyRows = ref([]);
const branchRows = ref([]);
const loading = ref(false);
const errorMessage = ref('');
const summary = ref({});
const assignments = ref([]);
const trackingRows = ref([]);
const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(authStore.user));
const canUseLoginScope = computed(() => !isSuperUser(authStore));

function companyIdsForBranch(branchId) {
  if (!branchId) return [];

  const ids = new Set();
  const branch = branchRows.value.find((item) => String(item.id) === String(branchId));
  const branchCompanyId = getRowCompanyId(branch);

  if (branchCompanyId) ids.add(String(branchCompanyId));

  companyRows.value.forEach((item) => {
    if (getRowBranchIds(item).includes(String(branchId))) {
      ids.add(String(item.id));
    }
  });

  return Array.from(ids);
}

const companyOptions = computed(() => getCompanyOptionsForScope(companyRows.value, authStore));

const branchOptions = computed(() =>
  getBranchOptionsForCompany(branchRows.value, authStore, filters.companyId)
);

const statusOptions = [
  { value: '', label: 'Semua Status' },
  { value: 'scheduled', label: 'Terjadwal' },
  { value: 'loaded', label: 'Barang Dimuat' },
  { value: 'on_route', label: 'Dalam Perjalanan' },
  { value: 'arrived', label: 'Sampai Lokasi' },
  { value: 'delivered', label: 'Terkirim' },
  { value: 'failed', label: 'Gagal Kirim' },
  { value: 'return_pickup', label: 'Ambil Retur' },
  { value: 'return_picked', label: 'Retur Diambil' },
  { value: 'returned_to_warehouse', label: 'Retur Diterima Gudang' }
];

const typeOptions = [
  { value: '', label: 'Semua Tipe' },
  { value: 'delivery', label: 'Pengiriman' },
  { value: 'return', label: 'Retur' }
];

const filterFields = computed(() => [
  { key: 'companyId', label: 'Perusahaan', type: 'search-select', options: companyOptions.value, disabled: canUseLoginScope.value && !!fallbackCompanyId.value },
  { key: 'branchId', label: 'Cabang', type: 'search-select', options: branchOptions.value, disabled: !filters.companyId || (!isSuperUser(authStore) && !!fallbackBranchId.value) },
  { key: 'date', label: 'Tanggal', type: 'date' },
  { key: 'type', label: 'Tipe', type: 'search-select', options: typeOptions },
  { key: 'status', label: 'Status', type: 'search-select', options: statusOptions },
  { key: 'search', label: 'Cari', placeholder: 'No referensi, customer, alamat, status' }
]);

const statCards = computed(() => [
  { label: 'Total Tugas', value: summary.value.total_tasks || 0 },
  { label: 'Pengiriman', value: summary.value.total_delivery || 0 },
  { label: 'Retur', value: summary.value.total_return || 0 },
  { label: 'Aktif', value: summary.value.total_active || 0 },
  { label: 'Selesai', value: summary.value.total_done || 0 },
  { label: 'Gagal', value: summary.value.total_failed || 0 }
]);

const filteredAssignments = computed(() => {
  const query = filters.search.trim().toLowerCase();
  if (!query) return assignments.value;
  return assignments.value.filter((item) =>
    [
      item.no_reference,
      item.customer_name,
      item.address,
      item.status_label,
      item.assignment_type_label
    ]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query))
  );
});

function unwrapData(response) {
  const data = unwrapResponse(response);
  return data?.data || data || {};
}

async function loadReferenceData() {
  const [companyResponse, branchResponse] = await Promise.all([getCompanies(), getBranches()]);
  companyRows.value = normalizeList(unwrapResponse(companyResponse));
  branchRows.value = normalizeList(unwrapResponse(branchResponse));

  if (!filters.companyId && canUseLoginScope.value && fallbackCompanyId.value) {
    filters.companyId = String(fallbackCompanyId.value);
  }
  if (!filters.branchId && !isSuperUser(authStore) && fallbackBranchId.value) {
    filters.branchId = String(fallbackBranchId.value);
  }
  syncBranchFromCompany();
}

function updateFilters(nextFilters) {
  const previousBranchId = filters.branchId;
  const previousCompanyId = filters.companyId;

  Object.assign(filters, nextFilters);

  if (filters.companyId !== previousCompanyId) {
    syncBranchFromCompany();
    return;
  }

  if (filters.branchId !== previousBranchId) {
    return;
  }
}

function syncBranchFromCompany() {
  if (!filters.companyId || !filters.branchId) {
    return;
  }

  if (!companyIdsForBranch(filters.branchId).includes(String(filters.companyId))) {
    filters.branchId = '';
  }
}

async function loadData() {
  loading.value = true;
  errorMessage.value = '';
  try {
    const params = {
      id_cabang: filters.branchId || fallbackBranchId.value || undefined,
      date: filters.date || undefined,
      type: filters.type || undefined,
      status: filters.status || undefined
    };

    const [dashboardResponse, assignmentResponse, trackingResponse] = await Promise.all([
      getHelperDriverDashboard({ id_cabang: params.id_cabang, date: filters.date || undefined }),
      getHelperDriverAssignments(params),
      getHelperDriverLatestTracking({ id_cabang: params.id_cabang })
    ]);

    const dashboardData = unwrapData(dashboardResponse);
    summary.value = dashboardData.summary || {};
    assignments.value = normalizeList(unwrapData(assignmentResponse));
    trackingRows.value = normalizeList(unwrapData(trackingResponse));
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Data helper driver belum bisa dimuat.');
  } finally {
    loading.value = false;
  }
}

function resetFilters() {
  filters.companyId = canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
  filters.branchId = !isSuperUser(authStore) && fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  syncBranchFromCompany();
  filters.date = toLocalDateInputValue();
  filters.type = '';
  filters.status = '';
  filters.search = '';
  loadData();
}

function mapUrl(row) {
  const lat = row.last_latitude || row.latitude;
  const lng = row.last_longitude || row.longitude;
  if (!lat || !lng) return '';
  return `https://www.google.com/maps/search/?api=1&query=${lat},${lng}`;
}

onMounted(async () => {
  try {
    await loadReferenceData();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Referensi cabang dan perusahaan belum bisa dimuat.');
  }
  await loadData();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Monitoring Armada"
      description="Pantau pengiriman, retur yang sudah di-ACC, dan posisi GPS kendaraan dari satu layar operasional."
    />

    <AppFilterBar
      :model-value="filters"
      :fields="filterFields"
      @update:model-value="updateFilters"
      @submit="loadData"
      @reset="resetFilters"
    />

    <div class="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
      <section v-for="item in statCards" :key="item.label" class="panel p-4">
        <p class="text-sm text-slate-500">{{ item.label }}</p>
        <p class="mt-2 text-2xl font-semibold text-slate-950">{{ item.value }}</p>
      </section>
    </div>

    <div v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ errorMessage }}
    </div>

    <section class="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
      <div class="space-y-3">
        <h3 class="text-base font-semibold text-slate-900">Tugas Driver</h3>
        <AppTable
          :rows="filteredAssignments"
          :columns="[
            { key: 'assignment_type_label', label: 'Tipe' },
            { key: 'no_reference', label: 'Referensi' },
            { key: 'customer_name', label: 'Customer' },
            { key: 'address', label: 'Alamat' },
            { key: 'status_label', label: 'Status' },
            { key: 'item_count', label: 'Item' },
            { key: 'last_tracked_at', label: 'GPS Terakhir' },
            {
              key: 'map',
              label: 'Map',
              render: (row) => mapUrl(row) ? 'Buka' : '-'
            }
          ]"
          :loading="loading"
          row-key="id"
          empty-message="Belum ada tugas helper driver untuk filter ini."
        />
      </div>

      <div class="space-y-3">
        <h3 class="text-base font-semibold text-slate-900">GPS Kendaraan Terakhir</h3>
        <div class="panel overflow-hidden">
          <div v-if="loading" class="p-5 text-sm text-slate-500">Memuat tracking...</div>
          <div v-else-if="!trackingRows.length" class="p-5 text-sm text-slate-500">Belum ada data GPS dari driver.</div>
          <div v-else class="divide-y divide-slate-100">
            <article v-for="row in trackingRows" :key="row.id" class="p-4">
              <div class="flex items-start justify-between gap-3">
                <div>
                  <p class="font-semibold text-slate-900">{{ row.driver_name || 'Driver' }}</p>
                  <p class="mt-1 text-sm text-slate-500">{{ row.no_pelat || row.fleet_name || 'Armada belum tercatat' }}</p>
                </div>
                <span class="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">{{ row.status || '-' }}</span>
              </div>
              <p class="mt-3 text-sm text-slate-700">{{ row.customer_name || row.no_reference || 'Tidak terikat tugas' }}</p>
              <p class="mt-1 text-xs text-slate-500">{{ row.latitude }}, {{ row.longitude }}</p>
              <a
                v-if="mapUrl(row)"
                :href="mapUrl(row)"
                target="_blank"
                class="mt-3 inline-flex rounded-xl border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Buka Maps
              </a>
            </article>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>
