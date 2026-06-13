<script setup lang="ts">
/**
 * 文件管理页（对标 RuoYi sys_oss）。
 * 复用 useCrudTable（列表/分页/删除确认）+ TablePagination；
 * 上传走 el-upload 手动模式（:auto-upload=false 由 before-upload 接管），下载走 blob。
 * v-hasPermi 仅控按钮可见性（UX 层），后端 RBAC 才是安全边界。
 */
import { onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useCrudTable } from '@/composables/useCrudTable'
import TablePagination from '@/components/TablePagination.vue'
import {
  listFiles,
  uploadFile,
  downloadFile,
  deleteFile,
  type FileRead,
} from '@/api/file'
import { normalizeApiError } from '@/api/transport'

const table = useCrudTable<FileRead, Record<string, never>>({
  fetchPage: async (params) => {
    const page = await listFiles(params)
    return { items: page.items, total: page.total }
  },
  removeItem: deleteFile,
})

/** 字节转可读单位（KB/MB/GB），仅展示用。 */
function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(2)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(2)} KB`
  return `${bytes} B`
}

/**
 * el-upload :auto-upload=false 时由 before-upload 接管发送：调 uploadFile 走 transport，
 * 成功刷新列表。返回 false 阻止 el-upload 自身的 XHR（我们用自己的 transport 通道）。
 */
async function handleUpload(rawFile: File): Promise<boolean> {
  try {
    const created = await uploadFile(rawFile)
    ElMessage.success(`上传成功：${created.original_filename}`)
    await table.refresh()
  } catch (err) {
    ElMessage.error(normalizeApiError(err).message)
  }
  return false
}

async function handleDownload(row: FileRead): Promise<void> {
  try {
    await downloadFile(row.id, row.original_filename)
  } catch (err) {
    ElMessage.error(normalizeApiError(err).message)
  }
}

onMounted(() => {
  void table.refresh()
})
</script>

<template>
  <div class="file-page">
    <!-- 工具栏 -->
    <div class="toolbar">
      <el-upload
        v-hasPermi="'system:file:upload'"
        :auto-upload="false"
        :show-file-list="false"
        :before-upload="handleUpload"
      >
        <el-button type="primary">上传</el-button>
      </el-upload>
    </div>

    <!-- 列表 -->
    <el-table v-loading="table.loading.value" :data="table.rows.value" border>
      <el-table-column prop="original_filename" label="文件名" min-width="200" show-overflow-tooltip />
      <el-table-column prop="content_type" label="类型" min-width="160" show-overflow-tooltip />
      <el-table-column label="大小" width="120">
        <template #default="{ row }">
          {{ formatBytes(row.size_bytes) }}
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="上传时间" min-width="180" />
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button
            v-hasPermi="'system:file:download'"
            link
            type="primary"
            @click="handleDownload(row)"
          >
            下载
          </el-button>
          <el-button
            v-hasPermi="'system:file:remove'"
            link
            type="danger"
            @click="table.remove(row.id)"
          >
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <TablePagination
      v-model:page="table.page.value"
      v-model:size="table.size.value"
      :total="table.total.value"
      class="pagination"
      @change="table.refresh()"
    />
  </div>
</template>

<style scoped>
.file-page {
  padding: 16px;
}
.toolbar {
  margin-bottom: 12px;
}
.pagination {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
