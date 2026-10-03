<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies, getPrincipals, getSales, getSupervisorSalesCallplanCalendar } from '@/api/master';
import { useAuthStore } from '@/app/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { scopeSalesRowsByLogin } from '@/utils/accessScope';
import AppEmptyState from '@/shared/components/AppEmptyState.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import {
  getSupervisorBranchOptions,
  getSupervisorCompanyOptions,
  getSupervisorPrincipalOptions,
  resetSupervisorBranchWhenCompanyChanges,
  syncSupervisorCompanyFromBranch,
} from '@/modules/supervisor-sales/utils/supervisorScope';

const auth = useAuthStore();
const now = new Date();

const filters = reactive({
  year: now.getFullYear(),
  month: now.getMonth() + 1,
  companyId: '',
  branchId: '',
  principalId: '',
  salesId: '',
});

const loading = ref(false);
const error = ref('');
const feedback = ref('');
const companies = ref([]);
const branches = ref([]);
const principals = ref([]);
const salesRows = ref([]);
const calendarRows = ref([]);
const summary = ref({
  total_callplan: 0,
  active_days: 0,
  average_per_day: 0,
  max_callplan: 0,
});
const selectedDate = ref('');
const detailModalOpen = ref(false);

const dayLabels = ['Min', 'Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab'];

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

const companyOptions = computed(() =>
  getSupervisorCompanyOptions(companies.value, branches.value, '', auth, true)
);

const branchOptions = computed(() => getSupervisorBranchOptions(branches.value, auth, true, filters.companyId, companies.value));

const principalOptions = computed(() => {
  const companyId = String(filters.companyId || '');
  return getSupervisorPrincipalOptions(principals.value, companyId, true);
});

function toLocalIsoDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

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
  const branchId = String(filters.branchId || '');
  const principalId = String(filters.principalId || '');

  let source = scopeSalesRowsByLogin(salesRows.value, auth).filter((item) =>
    matchesFilter(item, branchId, ['id_cabang', 'cabang_id', 'idCabang'])
  );

  source = source.filter((item) =>
    matchesFilter(item, principalId, ['id_principal', 'principal_id', 'id_principals'])
  );

  return [
    { value: '', label: 'Semua sales' },
    ...source.map((item) => ({
      value: String(item.id_sales || item.sales_id || item.id),
      label: `${item.nama || 'Sales'}${item.kode_sales ? ` - ${item.kode_sales}` : ''}`,
    })),
  ];
});

const monthTitle = computed(() =>
  new Intl.DateTimeFormat('id-ID', {
    month: 'long',
    year: 'numeric',
  }).format(new Date(Number(filters.year), Number(filters.month) - 1, 1))
);

const rowMap = computed(() => {
  const map = new Map();
  calendarRows.value.forEach((row) => {
    map.set(row.date, row);
  });
  return map;
});

const calendarCells = computed(() => {
  const year = Number(filters.year);
  const monthIndex = Number(filters.month) - 1;
  const firstDate = new Date(year, monthIndex, 1);
  const lastDate = new Date(year, monthIndex + 1, 0);
  const startDay = firstDate.getDay();
  const daysInMonth = lastDate.getDate();
  const totalCells = Math.ceil((startDay + daysInMonth) / 7) * 7;
  const cells = [];

  for (let index = 0; index < totalCells; index += 1) {
    const date = new Date(year, monthIndex, index - startDay + 1);
    const isoDate = toLocalIsoDate(date);
    const row = rowMap.value.get(isoDate);

    cells.push({
      key: `${isoDate}-${index}`,
      date: isoDate,
      day: date.getDate(),
      isCurrentMonth: date.getMonth() === monthIndex,
      isToday: isoDate === toLocalIsoDate(new Date()),
      ...row,
    });
  }

  return cells;
});

const selectedDay = computed(() => {
  if (!selectedDate.value) return null;
  return rowMap.value.get(selectedDate.value) || calendarCells.value.find((cell) => cell.date === selectedDate.value) || null;
});

const selectedDaySales = computed(() => normalizeList(selectedDay.value?.details || []));

const selectedDayTitle = computed(() => {
  if (!selectedDay.value?.date) return 'Detail Callplan';
  return new Intl.DateTimeFormat('id-ID', { dateStyle: 'full' }).format(new Date(selectedDay.value.date));
});

function dayIntensityClass(count) {
  const value = Number(count || 0);
  if (value >= 50) return 'bg-brand-700 text-white';
  if (value >= 30) return 'bg-brand-600 text-white';
  if (value > 0) return 'bg-brand-500 text-white';
  return 'bg-slate-100 text-slate-500';
}

