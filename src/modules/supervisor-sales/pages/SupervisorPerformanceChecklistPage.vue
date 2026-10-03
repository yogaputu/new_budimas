<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import {
  getBranches,
  getCompanies,
  getPrincipals,
  getSales,
  getSupervisorSalesPerformanceChecklist,
  saveSupervisorSalesPerformanceChecklistItem,
  saveSupervisorSalesPerformanceChecklistNote
} from '@/api/master';
import { useAuthStore } from '@/app/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { scopeSalesRowsByLogin } from '@/utils/accessScope';
import { toLocalDateInputValue } from '@/utils/date';
import { exportRowsToCsv } from '@/utils/exportCsv';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppModal from '@/shared/components/AppModal.vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import {
  getSupervisorBranchOptions,
  getSupervisorCompanyOptions,
  getSupervisorPrincipalOptions,
  resetSupervisorBranchWhenCompanyChanges,
  syncSupervisorCompanyFromBranch
} from '@/modules/supervisor-sales/utils/supervisorScope';

const auth = useAuthStore();

const filters = reactive({
  id_perusahaan: '',
  id_cabang: '',
  id_principal: '',
  id_sales: '',
  checklist_status: '',
  tanggal: toLocalDateInputValue()
});

const loading = ref(false);
const referenceLoading = ref(false);
const savingNoteId = ref('');
const savingManualId = ref('');
const activeTab = ref('daily');
const pageError = ref('');
const feedback = ref('');
const manualModalOpen = ref(false);
const selectedManualRow = ref(null);
const companies = ref([]);
const branches = ref([]);
const principals = ref([]);
const salesRows = ref([]);
const rows = ref([]);
const weeklyRows = ref([]);
const dailyAnalysis = ref([]);
const summary = ref({});
const weeklySummary = ref({});
const meta = ref({});
const notesDraft = reactive({});
const manualDrafts = reactive({});

const companyOptions = computed(() =>
  getSupervisorCompanyOptions(companies.value, branches.value, '', auth, true)
);
const branchOptions = computed(() =>
  getSupervisorBranchOptions(branches.value, auth, true, filters.id_perusahaan, companies.value)
);
const principalOptions = computed(() =>
  getSupervisorPrincipalOptions(principals.value, filters.id_perusahaan, true)
);

const salesOptions = computed(() => {
  let source = scopeSalesRowsByLogin(salesRows.value, auth);
  if (filters.id_cabang) {
    source = source.filter((item) => String(item.id_cabang || item.cabang_id || '') === String(filters.id_cabang));
  }
  if (filters.id_principal) {
    source = source.filter((item) => {
      const ids = Array.isArray(item.id_principals) ? item.id_principals : [item.id_principal, item.principal_id];
      return ids.map((value) => String(value || '')).includes(String(filters.id_principal));
    });
  }
  return [
    { value: '', label: 'Semua sales' },
    ...source.map((item) => ({
      value: String(item.id_sales || item.sales_id || item.id),
      label: `${item.nama || 'Sales'}${item.kode_sales ? ` - ${item.kode_sales}` : ''}`
    }))
  ];
});

const cardRows = computed(() => [
  { label: 'Sales Dicek', value: summary.value.total_sales || 0, tone: 'slate' },
  { label: 'Aman', value: summary.value.aman || 0, tone: 'green' },
  { label: 'Perlu Dicek', value: summary.value.perlu_dicek || 0, tone: 'amber' },
  { label: 'Kunjungan', value: `${summary.value.total_visited || 0}/${summary.value.total_callplan || 0}`, tone: 'blue' },
  { label: 'Order', value: summary.value.total_order || 0, tone: 'violet' },
  { label: 'Omset', value: formatCurrency(summary.value.total_omset || 0), tone: 'green' },
  { label: 'LPH', value: summary.value.total_lph || 0, tone: 'cyan' },
  { label: 'Pembayaran', value: formatCurrency(summary.value.total_payment || 0), tone: 'emerald' }
]);

const checklistDefinitions = [
  { key: 'visit', label: 'Kunjungan Call Plan' },
  { key: 'stock_opname', label: 'Stock Opname Outlet' },
  { key: 'program', label: 'Sosialisasi Program' },
  { key: 'omset', label: 'Omset vs Target' },
  { key: 'retur', label: 'Retur BS Outlet' },
  { key: 'lph', label: 'LPH Sales' },
  { key: 'payment', label: 'Pembayaran Outlet' }
];

