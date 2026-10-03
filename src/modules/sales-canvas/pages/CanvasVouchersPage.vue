<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { getVouchers } from '@/api/promo';
import PageHeader from '@/shared/components/PageHeader.vue';
import AppModal from '@/shared/components/AppModal.vue';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { formatCurrency, formatDate } from '@/modules/sales-canvas/utils/canvasFormat';

const router = useRouter();

const rows = ref([]);
const selectedRow = ref(null);
const detailOpen = ref(false);
const loading = ref(false);
const errorMessage = ref('');
const search = ref('');

function normalizeDate(value) {
  const raw = String(value || '').slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(raw) ? raw : '';
}

function normalizeChannelScope(value) {
  const scope = String(value || '').trim().toLowerCase();
  return ['promo', 'canvas', 'both'].includes(scope) ? scope : 'both';
}

function channelScopeLabel(row) {
  return {
    canvas: 'Canvas',
    both: 'Promo All-In & Canvas',
    promo: 'Promo All-In'
  }[normalizeChannelScope(row?.channel_scope)];
}

function voucherAvailability(row) {
  const today = new Date().toISOString().slice(0, 10);
  const startsAt = normalizeDate(row?.tanggal_mulai);
  const endsAt = normalizeDate(row?.tanggal_kadaluarsa);

  if (Number(row?.status_voucher) !== 1) {
    return { key: 'inactive', label: 'Nonaktif', className: 'bg-slate-100 text-slate-700 dark:bg-slate-500/15 dark:text-slate-200' };
  }
  if (startsAt && startsAt > today) {
    return { key: 'scheduled', label: 'Belum mulai', className: 'bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-200' };
  }
  if (endsAt && endsAt < today) {
    return { key: 'expired', label: 'Kedaluwarsa', className: 'bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-200' };
  }
  return { key: 'active', label: 'Tersedia', className: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-200' };
}

function canUseInCanvas(row) {
  return voucherAvailability(row).key === 'active'
    && ['canvas', 'both'].includes(normalizeChannelScope(row?.channel_scope))
    && [2, 3].includes(Number(row?.tipe_voucher));
}

const filteredRows = computed(() => {
  const query = search.value.trim().toLowerCase();
  const filtered = !query ? rows.value : rows.value.filter((item) =>
    [item.kode_voucher, item.nama_voucher, item.nama_principal, item.syarat_ketentuan, channelScopeLabel(item)]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query))
  );
  return [...filtered].sort((left, right) => {
    const leftAvailable = voucherAvailability(left).key === 'active' ? 0 : 1;
    const rightAvailable = voucherAvailability(right).key === 'active' ? 0 : 1;
    return leftAvailable - rightAvailable || Number(left.tipe_voucher || 0) - Number(right.tipe_voucher || 0);
  });
});

const summaryCards = computed(() => [
  { label: 'Total Voucher', value: String(rows.value.length) },
  { label: 'Aktif Sekarang', value: String(rows.value.filter((item) => canUseInCanvas(item)).length) },
  { label: 'Voucher 2', value: String(rows.value.filter((item) => Number(item.tipe_voucher) === 2).length) },
  { label: 'Voucher 3', value: String(rows.value.filter((item) => Number(item.tipe_voucher) === 3).length) }
]);

function normalizeVoucher(item, type) {
  return {
    ...item,
    channel_scope: normalizeChannelScope(item.channel_scope),
    tipe_voucher: item.tipe_voucher || type,
    diskon_label: [item.persentase_diskon_1, item.persentase_diskon_2, item.persentase_diskon_3]
      .filter((value) => Number(value || 0) > 0)
      .map((value) => `${value}%`)
      .join(' + ') || (Number(item.nominal_diskon || 0) > 0 ? formatCurrency(item.nominal_diskon) : '-')
  };
}

function responseRows(response) {
  const payload = unwrapResponse(response) || {};
  return normalizeList(payload.pages || payload.rows || payload);
}

async function loadData() {
  loading.value = true;
  errorMessage.value = '';
  try {
    const [v2, v3] = await Promise.all([
      getVouchers({ 'tipe-voucher': 2, scope_context: 'canvas', page: 0, limit: 250 }),
      getVouchers({ 'tipe-voucher': 3, scope_context: 'canvas', page: 0, limit: 250 })
    ]);
    rows.value = [
      ...responseRows(v2).map((item) => normalizeVoucher(item, 2)),
      ...responseRows(v3).map((item) => normalizeVoucher(item, 3))
    ];
  } catch (error) {
    errorMessage.value = normalizeError(error);
  } finally {
    loading.value = false;
  }
}

function openDetail(row) {
  selectedRow.value = row;
  detailOpen.value = true;
}

