<script setup>
import { computed, ref, watch } from 'vue';
import { useAppStore } from '@/app/stores/app';

const props = defineProps({
  columns: {
    type: Array,
    default: () => []
  },
  rows: {
    type: Array,
    default: () => []
  },
  loading: {
    type: Boolean,
    default: false
  },
  emptyMessage: {
    type: String,
    default: 'Belum ada data yang bisa ditampilkan.'
  },
  clickableRows: {
    type: Boolean,
    default: false
  },
  paginated: {
    type: Boolean,
    default: true
  },
  defaultPageSize: {
    type: Number,
    default: 15
  },
  pageSizeOptions: {
    type: Array,
    default: () => [10, 15, 25, 50, 100]
  },
  rowKey: {
    type: String,
    default: 'id'
  },
  selectedKey: {
    type: [String, Number],
    default: ''
  }
});

const emit = defineEmits(['row-click']);
const currentPage = ref(1);
const pageSize = ref(props.defaultPageSize);
const app = useAppStore();

const resolvedColumns = computed(() => {
  if (props.columns.length) {
    return props.columns;
  }

  const firstRow = props.rows[0] || {};
  return Object.keys(firstRow)
    .slice(0, 6)
    .map((key) => ({
      key,
      label: key.replace(/_/g, ' ')
    }));
});

const totalRows = computed(() => props.rows.length);
const totalPages = computed(() => {
  if (!props.paginated) return 1;
  return Math.max(1, Math.ceil(totalRows.value / Number(pageSize.value || props.defaultPageSize || 15)));
});
const startRow = computed(() => (currentPage.value - 1) * Number(pageSize.value || props.defaultPageSize || 15));
const endRow = computed(() => Math.min(startRow.value + Number(pageSize.value || props.defaultPageSize || 15), totalRows.value));
const visibleRows = computed(() => {
  if (!props.paginated) return props.rows;
  return props.rows.slice(startRow.value, endRow.value);
});
const showPagination = computed(() => props.paginated && !props.loading && totalRows.value > Number(pageSize.value || props.defaultPageSize || 15));

watch(
  () => props.rows,
  () => {
    currentPage.value = 1;
  }
);

watch(pageSize, () => {
  currentPage.value = 1;
});

watch(
  () => props.selectedKey,
  (selectedKey) => {
    if (!props.paginated || selectedKey === '' || selectedKey === null || selectedKey === undefined) {
      return;
    }

    const selectedIndex = props.rows.findIndex((row, index) => String(getRowKey(row, index)) === String(selectedKey));
    if (selectedIndex === -1) {
      return;
    }

    const size = Number(pageSize.value || props.defaultPageSize || 15);
    currentPage.value = Math.max(1, Math.floor(selectedIndex / size) + 1);
  },
  { immediate: true }
);

function previousPage() {
  currentPage.value = Math.max(1, currentPage.value - 1);
}

function nextPage() {
  currentPage.value = Math.min(totalPages.value, currentPage.value + 1);
}

function renderCell(row, column) {
  if (typeof column.render === 'function') {
    return column.render(row);
  }

  const value = row?.[column.key];
  if (value === null || value === undefined || value === '') {
    return '-';
  }

  return value;
}

function isCellObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) && ('text' in value || 'label' in value);
}

function getCellText(value) {
  if (!isCellObject(value)) {
    return value;
  }
  return value.text ?? value.label ?? '-';
}

function getCellClass(value) {
  if (!isCellObject(value)) {
    return '';
  }
  return value.className || '';
}

function getRowKey(row, index) {
  return row?.[props.rowKey] || row?.id || row?.kode || index;
}

function isSelectedRow(row, index) {
  return props.selectedKey !== '' && String(getRowKey(row, index)) === String(props.selectedKey);
}
</script>

