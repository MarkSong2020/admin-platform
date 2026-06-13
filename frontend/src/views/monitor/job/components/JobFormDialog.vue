<script setup lang="ts">
/**
 * 定时任务新增 / 编辑对话框。
 * handler_key 从 listHandlers 白名单加载下拉选项（管理员只能选预注册 handler，不可填任意串）。
 * params 走 JSON textarea：可选，提交前 JSON.parse 校验，非法给表单错误（写侧字段名 params）。
 */
import { computed, reactive, ref, watch } from 'vue'
import type { FormInstance, FormItemRule, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import {
  createJob,
  updateJob,
  listHandlers,
  type HandlerInfo,
  type ScheduledTaskRead,
} from '@/api/job'

const props = defineProps<{
  /** 被编辑的任务；null = 新增模式。 */
  editing: ScheduledTaskRead | null
}>()

const visible = defineModel<boolean>('visible', { required: true })

const emit = defineEmits<{
  /** 提交成功，父组件据此刷新列表。 */
  (e: 'saved'): void
}>()

const isEdit = computed(() => props.editing !== null)
const formRef = ref<FormInstance>()
const submitting = ref(false)
const handlers = ref<HandlerInfo[]>([])
const handlersLoading = ref(false)

interface FormModel {
  name: string
  handlerKey: string
  cronExpression: string
  cronTimezone: string
  paramsText: string
  status: 'enabled' | 'disabled'
  allowConcurrent: boolean
  misfireGraceSeconds: number
  timeoutSeconds: number | null
  remark: string
}

const form = reactive<FormModel>({
  name: '',
  handlerKey: '',
  cronExpression: '',
  cronTimezone: 'Asia/Shanghai',
  paramsText: '',
  status: 'disabled',
  allowConcurrent: false,
  misfireGraceSeconds: 300,
  timeoutSeconds: null,
  remark: '',
})

/** params JSON 校验：留空放过；非空必须是合法 JSON 对象。 */
const paramsValidator: FormItemRule['validator'] = (_rule, _value, callback) => {
  const text = form.paramsText.trim()
  if (text === '') {
    callback()
    return
  }
  try {
    const parsed: unknown = JSON.parse(text)
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      callback(new Error('params 必须是 JSON 对象'))
      return
    }
    callback()
  } catch {
    callback(new Error('params 不是合法 JSON'))
  }
}

const rules = computed<FormRules<FormModel>>(() => ({
  name: [{ required: true, message: '请输入任务名称', trigger: 'blur' }],
  handlerKey: [{ required: true, message: '请选择处理器', trigger: 'change' }],
  cronExpression: [{ required: true, message: '请输入 cron 表达式', trigger: 'blur' }],
  paramsText: [{ validator: paramsValidator, trigger: 'blur' }],
}))

async function loadHandlers(): Promise<void> {
  handlersLoading.value = true
  try {
    handlers.value = await listHandlers()
  } catch (err) {
    ElMessage.error((err as { message?: string }).message ?? '加载处理器失败')
  } finally {
    handlersLoading.value = false
  }
}

// 打开时加载 handler 白名单并按模式回填表单。
// immediate：对话框首次以 visible=true 打开（如测试直接传 visible: true）时也能触发。
watch(
  visible,
  (open) => {
  if (!open) return
  formRef.value?.clearValidate()
  void loadHandlers()
  const editing = props.editing
  if (editing) {
    form.name = editing.name
    form.handlerKey = editing.handler_key
    form.cronExpression = editing.cron_expression
    form.cronTimezone = editing.cron_timezone
    form.paramsText =
      editing.params_json && Object.keys(editing.params_json).length > 0
        ? JSON.stringify(editing.params_json, null, 2)
        : ''
    form.status = editing.status
    form.allowConcurrent = editing.allow_concurrent
    form.misfireGraceSeconds = editing.misfire_grace_seconds
    form.timeoutSeconds = editing.timeout_seconds
    form.remark = editing.remark ?? ''
  } else {
    form.name = ''
    form.handlerKey = ''
    form.cronExpression = ''
    form.cronTimezone = 'Asia/Shanghai'
    form.paramsText = ''
    form.status = 'disabled'
    form.allowConcurrent = false
    form.misfireGraceSeconds = 300
    form.timeoutSeconds = null
    form.remark = ''
  }
  },
  { immediate: true },
)

