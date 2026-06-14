<script setup lang="ts">
/**
 * 顶层布局壳：左 Sidebar（可折叠）+ 上 Navbar（折叠钮 + 面包屑 + 暗色切换 + 用户下拉）
 * + TagsView 页签 + 主内容区（路由过渡）。
 * 登出经 stores/logout.ts 的 performLogout（router 职责由 main.ts 注入，layouts 不 import src/router）。
 */
import { computed, ref } from 'vue'
import { ArrowDown, Expand, FullScreen, Fold, Moon, Sunny } from '@element-plus/icons-vue'
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

/** 头像首字（昵称/用户名首字符，大写）。 */
const avatarLetter = computed(() => displayName.value.charAt(0).toUpperCase())

/** 全屏切换（纯浏览器 API，无依赖）。 */
const isFullscreen = ref(false)
function toggleFullscreen(): void {
  if (document.fullscreenElement) {
    void document.exitFullscreen()
    isFullscreen.value = false
  } else {
    void document.documentElement.requestFullscreen()
    isFullscreen.value = true
  }
}

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
        <span class="logo-mark" aria-hidden="true">
          <svg viewBox="0 0 32 32" width="19" height="19">
            <rect x="3" y="3" width="17" height="17" rx="5" fill="#fff" opacity="0.55" />
            <rect x="12" y="12" width="17" height="17" rx="5" fill="#fff" />
          </svg>
        </span>
        <span v-show="!appStore.sidebarCollapsed" class="logo-text">Admin Platform</span>
      </div>
      <SidebarMenu />
    </el-aside>
    <el-container class="layout-body">
      <el-header class="layout-header">
        <div class="header-left">
          <el-button
            class="collapse-btn"
            text
            :icon="appStore.sidebarCollapsed ? Expand : Fold"
            :aria-label="appStore.sidebarCollapsed ? '展开侧栏' : '收起侧栏'"
            @click="appStore.toggleSidebar"
          />
          <Breadcrumb />
        </div>
        <div class="header-right">
          <el-tooltip content="全屏" placement="bottom">
            <el-button
              class="header-action"
              text
              :icon="FullScreen"
              aria-label="全屏切换"
              @click="toggleFullscreen"
            />
          </el-tooltip>
          <el-tooltip :content="isDark ? '切换亮色' : '切换暗色'" placement="bottom">
            <el-button
              class="header-action"
              text
              :icon="isDark ? Sunny : Moon"
              :aria-label="isDark ? '切换亮色' : '切换暗色'"
              @click="toggleDark"
            />
          </el-tooltip>
          <el-divider direction="vertical" />
          <el-dropdown trigger="click" @command="handleUserCommand">
            <span class="layout-user">
              <el-avatar :size="28" class="user-avatar">{{ avatarLetter }}</el-avatar>
              <span class="user-name">{{ displayName }}</span>
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
  background: linear-gradient(180deg, var(--el-color-primary-light-9), transparent);
  border-bottom: 1px solid var(--el-border-color-light);
}

.logo-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  color: #fff;
  background: var(--app-brand-gradient);
  border-radius: 9px;
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
  height: 36px;
  width: 36px;
  font-size: 18px;
  color: var(--el-text-color-regular);
}

.collapse-btn:hover,
.header-action:hover {
  color: var(--el-color-primary);
  background: var(--el-fill-color-light);
}

.layout-header :deep(.el-divider--vertical) {
  height: 20px;
  margin: 0 4px;
}

.layout-user {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border-radius: 8px;
  cursor: pointer;
  color: var(--el-text-color-primary);
  transition: background 0.18s ease;
}

.layout-user:hover {
  background: var(--el-fill-color-light);
}

.user-avatar {
  font-size: 13px;
  font-weight: 600;
  color: #fff;
  background: var(--app-brand-gradient);
}

.user-name {
  font-size: 14px;
}

.layout-user-icon {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.layout-main {
  padding: 16px;
  overflow-y: auto;
  background: var(--app-bg-page);
}
</style>
