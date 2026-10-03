export function escapePrintHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

export function formatPrintDate(value, fallback = '-') {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString('id-ID', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric'
  });
}

export function formatPrintNumber(value, options = {}) {
  return Number(value || 0).toLocaleString('en-US', {
    minimumFractionDigits: options.minimumFractionDigits ?? 2,
    maximumFractionDigits: options.maximumFractionDigits ?? 2
  });
}

export function reservePrintWindow(options = {}) {
  const width = options.width || 1280;
  const height = options.height || 760;
  return window.open('', '_blank', `width=${width},height=${height}`);
}

export function openPrintHtml(title, html, options = {}) {
  const win = options.printWindow || reservePrintWindow(options);
  if (!win) return false;

  win.document.write(html);
  win.document.close();
  win.focus();

  if (options.autoPrint !== false) {
    window.setTimeout(() => win.print(), options.delay || 250);
  }

  return true;
}

function firstValue(row, keys = [], fallback = '') {
  const key = keys.find((item) => row?.[item] !== undefined && row?.[item] !== null && row?.[item] !== '');
  return key ? row[key] : fallback;
}

function formatQty(value) {
  const quantity = Number(value || 0);
  return Number.isFinite(quantity) ? quantity.toLocaleString('id-ID') : '0';
}

function masterUomLabel(row, level) {
  return firstValue(
    row,
    [`puom${level}_kode`, `puom${level}_nama`, `uom${level}_label`],
    ''
  );
}

function formatUomQuantity(value, label) {
  const quantity = formatQty(value);
  return label ? `${quantity} ${label}` : quantity;
}

function uomText(row) {
  const uoms = [
    {
      value: firstValue(row, ['karton_order', 'karton_shipped', 'karton_delivered'], 0),
      label: masterUomLabel(row, 3)
    },
    {
      value: firstValue(row, ['box_order', 'unit_order', 'unit', 'box_shipped', 'box_delivered'], 0),
      label: masterUomLabel(row, 2)
    },
    {
      value: firstValue(row, ['pieces_order', 'satuan_order', 'satuan', 'pieces_shipped', 'pieces_delivered'], 0),
      label: masterUomLabel(row, 1)
    }
  ];

  const active = uoms.filter((item) => Number(item.value || 0) > 0);
  if (!active.length) return '-';
  return active.map((item) => formatUomQuantity(item.value, item.label)).join(' / ');
}

