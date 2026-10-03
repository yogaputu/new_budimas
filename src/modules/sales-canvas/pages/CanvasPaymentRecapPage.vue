<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import {
  getCanvasOrders,
  getCanvasPaymentRecap,
  getCanvasRequests,
  getCanvasReturnHistory,
  getCanvasSalesList
} from '@/api/salesCanvas';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
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
  tanggal_mulai: firstDayOfMonth(),
  tanggal_selesai: todayDate(),
  search: ''
});

const branchRows = ref([]);
const companyRows = ref([]);
const principalRows = ref([]);
const salesRows = ref([]);
const rows = ref([]);
const requestHistoryRows = ref([]);
const orderHistoryRows = ref([]);
const returnHistoryRows = ref([]);
const loading = ref(false);
const errorMessage = ref('');

const userId = computed(() => getCurrentUserId(authStore.user));
const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(authStore.user));
const fallbackSalesId = computed(() => getLoginSalesId(authStore.user));
const canUseLoginScope = computed(() => shouldLockToLoginSales(authStore));
const shouldLockBusinessScope = computed(() => !isSuperUser(authStore));

function todayDate() {
  return toLocalDateInput(new Date());
}

function firstDayOfMonth() {
  const now = new Date();
  return toLocalDateInput(new Date(now.getFullYear(), now.getMonth(), 1));
}

function toLocalDateInput(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

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

const tableRows = computed(() => {
  const query = filters.search.trim().toLowerCase();
  return rows.value
    .filter((item) => {
      if (!query) return true;
      return [item.nama_customer, item.kode_customer, item.id_canvas_order, item.nominal]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query));
    })
    .map((item) => ({
      ...item,
      tanggal_label: formatDate(item.tanggal_input),
      nominal_label: formatCurrency(item.nominal),
      tagihan_label: formatCurrency(item.total_tagihan),
      status_label: Array.isArray(item.status_setoran) ? item.status_setoran.join(', ') : (item.status_setoran || '-')
    }));
});

function isWithinSelectedDate(value) {
  if (!value) return true;
  const day = String(value).slice(0, 10);
  if (!day) return true;
  if (filters.tanggal_mulai && day < filters.tanggal_mulai) return false;
  if (filters.tanggal_selesai && day > filters.tanggal_selesai) return false;
  return true;
}

const activityTableRows = computed(() => {
  const query = filters.search.trim().toLowerCase();
  const entries = [
    ...requestHistoryRows.value.map((item) => ({
      key: `request-${item.id || item.id_canvas || ''}-${item.tanggal_request || ''}`,
      activity: 'Request Canvas',
      code: item.kode_request || `Request #${item.id || item.id_canvas || '-'}`,
      customer: item.nama_customer || item.nama_sales || '-',
      date: item.tanggal_request || item.created_at || '',
      nominal: Number(item.total_request || item.total || 0),
      status: item.status_label || item.status || '-'
    })),
    ...orderHistoryRows.value.map((item) => ({
      key: `order-${item.id || item.id_canvas_order || ''}-${item.tanggal_order || ''}`,
      activity: 'Order Canvas',
      code: item.kode_order || `Order #${item.id || item.id_canvas_order || '-'}`,
      customer: item.nama_customer || item.kode_customer || '-',
      date: item.tanggal_order || item.created_at || '',
      nominal: Number(item.total_order || item.total || 0),
      status: item.status_label || item.status || '-'
    })),
    ...returnHistoryRows.value.map((item) => ({
      key: `return-${item.id_return || item.id || ''}-${item.tanggal_return || ''}`,
      activity: 'Retur Canvas',
      code: item.kode_return || `Retur #${item.id_return || item.id || '-'}`,
      customer: item.nama_sales || item.nama_principal || '-',
      date: item.tanggal_return || item.created_at || '',
      nominal: Number(item.total_qty_detail || item.total_qty || 0),
      status: item.status_label || (Number(item.status || 0) === 1 ? 'Dikembalikan' : 'Draft'),
      quantity: true
    }))
  ];

  return entries
    .filter((item) => isWithinSelectedDate(item.date))
    .filter((item) => !query || [item.activity, item.code, item.customer, item.status]
      .some((value) => String(value || '').toLowerCase().includes(query)))
    .sort((left, right) => String(right.date || '').localeCompare(String(left.date || '')))
    .map((item) => ({
      ...item,
      tanggal_label: formatDate(item.date),
      nominal_label: item.quantity ? `${Number(item.nominal || 0).toLocaleString('id-ID')} pcs` : formatCurrency(item.nominal),
      status_label: String(item.status || '-').replace(/_/g, ' ')
    }));
});

