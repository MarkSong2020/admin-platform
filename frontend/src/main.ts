import './assets/main.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import { registerSessionExpiryHandler } from '@/stores/session-expiry'

const app = createApp(App)

app.use(createPinia())
app.use(router)

registerSessionExpiryHandler({
  redirectToLogin: () => {
    void router.replace('/login')
  },
})

app.mount('#app')
