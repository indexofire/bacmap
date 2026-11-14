<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import Icon from './Icon.vue'
import ToastHost from './ToastHost.vue'
import { api } from '../api'
import type { AgentEmbedLink, AuthStatus } from '../types'
import { useTheme } from '../composables/useTheme'

const route = useRoute()
const router = useRouter()
const { resolved: resolvedTheme, setTheme } = useTheme()
const menuOpen = ref(false)
const themeMenuOpen = ref(false)
const themeOptions = [
  { id: 'dark', label: 'INK', hint: '暗色仪器', icon: 'moon' },
  { id: 'light', label: 'PAPER', hint: '浅色文档', icon: 'sun' },
  { id: 'gray', label: 'CONCRETE', hint: '瑞士灰', icon: 'grid' },
] as const
const version = ref('0.2.0')
const search = ref('')
const pendingApprovals = ref(0)
let pendingTimer: ReturnType<typeof setInterval> | undefined

const title = computed(() => (route.meta.title as string | undefined) ?? '控制台')

const agentEmbeds = ref<AgentEmbedLink[]>([])
const auth = ref<AuthStatus | null>(null)

const groups = computed(() => {
  const base = [
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
        { to: '/specimens', label: '样本', icon: 'records' },
        { to: '/isolates', label: '菌株', icon: 'grid' },
        { to: '/samples', label: '测序数据', icon: 'activity' },
        { to: '/runs', label: '运行记录', icon: 'runs' },
        { to: '/records', label: '数据记录', icon: 'file-text' },
        { to: '/gom', label: 'GOM', icon: 'server' },
      ],
    },
    {
      label: '系统',
      items: [
        { to: '/overview', label: '系统概览', icon: 'overview' },
        { to: '/search', label: '检索', icon: 'search' },
      ],
    },
  ]
  if (agentEmbeds.value.length) {
    base.push({
      label: '智能体对话',
      items: agentEmbeds.value.map((e, i) => ({
        to: `/agent/${i}`,
        label: e.name,
        icon: 'terminal',
      })),
    })
  }
  return base
})

watch(
  () => route.fullPath,
  () => {
    menuOpen.value = false
  },
)

onMounted(async () => {
  window.addEventListener('click', onDocumentClick)
  window.addEventListener('keydown', onDocumentKey)
  void loadPending()
  void loadAuth()
  pendingTimer = setInterval(() => void loadPending(), 60_000)
  try {
    const cap = await api.capabilities()
    version.value = cap.bacmap_version
    const embeds = cap.agent_embeds
    agentEmbeds.value = Array.isArray(embeds) ? embeds : []
  } catch {
    // 版本号是装饰信息，失败不打断控制台。
  }
})

onBeforeUnmount(() => {
  if (pendingTimer) clearInterval(pendingTimer)
  window.removeEventListener('click', onDocumentClick)
  window.removeEventListener('keydown', onDocumentKey)
})

function onDocumentClick(event: MouseEvent) {
  const target = event.target
  if (target instanceof Element && target.closest('.theme-control')) return
  themeMenuOpen.value = false
}

function onDocumentKey(event: KeyboardEvent) {
  if (event.key === 'Escape') themeMenuOpen.value = false
}

function chooseTheme(id: 'dark' | 'light' | 'gray') {
  setTheme(id)
  themeMenuOpen.value = false
}

async function loadPending() {
  try {
    const stats = await api.stats()
    pendingApprovals.value = stats.tasks.by_state.awaiting_approval ?? 0
  } catch {
    // 统计接口不可用时保持上次计数，不打断导航。
  }
}

async function loadAuth() {
  try {
    auth.value = await api.authStatus()
  } catch {
    // 旧服务端没有 /auth/status：不显示操作员信息，控制台照常使用。
  }
}

async function logout() {
  try {
    await api.logout()
  } catch {
    // 会话已过期时登出也会失败；无论如何回到登录页。
  }
  window.location.assign('/console/login')
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

        <div
          v-if="auth?.enabled && auth.authenticated"
          class="operator"
          :title="`鉴权模式：${auth.mode}`"
        >
          <Icon name="shield" :size="13" />
          <span class="operator__name">{{ auth.operator || '已登录' }}</span>
          <button
            class="icon-btn operator__logout"
            type="button"
            title="登出"
            aria-label="登出"
            @click="logout"
          >
            <Icon name="log-out" :size="15" />
          </button>
        </div>

        <div class="theme-control">
          <button
            class="icon-btn topbar__theme"
            type="button"
            aria-label="切换主题"
            title="切换主题"
            aria-haspopup="menu"
            :aria-expanded="themeMenuOpen"
            @click="themeMenuOpen = !themeMenuOpen"
          >
            <Icon
              :name="resolvedTheme === 'dark' ? 'moon' : resolvedTheme === 'light' ? 'sun' : 'grid'"
            />
          </button>
          <div v-if="themeMenuOpen" class="theme-menu" role="menu" aria-label="主题">
            <div class="theme-menu__head mono">THEME / 模板</div>
            <button
              v-for="option in themeOptions"
              :key="option.id"
              type="button"
              class="theme-menu__item"
              :class="{ 'is-active': resolvedTheme === option.id }"
              role="menuitemradio"
              :aria-checked="resolvedTheme === option.id"
              @click="chooseTheme(option.id)"
            >
              <span class="theme-menu__swatch" :class="`theme-menu__swatch--${option.id}`" />
              <span class="theme-menu__label">
                <strong>{{ option.label }}</strong>
                <small>{{ option.hint }}</small>
              </span>
              <Icon :name="option.icon" :size="14" />
            </button>
          </div>
        </div>
      </header>

      <main id="main" class="content" tabindex="-1">
        <RouterView />
      </main>
    </div>

    <ToastHost />
  </div>
</template>
