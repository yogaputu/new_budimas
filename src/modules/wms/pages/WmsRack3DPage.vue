<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { getBranches, getCompanies } from '@/api/master';
import { getWmsPlacements, getWmsRacks } from '@/api/wms';
import { useAuthStore } from '@/app/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getBranchOptionsForCompany, getCompanyOptionsForScope, resetBranchWhenCompanyChanges } from '@/utils/filterScope';
import PageHeader from '@/shared/components/PageHeader.vue';

const auth = useAuthStore();
const sceneHost = ref(null);
const loading = ref(false);
const errorMessage = ref('');
const rackRows = ref([]);
const placementRows = ref([]);
const companyRows = ref([]);
const branchRows = ref([]);
const referencesLoaded = ref(false);
const selectedRackCode = ref('');

const filters = reactive({
  companyId: '',
  branchId: '',
  warehouse: '',
  search: '',
  type: '',
  status: '',
  active: 'true'
});

const rackTypeOptions = [
  { value: '', label: 'Semua tipe' },
  { value: 'Tetap', label: 'Tetap' },
  { value: 'Titipan', label: 'Titipan' },
  { value: 'Transit', label: 'Transit' },
  { value: 'Karantina', label: 'Karantina' }
];

const rackStatusOptions = [
  { value: '', label: 'Semua status' },
  { value: 'Isi', label: 'Isi' },
  { value: 'Kosong', label: 'Kosong' },
  { value: 'Nonaktif', label: 'Nonaktif' }
];

const rackActiveOptions = [
  { value: '', label: 'Semua rak' },
  { value: 'true', label: 'Aktif' },
  { value: 'false', label: 'Nonaktif' }
];

const WMS_PAGE_SIZE = 5000;
const RACK_REQUEST_TIMEOUT_MS = 30000;
const PLACEMENT_REQUEST_TIMEOUT_MS = 45000;

const companyOptions = computed(() => getCompanyOptionsForScope(companyRows.value, auth, true));
const branchOptions = computed(() =>
  getBranchOptionsForCompany(branchRows.value, auth, filters.companyId, true, companyRows.value)
);

const processSteps = [
  { key: 'receiving', label: 'Receiving', meta: 'Barang masuk' },
  { key: 'qr', label: 'QR Palet', meta: 'Cetak lokasi' },
  { key: 'titipan', label: 'Rak Titipan', meta: 'Simpan sementara' },
  { key: 'transfer', label: 'Transfer', meta: 'Titipan ke tetap' },
  { key: 'tetap', label: 'Rak Tetap', meta: 'Ready picking' },
  { key: 'picking', label: 'Picking', meta: 'Ambil barang' },
  { key: 'shipping', label: 'Shipping', meta: 'Kirim' }
];

let scene;
let camera;
let renderer;
let controls;
let animationFrame;
let resizeObserver;
let dynamicGroup;
let staticGroup;
let rackMesh;
let palletMesh;
let selectedOutline;
let rackInstanceRows = [];
let loadRequestId = 0;
let activeLoadController;

const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
const tempMatrix = new THREE.Matrix4();
const tempPosition = new THREE.Vector3();
const tempQuaternion = new THREE.Quaternion();
const tempScale = new THREE.Vector3();

const EXCEL_LAYOUT = {
  centerCol: 33.5,
  centerRow: 34.5,
  cellX: 1.18,
  cellZ: 0.78,
  rackDepth: 0.62,
  rackWidth: 1.04,
  rackHeight: 0.28
};

const rackBlockColumns = [
  { racks: [2, 3], colLeft: 5.7, colRight: 7.3, labelCol: 6.5 },
  { racks: [4, 5], colLeft: 11.7, colRight: 13.3, labelCol: 12.5 },
  { racks: [6, 7], colLeft: 17.7, colRight: 19.3, labelCol: 18.5 },
  { racks: [8, 9], colLeft: 23.7, colRight: 25.3, labelCol: 24.5 },
  { racks: [10, 11], colLeft: 29.7, colRight: 31.3, labelCol: 30.5 },
  { racks: [12, 13], colLeft: 35.7, colRight: 37.3, labelCol: 36.5 },
  { racks: [14, 15], colLeft: 41.7, colRight: 43.3, labelCol: 42.5 },
  { racks: [16, 17], colLeft: 47.7, colRight: 49.3, labelCol: 48.5 },
  { racks: [18, 19], colLeft: 53.7, colRight: 55.3, labelCol: 54.5 },
  { racks: [20, 21], colLeft: 59.7, colRight: 61.3, labelCol: 60.5 }
];

const denahRackLabels = [
  { label: 'RAK 01', col: 1.5, row: 7.8, area: 'food' },
  { label: 'RAK 02', col: 6.5, row: 7, area: 'food' },
  { label: 'RAK 04', col: 12.5, row: 7, area: 'food' },
  { label: 'RAK 06', col: 18.5, row: 7, area: 'food' },
  { label: 'RAK 08', col: 24.5, row: 7, area: 'food' },
  { label: 'RAK 10', col: 30.5, row: 7, area: 'food' },
  { label: 'RAK 03', col: 6.5, row: 62, area: 'food' },
  { label: 'RAK 05', col: 12.5, row: 62, area: 'food' },
  { label: 'RAK 07', col: 18.5, row: 62, area: 'food' },
  { label: 'RAK 09', col: 24.5, row: 62, area: 'food' },
  { label: 'RAK 11', col: 30.5, row: 62, area: 'food' },
  { label: 'RAK 12', col: 36.5, row: 19, area: 'nonfood' },
  { label: 'RAK 14', col: 42.5, row: 19, area: 'nonfood' },
  { label: 'RAK 16', col: 48.5, row: 19, area: 'nonfood' },
  { label: 'RAK 18', col: 54.5, row: 19, area: 'nonfood' },
  { label: 'RAK 20', col: 60.5, row: 19, area: 'nonfood' },
  { label: 'RAK 13', col: 36.5, row: 62, area: 'nonfood' },
  { label: 'RAK 15', col: 42.5, row: 62, area: 'nonfood' },
  { label: 'RAK 17', col: 48.5, row: 62, area: 'nonfood' },
  { label: 'RAK 19', col: 54.5, row: 62, area: 'nonfood' },
  { label: 'RAK 21', col: 60.5, row: 62, area: 'nonfood' },
  { label: 'RAK 22', col: 65.5, row: 20, area: 'nonfood' }
];

const placementMap = computed(() => {
  const map = new Map();

  placementRows.value.forEach((row) => {
    const code = rackCode(row);
    if (!code) return;
    const rows = map.get(code) || [];
    rows.push(row);
    map.set(code, rows);
  });

  return map;
});

const usingFallbackLayout = computed(() => !rackRows.value.length && !loading.value);

