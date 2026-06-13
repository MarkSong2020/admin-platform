<script setup lang="ts">
/**
 * 参数配置页。复用 useCrudTable（列表/分页）+ TablePagination，
 * 新增/编辑拆为同目录 components/ConfigFormDialog。
 * 删除自实现：内置参数后端返 409，提示「内置参数不可删除」（不走 composable 的通用 409 文案）。
 * v-hasPermi 仅控按钮可见性（UX 层），后端 RBAC 才是安全边界。
 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useCrudTable } from '@/composables/useCrudTable'
import TablePagination from '@/components/TablePagination.vue'
import ConfigFormDialog from './components/ConfigFormDialog.vue'
import { listConfigs, deleteConfig, type ConfigRead } from '@/api/config'

interface ConfigQuery {
  keyword?: string
}

const table = useCrudTable<ConfigRead, ConfigQuery>({
  fetchPage: async (params) => {
    const page = await listConfigs(params)
    return { items: page.items, total: page.total }
  },
})

const formVisible = ref(false)
const editing = ref<ConfigRead | null>(null)

function openCreate(): void {
  editing.value = null
  formVisible.value = true
}

function openEdit(row: ConfigRead): void {
  editing.value = row
  formVisible.value = true
}

/** 删除：二次确认 → deleteConfig；内置参数 409 → 专用提示。 */
async function handleRemove(row: ConfigRead): Promise<void> {
  try {
    await ElMessageBox.confirm('确认删除该参数吗？', '提示', {
      type: 'warning',
      confirmButtonText: '确定',
      cancelButtonText: '取消',
    })
  } catch {
    return // 用户取消
  }
  try {
    await deleteConfig(row.id)
    ElMessage.success('删除成功')
    await table.refresh()
  } catch (err) {
    const apiError = err as { status?: number; message?: string }
    const message = apiError.status === 409 ? '内置参数不可删除' : (apiError.message ?? '删除失败')
    ElMessage.error(message)
  }
}

onMounted(() => {
  void table.refresh()
})
</script>

<template>
  <div class="config-page">
    <!-- 搜索栏 -->
    <el-form inline class="search-bar" @submit.prevent>
      <el-form-item label="参数">
        <el-input
          v-model="table.query.keyword"
          placeholder="按参数名/键名搜索"
          clearable
          @keyup.enter="table.search()"
        />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="table.search()">查询</el-button>
        <el-button @click="table.reset()">重置</el-button>
      </el-form-item>
    </el-form>

    <!-- 工具栏 -->
    <div class="toolbar">
      <el-button v-hasPermi="'system:config:add'" type="primary" @click="openCreate">
        新增
      </el-button>
    </div>

    <!-- 列表 -->
    <el-table v-loading="table.loading.value" :data="table.rows.value" border>
      <el-table-column prop="name" label="参数名称" min-width="140" />
      <el-table-column prop="config_key" label="参数键名" min-width="180" />
      <el-table-column prop="config_value" label="参数键值" min-width="160" show-overflow-tooltip />
      <el-table-column label="内置" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_builtin ? 'warning' : 'info'">
            {{ row.is_builtin ? '是' : '否' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button v-hasPermi="'system:config:edit'" link type="primary" @click="openEdit(row)">
            编辑
          </el-button>
          <el-button
            v-hasPermi="'system:config:remove'"
            link
            type="danger"
            @click="handleRemove(row)"
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

    <ConfigFormDialog v-model:visible="formVisible" :editing="editing" @saved="table.refresh()" />
  </div>
</template>

<style scoped>
.config-page {
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
