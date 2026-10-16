import { escapePrintHtml as esc } from './printTemplates.js';
import { shipmentQrSvg } from './shipmentPicking.js';
import { pickingGroups } from './shipmentPicking.js';

export function pickingPrintDocument(reference, rows, document = {}) {
  return {
    reference, row: { dock_code: document.loading_dock || document.dock_code, cargo_zone: document.cargo_zone,
      delivery_notes: document.delivery_notes, nama_perusahaan: document.company_name },
    document: { generated_at: new Date().toISOString(), delivering_date: document.delivery_date || document.delivering_date,
      draft_created_at: document.draft_created_at, branch: document.branch, driver: document.driver, fleet: document.fleet,
      route: document.route || { name: document.nama_rute } },
    orders: pickingGroups(rows, 'nota').map(group => {
      const sources = new Map(group.rows.map(r => [r.id_sales_order || r.no_order || group.key, r]));
      const sourceRows = [...sources.values()];
      return { no: group.title, date: sourceRows[0].order_date,
        amount: sourceRows.every(r => numeric(r.order_amount) !== null) ? sourceRows.reduce((sum, r) => sum + Number(r.order_amount), 0) : null,
        customer: group.rows[0].customer_name || '-', code: group.rows[0].customer_code || '',
        area: group.rows[0].area_name, route: group.rows[0].nama_rute };
    }),
    products: pickingGroups(rows, 'variant').map(group => ({ sku: group.rows[0].product_code,
      name: group.rows[0].product_name, quantities: { pieces: group.required },
      uom: { pieces: { label: 'PCS' } }, orderPcs: group.required, pickedPcs: group.picked }))
  };
}

const numeric = value => value === null || value === undefined || value === '' || !Number.isFinite(Number(value)) ? null : Number(value);
const number = value => numeric(value) === null ? '—' : Number(value).toLocaleString('en-US', { maximumFractionDigits: 3 });
const money = value => numeric(value) === null ? '—' : Number(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const signatures = `<footer class="signatures"><div>Droping<span>(................)</span></div><div>Checker<span>(................)</span></div><div>Admin<span>(................)</span></div></footer>`;

// Keep business-local dates stable when the browser uses another time zone.
function printDate(value, withTime = false, shortMonth = false) {
  if (!value) return '—';
  const local = String(value).match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::\d{2})?(?:\.\d+)?)?$/);
  let parts;
  if (local) parts = { year: local[1], month: local[2], day: local[3], hour: local[4], minute: local[5] };
  else {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return '—';
    parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', { timeZone:'Asia/Jakarta', year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hourCycle:'h23' }).formatToParts(parsed).map(p => [p.type,p.value]));
  }
  const month = shortMonth ? ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][Number(parts.month)-1] : parts.month;
  const separator = shortMonth ? '-' : '/';
  return `${parts.day}${separator}${month}${separator}${parts.year}${withTime && parts.hour ? ` ${parts.hour}:${parts.minute}` : ''}`;
}
function caption(value) {
  const formatted = printDate(value);
  if (formatted === '—') return '—';
  const [day,month,year] = formatted.split('/');
  const weekday = new Intl.DateTimeFormat('id-ID', { weekday:'long',timeZone:'UTC' }).format(new Date(`${year}-${month}-${day}T12:00:00Z`)).toUpperCase();
  return `${weekday} / ${day} - ${month} - ${year}`;
}

