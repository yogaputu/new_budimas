<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  getBranches,
  getCompanies,
  getPrincipals,
  getProductDetail,
  getProductOptionsByPrincipal
} from '@/api/master';
import {
  createPurchaseOrder,
  generatePurchaseOrderCode,
  getPurchaseOrderDetail,
  getPurchaseOrderProducts,
  importPurchaseOrderTemplate,
  updatePurchaseOrder
} from '@/api/purchase';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import {
  canAccessAllPurchaseBranches,
  getPurchaseBranchOptions,
  getPurchaseCompanyIdsForBranch,
  getPurchaseCompanyOptions,
  getPurchaseFallbackBranchId,
  getPurchasePrincipalOptions
} from '@/modules/purchase/utils/purchaseScope';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const router = useRouter();
const route = useRoute();
const authStore = useAuthStore();

const form = reactive({
  companyId: '',
  branchId: '',
  principalId: '',
  code: '',
  note: ''
});

const productPicker = reactive({
  productId: ''
});

const companyRows = ref([]);
const branchRows = ref([]);
const principalRows = ref([]);
const productRows = ref([]);
const detailRows = ref([]);
const loading = reactive({
  meta: false,
  code: false,
  products: false,
  productDetail: false,
  submit: false
});
const feedback = ref('');
const errorMessage = ref('');
const lastCreatedOrder = ref(null);
const importModalOpen = ref(false);
const importFile = ref(null);
const importSourceType = ref('lob');
const importSubmitting = ref(false);
const importFileInputKey = ref(0);
const hydratingEdit = ref(false);
const hydratingRoute = ref(false);
const fallbackBranchId = computed(() => getPurchaseFallbackBranchId(authStore));
const canAccessAllBranches = computed(() => canAccessAllPurchaseBranches(authStore));
const isEditMode = computed(() => !!route.params.id);
const editingOrderId = computed(() => (route.params.id ? String(route.params.id) : ''));
const isBranchRequest = computed(() =>
  !isEditMode.value && (route.name === 'purchase-branch-requests-create' || getQueryValue('source') === 'branch-request')
);

const companyOptions = computed(() =>
  getPurchaseCompanyOptions(companyRows.value, branchRows.value, form.branchId, authStore)
);

const branchOptions = computed(() =>
  getPurchaseBranchOptions(branchRows.value, authStore, form.companyId, companyRows.value)
);

const principalOptions = computed(() =>
  getPurchasePrincipalOptions(principalRows.value, form.companyId)
);

const productOptions = computed(() =>
  productRows.value.map((item) => ({
    value: String(item.id || item.produk_id || item.value),
    label: `${item.kode_sku || item.kode || '-'} - ${item.nama || item.text || 'Produk'}`
  }))
);

const totalSummary = computed(() => {
  const total = detailRows.value.reduce((sum, item) => sum + Number(item.subtotal || 0), 0);
  return {
    lineCount: detailRows.value.length,
    total
  };
});

const pageTitle = computed(() => {
  if (isEditMode.value) return 'Edit/Revisi Purchase Order';
  return isBranchRequest.value ? 'Buat Request Cabang' : 'Buat Purchase Order';
});
const pageDescription = computed(() =>
  isEditMode.value
    ? 'Revisi header, produk, dan rincian UOM PO yang masih berada di tahap request atau need confirm.'
    : isBranchRequest.value
      ? 'Ajukan kebutuhan cabang untuk ditinjau terlebih dahulu. Request baru akan masuk tahap Request sebelum diproses menjadi purchase order.'
      : 'Frontend baru untuk membuat request purchase langsung ke API lama, lengkap dengan kode otomatis, detail produk, dan rincian UOM.'
);

function formatCurrency(value) {
  return `Rp ${new Intl.NumberFormat('id-ID').format(Number(value || 0))}`;
}

function normalizeQty(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}

function getQueryValue(key) {
  const value = route.query[key];
  return Array.isArray(value) ? value[0] : value;
}

function normalizeDoiDraftItem(item) {
  if (!item || typeof item !== 'object') return null;
  const productId = item.productId || item.produk_id || item.id_produk || item.id;
  if (!productId) return null;
  return {
    productId: String(productId),
    qty: item.qty ?? item.jumlah ?? item.recommended_purchase_qty ?? '',
  };
}

