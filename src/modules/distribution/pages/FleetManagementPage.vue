<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import { getBranches, getCompanies, getFleets } from '@/api/master';
import {
  completeFleetTrip,
  createFleetMaintenance,
  getFleetManagementOverview,
  getFleetMaintenances,
  getFleetTripGpsHistory,
  getFleetTripStopEvidence,
  getFleetTripStops,
  startFleetTrip,
  syncFleetTrips
} from '@/api/fleetManagement';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getLoginCompanyId, isSuperUser } from '@/utils/accessScope';
import { getBranchOptionsForCompany, getCompanyOptionsForScope } from '@/utils/filterScope';

const authStore = useAuthStore();
const filters = reactive({ companyId: '', branchId: '', status: '', search: '' });
const companyRows = ref([]);
const branchRows = ref([]);
const fleetRows = ref([]);
const trips = ref([]);
const maintenances = ref([]);
const summary = ref({});
const loading = ref(false);
const errorMessage = ref('');
const successMessage = ref('');
const selectedTrip = ref(null);
const tripModalOpen = ref(false);
const maintenanceModalOpen = ref(false);
const gpsRows = ref([]);
const gpsLoading = ref(false);
const podRows = ref([]);
const podLoading = ref(false);
const podError = ref('');
const podEndpointUnavailable = ref(false);
const podLastUpdatedAt = ref(null);
const podEvidenceUrls = reactive({});
const podEvidenceLoading = reactive({});
const podEvidenceErrors = reactive({});
const activeFleetMapRef = ref(null);
const tripMapRef = ref(null);
const activeFleetMapLoading = ref(false);
const tripMapLoading = ref(false);
const activeFleetMapError = ref('');
const tripMapError = ref('');
const lastGpsRefreshAt = ref(null);
const gpsMonitoringRefreshing = ref(false);
const tripActionLoading = ref(false);
const maintenanceSaving = ref(false);
const startForm = reactive({ odometer: '', notes: '' });
const completeForm = reactive({ odometer: '', destination_note: '', notes: '' });
const maintenanceForm = reactive({
  id_armada: '', maintenance_type: 'SERVICE', status: 'SELESAI', maintenance_date: new Date().toISOString().slice(0, 10),
  odometer_km: '', next_due_date: '', next_due_odometer_km: '', amount: '', workshop_vendor: '', notes: ''
});

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(authStore.user));
const lockedToLoginScope = computed(() => !isSuperUser(authStore));
const companyOptions = computed(() => getCompanyOptionsForScope(companyRows.value, authStore));
const branchOptions = computed(() => getBranchOptionsForCompany(branchRows.value, authStore, filters.companyId));
const activeFleetTrips = computed(() =>
  trips.value.filter((row) => ['BERANGKAT', 'BERMASALAH'].includes(String(row?.status || '').toUpperCase()) && hasCoordinates(row))
);
const tripGpsPoints = computed(() => {
  const historyPoints = gpsRows.value
    .map((row) => coordinatePoint(row))
    .filter(Boolean)
    .sort((left, right) => gpsPointTime(left) - gpsPointTime(right));

  if (historyPoints.length) return historyPoints;

  const latestPoint = coordinatePoint(selectedTrip.value);
  return latestPoint ? [latestPoint] : [];
});
const currentTripGpsPoint = computed(() => tripGpsPoints.value[tripGpsPoints.value.length - 1] || null);
const podStops = computed(() => podRows.value.map((row, index) => normalizePodStop(row, index)));
const podStopsWithCoordinates = computed(() => podStops.value.filter((row) => row.coordinate));
const podSummary = computed(() => {
  const rows = podStops.value;
  return {
    total: rows.length,
    delivered: rows.filter((row) => podStatus(row).state === 'delivered').length,
    arrived: rows.filter((row) => podStatus(row).state === 'arrived').length,
    issue: rows.filter((row) => podStatus(row).state === 'issue').length,
    pending: rows.filter((row) => ['pending', 'draft'].includes(podStatus(row).state)).length
  };
});
const fleetOptions = computed(() => normalizeList(fleetRows.value).map((row) => ({
  value: String(row.id),
  label: [row.kode, row.nama, row.no_pelat].filter(Boolean).join(' - ')
})));
const statusOptions = [
  { value: '', label: 'Semua status' },
  { value: 'SIAP_JALAN', label: 'Siap jalan' },
  { value: 'BERANGKAT', label: 'Dalam perjalanan' },
  { value: 'SELESAI', label: 'Selesai' },
  { value: 'BERMASALAH', label: 'Bermasalah' }
];
const maintenanceTypeOptions = [
  { value: 'SERVICE', label: 'Service berkala' },
  { value: 'BAN', label: 'Ban' },
  { value: 'OLI', label: 'Oli' },
  { value: 'PAJAK_STNK', label: 'Pajak / STNK' },
  { value: 'ASURANSI', label: 'Asuransi' },
  { value: 'KERUSAKAN', label: 'Perbaikan kerusakan' },
  { value: 'LAINNYA', label: 'Lainnya' }
];
const manifestVerificationFields = [
  'manifest_confirmation_status',
  'manifest_confirmation_at',
  'manifest_confirmation_by',
  'manifest_checked_items',
  'manifest_total_items',
  'manifest_discrepancy_note',
  'manifest_confirmation_note'
];

let leafletLoader = null;
let activeFleetMap = null;
let tripMap = null;
let activeFleetMapToken = 0;
let tripMapToken = 0;
let gpsRequestToken = 0;
let podRequestToken = 0;
let podEvidenceGeneration = 0;
let gpsRefreshTimer = null;
let monitoringRefreshInFlight = false;
let fleetDataRefreshInFlight = false;

const filterFields = computed(() => [
  { key: 'companyId', label: 'Perusahaan', type: 'search-select', options: companyOptions.value, disabled: lockedToLoginScope.value && Boolean(fallbackCompanyId.value) },
  { key: 'branchId', label: 'Cabang', type: 'search-select', options: branchOptions.value, disabled: !filters.companyId || (lockedToLoginScope.value && Boolean(fallbackBranchId.value)) },
  { key: 'status', label: 'Status perjalanan', type: 'search-select', options: statusOptions },
  { key: 'search', label: 'Cari', placeholder: 'Manifest, armada, pelat, atau driver' }
]);

const statCards = computed(() => [
  { label: 'Perjalanan', value: summary.value.total_trip || 0, tone: 'text-slate-950' },
  { label: 'Siap Jalan', value: summary.value.siap_jalan || 0, tone: 'text-sky-700' },
  { label: 'Berangkat', value: summary.value.berangkat || 0, tone: 'text-emerald-700' },
  { label: 'Selesai', value: summary.value.selesai || 0, tone: 'text-violet-700' },
  { label: 'Bermasalah', value: summary.value.bermasalah || 0, tone: 'text-rose-700' },
  { label: 'Maintenance <= 30 Hari', value: summary.value.maintenance_due || 0, tone: 'text-amber-700' }
]);

const tripColumns = [
  { key: 'no_manifest', label: 'Manifest' },
  { key: 'armada', label: 'Armada', render: (row) => [row.kode_armada, row.nama_armada, row.no_pelat].filter(Boolean).join(' | ') },
  { key: 'nama_driver', label: 'Driver' },
  { key: 'nama_helpers', label: 'Helper' },
  { key: 'status', label: 'Status', render: (row) => ({ text: statusLabel(row.status), className: statusClass(row.status) }) },
  { key: 'manifest_verification', label: 'Verifikasi Muatan', render: (row) => manifestConfirmationCell(row) },
  { key: 'gps', label: 'GPS terakhir', render: (row) => gpsLabel(row) }
];

const gpsColumns = [
  { key: 'captured_at', label: 'Waktu' },
  { key: 'coordinate', label: 'Koordinat', render: (row) => `${row.latitude}, ${row.longitude}` },
  { key: 'speed_kmh', label: 'Kecepatan' },
  { key: 'accuracy_m', label: 'Akurasi (m)' },
  { key: 'battery_pct', label: 'Baterai' },
  { key: 'source', label: 'Sumber' }
];

const maintenanceColumns = [
  { key: 'maintenance_date', label: 'Tanggal' },
  { key: 'armada', label: 'Armada', render: (row) => [row.kode_armada, row.nama_armada, row.no_pelat].filter(Boolean).join(' | ') },
  { key: 'maintenance_type', label: 'Jenis', render: (row) => maintenanceLabel(row.maintenance_type) },
  { key: 'status', label: 'Status' },
  { key: 'next_due_date', label: 'Jadwal berikutnya' },
  { key: 'next_due_odometer_km', label: 'KM berikutnya' },
  { key: 'amount', label: 'Nilai', render: (row) => formatCurrency(row.amount) }
];

function unwrapData(response) {
  const data = unwrapResponse(response);
  return data?.data || data || {};
}

function statusLabel(status) {
  return ({ SIAP_JALAN: 'Siap jalan', BERANGKAT: 'Dalam perjalanan', SELESAI: 'Selesai', BERMASALAH: 'Bermasalah', BATAL: 'Batal' })[status] || status || '-';
}

function statusClass(status) {
  return ({
    SIAP_JALAN: 'rounded-full bg-sky-100 px-2.5 py-1 text-xs font-semibold text-sky-700',
    BERANGKAT: 'rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-700',
    SELESAI: 'rounded-full bg-violet-100 px-2.5 py-1 text-xs font-semibold text-violet-700',
    BERMASALAH: 'rounded-full bg-rose-100 px-2.5 py-1 text-xs font-semibold text-rose-700'
  })[status] || 'rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600';
}

function maintenanceLabel(type) {
  return maintenanceTypeOptions.find((item) => item.value === type)?.label || type || '-';
}

function formatCurrency(value) {
  const amount = Number(value || 0);
  return new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(amount);
}

function firstValue(row, keys = []) {
  for (const key of keys) {
    const value = row?.[key];
    if (hasValue(value)) return value;
  }
  return null;
}

