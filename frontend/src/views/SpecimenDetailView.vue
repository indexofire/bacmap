<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import CopyButton from '../components/CopyButton.vue'
import EmptyState from '../components/EmptyState.vue'
import { api } from '../api'
import type { SpecimenDetail } from '../types'

const route = useRoute()
const router = useRouter()
const id = String(route.params.id)

const data = ref<SpecimenDetail | null>(null)
const loading = ref(true)
const error = ref('')
const deleting = ref(false)

const specimen = computed(() => data.value?.specimen ?? null)
const isolates = computed(() => data.value?.isolates ?? [])
const hasIsolates = computed(() => isolates.value.length > 0)

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await api.getSpecimen(id)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载样本详情失败'
  } finally {
    loading.value = false
  }
}

async function remove(force: boolean) {
  const prompt = force
    ? `将解除该样本下 ${isolates.value.length} 个菌株的关联（不删除菌株、测序数据或分析结果），然后删除样本。确定继续？`
    : `删除样本 ${id}？此操作不可撤销。`
  if (!window.confirm(prompt)) return
  deleting.value = true
  error.value = ''
  try {
    await api.deleteSpecimen(id, force)
    await router.push('/specimens')
  } catch (err) {
    error.value = err instanceof Error ? err.message : '删除样本失败'
  } finally {
    deleting.value = false
  }
}

onMounted(() => void load())
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <div class="inline-actions" style="margin-bottom: 8px">
          <RouterLink to="/specimens" class="btn btn--ghost btn--sm">
            <Icon name="arrow-left" />
            返回样本
          </RouterLink>
        </div>
        <h1 class="pagehead__title inline-actions">
          <span>{{ id }}</span>
          <CopyButton :value="id" label="样本编号" />
        </h1>
        <p class="pagehead__sub">样本下图菌株及其测序数据；结果仍按测序数据/运行隔离。</p>
      </div>
      <div class="pagehead__actions">
        <button class="btn btn--ghost" type="button" :disabled="loading" @click="load">
          <Icon name="refresh" />
          刷新
        </button>
        <button
          v-if="specimen && !loading"
          class="btn btn--danger"
          type="button"
          :disabled="deleting"
          :title="
            hasIsolates
              ? '先解除菌株关联（不删菌株/数据）再删除样本'
              : '删除这个空样本'
          "
          @click="remove(hasIsolates)"
        >
          <span v-if="deleting" class="spinner" />
          <Icon v-else name="trash" />
          {{ hasIsolates ? '解除关联并删除' : '删除样本' }}
        </button>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>
    <div v-if="loading" class="card card--pad"><div class="skeleton" style="height: 220px" /></div>

    <template v-else-if="specimen">
      <div class="detail-grid">
        <div class="stack">
          <section class="card">
            <div class="card__head">
              <h2 class="card__title">样本信息</h2>
              <span class="card__hint">不可变编号</span>
            </div>
            <div class="card__body">
              <dl class="statuslist">
                <div class="statuslist__row"><dt>样本编号</dt><dd class="mono">{{ specimen.specimen_id }}</dd></div>
                <div class="statuslist__row"><dt>来源</dt><dd>{{ specimen.origin || '—' }}</dd></div>
                <div class="statuslist__row"><dt>菌株数</dt><dd class="mono">{{ isolates.length }}</dd></div>
                <div v-if="specimen.note" class="statuslist__row"><dt>备注</dt><dd class="muted">{{ specimen.note }}</dd></div>
              </dl>
            </div>
          </section>

          <section class="card">
            <div class="card__head">
              <h2 class="card__title">菌株</h2>
              <span class="card__hint">{{ isolates.length }} 株</span>
            </div>
            <div v-if="isolates.length" class="card__body">
              <div v-for="isolate in isolates" :key="isolate.isolate_id" class="stack" style="margin-bottom: 18px">
                <div class="detail-head" style="margin: 0">
                  <RouterLink class="link-cell" :to="`/isolates/${isolate.isolate_id}`">
                    <code class="detail-id">{{ isolate.isolate_id }}</code>
                  </RouterLink>
                  <span v-if="isolate.lineage_id" class="card__hint">
                    谱系 {{ isolate.lineage_id }}<template v-if="isolate.passage != null"> · 第 {{ isolate.passage }} 代</template>
                  </span>
                </div>
                <div v-if="isolate.libraries?.length" class="table-wrap">
                  <table class="table">
                    <thead>
                      <tr><th scope="col">测序数据</th><th scope="col">平台</th><th scope="col">操作</th></tr>
                    </thead>
                    <tbody>
                      <tr v-for="lib in isolate.libraries" :key="lib.library_id">
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
                <p v-else class="muted">该菌株暂无登记测序数据。</p>
              </div>
            </div>
            <EmptyState v-else title="该样本暂无菌株" hint="样本级测序（mNGS/tNGS）将在后续版本接入。" />
          </section>
        </div>
      </div>
    </template>
  </div>
</template>
