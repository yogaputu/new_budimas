<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { RouterLink } from 'vue-router';
import {
  getBranches,
  getCompanies,
  getPrincipals,
  getSales,
  getSupervisorSalesCallplanCalendar,
  getSupervisorSalesVisitReport,
} from '@/api/master';
import { getMonthlySalesTargets } from '@/api/sales';
import { useAuthStore } from '@/app/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { scopeSalesRowsByLogin } from '@/utils/accessScope';
import { toLocalDateInputValue } from '@/utils/date';
import { resolveDashboardPanels } from '@/modules/supervisor-sales/utils/dashboardPanels';
import AppEmptyState from '@/shared/components/AppEmptyState.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
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

const monthlyFilters = reactive({
  tahun: String(now.getFullYear()),
  bulan: String(now.getMonth() + 1).padStart(2, '0'),
  id_perusahaan: '',
  id_principal: '',
  id_cabang: '',
});

const dailyFilters = reactive({
  companyId: '',
  branchId: '',
  principalId: '',
  salesId: '',
  date: toLocalDateInputValue(),
});

const loading = ref(false);
const error = ref('');
const feedback = ref('');
const companyRows = ref([]);
const branchRows = ref([]);
const principalRows = ref([]);
const salesRows = ref([]);
const targetRows = ref([]);
const targetsUnavailable = ref(false);
const dailyReportRows = ref([]);
const calendarRows = ref([]);
const buildingBlockHistory = ref([]);

const fallbackBranchId = computed(() => auth.user?.id_cabang || auth.user?.cabang_id || auth.user?.cabang?.id || '');
const activeCompanyId = computed(() =>
  String(
    auth.user?.perusahaan?.id ||
    auth.user?.id_perusahaan ||
    branchRows.value.find((item) => String(item.id) === String(fallbackBranchId.value))?.id_perusahaan ||
    ''
  )
);

const monthOptions = [
  { value: '01', label: 'Januari' },
  { value: '02', label: 'Februari' },
  { value: '03', label: 'Maret' },
  { value: '04', label: 'April' },
  { value: '05', label: 'Mei' },
  { value: '06', label: 'Juni' },
  { value: '07', label: 'Juli' },
  { value: '08', label: 'Agustus' },
  { value: '09', label: 'September' },
  { value: '10', label: 'Oktober' },
  { value: '11', label: 'November' },
  { value: '12', label: 'Desember' },
];

const companyOptions = computed(() =>
  getSupervisorCompanyOptions(companyRows.value, branchRows.value, '', auth, true)
);

const dailyBranchOptions = computed(() => getSupervisorBranchOptions(branchRows.value, auth, true, dailyFilters.companyId, companyRows.value));
const monthlyBranchOptions = computed(() => getSupervisorBranchOptions(branchRows.value, auth, true, monthlyFilters.id_perusahaan, companyRows.value));

const principalOptions = computed(() => {
  const companyId = String(dailyFilters.companyId || '');
  return getSupervisorPrincipalOptions(principalRows.value, companyId, true);
});

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
  const branchId = String(dailyFilters.branchId || '');
  const principalId = String(dailyFilters.principalId || '');

  let source = scopeSalesRowsByLogin(salesRows.value, auth).filter((item) =>
    matchesFilter(item, branchId, ['id_cabang', 'cabang_id', 'idCabang'])
  );

  source = source.filter((item) =>
    matchesFilter(item, principalId, ['id_principal', 'principal_id', 'id_principals'])
  );

  return [
    { value: '', label: 'Semua Sales' },
    ...source.map((item) => ({
      value: String(item.id_sales || item.sales_id || item.id),
      label: `${item.nama || 'Sales'}${item.kode_sales ? ` - ${item.kode_sales}` : ''}`,
    })),
  ];
});

function normalizeDashboardDate(value) {
  const raw = String(value || '').trim();
  const matched = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (matched) {
    const year = Number(matched[1]);
    const month = Number(matched[2]);
    const day = Number(matched[3]);
    const candidate = new Date(year, month - 1, day);
    if (
      candidate.getFullYear() === year
      && candidate.getMonth() === month - 1
      && candidate.getDate() === day
    ) {
      return raw;
    }
  }
  return toLocalDateInputValue();
}

function normalizeDashboardYear(value) {
  const year = Number(value);
  return Number.isInteger(year) && year >= 2000 && year <= 2100
    ? year
    : now.getFullYear();
}

function normalizeDashboardMonth(value) {
  const month = Number(value);
  return Number.isInteger(month) && month >= 1 && month <= 12
    ? month
    : now.getMonth() + 1;
}

