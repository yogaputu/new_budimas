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
import { previewDkPurchase, listDkPurchase, getDkPurchase, searchDkPurchaseProducts, reviewDkPurchase, processDkPurchase } from '@/api/duaKelinciPurchase';

const auth = useAuthStore(), route = useRoute(), router = useRouter();
const companies = ref([]), branches = ref([]), principals = ref([]), file = ref(null);
const payload = ref(null), recent = ref([]), selectedBatch = ref('');
const loading = ref(true), busy = ref(false), error = ref(''), success = ref(''), search = ref('');
const confirmOpen = ref(false), editRow = ref(null), productRows = ref([]), productLoading = ref(false);
const form = reactive({ company: '', branch: '', principal: '', basis: '' });
const edit = reactive({ product: '', price: '', ppn: '', units: ['', '', '', '', ''] });
let applying = false, productRevision = 0;
const companyOptions = computed(() => getCompanyOptionsForScope(companies.value, auth));
const branchOptions = computed(() => getBranchOptionsForCompany(branches.value, auth, form.company, false, companies.value));
const principalOptions = computed(() => principals.value.filter((p) => ![false, 0, '0', 'false'].includes(p.aktif)
  && getRowCompanyIds(p).map(String).includes(String(form.company))
  && ['DUAKELINCI', 'PTDUAKELINCI'].includes(String(p.nama_principal || p.nama || p.text || '').toUpperCase().replace(/[^A-Z0-9]/g, '')))
  .map((p) => ({ value: String(p.id), label: `${p.kode} — ${p.nama_principal || p.nama || p.text}` })));
const batch = computed(() => payload.value?.batch);
const rows = computed(() => payload.value?.preview?.rows || []);
const filtered = computed(() => rows.value.filter((r) => [r.product_code, r.product_name, r.delivery_ref, r.resolved?.nama].join(' ').toLowerCase().includes(search.value.toLowerCase())));
const canWrite = computed(() => auth.hasPermission('purchase.orders.create') || auth.hasPermission('m.purchase.ip.create'));
const scopeReady = computed(() => form.company && form.branch && form.principal);
const basisChanged = computed(() => batch.value && form.basis !== batch.value.quantity_basis);
const canProcess = computed(() => canWrite.value && !busy.value && !basisChanged.value && batch.value?.status === 'ready' && payload.value?.preview?.complete);
const principalLabel = computed(() => payload.value?.principal_mapping ? `${payload.value.principal_mapping.kode} — ${payload.value.principal_mapping.nama}` : '');
const productOptions = computed(() => productRows.value.map((p) => ({ value: String(p.id), label: `${p.kode_sku} — ${p.nama}` })));
const selectedProduct = computed(() => productRows.value.find((p) => String(p.id) === String(edit.product)));
const unitOptions = computed(() => (selectedProduct.value?.uoms || []).map((u) => ({ value: String(u.id), label: `${u.nama} × ${u.faktor_konversi}` })));
const basisOptions = [{ value: 'kirim', label: 'QTY Kirim' }, { value: 'terima', label: 'QTY Terima' }];
const batchOptions = computed(() => recent.value.map((b) => ({ value: String(b.id), label: `${b.source_ref} — ${b.status}${b.order_id ? ' · PO #' + b.order_id : ''}` })));
const money = (v) => Number(v ?? 0).toLocaleString('id-ID', { maximumFractionDigits: 4 });
const quantityLabel = (units = []) => units.filter((u) => u.quantity).map((u) => `${u.quantity} ${u.unit || '(tanpa label)'}`).join(' + ') || '0';
const scope = () => ({ id_perusahaan: form.company, id_cabang: form.branch, id_principal: form.principal });

