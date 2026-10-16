import test from 'node:test';
import assert from 'node:assert/strict';
import { balanceSheetHtml, profitLossHtml, journalHtml, generalLedgerHtml, reportDate, reportContext } from './financialReportPrint.js';
const ctx = { company:'<script>bad</script>', branch:'Solo', from:'2026-10-01', to:'2026-10-13', operator:'Test', printedAt:'13/10/2026' };
test('dates and unselected company are unambiguous', () => {
  assert.equal(reportDate('2026-10-13'), '13/10/2026');
  assert.match(reportContext({},[],[],{}).company, /bukan konsolidasi/);
});
test('balance escapes, shows imbalance, groups without losing actual parent postings', () => {
  const html=balanceSheetHtml(ctx,{sections:{aset:[{nama_akun:'Parent',parent_id:1,amount:10},{nama_akun:'Child',parent_id:1,amount:20}]},summary:{total_aset:30,selisih:30}});
  assert.ok(!html.includes('<script>bad'));
  assert.match(html,/&lt;script&gt;/); assert.match(html,/belum seimbang/);
  assert.match(html,/Parent/);assert.match(html,/Child/);assert.match(html,/30,00/);
});
test('journal prints all rows, debit/credit only, no ending-balance column', () => {
  const rows=Array.from({length:60},(_,i)=>({id:i+1,tanggal:'2026-10-13',info_jurnal:[{nama_akun:'A'+i,debit:100,kredit:50}]}));
  const html=journalHtml(ctx,rows);assert.match(html,/Jurnal #60/);assert.match(html,/6\.000,00/);assert.match(html,/3\.000,00/);assert.ok(!html.includes('Saldo Akhir'));
});
test('profit includes other-income/expense and warnings', () => {
  const html=profitLossHtml(ctx,{sections:{},summary:{laba_bersih:530},warnings:['Periksa kategori']});
  assert.match(html,/Pendapatan Lainnya/);assert.match(html,/Beban Lainnya/);assert.match(html,/530,00/);assert.match(html,/Periksa kategori/);
});
test('ledger includes opening-only accounts and keeps company data separate', () => {
  const html=generalLedgerHtml(ctx,{account_summaries:[{coa_id:1,id_perusahaan:1,nama_akun:'Kas A',saldo_awal:100,saldo_akhir:110},{coa_id:1,id_perusahaan:2,nama_akun:'Kas B',saldo_awal:900,saldo_akhir:900}],result:[{coa_id:1,id_perusahaan:1,keterangan:'Only A',debit:10,saldo_kumulatif:110}]});
  assert.equal(html.split('Only A').length-1,1);assert.match(html,/Kas B/);assert.match(html,/900,00/);assert.match(html,/Saldo Awal/);
});
