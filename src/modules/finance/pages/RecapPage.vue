<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { getPaymentExpenseAdjustments, getSalesPaymentRecap, submitSalesPaymentRecap } from '@/api/finance';
import { getBranches, getCompanies, getPlafons, getPrincipals, getSales } from '@/api/master';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getLoginCompanyId, getLoginSalesId, getRowBranchIds, getRowCompanyId, isSuperUser, scopeRowsByLoginBranch, scopeSalesRowsByLogin, shouldLockToLoginSales } from '@/utils/accessScope';
import { addLocalDays, toLocalDateInputValue } from '@/utils/date';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const numberFormatter = new Intl.NumberFormat('id-ID');

const today = new Date();
const defaultTo = toLocalDateInputValue(today);
const defaultFrom = toLocalDateInputValue(addLocalDays(today, -7));
const authStore = useAuthStore();
const route = useRoute();
const router = useRouter();

const form = reactive({
  branchId: '',
  companyId: '',
  tanggal: defaultTo,
  from: defaultFrom,
  to: defaultTo,
  id_sales: '',
  id_lph: '',
  nama_sales: '',
  buktiTransfer: ''
});

const tableFilter = reactive({
  keyword: '',
  status: 'all'
});

const branchRows = ref([]);
const companyRows = ref([]);
const principalRows = ref([]);
const plafonRows = ref([]);
const salesRows = ref([]);
const recapRows = ref([]);
const linkedExpenseRows = ref([]);
const linkedExpenseSummary = ref({
  total_pending: 0,
  total_pengurang_setoran_approved: 0,
  total_informatif_approved: 0
});
const loading = reactive({
  options: false,
  rows: false,
  submit: false,
  linkedExpenses: false
});
const feedback = ref('');
const errorMessage = ref('');

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(authStore.user));
const fallbackSalesId = computed(() => getLoginSalesId(authStore.user));
const canAccessAllBranches = computed(() => isSuperUser(authStore));
const shouldLockBusinessScope = computed(() => !canAccessAllBranches.value);
const canUseLoginScope = computed(() => shouldLockToLoginSales(authStore));

const branchOptions = computed(() =>
  scopeRowsByLoginBranch(branchRows.value, authStore).map((item) => ({
    value: String(item.id),
    label: `${item.kode ? `${item.kode} - ` : ''}${item.nama || item.nama_cabang || `Cabang ${item.id}`}`
  }))
);

function companyIdsForBranch(branchId) {
  if (!branchId) return [];

  const ids = new Set();
  const branch = branchRows.value.find((item) => String(item.id) === String(branchId));
  const directCompanyId = getRowCompanyId(branch);
  if (directCompanyId) ids.add(String(directCompanyId));
  if (fallbackCompanyId.value) ids.add(String(fallbackCompanyId.value));

  companyRows.value.forEach((item) => {
    if (getRowBranchIds(item).some((id) => String(id) === String(branchId))) {
      ids.add(String(item.id));
    }
  });

  if (form.companyId) ids.add(String(form.companyId));
  return [...ids];
}

const companyOptions = computed(() =>
  companyRows.value
    .filter((item) => companyIdsForBranch(form.branchId).includes(String(item.id)))
    .map((item) => ({
      value: String(item.id),
      label: item.nama || item.nama_perusahaan || `Perusahaan ${item.id}`
    }))
);

function getSalesCompanyId(item) {
  return item.id_perusahaan || item.company_id || item.perusahaan_id || '';
}

function getSalesBranchKey(item) {
  return String(item.id_cabang || item.cabang_id || item.branch_id || item.id_cabang_sales || '');
}

function getSalesPrincipalKeys(item) {
  return [
    item?.id_principal,
    item?.principal_id,
    item?.id_principal_sales,
    item?.principal_ids,
    item?.id_principal_list
  ]
    .flatMap((value) => String(value || '').split(','))
    .map((value) => value.trim())
    .filter(Boolean);
}

function getPlafonSalesKeys(item) {
  return [
    item?.id_sales,
    item?.id_user,
    item?.sales_id,
    item?.user_id
  ]
    .filter((value) => value !== null && value !== undefined && value !== '')
    .map((value) => String(value));
}

