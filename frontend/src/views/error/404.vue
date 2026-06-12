<script setup lang="ts">
// 404 页（公开，catchAll 兜底）。命名 404.vue（非 index.vue）以避开页面组件 glob 白名单。
</script>

<template>
  <div class="error-404">
    <h1>404</h1>
    <p>页面不存在或无权访问。</p>
  </div>
</template>

<style scoped>
.error-404 {
  padding: 24px;
  text-align: center;
}
</style>
