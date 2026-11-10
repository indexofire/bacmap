<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import Icon from './Icon.vue'
import ToastHost from './ToastHost.vue'
import { api } from '../api'
import { useTheme } from '../composables/useTheme'

const route = useRoute()
const router = useRouter()
const { resolved: resolvedTheme, toggle: toggleTheme } = useTheme()
const menuOpen = ref(false)
const version = ref('0.2.0')
const search = ref('')
const pendingApprovals = ref(0)
let pendingTimer: ReturnType<typeof setInterval> | undefined

const title = computed(() => (route.meta.title as string | undefined) ?? '控制台')

const groups = [
  {
    label: '工作台',
    items: [
      { to: '/', label: '仪表盘', icon: 'dashboard', exact: true },
      { to: '/tasks', label: '任务', icon: 'tasks' },
      { to: '/plans', label: '计划', icon: 'plans' },
      { to: '/research', label: '研究', icon: 'chart' },
    ],
  },
  {
    label: '证据链',
    items: [
      { to: '/samples', label: '样本', icon: 'records' },
      { to: '/runs', label: '运行记录', icon: 'runs' },
      { to: '/records', label: '数据记录', icon: 'file-text' },
      { to: '/gom', label: 'GOM', icon: 'server' },
    ],
  },
  {
    label: '系统',
    items: [
      { to: '/overview', label: '系统概览', icon: 'overview' },
      { to: '/search', label: '样本检索', icon: 'search' },
    ],
  },
]

watch(
  () => route.fullPath,
  () => {
    menuOpen.value = false
  },
)

onMounted(async () => {
  try {
    const cap = await api.capabilities()
    version.value = cap.bacmap_version
  } catch {
    // 版本号是装饰信息，失败不打断控制台。
  }
  void loadPending()
  pendingTimer = setInterval(() => void loadPending(), 60_000)
})

onBeforeUnmount(() => {
  if (pendingTimer) clearInterval(pendingTimer)
})

async function loadPending() {
  try {
    const stats = await api.stats()
    pendingApprovals.value = stats.tasks.by_state.awaiting_approval ?? 0
  } catch {
    // 统计接口不可用时保持上次计数，不打断导航。
  }
}

function submitSearch() {
  const q = search.value.trim()
  if (!q) return
  router.push({ path: '/search', query: { q } })
}
</script>

<template>
  <a class="skip-link" href="#main">跳到主要内容</a>
  <div class="shell">
    <aside class="sidebar" :class="{ 'is-open': menuOpen }" aria-label="主导航">
      <div class="sidebar__brand">
        <span class="brand-mark"><Icon name="activity" :size="16" /></span>
        <span class="brand-word">bacmap</span>
        <span class="brand-tag">console</span>
      </div>

      <nav class="sidebar__nav">
        <div v-for="group in groups" :key="group.label" class="nav-group">
          <div class="nav-group__label">{{ group.label }}</div>
          <RouterLink
            v-for="item in group.items"
            :key="item.to"
            :to="item.to"
            class="nav-link"
            :class="{ 'router-link-active': item.exact ? route.path === '/' : route.path.startsWith(item.to) }"
          >
            <Icon :name="item.icon" />
            <span>{{ item.label }}</span>
            <span
              v-if="item.to === '/tasks' && pendingApprovals"
              class="nav-link__count nav-link__count--alert"
              :title="`${pendingApprovals} 个任务等待审批`"
            >
              {{ pendingApprovals }}
            </span>
          </RouterLink>
        </div>
      </nav>

      <div class="sidebar__foot">
        <div class="locality">
          <Icon name="shield" />
          <span>数据不出本地网络 · ADR-16</span>
        </div>
        <div class="sidebar__version">bacmap v{{ version }}</div>
      </div>
    </aside>

    <div v-if="menuOpen" class="sidebar__scrim" @click="menuOpen = false" />

    <div class="main">
      <header class="topbar">
        <button
          class="icon-btn topbar__menu"
          type="button"
          aria-label="打开导航"
          @click="menuOpen = true"
        >
          <Icon name="menu" />
        </button>

        <nav class="crumbs" aria-label="面包屑">
          <RouterLink to="/" class="muted">控制台</RouterLink>
          <Icon name="chevron-right" :size="12" />
          <span class="crumbs__now">{{ title }}</span>
        </nav>

        <form class="topbar__search" role="search" @submit.prevent="submitSearch">
          <Icon name="search" />
          <input
            v-model="search"
            type="search"
            placeholder="搜索样本、ID…"
            aria-label="全局搜索"
          />
        </form>

        <RouterLink
          to="/search"
          class="icon-btn topbar__search-mobile"
          aria-label="搜索样本"
          title="搜索样本"
        >
          <Icon name="search" />
        </RouterLink>

        <button
          class="icon-btn topbar__theme"
          type="button"
          :aria-label="resolvedTheme === 'dark' ? '切换到浅色主题' : '切换到深色主题'"
          :title="resolvedTheme === 'dark' ? '切换到浅色主题' : '切换到深色主题'"
          :aria-pressed="resolvedTheme === 'light'"
          @click="toggleTheme"
        >
          <Icon :name="resolvedTheme === 'dark' ? 'sun' : 'moon'" />
        </button>
      </header>

      <main id="main" class="content" tabindex="-1">
        <RouterView />
      </main>
    </div>

    <ToastHost />
  </div>
</template>
