<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies, getPrincipals, getProductOptions, getProductOptionsByPrincipal, getSales } from '@/api/master';
import { getSupervisorCustomerMap } from '@/api/sales';
import { useAuthStore } from '@/app/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { scopeSalesRowsByLogin } from '@/utils/accessScope';
import {
  getBranchOptionsForCompany,
  getCompanyOptionsForScope,
  resetBranchWhenCompanyChanges,
} from '@/utils/filterScope';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const auth = useAuthStore();

const mapRef = ref(null);
const loading = reactive({ references: false, map: false, products: false });
const error = ref('');
const feedback = ref('');
const companies = ref([]);
const branches = ref([]);
const principals = ref([]);
const salesRows = ref([]);
const productRows = ref([]);
const mapRows = ref([]);
const summary = ref({});
const selectedProduct = ref(null);
const selectedKey = ref('');
const activeSideTab = ref('detail');
const listSearch = ref('');

const filters = reactive({
  companyId: '',
  branchId: '',
  principalId: '',
  salesId: '',
  productId: '',
  search: '',
  days: 180
});

let leafletLoader = null;
let mapInstance = null;
let markerLayer = null;
let markerMap = new Map();

const companyOptions = computed(() => getCompanyOptionsForScope(companies.value, auth, true));

const branchOptions = computed(() =>
  getBranchOptionsForCompany(branches.value, auth, filters.companyId, true, companies.value)
);

const principalOptions = computed(() => {
  const companyId = String(filters.companyId || '');
  const rows = principals.value.filter((item) => {
    if (!companyId) return true;
    return String(item.id_perusahaan || item.company_id || item.perusahaan_id || '') === companyId;
  });
  const options = rows.map((item) => ({
    value: String(item.id),
    label: item.nama || item.nama_principal || 'Principal'
  }));
  return [{ value: '', label: 'Semua principal' }, ...options];
});

const salesOptions = computed(() => {
  const branchId = String(filters.branchId || '');
  const principalId = String(filters.principalId || '');

  const rows = scopeSalesRowsByLogin(salesRows.value, auth).filter((item) => {
    const itemBranchId = String(item.id_cabang || item.cabang_id || item.idCabang || '');
    const itemPrincipalIds = String(item.id_principals || item.principal_ids || item.id_principal || '')
      .split(',')
      .map((value) => value.trim())
      .filter(Boolean);

    const branchMatches = !branchId || itemBranchId === branchId;
    const principalMatches = !principalId || itemPrincipalIds.includes(principalId) || String(item.id_principal || '') === principalId;
    return branchMatches && principalMatches;
  });

  return [
    { value: '', label: 'Semua sales' },
    ...rows.map((item) => ({
      value: String(item.id_sales || item.sales_id || item.id),
      label: `${item.kode_sales || item.kode || '-'} - ${item.nama || item.nama_sales || 'Sales'}`
    }))
  ];
});

const productOptions = computed(() => [
  { value: '', label: 'Semua barang' },
  ...productRows.value.map((item) => ({
    value: String(item.id || item.produk_id),
    label: `${item.kode_sku || item.kode || '-'} - ${item.nama || item.nama_produk || 'Barang'}`
  }))
]);

const validPoints = computed(() =>
  mapRows.value
    .map((row, index) => ({
      ...row,
      markerKey: String(row.id_customer || row.kode_customer || index),
      latitudeNumber: Number(row.latitude),
      longitudeNumber: Number(row.longitude)
    }))
    .filter((row) => Number.isFinite(row.latitudeNumber) && Number.isFinite(row.longitudeNumber))
    .filter((row) =>
      row.latitudeNumber >= -11
      && row.latitudeNumber <= 6
      && row.longitudeNumber >= 95
      && row.longitudeNumber <= 141
    )
);

const selectedPoint = computed(() =>
  validPoints.value.find((row) => String(row.markerKey) === String(selectedKey.value)) || validPoints.value[0] || null
);

