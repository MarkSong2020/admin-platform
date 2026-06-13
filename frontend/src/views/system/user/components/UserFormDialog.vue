<script setup lang="ts">
/**
 * 用户新增 / 编辑对话框。
 * 新增：username 必填、password 必填；编辑：username 禁改、password 选填（填则改密）。
 * dept_id 暂用数字输入（dept 树选择器待 dept 页落地，TODO）。
 */
import { computed, reactive, ref, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import { createUser, updateUser, type UserRead } from '@/api/users'

const props = defineProps<{
  /** 被编辑的用户；null = 新增模式。 */
  editing: UserRead | null
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
  username: string
  password: string
  nickname: string
  deptId: number | null
  status: 'active' | 'disabled'
}

const form = reactive<FormModel>({
  username: '',
  password: '',
  nickname: '',
  deptId: null,
  status: 'active',
})

const rules = computed<FormRules<FormModel>>(() => ({
  username: [{ required: !isEdit.value, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: !isEdit.value, message: '请输入密码', trigger: 'blur' }],
}))

// 打开时按模式回填表单
watch(visible, (open) => {
  if (!open) return
  formRef.value?.clearValidate()
  const editing = props.editing
  if (editing) {
    form.username = editing.username
    form.password = ''
    form.nickname = editing.nickname
    form.deptId = editing.dept_id
    form.status = editing.status === 'disabled' ? 'disabled' : 'active'
  } else {
    form.username = ''
    form.password = ''
    form.nickname = ''
    form.deptId = null
    form.status = 'active'
  }
})

async function submit(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    if (props.editing) {
      const payload: Parameters<typeof updateUser>[1] = {
        nickname: form.nickname,
        dept_id: form.deptId,
        status: form.status,
      }
      if (form.password) payload.password = form.password
      await updateUser(props.editing.id, payload)
    } else {
      await createUser({
        username: form.username,
        password: form.password,
        nickname: form.nickname,
        dept_id: form.deptId,
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
    :title="isEdit ? '编辑用户' : '新增用户'"
    width="480px"
    append-to-body
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
      <el-form-item label="用户名" prop="username">
        <el-input v-model="form.username" :disabled="isEdit" placeholder="登录用户名" />
      </el-form-item>
      <el-form-item label="密码" prop="password">
        <el-input
          v-model="form.password"
          type="password"
          show-password
          :placeholder="isEdit ? '留空则不修改' : '登录密码'"
        />
      </el-form-item>
      <el-form-item label="昵称" prop="nickname">
        <el-input v-model="form.nickname" placeholder="显示昵称" />
      </el-form-item>
      <el-form-item label="部门" prop="deptId">
        <!-- TODO: dept 页落地后替换为部门树选择器 -->
        <el-input-number v-model="form.deptId" :min="1" controls-position="right" />
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