function getPlafonBranchKey(item) {
  return String(item.id_cabang || item.cabang_id || item.branch_id || '');
}

function getPlafonCompanyKey(item) {
  return String(item.id_perusahaan || item.company_id || item.perusahaan_id || item.id_company || '');
}

function getPlafonPrincipalKey(item) {
  return String(item.id_principal || item.principal_id || '');
}

function getPrincipalCompanyKey(item) {
  return String(item?.id_perusahaan || item?.company_id || item?.perusahaan_id || item?.id_company || '');
}

function principalMatchesCompany(principalId, companyId) {
  if (!principalId || !companyId) return false;
  const principal = principalRows.value.find((item) => String(item.id) === String(principalId));
  return Boolean(principal && getPrincipalCompanyKey(principal) === String(companyId));
}

function salesMatchesCompany(item, companyId) {
  if (!companyId) return true;

  const rowCompanyId = getSalesCompanyId(item);
  if (rowCompanyId) return String(rowCompanyId) === String(companyId);

  if (getSalesPrincipalKeys(item).some((id) => principalMatchesCompany(id, companyId))) {
    return true;
  }

  const salesKeys = [
    item?.id_sales,
    item?.id_user,
    item?.id
  ]
    .filter((value) => value !== null && value !== undefined && value !== '')
    .map((value) => String(value));

  return plafonRows.value.some((plafon) => {
    if (form.branchId && getPlafonBranchKey(plafon) !== String(form.branchId)) return false;
    if (!getPlafonSalesKeys(plafon).some((key) => salesKeys.includes(key))) return false;

    const plafonCompanyId = getPlafonCompanyKey(plafon);
    if (plafonCompanyId) return plafonCompanyId === String(companyId);

    return principalMatchesCompany(getPlafonPrincipalKey(plafon), companyId);
  });
}

const salesOptions = computed(() =>
  scopeSalesRowsByLogin(salesRows.value, authStore)
    .filter((item) => !form.branchId || getSalesBranchKey(item) === String(form.branchId))
    .filter((item) => salesMatchesCompany(item, form.companyId))
    .map((item) => ({
      value: String(item.id_sales || item.id),
      label: item.nama_sales || item.nama || 'Sales'
    }))
);

const selectedSales = computed(() =>
  salesRows.value.find((item) => String(item.id_sales || item.id) === String(form.id_sales))
);
const linkedLphId = computed(() => String(form.id_lph || route.query.id_lph || ''));

function isFinanceReadyForRecap(item) {
  const value = item?.siap_rekap_finance;
  return ![false, 0, '0', 'false', 'FALSE'].includes(value);
}

const blockedCanvasRows = computed(() => recapRows.value.filter((item) => !isFinanceReadyForRecap(item)));

const totals = computed(() => {
  const totalCustomer = recapRows.value.reduce((acc, item) => acc + Number(item.jumlah_setoran || 0), 0);
  const totalTunai = recapRows.value.reduce((acc, item) => acc + Number(item.tunai || 0), 0);
  const totalNonTunai = recapRows.value.reduce((acc, item) => acc + Number(item.non_tunai || 0), 0);
  const totalSubmit = totalTunai + totalNonTunai;

  return [
    { label: 'Draft Rekap', value: String(recapRows.value.length) },
    { label: 'Setoran Customer', value: formatCurrency(totalCustomer) },
    { label: 'Submit Tunai', value: formatCurrency(totalTunai) },
    { label: 'Submit Non Tunai', value: formatCurrency(totalNonTunai) },
    { label: 'Selisih Input', value: formatCurrency(totalCustomer - totalSubmit) }
  ];
});

const filteredRecapRows = computed(() => {
  const keyword = String(tableFilter.keyword || '').trim().toLowerCase();

  return recapRows.value.filter((item) => {
    const searchable = [
      item.no_faktur,
      item.id_sales_order,
      item.id_canvas_order,
      item.sumber_setoran,
      item.nama_sales,
      item.nama_customer,
      item.kode_customer
    ]
      .filter((value) => value !== null && value !== undefined)
      .join(' ')
      .toLowerCase();

    if (keyword && !searchable.includes(keyword)) return false;

    const difference = rowDifference(item);
    const hasInput = Number(item.tunai || 0) > 0 || Number(item.non_tunai || 0) > 0;

    if (tableFilter.status === 'empty') return !hasInput;
    if (tableFilter.status === 'difference') return difference !== 0;
    if (tableFilter.status === 'balanced') return hasInput && difference === 0;
    if (tableFilter.status === 'over') return difference < 0;

    return true;
  });
});

