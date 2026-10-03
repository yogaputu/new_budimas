<script setup>
import { computed, ref } from 'vue';
import { RouterLink } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { navigationSections } from '@/shared/constants/navigation';
import { iconPath, resolveItemIcon, resolveSectionIcon } from '@/shared/utils/navigationIcons';

const auth = useAuthStore();
const search = ref('');
const activeSection = ref('Semua');

const sectionProfiles = {
  Overview: {
    tone: 'from-slate-500 to-blue-600',
    chip: 'bg-slate-100 text-slate-700 dark:bg-slate-500/10 dark:text-slate-200',
    description: 'Ringkasan akun dan landing page utama.'
  },
  'Master Data': {
    tone: 'from-sky-500 to-cyan-500',
    chip: 'bg-sky-100 text-sky-700 dark:bg-sky-500/10 dark:text-sky-200',
    description: 'Fondasi data ERP: user, sales, customer, produk, cabang, dan plafon.'
  },
  'Workflow Center': {
    tone: 'from-brand-500 to-indigo-600',
    chip: 'bg-brand-100 text-brand-700 dark:bg-brand-500/10 dark:text-brand-200',
    description: 'Task lintas Finance, Sales, Warehouse, Purchasing, HRD, approval, deadline, dan audit.'
  },
  Akses: {
    tone: 'from-indigo-500 to-violet-500',
    chip: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-200',
    description: 'Pengaturan fitur user dan jabatan.'
  },
  Distribusi: {
    tone: 'from-emerald-500 to-teal-500',
    chip: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-200',
    description: 'Order, picking, armada, invoice, retur, dan revisi faktur.'
  },
  Finance: {
    tone: 'from-amber-500 to-orange-500',
    chip: 'bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-200',
    description: 'COA, jurnal, pembayaran, pajak, tagihan, dan laporan accounting.'
  },
  Purchase: {
    tone: 'from-lime-500 to-green-600',
    chip: 'bg-lime-100 text-lime-700 dark:bg-lime-500/10 dark:text-lime-200',
    description: 'Purchase order, penerimaan, konfirmasi, dan tagihan purchase.'
  },
  Promo: {
    tone: 'from-pink-500 to-rose-500',
    chip: 'bg-pink-100 text-pink-700 dark:bg-pink-500/10 dark:text-pink-200',
    description: 'Voucher, klaim promo, approval, kasbon, dan monitoring.'
  },
  Operasional: {
    tone: 'from-fuchsia-500 to-purple-600',
    chip: 'bg-fuchsia-100 text-fuchsia-700 dark:bg-fuchsia-500/10 dark:text-fuchsia-200',
    description: 'Stock transfer dan stok opname.'
  },
  'Supervisor Sales': {
    tone: 'from-blue-500 to-brand-600',
    chip: 'bg-blue-100 text-blue-700 dark:bg-blue-500/10 dark:text-blue-200',
    description: 'Dashboard SPV, kunjungan sales, callplan, target, retur, dan DOI.'
  }
};

const visibleSections = computed(() =>
  navigationSections
    .map((section) => ({
      ...section,
      profile: sectionProfiles[section.title] || sectionProfiles.Overview,
      items: section.items.filter((item) => auth.hasMenuAccess(item))
    }))
    .filter((section) => section.items.length)
);

const visibleItems = computed(() =>
  visibleSections.value.flatMap((section) =>
    section.items.map((item) => ({
      ...item,
      section: section.title,
      profile: section.profile
    }))
  )
);

const sectionTabs = computed(() => ['Semua', ...visibleSections.value.map((section) => section.title)]);

const filteredItems = computed(() => {
  const keyword = search.value.trim().toLowerCase();

  return visibleItems.value.filter((item) => {
    const matchSection = activeSection.value === 'Semua' || item.section === activeSection.value;
    const matchSearch =
      !keyword ||
      [item.label, item.section, item.permission]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(keyword));

    return matchSection && matchSearch;
  });
});

