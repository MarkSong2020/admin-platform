<script setup lang="ts">
/**
 * 登录日志页（只读）。复用 useCrudTable 管列表/分页/查询（不传 removeItem，无删除）。
 * 字段少，直接列表展示（含 user_agent），不另开详情对话框。
 * user_agent 等外部输入经 el-table 文本插值渲染（非 v-html），杜绝 XSS。
 */
import { onMounted } from 'vue'
import { useCrudTable } from '@/composables/useCrudTable'
import TablePagination from '@/components/TablePagination.vue'
import { listLogininfor, type LoginLogRead } from '@/api/logininfor'
import { formatDateTime } from '@/utils/format'

interface LogininforQuery {
  username?: string
  status?: string
}

const table = useCrudTable<LoginLogRead, LogininforQuery>({
  fetchPage: async (params) => {
    const page = await listLogininfor(params)
    return { items: page.items, total: page.total }
  },
})

onMounted(() => {
  void table.refresh()
})
</script>

<template>
  <div class="logininfor-page">
    <!-- 搜索栏 -->
    <el-form inline class="search-bar" @submit.prevent>
      <el-form-item label="用户名">
        <el-input
          v-model="table.query.username"
          placeholder="按用户名搜索"
          clearable
          @keyup.enter="table.search()"
        />
      </el-form-item>
      <el-form-item label="状态">
        <el-select v-model="table.query.status" placeholder="全部" clearable style="width: 140px">
          <el-option label="成功" value="success" />
          <el-option label="失败" value="failure" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="table.search()">查询</el-button>
        <el-button @click="table.reset()">重置</el-button>
      </el-form-item>
    </el-form>

    <!-- 列表 -->
    <el-table v-loading="table.loading.value" :data="table.rows.value" border>
      <el-table-column label="登录时间" min-width="170">
        <template #default="{ row }">{{ formatDateTime(row.login_at_utc) }}</template>
      </el-table-column>
      <el-table-column prop="username" label="用户名" min-width="140" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'success' ? 'success' : 'danger'">
            {{ row.status === 'success' ? '成功' : '失败' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="原因码" min-width="160">
        <template #default="{ row }">{{ row.reason_code ?? '-' }}</template>
      </el-table-column>
      <el-table-column prop="ip" label="IP" min-width="140" />
      <el-table-column prop="user_agent" label="User-Agent" min-width="240" show-overflow-tooltip />
    </el-table>

    <!-- 分页 -->
    <TablePagination
      v-model:page="table.page.value"
      v-model:size="table.size.value"
      :total="table.total.value"
      class="pagination"
      @change="table.refresh()"
    />
  </div>
</template>

<style scoped>
.logininfor-page {
  padding: 16px;
}
.pagination {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
