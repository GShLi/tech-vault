<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { Activity, RefreshCw, Search } from 'lucide-vue-next'

import { api, ApiRequestError } from '@/api/client'
import StatusPill from '@/components/StatusPill.vue'
import { useTeamStore } from '@/stores/team'
import type { TraceView } from '@/types/api'
import { formatDate, shortId } from '@/utils/format'

const team = useTeamStore()
const traces = ref<TraceView[]>([])
const loading = ref(false)
const error = ref<ApiRequestError | null>(null)
const nextCursor = ref<string | null>(null)
const hasMore = ref(false)

function latency(trace: TraceView): number {
  return Object.values(trace.stage_latency_ms).reduce((total, value) => total + Number(value || 0), 0)
}

async function load(reset = true): Promise<void> {
  if (!team.selectedTeamId) return
  loading.value = true
  error.value = null
  try {
    const page = await api.listTraces(team.selectedTeamId, reset ? null : nextCursor.value)
    traces.value = reset ? page.data : [...traces.value, ...page.data]
    nextCursor.value = page.meta.next_cursor
    hasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => team.selectedTeamId, () => load())
</script>

<template>
  <div>
    <div class="page-header">
      <div><h2>检索调试</h2><p>按问答 Trace 检查 Query Rewrite、候选召回、融合、Rerank 与模型信息。</p></div>
      <button class="secondary-button" type="button" :disabled="loading" @click="load()"><RefreshCw :size="16" />刷新</button>
    </div>
    <div v-if="error" class="error-banner" role="alert"><strong>{{ error.message }}</strong><span v-if="error.requestId">请求 ID：{{ error.requestId }}</span><button class="inline-link" type="button" @click="load()">重试</button></div>
    <div v-if="loading && !traces.length" class="panel loading-state"><a-spin /><span>正在加载 Trace</span></div>
    <div v-else-if="!traces.length" class="panel empty-state"><Search :size="28" /><h3>暂无检索 Trace</h3><p>完成一次问答后，检索链路会记录在这里。</p></div>
    <div v-else class="panel">
      <div class="table-wrap">
        <table>
          <thead><tr><th>Trace</th><th>问题</th><th>引擎</th><th>耗时</th><th>状态</th><th>时间</th><th class="actions-column">操作</th></tr></thead>
          <tbody>
            <tr v-for="trace in traces" :key="trace.id">
              <td data-label="Trace"><RouterLink :to="`/traces/${trace.trace_id}`"><strong>{{ shortId(trace.trace_id) }}</strong></RouterLink><span class="cell-subtitle">{{ shortId(trace.chat_id) }}</span></td>
              <td data-label="问题"><span class="truncate-cell">{{ trace.original_query }}</span><span class="cell-subtitle">{{ trace.rewritten_query || '未改写' }}</span></td>
              <td data-label="引擎">{{ trace.engine_mode }}</td>
              <td data-label="耗时"><span class="inline-stat"><Activity :size="14" />{{ latency(trace) }} ms</span></td>
              <td data-label="状态"><StatusPill :status="trace.degraded ? 'degraded' : 'completed'" :label="trace.degraded ? '降级' : '正常'" /></td>
              <td data-label="时间">{{ formatDate(trace.created_at) }}</td>
              <td data-label="操作"><RouterLink class="ghost-button" :to="`/traces/${trace.trace_id}`">查看</RouterLink></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="hasMore" class="load-more"><button class="secondary-button" type="button" :disabled="loading" @click="load(false)">加载更多</button></div>
    </div>
  </div>
</template>
