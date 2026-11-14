<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import { api } from '../api'
import type { AuthStatus } from '../types'

const route = useRoute()
const status = ref<AuthStatus | null>(null)
const loading = ref(true)
const submitting = ref(false)
const token = ref('')
const error = ref('')

// 只接受站内路径：服务端已过滤一次，这里再兜底（防开放重定向）。
const next = computed(() => {
  const raw = String(route.query.next ?? '')
  if (!raw.startsWith('/') || raw.startsWith('//')) return '/'
  if (raw === '/console/login' || raw.startsWith('/console/login?')) return '/'
  return raw
})

onMounted(() => void refresh())

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    status.value = await api.authStatus()
    if (status.value.enabled && status.value.authenticated) {
      window.location.assign(next.value)
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : '无法获取登录状态'
  } finally {
    loading.value = false
  }
}

async function submit() {
  const value = token.value.trim()
  if (!value) return
  submitting.value = true
  error.value = ''
  try {
    const result = await api.login(value, next.value)
    window.location.assign(result.next || '/console/')
  } catch (err) {
    error.value = err instanceof Error ? err.message : '登录失败'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="login-screen">
    <section class="login-panel" aria-labelledby="login-title">
      <div class="login-brand">
        <span class="login-mark"><Icon name="activity" :size="18" /></span>
        <span class="login-word">bacmap</span>
        <span class="login-tag">console</span>
      </div>

      <h1 id="login-title" class="login-title">登录控制台</h1>

      <p v-if="loading" class="login-hint">正在检查登录状态…</p>

      <template v-else-if="status?.enabled && status.mode === 'cookie'">
        <p class="login-hint">
          输入部署令牌（环境变量 <code>BACMAP_WEB_TOKEN</code>）进入本机控制台。
        </p>
        <form class="login-form" @submit.prevent="submit">
          <label class="field__label" for="login-token">访问令牌</label>
          <input
            id="login-token"
            v-model="token"
            class="input"
            type="password"
            autocomplete="current-password"
            autofocus
            required
          />
          <p v-if="error" class="form-error" role="alert">{{ error }}</p>
          <button
            class="btn btn--primary login-submit"
            type="submit"
            :disabled="submitting || !token.trim()"
          >
            <span v-if="submitting" class="spinner" />
            <Icon v-else name="shield" />
            登录
          </button>
        </form>
        <p class="login-foot">令牌只用于本机/局域网控制台登录，不会离开本机。</p>
      </template>

      <template v-else-if="status && !status.enabled">
        <p class="login-hint">
          鉴权未启用（未设置 <code>BACMAP_WEB_TOKEN</code>），可直接进入控制台。
        </p>
        <a class="btn btn--primary login-submit" href="/console/">进入控制台</a>
      </template>

      <template v-else-if="status?.mode === 'bearer'">
        <p class="login-hint">
          当前为 <strong>bearer</strong> 模式（仅供 API 客户端）。浏览器登录需设置
          <code>BACMAP_WEB_AUTH=cookie</code> 后重启服务。
        </p>
        <a class="btn login-submit" href="/console/">返回控制台</a>
      </template>

      <template v-else>
        <p class="login-hint">{{ error || '无法获取登录状态。' }}</p>
        <button class="btn login-submit" type="button" @click="refresh">
          <Icon name="refresh" />
          重试
        </button>
      </template>
    </section>
  </div>
</template>

<style scoped>
.login-screen {
  display: grid;
  min-height: 100vh;
  padding: var(--sp-6, 24px);
  place-items: center;
  background:
    radial-gradient(circle at 18% 12%, var(--body-glow), transparent 42%),
    var(--bg);
}

.login-panel {
  width: min(420px, 100%);
  padding: 32px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--panel);
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.35);
}

.login-brand {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 20px;
}

.login-mark {
  display: inline-grid;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  place-items: center;
  background: var(--accent-soft);
  color: var(--link);
}

.login-word {
  font-family: var(--font-display, system-ui, sans-serif);
  font-size: 20px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--text-1);
}

.login-tag {
  color: var(--text-3);
  font-family: var(--font-mono, monospace);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.login-title {
  margin: 0 0 8px;
  font-size: 24px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--text-1);
}

.login-hint {
  margin: 0 0 20px;
  color: var(--text-3);
  font-size: 13px;
  line-height: 1.6;
}

.login-hint code {
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--code-bg);
  font-family: var(--font-mono, monospace);
  font-size: 12px;
}

.login-form {
  display: grid;
  gap: 10px;
}

.login-submit {
  justify-content: center;
  margin-top: 6px;
}

.login-foot {
  margin: 18px 0 0;
  color: var(--text-4);
  font-size: 11px;
  line-height: 1.5;
}
</style>
