<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import { getPromoClaimDetail, getPromoClaimDropdownData, getPromoClaims, updatePromoClaimStatus } from '@/api/promo';
import { useAuthStore } from '@/app/stores/auth';
import {
  canAccessAllPromoBranches,
  getPromoBranchOptions,
  getPromoCompanyOptions,
  getPromoFallbackBranchId,
  getPromoPrincipalOptions
} from '@/modules/promo/utils/promoScope';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import AppEmptyState from '@/shared/components/AppEmptyState.vue';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import { canAccessRoleGroups } from '@/utils/roleAccess';

const auth = useAuthStore();

const filters = reactive({
  id_cabang: '',
  id_perusahaan: '',
  id_principal: '',
  filters: ''
});

const tabs = [
  { key: 'all', label: 'Semua' },
  { key: 'review', label: 'Menunggu Review' },
  { key: 'rejected', label: 'Ditolak' },
  { key: 'approved', label: 'Disetujui' }
];

const activeTab = ref('review');
const dropdownData = ref({ principal: [] });
const branches = ref([]);
const companies = ref([]);
const principals = ref([]);
const allRows = ref([]);
const detail = ref(null);
const loading = ref(false);
const detailLoading = ref(false);
const actionLoading = ref(false);
const error = ref('');
const feedback = ref('');
const selectedRow = ref(null);

const isReviewer = computed(() => canAccessRoleGroups(auth, ['salesSupervisor']));

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
  { key: 'filters', label: 'Cari', placeholder: 'Nomor klaim, promo, principal' }
]);

function normalizeStatus(value) {
  return String(value || '').trim().toLowerCase();
}

const tabCounts = computed(() => ({
  all: allRows.value.length,
  review: allRows.value.filter((row) => normalizeStatus(row.status_klaim) === 'pengajuan klaim').length,
  rejected: allRows.value.filter((row) => normalizeStatus(row.status_klaim) === 'klaim ditolak').length,
  approved: allRows.value.filter((row) => normalizeStatus(row.status_klaim) === 'klaim disetujui').length
}));

const rows = computed(() => {
  if (activeTab.value === 'all') {
    return allRows.value;
  }
  if (activeTab.value === 'review') {
    return allRows.value.filter((row) => normalizeStatus(row.status_klaim) === 'pengajuan klaim');
  }
  if (activeTab.value === 'rejected') {
    return allRows.value.filter((row) => normalizeStatus(row.status_klaim) === 'klaim ditolak');
  }
  return allRows.value.filter((row) => normalizeStatus(row.status_klaim) === 'klaim disetujui');
});

const selectedKey = computed(() => selectedRow.value?.id || '');

const canApprove = computed(() =>
  isReviewer.value &&
  normalizeStatus(detail.value?.status_klaim || selectedRow.value?.status_klaim) === 'pengajuan klaim' &&
  !actionLoading.value
);

const canReject = computed(() => canApprove.value);

function statusBadgeConfig(status) {
  const normalized = normalizeStatus(status);

  if (normalized === 'pengajuan klaim') {
    return {
      text: 'Menunggu Review',
      className: 'inline-flex rounded-full bg-brand-100 px-3 py-1 text-xs font-semibold text-brand-700'
    };
  }

  if (normalized === 'klaim ditolak') {
    return {
      text: 'Ditolak',
      className: 'inline-flex rounded-full bg-rose-100 px-3 py-1 text-xs font-semibold text-rose-700'
    };
  }

  if (normalized === 'klaim disetujui') {
    return {
      text: 'Disetujui',
      className: 'inline-flex rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700'
    };
  }

  if (normalized === 'draft') {
    return {
      text: 'Draft',
      className: 'inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700'
    };
  }

  return {
    text: status || '-',
    className: 'inline-flex rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700'
  };
}

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
  {
    key: 'status_klaim',
    label: 'Status',
    render: (row) => statusBadgeConfig(row.status_klaim)
  }
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
      limit: 200,
      'no-paginate': 'true'
    });
    const payload = unwrapResponse(response) || {};
    allRows.value = normalizeList(payload.pages || payload);
    const targetId = preserveId || selectedRow.value?.id;
    selectedRow.value = targetId ? allRows.value.find((row) => String(row.id) === String(targetId)) || null : null;
    feedback.value = `Approval promo memuat ${allRows.value.length} klaim untuk ditinjau reviewer.`;
  } catch (err) {
    error.value = normalizeError(err, 'Daftar approval promo belum bisa dimuat.');
    allRows.value = [];
    selectedRow.value = null;
  } finally {
    loading.value = false;
  }
}

