<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import { getMonthlySalesTargets } from '@/api/sales';
import { useAuthStore } from '@/app/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import AppEmptyState from '@/shared/components/AppEmptyState.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import {
  getSupervisorBranchOptions,
  getSupervisorCompanyOptions,
  getSupervisorPrincipalOptions,
  resetSupervisorBranchWhenCompanyChanges,
  syncSupervisorCompanyFromBranch,
} from '@/modules/supervisor-sales/utils/supervisorScope';

const auth = useAuthStore();
const now = new Date();

const filter = reactive({
  tahun: String(now.getFullYear()),
  bulan: String(now.getMonth() + 1).padStart(2, '0'),
  id_cabang: '',
  id_perusahaan: '',
  id_principal: '',
  search: ''
});

const loading = ref(false);
const error = ref('');
const feedback = ref('');
const principals = ref([]);
const companies = ref([]);
const branches = ref([]);
const rows = ref([]);

const monthOptions = [
  { value: '01', label: 'Januari' },
  { value: '02', label: 'Februari' },
  { value: '03', label: 'Maret' },
  { value: '04', label: 'April' },
  { value: '05', label: 'Mei' },
  { value: '06', label: 'Juni' },
  { value: '07', label: 'Juli' },
  { value: '08', label: 'Agustus' },
  { value: '09', label: 'September' },
  { value: '10', label: 'Oktober' },
  { value: '11', label: 'November' },
  { value: '12', label: 'Desember' }
];

const fallbackBranchId = computed(() => auth.user?.cabang?.id || auth.user?.cabang_id || auth.user?.id_cabang || '');
const companyOptions = computed(() => getSupervisorCompanyOptions(companies.value, branches.value, '', auth, true));
const branchOptions = computed(() => getSupervisorBranchOptions(branches.value, auth, true, filter.id_perusahaan, companies.value));
const principalOptions = computed(() => getSupervisorPrincipalOptions(principals.value, filter.id_perusahaan, true));

const filteredRows = computed(() => {
  const query = String(filter.search || '').trim().toLowerCase();
  if (!query) return rows.value;

  return rows.value.filter((row) =>
    [row.nama_sales, row.kode_sales, row.nama_cabang, row.nama_principals]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query))
  );
});

const summary = computed(() => {
  const totalTarget = filteredRows.value.reduce((sum, row) => sum + Number(row.target_omset || 0), 0);
  const totalActual = filteredRows.value.reduce((sum, row) => sum + Number(row.actual_omset || 0), 0);
  const achievement = totalTarget > 0 ? (totalActual / totalTarget) * 100 : 0;
  const onTrack = filteredRows.value.filter((row) => Number(row.achievement_percent || 0) >= 100).length;
  const needAttention = filteredRows.value.filter((row) => Number(row.achievement_percent || 0) < 70).length;

  return {
    totalTarget,
    totalActual,
    achievement,
    onTrack,
    needAttention
  };
});

const rankedRows = computed(() =>
  [...filteredRows.value]
    .sort((left, right) => Number(right.achievement_percent || 0) - Number(left.achievement_percent || 0))
    .map((row, index) => ({
      ...row,
      rank: index + 1
    }))
);

const topPerformers = computed(() => rankedRows.value.slice(0, 5));
const watchlist = computed(() => rankedRows.value.filter((row) => Number(row.achievement_percent || 0) < 70).slice(0, 5));

