<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getDueReceivables, getFinanceInvoices, getPaymentPlafons, updateFinanceInvoiceStatuses } from '@/api/finance';
import { getBranches, getCompanies } from '@/api/master';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getLoginCompanyId, getRowBranchIds, getRowCompanyId, isSuperUser, scopeRowsByLoginBranch } from '@/utils/accessScope';
import { addLocalDays, toLocalDateInputValue } from '@/utils/date';
import { resolveFinanceInvoiceStatusLabel } from '@/modules/finance/utils/statusLabels';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const today = new Date();
const defaultFrom = toLocalDateInputValue(addLocalDays(today, -90));
const defaultTo = toLocalDateInputValue(addLocalDays(today, 90));
const DEFAULT_PAGE_SIZE = 50;
const numberFormatter = new Intl.NumberFormat('id-ID');
const authStore = useAuthStore();

const form = reactive({
  branchId: '',
  companyId: '',
  // Empty means all plafon when the finance endpoints are called. Keeping it
  // empty also lets a remote search field accept typing immediately.
  plafonId: '',
  from: defaultFrom,
  to: defaultTo,
  noFaktur: ''
});

const branchRows = ref([]);
const companyRows = ref([]);
const plafonRows = ref([]);
const plafonOptionLoading = ref(false);
const dueRows = ref([]);
const invoiceRows = ref([]);
const selectedDue = ref(null);
const detailOpen = ref(false);
const loading = reactive({ due: false, invoices: false, statuses: false, options: false });
const pagination = reactive({
  due: { page: 1, perPage: DEFAULT_PAGE_SIZE, total: 0, totalPages: 1 },
  invoices: { page: 1, perPage: DEFAULT_PAGE_SIZE, total: 0, totalPages: 1 }
});
const feedback = ref('');
const errorMessage = ref('');
let plafonSearchRequest = 0;

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(authStore.user));
const canAccessAllBranches = computed(() => isSuperUser(authStore));
const canUseLoginScope = computed(() => !canAccessAllBranches.value);

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

function formatPlafonOption(item) {
  const customer = item.nama_customer || 'Customer';
  const customerCode = item.kode_customer ? ` (${item.kode_customer})` : '';
  const principal = item.nama_principal ? ` - ${item.nama_principal}` : '';
  const sales = item.nama_sales ? ` - Sales: ${item.nama_sales}` : '';
  return `${item.kode || '-'} - ${customer}${customerCode}${principal}${sales}`;
}

const plafonOptions = computed(() =>
  plafonRows.value
    .map((item) => ({
      value: String(item.id),
      // AppSearchSelect also filters the returned remote rows locally while
      // waiting for the next debounce. Include each searchable server field
      // in the label so a customer code or sales-name result is not hidden.
      label: formatPlafonOption(item)
    }))
);

function resetPlafonSearch() {
  plafonSearchRequest += 1;
  plafonOptionLoading.value = false;
  plafonRows.value = [];
}

function mergePlafonRows(rows = []) {
  const seen = new Set();
  const merged = [];

  // Let the newest remote search appear first, while retaining a selected
  // plafon when the user searches again for another value.
  [...rows, ...plafonRows.value].forEach((item) => {
    const id = String(item?.id ?? '');
    if (!id || seen.has(id)) return;
    seen.add(id);
    merged.push(item);
  });

  plafonRows.value = merged;
}

async function searchPaymentPlafons(keyword = '') {
  const search = String(keyword || '').trim();
  const requestId = ++plafonSearchRequest;

  // More than one hundred thousand plafon records exist in the master.
  // Do not trigger an unfiltered lookup merely by opening the selector.
  if (search.length < 2) {
    // Invalidate a previous request and immediately release its loading state.
    // That request's finally block intentionally cannot touch a newer search.
    plafonOptionLoading.value = false;
    return;
  }

  plafonOptionLoading.value = true;
  try {
    const response = await getPaymentPlafons({
      id_cabang: form.branchId || undefined,
      id_perusahaan: form.companyId || undefined,
      search,
      limit: 100
    });

    if (requestId === plafonSearchRequest) {
      mergePlafonRows(normalizeList(unwrapResponse(response)));
    }
  } catch (error) {
    if (requestId === plafonSearchRequest) {
      errorMessage.value = normalizeError(error, 'Daftar plafon belum bisa dicari.');
    }
  } finally {
    if (requestId === plafonSearchRequest) {
      plafonOptionLoading.value = false;
    }
  }
}

