/**
 * 缓存监控 API 类型化封装（经 client.ts 的 openapi-fetch 实例）。
 * 端点：GET /monitor/cache（无参；Redis 不可用时 available=false 降级，info=null，不抛 500）。
 * 错误经 transport.normalizeProblemBody 归一化抛出（参照 users.ts 范式）。
 */
import { apiClient } from './client'
import { unwrap } from './transport'
import type { components } from './generated/types'

export type CacheMetrics = components['schemas']['CacheMetrics']

/** 拉取缓存监控指标（只读单视图；available=false 表示 Redis 不可用降级）。 */
export async function getCacheMetrics(): Promise<CacheMetrics> {
  return unwrap(await apiClient.GET('/api/v1/monitor/cache'))
}
