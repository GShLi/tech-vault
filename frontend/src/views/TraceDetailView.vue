<script setup lang="ts">
import { ApiRequestError, api, normalizeApiError } from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Card as ACard,
  Descriptions as ADescriptions,
  DescriptionsItem as ADescriptionsItem,
  Drawer as ADrawer,
  Empty as AEmpty,
  Progress as AProgress,
  Spin as ASpin,
  Table as ATable,
  TableColumn as ATableColumn,
  Tag as ATag,
} from '@arco-design/web-vue'

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  AlertTriangle,
  ArrowLeft,
  Braces,
  Copy,
  Download,
  Layers3,
  PanelRightOpen,
  Search,
} from 'lucide-vue-next'

import { statusColor } from '@/utils/status'
import { useTeamStore } from '@/stores/team'
import type { JsonRecord, TraceChunkDetail, TraceView } from '@/types/api'
import { formatDate, shortId, statusLabel } from '@/utils/format'
import {
  formatTraceDuration,
  traceStageMeta,
  traceStageParent,
  traceTotalDuration,
} from '@/utils/trace'

const route = useRoute()
const team = useTeamStore()
const trace = ref<TraceView | null>(null)
const loading = ref(false)
const error = ref<ApiRequestError | null>(null)
const drawerVisible = ref(false)
const selectedChunkId = ref<string | null>(null)
const copied = ref(false)
let copyTimer: number | undefined

const stages = computed(() => {
  const entries = Object.entries(trace.value?.stage_latency_ms ?? {}).filter(
    (entry): entry is [string, number] =>
      typeof entry[1] === 'number' && Number.isFinite(entry[1]),
  )
  const total = traceTotalDuration(trace.value?.stage_latency_ms ?? {})
  return entries.map(([key, value]) => {
    const meta = traceStageMeta(key)
    const parent = traceStageParent(key, trace.value?.stage_latency_ms ?? {})
    return {
      key,
      value,
      parentLabel: parent ? traceStageMeta(parent).label : null,
      ...meta,
      formatted: formatTraceDuration(value),
      width:
        total > 0 ? Math.max(value > 0 ? 1.5 : 0, (value / total) * 100) : 0,
      tooltip: `${key}：${meta.description}；原始耗时 ${value} ms${parent ? `；包含在${traceStageMeta(parent).label}中，不重复计入总耗时` : ''}`,
    }
  })
})
const totalStageLatency = computed(() =>
  traceTotalDuration(trace.value?.stage_latency_ms ?? {}),
)
const rewrite = computed(() => trace.value?.rewrite ?? null)
const rewriteSourceLabel = computed(() => {
  const value = rewrite.value
  if (!value) return ''
  if (value.fallback_reason || value.route === 'local_rules') return '规则回退'
  if (value.structured_mode === 'json_schema') return 'LLM 结构化'
  if (value.structured_mode === 'tool_use') return 'LLM 工具调用'
  return 'LLM JSON'
})
const rewriteFilters = computed(() => {
  const filters = rewrite.value?.applied_filters ?? {}
  const product = typeof filters.product === 'string' ? filters.product : ''
  const versions = Array.isArray(filters.version_values)
    ? filters.version_values.filter(
        (value): value is string => typeof value === 'string',
      )
    : []
  return [product, ...versions].filter(Boolean)
})
const feedbackLabels: Record<string, string> = {
  useful: '有帮助',
  not_useful: '无帮助',
  citation_error: '引用错误',
  knowledge_gap: '知识缺口',
}

const selectedChunk = computed<TraceChunkDetail | null>(() => {
  const chunkId = selectedChunkId.value
  if (!chunkId) return null
  return trace.value?.chunk_details?.[chunkId] ?? null
})

