<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies } from '@/api/master';
import { getJournalDetail, getJournalList } from '@/api/finance';
import { useAuthStore } from '@/stores/auth';
import { getLoginBranchId, getRowBranchIds, getRowCompanyId, isSuperUser, scopeRowsByLoginBranch } from '@/utils/accessScope';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { firstLocalDayOfMonth, toLocalDateInputValue } from '@/utils/date';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const today = new Date();
const defaultFrom = toLocalDateInputValue(firstLocalDayOfMonth(today));
const defaultTo = toLocalDateInputValue(today);
const authStore = useAuthStore();

const filters = reactive({
  search: '',
  companyId: '',
  branchId: '',
  from: defaultFrom,
  to: defaultTo
});

const rows = ref([]);
const companies = ref([]);
const branches = ref([]);
const selectedRow = ref(null);
const selectedDetail = ref([]);
const selectedDetailMeta = ref(null);
const modalOpen = ref(false);
const loading = reactive({
  list: false,
  refs: false,
  detail: false
});
const feedback = ref('');
const pageError = ref('');
const detailError = ref('');
let detailRequestId = 0;
const journalPage = ref(1);
const journalPageSize = ref(25);

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const canAccessAllBranches = computed(() => isSuperUser(authStore));

const companyOptions = computed(() =>
  companies.value
    .filter((item) => companyIdsForBranch(filters.branchId).includes(String(item.id)))
    .map(toCompanyOption)
);

const branchOptions = computed(() =>
  scopeRowsByLoginBranch(branches.value, authStore).map((item) => ({
    value: String(item.id),
    label: `${item.kode || '-'} - ${item.nama || item.nama_cabang || 'Cabang'}`
  }))
);

const detailColumns = [
  { key: 'nama_akun', label: 'Akun' },
  { key: 'jenis_transaksi', label: 'Jenis Transaksi' },
  { key: 'keterangan', label: 'Keterangan' },
  {
    key: 'debit_label',
    label: 'Debit',
    render: (row) => formatCurrency(row.debit)
  },
  {
    key: 'kredit_label',
    label: 'Kredit',
    render: (row) => formatCurrency(row.kredit)
  }
];

const filteredRows = computed(() => {
  const query = filters.search.trim().toLowerCase();
  if (!query) return rows.value;

  return rows.value.filter((item) =>
    [
      item.id_jurnal,
      item.nama_perusahaan,
      item.nama_cabang,
      ...(Array.isArray(item.info_jurnal)
        ? item.info_jurnal.flatMap((detail) => [detail.nama_akun, detail.jenis_transaksi])
        : [])
    ]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query))
  );
});

const journalTableRows = computed(() =>
  filteredRows.value.map((row) => {
    const detailRows = resolveJournalDetailRows(row);
    const totalDebit = detailRows.reduce((total, detail) => total + Number(detail.debit || 0), 0);
    const totalKredit = detailRows.reduce((total, detail) => total + Number(detail.kredit || 0), 0);
    return {
      ...row,
      total_baris: detailRows.length,
      total_debit: row.total_debit ?? totalDebit,
      total_kredit: row.total_kredit ?? totalKredit,
      ringkasan_text: resolveJournalSummary(row)
    };
  })
);
const journalTotalPages = computed(() => Math.max(1, Math.ceil(journalTableRows.value.length / Number(journalPageSize.value || 25))));
const journalStartRow = computed(() => (journalPage.value - 1) * Number(journalPageSize.value || 25));
const journalEndRow = computed(() => Math.min(journalStartRow.value + Number(journalPageSize.value || 25), journalTableRows.value.length));
const visibleJournalRows = computed(() => journalTableRows.value.slice(journalStartRow.value, journalEndRow.value));
const journalSummary = computed(() => {
  const totalDebit = journalTableRows.value.reduce((total, row) => total + Number(row.total_debit || 0), 0);
  const totalKredit = journalTableRows.value.reduce((total, row) => total + Number(row.total_kredit || 0), 0);
  const unbalancedCount = journalTableRows.value.filter((row) => !isJournalBalanced(row)).length;

  return {
    totalDebit,
    totalKredit,
    difference: totalDebit - totalKredit,
    unbalancedCount,
    balancedCount: journalTableRows.value.length - unbalancedCount
  };
});