const normalizedRacks = computed(() => {
  const rows = rackRows.value.length ? rackRows.value : createFallbackRackRows();

  return rows.map((row, index) => {
    const code = rackCode(row) || `SIM-RACK-${String(index + 1).padStart(3, '0')}`;
    const placements = (placementMap.value.get(code) || []).filter(rowHasStock);
    const active = normalizeActive(row.active ?? row.is_active ?? row.status_aktif);
    const type = textValue(row.type_rak || row.tipe_rak || row.type || row.tipe || 'Tetap');
    const rawStatus = normalizeText(row.status_rak || row.status || '');
    const hasStock = rowHasStock(row) || placements.length > 0;
    const status = !active || rawStatus === 'nonaktif'
      ? 'Nonaktif'
      : hasStock
        ? 'Isi'
        : 'Kosong';
    const parsed = parseRackPosition(row, code, index);
    const denah = denahPositionForRack({ parsed }, index);
    const qtyKarton = placements.reduce((sum, item) => sum + rowQtyKarton(item), 0);
    const qtyPcs = placements.reduce((sum, item) => sum + rowQtyPcs(item), 0);
    const productNames = uniqueValues(
      [
        ...(rowHasStock(row) ? [rowProductName(row) || rowProductCode(row)] : []),
        ...placements.map((item) => rowProductName(item) || rowProductCode(item))
      ]
    );

    return {
      id: row.id || code,
      code,
      type,
      status,
      active,
      parsed,
      denah,
      qtyKarton,
      qtyPcs,
      productCount: productNames.length,
      productNames,
      source: row,
      placements,
      searchText: [
        code,
        type,
        status,
        rowProductName(row),
        rowProductCode(row),
        row.description,
        ...productNames,
        ...placements.flatMap((item) => [rowProductCode(item), rowProductName(item), rowBatch(item)])
      ].filter(Boolean).join(' ').toLowerCase()
    };
  });
});

const warehouseOptions = computed(() => {
  const warehouses = [...new Set(normalizedRacks.value
    .map((row) => String(row.parsed?.gudang || ''))
    .filter(Boolean))]
    .sort((left, right) => Number(left) - Number(right));

  return warehouses.map((value) => ({
    value,
    label: `Gudang ${value}`
  }));
});

const warehouseStorageRacks = computed(() => normalizedRacks.value.filter((row) =>
  !isAisleRack(row)
  && (!filters.warehouse || String(row.parsed?.gudang || '') === String(filters.warehouse))
));

const filteredRacks = computed(() => {
  const keyword = filters.search.trim().toLowerCase();

  return warehouseStorageRacks.value.filter((row) => {
    const matchSearch = !keyword || row.searchText.includes(keyword);
    const matchType = !filters.type || normalizeText(row.type) === normalizeText(filters.type);
    const matchStatus = !filters.status || normalizeText(row.status) === normalizeText(filters.status);
    const matchActive = filters.active === ''
      || (filters.active === 'true' && row.active)
      || (filters.active === 'false' && !row.active);

    return matchSearch && matchType && matchStatus && matchActive;
  });
});

const sceneRacks = computed(() => aggregateSceneRacks(filteredRacks.value));
const warehouseSceneRacks = computed(() => aggregateSceneRacks(warehouseStorageRacks.value));

const selectedRack = computed(() =>
  sceneRacks.value.find((row) => row.code === selectedRackCode.value)
  || warehouseSceneRacks.value.find((row) => row.code === selectedRackCode.value)
  || sceneRacks.value[0]
  || warehouseSceneRacks.value[0]
  || null
);

const selectedRackPlacementRows = computed(() => [...(selectedRack.value?.placements || [])]
  .filter(rowHasStock)
  .sort((left, right) =>
    rowProductName(left).localeCompare(rowProductName(right), 'id')
    || rowProductCode(left).localeCompare(rowProductCode(right), 'id')
    || rowBatch(left).localeCompare(rowBatch(right), 'id')
  ));

const summaryCards = computed(() => {
  const rows = warehouseSceneRacks.value;
  const visible = sceneRacks.value;
  const occupied = rows.filter((row) => row.status === 'Isi').length;
  const inactive = rows.filter((row) => !row.active || row.status === 'Nonaktif').length;
  const temporary = rows.filter((row) => normalizeText(row.type).includes('titipan')).length;
  const fixed = rows.filter((row) => normalizeText(row.type).includes('tetap')).length;

  return [
    { label: 'Rak Tampil', value: numberLabel(visible.length), tone: 'blue' },
    { label: 'Rak Fisik', value: numberLabel(rows.length), tone: 'slate' },
    { label: 'Rak Isi', value: numberLabel(occupied), tone: 'amber' },
    { label: 'Rak Titipan', value: numberLabel(temporary), tone: 'emerald' },
    { label: 'Rak Tetap', value: numberLabel(fixed), tone: 'indigo' },
    { label: 'Nonaktif', value: numberLabel(inactive), tone: 'rose' }
  ];
});

const aisleStats = computed(() => {
  const grouped = new Map();

  sceneRacks.value.forEach((row) => {
    const key = `G${String(row.parsed.gudang || 0)}-R${String(row.parsed.rak || 0).padStart(2, '0')}`;
    const item = grouped.get(key) || { aisle: key, total: 0, occupied: 0, temporary: 0 };
    item.total += 1;
    if (row.status === 'Isi') item.occupied += 1;
    if (normalizeText(row.type).includes('titipan')) item.temporary += 1;
    grouped.set(key, item);
  });

  return [...grouped.values()]
    .sort((a, b) => b.total - a.total)
    .slice(0, 8);
});

watch(
  sceneRacks,
  (rows) => {
    if (!rows.some((row) => row.code === selectedRackCode.value)) {
      selectedRackCode.value = rows.find((row) => row.status === 'Isi')?.code || rows[0]?.code || '';
    }
    rebuildDynamicScene();
  },
  { flush: 'post' }
);

watch(selectedRackCode, () => {
  updateSelectedOutline();
});

watch(
  () => filters.companyId,
  () => {
    const branchReset = resetBranchWhenCompanyChanges(filters, 'companyId', 'branchId', branchRows.value, auth, companyRows.value);
    if (branchReset) return;
    if (referencesLoaded.value) {
      loadData();
    }
  }
);

watch(
  () => filters.branchId,
  () => {
    if (referencesLoaded.value) {
      loadData();
    }
  }
);

function numberLabel(value) {
  return Number(value || 0).toLocaleString('id-ID');
}

function normalizeText(value) {
  return String(value || '').trim().toLowerCase();
}

function textValue(value) {
  return String(value || '').trim();
}

function uniqueValues(values) {
  return [...new Set(values.map((value) => textValue(value)).filter(Boolean))];
}