const normalizedDailyDate = computed(() => normalizeDashboardDate(dailyFilters.date));
const normalizedDailyDateObject = computed(() => new Date(`${normalizedDailyDate.value}T00:00:00`));

const derivedDayLabel = computed(() => {
  if (!normalizedDailyDate.value) return '-';
  const days = ['Minggu', 'Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu'];
  return days[normalizedDailyDateObject.value.getDay()] || '-';
});

const derivedWeekLabel = computed(() => {
  if (!normalizedDailyDate.value) return '-';
  return `Week ${Math.min(Math.ceil(normalizedDailyDateObject.value.getDate() / 7), 4)}`;
});

const targetSummary = computed(() => {
  const totalTargetVisit = targetRows.value.reduce((sum, row) => sum + Number(row.target_kunjungan || 0), 0);
  const totalActualVisit = targetRows.value.reduce((sum, row) => sum + Number(row.actual_kunjungan || 0), 0);
  const totalTargetOmset = targetRows.value.reduce((sum, row) => sum + Number(row.target_omset || 0), 0);
  const totalActualOmset = targetRows.value.reduce((sum, row) => sum + Number(row.actual_omset || 0), 0);

  return {
    totalTargetVisit,
    totalActualVisit,
    visitAchievement: totalTargetVisit > 0 ? Math.round((totalActualVisit / totalTargetVisit) * 10000) / 100 : 0,
    totalTargetOmset,
    totalActualOmset,
    omsetGap: totalActualOmset - totalTargetOmset,
  };
});

const dailySummaryCards = computed(() => {
  const totalOutlet = dailyReportRows.value.filter((row) => row.data_source !== 'actual').length;
  const totalOrder = dailyReportRows.value.filter((row) => Number(row.has_order || 0) === 1).length;

  return [
    { key: 'outlet', label: 'Total Outlet', value: totalOutlet.toLocaleString('id-ID'), accent: 'text-brand-600', tone: 'border-brand-200' },
    { key: 'order', label: 'Total Order', value: totalOrder.toLocaleString('id-ID'), accent: 'text-sky-600', tone: 'border-sky-200' },
    { key: 'target', label: 'Target Omset', value: targetsUnavailable.value ? '—' : `Rp ${targetSummary.value.totalTargetOmset.toLocaleString('id-ID')}`, accent: 'text-emerald-600', tone: 'border-emerald-200' },
    { key: 'actual', label: 'MTD (Actual)', value: targetsUnavailable.value ? '—' : `Rp ${targetSummary.value.totalActualOmset.toLocaleString('id-ID')}`, accent: 'text-violet-600', tone: 'border-violet-200' },
    { key: 'gap', label: 'Gap MTD', value: targetsUnavailable.value ? '—' : `${targetSummary.value.omsetGap >= 0 ? '+' : '-'} Rp ${Math.abs(targetSummary.value.omsetGap).toLocaleString('id-ID')}`, accent: targetSummary.value.omsetGap >= 0 ? 'text-emerald-600' : 'text-rose-600', tone: 'border-rose-200' },
  ];
});

const perSalesDailyRows = computed(() => {
  const buckets = new Map();

  dailyReportRows.value.forEach((row) => {
    const salesKey = String(row.id_user_sales || row.id_sales || row.nama_sales || row.kode_customer || '');
    if (!buckets.has(salesKey)) {
      buckets.set(salesKey, {
        code: row.kode_sales || row.id_sales || row.id_user_sales || '-',
        sales: row.nama_sales || 'Tanpa Sales',
        cp: 0,
        ac: 0,
        ec: 0,
        nc: 0,
        nec: 0,
      });
    }

    const bucket = buckets.get(salesKey);
    const isCallplan = row.data_source !== 'actual';
    const isVisited = [1, 2].includes(Number(row.status_kunjungan || 0));
    const hasOrder = Number(row.has_order || 0) === 1;

    if (isCallplan) {
      bucket.cp += 1;
      if (isVisited) {
        bucket.ac += 1;
        if (hasOrder) bucket.ec += 1;
        else bucket.nec += 1;
      } else {
        bucket.nc += 1;
      }
    } else if (isVisited) {
      bucket.ac += 1;
    }
  });

  return Array.from(buckets.values())
    .map((item) => ({
      ...item,
      percent: item.cp > 0 ? Math.round((item.ac / item.cp) * 100) : 0,
    }))
    .sort((left, right) => right.cp - left.cp || right.ac - left.ac || left.sales.localeCompare(right.sales));
});

const maxDailyChartValue = computed(() =>
  Math.max(...perSalesDailyRows.value.map((item) => Math.max(item.cp || 0, item.nc + item.nec + item.ec || 0)), 1)
);