async function loadReferences() {
  const [companyResponse, branchResponse, principalResponse, salesResponse] = await Promise.all([
    getCompanies(),
    getBranches(),
    getPrincipals(),
    getSales(),
  ]);

  companies.value = normalizeList(unwrapResponse(companyResponse));
  branches.value = normalizeList(unwrapResponse(branchResponse));
  principals.value = normalizeList(unwrapResponse(principalResponse));
  salesRows.value = normalizeList(unwrapResponse(salesResponse));

  if (!filters.branchId && activeBranchId.value) {
    filters.branchId = activeBranchId.value;
  }

  syncSupervisorCompanyFromBranch(filters, 'branchId', 'companyId', branches.value, companies.value);
}

function buildParams() {
  return {
    year: Number(filters.year),
    month: Number(filters.month),
    id_perusahaan: filters.companyId || undefined,
    id_cabang: filters.branchId || undefined,
    id_principal: filters.principalId || undefined,
    id_sales: filters.salesId || undefined,
  };
}

function pickDefaultSelectedDate() {
  const currentMonthCells = calendarCells.value.filter((cell) => cell.isCurrentMonth);
  const todayIso = toLocalIsoDate(new Date());
  const todayCell = currentMonthCells.find((cell) => cell.date === todayIso);
  const withCallplan = currentMonthCells.find((cell) => Number(cell.callplan_count || 0) > 0);
  selectedDate.value = todayCell?.date || withCallplan?.date || currentMonthCells[0]?.date || '';
}

async function loadCalendar() {
  loading.value = true;
  error.value = '';

  try {
    const response = await getSupervisorSalesCallplanCalendar(buildParams());
    const payload = unwrapResponse(response) || {};

    calendarRows.value = normalizeList(payload.rows);
    summary.value = {
      total_callplan: Number(payload.summary?.total_callplan || 0),
      active_days: Number(payload.summary?.active_days || 0),
      average_per_day: Number(payload.summary?.average_per_day || 0),
      max_callplan: Number(payload.summary?.max_callplan || 0),
    };

    if (!selectedDate.value || !rowMap.value.has(selectedDate.value)) {
      pickDefaultSelectedDate();
    }

    feedback.value = `Kalender callplan ${monthTitle.value} memuat ${summary.value.total_callplan} callplan pada ${summary.value.active_days} hari aktif.`;
  } catch (err) {
    error.value = normalizeError(err, 'Kalender callplan sales belum bisa dimuat.');
    calendarRows.value = [];
    summary.value = {
      total_callplan: 0,
      active_days: 0,
      average_per_day: 0,
      max_callplan: 0,
    };
    selectedDate.value = '';
  } finally {
    loading.value = false;
  }
}

function previousMonth() {
  if (Number(filters.month) === 1) {
    filters.month = 12;
    filters.year = Number(filters.year) - 1;
  } else {
    filters.month = Number(filters.month) - 1;
  }
  loadCalendar();
}

function nextMonth() {
  if (Number(filters.month) === 12) {
    filters.month = 1;
    filters.year = Number(filters.year) + 1;
  } else {
    filters.month = Number(filters.month) + 1;
  }
  loadCalendar();
}

function resetFilters() {
  filters.year = now.getFullYear();
  filters.month = now.getMonth() + 1;
  filters.branchId = activeBranchId.value || '';
  filters.companyId = '';
  syncSupervisorCompanyFromBranch(filters, 'branchId', 'companyId', branches.value, companies.value);
  filters.principalId = '';
  filters.salesId = '';
  loadCalendar();
}

function selectDay(cell) {
  if (!cell?.date) return;
  selectedDate.value = cell.date;
  detailModalOpen.value = true;
}

watch(
  () => filters.companyId,
  (companyId) => {
    const normalizedCompanyId = String(companyId || '');

    if (resetSupervisorBranchWhenCompanyChanges(filters, 'companyId', 'branchId', branches.value, auth, companies.value)) {
      filters.salesId = '';
    }

    if (!normalizedCompanyId) {
      filters.principalId = '';
    } else if (!principalOptions.value.some((item) => item.value === String(filters.principalId))) {
      filters.principalId = '';
    }
  }
);

watch(
  () => filters.branchId,
  (branchId) => {
    if (!branchId) {
      filters.salesId = '';
      return;
    }
  }
);

watch(
  () => [filters.branchId, filters.principalId],
  () => {
    if (!salesOptions.value.some((item) => item.value === String(filters.salesId))) {
      filters.salesId = '';
    }
  }
);

