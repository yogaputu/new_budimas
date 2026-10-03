<script setup>
import { computed, onUnmounted, watch } from 'vue';
import { useAppStore } from '@/app/stores/app';

const props = defineProps({
  open: {
    type: Boolean,
    default: false
  },
  title: {
    type: String,
    default: ''
  },
  description: {
    type: String,
    default: ''
  },
  size: {
    type: String,
    default: 'lg'
  },
  panelClass: {
    type: String,
    default: ''
  },
  closeOnBackdrop: {
    type: Boolean,
    default: true
  },
  hideClose: {
    type: Boolean,
    default: false
  }
});

const emit = defineEmits(['close']);
const app = useAppStore();

const sizeClass = computed(() => {
  const map = {
    sm: 'max-w-md',
    md: 'max-w-lg',
    lg: 'max-w-2xl',
    xl: 'max-w-4xl',
    '2xl': 'max-w-5xl',
    '4xl': 'max-w-6xl',
    '6xl': 'max-w-7xl',
    '7xl': 'max-w-[96rem]',
    full: 'max-w-[calc(100vw-2rem)] h-[calc(100vh-2rem)]'
  };

  return props.panelClass || map[props.size] || map.lg;
});

function close() {
  emit('close');
}

function onBackdropClick() {
  if (props.closeOnBackdrop) {
    close();
  }
}

watch(
  () => props.open,
  (value) => {
    if (typeof document === 'undefined') return;
    document.body.style.overflow = value ? 'hidden' : '';
  },
  { immediate: true }
);

onUnmounted(() => {
  if (typeof document === 'undefined') return;
  document.body.style.overflow = '';
});
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition duration-150 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="open"
        :class="[
          'fixed inset-0 z-[100] flex items-center justify-center overflow-y-auto p-4 backdrop-blur-sm',
          app.isDark ? 'bg-slate-950/80' : 'bg-slate-950/45'
        ]"
        @mousedown.self="onBackdropClick"
      >
        <Transition
          enter-active-class="transition duration-200 ease-out"
          enter-from-class="translate-y-4 scale-95 opacity-0"
          enter-to-class="translate-y-0 scale-100 opacity-100"
          leave-active-class="transition duration-150 ease-in"
          leave-from-class="translate-y-0 scale-100 opacity-100"
          leave-to-class="translate-y-4 scale-95 opacity-0"
        >
          <section
            :class="[
              'flex max-h-[92vh] w-full flex-col overflow-hidden rounded-[28px] shadow-2xl',
              app.isDark
                ? 'border border-slate-800 bg-slate-900 text-slate-100'
                : 'border border-slate-200 bg-white text-slate-900',
              sizeClass
            ]"
          >
            <header
              :class="[
                'flex items-start justify-between gap-4 border-b px-6 py-5',
                app.isDark
                  ? 'border-slate-800 bg-slate-950'
                  : 'border-slate-200 bg-slate-50'
              ]"
            >
              <div>
                <p class="text-xs font-bold uppercase tracking-[0.25em] text-brand-600 dark:text-brand-300">
                  Budimas ERP
                </p>

                <h3
                  :class="[
                    'mt-1 text-xl font-bold',
                    app.isDark ? 'text-white' : 'text-slate-950'
                  ]"
                >
                  {{ title }}
                </h3>

                <p
                  v-if="description"
                  :class="[
                    'mt-1 text-sm',
                    app.isDark ? 'text-slate-400' : 'text-slate-500'
                  ]"
                >
                  {{ description }}
                </p>
              </div>

              <button
                v-if="!hideClose"
                :class="[
                  'rounded-2xl border px-3 py-2 text-sm font-bold transition-colors',
                  app.isDark
                    ? 'border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800 hover:text-white'
                    : 'border-slate-200 bg-white text-slate-500 hover:bg-slate-100 hover:text-slate-900'
                ]"
                @click="close"
              >
                ✕
              </button>
            </header>

            <main class="flex-1 overflow-y-auto px-6 py-5">
              <slot />
            </main>

            <footer
              v-if="$slots.footer"
              :class="[
                'border-t px-6 py-4',
                app.isDark
                  ? 'border-slate-800 bg-slate-950'
                  : 'border-slate-200 bg-slate-50'
              ]"
            >
              <slot name="footer" />
            </footer>
          </section>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>
