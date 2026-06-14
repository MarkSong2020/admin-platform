/**
 * v-hasPermi 按钮权限指令（spec §5：前端权限仅 UX 层，后端 RBAC 才是安全边界）。
 * 值为权限码字符串或数组（任一命中即显示）；无权限 → 直接从 DOM 移除元素（对标 RuoYi）。
 * 超管 '*:*:*' 恒显（permission store 的 has() 已内置通配）。
 */
import type { Directive } from 'vue'
import { usePermissionStore } from '@/stores/permission'

export type HasPermiValue = string | string[]

function isGranted(value: HasPermiValue | undefined): boolean {
  if (value == null) {
    throw new Error('v-hasPermi 需要权限码，如 v-hasPermi="\'system:user:add\'"')
  }
  const codes = Array.isArray(value) ? value : [value]
  if (codes.length === 0) {
    throw new Error('v-hasPermi 权限码数组不能为空')
  }
  const store = usePermissionStore()
  return codes.some((code) => store.has(code))
}

export const hasPermi: Directive<HTMLElement, HasPermiValue> = {
  mounted(el, binding) {
    if (!isGranted(binding.value)) {
      el.parentNode?.removeChild(el)
    }
  },
}