const detailDescriptionLines = computed(() => {
  const value = selectedDetailMeta.value?.keterangan_detail ?? selectedDetailMeta.value?.keterangan;
  return formatJournalDescription(value);
});

const selectedDetailSummary = computed(() => {
  const totalDebit = selectedDetail.value.reduce((total, row) => total + Number(row.debit || 0), 0);
  const totalKredit = selectedDetail.value.reduce((total, row) => total + Number(row.kredit || 0), 0);
  return {
    totalDebit,
    totalKredit
  };
});

function formatCurrency(value) {
  return `Rp ${new Intl.NumberFormat('id-ID').format(Number(value || 0))}`;
}

function formatDateLabel(value) {
  if (!value) return '-';
  const [year, month, day] = String(value).slice(0, 10).split('-');
  return year && month && day ? `${day}/${month}/${year}` : value;
}

function resolveJournalDetailRows(row) {
  return Array.isArray(row?.info_jurnal) ? row.info_jurnal : [];
}

function resolveJournalSummary(row) {
  const detailRows = resolveJournalDetailRows(row);
  if (!detailRows.length) return row.keterangan || '-';
  const first = detailRows[0];
  return `${first.nama_akun || '-'} / ${first.jenis_transaksi || row.jenis_transaksi || '-'}`;
}

function isJournalBalanced(row) {
  return Math.abs(Number(row?.total_debit || 0) - Number(row?.total_kredit || 0)) < 0.5;
}

function rowBalanceStatus(row) {
  return isJournalBalanced(row) ? 'Balance' : `Selisih ${formatCurrency(Number(row?.total_debit || 0) - Number(row?.total_kredit || 0))}`;
}

function resetFilters() {
  filters.search = '';
  filters.companyId = '';
  filters.branchId = canAccessAllBranches.value ? '' : String(fallbackBranchId.value || '');
  filters.from = defaultFrom;
  filters.to = defaultTo;
  journalPage.value = 1;
  loadRows();
}

function previousJournalPage() {
  journalPage.value = Math.max(1, journalPage.value - 1);
}

function nextJournalPage() {
  journalPage.value = Math.min(journalTotalPages.value, journalPage.value + 1);
}

function parseMaybeJson(value) {
  if (typeof value !== 'string') return value;
  const trimmed = value.trim();
  if (!trimmed || !['{', '['].includes(trimmed[0])) return value;
  try {
    return JSON.parse(trimmed);
  } catch {
    return value;
  }
}

function formatQtys(qtys = {}) {
  const parts = [
    ['UOM 1', qtys.uom_1],
    ['UOM 2', qtys.uom_2],
    ['UOM 3', qtys.uom_3]
  ]
    .filter(([, value]) => value !== null && value !== undefined && Number(value) !== 0)
    .map(([label, value]) => `${label}: ${value}`);

  return parts.length ? parts.join(', ') : 'Qty belum terbaca';
}

function formatJournalDescription(value) {
  const parsed = parseMaybeJson(value);
  const rows = Array.isArray(parsed?.result)
    ? parsed.result
    : Array.isArray(parsed)
      ? parsed
      : [];

  if (rows.length) {
    return rows.map((item) => {
      const name = item.nama || item.nama_produk || item.no_transaksi || item.kode || 'Detail transaksi';
      const qtyText = item.qtys ? ` (${formatQtys(item.qtys)})` : '';
      const transaksiText = item.transaksi_id ? ` - Transaksi ID: ${item.transaksi_id}` : '';
      const subtotalText = item.subtotal ? ` - ${formatCurrency(item.subtotal)}` : '';
      return `${name}${qtyText}${transaksiText}${subtotalText}`;
    });
  }

  if (parsed && typeof parsed === 'object') {
    return Object.entries(parsed).map(([key, item]) => `${key}: ${item ?? '-'}`);
  }

  return [String(parsed || '-')];
}

