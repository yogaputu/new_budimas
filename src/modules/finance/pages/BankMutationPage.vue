<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies } from '@/api/master';
import { getBankMutationDetail, getBankMutations, getCompanyBankAccounts, importBankMutations } from '@/api/finance';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getLoginCompanyId, getRowBranchIds, getRowCompanyId, isSuperUser } from '@/utils/accessScope';
import { getBranchOptionsForCompany, getCompanyOptionsForScope } from '@/utils/filterScope';
import { firstLocalDayOfMonth, toLocalDateInputValue } from '@/utils/date';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const numberFormatter = new Intl.NumberFormat('id-ID');

const today = new Date();
const firstDay = toLocalDateInputValue(firstLocalDayOfMonth(today));
const currentDay = toLocalDateInputValue(today);

const filters = reactive({
  search: '',
  branchId: '',
  companyId: '',
  rekeningId: '',
  tipe: '',
  status: '',
  periodeAwal: firstDay,
  periodeAkhir: currentDay
});

const rows = ref([]);
const branches = ref([]);
const companies = ref([]);
const bankAccounts = ref([]);
const selectedRow = ref(null);
const detailOpen = ref(false);
const detail = ref(null);
const pageError = ref('');
const feedback = ref('');
const importOpen = ref(false);
const importPreviewRows = ref([]);
const importForm = reactive({
  id_perusahaan: '',
  id_rekening_perusahaan: '',
  fileName: ''
});

const loading = reactive({
  refs: false,
  list: false,
  detail: false,
  importParse: false,
  importSave: false
});

const tipeOptions = [
  { value: '', label: 'Semua Tipe' },
  { value: '1', label: 'CR / Masuk' },
  { value: '2', label: 'DB / Keluar' }
];

const statusOptions = [
  { value: '', label: 'Semua Status' },
  { value: '1', label: 'Belum Diproses' },
  { value: '2', label: 'Sudah Diproses' }
];

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(authStore.user));
const canAccessAllBranches = computed(() => isSuperUser(authStore));
const canUseLoginScope = computed(() => !canAccessAllBranches.value);

const branchOptions = computed(() =>
  getBranchOptionsForCompany(branches.value, authStore, filters.companyId)
);

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

const companyOptions = computed(() => getCompanyOptionsForScope(companies.value, authStore));

const rekeningOptions = computed(() => {
  const unique = new Map();

  rows.value.forEach((item) => {
    if (!item.id_rekening_perusahaan || unique.has(String(item.id_rekening_perusahaan))) return;
    unique.set(String(item.id_rekening_perusahaan), {
      value: String(item.id_rekening_perusahaan),
      label: `${item.nama_bank || 'Bank'} - ${item.nomor_rekening || '-'} (${item.nama_pemilik || '-'})`
    });
  });

  return Array.from(unique.values());
});

const bankAccountOptions = computed(() =>
  bankAccounts.value
    .filter((item) => !importForm.id_perusahaan || String(item.id_perusahaan || '') === String(importForm.id_perusahaan))
    .map((item) => ({
      value: String(item.id_rekening_perusahaan || item.id),
      label: `${item.nama_bank || 'Bank'} - ${item.nomor_rekening || '-'} (${item.nama_pemilik || '-'})`
    }))
);

const summary = computed(() => {
  const masuk = rows.value
    .filter((item) => Number(item.tipe) === 1)
    .reduce((acc, item) => acc + Number(item.nominal_mutasi || 0), 0);
  const keluar = rows.value
    .filter((item) => Number(item.tipe) === 2)
    .reduce((acc, item) => acc + Number(item.nominal_mutasi || 0), 0);
  const sisa = rows.value.reduce((acc, item) => acc + Number(item.sisa || 0), 0);

  return {
    total: rows.value.length,
    masuk,
    keluar,
    sisa,
    belumProses: rows.value.filter((item) => Number(item.status_mutasi) === 1).length
  };
});

