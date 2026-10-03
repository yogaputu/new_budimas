<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies, getSales } from '@/api/master';
import { useAuthStore } from '@/app/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { scopeSalesRowsByLogin } from '@/utils/accessScope';
import { toLocalDateInputValue } from '@/utils/date';
import AppEmptyState from '@/shared/components/AppEmptyState.vue';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import api from '@/api/axios';
import {
  getSupervisorBranchOptions,
  getSupervisorCompanyOptions,
  resetSupervisorBranchWhenCompanyChanges,
  syncSupervisorCompanyFromBranch,
} from '@/modules/supervisor-sales/utils/supervisorScope';

const auth = useAuthStore();
const today = toLocalDateInputValue();

const filters = reactive({
  tanggal: today,
  branchId: '',
  companyId: '',
  salesUserId: '',
  status: ''
});

const companyRows = ref([]);
const branchRows = ref([]);
const salesRows = ref([]);
const rows = ref([]);
const visitRows = ref([]);
const loading = ref(false);
const error = ref('');
const feedback = ref('');
const selectedRow = ref(null);
const detailModalOpen = ref(false);

const fallbackBranchId = computed(() => auth.user?.id_cabang || auth.user?.cabang_id || auth.user?.cabang?.id || '');

const companyOptions = computed(() =>
  getSupervisorCompanyOptions(companyRows.value, branchRows.value, '', auth)
);

const branchOptions = computed(() => getSupervisorBranchOptions(branchRows.value, auth, false, filters.companyId, companyRows.value));

function syncCompanyFromBranch() {
  syncSupervisorCompanyFromBranch(filters, 'branchId', 'companyId', branchRows.value, companyRows.value);
}

const salesOptions = computed(() =>
  scopeSalesRowsByLogin(salesRows.value, auth)
    .filter((item) => !filters.branchId || String(item.id_cabang || item.cabang_id || '') === String(filters.branchId))
    .map((item) => ({
      value: String(item.id_user || item.id),
      label: `${item.kode_sales || '-'} - ${item.nama || 'Sales'}`
    }))
);

const statusOptions = [
  { value: 'belum-check-in', label: 'Belum Check In' },
  { value: 'check-in', label: 'Sudah Check In' },
  { value: 'lapangan', label: 'Masih di Lapangan' },
  { value: 'check-out', label: 'Sudah Check Out' }
];

const filterFields = computed(() => [
  { key: 'tanggal', label: 'Tanggal', type: 'date' },
  { key: 'companyId', label: 'Perusahaan', type: 'search-select', options: companyOptions.value, placeholder: 'Pilih perusahaan' },
  { key: 'branchId', label: 'Cabang', type: 'search-select', options: branchOptions.value, placeholder: 'Pilih cabang', disabled: !filters.companyId, emptyText: 'Pilih perusahaan terlebih dahulu.' },
  { key: 'salesUserId', label: 'Sales', type: 'search-select', options: salesOptions.value, placeholder: 'Semua sales', emptyText: 'Sales belum tersedia untuk filter ini.' },
  { key: 'status', label: 'Status Absensi', type: 'select', options: statusOptions }
]);

function updateFilters(nextFilters) {
  if (!nextFilters || typeof nextFilters !== 'object') return;
  Object.entries(nextFilters).forEach(([key, value]) => {
    if (Object.prototype.hasOwnProperty.call(filters, key)) {
      filters[key] = value;
    }
  });
}

const summary = computed(() => ({
  total: rows.value.length,
  checkedIn: rows.value.filter((row) => row.attendance_status !== 'Belum Check In').length,
  onField: rows.value.filter((row) => row.attendance_status === 'Masih di Lapangan').length,
  checkedOut: rows.value.filter((row) => row.attendance_status === 'Sudah Check Out').length
}));

const selectedKey = computed(() => selectedRow.value?.id_user || '');
const detailModalTitle = computed(() => (selectedRow.value?.nama_sales ? `Detail Aktivitas ${selectedRow.value.nama_sales}` : 'Detail Aktivitas Sales'));

const tableColumns = [
  { key: 'nama_sales', label: 'Sales' },
  { key: 'nama_cabang', label: 'Cabang' },
  { key: 'kode_sales', label: 'Kode Sales' },
  { key: 'total_kunjungan', label: 'Aktivitas', render: (row) => Number(row.total_kunjungan || 0) },
  { key: 'first_check_in_label', label: 'Check In Pertama' },
  { key: 'last_check_out_label', label: 'Check Out Terakhir' },
  { key: 'attendance_status', label: 'Status' }
];

