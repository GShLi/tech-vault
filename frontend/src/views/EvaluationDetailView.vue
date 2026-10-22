<script setup lang="ts">
import { useProviderSelection } from '@/composables/useProviderSelection'
import {
  ApiRequestError,
  api,
  loadAllPages,
  normalizeApiError,
} from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Card as ACard,
  Empty as AEmpty,
  Form as AForm,
  FormItem as AFormItem,
  Input as AInput,
  Message,
  Modal as AModal,
  Option as AOption,
  Select as ASelect,
  Spin as ASpin,
  Table as ATable,
  TableColumn as ATableColumn,
  Tag as ATag,
  Textarea as ATextarea,
} from '@arco-design/web-vue'

import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, FileJson, Play, Plus, Upload } from 'lucide-vue-next'

import { statusColor } from '@/utils/status'
import { useTeamStore } from '@/stores/team'
import type {
  EvaluationCase,
  EvaluationDataset,
  EvaluationRun,
  ModelProvider,
} from '@/types/api'
import { formatDate, shortId, statusLabel } from '@/utils/format'

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
const {
  selectedProviderId,
  selectedModelId,
  eligibleProviders,
  selectedProvider,
  modelOptions,
  hasProviderAndModel,
} = useProviderSelection(providers, allowedProviderIds)
let providerOptionsRequestGeneration = 0

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
    error.value = normalizeApiError(caught)
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
    error.value = normalizeApiError(caught)
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
    error.value = normalizeApiError(caught)
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
    error.value = normalizeApiError(caught)
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
      relevant_chunk_ids: relevantChunkIds.value
        .split(/[\n,]/)
        .map((item) => item.trim())
        .filter(Boolean),
      filters: {},
      relevance: {},
    })
    Message.success('评测样本已创建')
    showCase.value = false
    await load()
  } catch (caught) {
    error.value = normalizeApiError(caught)
  } finally {
    saving.value = false
  }
}