const chartRows = computed(() =>
  perSalesDailyRows.value.slice(0, 12).map((item) => {
    const base = Math.max(maxDailyChartValue.value, 1);
    const stackTotal = item.nc + item.nec + item.ec;
    return {
      ...item,
      cpHeight: `${Math.max(8, (item.cp / base) * 100)}%`,
      stackHeight: `${Math.max(8, (stackTotal / base) * 100)}%`,
      ncHeight: stackTotal > 0 ? `${(item.nc / stackTotal) * 100}%` : '0%',
      necHeight: stackTotal > 0 ? `${(item.nec / stackTotal) * 100}%` : '0%',
      ecHeight: stackTotal > 0 ? `${(item.ec / stackTotal) * 100}%` : '0%',
    };
  })
);

const activityTableRows = computed(() =>
  perSalesDailyRows.value.map((item) => ({
    ...item,
    percent_badge: {
      text: `${item.percent}%`,
      className: [
        'inline-flex min-w-[78px] items-center justify-center rounded-full px-3 py-1 text-xs font-semibold',
        item.percent >= 100
          ? 'bg-emerald-100 text-emerald-700'
          : item.percent >= 80
            ? 'bg-sky-100 text-sky-700'
            : item.percent >= 50
              ? 'bg-amber-100 text-amber-700'
              : 'bg-rose-100 text-rose-700',
      ].join(' '),
    },
  }))
);

const activityColumns = [
  { key: 'code', label: 'Kode' },
  { key: 'sales', label: 'Salesman' },
  { key: 'cp', label: 'CP' },
  { key: 'ac', label: 'AC' },
  { key: 'ec', label: 'EC' },
  { key: 'nc', label: 'NC' },
  { key: 'nec', label: 'NEC' },
  { key: 'percent_badge', label: '%' },
];

const calendarPreviewRows = computed(() => {
  const todayText = normalizedDailyDate.value;
  return calendarRows.value.filter((row) => row.date >= todayText && Number(row.callplan_count || 0) > 0).slice(0, 6);
});

function getHistoryLabel(period, index) {
  return `B${index + 1}`;
}

const historyLegend = computed(() =>
  buildingBlockHistory.value.map((period, index) => ({
    key: getHistoryLabel(period, index),
    label: `${getHistoryLabel(period, index)} • ${period.label}`,
  }))
);

const buildingBlockRows = computed(() => {
  const latest = buildingBlockHistory.value[buildingBlockHistory.value.length - 1];
  if (!latest) return [];

  const latestMap = new Map((latest.rows || []).map((row) => [String(row.id_sales), row]));
  const historyMaps = buildingBlockHistory.value.map((period) => ({
    label: period.label,
    map: new Map((period.rows || []).map((row) => [String(row.id_sales), row])),
  }));

  return targetRows.value
    .map((currentRow) => {
      const idSales = String(currentRow.id_sales);
      const latestRow = latestMap.get(idSales) || currentRow;
      const values = historyMaps.map(({ map }) => Number(map.get(idSales)?.actual_omset || 0));
      const avg = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
      const mtd = Number(latestRow.actual_omset || 0);
      const gap = mtd - avg;
      const percent = avg > 0 ? Math.round((mtd / avg) * 10000) / 100 : 0;

      let analysis = 'Stabil';
      if (gap > 0 && percent >= 110) analysis = 'Naik';
      else if (gap < 0 && percent < 90) analysis = 'Turun';
      else if (mtd === 0) analysis = 'Belum Bergerak';

      const row = {
        id_sales: currentRow.id_sales,
        sales: currentRow.nama_sales || '-',
        coverage: `${currentRow.nama_cabang || '-'} | ${currentRow.nama_principals || '-'}`,
        avg,
        mtd,
        gap,
        percent_badge: {
          text: `${percent.toLocaleString('id-ID', { minimumFractionDigits: 0, maximumFractionDigits: 2 })}%`,
          className: [
            'inline-flex min-w-[82px] items-center justify-center rounded-full px-3 py-1 text-xs font-semibold',
            percent >= 110
              ? 'bg-emerald-100 text-emerald-700'
              : percent >= 90
                ? 'bg-sky-100 text-sky-700'
                : percent > 0
                  ? 'bg-amber-100 text-amber-700'
                  : 'bg-slate-100 text-slate-600',
          ].join(' '),
        },
        analysis_badge: {
          text: analysis,
          className: [
            'inline-flex min-w-[96px] items-center justify-center rounded-full px-3 py-1 text-xs font-semibold',
            analysis === 'Naik'
              ? 'bg-emerald-100 text-emerald-700'
              : analysis === 'Turun'
                ? 'bg-rose-100 text-rose-700'
                : analysis === 'Belum Bergerak'
                  ? 'bg-slate-100 text-slate-600'
                  : 'bg-sky-100 text-sky-700',
          ].join(' '),
        },
      };

      historyMaps.forEach(({ map }, index) => {
        row[`b${index + 1}`] = Number(map.get(idSales)?.actual_omset || 0);
      });

      return row;
    })
    .sort((left, right) => right.mtd - left.mtd || right.avg - left.avg);
});

