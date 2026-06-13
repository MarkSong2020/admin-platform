/** 前端分层硬约束（对标后端 import-linter）。见 spec §4。 */
module.exports = {
  forbidden: [
    {
      name: 'api-no-stores',
      comment: 'api 层（含 session）禁止 import stores',
      severity: 'error',
      from: { path: '^src/api/' },
      to: { path: '^src/stores/' },
    },
    {
      name: 'api-no-router',
      comment: 'api 层（含 session）禁止 import router（失效经 emitter+typed error 上抛）',
      severity: 'error',
      from: { path: '^src/api/' },
      to: { path: '^src/router/' },
    },
    {
      name: 'no-views-import-router',
      comment: 'views 禁止 import 本地 router singleton（只用 vue-router 的 useRouter）',
      severity: 'error',
      from: { path: '^src/views/' },
      to: { path: '^src/router/' },
    },
    {
      name: 'components-no-views',
      comment: '通用组件禁止 import views',
      severity: 'error',
      from: { path: '^src/components/' },
      to: { path: '^src/views/' },
    },
    {
      name: 'views-no-layouts',
      comment: 'views 禁止 import layouts（壳组装归 router composition root）',
      severity: 'error',
      from: { path: '^src/views/' },
      to: { path: '^src/layouts/' },
    },
    {
      name: 'layouts-layer',
      comment: 'layouts 禁止 import views/router/api（登出/登录后装配走 stores 注入，导航用 useRouter）',
      severity: 'error',
      from: { path: '^src/layouts/' },
      to: { path: '^src/(views|router|api)/' },
    },
    {
      name: 'directives-layer',
      comment: 'directives 仅可依赖 stores/utils，禁止 import views/layouts/router/api',
      severity: 'error',
      from: { path: '^src/directives/' },
      to: { path: '^src/(views|layouts|router|api)/' },
    },
    {
      name: 'no-circular',
      comment: '禁止循环依赖',
      severity: 'error',
      from: {},
      to: { circular: true },
    },
  ],
  options: {
    doNotFollow: { path: 'node_modules' },
    tsConfig: { fileName: 'tsconfig.app.json' },
    // @ 别名经 webpack-resolve.cjs 的 resolve.alias 解析（tsConfig paths 无 baseUrl
    // 时 depcruise 解析不了 @，TS6 又把 baseUrl 标 deprecated，故用 webpackConfig 兜）。
    webpackConfig: { fileName: 'webpack-resolve.cjs' },
  },
}