function getDoiDraftFromRoute() {
  const branchId = getQueryValue('branchId');
  const companyId = getQueryValue('companyId');
  const principalId = getQueryValue('principalId');
  const draftKey = getQueryValue('draftKey');

  if (draftKey) {
    try {
      const raw = window.sessionStorage.getItem(`budimas.purchase.doi.${draftKey}`);
      const payload = raw ? JSON.parse(raw) : null;
      if (payload && typeof payload === 'object') {
        return {
          branchId: payload.branchId || branchId || '',
          companyId: payload.companyId || companyId || '',
          principalId: payload.principalId || principalId || '',
          items: normalizeList(payload.items).map(normalizeDoiDraftItem).filter(Boolean),
        };
      }
    } catch (error) {
      // Kalau draft session tidak terbaca, fallback ke query tunggal di bawah.
    }
  }

  const rawItems = getQueryValue('items');
  if (rawItems) {
    try {
      const parsedItems = JSON.parse(rawItems);
      return {
        branchId,
        companyId,
        principalId,
        items: normalizeList(parsedItems).map(normalizeDoiDraftItem).filter(Boolean),
      };
    } catch (error) {
      // Fallback ke query tunggal di bawah.
    }
  }

  const productId = getQueryValue('productId');
  const qty = getQueryValue('qty');
  return {
    branchId,
    companyId,
    principalId,
    items: productId ? [{ productId: String(productId), qty }] : [],
  };
}

function applySuggestedQty(line, suggestedQty) {
  let remaining = Math.floor(normalizeQty(suggestedQty));
  if (!remaining) {
    return;
  }

  const qtyRows = normalizeList(line.jumlah)
    .map((item, index) => ({
      item,
      index,
      factor: Math.max(1, Number(item.uom_faktor_konversi || 1))
    }))
    .sort((a, b) => b.factor - a.factor);

  if (!qtyRows.length) {
    return;
  }

  qtyRows.forEach(({ item, factor }) => {
    const qty = Math.floor(remaining / factor);
    item.jumlah = qty;
    remaining -= qty * factor;
  });

  if (remaining > 0) {
    qtyRows[qtyRows.length - 1].item.jumlah += 1;
  }

  recalculateLine(line);
}

function normalizePurchaseQtyRows(detail, productDetail) {
  const productPrice = Number(detail?.produk_harga_beli ?? productDetail?.harga_beli ?? 0);
  const ppnPercent = Number(detail?.ppn ?? productDetail?.ppn ?? 0);
  const rawQtyRows = normalizeList(detail?.jumlah);

  const purchaseQtyRows = rawQtyRows.map((qty) => ({
    ...qty,
    uom_id: qty.uom_id ?? qty.id ?? '',
    uom_kode: qty.uom_kode ?? qty.kode ?? '',
    uom_nama: qty.uom_nama ?? qty.nama ?? '',
    uom_level: Number(qty.uom_level ?? qty.level ?? 0),
    uom_faktor_konversi: Math.max(1, Number(qty.uom_faktor_konversi ?? qty.faktor_konversi ?? 1)),
    jumlah: 0,
    subtotal: 0
  }));

  const baseFactor = Math.min(
    ...purchaseQtyRows.map((qty) => Number(qty.uom_faktor_konversi || 1))
  );

  purchaseQtyRows.forEach((qty) => {
    // Harga produk disimpan pada UOM terkecil. Harga setiap UOM harus mengikuti faktornya.
    qty.uom_harga_beli = productPrice * (Number(qty.uom_faktor_konversi || 1) / baseFactor);
    qty.uom_harga_beli_ppn = qty.uom_harga_beli * (1 + ppnPercent / 100);
  });

  if (purchaseQtyRows.length) {
    return purchaseQtyRows;
  }

  const fallbackUoms = normalizeList(productDetail?.uoms).map((uom) => ({
      uom_id: uom.id,
      uom_kode: uom.kode ?? '',
      uom_nama: uom.nama ?? '',
      uom_level: Number(uom.level ?? 0),
      uom_faktor_konversi: Math.max(1, Number(uom.faktor_konversi ?? 1)),
      jumlah: 0,
      subtotal: 0
    }));
  const fallbackBaseFactor = Math.min(
    ...fallbackUoms.map((uom) => Number(uom.uom_faktor_konversi || 1))
  );

  return fallbackUoms.map((uom) => {
    const factor = Number(uom.uom_faktor_konversi || 1);
    const uomPrice = productPrice * (factor / fallbackBaseFactor);
    return {
      ...uom,
      uom_harga_beli: uomPrice,
      uom_harga_beli_ppn: uomPrice * (1 + ppnPercent / 100)
    };
  });
}