function useVoucher(row = selectedRow.value) {
  if (!row) return;
  if (!canUseInCanvas(row)) return;
  detailOpen.value = false;
  router.push({
    name: 'sales-canvas-orders',
    query: {
      voucher_type: String(row.tipe_voucher),
      voucher_id: String(row.id)
    }
  });
}

onMounted(loadData);
</script>

<template>
  <PageHeader title="Info Voucher Canvas" description="Voucher yang memang ditujukan untuk Order Canvas. Kelola programnya dari master voucher yang sama dengan Promo All-In.">
    <div class="header-actions">
      <button class="btn btn-secondary" :disabled="loading" @click="loadData">Reload</button>
      <button class="btn btn-secondary" @click="router.push({ name: 'sales-canvas-vouchers-manage' })">Kelola Voucher Canvas</button>
      <button class="btn btn-primary" @click="router.push({ name: 'sales-canvas-orders' })">Gunakan di Order Canvas</button>
    </div>
  </PageHeader>

  <div v-if="errorMessage" class="alert error">{{ errorMessage }}</div>

  <section class="summary-grid">
    <div v-for="card in summaryCards" :key="card.label" class="summary-card">
      <span>{{ card.label }}</span>
      <strong>{{ card.value }}</strong>
    </div>
  </section>

  <section class="management-note">
    <strong>Pengelolaan voucher terpusat</strong>
    <span>Tambah, edit, nonaktifkan, atau hapus lewat tombol <b>Kelola Voucher Canvas</b>. Data tetap memakai master Voucher yang sama dengan Promo All-In; atur cakupannya menjadi <b>Canvas</b> atau <b>Promo All-In &amp; Canvas</b>, bukan membuat voucher ganda.</span>
  </section>

  <section class="panel">
    <div class="toolbar">
      <div>
        <h2>List Voucher</h2>
        <p>{{ filteredRows.length }} voucher tampil dari {{ rows.length }} voucher tersedia.</p>
      </div>
      <input v-model="search" class="input" placeholder="Cari kode, nama, principal, syarat..." />
    </div>

    <div class="voucher-grid">
      <button v-for="row in filteredRows" :key="`${row.tipe_voucher}-${row.id}`" class="voucher-card" @click="openDetail(row)">
        <span class="voucher-card-top">
          <span class="voucher-type">V{{ row.tipe_voucher }}</span>
          <span class="availability-badge" :class="voucherAvailability(row).className">{{ voucherAvailability(row).label }}</span>
        </span>
        <strong>{{ row.nama_voucher || row.kode_voucher || 'Voucher' }}</strong>
        <small>{{ row.kode_voucher || '-' }}</small>
        <div class="voucher-meta">
          <span>{{ row.diskon_label }}</span>
          <span>{{ channelScopeLabel(row) }}</span>
          <span>{{ formatDate(row.tanggal_mulai) }} - {{ formatDate(row.tanggal_kadaluarsa) }}</span>
        </div>
        <span class="voucher-use-note">
          {{ canUseInCanvas(row) ? 'Klik untuk lihat detail dan gunakan di Order Canvas.' : 'Klik untuk melihat syarat voucher atau status ketersediaannya.' }}
        </span>
      </button>
      <div v-if="!loading && !filteredRows.length" class="empty">Voucher canvas belum tersedia.</div>
    </div>
  </section>

  <AppModal :open="detailOpen" title="Detail Info Voucher Canvas" size="lg" @close="detailOpen = false">
    <div v-if="selectedRow" class="detail-grid">
      <div class="info-card">
        <span>Kode Voucher</span>
        <strong>{{ selectedRow.kode_voucher || '-' }}</strong>
      </div>
      <div class="info-card">
        <span>Jenis</span>
        <strong>Voucher {{ selectedRow.tipe_voucher }}</strong>
      </div>
      <div class="info-card">
        <span>Diskon</span>
        <strong>{{ selectedRow.diskon_label }}</strong>
      </div>
      <div class="info-card">
        <span>Status Saat Ini</span>
        <strong>{{ voucherAvailability(selectedRow).label }}</strong>
      </div>
      <div class="info-card">
        <span>Berlaku untuk</span>
        <strong>{{ channelScopeLabel(selectedRow) }}</strong>
      </div>
      <div class="info-card">
        <span>Minimal Pembelian</span>
        <strong>{{ formatCurrency(selectedRow.minimal_total_pembelian || selectedRow.minimal_subtotal_pembelian || 0) }}</strong>
      </div>
      <div class="info-card">
        <span>Periode</span>
        <strong>{{ formatDate(selectedRow.tanggal_mulai) }} - {{ formatDate(selectedRow.tanggal_kadaluarsa) }}</strong>
      </div>
      <div class="info-card wide">
        <span>Nama Voucher</span>
        <strong>{{ selectedRow.nama_voucher || '-' }}</strong>
      </div>
      <div class="info-card wide">
        <span>Cara Penggunaan</span>
        <p v-if="canUseInCanvas(selectedRow)">Pilih voucher ini di modal Tambah Order Canvas. Sistem akan memvalidasi ulang customer, cabang, produk, dan qty sebelum order dapat disimpan.</p>
        <p v-else>Voucher belum bisa dipakai sampai periode dan syarat order terpenuhi.</p>
      </div>
      <div class="info-card wide">
        <span>Syarat & Ketentuan</span>
        <p>{{ selectedRow.syarat_ketentuan || '-' }}</p>
      </div>
    </div>
    <template #footer>
      <div class="modal-actions">
        <button class="btn btn-secondary" @click="detailOpen = false">Tutup</button>
        <button v-if="selectedRow && canUseInCanvas(selectedRow)" class="btn btn-primary" @click="useVoucher(selectedRow)">Gunakan di Order Canvas</button>
      </div>
    </template>
  </AppModal>
