import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAppStore } from './app'

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
})

describe('app store', () => {
  it('默认不折叠（无 localStorage）', () => {
    const store = useAppStore()
    expect(store.sidebarCollapsed).toBe(false)
  })

  it('toggleSidebar 翻转状态并持久化', () => {
    const store = useAppStore()
    store.toggleSidebar()
    expect(store.sidebarCollapsed).toBe(true)
    expect(localStorage.getItem('admin-platform:sidebar-collapsed')).toBe('1')
    store.toggleSidebar()
    expect(store.sidebarCollapsed).toBe(false)
    expect(localStorage.getItem('admin-platform:sidebar-collapsed')).toBe('0')
  })

  it('从 localStorage 恢复折叠态', () => {
    localStorage.setItem('admin-platform:sidebar-collapsed', '1')
    setActivePinia(createPinia())
    expect(useAppStore().sidebarCollapsed).toBe(true)
  })
})