function recalculateLine(line) {
  const details = normalizeList(line.jumlah);
  let subtotal = 0;
  let totalOrder = 0;
  details.forEach((item) => {
    item.jumlah = normalizeQty(item.jumlah);
    item.subtotal = Number(item.jumlah || 0) * Number(item.uom_harga_beli || 0);
    subtotal += Number(item.subtotal || 0);
    totalOrder += Number(item.jumlah || 0) * Number(item.uom_faktor_konversi || 1);
  });
  line.subtotal = subtotal;
  line.total_order = totalOrder;
  line.total_tersisa = totalOrder;
}

function updateQty(line, index, value) {
  line.jumlah[index].jumlah = normalizeQty(value);
  recalculateLine(line);
}

function removeLine(index) {
  detailRows.value.splice(index, 1);
}

function buildPayload() {
  const payload = {
    cabang_id: Number(form.branchId),
    principal_id: Number(form.principalId),
    kode: form.code,
    keterangan: form.note || '',
    request_source: isBranchRequest.value ? 'branch-request' : 'purchase-order',
    user_id: authStore.user?.id || authStore.user?.id_user || '',
    total: totalSummary.value.total,
    detail: detailRows.value.map((line) => ({
      produk_id: Number(line.produk_id),
      produk_kode: line.produk_kode,
      produk_nama: line.produk_nama,
      produk_harga_beli: Number(line.produk_harga_beli || 0),
      subtotal: Number(line.subtotal || 0),
      total_order: Number(line.total_order || 0),
      total_tersisa: Number(line.total_tersisa || 0),
      jumlah: normalizeList(line.jumlah).map((qty) => ({
        uom_id: Number(qty.uom_id),
        uom_kode: qty.uom_kode,
        uom_nama: qty.uom_nama,
        uom_level: Number(qty.uom_level || 0),
        uom_faktor_konversi: Number(qty.uom_faktor_konversi || 1),
        uom_harga_beli: Number(qty.uom_harga_beli || 0),
        uom_harga_beli_ppn: Number(qty.uom_harga_beli_ppn || 0),
        jumlah: Number(qty.jumlah || 0),
        subtotal: Number(qty.subtotal || 0)
      }))
    }))
  };
  if (isEditMode.value) {
    payload.order_id = Number(editingOrderId.value);
  }
  return payload;
}

async function loadMeta() {
  loading.meta = true;
  try {
    const [companies, branches, principals] = await Promise.all([getCompanies(), getBranches(), getPrincipals()]);
    companyRows.value = normalizeList(unwrapResponse(companies));
    branchRows.value = normalizeList(unwrapResponse(branches));
    principalRows.value = normalizeList(unwrapResponse(principals));
    if (!form.branchId && fallbackBranchId.value) {
      form.branchId = String(fallbackBranchId.value);
    }
  } finally {
    loading.meta = false;
  }
}

function normalizeExistingQtyRows(detail) {
  return normalizeList(detail?.jumlah).map((qty) => ({
    order_detail_jumlah_id: qty.id ?? qty.order_detail_jumlah_id ?? '',
    uom_id: qty.uom_id ?? '',
    uom_kode: qty.uom_kode ?? '',
    uom_nama: qty.uom_nama ?? '',
    uom_level: Number(qty.uom_level ?? 0),
    uom_faktor_konversi: Number(qty.uom_faktor_konversi ?? 1),
    uom_harga_beli: Number(qty.uom_harga_beli ?? detail?.produk_harga_beli ?? 0),
    uom_harga_beli_ppn: Number(qty.uom_harga_beli_ppn ?? qty.uom_harga_beli ?? detail?.produk_harga_beli ?? 0),
    jumlah: normalizeQty(qty.jumlah),
    subtotal: Number(qty.subtotal || 0)
  }));
}

function resolveCompanyIdFromPrincipal(principalId) {
  const principal = principalRows.value.find((item) => String(item.id) === String(principalId));
  return principal?.id_perusahaan ? String(principal.id_perusahaan) : '';
}