const dueSummary = computed(() => {
  const totalTagihan = dueRows.value.reduce((acc, item) => acc + Number(item.total_penjualan || 0), 0);
  const totalRetur = dueRows.value.reduce((acc, item) => acc + Number(item.nominal_retur || 0), 0);

  return [
    { label: 'Tagihan pada filter', value: numberFormatter.format(pagination.due.total) },
    { label: 'Penjualan halaman ini', value: formatCurrency(totalTagihan) },
    { label: 'Retur halaman ini', value: formatCurrency(totalRetur) }
  ];
});

const dueTableRows = computed(() =>
  dueRows.value.map((item) => ({
    ...item,
    total_penjualan_label: formatCurrency(item.total_penjualan),
    nominal_retur_label: formatCurrency(item.nominal_retur),
    jumlah_setoran: Array.isArray(item.setoran) ? item.setoran.length : 0,
    jumlah_faktur: Array.isArray(item.faktur) ? item.faktur.length : 0,
    sisa_tagihan_label: formatCurrency(Number(item.total_penjualan || 0) - Number(item.nominal_retur || 0)),
    status_label: `Order ${item.status_order || '-'} / Faktur ${item.status_faktur || '-'}`
  }))
);

const selectedFakturRows = computed(() => {
  if (!selectedDue.value) return [];
  const source = Array.isArray(selectedDue.value.faktur)
    ? selectedDue.value.faktur
    : selectedDue.value.faktur && typeof selectedDue.value.faktur === 'object'
      ? [selectedDue.value.faktur]
      : [];

  return source.map((item) => ({
    ...item,
    id: item.id ?? '-',
    no_faktur: item.no_faktur || '-',
    tanggal_order: item.tanggal_order || item.created_at || '-',
    tanggal_jatuh_tempo: item.tanggal_jatuh_tempo || '-',
    status_faktur_label: item.status_faktur_label || (item.status_faktur ?? '-')
  }));
});

const selectedSetoranRows = computed(() => {
  if (!selectedDue.value) return [];
  const source = Array.isArray(selectedDue.value.setoran) ? selectedDue.value.setoran : [];
  return source.map((item) => ({
    ...item,
    tanggal_setoran: item.tanggal_setoran || item.tanggal_input || '-',
    jumlah_setor: formatCurrency(item.jumlah_setor || item.jumlah_setoran || 0),
    tipe_setoran_label: item.tipe_setoran_label || (String(item.tipe_setoran) === '2' ? 'Non Tunai' : 'Tunai'),
    is_rekap_label: String(item.is_rekap ?? 0)
  }));
});

const invoiceTableRows = computed(() =>
  invoiceRows.value.map((item) => ({
    ...item,
    total_penjualan_label: formatCurrency(item.total_penjualan),
    total_retur_label: formatCurrency(item.nominal_retur),
    status_faktur_label: resolveFinanceInvoiceStatusLabel(item.status_faktur)
  }))
);

function formatCurrency(value) {
  return `Rp ${numberFormatter.format(Number(value || 0))}`;
}

function formatNumber(value) {
  return numberFormatter.format(Number(value || 0));
}

function openDueDetail(row) {
  selectedDue.value = row;
  detailOpen.value = true;
}

function closeDueDetail() {
  detailOpen.value = false;
}

