<script setup lang="ts">
/**
 * 定时任务管理页（最复杂监控页）：CRUD + 手动触发 + 执行日志。
 * 复用 useCrudTable（列表/分页/删除）+ TablePagination；新增/编辑、执行日志拆为同目录 components。
 * v-hasPermi 仅控按钮可见性（UX 层），后端 RBAC 才是安全边界。
 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useCrudTable } from '@/composables/useCrudTable'
import TablePagination from '@/components/TablePagination.vue'
import JobFormDialog from './components/JobFormDialog.vue'
import JobLogDialog from './components/JobLogDialog.vue'
import { listJobs, deleteJob, runJob, type ScheduledTaskRead } from '@/api/job'
import { type ApiError } from '@/api/transport'

interface JobQuery {
  status?: string
  handler_key?: string
}

const table = useCrudTable<ScheduledTaskRead, JobQuery>({
  fetchPage: async (params) => {
    const page = await listJobs(params)
    return { items: page.items, total: page.total }
  },
  removeItem: deleteJob,
})

const formVisible = ref(false)
const editing = ref<ScheduledTaskRead | null>(null)
const logVisible = ref(false)
const logTaskId = ref<number | null>(null)

function openCreate(): void {
  editing.value = null
  formVisible.value = true
}

function openEdit(row: ScheduledTaskRead): void {
  editing.value = row
  formVisible.value = true
}

function openLog(row: ScheduledTaskRead): void {
  logTaskId.value = row.id
  logVisible.value = true
}

/** 手动触发：二次确认 → runJob → 提示；409 提示「任务正在执行」。 */
async function handleRun(row: ScheduledTaskRead): Promise<void> {
  try {
    await ElMessageBox.confirm(`确认立即执行任务「${row.name}」吗？`, '提示', {
      type: 'warning',
      confirmButtonText: '确定',
      cancelButtonText: '取消',
    })
  } catch {
    return // 用户取消
  }
  try {
    await runJob(row.id)
    ElMessage.success('已触发执行')
    await table.refresh()
  } catch (err) {
    const apiError = err as ApiError
    ElMessage.error(apiError.status === 409 ? '任务正在执行' : (apiError.message ?? '触发失败'))
  }
}

onMounted(() => {
  void table.refresh()
})
</script>

<template>
  <div class="job-page">
    <!-- 搜索栏 -->
    <el-form inline class="search-bar" @submit.prevent>
      <el-form-item label="状态">
        <el-select
          v-model="table.query.status"
          placeholder="全部"
          clearable
          class="filter-select"
        >
          <el-option label="启用" value="enabled" />
          <el-option label="停用" value="disabled" />
        </el-select>
      </el-form-item>
      <el-form-item label="处理器">
        <el-input
          v-model="table.query.handler_key"
          placeholder="按处理器 key 搜索"
          clearable
          @keyup.enter="table.search()"
        />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="table.search()">查询</el-button>
        <el-button @click="table.reset()">重置</el-button>
      </el-form-item>
    </el-form>

    <!-- 工具栏 -->
    <div class="toolbar">
      <el-button v-hasPermi="'system:job:add'" type="primary" @click="openCreate">
        新增
      </el-button>
    </div>

    <!-- 列表 -->
    <el-table v-loading="table.loading.value" :data="table.rows.value" border>
      <el-table-column prop="name" label="任务名称" min-width="140" show-overflow-tooltip />
      <el-table-column prop="handler_key" label="处理器" min-width="140" show-overflow-tooltip />
      <el-table-column prop="cron_expression" label="cron" min-width="130" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'enabled' ? 'success' : 'info'">
            {{ row.status === 'enabled' ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="last_status" label="上次结果" width="110">
        <template #default="{ row }">
          {{ row.last_status ?? '-' }}
        </template>
      </el-table-column>
      <el-table-column prop="next_run_at" label="下次执行" min-width="180">
        <template #default="{ row }">
          {{ row.next_run_at ?? '-' }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="240" fixed="right">
        <template #default="{ row }">
          <el-button v-hasPermi="'system:job:edit'" link type="primary" @click="openEdit(row)">
            编辑
          </el-button>
          <el-button
            v-hasPermi="'system:job:remove'"
            link
            type="danger"
            @click="table.remove(row.id)"
          >
            删除
          </el-button>
          <el-button v-hasPermi="'system:job:run'" link type="success" @click="handleRun(row)">
            执行
          </el-button>
          <el-button v-hasPermi="'system:job:query'" link @click="openLog(row)">
            日志
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <TablePagination
      v-model:page="table.page.value"
      v-model:size="table.size.value"
      :total="table.total.value"
      class="pagination"
      @change="table.refresh()"
    />

    <JobFormDialog v-model:visible="formVisible" :editing="editing" @saved="table.refresh()" />
    <JobLogDialog v-model:visible="logVisible" :task-id="logTaskId" />
  </div>
</template>

<style scoped>
.job-page {
  padding: 16px;
}
.toolbar {
  margin-bottom: 12px;
}
.filter-select {
  width: 140px;
}
.pagination {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