const buildingBlockColumns = computed(() => {
  const baseColumns = [
    { key: 'sales', label: 'Sales' },
    { key: 'coverage', label: 'Cakupan' },
    {
      key: 'avg',
      label: 'AVG 6 Bulan',
      render: (row) => `Rp ${Number(row.avg || 0).toLocaleString('id-ID')}`,
    },
    {
      key: 'mtd',
      label: 'MTD',
      render: (row) => `Rp ${Number(row.mtd || 0).toLocaleString('id-ID')}`,
    },
    {
      key: 'gap',
      label: 'Gap',
      render: (row) => {
        const value = Number(row.gap || 0);
        return `${value >= 0 ? '+' : '-'} Rp ${Math.abs(value).toLocaleString('id-ID')}`;
      },
    },
    { key: 'percent_badge', label: '%' },
  ];

  historyLegend.value.forEach((item, index) => {
    baseColumns.push({
      key: `b${index + 1}`,
      label: item.key,
      render: (row) => `Rp ${Number(row[`b${index + 1}`] || 0).toLocaleString('id-ID')}`,
    });
  });

  baseColumns.push({ key: 'analysis_badge', label: 'Analisa' });
  return baseColumns;
});

const supportLinks = [
  { title: 'Kalender Call Plan', description: 'Buka kalender bulanan untuk melihat sebaran callplan per hari.', to: '/supervisor-sales/callplan-calendar' },
  { title: 'Absensi Sales', description: 'Cek siapa yang sudah check in, masih di lapangan, atau sudah check out.', to: '/supervisor-sales/attendance' },
  { title: 'Analisa DOI', description: 'Lihat stok tipis, sehat, overstock, dan produk yang belum bergerak.', to: '/supervisor-sales/doi-analysis' },
  { title: 'Monitoring Retur', description: 'Tindak lanjuti retur yang menunggu KPR, retur stock, atau credit note.', to: '/sales-order/retur-tracking' },
];

async function loadReferences() {
  const [companyResponse, branchResponse, principalResponse, salesResponse] = await Promise.all([
    getCompanies(),
    getBranches(),
    getPrincipals(),
    getSales(),
  ]);

  companyRows.value = normalizeList(unwrapResponse(companyResponse));
  branchRows.value = normalizeList(unwrapResponse(branchResponse));
  principalRows.value = normalizeList(unwrapResponse(principalResponse));
  salesRows.value = normalizeList(unwrapResponse(salesResponse));

  if (!dailyFilters.branchId && fallbackBranchId.value) dailyFilters.branchId = String(fallbackBranchId.value);
  syncSupervisorCompanyFromBranch(dailyFilters, 'branchId', 'companyId', branchRows.value, companyRows.value);
  if (!monthlyFilters.id_cabang && fallbackBranchId.value) monthlyFilters.id_cabang = String(fallbackBranchId.value);
  syncSupervisorCompanyFromBranch(monthlyFilters, 'id_cabang', 'id_perusahaan', branchRows.value, companyRows.value);
}

function getHistoryPeriods(year, month) {
  const periods = [];

  for (let offset = 5; offset >= 0; offset -= 1) {
    const date = new Date(year, month - 1 - offset, 1);
    periods.push({
      tahun: date.getFullYear(),
      bulan: date.getMonth() + 1,
      label: new Intl.DateTimeFormat('id-ID', { month: 'short', year: '2-digit' }).format(date),
    });
  }

  return periods;
}

