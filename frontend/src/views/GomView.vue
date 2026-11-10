<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'
import { api } from '../api'
import type { GomObject } from '../types'
import { fmtTime, shortId } from '../lib/format'

const router = useRouter()
const objects = ref<GomObject[]>([])
const allTypes = ref<string[]>([])
const type = ref('')
const loading = ref(true)
const error = ref('')

function goRow(event: Event, path: string) {
  const target = event.target
  if (target instanceof Element && target.closest('a,button')) return
  void router.push(path)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const items = await api.listGom(type.value.trim() || undefined, 200)
    objects.value = items
    if (!type.value.trim()) {
      allTypes.value = Array.from(new Set(items.map((o) => o.object_type))).sort()
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载 GOM 对象失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => void load())
watch(type, () => void load())
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <h1 class="pagehead__title">GOM 对象</h1>
        <p class="pagehead__sub">基因组对象是不可变事实（ADR-13）；这里展示最新版本的只读视图。</p>
      </div>
      <div class="pagehead__actions">
        <button class="btn btn--ghost" type="button" :disabled="loading" @click="load">
          <Icon name="refresh" />
          刷新
        </button>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>

    <section class="card">
      <div class="filters">
        <select v-model="type" class="select" style="width: 180px; height: 30px; padding: 0 30px 0 10px; font-size: 12px">
          <option value="">全部类型</option>
          <option v-for="item in allTypes" :key="item" :value="item">{{ item }}</option>
        </select>
        <span class="filter-spacer" />
        <span class="card__hint">{{ objects.length }} 条</span>
      </div>

      <div v-if="loading" class="card__body"><div class="skeleton" style="height: 200px" /></div>

      <div v-else-if="objects.length" class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th scope="col">object_id</th>
              <th scope="col">类型</th>
              <th scope="col">版本</th>
              <th scope="col">菌株</th>
              <th scope="col">载荷键</th>
              <th scope="col">时间</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="obj in objects"
              :key="`${obj.object_id}-${obj.version}`"
              class="row-click"
              @click="goRow($event, `/gom/${obj.object_id}?version=${obj.version}`)"
            >
              <td data-label="object_id">
                <RouterLink class="link-cell" :to="`/gom/${obj.object_id}?version=${obj.version}`">
                  {{ shortId(obj.object_id, 18) }}
                </RouterLink>
              </td>
              <td data-label="类型"><code>{{ obj.object_type }}</code></td>
              <td data-label="版本"><span class="mono">v{{ obj.version }}</span></td>
              <td data-label="菌株">{{ obj.strain_id || '—' }}</td>
              <td data-label="载荷键">
                <span class="mono muted" style="font-size: 11px">{{ (obj.payload_keys ?? []).join(', ') }}</span>
              </td>
              <td data-label="时间"><span class="mono muted">{{ fmtTime(obj.created_at) }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>

      <EmptyState
        v-else
        title="暂无 GOM 对象"
        hint="完成一次分析后，样本与分析对象会出现在这里。"
        icon="records"
      />
    </section>
  </div>
</template>
