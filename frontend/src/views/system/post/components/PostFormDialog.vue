<script setup lang="ts">
/**
 * 岗位新增 / 编辑对话框。
 * 新增：code 必填；编辑：code 禁改（唯一编码不可变）。name 必填、sort_order 数字、status 切换。
 */
import { computed, reactive, ref, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import { createPost, updatePost, type PostRead } from '@/api/posts'

const props = defineProps<{
  /** 被编辑的岗位；null = 新增模式。 */
  editing: PostRead | null
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
  sortOrder: number
  status: 'active' | 'disabled'
}

const form = reactive<FormModel>({
  code: '',
  name: '',
  sortOrder: 0,
  status: 'active',
})

const rules = computed<FormRules<FormModel>>(() => ({
  code: [{ required: !isEdit.value, message: '请输入岗位编码', trigger: 'blur' }],
  name: [{ required: true, message: '请输入岗位名称', trigger: 'blur' }],
}))

// 打开时按模式回填表单
watch(visible, (open) => {
  if (!open) return
  formRef.value?.clearValidate()
  const editing = props.editing
  if (editing) {
    form.code = editing.code
    form.name = editing.name
    form.sortOrder = editing.sort_order
    form.status = editing.status === 'disabled' ? 'disabled' : 'active'
  } else {
    form.code = ''
    form.name = ''
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
      await updatePost(props.editing.id, {
        name: form.name,
        sort_order: form.sortOrder,
        status: form.status,
      })
    } else {
      await createPost({
        code: form.code,
        name: form.name,
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
    :title="isEdit ? '编辑岗位' : '新增岗位'"
    width="480px"
    append-to-body
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
      <el-form-item label="岗位编码" prop="code">
        <el-input v-model="form.code" :disabled="isEdit" placeholder="全局唯一编码" />
      </el-form-item>
      <el-form-item label="岗位名称" prop="name">
        <el-input v-model="form.name" placeholder="岗位名称" />
      </el-form-item>
      <el-form-item label="排序" prop="sortOrder">
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