const summaryCards = computed(() => [
  { label: 'Customer Map', value: numberLabel(summary.value.total_customers || validPoints.value.length), tone: 'sky' },
  { label: 'Order Aktif', value: numberLabel(summary.value.ordered_in_window || 0), tone: 'emerald' },
  {
    label: filters.productId ? 'Order Barang' : 'Punya Order',
    value: numberLabel(filters.productId ? summary.value.product_customers || 0 : summary.value.ordered_in_window || 0),
    tone: 'amber'
  },
  { label: 'Tidak Order 30 Hari', value: numberLabel(summary.value.inactive_30_days || 0), tone: 'rose' }
]);

const filteredCustomerPoints = computed(() => {
  const keyword = listSearch.value.trim().toLowerCase();
  if (!keyword) return validPoints.value;

  return validPoints.value.filter((point) =>
    [
      point.nama_customer,
      point.kode_customer,
      point.nama_cabang,
      point.nama_sales_list,
      point.nama_principal_list,
    ]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(keyword))
  );
});

function activeBranchId() {
  return String(auth.user?.cabang?.id || auth.user?.cabang_id || auth.user?.id_cabang || '');
}

function activeCompanyId(branchId = '') {
  return String(
    auth.user?.perusahaan?.id ||
    auth.user?.id_perusahaan ||
    branches.value.find((item) => String(item.id) === String(branchId))?.id_perusahaan ||
    ''
  );
}

function numberLabel(value) {
  return Number(value || 0).toLocaleString('id-ID');
}

function moneyLabel(value) {
  return `Rp ${Number(value || 0).toLocaleString('id-ID', { maximumFractionDigits: 0 })}`;
}

function dateLabel(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' });
}

function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function payloadRows(response) {
  const payload = unwrapResponse(response);
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.rows)) return payload.rows;
  if (Array.isArray(payload?.items)) return payload.items;
  return normalizeList(payload);
}

function buildMapParams() {
  return {
    id_perusahaan: filters.companyId || undefined,
    id_cabang: filters.branchId || undefined,
    id_principal: filters.principalId || undefined,
    id_sales: filters.salesId || undefined,
    id_produk: filters.productId || undefined,
    search: filters.search || undefined,
    days: filters.days || 180
  };
}

async function loadReferences() {
  loading.references = true;
  error.value = '';

  try {
    const [companyResponse, branchResponse, principalResponse, salesResponse] = await Promise.all([
      getCompanies(),
      getBranches(),
      getPrincipals(),
      getSales()
    ]);

    companies.value = normalizeList(unwrapResponse(companyResponse));
    branches.value = normalizeList(unwrapResponse(branchResponse));
    principals.value = normalizeList(unwrapResponse(principalResponse));
    salesRows.value = normalizeList(unwrapResponse(salesResponse));

    const branchId = activeBranchId();
    if (!filters.branchId && branchId) {
      filters.branchId = branchId;
    }
    if (!filters.companyId) {
      filters.companyId = activeCompanyId(filters.branchId);
    }
  } catch (err) {
    error.value = normalizeError(err, 'Referensi mapping customer belum bisa dimuat.');
  } finally {
    loading.references = false;
  }
}

async function loadProductOptions(search = '') {
  loading.products = true;

  try {
    const params = {
      search,
      limit: 50,
      id_principal: filters.principalId || undefined
    };
    const response = filters.principalId
      ? await getProductOptionsByPrincipal(filters.principalId, params)
      : await getProductOptions(params);

    productRows.value = payloadRows(response).slice(0, 50);
  } catch (err) {
    productRows.value = [];
  } finally {
    loading.products = false;
  }
}