const groupedFilteredSections = computed(() =>
  visibleSections.value
    .map((section) => ({
      ...section,
      items: filteredItems.value.filter((item) => item.section === section.title)
    }))
    .filter((section) => section.items.length)
);

const moduleMix = computed(() => {
  const total = visibleItems.value.length || 1;

  return visibleSections.value.map((section) => ({
    title: section.title,
    count: section.items.length,
    percent: Math.round((section.items.length / total) * 100),
    profile: section.profile
  }));
});

const createShortcut = computed(() =>
  visibleItems.value.find((item) =>
    /create|input|buat|tambah|ajukan/i.test(`${item.to} ${item.label}`)
  ) || visibleItems.value[0]
);

const heroStats = computed(() => {
  const financeCount = visibleItems.value.filter((item) => item.section === 'Finance').length;
  const masterCount = visibleItems.value.filter((item) => item.section === 'Master Data').length;
  const workflowCount = visibleItems.value.filter((item) =>
    ['Distribusi', 'Purchase', 'Promo', 'Operasional', 'Supervisor Sales'].includes(item.section)
  ).length;

  return [
    {
      label: 'Menu Aktif',
      value: visibleItems.value.length,
      icon: 'grid',
      tone: 'from-brand-500 to-blue-600',
      note: 'Hanya menu sesuai hak akses login.'
    },
    {
      label: 'Area Kerja',
      value: visibleSections.value.length,
      icon: 'dashboard',
      tone: 'from-emerald-500 to-teal-500',
      note: 'Grup modul yang bisa dibuka.'
    },
    {
      label: 'Finance',
      value: financeCount,
      icon: 'bank',
      tone: 'from-amber-500 to-orange-500',
      note: 'Accounting, pajak, dan pembayaran.'
    },
    {
      label: 'Workflow Harian',
      value: workflowCount,
      icon: 'clipboard',
      tone: 'from-fuchsia-500 to-rose-500',
      note: 'Transaksi dan monitoring operasional.'
    },
    {
      label: 'Master Data',
      value: masterCount,
      icon: 'building',
      tone: 'from-sky-500 to-cyan-500',
      note: 'Data dasar sesuai scope user.'
    }
  ];
});

const accessCards = computed(() => [
  {
    label: 'User',
    value: auth.userName,
    note: auth.roleLabel,
    icon: 'user'
  },
  {
    label: 'Cabang',
    value: auth.branchName,
    note: 'Filter data mengikuti cabang login, kecuali superadmin.',
    icon: 'building'
  },
  {
    label: 'Landing',
    value: auth.homeRoute === '/' ? 'Dashboard' : auth.homeRoute,
    note: 'Rute awal setelah login.',
    icon: 'map'
  }
]);

function initials(label = '') {
  const words = String(label).trim().split(/\s+/).filter(Boolean);
  if (!words.length) return 'BD';
  return words.slice(0, 2).map((word) => word[0]).join('').toUpperCase();
}
</script>

