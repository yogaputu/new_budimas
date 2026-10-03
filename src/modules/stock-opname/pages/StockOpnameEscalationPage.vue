<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import { closeEscalatedStockOpname, getStockOpnameDetail, getStockOpnameList } from '@/api/stockOpname';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { exportRowsToCsv } from '@/utils/exportCsv';
import { toLocalDateInputValue } from '@/utils/date';
import { useAuthStore } from '@/stores/auth';
import { getLoginBranchId, getLoginCompanyId, getRowBranchIds, getRowCompanyId, isSuperUser } from '@/utils/accessScope';
import { getBranchOptionsForCompany, getCompanyOptionsForScope } from '@/utils/filterScope';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import { buildStockOpnameDetailPayload, normalizeStockOpnameDetail, updateStockOpnameDetail } from '../detailQuantities';

const auth = useAuthStore();
const filters = reactive({
  branchId: '',
  companyId: '',
  principalId: '',
  date: '',
  search: ''
});

const branchRows = ref([]);
const companyRows = ref([]);
const principalRows = ref([]);
const escalationRows = ref([]);
const selectedRow = ref(null);
const detailRows = ref([]);
const loading = ref(false);
const detailLoading = ref(false);
const actionLoading = ref(false);
const feedback = ref('');
const errorMessage = ref('');
const detailModalOpen = ref(false);

const fallbackBranchId = computed(() => getLoginBranchId(auth.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(auth.user));
const canAccessAllBranches = computed(() => isSuperUser(auth));
const canUseLoginScope = computed(() => !canAccessAllBranches.value);

function normalizeStockOpnameRows(payload) {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.pages?.result)) return payload.pages.result;
  if (Array.isArray(payload?.data?.pages?.result)) return payload.data.pages.result;
  if (Array.isArray(payload?.result)) return payload.result;
  if (Array.isArray(payload?.data)) return payload.data;
  return [];
}

function companyIdsForBranch(branchId) {
  if (!branchId) return [];
  const ids = new Set();
  const branch = branchRows.value.find((item) => String(item.id) === String(branchId));
  const directCompanyId = getRowCompanyId(branch);
  if (directCompanyId) ids.add(String(directCompanyId));

  companyRows.value.forEach((item) => {
    if (getRowBranchIds(item).includes(String(branchId))) {
      ids.add(String(item.id));
    }
  });

  return Array.from(ids);
}

const branchOptions = computed(() =>
  getBranchOptionsForCompany(branchRows.value, auth, filters.companyId)
);

const companyOptions = computed(() => getCompanyOptionsForScope(companyRows.value, auth));

