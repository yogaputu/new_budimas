<script setup>
import { computed, ref } from 'vue';
import { useRoute } from 'vue-router';
import PageHeader from '@/shared/components/PageHeader.vue';
import { insertDmsImport, previewDmsImport } from '@/api/dms';
import { normalizeError, unwrapResponse } from '@/utils/api';

const route = useRoute();
const selectedFiles = ref([]);
const headerFileName = ref('-');
const detailFileName = ref('-');
const rows = ref([]);
const errorMessage = ref('');
const feedback = ref('');
const isLoading = ref(false);
const isPreviewing = ref(false);

const previewRows = computed(() => rows.value.slice(0, 50));
const totalDetails = computed(() => rows.value.reduce((total, row) => total + (row.detail?.length || 0), 0));
const noDetailCount = computed(() => rows.value.filter((row) => !row.detail?.length).length);
const invalidRows = computed(() =>
  rows.value.filter((row) => !row.invoice_no || !row.customer_code || !row.route_name || !row.order_no)
);
const hasValidationError = computed(() => rows.value.length === 0 || invalidRows.value.length > 0 || noDetailCount.value > 0);
const validationMessage = computed(() => {
  if (!rows.value.length) {
    return 'Belum ada data DMS yang siap dikirim. Pilih file HDR dan DTL terlebih dahulu.';
  }

  if (invalidRows.value.length > 0) {
    return `${invalidRows.value.length} baris header belum lengkap. Pastikan kolom invoice_no, customer_code, route_name, dan order_no terisi.`;
  }

  if (noDetailCount.value > 0) {
    return `${noDetailCount.value} header tidak memiliki detail produk. Cek kembali pasangan file HDR dan DTL.`;
  }

  return '';
});
const canSubmit = computed(() => rows.value.length > 0 && !hasValidationError.value && !isLoading.value);
const pageTitle = computed(() => route.meta.pageTitle || 'DMS Import');
const pageDescription = computed(() =>
  route.meta.pageDescription || 'Import khusus DMS lama untuk pasangan file CSV HDR dan DTL. Alur ini langsung memakai endpoint DMS lama, bukan staging order baru.'
);

function normalizeHeader(header) {
  return String(header || '').replace(/\s+/g, '_').toLowerCase();
}

function detectDelimiter(line) {
  const candidates = ['|', ',', ';', '\t'];
  return candidates
    .map((delimiter) => ({ delimiter, count: String(line || '').split(delimiter).length - 1 }))
    .sort((a, b) => b.count - a.count)[0]?.delimiter || ',';
}

function parseCsvLine(line, delimiter = ',') {
  const values = [];
  let current = '';
  let inQuotes = false;

  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    const next = line[index + 1];

    if (char === '"' && inQuotes && next === '"') {
      current += '"';
      index += 1;
      continue;
    }

    if (char === '"') {
      inQuotes = !inQuotes;
      continue;
    }

    if (char === delimiter && !inQuotes) {
      values.push(current.trim());
      current = '';
      continue;
    }

    current += char;
  }

  values.push(current.trim());
  return values;
}

function parseCsv(content) {
  const lines = String(content || '')
    .replace(/^\uFEFF/, '')
    .split(/\r?\n/)
    .filter((line) => line.trim() !== '');

  if (lines.length < 2) {
    return [];
  }

  const delimiter = detectDelimiter(lines[0]);
  const headers = parseCsvLine(lines[0], delimiter).map(normalizeHeader);
  return lines.slice(1).map((line) => {
    const values = parseCsvLine(line, delimiter);
    return headers.reduce((row, header, index) => {
      row[header] = values[index] ?? '';
      return row;
    }, {});
  });
}

function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
}

function getSalesName(routeName) {
  const parts = String(routeName || '').split('-');
  return (parts[1] || routeName || '-').trim();
}

function formatCurrency(value) {
  const number = Number(String(value || 0).replace(/,/g, ''));
  if (!Number.isFinite(number)) {
    return value || '-';
  }
  return new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(number);
}

function showValidationError() {
  if (!hasValidationError.value) {
    return false;
  }

  errorMessage.value = validationMessage.value;
  feedback.value = '';
  return true;
}

