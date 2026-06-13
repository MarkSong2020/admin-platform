<script setup lang="ts">
/**
 * 岗位管理页。复用 useCrudTable（列表/分页/删除）+ TablePagination，
 * 新增/编辑拆为同目录 components/PostFormDialog。
 * v-hasPermi 仅控按钮可见性（UX 层），后端 RBAC 才是安全边界。
 */
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useCrudTable } from '@/composables/useCrudTable'
import TablePagination from '@/components/TablePagination.vue'
import PostFormDialog from './components/PostFormDialog.vue'
import PostImportDialog from './components/PostImportDialog.vue'
import { listPosts, deletePost, exportPosts, type PostRead } from '@/api/posts'
import { normalizeApiError } from '@/api/transport'

interface PostQuery {
  keyword?: string
}

const table = useCrudTable<PostRead, PostQuery>({
  fetchPage: async (params) => {
    const page = await listPosts(params)
    return { items: page.items, total: page.total }
  },
  removeItem: deletePost,
})

const formVisible = ref(false)
const importVisible = ref(false)
const exporting = ref(false)
const editing = ref<PostRead | null>(null)

function openCreate(): void {
  editing.value = null
  formVisible.value = true
}

function openEdit(row: PostRead): void {
  editing.value = row
  formVisible.value = true
}

/** 导出全量岗位为 posts.xlsx（blob 下载）。 */
async function handleExport(): Promise<void> {
  exporting.value = true
  try {
    await exportPosts()
  } catch (err) {
    ElMessage.error(normalizeApiError(err).message)
  } finally {
    exporting.value = false
  }
}

onMounted(() => {
  void table.refresh()
})
</script>

<template>
  <div class="post-page">
    <!-- 搜索栏 -->
    <el-form inline class="search-bar" @submit.prevent>
      <el-form-item label="岗位">
        <el-input
          v-model="table.query.keyword"
          placeholder="按岗位名/编码搜索"
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
      <el-button v-hasPermi="'system:post:add'" type="primary" @click="openCreate">
        新增
      </el-button>
      <el-button v-hasPermi="'system:post:import'" @click="importVisible = true">
        导入
      </el-button>
      <el-button v-hasPermi="'system:post:export'" :loading="exporting" @click="handleExport">
        导出
      </el-button>
    </div>

    <!-- 列表 -->
    <el-table v-loading="table.loading.value" :data="table.rows.value" border>
      <el-table-column prop="code" label="岗位编码" min-width="140" />
      <el-table-column prop="name" label="岗位名称" min-width="140" />
      <el-table-column prop="sort_order" label="排序" width="100" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'">
            {{ row.status === 'active' ? '正常' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button v-hasPermi="'system:post:edit'" link type="primary" @click="openEdit(row)">
            编辑
          </el-button>
          <el-button
            v-hasPermi="'system:post:remove'"
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

    <PostFormDialog v-model:visible="formVisible" :editing="editing" @saved="table.refresh()" />
    <PostImportDialog v-model:visible="importVisible" @imported="table.refresh()" />
  </div>
</template>

<style scoped>
.post-page {
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