<template>
  <div class="space-y-6">
    <section class="relative overflow-hidden rounded-[36px] border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-950">
      <div class="absolute -right-16 -top-20 h-64 w-64 rounded-full bg-brand-500/10 blur-3xl"></div>
      <div class="absolute -bottom-24 left-1/3 h-56 w-56 rounded-full bg-emerald-500/10 blur-3xl"></div>

      <div class="relative flex flex-wrap items-start justify-between gap-5">
        <div>
          <p class="text-xs font-bold uppercase tracking-[0.35em] text-brand-600 dark:text-brand-300">
            Budimas ERP
          </p>
          <h1 class="mt-3 text-3xl font-black tracking-tight text-slate-950 dark:text-white">
            Dashboard Operasional
          </h1>
          <p class="mt-2 max-w-3xl text-sm leading-6 text-slate-500 dark:text-slate-400">
            Ringkasan akses, shortcut menu, dan kartu modul yang otomatis mengikuti hak akses user login.
            Semua menu di bawah ini adalah menu yang memang boleh dibuka oleh akun aktif.
          </p>
        </div>

        <div class="flex flex-wrap items-center gap-2">
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-2.5 dark:border-slate-800 dark:bg-slate-900">
            <input
              v-model="search"
              type="text"
              placeholder="Cari menu, modul, fitur..."
              class="w-64 bg-transparent text-sm text-slate-900 outline-none placeholder:text-slate-400 dark:text-white"
            />
          </div>

          <RouterLink
            v-if="createShortcut"
            :to="createShortcut.to"
            class="rounded-2xl bg-brand-600 px-5 py-2.5 text-sm font-bold text-white shadow-sm hover:bg-brand-700"
          >
            + Aksi Cepat
          </RouterLink>
        </div>
      </div>

      <div class="relative mt-6 grid gap-3 md:grid-cols-3">
        <article
          v-for="card in accessCards"
          :key="card.label"
          class="rounded-3xl border border-slate-200 bg-slate-50/80 p-4 dark:border-slate-800 dark:bg-slate-900/80"
        >
          <div class="flex items-center gap-3">
            <div class="flex h-11 w-11 items-center justify-center rounded-2xl bg-slate-900 text-xs font-black text-white dark:bg-white dark:text-slate-950">
              <svg class="h-[19px] w-[19px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path :d="iconPath(card.icon)" />
              </svg>
            </div>
            <div class="min-w-0">
              <p class="text-xs font-bold uppercase tracking-[0.2em] text-slate-400">{{ card.label }}</p>
              <p class="truncate text-sm font-bold text-slate-950 dark:text-white">{{ card.value || '-' }}</p>
            </div>
          </div>
          <p class="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">{{ card.note }}</p>
        </article>
      </div>
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
      <article
        v-for="stat in heroStats"
        :key="stat.label"
        class="rounded-[30px] border border-slate-200 bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-lg dark:border-slate-800 dark:bg-slate-950"
      >
        <div
          class="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br text-sm font-black text-white"
          :class="stat.tone"
        >
          <svg class="h-[21px] w-[21px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path :d="iconPath(stat.icon)" />
          </svg>
        </div>
        <p class="mt-4 text-sm font-semibold text-slate-500 dark:text-slate-400">{{ stat.label }}</p>
        <p class="mt-2 text-3xl font-black text-slate-950 dark:text-white">{{ stat.value }}</p>
        <p class="mt-1 text-xs leading-5 text-slate-400">{{ stat.note }}</p>
      </article>
    </section>

    <section class="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
      <div class="rounded-[32px] border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div class="mb-5 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 class="text-lg font-black text-slate-950 dark:text-white">Distribusi Akses</h3>
            <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">Komposisi menu aktif berdasarkan area kerja.</p>
          </div>
          <span class="rounded-full bg-slate-100 px-3 py-1 text-xs font-bold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
            {{ visibleItems.length }} menu
          </span>
        </div>

        <div class="space-y-4">
          <div
            v-for="item in moduleMix"
            :key="item.title"
            class="space-y-2"
          >
            <div class="flex items-center justify-between gap-3 text-sm">
              <span class="font-bold text-slate-700 dark:text-slate-200">{{ item.title }}</span>
              <span class="text-slate-500 dark:text-slate-400">{{ item.count }} menu</span>
            </div>
            <div class="h-3 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
              <div
                class="h-full rounded-full bg-gradient-to-r"
                :class="item.profile.tone"
                :style="{ width: `${Math.max(item.percent, 8)}%` }"
              ></div>
            </div>
          </div>
        </div>
      </div>

      <div class="rounded-[32px] border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div class="mb-5">
          <h3 class="text-lg font-black text-slate-950 dark:text-white">Area Modul</h3>
          <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">Klik area untuk menyaring kartu menu di bawah.</p>
        </div>

        <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <button
            v-for="section in visibleSections"
            :key="section.title"
            type="button"
            class="rounded-3xl border p-4 text-left transition hover:-translate-y-0.5 hover:shadow-md"
            :class="activeSection === section.title ? 'border-brand-300 bg-brand-50 dark:border-brand-500/40 dark:bg-brand-500/10' : 'border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-900'"
            @click="activeSection = section.title"
          >
            <div class="flex items-center justify-between gap-3">
              <div
                class="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br text-xs font-black text-white"
                :class="section.profile.tone"
              >
                <svg class="h-[20px] w-[20px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <path :d="iconPath(resolveSectionIcon(section))" />
                </svg>
              </div>
              <span class="rounded-full px-2.5 py-1 text-xs font-bold" :class="section.profile.chip">
                {{ section.items.length }}
              </span>
            </div>
            <h4 class="mt-4 font-black text-slate-950 dark:text-white">{{ section.title }}</h4>
            <p class="mt-1 line-clamp-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
              {{ section.profile.description }}
            </p>
          </button>
        </div>
      </div>
    </section>

    <section class="rounded-[32px] border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
      <div class="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 class="text-lg font-black text-slate-950 dark:text-white">Semua Menu Aktif</h3>
          <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Kartu ini mengikuti permission user. Jika user cabang biasa login, data di halaman terkait tetap mengikuti filter cabang/perusahaan yang sudah kita ratakan.
          </p>
        </div>

        <div class="flex flex-wrap gap-2">
          <button
            v-for="tab in sectionTabs"
            :key="tab"
            type="button"
            class="rounded-full px-4 py-2 text-xs font-bold transition"
            :class="activeSection === tab ? 'bg-brand-600 text-white shadow-sm' : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800'"
            @click="activeSection = tab"
          >
            {{ tab }}
          </button>
        </div>
      </div>

      <div v-if="!filteredItems.length" class="rounded-3xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
        Tidak ada menu yang cocok dengan pencarian ini.
      </div>

      <div v-else class="space-y-7">
        <section
          v-for="section in groupedFilteredSections"
          :key="section.title"
          class="space-y-3"
        >
          <div class="flex items-center gap-3">
            <div class="h-px flex-1 bg-slate-200 dark:bg-slate-800"></div>
            <span class="rounded-full px-3 py-1 text-xs font-black uppercase tracking-[0.2em]" :class="section.profile.chip">
              {{ section.title }}
            </span>
            <div class="h-px flex-1 bg-slate-200 dark:bg-slate-800"></div>
          </div>

          <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-5">
            <RouterLink
              v-for="item in section.items"
              :key="item.to"
              :to="item.to"
              class="group rounded-3xl border border-slate-200 bg-slate-50 p-4 transition hover:-translate-y-0.5 hover:border-brand-300 hover:bg-white hover:shadow-lg dark:border-slate-800 dark:bg-slate-900 dark:hover:border-brand-500/40 dark:hover:bg-slate-900/80"
            >
              <div class="flex items-start justify-between gap-3">
                <div
                  class="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br text-sm font-black text-white shadow-sm"
                  :class="item.profile.tone"
                >
                  <svg class="h-[21px] w-[21px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path :d="iconPath(resolveItemIcon(item))" />
                  </svg>
                </div>
                <span class="rounded-full bg-white px-2.5 py-1 text-[11px] font-bold text-slate-500 ring-1 ring-slate-200 dark:bg-slate-950 dark:text-slate-400 dark:ring-slate-800">
                  Aktif
                </span>
              </div>

              <h4 class="mt-4 font-black text-slate-950 group-hover:text-brand-700 dark:text-white dark:group-hover:text-brand-300">
                {{ item.label }}
              </h4>
              <p class="mt-1 text-xs font-semibold text-slate-500 dark:text-slate-400">{{ item.section }}</p>
              <p class="mt-3 line-clamp-2 text-xs leading-5 text-slate-400">
                {{ item.permission || 'Akses umum' }}
              </p>
            </RouterLink>
          </div>
        </section>
      </div>
    </section>
  </div>
</template>
