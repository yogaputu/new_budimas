<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies } from '@/api/master';
import { getAccountCoaList, getGeneralLedger } from '@/api/finance';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getRowBranchIds, getRowCompanyId, hasMultiBusinessScope, hasSupervisorSalesScope, isSuperUser, scopeRowsByLoginBranch } from '@/utils/accessScope';
import { firstLocalDayOfMonth, toLocalDateInputValue } from '@/utils/date';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const today = new Date();
const defaultFrom = toLocalDateInputValue(firstLocalDayOfMonth(today));
const defaultTo = toLocalDateInputValue(today);

const form = reactive({
  coaId: '',
  branchId: '',
  companyId: '',
  from: defaultFrom,
  to: defaultTo
});

const coaRows = ref([]);
const companyRows = ref([]);
const branchRows = ref([]);
const ledgerRows = ref([]);
const summary = ref({
  saldo_awal: 0,
  total_debet: 0,
  total_kredit: 0,
  saldo_akhir: 0
});
const loading = reactive({
  options: false,
  ledger: false
});
const feedback = ref('');
const errorMessage = ref('');

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const canAccessAllBranches = computed(() => isSuperUser(authStore));
const shouldLockBusinessScope = computed(() => !canAccessAllBranches.value && !hasSupervisorSalesScope(authStore.user) && !hasMultiBusinessScope(authStore.user));

const coaOptions = computed(() =>
  coaRows.value.map((item) => ({
    value: String(item.id_coa || item.id || ''),
    label: `${item.nomor_akun || item.kode || '-'} - ${item.nama_akun || item.nama || 'Akun'}`
  }))
);

const branchOptions = computed(() =>
  scopeRowsByLoginBranch(branchRows.value, authStore).map((item) => ({
    value: String(item.id),
    label: `${item.kode || '-'} - ${item.nama || item.nama_cabang || 'Cabang'}`
  }))
);

function companyIdsForBranch(branchId) {
  if (!branchId) return [];

  const ids = new Set();
  const branch = branchRows.value.find((item) => String(item.id) === String(branchId));
  const directCompanyId = getRowCompanyId(branch);
  if (directCompanyId) ids.add(String(directCompanyId));

  companyRows.value.forEach((item) => {
    if (getRowBranchIds(item).some((id) => String(id) === String(branchId))) {
      ids.add(String(item.id));
    }
  });

  return [...ids];
}

const companyOptions = computed(() =>
  companyRows.value
    .filter((item) => companyIdsForBranch(form.branchId).includes(String(item.id)))
    .map((item) => ({
      value: String(item.id),
      label: item.nama || item.nama_perusahaan || `Perusahaan ${item.id}`
    }))
);

const tableRows = computed(() =>
  ledgerRows.value.map((item, index) => ({
    ...item,
    row_key: `${item.isParent ? 'parent' : 'child'}-${item.coa_id || item.id_jurnal || index}`,
    tanggal_label: item.tanggal || '-',
    akun_label: item.isParent ? `${item.nomor_akun || ''} ${item.nama_akun || ''}`.trim() : item.nama_akun || '-',
    keterangan_label: item.keterangan || '-',
    debit_label: item.isParent ? '' : formatCurrency(item.debit),
    kredit_label: item.isParent ? '' : formatCurrency(item.kredit),
    saldo_label: item.isParent ? '' : formatCurrency(item.saldo_kumulatif),
    modul_label: item.isParent ? '' : (item.modul || '-')
  }))
);

const netMovement = computed(() => Number(summary.value.total_debet || 0) - Number(summary.value.total_kredit || 0));
const filterLabel = computed(() => {
  const branch = branchOptions.value.find((item) => String(item.value) === String(form.branchId))?.label || 'Semua cabang';
  const company = companyOptions.value.find((item) => String(item.value) === String(form.companyId))?.label || 'Semua perusahaan';
  const account = coaOptions.value.find((item) => String(item.value) === String(form.coaId))?.label || 'Semua akun';
  return `${account} / ${branch} / ${company}`;
});