function firstText(row, keys = [], fallback = '') {
  const value = firstValue(row, keys);
  return hasValue(value) ? String(value).trim() : fallback;
}

function firstArray(row, keys = []) {
  for (const key of keys) {
    if (Array.isArray(row?.[key])) return row[key];
  }
  return [];
}

function podQuantityDisplay(value, uom = 'PCS') {
  if (!hasValue(value)) return '-';
  const number = numberOrNull(value);
  if (number === null) return String(value);
  const formatted = new Intl.NumberFormat('id-ID', { maximumFractionDigits: 3 }).format(number);
  return `${formatted} ${uom || 'PCS'}`;
}

function podQuantityValue(row, aliases) {
  return firstValue(row, aliases);
}

function podQuantityLabel(row, value, displayAliases = [], uomAliases = []) {
  const display = firstValue(row, displayAliases);
  const uom = firstText(row, uomAliases, 'PCS');
  if (hasValue(display)) return numberOrNull(display) === null ? String(display) : podQuantityDisplay(display, uom);
  return podQuantityDisplay(value, uom);
}

function calculatedDiscrepancy(plannedQty, actualQty, returnQty) {
  const planned = numberOrNull(plannedQty);
  const actual = numberOrNull(actualQty);
  const returned = numberOrNull(returnQty);
  if (planned === null || actual === null) return null;
  return planned - actual - (returned === null ? 0 : returned);
}

function podStatus(row) {
  const raw = String(row?.status || '').trim().toUpperCase();
  if (['DELIVERED', 'SELESAI', 'COMPLETED', 'COMPLETE', 'POD_CONFIRMED', 'POD_COMPLETE'].includes(raw)) {
    return { state: 'delivered', label: 'Terkirim', className: 'rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-700' };
  }
  if (['ARRIVED', 'TIBA', 'AT_DESTINATION', 'CHECKED_IN'].includes(raw)) {
    return { state: 'arrived', label: 'Tiba di toko', className: 'rounded-full bg-sky-100 px-2.5 py-1 text-xs font-semibold text-sky-700' };
  }
  if (['POD_DRAFT', 'POD_PENDING', 'AWAITING_SIGNATURE', 'MENUNGGU_POD'].includes(raw)) {
    return { state: 'draft', label: 'Menunggu POD', className: 'rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-700' };
  }
  if (['ISSUE', 'FAILED', 'GAGAL', 'RETURN', 'RETUR', 'PARTIAL', 'DISCREPANCY', 'BERMASALAH'].includes(raw)) {
    return { state: 'issue', label: raw === 'RETURN' || raw === 'RETUR' ? 'Retur' : raw === 'PARTIAL' ? 'Terkirim sebagian' : 'Perlu tindak lanjut', className: 'rounded-full bg-rose-100 px-2.5 py-1 text-xs font-semibold text-rose-700' };
  }
  if (['ON_ROUTE', 'DALAM_PERJALAN', 'IN_TRANSIT'].includes(raw)) {
    return { state: 'on-route', label: 'Dalam perjalanan', className: 'rounded-full bg-violet-100 px-2.5 py-1 text-xs font-semibold text-violet-700' };
  }
  return { state: 'pending', label: raw ? raw.replace(/_/g, ' ').toLocaleLowerCase('id-ID').replace(/(^|\s)\S/g, (letter) => letter.toUpperCase()) : 'Belum dikunjungi', className: 'rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600' };
}

function podStatusMapTone(row) {
  const state = podStatus(row).state;
  if (state === 'delivered') return { fill: '#059669', ring: '#d1fae5', border: '#047857' };
  if (state === 'arrived') return { fill: '#0284c7', ring: '#e0f2fe', border: '#0369a1' };
  if (state === 'issue') return { fill: '#e11d48', ring: '#ffe4e6', border: '#9f1239' };
  if (state === 'draft') return { fill: '#d97706', ring: '#fef3c7', border: '#b45309' };
  return { fill: '#64748b', ring: '#e2e8f0', border: '#475569' };
}

function evidenceUrl(value) {
  const pickUrl = (candidate) => {
    if (Array.isArray(candidate)) {
      return candidate.map((item) => pickUrl(item)).find(Boolean) || '';
    }
    if (candidate && typeof candidate === 'object') {
      return pickUrl(candidate.url || candidate.href || candidate.file_url || candidate.fileUrl || candidate.path || candidate.location);
    }
    const raw = String(candidate || '').trim();
    if (!raw) return '';
    try {
      const parsed = new URL(raw, typeof window === 'undefined' ? 'http://localhost' : window.location.origin);
      return ['http:', 'https:'].includes(parsed.protocol) ? raw : '';
    } catch (_) {
      return '';
    }
  };

  return pickUrl(value);
}

function normalizePodItem(row, index) {
  const plannedQty = podQuantityValue(row, ['planned_qty_pcs', 'expected_qty_pcs', 'qty_planned', 'qty_expected', 'qty_ordered', 'ordered_qty', 'expected_qty']);
  const actualQty = podQuantityValue(row, ['actual_qty_pcs', 'delivered_qty_pcs', 'qty_actual', 'qty_delivered', 'received_qty', 'qty_received', 'actual_qty']);
  const returnQty = podQuantityValue(row, ['return_qty_pcs', 'returned_qty_pcs', 'qty_return', 'return_qty', 'qty_retur', 'returned_qty']);
  const discrepancyRaw = podQuantityValue(row, ['discrepancy_qty_pcs', 'difference_qty_pcs', 'qty_discrepancy', 'qty_difference', 'selisih_qty', 'discrepancy_qty']);
  const discrepancyQty = hasValue(discrepancyRaw) ? discrepancyRaw : calculatedDiscrepancy(plannedQty, actualQty, returnQty);
  const uom = firstText(row, ['uom', 'uom_name', 'uom_kode', 'unit', 'satuan'], 'PCS');

  return {
    id: firstValue(row, ['id', 'id_detail', 'item_id', 'product_id']) || `item-${index}`,
    productName: firstText(row, ['product_name', 'nama_produk', 'produk_nama', 'product', 'nama_barang', 'item_name'], 'Barang belum bernama'),
    productCode: firstText(row, ['product_code', 'kode_produk', 'kode_sku', 'sku', 'item_code']),
    uom,
    plannedQty,
    actualQty,
    returnQty,
    discrepancyQty,
    plannedLabel: podQuantityLabel(row, plannedQty, ['planned_qty_display', 'expected_qty_display', 'qty_planned_display'], ['uom', 'uom_name', 'uom_kode', 'unit', 'satuan']),
    actualLabel: podQuantityLabel(row, actualQty, ['actual_qty_display', 'delivered_qty_display', 'qty_actual_display'], ['uom', 'uom_name', 'uom_kode', 'unit', 'satuan']),
    returnLabel: podQuantityLabel(row, returnQty, ['return_qty_display', 'returned_qty_display', 'qty_return_display'], ['uom', 'uom_name', 'uom_kode', 'unit', 'satuan']),
    discrepancyLabel: podQuantityLabel(row, discrepancyQty, ['discrepancy_qty_display', 'difference_qty_display', 'qty_discrepancy_display'], ['uom', 'uom_name', 'uom_kode', 'unit', 'satuan'])
  };
}

function normalizePodStop(row, index) {
  const plannedQty = podQuantityValue(row, ['planned_qty_pcs', 'expected_qty_pcs', 'qty_planned', 'qty_expected', 'qty_ordered', 'ordered_qty', 'expected_qty', 'total_expected_pcs']);
  const actualQty = podQuantityValue(row, ['actual_qty_pcs', 'delivered_qty_pcs', 'qty_actual', 'qty_delivered', 'received_qty', 'qty_received', 'actual_qty', 'total_actual_pcs']);
  const returnQty = podQuantityValue(row, ['return_qty_pcs', 'returned_qty_pcs', 'qty_return', 'return_qty', 'qty_retur', 'returned_qty', 'total_return_pcs']);
  const discrepancyRaw = podQuantityValue(row, ['discrepancy_qty_pcs', 'difference_qty_pcs', 'qty_discrepancy', 'qty_difference', 'selisih_qty', 'discrepancy_qty', 'total_discrepancy_pcs']);
  const discrepancyQty = hasValue(discrepancyRaw) ? discrepancyRaw : calculatedDiscrepancy(plannedQty, actualQty, returnQty);
  const uom = firstText(row, ['uom', 'uom_name', 'uom_kode', 'unit', 'satuan'], 'PCS');
  const latitude = firstValue(row, ['latitude', 'lat', 'destination_latitude', 'store_latitude', 'arrived_latitude']);
  const longitude = firstValue(row, ['longitude', 'lng', 'lon', 'destination_longitude', 'store_longitude', 'arrived_longitude']);
  const coordinate = coordinatePoint({ latitude, longitude });
  const items = firstArray(row, ['items', 'delivery_items', 'pod_items', 'details', 'item_details']).map((item, itemIndex) => normalizePodItem(item, itemIndex));
  const sequence = firstValue(row, ['sequence', 'stop_sequence', 'urutan', 'no_urut', 'sort_order']) || index + 1;

  return {
    id: firstValue(row, ['id', 'id_stop', 'stop_id', 'delivery_stop_id', 'destination_id', 'destination_key']) || `stop-${index}`,
    sequence,
    reference: firstText(row, ['no_faktur', 'no_reference', 'reference_no', 'no_order', 'no_sales_order', 'no_invoice', 'no_surat_jalan', 'nomor_referensi']),
    customerName: firstText(row, ['customer_name', 'nama_customer', 'nama_toko', 'store_name', 'toko', 'nama_pelanggan'], 'Tujuan belum tercatat'),
    customerCode: firstText(row, ['kode_customer', 'customer_code', 'kode_toko', 'store_code']),
    address: firstText(row, ['address', 'alamat', 'delivery_address', 'alamat_kirim']),
    telephone: firstText(row, ['telephone', 'phone', 'no_telp', 'telepon']),
    status: firstText(row, ['pod_status', 'delivery_status', 'stop_status', 'status'], 'PENDING'),
    arrivedAt: firstValue(row, ['arrived_at', 'arrival_at', 'tiba_at', 'checked_in_at', 'check_in_at']),
    deliveredAt: firstValue(row, ['delivered_at', 'completed_at', 'received_at', 'finished_at', 'pod_at', 'confirmed_at']),
    receiverName: firstText(row, ['receiver_name', 'received_by', 'recipient_name', 'nama_penerima', 'penerima']),
    receiverPhone: firstText(row, ['receiver_phone', 'recipient_phone', 'no_hp_penerima']),
    notes: firstText(row, ['notes', 'pod_notes', 'delivery_notes', 'catatan']),
    discrepancyNotes: firstText(row, ['discrepancy_notes', 'discrepancy_note', 'selisih_notes', 'catatan_selisih']),
    returnNotes: firstText(row, ['return_notes', 'return_note', 'retur_notes', 'catatan_retur']),
    photoUrl: evidenceUrl(firstValue(row, ['photo_url', 'pod_photo_url', 'proof_photo_url', 'delivery_photo_url', 'evidence_photo_url', 'photo', 'proof_photo'])),
    signatureUrl: evidenceUrl(firstValue(row, ['signature_url', 'receiver_signature_url', 'proof_signature_url', 'signature', 'ttd_url'])),
    evidenceUrl: evidenceUrl(firstValue(row, ['evidence_url', 'proof_url', 'attachment_url', 'document_url'])),
    coordinate,
    plannedQty,
    actualQty,
    returnQty,
    discrepancyQty,
    plannedLabel: podQuantityLabel(row, plannedQty, ['planned_qty_display', 'expected_qty_display', 'qty_planned_display'], ['uom', 'uom_name', 'uom_kode', 'unit', 'satuan']),
    actualLabel: podQuantityLabel(row, actualQty, ['actual_qty_display', 'delivered_qty_display', 'qty_actual_display'], ['uom', 'uom_name', 'uom_kode', 'unit', 'satuan']),
    returnLabel: podQuantityLabel(row, returnQty, ['return_qty_display', 'returned_qty_display', 'qty_return_display'], ['uom', 'uom_name', 'uom_kode', 'unit', 'satuan']),
    discrepancyLabel: podQuantityLabel(row, discrepancyQty, ['discrepancy_qty_display', 'difference_qty_display', 'qty_discrepancy_display'], ['uom', 'uom_name', 'uom_kode', 'unit', 'satuan']),
    itemCount: firstValue(row, ['delivered_item_count', 'item_count', 'total_items', 'items_count']) ?? items.length,
    items
  };
}

