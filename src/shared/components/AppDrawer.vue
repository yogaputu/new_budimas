<script setup>
import { useAppStore } from '@/app/stores/app';

defineProps({
  open: {
    type: Boolean,
    default: false
  },
  title: {
    type: String,
    default: ''
  },
  panelClass: {
    type: String,
    default: 'max-w-xl'
  }
});

defineEmits(['close']);

const app = useAppStore();
</script>

<template>
  <div v-if="open" :class="['fixed inset-0 z-50', app.isDark ? 'bg-slate-950/70' : 'bg-slate-950/30']">
    <div
      :class="[
        'absolute inset-y-0 right-0 flex w-full flex-col overflow-hidden shadow-panel',
        app.isDark ? 'border-l border-slate-800 bg-slate-900' : 'bg-white',
        panelClass
      ]"
    >
      <div
        :class="[
          'sticky top-0 z-10 flex items-center justify-between border-b px-6 py-5',
          app.isDark ? 'border-slate-800 bg-slate-900' : 'border-slate-100 bg-white'
        ]"
      >
        <h3 :class="['text-lg font-semibold', app.isDark ? 'text-slate-100' : 'text-slate-900']">{{ title }}</h3>
        <button
          :class="[
            'rounded-full px-2 py-1 transition-colors',
            app.isDark
              ? 'text-slate-500 hover:bg-slate-800 hover:text-slate-200'
              : 'text-slate-400 hover:bg-slate-100 hover:text-slate-700'
          ]"
          @click="$emit('close')"
        >
          X
        </button>
      </div>
      <div class="flex-1 overflow-y-auto px-6 py-5">
        <slot />
      </div>
    </div>
  </div>
</template>