</template>

<style scoped>
.summary-grid,
.voucher-grid,
.detail-grid {
  display: grid;
  gap: 16px;
}

.summary-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin: 20px 0;
}

.voucher-grid {
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
}

.panel,
.summary-card,
.voucher-card,
.info-card,
.management-note {
  border: 1px solid rgba(148, 163, 184, 0.26);
  border-radius: 20px;
  background: rgba(15, 23, 42, 0.72);
}

.panel {
  padding: 22px;
}

.management-note {
  align-items: flex-start;
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0 0 20px;
  padding: 16px 18px;
}

.management-note strong {
  color: var(--text-primary, #fff);
}

.management-note span {
  color: #9fb5d4;
  font-size: 14px;
  line-height: 1.5;
}

.summary-card,
.voucher-card,
.info-card {
  padding: 18px;
}

.summary-card span,
.info-card span,
.voucher-type {
  color: #93a7c5;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.summary-card strong {
  color: var(--text-primary, #fff);
  display: block;
  font-size: 24px;
  margin-top: 10px;
}

.toolbar {
  align-items: end;
  display: flex;
  gap: 16px;
  justify-content: space-between;
  margin-bottom: 18px;
}

.header-actions,
.modal-actions,
.voucher-card-top {
  align-items: center;
  display: flex;
  gap: 10px;
}

.header-actions,
.modal-actions {
  flex-wrap: wrap;
}

.modal-actions {
  justify-content: flex-end;
}

.voucher-card-top {
  justify-content: space-between;
}

.toolbar h2 {
  margin: 0 0 6px;
}

.toolbar p,
.voucher-card small,
.info-card p {
  color: #9fb5d4;
  margin: 0;
}

.input {
  background: rgba(2, 6, 23, 0.8);
  border: 1px solid rgba(148, 163, 184, 0.32);
  border-radius: 14px;
  color: #fff;
  min-width: 320px;
  padding: 12px 14px;
}

.voucher-card {
  color: #fff;
  cursor: pointer;
  text-align: left;
}

.voucher-card strong {
  display: block;
  font-size: 18px;
  margin: 14px 0 4px;
}

.availability-badge {
  border-radius: 999px;
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0;
  padding: 5px 8px;
  text-transform: none;
}

.voucher-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 16px;
}

.voucher-meta span:first-child {
  color: #bef264;
  font-weight: 900;
}

.voucher-meta span:last-child {
  color: #bfdbfe;
}

.voucher-use-note {
  color: #a5b4fc;
  display: block;
  font-size: 12px;
  line-height: 1.45;
  margin-top: 16px;
}

.detail-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.info-card.wide {
  grid-column: 1 / -1;
}

.info-card strong {
  color: #fff;
  display: block;
  margin-top: 8px;
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

.btn {
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 14px;
  color: #fff;
  cursor: pointer;
  font-weight: 900;
  padding: 11px 16px;
}

.btn-secondary {
  background: rgba(15, 23, 42, 0.82);
}

.btn-primary {
  background: #6d28d9;
  border-color: #7c3aed;
}

.empty {
  color: #9fb5d4;
  grid-column: 1 / -1;
  padding: 24px;
  text-align: center;
}

@media (max-width: 720px) {
  .summary-grid,
  .detail-grid {
    grid-template-columns: 1fr;
  }

  .toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .input {
    min-width: 0;
    width: 100%;
  }
}

@media (max-width: 900px) {
  .summary-grid,
  .detail-grid {
    grid-template-columns: 1fr;
  }

  .toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .input {
    min-width: 0;
    width: 100%;
  }
}
</style>
