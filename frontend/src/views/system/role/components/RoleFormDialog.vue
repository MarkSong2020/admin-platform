<script setup lang="ts">
/**
 * 角色新增 / 编辑对话框。
 * 新增：code 必填；编辑：code 禁改（后端约束 code 不可改）。
 * data_scope 5 选项（all / custom_dept / self_dept / self_dept_and_below / self），中文标签下拉。
 */
import { computed, reactive, ref, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import { createRole, updateRole, type RoleRead } from '@/api/roles'

const props = defineProps<{
  /** 被编辑的角色；null = 新增模式。 */
  editing: RoleRead | null
}>()

const visible = defineModel<boolean>('visible', { required: true })

const emit = defineEmits<{
  /** 提交成功，父组件据此刷新列表。 */
  (e: 'saved'): void
}>()

/** data_scope 枚举值 → 中文标签（5 值，cheatsheet §9）。 */
type DataScope = 'all' | 'custom_dept' | 'self_dept' | 'self_dept_and_below' | 'self'
const DATA_SCOPE_OPTIONS: { value: DataScope; label: string }[] = [
  { value: 'all', label: '全部数据权限' },
  { value: 'custom_dept', label: '自定义数据权限' },
  { value: 'self_dept', label: '本部门数据权限' },
  { value: 'self_dept_and_below', label: '本部门及以下数据权限' },
  { value: 'self', label: '仅本人数据权限' },
]

const isEdit = computed(() => props.editing !== null)
const formRef = ref<FormInstance>()
const submitting = ref(false)

interface FormModel {
  code: string
  name: string
  dataScope: DataScope
  sortOrder: number
  status: 'active' | 'disabled'
}

const form = reactive<FormModel>({
  code: '',
  name: '',
  dataScope: 'self',
  sortOrder: 0,
  status: 'active',
})

const rules = computed<FormRules<FormModel>>(() => ({
  code: [{ required: !isEdit.value, message: '请输入角色编码', trigger: 'blur' }],
  name: [{ required: true, message: '请输入角色名称', trigger: 'blur' }],
}))

// 打开时按模式回填表单
watch(visible, (open) => {
  if (!open) return
  formRef.value?.clearValidate()
  const editing = props.editing
  if (editing) {
    form.code = editing.code
    form.name = editing.name
    form.dataScope = editing.data_scope as DataScope
    form.sortOrder = editing.sort_order
    form.status = editing.status === 'disabled' ? 'disabled' : 'active'
  } else {
    form.code = ''
    form.name = ''
    form.dataScope = 'self'
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
      await updateRole(props.editing.id, {
        name: form.name,
        data_scope: form.dataScope,
        sort_order: form.sortOrder,
        status: form.status,
      })
    } else {
      await createRole({
        code: form.code,
        name: form.name,
        data_scope: form.dataScope,
        sort_order: form.sortOrder,
        status: form.status,
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
    :title="isEdit ? '编辑角色' : '新增角色'"
    width="480px"
    append-to-body
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
      <el-form-item label="角色编码" prop="code">
        <el-input v-model="form.code" :disabled="isEdit" placeholder="全局唯一编码" />
      </el-form-item>
      <el-form-item label="角色名称" prop="name">
        <el-input v-model="form.name" placeholder="显示名称" />
      </el-form-item>
      <el-form-item label="数据范围" prop="dataScope">
        <el-select v-model="form.dataScope" placeholder="选择数据范围" style="width: 100%">
          <el-option
            v-for="opt in DATA_SCOPE_OPTIONS"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="显示顺序" prop="sortOrder">
        <el-input-number v-model="form.sortOrder" :min="0" controls-position="right" />
      </el-form-item>
      <el-form-item label="状态" prop="status">
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
