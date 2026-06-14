import { defineStore } from 'pinia'
import { ref } from 'vue'

/** 应用级布局状态：侧栏折叠（持久化到 localStorage，刷新保持）。 */
const COLLAPSE_KEY = 'admin-platform:sidebar-collapsed'

export const useAppStore = defineStore('app', () => {
  const sidebarCollapsed = ref(localStorage.getItem(COLLAPSE_KEY) === '1')

  function toggleSidebar(): void {
    sidebarCollapsed.value = !sidebarCollapsed.value
    localStorage.setItem(COLLAPSE_KEY, sidebarCollapsed.value ? '1' : '0')
  }

  return { sidebarCollapsed, toggleSidebar }
})
