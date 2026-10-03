<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { createStockTransfer } from '@/api/stockTransfer';
import {
  getBranches,
  getCompanies,
  getProductDetail,
  getProductOptionsByPrincipal,
  getProductStockReady,
  getPrincipals
} from '@/api/master';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import {
  getLoginBranchId,
  getLoginCompanyId,
  getLoginBranchIds,
  isSuperUser
} from '@/utils/accessScope';
import { getCompanyIdsForBranch } from '@/utils/filterScope';
import { principalBelongsToTransferCompany } from '../companyScope';
import { useAuthStore } from '@/stores/auth';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const form = reactive({
  nota_stock_transfer: '',
  id_perusahaan_awal: '',
  id_cabang_awal: '',
  id_perusahaan_tujuan: '',
  id_cabang_tujuan: ''
});

const router = useRouter();
const productForm = reactive({
  id_principal: '',
  id_produk: '',
  uom_1: 0,
  uom_2: 0,
  uom_3: 0
});

const companyRows = ref([]);
const branchRows = ref([]);
const principalRows = ref([]);
const productRows = ref([]);
const products = ref([]);
const selectedStockReady = ref(null);
const selectedProductUoms = ref([]);
const productLoading = ref(false);
const productLoadError = ref('');
const productUomLoading = ref(false);
const productUomError = ref('');
const feedback = ref('');
const errorMessage = ref('');
const saving = ref(false);
let productUomRequestToken = 0;
let productOptionsRequestToken = 0;
const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(authStore.user));
const canAccessAllBranches = computed(() => isSuperUser(authStore));

function companyIdsForBranch(branchId) {
  return getCompanyIdsForBranch(branchId, branchRows.value, companyRows.value);
}

const scopedOriginBranches = computed(() => {
  const allowed = new Set(getLoginBranchIds(authStore.user));
  return branchRows.value.filter((branch) => canAccessAllBranches.value || !allowed.size ||
    allowed.has(String(branch.id || branch.id_cabang || branch.cabang_id)));
});

function companyOption(item) {
  const id = item?.id || item?.id_perusahaan || item?.company_id || '';
  const code = item?.kode || item?.kode_perusahaan || '';
  const name = item?.nama || item?.nama_perusahaan || `Perusahaan ${id}`;
  return {
    value: String(id),
    label: code ? `${code} - ${name}` : name
  };
}

function branchOption(item) {
  const id = item?.id || item?.id_cabang || item?.cabang_id || '';
  const code = item?.kode || item?.kode_cabang || '';
  const name = item?.nama || item?.nama_cabang || 'Cabang';
  return {
    value: String(id),
    label: code ? `${code} - ${name}` : name
  };
}

function branchMatchesCompany(branchId, companyId) {
  if (!branchId || !companyId) return false;
  return companyIdsForBranch(branchId).includes(String(companyId));
}

const availableOriginCompanyIds = computed(() => {
  const ids = new Set();
  scopedOriginBranches.value.forEach((branch) => {
    const branchId = branch?.id || branch?.id_cabang || branch?.cabang_id;
    companyIdsForBranch(branchId).forEach((companyId) => ids.add(String(companyId)));
  });

  if (fallbackCompanyId.value) {
    ids.add(String(fallbackCompanyId.value));
  }

  return ids;
});

const companyOriginOptions = computed(() =>
  companyRows.value
    .filter((item) => availableOriginCompanyIds.value.has(companyOption(item).value))
    .map(companyOption)
);

// Tujuan boleh berada di perusahaan lain. Pembatasan cabang baru dilakukan
// setelah perusahaan tujuan dipilih agar transfer lintas perusahaan tetap bisa dibuat.
const companyDestinationOptions = computed(() => companyRows.value.map(companyOption));

const branchOriginOptions = computed(() =>
  !form.id_perusahaan_awal
    ? []
    : scopedOriginBranches.value
      .filter((item) => branchMatchesCompany(item?.id || item?.id_cabang || item?.cabang_id, form.id_perusahaan_awal))
      .map(branchOption)
);