function podStopRowsFromPayload(payload) {
  if (Array.isArray(payload)) return payload;
  const candidates = [
    payload?.stops,
    payload?.delivery_stops,
    payload?.pod_stops,
    payload?.destinations,
    payload?.delivery_points,
    payload?.data?.stops,
    payload?.data?.delivery_stops,
    payload?.data?.pod_stops
  ];
  return candidates.find((candidate) => Array.isArray(candidate)) || null;
}

function embeddedPodStops(row) {
  return podStopRowsFromPayload({
    stops: row?.stops,
    delivery_stops: row?.delivery_stops,
    pod_stops: row?.pod_stops,
    destinations: row?.destinations,
    delivery_points: row?.delivery_points
  });
}

function isPodEndpointUnavailable(error) {
  return [404, 405, 501].includes(Number(error?.response?.status));
}

function podMapUrl(stop) {
  if (!stop?.coordinate) return '';
  return `https://www.google.com/maps/search/?api=1&query=${stop.coordinate.latitude},${stop.coordinate.longitude}`;
}

function podEvidenceSource(stop, type) {
  if (type === 'photo') return stop?.photoUrl || '';
  if (type === 'signature') return stop?.signatureUrl || '';
  if (type === 'document') return stop?.evidenceUrl || '';
  return '';
}

function podEvidenceKey(stop, type) {
  const source = podEvidenceSource(stop, type);
  return source ? `${type}:${source}` : '';
}

function activePodEvidenceKeys() {
  const keys = new Set();
  podStops.value.forEach((stop) => {
    ['photo', 'signature', 'document'].forEach((type) => {
      const key = podEvidenceKey(stop, type);
      if (key) keys.add(key);
    });
  });
  return keys;
}

function podEvidencePreviewUrl(stop, type) {
  const key = podEvidenceKey(stop, type);
  return key ? podEvidenceUrls[key] || '' : '';
}

function isPodEvidenceLoading(stop, type) {
  const key = podEvidenceKey(stop, type);
  return Boolean(key && podEvidenceLoading[key]);
}

function podEvidenceError(stop, type) {
  const key = podEvidenceKey(stop, type);
  return key ? podEvidenceErrors[key] || '' : '';
}

function revokePodEvidenceUrl(key) {
  const objectUrl = podEvidenceUrls[key];
  if (objectUrl && typeof URL !== 'undefined' && typeof URL.revokeObjectURL === 'function') {
    URL.revokeObjectURL(objectUrl);
  }
  delete podEvidenceUrls[key];
}

function clearPodEvidence() {
  podEvidenceGeneration += 1;
  Object.keys(podEvidenceUrls).forEach(revokePodEvidenceUrl);
  Object.keys(podEvidenceLoading).forEach((key) => delete podEvidenceLoading[key]);
  Object.keys(podEvidenceErrors).forEach((key) => delete podEvidenceErrors[key]);
}

function prunePodEvidence() {
  const activeKeys = activePodEvidenceKeys();
  Object.keys(podEvidenceUrls).forEach((key) => {
    if (!activeKeys.has(key)) revokePodEvidenceUrl(key);
  });
  Object.keys(podEvidenceErrors).forEach((key) => {
    if (!activeKeys.has(key)) delete podEvidenceErrors[key];
  });
}

async function loadPodEvidence(stop, type) {
  const source = podEvidenceSource(stop, type);
  const key = podEvidenceKey(stop, type);
  if (!source || !key || podEvidenceUrls[key] || podEvidenceLoading[key]) return podEvidenceUrls[key] || '';
  if (typeof URL === 'undefined' || typeof URL.createObjectURL !== 'function') {
    podEvidenceErrors[key] = 'Browser tidak mendukung tampilan bukti POD yang aman.';
    return '';
  }

  const generation = podEvidenceGeneration;
  podEvidenceLoading[key] = true;
  delete podEvidenceErrors[key];
  try {
    const response = await getFleetTripStopEvidence(source);
    const blob = response?.data;
    if (!blob || typeof blob.size !== 'number') {
      throw new Error('Berkas bukti POD tidak valid.');
    }

    const objectUrl = URL.createObjectURL(blob);
    if (generation !== podEvidenceGeneration || !activePodEvidenceKeys().has(key)) {
      URL.revokeObjectURL(objectUrl);
      return '';
    }

    revokePodEvidenceUrl(key);
    podEvidenceUrls[key] = objectUrl;
    return objectUrl;
  } catch (error) {
    if (generation === podEvidenceGeneration && activePodEvidenceKeys().has(key)) {
      podEvidenceErrors[key] = normalizeError(error, 'Bukti POD belum dapat dimuat.');
    }
    return '';
  } finally {
    if (generation === podEvidenceGeneration) {
      if (activePodEvidenceKeys().has(key)) podEvidenceLoading[key] = false;
      else delete podEvidenceLoading[key];
    }
  }
}

function coordinatePoint(row) {
  const latitude = Number(row?.latitude);
  const longitude = Number(row?.longitude);
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
  if (latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180) return null;
  if (latitude === 0 && longitude === 0) return null;
  return {
    ...row,
    latitude,
    longitude
  };
}

function hasCoordinates(row) {
  return Boolean(coordinatePoint(row));
}