function numericValue(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function rowQtyPcs(row = {}) {
  return numericValue(row.qty_pcs ?? row.qty_pieces ?? row.qty ?? row.pcs ?? row.quantity_pc);
}

function rowQtyKarton(row = {}) {
  return numericValue(row.qty_karton ?? row.qty_ctn ?? row.qty_ct ?? row.karton ?? row.quantity_ct);
}

function rowHasStock(row = {}) {
  return rowQtyPcs(row) > 0 || rowQtyKarton(row) > 0;
}

function rowProductCode(row = {}) {
  return textValue(row.kode_barang || row.kode_sku || row.product_code || row.productCode || row.KodeBarang || row.KodeStok);
}

function rowProductName(row = {}) {
  return textValue(row.nama_barang || row.nama_produk || row.product_name || row.productName || row.NamaBarang);
}

function rowBatch(row = {}) {
  return textValue(row.batch_number || row.batch_no || row.batch || row.Batch);
}

function positiveUomFactor(...values) {
  const factor = values
    .map((value) => numericValue(value))
    .find((value) => value > 0);
  return factor || 0;
}

function normalizedUomLevels(row = {}) {
  const baseName = textValue(row.uom1_nama || row.uom1_name || row.uom_name || 'PCS') || 'PCS';
  const baseFactor = positiveUomFactor(row.uom1_factor, 1) || 1;
  const levels = [
    { level: 3, name: textValue(row.uom3_nama || row.uom3_name), factor: positiveUomFactor(row.uom3_factor) },
    { level: 2, name: textValue(row.uom2_nama || row.uom2_name), factor: positiveUomFactor(row.uom2_factor) },
    { level: 1, name: baseName, factor: baseFactor }
  ].filter((item) => item.name && item.factor > 0);

  if (!levels.some((item) => item.factor > baseFactor)) {
    const fallbackFactor = positiveUomFactor(
      row.per_unit,
      row.isi_per_karton,
      row.isiperkarton,
      row.karton_to_pcs,
      row.uom_karton_ratio
    );
    if (fallbackFactor > baseFactor) {
      levels.unshift({ level: 3, name: 'Karton', factor: fallbackFactor });
    }
  }

  const seenFactors = new Set();
  return levels
    .sort((left, right) => right.factor - left.factor || right.level - left.level)
    .filter((item) => {
      if (seenFactors.has(item.factor)) return false;
      seenFactors.add(item.factor);
      return true;
    });
}

function formatUomQuantity(value, row = {}) {
  let remaining = Math.max(Math.trunc(numericValue(value)), 0);
  const levels = normalizedUomLevels(row);
  const parts = [];

  levels.forEach((uom, index) => {
    const qty = index === levels.length - 1 ? remaining : Math.floor(remaining / uom.factor);
    if (qty > 0 || (!parts.length && index === levels.length - 1)) {
      parts.push(`${numberLabel(qty)} ${uom.name}`);
    }
    remaining -= qty * uom.factor;
  });

  return parts.join(' + ') || `${numberLabel(value)} ${levels.at(-1)?.name || 'PCS'}`;
}

function uomConversionLabel(row = {}) {
  const levels = normalizedUomLevels(row);
  const base = levels.at(-1) || { name: 'PCS', factor: 1 };
  return levels
    .filter((item) => item.factor > base.factor)
    .map((item) => `1 ${item.name} = ${numberLabel(item.factor / base.factor)} ${base.name}`)
    .join(' | ');
}

function isAisleRack(row = {}) {
  return normalizeText(row.type).includes('lorong');
}

function aggregateSceneRacks(rows) {
  const grouped = new Map();

  rows.forEach((row) => {
    const key = sceneRackKey(row);
    const item = grouped.get(key) || {
      ...row,
      id: key,
      codes: [],
      sourceRows: [],
      placements: [],
      productNames: [],
      qtyKarton: 0,
      qtyPcs: 0,
      levelSet: new Set(),
      activeCount: 0
    };

    item.codes.push(row.code);
    item.sourceRows.push(row);
    item.placements.push(...(row.placements || []));
    item.productNames.push(...(row.productNames || []));
    item.qtyKarton += Number(row.qtyKarton || 0);
    item.qtyPcs += Number(row.qtyPcs || 0);
    item.levelSet.add(Number(row.parsed?.level || 0));
    if (row.active) item.activeCount += 1;
    grouped.set(key, item);
  });

  return [...grouped.values()].map((item) => {
    const productNames = uniqueValues(item.productNames);
    const active = item.activeCount > 0;
    const status = !active
      ? 'Nonaktif'
      : item.placements.some(rowHasStock) || item.qtyPcs > 0 || item.qtyKarton > 0
        ? 'Isi'
        : 'Kosong';

    return {
      ...item,
      active,
      status,
      productNames,
      productCount: productNames.length,
      slotCount: item.sourceRows.length,
      levelCount: item.levelSet.size,
      heightScale: Math.min(2.2, Math.max(0.9, 0.86 + item.levelSet.size * 0.18)),
      searchText: uniqueValues([
        item.searchText,
        ...item.codes,
        ...productNames
      ]).join(' ').toLowerCase(),
      levelSet: undefined
    };
  });
}

function sceneRackKey(row) {
  const parsed = row?.parsed || {};
  return [
    parsed.gudang || 1,
    parsed.rak || 0,
    parsed.kolom || 0,
    parsed.nomor || 0
  ].join('|');
}

function rackCode(row = {}) {
  return textValue(
    row.kode_rak
    || row.kodeRak
    || row.rak_code
    || row.location_code
    || row.kode_lokasi
    || row.kode
  ).toUpperCase().replace(/\s+/g, '');
}

function normalizeActive(value) {
  if (value === undefined || value === null || value === '') return true;
  const normalized = normalizeText(value);
  return !['false', '0', 'no', 'n', 'nonaktif', 'inactive'].includes(normalized);
}

function parseRackPosition(row = {}, code = '', index = 0) {
  const match = String(code || '').match(/G(\d+)[RL](\d+)L(\d+)K(\d+)N(\d+)/i);

  return {
    gudang: Number(row.gudang ?? row.gudang_id ?? match?.[1] ?? 1) || 1,
    rak: Number(row.rak ?? row.no_rak ?? match?.[2] ?? Math.floor(index / 80) + 1) || 1,
    level: Number(row.level ?? match?.[3] ?? (index % 5)) || 0,
    kolom: Number(row.kolom ?? row.column ?? match?.[4] ?? (index % 24) + 1) || 1,
    nomor: Number(row.nomor_urut ?? row.nomor ?? row.no ?? match?.[5] ?? (index % 2) + 1) || 1
  };
}

function createFallbackRackRows() {
  const rows = [];

  for (let rak = 1; rak <= 22; rak += 1) {
    const maxKolom = fallbackMaxKolomForRack(rak);
    for (let kolom = 1; kolom <= maxKolom; kolom += 1) {
      for (let level = 1; level <= 4; level += 1) {
        for (let nomor = 1; nomor <= 2; nomor += 1) {
          const occupied = (rak + kolom + level + nomor) % 4 === 0;
          rows.push({
            kode_rak: `G1R${String(rak).padStart(2, '0')}L${String(level).padStart(2, '0')}K${String(kolom).padStart(2, '0')}N${String(nomor).padStart(2, '0')}`,
            type_rak: rak >= 12 ? 'Titipan' : 'Tetap',
            status_rak: occupied ? 'Isi' : 'Kosong',
            active: true
          });
        }
      }
    }
  }

  return rows;
}

function fallbackMaxKolomForRack(rak) {
  if (rak === 1) return 26;
  if (rak === 22) return 20;
  if (rak % 2 === 0) return rak <= 10 ? 28 : 16;
  return 20;
}

function payloadRows(response) {
  const unwrapped = unwrapResponse(response);
  if (Array.isArray(unwrapped)) return unwrapped;
  if (Array.isArray(unwrapped?.items)) return unwrapped.items;
  return normalizeList(unwrapped);
}

function recordKey(row = {}, index = 0) {
  const id = textValue(row.id || row.source_id || row.uuid);
  if (id) return `id:${id}`;
  return [
    rackCode(row),
    rowProductCode(row),
    rowBatch(row),
    textValue(row.expired_date || row.expiry_date || row.expired),
    textValue(row.updated_at),
    index
  ].join('|');
}

function mergeUniqueRows(currentRows, nextRows) {
  const keys = new Set(currentRows.map((row, index) => recordKey(row, index)));
  const addedRows = [];

  nextRows.forEach((row, index) => {
    const key = recordKey(row, index);
    if (keys.has(key)) return;
    keys.add(key);
    addedRows.push(row);
  });

  return addedRows;
}

async function fetchAllRackRows(params, signal) {
  const rows = [];
  let offset = 0;

  while (true) {
    const response = await withRequestTimeout(
      getWmsRacks(
        { ...params, limit: WMS_PAGE_SIZE, offset },
        { signal, timeout: RACK_REQUEST_TIMEOUT_MS }
      ),
      RACK_REQUEST_TIMEOUT_MS,
      'Master rak WMS belum merespons.'
    );
    const pageRows = payloadRows(response);
    const addedRows = mergeUniqueRows(rows, pageRows);
    rows.push(...addedRows);

    const metadata = response?.data;
    const responseOffset = Number(metadata?.offset);
    const total = Number(metadata?.total);
    const supportsOffset = Number.isFinite(responseOffset) && responseOffset === offset;

    if (!supportsOffset || !addedRows.length || pageRows.length < WMS_PAGE_SIZE) break;
    if (Number.isFinite(total) && rows.length >= total) break;
    offset += pageRows.length;
  }

  return rows;
}

async function fetchAllPlacementRows(params, signal) {
  const rows = [];
  let offset = 0;

  while (true) {
    const response = await withRequestTimeout(
      getWmsPlacements(
        { ...params, limit: WMS_PAGE_SIZE, offset },
        { signal, timeout: PLACEMENT_REQUEST_TIMEOUT_MS }
      ),
      PLACEMENT_REQUEST_TIMEOUT_MS,
      'Penempatan rak WMS belum merespons.'
    );
    const pageRows = payloadRows(response);
    const addedRows = mergeUniqueRows(rows, pageRows);
    rows.push(...addedRows);

    if (!addedRows.length || pageRows.length < WMS_PAGE_SIZE) break;
    offset += pageRows.length;
  }

  return rows;
}

function activeBranchId() {
  return String(auth.user?.cabang?.id || auth.user?.cabang_id || auth.user?.id_cabang || '');
}

function activeCompanyId(branchId = '') {
  return String(
    auth.user?.perusahaan?.id ||
    auth.user?.id_perusahaan ||
    branchRows.value.find((item) => String(item?.id) === String(branchId))?.id_perusahaan ||
    ''
  );
}

function buildDataParams() {
  return {
    id_perusahaan: filters.companyId || undefined,
    id_cabang: filters.branchId || undefined
  };
}

async function loadReferences() {
  const [companyResult, branchResult] = await Promise.allSettled([
    getCompanies(),
    getBranches()
  ]);

  if (companyResult.status === 'fulfilled') {
    companyRows.value = normalizeList(unwrapResponse(companyResult.value));
  }

  if (branchResult.status === 'fulfilled') {
    branchRows.value = normalizeList(unwrapResponse(branchResult.value));
  }

  const branchId = activeBranchId();
  if (!filters.branchId && branchId) {
    filters.branchId = branchId;
  }
  if (!filters.companyId) {
    filters.companyId = activeCompanyId(filters.branchId);
  }
}

async function loadData() {
  const requestId = ++loadRequestId;
  activeLoadController?.abort();
  const controller = new AbortController();
  activeLoadController = controller;
  loading.value = true;
  errorMessage.value = '';
  const params = buildDataParams();

  const failures = [];
  const [racksResult, placementsResult] = await Promise.allSettled([
    fetchAllRackRows(params, controller.signal),
    fetchAllPlacementRows(params, controller.signal)
  ]);

  if (requestId !== loadRequestId) return;

  if (racksResult.status === 'fulfilled') {
    rackRows.value = racksResult.value;
  } else {
    rackRows.value = [];
    failures.push(formatDataError(racksResult.reason, 'Master rak WMS belum bisa dimuat.'));
  }

  if (placementsResult.status === 'fulfilled') {
    placementRows.value = placementsResult.value;
  } else {
    placementRows.value = [];
    failures.push(formatDataError(placementsResult.reason, 'Penempatan rak WMS belum bisa dimuat.'));
  }

  const firstWarehouse = warehouseOptions.value[0]?.value || '';
  if (!warehouseOptions.value.some((option) => option.value === filters.warehouse)) {
    filters.warehouse = firstWarehouse;
  }
  selectedRackCode.value = '';
  errorMessage.value = uniqueValues(failures).join(' ');
  loading.value = false;
  if (activeLoadController === controller) {
    activeLoadController = undefined;
  }
}

function withRequestTimeout(promise, timeoutMs, message) {
  let timeoutId;
  const timeout = new Promise((_, reject) => {
    timeoutId = window.setTimeout(() => reject(new Error(message)), timeoutMs);
  });

  return Promise.race([promise, timeout]).finally(() => window.clearTimeout(timeoutId));
}

function formatDataError(error, fallback) {
  const message = normalizeError(error, fallback);
  if (/timeout|exceeded|merespons/i.test(message)) {
    return fallback;
  }
  return message;
}

function initializeScene() {
  if (!sceneHost.value || renderer) return;

  scene = new THREE.Scene();
  scene.background = new THREE.Color('#07101a');
  scene.fog = new THREE.Fog('#07101a', 28, 105);

  camera = new THREE.PerspectiveCamera(45, 1, 0.1, 220);
  camera.position.set(22, 18, 28);

  renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.domElement.className = 'wms-3d-canvas';
  sceneHost.value.appendChild(renderer.domElement);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minDistance = 10;
  controls.maxDistance = 90;
  controls.maxPolarAngle = Math.PI * 0.47;
  controls.target.set(0, 2, 0);

  renderer.domElement.addEventListener('pointerdown', handlePointerDown);
  window.addEventListener('resize', resizeScene);
  resizeObserver = new ResizeObserver(resizeScene);
  resizeObserver.observe(sceneHost.value);

  buildStaticScene();
  rebuildDynamicScene();
  resizeScene();
  animateScene();
}

function buildStaticScene() {
  staticGroup = new THREE.Group();
  scene.add(staticGroup);

  const ambient = new THREE.HemisphereLight('#dbeafe', '#0f172a', 1.1);
  scene.add(ambient);

  const keyLight = new THREE.DirectionalLight('#ffffff', 2.3);
  keyLight.position.set(18, 26, 12);
  keyLight.castShadow = true;
  keyLight.shadow.mapSize.width = 2048;
  keyLight.shadow.mapSize.height = 2048;
  staticGroup.add(keyLight);

  const fillLight = new THREE.DirectionalLight('#38bdf8', 0.75);
  fillLight.position.set(-18, 15, -10);
  staticGroup.add(fillLight);

  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(86, 54),
    new THREE.MeshStandardMaterial({ color: '#27313c', roughness: 0.82, metalness: 0.05 })
  );
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  staticGroup.add(floor);

  const grid = new THREE.GridHelper(86, 43, '#f59e0b', '#44505f');
  grid.material.opacity = 0.24;
  grid.material.transparent = true;
  staticGroup.add(grid);

  createWarehouseWall(0, 5, -27, 86, 10, 0.35);
  createWarehouseWall(-43, 5, 0, 0.35, 10, 54);
  createWarehouseWall(43, 5, 0, 0.35, 10, 54);

  createLayoutPanel(1, 7, 32, 62, '#0f766e', 'GUDANG 01 (FOOD)');
  createLayoutPanel(35, 15, 66, 62, '#7c3aed', 'GUDANG 02 (NON FOOD)');
  createLayoutPanel(33, 1, 34, 62, '#f59e0b', 'LORONG UTAMA');
  createLayoutPanel(1, 37, 32, 40, '#f59e0b', 'LORONG FOOD');
  createLayoutPanel(35, 37, 66, 40, '#f59e0b', 'LORONG NON FOOD');

  createZone(-31, -22, 14, 4, '#0ea5e9', 'RECEIVING');
  createZone(28, -22, 16, 4, '#f59e0b', 'SHIPPING');
  createZone(-37, 19, 10, 6, '#334155', 'OFFICE');
  createDenahLabels();
}

