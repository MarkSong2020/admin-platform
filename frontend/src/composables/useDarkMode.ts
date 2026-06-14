import { ref } from 'vue'

/**
 * 暗色模式：切换 html.dark（Element Plus dark/css-vars 据此生效）+ 持久化 localStorage。
 * 模块级 ref 作单例，跨组件共享同一开关状态。
 */
const STORAGE_KEY = 'admin-platform:dark'
const isDark = ref(false)

/** 应用/移除 html.dark 并落 localStorage。 */
function apply(value: boolean): void {
  isDark.value = value
  document.documentElement.classList.toggle('dark', value)
  localStorage.setItem(STORAGE_KEY, value ? '1' : '0')
}

/** 启动时按偏好初始化（localStorage 优先，回退系统 prefers-color-scheme）。main.ts 调用一次。 */
export function initDarkMode(): void {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved !== null) {
    apply(saved === '1')
    return
  }
  apply(window.matchMedia('(prefers-color-scheme: dark)').matches)
}

/** 暗色开关 composable（isDark 只读视图 + toggle/set）。 */
export function useDarkMode() {
  return {
    isDark,
    toggle: () => apply(!isDark.value),
    set: apply,
  }
}