function apply(data) {
  payload.value = data;
  if (data?.batch) {
    form.basis = data.batch.quantity_basis;
    selectedBatch.value = String(data.batch.id);
    recent.value = recent.value.map((row) => String(row.id) === String(data.batch.id)
      ? { ...row, status: data.batch.status, order_id: data.order?.id || null } : row);
  }
}
async function loadBatch(id) {
  const data = unwrapResponse(await getDkPurchase(id));
  applying = true;
  form.company = String(data.batch.id_perusahaan);
  form.branch = String(data.batch.id_cabang);
  form.principal = String(data.batch.id_principal);
  apply(data);
  await nextTick();
  applying = false;
}
async function batches() {
  if (!scopeReady.value) return;
  recent.value = normalizeList(unwrapResponse(await listDkPurchase(scope())));
}
async function run(action) {
  if (busy.value) return;
  busy.value = true; error.value = ''; success.value = '';
  try { await action(); }
  catch (e) {
    error.value = normalizeError(e, 'Import PO belum dapat diproses.');
    if (e.response?.data?.result?.batch) apply(e.response.data.result);
    else if (e.response?.status === 409 && batch.value) {
      try { await loadBatch(batch.value.id); } catch { /* Keep original failure. */ }
    }
  } finally { busy.value = false; }
}
function selectFile(e) {
  file.value = e.target.files?.[0] || null;
  payload.value = null; selectedBatch.value = ''; closeEdit();
  error.value = ''; success.value = ''; router.replace({ query: {} });
}
async function preview() {
  if (!canWrite.value || !scopeReady.value || !form.basis || !file.value) return;
  await run(async () => {
    const data = new FormData();
    Object.entries(scope()).forEach(([k, v]) => data.append(k, v));
    data.append('quantity_basis', form.basis); data.append('excel_file', file.value);
    apply(unwrapResponse(await previewDkPurchase(data)));
    await router.replace({ query: { batch_id: batch.value.id } });
    await batches();
    success.value = batch.value.status === 'processed' ? 'Dokumen ini sudah menjadi PO. Tidak dibuat ulang.' : 'Preview tersimpan. Lengkapi seluruh baris sebelum membuat draft PO.';
  });
}
async function refresh() {
  await run(async () => {
    apply(unwrapResponse(await reviewDkPurchase(batch.value.id, { revision: batch.value.revision, quantity_basis: form.basis, lines: [] })));
    success.value = 'Preview divalidasi ulang. Periksa hasil dan nominal terbaru.';
  });
}
async function searchProducts(keyword = '') {
  if (!batch.value || !editRow.value) return;
  const revision = ++productRevision, id = batch.value.id;
  productLoading.value = true;
  try {
    const result = normalizeList(unwrapResponse(await searchDkPurchaseProducts(id, keyword)));
    if (revision !== productRevision || id !== batch.value?.id || !editRow.value) return;
    const keep = selectedProduct.value;
    productRows.value = keep && !result.some((p) => p.id === keep.id) ? [keep, ...result] : result;
  } catch (e) { if (revision === productRevision) error.value = normalizeError(e, 'Produk belum dapat dicari.'); }
  finally { if (revision === productRevision) productLoading.value = false; }
}
function openEdit(row) {
  editRow.value = row;
  productRows.value = row.product ? [{ ...row.product, uoms: row.uoms }] : [];
  edit.product = String(row.product?.id || '');
  edit.price = row.override?.price ?? '';
  edit.ppn = row.override?.ppn ?? '';
  edit.units = (row.override?.uom_ids || [null, null, null, null, null]).map((v) => v == null ? '' : String(v));
  searchProducts(row.product_code);
}
function chooseProduct(id) {
  if (String(id) === String(edit.product)) return;
  edit.product = id; edit.price = ''; edit.ppn = ''; edit.units = ['', '', '', '', ''];
}
function closeEdit() { editRow.value = null; productRevision++; productLoading.value = false; }
async function saveEdit() {
  const row = editRow.value;
  await run(async () => {
    apply(unwrapResponse(await reviewDkPurchase(batch.value.id, {
      revision: batch.value.revision, quantity_basis: form.basis,
      lines: [{ row_number: row.row_number, id_produk: edit.product ? Number(edit.product) : null,
        price: edit.price === '' ? null : String(edit.price), ppn: edit.ppn === '' ? null : String(edit.ppn),
        uom_ids: edit.units.map((v) => v === '' ? null : Number(v)) }]
    })));
    closeEdit(); success.value = 'Koreksi tersimpan pada batch ini. Master produk dan import lain tidak diubah.';
  });
}
async function process() {
  confirmOpen.value = false;
  if (!canProcess.value) return;
  await run(async () => {
    apply(unwrapResponse(await processDkPurchase(batch.value.id, { revision: batch.value.revision, confirm: true })));
    success.value = 'Draft PO dibuat. Lanjutkan tinjauan di Approval Purchase Order.';
    await batches();
  });
}
watch(() => [form.company, form.branch, form.principal], () => {
  if (applying || loading.value) return;
  if (!branchOptions.value.some((o) => o.value === form.branch)) form.branch = '';
  if (!principalOptions.value.some((o) => o.value === form.principal)) form.principal = '';
  payload.value = null; recent.value = []; selectedBatch.value = ''; closeEdit();
  error.value = ''; success.value = ''; router.replace({ query: {} });
});
watch(() => route.query.batch_id, async (id) => {
  if (loading.value || busy.value || String(id || '') === String(batch.value?.id || '')) return;
  if (!id) { payload.value = null; return; }
  await run(() => loadBatch(id));
});
onMounted(async () => {
  await run(async () => {
    const result = await Promise.all([getCompanies(), getBranches(), getPrincipals()]);
    [companies.value, branches.value, principals.value] = result.map((r) => normalizeList(unwrapResponse(r)));
    form.company = companyOptions.value.find((o) => o.value === String(auth.user?.id_perusahaan))?.value || (companyOptions.value.length === 1 ? companyOptions.value[0].value : '');
    if (branchOptions.value.length === 1) form.branch = branchOptions.value[0].value;
    if (route.query.batch_id) { await loadBatch(route.query.batch_id); await batches(); }
  });
  loading.value = false;
});
</script>