function createWarehouseWall(x, y, z, width, height, depth) {
  const wall = new THREE.Mesh(
    new THREE.BoxGeometry(width, height, depth),
    new THREE.MeshStandardMaterial({ color: '#475569', roughness: 0.78 })
  );
  wall.position.set(x, y, z);
  wall.receiveShadow = true;
  wall.castShadow = true;
  staticGroup.add(wall);
}

function createZone(x, z, width, depth, color, label) {
  const zone = new THREE.Mesh(
    new THREE.BoxGeometry(width, 0.06, depth),
    new THREE.MeshStandardMaterial({ color, transparent: true, opacity: 0.58, roughness: 0.7 })
  );
  zone.position.set(x, 0.04, z);
  zone.receiveShadow = true;
  staticGroup.add(zone);

  const sprite = createTextSprite(label, '#e0f2fe', 'rgba(2, 8, 23, 0.88)');
  sprite.position.set(x, 0.2, z);
  sprite.scale.set(4.8, 1.25, 1);
  staticGroup.add(sprite);
}

function gridToWorld(col, row) {
  return {
    x: (Number(col) - EXCEL_LAYOUT.centerCol) * EXCEL_LAYOUT.cellX,
    z: (Number(row) - EXCEL_LAYOUT.centerRow) * EXCEL_LAYOUT.cellZ
  };
}

