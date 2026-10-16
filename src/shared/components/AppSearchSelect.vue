<script setup>
import { computed, nextTick, onUnmounted, ref, useId, watch } from 'vue';
import { useAppStore } from '@/app/stores/app';

const props = defineProps({
  modelValue: {
    type: [String, Number, Boolean, Array],
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
  optionPageSize: {
    type: Number,
    default: 0
  },
  clearSearchOnOpen: {
    type: Boolean,
    default: false
  },
  clearable: {
    type: Boolean,
    default: true
  },
  ariaLabel: { type: String, default: '' },
  labelledBy: { type: String, default: undefined },
  inputId: { type: String, default: undefined },
  dropdownPortal: { type: Boolean, default: false }
});

const emit = defineEmits(['update:modelValue', 'search', 'focus', 'blur']);
const app = useAppStore();

const open = ref(false);
const search = ref('');
const searchInput = ref(null);
const anchor = ref(null);
const listbox = ref(null);
const dropdownStyle = ref(null);
const activeIndex = ref(-1);
const listId = `search-select-${useId()}`;
const visibleCount = ref(Number(props.optionPageSize) || 0);
let searchTimer = null;
let blurTimer = null;

function updateDropdownPosition() {
  if (!props.dropdownPortal || !open.value || !anchor.value) return;
  const rect = anchor.value.getBoundingClientRect();
  const width = Math.min(rect.width, window.innerWidth - 16);
  const below = window.innerHeight - rect.bottom;
  const above = rect.top;
  const upwards = below < 200 && above > below;
  dropdownStyle.value = {
    position: 'fixed', width: `${width}px`,
    left: `${Math.max(8, Math.min(rect.left, window.innerWidth - width - 8))}px`,
    top: upwards ? 'auto' : `${rect.bottom + 8}px`,
    bottom: upwards ? `${window.innerHeight - rect.top + 8}px` : 'auto',
    maxHeight: `${Math.max(48, Math.min(256, (upwards ? above : below) - 16))}px`
  };
}

function stopPositioning() {
  window.removeEventListener('resize', updateDropdownPosition);
  window.removeEventListener('scroll', updateDropdownPosition, true);
  document.removeEventListener('pointerdown', closeOutside, true);
}

function closeOutside(event) {
  if (anchor.value?.contains(event.target) || listbox.value?.contains(event.target)) return;
  open.value = false;
  search.value = props.multiple ? '' : selectedLabel.value;
}

watch(open, async value => {
  stopPositioning();
  dropdownStyle.value = null;
  if (!value) return;
  document.addEventListener('pointerdown', closeOutside, true);
  if (!props.dropdownPortal) return;
  await nextTick();
  if (!open.value) return;
  updateDropdownPosition();
  window.addEventListener('resize', updateDropdownPosition);
  window.addEventListener('scroll', updateDropdownPosition, true);
});

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

const hasSelection = computed(() => props.multiple ? selectedOptions.value.length > 0 : selectedValues.value.length > 0);

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
  const limit = props.optionPageSize > 0 ? visibleCount.value : Number(props.maxVisibleOptions || 0);
  if (!limit) {
    return filteredOptions.value;
  }
  return filteredOptions.value.slice(0, limit);
});

watch([search, open], () => { visibleCount.value = Number(props.optionPageSize) || 0; activeIndex.value = -1; });
watch(controlDisabled, value => { if (value) open.value = false; });

function interactionDisabled() {
  return controlDisabled.value || searchInput.value?.matches(':disabled');
}

function showMoreOptions() {
  visibleCount.value += Number(props.optionPageSize) || 0;
}

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
  if (interactionDisabled()) return;
  if (!open.value && props.clearSearchOnOpen) search.value = '';
  open.value = true;
  if (props.remoteSearch) {
    scheduleSearch(search.value);
  }
}

function handleControlClick(event) {
  if (interactionDisabled() || event.target?.closest?.('button')) return;
  openDropdown();
  searchInput.value?.focus?.();
}

function toggle() {
  if (interactionDisabled()) return;
  open.value = !open.value;
  if (open.value) {
    search.value = props.multiple || props.clearSearchOnOpen ? '' : selectedLabel.value;
    if (props.remoteSearch) {
      scheduleSearch(search.value);
    }
  }
}

function selectOption(option) {
  if (interactionDisabled() || option.disabled) return;

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
  if (interactionDisabled()) return;
  emit('update:modelValue', props.multiple ? [] : '');
  search.value = '';
  open.value = false;
}