const summaryCards = computed(() => {
  const totalNominal = rows.value.reduce((sum, item) => sum + Number(item.nominal || 0), 0);
  const totalTagihan = rows.value.reduce((sum, item) => sum + Number(item.total_tagihan || 0), 0);
  return [
    { label: 'Baris Rekap', value: String(rows.value.length) },
    { label: 'Total Setoran', value: formatCurrency(totalNominal) },
    { label: 'Total Tagihan', value: formatCurrency(totalTagihan) },
    { label: 'Order Canvas', value: String(new Set(rows.value.map((item) => item.id_canvas_order)).size) },
    { label: 'Aktivitas Canvas', value: String(activityTableRows.value.length) }
  ];
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

async function loadData() {
  loading.value = true;
  errorMessage.value = '';
  try {
    const params = {
      id_cabang: filters.id_cabang,
      id_perusahaan: filters.id_perusahaan,
      id_principal: filters.id_principal,
      id_sales: filters.id_sales,
      tanggal_mulai: filters.tanggal_mulai,
      tanggal_selesai: filters.tanggal_selesai
    };
    const [payments, requests, orders, returns] = await Promise.allSettled([
      getCanvasPaymentRecap(userId.value, params),
      getCanvasRequests(userId.value, params),
      getCanvasOrders(userId.value, params),
      getCanvasReturnHistory(userId.value, params)
    ]);

    if (payments.status === 'rejected') throw payments.reason;
    rows.value = normalizeList(unwrapResponse(payments.value));
    requestHistoryRows.value = requests.status === 'fulfilled' ? normalizeList(unwrapResponse(requests.value)) : [];
    orderHistoryRows.value = orders.status === 'fulfilled' ? normalizeList(unwrapResponse(orders.value)) : [];
    returnHistoryRows.value = returns.status === 'fulfilled' ? normalizeList(unwrapResponse(returns.value)) : [];
  } catch (error) {
    errorMessage.value = normalizeError(error);
    requestHistoryRows.value = [];
    orderHistoryRows.value = [];
    returnHistoryRows.value = [];
  } finally {
    loading.value = false;
  }
}

async function applyFilters() {
  await loadSales();
  await loadData();
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
  await loadData();
});
</script>

<template>
  <PageHeader title="Riwayat Canvas" description="Riwayat tagihan dan pembayaran Canvas. Riwayat retur tetap tersedia dari proses Retur Canvas untuk audit operasional.">
    <button class="btn btn-secondary" :disabled="loading" @click="applyFilters">Reload</button>
  </PageHeader>

  <section class="panel recap-filter">
    <div class="filter-main">
      <AppSearchSelect v-model="filters.id_cabang" label="Cabang" :options="branchOptions" placeholder="Pilih cabang" :disabled="shouldLockBusinessScope && !!fallbackBranchId" @update:model-value="syncCompanyFromBranch" />
      <AppSearchSelect v-model="filters.id_perusahaan" label="Perusahaan" :options="companyOptions" placeholder="Pilih perusahaan" :disabled="shouldLockBusinessScope && !!fallbackCompanyId" @update:model-value="resetSalesFilter" />
      <AppSearchSelect v-model="filters.id_principal" label="Principal" :options="principalOptions" placeholder="Semua principal" @update:model-value="resetSalesFilter" />
      <AppSearchSelect v-model="filters.id_sales" label="Sales Canvas" :options="salesOptions" placeholder="Semua sales" :disabled="canUseLoginScope && !!fallbackSalesId" />
    </div>

    <div class="filter-secondary">
      <label class="date-field">
        <span>Dari Tanggal</span>
        <input v-model="filters.tanggal_mulai" type="date" class="input" />
      </label>
      <label class="date-field">
        <span>Sampai Tanggal</span>
        <input v-model="filters.tanggal_selesai" type="date" class="input" />
      </label>
      <label class="search-field">
        <span>Cari Data</span>
        <input v-model="filters.search" class="input" placeholder="Cari customer/order..." />
      </label>
      <button class="btn btn-primary" :disabled="loading" @click="applyFilters">Terapkan</button>
    </div>
  </section>

  <div v-if="errorMessage" class="alert error">{{ errorMessage }}</div>

  <section class="summary-grid">
    <div v-for="card in summaryCards" :key="card.label" class="summary-card">
      <span>{{ card.label }}</span>
      <strong>{{ card.value }}</strong>
    </div>
  </section>

  <section class="panel">
    <div class="history-panel-heading">
      <div>
        <span>Riwayat Operasional Canvas</span>
        <strong>Request, order, dan retur Canvas dalam satu riwayat.</strong>
      </div>
    </div>
    <AppTable
      :columns="[
        { key: 'activity', label: 'Aktivitas' },
        { key: 'code', label: 'Dokumen' },
        { key: 'customer', label: 'Customer / Konteks' },
        { key: 'tanggal_label', label: 'Tanggal' },
        { key: 'nominal_label', label: 'Nilai / Qty' },
        { key: 'status_label', label: 'Status' }
      ]"
      :rows="activityTableRows"
      :loading="loading"
      empty-message="Belum ada aktivitas Canvas pada filter ini."
    />
  </section>

  <section class="panel payment-history-panel">
    <div class="history-panel-heading">
      <div>
        <span>Riwayat Tagihan Canvas</span>
        <strong>Rekap pembayaran yang dicatat untuk order Canvas.</strong>
      </div>
    </div>
    <AppTable
      :columns="[
        { key: 'id_canvas_order', label: 'Order Canvas' },
        { key: 'nama_customer', label: 'Customer' },
        { key: 'tanggal_label', label: 'Tanggal' },
        { key: 'nominal_label', label: 'Nominal' },
        { key: 'tagihan_label', label: 'Tagihan' },
        { key: 'status_label', label: 'Status' }
      ]"
      :rows="tableRows"
      :loading="loading"
    />
  </section>