const chunkFields = computed(() => {
  const chunk = selectedChunk.value
  if (!chunk || chunk.restricted) return []
  return [
    { label: 'Chunk ID', value: chunk.id, block: false },
    { label: '文档名称', value: chunk.document_name || '—', block: false },
    { label: '文档 ID', value: chunk.document_id || '—', block: false },
    { label: '知识库', value: chunk.knowledge_base_name || '—', block: false },
    { label: '知识库 ID', value: chunk.knowledge_base_id || '—', block: false },
    { label: '状态', value: chunk.chunk_status || '—', block: false },
    { label: '文档状态', value: chunk.doc_status || '—', block: false },
    { label: '可见性', value: chunk.visibility || '—', block: false },
    {
      label: '数据分级',
      value: chunk.data_classification || '—',
      block: false,
    },
    { label: '索引代次', value: chunk.index_generation || '—', block: false },
    {
      label: '版本',
      value: chunk.version != null ? String(chunk.version) : '—',
      block: false,
    },
    {
      label: '版本值',
      value: (chunk.version_values ?? []).join(', ') || '—',
      block: false,
    },
    {
      label: '标题路径',
      value: (chunk.heading_path ?? []).join(' / ') || '—',
      block: false,
    },
    {
      label: '来源定位',
      value: JSON.stringify(chunk.source_locator ?? {}, null, 2),
      block: true,
    },
    { label: '来源路径', value: chunk.source_path || '—', block: false },
    {
      label: '逻辑 Chunk Key',
      value: chunk.logical_chunk_key || '—',
      block: false,
    },
    { label: '内容哈希', value: chunk.content_hash || '—', block: false },
    {
      label: '创建时间',
      value: chunk.created_at ? formatDate(chunk.created_at) : '—',
      block: false,
    },
    {
      label: '更新时间',
      value: chunk.updated_at ? formatDate(chunk.updated_at) : '—',
      block: false,
    },
    { label: '内容', value: chunk.content || '—', block: true },
  ]
})

function rowId(row: JsonRecord): string {
  return String(row.chunk_id ?? row.document_version_id ?? row.id ?? '—')
}

function rowScore(row: JsonRecord, scoreKey: string): string {
  const value = row[scoreKey] ?? row.score ?? row.similarity
  return typeof value === 'number' ? value.toFixed(4) : String(value ?? '—')
}

function chunkDetail(row: JsonRecord): TraceChunkDetail | null {
  const chunkId = typeof row.chunk_id === 'string' ? row.chunk_id : ''
  if (!chunkId) return null
  return trace.value?.chunk_details?.[chunkId] ?? null
}

function chunkPreview(row: JsonRecord): string {
  const chunk = chunkDetail(row)
  if (!chunk) return 'Chunk 记录已不存在'
  if (chunk.restricted) return '无权查看该 Chunk 内容'
  return chunk.content?.trim() || 'Chunk 内容为空'
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function chunkSegments(
  row: JsonRecord,
): Array<{ text: string; highlighted: boolean }> {
  const text = chunkPreview(row)
  const matchedTerms = Array.isArray(row.matched_terms)
    ? row.matched_terms.filter(
        (value): value is string =>
          typeof value === 'string' && value.trim().length > 0,
      )
    : []
  const uniqueTerms = [
    ...new Map(
      matchedTerms.map((term) => [term.toLocaleLowerCase(), term]),
    ).values(),
  ].sort((left, right) => right.length - left.length)
  if (!uniqueTerms.length) {
    return [{ text, highlighted: false }]
  }
  const normalizedTerms = new Set(
    uniqueTerms.map((term) => term.toLocaleLowerCase()),
  )
  const pattern = new RegExp(
    `(${uniqueTerms.map(escapeRegex).join('|')})`,
    'gi',
  )
  return text
    .split(pattern)
    .filter(Boolean)
    .map((segment) => ({
      text: segment,
      highlighted: normalizedTerms.has(segment.toLocaleLowerCase()),
    }))
}

function openChunk(row: JsonRecord): void {
  const chunkId = typeof row.chunk_id === 'string' ? row.chunk_id : ''
  if (!chunkId) return
  selectedChunkId.value = chunkId
  copied.value = false
  drawerVisible.value = true
}

async function copyChunkJson(): Promise<void> {
  if (!selectedChunk.value) return
  const text = JSON.stringify(selectedChunk.value, null, 2)
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.setAttribute('readonly', '')
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
  }
  copied.value = true
  if (copyTimer) window.clearTimeout(copyTimer)
  copyTimer = window.setTimeout(() => {
    copied.value = false
  }, 1600)
}

