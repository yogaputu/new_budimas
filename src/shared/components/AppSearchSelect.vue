<script setup>
import { computed, onUnmounted, ref, watch } from 'vue';
import { useAppStore } from '@/app/stores/app';

const props = defineProps({
  modelValue: {
    type: [String, Number, Array],
    default: ''
  },
  options: {
    type: Array,
    default: () => []
  },
  multiple: {
    type: Boolean,
    default: false
  },
  label: {
    type: String,
    default: ''
  },
  placeholder: {
    type: String,
    default: 'Pilih data'
  },
  emptyText: {
    type: String,
    default: 'Data tidak ditemukan.'
  },
  disabled: {
    type: Boolean,
    default: false
  },
  loading: {
    type: Boolean,
    default: false
  },
  displayValue: {
    type: String,
    default: ''
  },
  remoteSearch: {
    type: Boolean,
    default: false
  },
  searchDebounceMs: {
    type: Number,
    default: 300
  },
  maxVisibleOptions: {
    type: Number,
    default: 0
  },
  clearSearchOnOpen: {
    type: Boolean,
    default: false
  }
});

const emit = defineEmits(['update:modelValue', 'search']);
const app = useAppStore();

const open = ref(false);
const search = ref('');
const searchInput = ref(null);
let searchTimer = null;

const controlDisabled = computed(() => props.disabled || (!props.remoteSearch && props.loading));

const selectedValues = computed(() => {
  if (!props.multiple) {
    return props.modelValue === null || props.modelValue === undefined || props.modelValue === ''
      ? []
      : [String(props.modelValue)];
  }

  if (Array.isArray(props.modelValue)) {
    return props.modelValue.map((value) => String(value)).filter(Boolean);
  }

  return String(props.modelValue || '')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);
});

const selectedOption = computed(() => {
  if (props.modelValue === null || props.modelValue === undefined || props.modelValue === '') {
    return null;
  }
  return props.options.find((option) => String(option.value) === String(props.modelValue));
});

const selectedOptions = computed(() =>
  props.options.filter((option) => selectedValues.value.includes(String(option.value)))
);

const hasSelection = computed(() => props.multiple ? selectedOptions.value.length > 0 : Boolean(props.modelValue));

const selectedLabel = computed(() => {
  if (props.displayValue) return props.displayValue;
  if (!props.multiple) return selectedOption.value?.label || '';

  const labels = selectedOptions.value.map((option) => option.label).filter(Boolean);
  if (!labels.length) return '';
  if (labels.length <= 2) return labels.join(', ');
  return `${labels.length} dipilih`;
});

function normalizedSearchText(value = '') {
  return String(value || '')
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, '');
}

const filteredOptions = computed(() => {
  const keyword = search.value.trim().toLowerCase();
  const normalizedKeyword = normalizedSearchText(keyword);

  if (!keyword) {
    return props.options;
  }

  // Keep stale remote rows out of view while the debounced server search is running.
  return props.options.filter((option) => {
    const label = String(option.label || '');
    return label.toLowerCase().includes(keyword)
      || (normalizedKeyword.length > 0 && normalizedSearchText(label).includes(normalizedKeyword));
  });
});
const displayedOptions = computed(() => {
  const limit = Number(props.maxVisibleOptions || 0);
  if (!limit) {
    return filteredOptions.value;
  }
  return filteredOptions.value.slice(0, limit);
});

watch(
  () => props.modelValue,
  () => {
    search.value = props.multiple ? '' : selectedLabel.value;
  },
  { immediate: true }
);

watch(
  selectedLabel,
  (label) => {
    if (!props.multiple && !open.value) {
      search.value = label || '';
    }
  }
);

watch(search, (value) => {
  if (!props.remoteSearch || !open.value) {
    return;
  }
  scheduleSearch(value);
});

function scheduleSearch(value = '') {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => {
    emit('search', String(value || '').trim());
  }, Number(props.searchDebounceMs || 300));
}

function openDropdown() {
  if (controlDisabled.value) return;
  if (!open.value && props.clearSearchOnOpen) search.value = '';
  open.value = true;
  if (props.remoteSearch) {
    scheduleSearch(search.value);
  }
}

function handleControlClick(event) {
  if (controlDisabled.value || event.target?.closest?.('button')) return;
  openDropdown();
  searchInput.value?.focus?.();
}

function toggle() {
  if (controlDisabled.value) return;
  open.value = !open.value;
  if (open.value) {
    search.value = props.multiple || props.clearSearchOnOpen ? '' : selectedLabel.value;
    if (props.remoteSearch) {
      scheduleSearch(search.value);
    }
  }
}

function selectOption(option) {
  if (controlDisabled.value) return;

  if (props.multiple) {
    const optionValue = String(option.value);
    if (!optionValue) {
      emit('update:modelValue', []);
      search.value = '';
      open.value = false;
      return;
    }

    const isSelected = selectedValues.value.includes(optionValue);
    const nextValues = isSelected
      ? selectedValues.value.filter((value) => value !== optionValue)
      : [...selectedValues.value, option.value];

    emit('update:modelValue', nextValues);
    search.value = '';
    open.value = true;
    return;
  }

  emit('update:modelValue', option.value);
  search.value = option.label;
  open.value = false;
}

