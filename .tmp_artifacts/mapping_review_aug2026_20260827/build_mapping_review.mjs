import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = "/Users/macairm2/www/new_budimas";
const auditRoot = path.join(root, ".tmp_audit/sqlserver_aug2026_bdm_tmp");
const outputDir = path.join(root, "outputs/mapping_review_aug2026_20260827");
const outputPath = path.join(outputDir, "Review_Mapping_BDM_TMP_Agustus_2026.xlsx");

const bdmReview = path.join(auditRoot, "review_bdm_solo_aug2026_01_26_r2_v3");
const tmpReview = path.join(auditRoot, "review_tmp_solo_aug2026_01_26_r2_v3");
const bdmUom = path.join(auditRoot, "review_bdm_uom_v4");
const tmpUom = path.join(auditRoot, "review_tmp_uom_v4");

function parseCsv(text) {
  const rows = [];
  let row = [];
  let value = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted) {
      if (char === '"') {
        if (text[index + 1] === '"') {
          value += '"';
          index += 1;
        } else {
          quoted = false;
        }
      } else {
        value += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      row.push(value);
      value = "";
    } else if (char === "\n") {
      row.push(value.replace(/\r$/, ""));
      rows.push(row);
      row = [];
      value = "";
    } else {
      value += char;
    }
  }
  if (value.length > 0 || row.length > 0) {
    row.push(value.replace(/\r$/, ""));
    rows.push(row);
  }
  return rows;
}

async function records(filePath) {
  const matrix = parseCsv(await fs.readFile(filePath, "utf8"));
  const headers = (matrix.shift() ?? []).map((header, index) => (index === 0 ? header.replace(/^\uFEFF/, "") : header));
  return matrix
    .filter((row) => row.some((value) => String(value).trim() !== ""))
    .map((row) => Object.fromEntries(headers.map((header, index) => [header, row[index] ?? ""])));
}

function cellAddress(column, row) {
  return `${column}${row}`;
}

function styleTitle(sheet, lastColumn, title, subtitle) {
  sheet.mergeCells(`A1:${lastColumn}1`);
  sheet.getRange(`A1:${lastColumn}1`).values = [[title]];
  sheet.getRange(`A1:${lastColumn}1`).format = {
    fill: "#0F172A",
    font: { bold: true, color: "#FFFFFF" },
    horizontalAlignment: "left",
    verticalAlignment: "center",
  };
  sheet.getRange(`A1:${lastColumn}1`).format.rowHeight = 28;
  sheet.mergeCells(`A2:${lastColumn}2`);
  sheet.getRange(`A2:${lastColumn}2`).values = [[subtitle]];
  sheet.getRange(`A2:${lastColumn}2`).format = {
    fill: "#E2E8F0",
    font: { color: "#334155" },
    horizontalAlignment: "left",
    verticalAlignment: "center",
    wrapText: true,
  };
  sheet.getRange(`A2:${lastColumn}2`).format.rowHeight = 30;
  sheet.showGridLines = false;
}

function formatHeader(range) {
  range.format = {
    fill: "#1D4ED8",
    font: { bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#1E3A8A" },
  };
  range.format.rowHeight = 32;
}

function setColumnWidths(sheet, lastRow, widths) {
  for (const [column, width] of Object.entries(widths)) {
    sheet.getRange(`${column}1:${column}${lastRow}`).format.columnWidth = width;
  }
}

function addStatusFormatting(range) {
  range.conditionalFormats.add("containsText", {
    text: "ambiguous",
    format: { fill: "#FEE2E2", font: { color: "#991B1B", bold: true } },
  });
  range.conditionalFormats.add("containsText", {
    text: "missing",
    format: { fill: "#FFEDD5", font: { color: "#9A3412", bold: true } },
  });
  range.conditionalFormats.add("containsText", {
    text: "outside",
    format: { fill: "#FEF3C7", font: { color: "#92400E", bold: true } },
  });
}

function addDecisionFormatting(range) {
  range.conditionalFormats.add("containsBlanks", {
    format: { fill: "#FEF3C7", font: { color: "#92400E" } },
  });
  range.conditionalFormats.add("containsText", {
    text: "approve",
    format: { fill: "#DCFCE7", font: { color: "#166534", bold: true } },
  });
  range.conditionalFormats.add("containsText", {
    text: "skip",
    format: { fill: "#E2E8F0", font: { color: "#475569" } },
  });
}

function normalizedStoreName(value) {
  return String(value ?? "")
    .normalize("NFKD")
    .toLocaleLowerCase("id-ID")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^\p{L}\p{N}]/gu, "");
}

