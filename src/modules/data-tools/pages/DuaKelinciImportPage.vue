<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import PageHeader from '@/shared/components/PageHeader.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppModal from '@/shared/components/AppModal.vue';
import { useAuthStore } from '@/stores/auth';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import { getCompanyOptionsForScope, getBranchOptionsForCompany } from '@/utils/filterScope';
import { getRowCompanyIds } from '@/utils/accessScope';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { toLocalDateInputValue } from '@/utils/date';
import { previewDuaKelinci, getDuaKelinciBatch, revalidateDuaKelinci, processDuaKelinci,
  searchDuaKelinciCustomers, mapDuaKelinciCustomer } from '@/api/duaKelinci';

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const companies = ref([]);
const branches = ref([]);
const principals = ref([]);
const file = ref(null);
const batch = ref(null);
const principalMapping = ref(null);
const rows = ref([]);
const excludedRows = ref([]);
const sourceDetailCount = ref(0);
const busy = ref(false);
const loading = ref(true);
const applying = ref(false);
const error = ref('');
const success = ref('');
const search = ref('');
const confirmOpen = ref(false);
const customerOptions = ref([]);
const customerLoading = ref(false);
const mapping = reactive({ outlet: '', customer: '' });
const form = reactive({ company: '', branch: '', principal: '' });
let customerSearchRevision = 0;

const companyOptions = computed(() => getCompanyOptionsForScope(companies.value, auth));
const branchOptions = computed(() => getBranchOptionsForCompany(branches.value, auth, form.company, false, companies.value));
const principalOptions = computed(() => principals.value.filter((row) => ![false, 0, '0', 'false'].includes(row.aktif)
  && getRowCompanyIds(row).map(String).includes(String(form.company)))
  .map((row) => ({ value: String(row.id), label: `${row.kode} — ${row.nama_principal || row.nama || row.text}` })));
const principalLabel = computed(() => principalMapping.value
  ? `${principalMapping.value.kode} — ${principalMapping.value.nama}`
  : principalOptions.value.find((row) => row.value === form.principal)?.label || 'Belum dipilih');
const headers = computed(() => rows.value.filter((row) => row.row_type === 'header'));
const details = computed(() => rows.value.filter((row) => row.row_type === 'detail'));
const errors = computed(() => rows.value.filter((row) => row.validation_status !== 'valid'));
const visibleDetails = computed(() => details.value.filter((row) =>
  [row.order_no, row.product_code, row.raw_data?._product_name, row.customer_code].join(' ').toLowerCase().includes(search.value.trim().toLowerCase())));
const total = computed(() => headers.value.reduce((sum, row) => sum + Number(row.subtotal || 0), 0));
const bonusCount = computed(() => details.value.filter((row) => row.raw_data?._is_bonus).length);
const canCreate = computed(() => auth.hasPermission('distribution.orders.create') || auth.hasPermission('m.distribusi.io.create'));
const canPreview = computed(() => file.value && form.company && form.branch && form.principal && !busy.value && canCreate.value);
const canProcess = computed(() => canCreate.value && !busy.value && batch.value?.status === 'ready' && !errors.value.length && headers.value.length > 0);
const mappingOutlets = computed(() => [...new Set(headers.value.map((row) => row.customer_code))]
  .map((code) => ({ value: code, label: code })));
const money = (value) => Number(value || 0).toLocaleString('id-ID', { maximumFractionDigits: 4 });

function applyPayload(payload) {
  batch.value = payload?.batch || null;
  principalMapping.value = payload?.principal_mapping || null;
  rows.value = payload?.rows || [];
  excludedRows.value = payload?.excluded_rows || [];
  sourceDetailCount.value = payload?.source_detail_count ?? rows.value.filter((row) => row.row_type === 'detail').length;
}

function clearPreview() {
  applyPayload(null);
  confirmOpen.value = false;
  mapping.outlet = '';
  mapping.customer = '';
  customerOptions.value = [];
  customerSearchRevision += 1;
  customerLoading.value = false;
  search.value = '';
  error.value = '';
  success.value = '';
  router.replace({ query: {} });
}

function selectFile(event) {
  clearPreview();
  file.value = event.target.files?.[0] || null;
}

watch(() => [form.company, form.branch, form.principal], () => {
  if (applying.value || loading.value) return;
  if (!branchOptions.value.some((row) => row.value === form.branch)) form.branch = '';
  if (!principalOptions.value.some((row) => row.value === form.principal)) form.principal = '';
  clearPreview();
});