async function loadMapData() {
  loading.map = true;
  error.value = '';
  feedback.value = '';

  try {
    const response = await getSupervisorCustomerMap(buildMapParams());
    const payload = unwrapResponse(response) || {};
    mapRows.value = normalizeList(payload.rows).map((row, index) => ({
      ...row,
      markerKey: String(row.id_customer || row.kode_customer || index)
    }));
    summary.value = payload.summary || {};
    selectedProduct.value = payload.selected_product || null;
    selectedKey.value = validPoints.value[0]?.markerKey || '';
    feedback.value = `Mapping customer memuat ${numberLabel(validPoints.value.length)} titik.`;
    await renderMap();
  } catch (err) {
    error.value = normalizeError(err, 'Mapping customer belum bisa dimuat.');
    mapRows.value = [];
    summary.value = {};
    selectedProduct.value = null;
    selectedKey.value = '';
    destroyMap();
  } finally {
    loading.map = false;
  }
}

function resetFilters() {
  filters.principalId = '';
  filters.salesId = '';
  filters.productId = '';
  filters.search = '';
  filters.days = 180;
  loadProductOptions();
  loadMapData();
}

function loadLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (leafletLoader) return leafletLoader;

  leafletLoader = new Promise((resolve, reject) => {
    if (!document.querySelector('link[data-leaflet-runtime="true"]')) {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
      link.dataset.leafletRuntime = 'true';
      document.head.appendChild(link);
    }

    const existingScript = document.querySelector('script[data-leaflet-runtime="true"]');
    if (existingScript) {
      existingScript.addEventListener('load', () => resolve(window.L));
      existingScript.addEventListener('error', () => reject(new Error('Leaflet gagal dimuat.')));
      return;
    }

    const script = document.createElement('script');
    script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
    script.async = true;
    script.dataset.leafletRuntime = 'true';
    script.onload = () => resolve(window.L);
    script.onerror = () => reject(new Error('Leaflet gagal dimuat.'));
    document.body.appendChild(script);
  });

  return leafletLoader;
}

function destroyMap() {
  markerMap.clear();
  if (mapInstance) {
    mapInstance.remove();
    mapInstance = null;
    markerLayer = null;
  }
}

function markerTone(point) {
  if (!filters.productId) return { bg: '#0ea5e9', border: '#0369a1', ring: point.inactive_30_days ? '#fecdd3' : '#bae6fd' };

  const level = String(point.product_frequency_level || 'none');
  if (level === 'high') return { bg: '#ef4444', border: '#991b1b', ring: '#fee2e2' };
  if (level === 'medium') return { bg: '#f59e0b', border: '#b45309', ring: '#fef3c7' };
  if (level === 'low') return { bg: '#10b981', border: '#047857', ring: '#d1fae5' };
  return { bg: '#64748b', border: '#334155', ring: '#e2e8f0' };
}

function buildMarkerIcon(L, point, isActive = false) {
  const tone = markerTone(point);
  const inactive = Boolean(point.inactive_30_days);
  const ringSize = isActive ? 42 : inactive ? 36 : 30;
  const coreSize = isActive ? 22 : 18;

  return L.divIcon({
    className: '',
    iconSize: [ringSize, ringSize],
    iconAnchor: [ringSize / 2, ringSize / 2],
    popupAnchor: [0, -(ringSize / 2)],
    html: `
      <div style="position:relative;width:${ringSize}px;height:${ringSize}px;display:flex;align-items:center;justify-content:center;">
        <div style="
          width:${ringSize}px;
          height:${ringSize}px;
          border-radius:999px;
          background:${isActive || inactive ? tone.ring : 'transparent'};
          border:${inactive ? '2px dashed #f43f5e' : isActive ? '2px solid rgba(248,250,252,.92)' : '0'};
          opacity:${isActive || inactive ? '1' : '0'};
        "></div>
        <div style="
          position:absolute;
          width:${coreSize}px;
          height:${coreSize}px;
          border-radius:999px;
          background:${tone.bg};
          border:3px solid ${tone.border};
          box-shadow:0 9px 18px rgba(15,23,42,.28);
        "></div>
      </div>
    `
  });
}

