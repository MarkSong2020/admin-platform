/**
 * 通用格式化工具（utils 叶子层，禁 import 任何业务层，仅可依赖第三方/无依赖）。
 * 收口此前 file/server 页重复的 formatBytes 与 operlog/logininfor 页重复的时间格式化，
 * 统一时间戳渲染口径（全站 ISO → 本地可读串）。
 */

/** ISO 8601 时间串转本地可读串；空值/非法串返回占位符 —。 */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString()
}

/** 字节转可读单位（KB/MB/GB），仅展示用。 */
export function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(2)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(2)} KB`
  return `${bytes} B`
}
