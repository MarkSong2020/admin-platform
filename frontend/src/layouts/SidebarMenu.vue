<script setup lang="ts">
/**
 * 侧边菜单：menu store 的 routers（RouterVO 树）递归渲染 el-menu。
 * 导航用 useRouter()（layouts 禁 import src/router）；hidden 节点逐层过滤。
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMenuStore } from '@/stores/menu'
import SidebarMenuItem from './SidebarMenuItem.vue'

const menuStore = useMenuStore()
const route = useRoute()
const router = useRouter()

const visibleRouters = computed(() => menuStore.routers.filter((item) => !item.hidden))

/** el-menu select：index 即节点完整路径。 */
function handleSelect(index: string): void {
  void router.push(index)
}
</script>

<template>
  <el-menu :default-active="route.path" class="sidebar-menu" @select="handleSelect">
    <el-menu-item index="/home">
      <span>首页</span>
    </el-menu-item>
    <SidebarMenuItem
      v-for="item in visibleRouters"
      :key="item.path"
      :item="item"
      base-path=""
    />
  </el-menu>
</template>

<style scoped>
.sidebar-menu {
  flex: 1;
  overflow-y: auto;
  border-right: none;
}
</style>
