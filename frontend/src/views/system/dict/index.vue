<script setup lang="ts">
/**
 * 字典管理页：字典类型列表 + 联动字典数据抽屉。
 * 复用 useCrudTable（列表/分页/删除）+ TablePagination；新增/编辑拆为 DictTypeFormDialog，
 * 点「数据」打开 DictDataDialog 管理该类型下的字典数据。
 * v-hasPermi 仅控按钮可见性（UX 层），后端 RBAC 才是安全边界。
 */
import { onMounted, ref } from 'vue'
import { useCrudTable } from '@/composables/useCrudTable'
import TablePagination from '@/components/TablePagination.vue'
import DictTypeFormDialog from './components/DictTypeFormDialog.vue'
import DictDataDialog from './components/DictDataDialog.vue'
import { listDictTypes, deleteDictType, type DictTypeRead } from '@/api/dict'

interface DictTypeQuery {
  keyword?: string
}

const table = useCrudTable<DictTypeRead, DictTypeQuery>({
  fetchPage: async (params) => {
    const page = await listDictTypes(params)
    return { items: page.items, total: page.total }
  },
  removeItem: deleteDictType,
})

const formVisible = ref(false)
const editing = ref<DictTypeRead | null>(null)

const dataVisible = ref(false)
const activeType = ref<DictTypeRead | null>(null)

function openCreate(): void {
  editing.value = null
  formVisible.value = true
}

function openEdit(row: DictTypeRead): void {
  editing.value = row
  formVisible.value = true
}

function openData(row: DictTypeRead): void {
  activeType.value = row
  dataVisible.value = true
}

onMounted(() => {
  void table.refresh()
})
</script>

<template>
  <div class="dict-page">
    <!-- 搜索栏 -->
    <el-form inline class="search-bar" @submit.prevent>
      <el-form-item label="字典">
        <el-input
          v-model="table.query.keyword"
          placeholder="按名称/类型搜索"
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
      <el-button v-hasPermi="'system:dict:add'" type="primary" @click="openCreate">
        新增
      </el-button>
    </div>

    <!-- 列表 -->
    <el-table v-loading="table.loading.value" :data="table.rows.value" border>
      <el-table-column prop="name" label="字典名称" min-width="140" />
      <el-table-column prop="type" label="字典类型" min-width="160" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'">
            {{ row.status === 'active' ? '正常' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="内置" width="90">
        <template #default="{ row }">
          <el-tag v-if="row.is_builtin" type="warning">内置</el-tag>
          <span v-else>否</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button v-hasPermi="'system:dict:query'" link type="primary" @click="openData(row)">
            数据
          </el-button>
          <el-button v-hasPermi="'system:dict:edit'" link type="primary" @click="openEdit(row)">
            编辑
          </el-button>
          <el-button
            v-hasPermi="'system:dict:remove'"
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

    <DictTypeFormDialog
      v-model:visible="formVisible"
      :editing="editing"
      @saved="table.refresh()"
    />
    <DictDataDialog v-model:visible="dataVisible" :dict-type="activeType" />
  </div>
</template>

<style scoped>
.dict-page {
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