const columns = [
  { key: 'kode_mutasi', label: 'Kode Mutasi' },
  { key: 'tanggal_label', label: 'Tanggal', render: (row) => formatDate(row.tanggal_mutasi) },
  { key: 'rekening_label', label: 'Rekening', render: (row) => `${row.nama_bank || '-'} - ${row.nomor_rekening || '-'}` },
  { key: 'nama_cabang', label: 'Cabang' },
  {
    key: 'tipe_label',
    label: 'Tipe',
    render: (row) => ({
      text: resolveTipeLabel(row.tipe),
      className:
        Number(row.tipe) === 1
          ? 'inline-flex rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700'
          : 'inline-flex rounded-full bg-rose-100 px-3 py-1 text-xs font-semibold text-rose-700'
    })
  },
  { key: 'nominal_label', label: 'Nominal', render: (row) => formatCurrency(row.nominal_mutasi) },
  { key: 'sisa_label', label: 'Sisa', render: (row) => formatCurrency(row.sisa) },
  {
    key: 'status_label',
    label: 'Status',
    render: (row) => ({
      text: resolveStatusLabel(row.status_mutasi),
      className:
        Number(row.status_mutasi) === 2
          ? 'inline-flex rounded-full bg-slate-200 px-3 py-1 text-xs font-semibold text-slate-700'
          : 'inline-flex rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700'
    })
  }
];

watch(
  () => filters.companyId,
  (companyId, previousCompanyId) => {
    if (String(companyId || '') === String(previousCompanyId || '')) return;
    syncBranchFromCompany();
    filters.rekeningId = '';
  }
);

watch(
  () => filters.branchId,
  () => {
    filters.rekeningId = '';
  }
);

function syncBranchFromCompany() {
  if (!filters.companyId) {
    if (canAccessAllBranches.value) filters.branchId = '';
    filters.rekeningId = '';
    return;
  }

  if (filters.branchId && !companyIdsForBranch(filters.branchId).includes(String(filters.companyId))) {
    filters.branchId = '';
    filters.rekeningId = '';
  }
}

function formatCurrency(value) {
  return `Rp ${numberFormatter.format(Number(value || 0))}`;
}

function formatDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10);
  return date.toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' });
}

function resolveTipeLabel(value) {
  return Number(value) === 2 ? 'DB / Keluar' : 'CR / Masuk';
}

function resolveStatusLabel(value) {
  return Number(value) === 2 ? 'Sudah Diproses' : 'Belum Diproses';
}

function parseCsvLine(line) {
  const result = [];
  let current = '';
  let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    const next = line[i + 1];
    if (char === '"' && quoted && next === '"') {
      current += '"';
      i += 1;
    } else if (char === '"') {
      quoted = !quoted;
    } else if (char === ',' && !quoted) {
      result.push(current.trim());
      current = '';
    } else {
      current += char;
    }
  }
  result.push(current.trim());
  return result;
}

