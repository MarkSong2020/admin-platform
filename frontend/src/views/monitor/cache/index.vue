<script setup lang="ts">
/**
 * 缓存监控页（只读 dashboard）。onMounted 拉 getCacheMetrics，刷新按钮重拉。
 * 降级处理：available=false（Redis 不可用）时 info 为 null，渲染 el-alert 提示，不渲染 info 详情；
 * available=true 时展示 info 摘要 + command_stats 表。
 */
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getCacheMetrics, type CacheMetrics } from '@/api/cache'
import { normalizeApiError, type ApiError } from '@/api/transport'

const metrics = ref<CacheMetrics | null>(null)
const loading = ref(false)

function toMessage(err: unknown): string {
  if (err !== null && typeof err === 'object' && 'code' in err && 'message' in err) {
    return (err as ApiError).message
  }
  const normalized = normalizeApiError(err)
  return 'message' in normalized ? normalized.message : '加载失败'
}

/** 命中率小数转百分比展示（null 时 —）。 */
function formatHitRate(rate: number | null): string {
  return rate === null ? '—' : `${(rate * 100).toFixed(1)} %`
}

async function load(): Promise<void> {
  loading.value = true
  try {
    metrics.value = await getCacheMetrics()
  } catch (err) {
    ElMessage.error(toMessage(err))
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div v-loading="loading" class="cache-page">
    <div class="toolbar">
      <el-button type="primary" @click="load">刷新</el-button>
    </div>

    <template v-if="metrics">
      <!-- 降级：Redis 不可用 -->
      <el-alert
        v-if="!metrics.available"
        title="缓存不可用"
        description="Redis 未配置或不可达，监控信息已降级。"
        type="warning"
        :closable="false"
        show-icon
      />

      <!-- 正常：info 摘要 + command_stats -->
      <template v-else-if="metrics.info">
        <el-card class="block" shadow="never">
          <template #header>Redis 概览</template>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="版本">
              {{ metrics.info.version ?? '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="模式">
              {{ metrics.info.mode ?? '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="运行时长(秒)">
              {{ metrics.info.uptime_seconds ?? '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="连接客户端">
              {{ metrics.info.connected_clients ?? '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="已用内存">
              {{ metrics.info.used_memory_human ?? '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="命中率">
              {{ formatHitRate(metrics.info.hit_rate) }}
            </el-descriptions-item>
            <el-descriptions-item label="命中 / 未命中">
              {{ metrics.info.keyspace_hits ?? '—' }} / {{ metrics.info.keyspace_misses ?? '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="累计命令数">
              {{ metrics.info.total_commands_processed ?? '—' }}
            </el-descriptions-item>
          </el-descriptions>
        </el-card>

        <el-card class="block" shadow="never">
          <template #header>命令统计</template>
          <el-table :data="metrics.command_stats" border>
            <el-table-column prop="name" label="命令" min-width="160" />
            <el-table-column prop="calls" label="调用次数" min-width="120" />
            <el-table-column prop="usec" label="耗时(μs)" min-width="120" />
            <el-table-column prop="usec_per_call" label="单次耗时(μs)" min-width="140" />
          </el-table>
        </el-card>
      </template>

      <!-- 兜底：available=true 但 info 为空（如 Redis 连上但 INFO 超时），避免静默空白 -->
      <el-alert
        v-else
        title="指标异常"
        description="缓存声明可用但未返回指标，请刷新重试。"
        type="warning"
        :closable="false"
        show-icon
      />
    </template>
  </div>
</template>

<style scoped>
.cache-page {
  padding: 16px;
}
.toolbar {
  margin-bottom: 12px;
}
.block {
  margin-bottom: 16px;
}
</style>
