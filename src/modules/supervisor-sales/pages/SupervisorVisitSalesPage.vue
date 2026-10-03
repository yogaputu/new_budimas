<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies, getPrincipals, getSales, getSupervisorSalesVisitReport } from '@/api/master';
import { useAuthStore } from '@/app/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { scopeSalesRowsByLogin } from '@/utils/accessScope';
import { toLocalDateInputValue } from '@/utils/date';
import AppEmptyState from '@/shared/components/AppEmptyState.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import VisitPointsMapModal from '@/modules/supervisor-sales/components/VisitPointsMapModal.vue';
import {
  getSupervisorBranchOptions,
  getSupervisorCompanyOptions,
  getSupervisorPrincipalOptions,
  resetSupervisorBranchWhenCompanyChanges,
  syncSupervisorCompanyFromBranch,
} from '@/modules/supervisor-sales/utils/supervisorScope';

const auth = useAuthStore();

const form = reactive({
  companyId: '',
  branchId: '',
  principalId: '',
  salesId: '',
  date: toLocalDateInputValue()
});

const loading = ref(false);
const reportLoading = ref(false);
const error = ref('');
const feedback = ref('');
const companies = ref([]);
const branches = ref([]);
const principals = ref([]);
const salesRows = ref([]);
const selectedFile = ref(null);
const reportRows = ref([]);
const chartRows = ref([]);
const hasLoadedReport = ref(false);
const reportMeta = ref({});
const mapModalOpen = ref(false);
const selectedMapKey = ref('');
const metricsMap = ref({
  callplan: 0,
  visited: 0,
  pending: 0,
  noorder: 0,
  actual_visits: 0,
  unplanned_visits: 0
});

const companyOptions = computed(() =>
  getSupervisorCompanyOptions(companies.value, branches.value, '', auth)
);

const branchOptions = computed(() => getSupervisorBranchOptions(branches.value, auth, false, form.companyId, companies.value));

const principalOptions = computed(() => {
  const companyId = String(form.companyId || '');
  return getSupervisorPrincipalOptions(principals.value, companyId, false);
});

const activeUser = computed(() => auth.user || {});
const activeBranchId = computed(() =>
  String(activeUser.value?.cabang?.id || activeUser.value?.cabang_id || activeUser.value?.id_cabang || '')
);
const activeCompanyId = computed(() =>
  String(
    activeUser.value?.perusahaan?.id ||
    activeUser.value?.id_perusahaan ||
    branches.value.find((item) => String(item.id) === activeBranchId.value)?.id_perusahaan ||
    ''
  )
);

function matchesFilter(item, expected, keys = []) {
  const normalizedExpected = String(expected || '').trim();
  if (!normalizedExpected) return true;

  return keys.some((key) => {
    const rawValue = item?.[key];

    if (Array.isArray(rawValue)) {
      return rawValue.map((value) => String(value)).includes(normalizedExpected);
    }

    if (rawValue === undefined || rawValue === null || rawValue === '') {
      return false;
    }

    return String(rawValue) === normalizedExpected;
  });
}

const salesOptions = computed(() => {
  const branchId = String(form.branchId || '');
  const principalId = String(form.principalId || '');

  let source = scopeSalesRowsByLogin(salesRows.value, auth).filter((item) =>
    matchesFilter(item, branchId, ['id_cabang', 'cabang_id', 'idCabang'])
  );

  source = source.filter((item) =>
    matchesFilter(item, principalId, ['id_principal', 'principal_id', 'id_principals'])
  );

  return source.map((item) => ({
    value: String(item.id_sales || item.sales_id || item.id),
    label: `${item.nama || 'Sales'}${item.kode_sales ? ` - ${item.kode_sales}` : ''}`
  }));
});

const derivedDayLabel = computed(() => {
  if (!form.date) return '-';
  const days = ['Minggu', 'Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu'];
  return days[new Date(form.date).getDay()] || '-';
});

const derivedWeekLabel = computed(() => {
  if (!form.date) return '-';
  const day = new Date(form.date).getDate();
  const week = Math.min(Math.ceil(day / 7), 4);
  return `Week ${week}`;
});

