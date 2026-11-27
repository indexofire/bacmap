<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import CopyButton from '../components/CopyButton.vue'
import KeyValueEditor from '../components/KeyValueEditor.vue'
import LabResultEditor from '../components/LabResultEditor.vue'
import { api } from '../api'
import { requireSucceeded, waitForTask } from '../lib/tasks'
import type {
  AuthStatus,
  IsolateDetail,
  LabResultRow,
  LibraryRow,
  WetlabWriteResult,
} from '../types'

const route = useRoute()
const router = useRouter()
const id = String(route.params.id)

const data = ref<IsolateDetail | null>(null)
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

const isolate = computed(() => data.value?.isolate ?? null)
const specimen = computed(() => data.value?.specimen ?? null)
const libraries = computed(() => data.value?.libraries ?? [])
const METADATA_FIELDS = new Set([
  'sample_id',
  'submitting_lab',
  'submit_date',
  'receiver',
  'patient_id',
  'patient_name',
  'patient_age',
  'patient_gender',
  'patient_phone',
  'isolation_date',
  'province',
  'city',
  'district',
  'facility',
  'sample_source',
  'sample_type',
  'food_category',
  'food_name',
  'collection_date',
  'symptoms',
  'onset_date',
  'diagnosis',
  'outcome',
  'hospital',
  'outbreak_id',
  'cluster_note',
])
const metadataLabels: Record<string, string> = {
  sample_id: '样本编号',
  submitting_lab: '送检单位',
  submit_date: '送检日期',
  receiver: '接收人',
  patient_id: '患者编号',
  patient_name: '患者姓名',
  patient_age: '年龄',
  patient_gender: '性别',
  patient_phone: '电话',
  isolation_date: '分离日期',
  province: '省份',
  city: '城市',
  district: '区县',
  facility: '机构',
  sample_source: '样本来源',
  sample_type: '样本类型',
  food_category: '食品类别',
  food_name: '食品名称',
  collection_date: '采集日期',
  symptoms: '症状',
  onset_date: '发病日期',
  diagnosis: '诊断',
  outcome: '转归',
  hospital: '医院',
  outbreak_id: '暴发编号',
  cluster_note: '聚集性备注',
}

function metadataLabel(key: string): string {
  return metadataLabels[key] ?? key
}

function libraryMeta(lib: LibraryRow): string {
  const meta = lib.metadata
  if (!meta || typeof meta !== 'object') return '—'
  const entries = Object.entries(meta as Record<string, unknown>)
  return entries.length ? entries.map(([key, value]) => `${key}=${String(value)}`).join('；') : '—'
}

function labExtra(lab: LabResultRow): string {
  const extra = lab.extra
  if (!extra || typeof extra !== 'object') return '—'
  const entries = Object.entries(extra as Record<string, unknown>)
  return entries.length ? entries.map(([key, value]) => `${key}=${String(value)}`).join('；') : '—'
}

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
      const sampleId = String(metadataDraft.value.sample_id ?? '')
      await afterTask(
        await api.saveIsolateMetadata(id, metadataDraft.value, sampleId, true),
      )
      notice.value = '菌株湿实验元数据已保存'
    } else {
      const data = { ...metadataDraft.value }
      const sampleId = String(data.sample_id ?? '')
      await api.proposeWetlab({
        kind: 'metadata',
        strain_id: id,
        sample_id: sampleId,
        fields: Object.fromEntries(
          Object.entries(data).filter(
            ([key]) => METADATA_FIELDS.has(key) && key !== 'sample_id',
          ),
        ),
        extra: Object.fromEntries(
          Object.entries(data).filter(
            ([key]) =>
              !METADATA_FIELDS.has(key) &&
              !['sample_id', 'strain_id', 'extra', 'created_at', 'updated_at'].includes(key),
          ),
        ),
        replace: true,
      })
      notice.value = '已提交菌株元数据修改提案，等待审核'
    }
    editingMeta.value = false
  } catch (err) {
    error.value = err instanceof Error ? err.message : '保存菌株元数据失败'
  } finally {
    savingMeta.value = false
  }
}

