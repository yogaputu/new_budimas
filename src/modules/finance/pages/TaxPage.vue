<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { toLocalDateInputValue } from '@/utils/date';
import { getBranches, getCompanies } from '@/api/master';
import { useAuthStore } from '@/stores/auth';
import { getLoginBranchId, getRowBranchIds, getRowCompanyId, isSuperUser, scopeRowsByLoginBranch } from '@/utils/accessScope';
import {
  addTaxData,
  exportDraftTaxXml,
  getDraftTaxInvoiceDetail,
  getDraftTaxInvoices,
  getFinalTaxInvoices,
  getTaxInvoicesByFile
} from '@/api/tax';

const tabs = [
  { key: 'draft', label: 'Draft Faktur' },
  { key: 'final', label: 'Final Faktur' },
  { key: 'import', label: 'Import Pajak' }
];

const activeTab = ref('draft');
const numberFormatter = new Intl.NumberFormat('id-ID');
const authStore = useAuthStore();
const DEFAULT_PAGE_SIZE = 100;

const loading = reactive({
  draft: false,
  final: false,
  detail: false,
  export: false,
  importLookup: false,
  importSave: false
});

const filters = reactive({
  draftSearch: '',
  draftCompanyId: '',
  draftBranchId: '',
  draftPrincipal: '',
  finalSearch: '',
  finalCompanyId: '',
  finalBranchId: '',
  finalPrincipal: ''
});

const draftRows = ref([]);
const finalRows = ref([]);
const selectedDraftIds = ref([]);
const feedback = ref('');
const errorMessage = ref('');
const successToast = ref('');
let toastTimer = null;

const detailOpen = ref(false);
const detailLoading = ref(false);
const detailHeader = ref(null);
const detailItems = ref([]);

const importForm = reactive({
  rawNoFaktur: ''
});
const importRows = ref([]);
const companyRows = ref([]);
const branchRows = ref([]);
const taxPagination = reactive({
  draft: { page: 1, perPage: DEFAULT_PAGE_SIZE, total: 0, totalPages: 1 },
  final: { page: 1, perPage: DEFAULT_PAGE_SIZE, total: 0, totalPages: 1 }
});

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const canAccessAllBranches = computed(() => isSuperUser(authStore));

const branchOptions = computed(() =>
  scopeRowsByLoginBranch(normalizeList(branchRows.value), authStore).map((item) => ({
    value: String(item.id),
    label: `${item.kode || '-'} - ${item.nama || item.nama_cabang || `Cabang ${item.id}`}`
  }))
);

function companyIdsForBranch(branchId) {
  if (!branchId) return [];

  const ids = new Set();
  const branch = normalizeList(branchRows.value).find((item) => String(item.id) === String(branchId));
  const directCompanyId = getRowCompanyId(branch);
  if (directCompanyId) ids.add(String(directCompanyId));

  normalizeList(companyRows.value).forEach((item) => {
    if (getRowBranchIds(item).some((id) => String(id) === String(branchId))) {
      ids.add(String(item.id));
    }
  });

  return [...ids];
}

function buildCompanyOptions(branchId = '') {
  const allowedIds = companyIdsForBranch(branchId);
  return normalizeList(companyRows.value)
    .filter((item) => allowedIds.includes(String(item.id)))
    .map((item) => ({
      value: String(item.id),
      label: item.nama || item.nama_perusahaan || `Perusahaan ${item.id}`
    }));
}

const draftCompanyOptions = computed(() => buildCompanyOptions(filters.draftBranchId));
const finalCompanyOptions = computed(() => buildCompanyOptions(filters.finalBranchId));

const draftPrincipalOptions = computed(() =>
  Array.from(new Set(draftRows.value.map((item) => item.nama_principal).filter(Boolean))).sort()
);

const finalPrincipalOptions = computed(() =>
  Array.from(new Set(finalRows.value.map((item) => item.nama_principal).filter(Boolean))).sort()
);

const filteredDraftRows = computed(() => {
  const keyword = filters.draftSearch.trim().toLowerCase();
  return draftRows.value.filter((item) => {
    const principalMatch = !filters.draftPrincipal || item.nama_principal === filters.draftPrincipal;
    const keywordMatch =
      !keyword ||
      [item.no_faktur, item.nama_customer, item.nama_principal, item.nsfp]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(keyword));
    return principalMatch && keywordMatch;
  });
});

const filteredFinalRows = computed(() => {
  const keyword = filters.finalSearch.trim().toLowerCase();
  return finalRows.value.filter((item) => {
    const principalMatch = !filters.finalPrincipal || item.nama_principal === filters.finalPrincipal;
    const keywordMatch =
      !keyword ||
      [item.no_faktur, item.nama_customer, item.nama_principal, item.nsfp]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(keyword));
    return principalMatch && keywordMatch;
  });
});

const selectedDraftRows = computed(() =>
  filteredDraftRows.value.filter((item) => selectedDraftIds.value.includes(item.id))
);