function gpsPointTime(row) {
  const value = row?.captured_at || row?.gps_at || row?.received_at;
  const timestamp = value ? new Date(value).getTime() : 0;
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function gpsLabel(row) {
  const point = coordinatePoint(row);
  if (!point) return '-';
  const capturedAt = row?.gps_at || row?.captured_at || row?.received_at;
  return `${point.latitude}, ${point.longitude}${capturedAt ? ` (${formatDateTime(capturedAt)})` : ''}`;
}

function hasValue(value) {
  return value !== null && value !== undefined && String(value).trim() !== '';
}

function hasManifestVerificationData(row) {
  return manifestVerificationFields.some((field) => Object.prototype.hasOwnProperty.call(row || {}, field) && hasValue(row?.[field]));
}

function numberOrNull(value) {
  if (!hasValue(value)) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function confirmationProgress(row) {
  const checked = numberOrNull(row?.manifest_checked_items);
  const total = numberOrNull(row?.manifest_total_items);
  if (total !== null) return `${checked ?? 0}/${total} item`;
  if (checked !== null) return `${checked} item dicek`;
  return 'Jumlah item belum dikirim';
}

function manifestConfirmationNote(row) {
  return String(row?.manifest_discrepancy_note || row?.manifest_confirmation_note || '').trim();
}

function manifestConfirmation(row) {
  const rawStatus = String(row?.manifest_confirmation_status || '').trim().toUpperCase();
  const discrepancyNote = manifestConfirmationNote(row);
  const confirmedAt = row?.manifest_confirmation_at;
  const confirmedBy = row?.manifest_confirmation_by;
  const hasData = hasManifestVerificationData(row);
  const discrepancyStatuses = ['ADA_SELISIH', 'SELISIH', 'DISCREPANCY', 'BERSELISIH', 'TIDAK_SESUAI', 'REJECTED', 'ISSUE'];
  const confirmedStatuses = ['SESUAI', 'CONFIRMED', 'DIKONFIRMASI', 'VERIFIED', 'VALID'];
  const pendingStatuses = ['PENDING', 'BELUM_DIKONFIRMASI', 'BELUM_KONFIRMASI', 'MENUNGGU_KONFIRMASI', 'DRAFT', ''];

  if (discrepancyStatuses.includes(rawStatus) || discrepancyNote) {
    return {
      state: 'discrepancy',
      label: 'Ada selisih',
      className: 'rounded-full bg-rose-100 px-2.5 py-1 text-xs font-semibold text-rose-700'
    };
  }
  if (confirmedStatuses.includes(rawStatus) || (!rawStatus && (hasValue(confirmedAt) || hasValue(confirmedBy)))) {
    return {
      state: 'confirmed',
      label: 'Sesuai',
      className: 'rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-700'
    };
  }
  if (!hasData) {
    return {
      state: 'unavailable',
      label: 'Belum dikonfirmasi',
      className: 'rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600'
    };
  }
  if (pendingStatuses.includes(rawStatus)) {
    return {
      state: 'pending',
      label: 'Menunggu konfirmasi',
      className: 'rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-700'
    };
  }
  return {
    state: 'pending',
    label: rawStatus.replace(/_/g, ' ').toLocaleLowerCase('id-ID').replace(/(^|\s)\S/g, (letter) => letter.toUpperCase()),
    className: 'rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-700'
  };
}

function manifestConfirmationCell(row) {
  const confirmation = manifestConfirmation(row);
  const progress = confirmationProgress(row);
  return {
    text: confirmation.state === 'unavailable' ? confirmation.label : `${confirmation.label} · ${progress}`,
    className: confirmation.className
  };
}

function formatDateTime(value) {
  if (!value) return '-';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('id-ID');
}

function mapUrl(row) {
  const point = coordinatePoint(row);
  if (!point) return '';
  return `https://www.google.com/maps/search/?api=1&query=${point.latitude},${point.longitude}`;
}

function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function loadLeaflet() {
  if (typeof window === 'undefined') return Promise.reject(new Error('Peta hanya tersedia di browser.'));
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

function destroyActiveFleetMap() {
  if (activeFleetMap) {
    activeFleetMap.remove();
    activeFleetMap = null;
  }
}

function destroyTripMap() {
  if (tripMap) {
    tripMap.remove();
    tripMap = null;
  }
}

function fleetStatusMapTone(status) {
  if (String(status || '').toUpperCase() === 'BERMASALAH') {
    return { fill: '#e11d48', ring: '#ffe4e6', border: '#9f1239' };
  }
  return { fill: '#059669', ring: '#d1fae5', border: '#047857' };
}

function vehicleMarkerIcon(L, row, options = {}) {
  const tone = options.tone || fleetStatusMapTone(row?.status);
  const label = options.label || '🚚';
  const size = options.size || 36;
  const fontSize = options.fontSize || 15;
  return L.divIcon({
    className: '',
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    popupAnchor: [0, -(size / 2)],
    html: `
      <div style="width:${size}px;height:${size}px;display:flex;align-items:center;justify-content:center;border-radius:999px;background:${tone.ring};border:2px solid #ffffff;box-shadow:0 8px 20px rgba(15,23,42,.28);">
        <span style="display:flex;width:${size - 10}px;height:${size - 10}px;align-items:center;justify-content:center;border-radius:999px;background:${tone.fill};border:2px solid ${tone.border};color:#ffffff;font-size:${fontSize}px;font-weight:700;line-height:1;">${escapeHtml(label)}</span>
      </div>
    `
  });
}

function fleetPopupHtml(row) {
  const capturedAt = row?.gps_at || row?.captured_at || row?.received_at;
  return `
    <div style="min-width:220px;font-family:Arial,sans-serif;color:#0f172a;line-height:1.5;">
      <div style="font-size:14px;font-weight:800;margin-bottom:5px;">${escapeHtml(row?.nama_armada || row?.kode_armada || 'Armada')}</div>
      <div style="font-size:12px;">
        <div><strong>Pelat:</strong> ${escapeHtml(row?.no_pelat || '-')}</div>
        <div><strong>Manifest:</strong> ${escapeHtml(row?.no_manifest || '-')}</div>
        <div><strong>Driver:</strong> ${escapeHtml(row?.nama_driver || '-')}</div>
        <div><strong>Status:</strong> ${escapeHtml(statusLabel(row?.status))}</div>
        <div><strong>GPS:</strong> ${escapeHtml(formatDateTime(capturedAt))}</div>
      </div>
    </div>
  `;
}

function gpsPopupHtml(point, title) {
  return `
    <div style="min-width:190px;font-family:Arial,sans-serif;color:#0f172a;line-height:1.5;">
      <div style="font-size:14px;font-weight:800;margin-bottom:5px;">${escapeHtml(title)}</div>
      <div style="font-size:12px;">
        <div><strong>Waktu:</strong> ${escapeHtml(formatDateTime(point?.captured_at || point?.gps_at || point?.received_at))}</div>
        <div><strong>Koordinat:</strong> ${escapeHtml(`${point?.latitude}, ${point?.longitude}`)}</div>
        ${hasValue(point?.speed_kmh) ? `<div><strong>Kecepatan:</strong> ${escapeHtml(`${point.speed_kmh} km/jam`)}</div>` : ''}
      </div>
    </div>
  `;
}

function podStopPopupHtml(stop) {
  const status = podStatus(stop);
  return `
    <div style="min-width:220px;font-family:Arial,sans-serif;color:#0f172a;line-height:1.5;">
      <div style="font-size:14px;font-weight:800;margin-bottom:5px;">${escapeHtml(`Stop ${stop.sequence} · ${stop.customerName}`)}</div>
      <div style="font-size:12px;">
        ${stop.reference ? `<div><strong>Referensi:</strong> ${escapeHtml(stop.reference)}</div>` : ''}
        <div><strong>Status:</strong> ${escapeHtml(status.label)}</div>
        <div><strong>Pesanan:</strong> ${escapeHtml(stop.plannedLabel)}</div>
        <div><strong>Aktual:</strong> ${escapeHtml(stop.actualLabel)}</div>
        ${stop.arrivedAt ? `<div><strong>Tiba:</strong> ${escapeHtml(formatDateTime(stop.arrivedAt))}</div>` : ''}
        ${stop.deliveredAt ? `<div><strong>POD:</strong> ${escapeHtml(formatDateTime(stop.deliveredAt))}</div>` : ''}
      </div>
    </div>
  `;
}

async function renderActiveFleetMap() {
  const renderToken = ++activeFleetMapToken;
  activeFleetMapError.value = '';
  await nextTick();

  const rows = activeFleetTrips.value;
  if (!activeFleetMapRef.value || !rows.length) {
    destroyActiveFleetMap();
    return;
  }

  activeFleetMapLoading.value = true;
  try {
    const L = await loadLeaflet();
    if (renderToken !== activeFleetMapToken || !activeFleetMapRef.value) return;

    destroyActiveFleetMap();
    activeFleetMap = L.map(activeFleetMapRef.value, { zoomControl: true, attributionControl: true });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors'
    }).addTo(activeFleetMap);

    const markers = L.featureGroup().addTo(activeFleetMap);
    rows.forEach((row) => {
      const point = coordinatePoint(row);
      if (!point) return;
      const marker = L.marker([point.latitude, point.longitude], { icon: vehicleMarkerIcon(L, row) });
      marker.bindPopup(fleetPopupHtml(row));
      marker.addTo(markers);
    });

    const bounds = markers.getBounds();
    if (bounds.isValid()) {
      activeFleetMap.fitBounds(bounds.pad(0.18), { maxZoom: 14 });
    }
    window.setTimeout(() => {
      if (renderToken === activeFleetMapToken && activeFleetMap) activeFleetMap.invalidateSize();
    }, 120);
  } catch (error) {
    if (renderToken === activeFleetMapToken) {
      activeFleetMapError.value = normalizeError(error, 'Peta armada belum dapat dimuat.');
      destroyActiveFleetMap();
    }
  } finally {
    if (renderToken === activeFleetMapToken) activeFleetMapLoading.value = false;
  }
}

async function renderTripMap() {
  const renderToken = ++tripMapToken;
  tripMapError.value = '';
  await nextTick();

  const points = tripGpsPoints.value;
  const stops = podStopsWithCoordinates.value;
  if (!tripModalOpen.value || !tripMapRef.value || (!points.length && !stops.length)) {
    destroyTripMap();
    return;
  }

  tripMapLoading.value = true;
  try {
    const L = await loadLeaflet();
    if (renderToken !== tripMapToken || !tripMapRef.value || !tripModalOpen.value) return;

    destroyTripMap();
    tripMap = L.map(tripMapRef.value, { zoomControl: true, attributionControl: true });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors'
    }).addTo(tripMap);

    const routeLayer = L.featureGroup().addTo(tripMap);
    if (points.length) {
      const routeCoordinates = points.map((point) => [point.latitude, point.longitude]);
      if (routeCoordinates.length >= 2) {
        L.polyline(routeCoordinates, {
          color: '#2563eb',
          weight: 5,
          opacity: 0.82,
          lineJoin: 'round'
        }).addTo(routeLayer);
      }

      const firstPoint = points[0];
      const lastPoint = points[points.length - 1];
      if (points.length >= 2) {
        L.marker([firstPoint.latitude, firstPoint.longitude], {
          icon: vehicleMarkerIcon(L, { status: 'SIAP_JALAN' }, { label: 'A', tone: { fill: '#2563eb', ring: '#dbeafe', border: '#1d4ed8' } })
        }).bindPopup(gpsPopupHtml(firstPoint, 'Titik awal perjalanan')).addTo(routeLayer);
      }
      L.marker([lastPoint.latitude, lastPoint.longitude], {
        icon: vehicleMarkerIcon(L, selectedTrip.value, { label: '🚚', tone: { fill: '#059669', ring: '#d1fae5', border: '#047857' } })
      }).bindPopup(gpsPopupHtml(lastPoint, points.length > 1 ? 'Posisi kendaraan terakhir' : 'Titik GPS kendaraan')).addTo(routeLayer);
    }

    stops.forEach((stop) => {
      const point = stop.coordinate;
      if (!point) return;
      L.marker([point.latitude, point.longitude], {
        icon: vehicleMarkerIcon(L, stop, {
          label: String(stop.sequence),
          size: 32,
          fontSize: 13,
          tone: podStatusMapTone(stop)
        })
      }).bindPopup(podStopPopupHtml(stop)).addTo(routeLayer);
    });

    const bounds = routeLayer.getBounds();
    if (bounds.isValid()) {
      tripMap.fitBounds(bounds.pad(0.18), { maxZoom: points.length === 1 ? 15 : 14 });
    } else if (points.length) {
      const lastPoint = points[points.length - 1];
      tripMap.setView([lastPoint.latitude, lastPoint.longitude], 15);
    } else if (stops.length) {
      tripMap.setView([stops[0].coordinate.latitude, stops[0].coordinate.longitude], 15);
    }
    window.setTimeout(() => {
      if (renderToken === tripMapToken && tripMap) tripMap.invalidateSize();
    }, 120);
  } catch (error) {
    if (renderToken === tripMapToken) {
      tripMapError.value = normalizeError(error, 'Peta jejak perjalanan belum dapat dimuat.');
      destroyTripMap();
    }
  } finally {
    if (renderToken === tripMapToken) tripMapLoading.value = false;
  }
}