// Missing operational/financial values are deliberately not invented from quantities.
function sheet(data, mode, options) {
  const { document: doc, row, reference, orders, products } = data;
  const company = esc([row.nama_perusahaan || 'BUDIMAS',doc.branch?.name].filter(Boolean).join(' / '));
  const description = row.delivery_notes || caption(doc.delivering_date);
  const printed = printDate(options.printedAt || doc.generated_at, true);
  const operator = esc(options.printedBy || doc.printed_by || '—');
  // The current API does not always provide the draft creation timestamp.
  // Print — instead of incorrectly using the time of printing/task creation.
  const created = printDate(doc.draft_created_at || row.draft_created_at, true);
  const meta = `<div class="variant-description"><h2>DRAFT BY VARIANT VER 2</h2><p class="company">${company}</p><dl><dt>Keterangan</dt><dd>${esc(description)}</dd><dt>Sopir</dt><dd>${esc(doc.driver?.name || '—')}</dd><dt>Kendaraan</dt><dd>${esc(doc.fleet?.plate || doc.fleet?.name || '—')}</dd><dt>Route</dt><dd>${esc(doc.route?.name || '—')}</dd><dt>Gudang</dt><dd>${esc(row.cargo_zone || '—')}</dd></dl></div>`;
  const qr = shipmentQrSvg(reference);
  if (mode === 'qr') return `<section class="label"><h2>${esc(reference)}</h2><div class="label-body">${qr}<div class="label-meta"><p>${esc(created)}</p><p>${esc(printDate(doc.delivering_date))}</p><p class="label-driver">${esc(doc.driver?.name || '—')}</p><p>${esc(row.cargo_zone || '—')}</p></div></div><p class="label-caption">${esc(description)}</p><footer class="label-signatures"><span>(............)</span><span>(............)</span></footer></section>`;
  const head = mode === 'nota'
    ? `<h2 class="nota-title">DRAFT BY NOTA</h2><header class="nota-header"><div><p class="company">${company}</p><p><b>${esc(printDate(doc.delivering_date,false,true))}</b></p><p><b>${esc(reference)}</b></p><p>${esc(description)} | ${esc(doc.driver?.name || '—')} | ${esc(row.cargo_zone || '—')}</p></div><div class="print-meta"><p>${operator}</p><p>${esc(printed)}</p></div></header>`
    : `<header class="variant-header"><div class="variant-qr">${qr}<b>${esc(reference)}</b></div>${meta}<div class="variant-dates"><p>Tanggal Draft: ${esc(created)}</p><p>Tanggal kirim: ${esc(printDate(doc.delivering_date))}</p><p class="printed-user">User: ${operator}</p><p>Tgl Cetak: ${esc(printed)}</p></div></header>`;
  const total = orders.length && orders.every(o => numeric(o.amount) !== null) ? orders.reduce((sum,o) => sum+Number(o.amount),0) : null;
  const parking = numeric(doc.estimated_parking_cost), unloading = numeric(doc.estimated_unloading_cost);
  const costs = parking !== null && unloading !== null ? parking + unloading : null;
  const table = mode === 'nota'
    ? `<table class="nota-table"><thead><tr><th></th><th>Tanggal</th><th>Faktur</th><th>Area</th><th>Outlet</th><th>Route</th><th class="num">Jumlah Harga</th></tr></thead><tbody>${orders.map((o, i) => `<tr><td>${i + 1}.</td><td>${esc(printDate(o.date,false,true))}</td><td>${esc(o.no)}</td><td>${esc(o.area || '—')}</td><td>${esc(o.code)} ${esc(o.customer)}</td><td>${esc(o.route || doc.route?.name || '—')}</td><td class="num">${money(o.amount)}</td></tr>`).join('')}</tbody></table><div class="nota-total"><p>Perkiraan Biaya Parkir: ${money(parking)}; Perkiraan Biaya Bongkar: ${money(unloading)}; Total Perkiraan Biaya: ${money(costs)}</p><strong>${money(total)}</strong></div>`
    : `<table><thead><tr><th>No.</th><th colspan="2">Variant</th><th>Qty Order / Satuan</th><th>Dock</th><th>Ricikan</th><th>Jumlah (PCS)</th></tr></thead><tbody>${products.map((p, i) => `<tr><td>${i + 1}</td><td>${esc(p.sku)}</td><td>${esc(p.name)}</td><td>${['karton', 'box', 'pieces'].filter(u => p.quantities[u] > 0).map(u => `${number(p.quantities[u])} ${esc(p.uom[u]?.label || u)}`).join(' + ') || '0 PCS'}</td><td>Rumus belum ditemukan</td><td>Rumus belum ditemukan</td><td class="num">${number(p.orderPcs)}</td></tr>`).join('')}</tbody></table>`;
  return `<section class="report-sheet">${head}${table}${signatures}<p class="note">Tanda — berarti data belum tersedia, bukan nol.</p></section>`;
}

