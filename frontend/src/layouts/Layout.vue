<script setup lang="ts">
/**
 * 顶层布局壳：左 Sidebar + 上 Header（面包屑 + 用户下拉）+ 主内容区。
 * 登出经 stores/logout.ts 的 performLogout（router 职责由 main.ts 注入，layouts 不 import src/router）。
 * keep-alive 首版不做：待页面多起来有切换性能诉求时，再按 meta.noCache 排除接入。
 */
import { computed } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import { useUserInfoStore } from '@/stores/user-info'
import { performLogout } from '@/stores/logout'
import SidebarMenu from './SidebarMenu.vue'
import Breadcrumb from './Breadcrumb.vue'

const userInfoStore = useUserInfoStore()

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
    <el-aside width="220px" class="layout-aside">
      <div class="layout-logo">admin-platform</div>
      <SidebarMenu />
    </el-aside>
    <el-container>
      <el-header class="layout-header">
        <Breadcrumb />
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
      </el-header>
      <el-main class="layout-main">
        <!-- 首版不做 keep-alive；后续按 meta.noCache 排除接入 -->
        <router-view />
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
  border-right: 1px solid var(--el-border-color-light);
  background: var(--el-bg-color);
}

.layout-logo {
  height: 56px;
  line-height: 56px;
  text-align: center;
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  border-bottom: 1px solid var(--el-border-color-light);
}

.layout-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 56px;
  border-bottom: 1px solid var(--el-border-color-light);
  background: var(--el-bg-color);
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
  background: var(--el-fill-color-light);
  overflow-y: auto;
}
</style>
