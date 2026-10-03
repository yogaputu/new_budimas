export function unwrapResponse(response) {
  const payload = response?.data;

  if (payload?.data !== undefined) {
    return payload.data;
  }

  if (payload?.result !== undefined) {
    return payload.result;
  }

  return payload;
}

export function normalizeList(payload) {
  if (Array.isArray(payload)) {
    return payload;
  }

  if (Array.isArray(payload?.pages?.result)) {
    return payload.pages.result;
  }

  if (Array.isArray(payload?.pages)) {
    return payload.pages;
  }

  if (Array.isArray(payload?.result)) {
    return payload.result;
  }

  if (Array.isArray(payload?.items)) {
    return payload.items;
  }

  if (Array.isArray(payload?.rows)) {
    return payload.rows;
  }

  if (Array.isArray(payload?.data)) {
    return payload.data;
  }

  if (payload && typeof payload === 'object') {
    const listCandidate = Object.values(payload).find((value) => Array.isArray(value));
    if (Array.isArray(listCandidate)) {
      return listCandidate;
    }
  }

  return [];
}

export function normalizeError(error, fallback = 'Terjadi kesalahan saat memproses permintaan.') {
  return (
    error?.response?.data?.message ||
    error?.response?.data?.error ||
    error?.message ||
    fallback
  );
}