function popupHtml(point) {
  const productLine = filters.productId
    ? `<div><strong>Order barang:</strong> ${numberLabel(point.product_order_count)} nota / ${numberLabel(point.product_qty)} qty</div>`
    : '';

  return `
    <div style="min-width:260px;font-family:Arial,sans-serif;color:#0f172a;">
      <div style="font-weight:800;margin-bottom:4px;">${escapeHtml(point.nama_customer || 'Customer')}</div>
      <div style="font-size:12px;line-height:1.6;">
        <div><strong>Kode:</strong> ${escapeHtml(point.kode_customer || '-')}</div>
        <div><strong>Sales:</strong> ${escapeHtml(point.nama_sales_list || '-')}</div>
        <div><strong>Principal:</strong> ${escapeHtml(point.nama_principal_list || '-')}</div>
        <div><strong>Cabang:</strong> ${escapeHtml(point.nama_cabang || '-')}</div>
        <div><strong>Order terakhir:</strong> ${escapeHtml(dateLabel(point.last_order_date))}</div>
        <div><strong>Total order:</strong> ${numberLabel(point.total_order)} nota / ${escapeHtml(moneyLabel(point.total_order_value))}</div>
        ${productLine}
        <div><strong>Status 30 hari:</strong> ${point.inactive_30_days ? 'Belum order' : 'Aktif order'}</div>
      </div>
    </div>
  `;
}

function updateMarkerIcons() {
  if (!window.L) return;
  markerMap.forEach(({ marker, point }) => {
    marker.setIcon(buildMarkerIcon(window.L, point, String(point.markerKey) === String(selectedKey.value)));
  });
}

function focusMarker(markerKey, options = {}) {
  const key = String(markerKey || '');
  if (!key || !markerMap.has(key)) return;

  const entry = markerMap.get(key);
  selectedKey.value = key;
  updateMarkerIcons();

  if (options.fly !== false && mapInstance) {
    mapInstance.flyTo(entry.marker.getLatLng(), Math.max(mapInstance.getZoom(), 15), { duration: 0.5 });
    entry.marker.openPopup();
  }
}

async function renderMap() {
  await nextTick();
  if (!mapRef.value || !validPoints.value.length) {
    destroyMap();
    return;
  }

  const L = await loadLeaflet();
  destroyMap();

  mapInstance = L.map(mapRef.value, {
    zoomControl: true,
    attributionControl: true
  });

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(mapInstance);

  markerLayer = L.featureGroup().addTo(mapInstance);
  validPoints.value.forEach((point) => {
    const marker = L.marker([point.latitudeNumber, point.longitudeNumber], {
      icon: buildMarkerIcon(L, point, String(point.markerKey) === String(selectedKey.value))
    });
    marker.bindPopup(popupHtml(point));
    marker.on('click', () => focusMarker(point.markerKey, { fly: false }));
    marker.addTo(markerLayer);
    markerMap.set(String(point.markerKey), { marker, point });
  });

  const bounds = markerLayer.getBounds();
  if (bounds.isValid()) {
    mapInstance.fitBounds(bounds.pad(0.18), { maxZoom: 14 });
  }

  if (selectedKey.value) {
    window.setTimeout(() => focusMarker(selectedKey.value, { fly: false }), 80);
  }
}

function selectPoint(point) {
  activeSideTab.value = 'detail';
  focusMarker(point.markerKey);
}

watch(
  () => filters.companyId,
  () => {
    const branchReset = resetBranchWhenCompanyChanges(filters, 'companyId', 'branchId', branches.value, auth, companies.value);
    if (branchReset) filters.salesId = '';
    if (!principalOptions.value.some((item) => String(item.value) === String(filters.principalId))) {
      filters.principalId = '';
    }
    loadProductOptions();
  }
);

