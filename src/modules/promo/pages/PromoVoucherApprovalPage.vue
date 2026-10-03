<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import { useAuthStore } from '@/app/stores/auth';
import { approveVoucherUsage, getVoucherUsageDetail, getVoucherUsageMonitoring, rejectVoucherUsage } from '@/api/promo';
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

const filters = reactive({
  branch: '',
  company: '',
  principal: '',
  tipe_voucher: '',
  usage_kind: '',
  search: ''
});

const auth = useAuthStore();
const branches = ref([]);
const companies = ref([]);
const principals = ref([]);
const rows = ref([]);
const loading = ref(false);
const detailLoading = ref(false);
const acting = ref(false);
const error = ref('');
const feedback = ref('');
const selectedRow = ref(null);
const selectedDetail = ref(null);
const activeTab = ref('pending');
const reviewerNote = ref('');

const canAccessAllBranches = computed(() => canAccessAllPromoBranches(auth));
const branchOptions = computed(() => getPromoBranchOptions(branches.value, auth));
const companyOptions = computed(() => getPromoCompanyOptions(companies.value, branches.value, filters.branch));
const principalOptions = computed(() => getPromoPrincipalOptions(principals.value, filters.company));

const filterFields = computed(() => [
  { key: 'branch', label: 'Cabang', type: 'select', options: branchOptions.value, disabled: !canAccessAllBranches.value },
  { key: 'company', label: 'Perusahaan', type: 'select', options: companyOptions.value, disabled: !filters.branch },
  { key: 'principal', label: 'Principal', type: 'select', options: principalOptions.value, disabled: !filters.company },
  {
    key: 'tipe_voucher',
    label: 'Tipe Voucher',
    type: 'select',
    options: [
      { value: '1', label: 'Voucher 1' },
      { value: '2', label: 'Voucher 2' },
      { value: '3', label: 'Voucher 3' }
    ]
  },
  {
    key: 'usage_kind',
    label: 'Jenis Pemakaian',
    type: 'select',
    options: [
      { value: 'regular', label: 'Reguler' },
      { value: 'product', label: 'Produk' }
    ]
  },
  { key: 'search', label: 'Cari Data', placeholder: 'Faktur, promo, customer, sales' }
]);

const tabs = [
  { key: 'pending', label: 'Menunggu Review' },
  { key: 'confirmed', label: 'Terkonfirmasi' },
  { key: 'rejected', label: 'Tertolak' },
  { key: 'all', label: 'Semua' }
];

function resolveTabKey(row) {
  if (row.review_status_label === 'Tertolak') return 'rejected';
  if (row.review_status_label === 'Terkonfirmasi' || row.review_status_label === 'Terpakai') return 'confirmed';
  if (row.review_status_label === 'Draft') return 'pending';
  return 'all';
}

const filteredRows = computed(() => {
  if (activeTab.value === 'all') return rows.value;
  return rows.value.filter((row) => resolveTabKey(row) === activeTab.value);
});

const summary = computed(() => ({
  total: rows.value.length,
  pending: rows.value.filter((row) => resolveTabKey(row) === 'pending').length,
  confirmed: rows.value.filter((row) => resolveTabKey(row) === 'confirmed').length,
  rejected: rows.value.filter((row) => resolveTabKey(row) === 'rejected').length
}));

const selectedKey = computed(() => `${selectedRow.value?.usage_kind || ''}:${selectedRow.value?.usage_id || ''}`);