function salesDocumentStyles() {
  return `
    @page { size: 13.5in 7.5in landscape; margin: 7mm 9mm; }
    * { box-sizing: border-box; }
    html,
    body {
      margin: 0;
      background: #fff;
      color: #000;
      font-family: "Courier New", Courier, monospace;
      font-size: 13px;
      line-height: 1.25;
    }
    .sheet {
      position: relative;
      width: 100%;
      min-height: 7.1in;
      padding: 8mm 10mm 7mm;
      border: 1px solid #111;
      overflow: hidden;
    }
    .sheet > *:not(.document-watermark) {
      position: relative;
      z-index: 1;
    }
    .document-watermark {
      position: absolute;
      top: 50%;
      left: 50%;
      z-index: 0;
      transform: translate(-50%, -50%) rotate(-24deg);
      border: 6px solid currentColor;
      border-radius: 12px;
      padding: 10px 24px;
      font-family: Arial, Helvetica, sans-serif;
      font-size: 88px;
      font-weight: 900;
      line-height: 1;
      letter-spacing: 10px;
      opacity: 0.12;
      pointer-events: none;
      white-space: nowrap;
    }
    .document-watermark.paid { color: #15803d; }
    .document-watermark.canceled { color: #dc2626; }
    .document-copy {
      margin-top: 4px;
      text-align: center;
      font-size: 11px;
    }
    .header-grid {
      display: grid;
      grid-template-columns: 35% 30% 35%;
      gap: 12px;
      align-items: start;
    }
    .company h1 {
      margin: 0 0 5px;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 22px;
      font-weight: 800;
      letter-spacing: 0;
    }
    .company div,
    .customer div {
      font-size: 13px;
      white-space: pre-wrap;
    }
    .rule {
      margin-top: 8px;
      border-top: 1px dashed #111;
      height: 1px;
    }
    .document-code {
      width: 72%;
      margin: 0 auto 10px;
      border: 3px double #111;
      padding: 4px 10px;
      text-align: center;
      font-size: 34px;
      font-weight: 900;
      line-height: 1;
      letter-spacing: 1px;
    }
    .document-title {
      text-align: center;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 18px;
      font-weight: 800;
      letter-spacing: 1px;
      text-transform: uppercase;
    }
    .document-number {
      margin-top: 24px;
      text-align: center;
      font-size: 13px;
    }
    .customer .label {
      margin-bottom: 2px;
      font-size: 12px;
      font-weight: 700;
    }
    .meta-row {
      display: grid;
      grid-template-columns: 35% 30% 35%;
      gap: 12px;
      margin-top: 8px;
      align-items: start;
      font-size: 19px;
    }
    .meta-center {
      padding-top: 8px;
      text-align: center;
      font-size: 13px;
    }
    .meta-right {
      font-size: 16px;
    }
    .print-table {
      width: 100%;
      margin-top: 24px;
      border-collapse: collapse;
      table-layout: fixed;
    }
    .print-table th,
    .print-table td {
      border: 0;
      padding: 3px 5px;
      vertical-align: top;
      overflow-wrap: anywhere;
    }
    .print-table th {
      font-family: Georgia, "Times New Roman", serif;
      font-size: 13px;
      font-style: italic;
      font-weight: 700;
    }
    .print-table td {
      font-size: 13px;
    }
    .num { text-align: right; white-space: nowrap; }
    .center { text-align: center; }
    .nowrap { white-space: nowrap; }
    .bottom-grid {
      display: grid;
      grid-template-columns: 58% 42%;
      gap: 18px;
      margin-top: 10px;
    }
    .notes {
      margin-top: 22px;
      padding-left: 24px;
      font-size: 12px;
      white-space: pre-wrap;
    }
    .company-bank {
      margin: 14px 0 0 24px;
      font-size: 12px;
      white-space: pre-wrap;
    }
    .amount-box {
      margin-left: auto;
      width: 310px;
      font-size: 14px;
    }
    .amount-line {
      display: grid;
      grid-template-columns: 1fr 135px;
      gap: 12px;
      padding: 3px 0;
      text-align: right;
    }
    .amount-separator {
      margin: 4px 0;
      border-top: 2px solid #111;
    }
    .amount-final {
      font-size: 18px;
      font-weight: 900;
    }
    .footer-grid {
      display: grid;
      grid-template-columns: 36% 22% 20% 22%;
      gap: 10px;
      margin-top: 34px;
      align-items: end;
      font-size: 13px;
    }
    .sales-info {
      font-size: 17px;
      line-height: 1.35;
    }
    .sign-title {
      margin-bottom: 70px;
      text-align: center;
    }
    .sign-label {
      text-align: center;
      white-space: nowrap;
    }
    .delivery-spacer {
      min-height: 105px;
    }
    @media print {
      body { margin: 0; }
      .sheet { border: 1px solid #111; }
    }
  `;
}

