<script setup lang="ts">
// 应用根：仅渲染路由出口（登录页 / Layout 壳由路由决定）。
import { RouterView } from 'vue-router'
</script>

<template>
  <RouterView />
</template>
