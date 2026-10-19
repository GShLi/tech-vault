<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, FileJson, Play, Plus, Upload } from 'lucide-vue-next'
import { Message } from '@arco-design/web-vue'

import { api, ApiRequestError, loadAllPages } from '@/api/client'
import StatusPill from '@/components/StatusPill.vue'
import { useTeamStore } from '@/stores/team'
import type {
  EvaluationCase,
  EvaluationDataset,
  EvaluationRun,
  ModelProvider,
} from '@/types/api'
import { formatDate, shortId } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const team = useTeamStore()
const dataset = ref<EvaluationDataset | null>(null)
const cases = ref<EvaluationCase[]>([])
const runs = ref<EvaluationRun[]>([])
const providers = ref<ModelProvider[]>([])
const allowedProviderIds = ref<string[]>([])
const loading = ref(false)
const saving = ref(false)
const loadingProviders = ref(false)
const loadingMoreCases = ref(false)
const loadingMoreRuns = ref(false)
const casesNextCursor = ref<string | null>(null)
const runsNextCursor = ref<string | null>(null)
const casesHasMore = ref(false)
const runsHasMore = ref(false)
const error = ref<ApiRequestError | null>(null)
const showCase = ref(false)
const showImport = ref(false)
const showRun = ref(false)
const queryId = ref('')
const queryType = ref('concept')
const query = ref('')
const relevantChunkIds = ref('')
const importContent = ref('')
const engineMode = ref('dual_engine')
const baselineRunId = ref('')
const selectedProviderId = ref('')
const selectedModelId = ref('')
let providerOptionsRequestGeneration = 0

const eligibleProviders = computed(() => {
  const allowedIds = new Set(allowedProviderIds.value)
  return providers.value.filter(
    (provider) =>
      provider.status === 'active' &&
      provider.has_api_key === true &&
      allowedIds.has(provider.id) &&
      Array.isArray(provider.model_ids) &&
      provider.model_ids.length > 0,
  )
})

const selectedProvider = computed(
  () =>
    eligibleProviders.value.find(
      (provider) => provider.id === selectedProviderId.value,
    ) ?? null,
)

const modelOptions = computed(() =>
  Array.isArray(selectedProvider.value?.model_ids)
    ? selectedProvider.value?.model_ids ?? []
    : [],
)

const hasProviderAndModel = computed(
  () =>
    Boolean(selectedProvider.value) &&
    Boolean(selectedModelId.value) &&
    modelOptions.value.includes(selectedModelId.value),
)

function currentDatasetId(): string {
  return String(route.params.datasetId ?? '')
}

async function load(): Promise<void> {
  if (!team.selectedTeamId || !currentDatasetId()) return
  loading.value = true
  error.value = null
  try {
    const [datasetView, casePage, runPage] = await Promise.all([
      api.getEvalDataset(team.selectedTeamId, currentDatasetId()),
      api.listEvalCases(team.selectedTeamId, currentDatasetId()),
      api.listEvalRuns(team.selectedTeamId, currentDatasetId()),
    ])
    dataset.value = datasetView
    cases.value = casePage.data
    runs.value = runPage.data
    casesNextCursor.value = casePage.meta.next_cursor
    runsNextCursor.value = runPage.meta.next_cursor
    casesHasMore.value = casePage.meta.has_more
    runsHasMore.value = runPage.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loading.value = false
  }
}

async function loadProviderOptions(): Promise<void> {
  const requestGeneration = ++providerOptionsRequestGeneration
  const teamId = team.selectedTeamId
  selectedProviderId.value = ''
  selectedModelId.value = ''
  if (!teamId) {
    providers.value = []
    allowedProviderIds.value = []
    return
  }
  loadingProviders.value = true
  providers.value = []
  allowedProviderIds.value = []
  try {
    const [policy, providerRows] = await Promise.all([
      api.getPolicy(teamId),
      loadAllPages((cursor) => api.listProviders(teamId, cursor, 100)),
    ])
    if (
      requestGeneration !== providerOptionsRequestGeneration ||
      team.selectedTeamId !== teamId
    ) {
      return
    }
    providers.value = providerRows
    allowedProviderIds.value = Array.isArray(policy.allowed_provider_ids)
      ? policy.allowed_provider_ids
      : []
  } catch (caught) {
    if (
      requestGeneration !== providerOptionsRequestGeneration ||
      team.selectedTeamId !== teamId
    ) {
      return
    }
    providers.value = []
    allowedProviderIds.value = []
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    if (requestGeneration === providerOptionsRequestGeneration) {
      loadingProviders.value = false
    }
  }
}

async function openRunModal(): Promise<void> {
  showRun.value = true
  await loadProviderOptions()
}

async function loadMoreCases(): Promise<void> {
  if (!team.selectedTeamId || !casesNextCursor.value) return
  loadingMoreCases.value = true
  try {
    const page = await api.listEvalCases(
      team.selectedTeamId,
      currentDatasetId(),
      casesNextCursor.value,
    )
    cases.value = [...cases.value, ...page.data]
    casesNextCursor.value = page.meta.next_cursor
    casesHasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loadingMoreCases.value = false
  }
}

