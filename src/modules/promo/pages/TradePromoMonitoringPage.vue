<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import { getTradePromoMonitoring } from '@/api/promo';
import { useAuthStore } from '@/app/stores/auth';
import {
  canAccessAllPromoBranches,
  getPromoBranchOptions,
  getPromoCompanyOptions,
  getPromoFallbackBranchId,
  getPromoPrincipalOptions
} from '@/modules/promo/utils/promoScope';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { toLocalDateInputValue } from '@/utils/date';
import AppEmptyState from '@/shared/components/AppEmptyState.vue';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const auth = useAuthStore();
const today = toLocalDateInputValue();

const filters = reactive({
  branch: '',
  company: '',
  principal: '',
  from: today,
  to: today,
  search: ''
});

const branches = ref([]);
const companies = ref([]);
const principals = ref([]);
const rows = ref([]);
const summary = ref({ orders: 0, qualified: 0, estimated_cashback: 0, groups: 0 });
const loading = ref(false);
const error = ref('');

const canAccessAllBranches = computed(() => canAccessAllPromoBranches(auth));
const branchOptions = computed(() => getPromoBranchOptions(branches.value, auth));
const companyOptions = computed(() => getPromoCompanyOptions(companies.value, branches.value, filters.branch));
const principalOptions = computed(() => getPromoPrincipalOptions(principals.value, filters.company));

const filterFields = computed(() => [
  { key: 'branch', label: 'Cabang', type: 'search-select', options: branchOptions.value, disabled: !canAccessAllBranches.value },
  { key: 'company', label: 'Perusahaan', type: 'search-select', options: companyOptions.value, disabled: !filters.branch },
  { key: 'principal', label: 'Principal', type: 'search-select', options: principalOptions.value, disabled: !filters.company },
  { key: 'from', label: 'Dari Tanggal', type: 'date' },
  { key: 'to', label: 'Sampai Tanggal', type: 'date' },
  { key: 'search', label: 'Cari', placeholder: 'Faktur, SO, customer, sales' }
]);

const qualifiedRows = computed(() => rows.value.filter((row) => row.qualified));
const nearRows = computed(() => rows.value.filter((row) => !row.qualified && Number(row.gap_qty || 0) > 0).slice(0, 8));

const tableColumns = [
  { key: 'tanggal_order', label: 'Tanggal' },
  { key: 'no_faktur', label: 'Faktur', render: (row) => row.no_faktur || row.no_sales_order || '-' },
  { key: 'nama_customer', label: 'Customer' },
  { key: 'nama_sales', label: 'Sales' },
  { key: 'nama_principal', label: 'Principal' },
  { key: 'subbrand_nama', label: 'Sub-brand' },
  {
    key: 'qty_ctn',
    label: 'Qty Ctn',
    render: (row) => Number(row.qty_ctn || 0).toLocaleString('id-ID')
  },
  {
    key: 'qualified',
    label: 'Status',
    render: (row) => ({
      text: row.qualified ? 'Memenuhi' : `Kurang ${Number(row.gap_qty || 0).toLocaleString('id-ID')} ctn`,
      className: row.qualified
        ? 'inline-flex rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700'
        : 'inline-flex rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700'
    })
  },
  {
    key: 'estimated_cashback',
    label: 'Est. Cashback',
    render: (row) =>
      new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(
        Number(row.estimated_cashback || 0)
      )
  }
];

function formatCurrency(value) {
  return new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(Number(value || 0));
}

async function loadReferences() {
  const [branchResponse, companyResponse, principalResponse] = await Promise.all([getBranches(), getCompanies(), getPrincipals()]);
  branches.value = normalizeList(unwrapResponse(branchResponse));
  companies.value = normalizeList(unwrapResponse(companyResponse));
  principals.value = normalizeList(unwrapResponse(principalResponse));
  applyLoginScope();
}

