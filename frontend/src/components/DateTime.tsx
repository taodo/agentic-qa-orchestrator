export function formatDate(value: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Invalid timestamp' : date.toLocaleString();
}
export function DateTime({ value }: { value: string | null }) {
  if (!value) return <span>—</span>;
  return <time dateTime={Number.isNaN(new Date(value).getTime()) ? undefined : value} title={value}>{formatDate(value)}</time>;
}