watch(
  () => [filters.branchId, filters.principalId],
  () => {
    if (!salesOptions.value.some((item) => String(item.value) === String(filters.salesId))) {
      filters.salesId = '';
    }
  }
);

watch(
  () => filters.principalId,
  () => {
    filters.productId = '';
    loadProductOptions();
  }
);

watch(selectedKey, updateMarkerIcons);

onMounted(async () => {
  await loadReferences();
  await loadProductOptions();
  await loadMapData();
});

onBeforeUnmount(destroyMap);
</script>

<template>
  <div class="space-y-5">
    <PageHeader
      title="Mapping Customer"
      description="Peta customer supervisor, histori order barang, dan status customer yang tidak order lebih dari 30 hari."
    >
      <div class="flex flex-wrap gap-2">
        <button
          class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900"
          :disabled="loading.map"
          @click="loadMapData"
        >
          {{ loading.map ? 'Memuat...' : 'Refresh' }}
        </button>
      </div>
    </PageHeader>

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-semibold text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-100">
      {{ error }}
    </section>

    <section class="panel p-4">
      <div class="customer-map-filter-bar">
        <div class="customer-map-filter">
          <AppSearchSelect v-model="filters.companyId" label="Perusahaan" placeholder="Pilih perusahaan" :options="companyOptions" :loading="loading.references" />
          <AppSearchSelect v-model="filters.branchId" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="!filters.companyId" empty-text="Pilih perusahaan terlebih dahulu." />
          <AppSearchSelect v-model="filters.salesId" label="Sales" placeholder="Semua sales" :options="salesOptions" empty-text="Sales belum tersedia untuk filter ini." />
          <AppSearchSelect v-model="filters.principalId" label="Principal" placeholder="Semua principal" :options="principalOptions" :disabled="!filters.companyId" empty-text="Pilih perusahaan terlebih dahulu." />
          <AppSearchSelect
            v-model="filters.productId"
            label="Barang"
            placeholder="Cari barang"
            :options="productOptions"
            :loading="loading.products"
            :remote-search="true"
            :max-visible-options="50"
            empty-text="Ketik kode atau nama barang."
            @search="loadProductOptions"
          />
          <AppFormField v-model="filters.search" label="Customer" placeholder="Kode, nama, alamat" />
          <AppFormField v-model="filters.days" label="Window" type="number" min="30" max="365" />
        </div>

        <div class="customer-map-actions">
          <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60" :disabled="loading.map" @click="loadMapData">
            Terapkan
          </button>
          <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" @click="resetFilters">
            Reset
          </button>
          <span v-if="feedback" class="customer-map-feedback">{{ feedback }}</span>
        </div>
      </div>
    </section>

    <section class="grid gap-2 md:grid-cols-4">
      <article v-for="card in summaryCards" :key="card.label" :class="['customer-map-card', `tone-${card.tone}`]">
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
      </article>
    </section>

    <section class="customer-map-layout">
      <div class="customer-map-canvas-wrap">
        <div ref="mapRef" class="customer-map-canvas"></div>
        <div v-if="loading.map" class="customer-map-overlay">Memuat mapping...</div>
        <div v-else-if="!validPoints.length" class="customer-map-overlay">Belum ada titik customer.</div>
        <div class="customer-map-legend">
          <span><i class="legend-high"></i> Tinggi</span>
          <span><i class="legend-medium"></i> Sedang</span>
          <span><i class="legend-low"></i> Rendah</span>
          <span><i class="legend-none"></i> Belum order barang</span>
          <span><i class="legend-inactive"></i> Tidak order 30 hari</span>
        </div>
      </div>

      <aside class="customer-map-side">
        <div class="customer-map-tabs">
          <button type="button" :class="{ active: activeSideTab === 'detail' }" @click="activeSideTab = 'detail'">
            Detail
          </button>
          <button type="button" :class="{ active: activeSideTab === 'list' }" @click="activeSideTab = 'list'">
            Customer
          </button>
        </div>

        <div v-if="activeSideTab === 'detail'" class="customer-map-detail">
          <p class="customer-map-eyebrow">Detail Marker</p>
          <h3>{{ selectedPoint?.nama_customer || '-' }}</h3>
          <dl>
            <div>
              <dt>Kode</dt>
              <dd>{{ selectedPoint?.kode_customer || '-' }}</dd>
            </div>
            <div>
              <dt>Cabang</dt>
              <dd>{{ selectedPoint?.nama_cabang || '-' }}</dd>
            </div>
            <div>
              <dt>Sales</dt>
              <dd>{{ selectedPoint?.nama_sales_list || '-' }}</dd>
            </div>
            <div>
              <dt>Principal</dt>
              <dd>{{ selectedPoint?.nama_principal_list || '-' }}</dd>
            </div>
            <div>
              <dt>Order Terakhir</dt>
              <dd>{{ dateLabel(selectedPoint?.last_order_date) }}</dd>
            </div>
            <div>
              <dt>Total Order</dt>
              <dd>{{ numberLabel(selectedPoint?.total_order) }} nota / {{ moneyLabel(selectedPoint?.total_order_value) }}</dd>
            </div>
            <div v-if="filters.productId">
              <dt>Barang Dipilih</dt>
              <dd>{{ selectedProduct?.nama || selectedPoint?.nama_produk || '-' }}</dd>
            </div>
            <div v-if="filters.productId">
              <dt>Order Barang</dt>
              <dd>{{ numberLabel(selectedPoint?.product_order_count) }} nota / {{ numberLabel(selectedPoint?.product_qty) }} qty</dd>
            </div>
            <div>
              <dt>Status 30 Hari</dt>
              <dd>{{ selectedPoint?.inactive_30_days ? 'Belum pesan' : 'Aktif pesan' }}</dd>
            </div>
          </dl>
        </div>

        <div v-else class="customer-map-list">
          <div class="customer-map-list-head">
            <p>Customer</p>
            <span>{{ numberLabel(filteredCustomerPoints.length) }}</span>
          </div>
          <div class="customer-map-list-search">
            <input v-model="listSearch" type="search" placeholder="Cari customer, cabang, sales" />
          </div>
          <button
            v-for="point in filteredCustomerPoints.slice(0, 120)"
            :key="point.markerKey"
            type="button"
            :class="['customer-map-row', { active: String(point.markerKey) === String(selectedKey) }]"
            @click="selectPoint(point)"
          >
            <span>
              <strong>{{ point.nama_customer || '-' }}</strong>
              <small>{{ point.kode_customer || '-' }} | {{ point.nama_cabang || '-' }}</small>
            </span>
            <em>{{ point.inactive_30_days ? '30+' : numberLabel(point.product_order_count || point.total_order) }}</em>
          </button>
          <p v-if="filteredCustomerPoints.length > 120" class="customer-map-list-note">
            Menampilkan 120 data pertama. Persempit dengan filter atau pencarian customer.
          </p>
        </div>
      </aside>
    </section>
  </div>