<template>
  <div class="panel overflow-hidden">
    <div class="overflow-x-auto">
      <table :class="['min-w-full divide-y text-sm', app.isDark ? 'divide-slate-800' : 'divide-slate-200']">
        <thead :class="app.isDark ? 'bg-slate-900' : 'bg-slate-50'">
          <tr>
            <th
              v-for="column in resolvedColumns"
              :key="column.key"
              :class="[
                'px-4 py-3 text-left font-medium uppercase tracking-wide',
                app.isDark ? 'text-slate-400' : 'text-slate-500'
              ]"
            >
              <slot :name="`header-${column.key}`" :column="column">{{ column.label }}</slot>
            </th>
          </tr>
        </thead>
        <tbody :class="app.isDark ? 'divide-y divide-slate-800 bg-slate-950' : 'divide-y divide-slate-100 bg-white'">
          <tr v-if="loading">
            <td
              :colspan="resolvedColumns.length || 1"
              :class="['px-4 py-10 text-center', app.isDark ? 'text-slate-400' : 'text-slate-500']"
            >
              Memuat data...
            </td>
          </tr>
          <tr v-else-if="!rows.length">
            <td
              :colspan="resolvedColumns.length || 1"
              :class="['px-4 py-10 text-center', app.isDark ? 'text-slate-400' : 'text-slate-500']"
            >
              {{ emptyMessage }}
            </td>
          </tr>
          <tr
            v-for="(row, index) in visibleRows"
            v-else
            :key="getRowKey(row, index)"
            :class="[
              'transition',
              clickableRows ? 'cursor-pointer' : '',
              app.isDark ? 'hover:bg-slate-900/80' : 'hover:bg-slate-50',
              isSelectedRow(row, index)
                ? (app.isDark ? 'bg-brand-500/10 ring-1 ring-inset ring-brand-500/40' : 'bg-brand-50/80 ring-1 ring-inset ring-brand-200')
                : ''
            ]"
            @click="clickableRows ? emit('row-click', row) : null"
          >
            <td
              v-for="column in resolvedColumns"
              :key="column.key"
              :class="['px-4 py-3 align-top', app.isDark ? 'text-slate-200' : 'text-slate-700']"
            >
              <slot :name="`cell-${column.key}`" :row="row" :column="column">
                <span
                  v-if="isCellObject(renderCell(row, column))"
                  :class="getCellClass(renderCell(row, column))"
                >
                  {{ getCellText(renderCell(row, column)) }}
                </span>
                <template v-else>
                  {{ renderCell(row, column) }}
                </template>
              </slot>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div
      v-if="showPagination"
      :class="[
        'flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3 text-sm',
        app.isDark
          ? 'border-slate-800 bg-slate-900 text-slate-300'
          : 'border-slate-100 bg-slate-50 text-slate-600'
      ]"
    >
      <div>
        Menampilkan
        <span :class="['font-semibold', app.isDark ? 'text-slate-100' : 'text-slate-900']">{{ startRow + 1 }}</span>
        -
        <span :class="['font-semibold', app.isDark ? 'text-slate-100' : 'text-slate-900']">{{ endRow }}</span>
        dari
        <span :class="['font-semibold', app.isDark ? 'text-slate-100' : 'text-slate-900']">{{ totalRows }}</span>
        data
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <label class="flex items-center gap-2">
          <span>Per halaman</span>
          <select
            v-model.number="pageSize"
            :class="[
              'rounded-xl px-2 py-1.5 text-sm outline-none',
              app.isDark
                ? 'border border-slate-700 bg-slate-950 text-slate-100'
                : 'border border-slate-200 bg-white text-slate-900'
            ]"
          >
            <option v-for="option in pageSizeOptions" :key="option" :value="Number(option)">{{ option }}</option>
          </select>
        </label>

        <button
          :class="[
            'rounded-xl px-3 py-1.5 text-sm disabled:opacity-50',
            app.isDark
              ? 'border border-slate-700 bg-slate-950 text-slate-100'
              : 'border border-slate-200 bg-white text-slate-900'
          ]"
          :disabled="currentPage <= 1"
          @click="previousPage"
        >
          Sebelumnya
        </button>
        <span :class="['px-2', app.isDark ? 'text-slate-400' : 'text-slate-500']">Hal {{ currentPage }} / {{ totalPages }}</span>
        <button
          :class="[
            'rounded-xl px-3 py-1.5 text-sm disabled:opacity-50',
            app.isDark
              ? 'border border-slate-700 bg-slate-950 text-slate-100'
              : 'border border-slate-200 bg-white text-slate-900'
          ]"
          :disabled="currentPage >= totalPages"
          @click="nextPage"
        >
          Berikutnya
        </button>
      </div>
    </div>
  </div>
</template>