function createLayoutPanel(col1, row1, col2, row2, color, label) {
  const start = gridToWorld(col1, row1);
  const end = gridToWorld(col2, row2);
  const width = Math.max(0.8, Math.abs(end.x - start.x) + EXCEL_LAYOUT.cellX);
  const depth = Math.max(0.8, Math.abs(end.z - start.z) + EXCEL_LAYOUT.cellZ);
  const centerX = (start.x + end.x) / 2;
  const centerZ = (start.z + end.z) / 2;
  const panel = new THREE.Mesh(
    new THREE.BoxGeometry(width, 0.045, depth),
    new THREE.MeshStandardMaterial({ color, transparent: true, opacity: 0.16, roughness: 0.86 })
  );
  panel.position.set(centerX, 0.065, centerZ);
  panel.receiveShadow = true;
  staticGroup.add(panel);

  if (label) {
    const sprite = createTextSprite(label, '#f8fafc', 'rgba(15, 23, 42, 0.72)');
    const labelPoint = gridToWorld(col1 + 1.2, row1 + 0.8);
    sprite.position.set(labelPoint.x, 0.32, labelPoint.z);
    sprite.scale.set(5.8, 1.05, 1);
    staticGroup.add(sprite);
  }
}

function createDenahLabels() {
  denahRackLabels.forEach((item) => {
    const point = gridToWorld(item.col, item.row);
    const sprite = createTextSprite(item.label, '#e0f2fe', item.area === 'food' ? 'rgba(15, 118, 110, 0.86)' : 'rgba(91, 33, 182, 0.86)');
    sprite.position.set(point.x, 2.1, point.z);
    sprite.scale.set(2.4, 0.62, 1);
    staticGroup.add(sprite);
  });
}

function rebuildDynamicScene() {
  if (!scene) return;

  if (dynamicGroup) {
    scene.remove(dynamicGroup);
    disposeObject(dynamicGroup);
  }

  dynamicGroup = new THREE.Group();
  scene.add(dynamicGroup);
  rackInstanceRows = buildRackLayout(sceneRacks.value);

  buildRackInstances();
  buildPalletInstances();
  buildSelectedOutline();
  frameCameraToRacks();
}

function buildRackLayout(rows) {
  const sortedRows = [...rows].sort((a, b) =>
    a.parsed.rak - b.parsed.rak
    || a.parsed.kolom - b.parsed.kolom
    || a.parsed.nomor - b.parsed.nomor
    || a.parsed.level - b.parsed.level
  );

  return sortedRows.map((row, index) => {
    const denah = denahPositionForRack(row, index);
    const y = 0.34 + Math.max(0, Math.min(Number(row.parsed.level || 0), 8)) * 0.08;

    return {
      ...row,
      instanceIndex: index,
      denah,
      position: new THREE.Vector3(denah.x, y, denah.z),
      rotationY: denah.rotationY,
      scale: new THREE.Vector3(denah.scaleX, row.heightScale || 1, denah.scaleZ)
    };
  });
}

function denahPositionForRack(row, index) {
  const rack = Math.max(1, Number(row.parsed.rak || 1));
  const kolom = Math.max(1, Number(row.parsed.kolom || 1));
  const nomor = Math.max(1, Number(row.parsed.nomor || 1));

  if (rack === 1) {
    return verticalWallRackPosition({
      rack,
      kolom,
      nomor,
      colLeft: 1.05,
      colRight: 1.95,
      rowStart: 9,
      maxKolom: 26,
      area: 'FOOD',
      label: 'RAK 01'
    });
  }

  if (rack === 22) {
    return verticalWallRackPosition({
      rack,
      kolom,
      nomor,
      colLeft: 64.95,
      colRight: 65.85,
      rowStart: 21,
      maxKolom: 20,
      area: 'NON FOOD',
      label: 'RAK 22'
    });
  }

  const block = rackBlockColumns.find((item) => item.racks.includes(rack));
  if (block) {
    const isTopRack = rack % 2 === 0;
    const isFood = rack <= 11;
    const maxKolom = isTopRack ? (isFood ? 28 : 16) : 20;
    const rowStart = isTopRack ? (isFood ? 9 : 21) : 41;
    const row = rowForRackColumn(kolom, maxKolom, rowStart);
    const splitAt = Math.ceil(maxKolom / 2);
    const side = kolom > splitAt ? 'left' : 'right';
    const sideCol = side === 'left' ? block.colLeft : block.colRight;
    const depthOffset = nomorOffset(nomor, side === 'left' ? -1 : 1);
    const point = gridToWorld(sideCol + depthOffset, row);

    return {
      x: point.x,
      z: point.z,
      rotationY: 0,
      scaleX: 0.92,
      scaleZ: 0.92,
      area: isFood ? 'FOOD' : 'NON FOOD',
      side,
      label: `RAK ${String(rack).padStart(2, '0')}`
    };
  }

  return overflowRackPosition(row, index);
}

function verticalWallRackPosition({ rack, kolom, nomor, colLeft, colRight, rowStart, maxKolom, area, label }) {
  const safeKolom = Math.max(1, Math.min(kolom, maxKolom));
  const row = rowStart + (safeKolom - 1) * 2;
  const col = nomor % 2 === 0 ? colRight : colLeft;
  const point = gridToWorld(col, row);

  return {
    x: point.x,
    z: point.z,
    rotationY: Math.PI / 2,
    scaleX: 0.92,
    scaleZ: 0.92,
    area,
    side: nomor % 2 === 0 ? 'kanan' : 'kiri',
    label
  };
}

function rowForRackColumn(kolom, maxKolom, rowStart) {
  const safeKolom = Math.max(1, Math.min(Number(kolom || 1), maxKolom));
  const splitAt = Math.ceil(maxKolom / 2);
  const rowIndex = safeKolom <= splitAt
    ? safeKolom - 1
    : maxKolom - safeKolom;

  return rowStart + Math.max(0, rowIndex) * 2;
}

function nomorOffset(nomor, direction) {
  const depthIndex = Math.max(0, Math.ceil(Number(nomor || 1) / 2) - 1);
  const oddEvenOffset = Number(nomor || 1) % 2 === 0 ? 0.16 : -0.16;
  return direction * (depthIndex * 0.18 + oddEvenOffset);
}

