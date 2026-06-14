import { describe, it, expect, beforeEach } from 'vitest'
import { useDarkMode } from './useDarkMode'

beforeEach(() => {
  localStorage.clear()
  document.documentElement.classList.remove('dark')
})

describe('useDarkMode', () => {
  it('toggle 切换 html.dark 并持久化', () => {
    const { isDark, toggle } = useDarkMode()
    toggle()
    expect(isDark.value).toBe(true)
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(localStorage.getItem('admin-platform:dark')).toBe('1')
    toggle()
    expect(isDark.value).toBe(false)
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(localStorage.getItem('admin-platform:dark')).toBe('0')
  })

  it('set 显式置位', () => {
    const { isDark, set } = useDarkMode()
    set(true)
    expect(isDark.value).toBe(true)
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })
})