function clearValue() {
  if (controlDisabled.value) return;
  emit('update:modelValue', props.multiple ? [] : '');
  search.value = '';
  open.value = false;
}

function handleBlur() {
  window.setTimeout(() => {
    if (props.multiple) {
      search.value = '';
      open.value = false;
      return;
    }

    if (!selectedOption.value) {
      search.value = props.displayValue || '';
    } else {
      search.value = selectedLabel.value;
    }
    open.value = false;
  }, 150);
}

function handleFocus() {
  openDropdown();
}

function optionSelected(option) {
  return selectedValues.value.includes(String(option.value));
}

onUnmounted(() => {
  window.clearTimeout(searchTimer);
});
</script>

<template>
  <label class="block">
    <span v-if="label" :class="['mb-1 block text-xs font-medium uppercase tracking-wide', app.isDark ? 'text-slate-400' : 'text-slate-500']">{{ label }}</span>

    <div class="relative min-w-0">
      <div
        :class="[
          'flex min-h-[46px] min-w-0 items-center gap-2 rounded-xl px-3 py-2.5',
          multiple ? 'flex-wrap' : '',
          controlDisabled ? 'cursor-not-allowed opacity-70' : '',
          app.isDark
            ? 'border border-slate-700 bg-slate-950'
            : 'border border-slate-200 bg-white'
        ]"
        @click="handleControlClick"
      >
        <template v-if="multiple && selectedOptions.length">
          <span
            v-for="option in selectedOptions.slice(0, 2)"
            :key="option.value"
            :class="[
              'max-w-[180px] truncate rounded-lg px-2 py-1 text-xs font-semibold',
              app.isDark ? 'bg-slate-800 text-slate-100' : 'bg-slate-100 text-slate-700'
            ]"
          >
            {{ option.label }}
          </span>
          <span
            v-if="selectedOptions.length > 2"
            :class="[
              'rounded-lg px-2 py-1 text-xs font-bold',
              app.isDark ? 'bg-brand-500/20 text-brand-200' : 'bg-brand-50 text-brand-700'
            ]"
          >
            +{{ selectedOptions.length - 2 }}
          </span>
        </template>

        <input
          ref="searchInput"
          v-model="search"
          type="text"
          :placeholder="multiple && selectedOptions.length ? 'Cari lagi' : placeholder"
          :disabled="controlDisabled"
          :class="[
            multiple ? 'min-w-[120px] flex-1' : 'w-full min-w-0 truncate',
            'border-0 bg-transparent p-0 text-sm outline-none ring-0',
            controlDisabled ? 'cursor-not-allowed' : '',
            app.isDark ? 'text-slate-100 placeholder:text-slate-500' : 'text-slate-900 placeholder:text-slate-400'
          ]"
          @focus="handleFocus"
          @blur="handleBlur"
        />

        <button
          v-if="hasSelection"
          type="button"
          :disabled="controlDisabled"
          :class="[
            'shrink-0 text-xs font-semibold uppercase tracking-wide transition-colors',
            app.isDark ? 'text-slate-500 hover:text-slate-200' : 'text-slate-400 hover:text-slate-700'
          ]"
          @click="clearValue"
          @mousedown.prevent
        >
          Reset
        </button>

        <button
          type="button"
          :disabled="controlDisabled"
          :class="[
            'shrink-0 text-xs font-semibold uppercase tracking-wide transition-colors',
            app.isDark ? 'text-slate-500 hover:text-slate-200' : 'text-slate-400 hover:text-slate-700'
          ]"
          @click="toggle"
          @mousedown.prevent
        >
          Pilih
        </button>
      </div>

      <div
        v-if="open"
        :class="[
          'absolute z-[9999] mt-2 max-h-64 w-full overflow-auto rounded-2xl p-2 shadow-xl',
          app.isDark
            ? 'border border-slate-700 bg-slate-900'
            : 'border border-slate-200 bg-white'
        ]"
      >
        <button
          v-for="option in displayedOptions"
          :key="option.value"
          type="button"
          :class="[
            'flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm transition-colors',
            app.isDark
              ? 'text-slate-100 hover:bg-slate-800'
              : 'text-slate-700 hover:bg-slate-50'
          ]"
          @mousedown.prevent="selectOption(option)"
        >
          <span
            v-if="multiple"
            :class="[
              'flex h-4 w-4 shrink-0 items-center justify-center rounded border',
              optionSelected(option)
                ? app.isDark ? 'border-brand-400 bg-brand-500' : 'border-brand-600 bg-brand-600'
                : app.isDark ? 'border-slate-600' : 'border-slate-300'
            ]"
          >
            <span v-if="optionSelected(option)" class="h-2 w-2 rounded-sm bg-white"></span>
          </span>
          <span class="min-w-0 flex-1 truncate">{{ option.label }}</span>
        </button>

        <div v-if="!displayedOptions.length" :class="['px-3 py-2 text-sm', app.isDark ? 'text-slate-500' : 'text-slate-400']">
          {{ loading ? 'Memuat...' : emptyText }}
        </div>
      </div>
    </div>
  </label>
</template>
