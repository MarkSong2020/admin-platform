<script setup lang="ts">
/**
 * 侧边菜单：menu store 的 routers（RouterVO 树）递归渲染 el-menu。
 * 导航用 useRouter()（layouts 禁 import src/router）；hidden 节点逐层过滤。
 * 折叠态由 app store 的 sidebarCollapsed 驱动（折叠时仅显图标 + hover 弹出）。
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { HomeFilled } from '@element-plus/icons-vue'
import { useMenuStore } from '@/stores/menu'
import { useAppStore } from '@/stores/app'
import SidebarMenuItem from './SidebarMenuItem.vue'

const menuStore = useMenuStore()
const appStore = useAppStore()
const route = useRoute()
const router = useRouter()

const visibleRouters = computed(() => menuStore.routers.filter((item) => !item.hidden))

/** el-menu select：index 即节点完整路径。 */
function handleSelect(index: string): void {
  void router.push(index)
}
</script>

<template>
  <el-menu
    :default-active="route.path"
    :collapse="appStore.sidebarCollapsed"
    :collapse-transition="false"
    class="sidebar-menu"
    @select="handleSelect"
  >
    <el-menu-item index="/home">
      <el-icon><HomeFilled /></el-icon>
      <template #title>首页</template>
    </el-menu-item>
    <SidebarMenuItem v-for="item in visibleRouters" :key="item.path" :item="item" base-path="" />
  </el-menu>
</template>

<style scoped>
.sidebar-menu {
  flex: 1;
  overflow-x: hidden;
  overflow-y: auto;
  border-right: none;
}

/* 折叠态宽度对齐 logo（EP 折叠默认 64px） */
.sidebar-menu:not(.el-menu--collapse) {
  width: var(--app-aside-width);
}
</style>
