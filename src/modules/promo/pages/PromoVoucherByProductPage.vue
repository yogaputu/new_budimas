<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import { useAuthStore } from '@/app/stores/auth';
import { getVoucherUsageByProduct } from '@/api/promo';
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
  search: ''
});

const auth = useAuthStore();
const branches = ref([]);
const companies = ref([]);
const principals = ref([]);
const rows = ref([]);
const loading = ref(false);
const error = ref('');

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
  { key: 'search', label: 'Cari Produk', placeholder: 'Nama produk atau principal' }
]);

const summary = computed(() => ({
  totalProduk: rows.value.length,
  totalNominal: rows.value.reduce((sum, row) => sum + Number(row.total_nominal || 0), 0),
  totalUsage: rows.value.reduce((sum, row) => sum + Number(row.total_usage || 0), 0),
  uniqueCustomers: rows.value.reduce((sum, row) => sum + Number(row.total_customer || 0), 0),
  uniqueSales: rows.value.reduce((sum, row) => sum + Number(row.total_sales || 0), 0)
}));

const hottestProducts = computed(() => rows.value.slice(0, 5));
const atRiskProducts = computed(() => rows.value.filter((row) => Number(row.rejected_count || 0) > 0).slice(0, 5));

const tableColumns = [
  { key: 'nama_produk', label: 'Produk' },
  { key: 'principal', label: 'Principal' },
  { key: 'total_usage', label: 'Usage' },
  {
    key: 'usage_health',
    label: 'Intensitas',
    render: (row) => ({
      text: row.usage_health || 'Rendah',
      className:
        row.usage_health === 'Tinggi'
          ? 'inline-flex min-w-[90px] items-center justify-center rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700'
          : row.usage_health === 'Menengah'
            ? 'inline-flex min-w-[90px] items-center justify-center rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700'
            : 'inline-flex min-w-[90px] items-center justify-center rounded-full bg-slate-200 px-3 py-1 text-xs font-semibold text-slate-700'
    })
  },
  { key: 'total_customer', label: 'Customer' },
  { key: 'total_sales', label: 'Sales' },
  {
    key: 'total_nominal',
    label: 'Total Nominal',
    render: (row) =>
      new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(
        Number(row.total_nominal || 0)
      )
  },
  { key: 'draft_count', label: 'Draft' },
  { key: 'confirmed_count', label: 'OK' },
  { key: 'used_count', label: 'Terpakai' },
  { key: 'rejected_count', label: 'Tolak' },
  { key: 'last_usage_date', label: 'Usage Terakhir' }
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
    const response = await getVoucherUsageByProduct({
      id_cabang: filters.branch,
      id_perusahaan: filters.company,
      id_principal: filters.principal,
      tipe_voucher: filters.tipe_voucher,
      filters: filters.search
    });
    const payload = unwrapResponse(response) || {};
    rows.value = normalizeList(payload.pages || payload);
  } catch (err) {
    error.value = normalizeError(err, 'Analisa voucher per produk belum bisa dimuat.');
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
    search: ''
  });
}

onMounted(async () => {
  await loadReferences();
  await loadRows();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Monitoring Voucher per Produk"
      description="Saya kumpulkan performa voucher dari sisi produk agar tim promo bisa membaca produk mana yang paling sering memakai voucher, nominal promo tertinggi, dan pola reject yang perlu diawasi."
    />

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Total Produk</p>
        <p class="mt-3 text-2xl font-semibold text-slate-900">{{ summary.totalProduk }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Total Usage</p>
        <p class="mt-3 text-2xl font-semibold text-slate-900">{{ summary.totalUsage }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Total Nominal</p>
        <p class="mt-3 text-2xl font-semibold text-slate-900">
          {{ new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(summary.totalNominal) }}
        </p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Customer Tersentuh</p>
        <p class="mt-3 text-2xl font-semibold text-slate-900">{{ summary.uniqueCustomers }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Sales Tersentuh</p>
        <p class="mt-3 text-2xl font-semibold text-slate-900">{{ summary.uniqueSales }}</p>
      </article>
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
            <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Produk Terpanas</p>
            <h3 class="mt-2 text-lg font-semibold text-slate-900">Top produk dengan pemakaian voucher tertinggi</h3>
          </div>
          <span class="rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">{{ hottestProducts.length }} produk</span>
        </div>
        <div class="mt-4 space-y-3">
          <div
            v-for="product in hottestProducts"
            :key="product.id_produk"
            class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"
          >
            <div class="flex items-start justify-between gap-4">
              <div>
                <p class="text-sm font-semibold text-slate-900">{{ product.nama_produk || `Produk ${product.id_produk}` }}</p>
                <p class="mt-1 text-xs text-slate-500">{{ product.principal || '-' }}</p>
              </div>
              <div class="text-right">
                <p class="text-sm font-semibold text-slate-900">{{ product.total_usage }} usage</p>
                <p class="mt-1 text-xs text-slate-500">
                  {{ new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(Number(product.total_nominal || 0)) }}
                </p>
              </div>
            </div>
          </div>
          <p v-if="!hottestProducts.length" class="text-sm text-slate-500">Belum ada produk yang memakai voucher pada filter ini.</p>
        </div>
      </article>

      <article class="panel p-5">
        <div class="flex items-center justify-between gap-4">
          <div>
            <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Produk Perlu Review</p>
            <h3 class="mt-2 text-lg font-semibold text-slate-900">Produk dengan reject voucher tertinggi</h3>
          </div>
          <span class="rounded-full bg-rose-50 px-3 py-1 text-xs font-semibold text-rose-700">{{ atRiskProducts.length }} produk</span>
        </div>
        <div class="mt-4 space-y-3">
          <div
            v-for="product in atRiskProducts"
            :key="`${product.id_produk}-risk`"
            class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"
          >
            <div class="flex items-start justify-between gap-4">
              <div>
                <p class="text-sm font-semibold text-slate-900">{{ product.nama_produk || `Produk ${product.id_produk}` }}</p>
                <p class="mt-1 text-xs text-slate-500">{{ product.principal || '-' }}</p>
              </div>
              <div class="text-right">
                <p class="text-sm font-semibold text-rose-700">{{ product.rejected_count }} reject</p>
                <p class="mt-1 text-xs text-slate-500">Customer: {{ product.total_customer }}</p>
              </div>
            </div>
          </div>
          <p v-if="!atRiskProducts.length" class="text-sm text-slate-500">Belum ada produk dengan reject voucher pada filter ini.</p>
        </div>
      </article>
    </section>

    <AppTable
      :rows="rows"
      :columns="tableColumns"
      :loading="loading"
      empty-message="Belum ada data analisa voucher per produk."
    />

    <AppEmptyState
      v-if="!loading && !rows.length && !error"
      title="Belum ada analisa produk"
      description="Pilih principal atau tipe voucher tertentu jika Anda ingin mempersempit monitoring voucher dari sisi produk."
    />
  </div>
</template>