async function loadBatch(id) {
  const payload = unwrapResponse(await getDuaKelinciBatch(id));
  applying.value = true;
  form.company = String(payload.batch.id_perusahaan);
  form.branch = String(payload.batch.id_cabang);
  form.principal = String(payload.batch.id_principal);
  applyPayload(payload);
  await nextTick();
  applying.value = false;
}

// This route keeps one component across batch_id updates, avoiding a stale
// KeepAlive copy when selecting another file. Also support back/forward links.
watch(() => route.query.batch_id, async (id) => {
  if (loading.value || busy.value || String(id || '') === String(batch.value?.id || '')) return;
  if (!id) { clearPreview(); return; }
  busy.value = true;
  error.value = '';
  try { await loadBatch(id); }
  catch (exception) { error.value = normalizeError(exception, 'Batch belum dapat dimuat.'); }
  finally { busy.value = false; }
});

async function preview() {
  if (!canPreview.value) return;
  clearPreview();
  busy.value = true;
  error.value = '';
  success.value = '';
  const data = new FormData();
  data.append('excel_file', file.value);
  data.append('id_perusahaan', form.company);
  data.append('id_cabang', form.branch);
  data.append('id_principal', form.principal);
  try {
    applyPayload(unwrapResponse(await previewDuaKelinci(data)));
    await router.replace({ query: { batch_id: batch.value.id } });
    success.value = 'Preview tersimpan. Periksa pemetaan, nominal diskon, PPN, dan baris bonus sebelum import.';
  } catch (exception) { error.value = normalizeError(exception, 'File belum dapat dipreview.'); }
  finally { busy.value = false; }
}

async function refresh() {
  if (!batch.value || busy.value) return;
  busy.value = true;
  error.value = '';
  success.value = '';
  try {
    applyPayload(unwrapResponse(await revalidateDuaKelinci(batch.value.id)));
    success.value = 'Validasi dan harga master diperbarui. Tinjau kembali total sebelum import.';
  } catch (exception) { error.value = normalizeError(exception, 'Validasi belum berhasil.'); }
  finally { busy.value = false; }
}

async function searchCustomers(keyword = '') {
  if (!batch.value) return;
  const revision = ++customerSearchRevision;
  const id = batch.value.id;
  customerLoading.value = true;
  try {
    const data = normalizeList(unwrapResponse(await searchDuaKelinciCustomers(id, keyword)));
    if (revision !== customerSearchRevision || batch.value?.id !== id) return;
    customerOptions.value = data.map((row) => ({ value: String(row.id), label: `${row.kode} — ${row.nama}` }));
  } catch (exception) { if (revision === customerSearchRevision) error.value = normalizeError(exception, 'Pencarian customer gagal.'); }
  finally { if (revision === customerSearchRevision) customerLoading.value = false; }
}

async function saveMapping() {
  if (!mapping.outlet || !mapping.customer || !batch.value || busy.value) return;
  busy.value = true;
  error.value = '';
  success.value = '';
  try {
    applyPayload(unwrapResponse(await mapDuaKelinciCustomer(batch.value.id, {
      outlet_code: mapping.outlet, id_customer: Number(mapping.customer)
    })));
    success.value = 'Mapping outlet disimpan khusus Dua Kelinci, perusahaan, cabang dan principal ini. Validasi sudah diperbarui.';
  } catch (exception) { error.value = normalizeError(exception, 'Mapping belum dapat disimpan.'); }
  finally { busy.value = false; }
}

async function process() {
  confirmOpen.value = false;
  if (!canProcess.value) return;
  busy.value = true;
  error.value = '';
  success.value = '';
  try {
    const result = unwrapResponse(await processDuaKelinci(batch.value.id));
    success.value = result.message || `${result.processed_order_count} Sales Order dibuat untuk Approval Order.`;
    await loadBatch(batch.value.id);
  } catch (exception) {
    error.value = normalizeError(exception, 'Import belum berhasil.');
    if (exception.response?.status === 409) {
      try { await loadBatch(batch.value.id); } catch { /* Keep the original error visible. */ }
    }
  } finally { busy.value = false; }
}

onMounted(async () => {
  try {
    const result = await Promise.all([getCompanies(), getBranches(), getPrincipals()]);
    [companies.value, branches.value, principals.value] = result.map((response) => normalizeList(unwrapResponse(response)));
    form.company = companyOptions.value.find((row) => /bmm|budimas/i.test(row.label))?.value || companyOptions.value[0]?.value || '';
    if (branchOptions.value.length === 1) form.branch = branchOptions.value[0].value;
    if (route.query.batch_id) await loadBatch(route.query.batch_id);
  } catch (exception) { error.value = normalizeError(exception, 'Data import belum dapat dimuat.'); }
  finally { loading.value = false; }
});
</script>