async function loadAll() {
  if (loading.due || loading.invoices) return;

  errorMessage.value = '';
  feedback.value = '';
  const errors = [];

  // Jangan menjalankan dua query finance yang besar pada saat bersamaan.
  // Keduanya kini hanya mengambil satu halaman agar daftar plafon yang besar
  // tidak lagi memicu timeout browser maupun beban puncak di server.
  const dueResult = await loadDue(1, { keepMessages: true });
  if (!dueResult.ok) errors.push(dueResult.message);

  const invoiceResult = await loadInvoices(1, { keepMessages: true });
  if (!invoiceResult.ok) errors.push(invoiceResult.message);

  if (errors.length) {
    errorMessage.value = errors.join(' ');
  }
}

async function loadPlafonOptions() {
  loading.options = true;
  try {
    const [branchResponse, companyResponse] = await Promise.all([getBranches(), getCompanies()]);
    branchRows.value = normalizeList(unwrapResponse(branchResponse));
    companyRows.value = normalizeList(unwrapResponse(companyResponse));
    if (canUseLoginScope.value && fallbackBranchId.value) {
      form.branchId = String(fallbackBranchId.value);
    }
    if (canUseLoginScope.value && fallbackCompanyId.value) {
      form.companyId = String(fallbackCompanyId.value);
    }

    // Master plafon sangat besar. Opsi dimuat secara remote ketika pengguna
    // mengetik, sehingga record di luar halaman pertama tetap dapat ditemukan
    // tanpa mengunduh seluruh master ke browser.
    resetPlafonSearch();
  } finally {
    loading.options = false;
  }
}

function resolvePageMeta(response, fallbackLength, requestedPage, requestedPerPage) {
  const meta = response?.data?.meta || response?.data?.data?.meta || response?.data?.result?.meta || {};
  const page = Math.max(Number(meta.page || requestedPage || 1), 1);
  const perPage = Math.max(Number(meta.per_page || meta.perPage || requestedPerPage || DEFAULT_PAGE_SIZE), 1);
  const total = Math.max(Number(meta.total ?? fallbackLength ?? 0), 0);
  const totalPages = Math.max(Number(meta.total_pages || meta.totalPages || Math.ceil(total / perPage) || 1), 1);

  return { page, perPage, total, totalPages };
}

function applyPageMeta(type, response, fallbackLength, requestedPage) {
  const meta = resolvePageMeta(response, fallbackLength, requestedPage, pagination[type].perPage);
  pagination[type].page = Math.min(meta.page, meta.totalPages);
  pagination[type].perPage = meta.perPage;
  pagination[type].total = meta.total;
  pagination[type].totalPages = meta.totalPages;
}

function getReceivableParams(type, page) {
  return {
    from: form.from,
    to: form.to,
    id_cabang: form.branchId || undefined,
    id_perusahaan: form.companyId || undefined,
    no_faktur: form.noFaktur || undefined,
    page,
    per_page: pagination[type].perPage
  };
}

async function loadDue(page = pagination.due.page, { keepMessages = false } = {}) {
  loading.due = true;
  if (!keepMessages) {
    errorMessage.value = '';
    feedback.value = '';
  }

  try {
    const response = await getDueReceivables(form.plafonId || 0, getReceivableParams('due', page));
    dueRows.value = normalizeList(unwrapResponse(response));
    applyPageMeta('due', response, dueRows.value.length, page);
    return { ok: true };
  } catch (error) {
    const message = normalizeError(error, 'Tagihan jatuh tempo belum bisa dimuat.');
    if (!keepMessages) errorMessage.value = message;
    dueRows.value = [];
    pagination.due.page = 1;
    pagination.due.total = 0;
    pagination.due.totalPages = 1;
    return { ok: false, message };
  } finally {
    loading.due = false;
  }
}