function toCompanyOption(item) {
  return {
    value: String(item.id),
    label: item.nama || item.nama_perusahaan || `Perusahaan ${item.id}`
  };
}

function companyIdsForBranch(branchId) {
  if (!branchId) return [];

  const ids = new Set();
  const branch = branches.value.find((item) => String(item.id) === String(branchId));
  const directCompanyId = getRowCompanyId(branch);
  if (directCompanyId) ids.add(String(directCompanyId));

  companies.value.forEach((item) => {
    if (getRowBranchIds(item).some((id) => String(id) === String(branchId))) {
      ids.add(String(item.id));
    }
  });

  return [...ids];
}

async function loadReferences() {
  loading.refs = true;
  try {
    const [companyResponse, branchResponse] = await Promise.all([getCompanies(), getBranches()]);
    companies.value = normalizeList(unwrapResponse(companyResponse));
    branches.value = normalizeList(unwrapResponse(branchResponse));
    if (!canAccessAllBranches.value && fallbackBranchId.value) {
      filters.branchId = String(fallbackBranchId.value);
    }
  } catch (error) {
    pageError.value = normalizeError(error, 'Referensi jurnal belum bisa dimuat.');
  } finally {
    loading.refs = false;
  }
}

async function loadRows() {
  loading.list = true;
  pageError.value = '';
  feedback.value = '';
  try {
    const response = await getJournalList({
      id_perusahaan: filters.companyId || undefined,
      id_cabang: filters.branchId || undefined,
      periode_awal: filters.from,
      periode_akhir: filters.to,
      'no-paginate': 'true',
      field: 'id_jurnal',
      order: 'desc'
    });

    rows.value = normalizeList(unwrapResponse(response));
    journalPage.value = 1;
    if (!rows.value.length) {
      feedback.value = 'Belum ada jurnal pada periode dan filter yang dipilih.';
    }
  } catch (error) {
    rows.value = [];
    pageError.value = normalizeError(error, 'Daftar jurnal belum bisa dimuat.');
  } finally {
    loading.list = false;
  }
}

async function openDetail(row) {
  const requestId = ++detailRequestId;
  selectedRow.value = row;
  selectedDetail.value = [];
  selectedDetailMeta.value = null;
  detailError.value = '';
  modalOpen.value = true;
  loading.detail = true;
  try {
    const response = await getJournalDetail(row.id_jurnal);
    if (requestId !== detailRequestId) return;
    const payload = unwrapResponse(response);
    const detailInfo = Array.isArray(payload?.info_jurnal)
      ? payload.info_jurnal
      : Array.isArray(response?.data?.info_jurnal)
        ? response.data.info_jurnal
        : [];

    selectedDetailMeta.value = payload && typeof payload === 'object' ? payload : response?.data || null;
    selectedDetail.value = detailInfo;
  } catch (error) {
    if (requestId !== detailRequestId) return;
    selectedDetailMeta.value = null;
    selectedDetail.value = [];
    detailError.value = normalizeError(error, 'Detail jurnal belum bisa dimuat.');
  } finally {
    if (requestId === detailRequestId) loading.detail = false;
  }
}

watch(
  () => filters.companyId,
  (value) => {
    if (!value) return;
    const allowedCompanyIds = companyIdsForBranch(filters.branchId);
    if (filters.branchId && !allowedCompanyIds.includes(String(value))) filters.companyId = '';
  }
);

watch(
  () => filters.branchId,
  (value, previousValue) => {
    if (String(value || '') === String(previousValue || '')) return;
    filters.companyId = '';
    rows.value = [];
    feedback.value = '';
    journalPage.value = 1;
  }
);

watch(
  () => [filters.search, filters.companyId, filters.from, filters.to],
  () => {
    journalPage.value = 1;
  }
);

watch(journalPageSize, () => {
  journalPage.value = 1;
});

