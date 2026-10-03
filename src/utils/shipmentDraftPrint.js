import { escapePrintHtml as esc, formatPrintDate } from './printTemplates.js';
import { shipmentQrSvg } from './shipmentPicking.js';

export const MAX_PRINT_DRAFTS = 50;
export function draftIds(value) {
  const parts = Array.isArray(value) ? value : String(value ?? '').split(',');
  return [...new Set(parts.map(value => String(value).trim()).filter(value => /^[1-9]\d*$/.test(value)))].sort((a, b) => Number(a) - Number(b));
}
export function shipmentKey(row) { return draftIds(row?.id_proses_picking).join(','); }
export function shipmentReference(row) {
  return shipmentKey(row) ? `DRF-${row.id_cabang || '?'}-${draftIds(row.id_proses_picking)[0]}` : 'Belum dibuat';
}
export function shipmentPrintError(row) {
  if (row?.__draft_schedule || !shipmentKey(row)) return 'Jadwal belum tersimpan.';
  const statuses = String(row.status_order ?? '').split(',').map(value => value.trim());
  if (!statuses.length || statuses.some(value => !['2', '10'].includes(value))) return 'Bukan draf aktif atau sebagian nota sudah diproses. Muat ulang jadwal.';
  if (!row.id_armada || !row.id_driver || !row.delivering_date) return 'Armada, driver, atau tanggal kirim belum lengkap.';
  return '';
}
function qty(value) {
  const number = Number(value ?? 0);
  if (!Number.isFinite(number) || number < 0) throw new Error('Jumlah barang pada draf tidak valid.');
  return number;
}
const num = value => qty(value).toLocaleString('id-ID', { maximumFractionDigits: 3 });
function sameIds(left, right) { return JSON.stringify(draftIds(left)) === JSON.stringify(draftIds(right)); }
function dateKey(value) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? '' : parsed.toISOString().slice(0, 10);
}

