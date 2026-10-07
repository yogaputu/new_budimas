<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import QRCode from 'qrcode';
import ShipmentPickingPanel from '../components/ShipmentPickingPanel.vue';
import ShipmentLoadingPanel from '../components/ShipmentLoadingPanel.vue';
import {
  completeWmsDelivery,
  confirmWmsChecker,
  confirmWmsTransfer,
  createWmsPrincipalGroup,
  createWmsPlacement,
  createWmsPallet,
  createWmsRack,
  deleteWmsPrincipalGroup,
  deleteWmsPlacement,
  deleteWmsPallet,
  deleteWmsRack,
  dropWmsManifestToQuarantine,
  finalizeWmsPicking,
  getWmsCheckerPending,
  getPickingIncidents,
  resolvePickingIncident,
  getWmsIncomingNoteDetails,
  getWmsInventory,
  getWmsInventoryBarcode,
  getWmsLowStockAlerts,
  getWmsNextPalletCode,
  getWmsNextRackCode,
  getWmsPallets,
  getWmsPickingDraftDetail,
  getWmsPlacements,
  getWmsPrincipalGroups,
  getWmsProductOptions,
  getWmsQuarantineOpen,
  getWmsRacks,
  getWmsReadyToLoad,
  getWmsTemporaryStocks,
  getWmsTransactions,
  processWmsIncomingPallet,
  processWmsLoading,
  processWmsQuarantineQc,
  scanWmsPickingRack,
  searchWmsManifest,
  updateWmsPrincipalGroup,
  updateWmsPlacement,
  updateWmsPallet,
  updateWmsRack
} from '@/api/wms';
import { getPrincipals, getProducts } from '@/api/master';
import { getStockReport } from '@/api/stockOpname';
import { placementBalances } from '../placementBalances';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const route = useRoute();
// The first page remains compact, while the remote WMS endpoint searches the
// complete product master (including products that have never moved in WMS).
const PRODUCT_OPTION_LIMIT = 100;
const PRODUCT_OPTION_FETCH_LIMIT = 1000;
const NOTE_PAGE_SIZE_OPTIONS = [10, 25, 50, 100];
const activeTab = ref('inventory');
const detailOpen = ref(false);
const rackModalOpen = ref(false);
const principalGroupModalOpen = ref(false);
const palletModalOpen = ref(false);
const placementModalOpen = ref(false);
const placementReport = ref([]);
const placementSummary = computed(() => placementBalances(placementReport.value, placementRows.value, {
  search:filters.placementSearch, rack:filters.placementRack, status:filters.placementStatus,
}));
const incomingPalletModalOpen = ref(false);
const transferConfirmOpen = ref(false);
const scannerOpen = ref(false);
const scannerTarget = ref('');
const scannerTitle = ref('');
const scannerVideo = ref(null);
const scannerStream = ref(null);
const scannerTimer = ref(null);
const detailTitle = ref('');
const detailDescription = ref('');
const detailRows = ref([]);
const detailManifest = ref(null);
const feedback = ref('');
const errorMessage = ref('');

const loading = reactive({
  inventory: false,
  barcode: false,
  racks: false,
  rackOptions: false,
  principalGroups: false,
  nextRack: false,
  pallets: false,
  nextPallet: false,
  placements: false,
  products: false,
  transactions: false,
  loading: false,
  checker: false,
  dropping: false,
  qc: false,
  transfer: false,
  incoming: false,
  picking: false,
  alerts: false,
  action: false
});

const filters = reactive({
  inventorySearch: '',
  inventoryStatus: '',
  rackSearch: '',
  rackType: '',
  rackStatus: '',
  rackActive: 'true',
  palletSearch: '',
  palletStatus: '',
  palletActive: 'true',
  incomingKodePallet: '',
  incomingBeratPerPcsKg: '',
  placementSearch: '',
  placementRack: '',
  placementStatus: '',
  barcodeProduct: '',
  transactionSearch: '',
  transactionType: '',
  incomingNota: '',
  incomingProduct: '',
  incomingStatus: '',
  pickingNota: '',
  pickingScanPayload: '',
  manifestDriver: '',
  checkerName: '',
  checkerDock: '',
  deliveryReceiver: '',
  deliveryNotes: '',
  quarantineSearch: '',
  qcName: '',
  transferProduct: '',
  transferSourceRack: '',
  transferTargetRack: '',
  transferTargetScanPayload: '',
  transferItemScanPayload: ''
});

const incomingPagination = reactive({
  page: 1,
  pageSize: 25
});

const pickingPagination = reactive({
  page: 1,
  pageSize: 25
});

const inventoryRows = ref([]);
const barcodeRows = ref([]);
const rackRows = ref([]);
const remoteRackRows = ref([]);
const rackTotal = ref(0);
const principalGroupRows = ref([]);
const principalRows = ref([]);
const palletRows = ref([]);
const placementRows = ref([]);
const productRows = ref([]);
const transactionRows = ref([]);
const readyToLoadRows = ref([]);
const checkerRows = ref([]);
const manifestRows = ref([]);
const quarantineRows = ref([]);
const transferRows = ref([]);
const alertRows = ref([]);
const incomingItems = ref([]);
const pickingItems = ref([]);
const incomingDocument = ref(null);
const pickingDocument = ref(null);
const incomingPalletRow = ref(null);
const incomingPalletLines = ref([]);
const incomingTotalRows = ref(0);
const pickingTotalRows = ref(0);
const incomingServerPaged = ref(true);
const pickingServerPaged = ref(true);
const selectedRackId = ref('');
const selectedPalletId = ref('');
const selectedPlacementId = ref('');
const selectedPrintRackCodes = ref([]);
const selectedLoadingScheduleKey = ref('');
const selectedManifestNo = ref('');
let productLoadSequence = 0;
let rackSearchRequestVersion = 0;
let placementItemUid = 0;
let incomingPalletLineUid = 0;

function createRackForm() {
  return {
    id: '',
    id_cabang: 5,
    gudang: 1,
    rak: 1,
    level: 0,
    kolom: 1,
    nomor_urut: 1,
    kode_rak: '',
    type_rak: 'Tetap',
    max_qty_pcs: 0,
    max_qty_karton: 0,
    mix_mode: 'single_principal',
    id_principal_group: '',
    status_rak: 'Kosong',
    active: true
  };
}

function createPrincipalGroupForm() {
  return {
    id: '',
    kode_group: '',
    nama_group: '',
    principal_ids: [],
    active: true,
    notes: ''
  };
}

function createPlacementForm() {
  return {
    id: '',
    id_produk: '',
    id_cabang: 5,
    kode_rak: '',
    kode_barang: '',
    nama_barang: '',
    qty_pcs: 0,
    qty_karton: 0,
    qty_pieces: 0,
    batch_number: '',
    expired_date: '',
    status: 'READY'
  };
}

function createPalletForm() {
  return {
    id: '',
    id_cabang: 5,
    kode_pallet: '',
    tipe_pallet: 'Standard',
    berat_kosong_kg: 0,
    max_berat_kg: 0,
    max_qty_pcs: 0,
    max_qty_karton: 0,
    selectedProductId: '',
    id_produk: '',
    kode_barang: '',
    nama_barang: '',
    default_qty_pcs: 0,
    default_qty_karton: 0,
    status_pallet: 'Kosong',
    active: true,
    notes: ''
  };
}

function createPlacementItem(seed = {}) {
  return {
    uid: seed.uid || `placement-item-${++placementItemUid}`,
    selectedProductId: seed.id_produk ? String(seed.id_produk) : '',
    id_produk: seed.id_produk || '',
    kode_barang: seed.kode_barang || '',
    nama_barang: seed.nama_barang || '',
    qty_pcs: seed.qty_pcs ?? 0,
    qty_karton: seed.qty_karton ?? 0,
    qty_pieces: seed.qty_pieces ?? 0,
    batch_number: seed.batch_number || '',
    // Date inputs only accept YYYY-MM-DD. API rows can contain a timestamp,
    // so normalize it before an existing placement is edited again.
    expired_date: normalizeWmsDate(
      seed.expired_date
      || seed.ExpiredDate
      || seed.tanggal_expired
      || seed.TanggalExpired
      || seed.expiry_date
      || seed.expired
      || ''
    )
  };
}

function createIncomingPalletLine(seed = {}) {
  return {
    uid: seed.uid || `incoming-pallet-${++incomingPalletLineUid}`,
    kode_pallet: seed.kode_pallet || '',
    kode_rak: seed.kode_rak || '',
    qty_ct: Number(seed.qty_ct ?? seed.QtyCT ?? 0),
    qty_pc: Number(seed.qty_pc ?? seed.QtyPC ?? 0),
    berat_barang_kg: seed.berat_barang_kg ?? '',
    batch_number: seed.batch_number || seed.batch || seed.Batch || '',
    expired_date: normalizeWmsDate(
      seed.expired_date
      || seed.ExpiredDate
      || seed.tanggal_expired
      || seed.TanggalExpired
      || seed.expiry_date
      || seed.expired
      || ''
    )
  };
}

const rackForm = reactive(createRackForm());
const principalGroupForm = reactive(createPrincipalGroupForm());
const palletForm = reactive(createPalletForm());
const placementForm = reactive(createPlacementForm());
const placementItems = ref([createPlacementItem()]);

const tabs = [
  { key: 'inventory', label: 'Inventory' },
  { key: 'incoming', label: 'Incoming' },
  { key: 'picking', label: 'Picking' },
  { key: 'checker', label: 'Checker' },
  { key: 'loading', label: 'Loading' },
  { key: 'dropping', label: 'Pengiriman & Manifest' },
  { key: 'qc', label: 'QC Karantina' },
  { key: 'transfer', label: 'Transfer Rak' },
  { key: 'transactions', label: 'Transaksi' },
  { key: 'alerts', label: 'Alert' }
];

const dedicatedSections = new Set(['racks', 'pallets', 'placements']);
const isMonitoringSection = computed(() => !dedicatedSections.has(activeTab.value));
const pageHeaderTitle = computed(() => {
  if (activeTab.value === 'racks') return 'Master Rak WMS';
  if (activeTab.value === 'pallets') return 'Master Pallet WMS';
  if (activeTab.value === 'placements') return 'Penempatan Barang WMS';
  return 'WMS Monitoring';
});
const pageHeaderDescription = computed(() => {
  if (activeTab.value === 'racks') return 'Kelola master rak gudang, tipe rak, status aktif, dan posisi rak.';
  if (activeTab.value === 'pallets') return 'Kelola pallet, batas berat, batas qty, dan status pemakaian pallet.';
  if (activeTab.value === 'placements') return 'Kelola isi rak, pilih barang, dan catat penyesuaian stok rak.';
  return 'Inventory rak, incoming, picking, loading, dropping, transfer rak, transaksi, dan alert gudang.';
});
const rackModalTitle = computed(() => (rackForm.id ? `Edit Master Rak ${rackForm.kode_rak || ''}`.trim() : 'Tambah Master Rak'));
const rackModalDescription = computed(() => (rackForm.id
  ? 'Perbarui tipe, status, posisi, dan status aktif rak.'
  : 'Kode rak dibuat otomatis dari kode terakhir. Level 0-1 untuk rak Tetap, level 2 ke atas untuk rak Titipan, dan rak Lorong hanya level 0.'
));
const palletModalTitle = computed(() => (palletForm.id ? `Edit Pallet ${palletForm.kode_pallet || ''}`.trim() : 'Tambah Pallet'));
const palletModalDescription = computed(() => (palletForm.id
  ? 'Perbarui tipe, kapasitas, status, dan catatan pallet.'
  : 'Kode pallet bisa otomatis, lalu isi batas berat atau batas qty jika ingin divalidasi saat incoming.'
));
const placementModalTitle = computed(() => (placementForm.id ? `Edit Penempatan ${placementForm.kode_barang || ''}`.trim() : 'Tambah Penempatan Barang'));
const placementModalDescription = computed(() => (placementForm.id
  ? 'Perbarui rak, barang, qty, batch, expired, dan status penempatan.'
  : 'Pilih kode rak sekali, lalu tambahkan satu atau beberapa barang untuk ditempatkan di rak yang sama.'
));
const placementSaveLabel = computed(() => {
  if (placementForm.id) return 'Update Penempatan';
  const totalItems = placementItems.value.filter((item) => item.kode_barang).length;
  return totalItems ? `Simpan ${totalItems} Barang` : 'Simpan Barang';
});

const transactionTypeOptions = [
  { value: '', label: 'Semua tipe' },
  { value: 'BD', label: 'Barang Datang' },
  { value: 'PICK', label: 'Picking' },
  { value: 'TR', label: 'Transfer' }
];

const inventoryStatusOptions = [
  { value: '', label: 'Semua status' },
  { value: 'READY', label: 'Ready' },
  { value: 'LOW', label: 'Low' },
  { value: 'Tetap', label: 'Rak Tetap' },
  { value: 'Titipan', label: 'Rak Titipan' },
  { value: 'Lorong', label: 'Rak Lorong' }
];

const incomingStatusOptions = [
  { value: '', label: 'Semua status' },
  { value: 'BELUM_KONFIRMASI_GUDANG', label: 'Belum konfirmasi' },
  { value: 'SEBAGIAN_KONFIRMASI_GUDANG', label: 'Sebagian dikonfirmasi' },
  { value: 'SUDAH_KONFIRMASI_GUDANG', label: 'Sudah dikonfirmasi' }
];

const rackTypeOptions = [
  { value: '', label: 'Semua tipe' },
  { value: 'Tetap', label: 'Tetap' },
  { value: 'Titipan', label: 'Titipan' },
  { value: 'Lorong', label: 'Lorong' },
  { value: 'Transit', label: 'Transit' },
  { value: 'Karantina', label: 'Karantina' }
];

const rackMixModeOptions = [
  { value: 'single_principal', label: 'Single Principal' },
  { value: 'mixed_group', label: 'Mixed Group' }
];

const rackStatusOptions = [
  { value: '', label: 'Semua status' },
  { value: 'Kosong', label: 'Kosong' },
  { value: 'Isi', label: 'Isi' },
  { value: 'Nonaktif', label: 'Nonaktif' }
];

const rackActiveOptions = [
  { value: '', label: 'Semua rak' },
  { value: 'true', label: 'Aktif' },
  { value: 'false', label: 'Nonaktif' }
];

const palletStatusOptions = [
  { value: '', label: 'Semua status' },
  { value: 'Kosong', label: 'Kosong' },
  { value: 'Terisi', label: 'Terisi' },
  { value: 'Rusak', label: 'Rusak' },
  { value: 'Nonaktif', label: 'Nonaktif' }
];

const palletActiveOptions = [
  { value: '', label: 'Semua pallet' },
  { value: 'true', label: 'Aktif' },
  { value: 'false', label: 'Nonaktif' }
];

const principalOptions = computed(() =>
  principalRows.value
    .map((item) => ({
      value: String(item.id || item.id_principal || ''),
      label: `${item.kode || item.kode_principal || '-'} - ${item.nama || item.nama_principal || 'Principal'}`.trim(),
      raw: item
    }))
    .filter((item) => item.value)
);