async function loadEditOrder() {
  if (!editingOrderId.value) return;
  hydratingEdit.value = true;
  loading.meta = true;
  errorMessage.value = '';
  try {
    const response = await getPurchaseOrderDetail(editingOrderId.value);
    const detail = unwrapResponse(response);
    if (!detail?.id) {
      throw new Error('Detail purchase order tidak ditemukan.');
    }

    form.branchId = String(detail.cabang_id || '');
    form.principalId = String(detail.principal_id || '');
    form.companyId = String(detail.id_perusahaan || resolveCompanyIdFromPrincipal(detail.principal_id) || '');
    form.code = String(detail.kode || '');
    form.note = detail.keterangan || '';

    detailRows.value = normalizeList(detail.detail).map((line) => {
      const normalized = {
        order_detail_id: line.id ?? line.order_detail_id ?? '',
        produk_id: line.produk_id,
        produk_kode: line.produk_kode,
        produk_nama: line.produk_nama,
        produk_harga_beli: Number(line.produk_harga_beli || 0),
        subtotal: Number(line.subtotal || 0),
        total_order: Number(line.total_order || 0),
        total_tersisa: Number(line.total_tersisa || line.total_order || 0),
        jumlah: normalizeExistingQtyRows(line)
      };
      recalculateLine(normalized);
      return normalized;
    });

    await loadProductOptions();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Detail purchase order belum bisa dimuat untuk revisi.');
  } finally {
    hydratingEdit.value = false;
    loading.meta = false;
  }
}

async function loadCode() {
  if (!form.branchId || !form.principalId) return;
  loading.code = true;
  try {
    const response = await generatePurchaseOrderCode(form.branchId, form.principalId);
    form.code = String(unwrapResponse(response) || '').trim();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Kode purchase order belum bisa dibuat.');
  } finally {
    loading.code = false;
  }
}

async function loadProductOptions() {
  productRows.value = [];
  productPicker.productId = '';
  if (!form.principalId) return;
  loading.products = true;
  try {
    const response = await getProductOptionsByPrincipal(form.principalId);
    productRows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Daftar produk principal belum bisa dimuat.');
  } finally {
    loading.products = false;
  }
}

function resolveProductIdForAdd(value) {
  if (!value || typeof value !== 'object') {
    return value;
  }

  if (value.target || value.currentTarget || value.type) {
    return productPicker.productId;
  }

  return value.productId || value.produk_id || value.id_produk || value.id || '';
}

async function addProduct(productId = productPicker.productId, options = {}) {
  const selectedProductId = String(resolveProductIdForAdd(productId) || '');
  if (!selectedProductId) return null;

  const existingLine = detailRows.value.find((item) => String(item.produk_id) === selectedProductId);
  if (existingLine) {
    applySuggestedQty(existingLine, options.suggestedQty);
    errorMessage.value = 'Produk ini sudah ada di daftar request.';
    return existingLine;
  }

  loading.productDetail = true;
  errorMessage.value = '';
  try {
    const [purchaseResponse, productResponse] = await Promise.all([
      getPurchaseOrderProducts(selectedProductId),
      getProductDetail(selectedProductId)
    ]);
    const detail = unwrapResponse(purchaseResponse);
    const productDetail = unwrapResponse(productResponse);
    if (!detail) {
      throw new Error('Detail produk purchase tidak ditemukan.');
    }
    const jumlahRows = normalizePurchaseQtyRows(detail, productDetail);
    const normalized = {
      produk_id: detail.produk_id,
      produk_kode: detail.produk_kode,
      produk_nama: detail.produk_nama,
      produk_harga_beli: Number(detail.produk_harga_beli || productDetail?.harga_beli || 0),
      subtotal: 0,
      total_order: 0,
      total_tersisa: 0,
      jumlah: jumlahRows
    };
    applySuggestedQty(normalized, options.suggestedQty);
    recalculateLine(normalized);
    detailRows.value.push(normalized);
    if (String(productPicker.productId || '') === selectedProductId) {
      productPicker.productId = '';
    }
    return normalized;
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Detail produk belum bisa dimuat.');
    return null;
  } finally {
    loading.productDetail = false;
  }
}