const weeklyDefinitions = [
  { key: 'at_nd', label: 'AT vs ND' },
  { key: 'f2_f1_noo', label: 'F2 -> F1 vs NOO' },
  { key: 'omset_timegone', label: 'Omset vs Time Gone' },
  { key: 'program_target', label: 'Program vs Target Outlet' }
];

const manualStatusOptions = [
  { value: '', label: 'Otomatis' },
  { value: 'ok', label: 'Aman' },
  { value: 'warn', label: 'Perlu Dicek' },
  { value: 'bad', label: 'Tidak Sesuai' },
  { value: 'nodata', label: 'Belum Ada Data' }
];

const checklistStatusOptions = [
  { value: 'attention', label: 'Perlu Dicek' },
  { value: 'manual', label: 'Sudah Manual' },
  { value: 'ok', label: 'Aman' },
  { value: 'bad', label: 'Tidak Sesuai' },
  { value: 'warn', label: 'Warning' },
  { value: 'nodata', label: 'Belum Ada Data' }
];

const filterModel = computed({
  get: () => filters,
  set: (value) => {
    Object.assign(filters, value || {});
  }
});

const filterFields = computed(() => [
  { key: 'tanggal', label: 'Tanggal', type: 'date' },
  { key: 'id_perusahaan', label: 'Perusahaan', type: 'search-select', options: companyOptions.value, placeholder: 'Pilih perusahaan' },
  {
    key: 'id_cabang',
    label: 'Cabang',
    type: 'search-select',
    options: branchOptions.value,
    placeholder: 'Pilih cabang',
    disabled: !filters.id_perusahaan,
    emptyText: 'Pilih perusahaan terlebih dahulu.'
  },
  { key: 'id_principal', label: 'Principal', type: 'search-select', options: principalOptions.value, placeholder: 'Semua principal' },
  { key: 'id_sales', label: 'Sales', type: 'search-select', options: salesOptions.value, placeholder: 'Semua sales', emptyText: 'Sales belum tersedia untuk filter ini.' },
  { key: 'checklist_status', label: 'Status Checklist', type: 'select', options: checklistStatusOptions, allLabel: 'Semua status' }
]);

const selectedManualTitle = computed(() => {
  if (!selectedManualRow.value) return 'Input Manual Checklist';
  return `Input Manual ${selectedManualRow.value.nama_sales || 'Sales'}`;
});

const filteredRows = computed(() => {
  const status = String(filters.checklist_status || '');
  if (!status) return rows.value;

  return rows.value.filter((row) => {
    const items = Object.values(row.checklist || {});
    if (status === 'attention') {
      return row.overall_status === 'Perlu Dicek' || items.some((item) => ['warn', 'bad'].includes(item.status));
    }
    if (status === 'manual') {
      return items.some((item) => item.manual);
    }
    return row.overall_status === status || items.some((item) => item.status === status);
  });
});

const filteredWeeklyRows = computed(() => {
  const status = String(filters.checklist_status || '');
  if (!status) return weeklyRows.value;

  return weeklyRows.value.filter((row) => {
    const items = Object.values(row.checklist || {});
    if (status === 'attention') {
      return row.overall_status === 'Perlu Dicek' || items.some((item) => ['warn', 'bad'].includes(item.status));
    }
    if (status === 'manual') return false;
    return row.overall_status === status || items.some((item) => item.status === status);
  });
});

function formatCurrency(value) {
  return new Intl.NumberFormat('id-ID', {
    style: 'currency',
    currency: 'IDR',
    maximumFractionDigits: 0
  }).format(Number(value || 0));
}

function formatDateTime(value) {
  if (!value) return '-';
  return String(value).replace('T', ' ').slice(0, 19);
}

function statusClass(status) {
  if (status === 'ok') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300';
  if (status === 'bad') return 'border-rose-500/30 bg-rose-500/10 text-rose-300';
  if (status === 'warn') return 'border-amber-500/30 bg-amber-500/10 text-amber-300';
  return 'border-slate-600/50 bg-slate-800/60 text-slate-300';
}