async function deleteMetadata() {
  if (!window.confirm('删除该菌株的全部湿实验元数据？菌株实体与测序数据不会删除。')) return
  savingMeta.value = true
  error.value = ''
  try {
    if (canWrite.value) {
      await afterTask(await api.deleteIsolateMetadata(id))
      notice.value = '菌株湿实验元数据已删除'
    } else {
      await api.proposeWetlab({ kind: 'metadata_delete', strain_id: id })
      notice.value = '已提交菌株元数据删除提案，等待审核'
    }
    editingMeta.value = false
  } catch (err) {
    error.value = err instanceof Error ? err.message : '删除菌株元数据失败'
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

async function remove() {
  if (!window.confirm(`删除菌株 ${id}？只有无测序数据/元数据/化验/GOM/运行记录的空菌株可以删除。`)) return
  deleting.value = true
  error.value = ''
  try {
    await api.deleteIsolate(id)
    await router.push('/isolates')
  } catch (err) {
    error.value = err instanceof Error ? err.message : '删除菌株失败'
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
        <button
          v-if="isolate && canWrite"
          class="btn btn--danger"
          type="button"
          :disabled="deleting"
          title="仅空菌株可删除"
          @click="remove"
        >
          <span v-if="deleting" class="spinner" />
          <Icon v-else name="trash" />
          删除菌株
        </button>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>
    <div v-if="notice" class="card__hint" style="margin-bottom: 16px">{{ notice }}</div>
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

          <section class="card">
            <div class="card__head">
              <h2 class="card__title">湿实验元数据</h2>
              <div class="inline-actions">
                <span class="card__hint">菌株级背景信息</span>
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
                <p class="card__hint">保存会全量替换该菌株的湿实验字段；删除字段即清空。</p>
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
            <div v-else-if="data?.metadata" class="card__body">
              <dl class="statuslist">
                <div
                  v-for="(value, key) in data.metadata"
                  :key="key"
                  class="statuslist__row"
                >
                  <dt>{{ metadataLabel(String(key)) }}</dt>
                  <dd class="mono">{{ typeof value === 'object' ? JSON.stringify(value) : value }}</dd>
                </div>
              </dl>
            </div>
            <div v-else class="card__body">
              <p class="muted">尚未录入该菌株的湿实验元数据。</p>
              <p class="card__hint">
                可在此页直接编辑，或从 XLSX/CSV/TSV 批量导入：
                <code>bacmap record import &lt;文件&gt;</code>。
              </p>
            </div>
          </section>

          <section class="card">
            <div class="card__head">
              <h2 class="card__title">化验结果</h2>
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
                      <th scope="col">方法</th>
                      <th scope="col">判读</th>
                      <th scope="col">标准</th>
                      <th scope="col">实验室</th>
                      <th scope="col">日期</th>
                      <th scope="col">其他</th>
                      <th scope="col">备注</th>
                      <th v-if="canEdit" scope="col">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="lab in data.lab_results" :key="lab.id">
                      <td data-label="类别">{{ lab.category }}</td>
                      <td data-label="项目">{{ lab.test_name }}</td>
                      <td data-label="结果" class="mono">{{ lab.result }}</td>
                      <td data-label="单位">{{ lab.unit || '—' }}</td>
                      <td data-label="方法">{{ lab.method || '—' }}</td>
                      <td data-label="判读">{{ lab.interpretation || '—' }}</td>
                      <td data-label="标准">{{ lab.standard || '—' }}</td>
                      <td data-label="实验室">{{ lab.lab || '—' }}</td>
                      <td data-label="日期">{{ lab.tested_date || '—' }}</td>
                      <td data-label="其他" class="muted">{{ labExtra(lab) }}</td>
                      <td data-label="备注" class="muted">{{ lab.notes || '—' }}</td>
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
              <p class="muted">尚未录入该菌株的化验/药敏结果。</p>
              <p class="card__hint">
                可在此页新增，或使用同一导入命令的 <code>lab</code>/<code>化验</code> 工作表。
              </p>
            </div>
            <LabResultEditor
              v-if="labOpen && canEdit"
              :key="labEditing?.id ?? 'new'"
              subject-type="isolate"
              :subject-id="id"
              :initial="labEditing"
              :proposal="!canWrite"
              @saved="labSaved"
              @cancel="labOpen = false; labEditing = null"
            />
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
                    <tr><th scope="col">测序数据</th><th scope="col">平台</th><th scope="col">元数据</th><th scope="col">操作</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="lib in libraries" :key="lib.library_id">
                      <td data-label="测序数据"><code>{{ lib.library_id }}</code></td>
                      <td data-label="平台">{{ lib.platform || '—' }}</td>
                      <td data-label="元数据" class="muted">{{ libraryMeta(lib) }}</td>
                      <td data-label="操作">
                        <div class="inline-actions">
                          <RouterLink class="btn btn--ghost btn--sm" :to="`/samples/${lib.library_id}`">
                            查看结果
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
            <div v-else class="card__body"><p class="muted">该菌株暂无登记测序数据。</p></div>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>
