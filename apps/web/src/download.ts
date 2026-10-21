/** Saves a blob (for example a PDF fetched with the auth header) through a temporary link. */
export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename.replace(/[^\w.-]+/g, "-");
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