const principalGroupOptions = computed(() =>
  principalGroupRows.value
    .filter((item) => item.active !== false)
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode_group || '-'} - ${item.nama_group || 'Group Principal'}`
    }))
);

const placementStatusOptions = [
  { value: '', label: 'Semua status' },
  { value: 'READY', label: 'Ready' },
  { value: 'LOW', label: 'Low' },
  { value: 'EMPTY', label: 'Empty' },
  { value: 'INACTIVE', label: 'Inactive' }
];

function productOptionFromRow(item = {}) {
  const id = item.id || item.id_produk || item.produk_id || item.value;
  const code = item.kode_sku || item.kode_barang || item.kode_ean || item.kode || item.product_code || '';
  const name = item.nama || item.nama_produk || item.nama_barang || item.label || '';
  const value = id || code;

  if (!value) return null;

  return {
    value: String(value),
    label: item.text || [code, name].filter(Boolean).join(' - ') || `Produk ${id || '-'}`,
    code,
    name,
    raw: item
  };
}

function selectedProductOption(selection = {}) {
  const value = selection.selectedProductId || selection.id_produk || selection.kode_barang;
  if (!value) return null;

  const code = selection.kode_barang || '';
  const name = selection.nama_barang || '';
  return {
    value: String(value),
    label: [code, name].filter(Boolean).join(' - ') || `Produk ${value}`,
    code,
    name,
    raw: selection
  };
}

const productOptions = computed(() => {
  // A remote search replaces productRows. Keep products already selected in
  // the pallet/placement forms in the option set so their label does not turn
  // blank while an operator searches for another product.
  const candidates = [
    ...productRows.value.map(productOptionFromRow),
    selectedProductOption(palletForm),
    ...placementItems.value.map(selectedProductOption)
  ].filter(Boolean);
  const unique = new Map();
  candidates.forEach((item) => {
    if (!unique.has(item.value)) unique.set(item.value, item);
  });
  return [...unique.values()];
});

function normalizeRackType(item) {
  return String(item?.type_rak || item?.shelf_type || 'Tetap').trim().toLowerCase();
}

function isPickingReadyRack(item) {
  const type = normalizeRackType(item);
  return type === 'tetap' || type === 'lorong';
}

function rackLevelValue(item) {
  const value = item?.level ?? item?.raw?.level ?? 0;
  return Number.isFinite(Number(value)) ? Number(value) : 0;
}

function isActiveRack(item) {
  return item?.active !== false && String(item?.status_rak || '').trim().toLowerCase() !== 'nonaktif';
}

function rackOption(item) {
  return {
      value: item.kode_rak,
      label: [
        item.kode_rak,
        item.type_rak,
        item.status_rak,
        item.active === false ? 'Nonaktif' : 'Aktif'
      ].filter(Boolean).join(' - '),
      raw: item
  };
}

const rackOptionRows = computed(() => {
  const rowMap = new Map();
  // Jangan mengganti daftar master dengan hasil pencarian. AppSearchSelect
  // menghitung chip/ringkasan pilihan dari `options`; bila pencarian remote
  // berikutnya tidak memuat lagi rak yang sudah dicentang, nilainya tetap ada
  // namun field tampak kosong. Gabungkan master dan hasil remote supaya
  // pilihan QR yang sudah dipilih selalu dapat dirender.
  const sourceRows = [...rackRows.value, ...remoteRackRows.value];
  sourceRows.forEach((item) => {
    const code = normalizeRackCode(item?.kode_rak);
    if (code) rowMap.set(code, item);
  });
  (Array.isArray(selectedPrintRackCodes.value)
    ? selectedPrintRackCodes.value
    : String(selectedPrintRackCodes.value || '').split(',')
  )
    .map((code) => normalizeRackCode(code))
    .filter(Boolean)
    .forEach((code) => {
      if (!rowMap.has(code)) rowMap.set(code, { kode_rak: code });
    });
  return Array.from(rowMap.values());
});

const rackSelectOptions = computed(() =>
  rackOptionRows.value
    .filter((item) => item?.kode_rak)
    .map((item) => rackOption(item))
);

const placementPrintRackOptions = computed(() => {
  const optionMap = new Map(rackSelectOptions.value.map((option) => [normalizeRackCode(option.value), {
    ...option,
    value: normalizeRackCode(option.value) || option.value
  }]));
  placementRows.value.forEach((row) => {
    const code = placementRackCode(row);
    if (!code || optionMap.has(code)) return;
    optionMap.set(code, {
      value: code,
      label: `${code} - Isi rak`,
      raw: row
    });
  });
  return Array.from(optionMap.values());
});

const fixedRackSelectOptions = computed(() =>
  rackOptionRows.value
    .filter((item) => item?.kode_rak && isActiveRack(item) && normalizeRackType(item) === 'tetap' && rackLevelValue(item) <= 1)
    .map((item) => rackOption(item))
);

const titipanRackSelectOptions = computed(() =>
  rackOptionRows.value
    .filter((item) => item?.kode_rak && isActiveRack(item) && normalizeRackType(item) === 'titipan' && rackLevelValue(item) >= 2)
    .map((item) => rackOption(item))
);

const placementRackSelectOptions = computed(() => {
  const options = rackOptionRows.value
    .filter((item) => {
      if (!item?.kode_rak || !isActiveRack(item)) return false;

      const type = normalizeRackType(item);
      const level = rackLevelValue(item);
      return (type === 'tetap' && level <= 1) || (type === 'lorong' && level === 0);
    })
    .map((item) => rackOption(item));
  if (placementForm.kode_rak && !options.some((item) => String(item.value) === String(placementForm.kode_rak))) {
    options.unshift({
      value: placementForm.kode_rak,
      label: placementForm.kode_rak,
      raw: null
    });
  }

  return options;
});

const palletSelectOptions = computed(() =>
  palletRows.value
    .filter((item) => item?.kode_pallet && item.active !== false)
    .map((item) => ({
      value: item.kode_pallet,
      label: [
        item.kode_pallet,
        palletProductLabel(item),
        item.tipe_pallet,
        item.status_pallet,
        `${numberLabel(item.used_qty_pcs)} pcs`
      ].filter(Boolean).join(' - '),
      raw: item
    }))
);

const transferTargetRackOptions = computed(() => {
  const options = [...fixedRackSelectOptions.value];
  if (filters.transferTargetRack && !options.some((item) => String(item.value) === String(filters.transferTargetRack))) {
    options.unshift({
      value: filters.transferTargetRack,
      label: filters.transferTargetRack,
      raw: null
    });
  }
  return options;
});

// QC may return GOOD stock only to an active fixed rack or aisle.  Each row
// keeps its own branch-scoped remote result, so choosing a rack on one row
// cannot accidentally show a rack from another row's branch.
function quarantineTargetRackOptions(row) {
  const optionMap = new Map();
  const branchId = Number(row?.id_cabang) || rackBranchId();
  (Array.isArray(row?.target_rack_options) ? row.target_rack_options : [])
    .filter((item) => item?.kode_rak && isActiveRack(item) && isPickingReadyRack(item)
      && (!item.id_cabang || Number(item.id_cabang) === branchId))
    .forEach((item) => optionMap.set(normalizeRackCode(item.kode_rak), rackOption(item)));

  const code = normalizeRackCode(row?.target_rack_input);
  if (code && !optionMap.has(code)) {
    optionMap.set(code, { value: code, label: code, raw: null });
  }

  return Array.from(optionMap.values());
}

const selectedTransferRows = computed(() =>
  transferRows.value.filter((row) => row.selected && Number(row.transfer_qty || 0) > 0)
);
const selectedRackRow = computed(() =>
  rackRows.value.find((row) => String(row.id) === String(selectedRackId.value)) || null
);
const selectedPlacementRow = computed(() =>
  placementRows.value.find((row) => String(row.id) === String(selectedPlacementId.value)) || null
);
const selectedPrintRackCodeList = computed(() =>
  Array.from(new Set(
    (Array.isArray(selectedPrintRackCodes.value) ? selectedPrintRackCodes.value : String(selectedPrintRackCodes.value || '').split(','))
      .map((code) => normalizeRackCode(code))
      .filter(Boolean)
  ))
);
const selectedPrintRackRows = computed(() =>
  selectedPrintRackCodeList.value.map((code) =>
    rackOptionRows.value.find((row) => String(row.kode_rak) === String(code)) || { kode_rak: code }
  )
);
const placementFilterRackCode = computed(() =>
  firstRackCode(
    filters.placementRack,
    rackCodeFromText(filters.placementSearch),
    selectedPlacementRow.value?.kode_rak
  )
);
const transferSelectionSummary = computed(() => ({
  itemCount: selectedTransferRows.value.length,
  totalQty: selectedTransferRows.value.reduce((total, row) => total + Number(row.transfer_qty || 0), 0)
}));
const allTransferRowsSelected = computed(() =>
  Boolean(transferRows.value.length) && transferRows.value.every((row) => row.selected)
);
const canConfirmTransfer = computed(() =>
  Boolean(filters.transferTargetRack && selectedTransferRows.value.length && !loading.action)
);

const monitoringPrintSummary = computed(() => {
  const loadedRack = rackRows.value.length;
  const totalRack = Math.max(Number(rackTotal.value || 0), loadedRack);
  const selectedRack = selectedPrintRackCodeList.value.length;
  if (selectedRack) {
    return `${numberLabel(selectedRack)} rak dipilih dari ${numberLabel(totalRack)} rak`;
  }
  if (totalRack > loadedRack) {
    return `${numberLabel(totalRack)} total rak, ${numberLabel(loadedRack)} dimuat. Ketik kode untuk mencari rak lain.`;
  }
  return `${numberLabel(totalRack)} rak tersedia`;
});

const inventoryReadyGudangCt = computed(() =>
  inventoryRows.value.reduce((total, item) => total + Number(item.quantity_ct || 0), 0)
);
const inventoryReadyPickingCt = computed(() =>
  inventoryRows.value
    .filter((item) => isPickingReadyRack(item))
    .reduce((total, item) => total + Number(item.quantity_ct || 0), 0)
);
const inventoryTitipanCt = computed(() =>
  inventoryRows.value
    .filter((item) => normalizeRackType(item) === 'titipan')
    .reduce((total, item) => total + Number(item.quantity_ct || 0), 0)
);

const summaryCards = computed(() => [
  { label: 'SKU WMS', value: numberLabel(inventoryRows.value.length) },
  { label: 'Rak Aktif', value: numberLabel(rackRows.value.filter((item) => item.active !== false).length) },
  { label: 'Pallet Aktif', value: numberLabel(palletRows.value.filter((item) => item.active !== false).length) },
  { label: 'Ready Gudang', value: numberLabel(inventoryReadyGudangCt.value) },
  { label: 'Ready Picking', value: numberLabel(inventoryReadyPickingCt.value) },
  { label: 'Titipan', value: numberLabel(inventoryTitipanCt.value) },
  { label: 'Ready Load', value: numberLabel(readyToLoadRows.value.length) },
  { label: 'Alert Rak', value: numberLabel(alertRows.value.length) }
]);

const flowSteps = computed(() => [
  {
    number: '01',
    title: 'Barang Datang',
    tab: 'incoming',
    metric: numberLabel(incomingItems.value.length),
    metricLabel: 'item incoming',
    source: 'purchase_transaksi',
    action: 'Cetak QR pallet',
    result: 'rak titipan + ledger BD',
    tone: 'border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-100'
  },
  {
    number: '02',
    title: 'Stok Rak',
    tab: 'inventory',
    metric: numberLabel(rackRows.value.length || inventoryRows.value.length),
    metricLabel: 'master rak',
    source: 'wms_rack_master + wms_stock_rak',
    action: 'Cek / edit rak',
    result: 'Titipan = ready gudang, Tetap/Lorong = siap picking',
    tone: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-100'
  },
  {
    number: '03',
    title: 'Picking Order',
    tab: 'picking',
    metric: numberLabel(pickingItems.value.length),
    metricLabel: 'item draft',
    source: 'sales_order',
    action: 'Scan rak',
    result: 'stok keluar + PICK',
    tone: 'border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-500/30 dark:bg-indigo-500/10 dark:text-indigo-100'
  },
  {
    number: '04',
    title: 'Ready Load',
    tab: 'loading',
    metric: numberLabel(readyToLoadRows.value.length),
    metricLabel: 'item siap muat',
    source: 'picked task',
    action: 'Proses loading',
    result: 'manifest dibuat',
    tone: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-100'
  },
  {
    number: '05',
    title: 'Manifest',
    tab: 'dropping',
    metric: numberLabel(manifestTableRows.value.length),
    metricLabel: 'manifest',
    source: 'loading_manifest',
    action: 'Cetak QR / cek kirim',
    result: 'selesai / karantina',
    tone: 'border-cyan-200 bg-cyan-50 text-cyan-700 dark:border-cyan-500/30 dark:bg-cyan-500/10 dark:text-cyan-100'
  },
  {
    number: '06',
    title: 'Karantina',
    tab: 'dropping',
    metric: numberLabel(alertRows.value.length),
    metricLabel: 'alert rak',
    source: 'wms_quarantine',
    action: 'Tahan barang retur',
    result: 'follow up gudang',
    tone: 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-100'
  }
]);

const manifestTableRows = computed(() =>
  manifestRows.value.map((item) => ({
    ...item,
    total_item: item.details?.length || 0,
    driver: item.details?.[0]?.DriverRencana || '-',
    nota: [...new Set(
      (item.details || [])
        .map((detail) => String(detail.Nota || detail.nota || '').trim())
        .filter(Boolean)
    )].join(', ') || '-'
  }))
);

function manifestNumber(row) {
  return String(row?.NoManifest || row?.no_manifest || row?.manifest_no || '').trim();
}

const selectedManifestForQr = computed(() => {
  const selectedNo = String(selectedManifestNo.value || '').trim();
  if (!selectedNo) return null;
  return manifestTableRows.value.find((row) => manifestNumber(row) === selectedNo) || null;
});

const inventoryColumns = [
  { key: 'product_code', label: 'Kode' },
  { key: 'product_name', label: 'Produk' },
  { key: 'quantity_ct', label: 'CT', render: (row) => numberLabel(row.quantity_ct) },
  { key: 'quantity_pc', label: 'PC', render: (row) => numberLabel(row.quantity_pc) },
  { key: 'location', label: 'Rak' },
  { key: 'shelf_type', label: 'Tipe Rak' },
  { key: 'wms_ready_status', label: 'Status WMS', render: (row) => statusBadge(row.wms_ready_status || row.status) },
  { key: 'tanggal_masuk_gudang', label: 'Masuk Gudang', render: (row) => rowTanggalMasuk(row) || '-' },
  { key: 'umur_barang_hari', label: 'Umur', render: (row) => rowUmurLabel(row) },
  { key: 'fifo_label', label: 'FIFO', render: (row) => flowBadge(row.fifo_label, Number(row.fifo_rank) === 1 ? 'green' : 'slate') },
  { key: 'fefo_label', label: 'FEFO', render: (row) => flowBadge(row.fefo_label, Number(row.fefo_rank) === 1 ? 'amber' : 'slate') },
  { key: 'batch_number', label: 'Batch' },
  { key: 'expiry_date', label: 'Expired' },
  { key: 'status', label: 'Status', render: (row) => statusBadge(row.status) }
];

const rackColumns = [
  { key: 'kode_rak', label: 'Kode Rak' },
  { key: 'type_rak', label: 'Tipe' },
  { key: 'status_rak', label: 'Status', render: (row) => statusBadge(row.status_rak) },
  { key: 'active', label: 'Aktif', render: (row) => statusBadge(row.active === false ? 'Nonaktif' : 'Aktif') },
  { key: 'qty_pcs', label: 'Qty PCS', render: (row) => numberLabel(row.qty_pcs) },
  { key: 'max_qty_pcs', label: 'Kapasitas PCS', render: (row) => row.max_qty_pcs ? numberLabel(row.max_qty_pcs) : 'Tidak dibatasi' },
  { key: 'mix_mode', label: 'Mix', render: (row) => row.mix_mode === 'mixed_group' ? 'Mixed Group' : 'Single Principal' },
  { key: 'principal_group_name', label: 'Group Principal', render: (row) => row.principal_group_name || '-' },
  { key: 'placement_count', label: 'Penempatan', render: (row) => numberLabel(row.placement_count) },
  { key: 'posisi', label: 'Posisi', render: (row) => rackPositionLabel(row) },
  { key: 'source_type', label: 'Sumber' }
];

const palletColumns = [
  { key: 'kode_pallet', label: 'Kode Pallet' },
  { key: 'tipe_pallet', label: 'Tipe' },
  { key: 'nama_barang', label: 'Produk / Isi', render: (row) => palletProductLabel(row) },
  { key: 'status_pallet', label: 'Status', render: (row) => statusBadge(row.status_pallet) },
  { key: 'used_qty_pcs', label: 'Isi PCS', render: (row) => numberLabel(row.used_qty_pcs) },
  { key: 'max_qty_pcs', label: 'Max PCS', render: (row) => row.max_qty_pcs ? numberLabel(row.max_qty_pcs) : 'Tidak dibatasi' },
  { key: 'used_qty_karton', label: 'Isi Karton', render: (row) => numberLabel(row.used_qty_karton) },
  { key: 'max_qty_karton', label: 'Max Karton', render: (row) => row.max_qty_karton ? numberLabel(row.max_qty_karton) : 'Tidak dibatasi' },
  { key: 'default_qty_karton', label: 'Bagi/Karton', render: (row) => row.default_qty_karton ? numberLabel(row.default_qty_karton) : '-' },
  { key: 'default_qty_pcs', label: 'Bagi/PCS', render: (row) => row.default_qty_pcs ? numberLabel(row.default_qty_pcs) : '-' },
  { key: 'used_berat_kg', label: 'Berat Isi', render: (row) => `${numberLabel(row.used_berat_kg)} kg` },
  { key: 'max_berat_kg', label: 'Max Berat', render: (row) => row.max_berat_kg ? `${numberLabel(row.max_berat_kg)} kg` : 'Tidak dibatasi' },
  { key: 'kode_rak_list', label: 'Rak' },
  { key: 'active', label: 'Aktif', render: (row) => statusBadge(row.active === false ? 'Nonaktif' : 'Aktif') }
];

const placementColumns = [
  { key: 'kode_rak', label: 'Rak' },
  { key: 'kode_barang', label: 'Kode Barang' },
  { key: 'nama_barang', label: 'Produk' },
  { key: 'qty_pcs', label: 'Jumlah (UOM)', render: (row) => formatUomQuantity(row.qty_pcs, row) },
  { key: 'qty_pcs_total', label: 'Total PCS', render: (row) => numberLabel(row.qty_pcs) },
  { key: 'batch_number', label: 'Batch' },
  { key: 'expired_date', label: 'Expired' },
  { key: 'status', label: 'Status', render: (row) => statusBadge(row.status) },
  { key: 'source_type', label: 'Sumber' }
];
const placementBalanceColumns = [
  {key:'nama_cabang',label:'Cabang'},
  {key:'kode_sku',label:'Kode SKU'},
  {key:'nama_produk',label:'Produk'},
  {key:'quantity',label:'Jumlah (Stok Ready)',render:r=>`${numberLabel(r.qty_pcs)} ${r.uom || 'PCS'}`},
  {key:'qty_pcs',label:'Total PCS',render:r=>numberLabel(r.qty_pcs)},
  {key:'jumlah_good',label:'GOOD',render:r=>numberLabel(r.jumlah_good)},
  {key:'mapped_pcs',label:'Terdata di Rak',render:r=>numberLabel(r.mapped_pcs)},
  {key:'mapping_gap',label:'Selisih Pemetaan',render:r=>numberLabel(r.mapping_gap)},
  {key:'mapping_status',label:'Status Pemetaan'},
];

const transactionColumns = [
  { key: 'Nota', label: 'Nota' },
  { key: 'JenisTransaksi', label: 'Tipe', render: (row) => statusBadge(row.JenisTransaksi) },
  { key: 'KodeBarang', label: 'Kode' },
  { key: 'NamaBarang', label: 'Produk' },
  { key: 'KodeRak', label: 'Rak' },
  { key: 'Masuk', label: 'Masuk', render: (row) => numberLabel(row.Masuk) },
  { key: 'Keluar', label: 'Keluar', render: (row) => numberLabel(row.Keluar) },
  { key: 'UserAdd', label: 'User' },
  { key: 'UrutTanggal', label: 'Tanggal' }
];

const loadColumns = [
  { key: 'loading_status', label: 'Tahap Loading' },
  { key: 'DockRencana', label: 'Dock' },
  { key: 'ZonaMuatan', label: 'Zona' },
  { key: 'CatatanPengiriman', label: 'Catatan' },
  { key: 'CalonNoManifest', label: 'Manifest' },
  { key: 'DriverRencana', label: 'Driver' },
  { key: 'ArmadaRencana', label: 'Armada' },
  { key: 'HelperRencana', label: 'Helper' },
  { key: 'Nota', label: 'Nota' },
  { key: 'KodeBarang', label: 'Kode' },
  { key: 'NamaBarang', label: 'Produk' },
  { key: 'Unit', label: 'Unit', render: (row) => numberLabel(row.Unit) },
  { key: 'Satuan', label: 'Satuan', render: (row) => numberLabel(row.Satuan) },
  { key: 'batch', label: 'Batch' },
  { key: 'expired', label: 'Expired' }
];

const manifestColumns = [
  { key: 'NoManifest', label: 'Manifest' },
  { key: 'driver', label: 'Driver' },
  { key: 'vehicle_no', label: 'Kendaraan', render: (row) => row.vehicle_no || '-' },
  { key: 'status', label: 'Status', render: (row) => statusBadge(row.status) },
  { key: 'total_item', label: 'Item', render: (row) => numberLabel(row.total_item) },
  { key: 'nota', label: 'Nota' }
];

const checkerColumns = [
  { key: 'nota', label: 'Draft / Nota' },
  { key: 'route_code', label: 'Rute', render: (row) => row.route_code || '-' },
  { key: 'total_item', label: 'Item', render: (row) => numberLabel(row.total_item) },
  { key: 'small_item', label: 'Barang Kecil', render: (row) => numberLabel(row.small_item) },
  { key: 'qty_perlu_cek', label: 'Qty Dicek', render: (row) => numberLabel(row.qty_perlu_cek) },
  { key: 'status', label: 'Status', render: (row) => statusBadge(row.status) }
];

const transferColumns = [
  { key: 'kode_barang', label: 'Kode' },
  { key: 'nama_barang', label: 'Produk' },
  { key: 'kode_rak_asal', label: 'Rak Asal' },
  { key: 'qty_karton', label: 'Karton', render: (row) => numberLabel(row.qty_karton) },
  { key: 'qty', label: 'Qty', render: (row) => numberLabel(row.qty) },
  { key: 'batch', label: 'Batch' },
  { key: 'expired_date', label: 'Expired' },
  { key: 'tanggal_masuk_gudang', label: 'Masuk Gudang', render: (row) => rowTanggalMasuk(row) || '-' },
  { key: 'umur_barang_hari', label: 'Umur', render: (row) => rowUmurLabel(row) },
  { key: 'fifo_label', label: 'FIFO', render: (row) => flowBadge(row.fifo_label, Number(row.fifo_rank) === 1 ? 'green' : 'slate') },
  { key: 'fefo_label', label: 'FEFO', render: (row) => flowBadge(row.fefo_label, Number(row.fefo_rank) === 1 ? 'amber' : 'slate') }
];

const alertColumns = [
  { key: 'kode_rak', label: 'Rak' },
  { key: 'kode_barang', label: 'Kode' },
  { key: 'nama_barang', label: 'Produk' },
  { key: 'qty_karton', label: 'Karton', render: (row) => numberLabel(row.qty_karton) }
];

const incomingColumns = [
  { key: 'Nota', label: 'Nota' },
  { key: 'KodeBarang', label: 'Kode' },
  { key: 'NamaBarang', label: 'Produk' },
  { key: 'QtyCT', label: 'CT', render: (row) => numberLabel(incomingRowQtyCt(row)) },
  { key: 'QtyPC', label: 'PC', render: (row) => numberLabel(incomingRowQtyPc(row)) },
  { key: 'PerUnit', label: 'Per Unit', render: (row) => numberLabel(incomingPerUnit(row)) },
  { key: 'IsiPalet', label: 'Palet', render: (row) => numberLabel(row.IsiPalet) }
];

const pickingColumns = [
  { key: 'product_code', label: 'Kode' },
  { key: 'product_name', label: 'Produk' },
  { key: 'rak_tetap', label: 'Rak' },
  { key: 'required_quantity', label: 'Qty', render: (row) => numberLabel(row.required_quantity) },
  { key: 'batch', label: 'Batch' },
  { key: 'status_draft', label: 'Status', render: (row) => statusBadge(row.status_draft) }
];

const incomingDisplayTotal = computed(() => incomingTotalRows.value || incomingItems.value.length);
const pickingDisplayTotal = computed(() => pickingTotalRows.value || pickingItems.value.length);
const incomingTotalPages = computed(() => totalPages(incomingDisplayTotal.value, incomingPagination.pageSize));
const pickingTotalPages = computed(() => totalPages(pickingDisplayTotal.value, pickingPagination.pageSize));
const incomingPageStart = computed(() => (incomingPagination.page - 1) * incomingPagination.pageSize);
const pickingPageStart = computed(() => (pickingPagination.page - 1) * pickingPagination.pageSize);
const visibleIncomingItems = computed(() => incomingServerPaged.value ? incomingItems.value : paginateRows(incomingItems.value, incomingPagination));
const visiblePickingItems = computed(() => pickingServerPaged.value ? pickingItems.value : paginateRows(pickingItems.value, pickingPagination));
const incomingPalletExpectedQty = computed(() => incomingRowTotalQty(incomingPalletRow.value));
const incomingPalletTotalQty = computed(() =>
  incomingPalletLines.value.reduce((total, line) => total + incomingLineTotalQty(line, incomingPalletRow.value), 0)
);
const incomingPalletRemainingQty = computed(() => incomingPalletExpectedQty.value - incomingPalletTotalQty.value);
const canSubmitIncomingPallets = computed(() =>
  Boolean(incomingPalletRow.value)
    && incomingPalletLines.value.length > 0
    && incomingPalletExpectedQty.value > 0
    && incomingPalletRemainingQty.value === 0
    && !loading.action
);
function pickingTaskIds(document = pickingDocument.value) {
  const rawIds = document?.task_ids;
  const candidates = Array.isArray(rawIds)
    ? rawIds
    : String(rawIds || '').split(',');
  const ids = candidates
    .map((value) => Number(value))
    .filter((value, index, values) => Number.isFinite(value) && value > 0 && values.indexOf(value) === index);
  if (ids.length) return ids;

  const fallbackId = Number(document?.id_picking || document?.id || 0);
  return fallbackId > 0 ? [fallbackId] : [];
}
const canFinalizePicking = computed(() => {
  const taskIds = pickingTaskIds();
  const status = String(pickingDocument.value?.status || '').toUpperCase();
  const hasSelectedNota = Boolean(String(filters.pickingNota || '').trim());
  const everyItemPicked = pickingItems.value.length > 0 && pickingItems.value.every((row) =>
    ['PICKED', 'CHECKED'].includes(String(row?.status_draft || row?.status || '').toUpperCase())
  );
  return Boolean(taskIds.length && hasSelectedNota && everyItemPicked && !['READY_DOCK', 'CHECKER_PENDING', 'CHECKER_HOLD', 'LOADING', 'LOADED'].includes(status));
});
const loadingScheduleGroups = computed(() => {
  const groups = new Map();
  readyToLoadRows.value.forEach((row, index) => {
    const key = String(row.ScheduleKey || row.schedule_key || `UNSCHEDULED|${row.wms_task_detail_id || index}`);
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        driver: textValue(row.DriverRencana || row.driver_name, 'Jadwal belum lengkap'),
        armada: textValue(row.ArmadaRencana || row.vehicle_no || row.armada_name, '-'),
        helpers: textValue(row.HelperRencana || row.helper_names, '-'),
        deliveryDate: textValue(row.ScheduledDeliveryDate || row.scheduled_delivery_date, '-'),
        isScheduled: String(row.ScheduleStatus || row.schedule_status || '').toUpperCase() === 'SCHEDULED',
        rows: []
      });
    }
    groups.get(key).rows.push(row);
  });
  return [...groups.values()];
});
const selectedLoadingScheduleGroup = computed(() =>
  loadingScheduleGroups.value.find((group) => group.key === selectedLoadingScheduleKey.value)
  || loadingScheduleGroups.value[0]
  || null
);
const selectedReadyToLoadRows = computed(() => selectedLoadingScheduleGroup.value?.rows || []);
const canSubmitScheduledLoading = computed(() =>
  Boolean(selectedLoadingScheduleGroup.value?.isScheduled && selectedReadyToLoadRows.value.length && !loading.action)
);

function numberLabel(value) {
  return Number(value || 0).toLocaleString('id-ID');
}

function incomingPerUnit(row) {
  return Math.max(Number(row?.PerUnit || row?.per_unit || 1), 1);
}

function incomingRowTotalQty(row) {
  if (!row) return 0;
  const directQtyPcs = Number(row.qty_pcs ?? row.QtyPCS ?? 0);
  if (Number.isFinite(directQtyPcs) && directQtyPcs > 0) return directQtyPcs;
  const perUnit = incomingPerUnit(row);
  const qtyCt = Number(row.QtyCT || row.qty_ct || 0);
  const qtyPc = Number(row.QtyPC || row.qty_pc || 0);
  const total = qtyCt * perUnit + qtyPc;
  return total > 0 ? total : Number(row.qty_pcs || 0);
}

function incomingRowQtyCt(row) {
  return Math.floor(incomingRowTotalQty(row) / incomingPerUnit(row));
}

function incomingRowQtyPc(row) {
  return incomingRowTotalQty(row) % incomingPerUnit(row);
}

function incomingLineTotalQty(line, row = incomingPalletRow.value) {
  const perUnit = incomingPerUnit(row);
  return Math.max(Number(line?.qty_ct || 0), 0) * perUnit + Math.max(Number(line?.qty_pc || 0), 0);
}

function incomingProductCode(row) {
  return String(row?.KodeBarang || row?.KodeStok || row?.kode_barang || '').trim();
}

function incomingProductId(row) {
  return String(row?.id_produk || row?.IdProduk || row?.produk_id || '').trim();
}

function findIncomingPalletRule(row) {
  const productCode = incomingProductCode(row);
  const productId = incomingProductId(row);
  return palletRows.value.find((item) => {
    if (item?.active === false) return false;
    const itemProductId = String(item.id_produk || '').trim();
    const itemCode = String(item.kode_barang || '').trim();
    return (productId && itemProductId && itemProductId === productId)
      || (productCode && itemCode && itemCode === productCode);
  });
}

function incomingPalletRuleQty(row) {
  const rule = findIncomingPalletRule(row);
  const perUnit = incomingPerUnit(row);
  const defaultQty = Number(rule?.default_qty_pcs || 0);
  const defaultKarton = Number(rule?.default_qty_karton || 0) * perUnit;
  const maxQty = Number(rule?.max_qty_pcs || 0);
  const maxKarton = Number(rule?.max_qty_karton || 0) * perUnit;
  return [defaultQty, defaultKarton, maxQty, maxKarton].find((qty) => qty > 0) || incomingRowTotalQty(row);
}

function splitIncomingPalletByRule(row) {
  const total = incomingRowTotalQty(row);
  const perUnit = incomingPerUnit(row);
  const chunkQty = Math.max(incomingPalletRuleQty(row), 1);
  const lines = [];
  let remaining = total;

  while (remaining > 0) {
    const qty = Math.min(remaining, chunkQty);
    lines.push(createIncomingPalletLine({
      qty_ct: Math.floor(qty / perUnit),
      qty_pc: qty % perUnit,
      batch_number: rowBatch(row),
      expired_date: rowExpired(row)
    }));
    remaining -= qty;
  }

  return lines.length ? lines : [createIncomingPalletLine()];
}

function incomingPalletCount(row) {
  return splitIncomingPalletByRule(row).length;
}

function statusBadge(value) {
  const text = String(value || '-');
  const normalized = text.toLowerCase();
  const className = normalized.includes('pending') || normalized.includes('belum')
    ? 'rounded-full bg-amber-100 px-2 py-1 text-xs font-bold text-amber-700 dark:bg-amber-500/15 dark:text-amber-200'
    : normalized.includes('low') || normalized.includes('empty')
      ? 'rounded-full bg-amber-100 px-2 py-1 text-xs font-bold text-amber-700 dark:bg-amber-500/15 dark:text-amber-200'
      : normalized.includes('ok') || normalized.includes('ready') || normalized.includes('bd')
      ? 'rounded-full bg-emerald-100 px-2 py-1 text-xs font-bold text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-200'
      : 'rounded-full bg-slate-100 px-2 py-1 text-xs font-bold text-slate-600 dark:bg-slate-800 dark:text-slate-200';
  return { text, className };
}

function flowBadge(value, tone = 'slate') {
  const text = textValue(value, '-');
  const toneClass = {
    green: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-200',
    amber: 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-200',
    slate: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-200'
  }[tone] || 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-200';
  return {
    text,
    className: `inline-flex rounded-full px-2.5 py-1 text-xs font-black ${toneClass}`
  };
}

function rowTanggalMasuk(row) {
  return textValue(row?.tanggal_masuk_gudang || row?.TanggalMasukGudang || row?.created_at || row?.createdAt, '');
}

function rowUmurLabel(row) {
  const days = Number(row?.umur_barang_hari ?? row?.umur_hari ?? row?.age_days);
  if (!Number.isFinite(days)) return '-';
  if (days <= 0) return 'Hari ini';
  return `${numberLabel(days)} hari`;
}

function rowFifoBadge(row) {
  return flowBadge(row?.fifo_label, Number(row?.fifo_rank) === 1 ? 'green' : 'slate');
}

function rowFefoBadge(row) {
  return flowBadge(row?.fefo_label, Number(row?.fefo_rank) === 1 ? 'amber' : 'slate');
}

function incomingStatusBadge(row) {
  const noteStatus = String(row?.StatusNota || row?.status_nota || '').toUpperCase();
  if (noteStatus === 'SUDAH_KONFIRMASI_GUDANG') {
    return {
      text: 'Sudah Konfirmasi Gudang',
      className: 'rounded-full bg-emerald-100 px-2 py-1 text-xs font-bold text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-200'
    };
  }
  if (noteStatus === 'SEBAGIAN_KONFIRMASI_GUDANG') {
    return {
      text: 'Sebagian Dikonfirmasi',
      className: 'rounded-full bg-sky-100 px-2 py-1 text-xs font-bold text-sky-700 dark:bg-sky-500/15 dark:text-sky-200'
    };
  }
  if (noteStatus === 'BELUM_KONFIRMASI_GUDANG') {
    return {
      text: 'Belum Konfirmasi Gudang',
      className: 'rounded-full bg-amber-100 px-2 py-1 text-xs font-bold text-amber-700 dark:bg-amber-500/15 dark:text-amber-200'
    };
  }
  if (isIncomingProcessed(row)) {
    return {
      text: 'Sudah Konfirmasi Gudang',
      className: 'rounded-full bg-emerald-100 px-2 py-1 text-xs font-bold text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-200'
    };
  }
  const status = String(row?.StatusGudang || row?.status_gudang || row?.status || '').toUpperCase();
  if (status === 'PENDING_WAREHOUSE' || status === 'BELUM_KONFIRMASI_GUDANG') {
    return {
      text: 'Belum Konfirmasi Gudang',
      className: 'rounded-full bg-amber-100 px-2 py-1 text-xs font-bold text-amber-700 dark:bg-amber-500/15 dark:text-amber-200'
    };
  }
  return {
    text: 'Siap Konfirmasi',
    className: 'rounded-full bg-sky-100 px-2 py-1 text-xs font-bold text-sky-700 dark:bg-sky-500/15 dark:text-sky-200'
  };
}

function rackPositionLabel(row) {
  const parts = [
    row.gudang ? `G${row.gudang}` : '',
    row.rak ? `R${padRackSegment(row.rak)}` : '',
    row.level !== null && row.level !== undefined && row.level !== '' ? `L${Number(row.level)}` : '',
    row.kolom ? `K${padRackSegment(row.kolom)}` : '',
    row.nomor_urut ? `N${padRackSegment(row.nomor_urut)}` : ''
  ].filter(Boolean);
  return parts.length ? parts.join(' / ') : '-';
}

function padRackSegment(value) {
  return String(Math.max(Number(value || 1), 1)).padStart(2, '0');
}

function formatRackCodeFromForm(form) {
  const gudang = Math.max(Number(form.gudang || 1), 1);
  const rak = Math.max(Number(form.rak || 1), 1);
  const level = Math.max(Number(form.level ?? 0), 0);
  const kolom = Math.max(Number(form.kolom || 1), 1);
  const nomor = Math.max(Number(form.nomor_urut || 1), 1);
  return `G${gudang}R${padRackSegment(rak)}L${level}K${padRackSegment(kolom)}N${padRackSegment(nomor)}`;
}

function payloadRows(payload) {
  const unwrapped = unwrapResponse(payload);
  if (Array.isArray(unwrapped)) return unwrapped;
  if (Array.isArray(unwrapped?.items)) return unwrapped.items;
  return normalizeList(unwrapped);
}

function totalPages(totalRows, pageSize) {
  return Math.max(1, Math.ceil(Number(totalRows || 0) / Number(pageSize || 25)));
}

function paginateRows(rows, pagination) {
  const pageSize = Number(pagination.pageSize || 25);
  const page = Math.max(1, Math.min(Number(pagination.page || 1), totalPages(rows.length, pageSize)));
  const start = (page - 1) * pageSize;
  return rows.slice(start, start + pageSize);
}

function pageRange(totalRows, pagination) {
  if (!totalRows) return '0 - 0';
  const start = (Number(pagination.page || 1) - 1) * Number(pagination.pageSize || 25) + 1;
  const end = Math.min(start + Number(pagination.pageSize || 25) - 1, totalRows);
  return `${numberLabel(start)} - ${numberLabel(end)}`;
}

function textValue(value, fallback = '-') {
  const text = String(value ?? '').trim();
  return text || fallback;
}

function normalizeRackCode(value) {
  let candidate = value;
  if (candidate && typeof candidate === 'object') {
    candidate = candidate.value
      || candidate.kode_rak
      || candidate.location
      || candidate.rak
      || candidate.label
      || candidate.raw?.kode_rak
      || candidate.raw?.location
      || '';
  }

  const text = String(candidate ?? '').trim();
  const compact = text.toUpperCase().replace(/[^A-Z0-9]/g, '');
  const matched = compact.match(/G\d+R\d+L\d+K\d+N\d+/);
  return matched ? matched[0] : compact;
}

function isRackCode(value) {
  return /^G\d+R\d+L\d+K\d+N\d+$/.test(normalizeRackCode(value));
}

function rackCodeFromText(value) {
  const code = normalizeRackCode(value);
  return isRackCode(code) ? code : '';
}

function firstRackCode(...values) {
  for (const value of values) {
    const code = normalizeRackCode(value);
    if (code) return code;
  }
  return '';
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function currentDateLabel() {
  return new Date().toLocaleString('id-ID', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });
}

function rackQrValue(row) {
  const code = normalizeRackCode(row?.kode_rak || row?.location || row?.rak);
  return code ? `BUDIMAS-WMS|LOCATION|${code}` : '';
}

function placementRackCode(row) {
  return normalizeRackCode(row?.kode_rak || row?.location || row?.rak);
}

function rowProductCode(row) {
  return textValue(row?.kode_barang || row?.KodeBarang || row?.KodeStok || row?.kode_sku || row?.product_code || row?.productCode, '');
}

function rowProductName(row) {
  return textValue(row?.nama_barang || row?.NamaBarang || row?.nama_produk || row?.product_name || row?.productName, '');
}

function rowQtyKarton(row) {
  return Number(row?.qty_karton ?? row?.qty_ct ?? row?.QtyCT ?? row?.karton ?? row?.quantity_ct ?? 0);
}

function rowQtyPcs(row) {
  return Number(row?.qty_pcs ?? row?.qty ?? row?.QtyPC ?? row?.QtyPCS ?? row?.required_quantity ?? row?.quantity_pc ?? 0);
}

function rowPerUnit(row) {
  const candidates = [
    row?.uom3_factor,
    row?.uom2_factor,
    row?.per_unit,
    row?.isi_per_karton,
    row?.isiperkarton,
    row?.karton_to_pcs,
    row?.uom_karton_ratio,
    row?.raw?.per_unit,
  ];
  const perUnit = candidates
    .map((value) => Number(value))
    .find((value) => Number.isFinite(value) && value > 0);
  return Math.max(Math.trunc(perUnit || 1), 1);
}

function normalizedUomLevels(row) {
  const levels = [
    { level: 3, name: row?.uom3_nama, factor: Number(row?.uom3_factor) },
    { level: 2, name: row?.uom2_nama, factor: Number(row?.uom2_factor) },
    { level: 1, name: row?.uom1_nama || 'PCS', factor: Number(row?.uom1_factor || 1) },
  ].filter((item) => item.name && Number.isFinite(item.factor) && item.factor > 0)
    .sort((a, b) => b.factor - a.factor);

  // Jika dua nama UOM memiliki faktor yang sama, jumlah fisiknya tidak dapat
  // dibedakan. Prioritaskan level tertinggi agar label tidak menampilkan
  // konversi atau qty yang duplikat (mis. CT dan Karton sama-sama 100 PCS).
  const seenFactors = new Set();
  return levels.filter((item) => {
    if (seenFactors.has(item.factor)) return false;
    seenFactors.add(item.factor);
    return true;
  });
}

function formatUomQuantity(value, row) {
  let remaining = Math.max(Math.trunc(Number(value) || 0), 0);
  const parts = [];
  normalizedUomLevels(row).forEach((uom, index, levels) => {
    const qty = index === levels.length - 1 ? remaining : Math.floor(remaining / uom.factor);
    if (qty > 0 || (!parts.length && index === levels.length - 1)) parts.push(`${numberLabel(qty)} ${uom.name}`);
    remaining -= qty * uom.factor;
  });
  return parts.join(' + ') || `${numberLabel(value)} PCS`;
}

function rowQuantityBreakdown(row) {
  const totalPcs = Math.max(Math.trunc(rowQtyPcs(row)), 0);
  let remaining = totalPcs;
  const levels = normalizedUomLevels(row);
  const parts = levels.map((uom, index) => {
    const qty = index === levels.length - 1 ? remaining : Math.floor(remaining / uom.factor);
    remaining -= qty * uom.factor;
    return { ...uom, qty };
  });
  const highest = parts[0] || { name: 'PCS', factor: 1, qty: totalPcs };

  return {
    totalPcs,
    parts,
    perUnit: highest.factor,
    qtyKarton: highest.qty,
    qtyPcs: parts.find((item) => item.level === 1)?.qty ?? 0,
  };
}

function uomConversionLabel(row) {
  return normalizedUomLevels(row)
    .filter((item) => item.level !== 1 && item.factor > 1)
    .map((item) => `1 ${item.name} = ${numberLabel(item.factor)} ${row?.uom1_nama || 'PCS'}`)
    .join(' | ') || '1 PCS = 1 PCS';
}

function rowBatch(row) {
  return textValue(row?.batch_number || row?.batch_no || row?.batch || row?.Batch, '');
}

function normalizeWmsDate(value) {
  const raw = textValue(value, '');
  if (!raw || raw.startsWith('1900-01-01')) return '';

  const iso = raw.match(/\d{4}-\d{2}-\d{2}/)?.[0];
  if (iso) return iso;

  const timestamp = Date.parse(raw);
  if (Number.isNaN(timestamp)) return '';
  return new Date(timestamp).toISOString().slice(0, 10);
}

function palletProductLabel(row = {}) {
  // produk_isi is calculated from positive pallet-detail rows by the API.
  // Fall back to the configured product only when the pallet is empty.
  return row.produk_isi || row.nama_barang || row.kode_barang || 'Umum';
}

function rowExpired(row) {
  return normalizeWmsDate(
    row?.expired_date
    || row?.ExpiredDate
    || row?.tanggal_expired
    || row?.TanggalExpired
    || row?.expiry_date
    || row?.expired
    || row?.Expired
  );
}

function itemQrValue(row, fallbackRack = '') {
  const productCode = rowProductCode(row);
  const rackCode = placementRackCode(row) || fallbackRack;
  if (!productCode || !rackCode) return '';
  return [
    productCode,
    rackCode,
    rowQtyPcs(row),
    0,
    0,
    rowProductName(row),
    rowBatch(row),
    rowExpired(row)
  ].map((part) => String(part ?? '').trim()).join(';');
}

function parseScanPayload(payload) {
  const text = String(payload || '').trim();
  const parts = text.split(';').map((part) => part.trim());
  const locationMatch = text.match(/BUDIMAS-WMS\|LOCATION\|([^|;\s]+)/i) || text.match(/\bG\d+R\d+L\d+K\d+N\d+\b/i);
  const semicolonRack = parts.length > 1 && /^G\d+R\d+L\d+K\d+N\d+$/i.test(parts[1]) ? parts[1] : '';
  // A pallet code is not always prefixed PLT- in legacy WMS data.  The
  // pallet QR contract has nine segments, whereas an item QR has eight.
  const hasPalletCode = parts.length >= 9 && Boolean(parts[2]);
  const qtyIndex = hasPalletCode ? 3 : 2;
  const nameIndex = hasPalletCode ? 6 : 5;
  const batchIndex = hasPalletCode ? 7 : 6;
  const expiredIndex = hasPalletCode ? 8 : 7;
  return {
    raw: text,
    productCode: parts.length > 1 ? parts[0] : '',
    rackCode: locationMatch?.[1] || semicolonRack || '',
    palletCode: hasPalletCode ? parts[2] : '',
    // Pallet labels encode CT at segment 3 and the remainder PCS at segment
    // 5. Keep both values; conversion to base PCS belongs to the selected
    // stock row because only it knows the product conversion factor.
    qtyCt: hasPalletCode ? Number(parts[3] || 0) : 0,
    qtyPc: hasPalletCode ? Number(parts[5] || 0) : 0,
    qty: Number(parts[qtyIndex] || 0),
    productName: parts[nameIndex] || '',
    batch: parts[batchIndex] || '',
    expired: parts[expiredIndex] || ''
  };
}

function rowsForRack(code, rows = placementRows.value) {
  const targetCode = normalizeRackCode(code);
  if (!targetCode) return [];
  return (Array.isArray(rows) ? rows : []).filter((row) => placementRackCode(row) === targetCode);
}

async function qrDataUrl(value) {
  return QRCode.toDataURL(String(value || ''), {
    errorCorrectionLevel: 'M',
    margin: 1,
    width: 260,
    color: {
      dark: '#0f172a',
      light: '#ffffff'
    }
  });
}

function openPrintDocument(title, bodyHtml, css = '') {
  const printWindow = window.open('', '_blank', 'width=1120,height=820');
  if (!printWindow) {
    setError(new Error('Popup cetak diblokir browser.'), 'Popup cetak diblokir browser. Izinkan popup lalu ulangi cetak.');
    return;
  }

  printWindow.document.write(`
    <!doctype html>
    <html lang="id">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>${escapeHtml(title)}</title>
        <style>
          * { box-sizing: border-box; }
          body {
            margin: 0;
            background: #e2e8f0;
            color: #0f172a;
            font-family: Arial, Helvetica, sans-serif;
          }
          .toolbar {
            position: sticky;
            top: 0;
            z-index: 10;
            display: flex;
            justify-content: space-between;
            gap: 12px;
            padding: 12px 16px;
            background: #0f172a;
            color: white;
          }
          .toolbar button {
            border: 0;
            border-radius: 8px;
            background: #65a30d;
            color: white;
            cursor: pointer;
            font-weight: 700;
            padding: 9px 14px;
          }
          .sheet {
            padding: 14mm;
          }
          .page-break {
            break-after: page;
            page-break-after: always;
          }
          .page-break:last-child {
            break-after: auto;
            page-break-after: auto;
          }
          ${css}
          @media print {
            body { background: white; }
            .toolbar { display: none; }
            .sheet { padding: 0; }
          }
        </style>
      </head>
      <body>
        <div class="toolbar">
          <strong>${escapeHtml(title)}</strong>
          <button onclick="window.print()">Cetak</button>
        </div>
        <main class="sheet">${bodyHtml}</main>
      </body>
    </html>
  `);
  printWindow.document.close();
  printWindow.focus();
  setTimeout(() => printWindow.print(), 350);
}

function thermalLabelPageCss() {
  return `
    @page { size: 100mm 150mm; margin: 0; }
    *,
    *::before,
    *::after {
      box-sizing: border-box;
    }
    html,
    body {
      margin: 0;
      min-width: 0;
    }
    .sheet {
      padding: 0;
    }
    @media screen {
      .sheet {
        width: 100%;
        padding: 8mm;
        display: grid;
        justify-content: center;
        gap: 8mm;
      }
    }
    @media print {
      html,
      body {
        width: 100mm;
        height: auto;
        margin: 0;
        overflow: visible;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }
      .sheet {
        width: 100mm;
        margin: 0;
        padding: 0;
      }
    }
  `;
}

function rackLabelCss() {
  return `
    ${thermalLabelPageCss()}
    .labels {
      display: block;
      width: 100mm;
    }
    .rack-label {
      width: 94mm;
      height: 144mm;
      margin: 3mm auto;
      border: 0.8mm solid #0f172a;
      border-radius: 2mm;
      background: white;
      padding: 4mm;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      break-inside: avoid;
      break-after: page;
      page-break-after: always;
    }
    .rack-label:last-child {
      break-after: auto;
      page-break-after: auto;
    }
    .qr-box {
      width: 54mm;
      height: 54mm;
      flex: 0 0 54mm;
      align-self: center;
      border: 0.5mm solid #cbd5e1;
      border-radius: 2mm;
      padding: 2mm;
      text-align: center;
    }
    .qr-box img {
      display: block;
      width: 100%;
      height: 100%;
      object-fit: contain;
    }
    .rack-code {
      margin-top: 3mm;
      font-size: 18pt;
      font-weight: 900;
      line-height: 1.05;
      letter-spacing: 0;
      text-align: center;
      overflow-wrap: anywhere;
    }
    .label-title {
      margin-top: 1.5mm;
      font-size: 7.5pt;
      font-weight: 800;
      letter-spacing: 0.12em;
      line-height: 1.1;
      text-transform: uppercase;
      color: #475569;
      text-align: center;
    }
    .meta {
      margin-top: auto;
      display: grid;
      gap: 1mm;
      font-size: 7.5pt;
    }
    .meta-row {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 2mm;
      min-height: 5.5mm;
      border-bottom: 0.3mm solid #e2e8f0;
      padding-bottom: 0.75mm;
    }
    .meta-row span:first-child {
      color: #64748b;
      font-weight: 700;
    }
    .meta-row span:last-child {
      max-width: 64%;
      font-weight: 800;
      line-height: 1.12;
      text-align: right;
      overflow: hidden;
      overflow-wrap: anywhere;
    }
    @media print {
      .rack-label {
        border-radius: 0;
      }
    }
  `;
}

function contentLabelCss() {
  return `
    ${thermalLabelPageCss()}
    .content-labels {
      width: 100mm;
      background: white;
    }
    .content-item-label {
      width: 94mm;
      height: 144mm;
      margin: 3mm auto;
      border: 0.8mm solid #0f172a;
      border-radius: 2mm;
      background: #ffffff;
      color: #0f172a;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      padding: 3.5mm;
      break-inside: avoid;
      break-after: page;
      page-break-after: always;
    }
    .content-item-label:last-child {
      break-after: auto;
      page-break-after: auto;
    }
    .content-item-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 4mm;
      min-height: 8mm;
      border-bottom: 0.35mm solid #cbd5e1;
      padding-bottom: 1.5mm;
    }
    .content-item-kicker {
      font-size: 7pt;
      font-weight: 900;
      letter-spacing: 0.12em;
      line-height: 1.15;
      text-transform: uppercase;
      color: #475569;
    }
    .content-item-rack-pill {
      max-width: 46mm;
      border: 0.35mm solid #0f172a;
      border-radius: 999px;
      padding: 1mm 2.2mm;
      font-size: 7.2pt;
      font-weight: 900;
      line-height: 1.1;
      text-align: center;
      overflow-wrap: anywhere;
    }
    .content-item-qr {
      width: 46mm;
      height: 46mm;
      align-self: center;
      flex: 0 0 46mm;
      display: flex;
      align-items: center;
      justify-content: center;
      margin-top: 2.5mm;
      border: 0.45mm solid #cbd5e1;
      border-radius: 2mm;
      padding: 1.75mm;
    }
    .content-item-qr img {
      display: block;
      width: 100%;
      height: auto;
      image-rendering: crisp-edges;
    }
    .content-item-code {
      margin-top: 2mm;
      font-size: 15pt;
      font-weight: 900;
      line-height: 1;
      text-align: center;
      overflow-wrap: anywhere;
    }
    .content-item-name {
      margin-top: 1.25mm;
      min-height: 7mm;
      max-height: 7mm;
      font-size: 8.5pt;
      font-weight: 800;
      line-height: 1.18;
      text-align: center;
      color: #334155;
      overflow: hidden;
      overflow-wrap: anywhere;
    }
    .content-item-meta {
      margin-top: auto;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 1mm;
      border-top: 0.35mm solid #cbd5e1;
      padding-top: 1.5mm;
      font-size: 7pt;
    }
    .content-item-meta-row {
      min-height: 7.25mm;
      border: 0.25mm solid #cbd5e1;
      border-radius: 1.5mm;
      padding: 0.9mm 1.25mm;
    }
    .content-item-meta-row span {
      display: block;
      font-size: 5.3pt;
      font-weight: 800;
      letter-spacing: 0.08em;
      line-height: 1;
      text-transform: uppercase;
      color: #64748b;
    }
    .content-item-meta-row strong {
      display: block;
      margin-top: 0.75mm;
      font-size: 7.8pt;
      font-weight: 900;
      line-height: 1.05;
      color: #0f172a;
      overflow-wrap: anywhere;
    }
    .content-item-meta-row.conversion strong {
      font-size: 6.7pt;
      line-height: 1.08;
    }
    .content-item-meta-row.wide {
      grid-column: 1 / -1;
    }
    .content-empty {
      width: 94mm;
      height: 144mm;
      margin: 3mm auto;
      border: 0.6mm dashed #94a3b8;
      padding: 30mm 8mm;
      text-align: center;
      color: #64748b;
      font-weight: 800;
    }
    @media screen {
      .content-item-label,
      .content-empty {
        box-shadow: 0 8px 28px rgba(15, 23, 42, 0.18);
      }
    }
    @media print {
      .content-item-label {
        border-color: #000000;
        border-radius: 0;
      }
    }
  `;
}

function itemLabelCss() {
  return `
    ${thermalLabelPageCss()}
    .item-label {
      width: 94mm;
      height: 144mm;
      margin: 3mm auto;
      border: 0.8mm solid #0f172a;
      border-radius: 2mm;
      background: white;
      padding: 4mm;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      break-inside: avoid;
      break-after: page;
      page-break-after: always;
    }
    .item-label:last-child {
      break-after: auto;
      page-break-after: auto;
    }
    .item-qr-box {
      width: 52mm;
      height: 52mm;
      flex: 0 0 52mm;
      align-self: center;
      border: 0.5mm solid #cbd5e1;
      border-radius: 2mm;
      padding: 2mm;
      text-align: center;
    }
    .item-qr-box img {
      display: block;
      width: 100%;
      height: 100%;
      object-fit: contain;
    }
    .item-title {
      margin-top: 2mm;
      font-size: 7pt;
      font-weight: 900;
      letter-spacing: 0.12em;
      line-height: 1.1;
      text-transform: uppercase;
      color: #475569;
      text-align: center;
    }
    .item-code {
      margin-top: 1.25mm;
      font-size: 16pt;
      font-weight: 900;
      line-height: 1;
      text-align: center;
      overflow-wrap: anywhere;
    }
    .item-name {
      margin-top: 1.25mm;
      max-height: 7mm;
      overflow: hidden;
      font-size: 8.5pt;
      font-weight: 700;
      line-height: 1.18;
      color: #334155;
      text-align: center;
      overflow-wrap: anywhere;
    }
    .item-meta {
      margin-top: auto;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 1mm;
      border-top: 0.35mm solid #cbd5e1;
      padding-top: 1.5mm;
      font-size: 7pt;
    }
    .item-meta-row {
      min-height: 7.25mm;
      border: 0.25mm solid #cbd5e1;
      border-radius: 1.5mm;
      padding: 0.9mm 1.25mm;
    }
    .item-meta-row.wide {
      grid-column: 1 / -1;
    }
    .item-meta-row span {
      display: block;
      color: #64748b;
      font-size: 5.3pt;
      font-weight: 800;
      letter-spacing: 0.08em;
      line-height: 1;
      text-transform: uppercase;
    }
    .item-meta-row strong {
      display: block;
      margin-top: 0.75mm;
      color: #0f172a;
      font-size: 7.8pt;
      font-weight: 900;
      line-height: 1.08;
      overflow: hidden;
      overflow-wrap: anywhere;
    }
    @media print {
      .item-label {
        border-radius: 0;
      }
    }
  `;
}

function buildRackLabelHtml(label) {
  return `
    <article class="rack-label">
      <div class="qr-box">
        <img src="${label.qr}" alt="QR ${escapeHtml(label.kode_rak)}" />
      </div>
      <div>
        <div class="label-title">QR Rak Gudang</div>
        <div class="rack-code">${escapeHtml(label.kode_rak)}</div>
        <div class="meta">
          <div class="meta-row"><span>Tipe</span><span>${escapeHtml(label.type_rak)}</span></div>
          <div class="meta-row"><span>Status</span><span>${escapeHtml(label.status_rak)}</span></div>
          <div class="meta-row"><span>Posisi</span><span>${escapeHtml(label.posisi)}</span></div>
          <div class="meta-row"><span>Cabang</span><span>${escapeHtml(label.id_cabang)}</span></div>
          <div class="meta-row"><span>Dicetak</span><span>${escapeHtml(label.printed_at)}</span></div>
        </div>
      </div>
    </article>
  `;
}

function buildContentLabelHtml(group) {
  const rowsHtml = group.rows.length
    ? group.rows.map((row) => {
      const kodeRak = placementRackCode(row) || group.kode_rak || '-';
      const kodeBarang = rowProductCode(row) || '-';
      const namaBarang = rowProductName(row) || '-';
      const quantity = rowQuantityBreakdown(row);
      const batch = rowBatch(row) || '-';
      const expired = rowExpired(row) || '-';
      return `
        <article class="content-item-label">
          <header class="content-item-header">
            <div class="content-item-kicker">QR Barang<br />WMS</div>
            <div class="content-item-rack-pill">${escapeHtml(kodeRak)}</div>
          </header>
          <div class="content-item-qr">
            ${row.qr ? `<img src="${row.qr}" alt="QR ${escapeHtml(kodeBarang)}" />` : ''}
          </div>
          <div class="content-item-code">${escapeHtml(kodeBarang)}</div>
          <div class="content-item-name">${escapeHtml(namaBarang)}</div>
          <div class="content-item-meta">
            <div class="content-item-meta-row wide">
              <span>Jumlah UOM</span>
              <strong>${escapeHtml(formatUomQuantity(quantity.totalPcs, row))}</strong>
            </div>
            <div class="content-item-meta-row">
              <span>Total ${escapeHtml(row.uom1_nama || 'PCS')}</span>
              <strong>${numberLabel(quantity.totalPcs)} ${escapeHtml(row.uom1_nama || 'PCS')}</strong>
            </div>
            <div class="content-item-meta-row conversion">
              <span>Total / Konversi</span>
              <strong>${escapeHtml(uomConversionLabel(row))}</strong>
            </div>
            <div class="content-item-meta-row wide">
              <span>Batch / Expired</span>
              <strong>${escapeHtml(batch)} / ${escapeHtml(expired)}</strong>
            </div>
          </div>
        </article>
      `;
    }).join('')
    : '<div class="content-empty">Belum ada isi pallet/rak yang tercatat.</div>';

  return `
    <section class="content-labels">
      ${rowsHtml}
    </section>
  `;
}

function buildItemLabelHtml(label) {
  return `
    <article class="item-label">
      <div class="item-qr-box">
        <img src="${label.qr}" alt="QR ${escapeHtml(label.kode_barang)}" />
      </div>
      <div>
        <div class="item-title">${escapeHtml(label.title || 'QR Barang WMS')}</div>
        <div class="item-code">${escapeHtml(label.kode_barang)}</div>
        <div class="item-name">${escapeHtml(label.nama_barang)}</div>
        <div class="item-meta">
          <div class="item-meta-row wide"><span>Rak</span><strong>${escapeHtml(label.kode_rak)}</strong></div>
          <div class="item-meta-row wide"><span>Jumlah UOM</span><strong>${escapeHtml(label.uom_quantity)}</strong></div>
          <div class="item-meta-row"><span>Total ${escapeHtml(label.uom_name)}</span><strong>${escapeHtml(numberLabel(label.qty_pcs))}</strong></div>
          <div class="item-meta-row"><span>Batch</span><strong>${escapeHtml(label.batch)}</strong></div>
          <div class="item-meta-row wide"><span>Expired</span><strong>${escapeHtml(label.expired)}</strong></div>
        </div>
      </div>
    </article>
  `;
}

async function printRackQrLabels(rows = rackRows.value) {
  const rowsToPrint = rows.filter((row) => rackQrValue(row));
  if (!rowsToPrint.length) {
    setError(new Error('Data rak belum tersedia untuk dicetak.'), 'Data rak belum tersedia untuk dicetak.');
    return;
  }

  try {
    const printedAt = currentDateLabel();
    const labels = await Promise.all(rowsToPrint.map(async (row) => ({
      kode_rak: textValue(row.kode_rak),
      qr: await qrDataUrl(rackQrValue(row)),
      type_rak: textValue(row.type_rak || row.shelf_type),
      status_rak: textValue(row.status_rak),
      posisi: rackPositionLabel(row),
      id_cabang: textValue(row.id_cabang),
      printed_at: printedAt
    })));

    openPrintDocument(
      `Cetak QR Rak (${labels.length} label)`,
      `<section class="labels">${labels.map((label) => buildRackLabelHtml(label)).join('')}</section>`,
      rackLabelCss()
    );
  } catch (error) {
    setError(error, 'QR rak belum bisa dibuat.');
  }
}

async function fetchPlacementsForRack(code) {
  const rackCode = normalizeRackCode(code);
  if (!rackCode) return [];

  const localRows = rowsForRack(rackCode);
  try {
    const response = await getWmsPlacements({
      kode_rak: rackCode,
      id_cabang: rackBranchId(),
      limit: 5000,
    });
    return rowsForRack(rackCode, payloadRows(response));
  } catch (error) {
    if (localRows.length) return localRows;
    throw error;
  }
}

async function printRackContentLabels(rackCodes = []) {
  const explicitCodes = rackCodes.map((code) => normalizeRackCode(code)).filter(Boolean);
  const codes = explicitCodes.length
    ? Array.from(new Set(explicitCodes))
    : Array.from(new Set(placementRows.value.map((row) => placementRackCode(row)).filter(Boolean)));

  if (!codes.length) {
    setError(new Error('Pilih rak atau muat data penempatan terlebih dahulu.'), 'Pilih rak atau muat data penempatan terlebih dahulu.');
    return;
  }

  try {
    const printedAt = currentDateLabel();
    const groups = await Promise.all(codes.map(async (code) => {
      const rows = await fetchPlacementsForRack(code);
      const printableRows = await Promise.all(rows.map(async (row) => {
        const qrPayload = itemQrValue(row, code);
        return {
          ...row,
          qr_payload: qrPayload,
          qr: qrPayload ? await qrDataUrl(qrPayload) : ''
        };
      }));
      return {
        kode_rak: code,
        rows: printableRows,
        total_pcs: printableRows.reduce((total, row) => total + rowQtyPcs(row), 0),
        printed_at: printedAt
      };
    }));
    const printableGroups = groups.filter((group) => group.rows.length);
    if (!printableGroups.length) {
      setError(new Error('Isi rak belum tersedia untuk dicetak.'), `Isi rak belum tersedia untuk dicetak. Kode dicek: ${codes.join(', ') || '-'}.`);
      return;
    }

    openPrintDocument(
      `Cetak Isi Pallet (${printableGroups.length} rak)`,
      printableGroups.map((group) => buildContentLabelHtml(group)).join(''),
      contentLabelCss()
    );
  } catch (error) {
    setError(error, 'Daftar isi pallet/rak belum bisa dicetak.');
  }
}

function printSelectedRackQr() {
  const row = selectedRackRow.value || (rackForm.kode_rak ? { ...rackForm } : null);
  printRackQrLabels(row ? [row] : []);
}

function printSelectedRackContents() {
  const code = placementModalOpen.value
    ? placementForm.kode_rak
    : rackModalOpen.value
      ? rackForm.kode_rak
      : firstRackCode(placementFilterRackCode.value, selectedRackRow.value?.kode_rak, rackForm.kode_rak, placementForm.kode_rak);
  printRackContentLabels(code ? [code] : []);
}

function printPlacementFilterContents() {
  printRackContentLabels(placementFilterRackCode.value ? [placementFilterRackCode.value] : []);
}

function printSelectedPlacementItemQr() {
  const row = selectedPlacementRow.value || (placementForm.kode_barang && placementForm.kode_rak ? { ...placementForm } : null);
  if (!row) {
    setError(new Error('Pilih penempatan terlebih dahulu.'), 'Pilih satu penempatan atau isi form penempatan untuk mencetak QR barang.');
    return;
  }
  printItemQrLabel(row);
}

function printChosenRackQrLabels() {
  printRackQrLabels(selectedPrintRackRows.value);
}

function printChosenRackContents() {
  printRackContentLabels(selectedPrintRackCodeList.value);
}

async function printItemQrLabel(row, options = {}) {
  const fallbackRack = options.rack || '';
  const payload = options.payload || itemQrValue(row, fallbackRack);
  if (!payload) {
    setError(new Error('Payload QR barang belum lengkap.'), 'Kode barang dan rak wajib tersedia untuk membuat QR barang.');
    return;
  }
  const parsed = parseScanPayload(payload);
  const label = {
    title: options.title || 'QR Barang WMS',
    kode_barang: rowProductCode(row) || parsed.productCode,
    nama_barang: rowProductName(row) || parsed.productName || '-',
    kode_rak: placementRackCode(row) || parsed.rackCode || fallbackRack,
    qty_pcs: rowQtyPcs(row) || parsed.qty,
    uom_name: textValue(row?.uom1_nama || row?.uom1_name || 'PCS'),
    uom_quantity: formatUomQuantity(rowQtyPcs(row) || parsed.qty, row),
    batch: rowBatch(row) || parsed.batch || '-',
    expired: rowExpired(row) || parsed.expired || '-',
    payload,
    qr: await qrDataUrl(payload)
  };
  openPrintDocument(
    `Cetak QR Barang ${label.kode_barang}`,
    buildItemLabelHtml(label),
    itemLabelCss()
  );
}

function qrDocumentPart(value, fallback = '-') {
  const normalized = String(value ?? '').trim().replace(/\|/g, '/');
  return normalized || fallback;
}

function buildDocumentQrHtml(label) {
  return `
    <article class="document-label">
      <div class="document-type">${escapeHtml(label.type_label)}</div>
      <div class="document-qr"><img src="${label.qr}" alt="QR ${escapeHtml(label.primary)}" /></div>
      <div class="document-primary">${escapeHtml(label.primary)}</div>
      <dl class="document-meta">
        ${label.meta.map((item) => `
          <div><dt>${escapeHtml(item.label)}</dt><dd>${escapeHtml(item.value)}</dd></div>
        `).join('')}
      </dl>
      <div class="document-warning">QR DOKUMEN - BUKAN QR PALLET, PRODUK, ATAU LOKASI RAK</div>
      <div class="document-payload">${escapeHtml(label.payload)}</div>
    </article>
  `;
}

function documentQrCss() {
  return `
    @page { size: A4 portrait; margin: 12mm; }
    html, body { min-width: 0; }
    .sheet {
      display: flex;
      justify-content: center;
      align-items: flex-start;
      min-height: 100%;
      padding: 12mm;
    }
    .document-label {
      width: 90mm;
      max-width: 100%;
      margin: 0;
      padding: 5mm;
      border: 1.2mm solid #0f172a;
      border-radius: 3mm;
      background: #fff;
      text-align: center;
      break-inside: avoid;
      page-break-inside: avoid;
    }
    .document-type { font-size: 18pt; font-weight: 900; letter-spacing: 0; }
    .document-qr img { width: 54mm; height: 54mm; margin: 3mm auto 2mm; display: block; }
    .document-primary { font-size: 14pt; font-weight: 900; overflow-wrap: anywhere; }
    .document-meta { margin: 3mm 0 0; text-align: left; }
    .document-meta div { display: grid; grid-template-columns: 29mm 1fr; gap: 2mm; padding: 1.3mm 0; border-bottom: .25mm solid #cbd5e1; }
    .document-meta dt { color: #475569; font-size: 8pt; font-weight: 700; text-transform: uppercase; }
    .document-meta dd { margin: 0; font-size: 9pt; font-weight: 800; overflow-wrap: anywhere; }
    .document-warning { margin-top: 3mm; padding: 2mm; border: .4mm solid #b45309; color: #92400e; font-size: 7.5pt; font-weight: 900; }
    .document-payload { margin-top: 2mm; color: #64748b; font-family: monospace; font-size: 6.5pt; overflow-wrap: anywhere; }
    @media print {
      html, body { width: auto; min-width: 0; margin: 0; }
      .sheet { display: block; min-height: 0; }
      .document-label { margin: 0 auto; }
    }
  `;
}

async function printIncomingDocumentQr(row = null) {
  const nota = qrDocumentPart(row?.Nota || row?.nota || incomingDocument.value?.nota || filters.incomingNota, '');
  if (!nota) {
    setError(new Error('Nota incoming belum dipilih.'), 'Isi atau pilih nota incoming terlebih dahulu.');
    return;
  }
  const payload = `BUDIMAS-WMS|INCOMING|${nota}`;
  const itemCount = incomingItems.value.filter((item) => String(item.Nota || item.nota || '') === nota).length || incomingItems.value.length;
  const label = {
    type_label: 'QR NOTA INCOMING',
    primary: nota,
    payload,
    qr: await qrDataUrl(payload),
    meta: [
      { label: 'Jenis', value: 'Dokumen penerimaan barang' },
      { label: 'Jumlah item', value: numberLabel(itemCount) },
      { label: 'Dicetak', value: currentDateLabel() }
    ]
  };
  openPrintDocument(`QR Nota Incoming ${nota}`, buildDocumentQrHtml(label), documentQrCss());
}

async function printPickingDocumentQr(row = null) {
  const document = row || pickingDocument.value || {};
  const idPicking = qrDocumentPart(document.id_picking || document.wms_task_id, '');
  const kodeRute = qrDocumentPart(document.kode_rute, 'TANPA-RUTE');
  const nota = qrDocumentPart(document.nota || document.no_faktur || document.no_order || filters.pickingNota, '');
  if (!idPicking || !nota) {
    setError(new Error('Dokumen picking belum terbentuk.'), 'Muat nota picking terlebih dahulu agar ID picking dapat dibuat.');
    return;
  }
  const payload = `BUDIMAS-WMS|PICKING|${idPicking}|${kodeRute}|${nota}`;
  const label = {
    type_label: 'QR DOKUMEN PICKING',
    primary: `Picking #${idPicking}`,
    payload,
    qr: await qrDataUrl(payload),
    meta: [
      { label: 'Nota', value: nota },
      { label: 'Kode rute', value: kodeRute },
      { label: 'Nama rute', value: qrDocumentPart(document.nama_rute) },
      { label: 'Dicetak', value: currentDateLabel() }
    ]
  };
  openPrintDocument(`QR Picking ${idPicking}`, buildDocumentQrHtml(label), documentQrCss());
}

async function printManifestDocumentQr(row = null) {
  const manifest = row || {};
  const noManifest = qrDocumentPart(
    manifest.NoManifest || manifest.no_manifest || manifest.manifest_no,
    ''
  );
  if (!noManifest) {
    setError(new Error('Nomor manifest belum tersedia.'), 'Muat data manifest terlebih dahulu sebelum mencetak QR/Barcode.');
    return;
  }

  // Contract ini dibaca langsung oleh WMS Mobile pada QC Karantina. Parser
  // Android juga menerima manifest lama yang tidak diawali MNF-, karena nomor
  // manifest selalu berada pada segmen terakhir.
  const payload = `BUDIMAS-WMS|MANIFEST|${noManifest}`;
  const details = Array.isArray(manifest.details) ? manifest.details : [];
  const notes = [...new Set(
    details
      .map((detail) => qrDocumentPart(detail?.Nota || detail?.nota, ''))
      .filter(Boolean)
  )];
  const helpers = Array.isArray(manifest.helpers)
    ? manifest.helpers
      .map((helper) => qrDocumentPart(helper?.nama || helper?.helper_name, ''))
      .filter(Boolean)
      .join(', ')
    : '';
  const label = {
    type_label: 'QR / BARCODE MANIFEST',
    primary: noManifest,
    payload,
    qr: await qrDataUrl(payload),
    meta: [
      { label: 'Jenis', value: 'Dokumen manifest loading WMS' },
      { label: 'Driver', value: qrDocumentPart(manifest.driver || details[0]?.DriverRencana) },
      { label: 'Kendaraan', value: qrDocumentPart(manifest.vehicle_no || manifest.NoKendaraan) },
      { label: 'Helper', value: helpers || '-' },
      { label: 'Nota', value: notes.join(', ') || '-' },
      { label: 'Jumlah item', value: numberLabel(manifest.total_item ?? details.length) },
      { label: 'Dicetak', value: currentDateLabel() }
    ]
  };
  openPrintDocument(`QR Manifest ${noManifest}`, buildDocumentQrHtml(label), documentQrCss());
}

function movePage(pagination, direction, maxPage) {
  pagination.page = Math.max(1, Math.min(maxPage, Number(pagination.page || 1) + direction));
}

async function changeIncomingPage(direction) {
  movePage(incomingPagination, direction, incomingTotalPages.value);
  if (incomingServerPaged.value) {
    await loadIncoming({ keepPage: true });
  }
}

async function changePickingPage(direction) {
  movePage(pickingPagination, direction, pickingTotalPages.value);
  if (pickingServerPaged.value) {
    await loadPickingDraft({ keepPage: true });
  }
}

function resetPage(pagination) {
  pagination.page = 1;
}

watch(
  () => route.meta?.wmsSection,
  (section) => {
    if (section === 'racks') {
      activeTab.value = 'racks';
      return;
    }

    if (section === 'pallets') {
      activeTab.value = 'pallets';
      return;
    }

    if (section === 'placements') {
      activeTab.value = 'placements';
      return;
    }

    if (dedicatedSections.has(activeTab.value)) {
      activeTab.value = 'inventory';
    }
  },
  { immediate: true }
);

watch(
  () => [rackForm.gudang, rackForm.rak, rackForm.level, rackForm.kolom, rackForm.nomor_urut],
  () => {
    if (!rackForm.id && !loading.nextRack) {
      rackForm.kode_rak = formatRackCodeFromForm(rackForm);
    }
  }
);

watch(() => rackForm.level, () => {
  const level = Math.max(Number(rackForm.level ?? 0), 0);
  if (level >= 2 && rackForm.type_rak !== 'Titipan') {
    rackForm.type_rak = 'Titipan';
  } else if (level <= 1 && rackForm.type_rak === 'Titipan') {
    rackForm.type_rak = 'Tetap';
  } else if (rackForm.type_rak === 'Lorong' && level !== 0) {
    rackForm.type_rak = 'Tetap';
  }
});

watch(() => rackForm.type_rak, () => {
  if (rackForm.type_rak === 'Titipan' && Number(rackForm.level ?? 0) < 2) {
    rackForm.level = 2;
  } else if (rackForm.type_rak === 'Lorong' && Number(rackForm.level ?? 0) !== 0) {
    rackForm.level = 0;
  } else if (rackForm.type_rak === 'Tetap' && Number(rackForm.level ?? 0) > 1) {
    rackForm.level = 1;
  }
});

watch(() => rackForm.mix_mode, () => {
  if (rackForm.mix_mode !== 'mixed_group') {
    rackForm.id_principal_group = '';
  } else {
    loadPrincipalGroups();
  }
});

watch(() => incomingPagination.pageSize, () => {
  resetPage(incomingPagination);
  if (incomingServerPaged.value && incomingItems.value.length) {
    loadIncoming({ keepPage: true });
  }
});
watch(() => pickingPagination.pageSize, () => {
  resetPage(pickingPagination);
  if (pickingServerPaged.value && pickingItems.value.length) {
    loadPickingDraft({ keepPage: true });
  }
});

function setFeedback(message) {
  feedback.value = message;
  errorMessage.value = '';
}

function setError(error, fallback) {
  errorMessage.value = normalizeError(error, fallback);
  feedback.value = '';
}

function transferRowKey(row, index = 0) {
  return row?.wms_stock_rak_id || [row?.kode_barang, row?.kode_rak_asal, row?.batch, index].filter(Boolean).join('|') || index;
}

function normalizeTransferRow(row = {}) {
  const availableQty = Number(row.qty || 0);
  return {
    ...row,
    selected: false,
    transfer_qty: availableQty,
    // Filled only by a pallet QR scan. A blank value is valid when one exact
    // pallet candidate exists; two or more candidates require a scan before
    // the transfer can be confirmed.
    pallet_code: ''
  };
}

function clampTransferQty(row) {
  const availableQty = Math.max(Number(row.qty || 0), 0);
  const requestedQty = Math.max(Number(row.transfer_qty || 0), 0);
  row.transfer_qty = Math.min(requestedQty, availableQty);
  if (row.transfer_qty <= 0) {
    row.selected = false;
  }
}

function toggleTransferRow(row, checked) {
  row.selected = checked;
  if (checked && Number(row.transfer_qty || 0) <= 0) {
    row.transfer_qty = Number(row.qty || 0);
  }
}

function toggleAllTransferRows(checked) {
  transferRows.value.forEach((row) => {
    toggleTransferRow(row, checked);
  });
}

function resetTransferSelection() {
  transferRows.value.forEach((row) => {
    row.selected = false;
    row.transfer_qty = Number(row.qty || 0);
    row.pallet_code = '';
  });
}

function isIncomingProcessed(row) {
  return Boolean(row?.SudahProses) || String(row?.status || '').toUpperCase() === 'DONE';
}

function isPickingScanned(row) {
  return ['PICKED', 'CHECKED', 'LOADED'].includes(String(row?.status_draft || row?.status || '').toUpperCase());
}

function openFlowStep(step) {
  activeTab.value = step.tab;
  setFeedback(`${step.title}: buka tab ${tabs.find((tab) => tab.key === step.tab)?.label || step.tab}.`);
}

function resetPrincipalGroupForm() {
  Object.assign(principalGroupForm, createPrincipalGroupForm());
}

function openCreatePrincipalGroupModal() {
  resetPrincipalGroupForm();
  principalGroupModalOpen.value = true;
  Promise.all([loadPrincipals(), loadPrincipalGroups()]);
}

function editPrincipalGroup(row) {
  Object.assign(principalGroupForm, {
    id: row.id || '',
    kode_group: row.kode_group || '',
    nama_group: row.nama_group || '',
    principal_ids: Array.isArray(row.principal_ids) ? row.principal_ids.map((item) => String(item)) : [],
    active: row.active !== false,
    notes: row.notes || ''
  });
  principalGroupModalOpen.value = true;
  loadPrincipals();
}

async function savePrincipalGroup() {
  if (!principalGroupForm.kode_group || !principalGroupForm.nama_group) {
    setError(new Error('Kode dan nama group wajib diisi.'), 'Kode dan nama group wajib diisi.');
    return;
  }
  loading.action = true;
  try {
    const payload = {
      ...principalGroupForm,
      principal_ids: principalGroupForm.principal_ids.map((item) => Number(item)).filter(Boolean)
    };
    if (principalGroupForm.id) {
      await updateWmsPrincipalGroup(principalGroupForm.id, payload);
      setFeedback(`Group principal ${principalGroupForm.kode_group} berhasil diperbarui.`);
    } else {
      await createWmsPrincipalGroup(payload);
      setFeedback(`Group principal ${principalGroupForm.kode_group} berhasil ditambahkan.`);
    }
    principalGroupModalOpen.value = false;
    resetPrincipalGroupForm();
    await Promise.all([loadPrincipalGroups(), loadRacks()]);
  } catch (error) {
    setError(error, 'Group principal belum berhasil disimpan.');
  } finally {
    loading.action = false;
  }
}

async function removePrincipalGroup() {
  if (!principalGroupForm.id) return;
  const confirmed = window.confirm(`Hapus/nonaktifkan group ${principalGroupForm.kode_group}?`);
  if (!confirmed) return;
  loading.action = true;
  try {
    await deleteWmsPrincipalGroup(principalGroupForm.id);
    setFeedback(`Group principal ${principalGroupForm.kode_group} berhasil diproses.`);
    principalGroupModalOpen.value = false;
    resetPrincipalGroupForm();
    await Promise.all([loadPrincipalGroups(), loadRacks()]);
  } catch (error) {
    setError(error, 'Group principal belum berhasil dihapus.');
  } finally {
    loading.action = false;
  }
}

function resetRackForm() {
  Object.assign(rackForm, createRackForm());
  selectedRackId.value = '';
  loadNextRackCode();
}

function openCreateRackModal() {
  resetRackForm();
  rackModalOpen.value = true;
  loadPrincipalGroups();
}

function editRack(row) {
  selectedRackId.value = row.id;
  Object.assign(rackForm, {
    id: row.id,
    id_cabang: row.id_cabang || 5,
    gudang: row.gudang ?? '',
    rak: row.rak ?? '',
    level: row.level ?? '',
    kolom: row.kolom ?? '',
    nomor_urut: row.nomor_urut ?? '',
    kode_rak: row.kode_rak || '',
    type_rak: row.type_rak || 'Tetap',
    max_qty_pcs: row.max_qty_pcs ?? 0,
    max_qty_karton: row.max_qty_karton ?? 0,
    mix_mode: row.mix_mode || 'single_principal',
    id_principal_group: row.id_principal_group ? String(row.id_principal_group) : '',
    status_rak: row.status_rak || 'Kosong',
    active: row.active !== false
  });
  rackModalOpen.value = true;
  loadPrincipalGroups();
  setFeedback(`Rak ${row.kode_rak} siap diedit.`);
}

async function loadNextRackCode() {
  if (rackForm.id) {
    return;
  }
  loading.nextRack = true;
  try {
    const response = await getWmsNextRackCode({ id_cabang: rackForm.id_cabang || 5 });
    const payload = unwrapResponse(response)?.data || unwrapResponse(response) || {};
    Object.assign(rackForm, {
      id_cabang: payload.id_cabang || rackForm.id_cabang || 5,
      gudang: payload.gudang ?? '',
      rak: payload.rak ?? '',
      level: payload.level ?? '',
      kolom: payload.kolom ?? '',
      nomor_urut: payload.nomor_urut ?? '',
      kode_rak: payload.kode_rak || rackForm.kode_rak
    });
  } catch (error) {
    setError(error, 'Kode rak berikutnya belum bisa dibuat otomatis.');
  } finally {
    loading.nextRack = false;
  }
}

async function loadRacks() {
  loading.racks = true;
  try {
    const response = await getWmsRacks({
      search: filters.rackSearch || undefined,
      type_rak: filters.rackType || undefined,
      status_rak: filters.rackStatus || undefined,
      active: filters.rackActive || undefined,
      id_cabang: rackBranchId(),
      limit: 500
    });
    rackRows.value = payloadRows(response);
    rackTotal.value = Number(response?.data?.total ?? rackRows.value.length);
    if (!rackForm.id && !rackForm.kode_rak) {
      loadNextRackCode();
    }
    setFeedback(`Master rak memuat ${rackRows.value.length.toLocaleString('id-ID')} baris.`);
  } catch (error) {
    rackRows.value = [];
    rackTotal.value = 0;
    setError(error, 'Master rak belum bisa dimuat.');
  } finally {
    loading.racks = false;
  }
}

function rackBranchId() {
  const candidate = placementForm.id_cabang || rackForm.id_cabang || filters.idCabang || 5;
  return Number(candidate) || 5;
}

async function searchRackOptions(keyword = '', options = {}) {
  const requestVersion = ++rackSearchRequestVersion;
  const normalizedKeyword = String(keyword || '').trim();
  loading.rackOptions = true;
  try {
    const response = await getWmsRacks({
      search: normalizedKeyword || undefined,
      id_cabang: Number(options.idCabang) || rackBranchId(),
      type_rak: options.typeRak || undefined,
      active: 'true',
      limit: 250
    });
    if (requestVersion !== rackSearchRequestVersion) return;
    remoteRackRows.value = payloadRows(response);
  } catch (error) {
    if (requestVersion !== rackSearchRequestVersion) return;
    remoteRackRows.value = [];
    setError(error, 'Pencarian rak belum bisa dimuat.');
  } finally {
    if (requestVersion === rackSearchRequestVersion) loading.rackOptions = false;
  }
}

async function searchQuarantineRackOptions(keyword = '', row) {
  if (!row) return;
  const requestVersion = Number(row.target_rack_request_version || 0) + 1;
  row.target_rack_request_version = requestVersion;
  row.target_rack_loading = true;
  const idCabang = Number(row.id_cabang) || rackBranchId();
  const search = String(keyword || '').trim();
  try {
    const responses = await Promise.all(
      ['Tetap', 'Lorong'].map((typeRak) => getWmsRacks({
        search: search || undefined,
        id_cabang: idCabang,
        type_rak: typeRak,
        active: 'true',
        limit: 250
      }))
    );
    if (requestVersion !== row.target_rack_request_version) return;
    const resultMap = new Map();
    responses.flatMap((response) => payloadRows(response)).forEach((rack) => {
      const code = normalizeRackCode(rack?.kode_rak);
      if (code) resultMap.set(code, rack);
    });
    row.target_rack_options = Array.from(resultMap.values());
  } catch (error) {
    if (requestVersion !== row.target_rack_request_version) return;
    row.target_rack_options = [];
    setError(error, 'Pencarian rak GOOD belum bisa dimuat.');
  } finally {
    if (requestVersion === row.target_rack_request_version) row.target_rack_loading = false;
  }
}

async function loadPrincipalGroups() {
  loading.principalGroups = true;
  try {
    const response = await getWmsPrincipalGroups({ active: 'true' });
    principalGroupRows.value = payloadRows(response);
  } catch (error) {
    principalGroupRows.value = [];
    setError(error, 'Group principal WMS belum bisa dimuat.');
  } finally {
    loading.principalGroups = false;
  }
}

async function loadPrincipals() {
  try {
    const response = await getPrincipals();
    principalRows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    principalRows.value = [];
    setError(error, 'Daftar principal belum bisa dimuat.');
  }
}

async function saveRack() {
  if (!rackForm.kode_rak) {
    setError(new Error('Kode rak wajib diisi.'), 'Kode rak wajib diisi.');
    return;
  }
  loading.action = true;
  try {
    const payload = { ...rackForm };
    if (rackForm.id) {
      await updateWmsRack(rackForm.id, payload);
      setFeedback(`Rak ${rackForm.kode_rak} berhasil diperbarui.`);
    } else {
      await createWmsRack(payload);
      setFeedback(`Rak ${rackForm.kode_rak} berhasil ditambahkan.`);
    }
    Object.assign(rackForm, createRackForm());
    selectedRackId.value = '';
    rackModalOpen.value = false;
    await Promise.all([loadRacks(), loadInventory()]);
    await loadNextRackCode();
  } catch (error) {
    setError(error, 'Rak belum berhasil disimpan.');
  } finally {
    loading.action = false;
  }
}

async function removeRack() {
  if (!rackForm.id) {
    return;
  }
  const force = !placementRows.value.some((item) => item.kode_rak === rackForm.kode_rak);
  const confirmed = window.confirm(`Nonaktifkan rak ${rackForm.kode_rak}?`);
  if (!confirmed) {
    return;
  }
  loading.action = true;
  try {
    await deleteWmsRack(rackForm.id, { force });
    setFeedback(`Rak ${rackForm.kode_rak} berhasil diproses.`);
    rackModalOpen.value = false;
    resetRackForm();
    await Promise.all([loadRacks(), loadInventory(), loadPlacements()]);
  } catch (error) {
    setError(error, 'Rak belum berhasil dihapus/dinonaktifkan.');
  } finally {
    loading.action = false;
  }
}

function resetPalletForm() {
  Object.assign(palletForm, createPalletForm());
  selectedPalletId.value = '';
  loadNextPalletCode();
}

function openCreatePalletModal() {
  resetPalletForm();
  palletModalOpen.value = true;
  loadProductOptions();
}

function editPallet(row) {
  selectedPalletId.value = row.id;
  Object.assign(palletForm, {
    id: row.id,
    id_cabang: row.id_cabang || 5,
    kode_pallet: row.kode_pallet || '',
    tipe_pallet: row.tipe_pallet || 'Standard',
    berat_kosong_kg: row.berat_kosong_kg ?? 0,
    max_berat_kg: row.max_berat_kg ?? 0,
    max_qty_pcs: row.max_qty_pcs ?? 0,
    max_qty_karton: row.max_qty_karton ?? 0,
    selectedProductId: row.id_produk ? String(row.id_produk) : '',
    id_produk: row.id_produk || '',
    kode_barang: row.kode_barang || '',
    nama_barang: row.nama_barang || '',
    default_qty_pcs: row.default_qty_pcs ?? 0,
    default_qty_karton: row.default_qty_karton ?? 0,
    status_pallet: row.status_pallet || 'Kosong',
    active: row.active !== false,
    notes: row.notes || ''
  });
  palletModalOpen.value = true;
  if (row.kode_barang || row.nama_barang) {
    loadProductOptions(row.kode_barang || row.nama_barang);
  }
  setFeedback(`Pallet ${row.kode_pallet} siap diedit.`);
}

function selectPalletProduct(value) {
  palletForm.selectedProductId = value || '';

  if (!value) {
    palletForm.id_produk = '';
    palletForm.kode_barang = '';
    palletForm.nama_barang = '';
    return;
  }

  const option = productOptions.value.find((product) => String(product.value) === String(value));
  if (!option) {
    return;
  }

  palletForm.id_produk = option.value;
  palletForm.kode_barang = option.code || option.raw?.kode_sku || option.raw?.kode_barang || option.raw?.kode_ean || option.value;
  palletForm.nama_barang = option.name || option.raw?.nama || option.raw?.nama_produk || option.raw?.nama_barang || palletForm.nama_barang;
}

async function loadNextPalletCode() {
  if (palletForm.id) {
    return;
  }
  loading.nextPallet = true;
  try {
    const response = await getWmsNextPalletCode({ id_cabang: palletForm.id_cabang || 5 });
    const payload = unwrapResponse(response)?.data || unwrapResponse(response) || {};
    Object.assign(palletForm, {
      id_cabang: payload.id_cabang || palletForm.id_cabang || 5,
      kode_pallet: payload.kode_pallet || palletForm.kode_pallet
    });
  } catch (error) {
    setError(error, 'Kode pallet berikutnya belum bisa dibuat otomatis.');
  } finally {
    loading.nextPallet = false;
  }
}

async function loadPallets() {
  loading.pallets = true;
  try {
    const response = await getWmsPallets({
      id_cabang: rackBranchId(),
      search: filters.palletSearch || undefined,
      status: filters.palletStatus || undefined,
      active: filters.palletActive || undefined
    });
    palletRows.value = payloadRows(response);
    if (!palletForm.id && !palletForm.kode_pallet) {
      loadNextPalletCode();
    }
    setFeedback(`Master pallet memuat ${palletRows.value.length.toLocaleString('id-ID')} baris.`);
  } catch (error) {
    palletRows.value = [];
    setError(error, 'Master pallet belum bisa dimuat.');
  } finally {
    loading.pallets = false;
  }
}

async function savePallet() {
  if (!palletForm.kode_pallet) {
    setError(new Error('Kode pallet wajib diisi.'), 'Kode pallet wajib diisi.');
    return;
  }
  loading.action = true;
  try {
    const payload = { ...palletForm };
    if (palletForm.id) {
      await updateWmsPallet(palletForm.id, payload);
      setFeedback(`Pallet ${palletForm.kode_pallet} berhasil diperbarui.`);
    } else {
      await createWmsPallet(payload);
      setFeedback(`Pallet ${palletForm.kode_pallet} berhasil ditambahkan.`);
    }
    Object.assign(palletForm, createPalletForm());
    selectedPalletId.value = '';
    palletModalOpen.value = false;
    await loadPallets();
    await loadNextPalletCode();
  } catch (error) {
    setError(error, 'Pallet belum berhasil disimpan.');
  } finally {
    loading.action = false;
  }
}

async function removePallet() {
  if (!palletForm.id) {
    return;
  }
  const confirmed = window.confirm(`Nonaktifkan pallet ${palletForm.kode_pallet}?`);
  if (!confirmed) {
    return;
  }
  loading.action = true;
  try {
    await deleteWmsPallet(palletForm.id);
    setFeedback(`Pallet ${palletForm.kode_pallet} berhasil dinonaktifkan.`);
    palletModalOpen.value = false;
    resetPalletForm();
    await loadPallets();
  } catch (error) {
    setError(error, 'Pallet belum berhasil dinonaktifkan.');
  } finally {
    loading.action = false;
  }
}

function resetPlacementForm() {
  Object.assign(placementForm, createPlacementForm());
  selectedPlacementId.value = '';
  placementItems.value = [createPlacementItem()];
}

function setPlacementItems(rows = [{}]) {
  placementItems.value = rows.map((row) => createPlacementItem(row));
}

function selectPlacementItemProduct(item, value) {
  item.selectedProductId = value || '';

  if (!value) {
    item.id_produk = '';
    item.kode_barang = '';
    item.nama_barang = '';
    return;
  }

  const option = productOptions.value.find((product) => String(product.value) === String(value));
  if (!option) {
    return;
  }

  item.id_produk = option.value;
  item.kode_barang = option.code || option.raw?.kode_sku || option.raw?.kode_barang || option.raw?.kode_ean || option.value;
  item.nama_barang = option.name || option.raw?.nama || option.raw?.nama_produk || option.raw?.nama_barang || item.nama_barang;
}

function addPlacementItem() {
  placementItems.value = [...placementItems.value, createPlacementItem()];
  loadProductOptions();
}

function removePlacementItem(uid) {
  if (placementItems.value.length <= 1) {
    placementItems.value = [createPlacementItem()];
    return;
  }

  placementItems.value = placementItems.value.filter((item) => item.uid !== uid);
}

function placementItemPayload(item) {
  return {
    ...placementForm,
    id_produk: item.id_produk || item.selectedProductId || undefined,
    kode_barang: item.kode_barang,
    nama_barang: item.nama_barang,
    qty_pcs: Number(item.qty_pcs || 0),
    qty_karton: Number(item.qty_karton || 0),
    qty_pieces: Number(item.qty_pieces || 0),
    batch_number: item.batch_number || '',
    expired_date: normalizeWmsDate(item.expired_date) || undefined
  };
}

function openCreatePlacementModal() {
  resetPlacementForm();
  placementModalOpen.value = true;
  loadProductOptions();
}

function editPlacement(row) {
  selectedPlacementId.value = row.id;
  Object.assign(placementForm, {
    id: row.id,
    id_produk: row.id_produk || '',
    id_cabang: row.id_cabang || 5,
    kode_rak: row.kode_rak || '',
    kode_barang: row.kode_barang || '',
    nama_barang: row.nama_barang || '',
    qty_pcs: row.qty_pcs ?? 0,
    qty_karton: row.qty_karton ?? 0,
    qty_pieces: 0,
    batch_number: row.batch_number || '',
    // Placement API returns an ISO calendar date.  Keep aliases from legacy
    // incoming rows too, so a recorded expiry is always visible in Edit.
    expired_date: rowExpired(row),
    status: row.status || 'READY'
  });
  setPlacementItems([placementForm]);
  placementModalOpen.value = true;
  loadProductOptions(placementForm.kode_barang || '');
  setFeedback(`Penempatan ${row.kode_barang} di ${row.kode_rak} siap diedit.`);
}

let placementLoadSequence = 0;
async function loadPlacements(silent = false) {
  const sequence = ++placementLoadSequence;
  loading.placements = true;
  try {
    const [response, report] = await Promise.all([getWmsPlacements({
      search: filters.placementSearch || undefined,
      kode_rak: filters.placementRack || undefined,
      status: filters.placementStatus || undefined,
      id_cabang: rackBranchId(),
      limit: 5000,
    }), getStockReport({id_cabang:rackBranchId()})]);
    if (sequence !== placementLoadSequence) return;
    placementRows.value = payloadRows(response);
    placementReport.value = payloadRows(report);
    if (!placementRows.value.some((row) => String(row.id) === String(selectedPlacementId.value))) {
      selectedPlacementId.value = '';
    }
    if (silent !== true) setFeedback(`Penempatan barang memuat ${placementRows.value.length.toLocaleString('id-ID')} baris.`);
  } catch (error) {
    if (sequence !== placementLoadSequence || silent === true) return;
    placementRows.value = [];
    placementReport.value = [];
    setError(error, 'Penempatan barang belum bisa dimuat.');
  } finally {
    if (sequence === placementLoadSequence) loading.placements = false;
  }
}

async function loadProductOptions(search = '') {
  const requestId = ++productLoadSequence;
  const keyword = String(search || '').trim();
  loading.products = true;
  try {
    let optionError = null;
    let rows = [];

    try {
      const response = await getWmsProductOptions({
        limit: PRODUCT_OPTION_FETCH_LIMIT,
        search: keyword || undefined
      });
      rows = normalizeList(unwrapResponse(response));
    } catch (error) {
      optionError = error;
    }

    // A successful empty WMS search really means no matching product.  Only
    // use the old endpoint if a rolling deployment has not exposed the WMS
    // search endpoint yet; otherwise a fallback page could show unrelated
    // first-100 products after an exact search.
    if (optionError) {
      const fallbackResponse = await getProducts({
        search: keyword || undefined,
        limit: PRODUCT_OPTION_FETCH_LIMIT
      });
      rows = normalizeList(unwrapResponse(fallbackResponse));
    }

    if (!rows.length && optionError) {
      throw optionError;
    }

    if (requestId === productLoadSequence) {
      productRows.value = rows;
    }
  } catch (error) {
    if (requestId === productLoadSequence) {
      productRows.value = [];
    }
    setError(error, 'Daftar produk belum bisa dimuat untuk penempatan rak.');
  } finally {
    if (requestId === productLoadSequence) {
      loading.products = false;
    }
  }
}

function searchProductOptions(keyword) {
  loadProductOptions(keyword);
}

async function savePlacement() {
  const itemsToSave = placementItems.value.filter((item) => item.kode_barang || item.selectedProductId);

  if (!placementForm.kode_rak || !itemsToSave.length) {
    setError(new Error('Kode rak dan kode barang wajib diisi.'), 'Kode rak dan kode barang wajib diisi.');
    return;
  }

  const incompleteItem = itemsToSave.find((item) => !item.kode_barang);
  if (incompleteItem) {
    setError(new Error('Pilih barang dari daftar untuk setiap baris.'), 'Pilih barang dari daftar untuk setiap baris.');
    return;
  }

  loading.action = true;
  try {
    if (placementForm.id) {
      const payload = placementItemPayload(itemsToSave[0]);
      await updateWmsPlacement(placementForm.id, payload);
      setFeedback(`Penempatan ${payload.kode_barang} berhasil diperbarui.`);
    } else {
      for (const item of itemsToSave) {
        await createWmsPlacement(placementItemPayload(item));
      }
      setFeedback(`${itemsToSave.length} baris berhasil ditempatkan di ${placementForm.kode_rak}. Produk, batch, dan expired yang sama otomatis digabung.`);
    }
    resetPlacementForm();
    placementModalOpen.value = false;
    await Promise.all([loadPlacements(), loadInventory(), loadRacks(), loadTransactions()]);
  } catch (error) {
    setError(error, 'Penempatan barang belum berhasil disimpan.');
  } finally {
    loading.action = false;
  }
}

async function removePlacement() {
  if (!placementForm.id) {
    return;
  }
  const confirmed = window.confirm(`Hapus penempatan ${placementForm.kode_barang} dari ${placementForm.kode_rak}?`);
  if (!confirmed) {
    return;
  }
  loading.action = true;
  try {
    await deleteWmsPlacement(placementForm.id);
    setFeedback(`Penempatan ${placementForm.kode_barang} berhasil dihapus.`);
    placementModalOpen.value = false;
    resetPlacementForm();
    await Promise.all([loadPlacements(), loadInventory(), loadRacks(), loadTransactions()]);
  } catch (error) {
    setError(error, 'Penempatan barang belum berhasil dihapus.');
  } finally {
    loading.action = false;
  }
}

async function loadInventory() {
  loading.inventory = true;
  try {
    const response = await getWmsInventory({
      search: filters.inventorySearch || undefined,
      status: filters.inventoryStatus || undefined
    });
    inventoryRows.value = payloadRows(response);
    setFeedback(`Inventory WMS memuat ${inventoryRows.value.length.toLocaleString('id-ID')} baris.`);
  } catch (error) {
    inventoryRows.value = [];
    setError(error, 'Inventory WMS belum bisa dimuat.');
  } finally {
    loading.inventory = false;
  }
}

async function lookupBarcode() {
  if (!filters.barcodeProduct) {
    barcodeRows.value = [];
    return;
  }
  loading.barcode = true;
  try {
    const response = await getWmsInventoryBarcode(filters.barcodeProduct);
    barcodeRows.value = payloadRows(response);
    setFeedback(`Barcode ${filters.barcodeProduct} memuat ${barcodeRows.value.length.toLocaleString('id-ID')} baris.`);
  } catch (error) {
    barcodeRows.value = [];
    setError(error, 'Barcode barang belum bisa dicek.');
  } finally {
    loading.barcode = false;
  }
}

async function loadTransactions() {
  loading.transactions = true;
  try {
    const response = await getWmsTransactions({
      search: filters.transactionSearch || undefined,
      type_filter: filters.transactionType || undefined
    });
    transactionRows.value = payloadRows(response);
    setFeedback(`Transaksi WMS memuat ${transactionRows.value.length.toLocaleString('id-ID')} baris.`);
  } catch (error) {
    transactionRows.value = [];
    setError(error, 'Transaksi WMS belum bisa dimuat.');
  } finally {
    loading.transactions = false;
  }
}

const pickingIncidents = ref([]);
async function loadPickingIncidents(silent = false) {
  try { pickingIncidents.value = payloadRows(await getPickingIncidents()); }
  catch (error) { if (!silent) setError(error, 'Laporan kendala picking belum bisa dimuat.'); }
}
async function closePickingIncident(row) {
  if (!row.resolutionNote?.trim()) return;
  loading.action = true;
  try {
    const result = unwrapResponse(await resolvePickingIncident(row.id, row.resolutionNote));
    setFeedback(result.message);
    await loadPickingIncidents();
  } catch (error) { setError(error, 'Laporan belum bisa ditutup.'); }
  finally { loading.action = false; }
}

async function loadCheckerPending() {
  loading.checker = true;
  try {
    const response = await getWmsCheckerPending();
    checkerRows.value = payloadRows(response).map((task) => ({ ...task, details: (task.details || []).map((detail) => ({
      ...detail, actualQty: '', actualCondition: '', actualNote: detail.checker_note || ''
    })) }));
    setFeedback(`Checker memuat ${checkerRows.value.length.toLocaleString('id-ID')} draft.`);
  } catch (error) {
    checkerRows.value = [];
    setError(error, 'Daftar checker belum bisa dimuat.');
  } finally {
    loading.checker = false;
  }
}

async function submitChecker(row) {
  if (!filters.checkerName.trim()) {
    setError(new Error('Nama checker wajib diisi.'), 'Isi nama checker sebelum konfirmasi.');
    return;
  }
  loading.action = true;
  try {
    const response = await confirmWmsChecker({
      task_id: row.id,
      checker_name: filters.checkerName,
      dock_code: filters.checkerDock,
      items: (row.details || []).map((detail) => ({
        detail_id: detail.id,
        checked_quantity: detail.actualQty === '' ? null : detail.actualQty,
        condition: detail.actualCondition,
        note: detail.actualNote
      }))
    });
    const result = unwrapResponse(response) || {};
    await loadCheckerPending();
    setFeedback(result.message || `Checker ${row.nota || row.id} selesai.`);
  } catch (error) {
    setError(error, 'Konfirmasi checker belum berhasil.');
  } finally {
    loading.action = false;
  }
}

async function loadReadyToLoad() {
  loading.loading = true;
  try {
    // Active loading uses ShipmentLoadingPanel with an explicit schedule selection.
    readyToLoadRows.value = [];
    return;
  } catch (error) {
    readyToLoadRows.value = [];
    setError(error, 'Ready load belum bisa dimuat.');
  } finally {
    loading.loading = false;
  }
}

async function submitLoading(action = 'complete') {
  if (!canSubmitScheduledLoading.value) {
    setError(
      new Error('Jadwal loading belum lengkap.'),
      'Pilih grup jadwal yang lengkap. Driver, armada, dan helper harus ditetapkan pada Penjadwalan Armada.'
    );
    return;
  }
  loading.action = true;
  try {
    const response = await processWmsLoading({ items: selectedReadyToLoadRows.value, action });
    const result = unwrapResponse(response) || {};
    if (action === 'start') {
      await loadReadyToLoad();
      setFeedback(result.message);
      return;
    }
    const totalItems = Number(result.total_item || result.manifest_item_count || 0);
    const autoIncluded = Number(result.auto_included_item_count || 0);
    const itemSummary = totalItems > 0
      ? ` (${totalItems.toLocaleString('id-ID')} item${autoIncluded > 0 ? `; ${autoIncluded.toLocaleString('id-ID')} item satu nota ikut dimuat` : ''})`
      : '';
    const assignment = selectedLoadingScheduleGroup.value;
    setFeedback(`Loading tersimpan: ${result.no_manifest || 'manifest WMS'}${itemSummary}. ${assignment?.driver || 'Driver'} · ${assignment?.armada || 'armada'}.`);
    await loadReadyToLoad();
  } catch (error) {
    setError(error, 'Loading belum berhasil diproses.');
  } finally {
    loading.action = false;
  }
}

async function loadManifest() {
  loading.dropping = true;
  try {
    const response = await searchWmsManifest({ kode_driver: filters.manifestDriver || undefined });
    manifestRows.value = payloadRows(response);
    const availableManifestNos = new Set(manifestTableRows.value.map(manifestNumber).filter(Boolean));
    if (!availableManifestNos.has(String(selectedManifestNo.value || '').trim())) {
      selectedManifestNo.value = manifestTableRows.value.map(manifestNumber).find(Boolean) || '';
    }
    setFeedback(`Manifest memuat ${manifestRows.value.length.toLocaleString('id-ID')} grup.`);
  } catch (error) {
    manifestRows.value = [];
    selectedManifestNo.value = '';
    setError(error, 'Manifest belum bisa dimuat.');
  } finally {
    loading.dropping = false;
  }
}

async function dropToQuarantine(row) {
  loading.action = true;
  try {
    const response = await dropWmsManifestToQuarantine({
      no_manifest: row.NoManifest,
      items: row.details || [],
      reason: filters.deliveryNotes || 'Gagal kirim / retur dari toko'
    });
    const result = unwrapResponse(response) || {};
    setFeedback(result.message || `Manifest ${row.NoManifest} masuk karantina.`);
    await Promise.all([loadManifest(), loadQuarantine()]);
  } catch (error) {
    setError(error, 'Manifest belum berhasil masuk karantina.');
  } finally {
    loading.action = false;
  }
}

async function completeDelivery(row) {
  loading.action = true;
  try {
    const response = await completeWmsDelivery({
      no_manifest: row.NoManifest,
      received_by: filters.deliveryReceiver,
      notes: filters.deliveryNotes
    });
    const result = unwrapResponse(response) || {};
    setFeedback(result.message || `Manifest ${row.NoManifest} selesai dikirim.`);
    await loadManifest();
  } catch (error) {
    setError(error, 'Pengiriman belum berhasil diselesaikan.');
  } finally {
    loading.action = false;
  }
}

async function loadQuarantine() {
  loading.qc = true;
  try {
    const response = await getWmsQuarantineOpen({
      search: filters.quarantineSearch || undefined,
      status: 'OPEN'
    });
    quarantineRows.value = payloadRows(response).map((row) => ({
      ...row,
      batch_number: rowBatch(row),
      expired_date: rowExpired(row),
      qty_good_input: Number(row.qty_pcs || 0),
      qty_bad_input: 0,
      no_expiry_input: false,
      target_rack_input: row.target_rack || '',
      target_rack_options: [],
      target_rack_loading: false,
      target_rack_request_version: 0
    }));
    setFeedback(`QC karantina memuat ${quarantineRows.value.length.toLocaleString('id-ID')} item.`);
  } catch (error) {
    quarantineRows.value = [];
    setError(error, 'Daftar QC karantina belum bisa dimuat.');
  } finally {
    loading.qc = false;
  }
}

async function submitQuarantineQc(row) {
  const qtyGood = Number(row.qty_good_input || 0);
  const qtyBad = Number(row.qty_bad_input || 0);
  if (qtyGood > 0 && !String(row.target_rack_input || '').trim()) {
    setError(new Error('Rak GOOD wajib diisi.'), 'Pilih rak Tetap atau Lorong untuk barang GOOD.');
    return;
  }
  loading.action = true;
  try {
    const response = await processWmsQuarantineQc({
      quarantine_id: row.id,
      qty_good: qtyGood,
      qty_bad: qtyBad,
      target_rack: row.target_rack_input,
      batch_number: rowBatch(row),
      expired_date: rowExpired(row),
      qc_name: filters.qcName,
      ...(['MANUAL_REQUIRED', 'MULTIPLE'].includes(row.lot_status) ? {
        lot_confirmed: true,
        no_expiry: row.no_expiry_input,
        expired_date: row.no_expiry_input ? null : rowExpired(row)
      } : {})
    });
    const result = unwrapResponse(response) || {};
    setFeedback(result.message || `QC ${row.kode_barang} selesai.`);
    await Promise.all([loadQuarantine(), loadManifest(), loadInventory()]);
  } catch (error) {
    setError(error, 'QC karantina belum berhasil disimpan.');
  } finally {
    loading.action = false;
  }
}

async function loadTransferStocks(options = {}) {
  loading.transfer = true;
  try {
    const response = await getWmsTemporaryStocks({
      kode_barang: filters.transferProduct || undefined,
      kode_rak: filters.transferSourceRack || undefined
    });
    transferRows.value = payloadRows(response).map((row) => normalizeTransferRow(row));
    transferConfirmOpen.value = false;
    if (!options.silent) {
      setFeedback(`Transfer rak memuat ${transferRows.value.length.toLocaleString('id-ID')} stok titipan.`);
    }
  } catch (error) {
    transferRows.value = [];
    setError(error, 'Stok sementara transfer belum bisa dimuat.');
  } finally {
    loading.transfer = false;
  }
}

async function applyTransferTargetScan() {
  const parsed = parseScanPayload(filters.transferTargetScanPayload);
  if (!parsed.rackCode) {
    setError(new Error('QR tujuan tidak memuat kode rak.'), 'Scan QR rak tujuan Tetap terlebih dahulu.');
    return;
  }
  filters.transferTargetRack = parsed.rackCode;
  if (parsed.productCode) {
    filters.transferProduct = parsed.productCode;
    await loadTransferStocks({ silent: true });
    setFeedback(`Tujuan transfer ${parsed.rackCode} untuk ${parsed.productCode} siap diverifikasi.`);
    return;
  }
  transferRows.value = [];
  setFeedback(`Tujuan transfer ${parsed.rackCode} sudah diset. Scan QR barang/pallet untuk memilih stok titipan asal.`);
}

async function applyTransferItemScan() {
  const parsed = parseScanPayload(filters.transferItemScanPayload);
  if (!parsed.productCode) {
    setError(new Error('QR barang tidak memuat kode barang.'), 'Scan QR barang/pallet yang berisi kode barang.');
    return;
  }
  if (!filters.transferTargetRack) {
    setError(new Error('Rak tujuan belum discan.'), 'Scan QR rak tujuan terlebih dahulu sebelum scan barang.');
    return;
  }
  if (parsed.rackCode) {
    filters.transferSourceRack = parsed.rackCode;
  }
  filters.transferProduct = parsed.productCode;

  const findMatchingRow = () => transferRows.value.find((item) => {
    const sameProduct = String(item.kode_barang || '').toUpperCase() === parsed.productCode.toUpperCase();
    const sameRack = parsed.rackCode
      ? String(item.kode_rak_asal || '').toUpperCase() === parsed.rackCode.toUpperCase()
      : true;
    const sameBatch = parsed.batch
      ? String(item.batch || '').toUpperCase() === parsed.batch.toUpperCase()
      : true;
    return sameProduct && sameRack && sameBatch;
  });

  // A location-only target scan intentionally clears the old list. Reload
  // the source line from the item QR so the documented scan-only flow works
  // without requiring an extra, hidden manual “Muat Stok” action.
  let row = findMatchingRow();
  if (!row) {
    await loadTransferStocks({ silent: true });
    row = findMatchingRow();
  }

  if (!row) {
    setError(new Error('Stok titipan tidak cocok dengan QR barang.'), `Stok titipan ${parsed.productCode} ${parsed.rackCode || ''} belum ada di daftar transfer.`);
    return;
  }

  row.selected = true;
  const scannedQtyPcs = parsed.palletCode
    ? Math.max(Number(parsed.qtyCt || 0), 0) * Math.max(Number(row.per_unit || 1), 1) + Math.max(Number(parsed.qtyPc || 0), 0)
    : Number(parsed.qty || 0);
  row.transfer_qty = scannedQtyPcs > 0
    ? Math.min(scannedQtyPcs, Number(row.qty || 0))
    : Number(row.qty || 0);
  if (parsed.palletCode) {
    row.pallet_code = parsed.palletCode;
  }
  const needsPalletScan = Number(row.pallet_count || 0) > 1 && !row.pallet_code;
  setFeedback(
    needsPalletScan
      ? `Produk ${parsed.productCode} cocok, tetapi ada beberapa pallet di rak ini. Scan QR pallet sebelum konfirmasi transfer.`
      : `QR ${parsed.palletCode ? 'pallet' : 'barang'} ${parsed.productCode} cocok. Item dipilih untuk transfer ke ${filters.transferTargetRack}.`
  );
}

function openTransferConfirmation() {
  if (!filters.transferTargetRack) {
    setError(new Error('Pilih rak Tetap tujuan transfer terlebih dahulu.'), 'Pilih rak Tetap tujuan transfer terlebih dahulu.');
    return;
  }

  if (!selectedTransferRows.value.length) {
    setError(new Error('Pilih minimal satu item titipan untuk ditransfer.'), 'Pilih minimal satu item titipan untuk ditransfer.');
    return;
  }

  const invalidRow = selectedTransferRows.value.find((row) => Number(row.transfer_qty || 0) > Number(row.qty || 0));
  if (invalidRow) {
    setError(new Error(`Qty transfer ${invalidRow.kode_barang} melebihi saldo rak titipan.`), `Qty transfer ${invalidRow.kode_barang} melebihi saldo rak titipan.`);
    return;
  }

  const ambiguousPalletRow = selectedTransferRows.value.find((row) =>
    Number(row.pallet_count || 0) > 1 && !String(row.pallet_code || '').trim()
  );
  if (ambiguousPalletRow) {
    setError(
      new Error(`Pallet ${ambiguousPalletRow.kode_barang} belum dipindai.`),
      `Rak ${ambiguousPalletRow.kode_rak_asal || '-'} memiliki beberapa pallet ${ambiguousPalletRow.kode_barang}. Scan QR pallet fisik yang dipindahkan terlebih dahulu.`
    );
    return;
  }

  transferConfirmOpen.value = true;
}

async function submitTransfer() {
  loading.action = true;
  try {
    const response = await confirmWmsTransfer({
      kode_barang: filters.transferProduct,
      target_rak: filters.transferTargetRack,
      items: selectedTransferRows.value.map((row) => ({
        ...row,
        qty: Number(row.transfer_qty || 0),
        pallet_code: String(row.pallet_code || row.kode_pallet || '').trim() || undefined
      }))
    });
    const result = unwrapResponse(response) || {};
    transferConfirmOpen.value = false;
    await loadTransferStocks({ silent: true });
    setFeedback(result.message || 'Transfer rak berhasil dikonfirmasi.');
  } catch (error) {
    setError(error, 'Transfer rak belum berhasil dikonfirmasi.');
  } finally {
    loading.action = false;
  }
}

async function loadAlerts() {
  loading.alerts = true;
  try {
    const response = await getWmsLowStockAlerts();
    alertRows.value = payloadRows(response);
    setFeedback(`Alert stok rendah memuat ${alertRows.value.length.toLocaleString('id-ID')} baris.`);
  } catch (error) {
    alertRows.value = [];
    setError(error, 'Alert stok rendah belum bisa dimuat.');
  } finally {
    loading.alerts = false;
  }
}

async function loadIncoming(options = {}) {
  loading.incoming = true;
  try {
    if (!options.keepPage) {
      resetPage(incomingPagination);
    }
    const nota = String(filters.incomingNota || '').trim();
    const product = String(filters.incomingProduct || '').trim();
    const status = String(filters.incomingStatus || '').trim();
    const response = await getWmsIncomingNoteDetails({
      page: incomingPagination.page,
      page_size: incomingPagination.pageSize,
      ...(nota ? { nota } : {}),
      ...(product ? { product } : {}),
      ...(status ? { status } : {})
    });
    const payload = unwrapResponse(response) || {};
    incomingDocument.value = null;
    incomingItems.value = Array.isArray(payload.items) ? payload.items : payloadRows(response);
    incomingServerPaged.value = true;
    incomingTotalRows.value = Number(payload.total || incomingItems.value.length);
    if (payload.page) {
      incomingPagination.page = Number(payload.page || 1);
    }
    const activeFilters = [
      nota ? `nota ${nota}` : '',
      product ? `produk ${product}` : '',
      status ? incomingStatusOptions.find((option) => option.value === status)?.label.toLowerCase() : ''
    ].filter(Boolean);
    setFeedback(`${activeFilters.length ? `Filter ${activeFilters.join(' · ')}` : 'Semua incoming'} memuat ${incomingItems.value.length.toLocaleString('id-ID')} item dari total ${incomingTotalRows.value.toLocaleString('id-ID')}.`);
  } catch (error) {
    incomingDocument.value = null;
    incomingItems.value = [];
    incomingTotalRows.value = 0;
    setError(error, 'Incoming note belum bisa dimuat.');
  } finally {
    loading.incoming = false;
  }
}

async function processIncoming(row) {
  if (isIncomingProcessed(row)) {
    setFeedback(`Item ${row.KodeBarang || row.KodeStok || ''} sudah diproses QR pallet.`);
    return;
  }

  openIncomingPalletModal(row);
}

function openIncomingPalletModal(row) {
  incomingPalletRow.value = row;
  incomingPalletLines.value = splitIncomingPalletByRule(row);
  if (filters.incomingKodePallet && incomingPalletLines.value.length === 1) {
    incomingPalletLines.value[0].kode_pallet = filters.incomingKodePallet;
  }
  incomingPalletModalOpen.value = true;
}

function autoSplitIncomingPallets() {
  if (!incomingPalletRow.value) return;
  incomingPalletLines.value = splitIncomingPalletByRule(incomingPalletRow.value);
}

function addIncomingPalletLine() {
  incomingPalletLines.value.push(createIncomingPalletLine({
    batch_number: rowBatch(incomingPalletRow.value),
    expired_date: rowExpired(incomingPalletRow.value)
  }));
}

function removeIncomingPalletLine(uid) {
  if (incomingPalletLines.value.length <= 1) {
    return;
  }
  incomingPalletLines.value = incomingPalletLines.value.filter((line) => line.uid !== uid);
}

function fillIncomingPalletRemaining(line) {
  const remainingWithoutLine = incomingPalletExpectedQty.value
    - incomingPalletLines.value.reduce((total, item) => item.uid === line.uid ? total : total + incomingLineTotalQty(item), 0);
  const qty = Math.max(remainingWithoutLine, 0);
  const perUnit = incomingPerUnit(incomingPalletRow.value);
  line.qty_ct = Math.floor(qty / perUnit);
  line.qty_pc = qty % perUnit;
}

async function submitIncomingPallets() {
  const row = incomingPalletRow.value;
  if (!row) return;
  if (!canSubmitIncomingPallets.value) {
    setError(new Error('Total pallet belum sesuai.'), 'Total qty semua pallet harus sama dengan total barang incoming.');
    return;
  }

  loading.action = true;
  try {
    const response = await processWmsIncomingPallet({
      ...row,
      berat_per_pcs_kg: filters.incomingBeratPerPcsKg || 0,
      pallets: incomingPalletLines.value.map((line) => ({
        kode_pallet: line.kode_pallet || '',
        kode_rak: line.kode_rak || '',
        qty_ct: Number(line.qty_ct || 0),
        qty_pc: Number(line.qty_pc || 0),
        berat_barang_kg: line.berat_barang_kg || '',
        batch_number: line.batch_number || '',
        expired_date: line.expired_date || ''
      })),
      batch: rowBatch(row) || undefined,
      expired: rowExpired(row) || undefined
    });
    const result = unwrapResponse(response) || {};
    const dataRows = Array.isArray(result.data_rak_list) ? result.data_rak_list : (result.data_rak ? [result.data_rak] : []);
    const selectedRack = dataRows[0]?.KodeRak || '';
    detailManifest.value = null;
    detailTitle.value = `QR ${row.KodeBarang || row.KodeStok || ''}`;
    detailDescription.value = result.message || `${dataRows.length} pallet berhasil diproses.`;
    detailRows.value = dataRows;
    detailOpen.value = true;
    row.SudahProses = true;
    row.status = 'DONE';
    incomingPalletModalOpen.value = false;
    await loadPallets();
    // Reload the server-derived note status as the current result can be
    // filtered by Belum/Sebagian/Sudah Konfirmasi Gudang.
    await loadIncoming({ keepPage: true });
    setFeedback(`Putaway ${row.KodeBarang || row.KodeStok || ''} berhasil diproses ke ${numberLabel(dataRows.length)} pallet.`);
    for (const item of dataRows) {
      if (!item.qr_data) continue;
      await printItemQrLabel(
        {
          ...row,
          kode_rak: item.KodeRak || selectedRack,
          qty_pcs: Number(item.QtyKarton || 0) * incomingPerUnit(row) + Number(item.QtyPieces || 0),
          batch: item.Batch || rowBatch(row),
          expired: item.ExpiredDate || rowExpired(row)
        },
        { payload: item.qr_data, title: `QR Pallet ${item.KodePallet || ''}`.trim() }
      );
    }
  } catch (error) {
    setError(error, 'Putaway palet belum berhasil diproses.');
  } finally {
    loading.action = false;
  }
}

async function loadPickingDraft(options = {}) {
  loading.picking = true;
  try {
    const nota = String(filters.pickingNota || '').trim();
    if (!options.keepPage) {
      resetPage(pickingPagination);
    }
    const params = nota
      ? undefined
      : { page: pickingPagination.page, page_size: pickingPagination.pageSize };
    const response = await getWmsPickingDraftDetail(nota, params);
    const payload = unwrapResponse(response) || {};
    pickingDocument.value = payload.document || payload.task || null;
    pickingItems.value = Array.isArray(payload.items) ? payload.items : payloadRows(response);
    pickingServerPaged.value = !nota;
    pickingTotalRows.value = !nota ? Number(payload.total || pickingItems.value.length) : pickingItems.value.length;
    if (!nota && payload.page) {
      pickingPagination.page = Number(payload.page || 1);
    }
    setFeedback(`${nota ? `Draft picking ${nota}` : 'Semua nota picking'} memuat ${pickingItems.value.length.toLocaleString('id-ID')} item dari total ${pickingTotalRows.value.toLocaleString('id-ID')}.`);
  } catch (error) {
    pickingDocument.value = null;
    pickingItems.value = [];
    pickingTotalRows.value = 0;
    setError(error, 'Draft picking belum bisa dimuat.');
  } finally {
    loading.picking = false;
  }
}

async function applyPickingScanPayload() {
  const parsed = parseScanPayload(filters.pickingScanPayload);
  if (!parsed.productCode || !parsed.rackCode) {
    setError(new Error('QR picking belum lengkap.'), 'Scan QR barang yang memuat kode barang dan kode rak.');
    return;
  }

  const row = pickingItems.value.find((item) => {
    const sameProduct = String(item.product_code || '').toUpperCase() === parsed.productCode.toUpperCase();
    // A pallet label can retain its old Titipan rack after a valid transfer.
    // Its live rack is checked by the API from pallet detail, so only a normal
    // item label must match the printed rack in the picking draft here.
    const sameRack = parsed.palletCode
      ? true
      : String(item.rak_tetap || '').toUpperCase() === parsed.rackCode.toUpperCase();
    const sameBatch = parsed.batch
      ? String(item.batch || '').toUpperCase() === parsed.batch.toUpperCase()
      : true;
    return sameProduct && sameRack && sameBatch && !isPickingScanned(item);
  });

  if (!row) {
    setError(new Error('Draft picking tidak cocok dengan QR.'), `Draft picking ${parsed.productCode} di ${parsed.rackCode} belum tersedia atau sudah discan.`);
    return;
  }

  await scanPicking(row, parsed);
}

async function scanPicking(row, scanData = null) {
  if (isPickingScanned(row)) {
    setFeedback(`Item ${row.product_code || ''} sudah discan picking.`);
    return;
  }

  if (scanData?.productCode && String(scanData.productCode).toUpperCase() !== String(row.product_code || '').toUpperCase()) {
    setError(new Error('QR barang tidak cocok.'), `QR ${scanData.productCode} tidak cocok dengan item ${row.product_code}.`);
    return;
  }

  if (!scanData?.palletCode && scanData?.rackCode && String(scanData.rackCode).toUpperCase() !== String(row.rak_tetap || '').toUpperCase()) {
    setError(new Error('QR rak tidak cocok.'), `QR rak ${scanData.rackCode} tidak cocok dengan rak picking ${row.rak_tetap}.`);
    return;
  }

  const confirmed = scanData || window.confirm(`Scan QR ${row.product_code || ''} di rak ${row.rak_tetap || '-'}?`);
  if (!confirmed) {
    return;
  }

  loading.action = true;
  try {
    const response = await scanWmsPickingRack({
      wms_task_detail_id: row.wms_task_detail_id,
      nota: row.nota || filters.pickingNota,
      reference_no: row.nota || filters.pickingNota,
      kode_barang: row.product_code,
      kode_rak: row.rak_tetap,
      batch: row.batch,
      expired_date: row.expired_date || row.expired || undefined,
      qty_pcs: Math.max(Number(row.required_quantity || 0) - Number(row.picked_quantity || 0), 0),
      pallet_code: scanData?.palletCode || undefined,
      scan_payload: scanData?.raw || undefined
    });
    const result = unwrapResponse(response) || {};
    row.status_draft = 'PICKED';
    setFeedback(result.msg || `Scan ${row.product_code} selesai.`);
  } catch (error) {
    setError(error, 'Scan picking belum berhasil.');
  } finally {
    loading.action = false;
  }
}

async function finalizePicking() {
  if (!canFinalizePicking.value) {
    setError(
      new Error('Picking belum lengkap.'),
      'Muat satu nota picking dan selesaikan scan semua item sebelum finalisasi.'
    );
    return;
  }

  loading.action = true;
  try {
    const taskIds = pickingTaskIds();
    const response = await finalizeWmsPicking({
      task_id: taskIds[0],
      task_ids: taskIds,
      nota: pickingDocument.value.nota || filters.pickingNota
    });
    const result = unwrapResponse(response) || {};
    pickingDocument.value = result.document || result.task || pickingDocument.value;
    const invoiceNo = result.invoice?.no_faktur || result.erp_order?.no_faktur;
    setFeedback(`${result.msg || 'Picking berhasil difinalisasi.'}${invoiceNo ? ` Invoice ${invoiceNo} siap dicetak.` : ''}`);
    await Promise.all([
      loadPickingDraft({ keepPage: true }),
      result.next_step === 'CHECKER' ? loadCheckerPending() : loadReadyToLoad()
    ]);
  } catch (error) {
    setError(error, 'Finalisasi picking belum berhasil.');
  } finally {
    loading.action = false;
  }
}

function openManifestDetail(row) {
  selectedManifestNo.value = manifestNumber(row);
  detailManifest.value = row;
  detailTitle.value = row.NoManifest;
  detailDescription.value = `${numberLabel(row.total_item)} item manifest`;
  detailRows.value = row.details || [];
  detailOpen.value = true;
}

function closeDetail() {
  detailOpen.value = false;
  detailManifest.value = null;
}

function setScannerPayload(value) {
  if (scannerTarget.value === 'picking') {
    filters.pickingScanPayload = value;
  } else if (scannerTarget.value === 'transfer-target') {
    filters.transferTargetScanPayload = value;
  } else if (scannerTarget.value === 'transfer-item') {
    filters.transferItemScanPayload = value;
  }
}

function stopQrScanner() {
  if (scannerTimer.value) {
    clearTimeout(scannerTimer.value);
    scannerTimer.value = null;
  }
  if (scannerStream.value) {
    scannerStream.value.getTracks().forEach((track) => track.stop());
    scannerStream.value = null;
  }
  scannerOpen.value = false;
}

async function scanVideoFrame(detector) {
  if (!scannerOpen.value || !scannerVideo.value) return;
  try {
    const codes = await detector.detect(scannerVideo.value);
    const value = codes?.[0]?.rawValue || '';
    if (value) {
      setScannerPayload(value);
      stopQrScanner();
      setFeedback('QR berhasil discan. Lanjutkan proses pada tombol aksi.');
      return;
    }
  } catch (error) {
    stopQrScanner();
    setError(error, 'Kamera QR belum bisa membaca frame.');
    return;
  }
  scannerTimer.value = setTimeout(() => scanVideoFrame(detector), 350);
}

async function openQrScanner(target, title) {
  if (!('BarcodeDetector' in window)) {
    setError(new Error('Browser belum mendukung BarcodeDetector.'), 'Browser ini belum mendukung scan QR kamera. Gunakan Chrome Android atau scan dengan scanner yang mengisi kolom input.');
    return;
  }

  stopQrScanner();
  scannerTarget.value = target;
  scannerTitle.value = title;
  scannerOpen.value = true;

  try {
    await nextTick();
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: 'environment' } },
      audio: false
    });
    scannerStream.value = stream;
    scannerVideo.value.srcObject = stream;
    await scannerVideo.value.play();
    const detector = new window.BarcodeDetector({ formats: ['qr_code'] });
    await scanVideoFrame(detector);
  } catch (error) {
    stopQrScanner();
    setError(error, 'Kamera QR belum bisa dibuka. Pastikan akses kamera diizinkan dan halaman dibuka lewat HTTPS atau localhost.');
  }
}

