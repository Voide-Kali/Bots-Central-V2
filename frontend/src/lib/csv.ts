/*
 * Minimal CSV helpers for the panel's "Exportar CSV" buttons. Fields are quoted (inner quotes
 * doubled) and joined with ";"; the download adds a UTF-8 BOM, so a pt-BR Excel/LibreOffice opens
 * the file straight into columns. No dependency on the DOM in csvText, so it is unit-testable.
 */

/** Build the CSV text from a header row and the data rows (all already strings). */
export function csvText(header: readonly string[], rows: readonly (readonly string[])[]): string {
  const cell = (value: string): string => `"${value.replace(/"/g, '""')}"`;
  return [header, ...rows].map((columns) => columns.map(cell).join(";")).join("\r\n");
}

/** Save CSV text as a file the browser downloads. No-op where the browser APIs are absent (tests, SSR). */
export function downloadCsv(filename: string, text: string): void {
  try {
    if (typeof URL === "undefined" || typeof URL.createObjectURL !== "function") return;
    const blob = new Blob(["﻿", text], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  } catch { /* download is best-effort */ }
}