const branchDestinationOptions = computed(() =>
  !form.id_perusahaan_tujuan
    ? []
    : branchRows.value
      .filter((item) => branchMatchesCompany(item?.id || item?.id_cabang || item?.cabang_id, form.id_perusahaan_tujuan))
      .map(branchOption)
);

const principalOptions = computed(() =>
  principalRows.value.filter((item) => principalBelongsToTransferCompany(item, form.id_perusahaan_awal)).map((item) => ({
    value: String(item.id),
    label: `${item.kode || item.id} - ${item.nama || item.nama_principal || item.text || 'Principal'}`
  }))
);

const productOptions = computed(() =>
  productRows.value.map((item) => ({
    value: String(item.id),
    label: `${item.kode_sku || item.kode || '-'} - ${item.nama || 'Produk'}`
  }))
);

const selectedProduct = computed(() => productRows.value.find((item) => String(item.id) === String(productForm.id_produk)));

const productUomFields = computed(() => {
  const uomsByLevel = new Map(selectedProductUoms.value.map((item) => [Number(item.level), item]));

  return [1, 2, 3].map((level) => {
    const uom = uomsByLevel.get(level);
    const label = uom?.kode || uom?.nama || `UOM ${level}`;
    const factor = Math.max(1, Number(uom?.faktor_konversi || 1));
    return {
      level,
      key: `uom_${level}`,
      enabled: Boolean(uom),
      label,
      factor,
      helpText: uom ? `1 ${label} = ${factor.toLocaleString('id-ID')} PCS` : 'Tidak dikonfigurasi pada master produk'
    };
  });
});

function normalizeTransferQuantity(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 0;
}

function normalizeProductUoms(payload) {
  const uoms = normalizeList(payload?.uoms || payload?.result?.uoms || payload);
  const uomsByLevel = new Map();

  uoms.forEach((item) => {
    const level = Number(item?.level ?? item?.uom_level ?? 0);
    if (![1, 2, 3].includes(level) || uomsByLevel.has(level)) return;
    uomsByLevel.set(level, {
      id: item?.id ?? item?.uom_id ?? '',
      level,
      kode: item?.kode ?? item?.uom_kode ?? '',
      nama: item?.nama ?? item?.uom_nama ?? '',
      faktor_konversi: Math.max(1, Number(item?.faktor_konversi ?? item?.uom_faktor_konversi ?? 1))
    });
  });

  return Array.from(uomsByLevel.values()).sort((left, right) => right.level - left.level);
}

function resetProductUomQuantities() {
  productForm.uom_1 = 0;
  productForm.uom_2 = 0;
  productForm.uom_3 = 0;
}

function normalizeUnavailableProductUoms() {
  const enabledLevels = new Set(selectedProductUoms.value.map((item) => Number(item.level)));
  [1, 2, 3].forEach((level) => {
    const key = `uom_${level}`;
    productForm[key] = enabledLevels.has(level) ? normalizeTransferQuantity(productForm[key]) : 0;
  });
}

function updateProductUom(level, value) {
  const field = productUomFields.value.find((item) => item.level === Number(level));
  if (!field?.enabled) return;
  productForm[field.key] = normalizeTransferQuantity(value);
}

function uomBreakdownForProduct(item) {
  return normalizeList(item?.uoms)
    .sort((left, right) => Number(right.level || 0) - Number(left.level || 0))
    .map((uom) => {
      const quantity = Number(item?.[`uom_${Number(uom.level)}`] || 0);
      const label = uom.kode || uom.nama || `UOM ${uom.level}`;
      return quantity > 0 ? `${quantity.toLocaleString('id-ID')} ${label}` : '';
    })
    .filter(Boolean)
    .join(' + ');
}

function totalPiecesForProduct(item) {
  return normalizeList(item?.uoms).reduce((total, uom) => {
    const quantity = Number(item?.[`uom_${Number(uom.level)}`] || 0);
    return total + (quantity * Math.max(1, Number(uom.faktor_konversi || 1)));
  }, 0);
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString('id-ID');
}

function resetProductForm() {
  productForm.id_produk = '';
  resetProductUomQuantities();
  selectedProductUoms.value = [];
  productUomError.value = '';
}