</template>

<style scoped>
.customer-map-filter-bar {
  min-width: 0;
  container-type: inline-size;
}

.customer-map-filter {
  display: grid;
  /*
   * Keep this filter deliberately capped at four columns.  An auto-fit grid
   * would use every available column on a wide browser or lower zoom level,
   * which is exactly what made the labels and selected values look clipped.
   */
  grid-template-columns: repeat(4, minmax(220px, 1fr));
  align-items: end;
  gap: 16px;
}

.customer-map-filter > :deep(label) {
  min-width: 0;
}

/* The customer lookup benefits from the extra room while keeping the window
 * input on the same logical row as the product criteria. */
.customer-map-filter > :deep(label:nth-child(6)) {
  grid-column: span 2;
}

.customer-map-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  margin-top: 14px;
  min-width: 0;
}

.customer-map-feedback {
  flex-basis: 100%;
  color: #0369a1;
  font-size: 12px;
  font-weight: 800;
  line-height: 1.35;
  text-align: left;
}

@container (max-width: 1120px) {
  .customer-map-filter {
    grid-template-columns: repeat(3, minmax(220px, 1fr));
  }
}

@container (max-width: 820px) {
  .customer-map-filter {
    grid-template-columns: repeat(2, minmax(220px, 1fr));
  }
}