async function loadDashboard() {
  loading.value = true;
  error.value = '';
  feedback.value = '';

  try {
    const dailyDate = normalizedDailyDate.value;
    const monthlyYear = normalizeDashboardYear(monthlyFilters.tahun);
    const monthlyMonth = normalizeDashboardMonth(monthlyFilters.bulan);

    // Keep the visible controls in sync with the safe request values. A
    // cleared/partially typed filter should simply mean the active period.
    dailyFilters.date = dailyDate;
    monthlyFilters.tahun = String(monthlyYear);
    monthlyFilters.bulan = String(monthlyMonth).padStart(2, '0');

    const historyPeriods = getHistoryPeriods(monthlyYear, monthlyMonth);

    // Keep successful panels visible when another endpoint is unavailable.
    const [targetResult, dailyResult, calendarResult] = await Promise.allSettled([
      getMonthlySalesTargets({
        tahun: String(monthlyYear),
        bulan: monthlyMonth,
        id_perusahaan: monthlyFilters.id_perusahaan || undefined,
        id_principal: monthlyFilters.id_principal || undefined,
        id_cabang: monthlyFilters.id_cabang || fallbackBranchId.value || undefined,
      }),
      getSupervisorSalesVisitReport({
        tanggal: dailyDate,
        id_perusahaan: dailyFilters.companyId || undefined,
        id_cabang: dailyFilters.branchId || fallbackBranchId.value || undefined,
        id_principal: dailyFilters.principalId || undefined,
        id_sales: dailyFilters.salesId || undefined,
      }),
      getSupervisorSalesCallplanCalendar({
        year: normalizedDailyDateObject.value.getFullYear(),
        month: normalizedDailyDateObject.value.getMonth() + 1,
        id_perusahaan: dailyFilters.companyId || undefined,
        id_cabang: dailyFilters.branchId || fallbackBranchId.value || undefined,
        id_principal: dailyFilters.principalId || undefined,
        id_sales: dailyFilters.salesId || undefined,
      }),
    ]);

    const panels = resolveDashboardPanels([targetResult, dailyResult, calendarResult]);
    const targetResponse = panels.responses.targets;
    const dailyResponse = panels.responses.daily;
    const calendarResponse = panels.responses.calendar;
    targetsUnavailable.value = panels.unavailable.includes('targets');

    const targetPayload = unwrapResponse(targetResponse) || {};
    targetRows.value = normalizeList(targetPayload.rows).map((row) => ({
      ...row,
      target_kunjungan: Number(row.target_kunjungan || 0),
      actual_kunjungan: Number(row.actual_kunjungan || 0),
      visit_achievement_percent: Number(row.visit_achievement_percent || 0),
      target_omset: Number(row.target_omset || 0),
      actual_omset: Number(row.actual_omset || 0),
      achievement_percent: Number(row.achievement_percent || 0),
    }));

    const dailyPayload = unwrapResponse(dailyResponse) || {};
    dailyReportRows.value = normalizeList(dailyPayload?.rows);

    const calendarPayload = unwrapResponse(calendarResponse) || {};
    calendarRows.value = normalizeList(calendarPayload?.rows);

    // The old implementation issued seven heavy target queries at the same
    // time (including the current month twice).  That saturated the legacy
    // API pool and made a successful dashboard look like a generic server
    // error.  Reuse the current response and load the five historical
    // periods one by one; a failed historical month must not hide today's
    // dashboard data.
    const historyRows = [];
    let unavailableHistoryCount = 0;
    for (const period of historyPeriods) {
      if (targetsUnavailable.value) break;
      try {
        const response = period.tahun === monthlyYear && period.bulan === monthlyMonth
          ? targetResponse
          : await getMonthlySalesTargets({
            tahun: String(period.tahun),
            bulan: period.bulan,
            id_perusahaan: monthlyFilters.id_perusahaan || undefined,
            id_principal: monthlyFilters.id_principal || undefined,
            id_cabang: monthlyFilters.id_cabang || fallbackBranchId.value || undefined,
          });
        const payload = unwrapResponse(response) || {};
        historyRows.push({
          ...period,
          rows: normalizeList(payload.rows).map((row) => ({
            ...row,
            actual_omset: Number(row.actual_omset || 0),
          })),
        });
      } catch (_) {
        unavailableHistoryCount += 1;
      }
    }
    buildingBlockHistory.value = historyRows;

    const unavailableNotes = [];
    if (panels.unavailable.length) {
      const labels = { targets: 'target MTD', daily: 'aktivitas harian', calendar: 'kalender callplan' };
      unavailableNotes.push(`Panel ${panels.unavailable.map((key) => labels[key]).join(', ')} sementara belum tersedia`);
    }
    if (unavailableHistoryCount) {
      unavailableNotes.push(`${unavailableHistoryCount} periode riwayat belum tersedia`);
    }
    const partialNote = unavailableNotes.length
      ? ` ${unavailableNotes.join(' dan ')}. Panel lain tetap ditampilkan; coba muat ulang untuk melengkapi data.`
      : '';
    feedback.value = `Dashboard supervisor memuat performa harian ${derivedDayLabel.value} dan analisa building block 6 bulan sampai ${monthOptions.find((item) => item.value === monthlyFilters.bulan)?.label || monthlyFilters.bulan} ${monthlyFilters.tahun}.${partialNote}`;
  } catch (err) {
    error.value = normalizeError(err, 'Dashboard supervisor belum bisa dimuat.');
    targetsUnavailable.value = true;
    targetRows.value = [];
    dailyReportRows.value = [];
    calendarRows.value = [];
    buildingBlockHistory.value = [];
  } finally {
    loading.value = false;
  }
}