async function loadInvoices(page = pagination.invoices.page, { keepMessages = false } = {}) {
  loading.invoices = true;
  if (!keepMessages) {
    errorMessage.value = '';
    feedback.value = '';
  }

  try {
    const response = await getFinanceInvoices(form.plafonId || 0, getReceivableParams('invoices', page));
    invoiceRows.value = normalizeList(unwrapResponse(response));
    applyPageMeta('invoices', response, invoiceRows.value.length, page);
    return { ok: true };
  } catch (error) {
    const message = normalizeError(error, 'Faktur customer belum bisa dimuat.');
    if (!keepMessages) errorMessage.value = message;
    invoiceRows.value = [];
    pagination.invoices.page = 1;
    pagination.invoices.total = 0;
    pagination.invoices.totalPages = 1;
    return { ok: false, message };
  } finally {
    loading.invoices = false;
  }
}

async function markAllInvoicesOpen() {
  const ids = dueRows.value.map((item) => item.id_faktur).filter(Boolean);
  if (!ids.length) {
    errorMessage.value = 'Belum ada faktur dari tagihan aktif yang bisa diubah statusnya.';
    return;
  }

  loading.statuses = true;
  errorMessage.value = '';
  feedback.value = '';

  try {
    await updateFinanceInvoiceStatuses({ id_fakturs: ids });
    feedback.value = 'Faktur berhasil dibuka untuk proses finance.';
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Status faktur belum berhasil diperbarui.');
  } finally {
    loading.statuses = false;
  }
}

onMounted(loadPlafonOptions);

watch(
  () => form.branchId,
  (branchId, previousBranchId) => {
    if (String(branchId || '') === String(previousBranchId || '')) return;
    form.companyId = canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
    form.plafonId = '';
    resetPlafonSearch();
  }
);

watch(
  () => form.companyId,
  (companyId) => {
    if (companyId && form.branchId && !companyIdsForBranch(form.branchId).includes(String(companyId))) {
      form.companyId = canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
    }
    form.plafonId = '';
    resetPlafonSearch();
  }
);
</script>