function applyLoginScope() {
  const fallbackBranch = getPromoFallbackBranchId(auth);
  if (!canAccessAllBranches.value && fallbackBranch) {
    filters.branch = String(fallbackBranch);
  }
}

async function loadRows() {
  loading.value = true;
  error.value = '';
  try {
    const response = await getTradePromoMonitoring({
      id_cabang: filters.branch,
      id_perusahaan: filters.company,
      id_principal: filters.principal,
      from: filters.from,
      to: filters.to,
      search: filters.search
    });
    const payload = unwrapResponse(response) || {};
    rows.value = normalizeList(payload.rows || payload);
    summary.value = payload.summary || { orders: 0, qualified: 0, estimated_cashback: 0, groups: rows.value.length };
  } catch (err) {
    error.value = normalizeError(err, 'Monitoring cashback bertingkat belum bisa dimuat.');
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

function updateFilters(nextFilters) {
  const oldBranch = filters.branch;
  const oldCompany = filters.company;
  Object.assign(filters, nextFilters || {});
  if (String(oldBranch || '') !== String(filters.branch || '')) {
    filters.company = '';
    filters.principal = '';
    return;
  }
  if (String(oldCompany || '') !== String(filters.company || '')) {
    filters.principal = '';
  }
}

function resetFilters() {
  Object.assign(filters, {
    branch: canAccessAllBranches.value ? '' : getPromoFallbackBranchId(auth) || '',
    company: '',
    principal: '',
    from: today,
    to: today,
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
      title="Monitoring Cashback Bertingkat"
      description="Pantau outlet dan sales yang sudah memenuhi strata cashback berdasarkan sub-brand dan kuantitas karton."
    />

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Order Dicek</p>
        <p class="mt-3 text-2xl font-semibold text-slate-900 dark:text-white">{{ Number(summary.orders || 0).toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Group Promo</p>
        <p class="mt-3 text-2xl font-semibold text-slate-900 dark:text-white">{{ Number(summary.groups || rows.length || 0).toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Memenuhi Strata</p>
        <p class="mt-3 text-2xl font-semibold text-emerald-600 dark:text-emerald-300">{{ Number(summary.qualified || qualifiedRows.length || 0).toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Est. Cashback</p>
        <p class="mt-3 text-2xl font-semibold text-slate-900 dark:text-white">{{ formatCurrency(summary.estimated_cashback) }}</p>
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

    <section v-if="nearRows.length" class="panel p-5">
      <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Hampir Memenuhi</p>
      <div class="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <article v-for="row in nearRows" :key="`${row.id_sales_order}-${row.id_subbrand}`" class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 dark:border-amber-500/30 dark:bg-amber-500/10">
          <p class="text-sm font-semibold text-slate-900 dark:text-white">{{ row.nama_customer || '-' }}</p>
          <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">{{ row.subbrand_nama || '-' }} | {{ row.nama_sales || '-' }}</p>
          <p class="mt-2 text-sm font-bold text-amber-700 dark:text-amber-300">Kurang {{ Number(row.gap_qty || 0).toLocaleString('id-ID') }} ctn</p>
        </article>
      </div>
    </section>

    <section class="panel overflow-hidden">
      <div class="border-b border-slate-200 px-5 py-4">
        <h3 class="text-lg font-semibold text-slate-900 dark:text-white">Daftar Capaian Cashback</h3>
        <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">Klik filter tanggal/cabang/principal untuk melihat outlet dan sales yang sudah memenuhi strata.</p>
      </div>
      <AppTable :rows="rows" :columns="tableColumns" :loading="loading" empty-message="Belum ada data cashback bertingkat." />
    </section>

    <AppEmptyState
      v-if="!loading && !rows.length && !error"
      title="Belum ada capaian"
      description="Jika order sudah ada tetapi belum muncul, cek master produk: brand, sub-brand, UOM, dan harga tipe harus lengkap."
    />
  </div>
</template>
