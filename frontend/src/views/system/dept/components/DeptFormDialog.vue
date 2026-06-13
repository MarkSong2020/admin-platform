<script setup lang="ts">
/**
 * 部门新增 / 编辑对话框。
 * 新增：code 必填；编辑：code 禁改、加状态切换。
 * parent_id 用 el-tree-select 从部门树选（可空=顶级）。编辑时自身及其子孙在树中禁选（防环）。
 */
import { computed, reactive, ref, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import { createDept, updateDept, type DeptRead } from '@/api/depts'
import { buildTree, type TreeNode } from '@/composables/useTree'

const props = defineProps<{
  /** 被编辑的部门；null = 新增模式。 */
  editing: DeptRead | null
  /** 全部部门平铺列表，用于构建父部门选择树。 */
  depts: DeptRead[]
}>()

const visible = defineModel<boolean>('visible', { required: true })

const emit = defineEmits<{
  /** 提交成功，父组件据此刷新列表。 */
  (e: 'saved'): void
}>()

const isEdit = computed(() => props.editing !== null)
const formRef = ref<FormInstance>()
const submitting = ref(false)

interface FormModel {
  code: string
  name: string
  parentId: number | null
  leader: string
  phone: string
  email: string
  sortOrder: number
  status: 'active' | 'disabled'
}

const form = reactive<FormModel>({
  code: '',
  name: '',
  parentId: null,
  leader: '',
  phone: '',
  email: '',
  sortOrder: 0,
  status: 'active',
})

const rules = computed<FormRules<FormModel>>(() => ({
  code: [{ required: !isEdit.value, message: '请输入部门编码', trigger: 'blur' }],
  name: [{ required: true, message: '请输入部门名称', trigger: 'blur' }],
  email: [{ type: 'email', message: '邮箱格式不正确', trigger: 'blur' }],
}))

/** 编辑模式下自身及其子孙的 id 集合（在父部门树中禁选，防成环）。 */
const disabledIds = computed<Set<number>>(() => {
  const ids = new Set<number>()
  const editing = props.editing
  if (!editing) return ids
  const childrenOf = new Map<number | null, DeptRead[]>()
  for (const d of props.depts) {
    const list = childrenOf.get(d.parent_id) ?? []
    list.push(d)
    childrenOf.set(d.parent_id, list)
  }
  const stack = [editing.id]
  while (stack.length > 0) {
    const id = stack.pop()!
    ids.add(id)
    for (const child of childrenOf.get(id) ?? []) stack.push(child.id)
  }
  return ids
})

/** el-tree-select 数据：部门树 + 节点禁选标记（防环）。 */
const treeData = computed<TreeNode<DeptRead>[]>(() => {
  const banned = disabledIds.value
  const decorate = (nodes: TreeNode<DeptRead>[]): TreeNode<DeptRead>[] =>
    nodes.map((node) => ({
      ...node,
      disabled: banned.has(node.id),
      children: node.children ? decorate(node.children) : undefined,
    }))
  return decorate(buildTree(props.depts))
})

// 打开时按模式回填表单
watch(visible, (open) => {
  if (!open) return
  formRef.value?.clearValidate()
  const editing = props.editing
  if (editing) {
    form.code = editing.code
    form.name = editing.name
    form.parentId = editing.parent_id
    form.leader = editing.leader ?? ''
    form.phone = editing.phone ?? ''
    form.email = editing.email ?? ''
    form.sortOrder = editing.sort_order
    form.status = editing.status === 'disabled' ? 'disabled' : 'active'
  } else {
    form.code = ''
    form.name = ''
    form.parentId = null
    form.leader = ''
    form.phone = ''
    form.email = ''
    form.sortOrder = 0
    form.status = 'active'
  }
})

async function submit(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    if (props.editing) {
      await updateDept(props.editing.id, {
        name: form.name,
        parent_id: form.parentId,
        leader: form.leader || null,
        phone: form.phone || null,
        email: form.email || null,
        sort_order: form.sortOrder,
        status: form.status,
      })
    } else {
      await createDept({
        code: form.code,
        name: form.name,
        parent_id: form.parentId,
        leader: form.leader || null,
        phone: form.phone || null,
        email: form.email || null,
        sort_order: form.sortOrder,
      })
    }
    ElMessage.success(isEdit.value ? '修改成功' : '新增成功')
    visible.value = false
    emit('saved')
  } catch (err) {
    ElMessage.error((err as { message?: string }).message ?? '提交失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="isEdit ? '编辑部门' : '新增部门'"
    width="480px"
    append-to-body
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
      <el-form-item label="上级部门" prop="parentId">
        <el-tree-select
          v-model="form.parentId"
          :data="treeData"
          :props="{ label: 'name', children: 'children' }"
          node-key="id"
          check-strictly
          clearable
          placeholder="不选则为顶级部门"
          class="full-width"
        />
      </el-form-item>
      <el-form-item label="部门编码" prop="code">
        <el-input v-model="form.code" :disabled="isEdit" placeholder="全局唯一编码" />
      </el-form-item>
      <el-form-item label="部门名称" prop="name">
        <el-input v-model="form.name" placeholder="部门名称" />
      </el-form-item>
      <el-form-item label="负责人" prop="leader">
        <el-input v-model="form.leader" placeholder="负责人" />
      </el-form-item>
      <el-form-item label="联系电话" prop="phone">
        <el-input v-model="form.phone" placeholder="联系电话" />
      </el-form-item>
      <el-form-item label="邮箱" prop="email">
        <el-input v-model="form.email" placeholder="邮箱" />
      </el-form-item>
      <el-form-item label="显示顺序" prop="sortOrder">
        <el-input-number v-model="form.sortOrder" :min="0" controls-position="right" />
      </el-form-item>
      <el-form-item v-if="isEdit" label="状态" prop="status">
        <el-radio-group v-model="form.status">
          <el-radio value="active">正常</el-radio>
          <el-radio value="disabled">停用</el-radio>
        </el-radio-group>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">确定</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.full-width {
  width: 100%;
}
</style>