<template>
  <PageHeader title="Import PO Dua Kelinci" description="Tinjau export pembelian Dua Kelinci dan buat draft PO untuk approval. Tidak langsung menerima stok atau membuat jurnal.">
    <RouterLink class="btn-secondary dkpo-nav" to="/purchase/order-confirmations">Approval PO</RouterLink>
  </PageHeader>
  <div class="dkpo space-y-5">
    <section class="dkpo-panel">
      <h2 class="text-lg font-semibold">1. File dan tujuan pembelian</h2>
      <div class="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <label><span>Perusahaan</span><AppSearchSelect v-model="form.company" :options="companyOptions" :disabled="busy || loading" placeholder="Pilih perusahaan" /></label>
        <label><span>Cabang</span><AppSearchSelect v-model="form.branch" :options="branchOptions" :disabled="busy || loading" placeholder="Pilih cabang" /></label>
        <label><span>Principal Dua Kelinci</span><AppSearchSelect v-model="form.principal" :options="principalOptions" :disabled="busy || loading" placeholder="Pilih principal Dua Kelinci" /></label>
        <label><span>Basis jumlah untuk draft PO</span><AppSearchSelect v-model="form.basis" :options="basisOptions" :disabled="busy || batch?.status === 'processed'" placeholder="Pilih Kirim atau Terima" /></label>
      </div>
      <p class="dkpo-muted mt-3 text-sm text-slate-500 dark:text-slate-400">File Penerimaan Barang digunakan sebagai bahan draft PO, bukan pencatatan penerimaan ulang. Pilih dasar jumlah secara eksplisit; kedua jumlah tetap ditampilkan di preview.</p>
      <div class="mt-4 flex flex-wrap items-center gap-3">
        <input type="file" aria-label="File pembelian Dua Kelinci" accept=".xls,.xlsx" class="min-w-0 max-w-full text-sm" :disabled="busy || !canWrite" @change="selectFile" />
        <button class="btn-primary" :disabled="busy || loading || !canWrite || !scopeReady || !form.basis || !file" @click="preview">Preview File PO</button>
      </div>
      <div class="dkpo-divider mt-4 flex flex-wrap items-end gap-3 border-t border-slate-200 pt-4 dark:border-slate-700">
        <label class="w-full min-w-0 md:w-auto md:flex-1"><span>Batch tersimpan (50 terbaru)</span><AppSearchSelect v-model="selectedBatch" :options="batchOptions" :disabled="busy" placeholder="Pilih batch import PO" /></label>
        <button class="btn-secondary" :disabled="busy || !scopeReady" @click="run(batches)">Muat Riwayat</button>
        <button class="btn-secondary" :disabled="busy || !selectedBatch" @click="run(async () => { await loadBatch(selectedBatch); await router.replace({ query: { batch_id: batch.id } }); })">Buka Batch</button>
      </div>
    </section>
    <p v-if="error" role="alert" class="dkpo-feedback rounded-xl bg-rose-50 p-4 text-rose-800 dark:bg-rose-950 dark:text-rose-200">{{ error }}</p>
    <p v-if="success" role="status" class="dkpo-feedback rounded-xl bg-emerald-50 p-4 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">{{ success }}</p>
    <section v-if="batch" class="dkpo-panel">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div><h2 class="text-lg font-semibold">2. Tinjau {{ batch.source_ref }}</h2><p class="mt-1 text-sm">{{ principalLabel }} · {{ payload.source.source_date }} · {{ batch.status }}</p></div>
        <button v-if="batch.status !== 'processed' && canWrite" class="btn-secondary" :disabled="busy" @click="refresh">Simpan Basis &amp; Validasi Ulang</button>
      </div>
      <p v-if="basisChanged" class="dkpo-warning mt-3 text-sm text-amber-700 dark:text-amber-300">Basis jumlah berubah. Simpan dan validasi ulang sebelum membuat draft PO.</p>
      <p class="dkpo-muted mt-3 text-sm text-slate-500 dark:text-slate-400">Harga beli per satuan dasar, belum PPN. Koreksi hanya berlaku untuk batch ini. Nominal di bawah belum lengkap selama masih ada baris bermasalah.</p>
      <div class="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div class="dkpo-stat">Baris / bermasalah<strong>{{ rows.length }} / {{ payload.preview.error_count }}</strong></div>
        <div class="dkpo-stat">DPP baris valid<strong>Rp {{ money(payload.preview.totals.dpp) }}</strong></div>
        <div class="dkpo-stat">PPN baris valid<strong>Rp {{ money(payload.preview.totals.tax_amount) }}</strong></div>
        <div class="dkpo-stat">Total baris valid<strong>Rp {{ money(payload.preview.totals.total) }}</strong></div>
      </div>
      <input v-model="search" type="search" class="dkpo-input mt-4 w-full md:max-w-md" placeholder="Cari kode / produk / surat jalan" aria-label="Cari baris PO" />
      <div class="dkpo-divider mt-4 overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-700">
        <table class="w-full min-w-[900px] text-left text-sm">
          <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950 dark:text-slate-400"><tr><th>Baris / SJ</th><th>Produk sumber / ERP</th><th>Kirim / Terima</th><th>Basis / konversi</th><th>Harga / PPN</th><th>Total</th><th>Validasi</th></tr></thead>
          <tbody><tr v-for="r in filtered" :key="r.row_number" class="border-t border-slate-200 align-top dark:border-slate-700">
            <td>{{ r.row_number }}<small>{{ r.delivery_ref }}</small></td>
            <td><strong>{{ r.product_code }}</strong><small>{{ r.product_name || 'Nama sumber kosong' }}</small><small>{{ r.resolved?.nama || r.product?.nama || 'Belum dipetakan' }}</small></td>
            <td><small>Kirim: {{ quantityLabel(r.kirim) }}</small><small>Terima: {{ quantityLabel(r.terima) }}</small></td>
            <td>{{ batch.quantity_basis === 'kirim' ? 'Kirim' : 'Terima' }}<small v-if="r.resolved">{{ r.resolved.total_base }} {{ r.resolved.base_unit }}</small></td>
            <td>{{ r.resolved ? 'Rp ' + money(r.resolved.price) : 'Belum lengkap' }}<small v-if="r.resolved">PPN {{ money(r.resolved.ppn) }}%</small></td>
            <td class="whitespace-nowrap">{{ r.resolved ? 'Rp ' + money(r.resolved.total) : '—' }}</td>
            <td class="max-w-xs"><p v-for="e in r.errors" :key="e" class="dkpo-error text-rose-700 dark:text-rose-300">{{ e }}</p><p v-for="w in r.warnings" :key="w" class="dkpo-warning text-amber-700 dark:text-amber-300">{{ w }}</p><span v-if="!r.errors.length">Valid</span><button v-if="canWrite && batch.status !== 'processed'" class="btn-secondary mt-2" :disabled="busy" :aria-label="`Koreksi baris ${r.row_number}`" @click="openEdit(r)">Koreksi</button></td>
          </tr></tbody>
        </table>
      </div>
      <details class="mt-4 text-sm"><summary class="cursor-pointer">Metadata sumber dan catatan pembacaan</summary><p class="mt-2">Distributor: {{ payload.source.distributor }}. Kiriman: {{ payload.source.shipment_ref }}. Catatan: {{ payload.source.source_note || '—' }}.</p><p v-for="w in payload.source.warnings" :key="w" class="mt-2">{{ w }}</p><p class="mt-2">Teks kedaluwarsa disimpan untuk audit; tidak dipakai menambah stok atau menebak tanggal kedaluwarsa.</p></details>
      <div class="dkpo-divider mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-4 dark:border-slate-700">
        <p v-if="payload.order">PO {{ payload.order.kode }} sudah dibuat. Status proses: {{ payload.order.proses_id_berjalan }}.</p>
        <p v-else class="text-sm">{{ payload.preview.error_count ? 'Lengkapi seluruh baris, tidak ada barang yang dilewati.' : 'Seluruh baris valid. Tinjau nominal sebelum konfirmasi.' }}</p>
        <button v-if="batch.status !== 'processed'" class="btn-primary" :disabled="!canProcess" @click="confirmOpen = true">Buat Draft PO</button>
        <RouterLink v-else class="btn-primary" to="/purchase/order-confirmations">Buka Approval PO</RouterLink>
      </div>
    </section>
  </div>
  <AppModal :open="!!editRow" title="Koreksi baris pembelian" @close="!busy && closeEdit()">
    <div v-if="editRow" class="dkpo space-y-4">
      <p>Baris {{ editRow.row_number }} · {{ editRow.product_code }} · {{ editRow.product_name || 'Nama sumber kosong' }}</p>
      <label class="block"><span>Mapping produk Dua Kelinci</span><AppSearchSelect :model-value="edit.product" :options="productOptions" :loading="productLoading" :disabled="busy" remote-search placeholder="Cari kode / nama produk Dua Kelinci" @search="searchProducts" @update:model-value="chooseProduct" /></label>
      <div class="grid gap-4 sm:grid-cols-2">
        <label><span>Harga beli per {{ selectedProduct?.uoms?.find(u => u.level === 1)?.nama || 'satuan dasar' }}</span><input v-model="edit.price" aria-label="Harga beli satuan dasar" class="dkpo-input w-full" type="number" min="0.0001" step="0.0001" :disabled="busy" /><small>Master: {{ selectedProduct?.harga_beli == null ? 'belum diisi' : money(selectedProduct.harga_beli) }}. Kosong = gunakan master.</small></label>
        <label><span>PPN (%)</span><input v-model="edit.ppn" aria-label="PPN persen" class="dkpo-input w-full" type="number" min="0" max="100" step="0.0001" :disabled="busy" /><small>Master: {{ selectedProduct?.ppn_rate == null ? 'belum diisi' : money(selectedProduct.ppn_rate) + '%' }}. Nol berarti PPN 0%.</small></label>
      </div>
      <div v-for="(u, i) in editRow[form.basis]" :key="i">
        <label v-if="u.quantity" class="block"><span>UM {{ i + 1 }}: {{ u.quantity }} {{ u.unit || '(tanpa label)' }}</span><AppSearchSelect v-model="edit.units[i]" :options="unitOptions" :disabled="busy || !edit.product" placeholder="Otomatis sesuai label, atau pilih UOM" /></label>
      </div>
      <p class="dkpo-muted text-sm text-slate-500 dark:text-slate-400">Faktor mengikuti master UOM. Tidak membuat produk/UOM baru. Harga dan PPN manual hanya disimpan pada batch ini.</p>
      <button class="btn-primary" :disabled="busy || !edit.product" @click="saveEdit">Simpan Koreksi &amp; Validasi</button>
    </div>
  </AppModal>
  <AppModal :open="confirmOpen" title="Konfirmasi draft PO Dua Kelinci" @close="confirmOpen = false">
    <div v-if="batch" class="space-y-4"><p>{{ batch.source_ref }} · {{ principalLabel }}</p><p>Basis: {{ batch.quantity_basis === 'kirim' ? 'QTY Kirim' : 'QTY Terima' }}. {{ rows.length }} baris. Total termasuk PPN: Rp {{ money(payload.preview.totals.total) }}.</p><p>Draft masuk Approval Purchase Order. Stok, penerimaan, hutang dan jurnal belum dibuat.</p><button class="btn-primary" :disabled="!canProcess" @click="process">Ya, Buat Draft PO</button></div>
  </AppModal>