async function load(): Promise<void> {
  const traceId = String(route.params.traceId ?? '')
  if (!team.selectedTeamId || !traceId) return
  loading.value = true
  error.value = null
  try {
    trace.value = await api.getTrace(team.selectedTeamId, traceId)
  } catch (caught) {
    error.value = normalizeApiError(caught)
  } finally {
    loading.value = false
  }
}

function exportSnapshot(): void {
  if (!trace.value) return
  const blob = new Blob([JSON.stringify(trace.value, null, 2)], {
    type: 'application/json',
  })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `trace-${trace.value.trace_id}.json`
  anchor.click()
  URL.revokeObjectURL(url)
}

onMounted(load)
watch(() => route.params.traceId, load)
onBeforeUnmount(() => {
  if (copyTimer) window.clearTimeout(copyTimer)
})
</script>

<template>
  <div>
    <div class="page-header">
      <div class="heading-with-back">
        <RouterLink to="/traces" custom v-slot="{ href, navigate }">
          <a-button
            type="text"
            :href="href"
            @click="navigate"
            title="返回 Trace 列表"
          >
            <ArrowLeft :size="18" />
          </a-button>
        </RouterLink>
        <div>
          <h2>Trace 详情</h2>
          <p>{{ trace ? trace.trace_id : '正在读取检索链路' }}</p>
        </div>
      </div>
      <a-button
        :disabled="!trace"
        @click="exportSnapshot"
        type="secondary"
        html-type="button"
      >
        <Download :size="16" />
        导出快照
      </a-button>
    </div>
    <a-alert v-if="error" type="error" class="page-alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
    </a-alert>
    <div v-if="loading && !trace" class="panel loading-state">
      <a-spin />
      <span>正在加载 Trace</span>
    </div>
    <template v-else-if="trace">
      <a-card class="page-card">
        <div class="detail-heading">
          <div class="detail-icon"><Layers3 :size="20" /></div>
          <div>
            <h3>{{ trace.original_query }}</h3>
            <p>{{ trace.engine_mode }} · {{ formatDate(trace.created_at) }}</p>
          </div>
          <a-tag
            :color="statusColor(trace.degraded ? 'degraded' : 'completed')"
          >
            {{ trace.degraded ? '降级' : '正常' }}
          </a-tag>
        </div>
        <a-descriptions
          :column="{ xs: 1, sm: 2, lg: 3 }"
          bordered
          class="detail-descriptions"
        >
          <a-descriptions-item label="改写查询">
            {{ trace.rewritten_query || '—' }}
          </a-descriptions-item>
          <a-descriptions-item label="会话">
            {{ shortId(trace.chat_id) }}
          </a-descriptions-item>
          <a-descriptions-item label="消息">
            {{ shortId(trace.message_id) }}
          </a-descriptions-item>
          <a-descriptions-item label="错误码">
            {{ trace.error_code || '—' }}
          </a-descriptions-item>
        </a-descriptions>
        <div v-if="rewrite" class="rewrite-summary" data-testid="trace-rewrite">
          <div class="rewrite-summary-head">
            <strong>QueryRewrite</strong>
            <a-tag>{{ rewriteSourceLabel }}</a-tag>
          </div>
          <div class="rewrite-query-flow">
            <span>{{ rewrite.original_query || '—' }}</span>
            <span class="rewrite-arrow">→</span>
            <span>{{ rewrite.rewritten_query || '—' }}</span>
          </div>
          <div v-if="rewriteFilters.length" class="rewrite-filter-list">
            <a-tag v-for="filter in rewriteFilters" :key="filter">
              {{ filter }}
            </a-tag>
          </div>
          <p class="muted-text">
            {{ rewrite.model_id || '未知模型' }}
            · {{ formatTraceDuration(rewrite.latency_ms ?? 0) }} ·
            {{ rewrite.input_tokens ?? 0 }} /
            {{ rewrite.output_tokens ?? 0 }} tokens
          </p>
          <p v-if="rewrite.fallback_reason" class="muted-text">
            回退原因：{{ rewrite.fallback_reason }}
          </p>
          <p v-if="rewrite.validation_error" class="muted-text">
            校验信息：{{ rewrite.validation_error }}
          </p>
        </div>
        <div class="stage-chart" data-testid="trace-stage-chart">
          <div class="stage-chart-heading">
            <div>
              <strong>阶段耗时</strong>
              <span>按去重后的总耗时占比展示；子调用已包含在所属阶段中</span>
            </div>
            <span
              class="stage-chart-total"
              :title="`阶段去重后耗时合计，原始值 ${totalStageLatency} ms`"
            >
              总耗时 {{ formatTraceDuration(totalStageLatency) }}
            </span>
          </div>
          <div v-if="stages.length" class="stage-chart-list">
            <div
              v-for="stage in stages"
              :key="stage.key"
              class="stage-chart-row"
              :data-testid="`trace-stage-${stage.key}`"
              :title="stage.tooltip"
              :aria-label="stage.tooltip"
            >
              <span class="stage-chart-label" :title="stage.tooltip">
                {{ stage.label }}
                <small v-if="stage.parentLabel" class="stage-parent-label">
                  包含在{{ stage.parentLabel }}
                </small>
              </span>
              <a-progress
                :percent="Math.max(0, Math.min(1, stage.width / 100))"
                :show-text="false"
                size="small"
              ></a-progress>
              <strong class="stage-chart-value" :title="stage.tooltip">
                {{ stage.formatted }}
              </strong>
            </div>
          </div>
          <a-empty v-else class="page-empty">
            <span>暂无阶段耗时数据</span>
          </a-empty>
        </div>
      </a-card>

      <div class="split-grid">
        <a-card class="page-card">
          <div class="section-heading">
            <h3>过滤条件</h3>
            <Braces :size="16" />
          </div>
          <pre class="json-block">{{
            JSON.stringify(trace.filters, null, 2)
          }}</pre>
        </a-card>
        <a-card class="page-card">
          <div class="section-heading">
            <h3>模型信息</h3>
            <Braces :size="16" />
          </div>
          <pre class="json-block">{{
            JSON.stringify(trace.model, null, 2)
          }}</pre>
        </a-card>
      </div>

      <a-card class="page-card">
        <div class="section-heading">
          <h3>用户反馈</h3>
          <span class="muted-text">{{ trace.feedback.length }} 条</span>
        </div>
        <div v-if="trace.feedback.length" class="feedback-list">
          <article
            v-for="item in trace.feedback"
            :key="item.id"
            class="feedback-item"
          >
            <div>
              <a-tag :color="statusColor(item.feedback_type)">
                {{ feedbackLabels[item.feedback_type] ?? item.feedback_type }}
              </a-tag>
              <span class="muted-text">{{ formatDate(item.created_at) }}</span>
            </div>
            <p>{{ item.comment || '未填写补充说明' }}</p>
          </article>
        </div>
        <a-empty v-else class="page-empty">
          <span>该次问答暂无用户反馈</span>
        </a-empty>
      </a-card>

      <a-card
        v-for="group in [
          {
            title: 'BM25 候选',
            scoreKey: 'bm25_score',
            rows: trace.bm25_candidates,
          },
          {
            title: 'Dense 候选',
            scoreKey: 'dense_score',
            rows: trace.dense_candidates,
          },
          {
            title: 'RRF 融合',
            scoreKey: 'rrf_score',
            rows: trace.rrf_candidates,
          },
          {
            title: 'Rerank 结果',
            scoreKey: 'rerank_score',
            rows: trace.rerank_candidates,
          },
          {
            title: '最终上下文',
            scoreKey: 'rerank_score',
            rows: trace.final_context,
          },
        ]"
        :key="group.title"
        class="page-card"
      >
        <div class="section-heading">
          <h3>{{ group.title }}</h3>
          <span class="muted-text">{{ group.rows.length }} 条</span>
        </div>
        <div v-if="group.rows.length" class="table-wrap">
          <a-table
            :data="group.rows"
            :pagination="false"
            :bordered="false"
            :scroll="{ x: 960 }"
          >
            <template #columns>
              <a-table-column title="Chunk" :width="180">
                <template #cell="{ record: row, rowIndex: index }">
                  {{ rowId(row) }}
                </template>
              </a-table-column>
              <a-table-column title="分数" :width="100">
                <template #cell="{ record: row, rowIndex: index }">
                  {{ rowScore(row, group.scoreKey) }}
                </template>
              </a-table-column>
              <a-table-column title="Chunk 内容">
                <template #cell="{ record: row, rowIndex: index }">
                  <a-button
                    :data-testid="`trace-chunk-${row.chunk_id ?? index}`"
                    title="点击查看 Chunk 详情"
                    @click="openChunk(row)"
                    type="text"
                    html-type="button"
                    class="chunk-content-trigger"
                  >
                    <span class="chunk-content-preview">
                      <template
                        v-for="(segment, segmentIndex) in chunkSegments(row)"
                        :key="segmentIndex"
                      >
                        <mark v-if="segment.highlighted">
                          {{ segment.text }}
                        </mark>
                        <template v-else>{{ segment.text }}</template>
                      </template>
                    </span>
                    <PanelRightOpen :size="14" aria-hidden="true" />
                  </a-button>
                </template>
              </a-table-column>
            </template>
          </a-table>
        </div>
        <a-empty v-else class="page-empty">
          <template #image><Search :size="20" /></template>
          <span>该阶段无候选</span>
        </a-empty>
      </a-card>

      <a-drawer
        v-model:visible="drawerVisible"
        :width="560"
        :footer="false"
        title="Chunk 详情"
        unmount-on-close
      >
        <div
          v-if="selectedChunk && !selectedChunk.restricted"
          class="chunk-detail-panel"
        >
          <div class="chunk-detail-toolbar">
            <span class="muted-text">
              {{ selectedChunk.document_name || selectedChunk.id }}
            </span>
            <a-button
              data-testid="copy-chunk-json"
              @click="copyChunkJson"
              type="secondary"
              html-type="button"
            >
              <Copy :size="16" />
              {{ copied ? '已复制' : '复制原始 JSON' }}
            </a-button>
          </div>
          <a-descriptions :column="1" bordered class="detail-descriptions">
            <a-descriptions-item
              v-for="field in chunkFields"
              :key="field.label"
            >
              <template #label>{{ field.label }}</template>
              <pre v-if="field.block" class="chunk-field-block">{{
                field.value
              }}</pre>
              <span v-else>{{ field.value }}</span>
            </a-descriptions-item>
          </a-descriptions>
        </div>
        <a-empty v-else class="page-empty">
          <template #image><AlertTriangle :size="20" /></template>
          <span>
            {{
              selectedChunk
                ? '该 Chunk 属于私有文档，当前账号无权查看详情'
                : 'Chunk 记录已不存在'
            }}
          </span>
        </a-empty>
      </a-drawer>
    </template>
  </div>
</template>
