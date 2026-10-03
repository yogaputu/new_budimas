<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import {
  getCanvasOrders,
  getCanvasPaymentHistory,
  getCanvasSalesList,
  submitCanvasPayment
} from '@/api/salesCanvas';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import AppModal from '@/shared/components/AppModal.vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getLoginCompanyId, getLoginSalesId, getRowBranchIds, getRowCompanyId, isSuperUser, scopeRowsByLoginBranch, scopeSalesRowsByLogin, shouldLockToLoginSales } from '@/utils/accessScope';
import { formatCurrency, formatDate, getCurrentUserId } from '@/modules/sales-canvas/utils/canvasFormat';

const authStore = useAuthStore();

const filters = reactive({
  id_cabang: '',
  id_perusahaan: '',
  id_principal: '',
  id_sales: '',
  search: ''
});

const paymentForm = reactive({
  jumlah_dibayarkan: '',
  tipe_setoran: 'tunai',
  keterangan: ''
});

const branchRows = ref([]);
const companyRows = ref([]);
const principalRows = ref([]);
const salesRows = ref([]);
const orderRows = ref([]);
const historyRows = ref([]);
const selectedOrder = ref(null);
const loading = ref(false);
const detailLoading = ref(false);
const submitting = ref(false);
const errorMessage = ref('');
const successMessage = ref('');
const paymentModalOpen = ref(false);
const paymentHistoryLoaded = ref(false);
let activePaymentAttempt = { signature: '', id: '' };

const userId = computed(() => getCurrentUserId(authStore.user));
const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(authStore.user));
const fallbackSalesId = computed(() => getLoginSalesId(authStore.user));
const canUseLoginScope = computed(() => shouldLockToLoginSales(authStore));
const shouldLockBusinessScope = computed(() => !isSuperUser(authStore));

function companyIdsForBranch(branchId) {
  if (!branchId) return [];
  const ids = new Set();
  const branch = branchRows.value.find((item) => String(item.id) === String(branchId));
  const branchCompanyId = getRowCompanyId(branch);
  if (branchCompanyId) ids.add(String(branchCompanyId));
  if (fallbackCompanyId.value) ids.add(String(fallbackCompanyId.value));
  companyRows.value.forEach((item) => {
    if (getRowBranchIds(item).includes(String(branchId))) ids.add(String(item.id));
  });
  principalRows.value.forEach((item) => {
    const companyId = getRowCompanyId(item);
    const sameRegion =
      branch &&
      item.id_wilayah1 &&
      item.id_wilayah2 &&
      String(item.id_wilayah1) === String(branch.id_wilayah1) &&
      String(item.id_wilayah2) === String(branch.id_wilayah2);
    if (companyId && sameRegion) ids.add(String(companyId));
  });
  return [...ids];
}

const branchOptions = computed(() =>
  scopeRowsByLoginBranch(branchRows.value, authStore).map((item) => ({
    value: String(item.id),
    label: `${item.kode || '-'} - ${item.nama || item.nama_cabang || 'Cabang'}`
  }))
);

const companyOptions = computed(() => {
  const allowed = companyIdsForBranch(filters.id_cabang);
  return companyRows.value
    .filter((item) => filters.id_cabang && allowed.includes(String(item.id)))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || '-'} - ${item.nama || item.nama_perusahaan || 'Perusahaan'}`
    }));
});

const principalOptions = computed(() =>
  principalRows.value
    .filter((item) => !filters.id_perusahaan || String(getRowCompanyId(item)) === String(filters.id_perusahaan))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || '-'} - ${item.nama || item.principal_nama || 'Principal'}`
    }))
);

const salesOptions = computed(() =>
  scopeSalesRowsByLogin(salesRows.value, authStore).map((item) => ({
    value: String(item.id_sales || item.id || ''),
    label: `${item.kode_sales ? `${item.kode_sales} - ` : ''}${item.nama_sales || 'Sales'}`
  }))
);

function moneyValue(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : 0;
}

function canonicalOrderTotal(order = {}) {
  // `canvas_order.total_order` is calculated by the server after voucher and
  // PPN handling.  Never rebuild the invoice amount from the detail table in
  // this payment screen, because that was the source of a misleading total.
  return moneyValue(order.total_order ?? order.total_tagihan ?? 0);
}

function orderPaidAmount(order = {}) {
  return moneyValue(order.total_dibayarkan ?? order.jumlah_setoran ?? 0);
}

