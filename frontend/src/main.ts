import './assets/main.css'
import 'element-plus/dist/index.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'

import App from './App.vue'
import router, { resetDynamicRoutes, setupAfterLogin } from './router'
import { registerSessionExpiryHandler } from '@/stores/session-expiry'
import { registerLogoutDeps } from '@/stores/logout'
import { registerPostLoginSetup } from '@/stores/post-login'
import { hasPermi } from '@/directives/has-permi'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(ElementPlus)
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

app.mount('#app')
