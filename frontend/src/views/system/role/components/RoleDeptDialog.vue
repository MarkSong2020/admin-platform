<script setup lang="ts">
/**
 * 分配数据范围部门对话框：仅当 data_scope==="custom_dept" 可用（父组件控制开启）。
 * 打开时并发拉「全部部门（组树）」+「该角色已绑定部门 id」，
 * el-tree show-checkbox 勾选后 setRoleDepts 全量替换。
 *
 * dept list 平铺分页（无独立树端点），前端 buildTree 按 parent_id 组树。
 */
import { nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { ElTree } from 'element-plus'
import { listDepts, type DeptRead } from '@/api/depts'
import { getRoleDepts, setRoleDepts } from '@/api/roles'
import { buildTree, type TreeNode } from '@/composables/useTree'

const props = defineProps<{
  /** 目标角色 id；null = 未选中（对话框不应打开）。 */
  roleId: number | null
}>()

const visible = defineModel<boolean>('visible', { required: true })

/** el-tree 节点属性映射（label 取部门名）。 */
const treeProps = { label: 'name', children: 'children' } as const

const treeRef = ref<InstanceType<typeof ElTree>>()
const treeData = ref<TreeNode<DeptRead>[]>([])
const checkedKeys = ref<number[]>([])
const loading = ref(false)
const submitting = ref(false)

watch(visible, async (open) => {
  if (!open || props.roleId === null) return
  loading.value = true
  try {
    const [deptPage, binding] = await Promise.all([
      listDepts({ page: 1, size: 100 }),
      getRoleDepts(props.roleId),
    ])
    treeData.value = buildTree<DeptRead>(deptPage.items)
    checkedKeys.value = binding.ids
    await nextTick()
    treeRef.value?.setCheckedKeys(binding.ids, false)
  } catch (err) {
    ElMessage.error((err as { message?: string }).message ?? '加载部门失败')
  } finally {
    loading.value = false
  }
})

async function submit(): Promise<void> {
  if (props.roleId === null) return
  submitting.value = true
  try {
    const checked = treeRef.value?.getCheckedKeys(false) ?? checkedKeys.value
    const halfChecked = treeRef.value?.getHalfCheckedKeys() ?? []
    const ids = [...checked, ...halfChecked].map((key) => Number(key))
    await setRoleDepts(props.roleId, ids)
    ElMessage.success('部门数据权限分配成功')
    visible.value = false
  } catch (err) {
    ElMessage.error((err as { message?: string }).message ?? '分配失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" title="分配数据权限（部门）" width="480px" append-to-body>
    <el-tree
      ref="treeRef"
      v-loading="loading"
      :data="treeData"
      :props="treeProps"
      show-checkbox
      node-key="id"
      :default-checked-keys="checkedKeys"
      :default-expand-all="true"
      class="dept-tree"
    />
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">确定</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.dept-tree {
  max-height: 50vh;
  overflow-y: auto;
}
</style>
