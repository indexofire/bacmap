<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from './components/AppShell.vue'

const route = useRoute()
// 登录页是裸页面：不渲染导航外壳（外壳会请求统计接口，未登录时触发 401 循环）。
const bare = computed(() => route.meta.bare === true)
</script>

<template>
  <RouterView v-if="bare" />
  <AppShell v-else />
</template>