const detailColumns = [
  { key: 'nama_customer', label: 'Customer' },
  { key: 'kode_customer', label: 'Kode' },
  { key: 'waktu_mulai', label: 'Check In', render: (row) => row.waktu_mulai || '-' },
  { key: 'waktu_selesai', label: 'Check Out', render: (row) => row.waktu_selesai || '-' },
  {
    key: 'status',
    label: 'Status Kunjungan',
    render: (row) => {
      if (Number(row.status || 0) === 2) return 'Selesai Kunjungan';
      if (Number(row.status || 0) === 1) return 'Check In';
      return 'Belum Kunjungan';
    }
  }
];

const selectedVisitRows = computed(() =>
  visitRows.value.filter((row) => String(row.id_user || '') === String(selectedRow.value?.id_user || ''))
);

function openActivityDetail(row) {
  selectedRow.value = row;
  detailModalOpen.value = true;
}

function closeActivityDetail() {
  detailModalOpen.value = false;
}

async function loadReferenceData() {
  const [companiesResponse, branchesResponse, salesResponse] = await Promise.all([getCompanies(), getBranches(), getSales()]);
  companyRows.value = normalizeList(unwrapResponse(companiesResponse));
  branchRows.value = normalizeList(unwrapResponse(branchesResponse));
  salesRows.value = normalizeList(unwrapResponse(salesResponse));
  syncCompanyFromBranch();
}

async function loadAttendance() {
  loading.value = true;
  error.value = '';
  feedback.value = '';

  try {
    const response = await api.get('/api/sales-kunjungan/supervisor-attendance-report', {
      params: {
        tanggal: filters.tanggal || today,
        id_perusahaan: filters.companyId || undefined,
        id_cabang: filters.branchId || undefined,
        id_user_sales: filters.salesUserId || undefined,
        status: filters.status || undefined
      }
    });

    const payload = unwrapResponse(response) || {};
    rows.value = normalizeList(payload.rows);
    visitRows.value = normalizeList(payload.visit_rows);
    feedback.value = payload.meta?.notes || `Absensi sales untuk ${filters.tanggal} berhasil dimuat.`;

    if (selectedRow.value) {
      selectedRow.value = rows.value.find((row) => String(row.id_user) === String(selectedRow.value?.id_user)) || null;
    }
  } catch (err) {
    error.value = normalizeError(err, 'Data absensi sales belum bisa dimuat.');
    rows.value = [];
    visitRows.value = [];
    selectedRow.value = null;
  } finally {
    loading.value = false;
  }
}

function resetFilters() {
  filters.tanggal = today;
  filters.branchId = auth.user?.supervised_sales?.length ? '' : String(fallbackBranchId.value || '');
  filters.companyId = '';
  filters.salesUserId = '';
  filters.status = '';
  syncCompanyFromBranch();
  loadAttendance();
}

onMounted(async () => {
  filters.branchId = auth.user?.supervised_sales?.length ? '' : String(fallbackBranchId.value || '');

  try {
    await loadReferenceData();
  } catch (err) {
    error.value = normalizeError(err, 'Referensi sales dan cabang belum bisa dimuat.');
  }

  await loadAttendance();
});

watch(
  () => filters.companyId,
  (value) => {
    if (!value) {
      filters.branchId = '';
      filters.salesUserId = '';
      return;
    }
    if (resetSupervisorBranchWhenCompanyChanges(filters, 'companyId', 'branchId', branchRows.value, auth, companyRows.value)) {
      filters.salesUserId = '';
    }
  }
);

