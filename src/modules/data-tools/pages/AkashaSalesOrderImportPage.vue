<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import PageHeader from '@/shared/components/PageHeader.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import {
  processSalesOrderImportBatch,
  revalidateSalesOrderImportBatch,
  saveCustomerExternalMapping,
  uploadSalesOrderImportPreview
} from '@/api/dataImport';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getRowBranchIds, getRowCompanyIds, scopeRowsByLoginBranch } from '@/utils/accessScope';
import { useAuthStore } from '@/stores/auth';

const auth = useAuthStore();
const route = useRoute();

const AKASHA_PRINCIPAL_CODE = '816';

const importConfig = computed(() => ({
  key: route.meta.importSourceKey || 'tmp',
  companyCode: String(route.meta.importCompanyCode || 'TMP').toUpperCase(),
  companyLabel: route.meta.importCompanyLabel || 'TMP',
  sourceServer: route.meta.importSourceServer || '192.168.5.243',
  sourceFormat: route.meta.importSourceFormat || 'akasha_odoo_xlsx',
  principalCode: String(route.meta.importPrincipalCode || AKASHA_PRINCIPAL_CODE),
  principalName: String(route.meta.importPrincipalName || 'akasha'),
  fileLabel: route.meta.importFileLabel || 'File Sales Order (.xlsx)',
  fileAccept: route.meta.importFileAccept || '.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  uploadLabel: route.meta.importUploadLabel || 'Upload File Sales Order Akasha',
  multipleFiles: Boolean(route.meta.importMultipleFiles),
  presetLabel: route.meta.importPresetLabel || 'Preset Akasha',
  title: route.meta.pageTitle || 'Import Sales Order Akasha TMP',
  description: route.meta.pageDescription || 'Upload file Sales Order Excel Akasha/Odoo untuk source TMP, preview validasi, lalu proses menjadi Sales Order.'
}));

const branches = ref([]);
const companies = ref([]);
const principals = ref([]);
const selectedFile = ref(null);
const batch = ref(null);
const rows = ref([]);
const loadingScope = ref(false);
const previewing = ref(false);
const processing = ref(false);
const revalidating = ref(false);
const resolvingCustomerId = ref('');
const syncingScopeFromPreview = ref(false);
const errorMessage = ref('');
const successMessage = ref('');

const form = reactive({
  companyId: '',
  branchId: '',
  principalId: ''
});

const branchOptions = computed(() =>
  scopeRowsByLoginBranch(branches.value, auth).map((item) => ({
    value: String(item.id),
    label: `${item.kode ? `${item.kode} - ` : ''}${item.nama || `Cabang ${item.id}`}`,
    raw: item
  }))
);

const selectedBranch = computed(() =>
  branchOptions.value.find((item) => String(item.value) === String(form.branchId))?.raw
);

const selectedBranchCompanyIds = computed(() => {
  if (!selectedBranch.value) return [];
  return getRowCompanyIds(selectedBranch.value).map(String);
});

const companyOptions = computed(() =>
  companies.value
    .filter((item) => {
      if (!form.branchId || !selectedBranchCompanyIds.value.length) return true;
      return selectedBranchCompanyIds.value.includes(String(item.id));
    })
    .map((item) => ({
      value: String(item.id),
      label: item.nama || item.text || `Perusahaan ${item.id}`,
      raw: item
    }))
);