const columns = [
  {
    key: 'rank',
    label: 'Rank',
    render: (row) => row.rank || '-'
  },
  {
    key: 'nama_sales',
    label: 'Sales',
    render: (row) => `${row.nama_sales || '-'}${row.kode_sales ? ` (${row.kode_sales})` : ''}`
  },
  { key: 'nama_cabang', label: 'Cabang' },
  { key: 'nama_principals', label: 'Principal' },
  {
    key: 'target_omset',
    label: 'Target',
    render: (row) => `Rp ${Number(row.target_omset || 0).toLocaleString('id-ID')}`
  },
  {
    key: 'actual_omset',
    label: 'Aktual',
    render: (row) => `Rp ${Number(row.actual_omset || 0).toLocaleString('id-ID')}`
  },
  {
    key: 'gap_omset',
    label: 'Gap',
    render: (row) => {
      const gap = Number(row.actual_omset || 0) - Number(row.target_omset || 0);
      const prefix = gap >= 0 ? '+' : '-';
      return `${prefix} Rp ${Math.abs(gap).toLocaleString('id-ID')}`;
    }
  },
  {
    key: 'achievement_percent',
    label: 'Pencapaian',
    render: (row) => `${Number(row.achievement_percent || 0).toLocaleString('id-ID', { maximumFractionDigits: 2 })}%`
  },
  {
    key: 'status',
    label: 'Status',
    render: (row) => {
      const percent = Number(row.achievement_percent || 0);
      if (percent >= 100) return 'On Track';
      if (percent >= 70) return 'Perlu Dorongan';
      return 'Butuh Perhatian';
    }
  }
];

function progressWidth(value) {
  return `${Math.max(8, Math.min(100, Number(value || 0)))}%`;
}

function statusTone(value) {
  const percent = Number(value || 0);
  if (percent >= 100) return 'bg-emerald-500';
  if (percent >= 70) return 'bg-amber-400';
  return 'bg-rose-500';
}

async function loadPrincipals() {
  const [branchResponse, companyResponse, principalResponse] = await Promise.all([getBranches(), getCompanies(), getPrincipals()]);
  branches.value = normalizeList(unwrapResponse(branchResponse));
  companies.value = normalizeList(unwrapResponse(companyResponse));
  principals.value = normalizeList(unwrapResponse(principalResponse));
  if (!filter.id_cabang && fallbackBranchId.value) filter.id_cabang = String(fallbackBranchId.value);
  syncSupervisorCompanyFromBranch(filter, 'id_cabang', 'id_perusahaan', branches.value, companies.value);
}

