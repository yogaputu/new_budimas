import { computed, onScopeDispose, reactive, ref, watch } from 'vue';
import { normalizeError, normalizeList, unwrapResponse } from '../utils/api.js';
import { MAX_DRAFT_NOTES, draftOrderId, draftEligibilityError, draftSelectionError, notaDateRangeError } from '../utils/shipmentDraft.js';

// Keep server pagination separate from selection: notes on other pages stay selected.
export function useShipmentNotePicker(fetchOrders, getScope) {
  const filters = reactive({ dateFrom: '', dateTo: '', search: '' });
  const rows = ref([]), selected = ref({}), loading = ref(false);
  const error = ref(''), selectionMessage = ref(''), loadedKey = ref('');
  const pagination = reactive({ page: 1, totalPages: 1, total: 0 });
  const filterKey = computed(() => JSON.stringify([getScope(), filters]));
  const selectedRows = computed(() => Object.values(selected.value));
  const selectionProblem = computed(() => selectedRows.value.length ? draftSelectionError(selectedRows.value) : '');
  const ready = computed(() => !loading.value && !error.value && loadedKey.value === filterKey.value);
  const eligibleRows = computed(() => rows.value.filter(row => !draftEligibilityError(row)));
  const allChecked = computed(() => eligibleRows.value.length > 0 && eligibleRows.value.every(row => selected.value[draftOrderId(row)]));
  const someChecked = computed(() => !allChecked.value && eligibleRows.value.some(row => selected.value[draftOrderId(row)]));
  let requestId = 0, disposed = false;

  function clearSelection() { selected.value = {}; selectionMessage.value = ''; }
  function invalidate() {
    requestId++;
    loading.value = false;
    rows.value = [];
    loadedKey.value = '';
    error.value = '';
    Object.assign(pagination, { page: 1, totalPages: 1, total: 0 });
    clearSelection();
  }
  watch(filterKey, invalidate, { flush: 'sync' });
  onScopeDispose(() => { disposed = true; requestId++; });

  async function load(page = 1) {
    const currentRequest = ++requestId, key = filterKey.value;
    const { companyId, branchId } = getScope();
    error.value = notaDateRangeError(filters.dateFrom, filters.dateTo) ||
      (!companyId || !branchId ? 'Pilih perusahaan dan cabang terlebih dahulu.' : '');
    if (error.value) { loading.value = false; loadedKey.value = ''; rows.value = []; clearSelection(); return; }
    loading.value = true;
    try {
      const response = await fetchOrders({
        id_perusahaan: companyId, id_cabang: branchId,
        status: 1, date_from: filters.dateFrom || undefined, date_to: filters.dateTo || undefined,
        search: filters.search.trim() || undefined, page: Math.max(1, Number(page) || 1), per_page: 50
      });
      if (disposed || currentRequest !== requestId || key !== filterKey.value) return;
      const payload = unwrapResponse(response) || {};
      const source = normalizeList(payload);
      // Fail closed even if an old API ignores the status/company/branch filters.
      rows.value = source.filter(row => row.status_order != null && Number(row.status_order) === 1 &&
        String(row.id_perusahaan) === String(companyId) && String(row.id_cabang) === String(branchId));
      const next = { ...selected.value };
      for (const row of source) {
        const id = draftOrderId(row);
        if (!next[id]) continue;
        if (!rows.value.includes(row) || draftEligibilityError(row)) delete next[id];
        else next[id] = row;
      }
      selected.value = next;
      const meta = payload.pagination || {};
      pagination.page = Math.max(1, Number(meta.page || page) || 1);
      pagination.total = Math.max(0, Number(meta.total ?? source.length) || 0);
      pagination.totalPages = Math.max(1, Number(meta.total_pages) || Math.ceil(pagination.total / 50));
      loadedKey.value = key;
    } catch (cause) {
      if (disposed || currentRequest !== requestId || key !== filterKey.value) return;
      error.value = normalizeError(cause, 'Nota terkonfirmasi belum dapat dimuat. Klik Terapkan untuk mencoba kembali.');
      rows.value = [];
      loadedKey.value = '';
    } finally {
      if (!disposed && currentRequest === requestId) loading.value = false;
    }
  }

  function selectRows(candidates, checked) {
    if (!ready.value) return;
    const next = { ...selected.value };
    for (const row of candidates) {
      const id = draftOrderId(row);
      if (!checked) delete next[id];
      else if (rows.value.includes(row) && !draftEligibilityError(row)) next[id] = row;
    }
    if (Object.keys(next).length > MAX_DRAFT_NOTES) {
      selectionMessage.value = `Maksimal ${MAX_DRAFT_NOTES} nota per draf. Pilihan tambahan dibatalkan.`;
      return;
    }
    selected.value = next;
    selectionMessage.value = '';
  }
  function reset() { Object.assign(filters, { dateFrom: '', dateTo: '', search: '' }); invalidate(); return load(); }

  return { filters, rows, selected, selectedRows, loading, error, selectionMessage, selectionProblem,
    pagination, ready, eligibleRows, allChecked, someChecked, load, selectRows, clearSelection, reset };
}
