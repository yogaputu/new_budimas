<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { getBranches, getCompanies } from '@/api/master';
import {
  createPurchaseReceipt,
  getPurchaseOrderDetail,
  getPurchaseReadyOrders
} from '@/api/purchase';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import {
  canAccessAllPurchaseBranches,
  getPurchaseBranchOptions,
  getPurchaseCompanyIdsForBranch,
  getPurchaseCompanyOptions,
  getPurchaseFallbackBranchId
} from '@/modules/purchase/utils/purchaseScope';
import { toLocalCompactDate } from '@/utils/date';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const router = useRouter();
const route = useRoute();
const authStore = useAuthStore();

const form = reactive({
  companyId: '',
  branchId: '',
  orderId: '',
  noTransaksi: '',
  note: '',
  batch: 1
});

const companyRows = ref([]);
const branchRows = ref([]);
const orderRows = ref([]);
const selectedOrder = ref(null);
const detailRows = ref([]);
const loading = reactive({
  meta: false,
  orders: false,
  detail: false,
  submit: false
});
const feedback = ref('');
const errorMessage = ref('');
const successToast = ref('');
const lastCreatedReceipt = ref(null);
const receiptRejections = ref([]);
const manualRejectionDrafts = ref({});
const activeManualRejectionKey = ref('');
const initialOrderId = ref('');
const fallbackBranchId = computed(() => getPurchaseFallbackBranchId(authStore));
const canAccessAllBranches = computed(() => canAccessAllPurchaseBranches(authStore));
let toastTimer = null;

const companyOptions = computed(() =>
  getPurchaseCompanyOptions(companyRows.value, branchRows.value, form.branchId, authStore)
);

const branchOptions = computed(() =>
  getPurchaseBranchOptions(branchRows.value, authStore, form.companyId, companyRows.value)
);

const orderOptions = computed(() =>
  orderRows.value.map((item) => ({
    value: String(item.id),
    label: `${item.kode || '-'} | ${item.principal_nama || '-'}`
  }))
);

const summary = computed(() => {
  const total = detailRows.value.reduce((sum, item) => sum + Number(item.subtotal || 0), 0);
  return {
    lines: detailRows.value.length,
    total
  };
});

function formatCurrency(value) {
  return `Rp ${new Intl.NumberFormat('id-ID').format(Number(value || 0))}`;
}

function normalizeQty(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}

