import './assets/main.css'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './styles/theme.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'

import App from './App.vue'
import router, { resetDynamicRoutes, setupAfterLogin } from './router'
import { registerSessionExpiryHandler } from '@/stores/session-expiry'
import { registerLogoutDeps } from '@/stores/logout'
import { registerPostLoginSetup } from '@/stores/post-login'
import { hasPermi } from '@/directives/has-permi'
import { initDarkMode } from '@/composables/useDarkMode'

const app = createApp(App)

app.use(createPinia())
app.use(router)
// 注入中文 locale，避免 el-pagination / el-table 空态 / 日期选择器等内置文案露英文
app.use(ElementPlus, { locale: zhCn })
app.directive('hasPermi', hasPermi)

// router 职责（reset 动态路由 / redirect）经回调注入，stores 不直接依赖 router
const routerDeps = {
  resetDynamicRoutes,
  redirectToLogin: () => {
    void router.replace({ name: 'login' })
  },
}

// 必须在 bootstrap 首次 refreshOnce 之前注册（spec §6 订阅时序）
registerSessionExpiryHandler(routerDeps)
// 主动登出（Layout 调 performLogout）与登录后装配（登录页调 runPostLoginSetup）同注入模式
registerLogoutDeps(routerDeps)
registerPostLoginSetup(setupAfterLogin)

// 暗色偏好初始化（localStorage > 系统）；须在 mount 前应用 html.dark，避免首屏闪烁
initDarkMode()

app.mount('#app')