const filteredOrders = computed(() => {
  const query = filters.search.trim().toLowerCase();
  return orderRows.value
    .filter((item) => {
      if (!query) return true;
      return [item.nama_sales, item.nama_customer, item.kode_customer, item.tanggal_order]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query));
    })
    .map((item) => {
      const totalTagihan = canonicalOrderTotal(item);
      const totalDibayar = orderPaidAmount(item);
      const sisaTagihan = Math.max(
        moneyValue(item.sisa_tagihan ?? (totalTagihan - totalDibayar)),
        0
      );
      return {
        ...item,
        total_order: totalTagihan,
        total_dibayarkan: totalDibayar,
        sisa_tagihan: sisaTagihan,
        tanggal_label: formatDate(item.tanggal_order),
        tagihan_label: formatCurrency(totalTagihan),
        dibayar_label: formatCurrency(totalDibayar),
        sisa_label: formatCurrency(sisaTagihan)
      };
    });
});

const historyTableRows = computed(() =>
  historyRows.value.map((item) => ({
    ...item,
    tanggal_label: formatDate(item.tanggal_input),
    nominal_label: formatCurrency(item.nominal || item.jumlah_setoran || 0),
    status_label: item.status_finance === 'MENUNGGU_REKAP'
      ? 'Menunggu Rekap Canvas Finance'
      : item.status_finance === 'SUDAH_DIREKAP'
        ? 'Sudah masuk Piutang Canvas Finance'
        : Array.isArray(item.status_setoran)
          ? item.status_setoran.filter((value) => value !== null && value !== undefined).join(', ') || '-'
          : (item.status_setoran || '-')
  }))
);

const totalTagihan = computed(() => canonicalOrderTotal(selectedOrder.value));
const totalDibayar = computed(() => {
  // Preserve the list endpoint's canonical total while payment history is
  // loading; replacing it with a temporary zero made the modal show a false
  // outstanding amount and encouraged duplicate payment attempts.
  if (!paymentHistoryLoaded.value) return orderPaidAmount(selectedOrder.value);
  return historyRows.value.reduce((sum, item) => sum + moneyValue(item.nominal ?? item.jumlah_setoran), 0);
});
const sisaTagihan = computed(() => Math.max(totalTagihan.value - totalDibayar.value, 0));
const canSubmitPayment = computed(() => {
  const nominal = moneyValue(paymentForm.jumlah_dibayarkan);
  return Boolean(selectedOrder.value)
    && nominal > 0
    && nominal <= sisaTagihan.value + 0.005;
});

function resetSalesFilter() {
  filters.id_sales = canUseLoginScope.value && fallbackSalesId.value ? String(fallbackSalesId.value) : '';
}

function syncCompanyFromBranch() {
  const allowed = companyIdsForBranch(filters.id_cabang);
  filters.id_perusahaan = shouldLockBusinessScope.value && fallbackCompanyId.value
    ? String(fallbackCompanyId.value)
    : allowed.includes(String(filters.id_perusahaan)) ? String(filters.id_perusahaan) : '';
  filters.id_principal = '';
  resetSalesFilter();
}

async function loadReferences() {
  const [branches, companies, principals] = await Promise.all([getBranches(), getCompanies(), getPrincipals()]);
  branchRows.value = normalizeList(unwrapResponse(branches));
  companyRows.value = normalizeList(unwrapResponse(companies));
  principalRows.value = normalizeList(unwrapResponse(principals));
  if (!filters.id_cabang && shouldLockBusinessScope.value) {
    filters.id_cabang = String(fallbackBranchId.value || '');
    syncCompanyFromBranch();
  }
  if (shouldLockBusinessScope.value && fallbackCompanyId.value) filters.id_perusahaan = String(fallbackCompanyId.value);
  if (canUseLoginScope.value && fallbackSalesId.value) filters.id_sales = String(fallbackSalesId.value);
}

async function loadSales() {
  if (!filters.id_cabang || !filters.id_perusahaan) {
    salesRows.value = [];
    return;
  }
  const response = await getCanvasSalesList({
    id_cabang: filters.id_cabang,
    id_perusahaan: filters.id_perusahaan,
    id_principal: filters.id_principal
  });
  salesRows.value = normalizeList(unwrapResponse(response));
  if (canUseLoginScope.value && fallbackSalesId.value) {
    filters.id_sales = String(fallbackSalesId.value);
  }
}

