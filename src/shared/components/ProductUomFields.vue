<script setup>
import { productUoms, productUomLabel } from '@/utils/productUom';
defineProps({ product: { type: Object, default: () => ({}) }, values: { type: Object, default: () => ({}) }, prefix: { type: String, default: 'qty_uom' }, disabled: Boolean });
defineEmits(['change']);
</script>
<template>
  <div class="grid min-w-0 gap-3" style="grid-template-columns: repeat(auto-fit, minmax(min(100%, 120px), 1fr))">
    <label v-for="unit in productUoms(product)" :key="unit.id || unit.level" class="block min-w-0">
      <span class="mb-1 block break-words text-xs font-semibold text-slate-500 dark:text-slate-400">{{ productUomLabel(product, unit.level) }}</span>
      <input :value="values[`${prefix}${unit.level}`] || 0" :disabled="disabled" :aria-label="`${product.nama_produk || product.nama || ''} — ${unit.nama}`"
        type="number" min="0" step="1" inputmode="numeric"
        class="w-full min-w-0 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-950 outline-none focus:border-brand-400 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
        @input="$emit('change', { level: unit.level, value: $event.target.value })" />
    </label>
    <p v-if="!productUoms(product).length" class="text-xs text-rose-600 dark:text-rose-300">Master UOM belum tersedia.</p>
  </div>
</template>