async function loadMoreRuns(): Promise<void> {
  if (!team.selectedTeamId || !runsNextCursor.value) return
  loadingMoreRuns.value = true
  try {
    const page = await api.listEvalRuns(
      team.selectedTeamId,
      currentDatasetId(),
      runsNextCursor.value,
    )
    runs.value = [...runs.value, ...page.data]
    runsNextCursor.value = page.meta.next_cursor
    runsHasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loadingMoreRuns.value = false
  }
}

async function createCase(): Promise<void> {
  if (!team.selectedTeamId) return
  saving.value = true
  error.value = null
  try {
    await api.createEvalCase({
      team_id: team.selectedTeamId,
      dataset_id: currentDatasetId(),
      query_id: queryId.value.trim(),
      query_type: queryType.value,
      query: query.value.trim(),
      relevant_chunk_ids: relevantChunkIds.value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean),
      filters: {},
      relevance: {},
    })
    Message.success('评测样本已创建')
    showCase.value = false
    await load()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    saving.value = false
  }
}

async function importCases(): Promise<void> {
  if (!team.selectedTeamId) return
  saving.value = true
  error.value = null
  try {
    const result = await api.importEvalCases(team.selectedTeamId, currentDatasetId(), importContent.value)
    Message.success(`已导入 ${result.imported} 条样本`)
    showImport.value = false
    importContent.value = ''
    await load()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    saving.value = false
  }
}

async function deleteCase(item: EvaluationCase): Promise<void> {
  if (!team.selectedTeamId) return
  try {
    await api.deleteEvalCase(team.selectedTeamId, item.id)
    Message.success('样本已删除')
    await load()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  }
}

async function startRun(): Promise<void> {
  if (!team.selectedTeamId || !hasProviderAndModel.value) return
  saving.value = true
  error.value = null
  try {
    const created = await api.startEvalRun({
      team_id: team.selectedTeamId,
      dataset_id: currentDatasetId(),
      provider_id: selectedProviderId.value,
      model_id: selectedModelId.value,
      engine_mode: engineMode.value,
      baseline_run_id: baselineRunId.value || null,
    })
    Message.success('评测任务已启动')
    showRun.value = false
    router.push(`/evaluations/runs/${created.id}`)
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    saving.value = false
  }
}

watch(selectedProviderId, () => {
  if (!modelOptions.value.includes(selectedModelId.value)) {
    selectedModelId.value = ''
  }
})

watch(
  () => team.selectedTeamId,
  async () => {
    await load()
    await loadProviderOptions()
  },
)

onMounted(async () => {
  await load()
  await loadProviderOptions()
})
watch(() => route.params.datasetId, load)
</script>