function syncBranchScope() {
  if (!filters.companyId || !filters.branchId) return;
  const branch = branchRows.value.find((item) => String(item.id) === String(filters.branchId));
  if (branch && String(branch.id_perusahaan || '') !== String(filters.companyId)) {
    filters.branchId = '';
  }
}

function updateFilters(next) {
  const previousCompany = filters.companyId;
  Object.assign(filters, next);
  if (filters.companyId !== previousCompany) syncBranchScope();
}

async function loadReferenceData() {
  const [companiesResponse, branchesResponse, fleetsResponse] = await Promise.all([getCompanies(), getBranches(), getFleets()]);
  companyRows.value = normalizeList(unwrapResponse(companiesResponse));
  branchRows.value = normalizeList(unwrapResponse(branchesResponse));
  fleetRows.value = normalizeList(unwrapResponse(fleetsResponse));
  if (lockedToLoginScope.value && fallbackCompanyId.value) filters.companyId = String(fallbackCompanyId.value);
  if (lockedToLoginScope.value && fallbackBranchId.value) filters.branchId = String(fallbackBranchId.value);
}

async function loadData({ sync = false, silent = false, includeMaintenance = true } = {}) {
  if (fleetDataRefreshInFlight) return false;
  fleetDataRefreshInFlight = true;
  if (!silent) {
    loading.value = true;
    errorMessage.value = '';
    successMessage.value = '';
  }
  const params = {
    id_perusahaan: filters.companyId || fallbackCompanyId.value || undefined,
    id_cabang: filters.branchId || fallbackBranchId.value || undefined,
    status: filters.status || undefined,
    search: filters.search || undefined
  };
  try {
    if (sync) await syncFleetTrips({ id_cabang: params.id_cabang });
    const [overviewResponse, maintenanceResponse] = await Promise.all([
      getFleetManagementOverview(params),
      includeMaintenance ? getFleetMaintenances({ id_cabang: params.id_cabang }) : Promise.resolve(null)
    ]);
    const overview = unwrapData(overviewResponse);
    summary.value = overview.summary || {};
    trips.value = normalizeList(overview.data || overview);
    if (maintenanceResponse) {
      const maintenance = unwrapData(maintenanceResponse);
      maintenances.value = normalizeList(maintenance.data || maintenance);
    }
    lastGpsRefreshAt.value = new Date();

    if (selectedTrip.value) {
      const refreshedTrip = trips.value.find((row) => String(row.id) === String(selectedTrip.value.id));
      if (refreshedTrip) selectedTrip.value = { ...selectedTrip.value, ...refreshedTrip };
    }

    void renderActiveFleetMap();
    return true;
  } catch (error) {
    if (!silent) {
      errorMessage.value = normalizeError(error, 'Data manajemen armada belum dapat dimuat.');
    } else {
      activeFleetMapError.value = normalizeError(error, 'Pembaruan GPS armada belum dapat dimuat.');
    }
    return false;
  } finally {
    if (!silent) loading.value = false;
    fleetDataRefreshInFlight = false;
  }
}

function resetFilters() {
  filters.companyId = lockedToLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
  filters.branchId = lockedToLoginScope.value && fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  filters.status = '';
  filters.search = '';
  loadData();
}

async function loadTripGpsHistory(row, { silent = false } = {}) {
  if (!row?.id) return false;
  const requestToken = ++gpsRequestToken;
  gpsLoading.value = true;
  if (!silent) tripMapError.value = '';
  try {
    const response = await getFleetTripGpsHistory(row.id);
    if (requestToken !== gpsRequestToken || String(selectedTrip.value?.id) !== String(row.id)) return false;
    const data = unwrapData(response);
    gpsRows.value = normalizeList(data.data || data);
    await renderTripMap();
    return true;
  } catch (error) {
    if (requestToken === gpsRequestToken) {
      const message = normalizeError(error, 'Riwayat GPS belum dapat dimuat.');
      tripMapError.value = message;
      if (!silent) errorMessage.value = message;
    }
    return false;
  } finally {
    if (requestToken === gpsRequestToken) gpsLoading.value = false;
  }
}

async function loadTripPodStops(row, { silent = false } = {}) {
  if (!row?.id) return false;
  const requestToken = ++podRequestToken;
  const embeddedRows = embeddedPodStops(row);

  if (embeddedRows) {
    podRows.value = embeddedRows;
    prunePodEvidence();
    podEndpointUnavailable.value = false;
    podLastUpdatedAt.value = new Date();
    void renderTripMap();
  }

  podLoading.value = true;
  if (!silent) podError.value = '';
  try {
    const response = await getFleetTripStops(row.id);
    if (requestToken !== podRequestToken || String(selectedTrip.value?.id) !== String(row.id)) return false;

    const payload = unwrapData(response);
    const rows = podStopRowsFromPayload(payload);
    if (!rows) {
      podError.value = 'Format data POD per toko belum dikenali. Pastikan API mengirimkan daftar stops.';
      return false;
    }

    podRows.value = rows;
    prunePodEvidence();
    podEndpointUnavailable.value = false;
    podLastUpdatedAt.value = new Date();
    await renderTripMap();
    return true;
  } catch (error) {
    if (requestToken !== podRequestToken) return false;
    if (isPodEndpointUnavailable(error)) {
      podEndpointUnavailable.value = true;
      podError.value = '';
      if (!embeddedRows) {
        podRows.value = [];
        prunePodEvidence();
      }
      await renderTripMap();
      return false;
    }

    if (!silent) {
      podError.value = normalizeError(error, 'Data POD per toko belum dapat dimuat.');
    }
    return false;
  } finally {
    if (requestToken === podRequestToken) podLoading.value = false;
  }
}

async function openTrip(row) {
  clearPodEvidence();
  selectedTrip.value = row;
  tripModalOpen.value = true;
  gpsRows.value = [];
  podRows.value = embeddedPodStops(row) || [];
  podLoading.value = false;
  podError.value = '';
  podEndpointUnavailable.value = false;
  podLastUpdatedAt.value = podRows.value.length ? new Date() : null;
  tripMapError.value = '';
  ++tripMapToken;
  destroyTripMap();
  startForm.odometer = row.start_odometer || '';
  startForm.notes = row.origin_note || '';
  completeForm.odometer = row.end_odometer || '';
  completeForm.destination_note = row.destination_note || '';
  completeForm.notes = row.notes || '';
  void renderTripMap();
  await Promise.all([loadTripGpsHistory(row), loadTripPodStops(row)]);
}

function closeTripModal() {
  tripModalOpen.value = false;
  gpsRows.value = [];
  podRows.value = [];
  podError.value = '';
  podEndpointUnavailable.value = false;
  podLastUpdatedAt.value = null;
  clearPodEvidence();
  ++gpsRequestToken;
  ++podRequestToken;
  ++tripMapToken;
  tripMapError.value = '';
  destroyTripMap();
}

async function refreshGpsMonitoring({ manual = false } = {}) {
  if (monitoringRefreshInFlight) return;
  monitoringRefreshInFlight = true;
  gpsMonitoringRefreshing.value = true;
  try {
    await loadData({ silent: !manual, includeMaintenance: false });
    if (tripModalOpen.value && selectedTrip.value) {
      await Promise.all([
        loadTripGpsHistory(selectedTrip.value, { silent: !manual }),
        loadTripPodStops(selectedTrip.value, { silent: !manual })
      ]);
    }
  } finally {
    monitoringRefreshInFlight = false;
    gpsMonitoringRefreshing.value = false;
  }
}

async function beginTrip() {
  if (!selectedTrip.value) return;
  tripActionLoading.value = true;
  try {
    await startFleetTrip(selectedTrip.value.id, { start_odometer: startForm.odometer, origin_note: startForm.notes });
    successMessage.value = 'Perjalanan berhasil dimulai.';
    await loadData();
    await openTrip(trips.value.find((row) => String(row.id) === String(selectedTrip.value.id)) || selectedTrip.value);
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Perjalanan belum dapat dimulai.');
  } finally {
    tripActionLoading.value = false;
  }
}

async function finishTrip() {
  if (!selectedTrip.value) return;
  tripActionLoading.value = true;
  try {
    await completeFleetTrip(selectedTrip.value.id, {
      end_odometer: completeForm.odometer,
      destination_note: completeForm.destination_note,
      notes: completeForm.notes
    });
    successMessage.value = 'Perjalanan berhasil ditandai selesai.';
    closeTripModal();
    await loadData();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Perjalanan belum dapat diselesaikan.');
  } finally {
    tripActionLoading.value = false;
  }
}