const draftSummary = computed(() => ({
  total: taxPagination.draft.total || filteredDraftRows.value.length,
  selected: selectedDraftIds.value.length,
  totalDpp: filteredDraftRows.value.reduce((acc, item) => acc + Number(item.dpp || 0), 0),
  totalPpn: filteredDraftRows.value.reduce((acc, item) => acc + Number(item.pajak || 0), 0)
}));

const finalSummary = computed(() => ({
  total: taxPagination.final.total || filteredFinalRows.value.length,
  totalDpp: filteredFinalRows.value.reduce((acc, item) => acc + Number(item.dpp || 0), 0),
  totalPpn: filteredFinalRows.value.reduce((acc, item) => acc + Number(item.pajak || 0), 0)
}));

const importSummary = computed(() => ({
  total: importRows.value.length,
  approved: importRows.value.filter((item) => item.status_faktur_pajak === 'Approved').length,
  withNsfp: importRows.value.filter((item) => String(item.nsfp || '').trim()).length
}));

watch(filteredDraftRows, (rows) => {
  const validIds = new Set(rows.map((item) => item.id));
  selectedDraftIds.value = selectedDraftIds.value.filter((id) => validIds.has(id));
});

watch(activeTab, async (tab) => {
  if (tab === 'draft' && !draftRows.value.length) {
    await loadDraftRows();
  }
  if (tab === 'final' && !finalRows.value.length) {
    await loadFinalRows();
  }
});

watch(
  () => filters.draftBranchId,
  (branchId, previousBranchId) => {
    if (String(branchId || '') === String(previousBranchId || '')) return;
    filters.draftCompanyId = '';
    filters.draftPrincipal = '';
  }
);

watch(
  () => filters.draftCompanyId,
  (companyId) => {
    if (companyId && filters.draftBranchId && !companyIdsForBranch(filters.draftBranchId, companyId).includes(String(companyId))) {
      filters.draftCompanyId = '';
    }
    filters.draftPrincipal = '';
  }
);

watch(
  () => filters.finalBranchId,
  (branchId, previousBranchId) => {
    if (String(branchId || '') === String(previousBranchId || '')) return;
    filters.finalCompanyId = '';
    filters.finalPrincipal = '';
  }
);

watch(
  () => filters.finalCompanyId,
  (companyId) => {
    if (companyId && filters.finalBranchId && !companyIdsForBranch(filters.finalBranchId, companyId).includes(String(companyId))) {
      filters.finalCompanyId = '';
    }
    filters.finalPrincipal = '';
  }
);

watch(
  () => [activeTab.value, filters.draftBranchId, filters.draftCompanyId, filters.draftPrincipal],
  async ([tab]) => {
    if (tab !== 'draft') return;
    selectedDraftIds.value = [];
    await loadDraftRows(1);
  }
);

watch(
  () => [activeTab.value, filters.finalBranchId, filters.finalCompanyId, filters.finalPrincipal],
  async ([tab]) => {
    if (tab !== 'final') return;
    await loadFinalRows(1);
  }
);

function formatCurrency(value) {
  return `Rp ${numberFormatter.format(Number(value || 0))}`;
}

function formatDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10);
  return date.toLocaleDateString('id-ID', { day: '2-digit', month: 'long', year: 'numeric' });
}

function resolveTaxRows(response) {
  const payload = unwrapResponse(response);
  const directRows = normalizeList(payload);

  if (
    directRows.length === 1 &&
    directRows[0] &&
    typeof directRows[0] === 'object' &&
    Array.isArray(directRows[0].result)
  ) {
    return normalizeList(directRows[0].result);
  }

  if (payload && typeof payload === 'object' && Array.isArray(payload.result)) {
    return normalizeList(payload.result);
  }

  return directRows;
}

function resolveTaxMeta(response) {
  const meta = response?.data?.meta || response?.data?.data?.meta || {};
  return {
    page: Number(meta.page || 1),
    perPage: Number(meta.per_page || meta.perPage || DEFAULT_PAGE_SIZE),
    total: Number(meta.total || 0),
    totalPages: Math.max(Number(meta.total_pages || meta.totalPages || 1), 1)
  };
}

function isApprovedStatus(status) {
  return String(status || '').trim().toLowerCase() === 'approved';
}

function resolveTaxDetailHeader(payload, fallback = null) {
  if (!payload || typeof payload !== 'object') {
    return fallback;
  }

  const header = payload.filterdata;
  if (header && typeof header === 'object') {
    if (Array.isArray(header.result)) {
      return header.result[0] || fallback;
    }
    if (header.result && typeof header.result === 'object') {
      return header.result;
    }
    return header;
  }

  return fallback;
}

function clearMessage() {
  feedback.value = '';
  errorMessage.value = '';
}

function showToast(message) {
  successToast.value = message;
  if (toastTimer) {
    clearTimeout(toastTimer);
  }
  toastTimer = setTimeout(() => {
    successToast.value = '';
  }, 3200);
}

