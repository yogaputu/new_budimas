<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import { resubmitPromoClaim, getPromoClaimDetail, getPromoClaimDropdownData, getPromoClaims, updatePromoClaimStatus } from '@/api/promo';
import { useAuthStore } from '@/app/stores/auth';
import {
  canAccessAllPromoBranches,
  getPromoBranchOptions,
  getPromoCompanyOptions,
  getPromoFallbackBranchId,
  getPromoPrincipalOptions
} from '@/modules/promo/utils/promoScope';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { toLocalDateInputValue } from '@/utils/date';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import { canAccessRoleGroups } from '@/utils/roleAccess';

const auth = useAuthStore();

const filters = reactive({
  id_cabang: '',
  id_perusahaan: '',
  id_principal: '',
  status_klaim: '',
  filters: ''
});

const dropdownData = ref({ principal: [], status_klaim: [] });
const branches = ref([]);
const companies = ref([]);
const principals = ref([]);
const rows = ref([]);
const detail = ref(null);
const loading = ref(false);
const detailLoading = ref(false);
const actionLoading = ref(false);
const error = ref('');
const feedback = ref('');
const selectedRow = ref(null);
const detailModalOpen = ref(false);

const canAccessAllBranches = computed(() => canAccessAllPromoBranches(auth));
const branchOptions = computed(() => getPromoBranchOptions(branches.value, auth));
const companyOptions = computed(() => getPromoCompanyOptions(companies.value, branches.value, filters.id_cabang));
const principalOptions = computed(() => getPromoPrincipalOptions(principals.value, filters.id_perusahaan));

const filterFields = computed(() => [
  { key: 'id_cabang', label: 'Cabang', type: 'search-select', options: branchOptions.value, disabled: !canAccessAllBranches.value },
  { key: 'id_perusahaan', label: 'Perusahaan', type: 'search-select', options: companyOptions.value, disabled: !filters.id_cabang },
  {
    key: 'id_principal',
    label: 'Principal',
    type: 'search-select',
    options: principalOptions.value,
    disabled: !filters.id_perusahaan
  },
  {
    key: 'status_klaim',
    label: 'Status Klaim',
    type: 'search-select',
    options: normalizeList(dropdownData.value.status_klaim).map((item) => ({
      value: String(item.id),
      label: item.nama || `Status ${item.id}`
    }))
  },
  { key: 'filters', label: 'Cari', placeholder: 'Nomor klaim, kode promo, principal' }
]);

const summary = computed(() => ({
  total: rows.value.length,
  draft: rows.value.filter((row) => String(row.status_klaim || '').toLowerCase() === 'draft').length,
  submitted: rows.value.filter((row) => String(row.status_klaim || '').toLowerCase() === 'pengajuan klaim').length,
  approved: rows.value.filter((row) => String(row.status_klaim || '').toLowerCase() === 'klaim disetujui').length,
  rejected: rows.value.filter((row) => String(row.status_klaim || '').toLowerCase() === 'klaim ditolak').length
}));

const selectedKey = computed(() => selectedRow.value?.id || '');

const isSupervisorOrAdmin = computed(() => canAccessRoleGroups(auth, ['salesSupervisor']));

const detailStatusText = computed(() => String(detail.value?.status_klaim || selectedRow.value?.status_klaim || '').trim().toLowerCase());
const canResubmitSelectedClaim = computed(() => detailStatusText.value === 'klaim ditolak' && !actionLoading.value);
const canReviewSelectedClaim = computed(() => isSupervisorOrAdmin.value && detailStatusText.value === 'pengajuan klaim' && !actionLoading.value);

const tableColumns = [
  { key: 'nomor_klaim', label: 'Nomor Klaim' },
  { key: 'kode_promo', label: 'Kode Promo' },
  { key: 'nama_promo', label: 'Nama Promo' },
  { key: 'principal', label: 'Principal' },
  {
    key: 'nominal_klaim',
    label: 'Nominal Klaim',
    render: (row) => `Rp ${Number(row.nominal_klaim || 0).toLocaleString('id-ID')}`
  },
  { key: 'status_klaim', label: 'Status' }
];

async function loadDropdowns() {
  const [dropdownResponse, branchResponse, companyResponse, principalResponse] = await Promise.all([
    getPromoClaimDropdownData(),
    getBranches(),
    getCompanies(),
    getPrincipals()
  ]);
  dropdownData.value = unwrapResponse(dropdownResponse) || {};
  branches.value = normalizeList(unwrapResponse(branchResponse));
  companies.value = normalizeList(unwrapResponse(companyResponse));
  principals.value = normalizeList(unwrapResponse(principalResponse));
  applyLoginBranchScope();
}

