export function toLocalDateInputValue(date = new Date()) {
  const value = date instanceof Date ? date : new Date(date);

  if (Number.isNaN(value.getTime())) {
    return '';
  }

  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');

  return `${year}-${month}-${day}`;
}

export function addLocalDays(date = new Date(), days = 0) {
  const value = date instanceof Date ? new Date(date) : new Date(date);
  value.setDate(value.getDate() + Number(days || 0));
  return value;
}

export function firstLocalDayOfMonth(date = new Date()) {
  const value = date instanceof Date ? date : new Date(date);
  return new Date(value.getFullYear(), value.getMonth(), 1);
}

export function toLocalCompactDate(date = new Date()) {
  return toLocalDateInputValue(date).replace(/-/g, '');
}