const metricCards = computed(() => [
  {
    key: 'callplan',
    label: 'Callplan',
    value: metricsMap.value.callplan || 0,
    note: 'Customer yang memang masuk jadwal kunjungan pada tanggal terpilih.'
  },
  {
    key: 'visited',
    label: 'Sudah Kunjungan',
    value: metricsMap.value.visited || 0,
    note: 'Sales sudah melakukan check in atau menyelesaikan kunjungan.'
  },
  {
    key: 'pending',
    label: 'Belum Kunjungan',
    value: metricsMap.value.pending || 0,
    note: 'Masih terjadwal tetapi belum ada aktivitas kunjungan di hari itu.'
  },
  {
    key: 'noorder',
    label: 'No Order',
    value: metricsMap.value.noorder || 0,
    note: 'Kunjungan yang belum menghasilkan sales order pada tanggal yang sama.'
  }
]);

const supportMetrics = computed(() => [
  {
    key: 'actual_visits',
    label: 'Kunjungan Aktual',
    value: metricsMap.value.actual_visits || 0,
    tone: 'text-emerald-700 bg-emerald-50 border-emerald-200'
  },
  {
    key: 'unplanned_visits',
    label: 'Di Luar Callplan',
    value: metricsMap.value.unplanned_visits || 0,
    tone: 'text-amber-700 bg-amber-50 border-amber-200'
  }
]);

const emptyStateTitle = computed(() => {
  if (metricsMap.value.unplanned_visits > 0) return 'Callplan kosong, tetapi ada kunjungan aktual';
  return 'Belum ada data kunjungan';
});

const emptyStateDescription = computed(() => (
  reportMeta.value?.notes || 'Coba ubah tanggal atau filter sales untuk melihat callplan yang aktif.'
));

const maxChartValue = computed(() =>
  Math.max(
    ...chartRows.value.map((item) => Math.max(item.callplan || 0, item.visited || 0, item.pending || 0)),
    1
  )
);

const salesVisitRows = computed(() =>
  chartRows.value.map((item) => ({
    ...item,
    callplanWidth: `${Math.max(((item.callplan || 0) / maxChartValue.value) * 100, 8)}%`,
    visitedWidth: `${Math.max(((item.visited || 0) / maxChartValue.value) * 100, 8)}%`,
    pendingWidth: `${Math.max(((item.pending || 0) / maxChartValue.value) * 100, 8)}%`
  }))
);

const rowsWithCoordinates = computed(() =>
  reportRows.value
    .filter((row) => row?.latitude && row?.longitude)
    .map((row, index) => ({
      ...row,
      markerKey: String(row.id_kunjungan || row.id_plafon || row.kode_customer || index)
    }))
);

const visitColumns = [
  { key: 'nama_sales', label: 'Sales' },
  {
    key: 'customer',
    label: 'Customer',
    render: (row) => `${row.nama_customer || '-'}${row.kode_customer ? ` (${row.kode_customer})` : ''}`
  },
  { key: 'nama_principal', label: 'Principal' },
  { key: 'nama_cabang', label: 'Cabang' },
  { key: 'tipe_kunjungan_label', label: 'Tipe Kunjungan' },
  { key: 'data_source_label', label: 'Sumber' },
  { key: 'status_kunjungan_label', label: 'Status' },
  {
    key: 'jam',
    label: 'Jam',
    render: (row) => `${row.waktu_mulai || '-'} / ${row.waktu_selesai || '-'}`
  },
  { key: 'status_order_label', label: 'Order' }
];

function buildReportParams() {
  return {
    tanggal: form.date,
    id_perusahaan: form.companyId || undefined,
    id_cabang: form.branchId || undefined,
    id_principal: form.principalId || undefined,
    id_sales: form.salesId || undefined
  };
}