@container (max-width: 560px) {
  .customer-map-filter {
    grid-template-columns: minmax(0, 1fr);
  }

  .customer-map-filter > :deep(label:nth-child(6)) {
    grid-column: auto;
  }
}

.dark .customer-map-feedback {
  color: #bae6fd;
}

.customer-map-card {
  border: 1px solid rgba(148, 163, 184, 0.2);
  background: rgba(15, 23, 42, 0.04);
  padding: 12px 14px;
}

.dark .customer-map-card {
  background: rgba(15, 23, 42, 0.78);
}

.customer-map-card span,
.customer-map-eyebrow,
.customer-map-detail dt,
.customer-map-list-head p {
  color: #64748b;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0;
  text-transform: uppercase;
}

.dark .customer-map-card span,
.dark .customer-map-eyebrow,
.dark .customer-map-detail dt,
.dark .customer-map-list-head p {
  color: #94a3b8;
}

.customer-map-card strong {
  display: block;
  margin-top: 6px;
  color: #0f172a;
  font-size: 24px;
  line-height: 1;
}

.dark .customer-map-card strong {
  color: #f8fafc;
}

.tone-sky { border-color: rgba(14, 165, 233, 0.34); }
.tone-emerald { border-color: rgba(16, 185, 129, 0.34); }
.tone-amber { border-color: rgba(245, 158, 11, 0.38); }
.tone-rose { border-color: rgba(244, 63, 94, 0.34); }

.customer-map-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: 14px;
  height: clamp(540px, calc(100vh - 300px), 720px);
  min-height: 0;
}

.customer-map-canvas-wrap {
  position: relative;
  min-height: 0;
  height: 100%;
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.2);
  background: #0f172a;
}

.customer-map-canvas {
  width: 100%;
  height: 100%;
  min-height: 0;
}

:deep(.leaflet-container) {
  width: 100%;
  height: 100%;
  font-family: inherit;
}

.customer-map-overlay {
  position: absolute;
  left: 50%;
  top: 50%;
  z-index: 500;
  transform: translate(-50%, -50%);
  border: 1px solid rgba(148, 163, 184, 0.28);
  background: rgba(2, 6, 23, 0.78);
  color: #f8fafc;
  font-weight: 800;
  padding: 12px 16px;
  backdrop-filter: blur(14px);
}

.customer-map-legend {
  position: absolute;
  left: 14px;
  bottom: 14px;
  z-index: 500;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  max-width: calc(100% - 28px);
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(2, 6, 23, 0.78);
  color: #e2e8f0;
  padding: 10px;
  backdrop-filter: blur(14px);
}

.customer-map-legend span {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  font-weight: 800;
}

.customer-map-legend i {
  display: block;
  width: 13px;
  height: 13px;
  border-radius: 999px;
}