function getStatusBadge(status) {
  const value = String(status || 'Draft').toLowerCase();
  if (value.includes('approved')) {
    return 'bg-emerald-100 text-emerald-700';
  }
  if (value.includes('export')) {
    return 'bg-sky-100 text-sky-700';
  }
  if (value.includes('cancel')) {
    return 'bg-rose-100 text-rose-700';
  }
  if (value.includes('amand')) {
    return 'bg-violet-100 text-violet-700';
  }
  return 'bg-amber-100 text-amber-700';
}

function toggleDraftSelection(id) {
  if (selectedDraftIds.value.includes(id)) {
    selectedDraftIds.value = selectedDraftIds.value.filter((item) => item !== id);
    return;
  }
  selectedDraftIds.value = [...selectedDraftIds.value, id];
}

function toggleSelectAllDraft() {
  const visibleIds = filteredDraftRows.value.map((item) => item.id);
  const allSelected = visibleIds.length && visibleIds.every((id) => selectedDraftIds.value.includes(id));
  selectedDraftIds.value = allSelected ? [] : visibleIds;
}

function applyTaxMeta(type, response, fallbackLength = 0) {
  const meta = resolveTaxMeta(response);
  taxPagination[type].page = meta.page;
  taxPagination[type].perPage = meta.perPage;
  taxPagination[type].total = meta.total || fallbackLength;
  taxPagination[type].totalPages = meta.totalPages;
}

async function loadDraftRows(page = taxPagination.draft.page) {
  loading.draft = true;
  clearMessage();
  try {
    const params = { page, per_page: taxPagination.draft.perPage };
    if (filters.draftCompanyId) params.id_perusahaan = filters.draftCompanyId;
    if (filters.draftBranchId) params.id_cabang = filters.draftBranchId;
    if (filters.draftPrincipal) params.nama_principal = filters.draftPrincipal;
    if (filters.draftSearch.trim()) params.search = filters.draftSearch.trim();
    const response = await getDraftTaxInvoices(params);
    draftRows.value = resolveTaxRows(response).filter((item) => !isApprovedStatus(item.status_faktur_pajak));
    applyTaxMeta('draft', response, draftRows.value.length);
  } catch (error) {
    draftRows.value = [];
    taxPagination.draft.total = 0;
    taxPagination.draft.totalPages = 1;
    errorMessage.value = normalizeError(error, 'Draft faktur pajak belum bisa dimuat.');
  } finally {
    loading.draft = false;
  }
}

async function loadFinalRows(page = taxPagination.final.page) {
  loading.final = true;
  clearMessage();
  try {
    const params = { page, per_page: taxPagination.final.perPage };
    if (filters.finalCompanyId) params.id_perusahaan = filters.finalCompanyId;
    if (filters.finalBranchId) params.id_cabang = filters.finalBranchId;
    if (filters.finalPrincipal) params.nama_principal = filters.finalPrincipal;
    if (filters.finalSearch.trim()) params.search = filters.finalSearch.trim();
    const response = await getFinalTaxInvoices(params);
    finalRows.value = resolveTaxRows(response);
    applyTaxMeta('final', response, finalRows.value.length);
  } catch (error) {
    finalRows.value = [];
    taxPagination.final.total = 0;
    taxPagination.final.totalPages = 1;
    errorMessage.value = normalizeError(error, 'Final faktur pajak belum bisa dimuat.');
  } finally {
    loading.final = false;
  }
}

function goDraftPage(direction) {
  const nextPage = Math.min(Math.max(taxPagination.draft.page + direction, 1), taxPagination.draft.totalPages || 1);
  if (nextPage !== taxPagination.draft.page) {
    selectedDraftIds.value = [];
    loadDraftRows(nextPage);
  }
}

function goFinalPage(direction) {
  const nextPage = Math.min(Math.max(taxPagination.final.page + direction, 1), taxPagination.final.totalPages || 1);
  if (nextPage !== taxPagination.final.page) {
    loadFinalRows(nextPage);
  }
}

async function openDetail(row) {
  if (!row?.id) return;
  detailOpen.value = true;
  detailLoading.value = true;
  detailHeader.value = null;
  detailItems.value = [];
  clearMessage();

  try {
    const response = await getDraftTaxInvoiceDetail(row.id);
    const payload = unwrapResponse(response) || {};
    detailHeader.value = resolveTaxDetailHeader(payload, row);
    detailItems.value = normalizeList(payload.tabledata);
  } catch (error) {
    detailHeader.value = row;
    detailItems.value = [];
    errorMessage.value = normalizeError(error, 'Detail faktur pajak belum bisa dimuat.');
  } finally {
    detailLoading.value = false;
  }
}