export function prepareShipmentDocument(row, payload) {
  const problem = shipmentPrintError(row);
  if (problem) throw new Error(problem);
  const document = payload?.document || {};
  if (!sameIds(document.source_picking_ids, row.id_proses_picking) ||
      String(document.branch?.id) !== String(row.id_cabang) ||
      String(document.route?.id) !== String(row.id_rute) ||
      String(document.fleet?.id) !== String(row.id_armada) ||
      String(document.driver?.id) !== String(row.id_driver) ||
      !dateKey(document.delivering_date) || dateKey(document.delivering_date) !== dateKey(row.delivering_date)) {
    throw new Error('Isi atau jadwal draf sudah berubah. Muat ulang daftar sebelum mencetak.');
  }
  const variants = payload?.variants;
  if (!Array.isArray(variants) || !variants.length) throw new Error('Rincian barang draf belum tersedia.');
  const orders = new Map(), details = new Map(), pickingIds = new Set();
  const products = variants.map(variant => {
    const product = { sku: variant.sku, name: variant.product_name, principal: variant.principal_name,
      uom: variant.uom || {}, quantities: { pieces: 0, box: 0, karton: 0 }, orderPcs: 0, pickedPcs: 0 };
    if (!variant.allocations?.length) throw new Error('Rincian nota pada draf belum lengkap.');
    for (const allocation of variant.allocations) {
      const pickingId = String(allocation.id_proses_picking || '');
      const detailId = String(allocation.id_order_detail || '');
      const orderId = String(allocation.id_sales_order || '');
      if (!draftIds(pickingId).length || !draftIds(detailId).length || !draftIds(orderId).length || pickingIds.has(pickingId)) {
        throw new Error('Rincian barang draf tidak valid atau terduplikasi.');
      }
      pickingIds.add(pickingId);
      if (!orders.has(orderId)) orders.set(orderId, { id: orderId, no: allocation.no_order, customerId: allocation.customer_id,
        customer: allocation.customer_name, code: allocation.customer_code, orderPcs: 0, pickedPcs: 0 });
      const order = orders.get(orderId), picked = qty(allocation.draft_picked_pcs);
      product.pickedPcs += picked; order.pickedPcs += picked;
      // Multiple batch/picking rows for one order detail must not multiply its ordered quantity.
      const signature = JSON.stringify([orderId, variant.product_id, allocation.order_uom, allocation.total_order_pcs]);
      if (details.has(detailId)) {
        if (details.get(detailId) !== signature) throw new Error('Rincian jumlah order tidak konsisten.');
        continue;
      }
      details.set(detailId, signature);
      for (const unit of ['pieces', 'box', 'karton']) product.quantities[unit] += qty(allocation.order_uom?.[unit]);
      const ordered = qty(allocation.total_order_pcs);
      product.orderPcs += ordered; order.orderPcs += ordered;
    }
    return product;
  });
  if (!sameIds([...pickingIds], row.id_proses_picking) || !sameIds([...orders.keys()], row.id_sales_order)) {
    throw new Error('Sebagian nota atau barang tidak lagi termasuk draf ini. Muat ulang daftar; cetak dibatalkan.');
  }
  return { row, document, reference: shipmentReference(row), products, orders: [...orders.values()],
    orderPcs: products.reduce((sum, product) => sum + product.orderPcs, 0),
    pickedPcs: products.reduce((sum, product) => sum + product.pickedPcs, 0) };
}
function orderUnits(product) {
  return ['karton', 'box', 'pieces'].filter(unit => product.quantities[unit] > 0)
    .map(unit => `${num(product.quantities[unit])} ${product.uom[unit]?.label || { karton: 'UOM 3', box: 'UOM 2', pieces: 'PCS' }[unit]}`).join(' + ') || '0 PCS';
}
function sheet(data) {
  const { row, document, products, orders, reference } = data;
  const field = (label, value) => `<div><small>${esc(label)}</small><span>${esc(value || '-')}</span></div>`;
  return `<section class="draft-sheet" data-draft="${esc(reference)}">
    <header><div><h1>DRAF KIRIMAN</h1><p>${esc(row.nama_perusahaan || 'BUDIMAS')}</p></div><div class="reference"><strong>${esc(reference)}</strong><p>${orders.length} nota · ${new Set(orders.map(order => order.customerId)).size} customer</p></div></header>
    <div class="metadata">
      ${field('Cabang', document.branch?.name)}${field('Tanggal kirim', formatPrintDate(document.delivering_date))}
      ${field('Rute', [document.route?.code, document.route?.name].filter(Boolean).join(' — '))}
      ${field('Armada', [document.fleet?.name, document.fleet?.plate].filter(Boolean).join(' / '))}
      ${field('Driver', document.driver?.name)}${field('Helper / Kernet', row.nama_helpers || row.nama_helper)}
      ${field('Loading dock / zona', [row.dock_code, row.cargo_zone].filter(Boolean).join(' / '))}${field('Dicetak', document.generated_at)}
    </div>
    <div style="display:flex;align-items:center;gap:14px">${shipmentQrSvg(reference)}<p class="notice">Scan QR draf ini untuk picking semua nota di Mobile WMS. DRAF — bukan faktur atau surat jalan. Nomor nota tetap terpisah. Cetak tidak mengubah stok maupun status pengiriman.</p></div>
    <h2>Daftar Nota / Customer</h2>
    <table><thead><tr><th>No</th><th>Nomor Nota / SO</th><th>Customer</th><th class="number">Qty Order (PCS)</th><th class="number">Qty Draf Picking (PCS)</th></tr></thead>
      <tbody>${orders.map((order, i) => `<tr><td>${i + 1}</td><td>${esc(order.no)}</td><td>${esc(order.code)} — ${esc(order.customer)}</td><td class="number">${num(order.orderPcs)}</td><td class="number">${num(order.pickedPcs)}</td></tr>`).join('')}</tbody>
    </table>
    <h2>Rekap Barang</h2>
    <table><thead><tr><th>No</th><th>SKU / Barang</th><th>Principal</th><th>Qty Order / Satuan</th><th class="number">Order (PCS)</th><th class="number">Draf Picking (PCS)</th></tr></thead>
      <tbody>${products.map((product, i) => `<tr><td>${i + 1}</td><td><strong>${esc(product.sku)}</strong><br>${esc(product.name)}</td><td>${esc(product.principal)}</td><td>${esc(orderUnits(product))}</td><td class="number">${num(product.orderPcs)}</td><td class="number">${num(product.pickedPcs)}</td></tr>`).join('')}</tbody>
    </table>
    <div class="totals">${orders.length} nota · ${products.length} produk &nbsp; | &nbsp; Total order: <strong>${num(data.orderPcs)} PCS</strong> &nbsp; | &nbsp; Draf picking: <strong>${num(data.pickedPcs)} PCS</strong></div>
    ${row.delivery_notes ? `<p class="notes"><strong>Catatan:</strong> ${esc(row.delivery_notes)}</p>` : ''}
    <div class="signatures"><div>Disiapkan Gudang</div><div>Checker</div><div>Driver / Helper</div></div>
    <p class="footnote">Referensi berdasarkan jadwal picking yang tersimpan; bukan nomor faktur.</p>
  </section>`;
}
export function buildShipmentDraftsHtml(documents) {
  if (!documents.length || documents.length > MAX_PRINT_DRAFTS) throw new Error(`Pilih 1–${MAX_PRINT_DRAFTS} draf untuk dicetak.`);
  return `<!doctype html><html lang="id"><head><meta charset="utf-8"><title>Cetak ${documents.length} Draf Kiriman</title><style>
    @page { size: A4 landscape; margin: 10mm; }
    * { box-sizing: border-box; } body { margin: 0; color: #172033; background: white; font: 11px Arial, sans-serif; }
    .draft-sheet { padding: 4px; } .draft-sheet + .draft-sheet { break-before: page; page-break-before: always; }
    header { display: flex; justify-content: space-between; gap: 20px; border-bottom: 2px solid #172033; padding-bottom: 8px; }
    h1 { font-size: 23px; margin: 0; } h2 { font-size: 12px; margin: 14px 0 6px; break-after: avoid; }
    p { margin: 5px 0; } .reference { text-align: right; } .reference strong { font-size: 17px; }
    .metadata { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px 18px; margin: 12px 0; }
    .metadata small { display: block; color: #526075; margin-bottom: 3px; text-transform: uppercase; font-size: 9px; }
    .metadata span, td { overflow-wrap: anywhere; } .notice { padding: 8px; background: #f1f5f9; border: 1px solid #cbd5e1; }
    table { border-collapse: collapse; width: 100%; table-layout: auto; } th, td { border: 1px solid #94a3b8; padding: 6px; text-align: left; vertical-align: top; }
    th { background: #e2e8f0; font-size: 10px; } thead { display: table-header-group; } tr { break-inside: avoid; }
    .number { text-align: right; white-space: nowrap; } .totals { text-align: right; padding: 10px 0; font-size: 12px; }
    .notes { white-space: pre-wrap; } .signatures { display: grid; grid-template-columns: repeat(3, 1fr); gap: 50px; margin-top: 45px; break-inside: avoid; }
    .signatures div { border-top: 1px solid #64748b; text-align: center; padding-top: 5px; } .footnote { margin-top: 12px; color: #64748b; font-size: 9px; }
    @media screen { body { background: #e2e8f0; } .draft-sheet { background: white; max-width: 1120px; margin: 18px auto; padding: 28px; } }
  </style></head><body>${documents.map(sheet).join('')}</body></html>`;
}
