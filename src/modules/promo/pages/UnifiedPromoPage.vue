<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies, getCustomers, getPrincipals, getProductBrands, getProductOptionsByPrincipal, getProductSubbrands } from '@/api/master';
import { createUnifiedPromo, deleteUnifiedPromo, getUnifiedPromoRuleUomOptions, getUnifiedPromos, setUnifiedPromoStatus, updateUnifiedPromo } from '@/api/promo';
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
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const auth = useAuthStore();
const today = toLocalDateInputValue();

const filters = reactive({
  branch: '',
  company: '',
  principal: '',
  status: 'active',
  search: ''
});

const form = reactive({
  id: '',
  kode_promo: '',
  nama_promo: '',
  promo_type: 'discount',
  benefit_scope: 'invoice',
  id_cabang: '',
  id_perusahaan: '',
  id_principal: '',
  id_customer: '',
  customer_target_mode: 'all',
  target_customer_ids: [],
  budget_limit: 0,
  periode_mulai: today,
  periode_selesai: today,
  status: 'active',
  keterangan: '',
  rules: []
});

const branches = ref([]);
const companies = ref([]);
const principals = ref([]);
const customers = ref([]);
const products = ref([]);
const brands = ref([]);
const subbrands = ref([]);
const rows = ref([]);
const selectedRow = ref(null);
const loading = ref(false);
const saving = ref(false);
const statusChangingId = ref('');
const error = ref('');
const feedback = ref('');
const hydratingForm = ref(false);
const formModalOpen = ref(false);
const customerTargetSearch = ref('');
const ruleUomStates = ref({});
let ruleUomRequestVersion = 0;

const programUsageCount = computed(() => Number(selectedRow.value?.usage_count || 0));
const isProgramLocked = computed(() => Boolean(form.id) && programUsageCount.value > 0);

