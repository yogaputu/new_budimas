<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import { getCustomerReceivableBalances, getCustomerReceivableInvoices } from '@/api/finance';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getLoginCompanyId, isSuperUser } from '@/utils/accessScope';
import { getBranchOptionsForCompany, getCompanyOptionsForScope } from '@/utils/filterScope';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const numberFormatter = new Intl.NumberFormat('id-ID');

const filters = reactive({
  id_cabang: '',
  id_perusahaan: '',
  id_principal: '',
  search: ''
});

const rows = ref([]);
const detailRows = ref([]);
const selectedCustomer = ref(null);
const detailOpen = ref(false);
const summary = reactive({
  total_customer: 0,
  total_saldo_piutang: 0,
  total_tagihan: 0,
  total_bayar: 0,
  total_cn: 0
});
const detailSummary = reactive({
  jumlah_faktur: 0,
  total_tagihan: 0,
  total_retur: 0,
  total_bayar: 0,
  total_cn: 0,
  saldo_piutang: 0
});
const branches = ref([]);
const companies = ref([]);
const principals = ref([]);
const loading = reactive({ refs: false, list: false, detail: false });
const errorMessage = ref('');
const detailErrorMessage = ref('');

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(authStore.user));
const canAccessAllBranches = computed(() => isSuperUser(authStore));