function addProduct() {
  feedback.value = '';
  errorMessage.value = '';

  if (!productForm.id_principal) {
    errorMessage.value = 'Pilih principal terlebih dahulu.';
    return;
  }

  if (!productForm.id_produk) {
    errorMessage.value = 'Pilih produk terlebih dahulu.';
    return;
  }

  normalizeUnavailableProductUoms();
  if (!selectedProductUoms.value.length) {
    errorMessage.value = 'Konfigurasi UOM produk belum tersedia. Lengkapi UOM pada master produk terlebih dahulu.';
    return;
  }

  const totalQty = productUomFields.value
    .filter((item) => item.enabled)
    .reduce((total, item) => total + Number(productForm[item.key] || 0), 0);
  if (totalQty <= 0) {
    errorMessage.value = 'Isi minimal satu quantity UOM lebih dari 0.';
    return;
  }

  const product = selectedProduct.value || {};
  const principal = principalRows.value.find((item) => String(item.id) === String(productForm.id_principal)) || {};
  if (!principalBelongsToTransferCompany(principal, form.id_perusahaan_awal)) {
    errorMessage.value = 'Principal produk harus sesuai perusahaan asal stok transfer.';
    return;
  }
  products.value.push({
    id_produk: Number(productForm.id_produk),
    id_principal: Number(productForm.id_principal),
    nama_principal: principal.nama || principal.nama_principal || principal.text || `Principal ${productForm.id_principal}`,
    nama_produk: product.nama || product.nama_produk || 'Produk',
    kode_sku: product.kode_sku || product.kode || '-',
    stock_ready: selectedStockReady.value ?? product.stok_ready ?? product.jumlah_ready ?? '-',
    uom_1: Number(productForm.uom_1 || 0),
    uom_2: Number(productForm.uom_2 || 0),
    uom_3: Number(productForm.uom_3 || 0),
    uoms: selectedProductUoms.value.map((item) => ({ ...item })),
    uom_breakdown: '',
    total_pieces: 0
  });
  const addedProduct = products.value[products.value.length - 1];
  addedProduct.uom_breakdown = uomBreakdownForProduct(addedProduct);
  addedProduct.total_pieces = totalPiecesForProduct(addedProduct);
  resetProductForm();
}

function removeProduct(index) {
  products.value.splice(index, 1);
}

function syncBranchForCompany(companyField, branchField) {
  const companyId = form[companyField];
  const branchId = form[branchField];

  if (!companyId) {
    form[branchField] = '';
    return;
  }

  if (branchId && !branchMatchesCompany(branchId, companyId)) {
    form[branchField] = '';
  }
}

function selectInitialOriginCompany() {
  const branchId = form.id_cabang_awal;
  if (!branchId || form.id_perusahaan_awal) return;

  const companyIds = companyIdsForBranch(branchId);
  const availableCompanyIds = new Set(companyRows.value.map((item) => companyOption(item).value));
  const preferredCompanyId = fallbackCompanyId.value &&
    companyIds.includes(String(fallbackCompanyId.value)) &&
    availableCompanyIds.has(String(fallbackCompanyId.value))
    ? String(fallbackCompanyId.value)
    : companyIds.find((companyId) => availableCompanyIds.has(String(companyId))) || '';

  if (preferredCompanyId) {
    form.id_perusahaan_awal = preferredCompanyId;
  }
}

function goToList() {
  router.push({ name: 'stock-transfer-list' });
}

async function loadOptions() {
  const [companyResponse, branchResponse, principalResponse] = await Promise.all([
    getCompanies(),
    getBranches(),
    getPrincipals()
  ]);

  companyRows.value = normalizeList(unwrapResponse(companyResponse));
  branchRows.value = normalizeList(unwrapResponse(branchResponse));
  principalRows.value = normalizeList(unwrapResponse(principalResponse));

  if (!canAccessAllBranches.value && fallbackBranchId.value) {
    form.id_cabang_awal = String(fallbackBranchId.value);
  }
  selectInitialOriginCompany();
}

