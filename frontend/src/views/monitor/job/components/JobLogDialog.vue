<script setup lang="ts">
/**
 * 执行日志对话框。传入 taskId，打开时拉该任务的执行日志（分页）。
 * 纯只读展示：execution_id / trigger_type / status / 起止时间 / 耗时 / 结果摘要 / 错误信息。
 */
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import TablePagination from '@/components/TablePagination.vue'
import { listJobLogs, type ScheduledTaskLogRead } from '@/api/job'

const props = defineProps<{
  /** 目标任务 id；null = 未选中（对话框不应打开）。 */
  taskId: number | null
}>()

const visible = defineModel<boolean>('visible', { required: true })

const rows = ref<ScheduledTaskLogRead[]>([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const size = ref(20)

/** 执行状态 → el-tag 类型映射。 */
const STATUS_TAG: Record<string, 'success' | 'danger' | 'warning' | 'info' | 'primary'> = {
  waiting: 'info',
  running: 'primary',
  success: 'success',
  failure: 'danger',
  misfire: 'warning',
  skipped: 'info',
}

function tagType(status: string): 'success' | 'danger' | 'warning' | 'info' | 'primary' {
  return STATUS_TAG[status] ?? 'info'
}

async function load(): Promise<void> {
  if (props.taskId === null) return
  loading.value = true
  try {
    const data = await listJobLogs({ page: page.value, size: size.value, task_id: props.taskId })
    rows.value = data.items
    total.value = data.total
  } catch (err) {
    ElMessage.error((err as { message?: string }).message ?? '加载执行日志失败')
  } finally {
    loading.value = false
  }
}

// 打开时回到第一页并加载
watch(visible, (open) => {
  if (!open || props.taskId === null) return
  page.value = 1
  void load()
})
</script>

<template>
  <el-dialog v-model="visible" title="执行日志" width="900px" append-to-body>
    <el-table v-loading="loading" :data="rows" border>
      <el-table-column prop="execution_id" label="执行ID" min-width="150" show-overflow-tooltip />
      <el-table-column label="触发方式" width="100">
        <template #default="{ row }">
          {{ row.trigger_type === 'manual' ? '手动' : '调度' }}
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="tagType(row.status)">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="started_at" label="开始时间" min-width="180" />
      <el-table-column prop="finished_at" label="结束时间" min-width="180" />
      <el-table-column prop="duration_ms" label="耗时(ms)" width="110" />
      <el-table-column
        prop="result_summary"
        label="结果摘要"
        min-width="160"
        show-overflow-tooltip
      />
      <el-table-column
        prop="error_message"
        label="错误信息"
        min-width="160"
        show-overflow-tooltip
      />
    </el-table>
    <TablePagination
      v-model:page="page"
      v-model:size="size"
      :total="total"
      class="pagination"
      @change="load"
    />
  </el-dialog>
</template>

<style scoped>
.pagination {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
