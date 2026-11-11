<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import { appUrl } from '../lib/format'
import { useTheme } from '../composables/useTheme'

/**
 * 旧版 Jinja 工具页的控制台内嵌载体（v1.10.20）。
 *
 * 研究工作台的表单型工具（系统发育 / Logistic / 打包 / 完整工作台）仍是
 * 服务端渲染页（base.html 无 JS，表单 POST + 303 重定向闭环）。此视图把它们
 * 装进控制台外壳：保留侧边栏与主题，用沙箱 iframe 承载（allow-forms /
 * allow-downloads；页面零脚本故无需 allow-scripts）。route.meta 声明标题与
 * 旧路径；:param 占位符用路由参数插值。
 */
const route = useRoute()
const { resolved: resolvedTheme } = useTheme()

const title = computed(() => (route.meta.title as string) ?? '')
const hint = computed(() => (route.meta.hint as string) ?? '')

const frameSrc = computed(() => {
  let path = (route.meta.legacyPath as string) ?? ''
  for (const [key, value] of Object.entries(route.params)) {
    path = path.replaceAll(`:${key}`, Array.isArray(value) ? value[0] : value)
  }
  return appUrl(path)
})
</script>

<template>
  <div class="page">
    <header class="pagehead">
      <div>
        <p class="eyebrow"><Icon name="chart" :size="12" /> 研究工具</p>
        <h1 class="pagehead__title">{{ title }}</h1>
        <p v-if="hint" class="pagehead__sub">{{ hint }}</p>
      </div>
      <div class="pagehead__actions">
        <a class="btn btn--ghost btn--sm" :href="frameSrc" target="_blank" rel="noopener">
          <Icon name="external-link" :size="13" />
          独立窗口
        </a>
      </div>
    </header>
    <div class="embed-card">
      <iframe
        :key="resolvedTheme"
        class="embed-frame"
        :src="frameSrc"
        :title="title"
        sandbox="allow-scripts allow-forms allow-same-origin allow-downloads"
      />
    </div>
  </div>
</template>

<style scoped>
.embed-card {
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--r-card, 10px);
  background: var(--surface);
}

.embed-frame {
  display: block;
  width: 100%;
  height: max(720px, calc(100vh - 210px));
  border: 0;
  background: var(--bg);
}
</style>
