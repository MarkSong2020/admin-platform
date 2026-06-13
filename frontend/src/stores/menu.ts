import { defineStore } from 'pinia'
import { ref } from 'vue'
import { fetchRouters, type RouterVO } from '@/api/auth'

// layouts 层禁 import api（depcruise），菜单树类型经本 store 转出
export type { RouterVO } from '@/api/auth'

/** 菜单路由树（getRouters）。只持数据，addRoute 归 router（T2 职责）。spec §5。 */
export const useMenuStore = defineStore('menu', () => {
  const routers = ref<RouterVO[]>([])
  const loaded = ref(false)

  async function loadRouters(): Promise<void> {
    routers.value = await fetchRouters()
    loaded.value = true
  }

  function reset(): void {
    routers.value = []
    loaded.value = false
  }

  return { routers, loaded, loadRouters, reset }
})