function cardClass(tone) {
  const tones = {
    green: 'border-emerald-500/30 bg-emerald-500/10',
    emerald: 'border-emerald-500/30 bg-emerald-500/10',
    amber: 'border-amber-500/30 bg-amber-500/10',
    blue: 'border-sky-500/30 bg-sky-500/10',
    violet: 'border-violet-500/30 bg-violet-500/10',
    cyan: 'border-cyan-500/30 bg-cyan-500/10',
    slate: 'border-slate-700 bg-slate-900/70'
  };
  return tones[tone] || tones.slate;
}

function checklistItem(row, key) {
  return row?.checklist?.[key] || { status: 'nodata', label: '-', value: '-', note: '' };
}

function checklistExportValue(row, key) {
  const item = checklistItem(row, key);
  const value = typeof item.value === 'number' ? item.value : (item.value || '-');
  return `${item.label || '-'} | ${value} | ${item.note || '-'}${item.manual ? ' | Manual' : ''}`;
}

function noteKey(row) {
  return String(row.id_sales || row.id_user_sales || '');
}

function manualKey(row, itemKey) {
  return `${noteKey(row)}:${itemKey}`;
}

function openManualEditor(row) {
  selectedManualRow.value = row;
  manualModalOpen.value = true;
}

function closeManualEditor() {
  manualModalOpen.value = false;
}

function syncDraftNotes() {
  rows.value.forEach((row) => {
    notesDraft[noteKey(row)] = row.supervisor_note || '';
  });
}

function syncManualDrafts() {
  rows.value.forEach((row) => {
    checklistDefinitions.forEach((item) => {
      const key = manualKey(row, item.key);
      const checklist = checklistItem(row, item.key);
      manualDrafts[key] = {
        status: checklist.manual_status || '',
        note: checklist.manual_note || ''
      };
    });
  });
}

function buildParams() {
  return Object.fromEntries(
    Object.entries(filters).filter(([key, value]) => key !== 'checklist_status' && value !== '' && value !== null && value !== undefined)
  );
}

function exportDailyChecklist() {
  const columns = [
    { label: 'Tanggal', value: () => meta.value.tanggal || filters.tanggal },
    { label: 'Sales', value: (row) => row.nama_sales || '-' },
    { label: 'Kode Sales', value: (row) => row.kode_sales || '-' },
    { label: 'Cabang', value: (row) => row.nama_cabang || '-' },
    { label: 'Status Umum', value: (row) => row.overall_status || '-' },
    ...checklistDefinitions.map((item) => ({
      label: item.label,
      value: (row) => checklistExportValue(row, item.key)
    })),
    { label: 'Way-out Supervisor', value: (row) => row.supervisor_note || '-' }
  ];
  exportRowsToCsv(`checklist-kinerja-sales-${filters.tanggal || 'harian'}.csv`, columns, filteredRows.value);
}

function exportWeeklyChecklist() {
  const columns = [
    { label: 'Periode Awal', value: () => weeklySummary.value.week_start || meta.value.week_start || '-' },
    { label: 'Periode Akhir', value: () => weeklySummary.value.week_end || meta.value.week_end || '-' },
    { label: 'Sales', value: (row) => row.nama_sales || '-' },
    { label: 'Kode Sales', value: (row) => row.kode_sales || '-' },
    { label: 'Cabang', value: (row) => row.nama_cabang || '-' },
    { label: 'Outlet Tersentuh', value: (row) => `${row.reached_outlet_count || 0}/${row.active_outlet_count || 0}` },
    { label: 'Order Minggu Ini', value: (row) => row.week_order_count || 0 },
    { label: 'Omset Minggu Ini', value: (row) => row.week_omset || 0 },
    ...weeklyDefinitions.map((item) => ({
      label: item.label,
      value: (row) => checklistExportValue(row, item.key)
    })),
    { label: 'Way-out', value: (row) => row.weekly_way_out || '-' }
  ];
  exportRowsToCsv(`evaluasi-mingguan-sales-${weeklySummary.value.week_start || filters.tanggal || 'mingguan'}.csv`, columns, filteredWeeklyRows.value);
}

