<script setup lang="ts">
/**
 * 角色管理页（最复杂域）。复用 useCrudTable（列表/分页/删除）+ TablePagination，
 * 新增/编辑表单 + 分配菜单（数据权限）+ 分配部门（自定义数据范围）拆为同目录 components/ 子对话框。
 * v-hasPermi 仅控按钮可见性（UX 层），后端 RBAC 才是安全边界。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useCrudTable } from '@/composables/useCrudTable'
import TablePagination from '@/components/TablePagination.vue'
import RoleFormDialog from './components/RoleFormDialog.vue'
import RoleMenuDialog from './components/RoleMenuDialog.vue'
import RoleDeptDialog from './components/RoleDeptDialog.vue'
import { listRoles, deleteRole, type RoleRead } from '@/api/roles'

interface RoleQuery {
  keyword?: string
}

/** data_scope 枚举值 → 中文标签。 */
const DATA_SCOPE_LABELS: Record<string, string> = {
  all: '全部数据权限',
  custom_dept: '自定义数据权限',
  self_dept: '本部门数据权限',
  self_dept_and_below: '本部门及以下',
  self: '仅本人数据权限',
}

function dataScopeLabel(scope: string): string {
  return DATA_SCOPE_LABELS[scope] ?? scope
}

const table = useCrudTable<RoleRead, RoleQuery>({
  fetchPage: async (params) => {
    const page = await listRoles(params)
    return { items: page.items, total: page.total }
  },
  removeItem: deleteRole,
})

// 对话框状态
const formVisible = ref(false)
const editing = ref<RoleRead | null>(null)
const menuVisible = ref(false)
const deptVisible = ref(false)
const bindingRoleId = ref<number | null>(null)
/** 当前操作行；其 data_scope 决定「分配部门」是否可用（仅 custom_dept）。 */
const bindingRole = ref<RoleRead | null>(null)

const canBindDept = computed(() => bindingRole.value?.data_scope === 'custom_dept')

function openCreate(): void {
  editing.value = null
  formVisible.value = true
}

function openEdit(row: RoleRead): void {
  editing.value = row
  formVisible.value = true
}

function openMenu(row: RoleRead): void {
  bindingRole.value = row
  bindingRoleId.value = row.id
  menuVisible.value = true
}

/** 仅 data_scope=custom_dept 的角色可分配部门；否则给出提示。 */
function openDept(row: RoleRead): void {
  if (row.data_scope !== 'custom_dept') {
    ElMessage.warning('仅「自定义数据权限」的角色可分配部门')
    return
  }
  bindingRole.value = row
  bindingRoleId.value = row.id
  deptVisible.value = true
}

onMounted(() => {
  void table.refresh()
})
</script>

<template>
  <div class="role-page">
    <!-- 搜索栏 -->
    <el-form inline class="search-bar" @submit.prevent>
      <el-form-item label="角色名称">
        <el-input
          v-model="table.query.keyword"
          placeholder="按角色名 / 编码搜索"
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
      <el-button v-hasPermi="'system:role:add'" type="primary" @click="openCreate">
        新增
      </el-button>
    </div>

    <!-- 列表 -->
    <el-table v-loading="table.loading.value" :data="table.rows.value" border>
      <el-table-column prop="code" label="角色编码" min-width="120" />
      <el-table-column prop="name" label="角色名称" min-width="120" />
      <el-table-column label="数据范围" min-width="160">
        <template #default="{ row }">
          <el-tag :type="row.data_scope === 'all' ? 'danger' : 'info'">
            {{ dataScopeLabel(row.data_scope) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="sort_order" label="排序" width="80" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'">
            {{ row.status === 'active' ? '正常' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="320" fixed="right">
        <template #default="{ row }">
          <el-button v-hasPermi="'system:role:edit'" link type="primary" @click="openEdit(row)">
            编辑
          </el-button>
          <el-button v-hasPermi="'system:role:edit'" link type="primary" @click="openMenu(row)">
            分配菜单
          </el-button>
          <el-button
            v-hasPermi="'system:role:edit'"
            link
            type="primary"
            :disabled="row.data_scope !== 'custom_dept'"
            @click="openDept(row)"
          >
            分配部门
          </el-button>
          <el-button
            v-hasPermi="'system:role:remove'"
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

    <RoleFormDialog v-model:visible="formVisible" :editing="editing" @saved="table.refresh()" />
    <RoleMenuDialog v-model:visible="menuVisible" :role-id="bindingRoleId" />
    <RoleDeptDialog v-if="canBindDept" v-model:visible="deptVisible" :role-id="bindingRoleId" />
  </div>
</template>

<style scoped>
.role-page {
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
