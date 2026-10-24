function displayText(value) {
  if (typeof value !== 'string' && typeof value !== 'number') return '';
  const text = String(value).trim();
  return ['-', '—'].includes(text) ? '' : text;
}

function containsReference(description, reference) {
  const escaped = reference.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  // An invoice such as INV-1 must not be mistaken for INV-10.
  return new RegExp(`(?:^|[^\\p{L}\\p{N}_-])${escaped}(?=$|[^\\p{L}\\p{N}_-])`, 'iu').test(description);
}

/** Display-only: retain the stored note and add references not already in it. */
export function journalLineDescription(line = {}) {
  const description = displayText(line.keterangan);
  const invoice = displayText(line.no_faktur);
  const invoiceId = !invoice && displayText(line.workflow_invoice_id);
  const references = [];
  let combined = description;
  const append = (label, value) => {
    if (!value || containsReference(combined, value)) return;
    references.push(`${label}: ${value}`);
    combined += ` | ${value}`;
  };
  append(invoice ? 'Faktur' : 'Faktur ID', invoice || invoiceId);
  append('Sumber', displayText(line.sumber_dana));
  append('Sumber', displayText(line.workflow_source));
  return [description, references.join(' · ')].filter(Boolean).join('\n') || '—';
}
