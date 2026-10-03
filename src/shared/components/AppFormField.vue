<script setup>
import { useAppStore } from '@/app/stores/app';

defineProps({
  label: {
    type: String,
    required: true
  },
  modelValue: {
    type: [String, Number],
    default: ''
  },
  type: {
    type: String,
    default: 'text'
  },
  placeholder: {
    type: String,
    default: ''
  },
  min: {
    type: [String, Number],
    default: undefined
  },
  max: {
    type: [String, Number],
    default: undefined
  },
  step: {
    type: [String, Number],
    default: undefined
  },
  readonly: {
    type: Boolean,
    default: false
  }
});

defineEmits(['update:modelValue']);

const app = useAppStore();
</script>

<template>
  <label class="block">
    <span :class="['mb-1.5 block text-sm font-medium', app.isDark ? 'text-slate-300' : 'text-slate-700']">{{ label }}</span>
    <textarea
      v-if="type === 'textarea'"
      :value="modelValue"
      :placeholder="placeholder"
      :readonly="readonly"
      :class="[
        'min-h-28 w-full rounded-xl px-3 py-2.5 text-sm outline-none transition focus:border-brand-400',
        readonly ? 'cursor-not-allowed opacity-75' : '',
        app.isDark
          ? 'border border-slate-700 bg-slate-950 text-slate-100 placeholder:text-slate-500'
          : 'border border-slate-200 bg-white text-slate-900 placeholder:text-slate-400'
      ]"
      @input="$emit('update:modelValue', $event.target.value)"
    />
    <input
      v-else
      :type="type"
      :value="modelValue"
      :placeholder="placeholder"
      :min="min"
      :max="max"
      :step="step"
      :readonly="readonly"
      :class="[
        'w-full rounded-xl px-3 py-2.5 text-sm outline-none transition focus:border-brand-400',
        readonly ? 'cursor-not-allowed opacity-75' : '',
        app.isDark
          ? 'border border-slate-700 bg-slate-950 text-slate-100 placeholder:text-slate-500'
          : 'border border-slate-200 bg-white text-slate-900 placeholder:text-slate-400'
      ]"
      @input="$emit('update:modelValue', $event.target.value)"
    />
  </label>
</template>
