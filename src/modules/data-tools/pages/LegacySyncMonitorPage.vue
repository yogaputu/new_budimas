<script setup>
import { computed, onMounted, ref } from 'vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import { getLegacySyncStatus } from '@/api/dataImport';
import { normalizeError, unwrapResponse } from '@/utils/api';

const loading = ref(false);
const errorMessage = ref('');
const status = ref(null);

const tableLabels = {
  principal: 'Principal',
  produk: 'Produk',
  customer: 'Customer',
  plafon: 'Plafon',
  wms_rack_master: 'Master Rak',
  wms_stock_rak: 'Stok Rak',
  users: 'User',
  sales: 'Sales',
  sales_detail: 'Sales Detail'
};

const tableCards = computed(() => {
  const counts = status.value?.table_counts || {};
  return Object.entries(tableLabels).map(([key, label]) => ({
    key,
    label,
    value: counts[key]
  }));
});

const latestLog = computed(() => status.value?.latest_log || null);
const logInsertCounts = computed(() => latestLog.value?.insert_counts || {});
const latestAudit = computed(() => status.value?.latest_audit || []);
const auditSummary = computed(() => status.value?.audit_summary || []);
const stagingCounts = computed(() => status.value?.staging_counts || []);

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
  return new Intl.NumberFormat('id-ID').format(Number(value));
}

function formatDateTime(value) {
  if (!value) return '-';
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  return new Intl.DateTimeFormat('id-ID', {
    dateStyle: 'medium',
    timeStyle: 'short'
  }).format(date);
}

function statusBadgeClass(value) {
  if (value === 'error') return 'border-rose-500/40 bg-rose-500/15 text-rose-100';
  return 'border-emerald-500/40 bg-emerald-500/15 text-emerald-100';
}

async function loadStatus() {
  loading.value = true;
  errorMessage.value = '';

  try {
    const response = await getLegacySyncStatus();
    status.value = unwrapResponse(response);
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Status sync legacy belum bisa dimuat.');
  } finally {
    loading.value = false;
  }
}