async function hydrateFromDoiQuery() {
  if (isEditMode.value || getQueryValue('source') !== 'doi') {
    return;
  }

  const draft = getDoiDraftFromRoute();
  const branchId = draft.branchId;
  const companyId = draft.companyId;
  const principalId = draft.principalId;

  if (!branchId || !principalId) {
    return;
  }

  hydratingRoute.value = true;
  errorMessage.value = '';
  try {
    form.branchId = String(branchId || '');
    form.companyId = String(companyId || '');
    form.principalId = String(principalId || '');
    await Promise.all([loadCode(), loadProductOptions()]);

    for (const item of draft.items) {
      await addProduct(item.productId, { suggestedQty: item.qty });
    }

    feedback.value = `Draft purchase order dari DOI sudah dimuat${draft.items.length ? ` (${draft.items.length} produk)` : ''}.`;
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Draft purchase order dari DOI belum bisa dimuat.');
  } finally {
    hydratingRoute.value = false;
  }
}

function openImportModal() {
  importSourceType.value = 'lob';
  importFile.value = null;
  importFileInputKey.value += 1;
  importModalOpen.value = true;
}

function onImportFileChange(event) {
  importFile.value = event.target?.files?.[0] || null;
}

async function submitImport() {
  if (!importFile.value) {
    errorMessage.value = 'Pilih file XLSX atau CSV terlebih dahulu.';
    return;
  }
  if (importSourceType.value === 'bd' && (!form.branchId || !form.principalId)) {
    errorMessage.value = 'Untuk Form Order Barang (BD), pilih Cabang dan Principal tujuan pada form PO terlebih dahulu.';
    return;
  }

  importSubmitting.value = true;
  errorMessage.value = '';
  feedback.value = '';
  try {
    const formData = new FormData();
    formData.append('file', importFile.value);
    formData.append('source_type', importSourceType.value);
    if (importSourceType.value === 'bd') {
      formData.append('cabang_id', form.branchId);
      formData.append('principal_id', form.principalId);
    }
    const userId = authStore.user?.id || authStore.user?.id_user;
    if (userId) formData.append('user_id', userId);

    const response = await importPurchaseOrderTemplate(formData);
    const result = unwrapResponse(response) || {};
    feedback.value = result.message || 'Purchase Order berhasil dibuat dari file impor.';
    importModalOpen.value = false;
    importFile.value = null;
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Import Purchase Order belum berhasil diproses.');
  } finally {
    importSubmitting.value = false;
  }
}

async function submitOrder() {
  if (!form.branchId || !form.principalId || !form.code) {
    errorMessage.value = 'Cabang, principal, dan kode purchase order wajib diisi.';
    return;
  }
  if (!detailRows.value.length) {
    errorMessage.value = 'Tambahkan minimal satu produk ke purchase order.';
    return;
  }
  if (!detailRows.value.every((item) => normalizeList(item.jumlah).some((qty) => Number(qty.jumlah || 0) > 0))) {
    errorMessage.value = 'Setiap produk harus memiliki minimal satu kuantitas UOM di atas 0.';
    return;
  }

  loading.submit = true;
  errorMessage.value = '';
  feedback.value = '';
  try {
    const response = isEditMode.value ? await updatePurchaseOrder(buildPayload()) : await createPurchaseOrder(buildPayload());
    const result = unwrapResponse(response);
    feedback.value = result?.message || (
      isEditMode.value
        ? 'Purchase order berhasil direvisi.'
        : isBranchRequest.value
          ? 'Request cabang berhasil dibuat dan menunggu approval.'
          : 'Purchase order berhasil dibuat.'
    );
    lastCreatedOrder.value = {
      code: form.code,
      branchId: form.branchId,
      companyId: form.companyId,
      principalId: form.principalId
    };
    if (!isEditMode.value) {
      detailRows.value = [];
      productPicker.productId = '';
      form.note = '';
      await loadCode();
    } else {
      await loadEditOrder();
    }
  } catch (error) {
    errorMessage.value = normalizeError(
      error,
      isEditMode.value
        ? 'Purchase order belum berhasil direvisi.'
        : isBranchRequest.value
          ? 'Request cabang belum berhasil dibuat.'
          : 'Purchase order belum berhasil dibuat.'
    );
  } finally {
    loading.submit = false;
  }
}

function openOrdersList() {
  const target = lastCreatedOrder.value;
  if (isBranchRequest.value) {
    router.push({
      name: 'purchase-branch-requests',
      query: {
        branchId: target?.branchId || form.branchId || '',
        companyId: target?.companyId || form.companyId || '',
        principalId: target?.principalId || form.principalId || '',
        search: target?.code || '',
        status: '1'
      }
    });
    return;
  }

  if (target?.branchId) {
    router.push({
      path: '/purchase/orders',
      query: {
        branchId: target.branchId,
        companyId: target.companyId || '',
        principalId: target.principalId || '',
        search: target.code || ''
      }
    });
    return;
  }

  router.push('/purchase/orders');
}