<template>
  <div class="space-y-6">
    <PageHeader title="Tagihan & Faktur Customer" description="Modul finance sekarang lebih siap dipakai untuk inspeksi tagihan plafon, rincian setoran, dan pengecekan faktur dalam rentang tanggal." />

    <section class="panel space-y-4 p-5">
      <div class="grid gap-4 lg:grid-cols-2 2xl:grid-cols-[minmax(220px,0.85fr)_minmax(260px,1fr)_minmax(360px,1.45fr)]">
        <AppSearchSelect v-model="form.branchId" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="!canAccessAllBranches && !!fallbackBranchId" empty-text="Cabang belum tersedia." />
        <AppSearchSelect v-model="form.companyId" label="Perusahaan" placeholder="Pilih perusahaan" :options="companyOptions" :disabled="!form.branchId || (canUseLoginScope && !!fallbackCompanyId)" empty-text="Pilih cabang terlebih dahulu." />
        <AppSearchSelect
          v-model="form.plafonId"
          label="Plafon"
          placeholder="Ketik kode plafon, customer, principal, atau sales"
          :options="plafonOptions"
          :loading="plafonOptionLoading"
          :remote-search="true"
          :search-debounce-ms="350"
          :max-visible-options="100"
          empty-text="Ketik minimal 2 karakter untuk mencari plafon."
          @search="searchPaymentPlafons"
        />
      </div>

      <div class="grid gap-4 lg:grid-cols-2 2xl:grid-cols-[minmax(190px,0.75fr)_minmax(190px,0.75fr)_minmax(300px,1.2fr)_minmax(420px,auto)]">
        <div>
          <label class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Dari Tanggal</label>
          <input v-model="form.from" type="date" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
        </div>
        <div>
          <label class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Sampai Tanggal</label>
          <input v-model="form.to" type="date" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
        </div>
        <div>
          <label class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Cari No Faktur</label>
          <input v-model="form.noFaktur" type="text" placeholder="Contoh: NPBMMSLO-2604000002" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
        </div>
        <div class="grid gap-3 sm:grid-cols-3 2xl:min-w-[420px] 2xl:self-end">
          <button
            class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="loading.due || loading.invoices"
            @click="loadAll"
          >
            {{ loading.due || loading.invoices ? 'Memuat...' : 'Muat Daftar' }}
          </button>
          <button
            class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
            :disabled="loading.invoices || loading.due"
            @click="loadInvoices(1)"
          >
            {{ loading.invoices ? 'Memuat...' : 'Muat Faktur' }}
          </button>
          <button class="rounded-xl border border-amber-200 px-4 py-3 text-sm font-medium text-amber-700 hover:bg-amber-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-amber-500/40 dark:text-amber-200 dark:hover:bg-amber-500/10" :disabled="loading.statuses" @click="markAllInvoicesOpen">
            {{ loading.statuses ? 'Memproses...' : 'Buka Faktur Finance' }}
          </button>
        </div>
      </div>
      <p class="text-sm text-slate-500 dark:text-slate-400">Daftar dimuat bertahap, maksimal {{ DEFAULT_PAGE_SIZE }} baris per tabel agar pencarian plafon besar tidak timeout. Gunakan navigasi halaman di bawah tabel untuk melihat seluruh hasil filter. Tombol <span class="font-medium text-slate-800 dark:text-slate-200">Buka Faktur Finance</span> hanya membuka faktur ke status proses finance, bukan menandai lunas.</p>
    </section>

    <section class="grid gap-4 md:grid-cols-3">
      <article v-for="item in dueSummary" :key="item.label" class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">{{ item.label }}</p>
        <p class="mt-3 text-lg font-semibold text-slate-900">{{ item.value }}</p>
      </article>
    </section>

    <section v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{{ feedback }}</section>
    <section v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ errorMessage }}</section>

    <div class="grid gap-6 xl:grid-cols-2">
      <section>
        <h3 class="mb-3 text-lg font-semibold text-slate-900">Tagihan jatuh tempo</h3>
        <AppTable
          :rows="dueTableRows"
          :columns="[
            { key: 'no_faktur', label: 'No Faktur' },
            { key: 'tanggal_jatuh_tempo', label: 'Jatuh Tempo' },
            { key: 'nama_customer', label: 'Customer' },
            { key: 'nama_principal', label: 'Principal' },
            { key: 'total_penjualan_label', label: 'Total' },
            { key: 'nominal_retur_label', label: 'Retur' },
            { key: 'sisa_tagihan_label', label: 'Sisa Est.' },
            { key: 'jumlah_faktur', label: 'Faktur' },
            { key: 'jumlah_setoran', label: 'Setoran' }
          ]"
          :loading="loading.due"
          :paginated="false"
          :clickable-rows="true"
          empty-message="Belum ada tagihan aktif untuk plafon terpilih."
          @row-click="openDueDetail"
        />
        <div class="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
          <p>
            Menampilkan {{ dueRows.length }} dari {{ formatNumber(pagination.due.total) }} tagihan
            <span class="text-slate-400 dark:text-slate-500">• Hal {{ pagination.due.page }} / {{ pagination.due.totalPages }}</span>
          </p>
          <div class="flex items-center gap-2">
            <button
              class="rounded-lg border border-slate-200 px-3 py-2 font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
              :disabled="loading.due || pagination.due.page <= 1"
              @click="loadDue(pagination.due.page - 1)"
            >
              Sebelumnya
            </button>
            <button
              class="rounded-lg border border-slate-200 px-3 py-2 font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
              :disabled="loading.due || pagination.due.page >= pagination.due.totalPages"
              @click="loadDue(pagination.due.page + 1)"
            >
              Berikutnya
            </button>
          </div>
        </div>
      </section>

      <section>
        <h3 class="mb-3 text-lg font-semibold text-slate-900">Faktur customer</h3>
        <AppTable
          :rows="invoiceTableRows"
          :columns="[
            { key: 'no_faktur', label: 'No Faktur' },
            { key: 'tanggal_order', label: 'Tanggal Order' },
            { key: 'total_penjualan_label', label: 'Total' },
            { key: 'status_faktur_label', label: 'Status Faktur' }
          ]"
          :loading="loading.invoices"
          :paginated="false"
          empty-message="Belum ada faktur customer pada rentang tanggal ini."
        />
        <div class="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
          <p>
            Menampilkan {{ invoiceRows.length }} dari {{ formatNumber(pagination.invoices.total) }} faktur
            <span class="text-slate-400 dark:text-slate-500">• Hal {{ pagination.invoices.page }} / {{ pagination.invoices.totalPages }}</span>
          </p>
          <div class="flex items-center gap-2">
            <button
              class="rounded-lg border border-slate-200 px-3 py-2 font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
              :disabled="loading.invoices || pagination.invoices.page <= 1"
              @click="loadInvoices(pagination.invoices.page - 1)"
            >
              Sebelumnya
            </button>
            <button
              class="rounded-lg border border-slate-200 px-3 py-2 font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
              :disabled="loading.invoices || pagination.invoices.page >= pagination.invoices.totalPages"
              @click="loadInvoices(pagination.invoices.page + 1)"
            >
              Berikutnya
            </button>
          </div>
        </div>
      </section>
    </div>

    <AppModal :open="detailOpen" title="Detail Tagihan" panel-class="max-w-5xl" @close="closeDueDetail">
      <div v-if="selectedDue" class="space-y-5">
        <section class="grid gap-3 md:grid-cols-4">
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-slate-400">No Faktur</p>
            <p class="mt-2 font-semibold text-slate-900">{{ selectedDue.no_faktur || '-' }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-slate-400">Customer</p>
            <p class="mt-2 font-semibold text-slate-900">{{ selectedDue.nama_customer || '-' }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-slate-400">Jatuh Tempo</p>
            <p class="mt-2 font-semibold text-slate-900">{{ selectedDue.tanggal_jatuh_tempo || '-' }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-slate-400">Sisa Estimasi</p>
            <p class="mt-2 font-semibold text-slate-900">{{ selectedDue.sisa_tagihan_label }}</p>
          </div>
        </section>

        <section>
          <h4 class="mb-3 text-base font-semibold text-slate-900">Faktur terkait</h4>
          <p class="mb-3 text-sm text-slate-500">Bagian ini diambil dari tabel <span class="font-medium text-slate-800">faktur</span> berdasarkan <span class="font-medium text-slate-800">id_sales_order</span> tagihan yang dipilih.</p>
          <AppTable
            :rows="selectedFakturRows"
            :columns="[
              { key: 'id', label: 'ID' },
              { key: 'no_faktur', label: 'No Faktur' },
              { key: 'tanggal_order', label: 'Tanggal Order' },
              { key: 'tanggal_jatuh_tempo', label: 'Jatuh Tempo' },
              { key: 'status_faktur_label', label: 'Status' }
            ]"
            empty-message="Tidak ada detail faktur tambahan."
          />
        </section>

        <section>
          <h4 class="mb-3 text-base font-semibold text-slate-900">Riwayat setoran terkait</h4>
          <p class="mb-3 text-sm text-slate-500">Bagian ini diambil dari <span class="font-medium text-slate-800">setoran_customer</span>. Kalau kolom <span class="font-medium text-slate-800">Rekap</span> bernilai <span class="font-medium text-slate-800">1</span>, artinya setoran itu sudah masuk proses rekap finance.</p>
          <AppTable
            :rows="selectedSetoranRows"
            :columns="[
              { key: 'id', label: 'ID' },
              { key: 'tanggal_setoran', label: 'Tanggal' },
              { key: 'jumlah_setor', label: 'Jumlah' },
              { key: 'tipe_setoran_label', label: 'Tipe' },
              { key: 'is_rekap_label', label: 'Rekap' }
            ]"
            empty-message="Belum ada setoran terkait."
          />
        </section>
      </div>
    </AppModal>
  </div>
</template>
