<script setup lang="ts">
/**
 * 菜单管理页（树形 + 类型联动表单）。menu 无独立树端点：一次拉全平铺列表（size=100），
 * 前端按 parent_id 用 buildTree 组树，el-table 树形展示（不分页）。
 * 类型联动表单拆到 components/MenuFormDialog.vue。
 * v-hasPermi 仅控按钮可见性（UX 层），后端 RBAC 才是安全边界。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { buildTree, type TreeNode } from '@/composables/useTree'
import MenuFormDialog from './components/MenuFormDialog.vue'
import { listMenus, deleteMenu, type MenuRead } from '@/api/menus'

const loading = ref(false)
/** 平铺菜单列表（树由 computed 派生；对话框父选择器也复用此平铺源）。 */
const flatMenus = ref<MenuRead[]>([])
const tree = computed<TreeNode<MenuRead>[]>(() => buildTree(flatMenus.value))

const formVisible = ref(false)
const editing = ref<MenuRead | null>(null)
/** 新增子级时预置的父菜单 id（顶级新增为 null）。 */
const presetParentId = ref<number | null>(null)

/** menu_type → 中文标签 + el-tag 类型。 */
const TYPE_LABEL: Record<string, string> = { M: '目录', C: '菜单', F: '按钮' }
const TYPE_TAG: Record<string, 'primary' | 'success' | 'info'> = {
  M: 'primary',
  C: 'success',
  F: 'info',
}

/** 一次拉全菜单（size=100 上限）；超 100 需翻页，当前后台菜单量未达上限。 */
async function refresh(): Promise<void> {
  loading.value = true
  try {
    const page = await listMenus({ page: 1, size: 100 })
    flatMenus.value = page.items
  } catch (err) {
    ElMessage.error((err as { message?: string }).message ?? '加载失败')
  } finally {
    loading.value = false
  }
}

function openCreate(): void {
  editing.value = null
  presetParentId.value = null
  formVisible.value = true
}

/** 新增子级：预置父菜单 id 后以新增模式打开。 */
function openCreateChild(row: MenuRead): void {
  editing.value = null
  presetParentId.value = row.id
  formVisible.value = true
}

function openEdit(row: MenuRead): void {
  editing.value = row
  presetParentId.value = null
  formVisible.value = true
}

/** 删除：二次确认 → deleteMenu → 刷新（409=存在子菜单）。 */
async function remove(row: MenuRead): Promise<void> {
  try {
    await ElMessageBox.confirm(`确认删除菜单「${row.name}」吗？`, '提示', {
      type: 'warning',
      confirmButtonText: '确定',
      cancelButtonText: '取消',
    })
  } catch {
    return // 用户取消
  }
  try {
    await deleteMenu(row.id)
    ElMessage.success('删除成功')
    await refresh()
  } catch (err) {
    const apiError = err as { status?: number; message?: string }
    const message =
      apiError.status === 409 ? '存在子菜单，无法删除' : (apiError.message ?? '删除失败')
    ElMessage.error(message)
  }
}

onMounted(() => {
  void refresh()
})
</script>

<template>
  <div class="menu-page">
    <!-- 工具栏 -->
    <div class="toolbar">
      <el-button v-hasPermi="'system:menu:add'" type="primary" @click="openCreate"> 新增 </el-button>
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
      <el-table-column prop="name" label="菜单名称" min-width="180" />
      <el-table-column label="类型" width="90">
        <template #default="{ row }">
          <el-tag :type="TYPE_TAG[row.menu_type] ?? 'info'">
            {{ TYPE_LABEL[row.menu_type] ?? row.menu_type }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="icon" label="图标" width="100" />
      <el-table-column prop="perms" label="权限标识" min-width="160" show-overflow-tooltip />
      <el-table-column prop="sort_order" label="排序" width="70" />
      <el-table-column label="显示" width="80">
        <template #default="{ row }">
          <el-tag :type="row.visible ? 'success' : 'info'">
            {{ row.visible ? '显示' : '隐藏' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'">
            {{ row.status === 'active' ? '正常' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button
            v-hasPermi="'system:menu:add'"
            link
            type="primary"
            @click="openCreateChild(row)"
          >
            新增子级
          </el-button>
          <el-button v-hasPermi="'system:menu:edit'" link type="primary" @click="openEdit(row)">
            编辑
          </el-button>
          <el-button v-hasPermi="'system:menu:remove'" link type="danger" @click="remove(row)">
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <MenuFormDialog
      v-model:visible="formVisible"
      :editing="editing"
      :menus="flatMenus"
      :preset-parent-id="presetParentId"
      @saved="refresh()"
    />
  </div>
</template>

<style scoped>
.menu-page {
  padding: 16px;
}
.toolbar {
  margin-bottom: 12px;
}
</style>