watch(
  () => [form.branchId, form.principalId],
  async ([branchId, principalId]) => {
    if (hydratingEdit.value || hydratingRoute.value) return;
    detailRows.value = [];
    productRows.value = [];
    productPicker.productId = '';
    if (branchId && principalId) {
      if (isEditMode.value) {
        await loadProductOptions();
      } else {
        await Promise.all([loadCode(), loadProductOptions()]);
      }
    } else {
      if (!isEditMode.value) form.code = '';
    }
  }
);

watch(
  () => form.companyId,
  (value) => {
    if (hydratingEdit.value || hydratingRoute.value) return;
    if (
      value &&
      form.branchId &&
      !getPurchaseCompanyIdsForBranch(form.branchId, branchRows.value, companyRows.value).includes(String(value))
    ) {
      form.companyId = '';
      return;
    }
    if (
      value &&
      form.principalId &&
      !principalOptions.value.some((item) => item.value === String(form.principalId))
    ) {
      form.principalId = '';
    }
  }
);

watch(
  () => form.branchId,
  (branchId, previousBranchId) => {
    if (hydratingEdit.value || hydratingRoute.value) return;
    if (String(branchId || '') !== String(previousBranchId || '')) {
      form.companyId = '';
      form.principalId = '';
      detailRows.value = [];
      productRows.value = [];
      productPicker.productId = '';
    }
  }
);