async function handleFiles(event) {
  errorMessage.value = '';
  feedback.value = '';
  rows.value = [];

  const files = Array.from(event.target.files || []);
  selectedFiles.value = files;

  if (files.length === 1 && files[0].name.toLowerCase().endsWith('.zip')) {
    isPreviewing.value = true;
    try {
      const formData = new FormData();
      formData.append('file', files[0]);
      const payload = unwrapResponse(await previewDmsImport(formData));
      rows.value = payload?.rows || [];
      headerFileName.value = payload?.header_file || '-';
      detailFileName.value = payload?.detail_file || '-';

      if (showValidationError()) {
        return;
      }

      feedback.value = `ZIP terbaca: ${payload?.total_header || rows.value.length} header dan ${payload?.total_detail || totalDetails.value} detail. Validasi siap dikirim.`;
    } catch (error) {
      headerFileName.value = '-';
      detailFileName.value = '-';
      errorMessage.value = normalizeError(error, 'ZIP DMS belum bisa dibaca.');
    } finally {
      isPreviewing.value = false;
    }
    return;
  }

  if (files.length !== 2) {
    headerFileName.value = '-';
    detailFileName.value = '-';
    errorMessage.value = 'Pilih 1 file ZIP DMS atau tepat 2 file CSV: satu file HDR dan satu file DTL.';
    return;
  }

  const headerFile = files.find((file) => file.name.toUpperCase().includes('HDR'));
  const detailFile = files.find((file) => file.name.toUpperCase().includes('DTL'));

  if (!headerFile || !detailFile) {
    headerFileName.value = headerFile?.name || '-';
    detailFileName.value = detailFile?.name || '-';
    errorMessage.value = 'Nama file harus mengandung HDR untuk header dan DTL untuk detail.';
    return;
  }

  headerFileName.value = headerFile.name;
  detailFileName.value = detailFile.name;

  try {
    const [headerContent, detailContent] = await Promise.all([readFile(headerFile), readFile(detailFile)]);
    const headers = parseCsv(headerContent);
    const details = parseCsv(detailContent);
    const detailByInvoice = details.reduce((map, item) => {
      const key = item.invoice_no || '';
      if (!map.has(key)) {
        map.set(key, []);
      }
      map.get(key).push(item);
      return map;
    }, new Map());

    rows.value = headers.map((item) => ({
      ...item,
      detail: detailByInvoice.get(item.invoice_no) || []
    }));

    if (showValidationError()) {
      return;
    }

    feedback.value = `File terbaca: ${headers.length} header dan ${details.length} detail. Validasi siap dikirim.`;
  } catch (error) {
    errorMessage.value = normalizeError(error);
  }
}

async function submitDms() {
  if (showValidationError()) {
    return;
  }

  isLoading.value = true;
  errorMessage.value = '';
  feedback.value = '';

  try {
    await insertDmsImport({ data: rows.value });
    feedback.value = 'Import DMS berhasil dikirim ke backend lama.';
    selectedFiles.value = [];
    rows.value = [];
    headerFileName.value = '-';
    detailFileName.value = '-';
  } catch (error) {
    errorMessage.value = normalizeError(error);
  } finally {
    isLoading.value = false;
  }
}
</script>

<template>
  <PageHeader
    :title="pageTitle"
    :description="pageDescription"
  >
    <button class="btn btn-primary" :disabled="isLoading" @click="submitDms">
      {{ isLoading ? 'Mengirim...' : 'Kirim ke DMS' }}
    </button>
  </PageHeader>

  <section class="dms-grid">
    <div class="panel">
      <div class="panel-title">Pilih File DMS</div>
      <p class="panel-copy">Pilih satu file ZIP DMS atau dua file CSV. Sistem mengenali HDR sebagai header dan DTL sebagai detail.</p>
      <input class="file-input" type="file" accept=".zip,application/zip,.csv,text/csv,text/plain" multiple :disabled="isPreviewing || isLoading" @change="handleFiles" />
      <div v-if="isPreviewing" class="previewing">Membaca file DMS...</div>
      <div class="file-box">
        <span>Header</span>
        <strong>{{ headerFileName }}</strong>
      </div>
      <div class="file-box">
        <span>Detail</span>
        <strong>{{ detailFileName }}</strong>
      </div>
    </div>

    <div class="panel warning">
      <div class="panel-title">Catatan Import</div>
      <p>
        Modul DMS lama memasukkan data langsung ke sales order, faktur, draft voucher, dan detail order. File Mondelez biasanya memakai delimiter garis tegak (|), dan sudah didukung pada preview ini.
      </p>
      <p>Jika masih ada customer, sales, plafon, principal, produk, atau UOM yang belum cocok, backend akan menolak saat proses import.</p>
    </div>
  </section>

  <div v-if="feedback" class="alert success">{{ feedback }}</div>
  <div v-if="errorMessage" class="alert error">{{ errorMessage }}</div>

  <section class="summary-grid">
    <div class="summary-card">
      <span>Invoice Header</span>
      <strong>{{ rows.length }}</strong>
    </div>
    <div class="summary-card">
      <span>Detail Produk</span>
      <strong>{{ totalDetails }}</strong>
    </div>
    <div class="summary-card">
      <span>Header Tanpa Detail</span>
      <strong>{{ noDetailCount }}</strong>
    </div>
    <div class="summary-card danger">
      <span>Baris Belum Lengkap</span>
      <strong>{{ invalidRows.length }}</strong>
    </div>
  </section>

  <section class="panel preview-panel">
    <div class="preview-head">
      <div>
        <div class="panel-title">Preview Import DMS</div>
        <p class="panel-copy">Menampilkan maksimal 50 header pertama beserta jumlah detail yang akan ikut dikirim.</p>
      </div>
      <span class="chip">{{ rows.length }} header</span>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>No Faktur</th>
            <th>Customer</th>
            <th>Sales</th>
            <th>Order Date</th>
            <th>Net Amount</th>
            <th>Detail</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!previewRows.length">
            <td colspan="7" class="empty">Belum ada file DMS yang dibaca.</td>
          </tr>
          <tr v-for="row in previewRows" :key="`${row.invoice_no}-${row.order_no}`">
            <td>
              <strong>{{ row.invoice_no || '-' }}</strong>
              <small>{{ row.order_no || '-' }}</small>
            </td>
            <td>
              <strong>{{ row.customer_code || '-' }}</strong>
              <small>{{ row.customer_name || '-' }}</small>
            </td>
            <td>{{ getSalesName(row.route_name) }}</td>
            <td>{{ row.order_date || '-' }}</td>
            <td>{{ formatCurrency(row.total_net_amount) }}</td>
            <td>{{ row.detail?.length || 0 }}</td>
            <td>
              <span
                class="status"
                :class="{ ok: row.invoice_no && row.customer_code && row.route_name && row.order_no && row.detail?.length }"
              >
                {{ row.invoice_no && row.customer_code && row.route_name && row.order_no && row.detail?.length ? 'Siap' : 'Cek' }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.dms-grid,
.summary-grid {
  display: grid;
  gap: 18px;
}

.dms-grid {
  grid-template-columns: minmax(0, 1.15fr) minmax(320px, 0.85fr);
  margin-top: 20px;
}

.summary-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin: 18px 0;
}

