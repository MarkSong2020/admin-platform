<script setup lang="ts">
/**
 * 侧边菜单递归节点（自引用组件）：
 * 有可见子节点 → el-sub-menu（目录）；否则 → el-menu-item（页面）。
 * index 为拼接后的完整路径，供 SidebarMenu 的 @select 做 router.push。
 * meta.icon 是 RuoYi svg 图标名，与 Element Plus 图标体系不对齐，首版不渲染图标。
 */
import { computed } from 'vue'
import type { RouterVO } from '@/stores/menu'

const props = defineProps<{
  /** RouterVO 节点（getRouters 树）。 */
  item: RouterVO
  /** 父级完整路径（顶层传 ''；子级相对路径据此拼接）。 */
  basePath: string
}>()

/** 顶层 path 以 / 开头直接用；子级相对路径拼到父级后。 */
const fullPath = computed(() => {
  if (props.item.path.startsWith('/')) return props.item.path
  return `${props.basePath.replace(/\/+$/, '')}/${props.item.path}`
})

const visibleChildren = computed(() => (props.item.children ?? []).filter((c) => !c.hidden))

const isDirectory = computed(() => visibleChildren.value.length > 0)

const title = computed(() => props.item.meta.title || props.item.name)
</script>

<template>
  <el-sub-menu v-if="isDirectory" :index="fullPath">
    <template #title>
      <span>{{ title }}</span>
    </template>
    <SidebarMenuItem
      v-for="child in visibleChildren"
      :key="child.path"
      :item="child"
      :base-path="fullPath"
    />
  </el-sub-menu>
  <el-menu-item v-else :index="fullPath">
    <span>{{ title }}</span>
  </el-menu-item>
</template>
