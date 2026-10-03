<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import { getAllCustomers, getBranches, getCompanies, getPrincipals, getSales } from '@/api/master';
import {
  getSalesOrderImportBatch,
  getSalesOrderImportBatches,
  processSalesOrderImportBatch,
  revalidateSalesOrderImportBatch,
  saveCustomerExternalMapping,
  saveProductExternalMapping,
  uploadSalesOrderImportPreview
} from '@/api/dataImport';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getRowBranchId, getRowBranchIds, getRowCompanyId, getRowCompanyIds, isSuperUser, scopeRowsByLoginBranch, scopeSalesRowsByLogin } from '@/utils/accessScope';
import { useAuthStore } from '@/stores/auth';

const auth = useAuthStore();

const invoiceHeaderColumns = [
  'Invoice No',
  'Distributor Code',
  'Distributor Name',
  'Customer Code',
  'Customer Name',
  'Customer Address',
  'Route Code',
  'Route Description',
  'Salesman Code',
  'Salesman Name',
  'Invoice Date',
  'Gross Value',
  'Line Discount',
  'Total Discount',
  'VAT',
  'Net Amount',
  'Invoice Type',
  'Reference Invoice No',
  'Payment Type',
  'Due Date',
  'Order Date',
  'Order No',
  'PO No',
  'Tax No',
  'Branch Code',
  'Branch Name',
  'Principal Code',
  'Principal Name',
  'FOC Discount'
];

const invoiceDetailColumns = [
  'Invoice No',
  'Distributor Code',
  'Customer Code',
  'Route Code',
  'Product Index',
  'Product Code',
  'Product Description',
  'UOM Code',
  'UOM Description',
  'Quantity',
  'Unit Price',
  'Gross Value',
  'Line Discount',
  'Total Discount',
  'VAT',
  'Net Amount',
  'Batch No',
  'Expired Date',
  'Principal Code',
  'Principal Name',
  'FOC Discount'
];

const orderHeaderColumns = Array.from({ length: 28 }, (_, index) => `Kolom ${index + 1}`);
const orderDetailColumns = Array.from({ length: 29 }, (_, index) => `Kolom ${index + 1}`);
orderDetailColumns[5] = 'Kode Produk Eksternal';
orderDetailColumns[17] = 'Kode SKU Produk';

const dataTypes = [
  {
    key: 'invoice-header',
    title: 'Invoice Header',
    badge: 'CSV',
    fileName: 'INVOICE_HDR.csv',
    description: 'Header faktur dari distributor. File memakai delimiter pipe dan memiliki baris header.',
    delimiter: '|',
    hasHeader: true,
    columns: invoiceHeaderColumns,
    requiredColumns: ['Invoice No', 'Distributor Code', 'Customer Code', 'Invoice Date', 'Net Amount'],
    primaryColumns: ['Invoice No'],
    templateRows: []
  },
  {
    key: 'invoice-detail',
    title: 'Invoice Detail',
    badge: 'CSV',
    fileName: 'INVOICE_DTL.csv',
    description: 'Detail produk per faktur. File memakai delimiter pipe dan memiliki baris header.',
    delimiter: '|',
    hasHeader: true,
    columns: invoiceDetailColumns,
    requiredColumns: ['Invoice No', 'Product Code', 'UOM Code', 'Quantity', 'Net Amount'],
    primaryColumns: ['Invoice No', 'Product Index', 'Product Code'],
    templateRows: []
  },
  {
    key: 'order-header',
    title: 'Order Header',
    badge: 'TXT',
    fileName: 'C015_H_ORDER_YYYYMMDDHHMMSS.txt',
    description: 'Header order principal. File memakai delimiter pipe, nilai dikutip, dan tidak memiliki header.',
    delimiter: '|',
    hasHeader: false,
    columns: orderHeaderColumns,
    requiredColumns: ['Kolom 1', 'Kolom 2', 'Kolom 3', 'Kolom 5'],
    primaryColumns: ['Kolom 2'],
    templateRows: [
      [
        'C000015',
        'SIC0152605-00001',
        '2026-05-14',
        'SLS001',
        'CUST001',
        'PO-001',
        '14',
        '1',
        '0',
        '0',
        '100000',
        '0',
        '11000',
        '111000',
        '0',
        '0',
        '0',
        '0',
        '0',
        '0',
        '0',
        '0',
        '0',
        '0',
        '0',
        '0',
        'GT',
        '2306'
      ]
    ]
  },
  {
    key: 'order-detail',
    title: 'Order Detail',
    badge: 'TXT',
    fileName: 'C015_D_ORDER1_YYYYMMDDHHMMSS.txt',
    description: 'Detail order principal. File memakai delimiter pipe, nilai dikutip, dan tidak memiliki header.',
    delimiter: '|',
    hasHeader: false,
    columns: orderDetailColumns,
    requiredColumns: ['Kolom 1', 'Kolom 2', 'Kode SKU Produk', 'Kolom 9'],
    primaryColumns: ['Kolom 2', 'Kode SKU Produk', 'Kolom 7'],
    templateRows: [
      [
        'C000015',
        'SIC0152605-00001',
        '2026-05-14',
        'SLS001',
        'CUST001',
        '4.080401.002',
        '1',
        'PCS',
        '10',
        '10000',
        '100000',
        '0',
        'KKIC007',
        '11000',
        '111000',
        '0',
        '0',
        '0',
        '0',
        '0',
        '0',
        '0',
        '0',
        '0',
        '0',
        '0',
        '0',
        'GT',
        '2306'
      ]
    ]
  }
];