function formatCurrency(value) {
  return `Rp ${new Intl.NumberFormat('id-ID').format(Number(value || 0))}`;
}

function resetFilters() {
  form.coaId = '';
  form.branchId = shouldLockBusinessScope.value && fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  form.companyId = '';
  form.from = defaultFrom;
  form.to = defaultTo;
  loadLedger();
}

async function loadOptions() {
  loading.options = true;
  try {
    const [coaResponse, companyResponse, branchResponse] = await Promise.all([
      getAccountCoaList(),
      getCompanies(),
      getBranches()
    ]);

    coaRows.value = normalizeList(unwrapResponse(coaResponse));
    companyRows.value = normalizeList(unwrapResponse(companyResponse));
    branchRows.value = normalizeList(unwrapResponse(branchResponse));
    if (shouldLockBusinessScope.value && fallbackBranchId.value) {
      form.branchId = String(fallbackBranchId.value);
    }
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Referensi akun dan cabang belum bisa dimuat.');
  } finally {
    loading.options = false;
  }
}

async function loadLedger() {
  loading.ledger = true;
  feedback.value = '';
  errorMessage.value = '';

  try {
    const response = await getGeneralLedger({
      id_coa: form.coaId || undefined,
      id_cabang: form.branchId || undefined,
      id_perusahaan: form.companyId || undefined,
      periode_awal: form.from,
      periode_akhir: form.to
    });
    const rawPayload = response?.data || {};
    const payload =
      rawPayload?.data && typeof rawPayload.data === 'object'
        ? rawPayload.data
        : rawPayload;

    ledgerRows.value = normalizeList(payload?.result ?? payload);
    summary.value = {
      saldo_awal: Number(payload?.summary?.saldo_awal || 0),
      total_debet: Number(payload?.summary?.total_debet || 0),
      total_kredit: Number(payload?.summary?.total_kredit || 0),
      saldo_akhir: Number(payload?.summary?.saldo_akhir || 0)
    };

    if (!ledgerRows.value.length) {
      feedback.value = 'Belum ada data buku besar untuk filter yang dipilih.';
    }
  } catch (error) {
    ledgerRows.value = [];
    summary.value = {
      saldo_awal: 0,
      total_debet: 0,
      total_kredit: 0,
      saldo_akhir: 0
    };
    errorMessage.value = normalizeError(error, 'Buku besar belum bisa dimuat.');
  } finally {
    loading.ledger = false;
  }
}

onMounted(async () => {
  await loadOptions();
  await loadLedger();
});

watch(
  () => form.companyId,
  (value) => {
    if (value && form.branchId && !companyIdsForBranch(form.branchId).includes(String(value))) {
      form.companyId = '';
    }
  }
);