function resetFilters() {
  monthlyFilters.tahun = String(now.getFullYear());
  monthlyFilters.bulan = String(now.getMonth() + 1).padStart(2, '0');
  monthlyFilters.id_perusahaan = '';
  monthlyFilters.id_principal = '';
  monthlyFilters.id_cabang = fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  syncSupervisorCompanyFromBranch(monthlyFilters, 'id_cabang', 'id_perusahaan', branchRows.value, companyRows.value);

  dailyFilters.branchId = fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  dailyFilters.companyId = '';
  syncSupervisorCompanyFromBranch(dailyFilters, 'branchId', 'companyId', branchRows.value, companyRows.value);
  dailyFilters.principalId = '';
  dailyFilters.salesId = '';
  dailyFilters.date = toLocalDateInputValue();
  loadDashboard();
}

watch(
  () => dailyFilters.companyId,
  (companyId) => {
    const normalizedCompanyId = String(companyId || '');

    if (resetSupervisorBranchWhenCompanyChanges(dailyFilters, 'companyId', 'branchId', branchRows.value, auth, companyRows.value)) {
      dailyFilters.salesId = '';
    }

    if (!normalizedCompanyId) {
      dailyFilters.branchId = '';
      dailyFilters.principalId = '';
    } else if (!principalOptions.value.some((item) => item.value === String(dailyFilters.principalId))) {
      dailyFilters.principalId = '';
    }
  }
);

watch(
  () => dailyFilters.branchId,
  (branchId) => {
    if (!branchId) {
      dailyFilters.salesId = '';
      return;
    }
  }
);

watch(
  () => [dailyFilters.branchId, dailyFilters.principalId],
  () => {
    if (!salesOptions.value.some((item) => item.value === String(dailyFilters.salesId))) {
      dailyFilters.salesId = '';
    }
  }
);

watch(
  () => monthlyFilters.id_perusahaan,
  (companyId) => {
    if (!companyId) {
      monthlyFilters.id_cabang = '';
      return;
    }
    resetSupervisorBranchWhenCompanyChanges(monthlyFilters, 'id_perusahaan', 'id_cabang', branchRows.value, auth, companyRows.value);
  }
);