async function loadClaims(preserveId = null) {
  loading.value = true;
  error.value = '';

  try {
    const response = await getPromoClaims({
      ...filters,
      page: 0,
      limit: 100,
      'no-paginate': 'true'
    });
    const payload = unwrapResponse(response) || {};
    rows.value = normalizeList(payload.pages || payload);
    const targetId = preserveId || selectedRow.value?.id;
    selectedRow.value = targetId ? rows.value.find((row) => String(row.id) === String(targetId)) || null : null;
    feedback.value = `Daftar klaim promo memuat ${rows.value.length} data.`;
  } catch (err) {
    error.value = normalizeError(err, 'Daftar klaim promo belum bisa dimuat.');
    rows.value = [];
    selectedRow.value = null;
  } finally {
    loading.value = false;
  }
}

async function loadClaimDetail(row = selectedRow.value) {
  if (!row?.id) return;
  selectedRow.value = row;
  detailModalOpen.value = true;
  detailLoading.value = true;
  error.value = '';

  try {
    const response = await getPromoClaimDetail(row.id);
    detail.value = unwrapResponse(response) || null;
  } catch (err) {
    error.value = normalizeError(err, 'Detail klaim promo belum bisa dimuat.');
    detail.value = null;
  } finally {
    detailLoading.value = false;
  }
}

function closeDetailModal() {
  detailModalOpen.value = false;
}

async function applyClaimAction(actionType) {
  if (!selectedRow.value?.id) {
    return;
  }

  actionLoading.value = true;
  error.value = '';
  feedback.value = '';

  try {
    if (actionType === 'resubmit') {
      await resubmitPromoClaim({
        klaim_id: Number(selectedRow.value.id),
        total_dpp: Number(detail.value?.total_dpp || 0),
        total_ppn: Number(detail.value?.total_ppn || 0),
        total_pph: Number(detail.value?.total_pph || 0),
        id_kategori_klaim: detail.value?.id_kategori_klaim || null,
        total_klaim_diajukan: Number(detail.value?.total_klaim_diajukan || 0),
        tanggal_pengajuan_klaim: toLocalDateInputValue()
      });
      feedback.value = `Klaim ${detail.value?.nomor_klaim || selectedRow.value.id} berhasil diajukan ulang.`;
    }

    if (actionType === 'approve') {
      await updatePromoClaimStatus(selectedRow.value.id, {
        status_klaim: 2
      });
      feedback.value = `Klaim ${detail.value?.nomor_klaim || selectedRow.value.id} berhasil disetujui.`;
    }

    if (actionType === 'reject') {
      await updatePromoClaimStatus(selectedRow.value.id, {
        status_klaim: 3
      });
      feedback.value = `Klaim ${detail.value?.nomor_klaim || selectedRow.value.id} berhasil ditolak.`;
    }

    await loadClaims(selectedRow.value.id);
    if (selectedRow.value?.id) {
      await loadClaimDetail(selectedRow.value);
    }
  } catch (err) {
    error.value = normalizeError(err, 'Aksi klaim promo belum berhasil diproses.');
  } finally {
    actionLoading.value = false;
  }
}

async function resubmitSelectedClaim() {
  const confirmed = window.confirm('Ajukan ulang klaim promo yang ditolak ini dengan data klaim terakhir?');
  if (!confirmed) return;
  await applyClaimAction('resubmit');
}

async function approveSelectedClaim() {
  const confirmed = window.confirm('Setujui klaim promo yang sedang dipilih?');
  if (!confirmed) return;
  await applyClaimAction('approve');
}

async function rejectSelectedClaim() {
  const confirmed = window.confirm('Tolak klaim promo yang sedang dipilih?');
  if (!confirmed) return;
  await applyClaimAction('reject');
}

function resetFilters() {
  filters.id_cabang = canAccessAllBranches.value ? '' : getPromoFallbackBranchId(auth) || '';
  filters.id_perusahaan = '';
  filters.id_principal = '';
  filters.status_klaim = '';
  filters.filters = '';
  loadClaims();
}

function applyLoginBranchScope() {
  const fallbackBranch = getPromoFallbackBranchId(auth);
  if (!canAccessAllBranches.value && fallbackBranch) {
    filters.id_cabang = String(fallbackBranch);
  }
}