<template>
  <div>
    <div class="page-header">
      <div class="heading-with-back">
        <RouterLink class="icon-button" to="/evaluations" title="返回评测列表">
          <ArrowLeft :size="18" />
        </RouterLink>
        <div>
          <h2>{{ dataset?.name || '黄金集详情' }}</h2>
          <p>{{ dataset?.description || '查询、相关性标注与运行记录。' }}</p>
        </div>
      </div>
      <div v-if="team.canManage" class="row-actions">
        <button class="secondary-button" type="button" @click="showImport = true">
          <Upload :size="16" />
          导入
        </button>
        <button class="secondary-button" type="button" @click="showCase = true">
          <Plus :size="16" />
          新增样本
        </button>
        <button
          class="primary-button"
          type="button"
          data-testid="open-evaluation-run"
          @click="openRunModal"
        >
          <Play :size="16" />
          启动评测
        </button>
      </div>
    </div>

    <div v-if="error" class="error-banner" role="alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
    </div>

    <div v-if="loading && !dataset" class="panel loading-state"><a-spin /><span>正在加载黄金集</span></div>
    <template v-else-if="dataset">
      <div class="metric-grid">
        <article class="metric-card"><span>样本数量</span><strong>{{ dataset.case_count }}</strong></article>
        <article class="metric-card"><span>数据集版本</span><strong>v{{ dataset.version }}</strong></article>
        <article class="metric-card"><span>运行次数</span><strong>{{ runs.length }}</strong></article>
      </div>

      <section class="panel detail-panel">
        <div class="section-heading"><h3>查询样本</h3><span class="muted-text">相关 Chunk 用于计算检索指标</span></div>
        <div v-if="cases.length" class="table-wrap">
          <table>
            <thead><tr><th>Query ID</th><th>类型</th><th>查询</th><th>相关 Chunk</th><th v-if="team.canManage">操作</th></tr></thead>
            <tbody>
              <tr v-for="item in cases" :key="item.id">
                <td>{{ item.query_id || shortId(item.id) }}</td>
                <td>{{ item.query_type }}</td>
                <td>{{ item.query }}</td>
                <td>{{ item.relevant_chunk_ids.length }}</td>
                <td v-if="team.canManage">
                  <button class="ghost-button danger-text" type="button" @click="deleteCase(item)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty-state compact"><FileJson :size="22" /><span>暂无评测样本</span></div>
        <div v-if="casesHasMore" class="load-more">
          <button class="secondary-button" type="button" :disabled="loadingMoreCases" @click="loadMoreCases">
            {{ loadingMoreCases ? '加载中' : '加载更多样本' }}
          </button>
        </div>
      </section>

      <section class="panel detail-panel">
        <div class="section-heading"><h3>运行记录</h3></div>
        <div v-if="runs.length" class="table-wrap">
          <table>
            <thead><tr><th>运行</th><th>引擎</th><th>状态</th><th>开始时间</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="runItem in runs" :key="runItem.id">
                <td>{{ shortId(runItem.id) }}</td>
                <td>{{ runItem.engine_mode }}</td>
                <td><StatusPill :status="runItem.status" /></td>
                <td>{{ formatDate(runItem.created_at) }}</td>
                <td><RouterLink class="ghost-button" :to="`/evaluations/runs/${runItem.id}`">查看报告</RouterLink></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty-state compact"><Play :size="22" /><span>尚未运行评测</span></div>
        <div v-if="runsHasMore" class="load-more">
          <button class="secondary-button" type="button" :disabled="loadingMoreRuns" @click="loadMoreRuns">
            {{ loadingMoreRuns ? '加载中' : '加载更多运行' }}
          </button>
        </div>
      </section>
    </template>

    <div v-if="showCase" class="modal-backdrop" @click.self="showCase = false">
      <div class="modal-panel">
        <div class="modal-heading"><h3>新增评测样本</h3><button class="icon-button" type="button" @click="showCase = false">×</button></div>
        <form class="form-stack" @submit.prevent="createCase">
          <label class="field"><span>Query ID</span><input v-model="queryId" type="text" required /></label>
          <label class="field"><span>查询类型</span><select v-model="queryType"><option value="concept">概念</option><option value="comparison">对比</option><option value="troubleshooting">排障</option></select></label>
          <label class="field"><span>查询</span><textarea v-model="query" rows="3" required /></label>
          <label class="field"><span>相关 Chunk ID（逗号或换行分隔）</span><textarea v-model="relevantChunkIds" rows="3" /></label>
          <div class="modal-actions"><button class="ghost-button" type="button" @click="showCase = false">取消</button><button class="primary-button" type="submit" :disabled="saving">保存</button></div>
        </form>
      </div>
    </div>

    <div v-if="showImport" class="modal-backdrop" @click.self="showImport = false">
      <div class="modal-panel">
        <div class="modal-heading"><h3>导入 JSONL</h3><button class="icon-button" type="button" @click="showImport = false">×</button></div>
        <form class="form-stack" @submit.prevent="importCases">
          <label class="field"><span>每行一个评测样本</span><textarea v-model="importContent" rows="10" placeholder='{"query_id":"q-1","query_type":"concept","query":"如何配置检索？","relevant_chunk_ids":[]}' /></label>
          <div class="modal-actions"><button class="ghost-button" type="button" @click="showImport = false">取消</button><button class="primary-button" type="submit" :disabled="saving || !importContent.trim()">导入</button></div>
        </form>
      </div>
    </div>

    <div v-if="showRun" class="modal-backdrop" @click.self="showRun = false">
      <div class="modal-panel">
        <div class="modal-heading"><h3>启动评测</h3><button class="icon-button" type="button" @click="showRun = false">×</button></div>
        <form class="form-stack" @submit.prevent="startRun">
          <label class="field">
            <span>供应商</span>
            <select
              v-model="selectedProviderId"
              data-testid="run-provider-select"
              :disabled="loadingProviders || !eligibleProviders.length"
              required
            >
              <option value="">选择供应商</option>
              <option v-for="provider in eligibleProviders" :key="provider.id" :value="provider.id">
                {{ provider.name }}
              </option>
            </select>
          </label>
          <label class="field">
            <span>模型</span>
            <select
              v-model="selectedModelId"
              data-testid="run-model-select"
              :disabled="!selectedProvider"
              required
            >
              <option value="">选择模型</option>
              <option v-for="model in modelOptions" :key="model" :value="model">
                {{ model }}
              </option>
            </select>
          </label>
          <label class="field"><span>检索引擎</span><select v-model="engineMode"><option value="dual_engine">ES + Qdrant 双引擎</option><option value="elastic_single">Elasticsearch 单引擎</option></select></label>
          <label class="field"><span>基线运行 ID（可选）</span><input v-model="baselineRunId" type="text" /></label>
          <div class="modal-actions"><button class="ghost-button" type="button" @click="showRun = false">取消</button><button class="primary-button" type="submit" data-testid="run-start-submit" :disabled="saving || !hasProviderAndModel"><Play :size="16" />启动</button></div>
        </form>
      </div>
    </div>
  </div>
</template>