const principalOptions = computed(() =>
  principalRows.value
    .filter((item) => filters.companyId && String(item.id_perusahaan || item.company_id || '') === String(filters.companyId))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || '-'} - ${item.nama || 'Principal'}`
    }))
);

const filteredEscalations = computed(() => {
  const query = filters.search.trim().toLowerCase();
  return escalationRows.value.filter((item) => {
    const matchSearch =
      !query ||
      [item.kode_so, item.nama_principal, item.nama_cabang, item.ket_so, item.status_so]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query));
    return matchSearch;
  });
});

const selectedSummary = computed(() => {
  const detail = detailRows.value[0] || {};
  const row = selectedRow.value || {};
  return {
    kode: row.kode_so || detail.kode_so || '-',
    tanggal: row.tanggal_so || detail.tanggal_so || '-',
    cabang: row.nama_cabang || detail.nama_cabang || '-',
    perusahaan: row.nama_perusahaan || detail.nama_perusahaan || '-',
    principal: row.nama_principal || detail.nama_principal || '-',
    produk: detailRows.value.length,
    status: row.status_so || detail.status_so || '-',
    catatan: row.ket_so || detail.ket_so || '-'
  };
});

const totalStock = computed(() => detailRows.value.reduce((total, item) => total + Number(item.stok || 0), 0));
const totalNominal = computed(() => detailRows.value.reduce((total, item) => total + Number(item.subtotal || 0), 0));
const totalSelisih = computed(() => detailRows.value.reduce((total, item) => total + Number(item.subtotal_selisih || 0), 0));

const tableColumns = [
  { key: 'kode_so', label: 'Kode SO' },
  { key: 'tanggal_so', label: 'Tanggal' },
  { key: 'nama_cabang', label: 'Cabang' },
  { key: 'nama_perusahaan', label: 'Perusahaan' },
  { key: 'nama_principal', label: 'Principal' },
  { key: 'produk_count', label: 'Produk' },
  {
    key: 'total',
    label: 'Total',
    render: (row) => formatCurrency(row.total)
  },
  { key: 'ket_so', label: 'Keterangan' }
];

function formatCurrency(value) {
  return `Rp ${Number(value || 0).toLocaleString('id-ID')}`;
}

function numberLabel(value) {
  return Number(value || 0).toLocaleString('id-ID');
}

function syncBranchFromCompany() {
  if (!filters.companyId) {
    if (canAccessAllBranches.value) filters.branchId = '';
    filters.principalId = '';
    return;
  }

  if (filters.branchId && !companyIdsForBranch(filters.branchId).includes(String(filters.companyId))) {
    filters.branchId = '';
    filters.principalId = '';
  }
}

function syncPrincipalFromCompany() {
  if (filters.principalId && !principalOptions.value.some((item) => String(item.value) === String(filters.principalId))) {
    filters.principalId = '';
  }
}

function updateDetailRow(index, field, value) {
  const next = [...detailRows.value];
  next[index] = updateStockOpnameDetail(next[index], field, value);
  detailRows.value = next;
}

function buildDetailPayload() {
  return buildStockOpnameDetailPayload(detailRows.value);
}

async function loadMasterData() {
  const [branchResponse, companyResponse, principalResponse] = await Promise.all([getBranches(), getCompanies(), getPrincipals()]);
  branchRows.value = normalizeList(unwrapResponse(branchResponse));
  companyRows.value = normalizeList(unwrapResponse(companyResponse));
  principalRows.value = normalizeList(unwrapResponse(principalResponse));

  if (!filters.companyId && canUseLoginScope.value && fallbackCompanyId.value) {
    filters.companyId = String(fallbackCompanyId.value);
  }
  if (!canAccessAllBranches.value && fallbackBranchId.value) {
    filters.branchId = String(fallbackBranchId.value);
  }
  syncBranchFromCompany();
  syncPrincipalFromCompany();
}

async function loadEscalations() {
  loading.value = true;
  errorMessage.value = '';
  feedback.value = '';
  try {
    const response = await getStockOpnameList({
      'no-paginate': 'true',
      order: 'desc',
      field: 'tanggal_so',
      status_so: 'eskalasi',
      id_cabang: filters.branchId || (!canAccessAllBranches.value ? fallbackBranchId.value : undefined),
      id_perusahaan: filters.companyId || undefined,
      id_principal: filters.principalId || undefined,
      tanggal_so: filters.date || undefined
    });
    escalationRows.value = normalizeStockOpnameRows(unwrapResponse(response));
    if (selectedRow.value && !escalationRows.value.some((item) => String(item.id_stock_opname || item.id) === String(selectedRow.value.id_stock_opname || selectedRow.value.id))) {
      selectedRow.value = null;
      detailRows.value = [];
    }
  } catch (error) {
    errorMessage.value = normalizeError(error, 'List eskalasi belum bisa dimuat.');
  } finally {
    loading.value = false;
  }
}

async function selectRow(row) {
  selectedRow.value = row;
  detailRows.value = [];
  detailModalOpen.value = true;
  detailLoading.value = true;
  errorMessage.value = '';
  feedback.value = '';
  try {
    const response = await getStockOpnameDetail(row.id_stock_opname || row.id);
    const details = normalizeList(unwrapResponse(response));
    detailRows.value = details.map(normalizeStockOpnameDetail);
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Detail eskalasi belum bisa dimuat.');
  } finally {
    detailLoading.value = false;
  }
}

function closeDetailModal() {
  detailModalOpen.value = false;
}

function clearSelectedEscalation() {
  detailModalOpen.value = false;
  selectedRow.value = null;
  detailRows.value = [];
}

async function closeEscalation() {
  if (!selectedRow.value || !detailRows.value.length) {
    errorMessage.value = 'Pilih eskalasi stok opname terlebih dahulu.';
    return;
  }

  const approved = window.confirm(`Tutup eskalasi ${selectedSummary.value.kode}? Perubahan stock akan disimpan.`);
  if (!approved) return;

  actionLoading.value = true;
  errorMessage.value = '';
  feedback.value = '';
  try {
    await closeEscalatedStockOpname({
      id_stock_opname: selectedRow.value.id_stock_opname || selectedRow.value.id,
      id_user: auth.user?.id,
      id_cabang: selectedRow.value.id_cabang || auth.user?.id_cabang,
      id_perusahaan: selectedRow.value.id_perusahaan || auth.user?.id_perusahaan,
      total: totalNominal.value,
      total_selisih: totalSelisih.value,
      data_produks: buildDetailPayload()
    });
    feedback.value = `Eskalasi ${selectedSummary.value.kode} berhasil ditutup.`;
    selectedRow.value = null;
    detailRows.value = [];
    detailModalOpen.value = false;
    await loadEscalations();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Close eskalasi gagal.');
  } finally {
    actionLoading.value = false;
  }
}

function resetFilters() {
  filters.companyId = canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
  filters.branchId = !canAccessAllBranches.value && fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  filters.principalId = '';
  filters.date = '';
  filters.search = '';
  syncBranchFromCompany();
  loadEscalations();
}

function exportEscalations() {
  exportRowsToCsv(
    `eskalasi-stock-opname-${toLocalDateInputValue()}.csv`,
    [
      { label: 'Kode SO', key: 'kode_so' },
      { label: 'Tanggal', key: 'tanggal_so' },
      { label: 'Cabang', key: 'nama_cabang' },
      { label: 'Perusahaan', key: 'nama_perusahaan' },
      { label: 'Principal', key: 'nama_principal' },
      { label: 'Produk', key: 'produk_count' },
      { label: 'Total', key: 'total' },
      { label: 'Keterangan', key: 'ket_so' },
      { label: 'Status', key: 'status_so' }
    ],
    filteredEscalations.value
  );
}

watch(
  () => filters.companyId,
  (companyId, previousCompanyId) => {
    if (String(companyId || '') === String(previousCompanyId || '')) return;
    syncBranchFromCompany();
    syncPrincipalFromCompany();
  }
);

watch(
  () => filters.branchId,
  () => {
    syncPrincipalFromCompany();
  }
);

onMounted(async () => {
  await loadMasterData();
  await loadEscalations();
});
</script>

<template>
  <div class="space-y-5">
    <PageHeader
      title="Eskalasi Stok Opname"
      description="List eskalasi dan close eskalasi dengan pola lama: pilih data, koreksi UOM, lalu tutup eskalasi."
    />

    <section class="panel p-4">
      <div class="grid gap-4 lg:grid-cols-5">
        <AppSearchSelect v-model="filters.companyId" label="Perusahaan" placeholder="Pilih perusahaan" :options="companyOptions" :disabled="canUseLoginScope && !!fallbackCompanyId" empty-text="Perusahaan belum tersedia." />
        <AppSearchSelect v-model="filters.branchId" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="!filters.companyId || (!canAccessAllBranches && !!fallbackBranchId)" empty-text="Pilih perusahaan terlebih dahulu." />
        <AppSearchSelect v-model="filters.principalId" label="Principal" :placeholder="filters.companyId ? 'Semua principal' : 'Pilih perusahaan dulu'" :options="principalOptions" :disabled="!filters.companyId" />
        <label class="block">
          <span class="mb-1 block text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Tanggal</span>
          <input v-model="filters.date" type="date" class="input" />
        </label>
        <label class="block">
          <span class="mb-1 block text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Cari</span>
          <input v-model="filters.search" class="input" placeholder="Kode SO, principal, catatan" />
        </label>
      </div>
      <div class="mt-4 flex flex-wrap gap-2">
        <button class="btn-primary" type="button" :disabled="loading" @click="loadEscalations">{{ loading ? 'Memuat...' : 'Cari Data' }}</button>
        <button class="btn-secondary" type="button" @click="resetFilters">Reset</button>
        <button class="btn-secondary" type="button" :disabled="!filteredEscalations.length" @click="exportEscalations">Export CSV</button>
      </div>
      <p v-if="feedback" class="mt-3 text-sm text-emerald-300">{{ feedback }}</p>
      <p v-if="errorMessage" class="mt-3 text-sm text-rose-300">{{ errorMessage }}</p>
    </section>

    <section class="space-y-3">
      <div>
        <h2 class="text-xl font-black text-white">List Eskalasi Stok Opname</h2>
        <p class="text-sm text-slate-400">Tampil {{ filteredEscalations.length.toLocaleString('id-ID') }} data eskalasi. Klik baris untuk membuka detail.</p>
      </div>
      <AppTable
        :rows="filteredEscalations"
        :columns="tableColumns"
        :loading="loading"
        row-key="id_stock_opname"
        clickable-rows
        :selected-key="selectedRow?.id_stock_opname || selectedRow?.id || ''"
        empty-message="Belum ada stok opname dengan status eskalasi."
        @row-click="selectRow"
      />
    </section>

    <AppModal
      :open="detailModalOpen"
      title="Detail Eskalasi Stok Opname"
      description="Koreksi qty UOM lalu tutup eskalasi jika data sudah final."
      size="7xl"
      @close="closeDetailModal"
    >
      <div v-if="!selectedRow" class="rounded-2xl border border-slate-800 bg-slate-950 p-4 text-sm text-slate-400">
        Pilih baris eskalasi untuk menampilkan detail produk.
      </div>

      <div v-else class="space-y-4">
          <div class="grid gap-3 md:grid-cols-2">
            <div class="rounded-2xl border border-slate-800 bg-slate-950 p-3">
              <p class="text-xs uppercase tracking-[0.28em] text-slate-500">Kode SO</p>
              <p class="mt-2 font-bold text-white">{{ selectedSummary.kode }}</p>
            </div>
            <div class="rounded-2xl border border-slate-800 bg-slate-950 p-3">
              <p class="text-xs uppercase tracking-[0.28em] text-slate-500">Tanggal</p>
              <p class="mt-2 font-bold text-white">{{ selectedSummary.tanggal }}</p>
            </div>
            <div class="rounded-2xl border border-slate-800 bg-slate-950 p-3">
              <p class="text-xs uppercase tracking-[0.28em] text-slate-500">Principal</p>
              <p class="mt-2 font-bold text-white">{{ selectedSummary.principal }}</p>
            </div>
            <div class="rounded-2xl border border-slate-800 bg-slate-950 p-3">
              <p class="text-xs uppercase tracking-[0.28em] text-slate-500">Status</p>
              <p class="mt-2 font-bold text-amber-200">{{ selectedSummary.status }}</p>
            </div>
          </div>

          <div class="grid gap-3 md:grid-cols-3">
            <div class="rounded-2xl border border-slate-800 bg-slate-950 p-3">
              <p class="text-xs uppercase tracking-[0.28em] text-slate-500">Total Stock</p>
              <p class="mt-2 text-xl font-black text-white">{{ numberLabel(totalStock) }}</p>
            </div>
            <div class="rounded-2xl border border-slate-800 bg-slate-950 p-3">
              <p class="text-xs uppercase tracking-[0.28em] text-slate-500">Total</p>
              <p class="mt-2 text-xl font-black text-emerald-300">{{ formatCurrency(totalNominal) }}</p>
            </div>
            <div class="rounded-2xl border border-slate-800 bg-slate-950 p-3">
              <p class="text-xs uppercase tracking-[0.28em] text-slate-500">Total Selisih</p>
              <p class="mt-2 text-xl font-black text-amber-300">{{ formatCurrency(totalSelisih) }}</p>
            </div>
          </div>

          <div class="overflow-x-auto rounded-2xl border border-slate-800">
            <table class="min-w-full divide-y divide-slate-800 text-sm">
              <thead class="bg-slate-900 text-slate-400">
                <tr>
                  <th class="px-3 py-3 text-left uppercase tracking-wide">Produk</th>
                  <th class="px-3 py-3 text-left uppercase tracking-wide">UOM 3</th>
                  <th class="px-3 py-3 text-left uppercase tracking-wide">UOM 2</th>
                  <th class="px-3 py-3 text-left uppercase tracking-wide">UOM 1</th>
                  <th class="px-3 py-3 text-right uppercase tracking-wide">Stock</th>
                  <th class="px-3 py-3 text-right uppercase tracking-wide">Good</th>
                  <th class="px-3 py-3 text-right uppercase tracking-wide">Bad</th>
                  <th class="px-3 py-3 text-right uppercase tracking-wide">System</th>
                  <th class="px-3 py-3 text-right uppercase tracking-wide">Selisih</th>
                  <th class="px-3 py-3 text-right uppercase tracking-wide">Subtotal Selisih</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-800 bg-slate-950">
                <tr v-if="detailLoading">
                  <td colspan="10" class="px-3 py-8 text-center text-slate-400">Memuat detail...</td>
                </tr>
                <tr v-else-if="!detailRows.length">
                  <td colspan="10" class="px-3 py-8 text-center text-slate-400">Detail produk belum tersedia.</td>
                </tr>
                <tr v-for="(item, index) in detailRows" v-else :key="`${item.id_produk}-${index}`">
                  <td class="px-3 py-3">
                    <p class="font-bold text-white">{{ item.nama_produk || '-' }}</p>
                    <p class="text-xs text-slate-400">{{ item.kode_sku || item.sku || '-' }}</p>
                  </td>
                  <td class="px-3 py-3">
                    <input :value="item.uom_3" :disabled="!item.konversi_uom_3" type="number" min="0" class="input w-24" @input="updateDetailRow(index, 'uom_3', $event.target.value)" />
                    <p class="mt-1 text-xs text-slate-500">{{ item.label_uom_3 || '-' }}</p>
                  </td>
                  <td class="px-3 py-3">
                    <input :value="item.uom_2" :disabled="!item.konversi_uom_2" type="number" min="0" class="input w-24" @input="updateDetailRow(index, 'uom_2', $event.target.value)" />
                    <p class="mt-1 text-xs text-slate-500">{{ item.label_uom_2 || '-' }}</p>
                  </td>
                  <td class="px-3 py-3">
                    <input :value="item.uom_1" :disabled="!item.konversi_uom_1" type="number" min="0" class="input w-24" @input="updateDetailRow(index, 'uom_1', $event.target.value)" />
                    <p class="mt-1 text-xs text-slate-500">{{ item.label_uom_1 || '-' }}</p>
                  </td>
                  <td class="px-3 py-3 text-right text-white">{{ numberLabel(item.stok) }}</td>
                  <td class="px-3 py-3 text-right text-emerald-300">{{ numberLabel(item.good_stock) }}</td>
                  <td class="px-3 py-3 text-right text-rose-300">{{ numberLabel(item.bad_stock) }}</td>
                  <td class="px-3 py-3 text-right text-slate-300">{{ numberLabel(item.stok_sistem) }}</td>
                  <td :class="['px-3 py-3 text-right font-bold', Number(item.selisih || 0) < 0 ? 'text-rose-300' : 'text-emerald-300']">{{ numberLabel(item.selisih) }}</td>
                  <td class="px-3 py-3 text-right text-slate-200">{{ formatCurrency(item.subtotal_selisih) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
      </div>

      <template #footer>
        <div class="flex flex-wrap justify-end gap-2">
          <button class="btn-secondary" type="button" @click="clearSelectedEscalation">Batal Pilih</button>
          <button class="btn-primary" type="button" :disabled="actionLoading || detailLoading || !detailRows.length" @click="closeEscalation">
            {{ actionLoading ? 'Menyimpan...' : 'Close Eskalasi' }}
          </button>
        </div>
      </template>
    </AppModal>
  </div>
</template>