function candidatePairs(row) {
  const branchIds = String(row.target_branch_candidate_ids ?? "").trim();
  const globalIds = String(row.target_global_candidate_ids ?? "").trim();
  const useBranch = branchIds.length > 0;
  const ids = (useBranch ? branchIds : globalIds).split(",").map((value) => value.trim()).filter(Boolean);
  const rawNames = String(useBranch ? row.target_branch_candidate_names ?? "" : row.target_global_candidate_names ?? "");
  const names = rawNames.split("|").map((value) => value.replace(/\s*\[cabang\s+\d+\]\s*$/iu, "").trim());
  return ids.map((id, index) => ({ id, name: names[index] ?? "" })).filter((candidate) => /^\d+$/.test(candidate.id));
}

function resolveBdmManualCustomers(rows, candidateRows) {
  const candidatesByKey = new Map(candidateRows.map((row) => [String(row.source_key_1 ?? "").trim().toLowerCase(), row]));
  return rows.map((row) => {
    const candidateRow = candidatesByKey.get(String(row.source_key_1 ?? "").trim().toLowerCase());
    const sourceName = normalizedStoreName(row.source_name);
    const matches = candidateRow
      ? candidatePairs(candidateRow).filter((candidate) => sourceName && normalizedStoreName(candidate.name) === sourceName)
      : [];
    if (matches.length === 0) {
      return {
        ...row,
        reference_status: "Skip — nama toko tidak sama",
        reference_target_id: "",
        reference_name_match: "no",
        reviewer_note: "Dilewati: tidak ada kandidat PostgreSQL dengan nama toko yang sama; tidak dimasukkan ke PostgreSQL.",
      };
    }
    const selected = [...matches].sort((left, right) => Number(left.id) - Number(right.id))[0];
    const tieNote = matches.length > 1 ? " Kandidat nama sama lebih dari satu; dipilih ID terkecil." : "";
    return {
      ...row,
      reference_status: matches.length > 1 ? "Nama sama ganda — ID terkecil" : "Nama sama — pilih target",
      reference_target_id: selected.id,
      reference_name_match: "yes",
      reviewer_note: `Dipilih berdasarkan nama toko yang sama: ${selected.name} (ID ${selected.id}).${tieNote}`,
    };
  });
}