function handleBlur(event) {
  emit('blur', event);
  window.clearTimeout(blurTimer);
  blurTimer = window.setTimeout(() => {
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

function handleFocus(event) {
  window.clearTimeout(blurTimer);
  emit('focus', event);
  openDropdown();
}

function handleInput() {
  // Selecting keeps focus in the search field; typing again must reopen it.
  if (!interactionDisabled()) open.value = true;
}

async function handleKeydown(event) {
  if (interactionDisabled()) return;
  if (event.key === 'Escape' || event.key === 'Tab') {
    if (event.key === 'Escape' && open.value) { event.preventDefault(); event.stopPropagation(); }
    open.value = false;
    search.value = props.multiple ? '' : selectedLabel.value;
    return;
  }
  if (event.key === 'Enter' && open.value) {
    event.preventDefault();
    const option = displayedOptions.value[activeIndex.value] || displayedOptions.value.find(o => !o.disabled);
    if (option) selectOption(option);
    return;
  }
  if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
  event.preventDefault();
  openDropdown();
  await nextTick();
  const options = displayedOptions.value;
  const step = event.key === 'ArrowDown' ? 1 : -1;
  let index = activeIndex.value < 0 && step < 0 ? options.length : activeIndex.value;
  for (let count = 0; count < options.length; count++) {
    index = (index + step + options.length) % options.length;
    if (!options[index].disabled) {
      activeIndex.value = index;
      nextTick(() => listbox.value?.querySelector(`[data-option-index="${index}"]`)?.scrollIntoView({ block: 'nearest' }));
      break;
    }
  }
}

defineExpose({ focus: () => searchInput.value?.focus() });

function optionSelected(option) {
  return selectedValues.value.includes(String(option.value));
}

onUnmounted(() => {
  open.value = false;
  window.clearTimeout(searchTimer);
  window.clearTimeout(blurTimer);
  stopPositioning();
});
</script>

<template>
  <component :is="label ? 'label' : 'div'" class="block min-w-0">
    <span v-if="label" :class="['mb-1 block text-xs font-medium uppercase tracking-wide', app.isDark ? 'text-slate-400' : 'text-slate-500']">{{ label }}</span>

    <div class="relative min-w-0">
      <div
        ref="anchor"
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
          :id="inputId"
          role="combobox"
          :aria-label="ariaLabel || label || undefined"
          :aria-labelledby="labelledBy"
          :aria-expanded="open"
          :aria-controls="listId"
          :aria-activedescendant="activeIndex >= 0 && open ? `${listId}-${activeIndex}` : undefined"
          aria-autocomplete="list"
          autocomplete="off"
          :placeholder="multiple && selectedOptions.length ? 'Cari lagi' : placeholder"
          :disabled="controlDisabled"
          :class="[
            multiple ? 'min-w-[120px] flex-1' : 'w-full min-w-0 truncate',
            'border-0 bg-transparent p-0 text-sm outline-none ring-0',
            controlDisabled ? 'cursor-not-allowed' : '',
            app.isDark ? 'text-slate-100 placeholder:text-slate-500' : 'text-slate-900 placeholder:text-slate-400'
          ]"
          @focus="handleFocus"
          @input="handleInput"
          @blur="handleBlur"
          @keydown="handleKeydown"
        />

        <button
          v-if="hasSelection && clearable"
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

      <Teleport to="body" :disabled="!dropdownPortal">
      <div
        v-if="open && (!dropdownPortal || dropdownStyle)"
        ref="listbox"
        :id="listId"
        role="listbox"
        :aria-multiselectable="multiple || undefined"
        :style="dropdownPortal ? dropdownStyle : undefined"
        :class="[
          'z-[9999] max-h-64 overflow-auto rounded-2xl p-2 shadow-xl',
          dropdownPortal ? 'fixed' : 'absolute mt-2 w-full',
          app.isDark
            ? 'border border-slate-700 bg-slate-900'
            : 'border border-slate-200 bg-white'
        ]"
      >
        <button
          v-for="(option, index) in displayedOptions"
          :key="option.value"
          :id="`${listId}-${index}`"
          role="option"
          tabindex="-1"
          :aria-selected="optionSelected(option)"
          :disabled="controlDisabled || option.disabled"
          :data-option-index="index"
          :title="option.label"
          type="button"
          :class="[
            'flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm transition-colors',
            option.disabled ? 'cursor-not-allowed opacity-50' : '',
            activeIndex === index ? app.isDark ? 'bg-slate-800' : 'bg-slate-100' : '',
            app.isDark
              ? 'text-slate-100 hover:bg-slate-800'
              : 'text-slate-700 hover:bg-slate-50'
          ]"
          @mousedown.prevent
          @click="selectOption(option)"
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
        <button v-if="optionPageSize > 0 && displayedOptions.length < filteredOptions.length" type="button"
          :class="['mt-1 w-full rounded-xl px-3 py-3 text-left text-sm font-semibold', app.isDark ? 'text-brand-200 hover:bg-slate-800' : 'text-brand-700 hover:bg-brand-50']"
          @mousedown.prevent @click="showMoreOptions">
          Tampilkan {{ optionPageSize }} berikutnya · {{ displayedOptions.length.toLocaleString('id-ID') }} / {{ filteredOptions.length.toLocaleString('id-ID') }} pilihan
        </button>
      </div>
      </Teleport>
    </div>
  </component>
</template>
