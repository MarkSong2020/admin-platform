<script setup lang="ts">
/**
 * 操作日志页（只读）。复用 useCrudTable 管列表/分页/查询（不传 removeItem，无删除）。
 * 筛选 event_type / result_status；点「详情」拉 AuditEventDetail 弹窗展示全字段含 payload。
 * v-hasPermi 仅控按钮可见性（UX 层），后端 RBAC 才是安全边界。
 */
import { onMounted, ref } from 'vue'
import { useCrudTable } from '@/composables/useCrudTable'
import TablePagination from '@/components/TablePagination.vue'
import OperlogDetailDialog from './components/OperlogDetailDialog.vue'
import { listOperlog, type AuditEventRead } from '@/api/operlog'
import { formatDateTime } from '@/utils/format'

interface OperlogQuery {
  event_type?: string
  result_status?: string
}

const table = useCrudTable<AuditEventRead, OperlogQuery>({
  fetchPage: async (params) => {
    const page = await listOperlog(params)
    return { items: page.items, total: page.total }
  },
})

const detailVisible = ref(false)
const detailPk = ref<number | null>(null)

function openDetail(row: AuditEventRead): void {
  detailPk.value = row.id
  detailVisible.value = true
}

onMounted(() => {
  void table.refresh()
})
</script>

<template>
  <div class="operlog-page">
    <!-- 搜索栏 -->
    <el-form inline class="search-bar" @submit.prevent>
      <el-form-item label="事件类型">
        <el-input
          v-model="table.query.event_type"
          placeholder="如 user.login"
          clearable
          @keyup.enter="table.search()"
        />
      </el-form-item>
      <el-form-item label="结果">
        <el-select
          v-model="table.query.result_status"
          placeholder="全部"
          clearable
          style="width: 140px"
        >
          <el-option label="成功" value="success" />
          <el-option label="失败" value="failure" />
          <el-option label="拒绝" value="denied" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="table.search()">查询</el-button>
        <el-button @click="table.reset()">重置</el-button>
      </el-form-item>
    </el-form>

    <!-- 列表 -->
    <el-table v-loading="table.loading.value" :data="table.rows.value" border>
      <el-table-column label="时间" min-width="170">
        <template #default="{ row }">{{ formatDateTime(row.occurred_at) }}</template>
      </el-table-column>
      <el-table-column prop="event_type" label="事件类型" min-width="150" show-overflow-tooltip />
      <el-table-column prop="title" label="标题" min-width="140" show-overflow-tooltip />
      <el-table-column prop="actor_username" label="操作者" min-width="120" />
      <el-table-column label="结果" width="90">
        <template #default="{ row }">
          <el-tag :type="row.result_status === 'success' ? 'success' : 'danger'">
            {{ row.result_status === 'success' ? '成功' : '失败' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="method" label="方法" width="90" />
      <el-table-column prop="path" label="路径" min-width="200" show-overflow-tooltip />
      <el-table-column prop="ip" label="IP" min-width="130" />
      <el-table-column label="耗时(ms)" width="100">
        <template #default="{ row }">{{ row.duration_ms ?? '-' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button
            v-hasPermi="'system:operlog:query'"
            link
            type="primary"
            @click="openDetail(row)"
          >
            详情
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

    <OperlogDetailDialog v-model:visible="detailVisible" :event-pk="detailPk" />
  </div>
</template>

<style scoped>
.operlog-page {
  padding: 16px;
}
.pagination {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