async function loadProductsByPrincipal() {
  const principalId = productForm.id_principal;
  const requestToken = ++productOptionsRequestToken;

  productRows.value = [];
  productLoadError.value = '';
  resetProductForm();
  selectedStockReady.value = null;

  if (!principalId) {
    productLoading.value = false;
    return;
  }

  productLoading.value = true;
  try {
    const response = await getProductOptionsByPrincipal(principalId);
    if (requestToken !== productOptionsRequestToken) return;
    productRows.value = normalizeList(unwrapResponse(response));
    if (!productRows.value.length) {
      productLoadError.value = 'Produk untuk principal ini belum tersedia.';
    }
  } catch (error) {
    if (requestToken !== productOptionsRequestToken) return;
    productRows.value = [];
    productLoadError.value = normalizeError(error, 'Daftar produk principal belum bisa dimuat.');
  } finally {
    if (requestToken === productOptionsRequestToken) {
      productLoading.value = false;
    }
  }
}

async function submitForm() {
  feedback.value = '';
  errorMessage.value = '';

  if (
    !form.id_perusahaan_awal ||
    !form.id_cabang_awal ||
    !form.id_perusahaan_tujuan ||
    !form.id_cabang_tujuan ||
    !products.value.length
  ) {
    errorMessage.value = 'Lengkapi perusahaan asal/tujuan, cabang asal/tujuan, dan minimal satu produk.';
    return;
  }

  if (!branchMatchesCompany(form.id_cabang_awal, form.id_perusahaan_awal)) {
    errorMessage.value = 'Cabang asal tidak terdaftar pada perusahaan asal yang dipilih.';
    return;
  }

  if (!branchMatchesCompany(form.id_cabang_tujuan, form.id_perusahaan_tujuan)) {
    errorMessage.value = 'Cabang tujuan tidak terdaftar pada perusahaan tujuan yang dipilih.';
    return;
  }

  if (products.value.some((item) => !item.id_principal)) {
    errorMessage.value = 'Setiap produk stok transfer wajib memiliki principal.';
    return;
  }

  if (form.id_cabang_awal === form.id_cabang_tujuan) {
    errorMessage.value = 'Cabang asal dan tujuan tidak boleh sama.';
    return;
  }

  saving.value = true;

  try {
    await createStockTransfer({
      ...form,
      products: products.value.map((item) => ({
        id_principal: item.id_principal,
        id_produk: item.id_produk,
        uom_1: item.uom_1,
        uom_2: item.uom_2,
        uom_3: item.uom_3
      }))
    });
    feedback.value = 'Permintaan stok transfer berhasil dibuat.';
    form.nota_stock_transfer = '';
    products.value = [];
    window.setTimeout(goToList, 600);
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Gagal membuat stok transfer.');
  } finally {
    saving.value = false;
  }
}

async function loadSelectedStockReady() {
  selectedStockReady.value = null;
  if (!form.id_cabang_awal || !productForm.id_produk) return;

  try {
    const response = await getProductStockReady({
      id_cabang: form.id_cabang_awal,
      id_produk: productForm.id_produk
    });
    const payload = unwrapResponse(response);
    selectedStockReady.value = Number(payload?.jumlah_ready ?? payload?.result?.jumlah_ready ?? payload?.[0]?.jumlah_ready ?? 0);
  } catch {
    selectedStockReady.value = 0;
  }
}

async function loadSelectedProductUoms() {
  const productId = productForm.id_produk;
  const requestToken = ++productUomRequestToken;
  selectedProductUoms.value = [];
  productUomError.value = '';

  if (!productId) {
    productUomLoading.value = false;
    return;
  }

  const inlineUoms = normalizeProductUoms(selectedProduct.value);
  if (inlineUoms.length) {
    selectedProductUoms.value = inlineUoms;
  }

  productUomLoading.value = true;
  try {
    const response = await getProductDetail(productId);
    const uoms = normalizeProductUoms(unwrapResponse(response));
    if (requestToken !== productUomRequestToken) return;

    selectedProductUoms.value = uoms;
    normalizeUnavailableProductUoms();
    if (!uoms.length) {
      productUomError.value = 'Master produk ini belum memiliki konfigurasi UOM.';
    }
  } catch (error) {
    if (requestToken !== productUomRequestToken) return;
    selectedProductUoms.value = [];
    normalizeUnavailableProductUoms();
    productUomError.value = normalizeError(error, 'Konfigurasi UOM produk belum bisa dimuat.');
  } finally {
    if (requestToken === productUomRequestToken) {
      productUomLoading.value = false;
    }
  }
}

