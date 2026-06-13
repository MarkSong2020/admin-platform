import { describe, it, expect } from 'vitest'
import { formatDateTime, formatBytes } from './format'

describe('formatDateTime', () => {
  it('将 ISO 8601 串转为本地可读串', () => {
    const iso = '2026-06-01T00:00:00Z'
    expect(formatDateTime(iso)).toBe(new Date(iso).toLocaleString())
  })

  it('null 返回占位符 —', () => {
    expect(formatDateTime(null)).toBe('—')
  })

  it('undefined 返回占位符 —', () => {
    expect(formatDateTime(undefined)).toBe('—')
  })

  it('空串返回占位符 —', () => {
    expect(formatDateTime('')).toBe('—')
  })

  it('非法时间串返回占位符 —', () => {
    expect(formatDateTime('not-a-date')).toBe('—')
  })
})

describe('formatBytes', () => {
  it('小于 1KB 显示字节', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(1023)).toBe('1023 B')
  })

  it('KB 边界', () => {
    expect(formatBytes(1024)).toBe('1.00 KB')
    expect(formatBytes(2048)).toBe('2.00 KB')
  })

  it('MB 边界', () => {
    expect(formatBytes(1024 ** 2)).toBe('1.00 MB')
    expect(formatBytes(5 * 1024 ** 2)).toBe('5.00 MB')
  })

  it('GB 边界', () => {
    expect(formatBytes(1024 ** 3)).toBe('1.00 GB')
    expect(formatBytes(3 * 1024 ** 3)).toBe('3.00 GB')
  })
})