async function loadReferences() {
  referenceLoading.value = true;
  pageError.value = '';
  try {
    const [companyResponse, branchResponse, principalResponse, salesResponse] = await Promise.all([
      getCompanies({ no_paginate: true }),
      getBranches({ no_paginate: true }),
      getPrincipals({ no_paginate: true }),
      getSales({ no_paginate: true })
    ]);
    companies.value = normalizeList(unwrapResponse(companyResponse));
    branches.value = normalizeList(unwrapResponse(branchResponse));
    principals.value = normalizeList(unwrapResponse(principalResponse));
    salesRows.value = normalizeList(unwrapResponse(salesResponse));
    syncSupervisorCompanyFromBranch(filters, 'id_cabang', 'id_perusahaan', branches.value, companies.value);
  } catch (error) {
    pageError.value = normalizeError(error, 'Referensi checklist supervisor belum bisa dimuat.');
  } finally {
    referenceLoading.value = false;
  }
}

async function loadReport() {
  loading.value = true;
  pageError.value = '';
  feedback.value = '';
  try {
    const response = await getSupervisorSalesPerformanceChecklist(buildParams());
    const payload = unwrapResponse(response) || {};
    rows.value = normalizeList(payload.rows);
    weeklyRows.value = normalizeList(payload.weekly?.rows);
    dailyAnalysis.value = normalizeList(payload.daily_analysis);
    summary.value = payload.summary || {};
    weeklySummary.value = payload.weekly?.summary || {};
    meta.value = payload.meta || {};
    syncDraftNotes();
    syncManualDrafts();
    feedback.value = rows.value.length
      ? `Checklist memuat ${rows.value.length} sales untuk tanggal ${filters.tanggal}.`
      : 'Belum ada sales pada filter ini.';
  } catch (error) {
    pageError.value = normalizeError(error, 'Checklist kinerja sales belum bisa dimuat.');
  } finally {
    loading.value = false;
  }
}

async function saveManualItem(row, item) {
  const key = manualKey(row, item.key);
  const draft = manualDrafts[key] || {};
  savingManualId.value = key;
  pageError.value = '';
  feedback.value = '';
  try {
    await saveSupervisorSalesPerformanceChecklistItem({
      tanggal: filters.tanggal,
      id_sales: row.id_sales,
      id_user_sales: row.id_user_sales,
      item_key: item.key,
      status: draft.status || '',
      note: draft.note || ''
    });
    feedback.value = draft.status
      ? `Input manual ${item.label} untuk ${row.nama_sales || 'sales'} tersimpan.`
      : `Input manual ${item.label} untuk ${row.nama_sales || 'sales'} kembali otomatis.`;
    manualModalOpen.value = false;
    await loadReport();
  } catch (error) {
    pageError.value = normalizeError(error, 'Input manual checklist belum bisa disimpan.');
  } finally {
    savingManualId.value = '';
  }
}

async function saveManualRow() {
  const row = selectedManualRow.value;
  if (!row) return;

  savingManualId.value = noteKey(row);
  pageError.value = '';
  feedback.value = '';
  try {
    await Promise.all(
      checklistDefinitions.map((item) => {
        const key = manualKey(row, item.key);
        const draft = manualDrafts[key] || {};
        return saveSupervisorSalesPerformanceChecklistItem({
          tanggal: filters.tanggal,
          id_sales: row.id_sales,
          id_user_sales: row.id_user_sales,
          item_key: item.key,
          status: draft.status || '',
          note: draft.note || ''
        });
      })
    );
    feedback.value = `Input manual checklist ${row.nama_sales || 'sales'} tersimpan.`;
    manualModalOpen.value = false;
    await loadReport();
  } catch (error) {
    pageError.value = normalizeError(error, 'Input manual checklist belum bisa disimpan.');
  } finally {
    savingManualId.value = '';
  }
}

function resetFilters() {
  filters.tanggal = toLocalDateInputValue();
  filters.id_perusahaan = '';
  filters.id_cabang = '';
  filters.id_principal = '';
  filters.id_sales = '';
  filters.checklist_status = '';
  syncSupervisorCompanyFromBranch(filters, 'id_cabang', 'id_perusahaan', branches.value, companies.value);
  loadReport();
}