watch(
  () => form.branchId,
  (branchId, previousBranchId) => {
    if (String(branchId || '') === String(previousBranchId || '')) return;
    form.companyId = '';
  }
);
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Buku Besar"
      description="Pantau saldo awal, mutasi debit kredit, dan detail buku besar per akun dalam rentang periode yang dipilih."
    />

    <section class="panel p-5">
      <div class="grid gap-4 xl:grid-cols-[1.4fr_1.1fr_1.1fr_0.9fr_0.9fr_auto_auto]">
        <AppSearchSelect
          v-model="form.coaId"
          label="Akun COA"
          placeholder="Pilih akun"
          :options="coaOptions"
          empty-text="Daftar akun belum tersedia."
        />
        <AppSearchSelect
          v-model="form.branchId"
          label="Cabang"
          placeholder="Pilih cabang"
          :options="branchOptions"
          :disabled="shouldLockBusinessScope && !!fallbackBranchId"
          empty-text="Daftar cabang belum tersedia."
        />
        <AppSearchSelect
          v-model="form.companyId"
          label="Perusahaan"
          placeholder="Pilih perusahaan"
          :options="companyOptions"
          :disabled="!form.branchId"
          empty-text="Pilih cabang terlebih dahulu."
        />
        <div>
          <label class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Periode Awal</label>
          <input v-model="form.from" type="date" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
        </div>
        <div>
          <label class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Periode Akhir</label>
          <input v-model="form.to" type="date" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
        </div>
        <button class="self-end rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200" :disabled="loading.ledger" @click="resetFilters">
          Reset
        </button>
        <button class="self-end rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white disabled:opacity-60" :disabled="loading.ledger" @click="loadLedger">
          {{ loading.ledger ? 'Memuat...' : 'Muat Buku Besar' }}
        </button>
      </div>
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Jumlah Baris</p>
        <p class="mt-3 text-lg font-semibold text-slate-900 dark:text-white">{{ tableRows.filter((row) => !row.isParent).length }}</p>
        <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">Transaksi child</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Saldo Awal</p>
        <p class="mt-3 text-lg font-semibold text-slate-900 dark:text-white">{{ formatCurrency(summary.saldo_awal) }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Total Debit</p>
        <p class="mt-3 text-lg font-semibold text-emerald-700">{{ formatCurrency(summary.total_debet) }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Total Kredit</p>
        <p class="mt-3 text-lg font-semibold text-rose-700">{{ formatCurrency(summary.total_kredit) }}</p>
      </article>
      <article class="panel border-brand-200 bg-brand-50 p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-brand-700">Mutasi Bersih</p>
        <p class="mt-3 text-lg font-semibold text-brand-900">{{ formatCurrency(netMovement) }}</p>
        <p class="mt-1 text-xs text-brand-700">Saldo akhir {{ formatCurrency(summary.saldo_akhir) }}</p>
      </article>
    </section>

    <section v-if="feedback" class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
      {{ feedback }}
    </section>
    <section v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ errorMessage }}
    </section>

    <section class="panel overflow-hidden">
      <div class="border-b border-slate-100 px-5 py-4">
        <h3 class="text-lg font-semibold text-slate-900 dark:text-white">Detail Transaksi Buku Besar</h3>
        <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">{{ filterLabel }} / {{ form.from }} sampai {{ form.to }}</p>
      </div>

      <div class="overflow-x-auto">
        <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
          <thead class="bg-slate-50 dark:bg-slate-900">
            <tr>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Tanggal</th>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Akun</th>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Keterangan</th>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Modul</th>
              <th class="px-4 py-3 text-right font-medium uppercase tracking-wide text-slate-500">Debit</th>
              <th class="px-4 py-3 text-right font-medium uppercase tracking-wide text-slate-500">Kredit</th>
              <th class="px-4 py-3 text-right font-medium uppercase tracking-wide text-slate-500">Saldo Kumulatif</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 bg-white dark:divide-slate-800 dark:bg-slate-950">
            <tr v-if="loading.ledger">
              <td colspan="7" class="px-4 py-10 text-center text-slate-500">
                Memuat data buku besar...
              </td>
            </tr>
            <tr v-else-if="!tableRows.length">
              <td colspan="7" class="px-4 py-10 text-center text-slate-500">
                Belum ada detail buku besar untuk filter yang dipilih.
              </td>
            </tr>
            <tr
              v-for="row in tableRows"
              v-else
              :key="row.row_key"
              :class="row.isParent ? 'bg-slate-100 font-semibold text-slate-900 dark:bg-slate-900 dark:text-white' : 'text-slate-700 dark:text-slate-200'"
            >
              <td class="px-4 py-3 align-top">{{ row.isParent ? '' : row.tanggal_label }}</td>
              <td class="px-4 py-3 align-top">
                <span v-if="row.isParent">{{ row.akun_label }}</span>
                <span v-else class="pl-4">{{ row.akun_label }}</span>
              </td>
              <td class="px-4 py-3 align-top">{{ row.isParent ? '' : row.keterangan_label }}</td>
              <td class="px-4 py-3 align-top">{{ row.isParent ? '' : row.modul_label }}</td>
              <td class="px-4 py-3 text-right align-top">{{ row.debit_label }}</td>
              <td class="px-4 py-3 text-right align-top">{{ row.kredit_label }}</td>
              <td class="px-4 py-3 text-right align-top">{{ row.saldo_label }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
