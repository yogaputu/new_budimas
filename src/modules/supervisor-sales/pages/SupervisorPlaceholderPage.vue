<script setup>
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import AppEmptyState from '@/shared/components/AppEmptyState.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const route = useRoute();

const title = computed(() => route.meta?.pageTitle || 'Supervisor Sales');
const description = computed(
  () =>
    route.meta?.pageDescription ||
    'Halaman supervisor sales ini sudah disiapkan sebagai landing area modul berikutnya.'
);
</script>

<template>
  <div class="space-y-6">
    <PageHeader :title="title" :description="description" />

    <section class="grid gap-4 md:grid-cols-3">
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Status Modul</p>
        <p class="mt-3 text-2xl font-bold text-slate-950">Siap Diteruskan</p>
        <p class="mt-2 text-sm text-slate-500">Struktur route dan menu sudah aktif di new-budimas.</p>
      </article>

      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Arah Berikutnya</p>
        <p class="mt-3 text-2xl font-bold text-slate-950">Hook API</p>
        <p class="mt-2 text-sm text-slate-500">Tinggal sambungkan data lama sesuai kebutuhan supervisor.</p>
      </article>

      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Mode Implementasi</p>
        <p class="mt-3 text-2xl font-bold text-slate-950">Bertahap</p>
        <p class="mt-2 text-sm text-slate-500">UI, filter, tabel, dan aksi bisa dilanjutkan modul per modul.</p>
      </article>
    </section>

    <AppEmptyState
      :title="title"
      description="Halaman ini saya siapkan dulu sebagai fondasi supervisor sales. Kalau Anda mau, modul ini bisa jadi target berikutnya setelah Kunjungan Sales."
    />
  </div>
</template>
