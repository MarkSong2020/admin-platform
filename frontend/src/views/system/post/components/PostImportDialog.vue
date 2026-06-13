<script setup lang="ts">
/**
 * 岗位 Excel 导入对话框。
 * 选 xlsx → importPosts（始终 200 业务通道）→ 展示 summary：
 *  - errors 为空：imported=N 成功，提示并通知父组件刷新；
 *  - errors 非空：一步全有全无（imported=0 全未入库），以表格列出全部错误行（row/column/message）。
 * 仅传输级失败（并发 409 / 超大 413 / 非法 422）才落 ElMessage.error。
 */
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import { importPosts, type PostImportSummary, type PostImportRowError } from '@/api/posts'
import { normalizeApiError } from '@/api/transport'

const visible = defineModel<boolean>('visible', { required: true })

const emit = defineEmits<{
  /** 有岗位成功导入，父组件据此刷新列表。 */
  (e: 'imported'): void
}>()

const uploading = ref(false)
/** 上次导入结果；null = 尚未导入。 */
const summary = ref<PostImportSummary | null>(null)

/** el-upload :auto-upload=false 时由 before-upload 接管：走 transport multipart，阻止自身 XHR。 */
async function handleSelect(rawFile: File): Promise<boolean> {
  uploading.value = true
  summary.value = null
  try {
    const result = await importPosts(rawFile)
    summary.value = result
    const errors: PostImportRowError[] = result.errors ?? []
    if (errors.length === 0) {
      ElMessage.success(`导入成功，共 ${result.imported} 条`)
      emit('imported')
    } else {
      ElMessage.warning(`存在 ${errors.length} 处错误，已全部回退（未导入任何行）`)
    }
  } catch (err) {
    // 传输级失败（409/413/422）：归一展示，不当作业务结果。
    ElMessage.error(normalizeApiError(err).message)
  } finally {
    uploading.value = false
  }
  return false
}

function close(): void {
  visible.value = false
  summary.value = null
}
</script>

<template>
  <el-dialog
    v-model="visible"
    title="导入岗位"
    width="640px"
    append-to-body
    @closed="summary = null"
  >
    <el-upload
      :auto-upload="false"
      :show-file-list="false"
      :before-upload="handleSelect"
      accept=".xlsx"
      drag
    >
      <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
      <div class="el-upload__text">将 xlsx 文件拖到此处，或<em>点击选择</em></div>
      <template #tip>
        <div class="upload-tip">仅支持 .xlsx；导入为「全有全无」——任一行出错则整批不入库。</div>
      </template>
    </el-upload>

    <div v-if="uploading" class="status" v-loading="true">导入中…</div>

    <!-- 成功结果 -->
    <el-alert
      v-if="summary && (summary.errors ?? []).length === 0"
      class="result"
      type="success"
      :closable="false"
      :title="`导入成功，共 ${summary.imported} 条`"
    />

    <!-- 错误结果：全量错误行表格 -->
    <div v-if="summary && (summary.errors ?? []).length > 0" class="result">
      <el-alert
        type="error"
        :closable="false"
        :title="`存在 ${(summary.errors ?? []).length} 处错误，已全部回退（imported=0）`"
      />
      <el-table :data="summary.errors ?? []" border max-height="320" class="error-table">
        <el-table-column prop="row" label="行号" width="80" />
        <el-table-column label="列" width="140">
          <template #default="{ row }">{{ row.column ?? '—' }}</template>
        </el-table-column>
        <el-table-column prop="code" label="错误码" width="160" />
        <el-table-column prop="message" label="说明" min-width="200" show-overflow-tooltip />
      </el-table>
    </div>

    <template #footer>
      <el-button @click="close">关闭</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.status {
  margin-top: 12px;
  text-align: center;
  color: var(--el-text-color-secondary);
}
.result {
  margin-top: 16px;
}
.upload-tip {
  margin-top: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.error-table {
  margin-top: 12px;
}
</style>