function setupReviewSheet({ workbook, name, subtitle, rows, kind, tableName, reviewMode = true }) {
  const sheet = workbook.worksheets.add(name);
  const isCustomer = kind === "customer";
  const headers = isCustomer
    ? ["Kode Customer", "Nama Customer", "Status", "Kandidat Target ID", "Scope", "Cocok Nama", reviewMode ? "Keputusan" : "Status Proses", reviewMode ? "Target ID Disetujui" : "Target Customer PostgreSQL", "Catatan Reviewer", "Sumber", "Entity"]
    : ["Jenis", "Kode 1", "Kode 2", "Nama Sumber", "Status", "Kandidat Target ID", "Keputusan", "Target ID Disetujui", "Catatan Reviewer", "Sumber"];
  const lastColumn = isCustomer ? "K" : "J";
  styleTitle(sheet, lastColumn, name, subtitle);
  sheet.getRange(`A4:${lastColumn}4`).values = [headers];
  formatHeader(sheet.getRange(`A4:${lastColumn}4`));
  const data = isCustomer
    ? rows.map((row) => [
        row.source_key_1,
        row.source_name,
        row.review_status,
        row.suggested_target_id,
        row.candidate_scope,
        reviewMode ? row.name_match : (row.reference_name_match || row.name_match),
        reviewMode ? row.decision : (row.reference_status || "referensi_bdm_tidak_diinput"),
        reviewMode ? row.approved_target_id : (row.reference_target_id || ""),
        row.reviewer_note,
        row.source_system,
        row.entity_type,
      ])
    : rows.map((row) => [
        row.entity_type,
        row.source_key_1,
        row.source_key_2,
        row.source_name,
        row.review_status,
        row.suggested_target_id,
        row.decision,
        row.approved_target_id,
        row.reviewer_note,
        row.source_system,
      ]);
  const firstDataRow = 5;
  const lastRow = firstDataRow + data.length - 1;
  sheet.getRange(`A${firstDataRow}:${lastColumn}${lastRow}`).values = data;
  const table = sheet.tables.add(`A4:${lastColumn}${lastRow}`, true, tableName);
  table.showFilterButton = true;
  sheet.freezePanes.freezeRows(4);
  sheet.freezePanes.freezeColumns(isCustomer ? 2 : 3);
  const statusColumn = isCustomer ? "C" : "E";
  const decisionColumn = isCustomer ? "G" : "G";
  addStatusFormatting(sheet.getRange(`${statusColumn}${firstDataRow}:${statusColumn}${lastRow}`));
  if (reviewMode) {
    addDecisionFormatting(sheet.getRange(`${decisionColumn}${firstDataRow}:${decisionColumn}${lastRow}`));
    sheet.getRange(`${decisionColumn}${firstDataRow}:${decisionColumn}${lastRow}`).dataValidation = {
      rule: {
        type: "list",
        values: isCustomer
          ? ["approve_exact", "approve_manual", "approve_created", "approve_cross_branch", "skip"]
          : ["approve_exact", "approve_manual", "approve_created", "skip"],
      },
    };
  } else {
    sheet.getRange(`${decisionColumn}${firstDataRow}:${decisionColumn}${lastRow}`).format = { fill: "#E2E8F0", font: { color: "#475569", italic: true } };
    sheet.getRange(`${decisionColumn}${firstDataRow}:${decisionColumn}${lastRow}`).conditionalFormats.add("containsText", {
      text: "Nama sama",
      format: { fill: "#DCFCE7", font: { color: "#166534", bold: true } },
    });
    sheet.getRange(`${decisionColumn}${firstDataRow}:${decisionColumn}${lastRow}`).conditionalFormats.add("containsText", {
      text: "Skip",
      format: { fill: "#FEE2E2", font: { color: "#991B1B", bold: true } },
    });
  }
  sheet.getRange(`A${firstDataRow}:${lastColumn}${lastRow}`).format.verticalAlignment = "top";
  sheet.getRange(`B${firstDataRow}:B${lastRow}`).format.wrapText = true;
  sheet.getRange(`${decisionColumn}${firstDataRow}:${decisionColumn}${lastRow}`).format.wrapText = true;
  sheet.getRange(`I${firstDataRow}:I${lastRow}`).format.wrapText = true;
  setColumnWidths(sheet, lastRow, isCustomer
    ? { A: 18, B: 32, C: 32, D: 18, E: 18, F: 13, G: 24, H: 20, I: 42, J: 18, K: 13 }
    : { A: 14, B: 20, C: 18, D: 34, E: 32, F: 20, G: 22, H: 20, I: 42, J: 18 });
  return { sheet, lastRow, reviewColumn: decisionColumn, dataRows: data.length, lastColumn, reviewMode };
}

