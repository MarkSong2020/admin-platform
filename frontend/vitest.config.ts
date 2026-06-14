import { fileURLToPath } from 'node:url'
import { mergeConfig, defineConfig, configDefaults, coverageConfigDefaults } from 'vitest/config'
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
      coverage: {
        provider: 'v8',
        reporter: ['text-summary', 'text'],
        // 默认 exclude（node_modules/dist/配置/spec 等）+ 生成类型；不排除业务页面（codex 共识）
        exclude: [...coverageConfigDefaults.exclude, 'src/api/generated/**'],
        // 阈值设当前 baseline 略下（防整体回归，非数字崇拜）；关键路径负向测试比总覆盖率更重要。
        // 后续可 ratchet 上调。baseline：stmt 71 / branch 73 / func 70 / line 74。
        thresholds: {
          statements: 68,
          branches: 70,
          functions: 65,
          lines: 70,
        },
      },
    },
  }),
)
