<script setup lang="ts">
/**
 * 页签栏（已访问视图）：route 变化入表，点击切换，× 关闭，右键 关闭其他/全部。
 * 导航用 useRouter()（layouts 禁 import src/router）；标题取 route.meta.title。
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Close } from '@element-plus/icons-vue'
import { useTagsViewStore, type TagView } from '@/stores/tags-view'

const route = useRoute()
const router = useRouter()
const store = useTagsViewStore()

const tags = computed(() => store.visited)

/** 当前路由进表（登录页不入）。 */
watch(
  () => route.path,
  (path) => {
    if (!path || path === '/login') return
    const title =
      typeof route.meta.title === 'string' && route.meta.title
        ? route.meta.title
        : (route.name?.toString() ?? path)
    store.addView({ path, title })
  },
  { immediate: true },
)

function isActive(tag: TagView): boolean {
  return tag.path === route.path
}

function goto(tag: TagView): void {
  if (!isActive(tag)) void router.push(tag.path)
}

/** 关闭标签；若关的是当前页，跳到剩余的最后一个标签。 */
function closeTag(tag: TagView): void {
  const wasActive = isActive(tag)
  store.removeView(tag.path)
  if (wasActive) {
    const last = store.visited[store.visited.length - 1]
    if (last) void router.push(last.path)
  }
}

// 右键上下文菜单
const ctxVisible = ref(false)
const ctxLeft = ref(0)
const ctxTop = ref(0)
const ctxTag = ref<TagView | null>(null)

function openContextMenu(tag: TagView, e: MouseEvent): void {
  ctxTag.value = tag
  ctxLeft.value = e.clientX
  ctxTop.value = e.clientY
  ctxVisible.value = true
}

function closeContextMenu(): void {
  ctxVisible.value = false
}

function closeOthers(): void {
  if (ctxTag.value) {
    store.closeOthers(ctxTag.value.path)
    if (!isActive(ctxTag.value)) void router.push(ctxTag.value.path)
  }
  closeContextMenu()
}

function closeAll(): void {
  store.closeAll()
  const last = store.visited[store.visited.length - 1]
  if (last) void router.push(last.path)
  closeContextMenu()
}

// 菜单打开时，任意点击关闭（once 自清理）
watch(ctxVisible, (visible) => {
  if (visible) document.addEventListener('click', closeContextMenu, { once: true })
})
</script>

<template>
  <div class="tags-view">
    <div class="tags-scroll">
      <span
        v-for="tag in tags"
        :key="tag.path"
        class="tag-item"
        :class="{ active: isActive(tag) }"
        role="button"
        tabindex="0"
        :aria-current="isActive(tag) ? 'page' : undefined"
        @click="goto(tag)"
        @keyup.enter="goto(tag)"
        @contextmenu.prevent="openContextMenu(tag, $event)"
      >
        <span class="tag-dot" />
        {{ tag.title }}
        <el-icon
          v-if="!tag.affix"
          class="tag-close"
          role="button"
          tabindex="0"
          aria-label="关闭标签"
          @click.stop="closeTag(tag)"
          @keyup.enter.stop="closeTag(tag)"
        >
          <Close />
        </el-icon>
      </span>
    </div>
    <ul
      v-show="ctxVisible"
      class="tags-contextmenu"
      :style="{ left: ctxLeft + 'px', top: ctxTop + 'px' }"
    >
      <li @click="closeOthers">关闭其他</li>
      <li @click="closeAll">关闭全部</li>
    </ul>
  </div>
</template>

<style scoped>
.tags-view {
  display: flex;
  align-items: center;
  height: var(--app-tags-height);
  padding: 0 12px;
  background: var(--el-bg-color);
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.tags-scroll {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  scrollbar-width: none;
}

.tags-scroll::-webkit-scrollbar {
  display: none;
}

.tag-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 26px;
  padding: 0 10px;
  font-size: 12px;
  white-space: nowrap;
  cursor: pointer;
  color: var(--el-text-color-regular);
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  transition:
    color 0.2s ease,
    background 0.2s ease,
    border-color 0.2s ease;
}

.tag-item:hover {
  color: var(--el-color-primary);
}

.tag-item.active {
  color: #fff;
  background: var(--el-color-primary);
  border-color: var(--el-color-primary);
}

.tag-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentcolor;
  opacity: 0.6;
}

.tag-item.active .tag-dot {
  background: #fff;
  opacity: 1;
}

.tag-close {
  font-size: 12px;
  border-radius: 50%;
}

.tag-close:hover {
  background: rgb(0 0 0 / 15%);
}

.tags-contextmenu {
  position: fixed;
  z-index: 3000;
  padding: 4px 0;
  margin: 0;
  list-style: none;
  background: var(--el-bg-color-overlay);
  border: 1px solid var(--el-border-color-light);
  border-radius: 6px;
  box-shadow: var(--el-box-shadow-light);
}

.tags-contextmenu li {
  padding: 6px 16px;
  font-size: 13px;
  color: var(--el-text-color-regular);
  cursor: pointer;
}

.tags-contextmenu li:hover {
  background: var(--el-fill-color-light);
  color: var(--el-color-primary);
}
</style>
