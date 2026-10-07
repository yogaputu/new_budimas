// Warehouse report is authoritative. Never apportion its balance across guessed lots/racks.
export function placementBalances(report, placements, {search='',rack='',status=''} = {}) {
  const key = r => `${r.id_cabang}:${r.id_produk}`;
  // Older imports may contain multiple stock rows for the same product/branch.
  // Match the report's additive balances; its rack aggregate is repeated on
  // each row and must be counted only once. Do not silently select MAX(ready).
  const balances = new Map();
  for (const row of report) {
    const k=key(row), existing=balances.get(k);
    if (!existing) balances.set(k, {...row, jumlah_ready:Number(row.jumlah_ready || 0), jumlah_good:Number(row.jumlah_good || 0)});
    else {
      existing.jumlah_ready+=Number(row.jumlah_ready || 0);
      existing.jumlah_good+=Number(row.jumlah_good || 0);
    }
  }
  const locations = new Map();
  for (const row of placements) {
    const k=key(row);
    if (!locations.has(k)) locations.set(k,[]);
    locations.get(k).push(row);
  }
  const keyword=search.trim().toLowerCase();
  return [...balances.values()].filter(row => {
    const lots=locations.get(key(row)) || [];
    if ((rack || status) && !lots.length) return false;
    return !keyword || lots.length || [row.kode_sku,row.nama_produk,row.nama_principal,row.nama_cabang].some(v=>String(v || '').toLowerCase().includes(keyword));
  }).map(row => ({
    ...row, id:key(row),
    qty_pcs:Math.max(Number(row.jumlah_ready || 0),0),
    mapped_pcs:Number(row.jumlah_rak_tetap || 0),
    mapping_gap:Number(row.jumlah_good || 0)-Number(row.jumlah_rak_tetap || 0),
    // Informational only: neither a real rack nor a pickable lot is invented.
    mapping_status:Number(row.jumlah_good || 0)===Number(row.jumlah_rak_tetap || 0) ? 'Sesuai GOOD' : 'Perlu rekonsiliasi rak',
  }));
}
