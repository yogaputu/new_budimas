<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies } from '@/api/master';
import { getSupervisorAuditLogs, getSupervisorAuditOptions } from '@/api/supervisorAudit';
import { useAuthStore } from '@/app/stores/auth';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import { getLoginBranchId, isSuperUser } from '@/utils/accessScope';
import {
  getSupervisorBranchOptions,
  getSupervisorCompanyOptions,
  resetSupervisorBranchWhenCompanyChanges,
  syncSupervisorCompanyFromBranch
} from '@/modules/supervisor-sales/utils/supervisorScope';

const auth = useAuthStore();

const rows = ref([]);
const branches = ref([]);
const companies = ref([]);
const optionRows = ref({ modules: [], actions: [], users: [] });
const loading = ref(false);
const pageError = ref('');
const selectedLog = ref(null);

const filters = reactive({
  id_cabang: '',
  id_perusahaan: '',
  id_user: '',
  module: '',
  action: '',
  target: '',
  from: '',
  to: '',
  search: ''
});

const fallbackBranchId = computed(() => getLoginBranchId(auth.user));
const canUseAllScope = computed(() => isSuperUser(auth));

const branchOptions = computed(() =>
  getSupervisorBranchOptions(branches.value, auth, false, filters.id_perusahaan, companies.value)
);

const companyOptions = computed(() => {
  return getSupervisorCompanyOptions(companies.value, branches.value, '', auth);
});

const userOptions = computed(() => [
  { value: '', label: 'Semua Supervisor/User' },
  ...(optionRows.value.users || []).map((item) => ({
    value: String(item.value),
    label: item.label || `User ${item.value}`
  }))
]);

const moduleOptions = computed(() => [
  { value: '', label: 'Semua Modul' },
  ...(optionRows.value.modules || []).map((item) => ({
    value: String(item.value),
    label: formatModule(item.label || item.value)
  }))
]);

const actionOptions = computed(() => [
  { value: '', label: 'Semua Action' },
  ...(optionRows.value.actions || []).map((item) => ({
    value: String(item.value),
    label: formatAction(item.label || item.value)
  }))
]);

const tableColumns = [
  { key: 'created_at', label: 'Waktu' },
  { key: 'nama_user', label: 'Supervisor/User' },
  { key: 'scope', label: 'Scope', render: (row) => `${row.kode_cabang || row.nama_cabang || '-'} / ${row.kode_perusahaan || row.nama_perusahaan || '-'}` },
  { key: 'module_label', label: 'Modul', render: (row) => formatModule(row.module) },
  { key: 'action_label', label: 'Action', render: (row) => formatAction(row.action) },
  { key: 'target_code', label: 'Target', render: (row) => row.target_code || row.target_id || '-' },
  { key: 'note', label: 'Catatan' }
];

const filterFields = computed(() => [
  {
    key: 'id_perusahaan',
    label: 'Perusahaan',
    type: 'search-select',
    options: companyOptions.value,
    placeholder: 'Semua perusahaan'
  },
  {
    key: 'id_cabang',
    label: 'Cabang',
    type: 'search-select',
    options: branchOptions.value,
    placeholder: 'Pilih cabang',
    disabled: !filters.id_perusahaan || (!canUseAllScope.value && !!fallbackBranchId.value),
    emptyText: 'Pilih perusahaan terlebih dahulu.'
  },
  {
    key: 'id_user',
    label: 'Supervisor/User',
    type: 'search-select',
    options: userOptions.value,
    placeholder: 'Semua user'
  },
  {
    key: 'module',
    label: 'Modul',
    type: 'search-select',
    options: moduleOptions.value,
    placeholder: 'Semua modul'
  },
  {
    key: 'action',
    label: 'Action',
    type: 'search-select',
    options: actionOptions.value,
    placeholder: 'Semua action'
  },
  { key: 'target', label: 'Dokumen', placeholder: 'No dokumen / ID...' },
  { key: 'from', label: 'Dari Tanggal', type: 'date' },
  { key: 'to', label: 'Sampai Tanggal', type: 'date' },
  { key: 'search', label: 'Cari', placeholder: 'Target, catatan, user...' }
]);