function parseCurrencyToken(value) {
  const text = String(value || '').replace(/"/g, '').trim();
  const type = /\bDB\b/i.test(text) ? 'db' : 'cr';
  const amount = Number(text.replace(/\b(CR|DB)\b/gi, '').replace(/,/g, '').trim() || 0);
  return { type, amount };
}

function normalizeBankDate(value, periodEnd = '') {
  const text = String(value || '').trim();
  if (/^\d{2}\/\d{2}\/\d{4}$/.test(text)) return text;
  if (text.toUpperCase() === 'PEND' && periodEnd) return periodEnd;
  return '';
}

function extractPeriodEnd(lines) {
  const periodLine = lines.find((line) => line.toLowerCase().includes('periode'));
  const match = periodLine?.match(/(\d{2}\/\d{2}\/\d{4})\s*-\s*(\d{2}\/\d{2}\/\d{4})/);
  return match?.[2] || '';
}

function parseBankCsv(text) {
  const lines = String(text || '').split(/\r?\n/).filter((line) => line.trim());
  const periodEnd = extractPeriodEnd(lines);
  const headerIndex = lines.findIndex((line) => line.toLowerCase().startsWith('tanggal transaksi,keterangan,cabang,jumlah,saldo'));
  if (headerIndex < 0) throw new Error('Header CSV mutasi bank tidak ditemukan.');

  return lines.slice(headerIndex + 1)
    .map(parseCsvLine)
    .filter((cols) => cols.length >= 5 && !String(cols[0] || '').toLowerCase().includes('saldo'))
    .map((cols) => {
      const amount = parseCurrencyToken(cols[3]);
      const saldo = Number(String(cols[4] || '').replace(/,/g, '').replace(/"/g, '') || 0);
      return {
        tanggal: normalizeBankDate(cols[0], periodEnd),
        keterangan: cols[1],
        cabang: cols[2],
        jumlah: amount.amount,
        saldo,
        tipe: amount.type
      };
    })
    .filter((item) => item.tanggal && item.jumlah > 0);
}

async function loadReferences() {
  loading.refs = true;
  try {
    const [branchResponse, companyResponse, accountResponse] = await Promise.all([getBranches(), getCompanies(), getCompanyBankAccounts()]);
    branches.value = normalizeList(unwrapResponse(branchResponse));
    companies.value = normalizeList(unwrapResponse(companyResponse));
    bankAccounts.value = normalizeList(unwrapResponse(accountResponse));
    if (!filters.companyId && canUseLoginScope.value && fallbackCompanyId.value) {
      filters.companyId = String(fallbackCompanyId.value);
    }
    if (!canAccessAllBranches.value && fallbackBranchId.value) {
      filters.branchId = String(fallbackBranchId.value);
    }
    syncBranchFromCompany();
  } catch (error) {
    pageError.value = normalizeError(error, 'Referensi filter mutasi bank belum bisa dimuat.');
  } finally {
    loading.refs = false;
  }
}

function openImport() {
  importForm.id_perusahaan = filters.companyId || (canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '');
  importForm.id_rekening_perusahaan = '';
  importForm.fileName = '';
  importPreviewRows.value = [];
  pageError.value = '';
  feedback.value = '';
  importOpen.value = true;
}

async function handleImportFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  loading.importParse = true;
  pageError.value = '';
  importForm.fileName = file.name;
  try {
    const text = await file.text();
    importPreviewRows.value = parseBankCsv(text);
    if (!importPreviewRows.value.length) {
      throw new Error('Tidak ada baris mutasi valid yang bisa diimport dari CSV.');
    }
  } catch (error) {
    importPreviewRows.value = [];
    pageError.value = normalizeError(error, 'File mutasi bank belum bisa diparsing.');
  } finally {
    loading.importParse = false;
    event.target.value = '';
  }
}

async function submitImportRows() {
  if (!importForm.id_perusahaan || !importForm.id_rekening_perusahaan) {
    pageError.value = 'Pilih perusahaan dan rekening sebelum import mutasi.';
    return;
  }
  if (!importPreviewRows.value.length) {
    pageError.value = 'Upload file CSV mutasi bank terlebih dahulu.';
    return;
  }
  loading.importSave = true;
  pageError.value = '';
  feedback.value = '';
  try {
    await importBankMutations({
      id_perusahaan: importForm.id_perusahaan,
      id_rekening_perusahaan: importForm.id_rekening_perusahaan,
      data_mutasi: importPreviewRows.value
    });
    feedback.value = `Import ${importPreviewRows.value.length} transaksi bank berhasil diproses.`;
    importOpen.value = false;
    await loadRows();
  } catch (error) {
    pageError.value = normalizeError(error, 'Import mutasi bank belum berhasil.');
  } finally {
    loading.importSave = false;
  }
}

async function loadRows() {
  loading.list = true;
  pageError.value = '';
  try {
    const response = await getBankMutations({
      search: filters.search || undefined,
      id_cabang: filters.branchId || undefined,
      id_perusahaan: filters.companyId || undefined,
      id_rekening_perusahaan: filters.rekeningId || undefined,
      tipe: filters.tipe || undefined,
      status_mutasi: filters.status || undefined,
      periode_awal: filters.periodeAwal || undefined,
      periode_akhir: filters.periodeAkhir || undefined
    });

    rows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    rows.value = [];
    pageError.value = normalizeError(error, 'Daftar mutasi bank belum bisa dimuat.');
  } finally {
    loading.list = false;
  }
}

async function openDetail(row) {
  selectedRow.value = row;
  detailOpen.value = true;
  detail.value = null;
  loading.detail = true;

  try {
    const response = await getBankMutationDetail(row.id_mutasi);
    detail.value = unwrapResponse(response);
  } catch (error) {
    pageError.value = normalizeError(error, 'Detail mutasi bank belum bisa dimuat.');
  } finally {
    loading.detail = false;
  }
}

function resetFilters() {
  Object.assign(filters, {
    search: '',
    companyId: canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '',
    branchId: !canAccessAllBranches.value && fallbackBranchId.value ? String(fallbackBranchId.value) : '',
    rekeningId: '',
    tipe: '',
    status: '',
    periodeAwal: firstDay,
    periodeAkhir: currentDay
  });
  syncBranchFromCompany();
  loadRows();
}

onMounted(async () => {
  await loadReferences();
  await loadRows();
});
</script>

<template>
  <section>
    <PageHeader
      title="Setoran Non Tunai"
      description="Rekonsiliasi pembayaran transfer dengan mutasi rekening perusahaan. Pantau dana masuk, sisa mutasi, dan status pemakaiannya untuk setoran non tunai."
    >
      <div class="flex flex-wrap gap-3">
        <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 dark:border-slate-700 dark:text-slate-200" @click="openImport">
          Import CSV Bank
        </button>
        <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-semibold text-white shadow-sm hover:bg-brand-700" @click="loadRows">
          Reload
        </button>
      </div>
    </PageHeader>

    <div class="grid gap-4 md:grid-cols-5">
      <div class="panel p-5">
        <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Total Mutasi</p>
        <p class="mt-3 text-2xl font-bold text-slate-950 dark:text-white">{{ summary.total }}</p>
      </div>
      <div class="panel p-5">
        <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">CR / Masuk</p>
        <p class="mt-3 text-xl font-bold text-emerald-600">{{ formatCurrency(summary.masuk) }}</p>
      </div>
      <div class="panel p-5">
        <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">DB / Keluar</p>
        <p class="mt-3 text-xl font-bold text-rose-600">{{ formatCurrency(summary.keluar) }}</p>
      </div>
      <div class="panel p-5">
        <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Sisa Belum Pakai</p>
        <p class="mt-3 text-xl font-bold text-amber-600">{{ formatCurrency(summary.sisa) }}</p>
      </div>
      <div class="panel p-5">
        <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Belum Proses</p>
        <p class="mt-3 text-2xl font-bold text-slate-950 dark:text-white">{{ summary.belumProses }}</p>
      </div>
    </div>

    <div class="panel mt-5 p-5">
      <div class="grid gap-4 lg:grid-cols-6">
        <label class="block lg:col-span-2">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Cari Mutasi</span>
          <input
            v-model="filters.search"
            class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-brand-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
            placeholder="Kode, keterangan, bank, customer, sales"
            @keyup.enter="loadRows"
          />
        </label>

        <AppSearchSelect v-model="filters.companyId" label="Perusahaan" :options="companyOptions" :disabled="canUseLoginScope && !!fallbackCompanyId" placeholder="Pilih perusahaan" empty-text="Perusahaan belum tersedia." />
        <AppSearchSelect v-model="filters.branchId" label="Cabang" :options="branchOptions" :disabled="!filters.companyId || (!canAccessAllBranches && !!fallbackBranchId)" placeholder="Pilih cabang" empty-text="Pilih perusahaan terlebih dahulu." />
        <AppSearchSelect v-model="filters.rekeningId" label="Rekening" :options="rekeningOptions" placeholder="Semua rekening" empty-text="Rekening tampil setelah data dimuat." />

        <label class="block">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Tipe</span>
          <select
            v-model="filters.tipe"
            class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-brand-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
          >
            <option v-for="option in tipeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </label>
      </div>

      <div class="mt-4 grid gap-4 lg:grid-cols-5">
        <label class="block">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Status</span>
          <select
            v-model="filters.status"
            class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-brand-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
          >
            <option v-for="option in statusOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </label>
        <label class="block">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Periode Awal</span>
          <input
            v-model="filters.periodeAwal"
            type="date"
            class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-brand-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
          />
        </label>
        <label class="block">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Periode Akhir</span>
          <input
            v-model="filters.periodeAkhir"
            type="date"
            class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-brand-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
          />
        </label>
        <div class="flex items-end gap-3 lg:col-span-2">
          <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-semibold text-white" :disabled="loading.list" @click="loadRows">
            {{ loading.list ? 'Memuat...' : 'Terapkan Filter' }}
          </button>
          <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 dark:border-slate-700 dark:text-slate-200" @click="resetFilters">
            Reset
          </button>
        </div>
      </div>
    </div>

    <p v-if="pageError" class="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ pageError }}
    </p>
    <p v-if="feedback" class="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
      {{ feedback }}
    </p>

    <div class="mt-5">
      <AppTable
        :rows="rows"
        :columns="columns"
        :loading="loading.list || loading.refs"
        row-key="id_mutasi"
        :selected-key="selectedRow?.id_mutasi"
        clickable-rows
        empty-message="Belum ada mutasi bank sesuai filter."
        @row-click="openDetail"
      />
    </div>

    <AppModal
      :open="detailOpen"
      :title="`Detail Mutasi ${selectedRow?.kode_mutasi || ''}`"
      description="Informasi rekening, nominal, status, dan relasi transaksi."
      size="xl"
      @close="detailOpen = false"
    >
      <div v-if="loading.detail" class="py-10 text-center text-sm text-slate-500">Memuat detail...</div>
      <div v-else class="grid gap-4 md:grid-cols-2">
        <div class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
          <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Rekening</p>
          <p class="mt-2 font-semibold text-slate-950 dark:text-white">{{ detail?.nama_bank || '-' }}</p>
          <p class="text-sm text-slate-500">{{ detail?.nomor_rekening || '-' }} / {{ detail?.nama_pemilik || '-' }}</p>
        </div>
        <div class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
          <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Nominal</p>
          <p class="mt-2 font-semibold text-slate-950 dark:text-white">{{ formatCurrency(detail?.nominal_mutasi) }}</p>
          <p class="text-sm text-slate-500">{{ resolveTipeLabel(detail?.tipe) }} - {{ resolveStatusLabel(detail?.status_mutasi) }}</p>
        </div>
        <div class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
          <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Organisasi</p>
          <p class="mt-2 font-semibold text-slate-950 dark:text-white">{{ detail?.nama_perusahaan || '-' }}</p>
          <p class="text-sm text-slate-500">{{ detail?.kode_cabang || '-' }} - {{ detail?.nama_cabang || '-' }}</p>
        </div>
        <div class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
          <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Relasi</p>
          <p class="mt-2 text-sm text-slate-700 dark:text-slate-200">Customer: {{ detail?.nama_customer || '-' }}</p>
          <p class="text-sm text-slate-700 dark:text-slate-200">Sales: {{ detail?.nama_sales || '-' }}</p>
          <p class="text-sm text-slate-700 dark:text-slate-200">Setoran ID: {{ detail?.id_setoran || '-' }}</p>
        </div>
        <div class="rounded-2xl border border-slate-200 p-4 md:col-span-2 dark:border-slate-700">
          <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Keterangan</p>
          <p class="mt-2 text-sm text-slate-700 dark:text-slate-200">{{ detail?.keterangan || '-' }}</p>
          <p class="mt-3 text-xs text-slate-500">Upload: {{ formatDate(detail?.tanggal_upload) }} | Sisa: {{ formatCurrency(detail?.sisa) }} | Saldo akhir: {{ formatCurrency(detail?.saldo_akhir) }}</p>
        </div>
      </div>
    </AppModal>

    <AppModal
      :open="importOpen"
      title="Import Transaksi Bank"
      description="Upload CSV mutasi rekening dari internet banking, lalu pilih rekening perusahaan tujuan."
      size="4xl"
      @close="importOpen = false"
    >
      <div class="space-y-5">
        <div class="grid gap-4 md:grid-cols-2">
          <AppSearchSelect v-model="importForm.id_perusahaan" label="Perusahaan" :options="companyOptions" placeholder="Pilih perusahaan" />
          <AppSearchSelect v-model="importForm.id_rekening_perusahaan" label="Rekening Perusahaan" :options="bankAccountOptions" :disabled="!importForm.id_perusahaan" placeholder="Pilih rekening" />
          <label class="block md:col-span-2">
            <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">File CSV Mutasi</span>
            <input type="file" accept=".csv,text/csv" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm dark:border-slate-700 dark:bg-slate-950" @change="handleImportFile" />
          </label>
        </div>

        <div class="grid gap-4 md:grid-cols-4">
          <div class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
            <p class="text-xs uppercase tracking-wide text-slate-500">File</p>
            <p class="mt-2 font-semibold">{{ importForm.fileName || '-' }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
            <p class="text-xs uppercase tracking-wide text-slate-500">Baris Valid</p>
            <p class="mt-2 font-semibold">{{ importPreviewRows.length }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
            <p class="text-xs uppercase tracking-wide text-slate-500">Total CR</p>
            <p class="mt-2 font-semibold text-emerald-700">{{ formatCurrency(importPreviewRows.filter((item) => item.tipe === 'cr').reduce((sum, item) => sum + Number(item.jumlah || 0), 0)) }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
            <p class="text-xs uppercase tracking-wide text-slate-500">Total DB</p>
            <p class="mt-2 font-semibold text-rose-700">{{ formatCurrency(importPreviewRows.filter((item) => item.tipe === 'db').reduce((sum, item) => sum + Number(item.jumlah || 0), 0)) }}</p>
          </div>
        </div>

        <div class="max-h-80 overflow-auto rounded-2xl border border-slate-200 dark:border-slate-700">
          <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
            <thead class="bg-slate-50 dark:bg-slate-900">
              <tr>
                <th class="px-4 py-3 text-left">Tanggal</th>
                <th class="px-4 py-3 text-left">Tipe</th>
                <th class="px-4 py-3 text-right">Jumlah</th>
                <th class="px-4 py-3 text-right">Saldo</th>
                <th class="px-4 py-3 text-left">Keterangan</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-800">
              <tr v-if="loading.importParse">
                <td colspan="5" class="px-4 py-8 text-center text-slate-500">Membaca file...</td>
              </tr>
              <tr v-else-if="!importPreviewRows.length">
                <td colspan="5" class="px-4 py-8 text-center text-slate-500">Belum ada preview transaksi.</td>
              </tr>
              <tr v-for="(item, index) in importPreviewRows.slice(0, 100)" v-else :key="`${item.tanggal}-${index}`">
                <td class="px-4 py-3">{{ item.tanggal }}</td>
                <td class="px-4 py-3 font-semibold" :class="item.tipe === 'cr' ? 'text-emerald-700' : 'text-rose-700'">{{ item.tipe.toUpperCase() }}</td>
                <td class="px-4 py-3 text-right">{{ formatCurrency(item.jumlah) }}</td>
                <td class="px-4 py-3 text-right">{{ formatCurrency(item.saldo) }}</td>
                <td class="px-4 py-3">{{ item.keterangan }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <template #footer>
        <div class="flex justify-end gap-3">
          <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold dark:border-slate-700" @click="importOpen = false">Tutup</button>
          <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-semibold text-white disabled:opacity-60" :disabled="loading.importSave || !importPreviewRows.length" @click="submitImportRows">
            {{ loading.importSave ? 'Mengimport...' : 'Import Transaksi' }}
          </button>
        </div>
      </template>
    </AppModal>
  </section>
</template>