async function loadOrders() {
  loading.value = true;
  errorMessage.value = '';
  try {
    const response = await getCanvasOrders(userId.value, {
      id_cabang: filters.id_cabang,
      id_perusahaan: filters.id_perusahaan,
      id_principal: filters.id_principal,
      id_sales: filters.id_sales
    });
    orderRows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    errorMessage.value = normalizeError(error);
  } finally {
    loading.value = false;
  }
}

async function selectOrder(row) {
  selectedOrder.value = row;
  paymentModalOpen.value = true;
  paymentForm.jumlah_dibayarkan = '';
  paymentForm.tipe_setoran = 'tunai';
  paymentForm.keterangan = '';
  activePaymentAttempt = { signature: '', id: '' };
  paymentHistoryLoaded.value = false;
  detailLoading.value = true;
  errorMessage.value = '';
  try {
    const response = await getCanvasPaymentHistory(row.id || row.id_canvas_order);
    historyRows.value = normalizeList(unwrapResponse(response));
    paymentHistoryLoaded.value = true;
    paymentForm.jumlah_dibayarkan = String(sisaTagihan.value || '');
  } catch (error) {
    historyRows.value = [];
    errorMessage.value = normalizeError(error);
  } finally {
    detailLoading.value = false;
  }
}

function closePaymentModal() {
  paymentModalOpen.value = false;
  paymentHistoryLoaded.value = false;
  activePaymentAttempt = { signature: '', id: '' };
}