onMounted(loadOptions);

watch(
  () => form.id_perusahaan_awal,
  () => {
    syncBranchForCompany('id_perusahaan_awal', 'id_cabang_awal');
    products.value = [];
    productForm.id_principal = '';
    resetProductForm();
    loadSelectedStockReady();
  }
);

watch(
  () => form.id_perusahaan_tujuan,
  () => {
    syncBranchForCompany('id_perusahaan_tujuan', 'id_cabang_tujuan');
  }
);

watch(
  () => form.id_cabang_awal,
  () => {
    if (
      form.id_cabang_awal &&
      form.id_perusahaan_awal &&
      !branchMatchesCompany(form.id_cabang_awal, form.id_perusahaan_awal)
    ) {
      form.id_cabang_awal = '';
      return;
    }
    products.value = [];
    loadSelectedStockReady();
  }
);

watch(
  () => form.id_cabang_tujuan,
  () => {
    if (
      form.id_cabang_tujuan &&
      form.id_perusahaan_tujuan &&
      !branchMatchesCompany(form.id_cabang_tujuan, form.id_perusahaan_tujuan)
    ) {
      form.id_cabang_tujuan = '';
    }
  }
);

watch(
  () => productForm.id_principal,
  () => {
    loadProductsByPrincipal();
  }
);

watch(
  () => productForm.id_produk,
  () => {
    resetProductUomQuantities();
    loadSelectedStockReady();
    loadSelectedProductUoms();
  }
);
</script>