const filteredSummary = computed(() => `${numberFormatter.format(filteredRecapRows.value.length)} dari ${numberFormatter.format(recapRows.value.length)} baris`);

function formatCurrency(value) {
  return `Rp ${numberFormatter.format(Number(value || 0))}`;
}

async function loadLinkedLphExpenses({ quiet = false } = {}) {
  if (!linkedLphId.value) {
    linkedExpenseRows.value = [];
    linkedExpenseSummary.value = {
      total_pending: 0,
      total_pengurang_setoran_approved: 0,
      total_informatif_approved: 0
    };
    return;
  }
  loading.linkedExpenses = true;
  try {
    const response = await getPaymentExpenseAdjustments({ id_lph: linkedLphId.value });
    const payload = unwrapResponse(response) || {};
    linkedExpenseRows.value = normalizeList(payload.data ?? payload);
    linkedExpenseSummary.value = {
      total_pending: 0,
      total_pengurang_setoran_approved: 0,
      total_informatif_approved: 0,
      ...(payload.summary || {})
    };
  } catch (error) {
    linkedExpenseRows.value = [];
    if (!quiet) errorMessage.value = normalizeError(error, 'Penyesuaian biaya LPH belum dapat dimuat.');
  } finally {
    loading.linkedExpenses = false;
  }
}

function openPaymentLph() {
  router.push({
    name: 'finance-payments',
    query: { id_lph: linkedLphId.value || undefined }
  });
}

function openCanvasFinance() {
  router.push({
    name: 'finance-canvas-receivables',
    query: {
      id_cabang: form.branchId || undefined,
      id_perusahaan: form.companyId || undefined
    }
  });
}

function getSelectedSalesUserId() {
  return String(selectedSales.value?.id_user || selectedSales.value?.user_id || '');
}

function getSelectedSalesId() {
  return String(selectedSales.value?.id_sales || selectedSales.value?.id || form.id_sales || '');
}

async function loadSalesOptions() {
  loading.options = true;
  try {
    const [branchResponse, companyResponse, principalResponse, plafonResponse, salesResponse] = await Promise.all([
      getBranches(),
      getCompanies(),
      getPrincipals(),
      getPlafons(),
      getSales()
    ]);
    branchRows.value = normalizeList(unwrapResponse(branchResponse));
    companyRows.value = normalizeList(unwrapResponse(companyResponse));
    principalRows.value = normalizeList(unwrapResponse(principalResponse));
    plafonRows.value = normalizeList(unwrapResponse(plafonResponse));
    salesRows.value = normalizeList(unwrapResponse(salesResponse));
    if (shouldLockBusinessScope.value && fallbackBranchId.value) {
      form.branchId = String(fallbackBranchId.value);
    }
    if (shouldLockBusinessScope.value && fallbackCompanyId.value) form.companyId = String(fallbackCompanyId.value);
    if (canUseLoginScope.value && fallbackSalesId.value) form.id_sales = String(fallbackSalesId.value);
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Master sales belum bisa dimuat.');
  } finally {
    loading.options = false;
  }
}

async function loadRecap() {
  if (!form.id_sales) {
    errorMessage.value = 'Pilih sales terlebih dahulu untuk memuat draft rekap.';
    recapRows.value = [];
    return;
  }

  loading.rows = true;
  feedback.value = '';
  errorMessage.value = '';

  try {
    const response = await getSalesPaymentRecap({
      id_sales: getSelectedSalesId(),
      sales_user_id: getSelectedSalesUserId() || undefined,
      nama_sales: form.nama_sales || undefined,
      from: form.from,
      to: form.to
    });

    recapRows.value = normalizeList(unwrapResponse(response)).map((item) => ({
      ...item,
      tunai: Number(item.tunai || 0),
      non_tunai: Number(item.non_tunai || 0)
    }));
    tableFilter.keyword = '';
    tableFilter.status = 'all';
    await loadLinkedLphExpenses({ quiet: true });
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Draft rekap pembayaran sales belum bisa dimuat.');
    recapRows.value = [];
  } finally {
    loading.rows = false;
  }
}