async function loadTargets() {
  loading.value = true;
  error.value = '';

  try {
    const response = await getMonthlySalesTargets({
      tahun: filter.tahun,
      bulan: Number(filter.bulan),
      id_principal: filter.id_principal || undefined,
      id_cabang: filter.id_cabang || fallbackBranchId.value || undefined,
      id_perusahaan: filter.id_perusahaan || undefined
    });

    const payload = unwrapResponse(response) || {};
    rows.value = normalizeList(payload.rows).map((row) => {
      const target = Number(row.target_omset || 0);
      const actual = Number(row.actual_omset || 0);
      const achievement = target > 0 ? Math.round((actual / target) * 10000) / 100 : 0;
      return {
        ...row,
        target_omset: target,
        actual_omset: actual,
        achievement_percent: Number(row.achievement_percent ?? achievement),
        gap_omset: actual - target
      };
    });

    feedback.value = `Monitor omset memuat ${rows.value.length} sales untuk ${monthOptions.find((item) => item.value === filter.bulan)?.label || filter.bulan} ${filter.tahun}.`;
  } catch (err) {
    error.value = normalizeError(err, 'Data monitor target omset belum bisa dimuat.');
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

function resetFilters() {
  filter.tahun = String(now.getFullYear());
  filter.bulan = String(now.getMonth() + 1).padStart(2, '0');
  filter.id_cabang = fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  filter.id_perusahaan = '';
  filter.id_principal = '';
  filter.search = '';
  syncSupervisorCompanyFromBranch(filter, 'id_cabang', 'id_perusahaan', branches.value, companies.value);
  loadTargets();
}

onMounted(async () => {
  try {
    await loadPrincipals();
  } catch (err) {
    error.value = normalizeError(err, 'Referensi principal belum bisa dimuat.');
  }

  await loadTargets();
});

function handleCompanyChange() {
  resetSupervisorBranchWhenCompanyChanges(filter, 'id_perusahaan', 'id_cabang', branches.value, auth, companies.value);
  filter.id_principal = '';
}
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Monitoring Target Omset"
      description="Supervisor memantau capaian target omset per sales, membaca gap yang masih tertinggal, dan melihat siapa yang perlu didorong pada periode berjalan."
    >
      <div class="flex flex-wrap gap-3">
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50" @click="resetFilters">
          Reset
        </button>
        <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700" @click="loadTargets">
          Refresh
        </button>
      </div>
    </PageHeader>

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ error }}
    </section>

    <section class="panel p-6">
      <div class="grid gap-4 md:grid-cols-6">
        <AppFormField v-model="filter.tahun" label="Tahun" type="number" />
        <AppSearchSelect v-model="filter.bulan" label="Bulan" placeholder="Pilih bulan" :options="monthOptions" />
        <AppSearchSelect v-model="filter.id_perusahaan" label="Perusahaan" placeholder="Semua perusahaan" :options="companyOptions" @update:model-value="handleCompanyChange" />
        <AppSearchSelect v-model="filter.id_cabang" label="Cabang" placeholder="Semua cabang" :options="branchOptions" :disabled="!filter.id_perusahaan" empty-text="Pilih perusahaan terlebih dahulu." />
        <AppSearchSelect v-model="filter.id_principal" label="Principal" placeholder="Semua principal" :options="principalOptions" :disabled="!filter.id_perusahaan" empty-text="Pilih perusahaan terlebih dahulu." />
        <AppFormField v-model="filter.search" label="Cari Sales" placeholder="Nama sales, kode, cabang" />
      </div>

      <div class="mt-5 flex flex-wrap gap-3">
        <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700" @click="loadTargets">
          Tampilkan Monitor
        </button>
      </div>

      <div v-if="feedback" class="mt-4 rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-700">
        {{ feedback }}
      </div>
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Total Target</p>
        <p class="mt-3 text-3xl font-bold text-slate-950">Rp {{ summary.totalTarget.toLocaleString('id-ID') }}</p>
        <p class="mt-2 text-sm text-slate-500">Akumulasi target omset dari hasil filter supervisor saat ini.</p>
      </article>
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Total Aktual</p>
        <p class="mt-3 text-3xl font-bold text-emerald-600">Rp {{ summary.totalActual.toLocaleString('id-ID') }}</p>
        <p class="mt-2 text-sm text-slate-500">Omset yang sudah tercatat dari transaksi periode aktif.</p>
      </article>
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Capaian Rata-rata</p>
        <p class="mt-3 text-3xl font-bold text-brand-700">
          {{ summary.achievement.toLocaleString('id-ID', { maximumFractionDigits: 2 }) }}%
        </p>
        <p class="mt-2 text-sm text-slate-500">Perbandingan total aktual terhadap total target tim sales.</p>
      </article>
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Butuh Perhatian</p>
        <p class="mt-3 text-3xl font-bold text-rose-600">{{ summary.needAttention }}</p>
        <p class="mt-2 text-sm text-slate-500">{{ summary.onTrack }} sales sudah mencapai atau melampaui target.</p>
      </article>
    </section>

    <div class="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
      <section class="panel p-6">
        <div class="mb-4 flex items-center justify-between gap-3">
          <div>
            <h3 class="text-xl font-bold text-slate-950">Peringkat Pencapaian</h3>
            <p class="mt-1 text-sm text-slate-500">Urutan sales dengan progres target tertinggi pada periode yang dipilih.</p>
          </div>
          <div class="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
            {{ topPerformers.length }} Teratas
          </div>
        </div>

        <div v-if="topPerformers.length" class="space-y-4">
          <article
            v-for="row in topPerformers"
            :key="row.id_sales"
            class="rounded-3xl border border-slate-200 bg-slate-50 p-4"
          >
            <div class="flex items-start justify-between gap-3">
              <div>
                <p class="text-sm font-semibold text-slate-500">#{{ row.rank }}</p>
                <h4 class="mt-1 text-base font-bold text-slate-950">{{ row.nama_sales || '-' }}</h4>
                <p class="mt-1 text-sm text-slate-500">{{ row.nama_cabang || '-' }} • {{ row.nama_principals || '-' }}</p>
              </div>
              <span class="rounded-full bg-white px-3 py-1 text-sm font-semibold text-slate-700">
                {{ Number(row.achievement_percent || 0).toLocaleString('id-ID', { maximumFractionDigits: 2 }) }}%
              </span>
            </div>

            <div class="mt-4 h-3 overflow-hidden rounded-full bg-slate-200">
              <div :class="['h-full rounded-full', statusTone(row.achievement_percent)]" :style="{ width: progressWidth(row.achievement_percent) }" />
            </div>

            <div class="mt-3 flex flex-wrap gap-4 text-sm text-slate-600">
              <span>Target: Rp {{ Number(row.target_omset || 0).toLocaleString('id-ID') }}</span>
              <span>Aktual: Rp {{ Number(row.actual_omset || 0).toLocaleString('id-ID') }}</span>
            </div>
          </article>
        </div>

        <AppEmptyState
          v-else
          title="Belum ada ranking omset"
          description="Data target omset belum tersedia untuk filter yang dipilih."
        />
      </section>

      <section class="panel p-6">
        <div class="mb-4 flex items-center justify-between gap-3">
          <div>
            <h3 class="text-xl font-bold text-slate-950">Watchlist Supervisor</h3>
            <p class="mt-1 text-sm text-slate-500">Sales dengan capaian rendah yang perlu perhatian dan follow up lebih dekat.</p>
          </div>
          <div class="rounded-full bg-rose-50 px-3 py-1 text-xs font-semibold text-rose-700">
            {{ watchlist.length }} Prioritas
          </div>
        </div>

        <div v-if="watchlist.length" class="space-y-4">
          <article
            v-for="row in watchlist"
            :key="row.id_sales"
            class="rounded-3xl border border-rose-100 bg-rose-50/60 p-4"
          >
            <div class="flex items-start justify-between gap-3">
              <div>
                <h4 class="text-base font-bold text-slate-950">{{ row.nama_sales || '-' }}</h4>
                <p class="mt-1 text-sm text-slate-500">{{ row.nama_cabang || '-' }} • {{ row.nama_principals || '-' }}</p>
              </div>
              <span class="rounded-full bg-white px-3 py-1 text-sm font-semibold text-rose-700">
                {{ Number(row.achievement_percent || 0).toLocaleString('id-ID', { maximumFractionDigits: 2 }) }}%
              </span>
            </div>

            <div class="mt-4 grid gap-3 md:grid-cols-3">
              <div class="rounded-2xl bg-white px-3 py-2 text-sm">
                <p class="text-slate-500">Target</p>
                <p class="mt-1 font-semibold text-slate-950">Rp {{ Number(row.target_omset || 0).toLocaleString('id-ID') }}</p>
              </div>
              <div class="rounded-2xl bg-white px-3 py-2 text-sm">
                <p class="text-slate-500">Aktual</p>
                <p class="mt-1 font-semibold text-slate-950">Rp {{ Number(row.actual_omset || 0).toLocaleString('id-ID') }}</p>
              </div>
              <div class="rounded-2xl bg-white px-3 py-2 text-sm">
                <p class="text-slate-500">Gap</p>
                <p class="mt-1 font-semibold text-rose-700">Rp {{ Math.abs(Number(row.gap_omset || 0)).toLocaleString('id-ID') }}</p>
              </div>
            </div>
          </article>
        </div>

        <AppEmptyState
          v-else
          title="Watchlist sedang kosong"
          description="Belum ada sales dengan capaian di bawah ambang perhatian untuk filter ini."
        />
      </section>
    </div>

    <section class="panel p-6">
      <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 class="text-xl font-bold text-slate-950">Tabel Monitoring Target Omset</h3>
          <p class="mt-1 text-sm text-slate-500">Supervisor bisa membaca performa seluruh sales dalam satu tabel, termasuk gap target dan status pencapaiannya.</p>
        </div>
        <div class="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
          {{ filteredRows.length }} Sales
        </div>
      </div>

      <AppTable
        :rows="rankedRows"
        :columns="columns"
        :loading="loading"
        :paginated="true"
        :default-page-size="15"
        empty-message="Belum ada data target omset untuk filter supervisor yang dipilih."
      />
    </section>
  </div>
</template>