function unwrapRows(response) {
  const payload = response?.data;
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.result)) return payload.result;
  if (Array.isArray(payload?.data)) return payload.data;
  if (Array.isArray(payload?.result?.data)) return payload.result.data;
  return [];
}

function unwrapResult(response) {
  return response?.data?.result || response?.data || {};
}

function formatModule(value) {
  return String(value || '-')
    .replace(/[-_]/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatAction(value) {
  return String(value || '-')
    .replace(/[-_]/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function prettyJson(value) {
  if (!value) return '-';
  try {
    const parsed = typeof value === 'string' ? JSON.parse(value) : value;
    return JSON.stringify(parsed, null, 2);
  } catch {
    return String(value);
  }
}

function buildParams() {
  return {
    ...filters,
    id_cabang: filters.id_cabang || (!canUseAllScope.value ? fallbackBranchId.value : ''),
    limit: 200
  };
}

async function loadReferences() {
  const [branchResponse, companyResponse, optionsResponse] = await Promise.all([
    getBranches(),
    getCompanies(),
    getSupervisorAuditOptions()
  ]);
  branches.value = unwrapRows(branchResponse);
  companies.value = unwrapRows(companyResponse);
  optionRows.value = unwrapResult(optionsResponse);

  if (!canUseAllScope.value && fallbackBranchId.value) {
    filters.id_cabang = String(fallbackBranchId.value);
    syncSupervisorCompanyFromBranch(filters, 'id_cabang', 'id_perusahaan', branches.value, companies.value);
  }
}

async function loadRows() {
  loading.value = true;
  pageError.value = '';
  try {
    const response = await getSupervisorAuditLogs(buildParams());
    rows.value = unwrapRows(response);
    const optionsResponse = await getSupervisorAuditOptions();
    optionRows.value = unwrapResult(optionsResponse);
  } catch (error) {
    pageError.value = error?.response?.data?.message || error?.message || 'Audit log supervisor belum bisa dimuat.';
  } finally {
    loading.value = false;
  }
}

function resetFilters() {
  filters.id_cabang = !canUseAllScope.value && fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  filters.id_perusahaan = '';
  syncSupervisorCompanyFromBranch(filters, 'id_cabang', 'id_perusahaan', branches.value, companies.value);
  filters.id_user = '';
  filters.module = '';
  filters.action = '';
  filters.target = '';
  filters.from = '';
  filters.to = '';
  filters.search = '';
  loadRows();
}

watch(
  () => filters.id_perusahaan,
  (value, previousValue) => {
    if (value === previousValue) return;
    resetSupervisorBranchWhenCompanyChanges(filters, 'id_perusahaan', 'id_cabang', branches.value, auth, companies.value);
  }
);

onMounted(async () => {
  try {
    await loadReferences();
    await loadRows();
  } catch (error) {
    pageError.value = error?.response?.data?.message || error?.message || 'Referensi audit log supervisor belum bisa dimuat.';
  }
});
</script>

<template>
  <PageHeader
    title="Audit Trail"
    description="Jejak approve, reject, edit, pembayaran, penerimaan, dan finalisasi lintas modul."
  >
    <button class="rounded-2xl border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-200 hover:bg-slate-800" @click="loadRows">
      Reload
    </button>
  </PageHeader>

  <div class="space-y-5">
    <div class="relative z-50">
      <AppFilterBar v-model="filters" :fields="filterFields" @submit="loadRows" @reset="resetFilters" />
    </div>

    <div v-if="pageError" class="rounded-2xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm font-semibold text-rose-200">
      {{ pageError }}
    </div>

    <section class="relative z-0 grid gap-4 md:grid-cols-4">
      <div class="panel-muted p-5">
        <p class="text-xs font-bold uppercase tracking-[0.28em] text-slate-400">Total Log</p>
        <p class="mt-3 text-2xl font-black text-white">{{ rows.length }}</p>
      </div>
      <div class="panel-muted p-5">
        <p class="text-xs font-bold uppercase tracking-[0.28em] text-slate-400">Modul</p>
        <p class="mt-3 text-2xl font-black text-white">{{ new Set(rows.map((row) => row.module).filter(Boolean)).size }}</p>
      </div>
      <div class="panel-muted p-5">
        <p class="text-xs font-bold uppercase tracking-[0.28em] text-slate-400">Action</p>
        <p class="mt-3 text-2xl font-black text-white">{{ new Set(rows.map((row) => row.action).filter(Boolean)).size }}</p>
      </div>
      <div class="panel-muted p-5">
        <p class="text-xs font-bold uppercase tracking-[0.28em] text-slate-400">User</p>
        <p class="mt-3 text-2xl font-black text-white">{{ new Set(rows.map((row) => row.id_user).filter(Boolean)).size }}</p>
      </div>
    </section>

    <div class="relative z-0">
      <AppTable
      :columns="tableColumns"
      :rows="rows"
      :loading="loading"
      row-key="id"
      clickable-rows
      empty-message="Belum ada audit trail untuk filter ini."
      @row-click="selectedLog = $event"
      />
    </div>
  </div>

  <AppModal
    :open="!!selectedLog"
    title="Detail Audit Trail"
    description="Before/after data ditampilkan untuk membantu pemeriksaan perubahan dokumen."
    size="6xl"
    @close="selectedLog = null"
  >
    <div v-if="selectedLog" class="space-y-5">
      <div class="grid gap-4 md:grid-cols-4">
        <div class="panel-muted p-4">
          <p class="text-xs font-bold uppercase tracking-[0.25em] text-slate-400">Waktu</p>
          <p class="mt-2 font-semibold text-white">{{ selectedLog.created_at || '-' }}</p>
        </div>
        <div class="panel-muted p-4">
          <p class="text-xs font-bold uppercase tracking-[0.25em] text-slate-400">User</p>
          <p class="mt-2 font-semibold text-white">{{ selectedLog.nama_user || '-' }}</p>
        </div>
        <div class="panel-muted p-4">
          <p class="text-xs font-bold uppercase tracking-[0.25em] text-slate-400">Modul</p>
          <p class="mt-2 font-semibold text-white">{{ formatModule(selectedLog.module) }}</p>
        </div>
        <div class="panel-muted p-4">
          <p class="text-xs font-bold uppercase tracking-[0.25em] text-slate-400">Action</p>
          <p class="mt-2 font-semibold text-white">{{ formatAction(selectedLog.action) }}</p>
        </div>
      </div>

      <div class="grid gap-4 md:grid-cols-2">
        <div class="panel-muted p-4">
          <p class="text-xs font-bold uppercase tracking-[0.25em] text-slate-400">Target</p>
          <p class="mt-2 font-semibold text-white">{{ selectedLog.target_type || '-' }} / {{ selectedLog.target_code || selectedLog.target_id || '-' }}</p>
        </div>
        <div class="panel-muted p-4">
          <p class="text-xs font-bold uppercase tracking-[0.25em] text-slate-400">Scope</p>
          <p class="mt-2 font-semibold text-white">{{ selectedLog.nama_cabang || '-' }} / {{ selectedLog.nama_perusahaan || '-' }}</p>
        </div>
      </div>

      <div class="panel-muted p-4">
        <p class="text-xs font-bold uppercase tracking-[0.25em] text-slate-400">Catatan</p>
        <p class="mt-2 whitespace-pre-wrap text-sm text-slate-200">{{ selectedLog.note || '-' }}</p>
      </div>

      <div class="grid gap-4 lg:grid-cols-2">
        <div class="panel-muted p-4">
          <p class="text-xs font-bold uppercase tracking-[0.25em] text-slate-400">Before</p>
          <pre class="mt-3 max-h-[360px] overflow-auto rounded-2xl bg-slate-950 p-4 text-xs text-slate-200">{{ prettyJson(selectedLog.before_data) }}</pre>
        </div>
        <div class="panel-muted p-4">
          <p class="text-xs font-bold uppercase tracking-[0.25em] text-slate-400">After</p>
          <pre class="mt-3 max-h-[360px] overflow-auto rounded-2xl bg-slate-950 p-4 text-xs text-slate-200">{{ prettyJson(selectedLog.after_data) }}</pre>
        </div>
      </div>
    </div>
  </AppModal>
</template>
