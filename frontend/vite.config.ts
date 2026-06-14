import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    rollupOptions: {
      output: {
        // 把体积大、变动少的 vendor 拆成独立 chunk，改善浏览器缓存命中与构建可读性。
        // 内部后台不追求减总体积（EP on-demand 暂不做），主要收益是缓存与消除单巨块警告。
        // Vite 8/rolldown 仅支持函数形式 manualChunks（对象形式会类型报错）。
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('element-plus')) return 'element-plus'
          if (/[\\/](vue|vue-router|pinia|@vue)[\\/]/.test(id)) return 'vue-vendor'
          return undefined
        },
      },
    },
  },
})