function overflowRackPosition(row, index) {
  const column = index % 16;
  const band = Math.floor(index / 16);
  const point = gridToWorld(4 + column * 3.6, 65 + band * 2.2);

  return {
    x: point.x,
    z: point.z,
    rotationY: 0,
    scaleX: 0.92,
    scaleZ: 0.92,
    area: 'LAINNYA',
    side: '-',
    label: `RAK ${String(row.parsed.rak || 0).padStart(2, '0')}`
  };
}

function buildRackInstances() {
  const count = rackInstanceRows.length;
  const geometry = new THREE.BoxGeometry(EXCEL_LAYOUT.rackWidth, EXCEL_LAYOUT.rackHeight, EXCEL_LAYOUT.rackDepth);
  const material = new THREE.MeshStandardMaterial({
    color: '#60a5fa',
    roughness: 0.52,
    metalness: 0.12,
    vertexColors: true
  });

  rackMesh = new THREE.InstancedMesh(geometry, material, count);
  rackMesh.castShadow = true;
  rackMesh.receiveShadow = true;
  rackMesh.userData.kind = 'rack';

  rackInstanceRows.forEach((row, index) => {
    tempPosition.copy(row.position);
    tempQuaternion.setFromAxisAngle(new THREE.Vector3(0, 1, 0), row.rotationY || 0);
    tempScale.set(row.scale?.x || 1, row.scale?.y || (row.status === 'Isi' ? 1.12 : 0.9), row.scale?.z || 1);
    tempMatrix.compose(tempPosition, tempQuaternion, tempScale);
    rackMesh.setMatrixAt(index, tempMatrix);
    rackMesh.setColorAt(index, rackColor(row));
  });

  rackMesh.instanceMatrix.needsUpdate = true;
  if (rackMesh.instanceColor) rackMesh.instanceColor.needsUpdate = true;
  dynamicGroup.add(rackMesh);
}

function buildPalletInstances() {
  const occupiedRows = rackInstanceRows.filter((row) => row.status === 'Isi');
  const geometry = new THREE.BoxGeometry(0.72, 0.18, 0.44);
  const material = new THREE.MeshStandardMaterial({
    color: '#d6a15f',
    roughness: 0.72,
    metalness: 0.03,
    vertexColors: true
  });

  palletMesh = new THREE.InstancedMesh(geometry, material, occupiedRows.length);
  palletMesh.castShadow = true;
  palletMesh.receiveShadow = true;

  occupiedRows.forEach((row, index) => {
    tempPosition.copy(row.position);
    tempPosition.y += 0.27;
    tempQuaternion.setFromAxisAngle(new THREE.Vector3(0, 1, 0), row.rotationY || 0);
    tempScale.set(1, 1 + Math.min(row.productCount, 3) * 0.12, 1);
    tempMatrix.compose(tempPosition, tempQuaternion, tempScale);
    palletMesh.setMatrixAt(index, tempMatrix);
    palletMesh.setColorAt(index, new THREE.Color(row.type === 'Titipan' ? '#fcd34d' : '#c0843f'));
  });

  palletMesh.instanceMatrix.needsUpdate = true;
  if (palletMesh.instanceColor) palletMesh.instanceColor.needsUpdate = true;
  dynamicGroup.add(palletMesh);
}

function buildAisleLabels() {
  const firstByAisle = new Map();

  rackInstanceRows.forEach((row) => {
    if (!firstByAisle.has(row.parsed.rak)) {
      firstByAisle.set(row.parsed.rak, row);
    }
  });

  [...firstByAisle.entries()]
    .sort(([a], [b]) => Number(a) - Number(b))
    .slice(0, 18)
    .forEach(([aisle, row]) => {
      const sprite = createTextSprite(`R${String(aisle).padStart(2, '0')}`, '#eff6ff', 'rgba(14, 116, 144, 0.86)');
      sprite.position.set(row.position.x, 2.2, row.position.z - 1.5);
      sprite.scale.set(2.1, 0.72, 1);
      dynamicGroup.add(sprite);
    });
}

function buildSelectedOutline() {
  selectedOutline = new THREE.Mesh(
    new THREE.BoxGeometry(1.18, 0.44, 0.78),
    new THREE.MeshBasicMaterial({ color: '#f8fafc', wireframe: true, transparent: true, opacity: 0.95 })
  );
  selectedOutline.visible = false;
  dynamicGroup.add(selectedOutline);
  updateSelectedOutline();
}

function rackColor(row) {
  if (!row.active || row.status === 'Nonaktif') return new THREE.Color('#64748b');
  if (row.status === 'Isi' && normalizeText(row.type).includes('titipan')) return new THREE.Color('#eab308');
  if (row.status === 'Isi') return new THREE.Color('#f97316');
  if (normalizeText(row.type).includes('titipan')) return new THREE.Color('#0f766e');
  if (normalizeText(row.type).includes('karantina')) return new THREE.Color('#be123c');
  if (normalizeText(row.type).includes('transit')) return new THREE.Color('#7c3aed');
  return new THREE.Color('#2563eb');
}

function createTextSprite(text, color, background) {
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 160;
  const context = canvas.getContext('2d');

  context.fillStyle = background;
  roundRect(context, 18, 18, 476, 124, 24);
  context.fill();
  context.strokeStyle = 'rgba(226, 232, 240, 0.65)';
  context.lineWidth = 4;
  context.stroke();
  context.fillStyle = color;
  context.font = '700 54px Arial';
  context.textAlign = 'center';
  context.textBaseline = 'middle';
  context.fillText(text, 256, 82);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const material = new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false });
  return new THREE.Sprite(material);
}

function roundRect(context, x, y, width, height, radius) {
  context.beginPath();
  context.moveTo(x + radius, y);
  context.lineTo(x + width - radius, y);
  context.quadraticCurveTo(x + width, y, x + width, y + radius);
  context.lineTo(x + width, y + height - radius);
  context.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
  context.lineTo(x + radius, y + height);
  context.quadraticCurveTo(x, y + height, x, y + height - radius);
  context.lineTo(x, y + radius);
  context.quadraticCurveTo(x, y, x + radius, y);
  context.closePath();
}

function frameCameraToRacks() {
  if (!rackInstanceRows.length || !dynamicGroup || !camera || !controls) return;

  const box = new THREE.Box3().setFromObject(dynamicGroup);
  const size = new THREE.Vector3();
  const center = new THREE.Vector3();
  box.getSize(size);
  box.getCenter(center);

  const maxDim = Math.max(size.x, size.z, 22);
  controls.target.copy(center);
  camera.position.set(center.x + maxDim * 0.58, Math.max(9, maxDim * 0.36), center.z + maxDim * 0.72);
  camera.near = 0.1;
  camera.far = Math.max(180, maxDim * 5);
  camera.updateProjectionMatrix();
  controls.update();
}

function updateSelectedOutline() {
  if (!selectedOutline) return;

  const row = rackInstanceRows.find((item) => item.code === selectedRackCode.value);
  if (!row) {
    selectedOutline.visible = false;
    return;
  }

  selectedOutline.position.copy(row.position);
  selectedOutline.rotation.y = row.rotationY || 0;
  selectedOutline.scale.set(row.scale?.x || 1, 1, row.scale?.z || 1);
  selectedOutline.visible = true;
}

function handlePointerDown(event) {
  if (!renderer || !camera || !rackMesh) return;

  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObject(rackMesh);
  const hit = hits.find((item) => item.instanceId !== undefined);
  if (!hit) return;

  const row = rackInstanceRows[hit.instanceId];
  if (row) {
    selectedRackCode.value = row.code;
  }
}

