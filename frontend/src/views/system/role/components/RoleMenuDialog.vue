<script setup lang="ts">
/**
 * 分配菜单（菜单数据权限）对话框：照 UserRolesDialog 范式，
 * 打开时并发拉「全部菜单（组树）」+「该角色已绑定菜单 id」，
 * el-tree show-checkbox 勾选后 setRoleMenus 全量替换。
 *
 * 菜单 list 返回分页平铺（无独立树端点），前端 buildTree 按 parent_id 组树。
 * listMenus 从 @/api/menus import（menu 页提供该导出）。
 */
import { nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { ElTree } from 'element-plus'
import { listMenus, type MenuRead } from '@/api/menus'
import { getRoleMenus, setRoleMenus } from '@/api/roles'
import { buildTree, type TreeNode } from '@/composables/useTree'

const props = defineProps<{
  /** 目标角色 id；null = 未选中（对话框不应打开）。 */
  roleId: number | null
}>()

const visible = defineModel<boolean>('visible', { required: true })

/** el-tree 节点属性映射（label 取菜单名）。 */
const treeProps = { label: 'name', children: 'children' } as const

const treeRef = ref<InstanceType<typeof ElTree>>()
const treeData = ref<TreeNode<MenuRead>[]>([])
const checkedKeys = ref<number[]>([])
const loading = ref(false)
const submitting = ref(false)

watch(visible, async (open) => {
  if (!open || props.roleId === null) return
  loading.value = true
  try {
    const [menuPage, binding] = await Promise.all([
      listMenus({ page: 1, size: 100 }),
      getRoleMenus(props.roleId),
    ])
    treeData.value = buildTree<MenuRead>(menuPage.items)
    checkedKeys.value = binding.ids
    // 树渲染后再回填勾选，避免 default-checked-keys 在数据未就绪时丢失
    await nextTick()
    treeRef.value?.setCheckedKeys(binding.ids, false)
  } catch (err) {
    ElMessage.error((err as { message?: string }).message ?? '加载菜单失败')
  } finally {
    loading.value = false
  }
})

async function submit(): Promise<void> {
  if (props.roleId === null) return
  submitting.value = true
  try {
    // 半选（父节点部分勾选）也要纳入，否则后端拿不到中间目录
    const checked = treeRef.value?.getCheckedKeys(false) ?? checkedKeys.value
    const halfChecked = treeRef.value?.getHalfCheckedKeys() ?? []
    const ids = [...checked, ...halfChecked].map((key) => Number(key))
    await setRoleMenus(props.roleId, ids)
    ElMessage.success('菜单分配成功')
    visible.value = false
  } catch (err) {
    ElMessage.error((err as { message?: string }).message ?? '分配失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    title="分配菜单"
    width="480px"
    append-to-body
    :close-on-click-modal="false"
  >
    <el-tree
      ref="treeRef"
      v-loading="loading"
      :data="treeData"
      :props="treeProps"
      show-checkbox
      node-key="id"
      :default-checked-keys="checkedKeys"
      :default-expand-all="true"
      class="menu-tree"
    />
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">确定</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.menu-tree {
  max-height: 50vh;
  overflow-y: auto;
}
</style>