<template>
  <div class="space-y-6">
    <PageHeader title="Buat Stok Transfer" description="Pilih perusahaan lalu cabang asal/tujuan, tambah beberapa produk, kemudian kirim request transfer tanpa mengetik ID manual.">
      <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="goToList">
        Kembali ke List
      </button>
    </PageHeader>

    <section class="panel p-6">
      <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <AppFormField v-model="form.nota_stock_transfer" label="Nota stok transfer" placeholder="Opsional / auto jika kosong" />
        <AppSearchSelect
          v-model="form.id_perusahaan_awal"
          label="Perusahaan asal"
          placeholder="Ketik / pilih perusahaan asal"
          :options="companyOriginOptions"
          empty-text="Perusahaan asal sesuai akses cabang belum tersedia."
        />
        <AppSearchSelect
          v-model="form.id_cabang_awal"
          label="Cabang asal"
          :placeholder="form.id_perusahaan_awal ? 'Ketik / pilih cabang asal' : 'Pilih perusahaan asal dahulu'"
          :options="branchOriginOptions"
          :disabled="!form.id_perusahaan_awal || (!canAccessAllBranches && !!fallbackBranchId)"
          :empty-text="form.id_perusahaan_awal ? 'Cabang asal tidak tersedia untuk perusahaan ini.' : 'Pilih perusahaan asal dahulu.'"
        />
        <AppSearchSelect
          v-model="form.id_perusahaan_tujuan"
          label="Perusahaan tujuan"
          placeholder="Ketik / pilih perusahaan tujuan"
          :options="companyDestinationOptions"
          empty-text="Perusahaan tujuan belum tersedia."
        />
        <AppSearchSelect
          v-model="form.id_cabang_tujuan"
          label="Cabang tujuan"
          :placeholder="form.id_perusahaan_tujuan ? 'Ketik / pilih cabang tujuan' : 'Pilih perusahaan tujuan dahulu'"
          :options="branchDestinationOptions"
          :disabled="!form.id_perusahaan_tujuan"
          :empty-text="form.id_perusahaan_tujuan ? 'Cabang tujuan tidak tersedia untuk perusahaan ini.' : 'Pilih perusahaan tujuan dahulu.'"
        />
      </div>
    </section>

    <section class="panel p-6">
      <h3 class="text-lg font-semibold text-slate-900">Produk Transfer</h3>
      <p class="mt-1 text-sm text-slate-500">Pilih principal terlebih dahulu agar daftar produk hanya menampilkan produk milik principal tersebut.</p>
      <div class="mt-4 grid gap-4 md:grid-cols-[minmax(0,0.85fr)_minmax(0,1.65fr)]">
        <AppSearchSelect
          v-model="productForm.id_principal"
          label="Principal"
          placeholder="Pilih principal"
          :options="principalOptions"
          :disabled="!form.id_perusahaan_awal"
          empty-text="Principal untuk perusahaan asal belum tersedia."
        />
        <AppSearchSelect
          v-model="productForm.id_produk"
          label="Produk"
          :placeholder="productForm.id_principal ? 'Pilih produk' : 'Pilih principal dulu'"
          :options="productOptions"
          :disabled="!productForm.id_principal || productLoading"
          :loading="productLoading"
          empty-text="Produk untuk principal ini belum tersedia."
        />
      </div>
      <div class="mt-4 grid gap-4 md:grid-cols-[repeat(3,minmax(0,1fr))_auto]">
        <label v-for="field in productUomFields" :key="field.key" class="block">
          <span class="mb-1.5 block text-sm font-medium text-slate-700">{{ field.label }}</span>
          <input
            :value="productForm[field.key]"
            type="number"
            min="0"
            step="1"
            :disabled="!field.enabled || productUomLoading"
            :aria-label="field.label"
            class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none transition focus:border-brand-400 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
            @input="updateProductUom(field.level, $event.target.value)"
          />
          <span class="mt-1 block text-[11px] text-slate-500">{{ field.helpText }}</span>
        </label>
        <button class="self-end rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-medium text-slate-700 disabled:cursor-not-allowed disabled:opacity-60" :disabled="productLoading || productUomLoading" @click="addProduct">
          Tambah
        </button>
      </div>
      <p v-if="productLoading" class="mt-3 text-sm text-slate-500">Memuat produk principal...</p>
      <p v-else-if="productLoadError" class="mt-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        {{ productLoadError }}
      </p>
      <p v-if="productUomLoading" class="mt-3 text-sm text-slate-500">Memuat konfigurasi UOM produk...</p>
      <p v-else-if="productUomError" class="mt-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        {{ productUomError }}
      </p>
      <p v-if="productForm.id_produk" class="mt-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
        Stok ready cabang asal saat ini:
        <span class="font-semibold text-slate-900">{{ selectedStockReady ?? 0 }}</span>
      </p>

      <div class="mt-5 overflow-x-auto rounded-2xl border border-slate-200">
        <table class="min-w-full divide-y divide-slate-200 text-sm">
          <thead class="bg-slate-50">
            <tr>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Principal</th>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">SKU</th>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Produk</th>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Stok Sistem</th>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Rincian UOM</th>
              <th class="px-4 py-3 text-right font-medium uppercase tracking-wide text-slate-500">Total PCS</th>
              <th class="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 bg-white">
            <tr v-if="!products.length">
              <td colspan="7" class="px-4 py-10 text-center text-slate-500">Belum ada produk transfer.</td>
            </tr>
            <tr v-for="(item, index) in products" v-else :key="`${item.id_produk}-${index}`">
              <td class="px-4 py-3 text-slate-700">{{ item.nama_principal }}</td>
              <td class="px-4 py-3 text-slate-700">{{ item.kode_sku }}</td>
              <td class="px-4 py-3 text-slate-700">{{ item.nama_produk }}</td>
              <td class="px-4 py-3 text-slate-700">{{ item.stock_ready }}</td>
              <td class="px-4 py-3 text-slate-700">{{ item.uom_breakdown || '-' }}</td>
              <td class="px-4 py-3 text-right font-medium text-slate-900">{{ formatNumber(item.total_pieces) }} PCS</td>
              <td class="px-4 py-3 text-right">
                <button class="rounded-xl border border-rose-200 px-3 py-1.5 text-xs font-medium text-rose-700" @click="removeProduct(index)">
                  Hapus
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="feedback" class="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
        {{ feedback }}
      </div>
      <div v-if="errorMessage" class="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
        {{ errorMessage }}
      </div>

      <button class="mt-5 rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60" :disabled="saving" @click="submitForm">
        {{ saving ? 'Membuat...' : 'Buat Stok Transfer' }}
      </button>
    </section>
  </div>
</template>
