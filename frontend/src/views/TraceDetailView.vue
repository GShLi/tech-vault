<script setup lang="ts">
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

import { api, ApiRequestError } from '@/api/client'
import StatusPill from '@/components/StatusPill.vue'
import { useTeamStore } from '@/stores/team'
import type { JsonRecord, TraceChunkDetail, TraceView } from '@/types/api'
import { formatDate, shortId } from '@/utils/format'
import {
  formatTraceDuration,
  traceStageMeta,
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
  const total = entries.reduce((sum, [, value]) => sum + Math.max(0, value), 0)
  return entries.map(([key, value]) => {
    const meta = traceStageMeta(key)
    return {
      key,
      value,
      ...meta,
      formatted: formatTraceDuration(value),
      width: total > 0 ? Math.max(value > 0 ? 1.5 : 0, (value / total) * 100) : 0,
      tooltip: `${key}：${meta.description}；原始耗时 ${value} ms`,
    }
  })
})
const totalStageLatency = computed(() =>
  traceTotalDuration(trace.value?.stage_latency_ms ?? {}),
)
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
    { label: '数据分级', value: chunk.data_classification || '—', block: false },
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

function rowScore(row: JsonRecord): string {
  const value = row.rerank_score ?? row.rrf_score ?? row.score ?? row.similarity
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
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loading.value = false
  }
}

