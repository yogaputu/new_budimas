<script setup>
defineProps({
  title: {
    type: String,
    required: true
  },
  description: {
    type: String,
    default: ''
  }
});
</script>

<template>
  <div class="mb-6 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
    <div>
      <h1 class="page-title">{{ title }}</h1>
      <p class="page-subtitle">{{ description }}</p>
    </div>
    <div v-if="$slots.actions || $slots.default" class="flex flex-wrap items-center gap-2">
      <slot name="actions">
        <slot />
      </slot>
    </div>
  </div>
</template>