const tableColumns = [
  { key: 'kode_voucher', label: 'Kode Voucher' },
  { key: 'nama_voucher', label: 'Nama Voucher' },
  { key: 'principal', label: 'Principal' },
  { key: 'nama_customer', label: 'Customer' },
  { key: 'nama_sales', label: 'Sales' },
  {
    key: 'usage_kind',
    label: 'Jenis',
    render: (row) => ({
      text: row.usage_kind === 'product' ? 'Produk' : 'Reguler',
      className:
        row.usage_kind === 'product'
          ? 'inline-flex min-w-[86px] items-center justify-center rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700'
          : 'inline-flex min-w-[86px] items-center justify-center rounded-full bg-sky-100 px-3 py-1 text-xs font-semibold text-sky-700'
    })
  },
  {
    key: 'review_status_label',
    label: 'Status Review',
    render: (row) => ({
      text: row.review_status_label,
      className:
        row.review_status_label === 'Terkonfirmasi'
          ? 'inline-flex min-w-[110px] items-center justify-center rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700'
          : row.review_status_label === 'Terpakai'
            ? 'inline-flex min-w-[110px] items-center justify-center rounded-full bg-indigo-100 px-3 py-1 text-xs font-semibold text-indigo-700'
            : row.review_status_label === 'Tertolak'
              ? 'inline-flex min-w-[110px] items-center justify-center rounded-full bg-rose-100 px-3 py-1 text-xs font-semibold text-rose-700'
              : 'inline-flex min-w-[110px] items-center justify-center rounded-full bg-slate-200 px-3 py-1 text-xs font-semibold text-slate-700'
    })
  }
];

async function loadReferences() {
  const [branchResponse, companyResponse, principalResponse] = await Promise.all([
    getBranches(),
    getCompanies(),
    getPrincipals()
  ]);
  branches.value = normalizeList(unwrapResponse(branchResponse));
  companies.value = normalizeList(unwrapResponse(companyResponse));
  principals.value = normalizeList(unwrapResponse(principalResponse));
  applyLoginBranchScope();
}

