import { defineStore } from 'pinia'
import { ref } from 'vue'

/** 按钮权限标识集合（getInfo.permissions），超管含 '*:*:*'。spec §5。 */
export const usePermissionStore = defineStore('permission', () => {
  const perms = ref<Set<string>>(new Set())
  function setPermissions(list: string[]): void {
    perms.value = new Set(list)
  }
  function has(code: string): boolean {
    return perms.value.has('*:*:*') || perms.value.has(code)
  }
  function reset(): void {
    perms.value = new Set()
  }
  return { perms, setPermissions, has, reset }
})