async function refreshAll() {
  await Promise.all([
    loadInventory(),
    loadRacks(),
    loadPrincipalGroups(),
    loadPrincipals(),
    loadPallets(),
    loadPlacements(),
    loadProductOptions(),
    loadCheckerPending(),
    loadPickingIncidents(),
    loadReadyToLoad(),
    loadTransactions(),
    loadAlerts(),
    loadTransferStocks(),
    loadIncoming(),
    loadPickingDraft(),
    loadManifest(),
    loadQuarantine()
]);
}

let incidentRefreshTimer;
watch(activeTab, tab => { if (tab === 'placements' && !loading.placements) loadPlacements(); });
onMounted(() => {
  refreshAll();
  incidentRefreshTimer = setInterval(() => {
    if (document.hidden) return;
    loadPickingIncidents(true);
    if (activeTab.value === 'placements' && !placementModalOpen.value && !loading.placements) loadPlacements(true);
  }, 30000);
});
onBeforeUnmount(() => clearInterval(incidentRefreshTimer));
onBeforeUnmount(stopQrScanner);
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      :title="pageHeaderTitle"
      :description="pageHeaderDescription"
    >
      <div class="flex flex-wrap gap-2">
        <button
          class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900"
          @click="refreshAll"
        >
          Refresh
        </button>
      </div>
    </PageHeader>

    <section v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
      {{ errorMessage }}
    </section>
    <section v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200">
      {{ feedback }}
    </section>

    <section v-if="isMonitoringSection" class="panel overflow-hidden">
      <div class="border-b border-slate-200 px-5 py-4 dark:border-slate-800">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p class="text-xs font-bold uppercase tracking-[0.25em] text-brand-600 dark:text-brand-300">Alur WMS</p>
            <h2 class="mt-1 text-xl font-bold text-slate-950 dark:text-white">Dari barang datang sampai manifest</h2>
          </div>
          <div class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
            Ringkasan proses gudang
          </div>
        </div>
      </div>

      <div class="px-5 py-5">
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-6">
          <button
            v-for="(step, index) in flowSteps"
            :key="step.number"
            type="button"
            class="group relative rounded-2xl border p-4 text-left transition hover:-translate-y-0.5 hover:shadow-sm focus:outline-none focus:ring-2 focus:ring-brand-500/30"
            :class="[
              step.tone,
              activeTab === step.tab ? 'ring-2 ring-brand-500/25' : ''
            ]"
            @click="openFlowStep(step)"
          >
            <span
              v-if="index < flowSteps.length - 1"
              class="pointer-events-none absolute left-[calc(100%+0.25rem)] top-8 hidden h-px w-2 bg-slate-300 dark:bg-slate-700 xl:block"
            ></span>
            <div class="flex items-start justify-between gap-3">
              <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white/80 text-xs font-black text-slate-900 shadow-sm dark:bg-slate-950/60 dark:text-white">
                {{ step.number }}
              </span>
              <span class="rounded-full bg-white/80 px-2 py-1 text-xs font-bold text-slate-700 dark:bg-slate-950/60 dark:text-slate-200">
                {{ step.metric }}
              </span>
            </div>
            <h3 class="mt-4 text-base font-black leading-5 text-slate-950 dark:text-white">{{ step.title }}</h3>
            <p class="mt-1 text-xs font-semibold text-slate-500 dark:text-slate-300">{{ step.metricLabel }}</p>
            <dl class="mt-4 space-y-2 text-xs leading-5">
              <div>
                <dt class="font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Sumber</dt>
                <dd class="break-words font-semibold text-slate-800 dark:text-slate-100">{{ step.source }}</dd>
              </div>
              <div>
                <dt class="font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Aksi</dt>
                <dd class="break-words font-semibold text-slate-800 dark:text-slate-100">{{ step.action }}</dd>
              </div>
              <div>
                <dt class="font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Hasil</dt>
                <dd class="break-words font-semibold text-slate-800 dark:text-slate-100">{{ step.result }}</dd>
              </div>
            </dl>
          </button>
        </div>
      </div>
    </section>

    <section v-if="isMonitoringSection" class="panel p-5">
      <div class="grid gap-4 xl:grid-cols-[minmax(260px,1fr)_minmax(280px,420px)_auto_auto_auto] xl:items-end">
        <div>
          <p class="text-xs font-bold uppercase tracking-[0.25em] text-brand-600 dark:text-brand-300">Cetak QR WMS</p>
          <h2 class="mt-1 text-xl font-bold text-slate-950 dark:text-white">Label rak dan daftar isi</h2>
          <p class="mt-1 text-sm font-semibold text-slate-500 dark:text-slate-400">{{ monitoringPrintSummary }}</p>
        </div>
        <AppSearchSelect
          v-model="selectedPrintRackCodes"
          label="Rak"
          placeholder="Pilih satu / beberapa rak"
          :options="rackSelectOptions"
          :multiple="true"
          :loading="loading.racks || loading.rackOptions"
          :remote-search="true"
          :max-visible-options="100"
          empty-text="Rak tidak ditemukan."
          @search="searchRackOptions"
        />
        <button
          type="button"
          class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900"
          :disabled="!rackRows.length"
          @click="printRackQrLabels()"
        >
          Cetak QR Semua
        </button>
        <button
          type="button"
          class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900"
          :disabled="!selectedPrintRackCodeList.length"
          @click="printChosenRackQrLabels"
        >
          Cetak QR Pilihan
        </button>
        <button
          type="button"
          class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900"
          :disabled="!selectedPrintRackCodeList.length"
          @click="printChosenRackContents"
        >
          Cetak Isi Rak
        </button>
      </div>
    </section>

    <section v-if="isMonitoringSection" class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-7">
      <article
        v-for="card in summaryCards"
        :key="card.label"
        class="panel p-5"
      >
        <p class="text-sm font-semibold text-slate-500 dark:text-slate-400">{{ card.label }}</p>
        <p class="mt-3 text-3xl font-bold text-slate-950 dark:text-white">{{ card.value }}</p>
      </article>
    </section>

    <section class="panel overflow-hidden">
      <div v-if="isMonitoringSection" class="flex gap-2 overflow-x-auto border-b border-slate-200 p-3 dark:border-slate-800">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          :class="[
            'shrink-0 rounded-xl px-4 py-2 text-sm font-bold transition',
            activeTab === tab.key
              ? 'bg-brand-600 text-white'
              : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-900'
          ]"
          @click="activeTab = tab.key"
        >
          {{ tab.label }}
        </button>
      </div>

      <div class="p-5">
        <button v-if="pickingIncidents.length && activeTab !== 'picking'" class="mb-4 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm font-semibold text-amber-900" @click="activeTab = 'picking'">
          {{ pickingIncidents.length }} kendala picking perlu ditindaklanjuti — buka laporan
        </button>
        <section v-if="activeTab === 'inventory'" class="space-y-5">
          <div class="grid gap-4 md:grid-cols-4">
            <AppFormField v-model="filters.inventorySearch" label="Cari Inventory" placeholder="Kode atau nama barang" />
            <label class="block">
              <span class="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">Status</span>
              <select v-model="filters.inventoryStatus" class="field">
                <option v-for="option in inventoryStatusOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
            </label>
            <div class="flex items-end">
              <button class="rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60 dark:bg-brand-600 dark:hover:bg-brand-700" :disabled="loading.inventory" @click="loadInventory">
                Muat Inventory
              </button>
            </div>
          </div>

          <div class="grid gap-4 md:grid-cols-[minmax(240px,1fr)_auto] md:items-end">
            <AppFormField v-model="filters.barcodeProduct" label="Scan / Barcode Produk" placeholder="BRG001" />
            <button class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" :disabled="loading.barcode" @click="lookupBarcode">
              Cek Barcode
            </button>
          </div>

          <AppTable :rows="inventoryRows" :columns="inventoryColumns" :loading="loading.inventory" row-key="product_code" />
          <AppTable v-if="barcodeRows.length || loading.barcode" :rows="barcodeRows" :columns="inventoryColumns" :loading="loading.barcode" row-key="product_code" empty-message="Barcode tidak menemukan stok." />
        </section>

        <section v-else-if="activeTab === 'racks'" class="space-y-6">
          <div class="space-y-4">
            <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-[minmax(220px,1fr)_minmax(160px,190px)_minmax(160px,190px)_minmax(140px,170px)_auto_auto] md:items-end">
              <AppFormField v-model="filters.rackSearch" label="Cari Rak" placeholder="Kode, tipe, status" />
              <label class="block">
                <span class="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">Tipe Rak</span>
                <select v-model="filters.rackType" class="field">
                  <option v-for="option in rackTypeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
                </select>
              </label>
              <label class="block">
                <span class="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">Status Rak</span>
                <select v-model="filters.rackStatus" class="field">
                  <option v-for="option in rackStatusOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
                </select>
              </label>
              <label class="block">
                <span class="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">Aktif</span>
                <select v-model="filters.rackActive" class="field">
                  <option v-for="option in rackActiveOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
                </select>
              </label>
              <button class="whitespace-nowrap rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60 dark:bg-brand-600 dark:hover:bg-brand-700" :disabled="loading.racks" @click="loadRacks">
                Muat Rak
              </button>
              <button class="whitespace-nowrap rounded-xl border border-brand-200 bg-brand-50 px-4 py-2.5 text-sm font-semibold text-brand-700 hover:bg-brand-100 disabled:opacity-60 dark:border-brand-500/40 dark:bg-brand-500/10 dark:text-brand-100 dark:hover:bg-brand-500/20" :disabled="loading.nextRack" @click="openCreateRackModal">
                Tambah Rak
              </button>
            </div>

            <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-[minmax(260px,1fr)_auto_auto_auto] md:items-end">
              <AppSearchSelect
                v-model="selectedPrintRackCodes"
                label="Pilih Rak Cetak"
                placeholder="Pilih beberapa rak"
                :options="rackSelectOptions"
                :multiple="true"
                :loading="loading.racks || loading.rackOptions"
                :remote-search="true"
                :max-visible-options="100"
                empty-text="Rak tidak ditemukan."
                @search="searchRackOptions"
              />
              <button class="whitespace-nowrap rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" :disabled="!rackRows.length" @click="printRackQrLabels()">
                Cetak QR Semua
              </button>
              <button class="whitespace-nowrap rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" :disabled="!selectedPrintRackCodeList.length" @click="printChosenRackQrLabels">
                Cetak QR Pilihan
              </button>
              <button class="whitespace-nowrap rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" :disabled="!selectedPrintRackCodeList.length" @click="printChosenRackContents">
                Cetak Isi Pilihan
              </button>
            </div>
          </div>

          <AppTable :rows="rackRows" :columns="rackColumns" :loading="loading.racks" :clickable-rows="true" row-key="id" :selected-key="selectedRackId" empty-message="Master rak belum tersedia." @row-click="editRack" />
        </section>

        <section v-else-if="activeTab === 'pallets'" class="space-y-6">
          <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-[minmax(220px,1fr)_minmax(160px,190px)_minmax(140px,170px)_auto_auto] md:items-end">
            <AppFormField v-model="filters.palletSearch" label="Cari Pallet" placeholder="Kode, tipe, catatan" />
            <label class="block">
              <span class="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">Status Pallet</span>
              <select v-model="filters.palletStatus" class="field">
                <option v-for="option in palletStatusOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
            </label>
            <label class="block">
              <span class="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">Aktif</span>
              <select v-model="filters.palletActive" class="field">
                <option v-for="option in palletActiveOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
            </label>
            <button class="whitespace-nowrap rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60 dark:bg-brand-600 dark:hover:bg-brand-700" :disabled="loading.pallets" @click="loadPallets">
              Muat Pallet
            </button>
            <button class="whitespace-nowrap rounded-xl border border-brand-200 bg-brand-50 px-4 py-2.5 text-sm font-semibold text-brand-700 hover:bg-brand-100 disabled:opacity-60 dark:border-brand-500/40 dark:bg-brand-500/10 dark:text-brand-100 dark:hover:bg-brand-500/20" :disabled="loading.nextPallet" @click="openCreatePalletModal">
              Tambah Pallet
            </button>
          </div>

          <AppTable :rows="palletRows" :columns="palletColumns" :loading="loading.pallets" :clickable-rows="true" row-key="id" :selected-key="selectedPalletId" empty-message="Master pallet belum tersedia." @row-click="editPallet" />
        </section>

        <section v-else-if="activeTab === 'placements'" class="space-y-6">
          <div class="space-y-4">
            <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-[minmax(220px,1fr)_minmax(220px,280px)_minmax(160px,200px)_auto_auto] md:items-end">
              <AppFormField v-model="filters.placementSearch" label="Cari Penempatan" placeholder="Kode rak, produk, SKU" />
              <AppSearchSelect
                v-model="filters.placementRack"
                label="Rak"
                placeholder="Pilih / ketik kode rak"
                :options="placementPrintRackOptions"
                :loading="loading.racks || loading.placements || loading.rackOptions"
                :remote-search="true"
                :max-visible-options="100"
                empty-text="Rak tidak ditemukan."
                @search="searchRackOptions"
              />
              <label class="block">
                <span class="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">Status</span>
                <select v-model="filters.placementStatus" class="field">
                  <option v-for="option in placementStatusOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
                </select>
              </label>
              <button class="whitespace-nowrap rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60 dark:bg-brand-600 dark:hover:bg-brand-700" :disabled="loading.placements" @click="loadPlacements">
                Muat Penempatan
              </button>
              <button class="whitespace-nowrap rounded-xl border border-brand-200 bg-brand-50 px-4 py-2.5 text-sm font-semibold text-brand-700 hover:bg-brand-100 dark:border-brand-500/40 dark:bg-brand-500/10 dark:text-brand-100 dark:hover:bg-brand-500/20" @click="openCreatePlacementModal">
                Tambah Penempatan
              </button>
            </div>

            <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-[minmax(260px,1fr)_auto_auto_auto_auto] md:items-end">
              <AppSearchSelect
                v-model="selectedPrintRackCodes"
                label="Pilih Rak Cetak"
                placeholder="Pilih beberapa rak"
                :options="placementPrintRackOptions"
                :multiple="true"
                :loading="loading.racks || loading.placements || loading.rackOptions"
                :remote-search="true"
                :max-visible-options="100"
                empty-text="Rak tidak ditemukan."
                @search="searchRackOptions"
              />
              <button class="whitespace-nowrap rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" :disabled="!placementRows.length" @click="printRackContentLabels()">
                Cetak Isi Semua
              </button>
              <button class="whitespace-nowrap rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" :disabled="!selectedPrintRackCodeList.length" @click="printChosenRackContents">
                Cetak Isi Pilihan
              </button>
              <button class="whitespace-nowrap rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" :disabled="!placementFilterRackCode" @click="printPlacementFilterContents">
                Cetak Isi Filter
              </button>
              <button class="whitespace-nowrap rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" :disabled="!selectedPlacementRow" @click="printSelectedPlacementItemQr">
                Cetak QR Barang
              </button>
            </div>
          </div>

          <h3 class="font-semibold">Saldo Penempatan — Acuan Laporan Stok Gudang</h3>
          <p class="text-sm text-slate-600 dark:text-slate-300">Jumlah dan Total PCS memakai STOK READY dari laporan, satu kali per produk/cabang. Filter rak memilih produk, bukan membagi saldo produk ke rak. Selisih pemetaan membandingkan GOOD dengan total rak Tetap/Lorong; tidak mengubah saldo laporan atau mengarang batch/lokasi. Saldo dimuat ulang tiap 30 detik saat halaman aktif.</p>
          <AppTable :rows="placementSummary" :columns="placementBalanceColumns" :loading="loading.placements" row-key="id" empty-message="Saldo laporan belum tersedia untuk filter ini." />
          <h3 class="font-semibold">Rincian Lokasi & Batch</h3>
          <p class="text-sm text-slate-600 dark:text-slate-300">Jumlah di bawah adalah catatan fisik masing-masing rak, bukan saldo transaksi. Klik baris untuk memperbaiki pemetaan berdasarkan barang sebenarnya. Selisih positif berarti lokasi belum lengkap; negatif berarti catatan rak melebihi GOOD. Data ini tidak menimpa Laporan Stok Gudang.</p>
          <AppTable :rows="placementRows" :columns="placementColumns" :loading="loading.placements" :clickable-rows="true" row-key="id" :selected-key="selectedPlacementId" empty-message="Penempatan barang belum tersedia." @row-click="editPlacement" />
        </section>

        <section v-else-if="activeTab === 'incoming'" class="space-y-5">
          <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-[minmax(220px,1fr)_minmax(220px,1fr)_minmax(180px,220px)_minmax(200px,240px)_minmax(160px,190px)_auto_auto] md:items-end">
            <AppFormField v-model="filters.incomingNota" label="Nota Incoming" placeholder="Cari sebagian nomor nota" />
            <AppFormField v-model="filters.incomingProduct" label="Produk" placeholder="Kode atau nama produk" />
            <label class="block">
              <span class="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">Status Konfirmasi</span>
              <select v-model="filters.incomingStatus" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none transition focus:border-brand-400 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100">
                <option v-for="option in incomingStatusOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
            </label>
            <AppSearchSelect
              v-model="filters.incomingKodePallet"
              label="Pallet"
              placeholder="Otomatis / pilih pallet"
              :options="palletSelectOptions"
              :loading="loading.pallets"
              empty-text="Pallet aktif tidak ditemukan."
            />
            <AppFormField v-model="filters.incomingBeratPerPcsKg" label="Berat / PCS (kg)" type="number" min="0" step="0.001" placeholder="Opsional" />
            <button class="rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60 dark:bg-brand-600 dark:hover:bg-brand-700" :disabled="loading.incoming" @click="loadIncoming">
              Muat Incoming
            </button>
            <button
              class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900"
              :disabled="!incomingDocument?.nota"
              @click="printIncomingDocumentQr()"
            >
              Cetak QR Nota
            </button>
          </div>
          <div class="panel overflow-hidden">
            <div class="border-b border-slate-200 px-4 py-3 text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">
              Rak titipan dipilih otomatis sesuai kategori produk: <strong>Food ke Gedung G1</strong> dan <strong>Non Food ke Gedung G2</strong>. Pallet boleh dipilih manual atau dibiarkan otomatis; kapasitas qty/berat tetap divalidasi.
            </div>
            <div class="overflow-x-auto">
              <table class="min-w-[1360px] w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
                <thead class="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-900 dark:text-slate-400">
                  <tr>
                    <th class="px-4 py-3">Nota</th>
                    <th class="px-4 py-3">Kode</th>
                    <th class="px-4 py-3">Produk</th>
                    <th class="px-4 py-3 text-right">Total PCS</th>
                    <th class="px-4 py-3 text-right">CT</th>
                    <th class="px-4 py-3 text-right">PC</th>
                    <th class="px-4 py-3 text-right">Per Unit</th>
                    <th class="px-4 py-3 text-right">Pallet</th>
                    <th class="px-4 py-3">Status</th>
                    <th class="px-4 py-3 text-right">Aksi</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-slate-100 bg-white dark:divide-slate-800 dark:bg-slate-950">
                  <tr v-if="loading.incoming">
                    <td colspan="10" class="px-4 py-10 text-center text-slate-500 dark:text-slate-400">Memuat data...</td>
                  </tr>
                  <tr v-else-if="!incomingItems.length">
                    <td colspan="10" class="px-4 py-10 text-center text-slate-500 dark:text-slate-400">Item incoming belum tersedia.</td>
                  </tr>
                  <tr v-for="(row, index) in visibleIncomingItems" v-else :key="row.wms_putaway_detail_id || `${row.Nota || 'incoming'}-${row.KodeBarang || row.KodeStok || index}-${incomingPageStart + index}`" class="text-slate-700 dark:text-slate-200">
                    <td class="px-4 py-3">{{ row.Nota || '-' }}</td>
                    <td class="px-4 py-3 font-semibold">{{ row.KodeBarang || row.KodeStok || '-' }}</td>
                    <td class="px-4 py-3">{{ row.NamaBarang || '-' }}</td>
                    <td class="px-4 py-3 text-right font-semibold">{{ numberLabel(incomingRowTotalQty(row)) }}</td>
                    <td class="px-4 py-3 text-right">{{ numberLabel(incomingRowQtyCt(row)) }}</td>
                    <td class="px-4 py-3 text-right">{{ numberLabel(incomingRowQtyPc(row)) }}</td>
                    <td class="px-4 py-3 text-right">{{ numberLabel(incomingPerUnit(row)) }}</td>
                    <td class="px-4 py-3 text-right">{{ numberLabel(incomingPalletCount(row)) }}</td>
                    <td class="px-4 py-3">
                      <span :class="incomingStatusBadge(row).className">
                        {{ incomingStatusBadge(row).text }}
                      </span>
                      <p v-if="row.KodeRakTitipan || row.kode_rak_titipan" class="mt-1 text-xs font-semibold text-slate-500 dark:text-slate-400">
                        Rak titipan: {{ row.KodeRakTitipan || row.kode_rak_titipan }}
                      </p>
                      <p v-if="row.GudangRekomendasi || row.gudang_rekomendasi" class="mt-1 text-xs font-semibold text-sky-700 dark:text-sky-300">
                        Zona otomatis:
                        {{ (row.ZonaPenyimpanan || row.zona_penyimpanan) === 'NON_FOOD' ? 'Non Food' : (row.ZonaPenyimpanan || row.zona_penyimpanan) === 'FOOD' ? 'Food' : 'Belum dipetakan' }}
                        · Gedung G{{ row.GudangRekomendasi || row.gudang_rekomendasi }}
                      </p>
                    </td>
                    <td class="px-4 py-3">
                      <div class="flex justify-end gap-2">
                        <button
                          class="rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900"
                          @click="printIncomingDocumentQr(row)"
                        >
                          QR Nota
                        </button>
                      <button
                        class="rounded-xl bg-slate-900 px-3 py-2 text-xs font-bold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-brand-600 dark:hover:bg-brand-700"
                        :disabled="loading.action || isIncomingProcessed(row)"
                        @click="processIncoming(row)"
                      >
                        Atur Pallet
                      </button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-if="incomingItems.length" class="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-4 py-3 text-sm text-slate-600 dark:border-slate-800 dark:text-slate-300">
              <span>Menampilkan {{ pageRange(incomingDisplayTotal, incomingPagination) }} dari {{ numberLabel(incomingDisplayTotal) }} item</span>
              <div class="flex flex-wrap items-center gap-2">
                <select v-model.number="incomingPagination.pageSize" class="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950">
                  <option v-for="option in NOTE_PAGE_SIZE_OPTIONS" :key="option" :value="option">{{ option }} / halaman</option>
                </select>
                <button class="rounded-xl border border-slate-200 px-3 py-2 font-semibold disabled:opacity-50 dark:border-slate-700" :disabled="incomingPagination.page <= 1 || loading.incoming" @click="changeIncomingPage(-1)">
                  Prev
                </button>
                <span class="px-2 font-semibold">{{ incomingPagination.page }} / {{ incomingTotalPages }}</span>
                <button class="rounded-xl border border-slate-200 px-3 py-2 font-semibold disabled:opacity-50 dark:border-slate-700" :disabled="incomingPagination.page >= incomingTotalPages || loading.incoming" @click="changeIncomingPage(1)">
                  Next
                </button>
              </div>
            </div>
          </div>
        </section>

        <section v-else-if="activeTab === 'picking'" class="space-y-5">
          <ShipmentPickingPanel />
          <article class="rounded-2xl border border-amber-300 p-4">
            <h3 class="font-bold">Kendala Picking · {{ pickingIncidents.length }} terbuka</h3>
            <button class="mt-2 font-semibold" @click="loadPickingIncidents">Muat laporan</button>
            <p class="mt-2 text-sm">Menutup laporan tidak mengubah stok atau menyelesaikan revisi faktur.</p>
            <div v-for="incident in pickingIncidents" :key="incident.id" class="mt-3 rounded-xl border p-3 text-sm">
              <p class="font-bold">{{ incident.no_faktur || incident.no_order }} · {{ incident.kode_barang }} · {{ incident.kode_rak }}</p>
              <p>Dibutuhkan {{ incident.required_qty }} PCS, tersedia {{ incident.available_qty }} PCS</p>
              <input v-model="incident.resolutionNote" class="field my-2" placeholder="Catatan tindakan penyelesaian" maxlength="1000" />
              <button :disabled="loading.action || !incident.resolutionNote?.trim()" class="font-semibold disabled:opacity-50" @click="closePickingIncident(incident)">Tutup laporan</button>
            </div>
          </article>
        </section>

        <section v-else-if="activeTab === 'checker'" class="space-y-5">
          <div class="grid gap-4 rounded-2xl border border-slate-200 p-4 md:grid-cols-[1fr_1fr_auto] md:items-end dark:border-slate-800">
            <AppFormField v-model="filters.checkerName" label="Nama Checker" placeholder="Nama petugas checker" />
            <AppFormField v-model="filters.checkerDock" label="Loading Dock" placeholder="Contoh: DOCK-A" />
            <button class="rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60 dark:bg-brand-600 dark:hover:bg-brand-700" :disabled="loading.checker" @click="loadCheckerPending">
              Muat Draft Checker
            </button>
          </div>
          <AppTable :rows="checkerRows" :columns="checkerColumns" :loading="loading.checker" row-key="id" empty-message="Belum ada barang yang menunggu checker." />
          <div v-if="checkerRows.length" class="grid gap-3 lg:grid-cols-2">
            <article v-for="task in checkerRows" :key="task.id" class="rounded-2xl border border-slate-200 p-4 dark:border-slate-800">
              <div class="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p class="text-xs font-bold uppercase tracking-wider text-slate-500">{{ task.shipment_reference || 'Draf lama' }} · {{ task.nota || `Task ${task.id}` }}</p>
                  <h3 class="mt-1 text-lg font-bold text-slate-950 dark:text-white">{{ numberLabel(task.total_item) }} barang</h3>
                  <p class="mt-1 text-sm text-slate-500">Cocokkan hasil scan picking dengan meja checker sebelum ke loading dock.</p>
                </div>
                <button class="rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-bold text-white hover:bg-emerald-700 disabled:opacity-60" :disabled="loading.action" @click="submitChecker(task)">
                  Simpan Hasil Checker OK / NG
                </button>
              </div>
              <div class="mt-4 divide-y divide-slate-200 rounded-xl border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
                <div v-for="detail in task.details" :key="detail.id" class="grid gap-3 px-3 py-2 text-sm md:grid-cols-2">
                  <span><strong>{{ detail.kode_barang }}</strong> · {{ detail.nama_barang }}</span>
                  <span class="font-bold">{{ numberLabel(detail.picked_quantity) }} PCS · {{ detail.handling_class }}</span>
                  <template v-if="detail">
                    <label>Jumlah aktual (PCS)<input v-model="detail.actualQty" class="field" type="number" min="0" step="1" placeholder="Hasil hitung fisik" /></label>
                    <label>Kondisi<select v-model="detail.actualCondition" aria-label="Kondisi" class="field"><option value="">Pilih kondisi</option><option value="GOOD">Baik</option><option value="DAMAGED">Rusak (NG)</option></select></label>
                    <label class="md:col-span-2">Catatan (wajib untuk NG)<input v-model="detail.actualNote" class="field" maxlength="1000" /></label>
                    <p v-if="task.status === 'CHECKER_HOLD'" class="font-semibold text-rose-600 md:col-span-2">Ditahan: hasil sebelumnya {{ detail.checked_quantity }} PCS / {{ detail.checker_status }}. Perbaiki lalu hitung ulang.</p>
                  </template>
                </div>
              </div>
            </article>
          </div>
        </section>

        <section v-else-if="activeTab === 'loading'" class="space-y-5">
          <ShipmentLoadingPanel />
        </section>

        <section v-else-if="activeTab === 'dropping'" class="space-y-5">
          <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-[1fr_1fr_2fr_auto] xl:items-end">
            <AppFormField v-model="filters.manifestDriver" label="Driver / Kode Driver" placeholder="Nama atau kode driver" />
            <AppFormField v-model="filters.deliveryReceiver" label="Penerima Toko" placeholder="Nama penerima" />
            <AppFormField v-model="filters.deliveryNotes" label="Catatan / Alasan Gagal" placeholder="Catatan serah terima atau alasan karantina" />
            <button class="rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60 dark:bg-brand-600 dark:hover:bg-brand-700" :disabled="loading.dropping" @click="loadManifest">
              Cari Manifest
            </button>
          </div>
          <section class="rounded-2xl border border-violet-200 bg-violet-50/70 p-4 dark:border-violet-500/30 dark:bg-violet-500/10">
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p class="text-xs font-bold uppercase tracking-[0.2em] text-violet-700 dark:text-violet-200">QR WMS</p>
                <h3 class="mt-1 text-lg font-black text-slate-950 dark:text-white">Cetak QR / Barcode Manifest</h3>
                <p class="mt-1 max-w-3xl text-sm text-slate-600 dark:text-slate-300">
                  QR ini dipindai dari menu <strong>QC Karantina</strong> di WMS Mobile. Klik <strong>Cari Manifest</strong>, pilih manifest, lalu cetak labelnya.
                </p>
              </div>
              <span v-if="manifestTableRows.length" class="rounded-full bg-white/80 px-3 py-1.5 text-xs font-bold text-violet-800 dark:bg-slate-950/50 dark:text-violet-100">
                {{ numberLabel(manifestTableRows.length) }} manifest siap dipilih
              </span>
            </div>
            <div class="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
              <label class="block">
                <span class="mb-1.5 block text-sm font-semibold text-slate-700 dark:text-slate-200">Manifest yang akan dicetak</span>
                <select v-model="selectedManifestNo" class="field" :disabled="loading.dropping || !manifestTableRows.length">
                  <option value="">{{ manifestTableRows.length ? 'Pilih manifest' : 'Cari manifest terlebih dahulu' }}</option>
                  <option v-for="manifest in manifestTableRows" :key="manifestNumber(manifest)" :value="manifestNumber(manifest)">
                    {{ manifestNumber(manifest) }} · {{ manifest.driver || '-' }} · {{ manifest.vehicle_no || '-' }}
                  </option>
                </select>
              </label>
              <button
                type="button"
                class="rounded-xl bg-violet-700 px-4 py-2.5 text-sm font-bold text-white hover:bg-violet-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-violet-600 dark:hover:bg-violet-500"
                :disabled="!selectedManifestForQr || loading.action"
                @click="printManifestDocumentQr(selectedManifestForQr)"
              >
                Cetak QR/Barcode Manifest
              </button>
            </div>
          </section>
          <AppTable :rows="manifestTableRows" :columns="manifestColumns" :loading="loading.dropping" :clickable-rows="true" row-key="NoManifest" empty-message="Manifest belum tersedia. Klik Cari Manifest untuk memuat data, lalu cetak QR/Barcode dari panel di atas." @row-click="openManifestDetail" />
          <div v-if="manifestTableRows.length" class="flex flex-wrap gap-2">
            <div v-for="manifest in manifestTableRows" :key="manifest.NoManifest" class="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 p-2 dark:border-slate-800">
              <button
                type="button"
                class="rounded-lg border border-violet-300 bg-violet-50 px-3 py-2 text-sm font-bold text-violet-700 hover:bg-violet-100 disabled:opacity-60 dark:border-violet-500/40 dark:bg-violet-500/10 dark:text-violet-100 dark:hover:bg-violet-500/20"
                :disabled="loading.action"
                @click="printManifestDocumentQr(manifest)"
              >
                Cetak QR {{ manifest.NoManifest }}
              </button>
              <button v-if="!['DELIVERED', 'QUARANTINE', 'QC_COMPLETE', 'DELIVERY_ISSUE'].includes(manifest.status)" class="rounded-lg bg-emerald-600 px-3 py-2 text-sm font-bold text-white hover:bg-emerald-700 disabled:opacity-60" :disabled="loading.action" @click="completeDelivery(manifest)">
                Pengiriman Selesai
              </button>
              <button v-if="!['DELIVERED', 'QUARANTINE', 'QC_COMPLETE', 'DELIVERY_ISSUE'].includes(manifest.status)" class="rounded-lg border border-rose-300 px-3 py-2 text-sm font-bold text-rose-700 hover:bg-rose-50 disabled:opacity-60 dark:border-rose-500/40 dark:text-rose-300 dark:hover:bg-rose-500/10" :disabled="loading.action" @click="dropToQuarantine(manifest)">
                Gagal Kirim / Karantina
              </button>
              <span v-else-if="manifest.status === 'DELIVERY_ISSUE'" class="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-bold text-amber-800 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">
                Retur / selisih per item menunggu QC Karantina
              </span>
            </div>
          </div>
        </section>

        <section v-else-if="activeTab === 'qc'" class="space-y-5">
          <div class="grid gap-4 rounded-2xl border border-slate-200 p-4 md:grid-cols-[1fr_1fr_auto] md:items-end dark:border-slate-800">
            <AppFormField v-model="filters.quarantineSearch" label="Cari Karantina" placeholder="Manifest, nota, SKU, atau produk" />
            <AppFormField v-model="filters.qcName" label="Petugas QC" placeholder="Nama petugas QC" />
            <button class="rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60 dark:bg-brand-600 dark:hover:bg-brand-700" :disabled="loading.qc" @click="loadQuarantine">
              Muat Karantina
            </button>
          </div>
          <div v-if="quarantineRows.length" class="space-y-3">
            <article v-for="row in quarantineRows" :key="row.id" class="rounded-2xl border border-slate-200 p-4 dark:border-slate-800">
              <div class="grid gap-4 xl:grid-cols-[minmax(260px,1.5fr)_repeat(3,minmax(140px,0.7fr))_auto] xl:items-end">
                <div>
                  <p class="text-xs font-bold uppercase tracking-wider text-rose-500">{{ row.no_manifest }} · {{ row.reference_no || '-' }}</p>
                  <h3 class="mt-1 text-lg font-bold text-slate-950 dark:text-white">{{ row.kode_barang }} · {{ row.nama_barang }}</h3>
                  <p class="mt-1 text-sm text-slate-500">Total {{ numberLabel(row.qty_pcs) }} PCS · {{ numberLabel(row.qty_ct) }} CT + {{ numberLabel(row.qty_pc) }} PC</p>
                  <p class="mt-1 text-sm text-slate-500">Batch: {{ row.batch_number || '-' }} · Expired: {{ row.expired_date || '-' }}</p>
                  <div v-if="['MANUAL_REQUIRED', 'MULTIPLE'].includes(row.lot_status)" class="mt-3 space-y-2">
                    <p class="text-sm text-amber-600">Cocokkan batch/expired fisik barang. Pisahkan detail retur jika berisi beberapa lot.</p>
                    <p v-for="lot in row.lot_options || []" :key="`${lot.batch_number}-${lot.expired_date}`" class="text-xs text-slate-500">Lot asal: {{ lot.batch_number || '-' }} · {{ lot.expired_date || '-' }}</p>
                    <AppFormField v-model="row.batch_number" label="Batch fisik barang" />
                    <AppFormField v-model="row.expired_date" type="date" label="Expired" :readonly="row.no_expiry_input" />
                    <label class="flex items-center gap-2 text-sm"><input v-model="row.no_expiry_input" type="checkbox" />Produk tanpa expired (sudah diperiksa)</label>
                  </div>
                </div>
                <AppFormField v-model="row.qty_good_input" type="number" label="GOOD (PCS)" />
                <AppFormField v-model="row.qty_bad_input" type="number" label="BAD (PCS)" />
                <AppSearchSelect
                  v-model="row.target_rack_input"
                  label="Rak GOOD"
                  placeholder="Cari rak Tetap / Lorong"
                  :options="quarantineTargetRackOptions(row)"
                  :remote-search="true"
                  :max-visible-options="100"
                  :loading="row.target_rack_loading"
                  empty-text="Rak Tetap atau Lorong aktif tidak ditemukan."
                  :display-value="row.target_rack_input"
                  @search="(keyword) => searchQuarantineRackOptions(keyword, row)"
                />
                <button class="rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-bold text-white hover:bg-emerald-700 disabled:opacity-60" :disabled="loading.action" @click="submitQuarantineQc(row)">
                  Simpan QC
                </button>
              </div>
            </article>
          </div>
          <div v-else-if="!loading.qc" class="rounded-2xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700">
            Tidak ada barang gagal kirim yang menunggu QC.
          </div>
        </section>

        <section v-else-if="activeTab === 'transfer'" class="space-y-5">
          <div class="grid gap-4 md:grid-cols-[minmax(240px,1fr)_auto_auto] md:items-end">
            <AppFormField v-model="filters.transferTargetScanPayload" label="1. Scan QR Rak Tujuan" placeholder="BUDIMAS-WMS|LOCATION|G1R01L0K01N01" />
            <button class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" @click="openQrScanner('transfer-target', 'Scan QR Rak Tujuan')">
              Kamera
            </button>
            <button class="rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60 dark:bg-brand-600 dark:hover:bg-brand-700" :disabled="loading.transfer || !filters.transferTargetScanPayload" @click="applyTransferTargetScan">
              Set Tujuan
            </button>
          </div>
          <div class="grid gap-4 md:grid-cols-[minmax(240px,1fr)_auto] md:items-end">
            <AppFormField v-model="filters.transferItemScanPayload" label="2. Scan QR Barang / Pallet" placeholder="CCLY001;G1R01L2K12N02;30;0;0;Nama;Batch;Expired" />
            <button class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" @click="openQrScanner('transfer-item', 'Scan QR Barang Transfer')">
              Kamera
            </button>
            <button class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" :disabled="!filters.transferItemScanPayload || !transferRows.length" @click="applyTransferItemScan">
              Verifikasi Barang
            </button>
          </div>
          <div class="grid gap-4 xl:grid-cols-[minmax(180px,1fr)_minmax(180px,1fr)_minmax(220px,320px)_auto_auto] xl:items-end">
            <AppFormField v-model="filters.transferProduct" label="Kode Barang" placeholder="Kode SKU / kosongkan semua" />
            <AppFormField v-model="filters.transferSourceRack" label="Rak Titipan Asal" placeholder="Kode rak titipan / kosongkan semua" />
            <AppSearchSelect
              v-model="filters.transferTargetRack"
              label="Rak Tetap Tujuan"
              placeholder="Pilih rak tetap"
              :options="transferTargetRackOptions"
              :remote-search="true"
              :max-visible-options="100"
              :loading="loading.racks || loading.rackOptions"
              empty-text="Rak tetap tidak ditemukan."
              :display-value="filters.transferTargetRack"
              @search="(keyword) => searchRackOptions(keyword, { typeRak: 'Tetap' })"
            />
            <button class="rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60 dark:bg-brand-600 dark:hover:bg-brand-700" :disabled="loading.transfer" @click="loadTransferStocks">
              Muat Stok
            </button>
            <button
              class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900"
              :disabled="!canConfirmTransfer"
              @click="openTransferConfirmation"
            >
              Konfirmasi Transfer
            </button>
          </div>

          <div class="grid gap-4 md:grid-cols-3">
            <div class="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950">
              <p class="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Item Terpilih</p>
              <p class="mt-2 text-2xl font-black text-slate-900 dark:text-white">{{ numberLabel(transferSelectionSummary.itemCount) }}</p>
            </div>
            <div class="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950">
              <p class="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Total Qty Transfer</p>
              <p class="mt-2 text-2xl font-black text-slate-900 dark:text-white">{{ numberLabel(transferSelectionSummary.totalQty) }}</p>
            </div>
            <div class="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-100">
              Pilih stok rak Titipan yang sudah dipindahkan fisiknya. Tujuan utama rak Tetap; jika kapasitas penuh, sistem memakai rak Lorong dengan kolom yang sama.
            </div>
          </div>

          <div class="panel overflow-hidden">
            <div class="flex flex-col gap-3 border-b border-slate-200 px-4 py-3 text-sm dark:border-slate-800 sm:flex-row sm:items-center sm:justify-between">
              <p class="text-slate-500 dark:text-slate-400">Daftar ini adalah stok asal rak Titipan. Scan QR barang/pallet atau isi filter agar barang yang tampil sesuai.</p>
              <button
                class="rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900"
                :disabled="!transferRows.length"
                @click="resetTransferSelection"
              >
                Reset Pilihan
              </button>
            </div>
            <div class="overflow-x-auto">
              <table class="min-w-[1200px] w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
                <thead class="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-900 dark:text-slate-400">
                  <tr>
                    <th class="w-14 px-4 py-3">
                      <input
                        type="checkbox"
                        class="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                        :checked="allTransferRowsSelected"
                        :disabled="!transferRows.length"
                        @change="toggleAllTransferRows($event.target.checked)"
                      />
                    </th>
                    <th class="px-4 py-3">Kode</th>
                    <th class="px-4 py-3">Produk</th>
                    <th class="px-4 py-3">Rak Titipan Asal</th>
                    <th class="px-4 py-3">Pallet</th>
                    <th class="px-4 py-3 text-right">Saldo</th>
                    <th class="w-36 px-4 py-3 text-right">Qty Transfer</th>
                    <th class="px-4 py-3">Batch</th>
                    <th class="px-4 py-3">Expired</th>
                    <th class="px-4 py-3">Masuk Gudang</th>
                    <th class="px-4 py-3">Umur</th>
                    <th class="px-4 py-3">Prioritas</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-slate-100 bg-white dark:divide-slate-800 dark:bg-slate-950">
                  <tr v-if="loading.transfer">
                    <td colspan="12" class="px-4 py-10 text-center text-slate-500 dark:text-slate-400">Memuat data...</td>
                  </tr>
                  <tr v-else-if="!transferRows.length">
                    <td colspan="12" class="px-4 py-10 text-center text-slate-500 dark:text-slate-400">Stok titipan untuk transfer belum tersedia.</td>
                  </tr>
                  <tr v-for="(row, index) in transferRows" v-else :key="transferRowKey(row, index)" :class="['text-slate-700 dark:text-slate-200', row.selected ? 'bg-brand-50/70 dark:bg-brand-500/10' : '']">
                    <td class="px-4 py-3">
                      <input
                        type="checkbox"
                        class="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                        :checked="row.selected"
                        @change="toggleTransferRow(row, $event.target.checked)"
                      />
                    </td>
                    <td class="px-4 py-3 font-semibold">{{ row.kode_barang || '-' }}</td>
                    <td class="px-4 py-3">{{ row.nama_barang || '-' }}</td>
                    <td class="px-4 py-3">
                      <span class="font-semibold">{{ row.kode_rak_asal || '-' }}</span>
                      <span class="ml-2 rounded-full bg-sky-100 px-2 py-0.5 text-xs font-bold text-sky-700 dark:bg-sky-500/15 dark:text-sky-200">Titipan</span>
                    </td>
                    <td class="px-4 py-3">
                      <p class="font-semibold">{{ row.pallet_code || row.kode_pallet_list || '-' }}</p>
                      <p v-if="Number(row.pallet_count || 0) > 1 && !row.pallet_code" class="mt-1 text-xs font-semibold text-amber-700 dark:text-amber-200">
                        Scan QR pallet wajib
                      </p>
                      <p v-else-if="row.pallet_code" class="mt-1 text-xs font-semibold text-emerald-700 dark:text-emerald-200">
                        Terverifikasi dari QR
                      </p>
                    </td>
                    <td class="px-4 py-3 text-right">{{ numberLabel(row.qty) }}</td>
                    <td class="px-4 py-3">
                      <input
                        v-model.number="row.transfer_qty"
                        type="number"
                        min="1"
                        :max="Number(row.qty || 0)"
                        class="field text-right"
                        :disabled="!row.selected"
                        @change="clampTransferQty(row)"
                      />
                    </td>
                    <td class="px-4 py-3">{{ row.batch || '-' }}</td>
                    <td class="px-4 py-3">{{ row.expired_date || '-' }}</td>
                    <td class="px-4 py-3">{{ rowTanggalMasuk(row) || '-' }}</td>
                    <td class="px-4 py-3 font-semibold">{{ rowUmurLabel(row) }}</td>
                    <td class="px-4 py-3">
                      <div class="flex flex-col items-start gap-1">
                        <span :class="rowFifoBadge(row).className">{{ rowFifoBadge(row).text }}</span>
                        <span :class="rowFefoBadge(row).className">{{ rowFefoBadge(row).text }}</span>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section v-else-if="activeTab === 'transactions'" class="space-y-5">
          <div class="grid gap-4 md:grid-cols-4">
            <AppFormField v-model="filters.transactionSearch" label="Cari Transaksi" placeholder="Nota, produk, kode" />
            <label class="block">
              <span class="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">Tipe</span>
              <select v-model="filters.transactionType" class="field">
                <option v-for="option in transactionTypeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
            </label>
            <div class="flex items-end">
              <button class="rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60 dark:bg-brand-600 dark:hover:bg-brand-700" :disabled="loading.transactions" @click="loadTransactions">
                Muat Transaksi
              </button>
            </div>
          </div>
          <AppTable :rows="transactionRows" :columns="transactionColumns" :loading="loading.transactions" row-key="Nota" empty-message="Transaksi WMS belum tersedia." />
        </section>

        <section v-else-if="activeTab === 'alerts'" class="space-y-5">
          <button class="rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60 dark:bg-brand-600 dark:hover:bg-brand-700" :disabled="loading.alerts" @click="loadAlerts">
            Muat Alert
          </button>
          <AppTable :rows="alertRows" :columns="alertColumns" :loading="loading.alerts" row-key="kode_rak" empty-message="Alert stok rendah belum tersedia." />
        </section>
      </div>
    </section>

    <AppModal :open="rackModalOpen" :title="rackModalTitle" :description="rackModalDescription" size="xl" @close="rackModalOpen = false">
      <div class="grid gap-4 md:grid-cols-3">
        <AppFormField
          v-model="rackForm.kode_rak"
          label="Kode Rak"
          placeholder="Otomatis dari kode terakhir"
          :readonly="!rackForm.id"
        />
        <AppFormField v-model="rackForm.gudang" label="Gudang" type="number" min="1" />
        <AppFormField v-model="rackForm.rak" label="Rak" type="number" min="1" />
        <AppFormField v-model="rackForm.level" label="Level" type="number" min="0" />
        <AppFormField v-model="rackForm.kolom" label="Kolom" type="number" min="1" />
        <AppFormField v-model="rackForm.nomor_urut" label="Nomor Urut" type="number" min="1" />
        <AppFormField v-model="rackForm.max_qty_karton" label="Kapasitas Karton" type="number" min="0" />
        <AppFormField v-model="rackForm.max_qty_pcs" label="Kapasitas PCS" type="number" min="0" />
        <label class="block">
          <span class="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">Tipe Rak</span>
          <select v-model="rackForm.type_rak" class="field">
            <option value="Tetap">Tetap</option>
            <option value="Titipan">Titipan</option>
            <option value="Lorong">Lorong</option>
          </select>
          <p class="mt-1.5 text-xs font-semibold text-slate-500 dark:text-slate-400">
            Tetap: level 0-1. Titipan: level 2+. Lorong: level 0.
          </p>
        </label>
        <label class="block">
          <span class="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">Mode Principal</span>
          <select v-model="rackForm.mix_mode" class="field">
            <option v-for="option in rackMixModeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
          <p class="mt-1.5 text-xs font-semibold text-slate-500 dark:text-slate-400">
            Single hanya satu principal. Mixed mengikuti group principal.
          </p>
        </label>
        <label class="block">
          <span class="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">Group Principal</span>
          <select v-model="rackForm.id_principal_group" class="field" :disabled="rackForm.mix_mode !== 'mixed_group'">
            <option value="">Pilih group</option>
            <option v-for="option in principalGroupOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
          <button
            type="button"
            class="mt-2 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-bold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900"
            @click="openCreatePrincipalGroupModal"
          >
            Kelola Group
          </button>
        </label>
        <label class="block">
          <span class="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">Status Rak</span>
          <select v-model="rackForm.status_rak" class="field">
            <option value="Kosong">Kosong</option>
            <option value="Isi">Isi</option>
            <option value="Nonaktif">Nonaktif</option>
          </select>
        </label>
        <label class="flex min-h-[68px] items-end gap-2 rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 dark:border-slate-700 dark:text-slate-200">
          <input v-model="rackForm.active" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500" />
          Rak aktif
        </label>
      </div>

      <template #footer>
        <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <button
            v-if="rackForm.id"
            class="rounded-xl border border-rose-200 px-4 py-2.5 text-sm font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50 dark:border-rose-500/40 dark:text-rose-200 dark:hover:bg-rose-500/10"
            :disabled="loading.action"
            @click="removeRack"
          >
            Nonaktifkan Rak
          </button>
          <span v-else class="hidden lg:block"></span>

          <div class="grid gap-2 sm:grid-cols-2 lg:flex lg:flex-row">
            <button class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" :disabled="!rackForm.kode_rak" @click="printSelectedRackQr">
              Cetak QR Rak
            </button>
            <button class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" :disabled="!rackForm.kode_rak" @click="printSelectedRackContents">
              Cetak Isi Rak
            </button>
            <button class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" :disabled="loading.nextRack || Boolean(rackForm.id)" @click="loadNextRackCode">
              {{ loading.nextRack ? 'Mengambil...' : 'Ambil Kode Terakhir' }}
            </button>
            <button class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" @click="resetRackForm">
              Reset Form
            </button>
            <button class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" @click="rackModalOpen = false">
              Batal
            </button>
            <button class="rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60 dark:bg-brand-600 dark:hover:bg-brand-700" :disabled="loading.action" @click="saveRack">
              {{ rackForm.id ? 'Update Rak' : 'Tambah Rak' }}
            </button>
          </div>
        </div>
      </template>
    </AppModal>

    <AppModal
      :open="principalGroupModalOpen"
      :title="principalGroupForm.id ? `Edit Group ${principalGroupForm.kode_group || ''}` : 'Tambah Group Principal'"
      description="Group ini dipakai rak mode Mixed Group agar beberapa principal boleh tercampur dalam satu rak."
      size="xl"
      @close="principalGroupModalOpen = false"
    >
      <div class="grid gap-5 lg:grid-cols-[1fr_1.2fr]">
        <div class="space-y-4">
          <div class="grid gap-4 md:grid-cols-2">
            <AppFormField v-model="principalGroupForm.kode_group" label="Kode Group" placeholder="MIX-A" />
            <AppFormField v-model="principalGroupForm.nama_group" label="Nama Group" placeholder="Mix Area A" />
          </div>
          <label class="block">
            <span class="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">Principal dalam Group</span>
            <select
              v-model="principalGroupForm.principal_ids"
              multiple
              class="field min-h-[180px]"
            >
              <option v-for="option in principalOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
            <p class="mt-1.5 text-xs font-semibold text-slate-500 dark:text-slate-400">
              Tahan Ctrl/Cmd untuk memilih beberapa principal.
            </p>
          </label>
          <AppFormField v-model="principalGroupForm.notes" label="Catatan" placeholder="Opsional" />
          <label class="flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 dark:border-slate-700 dark:text-slate-200">
            <input v-model="principalGroupForm.active" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500" />
            Group aktif
          </label>
        </div>

        <div class="rounded-2xl border border-slate-200 p-3 dark:border-slate-800">
          <div class="mb-3 flex items-center justify-between gap-3">
            <div>
              <p class="text-sm font-bold text-slate-900 dark:text-white">Daftar Group</p>
              <p class="text-xs text-slate-500 dark:text-slate-400">Klik Edit untuk mengubah anggota principal.</p>
            </div>
            <button
              class="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-bold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900"
              :disabled="loading.principalGroups"
              @click="loadPrincipalGroups"
            >
              Refresh
            </button>
          </div>
          <div class="max-h-[320px] space-y-2 overflow-y-auto pr-1">
            <div
              v-for="group in principalGroupRows"
              :key="group.id"
              class="rounded-xl border border-slate-200 p-3 dark:border-slate-800"
            >
              <div class="flex items-start justify-between gap-3">
                <div>
                  <p class="text-sm font-black text-slate-900 dark:text-white">{{ group.kode_group }} - {{ group.nama_group }}</p>
                  <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">{{ group.principal_names || 'Belum ada principal' }}</p>
                </div>
                <button
                  class="rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-bold text-white hover:bg-slate-800 dark:bg-brand-600 dark:hover:bg-brand-700"
                  @click="editPrincipalGroup(group)"
                >
                  Edit
                </button>
              </div>
            </div>
            <p v-if="!principalGroupRows.length" class="rounded-xl border border-dashed border-slate-300 p-4 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
              Belum ada group principal.
            </p>
          </div>
        </div>
      </div>

      <template #footer>
        <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <button
            v-if="principalGroupForm.id"
            class="rounded-xl border border-rose-200 px-4 py-2.5 text-sm font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50 dark:border-rose-500/40 dark:text-rose-200 dark:hover:bg-rose-500/10"
            :disabled="loading.action"
            @click="removePrincipalGroup"
          >
            Hapus / Nonaktifkan
          </button>
          <span v-else></span>
          <div class="flex flex-col gap-2 sm:flex-row">
            <button class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" @click="resetPrincipalGroupForm">
              Reset
            </button>
            <button class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" @click="principalGroupModalOpen = false">
              Tutup
            </button>
            <button class="rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60 dark:bg-brand-600 dark:hover:bg-brand-700" :disabled="loading.action" @click="savePrincipalGroup">
              {{ principalGroupForm.id ? 'Update Group' : 'Tambah Group' }}
            </button>
          </div>
        </div>
      </template>
    </AppModal>

    <AppModal :open="palletModalOpen" :title="palletModalTitle" :description="palletModalDescription" size="xl" @close="palletModalOpen = false">
      <div class="grid gap-4 md:grid-cols-3">
        <AppFormField
          v-model="palletForm.kode_pallet"
          label="Kode Pallet"
          placeholder="Otomatis dari kode terakhir"
          :readonly="!palletForm.id"
        />
        <AppFormField v-model="palletForm.tipe_pallet" label="Tipe Pallet" placeholder="Standard / Plastik / Kayu" />
        <AppFormField v-model="palletForm.berat_kosong_kg" label="Berat Kosong (kg)" type="number" min="0" step="0.001" />
        <AppFormField v-model="palletForm.max_berat_kg" label="Max Berat (kg)" type="number" min="0" step="0.001" />
        <AppFormField v-model="palletForm.max_qty_karton" label="Max Karton" type="number" min="0" />
        <AppFormField v-model="palletForm.max_qty_pcs" label="Max PCS" type="number" min="0" />
        <AppSearchSelect
          v-model="palletForm.selectedProductId"
          label="Produk"
          placeholder="Ketik nama atau kode produk"
          :options="productOptions"
          :loading="loading.products"
          :remote-search="true"
          :max-visible-options="PRODUCT_OPTION_LIMIT"
          empty-text="Produk tidak ditemukan."
          @update:model-value="selectPalletProduct"
          @search="searchProductOptions"
        />
        <AppFormField v-model="palletForm.default_qty_karton" label="Isi Otomatis Karton" type="number" min="0" />
        <AppFormField v-model="palletForm.default_qty_pcs" label="Isi Otomatis PCS" type="number" min="0" />
        <label class="block">
          <span class="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">Status Pallet</span>
          <select v-model="palletForm.status_pallet" class="field">
            <option value="Kosong">Kosong</option>
            <option value="Terisi">Terisi</option>
            <option value="Rusak">Rusak</option>
            <option value="Nonaktif">Nonaktif</option>
          </select>
        </label>
        <label class="flex min-h-[68px] items-end gap-2 rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 dark:border-slate-700 dark:text-slate-200">
          <input v-model="palletForm.active" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500" />
          Pallet aktif
        </label>
        <AppFormField v-model="palletForm.notes" label="Catatan" placeholder="Opsional" />
      </div>
      <p class="mt-3 text-xs font-semibold text-slate-500 dark:text-slate-400">
        Produk boleh kosong untuk pallet umum. Produk, stok, dan rak pada tabel mengikuti detail pallet yang masih bersaldo; rak lama tidak ditampilkan setelah seluruh qty dipindahkan. Isi otomatis dipakai untuk membagi incoming; batas 0 berarti tidak dibatasi.
      </p>

      <template #footer>
        <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <button
            v-if="palletForm.id"
            class="rounded-xl border border-rose-200 px-4 py-2.5 text-sm font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50 dark:border-rose-500/40 dark:text-rose-200 dark:hover:bg-rose-500/10"
            :disabled="loading.action"
            @click="removePallet"
          >
            Nonaktifkan Pallet
          </button>
          <span v-else class="hidden lg:block"></span>

          <div class="grid gap-2 sm:grid-cols-2 lg:flex lg:flex-row">
            <button class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" :disabled="loading.nextPallet || Boolean(palletForm.id)" @click="loadNextPalletCode">
              {{ loading.nextPallet ? 'Mengambil...' : 'Ambil Kode Pallet' }}
            </button>
            <button class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" @click="resetPalletForm">
              Reset Form
            </button>
            <button class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" @click="palletModalOpen = false">
              Batal
            </button>
            <button class="rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60 dark:bg-brand-600 dark:hover:bg-brand-700" :disabled="loading.action" @click="savePallet">
              {{ palletForm.id ? 'Update Pallet' : 'Tambah Pallet' }}
            </button>
          </div>
        </div>
      </template>
    </AppModal>

    <AppModal :open="incomingPalletModalOpen" title="Atur Pallet Incoming" description="Bagi total barang incoming ke satu atau beberapa pallet sebelum QR dicetak. Batch dan expired awal mengikuti data penerimaan PO, lalu dapat disesuaikan per pallet." size="6xl" @close="incomingPalletModalOpen = false">
      <div v-if="incomingPalletRow" class="space-y-5">
        <div class="grid gap-3 md:grid-cols-4">
          <div class="rounded-2xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-900">
            <p class="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Produk</p>
            <p class="mt-2 text-sm font-black text-slate-900 dark:text-white">{{ incomingPalletRow.KodeBarang || incomingPalletRow.KodeStok || '-' }}</p>
            <p class="mt-1 text-xs font-semibold text-slate-500 dark:text-slate-400">{{ incomingPalletRow.NamaBarang || '-' }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-900">
            <p class="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Total Incoming</p>
            <p class="mt-2 text-xl font-black text-slate-900 dark:text-white">{{ numberLabel(incomingPalletExpectedQty) }} PCS</p>
            <p class="mt-1 text-xs font-semibold text-slate-500 dark:text-slate-400">{{ numberLabel(incomingRowQtyCt(incomingPalletRow)) }} CT + {{ numberLabel(incomingRowQtyPc(incomingPalletRow)) }} PC</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-900">
            <p class="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Total Pallet</p>
            <p class="mt-2 text-xl font-black text-slate-900 dark:text-white">{{ numberLabel(incomingPalletTotalQty) }} PCS</p>
            <p class="mt-1 text-xs font-semibold text-slate-500 dark:text-slate-400">{{ numberLabel(incomingPalletLines.length) }} pallet</p>
          </div>
          <div class="rounded-2xl border p-4" :class="incomingPalletRemainingQty === 0 ? 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-100' : 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-100'">
            <p class="text-xs font-bold uppercase tracking-wide">Sisa</p>
            <p class="mt-2 text-xl font-black">{{ numberLabel(incomingPalletRemainingQty) }} PCS</p>
            <p class="mt-1 text-xs font-semibold">Harus 0 sebelum diproses</p>
          </div>
        </div>

        <div class="overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-700">
          <div class="flex flex-col gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-900/70 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p class="text-sm font-semibold text-slate-900 dark:text-slate-100">Pembagian Pallet</p>
              <p class="text-xs text-slate-500 dark:text-slate-400">
                Kosongkan pallet/rak agar sistem memakai master pallet produk dan memilih rak Titipan kosong otomatis.
              </p>
            </div>
            <div class="flex flex-wrap gap-2">
              <button
                type="button"
                class="rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
                @click="autoSplitIncomingPallets"
              >
                Bagi Otomatis
              </button>
              <button
                type="button"
                class="rounded-xl border border-brand-200 bg-brand-50 px-3 py-2 text-sm font-semibold text-brand-700 hover:bg-brand-100 dark:border-brand-500/40 dark:bg-brand-500/10 dark:text-brand-100 dark:hover:bg-brand-500/20"
                @click="addIncomingPalletLine"
              >
                + Tambah Pallet
              </button>
            </div>
          </div>

          <div class="overflow-x-auto">
            <table class="min-w-[1560px] w-full text-left text-sm">
              <thead class="bg-slate-100 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-900 dark:text-slate-400">
                <tr>
                  <th class="min-w-[280px] px-4 py-3">Pallet</th>
                  <th class="min-w-[300px] px-4 py-3">Rak Titipan</th>
                  <th class="min-w-[190px] px-4 py-3">Batch Number</th>
                  <th class="min-w-[180px] px-4 py-3">Expired Date</th>
                  <th class="w-32 px-4 py-3">Qty CT</th>
                  <th class="w-32 px-4 py-3">Qty PC</th>
                  <th class="w-40 px-4 py-3">Berat (kg)</th>
                  <th class="w-32 px-4 py-3 text-right">Total PCS</th>
                  <th class="w-36 px-4 py-3 text-right">Aksi</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-200 dark:divide-slate-800">
                <tr v-for="line in incomingPalletLines" :key="line.uid" class="align-top">
                  <td class="min-w-[280px] px-4 py-3">
                    <AppSearchSelect
                      v-model="line.kode_pallet"
                      label=""
                      placeholder="Otomatis / pilih pallet"
                      :options="palletSelectOptions"
                      :loading="loading.pallets"
                      empty-text="Pallet aktif tidak ditemukan."
                    />
                  </td>
                  <td class="min-w-[300px] px-4 py-3">
                    <AppSearchSelect
                      v-model="line.kode_rak"
                      label=""
                      placeholder="Otomatis / pilih rak titipan"
                      :options="titipanRackSelectOptions"
                      :loading="loading.racks"
                      empty-text="Rak titipan level 2 ke atas tidak ditemukan."
                    />
                  </td>
                  <td class="min-w-[190px] px-4 py-3">
                    <input v-model.trim="line.batch_number" type="text" class="field" placeholder="Dari penerimaan PO" />
                  </td>
                  <td class="min-w-[180px] px-4 py-3">
                    <input v-model="line.expired_date" type="date" class="field" />
                  </td>
                  <td class="px-4 py-3">
                    <input v-model.number="line.qty_ct" type="number" min="0" class="field" />
                  </td>
                  <td class="px-4 py-3">
                    <input v-model.number="line.qty_pc" type="number" min="0" class="field" />
                  </td>
                  <td class="px-4 py-3">
                    <input v-model="line.berat_barang_kg" type="number" min="0" step="0.001" class="field" placeholder="Auto" />
                  </td>
                  <td class="px-4 py-3 text-right font-bold text-slate-900 dark:text-white">
                    {{ numberLabel(incomingLineTotalQty(line)) }}
                  </td>
                  <td class="px-4 py-3 text-right">
                    <div class="flex justify-end gap-2">
                      <button type="button" class="rounded-xl border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" @click="fillIncomingPalletRemaining(line)">
                        Isi Sisa
                      </button>
                      <button type="button" class="rounded-xl border border-rose-200 px-3 py-2 text-xs font-semibold text-rose-700 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-rose-500/40 dark:text-rose-200 dark:hover:bg-rose-500/10" :disabled="incomingPalletLines.length <= 1" @click="removeIncomingPalletLine(line.uid)">
                        Hapus
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <template #footer>
        <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <p class="text-sm font-semibold" :class="incomingPalletRemainingQty === 0 ? 'text-emerald-600 dark:text-emerald-300' : 'text-amber-600 dark:text-amber-300'">
            Total pallet harus sama dengan total incoming.
          </p>
          <div class="flex flex-wrap justify-end gap-2">
            <button class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" @click="incomingPalletModalOpen = false">
              Batal
            </button>
            <button class="rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-brand-600 dark:hover:bg-brand-700" :disabled="!canSubmitIncomingPallets" @click="submitIncomingPallets">
              Proses & Cetak QR
            </button>
          </div>
        </div>
      </template>
    </AppModal>

    <AppModal :open="placementModalOpen" :title="placementModalTitle" :description="placementModalDescription" size="xl" @close="placementModalOpen = false">
      <div class="grid gap-4 md:grid-cols-[minmax(0,2fr)_minmax(180px,1fr)]">
        <AppSearchSelect
          v-model="placementForm.kode_rak"
          label="Kode Rak"
          placeholder="Pilih / ketik kode rak"
          :options="placementRackSelectOptions"
          :loading="loading.racks || loading.rackOptions"
          :remote-search="true"
          :max-visible-options="100"
          empty-text="Rak penyimpanan tidak ditemukan."
          :display-value="placementForm.kode_rak"
          @search="(keyword) => searchRackOptions(keyword)"
        />
        <label class="block">
          <span class="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">Status</span>
          <select v-model="placementForm.status" class="field">
            <option value="READY">READY</option>
            <option value="LOW">LOW</option>
            <option value="EMPTY">EMPTY</option>
            <option value="INACTIVE">INACTIVE</option>
          </select>
        </label>
      </div>
      <p class="mt-2 text-xs text-slate-500 dark:text-slate-400">
        Penempatan manual dapat memakai rak Tetap atau Lorong aktif. Rak Titipan hanya diisi dari proses incoming.
      </p>

      <div class="mt-6 overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-700">
        <div class="flex flex-col gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-900/70 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p class="text-sm font-semibold text-slate-900 dark:text-slate-100">Daftar Barang Dalam Rak</p>
            <p class="text-xs text-slate-500 dark:text-slate-400">Pilih barang per baris. Semua baris akan disimpan ke kode rak yang sama. Isi Total PCS atau Karton; bila keduanya diisi, Total PCS menjadi acuan.</p>
          </div>
          <button
            v-if="!placementForm.id"
            type="button"
            class="rounded-xl border border-brand-200 bg-brand-50 px-3 py-2 text-sm font-semibold text-brand-700 hover:bg-brand-100 dark:border-brand-500/40 dark:bg-brand-500/10 dark:text-brand-100 dark:hover:bg-brand-500/20"
            @click="addPlacementItem"
          >
            + Tambah Barang
          </button>
        </div>

        <div class="overflow-x-auto">
          <table class="min-w-[940px] w-full text-left text-sm">
            <thead class="bg-slate-100 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-900 dark:text-slate-400">
              <tr>
                <th class="px-4 py-3">Barang</th>
                <th class="w-32 px-4 py-3">Qty Karton</th>
                <th class="w-32 px-4 py-3">Total PCS</th>
                <th class="w-40 px-4 py-3">Batch</th>
                <th class="w-44 px-4 py-3">Expired</th>
                <th class="w-20 px-4 py-3 text-right">Aksi</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-200 dark:divide-slate-800">
              <tr v-for="item in placementItems" :key="item.uid" class="align-top">
                <td class="px-4 py-3">
                  <AppSearchSelect
                    :model-value="item.selectedProductId"
                    label=""
                    placeholder="Ketik nama atau kode barang"
                    :options="productOptions"
                    :loading="loading.products"
                    :remote-search="true"
                    :max-visible-options="PRODUCT_OPTION_LIMIT"
                    empty-text="Produk tidak ditemukan."
                    @update:model-value="(value) => selectPlacementItemProduct(item, value)"
                    @search="searchProductOptions"
                  />
                  <p v-if="item.kode_barang" class="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    {{ item.kode_barang }}<span v-if="item.nama_barang"> - {{ item.nama_barang }}</span>
                  </p>
                </td>
                <td class="px-4 py-3">
                  <input v-model.number="item.qty_karton" type="number" min="0" class="field" />
                </td>
                <td class="px-4 py-3">
                  <input v-model.number="item.qty_pcs" type="number" min="0" class="field" />
                </td>
                <td class="px-4 py-3">
                  <input v-model="item.batch_number" type="text" class="field" placeholder="Batch" />
                </td>
                <td class="px-4 py-3">
                  <input v-model="item.expired_date" type="date" class="field" />
                </td>
                <td class="px-4 py-3 text-right">
                  <button
                    type="button"
                    class="rounded-xl border border-rose-200 px-3 py-2 text-xs font-semibold text-rose-700 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-rose-500/40 dark:text-rose-200 dark:hover:bg-rose-500/10"
                    :disabled="placementForm.id || (placementItems.length <= 1 && !item.kode_barang)"
                    @click="removePlacementItem(item.uid)"
                  >
                    Hapus
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <template #footer>
        <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <button
            v-if="placementForm.id"
            class="rounded-xl border border-rose-200 px-4 py-2.5 text-sm font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50 dark:border-rose-500/40 dark:text-rose-200 dark:hover:bg-rose-500/10"
            :disabled="loading.action"
            @click="removePlacement"
          >
            Hapus Penempatan
          </button>
          <span v-else class="hidden lg:block"></span>

          <div class="grid gap-2 sm:grid-cols-2 lg:flex lg:flex-row">
            <button class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" :disabled="!placementForm.kode_rak" @click="printSelectedRackContents">
              Cetak Isi Rak
            </button>
            <button class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" :disabled="!placementForm.kode_rak || !placementForm.kode_barang" @click="printSelectedPlacementItemQr">
              Cetak QR Barang
            </button>
            <button class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" @click="resetPlacementForm">
              Reset Form
            </button>
            <button class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" @click="placementModalOpen = false">
              Batal
            </button>
            <button class="rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60 dark:bg-brand-600 dark:hover:bg-brand-700" :disabled="loading.action" @click="savePlacement">
              {{ placementSaveLabel }}
            </button>
          </div>
        </div>
      </template>
    </AppModal>

    <AppModal :open="transferConfirmOpen" title="Konfirmasi Transfer Rak" description="Pastikan barang sudah dipindahkan fisik dari rak titipan. Jika rak tetap penuh, sistem mengarahkan sisa ke rak Lorong dengan kolom yang sama." size="xl" @close="transferConfirmOpen = false">
      <div class="space-y-4">
        <div class="grid gap-3 sm:grid-cols-3">
          <div class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
            <p class="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Rak Tujuan</p>
            <p class="mt-2 font-black text-slate-900 dark:text-white">{{ filters.transferTargetRack || '-' }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
            <p class="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Item</p>
            <p class="mt-2 font-black text-slate-900 dark:text-white">{{ numberLabel(transferSelectionSummary.itemCount) }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
            <p class="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Total Qty</p>
            <p class="mt-2 font-black text-slate-900 dark:text-white">{{ numberLabel(transferSelectionSummary.totalQty) }}</p>
          </div>
        </div>

        <div class="overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-700">
          <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
            <thead class="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-900 dark:text-slate-400">
              <tr>
                <th class="px-4 py-3">Kode</th>
                <th class="px-4 py-3">Produk</th>
                <th class="px-4 py-3">Asal Titipan</th>
                <th class="px-4 py-3">Pallet</th>
                <th class="px-4 py-3 text-right">Qty Transfer</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 bg-white dark:divide-slate-800 dark:bg-slate-950">
              <tr v-for="(row, index) in selectedTransferRows" :key="`confirm-${transferRowKey(row, index)}`" class="text-slate-700 dark:text-slate-200">
                <td class="px-4 py-3 font-semibold">{{ row.kode_barang || '-' }}</td>
                <td class="px-4 py-3">{{ row.nama_barang || '-' }}</td>
                <td class="px-4 py-3">{{ row.kode_rak_asal || '-' }}</td>
                <td class="px-4 py-3">{{ row.pallet_code || row.kode_pallet_list || '-' }}</td>
                <td class="px-4 py-3 text-right">{{ numberLabel(row.transfer_qty) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <template #footer>
        <div class="flex flex-col gap-3 sm:flex-row sm:justify-end">
          <button class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" :disabled="loading.action" @click="transferConfirmOpen = false">
            Batal
          </button>
          <button class="rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60 dark:bg-brand-600 dark:hover:bg-brand-700" :disabled="loading.action" @click="submitTransfer">
            {{ loading.action ? 'Memproses...' : 'Proses Transfer' }}
          </button>
        </div>
      </template>
    </AppModal>

    <AppModal :open="detailOpen" :title="detailTitle" :description="detailDescription" size="4xl" @close="closeDetail">
      <AppTable :rows="detailRows" :loading="false" row-key="KodeBarang" empty-message="Detail belum tersedia." />
      <template #footer>
        <div class="flex flex-wrap justify-end gap-2">
          <button
            v-if="detailManifest"
            type="button"
            class="rounded-xl bg-violet-700 px-4 py-2.5 text-sm font-bold text-white hover:bg-violet-800 disabled:opacity-60 dark:bg-violet-600 dark:hover:bg-violet-500"
            :disabled="loading.action"
            @click="printManifestDocumentQr(detailManifest)"
          >
            Cetak QR/Barcode Manifest
          </button>
          <button
            type="button"
            class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900"
            @click="closeDetail"
          >
            Tutup
          </button>
        </div>
      </template>
    </AppModal>

    <AppModal :open="scannerOpen" :title="scannerTitle" description="Arahkan kamera HP ke QR WMS sampai payload terbaca otomatis." size="xl" @close="stopQrScanner">
      <div class="overflow-hidden rounded-2xl border border-slate-200 bg-slate-950 dark:border-slate-700">
        <video ref="scannerVideo" class="aspect-video w-full object-cover" playsinline muted></video>
      </div>
      <template #footer>
        <div class="flex justify-end">
          <button class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" @click="stopQrScanner">
            Tutup Kamera
          </button>
        </div>
      </template>
    </AppModal>
  </div>
</template>
