/**
 * 仅供 dependency-cruiser 解析 @ 别名用（见 .dependency-cruiser.cjs 的 webpackConfig）。
 * 本项目用 Vite，不用 webpack 构建；此文件只提供 resolve.alias，让 depcruise 把
 * `@/router` 解析成 `src/router/...`，否则分层规则（^src/api/ → ^src/router/）匹配不到。
 */
const path = require('node:path')

module.exports = {
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
    extensions: ['.ts', '.tsx', '.js', '.mjs', '.vue', '.json'],
  },
}