<template>
  <PageHeader title="Import Dua Kelinci" description="Baca export Excel Dua Kelinci, tinjau pemetaan dan nominal, lalu buat Sales Order pending untuk approval ERP.">
    <RouterLink class="btn-secondary dk-secondary" to="/distribution/orders">Approval Order</RouterLink>
  </PageHeader>
  <div class="space-y-5">
    <section class="dk-panel">
      <h2 class="text-lg font-semibold">1. File dan tujuan import</h2>
      <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">Excel .xlsx, maksimal 10 MiB / 2.000 baris / 200 order. Pilih scope tujuan, tidak mengikuti ID cabang bridging lama.</p>
      <div class="mt-5 grid gap-4 md:grid-cols-3">
        <label class="space-y-2"><span class="dk-label">Perusahaan</span><AppSearchSelect v-model="form.company" :options="companyOptions" :disabled="busy || loading" placeholder="Pilih perusahaan" /></label>
        <label class="space-y-2"><span class="dk-label">Cabang</span><AppSearchSelect v-model="form.branch" :options="branchOptions" :disabled="busy || loading" placeholder="Pilih cabang" /></label>
        <label class="space-y-2"><span class="dk-label">Mapping principal ERP</span><AppSearchSelect v-model="form.principal" :options="principalOptions" :disabled="busy || loading" placeholder="Pilih principal tujuan Dua Kelinci" /></label>
      </div>
      <p class="mt-3 text-sm text-slate-500">Kode principal ERP tidak harus 76. Pilih principal tujuan yang benar; pilihan ini tersimpan pada batch. Mengganti tujuan memerlukan preview baru, bukan mengubah order yang sudah diimpor.</p>
      <div class="mt-4 flex flex-wrap items-center gap-3">
        <input class="min-w-0 max-w-full text-sm" type="file" aria-label="File export Dua Kelinci" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" :disabled="busy || loading" @change="selectFile" />
        <button class="btn-primary" :disabled="!canPreview" @click="preview">{{ busy ? 'Memproses...' : 'Preview File' }}</button>
        <button class="btn-secondary dk-secondary" :disabled="!batch || batch.status === 'processed' || busy" @click="refresh">Refresh Validasi</button>
      </div>
      <p v-if="!principalOptions.length && form.company && !loading" class="mt-3 text-sm text-amber-700 dark:text-amber-300">Principal aktif belum tersedia di perusahaan ini. Lengkapi master sebelum import.</p>
      <details class="mt-4 rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-950">
        <summary class="cursor-pointer font-medium">Format sumber dan aturan perhitungan</summary>
        <p class="mt-2">Kolom wajib: NO_SO, PCODE, QTY, OUTLET_CODE, TGLTRANS, serta CODE atau USERN (CODE diprioritaskan). Opsional: DISC1, DISC2, DISC3, SPRICE1, REJECT.</p>
        <p class="mt-2">QTY = PCS/satuan dasar. DISC1–3 = diskon rupiah per baris. Harga sesuai tipe harga plafon dan PPN mengikuti master produk ERP, bukan PPN 11% hard-coded dari bridging.</p>
        <p class="mt-2">Mengikuti aturan bridging: SPRICE1=0 atau SKU berulang dalam satu SO ditandai BONUS (diskon 100%). Periksa setiap baris bonus. NO_SO diberi awalan DK bila belum ada.</p>
        <p class="mt-2">Baris REJECT=1 dengan QTY=0 dilewati dan tetap dicatat di preview/audit. QTY=0 tanpa reject atau reject dengan QTY positif ditolak untuk diperiksa.</p>
        <p class="mt-2">OUTLET_CODE dipetakan seperti KodeSS, melalui mapping khusus di bawah; tidak mengambil data atau mengubah SQL Server lama. Impor seluruh batch hanya jika semua baris valid.</p>
      </details>
    </section>
    <p v-if="error" role="alert" class="dk-feedback rounded-xl bg-rose-50 p-4 text-sm text-rose-800 dark:bg-rose-950 dark:text-rose-200">{{ error }}</p>
    <p v-if="success" role="status" class="dk-feedback rounded-xl bg-emerald-50 p-4 text-sm text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">{{ success }}</p>
    <template v-if="batch">
      <section class="dk-panel" aria-label="Tujuan mapping principal">
        <span class="dk-label">Dua Kelinci → principal ERP</span>
        <strong class="mt-2 block">{{ principalLabel }}</strong>
        <p class="mt-1 text-sm text-slate-500">Produk, customer dan plafon divalidasi terhadap principal ini. Tidak membuat atau mengganti kode master principal.</p>
      </section>
      <section v-if="excludedRows.length" class="dk-panel" aria-label="Baris sumber yang dilewati">
        <h2 class="font-semibold">{{ excludedRows.length }} baris sumber dilewati</h2>
        <p class="mt-1 text-sm text-slate-500">{{ sourceDetailCount }} baris di file = {{ details.length }} detail aktif + {{ excludedRows.length }} baris reject. Baris reject tidak membuat detail order; sumber aslinya tetap tersimpan untuk audit.</p>
        <div class="mt-3 max-h-48 overflow-auto"><table class="dk-table"><thead><tr><th>Baris Excel</th><th>SO</th><th>PCODE</th><th>Alasan</th></tr></thead><tbody>
          <tr v-for="row in excludedRows" :key="row.row_number"><td>{{ row.row_number }}</td><td>{{ row.order_no }}</td><td>{{ row.product_code }}</td><td>{{ row.reason }}</td></tr>
        </tbody></table></div>
      </section>
      <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div class="dk-panel"><span class="dk-label">Order / detail</span><strong class="mt-2 block text-xl">{{ headers.length }} / {{ details.length }}</strong></div>
        <div class="dk-panel"><span class="dk-label">Error validasi</span><strong class="mt-2 block text-xl" :class="errors.length ? 'text-rose-500' : 'text-emerald-500'">{{ errors.length }}</strong></div>
        <div class="dk-panel"><span class="dk-label">Baris bonus</span><strong class="mt-2 block text-xl text-amber-500">{{ bonusCount }}</strong></div>
        <div class="dk-panel"><span class="dk-label">Total termasuk PPN</span><strong class="mt-2 block text-xl">Rp {{ money(total) }}</strong></div>
      </div>
      <section v-if="batch.status !== 'processed'" class="dk-panel">
        <h2 class="font-semibold">2. Mapping outlet (bila diperlukan)</h2>
        <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">Pilih customer ERP dalam cabang dan principal ini. Mapping tidak membuat customer atau plafon baru.</p>
        <div class="mt-4 grid items-end gap-3 md:grid-cols-3">
          <label><span class="dk-label">OUTLET_CODE dari file</span><AppSearchSelect v-model="mapping.outlet" :options="mappingOutlets" :disabled="busy" /></label>
          <label><span class="dk-label">Customer ERP</span><AppSearchSelect v-model="mapping.customer" :options="customerOptions" remote-search :loading="customerLoading" :disabled="busy" placeholder="Cari kode/nama customer" @search="searchCustomers" /></label>
          <button class="btn-secondary dk-secondary" :disabled="!mapping.outlet || !mapping.customer || busy || !canCreate" @click="saveMapping">Simpan Mapping &amp; Validasi</button>
        </div>
      </section>
      <section class="dk-panel">
        <div class="flex flex-wrap items-center justify-between gap-3"><div><h2 class="font-semibold">3. Tinjau order</h2><p class="text-sm text-slate-500">{{ batch.import_code }} · {{ batch.status }}</p></div><button class="btn-primary" :disabled="!canProcess" @click="confirmOpen = true">Import ke Sales Order</button></div>
        <div class="mt-4 overflow-x-auto"><table class="dk-table"><thead><tr><th>Order / tanggal</th><th>Outlet → customer</th><th>Sales</th><th>Total</th><th>Validasi</th></tr></thead><tbody>
          <tr v-for="row in headers" :key="row.id"><td>{{ row.order_no }}<small>{{ toLocalDateInputValue(row.order_date) }}</small></td><td>{{ row.customer_code }}<small>{{ row.raw_data?._resolved_customer_code }} · {{ row.raw_data?._resolved_customer_name || 'Belum dipetakan' }}</small></td><td>{{ row.sales_code }}</td><td>Rp {{ money(row.subtotal) }}</td><td>{{ row.validation_message || row.validation_status }}</td></tr>
        </tbody></table></div>
        <p v-if="batch.status === 'processed'" class="mt-4 text-sm text-emerald-600 dark:text-emerald-400">Batch sudah diimpor. Lanjutkan konfirmasi melalui Distribusi → Approval Order; belum ada reservasi stok atau faktur final.</p>
      </section>
      <section class="dk-panel">
        <div class="flex flex-wrap items-center justify-between gap-3"><h2 class="font-semibold">Detail barang, diskon, PPN &amp; bonus</h2><input v-model="search" class="rounded-xl border border-slate-300 bg-transparent p-2 text-sm dark:border-slate-700" placeholder="Cari order / PCODE / outlet" /></div>
        <div class="mt-4 max-h-[36rem] overflow-auto"><table class="dk-table"><thead><tr><th>Baris / SO</th><th>PCODE / produk</th><th>Qty PCS</th><th>Harga master</th><th>Diskon Rp</th><th>DPP / PPN</th><th>Total</th><th>Validasi / bonus</th></tr></thead><tbody>
          <tr v-for="row in visibleDetails" :key="row.id"><td>{{ row.row_number }}<small>{{ row.order_no }}</small></td><td>{{ row.product_code }}<small>{{ row.raw_data?._product_name }}</small></td><td>{{ row.quantity }}</td><td>{{ money(row.raw_data?._finance?.unit_price) }}</td><td>{{ money(row.raw_data?._finance?.discount_amount) }}</td><td>{{ money(row.raw_data?._finance?.dpp) }}<small>PPN {{ row.raw_data?._finance?.tax_rate || '—' }}% · {{ money(row.raw_data?._finance?.tax_amount) }}</small></td><td>{{ money(row.raw_data?._finance?.total) }}</td><td><span v-if="row.raw_data?._is_bonus" class="font-semibold text-amber-600 dark:text-amber-300">BONUS<small>{{ row.raw_data._bonus_reason }}</small></span><span :class="row.validation_status !== 'valid' ? 'text-rose-500' : ''">{{ row.validation_message || row.validation_status }}</span></td></tr>
        </tbody></table></div>
      </section>
    </template>
  </div>
  <AppModal :open="confirmOpen" title="Import order Dua Kelinci?" size="md" @close="confirmOpen = false">
    <p class="mb-3 font-semibold">Principal tujuan: {{ principalLabel }}</p>
    <p>{{ headers.length }} order akan dibuat sebagai pending, total Rp {{ money(total) }}. {{ bonusCount }} baris ditandai bonus. Pastikan mapping, harga, diskon, dan PPN sudah benar.</p>
    <p v-if="excludedRows.length" class="mt-3 text-sm">{{ excludedRows.length }} baris REJECT=1 dan QTY=0 tidak ikut dibuat menjadi detail order.</p>
    <p class="mt-3 text-sm text-slate-500">Konfirmasi dan reservasi stok tetap melalui Approval Order ERP. Seluruh batch disimpan sekaligus atau dibatalkan bila gagal.</p>
    <div class="mt-5 flex justify-end gap-2"><button class="btn-secondary dk-secondary" @click="confirmOpen = false">Batal</button><button class="btn-primary" :disabled="!canProcess" @click="process">Ya, Import</button></div>
  </AppModal>
