<script setup lang="ts">
/**
 * 字典类型新增 / 编辑对话框。
 * 新增：name + type 必填；编辑：type 禁改（key 改名破坏前端契约）。
 * is_builtin 仅在编辑模式提供切换（解保护后才能删；内置类型禁删 → 409）。
 */
import { computed, reactive, ref, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import { createDictType, updateDictType, type DictTypeRead } from '@/api/dict'

const props = defineProps<{
  /** 被编辑的字典类型；null = 新增模式。 */
  editing: DictTypeRead | null
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
  name: string
  type: string
  isBuiltin: boolean
  remark: string
  status: 'active' | 'disabled'
}

const form = reactive<FormModel>({
  name: '',
  type: '',
  isBuiltin: false,
  remark: '',
  status: 'active',
})

const rules = computed<FormRules<FormModel>>(() => ({
  name: [{ required: true, message: '请输入字典名称', trigger: 'blur' }],
  type: [{ required: !isEdit.value, message: '请输入字典类型', trigger: 'blur' }],
}))

// 打开时按模式回填表单
watch(visible, (open) => {
  if (!open) return
  formRef.value?.clearValidate()
  const editing = props.editing
  if (editing) {
    form.name = editing.name
    form.type = editing.type
    form.isBuiltin = editing.is_builtin
    form.remark = editing.remark ?? ''
    form.status = editing.status === 'disabled' ? 'disabled' : 'active'
  } else {
    form.name = ''
    form.type = ''
    form.isBuiltin = false
    form.remark = ''
    form.status = 'active'
  }
})

async function submit(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    if (props.editing) {
      await updateDictType(props.editing.id, {
        name: form.name,
        is_builtin: form.isBuiltin,
        remark: form.remark,
        status: form.status,
      })
    } else {
      await createDictType({
        name: form.name,
        type: form.type,
        is_builtin: form.isBuiltin,
        remark: form.remark,
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
    :title="isEdit ? '编辑字典类型' : '新增字典类型'"
    width="480px"
    append-to-body
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
      <el-form-item label="字典名称" prop="name">
        <el-input v-model="form.name" placeholder="字典名称" />
      </el-form-item>
      <el-form-item label="字典类型" prop="type">
        <el-input v-model="form.type" :disabled="isEdit" placeholder="全局唯一类型 key" />
      </el-form-item>
      <el-form-item label="系统内置" prop="isBuiltin">
        <el-switch v-model="form.isBuiltin" />
        <span class="hint">内置类型禁删，关闭后方可删除</span>
      </el-form-item>
      <el-form-item label="状态" prop="status">
        <el-radio-group v-model="form.status">
          <el-radio value="active">正常</el-radio>
          <el-radio value="disabled">停用</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="备注" prop="remark">
        <el-input v-model="form.remark" type="textarea" :rows="2" placeholder="备注" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">确定</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.hint {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
