function escapeCsvValue(value) {
  if (value === null || value === undefined) return '';
  const text = String(value).replace(/"/g, '""');
  return /[",\n\r;]/.test(text) ? `"${text}"` : text;
}

export function exportRowsToCsv(filename, columns, rows) {
  const header = columns.map((column) => escapeCsvValue(column.label)).join(';');
  const body = rows.map((row) =>
    columns
      .map((column) => {
        const value = typeof column.value === 'function' ? column.value(row) : row[column.key];
        return escapeCsvValue(value);
      })
      .join(';')
  );
  const blob = new Blob([`\uFEFF${[header, ...body].join('\r\n')}`], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename.endsWith('.csv') ? filename : `${filename}.csv`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
