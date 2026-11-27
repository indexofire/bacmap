<script setup lang="ts">
import { onMounted, ref } from 'vue'
import EmptyState from '../components/EmptyState.vue'
import Icon from '../components/Icon.vue'
import { api } from '../api'
import type { UserRow } from '../types'

const rows = ref<UserRow[]>([])
const loading = ref(true)
const error = ref('')
const message = ref('')

const username = ref('')
const password = ref('')
const displayName = ref('')
const role = ref<UserRow['role']>('user')
const creating = ref(false)

const selected = ref<UserRow | null>(null)
const tokens = ref<Array<Record<string, unknown>>>([])
const tokenName = ref('')
const newToken = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    rows.value = await api.listUsers()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载用户失败'
  } finally {
    loading.value = false
  }
}

async function createUser() {
  if (!username.value.trim() || password.value.length < 8) return
  creating.value = true
  error.value = ''
  message.value = ''
  try {
    await api.createUser({
      username: username.value.trim(),
      password: password.value,
      role: role.value,
      display_name: displayName.value.trim(),
    })
    username.value = ''
    password.value = ''
    displayName.value = ''
    role.value = 'user'
    message.value = '用户已创建'
    await load()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '创建失败'
  } finally {
    creating.value = false
  }
}

async function changeRole(user: UserRow, value: string) {
  try {
    await api.setUserRole(user.user_id, value as UserRow['role'])
    message.value = `${user.username} 的角色已更新`
    await load()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '修改失败'
  }
}

async function toggleDisabled(user: UserRow) {
  try {
    await api.setUserDisabled(user.user_id, !user.disabled)
    message.value = `${user.username} 已${user.disabled ? '启用' : '停用'}`
    await load()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '操作失败'
  }
}

async function resetPassword(user: UserRow) {
  const value = window.prompt(`为 ${user.username} 设置新密码（至少 8 位）`)
  if (!value) return
  try {
    await api.resetUserPassword(user.user_id, value)
    message.value = `${user.username} 的密码已重置`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '重置失败'
  }
}

async function openTokens(user: UserRow) {
  selected.value = user
  newToken.value = ''
  tokenName.value = ''
  try {
    tokens.value = await api.listUserTokens(user.user_id)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载令牌失败'
  }
}

async function createToken() {
  if (!selected.value) return
  try {
    const result = await api.createUserToken(selected.value.user_id, tokenName.value)
    newToken.value = result.token
    tokens.value = await api.listUserTokens(selected.value.user_id)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '创建令牌失败'
  }
}

async function revokeToken(tokenId: string) {
  if (!selected.value) return
  try {
    await api.revokeUserToken(selected.value.user_id, tokenId)
    tokens.value = await api.listUserTokens(selected.value.user_id)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '吊销失败'
  }
}

onMounted(() => void load())
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <h1 class="pagehead__title">用户管理</h1>
        <p class="pagehead__sub">
          admin 管理全部；analyst 可分析、确认与审核；user 只能提交并查看自己的数据。
        </p>
      </div>
      <div class="pagehead__actions">
        <button class="btn btn--ghost" type="button" :disabled="loading" @click="load">
          <Icon name="refresh" />
          刷新
        </button>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>
    <div v-if="message" class="card__hint" style="margin-bottom: 16px">{{ message }}</div>

    <section class="card card--pad" style="margin-bottom: 16px">
      <div class="card__head">
        <h2 class="card__title">创建用户</h2>
        <span class="card__hint">首个管理员请在本机用 CLI 创建</span>
      </div>
      <form class="form" @submit.prevent="createUser">
        <div class="meta-grid">
          <div class="field">
            <label class="field__label" for="new-username">用户名</label>
            <input id="new-username" v-model="username" class="input" autocomplete="off" />
          </div>
          <div class="field">
            <label class="field__label" for="new-display">显示名（可选）</label>
            <input id="new-display" v-model="displayName" class="input" />
          </div>
          <div class="field">
            <label class="field__label" for="new-password">初始密码</label>
            <input
              id="new-password"
              v-model="password"
              class="input"
              type="password"
              autocomplete="new-password"
            />
          </div>
          <div class="field">
            <label class="field__label" for="new-role">角色</label>
            <select id="new-role" v-model="role" class="input">
              <option value="user">user（提交/查看自己）</option>
              <option value="analyst">analyst（分析/确认/审核）</option>
              <option value="admin">admin（全部）</option>
            </select>
          </div>
        </div>
        <div class="form__actions">
          <button
            class="btn btn--primary"
            type="submit"
            :disabled="creating || !username.trim() || password.length < 8"
          >
            <span v-if="creating" class="spinner" />
            <Icon v-else name="check" />
            创建
          </button>
        </div>
      </form>
    </section>

    <section class="card">
      <div v-if="loading" class="card__body"><div class="skeleton" style="height: 220px" /></div>
      <div v-else-if="rows.length" class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th scope="col">用户</th>
              <th scope="col">角色</th>
              <th scope="col">状态</th>
              <th scope="col">创建时间</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.user_id">
              <td data-label="用户">
                <strong>{{ row.username }}</strong>
                <span v-if="row.display_name" class="muted"> · {{ row.display_name }}</span>
              </td>
              <td data-label="角色">
                <select
                  class="input"
                  :value="row.role"
                  :disabled="row.username === 'system'"
                  @change="changeRole(row, ($event.target as HTMLSelectElement).value)"
                >
                  <option value="user">user</option>
                  <option value="analyst">analyst</option>
                  <option value="admin">admin</option>
                </select>
              </td>
              <td data-label="状态">
                <span :class="row.disabled ? 'muted' : 'mono'">
                  {{ row.disabled ? '已停用' : '正常' }}
                </span>
              </td>
              <td data-label="创建时间">{{ row.created_at.slice(0, 10) }}</td>
              <td data-label="操作">
                <div class="inline-actions">
                  <button class="btn btn--ghost" type="button" @click="resetPassword(row)">
                    重置密码
                  </button>
                  <button class="btn btn--ghost" type="button" @click="openTokens(row)">
                    令牌
                  </button>
                  <button class="btn btn--ghost" type="button" @click="toggleDisabled(row)">
                    {{ row.disabled ? '启用' : '停用' }}
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <EmptyState v-else title="暂无用户" hint="用上方表单创建第一个业务用户。" icon="shield" />
    </section>

    <section v-if="selected" class="card card--pad" style="margin-top: 16px">
      <div class="card__head">
        <h2 class="card__title">{{ selected.username }} 的 API 令牌</h2>
        <button class="btn btn--ghost" type="button" @click="selected = null">关闭</button>
      </div>
      <div v-if="newToken" class="form-error" style="margin-bottom: 12px">
        新令牌只显示一次：<code class="mono">{{ newToken }}</code>
      </div>
      <form class="inline-actions" @submit.prevent="createToken">
        <input v-model="tokenName" class="input" placeholder="令牌用途，如 cli-laptop" />
        <button class="btn btn--primary" type="submit">创建令牌</button>
      </form>
      <ul v-if="tokens.length" style="margin-top: 12px">
        <li v-for="token in tokens" :key="String(token.id)">
          <span class="mono">{{ token.id }}</span>
          · {{ token.name || '未命名' }}
          · {{ token.revoked ? '已吊销' : '有效' }}
          <button
            v-if="!token.revoked"
            class="btn btn--ghost"
            type="button"
            @click="revokeToken(String(token.id))"
          >
            吊销
          </button>
        </li>
      </ul>
      <p v-else class="card__hint">暂无令牌。</p>
    </section>
  </div>
</template>