export function buildSalesDocumentHtml({
  type = 'invoice',
  header = {},
  rows = [],
  company = {},
  title
} = {}) {
  const isDelivery = type === 'delivery';
  const docTitle = title || (isDelivery ? 'Surat Jalan' : 'Faktur Penjualan');
  const noFaktur = header.noFaktur || header.noOrder || '-';
  const subtotal = Number(header.subtotal ?? rows.reduce((total, row) => total + Number(firstValue(row, ['subtotalorder', 'subtotal', 'total_harga'], 0)), 0));
  const discountTotal = Number(header.discountTotal ?? rows.reduce((total, row) => total + Number(firstValue(row, ['total_nilai_discount', 'total_diskon', 'diskon_total'], 0)), 0));
  const taxTotal = Number(header.taxTotal ?? header.pajak ?? 0);
  const grandTotal = Number(header.grandTotal ?? header.totalPenjualan ?? subtotal + taxTotal);
  const printCode = header.routeStoreCode || header.routeCode || header.kodeRute || '-';

  const companyName = company.name || header.companyName || 'PT. BUDIMAS MAKMUR MULIA';
  const companyAddress = company.address || header.companyAddress || 'Jl. Serut RT 04/XII Mojosongo Solo';
  const companyPhone = company.phone || header.companyPhone || 'Telp. / Fax. (0271) 856064 (Hunting)';
  const companyEmail = company.email || header.companyEmail || 'Email : budimas.solo@yahoo.com';
  const customerLines = [
    header.customer || '-',
    header.address || header.alamat || '-'
  ].filter(Boolean).join('\n');
  const watermark = !isDelivery && ['PAID', 'BATAL'].includes(String(header.watermark || '').toUpperCase())
    ? String(header.watermark).toUpperCase()
    : '';
  const watermarkClass = watermark === 'PAID' ? 'paid' : 'canceled';
  const printCount = Number(header.printCount || 0);

  const rowsHtml = rows.length
    ? rows.map((row, index) => {
        const code = firstValue(row, ['kode_sku', 'kode_produk', 'kode_barang', 'kode'], '-');
        const name = firstValue(row, ['nama_produk', 'nama_barang', 'nama'], '-');
        const price = Number(firstValue(row, ['hargaorder', 'harga_order', 'harga_jual', 'harga'], 0));
        const lineDiscount = Number(firstValue(row, ['total_nilai_discount', 'total_diskon', 'diskon_total'], 0));
        const subtotalRow = Number(firstValue(row, ['subtotalorder', 'subtotal', 'total_harga'], 0));
        const discount1 = Number(firstValue(row, ['v1r_diskon', 'diskon1', 'diskon_1'], 0));
        const discount2 = Number(firstValue(row, ['v2r_diskon', 'v2p_diskon', 'diskon2', 'diskon_2'], 0));
        const discount3 = Number(firstValue(row, ['v3r_diskon', 'v3p_diskon', 'diskon3', 'diskon_3'], 0));
        const uom = uomText(row);

        if (isDelivery) {
          return `
            <tr>
              <td class="num">${index + 1}.</td>
              <td>${escapePrintHtml(code)}</td>
              <td>${escapePrintHtml(name)}</td>
              <td class="num">${escapePrintHtml(uom)}</td>
            </tr>
          `;
        }

        return `
          <tr>
            <td class="num">${index + 1}.</td>
            <td>${escapePrintHtml(code)}</td>
            <td>${escapePrintHtml(name)}</td>
            <td class="num">${escapePrintHtml(uom)}</td>
            <td class="num">${formatPrintNumber(price)}</td>
            <td class="num">${formatPrintNumber(discount1)}</td>
            <td class="num">${formatPrintNumber(discount2)}</td>
            <td class="num">${formatPrintNumber(discount3)}</td>
            <td class="num">${formatPrintNumber(lineDiscount)}</td>
            <td class="num">${formatPrintNumber(subtotalRow)}</td>
          </tr>
        `;
      }).join('')
    : `<tr><td colspan="${isDelivery ? 4 : 10}" class="center">Tidak ada detail produk.</td></tr>`;

  const tableHeader = isDelivery
    ? `
      <tr>
        <th style="width: 4%;"> </th>
        <th style="width: 14%;">Kode</th>
        <th>Nama</th>
        <th style="width: 20%;">UOM</th>
      </tr>
    `
    : `
      <tr>
        <th style="width: 4%;"> </th>
        <th style="width: 13%;">Kode</th>
        <th>Nama</th>
        <th style="width: 14%;">UOM</th>
        <th style="width: 9%;">Harga</th>
        <th style="width: 6%;">#1</th>
        <th style="width: 6%;">#2</th>
        <th style="width: 6%;">#3</th>
        <th style="width: 10%;">Tot.Disc</th>
        <th style="width: 10%;">Jumlah Harga</th>
      </tr>
    `;

  return `
    <!doctype html>
    <html lang="id">
      <head>
        <meta charset="utf-8" />
        <title>${escapePrintHtml(docTitle)} - ${escapePrintHtml(noFaktur)}</title>
        <style>${salesDocumentStyles()}</style>
      </head>
      <body>
        <section class="sheet">
          ${watermark ? `<div class="document-watermark ${watermarkClass}">${escapePrintHtml(watermark)}</div>` : ''}
          <div class="header-grid">
            <div class="company">
              <h1>${escapePrintHtml(companyName)}</h1>
              <div>${escapePrintHtml(companyAddress)}</div>
              <div>${escapePrintHtml(companyPhone)}</div>
              <div>${escapePrintHtml(companyEmail)}</div>
              <div class="rule"></div>
            </div>
            <div>
              <div class="document-code">${escapePrintHtml(printCode)}</div>
              <div class="document-title">${escapePrintHtml(docTitle)}</div>
              <div class="document-number">${isDelivery ? 'No. Surat Jalan' : 'No. Faktur'} : ${escapePrintHtml(noFaktur)}</div>
              ${!isDelivery && printCount > 0 ? `<div class="document-copy">Cetak ke-${escapePrintHtml(printCount)}</div>` : ''}
            </div>
            <div class="customer">
              <div class="label">Kepada Yth.</div>
              <div>Kode Customer : ${escapePrintHtml(header.kodeCustomer || '-')}</div>
              <div>${escapePrintHtml(customerLines)}</div>
              <div class="rule"></div>
            </div>
          </div>

          <div class="meta-row">
            <div>Tanggal : &nbsp; ${escapePrintHtml(formatPrintDate(header.date))}</div>
            <div class="meta-center"></div>
            <div class="meta-right">${isDelivery ? `PO : ${escapePrintHtml(header.po || header.noPo || '-')}` : `Jatuh Tempo : &nbsp; ${escapePrintHtml(formatPrintDate(header.dueDate))}`}</div>
          </div>

          <table class="print-table">
            <thead>${tableHeader}</thead>
            <tbody>${rowsHtml}</tbody>
          </table>

          ${isDelivery ? '<div class="delivery-spacer"></div>' : `
            <div class="bottom-grid">
              <div>
                <div class="notes">${escapePrintHtml(header.notes || '- Pembayaran dengan cek/BG dianggap lunas setelah diuangkan\n- Barang diterima dengan baik dan benar, maksimal komplain 2X24 jam\n- Copy bukan untuk penagihan\n- Penjualan KREDIT')}</div>
                ${header.companyBank ? `<div class="company-bank"><strong>Rekening Perusahaan:</strong>\n${escapePrintHtml(header.companyBank)}</div>` : ''}
              </div>
              <div class="amount-box">
                <div class="amount-line"><span></span><span>${formatPrintNumber(subtotal)}</span></div>
                <div class="amount-line"><span>PPn 11 %</span><span>${formatPrintNumber(taxTotal)}</span></div>
                <div class="amount-separator"></div>
                <div class="amount-line amount-final"><span></span><span>${formatPrintNumber(grandTotal)}</span></div>
              </div>
            </div>
          `}

          <div class="footer-grid">
            <div class="sales-info">
              <div>Jam&nbsp;&nbsp; : ${escapePrintHtml(header.printTime || '-')}</div>
              <div>Sales : ${escapePrintHtml(header.sales || '-')}</div>
              <div>${escapePrintHtml(header.po || header.noPo || '')}</div>
            </div>
            <div>
              <div class="sign-label">( Nama terang / Stempel )</div>
            </div>
            <div>
              <div class="sign-title">Hormat Kami</div>
              <div class="sign-label">(${escapePrintHtml(header.fakturist || '-')})</div>
            </div>
            <div>
              <div class="sign-label">( Pengirim )</div>
            </div>
          </div>
        </section>
      </body>
    </html>
  `;
}