async function loadReferences() {
  loading.value = true;
  error.value = '';

  try {
    const [companyResponse, branchResponse, principalResponse, salesResponse] = await Promise.all([
      getCompanies(),
      getBranches(),
      getPrincipals(),
      getSales()
    ]);

    companies.value = normalizeList(unwrapResponse(companyResponse));
    branches.value = normalizeList(unwrapResponse(branchResponse));
    principals.value = normalizeList(unwrapResponse(principalResponse));
    salesRows.value = normalizeList(unwrapResponse(salesResponse));

    if (!form.branchId && activeBranchId.value) {
      form.branchId = activeBranchId.value;
    }

    syncSupervisorCompanyFromBranch(form, 'branchId', 'companyId', branches.value, companies.value);
  } catch (err) {
    error.value = normalizeError(err, 'Referensi supervisor sales belum bisa dimuat.');
  } finally {
    loading.value = false;
  }
}

async function loadReport() {
  reportLoading.value = true;
  error.value = '';

  try {
    const response = await getSupervisorSalesVisitReport(buildReportParams());
    const payload = unwrapResponse(response) || {};

    metricsMap.value = {
      callplan: Number(payload?.summary?.callplan || 0),
      visited: Number(payload?.summary?.visited || 0),
      pending: Number(payload?.summary?.pending || 0),
      noorder: Number(payload?.summary?.noorder || 0),
      actual_visits: Number(payload?.summary?.actual_visits || 0),
      unplanned_visits: Number(payload?.summary?.unplanned_visits || 0)
    };
    chartRows.value = normalizeList(payload?.chart);
    reportRows.value = normalizeList(payload?.rows).map((row, index) => ({
      ...row,
      markerKey: String(row.id_kunjungan || row.id_plafon || row.kode_customer || index)
    }));
    reportMeta.value = payload?.meta || {};
    if (!reportRows.value.some((row) => String(row.markerKey) === String(selectedMapKey.value))) {
      selectedMapKey.value = reportRows.value[0]?.markerKey || '';
    }
    hasLoadedReport.value = true;
    feedback.value = `Laporan kunjungan untuk ${derivedDayLabel.value}, ${derivedWeekLabel.value} berhasil dimuat.`;
  } catch (err) {
    error.value = normalizeError(err, 'Laporan kunjungan sales belum bisa dimuat.');
    reportRows.value = [];
    chartRows.value = [];
    reportMeta.value = {};
    selectedMapKey.value = '';
    metricsMap.value = {
      callplan: 0,
      visited: 0,
      pending: 0,
      noorder: 0,
      actual_visits: 0,
      unplanned_visits: 0
    };
  } finally {
    reportLoading.value = false;
  }
}

function applyFilter() {
  loadReport();
}

function openMaps() {
  if (!rowsWithCoordinates.value.length) {
    feedback.value = 'Belum ada koordinat customer yang bisa dibuka ke peta untuk filter ini.';
    return;
  }

  if (!selectedMapKey.value) {
    selectedMapKey.value = rowsWithCoordinates.value[0]?.markerKey || '';
  }
  mapModalOpen.value = true;
  feedback.value = `Peta supervisor dibuka dengan ${rowsWithCoordinates.value.length} titik customer.`;
}

function selectVisitRow(row) {
  if (!row?.latitude || !row?.longitude) {
    feedback.value = 'Baris ini belum punya koordinat customer, jadi belum bisa difokuskan ke peta.';
    return;
  }

  selectedMapKey.value = String(row.id_kunjungan || row.id_plafon || row.kode_customer || '');
  mapModalOpen.value = true;
  feedback.value = `Fokus peta diarahkan ke ${row.nama_customer || row.kode_customer || 'customer terpilih'}.`;
}

function handleMapPointSelect(point) {
  selectedMapKey.value = String(point?.markerKey || point?.id_kunjungan || point?.id_plafon || point?.kode_customer || '');
}

