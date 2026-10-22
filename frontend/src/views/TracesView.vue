<script setup lang="ts">
import { useCursorList } from '@/composables/useCursorList'
import { traceTotalDuration } from '@/utils/trace'
import { api, normalizeApiError } from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Empty as AEmpty,
  Spin as ASpin,
  Table as ATable,
  TableColumn as ATableColumn,
  Tag as ATag,
} from '@arco-design/web-vue'

import { Activity, RefreshCw, Search } from 'lucide-vue-next'

import { statusColor } from '@/utils/status'
import { useTeamStore } from '@/stores/team'
import type { TraceView } from '@/types/api'
import { formatDate, shortId, statusLabel } from '@/utils/format'

const team = useTeamStore()
const {
  items: traces,
  loading,
  error,
  hasMore,
  load,
} = useCursorList<TraceView>(
  () => team.selectedTeamId,
  (teamId, cursor) => api.listTraces(teamId, cursor),
)

function latency(trace: TraceView): number {
  return traceTotalDuration(trace.stage_latency_ms)
}
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2>检索调试</h2>
        <p>
          按问答 Trace 检查 Query Rewrite、候选召回、融合、Rerank 与模型信息。
        </p>
      </div>
      <a-button
        :disabled="loading"
        @click="load()"
        type="secondary"
        html-type="button"
      >
        <RefreshCw :size="16" />
        刷新
      </a-button>
    </div>
    <a-alert v-if="error" type="error" class="page-alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
      <a-button @click="load()" type="text" html-type="button">重试</a-button>
    </a-alert>
    <div v-if="loading && !traces.length" class="panel loading-state">
      <a-spin />
      <span>正在加载 Trace</span>
    </div>
    <a-empty v-else-if="!traces.length" class="page-empty">
      <template #image><Search :size="28" /></template>
      <h3>暂无检索 Trace</h3>
      <p>完成一次问答后，检索链路会记录在这里。</p>
    </a-empty>
    <div v-else class="panel">
      <div class="table-wrap">
        <a-table
          :data="traces"
          :pagination="false"
          row-key="id"
          :bordered="false"
          :scroll="{ x: 960 }"
        >
          <template #columns>
            <a-table-column title="Trace">
              <template #cell="{ record: trace }">
                <RouterLink :to="`/traces/${trace.trace_id}`">
                  <strong>{{ shortId(trace.trace_id) }}</strong>
                </RouterLink>
                <span class="cell-subtitle">{{ shortId(trace.chat_id) }}</span>
              </template>
            </a-table-column>
            <a-table-column title="问题">
              <template #cell="{ record: trace }">
                <span class="truncate-cell">{{ trace.original_query }}</span>
                <span class="cell-subtitle">
                  {{ trace.rewritten_query || '未改写' }}
                </span>
              </template>
            </a-table-column>
            <a-table-column title="引擎">
              <template #cell="{ record: trace }">
                {{ trace.engine_mode }}
              </template>
            </a-table-column>
            <a-table-column title="耗时">
              <template #cell="{ record: trace }">
                <span class="inline-stat">
                  <Activity :size="14" />
                  {{ latency(trace) }} ms
                </span>
              </template>
            </a-table-column>
            <a-table-column title="状态" :width="100">
              <template #cell="{ record: trace }">
                <a-tag
                  :color="
                    statusColor(trace.degraded ? 'degraded' : 'completed')
                  "
                >
                  {{ trace.degraded ? '降级' : '正常' }}
                </a-tag>
              </template>
            </a-table-column>
            <a-table-column title="时间" :width="180">
              <template #cell="{ record: trace }">
                {{ formatDate(trace.created_at) }}
              </template>
            </a-table-column>
            <a-table-column title="操作" :width="180">
              <template #cell="{ record: trace }">
                <RouterLink
                  :to="`/traces/${trace.trace_id}`"
                  custom
                  v-slot="{ href, navigate }"
                >
                  <a-button type="text" :href="href" @click="navigate">
                    查看
                  </a-button>
                </RouterLink>
              </template>
            </a-table-column>
          </template>
        </a-table>
      </div>
      <div v-if="hasMore" class="load-more">
        <a-button
          :disabled="loading"
          @click="load(false)"
          type="secondary"
          html-type="button"
        >
          加载更多
        </a-button>
      </div>
    </div>
  </div>
</template>