async function loadClaimDetail(row = selectedRow.value) {
  if (!row?.id) return;
  selectedRow.value = row;
  detailLoading.value = true;
  error.value = '';

  try {
    const response = await getPromoClaimDetail(row.id);
    detail.value = unwrapResponse(response) || null;
  } catch (err) {
    error.value = normalizeError(err, 'Detail approval promo belum bisa dimuat.');
    detail.value = null;
  } finally {
    detailLoading.value = false;
  }
}

async function applyClaimDecision(statusKlaim, successMessage) {
  if (!selectedRow.value?.id) return;

  actionLoading.value = true;
  error.value = '';
  feedback.value = '';

  try {
    await updatePromoClaimStatus(selectedRow.value.id, { status_klaim: statusKlaim });
    feedback.value = successMessage;
    await loadClaims(selectedRow.value.id);
    if (selectedRow.value?.id) {
      await loadClaimDetail(selectedRow.value);
    }
  } catch (err) {
    error.value = normalizeError(err, 'Keputusan approval promo belum berhasil diproses.');
  } finally {
    actionLoading.value = false;
  }
}

async function approveSelectedClaim() {
  const confirmed = window.confirm('Setujui klaim promo yang sedang dipilih?');
  if (!confirmed) return;
  await applyClaimDecision(2, `Klaim ${detail.value?.nomor_klaim || selectedRow.value.id} berhasil disetujui.`);
}

async function rejectSelectedClaim() {
  const confirmed = window.confirm('Tolak klaim promo yang sedang dipilih?');
  if (!confirmed) return;
  await applyClaimDecision(3, `Klaim ${detail.value?.nomor_klaim || selectedRow.value.id} berhasil ditolak.`);
}

function selectTab(tabKey) {
  activeTab.value = tabKey;
  const currentId = selectedRow.value?.id;
  selectedRow.value = currentId ? rows.value.find((row) => String(row.id) === String(currentId)) || null : null;
  if (!selectedRow.value) {
    detail.value = null;
  }
}

function resetFilters() {
  filters.id_cabang = canAccessAllBranches.value ? '' : getPromoFallbackBranchId(auth) || '';
  filters.id_perusahaan = '';
  filters.id_principal = '';
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
    selectedRow.value = null;
    detail.value = null;
    return;
  }
  if (String(previousCompany || '') !== String(filters.id_perusahaan || '')) {
    filters.id_principal = '';
    selectedRow.value = null;
    detail.value = null;
  }
}