onMounted(loadStatus);
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Monitor Sync Legacy"
      description="Pantau sinkronisasi insert-only dari SQL Server legacy ke PostgreSQL ERP."
    >
      <button class="btn-primary" type="button" :disabled="loading" @click="loadStatus">
        {{ loading ? 'Memuat...' : 'Refresh' }}
      </button>
    </PageHeader>

    <div v-if="errorMessage" class="rounded-lg border border-rose-500/40 bg-rose-500/10 p-4 text-sm font-semibold text-rose-100">
      {{ errorMessage }}
    </div>

    <section class="grid gap-4 lg:grid-cols-3">
      <div class="rounded-lg border border-slate-700 bg-slate-900/70 p-5">
        <p class="text-xs font-bold uppercase tracking-[0.24em] text-slate-400">Mode Sync</p>
        <div class="mt-3 flex items-center gap-3">
          <span class="rounded-full border border-cyan-400/40 bg-cyan-400/10 px-3 py-1 text-sm font-bold text-cyan-100">
            Insert Only
          </span>
          <span class="text-sm text-slate-300">Data lama tidak dioverwrite.</span>
        </div>
      </div>

      <div class="rounded-lg border border-slate-700 bg-slate-900/70 p-5">
        <p class="text-xs font-bold uppercase tracking-[0.24em] text-slate-400">Jadwal Cron</p>
        <p class="mt-3 text-lg font-bold text-white">{{ status?.cron?.schedule || '-' }}</p>
        <p class="mt-1 text-xs text-slate-400">{{ status?.cron?.script || '-' }}</p>
      </div>

      <div class="rounded-lg border border-slate-700 bg-slate-900/70 p-5">
        <p class="text-xs font-bold uppercase tracking-[0.24em] text-slate-400">Log Terakhir</p>
        <div class="mt-3 flex items-center gap-3">
          <span
            class="rounded-full border px-3 py-1 text-sm font-bold"
            :class="statusBadgeClass(latestLog?.status)"
          >
            {{ latestLog?.status === 'error' ? 'Perlu Cek' : 'Normal' }}
          </span>
          <span class="text-sm text-slate-300">{{ formatDateTime(latestLog?.modified_at) }}</span>
        </div>
      </div>
    </section>

    <section class="rounded-lg border border-slate-700 bg-slate-900/70 p-5">
      <div class="mb-4 flex flex-col gap-1">
        <h2 class="text-xl font-bold text-white">Total Data Saat Ini</h2>
        <p class="text-sm text-slate-400">Jumlah data utama di PostgreSQL setelah proses migrasi dan sync berjalan.</p>
      </div>
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        <div
          v-for="item in tableCards"
          :key="item.key"
          class="rounded-lg border border-slate-700 bg-slate-950/60 p-4"
        >
          <p class="text-xs font-bold uppercase tracking-[0.18em] text-slate-500">{{ item.label }}</p>
          <p class="mt-2 text-2xl font-black text-white">{{ formatNumber(item.value) }}</p>
        </div>
      </div>
    </section>

    <section class="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
      <div class="rounded-lg border border-slate-700 bg-slate-900/70 p-5">
        <div class="mb-4 flex flex-col gap-1">
          <h2 class="text-xl font-bold text-white">Insert Pada Log Terakhir</h2>
          <p class="text-sm text-slate-400">Angka ini berasal dari log `/var/log/budimas` pada run terakhir.</p>
        </div>
        <div v-if="Object.keys(logInsertCounts).length" class="grid gap-3 sm:grid-cols-2">
          <div
            v-for="(value, key) in logInsertCounts"
            :key="key"
            class="flex items-center justify-between rounded-lg border border-slate-700 bg-slate-950/60 px-4 py-3"
          >
            <span class="text-sm font-semibold text-slate-300">{{ key }}</span>
            <span class="text-lg font-black text-white">{{ formatNumber(value) }}</span>
          </div>
        </div>
        <p v-else class="rounded-lg border border-slate-700 bg-slate-950/60 p-4 text-sm text-slate-400">
          Belum ada angka insert pada log terakhir, atau log belum terbaca oleh API.
        </p>
      </div>

      <div class="rounded-lg border border-slate-700 bg-slate-900/70 p-5">
        <div class="mb-4 flex flex-col gap-1">
          <h2 class="text-xl font-bold text-white">Staging SQL Server</h2>
          <p class="text-sm text-slate-400">Estimasi jumlah baris pada schema `legacy_master_import_server`.</p>
        </div>
        <div class="max-h-80 overflow-auto rounded-lg border border-slate-700">
          <table class="min-w-full divide-y divide-slate-700 text-sm">
            <thead class="bg-slate-950/80 text-left text-xs uppercase tracking-[0.16em] text-slate-400">
              <tr>
                <th class="px-4 py-3">Table</th>
                <th class="px-4 py-3 text-right">Rows</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-800">
              <tr v-for="row in stagingCounts" :key="row.table_name">
                <td class="px-4 py-3 font-semibold text-slate-200">{{ row.table_name }}</td>
                <td class="px-4 py-3 text-right font-bold text-white">{{ formatNumber(row.estimated_rows) }}</td>
              </tr>
              <tr v-if="!stagingCounts.length">
                <td class="px-4 py-6 text-center text-slate-400" colspan="2">Data staging belum tersedia.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <section class="rounded-lg border border-slate-700 bg-slate-900/70 p-5">
      <div class="mb-4 flex flex-col gap-1">
        <h2 class="text-xl font-bold text-white">Ringkasan Audit Merge</h2>
        <p class="text-sm text-slate-400">Rekap insert yang tercatat di `legacy_master_merge_audit`.</p>
      </div>
      <div class="overflow-auto rounded-lg border border-slate-700">
        <table class="min-w-full divide-y divide-slate-700 text-sm">
          <thead class="bg-slate-950/80 text-left text-xs uppercase tracking-[0.16em] text-slate-400">
            <tr>
              <th class="px-4 py-3">Batch</th>
              <th class="px-4 py-3">Table</th>
              <th class="px-4 py-3">Action</th>
              <th class="px-4 py-3 text-right">Total</th>
              <th class="px-4 py-3">Terakhir</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800">
            <tr v-for="row in auditSummary" :key="`${row.batch_code}-${row.table_name}-${row.action}`">
              <td class="px-4 py-3 text-slate-300">{{ row.batch_code }}</td>
              <td class="px-4 py-3 font-semibold text-white">{{ row.table_name }}</td>
              <td class="px-4 py-3 text-slate-300">{{ row.action }}</td>
              <td class="px-4 py-3 text-right font-bold text-white">{{ formatNumber(row.total_rows) }}</td>
              <td class="px-4 py-3 text-slate-300">{{ formatDateTime(row.last_created_at) }}</td>
            </tr>
            <tr v-if="!auditSummary.length">
              <td class="px-4 py-6 text-center text-slate-400" colspan="5">Belum ada audit merge.</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="grid gap-4 xl:grid-cols-2">
      <div class="rounded-lg border border-slate-700 bg-slate-900/70 p-5">
        <div class="mb-4 flex flex-col gap-1">
          <h2 class="text-xl font-bold text-white">Audit Terakhir</h2>
          <p class="text-sm text-slate-400">50 catatan terbaru dari audit merge.</p>
        </div>
        <div class="max-h-96 overflow-auto rounded-lg border border-slate-700">
          <table class="min-w-full divide-y divide-slate-700 text-sm">
            <thead class="bg-slate-950/80 text-left text-xs uppercase tracking-[0.16em] text-slate-400">
              <tr>
                <th class="px-4 py-3">Waktu</th>
                <th class="px-4 py-3">Table</th>
                <th class="px-4 py-3">Kode</th>
                <th class="px-4 py-3">Pesan</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-800">
              <tr v-for="row in latestAudit" :key="`${row.table_name}-${row.target_id}-${row.created_at}`">
                <td class="whitespace-nowrap px-4 py-3 text-slate-300">{{ formatDateTime(row.created_at) }}</td>
                <td class="px-4 py-3 font-semibold text-white">{{ row.table_name }}</td>
                <td class="px-4 py-3 text-slate-300">{{ row.legacy_code || '-' }}</td>
                <td class="px-4 py-3 text-slate-300">{{ row.message || '-' }}</td>
              </tr>
              <tr v-if="!latestAudit.length">
                <td class="px-4 py-6 text-center text-slate-400" colspan="4">Belum ada audit terbaru.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="rounded-lg border border-slate-700 bg-slate-900/70 p-5">
        <div class="mb-4 flex flex-col gap-1">
          <h2 class="text-xl font-bold text-white">Tail Log Terakhir</h2>
          <p class="text-sm text-slate-400">{{ latestLog?.name || 'Log belum tersedia' }}</p>
        </div>
        <pre class="max-h-96 overflow-auto rounded-lg border border-slate-700 bg-slate-950 p-4 text-xs leading-6 text-slate-200">{{ (latestLog?.tail || []).join('\n') || 'Belum ada log yang bisa ditampilkan.' }}</pre>
      </div>
    </section>
  </div>
</template>
