import './assets/main.css'
import 'element-plus/dist/index.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'

import App from './App.vue'
import router, { resetDynamicRoutes } from './router'
import { registerSessionExpiryHandler } from '@/stores/session-expiry'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(ElementPlus)

// 必须在 bootstrap 首次 refreshOnce 之前注册（spec §6 订阅时序）；
// router 的职责（reset 动态路由 / redirect）经回调注入，stores 不直接依赖 router。
registerSessionExpiryHandler({
  resetDynamicRoutes,
  redirectToLogin: () => {
    void router.replace({ name: 'login' })
  },
})

app.mount('#app')
