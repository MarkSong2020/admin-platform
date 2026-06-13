import { describe, it, expect, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import SidebarMenu from './SidebarMenu.vue'
import { useMenuStore, type RouterVO } from '@/stores/menu'

/** getRouters 样例树：目录（M→Layout）+ 页面 + 隐藏页 + 隐藏顶层目录。 */
const ROUTERS: RouterVO[] = [
  {
    name: 'System',
    path: '/system',
    component: 'Layout',
    redirect: 'noRedirect',
    hidden: false,
    alwaysShow: true,
    meta: { title: '系统管理', icon: 'system', noCache: false, link: null },
    children: [
      {
        name: 'User',
        path: 'user',
        component: 'system/user/index',
        redirect: null,
        hidden: false,
        alwaysShow: false,
        meta: { title: '用户管理', icon: 'user', noCache: false, link: null },
      },
      {
        name: 'Secret',
        path: 'secret',
        component: 'system/secret/index',
        redirect: null,
        hidden: true,
        alwaysShow: false,
        meta: { title: '隐藏页面', icon: '', noCache: false, link: null },
      },
    ],
  },
  {
    name: 'HiddenTop',
    path: '/hidden-top',
    component: 'Layout',
    redirect: null,
    hidden: true,
    alwaysShow: false,
    meta: { title: '隐藏目录', icon: '', noCache: false, link: null },
  },
]

let pinia: Pinia
let router: Router

async function mountSidebar(): Promise<VueWrapper> {
  router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/:pathMatch(.*)*', name: 'stub', component: { render: () => null } }],
  })
  await router.push('/')
  await router.isReady()
  useMenuStore().routers = ROUTERS
  return mount(SidebarMenu, { global: { plugins: [pinia, router, ElementPlus] } })
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})

describe('SidebarMenu', () => {
  it('目录渲染 el-sub-menu，页面渲染 el-menu-item（带完整路径 index）', async () => {
    const wrapper = await mountSidebar()
    const subMenu = wrapper.find('.el-sub-menu')
    expect(subMenu.exists()).toBe(true)
    expect(subMenu.text()).toContain('系统管理')
    const items = wrapper.findAll('.el-menu-item')
    const userItem = items.find((item) => item.text().includes('用户管理'))
    expect(userItem).toBeDefined()
  })

  it('hidden 节点（顶层与子级）均被过滤', async () => {
    const wrapper = await mountSidebar()
    expect(wrapper.text()).not.toContain('隐藏目录')
    expect(wrapper.text()).not.toContain('隐藏页面')
  })

  it('点击页面项 → router.push 完整路径', async () => {
    const wrapper = await mountSidebar()
    const items = wrapper.findAll('.el-menu-item')
    const userItem = items.find((item) => item.text().includes('用户管理'))
    await userItem!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/system/user')
  })
})