const selectedTypeKey = ref(dataTypes[0].key);
const uploadedFileName = ref('');
const rawContent = ref('');
const rows = ref([]);
const headers = ref([]);
const parseError = ref('');
const successMessage = ref('');
const backendHeaderFile = ref(null);
const backendDetailFile = ref(null);
const backendOrderFiles = ref([]);
const backendAkashaFile = ref(null);
const backendSourceFormat = ref('principal_txt');
const backendLoading = ref(false);
const backendProcessing = ref(false);
const backendRevalidating = ref(false);
const backendError = ref('');
const backendSuccess = ref('');
const backendBatch = ref(null);
const backendRows = ref([]);
const backendBatches = ref([]);
const mappingDrafts = ref({});
const mappingSaving = ref({});
const branches = ref([]);
const companies = ref([]);
const principals = ref([]);
const salesRows = ref([]);
const customers = ref([]);
const importScope = reactive({
  branchId: '',
  companyId: '',
  principalId: '',
  salesId: '',
  customerId: ''
});

const backendSourceFormats = [
  {
    key: 'principal_txt',
    title: 'Principal TXT Header + Detail',
    description: 'Format lama C015_H_ORDER dan C015_D_ORDER1, dua file pipe-delimited.'
  },
  {
    key: 'akasha_odoo_xlsx',
    title: 'Akasha/Odoo Excel',
    description: 'Format export Sales Order .xlsx untuk principal kode 816 PT Akasha Wira, cabang Wonogiri, perusahaan TMP.'
  }
];

const selectedType = computed(() => dataTypes.find((item) => item.key === selectedTypeKey.value) || dataTypes[0]);
const selectedBackendSource = computed(() =>
  backendSourceFormats.find((item) => item.key === backendSourceFormat.value) || backendSourceFormats[0]
);

const loginBranchId = computed(() => getLoginBranchId(auth.user));
const canAccessAllBranches = computed(() => isSuperUser(auth));
const selectedBranch = computed(() => branches.value.find((item) => String(item.id) === String(importScope.branchId || '')));
const selectedBranchCompanyIds = computed(() => {
  if (!importScope.branchId) return [];

  const directCompanyId = getRowCompanyId(selectedBranch.value);
  const relatedCompanyIds = companies.value
    .filter((item) => getRowBranchIds(item).includes(String(importScope.branchId)))
    .map((item) => String(item.id));

  return Array.from(new Set([directCompanyId, ...relatedCompanyIds].filter(Boolean).map(String)));
});

const branchOptions = computed(() =>
  scopeRowsByLoginBranch(branches.value, auth).map((item) => ({
    value: String(item.id),
    label: `${item.kode ? `${item.kode} - ` : ''}${item.nama || `Cabang ${item.id}`}`
  }))
);

const companyOptions = computed(() =>
  companies.value
    .filter((item) => importScope.branchId && selectedBranchCompanyIds.value.includes(String(item.id)))
    .map((item) => ({
      value: String(item.id),
      label: item.nama || item.text || `Perusahaan ${item.id}`
    }))
);

const principalOptions = computed(() =>
  principals.value
    .filter((item) => {
      if (!importScope.companyId) return true;
      const companyIds = getRowCompanyIds(item);
      return !companyIds.length || companyIds.includes(String(importScope.companyId));
    })
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode ? `${item.kode} - ` : ''}${item.nama_principal || item.nama || item.text || `Principal ${item.id}`}`,
      raw: item
    }))
);

const salesOptions = computed(() =>
  scopeSalesRowsByLogin(salesRows.value, auth)
    .filter((item) => !importScope.branchId || String(getRowBranchId(item)) === String(importScope.branchId))
    .filter((item) => {
      const rowCompanyId = getRowCompanyId(item);
      return !importScope.companyId || !rowCompanyId || String(rowCompanyId) === String(importScope.companyId);
    })
    .filter((item) => {
      if (!importScope.principalId) return true;
      const rawAssignedPrincipalIds = item.id_principals || item.id_principal || '';
      if (!rawAssignedPrincipalIds) return true;
      const assignedPrincipalIds = Array.isArray(rawAssignedPrincipalIds)
        ? item.id_principals
        : String(rawAssignedPrincipalIds).split(',');
      return assignedPrincipalIds.map((id) => String(id).trim()).includes(String(importScope.principalId));
    })
    .map((item) => ({
      value: String(item.id_sales || item.id),
      label: item.nama || item.nama_sales || item.text || `Sales ${item.id}`
    }))
);

const customerOptions = computed(() =>
  customers.value
    .filter((item) => !importScope.branchId || String(getRowBranchId(item)) === String(importScope.branchId))
    .slice(0, 500)
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode ? `${item.kode} - ` : ''}${item.nama || item.text || `Customer ${item.id}`}`
    }))
);

const importScopeReady = computed(() => Boolean(importScope.branchId && importScope.companyId && importScope.principalId));

const previewColumns = computed(() => headers.value.slice(0, 10));
const previewRows = computed(() => rows.value.slice(0, 12));

const validation = computed(() => {
  const required = selectedType.value.requiredColumns || [];
  const primaryColumns = selectedType.value.primaryColumns || [];
  const missingRequiredRows = rows.value.filter((row) =>
    required.some((column) => !String(row[column] ?? '').trim())
  ).length;

  const keyMap = new Map();
  rows.value.forEach((row) => {
    const key = primaryColumns.map((column) => String(row[column] ?? '').trim()).join('::');
    if (!key.replace(/:/g, '')) return;
    keyMap.set(key, (keyMap.get(key) || 0) + 1);
  });

  const duplicateKeys = Array.from(keyMap.values()).filter((count) => count > 1).length;

  return {
    totalRows: rows.value.length,
    totalColumns: headers.value.length,
    missingRequiredRows,
    duplicateKeys,
    ready: rows.value.length > 0 && missingRequiredRows === 0
  };
});

function resetPreview() {
  uploadedFileName.value = '';
  rawContent.value = '';
  rows.value = [];
  headers.value = [];
  parseError.value = '';
  successMessage.value = '';
}