function resizeScene() {
  if (!sceneHost.value || !renderer || !camera) return;

  const { clientWidth, clientHeight } = sceneHost.value;
  if (!clientWidth || !clientHeight) return;

  camera.aspect = clientWidth / clientHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(clientWidth, clientHeight, false);
}

function animateScene() {
  if (!renderer || !scene || !camera) return;

  controls?.update();
  renderer.render(scene, camera);
  animationFrame = window.requestAnimationFrame(animateScene);
}

function disposeObject(object) {
  object.traverse((child) => {
    if (child.geometry) child.geometry.dispose();
    const materials = Array.isArray(child.material) ? child.material : [child.material].filter(Boolean);
    materials.forEach((material) => {
      if (material.map) material.map.dispose();
      material.dispose();
    });
  });
}

function teardownScene() {
  if (animationFrame) window.cancelAnimationFrame(animationFrame);
  window.removeEventListener('resize', resizeScene);
  resizeObserver?.disconnect();

  if (renderer?.domElement) {
    renderer.domElement.removeEventListener('pointerdown', handlePointerDown);
    renderer.domElement.remove();
  }

  if (scene) disposeObject(scene);
  controls?.dispose();
  renderer?.dispose();
  scene = null;
  camera = null;
  renderer = null;
  controls = null;
  dynamicGroup = null;
  staticGroup = null;
  rackMesh = null;
  palletMesh = null;
  selectedOutline = null;
  rackInstanceRows = [];
}

onMounted(async () => {
  await nextTick();
  initializeScene();
  await loadReferences();
  await loadData();
  referencesLoaded.value = true;
});

onBeforeUnmount(() => {
  loadRequestId += 1;
  activeLoadController?.abort();
  teardownScene();
});
</script>

<template>
  <div class="space-y-5">
    <PageHeader
      title="Rak 3D WMS"
      description="Visual lokasi rak, status isi, rak titipan, rak tetap, dan alur perpindahan palet."
    >
      <div class="flex flex-wrap gap-2">
        <button
          type="button"
          class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900"
          :disabled="loading"
          @click="loadData"
        >
          {{ loading ? 'Memuat...' : 'Refresh' }}
        </button>
      </div>
    </PageHeader>

    <section v-if="errorMessage" class="rounded-2xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm font-semibold text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-100">
      {{ errorMessage }} Tampilan memakai layout simulasi sampai data API tersedia.
    </section>

    <section class="wms3d-stage">
      <div class="wms3d-toolbar">
        <label class="wms3d-field">
          <span>Perusahaan</span>
          <select v-model="filters.companyId">
            <option v-for="option in companyOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </label>

        <label class="wms3d-field">
          <span>Cabang</span>
          <select v-model="filters.branchId" :disabled="!filters.companyId">
            <option v-for="option in branchOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </label>

        <label class="wms3d-field">
          <span>Gudang</span>
          <select v-model="filters.warehouse" :disabled="!warehouseOptions.length">
            <option v-for="option in warehouseOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </label>

        <label class="wms3d-field wms3d-field-wide">
          <span>Cari Rak / Produk</span>
          <input v-model="filters.search" type="search" placeholder="Kode rak, produk, batch" />
        </label>

        <label class="wms3d-field">
          <span>Tipe Rak</span>
          <select v-model="filters.type">
            <option v-for="option in rackTypeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </label>

        <label class="wms3d-field">
          <span>Status</span>
          <select v-model="filters.status">
            <option v-for="option in rackStatusOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </label>

        <label class="wms3d-field">
          <span>Aktif</span>
          <select v-model="filters.active">
            <option v-for="option in rackActiveOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </label>
      </div>

      <div class="wms3d-summary">
        <article v-for="card in summaryCards" :key="card.label" class="wms3d-summary-card" :class="`tone-${card.tone}`">
          <span>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
        </article>
      </div>

      <div ref="sceneHost" class="wms3d-scene">
        <div v-if="loading" class="wms3d-loading">Memuat data rak...</div>
        <div class="wms3d-layout-badge">Layout Denah GUDANG.xlsx</div>
        <div v-if="usingFallbackLayout" class="wms3d-badge">Layout simulasi</div>
      </div>

      <aside class="wms3d-detail">
        <div class="wms3d-detail-header">
          <span>Detail Rak</span>
          <strong>{{ selectedRack?.code || '-' }}</strong>
        </div>

        <dl v-if="selectedRack" class="wms3d-detail-grid">
          <div>
            <dt>Tipe</dt>
            <dd>{{ selectedRack.type || '-' }}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>{{ selectedRack.status || '-' }}</dd>
          </div>
          <div>
            <dt>Total PCS</dt>
            <dd>{{ numberLabel(selectedRack.qtyPcs) }} PCS</dd>
          </div>
          <div>
            <dt>Produk</dt>
            <dd>{{ numberLabel(selectedRack.productCount) }}</dd>
          </div>
          <div>
            <dt>Area</dt>
            <dd>{{ selectedRack.denah?.area || '-' }}</dd>
          </div>
          <div>
            <dt>Blok Denah</dt>
            <dd>{{ selectedRack.denah?.label || '-' }}</dd>
          </div>
          <div>
            <dt>Slot Data</dt>
            <dd>{{ numberLabel(selectedRack.slotCount || 1) }} baris</dd>
          </div>
          <div>
            <dt>Level</dt>
            <dd>{{ numberLabel(selectedRack.levelCount || 1) }}</dd>
          </div>
        </dl>

        <div class="wms3d-products">
          <p>Isi Rak</p>
          <ul v-if="selectedRackPlacementRows.length">
            <li v-for="row in selectedRackPlacementRows.slice(0, 5)" :key="recordKey(row)">
              <strong>{{ rowProductName(row) || rowProductCode(row) || '-' }}</strong>
              <small>
                {{ formatUomQuantity(rowQtyPcs(row), row) }}
                <template v-if="rowBatch(row)"> · Batch {{ rowBatch(row) }}</template>
              </small>
              <small v-if="uomConversionLabel(row)">{{ uomConversionLabel(row) }}</small>
            </li>
          </ul>
          <span v-else>Kosong</span>
        </div>

        <div class="wms3d-aisles">
          <p>Aisle Terbesar</p>
          <div v-for="item in aisleStats" :key="item.aisle" class="wms3d-aisle-row">
            <span>{{ item.aisle }}</span>
            <strong>{{ numberLabel(item.occupied) }}/{{ numberLabel(item.total) }}</strong>
          </div>
        </div>
      </aside>

      <div class="wms3d-legend">
        <span><i class="legend-fixed"></i> Tetap kosong</span>
        <span><i class="legend-fixed-filled"></i> Tetap isi</span>
        <span><i class="legend-temp"></i> Titipan</span>
        <span><i class="legend-off"></i> Nonaktif</span>
      </div>

      <div class="wms3d-flow">
        <article v-for="(step, index) in processSteps" :key="step.key">
          <span>{{ String(index + 1).padStart(2, '0') }}</span>
          <strong>{{ step.label }}</strong>
          <small>{{ step.meta }}</small>
        </article>
      </div>
    </section>
  </div>
</template>

