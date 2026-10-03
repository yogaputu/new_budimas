<script setup>
import { useAppStore } from '@/app/stores/app';

const app = useAppStore();
</script>

<template>
  <div
    :class="[
      'relative flex min-h-screen items-center justify-center px-4 py-10 transition-colors duration-300',
      app.isDark
        ? 'bg-slate-950'
        : 'bg-gradient-to-br from-slate-50 via-sky-50 to-emerald-50'
    ]"
  >
    <button
      :class="[
        'absolute right-4 top-4 rounded-xl px-3 py-2 text-sm font-medium shadow-sm transition-colors sm:right-6 sm:top-6',
        app.isDark
          ? 'border border-slate-700 bg-slate-900 text-slate-100 hover:bg-slate-800'
          : 'border border-slate-200 bg-white/90 text-slate-700 backdrop-blur hover:bg-white'
      ]"
      @click="app.toggleTheme"
    >
      {{ app.themeLabel }}
    </button>
    <div
      :class="[
        'w-full max-w-md rounded-[22px] px-8 py-10 shadow-[0_30px_60px_-35px_rgba(15,23,42,0.4)] sm:px-10 transition-colors duration-300',
        app.isDark
          ? 'border border-slate-800 bg-slate-900'
          : 'bg-white'
      ]"
    >
      <section class="w-full">
          <RouterView />
      </section>
    </div>
  </div>
</template>
