/**
 * 若依菜单树 → Vue Router 路由配置。
 * component 字符串作 key 经 import.meta.glob 白名单映射；缺页 fail fast。
 * 见 spec §5。
 */
import type { RouteRecordRaw } from 'vue-router'
import Layout from '@/layouts/Layout.vue'
import ParentView from '@/layouts/ParentView.vue'

/** 路由壳组件 allowlist（非页面，不参与 seed 覆盖契约）。 */
export const SHELL_ALLOWLIST = ['Layout', 'ParentView'] as const
const SHELLS: Record<string, unknown> = { Layout, ParentView }

/** 所有页面组件：views 下的 index.vue，key 规范化为 'system/user/index' 形态。 */
const pageModules = import.meta.glob('@/views/**/index.vue')

/** 把 '/src/views/system/user/index.vue' → 'system/user/index'。 */
function normalizeKey(globPath: string): string {
  return globPath.replace(/^.*\/views\//, '').replace(/\.vue$/, '')
}

const pageMap = new Map<string, () => Promise<unknown>>()
for (const [globPath, loader] of Object.entries(pageModules)) {
  pageMap.set(normalizeKey(globPath), loader as () => Promise<unknown>)
}

/** 暴露页面 key 集合，供 seed 覆盖契约测试断言。 */
export function pageComponentKeys(): string[] {
  return [...pageMap.keys()]
}

export interface RouterNode {
  name: string
  path: string
  component: string
  redirect: string | null
  hidden: boolean
  alwaysShow: boolean
  meta: Record<string, unknown>
  children?: RouterNode[]
}

function resolveComponent(component: string): unknown {
  if (component in SHELLS) return SHELLS[component]
  const loader = pageMap.get(component)
  if (!loader) {
    throw new Error(`动态路由 component 无对应前端页面（缺页 fail fast）: ${component}`)
  }
  return loader
}

export function toRoutes(nodes: RouterNode[]): RouteRecordRaw[] {
  return nodes.map((node): RouteRecordRaw => {
    const base = {
      path: node.path,
      name: node.name,
      component: resolveComponent(node.component) as RouteRecordRaw['component'],
      meta: { ...node.meta, hidden: node.hidden },
    }
    const record: RouteRecordRaw = base as RouteRecordRaw
    if (node.redirect && node.redirect !== 'noRedirect') {
      ;(record as { redirect?: string }).redirect = node.redirect
    }
    if (node.children?.length) {
      record.children = toRoutes(node.children)
    }
    return record
  })
}
