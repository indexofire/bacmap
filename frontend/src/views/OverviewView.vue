<script setup lang="ts">
import { onMounted, ref } from 'vue'
import Icon from '../components/Icon.vue'
import { api } from '../api'
import type { Overview } from '../types'
import { jsonText } from '../lib/format'

const overview = ref<Overview | null>(null)
const loading = ref(true)
const error = ref('')

const stateLabels: Record<string, string> = {
  pending: '排队中',
  running: '运行中',
  awaiting_approval: '待审批',
  succeeded: '已完成',
  failed: '已失败',
  cancelled: '已取消',
}

function stateLabel(key: string): string {
  return stateLabels[key] ?? key
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    overview.value = await api.overview()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载系统概览失败'
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
        <h1 class="pagehead__title">系统概览</h1>
        <p class="pagehead__sub">
          端点、数据策略、工具版本、路径与沙箱状态。只读，不含密钥。
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

    <div v-if="loading" class="card card--pad"><div class="skeleton" style="height: 240px" /></div>

    <template v-else-if="overview">
      <div class="kpi-grid">
        <div class="kpi">
          <div class="kpi__label"><Icon name="shield" /> 数据上限</div>
          <div class="kpi__value">{{ overview.cloud_max_data_class }}</div>
          <div class="kpi__foot">cloud LLM 端点允许的最高分级</div>
        </div>
        <div class="kpi">
          <div class="kpi__label"><Icon name="server" /> 沙箱</div>
          <div class="kpi__value" style="font-size: 18px">{{ overview.sandbox }}</div>
          <div class="kpi__foot">mine / write 执行后端</div>
        </div>
        <div class="kpi">
          <div class="kpi__label"><Icon name="terminal" /> LLM 端点</div>
          <div class="kpi__value">{{ overview.endpoints.length }}</div>
          <div class="kpi__foot">已配置的模型服务</div>
        </div>
        <div class="kpi">
          <div class="kpi__label"><Icon name="activity" /> 任务总数</div>
          <div class="kpi__value">{{ Object.values(overview.task_counts).reduce((a, b) => a + b, 0) }}</div>
          <div class="kpi__foot">按状态统计</div>
        </div>
      </div>

      <div class="dash-grid">
        <div class="stack">
          <section class="card">
            <div class="card__head">
              <h2 class="card__title">LLM 端点</h2>
              <span class="card__hint">ADR-16：D3/D4 永不发往 cloud</span>
            </div>
            <div v-if="overview.endpoints.length" class="table-wrap">
              <table class="table">
                <thead>
                  <tr>
                    <th scope="col">名称</th>
                    <th scope="col">位置</th>
                    <th scope="col">模型</th>
                    <th scope="col">地址</th>
                    <th scope="col">状态</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="endpoint in overview.endpoints" :key="endpoint.name">
                    <td data-label="名称"><code>{{ endpoint.name }}</code></td>
                    <td data-label="位置">{{ endpoint.location }}</td>
                    <td data-label="模型" class="mono">{{ endpoint.model }}</td>
                    <td data-label="地址" class="mono muted" style="font-size: 11px">{{ endpoint.base_url }}</td>
                    <td data-label="状态">
                      <span class="badge" :class="endpoint.enabled ? 'badge--succeeded' : 'badge--cancelled'">
                        <span class="badge__dot" />
                        {{ endpoint.enabled ? '启用' : '停用' }}
                      </span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-else class="muted" style="padding: 20px">未配置 LLM 端点。</p>
          </section>

          <section class="card">
            <div class="card__head">
              <h2 class="card__title">路由与策略</h2>
            </div>
            <div class="card__body">
              <pre class="code-block">{{ jsonText(overview.routing) }}</pre>
            </div>
          </section>

          <section class="card">
            <div class="card__head">
              <h2 class="card__title">路径</h2>
            </div>
            <div class="card__body">
              <div class="stack">
                <div v-for="(value, key) in overview.paths" :key="key" class="kv">
                  <span class="kv__k">{{ key }}</span>
                  <span class="kv__v mono">{{ value }}</span>
                </div>
              </div>
            </div>
          </section>
        </div>

        <div class="stack">
          <section class="card card--pad">
            <h2 class="card__title" style="margin-bottom: 14px">工具版本</h2>
            <div class="stack">
              <div v-for="(value, key) in overview.versions" :key="key" class="kv">
                <span class="kv__k">{{ key }}</span>
                <span class="kv__v mono">{{ value }}</span>
              </div>
            </div>
          </section>

          <section class="card card--pad">
            <h2 class="card__title" style="margin-bottom: 14px">任务状态计数</h2>
            <div class="stack">
              <div v-for="(value, key) in overview.task_counts" :key="key" class="kv">
                <span class="kv__k">{{ stateLabel(String(key)) }}</span>
                <span class="kv__v mono">{{ value }}</span>
              </div>
              <p v-if="!Object.keys(overview.task_counts).length" class="muted">暂无任务。</p>
            </div>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>