function parseDelimitedLine(line, delimiter = '|') {
  const result = [];
  let current = '';
  let inQuotes = false;

  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    const nextChar = line[index + 1];

    if (char === '"' && nextChar === '"') {
      current += '"';
      index += 1;
      continue;
    }

    if (char === '"') {
      inQuotes = !inQuotes;
      continue;
    }

    if (char === delimiter && !inQuotes) {
      result.push(current.trim());
      current = '';
      continue;
    }

    current += char;
  }

  result.push(current.trim());
  return result;
}

function parseContent(content) {
  const config = selectedType.value;
  const lines = content
    .replace(/^\uFEFF/, '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  if (!lines.length) {
    throw new Error('File kosong atau tidak memiliki baris data.');
  }

  const firstLine = parseDelimitedLine(lines[0], config.delimiter);
  const activeHeaders = config.hasHeader ? firstLine : config.columns;
  const dataLines = config.hasHeader ? lines.slice(1) : lines;

  if (!activeHeaders.length) {
    throw new Error('Header/struktur kolom tidak terbaca.');
  }

  const parsedRows = dataLines.map((line, rowIndex) => {
    const values = parseDelimitedLine(line, config.delimiter);
    const row = {
      __rowNumber: config.hasHeader ? rowIndex + 2 : rowIndex + 1
    };

    activeHeaders.forEach((column, columnIndex) => {
      row[column] = values[columnIndex] ?? '';
    });

    row.__columnCount = values.length;
    return row;
  });

  headers.value = activeHeaders;
  rows.value = parsedRows;
}

async function handleUpload(event) {
  const file = event.target.files?.[0];
  if (!file) return;

  parseError.value = '';
  successMessage.value = '';
  uploadedFileName.value = file.name;

  try {
    const content = await file.text();
    rawContent.value = content;
    parseContent(content);
    successMessage.value = `${file.name} berhasil dibaca. ${rows.value.length} baris siap dicek.`;
  } catch (error) {
    rows.value = [];
    headers.value = [];
    parseError.value = error?.message || 'File gagal dibaca.';
  } finally {
    event.target.value = '';
  }
}

