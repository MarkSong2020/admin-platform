/**
 * 按钮权限 composable：供模板外的逻辑判断（与 v-hasPermi 同语义，spec §5 仅 UX 层）。
 * 用法：const { hasPermi } = usePermission(); hasPermi('system:user:add')。
 */
import { usePermissionStore } from '@/stores/permission'

export interface UsePermissionReturn {
  /** 权限码（或数组任一命中）是否持有；超管 '*:*:*' 恒 true。 */
  hasPermi: (value: string | string[]) => boolean
}

export function usePermission(): UsePermissionReturn {
  const store = usePermissionStore()

  function hasPermi(value: string | string[]): boolean {
    const codes = Array.isArray(value) ? value : [value]
    return codes.some((code) => store.has(code))
  }

  return { hasPermi }
}