function exportSnapshot(): void {
  if (!trace.value) return
  const blob = new Blob([JSON.stringify(trace.value, null, 2)], { type: 'application/json' })
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
        <RouterLink class="icon-button" to="/traces" title="返回 Trace 列表"><ArrowLeft :size="18" /></RouterLink>
        <div><h2>Trace 详情</h2><p>{{ trace ? trace.trace_id : '正在读取检索链路' }}</p></div>
      </div>
      <button class="secondary-button" type="button" :disabled="!trace" @click="exportSnapshot"><Download :size="16" />导出快照</button>
    </div>
    <div v-if="error" class="error-banner" role="alert"><strong>{{ error.message }}</strong><span v-if="error.requestId">请求 ID：{{ error.requestId }}</span></div>
    <div v-if="loading && !trace" class="panel loading-state"><a-spin /><span>正在加载 Trace</span></div>
    <template v-else-if="trace">
      <section class="panel detail-panel">
        <div class="detail-heading">
          <div class="detail-icon"><Layers3 :size="20" /></div>
          <div><h3>{{ trace.original_query }}</h3><p>{{ trace.engine_mode }} · {{ formatDate(trace.created_at) }}</p></div>
          <StatusPill :status="trace.degraded ? 'degraded' : 'completed'" :label="trace.degraded ? '降级' : '正常'" />
        </div>
        <dl class="detail-grid">
          <div><dt>改写查询</dt><dd>{{ trace.rewritten_query || '—' }}</dd></div>
          <div><dt>会话</dt><dd>{{ shortId(trace.chat_id) }}</dd></div>
          <div><dt>消息</dt><dd>{{ shortId(trace.message_id) }}</dd></div>
          <div><dt>错误码</dt><dd>{{ trace.error_code || '—' }}</dd></div>
        </dl>
        <div class="stage-chart" data-testid="trace-stage-chart">
          <div class="stage-chart-heading">
            <div>
              <strong>阶段耗时</strong>
              <span>按总耗时占比展示</span>
            </div>
            <span
              class="stage-chart-total"
              :title="`所有阶段耗时合计，原始值 ${totalStageLatency} ms`"
            >总耗时 {{ formatTraceDuration(totalStageLatency) }}</span>
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
              <span class="stage-chart-label" :title="stage.tooltip">{{ stage.label }}</span>
              <span class="stage-chart-track" aria-hidden="true">
                <span :style="{ width: `${stage.width}%` }"></span>
              </span>
              <strong class="stage-chart-value" :title="stage.tooltip">{{ stage.formatted }}</strong>
            </div>
          </div>
          <div v-else class="empty-state compact"><span>暂无阶段耗时数据</span></div>
        </div>
      </section>

      <div class="split-grid">
        <section class="panel detail-panel"><div class="section-heading"><h3>过滤条件</h3><Braces :size="16" /></div><pre class="json-block">{{ JSON.stringify(trace.filters, null, 2) }}</pre></section>
        <section class="panel detail-panel"><div class="section-heading"><h3>模型信息</h3><Braces :size="16" /></div><pre class="json-block">{{ JSON.stringify(trace.model, null, 2) }}</pre></section>
      </div>

      <section class="panel detail-panel">
        <div class="section-heading"><h3>用户反馈</h3><span class="muted-text">{{ trace.feedback.length }} 条</span></div>
        <div v-if="trace.feedback.length" class="feedback-list">
          <article v-for="item in trace.feedback" :key="item.id" class="feedback-item">
            <div><StatusPill :status="item.feedback_type" :label="feedbackLabels[item.feedback_type] ?? item.feedback_type" /><span class="muted-text">{{ formatDate(item.created_at) }}</span></div>
            <p>{{ item.comment || '未填写补充说明' }}</p>
          </article>
        </div>
        <div v-else class="empty-state compact"><span>该次问答暂无用户反馈</span></div>
      </section>

      <section v-for="group in [
        { title: 'BM25 候选', rows: trace.bm25_candidates },
        { title: 'Dense 候选', rows: trace.dense_candidates },
        { title: 'RRF 融合', rows: trace.rrf_candidates },
        { title: 'Rerank 结果', rows: trace.rerank_candidates },
        { title: '最终上下文', rows: trace.final_context },
      ]" :key="group.title" class="panel detail-panel">
        <div class="section-heading">
          <h3>{{ group.title }}</h3>
          <span class="muted-text">{{ group.rows.length }} 条 · 点击 Chunk 内容查看详情</span>
        </div>
        <div v-if="group.rows.length" class="table-wrap">
          <table>
            <thead>
              <tr><th>Chunk</th><th>分数</th><th>Chunk 内容</th></tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in group.rows" :key="`${group.title}-${index}`">
                <td>{{ rowId(row) }}</td>
                <td>{{ rowScore(row) }}</td>
                <td>
                  <button
                    class="chunk-content-trigger"
                    type="button"
                    :data-testid="`trace-chunk-${row.chunk_id ?? index}`"
                    title="点击查看 Chunk 详情"
                    @click="openChunk(row)"
                  >
                    <span class="chunk-content-preview">{{ chunkPreview(row) }}</span>
                    <PanelRightOpen :size="14" aria-hidden="true" />
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty-state compact"><Search :size="20" /><span>该阶段无候选</span></div>
      </section>

      <a-drawer
        v-model:visible="drawerVisible"
        :width="560"
        :footer="false"
        title="Chunk 详情"
        unmount-on-close
      >
        <div v-if="selectedChunk && !selectedChunk.restricted" class="chunk-detail-panel">
          <div class="chunk-detail-toolbar">
            <span class="muted-text">
              {{ selectedChunk.document_name || selectedChunk.id }}
            </span>
            <button
              class="secondary-button"
              type="button"
              data-testid="copy-chunk-json"
              @click="copyChunkJson"
            >
              <Copy :size="16" />
              {{ copied ? '已复制' : '复制原始 JSON' }}
            </button>
          </div>
          <dl class="chunk-field-list">
            <div v-for="field in chunkFields" :key="field.label" class="chunk-field">
              <dt>{{ field.label }}</dt>
              <dd>
                <pre v-if="field.block" class="chunk-field-block">{{ field.value }}</pre>
                <span v-else>{{ field.value }}</span>
              </dd>
            </div>
          </dl>
        </div>
        <div v-else class="empty-state compact">
          <AlertTriangle :size="20" />
          <span>
            {{ selectedChunk ? '该 Chunk 属于私有文档，当前账号无权查看详情' : 'Chunk 记录已不存在' }}
          </span>
        </div>
      </a-drawer>
    </template>
  </div>
</template>
