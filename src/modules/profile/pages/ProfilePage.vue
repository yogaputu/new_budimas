<script setup>
import { computed, onMounted, ref } from 'vue';
import { useAuthStore } from '@/stores/auth';
import { normalizeError } from '@/utils/api';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const auth = useAuthStore();
const loading = ref(false);
const errorMessage = ref('');

const profileCards = computed(() => {
  const user = auth.user || {};

  return [
    { label: 'Nama', value: user.nama || user.username || '-' },
    { label: 'Username', value: user.username || user.user_name || '-' },
    { label: 'Jabatan', value: auth.roleLabel || '-' },
    { label: 'Cabang', value: auth.branchName || '-' },
    { label: 'Role Scope', value: auth.roleScope || '-' },
    { label: 'Home Route', value: auth.homeRoute || '/' }
  ];
});

const permissionRows = computed(() =>
  (auth.permissions || []).map((permission, index) => ({
    no: index + 1,
    permission
  }))
);

const moduleRows = computed(() =>
  (auth.moduleAccess || []).map((module, index) => ({
    no: index + 1,
    modul: module?.nama || module?.name || module?.kode || JSON.stringify(module)
  }))
);

async function refreshProfile() {
  loading.value = true;
  errorMessage.value = '';

  try {
    await auth.fetchMe();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Profil user belum bisa diperbarui.');
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  if (!auth.user && auth.isAuthenticated) {
    refreshProfile();
  }
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Profil ERP"
      description="Ringkasan identitas login, cabang kerja, role, dan akses sistem user."
    >
      <button
        class="rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200 dark:hover:bg-slate-900"
        :disabled="loading"
        @click="refreshProfile"
      >
        {{ loading ? 'Memuat...' : 'Refresh Profil' }}
      </button>
    </PageHeader>

    <section v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
      {{ errorMessage }}
    </section>

    <section class="overflow-hidden rounded-[32px] border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950">
      <div class="grid gap-0 xl:grid-cols-[0.95fr_1.05fr]">
        <div class="relative overflow-hidden bg-gradient-to-br from-brand-600 via-blue-700 to-slate-950 p-6 text-white sm:p-8">
          <div class="absolute -right-16 -top-16 h-52 w-52 rounded-full bg-white/10 blur-3xl"></div>
          <div class="absolute bottom-0 left-0 h-40 w-40 rounded-full bg-emerald-400/20 blur-3xl"></div>

          <div class="relative">
            <div class="flex items-center gap-4">
              <div class="flex h-20 w-20 items-center justify-center rounded-3xl bg-white/15 text-2xl font-bold shadow-lg">
                {{ (auth.userName || 'U').slice(0, 2).toUpperCase() }}
              </div>

              <div>
                <p class="text-xs font-bold uppercase tracking-[0.3em] text-white/60">User Login</p>
                <h2 class="mt-2 text-2xl font-bold">{{ auth.userName || '-' }}</h2>
                <p class="mt-1 text-sm text-white/70">{{ auth.roleLabel || '-' }}</p>
              </div>
            </div>

            <div class="mt-7 grid gap-3 sm:grid-cols-2">
              <div class="rounded-2xl border border-white/10 bg-white/10 p-4">
                <p class="text-xs uppercase tracking-[0.25em] text-white/60">Cabang</p>
                <p class="mt-2 font-bold text-white">{{ auth.branchName || '-' }}</p>
              </div>

              <div class="rounded-2xl border border-white/10 bg-white/10 p-4">
                <p class="text-xs uppercase tracking-[0.25em] text-white/60">Role Scope</p>
                <p class="mt-2 font-bold text-white">{{ auth.roleScope || '-' }}</p>
              </div>
            </div>
          </div>
        </div>

        <div class="grid gap-4 p-6 sm:grid-cols-2 sm:p-8">
          <article
            v-for="card in profileCards"
            :key="card.label"
            class="rounded-2xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-900"
          >
            <p class="text-xs font-bold uppercase tracking-[0.22em] text-slate-400">{{ card.label }}</p>
            <p class="mt-3 break-words text-base font-bold text-slate-950 dark:text-white">{{ card.value }}</p>
          </article>
        </div>
      </div>
    </section>

    <section class="grid gap-4 md:grid-cols-3">
      <article class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <p class="text-xs font-bold uppercase tracking-[0.25em] text-slate-400">Total Permission</p>
        <p class="mt-3 text-3xl font-bold text-slate-950 dark:text-white">{{ permissionRows.length }}</p>
        <p class="mt-2 text-sm text-slate-500 dark:text-slate-400">Jumlah izin akses yang diterima dari backend.</p>
      </article>

      <article class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <p class="text-xs font-bold uppercase tracking-[0.25em] text-slate-400">Akses Modul</p>
        <p class="mt-3 text-3xl font-bold text-slate-950 dark:text-white">{{ moduleRows.length }}</p>
        <p class="mt-2 text-sm text-slate-500 dark:text-slate-400">Domain kerja yang aktif untuk user ini.</p>
      </article>

      <article class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <p class="text-xs font-bold uppercase tracking-[0.25em] text-slate-400">Landing Page</p>
        <p class="mt-3 text-xl font-bold text-slate-950 dark:text-white">{{ auth.homeRoute || '/' }}</p>
        <p class="mt-2 text-sm text-slate-500 dark:text-slate-400">Halaman default setelah login.</p>
      </article>
    </section>

    <section class="rounded-[32px] border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-950">
      <div class="mb-4">
        <h3 class="text-lg font-bold text-slate-950 dark:text-white">Permission & Akses Modul</h3>
        <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Data teknis role mapping. Digunakan router, navigation, dan validasi akses halaman.
        </p>
      </div>

      <div class="grid gap-6 xl:grid-cols-2">
        <section>
          <div class="mb-3">
            <h4 class="text-base font-bold text-slate-950 dark:text-white">Permission Login</h4>
            <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">Daftar permission mentah dari backend.</p>
          </div>

          <div class="overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-800">
            <AppTable
              :rows="permissionRows"
              :columns="[
                { key: 'no', label: 'No' },
                { key: 'permission', label: 'Permission' }
              ]"
              :loading="loading"
              empty-message="Belum ada permission yang diterima dari backend."
            />
          </div>
        </section>

        <section>
          <div class="mb-3">
            <h4 class="text-base font-bold text-slate-950 dark:text-white">Akses Modul</h4>
            <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">Daftar modul aktif untuk migrasi ERP baru.</p>
          </div>

          <div class="overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-800">
            <AppTable
              :rows="moduleRows"
              :columns="[
                { key: 'no', label: 'No' },
                { key: 'modul', label: 'Modul' }
              ]"
              :loading="loading"
              empty-message="Belum ada daftar akses modul dari backend."
            />
          </div>
        </section>
      </div>
    </section>
  </div>
</template>