</template>

<style scoped>
.panel,
.summary-card {
  border: 1px solid rgba(148, 163, 184, 0.26);
  border-radius: 20px;
  background: rgba(15, 23, 42, 0.72);
}

.panel {
  padding: 20px;
}

.recap-filter {
  display: grid;
  gap: 16px;
  margin-top: 18px;
}

.filter-main,
.filter-secondary {
  align-items: end;
  display: grid;
  gap: 14px;
  min-width: 0;
}

.filter-main {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.filter-secondary {
  grid-template-columns: minmax(180px, 0.65fr) minmax(180px, 0.65fr) minmax(260px, 1.2fr) 220px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin: 18px 0;
}

.summary-card {
  padding: 18px;
}

.summary-card span,
.field span {
  color: #93a7c5;
  display: block;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.summary-card strong {
  color: #fff;
  display: block;
  font-size: 22px;
  margin-top: 10px;
}

.history-panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.history-panel-heading span,
.history-panel-heading strong {
  display: block;
}

.history-panel-heading span {
  color: #7dd3fc;
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.history-panel-heading strong {
  color: #e2e8f0;
  margin-top: 5px;
}

.payment-history-panel { margin-top: 18px; }

.field,
.date-field,
.search-field {
  display: grid;
  gap: 8px;
}

.date-field span,
.search-field span {
  color: #93a7c5;
  display: block;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.1em;
  text-transform: uppercase;
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

.btn-primary {
  background: linear-gradient(135deg, #6b8f34, #8fb34b);
  border-color: transparent;
}

.btn-secondary {
  background: rgba(15, 23, 42, 0.82);
}

.alert.error {
  background: rgba(244, 63, 94, 0.12);
  border: 1px solid rgba(244, 63, 94, 0.3);
  border-radius: 16px;
  color: #fda4af;
  font-weight: 800;
  margin-top: 16px;
  padding: 14px 16px;
}

@media (max-width: 1200px) {
  .filter-main,
  .filter-secondary,
  .summary-grid {
    grid-template-columns: 1fr;
  }
}
</style>
