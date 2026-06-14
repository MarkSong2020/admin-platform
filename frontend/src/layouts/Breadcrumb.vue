<script setup lang="ts">
/** 面包屑：基于 route.matched 的 meta.title 逐级展示（无 title 的记录跳过）。 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const crumbs = computed(() =>
  route.matched
    .filter((record) => typeof record.meta.title === 'string' && record.meta.title !== '')
    .map((record) => ({ path: record.path, title: record.meta.title as string })),
)
</script>

<template>
  <el-breadcrumb separator="/">
    <el-breadcrumb-item v-for="crumb in crumbs" :key="crumb.path">
      {{ crumb.title }}
    </el-breadcrumb-item>
  </el-breadcrumb>
</template>