function downloadSkuHistory() {
  if (!reportRows.value.length) {
    feedback.value = 'Belum ada data kunjungan untuk diexport.';
    return;
  }

  const headers = [
    'Sales',
    'Kode Customer',
    'Nama Customer',
    'Cabang',
    'Principal',
    'Tipe Kunjungan',
    'Sumber',
    'Status Kunjungan',
    'Jam Mulai',
    'Jam Selesai',
    'Status Order',
    'Latitude',
    'Longitude'
  ];

  const csvRows = reportRows.value.map((row) => ([
    row.nama_sales || '',
    row.kode_customer || '',
    row.nama_customer || '',
    row.nama_cabang || '',
    row.nama_principal || '',
    row.tipe_kunjungan_label || '',
    row.data_source_label || '',
    row.status_kunjungan_label || '',
    row.waktu_mulai || '',
    row.waktu_selesai || '',
    row.status_order_label || '',
    row.latitude || '',
    row.longitude || ''
  ]));

  const csvContent = [headers, ...csvRows]
    .map((line) => line.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(','))
    .join('\n');

  const blob = new Blob([`\uFEFF${csvContent}`], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `laporan-kunjungan-sales-${form.date || 'export'}.csv`;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);

  feedback.value = `Export CSV berhasil dibuat untuk ${reportRows.value.length} baris kunjungan.`;
}

function onFileChange(event) {
  selectedFile.value = event.target.files?.[0] || null;
}

function processFile() {
  feedback.value = selectedFile.value
    ? `File ${selectedFile.value.name} sudah terbaca. Proses upload supervisor masih saya tahan sampai format file final dipastikan.`
    : 'Pilih file dulu sebelum diproses.';
}

watch(
  () => form.companyId,
  (companyId) => {
    const normalizedCompanyId = String(companyId || '');

    if (resetSupervisorBranchWhenCompanyChanges(form, 'companyId', 'branchId', branches.value, auth, companies.value)) {
      form.salesId = '';
    }

    if (!normalizedCompanyId) {
      form.principalId = '';
    } else if (!principalOptions.value.some((item) => item.value === String(form.principalId))) {
      form.principalId = '';
    }
  }
);

watch(
  () => form.branchId,
  (branchId) => {
    if (!branchId) {
      form.salesId = '';
      return;
    }
  }
);

watch(
  () => [form.branchId, form.principalId],
  () => {
    if (!salesOptions.value.some((item) => item.value === String(form.salesId))) {
      form.salesId = '';
    }
  }
);

