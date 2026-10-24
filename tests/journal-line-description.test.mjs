import assert from 'node:assert/strict';
import { test } from 'node:test';
import { journalLineDescription } from '../src/modules/finance/journalLineDescription.js';
import { journalHtml } from '../src/utils/financialReportPrint.js';

test('stored payment references remain visible once, without mutating accounting rows', () => {
  const line = Object.freeze({ keterangan: 'Pembayaran KW-7 | PJBMMSLO-2610000001 | NTN-0002',
    no_faktur: 'PJBMMSLO-2610000001', sumber_dana: 'NTN-0002', workflow_source: 'NTN-0002',
    debit: 99900, kredit: 0 });
  assert.equal(journalLineDescription(line), line.keterangan);
  assert.equal(line.debit, 99900);
});

test('missing invoice and source are appended to Keterangan', () => {
  assert.equal(journalLineDescription({ keterangan: 'Pelunasan SO', no_faktur: 'INV-1',
    workflow_source: 'sales:receipt:7:1:89' }),
  'Pelunasan SO\nFaktur: INV-1 · Sumber: sales:receipt:7:1:89');
});

test('supports workflow invoice ID fallback and preserves differing sources', () => {
  assert.equal(journalLineDescription({ workflow_invoice_id: 79159009, sumber_dana: 'NTN-1', workflow_source: 'KW-7' }),
    'Faktur ID: 79159009 · Sumber: NTN-1 · Sumber: KW-7');
});

test('matching requires a complete reference and escapes regular-expression characters', () => {
  assert.equal(journalLineDescription({ keterangan: 'INV-10 | TF(1)+.000', no_faktur: 'INV-1', workflow_source: 'TF(1)+.000' }),
    'INV-10 | TF(1)+.000\nFaktur: INV-1');
});

test('empty and placeholder metadata do not clutter descriptions', () => {
  for (const line of [{}, { keterangan: ' ', no_faktur: '-', sumber_dana: '—' }, { keterangan: null }]) {
    assert.equal(journalLineDescription(line), '—');
  }
  assert.equal(journalLineDescription({ keterangan: 'Tanpa referensi', no_faktur: '', workflow_source: null }), 'Tanpa referensi');
});

test('journal print retains and escapes references once and keeps monetary totals', () => {
  const html = journalHtml({}, [{ id_jurnal: 772, info_jurnal: [
    { keterangan: 'Bayar <script>', no_faktur: 'INV-1', workflow_source: 'NTN-2', debit: 987900, kredit: 0 },
    { keterangan: 'Bayar | INV-2 | NTN-3', no_faktur: 'INV-2', sumber_dana: 'NTN-3', debit: 0, kredit: 987900 }
  ] }]);
  assert.ok(html.includes('Bayar &lt;script&gt;<br>Faktur: INV-1 · Sumber: NTN-2'));
  assert.equal(html.match(/INV-2/g)?.length, 1);
  assert.equal(html.match(/NTN-3/g)?.length, 1);
  assert.ok(html.includes('987.900,00'));
  assert.ok(!html.includes('Jurnal belum seimbang'));
});
