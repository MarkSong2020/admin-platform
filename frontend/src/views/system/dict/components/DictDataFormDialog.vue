<script setup lang="ts">
/**
 * 字典数据新增 / 编辑对话框（嵌于 DictDataDialog 内）。
 * 新增固定挂在父类型 dict_type_id 下；编辑走 PATCH（不传 dict_type_id，不跨类型迁移）。
 * 单默认由后端 partial unique 保证，前端正常提交 is_default 即可。
 */
import { computed, reactive, ref, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import { createDictData, updateDictData, type DictDataRead } from '@/api/dict'

const props = defineProps<{
  /** 所属字典类型 id（新增时挂载）。 */
  dictTypeId: number
  /** 被编辑的字典数据；null = 新增模式。 */
  editing: DictDataRead | null
}>()

const visible = defineModel<boolean>('visible', { required: true })

const emit = defineEmits<{
  /** 提交成功，父组件据此刷新数据列表。 */
  (e: 'saved'): void
}>()

const isEdit = computed(() => props.editing !== null)
const formRef = ref<FormInstance>()
const submitting = ref(false)

interface FormModel {
  label: string
  value: string
  sortOrder: number
  cssClass: string
  isDefault: boolean
  remark: string
  status: 'active' | 'disabled'
}

const form = reactive<FormModel>({
  label: '',
  value: '',
  sortOrder: 0,
  cssClass: '',
  isDefault: false,
  remark: '',
  status: 'active',
})

const rules = computed<FormRules<FormModel>>(() => ({
  label: [{ required: true, message: '请输入字典标签', trigger: 'blur' }],
  value: [{ required: true, message: '请输入字典键值', trigger: 'blur' }],
}))

// 打开时按模式回填表单
watch(visible, (open) => {
  if (!open) return
  formRef.value?.clearValidate()
  const editing = props.editing
  if (editing) {
    form.label = editing.label
    form.value = editing.value
    form.sortOrder = editing.sort_order
    form.cssClass = editing.css_class ?? ''
    form.isDefault = editing.is_default
    form.remark = editing.remark ?? ''
    form.status = editing.status === 'disabled' ? 'disabled' : 'active'
  } else {
    form.label = ''
    form.value = ''
    form.sortOrder = 0
    form.cssClass = ''
    form.isDefault = false
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
      await updateDictData(props.editing.id, {
        label: form.label,
        value: form.value,
        sort_order: form.sortOrder,
        css_class: form.cssClass,
        is_default: form.isDefault,
        remark: form.remark,
        status: form.status,
      })
    } else {
      await createDictData({
        dict_type_id: props.dictTypeId,
        label: form.label,
        value: form.value,
        sort_order: form.sortOrder,
        css_class: form.cssClass,
        is_default: form.isDefault,
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
    :title="isEdit ? '编辑字典数据' : '新增字典数据'"
    width="480px"
    append-to-body
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
      <el-form-item label="字典标签" prop="label">
        <el-input v-model="form.label" placeholder="字典标签" />
      </el-form-item>
      <el-form-item label="字典键值" prop="value">
        <el-input v-model="form.value" placeholder="字典键值" />
      </el-form-item>
      <el-form-item label="排序" prop="sortOrder">
        <el-input-number v-model="form.sortOrder" :min="0" controls-position="right" />
      </el-form-item>
      <el-form-item label="CSS Class" prop="cssClass">
        <el-input v-model="form.cssClass" placeholder="前端样式 class（可空）" />
      </el-form-item>
      <el-form-item label="默认值" prop="isDefault">
        <el-switch v-model="form.isDefault" />
        <span class="hint">同一类型仅一条默认</span>
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
