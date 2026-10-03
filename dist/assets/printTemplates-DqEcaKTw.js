function n(i){return String(i??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#039;")}function k(i,t="-"){if(!i)return t;const e=new Date(i);return Number.isNaN(e.getTime())?String(i):e.toLocaleDateString("id-ID",{day:"2-digit",month:"2-digit",year:"numeric"})}function r(i,t={}){return Number(i||0).toLocaleString("en-US",{minimumFractionDigits:t.minimumFractionDigits??2,maximumFractionDigits:t.maximumFractionDigits??2})}function R(i={}){const t=i.width||1280,e=i.height||760;return window.open("","_blank",`width=${t},height=${e}`)}function J(i,t,e={}){const a=e.printWindow||R(e);return a?(a.document.write(t),a.document.close(),a.focus(),e.autoPrint!==!1&&window.setTimeout(()=>a.print(),e.delay||250),!0):!1}function o(i,t=[],e=""){const a=t.find(m=>(i==null?void 0:i[m])!==void 0&&(i==null?void 0:i[m])!==null&&(i==null?void 0:i[m])!=="");return a?i[a]:e}function B(i){const t=Number(i||0);return Number.isFinite(t)?t.toLocaleString("id-ID"):"0"}function c(i,t){return o(i,[`puom${t}_kode`,`puom${t}_nama`,`uom${t}_label`],"")}function K(i,t){const e=B(i);return t?`${e} ${t}`:e}function L(i){const e=[{value:o(i,["karton_order","karton_shipped","karton_delivered"],0),label:c(i,3)},{value:o(i,["box_order","unit_order","unit","box_shipped","box_delivered"],0),label:c(i,2)},{value:o(i,["pieces_order","satuan_order","satuan","pieces_shipped","pieces_delivered"],0),label:c(i,1)}].filter(a=>Number(a.value||0)>0);return e.length?e.map(a=>K(a.value,a.label)).join(" / "):"-"}function M(){return`
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
  `}function E({type:i="invoice",header:t={},rows:e=[],company:a={},title:m}={}){const d=i==="delivery",u=m||(d?"Surat Jalan":"Faktur Penjualan"),g=t.noFaktur||t.noOrder||"-",v=Number(t.subtotal??e.reduce((s,l)=>s+Number(o(l,["subtotalorder","subtotal","total_harga"],0)),0));Number(t.discountTotal??e.reduce((s,l)=>s+Number(o(l,["total_nilai_discount","total_diskon","diskon_total"],0)),0));const h=Number(t.taxTotal??t.pajak??0),$=Number(t.grandTotal??t.totalPenjualan??v+h),w=t.routeStoreCode||t.routeCode||t.kodeRute||"-",_=a.name||t.companyName||"PT. BUDIMAS MAKMUR MULIA",N=a.address||t.companyAddress||"Jl. Serut RT 04/XII Mojosongo Solo",z=a.phone||t.companyPhone||"Telp. / Fax. (0271) 856064 (Hunting)",P=a.email||t.companyEmail||"Email : budimas.solo@yahoo.com",T=[t.customer||"-",t.address||t.alamat||"-"].filter(Boolean).join(`
`),p=!d&&["PAID","BATAL"].includes(String(t.watermark||"").toUpperCase())?String(t.watermark).toUpperCase():"",D=p==="PAID"?"paid":"canceled",b=Number(t.printCount||0),S=e.length?e.map((s,l)=>{const f=o(s,["kode_sku","kode_produk","kode_barang","kode"],"-"),x=o(s,["nama_produk","nama_barang","nama"],"-"),j=Number(o(s,["hargaorder","harga_order","harga_jual","harga"],0)),A=Number(o(s,["total_nilai_discount","total_diskon","diskon_total"],0)),F=Number(o(s,["subtotalorder","subtotal","total_harga"],0)),H=Number(o(s,["v1r_diskon","diskon1","diskon_1"],0)),U=Number(o(s,["v2r_diskon","v2p_diskon","diskon2","diskon_2"],0)),I=Number(o(s,["v3r_diskon","v3p_diskon","diskon3","diskon_3"],0)),y=L(s);return d?`
            <tr>
              <td class="num">${l+1}.</td>
              <td>${n(f)}</td>
              <td>${n(x)}</td>
              <td class="num">${n(y)}</td>
            </tr>
          `:`
          <tr>
            <td class="num">${l+1}.</td>
            <td>${n(f)}</td>
            <td>${n(x)}</td>
            <td class="num">${n(y)}</td>
            <td class="num">${r(j)}</td>
            <td class="num">${r(H)}</td>
            <td class="num">${r(U)}</td>
            <td class="num">${r(I)}</td>
            <td class="num">${r(A)}</td>
            <td class="num">${r(F)}</td>
          </tr>
        `}).join(""):`<tr><td colspan="${d?4:10}" class="center">Tidak ada detail produk.</td></tr>`,C=d?`
      <tr>
        <th style="width: 4%;"> </th>
        <th style="width: 14%;">Kode</th>
        <th>Nama</th>
        <th style="width: 20%;">UOM</th>
      </tr>
    `:`
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
    `;return`
    <!doctype html>
    <html lang="id">
      <head>
        <meta charset="utf-8" />
        <title>${n(u)} - ${n(g)}</title>
        <style>${M()}</style>
      </head>
      <body>
        <section class="sheet">
          ${p?`<div class="document-watermark ${D}">${n(p)}</div>`:""}
          <div class="header-grid">
            <div class="company">
              <h1>${n(_)}</h1>
              <div>${n(N)}</div>
              <div>${n(z)}</div>
              <div>${n(P)}</div>
              <div class="rule"></div>
            </div>
            <div>
              <div class="document-code">${n(w)}</div>
              <div class="document-title">${n(u)}</div>
              <div class="document-number">${d?"No. Surat Jalan":"No. Faktur"} : ${n(g)}</div>
              ${!d&&b>0?`<div class="document-copy">Cetak ke-${n(b)}</div>`:""}
            </div>
            <div class="customer">
              <div class="label">Kepada Yth.</div>
              <div>Kode Customer : ${n(t.kodeCustomer||"-")}</div>
              <div>${n(T)}</div>
              <div class="rule"></div>
            </div>
          </div>

          <div class="meta-row">
            <div>Tanggal : &nbsp; ${n(k(t.date))}</div>
            <div class="meta-center"></div>
            <div class="meta-right">${d?`PO : ${n(t.po||t.noPo||"-")}`:`Jatuh Tempo : &nbsp; ${n(k(t.dueDate))}`}</div>
          </div>

          <table class="print-table">
            <thead>${C}</thead>
            <tbody>${S}</tbody>
          </table>

          ${d?'<div class="delivery-spacer"></div>':`
            <div class="bottom-grid">
              <div>
                <div class="notes">${n(t.notes||`- Pembayaran dengan cek/BG dianggap lunas setelah diuangkan
- Barang diterima dengan baik dan benar, maksimal komplain 2X24 jam
- Copy bukan untuk penagihan
- Penjualan KREDIT`)}</div>
                ${t.companyBank?`<div class="company-bank"><strong>Rekening Perusahaan:</strong>
${n(t.companyBank)}</div>`:""}
              </div>
              <div class="amount-box">
                <div class="amount-line"><span></span><span>${r(v)}</span></div>
                <div class="amount-line"><span>PPn 11 %</span><span>${r(h)}</span></div>
                <div class="amount-separator"></div>
                <div class="amount-line amount-final"><span></span><span>${r($)}</span></div>
              </div>
            </div>
          `}

          <div class="footer-grid">
            <div class="sales-info">
              <div>Jam&nbsp;&nbsp; : ${n(t.printTime||"-")}</div>
              <div>Sales : ${n(t.sales||"-")}</div>
              <div>${n(t.po||t.noPo||"")}</div>
            </div>
            <div>
              <div class="sign-label">( Nama terang / Stempel )</div>
            </div>
            <div>
              <div class="sign-title">Hormat Kami</div>
              <div class="sign-label">(${n(t.fakturist||"-")})</div>
            </div>
            <div>
              <div class="sign-label">( Pengirim )</div>
            </div>
          </div>
        </section>
      </body>
    </html>
  `}export{E as b,n as e,k as f,J as o,R as r};
