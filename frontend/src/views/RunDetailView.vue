<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import { api } from '../api'
import type { RunRow } from '../types'
import { fmtTime, jsonText } from '../lib/format'

const route = useRoute()
const id = String(route.params.id)

const run = ref<RunRow | null>(null)
const compareWith = ref('')
const compare = ref<Record<string, unknown> | null>(null)
const loading = ref(true)
const comparing = ref(false)
const error = ref('')
const compareError = ref('')

const sections = computed(() => {
  if (!run.value) return []
  const preferred = ['tool_versions', 'ref_databases', 'resolved_config', 'input_files', 'params']
  return preferred
    .filter((key) => run.value && key in run.value)
    .map((key) => ({ key, value: run.value![key] }))
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    run.value = await api.getRun(id)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载运行记录失败'
  } finally {
    loading.value = false
  }
}

async function compareRuns() {
  if (!compareWith.value.trim()) return
  comparing.value = true
  compareError.value = ''
  try {
    compare.value = await api.compareRuns(id, compareWith.value.trim())
  } catch (err) {
    compareError.value = err instanceof Error ? err.message : '比较失败'
    compare.value = null
  } finally {
    comparing.value = false
  }
}

onMounted(() => void load())
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <div class="inline-actions" style="margin-bottom: 8px">
          <RouterLink to="/runs" class="btn btn--ghost btn--sm">
            <Icon name="arrow-left" />
            返回运行记录
          </RouterLink>
        </div>
        <h1 class="pagehead__title">运行详情</h1>
        <p class="pagehead__sub">不可变证据：工具版本、参考库、配置与输入指纹。</p>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>

    <template v-if="loading">
      <div class="card card--pad"><div class="skeleton" style="height: 220px" /></div>
    </template>

    <template v-else-if="run">
      <div class="detail-grid">
        <div class="stack">
          <section class="card">
            <div class="card__head">
              <div>
                <code class="detail-id">{{ run.run_id }}</code>
                <p class="card__hint" style="margin-top: 4px">
                  {{ run.sample_id ?? '—' }} · {{ fmtTime(String(run.created_at ?? '')) }}
                </p>
              </div>
            </div>
            <div class="card__body">
              <dl class="statuslist">
                <div class="statuslist__row">
                  <dt>样本</dt>
                  <dd>{{ run.sample_id ?? '—' }}</dd>
                </div>
                <div class="statuslist__row">
                  <dt>任务</dt>
                  <dd>
                    <RouterLink v-if="run.task_id" class="link-cell" :to="`/tasks/${run.task_id}`">
                      {{ run.task_id }}
                    </RouterLink>
                    <span v-else>—</span>
                  </dd>
                </div>
                <div class="statuslist__row">
                  <dt>创建时间</dt>
                  <dd class="mono">{{ fmtTime(String(run.created_at ?? '')) }}</dd>
                </div>
              </dl>
            </div>
          </section>

          <section v-for="section in sections" :key="section.key" class="card">
            <div class="card__head">
              <h2 class="card__title">{{ section.key }}</h2>
            </div>
            <div class="card__body">
              <pre class="code-block">{{ jsonText(section.value) }}</pre>
            </div>
          </section>
        </div>

        <div class="stack">
          <section class="card card--pad">
            <h2 class="card__title">与另一运行比较</h2>
            <p class="card__hint" style="margin: 4px 0 14px">
              输入另一个 run_id，比较来源字段差异。
            </p>
            <form class="form" @submit.prevent="compareRuns">
              <div class="field">
                <label class="field__label" for="other-run">另一个运行 ID</label>
                <input
                  id="other-run"
                  v-model="compareWith"
                  class="input input--mono"
                  placeholder="run_id"
                  autocomplete="off"
                />
              </div>
              <div v-if="compareError" class="form-error" role="alert">{{ compareError }}</div>
              <div class="form__actions">
                <button class="btn btn--primary" type="submit" :disabled="comparing">
                  <span v-if="comparing" class="spinner" />
                  <Icon v-else name="chart" />
                  比较
                </button>
              </div>
            </form>
            <div v-if="compare" style="margin-top: 16px">
              <pre class="code-block">{{ jsonText(compare) }}</pre>
            </div>
          </section>

          <section class="card card--pad">
            <h2 class="card__title">原始记录</h2>
            <p class="card__hint" style="margin: 4px 0 14px">完整 JSON（只读）。</p>
            <pre class="code-block">{{ jsonText(run) }}</pre>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>
