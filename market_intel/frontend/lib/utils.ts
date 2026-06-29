/** Parse a naive UTC ISO string from the API and format in the browser's local timezone. */
export function fmtTs(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso.endsWith("Z") ? iso : iso + "Z").toLocaleString();
}
