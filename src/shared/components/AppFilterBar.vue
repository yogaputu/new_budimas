<script setup>
import { computed } from 'vue';
import { useAppStore } from '@/app/stores/app';
import AppSearchSelect from './AppSearchSelect.vue';

const props = defineProps({
  modelValue: {
    type: Object,
    required: true
  },
  fields: {
    type: Array,
    default: () => []
  }
});

const emit = defineEmits(['update:modelValue', 'submit', 'reset']);
const app = useAppStore();

function isCompanyField(field) {
  const label = String(field?.label || '').toLowerCase();
  const key = String(field?.key || '').toLowerCase();
  return label.includes('perusahaan') || key.includes('company') || key.includes('perusahaan');
}

function isBranchField(field) {
  const label = String(field?.label || '').toLowerCase();
  const key = String(field?.key || '').toLowerCase();
  return label.includes('cabang') || key.includes('branch') || key.includes('cabang');
}

const orderedFields = computed(() => {
  const fields = [...props.fields];
  const companyIndex = fields.findIndex(isCompanyField);
  const branchIndex = fields.findIndex(isBranchField);

  if (companyIndex >= 0 && branchIndex >= 0 && branchIndex < companyIndex) {
    const [companyField] = fields.splice(companyIndex, 1);
    const nextBranchIndex = fields.findIndex(isBranchField);
    fields.splice(nextBranchIndex, 0, companyField);
  }

  return fields;
});

function updateField(key, value) {
  emit('update:modelValue', {
    ...props.modelValue,
    [key]: value
  });
}

function withAllOption(field) {
  const options = field.options || [];
  if (field.disableAllOption) return options;
  if (options.some((option) => String(option.value ?? '') === '')) return options;

  const label = field.allLabel || `Semua ${String(field.label || '').toLowerCase()}`.trim();
  return [{ value: '', label }, ...options];
}

function searchSelectPlaceholder(field) {
  if (field.placeholder) return field.placeholder;

  const label = String(field.label || 'data').trim().toLowerCase();
  return `Cari ${label}`;
}
</script>

<template>
  <div class="panel-muted min-w-0 p-4">
    <div class="grid min-w-0 gap-3 [grid-template-columns:repeat(auto-fit,minmax(220px,1fr))]">
      <div v-for="field in orderedFields" :key="field.key" :class="field.wrapperClass || 'block'">
        <span :class="['mb-1 block text-xs font-medium uppercase tracking-wide', app.isDark ? 'text-slate-400' : 'text-slate-500']">{{ field.label }}</span>
        <input
          v-if="field.type !== 'select' && field.type !== 'search-select'"
          :type="field.type || 'text'"
          :aria-label="field.label"
          :placeholder="field.placeholder || ''"
          :value="modelValue[field.key] || ''"
          :disabled="field.disabled"
          :class="field.inputClass || [
            'w-full rounded-xl px-3 py-2.5 text-sm outline-none ring-0 transition focus:border-brand-400',
            app.isDark
              ? 'border border-slate-700 bg-slate-950 text-slate-100 placeholder:text-slate-500'
              : 'border border-slate-200 bg-white text-slate-900 placeholder:text-slate-400'
          ]"
          @input="updateField(field.key, $event.target.value)"
        />
        <AppSearchSelect
          v-else-if="field.type === 'search-select'"
          :model-value="field.multiple ? (modelValue[field.key] || []) : (modelValue[field.key] || '')"
          :options="withAllOption(field)"
          :multiple="Boolean(field.multiple)"
          :placeholder="searchSelectPlaceholder(field)"
          :empty-text="field.emptyText || 'Data belum tersedia.'"
          :disabled="field.disabled"
          :loading="field.loading"
          :display-value="field.displayValue || ''"
          @update:model-value="updateField(field.key, $event)"
        />
        <select
          v-else
          :value="modelValue[field.key] || ''"
          :disabled="field.disabled"
          :class="field.inputClass || [
            'w-full rounded-xl px-3 py-2.5 text-sm outline-none ring-0 transition focus:border-brand-400',
            app.isDark
              ? 'border border-slate-700 bg-slate-950 text-slate-100'
              : 'border border-slate-200 bg-white text-slate-900'
          ]"
          @change="updateField(field.key, $event.target.value)"
        >
          <option value="">{{ field.allLabel || `Semua ${String(field.label || '').toLowerCase()}`.trim() }}</option>
          <option v-for="option in field.options || []" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </div>
    </div>
    <div class="mt-4 flex flex-wrap gap-2">
      <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700" @click="$emit('submit')">
        Terapkan
      </button>
      <button :class="[
        'rounded-xl px-4 py-2 text-sm transition-colors',
        app.isDark
          ? 'border border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800'
          : 'border border-slate-200 text-slate-600 hover:bg-slate-50'
      ]" @click="$emit('reset')">
        Reset
      </button>
    </div>
  </div>
</template>