function setupUomSheet({ workbook, name, subtitle, rows, tableName }) {
  const sheet = workbook.worksheets.add(name);
  const headers = [
    "Sumber", "Principal", "SKU", "Nama Produk", "Target Produk ID", "Base UOM", "Pack UOM", "Faktor", "Konfigurasi UOM Target Saat Ini", "Status", "Aksi Direkomendasikan", "Prasyarat", "Keputusan",
  ];
  styleTitle(sheet, "M", name, subtitle);
  sheet.getRange("A4:M4").values = [headers];
  formatHeader(sheet.getRange("A4:M4"));
  const data = rows.map((row) => [
    row.source_system,
    row.principal_code,
    row.sku,
    row.source_product_name,
    row.target_product_ids,
    row.source_base_uom,
    row.source_pack_uom,
    row.source_pack_factor,
    row.current_target_uom_configuration,
    row.readiness_status,
    row.recommended_action,
    row.apply_after,
    "",
  ]);
  const firstDataRow = 5;
  const lastRow = firstDataRow + data.length - 1;
  sheet.getRange(`A${firstDataRow}:M${lastRow}`).values = data;
  const table = sheet.tables.add(`A4:M${lastRow}`, true, tableName);
  table.showFilterButton = true;
  sheet.freezePanes.freezeRows(4);
  sheet.freezePanes.freezeColumns(3);
  addStatusFormatting(sheet.getRange(`J${firstDataRow}:J${lastRow}`));
  addDecisionFormatting(sheet.getRange(`M${firstDataRow}:M${lastRow}`));
  sheet.getRange(`M${firstDataRow}:M${lastRow}`).dataValidation = {
    rule: { type: "list", values: ["siap_apply", "tahan", "perlu_mapping_produk", "skip"] },
  };
  sheet.getRange(`A${firstDataRow}:M${lastRow}`).format.verticalAlignment = "top";
  sheet.getRange(`D${firstDataRow}:D${lastRow}`).format.wrapText = true;
  sheet.getRange(`I${firstDataRow}:L${lastRow}`).format.wrapText = true;
  setColumnWidths(sheet, lastRow, { A: 18, B: 14, C: 22, D: 36, E: 18, F: 12, G: 12, H: 12, I: 48, J: 30, K: 44, L: 34, M: 22 });
  return { sheet, lastRow, reviewColumn: "M", dataRows: data.length, lastColumn: "M", reviewMode: true };
}

function setupInstructions(workbook) {
  const sheet = workbook.worksheets.add("Petunjuk");
  styleTitle(sheet, "F", "Petunjuk Peninjauan", "Workbook ini hanya untuk peninjauan mapping sebelum data bisnis dimasukkan ke PostgreSQL.");
  const rows = [
    ["Bagian", "Yang ditinjau", "Keputusan yang diisi", "Catatan"],
    ["Customer BDM", "Kasus manual BDM dan pasangan BDM→PostgreSQL yang sudah cocok", "Tidak perlu diisi manual", "Pilih kandidat dengan nama toko sama; jika ganda pilih ID terkecil. Tanpa nama toko sama, skip dan jangan dimasukkan ke PostgreSQL."],
    ["Customer TMP", "Kode, nama, kandidat target, dan scope cabang", "approve_exact / approve_cross_branch / approve_manual / skip", "Ini satu-satunya queue customer manual aktif. Customer sama tidak diduplikasi; data master diambil dari TMP saja."],
    ["Master BDM/TMP", "Principal, sales, dan produk tanpa mapping tunggal", "approve_exact / approve_manual / approve_created / skip", "Isi Target ID Disetujui setelah kandidat diverifikasi."],
    ["UOM BDM/TMP", "PCS/CT dan faktor konversi per produk", "siap_apply / tahan / perlu_mapping_produk / skip", "Jangan mengubah UOM yang sudah ekuivalen hanya karena ada level unit antara."],
    ["Nomor Dokumen", "Aturan nomor target", "Tidak perlu diedit", "BDM-SLO/<nota> dan TMP-SLO/<nota>; nomor asal tetap dicatat."],
    ["SQL Server", "Sumber data", "Tidak perlu tindakan", "Proses mengambil data secara read-only; tidak ada perubahan di SQL Server."],
  ];
  sheet.getRange("A4:D10").values = rows;
  formatHeader(sheet.getRange("A4:D4"));
  sheet.getRange("A5:D10").format.wrapText = true;
  sheet.getRange("A5:D10").format.verticalAlignment = "top";
  sheet.getRange("A4:D10").format.borders = { preset: "outside", style: "thin", color: "#CBD5E1" };
  setColumnWidths(sheet, 10, { A: 22, B: 40, C: 38, D: 52, E: 2, F: 2 });
  sheet.freezePanes.freezeRows(4);
  return { sheet, lastRow: 10, lastColumn: "D" };
}