const canAccessAllBranches = computed(() => canAccessAllPromoBranches(auth));
const branchOptions = computed(() => getPromoBranchOptions(branches.value, auth));
const filterCompanyOptions = computed(() => getPromoCompanyOptions(companies.value, branches.value, filters.branch));
const filterPrincipalOptions = computed(() => getPromoPrincipalOptions(principals.value, filters.company));
const formCompanyOptions = computed(() => getPromoCompanyOptions(companies.value, branches.value, form.id_cabang));
const formPrincipalOptions = computed(() => getPromoPrincipalOptions(principals.value, form.id_perusahaan));
const customerOptions = computed(() =>
  normalizeList(customers.value)
    .filter((item) => !form.id_cabang || String(item.id_cabang || item.cabang_id || '') === String(form.id_cabang))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || '-'} - ${item.nama || 'Customer'}`
    }))
);
const customerTargetOptions = computed(() =>
  customerOptions.value.filter((item) => {
    const keyword = customerTargetSearch.value.trim().toLowerCase();
    if (!keyword) return true;
    return item.label.toLowerCase().includes(keyword);
  })
);
const selectedCustomerTargets = computed(() => {
  const selected = new Set((form.target_customer_ids || []).map((item) => String(item)));
  return customerOptions.value.filter((item) => selected.has(String(item.value)));
});
const productOptions = computed(() =>
  products.value.map((item) => ({
    value: String(item.id || item.id_produk),
    label: `${item.kode_sku || item.kode || '-'} - ${item.nama || item.nama_produk || 'Produk'}`
  }))
);
const brandOptions = computed(() =>
  brands.value.map((item) => ({ value: String(item.id), label: item.nama || item.name || `Brand ${item.id}` }))
);
const subbrandOptions = computed(() =>
  subbrands.value.map((item) => ({ value: String(item.id), label: item.nama || item.name || `Sub-brand ${item.id}` }))
);

const statusOptions = [
  { value: 'active', label: 'Aktif' },
  { value: 'draft', label: 'Draft' },
  { value: 'inactive', label: 'Tidak aktif' },
  { value: 'all', label: 'Semua status' }
];

const promoTypeOptions = [
  { value: 'discount', label: 'Diskon Invoice' },
  { value: 'cashback', label: 'Cashback' },
  { value: 'free_product', label: 'Bonus Produk' }
];

const customerTargetModeOptions = [
  { value: 'all', label: 'Semua Customer' },
  { value: 'selected', label: 'Pilih Customer' }
];

const targetTypeOptions = [
  { value: 'all', label: 'Semua barang' },
  { value: 'product', label: 'Produk tertentu' },
  { value: 'brand', label: 'Brand' },
  { value: 'subbrand', label: 'Sub-brand' },
  { value: 'principal', label: 'Principal' },
  { value: 'customer', label: 'Customer' }
];

const benefitTypeOptions = [
  { value: 'percent', label: 'Persen (%)' },
  { value: 'nominal', label: 'Rupiah flat' },
  { value: 'nominal_per_qty', label: 'Rupiah per jumlah' },
  { value: 'free_product', label: 'Bonus produk' }
];

const summary = computed(() => ({
  total: rows.value.length,
  active: rows.value.filter((item) => item.status === 'active').length,
  rules: rows.value.reduce((sum, item) => sum + Number(item.total_rules || item.rules?.length || 0), 0),
  budget: rows.value.reduce((sum, item) => sum + Number(item.budget_limit || 0), 0)
}));

function formatCurrency(value) {
  return new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(Number(value || 0));
}

function isProgramActive(row) {
  return String(row?.status || '').trim().toLowerCase() === 'active';
}

function customerScopeLabel(row) {
  const total = Number(row.total_target_customer || row.target_customer_ids?.length || 0);
  if (total > 1) return `${total} customer terpilih`;
  if (total === 1) return row.nama_customer || row.nama_target_customers || '1 customer terpilih';
  return row.nama_customer || 'Semua customer';
}

function emptyRule() {
  return {
    nama_rule: '',
    target_type: 'subbrand',
    id_produk: '',
    id_brand: '',
    id_subbrand: '',
    id_principal: '',
    id_customer: '',
    qty_uom: '',
    min_qty: 0,
    max_qty: '',
    min_subtotal: 0,
    max_subtotal: '',
    benefit_type: 'percent',
    benefit_value: 0,
    free_product_id: '',
    free_qty: 0,
    priority: 0
  };
}

async function resetForm() {
  hydratingForm.value = true;
  ruleUomStates.value = {};
  Object.assign(form, {
    id: '',
    kode_promo: '',
    nama_promo: '',
    promo_type: 'discount',
    benefit_scope: 'invoice',
    id_cabang: filters.branch || '',
    id_perusahaan: filters.company || '',
    id_principal: filters.principal || '',
    id_customer: '',
    customer_target_mode: 'all',
    target_customer_ids: [],
    budget_limit: 0,
    periode_mulai: today,
    periode_selesai: today,
    status: 'active',
    keterangan: '',
    rules: [emptyRule(), { ...emptyRule(), min_qty: 5, benefit_value: 2 }, { ...emptyRule(), min_qty: 10, benefit_value: 3 }]
  });
  customerTargetSearch.value = '';
  selectedRow.value = null;
  await nextTick();
  hydratingForm.value = false;
  await refreshRuleUomOptions();
}

function normalizeRule(row = {}) {
  return {
    ...emptyRule(),
    ...row,
    id_produk: row.id_produk ? String(row.id_produk) : '',
    id_brand: row.id_brand ? String(row.id_brand) : '',
    id_subbrand: row.id_subbrand ? String(row.id_subbrand) : '',
    id_principal: row.id_principal ? String(row.id_principal) : '',
    id_customer: row.id_customer ? String(row.id_customer) : '',
    free_product_id: row.free_product_id ? String(row.free_product_id) : '',
    max_qty: row.max_qty ?? '',
    max_subtotal: row.max_subtotal ?? ''
  };
}

async function editRow(row) {
  hydratingForm.value = true;
  ruleUomStates.value = {};
  selectedRow.value = row;
  formModalOpen.value = true;
  const targetCustomerIds = normalizeList(row.target_customer_ids || row.customer_targets)
    .map((item) => (typeof item === 'object' ? item.id_customer || item.id : item))
    .filter(Boolean)
    .map((item) => String(item));
  if (!targetCustomerIds.length && row.id_customer) {
    targetCustomerIds.push(String(row.id_customer));
  }
  Object.assign(form, {
    id: row.id,
    kode_promo: row.kode_promo || '',
    nama_promo: row.nama_promo || '',
    promo_type: row.promo_type || 'discount',
    benefit_scope: row.benefit_scope || 'invoice',
    id_cabang: row.id_cabang ? String(row.id_cabang) : '',
    id_perusahaan: row.id_perusahaan ? String(row.id_perusahaan) : '',
    id_principal: row.id_principal ? String(row.id_principal) : '',
    id_customer: '',
    customer_target_mode: targetCustomerIds.length ? 'selected' : 'all',
    target_customer_ids: targetCustomerIds,
    budget_limit: Number(row.budget_limit || 0),
    periode_mulai: row.periode_mulai || today,
    periode_selesai: row.periode_selesai || today,
    status: row.status || 'active',
    keterangan: row.keterangan || '',
    rules: normalizeList(row.rules).map(normalizeRule)
  });
  if (!form.rules.length) {
    form.rules = [emptyRule()];
  }
  await nextTick();
  hydratingForm.value = false;
  await refreshRuleUomOptions();
}

async function openCreatePromo() {
  await resetForm();
  formModalOpen.value = true;
}

function closeFormModal() {
  formModalOpen.value = false;
}

function addRule() {
  form.rules.push({ ...emptyRule(), priority: form.rules.length });
}

function removeRule(index) {
  form.rules.splice(index, 1);
  if (!form.rules.length) addRule();
}

function toggleCustomerTarget(customerId) {
  const key = String(customerId);
  const selected = new Set((form.target_customer_ids || []).map((item) => String(item)));
  if (selected.has(key)) {
    selected.delete(key);
  } else {
    selected.add(key);
  }
  form.target_customer_ids = Array.from(selected);
}

function targetOptions(rule) {
  if (rule.target_type === 'product') return productOptions.value;
  if (rule.target_type === 'brand') return brandOptions.value;
  if (rule.target_type === 'subbrand') return subbrandOptions.value;
  if (rule.target_type === 'principal') return formPrincipalOptions.value;
  if (rule.target_type === 'customer') return customerOptions.value;
  return [];
}

function targetModel(rule) {
  if (rule.target_type === 'product') return 'id_produk';
  if (rule.target_type === 'brand') return 'id_brand';
  if (rule.target_type === 'subbrand') return 'id_subbrand';
  if (rule.target_type === 'principal') return 'id_principal';
  if (rule.target_type === 'customer') return 'id_customer';
  return '';
}

function clearRuleTarget(rule) {
  rule.id_produk = '';
  rule.id_brand = '';
  rule.id_subbrand = '';
  rule.id_principal = '';
  rule.id_customer = '';
  rule.qty_uom = '';
}

function fallbackQtyUomLabel(value) {
  if (value === 'piece' || value === 'pieces' || value === 'pcs') return 'PCS';
  if (value === 'box' || value === 'dus') return 'Box';
  if (value === 'karton' || value === 'carton' || value === 'ctn') return 'Karton';
  return value || 'UOM';
}

function ruleUomState(index) {
  return ruleUomStates.value[index] || { available_uoms: [], message: '', loading: false };
}

function ruleUomOptions(rule, index) {
  const options = normalizeList(ruleUomState(index).available_uoms);
  if (!rule.qty_uom || options.some((item) => String(item.value) === String(rule.qty_uom))) {
    return options;
  }
  return [
    { value: rule.qty_uom, label: `${fallbackQtyUomLabel(rule.qty_uom)} (tersimpan)` },
    ...options
  ];
}

function ruleUomHint(index) {
  const state = ruleUomState(index);
  if (state.loading) return 'Memuat UOM dari Master Produk...';
  return state.message || 'Pilih Principal dan target rule untuk memuat UOM dari Master Produk.';
}

async function refreshRuleUomOptions() {
  const requestVersion = ++ruleUomRequestVersion;
  const ruleSnapshots = form.rules.map((rule) => ({
    target_type: rule.target_type,
    id_produk: rule.id_produk,
    id_brand: rule.id_brand,
    id_subbrand: rule.id_subbrand,
    id_principal: rule.id_principal,
    id_customer: rule.id_customer
  }));

  if (!ruleSnapshots.length) {
    ruleUomStates.value = {};
    return;
  }

  ruleUomStates.value = Object.fromEntries(ruleSnapshots.map((_, index) => [
    index,
    { ...ruleUomState(index), loading: true }
  ]));

  const results = await Promise.all(ruleSnapshots.map(async (rule, index) => {
    try {
      const response = await getUnifiedPromoRuleUomOptions({
        program: { id_principal: form.id_principal || null },
        rule
      });
      return [index, { ...(unwrapResponse(response) || {}), loading: false }];
    } catch (err) {
      return [index, {
        available_uoms: [],
        message: normalizeError(err, 'UOM Master Produk belum dapat dimuat.'),
        loading: false
      }];
    }
  }));

  if (requestVersion !== ruleUomRequestVersion) return;

  const nextStates = Object.fromEntries(results);
  ruleUomStates.value = nextStates;
  if (isProgramLocked.value) return;

  form.rules.forEach((rule, index) => {
    const options = normalizeList(nextStates[index]?.available_uoms);
    if (!form.id && options.length && !rule.qty_uom) {
      rule.qty_uom = options[0].value;
    }
  });
}

function buildPayload() {
  const targetCustomerIds = form.customer_target_mode === 'selected'
    ? (form.target_customer_ids || []).map((item) => Number(item)).filter(Boolean)
    : [];
  return {
    ...form,
    id_customer: '',
    target_customer_ids: targetCustomerIds,
    rules: form.rules.map((rule, index) => ({
      ...rule,
      priority: Number(rule.priority || index)
    }))
  };
}

async function loadReferences() {
  const [branchResponse, companyResponse, principalResponse, customerResponse, brandResponse, subbrandResponse] = await Promise.all([
    getBranches(),
    getCompanies(),
    getPrincipals(),
    getCustomers(),
    getProductBrands(),
    getProductSubbrands()
  ]);
  branches.value = normalizeList(unwrapResponse(branchResponse));
  companies.value = normalizeList(unwrapResponse(companyResponse));
  principals.value = normalizeList(unwrapResponse(principalResponse));
  customers.value = normalizeList(unwrapResponse(customerResponse));
  brands.value = normalizeList(unwrapResponse(brandResponse));
  subbrands.value = normalizeList(unwrapResponse(subbrandResponse));
  if (!canAccessAllBranches.value && getPromoFallbackBranchId(auth)) {
    filters.branch = String(getPromoFallbackBranchId(auth));
  }
  await resetForm();
}

async function loadProducts() {
  if (!form.id_principal) {
    products.value = [];
    return;
  }
  const response = await getProductOptionsByPrincipal(form.id_principal);
  products.value = normalizeList(unwrapResponse(response));
}

async function loadRows() {
  loading.value = true;
  error.value = '';
  try {
    const response = await getUnifiedPromos({
      id_cabang: filters.branch,
      id_perusahaan: filters.company,
      id_principal: filters.principal,
      status: filters.status,
      search: filters.search
    });
    rows.value = normalizeList(unwrapResponse(response));
  } catch (err) {
    error.value = normalizeError(err, 'Daftar promo all-in belum bisa dimuat.');
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

async function submitForm() {
  saving.value = true;
  error.value = '';
  feedback.value = '';
  try {
    if (isProgramLocked.value) {
      error.value = `Promo ini sudah dipakai pada ${programUsageCount.value} transaksi dan tidak dapat diubah.`;
      return;
    }
    if (form.customer_target_mode === 'selected' && !form.target_customer_ids.length) {
      error.value = 'Pilih minimal satu customer, atau ubah Target Customer menjadi Semua Customer.';
      return;
    }
    if (form.rules.some((_, index) => ruleUomState(index).loading)) {
      error.value = 'Tunggu UOM dari Master Produk selesai dimuat sebelum menyimpan promo.';
      return;
    }
    const missingUomRule = form.rules.find((rule) => !rule.qty_uom);
    if (missingUomRule) {
      error.value = 'Pilih UOM syarat yang tersedia dari Master Produk pada setiap rule.';
      return;
    }
    const unsupportedUomRule = form.rules.find((rule, index) => {
      const available = normalizeList(ruleUomState(index).available_uoms);
      return available.length && !available.some((item) => String(item.value) === String(rule.qty_uom));
    });
    if (unsupportedUomRule) {
      error.value = 'Ada UOM rule yang tidak tersedia pada seluruh produk dalam scope. Pilih salah satu UOM yang ditawarkan.';
      return;
    }
    const payload = buildPayload();
    const response = form.id ? await updateUnifiedPromo(form.id, payload) : await createUnifiedPromo(payload);
    feedback.value = unwrapResponse(response)?.message || 'Promo all-in berhasil disimpan.';
    await loadRows();
    await resetForm();
    formModalOpen.value = false;
  } catch (err) {
    error.value = normalizeError(err, 'Promo all-in belum berhasil disimpan.');
  } finally {
    saving.value = false;
  }
}

async function removeProgram(row) {
  if (Number(row?.usage_count || 0) > 0) {
    error.value = `Promo ${row.kode_promo} sudah dipakai dan tidak dapat dihapus.`;
    return;
  }
  const confirmed = window.confirm(`Hapus promo ${row.kode_promo}? Data akan disembunyikan dari promo aktif.`);
  if (!confirmed) return;
  try {
    await deleteUnifiedPromo(row.id);
    feedback.value = 'Promo all-in berhasil dihapus.';
    await loadRows();
    if (String(form.id) === String(row.id)) {
      await resetForm();
      formModalOpen.value = false;
    }
  } catch (err) {
    error.value = normalizeError(err, 'Promo all-in belum berhasil dihapus.');
  }
}

async function changeProgramStatus(row) {
  if (!row?.id) return;

  const nextStatus = isProgramActive(row) ? 'inactive' : 'active';
  const action = nextStatus === 'inactive' ? 'nonaktifkan' : 'aktifkan';
  const confirmed = window.confirm(
    `${action.charAt(0).toUpperCase()}${action.slice(1)} promo ${row.kode_promo}? `
      + 'Konfigurasi dan riwayat pemakaian tidak akan diubah.'
  );
  if (!confirmed) return;

  error.value = '';
  feedback.value = '';
  statusChangingId.value = String(row.id);
  try {
    const response = await setUnifiedPromoStatus(row.id, { status: nextStatus });
    feedback.value = unwrapResponse(response)?.message || `Promo all-in berhasil di${action}.`;
    await loadRows();

    const refreshed = rows.value.find((item) => String(item.id) === String(row.id));
    if (refreshed && String(form.id) === String(row.id)) {
      selectedRow.value = refreshed;
      form.status = refreshed.status || nextStatus;
    }
  } catch (err) {
    error.value = normalizeError(err, `Promo all-in belum berhasil di${action}.`);
  } finally {
    statusChangingId.value = '';
  }
}

function updateFilterBranch(value) {
  filters.branch = value;
  filters.company = '';
  filters.principal = '';
}

function updateFilterCompany(value) {
  filters.company = value;
  filters.principal = '';
}

watch(
  () => form.id_cabang,
  () => {
    if (hydratingForm.value) return;
    form.id_perusahaan = '';
    form.id_principal = '';
    form.id_customer = '';
    form.target_customer_ids = [];
    customerTargetSearch.value = '';
    products.value = [];
  }
);

watch(
  () => form.id_perusahaan,
  () => {
    if (hydratingForm.value) return;
    form.id_principal = '';
    products.value = [];
  }
);

watch(
  () => form.id_principal,
  () => {
    loadProducts();
  }
);

const ruleUomScopeSignature = computed(() => JSON.stringify({
  id_principal: form.id_principal,
  rules: form.rules.map((rule) => ({
    target_type: rule.target_type,
    id_produk: rule.id_produk,
    id_brand: rule.id_brand,
    id_subbrand: rule.id_subbrand,
    id_principal: rule.id_principal,
    id_customer: rule.id_customer
  }))
}));

watch(ruleUomScopeSignature, () => {
  if (!hydratingForm.value) {
    refreshRuleUomOptions();
  }
});

watch(
  () => form.customer_target_mode,
  (mode) => {
    if (hydratingForm.value) return;
    if (mode === 'all') {
      form.target_customer_ids = [];
      customerTargetSearch.value = '';
    }
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
      title="Promo All-In"
      description="Satu tempat untuk voucher, diskon produk, cashback bertingkat, bonus produk, budget, dan periode promo."
    />

    <section class="grid gap-4 md:grid-cols-4">
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Total Program</p>
        <p class="mt-3 text-2xl font-semibold text-slate-900 dark:text-white">{{ summary.total }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Aktif</p>
        <p class="mt-3 text-2xl font-semibold text-emerald-600 dark:text-emerald-300">{{ summary.active }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Rule Bertingkat</p>
        <p class="mt-3 text-2xl font-semibold text-slate-900 dark:text-white">{{ summary.rules }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Budget</p>
        <p class="mt-3 text-2xl font-semibold text-slate-900 dark:text-white">{{ formatCurrency(summary.budget) }}</p>
      </article>
    </section>

    <section class="panel p-5">
      <div class="grid gap-4 lg:grid-cols-5">
        <AppSearchSelect :model-value="filters.branch" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="!canAccessAllBranches" @update:model-value="updateFilterBranch" />
        <AppSearchSelect :model-value="filters.company" label="Perusahaan" placeholder="Pilih perusahaan" :options="filterCompanyOptions" :disabled="!filters.branch" @update:model-value="updateFilterCompany" />
        <AppSearchSelect v-model="filters.principal" label="Principal" placeholder="Pilih principal" :options="filterPrincipalOptions" :disabled="!filters.company" />
        <AppSearchSelect v-model="filters.status" label="Status" placeholder="Pilih status" :options="statusOptions" />
        <AppFormField v-model="filters.search" label="Cari" placeholder="Kode, nama, catatan" />
      </div>
      <div class="mt-4 flex flex-wrap gap-2">
        <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700" type="button" @click="loadRows">Terapkan</button>
        <button class="rounded-xl border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800" type="button" @click="resetForm">Promo Baru</button>
      </div>
    </section>

    <section v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-400/30 dark:bg-emerald-500/10 dark:text-emerald-100">
      {{ feedback }}
    </section>
    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-400/30 dark:bg-rose-500/10 dark:text-rose-100">
      {{ error }}
    </section>

    <section class="panel overflow-hidden">
      <div class="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-4 dark:border-slate-800">
        <div>
          <h3 class="text-lg font-semibold text-slate-900 dark:text-white">Daftar Promo</h3>
          <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">Area daftar dibuat full-width. Klik baris untuk membuka modal edit rule dan strata.</p>
        </div>
        <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700" type="button" @click="openCreatePromo">
          Tambah Promo
        </button>
      </div>

      <div v-if="loading" class="p-5 text-sm text-slate-500 dark:text-slate-400">Memuat promo...</div>
      <div v-else-if="rows.length" class="overflow-x-auto">
        <table class="min-w-[1180px] w-full text-left text-sm">
          <thead class="bg-slate-50 text-xs uppercase tracking-[0.16em] text-slate-500 dark:bg-slate-950/60 dark:text-slate-400">
            <tr>
              <th class="px-5 py-4">Program</th>
              <th class="px-5 py-4">Scope</th>
              <th class="px-5 py-4">Tipe</th>
              <th class="px-5 py-4">Periode</th>
              <th class="px-5 py-4 text-right">Budget</th>
              <th class="px-5 py-4 text-center">Rule</th>
              <th class="px-5 py-4">Status</th>
              <th class="px-5 py-4 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-200 dark:divide-slate-800">
            <tr v-for="row in rows" :key="row.id" class="transition hover:bg-slate-50 dark:hover:bg-slate-800/60">
              <td class="px-5 py-4 align-top">
                <p class="font-semibold text-slate-900 dark:text-white">{{ row.kode_promo }}</p>
                <p class="mt-1 max-w-md text-slate-500 dark:text-slate-400">{{ row.nama_promo }}</p>
              </td>
              <td class="px-5 py-4 align-top">
                <p class="font-semibold text-slate-700 dark:text-slate-200">{{ row.nama_principal || 'Semua principal' }}</p>
                <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">{{ customerScopeLabel(row) }}</p>
                <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">{{ row.nama_cabang || 'Semua cabang' }} | {{ row.nama_perusahaan || 'Semua perusahaan' }}</p>
                <p v-if="Number(row.usage_count || 0) > 0" class="mt-1 text-xs font-semibold text-amber-600 dark:text-amber-300">
                  Sudah dipakai {{ Number(row.usage_count) }} transaksi · terkunci
                </p>
              </td>
              <td class="px-5 py-4 align-top">
                <div class="flex flex-wrap gap-2">
                  <span class="rounded-full border border-slate-200 px-2.5 py-1 text-xs font-semibold text-slate-600 dark:border-slate-700 dark:text-slate-300">{{ row.promo_type }}</span>
                  <span class="rounded-full border border-slate-200 px-2.5 py-1 text-xs font-semibold text-slate-600 dark:border-slate-700 dark:text-slate-300">{{ row.benefit_scope }}</span>
                </div>
              </td>
              <td class="px-5 py-4 align-top text-slate-600 dark:text-slate-300">
                {{ row.periode_mulai || '-' }}<br />
                <span class="text-xs text-slate-400">s/d</span> {{ row.periode_selesai || '-' }}
              </td>
              <td class="px-5 py-4 align-top text-right font-semibold text-slate-900 dark:text-white">{{ formatCurrency(row.budget_limit) }}</td>
              <td class="px-5 py-4 align-top text-center">
                <span class="rounded-full bg-brand-50 px-3 py-1 text-xs font-bold text-brand-700 dark:bg-brand-400/10 dark:text-brand-200">
                  {{ Number(row.total_rules || row.rules?.length || 0) }}
                </span>
              </td>
              <td class="px-5 py-4 align-top">
                <span :class="[
                  'rounded-full px-3 py-1 text-xs font-semibold',
                  isProgramActive(row)
                    ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-400/10 dark:text-emerald-200'
                    : 'bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-200'
                ]">{{ row.status }}</span>
              </td>
              <td class="px-5 py-4 align-top text-right">
                <div class="flex flex-wrap justify-end gap-2">
                  <button class="rounded-xl border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800" type="button" @click="editRow(row)">
                    Edit
                  </button>
                  <button
                    v-if="['active', 'inactive'].includes(String(row.status || '').toLowerCase())"
                    :class="[
                      'rounded-xl px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-60',
                      isProgramActive(row)
                        ? 'border border-amber-300 text-amber-700 hover:bg-amber-50 dark:border-amber-400/40 dark:text-amber-200 dark:hover:bg-amber-400/10'
                        : 'border border-emerald-300 text-emerald-700 hover:bg-emerald-50 dark:border-emerald-400/40 dark:text-emerald-200 dark:hover:bg-emerald-400/10'
                    ]"
                    type="button"
                    :disabled="String(statusChangingId) === String(row.id)"
                    @click="changeProgramStatus(row)"
                  >
                    {{ String(statusChangingId) === String(row.id) ? 'Memproses...' : (isProgramActive(row) ? 'Nonaktifkan' : 'Aktifkan') }}
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <AppEmptyState v-else title="Belum ada promo all-in" description="Buat program promo baru dari tombol Tambah Promo." />
    </section>

    <AppModal
      :open="formModalOpen"
      :title="form.id ? 'Edit Promo All-In' : 'Tambah Promo All-In'"
      :description="isProgramLocked ? `Promo sudah dipakai pada ${programUsageCount} transaksi. Konfigurasi dikunci untuk menjaga histori.` : 'Atur scope, periode, budget, lalu susun rule bertingkat dalam satu tempat.'"
      size="7xl"
      @close="closeFormModal"
    >
      <form class="space-y-5" @submit.prevent="submitForm">
        <section v-if="isProgramLocked" class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-400/30 dark:bg-amber-500/10 dark:text-amber-100">
          Promo ini sudah dipakai pada {{ programUsageCount }} transaksi. Scope, periode, budget, target customer, dan rule tidak dapat diubah. Promo tetap dapat dinonaktifkan atau diaktifkan kembali tanpa mengubah riwayat pemakaian.
        </section>
        <div class="grid gap-4 lg:grid-cols-3">
          <AppFormField v-model="form.kode_promo" label="Kode Promo" placeholder="PROMO-MKL-2026" :readonly="isProgramLocked" />
          <AppFormField v-model="form.nama_promo" label="Nama Promo" placeholder="Cashback MKL Bertingkat" :readonly="isProgramLocked" />
          <AppSearchSelect v-model="form.promo_type" label="Tipe Promo" :options="promoTypeOptions" :disabled="isProgramLocked" />
          <AppSearchSelect v-model="form.id_cabang" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="isProgramLocked" />
          <AppSearchSelect v-model="form.id_perusahaan" label="Perusahaan" placeholder="Pilih perusahaan" :options="formCompanyOptions" :disabled="isProgramLocked || !form.id_cabang" />
          <AppSearchSelect v-model="form.id_principal" label="Principal" placeholder="Pilih principal" :options="formPrincipalOptions" :disabled="isProgramLocked || !form.id_perusahaan" />
          <AppSearchSelect v-model="form.customer_target_mode" label="Target Customer" :options="customerTargetModeOptions" :disabled="isProgramLocked" />
          <AppSearchSelect v-model="form.status" label="Status" :options="statusOptions.filter((item) => item.value !== 'all')" :disabled="isProgramLocked" />
          <AppFormField v-model="form.budget_limit" label="Budget Promo" type="number" :readonly="isProgramLocked" />
          <AppFormField v-model="form.periode_mulai" label="Periode Mulai" type="date" :readonly="isProgramLocked" />
          <AppFormField v-model="form.periode_selesai" label="Periode Selesai" type="date" :readonly="isProgramLocked" />
          <AppFormField v-model="form.keterangan" label="Catatan" placeholder="Syarat umum promo" :readonly="isProgramLocked" />
        </div>

        <section v-if="form.customer_target_mode === 'selected'" class="rounded-2xl border border-slate-200 p-4 dark:border-slate-800">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h4 class="font-semibold text-slate-900 dark:text-white">Customer Target Promo</h4>
              <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
                Pilih satu atau beberapa customer. Jika dikosongkan, promo tidak akan berlaku ke customer mana pun pada mode ini.
              </p>
            </div>
            <span class="rounded-full bg-brand-50 px-3 py-1 text-xs font-bold text-brand-700 dark:bg-brand-400/10 dark:text-brand-200">
              {{ selectedCustomerTargets.length }} dipilih
            </span>
          </div>
          <div class="mt-4 grid gap-4 lg:grid-cols-[minmax(240px,0.8fr)_minmax(0,1.2fr)]">
            <div>
              <AppFormField v-model="customerTargetSearch" label="Cari Customer" placeholder="Kode atau nama customer" />
              <div class="mt-3 max-h-72 overflow-y-auto rounded-2xl border border-slate-200 dark:border-slate-700">
                <button
                  v-for="customer in customerTargetOptions"
                  :key="customer.value"
                  type="button"
                  class="flex w-full items-center gap-3 border-b border-slate-100 px-3 py-2 text-left text-sm last:border-b-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800"
                  :disabled="isProgramLocked"
                  @click="toggleCustomerTarget(customer.value)"
                >
                  <input
                    type="checkbox"
                    class="h-4 w-4 rounded border-slate-300 text-brand-600"
                    :checked="form.target_customer_ids.map(String).includes(String(customer.value))"
                    readonly
                  />
                  <span class="text-slate-700 dark:text-slate-200">{{ customer.label }}</span>
                </button>
                <p v-if="!customerTargetOptions.length" class="px-3 py-6 text-center text-sm text-slate-500 dark:text-slate-400">
                  Customer tidak ditemukan pada cabang ini.
                </p>
              </div>
            </div>
            <div class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
              <p class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Customer Terpilih</p>
              <div v-if="selectedCustomerTargets.length" class="mt-3 flex flex-wrap gap-2">
                <button
                  v-for="customer in selectedCustomerTargets"
                  :key="customer.value"
                  type="button"
                  class="rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-700 hover:bg-brand-100 dark:border-brand-400/30 dark:bg-brand-400/10 dark:text-brand-100"
                  :disabled="isProgramLocked"
                  @click="toggleCustomerTarget(customer.value)"
                >
                  {{ customer.label }} ×
                </button>
              </div>
              <p v-else class="mt-3 text-sm text-slate-500 dark:text-slate-400">
                Belum ada customer dipilih.
              </p>
            </div>
          </div>
        </section>

        <div class="rounded-2xl border border-slate-200 dark:border-slate-800">
          <div class="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3 dark:border-slate-800">
            <div>
              <h4 class="font-semibold text-slate-900 dark:text-white">Rule dan Strata</h4>
              <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">UOM syarat mengikuti Master Produk. Hanya satuan yang tersedia pada seluruh produk dalam scope rule yang dapat dipilih.</p>
            </div>
            <button class="rounded-xl border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800" type="button" :disabled="isProgramLocked" @click="addRule">Tambah Rule</button>
          </div>
          <div class="space-y-4 p-4">
            <article v-for="(rule, index) in form.rules" :key="index" class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
              <div class="mb-3 flex items-center justify-between gap-3">
                <p class="font-semibold text-slate-900 dark:text-white">Rule {{ index + 1 }}</p>
                <button class="text-sm font-semibold text-rose-600 disabled:cursor-not-allowed disabled:opacity-50 dark:text-rose-300" type="button" :disabled="isProgramLocked" @click="removeRule(index)">Hapus</button>
              </div>
              <div class="grid gap-3 lg:grid-cols-4">
                <AppFormField v-model="rule.nama_rule" label="Nama Rule" placeholder="Min. 2 BOX" :readonly="isProgramLocked" />
                <AppSearchSelect v-model="rule.target_type" label="Target" :options="targetTypeOptions" :disabled="isProgramLocked" @update:model-value="clearRuleTarget(rule)" />
                <AppSearchSelect
                  v-if="targetModel(rule)"
                  v-model="rule[targetModel(rule)]"
                  label="Data Target"
                  placeholder="Pilih target"
                  :options="targetOptions(rule)"
                  :disabled="isProgramLocked || targetOptions(rule).length === 0"
                />
                <AppSearchSelect
                  v-model="rule.qty_uom"
                  label="UOM Syarat"
                  placeholder="Pilih UOM master"
                  :options="ruleUomOptions(rule, index)"
                  :loading="ruleUomState(index).loading"
                  :disabled="isProgramLocked || ruleUomState(index).loading || !normalizeList(ruleUomState(index).available_uoms).length"
                />
                <AppFormField v-model="rule.min_qty" label="Minimal Qty" type="number" :readonly="isProgramLocked" />
                <AppFormField v-model="rule.max_qty" label="Maks Qty" type="number" placeholder="Kosong = unlimited" :readonly="isProgramLocked" />
                <AppFormField v-model="rule.min_subtotal" label="Minimal Subtotal" type="number" :readonly="isProgramLocked" />
                <AppSearchSelect v-model="rule.benefit_type" label="Benefit" :options="benefitTypeOptions" :disabled="isProgramLocked" />
                <AppFormField v-model="rule.benefit_value" label="Nilai Benefit" type="number" :readonly="isProgramLocked" />
                <AppSearchSelect v-if="rule.benefit_type === 'free_product'" v-model="rule.free_product_id" label="Produk Bonus" :options="productOptions" :disabled="isProgramLocked" />
                <AppFormField v-if="rule.benefit_type === 'free_product'" v-model="rule.free_qty" label="Qty Bonus" type="number" :readonly="isProgramLocked" />
                <AppFormField v-model="rule.priority" label="Prioritas" type="number" :readonly="isProgramLocked" />
                <p class="text-xs text-slate-500 dark:text-slate-400 lg:col-span-4">{{ ruleUomHint(index) }}</p>
              </div>
            </article>
          </div>
        </div>
      </form>

      <template #footer>
        <div class="flex flex-wrap justify-between gap-3">
          <button v-if="form.id && !isProgramLocked" class="rounded-xl border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-600 hover:bg-rose-50 dark:border-rose-400/40 dark:text-rose-200 dark:hover:bg-rose-500/10" type="button" @click="removeProgram(selectedRow)">Hapus</button>
          <button
            v-else-if="form.id && isProgramLocked && ['active', 'inactive'].includes(String(selectedRow?.status || form.status || '').toLowerCase())"
            :class="[
              'rounded-xl px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60',
              isProgramActive(selectedRow || form)
                ? 'border border-amber-300 text-amber-700 hover:bg-amber-50 dark:border-amber-400/40 dark:text-amber-200 dark:hover:bg-amber-400/10'
                : 'border border-emerald-300 text-emerald-700 hover:bg-emerald-50 dark:border-emerald-400/40 dark:text-emerald-200 dark:hover:bg-emerald-400/10'
            ]"
            type="button"
            :disabled="String(statusChangingId) === String(form.id)"
            @click="changeProgramStatus(selectedRow || form)"
          >
            {{ String(statusChangingId) === String(form.id) ? 'Memproses...' : (isProgramActive(selectedRow || form) ? 'Nonaktifkan Promo' : 'Aktifkan Promo') }}
          </button>
          <span v-else></span>
          <div class="flex gap-2">
            <button class="rounded-xl border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800" type="button" @click="resetForm">Reset</button>
            <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-60" type="button" :disabled="saving || isProgramLocked" @click="submitForm">
              {{ isProgramLocked ? 'Promo Terkunci' : (saving ? 'Menyimpan...' : 'Simpan Promo') }}
            </button>
          </div>
        </div>
      </template>
    </AppModal>
  </div>
</template>
