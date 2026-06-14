<script setup lang="ts">
/**
 * 部门管理页（树形）。dept 无独立树端点：一次拉全平铺列表（size=100），
 * 前端按 parent_id 用 buildTree 组树，el-table 树形展示（不分页）。
 * v-hasPermi 仅控按钮可见性（UX 层），后端 RBAC 才是安全边界。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { buildTree, type TreeNode } from '@/composables/useTree'
import DeptFormDialog from './components/DeptFormDialog.vue'
import { listDepts, deleteDept, type DeptRead } from '@/api/depts'

const loading = ref(false)
const keyword = ref('')
/** 平铺部门列表（树由 computed 派生；对话框父选择器也复用此平铺源）。 */
const flatDepts = ref<DeptRead[]>([])
const tree = computed<TreeNode<DeptRead>[]>(() => buildTree(flatDepts.value))

const formVisible = ref(false)
const editing = ref<DeptRead | null>(null)

/** 一次拉全部门（size=100 上限）；keyword 透传以便后端补齐后联通。 */
async function refresh(): Promise<void> {
  loading.value = true
  try {
    const page = await listDepts({ page: 1, size: 100, keyword: keyword.value || undefined })
    flatDepts.value = page.items
  } catch (err) {
    ElMessage.error((err as { message?: string }).message ?? '加载失败')
  } finally {
    loading.value = false
  }
}

function search(): void {
  void refresh()
}

function reset(): void {
  keyword.value = ''
  void refresh()
}

function openCreate(): void {
  editing.value = null
  formVisible.value = true
}

function openEdit(row: DeptRead): void {
  editing.value = row
  formVisible.value = true
}

/** 删除：二次确认 → deleteDept → 刷新（409=存在子部门或关联）。 */
async function remove(row: DeptRead): Promise<void> {
  try {
    await ElMessageBox.confirm(`确认删除部门「${row.name}」吗？`, '提示', {
      type: 'warning',
      confirmButtonText: '确定',
      cancelButtonText: '取消',
    })
  } catch {
    return // 用户取消
  }
  try {
    await deleteDept(row.id)
    ElMessage.success('删除成功')
    await refresh()
  } catch (err) {
    const apiError = err as { status?: number; message?: string }
    const message =
      apiError.status === 409 ? '存在子部门或关联，无法删除' : (apiError.message ?? '删除失败')
    ElMessage.error(message)
  }
}

onMounted(() => {
  void refresh()
})
</script>

<template>
  <div class="dept-page">
    <!-- 搜索栏 -->
    <el-form inline class="search-bar" @submit.prevent>
      <el-form-item label="部门名称">
        <el-input
          v-model="keyword"
          placeholder="按部门名称搜索"
          clearable
          @keyup.enter="search()"
        />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="search()">查询</el-button>
        <el-button @click="reset()">重置</el-button>
      </el-form-item>
    </el-form>

    <!-- 工具栏 -->
    <div class="toolbar">
      <el-button v-hasPermi="'system:dept:add'" type="primary" @click="openCreate">
        新增
      </el-button>
    </div>

    <!-- 树形列表 -->
    <el-table
      v-loading="loading"
      :data="tree"
      row-key="id"
      :tree-props="{ children: 'children' }"
      default-expand-all
      border
    >
      <el-table-column prop="name" label="部门名称" min-width="180" />
      <el-table-column prop="leader" label="负责人" min-width="120" />
      <el-table-column prop="phone" label="联系电话" min-width="130" />
      <el-table-column prop="sort_order" label="排序" width="80" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'">
            {{ row.status === 'active' ? '正常' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button v-hasPermi="'system:dept:edit'" link type="primary" @click="openEdit(row)">
            编辑
          </el-button>
          <el-button v-hasPermi="'system:dept:remove'" link type="danger" @click="remove(row)">
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <DeptFormDialog
      v-model:visible="formVisible"
      :editing="editing"
      :depts="flatDepts"
      @saved="refresh()"
    />
  </div>
</template>

<style scoped>
.dept-page {
  padding: 16px;
}
.toolbar {
  margin-bottom: 12px;
}
</style>
