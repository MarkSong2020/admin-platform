import { defineStore } from 'pinia'
import { ref } from 'vue'

/** 页签（已访问视图）。按 path 去重；affix 标签（首页）不可关闭。 */
export interface TagView {
  path: string
  title: string
  affix?: boolean
}

const HOME_TAG: TagView = { path: '/home', title: '首页', affix: true }

export const useTagsViewStore = defineStore('tags-view', () => {
  const visited = ref<TagView[]>([{ ...HOME_TAG }])

  /** 进入新视图（已存在则忽略）。 */
  function addView(view: TagView): void {
    if (visited.value.some((v) => v.path === view.path)) return
    visited.value.push(view)
  }

  /** 关闭单个（affix 不可关）。 */
  function removeView(path: string): void {
    const idx = visited.value.findIndex((v) => v.path === path)
    if (idx === -1 || visited.value[idx]?.affix) return
    visited.value.splice(idx, 1)
  }

  /** 关闭其他（保留 affix 与指定 path）。 */
  function closeOthers(path: string): void {
    visited.value = visited.value.filter((v) => v.affix || v.path === path)
  }

  /** 关闭全部（仅留 affix）。 */
  function closeAll(): void {
    visited.value = visited.value.filter((v) => v.affix)
  }

  /** 登出/会话失效时复位为仅首页。 */
  function reset(): void {
    visited.value = [{ ...HOME_TAG }]
  }

  return { visited, addView, removeView, closeOthers, closeAll, reset }
})
