import { fileURLToPath } from 'node:url'
import { mergeConfig, defineConfig, configDefaults } from 'vitest/config'
import viteConfig from './vite.config'

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      exclude: [...configDefaults.exclude, 'e2e/**'],
      root: fileURLToPath(new URL('./', import.meta.url)),
      // jsdom/Node fetch 不支持相对 URL；给 openapi-fetch baseUrl 一个有效的 origin
      env: { VITE_API_BASE: 'http://localhost' },
    },
  }),
)
