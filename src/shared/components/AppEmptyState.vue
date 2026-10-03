<script setup>
import { useAppStore } from '@/app/stores/app';

defineProps({
  title: {
    type: String,
    default: 'Belum ada data'
  },
  description: {
    type: String,
    default: 'Silakan ubah filter atau lakukan input baru.'
  }
});

const app = useAppStore();
</script>

<template>
  <div class="panel flex flex-col items-center justify-center px-6 py-12 text-center">
    <div :class="['flex h-16 w-16 items-center justify-center rounded-2xl', app.isDark ? 'bg-brand-500/15 text-brand-300' : 'bg-brand-50 text-brand-700']">0</div>
    <h3 :class="['mt-4 text-lg font-semibold', app.isDark ? 'text-slate-100' : 'text-slate-900']">{{ title }}</h3>
    <p :class="['mt-2 max-w-md text-sm', app.isDark ? 'text-slate-400' : 'text-slate-500']">{{ description }}</p>
  </div>
</template>
