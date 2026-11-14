<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import { api } from '../api'
import type { AgentEmbedLink } from '../types'

/**
 * 智能体对话嵌入（v1.10.24）：config.toml 的 [[web.agent_embed]] 配置
 * DSH / Hermes Dashboard / opencode serve 等本机智能体 web UI，控制台
 * 单窗口完成"对话 + 结果查看"。路由 /agent/:idx 对应 capabilities 的
 * agent_embeds 顺序；跨源 iframe 的 frame-src 白名单由服务端 CSP 放行。
 */
const route = useRoute()
const idx = computed(() => Number(route.params.idx ?? 0))

const embeds = ref<AgentEmbedLink[]>([])

onMounted(async () => {
  try {
    const caps = await api.capabilities()
    const list = caps.agent_embeds
    embeds.value = Array.isArray(list) ? list : []
  } catch {
    /* capabilities 失败 → 显示配置提示 */
  }
})

const embed = computed(() => embeds.value[idx.value])
const title = computed(() => embed.value?.name ?? '智能体对话')
</script>

<template>
  <div class="page">
    <header class="pagehead">
      <div>
        <p class="eyebrow"><Icon name="terminal" :size="12" /> 智能体对话</p>
        <h1 class="pagehead__title">{{ title }}</h1>
        <p class="pagehead__sub">本机智能体进程 · 回环嵌入（ADR-16：数据不出本地网络）</p>
      </div>
      <div class="pagehead__actions">
        <a v-if="embed" class="btn btn--ghost btn--sm" :href="embed.url" target="_blank" rel="noopener">
          <Icon name="external-link" :size="13" />
          独立窗口
        </a>
      </div>
    </header>
    <div class="embed-card">
      <iframe v-if="embed" class="embed-frame" :src="embed.url" :title="title" />
      <p v-else class="muted" style="padding: 24px">
        未配置智能体嵌入：在 config.toml 添加 [[web.agent_embed]] 后重启 bacmap web。
      </p>
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
  /* 低矮容器（DSH 侧栏 iframe 等）下 100vh 会塌缩——用固定地板高度兜底 */
  height: max(720px, calc(100vh - 210px));
  border: 0;
  background: #fff;
}
</style>
