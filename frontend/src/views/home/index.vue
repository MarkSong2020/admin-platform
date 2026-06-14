<script setup lang="ts">
/**
 * 工作台首页：问候 hero + 快捷入口 + 最近访问 + 系统信息。
 * 数据全部来自已加载 store（user-info / menu / tags-view），不造假 KPI；
 * 快捷入口经 menu store（getRouters 已按权限过滤）做可达性过滤。
 * 导航用 router-link（全局组件，不 import src/router）。
 */
import { computed } from 'vue'
import {
  Collection,
  Document,
  Monitor,
  OfficeBuilding,
  Postcard,
  SetUp,
  User,
  UserFilled,
} from '@element-plus/icons-vue'
import { useUserInfoStore } from '@/stores/user-info'
import { useMenuStore, type RouterVO } from '@/stores/menu'
import { useTagsViewStore } from '@/stores/tags-view'

const userInfo = useUserInfoStore()
const menuStore = useMenuStore()
const tagsView = useTagsViewStore()

const displayName = computed(() => userInfo.user?.nickname || userInfo.user?.username || '管理员')

const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return '凌晨好'
  if (h < 12) return '上午好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
})

const today = computed(() => {
  const d = new Date()
  const week = ['日', '一', '二', '三', '四', '五', '六'][d.getDay()]
  return `${d.getFullYear()} 年 ${d.getMonth() + 1} 月 ${d.getDate()} 日 · 星期${week}`
})

/** 递归收集可访问叶子路径（getRouters 已按权限过滤 → 真实可达集合）。 */
function collectPaths(nodes: RouterVO[], base: string, acc: Set<string>): void {
  for (const node of nodes) {
    if (node.hidden) continue
    const full = node.path.startsWith('/')
      ? node.path
      : `${base.replace(/\/+$/, '')}/${node.path}`
    const children = (node.children ?? []).filter((c) => !c.hidden)
    if (children.length) collectPaths(children, full, acc)
    else acc.add(full)
  }
}

const accessiblePaths = computed(() => {
  const set = new Set<string>()
  collectPaths(menuStore.routers, '', set)
  return set
})

/** 策展快捷入口（图标/配色策展）→ 按可达集合过滤，越权项不显示。 */
const QUICK_ENTRIES = [
  { label: '用户管理', path: '/system/user', icon: User, tint: '#4361ee' },
  { label: '角色权限', path: '/system/role', icon: UserFilled, tint: '#16a34a' },
  { label: '部门管理', path: '/system/dept', icon: OfficeBuilding, tint: '#0ea5e9' },
  { label: '岗位管理', path: '/system/post', icon: Postcard, tint: '#f59e0b' },
  { label: '字典管理', path: '/system/dict', icon: Collection, tint: '#722ed1' },
  { label: '参数设置', path: '/system/config', icon: SetUp, tint: '#06b6d4' },
  { label: '操作日志', path: '/monitor/operlog', icon: Document, tint: '#ef4444' },
  { label: '服务监控', path: '/monitor/server', icon: Monitor, tint: '#8b5cf6' },
]
const quickEntries = computed(() =>
  QUICK_ENTRIES.filter((entry) => accessiblePaths.value.has(entry.path)),
)

/** 最近访问（页签，去首页，最新在前，取前 8）。 */
const recentVisits = computed(() =>
  tagsView.visited
    .filter((tag) => tag.path !== '/home')
    .slice(-8)
    .reverse(),
)

const roleText = computed(() => (userInfo.roles.length ? userInfo.roles.join('、') : '—'))
</script>

