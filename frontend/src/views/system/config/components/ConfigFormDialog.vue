<script setup lang="ts">
/**
 * 参数新增 / 编辑对话框。
 * 新增：config_key 必填；编辑：config_key 禁改（创建后不可变）。name、config_value 必填，remark 可选。
 */
import { computed, reactive, ref, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import { createConfig, updateConfig, type ConfigRead } from '@/api/config'

const props = defineProps<{
  /** 被编辑的参数；null = 新增模式。 */
  editing: ConfigRead | null
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
  configKey: string
  configValue: string
  remark: string
}

const form = reactive<FormModel>({
  name: '',
  configKey: '',
  configValue: '',
  remark: '',
})

const rules = computed<FormRules<FormModel>>(() => ({
  name: [{ required: true, message: '请输入参数名称', trigger: 'blur' }],
  configKey: [{ required: !isEdit.value, message: '请输入参数键名', trigger: 'blur' }],
  configValue: [{ required: true, message: '请输入参数键值', trigger: 'blur' }],
}))

// 打开时按模式回填表单
watch(visible, (open) => {
  if (!open) return
  formRef.value?.clearValidate()
  const editing = props.editing
  if (editing) {
    form.name = editing.name
    form.configKey = editing.config_key
    form.configValue = editing.config_value
    form.remark = editing.remark ?? ''
  } else {
    form.name = ''
    form.configKey = ''
    form.configValue = ''
    form.remark = ''
  }
})

async function submit(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    if (props.editing) {
      await updateConfig(props.editing.id, {
        name: form.name,
        config_value: form.configValue,
        remark: form.remark,
      })
    } else {
      await createConfig({
        name: form.name,
        config_key: form.configKey,
        config_value: form.configValue,
        remark: form.remark,
        // 用户新建参数恒为非内置（内置参数仅 seed 注入，禁删保护）
        is_builtin: false,
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
    :title="isEdit ? '编辑参数' : '新增参数'"
    width="480px"
    append-to-body
    :close-on-click-modal="false"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
      <el-form-item label="参数名称" prop="name">
        <el-input v-model="form.name" placeholder="参数名称" />
      </el-form-item>
      <el-form-item label="参数键名" prop="configKey">
        <el-input v-model="form.configKey" :disabled="isEdit" placeholder="全局唯一键名" />
      </el-form-item>
      <el-form-item label="参数键值" prop="configValue">
        <el-input v-model="form.configValue" placeholder="参数键值" />
      </el-form-item>
      <el-form-item label="备注" prop="remark">
        <el-input v-model="form.remark" type="textarea" :rows="2" placeholder="备注（可选）" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">确定</el-button>
    </template>
  </el-dialog>
</template>
