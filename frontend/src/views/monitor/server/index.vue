<script setup lang="ts">
/**
 * 服务监控页（只读 dashboard）。onMounted 拉 getServerMetrics，
 * el-card 分块展示 CPU / 内存 / 磁盘 / 进程 / 系统信息，刷新按钮重拉。
 * 无写操作、无 useCrudTable（非列表语义）。
 */
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getServerMetrics, type ServerMetrics } from '@/api/server'
import { normalizeApiError, type ApiError } from '@/api/transport'
import { formatBytes } from '@/utils/format'

const metrics = ref<ServerMetrics | null>(null)
const loading = ref(false)

function toMessage(err: unknown): string {
  if (err !== null && typeof err === 'object' && 'code' in err && 'message' in err) {
    return (err as ApiError).message
  }
  const normalized = normalizeApiError(err)
  return 'message' in normalized ? normalized.message : '加载失败'
}

async function load(): Promise<void> {
  loading.value = true
  try {
    metrics.value = await getServerMetrics()
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
  <div v-loading="loading" class="server-page">
    <div class="toolbar">
      <el-button type="primary" @click="load">刷新</el-button>
    </div>

    <template v-if="metrics">
      <!-- CPU -->
      <el-card class="block" shadow="never">
        <template #header>CPU</template>
        <el-progress :percentage="Math.round(metrics.cpu.percent)" :stroke-width="18" />
        <el-descriptions :column="2" border class="desc">
          <el-descriptions-item label="核心数">
            {{ metrics.cpu.cores ?? '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="负载(1/5/15min)">
            {{ metrics.cpu.load_avg ? metrics.cpu.load_avg.join(' / ') : '—' }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 内存 -->
      <el-card class="block" shadow="never">
        <template #header>内存</template>
        <el-progress :percentage="Math.round(metrics.memory.percent)" :stroke-width="18" />
        <el-descriptions :column="2" border class="desc">
          <el-descriptions-item label="已用">
            {{ formatBytes(metrics.memory.used) }}
          </el-descriptions-item>
          <el-descriptions-item label="总量">
            {{ formatBytes(metrics.memory.total) }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 磁盘 -->
      <el-card class="block" shadow="never">
        <template #header>磁盘</template>
        <el-table :data="metrics.disks" border>
          <el-table-column prop="mountpoint" label="挂载点" min-width="120" />
          <el-table-column prop="fstype" label="文件系统" min-width="100" />
          <el-table-column label="已用 / 总量" min-width="180">
            <template #default="{ row }">
              {{ formatBytes(row.used) }} / {{ formatBytes(row.total) }}
            </template>
          </el-table-column>
          <el-table-column label="使用率" min-width="200">
            <template #default="{ row }">
              <el-progress :percentage="Math.round(row.percent)" />
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- 进程 -->
      <el-card class="block" shadow="never">
        <template #header>当前进程</template>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="PID">{{ metrics.process.pid }}</el-descriptions-item>
          <el-descriptions-item label="线程数">
            {{ metrics.process.num_threads }}
          </el-descriptions-item>
          <el-descriptions-item label="CPU 占用">
            {{ metrics.process.cpu_percent }} %
          </el-descriptions-item>
          <el-descriptions-item label="内存占用">
            {{ formatBytes(metrics.process.memory_rss) }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 系统信息 -->
      <el-card class="block" shadow="never">
        <template #header>系统信息</template>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="主机名">{{ metrics.sys.hostname }}</el-descriptions-item>
          <el-descriptions-item label="操作系统">
            {{ metrics.sys.os_name }} {{ metrics.sys.os_release }}
          </el-descriptions-item>
          <el-descriptions-item label="架构">{{ metrics.sys.arch }}</el-descriptions-item>
          <el-descriptions-item label="Python 版本">
            {{ metrics.sys.python_version }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>
    </template>
  </div>
</template>

<style scoped>
.server-page {
  padding: 16px;
}
.toolbar {
  margin-bottom: 12px;
}
.block {
  margin-bottom: 16px;
}
.desc {
  margin-top: 12px;
}
</style>