function updateFilters(nextFilters) {
  const previousBranch = filters.id_cabang;
  const previousCompany = filters.id_perusahaan;
  Object.assign(filters, nextFilters || {});
  if (String(previousBranch || '') !== String(filters.id_cabang || '')) {
    filters.id_perusahaan = '';
    filters.id_principal = '';
    return;
  }
  if (String(previousCompany || '') !== String(filters.id_perusahaan || '')) {
    filters.id_principal = '';
  }
}

onMounted(async () => {
  try {
    await loadDropdowns();
  } catch (err) {
    error.value = normalizeError(err, 'Filter klaim promo belum bisa dimuat.');
  }

  await loadClaims();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Daftar Klaim Promo"
      description="User bisa memantau semua klaim promo yang pernah diajukan, membaca status prosesnya, dan membuka detail klaim yang sedang berjalan."
    />

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Total Klaim</p>
        <p class="mt-3 text-2xl font-semibold text-slate-900">{{ summary.total.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Draft</p>
        <p class="mt-3 text-2xl font-semibold text-slate-500">{{ summary.draft.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Pengajuan</p>
        <p class="mt-3 text-2xl font-semibold text-brand-700">{{ summary.submitted.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Disetujui</p>
        <p class="mt-3 text-2xl font-semibold text-emerald-600">{{ summary.approved.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Ditolak</p>
        <p class="mt-3 text-2xl font-semibold text-rose-600">{{ summary.rejected.toLocaleString('id-ID') }}</p>
      </article>
    </section>

    <AppFilterBar :model-value="filters" :fields="filterFields" @update:model-value="updateFilters" @submit="loadClaims" @reset="resetFilters" />

    <section v-if="feedback" class="rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-700">
      {{ feedback }}
    </section>

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ error }}
    </section>

    <section class="panel p-5">
      <div class="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 class="text-lg font-semibold text-slate-900">List Klaim Promo</h3>
          <p class="mt-1 text-sm text-slate-500">Klik salah satu klaim untuk membuka detail dan ringkasan pengajuan dalam modal.</p>
        </div>
        <p v-if="selectedRow" class="rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-700">
          Terpilih: {{ selectedRow.nomor_klaim || selectedRow.id }}
        </p>
      </div>

      <AppTable
        :columns="tableColumns"
        :rows="rows"
        :loading="loading"
        row-key="id"
        :selected-key="selectedKey"
        :clickable-rows="true"
        empty-message="Belum ada data klaim promo untuk filter yang dipilih."
        @row-click="loadClaimDetail"
      />
    </section>

    <AppModal :open="detailModalOpen" title="Detail Klaim Promo" size="xl" @close="closeDetailModal">
      <div v-if="selectedRow" class="space-y-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p class="text-sm text-slate-500">Ringkasan klaim yang dipilih untuk pengecekan cepat.</p>
            <p class="mt-2 text-xl font-semibold text-slate-900">{{ selectedRow.nomor_klaim || 'Klaim terpilih' }}</p>
          </div>

          <div class="flex flex-wrap gap-2">
            <button
              v-if="canResubmitSelectedClaim"
              class="rounded-xl border border-amber-200 bg-amber-50 px-4 py-2 text-sm font-medium text-amber-700 hover:bg-amber-100 disabled:opacity-60"
              :disabled="actionLoading"
              @click="resubmitSelectedClaim"
            >
              {{ actionLoading ? 'Memproses...' : 'Ajukan Ulang' }}
            </button>
            <button
              v-if="canReviewSelectedClaim"
              class="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-60"
              :disabled="actionLoading"
              @click="approveSelectedClaim"
            >
              {{ actionLoading ? 'Memproses...' : 'Setujui' }}
            </button>
            <button
              v-if="canReviewSelectedClaim"
              class="rounded-xl border border-rose-200 bg-rose-50 px-4 py-2 text-sm font-medium text-rose-700 hover:bg-rose-100 disabled:opacity-60"
              :disabled="actionLoading"
              @click="rejectSelectedClaim"
            >
              {{ actionLoading ? 'Memproses...' : 'Tolak' }}
            </button>
          </div>
        </div>

        <div
          v-if="isSupervisorOrAdmin"
          class="rounded-2xl border border-brand-100 bg-brand-50/60 px-4 py-3 text-sm text-brand-700"
        >
          Mode reviewer aktif. Supervisor/admin bisa menyetujui atau menolak klaim yang masih berstatus pengajuan.
        </div>

        <div
          v-else-if="canResubmitSelectedClaim"
          class="rounded-2xl border border-amber-100 bg-amber-50 px-4 py-3 text-sm text-amber-700"
        >
          Klaim ini ditolak. User bisa memakai tombol <span class="font-semibold">Ajukan Ulang</span> untuk mengirim ulang klaim dengan data terakhir.
        </div>

        <p v-else class="text-sm text-slate-500">Status klaim menentukan aksi yang tersedia di modal ini.</p>

        <div v-if="detailLoading" class="py-10 text-center text-sm text-slate-500">
          Memuat detail klaim...
        </div>

        <template v-else-if="detail">
          <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-wide text-slate-400">Nomor Klaim</p>
              <p class="mt-2 font-semibold text-slate-900">{{ detail.nomor_klaim || '-' }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-wide text-slate-400">Kode Promo</p>
              <p class="mt-2 font-semibold text-slate-900">{{ detail.kode_promo || '-' }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-wide text-slate-400">Principal</p>
              <p class="mt-2 font-semibold text-slate-900">{{ detail.principal || '-' }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-wide text-slate-400">Kategori Klaim</p>
              <p class="mt-2 font-semibold text-slate-900">{{ detail.nama_kategori_klaim || '-' }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-wide text-slate-400">Total Klaim</p>
              <p class="mt-2 font-semibold text-slate-900">Rp {{ Number(detail.total_klaim_diajukan || 0).toLocaleString('id-ID') }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-wide text-slate-400">Status</p>
              <p class="mt-2 font-semibold text-slate-900">{{ detail.status_klaim || '-' }}</p>
            </article>
          </div>

          <div class="grid gap-3 md:grid-cols-3">
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-wide text-slate-400">DPP</p>
              <p class="mt-2 font-semibold text-slate-900">Rp {{ Number(detail.total_dpp || 0).toLocaleString('id-ID') }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-wide text-slate-400">PPN</p>
              <p class="mt-2 font-semibold text-slate-900">Rp {{ Number(detail.total_ppn || 0).toLocaleString('id-ID') }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-wide text-slate-400">PPH</p>
              <p class="mt-2 font-semibold text-slate-900">Rp {{ Number(detail.total_pph || 0).toLocaleString('id-ID') }}</p>
            </article>
          </div>

          <section class="rounded-2xl border border-slate-200 bg-white">
            <div class="border-b border-slate-200 px-4 py-3">
              <h4 class="text-sm font-semibold text-slate-900">Daftar Promo yang Diklaim</h4>
              <p class="mt-1 text-xs text-slate-500">Item faktur yang masuk ke klaim ini ditampilkan untuk audit pengajuan tanpa keluar dari halaman.</p>
            </div>

            <div v-if="normalizeList(detail.items).length" class="overflow-x-auto">
              <table class="min-w-full divide-y divide-slate-200 text-sm">
                <thead class="bg-slate-50 text-left text-xs uppercase tracking-[0.2em] text-slate-500">
                  <tr>
                    <th class="px-4 py-3">No Faktur</th>
                    <th class="px-4 py-3">Customer</th>
                    <th class="px-4 py-3">Kode Promo</th>
                    <th class="px-4 py-3">Estimasi Klaim</th>
                    <th class="px-4 py-3">DPP</th>
                    <th class="px-4 py-3">PPN</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-slate-100 bg-white">
                  <tr v-for="item in normalizeList(detail.items)" :key="`${detail.id}-${item.id_draft_voucher || item.id_unified_promo_usage || item.no_faktur}-${item.no_faktur}`">
                    <td class="px-4 py-3 text-slate-900">{{ item.no_faktur || '-' }}</td>
                    <td class="px-4 py-3 text-slate-700">{{ item.customer || '-' }}</td>
                    <td class="px-4 py-3 text-slate-700">{{ item.kode_promo || '-' }}</td>
                    <td class="px-4 py-3 text-slate-700">Rp {{ Number(item.estimasi_klaim || 0).toLocaleString('id-ID') }}</td>
                    <td class="px-4 py-3 text-slate-700">Rp {{ Number(item.dpp || 0).toLocaleString('id-ID') }}</td>
                    <td class="px-4 py-3 text-slate-700">Rp {{ Number(item.ppn || 0).toLocaleString('id-ID') }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div v-else class="px-4 py-6 text-sm text-slate-500">
              Belum ada item promo tercatat pada detail klaim ini.
            </div>
          </section>
        </template>
      </div>
    </AppModal>
  </div>
</template>
