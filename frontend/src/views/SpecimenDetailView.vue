<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import CopyButton from '../components/CopyButton.vue'
import EmptyState from '../components/EmptyState.vue'
import KeyValueEditor from '../components/KeyValueEditor.vue'
import LabResultEditor from '../components/LabResultEditor.vue'
import { api } from '../api'
import { requireSucceeded, waitForTask } from '../lib/tasks'
import type {
  AuthStatus,
  LabResultRow,
  LibraryRow,
  SpecimenDetail,
  WetlabWriteResult,
} from '../types'

const route = useRoute()
const router = useRouter()
const id = String(route.params.id)

const data = ref<SpecimenDetail | null>(null)
const loading = ref(true)
const error = ref('')
const deleting = ref(false)
const auth = ref<AuthStatus | null>(null)
const editingMeta = ref(false)
const metadataDraft = ref<Record<string, unknown>>({})
const savingMeta = ref(false)
const labOpen = ref(false)
const labEditing = ref<LabResultRow | null>(null)
const libraryEditing = ref('')
const libraryDraft = ref<Record<string, unknown>>({})
const savingLibrary = ref(false)
const assignIsolates = ref('')
const assignDatasets = ref('')
const assigning = ref(false)
const notice = ref('')

const canWrite = computed(() => {
  const value = auth.value
  if (!value || !value.enabled) return true
  if (value.mode === 'accounts' || value.mode === 'personal') {
    return value.role === 'admin' || value.role === 'analyst'
  }
  // bearer / cookie 单令牌部署：部署令牌即操作员。
  return true
})
const canPropose = computed(
  () => auth.value?.mode === 'accounts' && auth.value.role === 'user',
)
const canEdit = computed(() => canWrite.value || canPropose.value)

const specimen = computed(() => data.value?.specimen ?? null)
const isolates = computed(() => data.value?.isolates ?? [])
const hasIsolates = computed(() => isolates.value.length > 0)

function libraryMeta(lib: LibraryRow): string {
  const meta = lib.metadata
  if (!meta || typeof meta !== 'object') return '—'
  const entries = Object.entries(meta as Record<string, unknown>)
  return entries.length ? entries.map(([key, value]) => `${key}=${String(value)}`).join('；') : '—'
}

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

async function afterTask(result: WetlabWriteResult) {
  requireSucceeded(await waitForTask(result.task_id))
  await load()
}

function startMetadataEdit() {
  metadataDraft.value = { ...(data.value?.metadata ?? {}) }
  editingMeta.value = true
  notice.value = ''
}

async function saveMetadata() {
  savingMeta.value = true
  error.value = ''
  try {
    if (canWrite.value) {
      await afterTask(await api.saveSpecimenMetadata(id, metadataDraft.value, true))
      notice.value = '样本湿实验信息已保存'
    } else {
      await api.proposeWetlab({
        kind: 'specimen_metadata',
        specimen_id: id,
        data: metadataDraft.value,
        replace: true,
      })
      notice.value = '已提交样本信息修改提案，等待审核'
    }
    editingMeta.value = false
  } catch (err) {
    error.value = err instanceof Error ? err.message : '保存样本元数据失败'
  } finally {
    savingMeta.value = false
  }
}

async function deleteMetadata() {
  if (!window.confirm('删除该样本的全部湿实验元数据？样本实体、菌株与测序数据不会删除。')) return
  savingMeta.value = true
  error.value = ''
  try {
    if (canWrite.value) {
      await afterTask(await api.deleteSpecimenMetadata(id))
      notice.value = '样本湿实验信息已删除'
    } else {
      await api.proposeWetlab({
        kind: 'specimen_metadata_delete',
        specimen_id: id,
      })
      notice.value = '已提交删除提案，等待审核'
    }
    editingMeta.value = false
  } catch (err) {
    error.value = err instanceof Error ? err.message : '删除样本元数据失败'
  } finally {
    savingMeta.value = false
  }
}

function openNewLab() {
  labEditing.value = null
  labOpen.value = true
}

function editLab(lab: LabResultRow) {
  labEditing.value = lab
  labOpen.value = true
}

async function labSaved() {
  labOpen.value = false
  labEditing.value = null
  notice.value = canWrite.value
    ? '化验结果已保存'
    : '已提交化验结果修改提案，等待审核'
  await load()
}

