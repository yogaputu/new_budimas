// getSales returns users.id as id; the deposit FK references sales.id (id_sales).
export function depositSalesOptions(rows, branch) {
  const unique = new Map();
  for (const row of rows) {
    const id = Number(row.id_sales);
    if (!Number.isSafeInteger(id) || id <= 0) continue;
    if (branch && row.id_cabang && String(row.id_cabang) !== String(branch)) continue;
    if (!unique.has(id)) unique.set(id, {
      value: String(id), label: row.nama || row.nama_sales || `Sales ${id}`,
    });
  }
  return [...unique.values()].sort((a, b) => a.label.localeCompare(b.label, 'id'));
}