<template>
  <div class="dashboard app-bleed">
    <!-- 问候 hero（品牌渐变，与登录页同色系闭环） -->
    <section class="dash-hero">
      <div class="hero-text">
        <h1>{{ greeting }}，{{ displayName }}</h1>
        <p>欢迎回到 Admin Platform，祝你高效顺利的一天</p>
      </div>
      <div class="hero-meta">{{ today }}</div>
      <div class="hero-orb"></div>
    </section>

    <!-- 快捷入口 -->
    <section v-if="quickEntries.length" class="panel">
      <h3 class="panel-title">快捷入口</h3>
      <div class="quick-grid">
        <router-link
          v-for="entry in quickEntries"
          :key="entry.path"
          :to="entry.path"
          class="quick-item"
        >
          <span class="quick-icon" :style="{ background: entry.tint + '1f', color: entry.tint }">
            <el-icon><component :is="entry.icon" /></el-icon>
          </span>
          <span class="quick-label">{{ entry.label }}</span>
        </router-link>
      </div>
    </section>

    <div class="dash-cols">
      <!-- 最近访问 -->
      <section class="panel">
        <h3 class="panel-title">最近访问</h3>
        <div v-if="recentVisits.length" class="recent-list">
          <router-link
            v-for="tag in recentVisits"
            :key="tag.path"
            :to="tag.path"
            class="recent-item"
          >
            <span class="recent-dot"></span>
            <span class="recent-title">{{ tag.title }}</span>
            <span class="recent-path">{{ tag.path }}</span>
          </router-link>
        </div>
        <el-empty v-else description="暂无最近访问" :image-size="72" />
      </section>

      <!-- 系统信息 -->
      <section class="panel">
        <h3 class="panel-title">系统信息</h3>
        <dl class="info-list">
          <div class="info-row">
            <dt>产品</dt>
            <dd>Admin Platform · 企业级后台管理</dd>
          </div>
          <div class="info-row">
            <dt>当前账号</dt>
            <dd>{{ displayName }}</dd>
          </div>
          <div class="info-row">
            <dt>角色</dt>
            <dd>{{ roleText }}</dd>
          </div>
          <div class="info-row">
            <dt>可用功能</dt>
            <dd>{{ accessiblePaths.size }} 项</dd>
          </div>
        </dl>
      </section>
    </div>
  </div>
</template>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-4);
}

/* —— 问候 hero —— */
.dash-hero {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding: 28px 32px;
  overflow: hidden;
  color: #fff;
  background: var(--app-brand-gradient);
  border-radius: var(--app-radius-lg);
  box-shadow: var(--app-brand-glow);
}

.hero-text h1 {
  margin: 0 0 6px;
  font-size: 24px;
  font-weight: 700;
}

.hero-text p {
  margin: 0;
  font-size: 14px;
  opacity: 0.88;
}

.hero-meta {
  position: relative;
  z-index: 2;
  font-size: 13px;
  opacity: 0.85;
}

.hero-orb {
  position: absolute;
  top: -80px;
  right: -40px;
  width: 280px;
  height: 280px;
  border-radius: 50%;
  background: radial-gradient(circle, rgb(255 255 255 / 18%), transparent 70%);
}

/* —— 卡片面板 —— */
.panel {
  padding: var(--app-space-6);
  background: var(--app-card-bg);
  border-radius: var(--app-card-radius);
  box-shadow: var(--app-card-shadow);
}

.panel-title {
  margin: 0 0 var(--app-space-4);
  font-size: 15px;
  font-weight: var(--app-font-weight-semibold);
  color: var(--el-text-color-primary);
}

/* —— 快捷入口 —— */
.quick-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--app-space-3);
}

.quick-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 18px 8px;
  text-decoration: none;
  color: var(--el-text-color-regular);
  background: var(--el-fill-color-light);
  border-radius: var(--app-radius-lg);
  transition:
    transform 0.18s ease,
    background 0.18s ease,
    color 0.18s ease;
}

.quick-item:hover {
  transform: translateY(-2px);
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}

.quick-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  font-size: 22px;
  border-radius: 12px;
}

.quick-label {
  font-size: 13px;
  font-weight: var(--app-font-weight-medium);
}

/* —— 两列区 —— */
.dash-cols {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: var(--app-space-4);
}

/* —— 最近访问 —— */
.recent-list {
  display: flex;
  flex-direction: column;
}

.recent-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 8px;
  text-decoration: none;
  border-radius: 8px;
  color: var(--el-text-color-regular);
  transition: background 0.18s ease;
}

.recent-item:hover {
  background: var(--el-fill-color-light);
  color: var(--el-color-primary);
}

.recent-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--el-color-primary);
  flex-shrink: 0;
}

.recent-title {
  font-size: 14px;
}

.recent-path {
  margin-left: auto;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

/* —— 系统信息 —— */
.info-list {
  margin: 0;
}

.info-row {
  display: flex;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.info-row:last-child {
  border-bottom: none;
}

.info-row dt {
  width: 92px;
  flex-shrink: 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.info-row dd {
  margin: 0;
  font-size: 14px;
  color: var(--el-text-color-primary);
}

/* —— 响应式 —— */
@media (max-width: 1100px) {
  .quick-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .dash-cols {
    grid-template-columns: 1fr;
  }
}
</style>
