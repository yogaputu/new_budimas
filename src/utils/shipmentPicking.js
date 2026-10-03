import QRCode from 'qrcode';

export function shipmentQrSvg(reference) {
  if (!/^DRF-[1-9]\d*-[1-9]\d*$/.test(reference)) throw new Error('Referensi draf tidak valid.');
  const matrix = QRCode.create(`BUDIMAS-WMS|SHIPMENT|${reference}`, { errorCorrectionLevel: 'M' }).modules;
  const size = matrix.size + 8;
  let cells = '';
  for (let y = 0; y < matrix.size; y++) for (let x = 0; x < matrix.size; x++) {
    if (matrix.get(y, x)) cells += `<rect x="${x + 4}" y="${y + 4}" width="1" height="1"/>`;
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="110" height="110" viewBox="0 0 ${size} ${size}" aria-label="QR draf kiriman"><rect width="${size}" height="${size}" fill="white"/><g fill="black">${cells}</g></svg>`;
}

export function pickingGroups(rows, mode) {
  const groups = new Map();
  for (const row of rows) {
    const key = mode === 'nota' ? String(row.nota || row.no_order || row.id_picking || row.wms_task_id) : String(row.id_produk || row.product_code);
    if (!groups.has(key)) groups.set(key, { key, title: mode === 'nota' ? row.nota || row.no_order : `${row.product_code} · ${row.product_name}`, required: 0, picked: 0, rows: [] });
    const group = groups.get(key);
    group.required += Number(row.required_quantity || 0); group.picked += Number(row.picked_quantity || 0); group.rows.push(row);
  }
  return [...groups.values()];
}
