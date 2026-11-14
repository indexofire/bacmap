<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import CopyButton from '../components/CopyButton.vue'
import { api } from '../api'
import type { IsolateDetail } from '../types'

const route = useRoute()
const id = String(route.params.id)

const data = ref<IsolateDetail | null>(null)
const loading = ref(true)
const error = ref('')

const isolate = computed(() => data.value?.isolate ?? null)
const specimen = computed(() => data.value?.specimen ?? null)
const libraries = computed(() => data.value?.libraries ?? [])

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await api.getIsolate(id)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载菌株详情失败'
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
          <RouterLink to="/isolates" class="btn btn--ghost btn--sm">
            <Icon name="arrow-left" />
            返回菌株
          </RouterLink>
        </div>
        <h1 class="pagehead__title inline-actions">
          <span>{{ id }}</span>
          <CopyButton :value="id" label="菌株 ID" />
        </h1>
        <p class="pagehead__sub">菌株实体、所属样本与其测序数据。</p>
      </div>
      <div class="pagehead__actions">
        <button class="btn btn--ghost" type="button" :disabled="loading" @click="load">
          <Icon name="refresh" />
          刷新
        </button>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>
    <div v-if="loading" class="card card--pad"><div class="skeleton" style="height: 220px" /></div>

    <template v-else-if="isolate">
      <div class="detail-grid">
        <div class="stack">
          <section class="card">
            <div class="card__head"><h2 class="card__title">菌株信息</h2></div>
            <div class="card__body">
              <dl class="statuslist">
                <div class="statuslist__row"><dt>菌株</dt><dd class="mono">{{ isolate.isolate_id }}</dd></div>
                <div class="statuslist__row">
                  <dt>样本</dt>
                  <dd>
                    <RouterLink v-if="specimen" class="link-cell" :to="`/specimens/${specimen.specimen_id}`">
                      {{ specimen.specimen_id }}
                    </RouterLink>
                    <span v-else class="muted">未关联</span>
                  </dd>
                </div>
                <div class="statuslist__row"><dt>谱系</dt><dd>{{ isolate.lineage_id || '—' }}</dd></div>
                <div class="statuslist__row"><dt>传代</dt><dd class="mono">{{ isolate.passage ?? '—' }}</dd></div>
              </dl>
            </div>
          </section>

          <section v-if="data?.metadata" class="card">
            <div class="card__head">
              <h2 class="card__title">湿实验元数据</h2>
              <span class="card__hint">菌株级背景信息</span>
            </div>
            <div class="card__body">
              <dl class="statuslist">
                <div
                  v-for="(value, key) in data.metadata"
                  :key="key"
                  class="statuslist__row"
                >
                  <dt>{{ key }}</dt>
                  <dd class="mono">{{ typeof value === 'object' ? JSON.stringify(value) : value }}</dd>
                </div>
              </dl>
            </div>
          </section>

          <section v-if="data?.lab_results?.length" class="card">
            <div class="card__head">
              <h2 class="card__title">化验结果</h2>
              <span class="card__hint">{{ data.lab_results.length }} 条</span>
            </div>
            <div class="card__body">
              <div class="table-wrap">
                <table class="table">
                  <thead>
                    <tr>
                      <th scope="col">类别</th>
                      <th scope="col">项目</th>
                      <th scope="col">结果</th>
                      <th scope="col">单位</th>
                      <th scope="col">日期</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="lab in data.lab_results" :key="lab.id">
                      <td data-label="类别">{{ lab.category }}</td>
                      <td data-label="项目">{{ lab.test_name }}</td>
                      <td data-label="结果" class="mono">{{ lab.result }}</td>
                      <td data-label="单位">{{ lab.unit || '—' }}</td>
                      <td data-label="日期">{{ lab.tested_date || '—' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </section>

          <section class="card">
            <div class="card__head">
              <h2 class="card__title">测序数据</h2>
              <span class="card__hint">{{ libraries.length }} 份</span>
            </div>
            <div v-if="libraries.length" class="card__body">
              <div class="table-wrap">
                <table class="table">
                  <thead>
                    <tr><th scope="col">测序数据</th><th scope="col">平台</th><th scope="col">操作</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="lib in libraries" :key="lib.library_id">
                      <td data-label="测序数据"><code>{{ lib.library_id }}</code></td>
                      <td data-label="平台">{{ lib.platform || '—' }}</td>
                      <td data-label="操作">
                        <RouterLink class="btn btn--ghost btn--sm" :to="`/samples/${lib.library_id}`">
                          查看结果
                        </RouterLink>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            <div v-else class="card__body"><p class="muted">该菌株暂无登记测序数据。</p></div>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>