onMounted(async () => {
  try {
    await loadReferences();
  } catch (err) {
    error.value = normalizeError(err, 'Referensi dashboard supervisor belum bisa dimuat.');
  }

  await loadDashboard();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Dashboard Aktivitas Sales"
      description="Building block dan performa kunjungan harian saya satukan dengan target omset, callplan, dan retur agar supervisor lebih mudah membaca kondisi lapangan."
    >
      <div class="flex flex-wrap items-center gap-3">
        <div class="rounded-full bg-brand-600 px-3 py-1 text-xs font-semibold text-white">{{ derivedDayLabel }}</div>
        <div class="rounded-full bg-cyan-500 px-3 py-1 text-xs font-semibold text-white">{{ derivedWeekLabel }}</div>
        <div class="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600">
          {{ new Intl.DateTimeFormat('id-ID', { dateStyle: 'long' }).format(normalizedDailyDateObject) }}
        </div>
      </div>
    </PageHeader>

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ error }}
    </section>

    <section class="panel p-6">
      <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-[1.1fr_1.1fr_1.1fr_0.9fr_120px]">
        <AppSearchSelect v-model="dailyFilters.companyId" label="Perusahaan" placeholder="Semua perusahaan" :options="companyOptions" />
        <AppSearchSelect v-model="dailyFilters.branchId" label="Cabang" placeholder="Semua cabang" :options="dailyBranchOptions" :disabled="!dailyFilters.companyId" empty-text="Pilih perusahaan terlebih dahulu." />
        <AppSearchSelect v-model="dailyFilters.principalId" label="Principal" placeholder="Semua principal" :options="principalOptions" :disabled="!dailyFilters.companyId" empty-text="Pilih perusahaan terlebih dahulu." />
        <AppSearchSelect v-model="dailyFilters.salesId" label="Salesman" placeholder="Semua sales" :options="salesOptions" empty-text="Sales belum tersedia untuk filter ini." />
        <div class="flex items-end">
          <button class="w-full rounded-2xl bg-brand-600 px-4 py-3 text-sm font-semibold text-white shadow-lg shadow-brand-600/20 hover:bg-brand-700" @click="loadDashboard">
            Cari
          </button>
        </div>
      </div>

      <div class="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <AppFormField v-model="dailyFilters.date" label="Tanggal Harian" type="date" />
        <AppFormField v-model="monthlyFilters.tahun" label="Tahun MTD" type="number" />
        <AppSearchSelect v-model="monthlyFilters.bulan" label="Bulan MTD" placeholder="Pilih bulan" :options="monthOptions" />
        <AppSearchSelect v-model="monthlyFilters.id_perusahaan" label="Perusahaan MTD" placeholder="Semua perusahaan" :options="companyOptions" />
        <AppSearchSelect v-model="monthlyFilters.id_cabang" label="Cabang MTD" placeholder="Semua cabang" :options="monthlyBranchOptions" :disabled="!monthlyFilters.id_perusahaan" empty-text="Pilih perusahaan terlebih dahulu." />
      </div>

      <div class="mt-5 flex flex-wrap gap-3">
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50" @click="resetFilters">
          Reset
        </button>
        <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700" @click="loadDashboard">
          Refresh Dashboard
        </button>
      </div>

      <div v-if="feedback" class="mt-4 rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-700">
        {{ feedback }}
      </div>
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
      <article v-for="card in dailySummaryCards" :key="card.key" :class="['panel border-t-4 p-5', card.tone]">
        <p class="text-sm font-semibold uppercase tracking-wide text-slate-500">{{ card.label }}</p>
        <p :class="['mt-3 text-2xl font-bold', card.accent]">{{ card.value }}</p>
      </article>
    </section>

    <section class="panel p-6">
      <div class="mb-6 flex items-start justify-between gap-4">
        <div>
          <h3 class="text-2xl font-bold text-brand-700">Grafik Performa Kunjungan (Harian)</h3>
          <p class="mt-1 text-sm text-slate-500">Baris kiri menampilkan breakdown hasil kunjungan. Baris kanan menampilkan total callplan. Saya rapikan agar lebih ringan dibaca walau sales-nya banyak.</p>
        </div>
        <div class="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
          {{ chartRows.length }} Sales
        </div>
      </div>

      <AppEmptyState
        v-if="!loading && !chartRows.length"
        title="Belum ada performa kunjungan"
        description="Coba ganti tanggal, cabang, principal, atau sales untuk melihat distribusi callplan harian."
      />

      <div v-else class="overflow-x-auto">
        <div class="flex min-w-[1040px] items-end gap-8 px-4 py-6">
          <div
            v-for="item in chartRows"
            :key="`${item.code}-${item.sales}`"
            class="flex w-[144px] flex-col items-center gap-4"
          >
            <div class="flex h-80 items-end gap-3">
              <div class="flex w-14 flex-col items-center justify-end gap-2">
                <div class="text-xs font-bold text-slate-700">{{ item.nc + item.nec + item.ec }}</div>
                <div class="flex w-full flex-col-reverse overflow-hidden rounded-t-2xl bg-slate-100 shadow-inner" :style="{ height: item.stackHeight }">
                  <div v-if="item.nc > 0" class="flex items-center justify-center bg-rose-500 text-[11px] font-bold text-white" :style="{ height: item.ncHeight }">{{ item.nc }}</div>
                  <div v-if="item.nec > 0" class="flex items-center justify-center bg-amber-400 text-[11px] font-bold text-white" :style="{ height: item.necHeight }">{{ item.nec }}</div>
                  <div v-if="item.ec > 0" class="flex items-center justify-center bg-emerald-500 text-[11px] font-bold text-white" :style="{ height: item.ecHeight }">{{ item.ec }}</div>
                </div>
              </div>
              <div class="flex w-14 flex-col items-center justify-end gap-2">
                <div class="text-xs font-bold text-slate-700">{{ item.cp }}</div>
                <div class="flex w-full items-center justify-center rounded-t-2xl bg-lime-700 text-sm font-bold text-white shadow-sm" :style="{ height: item.cpHeight }">
                  {{ item.cp }}
                </div>
              </div>
            </div>

            <div class="space-y-1 text-center">
              <p class="line-clamp-2 text-sm font-semibold leading-5 text-slate-800">{{ item.sales }}</p>
              <p class="text-xs text-slate-500">{{ item.code }}</p>
            </div>
          </div>
        </div>

        <div class="mt-2 flex flex-wrap items-center justify-center gap-4 text-sm text-slate-600">
          <span class="inline-flex items-center gap-2"><span class="h-3 w-8 rounded-full bg-rose-500"></span> NC</span>
          <span class="inline-flex items-center gap-2"><span class="h-3 w-8 rounded-full bg-amber-400"></span> NEC</span>
          <span class="inline-flex items-center gap-2"><span class="h-3 w-8 rounded-full bg-emerald-500"></span> EC</span>
          <span class="inline-flex items-center gap-2"><span class="h-3 w-8 rounded-full bg-lime-700"></span> CP</span>
        </div>
      </div>
    </section>

    <section class="panel p-6">
      <div class="mb-4 flex items-center justify-between gap-3">
        <div>
          <h3 class="text-2xl font-bold text-brand-700">Laporan Kunjungan Sales (Data Harian)</h3>
          <p class="mt-1 text-sm text-slate-500">Rekap cepat CP, actual call, effective call, no call, non effective call, dan persentase harian per sales.</p>
        </div>
      </div>

      <AppTable
        :rows="activityTableRows"
        :columns="activityColumns"
        :loading="loading"
        :paginated="true"
        :default-page-size="8"
        empty-message="Belum ada data harian yang bisa ditampilkan untuk filter ini."
      />
    </section>

    <section class="panel p-6">
      <div class="mb-4 flex items-center justify-between gap-3">
        <div>
          <h3 class="text-2xl font-bold text-brand-700">Analisa Building Block (History 6 Bulan)</h3>
          <p class="mt-1 text-sm text-slate-500">Saya ambil aktual omset 6 bulan terakhir dari target bulanan yang sudah ada, lalu saya bandingkan dengan MTD bulan aktif untuk memberi sinyal naik, turun, atau belum bergerak.</p>
        </div>
        <div class="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
          {{ buildingBlockRows.length }} Sales
        </div>
      </div>

      <div v-if="historyLegend.length" class="mb-4 flex flex-wrap gap-2 text-xs text-slate-500">
        <span
          v-for="item in historyLegend"
          :key="item.key"
          class="rounded-full border border-slate-200 bg-slate-50 px-3 py-1"
        >
          {{ item.label }}
        </span>
      </div>

      <AppTable
        :rows="buildingBlockRows"
        :columns="buildingBlockColumns"
        :loading="loading"
        :paginated="true"
        :default-page-size="8"
        :empty-message="targetsUnavailable ? 'Target periode aktif belum tersedia. Coba muat ulang.' : 'Belum ada data building block yang bisa ditampilkan untuk filter MTD ini.'"
      />
    </section>

    <div class="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
      <section class="panel p-6">
        <div class="mb-4 flex items-center justify-between gap-3">
          <div>
            <h3 class="text-2xl font-bold text-brand-700">Kalender Call Plan Sales</h3>
            <p class="mt-1 text-sm text-slate-500">Preview hari aktif terdekat dari kalender callplan bulan berjalan. Untuk detail penuh tinggal buka modul kalender.</p>
          </div>
          <RouterLink
            to="/supervisor-sales/callplan-calendar"
            class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          >
            Buka Kalender
          </RouterLink>
        </div>

        <AppEmptyState
          v-if="!calendarPreviewRows.length"
          title="Belum ada preview callplan"
          description="Belum ada hari aktif callplan pada filter dashboard saat ini."
        />

        <div v-else class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <article
            v-for="item in calendarPreviewRows"
            :key="item.date"
            class="rounded-3xl border border-slate-200 bg-slate-50 p-4"
          >
            <p class="text-sm font-semibold text-brand-600">
              {{ new Intl.DateTimeFormat('id-ID', { weekday: 'long', day: 'numeric', month: 'short' }).format(new Date(item.date)) }}
            </p>
            <p class="mt-3 text-3xl font-bold text-slate-950">{{ Number(item.callplan_count || 0).toLocaleString('id-ID') }}</p>
            <p class="mt-2 text-sm text-slate-500">
              CP | {{ Number(item.sales_count || 0).toLocaleString('id-ID') }} sales | {{ Number(item.customer_count || 0).toLocaleString('id-ID') }} customer
            </p>
          </article>
        </div>
      </section>

      <section class="panel p-6">
        <div class="mb-4">
          <h3 class="text-2xl font-bold text-brand-700">Panel Pendukung</h3>
          <p class="mt-1 text-sm text-slate-500">Akses cepat ke modul supervisor yang paling sering dipakai saat tindak lanjut harian.</p>
        </div>

        <div class="space-y-4">
          <RouterLink
            v-for="item in supportLinks"
            :key="item.to"
            :to="item.to"
            class="block rounded-3xl border border-slate-200 bg-slate-50 p-4 transition hover:border-brand-200 hover:bg-brand-50/40"
          >
            <h4 class="text-base font-bold text-slate-950">{{ item.title }}</h4>
            <p class="mt-1 text-sm text-slate-500">{{ item.description }}</p>
          </RouterLink>
        </div>
      </section>
    </div>
  </div>
</template>
