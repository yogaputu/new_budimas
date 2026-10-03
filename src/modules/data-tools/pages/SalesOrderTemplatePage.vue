<script setup>
import { computed, ref } from 'vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import { orderTemplateColumns, orderTemplateExamples, orderTemplateRules, salesOrderTemplate } from '../salesOrderTemplate';

const search = ref('');
const templateUrl = `${import.meta.env.BASE_URL}${salesOrderTemplate.assetPath}`;
const visibleColumns = computed(() => {
  const term = search.value.trim().toLowerCase();
  return orderTemplateColumns.filter((column) =>
    `${column.key} ${column.description} ${column.scope}`.toLowerCase().includes(term)
  );
});
</script>

<template>
  <div class="sales-order-template">
  <PageHeader
    title="Template Order Sales"
    description="Ekspor template Excel untuk menyiapkan order customer dari sales atau admin berdasarkan data SQL Server yang sudah dipilah."
  >
    <RouterLink class="btn-secondary" to="/data-tools/import-download">Import / Download Data</RouterLink>
    <a class="btn-primary" :href="templateUrl" :download="salesOrderTemplate.fileName">Ekspor Template Excel (.xlsx)</a>
  </PageHeader>

  <section class="card">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h2 class="text-lg font-bold text-[var(--color-text)]">Contoh pengisian order</h2>
      <span class="rounded-full bg-[var(--color-primary-soft)] px-3 py-1 text-xs font-semibold text-[var(--color-primary)]">
        Versi {{ salesOrderTemplate.version }} · {{ orderTemplateColumns.length }} kolom
      </span>
    </div>
    <p class="mt-2 text-sm leading-6 text-[var(--color-text-muted)]">
      File berisi sheet <strong>Data_Order</strong> dengan 4 baris contoh untuk 3 order dan 3 customer,
      serta sheet <strong>Panduan</strong> berisi aturan dan penjelasan setiap kolom.
      Ganti semua data contoh sebelum digunakan. Satu baris mewakili satu produk dalam order.
    </p>
    <div class="mt-4 overflow-x-auto">
      <table class="w-full min-w-[820px] text-left text-sm">
        <thead class="bg-[var(--color-surface-muted)] text-[var(--color-text-muted)]">
          <tr>
            <th class="px-3 py-3">No. order</th><th class="px-3 py-3">Customer</th>
            <th class="px-3 py-3">Sales pemilik</th><th class="px-3 py-3">Asal / penginput</th>
            <th class="px-3 py-3">Produk</th><th class="px-3 py-3">Jumlah</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-[var(--color-border)] text-[var(--color-text)]">
          <tr v-for="row in orderTemplateExamples" :key="row.source_detail_id">
            <td class="whitespace-nowrap px-3 py-3 font-medium">{{ row.no_order }}</td>
            <td class="px-3 py-3">{{ row.nama_customer }}</td>
            <td class="px-3 py-3">{{ row.nama_sales }}</td>
            <td class="px-3 py-3">{{ row.sumber_order }}<span class="block text-xs text-[var(--color-text-muted)]">{{ row.kode_penginput }}</span></td>
            <td class="px-3 py-3">{{ row.nama_produk }}</td>
            <td class="whitespace-nowrap px-3 py-3">{{ row.qty_pcs }} pcs / {{ row.qty_box }} box / {{ row.qty_karton }} karton</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="mt-4 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
      {{ salesOrderTemplate.status }}
    </p>
  </section>

  <section class="card mt-6">
    <h2 class="text-lg font-bold text-[var(--color-text)]">Panduan menyiapkan data</h2>
    <dl class="mt-4 grid gap-4 lg:grid-cols-2">
      <div v-for="[title, description] in orderTemplateRules.slice(1, -1)" :key="title" class="rounded-xl border border-[var(--color-border)] p-4">
        <dt class="font-semibold text-[var(--color-text)]">{{ title }}</dt>
        <dd class="mt-2 text-sm leading-6 text-[var(--color-text-muted)]">{{ description }}</dd>
      </div>
    </dl>
  </section>

  <section class="card mt-6">
    <div class="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
      <h2 class="text-lg font-bold text-[var(--color-text)]">Kolom dalam Excel</h2>
      <label class="text-sm text-[var(--color-text-muted)]">
        Cari kolom
        <input v-model="search" type="search" class="ml-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-[var(--color-text)]" placeholder="Customer, sales, qty…" />
      </label>
    </div>
    <div class="mt-4 overflow-x-auto">
      <table class="w-full min-w-[740px] text-left text-sm">
        <thead class="bg-[var(--color-surface-muted)] text-[var(--color-text-muted)]">
          <tr><th class="px-3 py-3">Kolom / tipe</th><th class="px-3 py-3">Pengisian</th><th class="px-3 py-3">Contoh</th><th class="px-3 py-3">Penjelasan</th></tr>
        </thead>
        <tbody class="divide-y divide-[var(--color-border)] text-[var(--color-text)]">
          <tr v-for="column in visibleColumns" :key="column.key">
            <td class="px-3 py-3 align-top"><code>{{ column.key }}</code><span class="mt-1 block text-xs text-[var(--color-text-muted)]">{{ column.type }} · {{ column.scope }}</span></td>
            <td class="px-3 py-3 align-top">{{ column.required }}</td>
            <td class="whitespace-nowrap px-3 py-3 align-top">{{ orderTemplateExamples[0][column.key] }}</td>
            <td class="min-w-[280px] px-3 py-3 align-top leading-6 text-[var(--color-text-muted)]">{{ column.description }}</td>
          </tr>
          <tr v-if="!visibleColumns.length"><td colspan="4" class="px-3 py-6 text-center text-[var(--color-text-muted)]">Kolom tidak ditemukan.</td></tr>
        </tbody>
      </table>
    </div>
  </section>
  </div>
</template>

<style scoped>
.sales-order-template {
  --color-text: #0f172a;
  --color-text-muted: #64748b;
  --color-border: #e2e8f0;
  --color-surface: #ffffff;
  --color-surface-muted: #f8fafc;
  --color-primary: #1d4ed8;
  --color-primary-soft: #eff6ff;
}

:global(:root[data-theme='dark'] .sales-order-template) {
  --color-text: #e2e8f0;
  --color-text-muted: #94a3b8;
  --color-border: #334155;
  --color-surface: #0f172a;
  --color-surface-muted: #1e293b;
  --color-primary: #93c5fd;
  --color-primary-soft: #172554;
}

.card {
  @apply rounded-2xl border p-5 shadow-panel;
  background: var(--color-surface);
  border-color: var(--color-border);
}

.btn-secondary {
  color: var(--color-text);
  border-color: var(--color-border);
}
</style>