function fillRemainingPayment() {
  paymentForm.jumlah_dibayarkan = String(sisaTagihan.value || '');
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function printPaymentReceipt(row = null) {
  const order = selectedOrder.value || {};
  const payment = row || historyTableRows.value[0] || {};
  const nominal = payment.nominal || payment.jumlah_setoran || paymentForm.jumlah_dibayarkan || 0;
  const receiptWindow = window.open('', '_blank', 'width=760,height=900');
  if (!receiptWindow) {
    errorMessage.value = 'Popup cetak diblokir browser. Izinkan popup untuk mencetak bukti bayar.';
    return;
  }

  receiptWindow.document.write(`
    <html>
      <head>
        <title>Bukti Bayar Canvas</title>
        <style>
          body { font-family: Arial, sans-serif; margin: 32px; color: #111827; }
          .receipt { border: 1px solid #111827; padding: 24px; max-width: 680px; margin: auto; }
          h1 { font-size: 22px; margin: 0 0 4px; text-transform: uppercase; }
          .muted { color: #64748b; font-size: 12px; }
          .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 22px 0; }
          .box { border: 1px solid #cbd5e1; border-radius: 10px; padding: 12px; }
          .box span { color: #64748b; display: block; font-size: 11px; font-weight: 700; text-transform: uppercase; }
          .box strong { display: block; margin-top: 6px; }
          .total { background: #ecfdf5; border-color: #10b981; font-size: 20px; }
          .sign { display: grid; grid-template-columns: 1fr 1fr; gap: 48px; margin-top: 44px; text-align: center; }
          .line { border-top: 1px solid #111827; margin-top: 56px; padding-top: 6px; }
          @media print { button { display: none; } body { margin: 0; } .receipt { border: none; } }
        </style>
      </head>
      <body>
        <div class="receipt">
          <h1>Bukti Bayar Canvas</h1>
          <div class="muted">Dokumen pembayaran tunai/non tunai sales canvas</div>
          <div class="grid">
            <div class="box"><span>Customer</span><strong>${escapeHtml(order.nama_customer || '-')}</strong></div>
            <div class="box"><span>Sales Canvas</span><strong>${escapeHtml(order.nama_sales || '-')}</strong></div>
            <div class="box"><span>Tanggal Order</span><strong>${escapeHtml(formatDate(order.tanggal_order))}</strong></div>
            <div class="box"><span>Tanggal Bayar</span><strong>${escapeHtml(payment.tanggal_label || formatDate(new Date()))}</strong></div>
            <div class="box"><span>Total Tagihan</span><strong>${escapeHtml(formatCurrency(totalTagihan.value))}</strong></div>
            <div class="box"><span>Sisa Setelah Bayar</span><strong>${escapeHtml(formatCurrency(Math.max(sisaTagihan.value - Number(nominal || 0), 0)))}</strong></div>
            <div class="box total"><span>Nominal Bayar</span><strong>${escapeHtml(formatCurrency(nominal))}</strong></div>
            <div class="box"><span>Metode</span><strong>${escapeHtml(payment.status_label || payment.tipe_setoran || paymentForm.tipe_setoran || 'Tunai')}</strong></div>
          </div>
          <div class="sign">
            <div><div class="line">Sales Canvas</div></div>
            <div><div class="line">Customer</div></div>
          </div>
        </div>
        <script>window.print(); window.onafterprint = () => window.close();<\/script>
      </body>
    </html>
  `);
  receiptWindow.document.close();
}

async function submitPayment() {
  errorMessage.value = '';
  successMessage.value = '';
  if (!selectedOrder.value) {
    errorMessage.value = 'Pilih tagihan Canvas terlebih dahulu.';
    return;
  }

  const nominal = moneyValue(paymentForm.jumlah_dibayarkan);
  if (nominal <= 0) {
    errorMessage.value = 'Nominal pembayaran harus lebih dari Rp 0.';
    return;
  }
  if (nominal > sisaTagihan.value + 0.005) {
    errorMessage.value = 'Nominal pembayaran melebihi sisa tagihan Canvas.';
    return;
  }

  const idCanvasOrder = Number(selectedOrder.value.id || selectedOrder.value.id_canvas_order || 0);
  if (!idCanvasOrder) {
    errorMessage.value = 'ID order Canvas tidak valid.';
    return;
  }

  const signature = [
    idCanvasOrder,
    nominal.toFixed(2),
    paymentForm.tipe_setoran || 'tunai'
  ].join(':');
  if (activePaymentAttempt.signature !== signature) {
    const paymentId = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `canvas-${Date.now()}-${Math.random().toString(36).slice(2, 14)}`;
    activePaymentAttempt = { signature, id: paymentId };
  }

  submitting.value = true;
  try {
    await submitCanvasPayment({
      id_canvas_order: idCanvasOrder,
      jumlah_dibayarkan: nominal,
      tipe_setoran: paymentForm.tipe_setoran || 'tunai',
      payment_id: activePaymentAttempt.id
    });
    activePaymentAttempt = { signature: '', id: '' };
    successMessage.value = 'Pembayaran Canvas tercatat sebagai claim sales dan menunggu Rekap pada Piutang Canvas Finance.';

    const selectedId = String(idCanvasOrder);
    await loadOrders();
    const refreshedOrder = orderRows.value.find((item) => String(item.id || item.id_canvas_order) === selectedId);
    if (refreshedOrder) await selectOrder(refreshedOrder);
  } catch (error) {
    // Keep the idempotency key for an unchanged retry: if the request reached
    // the server but its response was lost, the server returns the same claim
    // rather than inserting a second payment.
    errorMessage.value = normalizeError(error, 'Gagal menyimpan pembayaran Canvas.');
  } finally {
    submitting.value = false;
  }
}

async function applyFilters() {
  await loadSales();
  await loadOrders();
}

watch(
  () => filters.id_cabang,
  async (value, previous) => {
    if (String(value || '') === String(previous || '')) return;
    syncCompanyFromBranch();
    await loadSales();
  }
);

watch(
  () => filters.id_perusahaan,
  async (value, previous) => {
    if (String(value || '') === String(previous || '')) return;
    filters.id_principal = '';
    resetSalesFilter();
    await loadSales();
  }
);

watch(
  () => filters.id_principal,
  async (value, previous) => {
    if (String(value || '') === String(previous || '')) return;
    resetSalesFilter();
    await loadSales();
  }
);

onMounted(async () => {
  await loadReferences();
  await loadSales();
  await loadOrders();
});
</script>

<template>
  <PageHeader title="Tagihan Pembayaran Canvas" description="Monitor tagihan canvas, lihat riwayat pembayaran, dan submit pembayaran per canvas order.">
    <button class="btn btn-secondary" :disabled="loading" @click="applyFilters">Reload</button>
  </PageHeader>

  <section class="panel filter-panel">
    <AppSearchSelect v-model="filters.id_cabang" label="Cabang" :options="branchOptions" placeholder="Pilih cabang" :disabled="shouldLockBusinessScope && !!fallbackBranchId" @update:model-value="syncCompanyFromBranch" />
    <AppSearchSelect v-model="filters.id_perusahaan" label="Perusahaan" :options="companyOptions" placeholder="Pilih perusahaan" :disabled="shouldLockBusinessScope && !!fallbackCompanyId" @update:model-value="resetSalesFilter" />
    <AppSearchSelect v-model="filters.id_principal" label="Principal" :options="principalOptions" placeholder="Semua principal" @update:model-value="resetSalesFilter" />
    <AppSearchSelect v-model="filters.id_sales" label="Sales Canvas" :options="salesOptions" placeholder="Semua sales" :disabled="canUseLoginScope && !!fallbackSalesId" />
    <input v-model="filters.search" class="input" placeholder="Cari sales, customer..." />
    <button class="btn btn-primary" :disabled="loading" @click="applyFilters">Terapkan</button>
  </section>

  <div v-if="successMessage" class="alert success">{{ successMessage }}</div>
  <div v-if="errorMessage" class="alert error">{{ errorMessage }}</div>

  <section class="content-grid">
    <div class="panel">
      <h2>Daftar Tagihan</h2>
      <AppTable
        :columns="[
          { key: 'nama_sales', label: 'Sales' },
          { key: 'nama_customer', label: 'Customer' },
          { key: 'tanggal_label', label: 'Tanggal' },
          { key: 'tagihan_label', label: 'Tagihan' },
          { key: 'dibayar_label', label: 'Dibayar' },
          { key: 'sisa_label', label: 'Sisa' }
        ]"
        :rows="filteredOrders"
        :loading="loading"
        clickable-rows
        :selected-key="selectedOrder?.id || selectedOrder?.id_canvas_order || ''"
        @row-click="selectOrder"
      />
    </div>
  </section>

  <AppModal
    :open="paymentModalOpen"
    title="Pembayaran Canvas"
    :description="selectedOrder ? `Tagihan ${selectedOrder.nama_customer || '-'} dari ${selectedOrder.nama_sales || 'sales canvas'}` : 'Pilih tagihan canvas untuk membuka form pembayaran.'"
    size="6xl"
    @close="closePaymentModal"
  >
    <div v-if="selectedOrder" class="payment-box">
      <div class="selected-order">
        <div>
          <span>Customer</span>
          <strong>{{ selectedOrder.nama_customer || '-' }}</strong>
        </div>
        <div>
          <span>Sales Canvas</span>
          <strong>{{ selectedOrder.nama_sales || '-' }}</strong>
        </div>
        <div>
          <span>Tanggal Order</span>
          <strong>{{ formatDate(selectedOrder.tanggal_order) }}</strong>
        </div>
      </div>

      <div class="info-grid">
        <div class="info-card">
          <span>Total Tagihan</span>
          <strong>{{ formatCurrency(totalTagihan) }}</strong>
        </div>
        <div class="info-card">
          <span>Sudah Dibayar</span>
          <strong>{{ formatCurrency(totalDibayar) }}</strong>
        </div>
        <div class="info-card">
          <span>Sisa Tagihan</span>
          <strong>{{ formatCurrency(sisaTagihan) }}</strong>
        </div>
      </div>

      <section class="pay-form-card">
        <div>
          <h3>Form Pembayaran</h3>
          <p class="section-help">
            Nominal memakai total Canvas final setelah diskon dan PPN. Pembayaran ini tercatat sebagai claim sales; Rekap, bukti setoran, dan finalisasi diproses pada Piutang Canvas Finance secara terpisah dari faktur Sales Order.
          </p>
        </div>
        <div class="pay-form-grid">
          <label class="form-field amount-field">
            <span>Jumlah Dibayarkan</span>
            <input v-model="paymentForm.jumlah_dibayarkan" type="number" class="input" placeholder="0" :disabled="sisaTagihan <= 0" />
          </label>
          <label class="form-field method-field">
            <span>Metode Bayar</span>
            <select v-model="paymentForm.tipe_setoran" class="input" :disabled="sisaTagihan <= 0">
              <option value="tunai">Tunai</option>
              <option value="non_tunai">Non Tunai / Transfer</option>
            </select>
          </label>
          <label class="form-field note-field">
            <span>Catatan</span>
            <input v-model="paymentForm.keterangan" class="input" placeholder="Opsional" :disabled="sisaTagihan <= 0" />
          </label>
          <div class="pay-actions">
            <button class="btn btn-secondary" :disabled="sisaTagihan <= 0" @click="fillRemainingPayment">
              Isi Sisa Tagihan
            </button>
            <button class="btn btn-primary" :disabled="submitting || !canSubmitPayment" @click="submitPayment">
              {{ submitting ? 'Menyimpan...' : 'Simpan Claim Pembayaran Canvas' }}
            </button>
            <button class="btn btn-secondary" :disabled="!selectedOrder" @click="printPaymentReceipt()">
              Cetak Bukti Bayar
            </button>
          </div>
        </div>
      </section>

      <section>
        <h3>Riwayat Pembayaran</h3>
        <AppTable
          :columns="[
            { key: 'tanggal_label', label: 'Tanggal' },
            { key: 'nominal_label', label: 'Nominal' },
            { key: 'status_label', label: 'Status' }
          ]"
          :rows="historyTableRows"
          :loading="detailLoading"
          clickable-rows
          @row-click="printPaymentReceipt"
        />
      </section>
    </div>
    <div v-else class="empty">Pilih tagihan canvas untuk melihat detail pembayaran.</div>
  </AppModal>
