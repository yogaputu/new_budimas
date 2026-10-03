const panelKeys = ['targets', 'daily', 'calendar'];

export function resolveDashboardPanels(results) {
  const responses = {};
  const unavailable = [];
  results.forEach((result, index) => {
    const key = panelKeys[index];
    if (result.status === 'fulfilled') responses[key] = result.value;
    else unavailable.push(key);
  });
  if (unavailable.length === panelKeys.length) throw results[0].reason;
  return { responses, unavailable };
}
