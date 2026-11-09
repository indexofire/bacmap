<script setup lang="ts">
import { RouterLink } from 'vue-router'
import EmptyState from '../components/EmptyState.vue'
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <h1 class="pagehead__title">页面不存在</h1>
        <p class="pagehead__sub">这个地址没有对应的控制台页面。</p>
      </div>
    </div>
    <section class="card">
      <EmptyState
        title="404"
        hint="检查链接，或从仪表盘重新开始。"
        icon="alert-circle"
      >
        <RouterLink to="/" class="btn btn--primary btn--sm">返回仪表盘</RouterLink>
      </EmptyState>
    </section>
  </div>
</template>