onMounted(async () => {
  try {
    await loadDropdowns();
  } catch (err) {
    error.value = normalizeError(err, 'Filter approval promo belum bisa dimuat.');
  }

  await loadClaims();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Approval Klaim Promo"
      description="Halaman ini khusus reviewer supaya supervisor/admin bisa fokus pada antrean keputusan klaim promo tanpa bercampur dengan tampilan user biasa."
    />

    <section
      v-if="!isReviewer"
      class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700"
    >
      Halaman ini dirancang untuk supervisor, manager, admin, atau IT yang bertugas mereview klaim promo.
    </section>

    <div class="grid gap-4 md:grid-cols-3">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        :class="[
          'panel flex items-center justify-between gap-3 rounded-3xl border px-5 py-4 text-left transition',
          activeTab === tab.key
            ? 'border-brand-200 bg-brand-50 ring-1 ring-inset ring-brand-200'
            : 'border-slate-200 bg-white hover:border-slate-300'
        ]"
        @click="selectTab(tab.key)"
      >
        <div>
          <p class="text-xs uppercase tracking-[0.25em] text-slate-400">{{ tab.label }}</p>
          <p class="mt-2 text-2xl font-semibold text-slate-900">{{ tabCounts[tab.key].toLocaleString('id-ID') }}</p>
        </div>
        <span
          :class="[
            'rounded-full px-3 py-1 text-xs font-semibold',
            tab.key === 'all'
              ? 'bg-slate-100 text-slate-700'
              : tab.key === 'review'
              ? 'bg-brand-100 text-brand-700'
              : tab.key === 'rejected'
                ? 'bg-rose-100 text-rose-700'
                : 'bg-emerald-100 text-emerald-700'
          ]"
        >
          {{ tab.label }}
        </span>
      </button>
    </div>

    <AppFilterBar :model-value="filters" :fields="filterFields" @update:model-value="updateFilters" @submit="loadClaims" @reset="resetFilters" />

    <section v-if="feedback" class="rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-700">
      {{ feedback }}
    </section>

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ error }}
    </section>

    <div class="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
      <section class="panel p-5">
        <div class="mb-4">
          <h3 class="text-lg font-semibold text-slate-900">Daftar Klaim untuk Review</h3>
          <p class="mt-1 text-sm text-slate-500">
            Tab aktif menentukan antrean kerja reviewer. Klik salah satu klaim untuk membaca detail dan mengambil keputusan.
          </p>
        </div>

        <AppTable
          :columns="tableColumns"
          :rows="rows"
          :loading="loading"
          row-key="id"
          :selected-key="selectedKey"
          :clickable-rows="true"
          empty-message="Belum ada klaim pada tab approval yang sedang dibuka."
          @row-click="loadClaimDetail"
        />
      </section>

      <section class="panel p-5">
        <div v-if="selectedRow" class="space-y-4">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 class="text-lg font-semibold text-slate-900">Detail Approval Klaim</h3>
              <p class="mt-1 text-sm text-slate-500">Reviewer bisa menilai klaim dan mengambil keputusan langsung dari panel ini.</p>
            </div>

            <div class="flex flex-wrap gap-2" v-if="isReviewer">
              <button
                v-if="canApprove"
                class="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-60"
                :disabled="actionLoading"
                @click="approveSelectedClaim"
              >
                {{ actionLoading ? 'Memproses...' : 'Setujui' }}
              </button>
              <button
                v-if="canReject"
                class="rounded-xl border border-rose-200 bg-rose-50 px-4 py-2 text-sm font-medium text-rose-700 hover:bg-rose-100 disabled:opacity-60"
                :disabled="actionLoading"
                @click="rejectSelectedClaim"
              >
                {{ actionLoading ? 'Memproses...' : 'Tolak' }}
              </button>
            </div>
          </div>

          <div
            class="rounded-2xl border border-brand-100 bg-brand-50/60 px-4 py-3 text-sm text-brand-700"
            v-if="isReviewer"
          >
            Reviewer fokus pada tiga antrean: klaim baru untuk direview, klaim yang sudah ditolak, dan klaim yang sudah disetujui.
          </div>

          <div v-if="detailLoading" class="py-10 text-center text-sm text-slate-500">
            Memuat detail approval klaim...
          </div>

          <template v-else-if="detail">
            <div class="grid gap-3 md:grid-cols-2">
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
                <div class="mt-2">
                  <span :class="statusBadgeConfig(detail.status_klaim).className">
                    {{ statusBadgeConfig(detail.status_klaim).text }}
                  </span>
                </div>
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
          </template>
        </div>

        <div v-else class="py-8">
          <AppEmptyState
            title="Belum ada klaim terpilih"
            description="Pilih klaim dari tabel kiri untuk mulai meninjau detail approval promo."
          />
        </div>
      </section>
    </div>
  </div>
</template>