async function removeLab(lab: LabResultRow) {
  if (!window.confirm(`删除化验结果 ${lab.category} / ${lab.test_name}？`)) return
  error.value = ''
  try {
    if (canWrite.value) {
      await afterTask(await api.deleteLabResult(lab.id))
      notice.value = '化验结果已删除'
    } else {
      await api.proposeWetlab({ kind: 'lab_result_delete', result_id: lab.id })
      notice.value = '已提交化验结果删除提案，等待审核'
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : '删除化验结果失败'
  }
}

function editLibrary(lib: LibraryRow) {
  libraryEditing.value = lib.library_id
  libraryDraft.value = { ...(lib.metadata ?? {}) }
  notice.value = ''
}

async function saveLibrary() {
  savingLibrary.value = true
  error.value = ''
  try {
    if (canWrite.value) {
      await afterTask(
        await api.saveLibraryMetadata(libraryEditing.value, libraryDraft.value, true),
      )
      notice.value = '测序数据元数据已保存'
    } else {
      await api.proposeWetlab({
        kind: 'library_metadata',
        library_id: libraryEditing.value,
        data: libraryDraft.value,
        replace: true,
      })
      notice.value = '已提交测序元数据修改提案，等待审核'
    }
    libraryEditing.value = ''
  } catch (err) {
    error.value = err instanceof Error ? err.message : '保存测序数据元数据失败'
  } finally {
    savingLibrary.value = false
  }
}

async function deleteLibrary(lib: LibraryRow) {
  if (!window.confirm(`删除测序数据 ${lib.library_id} 的附加元数据？（不影响测序文件与结果）`)) return
  error.value = ''
  try {
    if (canWrite.value) {
      await afterTask(await api.deleteLibraryMetadata(lib.library_id))
      notice.value = '测序数据元数据已删除'
    } else {
      await api.proposeWetlab({
        kind: 'library_metadata_delete',
        library_id: lib.library_id,
      })
      notice.value = '已提交测序元数据删除提案，等待审核'
    }
    if (libraryEditing.value === lib.library_id) libraryEditing.value = ''
  } catch (err) {
    error.value = err instanceof Error ? err.message : '删除测序数据元数据失败'
  }
}

function splitIds(raw: string): string[] {
  return raw.split(/[\s,，]+/).map((item) => item.trim()).filter(Boolean)
}

async function assign() {
  const isolates = splitIds(assignIsolates.value)
  const datasets = splitIds(assignDatasets.value)
  if (!isolates.length && !datasets.length) return
  assigning.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await api.assignSpecimenTask(id, isolates, datasets)
    requireSucceeded(await waitForTask(result.task_id))
    notice.value = '关联记录任务已完成'
    assignIsolates.value = ''
    assignDatasets.value = ''
    await load()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '关联失败'
  } finally {
    assigning.value = false
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

onMounted(async () => {
  try {
    auth.value = await api.authStatus()
  } catch {
    // 旧服务端没有 auth/status 时按可信部署处理。
  }
  await load()
})
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
          v-if="specimen && !loading && canWrite"
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
    <div v-if="notice" class="card__hint" style="margin-bottom: 16px">{{ notice }}</div>
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

          <section v-if="canWrite" class="card">
            <div class="card__head">
              <h2 class="card__title">关联菌株 / 测序数据</h2>
              <span class="card__hint">关联到样本 {{ id }}</span>
            </div>
            <form class="card__body form" @submit.prevent="assign">
              <div class="field">
                <label class="field__label">菌株 ID</label>
                <input v-model="assignIsolates" class="input" placeholder="ISO-1, ISO-2" />
              </div>
              <div class="field">
                <label class="field__label">测序数据 ID</label>
                <input v-model="assignDatasets" class="input" placeholder="LIB-1, LIB-2" />
              </div>
              <p class="card__hint">多个 ID 用空格或逗号分隔；已关联到其他样本的数据不会被静默改写。</p>
              <div class="form__actions">
                <button
                  class="btn btn--primary"
                  type="submit"
                  :disabled="assigning || (!assignIsolates.trim() && !assignDatasets.trim())"
                >
                  <span v-if="assigning" class="spinner" />
                  <Icon v-else name="plus" />
                  关联
                </button>
              </div>
            </form>
          </section>

          <section class="card">
            <div class="card__head">
              <h2 class="card__title">样本湿实验信息</h2>
              <div class="inline-actions">
                <span class="card__hint">患者/采样/来源</span>
                <button
                  v-if="canEdit && !editingMeta"
                  class="btn btn--ghost btn--sm"
                  type="button"
                  @click="startMetadataEdit"
                >
                  <Icon name="plus" />
                  编辑
                </button>
              </div>
            </div>
            <div v-if="editingMeta && canEdit" class="card__body">
              <form class="form" @submit.prevent="saveMetadata">
                <KeyValueEditor v-model="metadataDraft" :disabled="savingMeta" />
                <p class="card__hint">保存会全量替换该样本的湿实验字段；删除字段即清空。</p>
                <div class="form__actions">
                  <button class="btn btn--primary" type="submit" :disabled="savingMeta">
                    <span v-if="savingMeta" class="spinner" />
                    <Icon v-else name="check" />
                    保存
                  </button>
                  <button
                    class="btn btn--ghost"
                    type="button"
                    :disabled="savingMeta"
                    @click="editingMeta = false"
                  >
                    取消
                  </button>
                  <button
                    class="btn btn--danger"
                    type="button"
                    :disabled="savingMeta"
                    @click="deleteMetadata"
                  >
                    删除全部
                  </button>
                </div>
              </form>
            </div>
            <div v-else-if="data?.metadata && Object.keys(data.metadata).length" class="card__body">
              <dl class="statuslist">
                <div v-for="(value, key) in data.metadata" :key="key" class="statuslist__row">
                  <dt>{{ key }}</dt>
                  <dd class="mono">{{ typeof value === 'object' ? JSON.stringify(value) : value }}</dd>
                </div>
              </dl>
            </div>
            <div v-else class="card__body">
              <p class="muted">尚未录入该样本的湿实验信息。</p>
              <p class="card__hint">
                可在此页直接编辑，或从 XLSX/CSV/TSV 批量导入：
                <code>bacmap record import &lt;文件&gt;</code>。
              </p>
            </div>
          </section>

          <section class="card">
            <div class="card__head">
              <h2 class="card__title">样本级化验结果</h2>
              <div class="inline-actions">
                <span class="card__hint">{{ data?.lab_results?.length ?? 0 }} 条</span>
                <button
                  v-if="canEdit && !labOpen"
                  class="btn btn--ghost btn--sm"
                  type="button"
                  @click="openNewLab"
                >
                  <Icon name="plus" />
                  新增
                </button>
              </div>
            </div>
            <div v-if="data?.lab_results?.length" class="card__body">
              <div class="table-wrap">
                <table class="table">
                  <thead>
                    <tr>
                      <th scope="col">类别</th>
                      <th scope="col">项目</th>
                      <th scope="col">结果</th>
                      <th scope="col">单位</th>
                      <th scope="col">判读</th>
                      <th scope="col">日期</th>
                      <th v-if="canEdit" scope="col">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="lab in data.lab_results" :key="lab.id">
                      <td data-label="类别">{{ lab.category }}</td>
                      <td data-label="项目">{{ lab.test_name }}</td>
                      <td data-label="结果" class="mono">{{ lab.result }}</td>
                      <td data-label="单位">{{ lab.unit || '—' }}</td>
                      <td data-label="判读">{{ lab.interpretation || '—' }}</td>
                      <td data-label="日期">{{ lab.tested_date || '—' }}</td>
                      <td v-if="canEdit" data-label="操作">
                        <div class="inline-actions">
                          <button class="btn btn--ghost btn--sm" type="button" @click="editLab(lab)">
                            编辑
                          </button>
                          <button class="btn btn--danger btn--sm" type="button" @click="removeLab(lab)">
                            删除
                          </button>
                        </div>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            <div v-else class="card__body">
              <p class="muted">尚未录入样本级化验结果（如 mNGS 耐药基因）。</p>
            </div>
            <LabResultEditor
              v-if="labOpen && canEdit"
              :key="labEditing?.id ?? 'new'"
              subject-type="specimen"
              :subject-id="id"
              :initial="labEditing"
              :proposal="!canWrite"
              @saved="labSaved"
              @cancel="labOpen = false; labEditing = null"
            />
          </section>

          <section v-if="data?.libraries?.length" class="card">
            <div class="card__head">
              <h2 class="card__title">样本级测序数据</h2>
              <span class="card__hint">{{ data.libraries.length }} 份（mNGS/tNGS）</span>
            </div>
            <div class="card__body">
              <div class="table-wrap">
                <table class="table">
                  <thead>
                    <tr><th scope="col">测序数据</th><th scope="col">平台</th><th scope="col">元数据</th><th scope="col">操作</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="lib in data.libraries" :key="lib.library_id">
                      <td data-label="测序数据"><code>{{ lib.library_id }}</code></td>
                      <td data-label="平台">{{ lib.platform || '—' }}</td>
                      <td data-label="元数据" class="muted">{{ libraryMeta(lib) }}</td>
                      <td data-label="操作">
                        <div class="inline-actions">
                          <RouterLink class="btn btn--ghost btn--sm" :to="`/samples/${lib.library_id}`">
                            查看
                          </RouterLink>
                          <button
                            v-if="canWrite"
                            class="btn btn--ghost btn--sm"
                            type="button"
                            @click="editLibrary(lib)"
                          >
                            编辑元数据
                          </button>
                          <button
                            v-if="canEdit"
                            class="btn btn--danger btn--sm"
                            type="button"
                            @click="deleteLibrary(lib)"
                          >
                            删除元数据
                          </button>
                        </div>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <form
                v-if="canEdit && libraryEditing"
                class="form"
                style="margin-top: 16px"
                @submit.prevent="saveLibrary"
              >
                <div class="card__head">
                  <h3 class="card__title">编辑 {{ libraryEditing }} 的测序元数据</h3>
                  <button class="btn btn--ghost btn--sm" type="button" @click="libraryEditing = ''">
                    关闭
                  </button>
                </div>
                <KeyValueEditor :key="libraryEditing" v-model="libraryDraft" :disabled="savingLibrary" />
                <div class="form__actions">
                  <button class="btn btn--primary" type="submit" :disabled="savingLibrary">
                    <span v-if="savingLibrary" class="spinner" />
                    <Icon v-else name="check" />
                    保存测序元数据
                  </button>
                </div>
              </form>
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
