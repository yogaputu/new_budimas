// Run with the bundled Node runtime and a directory containing its node_modules:
// node scripts/build-sales-order-template.mjs /tmp/template-workspace
// The generated XLSX is a static asset; the browser needs no spreadsheet library.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { orderTemplateColumns, orderTemplateExamples, orderTemplateRules, salesOrderTemplate } from '../src/modules/data-tools/salesOrderTemplate.js';

const runtimeDirectory = process.argv[2];
if (!runtimeDirectory) throw new Error('Pass the workspace directory linked to the bundled spreadsheet dependencies.');
const require = createRequire(import.meta.url);
const artifactEntry = require.resolve('@oai/artifact-tool', { paths: [path.resolve(runtimeDirectory)] });
const { Workbook, SpreadsheetFile } = await import(pathToFileURL(artifactEntry).href);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outputDir = path.join(root, 'outputs', 'sales-order-template-20260929');
await fs.mkdir(outputDir, { recursive: true });

const keys = orderTemplateColumns.map((column) => column.key);
assert.equal(new Set(keys).size, keys.length);
const groupKeys = ['source_system', 'kode_perusahaan', 'kode_cabang', 'kode_principal', 'no_order'];
const groups = new Map();
for (const row of orderTemplateExamples) {
  assert.deepEqual(Object.keys(row).sort(), [...keys].sort(), 'Every example must match the complete column contract');
  assert.ok(['SALES', 'ADMIN'].includes(row.sumber_order));
  assert.ok(row.qty_pcs + row.qty_box + row.qty_karton > 0);
  for (const column of orderTemplateColumns) {
    const value = row[column.key];
    if (column.required === 'Wajib') assert.notEqual(value, '');
    if (column.type === 'Teks') assert.equal(typeof value, 'string');
    if (['Angka', 'Bilangan bulat'].includes(column.type)) assert.ok(Number.isFinite(value) && value >= 0);
    if (column.type === 'Bilangan bulat') assert.ok(Number.isInteger(value));
  }
  const groupKey = JSON.stringify(groupKeys.map((key) => row[key]));
  const previousRows = groups.get(groupKey) || [];
  for (const previous of previousRows) {
    for (const column of orderTemplateColumns.filter((column) => column.scope === 'Order')) {
      assert.equal(row[column.key], previous[column.key], `${column.key} must agree within an order`);
    }
    assert.notEqual(row.nomor_baris, previous.nomor_baris);
    assert.notEqual(row.source_detail_id, previous.source_detail_id);
  }
  groups.set(groupKey, [...previousRows, row]);
}
assert.equal(groups.size, 3);
assert.deepEqual([...new Set(orderTemplateExamples.map((row) => row.sumber_order))].sort(), ['ADMIN', 'SALES']);
assert.equal(orderTemplateExamples[3].kode_sales, 'CONTOH-SLS02', 'Admin input must preserve the owning salesperson');

const workbook = Workbook.create();
const data = workbook.worksheets.add(salesOrderTemplate.sheetName);
const guide = workbook.worksheets.add('Panduan');
data.showGridLines = false;
guide.showGridLines = false;
data.tabColor = '#1E3A8A';
guide.tabColor = '#64748B';

const matrix = [keys, ...orderTemplateExamples.map((row) => orderTemplateColumns.map((column) =>
  column.type === 'Tanggal' ? new Date(`${row[column.key]}T00:00:00Z`) : row[column.key]
))];
data.getRangeByIndexes(0, 0, matrix.length, keys.length).values = matrix;
const used = data.getRangeByIndexes(0, 0, matrix.length, keys.length);
used.format.font = { name: 'Arial', size: 10, color: '#172554' };
used.format.rowHeight = 36;
used.format.verticalAlignment = 'center';
used.format.wrapText = true;

for (let index = 0; index < keys.length; index++) {
  const column = orderTemplateColumns[index];
  const range = data.getRangeByIndexes(1, index, 1000, 1);
  range.setNumberFormat(column.type === 'Teks' ? '@' : column.type === 'Tanggal' ? 'yyyy-mm-dd' : column.type === 'Bilangan bulat' ? '0' : '0.00');
  data.getRangeByIndexes(0, index, matrix.length, 1).format.columnWidthPx =
    column.key === 'catatan_order' ? 310 : column.key.startsWith('nama_') ? 180 : 160;
  range.format.horizontalAlignment = column.type === 'Teks' ? 'left' : 'right';
}