</template>

<style scoped>
.dk-panel { @apply rounded-2xl border border-slate-200 bg-white p-5 text-slate-900; }
.dk-label { @apply mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500; }
.dk-table { @apply w-full text-left text-sm; }
.dk-table th { @apply sticky top-0 whitespace-nowrap border-b border-slate-200 bg-slate-50 px-3 py-3 text-xs font-semibold uppercase text-slate-500; }
.dk-table td { @apply border-b border-slate-100 px-3 py-3 align-top; }
.dk-table small { @apply mt-1 block text-xs text-slate-500; }
.btn-secondary { @apply border-slate-300 text-slate-700; }
.btn-primary:disabled, .btn-secondary:disabled { @apply cursor-not-allowed opacity-50; }
/* ERP's manual theme switch uses data-theme, not the OS media query. */
:global(:root[data-theme='dark'] .dk-panel) { @apply border-slate-800 bg-slate-900 text-slate-100; }
:global(:root[data-theme='dark'] .dk-label),
:global(:root[data-theme='dark'] .dk-table small) { @apply text-slate-400; }
:global(:root[data-theme='dark'] .dk-table th) { @apply border-slate-700 bg-slate-950 text-slate-400; }
:global(:root[data-theme='dark'] .dk-table td) { @apply border-slate-800; }
:global(:root[data-theme='dark'] .dk-secondary) { @apply border-slate-700 text-slate-200; }
:global(:root[data-theme='dark'] .dk-feedback[role='alert']) { @apply bg-rose-950 text-rose-200; }
:global(:root[data-theme='dark'] .dk-feedback[role='status']) { @apply bg-emerald-950 text-emerald-200; }
</style>
