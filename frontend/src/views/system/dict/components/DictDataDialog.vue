<script setup lang="ts">
/**
 * 字典数据管理抽屉：点字典类型「数据」按钮打开，管理该 dict_type_id 下的数据 CRUD。
 * 列表用 useCrudTable（按 dict_type_id 过滤）+ TablePagination；新增/编辑走 DictDataFormDialog。
 * v-hasPermi 控按钮可见（UX 层），后端 RBAC 才是安全边界（与类型共用 system:dict:* 权限码）。
 */
import { ref, watch } from 'vue'
import { useCrudTable } from '@/composables/useCrudTable'
import TablePagination from '@/components/TablePagination.vue'
import DictDataFormDialog from './DictDataFormDialog.vue'
import {
  listDictData,
  deleteDictData,
  type DictDataRead,
  type DictTypeRead,
} from '@/api/dict'

const props = defineProps<{
  /** 当前操作的字典类型；null = 未选中（抽屉不应打开）。 */
  dictType: DictTypeRead | null
}>()

const visible = defineModel<boolean>('visible', { required: true })

// 空查询：dict_type_id 在 fetchPage 内从 props 取，避免类型为空时构造非法请求。
type DataQuery = Record<string, never>

const table = useCrudTable<DictDataRead, DataQuery>({
  fetchPage: async (params) => {
    if (props.dictType === null) return { items: [], total: 0 }
    const page = await listDictData({
      page: params.page,
      size: params.size,
      dict_type_id: props.dictType.id,
    })
    return { items: page.items, total: page.total }
  },
  removeItem: deleteDictData,
})

const formVisible = ref(false)
const editing = ref<DictDataRead | null>(null)

function openCreate(): void {
  editing.value = null
  formVisible.value = true
}

function openEdit(row: DictDataRead): void {
  editing.value = row
  formVisible.value = true
}

// 抽屉打开时（且选中了类型）加载该类型的数据
watch(visible, (open) => {
  if (open && props.dictType !== null) {
    table.page.value = 1
    void table.refresh()
  }
})
</script>

<template>
  <el-drawer
    v-model="visible"
    :title="dictType ? `字典数据 - ${dictType.name}` : '字典数据'"
    size="720px"
    append-to-body
  >
    <div class="toolbar">
      <el-button v-hasPermi="'system:dict:add'" type="primary" @click="openCreate">
        新增
      </el-button>
    </div>

    <el-table v-loading="table.loading.value" :data="table.rows.value" border>
      <el-table-column prop="label" label="字典标签" min-width="120" />
      <el-table-column prop="value" label="字典键值" min-width="120" />
      <el-table-column prop="sort_order" label="排序" width="80" />
      <el-table-column label="默认" width="80">
        <template #default="{ row }">
          <el-tag v-if="row.is_default" type="success">是</el-tag>
          <span v-else>否</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'">
            {{ row.status === 'active' ? '正常' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
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

    <TablePagination
      v-model:page="table.page.value"
      v-model:size="table.size.value"
      :total="table.total.value"
      class="pagination"
      @change="table.refresh()"
    />

    <DictDataFormDialog
      v-if="dictType"
      v-model:visible="formVisible"
      :dict-type-id="dictType.id"
      :editing="editing"
      @saved="table.refresh()"
    />
  </el-drawer>
</template>

<style scoped>
.toolbar {
  margin-bottom: 12px;
}
.pagination {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
