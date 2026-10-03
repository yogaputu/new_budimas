<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import { useAuthStore } from '@/app/stores/auth';
import { getVoucherUsageDetail, getVoucherUsageMonitoring } from '@/api/promo';
import {
  canAccessAllPromoBranches,
  getPromoBranchOptions,
  getPromoCompanyOptions,
  getPromoFallbackBranchId,
  getPromoPrincipalOptions
} from '@/modules/promo/utils/promoScope';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import AppEmptyState from '@/shared/components/AppEmptyState.vue';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const filters = reactive({
  branch: '',
  company: '',
  principal: '',
  tipe_voucher: '',
  usage_kind: '',
  search: ''
});

const auth = useAuthStore();
const branches = ref([]);
const companies = ref([]);
const principals = ref([]);
const rows = ref([]);
const loading = ref(false);
const detailLoading = ref(false);
const error = ref('');
const selectedRow = ref(null);
const selectedDetail = ref(null);

const canAccessAllBranches = computed(() => canAccessAllPromoBranches(auth));
const branchOptions = computed(() => getPromoBranchOptions(branches.value, auth));
const companyOptions = computed(() => getPromoCompanyOptions(companies.value, branches.value, filters.branch));
const principalOptions = computed(() => getPromoPrincipalOptions(principals.value, filters.company));

const filterFields = computed(() => [
  { key: 'branch', label: 'Cabang', type: 'select', options: branchOptions.value, disabled: !canAccessAllBranches.value },
  { key: 'company', label: 'Perusahaan', type: 'select', options: companyOptions.value, disabled: !filters.branch },
  { key: 'principal', label: 'Principal', type: 'select', options: principalOptions.value, disabled: !filters.company },
  {
    key: 'tipe_voucher',
    label: 'Tipe Voucher',
    type: 'select',
    options: [
      { value: '1', label: 'Voucher 1' },
      { value: '2', label: 'Voucher 2' },
      { value: '3', label: 'Voucher 3' }
    ]
  },
  {
    key: 'usage_kind',
    label: 'Jenis Pemakaian',
    type: 'select',
    options: [
      { value: 'regular', label: 'Reguler' },
      { value: 'product', label: 'Produk' }
    ]
  },
  { key: 'search', label: 'Cari Data', placeholder: 'Faktur, promo, customer, sales' }
]);

const summary = computed(() => ({
  total: rows.value.length,
  pending: rows.value.filter((row) => row.review_status_label === 'Draft').length,
  confirmed: rows.value.filter((row) => row.review_status_label === 'Terkonfirmasi').length,
  used: rows.value.filter((row) => row.review_status_label === 'Terpakai').length,
  rejected: rows.value.filter((row) => row.review_status_label === 'Tertolak').length
}));

const topCustomers = computed(() => {
  const grouped = new Map();
  for (const row of rows.value) {
    const key = row.nama_customer || 'Customer tidak diketahui';
    const current = grouped.get(key) || {
      nama_customer: key,
      principal: row.principal || '-',
      total_usage: 0,
      total_nominal: 0,
      terpakai: 0,
      tertolak: 0
    };
    current.total_usage += 1;
    current.total_nominal += Number(row.nominal_promo || 0);
    if (row.review_status_label === 'Terpakai') current.terpakai += 1;
    if (row.review_status_label === 'Tertolak') current.tertolak += 1;
    grouped.set(key, current);
  }
  return [...grouped.values()].sort((a, b) => b.total_nominal - a.total_nominal).slice(0, 6);
});

const topSales = computed(() => {
  const grouped = new Map();
  for (const row of rows.value) {
    const key = row.nama_sales || 'Sales tidak diketahui';
    const current = grouped.get(key) || {
      nama_sales: key,
      total_usage: 0,
      total_nominal: 0,
      draft: 0,
      confirmed: 0,
      rejected: 0
    };
    current.total_usage += 1;
    current.total_nominal += Number(row.nominal_promo || 0);
    if (row.review_status_label === 'Draft') current.draft += 1;
    if (['Terkonfirmasi', 'Terpakai'].includes(row.review_status_label)) current.confirmed += 1;
    if (row.review_status_label === 'Tertolak') current.rejected += 1;
    grouped.set(key, current);
  }
  return [...grouped.values()].sort((a, b) => b.total_usage - a.total_usage).slice(0, 6);
});

const selectedKey = computed(() => `${selectedRow.value?.usage_kind || ''}:${selectedRow.value?.usage_id || ''}`);