</template>

<style scoped>
.panel,
.info-card {
  border: 1px solid rgba(148, 163, 184, 0.26);
  border-radius: 20px;
  background: rgba(15, 23, 42, 0.72);
}

.panel {
  padding: 20px;
}

.filter-panel {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 14px;
  margin-top: 18px;
  min-width: 0;
}

.content-grid {
  display: block;
  margin-top: 18px;
  min-width: 0;
}

h2,
h3 {
  margin: 0 0 16px;
}

.input {
  background: rgba(2, 6, 23, 0.82);
  border: 1px solid rgba(148, 163, 184, 0.32);
  border-radius: 14px;
  color: #fff;
  padding: 12px 14px;
  width: 100%;
}

.btn {
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 14px;
  color: #fff;
  cursor: pointer;
  font-weight: 900;
  padding: 12px 16px;
}

.btn:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.btn-primary {
  background: linear-gradient(135deg, #6b8f34, #8fb34b);
  border-color: transparent;
}

.btn-secondary {
  background: rgba(15, 23, 42, 0.82);
}

.btn.full {
  width: 100%;
}

.payment-box,
.info-grid {
  display: grid;
  gap: 14px;
}

.info-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.selected-order {
  background: linear-gradient(135deg, rgba(107, 143, 52, 0.22), rgba(14, 165, 233, 0.12));
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 22px;
  display: grid;
  gap: 14px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  padding: 16px;
}

.selected-order span {
  color: #93a7c5;
  display: block;
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.selected-order strong {
  color: #fff;
  display: block;
  margin-top: 8px;
}

.info-card {
  padding: 14px;
}

.pay-form-card {
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 22px;
  background: rgba(15, 23, 42, 0.5);
  display: grid;
  gap: 16px;
  padding: 16px;
}

.section-help {
  color: #93a7c5;
  font-size: 13px;
  margin: -8px 0 0;
}

.pay-form-grid {
  align-items: end;
  display: grid;
  gap: 14px;
  grid-template-columns: minmax(240px, 1.4fr) minmax(190px, 0.7fr);
}

.note-field {
  grid-column: 1 / 2;
}

.pay-actions {
  align-self: stretch;
  display: grid;
  gap: 10px;
  grid-column: 2 / 3;
  grid-row: 1 / span 2;
}

.pay-actions .btn {
  min-height: 48px;
}

.info-card span,
.form-field span {
  color: #93a7c5;
  display: block;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.info-card strong {
  color: #fff;
  display: block;
  margin-top: 8px;
}

.form-field {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.alert {
  border-radius: 16px;
  font-weight: 800;
  margin-top: 16px;
  padding: 14px 16px;
}

.alert.success {
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.3);
  color: #6ee7b7;
}

.alert.error {
  background: rgba(244, 63, 94, 0.12);
  border: 1px solid rgba(244, 63, 94, 0.3);
  color: #fda4af;
}

.empty {
  color: #9fb5d4;
  padding: 28px;
  text-align: center;
}

@media (max-width: 1200px) {
  .info-grid,
  .selected-order,
  .pay-form-grid {
    grid-template-columns: 1fr;
  }

  .note-field,
  .pay-actions {
    grid-column: auto;
    grid-row: auto;
  }
}
</style>