onMounted(async () => {
  try {
    await loadReferences();
  } catch (err) {
    error.value = normalizeError(err, 'Referensi kalender callplan belum bisa dimuat.');
  }

  await loadCalendar();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Kalender Call Plan Sales"
      description="Supervisor bisa melihat sebaran callplan sales per hari dalam bentuk kalender bulanan agar lebih mudah membaca beban tim dan ritme kunjungan."
    >
      <div class="flex flex-wrap gap-3">
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50" @click="resetFilters">
          Reset
        </button>
        <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700" @click="loadCalendar">
          Refresh Kalender
        </button>
      </div>
    </PageHeader>

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ error }}
    </section>

    <section class="panel p-6">
      <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
        <AppFormField v-model="filters.year" label="Tahun" type="number" />
        <AppSearchSelect
          v-model="filters.month"
          label="Bulan"
          placeholder="Pilih bulan"
          :options="[
            { value: 1, label: 'Januari' },
            { value: 2, label: 'Februari' },
            { value: 3, label: 'Maret' },
            { value: 4, label: 'April' },
            { value: 5, label: 'Mei' },
            { value: 6, label: 'Juni' },
            { value: 7, label: 'Juli' },
            { value: 8, label: 'Agustus' },
            { value: 9, label: 'September' },
            { value: 10, label: 'Oktober' },
            { value: 11, label: 'November' },
            { value: 12, label: 'Desember' }
          ]"
        />
        <AppSearchSelect v-model="filters.companyId" label="Perusahaan" placeholder="Semua perusahaan" :options="companyOptions" />
        <AppSearchSelect v-model="filters.branchId" label="Cabang" placeholder="Semua cabang" :options="branchOptions" :disabled="!filters.companyId" empty-text="Pilih perusahaan terlebih dahulu." />
        <AppSearchSelect v-model="filters.principalId" label="Principal" placeholder="Semua principal" :options="principalOptions" :disabled="!filters.companyId" empty-text="Pilih perusahaan terlebih dahulu." />
        <AppSearchSelect v-model="filters.salesId" label="Sales" placeholder="Semua sales" :options="salesOptions" empty-text="Sales belum tersedia untuk filter ini." />
      </div>

      <div class="mt-5 flex flex-wrap gap-3">
        <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700" @click="loadCalendar">
          Tampilkan Kalender
        </button>
      </div>

      <div v-if="feedback" class="mt-4 rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-700">
        {{ feedback }}
      </div>
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Total Callplan</p>
        <p class="mt-3 text-3xl font-bold text-slate-950">{{ summary.total_callplan.toLocaleString('id-ID') }}</p>
        <p class="mt-2 text-sm text-slate-500">Akumulasi seluruh callplan pada bulan terpilih.</p>
      </article>
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Hari Aktif</p>
        <p class="mt-3 text-3xl font-bold text-brand-700">{{ summary.active_days.toLocaleString('id-ID') }}</p>
        <p class="mt-2 text-sm text-slate-500">Jumlah hari yang punya callplan aktif pada filter ini.</p>
      </article>
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Rata-rata CP / Hari</p>
        <p class="mt-3 text-3xl font-bold text-emerald-600">{{ summary.average_per_day.toLocaleString('id-ID') }}</p>
        <p class="mt-2 text-sm text-slate-500">Ritme rata-rata beban callplan di hari yang aktif.</p>
      </article>
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Puncak Harian</p>
        <p class="mt-3 text-3xl font-bold text-amber-600">{{ summary.max_callplan.toLocaleString('id-ID') }}</p>
        <p class="mt-2 text-sm text-slate-500">Callplan tertinggi yang muncul pada satu hari di bulan ini.</p>
      </article>
    </section>

    <section class="panel overflow-hidden">
      <div class="flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 px-4 py-4 sm:px-6">
        <div class="flex items-center gap-3">
          <button class="rounded-xl bg-slate-700 px-4 py-3 text-white hover:bg-slate-800" @click="previousMonth">
            &lsaquo;
          </button>
          <button class="rounded-xl bg-slate-700 px-4 py-3 text-white hover:bg-slate-800" @click="nextMonth">
            &rsaquo;
          </button>
        </div>
        <h2 class="text-3xl font-light tracking-tight text-slate-500">{{ monthTitle }}</h2>
        <div class="text-sm text-slate-500">
          Klik tanggal untuk melihat detail callplan harian.
        </div>
      </div>

      <div class="grid grid-cols-7 border-b border-slate-100 bg-slate-50">
        <div
          v-for="label in dayLabels"
          :key="label"
          class="border-r border-slate-100 px-3 py-3 text-center text-xl font-bold text-brand-600 last:border-r-0"
        >
          {{ label }}
        </div>
      </div>

      <div class="grid grid-cols-7">
        <button
          v-for="cell in calendarCells"
          :key="cell.key"
          type="button"
          :class="[
            'min-h-[150px] border-r border-b border-slate-100 p-2 text-left align-top transition hover:bg-slate-50',
            !cell.isCurrentMonth ? 'bg-slate-50/60 text-slate-300' : 'bg-white',
            cell.date === selectedDate ? 'ring-2 ring-inset ring-brand-300 bg-brand-50/40' : '',
            cell.isToday ? 'bg-amber-50/60' : ''
          ]"
          @click="selectDay(cell)"
        >
          <div class="flex items-start justify-between gap-2">
            <div class="flex flex-col items-end ml-auto">
              <span :class="['text-4xl font-bold leading-none', cell.isCurrentMonth ? 'text-brand-600' : 'text-slate-300']">
                {{ cell.day }}
              </span>
              <span :class="['mt-1 text-sm font-semibold', cell.isCurrentMonth ? 'text-brand-500' : 'text-slate-300']">
                {{ cell.week_label || '' }}
              </span>
            </div>
          </div>

          <div class="mt-5 space-y-2">
            <div :class="['inline-flex min-w-[96px] rounded-md px-3 py-2 text-sm font-semibold', dayIntensityClass(cell.callplan_count)]">
              CP: {{ Number(cell.callplan_count || 0).toLocaleString('id-ID') }}
            </div>

            <div v-if="cell.isCurrentMonth" class="space-y-1 text-xs text-slate-500">
              <p>Sales: {{ Number(cell.sales_count || 0).toLocaleString('id-ID') }}</p>
              <p>Customer: {{ Number(cell.customer_count || 0).toLocaleString('id-ID') }}</p>
            </div>
          </div>
        </button>
      </div>
    </section>

    <AppModal
      :open="detailModalOpen"
      :title="selectedDayTitle"
      description="Distribusi callplan sales pada tanggal yang dipilih."
      size="4xl"
      @close="detailModalOpen = false"
    >
      <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p class="text-sm font-semibold text-slate-500 dark:text-slate-400">Total Callplan</p>
          <p class="mt-1 text-3xl font-bold text-brand-700 dark:text-brand-300">
            {{ Number(selectedDay?.callplan_count || 0).toLocaleString('id-ID') }} CP
          </p>
        </div>
        <div class="grid grid-cols-2 gap-3 text-sm">
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-950">
            <p class="font-semibold text-slate-500 dark:text-slate-400">Sales</p>
            <p class="mt-1 text-xl font-bold text-slate-950 dark:text-white">{{ Number(selectedDay?.sales_count || 0).toLocaleString('id-ID') }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-950">
            <p class="font-semibold text-slate-500 dark:text-slate-400">Customer</p>
            <p class="mt-1 text-xl font-bold text-slate-950 dark:text-white">{{ Number(selectedDay?.customer_count || 0).toLocaleString('id-ID') }}</p>
          </div>
        </div>
      </div>

      <AppEmptyState
        v-if="!selectedDay || !selectedDaySales.length"
        title="Belum ada callplan"
        description="Tanggal yang dipilih belum memiliki callplan aktif untuk filter yang sedang digunakan."
      />

      <div v-else class="grid gap-4 lg:grid-cols-2">
        <article
          v-for="item in selectedDaySales"
          :key="`${item.id_user_sales || item.id_sales || item.nama_sales}-${item.callplan_count}`"
          class="rounded-3xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-950"
        >
          <div class="flex items-start justify-between gap-3">
            <div>
              <h4 class="text-base font-bold text-slate-950 dark:text-white">{{ item.nama_sales || '-' }}</h4>
              <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">{{ Number(item.callplan_count || 0).toLocaleString('id-ID') }} callplan</p>
            </div>
            <span class="rounded-full bg-brand-600 px-3 py-1 text-sm font-semibold text-white">
              {{ Number(item.callplan_count || 0).toLocaleString('id-ID') }}
            </span>
          </div>

          <div class="mt-4 space-y-2 text-sm text-slate-600 dark:text-slate-300">
            <p class="font-semibold text-slate-700 dark:text-slate-200">Customer terjadwal:</p>
            <div class="flex flex-wrap gap-2">
              <span
                v-for="customer in item.customers"
                :key="`${customer.id_customer}-${customer.kode_customer}`"
                class="rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-700 dark:bg-slate-900 dark:text-slate-200"
              >
                {{ customer.nama_customer || customer.kode_customer || 'Customer' }}
              </span>
            </div>
          </div>
        </article>
      </div>
    </AppModal>
  </div>
</template>
