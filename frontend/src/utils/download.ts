/** Hand a downloaded file to the browser (object URL + anchor click).
 * Pure browser plumbing: no file content is inspected or generated here. */
export function saveFile(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
  // release after the click has been dispatched
  setTimeout(() => URL.revokeObjectURL(url), 0)
}
