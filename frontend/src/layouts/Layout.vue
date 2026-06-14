<script setup lang="ts">
/**
 * 顶层布局壳：左 Sidebar（可折叠）+ 上 Navbar（折叠钮 + 面包屑 + 暗色切换 + 用户下拉）
 * + TagsView 页签 + 主内容区（路由过渡）。
 * 登出经 stores/logout.ts 的 performLogout（router 职责由 main.ts 注入，layouts 不 import src/router）。
 */
import { computed } from 'vue'
import { ArrowDown, Expand, Fold, Moon, Sunny } from '@element-plus/icons-vue'
import { useUserInfoStore } from '@/stores/user-info'
import { performLogout } from '@/stores/logout'
import { useAppStore } from '@/stores/app'
import { useDarkMode } from '@/composables/useDarkMode'
import SidebarMenu from './SidebarMenu.vue'
import Breadcrumb from './Breadcrumb.vue'
import TagsView from './TagsView.vue'

const userInfoStore = useUserInfoStore()
const appStore = useAppStore()
const { isDark, toggle: toggleDark } = useDarkMode()

/** 顶栏展示名：昵称优先，回退用户名。 */
const displayName = computed(
  () => userInfoStore.user?.nickname || userInfoStore.user?.username || '未登录',
)

/** 用户下拉命令分发（当前仅登出）。 */
async function handleUserCommand(command: string | number | object): Promise<void> {
  if (command === 'logout') await performLogout()
}
</script>

<template>
  <el-container class="layout">
    <el-aside
      :width="appStore.sidebarCollapsed ? '64px' : '220px'"
      class="layout-aside"
    >
      <div class="layout-logo">
        <span class="logo-mark">AP</span>
        <span v-show="!appStore.sidebarCollapsed" class="logo-text">admin-platform</span>
      </div>
      <SidebarMenu />
    </el-aside>
    <el-container class="layout-body">
      <el-header class="layout-header">
        <div class="header-left">
          <el-icon class="collapse-btn" @click="appStore.toggleSidebar">
            <component :is="appStore.sidebarCollapsed ? Expand : Fold" />
          </el-icon>
          <Breadcrumb />
        </div>
        <div class="header-right">
          <el-tooltip :content="isDark ? '切换亮色' : '切换暗色'" placement="bottom">
            <el-icon class="header-action" @click="toggleDark">
              <component :is="isDark ? Sunny : Moon" />
            </el-icon>
          </el-tooltip>
          <el-dropdown trigger="click" @command="handleUserCommand">
            <span class="layout-user">
              {{ displayName }}
              <el-icon class="layout-user-icon"><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <TagsView />
      <el-main class="layout-main">
        <router-view v-slot="{ Component }">
          <transition name="fade-transform" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.layout {
  height: 100vh;
}

.layout-aside {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--el-bg-color);
  border-right: 1px solid var(--el-border-color-light);
  transition: width 0.28s ease;
}

.layout-logo {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: var(--app-header-height);
  overflow: hidden;
  border-bottom: 1px solid var(--el-border-color-light);
}

.logo-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  font-size: 14px;
  font-weight: 700;
  color: #fff;
  background: var(--el-color-primary);
  border-radius: 8px;
  flex-shrink: 0;
}

.logo-text {
  font-size: 16px;
  font-weight: 600;
  white-space: nowrap;
  color: var(--el-text-color-primary);
}

.layout-body {
  overflow: hidden;
}

.layout-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: var(--app-header-height);
  background: var(--el-bg-color);
  border-bottom: 1px solid var(--el-border-color-light);
}

.header-left,
.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.collapse-btn,
.header-action {
  font-size: 18px;
  cursor: pointer;
  color: var(--el-text-color-regular);
}

.collapse-btn:hover,
.header-action:hover {
  color: var(--el-color-primary);
}

.layout-user {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  color: var(--el-text-color-primary);
}

.layout-user-icon {
  font-size: 12px;
}

.layout-main {
  padding: 16px;
  overflow-y: auto;
  background: var(--app-bg-page);
}
</style>