function normalizeNullableNumber(value) {
  if (value === '' || value === null || value === undefined) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function showToast(message) {
  successToast.value = message;
  if (toastTimer) {
    clearTimeout(toastTimer);
  }
  toastTimer = setTimeout(() => {
    successToast.value = '';
  }, 3200);
}

function generateTransactionNo(orderCode = '') {
  const stamp = new Date();
  const date = toLocalCompactDate(stamp);
  const time = `${stamp.getHours()}${stamp.getMinutes()}${stamp.getSeconds()}`.padStart(6, '0');
  const suffix = orderCode ? orderCode.split('/').pop() : 'TRX';
  return `PTR-${date}-${suffix}-${time}`;
}

function recalculateLine(line) {
  const details = normalizeList(line.jumlah);
  let subtotal = 0;
  details.forEach((item) => {
    item.jumlah = normalizeQty(item.jumlah);
    item.subtotal = Number(item.jumlah || 0) * Number(item.uom_harga_beli || 0);
    subtotal += Number(item.subtotal || 0);
  });
  line.subtotal = subtotal;
}

function remainingReceiptQty(qty) {
  return Math.max(0, normalizeQty(qty?.jumlah_tersisa ?? qty?.jumlah_pesanan));
}

function updateQty(line, index, value) {
  const qty = line.jumlah[index];
  qty.jumlah = Math.min(normalizeQty(value), remainingReceiptQty(qty));
  const draft = manualRejectionDrafts.value[manualRejectionKey(line, qty)];
  if (draft) {
    draft.rejected_qty = Math.min(normalizeQty(draft.rejected_qty), remainingQtyForManualRejection(qty));
  }
  recalculateLine(line);
}

function remainingQtyForReceipt(line, qty) {
  const rejectedQty = normalizeQty(manualRejectionFor(line, qty)?.rejected_qty);
  return Math.max(0, remainingReceiptQty(qty) - rejectedQty);
}

function fillQtyWithRemaining(line, qty) {
  qty.jumlah = remainingQtyForReceipt(line, qty);
  recalculateLine(line);
}

function fillLineWithRemaining(line) {
  normalizeList(line?.jumlah).forEach((qty) => {
    qty.jumlah = remainingQtyForReceipt(line, qty);
  });
  recalculateLine(line);
}

function fillAllWithRemaining() {
  detailRows.value.forEach((line) => fillLineWithRemaining(line));
}

function clearLineReceiptQty(line) {
  normalizeList(line?.jumlah).forEach((qty) => {
    qty.jumlah = 0;
  });
  recalculateLine(line);
}

function clearAllReceiptQty() {
  detailRows.value.forEach((line) => clearLineReceiptQty(line));
}

function canFillQtyWithRemaining(line, qty) {
  return normalizeQty(qty?.jumlah) !== remainingQtyForReceipt(line, qty);
}

function lineHasFillableQty(line) {
  return normalizeList(line?.jumlah).some((qty) => canFillQtyWithRemaining(line, qty));
}

function manualRejectionKey(line, qty) {
  return `${line?.id || 'detail'}:${qty?.id || qty?.uom_kode || 'uom'}`;
}

function remainingQtyForManualRejection(qty) {
  return Math.max(0, remainingReceiptQty(qty) - normalizeQty(qty?.jumlah));
}

function manualRejectionFor(line, qty) {
  return manualRejectionDrafts.value[manualRejectionKey(line, qty)] || null;
}

function openManualRejection(line, qty) {
  const key = manualRejectionKey(line, qty);
  if (!manualRejectionDrafts.value[key]) {
    manualRejectionDrafts.value[key] = {
      order_detail_id: Number(line.id),
      order_detail_jumlah_id: Number(qty.id),
      rejected_qty: remainingQtyForManualRejection(qty),
      reason_code: 'QUALITY_NOT_ACCEPTED',
      reason_note: ''
    };
  }
  activeManualRejectionKey.value = key;
}

function openLineManualRejection(line) {
  const qty = normalizeList(line?.jumlah).find((item) => remainingQtyForManualRejection(item) > 0);
  if (!qty) {
    errorMessage.value = 'Tidak ada sisa kuantitas PO yang dapat ditolak pada produk ini.';
    return;
  }
  openManualRejection(line, qty);
}

function removeManualRejection(line, qty) {
  const key = manualRejectionKey(line, qty);
  delete manualRejectionDrafts.value[key];
  if (activeManualRejectionKey.value === key) {
    activeManualRejectionKey.value = '';
  }
}

function clearManualRejections() {
  manualRejectionDrafts.value = {};
  activeManualRejectionKey.value = '';
}

function manualRejectionsPayload() {
  return Object.values(manualRejectionDrafts.value)
    .map((item) => ({
      order_detail_id: Number(item.order_detail_id),
      order_detail_jumlah_id: Number(item.order_detail_jumlah_id),
      rejected_qty: normalizeQty(item.rejected_qty),
      reason_code: item.reason_code || 'OTHER',
      reason_note: String(item.reason_note || '').trim()
    }))
    .filter((item) => item.order_detail_id && item.order_detail_jumlah_id && item.rejected_qty > 0);
}

function buildPayload() {
  return {
    order_id: Number(form.orderId),
    no_transaksi: form.noTransaksi,
    keterangan: form.note || '',
    batch: Number(form.batch || 1),
    subtotal: summary.value.total,
    user_id: normalizeNullableNumber(authStore.user?.id ?? authStore.user?.id_user),
    user_jabatan_id: normalizeNullableNumber(authStore.user?.id_jabatan ?? authStore.user?.jabatan_id),
    manual_rejections: manualRejectionsPayload(),
    detail: detailRows.value.map((line) => ({
      order_detail_id: Number(line.id),
      tanggal_expired: line.tanggal_expired || null,
      batch_number: line.batch_number || '',
      subtotal: Number(line.subtotal || 0),
      jumlah: normalizeList(line.jumlah).map((qty) => ({
        order_detail_jumlah_id: Number(qty.id),
        jumlah: Number(qty.jumlah || 0),
        subtotal: Number(qty.subtotal || 0)
      }))
    }))
  };
}

async function loadMeta() {
  loading.meta = true;
  try {
    const [companyResponse, branchResponse] = await Promise.all([getCompanies(), getBranches()]);
    companyRows.value = normalizeList(unwrapResponse(companyResponse));
    branchRows.value = normalizeList(unwrapResponse(branchResponse));
    if (!form.branchId && route.query.branchId) {
      form.branchId = String(route.query.branchId);
    } else if (!form.branchId && fallbackBranchId.value) {
      form.branchId = String(fallbackBranchId.value);
    }
    if (!form.companyId && route.query.companyId) {
      form.companyId = String(route.query.companyId);
    }
    if (route.query.orderId) {
      initialOrderId.value = String(route.query.orderId);
    }
  } finally {
    loading.meta = false;
  }
}

async function loadReadyOrders() {
  orderRows.value = [];
  form.orderId = '';
  selectedOrder.value = null;
  detailRows.value = [];
  clearManualRejections();
  if (!form.branchId) return;
  loading.orders = true;
  try {
    const params = { cabang_id: form.branchId };
    const response = await getPurchaseReadyOrders(params);
    orderRows.value = normalizeList(unwrapResponse(response)).sort((a, b) => {
      const codeCompare = String(b.kode || '').localeCompare(String(a.kode || ''), 'id', {
        numeric: true,
        sensitivity: 'base'
      });
      if (codeCompare !== 0) return codeCompare;
      return Number(b.id || 0) - Number(a.id || 0);
    });
    if (initialOrderId.value && orderRows.value.some((item) => String(item.id) === String(initialOrderId.value))) {
      form.orderId = String(initialOrderId.value);
      initialOrderId.value = '';
    }
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Daftar order siap penerimaan belum bisa dimuat.');
  } finally {
    loading.orders = false;
  }
}

async function loadOrderDetail() {
  selectedOrder.value = orderRows.value.find((item) => String(item.id) === String(form.orderId)) || null;
  detailRows.value = [];
  clearManualRejections();
  if (!form.orderId) return;
  receiptRejections.value = [];
  loading.detail = true;
  errorMessage.value = '';
  try {
    const response = await getPurchaseOrderDetail(form.orderId);
    const detail = unwrapResponse(response);
    selectedOrder.value = selectedOrder.value || detail;
    form.noTransaksi = generateTransactionNo(selectedOrder.value?.kode || detail?.kode);
    detailRows.value = normalizeList(detail?.detail).map((item) => ({
      ...item,
      batch_number: '',
      tanggal_expired: '',
      subtotal: 0,
      jumlah: normalizeList(item.jumlah).map((qty) => ({
        ...qty,
        jumlah_pesanan: Number(qty.jumlah_pesanan ?? qty.jumlah ?? 0),
        jumlah_diterima: Number(qty.jumlah_diterima || 0),
        jumlah_tersisa: Number(qty.jumlah_tersisa ?? qty.jumlah ?? 0),
        jumlah: 0,
        subtotal: 0
      }))
    }));
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Detail order untuk penerimaan belum bisa dimuat.');
  } finally {
    loading.detail = false;
  }
}

async function submitReceipt() {
  if (!form.orderId || !form.noTransaksi) {
    errorMessage.value = 'Pilih order dan pastikan nomor transaksi terisi.';
    return;
  }
  if (!detailRows.value.length) {
    errorMessage.value = 'Belum ada detail order yang bisa diterima.';
    return;
  }
  const hasAcceptedQty = detailRows.value.some((line) => normalizeList(line.jumlah).some((qty) => Number(qty.jumlah || 0) > 0));
  const hasManualRejection = manualRejectionsPayload().length > 0;
  if (!hasAcceptedQty && !hasManualRejection) {
    errorMessage.value = 'Isi jumlah penerimaan atau catat penolakan barang.';
    return;
  }

  loading.submit = true;
  errorMessage.value = '';
  feedback.value = '';
  receiptRejections.value = [];
  try {
    const response = await createPurchaseReceipt(buildPayload());
    const result = unwrapResponse(response);
    receiptRejections.value = normalizeList(result?.rejections);
    if (result?.status === 'rejected' || result?.status === 'failed') {
      errorMessage.value = result?.message || 'Penerimaan tidak dapat disimpan karena tidak sesuai dengan PO.';
      return;
    }
    feedback.value = result?.message || 'Penerimaan barang berhasil disimpan.';
    showToast(feedback.value);
    lastCreatedReceipt.value = {
      branchId: form.branchId,
      companyId: form.companyId,
      principalId: selectedOrder.value?.principal_id || selectedOrder.value?.id_principal || '',
      transactionId: result?.id || result?.transaksi_id || ''
    };
    detailRows.value = [];
    form.note = '';
    form.noTransaksi = '';
    form.orderId = '';
    selectedOrder.value = null;
    clearManualRejections();
    await loadReadyOrders();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Penerimaan barang belum berhasil disimpan.');
  } finally {
    loading.submit = false;
  }
}

function openConfirmationQueue() {
  router.push({
    path: '/purchase/confirmations',
    query: {
      branchId: lastCreatedReceipt.value?.branchId || form.branchId || '',
      companyId: lastCreatedReceipt.value?.companyId || form.companyId || '',
      principalId: lastCreatedReceipt.value?.principalId || ''
    }
  });
}

watch(
  () => form.branchId,
  async (branchId, previousBranchId) => {
    if (String(branchId || '') !== String(previousBranchId || '')) {
      form.companyId = '';
    }
    await loadReadyOrders();
  }
);

watch(
  () => form.companyId,
  (value) => {
    if (
      value &&
      form.branchId &&
      !getPurchaseCompanyIdsForBranch(form.branchId, branchRows.value, companyRows.value).includes(String(value))
    ) {
      form.companyId = '';
      return;
    }
    loadReadyOrders();
  }
);

watch(
  () => form.orderId,
  async () => {
    await loadOrderDetail();
  }
);

onMounted(loadMeta);
</script>

<template>
  <div class="space-y-6">
    <div v-if="successToast" class="fixed right-4 top-4 z-50 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-800 shadow-lg">
      {{ successToast }}
    </div>

    <PageHeader
      title="Input Penerimaan Barang"
      description="Frontend baru untuk mencatat penerimaan barang dari purchase order yang sudah dikonfirmasi, lengkap dengan batch, expired, dan kuantitas per UOM."
    />

    <section v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
      {{ feedback }}
    </section>
    <section v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ errorMessage }}
    </section>
    <section v-if="receiptRejections.length" class="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
      <div class="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p class="font-semibold">Penolakan penerimaan</p>
          <p class="mt-1 text-xs text-amber-800">Barang yang tidak sesuai PO tidak masuk ke stok maupun daftar incoming WMS.</p>
        </div>
        <span class="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold">{{ receiptRejections.length }} temuan</span>
      </div>
      <div class="mt-3 divide-y divide-amber-200 rounded-xl border border-amber-200 bg-white/70">
        <div v-for="(rejection, index) in receiptRejections" :key="`${rejection.order_detail_jumlah_id || 'unknown'}-${index}`" class="grid gap-1 px-3 py-3 md:grid-cols-[1fr_auto] md:items-center">
          <div>
            <p class="font-medium">{{ rejection.produk_nama || rejection.produk_kode || 'Produk atau UOM tidak terdaftar' }}</p>
            <p class="text-xs text-amber-800">{{ rejection.reason_text }}</p>
          </div>
          <p class="text-xs font-semibold text-amber-900">
            Ditolak {{ Number(rejection.rejected_qty || 0).toLocaleString('id-ID') }} {{ rejection.uom_kode || 'unit' }}
          </p>
        </div>
      </div>
    </section>

    <section class="panel p-5">
      <div class="grid gap-4 xl:grid-cols-5">
        <AppSearchSelect v-model="form.branchId" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="!canAccessAllBranches && !!fallbackBranchId" />
        <AppSearchSelect v-model="form.companyId" label="Perusahaan" placeholder="Pilih perusahaan" :options="companyOptions" />
        <AppSearchSelect v-model="form.orderId" label="Order Siap Terima" placeholder="Pilih order" :options="orderOptions" />
        <AppFormField v-model="form.noTransaksi" label="No Transaksi" placeholder="Nomor transaksi otomatis" />
        <AppFormField v-model="form.batch" label="Batch Ke" type="number" min="1" />
      </div>
      <div class="mt-4 grid gap-4 xl:grid-cols-[1fr_220px]">
        <AppFormField v-model="form.note" label="Keterangan" placeholder="Catatan penerimaan barang" />
        <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
          <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Estimasi Total</p>
          <p class="mt-2 text-sm font-semibold text-slate-900">{{ formatCurrency(summary.total) }}</p>
          <p class="mt-1 text-xs text-slate-500">{{ summary.lines }} baris produk</p>
        </div>
      </div>
    </section>

    <section v-if="selectedOrder" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm text-slate-600">
      <strong class="text-slate-900">{{ selectedOrder.kode || selectedOrder.order_kode || '-' }}</strong>
      <span class="mx-2 text-slate-300">|</span>
      <span>{{ selectedOrder.principal_nama || '-' }}</span>
      <span class="mx-2 text-slate-300">|</span>
      <span>{{ selectedOrder.cabang_nama || '-' }}</span>
    </section>

    <section v-if="loading.detail" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
      Memuat detail order untuk penerimaan barang...
    </section>

    <section v-else class="space-y-4">
      <div v-if="detailRows.length" class="rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p class="font-semibold">Penerimaan sebagian diperbolehkan.</p>
            <p class="mt-1 text-xs text-sky-700">Isi hanya jumlah barang yang datang saat ini. Sisa PO tetap tersedia untuk diterima pada transaksi berikutnya. Qty penolakan yang sudah diisi tetap dipertahankan.</p>
          </div>
          <div class="flex flex-wrap gap-2">
            <button
              type="button"
              class="rounded-lg bg-sky-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-sky-800 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="!detailRows.some((line) => lineHasFillableQty(line))"
              @click="fillAllWithRemaining"
            >
              Terima Semua Sisa
            </button>
            <button
              type="button"
              class="rounded-lg border border-sky-200 bg-white px-3 py-1.5 text-xs font-semibold text-sky-800 hover:bg-sky-100"
              @click="clearAllReceiptQty"
            >
              Kosongkan Qty Terima
            </button>
          </div>
        </div>
      </div>
      <article v-for="(line, lineIndex) in detailRows" :key="`${line.id}-${lineIndex}`" class="panel p-5">
        <div class="mb-4 grid gap-3 lg:grid-cols-[1.3fr_0.7fr_0.7fr]">
          <div>
            <p class="text-sm font-semibold text-slate-900">{{ line.produk_nama }}</p>
            <p class="mt-1 text-xs text-slate-500">{{ line.produk_kode }} | Order {{ Number(line.total_order || 0).toLocaleString('id-ID') }} | Sisa {{ Number(line.total_tersisa || 0).toLocaleString('id-ID') }}</p>
            <div class="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                class="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-700 hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="!lineHasFillableQty(line)"
                @click="fillLineWithRemaining(line)"
              >
                Terima Sisa Produk
              </button>
              <button
                type="button"
                class="rounded-lg border border-rose-200 bg-rose-50 px-3 py-1.5 text-xs font-semibold text-rose-700 hover:bg-rose-100"
                @click="openLineManualRejection(line)"
              >
                Tolak Barang / Qty
              </button>
            </div>
          </div>
          <AppFormField v-model="line.batch_number" label="Batch Number" placeholder="Batch fisik" />
          <AppFormField v-model="line.tanggal_expired" label="Tanggal Expired" type="date" />
        </div>

        <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <div v-for="(qty, qtyIndex) in line.jumlah" :key="`${qty.id}-${qtyIndex}`" class="rounded-2xl border border-slate-200 bg-slate-50 p-3">
            <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">{{ qty.uom_kode || qty.uom_nama || 'UOM' }}</p>
            <p class="mt-1 text-sm font-semibold text-slate-900">{{ formatCurrency(qty.uom_harga_beli || 0) }}</p>
            <p class="mt-2 text-xs text-slate-500">Pesanan: {{ Number(qty.jumlah_pesanan || 0).toLocaleString('id-ID') }}</p>
            <p class="mt-1 text-xs text-slate-500">Sudah diterima: {{ Number(qty.jumlah_diterima || 0).toLocaleString('id-ID') }}</p>
            <p class="mt-1 text-xs font-semibold text-emerald-700">Sisa dapat diterima: {{ remainingReceiptQty(qty).toLocaleString('id-ID') }}</p>
            <div class="mt-3 flex items-center justify-between gap-2">
              <label class="block text-xs font-medium text-slate-500">Diterima Sekarang</label>
              <button
                type="button"
                class="text-xs font-semibold text-emerald-700 hover:text-emerald-800 disabled:cursor-not-allowed disabled:text-slate-400"
                :disabled="!canFillQtyWithRemaining(line, qty)"
                @click="fillQtyWithRemaining(line, qty)"
              >
                Isi sisa
              </button>
            </div>
            <input
              :value="qty.jumlah"
              type="number"
              min="0"
              :max="remainingReceiptQty(qty)"
              :disabled="remainingReceiptQty(qty) <= 0"
              class="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
              @input="updateQty(line, qtyIndex, $event.target.value)"
            />
            <p v-if="remainingReceiptQty(qty) <= 0" class="mt-2 text-xs font-medium text-slate-500">
              UOM ini sudah terpenuhi pada penerimaan sebelumnya.
            </p>
            <div class="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                class="rounded-lg border border-rose-200 bg-white px-3 py-1.5 text-xs font-semibold text-rose-700 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="remainingQtyForManualRejection(qty) <= 0"
                @click="openManualRejection(line, qty)"
              >
                {{ manualRejectionFor(line, qty) ? 'Ubah Penolakan' : 'Tolak Qty' }}
              </button>
              <button
                v-if="manualRejectionFor(line, qty)"
                type="button"
                class="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50"
                @click="removeManualRejection(line, qty)"
              >
                Batal Tolak
              </button>
            </div>
            <div v-if="activeManualRejectionKey === manualRejectionKey(line, qty)" class="mt-3 rounded-xl border border-rose-200 bg-rose-50 p-3">
              <div class="grid gap-3 sm:grid-cols-2">
                <label class="block text-xs font-medium text-rose-900">
                  Jumlah Ditolak
                  <input
                    :value="manualRejectionFor(line, qty)?.rejected_qty || 0"
                    type="number"
                    min="0"
                    :max="remainingQtyForManualRejection(qty)"
                    class="mt-1 w-full rounded-lg border border-rose-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none"
                    @input="manualRejectionFor(line, qty).rejected_qty = Math.min(normalizeQty($event.target.value), remainingQtyForManualRejection(qty))"
                  />
                </label>
                <label class="block text-xs font-medium text-rose-900">
                  Alasan Penolakan
                  <select v-model="manualRejectionFor(line, qty).reason_code" class="mt-1 w-full rounded-lg border border-rose-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none">
                    <option value="QUALITY_NOT_ACCEPTED">Kualitas tidak sesuai</option>
                    <option value="DAMAGED">Barang rusak</option>
                    <option value="WRONG_ITEM">Barang tidak sesuai PO</option>
                    <option value="OTHER">Lainnya</option>
                  </select>
                </label>
              </div>
              <label class="mt-3 block text-xs font-medium text-rose-900">
                Catatan Penolakan
                <textarea v-model="manualRejectionFor(line, qty).reason_note" rows="2" class="mt-1 w-full rounded-lg border border-rose-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none" placeholder="Contoh: kemasan penyok saat diterima"></textarea>
              </label>
              <p class="mt-2 text-xs text-rose-700">Barang yang ditolak tidak masuk stok. Sisa PO tetap dapat diterima pada pengiriman berikutnya.</p>
            </div>
            <p class="mt-2 text-xs text-slate-500">Subtotal {{ formatCurrency(qty.subtotal || 0) }}</p>
          </div>
        </div>
      </article>

      <section v-if="!detailRows.length" class="rounded-2xl border border-dashed border-slate-200 px-4 py-8 text-sm text-slate-500">
        Pilih order siap terima untuk memuat detail penerimaan barang.
      </section>
    </section>

    <div class="flex flex-wrap gap-3">
      <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white" :disabled="loading.submit" @click="submitReceipt">
        {{ loading.submit ? 'Menyimpan...' : 'Simpan Penerimaan Barang' }}
      </button>
      <button
        v-if="lastCreatedReceipt"
        class="rounded-xl border border-brand-200 bg-brand-50 px-4 py-3 text-sm font-medium text-brand-700"
        @click="openConfirmationQueue"
      >
        Lanjut ke Finalisasi Purchase Order
      </button>
      <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700" @click="router.push('/purchase/receipts')">
        Lihat Daftar Penerimaan
      </button>
    </div>
  </div>
</template>
