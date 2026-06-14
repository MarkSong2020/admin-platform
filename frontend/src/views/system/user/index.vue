<script setup lang="ts">
/**
 * 用户管理页。复用 useCrudTable（列表/分页/删除）+ TablePagination，
 * 新增/编辑/分配角色/分配岗位拆为同目录 components/ 子对话框。
 * v-hasPermi 仅控按钮可见性（UX 层），后端 RBAC 才是安全边界（spec §5）。
 */
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useCrudTable } from '@/composables/useCrudTable'
import TablePagination from '@/components/TablePagination.vue'
import UserFormDialog from './components/UserFormDialog.vue'
import UserRolesDialog from './components/UserRolesDialog.vue'
import UserPostsDialog from './components/UserPostsDialog.vue'
import { listUsers, deleteUser, updateUser, type UserRead } from '@/api/users'

interface UserQuery {
  keyword?: string
}

const table = useCrudTable<UserRead, UserQuery>({
  fetchPage: async (params) => {
    const page = await listUsers(params)
    return { items: page.items, total: page.total }
  },
  removeItem: deleteUser,
})

// 对话框状态
const formVisible = ref(false)
const editing = ref<UserRead | null>(null)
const rolesVisible = ref(false)
const postsVisible = ref(false)
const bindingUserId = ref<number | null>(null)

function openCreate(): void {
  editing.value = null
  formVisible.value = true
}

function openEdit(row: UserRead): void {
  editing.value = row
  formVisible.value = true
}

function openRoles(row: UserRead): void {
  bindingUserId.value = row.id
  rolesVisible.value = true
}

function openPosts(row: UserRead): void {
  bindingUserId.value = row.id
  postsVisible.value = true
}

/** 点 status 标签切换启用/停用（走 PATCH）。 */
async function toggleStatus(row: UserRead): Promise<void> {
  const next = row.status === 'active' ? 'disabled' : 'active'
  try {
    await updateUser(row.id, { status: next })
    ElMessage.success(next === 'active' ? '已启用' : '已停用')
    await table.refresh()
  } catch (err) {
    ElMessage.error((err as { message?: string }).message ?? '状态切换失败')
  }
}

onMounted(() => {
  void table.refresh()
})
</script>

<template>
  <div class="user-page">
    <!-- 搜索栏 -->
    <el-form inline class="search-bar" @submit.prevent>
      <el-form-item label="用户名">
        <el-input
          v-model="table.query.keyword"
          placeholder="按用户名搜索"
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
      <el-button v-hasPermi="'system:user:add'" type="primary" @click="openCreate">
        新增
      </el-button>
    </div>

    <!-- 列表 -->
    <el-table v-loading="table.loading.value" :data="table.rows.value" border>
      <el-table-column prop="username" label="用户名" min-width="120" />
      <el-table-column prop="nickname" label="昵称" min-width="120" />
      <el-table-column prop="dept_id" label="部门" width="100" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag
            :type="row.status === 'active' ? 'success' : 'info'"
            class="status-tag"
            @click="toggleStatus(row)"
          >
            {{ row.status === 'active' ? '正常' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="320" fixed="right">
        <template #default="{ row }">
          <el-button v-hasPermi="'system:user:edit'" link type="primary" @click="openEdit(row)">
            编辑
          </el-button>
          <el-button v-hasPermi="'system:user:edit'" link type="primary" @click="openRoles(row)">
            分配角色
          </el-button>
          <el-button v-hasPermi="'system:user:edit'" link type="primary" @click="openPosts(row)">
            分配岗位
          </el-button>
          <el-button
            v-hasPermi="'system:user:remove'"
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

    <UserFormDialog v-model:visible="formVisible" :editing="editing" @saved="table.refresh()" />
    <UserRolesDialog v-model:visible="rolesVisible" :user-id="bindingUserId" />
    <UserPostsDialog v-model:visible="postsVisible" :user-id="bindingUserId" />
  </div>
</template>

<style scoped>
.user-page {
  padding: 16px;
}
.toolbar {
  margin-bottom: 12px;
}
.status-tag {
  cursor: pointer;
}
.pagination {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
