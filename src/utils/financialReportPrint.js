import { escapePrintHtml as e, openPrintHtml } from './printTemplates.js';
import { journalLineDescription } from '../modules/finance/journalLineDescription.js';

const money = (v) => Number(v || 0).toLocaleString('id-ID', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const num = (v) => `<td class="number">${money(v)}</td>`;
export function reportDate(value) {
  if (!value) return '-';
  const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (match) return `${match[3]}/${match[2]}/${match[1]}`;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleDateString('id-ID');
}
export function reportContext(filters, companies, branches, user) {
  const find = (rows, id, all) => id ? (rows.find(r => String(r.id) === String(id))?.nama || `ID ${id}`) : all;
  return {
    company: find(companies, filters.companyId, 'Semua Perusahaan — Gabungan (bukan konsolidasi)'),
    branch: find(branches, filters.branchId, 'Semua Cabang'),
    from: filters.from, to: filters.to, search: filters.search,
    operator: user?.nama || user?.name || '-',
    printedAt: new Date().toLocaleString('id-ID'),
  };
}
function documentHtml(title, ctx, content, landscape = false) {
  return `<!doctype html><html lang="id"><head><meta charset="utf-8"><title>${e(title)}</title><style>
    @page{size:A4 ${landscape ? 'landscape' : 'portrait'};margin:13mm 12mm}
    *{box-sizing:border-box}body{font:11px Arial,sans-serif;color:#111;margin:0;background:white}
    h1{font-size:20px;margin:7px 0}h2{font-size:14px;margin:18px 0 8px;break-after:avoid}p{margin:5px 0}
    header{text-align:center;border-bottom:2px solid #222;padding-bottom:12px;margin-bottom:12px}
    .meta{display:flex;justify-content:space-between;gap:12px;font-size:10px;margin:10px 0}
    table{border-collapse:collapse;width:100%;table-layout:fixed;margin-bottom:14px}
    thead{display:table-header-group}th{text-align:left;background:#eee;border-top:1px solid #333;border-bottom:1px solid #333}
    th,td{padding:6px 5px;vertical-align:top;overflow-wrap:anywhere}td{border-bottom:1px solid #ddd}
    tr{break-inside:avoid}.number{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
    .group td{font-weight:bold;background:#f2f2f2}.total td{font-weight:bold;border-top:1px solid #222;border-bottom:2px solid #222}
    .warning{border:1px solid #888;padding:8px;margin:10px 0;break-inside:avoid}.muted{font-size:10px;color:#444}
    .toolbar{padding:12px;background:#eee;position:sticky;top:0}.toolbar button{padding:8px 16px;cursor:pointer}
    .account{break-after:avoid}.account+table{margin-top:0}.indent{padding-left:17px}
    footer{margin-top:18px;border-top:1px solid #999;padding-top:7px;font-size:9px}
    @media screen{body{max-width:${landscape ? '1100' : '780'}px;margin:auto;padding:18px}}
    @media print{.toolbar{display:none}body{padding:0}.meta{break-inside:avoid}}
  </style></head><body><div class="toolbar"><button onclick="window.print()">Cetak / Simpan PDF</button></div>
  <header><strong>${e(ctx.company)}</strong><h1>${e(title)}</h1><p>${ctx.from ? `Periode ${e(reportDate(ctx.from))} – ` : 'Per '}${e(reportDate(ctx.to))}</p><p>${e(ctx.branch)} · Dalam IDR</p></header>
  <div class="meta"><span>Dicetak oleh: ${e(ctx.operator)}${ctx.search ? ` · Pencarian: ${e(ctx.search)}` : ''}</span><span>${e(ctx.printedAt)}</span></div>
  ${content}<footer>Budimas ERP · ${e(title)} · Saldo dan transaksi sesuai data pada saat laporan dimuat.</footer></body></html>`;
}
const warningsHtml = (warnings = []) => warnings.map(w => `<p class="warning">${e(w)}</p>`).join('');
const totalRow = (label, value) => `<tr class="total"><td colspan="2">${e(label)}</td>${num(value)}</tr>`;
function sectionHtml(title, rows, total) {
  let body = '';
  const groups = new Map();
  for (const r of rows || []) {
    const key = JSON.stringify([r.id_perusahaan, r.nama_kategori, r.parent_id]);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(r);
  }
  for (const group of groups.values()) {
    const first = group[0];
    const label = [...new Set([first.nama_perusahaan, first.nama_kategori, first.parent_nama_akun].filter(Boolean))].join(' / ');
    body += `<tr class="group"><td colspan="3">${e(label || title)}</td></tr>`;
    body += group.map(r => `<tr><td>${e(r.nomor_akun || r.kode_produk || '-')}</td><td class="indent">${e(r.nama_akun || r.nama_produk || '-')}</td>${num(r.amount)}</tr>`).join('');
    if (group.length > 1) body += totalRow('Subtotal ' + label, group.reduce((v, r) => v + Number(r.amount || 0), 0));
  }
  return `<h2>${e(title)}</h2><table><colgroup><col style="width:20%"><col style="width:57%"><col style="width:23%"></colgroup><thead><tr><th>Kode Akun</th><th>Nama Akun / Principal</th><th class="number">Saldo (IDR)</th></tr></thead><tbody>${body || '<tr><td colspan="3">Tidak ada transaksi.</td></tr>'}${totalRow('Total ' + title, total)}</tbody></table>`;
}
export function balanceSheetHtml(ctx, report) {
  const s = report.summary || {}, sections = report.sections || {};
  const alerts = [...(report.warnings || [])];
  if (Math.abs(Number(s.selisih || 0)) >= 0.01 && !alerts.some(w => /seimbang/i.test(w))) alerts.push('Neraca belum seimbang. Periksa jurnal dan pemetaan akun.');
  let body = warningsHtml(alerts);
  for (const [key, title, total] of [['aset', 'Aset', s.total_aset], ['kewajiban', 'Kewajiban', s.total_kewajiban], ['ekuitas', 'Ekuitas', s.total_ekuitas]]) body += sectionHtml(title, sections[key], total);
  body += `<table><tbody>${totalRow('Total Kewajiban dan Ekuitas', s.total_kewajiban_ekuitas)}${totalRow('Selisih Aset − Kewajiban − Ekuitas', s.selisih)}</tbody></table>`;
  if (sections.lainnya?.length) body += sectionHtml('Belum Terklasifikasi (di luar total Neraca)', sections.lainnya, s.total_lainnya);
  return documentHtml('Neraca', ctx, body);
}
export function profitLossHtml(ctx, report) {
  const s = report.summary || {}, sections = report.sections || {};
  let body = `<p>Metode HPP: ${e(report.hpp_method || 'journal')} · Sumber: ${e(report.hpp_source || 'journal')}</p>${warningsHtml(report.warnings)}`;
  for (const [key, title, total] of [['pendapatan', 'Pendapatan', s.total_pendapatan], ['hpp', 'Harga Pokok Penjualan', s.total_hpp], ['beban', 'Beban Operasional', s.total_beban], ['pendapatan_lain', 'Pendapatan Lainnya', s.total_pendapatan_lain], ['beban_lain', 'Beban Lainnya', s.total_beban_lain]]) {
    body += sectionHtml(title, sections[key], total);
    if (key === 'hpp') body += `<table><tbody>${totalRow('Laba Kotor', s.laba_kotor)}</tbody></table>`;
    if (key === 'beban') body += `<table><tbody>${totalRow('Laba Operasional', s.laba_operasional)}</tbody></table>`;
  }
  body += `<table><tbody>${totalRow('Laba / Rugi Bersih', s.laba_bersih)}</tbody></table>`;
  if (sections.lainnya?.length) body += sectionHtml('Belum Terklasifikasi (tidak dihitung sebagai laba)', sections.lainnya, s.total_lainnya);
  return documentHtml('Laba Rugi', ctx, body);
}
export function journalHtml(ctx, rows) {
  let debit = 0, credit = 0, body = '';
  for (const r of rows) {
    body += `<tr class="group"><td>${e(reportDate(r.tanggal))}</td><td colspan="3">Jurnal #${e(r.id_jurnal || r.id)} · ${e(r.nama_perusahaan)} / ${e(r.nama_cabang)}<br>${e(r.keterangan || r.jenis_transaksi || '')}</td><td></td><td></td></tr>`;
    for (const line of r.info_jurnal || []) {
      debit += Number(line.debit || 0); credit += Number(line.kredit || 0);
      body += `<tr><td class="muted">#${e(r.id_jurnal || r.id)}</td><td>${e(line.nomor_akun || '-')}</td><td>${e(line.nama_akun)}</td><td>${e(journalLineDescription(line)).replaceAll('\n', '<br>')}</td>${num(line.debit)}${num(line.kredit)}</tr>`;
    }
  }
  const table = `<p>${rows.length} jurnal · Seluruh hasil filter, bukan hanya halaman aktif.</p><table><colgroup><col style="width:10%"><col style="width:12%"><col style="width:24%"><col style="width:28%"><col style="width:13%"><col style="width:13%"></colgroup><thead><tr><th>Tanggal</th><th>Kode Akun</th><th>Akun</th><th>Keterangan / Referensi</th><th class="number">Debit</th><th class="number">Kredit</th></tr></thead><tbody>${body || '<tr><td colspan="6">Tidak ada jurnal.</td></tr>'}<tr class="total"><td colspan="4">Total Debit / Kredit</td>${num(debit)}${num(credit)}</tr></tbody></table>`;
  return documentHtml('Jurnal', ctx, table + (Math.abs(debit-credit) >= 0.01 ? warningsHtml([`Jurnal belum seimbang. Selisih debit − kredit: Rp ${money(debit-credit)}.`]) : ''), true);
}
export function generalLedgerHtml(ctx, report) {
  const rows = (report.result || []).filter(r => !r.isParent);
  let body = `<p>Saldo menggunakan Debit − Kredit; saldo berjalan dihitung terpisah per perusahaan dan akun.</p>${warningsHtml(report.warnings)}`;
  for (const a of report.account_summaries || []) {
    const lines = rows.filter(r => r.coa_id === a.coa_id && r.id_perusahaan === a.id_perusahaan);
    body += `<h2 class="account">${e(a.nama_perusahaan)} · ${e(a.nomor_akun || '-')} — ${e(a.nama_akun)}</h2><table><colgroup><col style="width:10%"><col style="width:9%"><col style="width:36%"><col style="width:15%"><col style="width:15%"><col style="width:15%"></colgroup><thead><tr class="group"><th colspan="6">${e(a.nama_perusahaan)} · ${e(a.nomor_akun || '-')} — ${e(a.nama_akun)}</th></tr><tr><th>Tanggal</th><th>Jurnal</th><th>Keterangan / Referensi / Cabang</th><th class="number">Debit</th><th class="number">Kredit</th><th class="number">Saldo</th></tr></thead><tbody><tr class="group"><td colspan="5">Saldo Awal</td>${num(a.saldo_awal)}</tr>`;
    body += lines.map(r => `<tr><td>${e(reportDate(r.tanggal))}</td><td>${e(r.id_jurnal)}</td><td>${e(r.keterangan || '-')}<br><span class="muted">${e([r.no_faktur, r.sumber_dana, r.nama_cabang].filter(Boolean).join(' · '))}</span></td>${num(r.debit)}${num(r.kredit)}${num(r.saldo_kumulatif)}</tr>`).join('');
    body += `<tr class="total"><td colspan="3">Total Mutasi / Saldo Akhir</td>${num(a.total_debet)}${num(a.total_kredit)}${num(a.saldo_akhir)}</tr></tbody></table>`;
  }
  if (!report.account_summaries?.length) body += '<p>Tidak ada saldo atau mutasi pada filter ini.</p>';
  return documentHtml('Buku Besar', ctx, body, true);
}
export function showFinancialPrint(title, html) {
  return openPrintHtml(title, html, { autoPrint: false });
}