onMounted(async () => {
  await loadMeta();
  if (isEditMode.value) {
    await loadEditOrder();
  } else {
    await hydrateFromDoiQuery();
  }
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      :title="pageTitle"
      :description="pageDescription"
    >
      <button
        v-if="!isEditMode && !isBranchRequest"
        class="rounded-xl border border-brand-200 bg-white px-4 py-2.5 text-sm font-semibold text-brand-700 hover:bg-brand-50"
        @click="openImportModal"
      >
        Import PO XLSX / CSV
      </button>
    </PageHeader>

    <section v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
      {{ feedback }}
    </section>
    <section v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ errorMessage }}
    </section>

    <section class="panel p-5">
      <div class="grid gap-4 xl:grid-cols-5">
        <AppSearchSelect v-model="form.branchId" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="!canAccessAllBranches && !!fallbackBranchId" />
        <AppSearchSelect v-model="form.companyId" label="Perusahaan" placeholder="Pilih perusahaan" :options="companyOptions" />
        <AppSearchSelect v-model="form.principalId" label="Principal" placeholder="Pilih principal" :options="principalOptions" />
        <AppFormField v-model="form.code" :label="isBranchRequest ? 'Kode Request Cabang' : 'Kode PO'" readonly />
        <AppFormField v-model="form.note" label="Keterangan" :placeholder="isBranchRequest ? 'Catatan kebutuhan cabang' : 'Catatan purchase order'" />
      </div>
    </section>

    <section class="panel p-5 space-y-4">
      <div class="flex flex-col gap-3 lg:flex-row lg:items-end">
        <div class="flex-1">
          <AppSearchSelect
            v-model="productPicker.productId"
            label="Tambah Produk"
            placeholder="Cari produk principal"
            :options="productOptions"
            empty-text="Pilih principal dulu."
          />
        </div>
        <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white" :disabled="loading.productDetail" @click="addProduct()">
          {{ loading.productDetail ? 'Memuat...' : 'Tambah Produk' }}
        </button>
      </div>

      <div class="grid gap-4 md:grid-cols-3">
        <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
          <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Baris Produk</p>
          <p class="mt-2 text-sm font-semibold text-slate-900">{{ detailRows.length }}</p>
        </article>
        <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
          <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Kode PO</p>
          <p class="mt-2 text-sm font-semibold text-slate-900">{{ form.code || '-' }}</p>
        </article>
        <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
          <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Estimasi Total</p>
          <p class="mt-2 text-sm font-semibold text-slate-900">{{ formatCurrency(totalSummary.total) }}</p>
        </article>
      </div>

      <div v-if="!detailRows.length" class="rounded-2xl border border-dashed border-slate-200 px-4 py-8 text-sm text-slate-500">
        Belum ada produk pada purchase order ini.
      </div>

      <div v-else class="space-y-4">
        <article v-for="(line, lineIndex) in detailRows" :key="`${line.produk_id}-${lineIndex}`" class="rounded-3xl border border-slate-200 bg-white p-4">
          <div class="mb-4 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <p class="text-sm font-semibold text-slate-900">{{ line.produk_nama }}</p>
              <p class="text-xs text-slate-500">{{ line.produk_kode }} | Harga beli {{ formatCurrency(line.produk_harga_beli) }}</p>
            </div>
            <button class="rounded-xl border border-rose-200 px-3 py-2 text-xs font-medium text-rose-700" @click="removeLine(lineIndex)">
              Hapus
            </button>
          </div>

          <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            <div v-for="(qty, qtyIndex) in line.jumlah" :key="`${qty.uom_id}-${qtyIndex}`" class="rounded-2xl border border-slate-200 bg-slate-50 p-3">
              <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">{{ qty.uom_kode || qty.uom_nama || 'UOM' }}</p>
              <p class="mt-1 text-sm font-semibold text-slate-900">{{ formatCurrency(qty.uom_harga_beli || 0) }}</p>
              <label class="mt-3 block text-xs font-medium text-slate-500">Jumlah</label>
              <input
                :value="qty.jumlah"
                type="number"
                min="0"
                class="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none"
                @input="updateQty(line, qtyIndex, $event.target.value)"
              />
              <p class="mt-2 text-xs text-slate-500">Subtotal {{ formatCurrency(qty.subtotal || 0) }}</p>
            </div>
          </div>

          <div class="mt-4 grid gap-3 md:grid-cols-2">
            <div class="rounded-2xl border border-slate-200 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Total Konversi</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ Number(line.total_order || 0).toLocaleString('id-ID') }}</p>
            </div>
            <div class="rounded-2xl border border-slate-200 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Subtotal Produk</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ formatCurrency(line.subtotal || 0) }}</p>
            </div>
          </div>
        </article>
      </div>

      <div class="flex flex-wrap gap-3">
        <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white" :disabled="loading.submit" @click="submitOrder">
          {{ loading.submit ? 'Menyimpan...' : isEditMode ? 'Update Purchase Order' : isBranchRequest ? 'Kirim Request Cabang' : 'Simpan Purchase Order' }}
        </button>
        <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700" @click="openOrdersList">
          {{ isBranchRequest ? (lastCreatedOrder?.code ? 'Lihat Request Tersimpan' : 'Lihat Daftar Request') : (lastCreatedOrder?.code && !isEditMode ? 'Lihat PO Tersimpan' : 'Lihat Daftar PO') }}
        </button>
      </div>
    </section>

    <AppModal
      :open="importModalOpen"
      title="Import Purchase Order"
      description="Gunakan file hasil Export Analisa DOI (XLSX atau CSV). File BD tetap didukung dalam format XLSX."
      size="lg"
      @close="!importSubmitting && (importModalOpen = false)"
    >
      <div class="space-y-4">
        <label class="block">
          <span class="text-sm font-medium text-slate-700">Sumber file</span>
          <select v-model="importSourceType" class="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none">
            <option value="lob">Analisa DOI / LOB (XLSX atau CSV)</option>
            <option value="bd">Form Order Barang / BD (XLSX)</option>
          </select>
        </label>

        <div v-if="importSourceType === 'bd'" class="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          BD akan memakai Cabang dan Principal yang sedang dipilih pada form ini.
        </div>
        <div v-else class="rounded-xl border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-800">
          LOB/DOI membawa Cabang, Principal, dan Produk dari metadata ekspor. Ubah hanya kolom Final OB SPV sebelum impor.
        </div>

        <label class="block">
          <span class="text-sm font-medium text-slate-700">File XLSX atau CSV</span>
          <input
            :key="importFileInputKey"
            class="mt-1 block w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700"
            type="file"
            accept=".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
            @change="onImportFileChange"
          />
          <span v-if="importFile" class="mt-1 block text-xs text-slate-500">{{ importFile.name }}</span>
        </label>
      </div>

      <template #footer>
        <div class="flex justify-end gap-2">
          <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700" :disabled="importSubmitting" @click="importModalOpen = false">
            Batal
          </button>
          <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60" :disabled="importSubmitting" @click="submitImport">
            {{ importSubmitting ? 'Mengimpor...' : 'Import Purchase Order' }}
          </button>
        </div>
      </template>
    </AppModal>
  </div>
</template>
