<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies } from '@/api/master';
import {
  createAccountingTransaction,
  getAccountingTransactions,
  getCompanyBankAccounts,
  updateAccountingTransaction
} from '@/api/finance';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getRowBranchIds, getRowCompanyId, isSuperUser, scopeRowsByLoginBranch } from '@/utils/accessScope';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const today = new Date().toISOString().slice(0, 10);

const filters = reactive({
  branchId: '',
  companyId: '',
  rekeningId: '',
  date: '',
  type: ''
});

const form = reactive({
  id_mutasi_acc: '',
  tanggal_transaksi: today,
  id_rekening_perusahaan: '',
  tipe: '1',
  nominal: '',
  keterangan: ''
});

const rows = ref([]);
const branches = ref([]);
const companies = ref([]);
const accounts = ref([]);
const loading = reactive({ refs: false, accounts: false, list: false, save: false });
const pageError = ref('');
const feedback = ref('');
const actionError = ref('');
const modalOpen = ref(false);
const mode = ref('create');

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const canAccessAllBranches = computed(() => isSuperUser(authStore));

const branchOptions = computed(() =>
  scopeRowsByLoginBranch(branches.value, authStore).map((item) => ({
    value: String(item.id),
    label: `${item.kode ? `${item.kode} - ` : ''}${item.nama || item.nama_cabang || `Cabang ${item.id}`}`
  }))
);

function companyIdsForBranch(branchId) {
  if (!branchId) return [];
  const ids = new Set();
  const branch = branches.value.find((item) => String(item.id) === String(branchId));
  const directCompanyId = getRowCompanyId(branch);
  if (directCompanyId) ids.add(String(directCompanyId));

  companies.value.forEach((item) => {
    if (getRowBranchIds(item).some((id) => String(id) === String(branchId))) {
      ids.add(String(item.id));
    }
  });

  return [...ids];
}

function companyOption(item) {
  return {
    value: String(item.id),
    label: `${item.kode ? `${item.kode} - ` : ''}${item.nama || item.nama_perusahaan || `Perusahaan ${item.id}`}`
  };
}

const companyOptions = computed(() => {
  const allowed = companyIdsForBranch(filters.branchId);
  return companies.value.filter((item) => allowed.includes(String(item.id))).map(companyOption);
});

const accountOptions = computed(() =>
  accounts.value.map((item) => ({
    value: String(item.id_rekening_perusahaan || item.id),
    label: `${item.nama_bank || 'Bank'} - ${item.nomor_rekening || '-'} (${item.nama_pemilik || '-'})`
  }))
);

const typeOptions = [
  { value: '', label: 'Semua Tipe' },
  { value: '1', label: 'Masuk' },
  { value: '2', label: 'Keluar' }
];

const formTypeOptions = typeOptions.filter((item) => item.value);

const columns = [
  { key: 'kode_transaksi', label: 'Kode Transaksi' },
  { key: 'tanggal_transaksi', label: 'Tanggal', render: (row) => formatDate(row.tanggal_transaksi) },
  { key: 'nama_perusahaan', label: 'Perusahaan', render: (row) => row.nama_perusahaan || resolveCompanyName(row.id_perusahaan) },
  { key: 'rekening', label: 'Rekening', render: (row) => `${row.nama_bank || 'Bank'} - ${row.nomor_rekening || '-'}` },
  { key: 'tipe_transaksi', label: 'Tipe', render: (row) => transactionBadge(row.tipe_transaksi || row.tipe) },
  { key: 'nominal', label: 'Nominal', render: (row) => formatCurrency(row.nominal) },
  { key: 'status', label: 'Status', render: (row) => statusBadge(row.status) },
  { key: 'keterangan', label: 'Keterangan' }
];

function formatCurrency(value) {
  return new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(Number(value || 0));
}

