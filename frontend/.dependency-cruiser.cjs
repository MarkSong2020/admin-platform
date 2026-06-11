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