<style scoped>
.wms3d-stage {
  position: relative;
  /*
   * This screen lives beside the persistent ERP sidebar, so viewport media
   * queries alone are not enough to tell us how much room the 3D stage has.
   * Let the stage react to its actual inline size instead.  It prevents the
   * filter controls, side detail, and process flow from competing for the
   * same space on laptop-sized desktops.
   */
  container-type: inline-size;
  min-height: min(780px, calc(100vh - 180px));
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background:
    radial-gradient(circle at 22% 15%, rgba(14, 165, 233, 0.17), transparent 32%),
    linear-gradient(135deg, #07101a 0%, #111827 48%, #020617 100%);
  box-shadow: 0 28px 80px rgba(2, 6, 23, 0.34);
}

.wms3d-scene {
  position: absolute;
  inset: 0;
}

:deep(.wms-3d-canvas) {
  display: block;
  width: 100%;
  height: 100%;
}

.wms3d-toolbar,
.wms3d-summary,
.wms3d-detail,
.wms3d-legend,
.wms3d-flow,
.wms3d-badge,
.wms3d-layout-badge,
.wms3d-loading {
  position: absolute;
  z-index: 2;
}

.wms3d-toolbar {
  left: 18px;
  right: 332px;
  top: 18px;
  display: grid;
  grid-template-columns: repeat(2, minmax(150px, 0.82fr)) minmax(200px, 1.3fr) repeat(4, minmax(110px, 0.56fr));
  gap: 10px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(2, 6, 23, 0.72);
  padding: 10px;
  backdrop-filter: blur(18px);
}

.wms3d-field {
  min-width: 0;
}

.wms3d-field span {
  display: block;
  margin-bottom: 6px;
  color: #93a4b8;
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
}

.wms3d-field input,
.wms3d-field select {
  width: 100%;
  min-height: 42px;
  border: 1px solid rgba(148, 163, 184, 0.26);
  background: rgba(15, 23, 42, 0.88);
  color: #f8fafc;
  font-size: 14px;
  outline: none;
  padding: 0 12px;
}

.wms3d-field select:disabled {
  opacity: 0.55;
}

.wms3d-field input::placeholder {
  color: #6b7b90;
}

.wms3d-summary {
  left: 18px;
  top: 114px;
  display: grid;
  grid-template-columns: repeat(3, minmax(110px, 1fr));
  gap: 8px;
  max-width: 520px;
}

.wms3d-summary-card {
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(15, 23, 42, 0.74);
  padding: 12px;
  backdrop-filter: blur(16px);
}

.wms3d-summary-card span,
.wms3d-detail dt,
.wms3d-products p,
.wms3d-aisles p {
  color: #96a6bb;
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
}

.wms3d-summary-card strong {
  display: block;
  margin-top: 6px;
  color: #f8fafc;
  font-size: 22px;
  line-height: 1;
}

.tone-blue { border-color: rgba(56, 189, 248, 0.36); }
.tone-amber { border-color: rgba(245, 158, 11, 0.42); }
.tone-emerald { border-color: rgba(16, 185, 129, 0.4); }
.tone-indigo { border-color: rgba(129, 140, 248, 0.4); }
.tone-rose { border-color: rgba(244, 63, 94, 0.38); }

.wms3d-detail {
  right: 18px;
  top: 18px;
  width: 296px;
  max-height: calc(100% - 150px);
  overflow: auto;
  border: 1px solid rgba(148, 163, 184, 0.2);
  background: rgba(2, 6, 23, 0.78);
  padding: 16px;
  color: #f8fafc;
  backdrop-filter: blur(18px);
}

.wms3d-detail-header {
  display: grid;
  gap: 7px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
  padding-bottom: 14px;
}

.wms3d-detail-header span {
  color: #c7d2fe;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}

.wms3d-detail-header strong {
  font-size: 22px;
  line-height: 1.15;
  overflow-wrap: anywhere;
}

.wms3d-detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.wms3d-detail-grid div {
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(15, 23, 42, 0.72);
  padding: 10px;
}

.wms3d-detail dd {
  margin-top: 5px;
  color: #f8fafc;
  font-size: 14px;
  font-weight: 800;
  overflow-wrap: anywhere;
}

.wms3d-products,
.wms3d-aisles {
  margin-top: 14px;
  border-top: 1px solid rgba(148, 163, 184, 0.18);
  padding-top: 14px;
}

.wms3d-products ul {
  margin-top: 9px;
  display: grid;
  gap: 8px;
}

.wms3d-products li,
.wms3d-products span {
  display: block;
  color: #e2e8f0;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.35;
}

.wms3d-products li {
  border-left: 2px solid rgba(56, 189, 248, 0.72);
  padding-left: 9px;
}

.wms3d-products li strong,
.wms3d-products li small {
  display: block;
}

.wms3d-products li small {
  margin-top: 2px;
  color: #9fb0c4;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.wms3d-aisle-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
  padding: 8px 0;
  color: #e2e8f0;
  font-size: 13px;
}

.wms3d-legend {
  bottom: 120px;
  left: 18px;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(2, 6, 23, 0.68);
  padding: 10px;
  backdrop-filter: blur(16px);
}

.wms3d-legend span {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: #e2e8f0;
  font-size: 12px;
  font-weight: 800;
}

.wms3d-legend i {
  display: block;
  width: 13px;
  height: 13px;
}

.legend-fixed { background: #2563eb; }
.legend-fixed-filled { background: #f97316; }
.legend-temp { background: #eab308; }
.legend-off { background: #64748b; }

.wms3d-flow {
  left: 50%;
  bottom: 18px;
  display: grid;
  width: min(1020px, calc(100% - 36px));
  grid-template-columns: repeat(7, minmax(0, 1fr));
  transform: translateX(-50%);
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(2, 6, 23, 0.76);
  backdrop-filter: blur(18px);
}

.wms3d-flow article {
  min-width: 0;
  border-right: 1px solid rgba(148, 163, 184, 0.14);
  padding: 14px;
}

.wms3d-flow article:last-child {
  border-right: 0;
}

.wms3d-flow span {
  color: #38bdf8;
  font-size: 11px;
  font-weight: 900;
}

.wms3d-flow strong {
  display: block;
  margin-top: 6px;
  color: #f8fafc;
  font-size: 13px;
  line-height: 1.2;
}

.wms3d-flow small {
  display: block;
  margin-top: 4px;
  color: #9ca3af;
  font-size: 11px;
  line-height: 1.25;
}

.wms3d-badge,
.wms3d-layout-badge,
.wms3d-loading {
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  border: 1px solid rgba(148, 163, 184, 0.24);
  background: rgba(2, 6, 23, 0.72);
  color: #f8fafc;
  font-weight: 800;
  padding: 12px 16px;
  backdrop-filter: blur(14px);
}

.wms3d-badge {
  left: 18px;
  top: auto;
  bottom: 74px;
  transform: none;
  color: #fde68a;
}

.wms3d-layout-badge {
  left: 18px;
  top: auto;
  bottom: 114px;
  transform: none;
  color: #bae6fd;
}

@container (max-width: 1320px) {
  .wms3d-stage {
    min-height: 980px;
  }

  .wms3d-toolbar {
    right: 18px;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .wms3d-summary {
    top: 258px;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .wms3d-detail {
    top: auto;
    bottom: 178px;
    width: min(360px, calc(100% - 36px));
    max-height: 300px;
  }
}

@container (max-width: 820px) {
  .wms3d-stage {
    min-height: 1248px;
    margin-inline: -12px;
  }

  .wms3d-toolbar {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .wms3d-field-wide {
    grid-column: 1 / -1;
  }

  .wms3d-summary {
    top: 400px;
    right: 18px;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    max-width: none;
  }

  .wms3d-detail {
    left: 18px;
    right: 18px;
    bottom: 228px;
    width: auto;
  }

  .wms3d-legend {
    bottom: 156px;
    right: 18px;
  }

  .wms3d-flow {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .wms3d-flow article {
    border-bottom: 1px solid rgba(148, 163, 184, 0.14);
  }
}
</style>