function formatDate(value) {
  if (!value) return '-';
  return new Intl.DateTimeFormat('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(value));
}

function transactionBadge(type) {
  return String(type) === '2'
    ? { text: 'Keluar', className: 'inline-flex rounded-full bg-rose-100 px-3 py-1 text-xs font-bold text-rose-700' }
    : { text: 'Masuk', className: 'inline-flex rounded-full bg-emerald-100 px-3 py-1 text-xs font-bold text-emerald-700' };
}

function statusBadge(status) {
  return Number(status) === 1
    ? { text: 'Terkonfirmasi', className: 'inline-flex rounded-full bg-emerald-100 px-3 py-1 text-xs font-bold text-emerald-700' }
    : { text: 'Draft', className: 'inline-flex rounded-full bg-amber-100 px-3 py-1 text-xs font-bold text-amber-700' };
}

function resolveCompanyName(id) {
  return companies.value.find((item) => String(item.id) === String(id))?.nama || '-';
}

async function loadReferences() {
  loading.refs = true;
  try {
    const [branchResponse, companyResponse] = await Promise.all([getBranches(), getCompanies()]);
    branches.value = normalizeList(unwrapResponse(branchResponse));
    companies.value = normalizeList(unwrapResponse(companyResponse));
    if (!canAccessAllBranches.value && fallbackBranchId.value) {
      filters.branchId = String(fallbackBranchId.value);
    }
  } catch (error) {
    pageError.value = normalizeError(error, 'Referensi input transaksi belum bisa dimuat.');
  } finally {
    loading.refs = false;
  }
}

async function loadAccounts() {
  accounts.value = [];
  filters.rekeningId = '';
  form.id_rekening_perusahaan = '';
  if (!filters.companyId) return;

  loading.accounts = true;
  try {
    const response = await getCompanyBankAccounts({
      clause: JSON.stringify({ id_perusahaan: `=${Number(filters.companyId)}` })
    });
    accounts.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    pageError.value = normalizeError(error, 'Daftar rekening perusahaan belum bisa dimuat.');
  } finally {
    loading.accounts = false;
  }
}

async function loadRows() {
  loading.list = true;
  pageError.value = '';
  try {
    const response = await getAccountingTransactions({
      tanggal_transaksi: filters.date || undefined,
      id_rekening_perusahaan: filters.rekeningId || undefined,
      tipe: filters.type || undefined
    });
    const list = normalizeList(unwrapResponse(response));
    rows.value = filters.companyId ? list.filter((item) => String(item.id_perusahaan) === String(filters.companyId)) : list;
  } catch (error) {
    rows.value = [];
    pageError.value = normalizeError(error, 'Daftar transaksi belum bisa dimuat.');
  } finally {
    loading.list = false;
  }
}

function openCreate() {
  mode.value = 'create';
  actionError.value = '';
  feedback.value = '';
  Object.assign(form, {
    id_mutasi_acc: '',
    tanggal_transaksi: today,
    id_rekening_perusahaan: filters.rekeningId || '',
    tipe: '1',
    nominal: '',
    keterangan: ''
  });
  modalOpen.value = true;
}

function openEdit(row) {
  if (Number(row.status) === 1) return;
  mode.value = 'edit';
  actionError.value = '';
  feedback.value = '';
  Object.assign(form, {
    id_mutasi_acc: String(row.id_mutasi_acc || ''),
    tanggal_transaksi: String(row.tanggal_transaksi || today).slice(0, 10),
    id_rekening_perusahaan: String(row.id_rekening_perusahaan || ''),
    tipe: String(row.tipe_transaksi || row.tipe || '1'),
    nominal: Number(row.nominal || 0),
    keterangan: row.keterangan || ''
  });
  modalOpen.value = true;
}

async function saveTransaction() {
  if (!form.tanggal_transaksi || !form.id_rekening_perusahaan || !form.tipe || !form.nominal) {
    actionError.value = 'Tanggal, rekening, tipe, dan nominal wajib diisi.';
    return;
  }

  loading.save = true;
  actionError.value = '';
  feedback.value = '';
  try {
    if (mode.value === 'create') {
      await createAccountingTransaction(form);
      feedback.value = 'Transaksi berhasil ditambahkan.';
    } else {
      await updateAccountingTransaction(form);
      feedback.value = 'Transaksi berhasil diperbarui.';
    }
    modalOpen.value = false;
    await loadRows();
  } catch (error) {
    actionError.value = normalizeError(error, 'Transaksi belum berhasil disimpan.');
  } finally {
    loading.save = false;
  }
}

watch(
  () => filters.branchId,
  () => {
    filters.companyId = '';
    rows.value = [];
  }
);

watch(
  () => filters.companyId,
  async () => {
    await loadAccounts();
    rows.value = [];
  }
);

onMounted(async () => {
  await loadReferences();
  await loadRows();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Input Transaksi"
      description="Input transaksi kas/bank manual ke rekening perusahaan, sebagai penghubung mutasi dan jurnal accounting."
    >
      <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-bold text-white" :disabled="!filters.companyId" @click="openCreate">
        Tambah Transaksi
      </button>
    </PageHeader>

    <section class="panel p-5">
      <div class="grid gap-4 xl:grid-cols-6">
        <AppSearchSelect
          v-model="filters.branchId"
          label="Cabang"
          placeholder="Pilih cabang"
          :options="branchOptions"
          :disabled="!canAccessAllBranches && !!fallbackBranchId"
        />
        <AppSearchSelect
          v-model="filters.companyId"
          label="Perusahaan"
          placeholder="Pilih perusahaan"
          :options="companyOptions"
          :disabled="!filters.branchId"
          empty-text="Pilih cabang terlebih dahulu."
        />
        <AppSearchSelect
          v-model="filters.rekeningId"
          label="Rekening"
          placeholder="Semua rekening"
          :options="accountOptions"
          :disabled="!filters.companyId || loading.accounts"
          empty-text="Rekening belum tersedia untuk perusahaan ini."
        />
        <AppSearchSelect v-model="filters.type" label="Tipe" placeholder="Semua tipe" :options="typeOptions" />
        <div>
          <label class="field-label">Tanggal</label>
          <input v-model="filters.date" type="date" class="field-control" />
        </div>
        <button class="self-end rounded-xl bg-brand-600 px-4 py-3 text-sm font-bold text-white" @click="loadRows">
          Terapkan
        </button>
      </div>
    </section>

    <section v-if="feedback" class="rounded-2xl border border-emerald-300/40 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
      {{ feedback }}
    </section>
    <section v-if="pageError" class="rounded-2xl border border-rose-300/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
      {{ pageError }}
    </section>

    <AppTable
      :columns="columns"
      :rows="rows"
      :loading="loading.list"
      clickable-rows
      row-key="id_mutasi_acc"
      empty-message="Belum ada transaksi pada filter ini."
      @row-click="openEdit"
    />

    <AppModal
      :open="modalOpen"
      :title="mode === 'create' ? 'Tambah Transaksi' : 'Edit Transaksi'"
      description="Transaksi yang sudah terkonfirmasi tidak dapat diubah."
      size="4xl"
      @close="modalOpen = false"
    >
      <section v-if="actionError" class="mb-4 rounded-2xl border border-rose-300/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
        {{ actionError }}
      </section>
      <div class="grid gap-4 md:grid-cols-2">
        <div>
          <label class="field-label">Tanggal Transaksi</label>
          <input v-model="form.tanggal_transaksi" type="date" class="field-control" />
        </div>
        <AppSearchSelect
          v-model="form.id_rekening_perusahaan"
          label="Rekening Perusahaan"
          placeholder="Pilih rekening"
          :options="accountOptions"
          empty-text="Pilih perusahaan yang punya rekening terlebih dahulu."
        />
        <AppSearchSelect v-model="form.tipe" label="Tipe Transaksi" placeholder="Pilih tipe" :options="formTypeOptions" />
        <div>
          <label class="field-label">Nominal</label>
          <input v-model="form.nominal" type="number" min="0" class="field-control" />
        </div>
        <div class="md:col-span-2">
          <label class="field-label">Keterangan</label>
          <textarea v-model="form.keterangan" rows="4" class="field-control resize-none" />
        </div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-3">
          <button class="rounded-xl border border-slate-700 px-4 py-3 text-sm font-bold" @click="modalOpen = false">Tutup</button>
          <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-bold text-white disabled:opacity-60" :disabled="loading.save" @click="saveTransaction">
            {{ loading.save ? 'Menyimpan...' : mode === 'create' ? 'Simpan Transaksi' : 'Perbarui Transaksi' }}
          </button>
        </div>
      </template>
    </AppModal>
  </div>
</template>
