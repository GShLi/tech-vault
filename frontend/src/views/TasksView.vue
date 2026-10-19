<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { Activity, RefreshCw, XCircle } from 'lucide-vue-next'
import { Message } from '@arco-design/web-vue'

import { api, ApiRequestError } from '@/api/client'
import StatusPill from '@/components/StatusPill.vue'
import { useTeamStore } from '@/stores/team'
import type { IngestionRun } from '@/types/api'
import { formatDate, shortId } from '@/utils/format'

const team = useTeamStore()
const items = ref<IngestionRun[]>([])
const loading = ref(false)
const error = ref<ApiRequestError | null>(null)
const nextCursor = ref<string | null>(null)
const hasMore = ref(false)

const activeStatuses = new Set(['queued', 'running', 'building', 'parsing'])

async function load(reset = true): Promise<void> {
  if (!team.selectedTeamId) return
  loading.value = true
  error.value = null
  try {
    const page = await api.listIngestions(
      team.selectedTeamId,
      reset ? null : nextCursor.value,
    )
    items.value = reset ? page.data : [...items.value, ...page.data]
    nextCursor.value = page.meta.next_cursor
    hasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loading.value = false
  }
}

async function retry(run: IngestionRun): Promise<void> {
  if (!team.selectedTeamId) return
  try {
    await api.retryIngestion(team.selectedTeamId, run.id)
    Message.success('任务已重新排队')
    await load()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  }
}

async function cancel(run: IngestionRun): Promise<void> {
  if (!team.selectedTeamId) return
  try {
    await api.cancelIngestion(team.selectedTeamId, run.id)
    Message.success('任务已取消')
    await load()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  }
}

onMounted(() => load())
watch(() => team.selectedTeamId, () => load())
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2>任务中心</h2>
        <p>查看解析、切分、向量化和索引任务的处理进度。</p>
      </div>
      <button class="secondary-button" type="button" :disabled="loading" @click="load()">
        <RefreshCw :size="16" />
        刷新
      </button>
    </div>

    <div v-if="error" class="error-banner" role="alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
      <button class="inline-link" type="button" @click="load()">重试</button>
    </div>

    <div v-if="loading && !items.length" class="panel loading-state">
      <a-spin />
      <span>正在加载任务</span>
    </div>
    <div v-else-if="!items.length" class="panel empty-state">
      <Activity :size="28" />
      <h3>暂无任务</h3>
      <p>上传文档或触发来源同步后，任务会出现在这里。</p>
    </div>
    <div v-else class="panel">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>任务</th>
              <th>阶段 / 进度</th>
              <th>状态</th>
              <th>失败原因</th>
              <th>创建时间</th>
              <th class="actions-column">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="run in items" :key="run.id">
              <td data-label="任务">
                <RouterLink :to="`/tasks/${run.id}`"><strong>{{ shortId(run.id) }}</strong></RouterLink>
                <span class="cell-subtitle">版本 {{ shortId(run.document_version_id) }}</span>
              </td>
              <td data-label="阶段 / 进度">
                <span>{{ run.current_stage || '等待调度' }}</span>
                <span class="cell-subtitle">{{ run.stage_progress_pct }}%</span>
                <div class="progress-track" aria-hidden="true">
                  <span :style="{ width: `${Math.min(100, Math.max(0, run.stage_progress_pct))}%` }" />
                </div>
              </td>
              <td data-label="状态"><StatusPill :status="run.status" /></td>
              <td data-label="失败原因">
                <span v-if="run.error_code" class="danger-text">{{ run.error_code }}</span>
                <span v-else class="muted-text">—</span>
              </td>
              <td data-label="创建时间">{{ formatDate(run.created_at) }}</td>
              <td data-label="操作">
                <div class="row-actions">
                  <button
                    v-if="run.retryable || run.status === 'failed' || run.status === 'cancelled'"
                    class="ghost-button"
                    :data-testid="`task-retry-${run.id}`"
                    type="button"
                    @click="retry(run)"
                  >
                    <RefreshCw :size="14" />
                    重试
                  </button>
                  <button
                    v-if="activeStatuses.has(run.status)"
                    class="ghost-button danger-text"
                    type="button"
                    @click="cancel(run)"
                  >
                    <XCircle :size="14" />
                    取消
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="hasMore" class="load-more">
        <button class="secondary-button" type="button" :disabled="loading" @click="load(false)">
          加载更多
        </button>
      </div>
    </div>
  </div>
</template>
