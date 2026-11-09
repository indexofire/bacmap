<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { api } from '../api'
import type { TaskRow } from '../types'
import { fmtTime, shortId } from '../lib/format'
import { useToast } from '../composables/useToast'

const toast = useToast()
const tabs = [
  { key: 'metadata', label: '元数据' },
  { key: 'lab', label: '化验结果' },
  { key: 'knowledge-import', label: '知识导入' },
  { key: 'knowledge-approve', label: '知识审核' },
] as const

const active = ref<(typeof tabs)[number]['key']>('metadata')
const tasks = ref<TaskRow[]>([])
const loading = ref(true)
const busy = ref(false)
const error = ref('')

const metadata = ref({ strain_id: '', sample_id: '', fields: '' })
const lab = ref({ strain_id: '', category: '', test_name: '', result: '', unit: '' })
const knowledge = ref({ title: '', identifier: '', content: '' })
const approve = ref({ entry_id: '' })

const recent = computed(() => tasks.value.filter((t) => t.task_type === 'record').slice(0, 10))

async function load() {
  loading.value = true
  try {
    tasks.value = await api.listTasks(200)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载记录任务失败'
  } finally {
    loading.value = false
  }
}

async function submit() {
  busy.value = true
  error.value = ''
  try {
    let task: TaskRow
    if (active.value === 'metadata') {
      task = await api.createRecord('metadata', {
        strain_id: metadata.value.strain_id,
        sample_id: metadata.value.sample_id,
        fields: metadata.value.fields,
      })
      metadata.value = { strain_id: '', sample_id: '', fields: '' }
    } else if (active.value === 'lab') {
      task = await api.createRecord('lab', { ...lab.value })
      lab.value = { strain_id: '', category: '', test_name: '', result: '', unit: '' }
    } else if (active.value === 'knowledge-import') {
      task = await api.createRecord('knowledge-import', { ...knowledge.value })
      knowledge.value = { title: '', identifier: '', content: '' }
    } else {
      task = await api.createRecord('knowledge-approve', { entry_id: approve.value.entry_id })
      approve.value = { entry_id: '' }
    }
    toast.ok(`记录任务已提交：${task.task_id.slice(0, 12)}…`)
    await load()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '提交记录失败'
  } finally {
    busy.value = false
  }
}

onMounted(() => void load())
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <h1 class="pagehead__title">数据记录</h1>
        <p class="pagehead__sub">
          元数据、化验结果与知识库写入都经 record 任务与证据链，不直接改库。
        </p>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>

    <div class="detail-grid">
      <section class="card">
        <div class="filters">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            type="button"
            class="chip"
            :class="{ 'is-active': active === tab.key }"
            @click="active = tab.key"
          >
            {{ tab.label }}
          </button>
        </div>

        <form class="card__body form" @submit.prevent="submit">
          <template v-if="active === 'metadata'">
            <div class="field">
              <label class="field__label" for="md-strain">菌株 / 样本 ID</label>
              <input id="md-strain" v-model="metadata.strain_id" class="input" required autocomplete="off" />
            </div>
            <div class="field">
              <label class="field__label" for="md-sample">
                样本 ID
                <span class="field__optional">可选，默认同菌株</span>
              </label>
              <input id="md-sample" v-model="metadata.sample_id" class="input" autocomplete="off" />
            </div>
            <div class="field">
              <label class="field__label" for="md-fields">字段</label>
              <textarea
                id="md-fields"
                v-model="metadata.fields"
                class="textarea textarea--mono"
                rows="4"
                placeholder="collection_date=2026-01-01, location=HZ"
              />
              <p class="field__hint">每行或逗号分隔的 k=v；字段白名单由记录任务校验。</p>
            </div>
          </template>

          <template v-else-if="active === 'lab'">
            <div class="field">
              <label class="field__label" for="lab-strain">菌株 ID</label>
              <input id="lab-strain" v-model="lab.strain_id" class="input" required autocomplete="off" />
            </div>
            <div class="field">
              <label class="field__label" for="lab-cat">类别</label>
              <input id="lab-cat" v-model="lab.category" class="input" required autocomplete="off" />
            </div>
            <div class="field">
              <label class="field__label" for="lab-test">检验项目</label>
              <input id="lab-test" v-model="lab.test_name" class="input" required autocomplete="off" />
            </div>
            <div class="field">
              <label class="field__label" for="lab-result">结果</label>
              <input id="lab-result" v-model="lab.result" class="input" required autocomplete="off" />
            </div>
            <div class="field">
              <label class="field__label" for="lab-unit">
                单位
                <span class="field__optional">可选</span>
              </label>
              <input id="lab-unit" v-model="lab.unit" class="input" autocomplete="off" />
            </div>
          </template>

          <template v-else-if="active === 'knowledge-import'">
            <div class="field">
              <label class="field__label" for="kb-title">标题</label>
              <input id="kb-title" v-model="knowledge.title" class="input" required autocomplete="off" />
            </div>
            <div class="field">
              <label class="field__label" for="kb-ident">来源标识</label>
              <input id="kb-ident" v-model="knowledge.identifier" class="input input--mono" required autocomplete="off" />
            </div>
            <div class="field">
              <label class="field__label" for="kb-content">正文</label>
              <textarea id="kb-content" v-model="knowledge.content" class="textarea" rows="6" required />
            </div>
          </template>

          <template v-else>
            <div class="field">
              <label class="field__label" for="kb-entry">知识条目 ID</label>
              <input
                id="kb-entry"
                v-model="approve.entry_id"
                class="input input--mono"
                inputmode="numeric"
                required
                autocomplete="off"
              />
              <p class="field__hint">审核通过后条目才进入知识库。</p>
            </div>
          </template>

          <div class="form__actions">
            <button class="btn btn--primary" type="submit" :disabled="busy">
              <span v-if="busy" class="spinner" />
              <Icon v-else name="plus" />
              提交记录任务
            </button>
          </div>
        </form>
      </section>

      <section class="card">
        <div class="card__head">
          <h2 class="card__title">最近记录任务</h2>
          <span class="card__hint">{{ recent.length }} 条</span>
        </div>
        <div v-if="loading" class="card__body"><div class="skeleton" style="height: 160px" /></div>
        <div v-else-if="recent.length" class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th scope="col">任务</th>
                <th scope="col">状态</th>
                <th scope="col">创建时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="task in recent" :key="task.task_id">
                <td data-label="任务">
                  <RouterLink class="link-cell" :to="`/tasks/${task.task_id}`">
                    {{ shortId(task.task_id) }}
                  </RouterLink>
                </td>
                <td data-label="状态"><StatusBadge :state="task.state" /></td>
                <td data-label="创建时间">
                  <span class="mono muted">{{ fmtTime(task.created_at) }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <EmptyState
          v-else
          title="还没有记录任务"
          hint="提交一条元数据或化验结果，任务会经过同一套证据链。"
          icon="records"
        />
      </section>
    </div>
  </div>
</template>
