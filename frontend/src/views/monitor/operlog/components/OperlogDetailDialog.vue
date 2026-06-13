<script setup lang="ts">
/**
 * 操作日志详情对话框。打开时调 getOperlog 拉 AuditEventDetail，
 * el-descriptions 平铺全字段；payload 用 <pre> + JSON.stringify 纯文本展示，
 * 禁 v-html（payload/user_agent 可能含恶意串，纯文本渲染杜绝 XSS）。
 */
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getOperlog, type AuditEventDetail } from '@/api/operlog'
import { normalizeApiError } from '@/api/transport'

const visible = defineModel<boolean>('visible', { required: true })

const props = defineProps<{
  /** 待查看的审计事件主键；null 时不加载。 */
  eventPk: number | null
}>()

const loading = ref(false)
const detail = ref<AuditEventDetail | null>(null)

/** payload 序列化为缩进 JSON 文本（空对象显示占位）。 */
function payloadText(payload: AuditEventDetail['payload']): string {
  if (!payload || Object.keys(payload).length === 0) return '（无）'
  return JSON.stringify(payload, null, 2)
}

async function load(eventPk: number): Promise<void> {
  loading.value = true
  detail.value = null
  try {
    detail.value = await getOperlog(eventPk)
  } catch (err) {
    const normalized = normalizeApiError(err)
    ElMessage.error('message' in normalized ? normalized.message : '加载详情失败')
    visible.value = false
  } finally {
    loading.value = false
  }
}

watch(
  () => [visible.value, props.eventPk] as const,
  ([open, pk]) => {
    if (open && pk !== null) void load(pk)
  },
  { immediate: true },
)
</script>

<template>
  <el-dialog v-model="visible" title="操作日志详情" width="720px">
    <el-descriptions v-loading="loading" :column="2" border>
      <el-descriptions-item label="事件类型">{{ detail?.event_type }}</el-descriptions-item>
      <el-descriptions-item label="标题">{{ detail?.title }}</el-descriptions-item>
      <el-descriptions-item label="动作">{{ detail?.action }}</el-descriptions-item>
      <el-descriptions-item label="风险等级">{{ detail?.risk_level }}</el-descriptions-item>
      <el-descriptions-item label="操作者">{{ detail?.actor_username ?? '-' }}</el-descriptions-item>
      <el-descriptions-item label="操作者ID">{{ detail?.actor_user_id ?? '-' }}</el-descriptions-item>
      <el-descriptions-item label="超级管理员">
        {{ detail?.actor_is_super_admin ? '是' : '否' }}
      </el-descriptions-item>
      <el-descriptions-item label="结果">
        <el-tag :type="detail?.result_status === 'success' ? 'success' : 'danger'">
          {{ detail?.result_status }}
        </el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="HTTP 状态">{{ detail?.result_http_status ?? '-' }}</el-descriptions-item>
      <el-descriptions-item label="错误码">{{ detail?.result_error_code ?? '-' }}</el-descriptions-item>
      <el-descriptions-item label="目标类型">{{ detail?.target_type ?? '-' }}</el-descriptions-item>
      <el-descriptions-item label="目标">{{ detail?.target_display ?? detail?.target_id ?? '-' }}</el-descriptions-item>
      <el-descriptions-item label="方法">{{ detail?.method ?? '-' }}</el-descriptions-item>
      <el-descriptions-item label="路径">{{ detail?.path ?? '-' }}</el-descriptions-item>
      <el-descriptions-item label="IP">{{ detail?.ip ?? '-' }}</el-descriptions-item>
      <el-descriptions-item label="耗时(ms)">{{ detail?.duration_ms ?? '-' }}</el-descriptions-item>
      <el-descriptions-item label="发生时间">{{ detail?.occurred_at }}</el-descriptions-item>
      <el-descriptions-item label="脱敏">{{ detail?.redaction_applied ? '是' : '否' }}</el-descriptions-item>
      <el-descriptions-item label="Request ID">{{ detail?.request_id ?? '-' }}</el-descriptions-item>
      <el-descriptions-item label="Trace ID">{{ detail?.trace_id ?? '-' }}</el-descriptions-item>
      <el-descriptions-item label="User-Agent" :span="2">{{ detail?.user_agent ?? '-' }}</el-descriptions-item>
      <el-descriptions-item label="Payload" :span="2">
        <pre class="payload">{{ detail ? payloadText(detail.payload) : '' }}</pre>
      </el-descriptions-item>
    </el-descriptions>
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.payload {
  margin: 0;
  max-height: 240px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 12px;
  font-family: var(--el-font-family-mono, monospace);
}
</style>