function updateAmount(row, key, event) {
  if (!isFinanceReadyForRecap(row)) return;
  const rawValue = Number(event.target.value || 0);
  row[key] = rawValue < 0 ? 0 : rawValue;
}

function fillRow(row, mode) {
  if (!row || !isFinanceReadyForRecap(row)) return;
  const amount = Number(row.jumlah_setoran || 0);
  if (mode === 'cash') {
    row.tunai = amount;
    row.non_tunai = 0;
  } else if (mode === 'noncash') {
    row.tunai = 0;
    row.non_tunai = amount;
  } else {
    row.tunai = 0;
    row.non_tunai = 0;
  }
}

function fillAll(mode) {
  filteredRecapRows.value
    .filter((row) => isFinanceReadyForRecap(row))
    .forEach((row) => fillRow(row, mode));
}

function rowDifference(row) {
  return Number(row.jumlah_setoran || 0) - Number(row.tunai || 0) - Number(row.non_tunai || 0);
}

async function submitRecap() {
  feedback.value = '';
  errorMessage.value = '';

  const payloadRows = recapRows.value
    .filter((item) => isFinanceReadyForRecap(item))
    .map((item) => ({
      id: item.id,
      id_sales_order: item.id_sales_order,
      id_canvas_order: item.id_canvas_order,
      sumber_setoran: item.sumber_setoran,
      tunai: Number(item.tunai || 0),
      non_tunai: Number(item.non_tunai || 0)
    }))
    .filter((item) => item.tunai > 0 || item.non_tunai > 0);

  if (!form.id_sales || !form.nama_sales) {
    errorMessage.value = 'Pilih sales yang valid terlebih dahulu.';
    return;
  }

  if (!payloadRows.length) {
    errorMessage.value = 'Isi nominal tunai atau non tunai minimal pada satu baris sebelum submit rekap.';
    return;
  }

  const hasOverInput = recapRows.value
    .filter((item) => isFinanceReadyForRecap(item))
    .some((item) => rowDifference(item) < 0);
  if (hasOverInput) {
    errorMessage.value = 'Ada baris yang nominal tunai + non tunai melebihi setoran customer.';
    return;
  }

  loading.submit = true;

  try {
    const response = await submitSalesPaymentRecap({
      tanggal: form.tanggal,
      nama_sales: form.nama_sales,
      buktiTransfer: form.buktiTransfer,
      data: payloadRows
    });
    const payload = unwrapResponse(response) || {};
    feedback.value = `Rekap pembayaran sales berhasil disubmit. Draft yang sudah direkap akan hilang dari daftar ini karena dipindahkan ke data setoran finance. Total setoran dibuat: ${Number(payload.total_setoran_created || 0)}.`;
    await loadRecap();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Submit rekap pembayaran sales gagal.');
  } finally {
    loading.submit = false;
  }
}

watch(
  () => form.branchId,
  (branchId, previousBranchId) => {
    if (String(branchId || '') === String(previousBranchId || '')) return;
    form.companyId = shouldLockBusinessScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
    form.id_sales = canUseLoginScope.value && fallbackSalesId.value ? String(fallbackSalesId.value) : '';
    form.nama_sales = '';
    recapRows.value = [];
  }
);

watch(
  () => form.companyId,
  (companyId) => {
    if (companyId && form.branchId && !companyIdsForBranch(form.branchId).includes(String(companyId))) {
      form.companyId = '';
    }
    form.id_sales = canUseLoginScope.value && fallbackSalesId.value ? String(fallbackSalesId.value) : '';
    form.nama_sales = '';
    recapRows.value = [];
  }
);

watch(
  () => form.id_sales,
  (value) => {
    recapRows.value = [];
    if (!value || !selectedSales.value) {
      form.nama_sales = '';
      return;
    }

    form.nama_sales = selectedSales.value.nama_sales || selectedSales.value.nama || '';
  }
);