function setupDocumentPolicy(workbook) {
  const sheet = workbook.worksheets.add("Nomor Dokumen");
  styleTitle(sheet, "F", "Kebijakan Nomor Dokumen", "Pemisah dokumen BDM dan TMP agar nota/faktur dengan nomor sama tidak saling bertabrakan di PostgreSQL.");
  const values = [
    ["Sumber", "Perusahaan", "Cabang", "Prefix Target", "Contoh Nota Asli", "Nomor Target"],
    ["bdm_solo_dist", "BMM", "Solo", "BDM-SLO/", "INV-000123", "BDM-SLO/INV-000123"],
    ["tmp_solo_dist", "TMP", "Solo", "TMP-SLO/", "INV-000123", "TMP-SLO/INV-000123"],
    ["Catatan", "", "", "", "", "Nomor asal tetap tersimpan bersama source_system dan source_table pada registry dokumen."],
  ];
  sheet.getRange("A4:F7").values = values;
  formatHeader(sheet.getRange("A4:F4"));
  sheet.getRange("A5:F7").format.wrapText = true;
  sheet.getRange("A4:F7").format.borders = { preset: "outside", style: "thin", color: "#CBD5E1" };
  sheet.getRange("D5:D6").format = { fill: "#DCFCE7", font: { bold: true, color: "#166534" } };
  setColumnWidths(sheet, 7, { A: 22, B: 16, C: 14, D: 18, E: 22, F: 32 });
  return { sheet, lastRow: 7, lastColumn: "F" };
}

const [customerBdm, customerTmp, queueBdm, queueTmp, uomBdm, uomTmp, customerBdmCandidates] = await Promise.all([
  records(path.join(bdmReview, "customer_mapping_manual_review.csv")),
  records(path.join(tmpReview, "customer_mapping_manual_review.csv")),
  records(path.join(bdmReview, "mapping_review_queue.csv")),
  records(path.join(tmpReview, "mapping_review_queue.csv")),
  records(path.join(bdmUom, "uom_sync_plan.csv")),
  records(path.join(tmpUom, "uom_sync_plan.csv")),
  records(path.join(bdmReview, "customer_candidates.csv")),
]);

const masterBdm = queueBdm.filter((row) => row.entity_type !== "customer");
const masterTmp = queueTmp.filter((row) => row.entity_type !== "customer");
const customerBdmResolved = resolveBdmManualCustomers(customerBdm, customerBdmCandidates);
const bdmNameMatched = customerBdmResolved.filter((row) => row.reference_target_id).length;
const bdmNameSkipped = customerBdmResolved.length - bdmNameMatched;

const workbook = Workbook.create();
const dashboard = workbook.worksheets.add("Ringkasan");
styleTitle(dashboard, "H", "Review Mapping BDM & TMP — Agustus 2026", "Workbook peninjauan sebelum data dari SQL Server dimasukkan ke PostgreSQL. SQL Server tetap read-only.");

