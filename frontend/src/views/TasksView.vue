<script setup lang="ts">
import { useRoute } from 'vue-router'
import { useCursorList } from '@/composables/useCursorList'
import { api, normalizeApiError } from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Empty as AEmpty,
  Message,
  Progress as AProgress,
  Spin as ASpin,
  Table as ATable,
  TableColumn as ATableColumn,
  Tag as ATag,
} from '@arco-design/web-vue'

import { Activity, RefreshCw, XCircle } from 'lucide-vue-next'

import { statusColor } from '@/utils/status'
import { useTeamStore } from '@/stores/team'
import type { IngestionRun } from '@/types/api'
import { formatDate, shortId, statusLabel } from '@/utils/format'

const team = useTeamStore()
const route = useRoute()
const {
  items: items,
  loading,
  error,
  hasMore,
  load,
} = useCursorList<IngestionRun>(
  () => team.selectedTeamId ? JSON.stringify([team.selectedTeamId, route?.query.kbId || null]) : null,
  (scope, cursor) => { const [teamId, kbId] = JSON.parse(scope); return api.listIngestions(teamId, cursor, 20, kbId || undefined) },
)

const activeStatuses = new Set(['queued', 'running', 'building', 'parsing', 'prepared'])

async function retry(run: IngestionRun): Promise<void> {
  if (!team.selectedTeamId) return
  try {
    await api.retryIngestion(team.selectedTeamId, run.id)
    Message.success('任务已重新排队')
    await load()
  } catch (caught) {
    error.value = normalizeApiError(caught)
  }
}

async function cancel(run: IngestionRun): Promise<void> {
  if (!team.selectedTeamId) return
  try {
    await api.cancelIngestion(team.selectedTeamId, run.id)
    Message.success('任务已取消')
    await load()
  } catch (caught) {
    error.value = normalizeApiError(caught)
  }
}
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2>任务中心</h2>
        <p>查看解析、切分、向量化和索引任务的处理进度。<span v-if="route?.query.kbId">（已按当前知识库筛选）</span></p>
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

    <div v-if="loading && !items.length" class="panel loading-state">
      <a-spin />
      <span>正在加载任务</span>
    </div>
    <a-empty v-else-if="!items.length" class="page-empty">
      <template #image><Activity :size="28" /></template>
      <h3>暂无任务</h3>
      <p>上传文档后，任务会出现在这里。</p>
    </a-empty>
    <div v-else class="panel">
      <div class="table-wrap">
        <a-table
          :data="items"
          :pagination="false"
          row-key="id"
          :bordered="false"
          :scroll="{ x: 960 }"
        >
          <template #columns>
            <a-table-column title="任务">
              <template #cell="{ record: run }">
                <RouterLink :to="`/tasks/${run.id}`">
                  <strong>{{ shortId(run.id) }}</strong>
                </RouterLink>
                <span class="cell-subtitle">
                  版本 {{ shortId(run.document_version_id) }}
                </span>
              </template>
            </a-table-column>
            <a-table-column title="阶段 / 进度">
              <template #cell="{ record: run }">
                <span>{{ run.current_stage ? statusLabel(run.current_stage) : '等待调度' }}</span>
                <span class="cell-subtitle">{{ run.stage_progress_pct }}%</span>
                <a-progress
                  :percent="
                    Math.max(
                      0,
                      Math.min(
                        1,
                        Math.min(100, Math.max(0, run.stage_progress_pct)) /
                          100,
                      ),
                    )
                  "
                  :show-text="false"
                  size="small"
                ></a-progress>
              </template>
            </a-table-column>
            <a-table-column title="状态" :width="100">
              <template #cell="{ record: run }">
                <a-tag :color="statusColor(run.status)">
                  {{ statusLabel(run.status) }}
                </a-tag>
              </template>
            </a-table-column>
            <a-table-column title="失败原因">
              <template #cell="{ record: run }">
                <span v-if="run.error_code" class="danger-text">
                  {{ run.error_code }}
                </span>
                <span v-else class="muted-text">—</span>
              </template>
            </a-table-column>
            <a-table-column title="创建时间" :width="180">
              <template #cell="{ record: run }">
                {{ formatDate(run.created_at) }}
              </template>
            </a-table-column>
            <a-table-column title="操作" :width="180">
              <template #cell="{ record: run }">
                <div class="row-actions">
                  <a-button
                    v-if="
                      run.retryable ||
                      run.status === 'failed' ||
                      run.status === 'cancelled'
                    "
                    :data-testid="`task-retry-${run.id}`"
                    @click="retry(run)"
                    type="text"
                    html-type="button"
                  >
                    <RefreshCw :size="14" />
                    重试
                  </a-button>
                  <a-button
                    v-if="activeStatuses.has(run.status)"
                    @click="cancel(run)"
                    type="text"
                    html-type="button"
                    status="danger"
                  >
                    <XCircle :size="14" />
                    取消
                  </a-button>
                </div>
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
