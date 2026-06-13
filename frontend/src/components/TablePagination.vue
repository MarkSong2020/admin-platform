<script setup lang="ts">
/**
 * el-pagination 薄包装：纯展示，props 入 / emit 出，不依赖 api/stores（depcruise components 层约束）。
 * page/size 双向绑定（v-model:page / v-model:size），翻页或改每页条数都 emit change。
 */
const page = defineModel<number>('page', { required: true })
const size = defineModel<number>('size', { required: true })

defineProps<{
  /** 记录总数。 */
  total: number
}>()

const emit = defineEmits<{
  /** 分页变化（翻页或改每页条数后），调用方据此重新拉数据。 */
  (e: 'change'): void
}>()

function handleCurrentChange(value: number): void {
  page.value = value
  emit('change')
}

function handleSizeChange(value: number): void {
  size.value = value
  page.value = 1 // 改每页条数回到第一页，避免越界空页
  emit('change')
}
</script>

<template>
  <el-pagination
    :current-page="page"
    :page-size="size"
    :total="total"
    :page-sizes="[10, 20, 50, 100]"
    layout="total, sizes, prev, pager, next"
    background
    @current-change="handleCurrentChange"
    @size-change="handleSizeChange"
  />
</template>