async function loadRows() {
  loading.value = true;
  error.value = '';
  try {
    const response = await getVoucherUsageMonitoring({
      id_cabang: filters.branch,
      id_perusahaan: filters.company,
      id_principal: filters.principal,
      tipe_voucher: filters.tipe_voucher,
      usage_kind: filters.usage_kind,
      filters: filters.search
    });
    const payload = unwrapResponse(response) || {};
    rows.value = normalizeList(payload.pages || payload);
  } catch (err) {
    error.value = normalizeError(err, 'Approval voucher belum bisa dimuat.');
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

function applyLoginBranchScope() {
  const fallbackBranch = getPromoFallbackBranchId(auth);
  if (!canAccessAllBranches.value && fallbackBranch) {
    filters.branch = String(fallbackBranch);
  }
}

function updateFilters(nextFilters) {
  const previousBranch = filters.branch;
  const previousCompany = filters.company;
  Object.assign(filters, nextFilters || {});
  if (String(previousBranch || '') !== String(filters.branch || '')) {
    filters.company = '';
    filters.principal = '';
    selectedRow.value = null;
    selectedDetail.value = null;
    return;
  }
  if (String(previousCompany || '') !== String(filters.company || '')) {
    filters.principal = '';
    selectedRow.value = null;
    selectedDetail.value = null;
  }
}

function resetFilters() {
  Object.assign(filters, {
    branch: canAccessAllBranches.value ? '' : getPromoFallbackBranchId(auth) || '',
    company: '',
    principal: '',
    tipe_voucher: '',
    usage_kind: '',
    search: ''
  });
  selectedRow.value = null;
  selectedDetail.value = null;
}

async function openDetail(row) {
  selectedRow.value = row;
  detailLoading.value = true;
  feedback.value = '';
  reviewerNote.value = '';
  try {
    const response = await getVoucherUsageDetail(row.usage_kind, row.usage_id);
    selectedDetail.value = unwrapResponse(response) || {};
  } catch (err) {
    error.value = normalizeError(err, 'Detail approval voucher belum bisa dimuat.');
    selectedDetail.value = null;
  } finally {
    detailLoading.value = false;
  }
}

async function approveSelected() {
  if (!selectedRow.value?.can_approve) return;
  acting.value = true;
  error.value = '';
  feedback.value = '';
  try {
    await approveVoucherUsage({
      usage_kind: selectedRow.value.usage_kind,
      usage_id: selectedRow.value.usage_id,
      reviewer_note: reviewerNote.value
    });
    feedback.value = 'Voucher berhasil dikonfirmasi.';
    await loadRows();
    const replacement = rows.value.find(
      (item) => item.usage_kind === selectedRow.value.usage_kind && String(item.usage_id) === String(selectedRow.value.usage_id)
    );
    if (replacement) {
      await openDetail(replacement);
    }
    reviewerNote.value = '';
  } catch (err) {
    error.value = normalizeError(err, 'Voucher belum berhasil dikonfirmasi.');
  } finally {
    acting.value = false;
  }
}

async function rejectSelected() {
  if (!selectedRow.value?.can_reject) return;
  const confirmed = window.confirm('Tolak pemakaian voucher yang sedang dipilih?');
  if (!confirmed) return;

  acting.value = true;
  error.value = '';
  feedback.value = '';
  try {
    await rejectVoucherUsage({
      usage_kind: selectedRow.value.usage_kind,
      usage_id: selectedRow.value.usage_id,
      reviewer_note: reviewerNote.value
    });
    feedback.value = 'Voucher berhasil ditolak.';
    await loadRows();
    const replacement = rows.value.find(
      (item) => item.usage_kind === selectedRow.value.usage_kind && String(item.usage_id) === String(selectedRow.value.usage_id)
    );
    if (replacement) {
      await openDetail(replacement);
    }
    reviewerNote.value = '';
  } catch (err) {
    error.value = normalizeError(err, 'Voucher belum berhasil ditolak.');
  } finally {
    acting.value = false;
  }
}

watch(selectedRow, () => {
  reviewerNote.value = '';
});

onMounted(async () => {
  await loadReferences();
  await loadRows();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Approval Voucher"
      description="Reviewer memantau voucher yang digunakan di order, melihat detail invoice dan item voucher, lalu memutuskan konfirmasi atau tolak dari satu layar operasional."
    />

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <article class="panel p-5"><p class="text-xs uppercase tracking-[0.25em] text-slate-400">Total Review</p><p class="mt-3 text-2xl font-semibold text-slate-900">{{ summary.total }}</p></article>
      <article class="panel p-5"><p class="text-xs uppercase tracking-[0.25em] text-slate-400">Menunggu Review</p><p class="mt-3 text-2xl font-semibold text-slate-700">{{ summary.pending }}</p></article>
      <article class="panel p-5"><p class="text-xs uppercase tracking-[0.25em] text-slate-400">Terkonfirmasi / Terpakai</p><p class="mt-3 text-2xl font-semibold text-emerald-600">{{ summary.confirmed }}</p></article>
      <article class="panel p-5"><p class="text-xs uppercase tracking-[0.25em] text-slate-400">Tertolak</p><p class="mt-3 text-2xl font-semibold text-rose-600">{{ summary.rejected }}</p></article>
    </section>

    <AppFilterBar
      :model-value="filters"
      :fields="filterFields"
      @update:model-value="updateFilters"
      @submit="loadRows"
      @reset="resetFilters"
    />

    <div class="flex flex-wrap gap-2">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="rounded-full px-4 py-2 text-sm font-medium transition"
        :class="activeTab === tab.key ? 'bg-brand-600 text-white' : 'border border-slate-200 bg-white text-slate-600 hover:bg-slate-50'"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
    </div>

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ error }}
    </section>
    <section v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
      {{ feedback }}
    </section>

    <section class="grid gap-6 xl:grid-cols-2">
      <article class="panel p-5">
        <div class="flex items-center justify-between gap-4">
          <div>
            <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Review by Customer</p>
            <h3 class="mt-2 text-lg font-semibold text-slate-900">Customer yang paling sering masuk approval</h3>
          </div>
          <span class="rounded-full bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-700">{{ filteredRows.length }} usage</span>
        </div>
        <div class="mt-4 space-y-3">
          <div
            v-for="customer in [...filteredRows].reduce((map, row) => {
              const key = row.nama_customer || 'Customer tidak diketahui';
              const current = map.get(key) || { nama_customer: key, total: 0, nominal: 0 };
              current.total += 1;
              current.nominal += Number(row.nominal_promo || 0);
              map.set(key, current);
              return map;
            }, new Map()).values()"
            :key="customer.nama_customer"
            class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"
          >
            <div class="flex items-center justify-between gap-4">
              <div>
                <p class="text-sm font-semibold text-slate-900">{{ customer.nama_customer }}</p>
                <p class="mt-1 text-xs text-slate-500">{{ customer.total }} usage perlu perhatian</p>
              </div>
              <p class="text-sm font-semibold text-slate-900">
                {{ new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(customer.nominal) }}
              </p>
            </div>
          </div>
          <p v-if="!filteredRows.length" class="text-sm text-slate-500">Belum ada customer pada tab review ini.</p>
        </div>
      </article>

      <article class="panel p-5">
        <div class="flex items-center justify-between gap-4">
          <div>
            <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Review by Sales</p>
            <h3 class="mt-2 text-lg font-semibold text-slate-900">Sales yang paling banyak memakai voucher</h3>
          </div>
          <span class="rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">Top usage</span>
        </div>
        <div class="mt-4 space-y-3">
          <div
            v-for="sales in [...filteredRows].reduce((map, row) => {
              const key = row.nama_sales || 'Sales tidak diketahui';
              const current = map.get(key) || { nama_sales: key, total: 0, nominal: 0 };
              current.total += 1;
              current.nominal += Number(row.nominal_promo || 0);
              map.set(key, current);
              return map;
            }, new Map()).values()"
            :key="sales.nama_sales"
            class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"
          >
            <div class="flex items-center justify-between gap-4">
              <div>
                <p class="text-sm font-semibold text-slate-900">{{ sales.nama_sales }}</p>
                <p class="mt-1 text-xs text-slate-500">{{ sales.total }} invoice voucher</p>
              </div>
              <p class="text-sm font-semibold text-slate-900">
                {{ new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(sales.nominal) }}
              </p>
            </div>
          </div>
          <p v-if="!filteredRows.length" class="text-sm text-slate-500">Belum ada data sales pada tab review ini.</p>
        </div>
      </article>
    </section>

    <section class="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
      <AppTable
        :rows="filteredRows"
        :columns="tableColumns"
        :loading="loading"
        :clickable-rows="true"
        row-key="usage_id"
        :selected-key="selectedKey"
        empty-message="Belum ada voucher untuk direview."
        @row-click="openDetail"
      />

      <aside class="panel p-5">
        <div class="flex items-start justify-between gap-4">
          <div>
            <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Panel Review</p>
            <h3 class="mt-2 text-xl font-semibold text-slate-900">{{ selectedDetail?.kode_voucher || 'Pilih data review' }}</h3>
            <p class="mt-1 text-sm text-slate-500">{{ selectedDetail?.nama_voucher || 'Klik salah satu baris agar reviewer bisa melihat detail invoice dan item voucher.' }}</p>
          </div>
          <div class="flex flex-wrap gap-2" v-if="selectedRow">
            <button
              class="rounded-xl border border-emerald-200 px-3 py-2 text-sm font-medium text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
              :disabled="acting || !selectedRow.can_approve"
              @click="approveSelected"
            >
              Konfirmasi
            </button>
            <button
              class="rounded-xl border border-rose-200 px-3 py-2 text-sm font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-50"
              :disabled="acting || !selectedRow.can_reject"
              @click="rejectSelected"
            >
              Tolak
            </button>
          </div>
        </div>

        <div v-if="detailLoading" class="mt-6 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
          Memuat detail approval voucher...
        </div>

        <AppEmptyState
          v-else-if="!selectedDetail"
          title="Belum ada data dipilih"
          description="Panel ini akan menampilkan informasi review voucher yang dipakai pada invoice dan customer tertentu."
        />

        <div v-else class="mt-6 space-y-4">
          <div class="grid gap-3 sm:grid-cols-2">
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"><p class="text-xs uppercase tracking-[0.2em] text-slate-400">Invoice</p><p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedDetail.no_faktur || '-' }}</p></div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"><p class="text-xs uppercase tracking-[0.2em] text-slate-400">Status</p><p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedDetail.review_status_label || '-' }}</p></div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"><p class="text-xs uppercase tracking-[0.2em] text-slate-400">Customer</p><p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedDetail.nama_customer || '-' }}</p></div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"><p class="text-xs uppercase tracking-[0.2em] text-slate-400">Sales</p><p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedDetail.nama_sales || '-' }}</p></div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"><p class="text-xs uppercase tracking-[0.2em] text-slate-400">Principal</p><p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedDetail.principal || '-' }}</p></div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"><p class="text-xs uppercase tracking-[0.2em] text-slate-400">Nilai Voucher</p><p class="mt-2 text-sm font-semibold text-slate-900">{{ new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(Number(selectedDetail.nominal_promo || 0)) }}</p></div>
          </div>

          <div class="rounded-2xl border border-slate-200 bg-white p-4">
            <label class="block text-sm font-semibold text-slate-900">Catatan Reviewer</label>
            <p class="mt-1 text-xs text-slate-500">Catatan ini akan tersimpan sebagai histori keputusan approval voucher.</p>
            <textarea
              v-model="reviewerNote"
              rows="3"
              class="mt-3 w-full rounded-2xl border border-slate-200 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-brand-300 focus:ring-4 focus:ring-brand-100"
              placeholder="Tulis alasan konfirmasi atau penolakan voucher ini..."
            />
          </div>

          <div class="rounded-2xl border border-slate-200 bg-white p-4">
            <p class="text-sm font-semibold text-slate-900">Catatan Review Terbaru</p>
            <div v-if="selectedDetail.latest_review_note" class="mt-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <div class="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span class="rounded-full bg-slate-200 px-2.5 py-1 font-medium text-slate-700">{{ selectedDetail.latest_review_note.action_type }}</span>
                <span>{{ selectedDetail.latest_review_note.reviewer_name || 'Reviewer' }}</span>
                <span>{{ selectedDetail.latest_review_note.created_at || '-' }}</span>
              </div>
              <p class="mt-3 text-sm text-slate-700">{{ selectedDetail.latest_review_note.reviewer_note || '-' }}</p>
            </div>
            <p v-else class="mt-3 text-sm text-slate-500">Belum ada catatan reviewer pada voucher ini.</p>
          </div>

          <div class="rounded-2xl border border-slate-200 bg-white p-4">
            <p class="text-sm font-semibold text-slate-900">Item Voucher</p>
            <div class="mt-3 space-y-3">
              <div v-for="item in selectedDetail.items || []" :key="`${item.id_produk}-${item.nama_produk}`" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                <p class="text-sm font-semibold text-slate-900">{{ item.nama_produk || `Produk ${item.id_produk}` }}</p>
                <div class="mt-2 flex flex-wrap gap-4 text-xs text-slate-500">
                  <span>Discount: {{ item.discount || 0 }}</span>
                  <span>Nilai: {{ new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(Number(item.nilai_discount || 0)) }}</span>
                </div>
              </div>
              <p v-if="!(selectedDetail.items || []).length" class="text-sm text-slate-500">Belum ada item yang tercatat.</p>
            </div>
          </div>

          <div class="rounded-2xl border border-slate-200 bg-white p-4">
            <p class="text-sm font-semibold text-slate-900">Histori Review</p>
            <div class="mt-3 space-y-3">
              <div
                v-for="note in selectedDetail.review_notes || []"
                :key="note.id"
                class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"
              >
                <div class="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <span class="rounded-full bg-slate-200 px-2.5 py-1 font-medium text-slate-700">{{ note.action_type }}</span>
                  <span>{{ note.reviewer_name || 'Reviewer' }}</span>
                  <span>{{ note.created_at || '-' }}</span>
                </div>
                <p class="mt-3 text-sm text-slate-700">{{ note.reviewer_note || '-' }}</p>
              </div>
              <p v-if="!(selectedDetail.review_notes || []).length" class="text-sm text-slate-500">Belum ada histori review untuk voucher ini.</p>
            </div>
          </div>
        </div>
      </aside>
    </section>
  </div>
</template>