async function handleExportXml() {
  if (!selectedDraftIds.value.length) {
    errorMessage.value = 'Pilih minimal satu draft faktur untuk export XML.';
    return;
  }

  loading.export = true;
  clearMessage();
  try {
    const response = await exportDraftTaxXml(selectedDraftIds.value);
    const blob = new Blob([response.data], { type: 'application/xml' });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `draft-pajak-${toLocalDateInputValue()}.xml`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
    feedback.value = `Berhasil export XML untuk ${selectedDraftIds.value.length} faktur.`;
    await loadDraftRows();
    await loadFinalRows();
    selectedDraftIds.value = [];
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Export XML draft pajak belum berhasil.');
  } finally {
    loading.export = false;
  }
}

function normalizeNoFakturInput(raw) {
  return Array.from(
    new Set(
      String(raw || '')
        .split(/[\n,;]+/)
        .map((item) => item.trim())
        .filter(Boolean)
    )
  );
}

async function lookupImportRows() {
  const noFakturList = normalizeNoFakturInput(importForm.rawNoFaktur);
  if (!noFakturList.length) {
    errorMessage.value = 'Isi minimal satu nomor faktur untuk proses import pajak.';
    return;
  }

  loading.importLookup = true;
  clearMessage();
  try {
    const response = await getTaxInvoicesByFile(noFakturList.join(','));
    importRows.value = resolveTaxRows(response).map((item) => ({
      ...item,
      nsfp: item.nsfp || '',
      dpp_csv: Number(item.dpp || 0),
      ppn_csv: Number(item.pajak || 0),
      hpp_csv: Number(item.subtotal_penjualan || 0),
      status_faktur_pajak: item.nsfp ? 'Approved' : 'Draft'
    }));
    feedback.value = `${importRows.value.length} faktur ditemukan dan siap diproses ke pajak.`;
  } catch (error) {
    importRows.value = [];
    errorMessage.value = normalizeError(error, 'Nomor faktur belum bisa dicek dari file/import.');
  } finally {
    loading.importLookup = false;
  }
}

async function submitImportRows() {
  if (!importRows.value.length) {
    errorMessage.value = 'Belum ada data faktur yang siap di-import ke pajak.';
    return;
  }

  const approvedWithoutNsfp = importRows.value.find(
    (item) => item.status_faktur_pajak === 'Approved' && !String(item.nsfp || '').trim()
  );
  if (approvedWithoutNsfp) {
    errorMessage.value = `NSFP wajib diisi untuk faktur ${approvedWithoutNsfp.no_faktur} sebelum status Approved dikirim ke pajak.`;
    return;
  }

  loading.importSave = true;
  clearMessage();
  try {
    const payload = importRows.value.map((item) => ({
      no_faktur: item.no_faktur,
      nsfp: item.nsfp || null,
      dpp: Number(item.dpp || 0),
      pajak: Number(item.pajak || 0),
      subtotal_penjualan: Number(item.subtotal_penjualan || 0),
      dpp_csv: Number(item.dpp_csv || 0),
      ppn_csv: Number(item.ppn_csv || 0),
      hpp_csv: Number(item.hpp_csv || 0),
      status_faktur_pajak: item.status_faktur_pajak,
      // Backend legacy pajak masih membaca field status_faktur pada sebagian jalur.
      status_faktur: item.status_faktur_pajak
    }));
    const response = await addTaxData(payload);
    const result = response?.data || {};
    if (result.success === false) {
      throw new Error(result.message || 'Import data pajak ditolak backend.');
    }
    const approvedNoFaktur = new Set(
      payload.filter((item) => isApprovedStatus(item.status_faktur_pajak)).map((item) => item.no_faktur)
    );
    if (approvedNoFaktur.size) {
      draftRows.value = draftRows.value.filter((item) => !approvedNoFaktur.has(item.no_faktur));
    }
    feedback.value = result.message || `Berhasil memproses ${payload.length} faktur ke modul pajak.`;
    showToast(feedback.value);
    importRows.value = [];
    importForm.rawNoFaktur = '';
    await loadDraftRows();
    await loadFinalRows();
    activeTab.value = 'final';
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Import data pajak belum berhasil diproses.');
  } finally {
    loading.importSave = false;
  }
}

async function loadReferenceOptions() {
  try {
    const [companiesResponse, branchesResponse] = await Promise.all([getCompanies(), getBranches()]);
    companyRows.value = normalizeList(unwrapResponse(companiesResponse));
    branchRows.value = normalizeList(unwrapResponse(branchesResponse));
    if (!canAccessAllBranches.value && fallbackBranchId.value) {
      filters.draftBranchId = String(fallbackBranchId.value);
      filters.finalBranchId = String(fallbackBranchId.value);
    }
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Referensi perusahaan dan cabang belum bisa dimuat.');
  }
}

onMounted(async () => {
  await loadReferenceOptions();
  await loadDraftRows();
});
</script>