async function reconcileCompletedTrip() {
  if (!selectedTrip.value) return;
  const tripId = selectedTrip.value.id;
  tripActionLoading.value = true;
  try {
    // The endpoint is deliberately idempotent for a completed trip.  This is
    // useful for legacy trips that reached SELESAI before POD/retur outcomes
    // were synchronised to the related Sales Orders.
    const response = await completeFleetTrip(tripId, {});
    const data = unwrapResponse(response) || {};
    const completed = Array.isArray(data.sales_orders_completed) ? data.sales_orders_completed.length : 0;
    const revision = Array.isArray(data.sales_orders_revision) ? data.sales_orders_revision.length : 0;
    successMessage.value = revision
      ? `${completed} Sales Order selesai dan ${revision} Sales Order masuk Perlu Revisi untuk tindak lanjut retur/QC.`
      : completed
        ? `${completed} Sales Order berhasil disinkronkan menjadi selesai.`
        : 'Hasil perjalanan sudah disinkronkan. Tidak ada Sales Order yang perlu diubah.';
    await loadData();
    await openTrip(trips.value.find((row) => String(row.id) === String(tripId)) || selectedTrip.value);
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Status Sales Order belum dapat disinkronkan.');
  } finally {
    tripActionLoading.value = false;
  }
}

function openMaintenanceModal() {
  maintenanceForm.id_armada = '';
  maintenanceForm.maintenance_type = 'SERVICE';
  maintenanceForm.status = 'SELESAI';
  maintenanceForm.maintenance_date = new Date().toISOString().slice(0, 10);
  maintenanceForm.odometer_km = '';
  maintenanceForm.next_due_date = '';
  maintenanceForm.next_due_odometer_km = '';
  maintenanceForm.amount = '';
  maintenanceForm.workshop_vendor = '';
  maintenanceForm.notes = '';
  maintenanceModalOpen.value = true;
}

async function saveMaintenance() {
  if (!maintenanceForm.id_armada) {
    errorMessage.value = 'Pilih armada untuk catatan maintenance.';
    return;
  }
  maintenanceSaving.value = true;
  try {
    await createFleetMaintenance(maintenanceForm);
    maintenanceModalOpen.value = false;
    successMessage.value = 'Catatan maintenance armada berhasil disimpan.';
    await loadData();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Catatan maintenance belum dapat disimpan.');
  } finally {
    maintenanceSaving.value = false;
  }
}

onMounted(async () => {
  try {
    await loadReferenceData();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Referensi armada belum dapat dimuat.');
  }
  // Membuka halaman harus tetap bisa dilakukan oleh pemegang akses lihat.
  // Sinkronisasi manifest adalah aksi tulis dan hanya dilakukan saat tombolnya
  // dipilih oleh pengguna yang memang memiliki hak tersebut.
  await loadData();

  if (typeof window !== 'undefined') {
    gpsRefreshTimer = window.setInterval(() => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
      void refreshGpsMonitoring();
    }, 30000);
  }
});

