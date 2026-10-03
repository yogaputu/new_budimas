import { ref } from 'vue';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';

export function useRemoteCollection(fetcher, options = {}) {
  const items = ref([]);
  const loading = ref(false);
  const error = ref('');

  async function load(params = {}) {
    loading.value = true;
    error.value = '';

    try {
      const sanitizedParams = Object.fromEntries(
        Object.entries(params || {}).filter(([, value]) => value !== '' && value !== null && value !== undefined)
      );
      const response = await fetcher(sanitizedParams);
      const payload = unwrapResponse(response);
      items.value = options.transform ? options.transform(payload) : normalizeList(payload);
      return items.value;
    } catch (err) {
      error.value = normalizeError(err, options.errorMessage);
      items.value = [];
      return [];
    } finally {
      loading.value = false;
    }
  }

  return {
    items,
    loading,
    error,
    load
  };
}