const principalOptions = computed(() =>
  principals.value
    .filter((item) => {
      const code = String(item.kode || '').trim();
      const name = String(item.nama_principal || item.nama || item.text || '').toLowerCase();
      const targetCode = String(importConfig.value.principalCode || '').trim();
      const targetName = String(importConfig.value.principalName || '').trim().toLowerCase();
      if (targetCode && code.toLowerCase() === targetCode.toLowerCase()) return true;
      if (targetName && name.includes(targetName)) return true;
      if (!form.companyId) return true;
      const companyIds = getRowCompanyIds(item);
      return !companyIds.length || companyIds.includes(String(form.companyId));
    })
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode ? `${item.kode} - ` : ''}${item.nama_principal || item.nama || item.text || `Principal ${item.id}`}`,
      raw: item
    }))
);

const targetPrincipal = computed(() =>
  principalOptions.value.find((item) => {
    const code = String(item.raw?.kode || '').trim();
    const name = String(item.raw?.nama_principal || item.raw?.nama || item.label || '').toLowerCase();
    const targetCode = String(importConfig.value.principalCode || '').trim();
    const targetName = String(importConfig.value.principalName || '').trim().toLowerCase();
    return (targetCode && code.toLowerCase() === targetCode.toLowerCase()) || (targetName && name.includes(targetName));
  })
);

const principalMissing = computed(() => !targetPrincipal.value && !form.principalId);

const fileName = computed(() => selectedFile.value?.name || '-');
const selectedFiles = computed(() => {
  if (!selectedFile.value) return [];
  return Array.isArray(selectedFile.value) ? selectedFile.value : [selectedFile.value];
});
const fileNames = computed(() => {
  if (!selectedFiles.value.length) return '-';
  return selectedFiles.value.map((file) => file.name).join(' + ');
});

const headerRows = computed(() => rows.value.filter((row) => row.row_type === 'header'));
const detailRows = computed(() => rows.value.filter((row) => row.row_type === 'detail'));

const detailCountByOrder = computed(() => {
  const counts = new Map();
  detailRows.value.forEach((row) => {
    const key = row.order_no || '';
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  return counts;
});

const errorCountByOrder = computed(() => {
  const counts = new Map();
  detailRows.value.forEach((row) => {
    if (row.validation_status === 'valid') return;
    const key = row.order_no || '';
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  return counts;
});

const headerPreviewRows = computed(() =>
  headerRows.value.map((row) => ({
    ...row,
    item_count: detailCountByOrder.value.get(row.order_no || '') || 0,
    detail_error_count: errorCountByOrder.value.get(row.order_no || '') || 0
  }))
);

const customerConflictRows = computed(() =>
  headerPreviewRows.value
    .filter((row) => row.raw_data?._customer_conflict?.candidates?.length)
    .map((row) => ({
      ...row,
      conflict: row.raw_data._customer_conflict
    }))
);

const summary = computed(() => {
  const errorRows = rows.value.filter((row) => row.validation_status !== 'valid').length;
  return {
    orders: headerRows.value.length,
    details: detailRows.value.length,
    validOrders: headerPreviewRows.value.filter(
      (row) => row.validation_status === 'valid' && !row.detail_error_count
    ).length,
    errors: errorRows
  };
});

const canPreview = computed(() =>
  Boolean(
    !previewing.value
      && (
        importConfig.value.multipleFiles
          ? selectedFiles.value.length >= 2
          : selectedFiles.value.length >= 1
      )
  )
);

const canImport = computed(() =>
  Boolean(batch.value?.id && Number(batch.value?.error_count || summary.value.errors || 0) === 0 && batch.value?.status !== 'processed' && !processing.value)
);

const scopedCustomerMappingSource = computed(() => {
  if (form.companyId && form.branchId) {
    return `sales_order_import:p${form.companyId}:c${form.branchId}`;
  }
  if (form.companyId) {
    return `sales_order_import:p${form.companyId}`;
  }
  return 'sales_order_import';
});

function formatCurrency(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number)) return value || '-';
  return new Intl.NumberFormat('id-ID', {
    style: 'currency',
    currency: 'IDR',
    maximumFractionDigits: 0
  }).format(number);
}

function normalizeText(value) {
  return String(value || '').trim().toLowerCase();
}

function resetPreview() {
  batch.value = null;
  rows.value = [];
  successMessage.value = '';
  errorMessage.value = '';
}

function handleFile(event) {
  const files = Array.from(event.target.files || []);
  selectedFile.value = importConfig.value.multipleFiles ? files : (files[0] || null);
  resetPreview();
  if (selectedFiles.value.length) {
    applyAkashaPreset();
  }
}

function applyAkashaPreset() {
  const sourceCode = normalizeText(importConfig.value.companyCode);
  const sourceLabel = normalizeText(importConfig.value.companyLabel);
  const company = companyOptions.value.find((item) => {
    const text = normalizeText(`${item.label} ${item.raw?.kode || ''}`);
    if (sourceCode === 'BMM') {
      return text.includes('bmm') || text.includes('budimas');
    }
    if (sourceCode === 'TMP') {
      return text.includes('tmp') || text.includes('tiga mutiara');
    }
    return text.includes(sourceCode) || text.includes(sourceLabel);
  });
  if (company) {
    form.companyId = company.value;
  }

  if (targetPrincipal.value) {
    form.principalId = targetPrincipal.value.value;
  }
}

async function loadScope() {
  loadingScope.value = true;
  errorMessage.value = '';
  try {
    const [branchResponse, companyResponse, principalResponse] = await Promise.all([
      getBranches(),
      getCompanies(),
      getPrincipals()
    ]);

    branches.value = normalizeList(unwrapResponse(branchResponse));
    companies.value = normalizeList(unwrapResponse(companyResponse));
    principals.value = normalizeList(unwrapResponse(principalResponse));
    applyAkashaPreset();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Data perusahaan, cabang, dan principal belum berhasil dimuat.');
  } finally {
    loadingScope.value = false;
  }
}

function syncPrincipalPreset() {
  if (form.principalId && principalOptions.value.some((item) => String(item.value) === String(form.principalId))) {
    return;
  }
  form.principalId = targetPrincipal.value?.value || '';
}

function pickOrderPairFiles(files) {
  const headerFile = files.find((file) => {
    const name = file.name.toLowerCase();
    return name.includes('header') || name.includes('h_order');
  }) || files[0];
  const detailFile = files.find((file) => {
    const name = file.name.toLowerCase();
    return name.includes('detail') || name.includes('d_order');
  }) || files.find((file) => file !== headerFile) || files[1];
  return { headerFile, detailFile };
}

watch(
  () => form.branchId,
  () => {
    if (syncingScopeFromPreview.value) return;
    if (form.companyId && !companyOptions.value.some((item) => String(item.value) === String(form.companyId))) {
      form.companyId = '';
    }
    syncPrincipalPreset();
    resetPreview();
  }
);

watch(
  () => form.companyId,
  () => {
    if (syncingScopeFromPreview.value) return;
    syncPrincipalPreset();
    resetPreview();
  }
);

watch(
  () => form.principalId,
  () => {
    if (syncingScopeFromPreview.value) return;
    resetPreview();
  }
);

watch(
  () => route.name,
  () => {
    syncingScopeFromPreview.value = true;
    form.companyId = '';
    form.branchId = '';
    form.principalId = '';
    syncingScopeFromPreview.value = false;
    resetPreview();
    applyAkashaPreset();
  }
);

function findRawLabel(collection, id, formatter) {
  const item = collection.value.find((row) => String(row.id) === String(id));
  if (!item) return '';
  return formatter(item);
}

function scopeChangeLabel(field, id) {
  if (!id) return '';
  if (field === 'branchId') {
    return findRawLabel(branches, id, (item) => `${item.kode ? `${item.kode} - ` : ''}${item.nama || `Cabang ${item.id}`}`);
  }
  if (field === 'companyId') {
    return findRawLabel(companies, id, (item) => item.nama || item.text || `Perusahaan ${item.id}`);
  }
  if (field === 'principalId') {
    return findRawLabel(principals, id, (item) => `${item.kode ? `${item.kode} - ` : ''}${item.nama_principal || item.nama || item.text || `Principal ${item.id}`}`);
  }
  return '';
}

async function applyScopeFromBatch(batchRow) {
  if (!batchRow) return [];

  const before = {
    companyId: form.companyId,
    branchId: form.branchId,
    principalId: form.principalId
  };

  syncingScopeFromPreview.value = true;
  if (batchRow.id_perusahaan) form.companyId = String(batchRow.id_perusahaan);
  if (batchRow.id_cabang) form.branchId = String(batchRow.id_cabang);
  if (batchRow.id_principal) form.principalId = String(batchRow.id_principal);
  await nextTick();
  syncingScopeFromPreview.value = false;

  const changes = [];
  if (before.companyId !== form.companyId) {
    changes.push(scopeChangeLabel('companyId', form.companyId) || `perusahaan ${form.companyId}`);
  }
  if (before.branchId !== form.branchId) {
    changes.push(scopeChangeLabel('branchId', form.branchId) || `cabang ${form.branchId}`);
  }
  if (before.principalId !== form.principalId) {
    changes.push(scopeChangeLabel('principalId', form.principalId) || `principal ${form.principalId}`);
  }
  return changes.filter(Boolean);
}

async function previewImport() {
  if (!canPreview.value) {
    errorMessage.value = `Pilih ${importConfig.value.fileLabel.toLowerCase()} terlebih dahulu.`;
    successMessage.value = '';
    return;
  }

  previewing.value = true;
  errorMessage.value = '';
  successMessage.value = '';

  const formData = new FormData();
  formData.append('source_format', importConfig.value.sourceFormat);
  formData.append('principal_code', importConfig.value.principalCode);
  formData.append('principal_name', importConfig.value.principalName);
  formData.append('company_code', importConfig.value.companyCode);
  if (['bosnet_hidro_csv', 'ufit_order_txt'].includes(importConfig.value.sourceFormat)) {
    const { headerFile, detailFile } = pickOrderPairFiles(selectedFiles.value);
    formData.append('header_file', headerFile);
    formData.append('detail_file', detailFile);
  } else if (importConfig.value.sourceFormat === 'godrej_rd_txt') {
    formData.append('txt_file', selectedFiles.value[0]);
  } else if (importConfig.value.sourceFormat === 'onesky_sosro_csv') {
    formData.append('csv_file', selectedFiles.value[0]);
  } else {
    formData.append('excel_file', selectedFiles.value[0]);
  }
  if (form.branchId) formData.append('id_cabang', form.branchId);
  if (form.companyId) formData.append('id_perusahaan', form.companyId);
  if (form.principalId) formData.append('id_principal', form.principalId);

  try {
    const payload = unwrapResponse(await uploadSalesOrderImportPreview(formData));
    const scopeChanges = await applyScopeFromBatch(payload?.batch);
    batch.value = payload?.batch || null;
    rows.value = payload?.rows || [];
    const scopeMessage = scopeChanges.length ? ` Scope mengikuti file: ${scopeChanges.join(', ')}.` : '';
    successMessage.value = `Preview ${importConfig.value.companyLabel} berhasil. ${summary.value.orders} order dan ${summary.value.details} item terbaca.${scopeMessage}`;
  } catch (error) {
    batch.value = null;
    rows.value = [];
    errorMessage.value = normalizeError(error, `Preview import ${importConfig.value.companyLabel} belum berhasil.`);
  } finally {
    previewing.value = false;
  }
}

async function refreshValidation() {
  if (!batch.value?.id) return;
  revalidating.value = true;
  errorMessage.value = '';
  successMessage.value = '';

  try {
    const payload = unwrapResponse(await revalidateSalesOrderImportBatch(batch.value.id));
    batch.value = payload?.batch || batch.value;
    rows.value = payload?.rows || rows.value;
    successMessage.value = `Validasi import ${importConfig.value.companyLabel} sudah diperbarui.`;
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Refresh validasi belum berhasil.');
  } finally {
    revalidating.value = false;
  }
}

async function processImport() {
  if (!canImport.value) {
    errorMessage.value = batch.value?.id
      ? 'Masih ada error validasi. Perbaiki mapping/customer/produk dulu lalu refresh validasi.'
      : 'Preview file terlebih dahulu sebelum import.';
    successMessage.value = '';
    return;
  }

  processing.value = true;
  errorMessage.value = '';
  successMessage.value = '';

  try {
    const payload = unwrapResponse(await processSalesOrderImportBatch(batch.value.id));
    batch.value = {
      ...batch.value,
      status: 'processed',
      processed_order_count: payload?.processed_order_count || payload?.processed_order_ids?.length || 0
    };
    successMessage.value = payload?.message || `Import berhasil membuat ${batch.value.processed_order_count || 0} Sales Order.`;
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Import ke Sales Order belum berhasil.');
  } finally {
    processing.value = false;
  }
}

function customerCandidateLabel(candidate) {
  const branch = candidate.kode_cabang ? ` / ${candidate.kode_cabang}` : '';
  const reason = candidate.alasan ? ` - ${candidate.alasan}` : '';
  return `${candidate.kode_customer || '-'} - ${candidate.nama_customer || '-'}${branch}${reason}`;
}

const validationErrorRows = computed(() =>
  rows.value
    .filter((row) => row.validation_status !== 'valid')
    .map((row) => ({
      ...row,
      display_code: row.row_type === 'detail'
        ? row.product_code || row.raw_data?.external_product_code || '-'
        : row.customer_code || '-',
      display_name: row.row_type === 'detail'
        ? row.raw_data?._product_name || row.raw_data?.external_user || '-'
        : row.raw_data?.external_user_2 || '-',
      display_type: row.row_type === 'detail' ? 'Detail Produk' : 'Header Order'
    }))
);

async function chooseCustomerConflict(row, candidate) {
  const conflict = row?.conflict || row?.raw_data?._customer_conflict;
  if (!conflict?.lookup_code || !candidate?.id_customer) return;

  const resolvingKey = `${row.id || row.order_no}:${candidate.id_customer}`;
  resolvingCustomerId.value = resolvingKey;
  errorMessage.value = '';
  successMessage.value = '';

  try {
    await saveCustomerExternalMapping({
      kode_external: conflict.lookup_code,
      id_customer: candidate.id_customer,
      source: conflict.mapping_source || scopedCustomerMappingSource.value
    });
    successMessage.value = `Mapping ${conflict.lookup_code} diarahkan ke ${candidate.nama_customer}. Validasi diperbarui.`;
    await refreshValidation();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Mapping customer konflik belum berhasil disimpan.');
  } finally {
    resolvingCustomerId.value = '';
  }
}

onMounted(loadScope);
</script>

<template>
  <PageHeader
    :title="importConfig.title"
    :description="importConfig.description"
  >
    <button class="btn btn-secondary" :disabled="loadingScope" @click="loadScope">
      {{ loadingScope ? 'Memuat...' : 'Reload Scope' }}
    </button>
  </PageHeader>

  <section class="akasha-panel">
    <div class="panel-head">
      <div>
        <p class="eyebrow">{{ importConfig.uploadLabel }}</p>
        <h2>Scope Import {{ importConfig.companyLabel }}</h2>
        <small class="source-note">Source {{ importConfig.companyLabel }} / SQL Server {{ importConfig.sourceServer }}</small>
      </div>
      <button class="btn btn-secondary" :disabled="loadingScope" @click="applyAkashaPreset">{{ importConfig.presetLabel }}</button>
    </div>

    <div class="akasha-scope-grid">
      <div class="akasha-filter-field akasha-file-field">
        <span class="akasha-field-label">{{ importConfig.fileLabel }}</span>
        <label class="akasha-file-control">
          <input type="file" :accept="importConfig.fileAccept" :multiple="importConfig.multipleFiles" @change="handleFile" />
          <span class="akasha-file-button">Browse</span>
          <strong>{{ importConfig.multipleFiles ? fileNames : fileName }}</strong>
        </label>
      </div>
      <div class="akasha-filter-field">
        <span class="akasha-field-label">Perusahaan</span>
        <AppSearchSelect
          v-model="form.companyId"
          placeholder="Pilih perusahaan"
          :options="companyOptions"
          :loading="loadingScope"
        />
      </div>
      <div class="akasha-filter-field">
        <span class="akasha-field-label">Cabang</span>
        <AppSearchSelect
          v-model="form.branchId"
          placeholder="Pilih cabang"
          :options="branchOptions"
          :loading="loadingScope"
        />
      </div>
      <div class="akasha-filter-field">
        <span class="akasha-field-label">Principal</span>
        <AppSearchSelect
          v-model="form.principalId"
          :placeholder="`Pilih principal ${importConfig.principalName}`"
          :options="principalOptions"
          :loading="loadingScope"
        />
      </div>
    </div>

    <div class="akasha-actions">
      <button class="btn btn-warning" :disabled="!canPreview" @click="previewImport">
        {{ previewing ? 'Preview...' : 'Preview' }}
      </button>
      <button class="btn btn-primary" :disabled="!canImport" @click="processImport">
        {{ processing ? 'Import...' : 'Import' }}
      </button>
      <button class="btn btn-secondary" :disabled="!batch?.id || revalidating" @click="refreshValidation">
        {{ revalidating ? 'Validasi...' : 'Refresh Validasi' }}
      </button>
    </div>

    <div v-if="principalMissing" class="alert warning">
      Principal {{ importConfig.principalCode }} / {{ importConfig.principalName }} belum ditemukan pada master principal untuk source {{ importConfig.companyLabel }}.
      Tambahkan dulu di Master Principal agar file bisa dipreview.
    </div>
    <div v-if="successMessage" class="alert success">{{ successMessage }}</div>
    <div v-if="errorMessage" class="alert error">{{ errorMessage }}</div>
  </section>

  <section class="summary-grid">
    <div class="summary-card">
      <span>Order</span>
      <strong>{{ summary.orders }}</strong>
    </div>
    <div class="summary-card">
      <span>Item</span>
      <strong>{{ summary.details }}</strong>
    </div>
    <div class="summary-card">
      <span>Order Valid</span>
      <strong>{{ summary.validOrders }}</strong>
    </div>
    <div class="summary-card danger">
      <span>Error Validasi</span>
      <strong>{{ summary.errors }}</strong>
    </div>
  </section>

  <section v-if="customerConflictRows.length" class="akasha-panel conflict-panel">
    <div class="panel-head">
      <div>
        <p class="eyebrow">Konflik Customer</p>
        <h2>Pilih customer tujuan sebelum import</h2>
      </div>
      <span class="status-chip error">{{ customerConflictRows.length }} konflik</span>
    </div>

    <div class="conflict-list">
      <div v-for="row in customerConflictRows" :key="`conflict-${row.id || row.order_no}`" class="conflict-item">
        <div class="conflict-summary">
          <strong>{{ row.order_no || '-' }}</strong>
          <span>
            Kode file <b>{{ row.conflict.lookup_code }}</b> terbaca sebagai
            <b>{{ row.conflict.resolved_customer?.nama_customer || '-' }}</b>,
            tetapi nama di file <b>{{ row.conflict.file_customer_name || '-' }}</b>.
          </span>
        </div>
        <div class="candidate-grid">
          <button
            v-for="candidate in row.conflict.candidates"
            :key="`${row.id || row.order_no}-${candidate.id_customer}`"
            type="button"
            class="candidate-button"
            :disabled="Boolean(resolvingCustomerId)"
            @click="chooseCustomerConflict(row, candidate)"
          >
            <span>{{ customerCandidateLabel(candidate) }}</span>
            <small>Pilih customer ini</small>
          </button>
        </div>
      </div>
    </div>
  </section>

  <section v-if="validationErrorRows.length" class="akasha-panel error-panel">
    <div class="panel-head">
      <div>
        <p class="eyebrow">Detail Error Validasi</p>
        <h2>{{ validationErrorRows.length }} baris perlu dicek</h2>
      </div>
      <span class="status-chip error">Need Review</span>
    </div>

    <div class="table-wrap">
      <table class="error-table">
        <thead>
          <tr>
            <th>Baris</th>
            <th>Jenis</th>
            <th>Nota</th>
            <th>Kode Customer</th>
            <th>Kode</th>
            <th>Nama / Produk</th>
            <th>Sales</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in validationErrorRows" :key="`error-${row.id || `${row.row_type}-${row.row_number}`}`">
            <td>{{ row.row_number || '-' }}</td>
            <td>{{ row.display_type }}</td>
            <td>{{ row.order_no || '-' }}</td>
            <td>{{ row.customer_code || '-' }}</td>
            <td>
              <strong>{{ row.display_code }}</strong>
              <small v-if="row.row_type === 'detail' && row.raw_data?.external_product_code && row.raw_data.external_product_code !== row.product_code">
                External: {{ row.raw_data.external_product_code }}
              </small>
            </td>
            <td>{{ row.display_name }}</td>
            <td>{{ row.sales_code || '-' }}</td>
            <td>
              <span class="error-text">{{ row.validation_message || 'Error validasi' }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>

  <section class="akasha-panel">
    <div class="panel-head">
      <div>
        <p class="eyebrow">Header Sales Order</p>
        <h2>{{ batch?.import_code || 'Preview belum dibuat' }}</h2>
      </div>
      <span class="status-chip" :class="batch?.status || 'draft'">{{ batch?.status || 'draft' }}</span>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Nota</th>
            <th>Tanggal</th>
            <th>Kode Customer</th>
            <th>Nama Customer</th>
            <th>Kode Sales</th>
            <th>Jumlah Item</th>
            <th>Total</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!headerPreviewRows.length">
            <td colspan="8" class="empty">No data available in table</td>
          </tr>
          <tr v-for="row in headerPreviewRows" :key="row.id || row.order_no">
            <td>
              <strong>{{ row.order_no || '-' }}</strong>
              <small>{{ row.raw_data?.external_ref || '-' }}</small>
            </td>
            <td>{{ row.order_date || '-' }}</td>
            <td>{{ row.customer_code || '-' }}</td>
            <td>{{ row.raw_data?.external_user_2 || '-' }}</td>
            <td>{{ row.sales_code || '-' }}</td>
            <td>
              {{ row.item_count }}
              <small v-if="row.detail_error_count" class="error-text">{{ row.detail_error_count }} detail error</small>
            </td>
            <td>{{ formatCurrency(row.subtotal || row.raw_data?.net_amount) }}</td>
            <td>
              <span class="status-chip" :class="row.validation_status">
                {{ row.validation_status || '-' }}
              </span>
              <small v-if="row.validation_message">{{ row.validation_message }}</small>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.akasha-panel,
.summary-card {
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 8px;
  background: var(--color-surface, #111827);
  box-shadow: 0 18px 45px rgba(2, 6, 23, 0.18);
}

.akasha-panel {
  margin-top: 20px;
  padding: 22px;
}

.panel-head {
  align-items: center;
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.panel-head h2 {
  color: var(--color-text, #f8fafc);
  font-size: 20px;
  font-weight: 800;
  margin: 4px 0 0;
}

.source-note {
  color: var(--color-text-muted, #8ca1c2);
  display: block;
  font-size: 13px;
  font-weight: 700;
  margin-top: 6px;
}

.eyebrow,
.akasha-field-label,
.summary-card span {
  color: var(--color-text-muted, #8ca1c2);
  font-size: 13px;
  font-weight: 800;
  letter-spacing: 0;
  text-transform: uppercase;
}

.akasha-scope-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 22px 28px;
  align-items: start;
}

.akasha-filter-field {
  display: grid;
  grid-template-rows: 18px minmax(48px, auto);
  gap: 8px;
  min-width: 0;
}

.akasha-file-field {
  grid-column: 1 / -1;
}

.akasha-field-label {
  line-height: 18px;
}

.akasha-file-control {
  align-items: center;
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 12px;
  background: rgba(3, 7, 18, 0.72);
  color: var(--color-text, #f8fafc);
  display: flex;
  gap: 10px;
  min-height: 46px;
  min-width: 0;
  overflow: hidden;
  padding: 8px 12px;
}

.akasha-file-control input {
  height: 1px;
  opacity: 0;
  overflow: hidden;
  position: absolute;
  width: 100%;
}

.akasha-file-button {
  background: rgba(148, 163, 184, 0.24);
  border-radius: 8px;
  color: var(--color-text, #f8fafc);
  cursor: pointer;
  flex: 0 0 auto;
  font-size: 14px;
  font-weight: 800;
  padding: 8px 12px;
  text-transform: none;
}

.akasha-file-field strong {
  color: var(--color-text, #f8fafc);
  font-size: 13px;
  font-weight: 700;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.akasha-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 26px;
}

.akasha-actions .btn {
  min-height: 44px;
  min-width: 128px;
  justify-content: center;
}

.btn-warning {
  background: #f6c238;
  color: #111827;
}

.alert {
  border-radius: 8px;
  margin-top: 16px;
  padding: 14px 16px;
  font-weight: 700;
}

.alert.success {
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.42);
  color: #6ee7b7;
}

.alert.error {
  background: rgba(244, 63, 94, 0.12);
  border: 1px solid rgba(244, 63, 94, 0.42);
  color: #fda4af;
}

.alert.warning {
  background: rgba(251, 191, 36, 0.12);
  border: 1px solid rgba(251, 191, 36, 0.42);
  color: #fde68a;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin-top: 18px;
}

.summary-card {
  padding: 20px;
}

.summary-card strong {
  color: var(--color-text, #f8fafc);
  display: block;
  font-size: 28px;
  margin-top: 10px;
}

.summary-card.danger strong {
  color: #fb7185;
}

.conflict-panel {
  border-color: rgba(251, 191, 36, 0.42);
}

.error-panel {
  border-color: rgba(244, 63, 94, 0.42);
}

.conflict-list {
  display: grid;
  gap: 14px;
}

.conflict-item {
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 8px;
  background: rgba(3, 7, 18, 0.36);
  padding: 16px;
}

.conflict-summary {
  display: grid;
  gap: 6px;
  color: var(--color-text, #f8fafc);
}

.conflict-summary strong {
  font-size: 16px;
}

.conflict-summary span {
  color: var(--color-text-muted, #8ca1c2);
  line-height: 1.5;
}

.conflict-summary b {
  color: var(--color-text, #f8fafc);
}

.candidate-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.candidate-button {
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.86);
  color: var(--color-text, #f8fafc);
  cursor: pointer;
  display: grid;
  gap: 4px;
  min-height: 66px;
  padding: 12px 14px;
  text-align: left;
}

.candidate-button:hover:not(:disabled) {
  border-color: rgba(96, 165, 250, 0.72);
  background: rgba(30, 41, 59, 0.94);
}

.candidate-button:disabled {
  cursor: wait;
  opacity: 0.64;
}

.candidate-button span {
  font-weight: 800;
}

.candidate-button small {
  color: var(--color-text-muted, #8ca1c2);
}

.table-wrap {
  overflow-x: auto;
}

table {
  border-collapse: collapse;
  min-width: 1080px;
  width: 100%;
}

.error-table {
  min-width: 1260px;
}

th,
td {
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
  padding: 14px 16px;
  text-align: left;
  vertical-align: top;
}

th {
  color: var(--color-text-muted, #8ca1c2);
  font-size: 13px;
  font-weight: 800;
  text-transform: uppercase;
}

td {
  color: var(--color-text, #f8fafc);
}

td strong,
td small {
  display: block;
}

td small {
  color: var(--color-text-muted, #8ca1c2);
  margin-top: 4px;
}

.error-text {
  color: #fda4af;
  font-weight: 800;
}

.empty {
  color: var(--color-text-muted, #8ca1c2);
  padding: 28px;
  text-align: center;
}

.status-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.22);
  color: var(--color-text, #f8fafc);
  font-size: 12px;
  font-weight: 800;
  padding: 6px 11px;
  text-transform: uppercase;
}

.status-chip.valid,
.status-chip.ready,
.status-chip.processed {
  background: rgba(16, 185, 129, 0.18);
  color: #6ee7b7;
}

.status-chip.invalid,
.status-chip.need_review,
.status-chip.error {
  background: rgba(244, 63, 94, 0.18);
  color: #fda4af;
}

@media (max-width: 900px) {
  .akasha-scope-grid,
  .summary-grid {
    grid-template-columns: 1fr;
  }

  .panel-head {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