<template>
  <div class="space-y-6">
    <div v-if="successToast" class="fixed right-4 top-4 z-50 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-800 shadow-lg">
      {{ successToast }}
    </div>

    <PageHeader
      title="Pajak"
      description="Kelola draft faktur pajak, final faktur pajak, export XML, dan import approval faktur dalam satu area operasional."
    />

    <section class="panel p-4">
      <div class="flex flex-wrap gap-2">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          :class="[
            'rounded-xl px-4 py-2 text-sm font-medium transition',
            activeTab === tab.key
              ? 'bg-brand-600 text-white'
              : 'border border-slate-200 bg-white text-slate-700'
          ]"
          @click="activeTab = tab.key"
        >
          {{ tab.label }}
        </button>
      </div>
    </section>

    <section v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
      {{ feedback }}
    </section>
    <section v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ errorMessage }}
    </section>

    <template v-if="activeTab === 'draft'">
      <section class="grid gap-4 md:grid-cols-4">
        <article class="panel p-5">
          <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Draft Terlihat</p>
          <p class="mt-3 text-lg font-semibold text-slate-900">{{ draftSummary.total }}</p>
        </article>
        <article class="panel p-5">
          <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Terpilih Export</p>
          <p class="mt-3 text-lg font-semibold text-brand-700">{{ draftSummary.selected }}</p>
        </article>
        <article class="panel p-5">
          <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Total DPP</p>
          <p class="mt-3 text-lg font-semibold text-slate-900">{{ formatCurrency(draftSummary.totalDpp) }}</p>
        </article>
        <article class="panel p-5">
          <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Total PPN</p>
          <p class="mt-3 text-lg font-semibold text-slate-900">{{ formatCurrency(draftSummary.totalPpn) }}</p>
        </article>
      </section>

      <section class="panel p-5">
        <div class="grid gap-4 xl:grid-cols-[1.4fr_1fr_1fr_1fr_auto_auto]">
          <div>
            <label class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Cari Faktur</label>
            <input
              v-model="filters.draftSearch"
              type="text"
              placeholder="Cari no faktur, customer, principal, atau NSFP"
              class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none"
              @keyup.enter="loadDraftRows(1)"
            />
          </div>
          <div>
            <AppSearchSelect v-model="filters.draftBranchId" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="!canAccessAllBranches && !!fallbackBranchId" />
          </div>
          <div>
            <AppSearchSelect v-model="filters.draftCompanyId" label="Perusahaan" placeholder="Pilih perusahaan" :options="draftCompanyOptions" :disabled="!filters.draftBranchId" empty-text="Pilih cabang terlebih dahulu." />
          </div>
          <div>
            <label class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Principal</label>
            <select v-model="filters.draftPrincipal" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none">
              <option value="">Semua principal</option>
              <option v-for="principal in draftPrincipalOptions" :key="principal" :value="principal">{{ principal }}</option>
            </select>
          </div>
          <button class="self-end rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700" @click="loadDraftRows(1)">
            Reload
          </button>
          <button
            class="self-end rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white disabled:opacity-50"
            :disabled="loading.export || !selectedDraftIds.length"
            @click="handleExportXml"
          >
            {{ loading.export ? 'Export...' : 'Export XML Draft' }}
          </button>
        </div>
      </section>

      <section class="panel overflow-hidden">
        <div class="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div>
            <h3 class="text-lg font-semibold text-slate-900">Draft Faktur Pajak</h3>
            <p class="mt-1 text-sm text-slate-500">Klik baris untuk melihat detail produk dan gunakan checkbox untuk menandai faktur yang akan diexport ke XML.</p>
          </div>
          <button class="rounded-xl border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700" @click="toggleSelectAllDraft">
            {{ filteredDraftRows.length && filteredDraftRows.every((item) => selectedDraftIds.includes(item.id)) ? 'Batalkan Semua' : 'Pilih Semua' }}
          </button>
        </div>
        <div class="overflow-x-auto">
          <table class="min-w-full divide-y divide-slate-200 text-sm">
            <thead class="bg-slate-50">
              <tr>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Pilih</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">No Faktur</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Customer</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Principal</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Tanggal</th>
                <th class="px-4 py-3 text-right font-medium uppercase tracking-wide text-slate-500">DPP</th>
                <th class="px-4 py-3 text-right font-medium uppercase tracking-wide text-slate-500">PPN</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Status</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 bg-white">
              <tr v-if="loading.draft">
                <td colspan="8" class="px-4 py-10 text-center text-slate-500">Memuat draft faktur pajak...</td>
              </tr>
              <tr v-else-if="!filteredDraftRows.length">
                <td colspan="8" class="px-4 py-10 text-center text-slate-500">Belum ada draft faktur pajak untuk filter ini.</td>
              </tr>
              <tr
                v-for="row in filteredDraftRows"
                v-else
                :key="row.id"
                class="cursor-pointer text-slate-700 transition hover:bg-slate-50"
                @click="openDetail(row)"
              >
                <td class="px-4 py-3 align-top" @click.stop>
                  <input :checked="selectedDraftIds.includes(row.id)" type="checkbox" @change="toggleDraftSelection(row.id)" />
                </td>
                <td class="px-4 py-3 align-top font-medium text-slate-900">{{ row.no_faktur || '-' }}</td>
                <td class="px-4 py-3 align-top">{{ row.nama_customer || '-' }}</td>
                <td class="px-4 py-3 align-top">{{ row.nama_principal || '-' }}</td>
                <td class="px-4 py-3 align-top">{{ formatDate(row.tanggal_faktur) }}</td>
                <td class="px-4 py-3 text-right align-top">{{ formatCurrency(row.dpp) }}</td>
                <td class="px-4 py-3 text-right align-top">{{ formatCurrency(row.pajak) }}</td>
                <td class="px-4 py-3 align-top">
                  <span :class="['inline-flex rounded-full px-3 py-1 text-xs font-semibold', getStatusBadge(row.status_faktur_pajak)]">
                    {{ row.status_faktur_pajak || 'Draft' }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-5 py-4 text-sm text-slate-600">
          <span>Halaman {{ taxPagination.draft.page }} dari {{ taxPagination.draft.totalPages }} • Total {{ numberFormatter.format(taxPagination.draft.total) }} faktur</span>
          <div class="flex gap-2">
            <button class="rounded-xl border border-slate-200 px-3 py-2 font-medium disabled:opacity-50" :disabled="loading.draft || taxPagination.draft.page <= 1" @click="goDraftPage(-1)">Sebelumnya</button>
            <button class="rounded-xl border border-slate-200 px-3 py-2 font-medium disabled:opacity-50" :disabled="loading.draft || taxPagination.draft.page >= taxPagination.draft.totalPages" @click="goDraftPage(1)">Berikutnya</button>
          </div>
        </div>
      </section>
    </template>

    <template v-else-if="activeTab === 'final'">
      <section class="grid gap-4 md:grid-cols-3">
        <article class="panel p-5">
          <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Final Terlihat</p>
          <p class="mt-3 text-lg font-semibold text-slate-900">{{ finalSummary.total }}</p>
        </article>
        <article class="panel p-5">
          <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Total DPP</p>
          <p class="mt-3 text-lg font-semibold text-slate-900">{{ formatCurrency(finalSummary.totalDpp) }}</p>
        </article>
        <article class="panel p-5">
          <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Total PPN</p>
          <p class="mt-3 text-lg font-semibold text-slate-900">{{ formatCurrency(finalSummary.totalPpn) }}</p>
        </article>
      </section>

      <section class="panel p-5">
        <div class="grid gap-4 xl:grid-cols-[1.4fr_1fr_1fr_1fr_auto]">
          <div>
            <label class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Cari Faktur</label>
            <input
              v-model="filters.finalSearch"
              type="text"
              placeholder="Cari no faktur, customer, principal, atau NSFP"
              class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none"
              @keyup.enter="loadFinalRows(1)"
            />
          </div>
          <div>
            <AppSearchSelect v-model="filters.finalBranchId" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="!canAccessAllBranches && !!fallbackBranchId" />
          </div>
          <div>
            <AppSearchSelect v-model="filters.finalCompanyId" label="Perusahaan" placeholder="Pilih perusahaan" :options="finalCompanyOptions" :disabled="!filters.finalBranchId" empty-text="Pilih cabang terlebih dahulu." />
          </div>
          <div>
            <label class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Principal</label>
            <select v-model="filters.finalPrincipal" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none">
              <option value="">Semua principal</option>
              <option v-for="principal in finalPrincipalOptions" :key="principal" :value="principal">{{ principal }}</option>
            </select>
          </div>
          <button class="self-end rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700" @click="loadFinalRows(1)">
            Reload
          </button>
        </div>
      </section>

      <section class="panel overflow-hidden">
        <div class="border-b border-slate-100 px-5 py-4">
          <h3 class="text-lg font-semibold text-slate-900">Final Faktur Pajak</h3>
          <p class="mt-1 text-sm text-slate-500">Klik baris untuk melihat rincian produk faktur pajak yang sudah approved/final.</p>
        </div>
        <div class="overflow-x-auto">
          <table class="min-w-full divide-y divide-slate-200 text-sm">
            <thead class="bg-slate-50">
              <tr>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">No Faktur</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">NSFP</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Customer</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Principal</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Tanggal</th>
                <th class="px-4 py-3 text-right font-medium uppercase tracking-wide text-slate-500">DPP</th>
                <th class="px-4 py-3 text-right font-medium uppercase tracking-wide text-slate-500">PPN</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Status</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 bg-white">
              <tr v-if="loading.final">
                <td colspan="8" class="px-4 py-10 text-center text-slate-500">Memuat final faktur pajak...</td>
              </tr>
              <tr v-else-if="!filteredFinalRows.length">
                <td colspan="8" class="px-4 py-10 text-center text-slate-500">Belum ada final faktur pajak untuk filter ini.</td>
              </tr>
              <tr
                v-for="row in filteredFinalRows"
                v-else
                :key="row.id"
                class="cursor-pointer text-slate-700 transition hover:bg-slate-50"
                @click="openDetail(row)"
              >
                <td class="px-4 py-3 align-top font-medium text-slate-900">{{ row.no_faktur || '-' }}</td>
                <td class="px-4 py-3 align-top">{{ row.nsfp || '-' }}</td>
                <td class="px-4 py-3 align-top">{{ row.nama_customer || '-' }}</td>
                <td class="px-4 py-3 align-top">{{ row.nama_principal || '-' }}</td>
                <td class="px-4 py-3 align-top">{{ formatDate(row.tanggal_faktur) }}</td>
                <td class="px-4 py-3 text-right align-top">{{ formatCurrency(row.dpp) }}</td>
                <td class="px-4 py-3 text-right align-top">{{ formatCurrency(row.pajak) }}</td>
                <td class="px-4 py-3 align-top">
                  <span :class="['inline-flex rounded-full px-3 py-1 text-xs font-semibold', getStatusBadge(row.status_faktur_pajak)]">
                    {{ row.status_faktur_pajak || 'Approved' }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-5 py-4 text-sm text-slate-600">
          <span>Halaman {{ taxPagination.final.page }} dari {{ taxPagination.final.totalPages }} • Total {{ numberFormatter.format(taxPagination.final.total) }} faktur</span>
          <div class="flex gap-2">
            <button class="rounded-xl border border-slate-200 px-3 py-2 font-medium disabled:opacity-50" :disabled="loading.final || taxPagination.final.page <= 1" @click="goFinalPage(-1)">Sebelumnya</button>
            <button class="rounded-xl border border-slate-200 px-3 py-2 font-medium disabled:opacity-50" :disabled="loading.final || taxPagination.final.page >= taxPagination.final.totalPages" @click="goFinalPage(1)">Berikutnya</button>
          </div>
        </div>
      </section>
    </template>

    <template v-else>
      <section class="grid gap-4 md:grid-cols-3">
        <article class="panel p-5">
          <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Baris Import</p>
          <p class="mt-3 text-lg font-semibold text-slate-900">{{ importSummary.total }}</p>
        </article>
        <article class="panel p-5">
          <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Status Approved</p>
          <p class="mt-3 text-lg font-semibold text-emerald-700">{{ importSummary.approved }}</p>
        </article>
        <article class="panel p-5">
          <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Sudah Ada NSFP</p>
          <p class="mt-3 text-lg font-semibold text-slate-900">{{ importSummary.withNsfp }}</p>
        </article>
      </section>

      <section class="panel p-5 space-y-4">
        <div>
          <label class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">No Faktur</label>
          <textarea
            v-model="importForm.rawNoFaktur"
            rows="5"
            placeholder="Tempel nomor faktur, pisahkan dengan enter atau koma."
            class="w-full rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none"
          />
        </div>
        <div class="flex flex-wrap gap-3">
          <button
            class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700"
            :disabled="loading.importLookup"
            @click="lookupImportRows"
          >
            {{ loading.importLookup ? 'Mencari Faktur...' : 'Cari Faktur' }}
          </button>
          <button
            class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white disabled:opacity-50"
            :disabled="loading.importSave || !importRows.length"
            @click="submitImportRows"
          >
            {{ loading.importSave ? 'Menyimpan...' : 'Kirim ke Pajak' }}
          </button>
        </div>
      </section>

      <section class="panel overflow-hidden">
        <div class="border-b border-slate-100 px-5 py-4">
          <h3 class="text-lg font-semibold text-slate-900">Preview Import Pajak</h3>
          <p class="mt-1 text-sm text-slate-500">Anda bisa menyesuaikan NSFP, status faktur pajak, dan nominal CSV sebelum data dikirim ke modul pajak.</p>
        </div>
        <div class="overflow-x-auto">
          <table class="min-w-[1120px] divide-y divide-slate-200 text-sm">
            <thead class="bg-slate-50">
              <tr>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">No Faktur</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Customer</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Principal</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">NSFP</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Status</th>
                <th class="px-4 py-3 text-right font-medium uppercase tracking-wide text-slate-500">DPP CSV</th>
                <th class="px-4 py-3 text-right font-medium uppercase tracking-wide text-slate-500">PPN CSV</th>
                <th class="px-4 py-3 text-right font-medium uppercase tracking-wide text-slate-500">HPP CSV</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 bg-white">
              <tr v-if="loading.importLookup">
                <td colspan="8" class="px-4 py-10 text-center text-slate-500">Memuat data faktur untuk import...</td>
              </tr>
              <tr v-else-if="!importRows.length">
                <td colspan="8" class="px-4 py-10 text-center text-slate-500">Belum ada faktur yang dipilih untuk proses import pajak.</td>
              </tr>
              <tr v-for="row in importRows" v-else :key="row.no_faktur" class="text-slate-700">
                <td class="px-4 py-3 align-top font-medium text-slate-900">{{ row.no_faktur }}</td>
                <td class="px-4 py-3 align-top">{{ row.nama_customer || '-' }}</td>
                <td class="px-4 py-3 align-top">{{ row.nama_principal || '-' }}</td>
                <td class="px-4 py-3 align-top">
                  <input v-model="row.nsfp" type="text" placeholder="Nomor seri faktur pajak" class="w-48 rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none" />
                </td>
                <td class="px-4 py-3 align-top">
                  <select v-model="row.status_faktur_pajak" class="rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none">
                    <option>Draft</option>
                    <option>Sudah Export</option>
                    <option>Approved</option>
                    <option>Canceled</option>
                    <option>Amanded</option>
                  </select>
                </td>
                <td class="px-4 py-3 align-top">
                  <input v-model.number="row.dpp_csv" type="number" min="0" class="w-32 rounded-xl border border-slate-200 px-3 py-2 text-right text-sm outline-none" />
                </td>
                <td class="px-4 py-3 align-top">
                  <input v-model.number="row.ppn_csv" type="number" min="0" class="w-32 rounded-xl border border-slate-200 px-3 py-2 text-right text-sm outline-none" />
                </td>
                <td class="px-4 py-3 align-top">
                  <input v-model.number="row.hpp_csv" type="number" min="0" class="w-32 rounded-xl border border-slate-200 px-3 py-2 text-right text-sm outline-none" />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <AppModal
      :open="detailOpen"
      title="Detail Faktur Pajak"
      description="Ringkasan header dan rincian item faktur pajak untuk keperluan review cepat."
      size="4xl"
      @close="detailOpen = false"
    >
      <div v-if="detailLoading" class="py-12 text-center text-slate-500">
        Memuat detail faktur pajak...
      </div>
      <div v-else class="space-y-6">
        <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <article class="rounded-2xl border border-slate-200 p-4">
            <p class="text-xs uppercase tracking-[0.25em] text-slate-400">No Faktur</p>
            <p class="mt-2 font-semibold text-slate-900">{{ detailHeader?.no_faktur || '-' }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 p-4">
            <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Tanggal Faktur</p>
            <p class="mt-2 font-semibold text-slate-900">{{ formatDate(detailHeader?.tanggal_faktur) }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 p-4">
            <p class="text-xs uppercase tracking-[0.25em] text-slate-400">NPWP</p>
            <p class="mt-2 font-semibold text-slate-900">{{ detailHeader?.npwp || '-' }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 p-4">
            <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Customer</p>
            <p class="mt-2 font-semibold text-slate-900">{{ detailHeader?.nama_customer || '-' }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 p-4">
            <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Kode Customer</p>
            <p class="mt-2 font-semibold text-slate-900">{{ detailHeader?.kode_customer || '-' }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 p-4">
            <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Principal</p>
            <p class="mt-2 font-semibold text-slate-900">{{ detailHeader?.nama_principal || '-' }}</p>
          </article>
        </section>

        <section class="overflow-x-auto rounded-2xl border border-slate-200">
          <table class="min-w-full divide-y divide-slate-200 text-sm">
            <thead class="bg-slate-50">
              <tr>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Kode SKU</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Produk</th>
                <th class="px-4 py-3 text-right font-medium uppercase tracking-wide text-slate-500">Qty Pieces</th>
                <th class="px-4 py-3 text-right font-medium uppercase tracking-wide text-slate-500">Harga</th>
                <th class="px-4 py-3 text-right font-medium uppercase tracking-wide text-slate-500">DPP</th>
                <th class="px-4 py-3 text-right font-medium uppercase tracking-wide text-slate-500">PPN</th>
                <th class="px-4 py-3 text-right font-medium uppercase tracking-wide text-slate-500">HPP</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 bg-white">
              <tr v-if="!detailItems.length">
                <td colspan="7" class="px-4 py-10 text-center text-slate-500">Belum ada rincian item faktur.</td>
              </tr>
              <tr v-for="item in detailItems" v-else :key="`${item.faktur_id}-${item.kode_sku}`" class="text-slate-700">
                <td class="px-4 py-3 align-top">{{ item.kode_sku || '-' }}</td>
                <td class="px-4 py-3 align-top">{{ item.nama_produk || '-' }}</td>
                <td class="px-4 py-3 text-right align-top">{{ numberFormatter.format(Number(item.jumlah_uom_1 || 0)) }}</td>
                <td class="px-4 py-3 text-right align-top">{{ formatCurrency(item.harga) }}</td>
                <td class="px-4 py-3 text-right align-top">{{ formatCurrency(item.dpp) }}</td>
                <td class="px-4 py-3 text-right align-top">{{ formatCurrency(item.pajak) }}</td>
                <td class="px-4 py-3 text-right align-top">{{ formatCurrency(item.hpp) }}</td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>
    </AppModal>
  </div>
</template>