onMounted(async () => {
  await loadReferences();
  await loadReport();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Laporan Kunjungan Sales"
      description="Halaman ini sekarang dipakai sebagai monitor supervisor untuk melihat callplan, progres kunjungan, dan indikasi no order per sales di tanggal terpilih."
    />

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ error }}
    </section>

    <section class="panel p-6">
      <div class="grid gap-4 md:grid-cols-2">
        <AppSearchSelect v-model="form.companyId" label="Perusahaan" placeholder="Pilih perusahaan" :options="companyOptions" />
        <AppSearchSelect v-model="form.branchId" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="!form.companyId" empty-text="Pilih perusahaan terlebih dahulu." />
        <AppFormField v-model="form.date" label="Tanggal" type="date" />
        <AppSearchSelect v-model="form.principalId" label="Principal" placeholder="Pilih principal" :options="principalOptions" :disabled="!form.companyId" empty-text="Pilih perusahaan terlebih dahulu." />
        <AppSearchSelect v-model="form.salesId" label="Sales" placeholder="Pilih sales" :options="salesOptions" empty-text="Sales belum tersedia untuk filter ini." />
        <AppFormField :model-value="derivedDayLabel" label="Hari" readonly />
        <AppFormField :model-value="derivedWeekLabel" label="Week" readonly />
      </div>

      <div class="mt-5 flex flex-wrap items-center gap-3">
        <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700" @click="applyFilter">
          Filter
        </button>
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50" @click="openMaps">
          View Maps
        </button>
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50" @click="downloadSkuHistory">
          Download Histori SKU
        </button>
      </div>

      <div class="mt-5 flex flex-wrap items-center gap-3">
        <input type="file" class="block text-sm text-slate-600 file:mr-3 file:rounded-lg file:border-0 file:bg-slate-100 file:px-3 file:py-2 file:text-sm file:font-medium" @change="onFileChange" />
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50" @click="processFile">
          Proses File
        </button>
      </div>

      <div v-if="feedback" class="mt-5 rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-700">
        {{ feedback }}
      </div>

      <div
        v-if="hasLoadedReport && reportMeta.notes"
        class="mt-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600"
      >
        {{ reportMeta.notes }}
      </div>
    </section>

    <section class="grid gap-4 md:grid-cols-4">
      <article v-for="item in metricCards" :key="item.key" class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">{{ item.label }}</p>
        <p class="mt-3 text-3xl font-bold text-slate-950">{{ item.value }}</p>
        <p class="mt-2 text-xs text-slate-400">{{ item.note }}</p>
      </article>
    </section>

    <section class="flex flex-wrap gap-3">
      <article
        v-for="item in supportMetrics"
        :key="item.key"
        :class="['rounded-2xl border px-4 py-3 text-sm', item.tone]"
      >
        <p class="font-semibold">{{ item.label }}</p>
        <p class="mt-1 text-2xl font-bold">{{ item.value }}</p>
      </article>
    </section>

    <section class="panel p-6">
      <div class="flex items-start justify-between gap-4">
        <div>
          <h3 class="text-xl font-bold text-brand-700">Chart Monitor Kunjungan Sales</h3>
          <p class="mt-1 text-sm text-slate-500">Ringkasan per sales saya tampilkan sebagai batang progres sederhana agar supervisor cepat melihat beban callplan dan progress lapangan.</p>
        </div>
        <div class="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
          {{ reportLoading ? 'Memuat...' : `${chartRows.length} Sales` }}
        </div>
      </div>

      <AppEmptyState
        v-if="hasLoadedReport && !reportLoading && !salesVisitRows.length"
        :title="emptyStateTitle"
        :description="emptyStateDescription"
      />

      <div v-else class="mt-8 space-y-6">
        <div v-for="item in salesVisitRows" :key="item.sales" class="space-y-3 rounded-2xl border border-slate-100 p-4">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p class="text-sm font-semibold text-slate-900">{{ item.sales }}</p>
              <p class="text-xs text-slate-500">
                Callplan {{ item.callplan }} | Sudah Kunjungan {{ item.visited }} | Belum Kunjungan {{ item.pending }} | No Order {{ item.noorder }}
              </p>
            </div>
          </div>

          <div class="space-y-2">
            <div class="flex items-center justify-between text-xs text-slate-500">
              <span>Callplan</span>
              <span>{{ item.callplan }}</span>
            </div>
            <div class="h-3 rounded-full bg-slate-100">
              <div class="h-3 rounded-full bg-sky-500" :style="{ width: item.callplanWidth }"></div>
            </div>
          </div>

          <div class="space-y-2">
            <div class="flex items-center justify-between text-xs text-slate-500">
              <span>Sudah Kunjungan</span>
              <span>{{ item.visited }}</span>
            </div>
            <div class="h-3 rounded-full bg-slate-100">
              <div class="h-3 rounded-full bg-emerald-500" :style="{ width: item.visitedWidth }"></div>
            </div>
          </div>

          <div class="space-y-2">
            <div class="flex items-center justify-between text-xs text-slate-500">
              <span>Belum Kunjungan</span>
              <span>{{ item.pending }}</span>
            </div>
            <div class="h-3 rounded-full bg-slate-100">
              <div class="h-3 rounded-full bg-amber-500" :style="{ width: item.pendingWidth }"></div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="panel p-6">
      <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 class="text-xl font-bold text-slate-950">Daftar Kunjungan</h3>
          <p class="mt-1 text-sm text-slate-500">Baris di bawah ini memudahkan supervisor menelusuri customer mana yang sudah dikunjungi, belum dikunjungi, dan belum menghasilkan order.</p>
        </div>
        <div class="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
          {{ reportRows.length }} Baris
        </div>
      </div>

      <AppTable
        :rows="reportRows"
        :columns="visitColumns"
        :loading="reportLoading"
        :clickable-rows="true"
        :paginated="true"
        :default-page-size="15"
        :selected-key="selectedMapKey"
        row-key="markerKey"
        empty-message="Belum ada data kunjungan untuk filter yang dipilih."
        @row-click="selectVisitRow"
      />
    </section>

    <VisitPointsMapModal
      :open="mapModalOpen"
      :points="rowsWithCoordinates"
      :selected-key="selectedMapKey"
      @select="handleMapPointSelect"
      @close="mapModalOpen = false"
    />
  </div>
</template>