onUnmounted(() => {
  ++activeFleetMapToken;
  ++tripMapToken;
  ++gpsRequestToken;
  ++podRequestToken;
  clearPodEvidence();
  if (gpsRefreshTimer && typeof window !== 'undefined') window.clearInterval(gpsRefreshTimer);
  gpsRefreshTimer = null;
  destroyActiveFleetMap();
  destroyTripMap();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Monitoring Armada"
      description="Pantau perjalanan kendaraan, penugasan manifest, GPS terakhir, POD, dan jadwal maintenance dari aplikasi Driver dan Helper."
    >
      <template #actions>
        <button class="btn-secondary" :disabled="gpsMonitoringRefreshing" @click="refreshGpsMonitoring({ manual: true })">
          {{ gpsMonitoringRefreshing ? 'Memperbarui GPS...' : 'Refresh GPS' }}
        </button>
        <button class="btn-secondary" :disabled="loading" @click="loadData({ sync: true })">Sinkronkan Manifest</button>
        <button class="btn-primary" @click="openMaintenanceModal">Tambah Maintenance</button>
      </template>
    </PageHeader>

    <AppFilterBar
      :model-value="filters"
      :fields="filterFields"
      @update:model-value="updateFilters"
      @submit="loadData"
      @reset="resetFilters"
    />

    <div class="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
      <section v-for="item in statCards" :key="item.label" class="panel p-4">
        <p class="text-sm text-slate-500">{{ item.label }}</p>
        <p :class="['mt-2 text-2xl font-semibold', item.tone]">{{ item.value }}</p>
      </section>
    </div>

    <section class="panel overflow-hidden">
      <div class="flex flex-wrap items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
        <div>
          <div class="flex flex-wrap items-center gap-2">
            <h2 class="text-lg font-semibold text-slate-950">Peta Armada Aktif</h2>
            <span class="rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-700">{{ activeFleetTrips.length }} kendaraan</span>
          </div>
          <p class="mt-1 text-sm text-slate-500">Posisi terakhir armada berstatus dalam perjalanan atau bermasalah. Klik marker untuk detail singkat kendaraan.</p>
        </div>
        <div class="text-right text-xs text-slate-500">
          <p>Pembaruan otomatis setiap 30 detik</p>
          <p class="mt-1">Terakhir diperbarui: <span class="font-semibold text-slate-700">{{ formatDateTime(lastGpsRefreshAt) }}</span></p>
        </div>
      </div>

      <div v-if="activeFleetTrips.length" class="relative">
        <div ref="activeFleetMapRef" class="h-[360px] w-full bg-slate-100"></div>
        <div v-if="activeFleetMapLoading" class="absolute inset-0 flex items-center justify-center bg-white/70 text-sm font-semibold text-slate-600">Memuat peta armada...</div>
      </div>
      <div v-else class="px-5 py-10 text-center text-sm text-slate-500">
        Belum ada titik GPS dari armada yang sedang berjalan. Posisi akan muncul setelah aplikasi Driver/Helper mengirim lokasi.
      </div>
      <p v-if="activeFleetMapError" class="border-t border-rose-200 bg-rose-50 px-5 py-3 text-sm text-rose-700">{{ activeFleetMapError }}</p>
      <div v-if="activeFleetTrips.length" class="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-slate-200 px-5 py-3 text-xs text-slate-600">
        <span class="inline-flex items-center gap-2"><span class="h-2.5 w-2.5 rounded-full bg-emerald-600"></span>Dalam perjalanan</span>
        <span class="inline-flex items-center gap-2"><span class="h-2.5 w-2.5 rounded-full bg-rose-600"></span>Bermasalah</span>
        <span>Hanya marker dengan koordinat GPS valid yang ditampilkan.</span>
      </div>
    </section>

    <div v-if="errorMessage" class="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ errorMessage }}</div>
    <div v-if="successMessage" class="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{{ successMessage }}</div>

    <section class="space-y-3">
      <div class="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 class="text-lg font-semibold text-slate-950">Perjalanan Armada</h2>
          <p class="mt-1 text-sm text-slate-500">Satu baris adalah satu manifest perjalanan. Klik untuk membuka GPS dan tindakan operasional.</p>
        </div>
      </div>
      <AppTable
        :rows="trips"
        :columns="tripColumns"
        :loading="loading"
        :clickable-rows="true"
        row-key="id"
        empty-message="Belum ada perjalanan armada dari manifest yang sesuai filter."
        @row-click="openTrip"
      />
    </section>

    <section class="space-y-3">
      <div>
        <h2 class="text-lg font-semibold text-slate-950">Riwayat Maintenance</h2>
        <p class="mt-1 text-sm text-slate-500">Catatan ini akan menjadi sumber jadwal service, ban, STNK, asuransi, dan kondisi kendaraan di aplikasi Driver/Helper.</p>
      </div>
      <AppTable :rows="maintenances" :columns="maintenanceColumns" :loading="loading" row-key="id" empty-message="Belum ada catatan maintenance armada." />
    </section>

    <AppModal
      :open="tripModalOpen"
      size="4xl"
      :title="`Perjalanan ${selectedTrip?.no_manifest || ''}`"
      description="Pantau manifest, petugas, titik GPS, dan status perjalanan armada."
      @close="closeTripModal"
    >
      <div v-if="selectedTrip" class="space-y-5">
        <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div class="rounded-xl border border-slate-200 p-4"><p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Armada</p><p class="mt-2 font-semibold text-slate-900">{{ selectedTrip.nama_armada }}</p><p class="mt-1 text-sm text-slate-500">{{ selectedTrip.no_pelat || '-' }}</p></div>
          <div class="rounded-xl border border-slate-200 p-4"><p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Driver</p><p class="mt-2 font-semibold text-slate-900">{{ selectedTrip.nama_driver }}</p><p class="mt-1 text-sm text-slate-500">{{ selectedTrip.nama_helpers || 'Tanpa helper' }}</p></div>
          <div class="rounded-xl border border-slate-200 p-4"><p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Status</p><p :class="['mt-3 inline-flex', statusClass(selectedTrip.status)]">{{ statusLabel(selectedTrip.status) }}</p></div>
          <div class="rounded-xl border border-slate-200 p-4"><p class="text-xs font-semibold uppercase tracking-wide text-slate-500">GPS Terakhir</p><p class="mt-2 text-sm font-semibold text-slate-900">{{ gpsLabel(currentTripGpsPoint || selectedTrip) }}</p><a v-if="mapUrl(currentTripGpsPoint || selectedTrip)" :href="mapUrl(currentTripGpsPoint || selectedTrip)" target="_blank" rel="noopener" class="mt-2 inline-flex text-sm font-semibold text-brand-700 hover:text-brand-800">Buka Maps</a></div>
        </div>

        <section class="overflow-hidden rounded-xl border border-slate-200 bg-white">
          <div class="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 px-4 py-3">
            <div>
              <h3 class="text-base font-semibold text-slate-900">Jejak Perjalanan Kendaraan</h3>
              <p class="mt-1 text-sm text-slate-500">Garis biru mengikuti urutan titik GPS dari aplikasi Driver/Helper; A adalah titik awal, marker truk adalah posisi terakhir, dan marker bernomor adalah tujuan toko.</p>
            </div>
            <button class="btn-secondary text-sm" :disabled="gpsLoading" @click="loadTripGpsHistory(selectedTrip)">{{ gpsLoading ? 'Memuat GPS...' : 'Refresh Jejak' }}</button>
          </div>
          <div v-if="tripGpsPoints.length || podStopsWithCoordinates.length" class="relative">
            <div ref="tripMapRef" class="h-[390px] w-full bg-slate-100"></div>
            <div v-if="tripMapLoading" class="absolute inset-0 flex items-center justify-center bg-white/70 text-sm font-semibold text-slate-600">Memuat jejak perjalanan...</div>
          </div>
          <div v-else class="px-4 py-10 text-center text-sm text-slate-500">
            Belum ada titik GPS maupun koordinat tujuan untuk perjalanan ini. Jejak akan terlihat setelah aplikasi Driver/Helper mengirim lokasi.
          </div>
          <p v-if="tripMapError" class="border-t border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ tripMapError }}</p>
          <div v-if="tripGpsPoints.length || podStopsWithCoordinates.length" class="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-slate-200 px-4 py-3 text-xs text-slate-600">
            <span v-if="tripGpsPoints.length">{{ tripGpsPoints.length }} titik GPS</span>
            <span v-if="podStopsWithCoordinates.length">{{ podStopsWithCoordinates.length }} tujuan bertitik lokasi</span>
            <span v-if="currentTripGpsPoint">Posisi terakhir: {{ formatDateTime(currentTripGpsPoint?.captured_at || currentTripGpsPoint?.gps_at || currentTripGpsPoint?.received_at) }}</span>
            <a v-if="mapUrl(currentTripGpsPoint)" :href="mapUrl(currentTripGpsPoint)" target="_blank" rel="noopener" class="font-semibold text-brand-700 hover:text-brand-800">Buka posisi terakhir di Maps</a>
          </div>
        </section>

        <section class="overflow-hidden rounded-xl border border-slate-200 bg-white">
          <div class="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 px-4 py-3">
            <div>
              <div class="flex flex-wrap items-center gap-2">
                <h3 class="text-base font-semibold text-slate-900">Pengantaran per Toko &amp; POD</h3>
                <span v-if="podStops.length" class="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700">{{ podSummary.total }} tujuan</span>
                <span v-if="podSummary.delivered" class="rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-700">{{ podSummary.delivered }} terkirim</span>
                <span v-if="podSummary.arrived" class="rounded-full bg-sky-100 px-2.5 py-1 text-xs font-semibold text-sky-700">{{ podSummary.arrived }} tiba</span>
                <span v-if="podSummary.issue" class="rounded-full bg-rose-100 px-2.5 py-1 text-xs font-semibold text-rose-700">{{ podSummary.issue }} perlu tindak lanjut</span>
              </div>
              <p class="mt-1 text-sm text-slate-500">Pantau kunjungan toko, jumlah pesanan versus aktual, retur/selisih, penerima, serta bukti serah terima dari aplikasi Driver/Helper.</p>
            </div>
            <div class="text-right">
              <button class="btn-secondary text-sm" :disabled="podLoading" @click="loadTripPodStops(selectedTrip)">{{ podLoading ? 'Memuat POD...' : 'Refresh POD' }}</button>
              <p v-if="podLastUpdatedAt" class="mt-2 text-xs text-slate-500">Diperbarui: {{ formatDateTime(podLastUpdatedAt) }}</p>
            </div>
          </div>

          <div v-if="podLoading && !podStops.length" class="px-4 py-10 text-center text-sm text-slate-500">Memuat status pengantaran per toko...</div>
          <div v-else-if="podEndpointUnavailable && !podStops.length" class="px-4 py-8 text-sm text-slate-600">
            Data POD per toko belum tersedia dari server. Panel ini akan otomatis menampilkan status dan bukti penerimaan setelah API pengantaran per toko diaktifkan.
          </div>
          <div v-else-if="podError" class="border-y border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ podError }}</div>
          <div v-else-if="!podStops.length" class="px-4 py-10 text-center text-sm text-slate-500">Belum ada tujuan toko pada manifest ini.</div>
          <div v-else class="space-y-4 p-4">
            <article v-for="stop in podStops" :key="stop.id" class="overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
              <div class="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3">
                <div class="min-w-0">
                  <div class="flex flex-wrap items-center gap-2">
                    <span class="inline-flex h-7 min-w-[1.75rem] items-center justify-center rounded-full bg-brand-100 px-2 text-xs font-bold text-brand-700">{{ stop.sequence }}</span>
                    <h4 class="font-semibold text-slate-900">{{ stop.customerName }}</h4>
                    <span v-if="stop.customerCode" class="text-xs font-medium text-slate-500">{{ stop.customerCode }}</span>
                  </div>
                  <p v-if="stop.reference" class="mt-1 text-sm font-medium text-slate-600">{{ stop.reference }}</p>
                  <p v-if="stop.address" class="mt-1 max-w-3xl text-sm text-slate-500">{{ stop.address }}</p>
                  <div class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
                    <span v-if="stop.telephone">{{ stop.telephone }}</span>
                    <a v-if="podMapUrl(stop)" :href="podMapUrl(stop)" target="_blank" rel="noopener" class="font-semibold text-brand-700 hover:text-brand-800">Buka tujuan di Maps</a>
                  </div>
                </div>
                <span :class="['inline-flex shrink-0', podStatus(stop).className]">{{ podStatus(stop).label }}</span>
              </div>

              <div class="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-4">
                <div class="rounded-lg border border-slate-200 bg-white p-3"><p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Tiba di Lokasi</p><p class="mt-1 text-sm font-semibold text-slate-900">{{ formatDateTime(stop.arrivedAt) }}</p></div>
                <div class="rounded-lg border border-slate-200 bg-white p-3"><p class="text-xs font-semibold uppercase tracking-wide text-slate-500">POD / Selesai</p><p class="mt-1 text-sm font-semibold text-slate-900">{{ formatDateTime(stop.deliveredAt) }}</p></div>
                <div class="rounded-lg border border-slate-200 bg-white p-3"><p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Penerima</p><p class="mt-1 text-sm font-semibold text-slate-900">{{ stop.receiverName || '-' }}</p><p v-if="stop.receiverPhone" class="mt-1 text-xs text-slate-500">{{ stop.receiverPhone }}</p></div>
                <div class="rounded-lg border border-slate-200 bg-white p-3"><p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Item</p><p class="mt-1 text-sm font-semibold text-slate-900">{{ stop.itemCount || 0 }} item</p><p class="mt-1 text-xs text-slate-500">Pesanan dan aktual dirinci di bawah.</p></div>
              </div>

              <div v-if="hasValue(stop.plannedQty) || hasValue(stop.actualQty) || hasValue(stop.returnQty) || hasValue(stop.discrepancyQty)" class="grid gap-3 px-4 pb-4 sm:grid-cols-2 xl:grid-cols-4">
                <div class="rounded-lg border border-slate-200 bg-white p-3"><p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Pesanan</p><p class="mt-1 font-semibold text-slate-900">{{ stop.plannedLabel }}</p></div>
                <div class="rounded-lg border border-emerald-200 bg-emerald-50 p-3"><p class="text-xs font-semibold uppercase tracking-wide text-emerald-700">Aktual Diterima</p><p class="mt-1 font-semibold text-emerald-900">{{ stop.actualLabel }}</p></div>
                <div class="rounded-lg border border-amber-200 bg-amber-50 p-3"><p class="text-xs font-semibold uppercase tracking-wide text-amber-700">Retur</p><p class="mt-1 font-semibold text-amber-900">{{ stop.returnLabel }}</p></div>
                <div class="rounded-lg border border-rose-200 bg-rose-50 p-3"><p class="text-xs font-semibold uppercase tracking-wide text-rose-700">Selisih Bersih</p><p class="mt-1 font-semibold text-rose-900">{{ stop.discrepancyLabel }}</p></div>
              </div>

              <div v-if="stop.notes || stop.discrepancyNotes || stop.returnNotes" class="mx-4 mb-4 grid gap-3 md:grid-cols-3">
                <div v-if="stop.notes" class="rounded-lg border border-slate-200 bg-white p-3 text-sm text-slate-700"><p class="font-semibold text-slate-900">Catatan pengantaran</p><p class="mt-1 whitespace-pre-line">{{ stop.notes }}</p></div>
                <div v-if="stop.discrepancyNotes" class="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800"><p class="font-semibold">Catatan selisih</p><p class="mt-1 whitespace-pre-line">{{ stop.discrepancyNotes }}</p></div>
                <div v-if="stop.returnNotes" class="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"><p class="font-semibold">Catatan retur</p><p class="mt-1 whitespace-pre-line">{{ stop.returnNotes }}</p></div>
              </div>

              <div v-if="stop.photoUrl || stop.signatureUrl || stop.evidenceUrl" class="mx-4 mb-4 grid gap-3 md:grid-cols-3">
                <div v-if="stop.photoUrl" class="overflow-hidden rounded-lg border border-slate-200 bg-white p-3">
                  <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Foto POD</p>
                  <a v-if="podEvidencePreviewUrl(stop, 'photo')" :href="podEvidencePreviewUrl(stop, 'photo')" target="_blank" rel="noopener" class="mt-2 block rounded-md transition hover:opacity-90">
                    <img :src="podEvidencePreviewUrl(stop, 'photo')" :alt="`Foto POD ${stop.customerName}`" class="h-28 w-full rounded-md object-cover" loading="lazy" />
                    <p class="mt-2 text-xs font-semibold text-brand-700">Buka foto ukuran penuh</p>
                  </a>
                  <button v-else class="btn-secondary mt-3 w-full text-sm" :disabled="isPodEvidenceLoading(stop, 'photo')" @click="loadPodEvidence(stop, 'photo')">{{ isPodEvidenceLoading(stop, 'photo') ? 'Memuat foto...' : 'Muat Foto POD' }}</button>
                  <p v-if="podEvidenceError(stop, 'photo')" class="mt-2 text-xs text-rose-700">{{ podEvidenceError(stop, 'photo') }}</p>
                </div>
                <div v-if="stop.signatureUrl" class="overflow-hidden rounded-lg border border-slate-200 bg-white p-3">
                  <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Tanda tangan penerima</p>
                  <a v-if="podEvidencePreviewUrl(stop, 'signature')" :href="podEvidencePreviewUrl(stop, 'signature')" target="_blank" rel="noopener" class="mt-2 block rounded-md transition hover:opacity-90">
                    <img :src="podEvidencePreviewUrl(stop, 'signature')" :alt="`Tanda tangan ${stop.customerName}`" class="h-28 w-full rounded-md bg-slate-50 object-contain" loading="lazy" />
                    <p class="mt-2 text-xs font-semibold text-brand-700">Buka tanda tangan ukuran penuh</p>
                  </a>
                  <button v-else class="btn-secondary mt-3 w-full text-sm" :disabled="isPodEvidenceLoading(stop, 'signature')" @click="loadPodEvidence(stop, 'signature')">{{ isPodEvidenceLoading(stop, 'signature') ? 'Memuat tanda tangan...' : 'Muat Tanda Tangan' }}</button>
                  <p v-if="podEvidenceError(stop, 'signature')" class="mt-2 text-xs text-rose-700">{{ podEvidenceError(stop, 'signature') }}</p>
                </div>
                <div v-if="stop.evidenceUrl" class="rounded-lg border border-slate-200 bg-white p-3">
                  <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Dokumen bukti</p>
                  <a v-if="podEvidencePreviewUrl(stop, 'document')" :href="podEvidencePreviewUrl(stop, 'document')" target="_blank" rel="noopener" class="mt-3 inline-flex text-sm font-semibold text-brand-700 hover:text-brand-800">Buka dokumen POD</a>
                  <button v-else class="btn-secondary mt-3 w-full text-sm" :disabled="isPodEvidenceLoading(stop, 'document')" @click="loadPodEvidence(stop, 'document')">{{ isPodEvidenceLoading(stop, 'document') ? 'Memuat dokumen...' : 'Muat Dokumen POD' }}</button>
                  <p v-if="podEvidenceError(stop, 'document')" class="mt-2 text-xs text-rose-700">{{ podEvidenceError(stop, 'document') }}</p>
                </div>
              </div>

              <div v-if="stop.items.length" class="border-t border-slate-200 bg-white px-4 py-4">
                <p class="text-sm font-semibold text-slate-900">Rincian barang</p>
                <div class="mt-3 overflow-x-auto rounded-lg border border-slate-200">
                  <table class="min-w-full divide-y divide-slate-200 text-sm">
                    <thead class="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                      <tr><th class="px-3 py-2">Barang</th><th class="px-3 py-2">Pesanan</th><th class="px-3 py-2">Aktual</th><th class="px-3 py-2">Retur</th><th class="px-3 py-2">Selisih</th></tr>
                    </thead>
                    <tbody class="divide-y divide-slate-100 bg-white text-slate-700">
                      <tr v-for="item in stop.items" :key="item.id">
                        <td class="px-3 py-2"><p class="font-medium text-slate-900">{{ item.productName }}</p><p v-if="item.productCode" class="mt-0.5 text-xs text-slate-500">{{ item.productCode }}</p></td>
                        <td class="px-3 py-2">{{ item.plannedLabel }}</td>
                        <td class="px-3 py-2 font-medium text-emerald-700">{{ item.actualLabel }}</td>
                        <td class="px-3 py-2 text-amber-700">{{ item.returnLabel }}</td>
                        <td class="px-3 py-2 text-rose-700">{{ item.discrepancyLabel }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </article>
          </div>
        </section>

        <section class="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 class="text-base font-semibold text-slate-900">Verifikasi Muatan</h3>
              <p class="mt-1 text-sm text-slate-500">Konfirmasi Driver/Helper atas manifest dan barang yang dimuat sebelum perjalanan dimulai.</p>
            </div>
            <span :class="['inline-flex', manifestConfirmation(selectedTrip).className]">{{ manifestConfirmation(selectedTrip).label }}</span>
          </div>

          <template v-if="hasManifestVerificationData(selectedTrip)">
            <div class="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <div class="rounded-lg border border-slate-200 bg-white p-3"><p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Item Dicek</p><p class="mt-1 font-semibold text-slate-900">{{ confirmationProgress(selectedTrip) }}</p></div>
              <div class="rounded-lg border border-slate-200 bg-white p-3"><p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Dikonfirmasi Oleh</p><p class="mt-1 font-semibold text-slate-900">{{ selectedTrip.manifest_confirmation_by || '-' }}</p></div>
              <div class="rounded-lg border border-slate-200 bg-white p-3"><p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Waktu Konfirmasi</p><p class="mt-1 font-semibold text-slate-900">{{ formatDateTime(selectedTrip.manifest_confirmation_at) }}</p></div>
              <div class="rounded-lg border border-slate-200 bg-white p-3"><p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Status Pemeriksaan</p><p class="mt-1 font-semibold text-slate-900">{{ manifestConfirmation(selectedTrip).label }}</p></div>
            </div>
            <div v-if="manifestConfirmationNote(selectedTrip)" class="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
              <p class="font-semibold">Catatan selisih</p>
              <p class="mt-1 whitespace-pre-line">{{ manifestConfirmationNote(selectedTrip) }}</p>
            </div>
          </template>
          <p v-else class="mt-3 text-sm text-slate-600">Belum ada konfirmasi muatan dari aplikasi Driver/Helper untuk manifest ini.</p>
        </section>

        <div v-if="selectedTrip.status === 'SIAP_JALAN'" class="rounded-xl border border-sky-200 bg-sky-50 p-4">
          <p class="font-semibold text-sky-900">Mulai perjalanan</p>
          <div class="mt-3 grid gap-3 md:grid-cols-2">
            <AppFormField v-model="startForm.odometer" label="Odometer awal" type="number" placeholder="Contoh: 12500" />
            <AppFormField v-model="startForm.notes" label="Catatan keberangkatan" placeholder="Opsional" />
          </div>
          <button class="btn-primary mt-4" :disabled="tripActionLoading" @click="beginTrip">Mulai Perjalanan</button>
        </div>

        <div v-if="selectedTrip.status === 'BERANGKAT'" class="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
          <p class="font-semibold text-emerald-900">Selesaikan monitoring perjalanan</p>
          <div class="mt-3 grid gap-3 md:grid-cols-2">
            <AppFormField v-model="completeForm.odometer" label="Odometer akhir" type="number" placeholder="Contoh: 12625" />
            <AppFormField v-model="completeForm.destination_note" label="Lokasi akhir" placeholder="Gudang / customer / lokasi lain" />
          </div>
          <div class="mt-3"><AppFormField v-model="completeForm.notes" label="Catatan perjalanan" type="textarea" placeholder="Catatan kondisi kendaraan, hambatan, atau serah terima" /></div>
          <button class="btn-primary mt-4" :disabled="tripActionLoading" @click="finishTrip">Selesaikan Perjalanan</button>
        </div>

        <div v-else-if="selectedTrip.status === 'SELESAI'" class="rounded-xl border border-violet-200 bg-violet-50 p-4">
          <p class="font-semibold text-violet-950">Sinkronkan hasil perjalanan</p>
          <p class="mt-1 text-sm text-violet-900">Gunakan untuk perjalanan lama yang sudah selesai tetapi status Sales Order atau retur/QC belum ikut tersinkron.</p>
          <button class="btn-secondary mt-4" :disabled="tripActionLoading" @click="reconcileCompletedTrip">
            {{ tripActionLoading ? 'Menyinkronkan...' : 'Sinkronkan Status Sales Order' }}
          </button>
        </div>

        <div class="space-y-2">
          <h3 class="text-base font-semibold text-slate-900">Riwayat GPS</h3>
          <AppTable :rows="gpsRows" :columns="gpsColumns" :loading="gpsLoading" :paginated="false" row-key="id" empty-message="Belum ada titik GPS. Nantinya aplikasi Driver/Helper akan mengirim titik secara otomatis ketika perjalanan dimulai." />
        </div>
      </div>
    </AppModal>

    <AppModal
      :open="maintenanceModalOpen"
      title="Tambah Maintenance Armada"
      description="Simpan pekerjaan service dan jadwal berikutnya agar kendaraan tetap siap beroperasi."
      @close="maintenanceModalOpen = false"
    >
      <div class="grid gap-4 md:grid-cols-2">
        <AppSearchSelect v-model="maintenanceForm.id_armada" label="Armada" placeholder="Pilih armada" :options="fleetOptions" />
        <AppSearchSelect v-model="maintenanceForm.maintenance_type" label="Jenis maintenance" :options="maintenanceTypeOptions" />
        <AppFormField v-model="maintenanceForm.maintenance_date" label="Tanggal maintenance" type="date" />
        <AppFormField v-model="maintenanceForm.odometer_km" label="Odometer (km)" type="number" />
        <AppFormField v-model="maintenanceForm.next_due_date" label="Jadwal maintenance berikutnya" type="date" />
        <AppFormField v-model="maintenanceForm.next_due_odometer_km" label="Batas odometer berikutnya" type="number" />
        <AppFormField v-model="maintenanceForm.amount" label="Biaya" type="number" placeholder="0" />
        <AppFormField v-model="maintenanceForm.workshop_vendor" label="Bengkel / vendor" placeholder="Opsional" />
      </div>
      <div class="mt-4"><AppFormField v-model="maintenanceForm.notes" label="Catatan" type="textarea" placeholder="Pekerjaan yang dilakukan atau keluhan kendaraan" /></div>
      <template #footer>
        <div class="flex justify-end gap-3"><button class="btn-secondary" @click="maintenanceModalOpen = false">Batal</button><button class="btn-primary" :disabled="maintenanceSaving" @click="saveMaintenance">Simpan Maintenance</button></div>
      </template>
    </AppModal>
  </div>
</template>