watch(
  () => filters.branchId,
  (value) => {
    if (!value) {
      filters.salesUserId = '';
      return;
    }
    if (
      filters.salesUserId &&
      !salesRows.value.some(
        (item) =>
          String(item.id_user || item.id) === String(filters.salesUserId) &&
          (!filters.branchId || String(item.id_cabang || item.cabang_id || '') === String(filters.branchId))
      )
    ) {
      filters.salesUserId = '';
    }
  }
);
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Absensi Sales"
      description="Supervisor memantau kehadiran lapangan sales berdasarkan aktivitas check in dan check out kunjungan pada tanggal yang dipilih."
    >
      <div class="flex flex-wrap gap-2">
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="resetFilters">
          Reset Filter
        </button>
        <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700" @click="loadAttendance">
          Refresh Data
        </button>
      </div>
    </PageHeader>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Total Sales</p>
        <p class="mt-3 text-2xl font-semibold text-slate-900">{{ summary.total.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Sudah Check In</p>
        <p class="mt-3 text-2xl font-semibold text-brand-700">{{ summary.checkedIn.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Masih di Lapangan</p>
        <p class="mt-3 text-2xl font-semibold text-amber-600">{{ summary.onField.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Sudah Check Out</p>
        <p class="mt-3 text-2xl font-semibold text-emerald-600">{{ summary.checkedOut.toLocaleString('id-ID') }}</p>
      </article>
    </section>

    <AppFilterBar :model-value="filters" :fields="filterFields" @update:model-value="updateFilters" @submit="loadAttendance" @reset="resetFilters" />

    <section v-if="feedback" class="rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-700">
      {{ feedback }}
    </section>

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ error }}
    </section>

    <div class="space-y-6">
      <section class="panel p-5">
        <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 class="text-lg font-semibold text-slate-900">Rekap Absensi Sales</h3>
            <p class="mt-1 text-sm text-slate-500">Klik salah satu sales untuk melihat detail aktivitas kunjungannya pada tanggal yang sama.</p>
          </div>
        </div>

        <AppTable
          :columns="tableColumns"
          :rows="rows"
          :loading="loading"
          row-key="id_user"
          :selected-key="selectedKey"
          :clickable-rows="true"
          empty-message="Belum ada data absensi sales untuk filter yang dipilih."
          @row-click="openActivityDetail"
        />
      </section>

      <section class="hidden">
        <div v-if="selectedRow" class="space-y-4">
          <div>
            <h3 class="text-lg font-semibold text-slate-900">Detail Aktivitas Sales</h3>
            <p class="mt-1 text-sm text-slate-500">{{ selectedRow.nama_sales }} • {{ selectedRow.attendance_status }}</p>
          </div>

          <div class="grid gap-3 md:grid-cols-2">
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-wide text-slate-400">Check In Pertama</p>
              <p class="mt-2 font-semibold text-slate-900">{{ selectedRow.first_check_in_label }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-wide text-slate-400">Check Out Terakhir</p>
              <p class="mt-2 font-semibold text-slate-900">{{ selectedRow.last_check_out_label }}</p>
            </article>
          </div>

          <AppTable
            :columns="detailColumns"
            :rows="selectedVisitRows"
            :loading="loading"
            :paginated="true"
            :default-page-size="8"
            empty-message="Belum ada aktivitas kunjungan untuk sales ini pada tanggal yang dipilih."
          />
        </div>

        <div v-else class="py-8">
          <AppEmptyState
            title="Belum ada sales terpilih"
            description="Pilih salah satu sales pada tabel kiri untuk melihat detail aktivitas check in dan check out."
          />
        </div>
      </section>
    </div>

    <AppModal
      :open="detailModalOpen"
      :title="detailModalTitle"
      :description="selectedRow ? `${selectedRow.kode_sales || '-'} - ${selectedRow.attendance_status || '-'}` : 'Detail aktivitas check in dan check out sales.'"
      size="5xl"
      @close="closeActivityDetail"
    >
      <div v-if="selectedRow" class="space-y-4">
        <div class="grid gap-3 md:grid-cols-3">
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-950">
            <p class="text-xs uppercase tracking-wide text-slate-400">Status Absensi</p>
            <p class="mt-2 font-semibold text-slate-900 dark:text-white">{{ selectedRow.attendance_status || '-' }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-950">
            <p class="text-xs uppercase tracking-wide text-slate-400">Check In Pertama</p>
            <p class="mt-2 font-semibold text-slate-900 dark:text-white">{{ selectedRow.first_check_in_label || '-' }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-950">
            <p class="text-xs uppercase tracking-wide text-slate-400">Check Out Terakhir</p>
            <p class="mt-2 font-semibold text-slate-900 dark:text-white">{{ selectedRow.last_check_out_label || '-' }}</p>
          </article>
        </div>

        <AppTable
          :columns="detailColumns"
          :rows="selectedVisitRows"
          :loading="loading"
          :paginated="true"
          :default-page-size="8"
          empty-message="Belum ada aktivitas kunjungan untuk sales ini pada tanggal yang dipilih."
        />
      </div>

      <AppEmptyState
        v-else
        title="Belum ada sales terpilih"
        description="Pilih salah satu sales pada tabel untuk melihat detail aktivitas check in dan check out."
      />
    </AppModal>
  </div>
</template>