.legend-high { background: #ef4444; }
.legend-medium { background: #f59e0b; }
.legend-low { background: #10b981; }
.legend-none { background: #64748b; }
.legend-inactive {
  background: #f8fafc;
  border: 2px dashed #f43f5e;
}

.customer-map-side {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
  min-width: 0;
  min-height: 0;
}

.customer-map-tabs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  background: rgba(15, 23, 42, 0.04);
  padding: 6px;
}

.dark .customer-map-tabs {
  background: rgba(15, 23, 42, 0.78);
}

.customer-map-tabs button {
  min-height: 36px;
  color: #64748b;
  font-size: 12px;
  font-weight: 900;
}

.customer-map-tabs button.active {
  background: #0ea5e9;
  color: #ffffff;
}

.customer-map-detail,
.customer-map-list {
  flex: 1 1 auto;
  min-height: 0;
  border: 1px solid rgba(148, 163, 184, 0.2);
  background: rgba(255, 255, 255, 0.9);
  padding: 14px;
  overflow: auto;
}

.dark .customer-map-detail,
.dark .customer-map-list {
  background: rgba(15, 23, 42, 0.8);
}

.customer-map-detail h3 {
  margin-top: 6px;
  color: #0f172a;
  font-size: 18px;
  font-weight: 900;
  line-height: 1.15;
  overflow-wrap: anywhere;
}

.dark .customer-map-detail h3 {
  color: #f8fafc;
}

.customer-map-detail dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}

.customer-map-detail div {
  min-width: 0;
  border-top: 1px solid rgba(148, 163, 184, 0.16);
  padding-top: 9px;
}

.customer-map-detail dd {
  margin-top: 3px;
  color: #0f172a;
  font-size: 12px;
  font-weight: 800;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.dark .customer-map-detail dd {
  color: #f8fafc;
}

.customer-map-list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.customer-map-list-head span {
  border-radius: 999px;
  background: rgba(14, 165, 233, 0.14);
  color: #0369a1;
  font-size: 12px;
  font-weight: 900;
  padding: 4px 8px;
}

.customer-map-list-search {
  margin-bottom: 8px;
}

.customer-map-list-search input {
  width: 100%;
  border: 1px solid rgba(148, 163, 184, 0.26);
  background: rgba(248, 250, 252, 0.9);
  color: #0f172a;
  font-size: 12px;
  font-weight: 700;
  outline: none;
  padding: 9px 10px;
}

.customer-map-list-search input:focus {
  border-color: rgba(14, 165, 233, 0.58);
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.12);
}

.dark .customer-map-list-search input {
  background: rgba(15, 23, 42, 0.72);
  color: #f8fafc;
}

.customer-map-row {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid transparent;
  border-bottom-color: rgba(148, 163, 184, 0.14);
  padding: 9px 8px;
  text-align: left;
}

.customer-map-row:hover,
.customer-map-row.active {
  border-color: rgba(14, 165, 233, 0.34);
  background: rgba(14, 165, 233, 0.08);
}

.customer-map-row span {
  min-width: 0;
}

.customer-map-row strong {
  display: block;
  color: #0f172a;
  font-size: 13px;
  line-height: 1.25;
  overflow-wrap: anywhere;
}

.customer-map-row small {
  display: block;
  margin-top: 2px;
  color: #64748b;
  font-size: 11px;
  line-height: 1.25;
}

.dark .customer-map-row strong {
  color: #f8fafc;
}

.dark .customer-map-row small {
  color: #94a3b8;
}

.customer-map-row em {
  flex: 0 0 auto;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.08);
  color: #0f172a;
  font-size: 11px;
  font-style: normal;
  font-weight: 900;
  padding: 4px 7px;
}

.dark .customer-map-row em {
  background: rgba(148, 163, 184, 0.16);
  color: #f8fafc;
}

.customer-map-list-note {
  margin-top: 10px;
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.4;
}

@media (max-width: 1280px) {
  .customer-map-layout {
    grid-template-columns: 1fr;
    height: auto;
  }

  .customer-map-side {
    height: 420px;
  }

  .customer-map-canvas-wrap,
  .customer-map-canvas {
    height: 520px;
  }
}

@media (max-width: 760px) {
  .customer-map-filter {
    grid-template-columns: minmax(0, 1fr);
  }

  .customer-map-canvas-wrap,
  .customer-map-canvas {
    height: 460px;
  }

  .customer-map-side {
    height: 460px;
  }

  .customer-map-detail dl {
    grid-template-columns: 1fr;
  }
}
</style>
