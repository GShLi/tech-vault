<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, Braces, Download, Layers3, Search } from 'lucide-vue-next'

import { api, ApiRequestError } from '@/api/client'
import StatusPill from '@/components/StatusPill.vue'
import { useTeamStore } from '@/stores/team'
import type { JsonRecord, TraceView } from '@/types/api'
import { formatDate, shortId } from '@/utils/format'

const route = useRoute()
const team = useTeamStore()
const trace = ref<TraceView | null>(null)
const loading = ref(false)
const error = ref<ApiRequestError | null>(null)

const stages = computed(() => Object.entries(trace.value?.stage_latency_ms ?? {}))
const feedbackLabels: Record<string, string> = {
  useful: '有帮助',
  not_useful: '无帮助',
  citation_error: '引用错误',
  knowledge_gap: '知识缺口',
}

function rowId(row: JsonRecord): string {
  return String(row.chunk_id ?? row.document_version_id ?? row.id ?? '—')
}

function rowScore(row: JsonRecord): string {
  const value = row.rerank_score ?? row.rrf_score ?? row.score ?? row.similarity
  return typeof value === 'number' ? value.toFixed(4) : String(value ?? '—')
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
        <div class="stage-list">
          <div v-for="[stage, value] in stages" :key="stage" class="stage-item">
            <span>{{ stage }}</span><strong>{{ value }} ms</strong>
          </div>
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
        <div class="section-heading"><h3>{{ group.title }}</h3><span class="muted-text">{{ group.rows.length }} 条</span></div>
        <div v-if="group.rows.length" class="table-wrap">
          <table><thead><tr><th>Chunk</th><th>分数</th><th>原始记录</th></tr></thead><tbody><tr v-for="(row, index) in group.rows" :key="`${group.title}-${index}`"><td>{{ rowId(row) }}</td><td>{{ rowScore(row) }}</td><td><code class="json-inline">{{ JSON.stringify(row) }}</code></td></tr></tbody></table>
        </div>
        <div v-else class="empty-state compact"><Search :size="20" /><span>该阶段无候选</span></div>
      </section>
    </template>
  </div>
</template>