const tableColumns = [
  { key: 'kode_voucher', label: 'Kode Voucher' },
  { key: 'nama_voucher', label: 'Nama Voucher' },
  { key: 'principal', label: 'Principal' },
  { key: 'nama_customer', label: 'Customer' },
  { key: 'nama_sales', label: 'Sales' },
  {
    key: 'usage_kind',
    label: 'Jenis',
    render: (row) => ({
      text: row.usage_kind === 'product' ? 'Produk' : 'Reguler',
      className:
        row.usage_kind === 'product'
          ? 'inline-flex min-w-[86px] items-center justify-center rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700'
          : 'inline-flex min-w-[86px] items-center justify-center rounded-full bg-sky-100 px-3 py-1 text-xs font-semibold text-sky-700'
    })
  },
  {
    key: 'nominal_promo',
    label: 'Nilai',
    render: (row) =>
      new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(
        Number(row.nominal_promo || 0)
      )
  },
  {
    key: 'review_status_label',
    label: 'Status',
    render: (row) => ({
      text: row.review_status_label,
      className:
        row.review_status_label === 'Terkonfirmasi'
          ? 'inline-flex min-w-[110px] items-center justify-center rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700'
          : row.review_status_label === 'Terpakai'
            ? 'inline-flex min-w-[110px] items-center justify-center rounded-full bg-indigo-100 px-3 py-1 text-xs font-semibold text-indigo-700'
            : row.review_status_label === 'Tertolak'
              ? 'inline-flex min-w-[110px] items-center justify-center rounded-full bg-rose-100 px-3 py-1 text-xs font-semibold text-rose-700'
              : 'inline-flex min-w-[110px] items-center justify-center rounded-full bg-slate-200 px-3 py-1 text-xs font-semibold text-slate-700'
    })
  }
];

async function loadReferences() {
  const [branchResponse, companyResponse, principalResponse] = await Promise.all([
    getBranches(),
    getCompanies(),
    getPrincipals()
  ]);
  branches.value = normalizeList(unwrapResponse(branchResponse));
  companies.value = normalizeList(unwrapResponse(companyResponse));
  principals.value = normalizeList(unwrapResponse(principalResponse));
  applyLoginBranchScope();
}

