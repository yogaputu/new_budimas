<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import { createCoa, getAccountCoaList, getCoaCatalog, getCoaCategoryList, updateCoa } from '@/api/finance';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getRowCompanyId, hasMultiBusinessScope, hasSupervisorSalesScope, isSuperUser } from '@/utils/accessScope';
import { toLocalDateInputValue } from '@/utils/date';
import { getBranchOptionsForCompany } from '@/utils/filterScope';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import CoaDetailModal from '../components/CoaDetailModal.vue';

const authStore = useAuthStore();

const filters = reactive({
  search: '',
  branchId: '',
  companyId: '',
  active: '',
  mainOnly: false,
  showArchived: false,
  balanceDate: toLocalDateInputValue()
});

const form = reactive({
  id_coa: '',
  id_cabang_ids: [],
  id_perusahaan: '',
  id_kategori: '',
  nomor_akun: '',
  nama_akun: '',
  parent_id: '',
  principal_id: '',
  is_active: true
});

const rows = ref([]);
const branches = ref([]);
const companies = ref([]);
const principals = ref([]);
const categories = ref([]);
const parentCoas = ref([]);
const loading = reactive({
  list: false,
  refs: false,
  save: false
});
const modalOpen = ref(false);
const mode = ref('create');
const selectedRow = ref(null);
const detailAccount = ref(null);

function editFromDetail(row) {
  detailAccount.value = null;
  openEdit(row);
}
const feedback = ref('');
const actionError = ref('');
const pageError = ref('');
const coaPage = ref(1);
const coaPageSize = ref(25);
let syncingFormContext = false;

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const canAccessAllBranches = computed(() => isSuperUser(authStore));
const shouldLockBusinessScope = computed(() => !canAccessAllBranches.value && !hasSupervisorSalesScope(authStore.user) && !hasMultiBusinessScope(authStore.user));

const filterCompanyOptions = computed(() =>
  companies.value.map((item) => ({
    value: String(item.id),
    label: `${item.kode ? `${item.kode} - ` : ''}${item.nama || item.nama_perusahaan || `Perusahaan ${item.id}`}`
  }))
);

const branchOptions = computed(() =>
  getBranchOptionsForCompany(branches.value, authStore, filters.companyId, false, companies.value)
);

const formCompanyOptions = computed(() => filterCompanyOptions.value);

const formBranchOptions = computed(() =>
  getBranchOptionsForCompany(branches.value, authStore, form.id_perusahaan, false, companies.value)
);