function quoteValue(value) {
  const escaped = String(value ?? '').replace(/"/g, '""');
  return `"${escaped}"`;
}

function buildTemplateContent(config) {
  if (config.hasHeader) {
    const header = config.columns.join(config.delimiter);
    return config.templateRows.length
      ? [header, ...config.templateRows.map((row) => row.join(config.delimiter))].join('\n')
      : `${header}\n`;
  }

  return config.templateRows.map((row) => row.map(quoteValue).join(config.delimiter)).join('\n');
}

function downloadText(fileName, content, mimeType = 'text/plain;charset=utf-8') {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function downloadTemplate(config = selectedType.value) {
  downloadText(config.fileName, buildTemplateContent(config));
}

function downloadPreview() {
  if (!rows.value.length) return;

  const output = [
    headers.value.join(selectedType.value.delimiter),
    ...rows.value.map((row) => headers.value.map((column) => row[column] ?? '').join(selectedType.value.delimiter))
  ].join('\n');

  const baseName = uploadedFileName.value.replace(/\.[^.]+$/, '') || selectedType.value.key;
  downloadText(`${baseName}-preview.csv`, output, 'text/csv;charset=utf-8');
}

function formatNumber(value) {
  return new Intl.NumberFormat('id-ID').format(value || 0);
}

function handleBackendHeaderFile(event) {
  backendHeaderFile.value = event.target.files?.[0] || null;
}

function handleBackendDetailFile(event) {
  backendDetailFile.value = event.target.files?.[0] || null;
}

function handleBackendOrderFiles(event) {
  const files = Array.from(event.target.files || []);
  backendOrderFiles.value = files;
  backendHeaderFile.value = files.find((file) => file.name.toUpperCase().includes('_H_ORDER')) || null;
  backendDetailFile.value = files.find((file) => file.name.toUpperCase().includes('_D_ORDER')) || null;
}

function handleBackendAkashaFile(event) {
  backendAkashaFile.value = event.target.files?.[0] || null;
}

function rowText(row, keys = []) {
  return keys
    .map((key) => String(row?.[key] || '').trim())
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
}

function autoSelectAkashaScope() {
  const branch = branchOptions.value.find((item) => item.label.toLowerCase().includes('wonogiri'));
  if (branch) {
    importScope.branchId = branch.value;
    applyBranchScope({ preserveCompany: true });
  }

  const company = companyOptions.value.find((item) => item.label.toLowerCase().includes('tmp') || item.label.toLowerCase().includes('tiga mutiara'));
  if (company) {
    importScope.companyId = company.value;
  }

  const principal = principalOptions.value.find((item) => {
    const text = rowText(item.raw, ['id', 'kode', 'nama', 'nama_principal']);
    return text.includes('816') || text.includes('akasha');
  });
  if (principal) {
    importScope.principalId = principal.value;
  }

  backendSourceFormat.value = 'akasha_odoo_xlsx';
  backendSuccess.value = 'Preset Akasha diterapkan. Cek ulang Cabang, Perusahaan, dan Principal sebelum upload.';
  backendError.value = '';
}

watch(
  () => importScope.branchId,
  () => {
    applyBranchScope();
  }
);

watch(
  () => importScope.companyId,
  () => {
    if (importScope.principalId && !principalOptions.value.some((item) => item.value === String(importScope.principalId))) {
      importScope.principalId = '';
    }
    if (importScope.salesId && !salesOptions.value.some((item) => item.value === String(importScope.salesId))) {
      importScope.salesId = '';
    }
  }
);

async function loadBackendBatches() {
  try {
    const payload = unwrapResponse(await getSalesOrderImportBatches());
    backendBatches.value = normalizeList(payload);
  } catch {
    backendBatches.value = [];
  }
}

async function loadScopeOptions() {
  try {
    const [branchResponse, companyResponse, principalResponse, salesResponse, customerResponse] = await Promise.all([
      getBranches(),
      getCompanies(),
      getPrincipals(),
      getSales(),
      getAllCustomers()
    ]);

    branches.value = normalizeList(unwrapResponse(branchResponse));
    companies.value = normalizeList(unwrapResponse(companyResponse));
    principals.value = normalizeList(unwrapResponse(principalResponse));
    salesRows.value = normalizeList(unwrapResponse(salesResponse));
    customers.value = normalizeList(unwrapResponse(customerResponse));

    if (!canAccessAllBranches.value && loginBranchId.value) {
      importScope.branchId = String(loginBranchId.value);
      applyBranchScope();
    }
  } catch (error) {
    backendError.value = normalizeError(error, 'Data filter import belum berhasil dimuat.');
  }
}

function applyBranchScope({ preserveCompany = false } = {}) {
  if (!importScope.branchId) {
    importScope.companyId = '';
    importScope.principalId = '';
    importScope.salesId = '';
    importScope.customerId = '';
    return;
  }

  const allowedCompanyIds = selectedBranchCompanyIds.value;
  if (!preserveCompany || !allowedCompanyIds.includes(String(importScope.companyId))) {
    importScope.companyId = '';
  }

  if (importScope.principalId && !principalOptions.value.some((item) => item.value === String(importScope.principalId))) {
    importScope.principalId = '';
  }
  if (importScope.salesId && !salesOptions.value.some((item) => item.value === String(importScope.salesId))) {
    importScope.salesId = '';
  }
  if (importScope.customerId && !customerOptions.value.some((item) => item.value === String(importScope.customerId))) {
    importScope.customerId = '';
  }
}

async function selectBackendBatch(batch) {
  backendBatch.value = batch;
  backendError.value = '';
  backendSuccess.value = '';

  try {
    const payload = unwrapResponse(await getSalesOrderImportBatch(batch.id));
    backendBatch.value = payload?.batch || batch;
    backendRows.value = payload?.rows || [];
    prepareMappingDrafts(backendRows.value);
  } catch (error) {
    backendError.value = normalizeError(error, 'Detail batch belum berhasil dimuat.');
  }
}

async function uploadBackendPreview() {
  if (!importScopeReady.value) {
    backendError.value = 'Pilih cabang, perusahaan, dan principal terlebih dahulu sebelum upload import order.';
    return;
  }

  if (backendSourceFormat.value === 'akasha_odoo_xlsx' && !backendAkashaFile.value) {
    backendError.value = 'Pilih file Excel Akasha/Odoo terlebih dahulu.';
    return;
  }

  if (backendSourceFormat.value !== 'akasha_odoo_xlsx' && (!backendHeaderFile.value || !backendDetailFile.value)) {
    backendError.value = 'Pilih file order header dan order detail terlebih dahulu.';
    return;
  }

  backendLoading.value = true;
  backendError.value = '';
  backendSuccess.value = '';

  try {
    const formData = new FormData();
    formData.append('source_format', backendSourceFormat.value);
    if (backendSourceFormat.value === 'akasha_odoo_xlsx') {
      formData.append('excel_file', backendAkashaFile.value);
      formData.append('principal_code', '816');
    } else if (backendOrderFiles.value.length) {
      backendOrderFiles.value.forEach((file) => formData.append('files', file));
    } else {
      formData.append('header_file', backendHeaderFile.value);
      formData.append('detail_file', backendDetailFile.value);
    }
    formData.append('id_cabang', importScope.branchId);
    formData.append('id_perusahaan', importScope.companyId);
    formData.append('id_principal', importScope.principalId);
    if (importScope.salesId) formData.append('id_sales', importScope.salesId);
    if (importScope.customerId) formData.append('id_customer', importScope.customerId);

    const payload = unwrapResponse(await uploadSalesOrderImportPreview(formData));
    backendBatch.value = payload?.batch || null;
    backendRows.value = payload?.rows || [];
    prepareMappingDrafts(backendRows.value);
    backendSuccess.value = `Batch ${backendBatch.value?.import_code || ''} berhasil dibuat.`;
    await loadBackendBatches();
  } catch (error) {
    backendError.value = normalizeError(error, 'Upload import order gagal.');
  } finally {
    backendLoading.value = false;
  }
}

function parseRawData(row) {
  const raw = row?.raw_data;
  if (!raw) return {};
  if (typeof raw === 'string') {
    try {
      return JSON.parse(raw);
    } catch {
      return {};
    }
  }
  return raw;
}

function getExternalCode(row) {
  const raw = parseRawData(row);
  return raw.external_product_code || row.product_code || '';
}

function getMappingExternalCode(row) {
  return row.row_type === 'header' ? row.customer_code || '' : getExternalCode(row);
}

function prepareMappingDrafts(rowList) {
  const nextDrafts = { ...mappingDrafts.value };
  rowList
    .filter((row) => row.validation_status !== 'valid')
    .forEach((row) => {
      if (!nextDrafts[row.id]) {
        nextDrafts[row.id] = {
          kode_external: getMappingExternalCode(row),
          kode_sku: row.product_code || '',
          kode_customer: '',
          id_customer: ''
        };
      }
    });
  mappingDrafts.value = nextDrafts;
}

async function saveMapping(row) {
  const draft = mappingDrafts.value[row.id];
  const targetValue = row.row_type === 'header' ? (draft?.id_customer || draft?.kode_customer) : draft?.kode_sku;

  if (!draft?.kode_external || !targetValue) {
    backendError.value = row.row_type === 'header'
      ? 'Kode external dan customer Budimas wajib dipilih.'
      : 'Kode external dan SKU Budimas wajib diisi.';
    return;
  }

  backendError.value = '';
  backendSuccess.value = '';
  mappingSaving.value = { ...mappingSaving.value, [row.id]: true };

  try {
    const payload = unwrapResponse(
      row.row_type === 'header'
        ? await saveCustomerExternalMapping(draft)
        : await saveProductExternalMapping(draft)
    );
    backendSuccess.value = payload?.message || (row.row_type === 'header' ? 'Mapping customer berhasil disimpan.' : 'Mapping produk berhasil disimpan.');
    if (backendBatch.value?.id) {
      await refreshBackendValidation();
    }
  } catch (error) {
    backendError.value = normalizeError(error, 'Mapping produk gagal disimpan.');
  } finally {
    mappingSaving.value = { ...mappingSaving.value, [row.id]: false };
  }
}

async function refreshBackendValidation() {
  if (!backendBatch.value?.id) return;

  backendRevalidating.value = true;
  backendError.value = '';
  backendSuccess.value = '';

  try {
    const payload = unwrapResponse(await revalidateSalesOrderImportBatch(backendBatch.value.id));
    backendBatch.value = payload?.batch || backendBatch.value;
    backendRows.value = payload?.rows || backendRows.value;
    prepareMappingDrafts(backendRows.value);
    backendSuccess.value = Number(backendBatch.value?.error_count || 0)
      ? 'Validasi batch diperbarui. Masih ada data yang perlu diperbaiki.'
      : 'Validasi batch sudah bersih dan siap diproses ke Sales Order.';
    await loadBackendBatches();
  } catch (error) {
    backendError.value = normalizeError(error, 'Refresh validasi batch gagal.');
  } finally {
    backendRevalidating.value = false;
  }
}

async function processBackendBatch() {
  if (!backendBatch.value?.id) return;

  backendProcessing.value = true;
  backendError.value = '';
  backendSuccess.value = '';

  try {
    const payload = unwrapResponse(await processSalesOrderImportBatch(backendBatch.value.id));
    backendSuccess.value = payload?.message || 'Batch berhasil diproses ke Sales Order.';
    backendBatch.value = {
      ...backendBatch.value,
      status: 'processed',
      processed_order_count: payload?.processed_order_count || 0
    };
    await loadBackendBatches();
  } catch (error) {
    backendError.value = normalizeError(error, 'Proses batch import gagal.');
  } finally {
    backendProcessing.value = false;
  }
}

onMounted(() => {
  loadScopeOptions();
  loadBackendBatches();
});
</script>

<template>
  <PageHeader
    title="Import / Download Data"
    description="Pusat validasi format dan template file invoice/order sebelum data dikirim ke backend."
  >
    <button type="button" class="btn-secondary" @click="downloadTemplate()">Download Template Aktif</button>
  </PageHeader>

  <section class="panel mb-6 flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
    <div>
      <h2 class="text-lg font-bold">Template Excel Order Sales</h2>
      <p class="page-subtitle mt-1">
        Siapkan data order customer dari sales atau admin menggunakan contoh dan panduan pengisian Excel.
      </p>
    </div>
    <RouterLink class="btn-primary shrink-0" to="/data-tools/sales-order-template">Buka Template Order Sales</RouterLink>
  </section>

  <section class="grid gap-4 xl:grid-cols-4">
    <button
      v-for="type in dataTypes"
      :key="type.key"
      type="button"
      class="card text-left transition hover:-translate-y-0.5 hover:border-[var(--color-primary)]"
      :class="{ 'border-[var(--color-primary)] bg-[var(--color-primary-soft)]': selectedTypeKey === type.key }"
      @click="
        selectedTypeKey = type.key;
        resetPreview();
      "
    >
      <div class="mb-4 flex items-start justify-between gap-3">
        <span class="rounded-full bg-[var(--color-surface-muted)] px-3 py-1 text-xs font-bold text-[var(--color-text)]">
          {{ type.badge }}
        </span>
        <span class="text-xs uppercase tracking-[0.24em] text-[var(--color-text-muted)]">
          {{ type.hasHeader ? 'Dengan Header' : 'Headerless' }}
        </span>
      </div>
      <h2 class="text-lg font-bold text-[var(--color-text)]">{{ type.title }}</h2>
      <p class="mt-2 text-sm leading-6 text-[var(--color-text-muted)]">{{ type.description }}</p>
      <button type="button" class="btn-ghost mt-5" @click.stop="downloadTemplate(type)">
        Download {{ type.badge }}
      </button>
    </button>
  </section>

  <section class="card mt-6">
    <div class="grid gap-5 lg:grid-cols-[1.2fr_0.8fr]">
      <div>
        <p class="label">Format Terpilih</p>
        <h2 class="text-2xl font-bold text-[var(--color-text)]">{{ selectedType.title }}</h2>
        <p class="mt-2 text-sm leading-6 text-[var(--color-text-muted)]">{{ selectedType.description }}</p>

        <div class="mt-5 grid gap-3 sm:grid-cols-3">
          <div class="rounded-2xl border border-[var(--color-border)] p-4">
            <p class="label">Delimiter</p>
            <p class="mt-2 text-xl font-bold text-[var(--color-text)]">Pipe (|)</p>
          </div>
          <div class="rounded-2xl border border-[var(--color-border)] p-4">
            <p class="label">Jumlah Kolom</p>
            <p class="mt-2 text-xl font-bold text-[var(--color-text)]">{{ selectedType.columns.length }}</p>
          </div>
          <div class="rounded-2xl border border-[var(--color-border)] p-4">
            <p class="label">Primary Check</p>
            <p class="mt-2 text-sm font-semibold text-[var(--color-text)]">{{ selectedType.primaryColumns.join(' + ') }}</p>
          </div>
        </div>
      </div>

      <div class="rounded-3xl border border-dashed border-[var(--color-border)] bg-[var(--color-surface-muted)] p-5">
        <p class="label">Upload File</p>
        <label class="mt-3 flex cursor-pointer flex-col items-center justify-center rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] px-5 py-8 text-center">
          <span class="text-base font-bold text-[var(--color-text)]">Pilih file untuk preview</span>
          <span class="mt-2 text-sm text-[var(--color-text-muted)]">CSV/TXT pipe-delimited sesuai template.</span>
          <input class="hidden" type="file" accept=".csv,.txt,text/csv,text/plain" @change="handleUpload" />
        </label>
        <p v-if="uploadedFileName" class="mt-3 text-sm text-[var(--color-text-muted)]">
          File aktif: <span class="font-semibold text-[var(--color-text)]">{{ uploadedFileName }}</span>
        </p>
      </div>
    </div>

    <div v-if="successMessage" class="mt-5 rounded-2xl border border-emerald-400/40 bg-emerald-500/10 px-4 py-3 text-sm font-semibold text-emerald-300">
      {{ successMessage }}
    </div>
    <div v-if="parseError" class="mt-5 rounded-2xl border border-rose-400/40 bg-rose-500/10 px-4 py-3 text-sm font-semibold text-rose-300">
      {{ parseError }}
    </div>
  </section>

  <section class="card mt-6">
    <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
      <div>
        <p class="label">Backend Import</p>
        <h2 class="text-2xl font-bold text-[var(--color-text)]">Order Header + Order Detail ke Staging</h2>
        <p class="mt-2 max-w-4xl text-sm leading-6 text-[var(--color-text-muted)]">
          Gunakan bagian ini untuk mengirim file <strong>C015_H_ORDER</strong> dan <strong>C015_D_ORDER1</strong>
          ke backend. Data akan masuk staging dulu, divalidasi, lalu baru bisa diproses ke Sales Order.
        </p>
      </div>
      <button type="button" class="btn-secondary" @click="loadBackendBatches">Reload Batch</button>
    </div>

    <div class="mt-5 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-muted)] p-4">
      <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p class="label">Scope Import</p>
          <p class="mt-1 text-sm text-[var(--color-text-muted)]">
            Pilih scope sebelum upload. Format Akasha memakai principal kode 816 dan file Excel Sales Order dari Odoo.
          </p>
        </div>
        <button type="button" class="btn-secondary whitespace-nowrap" @click="autoSelectAkashaScope">
          Preset Akasha Wonogiri TMP
        </button>
      </div>

      <div class="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        <AppSearchSelect
          v-model="importScope.branchId"
          label="Cabang *"
          placeholder="Pilih cabang"
          :options="branchOptions"
          :disabled="!canAccessAllBranches && !!loginBranchId"
          empty-text="Cabang belum tersedia."
        />
        <AppSearchSelect
          v-model="importScope.companyId"
          label="Perusahaan *"
          :placeholder="importScope.branchId ? 'Pilih perusahaan' : 'Pilih cabang dulu'"
          :options="companyOptions"
          :disabled="!importScope.branchId"
          empty-text="Perusahaan belum tersedia untuk cabang ini."
        />
        <AppSearchSelect
          v-model="importScope.principalId"
          label="Principal *"
          :placeholder="importScope.companyId ? 'Pilih principal' : 'Pilih perusahaan dulu'"
          :options="principalOptions"
          :disabled="!importScope.companyId"
          empty-text="Principal belum tersedia."
        />
        <AppSearchSelect
          v-model="importScope.salesId"
          label="Sales"
          placeholder="Opsional"
          :options="salesOptions"
          :disabled="!importScope.branchId"
          empty-text="Sales belum tersedia."
        />
        <AppSearchSelect
          v-model="importScope.customerId"
          label="Customer"
          placeholder="Opsional"
          :options="customerOptions"
          :disabled="!importScope.branchId"
          empty-text="Customer belum tersedia."
        />
      </div>
      <p class="mt-3 text-xs text-[var(--color-text-muted)]">
        Cabang, perusahaan, dan principal wajib dipilih. Sales dan customer hanya dipakai untuk membatasi file satu sales/customer;
        untuk file banyak customer, biarkan customer kosong lalu gunakan mapping pada tabel validasi jika kode eksternal belum dikenal.
      </p>
    </div>

    <div class="mt-5 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-muted)] p-4">
      <p class="label">Format Sumber</p>
      <div class="mt-3 grid gap-3 lg:grid-cols-2">
        <button
          v-for="source in backendSourceFormats"
          :key="source.key"
          type="button"
          class="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-left transition hover:border-[var(--color-primary)]"
          :class="{ 'border-[var(--color-primary)] bg-[var(--color-primary-soft)]': backendSourceFormat === source.key }"
          @click="backendSourceFormat = source.key"
        >
          <p class="font-bold text-[var(--color-text)]">{{ source.title }}</p>
          <p class="mt-2 text-sm leading-6 text-[var(--color-text-muted)]">{{ source.description }}</p>
        </button>
      </div>
      <p class="mt-3 text-xs text-[var(--color-text-muted)]">
        Format aktif: <span class="font-semibold text-[var(--color-text)]">{{ selectedBackendSource.title }}</span>
      </p>
    </div>

    <div class="mt-5 grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
      <label v-if="backendSourceFormat === 'akasha_odoo_xlsx'" class="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-muted)] p-4">
        <span class="label">File Excel Akasha/Odoo</span>
        <input class="mt-3 w-full text-sm text-[var(--color-text)]" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" @change="handleBackendAkashaFile" />
        <span class="mt-2 block text-xs text-[var(--color-text-muted)]">
          Upload file <strong>Sales Order (sale.order).xlsx</strong>. Satu order dengan beberapa baris produk akan digabung otomatis.
        </span>
      </label>
      <label v-else class="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-muted)] p-4">
        <span class="label">Pilih 2 File Sekaligus</span>
        <input class="mt-3 w-full text-sm text-[var(--color-text)]" type="file" accept=".txt,text/plain" multiple @change="handleBackendOrderFiles" />
        <span class="mt-2 block text-xs text-[var(--color-text-muted)]">
          Backend otomatis mengenali file <strong>H_ORDER</strong> sebagai header dan <strong>D_ORDER</strong> sebagai detail.
        </span>
      </label>
      <div class="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-muted)] p-4">
        <p class="label">File Terbaca</p>
        <template v-if="backendSourceFormat === 'akasha_odoo_xlsx'">
          <p class="mt-3 text-sm text-[var(--color-text)]">
            Excel: <span class="font-semibold">{{ backendAkashaFile?.name || '-' }}</span>
          </p>
          <p class="mt-2 text-xs leading-5 text-[var(--color-text-muted)]">
            Output staging akan dibuat sebagai Sales Order draft, lalu admin/fakturis tetap melakukan konfirmasi dari halaman order.
          </p>
        </template>
        <template v-else>
          <p class="mt-3 text-sm text-[var(--color-text)]">
            Header: <span class="font-semibold">{{ backendHeaderFile?.name || '-' }}</span>
          </p>
          <p class="mt-2 text-sm text-[var(--color-text)]">
            Detail: <span class="font-semibold">{{ backendDetailFile?.name || '-' }}</span>
          </p>
        </template>
      </div>
    </div>

    <div class="mt-5 flex flex-wrap gap-3">
      <button type="button" class="btn-primary" :disabled="backendLoading" @click="uploadBackendPreview">
        {{ backendLoading ? 'Mengupload...' : 'Upload ke Staging' }}
      </button>
      <button
        type="button"
        class="btn-secondary"
        :disabled="!backendBatch?.id || backendBatch?.status === 'processed' || backendProcessing || backendRevalidating"
        @click="processBackendBatch"
      >
        {{ backendProcessing ? 'Memproses...' : 'Proses ke Sales Order' }}
      </button>
      <button
        type="button"
        class="btn-secondary"
        :disabled="!backendBatch?.id || backendBatch?.status === 'processed' || backendProcessing || backendRevalidating"
        @click="refreshBackendValidation"
      >
        {{ backendRevalidating ? 'Validasi...' : 'Refresh Validasi' }}
      </button>
    </div>

    <div v-if="backendSuccess" class="mt-5 rounded-2xl border border-emerald-400/40 bg-emerald-500/10 px-4 py-3 text-sm font-semibold text-emerald-300">
      {{ backendSuccess }}
    </div>
    <div v-if="backendError" class="mt-5 rounded-2xl border border-rose-400/40 bg-rose-500/10 px-4 py-3 text-sm font-semibold text-rose-300">
      {{ backendError }}
    </div>

    <div v-if="backendBatch" class="mt-5 grid gap-4 md:grid-cols-5">
      <div class="rounded-2xl border border-[var(--color-border)] p-4">
        <p class="label">Batch</p>
        <p class="mt-2 font-bold text-[var(--color-text)]">{{ backendBatch.import_code }}</p>
      </div>
      <div class="rounded-2xl border border-[var(--color-border)] p-4">
        <p class="label">Status</p>
        <p class="mt-2 font-bold text-[var(--color-text)]">{{ backendBatch.status }}</p>
      </div>
      <div class="rounded-2xl border border-[var(--color-border)] p-4">
        <p class="label">Header Valid</p>
        <p class="mt-2 font-bold text-[var(--color-text)]">{{ backendBatch.valid_header }} / {{ backendBatch.total_header }}</p>
      </div>
      <div class="rounded-2xl border border-[var(--color-border)] p-4">
        <p class="label">Detail Valid</p>
        <p class="mt-2 font-bold text-[var(--color-text)]">{{ backendBatch.valid_detail }} / {{ backendBatch.total_detail }}</p>
      </div>
      <div class="rounded-2xl border border-[var(--color-border)] p-4">
        <p class="label">Error</p>
        <p class="mt-2 font-bold" :class="Number(backendBatch.error_count || 0) ? 'text-rose-300' : 'text-emerald-300'">
          {{ backendBatch.error_count }}
        </p>
      </div>
    </div>

    <div v-if="backendRows.length" class="mt-5 overflow-x-auto rounded-2xl border border-[var(--color-border)]">
      <table class="min-w-full text-left text-sm">
        <thead class="bg-[var(--color-surface-muted)] text-xs uppercase tracking-[0.12em] text-[var(--color-text-muted)]">
          <tr>
            <th class="px-4 py-4">Tipe</th>
            <th class="px-4 py-4">Baris</th>
            <th class="px-4 py-4">No Order</th>
            <th class="px-4 py-4">Customer</th>
            <th class="px-4 py-4">Kode External</th>
            <th class="px-4 py-4">Produk</th>
            <th class="px-4 py-4">Status</th>
            <th class="px-4 py-4">Catatan</th>
            <th class="px-4 py-4">Mapping</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-[var(--color-border)]">
          <tr v-for="row in backendRows.slice(0, 20)" :key="row.id">
            <td class="px-4 py-4 text-[var(--color-text)]">{{ row.row_type }}</td>
            <td class="px-4 py-4 text-[var(--color-text-muted)]">{{ row.row_number }}</td>
            <td class="px-4 py-4 font-semibold text-[var(--color-text)]">{{ row.order_no || '-' }}</td>
            <td class="px-4 py-4 text-[var(--color-text)]">{{ row.customer_code || '-' }}</td>
            <td class="px-4 py-4 text-[var(--color-text-muted)]">{{ getExternalCode(row) || '-' }}</td>
            <td class="px-4 py-4 text-[var(--color-text)]">{{ row.product_code || '-' }}</td>
            <td class="px-4 py-4">
              <span
                class="rounded-full px-3 py-1 text-xs font-bold"
                :class="row.validation_status === 'valid' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-rose-500/15 text-rose-300'"
              >
                {{ row.validation_status }}
              </span>
            </td>
            <td class="max-w-[360px] px-4 py-4 text-[var(--color-text-muted)]">{{ row.validation_message || '-' }}</td>
            <td class="min-w-[320px] px-4 py-4">
              <div v-if="row.validation_status !== 'valid'" class="flex items-center gap-2">
                <AppSearchSelect
                  v-if="row.row_type === 'header'"
                  v-model="mappingDrafts[row.id].id_customer"
                  class="min-w-[260px]"
                  label=""
                  placeholder="Kode customer Budimas"
                  :options="customerOptions"
                  empty-text="Customer tidak ditemukan di cabang ini."
                />
                <input
                  v-else
                  v-model="mappingDrafts[row.id].kode_sku"
                  class="input h-10 min-w-[150px]"
                  placeholder="SKU Budimas"
                />
                <button type="button" class="btn-primary h-10 whitespace-nowrap" :disabled="mappingSaving[row.id]" @click="saveMapping(row)">
                  {{ mappingSaving[row.id] ? 'Simpan...' : 'Simpan' }}
                </button>
              </div>
              <span v-else class="text-xs text-[var(--color-text-muted)]">-</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="backendBatches.length" class="mt-5">
      <h3 class="font-bold text-[var(--color-text)]">Batch Terakhir</h3>
      <div class="mt-3 grid gap-3 lg:grid-cols-3">
        <button
          v-for="batch in backendBatches.slice(0, 6)"
          :key="batch.id"
          type="button"
          class="rounded-2xl border border-[var(--color-border)] p-4 text-left hover:border-[var(--color-primary)]"
          @click="selectBackendBatch(batch)"
        >
          <p class="font-bold text-[var(--color-text)]">{{ batch.import_code }}</p>
          <p class="mt-1 text-xs text-[var(--color-text-muted)]">
            {{ batch.status }} - error {{ batch.error_count }} - detail {{ batch.total_detail }}
          </p>
        </button>
      </div>
    </div>
  </section>

  <section class="mt-6 grid gap-4 md:grid-cols-4">
    <div class="card">
      <p class="label">Total Baris</p>
      <p class="mt-3 text-2xl font-bold text-[var(--color-text)]">{{ formatNumber(validation.totalRows) }}</p>
    </div>
    <div class="card">
      <p class="label">Kolom Terbaca</p>
      <p class="mt-3 text-2xl font-bold text-[var(--color-text)]">{{ formatNumber(validation.totalColumns) }}</p>
    </div>
    <div class="card">
      <p class="label">Wajib Kosong</p>
      <p class="mt-3 text-2xl font-bold" :class="validation.missingRequiredRows ? 'text-rose-300' : 'text-emerald-300'">
        {{ formatNumber(validation.missingRequiredRows) }}
      </p>
    </div>
    <div class="card">
      <p class="label">Duplikat Key</p>
      <p class="mt-3 text-2xl font-bold" :class="validation.duplicateKeys ? 'text-amber-300' : 'text-emerald-300'">
        {{ formatNumber(validation.duplicateKeys) }}
      </p>
    </div>
  </section>

  <section class="card mt-6 overflow-hidden p-0">
    <div class="flex flex-col gap-3 border-b border-[var(--color-border)] p-5 lg:flex-row lg:items-center lg:justify-between">
      <div>
        <h2 class="text-xl font-bold text-[var(--color-text)]">Preview Data</h2>
        <p class="mt-1 text-sm text-[var(--color-text-muted)]">
          Menampilkan maksimal 12 baris pertama dan 10 kolom pertama agar file besar tetap ringan dibuka.
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <button type="button" class="btn-secondary" :disabled="!rows.length" @click="downloadPreview">Download Preview</button>
        <button type="button" class="btn-primary" :disabled="!validation.ready">
          Siap Import
        </button>
      </div>
    </div>

    <div v-if="!rows.length" class="p-8 text-center text-sm text-[var(--color-text-muted)]">
      Upload file {{ selectedType.title }} untuk melihat preview di sini.
    </div>

    <div v-else class="overflow-x-auto">
      <table class="min-w-full text-left text-sm">
        <thead class="bg-[var(--color-surface-muted)] text-xs uppercase tracking-[0.12em] text-[var(--color-text-muted)]">
          <tr>
            <th class="px-4 py-4">Baris</th>
            <th v-for="column in previewColumns" :key="column" class="px-4 py-4">{{ column }}</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-[var(--color-border)]">
          <tr v-for="row in previewRows" :key="row.__rowNumber" class="hover:bg-[var(--color-surface-muted)]">
            <td class="px-4 py-4 font-semibold text-[var(--color-text-muted)]">{{ row.__rowNumber }}</td>
            <td v-for="column in previewColumns" :key="column" class="max-w-[220px] truncate px-4 py-4 text-[var(--color-text)]">
              {{ row[column] || '-' }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>

  <section class="card mt-6">
    <h2 class="text-xl font-bold text-[var(--color-text)]">Catatan Integrasi</h2>
    <p class="mt-2 text-sm leading-6 text-[var(--color-text-muted)]">
      Halaman ini saat ini diposisikan sebagai gerbang validasi dan download template. Tombol import ke backend bisa
      disambungkan setelah endpoint final disepakati, supaya tidak ada data invoice/order yang masuk parsial.
    </p>
  </section>
</template>