async function loadRows() {
  loading.value = true;
  error.value = '';
  try {
    const response = await getVoucherUsageMonitoring({
      id_cabang: filters.branch,
      id_perusahaan: filters.company,
      id_principal: filters.principal,
      tipe_voucher: filters.tipe_voucher,
      usage_kind: filters.usage_kind,
      filters: filters.search
    });
    const payload = unwrapResponse(response) || {};
    rows.value = normalizeList(payload.pages || payload);
  } catch (err) {
    error.value = normalizeError(err, 'Monitoring pemakaian voucher belum bisa dimuat.');
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

function applyLoginBranchScope() {
  const fallbackBranch = getPromoFallbackBranchId(auth);
  if (!canAccessAllBranches.value && fallbackBranch) {
    filters.branch = String(fallbackBranch);
  }
}

function updateFilters(nextFilters) {
  const previousBranch = filters.branch;
  const previousCompany = filters.company;
  Object.assign(filters, nextFilters || {});
  if (String(previousBranch || '') !== String(filters.branch || '')) {
    filters.company = '';
    filters.principal = '';
    return;
  }
  if (String(previousCompany || '') !== String(filters.company || '')) {
    filters.principal = '';
  }
}

function resetFilters() {
  Object.assign(filters, {
    branch: canAccessAllBranches.value ? '' : getPromoFallbackBranchId(auth) || '',
    company: '',
    principal: '',
    tipe_voucher: '',
    usage_kind: '',
    search: ''
  });
}

async function openDetail(row) {
  selectedRow.value = row;
  detailLoading.value = true;
  error.value = '';
  try {
    const response = await getVoucherUsageDetail(row.usage_kind, row.usage_id);
    selectedDetail.value = unwrapResponse(response) || {};
  } catch (err) {
    error.value = normalizeError(err, 'Detail pemakaian voucher belum bisa dimuat.');
    selectedDetail.value = null;
  } finally {
    detailLoading.value = false;
  }
}

onMounted(async () => {
  await loadReferences();
  await loadRows();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Monitoring Pemakaian Voucher"
      description="Saya kumpulkan pemakaian voucher reguler dan produk dalam satu layar agar tim promo bisa memantau invoice, customer, principal, dan status review dari backend lama."
    />

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
      <article class="panel p-5"><p class="text-xs uppercase tracking-[0.25em] text-slate-400">Total</p><p class="mt-3 text-2xl font-semibold text-slate-900">{{ summary.total }}</p></article>
      <article class="panel p-5"><p class="text-xs uppercase tracking-[0.25em] text-slate-400">Draft</p><p class="mt-3 text-2xl font-semibold text-slate-700">{{ summary.pending }}</p></article>
      <article class="panel p-5"><p class="text-xs uppercase tracking-[0.25em] text-slate-400">Terkonfirmasi</p><p class="mt-3 text-2xl font-semibold text-emerald-600">{{ summary.confirmed }}</p></article>
      <article class="panel p-5"><p class="text-xs uppercase tracking-[0.25em] text-slate-400">Terpakai</p><p class="mt-3 text-2xl font-semibold text-indigo-600">{{ summary.used }}</p></article>
      <article class="panel p-5"><p class="text-xs uppercase tracking-[0.25em] text-slate-400">Tertolak</p><p class="mt-3 text-2xl font-semibold text-rose-600">{{ summary.rejected }}</p></article>
    </section>

    <AppFilterBar
      :model-value="filters"
      :fields="filterFields"
      @update:model-value="updateFilters"
      @submit="loadRows"
      @reset="resetFilters"
    />

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ error }}
    </section>

    <section class="grid gap-6 xl:grid-cols-2">
      <article class="panel p-5">
        <div class="flex items-center justify-between gap-4">
          <div>
            <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Monitoring Customer</p>
            <h3 class="mt-2 text-lg font-semibold text-slate-900">Customer dengan pemakaian voucher terbesar</h3>
          </div>
          <span class="rounded-full bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-700">{{ topCustomers.length }} customer</span>
        </div>
        <div class="mt-4 space-y-3">
          <div
            v-for="customer in topCustomers"
            :key="customer.nama_customer"
            class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"
          >
            <div class="flex items-start justify-between gap-4">
              <div>
                <p class="text-sm font-semibold text-slate-900">{{ customer.nama_customer }}</p>
                <p class="mt-1 text-xs text-slate-500">{{ customer.principal }}</p>
              </div>
              <p class="text-sm font-semibold text-slate-900">
                {{ new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(customer.total_nominal) }}
              </p>
            </div>
            <div class="mt-3 flex flex-wrap gap-2 text-xs text-slate-600">
              <span class="rounded-full bg-slate-200 px-2.5 py-1 font-medium">Usage: {{ customer.total_usage }}</span>
              <span class="rounded-full bg-indigo-100 px-2.5 py-1 font-medium text-indigo-700">Terpakai: {{ customer.terpakai }}</span>
              <span class="rounded-full bg-rose-100 px-2.5 py-1 font-medium text-rose-700">Tertolak: {{ customer.tertolak }}</span>
            </div>
          </div>
          <p v-if="!topCustomers.length" class="text-sm text-slate-500">Belum ada customer yang memakai voucher pada filter ini.</p>
        </div>
      </article>

      <article class="panel p-5">
        <div class="flex items-center justify-between gap-4">
          <div>
            <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Monitoring Sales</p>
            <h3 class="mt-2 text-lg font-semibold text-slate-900">Sales paling aktif memakai voucher</h3>
          </div>
          <span class="rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">{{ topSales.length }} sales</span>
        </div>
        <div class="mt-4 space-y-3">
          <div
            v-for="sales in topSales"
            :key="sales.nama_sales"
            class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"
          >
            <div class="flex items-start justify-between gap-4">
              <div>
                <p class="text-sm font-semibold text-slate-900">{{ sales.nama_sales }}</p>
                <p class="mt-1 text-xs text-slate-500">Pemakaian voucher pada invoice sales ini</p>
              </div>
              <p class="text-sm font-semibold text-slate-900">{{ sales.total_usage }} usage</p>
            </div>
            <div class="mt-3 flex flex-wrap gap-2 text-xs text-slate-600">
              <span class="rounded-full bg-slate-200 px-2.5 py-1 font-medium">
                {{ new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(sales.total_nominal) }}
              </span>
              <span class="rounded-full bg-amber-100 px-2.5 py-1 font-medium text-amber-700">Draft: {{ sales.draft }}</span>
              <span class="rounded-full bg-emerald-100 px-2.5 py-1 font-medium text-emerald-700">OK: {{ sales.confirmed }}</span>
              <span class="rounded-full bg-rose-100 px-2.5 py-1 font-medium text-rose-700">Tolak: {{ sales.rejected }}</span>
            </div>
          </div>
          <p v-if="!topSales.length" class="text-sm text-slate-500">Belum ada data sales pada filter ini.</p>
        </div>
      </article>
    </section>

    <section class="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
      <AppTable
        :rows="rows"
        :columns="tableColumns"
        :loading="loading"
        :clickable-rows="true"
        row-key="usage_id"
        :selected-key="selectedKey"
        empty-message="Belum ada data pemakaian voucher."
        @row-click="openDetail"
      />

      <aside class="panel p-5">
        <div>
          <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Detail Pemakaian</p>
          <h3 class="mt-2 text-xl font-semibold text-slate-900">{{ selectedDetail?.kode_voucher || 'Pilih data voucher' }}</h3>
          <p class="mt-1 text-sm text-slate-500">{{ selectedDetail?.nama_voucher || 'Klik salah satu baris untuk melihat invoice, customer, dan item voucher.' }}</p>
        </div>

        <div v-if="detailLoading" class="mt-6 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
          Memuat detail pemakaian voucher...
        </div>

        <AppEmptyState
          v-else-if="!selectedDetail"
          title="Belum ada data dipilih"
          description="Panel ini akan menampilkan detail invoice, sales, customer, dan daftar item voucher yang digunakan."
        />

        <div v-else class="mt-6 space-y-4">
          <div class="grid gap-3 sm:grid-cols-2">
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"><p class="text-xs uppercase tracking-[0.2em] text-slate-400">Invoice</p><p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedDetail.no_faktur || '-' }}</p></div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"><p class="text-xs uppercase tracking-[0.2em] text-slate-400">Status</p><p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedDetail.review_status_label || '-' }}</p></div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"><p class="text-xs uppercase tracking-[0.2em] text-slate-400">Customer</p><p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedDetail.nama_customer || '-' }}</p></div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"><p class="text-xs uppercase tracking-[0.2em] text-slate-400">Sales</p><p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedDetail.nama_sales || '-' }}</p></div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"><p class="text-xs uppercase tracking-[0.2em] text-slate-400">Principal</p><p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedDetail.principal || '-' }}</p></div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"><p class="text-xs uppercase tracking-[0.2em] text-slate-400">Nilai Voucher</p><p class="mt-2 text-sm font-semibold text-slate-900">{{ new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(Number(selectedDetail.nominal_promo || 0)) }}</p></div>
          </div>

          <div class="rounded-2xl border border-slate-200 bg-white p-4">
            <p class="text-sm font-semibold text-slate-900">Catatan Reviewer Terbaru</p>
            <div v-if="selectedDetail.latest_review_note" class="mt-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <div class="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span class="rounded-full bg-slate-200 px-2.5 py-1 font-medium text-slate-700">{{ selectedDetail.latest_review_note.action_type }}</span>
                <span>{{ selectedDetail.latest_review_note.reviewer_name || 'Reviewer' }}</span>
                <span>{{ selectedDetail.latest_review_note.created_at || '-' }}</span>
              </div>
              <p class="mt-3 text-sm text-slate-700">{{ selectedDetail.latest_review_note.reviewer_note || '-' }}</p>
            </div>
            <p v-else class="mt-3 text-sm text-slate-500">Belum ada catatan reviewer untuk voucher ini.</p>
          </div>

          <div class="rounded-2xl border border-slate-200 bg-white p-4">
            <p class="text-sm font-semibold text-slate-900">Item Voucher</p>
            <div class="mt-3 space-y-3">
              <div v-for="item in selectedDetail.items || []" :key="`${item.id_produk}-${item.nama_produk}`" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                <p class="text-sm font-semibold text-slate-900">{{ item.nama_produk || `Produk ${item.id_produk}` }}</p>
                <div class="mt-2 flex flex-wrap gap-4 text-xs text-slate-500">
                  <span>Discount: {{ item.discount || 0 }}</span>
                  <span>Nilai: {{ new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(Number(item.nilai_discount || 0)) }}</span>
                </div>
              </div>
              <p v-if="!(selectedDetail.items || []).length" class="text-sm text-slate-500">Belum ada item yang tercatat.</p>
            </div>
          </div>

          <div class="rounded-2xl border border-slate-200 bg-white p-4">
            <p class="text-sm font-semibold text-slate-900">Histori Review</p>
            <div class="mt-3 space-y-3">
              <div
                v-for="note in selectedDetail.review_notes || []"
                :key="note.id"
                class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"
              >
                <div class="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <span class="rounded-full bg-slate-200 px-2.5 py-1 font-medium text-slate-700">{{ note.action_type }}</span>
                  <span>{{ note.reviewer_name || 'Reviewer' }}</span>
                  <span>{{ note.created_at || '-' }}</span>
                </div>
                <p class="mt-3 text-sm text-slate-700">{{ note.reviewer_note || '-' }}</p>
              </div>
              <p v-if="!(selectedDetail.review_notes || []).length" class="text-sm text-slate-500">Belum ada histori review untuk voucher ini.</p>
            </div>
          </div>
        </div>
      </aside>
    </section>
  </div>
</template>