async function saveNote(row) {
  const key = noteKey(row);
  savingNoteId.value = key;
  pageError.value = '';
  feedback.value = '';
  try {
    await saveSupervisorSalesPerformanceChecklistNote({
      tanggal: filters.tanggal,
      id_sales: row.id_sales,
      id_user_sales: row.id_user_sales,
      note: notesDraft[key] || ''
    });
    row.supervisor_note = notesDraft[key] || '';
    feedback.value = `Catatan ${row.nama_sales || 'sales'} tersimpan.`;
  } catch (error) {
    pageError.value = normalizeError(error, 'Catatan checklist belum bisa disimpan.');
  } finally {
    savingNoteId.value = '';
  }
}

watch(() => filters.id_perusahaan, () => {
  resetSupervisorBranchWhenCompanyChanges(filters, 'id_perusahaan', 'id_cabang', branches.value, auth, companies.value);
  filters.id_principal = '';
  filters.id_sales = '';
});

watch(() => filters.id_cabang, () => {
  syncSupervisorCompanyFromBranch(filters, 'id_cabang', 'id_perusahaan', branches.value, companies.value);
  filters.id_sales = '';
});

onMounted(async () => {
  await loadReferences();
  await loadReport();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Checklist Kinerja Sales"
      description="Pemantauan harian untuk callplan, stock opname, omset, retur, LPH, pembayaran, dan catatan tindak lanjut supervisor."
    >
      <div class="flex flex-wrap gap-2">
        <button
          class="rounded-xl border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-200 hover:border-emerald-500 hover:text-emerald-200 disabled:opacity-60"
          :disabled="loading || !filteredRows.length"
          @click="exportDailyChecklist"
        >
          Export Harian
        </button>
        <button
          class="rounded-xl border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-200 hover:border-emerald-500 hover:text-emerald-200 disabled:opacity-60"
          :disabled="loading || !filteredWeeklyRows.length"
          @click="exportWeeklyChecklist"
        >
          Export Mingguan
        </button>
      </div>
    </PageHeader>

    <AppFilterBar v-model="filterModel" :fields="filterFields" @submit="loadReport" @reset="resetFilters" />

    <div v-if="pageError" class="rounded-2xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
      {{ pageError }}
    </div>
    <div v-if="feedback" class="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
      {{ feedback }}
    </div>

    <section class="grid gap-4 md:grid-cols-4 xl:grid-cols-8">
      <div v-for="card in cardRows" :key="card.label" :class="['rounded-2xl border p-4', cardClass(card.tone)]">
        <p class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">{{ card.label }}</p>
        <p class="mt-2 text-2xl font-bold text-white">{{ card.value }}</p>
      </div>
    </section>

    <section class="rounded-2xl border border-slate-800 bg-slate-900/70 p-2">
      <div class="flex flex-wrap gap-2">
        <button
          class="rounded-xl px-4 py-2 text-sm font-semibold transition"
          :class="activeTab === 'daily' ? 'bg-emerald-600 text-white' : 'text-slate-300 hover:bg-slate-800'"
          @click="activeTab = 'daily'"
        >
          Checklist Harian
        </button>
        <button
          class="rounded-xl px-4 py-2 text-sm font-semibold transition"
          :class="activeTab === 'weekly' ? 'bg-emerald-600 text-white' : 'text-slate-300 hover:bg-slate-800'"
          @click="activeTab = 'weekly'"
        >
          Evaluasi Mingguan
        </button>
      </div>
    </section>

    <section v-if="activeTab === 'daily'" class="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/70">
      <div class="border-b border-slate-800 px-5 py-4">
        <h2 class="text-lg font-bold text-white">Checklist Harian</h2>
        <p class="mt-1 text-sm text-slate-400">Tanggal {{ meta.tanggal || filters.tanggal }}. Status otomatis dapat dilengkapi dengan catatan way-out supervisor.</p>
      </div>

      <div v-if="dailyAnalysis.length" class="border-b border-slate-800 px-5 py-4">
        <h3 class="text-sm font-bold uppercase tracking-[0.16em] text-amber-200">Analisa Dashboard Poin 1-4</h3>
        <div class="mt-3 grid gap-3 lg:grid-cols-2">
          <article v-for="item in dailyAnalysis" :key="item.title" class="rounded-xl border border-slate-700 bg-slate-950/70 p-4">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <h4 class="font-semibold text-white">{{ item.title }}</h4>
              <span class="rounded-full border px-2 py-1 text-xs font-semibold" :class="statusClass(item.status)">
                {{ item.status === 'ok' ? 'Aman' : item.status === 'warn' ? 'Perlu Dicek' : 'Belum Ada Data' }}
              </span>
            </div>
            <p class="mt-2 text-sm text-slate-300">{{ item.summary }}</p>
            <p class="mt-2 text-xs leading-relaxed text-amber-100/90">Way-out: {{ item.way_out }}</p>
          </article>
        </div>
      </div>

      <div v-if="loading" class="px-5 py-12 text-center text-sm text-slate-400">
        Memuat checklist...
      </div>
      <div v-else-if="!filteredRows.length" class="px-5 py-12 text-center text-sm text-slate-400">
        Belum ada data checklist untuk filter ini.
      </div>
      <div v-else class="overflow-x-auto">
        <table class="min-w-[1280px] w-full text-left text-sm">
          <thead class="bg-slate-950/80 text-xs uppercase tracking-[0.14em] text-slate-400">
            <tr>
              <th class="px-4 py-3">Sales</th>
              <th v-for="item in checklistDefinitions" :key="item.key" class="px-4 py-3">{{ item.label }}</th>
              <th class="px-4 py-3">Way-out</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800">
            <tr v-for="row in filteredRows" :key="row.id_sales" class="align-top">
              <td class="w-56 px-4 py-4">
                <div class="font-semibold text-white">{{ row.nama_sales }}</div>
                <div class="mt-1 text-xs text-slate-400">{{ row.kode_sales || '-' }} · {{ row.nama_cabang || '-' }}</div>
                <div class="mt-3 inline-flex rounded-full border px-2 py-1 text-xs font-semibold" :class="row.overall_status === 'Aman' ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : 'border-amber-500/30 bg-amber-500/10 text-amber-300'">
                  {{ row.overall_status }}
                </div>
                <button
                  class="mt-3 rounded-lg border border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-200 hover:border-emerald-500 hover:text-emerald-200"
                  @click="openManualEditor(row)"
                >
                  Input Manual
                </button>
              </td>
              <td v-for="item in checklistDefinitions" :key="`${row.id_sales}-${item.key}`" class="w-44 px-4 py-4">
                <div class="flex flex-wrap items-center gap-2">
                  <div class="inline-flex rounded-full border px-2 py-1 text-xs font-semibold" :class="statusClass(checklistItem(row, item.key).status)">
                    {{ checklistItem(row, item.key).label }}
                  </div>
                  <span v-if="checklistItem(row, item.key).manual" class="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-cyan-200">
                    Manual
                  </span>
                </div>
                <div class="mt-2 text-sm font-semibold text-white">
                  <template v-if="typeof checklistItem(row, item.key).value === 'number' && ['omset', 'payment'].includes(item.key)">
                    {{ formatCurrency(checklistItem(row, item.key).value) }}
                  </template>
                  <template v-else>
                    {{ checklistItem(row, item.key).value }}
                  </template>
                </div>
                <p v-if="checklistItem(row, item.key).manual" class="mt-1 text-[11px] leading-relaxed text-cyan-200/90">
                  Otomatis: {{ checklistItem(row, item.key).auto_label || '-' }}
                </p>
                <p class="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-400">{{ checklistItem(row, item.key).note }}</p>
              </td>
              <td class="w-72 px-4 py-4">
                <textarea
                  v-model="notesDraft[noteKey(row)]"
                  rows="4"
                  class="w-full resize-none rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-emerald-400"
                  placeholder="Tulis tindak lanjut, kendala, atau way-out..."
                />
                <div class="mt-2 flex items-center justify-between gap-3">
                  <span class="text-xs text-slate-500">Update: {{ formatDateTime(row.supervisor_note_updated_at) }}</span>
                  <button class="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-500 disabled:opacity-60" :disabled="savingNoteId === noteKey(row)" @click="saveNote(row)">
                    {{ savingNoteId === noteKey(row) ? 'Simpan...' : 'Simpan' }}
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-else class="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/70">
      <div class="border-b border-slate-800 px-5 py-4">
        <h2 class="text-lg font-bold text-white">Evaluasi Mingguan</h2>
        <p class="mt-1 text-sm text-slate-400">
          Periode {{ weeklySummary.week_start || meta.week_start || '-' }} sampai {{ weeklySummary.week_end || meta.week_end || '-' }}. AT/ND memakai outlet aktif plafon dibanding outlet yang dikunjungi atau order minggu ini.
        </p>
        <div class="mt-4 grid gap-3 md:grid-cols-4">
          <div class="rounded-xl border border-slate-700 bg-slate-950/70 p-4">
            <p class="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">AT/ND &lt; 80%</p>
            <p class="mt-2 text-xl font-bold text-white">{{ weeklySummary.at_nd_under_80 || 0 }}</p>
          </div>
          <div class="rounded-xl border border-slate-700 bg-slate-950/70 p-4">
            <p class="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">Omset Kurang</p>
            <p class="mt-2 text-xl font-bold text-white">{{ weeklySummary.omset_under_timegone || 0 }}</p>
          </div>
          <div class="rounded-xl border border-slate-700 bg-slate-950/70 p-4">
            <p class="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">Omset Minggu Ini</p>
            <p class="mt-2 text-xl font-bold text-white">{{ formatCurrency(weeklySummary.total_week_omset || 0) }}</p>
          </div>
          <div class="rounded-xl border border-slate-700 bg-slate-950/70 p-4">
            <p class="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">Target Bulan</p>
            <p class="mt-2 text-xl font-bold text-white">{{ formatCurrency(weeklySummary.total_target_omset || 0) }}</p>
          </div>
        </div>
      </div>

      <div v-if="loading" class="px-5 py-12 text-center text-sm text-slate-400">
        Memuat evaluasi mingguan...
      </div>
      <div v-else-if="!filteredWeeklyRows.length" class="px-5 py-12 text-center text-sm text-slate-400">
        Belum ada data evaluasi mingguan untuk filter ini.
      </div>
      <div v-else class="overflow-x-auto">
        <table class="min-w-[1180px] w-full text-left text-sm">
          <thead class="bg-slate-950/80 text-xs uppercase tracking-[0.14em] text-slate-400">
            <tr>
              <th class="px-4 py-3">Sales</th>
              <th v-for="item in weeklyDefinitions" :key="item.key" class="px-4 py-3">{{ item.label }}</th>
              <th class="px-4 py-3">Way-out</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800">
            <tr v-for="row in filteredWeeklyRows" :key="`weekly-${row.id_sales}`" class="align-top">
              <td class="w-56 px-4 py-4">
                <div class="font-semibold text-white">{{ row.nama_sales }}</div>
                <div class="mt-1 text-xs text-slate-400">{{ row.kode_sales || '-' }} · {{ row.nama_cabang || '-' }}</div>
                <div class="mt-3 text-xs text-slate-400">
                  Outlet {{ row.reached_outlet_count || 0 }}/{{ row.active_outlet_count || 0 }} · Order {{ row.week_order_count || 0 }}
                </div>
              </td>
              <td v-for="item in weeklyDefinitions" :key="`weekly-${row.id_sales}-${item.key}`" class="w-48 px-4 py-4">
                <div class="inline-flex rounded-full border px-2 py-1 text-xs font-semibold" :class="statusClass(checklistItem(row, item.key).status)">
                  {{ checklistItem(row, item.key).label }}
                </div>
                <div class="mt-2 text-sm font-semibold text-white">
                  <template v-if="item.key === 'omset_timegone'">
                    {{ formatCurrency(checklistItem(row, item.key).value) }}
                  </template>
                  <template v-else>
                    {{ checklistItem(row, item.key).value }}
                  </template>
                </div>
                <p class="mt-1 text-xs leading-relaxed text-slate-400">{{ checklistItem(row, item.key).note }}</p>
              </td>
              <td class="w-72 px-4 py-4 text-sm leading-relaxed text-slate-300">
                {{ row.weekly_way_out || '-' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <AppModal
      :open="manualModalOpen"
      :title="selectedManualTitle"
      :description="selectedManualRow ? `${selectedManualRow.nama_sales || 'Sales'} - ${selectedManualRow.kode_sales || '-'}` : 'Pilih status manual untuk checklist sales.'"
      size="6xl"
      @close="closeManualEditor"
    >
      <div v-if="selectedManualRow" class="space-y-5">
        <div class="rounded-2xl border border-slate-700 bg-slate-950/70 p-4">
          <p class="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">Ringkasan Sales</p>
          <div class="mt-3 flex flex-wrap items-center gap-3">
            <div>
              <p class="text-lg font-bold text-white">{{ selectedManualRow.nama_sales || '-' }}</p>
              <p class="text-sm text-slate-400">{{ selectedManualRow.kode_sales || '-' }} · {{ selectedManualRow.nama_cabang || '-' }}</p>
            </div>
            <span class="rounded-full border px-2 py-1 text-xs font-semibold" :class="selectedManualRow.overall_status === 'Aman' ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : 'border-amber-500/30 bg-amber-500/10 text-amber-300'">
              {{ selectedManualRow.overall_status || '-' }}
            </span>
          </div>
        </div>

        <div class="max-h-[62vh] space-y-3 overflow-y-auto pr-1">
          <article
            v-for="item in checklistDefinitions"
            :key="`manual-row-${item.key}`"
            class="rounded-2xl border border-slate-800 bg-slate-950/60 p-4"
          >
            <div class="grid gap-4 lg:grid-cols-[minmax(220px,0.9fr)_minmax(280px,1.2fr)_minmax(260px,1fr)]">
              <div>
                <p class="font-semibold text-white">{{ item.label }}</p>
                <div class="mt-2 flex flex-wrap items-center gap-2">
                  <span class="rounded-full border px-2 py-1 text-xs font-semibold" :class="statusClass(checklistItem(selectedManualRow, item.key).status)">
                    {{ checklistItem(selectedManualRow, item.key).label }}
                  </span>
                  <span v-if="checklistItem(selectedManualRow, item.key).manual" class="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-cyan-200">
                    Manual
                  </span>
                </div>
                <p class="mt-2 text-xs leading-relaxed text-slate-400">{{ checklistItem(selectedManualRow, item.key).note || '-' }}</p>
              </div>

              <div>
                <p class="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">Status Manual</p>
                <div v-if="manualDrafts[manualKey(selectedManualRow, item.key)]" class="mt-2 grid gap-2 sm:grid-cols-2">
                  <label
                    v-for="option in manualStatusOptions"
                    :key="option.value"
                    class="flex cursor-pointer items-center gap-2 rounded-xl border px-3 py-2 text-xs font-semibold transition"
                    :class="manualDrafts[manualKey(selectedManualRow, item.key)].status === option.value ? 'border-emerald-400 bg-emerald-500/15 text-emerald-100' : 'border-slate-700 bg-slate-900/80 text-slate-300 hover:border-slate-500'"
                  >
                    <input
                      v-model="manualDrafts[manualKey(selectedManualRow, item.key)].status"
                      type="radio"
                      :name="`manual-modal-${selectedManualRow.id_sales}-${item.key}`"
                      :value="option.value"
                      class="h-3.5 w-3.5 accent-emerald-500"
                    />
                    <span>{{ option.label }}</span>
                  </label>
                </div>
              </div>

              <label v-if="manualDrafts[manualKey(selectedManualRow, item.key)]" class="block">
                <span class="mb-2 block text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">Catatan Manual</span>
                <textarea
                  v-model="manualDrafts[manualKey(selectedManualRow, item.key)].note"
                  rows="4"
                  class="w-full resize-none rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-emerald-400"
                  placeholder="Alasan koreksi atau way-out..."
                />
              </label>
            </div>
          </article>
        </div>

        <div class="flex flex-wrap justify-end gap-3">
          <button class="rounded-xl border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-200 hover:bg-slate-800" @click="closeManualEditor">
            Batal
          </button>
          <button
            class="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-60"
            :disabled="savingManualId === noteKey(selectedManualRow)"
            @click="saveManualRow"
          >
            {{ savingManualId === noteKey(selectedManualRow) ? 'Menyimpan...' : 'Simpan Semua Manual' }}
          </button>
        </div>
      </div>
    </AppModal>
  </div>
</template>