/** params 文本解析结果：ok=true 携带对象（留空为 undefined），ok=false 携带错误信息。 */
type ParamsParse =
  | { ok: true; value: Record<string, unknown> | undefined }
  | { ok: false; message: string }

/** params 文本 → 对象。留空放过；非空必须是合法 JSON 对象（与 paramsValidator 同口径）。 */
function parseParams(): ParamsParse {
  const text = form.paramsText.trim()
  if (text === '') return { ok: true, value: undefined }
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    return { ok: false, message: 'params 不是合法 JSON' }
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return { ok: false, message: 'params 必须是 JSON 对象' }
  }
  return { ok: true, value: parsed as Record<string, unknown> }
}

async function submit(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  // 兜底：即便 async-validator 因 trigger/时序未拦住，提交前再判一次 params。
  const parsed = parseParams()
  if (!parsed.ok) {
    ElMessage.error(parsed.message)
    return
  }
  submitting.value = true
  try {
    const params = parsed.value
    if (props.editing) {
      await updateJob(props.editing.id, {
        name: form.name,
        handler_key: form.handlerKey,
        cron_expression: form.cronExpression,
        cron_timezone: form.cronTimezone,
        params: params ?? null,
        status: form.status,
        allow_concurrent: form.allowConcurrent,
        misfire_grace_seconds: form.misfireGraceSeconds,
        timeout_seconds: form.timeoutSeconds,
        remark: form.remark,
      })
    } else {
      await createJob({
        name: form.name,
        handler_key: form.handlerKey,
        cron_expression: form.cronExpression,
        cron_timezone: form.cronTimezone,
        ...(params ? { params } : {}),
        status: form.status,
        allow_concurrent: form.allowConcurrent,
        misfire_grace_seconds: form.misfireGraceSeconds,
        timeout_seconds: form.timeoutSeconds,
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
    :title="isEdit ? '编辑任务' : '新增任务'"
    width="560px"
    append-to-body
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="110px">
      <el-form-item label="任务名称" prop="name">
        <el-input v-model="form.name" placeholder="任务名称" />
      </el-form-item>
      <el-form-item label="处理器" prop="handlerKey">
        <el-select
          v-model="form.handlerKey"
          v-loading="handlersLoading"
          placeholder="从白名单选择处理器"
          class="full-width"
        >
          <el-option
            v-for="h in handlers"
            :key="h.key"
            :label="`${h.display_name}（${h.key}）`"
            :value="h.key"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="cron 表达式" prop="cronExpression">
        <el-input v-model="form.cronExpression" placeholder="如 0 0 * * *" />
      </el-form-item>
      <el-form-item label="时区" prop="cronTimezone">
        <el-input v-model="form.cronTimezone" placeholder="Asia/Shanghai" />
      </el-form-item>
      <el-form-item label="参数(JSON)" prop="paramsText">
        <el-input
          v-model="form.paramsText"
          type="textarea"
          :rows="3"
          placeholder='可选，JSON 对象，如 {"key": "value"}'
        />
      </el-form-item>
      <el-form-item label="状态" prop="status">
        <el-radio-group v-model="form.status">
          <el-radio value="enabled">启用</el-radio>
          <el-radio value="disabled">停用</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="允许并发" prop="allowConcurrent">
        <el-switch v-model="form.allowConcurrent" />
      </el-form-item>
      <el-form-item label="错过容忍(秒)" prop="misfireGraceSeconds">
        <el-input-number v-model="form.misfireGraceSeconds" :min="0" controls-position="right" />
      </el-form-item>
      <el-form-item label="超时(秒)" prop="timeoutSeconds">
        <el-input-number
          v-model="form.timeoutSeconds"
          :min="0"
          controls-position="right"
          placeholder="可选"
        />
      </el-form-item>
      <el-form-item label="备注" prop="remark">
        <el-input v-model="form.remark" type="textarea" :rows="2" placeholder="可选" />
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