onMounted(async () => {
  await loadReferences();
  await loadRows();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Jurnal"
      description="Pantau jurnal yang terbentuk dari modul operasional dan telusuri detail debit-kredit per transaksi accounting."
    />

    <section class="panel p-5">
      <div class="grid gap-4 xl:grid-cols-[1.5fr_1fr_1fr_0.9fr_0.9fr_auto_auto]">
        <div>
          <label class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Cari Jurnal</label>
          <input
            v-model="filters.search"
            type="text"
            placeholder="Cari ID jurnal, akun, perusahaan, atau cabang"
            class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white"
          />
        </div>
        <AppSearchSelect
          v-model="filters.branchId"
          label="Cabang"
          placeholder="Semua cabang"
          :options="branchOptions"
          :disabled="!canAccessAllBranches && !!fallbackBranchId"
          empty-text="Daftar cabang belum tersedia."
        />
        <AppSearchSelect
          v-model="filters.companyId"
          label="Perusahaan"
          placeholder="Pilih perusahaan"
          :options="companyOptions"
          :disabled="!filters.branchId"
          empty-text="Pilih cabang terlebih dahulu."
        />
        <div>
          <label class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Periode Awal</label>
          <input v-model="filters.from" type="date" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
        </div>
        <div>
          <label class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Periode Akhir</label>
          <input v-model="filters.to" type="date" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
        </div>
        <button class="self-end rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white disabled:opacity-60" :disabled="loading.list" @click="loadRows">
          Muat Jurnal
        </button>
        <button class="self-end rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200" @click="resetFilters">
          Reset
        </button>
      </div>
    </section>

    <section v-if="feedback" class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
      {{ feedback }}
    </section>
    <section v-if="pageError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ pageError }}
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <article class="rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <p class="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">Jumlah Jurnal</p>
        <p class="mt-3 text-xl font-semibold text-slate-900 dark:text-white">{{ journalTableRows.length }}</p>
        <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">{{ journalSummary.balancedCount }} balance, {{ journalSummary.unbalancedCount }} selisih</p>
      </article>
      <article class="rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <p class="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">Total Debit</p>
        <p class="mt-3 text-xl font-semibold text-emerald-700 dark:text-emerald-300">{{ formatCurrency(journalSummary.totalDebit) }}</p>
        <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">Seluruh jurnal hasil filter</p>
      </article>
      <article class="rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <p class="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">Total Kredit</p>
        <p class="mt-3 text-xl font-semibold text-rose-700 dark:text-rose-300">{{ formatCurrency(journalSummary.totalKredit) }}</p>
        <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">Seluruh jurnal hasil filter</p>
      </article>
      <article class="rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <p class="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">Selisih Debit Kredit</p>
        <p
          class="mt-3 text-xl font-semibold"
          :class="journalSummary.difference < 0 ? 'text-rose-600 dark:text-rose-300' : journalSummary.difference > 0 ? 'text-amber-600 dark:text-amber-300' : 'text-cyan-700 dark:text-cyan-300'"
        >
          {{ formatCurrency(journalSummary.difference) }}
        </p>
        <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">{{ formatDateLabel(filters.from) }} - {{ formatDateLabel(filters.to) }}</p>
      </article>
    </section>

    <section class="panel overflow-hidden">
      <div class="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3 dark:border-slate-800">
        <p class="text-sm font-semibold text-slate-500 dark:text-slate-300">
          Jurnal berdasarkan periode {{ formatDateLabel(filters.from) }} sampai {{ formatDateLabel(filters.to) }}
        </p>
        <button class="rounded-xl bg-cyan-700 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-800 disabled:opacity-60" :disabled="loading.list" @click="loadRows">
          Refresh
        </button>
      </div>

      <div class="overflow-x-auto">
        <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
          <thead class="bg-cyan-50 text-slate-700 dark:bg-slate-900 dark:text-slate-300">
            <tr>
              <th class="w-12 px-4 py-3 text-left">
                <input type="checkbox" class="h-4 w-4 rounded border-slate-300 text-brand-600" disabled />
              </th>
              <th class="px-4 py-3 text-left font-semibold">Tanggal</th>
              <th class="px-4 py-3 text-left font-semibold">ID Jurnal</th>
              <th class="px-4 py-3 text-left font-semibold">Perusahaan</th>
              <th class="px-4 py-3 text-left font-semibold">Cabang</th>
              <th class="min-w-[260px] px-4 py-3 text-left font-semibold">Ringkasan</th>
              <th class="px-4 py-3 text-right font-semibold">Debit</th>
              <th class="px-4 py-3 text-right font-semibold">Kredit</th>
              <th class="px-4 py-3 text-left font-semibold">Status</th>
              <th class="px-4 py-3 text-right font-semibold">Aksi</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 bg-white dark:divide-slate-800 dark:bg-slate-950">
            <tr v-if="loading.list">
              <td colspan="10" class="px-4 py-10 text-center text-slate-500 dark:text-slate-400">Memuat jurnal...</td>
            </tr>
            <tr v-else-if="!journalTableRows.length">
              <td colspan="10" class="px-4 py-10 text-center text-slate-500 dark:text-slate-400">Belum ada jurnal untuk periode yang dipilih.</td>
            </tr>
            <tr
              v-for="row in visibleJournalRows"
              v-else
              :key="row.id_jurnal"
              class="cursor-pointer transition hover:bg-slate-50 dark:hover:bg-slate-900/80"
              @click="openDetail(row)"
            >
              <td class="px-4 py-3 align-middle">
                <input type="checkbox" class="h-4 w-4 rounded border-slate-300 text-brand-600" @click.stop />
              </td>
              <td class="whitespace-nowrap px-4 py-3 align-middle text-slate-700 dark:text-slate-200">{{ row.tanggal || row.tgl_transaksi || '-' }}</td>
              <td class="whitespace-nowrap px-4 py-3 align-middle font-semibold text-cyan-700 dark:text-cyan-300">{{ row.id_jurnal || '-' }}</td>
              <td class="px-4 py-3 align-middle text-slate-700 dark:text-slate-200">{{ row.nama_perusahaan || '-' }}</td>
              <td class="px-4 py-3 align-middle text-slate-700 dark:text-slate-200">{{ row.nama_cabang || '-' }}</td>
              <td class="px-4 py-3 align-middle text-cyan-700 dark:text-cyan-300">{{ row.ringkasan_text }}</td>
              <td class="whitespace-nowrap px-4 py-3 text-right align-middle text-emerald-700 dark:text-emerald-300">{{ formatCurrency(row.total_debit) }}</td>
              <td class="whitespace-nowrap px-4 py-3 text-right align-middle text-rose-700 dark:text-rose-300">{{ formatCurrency(row.total_kredit) }}</td>
              <td class="whitespace-nowrap px-4 py-3 align-middle">
                <span
                  class="rounded-full px-2.5 py-1 text-xs font-semibold"
                  :class="isJournalBalanced(row) ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300' : 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300'"
                >
                  {{ rowBalanceStatus(row) }}
                </span>
              </td>
              <td class="whitespace-nowrap px-4 py-3 text-right align-middle">
                <button class="rounded-xl border border-cyan-700/30 px-3 py-1.5 text-xs font-semibold text-cyan-700 hover:bg-cyan-50 dark:text-cyan-300 dark:hover:bg-cyan-950/40" @click.stop="openDetail(row)">
                  Detail
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div
        v-if="!loading.list && journalTableRows.length"
        class="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300"
      >
        <div>
          Menampilkan
          <span class="font-semibold text-slate-900 dark:text-white">{{ journalStartRow + 1 }}</span>
          -
          <span class="font-semibold text-slate-900 dark:text-white">{{ journalEndRow }}</span>
          dari
          <span class="font-semibold text-slate-900 dark:text-white">{{ journalTableRows.length }}</span>
          jurnal
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <label class="flex items-center gap-2">
            <span>Per halaman</span>
            <select v-model.number="journalPageSize" class="rounded-xl border border-slate-200 bg-white px-2 py-1.5 text-sm outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white">
              <option :value="15">15</option>
              <option :value="25">25</option>
              <option :value="50">50</option>
              <option :value="100">100</option>
            </select>
          </label>
          <button class="rounded-xl border border-slate-200 bg-white px-3 py-1.5 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-950 dark:text-white" :disabled="journalPage <= 1" @click="previousJournalPage">Sebelumnya</button>
          <span class="px-2 text-slate-500 dark:text-slate-400">Hal {{ journalPage }} / {{ journalTotalPages }}</span>
          <button class="rounded-xl border border-slate-200 bg-white px-3 py-1.5 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-950 dark:text-white" :disabled="journalPage >= journalTotalPages" @click="nextJournalPage">Berikutnya</button>
        </div>
      </div>
    </section>

    <AppModal
      :open="modalOpen"
      :title="`Detail Jurnal ${selectedRow?.id_jurnal || ''}`"
      description="Lihat ringkasan transaksi dan baris debit-kredit yang membentuk jurnal ini."
      size="4xl"
      @close="modalOpen = false"
    >
      <div class="space-y-5">
        <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
            <p class="text-xs font-medium uppercase tracking-[0.25em] text-slate-400">ID Jurnal</p>
            <p class="mt-2 text-base font-semibold text-slate-900">{{ selectedRow?.id_jurnal || '-' }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
            <p class="text-xs font-medium uppercase tracking-[0.25em] text-slate-400">Tanggal</p>
            <p class="mt-2 text-base font-semibold text-slate-900">{{ selectedRow?.tanggal || selectedRow?.tgl_transaksi || selectedDetailMeta?.tanggal || '-' }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
            <p class="text-xs font-medium uppercase tracking-[0.25em] text-slate-400">Perusahaan</p>
            <p class="mt-2 text-base font-semibold text-slate-900">{{ selectedRow?.nama_perusahaan || '-' }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
            <p class="text-xs font-medium uppercase tracking-[0.25em] text-slate-400">Cabang</p>
            <p class="mt-2 text-base font-semibold text-slate-900">{{ selectedRow?.nama_cabang || '-' }}</p>
          </article>
        </div>

        <div class="grid gap-4 md:grid-cols-2">
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
            <p class="text-xs font-medium uppercase tracking-[0.25em] text-slate-400">Jenis Transaksi Utama</p>
            <p class="mt-2 text-base font-semibold text-slate-900">{{ selectedDetailMeta?.jenis_transaksi || '-' }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
            <p class="text-xs font-medium uppercase tracking-[0.25em] text-slate-400">Keterangan Detail</p>
            <div class="mt-2 space-y-1 text-sm font-medium text-slate-700">
              <p v-for="(line, index) in detailDescriptionLines" :key="`${line}-${index}`">
                {{ line }}
              </p>
            </div>
          </article>
        </div>

        <p v-if="detailError" role="alert" class="rounded-xl bg-rose-50 p-4 text-rose-700">{{ detailError }}</p>
        <div v-if="!detailError" class="grid gap-4 md:grid-cols-2">
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
            <p class="text-xs font-medium uppercase tracking-[0.25em] text-slate-400">Total Debit</p>
            <p class="mt-2 text-base font-semibold text-emerald-700">{{ loading.detail ? 'Memuat…' : formatCurrency(selectedDetailSummary.totalDebit) }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
            <p class="text-xs font-medium uppercase tracking-[0.25em] text-slate-400">Total Kredit</p>
            <p class="mt-2 text-base font-semibold text-rose-700">{{ loading.detail ? 'Memuat…' : formatCurrency(selectedDetailSummary.totalKredit) }}</p>
          </article>
        </div>

        <AppTable
          :columns="detailColumns"
          :rows="selectedDetail"
          :loading="loading.detail"
          :paginated="false"
          row-key="id"
          empty-message="Belum ada detail jurnal."
        />
      </div>
    </AppModal>
  </div>
</template>