onMounted(async () => {
  await loadSalesOptions();
  if (route.query.id_lph) form.id_lph = String(route.query.id_lph);
  if (route.query.id_sales) form.id_sales = String(route.query.id_sales);
  await loadLinkedLphExpenses({ quiet: true });
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Rekap Pembayaran"
      description="Rekonsiliasi pembayaran customer per sales sebelum nominal diteruskan ke Setoran Tunai atau Setoran Non Tunai. Pastikan setiap baris tidak memiliki selisih."
    />

    <section class="panel p-5">
      <div class="grid min-w-0 gap-4 [grid-template-columns:repeat(auto-fit,minmax(210px,1fr))]">
        <AppSearchSelect v-model="form.branchId" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="shouldLockBusinessScope && !!fallbackBranchId" empty-text="Cabang belum tersedia." />
        <AppSearchSelect v-model="form.companyId" label="Perusahaan" placeholder="Pilih perusahaan" :options="companyOptions" :disabled="!form.branchId || (shouldLockBusinessScope && !!fallbackCompanyId)" empty-text="Pilih cabang terlebih dahulu." />
        <AppSearchSelect v-model="form.id_sales" label="Sales" placeholder="Pilih sales" :options="salesOptions" :disabled="canUseLoginScope && !!fallbackSalesId" empty-text="Sales belum tersedia." />
        <AppFormField v-model="form.tanggal" label="Tanggal Rekap" type="date" />
        <AppFormField v-model="form.from" label="Dari Tanggal" type="date" />
        <AppFormField v-model="form.to" label="Sampai Tanggal" type="date" />
        <AppFormField v-model="form.buktiTransfer" label="Bukti Transfer" placeholder="Opsional untuk setoran non tunai" />
        <button class="self-end rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700" @click="loadRecap">Muat Draft Rekap</button>
      </div>

      <section class="mt-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm text-slate-600">
        <p>Nama sales: <span class="font-semibold text-slate-900">{{ form.nama_sales || '-' }}</span></p>
        <p class="mt-1">Draft dimuat berdasarkan rentang tanggal input pembayaran sales; tanggal setoran dipakai saat submit ke finance.</p>
        <p class="mt-1">Sesudah submit, baris draft berubah menjadi <span class="font-semibold text-slate-900">sudah direkap</span>. Nilai tunai dilanjutkan sebagai setoran kas, sedangkan nilai non tunai siap dicocokkan di <span class="font-semibold text-slate-900">Setoran Non Tunai</span>.</p>
        <div v-if="blockedCanvasRows.length" class="mt-3 flex flex-wrap items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800">
          <p class="text-sm font-medium">{{ blockedCanvasRows.length }} claim Canvas tidak diproses di Rekap Pembayaran LPH. Gunakan jalur Piutang Canvas Finance agar claim, bukti penerimaan, dan finalisasi tetap diaudit tanpa membuat faktur Sales Order.</p>
          <button class="rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-xs font-semibold text-amber-900 hover:bg-amber-100" @click="openCanvasFinance">Buka Piutang Canvas Finance</button>
        </div>
      </section>
    </section>

    <section v-if="linkedLphId" class="panel p-5">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.22em] text-brand-600">Kontrol biaya LPH</p>
          <h3 class="mt-1 text-lg font-semibold text-slate-900">Penyesuaian biaya pada LPH #{{ linkedLphId }}</h3>
          <p class="mt-1 max-w-3xl text-sm text-slate-600">Rekap hanya menampilkan kontrol biaya yang tercatat. Tambah, approval, atau pembatalan biaya dilakukan dari Pembayaran Tagihan agar tetap terikat pada COA dan audit Finance.</p>
        </div>
        <div class="flex flex-wrap gap-2">
          <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" :disabled="loading.linkedExpenses" @click="loadLinkedLphExpenses()">{{ loading.linkedExpenses ? 'Memuat...' : 'Perbarui Biaya' }}</button>
          <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white" @click="openPaymentLph">Buka Pembayaran Tagihan</button>
        </div>
      </div>
      <div class="mt-4 grid gap-3 sm:grid-cols-3">
        <div class="rounded-xl border border-sky-200 bg-sky-50 px-4 py-3"><p class="text-xs font-semibold uppercase tracking-wide text-sky-700">Pengurang disetujui</p><p class="mt-1 font-semibold text-sky-900">{{ formatCurrency(linkedExpenseSummary.total_pengurang_setoran_approved) }}</p></div>
        <div class="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3"><p class="text-xs font-semibold uppercase tracking-wide text-amber-700">Menunggu approval</p><p class="mt-1 font-semibold text-amber-900">{{ formatCurrency(linkedExpenseSummary.total_pending) }}</p></div>
        <div class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3"><p class="text-xs font-semibold uppercase tracking-wide text-slate-600">Informatif disetujui</p><p class="mt-1 font-semibold text-slate-900">{{ formatCurrency(linkedExpenseSummary.total_informatif_approved) }}</p></div>
      </div>
      <p class="mt-3 text-xs leading-5 text-slate-500">Pengurang setoran mengubah angka kontrol netto setelah approval saja. Nilai sumber pembayaran Mobile Sales, nominal setoran, dan syarat finalisasi tetap tidak berubah.</p>
      <div class="mt-4 overflow-x-auto rounded-xl border border-slate-200">
        <table class="min-w-full divide-y divide-slate-200 text-sm">
          <thead class="bg-slate-50"><tr><th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Kategori / COA</th><th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Nominal</th><th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Arah</th><th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Status</th></tr></thead>
          <tbody class="divide-y divide-slate-100 bg-white">
            <tr v-if="loading.linkedExpenses"><td colspan="4" class="px-4 py-6 text-center text-slate-500">Memuat penyesuaian biaya LPH...</td></tr>
            <tr v-else-if="!linkedExpenseRows.length"><td colspan="4" class="px-4 py-6 text-center text-slate-500">Belum ada penyesuaian biaya pada LPH ini.</td></tr>
            <tr v-for="row in linkedExpenseRows" v-else :key="row.id"><td class="px-4 py-3 text-slate-700"><p class="font-medium">{{ row.kategori || '-' }}</p><p class="mt-1 text-xs text-slate-500">{{ row.nomor_akun || '-' }} · {{ row.nama_akun || '-' }}</p></td><td class="px-4 py-3 font-medium text-slate-700">{{ formatCurrency(row.nominal) }}</td><td class="px-4 py-3 text-slate-700">{{ row.impact_label || row.impact_direction || '-' }}</td><td class="px-4 py-3 text-slate-700">{{ row.status_label || row.status || '-' }}</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
      <article v-for="item in totals" :key="item.label" class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">{{ item.label }}</p>
        <p class="mt-3 text-lg font-semibold text-slate-900">{{ item.value }}</p>
      </article>
    </section>

    <section v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{{ feedback }}</section>
    <section v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ errorMessage }}</section>

    <section class="panel overflow-hidden">
      <div class="flex flex-col gap-4 border-b border-slate-200 px-5 py-4 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <h3 class="text-lg font-semibold text-slate-900">Draft Pembayaran Sales</h3>
          <p class="text-sm text-slate-500">Jumlah Bayar berasal dari input sales. Tentukan penyaluran tunai atau non tunai per baris, lalu pastikan tidak ada selisih. Claim Canvas tanpa faktur Finance hanya ditampilkan untuk review dan tidak dapat diposting sebagai Sales Order.</p>
          <p v-if="recapRows.length" class="mt-1 text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Tampil {{ filteredSummary }}</p>
        </div>
        <div class="flex flex-col gap-3 xl:items-end">
          <div class="grid gap-2 sm:grid-cols-[minmax(220px,1fr)_180px_auto]">
            <input
              v-model="tableFilter.keyword"
              type="search"
              class="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 outline-none transition placeholder:text-slate-400 focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
              placeholder="Cari no faktur, SO, sales, customer..."
            />
            <select
              v-model="tableFilter.status"
              class="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 outline-none transition focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
            >
              <option value="all">Semua status</option>
              <option value="empty">Belum diisi</option>
              <option value="difference">Masih selisih</option>
              <option value="balanced">Sudah pas</option>
              <option value="over">Lebih input</option>
            </select>
            <button class="rounded-xl border border-slate-200 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50" @click="tableFilter.keyword = ''; tableFilter.status = 'all'">
              Reset Filter
            </button>
          </div>
          <div class="flex flex-wrap gap-2">
            <button class="rounded-xl border border-slate-200 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50" :disabled="loading.rows || !filteredRecapRows.length" @click="fillAll('cash')">
              Semua Tunai
            </button>
            <button class="rounded-xl border border-slate-200 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50" :disabled="loading.rows || !filteredRecapRows.length" @click="fillAll('noncash')">
              Semua Non Tunai
            </button>
            <button class="rounded-xl border border-slate-200 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50" :disabled="loading.rows || !filteredRecapRows.length" @click="fillAll('clear')">
              Kosongkan
            </button>
            <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white" :disabled="loading.submit || loading.rows" @click="submitRecap">
              {{ loading.submit ? 'Memproses...' : 'Submit Rekap' }}
            </button>
          </div>
        </div>
      </div>

      <div class="overflow-x-auto">
        <table class="min-w-full divide-y divide-slate-200 text-sm">
          <thead class="bg-slate-50">
            <tr>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Sumber</th>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">No Faktur / Order</th>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Nama Sales Order</th>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Setoran Customer</th>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Tunai</th>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Non Tunai</th>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Selisih</th>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Aksi Cepat</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 bg-white">
            <tr v-if="loading.rows">
              <td colspan="8" class="px-4 py-10 text-center text-slate-500">Memuat draft rekap...</td>
            </tr>
            <tr v-else-if="!recapRows.length">
              <td colspan="8" class="px-4 py-10 text-center text-slate-500">Belum ada draft rekap pembayaran sales untuk sales ini.</td>
            </tr>
            <tr v-else-if="!filteredRecapRows.length">
              <td colspan="8" class="px-4 py-10 text-center text-slate-500">Tidak ada draft yang cocok dengan filter tabel.</td>
            </tr>
            <tr v-for="(row, index) in filteredRecapRows" v-else :key="row.id || row.nama_pemilik_sales_order || null || index">
              <td class="px-4 py-3 text-slate-700">
                <span class="rounded-full px-3 py-1 text-xs font-bold" :class="row.sumber_setoran === 'canvas' ? 'bg-sky-100 text-sky-700' : 'bg-emerald-100 text-emerald-700'">
                  {{ row.sumber_setoran === 'canvas' ? 'Canvas' : 'Sales Order' }}
                </span>
              </td>
              <td class="px-4 py-3 text-slate-700">
                {{ row.no_faktur || '-' }}
                <p v-if="!isFinanceReadyForRecap(row)" class="mt-1 max-w-xs text-xs font-medium text-amber-700">{{ row.alasan_rekap_diblokir }}</p>
              </td>
              <td class="px-4 py-3 text-slate-700">{{ row.nama_sales || '-' }}</td>
              <td class="px-4 py-3 text-slate-700">{{ formatCurrency(row.jumlah_setoran) }}</td>
              <td class="px-4 py-3">
                <input
                  :value="row.tunai"
                  type="number"
                  min="0"
                  class="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none transition focus:border-brand-400"
                  :disabled="!isFinanceReadyForRecap(row)"
                  :title="!isFinanceReadyForRecap(row) ? row.alasan_rekap_diblokir : ''"
                  @input="updateAmount(row, 'tunai', $event)"
                />
              </td>
              <td class="px-4 py-3">
                <input
                  :value="row.non_tunai"
                  type="number"
                  min="0"
                  class="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none transition focus:border-brand-400"
                  :disabled="!isFinanceReadyForRecap(row)"
                  :title="!isFinanceReadyForRecap(row) ? row.alasan_rekap_diblokir : ''"
                  @input="updateAmount(row, 'non_tunai', $event)"
                />
              </td>
              <td class="px-4 py-3" :class="rowDifference(row) < 0 ? 'font-semibold text-rose-700' : 'text-slate-700'">
                {{ formatCurrency(rowDifference(row)) }}
              </td>
              <td class="px-4 py-3">
                <div class="flex flex-wrap gap-2">
                  <template v-if="isFinanceReadyForRecap(row)">
                    <button class="rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50" @click="fillRow(row, 'cash')">Tunai</button>
                    <button class="rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50" @click="fillRow(row, 'noncash')">Non Tunai</button>
                    <button class="rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50" @click="fillRow(row, 'clear')">Clear</button>
                  </template>
                  <span v-else class="rounded-lg bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-800">Menunggu pemetaan piutang</span>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
