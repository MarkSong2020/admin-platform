<script setup lang="ts">
/**
 * 通知公告新增 / 编辑对话框。
 * title 必填，notice_type 下拉必选，content 用 textarea 纯文本输入。
 * 安全：content 首版不引富文本编辑器、列表/详情不 v-html 渲染（spec §10 风险12，防 XSS）。
 */
import { computed, reactive, ref, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import { createNotice, updateNotice, type NoticeRead, type NoticeType } from '@/api/notice'

const props = defineProps<{
  /** 被编辑的公告；null = 新增模式。 */
  editing: NoticeRead | null
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
  title: string
  noticeType: NoticeType
  content: string
  status: 'active' | 'disabled'
  remark: string
}

const form = reactive<FormModel>({
  title: '',
  noticeType: 'notification',
  content: '',
  status: 'active',
  remark: '',
})

const rules = computed<FormRules<FormModel>>(() => ({
  title: [{ required: true, message: '请输入公告标题', trigger: 'blur' }],
  noticeType: [{ required: true, message: '请选择公告类型', trigger: 'change' }],
}))

// 打开时按模式回填表单
watch(visible, (open) => {
  if (!open) return
  formRef.value?.clearValidate()
  const editing = props.editing
  if (editing) {
    form.title = editing.title
    form.noticeType = editing.notice_type === 'announcement' ? 'announcement' : 'notification'
    form.content = editing.content
    form.status = editing.status === 'disabled' ? 'disabled' : 'active'
    form.remark = editing.remark ?? ''
  } else {
    form.title = ''
    form.noticeType = 'notification'
    form.content = ''
    form.status = 'active'
    form.remark = ''
  }
})

async function submit(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    if (props.editing) {
      await updateNotice(props.editing.id, {
        title: form.title,
        notice_type: form.noticeType,
        content: form.content,
        status: form.status,
        remark: form.remark,
      })
    } else {
      await createNotice({
        title: form.title,
        notice_type: form.noticeType,
        content: form.content,
        status: form.status,
        remark: form.remark,
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
    :title="isEdit ? '编辑公告' : '新增公告'"
    width="560px"
    append-to-body
    :close-on-click-modal="false"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
      <el-form-item label="公告标题" prop="title">
        <el-input v-model="form.title" placeholder="公告标题" />
      </el-form-item>
      <el-form-item label="公告类型" prop="noticeType">
        <el-select v-model="form.noticeType" placeholder="请选择" style="width: 100%">
          <el-option label="通知" value="notification" />
          <el-option label="公告" value="announcement" />
        </el-select>
      </el-form-item>
      <el-form-item label="公告内容" prop="content">
        <!-- 纯文本 textarea：首版不引富文本编辑器、不渲染 raw HTML（防 XSS） -->
        <el-input
          v-model="form.content"
          type="textarea"
          :rows="6"
          placeholder="公告内容（纯文本）"
        />
      </el-form-item>
      <el-form-item label="状态" prop="status">
        <el-radio-group v-model="form.status">
          <el-radio value="active">正常</el-radio>
          <el-radio value="disabled">停用</el-radio>
        </el-radio-group>
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