const companyOptions = computed(() => getCompanyOptionsForScope(companies.value, authStore));
const branchOptions = computed(() => getBranchOptionsForCompany(branches.value, authStore, filters.id_perusahaan));
const principalOptions = computed(() =>
  principals.value
    .filter((item) => !filters.id_perusahaan || String(item.id_perusahaan || '') === String(filters.id_perusahaan))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || '-'} - ${item.nama || `Principal ${item.id}`}`
    }))
);

const cards = computed(() => [
  { label: 'Customer Piutang', value: numberFormatter.format(summary.total_customer || 0) },
  { label: 'Saldo Piutang', value: formatCurrency(summary.total_saldo_piutang), tone: 'text-rose-700 dark:text-rose-300' },
  { label: 'Total Tagihan', value: formatCurrency(summary.total_tagihan) },
  { label: 'Total Bayar + CN', value: formatCurrency(Number(summary.total_bayar || 0) + Number(summary.total_cn || 0)), tone: 'text-emerald-700 dark:text-emerald-300' }
]);

const tableRows = computed(() =>
  rows.value.map((item) => ({
    ...item,
    saldo_piutang_label: formatCurrency(item.saldo_piutang),
    total_tagihan_label: formatCurrency(item.total_tagihan),
    total_bayar_label: formatCurrency(item.total_bayar),
    total_cn_label: formatCurrency(item.total_cn),
    jumlah_faktur_label: `${Number(item.faktur_belum_lunas || 0)} / ${Number(item.jumlah_faktur || 0)}`,
    tanggal_faktur_tertua_label: formatDate(item.tanggal_faktur_tertua)
  }))
);

const detailCards = computed(() => [
  { label: 'Faktur Belum Lunas', value: numberFormatter.format(detailSummary.jumlah_faktur || 0) },
  { label: 'Tagihan', value: formatCurrency(detailSummary.total_tagihan) },
  { label: 'Bayar + CN', value: formatCurrency(Number(detailSummary.total_bayar || 0) + Number(detailSummary.total_cn || 0)), tone: 'text-emerald-700 dark:text-emerald-300' },
  { label: 'Saldo Piutang', value: formatCurrency(detailSummary.saldo_piutang), tone: 'text-rose-700 dark:text-rose-300' }
]);

const detailTableRows = computed(() =>
  detailRows.value.map((item) => ({
    ...item,
    tanggal_order_label: formatDate(item.tanggal_order),
    tanggal_faktur_label: formatDate(item.tanggal_faktur),
    tanggal_jatuh_tempo_label: formatDate(item.tanggal_jatuh_tempo),
    total_penjualan_label: formatCurrency(item.total_penjualan),
    nominal_retur_label: formatCurrency(item.nominal_retur),
    total_bayar_label: formatCurrency(item.total_bayar),
    total_voucher_label: formatCurrency(item.total_voucher),
    outstanding_label: formatCurrency(item.outstanding),
    status_bayar_label: formatPaymentStatus(item.status_bayar)
  }))
);

const columns = [
  { key: 'kode_customer', label: 'Kode' },
  { key: 'nama_customer', label: 'Customer' },
  { key: 'nama_cabang', label: 'Cabang' },
  { key: 'nama_perusahaan', label: 'Perusahaan' },
  { key: 'principal_list', label: 'Principal' },
  { key: 'jumlah_faktur_label', label: 'Faktur BL/Lunas' },
  { key: 'tanggal_faktur_tertua_label', label: 'Faktur Tertua' },
  { key: 'total_tagihan_label', label: 'Tagihan' },
  { key: 'total_bayar_label', label: 'Bayar' },
  { key: 'total_cn_label', label: 'CN' },
  { key: 'saldo_piutang_label', label: 'Saldo Piutang' }
];

const detailColumns = [
  { key: 'no_faktur', label: 'No Faktur' },
  { key: 'no_order', label: 'No Order' },
  { key: 'nama_principal', label: 'Principal' },
  { key: 'tanggal_order_label', label: 'Tanggal Order' },
  { key: 'tanggal_jatuh_tempo_label', label: 'Jatuh Tempo' },
  { key: 'total_penjualan_label', label: 'Tagihan' },
  { key: 'nominal_retur_label', label: 'Retur' },
  { key: 'total_bayar_label', label: 'Bayar' },
  { key: 'total_voucher_label', label: 'CN' },
  { key: 'outstanding_label', label: 'Sisa' },
  { key: 'status_bayar_label', label: 'Status' }
];

function formatCurrency(value) {
  return `Rp ${numberFormatter.format(Number(value || 0))}`;
}

function formatDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10);
  return date.toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' });
}

function formatPaymentStatus(value) {
  const status = String(value || '').toLowerCase();
  if (status === 'paid') return 'Lunas';
  if (status === 'partial') return 'Dibayar Sebagian';
  if (status === 'unpaid') return 'Belum Bayar';
  return value || '-';
}

async function loadReferences() {
  loading.refs = true;
  try {
    const [branchResponse, companyResponse, principalResponse] = await Promise.all([getBranches(), getCompanies(), getPrincipals()]);
    branches.value = normalizeList(unwrapResponse(branchResponse));
    companies.value = normalizeList(unwrapResponse(companyResponse));
    principals.value = normalizeList(unwrapResponse(principalResponse));
    if (!canAccessAllBranches.value && fallbackBranchId.value) filters.id_cabang = String(fallbackBranchId.value);
    if (fallbackCompanyId.value) filters.id_perusahaan = String(fallbackCompanyId.value);
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Referensi saldo piutang belum bisa dimuat.');
  } finally {
    loading.refs = false;
  }
}

async function loadRows() {
  loading.list = true;
  errorMessage.value = '';
  try {
    const response = await getCustomerReceivableBalances({
      id_cabang: filters.id_cabang || undefined,
      id_perusahaan: filters.id_perusahaan || undefined,
      id_principal: filters.id_principal || undefined,
      search: filters.search || undefined
    });
    const payload = unwrapResponse(response);
    rows.value = normalizeList(payload);
    Object.assign(summary, response?.data?.summary || payload?.summary || {});
  } catch (error) {
    rows.value = [];
    errorMessage.value = normalizeError(error, 'Saldo piutang customer belum bisa dimuat.');
  } finally {
    loading.list = false;
  }
}

async function openDetail(row) {
  selectedCustomer.value = row;
  detailOpen.value = true;
  detailRows.value = [];
  detailErrorMessage.value = '';
  Object.assign(detailSummary, {
    jumlah_faktur: 0,
    total_tagihan: 0,
    total_retur: 0,
    total_bayar: 0,
    total_cn: 0,
    saldo_piutang: 0
  });

  loading.detail = true;
  try {
    const response = await getCustomerReceivableInvoices({
      id_customer: row.id_customer,
      id_cabang: filters.id_cabang || row.id_cabang || undefined,
      id_perusahaan: filters.id_perusahaan || row.id_perusahaan || undefined,
      id_principal: filters.id_principal || undefined,
      search: filters.search || undefined
    });
    const payload = unwrapResponse(response);
    detailRows.value = normalizeList(payload);
    Object.assign(detailSummary, response?.data?.summary || payload?.summary || {});
  } catch (error) {
    detailRows.value = [];
    detailErrorMessage.value = normalizeError(error, 'Detail piutang customer belum bisa dimuat.');
  } finally {
    loading.detail = false;
  }
}

function closeDetail() {
  detailOpen.value = false;
  selectedCustomer.value = null;
  detailRows.value = [];
  detailErrorMessage.value = '';
}

function resetFilters() {
  filters.search = '';
  filters.id_principal = '';
  filters.id_perusahaan = fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
  filters.id_cabang = !canAccessAllBranches.value && fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  loadRows();
}

onMounted(async () => {
  await loadReferences();
  await loadRows();
});
</script>

<template>
  <section class="space-y-6">
    <PageHeader
      title="Piutang Customer"
      description="Saldo piutang dari faktur terkirim, retur, Credit Note, dan pembayaran yang telah disahkan."
    >
      <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-semibold text-white" @click="loadRows">Reload</button>
    </PageHeader>

    <section class="panel p-5">
      <div class="grid gap-4 lg:grid-cols-5">
        <AppSearchSelect v-model="filters.id_perusahaan" label="Perusahaan" :options="companyOptions" placeholder="Semua perusahaan" />
        <AppSearchSelect v-model="filters.id_cabang" label="Cabang" :options="branchOptions" :disabled="!filters.id_perusahaan || (!canAccessAllBranches && !!fallbackBranchId)" placeholder="Semua cabang" />
        <AppSearchSelect v-model="filters.id_principal" label="Principal" :options="principalOptions" :disabled="!filters.id_perusahaan" placeholder="Semua principal" />
        <label class="block">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Cari</span>
          <input v-model="filters.search" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm outline-none dark:border-slate-700 dark:bg-slate-950" placeholder="Customer, kode, faktur..." @keyup.enter="loadRows" />
        </label>
        <div class="flex items-end gap-3">
          <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-semibold text-white" :disabled="loading.list" @click="loadRows">Terapkan</button>
          <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 dark:border-slate-700 dark:text-slate-200" @click="resetFilters">Reset</button>
        </div>
      </div>
    </section>

    <p class="text-sm text-slate-600 dark:text-slate-300">
      Faktur gabungan dihitung satu kali. Filter Principal tetap menampilkan total nota utuh beserta seluruh principal pada nota tersebut.
    </p>
    <p v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ errorMessage }}</p>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <article v-for="card in cards" :key="card.label" class="panel p-5">
        <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">{{ card.label }}</p>
        <p :class="['mt-3 text-xl font-bold text-slate-950 dark:text-white', card.tone]">{{ card.value }}</p>
      </article>
    </section>

    <AppTable
      :rows="tableRows"
      :columns="columns"
      :loading="loading.list || loading.refs"
      :clickable-rows="true"
      row-key="id_customer"
      empty-message="Tidak ada saldo piutang customer untuk filter ini."
      @row-click="openDetail"
    />

    <AppModal
      :open="detailOpen"
      :title="selectedCustomer ? `Detail Piutang ${selectedCustomer.nama_customer || selectedCustomer.kode_customer || 'Customer'}` : 'Detail Piutang Customer'"
      description="Daftar faktur yang masih memiliki sisa tagihan berdasarkan filter Piutang Customer."
      size="6xl"
      @close="closeDetail"
    >
      <div class="space-y-5">
        <section v-if="selectedCustomer" class="grid gap-3 md:grid-cols-4">
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-950">
            <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">Customer</p>
            <p class="mt-2 font-semibold text-slate-950 dark:text-white">{{ selectedCustomer.kode_customer || '-' }} - {{ selectedCustomer.nama_customer || '-' }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-950">
            <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">Cabang</p>
            <p class="mt-2 font-semibold text-slate-950 dark:text-white">{{ selectedCustomer.nama_cabang || '-' }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-950">
            <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">Perusahaan</p>
            <p class="mt-2 font-semibold text-slate-950 dark:text-white">{{ selectedCustomer.nama_perusahaan || '-' }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-950">
            <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">Principal</p>
            <p class="mt-2 font-semibold text-slate-950 dark:text-white">{{ selectedCustomer.principal_list || '-' }}</p>
          </div>
        </section>

        <p v-if="detailErrorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200">
          {{ detailErrorMessage }}
        </p>

        <section class="grid gap-3 md:grid-cols-4">
          <article v-for="card in detailCards" :key="card.label" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-950">
            <p class="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">{{ card.label }}</p>
            <p :class="['mt-2 text-lg font-bold text-slate-950 dark:text-white', card.tone]">{{ card.value }}</p>
          </article>
        </section>

        <AppTable
          :rows="detailTableRows"
          :columns="detailColumns"
          :loading="loading.detail"
          row-key="id_faktur"
          :default-page-size="10"
          empty-message="Tidak ada faktur belum lunas untuk customer ini."
        />
      </div>
    </AppModal>
  </section>
</template>