export function buildPickingReferenceHtml(documents, mode, options = {}) {
  if (!['nota', 'variant', 'qr'].includes(mode)) throw new Error('Format cetak tidak valid.');
  if (!documents.length || documents.length > 50) throw new Error('Pilih 1–50 draf.');
  return `<!doctype html><html lang="id"><head><meta charset="utf-8"><title>Cetak Picking</title><style>
  @page { size: ${mode === 'qr' ? 'A5 landscape' : 'A4 portrait'}; margin: 14mm 10mm 10mm;
    @top-right { content: ${mode === 'qr' ? 'none' : '"Page " counter(page) " of " counter(pages)'}; font: 11px Arial,sans-serif; }
  }
  * { box-sizing: border-box } body { margin: 0; color: #000; background: white; font: 11px Arial, sans-serif; }
  section + section { break-before: page; page-break-before: always } h2 { margin:0;font:bold 14px 'Times New Roman',serif }
  .nota-title { text-align:center;text-decoration:underline;font-size:16px;margin:0 0 24px }.company { font:12px 'Times New Roman',serif;margin-bottom:10px }
  .nota-header { display:grid;grid-template-columns:2fr 1fr;gap:20px;margin:0 20px 18px }.print-meta { padding:15px 0 0 22px }
  .variant-header { display:grid;grid-template-columns:112px 1fr 205px;gap:12px;margin-bottom:10px;align-items:start }.variant-qr svg { display:block;width:105px;height:105px }.variant-qr b { display:block;font:bold 12px 'Times New Roman',serif;overflow-wrap:anywhere }
  .variant-description h2 { margin:4px 0 }.variant-description .company { margin:3px 0 }.variant-description dl { display:grid;grid-template-columns:72px 1fr;margin:3px 0;font:10px/1.45 'Courier New',monospace } dt,dd { margin:0;overflow-wrap:anywhere } dd::before { content:': ' }
  .variant-dates { font:10px/1.6 'Courier New',monospace;padding-top:12px }.printed-user { font:11px Arial,sans-serif;margin-top:12px }
  p { margin: 4px 0 } table { width: 100%; border-collapse: collapse; } th, td { border-bottom: 1px solid #222; padding: 7px 4px; text-align: left; overflow-wrap: anywhere; }
  th { border-top: 1px solid #222; } thead { display: table-header-group } tr { break-inside: avoid } .num { text-align: right }
  .nota-table tbody { border-bottom:1px dashed #000 }.nota-table td { border-bottom:0;font-size:10px }.nota-table th { font-family:'Times New Roman',serif }
  .nota-total { display:flex;gap:12px;justify-content:space-between;border-top:1px solid #000;padding-top:5px;margin-top:2px;break-inside:avoid }.nota-total p { font:11px 'Times New Roman',serif }.nota-total strong { min-width:130px;text-align:right;border-bottom:3px double #000;padding-bottom:3px;font:bold 14px 'Times New Roman',serif }
  .signatures { display:grid;grid-template-columns:repeat(3,1fr);text-align:center;font:16px Arial,sans-serif;margin-top:20px;break-inside:avoid }.signatures span { display:block;font:12px 'Courier New',monospace;margin-top:48px }
  .label { max-width:160mm;margin:auto }.label h2 { font-size:18px;margin:12px 0 0;text-align:center }.label-body { display:grid;grid-template-columns:155px 1fr;gap:14px;align-items:start;margin-top:4px }.label-body svg { width:155px;height:155px;display:block }
  .label-meta { padding-top:12px;font:11px/1.5 'Courier New',monospace;letter-spacing:1px }.label-driver { margin:12px 0 32px }.label-caption { font:11px 'Courier New',monospace;letter-spacing:1px;text-align:center;margin-top:0 }.label-signatures { display:flex;justify-content:space-around;font:16px 'Courier New',monospace;margin-top:48px }
  .note { font:9px/1.4 Arial,sans-serif;margin-top:16px }
  @media screen { body { background:#ddd;padding:20px }.report-sheet { background:#fff;max-width:210mm;min-height:297mm;padding:14mm 10mm;margin:0 auto 20px }.label { background:#fff;padding:8mm;max-width:210mm;min-height:148mm } }
  </style></head><body>${documents.map(d => sheet(d, mode, options)).join('')}</body></html>`;
}
