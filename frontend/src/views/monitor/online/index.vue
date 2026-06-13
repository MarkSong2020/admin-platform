<script setup lang="ts">
/**
 * 在线用户监控页。列表复用 useCrudTable（仅列表/分页/刷新），
 * 强制下线因路径参数是字符串 session_id（非 number 主键），useCrudTable.remove 签名是 (id:number) 不匹配，
 * 故自写 二次确认 + kickOnline + refresh，不套 useCrudTable.remove。
 * v-hasPermi 仅控按钮可见性（UX 层），后端 RBAC 才是安全边界。
 */
import { onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useCrudTable } from '@/composables/useCrudTable'
import TablePagination from '@/components/TablePagination.vue'
import { listOnline, kickOnline, type OnlineSession } from '@/api/online'
import { normalizeApiError, type ApiError } from '@/api/transport'
import { formatDateTime } from '@/utils/format'

const table = useCrudTable<OnlineSession, Record<string, never>>({
  fetchPage: async (params) => {
    const page = await listOnline({ page: params.page, size: params.size })
    return { items: page.items, total: page.total }
  },
})

/**
 * online.ts 抛出的已是归一化 ApiError（普通对象，非 Error 实例）；
 * normalizeApiError 对普通对象会降级成 UNKNOWN，故先识别已归一形状直接用。
 */
function toMessage(err: unknown): string {
  if (
    err !== null &&
    typeof err === 'object' &&
    'code' in err &&
    'status' in err &&
    'message' in err
  ) {
    return (err as ApiError).message
  }
  const normalized = normalizeApiError(err)
  return 'message' in normalized ? normalized.message : '强制下线失败'
}

/** 强制下线：二次确认 → kickOnline（字符串 session_id）→ 刷新列表。 */
async function handleKick(row: OnlineSession): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确认强制下线用户「${row.username}」的会话吗？`,
      '强制下线',
      { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' },
    )
  } catch {
    return // 用户取消，不视为错误
  }
  try {
    await kickOnline(row.session_id)
    ElMessage.success('已强制下线')
    await table.refresh()
  } catch (err) {
    ElMessage.error(toMessage(err))
  }
}

onMounted(() => {
  void table.refresh()
})
</script>

<template>
  <div class="online-page">
    <el-table v-loading="table.loading.value" :data="table.rows.value" border>
      <el-table-column prop="username" label="用户名" min-width="140" />
      <el-table-column label="登录时间" min-width="180">
        <template #default="{ row }">{{ formatDateTime(row.login_time) }}</template>
      </el-table-column>
      <el-table-column label="最后活动时间" min-width="180">
        <template #default="{ row }">{{ formatDateTime(row.last_active_time) }}</template>
      </el-table-column>
      <el-table-column label="过期时间" min-width="180">
        <template #default="{ row }">{{ formatDateTime(row.expires_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button
            v-hasPermi="'system:online:remove'"
            link
            type="danger"
            @click="handleKick(row)"
          >
            强制下线
          </el-button>
        </template>
      </el-table-column>
    </el-table>

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
.online-page {
  padding: 16px;
}
.pagination {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
