<script setup lang="ts">
/**
 * 通知公告页。复用 useCrudTable（列表/分页/删除）+ TablePagination，
 * 新增/编辑拆为同目录 components/NoticeFormDialog。
 * 筛选支持公告类型 + 状态。content 不在列表展示，且全程不 v-html（防 XSS，spec §10 风险12）。
 * v-hasPermi 仅控按钮可见性（UX 层），后端 RBAC 才是安全边界。
 */
import { onMounted, ref } from 'vue'
import { useCrudTable } from '@/composables/useCrudTable'
import TablePagination from '@/components/TablePagination.vue'
import NoticeFormDialog from './components/NoticeFormDialog.vue'
import { listNotices, deleteNotice, type NoticeRead, type NoticeType } from '@/api/notice'

interface NoticeQuery {
  notice_type?: NoticeType
  status?: 'active' | 'disabled'
}

const table = useCrudTable<NoticeRead, NoticeQuery>({
  fetchPage: async (params) => {
    const page = await listNotices(params)
    return { items: page.items, total: page.total }
  },
  removeItem: deleteNotice,
})

const formVisible = ref(false)
const editing = ref<NoticeRead | null>(null)

function openCreate(): void {
  editing.value = null
  formVisible.value = true
}

function openEdit(row: NoticeRead): void {
  editing.value = row
  formVisible.value = true
}

onMounted(() => {
  void table.refresh()
})
</script>

<template>
  <div class="notice-page">
    <!-- 筛选栏 -->
    <el-form inline class="search-bar" @submit.prevent>
      <el-form-item label="类型">
        <el-select
          v-model="table.query.notice_type"
          placeholder="全部"
          clearable
          style="width: 140px"
          @change="table.search()"
        >
          <el-option label="通知" value="notification" />
          <el-option label="公告" value="announcement" />
        </el-select>
      </el-form-item>
      <el-form-item label="状态">
        <el-select
          v-model="table.query.status"
          placeholder="全部"
          clearable
          style="width: 140px"
          @change="table.search()"
        >
          <el-option label="正常" value="active" />
          <el-option label="停用" value="disabled" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="table.search()">查询</el-button>
        <el-button @click="table.reset()">重置</el-button>
      </el-form-item>
    </el-form>

    <!-- 工具栏 -->
    <div class="toolbar">
      <el-button v-hasPermi="'system:notice:add'" type="primary" @click="openCreate">
        新增
      </el-button>
    </div>

    <!-- 列表 -->
    <el-table v-loading="table.loading.value" :data="table.rows.value" border>
      <el-table-column prop="title" label="公告标题" min-width="200" show-overflow-tooltip />
      <el-table-column label="类型" width="100">
        <template #default="{ row }">
          <el-tag :type="row.notice_type === 'announcement' ? 'warning' : 'primary'">
            {{ row.notice_type === 'announcement' ? '公告' : '通知' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'">
            {{ row.status === 'active' ? '正常' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" min-width="180" />
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button v-hasPermi="'system:notice:edit'" link type="primary" @click="openEdit(row)">
            编辑
          </el-button>
          <el-button
            v-hasPermi="'system:notice:remove'"
            link
            type="danger"
            @click="table.remove(row.id)"
          >
            删除
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

    <NoticeFormDialog v-model:visible="formVisible" :editing="editing" @saved="table.refresh()" />
  </div>
</template>

<style scoped>
.notice-page {
  padding: 16px;
}
.toolbar {
  margin-bottom: 12px;
}
.pagination {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