const table = data.tables.add(`A1:Z${matrix.length}`, true, 'DataOrderSales');
table.showFilterButton = true;
const header = data.getRange('A1:Z1');
header.format.fill = '#1E3A8A';
header.format.font = { name: 'Arial', size: 10, bold: true, color: '#FFFFFF' };
header.format.rowHeight = 44;
header.format.horizontalAlignment = 'center';
header.format.borders = { insideVertical: { style: 'thin', color: '#FFFFFF' } };
data.freezePanes.freezeRows(1);
data.freezePanes.freezeColumns(1);
data.getRange('J2:J1001').dataValidation = { rule: { type: 'list', values: ['SALES', 'ADMIN'] } };

guide.getRange('A2').values = [[`Template Order Sales v${salesOrderTemplate.version}`]];
guide.getRange('A4:B4').values = [['Aturan pengisian', 'Penjelasan']];
guide.getRangeByIndexes(4, 0, orderTemplateRules.length, 2).values = orderTemplateRules;
const dictionaryHeader = 6 + orderTemplateRules.length;
guide.getRange(`A${dictionaryHeader}:B${dictionaryHeader}`).values = [['Kolom Data_Order', 'Tipe, lingkup dan cara mengisi']];
const dictionary = orderTemplateColumns.map((column) => [
  column.key,
  `${column.required} · ${column.type} · ${column.scope}. ${column.description}\nContoh: ${orderTemplateExamples[0][column.key]}`
]);
guide.getRangeByIndexes(dictionaryHeader, 0, dictionary.length, 2).values = dictionary;
const lastGuideRow = dictionaryHeader + dictionary.length;
guide.getRange(`A1:B${lastGuideRow}`).format.font = { name: 'Arial', size: 10, color: '#172554' };
guide.getRange(`A4:B${lastGuideRow}`).format.wrapText = true;
guide.getRange(`A4:B${lastGuideRow}`).format.verticalAlignment = 'center';
guide.getRange(`A4:B${lastGuideRow}`).format.rowHeight = 60;
guide.getRange(`A1:A${lastGuideRow}`).format.columnWidthPx = 260;
guide.getRange(`B1:B${lastGuideRow}`).format.columnWidthPx = 840;
guide.getRange('A2').format.font = { name: 'Arial', size: 15, bold: true, color: '#1E3A8A' };
guide.getRange('A2:B2').format.rowHeight = 30;
for (const rowNumber of [4, dictionaryHeader]) {
  guide.getRange(`A${rowNumber}:B${rowNumber}`).format.fill = '#1E3A8A';
  guide.getRange(`A${rowNumber}:B${rowNumber}`).format.font = { name: 'Arial', size: 10, bold: true, color: '#FFFFFF' };
  guide.getRange(`A${rowNumber}:B${rowNumber}`).format.rowHeight = 30;
}
guide.getRange(`A${4 + orderTemplateRules.length}:B${4 + orderTemplateRules.length}`).format.fill = '#FEF3C7';

workbook.recalculate();
console.log((await workbook.inspect({ kind: 'table', range: 'Data_Order!A1:J5', include: 'values,formulas', tableMaxRows: 5, tableMaxCols: 10, maxChars: 2200 })).ndjson);
console.log((await workbook.inspect({ kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#SPILL!', options: { useRegex: true, maxResults: 10 }, summary: 'Template error scan', maxChars: 1000 })).ndjson);

// Render every data column and both the instructions and column dictionary.
for (const [name, sheetName, range] of [
  ['order-identity', 'Data_Order', 'A1:M5'],
  ['order-items', 'Data_Order', 'N1:Z5'],
  ['guide', 'Panduan', 'A1:B15'],
  ['columns-1', 'Panduan', 'A17:B30'],
  ['columns-2', 'Panduan', `A31:B${lastGuideRow}`]
]) {
  const preview = await workbook.render({ sheetName, range, scale: 1, format: 'png' });
  await fs.writeFile(path.join(outputDir, `${name}.png`), new Uint8Array(await preview.arrayBuffer()));
}

const outputPath = path.join(outputDir, salesOrderTemplate.fileName);
await (await SpreadsheetFile.exportXlsx(workbook)).save(outputPath);
const assetPath = path.join(root, 'public', salesOrderTemplate.assetPath);
await fs.mkdir(path.dirname(assetPath), { recursive: true });
await fs.copyFile(outputPath, assetPath);
console.log(`Verified ${groups.size} example orders and exported ${keys.length} columns to ${assetPath}`);