const principalOptions = computed(() =>
  principals.value
    .filter((item) => !form.id_perusahaan || String(item.id_perusahaan || item.company_id || '') === String(form.id_perusahaan))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || '-'} - ${item.nama || item.nama_principal || 'Principal'}`
    }))
);

const categoryOptions = computed(() =>
  categories.value.map((item) => ({
    value: String(item.id_category),
    label: item.nama_kategori || `Kategori ${item.id_category}`
  }))
);

const parentCoaOptions = computed(() =>
  parentCoas.value
    .filter((item) => String(item.id_coa) !== String(form.id_coa || ''))
    .map((item) => ({
      value: String(item.id_coa),
      label: `${item.nomor_akun || '-'} - ${item.nama_akun || 'COA Utama'}`
    }))
);

const columns = [
  { key: 'nomor_akun', label: 'No Akun' },
  { key: 'nama_akun', label: 'Nama Akun' },
  { key: 'nama_kategori', label: 'Kategori' },
  { key: 'nama_perusahaan', label: 'Perusahaan' },
  { key: 'nama_principal', label: 'Principal' },
  { key: 'nama_parent', label: 'Parent' },
  { key: 'saldo_awal_label', label: 'Saldo Awal', render: (row) => formatCurrency(row.saldo_awal) },
  {
    key: 'status_label',
    label: 'Status',
    render: (row) => ({
      text: row.is_active ? 'Aktif' : 'Nonaktif',
      className: row.is_active
        ? 'inline-flex rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700'
        : 'inline-flex rounded-full bg-slate-200 px-3 py-1 text-xs font-semibold text-slate-600'
    })
  },
  { key: 'total_used', label: 'Dipakai' }
];

function formatCurrency(value) {
  return new Intl.NumberFormat('id-ID', {
    style: 'currency',
    currency: 'IDR',
    maximumFractionDigits: 2
  }).format(Number(value || 0));
}

const filteredRows = computed(() => {
  const query = filters.search.trim().toLowerCase();
  if (!query) return rows.value;

  return rows.value.filter((item) =>
    [
      item.nomor_akun,
      item.nama_akun,
      item.nama_kategori,
      item.nama_perusahaan,
      item.kode_perusahaan,
      item.kode_cabang_list,
      item.nama_cabang_list,
      item.nama_principal,
      item.nama_parent
    ]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query))
  );
});

const parentIdSet = computed(() => new Set(rows.value.map((item) => item.parent_id).filter(Boolean).map(String)));
const rowById = computed(() => new Map(rows.value.map((item) => [String(item.id_coa), item])));
const coaTableRows = computed(() =>
  filteredRows.value.map((item) => ({
    ...item,
    depth: resolveAccountDepth(item),
    isParent: parentIdSet.value.has(String(item.id_coa))
  }))
);
const coaTotalPages = computed(() => Math.max(1, Math.ceil(coaTableRows.value.length / Number(coaPageSize.value || 25))));
const coaStartRow = computed(() => (coaPage.value - 1) * Number(coaPageSize.value || 25));
const coaEndRow = computed(() => Math.min(coaStartRow.value + Number(coaPageSize.value || 25), coaTableRows.value.length));
const visibleCoaRows = computed(() => coaTableRows.value.slice(coaStartRow.value, coaEndRow.value));
const coaSummary = computed(() => {
  const totalDebit = coaTableRows.value.reduce((total, row) => total + Number(row.total_debit || 0), 0);
  const totalKredit = coaTableRows.value.reduce((total, row) => total + Number(row.total_kredit || 0), 0);
  const saldoAkhir = coaTableRows.value.reduce((total, row) => total + Number(row.saldo_akhir || 0), 0);

  return {
    totalDebit,
    totalKredit,
    saldoAkhir
  };
});

function resolveAccountDepth(row) {
  let depth = 0;
  let parentId = row?.parent_id;
  const visited = new Set();

  while (parentId && rowById.value.has(String(parentId)) && !visited.has(String(parentId))) {
    visited.add(String(parentId));
    depth += 1;
    parentId = rowById.value.get(String(parentId))?.parent_id;
  }

  return depth;
}

function formatBalance(value) {
  const amount = Number(value || 0);
  const formatted = new Intl.NumberFormat('id-ID', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(Math.abs(amount));
  return amount < 0 ? `( ${formatted} )` : formatted;
}

function formatDateLabel(value) {
  if (!value) return '-';
  const [year, month, day] = String(value).slice(0, 10).split('-');
  return year && month && day ? `${day}/${month}/${year}` : value;
}

function parseIdList(value) {
  if (Array.isArray(value)) return value.map((item) => String(item)).filter(Boolean);
  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function resolveUserScope(row) {
  return row.nama_principal || 'all';
}

function resolveCompanyBranchLabel(row) {
  const company = `${row.kode_perusahaan ? `${row.kode_perusahaan} - ` : ''}${row.nama_perusahaan || '-'}`;
  const branchesLabel = row.kode_cabang_list || row.nama_cabang_list || 'Semua cabang';
  return { company, branchesLabel };
}

function resolveTaxLabel(row) {
  return row.pajak || row.tax_label || '-';
}

function isLockedAccount(row) {
  return Number(row.total_used || 0) > 0;
}

function previousCoaPage() {
  coaPage.value = Math.max(1, coaPage.value - 1);
}

function nextCoaPage() {
  coaPage.value = Math.min(coaTotalPages.value, coaPage.value + 1);
}

function resetForm() {
  Object.assign(form, {
    id_coa: '',
    id_cabang_ids: [],
    id_perusahaan: '',
    id_kategori: '',
    nomor_akun: '',
    nama_akun: '',
    parent_id: '',
    principal_id: '',
    is_active: true
  });
}

function suggestChildAccountNumber(parentId) {
  if (!parentId) return form.nomor_akun;

  const parent = parentCoas.value.find((item) => String(item.id_coa) === String(parentId)) || rows.value.find((item) => String(item.id_coa) === String(parentId));
  const parentNumber = String(parent?.nomor_akun || '').trim();
  if (!parentNumber) return form.nomor_akun;

  const childPrefixPattern = new RegExp(`^${parentNumber.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}[.-](\\d+)`);
  const siblingNumbers = rows.value
    .filter((item) => String(item.parent_id || '') === String(parentId) && String(item.id_coa || '') !== String(form.id_coa || ''))
    .map((item) => String(item.nomor_akun || '').trim())
    .filter((value) => childPrefixPattern.test(value));
  const nextSequence = siblingNumbers.reduce((max, value) => {
    const number = Number(value.match(childPrefixPattern)?.[1]);
    return Number.isFinite(number) ? Math.max(max, number) : max;
  }, 0) + 1;

  return `${parentNumber}-${String(nextSequence).padStart(2, '0')}`;
}

function syncAccountNumberFromParent(force = false) {
  if (!form.parent_id) return;
  const nextNumber = suggestChildAccountNumber(form.parent_id);
  if (!nextNumber) return;
  const currentNumber = String(form.nomor_akun || '').trim();
  const parent = parentCoas.value.find((item) => String(item.id_coa) === String(form.parent_id)) || rows.value.find((item) => String(item.id_coa) === String(form.parent_id));
  const parentNumber = String(parent?.nomor_akun || '').trim();
  const alreadyChildOfParent = parentNumber && (currentNumber.startsWith(`${parentNumber}-`) || currentNumber.startsWith(`${parentNumber}.`));

  if (force || !currentNumber || !alreadyChildOfParent) {
    form.nomor_akun = nextNumber;
  } else if (parentNumber && currentNumber.startsWith(`${parentNumber}.`)) {
    form.nomor_akun = `${parentNumber}-${currentNumber.slice(parentNumber.length + 1)}`;
  }
}

function buildPayload() {
  syncAccountNumberFromParent(false);
  return {
    ...(form.id_coa ? { id_coa: form.id_coa } : {}),
    id_perusahaan: form.id_perusahaan || null,
    id_cabang_ids: form.id_cabang_ids.map((id) => Number(id)).filter(Boolean),
    id_kategori: form.id_kategori || null,
    nomor_akun: form.nomor_akun?.trim(),
    nama_akun: form.nama_akun?.trim(),
    parent_id: form.parent_id || null,
    parent_nomor_akun: parentCoas.value.find((item) => String(item.id_coa) === String(form.parent_id || ''))?.nomor_akun || null,
    principal_id: form.principal_id || null,
    is_active: Boolean(form.is_active)
  };
}

async function loadReferences() {
  loading.refs = true;
  try {
    const [branchResponse, companyResponse, principalResponse, categoryResponse] = await Promise.all([
      getBranches(),
      getCompanies(),
      getPrincipals(),
      getCoaCategoryList()
    ]);

    branches.value = normalizeList(unwrapResponse(branchResponse));
    companies.value = normalizeList(unwrapResponse(companyResponse));
    principals.value = normalizeList(unwrapResponse(principalResponse));
    categories.value = normalizeList(unwrapResponse(categoryResponse));

    if (shouldLockBusinessScope.value && fallbackBranchId.value) {
      const fallbackBranch = branches.value.find((item) => String(item.id) === String(fallbackBranchId.value));
      filters.companyId = String(getRowCompanyId(fallbackBranch) || '');
      filters.branchId = String(fallbackBranchId.value);
    }
  } catch (error) {
    pageError.value = normalizeError(error, 'Referensi COA belum bisa dimuat.');
  } finally {
    loading.refs = false;
  }
}

async function loadParentCoaOptions() {
  if (!form.id_perusahaan) {
    parentCoas.value = [];
    return;
  }

  try {
    const response = await getAccountCoaList({ id_perusahaan: form.id_perusahaan });
    parentCoas.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    actionError.value = normalizeError(error, 'Daftar parent COA belum bisa dimuat.');
    parentCoas.value = [];
  }
}

async function loadRows() {
  loading.list = true;
  pageError.value = '';

  try {
    const response = await getCoaCatalog({
      id_perusahaan: filters.companyId || undefined,
      id_cabang: filters.branchId || undefined,
      is_active: filters.showArchived ? undefined : 'true',
      is_main: filters.mainOnly ? 'true' : undefined,
      saldo_tanggal: filters.balanceDate || undefined,
      'no-paginate': 'true',
      field: 'nomor_akun',
      order: 'asc'
    });
    rows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    rows.value = [];
    pageError.value = normalizeError(error, 'Daftar COA belum bisa dimuat.');
  } finally {
    loading.list = false;
  }
}

async function openCreate() {
  mode.value = 'create';
  selectedRow.value = null;
  feedback.value = '';
  actionError.value = '';
  resetForm();
  syncingFormContext = true;
  form.id_perusahaan = String(filters.companyId || '');
  form.id_cabang_ids = filters.branchId ? [String(filters.branchId)] : [];
  await nextTick();
  syncingFormContext = false;
  modalOpen.value = true;
}

async function openEdit(row) {
  mode.value = 'edit';
  selectedRow.value = row;
  feedback.value = '';
  actionError.value = '';
  syncingFormContext = true;
  Object.assign(form, {
    id_coa: String(row.id_coa || ''),
    id_cabang_ids: parseIdList(row.id_cabang_list),
    id_perusahaan: String(row.id_perusahaan || ''),
    id_kategori: String(row.id_kategori || ''),
    nomor_akun: row.nomor_akun || '',
    nama_akun: row.nama_akun || '',
    parent_id: row.parent_id ? String(row.parent_id) : '',
    principal_id: row.principal_id ? String(row.principal_id) : '',
    is_active: Boolean(row.is_active)
  });
  await nextTick();
  syncingFormContext = false;
  await loadParentCoaOptions();
  modalOpen.value = true;
}

async function save() {
  if (!form.id_perusahaan || !form.id_kategori || !form.nomor_akun.trim() || !form.nama_akun.trim()) {
    actionError.value = 'Perusahaan, kategori, nomor akun, dan nama akun wajib diisi.';
    return;
  }

  loading.save = true;
  feedback.value = '';
  actionError.value = '';

  try {
    const payload = buildPayload();
    if (mode.value === 'create') {
      await createCoa(payload);
      feedback.value = 'COA berhasil ditambahkan.';
      resetForm();
      parentCoas.value = [];
    } else {
      await updateCoa(payload);
      feedback.value = 'COA berhasil diperbarui.';
    }

    await loadRows();
  } catch (error) {
    actionError.value = normalizeError(error, 'COA belum berhasil disimpan.');
  } finally {
    loading.save = false;
  }
}

watch(
  () => form.id_perusahaan,
  async () => {
    if (form.principal_id && !principalOptions.value.some((item) => item.value === String(form.principal_id))) {
      form.principal_id = '';
    }
    await loadParentCoaOptions();
    if (!syncingFormContext && form.parent_id && !parentCoaOptions.value.some((item) => item.value === String(form.parent_id))) {
      form.parent_id = '';
    }
  }
);

watch(
  () => form.parent_id,
  (parentId, previousParentId) => {
    if (syncingFormContext || String(parentId || '') === String(previousParentId || '')) return;
    syncAccountNumberFromParent(true);
  }
);

watch(
  () => filters.companyId,
  (companyId, previousCompanyId) => {
    if (String(companyId || '') === String(previousCompanyId || '')) return;
    filters.branchId = '';
    rows.value = [];
    coaPage.value = 1;
  }
);

watch(
  () => [filters.search, filters.mainOnly, filters.showArchived, filters.balanceDate, filters.companyId],
  () => {
    coaPage.value = 1;
  }
);

watch(coaPageSize, () => {
  coaPage.value = 1;
});

watch(
  () => form.id_perusahaan,
  (companyId, previousCompanyId) => {
    if (syncingFormContext) return;
    if (String(companyId || '') === String(previousCompanyId || '')) return;
    form.id_cabang_ids = [];
    form.principal_id = '';
    form.parent_id = '';
    parentCoas.value = [];
  }
);

onMounted(async () => {
  await loadReferences();
  await loadRows();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Chart of Account"
      description="Kelola struktur akun akuntansi sebagai fondasi jurnal, buku besar, dan proses accounting lanjutan."
    />

    <section class="panel p-5">
      <div class="grid gap-4 xl:grid-cols-[1.4fr_1fr_1fr_0.9fr_auto]">
        <div>
          <label class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Cari COA</label>
          <input
            v-model="filters.search"
            type="text"
            placeholder="Cari nomor akun, nama akun, kategori, atau principal"
            class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white"
          />
        </div>
        <AppSearchSelect
          v-model="filters.companyId"
          label="Perusahaan"
          placeholder="Pilih perusahaan"
          :options="filterCompanyOptions"
          empty-text="Perusahaan belum tersedia."
        />
        <AppSearchSelect
          v-model="filters.branchId"
          label="Cabang"
          placeholder="Pilih cabang"
          :options="branchOptions"
          :disabled="!filters.companyId || (shouldLockBusinessScope && !!fallbackBranchId)"
          empty-text="Pilih perusahaan terlebih dahulu."
        />
        <div>
          <label class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Tanggal Saldo</label>
          <input v-model="filters.balanceDate" type="date" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
        </div>
        <div class="flex items-end justify-end gap-3">
          <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700" @click="loadRows">Reload</button>
          <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white" @click="openCreate">Tambah COA</button>
        </div>
      </div>

      <div class="mt-4 flex flex-wrap items-center gap-5">
        <label class="flex items-center gap-3 text-sm text-slate-600">
          <input v-model="filters.showArchived" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-brand-600" @change="loadRows" />
          <span>Tampilkan Arsip Akun</span>
        </label>
        <label class="flex items-center gap-3 text-sm text-slate-600">
          <input v-model="filters.mainOnly" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-brand-600" @change="loadRows" />
          <span>Hanya akun induk</span>
        </label>
      </div>
    </section>

    <section v-if="pageError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ pageError }}
    </section>

    <section class="grid gap-4 md:grid-cols-3">
      <article class="rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <p class="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">Total Debit</p>
        <p class="mt-3 text-xl font-semibold text-emerald-700 dark:text-emerald-300">{{ formatCurrency(coaSummary.totalDebit) }}</p>
        <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">Seluruh akun hasil filter</p>
      </article>
      <article class="rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <p class="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">Total Kredit</p>
        <p class="mt-3 text-xl font-semibold text-rose-700 dark:text-rose-300">{{ formatCurrency(coaSummary.totalKredit) }}</p>
        <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">Seluruh akun hasil filter</p>
      </article>
      <article class="rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <p class="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">Total Saldo Akhir</p>
        <p
          class="mt-3 text-xl font-semibold"
          :class="coaSummary.saldoAkhir < 0 ? 'text-rose-600 dark:text-rose-300' : 'text-cyan-700 dark:text-cyan-300'"
        >
          {{ formatCurrency(coaSummary.saldoAkhir) }}
        </p>
        <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">Saldo tanggal {{ formatDateLabel(filters.balanceDate) }}</p>
      </article>
    </section>

    <section class="panel overflow-hidden">
      <div class="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3 dark:border-slate-800">
        <p class="text-sm font-semibold text-slate-500 dark:text-slate-300">
          Saldo di bawah berdasarkan tanggal {{ formatDateLabel(filters.balanceDate) }}, kecuali ada pernyataan lain
        </p>
        <div class="flex overflow-hidden rounded-xl border border-cyan-900/30 shadow-sm">
          <button class="bg-cyan-700 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-800" @click="openCreate">
            Tindakan
          </button>
          <button class="border-l border-cyan-900/30 bg-cyan-800 px-3 py-2 text-sm font-semibold text-white hover:bg-cyan-900" @click="loadRows">
            Menu
          </button>
        </div>
      </div>

      <div class="overflow-x-auto">
        <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
          <thead class="bg-cyan-50 text-slate-700 dark:bg-slate-900 dark:text-slate-300">
            <tr>
              <th class="w-12 px-4 py-3 text-left">
                <input type="checkbox" class="h-4 w-4 rounded border-slate-300 text-brand-600" disabled />
              </th>
              <th class="px-4 py-3 text-left font-semibold">Kunci</th>
              <th class="px-4 py-3 text-left font-semibold">Kode Akun</th>
              <th class="min-w-[280px] px-4 py-3 text-left font-semibold">Nama Akun</th>
              <th class="px-4 py-3 text-left font-semibold">Kategori Akun</th>
              <th class="min-w-[220px] px-4 py-3 text-left font-semibold">Perusahaan / Cabang</th>
              <th class="px-4 py-3 text-left font-semibold">Pengguna</th>
              <th class="px-4 py-3 text-left font-semibold">Pajak</th>
              <th class="px-4 py-3 text-right font-semibold">Saldo (dalam IDR)</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 bg-white dark:divide-slate-800 dark:bg-slate-950">
            <tr v-if="loading.list">
              <td colspan="9" class="px-4 py-10 text-center text-slate-500 dark:text-slate-400">Memuat daftar akun...</td>
            </tr>
            <tr v-else-if="!coaTableRows.length">
              <td colspan="9" class="px-4 py-10 text-center text-slate-500 dark:text-slate-400">Belum ada COA yang bisa ditampilkan.</td>
            </tr>
            <tr
              v-for="row in visibleCoaRows"
              v-else
              :key="row.id_coa"
              class="cursor-pointer transition hover:bg-slate-50 dark:hover:bg-slate-900/80"
              :class="{ 'bg-slate-50/80 dark:bg-slate-900/50': !row.is_active }"
              @click="detailAccount = row"
            >
              <td class="px-4 py-3 align-middle">
                <input type="checkbox" class="h-4 w-4 rounded border-slate-300 text-brand-600" :checked="!row.is_active" @click.stop />
              </td>
              <td class="px-4 py-3 align-middle text-slate-600 dark:text-slate-300">
                <span v-if="isLockedAccount(row)" class="inline-flex h-6 min-w-6 items-center justify-center rounded-full bg-slate-100 px-2 text-xs font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-200">Lock</span>
                <span v-else>-</span>
              </td>
              <td class="whitespace-nowrap px-4 py-3 align-middle text-slate-700 dark:text-slate-200">{{ row.nomor_akun || '-' }}</td>
              <td class="px-4 py-3 align-middle">
                <button
                  type="button"
                  class="font-medium text-cyan-700 dark:text-cyan-300"
                  :style="{ paddingLeft: `${row.depth * 28}px` }"
                  @click.stop="detailAccount = row"
                >
                  {{ row.nama_akun || '-' }}
                </button>
              </td>
              <td class="px-4 py-3 align-middle text-cyan-700 dark:text-cyan-300">{{ row.nama_kategori || '-' }}</td>
              <td class="px-4 py-3 align-middle text-slate-700 dark:text-slate-200">
                <div class="font-medium">{{ resolveCompanyBranchLabel(row).company }}</div>
                <div class="mt-1 text-xs text-slate-500 dark:text-slate-400">{{ resolveCompanyBranchLabel(row).branchesLabel }}</div>
              </td>
              <td class="px-4 py-3 align-middle text-slate-700 dark:text-slate-200">{{ resolveUserScope(row) }}</td>
              <td class="px-4 py-3 align-middle text-slate-700 dark:text-slate-200">{{ resolveTaxLabel(row) }}</td>
              <td
                class="whitespace-nowrap px-4 py-3 text-right align-middle font-medium"
                :class="Number(row.saldo_akhir || 0) < 0 ? 'text-rose-500' : 'text-slate-700 dark:text-slate-100'"
              >
                {{ formatBalance(row.saldo_akhir) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div
        v-if="!loading.list && coaTableRows.length"
        class="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300"
      >
        <div>
          Menampilkan
          <span class="font-semibold text-slate-900 dark:text-white">{{ coaStartRow + 1 }}</span>
          -
          <span class="font-semibold text-slate-900 dark:text-white">{{ coaEndRow }}</span>
          dari
          <span class="font-semibold text-slate-900 dark:text-white">{{ coaTableRows.length }}</span>
          akun
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <label class="flex items-center gap-2">
            <span>Per halaman</span>
            <select v-model.number="coaPageSize" class="rounded-xl border border-slate-200 bg-white px-2 py-1.5 text-sm outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white">
              <option :value="15">15</option>
              <option :value="25">25</option>
              <option :value="50">50</option>
              <option :value="100">100</option>
            </select>
          </label>
          <button class="rounded-xl border border-slate-200 bg-white px-3 py-1.5 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-950 dark:text-white" :disabled="coaPage <= 1" @click="previousCoaPage">Sebelumnya</button>
          <span class="px-2 text-slate-500 dark:text-slate-400">Hal {{ coaPage }} / {{ coaTotalPages }}</span>
          <button class="rounded-xl border border-slate-200 bg-white px-3 py-1.5 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-950 dark:text-white" :disabled="coaPage >= coaTotalPages" @click="nextCoaPage">Berikutnya</button>
        </div>
      </div>
    </section>

    <CoaDetailModal :account="detailAccount" :branches="branchOptions" :initial-date="filters.balanceDate" :initial-branch="filters.branchId" @close="detailAccount = null" @edit="editFromDetail" />

    <AppModal
      :open="modalOpen"
      :title="mode === 'create' ? 'Tambah COA' : `Edit COA ${selectedRow?.nomor_akun || ''}`"
      description="Susun akun induk, kategori, principal terkait, dan status aktif akun agar siap dipakai di jurnal."
      size="xl"
      @close="modalOpen = false"
    >
      <div class="space-y-5">
        <section v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {{ feedback }}
        </section>
        <section v-if="actionError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {{ actionError }}
        </section>

        <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <AppSearchSelect
            v-model="form.id_perusahaan"
            label="Perusahaan"
            placeholder="Pilih perusahaan"
            :options="formCompanyOptions"
            empty-text="Perusahaan belum tersedia."
          />
          <AppSearchSelect
            v-model="form.id_cabang_ids"
            multiple
            label="Cabang"
            placeholder="Pilih satu atau lebih cabang"
            :options="formBranchOptions"
            :disabled="!form.id_perusahaan || (shouldLockBusinessScope && !!fallbackBranchId)"
            empty-text="Pilih perusahaan terlebih dahulu."
          />
          <AppSearchSelect
            v-model="form.id_kategori"
            label="Kategori COA"
            placeholder="Pilih kategori akun"
            :options="categoryOptions"
            empty-text="Kategori akun belum tersedia."
          />
          <AppSearchSelect
            v-model="form.parent_id"
            label="Parent COA"
            placeholder="Opsional: pilih akun induk"
            :options="parentCoaOptions"
            empty-text="COA utama belum tersedia untuk perusahaan ini."
          />
          <div>
            <label class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Nomor Akun</label>
            <input v-model="form.nomor_akun" type="text" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none" />
          </div>
          <div>
            <label class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Nama Akun</label>
            <input v-model="form.nama_akun" type="text" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none" />
          </div>
          <AppSearchSelect
            v-model="form.principal_id"
            label="Principal"
            placeholder="Opsional: kaitkan principal"
            :options="principalOptions"
            empty-text="Principal belum tersedia untuk perusahaan ini."
          />
        </div>

        <label v-if="mode === 'edit'" class="flex items-center gap-3 text-sm text-slate-700">
          <input v-model="form.is_active" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-brand-600" />
          <span>Akun aktif dan bisa dipakai di transaksi</span>
        </label>
      </div>

      <template #footer>
        <div class="flex items-center justify-end gap-3">
          <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700" @click="modalOpen = false">
            Tutup
          </button>
          <button
            class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="loading.save || loading.refs"
            @click="save"
          >
            {{ loading.save ? 'Menyimpan...' : mode === 'create' ? 'Simpan COA' : 'Perbarui COA' }}
          </button>
        </div>
      </template>
    </AppModal>
  </div>
</template>