const reviewSheets = [];
reviewSheets.push(setupReviewSheet({ workbook, name: "Customer BDM", subtitle: "Referensi BDM dengan aturan nama toko: pilih nama sama, kandidat ganda memakai ID terkecil, dan tanpa nama sama dilewati. Sheet ini bukan queue pengisian manual.", rows: customerBdmResolved, kind: "customer", tableName: "CustomerBdmReference", reviewMode: false }));
reviewSheets.push(setupReviewSheet({ workbook, name: "Customer TMP", subtitle: "Queue customer manual aktif. TMP adalah satu-satunya sumber untuk membuat atau memperbarui data master customer.", rows: customerTmp, kind: "customer", tableName: "CustomerTmpReview" }));
reviewSheets.push(setupReviewSheet({ workbook, name: "Master BDM", subtitle: "Principal, sales, dan produk BDM yang belum memiliki mapping aman. Isi Keputusan dan Target ID Disetujui.", rows: masterBdm, kind: "master", tableName: "MasterBdmReview" }));
reviewSheets.push(setupReviewSheet({ workbook, name: "Master TMP", subtitle: "Principal, sales, dan produk TMP yang belum memiliki mapping aman. Isi Keputusan dan Target ID Disetujui.", rows: masterTmp, kind: "master", tableName: "MasterTmpReview" }));
reviewSheets.push(setupUomSheet({ workbook, name: "UOM BDM", subtitle: "Hanya SKU BDM yang belum siap secara UOM. CT pada level lebih tinggi tetap dianggap setara bila faktor konversinya sama.", rows: uomBdm, tableName: "UomBdmReview" }));
reviewSheets.push(setupUomSheet({ workbook, name: "UOM TMP", subtitle: "Hanya SKU TMP yang belum siap secara UOM. Isi keputusan setelah produk target telah jelas.", rows: uomTmp, tableName: "UomTmpReview" }));
const instructions = setupInstructions(workbook);
const documentPolicy = setupDocumentPolicy(workbook);

const summaryRows = [
  ["Area Review", "Total", "Keputusan Siap", "Sisa"],
  ["Customer BDM (manual referensi)", null, null, null],
  ["Customer TMP (manual aktif)", null, null, null],
  ["Master BDM", null, null, null],
  ["Master TMP", null, null, null],
  ["UOM BDM", null, null, null],
  ["UOM TMP", null, null, null],
];
dashboard.getRange("A4:D10").values = summaryRows;
formatHeader(dashboard.getRange("A4:D4"));
for (const [index, item] of reviewSheets.entries()) {
  const dashboardRow = 5 + index;
  const sheetName = item.sheet.name;
  const firstData = 5;
  const sourceEnd = item.lastRow;
  dashboard.getRange(`B${dashboardRow}`).formulas = [[`=COUNTA('${sheetName}'!A${firstData}:A${sourceEnd})`]];
  if (item.reviewMode) {
    dashboard.getRange(`C${dashboardRow}`).formulas = [[`=COUNTIF('${sheetName}'!${item.reviewColumn}${firstData}:${item.reviewColumn}${sourceEnd},"approve*")+COUNTIF('${sheetName}'!${item.reviewColumn}${firstData}:${item.reviewColumn}${sourceEnd},"siap_apply")`]];
    dashboard.getRange(`D${dashboardRow}`).formulas = [[`=B${dashboardRow}-C${dashboardRow}`]];
  } else {
    dashboard.getRange(`C${dashboardRow}:D${dashboardRow}`).values = [["Tidak diinput", "Referensi"]];
  }
}
dashboard.getRange("A4:D10").format.borders = { preset: "outside", style: "thin", color: "#CBD5E1" };
dashboard.getRange("B5:D10").format.numberFormat = "#,##0";