async function importCases(): Promise<void> {
  if (!team.selectedTeamId) return
  saving.value = true
  error.value = null
  try {
    const result = await api.importEvalCases(
      team.selectedTeamId,
      currentDatasetId(),
      importContent.value,
    )
    Message.success(`已导入 ${result.imported} 条样本`)
    showImport.value = false
    importContent.value = ''
    await load()
  } catch (caught) {
    error.value = normalizeApiError(caught)
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
    error.value = normalizeApiError(caught)
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
    error.value = normalizeApiError(caught)
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
        <RouterLink to="/evaluations" custom v-slot="{ href, navigate }">
          <a-button
            type="text"
            :href="href"
            @click="navigate"
            title="返回评测列表"
          >
            <ArrowLeft :size="18" />
          </a-button>
        </RouterLink>
        <div>
          <h2>{{ dataset?.name || '黄金集详情' }}</h2>
          <p>{{ dataset?.description || '查询、相关性标注与运行记录。' }}</p>
        </div>
      </div>
      <div v-if="team.canManage" class="row-actions">
        <a-button
          @click="showImport = true"
          type="secondary"
          html-type="button"
        >
          <Upload :size="16" />
          导入
        </a-button>
        <a-button @click="showCase = true" type="secondary" html-type="button">
          <Plus :size="16" />
          新增样本
        </a-button>
        <a-button
          data-testid="open-evaluation-run"
          @click="openRunModal"
          type="primary"
          html-type="button"
        >
          <Play :size="16" />
          启动评测
        </a-button>
      </div>
    </div>

    <a-alert v-if="error" type="error" class="page-alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
    </a-alert>

    <div v-if="loading && !dataset" class="panel loading-state">
      <a-spin />
      <span>正在加载黄金集</span>
    </div>
    <template v-else-if="dataset">
      <div class="metric-grid">
        <article class="metric-card">
          <span>样本数量</span>
          <strong>{{ dataset.case_count }}</strong>
        </article>
        <article class="metric-card">
          <span>数据集版本</span>
          <strong>v{{ dataset.version }}</strong>
        </article>
        <article class="metric-card">
          <span>运行次数</span>
          <strong>{{ runs.length }}</strong>
        </article>
      </div>

      <a-card class="page-card">
        <div class="section-heading">
          <h3>查询样本</h3>
          <span class="muted-text">相关 Chunk 用于计算检索指标</span>
        </div>
        <div v-if="cases.length" class="table-wrap">
          <a-table
            :data="cases"
            :pagination="false"
            row-key="id"
            :bordered="false"
            :scroll="{ x: 960 }"
          >
            <template #columns>
              <a-table-column title="Query ID">
                <template #cell="{ record: item }">
                  {{ item.query_id || shortId(item.id) }}
                </template>
              </a-table-column>
              <a-table-column title="类型">
                <template #cell="{ record: item }">
                  {{ item.query_type }}
                </template>
              </a-table-column>
              <a-table-column title="查询">
                <template #cell="{ record: item }">{{ item.query }}</template>
              </a-table-column>
              <a-table-column title="相关 Chunk">
                <template #cell="{ record: item }">
                  {{ item.relevant_chunk_ids.length }}
                </template>
              </a-table-column>
              <a-table-column v-if="team.canManage" title="操作" :width="180">
                <template #cell="{ record: item }">
                  <a-button
                    @click="deleteCase(item)"
                    type="text"
                    html-type="button"
                    status="danger"
                  >
                    删除
                  </a-button>
                </template>
              </a-table-column>
            </template>
          </a-table>
        </div>
        <a-empty v-else class="page-empty">
          <template #image><FileJson :size="22" /></template>
          <span>暂无评测样本</span>
        </a-empty>
        <div v-if="casesHasMore" class="load-more">
          <a-button
            :disabled="loadingMoreCases"
            @click="loadMoreCases"
            type="secondary"
            html-type="button"
          >
            {{ loadingMoreCases ? '加载中' : '加载更多样本' }}
          </a-button>
        </div>
      </a-card>

      <a-card class="page-card">
        <div class="section-heading"><h3>运行记录</h3></div>
        <div v-if="runs.length" class="table-wrap">
          <a-table
            :data="runs"
            :pagination="false"
            row-key="id"
            :bordered="false"
            :scroll="{ x: 960 }"
          >
            <template #columns>
              <a-table-column title="运行">
                <template #cell="{ record: runItem }">
                  {{ shortId(runItem.id) }}
                </template>
              </a-table-column>
              <a-table-column title="引擎">
                <template #cell="{ record: runItem }">
                  {{ runItem.engine_mode }}
                </template>
              </a-table-column>
              <a-table-column title="状态" :width="100">
                <template #cell="{ record: runItem }">
                  <a-tag :color="statusColor(runItem.status)">
                    {{ statusLabel(runItem.status) }}
                  </a-tag>
                </template>
              </a-table-column>
              <a-table-column title="开始时间" :width="180">
                <template #cell="{ record: runItem }">
                  {{ formatDate(runItem.created_at) }}
                </template>
              </a-table-column>
              <a-table-column title="操作" :width="180">
                <template #cell="{ record: runItem }">
                  <RouterLink
                    :to="`/evaluations/runs/${runItem.id}`"
                    custom
                    v-slot="{ href, navigate }"
                  >
                    <a-button type="text" :href="href" @click="navigate">
                      查看报告
                    </a-button>
                  </RouterLink>
                </template>
              </a-table-column>
            </template>
          </a-table>
        </div>
        <a-empty v-else class="page-empty">
          <template #image><Play :size="22" /></template>
          <span>尚未运行评测</span>
        </a-empty>
        <div v-if="runsHasMore" class="load-more">
          <a-button
            :disabled="loadingMoreRuns"
            @click="loadMoreRuns"
            type="secondary"
            html-type="button"
          >
            {{ loadingMoreRuns ? '加载中' : '加载更多运行' }}
          </a-button>
        </div>
      </a-card>
    </template>

    <a-modal
      v-if="showCase"
      :visible="true"
      :footer="false"
      unmount-on-close
      @cancel="showCase = false"
      width="520px"
    >
      <template #title>新增评测样本</template>
      <a-form
        class="form-stack"
        :model="{ queryId, queryType, query, relevantChunkIds }"
        layout="vertical"
        @submit-success="createCase"
      >
        <a-form-item
          field="queryId"
          :rules="[{ required: true, message: '请填写Query ID' }]"
          :validate-trigger="['change', 'blur']"
        >
          <template #label>Query ID</template>
          <a-input
            v-model="queryId"
            type="text"
            :input-attrs="{ required: true }"
          ></a-input>
        </a-form-item>
        <a-form-item field="queryType">
          <template #label>查询类型</template>
          <a-select v-model="queryType">
            <a-option value="concept">概念</a-option>
            <a-option value="comparison">对比</a-option>
            <a-option value="troubleshooting">排障</a-option>
          </a-select>
        </a-form-item>
        <a-form-item
          field="query"
          :rules="[{ required: true, message: '请填写查询' }]"
          :validate-trigger="['change', 'blur']"
        >
          <template #label>查询</template>
          <a-textarea
            v-model="query"
            :textarea-attrs="{ required: true, rows: '3' }"
          ></a-textarea>
        </a-form-item>
        <a-form-item field="relevantChunkIds">
          <template #label>相关 Chunk ID（逗号或换行分隔）</template>
          <a-textarea
            v-model="relevantChunkIds"
            :textarea-attrs="{ rows: '3' }"
          ></a-textarea>
        </a-form-item>
        <div class="modal-actions">
          <a-button @click="showCase = false" type="text" html-type="button">
            取消
          </a-button>
          <a-button :disabled="saving" type="primary" html-type="submit">
            保存
          </a-button>
        </div>
      </a-form>
    </a-modal>

    <a-modal
      v-if="showImport"
      :visible="true"
      :footer="false"
      unmount-on-close
      @cancel="showImport = false"
      width="520px"
    >
      <template #title>导入 JSONL</template>
      <a-form
        class="form-stack"
        :model="{ importContent }"
        layout="vertical"
        @submit-success="importCases"
      >
        <a-form-item field="importContent">
          <template #label>每行一个评测样本</template>
          <a-textarea
            v-model="importContent"
            placeholder='{"query_id":"q-1","query_type":"concept","query":"如何配置检索？","relevant_chunk_ids":[]}'
            :textarea-attrs="{ rows: '10' }"
          ></a-textarea>
        </a-form-item>
        <div class="modal-actions">
          <a-button @click="showImport = false" type="text" html-type="button">
            取消
          </a-button>
          <a-button
            :disabled="saving || !importContent.trim()"
            type="primary"
            html-type="submit"
          >
            导入
          </a-button>
        </div>
      </a-form>
    </a-modal>

    <a-modal
      v-if="showRun"
      :visible="true"
      :footer="false"
      unmount-on-close
      @cancel="showRun = false"
      width="520px"
    >
      <template #title>启动评测</template>
      <a-form
        class="form-stack"
        :model="{
          selectedProviderId,
          selectedModelId,
          engineMode,
          baselineRunId,
        }"
        layout="vertical"
        @submit-success="startRun"
      >
        <a-form-item
          field="selectedProviderId"
          :rules="[{ required: true, message: '请填写供应商' }]"
          :validate-trigger="['change', 'blur']"
        >
          <template #label>供应商</template>
          <a-select
            v-model="selectedProviderId"
            data-testid="run-provider-select"
            :disabled="loadingProviders || !eligibleProviders.length"
          >
            <a-option value="">选择供应商</a-option>
            <a-option
              v-for="provider in eligibleProviders"
              :key="provider.id"
              :value="provider.id"
            >
              {{ provider.name }}
            </a-option>
          </a-select>
        </a-form-item>
        <a-form-item
          field="selectedModelId"
          :rules="[{ required: true, message: '请填写模型' }]"
          :validate-trigger="['change', 'blur']"
        >
          <template #label>模型</template>
          <a-select
            v-model="selectedModelId"
            data-testid="run-model-select"
            :disabled="!selectedProvider"
          >
            <a-option value="">选择模型</a-option>
            <a-option v-for="model in modelOptions" :key="model" :value="model">
              {{ model }}
            </a-option>
          </a-select>
        </a-form-item>
        <a-form-item field="engineMode">
          <template #label>检索引擎</template>
          <a-select v-model="engineMode">
            <a-option value="dual_engine">ES + Qdrant 双引擎</a-option>
            <a-option value="elastic_single">Elasticsearch 单引擎</a-option>
          </a-select>
        </a-form-item>
        <a-form-item field="baselineRunId">
          <template #label>基线运行 ID（可选）</template>
          <a-input v-model="baselineRunId" type="text"></a-input>
        </a-form-item>
        <div class="modal-actions">
          <a-button @click="showRun = false" type="text" html-type="button">
            取消
          </a-button>
          <a-button
            data-testid="run-start-submit"
            :disabled="saving || !hasProviderAndModel"
            type="primary"
            html-type="submit"
          >
            <Play :size="16" />
            启动
          </a-button>
        </div>
      </a-form>
    </a-modal>
  </div>
</template>
