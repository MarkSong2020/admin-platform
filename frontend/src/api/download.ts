/**
 * 浏览器落盘助手：把 transport.downloadBlob 返回的 Blob 触发为下载。
 * transport.downloadBlob 只取 blob 不负责保存（职责单一），保存逻辑统一收口在此，
 * 供 file / posts 等下载端点复用，避免每处重复 createObjectURL/a.click/revoke 仪式。
 */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