.panel,
.summary-card {
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 22px;
  background:
    linear-gradient(145deg, rgba(34, 48, 72, 0.86), rgba(12, 18, 32, 0.94)),
    var(--surface-card, #111827);
  box-shadow: 0 18px 45px rgba(2, 6, 23, 0.22);
}

.panel {
  padding: 24px;
}

.panel.warning {
  border-color: rgba(132, 204, 22, 0.32);
}

.panel-title {
  color: var(--text-primary, #f8fafc);
  font-size: 18px;
  font-weight: 800;
  margin-bottom: 8px;
}

.panel-copy,
.panel p {
  color: var(--text-secondary, #b6c5dc);
  line-height: 1.65;
  margin: 0 0 16px;
}

.file-input {
  width: 100%;
  border: 1px dashed rgba(148, 163, 184, 0.45);
  border-radius: 18px;
  color: var(--text-primary, #f8fafc);
  padding: 18px;
  margin-bottom: 16px;
}

.file-box {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 16px;
  padding: 14px 16px;
  margin-top: 10px;
}

.file-box span,
.summary-card span {
  color: #8ea4c4;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.file-box strong,
.summary-card strong {
  color: var(--text-primary, #f8fafc);
}

.alert {
  border-radius: 16px;
  font-weight: 800;
  margin-top: 18px;
  padding: 16px 18px;
}

.alert.success {
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.32);
  color: #6ee7b7;
}

.alert.error {
  background: rgba(244, 63, 94, 0.12);
  border: 1px solid rgba(244, 63, 94, 0.34);
  color: #fda4af;
}

.summary-card {
  padding: 20px;
}

.summary-card strong {
  display: block;
  font-size: 28px;
  margin-top: 12px;
}

.summary-card.danger strong {
  color: #fb7185;
}

.preview-panel {
  margin-top: 18px;
  padding: 0;
  overflow: hidden;
}

.preview-head {
  align-items: center;
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 22px 24px;
}

.chip,
.status {
  border-radius: 999px;
  display: inline-flex;
  font-size: 12px;
  font-weight: 900;
  padding: 8px 12px;
}

.chip {
  background: rgba(59, 130, 246, 0.16);
  color: #bfdbfe;
}

.status {
  background: rgba(251, 113, 133, 0.16);
  color: #fda4af;
}

.status.ok {
  background: rgba(16, 185, 129, 0.16);
  color: #6ee7b7;
}

.table-wrap {
  overflow-x: auto;
}

table {
  border-collapse: collapse;
  min-width: 980px;
  width: 100%;
}

th,
td {
  border-top: 1px solid rgba(148, 163, 184, 0.2);
  color: var(--text-primary, #f8fafc);
  padding: 16px 18px;
  text-align: left;
  vertical-align: top;
}

th {
  background: rgba(15, 23, 42, 0.52);
  color: #9fb5d4;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

td small {
  color: #9fb5d4;
  display: block;
  margin-top: 5px;
}

.empty {
  color: #9fb5d4;
  text-align: center;
}

.btn {
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 14px;
  color: var(--text-primary, #f8fafc);
  cursor: pointer;
  font-weight: 900;
  padding: 12px 18px;
}

.btn-primary {
  background: linear-gradient(135deg, #6b8f34, #8fb34b);
  border-color: transparent;
}

.btn:disabled {
  cursor: not-allowed;
  opacity: 0.48;
}

@media (max-width: 980px) {
  .dms-grid,
  .summary-grid {
    grid-template-columns: 1fr;
  }
}
</style>