dashboard.getRange("F4:H4").merge();
dashboard.getRange("F4:H4").values = [["Status & Kebijakan"]];
dashboard.getRange("F4:H4").format = { fill: "#0F766E", font: { bold: true, color: "#FFFFFF" }, horizontalAlignment: "center" };
dashboard.getRange("F5:G12").values = [
  ["Customer BDM sudah diregistrasi", 23656],
  ["Customer TMP sudah diregistrasi", 11362],
  ["BDM nama toko sama", `${bdmNameMatched} → map`],
  ["BDM tanpa nama sama", `${bdmNameSkipped} → skip`],
  ["BDM cocok PostgreSQL", "Timpa otomatis"],
  ["Manual customer aktif", "TMP saja"],
  ["Prioritas customer sama", "TMP menimpa BDM"],
  ["Tabel publik ERP diubah", "Belum"],
];
dashboard.getRange("F5:G12").format.borders = { preset: "outside", style: "thin", color: "#CBD5E1" };
dashboard.getRange("G5:G8").format.numberFormat = "#,##0";
dashboard.getRange("F5:F12").format = { fill: "#ECFDF5", font: { bold: true, color: "#065F46" } };

dashboard.mergeCells("A13:H13");
dashboard.getRange("A13:H13").values = [["Urutan kerja berikutnya"]];
dashboard.getRange("A13:H13").format = { fill: "#1D4ED8", font: { bold: true, color: "#FFFFFF" }, horizontalAlignment: "left" };
dashboard.mergeCells("A14:H16");
dashboard.getRange("A14:H16").values = [["1. Isi keputusan pada sheet review.  2. Selesaikan principal/produk/sales dan UOM yang ditahan.  3. Pada jam aktivitas rendah, ambil extract final SQL Server secara read-only.  4. Baru masukkan master dan transaksi ke PostgreSQL dengan nomor dokumen BDM-SLO/ atau TMP-SLO/."]];
dashboard.getRange("A14:H16").format = { fill: "#EFF6FF", font: { color: "#1E3A8A" }, wrapText: true, verticalAlignment: "top", borders: { preset: "outside", style: "thin", color: "#BFDBFE" } };
dashboard.getRange("A14:H16").format.rowHeight = 42;
setColumnWidths(dashboard, 16, { A: 30, B: 16, C: 20, D: 16, E: 3, F: 34, G: 18, H: 18 });
dashboard.freezePanes.freezeRows(4);

const inspection = await workbook.inspect({
  kind: "table",
  range: "Ringkasan!A1:H16",
  include: "values,formulas",
  tableMaxRows: 20,
  tableMaxCols: 10,
});
console.log(inspection.ndjson);
const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "formula error scan",
});
console.log(formulaErrors.ndjson);

await fs.mkdir(outputDir, { recursive: true });
for (const item of [
  { sheetName: "Ringkasan", range: "A1:H16", file: "preview_ringkasan.png" },
  { sheetName: "Customer BDM", range: "A1:K18", file: "preview_customer_bdm.png" },
  { sheetName: "Customer TMP", range: "A1:K18", file: "preview_customer_tmp.png" },
  { sheetName: "Master BDM", range: "A1:J18", file: "preview_master_bdm.png" },
  { sheetName: "Master TMP", range: "A1:J18", file: "preview_master_tmp.png" },
  { sheetName: "UOM BDM", range: "A1:M18", file: "preview_uom_bdm.png" },
  { sheetName: "UOM TMP", range: "A1:M18", file: "preview_uom_tmp.png" },
  { sheetName: "Petunjuk", range: "A1:D10", file: "preview_petunjuk.png" },
  { sheetName: "Nomor Dokumen", range: "A1:F7", file: "preview_nomor_dokumen.png" },
]) {
  const png = await workbook.render({ sheetName: item.sheetName, range: item.range, scale: 1.25, format: "png" });
  await fs.writeFile(path.join(outputDir, item.file), new Uint8Array(await png.arrayBuffer()));
}

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);
console.log(JSON.stringify({ outputPath, counts: { customerBdm: customerBdm.length, customerTmp: customerTmp.length, masterBdm: masterBdm.length, masterTmp: masterTmp.length, uomBdm: uomBdm.length, uomTmp: uomTmp.length }, instructionRows: instructions.lastRow, documentPolicyRows: documentPolicy.lastRow }, null, 2));
