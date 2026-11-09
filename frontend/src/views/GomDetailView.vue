<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import { api } from '../api'
import type { GomObject } from '../types'
import { fmtTime, jsonText } from '../lib/format'

const route = useRoute()
const id = String(route.params.id)
const version = route.query.version ? Number(route.query.version) : undefined
const object = ref<GomObject | null>(null)
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    object.value = await api.getGom(id, version)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载 GOM 对象失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => void load())
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <div class="inline-actions" style="margin-bottom: 8px">
          <RouterLink to="/gom" class="btn btn--ghost btn--sm">
            <Icon name="arrow-left" />
            返回 GOM
          </RouterLink>
        </div>
        <h1 class="pagehead__title">GOM 对象</h1>
        <p class="pagehead__sub">不可变对象的最新版本或指定版本。</p>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>
    <div v-if="loading" class="card card--pad"><div class="skeleton" style="height: 220px" /></div>

    <template v-else-if="object">
      <div class="detail-grid">
        <div class="stack">
          <section class="card">
            <div class="card__head">
              <div>
                <code class="detail-id">{{ object.object_id }}</code>
                <p class="card__hint" style="margin-top: 4px">
                  {{ object.object_type }} · v{{ object.version }} · {{ object.strain_id || '—' }}
                </p>
              </div>
            </div>
            <div class="card__body">
              <dl class="statuslist">
                <div class="statuslist__row"><dt>类型</dt><dd><code>{{ object.object_type }}</code></dd></div>
                <div class="statuslist__row"><dt>版本</dt><dd class="mono">v{{ object.version }}</dd></div>
                <div class="statuslist__row"><dt>菌株</dt><dd>{{ object.strain_id || '—' }}</dd></div>
                <div class="statuslist__row"><dt>创建时间</dt><dd class="mono">{{ fmtTime(object.created_at) }}</dd></div>
                <div class="statuslist__row"><dt>载荷键</dt><dd class="mono">{{ (object.payload_keys ?? []).join(', ') || '—' }}</dd></div>
              </dl>
            </div>
          </section>
          <section class="card">
            <div class="card__head"><h2 class="card__title">载荷</h2></div>
            <div class="card__body"><pre class="code-block">{{ jsonText(object.payload) }}</pre></div>
          </section>
        </div>
        <div class="stack">
          <section class="card card--pad">
            <h2 class="card__title" style="margin-bottom: 14px">原始对象</h2>
            <pre class="code-block">{{ jsonText(object) }}</pre>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>