</template>

<style scoped>
.dkpo-panel { @apply min-w-0 rounded-2xl border border-slate-200 bg-white p-5 text-slate-900; }
.dkpo label > span { @apply mb-2 block text-sm font-medium; }
.dkpo small { @apply mt-1 block text-xs text-slate-500; }
.dkpo-input { @apply rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-slate-900; }
.dkpo-stat { @apply rounded-xl bg-slate-50 p-3 text-xs text-slate-500; }
.dkpo-stat strong { @apply mt-2 block break-words text-base text-slate-900; }
.dkpo th, .dkpo td { @apply px-3 py-3; }
.dkpo .btn-secondary, .dkpo-nav { @apply border-slate-300 text-slate-700; }
/* The ERP theme switch is data-theme, independent of the OS media query. */
:global(:root[data-theme='dark'] .dkpo-panel) { @apply border-slate-700 bg-slate-900 text-slate-100; }
:global(:root[data-theme='dark'] .dkpo-input) { @apply border-slate-600 bg-slate-950 text-slate-100; }
:global(:root[data-theme='dark'] .dkpo-stat), :global(:root[data-theme='dark'] .dkpo thead) { @apply bg-slate-950 text-slate-400; }
:global(:root[data-theme='dark'] .dkpo-stat strong) { @apply text-slate-100; }
:global(:root[data-theme='dark'] .dkpo small), :global(:root[data-theme='dark'] .dkpo-muted) { color: #94a3b8; }
:global(:root[data-theme='dark'] .dkpo-divider), :global(:root[data-theme='dark'] .dkpo tr) { border-color: #334155; }
:global(:root[data-theme='dark'] .dkpo-error) { color: #fda4af; }
:global(:root[data-theme='dark'] .dkpo-warning) { color: #fcd34d; }
:global(:root[data-theme='dark'] .dkpo .btn-secondary) { @apply border-slate-700 text-slate-200; }
:global(:root[data-theme='dark'] .dkpo-nav) { @apply border-slate-700 text-slate-200; }
:global(:root[data-theme='dark'] .dkpo-feedback[role='alert']) { @apply bg-rose-950 text-rose-200; }
:global(:root[data-theme='dark'] .dkpo-feedback[role='status']) { @apply bg-emerald-950 text-emerald-200; }
:global(:root[data-theme='light'] .dkpo thead) { @apply bg-slate-50 text-slate-500; }
:global(:root[data-theme='light'] .dkpo-divider), :global(:root[data-theme='light'] .dkpo tr) { border-color: #e2e8f0; }
:global(:root[data-theme='light'] .dkpo-muted) { color: #64748b; }
:global(:root[data-theme='light'] .dkpo-error) { color: #be123c; }
:global(:root[data-theme='light'] .dkpo-warning) { color: #b45309; }
:global(:root[data-theme='light'] .dkpo-feedback[role='alert']) { @apply bg-rose-50 text-rose-800; }
:global(:root[data-theme='light'] .dkpo-feedback[role='status']) { @apply bg-emerald-50 text-emerald-800; }
.dkpo .btn-primary:disabled, .dkpo .btn-secondary:disabled { @apply cursor-not-allowed opacity-50; }
</style>
